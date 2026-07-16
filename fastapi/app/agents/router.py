"""
Agent chat router — bridges HTTP requests to the LangGraph agent.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.graph import agent_graph
from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.services.media_service import (
    build_file_urls,
    choose_best_match,
    search_nodes,
    serialize_node,
)

agent_router = APIRouter(prefix="/agent", tags=["agent"])


# ═══════════════════════════════════════════════════════════════════
#  Pydantic models
# ═══════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    thread_id: str
    action: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


# ═══════════════════════════════════════════════════════════════════
#  System prompt builder
# ═══════════════════════════════════════════════════════════════════

# Public alias for the evaluator / external users
SYSTEM_PROMPT_TEMPLATE = (
    "你是 NAS 文件系统助手。请根据用户自然语言需求，优先通过 tools 完成文件操作。"
    "\n\n你可以完成：\n1. 返回文件信息/文件夹信息\n2. 返回下载 URL\n3. 返回在线播放 URL"
    "\n4. 移动文件或文件夹\n5. 复制文件或文件夹\n6. 搜索文件"
    "\n7. 搜索本地文档知识库（PDF、Word、txt、markdown），获取文档中的知识和信息"
    "\n\n要求：\n1. 能用工具时必须调用工具，不要臆造路径和 URL。"
    "\n2. 工具参数中的 base_url 必须使用: {base_url}"
    "\n3. 当用户询问知识类问题、论文内容、文档摘要等时，优先使用 search_documents_tool 搜索本地文档。"
    "\n4. response 文本不要包含任何 http/https URL、不要使用 markdown 链接，按钮交互由前端根据 data 渲染。"
    "\n5. 最终回答必须是 JSON（不要 markdown 代码块），格式："
    '\n{{"response": "给用户看的自然语言回复", '
    '"action": "play|download|file_info|folder_info|move|copy|search|document_search|create_folder|rename|delete|chat", '
    '"data": {{}}}}'
)

_BASE_SYSTEM_PROMPT = """\
You are a NAS file system assistant.  Use tools for ALL file operations — never make up paths or URLs.

Your abilities:
1.  File info / folder listing (get_file_info_tool, get_folder_info_tool)
2.  Download / streaming URLs (get_download_url_tool, get_play_url_tool)
3.  Search files (search_files_tool)
4.  Create folders (create_folder_tool)
5.  Rename files/folders (rename_file_tool)
6.  Delete files/folders (delete_file_tool)
7.  Move files/folders (move_file_tool)
8.  Copy files/folders (copy_file_tool)
9.  Search local documents — PDF, Word, txt, markdown (search_documents_tool)

Rules:
1. Always use tools — never guess paths or URLs.
2. For complex multi-step tasks, plan the steps and execute them one by one.
3. Before destructive operations (delete, move), briefly confirm what you are about to do.
4. Do NOT include raw http/https URLs in the response text — the frontend renders buttons from the data field.
5. You MUST output a single JSON object (no markdown code fences) with this exact schema:

{{
  "response": "<natural language reply to the user>",
  "action": "play|download|file_info|folder_info|move|copy|search|document_search|create_folder|rename|delete|chat",
  "data": {{}}
}}
"""


def _build_system_prompt(user: User) -> str:
    """Build the system prompt, injecting the user's file-system config if set."""
    prompt = _BASE_SYSTEM_PROMPT

    if user.file_system_config and user.file_system_config.strip():
        config_block = f"""
[USER FILE SYSTEM FRAMEWORK]
The user has described their file organisation rules below.
When creating, moving, renaming, or organising files and folders,
you MUST follow these conventions:

{user.file_system_config.strip()}

"""
        prompt = config_block + prompt

    return prompt


# ═══════════════════════════════════════════════════════════════════
#  Post-processing helpers (keep the existing logic, extend for new actions)
# ═══════════════════════════════════════════════════════════════════

def _clean_user_response(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"\1", text)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _extract_json_payload(content: str) -> Optional[Dict[str, Any]]:
    try:
        obj = json.loads(content)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    left = content.find("{")
    right = content.rfind("}")
    if left >= 0 and right > left:
        snippet = content[left : right + 1]
        try:
            obj = json.loads(snippet)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


_KNOWN_ACTIONS = frozenset({
    "play", "download", "file_info", "folder_info",
    "move", "copy", "search", "document_search",
    "create_folder", "rename", "delete", "chat",
})


def _detect_action(action: Optional[str], message: str, response: str) -> Optional[str]:
    if action and action in _KNOWN_ACTIONS:
        return action
    text = f"{message}\n{response}".lower()
    if any(k in text for k in ["播放", "在线看", "在线播放", "play"]):
        return "play"
    if any(k in text for k in ["下载", "download"]):
        return "download"
    if any(k in text for k in ["新建文件夹", "创建文件夹", "新建目录", "创建目录"]):
        return "create_folder"
    if any(k in text for k in ["重命名", "改名", "rename"]):
        return "rename"
    if any(k in text for k in ["删除", "删掉", "delete", "移除"]):
        return "delete"
    if any(k in text for k in ["文件夹", "目录", "folder"]):
        return "folder_info"
    if any(k in text for k in ["信息", "详情", "属性", "info"]):
        return "file_info"
    if any(k in text for k in ["移动", "move", "搬"]):
        return "move"
    if any(k in text for k in ["复制", "copy"]):
        return "copy"
    if any(k in text for k in ["搜索", "查找", "找", "search"]):
        return "search"
    if any(k in text for k in ["文档", "论文", "document", "知识", "摘要"]):
        return "document_search"
    return "chat"


