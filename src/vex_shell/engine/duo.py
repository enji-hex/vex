from __future__ import annotations

import asyncio
from functools import partial
import os
from typing import TYPE_CHECKING, Hashable

from langgraph.graph import StateGraph

if TYPE_CHECKING:
    from langchain.tools import BaseTool
    from langgraph.prebuilt import ToolNode
    from langchain_core.runnables import RunnableConfig

    from vex_shell.utils.config import Settings

from vex_shell.utils.config import LOGGER
from vex_shell.utils.file_access import file_access_control
from vex_shell.utils.fs import sync_cwd_tree, sync_loaded_files

from .state import FileData, State


def build_graph(settings: Settings, tools: list[BaseTool]) -> StateGraph:
    LOGGER.info('DUO graph is used')
    # fake duo-agent mode 'cause we use single agent with different system prompts
    from langgraph.graph.state import StateGraph
    from langgraph.prebuilt import ToolNode
    from .nodes import llm_call_node
    from .state import State

    graph = StateGraph(State)
    graph.add_node("writer", partial(llm_call_node, settings=settings, tools=tools))
    graph.add_node("validator", partial(llm_call_node, settings=settings, tools=tools))
    graph.add_node("tool_node", ToolNode(tools))

    graph.add_edge("__start__", "writer")
    # writer route to tool_node/validator/end
    graph.add_conditional_edges(
        "writer",
        lambda s: s.get("route","end"),
        {"tool_node": "tool_node", "llm_call": "validator", "end": "__end__"},
    )

    graph.add_edge("tool_node", "writer")  # callback to writer

    # validator route to writer/end
    graph.add_conditional_edges(
        "validator", lambda s: s.get("route","end"), {"llm_call": "writer", "end": "__end__"}
    )
    return graph
