"""
orchestrator/orchestrator.py
============================
Plan → Act → Observe → Iterate state machine.

Control flow
------------

  PLANNING
    │  LLM produces a list of tool steps (JSON).
    ▼
  ACTING  (for each step in plan)
    │  Dispatch to tool from TOOL_REGISTRY.
    ▼
  OBSERVING
    │  ToolResult.success=True  → accumulate output, advance to next step.
    │  ToolResult.success=False → feed error back, increment retry counter.
    │       retry < MAX_RETRIES → REPLANNING (re-plan from current step)
    │       retry == MAX_RETRIES → FAILED (halt, return failure_summary)
    ▼
  COMPLETED  (all steps succeeded)
    │  LLM synthesises a final answer from accumulated step outputs.
    ▼
  return OrchestratorRun

Mockability
-----------
The orchestrator accepts any object satisfying ``LLMOrchestratorProtocol``
(same structural shape as ``OllamaClient.chat_completion``).  Pass a
``FakeOllamaClient`` in tests — no live Ollama required.

Audit logging
-------------
Every state transition, tool dispatch, tool result, retry, and final output
is recorded in the audit log with the same ``request_id`` that was passed
in, so a full run is traceable as a single correlated sequence.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional, Protocol, runtime_checkable

from app.audit.logger import AuditLogger, EventType
from app.orchestrator.state import (
    OrchestratorRun,
    OrchestratorStatus,
    PlannedStep,
    StepOutcome,
)
from app.tools.base import ToolResult
from app.tools.registry import TOOL_REGISTRY, get_tool, list_tools

_log = logging.getLogger("sovereign.orchestrator")

MAX_RETRIES: int = 3  # per step — after this the run halts with FAILED


# ---------------------------------------------------------------------------
# Protocol — same structural contract as OllamaClient.chat_completion
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMOrchestratorProtocol(Protocol):
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        request_id: Optional[str] = None,
        temperature: float = ...,
        max_tokens: int = ...,
        extra_body: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Must return an object with a ``.content: str`` attribute."""
        ...


# ---------------------------------------------------------------------------
# Planning prompt builders
# ---------------------------------------------------------------------------

