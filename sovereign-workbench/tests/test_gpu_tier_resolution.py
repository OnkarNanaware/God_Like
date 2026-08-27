"""
tests/test_gpu_tier_resolution.py
==================================
Dedicated test suite for GPU detection and tier resolution.

All tests are fully offline — no real GPU, no nvidia-smi, no sysctl
required.  Platform-specific code is mocked at the subprocess level so
tests pass identically on macOS, Linux, and Windows CI.

Coverage
--------
macOS detection
  1. sysctl hw.memsize succeeds → correct total/budget in MB, gpu_available=True
  2. sysctl returns non-zero exit → _NO_GPU fallback
  3. sysctl stdout malformed → _NO_GPU fallback (ValueError caught)
  4. sysctl binary missing → _NO_GPU fallback (FileNotFoundError caught)
  5. sysctl succeeds on 8 GB machine → 4096 MB budget

NVIDIA detection
  6. nvidia-smi parses CSV → correct total/free/name, gpu_available=True
  7. nvidia-smi missing → _NO_GPU (regression: original behaviour preserved)
  8. nvidia-smi exits non-zero → _NO_GPU fallback
  9. nvidia-smi empty output → _NO_GPU fallback

Platform dispatch
 10. platform.system()=="Darwin"  → _detect_apple_silicon called
 11. platform.system()=="Linux"   → _detect_nvidia called
 12. platform.system()=="Windows" → _detect_nvidia called

Tier resolver with macOS output
 13. 16 GB Mac → budget ~6963 MB → qwen25_7b_instruct selected for text
 14. 8 GB Mac  → budget ~3481 MB → smallest valid model selected
 15. macOS sysctl failure → _NO_GPU → all modalities resolve (smallest)
 16. embedding always resolves to bge_m3
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subprocess_result(stdout: str, returncode: int = 0) -> MagicMock:
    """Build a mock subprocess.CompletedProcess."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = ""
    return m


# ---------------------------------------------------------------------------
# macOS / Apple Silicon detection (tests 1-5)
# ---------------------------------------------------------------------------


class TestDetectAppleSilicon:
    def _fn(self):
        from app.hardware.gpu_detect import _detect_apple_silicon
        return _detect_apple_silicon

    def test_16gb_success(self):
        """16 GB machine: total=16384 MB, budget=8192 MB, gpu_available=True."""
        fn = self._fn()
        with patch("subprocess.run", return_value=_make_subprocess_result("hw.memsize: 17179869184\n")):
            info = fn()
        assert info["gpu_available"] is True
        assert info["total_vram_mb"] == 16384
        assert info["free_vram_mb"] == 8192   # 50% of 16384
        assert "Apple Silicon" in info["device_name"]

    def test_sysctl_nonzero_exit_returns_no_gpu(self):
        """sysctl exits non-zero → _NO_GPU."""
        fn = self._fn()
        with patch("subprocess.run", return_value=_make_subprocess_result("", returncode=1)):
            info = fn()
        assert info["gpu_available"] is False
        assert info["total_vram_mb"] == 0
        assert info["free_vram_mb"] == 0

    def test_sysctl_malformed_stdout_returns_no_gpu(self):
        """sysctl prints unparseable garbage → _NO_GPU, no exception raised."""
        fn = self._fn()
        with patch("subprocess.run", return_value=_make_subprocess_result("hw.memsize: GARBAGE\n")):
            info = fn()
        assert info["gpu_available"] is False
        assert info["device_name"] == ""

    def test_sysctl_binary_missing_returns_no_gpu(self):
        """sysctl not on PATH → _NO_GPU gracefully (FileNotFoundError caught)."""
        fn = self._fn()
        with patch("subprocess.run", side_effect=FileNotFoundError("sysctl")):
            info = fn()
        assert info["gpu_available"] is False

    def test_8gb_machine_budget_is_half(self):
        """8 GB machine (8589934592 bytes) → total=8192, budget=4096."""
        fn = self._fn()
        with patch("subprocess.run", return_value=_make_subprocess_result("hw.memsize: 8589934592\n")):
            info = fn()
        assert info["gpu_available"] is True
        assert info["total_vram_mb"] == 8192
        assert info["free_vram_mb"] == 4096


# ---------------------------------------------------------------------------
# NVIDIA detection regression tests (tests 6-9)
# ---------------------------------------------------------------------------


class TestDetectNvidia:
    def _fn(self):
        from app.hardware.gpu_detect import _detect_nvidia
        return _detect_nvidia

    def test_parses_csv_correctly(self):
        """nvidia-smi CSV → gpu_available=True with correct values."""
        fn = self._fn()
        with patch("subprocess.run", return_value=_make_subprocess_result("24564, 20000, NVIDIA RTX 4090\n")):
            info = fn()
        assert info["gpu_available"] is True
        assert info["total_vram_mb"] == 24564
        assert info["free_vram_mb"] == 20000
        assert "4090" in info["device_name"]

    def test_nvidia_smi_missing_returns_no_gpu(self):
        """nvidia-smi not on PATH → _NO_GPU (original behaviour preserved)."""
        fn = self._fn()
        with patch("subprocess.run", side_effect=FileNotFoundError("nvidia-smi")):
            info = fn()
        assert info["gpu_available"] is False
        assert info["total_vram_mb"] == 0
        assert info["free_vram_mb"] == 0
        assert info["device_name"] == ""

    def test_nvidia_smi_nonzero_exit_returns_no_gpu(self):
        """nvidia-smi exits non-zero (driver error) → _NO_GPU."""
        fn = self._fn()
        with patch("subprocess.run", return_value=_make_subprocess_result("", returncode=6)):
            info = fn()
        assert info["gpu_available"] is False

    def test_nvidia_smi_empty_stdout_returns_no_gpu(self):
        """nvidia-smi succeeds but outputs nothing → _NO_GPU."""
        fn = self._fn()
        with patch("subprocess.run", return_value=_make_subprocess_result("")):
            info = fn()
        assert info["gpu_available"] is False


