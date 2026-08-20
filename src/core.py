
from __future__ import annotations

from pathlib import Path
import aiosqlite

from typing import Annotated, Dict, List, Optional, Tuple, TypedDict
from langchain_core.tools import BaseTool
from langchain.messages import ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import START, END
from langgraph.graph.message import add_messages

from langgraph.graph.state import CompiledStateGraph, StateGraph
from functools import partial
from langchain_openrouter import ChatOpenRouter
from langchain_openai import ChatOpenAI
from langchain.messages import (
    HumanMessage,
    AnyMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
    ToolCall
)
from langgraph.prebuilt import ToolNode
from tools.tools import tools
import openai
import re
import json
import uuid

from utils import config
from utils.fs import FileData, sync_loaded_files

import os
import time
from utils.file_access import file_access_control

start_time = time.perf_counter()

def merge_dict_state(left: dict | None, right: dict | None) -> dict:
    return (left or {}) | (right or {})

class State(TypedDict):
    messages: Annotated[list, add_messages]
    loaded_files: Annotated[Dict[str, FileData],merge_dict_state]
    llm_calls: int

# HEPLERS
def get_safe_window(messages:list, target_window:int) -> list:
    if target_window == -1 or len(messages) <= target_window:
        return messages
    sliced = messages[-target_window:]
    for i,msg in enumerate(sliced):
        if isinstance(msg,HumanMessage):
            return sliced[i:]
    return messages

def format_file_context(loaded_files: Dict[str, FileData]) -> str:
    if not loaded_files:
        return ""

    blocks = ["\n### Active Working Context (Latest File Versions)\n"]
    for path, info in loaded_files.items():
        blocks.append(f"```{path}\n{info['content']}\n```")
    return "\n".join(blocks)


def normalize_tool_calls(msg:AIMessage,tool_names:List[str]) -> AIMessage:
    if msg.tool_calls: return msg
    
    text = " ".join(b.get("text", "") for b in msg.content) if isinstance(msg.content, list) else ""
    dec, pos, calls = json.JSONDecoder(), 0, []

    while (pos := text.find("{",pos)) != -1:
        try:
            d, pos = dec.raw_decode(text,idx=pos)
            if isinstance(d,dict) and (name  := d.get("name")) in tool_names:
                args = d.get("arguments") or d.get("args") or {}
                config.LOGGER.info(f'fallback tool call {name} {str(args)}')
                calls.append(ToolCall(name=name,args=args,id=f'call_{uuid.uuid4().hex[:8]}'))
        except json.JSONDecodeError:
            pos += 1

    if calls: msg.tool_calls, msg.content = calls,""
    return msg


# LLM NODES
async def llm_call_node(state: State,settings,tool_names:List[str]):
    """
    Handle errors
    - 429
    - Bad model
    - No tool support
    
    """
    
    llm_cfg = settings.model
    current_calls  = state.get("llm_calls", 0) + 1

    # sync all loaded files
    new_files_snap = sync_loaded_files(state.get("loaded_files", {}))
    config.LOGGER.info(
        f"cached files {str(', '.join([f for f in new_files_snap.keys()]))}"
    )

    # handle sliding window  
    window:int = llm_cfg.get('context_sliding_window',-1)
    recent = get_safe_window(state['messages'],window)
    
    system_msg = SystemMessage(content=settings.system_prompt)
    messages:list = [system_msg] + recent

    # Handle file_context
    env_block = file_access_control.build_environment_context()
    file_block = format_file_context(new_files_snap)
    
    # always in WORKING_CONTEXT
    ground_truth_block  = (
        f"{env_block}\n" 
        f"--- ACTIVE WORKING CONTEXT (GROUND TRUTH) ---\n"
    )
    # append only if file context present
    if file_block:
        ground_truth_block += f"{file_block}\n" 
    
    # Attach context to the last message
    last_msg = messages[-1]
    updated = f"{last_msg.content}\n\n{ground_truth_block}"

    if isinstance(last_msg, HumanMessage):
        messages[-1] = HumanMessage(content=updated, id=last_msg.id)
    elif isinstance(last_msg, ToolMessage):
        messages[-1] = ToolMessage(
            content=updated,
            tool_call_id=last_msg.tool_call_id,
            id=last_msg.id,
        )
    elif isinstance(last_msg,AIMessage):
        messages[-1] = AIMessage(
            content=updated,
            tool_calls=last_msg.tool_calls,
            id=last_msg.id,
        )
    
    # reasoning 
    # https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
    # timeout trigger error(maybe)

    if llm_cfg['provider'] == "openrouter":
        llm = ChatOpenRouter(
            model=llm_cfg['name'],
            api_key=os.environ.get('VEX_API_KEY'),
            base_url=llm_cfg.get('llm_url',"https://openrouter.ai/api/v1"),
            temperature=llm_cfg['temperature'],
            max_completion_tokens=llm_cfg['max_completion_tokens'],
            max_retries=int(llm_cfg['max_retries']),
            stream_usage=True,
            streaming=True,
            reasoning=llm_cfg['reasoning'],
            model_kwargs=llm_cfg.get('extra_body',{})
            
        )
    elif llm_cfg['provider'] == "ollama":
        llm = ChatOpenAI(
            model=llm_cfg['name'],
            base_url=llm_cfg.get('llm_url',"http://localhost:11434/v1"),
            api_key="ollama",
            temperature=llm_cfg['temperature'],
            max_completion_tokens=llm_cfg.get('max_completion_tokens'),
            max_retries=int(llm_cfg['max_retries']),
            model_kwargs=llm_cfg.get('extra_body', {}),
            streaming=True,
            stream_usage=True
        )
    else:
        raise RuntimeError("LLM provider undefined")
    
    config.LOGGER.info(f'extra body {llm_cfg.get("extra_body",{})}')
    llm_with_tools = llm.bind_tools(tools)

    resp = await llm_with_tools.ainvoke(messages)
    resp = normalize_tool_calls(resp,tool_names)

    return {
        "messages": [resp],
        "llm_calls": current_calls,
        "loaded_files": new_files_snap,
    }

def should_continue(state: State):
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tool_node"
    return END

async def run_agent(console,settings,session_id:str):
    graph = StateGraph(State)
    
    
    if settings.chat['use_mcp']:
        from mcp_tools.tools_mcp import load_mcp_tools
        mcp_tools,mcp_manager = await load_mcp_tools()
        tools.extend(mcp_tools)
        config.LOGGER.info('MCP tools loaded')
    else:
        mcp_manager = None

    tools_names = [e.name for e in tools]
    graph.add_node("llm_call", partial(llm_call_node,
                                       settings=settings,
                                       tool_names=tools_names))
    graph.add_node("tool_node", ToolNode(tools))
    graph.add_edge(START, "llm_call")
    graph.add_conditional_edges(
        "llm_call", should_continue, ["tool_node", END]
    )
    graph.add_edge("tool_node", "llm_call")

    db_path = Path.cwd() / ".vex" / "session.db"
    conn = await aiosqlite.connect(str(db_path))
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()

    agent: CompiledStateGraph = graph.compile(checkpointer=checkpointer)

    from ui.console import start_session
    try:
        await start_session(agent,settings,console,session_id)
    finally:
        await conn.close()
        if mcp_manager:
            await mcp_manager.aclose()