_PLANNING_SYSTEM_PROMPT = """\
You are the planning component of an AI agent. Given a goal and a list of \
available tools, produce a JSON array of steps to accomplish the goal.

Available tools:
{tools_json}

Output format — a JSON array, NOTHING else, no markdown fences:
[
  {{
    "step_index": 0,
    "tool_name": "<EXACT tool name from the list above>",
    "tool_args": {{<keyword args matching the tool's input_schema>}},
    "description": "<one sentence: why this step is needed>"
  }},
  ...
]

DELIVERABLE GENERATION RULES — these are mandatory, read carefully:

The tools generate_docx, generate_pptx, and generate_xlsx (collectively
"generation tools") produce files that are delivered to the user as
downloads. They MUST appear in the plan ONLY when the user's goal explicitly
requests a file or document as output.

Phrases that ARE explicit generation requests (generation tool ALLOWED):
  "prepare an approval note", "give me the inspection report as a Word file",
  "generate a document", "save this as a spreadsheet", "create a report",
  "produce a .docx", "write out the findings as a file", "download this",
  "I need a Word document", "make a PowerPoint", "export as Excel"

Phrases that are NOT generation requests — answer in chat only, NO generation step:
  "what does this report say", "summarize the findings", "is this compliant",
  "check this against the SOP", "tell me the key issues", "explain this document",
  "what are the recommendations", "analyse this spreadsheet", "what does X mean",
  or any question whose answer fits naturally in a text response

AMBIGUITY RULE:
If the user's request is not unambiguously asking for a file or document as output
(e.g., the phrasing is ambiguous, or the goal is equally a chat/analysis task),
do NOT include any generation tool in the plan. Default to answering in chat only.
Only include a generation tool (generate_docx, generate_pptx, generate_xlsx) when
the user is unambiguously asking for a file as a deliverable.

GENERAL KNOWLEDGE RULE:
Return an EMPTY array [] ONLY for trivial greetings (e.g. "hello"), basic math (e.g. "what is 2+2"), or pure general chat that has no relation to any system, architecture, report, or technical topic.

CODE TASK RULE:
If the goal is explicitly a pure programming, scripting, or debugging task — such as:
  "write a function to reverse a string", "debug this traceback", "implement binary search in Python",
  "write a script to parse CSV"
— use the 'code_sandbox' tool. Do NOT call rag_search for standalone generic programming requests.

RAG SEARCH RULE:
If the goal asks about ANY project, system architecture, internal knowledge, concept, design (e.g. "explain SignBridge architecture"), report, standard, policy, SOP, audit, compliance, inspection, or organisation topic:
You MUST call 'rag_search' with tool_args: {{"query": "<concise search query>"}}.
Always search the internal knowledge base for domain, project, or document questions to retrieve grounded context.

BUDGET / APPROVAL NOTE RULE — READ CAREFULLY:
When the user uploads a spreadsheet (.xlsx, .xls, .csv) and requests an approval note
or similar financial document:
1. Call analyze_spreadsheet first (file_path = the uploaded file's absolute path).
2. Call generate_docx with document_type="approval_note" AND pass
   source_spreadsheet_path = <same uploaded file path>.
   The tool will read the spreadsheet and auto-populate the financial rows and total.
   Do NOT hard-code financial_rows as an empty list [].
   Do NOT invent line items or amounts.
   Pass approval_data with the non-financial fields only (date, to, from_, subject, etc.).

CRITICAL RULES — violating any of these will cause the agent to fail:
- Output only the JSON array. No prose, no markdown fences, no code blocks.
- You MUST use only tool names that appear EXACTLY in the available tools list above.
- Do NOT invent tool names. Do NOT use 'text_summarize', 'web_search', or any \
tool not explicitly listed.
- tool_args keys must match the required fields in each tool's input_schema exactly.
- Keep the plan minimal — fewest steps that accomplish the goal.
- If reading a file is needed, use 'file_read' with a 'path' argument.\
""".strip()


_REPLAN_SYSTEM_PROMPT = """\
You are the re-planning component of an AI agent. A previous step failed. \
Produce a revised JSON array of remaining steps.

Available tools (use ONLY these — do NOT invent tool names):
{tools_json}

Failed step:
  tool_name: {tool_name}
  tool_args: {tool_args}
  error: {error}

Remaining goal context:
{goal}

Output format — a JSON array of remaining steps (same schema as before, NO markdown \
fences), NOTHING else.
Use ONLY tool names that appear exactly in the available tools list above.
""".strip()

_SYNTHESIS_SYSTEM_PROMPT = """\
You are the synthesis component of an AI agent. Given the original goal and \
the outputs of all completed steps, produce a final response that directly \
addresses the goal.

Be concise. Refer to specific findings from the tool outputs where relevant.

IMPORTANT: if the tool outputs section is empty or absent (no tools were called \
because the question can be answered directly from general knowledge), produce \
a direct, helpful answer from your own knowledge. ALWAYS prefix such answers with:

⚠️ General knowledge — not from an internal document.

Answers derived from retrieved internal documents should NOT include this prefix.
""".strip()

_DIRECT_ANSWER_SYSTEM_PROMPT = """\
You are a knowledgeable assistant. The user has asked a general question that \
does not require any internal documents, files, or tools to answer. Answer \
directly, clearly, and helpfully from your own knowledge.

ALWAYS start your response with:
⚠️ General knowledge — not from an internal document.

Then provide the answer on the next line.
""".strip()

_CODE_ANSWER_SYSTEM_PROMPT = """\
You are an expert software engineer and technical assistant. The user has asked a programming or code-related question. Provide clean, robust, efficient, and well-structured code with concise explanations. Answer directly and authoritatively.
""".strip()


def _tools_json_str() -> str:
    return json.dumps(list_tools(), indent=2)


