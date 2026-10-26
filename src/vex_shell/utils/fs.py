from pathlib import Path

from vex_shell.engine.state import FileData, State

from .config import LOGGER
from .file_access import file_access_control


def sync_cwd_tree(state: State) -> str:
    """Update cwd_tree in Agent State"""
    from vex_shell.tools.tools import _tree_tool

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
        # adjust path
        full_path = Path(rel_path)
        if not full_path.is_absolute():
            full_path = cwd  / full_path

        try:
            # check permissions , raise exception if no perms
            full_path = file_access_control.validate_read(str(full_path))
        
            if not full_path.is_file():
                updated_files.pop(rel_path,None)
                modified = True
                LOGGER.debug(f"Removing [deleted] cached file  {rel_path}")
                continue

        
            stat = full_path.stat()
            # nothing changes
            if stat.st_mtime_ns == cached["mtime"] and stat.st_size == cached["size"]:
                continue

            if cached["content"].startswith("data:image/"):
                from vex_shell.tools.tools import read_image
                new_content = read_image(full_path)
            else:
                # re-read content from already validated file
                new_content = full_path.read_text(encoding='utf-8')
            
            updated_files[rel_path] = FileData(
                content=new_content, 
                mtime=stat.st_mtime_ns, 
                size=stat.st_size,
            )
            modified = True
            LOGGER.info(f"Autosync file:{rel_path}")

        except Exception as e:
            updated_files.pop(rel_path,None)
            modified = True
            LOGGER.error(f"FS removing unusable cached file {rel_path}: {e}")


    return updated_files if modified else loaded_files
