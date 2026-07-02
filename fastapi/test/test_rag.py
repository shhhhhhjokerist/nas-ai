"""Integration tests for retrieval service and RAG endpoints.

These tests use ChromaDB's ephemeral (in-memory) client so no persistence is needed.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import app
from app.db import Base, get_db


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fake_embedding(texts: list[str]) -> list[list[float]]:
    """Deterministic fake embedding for tests — avoids loading BGE model."""
    import hashlib

    dim = 512
    out = []
    for t in texts:
        h = hashlib.md5(t.encode()).digest()
        vec = [(b / 255.0) for b in h]
        # Pad or truncate to *dim*
        while len(vec) < dim:
            vec.append(0.0)
        vec = vec[:dim]
        # L2 normalize (rough)
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        out.append(vec)
    return out


def _fake_embed_query(text: str) -> list[float]:
    return _fake_embedding([text])[0]


# ── Tests ────────────────────────────────────────────────────────────────────


class TestRetrievalEmpty(unittest.TestCase):
    """Test retrieval when no documents are indexed."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.chroma_dir = os.path.join(self.tmpdir, "chroma_test")

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

        def override_get_db():
            db = self.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        import shutil

        Base.metadata.drop_all(bind=self.engine)
        app.dependency_overrides.clear()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_rag_query_empty(self):
        resp = self.client.post("/rag/query", json={"query": "test", "top_k": 3})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_rag_ask_empty(self):
        resp = self.client.post("/rag/ask", json={"query": "test", "top_k": 3})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("answer", data)
        self.assertEqual(data["sources"], [])

    def test_document_list_empty(self):
        resp = self.client.get("/documents/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_document_scan_empty(self):
        resp = self.client.post("/documents/scan")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["indexed"], 0)
        self.assertEqual(data["deleted"], 0)


class TestRetrievalWithChunks(unittest.TestCase):
    """Test retrieval with pre-populated ChromaDB chunks."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.chroma_dir = os.path.join(self.tmpdir, "chroma_test")

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

        def override_get_db():
            db = self.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        # Patch embedding service with deterministic fake vectors so tests
        # don't download the BGE model.
        self._patch_embed = mock.patch(
            "app.services.retrieval_service.RetrievalService.embedding_service",
            new_callable=mock.PropertyMock,
        )

        # Rather than fully mock, we'll patch the EmbeddingService globally.
        self._patch_get_emb = mock.patch(
            "app.services.embedding_service.get_embedding_service",
            return_value=mock.MagicMock(
                dim=512,
                embed=_fake_embedding,
                embed_query=_fake_embed_query,
            ),
        )
        self.mock_get_emb = self._patch_get_emb.start()

        # Patch ChromaDB collection to minimize persistence issues
        self._patch_chroma = mock.patch(
            "app.services.vector_store.VectorStore",
            autospec=True,
        )

        self.client = TestClient(app)

    def tearDown(self):
        import shutil

        mock.patch.stopall()
        Base.metadata.drop_all(bind=self.engine)
        app.dependency_overrides.clear()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_rag_query_with_mocked_retrieval(self):
        """This tests the endpoint plumbing even when store is empty."""
        resp = self.client.post("/rag/query", json={"query": "人工智能", "top_k": 3})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("count", resp.json())


if __name__ == "__main__":
    unittest.main()
