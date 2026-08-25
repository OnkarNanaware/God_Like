"""
router/router.py
================
Two-stage model router for the Sovereign Workbench.

Stage 1  — Heuristic pass (``app.router.heuristics``):
  Pure-function keyword/file-extension scan.  Zero model calls.
  Produces a list of ``HeuristicSignal`` objects sorted by confidence.
  If the top signal's confidence ≥ ``CONFIDENCE_THRESHOLD`` (0.75),
  the decision is made here.

Stage 2  — LLM fallback (``app.router.llm_classifier``):
  Invoked only when heuristics are ambiguous.  Sends a short classification
  prompt to the *smallest* capable text model.  Result is parsed into a
  ``Capability`` label and mapped to a model.

Both stages write a ``route_decision`` record to the audit log so every
routing decision is traceable, including which stage fired and why.

Model selection
---------------
The router reads ``MODEL_REGISTRY`` from ``ollama_client.py`` (the same
``models.yaml``-derived dict used everywhere else).  It maps a ``Capability``
to the model whose ``capability_tags`` list contains it.  When multiple
models match, preference order is:

  code/debug tasks  →  prefer larger coder model if present, else smaller
  vision tasks      →  the vision model
  general tasks     →  default text model (``qwen25_14b_instruct``)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from app.audit.logger import AuditLogger, EventType
from app.models.ollama_client import MODEL_REGISTRY
from app.router.heuristics import (
    CONFIDENCE_THRESHOLD,
    Capability,
    HeuristicSignal,
    is_ambiguous,
    run_heuristics,
)
from app.router.llm_classifier import LLMClassifierProtocol, classify_with_llm

_log = logging.getLogger("sovereign.router")

# ---------------------------------------------------------------------------
# Default model fallback when nothing else matches
# ---------------------------------------------------------------------------

_DEFAULT_MODEL_NAME = "qwen25_14b_instruct"

# Preferred model ordering for code tasks (most capable first so we can
# fall back if one isn't pulled yet).
_CODE_MODEL_PREFERENCE = ["qwen25_coder_14b", "qwen25_coder_7b"]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingDecision:
    """
    The outcome of the routing process.

    Attributes
    ----------
    model_name  : Registry key (e.g. "qwen25_coder_14b").
    ollama_tag  : The actual tag passed to Ollama.
    stage       : "heuristic" | "llm_fallback" | "default"
    capability  : The winning capability label (may be None for default path).
    signals     : All heuristic signals collected (empty if heuristics skipped).
    reason      : Human-readable explanation.
    request_id  : Propagated correlation ID.
    """

    model_name: str
    ollama_tag: str
    stage: str
    capability: Optional[str]
    signals: list[HeuristicSignal]
    reason: str
    request_id: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class Router:
    """
    Two-stage model router.

    Parameters
    ----------
    audit_logger:
        Shared ``AuditLogger`` instance.  Every routing decision is logged here.
    llm_client:
        An object satisfying ``LLMClassifierProtocol`` — used for the LLM
        fallback stage.  Inject a ``FakeOllamaClient`` in tests.
    default_model_name:
        Registry key to use when nothing else matches.  Defaults to
        ``qwen25_14b_instruct``.
    """

    def __init__(
        self,
        audit_logger: AuditLogger,
        llm_client: Optional[LLMClassifierProtocol] = None,
        default_model_name: str = _DEFAULT_MODEL_NAME,
    ) -> None:
        self._audit = audit_logger
        self._llm_client = llm_client
        self._default_model_name = default_model_name
        self._registry: dict[str, dict[str, Any]] = MODEL_REGISTRY

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def route(
        self,
        text: str,
        *,
        request_id: Optional[str] = None,
        attached_filenames: Optional[Sequence[str]] = None,
        explicit_capability_hint: Optional[str] = None,
    ) -> RoutingDecision:
        """
        Determine which model should handle this request.

        Parameters
        ----------
        text:
            Full text of the user request.
        request_id:
            Correlation ID for audit logging.  Generated if omitted.
        attached_filenames:
            Basenames or paths of any attached files (used by file-type heuristic).
        explicit_capability_hint:
            A ``Capability`` tag string supplied by the caller.  Forces confidence=1.

        Returns
        -------
        A ``RoutingDecision`` with the chosen model and full audit metadata.
        """
        request_id = request_id or str(uuid.uuid4())

        # ── Stage 1: Heuristic pass ───────────────────────────────────────
        signals = run_heuristics(
            text,
            attached_filenames=attached_filenames,
            explicit_capability_hint=explicit_capability_hint,
        )

        if not is_ambiguous(signals):
            winner = signals[0]
            model_name = self._pick_model_for_capability(winner.capability)
            decision = RoutingDecision(
                model_name=model_name,
                ollama_tag=self._registry[model_name]["ollama_tag"],
                stage="heuristic",
                capability=winner.capability.value,
                signals=signals,
                reason=(
                    f"Heuristic stage confident (score={winner.confidence:.2f}): "
                    f"{winner.reason}"
                ),
                request_id=request_id,
            )
            self._log_decision(decision)
            return decision

        # ── Stage 2: LLM fallback ─────────────────────────────────────────
        if self._llm_client is not None:
            classified_capability = await classify_with_llm(
                self._llm_client,
                text,
                request_id=request_id,
            )
            if classified_capability is not None:
                model_name = self._pick_model_for_capability(classified_capability)
                decision = RoutingDecision(
                    model_name=model_name,
                    ollama_tag=self._registry[model_name]["ollama_tag"],
                    stage="llm_fallback",
                    capability=classified_capability.value,
                    signals=signals,
                    reason=(
                        f"Heuristic ambiguous "
                        f"(top confidence="
                        f"{signals[0].confidence:.2f} < {CONFIDENCE_THRESHOLD}"
                        if signals else
                        f"(no heuristic signals"
                    ) + f"); LLM classified as '{classified_capability.value}'",
                    request_id=request_id,
                )

                self._log_decision(decision)
                return decision

        # ── Stage 3: Default fallback ─────────────────────────────────────
        model_name = self._default_model_name
        decision = RoutingDecision(
            model_name=model_name,
            ollama_tag=self._registry[model_name]["ollama_tag"],
            stage="default",
            capability=None,
            signals=signals,
            reason=(
                "Heuristic ambiguous and LLM fallback unavailable or failed — "
                "using default text model"
            ),
            request_id=request_id,
        )
        self._log_decision(decision)
        return decision

    # ------------------------------------------------------------------
    # Model selection
    # ------------------------------------------------------------------

    def _pick_model_for_capability(self, capability: Capability) -> str:
        """
        Find the best registry model that has ``capability.value`` in its
        ``capability_tags``.

        Strategy
        --------
        * For code capabilities: try ``_CODE_MODEL_PREFERENCE`` in order.
        * For vision: pick any model with modality=="vision".
        * For embedding: pick any model with modality=="embedding".
        * Otherwise: first match from registry, fallback to default.
        """
        cap_value = capability.value

        # Code path
        if cap_value in {
            Capability.CODE_GENERATION.value,
            Capability.CODE_REVIEW.value,
            Capability.DEBUGGING.value,
            Capability.REFACTORING.value,
            Capability.COMPLEX_CODE.value,
        }:
            for preferred in _CODE_MODEL_PREFERENCE:
                if preferred in self._registry:
                    if cap_value in self._registry[preferred].get("capability_tags", []):
                        return preferred
            # fallback: any model with the tag
            return self._first_model_with_tag(cap_value)

        # Vision path
        if cap_value in {
            Capability.IMAGE_UNDERSTANDING.value,
            Capability.OCR.value,
            Capability.DOCUMENT_VISION.value,
            Capability.CHART_ANALYSIS.value,
        }:
            for name, cfg in self._registry.items():
                if cfg.get("modality") == "vision":
                    return name
            return self._default_model_name

        # Embedding path
        if cap_value == Capability.EMBEDDING.value:
            for name, cfg in self._registry.items():
                if cfg.get("modality") == "embedding":
                    return name

        return self._first_model_with_tag(cap_value)

    def _first_model_with_tag(self, tag: str) -> str:
        """Return the first registry model that has ``tag`` in capability_tags."""
        for name, cfg in self._registry.items():
            if tag in cfg.get("capability_tags", []):
                return name
        return self._default_model_name

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    def _log_decision(self, decision: RoutingDecision) -> None:
        """Write a ``route_decision`` event to the audit trail."""
        self._audit.log_event(
            EventType.ROUTE_DECISION,
            request_id=decision.request_id,
            payload={
                "model_name": decision.model_name,
                "ollama_tag": decision.ollama_tag,
                "stage": decision.stage,
                "capability": decision.capability,
                "reason": decision.reason,
                "heuristic_signals": [
                    {
                        "capability": s.capability.value,
                        "confidence": s.confidence,
                        "reason": s.reason,
                        "source": s.source,
                    }
                    for s in decision.signals
                ],
            },
        )
        _log.info(
            "Route [%s] → %s via %s (capability=%s)",
            decision.request_id,
            decision.model_name,
            decision.stage,
            decision.capability,
        )
