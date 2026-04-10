# app/agents/graph.py
from typing import Annotated, Literal
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import AIMessage, ToolMessage


# 定义状态
class State(TypedDict):
    messages: Annotated[list, add_messages]

# 定义工具（可选）- 可以调用你的数据库或 API
@tool
def get_user_info(user_id: str) -> str:
    """根据用户 ID 获取用户信息"""
    # 这里可以调用你的数据库
    return f"用户 {user_id} 的信息..."

@tool
def query_media_files(query: str) -> str:
    """根据关键词查询媒体文件"""
    # 这里可以调用你现有的数据库查询
    return f"找到以下媒体文件: ..."

@tool
def 

# 创建图
def create_agent_graph():
    # 初始化 LLM
    # llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    # llm = ChatOpenAI(model='glm-4.7-flash',
    llm = ChatOpenAI(model='glm-4.7-flashX',
                     base_url='https://open.bigmodel.cn/api/paas/v4/',
                     api_key="",
                     temperature=0.3,
                     max_tokens=512
                     )
    
    # 绑定工具
    tools = [get_user_info, query_media_files]
    llm_with_tools = llm.bind_tools(tools)
    
    # 定义节点函数
    def chatbot(state: State):
        """聊天机器人节点"""
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}
    
    def tool_node(state: State):
        """工具执行节点"""
        messages = state["messages"]
        last_message = messages[-1]
        
        tool_calls = last_message.tool_calls
        results = []
        for tc in tool_calls:
            if tc["name"] == "get_user_info":
                result = get_user_info.invoke(tc["args"])
            elif tc["name"] == "query_media_files":
                result = query_media_files.invoke(tc["args"])
            else:
                result = f"Unknown tool: {tc['name']}"
            
            results.append(
                ToolMessage(content=result, tool_call_id=tc["id"])
            )
        
        return {"messages": results}
    
    # 定义路由
    def should_continue(state: State) -> Literal["tools", END]:
        messages = state["messages"]
        last_message = messages[-1]
        
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return END
    
    # 构建图
    graph = StateGraph(State)
    graph.add_node("chatbot", chatbot)
    graph.add_node("tools", tool_node)
    
    graph.add_edge(START, "chatbot")
    graph.add_conditional_edges("chatbot", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "chatbot")
    
    return graph.compile()

# 创建全局 graph 实例
agent_graph = create_agent_graph()