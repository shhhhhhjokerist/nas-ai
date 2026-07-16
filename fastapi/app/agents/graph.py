"""
LangGraph agent for NAS file management.

Architecture
------------
Two-node ReAct loop:  chatbot ←→ tools

The router injects *user_id* and *file_system_config* via
``RunnableConfig.configurable``.  The tool node reads *user_id* and
passes it to every tool so they can enforce file-level permissions.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from typing_extensions import TypedDict

from app.config import get_settings
from app.db import SessionLocal
from app.models.media import FileNode
from app.services.media_service import (
    build_file_urls,
    choose_best_match,
    copy_node,
    delete_node,
    get_children_visible,
    move_node,
    rename_node,
    search_nodes,
    serialize_node,
)


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

@contextmanager
def _db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _json(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def _user_id_from_config(config: Optional[RunnableConfig]) -> Optional[int]:
    """Extract user_id injected by the router."""
    if config and "configurable" in config:
        uid = config["configurable"].get("user_id")
        if uid is not None:
            return int(uid)
    return None


# ═══════════════════════════════════════════════════════════════════
#  Tools
# ═══════════════════════════════════════════════════════════════════

@tool
def search_files_tool(
    keyword: str,
    only_directory: bool = False,
    only_file: bool = False,
    limit: int = 20,
    user_id: Optional[int] = None,
) -> str:
    """Search files or folders by keyword and return candidates with URLs."""
    with _db_session() as session:
        nodes = search_nodes(
            session=session,
            keyword=keyword,
            only_directory=only_directory,
            only_file=only_file,
            limit=limit,
            user_id=user_id,
        )
        settings = get_settings()
        base_url = settings.AGENT_BASE_APP_URL
        return _json({
            "keyword": keyword,
            "count": len(nodes),
            "results": [
                {**serialize_node(node), "urls": build_file_urls(node, base_url)}
                for node in nodes
            ],
        })


@tool
def get_play_url_tool(name: str, user_id: Optional[int] = None) -> str:
    """Find a video file by name and return playable URL for online streaming."""
    with _db_session() as session:
        candidates = search_nodes(session, name, limit=20, user_id=user_id)
        node = choose_best_match(candidates, name, prefer_directory=False, prefer_video=True)
        if not node:
            return _json({"ok": False, "error": f"File not found: {name}"})
        settings = get_settings()
        urls = build_file_urls(node, settings.AGENT_BASE_APP_URL)
        if node.is_directory or "play_url" not in urls:
            return _json({
                "ok": False,
                "error": f"{node.name} is not a playable video",
                "file": serialize_node(node),
                "urls": urls,
            })
        return _json({"ok": True, "file": serialize_node(node), "urls": urls})


@tool
def get_download_url_tool(name: str, user_id: Optional[int] = None) -> str:
    """Find a file by name and return direct download URL."""
    with _db_session() as session:
        candidates = search_nodes(session, name, limit=20, user_id=user_id)
        node = choose_best_match(candidates, name, prefer_directory=False)
        if not node:
            return _json({"ok": False, "error": f"File not found: {name}"})
        settings = get_settings()
        urls = build_file_urls(node, settings.AGENT_BASE_APP_URL)
        if node.is_directory:
            return _json({
                "ok": False,
                "error": f"{node.name} is a directory, cannot download",
                "file": serialize_node(node),
                "urls": urls,
            })
        return _json({"ok": True, "file": serialize_node(node), "urls": urls})


@tool
def get_file_info_tool(name: str, user_id: Optional[int] = None) -> str:
    """Find one best matching file/folder and return detailed info with URLs."""
    with _db_session() as session:
        candidates = search_nodes(session, name, limit=20, user_id=user_id)
        node = choose_best_match(candidates, name)
        if not node:
            return _json({"ok": False, "error": f"No match found: {name}"})
        settings = get_settings()
        return _json({
            "ok": True,
            "file": serialize_node(node),
            "urls": build_file_urls(node, settings.AGENT_BASE_APP_URL),
        })


@tool
def get_folder_info_tool(name: str, user_id: Optional[int] = None) -> str:
    """Find one folder and return child list and browse URL."""
    with _db_session() as session:
        candidates = search_nodes(session, name, only_directory=True, limit=20, user_id=user_id)
        node = choose_best_match(candidates, name, prefer_directory=True)
        if not node:
            return _json({"ok": False, "error": f"Folder not found: {name}"})
        children = get_children_visible(session, node.id, user_id=user_id, limit=50)
        settings = get_settings()
        return _json({
            "ok": True,
            "folder": serialize_node(node),
            "children": [serialize_node(item) for item in children],
            "urls": build_file_urls(node, settings.AGENT_BASE_APP_URL),
        })


@tool
def move_file_tool(
    source_name: str,
    destination_folder: str,
    user_id: Optional[int] = None,
) -> str:
    """Move a file/folder into destination folder, then return updated info and URLs."""
    with _db_session() as session:
        source_candidates = search_nodes(session, source_name, limit=20, user_id=user_id)
        source = choose_best_match(source_candidates, source_name, prefer_directory=False)
        if not source:
            return _json({"ok": False, "error": f"Source not found: {source_name}"})

        dest_candidates = search_nodes(
            session, destination_folder, only_directory=True, limit=20, user_id=user_id
        )
        destination = choose_best_match(dest_candidates, destination_folder, prefer_directory=True)
        if not destination:
            return _json({"ok": False, "error": f"Destination not found: {destination_folder}"})

        try:
            moved = move_node(session, source, destination)
        except ValueError as e:
            session.rollback()
            return _json({"ok": False, "error": str(e)})

        settings = get_settings()
        return _json({
            "ok": True,
            "file": serialize_node(moved),
            "destination": serialize_node(destination),
            "urls": build_file_urls(moved, settings.AGENT_BASE_APP_URL),
        })


@tool
def copy_file_tool(
    source_name: str,
    destination_folder: str,
    new_name: str = "",
    user_id: Optional[int] = None,
) -> str:
    """Copy a file or folder into a destination folder and return the new node info."""
    with _db_session() as session:
        source_candidates = search_nodes(session, source_name, limit=20, user_id=user_id)
        source = choose_best_match(source_candidates, source_name, prefer_directory=False)
        if not source:
            return _json({"ok": False, "error": f"Source not found: {source_name}"})

        dest_candidates = search_nodes(
            session, destination_folder, only_directory=True, limit=20, user_id=user_id
        )
        destination = choose_best_match(dest_candidates, destination_folder, prefer_directory=True)
        if not destination:
            return _json({"ok": False, "error": f"Destination not found: {destination_folder}"})

        try:
            copied = copy_node(session, source, destination, new_name or None)
            session.commit()
            session.refresh(copied)
        except ValueError as e:
            session.rollback()
            return _json({"ok": False, "error": str(e)})

        settings = get_settings()
        return _json({
            "ok": True,
            "file": serialize_node(copied),
            "destination": serialize_node(destination),
            "urls": build_file_urls(copied, settings.AGENT_BASE_APP_URL),
        })


@tool
def create_folder_tool(
    name: str,
    parent_name: str = "",
    user_id: Optional[int] = None,
) -> str:
    """Create a new folder.  If *parent_name* is given, create inside that folder;
    otherwise create at root level."""
    settings = get_settings()
    with _db_session() as session:
        parent = None
        if parent_name:
            candidates = search_nodes(
                session, parent_name, only_directory=True, limit=5, user_id=user_id
            )
            parent = choose_best_match(candidates, parent_name, prefer_directory=True)
            if not parent:
                return _json({"ok": False, "error": f"Parent folder not found: {parent_name}"})

        media_dir = Path(settings.MEDIA_DIR)
        if parent:
            new_abs = Path(parent.abs_path) / name
            new_rel = str((Path(parent.path) / name).as_posix())
        else:
            new_abs = media_dir / name
            new_rel = name

        if new_abs.exists():
            return _json({"ok": False, "error": f"Path already exists: {name}"})

        new_abs.mkdir(parents=True, exist_ok=False)

        folder = FileNode(
            name=name,
            path=new_rel,
            abs_path=str(new_abs.resolve()),
            parent_id=parent.id if parent else None,
            is_directory=True,
            size=0,
            owner_id=user_id,
            visibility="private",
        )
        session.add(folder)
        session.commit()
        session.refresh(folder)

        return _json({
            "ok": True,
            "folder": serialize_node(folder),
            "urls": build_file_urls(folder, settings.AGENT_BASE_APP_URL),
        })


@tool
def rename_file_tool(
    name: str,
    new_name: str,
    user_id: Optional[int] = None,
) -> str:
    """Rename a file or folder.  *name* finds the target, *new_name* is the desired name."""
    settings = get_settings()
    with _db_session() as session:
        candidates = search_nodes(session, name, limit=20, user_id=user_id)
        node = choose_best_match(candidates, name)
        if not node:
            return _json({"ok": False, "error": f"File not found: {name}"})

        try:
            renamed = rename_node(session, node, new_name)
        except ValueError as e:
            session.rollback()
            return _json({"ok": False, "error": str(e)})

        return _json({
            "ok": True,
            "file": serialize_node(renamed),
            "urls": build_file_urls(renamed, settings.AGENT_BASE_APP_URL),
        })


@tool
def delete_file_tool(
    name: str,
    permanent: bool = False,
    user_id: Optional[int] = None,
) -> str:
    """Delete a file or folder.  By default soft-deletes (recoverable).
    Set *permanent=True* to permanently remove from disk."""
    with _db_session() as session:
        candidates = search_nodes(session, name, limit=20, user_id=user_id)
        node = choose_best_match(candidates, name)
        if not node:
            return _json({"ok": False, "error": f"File not found: {name}"})

        try:
            delete_node(session, node, permanent=permanent)
        except ValueError as e:
            session.rollback()
            return _json({"ok": False, "error": str(e)})

        return _json({
            "ok": True,
            "action": "deleted",
            "name": node.name,
            "permanent": permanent,
        })


@tool
def search_documents_tool(
    query: str,
    limit: int = 5,
    user_id: Optional[int] = None,
) -> str:
    """Search local documents (PDF, Word, txt, markdown) for relevant information.
    Use this when the user asks about knowledge, papers, reports, notes, or any
    topic that might be covered in their document collection.
    """
    from app.services.retrieval_service import RetrievalService

    retrieval = RetrievalService()
    hits = retrieval.search(query, top_k=limit)

    if not hits:
        return _json({
            "ok": True,
            "query": query,
            "count": 0,
            "results": [],
            "message": "No relevant documents found.",
        })

    return _json({
        "ok": True,
        "query": query,
        "count": len(hits),
        "results": [
            {
                "source": h["metadata"].get("file_name", "unknown"),
                "text": h["text"],
                "relevance": round(h.get("score", 0), 4),
            }
            for h in hits
        ],
    })


# ═══════════════════════════════════════════════════════════════════
#  Tool registry
# ═══════════════════════════════════════════════════════════════════

TOOLS = [
    search_files_tool,
    get_play_url_tool,
    get_download_url_tool,
    get_file_info_tool,
    get_folder_info_tool,
    move_file_tool,
    copy_file_tool,
    create_folder_tool,
    rename_file_tool,
    delete_file_tool,
    search_documents_tool,
]
TOOL_MAP = {t.name: t for t in TOOLS}


# ═══════════════════════════════════════════════════════════════════
#  Graph
# ═══════════════════════════════════════════════════════════════════

class State(TypedDict):
    messages: Annotated[list, add_messages]


def _build_llm() -> ChatOpenAI:
    settings = get_settings()
    if not settings.AGENT_API_KEY:
        raise RuntimeError(
            "AGENT_API_KEY is not set.  "
            "Add it to your .env file or set the environment variable."
        )
    return ChatOpenAI(
        model=settings.AGENT_MODEL,
        base_url=settings.AGENT_BASE_URL,
        api_key=settings.AGENT_API_KEY,
        temperature=settings.AGENT_TEMPERATURE,
        max_tokens=settings.AGENT_MAX_TOKENS,
    )


# Shared checkpointer for conversation memory
_memory_saver = MemorySaver()


def create_agent_graph():
    llm_with_tools = _build_llm().bind_tools(TOOLS)

    def chatbot(state: State):
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    def tool_node(state: State, config: RunnableConfig):
        """Execute tool calls, injecting *user_id* from the router-provided config."""
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", []) or []
        user_id = _user_id_from_config(config)

        results: List[ToolMessage] = []
        for tc in tool_calls:
            tool_name = tc.get("name")
            tool_args = dict(tc.get("args", {}))
            tool_args["user_id"] = user_id  # ← inject permission context

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

    return graph.compile(checkpointer=_memory_saver)


# Single shared agent instance (checkpointer lives inside)
agent_graph = create_agent_graph()
