<div align="center">

# 🔐 Sovereign Workbench

**A private, self-hosted, enterprise-grade AI workbench for regulated and security-critical organizations.**

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.5-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Ollama](https://img.shields.io/badge/Powered%20by-Ollama-black?logo=ollama&logoColor=white)](https://ollama.com/)
[![Qdrant](https://img.shields.io/badge/Vector%20DB-Qdrant-DC143C)](https://qdrant.tech/)
[![License: Private](https://img.shields.io/badge/License-Private-red)](.)

> **Zero external network calls. No cloud SDKs. No data exfiltration. Ever.**
>
> All models, tools, embeddings, vector stores, and sandboxes run entirely on your local machine.

</div>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Network Sovereignty Guarantee](#-network-sovereignty-guarantee)
- [Architecture](#-architecture)
- [Project Structure](#-project-structure)
- [Technology Stack](#-technology-stack)
- [AI Model Registry](#-ai-model-registry)
- [Phase Status](#-phase-status)
- [Prerequisites](#-prerequisites)
- [Quick Start](#-quick-start)
- [API Reference](#-api-reference)
- [RAG Pipeline](#-rag-pipeline)
- [Tool System](#-tool-system)
- [Code Execution Sandbox](#-code-execution-sandbox)
- [Document Generation](#-document-generation)
- [Audit Logging](#-audit-logging)
- [Hardware-Aware Tier Resolution](#-hardware-aware-tier-resolution)
- [Configuration Reference](#-configuration-reference)
- [Testing](#-testing)
- [Roadmap](#-roadmap)
- [Compliance Notes](#-compliance-notes)

---

## 🔍 Overview

**Sovereign Workbench** is a fully air-gap capable, enterprise-grade autonomous AI agent platform purpose-built for organizations where data cannot leave the premises — refineries, industrial operations, defense contractors, compliance teams, and regulated entities.

### Core Problem Solved

Public AI APIs (OpenAI, Anthropic, Google Cloud) violate data sovereignty by exporting confidential documents to external servers and exposing usage telemetry. Sovereign Workbench solves this by guaranteeing:

- ✅ **All inference** runs on local Ollama instances (Qwen 2.5 family)
- ✅ **All embeddings** generated locally via `bge-m3`
- ✅ **All vector search** served by a local Qdrant instance
- ✅ **All code execution** sandboxed in Docker with `--network=none`
- ✅ **All document generation** uses offline Python libraries
- ✅ **Every action** recorded in a cryptographically tamper-evident audit trail

### Target Users

Plant safety engineers · Compliance officers · Refinery operators · Industrial inspectors · Security administrators handling air-gapped or confidential industrial operations (MRPL / OISD).

---

## 🛡️ Network Sovereignty Guarantee

> **Zero external network calls at runtime.**

Every model call is validated against a `localhost`-only allowlist (`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`) in both the model registry loader and the audit logger.

- Any call to a **non-local endpoint** raises an immediate `ValueError`
- The violation is recorded in the audit trail as a **`SOVEREIGNTY VIOLATION`** event
- `httpx.AsyncClient` is created with `trust_env=False` — preventing OS `HTTPS_PROXY`/`ALL_PROXY` from silently routing inference traffic through an external proxy
- No `openai`, `anthropic`, `boto3`, `azure-ai`, or equivalent SDK is imported

---

## 🏗️ Architecture

```
                           ┌──────────────────────────────────────────────────────────┐
                           │                    CLIENT INTERFACE                      │
                           │  (FastAPI REST Endpoints / SSE Chat / Standalone Sandbox) │
                           └────────────────────────────┬─────────────────────────────┘
                                                        │
             ┌──────────────────────────────────────────┴────────────────────────────────────────┐
             │                                                                                   │
             ▼                                                                                   ▼
┌───────────────────────────┐                                                       ┌───────────────────────────┐
│   POST /sandbox/execute   │                                                       │       POST /chat          │
│  (Standalone Fast-Path)   │                                                       │   (Agent / Inference)     │
└─────────────┬─────────────┘                                                       └─────────────┬─────────────┘
              │                                                                                   │
              ▼                                                                                   ▼
┌───────────────────────────┐                                                       ┌───────────────────────────┐
│      SandboxManager       │                                                       │     Capability Router     │
│   (app/sandbox/manager)   │                                                       │   · Heuristic Classifier  │
└─────────────┬─────────────┘                                                       │   · LLM Fallback (Qwen)   │
              │                                                                     └─────────────┬─────────────┘
              ▼                                                                                   │
┌───────────────────────────┐                                                                     ▼
│       DockerRunner        │                                                       ┌───────────────────────────┐
│   · --network=none        │                                                       │     Agent Orchestrator    │
│   · --read-only / tmpfs   │                                                       │ (Plan→Act→Observe→Iterate)│
│   · --memory=128m         │                                                       └─────────────┬─────────────┘
└───────────────────────────┘                    ┌───────────────────────────────────────────────┼─────────────────────────────────┐
                                                 │                                               │                                 │
                                                 ▼                                               ▼                                 ▼
                                   ┌───────────────────────────┐                ┌───────────────────────────┐   ┌───────────────────────────┐
                                   │       TOOL REGISTRY       │                │       OLLAMA CLIENT       │   │       AUDIT LOGGER        │
                                   │ ──────────────────────── ─│                │ ──────────────────────── ─│   │ ──────────────────────── ─│
                                   │ · file_read               │                │ · qwen2.5:14b (Reasoning) │   │ · logs/audit.jsonl        │
                                   │ · rag_search (Qdrant)     │                │ · qwen2.5-coder:14b (Code)│   │ · SHA-256 Hash Chain      │
                                   │ · code_sandbox (Docker)   │                │ · qwen2.5vl:7b (Vision)   │   │ · fcntl File Locking      │
                                   │ · generate_docx (Word)    │                │ · bge-m3 (Embeddings)     │   │ · Localhost Guardrail     │
                                   │ · generate_pptx (Slides)  │                │ · trust_env=False         │   └───────────────────────────┘
                                   │ · generate_xlsx (Excel)   │                └───────────────────────────┘
                                   │ · vision_extract (OCR)    │
                                   └─────────────┬─────────────┘
                                                 │
                                                 ▼
                                   ┌───────────────────────────┐
                                   │   LOCAL RAG KNOWLEDGE     │
                                   │ ──────────────────────── ─│
                                   │ · Qdrant (localhost:6333) │
                                   │ · MRPL Public Docs (PDF)  │
                                   │ · OISD Refinery Standards │
                                   │ · Cosine Dist (1024-dim)  │
                                   └───────────────────────────┘
```

### Two-Stage Routing Flow

```
User Prompt + Attachments + Hints
              │
              ▼
Stage 1: Heuristic Classifier (zero-latency)
├── 1. Check explicit_capability_hint  (confidence = 1.0)
├── 2. Check file extensions (.pdf/.png → Vision; .py/.sql → Code)
└── 3. Check regex keyword patterns (tracebacks, OCR, charts)
              │
      Confidence ≥ 0.75?
     ┌─────────┴─────────┐
    YES                  NO (Ambiguous)
     │                   │
     ▼                   ▼
 Return Model    Stage 2: LLM Classifier
 (Heuristic)     ├── Prompt small text model
                 ├── Temperature: 0.0, Max tokens: 16
                 └── Parse output into Capability enum
                             │
                    Recognized Label?
                   ┌─────────┴─────────┐
                  YES                  NO
                   │                   │
                   ▼                   ▼
             Return Model     Default Text Fallback
             (LLM Stage)      (qwen25_14b_instruct)
```

### Agent Orchestrator State Machine

```
IDLE → PLANNING → ACTING → OBSERVING → (REPLANNING) → COMPLETED / FAILED
                                 ↑______________|  (max 3 retries)
```

---

## 📁 Project Structure

```
sovereign-workbench/
├── app/
│   ├── main.py                       ← FastAPI entrypoint, lifespan manager & route handlers
│   ├── config/
│   │   └── models.yaml               ← Single source of truth for all models (tags, VRAM, tiers)
│   ├── models/
│   │   └── ollama_client.py          ← Async HTTP client for Ollama (chat, SSE stream, embeddings)
│   ├── audit/
│   │   └── logger.py                 ← Hash-chained, append-only JSONL logger with flock/fsync
│   ├── hardware/
│   │   ├── gpu_detect.py             ← Zero-dependency nvidia-smi CSV parser
│   │   └── tier_resolver.py          ← VRAM budget allocator (15% headroom) & model tier mapper
│   ├── router/
│   │   ├── heuristics.py             ← Zero-latency regex/extension/hint rule classifier
│   │   ├── llm_classifier.py         ← Fallback LLM prompt classifier for ambiguous inputs
│   │   └── router.py                 ← Two-stage orchestration returning RoutingDecision
│   ├── orchestrator/
│   │   ├── state.py                  ← Dataclasses (PlannedStep, StepOutcome, OrchestratorRun)
│   │   └── orchestrator.py           ← Plan→Act→Observe→Iterate engine with 3-retry replanning
│   ├── rag/
│   │   ├── chunker.py                ← Sliding-window text chunker & PyMuPDF page-aware chunker
│   │   ├── embedder.py               ← Batch embedding generator using local bge-m3 via Ollama
│   │   ├── store.py                  ← Local Qdrant client wrapper (filtered search, deterministic IDs)
│   │   ├── ingestor.py               ← Single-file ingestion pipeline with SHA-256 document hashing
│   │   ├── ingest.py                 ← Folder-level batch ingestion pipeline
│   │   └── eval.py                   ← Evaluation engine executing queries from eval_set.yaml
│   ├── sandbox/
│   │   ├── docker_runner.py          ← Subprocess docker execution with strict isolation flags
│   │   ├── manager.py                ← Workspace lifecycle manager (tempfile creation & cleanup)
│   │   ├── models.py                 ← Pydantic schemas (ExecuteRequest, ExecuteResponse)
│   │   └── router.py                 ← FastAPI router for POST /sandbox/execute
│   └── tools/
│       ├── base.py                   ← BaseTool abstract interface & ToolResult dataclass
│       ├── registry.py               ← Static & dynamic tool registry (TOOL_REGISTRY)
│       ├── file_read.py              ← Line-bounded, size-capped safe local file reader
│       ├── rag_search.py             ← Semantic search tool integrated with VectorStore & Embedder
│       ├── code_sandbox.py           ← Orchestrator-integrated Docker Python execution tool
│       ├── vision_extract.py         ← Multimodal structured JSON extraction (Pillow/pdf2image)
│       └── docgen/
│           ├── generate_docx.py      ← Formatted Microsoft Word document generator
│           ├── generate_pptx.py      ← Formatted Microsoft PowerPoint slide deck generator
│           └── generate_xlsx.py      ← Formatted Microsoft Excel workbook generator
├── knowledge_base/
│   ├── mrpl_public/                  ← MRPL Sustainability, RTI, financial & environment reports
│   ├── oisd_standards/               ← OISD-STD-174/175/176/181/183/185 refinery safety standards
│   └── synthetic_demo/               ← Synthetic inspection reports & SOPs for demo
├── sandbox/
│   └── python/
│       └── Dockerfile                ← Hardened non-root Python 3.11-slim sandbox image
├── tests/
│   ├── test_phase_a.py               ← Phase A: Foundation, Ollama client, AuditLogger (8 tests)
│   ├── test_phase_b.py               ← Phase B: Router heuristics, Orchestrator loop (12 tests)
│   ├── test_phase_c.py               ← Phase C: Chunker, Embedder, Qdrant store, Ingest (24 tests)
│   └── test_phase_d.py               ← Phase D: VisionExtract, DocGen, Sandbox (18 tests)
├── outputs/generated/                ← Generated .docx, .pptx, .xlsx artifacts
├── logs/                             ← Audit logs & run traces (gitignored)
├── eval_set.yaml                     ← Retrieval evaluation query benchmark set
├── smoke_test_phase_b.py             ← Live Ollama Phase B integration test
├── smoke_test_phase_c.py             ← Live RAG Phase C integration test
├── verify_phases_abc.py              ← Multi-stage live system verification script
├── requirements.txt
├── .env.example
└── README.md
```

---

## ⚙️ Technology Stack

| Category | Library / Tool | Version | Purpose |
|---|---|---|---|
| **API Framework** | FastAPI + uvicorn | 0.115.5 / 0.32.1 | REST API, SSE streaming |
| **Data Validation** | Pydantic | 2.10.3 | Request/response schemas |
| **HTTP Client** | httpx | 0.28.1 | Async Ollama API calls (`trust_env=False`) |
| **Config** | PyYAML | 6.0.2 | `models.yaml` parsing |
| **Inference Engine** | Ollama | local | LLM hosting (Qwen 2.5 family) |
| **Vector Database** | Qdrant | 1.12.1 | Local embedding storage & retrieval |
| **PDF Parsing** | PyMuPDF (`fitz`) | 1.25.1 | Page-aware PDF text extraction |
| **Image Processing** | Pillow + pdf2image | ≥10.0.0 / ≥1.17.0 | Vision OCR rasterization |
| **Word Generation** | python-docx | 1.1.2 | `.docx` report generation |
| **PowerPoint** | python-pptx | 1.0.2 | `.pptx` slide deck generation |
| **Excel** | openpyxl | 3.1.5 | `.xlsx` workbook generation |
| **Testing** | pytest + pytest-asyncio | 8.3.4 / 0.24.0 | Unit & async test runner |
| **HTTP Mocking** | respx | 0.21.1 | Offline Ollama API mocking |

---

## 🤖 AI Model Registry

All models are defined in `app/config/models.yaml` — the single source of truth. No model may be called unless registered here.

| Model Name | Modality | Ollama Tag | Context | Tier | Est. VRAM | Capability Tags |
|---|---|---|---|---|---|---|
| `qwen25_7b_instruct` | Text | `qwen2.5:7b-instruct-q4_K_M` | 32,768 | `small` | 4,500 MB | chat, reasoning, summarization, document_qa |
| `qwen25_14b_instruct` | Text | `qwen2.5:14b-instruct-q4_K_M` | 32,768 | `mid` | 9,000 MB | chat, reasoning, summarization, document_qa |
| `qwen25_32b_instruct` | Text | `qwen2.5:32b-instruct-q4_K_M` | 32,768 | `large` | 19,000 MB | chat, reasoning, complex_reasoning |
| `qwen25_coder_7b` | Code | `qwen2.5-coder:7b` | 32,768 | `small` | 4,500 MB | code_generation, code_review, debugging |
| `qwen25_coder_14b` | Code | `qwen2.5-coder:14b` | 32,768 | `mid` | 9,000 MB | code_generation, complex_code, refactoring |
| `qwen25vl_3b` | Vision | `qwen2.5vl:3b` | 32,768 | `small` | 3,000 MB | ocr, image_understanding, vision_extraction |
| `qwen25vl_7b` | Vision | `qwen2.5vl:7b` | 32,768 | `mid` | 6,000 MB | ocr, document_vision, chart_analysis |
| `bge_m3` | Embedding | `bge-m3` | 8,192 | `default` | 1,200 MB | embedding, rag, semantic_search |

---

## 📊 Phase Status

| Phase | Title | Status | Completion |
|---|---|:---:|:---:|
| **Phase A** | Sovereign Foundation & Local LLM | ✅ **COMPLETE** | **100%** |
| **Phase B** | Routing & Autonomous Agent | ✅ **COMPLETE** | **100%** |
| **Phase C** | Local RAG & Hardware Adaptation | ✅ **COMPLETE** | **100%** |
| **Phase D** | Sandbox & Document Generation | ✅ **COMPLETE** | **100%** |
| **Phase E** | Hardened Sovereignty & Compliance | ⏳ **PLANNED** | 0% |
| **Phase F** | Web UI & Multimodal Operations | ⏳ **PLANNED** | 0% |

```
Overall Progress: [████████████████████████████████████░░░░░░░░░░░░░░] ~70% Complete
├── Phase A: [████████████████████] 100% ✅  Foundation, model registry, local LLM, audit log
├── Phase B: [████████████████████] 100% ✅  Router, orchestrator, tool framework
├── Phase C: [████████████████████] 100% ✅  Local RAG, vector search, hardware adaptation
├── Phase D: [████████████████████] 100% ✅  Code sandbox, Office doc generation, vision OCR
├── Phase E: [░░░░░░░░░░░░░░░░░░░░]   0% ⏳  Air-gap firewall, audit sealing, compliance CLI
└── Phase F: [░░░░░░░░░░░░░░░░░░░░]   0% ⏳  Web UI, agent inspector, knowledge manager
```

---

## 📦 Prerequisites

- **Python 3.11** (recommended; 3.11–3.13 compatible)
- **[Ollama](https://ollama.com)** running locally (`ollama serve`)
- **[Docker](https://www.docker.com/)** — for the isolated code execution sandbox
- **[Qdrant](https://qdrant.tech/documentation/quick-start/)** — local vector database on `localhost:6333`

### Pull Required Models

```bash
ollama pull qwen2.5:14b-instruct-q4_K_M   # Primary reasoning model
ollama pull qwen2.5:7b-instruct-q4_K_M    # Small tier fallback
ollama pull qwen2.5-coder:14b              # Code generation & review
ollama pull qwen2.5-coder:7b               # Small tier code model
ollama pull qwen2.5vl:7b                   # Vision/OCR multimodal
ollama pull qwen2.5vl:3b                   # Small tier vision
ollama pull bge-m3                         # Local embedding model
```

### Build the Sandbox Docker Image

```bash
cd sovereign-workbench
docker build -t sovereign-sandbox-python ./sandbox/python/
```

---

## 🚀 Quick Start

```bash
# 1. Clone and enter the workspace
cd sovereign-workbench

# 2. Create and activate virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install all dependencies
pip install -r requirements.txt

# 4. Configure environment (no API keys needed — intentional)
cp .env.example .env

# 5. Start Qdrant vector database (separate terminal)
docker run -p 6333:6333 qdrant/qdrant

# 6. Start Ollama inference server (separate terminal)
ollama serve

# 7. Start the Sovereign Workbench
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The server is available at `http://127.0.0.1:8000`.  
Visit `http://127.0.0.1:8000/docs` for the interactive API explorer.

### Verify Sovereignty (Offline Test)

```bash
# Disable your network interface, then:
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Are you running locally?"}]}' | jq .

# Watch the audit trail
tail -f logs/audit.jsonl | jq .
```

Expected: request succeeds, response comes from `qwen2.5:14b-instruct-q4_K_M`, and `logs/audit.jsonl` contains a `model_call` entry with `"endpoint": "http://localhost:11434"`.

---

## 🌐 API Reference

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness & subsystem status probe |
| `GET` | `/models` | List all registered models from `models.yaml` |
| `GET` | `/tools` | List all registered agent tools with input schemas |
| `POST` | `/chat` | Streaming (SSE) or batch chat completion via the autonomous agent |
| `POST` | `/ingest` | Ingest a local document into a Qdrant collection |
| `POST` | `/rag/search` | Standalone semantic vector search |
| `POST` | `/sandbox/execute` | Execute Python code in an isolated Docker container |

### Chat — SSE Streaming

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Summarize OISD fire protection standards"}],
    "stream": true
  }'
```

### Document Ingestion

```bash
curl -s -X POST http://127.0.0.1:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source_path": "/path/to/document.pdf",
    "collection": "docs"
  }' | jq .
```

### Semantic Search

```bash
curl -s -X POST http://127.0.0.1:8000/rag/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "fire suppression requirements for petroleum storage",
    "collection": "docs",
    "top_k": 5
  }' | jq .
```

### Sandbox Execution

```bash
curl -s -X POST http://127.0.0.1:8000/sandbox/execute \
  -H "Content-Type: application/json" \
  -d '{
    "code": "import math\nresult = math.sqrt(144)\nprint(f\"Result: {result}\")",
    "timeout": 10
  }' | jq .
```

---

## 📚 RAG Pipeline

The local Retrieval-Augmented Generation pipeline provides factual grounding from your private knowledge base — completely offline.

### Ingestion Flow

```
knowledge_base/ (PDF / TXT)
        │
        ▼
 1. Document Loader  (PyMuPDF for PDF, stdlib for text)
        │
        ▼
 2. Sliding-Window Chunker
    ├── Text: 512 chars, 64-char overlap
    └── PDF:  600 chars/page, 90-char overlap
        │
        ▼
 3. Provenance Tagging
    ├── doc_name, page_number, chunk_index
    ├── source_category  (mrpl_public | oisd_standards)
    ├── status           (in_force | withdrawn)
    └── confidentiality  (public | internal | confidential)
        │
        ▼
 4. Deterministic UUID
    UUID = UUID5(SHA-256(doc_name + page_number + chunk_index)[:16])
        │
        ▼
 5. Local Embedding  (bge-m3 via Ollama → 1024-dim vectors)
        │
        ▼
 6. Qdrant Upsert  (localhost:6333, Cosine similarity)
```

### Knowledge Base Contents

| Category | Contents |
|---|---|
| `mrpl_public/` | MRPL Sustainability Reports (FY 2023-24, 2024-25), Annual Report, RTI Act, Environment Report |
| `oisd_standards/` | OISD-STD-174/175/176/181/183/185 — Oil Industry Safety Directorate standards |
| `synthetic_demo/` | Synthetic CDU inspection report & SOP approval note for demos |

### Ingest Your Own Documents

```bash
# Via REST API
curl -X POST http://127.0.0.1:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"source_path": "knowledge_base/oisd_standards", "collection": "oisd"}'

# Via Python
from app.rag.ingest import ingest_folder
import asyncio
asyncio.run(ingest_folder("knowledge_base/oisd_standards", collection="oisd"))
```

---

## 🔧 Tool System

All agent tools inherit from `BaseTool` and return a `ToolResult`. Tools **never throw unhandled exceptions** during `execute()`.

```python
@dataclass
class ToolResult:
    success: bool
    output: Any
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Registered Tools

| Tool Name | Module | Description |
|---|---|---|
| `file_read` | `app/tools/file_read.py` | Line-bounded local file reader with 512KB cap & binary sniffing |
| `rag_search` | `app/tools/rag_search.py` | Semantic vector search with status/category filtering & citations |
| `code_sandbox` | `app/tools/code_sandbox.py` | Python execution in Docker (`--network=none`, 256MB RAM, 120s) |
| `generate_docx` | `app/tools/docgen/generate_docx.py` | Word report generator (headings, tables, recommendations) |
| `generate_pptx` | `app/tools/docgen/generate_pptx.py` | PowerPoint deck generator (title & content slides) |
| `generate_xlsx` | `app/tools/docgen/generate_xlsx.py` | Excel workbook generator (headers, rows, formulas, auto-width) |
| `vision_extract` | `app/tools/vision_extract.py` | Structured JSON extraction from images & PDFs via `qwen2.5vl` |

---

## 🐳 Code Execution Sandbox

Two complementary sandbox implementations exist for different use cases.

| Property | Standalone (`/sandbox/execute`) | Agent Tool (`code_sandbox`) |
|---|---|---|
| **Network** | `--network=none` | `--network=none` |
| **Memory** | `--memory=128m` (hard swap) | `--memory=256m` |
| **CPU** | `--cpus=0.5` | `--cpus=0.5` |
| **Filesystem** | `--read-only` + `--tmpfs /tmp:32m` | `--read-only` + `--tmpfs /tmp:64m` |
| **User** | Non-root `sandboxuser` (uid=1000) | Container default |
| **Process Limit** | `--pids-limit=64` (fork-bomb protection) | Container default |
| **Privilege Escalation** | `--security-opt no-new-privileges` | Not set |
| **Timeout** | 10s default (max 30s) | 120s wall-clock |
| **Audit Logging** | Omitted (pure isolation) | `SANDBOX_EXEC` event (SHA-256, duration) |

---

## 📄 Document Generation

The agent can autonomously generate enterprise-ready office documents without any external services. All outputs land in `outputs/generated/` and are recorded as `DOCGEN` audit events.

### Word Documents (`.docx`)

```json
{
  "tool": "generate_docx",
  "args": {
    "title": "CDU Unit 4 Inspection Report",
    "sections": [
      {"heading": "Executive Summary", "content": "..."},
      {"heading": "Critical Findings",  "content": "..."}
    ],
    "findings_table": [
      {"id": "F-001", "finding": "Corrosion on heat exchanger", "severity": "HIGH", "status": "Open"}
    ],
    "output_filename": "inspection_report.docx"
  }
}
```

### PowerPoint Slides (`.pptx`)

```json
{
  "tool": "generate_pptx",
  "args": {
    "title": "Safety Compliance Q3 2026",
    "slides": [
      {"heading": "Key Findings",  "bullets": ["Finding 1", "Finding 2"]},
      {"heading": "Action Items",  "bullets": ["Action 1", "Action 2"]}
    ],
    "output_filename": "compliance_brief.pptx"
  }
}
```

### Excel Workbooks (`.xlsx`)

```json
{
  "tool": "generate_xlsx",
  "args": {
    "headers": ["Equipment", "Risk Score", "Last Inspected"],
    "rows": [
      ["CDU-4", 8.2, "2026-07-15"],
      ["FCC-2", 6.1, "2026-06-30"]
    ],
    "formula_row": ["TOTALS", "=AVERAGE(B2:B3)", ""],
    "output_filename": "risk_matrix.xlsx"
  }
}
```

---

## 📋 Audit Logging

Every action is recorded in `logs/audit.jsonl` — a cryptographically tamper-evident, append-only log with SHA-256 hash chaining.

### Log Record Format

```json
{
  "event_type": "model_call",
  "timestamp_utc": "2026-09-01T10:23:45.123456+00:00",
  "request_id": "3f7a1b2c-...",
  "sequence": 42,
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

`prev_hash` = SHA-256 of the previous record (with `self_hash=""` during hashing)  
`self_hash` = SHA-256 of this record (with `self_hash=""` during hashing)

This forms a hash chain verifiable with `AuditLogger.verify_chain()`.

### Verify Chain Integrity

```python
from app.audit.logger import AuditLogger
logger = AuditLogger("logs/audit.jsonl")
is_valid, broken_at = logger.verify_chain()
print(f"Chain valid: {is_valid}, broken at sequence: {broken_at}")
```

### Event Types

| Event Type | Description |
|---|---|
| `model_call` | LLM completion — tokens, latency, endpoint |
| `tool_call` | Tool dispatch & observation result |
| `route_decision` | Heuristic/LLM routing decision |
| `agent_action` | Orchestrator state transitions (`plan_produced`, `retry_triggered`) |
| `rag_ingest` | Document ingestion — chunks, SHA-256 fingerprint |
| `rag_retrieval` | Retrieval query — top-k hits, source citations |
| `vision_extract` | Multimodal extraction — page count, field/table counts |
| `docgen` | Word/PowerPoint/Excel generation event |
| `sandbox_exec` | Python sandbox — code SHA-256, exit code, duration |
| `file_write` | Output artifact file creation |
| `startup` | Logger init & hardware model resolution |
| `error` | Caught exceptions, timeouts, sovereignty violations |

---

## 🖥️ Hardware-Aware Tier Resolution

Sovereign Workbench automatically adapts to available GPU VRAM without requiring PyTorch or PyNVML.

```
1. GPU Detection  (app/hardware/gpu_detect.py)
   └── nvidia-smi --query-gpu=memory.total,memory.free,name --format=csv,noheader,nounits
       ├── GPU found  → total_vram_mb, free_vram_mb
       └── No GPU / macOS / CPU  → gpu_available: False, zeroed VRAM

2. Budget Calculation
   budget_vram = free_vram_mb × 0.85   (15% safety headroom)

3. Model Selection  (app/hardware/tier_resolver.py)
   └── For each modality (text · code · vision · embedding):
       ├── Sort models descending by est_vram_mb
       ├── Select largest model fitting within remaining budget
       └── Fallback to 'small' tier if budget is 0 or no model fits
```

### Override Tier Manually

```bash
# Force small models (CPU / low-VRAM machines)
FORCE_TIER=small uvicorn app.main:app --host 127.0.0.1 --port 8000

# Force large models (high-end GPU machines)
FORCE_TIER=large uvicorn app.main:app --host 127.0.0.1 --port 8000
```

---

## ⚙️ Configuration Reference

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_MODEL` | `qwen25_14b_instruct` | Fallback text model if tier resolver is bypassed |
| `AUDIT_LOG_PATH` | `logs/audit.jsonl` | Filepath for the append-only cryptographic audit trail |
| `FORCE_TIER` | *(auto-detect)* | Force model tier: `small`, `mid`, `large`, `default` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local Ollama inference server endpoint |
| `QDRANT_HOST` | `localhost` | Local Qdrant vector database host |
| `QDRANT_PORT` | `6333` | Local Qdrant vector database port |

Hardcoded defaults in `app/config/models.yaml` and source code:

| Setting | Default | Description |
|---|---|---|
| Sandbox Memory (standalone) | `128m` | Hard memory limit for `/sandbox/execute` |
| Sandbox Memory (tool) | `256m` | Memory limit for `code_sandbox` agent tool |
| Max Tool Retries | `3` | Maximum retry attempts per orchestrator step |
| File Read Cap | `524,288` (512 KB) | Maximum bytes read by `file_read` tool |
| Embedding Dimensions | `1024` | Output dimension for `bge-m3` vectors |

---

## 🧪 Testing

### Unit Tests — No Live Ollama Required

All HTTP calls are intercepted by `respx`. Run fully offline.

```bash
# Run all 62 tests across all phases
pytest tests/ -v

# Run individual phases
pytest tests/test_phase_a.py -v   #  8 tests — Foundation, audit, sovereignty
pytest tests/test_phase_b.py -v   # 12 tests — Router, orchestrator, file_read
pytest tests/test_phase_c.py -v   # 24 tests — RAG, GPU, tier, Qdrant, ingestor
pytest tests/test_phase_d.py -v   # 18 tests — Vision, DocGen, Sandbox
```

### Live Integration Smoke Tests — Requires Ollama + Qdrant

```bash
# Phase B end-to-end with live LLM
python smoke_test_phase_b.py

# Phase C end-to-end with live RAG
python smoke_test_phase_c.py

# Full multi-stage system verification (GPU, models, orchestrator, RAG, citations)
python verify_phases_abc.py
```

### Test Suite Summary

| Suite | Tests | Coverage |
|---|---|---|
| `test_phase_a.py` | 8 | Health, chat, audit chain integrity, localhost enforcement, sovereignty violations |
| `test_phase_b.py` | 12 | Heuristic router, LLM fallback, file reader safety, orchestrator happy path, retry & failure halting |
| `test_phase_c.py` | 24 | Chunking, GPU detection, tier resolution, embedder, Qdrant upsert/search, ingestor, withdrawn chunk exclusion |
| `test_phase_d.py` | 18 | VisionExtract JSON parsing & retries, Word/PPT/Excel generation, Docker sandbox execution & timeouts |

---

## 🗺️ Roadmap

### Phase E — Hardened Air-Gap Sovereignty & Compliance

- [ ] **Host-Level Air-Gap Firewall** — `nftables`/`iptables` egress-blocking scripts (loopback-only)
- [ ] **Automated Penetration Tests** — `scripts/verify_airgap.py` socket-level verification
- [ ] **Cryptographic Audit Sealing** — Ed25519/HMAC signing of audit log batches
- [ ] **Log Rotation with Chain Continuity** — Automated rotation preserving hash-chain integrity
- [ ] **Compliance Verification CLI** — Standalone `scripts/verify_audit_log.py` for compliance officers
- [ ] **Compliance Report Generator** — PDF/Markdown audit summary export

### Phase F — Web UI, Multimodal & Enterprise Tooling

- [ ] **Self-Hosted Chat Interface** — Real-time SSE streaming, model selector, conversation history
- [ ] **Agent Inspector** — Visual timeline of `PLANNING → ACTING → OBSERVING → SYNTHESIS` with tool I/O
- [ ] **Knowledge Base Manager** — Web UI for document upload, ingestion stats, semantic query testing
- [ ] **Audit Trail Dashboard** — Visual log explorer, hash-chain status, sovereignty violation alerts
- [ ] **Vision API Endpoint** — `/vision` for chart interpretation, diagram analysis, image Q&A
- [ ] **Unified Test Runner** — `Makefile` running offline unit, live smoke, and integration tests

---

## 📜 Compliance Notes

This workbench was designed from the ground up for regulated environments:

1. **No Proxy Leakage** — `httpx.AsyncClient(trust_env=False)` prevents `HTTPS_PROXY`/`ALL_PROXY` from silently rerouting inference traffic.

2. **No Proprietary Cloud SDKs** — `openai`, `anthropic`, `boto3`, `azure-ai` are never imported. All inference uses Ollama's raw OpenAI-compatible HTTP API directly.

3. **Atomic Audit Writes** — `AuditLogger` uses `fcntl.LOCK_EX` for write serialization across concurrent async tasks and processes, and `os.fsync()` to guarantee physical disk flush before returning.

4. **Deterministic Re-ingestion** — Point IDs are derived deterministically via SHA-256 of document content and chunk position. Re-running ingestion updates existing vectors in place without creating duplicates.

5. **Sovereignty Enforced at Every Layer** — The localhost allowlist is validated at both the `OllamaClient` constructor level *and* the `AuditLogger` write level. A non-local endpoint cannot be called without both raising an exception and writing a `SOVEREIGNTY VIOLATION` record.

---

<div align="center">

**Sovereign Workbench** — *Your data. Your models. Your machine. Always.*

</div>
