"""
hardware/gpu_detect.py
======================
Platform-aware GPU / unified-memory detection using only stdlib
``subprocess``.  No heavy dependencies (no torch, no pynvml).

Three detection paths
---------------------
1. **macOS (Apple Silicon):** ``sysctl hw.memsize`` → total unified memory.
   50 % of total RAM is reported as ``free_vram_mb`` — a conservative
   budget that reserves headroom for the OS and other apps.
   ``gpu_available = True`` so the tier resolver uses the budget instead
   of falling back to the zero-budget CPU path.

2. **Linux/Windows + NVIDIA present:** ``nvidia-smi`` CSV query (unchanged
   from the original implementation).

3. **Neither detected:** Returns the zeroed :data:`_NO_GPU` dict and the
   tier resolver falls back to the smallest (CPU-friendly) model tier.

Return schema
-------------
{
    "gpu_available" : bool,
    "total_vram_mb" : int,   # 0 when no GPU / unified memory
    "free_vram_mb"  : int,   # effective budget (see per-path notes)
    "device_name"   : str,   # "" when no GPU
}

Sovereignty note
----------------
This module never opens a socket.  All subprocess calls launch only
local binaries (``sysctl``, ``nvidia-smi``).
"""

from __future__ import annotations

import logging
import subprocess
from typing import TypedDict

_log = logging.getLogger("sovereign.hardware.gpu_detect")


class GpuInfo(TypedDict):
    gpu_available: bool
    total_vram_mb: int
    free_vram_mb: int
    device_name: str


_NO_GPU: GpuInfo = {
    "gpu_available": False,
    "total_vram_mb": 0,
    "free_vram_mb": 0,
    "device_name": "",
}


# ---------------------------------------------------------------------------
# macOS / Apple Silicon path
# ---------------------------------------------------------------------------


def _detect_apple_silicon() -> GpuInfo:
    """
    Query total unified memory via ``sysctl hw.memsize`` (macOS only).

    Apple Silicon GPUs share memory with the CPU.  There is no separate
    "free VRAM" counter — the GPU competes with the OS, apps, and the CPU
    for the same physical pool.

    We report **50 % of total RAM** as ``free_vram_mb`` (the effective
    budget passed to the tier resolver).  The tier resolver then applies
    its own 85 % headroom on top, so the actual model-selection budget
    is ≈ 42.5 % of installed RAM — conservative enough to avoid OOM
    while still allowing mid-tier models on a 16 GB machine.

    Returns :data:`_NO_GPU` if ``sysctl`` fails for any reason.
    """
    try:
        result = subprocess.run(
            ["sysctl", "hw.memsize"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            _log.warning(
                "sysctl hw.memsize failed (rc=%d) — falling back to CPU tier",
                result.returncode,
            )
            return _NO_GPU

        # Typical output: "hw.memsize: 17179869184"
        raw_bytes = int(result.stdout.strip().split(":")[-1].strip())
        total_mb = raw_bytes // (1024 * 1024)

        # 50 % budget: OS + background apps + other processes own the other half.
        budget_mb = total_mb // 2

        _log.info(
            "macOS unified memory: total=%d MB  effective_budget=%d MB (50%% of pool)",
            total_mb,
            budget_mb,
        )
        return {
            "gpu_available": True,
            "total_vram_mb": total_mb,
            "free_vram_mb": budget_mb,
            "device_name": "Apple Silicon (unified memory)",
        }

    except (FileNotFoundError, ValueError, OSError) as exc:
        _log.warning("macOS memory detection failed (%s) — falling back to CPU tier", exc)
        return _NO_GPU


# ---------------------------------------------------------------------------
# NVIDIA / Linux path (original implementation, unchanged)
# ---------------------------------------------------------------------------


def _run_nvidia_smi() -> str:
    """
    Execute ``nvidia-smi`` and return raw stdout.

    Raises
    ------
    FileNotFoundError  if nvidia-smi is not on PATH.
    RuntimeError       if nvidia-smi exits non-zero.
    """
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.total,memory.free,name",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=10,     # generous; never blocks indefinitely
        check=False,    # we handle non-zero exit ourselves
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"nvidia-smi exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _detect_nvidia() -> GpuInfo:
    """
    Detect the first available NVIDIA GPU via ``nvidia-smi``.

    Returns :data:`_NO_GPU` on any error (no GPU, no driver, no nvidia-smi).
    """
    try:
        raw = _run_nvidia_smi()
        if not raw:
            _log.warning("nvidia-smi returned empty output — assuming no GPU")
            return _NO_GPU

        # nvidia-smi emits one CSV line per GPU; we only need the first.
        first_line = raw.splitlines()[0]
        parts = [p.strip() for p in first_line.split(",")]
        if len(parts) < 3:
            raise ValueError(f"Unexpected nvidia-smi CSV format: {first_line!r}")

        total_mb = int(parts[0])
        free_mb = int(parts[1])
        device_name = parts[2]

        _log.info(
            "GPU detected: %s  total=%d MB  free=%d MB",
            device_name,
            total_mb,
            free_mb,
        )
        return {
            "gpu_available": True,
            "total_vram_mb": total_mb,
            "free_vram_mb": free_mb,
            "device_name": device_name,
        }

    except FileNotFoundError:
        _log.warning("nvidia-smi not found — no GPU available, falling back to CPU tier")
        return _NO_GPU
    except (RuntimeError, ValueError, OSError) as exc:
        _log.warning("GPU detection failed (%s) — falling back to CPU tier", exc)
        return _NO_GPU


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def detect_gpu() -> GpuInfo:
    """
    Detect the best available compute memory budget for the current platform.

    Branches
    --------
    * macOS  → :func:`_detect_apple_silicon` (``sysctl hw.memsize``)
    * Other  → :func:`_detect_nvidia` (``nvidia-smi``)
    * Either fails → :data:`_NO_GPU` CPU fallback

    Returns a :class:`GpuInfo` dict.  Never raises — the caller's startup
    path remains unconditional.
    """
    import platform as _platform

    system = _platform.system()

    if system == "Darwin":
        return _detect_apple_silicon()

    # Linux, Windows, or unknown → try nvidia-smi
    return _detect_nvidia()
