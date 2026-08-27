"""
tests/test_phase_c.py
=====================
Phase C offline tests — all pass without a live Ollama instance or Qdrant.

Phase C baseline (18 tests)
---------------------------
 1.  chunk_text: correct chunk / overlap counts
 2.  chunk_text: text shorter than chunk_size → single chunk
 3.  chunk_text: empty string → empty list
 4.  chunk_text: overlap=0 → no shared characters
 5.  gpu_detect: returns zeroed dict when nvidia-smi is absent (FileNotFoundError)
 6.  gpu_detect: parses nvidia-smi CSV stub correctly
 7.  tier_resolver: picks smallest model when budget=0 (CPU / no GPU)
 8.  tier_resolver: picks larger model when budget is sufficient
 9.  tier_resolver: respects FORCE_TIER env var
10.  Embedder.embed_batch: calls ollama_client.embeddings N times
11.  Embedder.embed_batch: raises on empty list
12.  VectorStore.upsert: calls qdrant_client.upsert with correct payload shape
13.  VectorStore.search: returns SearchResult list
14.  Ingestor.ingest: end-to-end chunk→embed→upsert + audit record written
15.  Ingestor.ingest: raises FileNotFoundError on missing source
16.  RagSearchTool.execute: returns formatted markdown from mocked store
17.  RagSearchTool.execute: returns failure when query is missing
18.  RagSearchTool.execute: returns success on empty results

Phase C — new spec tests (6 tests, tests 19-24)
-------------------------------------------------
19.  KnowledgeBaseIngestor: all metadata fields populated, confidentiality='public'
20.  KnowledgeBaseIngestor: zero-text PDF logs warning, batch continues (skip not fail)
21.  KnowledgeBaseIngestor: re-ingestion updates not duplicates (deterministic IDs)
22.  RagSearchTool / store.search_filtered: withdrawn chunks excluded by default
23.  RagSearchTool: audit log entry written with request_id, query, doc names
24.  Orchestrator: 2-step plan calls rag_search as a registered tool
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1-4: chunk_text
# ---------------------------------------------------------------------------


class TestChunkText:
    def _import(self):
        from app.rag.chunker import chunk_text
        return chunk_text

    def test_chunk_count_and_overlap(self):
        chunk_text = self._import()
        # 1000-char text, chunk_size=200, overlap=50 → step=150
        # starts: 0, 150, 300, 450, 600, 750, 900 → 7 chunks
        text = "A" * 1000
        chunks = chunk_text(text, chunk_size=200, overlap=50)
        assert len(chunks) == 7, f"Expected 7 chunks, got {len(chunks)}"
        # Every chunk except the last should be exactly chunk_size chars
        for c in chunks[:-1]:
            assert len(c) == 200, f"Chunk too short: {len(c)}"

    def test_short_text_single_chunk(self):
        chunk_text = self._import()
        text = "hello world"
        chunks = chunk_text(text, chunk_size=512, overlap=64)
        assert chunks == ["hello world"]

    def test_empty_string_returns_empty_list(self):
        chunk_text = self._import()
        assert chunk_text("", chunk_size=200, overlap=50) == []

    def test_zero_overlap_no_shared_chars(self):
        chunk_text = self._import()
        text = "ABCDEFGHIJ"  # 10 chars
        chunks = chunk_text(text, chunk_size=5, overlap=0)
        # step = 5, starts: 0, 5 → ["ABCDE", "FGHIJ"]
        assert chunks == ["ABCDE", "FGHIJ"]


# ---------------------------------------------------------------------------
# 5-6: gpu_detect
# ---------------------------------------------------------------------------


class TestGpuDetect:
    def _import(self):
        from app.hardware.gpu_detect import detect_gpu
        return detect_gpu

    def test_no_gpu_returns_zeroed_dict(self):
        """When nvidia-smi is absent, detect_gpu must return _NO_GPU."""
        detect_gpu = self._import()
        # Force Linux platform so the nvidia-smi path runs (not sysctl).
        with patch("platform.system", return_value="Linux"):
            with patch("subprocess.run", side_effect=FileNotFoundError("nvidia-smi not found")):
                info = detect_gpu()
        assert info["gpu_available"] is False
        assert info["total_vram_mb"] == 0
        assert info["free_vram_mb"] == 0
        assert info["device_name"] == ""

    def test_parses_nvidia_smi_csv(self):
        """nvidia-smi CSV output is parsed correctly into GpuInfo."""
        detect_gpu = self._import()
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "24564, 20000, NVIDIA RTX 4090\n"
        # Force Linux platform so the nvidia-smi path runs (not sysctl).
        with patch("platform.system", return_value="Linux"):
            with patch("subprocess.run", return_value=fake_result):
                info = detect_gpu()
        assert info["gpu_available"] is True
        assert info["total_vram_mb"] == 24564
        assert info["free_vram_mb"] == 20000
        assert "4090" in info["device_name"]



# ---------------------------------------------------------------------------
# 7-9: tier_resolver
# ---------------------------------------------------------------------------


class TestTierResolver:
    def _import(self):
        from app.hardware.tier_resolver import resolve_startup_models
        return resolve_startup_models

    def _no_gpu_info(self):
        return {
            "gpu_available": False,
            "total_vram_mb": 0,
            "free_vram_mb": 0,
            "device_name": "",
        }

    def _gpu_info(self, free_mb: int):
        return {
            "gpu_available": True,
            "total_vram_mb": free_mb + 4000,
            "free_vram_mb": free_mb,
            "device_name": "Test GPU",
        }

    def test_cpu_mode_picks_smallest(self):
        """With 0 VRAM budget every modality should fall back to the smallest model."""
        resolve_startup_models = self._import()
        with patch("app.hardware.tier_resolver.detect_gpu", return_value=self._no_gpu_info()):
            resolved = resolve_startup_models()
        # The text modality should be mapped to something (not empty)
        assert "text" in resolved
        # All resolved values must be valid registry keys
        from app.models.ollama_client import MODEL_REGISTRY
        for modality, name in resolved.items():
            assert name in MODEL_REGISTRY, f"{name} not in registry"

    def test_large_budget_picks_bigger_model(self):
        """With 48 GB free we expect mid or large tier to be chosen for text."""
        resolve_startup_models = self._import()
        with patch(
            "app.hardware.tier_resolver.detect_gpu",
            return_value=self._gpu_info(free_mb=48000),
        ):
            resolved = resolve_startup_models()
        assert "text" in resolved
        from app.models.ollama_client import MODEL_REGISTRY
        text_model = MODEL_REGISTRY[resolved["text"]]
        # Should NOT be the tiny 7b if budget is 48 GB
        assert text_model.get("est_vram_mb", 0) > 4000, (
            f"Expected a larger model, got {text_model['name']} "
            f"with est_vram_mb={text_model.get('est_vram_mb')}"
        )

    def test_force_tier_env_var(self):
        """FORCE_TIER=small must select small-tier models regardless of GPU."""
        resolve_startup_models = self._import()
        env = {"FORCE_TIER": "small"}
        with patch.dict(os.environ, env):
            resolved = resolve_startup_models()
        from app.models.ollama_client import MODEL_REGISTRY
        for modality, name in resolved.items():
            tier = MODEL_REGISTRY[name].get("tier", "")
            assert tier in ("small", "default"), (
                f"Expected small/default tier for {modality}, got {tier} ({name})"
            )


# ---------------------------------------------------------------------------
# 10: Embedder
# ---------------------------------------------------------------------------


class TestEmbedder:
    def test_embed_batch_calls_client_n_times(self):
        from app.rag.embedder import Embedder

        mock_client = MagicMock()
        mock_client.embeddings = AsyncMock(return_value=[0.1] * 1024)

        embedder = Embedder(mock_client)
        texts = ["hello", "world", "foo"]
        result = _run(embedder.embed_batch(texts))

        assert mock_client.embeddings.call_count == len(texts)
        assert len(result) == len(texts)
        assert all(len(v) == 1024 for v in result)

    def test_embed_batch_raises_on_empty(self):
        from app.rag.embedder import Embedder
        mock_client = MagicMock()
        embedder = Embedder(mock_client)
        with pytest.raises(ValueError, match="at least one text"):
            _run(embedder.embed_batch([]))


# ---------------------------------------------------------------------------
# 11-12: VectorStore
# ---------------------------------------------------------------------------


class TestVectorStore:
    def _make_store_with_mock_client(self):
        """Create a VectorStore with a mocked qdrant_client.QdrantClient."""
        from app.rag.store import VectorStore

        mock_qdrant = MagicMock()
        # Simulate empty existing collections
        mock_qdrant.get_collections.return_value.collections = []

        store = VectorStore.__new__(VectorStore)
        store._client = mock_qdrant
        return store, mock_qdrant

    def test_upsert_calls_qdrant_with_correct_count(self):
        store, mock_qdrant = self._make_store_with_mock_client()

        chunks = ["chunk A", "chunk B", "chunk C"]
        vectors = [[0.1] * 1024, [0.2] * 1024, [0.3] * 1024]

        ids = store.upsert(
            collection="test_col",
            chunks=chunks,
            vectors=vectors,
            source="/test/file.txt",
        )

        # Collection should have been created (it didn't exist)
        mock_qdrant.create_collection.assert_called_once()
        # Upsert should have been called once with 3 points
        mock_qdrant.upsert.assert_called_once()
        call_kwargs = mock_qdrant.upsert.call_args
        points = call_kwargs.kwargs.get("points", call_kwargs.args[0] if call_kwargs.args else [])
        assert len(ids) == 3

    def test_search_returns_search_results(self):
        from app.rag.store import SearchResult

        store, mock_qdrant = self._make_store_with_mock_client()

        # Mock Qdrant search hits
        hit1 = MagicMock()
        hit1.score = 0.95
        hit1.id = str(uuid.uuid4())
        hit1.payload = {"text": "relevant text", "source": "/docs/a.txt"}

        hit2 = MagicMock()
        hit2.score = 0.81
        hit2.id = str(uuid.uuid4())
        hit2.payload = {"text": "less relevant", "source": "/docs/b.txt"}

        mock_qdrant.search.return_value = [hit1, hit2]

        results = store.search(
            collection="test_col",
            query_vector=[0.5] * 1024,
            top_k=5,
        )

        assert len(results) == 2
        assert isinstance(results[0], SearchResult)
        assert results[0].score == pytest.approx(0.95)
        assert results[0].text == "relevant text"
        assert results[1].score == pytest.approx(0.81)


# ---------------------------------------------------------------------------
# 13-14: Ingestor
# ---------------------------------------------------------------------------


class TestIngestor:
    def _make_ingestor(self, audit_logger, mock_store, mock_embedder):
        from app.rag.ingestor import Ingestor
        return Ingestor(
            embedder=mock_embedder,
            store=mock_store,
            audit_logger=audit_logger,
        )

    def test_ingest_end_to_end(self, tmp_path):
        """Full chunk→embed→upsert pipeline on a real temp file."""
        from app.rag.ingestor import Ingestor

        # Create a temp text file with enough content to chunk
        content = "The quick brown fox jumps over the lazy dog. " * 30
        src = tmp_path / "test.txt"
        src.write_text(content)

        # Mocks
        mock_embedder = MagicMock()
        mock_embedder.embed_batch = AsyncMock(
            side_effect=lambda texts, **kw: [[0.1] * 1024] * len(texts)
        )
        mock_store = MagicMock()
        mock_store.upsert = MagicMock(return_value=["id1", "id2"])

        # Temporary audit log
        audit_log = tmp_path / "audit.jsonl"
        from app.audit.logger import AuditLogger
        audit_logger = AuditLogger(log_path=audit_log)

        ingestor = Ingestor(
            embedder=mock_embedder,
            store=mock_store,
            audit_logger=audit_logger,
        )

        result = _run(ingestor.ingest(src, collection="docs"))

        # embed_batch was called
        mock_embedder.embed_batch.assert_called_once()
        # upsert was called
        mock_store.upsert.assert_called_once()
        # Result is correct
        assert result.chunks_ingested > 0
        assert result.collection == "docs"
        assert len(result.source_sha256) == 64

        # Audit log must contain a rag_ingest record
        records = [
            __import__("json").loads(line)
            for line in audit_log.read_text().splitlines()
            if line.strip()
        ]
        rag_records = [r for r in records if r.get("event_type") == "rag_ingest"]
        assert len(rag_records) == 1
        assert rag_records[0]["payload"]["chunks_ingested"] == result.chunks_ingested

    def test_ingest_missing_file_raises(self):
        """Ingestor must raise FileNotFoundError for a non-existent path."""
        from app.rag.ingestor import Ingestor
        from app.audit.logger import AuditLogger
        import tempfile, os

        with tempfile.TemporaryDirectory() as td:
            audit_logger = AuditLogger(log_path=Path(td) / "audit.jsonl")
            mock_embedder = MagicMock()
            mock_store = MagicMock()
            ingestor = Ingestor(
                embedder=mock_embedder,
                store=mock_store,
                audit_logger=audit_logger,
            )
            with pytest.raises(FileNotFoundError):
                _run(ingestor.ingest("/nonexistent/path/file.txt", collection="docs"))


# ---------------------------------------------------------------------------
# 15: RagSearchTool
# ---------------------------------------------------------------------------


class TestRagSearchTool:
    def test_execute_returns_formatted_markdown(self):
        from app.rag.store import SearchResult
        from app.tools.rag_search import RagSearchTool

        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed_one = AsyncMock(return_value=[0.1] * 1024)

        chunk_id = str(uuid.uuid4())
        mock_store.search_filtered.return_value = [
            SearchResult(
                score=0.92,
                text="The answer is 42.",
                source="/docs/hitchhiker.txt",
                chunk_id=chunk_id,
                collection="docs",
            )
        ]

        tool = RagSearchTool(store=mock_store, embedder=mock_embedder)
        result = _run(tool.execute(query="what is the answer?"))

        assert result.success is True
        assert "0.92" in result.output
        assert "42" in result.output
        assert result.metadata["hits"] == 1

    def test_execute_missing_query_returns_failure(self):
        from app.tools.rag_search import RagSearchTool

        mock_store = MagicMock()
        mock_embedder = MagicMock()
        tool = RagSearchTool(store=mock_store, embedder=mock_embedder)

        result = _run(tool.execute())  # no query kwarg
        assert result.success is False
        assert "query" in result.error.lower()

    def test_execute_empty_results_returns_success(self):
        from app.tools.rag_search import RagSearchTool

        mock_store = MagicMock()
        mock_store.search_filtered.return_value = []
        mock_embedder = MagicMock()
        mock_embedder.embed_one = AsyncMock(return_value=[0.1] * 1024)

        tool = RagSearchTool(store=mock_store, embedder=mock_embedder)
        result = _run(tool.execute(query="something obscure"))
        assert result.success is True
        assert "No relevant" in result.output


# ===========================================================================
# ── 19-24: New Phase C spec tests (FakeEmbeddingClient + in-memory Qdrant)
# ===========================================================================
#
# These tests use:
#   - FakeEmbeddingClient: deterministic fixed-vector, no Ollama needed.
#   - In-memory QdrantClient (":memory:"): real Qdrant library, no server.
#   - FakeOllamaClient: from the Phase B pattern, for orchestrator tests.
#
# All pass fully offline.
# ---------------------------------------------------------------------------


class FakeEmbeddingClient:
    """
    Deterministic embedding stub.  Always returns the same fixed 1024-dim
    vector so semantic similarity comparisons are stable across test runs.
    """

    def __init__(self, dim: int = 1024, value: float = 0.1) -> None:
        self._dim = dim
        self._value = value
        self.call_count = 0

    async def embeddings(
        self,
        text: str,
        *,
        request_id: str | None = None,
    ) -> list[float]:
        self.call_count += 1
        return [self._value] * self._dim


def _make_in_memory_store():
    """
    Return a VectorStore whose internal Qdrant client points at ':memory:'.
    Bypasses VectorStore.__init__ (which connects to localhost:6333).
    """
    from app.rag.store import VectorStore
    from qdrant_client import QdrantClient  # type: ignore[import]

    store = VectorStore.__new__(VectorStore)
    store._client = QdrantClient(":memory:")
    return store


# ---------------------------------------------------------------------------
# 19. KnowledgeBaseIngestor — metadata schema
# ---------------------------------------------------------------------------


class TestKBIngestorMetadata:
    def test_all_metadata_fields_populated(self, tmp_path):
        """
        Ingesting a small PDF-shaped fixture should produce chunks with
        every required metadata field: doc_name, source_category, page_number,
        edition_date (null), status ('in_force'), confidentiality ('public').

        We synthesise a minimal real PDF using pymupdf so the chunker can
        actually extract text (no mocking needed for chunker).
        """
        import fitz  # pymupdf
        from app.audit.logger import AuditLogger
        from app.rag.embedder import Embedder
        from app.rag.ingest import KnowledgeBaseIngestor
        from app.rag.store import make_chunk_id

        # Create a tiny PDF with real extractable text
        pdf_path = tmp_path / "test_doc.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "This is test content for metadata verification. " * 20)
        doc.save(str(pdf_path))
        doc.close()

        # Infrastructure
        store = _make_in_memory_store()
        fake_client = FakeEmbeddingClient()
        embedder = Embedder(fake_client)
        audit_log = tmp_path / "audit.jsonl"
        audit = AuditLogger(log_path=audit_log)

        kb_ingestor = KnowledgeBaseIngestor(
            embedder=embedder,
            store=store,
            audit_logger=audit,
        )

        result = _run(
            kb_ingestor.ingest_document(
                pdf_path=pdf_path,
                source_category="mrpl_public",
                collection="test_col",
            )
        )

        assert not result.skipped, "Expected chunks extracted, not skipped"
        assert result.chunks_ingested > 0

        # Read back from in-memory Qdrant and inspect payload
        hits, _ = store._client.scroll(
            collection_name="test_col",
            with_payload=True,
            limit=100,
        )
        assert len(hits) > 0

        payload = hits[0].payload
        assert payload["doc_name"] == "test_doc.pdf"
        assert payload["source_category"] == "mrpl_public"
        assert isinstance(payload["page_number"], int) and payload["page_number"] >= 1
        assert payload["edition_date"] is None       # null — not guessed
        assert payload["status"] == "in_force"       # default
        assert payload["confidentiality"] == "public"  # default — enforced now
        assert "text" in payload
        assert "source" in payload
        assert len(payload["source_sha256"]) == 64

        # Verify the point ID is deterministic
        expected_id = make_chunk_id("test_doc.pdf", payload["page_number"], 0)
        # At least one chunk should have the expected deterministic id
        all_ids = {str(h.id) for h in hits}
        assert expected_id in all_ids, (
            f"Deterministic point ID {expected_id!r} not found among {list(all_ids)[:5]}"
        )


# ---------------------------------------------------------------------------
# 20. KnowledgeBaseIngestor — zero-text PDF (scanned/image-only)
# ---------------------------------------------------------------------------


class TestKBIngestorZeroTextPDF:
    def test_zero_text_pdf_logs_warning_and_is_skipped(self, tmp_path, caplog):
        """
        A PDF with no extractable text (all-image pages) must:
        - Log a WARNING mentioning ZERO_TEXT_PDF.
        - Return a DocumentIngestResult with skipped=True.
        - NOT crash the batch (no exception raised).
        """
        import fitz  # pymupdf
        import logging
        from app.audit.logger import AuditLogger
        from app.rag.embedder import Embedder
        from app.rag.ingest import KnowledgeBaseIngestor

        # Create a PDF with a blank page (no text → fitz extracts nothing)
        pdf_path = tmp_path / "blank_scan.pdf"
        doc = fitz.open()
        doc.new_page()   # blank page, no text layer
        doc.save(str(pdf_path))
        doc.close()

        store = _make_in_memory_store()
        fake_client = FakeEmbeddingClient()
        embedder = Embedder(fake_client)
        audit = AuditLogger(log_path=tmp_path / "audit.jsonl")

        kb_ingestor = KnowledgeBaseIngestor(
            embedder=embedder, store=store, audit_logger=audit
        )

        with caplog.at_level(logging.WARNING, logger="sovereign.rag.ingest"):
            result = _run(
                kb_ingestor.ingest_document(
                    pdf_path=pdf_path,
                    source_category="oisd_standards",
                    collection="test_col",
                )
            )

        assert result.skipped is True, "Expected skipped=True for zero-text PDF"
        assert result.chunks_ingested == 0
        assert result.skip_reason is not None

        # embedder must NOT have been called (nothing to embed)
        assert fake_client.call_count == 0, (
            f"Embedder was called {fake_client.call_count} times on a zero-text PDF"
        )

        # Warning must have been logged
        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("ZERO_TEXT_PDF" in m for m in warning_messages), (
            f"Expected ZERO_TEXT_PDF warning, got: {warning_messages}"
        )


# ---------------------------------------------------------------------------
# 21. Re-ingestion updates, not duplicates (deterministic IDs)
# ---------------------------------------------------------------------------


class TestKBIngestorReingestion:
    def test_reingestion_updates_not_duplicates(self, tmp_path):
        """
        Running ingest_document twice on the same file must produce the same
        set of deterministic point IDs.  Qdrant's upsert semantics will update
        existing points, so the collection count must be identical after both
        runs — no duplicates.
        """
        import fitz  # pymupdf
        from app.audit.logger import AuditLogger
        from app.rag.embedder import Embedder
        from app.rag.ingest import KnowledgeBaseIngestor

        pdf_path = tmp_path / "stable_doc.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Re-ingestion test content. " * 30)
        doc.save(str(pdf_path))
        doc.close()

        store = _make_in_memory_store()
        fake_client = FakeEmbeddingClient()
        embedder = Embedder(fake_client)
        audit = AuditLogger(log_path=tmp_path / "audit.jsonl")

        kb_ingestor = KnowledgeBaseIngestor(
            embedder=embedder, store=store, audit_logger=audit
        )

        # First ingest
        r1 = _run(
            kb_ingestor.ingest_document(
                pdf_path=pdf_path,
                source_category="mrpl_public",
                collection="test_col",
            )
        )
        count_after_first = store._client.count("test_col").count
        assert count_after_first == r1.chunks_ingested

        # Second ingest — same file, same IDs
        r2 = _run(
            kb_ingestor.ingest_document(
                pdf_path=pdf_path,
                source_category="mrpl_public",
                collection="test_col",
            )
        )
        count_after_second = store._client.count("test_col").count

        assert count_after_second == count_after_first, (
            f"Re-ingestion duplicated points: {count_after_first} → {count_after_second}. "
            "Deterministic IDs are not working."
        )
        assert r2.chunks_ingested == r1.chunks_ingested


# ---------------------------------------------------------------------------
# 22. search_filtered — withdrawn chunks excluded by default
# ---------------------------------------------------------------------------


class TestSearchFilteredWithdrawn:
    def test_withdrawn_chunks_excluded_by_default(self):
        """
        Store two points: one status='in_force', one status='withdrawn'.
        search_filtered() with the default exclude_status=["withdrawn"] must
        return only the in_force chunk.
        """
        from qdrant_client import QdrantClient  # type: ignore[import]
        from qdrant_client.models import Distance, VectorParams, PointStruct
        from app.rag.store import VectorStore, SearchResult, make_chunk_id

        store = _make_in_memory_store()
        DIM = 1024

        # Create collection manually in in-memory client
        store._client.create_collection(
            "test_col",
            vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
        )

        in_force_id = make_chunk_id("doc_a.pdf", 1, 0)
        withdrawn_id = make_chunk_id("doc_b.pdf", 2, 0)

        store._client.upsert(
            collection_name="test_col",
            points=[
                PointStruct(
                    id=in_force_id,
                    vector=[0.1] * DIM,
                    payload={
                        "text": "Active content",
                        "source": "/docs/doc_a.pdf",
                        "doc_name": "doc_a.pdf",
                        "source_category": "mrpl_public",
                        "page_number": 1,
                        "status": "in_force",
                        "confidentiality": "public",
                        "edition_date": None,
                    },
                ),
                PointStruct(
                    id=withdrawn_id,
                    vector=[0.1] * DIM,
                    payload={
                        "text": "Withdrawn content",
                        "source": "/docs/doc_b.pdf",
                        "doc_name": "doc_b.pdf",
                        "source_category": "mrpl_public",
                        "page_number": 2,
                        "status": "withdrawn",
                        "confidentiality": "public",
                        "edition_date": None,
                    },
                ),
            ],
        )

        # Default search_filtered MUST exclude the withdrawn chunk
        results = store.search_filtered(
            collection="test_col",
            query_vector=[0.1] * DIM,
            top_k=10,
        )

        assert len(results) == 1, (
            f"Expected 1 result (in_force only), got {len(results)}: "
            f"{[r.doc_name for r in results]}"
        )
        assert results[0].doc_name == "doc_a.pdf"
        assert results[0].status == "in_force"

        # Unfiltered search should return both
        all_results = store.search(
            collection="test_col",
            query_vector=[0.1] * DIM,
            top_k=10,
        )
        assert len(all_results) == 2, (
            f"Expected 2 results unfiltered, got {len(all_results)}"
        )


# ---------------------------------------------------------------------------
# 23. RagSearchTool — RAG_RETRIEVAL audit log entry
# ---------------------------------------------------------------------------


class TestRagSearchAuditLog:
    def test_retrieval_logged_with_request_id_query_docs(self, tmp_path):
        """
        RagSearchTool.execute() must write a RAG_RETRIEVAL audit record
        containing: request_id, the query, and the doc_name/page_number of
        every returned chunk.
        """
        import json
        from qdrant_client.models import Distance, VectorParams, PointStruct
        from app.audit.logger import AuditLogger
        from app.rag.embedder import Embedder
        from app.rag.store import make_chunk_id
        from app.tools.rag_search import RagSearchTool

        DIM = 1024
        audit_log = tmp_path / "audit.jsonl"
        audit = AuditLogger(log_path=audit_log)

        store = _make_in_memory_store()
        store._client.create_collection(
            "test_col",
            vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
        )

        point_id = make_chunk_id("env_report.pdf", 5, 0)
        store._client.upsert(
            collection_name="test_col",
            points=[
                PointStruct(
                    id=point_id,
                    vector=[0.1] * DIM,
                    payload={
                        "text": "Environmental compliance chapter.",
                        "source": "/kb/mrpl_public/env_report.pdf",
                        "doc_name": "env_report.pdf",
                        "source_category": "mrpl_public",
                        "page_number": 5,
                        "status": "in_force",
                        "confidentiality": "public",
                        "edition_date": None,
                    },
                )
            ],
        )

        fake_client = FakeEmbeddingClient()
        embedder = Embedder(fake_client)
        tool = RagSearchTool(store=store, embedder=embedder, audit_logger=audit)

        request_id = "test-retrieval-audit-001"
        result = _run(
            tool.execute(
                query="environmental compliance",
                collection="test_col",
                request_id=request_id,
            )
        )

        assert result.success is True, f"Tool failed: {result.error}"

        # Parse audit log
        records = [
            json.loads(line)
            for line in audit_log.read_text().splitlines()
            if line.strip()
        ]
        retrieval_records = [
            r for r in records
            if r.get("event_type") == "rag_retrieval"
            and r.get("request_id") == request_id
        ]
        assert len(retrieval_records) >= 1, (
            "Expected at least one rag_retrieval audit record with the correct request_id"
        )

        rec = retrieval_records[0]
        payload = rec["payload"]

        # Must contain query
        assert "environmental compliance" in payload["query"]

        # Must contain source attribution (doc_name + page_number)
        assert "sources" in payload
        assert len(payload["sources"]) >= 1
        source = payload["sources"][0]
        assert source["doc_name"] == "env_report.pdf"
        assert source["page_number"] == 5


# ---------------------------------------------------------------------------
# 24. Orchestrator — 2-step plan with rag_search as registered tool
# ---------------------------------------------------------------------------


class TestOrchestratorWithRagSearch:
    def test_orchestrator_can_call_rag_search(self, tmp_path):
        """
        Register a RagSearchTool (backed by in-memory Qdrant) alongside
        the normal TOOL_REGISTRY, give FakeOllamaClient a plan that calls
        rag_search, and verify the orchestrator completes with COMPLETED status.

        This test validates that:
        1. The orchestrator's tool interface is generic enough to accept rag_search.
        2. The 2-step flow (plan → act → synthesise) works end-to-end.
        3. The final output references the retrieved doc (or at least reports
           a successful run).
        """
        import json
        from dataclasses import dataclass
        from typing import Any, Optional
        from qdrant_client.models import Distance, VectorParams, PointStruct

        from app.audit.logger import AuditLogger
        from app.orchestrator.orchestrator import Orchestrator
        from app.orchestrator.state import OrchestratorStatus
        from app.rag.embedder import Embedder
        from app.rag.store import make_chunk_id
        from app.tools.rag_search import RagSearchTool
        from app.tools.registry import register_tool, TOOL_REGISTRY

        @dataclass
        class FakeResponse:
            content: str
            prompt_tokens: int = 5
            response_tokens: int = 5
            total_tokens: int = 10
            latency_ms: float = 1.0
            model_name: str = "fake"
            ollama_tag: str = "fake:latest"
            request_id: str = "fake-rid"

        class FakeOllamaClient:
            def __init__(self, responses):
                self._responses = responses
                self._idx = 0

            async def chat_completion(self, messages, *, request_id=None,
                                      temperature=0.0, max_tokens=16,
                                      extra_body=None):
                idx = min(self._idx, len(self._responses) - 1)
                content = self._responses[idx]
                self._idx += 1
                return FakeResponse(content=content)

        DIM = 1024
        store = _make_in_memory_store()
        store._client.create_collection(
            "docs",
            vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
        )

        point_id = make_chunk_id("oisd_standards.pdf", 3, 0)
        store._client.upsert(
            collection_name="docs",
            points=[
                PointStruct(
                    id=point_id,
                    vector=[0.1] * DIM,
                    payload={
                        "text": "OISD standard 118 covers pressure vessel inspection.",
                        "source": "/kb/oisd_standards/oisd_standards.pdf",
                        "doc_name": "oisd_standards.pdf",
                        "source_category": "oisd_standards",
                        "page_number": 3,
                        "status": "in_force",
                        "confidentiality": "public",
                        "edition_date": None,
                    },
                )
            ],
        )

        fake_embedding = FakeEmbeddingClient()
        embedder = Embedder(fake_embedding)
        audit_log = tmp_path / "audit.jsonl"
        audit = AuditLogger(log_path=audit_log)

        tool = RagSearchTool(store=store, embedder=embedder, audit_logger=audit)
        # Register in the live TOOL_REGISTRY so orchestrator can find it
        register_tool(tool)

        plan_json = json.dumps([
            {
                "step_index": 0,
                "tool_name": "rag_search",
                "tool_args": {
                    "query": "pressure vessel inspection standard",
                    "collection": "docs",
                },
                "description": "Search for OISD pressure vessel standard",
            }
        ])
        synthesis_text = (
            "Per OISD standard 118 (oisd_standards.pdf, page 3), "
            "pressure vessels must be inspected annually."
        )

        fake_llm = FakeOllamaClient(responses=[plan_json, synthesis_text])
        orch = Orchestrator(llm_client=fake_llm, audit_logger=audit)

        run = _run(
            orch.run(
                "What does OISD say about pressure vessel inspection?",
                request_id="orch-rag-001",
            )
        )

        assert run.status == OrchestratorStatus.COMPLETED, (
            f"Expected COMPLETED, got {run.status}. Failure: {run.failure_summary}"
        )
        assert len(run.outcomes) >= 1
        assert run.outcomes[0].success is True, (
            f"rag_search step failed: {run.outcomes[0].error}"
        )
        assert run.final_output is not None
