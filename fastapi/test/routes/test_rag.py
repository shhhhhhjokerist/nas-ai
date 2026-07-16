"""RAG endpoint tests — query and ask endpoints with auth."""
import pytest
from unittest import mock
from fastapi.testclient import TestClient


class TestRAGAuth:
    def test_query_no_auth(self, client: TestClient):
        assert client.post("/rag/query", json={"query": "test"}).status_code == 401

    def test_ask_no_auth(self, client: TestClient):
        assert client.post("/rag/ask", json={"query": "test"}).status_code == 401


class TestRAGEndpoints:
    def test_query_empty(self, client: TestClient, auth_headers):
        """Test query endpoint with mocked vector store to avoid model + ChromaDB."""
        with mock.patch("app.services.vector_store.VectorStore") as mock_vs_cls:
            mock_vs = mock.MagicMock()
            mock_vs.search.return_value = []
            mock_vs_cls.return_value = mock_vs

            with mock.patch("app.services.retrieval_service.RetrievalService.embedding_service",
                            new_callable=mock.PropertyMock) as mock_emb:
                mock_svc = mock.MagicMock()
                mock_svc.embed_query.return_value = [0.1] * 512
                mock_emb.return_value = mock_svc

                resp = client.post("/rag/query", json={"query": "test", "top_k": 3}, headers=auth_headers)
                assert resp.status_code == 200
                assert "count" in resp.json()

    def test_ask_query(self, client: TestClient, auth_headers):
        """Test ask endpoint with mocked RAG service."""
        with mock.patch("app.services.rag_service.RAGService.ask") as mock_ask:
            mock_ask.return_value = {"query": "test", "answer": "mock answer", "sources": []}
            resp = client.post("/rag/ask", json={"query": "test", "top_k": 2}, headers=auth_headers)
            assert resp.status_code == 200
            assert resp.json()["answer"] == "mock answer"
