#!/usr/bin/env python3
"""
scripts/verify_memory_budget.py
================================
Repeatable memory math diagnostic for the Sovereign Workbench.

Usage
-----
    cd sovereign-workbench
    source .venv/bin/activate
    python scripts/verify_memory_budget.py

Output
------
Prints:
  - Raw GPU/memory detection result
  - Per-modality model selection with individual VRAM estimates
  - Cumulative total vs. machine total RAM
  - PASS / FAIL verdict with a clear explanation

This script is a shareable, repeatable artifact that replaces ad-hoc
shell one-liners.  Run it first on the development machine, then on the
venue/demo machine before demo day.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── Make sure the project root is on sys.path ──────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def _bar(value: int, total: int, width: int = 40) -> str:
    filled = int(width * min(value, total) / max(total, 1))
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def main() -> int:
    print()
    print("=" * 64)
    print("  Sovereign Workbench — Memory Budget Verification")
    print("=" * 64)

    # ── 1. Hardware detection ──────────────────────────────────────────
    try:
        from app.hardware.gpu_detect import detect_gpu
    except ImportError as exc:
        print(f"\n[ERROR] Could not import gpu_detect: {exc}")
        print("Make sure you are running from the project root with the venv active.")
        return 1

    gpu_info = detect_gpu()
    total_mb = gpu_info["total_vram_mb"]
    free_mb = gpu_info["free_vram_mb"]
    device = gpu_info["device_name"] or "Unknown / CPU only"

    print()
    print(f"  Device      : {device}")
    print(f"  Total RAM   : {total_mb:,} MB  ({total_mb / 1024:.1f} GB)")
    print(f"  Effective   : {free_mb:,} MB  (50% of pool on Apple Silicon; free VRAM on NVIDIA)")
    print(f"  GPU avail   : {gpu_info['gpu_available']}")
    print()

    # ── 2. Tier resolver ───────────────────────────────────────────────
    try:
        from app.hardware.tier_resolver import resolve_startup_models
        from app.models.ollama_client import MODEL_REGISTRY
    except ImportError as exc:
        print(f"[ERROR] Could not import tier_resolver: {exc}")
        return 1

    print("  Running tier resolver …")
    resolved = resolve_startup_models()  # no audit_logger for this script

    print()
    print("  Selected models:")
    print(f"  {'Modality':<12}  {'Name':<30}  {'Tag':<40}  {'Est VRAM':>10}")
    print("  " + "-" * 100)

    cumulative_mb = 0
    rows = []
    for modality, name in resolved.items():
        entry = MODEL_REGISTRY.get(name, {})
        est_mb = entry.get("est_vram_mb", 0)
        tag = entry.get("ollama_tag", "?")
        tier = entry.get("tier", "?")
        cumulative_mb += est_mb
        rows.append((modality, name, tag, tier, est_mb, cumulative_mb))
        print(f"  {modality:<12}  {name:<30}  {tag:<40}  {est_mb:>8,} MB")

    print("  " + "-" * 100)
    print(f"  {'TOTAL':<12}  {'':30}  {'':40}  {cumulative_mb:>8,} MB")
    print()

    # ── 3. Verdict ─────────────────────────────────────────────────────
    # Use total_mb (full physical RAM) as the hard ceiling.
    # On Apple Silicon the OS + apps compete for the same pool.
    fits_in_ram = cumulative_mb <= total_mb
    # Conservative check: fits if <= 80% of total (leaves headroom for OS)
    fits_with_headroom = cumulative_mb <= int(total_mb * 0.80)
    headroom_pct = 80

    bar = _bar(cumulative_mb, total_mb)
    pct_used = 100 * cumulative_mb / max(total_mb, 1)
    print(f"  {bar}  {pct_used:.0f}% of {total_mb:,} MB")
    print()

    if fits_with_headroom:
        print("  VERDICT: PASS ✅")
        print(f"  Combined estimate ({cumulative_mb:,} MB) is within {headroom_pct}% of")
        print(f"  total RAM ({total_mb:,} MB).  Safe to run all 4 models concurrently")
        print(f"  on this machine (Ollama will manage paging, but shouldn't evict).")
    elif fits_in_ram:
        print("  VERDICT: MARGINAL ⚠️")
        print(f"  Combined estimate ({cumulative_mb:,} MB) fits in total RAM ({total_mb:,} MB)")
        print(f"  but exceeds the 80% safety threshold ({int(total_mb * 0.80):,} MB).")
        print(f"  Ollama WILL compete with the OS for memory.  Test live with all 4")
        print(f"  models loaded simultaneously and watch for eviction/reload events.")
    else:
        print("  VERDICT: FAIL ❌")
        print(f"  Combined estimate ({cumulative_mb:,} MB) EXCEEDS total physical RAM")
        print(f"  ({total_mb:,} MB) by {cumulative_mb - total_mb:,} MB.")
        print(f"  Running all 4 models simultaneously will trigger OS-level paging.")
        print()
        print("  Resolution options:")
        print("  (a) Pull qwen2.5-coder:7b and use FORCE_TIER=small (need 7b pulled)")
        print(f"      Small-tier total would be: 4500+4700+3000+1200 = 13,400 MB — fits")
        print("  (b) Use FORCE_TIER=small in the environment before starting the server")
        print("  (c) Verify venue machine has dedicated GPU/more RAM and re-run there")
        print()
        print("  To pull the 7b coder model:")
        print("    ollama pull qwen2.5-coder:7b-instruct-q4_K_M")

    print()
    print("=" * 64)

    return 0 if fits_in_ram else 1


if __name__ == "__main__":
    sys.exit(main())
