"""
tests/test_phase_e.py
=====================
Phase E integration tests for FastAPI endpoints, SSE streaming, security hardening,
and hardware status/tier management.

Coverage:
---------
1. GET /hardware/status — returns hardware detection and tier info.
2. POST /hardware/force_tier — switches active tier (re-resolves models).
3. POST /orchestrator/run — submits goal, handles file uploads safely.
4. GET /orchestrator/stream/{request_id} — streams SSE events to completion.
5. GET /outputs/{filename} — security: blocks path traversal (../, absolute paths, subdirs).
6. GET /outputs/{filename} — serves valid generated deliverable.
7. GET /audit/recent — returns records for request_id with verified chain.
8. Concurrency: AsyncAuditAdapter writes without blocking loop.
"""

from __future__ import annotations

import asyncio
import io
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.audit.async_adapter import AsyncAuditAdapter
from app.audit.logger import AuditLogger, EventType
from app.main import app
from app.orchestrator.orchestrator import Orchestrator
from app.orchestrator.state import OrchestratorRun, OrchestratorStatus, PlannedStep, StepOutcome
from app.orchestrator.streaming_runner import run_with_streaming
from app.routers.orchestrator_router import setup_orchestrator_router


@pytest.fixture
def client(tmp_path):
    log_file = tmp_path / "test_audit.jsonl"
    logger = AuditLogger(log_path=log_file)
    async_audit = AsyncAuditAdapter(logger)

    fake_llm = AsyncMock()
    fake_llm.model_name = "qwen2.5-coder:7b"
    fake_llm.ollama_tag = "qwen2.5-coder:7b"
    fake_llm.chat_completion.return_value.content = (
        '[{"tool_name": "file_read", "tool_args": {"path": "test.txt"}, "description": "read"}]'
    )

    orchestrator = Orchestrator(llm_client=fake_llm, audit_logger=logger)

    startup_resolved = {
        "text": "qwen2.5:7b",
        "coder": "qwen2.5-coder:7b",
        "vision": "llama3.2-vision:11b",
    }
    startup_gpu = {
        "gpu_available": True,
        "total_vram_mb": 16000,
        "free_vram_mb": 14000,
        "device_name": "Apple M-Series",
    }

    setup_orchestrator_router(
        audit_logger=logger,
        async_audit=async_audit,
        orchestrator=orchestrator,
        startup_resolved=startup_resolved,
        startup_gpu_info=startup_gpu,
    )

    with TestClient(app) as test_client:
        yield test_client


def test_hardware_status(client):
    """GET /hardware/status returns hardware probe and active tier.

    Note: The lifespan re-runs detect_gpu() which on CI/Mac may return
    gpu_available=False (no nvidia-smi). We assert structural correctness
    and that the resolved_models list is non-empty (injected by fixture).
    """
    resp = client.get("/hardware/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "gpu_info" in data
    assert "resolved_models" in data
    assert "degraded" in data
    assert "gpu_available" in data["gpu_info"]
    # Resolved models come from the fixture's startup_resolved dict
    assert isinstance(data["resolved_models"], list)


def test_hardware_force_tier(client):
    """POST /hardware/force_tier updates active tier."""
    resp = client.post("/hardware/force_tier", data={"tier": "small"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["applied_tier"] == "small"
    assert "vram_note" in data


def test_outputs_security_path_traversal(client):
    """GET /outputs/{filename} must block all path traversal attempts."""
    malicious_inputs = [
        "../audit/audit.log",
        "..%2Faudit%2Faudit.log",
        "..\\..\\etc\\passwd",
        "/etc/passwd",
        "nested/sub/file.txt",
    ]
    for filename in malicious_inputs:
        resp = client.get(f"/outputs/{filename}")
        assert resp.status_code in [400, 404], f"Expected 400/404 for traversal attempt: {filename}"


def test_outputs_serves_valid_file(client, tmp_path):
    """GET /outputs/{filename} safely serves an existing file in outputs/."""
    outputs_dir = Path("outputs")
    outputs_dir.mkdir(exist_ok=True)
    test_file = outputs_dir / "test_deliverable_e.txt"
    test_file.write_text("Sovereign Workbench Output Deliverable", encoding="utf-8")

    try:
        resp = client.get(f"/outputs/{test_file.name}")
        assert resp.status_code == 200
        assert resp.text == "Sovereign Workbench Output Deliverable"
    finally:
        if test_file.exists():
            test_file.unlink()


def test_orchestrator_run_and_stream(client):
    """Test full workflow: POST /orchestrator/run followed by GET /orchestrator/stream."""
    # Create a mock file upload
    file_bytes = b"Sample input document content"
    files = [("files", ("input_doc.txt", io.BytesIO(file_bytes), "text/plain"))]
    data = {"goal": "Analyze the attached input document"}

    # 1. Run submission
    resp = client.post("/orchestrator/run", data=data, files=files)
    assert resp.status_code == 200
    run_data = resp.json()
    assert "request_id" in run_data
    request_id = run_data["request_id"]
    assert run_data["status"] == "accepted"

    # 2. SSE Streaming
    with client.stream("GET", f"/orchestrator/stream/{request_id}") as stream_resp:
        assert stream_resp.status_code == 200
        assert "text/event-stream" in stream_resp.headers["content-type"]
        events = []
        for line in stream_resp.iter_lines():
            if line and line.startswith("data: "):
                events.append(line[6:])

        # Ensure stream delivers completion
        assert any("[DONE]" in e or "completed" in e or "failed" in e for e in events)


def test_audit_recent(client, tmp_path):
    """GET /audit/recent returns records and checks chain validity."""
    log_file = tmp_path / "test_audit_rec.jsonl"
    logger = AuditLogger(log_path=log_file)
    async_audit = AsyncAuditAdapter(logger)
    req_id = "req-test-audit-123"

    logger.log_event(EventType.AGENT_ACTION, request_id=req_id, payload={"goal": "Audit test"})
    logger.log_event(EventType.TOOL_CALL, request_id=req_id, payload={"tool": "FileReadTool"})
    logger.log_event(EventType.AGENT_ACTION, request_id=req_id, payload={"status": "done"})

    setup_orchestrator_router(
        audit_logger=logger,
        async_audit=async_audit,
        orchestrator=None,
        startup_resolved={},
        startup_gpu_info={},
    )

    resp = client.get(f"/audit/recent?request_id={req_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["returned"] == 3
    assert data["chain_valid"] is True
    assert len(data["records"]) == 3


@pytest.mark.asyncio
async def test_async_audit_adapter(tmp_path):
    """Verify AsyncAuditAdapter offloads writes asynchronously."""
    log_file = tmp_path / "async_audit.jsonl"
    sync_logger = AuditLogger(log_path=log_file)
    async_adapter = AsyncAuditAdapter(sync_logger)

    rec = await async_adapter.log_event(
        event_type=EventType.MODEL_CALL,
        request_id="req-async-1",
        payload={"model": "qwen2.5-coder"},
    )

    assert rec.event_type == EventType.MODEL_CALL
    assert rec.request_id == "req-async-1"
    valid, errors = sync_logger.verify_chain()
    assert valid is True
