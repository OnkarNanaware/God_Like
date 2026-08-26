"""
orchestrator/streaming_runner.py
=================================
SSE-aware orchestrator runner.

Purpose
-------
Wraps ``Orchestrator.run()`` to publish structured events to a caller-supplied
``asyncio.Queue`` at each state transition, without modifying the core
``Orchestrator`` class.  The FastAPI SSE endpoint drains that queue as events
arrive and forwards them to the browser.

Event schema
------------
Every item pushed to the queue is a ``dict`` with the shape::

    {
        "type": str,         # one of the SSE_* constants below
        "request_id": str,
        "payload": dict      # event-specific data
    }

The sentinel ``{"type": "done"}`` marks the end of the stream.

Event types
-----------
``plan_ready``      — planning complete; payload has ``steps`` list.
``step_start``      — a tool dispatch is starting; payload has ``step_index``,
                      ``tool_name``, ``tool_args``, ``description``, ``attempt``.
``step_done``       — a tool returned; payload adds ``success``, ``output_preview``,
                      ``error`` (if failed).
``retry``           — a step is being retried; payload has ``step_index``,
                      ``tool_name``, ``attempt``, ``error``.
``synthesis_start`` — final synthesis LLM call beginning.
``completed``       — run finished; payload has ``final_output``,
                      ``sources`` (RAG citations extracted), ``output_files``.
``failed``          — run failed; payload has ``failure_summary``.
``done``            — sentinel; queue consumer should stop.

Structured file context
-----------------------
``attached_files`` is a separate list of validated local paths (not injected
into the goal text).  When present, the planning prompt is augmented with an
explicit "Attached files" block so the planner can reference them by path in
``tool_args`` without relying on the model noticing a bracketed string
embedded in free text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Optional

from app.audit.async_adapter import AsyncAuditAdapter
from app.audit.logger import AuditLogger, EventType
from app.orchestrator.orchestrator import (
    Orchestrator,
    _build_plan_messages,
    _build_replan_messages,
    _build_synthesis_messages,
    _parse_plan,
    _tools_json_str,
    MAX_RETRIES,
)
from app.orchestrator.state import (
    OrchestratorRun,
    OrchestratorStatus,
    PlannedStep,
    StepOutcome,
)
from app.tools.base import ToolResult
from app.tools.registry import TOOL_REGISTRY, get_tool, list_tools

_log = logging.getLogger("sovereign.streaming_runner")

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

SSE_PLAN_READY = "plan_ready"
SSE_STEP_START = "step_start"
SSE_STEP_DONE = "step_done"
SSE_RETRY = "retry"
SSE_SYNTHESIS_START = "synthesis_start"
SSE_COMPLETED = "completed"
SSE_FAILED = "failed"
SSE_FALLBACK = "fallback"
SSE_DONE = "done"  # terminal sentinel


def _push(queue: asyncio.Queue, event_type: str, request_id: str, payload: dict) -> None:
    """Non-blocking queue put — drops the event if the queue is full (shouldn't happen)."""
    item = {"type": event_type, "request_id": request_id, "payload": payload}
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        _log.warning("SSE queue full for request_id=%s — event dropped: %s", request_id, event_type)


def _extract_sources(run: OrchestratorRun) -> list[dict]:
    """
    Pull RAG-grounded citations out of step outputs for the UI.

    Looks for dicts in tool outputs that have ``doc_name`` / ``source`` and
    optionally ``page_number`` / ``score`` fields — the shape that
    ``RagSearchTool`` returns.
    """
    sources: list[dict] = []
    seen: set[str] = set()
    for outcome in run.outcomes:
        if not outcome.success or outcome.output is None:
            continue
        raw = outcome.output
        items: list[Any] = []
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = raw.get("results", [raw])
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("doc_name") or item.get("source") or item.get("name")
            if not name:
                continue
            key = f"{name}:{item.get('page_number', '')}"
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                {
                    "name": name,
                    "page_number": item.get("page_number"),
                    "score": item.get("score"),
                    "note": item.get("text", "")[:200] if item.get("text") else None,
                }
            )
    return sources


