"""
audit/async_adapter.py
======================
Async-safe wrapper around the synchronous ``AuditLogger``.

Problem
-------
``AuditLogger._write_record()`` holds an OS-level ``fcntl.LOCK_EX`` while
flushing + fsyncing the log file.  That is a blocking syscall.  Calling it
directly from inside an ``asyncio`` coroutine (e.g. from an SSE-streaming
background task) stalls the event loop for every log write — unacceptable
once Phase E introduces multiple concurrent SSE streams.

Solution
--------
``AsyncAuditAdapter`` exposes the same public interface as ``AuditLogger``
but delegates every write through ``asyncio.to_thread()``, so the blocking
flock/flush/fsync happens on a thread-pool worker while the event loop
remains free.

Usage
-----
    from app.audit.async_adapter import AsyncAuditAdapter

    # Wrap the singleton that was created at startup:
    async_audit = AsyncAuditAdapter(audit_logger)

    # Then inside any coroutine:
    await async_audit.log_event(EventType.AGENT_ACTION, request_id=rid, payload={...})

The underlying ``AuditLogger`` is unchanged — existing synchronous callers
(test suite, startup code, sandbox router) keep calling it directly.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from app.audit.logger import AuditLogger, EventType


class AsyncAuditAdapter:
    """
    Async wrapper around :class:`AuditLogger`.

    Every method ``await``s ``asyncio.to_thread(...)`` so that the
    blocking ``fcntl`` exclusive-lock write never runs on the event loop.

    Parameters
    ----------
    logger:
        The synchronous ``AuditLogger`` singleton created at startup.
    """

    def __init__(self, logger: AuditLogger) -> None:
        self._logger = logger

    # ------------------------------------------------------------------
    # Public async API — mirrors AuditLogger's sync API
    # ------------------------------------------------------------------

    async def log_model_call(
        self,
        *,
        request_id: str,
        model_name: str,
        ollama_tag: str,
        endpoint: str,
        prompt_tokens: int,
        response_tokens: int,
        latency_ms: float,
        status: str,
        error_message: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Async wrapper around :meth:`AuditLogger.log_model_call`."""
        await asyncio.to_thread(
            self._logger.log_model_call,
            request_id=request_id,
            model_name=model_name,
            ollama_tag=ollama_tag,
            endpoint=endpoint,
            prompt_tokens=prompt_tokens,
            response_tokens=response_tokens,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
            extra=extra,
        )

    async def log_event(
        self,
        event_type: EventType,
        *,
        request_id: str,
        payload: dict[str, Any],
    ):
        """Async wrapper around :meth:`AuditLogger.log_event`.

        Returns the created ``AuditRecord`` (same as the sync logger),
        so callers that need to inspect the written record can do so.
        """
        return await asyncio.to_thread(
            self._logger.log_event,
            event_type,
            request_id=request_id,
            payload=payload,
        )

    async def log_error(
        self,
        *,
        request_id: str,
        error_type: str,
        message: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> None:
        """Async wrapper around :meth:`AuditLogger.log_error`."""
        await asyncio.to_thread(
            self._logger.log_error,
            request_id=request_id,
            error_type=error_type,
            message=message,
            extra=extra,
        )

    # ------------------------------------------------------------------
    # Pass-through for synchronous helpers (verify_chain, etc.)
    # ------------------------------------------------------------------

    def verify_chain(self) -> tuple[bool, list[str]]:
        """Synchronous chain verification — safe to call from non-async code."""
        return self._logger.verify_chain()

    @property
    def path(self):
        """Expose the underlying log file path for diagnostics."""
        return self._logger._path
