"""
tools/base.py
=============
Abstract base interface for all tools in the Sovereign Workbench.

Design principles
-----------------
* Tools are async: the orchestrator uses ``asyncio`` and some future tools
  (e.g. code sandbox, RAG retrieval) will be genuinely async.
* ``execute()`` NEVER raises exceptions — it returns a ``ToolResult``
  with ``success=False`` and a structured error.  The orchestrator relies
  on this contract to implement its retry/re-plan logic cleanly.
* ``input_schema`` is a JSON-Schema dict (subset of OpenAPI) — this will
  feed the model's function-calling prompt in Phase B and later phases.
* Every tool call is audit-logged by the orchestrator (not the tool itself),
  keeping tools free of cross-cutting concerns.

Adding a new tool
-----------------
1. Subclass ``BaseTool``.
2. Implement ``name``, ``description``, ``input_schema``, and ``execute()``.
3. Register it in ``app/tools/registry.py``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """
    The outcome of a single tool call.

    Attributes
    ----------
    success:
        True if the tool completed its work.  False signals the orchestrator
        to log a failure and consider a retry or re-plan.
    output:
        The tool's primary output — type varies by tool (str, dict, list, etc.).
        Must be JSON-serialisable for audit logging.
    error:
        Human-readable error message when ``success=False``.  None otherwise.
    metadata:
        Optional extra fields (e.g. file size, line count).  Always a dict.
    """

    success: bool
    output: Any
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialisable representation for audit logging."""
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# BaseTool
# ---------------------------------------------------------------------------


class BaseTool(abc.ABC):
    """
    Abstract base class for all workbench tools.

    Subclasses must define:
        name           — unique slug (lowercase, underscores)
        description    — one-sentence description for the model's prompt
        input_schema   — JSON-Schema object schema (``"type": "object"``)
        execute()      — the actual tool logic (async, never raises)
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique tool identifier, e.g. 'file_read'."""
        ...

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """One-sentence description used in the planning prompt."""
        ...

    @property
    @abc.abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """
        JSON-Schema for the tool's keyword arguments.

        Example::

            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute file path"}
                },
                "required": ["path"],
            }
        """
        ...

    @abc.abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        Run the tool with the provided keyword arguments.

        Must NEVER raise.  Catch all exceptions internally and return
        ``ToolResult(success=False, output=None, error=str(exc))``.
        """
        ...

    def describe(self) -> dict[str, Any]:
        """
        Return a serialisable description dict used in planning prompts
        and audit logs.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
