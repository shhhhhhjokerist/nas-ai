"""Agent HTTP endpoint integration tests."""
import json
import pytest
from unittest import mock
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════════════════════════════
#  Auth
# ═══════════════════════════════════════════════════════════════════

class TestAgentAuth:
    def test_chat_no_auth(self, client: TestClient):
        resp = client.post("/agent/chat", json={"message": "hello"})
        assert resp.status_code == 401

    def test_history_no_auth(self, client: TestClient):
        resp = client.get("/agent/threads/test/history")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════
#  Chat (mocked agent graph — avoid real LLM calls)
# ═══════════════════════════════════════════════════════════════════

def _make_mock_state(content: str):
    """Build a fake LangGraph result with a final AI message."""
    from langchain_core.messages import AIMessage
    return {"messages": [AIMessage(content=content)]}


class TestAgentChat:
    def test_chat_simple_response(self, client: TestClient, auth_headers):
        state = _make_mock_state(json.dumps({
            "response": "你好！我是 NAS 助手。",
            "action": "chat",
            "data": {},
        }, ensure_ascii=False))

        with mock.patch(
            "app.agents.graph.agent_graph.ainvoke",
            new=mock.AsyncMock(return_value=state),
        ):
            resp = client.post("/agent/chat", json={
                "message": "你好", "thread_id": "test-thread-1",
            }, headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "你好" in data["response"]
        assert data["action"] == "chat"
        assert data["thread_id"] == "test-thread-1"

    def test_chat_with_file_info_action(self, client: TestClient, auth_headers):
        state = _make_mock_state(json.dumps({
            "response": "找到了文件 readme.txt",
            "action": "file_info",
            "data": {"file": {"name": "readme.txt", "id": 1}},
        }, ensure_ascii=False))

        with mock.patch(
            "app.agents.graph.agent_graph.ainvoke",
            new=mock.AsyncMock(return_value=state),
        ):
            resp = client.post("/agent/chat", json={
                "message": "查看 readme 文件信息",
            }, headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "file_info"

    def test_chat_with_search_action(self, client: TestClient, auth_headers):
        state = _make_mock_state(json.dumps({
            "response": "搜索到 3 个结果",
            "action": "search",
            "data": {"results": []},
        }, ensure_ascii=False))

        with mock.patch(
            "app.agents.graph.agent_graph.ainvoke",
            new=mock.AsyncMock(return_value=state),
        ):
            resp = client.post("/agent/chat", json={
                "message": "搜索所有 PDF",
            }, headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["action"] == "search"

    def test_chat_user_id_injected(self, client: TestClient, auth_headers, regular_user):
        """Verify user_id is passed in configurable to the agent graph."""
        state = _make_mock_state(json.dumps({
            "response": "ok", "action": "chat", "data": {},
        }))

        mock_ainvoke = mock.AsyncMock(return_value=state)
        with mock.patch("app.agents.graph.agent_graph.ainvoke", new=mock_ainvoke):
            client.post("/agent/chat", json={
                "message": "test", "thread_id": "uid-test",
            }, headers=auth_headers)

        # Check that user_id was in the config
        call_config = mock_ainvoke.call_args[1]["config"]
        assert call_config["configurable"]["user_id"] == regular_user.id

    def test_chat_without_thread_id_defaults(self, client: TestClient, auth_headers):
        state = _make_mock_state(json.dumps({
            "response": "ok", "action": "chat", "data": {},
        }))
        with mock.patch(
            "app.agents.graph.agent_graph.ainvoke",
            new=mock.AsyncMock(return_value=state),
        ):
            resp = client.post("/agent/chat", json={
                "message": "test",
            }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["thread_id"] == "default"


# ═══════════════════════════════════════════════════════════════════
#  File system config injection
# ═══════════════════════════════════════════════════════════════════

class TestFileSystemConfigInjection:
    def test_config_injected_into_system_prompt(self, client: TestClient, auth_headers):
        # Set a custom file system config
        config_text = "Photos -> Photos/YYYY/MM. All movies must go in Movies/."
        client.patch("/user/me/file-system-config", json={
            "file_system_config": config_text,
        }, headers=auth_headers)

        state = _make_mock_state(json.dumps({
            "response": "已按你的规则整理文件。",
            "action": "chat",
            "data": {},
        }, ensure_ascii=False))

        mock_ainvoke = mock.AsyncMock(return_value=state)
        with mock.patch("app.agents.graph.agent_graph.ainvoke", new=mock_ainvoke):
            client.post("/agent/chat", json={
                "message": "整理我的文件",
            }, headers=auth_headers)

        # The system prompt should contain the user's config
        messages = mock_ainvoke.call_args[0][0]["messages"]
        system_content = messages[0].content
        assert config_text in system_content


# ═══════════════════════════════════════════════════════════════════
#  History endpoint
# ═══════════════════════════════════════════════════════════════════

class TestAgentHistory:
    def test_history_returns_empty_for_new_thread(self, client: TestClient, auth_headers):
        resp = client.get("/agent/threads/new-thread/history", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["thread_id"] == "new-thread"

    def test_history_after_chat(self, client: TestClient, auth_headers):
        state = _make_mock_state(json.dumps({
            "response": "Hello back!", "action": "chat", "data": {},
        }))

        with mock.patch(
            "app.agents.graph.agent_graph.ainvoke",
            new=mock.AsyncMock(return_value=state),
        ):
            client.post("/agent/chat", json={
                "message": "Hello!", "thread_id": "conv-1",
            }, headers=auth_headers)

        resp = client.get("/agent/threads/conv-1/history", headers=auth_headers)
        assert resp.status_code == 200
