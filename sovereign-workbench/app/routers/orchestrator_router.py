"""
routers/orchestrator_router.py
================================
Phase E API endpoints wired to the backend:

  GET  /hardware/status          — GPU info + resolved model tiers (phase-startup cache + live re-query)
  POST /hardware/force_tier      — dev/demo override: set in-process FORCE_TIER and re-resolve
  POST /orchestrator/run         — submit a goal + optional files; returns request_id immediately
  GET  /orchestrator/stream/{id} — SSE stream of agent progress for a running request
  GET  /audit/recent             — last N audit records (optionally filtered by request_id)
  GET  /outputs/{artifact_id}    — artifact download by UUID; path-traversal-safe

Security notes
--------------
- ``GET /outputs/{artifact_id}``:  artifact_id must match the pattern ``^[0-9a-f]{32}$``
  (32-character hex UUID4).  Requests with any other format return 400 immediately,
  before any registry or filesystem access.  No path components, separators, or
  ``..`` sequences can appear in a valid UUID hex string.
- Uploaded files land in UPLOADS_DIR (separate from generated OUTPUTS_DIR).
  Client-supplied filenames are sanitized: only the ``Path.name`` component
  is kept, a UUID prefix is prepended, and any remaining path traversal
  characters are stripped.

Async safety
------------
- All AuditLogger writes inside this router are called through
  ``AsyncAuditAdapter`` (asyncio.to_thread) so the blocking fcntl lock
  never runs on the event loop.
- Background orchestrator tasks push events to per-request ``asyncio.Queue``
  objects stored in ``_run_queues``.

Queue lifecycle (Fix #4)
------------------------
- The SSE generator checks ``await request.is_disconnected()`` each
  iteration and removes the queue from ``_run_queues`` on disconnect or
  after sending [DONE].
- The background task also pops its queue entry from ``_run_queues``
  when the run finishes, even if no SSE client is connected.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.artifacts.manager import get_artifact_manager

_log = logging.getLogger("sovereign.routers.orchestrator")

router = APIRouter()

# ---------------------------------------------------------------------------
# Directory constants
# ---------------------------------------------------------------------------

_BASE_DIR = Path(__file__).resolve().parent.parent.parent  # sovereign-workbench/
OUTPUTS_DIR = (_BASE_DIR / "outputs").resolve()
UPLOADS_DIR = (_BASE_DIR / "uploads").resolve()
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# In-process state — run queues and tier override
# ---------------------------------------------------------------------------

# Maps request_id → asyncio.Queue[dict].  Populated by orchestrator/run,
# drained by orchestrator/stream.  Cleaned up on [DONE] / disconnect.
_run_queues: dict[str, asyncio.Queue] = {}

# In-process force-tier override.  None = use env var / auto-detect.
# This is NOT written to the environment — it only affects resolve_startup_models()
# calls made while this process is alive.
_force_tier_override: Optional[str] = None

# ---------------------------------------------------------------------------
# Dependency helpers (injected from main.py at startup)
# ---------------------------------------------------------------------------

# These are populated by main.py calling setup_orchestrator_router() in its
# lifespan handler, so the router can access the singleton clients and loggers
# without importing main.py (circular).

_audit_logger = None          # AuditLogger singleton
_async_audit = None           # AsyncAuditAdapter wrapping _audit_logger
_vector_store = None          # VectorStore singleton (for KB-awareness in planning)
_router = None                # Router singleton (for dynamic model selection)


def setup_orchestrator_router(
    audit_logger,
    async_audit,
    orchestrator,
    startup_resolved: dict,
    startup_gpu_info: dict,
    vector_store=None,
    router=None,
) -> None:
    """Called once from main.py's lifespan to wire up singletons."""
    global _audit_logger, _async_audit, _orchestrator, _startup_resolved, _startup_gpu_info, _vector_store, _router
    _audit_logger = audit_logger
    _async_audit = async_audit
    _orchestrator = orchestrator
    _startup_resolved = startup_resolved
    _startup_gpu_info = startup_gpu_info
    _vector_store = vector_store
    _router = router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_filename(client_name: str) -> str:
    """
    Sanitize a client-supplied filename.

    Keeps only the final path component (``Path(name).name``), strips any
    remaining directory separators, and prepends a UUID so collisions are
    impossible.
    """
    safe = Path(client_name).name  # strip any directory prefix
    # Extra belt-and-suspenders: remove any remaining / \ .. chars
    safe = re.sub(r"[/\\]|\.\.", "", safe)
    safe = safe.strip(". ")
    if not safe:
        safe = "upload"
    return f"{uuid.uuid4().hex}_{safe}"


