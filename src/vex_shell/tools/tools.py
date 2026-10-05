from __future__ import annotations

from pathlib import Path
import os
import glob
from langchain.tools import InjectedState, InjectedToolCallId
from langgraph.types import Command
from langchain_core.tools import BaseTool, tool

from langchain_core.runnables import RunnableConfig
from typing import Annotated, Dict, List, Tuple

import io
import pathspec

from vex_shell.utils.config import LOGGER
from vex_shell.utils.file_access import file_access_control
from vex_shell.engine.state import FileData


    
# 
# CORE tools packet
# 

def get_gitignore_spec(root_path: Path) -> pathspec.PathSpec:
    """Loads .gitignore from root_path and appends default fallback ignores."""
    default_ignores = [".git/", "__pycache__/", ".venv/", "venv/", "node_modules/",".next"]
    gitignore_file = root_path / ".gitignore"
    patterns = list(default_ignores)
    if gitignore_file.is_file():
        patterns.extend(gitignore_file.read_text(encoding="utf-8").splitlines())
        
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

def get_rel_str(p: Path, cwd: Path) -> str:
    try:
        return p.relative_to(cwd).as_posix()
    except ValueError:
        return p.as_posix()


def read_image(path:Path,max_dim: int = 1024) -> str:
    from base64 import b64encode
    from PIL import Image

    with Image.open(path) as img:
        # fix for PNG
        if (
            img.mode in ("RGBA", "LA") 
            or (img.mode == "P" and "transparency" in img.info)
            ):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.convert("RGBA").split()[3])
            img = background
        # Convert other types directly into JPG
        else:
            img = img.convert("RGB")
        
        img.thumbnail((max_dim,max_dim),Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer,format="JPEG",quality=85)

        b64_data = b64encode(buffer.getvalue()).decode('utf-8')
    
    return f'data:image/jpeg;base64,{b64_data}'

def _read_files(
    paths: List[str],
    config: RunnableConfig,
    state: dict,
) -> Tuple[Dict[str,FileData] ,List[str]]:
    """
    Return loaded files dict, messages
    """
    from vex_shell.engine.helpers import count_tokens

    use_vision = config.get('configurable',{}).get('use_vision',False)
    cwd = Path(file_access_control.cwd)
    spec = get_gitignore_spec(cwd)

    loaded:Dict[str,FileData] = dict(state.get("loaded_files",{}))
    msgs =  []

    for p in paths:
        try:
            target = Path(file_access_control.validate_read(p))
            if not target.is_file():
                msgs.append(f"read_files: {p}: not a file")
                continue
            
            rel_path = get_rel_str(target,cwd)
            if spec.match_file(rel_path):
                msgs.append(f"read_file: {p} file is ignored by .gitignore")
                continue

            suffix   =  target.suffix.lower().lstrip('.')
            tokens = 0
            if suffix in ["jpg", "jpeg", "webp", "png"] and use_vision:
                content = read_image(target)            
                line_info = "image/base64"
                LOGGER.debug(f'read_file image  {len(content)}')
            else:
                content = target.read_text(encoding='utf-8')
                line_info = f"{len(content.splitlines())} lines"
                tokens = count_tokens(content)

            stat = target.stat()
            loaded[rel_path] = FileData(
                content=content,
                size=stat.st_size,
                mtime=stat.st_mtime_ns,
                tokens=tokens
                )
            msgs.append(f"cached '{p}' ({line_info})")
        except Exception as err:
            msgs.append(f"read_files: {err}")
    
    return loaded, msgs

