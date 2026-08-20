from pathlib import Path
import os, sys
import ast, inspect
import glob
from langchain.tools import ToolRuntime, InjectedState, InjectedToolCallId
from langgraph.types import Command
from langchain_core.tools import BaseTool, tool
from langchain_core.messages import ToolMessage
from utils.config import LOGGER
from typing import Annotated
from utils.fs import FileData

from utils.file_access import file_access_control

# 
# CORE tools packet
# 

@tool
def read_file(
    path: str,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command | str:
    """Read a NEW file from disk and add it to the active working context."""

    try:
        target = file_access_control.validate_read(path)
    except Exception as err:
        return f"read_file: {err}"

    if not target.exists():
        return f"read_file: {target}: No such file or directory"
    if not target.is_file():
        return f"read_file: {target}: Is a directory"

    rel_path = target.relative_to(Path.cwd(),walk_up=True).as_posix()
    stat = target.stat()
    try:
        content = target.read_text(encoding='utf-8')
    except Exception as err:
        return f"read_file: {err}"
    
    line_count = len(content.splitlines())
    current_files = dict(state.get("loaded_files", {}))
    current_files[rel_path] = FileData(
        content=content, size=stat.st_size, mtime=stat.st_mtime_ns
    )
    LOGGER.info(f"read_file cached {current_files}")

    return Command(
        update={
            "loaded_files": current_files,
            "messages": [
                ToolMessage(
                    content=f"Successfully cached '{path}' ({line_count} lines) in active memory.",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )

@tool
def write_file(
    path: str,
    content:str,
) -> str:
    """
    Write provided content into the specified file path.
    Create parent folder if it doesn't exist
    """

    try:
        target = file_access_control.validate_write(path)
    except Exception as err:
        return f"write_file: {err}"
    
    if target.is_dir():
        return f"write_file: '{path}': Is a directory"

    # create directory if not exists
    target.parent.mkdir(exist_ok=True,parents=True)
    target.write_text(data=content,encoding='utf-8')
    rel_path = target.relative_to(Path.cwd(), walk_up=True).as_posix()
    
    LOGGER.info(f"write to file {rel_path}")
    return f"Successfully wrote content to '{rel_path}'"

@tool
def glob_tool(glob_pattern: str) -> str:
    """
    Glob tool, accept wildcard syntax an return list of related filepath as string, one entry per line
    """
    matches: list[str] = []
    for g in glob_pattern.split():  # handle multientry glob
        for path in glob.glob(g, recursive=True):
            try:
                safe_path = file_access_control.validate_read(path)
                rel_path = safe_path.relative_to(Path.cwd(),walk_up=True).as_posix()
                matches.append(rel_path)
            except PermissionError:
                continue
    if len(matches) == 0:
        return f"No matches found, test other pattern"
    
    return "\n".join(list(dict.fromkeys(matches)))

tools = [ obj for _, obj in globals().items() if isinstance(obj, BaseTool) ]
LOGGER.info(f"Loaded {len(tools)} tools: {str([t.name for t in tools])}")

