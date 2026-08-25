"""
hardware/gpu_detect.py
======================
Lightweight GPU detection using only stdlib ``subprocess``.

No heavy dependencies (no torch, no pynvml).  Calls ``nvidia-smi`` once;
if the binary is absent or returns nothing, returns a zeroed-out dict.

Return schema
-------------
{
    "gpu_available" : bool,
    "total_vram_mb" : int,   # 0 when no GPU
    "free_vram_mb"  : int,   # 0 when no GPU
    "device_name"   : str,   # "" when no GPU
}

Sovereignty note
----------------
This module never opens a socket.  ``subprocess.run`` only launches a
local binary (``nvidia-smi``).
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


def _run_nvidia_smi() -> str:
    """
    Execute ``nvidia-smi`` and return raw stdout.

    Raises
    ------
    FileNotFoundError  if nvidia-smi is not on PATH.
    subprocess.SubprocessError  for any other process error.
    """
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.total,memory.free,name",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=10,         # generous; never blocks indefinitely
        check=False,        # we handle non-zero exit ourselves
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"nvidia-smi exited {result.returncode}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def detect_gpu() -> GpuInfo:
    """
    Detect the first available NVIDIA GPU.

    Returns a :class:`GpuInfo` dict.  On any error (no GPU, no driver,
    no nvidia-smi) returns :data:`_NO_GPU` and logs a WARNING — it never
    raises so the caller's startup path remains unconditional.
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
