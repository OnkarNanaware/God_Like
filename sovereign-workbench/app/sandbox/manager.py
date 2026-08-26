"""
app/sandbox/manager.py
======================
High-level SandboxManager.

Sole responsibility
-------------------
1. Accept Python code (string) and an optional timeout.
2. Create a clean, isolated temporary workspace on disk.
3. Write the user's code to ``main.py`` inside that workspace.
4. Delegate container execution to DockerRunner.
5. Capture the structured result.
6. Unconditionally clean up the workspace (finally block).
7. Return a SandboxResult to the caller.

Isolation guarantees enforced here
------------------------------------
- Only the per-request temp dir is ever created or deleted.
- No project files, .env files, or Docker socket paths are touched.
- The workspace is deleted even if DockerRunner raises.

What this module does NOT touch
---------------------------------
  - Ollama / OllamaClient
  - Model Registry
  - Model Router / heuristics / llm_classifier
  - Orchestrator (plan→act→observe)
  - RAG / Qdrant
  - AuditLogger
  - Any existing sovereign workbench module
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from app.sandbox.docker_runner import DEFAULT_TIMEOUT, RawRunResult, run_code_in_docker

_log = logging.getLogger("sovereign.sandbox.manager")


# ── Result dataclass ─────────────────────────────────────────────────────


@dataclass
class SandboxResult:
    """Structured result returned by SandboxManager.execute()."""

    success: bool       # True iff exit_code == 0 and not timed_out
    stdout: str
    stderr: str
    exit_code: int      # 0 = success | 124 = timeout | -1 = internal error
    timed_out: bool
    duration_ms: float  # total wall-clock time including workspace I/O


# ── Manager ──────────────────────────────────────────────────────────────


class SandboxManager:
    """
    Lifecycle manager for a single sandboxed Python execution.

    Example
    -------
    ::

        manager = SandboxManager()
        result  = await manager.execute("print('hello')")
        print(result.stdout)   # "hello\\n"

    The manager is stateless — it can be reused for multiple requests.
    """

    async def execute(
        self,
        code: str,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> SandboxResult:
        """
        Execute *code* inside an isolated Docker container.

        Parameters
        ----------
        code:
            Python source code as a plain string.
        timeout:
            Maximum execution time in seconds (container is killed on expiry).

        Returns
        -------
        :class:`SandboxResult` — never raises; errors are returned inside it.
        """
        workspace: Path | None = None
        t0 = time.monotonic()

        try:
            # ── 1. Create temporary workspace ────────────────────────────
            # tempfile.mkdtemp creates a directory only the current OS user
            # can access (mode 700 on POSIX).  On Windows, it lands in
            # %TEMP% which is not the project directory.
            workspace = Path(tempfile.mkdtemp(prefix="sovereign_sandbox_"))
            _log.info("Sandbox workspace created: %s", workspace)

            # ── 2. Write user code ────────────────────────────────────────
            main_py = workspace / "main.py"
            main_py.write_text(code, encoding="utf-8")
            _log.info(
                "Wrote %d bytes to %s",
                len(code.encode("utf-8")),
                main_py,
            )

            # ── 3. Delegate to DockerRunner ───────────────────────────────
            raw: RawRunResult = await run_code_in_docker(workspace, timeout=timeout)

        except Exception as exc:         # noqa: BLE001
            _log.error("SandboxManager setup error: %s", exc)
            duration_ms = (time.monotonic() - t0) * 1000.0
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Sandbox setup error: {exc}",
                exit_code=-1,
                timed_out=False,
                duration_ms=round(duration_ms, 2),
            )

        finally:
            # ── 4. Clean up workspace unconditionally ─────────────────────
            if workspace is not None and workspace.exists():
                try:
                    shutil.rmtree(workspace)
                    _log.info("Sandbox workspace cleaned up: %s", workspace)
                except Exception as cleanup_exc:   # noqa: BLE001
                    _log.warning(
                        "Failed to clean up workspace %s: %s",
                        workspace,
                        cleanup_exc,
                    )

        duration_ms = (time.monotonic() - t0) * 1000.0
        success = (raw.exit_code == 0) and not raw.timed_out

        _log.info(
            "Sandbox execution complete — "
            "exit_code=%d  timed_out=%s  duration=%.0fms",
            raw.exit_code,
            raw.timed_out,
            duration_ms,
        )

        return SandboxResult(
            success=success,
            stdout=raw.stdout,
            stderr=raw.stderr,
            exit_code=raw.exit_code,
            timed_out=raw.timed_out,
            duration_ms=round(duration_ms, 2),
        )
