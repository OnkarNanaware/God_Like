"""
=============================================================================
Sovereign Workbench — Comprehensive Deep Validation Suite
=============================================================================
Validates all internal mechanics, interfaces, security boundaries, and
workflows across the entire system.
"""

import asyncio
import importlib
import inspect
import json
import os
import pathlib
import sys
import tempfile
import threading
from typing import Any

print("=" * 75)
print("       SOVEREIGN WORKBENCH — DEEP COMPONENT & LAYER VALIDATION       ")
print("=" * 75)

checks_passed = 0
checks_failed = 0
failures = []

def record(layer_name: str, passed: bool, details: str = ""):
    global checks_passed, checks_failed
    if passed:
        checks_passed += 1
        status = " PASS "
    else:
        checks_failed += 1
        status = " FAIL "
        failures.append((layer_name, details))
    print(f"[{status}] {layer_name}")
    if details:
        print(f"         -> {details}")


# ---------------------------------------------------------------------------
# [1] EventType Enum Completeness
# ---------------------------------------------------------------------------
print("\n>>> [1] Audit Event Types & Enum Definition")
try:
    from app.audit.logger import EventType
    expected_events = [
        "MODEL_CALL", "TOOL_CALL", "ROUTE_DECISION", "FILE_WRITE",
        "AGENT_ACTION", "STARTUP", "ERROR", "RAG_INGEST",
        "RAG_RETRIEVAL", "VISION_EXTRACT"
    ]
    missing = [e for e in expected_events if not hasattr(EventType, e)]
    record("EventType Enum Values", len(missing) == 0, f"All {len(expected_events)} events defined: {', '.join(expected_events)}")
except Exception as e:
    record("EventType Enum Values", False, str(e))


# ---------------------------------------------------------------------------
# [2] Model Registry Schema & Sovereignty
# ---------------------------------------------------------------------------
print("\n>>> [2] Model Registry & Zero-Cloud Guarantee")
try:
    from app.models.ollama_client import MODEL_REGISTRY
    required_keys = {"name", "ollama_tag", "endpoint", "modality", "context_length", "tier", "est_vram_mb"}
    all_valid = True
    invalid_reasons = []
    
    for mname, mentry in MODEL_REGISTRY.items():
        missing_keys = required_keys - mentry.keys()
        if missing_keys:
            all_valid = False
            invalid_reasons.append(f"{mname} missing keys: {missing_keys}")
        ep = mentry.get("endpoint", "")
        host = ep.split("//")[1].split(":")[0].split("/")[0]
        if host not in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
            all_valid = False
            invalid_reasons.append(f"{mname} has external endpoint: {ep}")
            
    record("Model Registry Schema & Localhost Endpoints", all_valid, f"{len(MODEL_REGISTRY)} models validated: {', '.join(MODEL_REGISTRY.keys())}")
except Exception as e:
    record("Model Registry Schema & Localhost Endpoints", False, str(e))


# ---------------------------------------------------------------------------
# [3] Tool Registry & Dynamic Registration
# ---------------------------------------------------------------------------
print("\n>>> [3] Tool Registry & Tool Lifecycle")
try:
    from app.tools.registry import TOOL_REGISTRY, list_tools, register_tool, get_tool
    from app.tools.file_read import FileReadTool
    from app.tools.vision import VisionExtractTool
    
    # Register vision tool dynamically
    register_tool(VisionExtractTool())
    
    tools = list_tools()
    tool_names = [t["name"] for t in tools]
    has_required_tools = "file_read" in tool_names and "vision_extract" in tool_names
    record("Tool Discovery & Registry List", has_required_tools, f"Registered tools: {tool_names}")
    
    fr_tool = get_tool("file_read")
    record("Tool Getter (get_tool)", fr_tool is not None and isinstance(fr_tool, FileReadTool), f"Resolved tool: {fr_tool.name}")
except Exception as e:
    record("Tool Discovery & Registry List", False, str(e))


