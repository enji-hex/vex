from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from vex_shell.utils.config import LOGGER

if TYPE_CHECKING:
    from langchain_core.messages import AIMessage, AnyMessage
    from .state import FileData


def msg_get_text(msg: AnyMessage) -> str:
    """Return AnyMessage as plain text"""
    content = msg.content
    if isinstance(content, list):
        return " ".join([b.get("text", "") for b in content if b.get("type") == "text"])
    else:
        return str(content)

def show_context_hook(parts: list[str]):
    """Summarizes context components for transparent debugging."""
    debug_str = "[ CONTEXT-START ]\n"
    for part in parts:
        if part.startswith("```"):
            path = part.split("\n")[0].replace("```", "").strip()
            debug_str += f"[FILE] Loaded: {path} ({len(part)} chars)\n"
        elif "<env_metadata>" in part:
            debug_str += f"[ENV]\n{part}\n"
        elif "<history>" in part:
            debug_str += f"[HISTORY] ({len(part)} chars)\n"
        elif "<active_context>" in part:
            debug_str += f"[CONTEXT] ({len(part)} chars)\n"
        elif "<user_prompt>" in part:
            debug_str += f"[PROMPT] ({len(part)} chars)\n"
        elif "<cwd_tree>" in part:
            debug_str += f"[TREE] ({len(part)} chars)\n"
        else:
            debug_str += f"[OTHER] {part[:50]}...\n"
    debug_str += "[ CONTEXT-END ]\n"
    LOGGER.debug(debug_str)

async def get_saved_sessions(db_path: str | Path) -> list[str]:
    import aiosqlite

    path = Path(db_path)
    if not path.exists():
        return []

    async with aiosqlite.connect(path) as db:
        async with db.execute("SELECT DISTINCT thread_id FROM checkpoints") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


def get_safe_window(messages: list, target_window: int) -> list:
    """target_window = -1, disable target window"""

    from langchain_core.messages import HumanMessage, ToolMessage

    if target_window != -1 and len(messages) > target_window:
        sliced = messages[-target_window:]
        for i, msg in enumerate(sliced):
            # truncate Set Human message at beginning
            if isinstance(msg, HumanMessage):
                sliced = sliced[i:]
                break
    else:
        sliced = messages

    pruned = []
    for msg in sliced:
        if isinstance(msg, ToolMessage):
            tool_name = msg.name
            if len(msg.content) > 200 and tool_name != "tree_tool":
                # We can't delete tool call message, but
                # we can truncate long ToolCall messages
                msg = ToolMessage(
                    content=f"[Output truncated: {msg.content[:100]}...]",
                    tool_call_id=msg.tool_call_id,
                    id=msg.id,
                )
        pruned.append(msg)

    return pruned


def format_chat_plain(
    history: list[AnyMessage],
    system_message: str,
    prompt: str,
    loaded_files: dict[str, FileData],
    env_block: str,
    use_vision: bool,
    cwd_tree: str | None = None,
    hook: Callable | None = None,
) -> tuple[list[AnyMessage], list]:
    """
    Construct Ephemeral chat version from the *already-synced* loaded_files dict.
    Returns (payload_messages, image_paths) where image_paths is a list of
    keys that were injected as images and should be purged afterwards.

    <history> <active_context> <user_prompt>
    Where:
        <active_context> = <env_metadata> <file(s)> <cwd_tree>

    We can store each part of final answer as list entry, and use 'hooks'
    """

    from langchain_core.messages import SystemMessage, HumanMessage

    image_blocks = []
    image_paths: list[str] = []
    histor_str = format_chat_history(history)

    result = [
        f"{env_block}\n",
        f"<history>\n{histor_str}\n</history>",
        f"<active_context>\n",
    ]

    for path, info in loaded_files.items():
        if info["content"].startswith("data:image/"):
            if use_vision:
                image_blocks.append({"type": "text", "text": f"\n--- File: {path} ---"})
                image_blocks.append(
                    {"type": "image_url", "image_url": {"url": info["content"]}}
                )
                image_paths.append(path)
            else:
                image_blocks.append(
                    {
                        "type": "text",
                        "text": f"\n--- File: {path} [IMAGE LOADED (Vision Disabled)] ---",
                    }
                )
        else:
            result.append(f"```{path}\n{info['content']}\n```")  

    if cwd_tree:
        result.append(f"<cwd_tree>\n{cwd_tree}\n</cwd_tree>")
    result.append(f"\n\n<user_prompt>\n{prompt}\n</user_prompt>")

    # apply hook before flat result into string
    if hook:
        hook(result)

    result = "".join(result)

    if image_blocks:
        human_content = [{"type": "text", "text": result}] + image_blocks
        payload = [
            SystemMessage(content=system_message),
            HumanMessage(content=human_content),
        ]
    else:
        payload = [SystemMessage(content=system_message), HumanMessage(content=result)]
    return payload, image_paths


def format_chat_history(messages: list) -> str:
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

    lines = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "User"
        elif isinstance(msg, AIMessage):
            role = msg.response_metadata.get("role", "Assistant")
        elif isinstance(msg, ToolMessage):
            role = f"Tool({msg.name})"
        else:
            role = "Unknown"
        content = msg_get_text(msg)
        if role.startswith("Tool"):
            content = content[:200] + ("..." if len(content) > 200 else "")

        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def normalize_tool_calls(msg: AIMessage, tool_names: list[str]) -> AIMessage:
    from langchain_core.messages import ToolCall

    if msg.tool_calls:
        return msg

    text = (
        " ".join(b.get("text", "") for b in msg.content)
        if isinstance(msg.content, list)
        else ""
    )
    dec, pos, calls = json.JSONDecoder(), 0, []

    while (pos := text.find("{", pos)) != -1:
        try:
            d, pos = dec.raw_decode(text, idx=pos)
            if isinstance(d, dict) and (name := d.get("name")) in tool_names:
                args = d.get("arguments") or d.get("args") or {}
                LOGGER.info(f"fallback tool call {name} {args!s}")
                calls.append(
                    ToolCall(name=name, args=args, id=f"call_{uuid.uuid4().hex[:8]}")
                )
        except json.JSONDecodeError:
            pos += 1

    if calls:
        msg.tool_calls, msg.content = calls, ""
    return msg


_ENC = None


def count_tokens(text: str) -> int:
    import tiktoken

    global _ENC
    if not _ENC:
        _ENC = tiktoken.get_encoding("cl100k_base")
    return len(_ENC.encode_ordinary(text))
