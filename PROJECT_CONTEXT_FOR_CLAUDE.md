# PROJECT CONTEXT FOR CLAUDE: SOVEREIGN WORKBENCH

> **Target Audience:** AI Software Engineers / Autonomous Agents (specifically Claude) taking over this codebase.  
> **Document Purpose:** Complete, technically rigorous, zero-assumption specification and implementation breakdown of the **Sovereign Workbench** repository.  
> **Repository Path:** `/Users/vedikamohite/GodLike` (Main package in `sovereign-workbench/`)  
> **Current Git Branch:** `main` (commit `1968d00`, up to date with `origin/main`)  
> **Repository Version:** `0.1.0-phase-c` / `phase-d` in progress  
> **Analysis Date:** August 2026  

---

# TABLE OF CONTENTS
1. [Project Identity & Core Mission](#1-project-identity--core-mission)
2. [Project Requirements & Original Goals](#2-project-requirements--original-goals)
3. [Complete System Architecture](#3-complete-system-architecture)
4. [Repository Directory & File Index](#4-repository-directory--file-index)
5. [Technology Stack & Dependency Analysis](#5-technology-stack--dependency-analysis)
6. [AI & LLM Inference Architecture](#6-ai--llm-inference-architecture)
7. [Local RAG Pipeline & Vector Search](#7-local-rag-pipeline--vector-search)
8. [Tool System & Extensibility Registry](#8-tool-system--extensibility-registry)
9. [Code Execution Sandbox Architecture](#9-code-execution-sandbox-architecture)
10. [OCR & Multimodal Vision Pipeline](#10-ocr--multimodal-vision-pipeline)
11. [Office Document Generation Subsystem](#11-office-document-generation-subsystem)
12. [Tamper-Evident Audit Logging & Sovereignty Enforcement](#12-tamper-evident-audit-logging--sovereignty-enforcement)
13. [Hardware-Aware Tier Resolution & Dynamic Model Budgeting](#13-hardware-aware-tier-resolution--dynamic-model-budgeting)
14. [Complete Configuration & Environment Reference](#14-complete-configuration--environment-reference)
15. [Exhaustive API Endpoint Reference](#15-exhaustive-api-endpoint-reference)
16. [Verification, Benchmarking & Testing Suites](#16-verification-benchmarking--testing-suites)
17. [Current Implementation Status Matrix (Phase by Phase)](#17-current-implementation-status-matrix-phase-by-phase)
18. [Known Issues, Bugs, Inconsistencies & Edge Cases](#18-known-issues-bugs-inconsistencies--edge-cases)
19. [Git Branching, Commit History & Merge Analysis](#19-git-branching-commit-history--merge-analysis)
20. [Recent Development Evolution](#20-recent-development-evolution)
21. [Environment Setup & Installation Runbook](#21-environment-setup--installation-runbook)
22. [Step-by-Step Operator Runbook](#22-step-by-step-operator-runbook)
23. [End-to-End User & Agent Workflows](#23-end-to-end-user--agent-workflows)
24. [Security Threat Model & Boundary Analysis](#24-security-threat-model--boundary-analysis)
25. [Architectural Gaps & Technical Debt](#25-architectural-gaps--technical-debt)
26. [Prioritized Next Steps (P0 to P3 Roadmap)](#26-prioritized-next-steps-p0-to-p3-roadmap)
27. [CLAUDE HANDOFF (Executive Action Guide)](#27-claude-handoff-executive-action-guide)
28. [Important File Master Index](#28-important-file-master-index)

---

# 1. PROJECT IDENTITY & CORE MISSION

* **Project Name:** Sovereign Workbench
* **Repository Name:** `GodLike` / `sovereign-workbench`
* **Main Purpose:** A private, enterprise-grade, self-hosted AI workbench and autonomous agent system engineered for regulated and security-critical organizations (specifically demonstrated on refinery operations, safety standards, and confidential internal compliance like MRPL / OISD).
* **Problem Being Solved:** Public AI APIs (OpenAI, Anthropic, Google Cloud) violate data sovereignty, export confidential enterprise documents, and expose telemetry to external servers. Sovereign Workbench ensures that **all models, vector stores, sandboxes, tools, and data stay 100% on the local host machine**.
* **Target Users:** Plant safety engineers, compliance officers, refinery operators, industrial inspectors, and security administrators handling air-gapped or confidential industrial operations.
* **Intended Deployment Environment:** On-premises bare-metal Linux servers, air-gapped workstations, or GPU-equipped edge nodes (with CPU fallback capability on macOS/Apple Silicon).
* **Current Development Phase:** Transitioning from Phase C (RAG & Hardware Adaptation) through Phase D (Docker Sandbox, Multimodal Vision, and Office Document Generation). Core components of Phase A, B, C, and D are already implemented and merged into `main`.
* **Core Technical Guarantees:**
  1. **Zero External Network Calls:** Every inference call is strictly validated against a `localhost`-only allowlist (`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`). Any non-local destination raises an immediate `ValueError` and registers a `SOVEREIGNTY VIOLATION` in the audit log.
  2. **No Proprietary Cloud SDKs:** The application does not import `openai`, `anthropic`, `boto3`, or `azure-ai`. Inference and embeddings communicate directly via raw HTTP using `httpx.AsyncClient` with `trust_env=False` to prevent OS proxy interception.
  3. **Cryptographic Tamper-Evident Audit Trail:** Every model call, tool dispatch, document ingestion, code sandbox execution, and routing decision is appended to a JSONL log with SHA-256 hash chaining (`prev_hash` $\to$ `self_hash`) and kernel-level file locking (`fcntl.flock` + `os.fsync`).

---

# 2. PROJECT REQUIREMENTS / ORIGINAL GOALS

Based on the repository documentation, design specifications, and commit history, the system fulfills the following core functional and non-functional requirements:

### Functional Requirements
1. **Local LLM Inference:** Streaming (Server-Sent Events) and batch chat completions powered by local Ollama instances running open-weights models (`qwen2.5` family).
2. **Hardware-Aware Model Tiering:** Zero-dependency GPU detection (`nvidia-smi` parser) dynamically assigning models based on available VRAM with a mandatory 15% safety buffer.
3. **Intelligent Two-Stage Routing:** Heuristic routing (regex keywords, file extensions, explicit hints) with LLM-fallback classification when ambiguity exists.
4. **Autonomous Agent State Machine:** Multi-step Plan $\to$ Act $\to$ Observe $\to$ Iterate state machine with automatic retry and dynamic replanning on step failure (max 3 retries).
5. **Local RAG Pipeline:** Sliding-window text and PDF chunker, `bge-m3` embedding generation, local Qdrant vector database storage with status/category metadata filtering, and citation attribution (`doc_name` + `page_number`).
6. **Isolated Python Code Sandbox:** Execution of untrusted agent code in a hardened Docker container with `--network=none`, memory/CPU caps, read-only root filesystem, ephemeral `/tmp`, and strict timeouts.
7. **Multimodal Extraction & Vision OCR:** Structured JSON extraction from scanned PDFs and rasterized images using local vision models (`qwen2.5vl`).
8. **Office Deliverable Generation:** Programmatic creation of standard enterprise deliverables without external dependencies (`.docx` via `python-docx`, `.pptx` via `python-pptx`, `.xlsx` via `openpyxl`).

### Non-Functional & Security Requirements
* **Air-Gap Compatibility:** Must operate without active internet connection.
* **Deterministic Re-ingestion:** Deduplication through deterministic UUID generation based on SHA-256 digests of document content and chunk position.
* **Process Fault Tolerance:** Failures in individual tools or models must be trapped gracefully without crashing the FastAPI daemon or agent loop.

---

# 3. COMPLETE SYSTEM ARCHITECTURE

```
                               ┌──────────────────────────────────────────────────────────┐
                               │                    CLIENT INTERFACE                      │
                               │  (FastAPI REST Endpoints / SSE Chat / Standalone Sandbox) │
                               └────────────────────────────┬─────────────────────────────┘
                                                            │
                 ┌──────────────────────────────────────────┴─────────────────────────────────────────┐
                 │                                                                                    │
                 ▼                                                                                    ▼
   ┌───────────────────────────┐                                                        ┌───────────────────────────┐
   │    POST /sandbox/execute  │                                                        │       POST /chat          │
   │  (Standalone Fast-Path)   │                                                        │   (Agent / Inference)     │
   └─────────────┬─────────────┘                                                        └─────────────┬─────────────┘
                 │                                                                                    │
                 ▼                                                                                    ▼
   ┌───────────────────────────┐                                                        ┌───────────────────────────┐
   │      SandboxManager       │                                                        │     Capability Router     │
   │   (app/sandbox/manager)   │                                                        │   - Heuristic Classifier  │
   └─────────────┬─────────────┘                                                        │   - LLM Fallback (Qwen)   │
                 │                                                                      └─────────────┬─────────────┘
                 ▼                                                                                    │
   ┌───────────────────────────┐                                                                      ▼
   │       DockerRunner        │                                                        ┌───────────────────────────┐
   │   - --network=none        │                                                        │     Agent Orchestrator    │
   │   - --read-only / tmpfs   │                                                        │ (Plan→Act→Observe→Iterate)│
   │   - --memory=128m         │                                                        └─────────────┬─────────────┘
   │   - sovereign-sandbox-py  │                                                                      │
   └───────────────────────────┘                                                                      │
                                                ┌─────────────────────────────────────────────────────┼──────────────────────────────────┐
                                                │                                                     │                                  │
                                                ▼                                                     ▼                                  ▼
                                  ┌───────────────────────────┐                         ┌───────────────────────────┐      ┌───────────────────────────┐
                                  │       TOOL REGISTRY       │                         │       OLLAMA CLIENT       │      │       AUDIT LOGGER        │
                                  │ ───────────────────────── │                         │ ───────────────────────── │      │ ───────────────────────── │
                                  │ • file_read (Text/Cap)    │                         │ • qwen2.5:14b (Reasoning) │      │ • logs/audit.jsonl        │
                                  │ • rag_search (Qdrant)     │                         │ • qwen2.5-coder:14b (Code)│      │ • SHA-256 Hash Chain      │
                                  │ • code_sandbox (Docker)   │                         │ • qwen2.5vl:3b/7b (Vision)│      │ • fcntl File Locking      │
                                  │ • generate_docx (Word)    │                         │ • bge-m3 (Embeddings)     │      │ • Localhost Guardrail     │
                                  │ • generate_pptx (Slides)  │                         │ • trust_env=False         │      └───────────────────────────┘
                                  │ • generate_xlsx (Excel)   │                         └───────────────────────────┘
                                  │ • vision_extract (OCR)    │
                                  └─────────────┬─────────────┘
                                                │
                                                ▼
                                  ┌───────────────────────────┐
                                  │   LOCAL RAG KNOWLEDGE     │
                                  │ ───────────────────────── │
                                  │ • Qdrant (localhost:6333) │
                                  │ • MRPL Public Docs (PDF)  │
                                  │ • OISD Refinery Standards │
                                  │ • Cosine Dist (1024-dim)  │
                                  └───────────────────────────┘
```

---

# 4. REPOSITORY STRUCTURE

```text
GodLike/
├── .git/                                      ← Git repository metadata
├── .gitignore                                 ← Ignores .venv, __pycache__, logs, generated outputs
├── PROJECT_CONTEXT_FOR_CLAUDE.md              ← THIS COMPLETE CONTEXT DOCUMENT
└── sovereign-workbench/                       ← Primary project workspace root
    ├── README.md                              ← Original project overview & Phase A-C quickstart
    ├── PROJECT_STATUS.md                      ← Phase roadmap & component checklist
    ├── requirements.txt                       ← Pinned Python dependencies
    ├── eval_set.yaml                          ← Retrieval evaluation query benchmark set
    ├── smoke_test_phase_b.py                  ← Real-model end-to-end smoke test for Phase B
    ├── smoke_test_phase_c.py                  ← Real-data end-to-end smoke test for Phase C
    ├── verify_phases_abc.py                   ← Multi-stage live system verification script
    ├── verify_step4.py                        ← Orchestrator live run & JSON parser stress verification
    ├── verify_step5.py                        ← RAG ingestion, evaluation & citation verification
    ├── verify_step7.py                        ← Sequential 4-slot model load & latency probe
    ├── app/                                   ← Main backend application package
    │   ├── __init__.py
    │   ├── main.py                            ← FastAPI entrypoint, lifespan manager, & route handlers
    │   ├── audit/                             ← Cryptographic audit logging subsystem
    │   │   ├── __init__.py
    │   │   └── logger.py                      ← Hash-chained, append-only JSONL logger with flock/fsync
    │   ├── config/                            ← Configuration models & registry
    │   │   ├── __init__.py
    │   │   └── models.yaml                    ← Single source of truth for all models, tiers, tags, VRAM
    │   ├── hardware/                          ← Zero-dependency hardware discovery
    │   │   ├── __init__.py
    │   │   ├── gpu_detect.py                  ← Subprocess nvidia-smi CSV parser (returns zeroed dict on CPU)
    │   │   └── tier_resolver.py               ← VRAM budget allocator (15% headroom) & model tier mapper
    │   ├── models/                            ← Local inference clients
    │   │   ├── __init__.py
    │   │   └── ollama_client.py               ← Async HTTP client for Ollama (chat, SSE stream, embeddings)
    │   ├── orchestrator/                      ← Autonomous Agent State Machine
    │   │   ├── __init__.py
    │   │   ├── state.py                       ← Dataclasses (PlannedStep, StepOutcome, OrchestratorRun)
    │   │   └── orchestrator.py                ← Plan→Act→Observe→Iterate engine with 3-retry dynamic replan
    │   ├── rag/                               ← Knowledge base & vector retrieval pipeline
    │   │   ├── __init__.py
    │   │   ├── chunker.py                     ← Sliding-window text chunker & PyMuPDF page-aware chunker
    │   │   ├── embedder.py                    ← Batch embedding generator using local bge-m3 via Ollama
    │   │   ├── eval.py                        ← Evaluation engine executing queries from eval_set.yaml
    │   │   ├── ingest.py                      ← Folder-level batch ingestion pipeline (derives categories)
    │   │   ├── ingestor.py                    ← Single-file ingestion pipeline with SHA-256 document hashing
    │   │   └── store.py                       ← Local Qdrant client wrapper (filtered search, deterministic IDs)
    │   ├── router/                            ← Capability & model routing
    │   │   ├── __init__.py
    │   │   ├── heuristics.py                  ← Zero-latency regex/extension/hint rule classifier
    │   │   ├── llm_classifier.py              ← Low-temp prompt classifier for ambiguous inputs
    │   │   └── router.py                      ← Two-stage orchestration returning RoutingDecision
    │   ├── sandbox/                           ← Standalone decoupled sandbox API subsystem
    │   │   ├── __init__.py
    │   │   ├── docker_runner.py               ← Subprocess docker execution with strict isolation flags
    │   │   ├── manager.py                     ← Workspace lifecycle manager (tempfile creation & cleanup)
    │   │   ├── models.py                      ← Pydantic schemas (ExecuteRequest, ExecuteResponse)
    │   │   └── router.py                      ← FastAPI router for POST /sandbox/execute
    │   └── tools/                             ← Agent tool implementations & registry
    │       ├── __init__.py
    │       ├── base.py                        ← BaseTool abstract interface & ToolResult dataclass
    │       ├── registry.py                    ← Static & dynamic tool registry (TOOL_REGISTRY)
    │       ├── file_read.py                   ← Line-bounded, size-capped safe local file reader
    │       ├── rag_search.py                  ← Semantic search tool integrated with VectorStore & Embedder
    │       ├── code_sandbox.py                ← Orchestrator-integrated Docker Python execution tool
    │       ├── vision_extract.py              ← Multimodal structured JSON extraction tool (Pillow/pdf2image)
    │       └── docgen/                        ← Office deliverable generation tools
    │           ├── __init__.py
    │           ├── generate_docx.py           ← Formatted Microsoft Word document generator (python-docx)
    │           ├── generate_pptx.py           ← Formatted Microsoft PowerPoint slide deck generator (python-pptx)
    │           └── generate_xlsx.py           ← Formatted Microsoft Excel workbook generator (openpyxl)
    ├── knowledge_base/                        ← Knowledge base documents repository
    │   ├── mrpl_public/                       ← Public enterprise reports (Sustainability, RTI, Financials)
    │   │   ├── MRPL_Sustainability_report_FY_2023-24.pdf
    │   │   ├── MRPL_Sustainability_report_FY_2024-25.pdf
    │   │   ├── Organisation-chart212022.pdf
    │   │   ├── RTI-ActEnglish.pdf
    │   │   ├── annual_report.pdf
    │   │   └── environment_report.pdf
    │   ├── oisd_standards/                    ← Oil Industry Safety Directorate standards
    │   │   ├── OISD_Standards_Detailed_Explanation_Guide_SIH26117.pdf
    │   │   ├── OISD-STD-174.pdf               ← (untracked)
    │   │   ├── OISD-STD-175.pdf               ← (untracked)
    │   │   ├── OISD-STD-176.pdf               ← (untracked)
    │   │   ├── OISD-STD-181.pdf               ← (untracked)
    │   │   ├── OISD-STD-183.pdf               ← (untracked)
    │   │   └── OISD-STD-185.pdf               ← (untracked)
    │   └── synthetic_demo/                    ← Demonstration text documents
    │       ├── inspection_report.txt          ← Synthetic CDU unit 4 inspection findings
    │       └── sop_approval_note.txt          ← Standard operating procedure for approval notes
    ├── outputs/                               ← Generated artifacts directory
    │   └── generated/                         ← Output folder for docx, pptx, xlsx deliverables
    ├── logs/                                  ← Audit logs & run traces (ignored by git)
    ├── sandbox/                               ← Docker build assets
    │   └── python/
    │       └── Dockerfile                     ← Hardened non-root Python 3.11-slim sandbox image
    └── tests/                                 ← Pytest test suites
        ├── __init__.py
        ├── test_phase_a.py                    ← Phase A: Foundation, Ollama client, AuditLogger (8 tests)
        ├── test_phase_b.py                    ← Phase B: Router heuristics, Orchestrator loop (12 tests)
        ├── test_phase_c.py                    ← Phase C: Chunker, Embedder, Qdrant store, Ingest (24 tests)
        └── test_phase_d.py                    ← Phase D: VisionExtract, DocGen (Word/PPT/Excel), Sandbox (18 tests)
```

---

# 5. TECHNOLOGY STACK & DEPENDENCY ANALYSIS

### Core Runtime & Frameworks
* **Python Version:** Python 3.11 recommended (code is compatible with Python 3.11–3.13).
* **API Framework:** `FastAPI` (0.115.5) + `uvicorn[standard]` (0.32.1).
* **Data Validation & Schemas:** `pydantic` (2.10.3).
* **HTTP Client:** `httpx` (0.28.1) — pure async client with `trust_env=False`.
* **Config Parsing:** `pyyaml` (6.0.2).
* **Form / Multipart Parsing:** `python-multipart` (0.0.20).

### AI, Vector DB & Document Processing
* **Local Inference Engine:** `Ollama` (running on `http://localhost:11434`).
* **Vector Database:** `Qdrant` (running on `http://localhost:6333`, Python SDK `qdrant-client` 1.12.1).
* **PDF Parsing:** `PyMuPDF` (`fitz` 1.25.1).
* **PDF Rasterization & Image Processing:** `pdf2image` ($\ge$ 1.17.0) + `Pillow` ($\ge$ 10.0.0).
* **Office Document Generation:**
  * Word: `python-docx` (1.1.2)
  * PowerPoint: `python-pptx` (1.0.2)
  * Excel: `openpyxl` (3.1.5)

### Testing & Verification
* **Test Runners:** `pytest` (8.3.4), `pytest-asyncio` (0.24.0).
* **HTTP Mocking:** `respx` (0.21.1) for offline mock testing of Ollama API interactions.

---

# 6. AI & LLM INFERENCE ARCHITECTURE

### 1. Model Registry Specification (`app/config/models.yaml`)
`models.yaml` is the single source of truth for all models available to the system. No model may be called at runtime unless it is registered here.

| Model Identifier (`name`) | Modality | Ollama Tag | Context Window | Tier | Estimated VRAM | Capability Tags |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `qwen25_7b_instruct` | Text | `qwen2.5:7b-instruct-q4_K_M` | 32,768 | `small` | 4,500 MB | `chat`, `reasoning`, `summarization`, `document_qa`, `default_text` |
| `qwen25_14b_instruct` | Text | `qwen2.5:14b-instruct-q4_K_M` | 32,768 | `mid` | 9,000 MB | `chat`, `reasoning`, `summarization`, `document_qa`, `default_text` |
| `qwen25_32b_instruct` | Text | `qwen2.5:32b-instruct-q4_K_M` | 32,768 | `large` | 19,000 MB | `chat`, `reasoning`, `summarization`, `document_qa`, `complex_reasoning` |
| `qwen25_coder_7b` | Code | `qwen2.5-coder:14b` *(note 1)* | 32,768 | `small` | 9,000 MB | `code_generation`, `code_review`, `debugging`, `refactoring` |
| `qwen25_coder_14b` | Code | `qwen2.5-coder:14b` | 32,768 | `mid` | 9,000 MB | `code_generation`, `code_review`, `debugging`, `refactoring`, `complex_code` |
| `qwen25vl_3b` | Vision | `qwen2.5vl:3b` | 32,768 | `small` | 3,000 MB | `image_understanding`, `ocr`, `document_vision`, `vision_extraction`, `chart_analysis` |
| `qwen25vl_7b` | Vision | `qwen2.5vl:7b` | 32,768 | `mid` | 6,000 MB | `image_understanding`, `ocr`, `document_vision`, `vision_extraction`, `chart_analysis` |
| `bge_m3` | Embedding | `bge-m3` | 8,192 | `default`| 1,200 MB | `embedding`, `rag`, `semantic_search` |

*(Note 1: `qwen25_coder_7b` was configured with `qwen2.5-coder:14b` in `models.yaml` because the 14b model was pulled on the target machine).*

### 2. Client Implementation (`app/models/ollama_client.py`)
* Implements `chat_completion`, `chat_stream` (SSE generator), and `embeddings`.
* Enforces `trust_env=False` on `httpx.AsyncClient`.
* Validates endpoint URLs at module import time against localhost allowlist.
* Captures token usage (`prompt_tokens`, `completion_tokens`, `total_tokens`) and latency (`latency_ms`) and immediately logs them to `AuditLogger`.

### 3. Capability Classification & Two-Stage Routing Flow
```
User Prompt + Optional Attachments + Hints
                    │
                    ▼
   Stage 1: Heuristic Classifier (app/router/heuristics.py)
   ├── 1. Check explicit_capability_hint (confidence = 1.0)
   ├── 2. Check attached file extensions (.pdf/.png → Vision; .py/.sql → Code)
   └── 3. Check regex keyword patterns (tracebacks, errors, OCR, charts)
                    │
           Confidence ≥ 0.75 ?
          ┌─────────┴─────────┐
         YES                  NO (Ambiguous)
          │                   │
          ▼                   ▼
   Return Selected    Stage 2: LLM Classifier (app/router/llm_classifier.py)
   Model (Heuristic)  ├── Prompt small text model with capability labels
                      ├── Temperature: 0.0, Max tokens: 16
                      └── Parse output into Capability enum
                              │
                     Recognized Label ?
                    ┌─────────┴─────────┐
                   YES                  NO
                    │                   │
                    ▼                   ▼
             Return Selected     Default Text Fallback
             Model (LLM Stage)   (qwen25_14b_instruct)
```

### 4. Autonomous Agent Orchestrator (`app/orchestrator/orchestrator.py`)
* **Execution State Machine:** `IDLE` $\to$ `PLANNING` $\to$ `ACTING` $\to$ `OBSERVING` $\to$ (`REPLANNING`) $\to$ `COMPLETED` / `FAILED`.
* **Prompt Construction:** Provides the model with a JSON-formatted dump of all registered tools and their exact input schemas.
* **Tolerant JSON Parsing:** Handles model quirks:
  * Strips markdown fences (` ```json ... ``` `).
  * Strips JavaScript single-line `//` comments outside strings.
  * Normalizes both `{tool_name, tool_args}` and OpenAI `{name, arguments}` formats.
  * Filters out hallucinated/invented tool names early without wasting retries.
* **Dynamic Replanning:** If any step execution returns `ToolResult.success=False`, the orchestrator feeds the error message back into the model to generate a revised sub-plan. Retries are capped at `MAX_RETRIES = 3`.
* **Synthesis:** Once all steps succeed, accumulated context snippets (capped at 4,000 chars per step) are fed to the model to generate the final response.

---

# 7. LOCAL RAG PIPELINE & VECTOR SEARCH

### Ingestion Flow
1. **Document Loading:** Files from `knowledge_base/` are scanned. PDF files are processed using `pymupdf` (`fitz`), plain text and source code using stdlib reading.
2. **Page-by-Page Chunking:** `chunk_pdf_paged()` extracts text on a per-page basis with a default sliding window of 600 characters and 90 characters overlap (512/64 in general single-file ingestor).
3. **Provenance Metadata Tagging:** Every chunk is assigned:
   * `doc_name`: PDF filename (e.g. `environment_report.pdf`)
   * `source_category`: Parent folder name (`mrpl_public`, `oisd_standards`)
   * `page_number`: 1-indexed PDF page number
   * `chunk_index`: Sequence position
   * `status`: `in_force` (or `withdrawn`)
   * `confidentiality`: `public` (or `internal`, `confidential`)
   * `source`: Absolute filepath
4. **Deterministic Point IDs:** Point IDs in Qdrant are generated deterministically:
   $$\text{UUID} = \text{UUID}(\text{SHA-256}(\text{doc\_name} \parallel \text{page\_number} \parallel \text{chunk\_index})[:16])$$
   Re-running ingestion updates existing vectors in place without duplicating records.
5. **Local Embeddings:** Chunks are embedded sequentially via `bge-m3` on local Ollama, yielding 1024-dimensional vectors.
6. **Qdrant Upsert:** Stored in Qdrant (`localhost:6333`) under collection name (default `docs` or caller-specified).

### Retrieval & Filtered Search (`app/rag/store.py` & `app/tools/rag_search.py`)
* **Vector Distance Metric:** Cosine similarity.
* **Mandatory Filtering (`search_filtered`):**
  * `exclude_status`: Automatically excludes chunks with `status="withdrawn"`.
  * `source_category`: Scopes queries to specific folders (e.g., searching only `oisd_standards` or `mrpl_public`).
* **Source Attribution & Citation:** Results return formatted markdown citations:
  `**[1] score=0.875** | environment_report.pdf (page 12) | mrpl_public`
* **Retrieval Audit:** Every query execution generates a `RAG_RETRIEVAL` audit event containing the query, collection name, hits, and all returned document names with page numbers.

---

# 8. TOOL SYSTEM & EXTENSIBILITY REGISTRY

All agent tools inherit from `BaseTool` (`app/tools/base.py`) and return a `ToolResult`. Tools are guaranteed **never to throw unhandled exceptions** during `execute()`.

```python
@dataclass
class ToolResult:
    success: bool
    output: Any
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Complete Tool Inventory

| Tool Name | Class & Module | Purpose | Key Inputs | Key Outputs | Registered In |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `file_read` | `FileReadTool`<br>`app/tools/file_read.py` | Line-bounded text file reading with null-byte binary sniffing (8KB check) and 512KB size cap. | `path`: str<br>`encoding`: str (default "utf-8") | String content with truncation notices. | `TOOL_REGISTRY` (Static) |
| `rag_search` | `RagSearchTool`<br>`app/tools/rag_search.py` | Local semantic knowledge search with status/category filtering and citation tracking. | `query`: str<br>`collection`: str<br>`top_k`: int<br>`source_category`: str | Ranked markdown string + `sources` citation metadata. | `register_tool()` at Startup |
| `code_sandbox` | `CodeSandboxTool`<br>`app/tools/code_sandbox.py` | Execution of Python scripts in Docker with `--network=none`, 256MB RAM, 120s timeout. | `code`: str<br>`language`: "python"<br>`request_id`: str | `exit_code`, `stdout`, `stderr`, `timed_out`, `code_hash`. | `TOOL_REGISTRY` (Static) |
| `generate_docx` | `GenerateDocxTool`<br>`app/tools/docgen/generate_docx.py` | Generates formatted Microsoft Word files with headings, tables, recommendations. | `title`: str<br>`sections`: list[dict]<br>`findings_table`: list[dict]<br>`output_filename`: str | Absolute filepath in `outputs/generated/`. | `TOOL_REGISTRY` (Static) |
| `generate_pptx` | `GeneratePptxTool`<br>`app/tools/docgen/generate_pptx.py` | Generates Microsoft PowerPoint presentation decks with title and content slides. | `title`: str<br>`slides`: list[dict]<br>`output_filename`: str | Absolute filepath in `outputs/generated/`. | `TOOL_REGISTRY` (Static) |
| `generate_xlsx` | `GenerateXlsxTool`<br>`app/tools/docgen/generate_xlsx.py` | Generates Microsoft Excel workbooks with formatted headers, data rows, and formula rows. | `headers`: list[str]<br>`rows`: list[list]<br>`formula_row`: list[str]<br>`output_filename`: str | Absolute filepath in `outputs/generated/`. | `TOOL_REGISTRY` (Static) |
| `vision_extract`| `VisionExtractTool`<br>`app/tools/vision_extract.py` | Multimodal structured JSON extraction from images and PDFs using `qwen2.5vl`. | `file_path`: str<br>`request_id`: str | List of page dicts with `fields`, `tables`, `annotations`. | `register_tool()` at Startup |

---

# 9. CODE EXECUTION SANDBOX ARCHITECTURE

The repository contains **two complementary sandbox implementations**:
1. **Standalone Sandbox Service (`app/sandbox/`):** A lightweight FastAPI endpoint (`POST /sandbox/execute`) designed for high-performance direct execution, completely isolated from LLM and agent orchestration.
2. **Orchestrator Sandbox Tool (`app/tools/code_sandbox.py`):** An agent-callable tool integrated into the Plan-Act-Observe loop, with audit trail logging.

### Security Isolation Comparison

| Isolation Property | Standalone Sandbox (`app/sandbox/`) | Orchestrator Tool (`app/tools/code_sandbox.py`) |
| :--- | :--- | :--- |
| **Docker Base Image** | `sovereign-sandbox-python` (`sandbox/python/Dockerfile`) | `python:3.11-slim` |
| **User Privileges** | Non-root `sandboxuser` (`uid=1000`, `gid=1000`, no home) | Default container user (root inside container namespace) |
| **Network Egress** | `--network=none` (Zero network access) | `--network=none` (Zero network access) |
| **Memory Limit** | `--memory=128m --memory-swap=128m` | `--memory=256m` |
| **CPU Quota** | `--cpus=0.5` | `--cpus=0.5` |
| **Process / Fork Limit** | `--pids-limit=64` (Fork-bomb protection) | Not explicitly set (relies on container default) |
| **Filesystem State** | `--read-only` root + `--tmpfs /tmp:size=32m` | `--read-only` root + `--tmpfs /tmp:size=64m` |
| **Code Mount** | `-v workspace:/sandbox:ro` (read-only) | `-v tmp_script:/sandbox/script.py:ro` (read-only) |
| **Privilege Escalation**| `--security-opt no-new-privileges` | Not explicitly set |
| **Execution Timeout** | 10s default (configurable 1–30s) | 120s wall-clock timeout |
| **Cleanup Guarantee** | Temporary directory removed in `finally` block | `finally: docker rm -f` + temp file deletion |
| **Audit Logging** | Intentionally omitted for standalone isolation | Writes `SANDBOX_EXEC` event (code SHA-256, duration) |

---

# 10. OCR & MULTIMODAL VISION PIPELINE

* **Module:** `app/tools/vision_extract.py`
* **Supported File Types:** `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.bmp`, `.webp`, and `.pdf`.
* **Rasterization Engine:** `pdf2image` rasterizes PDF pages into PIL `Image` objects.
* **Inference Pipeline:**
  1. Each page image is base64 encoded as PNG.
  2. Image is passed to `qwen2.5vl` (either 3b or 7b) via `OllamaClient.chat_completion`.
  3. System prompt forces strict JSON output adhering to schema:
     ```json
     {
       "page": 1,
       "fields": [{"name": "...", "value": "...", "region": "..."}],
       "tables": [{"title": "...", "headers": ["..."], "rows": [["..."]]}],
       "annotations": [{"text": "...", "region": "..."}]
     }
     ```
  4. Non-JSON responses are rejected and retried up to `_MAX_RETRIES = 2`.
* **Audit Trail:** Logs a `VISION_EXTRACT` event recording `file_path`, `page_count`, total `field_count`, and total `table_count` (full text is omitted to avoid log bloat).

---

# 11. OFFICE DOCUMENT GENERATION SUBSYSTEM

All document generators write outputs to `outputs/generated/` and record `DOCGEN` audit events.

1. **Microsoft Word (`app/tools/docgen/generate_docx.py`):**
   * Library: `python-docx`.
   * Features: Formatted Heading 1 title, structured sections with subheadings, styled findings table (`ID`, `Finding`, `Severity`, `Status`), bulleted recommendation lists.
2. **Microsoft PowerPoint (`app/tools/docgen/generate_pptx.py`):**
   * Library: `python-pptx`.
   * Features: Title slide layout (with "Generated by Sovereign Workbench" subtitle), content slide layouts with headings and formatted bullet paragraphs.
3. **Microsoft Excel (`app/tools/docgen/generate_xlsx.py`):**
   * Library: `openpyxl`.
   * Features: Worksheet naming, bold header styling, 2D row data insertion, formula row evaluation support (e.g. `=SUM(B2:B10)`), and dynamic column width auto-sizing.

---

# 12. TAMPER-EVIDENT AUDIT LOGGING & SECURITY

* **Module:** `app/audit/logger.py`
* **Format:** Append-only JSON Lines (`logs/audit.jsonl`).
* **Cryptographic Hash Chaining:**
  * Every record calculates a canonical SHA-256 hash `self_hash` across its fields (with `self_hash=""` during computation).
  * Each record embeds the `prev_hash` of the preceding record. The genesis record uses `prev_hash: "GENESIS"`.
  * Hash chain integrity is verified via `AuditLogger.verify_chain()`.
* **Concurrency & Durability:**
  * Uses `fcntl.flock(fh, fcntl.LOCK_EX)` on POSIX platforms to ensure atomic writes across concurrent async tasks and processes (with threading fallback shim on Windows).
  * Executes `os.fsync(fh.fileno())` to guarantee physical disk flush before returning.
* **Sovereignty Assertion:**
  * Validates every logged model call endpoint against `_is_local_endpoint()`.
  * If a non-local endpoint is detected, writes a sovereignty violation record and raises a hard `ValueError`.

### Event Types (`EventType` Enum)
* `model_call`: LLM completions, prompt/response tokens, latency.
* `tool_call`: Tool dispatch and observation results.
* `route_decision`: Stage 1 / Stage 2 capability routing decisions.
* `file_write`: Output artifact file creation.
* `agent_action`: Orchestrator state transitions (`run_started`, `plan_produced`, `retry_triggered`).
* `startup`: Logger initialization and `model_resolution` hardware selection.
* `error`: Caught exceptions, connection errors, and timeouts.
* `rag_ingest`: Document ingestion metrics, chunks count, SHA-256 fingerprint.
* `rag_retrieval`: Retrieval query, top-k hits, and source document/page citations.
* `vision_extract`: Multimodal extraction counts.
* `docgen`: Word, PowerPoint, and Excel generation events.
* `sandbox_exec`: Python code execution hash, exit code, duration.

---

# 13. HARDWARE-AWARE TIER RESOLUTION

* **Modules:** `app/hardware/gpu_detect.py` & `app/hardware/tier_resolver.py`
* **GPU Detection Mechanism:** Subprocess execution of `nvidia-smi --query-gpu=memory.total,memory.free,name --format=csv,noheader,nounits`.
  * If `nvidia-smi` is missing or fails (e.g., macOS / Apple Silicon / CPU servers), it returns `gpu_available: False`, `total_vram_mb: 0`, `free_vram_mb: 0`.
* **Budgeting Algorithm:**
  $$\text{Budget}_{\text{VRAM}} = \text{Free VRAM} \times 0.85 \quad (15\%\text{ safety headroom})$$
* **Resolution Logic:**
  1. Models in `models.yaml` are grouped by modality (`text`, `code`, `vision`, `embedding`) and sorted descending by `est_vram_mb`.
  2. For each modality, selects the largest model whose `est_vram_mb` $\le$ remaining budget.
  3. If budget is 0 or no model fits, falls back to the smallest tier model (`small`).
* **Environment Override:** Setting `FORCE_TIER=small` (or `mid`, `large`, `default`) bypasses GPU detection entirely and forces that tier across all modalities.

---

# 14. COMPLETE CONFIGURATION REFERENCE

| Configuration Key / Variable | Source | Default Value | Description |
| :--- | :--- | :--- | :--- |
| `DEFAULT_MODEL` | Environment Variable | `qwen25_14b_instruct` | Fallback text model used if tier resolver is bypassed |
| `AUDIT_LOG_PATH` | Environment Variable | `logs/audit.jsonl` | Filepath for append-only cryptographic audit trail |
| `FORCE_TIER` | Environment Variable | `None` (auto-detect) | Forced model size tier (`small`, `mid`, `large`, `default`) |
| Ollama Base URL | `models.yaml` | `http://localhost:11434`| Local Ollama inference server base endpoint |
| Qdrant Host / Port | `app/rag/store.py` | `localhost:6333` | Local Qdrant vector database endpoint |
| Sandbox Image | `app/sandbox/docker_runner.py` | `sovereign-sandbox-python` | Dedicated hardened Docker sandbox image |
| Standalone Sandbox Memory | `app/sandbox/docker_runner.py` | `128m` | Hard memory limit for standalone sandbox |
| Tool Sandbox Memory | `app/tools/code_sandbox.py` | `256m` | Memory limit for agent code sandbox tool |
| Max Tool Retries | `app/orchestrator/orchestrator.py` | `3` | Maximum retry attempts per plan step |
| File Read Cap | `app/tools/file_read.py` | `524,288` (512 KB) | Maximum bytes read by `file_read` tool |
| Embedding Vector Dimensions | `app/rag/store.py` | `1024` | Output dimension for `bge-m3` vectors |

---

# 15. EXHAUSTIVE API ENDPOINT REFERENCE

| Method | Path | Purpose | Input Payload | Output Payload | Source File | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/health` | Liveness & subsystem status probe | None | `{"status": "ok", "phase": "C", "rag": "ready"}` | `app/main.py` | Active |
| `GET` | `/models` | List all models in registry | None | `{"models": [...]}` | `app/main.py` | Active |
| `GET` | `/tools` | List all registered tools & schemas | None | `{"tools": [...]}` | `app/main.py` | Active |
| `POST` | `/chat` | Standard / SSE streaming chat completion | `ChatRequest` (messages, model, stream, temp) | `ChatResponse` or SSE stream (`data: {"delta": ...}`) | `app/main.py` | Active |
| `POST` | `/ingest` | Ingest document into Qdrant collection | `IngestRequest` (source_path, collection) | `IngestResponse` (chunks_ingested, sha256, duration) | `app/main.py` | Active |
| `POST` | `/rag/search` | Standalone semantic search query | `RagSearchRequest` (query, collection, top_k) | `RagSearchResponse` (results with scores and sources) | `app/main.py` | Active |
| `POST` | `/sandbox/execute` | Execute Python code in isolated Docker | `ExecuteRequest` (code, timeout) | `ExecuteResponse` (success, stdout, stderr, exit_code) | `app/sandbox/router.py` | Active |

---

# 16. TESTING & VERIFICATION SUITES

### Pytest Unit Test Suites
1. `tests/test_phase_a.py` (8 tests): Validates health check, chat completion, audit logging, localhost enforcement, sovereignty violation rejections, and hash-chain integrity using `respx` mocks.
2. `tests/test_phase_b.py` (12 tests): Validates heuristic router (tracebacks, PDFs, images), LLM fallback router, `FileReadTool` safety limits, orchestrator happy path, retry handling, failure halting, and audit tracking.
3. `tests/test_phase_c.py` (24 tests): Validates text chunker, GPU detection parsing, tier resolution, batch embedder, Qdrant store upsert/search, single-file ingestor, `RagSearchTool`, metadata fields, zero-text PDF skipping, deterministic ID updates, and withdrawn chunk exclusion.
4. `tests/test_phase_d.py` (18 tests): Validates `VisionExtractTool` JSON parsing and retry limits, `GenerateDocxTool`, `GeneratePptxTool`, `GenerateXlsxTool`, orchestrator plan tool dispatches, and Docker `CodeSandboxTool` execution/timeouts.

### System Verification & Live Smoke Scripts
* `verify_phases_abc.py`: End-to-end multi-step verification checking GPU hardware detection, live model probes across 4 slots, orchestrator live run, RAG batch ingestion, evaluation queries, and hash-chain verification.
* `verify_step4.py`: Probes live orchestrator execution on a real document with live LLM planning, acting (`file_read`), and synthesis.
* `verify_step5.py`: Executes full RAG ingestion on `knowledge_base/`, runs `eval_set.yaml` retrieval benchmark, and verifies citation output.
* `verify_step7.py`: Probes sequential load across all 4 model slots back-to-back, reporting latency and memory pressure.
* `smoke_test_phase_b.py` & `smoke_test_phase_c.py`: Live integration scripts validating real Ollama models and in-memory Qdrant.

---

# 17. CURRENT IMPLEMENTATION STATUS MATRIX

| Phase / Feature Area | Target Component | Implemented | Tested Offline | Tested Live | Status |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Phase A: Foundation** | Model Registry (`models.yaml`) | Yes | Yes | Yes | **COMPLETE** |
| | Ollama Async Client (`ollama_client.py`) | Yes | Yes | Yes | **COMPLETE** |
| | FastAPI Engine & `/chat` (`main.py`) | Yes | Yes | Yes | **COMPLETE** |
| | Hash-Chained Audit Logger (`logger.py`)| Yes | Yes | Yes | **COMPLETE** |
| **Phase B: Agent & Routing** | Heuristic & LLM Router (`router/`) | Yes | Yes | Yes | **COMPLETE** |
| | Orchestrator Loop (`orchestrator/`) | Yes | Yes | Yes | **COMPLETE** |
| | Tool Base & Registry (`tools/`) | Yes | Yes | Yes | **COMPLETE** |
| | Safe File Reader (`file_read.py`) | Yes | Yes | Yes | **COMPLETE** |
| **Phase C: Local RAG** | GPU & Tier Resolver (`hardware/`) | Yes | Yes | Yes | **COMPLETE** |
| | Text & PDF Chunker (`chunker.py`) | Yes | Yes | Yes | **COMPLETE** |
| | Batch Embedder (`embedder.py`) | Yes | Yes | Yes | **COMPLETE** |
| | Qdrant Vector Store (`store.py`) | Yes | Yes | Yes | **COMPLETE** |
| | Knowledge Ingestor (`ingest.py`) | Yes | Yes | Yes | **COMPLETE** |
| | Semantic Search Tool (`rag_search.py`) | Yes | Yes | Yes | **COMPLETE** |
| **Phase D: Tools & Sandbox**| Standalone Sandbox API (`app/sandbox/`) | Yes | Yes | Untested Live | **COMPLETE** |
| | Sandbox Agent Tool (`code_sandbox.py`) | Yes | Yes | Untested Live | **COMPLETE** |
| | Word Gen (`generate_docx.py`) | Yes | Yes | Yes | **COMPLETE** |
| | Slide Gen (`generate_pptx.py`) | Yes | Yes | Yes | **COMPLETE** |
| | Spreadsheet Gen (`generate_xlsx.py`) | Yes | Yes | Yes | **COMPLETE** |
| | Vision OCR Tool (`vision_extract.py`) | Yes | Yes | Untested Live | **COMPLETE** |
| **Phase E: Hardened Air-Gap**| Host `nftables` Firewall Scripts | No | No | No | **PLANNED** |
| | Asymmetric Digital Audit Seals | No | No | No | **PLANNED** |
| | Compliance Reporting CLI | No | No | No | **PLANNED** |
| **Phase F: Web UI & Ops** | Self-Hosted React/Web Interface | No | No | No | **PLANNED** |
| | Visual Agent Execution Trace UI | No | No | No | **PLANNED** |
| | Knowledge Base Management UI | No | No | No | **PLANNED** |

---

# 18. KNOWN ISSUES, BUGS & ARCHITECTURAL GAPS

1. **Dual Code Sandbox Implementations:**
   * `app/sandbox/` provides a standalone API (`POST /sandbox/execute`) using image `sovereign-sandbox-python`.
   * `app/tools/code_sandbox.py` provides an orchestrator tool using image `python:3.11-slim`.
   * *Impact:* Redundant code and different security boundaries.
   * *Direction:* Unify the orchestrator `CodeSandboxTool` to internally call `SandboxManager` so both use the hardened `sovereign-sandbox-python` Docker image and identical resource constraints.
2. **`PROJECT_STATUS.md` Drift:**
   * `PROJECT_STATUS.md` was authored during Phase C and marks Phase D as "0% PENDING", but Phase D tools (`code_sandbox.py`, `generate_docx.py`, `generate_pptx.py`, `generate_xlsx.py`, `vision_extract.py`) and `tests/test_phase_d.py` are already implemented and merged in commit `1968d00`.
3. **Dynamic Tool Startup Registration:**
   * In `app/main.py`, `RagSearchTool` is registered during lifespan startup. However, `VisionExtractTool` is not yet instantiated or registered in `app/main.py` lifespan because it requires the vision model client.
4. **`models.yaml` Tag Mismatch on Code Model:**
   * `qwen25_coder_7b` in `models.yaml` points to `ollama_tag: "qwen2.5-coder:14b"` because 14b was pulled on the workstation. If a smaller 7b footprint is needed, `qwen2.5-coder:7b` must be pulled and `models.yaml` updated.
5. **Untracked Knowledge Base PDFs:**
   * Six OISD standard PDFs (`OISD-STD-174.pdf`, `175`, `176`, `181`, `183`, `185`) in `knowledge_base/oisd_standards/` are untracked by Git.

---

# 19. GIT HISTORY & BRANCH ANALYSIS

### Branch Topology & Head Status
* **Current Branch:** `main` (commit `1968d00`)
* **Remote Tracking:** `origin/main` (in sync, zero unpushed commits)
* **Feature Branches:** `sandboxModel` (merged into `main` via PR #1 / `130d2e5`)
* **Working Tree State:** Clean (only untracked OISD PDF files in `knowledge_base/oisd_standards/`)

### Recent Commit Sequence
```text
*   1968d00 (HEAD -> main, origin/main, origin/HEAD) concluded merge
|\  
| *   130d2e5 Merge pull request #1 from OnkarNanaware/sandboxModel
| |\  
* | \   5b689e1 remerge
|\ \ \  
| |/ /  
|/| /   
| |/    
| *   12d2e7b (origin/sandboxModel, sandboxModel) Merge remote-tracking branch 'origin/main' into sandboxModel
| |\  
| * | 2624403 feat: implement standalone Python execution sandbox and update project status
* | | 7ae384d OCR,document generation and sandbox
| |/  
|/|   
* | c12a410  update model config to 14b and add verification scripts for orchestrator and RAG workflows
* | 9051c18 feat: implement RAG pipeline with local vector search, document ingestion, and hardware-aware model tier resolution
|/  
* 30bdc46  implement RAG pipeline with local vector search, document ingestion, and hardware-aware model tier resolution
* 3b0879e phase C upadted
* b426afa feat: implement heuristic-based router with LLM fallback capability classification
* f81d2fe feat: initialize project structure and implement phase A smoke tests with audit logging
* d9a55a0 feat: implement hash-chained audit logger and initialize project configuration models
```

---

# 20. RECENT DEVELOPMENT EVOLUTION

1. **Phase A (Initial Commits `d9a55a0`, `f81d2fe`):**
   * Built core `AuditLogger` with SHA-256 hash chaining, `models.yaml`, `OllamaClient`, and initial FastAPI `/chat`.
2. **Phase B (Commit `b426afa`):**
   * Implemented heuristic router + LLM fallback and autonomous `Orchestrator` state machine with `FileReadTool`.
3. **Phase C (Commits `3b0879e`, `30bdc46`, `9051c18`):**
   * Implemented hardware detection (`gpu_detect.py`), VRAM tier resolver (`tier_resolver.py`), Qdrant vector store (`store.py`), sliding-window chunker (`chunker.py`), batch embedder (`embedder.py`), folder ingestor (`ingest.py`), and evaluation benchmark (`eval.py`).
4. **Phase D & Sandbox Branch Merge (Commits `c12a410`, `2624403`, `7ae384d`, `1968d00`):**
   * Siddhesh-45 implemented standalone Docker sandbox in branch `sandboxModel` (`app/sandbox/`, `sandbox/python/Dockerfile`).
   * Onkar implemented `app/tools/code_sandbox.py`, `app/tools/docgen/` (Word, PPT, Excel), `app/tools/vision_extract.py`, and `tests/test_phase_d.py`.
   * Both feature sets were merged into `main`.

---

# 21. DEPENDENCIES & ENVIRONMENT SETUP

### Prerequisites
* **Operating System:** Linux (Ubuntu 22.04+ / RHEL 9+) or macOS (Apple Silicon / Intel).
* **Python:** Python 3.11 recommended.
* **Docker:** Docker Engine / Docker Desktop installed and running on PATH.
* **Ollama:** Ollama installed and running (`ollama serve`).

### Required Local AI Models
```bash
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama pull qwen2.5-coder:14b
ollama pull qwen2.5vl:3b
ollama pull bge-m3
```

### Python Virtual Environment Setup
```bash
cd sovereign-workbench
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Docker Sandbox Image Build
```bash
docker build -t sovereign-sandbox-python -f sandbox/python/Dockerfile .
```

---

# 22. STEP-BY-STEP OPERATOR RUNBOOK

### Step 1: Start Supporting Local Daemons
```bash
# Terminal 1: Start Ollama
ollama serve

# Terminal 2: Start Qdrant Vector Database (if using persistent server)
docker run -p 6333:6333 -v $(pwd)/qdrant_storage:/qdrant/storage:z qdrant/qdrant
```

### Step 2: Start the Sovereign Workbench API
```bash
cd sovereign-workbench
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Step 3: Ingest Knowledge Base Documents
```bash
curl -s -X POST http://127.0.0.1:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source_path": "knowledge_base/mrpl_public/environment_report.pdf",
    "collection": "docs"
  }' | jq .
```

### Step 4: Execute a Test Chat Query
```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is the primary function of CDU Unit 4?"}],
    "stream": false
  }' | jq .
```

### Step 5: Verify Cryptographic Audit Log
```bash
python3 -c "
from app.audit.logger import AuditLogger
audit = AuditLogger()
ok, errors = audit.verify_chain()
print('Audit Chain Verified:', ok)
if not ok:
    print('Errors:', errors)
"
```

---

# 23. END-TO-END USER & AGENT WORKFLOWS

### Workflow 1: Direct Sovereign Inference
`User Request` $\to$ `FastAPI POST /chat` $\to$ `Tier Resolver (Hardware Check)` $\to$ `OllamaClient (localhost:11434)` $\to$ `Audit Logger (MODEL_CALL)` $\to$ `Response (SSE/Batch)`.

### Workflow 2: Autonomous Knowledge Retrieval & Report Generation
```text
User Goal: "Analyze CDU Unit 4 inspection findings and generate an executive Word report."
   │
   ▼
Orchestrator Planning Step (qwen2.5:14b)
   │
   ├── Step 1 [file_read]: Read 'knowledge_base/synthetic_demo/inspection_report.txt'
   │       └── Output: High severity finding F-001 (HX-401 temperature anomaly at 312°C)
   │
   ├── Step 2 [rag_search]: Query 'OISD 118 approval requirements for heat exchanger anomalies'
   │       └── Output: OISD-118 Cl. 4.3 mandatory Chief Inspector approval note before restart
   │
   ├── Step 3 [generate_docx]: Create 'MRPL_U4_CDU_Approval_Note.docx'
   │       └── Output: Saved to outputs/generated/MRPL_U4_CDU_Approval_Note.docx
   │
   ▼
Synthesis Step: Compiles final executive summary with exact document and clause citations.
```

---

# 24. SECURITY THREAT MODEL & TRUST BOUNDARIES

1. **Untrusted Code Execution:**
   * *Threat:* LLM generated Python scripts attempting filesystem modification, host discovery, or outbound C2 network calls.
   * *Mitigation:* Hardened Docker container (`--network=none`, `--read-only`, non-root user, memory/CPU caps, ephemeral `/tmp`).
2. **Network Data Leakage / Telemetry:**
   * *Threat:* Third-party SDKs silently communicating with external SaaS endpoints or adhering to host `HTTPS_PROXY`.
   * *Mitigation:* No cloud SDKs imported; `httpx.AsyncClient(trust_env=False)`; `AuditLogger` rejects and logs non-local endpoints.
3. **Audit Log Tampering:**
   * *Threat:* Host process modifying prior audit events to hide unauthorized operations.
   * *Mitigation:* SHA-256 hash chaining where altering any prior line invalidates all subsequent `self_hash` links.

---

# 25. ARCHITECTURAL GAPS & TECHNICAL DEBT

1. **Tool Registration Unification:**
   * `VisionExtractTool` is implemented but needs dynamic instantiation in `app/main.py` lifespan so it is exposed to the `/tools` endpoint and orchestrator.
2. **Sandbox Deduplication:**
   * Consolidate `app/tools/code_sandbox.py` to use `app.sandbox.manager.SandboxManager` so both use the non-root `sovereign-sandbox-python` Docker container.
3. **Qdrant Lifecycle:**
   * While unit tests and smoke tests use `:memory:` Qdrant, production mode requires an active Qdrant daemon on `localhost:6333`. An automated health-check probe in `lifespan` handles this cleanly.

---

# 26. NEXT STEPS (ROADMAP)

### P0 — Critical Fixes & Integration
* Register `VisionExtractTool` in `app/main.py` lifespan using the resolved vision model client.
* Unify `app/tools/code_sandbox.py` with `app/sandbox/manager.py`.
* Ensure `sovereign-sandbox-python` Docker image build script is part of initial setup automation.

### P1 — Deliverables & Workflow Enhancements (Phase D Completion)
* Create an end-to-end multi-tool test in `tests/test_phase_d.py` executing: `file_read` $\to$ `rag_search` $\to$ `code_sandbox` $\to$ `generate_docx`.
* Add OCR ingestion fallback in `app/rag/ingest.py` for PDFs with 0 extractable characters using `VisionExtractTool`.

### P2 — Hardened Sovereignty & Compliance (Phase E)
* Implement host-level `nftables` script blocking all non-loopback egress.
* Implement cryptographic signing of audit batches (Ed25519 key pair).
* Add standalone audit log verification CLI (`app/audit/cli.py`).

### P3 — Enterprise Web Interface (Phase F)
* Develop lightweight self-hosted Web UI with real-time SSE streaming, visual agent step explorer, and knowledge base document manager.

---

# 27. CLAUDE HANDOFF (EXECUTIVE ACTION GUIDE)

```text
========================================================================================
                               CLAUDE HANDOFF SUMMARY
========================================================================================
1. WHAT WE ARE BUILDING:
   A strictly local, air-gapped, private AI workbench for high-compliance enterprise
   operations (MRPL refinery, OISD standards). Zero external network calls at runtime.

2. CURRENT ARCHITECTURE:
   - FastAPI backend (app/main.py)
   - Model Registry (app/config/models.yaml)
   - Local Ollama Client (app/models/ollama_client.py)
   - Capability Router: Heuristics + LLM Fallback (app/router/)
   - Orchestrator: Plan→Act→Observe→Iterate with 3 retries (app/orchestrator/)
   - RAG: Qdrant vector store + bge-m3 + PyMuPDF (app/rag/)
   - Sandbox: Docker --network=none isolated Python runner (app/sandbox/ & app/tools/)
   - DocGen: python-docx, python-pptx, openpyxl (app/tools/docgen/)
   - Vision: qwen2.5vl structured JSON extraction (app/tools/vision_extract.py)
   - Audit: Hash-chained JSONL with flock/fsync (app/audit/logger.py)

3. GIT STATUS:
   - Branch: main (commit 1968d00, synchronized with origin/main)
   - Feature branch 'sandboxModel' has already been merged into main.

4. CRITICAL RULES CLAUDE MUST NEVER BREAK:
   - NEVER import openai, anthropic, or cloud SDKs.
   - NEVER point endpoints to any host other than localhost / 127.0.0.1.
   - NEVER remove trust_env=False from httpx clients.
   - NEVER remove hash chaining or fcntl locking from AuditLogger.
   - DO NOT modify git history without explicit operator request.

5. IMMEDIATE HIGH-PRIORITY TASKS:
   - Wire VisionExtractTool into app/main.py lifespan.
   - Unify CodeSandboxTool with SandboxManager.
   - Expand test_phase_d.py to include an end-to-end multi-tool orchestration pipeline.
========================================================================================
```

---

# 28. IMPORTANT FILE MASTER INDEX

| File Path | Component | Importance | Rationale & Responsibility |
| :--- | :--- | :---: | :--- |
| `sovereign-workbench/app/main.py` | API Entrypoint | **CRITICAL** | Lifespan manager, initializes singletons, routes `/chat`, `/ingest`, `/rag/search`, `/health`, `/tools`. |
| `sovereign-workbench/app/config/models.yaml` | Model Registry | **CRITICAL** | Single source of truth for all models, tags, endpoints, context sizes, and VRAM estimates. |
| `sovereign-workbench/app/models/ollama_client.py` | Inference Engine | **CRITICAL** | Low-level async client for Ollama, enforces `trust_env=False` and localhost-only assertions. |
| `sovereign-workbench/app/audit/logger.py` | Audit System | **CRITICAL** | Implements tamper-evident SHA-256 hash chaining, `fcntl` file locking, and `os.fsync`. |
| `sovereign-workbench/app/orchestrator/orchestrator.py` | Agent Loop | **CRITICAL** | Plan $\to$ Act $\to$ Observe $\to$ Iterate state machine with 3-retry dynamic replanning. |
| `sovereign-workbench/app/router/router.py` | Router Engine | **HIGH** | Two-stage heuristic and LLM capability router. |
| `sovereign-workbench/app/hardware/tier_resolver.py`| VRAM Allocator | **HIGH** | Calculates free VRAM budget with 15% headroom and selects model tiers. |
| `sovereign-workbench/app/rag/store.py` | Vector Store | **HIGH** | Qdrant client wrapper with deterministic point IDs and category/status filtering. |
| `sovereign-workbench/app/rag/ingest.py` | Batch Ingestor | **HIGH** | Folder-level ingestion pipeline deriving metadata from `knowledge_base/` directories. |
| `sovereign-workbench/app/tools/registry.py` | Tool Registry | **HIGH** | Central catalog of all static and dynamic agent tools. |
| `sovereign-workbench/app/tools/code_sandbox.py` | Agent Sandbox | **HIGH** | Docker-isolated Python code execution tool with `--network=none`. |
| `sovereign-workbench/app/sandbox/manager.py` | Standalone Sandbox | **HIGH** | Workspace lifecycle manager for isolated container code execution. |
| `sovereign-workbench/app/tools/vision_extract.py` | Vision & OCR | **HIGH** | Structured JSON multimodal extraction tool using `qwen2.5vl`. |
| `sovereign-workbench/app/tools/docgen/generate_docx.py` | DocGen (Word) | **MEDIUM** | Formatted `.docx` report generator. |
| `sovereign-workbench/app/tools/docgen/generate_pptx.py` | DocGen (Slides) | **MEDIUM** | Formatted `.pptx` presentation deck generator. |
| `sovereign-workbench/app/tools/docgen/generate_xlsx.py` | DocGen (Excel) | **MEDIUM** | Formatted `.xlsx` spreadsheet generator with formula evaluation. |
| `sovereign-workbench/tests/test_phase_d.py` | Phase D Tests | **MEDIUM** | Unit test suite for vision, docgen, and code sandbox. |