def _build_plan_messages(
    goal: str,
    kb_docs: Optional[list[str]] = None,
) -> list[dict[str, str]]:
    """
    Build planning messages for the LLM.

    Parameters
    ----------
    goal:
        The user's natural-language goal.
    kb_docs:
        Optional list of document names currently in the knowledge base
        (e.g. ["amcat.pdf", "oisd_guide.pdf"]).  When provided, a
        KB AWARENESS block is injected into the user message so the
        planner knows to route questions about those documents through
        ``rag_search`` instead of the general-knowledge path.
    """
    user_content = f"Goal: {goal}"
    if kb_docs:
        doc_list = "\n".join(f"  - {d}" for d in kb_docs)
        user_content += (
            "\n\nKB AWARENESS — indexed documents in the knowledge base:\n"
            f"{doc_list}\n"
            "If the goal asks about any topic, concept, system, architecture, or content related to these documents or internal domain knowledge, you MUST call rag_search (RAG SEARCH RULE applies). "
            "Do NOT return an empty array [].\n"
            "HOWEVER: if the goal is purely a generic programming or coding task (e.g. 'write a python function to reverse a string'), "
            "use code_sandbox instead of rag_search."
        )
    return [
        {"role": "system", "content": _PLANNING_SYSTEM_PROMPT.format(tools_json=_tools_json_str())},
        {"role": "user", "content": user_content},
    ]


def _build_replan_messages(
    goal: str,
    failed_step: PlannedStep,
    error: str,
    context: list[str],
) -> list[dict[str, str]]:
    context_text = "\n\n".join(context) if context else "(no prior context)"
    return [
        {
            "role": "system",
            "content": _REPLAN_SYSTEM_PROMPT.format(
                tools_json=_tools_json_str(),
                tool_name=failed_step.tool_name,
                tool_args=json.dumps(failed_step.tool_args),
                error=error,
                goal=f"{goal}\n\nPrior context:\n{context_text}",
            ),
        },
        {"role": "user", "content": "Produce the revised plan."},
    ]


