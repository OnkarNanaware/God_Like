"""
hardware/tier_resolver.py
=========================
Startup-time GPU-adaptive model selection.

Algorithm
---------
1. Detect free VRAM via ``gpu_detect.detect_gpu()``.
2. Apply a 15 % safety headroom: ``budget = free_vram * 0.85``.
3. For each *modality group* (text, code, vision, embedding) pick the
   **largest tier** whose ``est_vram_mb`` fits inside the remaining
   budget, consuming that much from the budget.
4. Return a mapping ``{modality → model_name}`` that callers (``main.py``,
   ``Router``) use to override defaults.

Manual override
---------------
Set the environment variable ``FORCE_TIER=small`` (or ``mid`` / ``large``
/ ``default``) to skip GPU detection and force that tier for every group.

Audit logging
-------------
Writes a ``model_resolution`` startup event via ``AuditLogger`` so every
deployment records which models were selected and why.

Sovereignty note
----------------
No sockets opened here.  ``detect_gpu`` only calls a local binary.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from app.hardware.gpu_detect import GpuInfo, detect_gpu
from app.models.ollama_client import MODEL_REGISTRY

_log = logging.getLogger("sovereign.hardware.tier_resolver")

# Safety headroom: keep 15 % of free VRAM as buffer for OS + driver overhead.
_HEADROOM = 0.85

# Tier ordering: largest first so we iterate from best to most conservative.
_TIER_ORDER = ["large", "mid", "small", "default"]

# Which modalities should the resolver manage?
_MANAGED_MODALITIES = ("text", "code", "vision", "embedding")


def _group_by_modality() -> dict[str, list[dict[str, Any]]]:
    """
    Group MODEL_REGISTRY entries by modality.

    Returns {modality: [entry, ...]} sorted within each group by
    est_vram_mb descending (largest first).
    """
    groups: dict[str, list[dict[str, Any]]] = {m: [] for m in _MANAGED_MODALITIES}
    for entry in MODEL_REGISTRY.values():
        modality = entry.get("modality", "")
        if modality in groups:
            groups[modality].append(entry)
    # Sort largest→smallest within each group
    for modality in groups:
        groups[modality].sort(key=lambda e: e.get("est_vram_mb", 0), reverse=True)
    return groups


def _pick_best_fit(
    candidates: list[dict[str, Any]],
    budget_mb: int,
    force_tier: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Choose the best model from *candidates* subject to VRAM constraints.

    Parameters
    ----------
    candidates:
        List of model entries for one modality, sorted largest-first.
    budget_mb:
        Remaining VRAM budget in MB.
    force_tier:
        If set, return the first entry matching that tier name (case-insensitive).
        Falls back to the smallest entry if the tier isn't found.

    Returns
    -------
    The chosen model entry dict, or ``None`` if *candidates* is empty.
    """
    if not candidates:
        return None

    if force_tier:
        forced = next(
            (e for e in candidates if e.get("tier", "").lower() == force_tier.lower()),
            None,
        )
        return forced if forced is not None else candidates[-1]  # smallest fallback

    # Pick the largest that fits inside the budget.
    for entry in candidates:  # already sorted largest→smallest
        if entry.get("est_vram_mb", 0) <= budget_mb:
            return entry

    # Nothing fits — return the smallest (will run slowly but at least works).
    _log.warning(
        "No model fits within budget=%d MB; selecting smallest as emergency fallback",
        budget_mb,
    )
    return candidates[-1]


def resolve_startup_models(
    force_tier: Optional[str] = None,
    audit_logger: Any = None,
) -> dict[str, str]:
    """
    Select the best model for each modality given the current hardware.

    Parameters
    ----------
    force_tier:
        Override tier for every modality.  If ``None``, reads from the
        ``FORCE_TIER`` environment variable, then falls back to auto-detect.
    audit_logger:
        An ``AuditLogger`` instance.  If provided, writes a
        ``model_resolution`` startup record.

    Returns
    -------
    ``{modality: model_name}`` — e.g.
    ``{"text": "qwen25_14b_instruct", "code": "qwen25_coder_7b", ...}``
    """
    # ── 1. Honour FORCE_TIER env override ──────────────────────────────
    effective_force_tier = force_tier or os.environ.get("FORCE_TIER")

    # ── 2. Detect hardware ─────────────────────────────────────────────
    if effective_force_tier:
        gpu_info: GpuInfo = {
            "gpu_available": False,
            "total_vram_mb": 0,
            "free_vram_mb": 0,
            "device_name": "forced",
        }
        _log.info("FORCE_TIER=%r — skipping GPU detection", effective_force_tier)
    else:
        gpu_info = detect_gpu()

    budget_mb = int(gpu_info["free_vram_mb"] * _HEADROOM) if gpu_info["gpu_available"] else 0
    _log.info(
        "VRAM budget: %d MB  (free=%d MB, headroom=%.0f%%)",
        budget_mb,
        gpu_info["free_vram_mb"],
        _HEADROOM * 100,
    )

    # ── 3. Group registry by modality ──────────────────────────────────
    groups = _group_by_modality()

    # ── 4. Resolve each modality ───────────────────────────────────────
    resolved: dict[str, str] = {}
    used_mb = 0

    for modality in _MANAGED_MODALITIES:
        candidates = groups.get(modality, [])
        remaining = max(0, budget_mb - used_mb)

        chosen = _pick_best_fit(candidates, remaining, force_tier=effective_force_tier)
        if chosen is None:
            _log.warning("No models registered for modality=%r — skipping", modality)
            continue

        resolved[modality] = chosen["name"]
        used_mb += chosen.get("est_vram_mb", 0)
        _log.info(
            "  modality=%-10s  →  %-30s  tier=%-7s  est=%d MB  (budget_remaining=%d MB)",
            modality,
            chosen["name"],
            chosen.get("tier", "?"),
            chosen.get("est_vram_mb", 0),
            max(0, budget_mb - used_mb),
        )

    # ── 5. Audit log ───────────────────────────────────────────────────
    summary = {name: MODEL_REGISTRY[name]["ollama_tag"] for name in resolved.values()}
    resolution_payload = {
        "gpu_info": gpu_info,
        "budget_mb": budget_mb,
        "force_tier": effective_force_tier,
        "resolved_models": resolved,
        "resolved_tags": summary,
        "total_est_vram_mb": used_mb,
    }

    if audit_logger is not None:
        try:
            # Use the generic log_event path so we don't need a new logger method.
            from app.audit.logger import EventType

            audit_logger.log_event(
                EventType.STARTUP,
                request_id="SYSTEM_TIER_RESOLVER",
                payload={"event": "model_resolution", **resolution_payload},
            )
        except Exception as exc:  # noqa: BLE001 — audit must never crash startup
            _log.warning("Could not write model_resolution audit record: %s", exc)
    else:
        _log.info("model_resolution (no audit_logger): %s", resolution_payload)

    return resolved