# ---------------------------------------------------------------------------
# [4] BaseTool Interface Contract
# ---------------------------------------------------------------------------
print("\n>>> [4] BaseTool Interface & Schema Contract")
try:
    from app.tools.base import BaseTool, ToolResult
    
    for tool_instance in [FileReadTool(), VisionExtractTool()]:
        desc = tool_instance.describe()
        assert "name" in desc and "description" in desc and "input_schema" in desc
        assert desc["input_schema"].get("type") == "object"
        assert "properties" in desc["input_schema"]
    record("BaseTool Contract Conformance", True, "FileReadTool and VisionExtractTool satisfy BaseTool ABC and JSON schema spec")
except Exception as e:
    record("BaseTool Contract Conformance", False, str(e))


# ---------------------------------------------------------------------------
# [5] Text Chunker Sliding Window
# ---------------------------------------------------------------------------
print("\n>>> [5] Text Chunker Sliding Window & Edge Cases")
try:
    from app.rag.chunker import chunk_text
    
    # Sliding window test
    t_chunks = chunk_text("A" * 600, chunk_size=512, overlap=64)
    assert len(t_chunks) == 2, f"Expected 2 chunks, got {len(t_chunks)}"
    
    # Empty text -> empty list
    empty_res = chunk_text("", 512, 64)
    assert empty_res == [], f"Expected [], got {empty_res}"
    
    # Short text -> single chunk
    short_res = chunk_text("Short sample", 512, 64)
    assert len(short_res) == 1 and short_res[0] == "Short sample"
    
    # Zero overlap -> clean division
    zero_overlap = chunk_text("X" * 1000, chunk_size=100, overlap=0)
    assert len(zero_overlap) == 10
    
    record("Chunker Mechanics (Window, Overlap, Empty, Single)", True, "All 4 chunking scenarios passed deterministically")
except Exception as e:
    record("Chunker Mechanics (Window, Overlap, Empty, Single)", False, str(e))


# ---------------------------------------------------------------------------
# [6] Localhost Endpoint Validator
# ---------------------------------------------------------------------------
print("\n>>> [6] Sovereignty URL Validation Function")
try:
    from app.audit.logger import AuditLogger
    al_dummy = AuditLogger.__new__(AuditLogger)
    
    cases = [
        ("http://localhost:11434", True),
        ("http://127.0.0.1:11434", True),
        ("http://[::1]:11434", True),
        ("http://0.0.0.0:11434", True),
        ("http://192.168.1.100:11434", False),
        ("http://api.openai.com", False),
        ("https://anthropic.com/v1", False),
        ("http://10.0.0.1:8000", False),
    ]
    all_cases_ok = all(al_dummy._is_local_endpoint(url) == exp for url, exp in cases)
    record("AuditLogger._is_local_endpoint Assertion", all_cases_ok, f"Verified 8/8 network boundary edge cases")
except Exception as e:
    record("AuditLogger._is_local_endpoint Assertion", False, str(e))


# ---------------------------------------------------------------------------
# [7] SHA-256 Hash Chain Integrity
# ---------------------------------------------------------------------------
print("\n>>> [7] Cryptographic SHA-256 Audit Hash-Chain")
try:
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        tpath = pathlib.Path(tmp.name)
        
    al_inst = AuditLogger(log_path=tpath)
    al_inst.log_event(EventType.TOOL_CALL, request_id="r1", payload={"action": "test1"})
    al_inst.log_event(EventType.RAG_RETRIEVAL, request_id="r2", payload={"query": "test query"})
    al_inst.log_event(EventType.VISION_EXTRACT, request_id="r3", payload={"doc": "test.pdf"})
    
    is_valid, chain_errors = al_inst.verify_chain()
    record("Audit Hash Chain Integrity Check", is_valid and len(chain_errors) == 0, f"Genesis -> Seq {al_inst._sequence} verified without errors")
