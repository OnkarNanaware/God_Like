"""
tools/registry.py
=================
Central registry of all available tools.

The orchestrator imports ``TOOL_REGISTRY`` to discover what tools exist,
build planning prompts, and dispatch ``act`` steps.

Adding a tool
-------------
1. Implement a subclass of ``BaseTool`` in ``app/tools/``.
2. Instantiate it and add it to ``_REGISTERED_TOOLS`` below.
3. That's it — the registry builds the lookup dict automatically.
"""

from __future__ import annotations

from typing import Optional

from app.tools.base import BaseTool
from app.tools.file_read import FileReadTool

# ---------------------------------------------------------------------------
# Registered tool instances — add new tools here.
# ---------------------------------------------------------------------------

_REGISTERED_TOOLS: list[BaseTool] = [
    FileReadTool(),
    # Phase D: add CodeSandboxTool(), DocGenerateTool(), etc.
]

# Lookup dict: tool name → tool instance
TOOL_REGISTRY: dict[str, BaseTool] = {t.name: t for t in _REGISTERED_TOOLS}


def get_tool(name: str) -> Optional[BaseTool]:
    """Return the tool with the given name, or None if not found."""
    return TOOL_REGISTRY.get(name)


def list_tools() -> list[dict]:
    """Return a list of tool descriptors (for planning prompts and /tools endpoint)."""
    return [t.describe() for t in _REGISTERED_TOOLS]
