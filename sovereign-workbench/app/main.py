"""
app/main.py
===========
Sovereign Workbench — FastAPI application entrypoint.

Phases A-C:  /chat, /ingest, /rag/search endpoints.

Network sovereignty
-------------------
* No external HTTP calls are made at startup or during request handling.
* The OllamaClient validates at import time that all configured endpoints
  resolve to localhost.
* Qdrant is accessed at localhost:6333 only.
* Lifespan events close the HTTP client cleanly on shutdown.
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.audit.logger import AuditLogger, EventType
from app.audit.async_adapter import AsyncAuditAdapter
from app.models.ollama_client import (
    MODEL_REGISTRY,
    OllamaAPIError,
    OllamaClient,
    OllamaConnectionError,
    OllamaTimeoutError,
)

# Standalone sandbox router — no Ollama, no LLM, no orchestrator, no RAG.
from app.sandbox.router import router as sandbox_router

# Phase E: orchestrator + hardware endpoints.
from app.routers.orchestrator_router import router as orchestrator_router, setup_orchestrator_router

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
_async_audit: AsyncAuditAdapter | None = None  # Phase E: async-safe wrapper
_default_client: OllamaClient | None = None
_embedding_client: OllamaClient | None = None
_vision_client: OllamaClient | None = None  # Phase D — VisionExtractTool

# Phase C singletons
_ingestor: Any | None = None   # app.rag.ingestor.Ingestor
_vector_store: Any | None = None  # app.rag.store.VectorStore

# Phase E: Orchestrator singleton
_orchestrator: Any | None = None  # app.orchestrator.orchestrator.Orchestrator

# The model used by the /chat endpoint — resolved at startup by tier_resolver.
_DEFAULT_MODEL_NAME = os.environ.get("DEFAULT_MODEL", "qwen25_14b_instruct")
_EMBEDDING_MODEL_NAME = "bge_m3"
_DEFAULT_VISION_MODEL_NAME = "qwen25vl_3b"


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _audit_logger, _async_audit, _default_client, _embedding_client, _vision_client, _ingestor, _vector_store, _orchestrator
    resolved: dict = {}  # populated by tier resolver; safe default for scope

    # ── Audit logger ───────────────────────────────────────────────────
    _audit_logger = AuditLogger()
    _async_audit = AsyncAuditAdapter(_audit_logger)  # Phase E: thread-safe async wrapper
    _log.info("AuditLogger initialised — log path: %s", _audit_logger._path)

    # ── GPU-adaptive model selection ───────────────────────────────────
    try:
        from app.hardware.tier_resolver import resolve_startup_models
        resolved = resolve_startup_models(audit_logger=_audit_logger)
        # Map modality → model_name; prefer "text" modality for default chat.
        text_model = resolved.get("text", _DEFAULT_MODEL_NAME)
        # Only override if that model is actually in the registry.
        if text_model in MODEL_REGISTRY:
            actual_default = text_model
            _log.info("GPU tier resolver selected default text model: %s", actual_default)
        else:
            actual_default = _DEFAULT_MODEL_NAME
            _log.warning(
                "Resolved model '%s' not in registry — falling back to %s",
                text_model,
                actual_default,
            )
    except Exception as exc:  # noqa: BLE001 — resolver failure must not crash startup
        resolved = {}
        actual_default = _DEFAULT_MODEL_NAME
        _log.warning("Tier resolver failed (%s) — using default model: %s", exc, actual_default)

    # ── Default LLM client ─────────────────────────────────────────────
    _default_client = OllamaClient(
        model_name=actual_default,
        audit_logger=_audit_logger,
    )
    _log.info(
        "Default model: %s (%s)",
        actual_default,
        _default_client.ollama_tag,
    )

    # ── Embedding client (bge-m3) ──────────────────────────────────────
    if _EMBEDDING_MODEL_NAME in MODEL_REGISTRY:
        _embedding_client = OllamaClient(
            model_name=_EMBEDDING_MODEL_NAME,
            audit_logger=_audit_logger,
        )
        _log.info("Embedding model: %s (%s)", _EMBEDDING_MODEL_NAME, _embedding_client.ollama_tag)
    else:
        _log.warning(
            "Embedding model '%s' not found in registry — /ingest and /rag/search unavailable",
            _EMBEDDING_MODEL_NAME,
        )

    # ── Qdrant vector store + Ingestor ─────────────────────────────────
    if _embedding_client is not None:
        try:
            from app.rag.embedder import Embedder
            from app.rag.ingestor import Ingestor
            from app.rag.store import VectorStore
            from app.tools.rag_search import RagSearchTool
            from app.tools.registry import register_tool

            # Use embedded Qdrant (no Docker required) via qdrant_storage/ on disk.
            _QDRANT_STORAGE = Path(__file__).resolve().parent.parent / "qdrant_storage"
            _QDRANT_STORAGE.mkdir(parents=True, exist_ok=True)
            _vector_store = VectorStore(storage_path=_QDRANT_STORAGE)
            embedder = Embedder(_embedding_client)
            _ingestor = Ingestor(
                embedder=embedder,
                store=_vector_store,
                audit_logger=_audit_logger,
            )
            # Register the RAG search tool with the orchestrator's registry.
            register_tool(
                RagSearchTool(
                    store=_vector_store,
                    embedder=embedder,
                    audit_logger=_audit_logger,
                )
            )
            # NOTE: VisionExtractTool (stub from app.tools.vision) is intentionally
            # NOT registered here — the real implementation is registered below after
            # the vision OllamaClient is initialised.
            _log.info("RAG pipeline ready — qdrant_storage=%s", _QDRANT_STORAGE)

            # ── Vision client + VisionExtractTool (Phase D) ────────────
            # Resolve the vision model from the tier resolver output; fall
            # back to the small 3b vision model if the resolver did not
            # select one (e.g. CPU-only / low-VRAM machine).
            # IMPORTANT: Only app.tools.vision_extract is used — the stub
            # in app.tools.vision is legacy code and must NOT be registered.
            from app.tools.vision_extract import VisionExtractTool
            vision_model_name = resolved.get("vision", _DEFAULT_VISION_MODEL_NAME)
            if vision_model_name not in MODEL_REGISTRY:
                vision_model_name = _DEFAULT_VISION_MODEL_NAME
                _log.warning(
                    "Resolved vision model not in registry — falling back to %s",
                    vision_model_name,
                )
            _vision_client = OllamaClient(
                model_name=vision_model_name,
                audit_logger=_audit_logger,
            )
            register_tool(
                VisionExtractTool(
                    llm_client=_vision_client,
                    audit_logger=_audit_logger,
                )
            )
            _log.info(
                "Vision pipeline ready (%s) — vision_extract tool registered",
                vision_model_name,
            )

        except ImportError as exc:
            _log.warning(
                "RAG dependencies not installed (%s) — /ingest and /rag/search disabled.  "
                "Run: pip install qdrant-client pymupdf",
                exc,
            )
        except Exception as exc:  # noqa: BLE001 — Qdrant may not be running in dev
            _log.warning(
                "Qdrant not reachable at startup (%s) — "
                "/ingest and /rag/search will fail at request time",
                exc,
            )

    # ── Phase E: Orchestrator singleton ───────────────────────────────
    try:
        from app.orchestrator.orchestrator import Orchestrator
        _orchestrator = Orchestrator(
            llm_client=_default_client,
            audit_logger=_audit_logger,
        )
        # Wire up gpu_info for /hardware/status
        try:
            from app.hardware.gpu_detect import detect_gpu
            _startup_gpu_info = detect_gpu()
        except Exception:
            _startup_gpu_info = {
                "gpu_available": False,
                "total_vram_mb": 0,
                "free_vram_mb": 0,
                "device_name": "",
            }
        setup_orchestrator_router(
            audit_logger=_audit_logger,
            async_audit=_async_audit,
            orchestrator=_orchestrator,
            startup_resolved=resolved,
            startup_gpu_info=_startup_gpu_info,
        )
        _log.info("Orchestrator initialised and Phase E router wired.")
    except Exception as exc:  # noqa: BLE001
        _log.warning("Orchestrator setup failed (%s) — /orchestrator endpoints unavailable", exc)

    yield  # ← application runs here

    # Shutdown
    if _default_client is not None:
        await _default_client.aclose()
    if _embedding_client is not None:
        await _embedding_client.aclose()
    if _vision_client is not None:
        await _vision_client.aclose()
    _log.info("Sovereign Workbench shut down cleanly — Phase E.")


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
    version="0.1.0-phase-e",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS: restrict to localhost origins only.
# Phase E adds port 5173 (Vite dev server default).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Register the standalone sandbox endpoint (POST /sandbox/execute)
app.include_router(sandbox_router)

# Phase E: orchestrator, hardware, audit, and file-download endpoints.
app.include_router(orchestrator_router)


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


# ── Phase C schemas ────────────────────────────────────────────────────────


class IngestRequest(BaseModel):
    source_path: str = Field(
        ...,
        description="Absolute (or cwd-relative) path to the file to ingest.",
    )
    collection: str = Field(
        default="docs",
        description="Target Qdrant collection name (caller-controlled namespace).",
    )
    request_id: Optional[str] = Field(default=None, description="Audit correlation ID.")


class IngestResponse(BaseModel):
    request_id: str
    source_path: str
    collection: str
    chunks_ingested: int
    source_sha256: str
    duration_ms: float


class RagSearchRequest(BaseModel):
    query: str = Field(..., description="Natural-language query.")
    collection: str = Field(default="docs", description="Target Qdrant collection.")
    top_k: int = Field(default=5, ge=1, le=20, description="Max results.")
    request_id: Optional[str] = Field(default=None)


class RagSearchResult(BaseModel):
    score: float
    text: str
    source: str
    chunk_id: str
    collection: str


class RagSearchResponse(BaseModel):
    request_id: str
    collection: str
    query: str
    results: list[RagSearchResult]


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
    """
    if model_name == _DEFAULT_MODEL_NAME and _default_client is not None:
        return _default_client
    return OllamaClient(
        model_name=model_name,
        audit_logger=_get_audit_logger(),
    )


