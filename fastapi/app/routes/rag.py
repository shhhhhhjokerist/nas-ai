"""RAG query endpoints — retrieval-only and full ask (retrieve + generate)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.rag_service import RAGService
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/rag", tags=["rag"])


# ── Pydantic schemas ─────────────────────────────────────────────────────────

class RAGQueryRequest(BaseModel):
    query: str
    top_k: int = 5


class RetrievalResponse(BaseModel):
    query: str
    count: int
    results: list[dict]


class RAGAskResponse(BaseModel):
    query: str
    answer: str
    sources: list[dict]


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/query", response_model=RetrievalResponse)
async def rag_query(request: RAGQueryRequest):
    """Retrieve relevant document chunks (retrieval only, no generation)."""
    retrieval = RetrievalService()
    hits = retrieval.search(request.query, top_k=request.top_k)
    return RetrievalResponse(
        query=request.query,
        count=len(hits),
        results=[
            {
                "text": h["text"],
                "source": h["metadata"].get("file_name", "unknown"),
                "score": h.get("score"),
                "chunk_index": h["metadata"].get("chunk_index"),
            }
            for h in hits
        ],
    )


@router.post("/ask", response_model=RAGAskResponse)
async def rag_ask(request: RAGQueryRequest):
    """Full RAG: retrieve context and generate an answer from the LLM."""
    try:
        rag = RAGService()
        result = rag.ask(request.query, top_k=request.top_k)
        return RAGAskResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"RAG query failed: {str(exc)}")
