# Sovereign Workbench — Project Implementation Status & Roadmap

> **Repository:** `Sovereign Workbench` (Private, Self-Hosted, Air-Gapped AI Workbench)  
> **Status Date:** August 2026  
> **Current Version:** `0.1.0-phase-c`  
> **Core Guarantee:** Zero external network calls at runtime, localhost-only validation, cryptographic hash-chained audit trails.

---

## 📊 Executive Summary & Phase Progress

| Phase | Title | Status | Completion | Key Capabilities Delivered |
| :--- | :--- | :---: | :---: | :--- |
| **Phase A** | **Sovereign Foundation & Local LLM** | ✅ **COMPLETED** | **100%** | Model registry, Ollama async client, FastAPI `/chat` (SSE + batch), hash-chained audit logger. |
| **Phase B** | **Routing & Autonomous Agent** | ✅ **COMPLETED** | **100%** | Heuristic + LLM router, Plan→Act→Observe→Iterate orchestrator, tool registry, `file_read` tool. |
| **Phase C** | **Local RAG & Hardware Adaptation** | ✅ **COMPLETED** | **100%** | GPU detection, VRAM tier resolver, Qdrant vector store, `bge-m3` embedder, `ingestor`, `rag_search` tool. |
| **Phase D** | **Sandbox & Document Generation** | ⏳ **PENDING** | **0%** | `--network=none` Docker sandbox (`CodeSandboxTool`), Word/Excel/PPT generation tools (`docx`, `xlsx`, `pptx`). |
| **Phase E** | **Hardened Sovereignty & Compliance** | ⏳ **PENDING** | **0%** | `nftables` air-gap firewall enforcement, cryptographic audit seals, compliance reporting CLI. |
| **Phase F** | **Web UI & Multimodal Operations** | ⏳ **PENDING** | **0%** | Self-hosted Web interface, visual agent execution trace, document management UI, vision OCR pipeline. |

```
Overall Progress: [██████████████████████████████░░░░░░░░░░░░░░░░░░░░] ~55% Completed
├── Phase A: [████████████████████] 100% (Completed)
├── Phase B: [████████████████████] 100% (Completed)
├── Phase C: [████████████████████] 100% (Completed)
├── Phase D: [░░░░░░░░░░░░░░░░░░░░]   0% (Next Up)
├── Phase E: [░░░░░░░░░░░░░░░░░░░░]   0% (Planned)
└── Phase F: [░░░░░░░░░░░░░░░░░░░░]   0% (Planned)
```

---

## 📁 Repository Codebase Architecture

```
sovereign-workbench/
├── app/
│   ├── main.py                     ← FastAPI entrypoint (/chat, /ingest, /rag/search, /health, /models, /tools)
│   ├── config/
│   │   └── models.yaml             ← Single source of truth for all models (text, code, vision, embedding)
│   ├── models/
│   │   └── ollama_client.py        ← Local async client (httpx, trust_env=False, zero external SDKs)
│   ├── audit/
│   │   └── logger.py               ← Append-only, hash-chained JSONL audit logger (with fcntl locking & fsync)
│   ├── hardware/
│   │   ├── gpu_detect.py           ← Zero-dependency nvidia-smi CSV parser
│   │   └── tier_resolver.py        ← Hardware-aware VRAM budget resolver (15% safety headroom)
│   ├── router/
│   │   ├── heuristics.py           ← Fast zero-model heuristic pass (extensions, regex, hints)
│   │   ├── llm_classifier.py       ← Fallback LLM prompt classifier for ambiguous queries
│   │   └── router.py               ← Orchestrates heuristic & LLM routing passes
│   ├── orchestrator/
│   │   ├── state.py                ← Orchestrator dataclasses & status enums
│   │   └── orchestrator.py         ← Plan → Act → Observe → Iterate loop with automatic replanning
│   ├── tools/
│   │   ├── base.py                 ← Abstract BaseTool and ToolResult dataclass
│   │   ├── registry.py             ← Static & dynamic tool registry
│   │   ├── file_read.py            ← Line-bounded, secure local file reader
│   │   └── rag_search.py           ← Semantic vector search tool via Qdrant
│   └── rag/
│       ├── chunker.py              ← Text & PDF sliding-window chunker (PyMuPDF)
│       ├── embedder.py             ← Local bge-m3 embedding generator via Ollama
│       ├── store.py                ← Qdrant vector store wrapper (localhost:6333, Cosine distance)
│       └── ingestor.py             ← File hasher, chunker, embedder, upsert pipeline + audit logger
├── knowledge_base/
│   └── mrpl_public/                ← Seeded enterprise PDF documents
├── tests/
│   ├── test_phase_a.py             ← Phase A smoke & sovereignty tests (8 tests)
│   ├── test_phase_b.py             ← Phase B routing & orchestrator tests (12 tests)
│   └── test_phase_c.py             ← Phase C RAG & hardware tier tests (15 tests)
├── smoke_test_phase_b.py           ← Real-model live end-to-end smoke test script
├── requirements.txt                ← Python dependencies
├── .env.example                    ← Configuration environment variables
└── README.md                       ← Initial system documentation
```

