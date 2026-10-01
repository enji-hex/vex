from __future__ import annotations
from functools import partial
from typing import List, Optional, Tuple, TYPE_CHECKING


# from langgraph.graph import START, END 
# thi shit imports ENTIRE langgraph.graph module!!!
END   = "__end__"
START = "__start__"

# import only for type checking
if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from vex_shell.mcp_tools.tools_mcp import MCPManager
    from langgraph.graph.state import  StateGraph
    from vex_shell.utils.config import Settings
    from .state import State
    

async def get_tools(settings:Settings) -> Tuple[List[BaseTool], Optional[MCPManager]]:
    from ..tools.tools import get_tools
    tools = get_tools()
    if settings.chat["use_mcp"]:
        from vex_shell.mcp_tools.tools_mcp import load_mcp_tools

        mcp_tools, mcp_manager = await load_mcp_tools()
        tools.extend(mcp_tools)
    else:
        mcp_manager = None
        
    return tools,mcp_manager

def build_graph(settings: Settings, tools:List[BaseTool]) -> StateGraph:
    from langgraph.graph.state import  StateGraph
    from langgraph.prebuilt import ToolNode

    from .nodes import llm_call_node, verification_node, should_continue, should_verify
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
        "tool_node",  # source node
        should_verify,  # check condition
        # path maps
        # llm_call str -> route to llm_call function
        {"verification_node": "verification_node", "llm_call": "llm_call"},
    )
    graph.add_edge("verification_node", "llm_call")
    return graph