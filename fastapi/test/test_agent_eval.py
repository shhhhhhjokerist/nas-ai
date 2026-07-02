"""Tests for the agent evaluation engine — dataclasses, persistence,
metrics extraction, success checks, and full evaluator flow.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from app.services.agent_evaluator import (
    AgentEvaluationQuestion,
    AgentEvaluator,
    AgentEvaluationResult,
    AgentMetrics,
    AgentQuestionSetManager,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _make_ai_message(content: str, token_usage=None, tool_calls=None,
                     response_metadata=None):
    """Build a mock AIMessage for testing metrics extraction."""
    from langchain_core.messages import AIMessage

    meta = response_metadata or {}
    if token_usage:
        meta["token_usage"] = token_usage
    kwargs = {"content": content, "response_metadata": meta}
    if tool_calls is not None:
        kwargs["tool_calls"] = tool_calls
    return AIMessage(**kwargs)


def _make_tool_message(content="{}", tool_call_id="tc1"):
    """Build a mock ToolMessage."""
    from langchain_core.messages import ToolMessage
    return ToolMessage(content=content, tool_call_id=tool_call_id)


# ═══════════════════════════════════════════════════════════════════════════════
#  Test 1 — Dataclass defaults and serialization
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentMetricsDataclasses(unittest.TestCase):
    """Unit tests for data model defaults and to_dict()."""

    def test_agent_metrics_defaults(self):
        m = AgentMetrics()
        self.assertEqual(m.latency_ms, 0.0)
        self.assertEqual(m.prompt_tokens, 0)
        self.assertEqual(m.completion_tokens, 0)
        self.assertEqual(m.total_tokens, 0)
        self.assertEqual(m.tool_calls_count, 0)
        self.assertEqual(m.tools_used, [])
        self.assertEqual(m.llm_calls_count, 0)

    def test_agent_metrics_to_dict(self):
        m = AgentMetrics(
            latency_ms=123.45,
            prompt_tokens=500,
            completion_tokens=150,
            total_tokens=650,
            tool_calls_count=2,
            tools_used=["search_files_tool"],
            llm_calls_count=3,
        )
        d = m.to_dict()
        self.assertEqual(d["latency_ms"], 123.45)
        self.assertEqual(d["prompt_tokens"], 500)
        self.assertEqual(d["completion_tokens"], 150)
        self.assertEqual(d["total_tokens"], 650)
        self.assertEqual(d["tool_calls_count"], 2)
        self.assertEqual(d["tools_used"], ["search_files_tool"])
        self.assertEqual(d["llm_calls_count"], 3)

    def test_agent_eval_question_defaults(self):
        q = AgentEvaluationQuestion(id="q1", question="Hello?")
        self.assertEqual(q.id, "q1")
        self.assertEqual(q.question, "Hello?")
        self.assertIsNone(q.expected_action)
        self.assertIsNone(q.expected_tools)
        self.assertIsNone(q.expected_data_fields)
        self.assertIsNone(q.expected_response_keywords)
        self.assertEqual(q.description, "")

    def test_agent_eval_question_with_expectations(self):
        q = AgentEvaluationQuestion(
            id="q2",
            question="Find file X",
            expected_action="file_info",
            expected_tools=["get_file_info_tool"],
            expected_data_fields=["file"],
            description="File info test",
        )
        self.assertEqual(q.expected_action, "file_info")
        self.assertEqual(q.expected_tools, ["get_file_info_tool"])

    def test_agent_eval_result_to_dict(self):
        result = AgentEvaluationResult(
            per_question=[
                {"question_id": "q1", "checks": {"success": True}},
            ],
            aggregate={"success_rate": 1.0, "total_questions": 1},
            config={"agent_model": "test"},
        )
        d = result.to_dict()
        self.assertEqual(d["aggregate"]["success_rate"], 1.0)
        self.assertEqual(len(d["per_question"]), 1)
        self.assertIn("timestamp", d)


# ═══════════════════════════════════════════════════════════════════════════════
#  Test 2 — QuestionSetManager persistence
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentQuestionSetManager(unittest.TestCase):
    """Unit tests for AgentQuestionSetManager save/load."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        path = os.path.join(self.tmpdir, "agent_questions.json")
        questions = [
            AgentEvaluationQuestion(
                id="aq1",
                question="Find file X?",
                expected_action="file_info",
                expected_tools=["get_file_info_tool"],
                expected_data_fields=["file", "urls"],
                description="File info",
            ),
            AgentEvaluationQuestion(
                id="aq2",
                question="Hello?",
                description="Chat only — no tools",
            ),
        ]
        AgentQuestionSetManager.save(questions, path)
        self.assertTrue(os.path.exists(path))

        loaded = AgentQuestionSetManager.load(path)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].id, "aq1")
        self.assertEqual(loaded[0].expected_action, "file_info")
        self.assertEqual(loaded[0].expected_tools, ["get_file_info_tool"])
        self.assertEqual(loaded[1].id, "aq2")
        self.assertIsNone(loaded[1].expected_action)

    def test_load_empty_array(self):
        path = os.path.join(self.tmpdir, "empty.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)
        loaded = AgentQuestionSetManager.load(path)
        self.assertEqual(loaded, [])

    def test_load_with_questions_key(self):
        path = os.path.join(self.tmpdir, "wrapped.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "questions": [
                        {
                            "id": "aq1",
                            "question": "Test?",
                            "expected_action": "chat",
                            "description": "Chat test",
                        }
                    ]
                },
                f,
                ensure_ascii=False,
            )
        loaded = AgentQuestionSetManager.load(path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].id, "aq1")
        self.assertEqual(loaded[0].expected_action, "chat")

    def test_load_with_missing_optionals(self):
        """Questions without expected_* fields should load with None defaults."""
        path = os.path.join(self.tmpdir, "minimal.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"questions": [{"id": "q1", "question": "What?"}]},
                f,
            )
        loaded = AgentQuestionSetManager.load(path)
        self.assertEqual(len(loaded), 1)
        self.assertIsNone(loaded[0].expected_action)
        self.assertIsNone(loaded[0].expected_tools)


# ═══════════════════════════════════════════════════════════════════════════════
#  Test 3 — Metrics extraction static methods
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentMetricsExtraction(unittest.TestCase):
    """Unit tests for _extract_token_usage, _count_tool_calls, _count_llm_calls."""

    def test_extract_token_usage_with_usage(self):
        msg = _make_ai_message(
            content="hello",
            token_usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )
        result = AgentEvaluator._extract_token_usage([msg])
        self.assertEqual(result["prompt_tokens"], 100)
        self.assertEqual(result["completion_tokens"], 50)
        self.assertEqual(result["total_tokens"], 150)

    def test_extract_token_usage_without_usage(self):
        """Graceful degradation when token_usage is absent."""
        msg = _make_ai_message(content="hello")
        result = AgentEvaluator._extract_token_usage([msg])
        self.assertEqual(result["prompt_tokens"], 0)
        self.assertEqual(result["completion_tokens"], 0)
        self.assertEqual(result["total_tokens"], 0)

    def test_extract_token_usage_multiple_llm_calls(self):
        """Tokens should be summed across all AIMessages."""
        msg1 = _make_ai_message(
            content="first",
            token_usage={"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
        )
        msg2 = _make_ai_message(
            content="second",
            token_usage={"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100},
        )
        result = AgentEvaluator._extract_token_usage([msg1, msg2])
        self.assertEqual(result["prompt_tokens"], 180)
        self.assertEqual(result["completion_tokens"], 50)
        self.assertEqual(result["total_tokens"], 230)

    def test_count_tool_calls_with_tools(self):
        """AIMessage with tool_calls + corresponding ToolMessages."""
        messages = [
            _make_ai_message(
                content="",
                tool_calls=[{"name": "search_files_tool", "args": {}, "id": "tc1"}],
            ),
            _make_tool_message(tool_call_id="tc1"),
            _make_ai_message(content='{"response": "done"}'),
        ]
        count, tools_used = AgentEvaluator._count_tool_calls(messages)
        self.assertEqual(count, 1)
        self.assertEqual(tools_used, ["search_files_tool"])

    def test_count_tool_calls_multiple_tools(self):
        """Multiple distinct tools in one conversation."""
        messages = [
            _make_ai_message(
                content="",
                tool_calls=[
                    {"name": "search_files_tool", "args": {}, "id": "tc1"},
                    {"name": "get_file_info_tool", "args": {}, "id": "tc2"},
                ],
            ),
            _make_tool_message(tool_call_id="tc1"),
            _make_tool_message(tool_call_id="tc2"),
        ]
        count, tools_used = AgentEvaluator._count_tool_calls(messages)
        self.assertEqual(count, 2)
        self.assertEqual(set(tools_used), {"get_file_info_tool", "search_files_tool"})

    def test_count_tool_calls_no_tools(self):
        """Pure chat with no tool calls."""
        messages = [
            _make_ai_message(content='{"response": "Hello!", "action": "chat"}'),
        ]
        count, tools_used = AgentEvaluator._count_tool_calls(messages)
        self.assertEqual(count, 0)
        self.assertEqual(tools_used, [])

    def test_count_llm_calls(self):
        messages = [
            _make_ai_message(content="call 1", tool_calls=[{"name": "t1", "args": {}, "id": "x"}]),
            _make_tool_message(tool_call_id="x"),
            _make_ai_message(content="call 2"),
        ]
        self.assertEqual(AgentEvaluator._count_llm_calls(messages), 2)

    def test_count_llm_calls_single(self):
        messages = [_make_ai_message(content="only one")]
        self.assertEqual(AgentEvaluator._count_llm_calls(messages), 1)

    def test_non_dict_message_ignored_in_token_extraction(self):
        """Messages without response_metadata are safely skipped."""
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content="system prompt"),
            HumanMessage(content="user question"),
            _make_ai_message(
                content="answer",
                token_usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
            ),
        ]
        result = AgentEvaluator._extract_token_usage(messages)
        self.assertEqual(result["total_tokens"], 60)


# ═══════════════════════════════════════════════════════════════════════════════
#  Test 4 — Success evaluation logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentSuccessEvaluation(unittest.TestCase):
    """Unit tests for _evaluate_success — pure logic, no I/O."""

    def test_action_match(self):
        q = AgentEvaluationQuestion(id="q1", question="?", expected_action="play")
        checks = AgentEvaluator._evaluate_success(
            q, {"action": "play", "response": "here"}, []
        )
        self.assertTrue(checks["action_match"])
        self.assertTrue(checks["success"])

    def test_action_mismatch(self):
        q = AgentEvaluationQuestion(id="q1", question="?", expected_action="play")
        checks = AgentEvaluator._evaluate_success(
            q, {"action": "search", "response": "here"}, []
        )
        self.assertFalse(checks["action_match"])
        self.assertFalse(checks["success"])

    def test_tools_subset_match(self):
        """expected_tools subset of actual → pass (agent used expected + extra)."""
        q = AgentEvaluationQuestion(
            id="q1", question="?",
            expected_tools=["get_file_info_tool"],
        )
        checks = AgentEvaluator._evaluate_success(
            q, {}, ["get_file_info_tool"]
        )
        self.assertTrue(checks["tools_match"])
        self.assertTrue(checks["success"])

    def test_tools_subset_with_fallback(self):
        """Agent uses expected tool + fallback search → still pass."""
        q = AgentEvaluationQuestion(
            id="q1", question="?",
            expected_tools=["get_file_info_tool"],
        )
        checks = AgentEvaluator._evaluate_success(
            q, {}, ["get_file_info_tool", "search_files_tool"]
        )
        self.assertTrue(checks["tools_match"])
        self.assertTrue(checks["success"])

    def test_tools_mismatch(self):
        """Expected tool not used at all → fail."""
        q = AgentEvaluationQuestion(
            id="q1", question="?",
            expected_tools=["get_file_info_tool"],
        )
        checks = AgentEvaluator._evaluate_success(
            q, {}, ["search_files_tool"]
        )
        self.assertFalse(checks["tools_match"])

    def test_tools_empty_expected_no_tools_used(self):
        """expected_tools=[] means NO tools should be called."""
        q = AgentEvaluationQuestion(id="q1", question="?", expected_tools=[])
        checks = AgentEvaluator._evaluate_success(q, {}, [])
        self.assertTrue(checks["tools_match"])
        self.assertTrue(checks["success"])

    def test_tools_empty_expected_but_tools_used(self):
        """expected_tools=[] but agent called a tool anyway → fail."""
        q = AgentEvaluationQuestion(id="q1", question="?", expected_tools=[])
        checks = AgentEvaluator._evaluate_success(
            q, {}, ["search_files_tool"]
        )
        self.assertFalse(checks["tools_match"])

    def test_data_fields_subset(self):
        """expected_data_fields should be a subset of actual data keys."""
        q = AgentEvaluationQuestion(
            id="q1", question="?",
            expected_data_fields=["file", "urls"],
        )
        checks = AgentEvaluator._evaluate_success(
            q, {"data": {"file": {}, "urls": {}, "extra": 1}}, []
        )
        self.assertTrue(checks["data_fields_match"])

    def test_data_fields_missing(self):
        q = AgentEvaluationQuestion(
            id="q1", question="?",
            expected_data_fields=["file", "urls"],
        )
        checks = AgentEvaluator._evaluate_success(
            q, {"data": {"file": {}}}, []
        )
        self.assertFalse(checks["data_fields_match"])

    def test_data_fields_null_data(self):
        """When data is None, no fields can match."""
        q = AgentEvaluationQuestion(
            id="q1", question="?",
            expected_data_fields=["file"],
        )
        checks = AgentEvaluator._evaluate_success(
            q, {}, []
        )
        self.assertFalse(checks["data_fields_match"])

    def test_keywords_all_match(self):
        q = AgentEvaluationQuestion(
            id="q1", question="?",
            expected_response_keywords=["找到", "成功"],
        )
        checks = AgentEvaluator._evaluate_success(
            q, {"response": "已找到文件，操作成功"}, []
        )
        self.assertTrue(checks["keywords_match"])

    def test_keywords_partial_match(self):
        q = AgentEvaluationQuestion(
            id="q1", question="?",
            expected_response_keywords=["找到", "成功"],
        )
        checks = AgentEvaluator._evaluate_success(
            q, {"response": "找到了文件"}, []
        )
        self.assertFalse(checks["keywords_match"])

    def test_no_expectations(self):
        """Question with no expected_* fields → success=True (vacuously true)."""
        q = AgentEvaluationQuestion(id="q1", question="?")
        checks = AgentEvaluator._evaluate_success(q, {}, [])
        self.assertTrue(checks["success"])
        self.assertEqual(len(checks), 1)  # only "success" key

    def test_combined_checks(self):
        """Multiple checks — all must pass for overall success."""
        q = AgentEvaluationQuestion(
            id="q1",
            question="?",
            expected_action="search",
            expected_tools=["search_files_tool"],
            expected_data_fields=["results"],
        )
        # All pass
        checks = AgentEvaluator._evaluate_success(
            q,
            {"action": "search", "data": {"results": [], "keyword": "x"}},
            ["search_files_tool"],
        )
        self.assertTrue(checks["action_match"])
        self.assertTrue(checks["tools_match"])
        self.assertTrue(checks["data_fields_match"])
        self.assertTrue(checks["success"])

        # One fails
        checks2 = AgentEvaluator._evaluate_success(
            q,
            {"action": "wrong"},
            ["search_files_tool"],
        )
        self.assertFalse(checks2["success"])


# ═══════════════════════════════════════════════════════════════════════════════
#  Test 5 — AgentEvaluator full flow (mocked graph)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentEvaluatorFullFlow(unittest.TestCase):
    """Tests for AgentEvaluator.run() with a mocked agent_graph."""

    def _build_mock_state(self, content, token_usage=None, tool_calls=None):
        """Build a synthetic LangGraph result dict."""
        ai_msg = _make_ai_message(
            content=content,
            token_usage=token_usage,
            tool_calls=tool_calls,
        )
        messages = [ai_msg]
        if tool_calls:
            for tc in tool_calls:
                messages.append(
                    _make_tool_message(tool_call_id=tc.get("id", "tc_x"))
                )
            # Add a final AI message after tools
            messages.append(
                _make_ai_message(
                    content=content,
                    token_usage=token_usage,
                )
            )
        return {"messages": messages}

    def test_single_question_success(self):
        """One question, everything matches → success=True."""
        q = AgentEvaluationQuestion(
            id="aq1",
            question="Find README",
            expected_action="file_info",
            expected_tools=["get_file_info_tool"],
            expected_data_fields=["file", "urls"],
        )

        state = self._build_mock_state(
            content=json.dumps({
                "response": "找到文件 README",
                "action": "file_info",
                "data": {"file": {"name": "README"}, "urls": {}},
            }),
            token_usage={"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
            tool_calls=[{"name": "get_file_info_tool", "args": {"name": "README"}, "id": "tc1"}],
        )

        with mock.patch(
            "app.agents.graph.agent_graph.ainvoke",
            new=mock.AsyncMock(return_value=state),
        ):
            evaluator = AgentEvaluator([q])
            result = evaluator.run()
            # Need to run async
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(result)

        self.assertEqual(len(result.per_question), 1)
        pq = result.per_question[0]
        self.assertEqual(pq["question_id"], "aq1")
        self.assertEqual(pq["action"], "file_info")
        self.assertEqual(pq["tools_used"], ["get_file_info_tool"])
        self.assertTrue(pq["checks"]["success"])
        self.assertTrue(pq["checks"]["action_match"])
        self.assertTrue(pq["checks"]["tools_match"])
        self.assertTrue(pq["checks"]["data_fields_match"])
        self.assertEqual(pq["metrics"]["prompt_tokens"], 200)  # 2 AI msgs × 100
        self.assertEqual(pq["metrics"]["completion_tokens"], 60)  # 2 × 30
        self.assertEqual(pq["metrics"]["tool_calls_count"], 1)
        self.assertEqual(pq["metrics"]["llm_calls_count"], 2)

    def test_aggregate_computes_correctly(self):
        """Two questions — verify summary statistics."""
        q1 = AgentEvaluationQuestion(id="aq1", question="Q1?", expected_action="chat")
        q2 = AgentEvaluationQuestion(id="aq2", question="Q2?", expected_action="search")

        state_ok = self._build_mock_state(
            content=json.dumps({"response": "ok", "action": "chat"}),
            token_usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        )
        state_fail = self._build_mock_state(
            content=json.dumps({"response": "fail", "action": "chat"}),  # wrong action
            token_usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )

        mock_graph = mock.AsyncMock(side_effect=[state_ok, state_fail])

        with mock.patch("app.agents.graph.agent_graph.ainvoke", new=mock_graph):
            evaluator = AgentEvaluator([q1, q2])
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(evaluator.run())

        agg = result.aggregate
        self.assertEqual(agg["total_questions"], 2)
        self.assertEqual(agg["success_rate"], 0.5)
        self.assertEqual(agg["avg_total_tokens"], 90.0)  # (60 + 120) / 2
        self.assertGreater(agg["avg_latency_ms"], 0)

    def test_graph_exception_handling(self):
        """When ainvoke raises, the question is marked failed with error info."""
        q = AgentEvaluationQuestion(id="aq1", question="Q?")

        with mock.patch(
            "app.agents.graph.agent_graph.ainvoke",
            new=mock.AsyncMock(side_effect=RuntimeError("LLM timeout")),
        ):
            evaluator = AgentEvaluator([q])
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(evaluator.run())

        pq = result.per_question[0]
        self.assertFalse(pq["checks"]["success"])
        self.assertEqual(pq["checks"]["error"], "LLM timeout")
        self.assertEqual(pq["error"], "LLM timeout")
        # Metrics should still have latency (time until exception)
        self.assertGreater(pq["metrics"]["latency_ms"], 0)

    def test_graph_returns_non_json_content(self):
        """When the LLM returns plain text (not JSON), graceful handling."""
        q = AgentEvaluationQuestion(
            id="aq1", question="Q?", expected_action="chat"
        )

        state = self._build_mock_state(
            content="Just plain text, no JSON at all",
            token_usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        )

        with mock.patch(
            "app.agents.graph.agent_graph.ainvoke",
            new=mock.AsyncMock(return_value=state),
        ):
            evaluator = AgentEvaluator([q])
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(evaluator.run())

        pq = result.per_question[0]
        # action defaults to None when JSON can't be parsed
        self.assertIsNone(pq["action"])
        # expected_action was "chat" but actual is None → action_match fails
        self.assertFalse(pq["checks"]["success"])
        # But metrics are still captured
        self.assertEqual(pq["metrics"]["total_tokens"], 25)


if __name__ == "__main__":
    unittest.main()