# 32-char lowercase hex UUID4 — the only valid artifact_id format.
# No path separators, dots, or traversal sequences can appear in this pattern.
_ARTIFACT_ID_RE = re.compile(r'^[0-9a-f]{32}$')


def _validate_artifact_id(artifact_id: str) -> None:
    """
    Raise ``HTTPException 400`` if *artifact_id* is not a valid 32-char hex UUID.

    This check runs before any registry or filesystem access, so malformed IDs
    are rejected instantly without touching the artifact store.
    """
    if not _ARTIFACT_ID_RE.match(artifact_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_artifact_id",
                "message": (
                    "artifact_id must be a 32-character lowercase hex UUID "
                    "(uuid4().hex format).  No path separators or dots allowed."
                ),
            },
        )


def _enrich_resolved_models(resolved: dict) -> list[dict]:
    """
    Convert {modality: model_name} → [{modality, model_name, ollama_tag, tier, est_vram_mb}].
    """
    from app.models.ollama_client import MODEL_REGISTRY

    result = []
    for modality, model_name in resolved.items():
        entry = MODEL_REGISTRY.get(model_name, {})
        result.append(
            {
                "modality": modality,
                "model_name": model_name,
                "ollama_tag": entry.get("ollama_tag", model_name),
                "tier": entry.get("tier", "unknown"),
                "est_vram_mb": entry.get("est_vram_mb", 0),
            }
        )
    return result


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/hardware/status", tags=["Hardware"])
async def hardware_status() -> dict:
    """
    Return detected VRAM, per-slot resolved tier, and the currently active
    model tag for each capability slot.

    This is what the UI's GPU panel reads on load and after a force-tier
    switch.  Always returns a coherent response — degraded state (CPU, no GPU)
    is surfaced explicitly, not hidden behind a generic "ready."
    """
    if _async_audit is not None:
        await _async_audit.log_event(
            __import__("app.audit.logger", fromlist=["EventType"]).EventType.AGENT_ACTION,
            request_id="SYSTEM_HARDWARE_STATUS",
            payload={"action": "hardware_status_queried"},
        )

    return {
        "gpu_info": _startup_gpu_info,
        "force_tier": _force_tier_override,
        "resolved_models": _enrich_resolved_models(_startup_resolved),
        "degraded": not _startup_gpu_info.get("gpu_available", False),
    }


@router.post("/hardware/force_tier", tags=["Hardware"])
async def force_tier(tier: str = Form(...)) -> dict:
    """
    DEV/DEMO MODE ONLY — force a specific tier for all model slots.

    Sets an in-process override (not an env var — does not persist across
    restarts) and re-runs the tier resolver with the forced tier.  The UI
    should show a transient warning that Ollama may take a moment to unload
    the previous model from VRAM.

    Valid values: ``small``, ``mid``, ``large``, ``default``, ``""``.
    Passing an empty string clears the override and re-runs auto-detection.
    """
    global _force_tier_override, _startup_resolved, _startup_gpu_info

    clean = tier.strip().lower() if tier.strip() else None
    _force_tier_override = clean

    try:
        from app.hardware.tier_resolver import resolve_startup_models
        from app.hardware.gpu_detect import detect_gpu

        new_resolved = resolve_startup_models(
            force_tier=clean,
            audit_logger=_audit_logger,
        )
        if clean:
            # When forced, gpu_detect was skipped; keep the startup gpu_info.
            new_gpu_info = _startup_gpu_info
        else:
            new_gpu_info = detect_gpu()
            _startup_gpu_info = new_gpu_info

        _startup_resolved = new_resolved
    except Exception as exc:
        _log.warning("force_tier re-resolve failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "resolve_failed", "message": str(exc)},
        )

    if _async_audit is not None:
        from app.audit.logger import EventType
        await _async_audit.log_event(
            EventType.AGENT_ACTION,
            request_id="SYSTEM_FORCE_TIER",
            payload={"action": "force_tier_applied", "tier": clean},
        )

    return {
        "applied_tier": clean,
        "resolved_models": _enrich_resolved_models(_startup_resolved),
        "vram_note": (
            "Tier switch applied. Ollama may take a moment to unload the "
            "previous model from VRAM before the new model is fully active."
        ) if clean else "Auto-detection restored.",
    }


