"""Evaluation engine for the RAG system.

Computes retrieval metrics (hit rate, MRR, precision, recall) and generation
metrics (faithfulness, relevance) via an LLM judge.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from app.services.rag_service import RAGService
from app.services.retrieval_service import RetrievalService


# ═══════════════════════════════════════════════════════════════════════════════
#  Data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EvaluationQuestion:
    id: str
    question: str
    expected_answer: str = ""
    relevant_file: Optional[str] = None


@dataclass
class RetrievalMetrics:
    hit_rate: float = 0.0
    mrr: float = 0.0
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GenerationMetrics:
    faithfulness: float = 0.0
    relevance: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvaluationResult:
    retrieval: RetrievalMetrics = field(default_factory=RetrievalMetrics)
    generation: GenerationMetrics = field(default_factory=GenerationMetrics)
    per_question: list[dict] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        return {
            "retrieval": self.retrieval.to_dict(),
            "generation": self.generation.to_dict(),
            "per_question": self.per_question,
            "config": self.config,
            "timestamp": self.timestamp,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  Evaluator
# ═══════════════════════════════════════════════════════════════════════════════

class Evaluator:
    """Runs RAG evaluation over a question set and aggregates metrics.

    Retrieval metrics are computed by checking whether retrieved chunks come
    from the expected file (*relevant_file*).

    Generation metrics use the same ZhipuAI LLM as a binary judge (yes/no).
    """

    def __init__(
        self,
        questions: list[EvaluationQuestion],
        retrieval_service: RetrievalService | None = None,
        rag_service: RAGService | None = None,
    ):
        self.questions = questions
        self.retrieval = retrieval_service or RetrievalService()
        self.rag = rag_service or RAGService()

    # ── public ─────────────────────────────────────────────────────────────

    def run(self, top_k: int = 5) -> EvaluationResult:
        """Evaluate every question and aggregate metrics."""
        per_question: list[dict] = []

        # ── warn if no labels ─────────────────────────────────────────
        labeled = [q for q in self.questions if q.relevant_file]
        if not labeled:
            import logging
            _log = logging.getLogger(__name__)
            _log.warning(
                "None of the %d questions have a 'relevant_file' label. "
                "Retrieval metrics (hit_rate, MRR, precision, recall) "
                "will all be 0.  Set 'relevant_file' to the filename "
                "that should contain the answer for each question.",
                len(self.questions),
            )

        hit_count = 0
        reciprocal_ranks: list[float] = []
        precision_sum = 0.0
        recall_sum = 0.0
        faithfulness_sum = 0.0
        relevance_sum = 0.0
        n = len(self.questions)

        for q in self.questions:
            qr = self._evaluate_question(q, top_k)
            per_question.append(qr)

            if qr.get("hit"):
                hit_count += 1
            if qr.get("reciprocal_rank") is not None:
                reciprocal_ranks.append(qr["reciprocal_rank"])
            precision_sum += qr.get("precision", 0)
            recall_sum += qr.get("recall", 0)
            faithfulness_sum += qr.get("faithfulness", 0)
            relevance_sum += qr.get("relevance", 0)

        from app.config import Config

        return EvaluationResult(
            retrieval=RetrievalMetrics(
                hit_rate=round(hit_count / n, 4) if n > 0 else 0,
                mrr=round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4)
                if reciprocal_ranks
                else 0,
                precision_at_k=round(precision_sum / n, 4) if n > 0 else 0,
                recall_at_k=round(recall_sum / n, 4) if n > 0 else 0,
            ),
            generation=GenerationMetrics(
                faithfulness=round(faithfulness_sum / n, 4) if n > 0 else 0,
                relevance=round(relevance_sum / n, 4) if n > 0 else 0,
            ),
            per_question=per_question,
            config={
                "top_k": top_k,
                "chunk_size": Config.CHUNK_SIZE,
                "chunk_overlap": Config.CHUNK_OVERLAP,
                "embedding_model": Config.EMBEDDING_MODEL_NAME,
                "num_questions": n,
                "labeled_questions": len(labeled),
                "note": (
                    "Hit Rate / MRR / Precision / Recall 需要 relevant_file 标签；"
                    "Faithfulness / Relevance 由 LLM Judge 自动评分无需标签"
                ),
            },
        )

    # ── per-question ──────────────────────────────────────────────────────

    def _evaluate_question(self, q: EvaluationQuestion, top_k: int) -> dict:
        """Run one question through retrieval + generation + judging."""
        # 1. Retrieve
        hits = self.retrieval.search(q.question, top_k=top_k)

        # 2. Compute retrieval metrics
        relevant_ranks: list[int] = []
        if q.relevant_file:
            for rank, hit in enumerate(hits, start=1):
                hit_file = hit["metadata"].get("file_path", "")
                if q.relevant_file in hit_file or hit_file.endswith(q.relevant_file):
                    relevant_ranks.append(rank)

        hit_bool = len(relevant_ranks) > 0
        rr = 1.0 / relevant_ranks[0] if relevant_ranks else None
        precision = len(relevant_ranks) / top_k if top_k > 0 else 0
        recall = 1.0 if hit_bool else 0.0

        # 3. Generate via RAG
        rag_result = self.rag.ask(q.question, top_k=top_k)
        answer = rag_result["answer"]

        # 4. LLM judge (skip if no context was retrieved)
        if hits:
            faithfulness = self._judge_faithfulness(q.question, answer, hits)
            relevance = self._judge_relevance(q.question, answer)
        else:
            faithfulness = 0.0
            relevance = 0.0

        return {
            "question_id": q.id,
            "question": q.question,
            "expected_answer": q.expected_answer,
            "answer": answer,
            "hit": hit_bool,
            "reciprocal_rank": rr,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "faithfulness": faithfulness,
            "relevance": relevance,
            "num_retrieved": len(hits),
            "sources": [h["metadata"].get("file_name", "") for h in hits],
        }

    # ── LLM judges ────────────────────────────────────────────────────────

    def _judge_faithfulness(
        self, question: str, answer: str, context_chunks: list[dict]
    ) -> float:
        """Judge whether the answer is supported by the retrieved context."""
        from app.agents.graph import _build_llm

        context_text = "\n\n---\n\n".join(c["text"] for c in context_chunks)
        prompt = (
            "你是一个评估器。给定一个问题、检索到的上下文和一个回答，"
            "判断该回答是否完全被上下文所支撑。\n\n"
            f"### 问题:\n{question}\n\n"
            f"### 检索到的上下文:\n{context_text}\n\n"
            f"### 回答:\n{answer}\n\n"
            "回答是否完全被上下文支撑？只回答 'yes' 或 'no'。"
        )

        llm = _build_llm()
        response = llm.invoke(prompt)
        return 1.0 if "yes" in response.content.lower() else 0.0

    def _judge_relevance(self, question: str, answer: str) -> float:
        """Judge whether the answer directly addresses the question."""
        from app.agents.graph import _build_llm

        prompt = (
            "你是一个评估器。给定一个问题和一个回答，判断回答是否直接回应了问题。\n\n"
            f"### 问题:\n{question}\n\n"
            f"### 回答:\n{answer}\n\n"
            "回答是否直接回应了问题？只回答 'yes' 或 'no'。"
        )

        llm = _build_llm()
        response = llm.invoke(prompt)
        return 1.0 if "yes" in response.content.lower() else 0.0


# ═══════════════════════════════════════════════════════════════════════════════
#  Question-set persistence
# ═══════════════════════════════════════════════════════════════════════════════

class QuestionSetManager:
    """Load / save evaluation question sets from JSON."""

    @staticmethod
    def load(path: str) -> list[EvaluationQuestion]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("questions", [])
        return [EvaluationQuestion(**item) for item in items]

    @staticmethod
    def save(questions: list[EvaluationQuestion], path: str):
        data = {"questions": [asdict(q) for q in questions]}
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
