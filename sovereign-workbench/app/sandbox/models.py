"""
app/sandbox/models.py
=====================
Pydantic schemas for the sandbox API layer.

ExecuteRequest  — incoming POST /sandbox/execute payload
ExecuteResponse — outgoing API response

No Ollama, no LLM, no model router, no orchestrator, no RAG.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    """Request body for POST /sandbox/execute."""

    code: str = Field(
        ...,
        description="Python source code to execute inside the Docker sandbox.",
        min_length=1,
    )
    timeout: int = Field(
        default=10,
        ge=1,
        le=30,
        description=(
            "Maximum execution time in seconds (1–30). "
            "The container is killed if this limit is exceeded."
        ),
    )


class ExecuteResponse(BaseModel):
    """Response body from POST /sandbox/execute."""

    success: bool = Field(
        description="True if the code executed with exit code 0 and did not time out."
    )
    stdout: str = Field(description="Captured standard output from the executed code.")
    stderr: str = Field(description="Captured standard error from the executed code.")
    exit_code: int = Field(
        description="Process exit code. 0 = success, 124 = timed out, -1 = runner error."
    )
    timed_out: bool = Field(
        default=False,
        description="True if the container was killed due to the timeout limit.",
    )
    duration_ms: float = Field(
        default=0.0,
        description="Total wall-clock time from workspace creation to container exit, in milliseconds.",
    )
