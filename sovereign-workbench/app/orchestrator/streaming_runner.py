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
``artifact_created``— a docgen tool succeeded and the artifact is registered;
                      payload is ``Artifact.to_dict()`` (no physical_path).
``artifact_failed`` — artifact registration failed after the document was written
                      (storage error, sanitization error, etc.); payload has
                      ``filename`` and ``error``.  Note: normal doc-gen tool
                      failures emit ``step_done(success=False)``, NOT this event.
``synthesis_start`` — final synthesis LLM call beginning.
``completed``       — run finished; payload has ``final_output``,
                      ``sources`` (RAG citations extracted), ``artifacts`` (list of
                      Artifact.to_dict() for all generated files).
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
SSE_ARTIFACT_CREATED = "artifact_created"  # fired immediately when a docgen tool succeeds
SSE_ARTIFACT_FAILED  = "artifact_failed"   # fired only for artifact registration failures
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


def _extract_artifacts(run: OrchestratorRun) -> list[dict]:
    """
    Collect artifact dicts from step outcomes that have ``metadata["artifact"]``.

    Uses explicit metadata inspection — no string-path heuristics.
    Returns a list of ``Artifact.to_dict()`` payloads (no ``physical_path``).
    """
    artifacts: list[dict] = []
    seen: set[str] = set()
    for outcome in run.outcomes:
        if not outcome.success:
            continue
        art = outcome.metadata.get("artifact") if outcome.metadata else None
        if not isinstance(art, dict):
            continue
        artifact_id = art.get("artifact_id")
        if artifact_id and artifact_id not in seen:
            seen.add(artifact_id)
            artifacts.append(art)
    return artifacts


# Spreadsheet extensions that should always trigger analyze_spreadsheet
_SPREADSHEET_EXTS = frozenset({".xlsx", ".xls", ".csv"})


def _classify_attached_files(attached_files: list[str]) -> dict:
    """
    Classify attached files by category.

    Returns a dict with keys:
      'spreadsheets' — paths with .xlsx/.xls/.csv extension
      'others'       — everything else
    """
    from pathlib import Path as _Path
    result: dict = {"spreadsheets": [], "others": []}
    for p in attached_files:
        ext = _Path(p).suffix.lower()
        if ext in _SPREADSHEET_EXTS:
            result["spreadsheets"].append(p)
        else:
            result["others"].append(p)
    return result


def _build_augmented_plan_messages(
    goal: str,
    attached_files: list[str],
    kb_docs: Optional[list[str]] = None,
) -> list[dict]:
    """
    Build planning messages with an explicit attached-files block
    so the planner sees them as structured context, not text to parse.

    When spreadsheet files (.xlsx/.xls/.csv) are present, the prompt includes
    an explicit MANDATORY directive that overrides the general-knowledge shortcut
    rule — this is the fix for the priority-ordering regression where the planner
    was firing the empty-plan general-knowledge path instead of calling
    analyze_spreadsheet.

    kb_docs:
        Optional list of document names currently indexed in the knowledge base.
        Injected as a KB AWARENESS block so the planner knows when rag_search
        is mandatory.
    """
    classified = _classify_attached_files(attached_files)
    spreadsheets = classified["spreadsheets"]
    others = classified["others"]

    augmented_goal = goal
    if attached_files:
        file_block = "\n".join(f"  - {p}" for p in attached_files)
        augmented_goal = (
            f"{goal}\n\n"
            f"Attached files available for tool use (use exact paths in tool_args):\n"
            f"{file_block}"
        )

    if spreadsheets:
        # Explicit override: the general-knowledge / empty-plan rule must NOT
        # fire when a spreadsheet is present. Give the planner a concrete
        # mandatory step so it cannot return [].
        spreadsheet_block = "\n".join(f"  - {p}" for p in spreadsheets)
        augmented_goal += (
            "\n\n"
            "MANDATORY OVERRIDE — A spreadsheet file has been uploaded. "
            "You MUST include an 'analyze_spreadsheet' step in your plan. "
            "Do NOT return an empty array []. "
            "The GENERAL KNOWLEDGE RULE does not apply when files are attached. "
            "Set tool_args.file_path to the exact path below:\n"
            f"{spreadsheet_block}"
        )

    # _build_plan_messages already injects the KB AWARENESS block when kb_docs is
    # provided (see orchestrator.py).  We don't need to duplicate it here; the
    # CODE TASK RULE guard added there covers this path too.
    messages = _build_plan_messages(augmented_goal, kb_docs=kb_docs)
    return messages


