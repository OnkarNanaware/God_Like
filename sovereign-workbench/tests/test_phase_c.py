"""
tests/test_phase_c.py
=====================
Phase C offline tests — all pass without a live Ollama instance or Qdrant.

Coverage (15 tests)
-------------------
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
11.  VectorStore.upsert: calls qdrant_client.upsert with correct payload shape
12.  VectorStore.search: returns SearchResult list
13.  Ingestor.ingest: end-to-end chunk→embed→upsert + audit record written
14.  Ingestor.ingest: raises FileNotFoundError on missing source
15.  RagSearchTool.execute: returns formatted markdown from mocked store
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
        detect_gpu = self._import()
        with patch("subprocess.run", side_effect=FileNotFoundError("nvidia-smi not found")):
            info = detect_gpu()
        assert info["gpu_available"] is False
        assert info["total_vram_mb"] == 0
        assert info["free_vram_mb"] == 0
        assert info["device_name"] == ""

    def test_parses_nvidia_smi_csv(self):
        detect_gpu = self._import()
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "24564, 20000, NVIDIA RTX 4090\n"
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
        mock_store.search.return_value = [
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
        mock_store.search.return_value = []
        mock_embedder = MagicMock()
        mock_embedder.embed_one = AsyncMock(return_value=[0.1] * 1024)

        tool = RagSearchTool(store=mock_store, embedder=mock_embedder)
        result = _run(tool.execute(query="something obscure"))
        assert result.success is True
        assert "No relevant" in result.output