# ---------------------------------------------------------------------------
# Platform dispatch (tests 10-12)
# ---------------------------------------------------------------------------


class TestPlatformDispatch:
    def test_darwin_routes_to_apple_silicon(self):
        """detect_gpu() on Darwin must call _detect_apple_silicon, not _detect_nvidia."""
        from app.hardware.gpu_detect import detect_gpu
        mac_result = {
            "gpu_available": True, "total_vram_mb": 16384,
            "free_vram_mb": 8192, "device_name": "Apple Silicon (unified memory)",
        }
        with patch("platform.system", return_value="Darwin"):
            with patch("app.hardware.gpu_detect._detect_apple_silicon", return_value=mac_result) as mock_mac:
                with patch("app.hardware.gpu_detect._detect_nvidia") as mock_nv:
                    result = detect_gpu()
        mock_mac.assert_called_once()
        mock_nv.assert_not_called()
        assert result["device_name"] == "Apple Silicon (unified memory)"

    def test_linux_routes_to_nvidia(self):
        """detect_gpu() on Linux must call _detect_nvidia, not _detect_apple_silicon."""
        from app.hardware.gpu_detect import detect_gpu
        nv_result = {
            "gpu_available": False, "total_vram_mb": 0,
            "free_vram_mb": 0, "device_name": "",
        }
        with patch("platform.system", return_value="Linux"):
            with patch("app.hardware.gpu_detect._detect_apple_silicon") as mock_mac:
                with patch("app.hardware.gpu_detect._detect_nvidia", return_value=nv_result) as mock_nv:
                    detect_gpu()
        mock_nv.assert_called_once()
        mock_mac.assert_not_called()

    def test_windows_routes_to_nvidia(self):
        """detect_gpu() on Windows must call _detect_nvidia (sysctl does not exist)."""
        from app.hardware.gpu_detect import detect_gpu
        nv_result = {
            "gpu_available": False, "total_vram_mb": 0,
            "free_vram_mb": 0, "device_name": "",
        }
        with patch("platform.system", return_value="Windows"):
            with patch("app.hardware.gpu_detect._detect_apple_silicon") as mock_mac:
                with patch("app.hardware.gpu_detect._detect_nvidia", return_value=nv_result) as mock_nv:
                    detect_gpu()
        mock_nv.assert_called_once()
        mock_mac.assert_not_called()


# ---------------------------------------------------------------------------
# Tier resolver integration with macOS output (tests 13-16)
# ---------------------------------------------------------------------------


class TestTierResolverMacOS:
    def _mac_gpu_info(self, total_mb: int) -> dict:
        return {
            "gpu_available": True,
            "total_vram_mb": total_mb,
            "free_vram_mb": total_mb // 2,  # 50% budget
            "device_name": "Apple Silicon (unified memory)",
        }

    def test_16gb_mac_text_model_at_least_7b(self):
        """
        16 GB → 8192 MB budget → 6963 MB after 85% headroom.
        qwen25_7b_instruct (4500 MB) fits; must be selected (not emergency-smallest).
        """
        from app.hardware.tier_resolver import resolve_startup_models
        with patch("app.hardware.tier_resolver.detect_gpu", return_value=self._mac_gpu_info(16384)):
            resolved = resolve_startup_models()
        assert "text" in resolved
        from app.models.ollama_client import MODEL_REGISTRY
        assert resolved["text"] in MODEL_REGISTRY
        text_entry = MODEL_REGISTRY[resolved["text"]]
        assert text_entry.get("est_vram_mb", 0) >= 4000, (
            f"Expected ≥7b model for 16 GB Mac, got {text_entry['name']} "
            f"({text_entry.get('est_vram_mb')} MB)"
        )

    def test_8gb_mac_resolves_all_modalities(self):
        """8 GB Mac → all four modalities should still resolve to valid registry entries."""
        from app.hardware.tier_resolver import resolve_startup_models
        with patch("app.hardware.tier_resolver.detect_gpu", return_value=self._mac_gpu_info(8192)):
            resolved = resolve_startup_models()
        from app.models.ollama_client import MODEL_REGISTRY
        for mod, name in resolved.items():
            assert name in MODEL_REGISTRY, f"Modality={mod} resolved to unknown model {name}"

    def test_mac_sysctl_failure_gives_cpu_tier_fallback(self):
        """sysctl fails → _NO_GPU → tier resolver still resolves all modalities."""
        from app.hardware.tier_resolver import resolve_startup_models
        no_gpu = {"gpu_available": False, "total_vram_mb": 0, "free_vram_mb": 0, "device_name": ""}
        with patch("app.hardware.tier_resolver.detect_gpu", return_value=no_gpu):
            resolved = resolve_startup_models()
        assert "text" in resolved
        from app.models.ollama_client import MODEL_REGISTRY
        for mod, name in resolved.items():
            assert name in MODEL_REGISTRY, f"Modality={mod} resolved to unknown model {name}"

    def test_embedding_always_resolves_to_bge_m3(self):
        """bge_m3 must always be selected for the embedding modality on a Mac."""
        from app.hardware.tier_resolver import resolve_startup_models
        with patch("app.hardware.tier_resolver.detect_gpu", return_value=self._mac_gpu_info(16384)):
            resolved = resolve_startup_models()
        assert "embedding" in resolved
        assert resolved["embedding"] == "bge_m3", (
            f"Expected bge_m3 for embedding, got {resolved['embedding']}"
        )
