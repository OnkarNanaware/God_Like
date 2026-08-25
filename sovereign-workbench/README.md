# Sovereign Workbench

A **private, self-hosted AI workbench** for organizations handling confidential data.  
All models, tools, and data stay on the organization's own machine — no external API calls, ever.

---

## Network Sovereignty Guarantee

> **Zero external network calls at runtime.**  
> Every model call is validated against a `localhost`-only allowlist in both the model registry loader and the audit logger.  Any call to a non-local endpoint raises an immediate `ValueError` and is recorded in the audit trail as a sovereignty violation.

---

## Architecture Overview

```
sovereign-workbench/
├── app/
│   ├── main.py                 ← FastAPI entrypoint + /chat endpoint
│   ├── config/
│   │   └── models.yaml         ← Single source of truth for all models
│   ├── models/
│   │   └── ollama_client.py    ← Thin async wrapper (httpx, no openai SDK)
│   ├── audit/
│   │   └── logger.py           ← Append-only, hash-chained JSON-lines audit log
│   ├── router/                 ← Phase B: heuristic + LLM-fallback router
│   ├── orchestrator/           ← Phase B: plan→act→observe→iterate loop
│   ├── tools/                  ← Phase B+: file read, RAG search, doc gen, sandbox
│   └── rag/                    ← Phase C: Qdrant ingestion + retrieval
├── sandbox/
│   └── Dockerfile              ← Phase D: --network=none code execution sandbox
├── tests/
│   └── test_phase_a.py         ← Phase A smoke tests
├── requirements.txt
├── .env.example
└── README.md
```

---

## Phase A — What's Built

| Component | File | Status |
|-----------|------|--------|
| Model registry | `app/config/models.yaml` | ✅ |
| Ollama async client | `app/models/ollama_client.py` | ✅ |
| FastAPI app + `/chat` | `app/main.py` | ✅ |
| Hash-chained audit logger | `app/audit/logger.py` | ✅ |
| Smoke tests | `tests/test_phase_a.py` | ✅ |

---

## Prerequisites

- Python 3.11
- [Ollama](https://ollama.com) running locally (`ollama serve`)
- The following models pulled:

```bash
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama pull qwen2.5-coder:7b
ollama pull qwen2.5-coder:14b
ollama pull qwen2.5vl:7b
ollama pull bge-m3
```

---

## Quick Start

```bash
# 1. Create and activate a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and review the env file (no API keys needed — this is intentional)
cp .env.example .env

# 4. Start Ollama (in a separate terminal)
ollama serve

# 5. Start the workbench
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## Verifying Phase A (offline)

```bash
# Disable your network interface, then:
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Are you running locally?"}]}' | jq .

# Check the audit log
tail -f logs/audit.jsonl | jq .
```

Expected: the request succeeds, the response comes from `qwen2.5:14b-instruct-q4_K_M`, and `logs/audit.jsonl` contains a `model_call` entry with `"endpoint": "http://localhost:11434"`.

---

## Running Tests

```bash
pytest tests/test_phase_a.py -v
```

All 8 tests pass without a live Ollama instance (Ollama calls are intercepted by `respx`).

---

## Audit Log Format

Each line in `logs/audit.jsonl` is a JSON object:

```json
{
  "event_type": "model_call",
  "timestamp_utc": "2025-01-15T10:23:45.123456+00:00",
  "request_id": "3f7a1b2c-...",
  "sequence": 2,
  "prev_hash": "a3f9...d1",
  "self_hash": "b7c2...e4",
  "payload": {
    "model_name": "qwen25_14b_instruct",
    "ollama_tag": "qwen2.5:14b-instruct-q4_K_M",
    "endpoint": "http://localhost:11434",
    "prompt_tokens": 142,
    "response_tokens": 87,
    "latency_ms": 1234.5,
    "status": "success"
  }
}
```

`prev_hash` = SHA-256 of the previous record's raw bytes (with `self_hash=""` during hashing).  
`self_hash` = SHA-256 of this record (with `self_hash=""` during hashing).

This forms a hash chain verifiable with `AuditLogger.verify_chain()`.

---

## What's Next (Phase B)

- **Router:** heuristic pass (file type / keyword → model selection) with LLM fallback classification
- **Agent orchestrator:** `plan → act → observe → iterate` state machine
- **Tool interface:** `name`, `description`, `input_schema`, `execute()` base class with retry/re-plan (cap 3)

---

## Compliance Notes

- `httpx.AsyncClient` is created with `trust_env=False` — this prevents the host's `HTTPS_PROXY` / `ALL_PROXY` environment variables from silently routing inference traffic through an external proxy.
- No `openai`, `anthropic`, `boto3`, `azure-ai`, or equivalent SDK is imported. We speak to Ollama's raw OpenAI-compatible HTTP API directly.
- The `AuditLogger` uses `fcntl.LOCK_EX` for write serialization and `os.fsync()` to flush to disk before returning — audit records are not held in memory.
