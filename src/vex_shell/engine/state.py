from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, TypedDict

from langgraph.graph.message import add_messages

if TYPE_CHECKING:
    from vex_shell.utils.fs import FileData


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
    loaded_files: Annotated[dict[str, FileData],merge_dict_state]
    cwd_tree: str
    llm_calls: int

class FileData(TypedDict):
    content: str
    mtime: float
    size: int