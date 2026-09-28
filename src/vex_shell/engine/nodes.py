from __future__ import annotations

import asyncio
import os

from typing import Annotated, Any, Dict, List, Optional, Tuple, TypedDict
from langchain_core.runnables import RunnableConfig
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
    ToolCall,
)
from langgraph.prebuilt import ToolNode
from vex_shell.tools.tools import tools

from vex_shell.utils.config import Settings, LOGGER
from vex_shell.utils.file_access import file_access_control

from .state import State
from vex_shell.utils.fs import sync_loaded_files,sync_cwd_tree
from .helpers import (
    get_safe_window,
    format_file_context,
    normalize_tool_calls,
)


# LLM NODES
async def llm_call_node(
    state: State, config: RunnableConfig, settings: Settings, tool_names: List[str]
):
    """
    Handle errors
    - 429
    - Bad model
    - No tool support
    """

    llm_cfg = settings.model
    current_calls = state.get("llm_calls", 0) + 1

    # sync all loaded files
    new_files_snap = sync_loaded_files(state.get("loaded_files", {}))
    cwd_tree       = sync_cwd_tree(state) if settings.chat.get('autosync_cwd_tree',False) else None

    # handle sliding window
    window: int = llm_cfg.get("context_sliding_window", -1)
    recent = get_safe_window(state["messages"], window)
    
    system_msg = SystemMessage(content=settings.system_prompt)

    # Handle file_context
    env_block = file_access_control.build_environment_context()
    context_blocks: list = format_file_context(
        state,
        env_block,
        config.get("configurable", {}).get("use_vision", False),
    )

    ephemeral_context_msg = HumanMessage(
        content=[{"type": "text", "text": "--- ACTIVE FILE CONTEXT (GROUND TRUTH) ---"}]
        + context_blocks
    )
    payload_messages = [system_msg] + recent + [ephemeral_context_msg]

    # reasoning
    # https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
    # timeout trigger error(maybe)

    if llm_cfg["provider"] == "openrouter":
        llm = ChatOpenRouter(
            model=llm_cfg["name"],
            api_key=os.environ.get("VEX_API_KEY"),
            base_url=llm_cfg.get("llm_url", "https://openrouter.ai/api/v1"),
            temperature=llm_cfg["temperature"],
            max_completion_tokens=llm_cfg["max_completion_tokens"],
            max_retries=int(llm_cfg["max_retries"]),
            stream_usage=True,
            streaming=True,
            reasoning=llm_cfg["reasoning"],
            model_kwargs=llm_cfg.get("extra_body", {}),
        )
    elif llm_cfg["provider"] == "ollama":
        stream_chunk_timeout = llm_cfg.get('ollama',{})\
            .get('stream_chunk_timeout','0')
        
        llm = ChatOpenAI(
            model=llm_cfg["name"],
            base_url=llm_cfg.get("llm_url", "http://localhost:11434/v1"),
            api_key="ollama",
            temperature=llm_cfg["temperature"],
            max_completion_tokens=llm_cfg.get("max_completion_tokens"),
            max_retries=int(llm_cfg["max_retries"]),
            streaming=True,
            stream_usage=True,
            stream_chunk_timeout=int(stream_chunk_timeout),
            extra_body=llm_cfg.get("extra_body", {}),
        )
    else:
        raise RuntimeError("LLM provider undefined")

    LOGGER.info(f'extra body {llm_cfg.get("extra_body",{})}')
    llm_with_tools = llm.bind_tools(tools)

    resp = await llm_with_tools.ainvoke(payload_messages, config=config)

    finish_reason = resp.additional_kwargs.get("finish_reason")
    if finish_reason == "length":
        LOGGER.warning(
            f'response was truncated by token limit {settings.model.get("max_completion_tokens")}, fallback'
        )

        # Prevent tool calls ,force tool_calls to be empty so 'should_continue'
        # returns END instead of 'tool_node'
        resp.tool_calls = []
        warning_msg = SystemMessage(
            content="[SYSTEM: Your previous response was truncated due to token limits. "
            "Please continue exactly where you left off in your next response.]"
        )
        return {
            "messages": [resp, warning_msg],
            "llm_calls": current_calls,
            "loaded_files": new_files_snap,
        }

    resp = normalize_tool_calls(resp, tool_names)
    return {
        "messages": [resp],
        "llm_calls": current_calls,
        "loaded_files": new_files_snap,
        "cwd_tree":cwd_tree,
    }


def should_verify(state: State):
    last_msg = state["messages"][-1]

    if isinstance(last_msg, ToolMessage) and last_msg.name == "write_file":
        LOGGER.info("should verify , last mesage write")
        return "verification_node"
    return "llm_call"


async def verification_node(state: State, settings: Settings):

    check_cmd = settings.verification.get("check_command")

    if check_cmd:
        proc = await asyncio.subprocess.create_subprocess_shell(
            check_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=file_access_control.cwd,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        LOGGER.info(f'VERIFY RES {str(stdout_bytes.decode("utf-8"))} \
                    {str(stderr_bytes.decode("utf-8"))}')

        if proc.returncode != 0:
            output = (
                (stderr_bytes or stdout_bytes).decode("utf-8", errors="replace").strip()
            )
            return {
                "messages": [
                    HumanMessage(
                        content=f"Build/Check failed (`{check_cmd}`):\n{output}"
                    )
                ]
            }

    return {}

def should_continue(state: State):
    messages = state.get("messages",[])
    if not messages:
        return END

    last = messages[-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tool_node"
    return END
