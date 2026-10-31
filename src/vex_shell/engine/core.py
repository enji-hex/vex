from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from langchain_core.messages import AnyMessage

from vex_shell.engine.events import TokenUsage
from vex_shell.utils.config import LOGGER

# from langgraph.graph import START, END
# thi shit imports ENTIRE langgraph.graph module!!!
END = "__end__"
START = "__start__"

# import only for type checking
if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from langgraph.graph.state import StateGraph

    from vex_shell.mcp_tools.tools_mcp import MCPManager
    from vex_shell.utils.config import Settings


async def get_tools(settings: Settings) -> tuple[list[BaseTool], MCPManager | None]:
    from ..tools.tools import get_tools

    tools = get_tools()
    mcp_manager = None

    if settings.chat["use_mcp"]:
        from vex_shell.mcp_tools.tools_mcp import load_mcp_tools

        mcp_tools, mcp_manager = await load_mcp_tools()
        tools.extend(mcp_tools)

    return tools, mcp_manager


def build_graph(settings: Settings, tools: list[BaseTool]) -> StateGraph:
    from langgraph.graph.state import StateGraph
    from langgraph.prebuilt import ToolNode

    from .nodes import llm_call_node, should_continue, should_verify, verification_node
    from .state import State

    graph = StateGraph(State)

    # LLM Nodes
    graph.add_node("writer", partial(llm_call_node, settings=settings, tools=tools))
    graph.add_node("tool_node", ToolNode(tools))
    graph.add_node("verification_node", partial(verification_node, settings=settings))

    # Graph Edges
    graph.add_edge(START, "writer")
    graph.add_conditional_edges("writer", should_continue, ["tool_node", END])
    graph.add_conditional_edges(
        "tool_node",  # source node
        partial(should_verify, settings=settings),  # check condition
        # path maps
        # llm_call str -> route to llm_call function
        {"verification_node": "verification_node", "writer": "writer"},
    )
    graph.add_edge("verification_node", "writer")
    return graph


# --- partial shift to Graph 1st impl ---
async def graph_get_state(graph, config):
    return await graph.aget_state(config)


async def graph_restore_history(graph, config) -> list[AnyMessage]:
    state = await graph_get_state(graph, config)
    messages: list[AnyMessage] | None = state.values.get("messages")
    if not messages:
        return []

    recent_messages = []
    for m in messages:
        if m.type == "human":
            recent_messages.append(m)
        if m.type == "ai":

            if isinstance(m.content, str):
                recent_messages.append(m)
            elif isinstance(m.content, list) and any(
                isinstance(c, dict) and c.get("type") == "text" for c in m.content
            ):
                recent_messages.append(m)
    return recent_messages


async def graph_export_history(
    graph, config, model_name: str, system_prompt: str, session_id: str
):
    from datetime import datetime
    import json

    messages = await graph_restore_history(graph, config)
    data = {
        "version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "model": model_name,
        "messages": [{"role": "system", "content": system_prompt}],
    }

    for m in messages:
        if m.type == "human" and isinstance(m.content, str):
            data["messages"].append({"role": "user", "content": m.content})
        if m.type == "ai" and m.content:
            for c in m.content:
                if isinstance(c, dict) and c["type"] == "text":
                    data["messages"].append({"role": "assistant", "content": c["text"]})

    with open(f"./{session_id}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


async def graph_restore_token_usage(graph,config) -> TokenUsage:
    """Restore token usage for message history"""
    current_state = await graph_get_state(graph,config)
    token_usage = TokenUsage()

    # empty token usage
    if "messages" not in current_state.values:
        return token_usage

    for m in current_state.values["messages"]:
        if hasattr(m, "usage_metadata"):
            try:
                u = m.usage_metadata
                token_usage.tok_in += u.get("input_tokens", 0)
                token_usage.tok_out += u.get("output_tokens", 0)
                token_usage.tok_total += u.get("total_tokens", 0)
            except Exception as err:
                LOGGER.error(f"Error get token usage metrics, {err}")
    return token_usage