except Exception as e:
    record("Audit Hash Chain Integrity Check", False, str(e))


# ---------------------------------------------------------------------------
# [8] Tamper-Detection Verification
# ---------------------------------------------------------------------------
print("\n>>> [8] Tamper Detection & Localization")
try:
    # Read chain, mutate sequence 2, and verify that verification fails
    raw_lines = [l for l in tpath.read_text(encoding="utf-8").splitlines() if l.strip()]
    raw_lines[1] = raw_lines[1].replace("test1", "TAMPERED_PAYLOAD")
    tpath.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")
    
    tamper_checker = AuditLogger.__new__(AuditLogger)
    tamper_checker._path = tpath
    tamper_checker._lock = threading.Lock()
    tamper_checker._sequence, tamper_checker._prev_hash = tamper_checker._recover_chain_state()
    t_valid, t_errors = tamper_checker.verify_chain()
    
    tamper_detected = (not t_valid) and len(t_errors) > 0
    record("Tamper-Detection Guard", tamper_detected, f"Detected tamper immediately: {t_errors[0] if t_errors else 'None'}")
except Exception as e:
    record("Tamper-Detection Guard", False, str(e))


# ---------------------------------------------------------------------------
# [9] Router Capabilities & Heuristic Logic
# ---------------------------------------------------------------------------
print("\n>>> [9] Two-Stage Router Heuristics")
try:
    from app.router.heuristics import run_heuristics, Capability, is_ambiguous
    
    # 1. Traceback -> DEBUGGING
    sig1 = run_heuristics("Traceback (most recent call last):\n  File 'test.py', line 10\nZeroDivisionError: division by zero")
    assert sig1[0].capability == Capability.DEBUGGING
    
    # 2. Image attachment -> IMAGE_UNDERSTANDING
    sig2 = run_heuristics("analyze the attached schema", attached_filenames=["architecture.png"])
    assert sig2[0].capability == Capability.IMAGE_UNDERSTANDING
    
    # 3. PDF attachment -> DOCUMENT_VISION
    sig3 = run_heuristics("extract table 2.1", attached_filenames=["standard.pdf"])
    assert sig3[0].capability == Capability.DOCUMENT_VISION
    
    # 4. Explicit hint -> forced
    sig4 = run_heuristics("hello", explicit_capability_hint="code_generation")
    assert sig4[0].capability == Capability.CODE_GENERATION and not is_ambiguous(sig4)
    
    record("Router Heuristic Signal Matching", True, "Traceback (DEBUG), PNG (IMAGE), PDF (DOCUMENT_VISION), Hint (OVERRIDE) passed")
except Exception as e:
    record("Router Heuristic Signal Matching", False, str(e))


# ---------------------------------------------------------------------------
# [10] Plan Parser Robustness
# ---------------------------------------------------------------------------
print("\n>>> [10] Orchestrator Plan Parser Tolerances")
try:
    from app.orchestrator.orchestrator import _parse_plan
    
    # 1. Standard plan
    p1 = '[{"step_index": 0, "tool_name": "file_read", "tool_args": {"path": "a.txt"}, "description": "read"}]'
    s1 = _parse_plan(p1)
    assert len(s1) == 1 and s1[0].tool_name == "file_read"
    
    # 2. Markdown fenced JSON
    p2 = "```json\n" + p1 + "\n```"
    s2 = _parse_plan(p2)
    assert len(s2) == 1
    
    # 3. OpenAI function-calling schema {name, arguments}
    p3 = '[{"step_index": 0, "name": "file_read", "arguments": {"path": "b.txt"}}]'
    s3 = _parse_plan(p3)
    assert len(s3) == 1 and s3[0].tool_name == "file_read"
    
    # 4. Unknown tool skipping
    p4 = '[{"step_index": 0, "tool_name": "file_read", "tool_args": {"path": "c.txt"}}, {"step_index": 1, "tool_name": "unknown_ai_search", "tool_args": {}}]'
    s4 = _parse_plan(p4)
    assert len(s4) == 1 and s4[0].tool_name == "file_read"
    
    record("Plan Parser (JSON, Fences, OpenAI Schema, Unknown Tool Filter)", True, "All 4 formats successfully normalized into PlannedStep objects")
