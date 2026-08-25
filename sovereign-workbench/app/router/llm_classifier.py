"""
router/llm_classifier.py
========================
LLM-backed fallback classifier for the router.

This module is intentionally thin.  The heavy lifting is done by the model;
this layer's only jobs are:

  1. Build the classification prompt from the available capability labels.
  2. Call the OllamaClient (or any object that satisfies ``LLMClassifierProtocol``).
  3. Parse the model's response into a ``Capability`` label.
  4. Return ``None`` on parse failure so the router can fall back to a safe default.

Testability
-----------
``LLMClassifierProtocol`` is a ``typing.Protocol`` — any object with the same
``chat_completion`` signature satisfies it.  Tests inject a ``FakeOllamaClient``
that returns a fixed label string without touching the network.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Protocol, runtime_checkable

from app.router.heuristics import Capability

_log = logging.getLogger("sovereign.router.llm_classifier")

# ---------------------------------------------------------------------------
# Protocol — what we need from the model client (satisfied by OllamaClient
# and by any test double with the same signature).
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMClassifierProtocol(Protocol):
    """Structural typing protocol for the LLM used by the classifier."""

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        request_id: Optional[str] = None,
        temperature: float = ...,
        max_tokens: int = ...,
        extra_body: Optional[dict[str, Any]] = None,
    ) -> Any:
        """
        Must return an object with a `.content` attribute containing the model's text.
        """
        ...


# ---------------------------------------------------------------------------
# Classification prompt
# ---------------------------------------------------------------------------

_VALID_LABELS: list[str] = [cap.value for cap in Capability]

_SYSTEM_PROMPT = """\
You are a request classifier for an AI workbench. Your sole task is to read a user \
request and output a single capability label that best describes what the user needs.

Valid labels (output exactly one, no explanation):
{labels}

Rules:
- Output only the label, nothing else.
- If the request involves code, errors, debugging, or programming, prefer: \
code_generation, debugging, code_review, or refactoring.
- If the request involves images, PDFs, charts, diagrams, or OCR, prefer: \
image_understanding, ocr, document_vision, or chart_analysis.
- If the request involves summarizing, Q&A over documents, or general knowledge, prefer: \
summarization, document_qa, or chat.
- Default to 'chat' if nothing else fits.
""".strip()


def _build_classification_messages(user_text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": _SYSTEM_PROMPT.format(labels=", ".join(_VALID_LABELS)),
        },
        {
            "role": "user",
            "content": f"Classify this request:\n\n{user_text[:2000]}",  # cap to avoid overflow
        },
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def classify_with_llm(
    client: LLMClassifierProtocol,
    user_text: str,
    *,
    request_id: Optional[str] = None,
) -> Optional[Capability]:
    """
    Ask the LLM to classify ``user_text`` into a ``Capability`` label.

    Returns
    -------
    The best-matching ``Capability``, or ``None`` if the model returns
    an unrecognised label (so the router can apply its own safe default).
    """
    messages = _build_classification_messages(user_text)
    try:
        response = await client.chat_completion(
            messages,
            request_id=request_id,
            temperature=0.0,  # deterministic — this is classification, not generation
            max_tokens=16,    # we only need one label word
        )
        raw: str = response.content.strip().lower()
    except Exception as exc:
        _log.warning(
            "LLM classifier call failed (request_id=%s): %s — falling back to default",
            request_id,
            exc,
        )
        return None

    # Exact match first.
    try:
        return Capability(raw)
    except ValueError:
        pass

    # Partial match — the model may have added punctuation or a short explanation.
    for label in _VALID_LABELS:
        if label in raw:
            try:
                return Capability(label)
            except ValueError:
                continue

    _log.warning(
        "LLM classifier returned unrecognised label %r (request_id=%s) — using default",
        raw,
        request_id,
    )
    return None
