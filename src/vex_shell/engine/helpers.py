from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vex_shell.utils.config import LOGGER

if TYPE_CHECKING:
    from langchain_core.messages import AIMessage

    from .state import FileData

async def get_saved_sessions(db_path:str|Path) -> list[str]:
    import aiosqlite
    path = Path(db_path)
    if not path.exists(): return []

    async with aiosqlite.connect(path) as db:
        async with db.execute("SELECT DISTINCT thread_id FROM checkpoints") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

def get_safe_window(messages:list, target_window:int) -> list:
    """ target_window = -1, disable target window"""
    
    from langchain_core.messages import HumanMessage, ToolMessage

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
            if len(msg.content) > 200 and tool_name != "tree_tool":
                # We can't delete tool call message, but 
                # we can truncate long ToolCall messages
                msg = ToolMessage(
                    content=f"[Output truncated: {msg.content[:100]}...]",
                    tool_call_id=msg.tool_call_id,
                    id=msg.id
                )
        pruned.append(msg)
    
    return pruned

def format_file_context(
        loaded_files: dict[str, FileData],
        env_block: str,
        use_vision: bool,
        cwd_tree: str | None = None,
    ) -> tuple[list[dict[str,Any]],list]:
    """
    Build context blocks from the *already-synced* loaded_files dict.
    Returns (content_blocks, image_paths) where image_paths is a list of
    keys that were injected as images and should be purged afterwards.
    """

    content_blocks = []
    image_paths: list[str] = []

    header_text = (
        f"{env_block}\n"
        f"--- ACTIVE WORKING CONTEXT (GROUND TRUTH) ---\n"
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
                image_paths.append(path)
            else:
                content_blocks.append({
                    "type": "text", 
                    "text": f"\n--- File: {path} [IMAGE LOADED (Vision Disabled)] ---"})
        else:
            content_blocks.append({
                "type":"text",
                "text":f"```{path}\n{info['content']}\n```"
            })
    
    if cwd_tree:
        content_blocks.append({
            "type": "text",
            "text": f"### Active Working Directory Tree\n\n{cwd_tree}\n"
        })
    
    LOGGER.debug(str(content_blocks))
    return content_blocks, image_paths


def normalize_tool_calls(msg:AIMessage,tool_names:list[str]) -> AIMessage:
    from langchain_core.messages import ToolCall

    if msg.tool_calls: return msg
    
    text = " ".join(b.get("text", "") for b in msg.content) if isinstance(msg.content, list) else ""
    dec, pos, calls = json.JSONDecoder(), 0, []

    while (pos := text.find("{",pos)) != -1:
        try:
            d, pos = dec.raw_decode(text,idx=pos)
            if isinstance(d,dict) and (name  := d.get("name")) in tool_names:
                args = d.get("arguments") or d.get("args") or {}
                LOGGER.info(f'fallback tool call {name} {args!s}')
                calls.append(ToolCall(name=name,args=args,id=f'call_{uuid.uuid4().hex[:8]}'))
        except json.JSONDecodeError:
            pos += 1

    if calls: msg.tool_calls, msg.content = calls,""
    return msg

_ENC = None
def count_tokens(text: str) -> int:
    import tiktoken
    global _ENC
    if not _ENC:
        _ENC  = tiktoken.get_encoding("cl100k_base")
    return len(_ENC.encode_ordinary(text))

