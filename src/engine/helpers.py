
from __future__ import annotations

import asyncio
from pathlib import Path
import aiosqlite

from typing import Annotated, Any, Dict, List, Optional, Tuple, TypedDict
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langchain.messages import ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import START, END
from langgraph.graph.message import add_messages

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

from utils.config import LOGGER,Settings
from utils.fs import FileData, sync_loaded_files

from utils.file_access import file_access_control



def get_safe_window(messages:list, target_window:int) -> list:
    if target_window != -1 and len(messages) > target_window:
        sliced = messages[-target_window:]
        for i,msg in enumerate(sliced):
            # truncate Set Human message at beginning
            if isinstance(msg,HumanMessage):
                sliced = sliced[i:];break
    else:
        sliced = messages
    
    pruned = []
    for msg in sliced:
        if isinstance(msg,ToolMessage):
            tool_name = msg.name
            LOGGER.info(f'tool name {tool_name}')
            if len(msg.content) > 200 and tool_name != "tree_tool":
                # truncate long ToolCall messages
                msg = ToolMessage(
                    content=f"[Output truncated: {msg.content[:100]}...]",
                    tool_call_id=msg.tool_call_id,
                    id=msg.id
                )
        pruned.append(msg)
    
    return pruned

def format_file_context(
        env_block:str,
        loaded_files: Dict[str, FileData],
        use_vision:bool
    ) -> List[Dict[str,Any]]:

    content_blocks = []
    header_text = (
        f"{env_block}\n"
        f"--- ACTIVE WORKING CONTEXT (GROUND TRUTH) ---\n"
        f"### Active Working Context (Latest File Versions)\n"
    )
    
    content_blocks.append({"type":"text","text":header_text})
    for path, info in loaded_files.items():
        if info['content'].startswith("data:image/"):
            if use_vision:
                content_blocks.append({
                    "type":"text",
                    "text":f"\n--- File: {path} ---"
                })
                content_blocks.append({
                    "type":"image_url",
                    "image_url":{"url":info['content']}
                })
            else:
                content_blocks.append({
                    "type": "text", 
                    "text": f"\n--- File: {path} [IMAGE LOADED (Vision Disabled)] ---"})
        else:
            content_blocks.append({
                "type":"text",
                "text":f"```{path}\n{info['content']}\n```"
            })
    
    return content_blocks


def normalize_tool_calls(msg:AIMessage,tool_names:List[str]) -> AIMessage:
    if msg.tool_calls: return msg
    
    text = " ".join(b.get("text", "") for b in msg.content) if isinstance(msg.content, list) else ""
    dec, pos, calls = json.JSONDecoder(), 0, []

    while (pos := text.find("{",pos)) != -1:
        try:
            d, pos = dec.raw_decode(text,idx=pos)
            if isinstance(d,dict) and (name  := d.get("name")) in tool_names:
                args = d.get("arguments") or d.get("args") or {}
                LOGGER.info(f'fallback tool call {name} {str(args)}')
                calls.append(ToolCall(name=name,args=args,id=f'call_{uuid.uuid4().hex[:8]}'))
        except json.JSONDecodeError:
            pos += 1

    if calls: msg.tool_calls, msg.content = calls,""
    return msg