"""
app/sandbox/router.py
=====================
FastAPI APIRouter for the standalone sandbox endpoint.

POST /sandbox/execute
---------------------
Accepts Python code, passes it directly to SandboxManager,
and returns stdout / stderr / exit_code.

Execution flow (the ONLY flow allowed for this endpoint)
---------------------------------------------------------

    POST /sandbox/execute
            ↓
    ExecuteRequest  (Pydantic validation)
            ↓
    SandboxManager.execute()
            ↓
    DockerRunner → Docker Container → Python code
            ↓
    ExecuteResponse
            ↓
    HTTP JSON Response

This router does NOT call:
  - Ollama / OllamaClient
  - Any LLM or language model
  - Model Router / heuristics / llm_classifier
  - Orchestrator (plan→act→observe)
  - RAG / Qdrant / Embedder
  - AuditLogger (intentionally omitted — sandbox is standalone)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.sandbox.manager import SandboxManager
from app.sandbox.models import ExecuteRequest, ExecuteResponse

_log = logging.getLogger("sovereign.sandbox.router")

# A single shared manager instance (stateless — safe to reuse)
_manager = SandboxManager()

router = APIRouter(
    prefix="/sandbox",
    tags=["Sandbox"],
)


@router.post(
    "/execute",
    response_model=ExecuteResponse,
    summary="Execute Python code in an isolated Docker sandbox",
    description=(
        "Runs Python source code inside a hardened Docker container. "
        "The container has no network access, runs as a non-root user, "
        "has hard CPU and memory limits, and is automatically removed after "
        "execution. No LLM, Ollama, or agent component is involved."
    ),
)
async def execute_sandbox(request: ExecuteRequest) -> ExecuteResponse:
    """
    Execute Python code in the sandbox.

    - **code**: Python source code (required, non-empty).
    - **timeout**: Maximum execution time in seconds (1–30, default 10).

    Returns stdout, stderr, exit_code, and timing information.
    """
    if not request.code or not request.code.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "empty_code",
                "message": "The 'code' field must not be empty or whitespace-only.",
            },
        )

    _log.info(
        "Sandbox execute request — code_len=%d  timeout=%ds",
        len(request.code),
        request.timeout,
    )

    result = await _manager.execute(
        code=request.code,
        timeout=request.timeout,
    )

    return ExecuteResponse(
        success=result.success,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        duration_ms=result.duration_ms,
    )
