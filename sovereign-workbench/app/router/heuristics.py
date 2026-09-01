"""
router/heuristics.py
====================
Fast, zero-model-call heuristic pass for model selection.

The heuristic examines three signals (in priority order):
  1. Attached file extension / MIME type → vision if image/PDF, code if source.
  2. Explicit capability hint supplied by the caller (highest priority if present).
  3. Keyword scan of the request text for code/error/vision patterns.

Each signal produces a ``HeuristicSignal`` with a confidence in [0, 1].
The router combines them and declares ``AMBIGUOUS`` when the top confidence
falls below ``CONFIDENCE_THRESHOLD``, triggering the LLM fallback.

No model calls, no I/O, no side effects — this module is pure functions so
it is trivially testable and has zero startup cost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Optional, Sequence


# ---------------------------------------------------------------------------
# Capability labels (must match capability_tags in models.yaml)
# ---------------------------------------------------------------------------


class Capability(str, Enum):
    CHAT = "chat"
    REASONING = "reasoning"
    SUMMARIZATION = "summarization"
    DOCUMENT_QA = "document_qa"
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    COMPLEX_CODE = "complex_code"
    IMAGE_UNDERSTANDING = "image_understanding"
    OCR = "ocr"
    DOCUMENT_VISION = "document_vision"
    CHART_ANALYSIS = "chart_analysis"
    EMBEDDING = "embedding"
    SPREADSHEET_ANALYSIS = "spreadsheet_analysis"  # Phase D–E: .xlsx/.xls/.csv uploads


# ---------------------------------------------------------------------------
# Signal dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeuristicSignal:
    """
    A single routing signal from the heuristic pass.

    Attributes
    ----------
    capability: The inferred capability needed.
    confidence: Score in [0, 1].  ≥ 0.8 is considered definitive.
    reason:     Human-readable explanation logged to the audit trail.
    source:     Which heuristic produced this signal.
    """

    capability: Capability
    confidence: float  # [0, 1]
    reason: str
    source: str  # "file_type" | "keyword" | "explicit_hint"


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Below this threshold the best heuristic signal is considered ambiguous
# and the LLM fallback will be invoked.
CONFIDENCE_THRESHOLD: float = 0.75

# File extensions that route to the vision model.
_VISION_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".svg"}
)

# File extensions that route to the code model.
_CODE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py", ".js", ".ts", ".java", ".c", ".cpp", ".cc", ".h", ".hpp",
        ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala",
        ".sh", ".bash", ".zsh", ".fish", ".yaml", ".yml", ".json",
        ".toml", ".tf", ".hcl", ".sql", ".r", ".m", ".pl",
    }
)

# File extensions that route to the spreadsheet analysis tool.
_SPREADSHEET_EXTENSIONS: frozenset[str] = frozenset(
    {".xlsx", ".xls", ".csv"}
)

# Keyword patterns that signal a code/debugging task.
# Each tuple is (pattern, confidence, capability, reason).
_CODE_KEYWORD_PATTERNS: list[tuple[re.Pattern[str], float, Capability, str]] = [
    (re.compile(r"\btraceback\b", re.IGNORECASE), 0.90, Capability.DEBUGGING, "contains 'traceback'"),
    (re.compile(r"\bstack\s+trace\b", re.IGNORECASE), 0.90, Capability.DEBUGGING, "contains 'stack trace'"),
    (re.compile(r"\berror:\s+", re.IGNORECASE), 0.80, Capability.DEBUGGING, "contains 'error:'"),
    (re.compile(r"\bexception\b", re.IGNORECASE), 0.80, Capability.DEBUGGING, "contains 'exception'"),
    (re.compile(r"\bdef\s+\w+\s*\(", re.IGNORECASE), 0.85, Capability.CODE_GENERATION, "contains function definition"),
    (re.compile(r"\bclass\s+\w+[\s(:]", re.IGNORECASE), 0.85, Capability.CODE_GENERATION, "contains class definition"),
    (re.compile(r"\bfunction\s+\w+\s*\(", re.IGNORECASE), 0.82, Capability.CODE_GENERATION, "contains JS/TS function"),
    (re.compile(r"\bimport\s+\w+", re.IGNORECASE), 0.70, Capability.CODE_GENERATION, "contains import statement"),
    (re.compile(r"\brefactor\b", re.IGNORECASE), 0.80, Capability.REFACTORING, "contains 'refactor'"),
    (re.compile(r"\bcode\s+review\b", re.IGNORECASE), 0.80, Capability.CODE_REVIEW, "contains 'code review'"),
    (re.compile(r"\bdebug\b", re.IGNORECASE), 0.78, Capability.DEBUGGING, "contains 'debug'"),
    (re.compile(r"```[\w]*\n", re.IGNORECASE), 0.85, Capability.CODE_GENERATION, "contains fenced code block"),
]

# Vision keyword patterns.
_VISION_KEYWORD_PATTERNS: list[tuple[re.Pattern[str], float, Capability, str]] = [
    (re.compile(r"\bscreenshot\b", re.IGNORECASE), 0.85, Capability.IMAGE_UNDERSTANDING, "contains 'screenshot'"),
    (re.compile(r"\bimage\b", re.IGNORECASE), 0.70, Capability.IMAGE_UNDERSTANDING, "contains 'image'"),
    (re.compile(r"\bdiagram\b", re.IGNORECASE), 0.78, Capability.CHART_ANALYSIS, "contains 'diagram'"),
    (re.compile(r"\bchart\b", re.IGNORECASE), 0.80, Capability.CHART_ANALYSIS, "contains 'chart'"),
    (re.compile(r"\bocr\b", re.IGNORECASE), 0.92, Capability.OCR, "contains 'ocr'"),
    (re.compile(r"\bextract\s+text\b", re.IGNORECASE), 0.82, Capability.OCR, "contains 'extract text'"),
    (re.compile(r"\bscanned\b", re.IGNORECASE), 0.80, Capability.DOCUMENT_VISION, "contains 'scanned'"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_heuristics(
    text: str,
    *,
    attached_filenames: Optional[Sequence[str]] = None,
    explicit_capability_hint: Optional[str] = None,
) -> list[HeuristicSignal]:
    """
    Run all heuristic checks and return a list of signals, highest confidence first.

    Parameters
    ----------
    text:
        The full text of the user request (all messages concatenated).
    attached_filenames:
        File names (basenames or full paths) of any attached files.
    explicit_capability_hint:
        A capability tag string supplied directly by the caller (e.g. "code_generation").
        This always wins over keyword heuristics if confidence == 1.0.

    Returns
    -------
    A sorted list of ``HeuristicSignal`` objects (descending confidence).
    An empty list means no signals — triggers LLM fallback immediately.
    """
    signals: list[HeuristicSignal] = []

    # ── 1. Explicit capability hint (caller-supplied, unconditional) ──────
    if explicit_capability_hint:
        try:
            cap = Capability(explicit_capability_hint.lower())
            signals.append(
                HeuristicSignal(
                    capability=cap,
                    confidence=1.0,
                    reason=f"caller supplied explicit_capability_hint='{explicit_capability_hint}'",
                    source="explicit_hint",
                )
            )
        except ValueError:
            # Unknown hint — ignore and fall through
            pass

    # ── 2. Attached file extension ────────────────────────────────────────
    if attached_filenames:
        for fname in attached_filenames:
            ext = PurePosixPath(fname).suffix.lower()
            if ext in _VISION_EXTENSIONS:
                signals.append(
                    HeuristicSignal(
                        capability=Capability.IMAGE_UNDERSTANDING
                        if ext != ".pdf"
                        else Capability.DOCUMENT_VISION,
                        confidence=0.95,
                        reason=f"attached file '{fname}' has vision extension '{ext}'",
                        source="file_type",
                    )
                )
            elif ext in _CODE_EXTENSIONS:
                signals.append(
                    HeuristicSignal(
                        capability=Capability.CODE_GENERATION,
                        confidence=0.88,
                        reason=f"attached file '{fname}' has code extension '{ext}'",
                        source="file_type",
                    )
                )
            elif ext in _SPREADSHEET_EXTENSIONS:
                signals.append(
                    HeuristicSignal(
                        capability=Capability.SPREADSHEET_ANALYSIS,
                        confidence=0.95,
                        reason=f"attached file '{fname}' has spreadsheet extension '{ext}'",
                        source="file_type",
                    )
                )

    # ── 3. Keyword scan ───────────────────────────────────────────────────
    for pattern, confidence, capability, reason in _CODE_KEYWORD_PATTERNS:
        if pattern.search(text):
            signals.append(
                HeuristicSignal(
                    capability=capability,
                    confidence=confidence,
                    reason=reason,
                    source="keyword",
                )
            )

    for pattern, confidence, capability, reason in _VISION_KEYWORD_PATTERNS:
        if pattern.search(text):
            signals.append(
                HeuristicSignal(
                    capability=capability,
                    confidence=confidence,
                    reason=reason,
                    source="keyword",
                )
            )

    # Sort descending by confidence so callers can take [0] for the winner.
    signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


def is_ambiguous(signals: list[HeuristicSignal]) -> bool:
    """
    Return True if the heuristic signals are too weak to make a confident decision,
    meaning the LLM fallback should be invoked.
    """
    if not signals:
        return True
    return signals[0].confidence < CONFIDENCE_THRESHOLD