---

## 🛠️ Detailed Breakdown: What is COMPLETED

### 1. Phase A — Sovereign Foundation & Local Inference Engine ✅
- [x] **Model Registry (`app/config/models.yaml`)**
  - Single source of truth defining models, Ollama tags, endpoints, context lengths, tiers, and estimated VRAM footprint.
  - Multi-modality models configured: `qwen2.5:7b`, `14b`, `32b` (Text), `qwen2.5-coder:7b`, `14b` (Code), `qwen2.5vl:3b`, `7b` (Vision), `bge-m3` (Embedding).
- [x] **Strict Sovereignty Enforcement (`app/models/ollama_client.py`)**
  - `httpx.AsyncClient` configured with `trust_env=False` to prevent HTTP/HTTPS proxy leaks.
  - Runtime validation rejecting non-localhost endpoints (`ValueError` on external hosts).
  - No external commercial SDKs imported (`openai`, `anthropic`, `boto3`, etc.).
  - Support for chat completion, Server-Sent Events (SSE) streaming (`chat_stream`), and vector embeddings (`embeddings`).
- [x] **FastAPI Application Entrypoint (`app/main.py`)**
  - Endpoints: `GET /health`, `GET /models`, `GET /tools`, `POST /chat`.
  - Full support for both batch responses and streaming responses (`stream: true`).
  - Localhost CORS policy (`http://localhost:*`, `http://127.0.0.1:*`).
  - Lifespan management for clean initialization and shutdown.
- [x] **Tamper-Evident Hash-Chained Audit Logger (`app/audit/logger.py`)**
  - Append-only JSON-lines format (`logs/audit.jsonl`).
  - SHA-256 hash chaining (`prev_hash`, `self_hash`).
  - File locking (`fcntl.LOCK_EX`) and synchronous disk flushing (`os.fsync`) preventing write collisions.
  - Built-in chain verification tool (`AuditLogger.verify_chain()`).
- [x] **Phase A Test Suite (`tests/test_phase_a.py`)**
  - 8 unit tests mocking Ollama via `respx` to test health, chat, sovereignty violation rejection, error states, and hash-chain validity.

---

### 2. Phase B — Intelligent Routing & Autonomous Agent Orchestration ✅
- [x] **Two-Tier Capability Router (`app/router/`)**
  - **Heuristic Classifier (`heuristics.py`):** Zero-latency rule-based classifier matching file extensions (PDF, images, source files), caller hints, and regex keywords (tracebacks, errors, visual keywords).
  - **LLM Fallback Classifier (`llm_classifier.py`):** Low-temperature JSON classification prompt activated when heuristic confidence is below `0.75`.
  - **Unified Router (`router.py`):** Resolves requests to optimal models in `models.yaml` and logs `route_decision` audit events.
- [x] **Autonomous Agent State Machine (`app/orchestrator/`)**
  - Plan → Act → Observe → Iterate execution loop (`IDLE` → `PLANNING` → `ACTING` → `OBSERVING` → `REPLANNING` → `COMPLETED` / `FAILED`).
  - Resilient JSON parser extracting plans while stripping markdown code fences and inline `//` comments.
  - Automatic dynamic replanning on step failure with feedback injection.
  - Max retry cap (`MAX_RETRIES = 3`) to prevent infinite looping.
  - Final response synthesis combining all accumulated tool outputs into a coherent answer.
- [x] **Tool Framework & Built-in File Reader (`app/tools/`)**
  - `BaseTool` abstract interface with OpenAPI-compliant `input_schema` and `ToolResult` wrappers.
  - Static and dynamic tool registry `TOOL_REGISTRY` (`register_tool`, `get_tool`, `list_tools`).
  - `FileReadTool`: Safe local file reader with line ranges (`start_line`, `max_lines`), size caps, and directory boundary enforcement.
- [x] **Phase B Test Suite & Live Smoke Test**
  - `tests/test_phase_b.py`: 12 offline tests verifying router heuristics, LLM fallback, file reading, multi-step orchestration, retry limits, and audit chain.
  - `smoke_test_phase_b.py`: Live end-to-end integration test validating real Ollama model execution.

---

### 3. Phase C — Local RAG Knowledge Base & Hardware Adaptation ✅
- [x] **Hardware-Aware Tier Resolution (`app/hardware/`)**
  - `gpu_detect.py`: Zero-overhead GPU detection via `nvidia-smi` without requiring PyTorch or PyNVML.
  - `tier_resolver.py`: Calculates free VRAM budget with a 15% safety buffer (`budget = free_vram * 0.85`), groups models by modality, and selects the largest model that fits within budget.
  - `FORCE_TIER` environment override (`small`, `mid`, `large`, `default`).
  - Records `model_resolution` startup events in the audit log.