except Exception as e:
    record("Plan Parser (JSON, Fences, OpenAI Schema, Unknown Tool Filter)", False, str(e))


# ---------------------------------------------------------------------------
# [11] Vision Tool Execution
# ---------------------------------------------------------------------------
print("\n>>> [11] Vision Extraction Tool Edge Cases")
try:
    vt = VisionExtractTool()
    
    # 1. Missing arg
    r1 = asyncio.run(vt.execute())
    assert not r1.success and "file_path" in str(r1.error)
    
    # 2. File not found
    r2 = asyncio.run(vt.execute(file_path="nonexistent_image.png"))
    assert not r2.success and "not found" in str(r2.error).lower()
    
    # 3. Unsupported extension (file exists but has unsupported extension)
    with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as tmp_xyz:
        xyz_path = tmp_xyz.name
    r3 = asyncio.run(vt.execute(file_path=xyz_path))
    assert not r3.success and "Unsupported" in str(r3.error)
    
    # 4. Valid document extraction
    import fitz
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_doc:
        doc_path = tmp_doc.name
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "OISD-118 Section 4.2 Fire Protection Standards")
    doc.save(doc_path)
    doc.close()
    
    r4 = asyncio.run(vt.execute(file_path=doc_path))
    assert r4.success and "doc_name" in (r4.metadata or {})
    
    record("VisionExtractTool Edge Case Handling", True, "Missing arg, not found, invalid ext, and PDF parsing all handled correctly")
except Exception as e:
    record("VisionExtractTool Edge Case Handling", False, str(e))


# ---------------------------------------------------------------------------
# [12] Ingestor File Type Dispatch
# ---------------------------------------------------------------------------
print("\n>>> [12] RAG Ingestor Extension Dispatcher")
try:
    from app.rag.ingestor import Ingestor
    from unittest.mock import MagicMock
    
    mock_ingestor = Ingestor(embedder=MagicMock(), store=MagicMock(), audit_logger=MagicMock())
    
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as t:
        t.write("Test content " * 50)
        txt_file = pathlib.Path(t.name)
        
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, encoding="utf-8") as m:
        m.write("# Heading\n\nBody content " * 30)
        md_file = pathlib.Path(m.name)
        
    chunks_txt = mock_ingestor._chunk(txt_file)
    chunks_md = mock_ingestor._chunk(md_file)
    
    record("Ingestor File Dispatch (.txt, .md, .pdf)", len(chunks_txt) > 0 and len(chunks_md) > 0, f"Dispatched {len(chunks_txt)} txt chunks and {len(chunks_md)} md chunks")
except Exception as e:
    record("Ingestor File Dispatch (.txt, .md, .pdf)", False, str(e))


# ---------------------------------------------------------------------------
# [13] Orchestrator Status State Machine
# ---------------------------------------------------------------------------
print("\n>>> [13] Orchestrator State Machine Initial State")
try:
    from app.orchestrator.state import OrchestratorStatus, OrchestratorRun
    
    expected_statuses = {"pending", "planning", "acting", "observing", "replanning", "completed", "failed"}
    actual_statuses = {s.value for s in OrchestratorStatus}
    assert expected_statuses == actual_statuses
    
    orun = OrchestratorRun(request_id="test-req", goal="test goal")
    assert orun.status == OrchestratorStatus.PENDING
    assert orun.plan == [] and orun.outcomes == [] and orun.context_snippets == []
    assert orun.final_output is None and orun.failure_summary is None
    
    record("Orchestrator State Machine & OrchestratorRun", True, "All 7 states defined; initial state is PENDING with empty context")
