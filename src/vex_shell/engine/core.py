from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

# from langgraph.graph import START, END 
# thi shit imports ENTIRE langgraph.graph module!!!
END   = "__end__"
START = "__start__"

# import only for type checking
if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from langgraph.graph.state import StateGraph

    from vex_shell.mcp_tools.tools_mcp import MCPManager
    from vex_shell.utils.config import Settings

    
async def get_tools(settings:Settings) -> tuple[list[BaseTool], MCPManager | None]:
    from ..tools.tools import get_tools
    tools = get_tools()
    mcp_manager = None
    
    if settings.chat["use_mcp"]:
        from vex_shell.mcp_tools.tools_mcp import load_mcp_tools
        mcp_tools, mcp_manager = await load_mcp_tools()
        tools.extend(mcp_tools)
        
    return tools,mcp_manager

def build_graph(settings: Settings, tools:list[BaseTool]) -> StateGraph:
    from langgraph.graph.state import StateGraph
    from langgraph.prebuilt import ToolNode

    from .nodes import llm_call_node, should_continue, should_verify, verification_node
    from .state import State
    
    graph = StateGraph(State)
    
    # LLM Nodes
    graph.add_node(
        "llm_call", partial(llm_call_node, settings=settings,tools=tools)
    )
    graph.add_node("tool_node", ToolNode(tools))
    graph.add_node("verification_node", partial(verification_node, settings=settings))

    # Graph Edges
    graph.add_edge(START, "llm_call")
    graph.add_conditional_edges("llm_call", should_continue, ["tool_node", END])
    graph.add_conditional_edges(
        "tool_node",    # source node
        partial(should_verify,settings=settings),  # check condition
        # path maps
        # llm_call str -> route to llm_call function
        {"verification_node": "verification_node", "llm_call": "llm_call"},
    )
    graph.add_edge("verification_node", "llm_call")
    return graph