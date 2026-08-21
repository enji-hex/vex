from pathlib import Path
import os, sys
import ast, inspect
import glob
from langchain.tools import ToolRuntime, InjectedState, InjectedToolCallId
from langgraph.types import Command
from langchain_core.tools import BaseTool, tool
from langchain_core.messages import ToolMessage
from utils.config import LOGGER
from typing import Annotated, List
from utils.fs import FileData
from collections import defaultdict
import asyncio

from utils.file_access import file_access_control

# 
# CORE tools packet
# 


@tool
def read_files(
    paths: List[str],
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command | str:
    """Read multiple NEW files from disk and add it to the active working context."""
    loaded = dict(state.get("loaded_files",{}))
    msgs =  []

    for p in paths:
        try:
            target = file_access_control.validate_read(p)
        except Exception as err:
            msgs.append(f"read_files: {err}")
            continue
        if not target.is_file():
           msgs.append(f"read_files: {p}: not a file")
           continue

        rel_path = target.relative_to(Path.cwd(),walk_up=True).as_posix()
        try:
            content = target.read_text(encoding='utf-8')
        except Exception as err:
            msgs.append(f"read_files: {err}")
            continue

        stat = target.stat()
        loaded[rel_path] = FileData(
            content=content,size=stat.st_size,mtime=stat.st_mtime_ns)
        msgs.append(f"cached '{p}' ({len(content.splitlines())}) lines")
    
    if not msgs:
        return "read_files: no files were read"
    
    return Command(
        update={
            "loaded_files": loaded,
            "messages": [
                ToolMessage(
                    content="\n".join(msgs),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


    
@tool
async def write_file(
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

    lock = file_access_control.get_write_lock(target)
    async with lock:
        # create directory if not exists
        target.parent.mkdir(exist_ok=True,parents=True)
        target.write_text(data=content,encoding='utf-8')
    
    rel_path = target.relative_to(Path.cwd(), walk_up=True).as_posix()
    LOGGER.info(f"write to file {rel_path}")
    return f"Successfully wrote content to '{rel_path}'"

@tool
def glob_tool(glob_patterns: List[str]) -> str:
    """
    Glob tool, accept list of wildcard syntax an return list of related filepath as string, one entry per line
    """
    matches: list[str] = []

    for g in glob_patterns:  # handle multientry glob
        for path in glob.glob(g, recursive=True):
            try:
                safe_path = file_access_control.validate_read(path)
                try:
                    rel_path = safe_path.relative_to(
                        Path.cwd(),walk_up=True
                        ).as_posix()
                except ValueError:
                    rel_path = safe_path.as_posix()

                matches.append(rel_path)
            except PermissionError:
                continue

    if len(matches) == 0:
        return f"No matches found, test other pattern"
    
    return "\n".join(list(dict.fromkeys(matches)))

@tool 
def tree_tool(root:str ) -> str:
    """Return an indented tree view of *root* """
    try:
        base = file_access_control.validate_read(root)
    except Exception as e:
        return f"tree_tool: {e}"
    if not base.is_dir():
        return f"tree_tool: {root} is not dir"
    
    lines = []
    for dirpath,dirnames,filenames in os.walk(base):
        rel_dir = Path(dirpath).relative_to(Path.cwd())
        indent = " " * len(rel_dir.parts)
        lines.append(f"{indent}{rel_dir.name}")
        for f in sorted(filenames):
            lines.append(f"{indent} {f}")
    return "\n".join(lines)

    
tools = [ obj for _, obj in globals().items() if isinstance(obj, BaseTool) ]
LOGGER.info(f"Loaded {len(tools)} tools: {str([t.name for t in tools])}")