- [x] **Document Processing & Vector Ingestion Pipeline (`app/rag/`)**
  - `chunker.py`: Sliding-window text chunker (default 512 characters, 64-character overlap) and PyMuPDF PDF parser.
  - `embedder.py`: Batch embedding engine running `bge-m3` locally via Ollama.
  - `store.py`: Local Qdrant client (`localhost:6333`) utilizing Cosine similarity (1024 dimensions).
  - `ingestor.py`: Complete ingestion pipeline computing SHA-256 file fingerprints, chunking, embedding, upserting to Qdrant, and logging `rag_ingest` audit entries.
- [x] **RAG Search Tool & API Endpoints**
  - `RagSearchTool` in `app/tools/rag_search.py`: Connected to VectorStore and registered into the agent's `TOOL_REGISTRY`.
  - `POST /ingest`: FastAPI endpoint for ingesting local documents into custom Qdrant collections.
  - `POST /rag/search`: Standalone semantic search endpoint returning ranked results with similarity scores.
- [x] **Phase C Test Suite & Seeded Knowledge**
  - `tests/test_phase_c.py`: 15 unit tests covering chunking, GPU detection, tier resolution, embedding, Qdrant upsert/search, and ingestor workflows.
  - Seeded public enterprise sustainability, RTI, and financial reports under `knowledge_base/mrpl_public/`.

---

## ⏳ Detailed Breakdown: What is REMAINING (Roadmap)

### 1. Phase D — Isolated Code Sandbox & Office Document Generation
- [ ] **Secure Code Execution Sandbox (`sandbox/`)**
  - Create `sandbox/Dockerfile` (hardened Alpine/Debian Python runtime).
  - Enforce `--network=none` Docker flag to guarantee zero outbound network access during code execution.
  - Implement execution constraints: memory limits, CPU quotas, and strict timeouts (e.g. 15s).
  - Implement `CodeSandboxTool` in `app/tools/code_sandbox.py` allowing the agent to run Python data analysis, transformations, and mathematical calculations.
- [ ] **Office Document Generation Tools (`app/tools/`)**
  - `DocGenerateTool`: Generate formatted Word documents (`.docx`) with headers, tables, and paragraphs via `python-docx`.
  - `ExcelGenerateTool`: Generate formatted spreadsheets (`.xlsx`) with formulas, charts, and structured tables via `openpyxl`.
  - `PptxGenerateTool`: Generate slide presentations (`.pptx`) for executive briefs via `python-pptx`.
  - Tool registration and audit logging for all generated artifacts.
- [ ] **End-to-End Multi-Tool Agent Workflows**
  - Multi-step orchestration: Retrieve knowledge via RAG → Analyze data in Code Sandbox → Generate final Word/Excel report.
- [ ] **Phase D Test Suite**
  - Create `tests/test_phase_d.py` for sandbox execution, resource timeout handling, code error recovery, and document generation accuracy.

---

### 2. Phase E — Hardened Air-Gap Sovereignty & Compliance Auditing
- [ ] **Host-Level Air-Gap Enforcement Scripts**
  - Linux `nftables` / `iptables` configuration script to block all egress packets except loopback (`lo`).
  - Automated network penetration test script (`scripts/verify_airgap.py`) verifying socket attempts fail immediately.
- [ ] **Cryptographic Audit Log Hardening**
  - Asymmetric cryptographic digital signing (e.g., Ed25519 or HMAC key) for sealing audit batches.
  - Automated log rotation system maintaining continuous hash-chain integrity across log files.
- [ ] **Compliance & Audit Verification CLI**
  - Standalone verification CLI (`app/audit/cli.py` or `scripts/verify_audit_log.py`) enabling compliance officers to verify tamper-evidence, token consumption, and model call origins.
  - Compliance report generator (PDF/Markdown export of audit summaries).

---

### 3. Phase F — Web UI, Multimodal Vision & Enterprise Operations
- [ ] **Self-Hosted Web Interface / Dashboard**
  - Interactive Chat Interface: Real-time SSE streaming, model selector, and conversation history.
  - Agent Inspector: Visual timeline showing agent steps (`PLANNING` → `ACTING` → `OBSERVING` → `SYNTHESIS`) with tool inputs/outputs and retry attempts.
  - Knowledge Base Manager: Web UI for uploading documents, initiating ingestion, viewing collection statistics, and testing semantic queries.
  - Audit Trail Dashboard: Visual explorer for log records, hash chain status, and sovereignty violation alerts.