def _build_synthesis_messages(goal: str, context: list[str]) -> list[dict[str, str]]:
    context_text = "\n\n".join(context) if context else "(no tool outputs available)"
    return [
        {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Goal: {goal}\n\n"
                f"Tool outputs:\n{context_text}\n\n"
                f"Produce the final response."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------


def _parse_plan(raw: str) -> list[PlannedStep]:
    """
    Extract a JSON array from the LLM output and parse it into ``PlannedStep`` objects.

    Tolerant parser:
    * Strips prose/markdown fences.
    * Strips JavaScript-style single-line comments (``// ...``) that some
      models emit inside JSON strings.
    * Accepts both our schema ``{tool_name, tool_args}`` and the OpenAI
      function-call schema ``{name, arguments}`` that some models emit.
    * Removes steps that reference unknown tools (with a warning) rather than
      letting the orchestrator exhaust retries on an invented tool name.

    Raises
    ------
    ValueError  if no valid JSON array can be extracted.
    """
    import re as _re

    # Strip markdown fences.
    cleaned = _re.sub(r"```(?:json)?\s*", "", raw, flags=_re.IGNORECASE).strip()
    cleaned = _re.sub(r"```\s*$", "", cleaned, flags=_re.IGNORECASE).strip()

    # Strip JS single-line comments (// ...) — Python's json module rejects them.
    # We do this line-by-line to avoid breaking URL strings that contain //.
    cleaned_lines = []
    for line in cleaned.splitlines():
        # Remove trailing // comment, but only if it's outside a quoted string.
        # Simple heuristic: if the line has an even number of " before //, strip.
        comment_idx = line.find("//")
        if comment_idx != -1:
            prefix = line[:comment_idx]
            if prefix.count('"') % 2 == 0:  # not inside a string
                line = prefix.rstrip(", ")  # also strip trailing comma
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)

    # Find the outermost JSON array.
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON array found in plan response: {raw[:300]!r}")

    array_str = cleaned[start : end + 1]
    try:
        items: list[dict[str, Any]] = json.loads(array_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Plan JSON parse error: {exc} — raw: {array_str[:300]!r}") from exc

    steps: list[PlannedStep] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"Plan step is not a dict: {item!r}")

        # Accept both {tool_name, tool_args} (our schema) and
        # {name, arguments} (OpenAI function-call schema).
        tool_name = item.get("tool_name") or item.get("name")
        tool_args = (
            item.get("tool_args")
            or item.get("arguments")
            or item.get("parameters")
            or {}
        )

        if not tool_name:
            raise ValueError(f"Plan step missing 'tool_name' or 'name': {item!r}")
        if not isinstance(tool_args, dict):
            raise ValueError(f"Plan step tool_args/arguments is not a dict: {item!r}")

        # Filter out invented tool names early — log a warning and skip.
        # Known tools include static tools and dynamically registered tools.
        _KNOWN_TOOL_NAMES = {
            "file_read",
            "generate_docx",
            "generate_pptx",
            "generate_xlsx",
            "code_sandbox",
            "rag_search",
            "vision_extract",
            "analyze_spreadsheet",
        }
        from app.tools.registry import TOOL_REGISTRY as _TOOL_REGISTRY
        if tool_name not in _TOOL_REGISTRY and tool_name not in _KNOWN_TOOL_NAMES:
            _log.warning(
                "Plan references unknown tool '%s' — removing from plan. "
                "Available: %s",
                tool_name,
                list(_TOOL_REGISTRY),
            )
            continue  # skip this step

        steps.append(
            PlannedStep(
                step_index=int(item.get("step_index", len(steps))),
                tool_name=tool_name,
                tool_args=tool_args,
                description=item.get("description", ""),
            )
        )
    return steps


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """
    Plan → Act → Observe → Iterate agent loop.

    Parameters
    ----------
    llm_client:
        Object satisfying ``LLMOrchestratorProtocol`` (``OllamaClient`` or a
        test double).
    audit_logger:
        Shared ``AuditLogger`` — all steps are recorded here.
    max_retries:
        Maximum retry attempts per step before declaring failure.
    """

    def __init__(
        self,
        llm_client: LLMOrchestratorProtocol,
        audit_logger: AuditLogger,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self._llm = llm_client
        self._audit = audit_logger
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        goal: str,
        *,
        request_id: Optional[str] = None,
    ) -> OrchestratorRun:
        """
        Execute the agent loop for the given ``goal``.

        Parameters
        ----------
        goal:
            Natural-language description of what the agent should accomplish.
        request_id:
            Correlation ID threaded through the entire run.  Generated if omitted.

        Returns
        -------
        An ``OrchestratorRun`` with ``status == COMPLETED`` on success,
        ``status == FAILED`` on unrecoverable failure.
        """
        request_id = request_id or str(uuid.uuid4())
        run = OrchestratorRun(request_id=request_id, goal=goal)

        self._log(EventType.AGENT_ACTION, run, "run_started", {"goal": goal})

        # ── PLANNING ─────────────────────────────────────────────────────
        run.status = OrchestratorStatus.PLANNING
        kb_docs: Optional[list[str]] = None
        try:
            plan = await self._plan(goal, run, kb_docs=kb_docs)
        except Exception as exc:
            run.status = OrchestratorStatus.FAILED
            run.failure_summary = f"Planning failed: {exc}"
            self._log(EventType.AGENT_ACTION, run, "planning_failed", {"error": str(exc)})
            return run

        run.plan = plan
        self._log(
            EventType.AGENT_ACTION,
            run,
            "plan_produced",
            {
                "step_count": len(plan),
                "steps": [
                    {"step_index": s.step_index, "tool_name": s.tool_name, "description": s.description}
                    for s in plan
                ],
            },
        )

        if not plan:
            # Empty plan — model decided no tools are needed. Synthesise directly.
            run.status = OrchestratorStatus.COMPLETED
            run.final_output = await self._synthesise(goal, run)
            self._log(EventType.AGENT_ACTION, run, "completed_no_tools", {"kb_docs": kb_docs or []})
            return run

        # ── ACT / OBSERVE / RETRY loop ────────────────────────────────────
        step_index = 0
        while step_index < len(run.plan):
            step = run.plan[step_index]
            attempt = 0
            step_done = False

            while not step_done and attempt < self._max_retries:
                attempt += 1
                run.status = OrchestratorStatus.ACTING

                # Dispatch tool
                result = await self._act(step, run, attempt)

                # Observe
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

                self._log(
                    EventType.TOOL_CALL,
                    run,
                    "tool_observed",
                    {
                        "tool_name": step.tool_name,
                        "step_index": step.step_index,
                        "attempt": attempt,
                        "success": result.success,
                        "error": result.error,
                    },
                )

                if result.success:
                    # Accumulate output snippet for context.
                    snippet = (
                        f"[Step {step.step_index} — {step.tool_name}]:\n"
                        f"{str(result.output)[:4000]}"
                    )
                    run.context_snippets.append(snippet)
                    step_done = True

                else:
                    # Failure path
                    if attempt < self._max_retries:
                        run.status = OrchestratorStatus.REPLANNING
                        self._log(
                            EventType.AGENT_ACTION,
                            run,
                            "retry_triggered",
                            {
                                "step_index": step.step_index,
                                "tool_name": step.tool_name,
                                "attempt": attempt,
                                "error": result.error,
                            },
                        )
                        # Re-plan: replace the current step and everything after it.
                        try:
                            revised = await self._replan(goal, step, result.error or "unknown error", run)
                            run.plan = run.plan[:step_index] + revised
                            # Restart the step with the revised plan.
                            step = run.plan[step_index]
                        except Exception as exc:
                            # Re-plan itself failed — treat as a retry of the same step.
                            _log.warning("Re-plan failed (request_id=%s): %s", request_id, exc)
                    else:
                        # Exhausted retries for this step.
                        run.status = OrchestratorStatus.FAILED
                        run.failure_summary = (
                            f"Step {step.step_index} ('{step.tool_name}') failed "
                            f"after {self._max_retries} attempts.  "
                            f"Last error: {result.error}"
                        )
                        self._log(
                            EventType.AGENT_ACTION,
                            run,
                            "step_exhausted",
                            {
                                "step_index": step.step_index,
                                "tool_name": step.tool_name,
                                "max_retries": self._max_retries,
                                "last_error": result.error,
                            },
                        )
                        return run

            step_index += 1

        # ── SYNTHESIS ─────────────────────────────────────────────────────
        run.status = OrchestratorStatus.COMPLETED
        run.final_output = await self._synthesise(goal, run)
        self._log(
            EventType.AGENT_ACTION,
            run,
            "run_completed",
            {"final_output_length": len(run.final_output or "")},
        )
        return run

    # ------------------------------------------------------------------
    # Internal phases
    # ------------------------------------------------------------------

    async def _plan(
        self,
        goal: str,
        run: OrchestratorRun,
        kb_docs: Optional[list[str]] = None,
        llm_client: Optional[LLMOrchestratorProtocol] = None,
    ) -> list[PlannedStep]:
        """Ask the LLM to decompose ``goal`` into a list of tool steps."""
        client = llm_client or self._llm
        messages = _build_plan_messages(goal, kb_docs=kb_docs)
        resp = await client.chat_completion(
            messages,
            request_id=run.request_id,
            temperature=0.0,
            max_tokens=1024,
        )
        return _parse_plan(resp.content)

    async def _replan(
        self,
        goal: str,
        failed_step: PlannedStep,
        error: str,
        run: OrchestratorRun,
    ) -> list[PlannedStep]:
        """Ask the LLM for a revised plan starting from the failed step."""
        messages = _build_replan_messages(goal, failed_step, error, run.context_snippets)
        resp = await self._llm.chat_completion(
            messages,
            request_id=run.request_id,
            temperature=0.0,
            max_tokens=1024,
        )
        return _parse_plan(resp.content)

    async def _act(
        self,
        step: PlannedStep,
        run: OrchestratorRun,
        attempt: int,
    ) -> ToolResult:
        """Dispatch the planned step to the appropriate tool."""
        tool = get_tool(step.tool_name)
        if tool is None:
            return ToolResult(
                success=False,
                output=None,
                error=(
                    f"Unknown tool '{step.tool_name}'.  "
                    f"Available tools: {list(TOOL_REGISTRY)}"
                ),
            )

        # Fix (P1): strip markdown code fences from tool_args["code"] so that
        # LLM responses containing ```python ... ``` blocks don't reach Docker
        # as raw text (which would cause a Python SyntaxError in the container).
        if step.tool_name == "code_sandbox" and "code" in step.tool_args:
            raw = step.tool_args["code"].strip()
            raw = re.sub(r"^```[a-zA-Z]*\s*\n?", "", raw)
            raw = re.sub(r"\n?```\s*$", "", raw).strip()
            step.tool_args["code"] = raw

        self._log(
            EventType.TOOL_CALL,
            run,
            "tool_dispatched",
            {
                "tool_name": step.tool_name,
                "step_index": step.step_index,
                "attempt": attempt,
                "tool_args": step.tool_args,
            },
        )

        try:
            result = await tool.execute(**step.tool_args)
        except Exception as exc:
            # The tool contract says execute() never raises, but we guard here
            # defensively — a bug in the tool must not crash the orchestrator.
            _log.exception(
                "Tool '%s' raised unexpectedly (request_id=%s, attempt=%d): %s",
                step.tool_name,
                run.request_id,
                attempt,
                exc,
            )
            result = ToolResult(
                success=False,
                output=None,
                error=f"Tool raised unexpectedly: {type(exc).__name__}: {exc}",
            )

        # Fix (P0): semantic verification — after a successful code_sandbox run,
        # ask the LLM whether the actual output satisfies the original goal.
        # This catches cases where exit_code==0 but the answer is semantically
        # wrong (e.g. print(41) when the goal was to print 42).
        if result.success and step.tool_name == "code_sandbox" and result.output:
            verified, reason = await self._verify_sandbox_output(
                goal=run.goal,
                code=step.tool_args.get("code", ""),
                sandbox_output=result.output,
                run=run,
            )
            if not verified:
                self._log(
                    EventType.AGENT_ACTION, run, "verification_failed",
                    {"step_index": step.step_index, "reason": reason},
                )
                result = ToolResult(
                    success=False,
                    output=result.output,
                    error=f"Verification failed: {reason}",
                    metadata=result.metadata,
                )

        return result

    async def _verify_sandbox_output(
        self,
        goal: str,
        code: str,
        sandbox_output: dict,
        run: OrchestratorRun,
    ) -> tuple[bool, str]:
        """
        Ask the LLM whether the sandbox output satisfies the original goal.

        Returns ``(verified: bool, reason: str)``.

        On any LLM error the verifier defaults to ``(True, "skipped")`` so a
        transient model outage does not discard a genuinely correct result.
        """
        stdout = (sandbox_output.get("stdout") or "").strip()
        stderr = (sandbox_output.get("stderr") or "").strip()
        exit_code = sandbox_output.get("exit_code", 0)

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a code-output verifier. "
                    "Given a goal, the code that was executed, and its output, "
                    "decide whether the output correctly satisfies the goal.\n\n"
                    "Reply with EXACTLY one of:\n"
                    "  VERIFIED\n"
                    "  NEEDS_CORRECTION: <one-line reason>\n\n"
                    "No other text."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Goal: {goal}\n\n"
                    f"Code:\n{code}\n\n"
                    f"Exit code: {exit_code}\n"
                    f"Stdout:\n{stdout or '(empty)'}\n"
                    f"Stderr:\n{stderr or '(empty)'}\n\n"
                    "Does the output satisfy the goal?"
                ),
            },
        ]

        try:
            resp = await self._llm.chat_completion(
                messages,
                request_id=run.request_id,
                temperature=0.0,
                max_tokens=128,
            )
            content = resp.content.strip()
            if content.upper().startswith("VERIFIED"):
                return True, "verified"
            reason = content.replace("NEEDS_CORRECTION:", "").strip()
            return False, reason or "Output did not satisfy the goal."
        except Exception as exc:
            _log.warning(
                "Sandbox verification LLM call failed (request_id=%s): %s "
                "\u2014 defaulting to verified",
                run.request_id,
                exc,
            )
            return True, f"verification skipped ({exc})"

    async def _synthesise(
        self,
        goal: str,
        run: OrchestratorRun,
        llm_client: Optional[LLMOrchestratorProtocol] = None,
        capability: Optional[str] = None,
    ) -> str:
        """
        Produce a final answer from accumulated step outputs.

        If no tool outputs were collected (empty plan / direct-answer path):
        - For code capabilities (code_generation, debugging, etc.): uses the Coder LLM
          with _CODE_ANSWER_SYSTEM_PROMPT.
        - For general knowledge questions: uses _DIRECT_ANSWER_SYSTEM_PROMPT and
          labels with "⚠️ General knowledge — not from an internal document."

        If tool outputs exist, the LLM synthesises from those outputs.  If all
        the outputs came from an empty RAG result, the synthesis prompt instructs
        the model to fall back to general knowledge and label accordingly.
        """
        client = llm_client or self._llm
        is_code_task = capability in {
            "code_generation",
            "code_review",
            "debugging",
            "refactoring",
            "complex_code",
        }

        # ── Direct-answer path (empty plan: no tools were called) ───────────
        if not run.context_snippets:
            if is_code_task:
                messages = [
                    {"role": "system", "content": _CODE_ANSWER_SYSTEM_PROMPT},
                    {"role": "user", "content": goal},
                ]
            else:
                messages = [
                    {"role": "system", "content": _DIRECT_ANSWER_SYSTEM_PROMPT},
                    {"role": "user", "content": goal},
                ]
            try:
                resp = await client.chat_completion(
                    messages,
                    request_id=run.request_id,
                    temperature=0.2 if is_code_task else 0.3,
                    max_tokens=2048 if is_code_task else 1024,
                )
                return resp.content
            except Exception as exc:
                _log.warning("Direct-answer synthesis failed (request_id=%s): %s", run.request_id, exc)
                prefix = "" if is_code_task else "⚠️ General knowledge — not from an internal document.\n\n"
                return (
                    f"{prefix}(Synthesis step failed: {exc})"
                )

        # ── Tool-grounded synthesis path ─────────────────────────────────
        # Detect whether ALL context came from empty RAG results so the
        # synthesis prompt can instruct the model to fall back to general knowledge.
        #
        # FIX (Bug 3): Match only the exact sentinel string that RagSearchTool
        # returns on a zero-hit search.  The previous broad match
        # ("no results" in s.lower()) could accidentally match document
        # content that happens to contain those words, causing real RAG
        # results to be silently discarded.
        _RAG_EMPTY_SENTINEL = "No relevant documents found in the knowledge base."
        rag_snippets = [
            s for s in run.context_snippets
            if "rag_search" in s
        ]
        all_rag_empty = bool(rag_snippets) and all(
            _RAG_EMPTY_SENTINEL in s
            for s in rag_snippets
        )

        if all_rag_empty:
            # All RAG calls returned nothing: answer from general knowledge, labelled.
            system_prompt = _CODE_ANSWER_SYSTEM_PROMPT if is_code_task else _DIRECT_ANSWER_SYSTEM_PROMPT
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"{goal}\n\n"
                        "(The internal document corpus returned no relevant results "
                        "for this question. Answer from general knowledge.)"
                    ),
                },
            ]
        else:
            messages = _build_synthesis_messages(goal, run.context_snippets)

        try:
            resp = await client.chat_completion(
                messages,
                request_id=run.request_id,
                temperature=0.2 if is_code_task else 0.3,
                max_tokens=2048,
            )
            return resp.content
        except Exception as exc:
            _log.warning("Synthesis call failed (request_id=%s): %s", run.request_id, exc)
            return (
                f"Synthesis step failed ({exc}).  Raw tool outputs:\n\n"
                + "\n\n".join(run.context_snippets)
            )

    # ------------------------------------------------------------------
    # Audit helper
    # ------------------------------------------------------------------

    def _log(
        self,
        event_type: EventType,
        run: OrchestratorRun,
        action: str,
        extra: dict[str, Any],
    ) -> None:
        payload: dict[str, Any] = {
            "action": action,
            "status": run.status.value,
            "goal_preview": run.goal[:120],
        }
        payload.update(extra)
        self._audit.log_event(event_type, request_id=run.request_id, payload=payload)