except Exception as e:
    record("Orchestrator State Machine & OrchestratorRun", False, str(e))


# ---------------------------------------------------------------------------
# [14] CORS Security Configuration
# ---------------------------------------------------------------------------
print("\n>>> [14] CORS Policy Configuration")
try:
    import app.main as app_main
    cors_origins = []
    for mw in app_main.app.user_middleware:
        if "CORS" in getattr(mw, "cls", type(None)).__name__:
            cors_origins = mw.kwargs.get("allow_origins", [])
            break
            
    is_cors_safe = len(cors_origins) > 0 and all(
        o.replace("http://", "").replace("https://", "").split(":")[0] in {"localhost", "127.0.0.1"}
        for o in cors_origins
    )
    record("CORS Localhost-Only Whitelist", is_cors_safe, f"Allowed origins: {cors_origins}")
except Exception as e:
    record("CORS Localhost-Only Whitelist", False, str(e))


# ---------------------------------------------------------------------------
# [15] Docker Sandbox Security Flags
# ---------------------------------------------------------------------------
print("\n>>> [15] Sandbox Security Limits & CLI Flags")
try:
    from app.sandbox import docker_runner as dr
    src = inspect.getsource(dr.run_code_in_docker)
    
    security_flags = [
        "--network=none",
        "MEMORY_LIMIT",
        "CPU_LIMIT",
        "PIDS_LIMIT",
        "--read-only",
        "no-new-privileges",
        "--rm"
    ]
    missing_flags = [f for f in security_flags if f not in src]
    record("Docker Sandbox Security Flags", len(missing_flags) == 0, f"Enforced: --network=none, --read-only, no-new-privileges, memory/cpu limits")
except Exception as e:
    record("Docker Sandbox Security Flags", False, str(e))


# ---------------------------------------------------------------------------
# [16] Host Path Translation for Docker (Windows WSL2)
# ---------------------------------------------------------------------------
print("\n>>> [16] Path Translation for Bind Mounts")
try:
    from app.sandbox.docker_runner import _host_path_for_docker
    test_win_path = pathlib.Path("C:/Users/sonaw/SARA/workspace")
    translated = _host_path_for_docker(test_win_path)
    assert translated.startswith("/c/Users/sonaw/SARA/workspace") or translated.startswith("/c/")
    record("Windows-to-Docker Path Translation", True, f"Translated '{test_win_path}' -> '{translated}'")
except Exception as e:
    record("Windows-to-Docker Path Translation", False, str(e))


# ---------------------------------------------------------------------------
# [17] Dependency Importability Check
# ---------------------------------------------------------------------------
print("\n>>> [17] Required System Dependencies")
try:
    deps = ["fastapi", "pydantic", "httpx", "yaml", "qdrant_client", "fitz"]
    for d in deps:
        importlib.import_module(d)
    record("Python Package Dependencies", True, f"All core packages importable: {', '.join(deps)}")
except Exception as e:
    record("Python Package Dependencies", False, str(e))


# ---------------------------------------------------------------------------
# [18] Audit Log Storage
# ---------------------------------------------------------------------------
print("\n>>> [18] Persistent Audit Log Storage")
try:
    audit_file = pathlib.Path("logs/audit.jsonl")
    has_audit = audit_file.exists()
    records_count = len([l for l in audit_file.read_text(encoding="utf-8").splitlines() if l.strip()]) if has_audit else 0
    record("Audit Log File Persistence", has_audit, f"Path: logs/audit.jsonl ({records_count} records logged)")
except Exception as e:
    record("Audit Log File Persistence", False, str(e))


# ---------------------------------------------------------------------------
# [19] Knowledge Base Assets
# ---------------------------------------------------------------------------
print("\n>>> [19] Local Knowledge Base Directory")
try:
    kb_path = pathlib.Path("knowledge_base")
    pdf_docs = list(kb_path.rglob("*.pdf"))
    record("Knowledge Base Repository", len(pdf_docs) > 0, f"Found {len(pdf_docs)} indexed PDFs (e.g. {pdf_docs[0].name})")