- [ ] **Multimodal Vision & OCR Pipeline**
  - Implement `/vision` API endpoint and `VisionTool` utilizing `qwen2.5vl` for chart interpretation, diagram analysis, and image QA.
  - OCR fallback pipeline for scanned PDFs and image-heavy documents during ingestion.
- [ ] **Documentation & CI/CD Tooling**
  - Update `README.md` to document Phase B, Phase C, and Phase D features, environment variables, and setup instructions.
  - Create a unified test runner (`run_all_tests.py` / `Makefile`) to run offline unit tests, mock suites, and live smoke tests.

---

## 📋 Comprehensive Status Checklist by File & Component

| Component | Target File | Status | Description |
| :--- | :--- | :---: | :--- |
| **Model Registry** | `app/config/models.yaml` | ✅ Complete | Single source of truth for all models across 4 modalities. |
| **Ollama Client** | `app/models/ollama_client.py` | ✅ Complete | Async client, zero proxy leak (`trust_env=False`), chat + stream + embeddings. |
| **Audit Logger** | `app/audit/logger.py` | ✅ Complete | JSONL, SHA-256 hash chaining, `fcntl` locking, fsync disk flushing. |
| **FastAPI Core** | `app/main.py` | ✅ Complete | `/chat` (SSE & batch), `/ingest`, `/rag/search`, `/health`, `/models`, `/tools`. |
| **GPU Detection** | `app/hardware/gpu_detect.py` | ✅ Complete | Subprocess `nvidia-smi` parser without torch/nvml dependencies. |
| **Tier Resolver** | `app/hardware/tier_resolver.py` | ✅ Complete | VRAM budget calculator (15% buffer) and modality model selector. |
| **Heuristics Router** | `app/router/heuristics.py` | ✅ Complete | Zero-model fast pass (extensions, regex, hints). |
| **LLM Classifier** | `app/router/llm_classifier.py` | ✅ Complete | Ambiguity fallback classifier prompt. |
| **Router Engine** | `app/router/router.py` | ✅ Complete | Orchestrates heuristic + LLM routing and audit logging. |
| **Orchestrator** | `app/orchestrator/orchestrator.py` | ✅ Complete | Plan→Act→Observe→Iterate state machine with 3-retry replanning. |
| **Agent State** | `app/orchestrator/state.py` | ✅ Complete | Step, run, and status data models. |
| **Tool Registry** | `app/tools/registry.py` | ✅ Complete | Static & dynamic tool registration system. |
| **Tool Base** | `app/tools/base.py` | ✅ Complete | `BaseTool` class, `ToolResult` schema. |
| **File Read Tool** | `app/tools/file_read.py` | ✅ Complete | Line-bounded local file reader. |
| **RAG Search Tool** | `app/tools/rag_search.py` | ✅ Complete | Semantic retrieval tool integrated with Qdrant and Embedder. |
| **Text/PDF Chunker**| `app/rag/chunker.py` | ✅ Complete | Text & PyMuPDF PDF chunker. |
| **Embedder** | `app/rag/embedder.py` | ✅ Complete | `bge-m3` embedding interface. |
| **Vector Store** | `app/rag/store.py` | ✅ Complete | Qdrant client wrapper (`localhost:6333`, Cosine distance). |
| **Ingestor** | `app/rag/ingestor.py` | ✅ Complete | SHA-256 hash, chunk, embed, upsert, audit log pipeline. |
| **Phase A Tests** | `tests/test_phase_a.py` | ✅ Complete | 8 offline tests. |
| **Phase B Tests** | `tests/test_phase_b.py` | ✅ Complete | 12 offline tests. |
| **Phase C Tests** | `tests/test_phase_c.py` | ✅ Complete | 15 offline tests. |
| **Phase B Smoke** | `smoke_test_phase_b.py` | ✅ Complete | Live Ollama integration test. |
| **Code Sandbox** | `sandbox/Dockerfile` + `app/tools/code_sandbox.py` | ⏳ Pending | Phase D: `--network=none` isolated execution environment. |
| **Doc Gen Tools** | `app/tools/doc_gen.py` | ⏳ Pending | Phase D: Word (`.docx`), Excel (`.xlsx`), PowerPoint (`.pptx`) generators. |
| **Air-Gap Rules** | `scripts/airgap_nftables.sh` | ⏳ Pending | Phase E: Firewall egress blocking rules. |
| **Audit CLI** | `app/audit/cli.py` | ⏳ Pending | Phase E: Standalone compliance validator and export tool. |
| **Web UI** | `app/ui/` or `frontend/` | ⏳ Pending | Phase F: Chat UI, Agent trace viewer, and Knowledge manager. |
| **Vision Endpoint**| `app/tools/vision.py` | ⏳ Pending | Phase F: Multimodal OCR and chart understanding. |
| **Docs Update** | `README.md` | ⏳ Pending | Phase F: Update README with Phase B, C, D guides and runbooks. |
