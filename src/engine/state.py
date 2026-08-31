

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

from langgraph.graph.state import CompiledStateGraph, StateGraph
from functools import partial
from langchain_openrouter import ChatOpenRouter
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode
from tools.tools import tools

from utils.fs import FileData

def merge_dict_state(left: dict | None, right: dict | None) -> dict:
    return (left or {}) | (right or {})

class State(TypedDict):
    messages: Annotated[list, add_messages]
    loaded_files: Annotated[Dict[str, FileData],merge_dict_state]
    llm_calls: int