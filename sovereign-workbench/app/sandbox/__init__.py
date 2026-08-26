"""
app/sandbox
===========
Standalone Python code execution sandbox.

This module is completely independent of all other sovereign workbench
components.  It does NOT import or call:
  - Ollama / OllamaClient
  - Model Registry
  - Model Router
  - Orchestrator
  - RAG / Qdrant

Public API
----------
::

    from app.sandbox import SandboxManager, SandboxResult

    manager = SandboxManager()
    result  = await manager.execute(code="print(2 + 2)", timeout=10)
    # result.stdout  == "4\\n"
    # result.success == True
    # result.exit_code == 0

FastAPI integration
-------------------
The sandbox router is registered in ``app/main.py`` via::

    from app.sandbox.router import router as sandbox_router
    app.include_router(sandbox_router)

which exposes ``POST /sandbox/execute``.
"""

from app.sandbox.manager import SandboxManager, SandboxResult

__all__ = ["SandboxManager", "SandboxResult"]
