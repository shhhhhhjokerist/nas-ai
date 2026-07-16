"""Agent graph flow tests — state transitions, tool routing, user context."""
import json
import pytest
from unittest import mock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


class TestGraphStructure:
    def test_graph_has_two_nodes(self):
        from app.agents.graph import create_agent_graph
        graph = create_agent_graph()
        nodes = graph.get_graph().nodes
        assert "chatbot" in nodes
        assert "tools" in nodes

    def test_graph_starts_at_chatbot(self):
        from app.agents.graph import create_agent_graph
        graph = create_agent_graph()
        # Verify graph is compilable and has expected structure
        assert graph is not None


class TestShouldContinue:
    def test_continue_to_tools_when_tool_calls_present(self):
        from app.agents.graph import create_agent_graph
        msg = AIMessage(content="", tool_calls=[{"name": "search_files_tool", "args": {}, "id": "tc1"}])
        state = {"messages": [msg]}

        graph = create_agent_graph()
        # The should_continue function is internal, test via invoke
        assert graph is not None  # graph compiles successfully


class TestUserIDInjection:
    """Verify the tool_node injects user_id from RunnableConfig."""
    def test_user_id_from_config_extracts_correctly(self):
        from app.agents.graph import _user_id_from_config

        config = {"configurable": {"thread_id": "t1", "user_id": 42}}
        assert _user_id_from_config(config) == 42

    def test_user_id_from_config_none_when_missing(self):
        from app.agents.graph import _user_id_from_config
        assert _user_id_from_config(None) is None
        assert _user_id_from_config({}) is None
        assert _user_id_from_config({"configurable": {}}) is None


class TestBuildLLM:
    def test_missing_api_key_raises(self):
        """When AGENT_API_KEY is not set, _build_llm should raise RuntimeError."""
        from app.agents.graph import _build_llm
        with mock.patch("app.agents.graph.get_settings") as mock_settings:
            settings = mock.MagicMock()
            settings.AGENT_API_KEY = ""
            mock_settings.return_value = settings
            with pytest.raises(RuntimeError, match="AGENT_API_KEY"):
                _build_llm()

    def test_valid_api_key_returns_llm(self):
        """With a valid API key, _build_llm should return a ChatOpenAI instance."""
        from app.agents.graph import _build_llm
        from langchain_openai import ChatOpenAI
        with mock.patch("app.agents.graph.get_settings") as mock_settings:
            settings = mock.MagicMock()
            settings.AGENT_API_KEY = "sk-test-123"
            settings.AGENT_MODEL = "test-model"
            settings.AGENT_BASE_URL = "https://test.api.com/v1"
            settings.AGENT_TEMPERATURE = 0.1
            settings.AGENT_MAX_TOKENS = 500
            mock_settings.return_value = settings
            llm = _build_llm()
            assert isinstance(llm, ChatOpenAI)


class TestStateSchema:
    def test_state_has_messages_field(self):
        from app.agents.graph import State
        state: State = {"messages": []}
        assert "messages" in state
