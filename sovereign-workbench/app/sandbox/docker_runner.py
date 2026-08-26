"""
app/sandbox/docker_runner.py
============================
Low-level Docker execution layer.

Sole responsibility
-------------------
Accept a workspace Path (containing main.py), spin up an isolated
Docker container, capture stdout / stderr / exit_code, and return
a raw result object.

Isolation guarantees applied here
----------------------------------
  --rm                         container auto-removed on exit
  --network=none               zero outbound/inbound network
  --memory / --memory-swap     hard memory cap (no swap)
  --cpus                       CPU quota
  --pids-limit                 fork-bomb prevention
  --security-opt no-new-privileges  no privilege escalation
  --read-only                  container FS is read-only
  --tmpfs /tmp:size=32m        writable /tmp for Python internals
  -v workspace:/sandbox:ro     ONLY the temp workspace is mounted, read-only

What this module does NOT touch
---------------------------------
  - Ollama / OllamaClient
  - Model Registry
  - Model Router
  - Orchestrator
  - RAG / Qdrant
  - AuditLogger
  - Any existing sovereign workbench module
"""

from __future__ import annotations

import asyncio
import logging
import platform
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger("sovereign.sandbox.docker_runner")

# ── Configuration constants ───────────────────────────────────────────────

SANDBOX_IMAGE: str = "sovereign-sandbox-python"
DEFAULT_TIMEOUT: int = 10       # seconds
MEMORY_LIMIT: str = "128m"
CPU_LIMIT: str = "0.5"
PIDS_LIMIT: int = 64


# ── Result dataclass ─────────────────────────────────────────────────────


@dataclass
class RawRunResult:
    """Raw execution output from the Docker container."""

    stdout: str
    stderr: str
    exit_code: int   # 0 = success | 124 = timed_out | -1 = runner error
    timed_out: bool


# ── Path helpers ─────────────────────────────────────────────────────────


def _host_path_for_docker(path: Path) -> str:
    """
    Return a path string that Docker on this host understands for -v mounts.

    On Windows + Docker Desktop (WSL2 backend):
        C:\\Users\\... → /c/Users/...   (Docker Desktop accepts this)
    On Linux/macOS:
        /tmp/... → /tmp/...  (unchanged)
    """
    abs_path = path.resolve()
    if platform.system() == "Windows":
        drive = abs_path.drive.rstrip(":").lower()          # "C:" → "c"
        rest = str(abs_path)[len(abs_path.drive):]          # "\Users\foo"
        rest = rest.replace("\\", "/")                      # "/Users/foo"
        return f"/{drive}{rest}"                            # "/c/Users/foo"
    return str(abs_path)


# ── Core runner ──────────────────────────────────────────────────────────


async def run_code_in_docker(
    workspace: Path,
    timeout: int = DEFAULT_TIMEOUT,
) -> RawRunResult:
    """
    Execute ``/sandbox/main.py`` inside a hardened Docker container.

    Parameters
    ----------
    workspace:
        Host path to a temporary directory that contains exactly one file:
        ``main.py``.  This directory is bind-mounted read-only into the
        container at ``/sandbox``.
    timeout:
        Seconds before the container is killed (SIGKILL).

    Returns
    -------
    :class:`RawRunResult` — never raises; all errors are captured inside it.
    """
    docker_workspace = _host_path_for_docker(workspace)

    cmd = [
        "docker", "run",
        # ── Lifecycle ───────────────────────────────────────────────────
        "--rm",                                  # auto-remove after exit
        # ── Network ─────────────────────────────────────────────────────
        "--network=none",                        # complete network isolation
        # ── Resources ───────────────────────────────────────────────────
        f"--memory={MEMORY_LIMIT}",              # hard memory cap
        f"--memory-swap={MEMORY_LIMIT}",         # disable swap
        f"--cpus={CPU_LIMIT}",                   # CPU quota
        f"--pids-limit={PIDS_LIMIT}",            # prevent fork bombs
        # ── Security ────────────────────────────────────────────────────
        "--security-opt", "no-new-privileges",   # no privilege escalation
        "--read-only",                           # container FS is read-only
        "--tmpfs", "/tmp:size=32m",              # writable /tmp for Python
        # ── Code mount ──────────────────────────────────────────────────
        "-v", f"{docker_workspace}:/sandbox:ro", # code only, read-only
        # ── Image ───────────────────────────────────────────────────────
        SANDBOX_IMAGE,
    ]

    _log.debug("Launching container: %s", " ".join(cmd))

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
                timeout=float(timeout),
            )
            exit_code = proc.returncode if proc.returncode is not None else -1

        except asyncio.TimeoutError:
            timed_out = True
            _log.warning(
                "Sandbox timed out after %ds — sending SIGKILL to container", timeout
            )
            try:
                proc.kill()
                await proc.communicate()          # drain to avoid zombie
            except ProcessLookupError:
                pass
            stdout_bytes = b""
            stderr_bytes = b"Execution timed out."
            exit_code = 124

    except FileNotFoundError:
        # 'docker' binary not found on PATH
        _log.error(
            "docker binary not found. Is Docker Desktop running and on PATH?"
        )
        return RawRunResult(
            stdout="",
            stderr=(
                "Docker is not available. "
                "Please start Docker Desktop and ensure it is on PATH."
            ),
            exit_code=-1,
            timed_out=False,
        )

    except Exception as exc:          # noqa: BLE001
        _log.error("DockerRunner unexpected error: %s", exc)
        return RawRunResult(
            stdout="",
            stderr=f"Sandbox runner internal error: {exc}",
            exit_code=-1,
            timed_out=False,
        )

    _log.debug(
        "Container exited — exit_code=%d  timed_out=%s  "
        "stdout_len=%d  stderr_len=%d",
        exit_code, timed_out, len(stdout_bytes), len(stderr_bytes),
    )

    return RawRunResult(
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        exit_code=exit_code,
        timed_out=timed_out,
    )
