"""Tests for evaluator.py — metrics dataclasses + QuestionSetManager."""
import json
import os
import tempfile

import pytest

from app.services.evaluator import (
    EvaluationQuestion,
    EvaluationResult,
    GenerationMetrics,
    QuestionSetManager,
    RetrievalMetrics,
)


class TestRetrievalMetrics:
    def test_defaults(self):
        m = RetrievalMetrics()
        assert m.hit_rate == 0.0
        assert m.mrr == 0.0

    def test_to_dict(self):
        m = RetrievalMetrics(hit_rate=0.8, mrr=0.6)
        d = m.to_dict()
        assert d["hit_rate"] == 0.8
        assert d["mrr"] == 0.6


class TestGenerationMetrics:
    def test_to_dict(self):
        m = GenerationMetrics(faithfulness=0.9, relevance=0.7)
        d = m.to_dict()
        assert d["faithfulness"] == 0.9
        assert d["relevance"] == 0.7


class TestEvaluationResult:
    def test_to_dict(self):
        result = EvaluationResult(
            retrieval=RetrievalMetrics(hit_rate=0.75),
            generation=GenerationMetrics(faithfulness=0.8, relevance=0.9),
            per_question=[{"question_id": "q1", "hit": True, "faithfulness": 1.0}],
            config={"top_k": 5},
        )
        d = result.to_dict()
        assert d["retrieval"]["hit_rate"] == 0.75
        assert d["generation"]["faithfulness"] == 0.8
        assert len(d["per_question"]) == 1


class TestQuestionSetManager:
    @pytest.fixture
    def tmpdir(self):
        d = tempfile.mkdtemp()
        yield d
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    def test_save_and_load(self, tmpdir):
        path = os.path.join(tmpdir, "questions.json")
        questions = [
            EvaluationQuestion(
                id="q1",
                question="What is AI?",
                expected_answer="Artificial Intelligence",
                relevant_file="ai_intro.pdf",
            ),
            EvaluationQuestion(id="q2", question="What is ML?"),
        ]
        QuestionSetManager.save(questions, path)
        assert os.path.exists(path)

        loaded = QuestionSetManager.load(path)
        assert len(loaded) == 2
        assert loaded[0].id == "q1"
        assert loaded[0].question == "What is AI?"
        assert loaded[0].relevant_file == "ai_intro.pdf"
        assert loaded[1].id == "q2"

    def test_load_empty_array(self, tmpdir):
        path = os.path.join(tmpdir, "empty.json")
        with open(path, "w") as f:
            json.dump([], f)
        loaded = QuestionSetManager.load(path)
        assert loaded == []

    def test_load_with_questions_key(self, tmpdir):
        path = os.path.join(tmpdir, "wrapped.json")
        with open(path, "w") as f:
            json.dump(
                {"questions": [{"id": "q1", "question": "Test?"}]}, f
            )
        loaded = QuestionSetManager.load(path)
        assert len(loaded) == 1
        assert loaded[0].id == "q1"
