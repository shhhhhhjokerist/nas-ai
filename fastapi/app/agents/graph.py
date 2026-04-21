# app/agents/graph.py
import json
import os
from contextlib import contextmanager
from typing import Annotated, Any, Dict, Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from typing_extensions import TypedDict

from app.db import SessionLocal
from app.models.media import FileNode
from app.services.media_service import (
    build_file_urls,
    choose_best_match,
    copy_node,
    move_node,
    search_nodes,
    serialize_node,
)


DEFAULT_BASE_URL = os.getenv("AGENT_BASE_APP_URL", "http://127.0.0.1:8000")


@contextmanager
def _db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _json(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


@tool
def search_files_tool(
    keyword: str,
    only_directory: bool = False,
    only_file: bool = False,
    limit: int = 20,
    base_url: str = DEFAULT_BASE_URL,
) -> str:
    """Search files or folders by keyword and return candidates with URLs."""
    with _db_session() as session:
        nodes = search_nodes(
            session=session,
            keyword=keyword,
            only_directory=only_directory,
            only_file=only_file,
            limit=limit,
        )
        return _json(
            {
                "keyword": keyword,
                "count": len(nodes),
                "results": [
                    {
                        **serialize_node(node),
                        "urls": build_file_urls(node, base_url),
                    }
                    for node in nodes
                ],
            }
        )


@tool
def get_play_url_tool(name: str, base_url: str = DEFAULT_BASE_URL) -> str:
    """Find a video file by name and return playable URL for online streaming."""
    with _db_session() as session:
        candidates = search_nodes(session, name, only_directory=False, only_file=False, limit=20)
        node = choose_best_match(candidates, name, prefer_directory=False, prefer_video=True)
        if not node:
            return _json({"ok": False, "error": f"未找到文件: {name}"})

        urls = build_file_urls(node, base_url)
        if node.is_directory or "play_url" not in urls:
            return _json(
                {
                    "ok": False,
                    "error": f"{node.name} 不是可在线播放视频",
                    "file": serialize_node(node),
                    "urls": urls,
                }
            )
        return _json({"ok": True, "file": serialize_node(node), "urls": urls})


@tool
def get_download_url_tool(name: str, base_url: str = DEFAULT_BASE_URL) -> str:
    """Find a file by name and return direct download URL."""
    with _db_session() as session:
        candidates = search_nodes(session, name, only_directory=False, only_file=False, limit=20)
        node = choose_best_match(candidates, name, prefer_directory=False)
        if not node:
            return _json({"ok": False, "error": f"未找到文件: {name}"})

        urls = build_file_urls(node, base_url)
        if node.is_directory:
            return _json(
                {
                    "ok": False,
                    "error": f"{node.name} 是文件夹，不能直接下载目录",
                    "file": serialize_node(node),
                    "urls": urls,
                }
            )
        return _json({"ok": True, "file": serialize_node(node), "urls": urls})


@tool
def get_file_info_tool(name: str, base_url: str = DEFAULT_BASE_URL) -> str:
    """Find one best matching file/folder and return detailed info with URLs."""
    with _db_session() as session:
        candidates = search_nodes(session, name, only_directory=False, only_file=False, limit=20)
        node = choose_best_match(candidates, name)
        if not node:
            return _json({"ok": False, "error": f"未找到匹配项: {name}"})

        return _json({"ok": True, "file": serialize_node(node), "urls": build_file_urls(node, base_url)})


@tool
def get_folder_info_tool(name: str, base_url: str = DEFAULT_BASE_URL) -> str:
    """Find one folder and return child list and browse URL."""
    with _db_session() as session:
        candidates = search_nodes(session, name, only_directory=True, only_file=False, limit=20)
        node = choose_best_match(candidates, name, prefer_directory=True)
        if not node:
            return _json({"ok": False, "error": f"未找到文件夹: {name}"})

        children = (
            session.query(FileNode)
            .filter(FileNode.parent_id == node.id, FileNode.is_deleted == False)
            .order_by(FileNode.is_directory.desc(), FileNode.name.asc())
            .limit(50)
            .all()
        )
        return _json(
            {
                "ok": True,
                "folder": serialize_node(node),
                "children": [serialize_node(item) for item in children],
                "urls": build_file_urls(node, base_url),
            }
        )


@tool
def move_file_tool(source_name: str, destination_folder: str, base_url: str = DEFAULT_BASE_URL) -> str:
    """Move a file/folder into destination folder, then return updated info and URLs."""
    with _db_session() as session:
        source_candidates = search_nodes(session, source_name, only_directory=False, only_file=False, limit=20)
        source = choose_best_match(source_candidates, source_name, prefer_directory=False)
        if not source:
            return _json({"ok": False, "error": f"未找到源文件: {source_name}"})

        dest_candidates = search_nodes(session, destination_folder, only_directory=True, only_file=False, limit=20)
        destination = choose_best_match(dest_candidates, destination_folder, prefer_directory=True)
        if not destination:
            return _json({"ok": False, "error": f"未找到目标目录: {destination_folder}"})

        try:
            moved = move_node(session, source, destination)
        except ValueError as e:
            session.rollback()
            return _json({"ok": False, "error": str(e)})

        return _json(
            {
                "ok": True,
                "file": serialize_node(moved),
                "destination": serialize_node(destination),
                "urls": build_file_urls(moved, base_url),
            }
        )


@tool
def copy_file_tool(source_name: str, destination_folder: str, new_name: str = "", base_url: str = DEFAULT_BASE_URL) -> str:
    """Copy a file or folder into a destination folder and return the new node info."""
    with _db_session() as session:
        source_candidates = search_nodes(session, source_name, only_directory=False, only_file=False, limit=20)
        source = choose_best_match(source_candidates, source_name, prefer_directory=False)
        if not source:
            return _json({"ok": False, "error": f"未找到源文件: {source_name}"})

        dest_candidates = search_nodes(session, destination_folder, only_directory=True, only_file=False, limit=20)
        destination = choose_best_match(dest_candidates, destination_folder, prefer_directory=True)
        if not destination:
            return _json({"ok": False, "error": f"未找到目标目录: {destination_folder}"})

        try:
            copied = copy_node(session, source, destination, new_name or None)
            session.commit()
            session.refresh(copied)
        except ValueError as e:
            session.rollback()
            return _json({"ok": False, "error": str(e)})

        return _json(
            {
                "ok": True,
                "file": serialize_node(copied),
                "destination": serialize_node(destination),
                "urls": build_file_urls(copied, base_url),
            }
        )


TOOLS = [
    search_files_tool,
    get_play_url_tool,
    get_download_url_tool,
    get_file_info_tool,
    get_folder_info_tool,
    move_file_tool,
    copy_file_tool,
]
TOOL_MAP = {tool_obj.name: tool_obj for tool_obj in TOOLS}


class State(TypedDict):
    messages: Annotated[list, add_messages]


def _build_llm() -> ChatOpenAI:
    # models: glm-4.7-flash, glm-4-flashx-250414
    model = os.getenv("AGENT_MODEL", "glm-4-flashx-250414")
    base_url = os.getenv("AGENT_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
    # api_key = os.getenv("AGENT_API_KEY") or os.getenv("ZHIPUAI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    api_key = "1f4222091d444ac992fd951a6cafa7eb.8H3I5Sy1Xw1b8K7B"
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0.2,
        max_tokens=1024,
    )


def create_agent_graph():
    llm_with_tools = _build_llm().bind_tools(TOOLS)

    def chatbot(state: State):
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    def tool_node(state: State):
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", []) or []
        results = []
        for tc in tool_calls:
            tool_name = tc.get("name")
            tool_args = tc.get("args", {})
            tool_obj = TOOL_MAP.get(tool_name)
            if not tool_obj:
                content = _json({"ok": False, "error": f"Unknown tool: {tool_name}"})
            else:
                try:
                    content = tool_obj.invoke(tool_args)
                except Exception as e:
                    content = _json({"ok": False, "error": f"Tool failed: {str(e)}"})
            results.append(ToolMessage(content=content, tool_call_id=tc["id"]))
        return {"messages": results}

    def should_continue(state: State) -> Literal["tools", "end"]:
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tools"
        return "end"

    graph = StateGraph(State)
    graph.add_node("chatbot", chatbot)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "chatbot")
    graph.add_conditional_edges("chatbot", should_continue, {"tools": "tools", "end": END})
    graph.add_edge("tools", "chatbot")
    return graph.compile()


agent_graph = create_agent_graph()