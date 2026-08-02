from pathlib import Path
import sqlite3
from typing import Annotated, Dict, Literal, TypedDict, List
import uuid

from langchain.messages import ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import START, END
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph, StateGraph

from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langgraph.prebuilt import ToolCallTransformer
from dotenv import load_dotenv
from langchain.messages import (
    HumanMessage,
    AnyMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.prebuilt import ToolNode
import json, os

from ui.console import start_session
from tools.tools import tools, tools_by_name

from mcp_tools import tools_mcp_network,tools_mcp_stdio

from utils import config
from utils.fs import FileData, sync_loaded_files
import argparse
from importlib import resources
import sys


SYSTEM_PROMPT = ""
MAX_LLM_CALLS = 15
llm_with_tools = None

# mcp_tools_network = tools_mcp_network.load_mcp_tools('http://127.0.0.1:8000/mcp/')
# mcp_tools,mcp_manager = tools_mcp_stdio.load_mcp_tools()
# append MCP tools
# tools += mcp_tools

class State(TypedDict):
    """Save history of conversation"""

    messages: Annotated[list, add_messages]
    loaded_files: Dict[str, FileData]
    llm_calls: int


# NODES

# REMOVE IT
def tool_node(state: State):
    result = []
    for tool_call in state["messages"][-1].tool_calls:
        tool_name = tool_call["name"]
        # print('tool call',tool_name)
        if tool_name not in tools_by_name:
            result.append(
                ToolMessage(
                    content=f"Error: Tool '{tool_name}' not available.",
                    tool_call_id=tool_call["id"],
                )
            )
            continue

        tool = tools_by_name[tool_call["name"]]
        config.LOGGER.debug(f'Execute {tool} with ({tool_call["args"]})')
        try:
            observation = str(tool.invoke(tool_call["args"]))
        except Exception as err:
            observation = f"Error calling {tool_name} {err}"

        result.append(
            ToolMessage(content=str(observation), tool_call_id=tool_call["id"])
        )

    return {"messages": result}


def should_continue(state: State):
    # if state.get("llm_calls", 0) >= MAX_LLM_CALLS:
    #     return END

    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tool_node"
    return END


def format_file_context(loaded_files: Dict[str, FileData]) -> str:
    if not loaded_files:
        return ""

    blocks = ["\n### Active Working Context (Latest File Versions)\n"]
    for path, info in loaded_files.items():
        blocks.append(f"```{path}\n{info['content']}\n```")
    return "\n".join(blocks)


def llm_call_node(state: State):
    global llm_with_tools

    current_calls = state.get("llm_calls", 0) + 1
    old_files_snap = state.get("loaded_files", {})

    # sync all loaded files
    new_files_snap = sync_loaded_files(old_files_snap)

    config.LOGGER.info(f"loaded files {str(new_files_snap)}")

    file_context = format_file_context(new_files_snap)
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]

    if file_context:
        last_msg = messages[-1]
        updated_content = (
            f"{last_msg.content}\n\n"
            f"--- ACTIVE WORKING CONTEXT (GROUND TRUTH) ---\n"
            f"{file_context}"
        )
        if isinstance(last_msg, HumanMessage):
            messages[-1] = HumanMessage(content=updated_content, id=last_msg.id)
        elif isinstance(last_msg, ToolMessage):
            messages[-1] = ToolMessage(
                content=updated_content,
                tool_call_id=last_msg.tool_call_id,
                id=last_msg.id,
            )

    config.LOGGER.info(f"messages from llm_call_node {messages}")
    resp = llm_with_tools.invoke(messages)
    return {
        "messages": [resp],
        "llm_calls": current_calls,
        "loaded_files": new_files_snap,
    }


DB_DIR = Path.cwd() / ".vex"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "session.db"

def init_workspace():
    vex_dir = Path.cwd() / ".vex"
    vex_dir.mkdir(parents=True,exist_ok=True)

    for file in resources.files("templates").iterdir():
        if file.is_dir() or file.name == "__init__.py": continue

        content = file.read_text(encoding='utf-8')
        (vex_dir / file.name ).write_text(content)
    
    with open("AGENTS.md", 'w',encoding="utf-8") as f:
        f.write("")

def main():
    global SYSTEM_PROMPT,llm_with_tools

    parser = argparse.ArgumentParser(description="VEX Shell agent")
    parser.add_argument("--init","-i",action="store_true",
                        help="Initialize .vex project")
    args = parser.parse_args()
    if args.init:
        init_workspace()
        sys.exit(0)

    llm_config = config.get_config()

    # MODEL = "inclusionai/ling-3.0-flash:free"
    MODEL = "openai/gpt-oss-120b"
    llm = ChatOpenAI(
        model=MODEL,
        api_key=llm_config['chat']['api_key'],
        base_url="https://openrouter.ai/api/v1",
        temperature=0,
        max_completion_tokens=8192,
        timeout=60.0,
        max_retries=3,
        stream_usage=True,
        extra_body={
            # "include_reasoning": True,
            "provider": {
                "order": ["CoreWeave", "DeepInfra"],
                "allow_fallbacks": True,
                "data_collection": "deny",
            }
            # "reasoning": {
            #     "effort": "none",
            #     # "mandatory": True,
            #     # "exclude": False
            #     },
        },
    )

    # llm = ChatOpenAI(
    #     model="qwen2.5-coder:latest",
    #     base_url="http://localhost:11434/v1",
    #     api_key="ollama",
    #     stream_usage=True,
    #     temperature=0,
    #     extra_body={
    #         "options":{"num_ctx":8192}
    #     }
    # )
    
    llm_with_tools = llm.bind_tools(tools)

    graph_builder = StateGraph(State)
    graph_builder.add_node("llm_call", llm_call_node)

    lg_tool_node = ToolNode(tools)
    graph_builder.add_node("tool_node", lg_tool_node)

    graph_builder.add_edge(START, "llm_call")
    graph_builder.add_conditional_edges("llm_call", should_continue, ["tool_node", END])
    graph_builder.add_edge("tool_node", "llm_call")

    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()
    agent: CompiledStateGraph = graph_builder.compile(checkpointer=checkpointer)

    with open("AGENT.md", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read()
    config.LOGGER.info(f"system prompt len {len(SYSTEM_PROMPT)} chars")

    start_session(agent)


if __name__ == "__main__":
    main()
