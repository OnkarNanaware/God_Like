"""
app/main.py
===========
Sovereign Workbench — FastAPI application entrypoint.

Phase A:  /chat endpoint backed by the default text model.

Network sovereignty
-------------------
* No external HTTP calls are made at startup or during request handling.
* The OllamaClient validates at import time that all configured endpoints
  resolve to localhost.
* Lifespan events close the HTTP client cleanly on shutdown.
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.audit.logger import AuditLogger, EventType
from app.models.ollama_client import (
    MODEL_REGISTRY,
    OllamaAPIError,
    OllamaClient,
    OllamaConnectionError,
    OllamaTimeoutError,
)

# ---------------------------------------------------------------------------
# Logging — stdlib, writes to stdout AND to the structured audit file.
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
_log = logging.getLogger("sovereign.main")

# ---------------------------------------------------------------------------
# Application-level singletons (created once in the lifespan context).
# ---------------------------------------------------------------------------

_audit_logger: AuditLogger | None = None
_default_client: OllamaClient | None = None

# The model used by the Phase-A /chat endpoint.
# Phase B will replace this with router-selected models.
_DEFAULT_MODEL_NAME = os.environ.get("DEFAULT_MODEL", "qwen25_14b_instruct")


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _audit_logger, _default_client

    _audit_logger = AuditLogger()
    _log.info("AuditLogger initialised — log path: %s", _audit_logger._path)

    _default_client = OllamaClient(
        model_name=_DEFAULT_MODEL_NAME,
        audit_logger=_audit_logger,
    )
    _log.info(
        "Default model: %s (%s)",
        _DEFAULT_MODEL_NAME,
        _default_client.ollama_tag,
    )

    yield  # ← application runs here

    # Shutdown
    if _default_client is not None:
        await _default_client.aclose()
    _log.info("Sovereign Workbench shut down cleanly.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Sovereign Workbench",
    description=(
        "Private, self-hosted AI workbench.  "
        "All inference runs on localhost via Ollama.  "
        "No external network calls are made at any time."
    ),
    version="0.1.0-phase-a",
    lifespan=lifespan,
    # Disable OpenAPI docs telemetry — FastAPI itself has none, but be explicit.
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS: restrict to localhost origins only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str = Field(..., description="'system', 'user', or 'assistant'")
    content: str = Field(..., description="Message content text")


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(
        ..., min_length=1, description="Conversation history, latest message last"
    )
    model: Optional[str] = Field(
        default=None,
        description=(
            "Model name key from models.yaml (e.g. 'qwen25_14b_instruct').  "
            "Defaults to the server's DEFAULT_MODEL."
        ),
    )
    stream: bool = Field(default=False, description="Stream the response as SSE")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, gt=0, le=32768)
    request_id: Optional[str] = Field(
        default=None,
        description="Caller-supplied correlation ID.  A UUID is generated if omitted.",
    )


class ChatResponseUsage(BaseModel):
    prompt_tokens: int
    response_tokens: int
    total_tokens: int
    latency_ms: float


class ChatResponse(BaseModel):
    request_id: str
    model_name: str
    ollama_tag: str
    content: str
    usage: ChatResponseUsage


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------


def _get_audit_logger() -> AuditLogger:
    if _audit_logger is None:
        raise RuntimeError("AuditLogger not initialised — is the lifespan running?")
    return _audit_logger


def _get_or_create_client(model_name: str) -> OllamaClient:
    """
    Return the default client for the default model, or create a short-lived
    client for a caller-specified model.

    Phase B will replace this with a proper client pool / router.
    """
    if model_name == _DEFAULT_MODEL_NAME and _default_client is not None:
        return _default_client
    # Caller requested a non-default model — create a transient client.
    # (Acceptable for Phase A; Phase B will add a client pool.)
    return OllamaClient(
        model_name=model_name,
        audit_logger=_get_audit_logger(),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Meta"])
async def health_check() -> dict[str, str]:
    """
    Liveness probe.  Does NOT ping Ollama — this is intentional so the
    workbench itself stays up even when a model is being loaded.
    """
    return {"status": "ok", "phase": "A"}


@app.get("/models", tags=["Meta"])
async def list_models() -> dict[str, Any]:
    """Return all models registered in models.yaml."""
    return {"models": list(MODEL_REGISTRY.values())}


@app.post("/chat", tags=["Inference"], response_model=ChatResponse)
async def chat(request: ChatRequest, raw_request: Request) -> Any:
    """
    Phase A main endpoint.

    Accepts a conversation history and returns a model response from the
    locally-running Ollama instance.  No data leaves the host.

    Streaming mode
    --------------
    Set ``stream: true`` to receive Server-Sent Events.  Each event data
    payload is a JSON object with a ``delta`` field.  The stream ends with
    ``data: [DONE]``.
    """
    audit = _get_audit_logger()
    request_id = request.request_id or str(uuid.uuid4())
    model_name = request.model or _DEFAULT_MODEL_NAME

    # Validate model name early — give a clear error before hitting Ollama.
    if model_name not in MODEL_REGISTRY:
        audit.log_error(
            request_id=request_id,
            error_type="UnknownModel",
            message=f"Requested model '{model_name}' not in registry",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "unknown_model",
                "message": (
                    f"Model '{model_name}' is not in the registry.  "
                    f"Available: {list(MODEL_REGISTRY)}"
                ),
                "request_id": request_id,
            },
        )

    messages = [m.model_dump() for m in request.messages]

    try:
        client = _get_or_create_client(model_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "client_init_failed", "message": str(exc), "request_id": request_id},
        )

    # -----------------------------------------------------------------------
    # Streaming path
    # -----------------------------------------------------------------------
    if request.stream:
        async def _sse_generator() -> AsyncGenerator[str, None]:
            try:
                async for delta in client.chat_stream(
                    messages,
                    request_id=request_id,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                ):
                    import json as _json
                    yield f"data: {_json.dumps({'delta': delta, 'request_id': request_id})}\n\n"
            except OllamaConnectionError as exc:
                import json as _json
                yield f"data: {_json.dumps({'error': str(exc), 'request_id': request_id})}\n\n"
            finally:
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            _sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Request-ID": request_id,
            },
        )

    # -----------------------------------------------------------------------
    # Non-streaming path
    # -----------------------------------------------------------------------
    try:
        result = await client.chat_completion(
            messages,
            request_id=request_id,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except OllamaConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "ollama_not_reachable",
                "message": str(exc),
                "request_id": request_id,
            },
        )
    except OllamaTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "error": "ollama_timeout",
                "message": str(exc),
                "request_id": request_id,
            },
        )
    except OllamaAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "ollama_api_error",
                "message": str(exc),
                "request_id": request_id,
            },
        )

    return ChatResponse(
        request_id=result.request_id,
        model_name=result.model_name,
        ollama_tag=result.ollama_tag,
        content=result.content,
        usage=ChatResponseUsage(
            prompt_tokens=result.prompt_tokens,
            response_tokens=result.response_tokens,
            total_tokens=result.total_tokens,
            latency_ms=result.latency_ms,
        ),
    )


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all for unhandled exceptions.  Logs to audit trail and returns a
    generic 500 so we never leak stack traces to callers.
    """
    request_id = str(uuid.uuid4())
    _log.exception("Unhandled exception for request_id=%s: %s", request_id, exc)
    if _audit_logger is not None:
        _audit_logger.log_error(
            request_id=request_id,
            error_type=type(exc).__name__,
            message=str(exc),
        )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred.  Check the audit log for details.",
            "request_id": request_id,
        },
    )
