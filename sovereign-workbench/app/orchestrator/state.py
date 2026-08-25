"""
orchestrator/state.py
=====================
State types for the plan → act → observe → iterate state machine.

Keeping types in a separate module avoids circular imports between
``orchestrator.py`` and the tools/router packages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class OrchestratorStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    ACTING = "acting"
    OBSERVING = "observing"
    REPLANNING = "replanning"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PlannedStep:
    """
    A single step produced by the planning LLM.

    Attributes
    ----------
    step_index  : 0-based position in the plan.
    tool_name   : Must match a key in ``TOOL_REGISTRY``.
    tool_args   : Keyword arguments to pass to ``tool.execute(**tool_args)``.
    description : Human-readable explanation of why this step is needed.
    """

    step_index: int
    tool_name: str
    tool_args: dict[str, Any]
    description: str


@dataclass
class StepOutcome:
    """Record of a single step execution attempt."""

    step_index: int
    tool_name: str
    tool_args: dict[str, Any]
    success: bool
    output: Any
    error: Optional[str]
    attempt: int  # 1-based retry counter


@dataclass
class OrchestratorRun:
    """
    Full state of one orchestrator execution.

    Created at the start of ``Orchestrator.run()`` and updated in place
    as each step executes.
    """

    request_id: str
    goal: str
    status: OrchestratorStatus = OrchestratorStatus.PENDING
    plan: list[PlannedStep] = field(default_factory=list)
    outcomes: list[StepOutcome] = field(default_factory=list)
    final_output: Optional[str] = None
    failure_summary: Optional[str] = None
    # Accumulated context fed back into re-plan prompts.
    context_snippets: list[str] = field(default_factory=list)
