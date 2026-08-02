from pathlib import Path
import subprocess
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


# 
# CORE tools packet
# 

@tool
def cat_tool(
    path: str,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command | str:
    """Reads a NEW file from disk and caches it into active working context.

    IMPORTANT: Do NOT invoke this tool for files that are already listed in
    'Active Working Context', as those files are auto-synced automatically before every turn.
    """

    if not os.path.exists(path):
        return f"cat: {path}: No such file or directory"
    if os.path.isdir(path):
        return f"cat: {path}: Is a directory"

    path = os.path.abspath(path)
    stat = os.stat(path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
        line_count = content.count("\n") + (
            1 if content and not content.endswith("\n") else 0
        )

    rel_path = os.path.relpath(path)
    current_files = dict(state.get("loaded_files", {}))
    current_files[rel_path] = FileData(
        content=content, size=stat.st_size, mtime=stat.st_mtime_ns
    )
    LOGGER.info(f"read {current_files}")

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
def glob_tool(glob_pattern: str) -> str:
    """
    Always use wildcard path with this tool, e.g. ./test/*.c or ./project/*.hpp
    Glob tool, accept wildcard syntax an return list of related filepath as string, one entry per line
    """
    print(f"call glob_tool {glob_pattern}")
    matches = []
    for g in glob_pattern.split():  # handle multientry glob
        # print('current glob',g)
        matches += glob.glob(g, recursive=True)

    if len(matches) == 0:
        return f"No matches found, test other glob_pattern"
    return "\n".join(matches)


@tool
def ripgrep_tool(regex: str, path: str, filetype: str = "") -> str:
    """
    Search for files or text matching a regex pattern inside a path using ripgrep.
    regex - regex patter for searching
    path - path to target file
    filetype - target file extension (e.g. md,txt or empty string if not specified)
    """
    clean_regex = regex.strip("'\"")
    target_path = os.path.abspath(path.replace("\xa0", " ").strip("'\" "))

    if not Path(target_path).exists():
        return f"rg: path '{target_path}' does not exist, try another path"

    args = ["rg", "-e", clean_regex, "-l"]
    if filetype.strip():
        ext = filetype.strip().lstrip(".")
        args.extend(["-g", f"*.{ext}"])

    args.append(target_path)
    print("full cmd rg", " ".join(args))

    res = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if res.returncode != 0 or res.stdout == None:
        return f"rg: no matches found for '{regex}' in {path} {res.stderr}"
    return res.stdout.strip()


@tool
def compile_check_tool(path: str, flags: str = "-Wall -Wextra") -> str:
    """
    Check C/C++ syntax and warnings without building binaries.
    file_path - path to .c or .cpp file
    flags - extra flags (default: '-Wall -Wextra')
    Suppored extensions: .c,.cpp,.h,.hpp,.cc
    """
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        return f"Error: File '{path}' does not exist or it's not a file, perform directory discover"
    if not abs_path.endswith((".cpp", ".c", ".cc", ".hpp", ".h")):
        return f"Wrong file extension for compile_checking"

    compiler = "g++" if abs_path.endswith((".cpp", ".hpp", ".cc")) else "gcc"
    cmd = [compiler, "-fsyntax-only"] + flags.split() + [abs_path]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return f"Compilation Check PASED for {path}"
        return f"Compilation check failed:\n{res.stderr}"
    except Exception as e:
        return f"Compiler check error {str(e)}"


tools = [
    obj
    for _, obj in inspect.getmembers(sys.modules[__name__])
    if isinstance(obj, BaseTool)
]
LOGGER.info(f"Loaded {len(tools)} tools:", [t.name for t in tools])
tools_by_name = {tool.name: tool for tool in tools}

