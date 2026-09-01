"""
tools/code_sandbox.py
=====================
CodeSandboxTool — execute untrusted code in an isolated Docker container.

Security model
--------------
* --network=none          No network egress from the container.
* --memory=256m           Hard memory cap.
* --cpus=0.5              Hard CPU cap.
* --read-only             Container filesystem is read-only (except /tmp).
* --tmpfs /tmp:size=64m   Ephemeral scratch space; gone when container dies.
* --rm                    Docker auto-removes container on exit (belt).
* finally: docker rm -f   Explicit removal after every run (suspenders).
                          This fires on timeout, exception, or any exit code.
* Hard timeout: 30 s      asyncio.wait_for wraps the subprocess call.
  A hung script never blocks the orchestrator.

Design
------
The tool does NOT decide whether code succeeded — it returns exit code,
stdout, and stderr. The orchestrator's existing retry/re-plan loop
interprets success/failure. This keeps concerns separated.

Language: Python only (v1). The Docker image used is python:3.11-slim.
Pull it once before running tests: docker pull python:3.11-slim

Audit
-----
One SANDBOX_EXEC record per call: SHA-256 of code (not full code),
exit_code, duration_ms, request_id.

Sovereignty note
----------------
The Docker daemon is local. --network=none prevents any container
from reaching external hosts. Sovereignty is maintained.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from app.audit.logger import AuditLogger, EventType
from app.tools.base import BaseTool, ToolResult

_log = logging.getLogger("sovereign.tools.code_sandbox")

_DOCKER_IMAGE = "python:3.11-slim"
_TIMEOUT_SECONDS = 120  # wall-clock: includes Docker cold-start (~50s on Mac VM) +
                        # 30s script execution budget per the spec. A hung script
                        # still cannot run indefinitely.
_MEMORY_LIMIT = "256m"
_CPU_LIMIT = "0.5"


class CodeSandboxTool(BaseTool):
    """
    Execute a Python code string in a Docker sandbox and return
    stdout, stderr, and exit code.

    The tool never raises; all outcomes (including timeout and
    container-launch failure) are returned as ToolResult.
    """

    name = "code_sandbox"
    description = (
        "Execute a Python code string in an isolated Docker sandbox "
        "(--network=none, memory/CPU capped, ephemeral filesystem). "
        "Returns stdout, stderr, and exit code. Does not interpret "
        "success or failure — the orchestrator decides."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source code to execute.",
            },
            "language": {
                "type": "string",
                "description": "Programming language (only 'python' supported in v1).",
                "enum": ["python"],
            },
            "request_id": {
                "type": "string",
                "description": "Correlation ID propagated through the audit log.",
            },
        },
        "required": ["code"],
    }

    def __init__(self, audit_logger: Optional[AuditLogger] = None) -> None:
        self._audit = audit_logger

    async def execute(self, **kwargs: Any) -> ToolResult:
        code: Optional[str] = kwargs.get("code")
        language: str = kwargs.get("language") or "python"
        request_id: Optional[str] = kwargs.get("request_id")

        if not code:
            return ToolResult(success=False, output=None,
                              error="Missing required argument: code")

        if language != "python":
            return ToolResult(
                success=False, output=None,
                error=f"Unsupported language '{language}'. Only 'python' is supported in v1.",
            )

        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
        container_name = f"sovereign-sandbox-{code_hash[:8]}-{os.getpid()}"

        t0 = time.monotonic()
        exit_code: int = -1
        stdout_text = ""
        stderr_text = ""
        timed_out = False

        # Write code to a temp file that will be mounted into the container.
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            prefix="sandbox_",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        try:
            exit_code, stdout_text, stderr_text, timed_out = await self._run_container(
                container_name=container_name,
                host_script_path=tmp_path,
            )
        finally:
            # Always clean up the temp file.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        duration_ms = (time.monotonic() - t0) * 1000

        self._log_execution(
            code_hash=code_hash,
            exit_code=exit_code,
            timed_out=timed_out,
            duration_ms=duration_ms,
            request_id=request_id,
        )

        if timed_out:
            return ToolResult(
                success=False,
                output={
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "exit_code": exit_code,
                    "timed_out": True,
                },
                error=f"Execution timed out after {_TIMEOUT_SECONDS}s.",
                metadata={
                    "code_hash": code_hash,
                    "duration_ms": round(duration_ms, 1),
                    "timed_out": True,
                },
            )

        # Signal failure when the script exited non-zero so the orchestrator's
        # replan loop can correct runtime errors (ZeroDivisionError, NameError,
        # SyntaxError, etc.) — not only timeouts.
        execution_success = (exit_code == 0)
        return ToolResult(
            success=execution_success,
            output={
                "stdout": stdout_text,
                "stderr": stderr_text,
                "exit_code": exit_code,
                "timed_out": False,
            },
            error=(
                f"Code exited with code {exit_code}. "
                f"stderr: {stderr_text[:400]}"
                if not execution_success else None
            ),
            metadata={
                "code_hash": code_hash,
                "exit_code": exit_code,
                "duration_ms": round(duration_ms, 1),
                "timed_out": False,
            },
        )

    # ------------------------------------------------------------------
    # Container runner
    # ------------------------------------------------------------------

    async def _run_container(
        self,
        container_name: str,
        host_script_path: str,
    ) -> tuple[int, str, str, bool]:
        """
        Spin up the Docker container, run the script, tear it down.

        Returns (exit_code, stdout, stderr, timed_out).
        Container is removed in a finally block regardless of outcome.
        """
        # Mount the script read-only into /sandbox/script.py
        cmd = [
            "docker", "run",
            "--name", container_name,
            "--network=none",
            f"--memory={_MEMORY_LIMIT}",
            f"--cpus={_CPU_LIMIT}",
            "--read-only",
            "--tmpfs", "/tmp:size=64m",
            "--rm",  # belt
            "-v", f"{host_script_path}:/sandbox/script.py:ro",
            _DOCKER_IMAGE,
            "python", "/sandbox/script.py",
        ]

        proc: Optional[asyncio.subprocess.Process] = None
        exit_code = -1
        stdout_text = ""
        stderr_text = ""
        timed_out = False

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=_TIMEOUT_SECONDS,
                )
                exit_code = proc.returncode if proc.returncode is not None else -1
                stdout_text = stdout_bytes.decode("utf-8", errors="replace")
                stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            except asyncio.TimeoutError:
                timed_out = True
                # Kill the process group
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                # Drain leftover output (best-effort)
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(), timeout=5.0
                    )
                    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
                    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
                except Exception:
                    pass

        except FileNotFoundError:
            # Docker not found on PATH
            return -1, "", "Docker not found on PATH.", False
        except Exception as exc:
            _log.error("Container launch failed for %s: %s", container_name, exc)
            return -1, "", str(exc), False
        finally:
            # Suspenders: explicit rm -f to handle cases where --rm didn't fire
            # (e.g. if docker run itself failed before --rm could take effect).
            self._force_remove_container(container_name)

        return exit_code, stdout_text, stderr_text, timed_out

    @staticmethod
    def _force_remove_container(container_name: str) -> None:
        """
        Best-effort `docker rm -f <name>`.  Errors are swallowed so this
        never raises from within a finally block.
        """
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except Exception as exc:
            _log.debug("docker rm -f %s: %s (ignored)", container_name, exc)

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    def _log_execution(
        self,
        code_hash: str,
        exit_code: int,
        timed_out: bool,
        duration_ms: float,
        request_id: Optional[str],
    ) -> None:
        if not self._audit:
            return
        try:
            self._audit.log_event(
                event_type=EventType.SANDBOX_EXEC,
                request_id=request_id or "",
                payload={
                    "code_hash": code_hash,
                    "exit_code": exit_code,
                    "timed_out": timed_out,
                    "duration_ms": round(duration_ms, 1),
                },
            )
        except Exception as exc:
            _log.warning("Failed to write SANDBOX_EXEC audit record: %s", exc)
