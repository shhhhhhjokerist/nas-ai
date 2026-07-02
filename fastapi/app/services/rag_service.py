"""Full RAG pipeline: retrieve context → build prompt → generate answer."""

from __future__ import annotations

from app.services.retrieval_service import RetrievalService


class RAGService:
    """End-to-end RAG: retrieval + LLM generation."""

    def __init__(self, retrieval_service: RetrievalService | None = None):
        self.retrieval = retrieval_service or RetrievalService()

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        """Semantic search — retrieve relevant chunks only."""
        return self.retrieval.search(query, top_k=top_k)

    def generate(self, query: str, context_chunks: list[dict]) -> str:
        """Build a prompt from context chunks and call the LLM for an answer."""
        from app.agents.graph import _build_llm

        if not context_chunks:
            return "未找到相关文档内容，无法回答该问题。"

        context_text = "\n\n---\n\n".join(
            f"[来源: {c['metadata'].get('file_name', 'unknown')}]\n{c['text']}"
            for c in context_chunks
        )

        prompt = (
            "你是一个知识库助手。请根据以下文档摘录回答用户的问题。"
            "如果摘录中没有足够的信息，请如实告知。\n\n"
            f"### 文档摘录:\n{context_text}\n\n"
            f"### 用户问题:\n{query}\n\n"
            f"### 回答:"
        )

        llm = _build_llm()
        response = llm.invoke(prompt)
        return response.content

    def ask(self, query: str, top_k: int | None = None) -> dict:
        """Full RAG pipeline: retrieve context and generate an answer.

        Returns
        -------
        dict  ``{query, answer, sources}``
        """
        chunks = self.retrieve(query, top_k=top_k)
        answer = self.generate(query, chunks)
        return {
            "query": query,
            "answer": answer,
            "sources": [
                {
                    "file_name": c["metadata"].get("file_name", "unknown"),
                    "file_path": c["metadata"].get("file_path", ""),
                    "chunk_index": c["metadata"].get("chunk_index", 0),
                    "text_preview": c["text"][:200],
                    "score": c.get("score"),
                }
                for c in chunks
            ],
        }
