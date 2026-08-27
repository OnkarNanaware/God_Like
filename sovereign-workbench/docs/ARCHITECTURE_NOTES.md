# Architecture Notes — Sovereign Workbench

> **For judges, reviewers, and any presenter who references the deployment model.**

---

## Qdrant Vector Store — Deployment Mode

**Current mode: Embedded (in-process), no Docker required.**

The RAG pipeline runs Qdrant fully in-process using `qdrant-client`'s embedded mode.
Qdrant data is persisted to the local directory `qdrant_storage/` inside the project.
No Qdrant container, no Docker pull, no separate process, no network port for Qdrant.

> **Previous materials may say "Qdrant container" or "Docker" for Qdrant.
> This is no longer accurate.  Embedded mode is the current and intentional deployment model.**

This is a deliberate simplification that:
- Eliminates a Docker dependency for the vector store
- Removes one more network service from the localhost-only surface
- Keeps everything in a single process for the demo machine setup

If asked by a judge: *"We run Qdrant embedded — the qdrant-client library includes an in-process mode that persists to disk. No container is needed. All data stays on-device in `qdrant_storage/`."*

---

## Service Inventory (as of Phase D/E)

| Service | How it runs | Network binding |
|---------|-------------|-----------------|
| FastAPI backend | `uvicorn app.main:app --host 127.0.0.1 --port 8000` | `127.0.0.1:8000` (localhost only) |
| Ollama | `ollama serve` (system daemon) | `127.0.0.1:11434` (localhost only) |
| Qdrant | **Embedded in-process** (no separate process) | None — no network port |
| Frontend (Vite dev) | `npm run dev` | `127.0.0.1:5173` (localhost only) |
| Docker (for code sandbox) | Local Docker daemon | Used for `--network=none` sandbox containers only; no containers listen on external interfaces |

**Every service is localhost-only. No external network calls are made at runtime.**

---

## Model Selection at Startup

The tier resolver selects models at startup based on available hardware:

- **macOS (Apple Silicon):** Uses 50% of unified RAM as the effective budget, then applies 15% headroom. On a 16 GB Mac the budget is ~6,800 MB.
- **Linux + NVIDIA GPU:** Uses free VRAM from `nvidia-smi` minus 15% headroom.
- **No GPU detected:** Falls back to smallest tier for all modalities.

The resolver iterates modalities in order (`text → code → vision → embedding`) and picks the largest model that fits in the *remaining* budget after prior selections. This means the budget is shared cumulatively — individual models may fit but their combined footprint still needs to fit on the machine.

For the venue machine: run `python scripts/verify_memory_budget.py` before demo day.