def _fetch_kb_doc_names(
    vector_store: Any,
    collection: str = "sovereign_knowledge_base",
    limit: int = 500,
) -> list[str]:
    """
    Fetch the distinct document names currently indexed in Qdrant.

    Returns a deduplicated list of ``doc_name`` values (PDF basenames, etc.)
    from the collection payload.  Returns an empty list on any error so a
    Qdrant hiccup never blocks the orchestrator.
    """
    try:
        points, _ = vector_store._client.scroll(
            collection_name=collection,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        seen: set[str] = set()
        names: list[str] = []
        for p in points:
            payload = p.payload or {}
            doc_name = payload.get("doc_name") or ""
            if doc_name and doc_name not in seen:
                seen.add(doc_name)
                names.append(doc_name)
        return names
    except Exception as exc:
        _log.warning("Could not fetch KB doc names from Qdrant: %s", exc)
        return []


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
    vector_store: Optional[Any] = None,
    router: Optional[Any] = None,
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
    vector_store:
        Optional :class:`~app.rag.store.VectorStore` instance.  When provided,
        the list of currently-indexed document names is fetched from Qdrant
        and injected into the planning prompt as a KB AWARENESS block so the
        planner knows to call ``rag_search`` for questions about those documents
        instead of falling back to general knowledge.
    router:
        Optional :class:`~app.router.router.Router` instance. When provided,
        routes the goal to the optimal model (e.g. coder LLM for coding tasks,
        general text model for text/reasoning) before planning and synthesis.

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

    # ── Model Routing: select the best model for this context ─────────────
    routed_client = orchestrator._llm
    capability_label: Optional[str] = None
    if router is not None:
        try:
            decision = await router.route(
                goal,
                request_id=request_id,
                attached_filenames=attached_files,
            )
            capability_label = decision.capability
            from app.models.ollama_client import OllamaClient
            if isinstance(orchestrator._llm, OllamaClient):
                if getattr(orchestrator._llm, "_model_cfg", {}).get("name") == decision.model_name:
                    routed_client = orchestrator._llm
                else:
                    routed_client = OllamaClient(
                        model_name=decision.model_name,
                        audit_logger=orchestrator._audit,
                    )
            else:
                routed_client = orchestrator._llm
            _push(
                queue,
                "model_routed",
                request_id,
                {
                    "model_name": decision.model_name,
                    "ollama_tag": decision.ollama_tag,
                    "capability": decision.capability,
                    "stage": decision.stage,
                    "reason": decision.reason,
                },
            )
            _log.info(
                "Goal routed to model=%s capability=%s (request_id=%s)",
                decision.model_name,
                decision.capability,
                request_id,
            )
        except Exception as exc:
            _log.warning(
                "Router call failed (request_id=%s): %s — using default LLM",
                request_id,
                exc,
            )

    # ── Fetch KB document names for planner awareness ──────────────────────
    # Retrieve the list of ingested document names from Qdrant so the planner
    # prompt includes a KB AWARENESS block.  This prevents the planner from
    # choosing the GENERAL KNOWLEDGE path for questions about ingested docs.
    kb_docs: list[str] = []
    if vector_store is not None:
        kb_docs = await asyncio.get_event_loop().run_in_executor(
            None, _fetch_kb_doc_names, vector_store
        )
        if kb_docs:
            _log.info(
                "KB awareness: %d document(s) injected into planning prompt (request_id=%s): %s",
                len(kb_docs),
                request_id,
                kb_docs[:10],
            )

    # ── PLANNING ──────────────────────────────────────────────────────────
    run.status = OrchestratorStatus.PLANNING
    try:
        if attached_files:
            messages = _build_augmented_plan_messages(goal, attached_files, kb_docs=kb_docs)
        else:
            messages = _build_plan_messages(goal, kb_docs=kb_docs)

        resp = await routed_client.chat_completion(
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

    # ── FIX: Guard against the general-knowledge shortcut when files exist ──
    # If the planner returned an empty plan but spreadsheet files are attached,
    # the model wrongly triggered the general-knowledge fallback instead of
    # calling analyze_spreadsheet.  Force-inject the correct tool step.
    if not plan and attached_files:
        classified = _classify_attached_files(attached_files)
        if classified["spreadsheets"]:
            _log.warning(
                "Planner returned empty plan despite attached spreadsheet(s) "
                "(request_id=%s) — force-injecting analyze_spreadsheet step",
                request_id,
            )
            from app.orchestrator.state import PlannedStep as _PlannedStep
            plan = [
                _PlannedStep(
                    step_index=0,
                    tool_name="analyze_spreadsheet",
                    tool_args={"file_path": classified["spreadsheets"][0]},
                    description="Analyze the uploaded spreadsheet file and produce a summary.",
                )
            ]

    # ── FIX: Auto-fill file_path when planner emits step but omits the arg ─
    # The planner may correctly choose analyze_spreadsheet but leave file_path
    # empty or missing.  If exactly one spreadsheet is attached, fill it in.
    if attached_files:
        classified = _classify_attached_files(attached_files)
        if classified["spreadsheets"]:
            for step in plan:
                if step.tool_name == "analyze_spreadsheet" and not step.tool_args.get("file_path"):
                    step.tool_args["file_path"] = classified["spreadsheets"][0]
                    _log.info(
                        "Auto-filled file_path=%s for analyze_spreadsheet step "
                        "(request_id=%s)",
                        classified["spreadsheets"][0],
                        request_id,
                    )

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
        run.final_output = await orchestrator._synthesise(
            goal,
            run,
            llm_client=routed_client,
            capability=capability_label,
        )
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
                metadata=result.metadata or {},
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

                # ── Emit artifact_created immediately for docgen steps ─────────
                # metadata["artifact"] is set by generate_docx/pptx/xlsx tools
                # only when registration succeeded.  Physical_path is NOT in it.
                art = result.metadata.get("artifact") if result.metadata else None
                if isinstance(art, dict):
                    _push(queue, SSE_ARTIFACT_CREATED, request_id, art)

            else:
                # ── Emit artifact_failed for registration failures only ────────
                # metadata["artifact_error"] is set when the document was written
                # but ArtifactManager.register_artifact() raised ArtifactError.
                # Normal doc-gen tool failures (invalid input, library crash) only
                # produce step_done(success=False) — they do NOT set artifact_error.
                art_err = result.metadata.get("artifact_error") if result.metadata else None
                if isinstance(art_err, dict):
                    _push(queue, SSE_ARTIFACT_FAILED, request_id, art_err)

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

    run.final_output = await orchestrator._synthesise(
        goal,
        run,
        llm_client=routed_client,
        capability=capability_label,
    )

    sources = _extract_sources(run)
    artifacts = _extract_artifacts(run)

    _push(
        queue,
        SSE_COMPLETED,
        request_id,
        {
            "final_output": run.final_output,
            "sources": sources,
            "artifacts": artifacts,
        },
    )
    _push(queue, SSE_DONE, request_id, {})

    await _alog(
        EventType.AGENT_ACTION,
        "run_completed",
        {"final_output_length": len(run.final_output or "")},
    )
    return run
