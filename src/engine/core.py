
from __future__ import annotations

import asyncio
from pathlib import Path
import aiosqlite

from typing import Annotated, Any, Dict, List, Optional, Tuple, TypedDict
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain.messages import ToolMessage

from langgraph.graph import START, END

from langgraph.graph.state import CompiledStateGraph, StateGraph
from functools import partial
from langchain_openrouter import ChatOpenRouter
from langchain_openai import ChatOpenAI

from langgraph.prebuilt import ToolNode
from tools.tools import tools

from utils.config import LOGGER,Settings
from utils.fs import FileData, sync_loaded_files
from utils.file_access import file_access_control

from .nodes import llm_call_node,verification_node,should_continue,should_verify
from .state import State
from .stream_processor import Agent

def build_graph(settings:Settings,tool_names:List[str]) -> StateGraph:
    graph = StateGraph(State)
    
    # LLM Nodes
    graph.add_node("llm_call", partial(llm_call_node,
                                       settings=settings,
                                       tool_names=tool_names))
    graph.add_node("tool_node", ToolNode(tools))
    graph.add_node("verification_node", partial(
        verification_node,settings=settings))
    

    # Graph Edges
    graph.add_edge(START, "llm_call")
    graph.add_conditional_edges(
        "llm_call", should_continue, ["tool_node", END]
    )
    graph.add_conditional_edges(
        "tool_node",   # source node
        should_verify, # check condition 
        # path maps
        # llm_call str -> route to llm_call function
        {
            "verification_node": "verification_node",
            "llm_call": "llm_call"
        }
    )
    graph.add_edge("verification_node", "llm_call")
    return graph

async def run_agent(console,settings:Settings,session_id:str = "default"):
    if settings.chat['use_mcp']:
        from mcp_tools.tools_mcp import load_mcp_tools
        mcp_tools,mcp_manager = await load_mcp_tools()
        tools.extend(mcp_tools)
        LOGGER.info('MCP tools loaded')
    else:
        mcp_manager = None

    
    tool_names = [e.name for e in tools]
    graph = build_graph(settings,tool_names)
    
    agent = await Agent.create(graph,session_id,settings,mcp_manager)
    LOGGER.info(f'use_vision {settings.model["use_vision"]}')

    from ui.console import start_session
    try:
        await start_session(agent,console)
    finally:
        await agent.close()

