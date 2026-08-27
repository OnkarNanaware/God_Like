# Verification Checklist — Task Tracker

## Phase 1 — Code Fixes
- [x] 1a. Fix `models.yaml`: add real `qwen25_coder_7b` entry (tag `qwen2.5-coder:7b`, est 4700MB), fix existing entry
- [x] 1b. Fix `main.py`: decouple `VisionExtractTool` registration from Qdrant try block

## Phase 2 — New Scripts
- [x] 2a. `scripts/ingest_corpus.py` — bulk ingest all knowledge_base/ PDFs into sovereign_knowledge_base
- [x] 2b. `scripts/verify_memory_budget.py` — repeatable memory math diagnostic
- [x] 2c. `scripts/verify_corpus_retrieval.py` — retrieval eval harness (3 queries + 1 mismatch)
- [x] 2d. `docs/ARCHITECTURE_NOTES.md` — Docker → embedded Qdrant one-liner update

## Phase 3 — Corpus Ingestion
- [ ] 3a. Run `python scripts/ingest_corpus.py` → populate sovereign_knowledge_base
      (needs Ollama running with bge-m3 pulled; ~30–90 min for 15 files)

## Phase 4 — Live Verification Passes
- [ ] 4a. `verify_memory_budget.py` on venue machine — confirm totals
- [ ] 4b. Pull `qwen2.5-coder:7b-instruct-q4_K_M` on demo machine
      `ollama pull qwen2.5-coder:7b-instruct-q4_K_M`
- [ ] 4c. Air-gap cold-start run (WiFi off, server starts, full flow completes)
- [ ] 4d. Router dual-type demo (coding + vision in same session, two different models in logs)
- [ ] 4e. Flagship 11-step flow — blocked until 4b resolved on venue machine
- [ ] 4f. Retrieval eval: `python scripts/verify_corpus_retrieval.py` (after 3a)
- [ ] 4g. Full flow twice in a row without restart
- [ ] 4h. pytest suite re-run on venue machine: must be 83 passed, 4 skipped, 0 failures
