import os
from typing import TypedDict
from utils.config import LOGGER


class FileData(TypedDict):
    content: str
    mtime: float
    size: int


def sync_loaded_files(loaded_files: dict[str, FileData]) -> dict[str, FileData]:
    """Autosync all files loaded in chat context"""
    if not loaded_files:
        return {}

    updated_files = None
    for path, cached in loaded_files.items():
        try:
            stat = os.stat(path)
            # nothing changes
            if stat.st_mtime_ns == cached["mtime"] and stat.st_size == cached["size"]:
                continue
            with open(path, "r", encoding="utf-8") as f:
                new_content = f.read()
            # lazy loading
            if updated_files is None:
                updated_files = dict(loaded_files)

            updated_files[path] = FileData(
                content=new_content, mtime=stat.st_mtime, size=stat.st_size
            )
            LOGGER.info(f"Autosync file:{path}")

        except Exception as e:
            LOGGER.warning(f"file sync error {e}")

    return updated_files if updated_files is not None else loaded_files
