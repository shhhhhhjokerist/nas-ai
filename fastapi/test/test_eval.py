"""Tests for the evaluation engine (dataclasses + question-set manager)."""

import json
import os
import tempfile
import unittest

from app.services.evaluator import (
    EvaluationQuestion,
    EvaluationResult,
    GenerationMetrics,
    QuestionSetManager,
    RetrievalMetrics,
)


class TestMetricsDataclasses(unittest.TestCase):
    def test_retrieval_metrics_defaults(self):
        m = RetrievalMetrics()
        self.assertEqual(m.hit_rate, 0.0)
        self.assertEqual(m.mrr, 0.0)

    def test_retrieval_metrics_to_dict(self):
        m = RetrievalMetrics(hit_rate=0.8, mrr=0.6)
        d = m.to_dict()
        self.assertEqual(d["hit_rate"], 0.8)
        self.assertEqual(d["mrr"], 0.6)

    def test_generation_metrics_to_dict(self):
        m = GenerationMetrics(faithfulness=0.9, relevance=0.7)
        d = m.to_dict()
        self.assertEqual(d["faithfulness"], 0.9)
        self.assertEqual(d["relevance"], 0.7)

    def test_evaluation_result_to_dict(self):
        result = EvaluationResult(
            retrieval=RetrievalMetrics(hit_rate=0.75),
            generation=GenerationMetrics(faithfulness=0.8, relevance=0.9),
            per_question=[
                {"question_id": "q1", "hit": True, "faithfulness": 1.0}
            ],
            config={"top_k": 5},
        )
        d = result.to_dict()
        self.assertEqual(d["retrieval"]["hit_rate"], 0.75)
        self.assertEqual(d["generation"]["faithfulness"], 0.8)
        self.assertEqual(len(d["per_question"]), 1)


class TestQuestionSetManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        path = os.path.join(self.tmpdir, "questions.json")
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
        self.assertTrue(os.path.exists(path))

        loaded = QuestionSetManager.load(path)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].id, "q1")
        self.assertEqual(loaded[0].question, "What is AI?")
        self.assertEqual(loaded[0].relevant_file, "ai_intro.pdf")
        self.assertEqual(loaded[1].id, "q2")

    def test_load_empty_array(self):
        path = os.path.join(self.tmpdir, "empty.json")
        with open(path, "w") as f:
            json.dump([], f)
        loaded = QuestionSetManager.load(path)
        self.assertEqual(loaded, [])

    def test_load_with_questions_key(self):
        path = os.path.join(self.tmpdir, "wrapped.json")
        with open(path, "w") as f:
            json.dump(
                {"questions": [{"id": "q1", "question": "Test?"}]}, f
            )
        loaded = QuestionSetManager.load(path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].id, "q1")


if __name__ == "__main__":
    unittest.main()