# ---------------------------------------------------------------------------
# Routes — Meta
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Meta"])
async def health_check() -> dict[str, str]:
    """
    Liveness probe.  Does NOT ping Ollama — this is intentional so the
    workbench itself stays up even when a model is being loaded.
    """
    rag_status = "ready" if _ingestor is not None else "unavailable"
    orch_status = "ready" if _orchestrator is not None else "unavailable"
    return {"status": "ok", "phase": "E", "rag": rag_status, "orchestrator": orch_status}


@app.get("/models", tags=["Meta"])
async def list_models() -> dict[str, Any]:
    """Return all models registered in models.yaml."""
    return {"models": list(MODEL_REGISTRY.values())}


@app.get("/tools", tags=["Meta"])
async def list_tools_endpoint() -> dict[str, Any]:
    """Return all registered tools and their input schemas."""
    from app.tools.registry import list_tools
    return {"tools": list_tools()}


# ---------------------------------------------------------------------------
# Routes — Inference (/chat)
# ---------------------------------------------------------------------------


@app.post("/chat", tags=["Inference"], response_model=ChatResponse)
async def chat(request: ChatRequest, raw_request: Request) -> Any:
    """
    Main chat endpoint.

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

    # ── Streaming path ─────────────────────────────────────────────────
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

    # ── Non-streaming path ─────────────────────────────────────────────
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
# Routes — RAG (/ingest, /rag/search)
# ---------------------------------------------------------------------------


@app.post("/ingest", tags=["RAG"], response_model=IngestResponse)
async def ingest_document(request: IngestRequest) -> IngestResponse:
    """
    Ingest a document into the local Qdrant vector store.

    Supported formats: PDF, plain text, Markdown, and common source-code
    extensions (.py, .js, .ts, .go, .java, .cpp, .c, …).

    The file is chunked (512-char sliding window, 64-char overlap), embedded
    with bge-m3 via Ollama, and upserted into the specified Qdrant collection.
    A ``rag_ingest`` audit record is written on success.

    Raises 503 if the RAG pipeline is not initialised (Qdrant/bge-m3 not ready).
    """
    if _ingestor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "rag_not_ready",
                "message": (
                    "RAG pipeline not initialised.  "
                    "Ensure Qdrant is running (docker run -p 6333:6333 qdrant/qdrant) "
                    "and qdrant-client + pymupdf are installed."
                ),
            },
        )

    request_id = request.request_id or str(uuid.uuid4())

    try:
        result = await _ingestor.ingest(
            source_path=request.source_path,
            collection=request.collection,
            request_id=request_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "file_not_found",
                "message": str(exc),
                "request_id": request_id,
            },
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ingestion_failed",
                "message": str(exc),
                "request_id": request_id,
            },
        )
    except Exception as exc:
        _get_audit_logger().log_error(
            request_id=request_id,
            error_type=type(exc).__name__,
            message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "ingestion_error",
                "message": str(exc),
                "request_id": request_id,
            },
        )

    return IngestResponse(
        request_id=result.request_id,
        source_path=result.source_path,
        collection=result.collection,
        chunks_ingested=result.chunks_ingested,
        source_sha256=result.source_sha256,
        duration_ms=result.duration_ms,
    )


@app.post("/rag/search", tags=["RAG"], response_model=RagSearchResponse)
async def rag_search(request: RagSearchRequest) -> RagSearchResponse:
    """
    Semantic search over the local Qdrant knowledge base.

    The query is embedded with bge-m3, then the ``top_k`` most similar
    chunks are returned with their similarity scores and source paths.

    Raises 503 if the RAG pipeline is not initialised.
    """
    if _vector_store is None or _embedding_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "rag_not_ready",
                "message": (
                    "RAG pipeline not initialised.  "
                    "Ensure Qdrant is running and dependencies are installed."
                ),
            },
        )

    request_id = request.request_id or str(uuid.uuid4())

    try:
        from app.rag.embedder import Embedder
        embedder = Embedder(_embedding_client)
        query_vector = await embedder.embed_one(request.query.strip(), request_id=request_id)
        results = _vector_store.search(
            collection=request.collection,
            query_vector=query_vector,
            top_k=request.top_k,
        )
    except Exception as exc:
        _get_audit_logger().log_error(
            request_id=request_id,
            error_type=type(exc).__name__,
            message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "search_error",
                "message": str(exc),
                "request_id": request_id,
            },
        )

    return RagSearchResponse(
        request_id=request_id,
        collection=request.collection,
        query=request.query,
        results=[
            RagSearchResult(
                score=r.score,
                text=r.text,
                source=r.source,
                chunk_id=r.chunk_id,
                collection=r.collection,
            )
            for r in results
        ],
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
