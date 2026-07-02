#!/usr/bin/env python3
"""Standalone RAG + Agent evaluation — no FastAPI server needed.

Usage::

    cd fastapi

    # RAG evaluation
    python evaluation/run_eval.py --mode rag

    # Agent evaluation (calls agent_graph directly, no server needed)
    python evaluation/run_eval.py --mode agent

    # Both
    python evaluation/run_eval.py --mode all

    # Custom options
    python evaluation/run_eval.py --mode agent --agent-questions evaluation/my_questions.json
    python evaluation/run_eval.py --mode rag --top-k 10 --output results/custom.json

Directory layout expected::

    evaluation/
        docs/                          # <-- put eval documents here (for RAG eval)
        sample_questions.json          # RAG eval questions
        sample_agent_questions.json    # Agent eval questions
        chroma_db/                     # auto-built eval vector DB
        results/                       # saved reports
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Ensure the fastapi/ dir is on sys.path so that `from app.xxx` works.
_HERE = Path(__file__).resolve().parent
_FASTAPI_DIR = _HERE.parent
sys.path.insert(0, str(_FASTAPI_DIR))

# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RAG + Agent Evaluation")
    p.add_argument(
        "--mode",
        choices=("rag", "agent", "all"),
        default="agent",
        help="Evaluation mode (default: agent)",
    )
    p.add_argument(
        "--questions",
        default=None,
        help="Path to RAG question JSON (default: evaluation/sample_questions.json)",
    )
    p.add_argument(
        "--agent-questions",
        default=None,
        help="Path to Agent question JSON (default: evaluation/sample_agent_questions.json)",
    )
    p.add_argument(
        "--top-k", type=int, default=5, help="Chunks per query (default: 5)"
    )
    p.add_argument(
        "--output",
        default=None,
        help="Save full report to JSON (default: auto-generated under results/)",
    )
    p.add_argument(
        "--no-build",
        action="store_true",
        help="Skip auto-building the eval vector index",
    )
    return p.parse_args()


# ═══════════════════════════════════════════════════════════════════════════════
#  Eval index builder (standalone — no app SQLAlchemy needed)
# ═══════════════════════════════════════════════════════════════════════════════

_EVAL_CHROMA_DIR = _HERE / "chroma_db"
_EVAL_DOCS_DIR = _HERE / "docs"


def _build_eval_index(docs_dir: Path | None = None, force: bool = False) -> int:
    """Index all docs in *docs_dir* into the eval ChromaDB.

    Returns the number of chunks created (0 if already built).
    """
    from app.services.vector_store import VectorStore
    from app.services.embedding_service import get_embedding_service
    from app.services.document_parser import SUPPORTED_EXTENSIONS, parse_file
    from app.services.chunker import chunk_text
    from app.config import Config

    docs = docs_dir or _EVAL_DOCS_DIR
    if not docs.exists():
        print(f"[skip] Docs directory not found: {docs}")
        return 0

    store = VectorStore(str(_EVAL_CHROMA_DIR), collection_name="eval_documents")

    if not force and store.count() > 0:
        print(f"[skip] Eval vector DB already has {store.count()} chunks.  Use --no-build to skip.")
        return 0

    print(f"Building eval index from: {docs}")
    emb = get_embedding_service()

    # Gather files
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(docs):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append(Path(dirpath) / f)

    if not files:
        print("[warn] No supported documents found in evaluation/docs/")
        print("       Put 10 PDF/Word/txt/md files there as your eval dataset.")
        return 0

    print(f"Found {len(files)} document(s)")

    total_chunks = 0
    for fp in files:
        try:
            text, meta = parse_file(str(fp))
            if not text.strip():
                print(f"  [warn] {fp.name}: no readable text, skipped")
                continue
            chunks = chunk_text(text, Config.CHUNK_SIZE, Config.CHUNK_OVERLAP)
            if not chunks:
                continue
            embeddings = emb.embed(chunks)
            metadatas = [
                {
                    "file_path": str(fp.resolve()),
                    "file_name": meta["file_name"],
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                }
                for i in range(len(chunks))
            ]
            store.add(texts=chunks, embeddings=embeddings, metadatas=metadatas)
            total_chunks += len(chunks)
            print(f"  [ok] {fp.name}: {len(chunks)} chunks")
        except Exception as exc:
            print(f"  [fail] {fp.name}: {exc}")

    print(f"Indexed {total_chunks} chunks total.")
    return total_chunks


# ═══════════════════════════════════════════════════════════════════════════════
#  RAG evaluation
# ═══════════════════════════════════════════════════════════════════════════════


def _rag_eval(questions_path: str, top_k: int) -> dict:
    """Run retrieval + generation evaluation."""
    from app.services.evaluator import Evaluator, QuestionSetManager
    from app.services.retrieval_service import RetrievalService
    from app.services.rag_service import RAGService

    # Point RetrievalService at the eval ChromaDB, not the app's
    from app.services.vector_store import VectorStore
    eval_store = VectorStore(str(_EVAL_CHROMA_DIR), collection_name="eval_documents")
    retrieval = RetrievalService(vector_store=eval_store)
    rag = RAGService(retrieval_service=retrieval)

    questions = QuestionSetManager.load(questions_path)
    print(f"Loaded {len(questions)} RAG questions from {questions_path}")

    evaluator = Evaluator(questions, retrieval_service=retrieval, rag_service=rag)
    result = evaluator.run(top_k=top_k)
    return result.to_dict()


# ═══════════════════════════════════════════════════════════════════════════════
#  Agent evaluation  (standalone — calls agent_graph directly)
# ═══════════════════════════════════════════════════════════════════════════════


def _agent_eval(questions_path: str) -> dict:
    """Run agent evaluation by calling the LangGraph agent directly.

    No FastAPI server required — the evaluator imports ``agent_graph`` and
    calls ``ainvoke``, then extracts token usage, tool calls, latency, and
    success checks from the returned state.
    """
    import asyncio

    from app.services.agent_evaluator import (
        AgentEvaluator,
        AgentQuestionSetManager,
    )

    questions = AgentQuestionSetManager.load(questions_path)
    print(f"Loaded {len(questions)} Agent questions from {questions_path}")

    evaluator = AgentEvaluator(questions)
    result = asyncio.run(evaluator.run())
    return result.to_dict()


# ═══════════════════════════════════════════════════════════════════════════════
#  Report helper
# ═══════════════════════════════════════════════════════════════════════════════


def _save_report(report: dict, output_path: str | None, tag: str = "eval") -> str:
    if output_path:
        path = output_path
    else:
        results_dir = _HERE / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        path = str(results_dir / f"{tag}_{time.strftime('%Y%m%d_%H%M%S')}.json")

    report.setdefault("timestamp", time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    args = parse_args()

    rag_questions_path = args.questions or str(_HERE / "sample_questions.json")
    agent_questions_path = args.agent_questions or str(
        _HERE / "sample_agent_questions.json"
    )

    # ── RAG evaluation ────────────────────────────────────────────────────
    if args.mode in ("rag", "all"):
        # 1. Build eval index (if needed)
        if not args.no_build:
            _build_eval_index()

        # 2. Run RAG eval
        if not Path(rag_questions_path).exists():
            print(f"[ERROR] RAG questions file not found: {rag_questions_path}")
        else:
            t0 = time.time()
            report = _rag_eval(rag_questions_path, args.top_k)
            elapsed = time.time() - t0

            # Print summary
            r = report["retrieval"]
            g = report["generation"]
            print()
            print("=" * 60)
            print("  RAG EVALUATION RESULTS")
            print("=" * 60)
            print(f"  Questions : {report['config'].get('num_questions', '?')}")
            print(f"  Elapsed   : {elapsed:.1f}s")
            print()
            print("  ── Retrieval ──")
            print(f"  Hit Rate       : {r['hit_rate']:.2%}")
            print(f"  MRR            : {r['mrr']:.4f}")
            print(f"  Precision@{args.top_k}  : {r['precision_at_k']:.4f}")
            print(f"  Recall@{args.top_k}     : {r['recall_at_k']:.4f}")
            print()
            print("  ── Generation (LLM Judge) ──")
            print(f"  Faithfulness   : {g['faithfulness']:.2%}")
            print(f"  Relevance      : {g['relevance']:.2%}")
            print()
            print("  ── Config ──")
            for k, v in report["config"].items():
                print(f"  {k:.<35s} {v}")
            print("=" * 60)

            # Per-question detail
            print()
            for qr in report.get("per_question", []):
                mark = "✓" if qr.get("hit") else "✗"
                print(f"  [{qr['question_id']}] {mark}  {qr['question'][:60]}")
                print(f"       answer: {qr['answer'][:120]}")
                print(f"       sources: {', '.join(qr.get('sources', []))}")
                if qr.get("reciprocal_rank") is not None:
                    print(
                        f"       RR: {qr['reciprocal_rank']:.4f}  "
                        f"faith: {qr['faithfulness']}  relev: {qr['relevance']}"
                    )
                print()

            report["elapsed_seconds"] = round(elapsed, 1)
            path = _save_report(report, args.output, tag="rag")
            print(f"RAG report saved to: {path}")

    # ── Agent evaluation ──────────────────────────────────────────────────
    if args.mode in ("agent", "all"):
        if not Path(agent_questions_path).exists():
            print(f"[ERROR] Agent questions file not found: {agent_questions_path}")
        else:
            print()
            print("=" * 60)
            print("  AGENT EVALUATION RESULTS")
            print("=" * 60)

            t0 = time.time()
            report = _agent_eval(agent_questions_path)
            elapsed = time.time() - t0

            agg = report.get("aggregate", {})
            cfg = report.get("config", {})

            print(f"  Questions    : {agg.get('total_questions', '?')}")
            print(f"  Model        : {cfg.get('agent_model', '?')}")
            print(f"  Elapsed      : {elapsed:.1f}s")
            print()
            print("  ── Success ──")
            print(f"  Success Rate  : {agg.get('success_rate', 0):.2%}")
            print()
            print("  ── Latency ──")
            print(f"  Avg           : {agg.get('avg_latency_ms', 0):.0f} ms")
            print(f"  Min / Max     : {agg.get('min_latency_ms', 0):.0f} / {agg.get('max_latency_ms', 0):.0f} ms")
            print()
            print("  ── Token Usage (avg per question) ──")
            print(f"  Prompt        : {agg.get('avg_prompt_tokens', 0):.0f}")
            print(f"  Completion    : {agg.get('avg_completion_tokens', 0):.0f}")
            print(f"  Total         : {agg.get('avg_total_tokens', 0):.0f}")
            print()
            print("  ── Tool Calls ──")
            print(f"  Avg / question: {agg.get('avg_tool_calls_per_question', 0):.2f}")
            tool_dist = agg.get("tool_usage_distribution", {})
            if tool_dist:
                for tool, count in sorted(tool_dist.items(), key=lambda x: -x[1]):
                    print(f"  {tool:<35s} {count}")
            print("=" * 60)

            # Per-question detail
            print()
            for pq in report.get("per_question", []):
                checks = pq.get("checks", {})
                success = "✓" if checks.get("success") else "✗"
                m = pq.get("metrics", {})
                print(f"  [{pq['question_id']}] {success}  {pq['question'][:60]}")
                print(f"       action: {pq.get('action', '?')}  "
                      f"tools: {pq.get('tools_used', [])}  "
                      f"tokens: {m.get('total_tokens', 0)}  "
                      f"latency: {m.get('latency_ms', 0):.0f}ms")
                if not checks.get("success"):
                    for k, v in checks.items():
                        if k != "success" and not v:
                            print(f"       ✗ {k}")
                print()

            report["elapsed_seconds"] = round(elapsed, 1)
            path = _save_report(report, args.output, tag="agent")
            print(f"Agent report saved to: {path}")


if __name__ == "__main__":
    main()
