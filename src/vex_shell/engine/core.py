from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Hashable, Tuple

from langchain_core.messages import AnyMessage

from vex_shell.engine.events import TokenUsage
from vex_shell.engine.state import State
from vex_shell.utils.config import LOGGER
from vex_shell.utils.file_access import file_access_control

# from langgraph.graph import START, END
# thi shit imports ENTIRE langgraph.graph module!!!
END = "__end__"
START = "__start__"

@dataclass
class SavedMessage:
    message:AnyMessage
    role:str # user or agent_name

# import only for type checking
if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from langgraph.graph.state import StateGraph
    from vex_shell.mcp_tools.tools_mcp import MCPManager
    from vex_shell.utils.config import Settings


async def get_tools(settings: Settings) -> tuple[list[BaseTool], MCPManager | None]:
    from ..tools.tools import get_tools

    ignore_list = []
    if len(file_access_control.write_patterns) == 0 and not file_access_control.all_write:
        ignore_list.append("write_file")
    if not settings.model.get("ase_sandbox"):
        ignore_list.append("ase_tool")
    tools = get_tools(ignore_list)

    mcp_manager = None
    if settings.chat["use_mcp"]:
        from vex_shell.mcp_tools.tools_mcp import load_mcp_tools
        mcp_tools, mcp_manager = await load_mcp_tools()
        tools.extend(mcp_tools)

    return tools, mcp_manager


def build_graph(settings: Settings, tools: list[BaseTool]) -> StateGraph:
    from langgraph.graph.state import StateGraph
    from langgraph.prebuilt import ToolNode
    from .nodes import (
            verification_node,
            writer_node,
            validator_node,
            should_verify
        )

    def router(state:State) -> str:
        return state.get("next","end")

    graph = StateGraph(State)
    duo = settings.chat.get("duo", False)

    # LLM Nodes
    graph.add_node("writer", partial(writer_node, settings=settings, tools=tools))
    graph.add_node("tool_node", ToolNode(tools))
    graph.add_node("verification_node", partial(verification_node, settings=settings))
    if duo:
        graph.add_node("validator",partial(validator_node,settings=settings,tools=tools))

    # Graph Edges
    graph.add_edge(START, "writer")
    writer_targets: dict[Hashable,str] = {"tool_node":"tool_node","end":"__end__"}
    if duo:
        writer_targets["validator"] = "validator"
    graph.add_conditional_edges("writer", router, writer_targets)

    graph.add_conditional_edges(
        "tool_node",
        partial(should_verify,settings=settings),
        {"verification_node": "verification_node", "writer": "writer"}
        )

    if duo:                                                                                                      
        verification_targets: dict[Hashable,str] = {"validator": "validator", "writer": "writer"}                                    
    else:                                                                                                        
        verification_targets: dict[Hashable,str] = {"writer": "writer"}   
    graph.add_conditional_edges("verification_node", router,verification_targets)

    if duo:
        validator_targets: dict[Hashable,str] = {"writer": "writer", "end": END}                                                     
        graph.add_conditional_edges("validator", router, validator_targets)

    return graph


# --- partial shift to Graph 1st impl ---
async def graph_get_state(graph, config):
    return await graph.aget_state(config)

async def graph_restore_history(graph, config) -> Tuple[list[SavedMessage],TokenUsage]:
    state = await graph_get_state(graph, config)
    token_usage = TokenUsage()
    messages: list | None = state.values.get("messages")
    if not messages:
        return [],token_usage

    recent_messages = []
    for m in messages:
        if hasattr(m,"usage_metadata") and m.usage_metadata:
            try:
                u = m.usage_metadata
                token_usage.tok_in += u.get("input_tokens", 0)
                token_usage.tok_out += u.get("output_tokens", 0)
                token_usage.tok_total += u.get("total_tokens", 0)
            except Exception as err:
                LOGGER.error(f"Error get token usage metrics, {err}",exc_info=True)

        role = m.response_metadata.get("role") or m.additional_kwargs.get("role")
        # fallback to old checkpointers
        if role is None: 
            role = 'VEX' if m.type == "ai" else "user"

        if m.type == "human":
            recent_messages.append(SavedMessage(m,role))
        elif m.type == "ai":
            if isinstance(m.content, str) and m.content.strip():
                recent_messages.append(SavedMessage(m,role))
            elif isinstance(m.content, list):
                if any(isinstance(c, dict) and c.get("type") == "text" for c in m.content):
                    recent_messages.append(SavedMessage(m,role))

    return recent_messages,token_usage


async def graph_export_history(
    graph, config, model_name: str, system_prompt: str, session_id: str
):
    import json
    from datetime import datetime

    messages,token_usage = await graph_restore_history(graph, config)
    data = {
        "version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "model": model_name,
        "messages": [{"role": "system", "content": system_prompt}],
    }

    for msg in messages:
        if msg.role == "user" and isinstance(msg.message.content, str):
            data["messages"].append({"role": "user", "content": msg.message.content})
        
        elif isinstance(msg.message.content,str):
            data["messages"].append({"role": msg.role, "content": msg.message.content})
        elif isinstance(msg.message.content,list):
            for c in msg.message.content:
                if isinstance(c, dict) and c["type"] == "text":
                    data["messages"].append({"role": msg.role, "content": c["text"]})

    with open(f"./{session_id}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)