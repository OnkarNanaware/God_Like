"""
tools/registry.py
=================
Central registry of all available tools.

The orchestrator imports ``TOOL_REGISTRY`` to discover what tools exist,
build planning prompts, and dispatch ``act`` steps.

Adding a stateless tool
-----------------------
1. Implement a subclass of ``BaseTool`` in ``app/tools/``.
2. Instantiate it and add it to ``_REGISTERED_TOOLS`` below.
3. That's it — the registry builds the lookup dict automatically.

Adding a stateful tool (e.g. RagSearchTool)
--------------------------------------------
Stateful tools depend on resources that are not available at import time
(Qdrant client, OllamaClient, etc.).  Register them dynamically at startup
via ``register_tool()``.  Call this from ``app/main.py``'s lifespan handler
AFTER the resources are initialised.
"""

from __future__ import annotations

from typing import Optional

from app.tools.base import BaseTool
from app.tools.file_read import FileReadTool

# ---------------------------------------------------------------------------
# Static tool instances — always available, no runtime deps.
# ---------------------------------------------------------------------------

_REGISTERED_TOOLS: list[BaseTool] = [
    FileReadTool(),
    # Phase D: add CodeSandboxTool(), DocGenerateTool(), etc.
]

# Lookup dict: tool name → tool instance
TOOL_REGISTRY: dict[str, BaseTool] = {t.name: t for t in _REGISTERED_TOOLS}


# ---------------------------------------------------------------------------
# Dynamic registration (for stateful tools wired at startup)
# ---------------------------------------------------------------------------


def register_tool(tool: BaseTool) -> None:
    """
    Register a tool instance at runtime (after startup resources are ready).

    Idempotent: if a tool with the same name is already registered, the new
    instance replaces it.
    """
    TOOL_REGISTRY[tool.name] = tool
    # Keep _REGISTERED_TOOLS in sync so list_tools() stays accurate.
    _REGISTERED_TOOLS[:] = list(TOOL_REGISTRY.values())


def get_tool(name: str) -> Optional[BaseTool]:
    """Return the tool with the given name, or None if not found."""
    return TOOL_REGISTRY.get(name)


def list_tools() -> list[dict]:
    """Return a list of tool descriptors (for planning prompts and /tools endpoint)."""
    return [t.describe() for t in TOOL_REGISTRY.values()]