def _extract_target(message: str) -> str:
    patterns = [
        r"《([^》]+)》",
        r'"([^"]+)"',
        r"'([^']+)'",
    ]
    for pattern in patterns:
        matched = re.search(pattern, message)
        if matched:
            return matched.group(1).strip()

    cleaned = re.sub(r"^(我想要|我想|请帮我|帮我|我要|给我)", "", message).strip()
    cleaned = re.sub(r"^(看一下|看一看|看|找一下|找一找)", "", cleaned).strip()
    for word in [
        "在线看", "在线播放", "播放", "看一下", "看一看", "看",
        "下载", "查看", "返回", "导航到", "打开",
        "文件夹", "目录", "文件", "信息",
        "新建", "创建", "删除", "重命名", "移动", "复制",
    ]:
        cleaned = cleaned.replace(word, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，。,.!?？")
    return cleaned


def _hydrate_data_if_missing(
    action: str,
    data: Optional[Dict[str, Any]],
    user_message: str,
    session: Session,
    base_url: str,
) -> Optional[Dict[str, Any]]:
    if isinstance(data, dict) and data.get("urls"):
        return data

    if action not in {
        "play", "download", "file_info", "folder_info",
        "search", "create_folder", "rename", "delete",
    }:
        return data

    target = _extract_target(user_message)
    if not target:
        return data

    if action == "search":
        candidates = search_nodes(session, target, limit=20)
        return {
            "keyword": target,
            "results": [
                {**serialize_node(node), "urls": build_file_urls(node, base_url)}
                for node in candidates
            ],
        }

    only_directory = action == "folder_info"
    prefer_video = action == "play"
    candidates = search_nodes(session, target, only_directory=only_directory, limit=20)

    if action == "play" and candidates:
        has_video = any(
            (not node.is_directory) and build_file_urls(node, base_url).get("play_url")
            for node in candidates
        )
        if not has_video:
            folder_node = choose_best_match(
                candidates, target, prefer_directory=True, prefer_video=False
            )
            if folder_node:
                return {
                    "file": serialize_node(folder_node),
                    "urls": build_file_urls(folder_node, base_url),
                }

    node = choose_best_match(
        candidates, target,
        prefer_directory=True if only_directory else False,
        prefer_video=prefer_video,
    )
    if not node:
        return data

    return {
        "file": serialize_node(node),
        "urls": build_file_urls(node, base_url),
    }


# ═══════════════════════════════════════════════════════════════════
#  Endpoints
# ═══════════════════════════════════════════════════════════════════

@agent_router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
    session: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Chat with the NAS file management agent.

    The agent can search, browse, play, download, create, rename, delete,
    move, and copy files — as well as search local documents via RAG.
    Conversation history is preserved per *thread_id*.
    """
    thread_id = request.thread_id or "default"
    base_url = str(http_request.base_url).rstrip("/")

    system_prompt = _build_system_prompt(current_user)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=request.message),
    ]

    try:
        result = await agent_graph.ainvoke(
            {"messages": messages},
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "user_id": current_user.id,
                }
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent invocation failed: {str(e)}")

    final_message = result["messages"][-1]
    response_content = getattr(final_message, "content", str(final_message))
    payload = _extract_json_payload(response_content) or {}

    response_text = _clean_user_response(payload.get("response", response_content))
    action = _detect_action(payload.get("action"), request.message, response_text)
    data = _hydrate_data_if_missing(
        action=action,
        data=payload.get("data"),
        user_message=request.message,
        session=session,
        base_url=base_url,
    )

    return ChatResponse(
        response=response_text,
        thread_id=thread_id,
        action=action,
        data=data,
    )


@agent_router.get("/threads/{thread_id}/history")
async def get_thread_history(
    thread_id: str,
    current_user: User = Depends(get_current_user),
):
    """Return conversation history for a thread.

    Requires a checkpointer (MemorySaver is configured in graph.py).
    Returns the raw state snapshot from LangGraph.
    """
    try:
        config = {
            "configurable": {
                "thread_id": thread_id,
                "user_id": current_user.id,
            }
        }
        state = await agent_graph.aget_state(config)
        if state.values:
            messages = state.values.get("messages", [])
            return {
                "thread_id": thread_id,
                "messages": [
                    {"role": type(m).__name__, "content": getattr(m, "content", str(m))}
                    for m in messages
                ],
            }
        return {"thread_id": thread_id, "messages": []}
    except Exception:
        return {"thread_id": thread_id, "messages": []}