@router.post("/orchestrator/run", tags=["Orchestrator"])
async def orchestrator_run(
    goal: str = Form(..., description="Natural-language goal for the agent"),
    files: list[UploadFile] = File(default=[]),
) -> dict:
    """
    Submit a goal to the full Plan→Act→Observe→Iterate agentic loop.

    File uploads land in ``uploads/`` (separate from generated ``outputs/``).
    File paths are passed to the orchestrator as structured context alongside
    the goal — NOT injected as bracketed text into the goal string.

    Returns immediately with a ``request_id``.  Poll
    ``GET /orchestrator/stream/{request_id}`` for live progress.
    """
    if _orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "orchestrator_not_ready",
                "message": "Orchestrator not initialised — check backend startup logs.",
            },
        )

    request_id = str(uuid.uuid4())

    # Save uploaded files with sanitized names into uploads/ (fix #2)
    saved_paths: list[str] = []
    for upload in files:
        if upload.filename:
            safe_name = _safe_filename(upload.filename)
            dest = UPLOADS_DIR / safe_name
            try:
                content = await upload.read()
                dest.write_bytes(content)
                saved_paths.append(str(dest))
                _log.info(
                    "Uploaded file saved: %s (%d bytes) request_id=%s",
                    dest.name,
                    len(content),
                    request_id,
                )
            except Exception as exc:
                _log.warning("File upload failed (%s): %s", upload.filename, exc)

    # Create the per-request queue before spawning the task so the SSE
    # endpoint can subscribe immediately.
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    _run_queues[request_id] = queue

    if _async_audit is not None:
        from app.audit.logger import EventType
        await _async_audit.log_event(
            EventType.AGENT_ACTION,
            request_id=request_id,
            payload={
                "action": "orchestrator_run_accepted",
                "goal_preview": goal[:120],
                "attached_files": saved_paths,
            },
        )

    async def _background_run() -> None:
        """Background coroutine: runs the orchestrator and cleans up the queue."""
        from app.orchestrator.streaming_runner import run_with_streaming
        try:
            await run_with_streaming(
                orchestrator=_orchestrator,
                goal=goal,
                queue=queue,
                request_id=request_id,
                attached_files=saved_paths,
                async_audit=_async_audit,
                vector_store=_vector_store,
                router=_router,
            )
        except Exception as exc:
            _log.exception(
                "Background orchestrator run failed (request_id=%s): %s",
                request_id,
                exc,
            )
            try:
                queue.put_nowait(
                    {
                        "type": "failed",
                        "request_id": request_id,
                        "payload": {"failure_summary": f"Unexpected error: {exc}"},
                    }
                )
                queue.put_nowait({"type": "done", "request_id": request_id, "payload": {}})
            except asyncio.QueueFull:
                pass
        finally:
            # Fix #4: clean up queue regardless of client connection state
            _run_queues.pop(request_id, None)
            _log.debug("Queue cleaned up for request_id=%s", request_id)

    asyncio.create_task(_background_run())

    return {
        "request_id": request_id,
        "status": "accepted",
        "goal_preview": goal[:120],
        "attached_files": saved_paths,
    }