def _extract_output_files(run: OrchestratorRun) -> list[str]:
    """
    Collect file paths produced by doc-gen / sandbox tools for UI download links.

    Looks for string outputs that look like local file paths ending in
    .docx / .pptx / .xlsx / .py / .js (the output types Phase D can produce).
    """
    file_exts = {".docx", ".pptx", ".xlsx", ".py", ".js", ".ts", ".txt"}
    files: list[str] = []
    seen: set[str] = set()
    for outcome in run.outcomes:
        if not outcome.success or outcome.output is None:
            continue
        raw = outcome.output
        candidates: list[str] = []
        if isinstance(raw, str):
            candidates = [raw.strip()]
        elif isinstance(raw, dict):
            for v in raw.values():
                if isinstance(v, str):
                    candidates.append(v.strip())
        for c in candidates:
            from pathlib import Path as _Path
            try:
                p = _Path(c)
                if p.suffix.lower() in file_exts and c not in seen:
                    seen.add(c)
                    files.append(c)
            except Exception:
                pass
    return files


def _build_augmented_plan_messages(goal: str, attached_files: list[str]) -> list[dict]:
    """
    Build planning messages with an explicit attached-files block
    so the planner sees them as structured context, not text to parse.
    """
    from app.orchestrator.orchestrator import _PLANNING_SYSTEM_PROMPT
    augmented_goal = goal
    if attached_files:
        file_block = "\n".join(f"  - {p}" for p in attached_files)
        augmented_goal = (
            f"{goal}\n\n"
            f"Attached files available for tool use (use exact paths in tool_args):\n"
            f"{file_block}"
        )
    messages = _build_plan_messages(augmented_goal)
    return messages


# ---------------------------------------------------------------------------
# Public runner
# ---------------------------------------------------------------------------


