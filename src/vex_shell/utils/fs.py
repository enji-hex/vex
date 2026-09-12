from pathlib import Path

from .config import LOGGER
from .file_access import file_access_control
from vex_shell.tools.tools import _tree_tool
from vex_shell.engine.state import FileData

from vex_shell.engine.state import State

def sync_cwd_tree(state: State) -> str:
    """Update cwd_tree in Agent State"""

    new_tree = _tree_tool(file_access_control.cwd)
    state.update({"cwd_tree":new_tree})
    return new_tree

def sync_loaded_files(loaded_files: dict[str, FileData]) -> dict[str, FileData]:
    """Autosync all files loaded in chat context"""
    if not loaded_files:
        return {}

    cwd = Path(file_access_control.cwd)
    updated_files = dict(loaded_files)
    modified = False

    for rel_path, cached in loaded_files.items():
        full_path = cwd / rel_path
        
        if not full_path.exists():
            del updated_files[rel_path]
            modified = True
            continue

        try:
            stat = full_path.stat()
            # nothing changes
            if stat.st_mtime_ns == cached["mtime"] and stat.st_size == cached["size"]:
                continue

            # re-read content from already validated file
            new_content = full_path.read_text(encoding='utf-8')
            
            updated_files[rel_path] = FileData(
                content=new_content, 
                mtime=stat.st_mtime_ns, 
                size=stat.st_size
            )
            LOGGER.info(f"Autosync file:{rel_path}")
            modified = True

        except Exception as e:
            LOGGER.warning(f"file sync error {e}")

    return updated_files if modified else loaded_files