@router.get("/orchestrator/stream/{request_id}", tags=["Orchestrator"])
async def orchestrator_stream(request_id: str, request: Request) -> StreamingResponse:
    """
    Server-Sent Events stream for an in-progress orchestrator run.

    Each event is a JSON object: ``{type, request_id, payload}``.
    Stream terminates with ``data: [DONE]\\n\\n`` when the run completes
    or fails, or if the client disconnects.

    The per-request queue is removed from ``_run_queues`` after [DONE]
    is sent or on client disconnect (Fix #4).
    """
    if request_id not in _run_queues:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "run_not_found",
                "message": (
                    f"No active run for request_id={request_id!r}.  "
                    "Either the run hasn't been submitted yet, or it already finished "
                    "and the queue was cleaned up."
                ),
            },
        )

    queue = _run_queues[request_id]

    async def _sse_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                # Fix #4: check for client disconnect
                if await request.is_disconnected():
                    _log.info(
                        "SSE client disconnected for request_id=%s — closing stream",
                        request_id,
                    )
                    break

                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # No event yet; loop back to check disconnect
                    yield ": keepalive\n\n"
                    continue

                event_type = item.get("type", "")
                yield f"data: {json.dumps(item)}\n\n"

                if event_type == "done":
                    yield "data: [DONE]\n\n"
                    break

        finally:
            # Fix #4: ensure queue is removed whether we broke out normally
            # or via an exception/disconnect
            _run_queues.pop(request_id, None)

    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )


@router.get("/audit/recent", tags=["Audit"])
async def audit_recent(
    request_id: Optional[str] = None,
    n: int = 50,
) -> dict:
    """
    Return the last *n* audit log entries, optionally filtered by ``request_id``.

    Also runs a chain-validity check on the entire log and returns the result
    so the UI can show a VERIFIED / BROKEN indicator.
    """
    if _audit_logger is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "audit_not_ready", "message": "AuditLogger not initialised."},
        )

    log_path = _audit_logger._path
    if not log_path.exists():
        return {"records": [], "chain_valid": True, "chain_errors": [], "total_scanned": 0}

    records: list[dict] = []
    total_scanned = 0

    try:
        with log_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                total_scanned += 1
                try:
                    rec = __import__("json").loads(raw)
                    if request_id is None or rec.get("request_id") == request_id:
                        records.append(rec)
                except Exception:
                    continue
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "audit_read_error", "message": str(exc)},
        )

    # Return last n matching records
    recent = records[-n:] if len(records) > n else records

    # Chain validity (run in thread — reads the whole file)
    try:
        chain_valid, chain_errors = await asyncio.to_thread(_audit_logger.verify_chain)
    except Exception as exc:
        chain_valid = False
        chain_errors = [str(exc)]

    return {
        "records": recent,
        "chain_valid": chain_valid,
        "chain_errors": chain_errors,
        "total_scanned": total_scanned,
        "returned": len(recent),
    }


@router.get("/outputs/{artifact_id}", tags=["Files"])
async def download_artifact(artifact_id: str) -> FileResponse:
    """
    Download a generated artifact (DOCX, PPTX, XLSX) by its UUID.

    Security
    --------
    1. ``artifact_id`` is validated against ``^[0-9a-f]{32}$`` before any
       registry or filesystem access.  Invalid format → 400.
    2. The artifact is looked up in the in-process ``ArtifactManager`` registry.
       Unknown ID → 404.
    3. The physical file path is accessed from the registry internally — it is
       NEVER received from or sent to the client.
    """
    # Step 1: UUID format validation — rejects traversal, dots, slashes instantly
    _validate_artifact_id(artifact_id)

    # Step 2: Registry lookup
    artifact = get_artifact_manager().get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "artifact_not_found",
                "artifact_id": artifact_id,
                "message": (
                    "Artifact not found.  The server may have restarted since the "
                    "file was generated, or the ID is incorrect."
                ),
            },
        )

    # Step 3: Serve — physical_path accessed internally, never exposed to client
    return FileResponse(
        path=artifact.physical_path,
        media_type=artifact.mime_type,
        filename=artifact.filename,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )
