"""Tests for agent_evaluator.py — dataclasses, persistence, metrics extraction,
success checks, and full evaluator flow."""
import json
import os
import tempfile
from unittest import mock

import pytest

from app.services.agent_evaluator import (
    AgentEvaluationQuestion,
    AgentEvaluator,
    AgentEvaluationResult,
    AgentMetrics,
    AgentQuestionSetManager,
)


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _make_ai_message(content="", token_usage=None, tool_calls=None, response_metadata=None):
    from langchain_core.messages import AIMessage
    meta = response_metadata or {}
    if token_usage:
        meta["token_usage"] = token_usage
    kwargs = {"content": content, "response_metadata": meta}
    if tool_calls is not None:
        kwargs["tool_calls"] = tool_calls
    return AIMessage(**kwargs)


def _make_tool_message(content="{}", tool_call_id="tc1"):
    from langchain_core.messages import ToolMessage
    return ToolMessage(content=content, tool_call_id=tool_call_id)


def _build_mock_state(content, token_usage=None, tool_calls=None):
    """Build a synthetic LangGraph result dict."""
    ai_msg = _make_ai_message(content=content, token_usage=token_usage, tool_calls=tool_calls)
    messages = [ai_msg]
    if tool_calls:
        for tc in tool_calls:
            messages.append(_make_tool_message(tool_call_id=tc.get("id", "tc_x")))
        messages.append(_make_ai_message(content=content, token_usage=token_usage))
    return {"messages": messages}


# ═══════════════════════════════════════════════════════════════════
#  Test 1 — Dataclass defaults and serialization
# ═══════════════════════════════════════════════════════════════════

class TestAgentMetricsDefaults:
    def test_defaults(self):
        m = AgentMetrics()
        assert m.latency_ms == 0.0
        assert m.prompt_tokens == 0
        assert m.completion_tokens == 0
        assert m.total_tokens == 0
        assert m.tool_calls_count == 0
        assert m.tools_used == []
        assert m.llm_calls_count == 0

    def test_to_dict(self):
        m = AgentMetrics(
            latency_ms=123.45, prompt_tokens=500, completion_tokens=150,
            total_tokens=650, tool_calls_count=2,
            tools_used=["search_files_tool"], llm_calls_count=3,
        )
        d = m.to_dict()
        assert d["latency_ms"] == 123.45
        assert d["prompt_tokens"] == 500
        assert d["completion_tokens"] == 150
        assert d["total_tokens"] == 650
        assert d["tool_calls_count"] == 2
        assert d["tools_used"] == ["search_files_tool"]
        assert d["llm_calls_count"] == 3


class TestAgentEvalQuestion:
    def test_defaults(self):
        q = AgentEvaluationQuestion(id="q1", question="Hello?")
        assert q.id == "q1"
        assert q.question == "Hello?"
        assert q.expected_action is None
        assert q.expected_tools is None
        assert q.expected_data_fields is None
        assert q.expected_response_keywords is None
        assert q.description == ""

    def test_with_expectations(self):
        q = AgentEvaluationQuestion(
            id="q2", question="Find file X",
            expected_action="file_info",
            expected_tools=["get_file_info_tool"],
            expected_data_fields=["file"],
            description="File info test",
        )
        assert q.expected_action == "file_info"
        assert q.expected_tools == ["get_file_info_tool"]


class TestAgentEvalResult:
    def test_to_dict(self):
        result = AgentEvaluationResult(
            per_question=[{"question_id": "q1", "checks": {"success": True}}],
            aggregate={"success_rate": 1.0, "total_questions": 1},
            config={"agent_model": "test"},
        )
        d = result.to_dict()
        assert d["aggregate"]["success_rate"] == 1.0
        assert len(d["per_question"]) == 1
        assert "timestamp" in d


# ═══════════════════════════════════════════════════════════════════
#  Test 2 — QuestionSetManager persistence
# ═══════════════════════════════════════════════════════════════════

class TestAgentQuestionSetManager:
    @pytest.fixture
    def tmpdir(self):
        d = tempfile.mkdtemp()
        yield d
        import shutil
        shutil.rmtree(d, ignore_errors=True)

    def test_save_and_load(self, tmpdir):
        path = os.path.join(tmpdir, "agent_questions.json")
        questions = [
            AgentEvaluationQuestion(
                id="aq1", question="Find file X?", expected_action="file_info",
                expected_tools=["get_file_info_tool"],
                expected_data_fields=["file", "urls"], description="File info",
            ),
            AgentEvaluationQuestion(
                id="aq2", question="Hello?", description="Chat only — no tools",
            ),
        ]
        AgentQuestionSetManager.save(questions, path)
        assert os.path.exists(path)

        loaded = AgentQuestionSetManager.load(path)
        assert len(loaded) == 2
        assert loaded[0].id == "aq1"
        assert loaded[0].expected_action == "file_info"
        assert loaded[0].expected_tools == ["get_file_info_tool"]
        assert loaded[1].id == "aq2"
        assert loaded[1].expected_action is None

    def test_load_empty_array(self, tmpdir):
        path = os.path.join(tmpdir, "empty.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)
        loaded = AgentQuestionSetManager.load(path)
        assert loaded == []

    def test_load_with_questions_key(self, tmpdir):
        path = os.path.join(tmpdir, "wrapped.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "questions": [{
                    "id": "aq1", "question": "Test?",
                    "expected_action": "chat", "description": "Chat test",
                }]
            }, f, ensure_ascii=False)
        loaded = AgentQuestionSetManager.load(path)
        assert len(loaded) == 1
        assert loaded[0].id == "aq1"
        assert loaded[0].expected_action == "chat"

    def test_load_with_missing_optionals(self, tmpdir):
        path = os.path.join(tmpdir, "minimal.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"questions": [{"id": "q1", "question": "What?"}]}, f)
        loaded = AgentQuestionSetManager.load(path)
        assert len(loaded) == 1
        assert loaded[0].expected_action is None
        assert loaded[0].expected_tools is None


# ═══════════════════════════════════════════════════════════════════
#  Test 3 — Metrics extraction
# ═══════════════════════════════════════════════════════════════════

class TestTokenUsageExtraction:
    def test_with_usage(self):
        msg = _make_ai_message(content="hello", token_usage={
            "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150,
        })
        result = AgentEvaluator._extract_token_usage([msg])
        assert result["prompt_tokens"] == 100
        assert result["completion_tokens"] == 50
        assert result["total_tokens"] == 150

    def test_without_usage(self):
        msg = _make_ai_message(content="hello")
        result = AgentEvaluator._extract_token_usage([msg])
        assert result["prompt_tokens"] == 0
        assert result["completion_tokens"] == 0
        assert result["total_tokens"] == 0

    def test_multiple_llm_calls(self):
        msg1 = _make_ai_message(content="first", token_usage={
            "prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130,
        })
        msg2 = _make_ai_message(content="second", token_usage={
            "prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100,
        })
        result = AgentEvaluator._extract_token_usage([msg1, msg2])
        assert result["prompt_tokens"] == 180
        assert result["completion_tokens"] == 50
        assert result["total_tokens"] == 230

    def test_non_dict_message_ignored(self):
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content="system prompt"),
            HumanMessage(content="user question"),
            _make_ai_message(content="answer", token_usage={
                "prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60,
            }),
        ]
        result = AgentEvaluator._extract_token_usage(messages)
        assert result["total_tokens"] == 60


class TestToolCallCounting:
    def test_with_tools(self):
        messages = [
            _make_ai_message(content="", tool_calls=[
                {"name": "search_files_tool", "args": {}, "id": "tc1"},
            ]),
            _make_tool_message(tool_call_id="tc1"),
            _make_ai_message(content='{"response": "done"}'),
        ]
        count, tools_used = AgentEvaluator._count_tool_calls(messages)
        assert count == 1
        assert tools_used == ["search_files_tool"]

    def test_multiple_tools(self):
        messages = [
            _make_ai_message(content="", tool_calls=[
                {"name": "search_files_tool", "args": {}, "id": "tc1"},
                {"name": "get_file_info_tool", "args": {}, "id": "tc2"},
            ]),
            _make_tool_message(tool_call_id="tc1"),
            _make_tool_message(tool_call_id="tc2"),
        ]
        count, tools_used = AgentEvaluator._count_tool_calls(messages)
        assert count == 2
        assert set(tools_used) == {"get_file_info_tool", "search_files_tool"}

    def test_no_tools(self):
        messages = [_make_ai_message(content='{"response": "Hello!", "action": "chat"}')]
        count, tools_used = AgentEvaluator._count_tool_calls(messages)
        assert count == 0
        assert tools_used == []


class TestLLMCallCounting:
    def test_two_calls(self):
        messages = [
            _make_ai_message(content="call 1", tool_calls=[
                {"name": "t1", "args": {}, "id": "x"},
            ]),
            _make_tool_message(tool_call_id="x"),
            _make_ai_message(content="call 2"),
        ]
        assert AgentEvaluator._count_llm_calls(messages) == 2

    def test_single_call(self):
        messages = [_make_ai_message(content="only one")]
        assert AgentEvaluator._count_llm_calls(messages) == 1


# ═══════════════════════════════════════════════════════════════════
#  Test 4 — Success evaluation logic
# ═══════════════════════════════════════════════════════════════════

class TestActionMatch:
    def test_match(self):
        q = AgentEvaluationQuestion(id="q1", question="?", expected_action="play")
        checks = AgentEvaluator._evaluate_success(q, {"action": "play", "response": "here"}, [])
        assert checks["action_match"]
        assert checks["success"]

    def test_mismatch(self):
        q = AgentEvaluationQuestion(id="q1", question="?", expected_action="play")
        checks = AgentEvaluator._evaluate_success(q, {"action": "search", "response": "here"}, [])
        assert not checks["action_match"]
        assert not checks["success"]


class TestToolsMatch:
    def test_subset_match(self):
        q = AgentEvaluationQuestion(id="q1", question="?", expected_tools=["get_file_info_tool"])
        checks = AgentEvaluator._evaluate_success(q, {}, ["get_file_info_tool"])
        assert checks["tools_match"]
        assert checks["success"]

    def test_subset_with_fallback(self):
        q = AgentEvaluationQuestion(id="q1", question="?", expected_tools=["get_file_info_tool"])
        checks = AgentEvaluator._evaluate_success(q, {}, ["get_file_info_tool", "search_files_tool"])
        assert checks["tools_match"]
        assert checks["success"]

    def test_mismatch(self):
        q = AgentEvaluationQuestion(id="q1", question="?", expected_tools=["get_file_info_tool"])
        checks = AgentEvaluator._evaluate_success(q, {}, ["search_files_tool"])
        assert not checks["tools_match"]

    def test_empty_expected_no_tools_used(self):
        q = AgentEvaluationQuestion(id="q1", question="?", expected_tools=[])
        checks = AgentEvaluator._evaluate_success(q, {}, [])
        assert checks["tools_match"]
        assert checks["success"]

    def test_empty_expected_but_tools_used(self):
        q = AgentEvaluationQuestion(id="q1", question="?", expected_tools=[])
        checks = AgentEvaluator._evaluate_success(q, {}, ["search_files_tool"])
        assert not checks["tools_match"]


class TestDataFieldsMatch:
    def test_subset(self):
        q = AgentEvaluationQuestion(id="q1", question="?", expected_data_fields=["file", "urls"])
        checks = AgentEvaluator._evaluate_success(q, {"data": {"file": {}, "urls": {}, "extra": 1}}, [])
        assert checks["data_fields_match"]

    def test_missing(self):
        q = AgentEvaluationQuestion(id="q1", question="?", expected_data_fields=["file", "urls"])
        checks = AgentEvaluator._evaluate_success(q, {"data": {"file": {}}}, [])
        assert not checks["data_fields_match"]

    def test_null_data(self):
        q = AgentEvaluationQuestion(id="q1", question="?", expected_data_fields=["file"])
        checks = AgentEvaluator._evaluate_success(q, {}, [])
        assert not checks["data_fields_match"]


class TestKeywordsMatch:
    def test_all_match(self):
        q = AgentEvaluationQuestion(id="q1", question="?",
                                     expected_response_keywords=["找到", "成功"])
        checks = AgentEvaluator._evaluate_success(q, {"response": "已找到文件，操作成功"}, [])
        assert checks["keywords_match"]

    def test_partial_match(self):
        q = AgentEvaluationQuestion(id="q1", question="?",
                                     expected_response_keywords=["找到", "成功"])
        checks = AgentEvaluator._evaluate_success(q, {"response": "找到了文件"}, [])
        assert not checks["keywords_match"]


class TestNoExpectations:
    def test_vacuously_true(self):
        q = AgentEvaluationQuestion(id="q1", question="?")
        checks = AgentEvaluator._evaluate_success(q, {}, [])
        assert checks["success"]
        assert len(checks) == 1  # only "success" key


class TestCombinedChecks:
    def test_all_pass(self):
        q = AgentEvaluationQuestion(
            id="q1", question="?", expected_action="search",
            expected_tools=["search_files_tool"], expected_data_fields=["results"],
        )
        checks = AgentEvaluator._evaluate_success(
            q,
            {"action": "search", "data": {"results": [], "keyword": "x"}},
            ["search_files_tool"],
        )
        assert checks["action_match"]
        assert checks["tools_match"]
        assert checks["data_fields_match"]
        assert checks["success"]

    def test_one_fails(self):
        q = AgentEvaluationQuestion(
            id="q1", question="?", expected_action="search",
            expected_tools=["search_files_tool"], expected_data_fields=["results"],
        )
        checks = AgentEvaluator._evaluate_success(q, {"action": "wrong"}, ["search_files_tool"])
        assert not checks["success"]


# ═══════════════════════════════════════════════════════════════════
#  Test 5 — AgentEvaluator full flow (mocked graph)
# ═══════════════════════════════════════════════════════════════════

class TestAgentEvaluatorFullFlow:
    def test_single_question_success(self):
        q = AgentEvaluationQuestion(
            id="aq1", question="Find README", expected_action="file_info",
            expected_tools=["get_file_info_tool"], expected_data_fields=["file", "urls"],
        )
        state = _build_mock_state(
            content=json.dumps({
                "response": "找到文件 README", "action": "file_info",
                "data": {"file": {"name": "README"}, "urls": {}},
            }),
            token_usage={"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
            tool_calls=[{"name": "get_file_info_tool", "args": {"name": "README"}, "id": "tc1"}],
        )

        with mock.patch("app.agents.graph.agent_graph.ainvoke",
                        new=mock.AsyncMock(return_value=state)):
            evaluator = AgentEvaluator([q])
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(evaluator.run())

        assert len(result.per_question) == 1
        pq = result.per_question[0]
        assert pq["question_id"] == "aq1"
        assert pq["action"] == "file_info"
        assert pq["tools_used"] == ["get_file_info_tool"]
        assert pq["checks"]["success"]
        assert pq["checks"]["action_match"]
        assert pq["checks"]["tools_match"]
        assert pq["checks"]["data_fields_match"]
        assert pq["metrics"]["prompt_tokens"] == 200
        assert pq["metrics"]["completion_tokens"] == 60
        assert pq["metrics"]["tool_calls_count"] == 1
        assert pq["metrics"]["llm_calls_count"] == 2

    def test_aggregate_computes_correctly(self):
        q1 = AgentEvaluationQuestion(id="aq1", question="Q1?", expected_action="chat")
        q2 = AgentEvaluationQuestion(id="aq2", question="Q2?", expected_action="search")

        state_ok = _build_mock_state(
            content=json.dumps({"response": "ok", "action": "chat"}),
            token_usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        )
        state_fail = _build_mock_state(
            content=json.dumps({"response": "fail", "action": "chat"}),
            token_usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )
        mock_graph = mock.AsyncMock(side_effect=[state_ok, state_fail])

        with mock.patch("app.agents.graph.agent_graph.ainvoke", new=mock_graph):
            evaluator = AgentEvaluator([q1, q2])
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(evaluator.run())

        agg = result.aggregate
        assert agg["total_questions"] == 2
        assert agg["success_rate"] == 0.5
        assert agg["avg_total_tokens"] == 90.0
        assert agg["avg_latency_ms"] > 0

    def test_graph_exception_handling(self):
        q = AgentEvaluationQuestion(id="aq1", question="Q?")

        with mock.patch("app.agents.graph.agent_graph.ainvoke",
                        new=mock.AsyncMock(side_effect=RuntimeError("LLM timeout"))):
            evaluator = AgentEvaluator([q])
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(evaluator.run())

        pq = result.per_question[0]
        assert not pq["checks"]["success"]
        assert pq["checks"]["error"] == "LLM timeout"
        assert pq["error"] == "LLM timeout"
        assert pq["metrics"]["latency_ms"] > 0

    def test_graph_returns_non_json_content(self):
        q = AgentEvaluationQuestion(id="aq1", question="Q?", expected_action="chat")

        state = _build_mock_state(
            content="Just plain text, no JSON at all",
            token_usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        )

        with mock.patch("app.agents.graph.agent_graph.ainvoke",
                        new=mock.AsyncMock(return_value=state)):
            evaluator = AgentEvaluator([q])
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(evaluator.run())

        pq = result.per_question[0]
        assert pq["action"] is None
        assert not pq["checks"]["success"]
        assert pq["metrics"]["total_tokens"] == 25