@tool
def read_files(
    paths: List[str],
    config: RunnableConfig,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command | str:
    """Read multiple NEW files from disk and add it to the active working context."""

    from langchain_core.messages import ToolMessage
    
    loaded, msgs = _read_files(paths,config,state)
    
    if not msgs: return "read_files: no files were read"
    return Command(
        update={
            "loaded_files": loaded,
            "messages": [
                ToolMessage(content="\n".join(msgs),tool_call_id=tool_call_id,
                )
            ],
        }
    )


@tool
async def write_file(
    path: str,
    content:str,
    config: RunnableConfig,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command | str:
    """
    Write provided content into the specified file path.
    Create parent folder if it doesn't exist
    """
    from langchain_core.messages import ToolMessage
    from vex_shell.engine.helpers import count_tokens

    cache_on_write = config.get('configurable',{}).get('cache_on_write',False)

    cwd = Path(file_access_control.cwd)
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
        target_stat = target.stat()
    
    rel_path = get_rel_str(target,cwd)
    LOGGER.info(f"write to file {rel_path}")
    msg_text = f"Successfully wrote content to '{rel_path}'"

    if cache_on_write:
        new_file_ctx = {rel_path:FileData(
            content=content,
            size=target_stat.st_size,
            mtime=target_stat.st_mtime_ns,
            tokens=count_tokens(content)
            )}
        return Command(
            update={
                "loaded_files": new_file_ctx,
                "messages": [
                    ToolMessage(content=msg_text,tool_call_id=tool_call_id,
                    )
                ],
            }
        )
    return msg_text
    

def _glob_tool(glob_patterns: List[str]) -> List[str]:
    matches: list[str] = []
    LOGGER.debug(f'glob_tool {str(glob_patterns)}')
    cwd  = Path(file_access_control.cwd)
    spec = get_gitignore_spec(cwd)

    for g in glob_patterns:  # handle multientry glob
        is_abs = Path(g).is_absolute()
        
        for path_str in glob.glob(g, 
            root_dir=None if is_abs else cwd,
            recursive=True,
            include_hidden=False
            ):
            full_path = Path(path_str) if is_abs else cwd / path_str
            try:
                safe_path = file_access_control.validate_read(full_path.as_posix())
                rel_path  = get_rel_str(safe_path,cwd)
                if safe_path.is_file() and not spec.match_file(rel_path):
                    matches.append(rel_path)
            except (PermissionError,ValueError):
                continue

    return matches

@tool
def glob_tool(glob_patterns: List[str]) -> str:
    """
    Glob tool, accept list of wildcard syntax an return list of related filepath as string, one entry per line
    """
    matches: list[str] = _glob_tool(glob_patterns)
    if not matches:
        return f"No matches found, test other pattern"
    return "\n".join(list(dict.fromkeys(matches)))
        
def _tree_tool(root: str = ".") -> str:
    """Return an indented tree view of *root* showing permission-validated files."""
    cwd = Path(file_access_control.cwd)
    base = (
        cwd / root if not Path(root).is_absolute() else Path(root)
    ).resolve()

    if not base.is_dir():
        return f"tree_tool: {root} is not dir"

    spec = get_gitignore_spec(cwd)
    valid_rel_paths: List[Path] = []

    for dirpath_str, dirnames, filenames in os.walk(base):
        dirpath = Path(dirpath_str)
        
        # Filter fiels with .gitignore
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not spec.match_file(get_rel_str(dirpath / d, cwd) + "/")
        )

        for f in sorted(filenames):
            file_path = dirpath / f
            rel_str = get_rel_str(file_path, cwd)

            if spec.match_file(rel_str):
                continue
            try:
                file_access_control.validate_read(str(file_path))
                valid_rel_paths.append(file_path.relative_to(base))
            except PermissionError:
                pass

    if not valid_rel_paths:
        return f"{base.name}/ (no accessible files)"

    printed_dirs: set[Path] = set()
    lines = [f"{base.name}/"]

    for rel_file in sorted(valid_rel_paths):
        ancestors = [p for p in reversed(rel_file.parents) if p != Path(".")]

        for parent in ancestors:
            if parent not in printed_dirs:
                depth = len(parent.parts)
                indent = "  " * depth  # 2 spaces per level
                lines.append(f"{indent}{parent.name}/")
                printed_dirs.add(parent)

        depth = len(rel_file.parts)
        indent = "  " * depth
        lines.append(f"{indent}{rel_file.name}")

    return "\n".join(lines)


@tool
def tree_tool(root: str = ".") -> str:
    """Return an indented tree view of *root* showing permission-validated files."""
    return _tree_tool(root)

def get_tools():
    tools = []
    has_write_access = len(file_access_control.write_patterns) > 0 or file_access_control.all_write
    
    for _,obj in globals().items():
        if isinstance(obj,BaseTool):
            if obj.name == "write_file" and has_write_access == False:
                continue
            tools.append(obj)

    LOGGER.info(f"Loaded {len(tools)} tools: {str([t.name for t in tools])}")
    return tools