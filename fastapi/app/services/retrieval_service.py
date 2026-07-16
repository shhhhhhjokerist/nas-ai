"""Orchestrates embedding + vector search for document retrieval."""

from __future__ import annotations

from app.config import get_settings


class RetrievalService:
    """Combines EmbeddingService and VectorStore for semantic search.

    Lightweight — instantiate on-demand (no heavy state beyond the shared
    embedding singleton and the persisted ChromaDB).
    """

    def __init__(self, vector_store=None, embedding_service=None):
        self._vector_store = vector_store
        self._embedding_service = embedding_service

    # ── lazy init ────────────────────────────────────────────────────────────

    @property
    def vector_store(self):
        if self._vector_store is not None:
            return self._vector_store
        from app.services.vector_store import VectorStore

        self._vector_store = VectorStore(persist_dir=get_settings().CHROMA_DB_DIR)
        return self._vector_store

    @property
    def embedding_service(self):
        if self._embedding_service is not None:
            return self._embedding_service
        from app.services.embedding_service import get_embedding_service

        self._embedding_service = get_embedding_service()
        return self._embedding_service

    # ── public ───────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int | None = None,
        file_filter: str | None = None,
    ) -> list[dict]:
        """Semantic search over indexed documents.

        Parameters
        ----------
        query : str
            Natural-language query.
        top_k : int or None
            Number of results (defaults to ``Config.RETRIEVAL_TOP_K``).
        file_filter : str or None
            If set, restrict results to chunks from this absolute file path.

        Returns
        -------
        list[dict]
            Each hit: ``{id, text, metadata, distance, score}``
            where *score* = 1 − cosine-distance.
        """
        k = top_k or get_settings().RETRIEVAL_TOP_K

        query_vec = self.embedding_service.embed_query(query)

        where = None
        if file_filter:
            where = {"file_path": file_filter}

        hits = self.vector_store.search(query_vec, top_k=k, where=where)

        # Convert cosine distance → similarity score
        for hit in hits:
            dist = hit.get("distance")
            hit["score"] = round(1.0 - dist, 4) if dist is not None else None

        return hits
