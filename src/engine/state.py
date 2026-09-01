

from __future__ import annotations

import asyncio
from pathlib import Path
import aiosqlite

from typing import Annotated, Any, Dict, List, Optional, Tuple, TypedDict
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.message import add_messages

def merge_dict_state(left: dict | None, right: dict | None) -> dict:
    new_ctx = (left or {}).copy()
    if right:
        for k, v in right.items():
            if v is None:
                new_ctx.pop(k, None)  # Delete key if payload value is None
            else:
                new_ctx[k] = v
    return new_ctx

class State(TypedDict):
    messages: Annotated[list, add_messages]
    loaded_files: Annotated[Dict[str, FileData],merge_dict_state]
    llm_calls: int


class FileData(TypedDict):
    content: str
    mtime: float
    size: int