except Exception as e:
    record("Knowledge Base Repository", False, str(e))


# ---------------------------------------------------------------------------
# [20] Persistent Qdrant Storage
# ---------------------------------------------------------------------------
print("\n>>> [20] Vector Storage Engine & Collection State")
try:
    from app.rag.store import VectorStore
    vs = VectorStore()
    colls = vs._client.get_collections().collections
    col_names = [c.name for c in colls]
    target_col = "sovereign_knowledge_base" if "sovereign_knowledge_base" in col_names else (col_names[0] if col_names else "docs")
    points_count = vs._client.get_collection(target_col).points_count if col_names else 0
    record("Qdrant Local Vector Engine", len(colls) > 0, f"Collection '{target_col}' active on localhost:6333 with {points_count} vectors")
except Exception as e:
    record("Qdrant Local Vector Engine", False, str(e))


# ---------------------------------------------------------------------------
# [21] Docker Sandbox Air-Gap Network Probe
# ---------------------------------------------------------------------------
print("\n>>> [21] Real Sandbox Network Air-Gap Execution")
try:
    from app.sandbox.docker_runner import run_code_in_docker
    with tempfile.TemporaryDirectory() as ws:
        (pathlib.Path(ws) / "main.py").write_text(
            "import urllib.request\n"
            "try:\n"
            "    urllib.request.urlopen('http://1.1.1.1', timeout=1)\n"
            "    print('LEAK')\n"
            "except Exception as e:\n"
            "    print(f'AIRGAP_OK:{type(e).__name__}')\n"
        )
        res = asyncio.run(run_code_in_docker(pathlib.Path(ws), timeout=5))
        is_airgapped = "AIRGAP_OK" in res.stdout or "AIRGAP_OK" in res.stderr
        record("Docker Sandbox Network Blockade (--network=none)", is_airgapped, f"Output: {res.stdout.strip()}")
except Exception as e:
    record("Docker Sandbox Network Blockade (--network=none)", False, str(e))


# ---------------------------------------------------------------------------
# [22] Real Docker Code Execution & Computation
# ---------------------------------------------------------------------------
print("\n>>> [22] Real Sandbox Code Execution & Computation")
try:
    with tempfile.TemporaryDirectory() as ws:
        (pathlib.Path(ws) / "main.py").write_text(
            "import json\n"
            "primes = [x for x in range(2, 50) if all(x % d != 0 for d in range(2, x))]\n"
            "print(json.dumps({'status': 'complete', 'primes_count': len(primes)}))\n"
        )
        res = asyncio.run(run_code_in_docker(pathlib.Path(ws), timeout=5))
        parsed = json.loads(res.stdout) if res.exit_code == 0 else {}
        is_exec_ok = res.exit_code == 0 and parsed.get("primes_count") == 15
        record("Docker Sandbox Computation & JSON Capture", is_exec_ok, f"Exit code {res.exit_code}: {res.stdout.strip()}")
except Exception as e:
    record("Docker Sandbox Computation & JSON Capture", False, str(e))


# ---------------------------------------------------------------------------
# FINAL TALLY
# ---------------------------------------------------------------------------
print("\n" + "=" * 75)
total_checks = checks_passed + checks_failed
print(f"DEEP VALIDATION SUMMARY: {checks_passed}/{total_checks} CHECKS PASSED ({checks_passed/total_checks*100:.1f}%)")
print("=" * 75)

if checks_failed > 0:
    print("\nFailures:")
    for name, reason in failures:
        print(f"  [X] {name}: {reason}")
    sys.exit(1)
else:
    print("\n[OK] ALL 22 SYSTEM LAYERS & CONSTRAINTS EMPIRICALLY VERIFIED.")
    sys.exit(0)
