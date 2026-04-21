# app/agents/router.py
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Any, Optional
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.graph import agent_graph
from app.db import get_db
from app.services.media_service import (
    build_file_urls,
    choose_best_match,
    search_nodes,
    serialize_node,
)
from sqlalchemy.orm import Session

agent_router = APIRouter(prefix="/agent", tags=["agent"])

class ChatRequest(BaseModel):
    message: str
    # thread_id: str | None = None  # 可选：会话 ID
    thread_id: str = None

class ChatResponse(BaseModel):
    response: str
    thread_id: str
    action: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


SYSTEM_PROMPT_TEMPLATE = """
你是 NAS 文件系统助手。请根据用户自然语言需求，优先通过 tools 完成文件操作。

你可以完成：
1. 返回文件信息/文件夹信息
2. 返回下载 URL
3. 返回在线播放 URL
4. 移动文件或文件夹
5. 复制文件或文件夹
6. 搜索文件

要求：
1. 能用工具时必须调用工具，不要臆造路径和 URL。
2. 工具参数中的 base_url 必须使用: {base_url}
3. response 文本不要包含任何 http/https URL、不要使用 markdown 链接，按钮交互由前端根据 data 渲染。
4. 最终回答必须是 JSON（不要 markdown 代码块），格式：
{{
  "response": "给用户看的自然语言回复",
  "action": "play|download|file_info|folder_info|move|search|chat",
  "data": {{}}
}}
""".strip()


def _clean_user_response(text: str) -> str:
    if not text:
        return ""

    # Remove markdown links: [title](url) -> title
    import re
    cleaned = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"\1", text)
    # Remove plain URLs
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    # Normalize excessive blank lines
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
        snippet = content[left:right + 1]
        try:
            obj = json.loads(snippet)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


def _detect_action(action: Optional[str], message: str, response: str) -> Optional[str]:
    if action:
        return action
    text = f"{message}\n{response}".lower()
    if any(k in text for k in ["播放", "在线看", "在线播放", "play"]):
        return "play"
    if any(k in text for k in ["下载", "download"]):
        return "download"
    if any(k in text for k in ["文件夹", "目录", "folder"]):
        return "folder_info"
    if any(k in text for k in ["信息", "详情", "属性", "info"]):
        return "file_info"
    if any(k in text for k in ["搜索", "查找", "找", "search"]):
        return "search"
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
        "在线看",
        "在线播放",
        "播放",
        "看一下",
        "看一看",
        "看",
        "下载",
        "查看",
        "返回",
        "导航到",
        "打开",
        "文件夹",
        "目录",
        "文件",
        "信息",
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

    if action not in {"play", "download", "file_info", "folder_info", "search"}:
        return data

    target = _extract_target(user_message)
    if not target:
        return data

    if action == "search":
        candidates = search_nodes(session, target, limit=20)
        return {
            "keyword": target,
            "results": [
                {
                    **serialize_node(node),
                    "urls": build_file_urls(node, base_url),
                }
                for node in candidates
            ],
        }

    only_directory = action == "folder_info"
    prefer_video = action == "play"
    candidates = search_nodes(session, target, only_directory=only_directory, limit=20)

    # If user asks to play but only folder-like results exist, still return folder data
    # so frontend can render "打开对应文件夹" navigation button.
    if action == "play" and candidates:
        has_video_file = any((not node.is_directory) and build_file_urls(node, base_url).get("play_url") for node in candidates)
        if not has_video_file:
            folder_node = choose_best_match(candidates, target, prefer_directory=True, prefer_video=False)
            if folder_node:
                return {
                    "file": serialize_node(folder_node),
                    "urls": build_file_urls(folder_node, base_url),
                }

    node = choose_best_match(
        candidates,
        target,
        prefer_directory=True if only_directory else False,
        prefer_video=prefer_video,
    )
    if not node:
        return data

    return {
        "file": serialize_node(node),
        "urls": build_file_urls(node, base_url),
    }

@agent_router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
    session: Session = Depends(get_db)
):
    """
    与 Agent 对话
    """
    try:
        thread_id = request.thread_id or "default"
        base_url = str(http_request.base_url).rstrip("/")

        messages = [
            SystemMessage(content=SYSTEM_PROMPT_TEMPLATE.format(base_url=base_url)),
            HumanMessage(content=request.message),
        ]

        result = await agent_graph.ainvoke(
            {"messages": messages},
            config={"configurable": {"thread_id": thread_id}},
        )
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
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@agent_router.get("/threads/{thread_id}/history")
async def get_thread_history(thread_id: str):
    """
    获取指定会话的历史记录
    注意：这需要配置 Checkpointer 才能工作
    """
    # 简化版：返回提示信息
    return {"message": f"Thread {thread_id} history", "history": []}