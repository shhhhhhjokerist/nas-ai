# app/agents/router.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
from langchain_core.messages import HumanMessage, AIMessage

from app.agents.graph import agent_graph
from app.db import get_db
from sqlalchemy.orm import Session

agent_router = APIRouter(prefix="/agent", tags=["agent"])

class ChatRequest(BaseModel):
    message: str
    # thread_id: str | None = None  # 可选：会话 ID
    thread_id: str = None

class ChatResponse(BaseModel):
    response: str
    thread_id: str

@agent_router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    session: Session = Depends(get_db)
):
    """
    与 Agent 对话
    """
    try:
        # 配置 thread_id 用于状态持久化（可选）
        config = {"configurable": {"thread_id": request.thread_id or "default"}}
        
        # 调用 agent
        messages = [HumanMessage(content=request.message)]
        result = await agent_graph.ainvoke(
            {"messages": messages},
            config=config
        )
        
        # 提取最终响应
        final_message = result["messages"][-1]
        response_content = final_message.content if hasattr(final_message, "content") else str(final_message)
        
        return ChatResponse(
            response=response_content,
            thread_id=request.thread_id or "default"
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