async def run_with_streaming(
    orchestrator: Orchestrator,
    goal: str,
    queue: asyncio.Queue,
    *,
    request_id: Optional[str] = None,
    attached_files: Optional[list[str]] = None,
    async_audit: Optional[AsyncAuditAdapter] = None,
) -> OrchestratorRun:
    """
    Run the orchestrator and push SSE events to *queue* at each transition.

    Parameters
    ----------
    orchestrator:
        Configured ``Orchestrator`` instance (with its LLM client and sync audit logger).
    goal:
        Natural-language goal from the user.
    queue:
        ``asyncio.Queue`` that the SSE endpoint will drain.
    request_id:
        Correlation ID.  Generated if omitted.
    attached_files:
        List of validated local file paths (from uploads/).  Passed as
        structured context to the planning prompt — NOT injected into
        the goal text.
    async_audit:
        Optional :class:`AsyncAuditAdapter` for non-blocking audit writes
        inside this coroutine.  If ``None``, audit writes are skipped here
        (the orchestrator's own sync writes still happen via its internal
        ``_log()`` calls).

    Returns
    -------
    The completed (or failed) ``OrchestratorRun``.
    """
    request_id = request_id or str(uuid.uuid4())
    attached_files = attached_files or []
    run = OrchestratorRun(request_id=request_id, goal=goal)

    async def _alog(event_type: EventType, action: str, extra: dict) -> None:
        if async_audit is None:
            return
        payload = {"action": action, "status": run.status.value, "goal_preview": goal[:120]}
        payload.update(extra)
        await async_audit.log_event(event_type, request_id=request_id, payload=payload)

    # ── PLANNING ──────────────────────────────────────────────────────────
    run.status = OrchestratorStatus.PLANNING
    try:
        if attached_files:
            messages = _build_augmented_plan_messages(goal, attached_files)
        else:
            messages = _build_plan_messages(goal)

        resp = await orchestrator._llm.chat_completion(
            messages,
            request_id=request_id,
            temperature=0.0,
            max_tokens=1024,
        )
        plan = _parse_plan(resp.content)
    except Exception as exc:
        run.status = OrchestratorStatus.FAILED
        run.failure_summary = f"Planning failed: {exc}"
        _push(queue, SSE_FAILED, request_id, {"failure_summary": run.failure_summary})
        _push(queue, SSE_DONE, request_id, {})
        await _alog(EventType.AGENT_ACTION, "planning_failed", {"error": str(exc)})
        return run

    run.plan = plan
    _push(
        queue,
        SSE_PLAN_READY,
        request_id,
        {
            "step_count": len(plan),
            "steps": [
                {
                    "step_index": s.step_index,
                    "tool_name": s.tool_name,
                    "description": s.description,
                }
                for s in plan
            ],
        },
    )
    await _alog(
        EventType.AGENT_ACTION,
        "plan_produced",
        {"step_count": len(plan)},
    )

    if not plan:
        run.status = OrchestratorStatus.COMPLETED
        _push(queue, SSE_SYNTHESIS_START, request_id, {})
        run.final_output = await orchestrator._synthesise(goal, run)
        _push(
            queue,
            SSE_COMPLETED,
            request_id,
            {
                "final_output": run.final_output,
                "sources": [],
                "output_files": [],
            },
        )
        _push(queue, SSE_DONE, request_id, {})
        return run

    # ── ACT / OBSERVE / RETRY loop ─────────────────────────────────────────
    step_index = 0
    while step_index < len(run.plan):
        step = run.plan[step_index]
        attempt = 0
        step_done = False

        while not step_done and attempt < orchestrator._max_retries:
            attempt += 1
            run.status = OrchestratorStatus.ACTING

            # Emit step_start
            _push(
                queue,
                SSE_STEP_START,
                request_id,
                {
                    "step_index": step.step_index,
                    "tool_name": step.tool_name,
                    "tool_args": step.tool_args,
                    "description": step.description,
                    "attempt": attempt,
                },
            )

            # Dispatch to tool (reuse orchestrator's _act method)
            result = await orchestrator._act(step, run, attempt)

            run.status = OrchestratorStatus.OBSERVING
            outcome = StepOutcome(
                step_index=step.step_index,
                tool_name=step.tool_name,
                tool_args=step.tool_args,
                success=result.success,
                output=result.output,
                error=result.error,
                attempt=attempt,
            )
            run.outcomes.append(outcome)

            # Emit step_done
            output_preview = (
                str(result.output)[:500] if result.output is not None else None
            )
            _push(
                queue,
                SSE_STEP_DONE,
                request_id,
                {
                    "step_index": step.step_index,
                    "tool_name": step.tool_name,
                    "attempt": attempt,
                    "success": result.success,
                    "output_preview": output_preview,
                    "error": result.error,
                },
            )

            if result.success:
                snippet = (
                    f"[Step {step.step_index} — {step.tool_name}]:\n"
                    f"{str(result.output)[:4000]}"
                )
                run.context_snippets.append(snippet)
                step_done = True

            else:
                if attempt < orchestrator._max_retries:
                    run.status = OrchestratorStatus.REPLANNING
                    _push(
                        queue,
                        SSE_RETRY,
                        request_id,
                        {
                            "step_index": step.step_index,
                            "tool_name": step.tool_name,
                            "attempt": attempt,
                            "error": result.error,
                        },
                    )
                    try:
                        revised = await orchestrator._replan(
                            goal, step, result.error or "unknown error", run
                        )
                        run.plan = run.plan[:step_index] + revised
                        step = run.plan[step_index]
                    except Exception as exc:
                        _log.warning(
                            "Re-plan failed (request_id=%s): %s", request_id, exc
                        )
                else:
                    run.status = OrchestratorStatus.FAILED
                    run.failure_summary = (
                        f"Step {step.step_index} ('{step.tool_name}') failed "
                        f"after {orchestrator._max_retries} attempts.  "
                        f"Last error: {result.error}"
                    )
                    _push(
                        queue,
                        SSE_FAILED,
                        request_id,
                        {"failure_summary": run.failure_summary},
                    )
                    _push(queue, SSE_DONE, request_id, {})
                    return run

        step_index += 1

    # ── SYNTHESIS ──────────────────────────────────────────────────────────
    run.status = OrchestratorStatus.COMPLETED
    _push(queue, SSE_SYNTHESIS_START, request_id, {})

    run.final_output = await orchestrator._synthesise(goal, run)

    sources = _extract_sources(run)
    output_files = _extract_output_files(run)

    _push(
        queue,
        SSE_COMPLETED,
        request_id,
        {
            "final_output": run.final_output,
            "sources": sources,
            "output_files": output_files,
        },
    )
    _push(queue, SSE_DONE, request_id, {})

    await _alog(
        EventType.AGENT_ACTION,
        "run_completed",
        {"final_output_length": len(run.final_output or "")},
    )
    return run
