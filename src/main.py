from pathlib import Path
import aiosqlite

from typing import Annotated, Dict, TypedDict

from langchain.messages import ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import START, END
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph, StateGraph

from langchain_openrouter import ChatOpenRouter
from langchain.messages import (
    HumanMessage,
    AnyMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.prebuilt import ToolNode
import  os

from rich.console import Console
from ui.console import start_session
from ui import colors
from tools.tools import tools, tools_by_name

from utils import config
from utils.fs import FileData, sync_loaded_files
import argparse
from importlib import resources
import sys,time
import asyncio
from rich import print as rprint

start_time = time.perf_counter()

SYSTEM_PROMPT = ""
MAX_LLM_CALLS = 15
llm_with_tools = None
MCP_MANAGER = None


class State(TypedDict):
    """Save history of conversation"""
    messages: Annotated[list, add_messages]
    loaded_files: Dict[str, FileData]
    llm_calls: int


# NODES
# conditional edge evaluators should be sync
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


async def llm_call_node(state: State):
    """
    reservred
    """

    global llm_with_tools
    llm_config = config.get_config()

    current_calls  = state.get("llm_calls", 0) + 1
    old_files_snap = state.get("loaded_files", {})

    # sync all loaded files
    new_files_snap = sync_loaded_files(old_files_snap)
    config.LOGGER.info(f"loaded files {str(new_files_snap)}")


    # handle sliding window  
    raw_mesages = state["messages"]
    window_size = llm_config.get('context_sliding_window')
    if window_size and  len(raw_mesages) > window_size:
        recent_messages = list(raw_mesages[-window_size:])
        while recent_messages and isinstance(recent_messages[0],ToolMessage):
            window_size+=1
            recent_messages = list(raw_mesages[-window_size:])
    else:
        recent_messages = list(raw_mesages)
    
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + recent_messages

    # Handle file_context
    file_context = format_file_context(new_files_snap)
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
    resp = await llm_with_tools.ainvoke(messages)
    return {
        "messages": [resp],
        "llm_calls": current_calls,
        "loaded_files": new_files_snap,
    }

def init_workspace(home:bool = False,console:Console):
    vex_dir = Path.home() / ".vex" if home else Path.cwd() / ".vex"
    vex_dir.mkdir(parents=True,exist_ok=True)

    for file in resources.files("templates").iterdir():
        if file.is_dir() or file.name == "__init__.py": continue

        content = file.read_text(encoding='utf-8')
        (vex_dir / file.name ).write_text(content)
    
    console.print(
        f"[vex.success]✓[/vex.success] New .vex folder initialized at "
        f"[vex.prompt]{vex_dir.absolute()}[/vex.prompt]"
    )
    console.print(
        "[vex.muted]Initialization complete. " \
        "Set API keys and adjust settings for your requirements.[/vex.muted]"
    )


def resolve_system_msg() -> str:
    candidates = [
        Path.cwd() / ".vex" / "AGENTS.md",
        Path.home() / ".vex" / "AGENTS.md"
    ]
    for p in candidates:
        if p.is_file():
            config.LOGGER.info(f"system prompt len {len(SYSTEM_PROMPT)} chars")
            return p.read_text(encoding='utf-8')


async def main():
    global SYSTEM_PROMPT,llm_with_tools,tools,MCP_MANAGER

    parser = argparse.ArgumentParser(description="VEX Shell agent, if u start it from folder where VEX was not initialized " \
        "by --init flag user .vex folder will be used")
    parser.add_argument("--init","-i",action="store_true",
                        help="Initialize .vex project")
    args = parser.parse_args()

    console = Console(theme=colors.CYBERPUNK.to_rich_theme())
    if args.init:
        init_workspace(console=console)
        sys.exit(0)

    # no args , init systemwide config
    vex_dir = Path.cwd() / ".vex"
    if not Path.exists(vex_dir):
        init_workspace(home=True,console=console)

    SYSTEM_PROMPT = resolve_system_msg()
    
    
    llm_config:Dict = config.get_config()
    extra_body=llm_config['model'].get('extra_body')

    # reasoning 
    # https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
    # timeout trigger error(maybe)
    llm = ChatOpenRouter(
        model=llm_config['model']['name'],
        api_key=llm_config['model']['api_key'],
        base_url="https://openrouter.ai/api/v1",
        temperature=llm_config['model']['temperature'],
        max_completion_tokens=llm_config['model']['max_completion_tokens'],
        max_retries=int(llm_config['model']['max_retries']),
        stream_usage=True,
        reasoning=llm_config['model']['reasoning']
    )
    
    config.LOGGER.info(f"extra_body {str(extra_body)}")

    config.LOGGER.info(f'start time {time.perf_counter() - start_time} secs')
    # append MCP tools
    if llm_config['chat']['use_mcp']:
        from mcp_tools import tools_mcp
        config.LOGGER.info(f'start time + mcp import {time.perf_counter() - start_time} secs')

        mcp_tools,MCP_MANAGER = await tools_mcp.load_mcp_tools()
        tools += mcp_tools
    
    llm_with_tools = llm.bind_tools(tools)

    graph_builder = StateGraph(State)
    graph_builder.add_node("llm_call", llm_call_node)

    lg_tool_node = ToolNode(tools)
    graph_builder.add_node("tool_node", lg_tool_node)

    graph_builder.add_edge(START, "llm_call")
    graph_builder.add_conditional_edges("llm_call", should_continue, ["tool_node", END])
    graph_builder.add_edge("tool_node", "llm_call")

    db_path = Path.cwd() / ".vex" / "session.db"
    conn = await aiosqlite.connect(str(db_path))
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()
    agent: CompiledStateGraph = graph_builder.compile(checkpointer=checkpointer)


    end_time = time.perf_counter()
    config.LOGGER.info(f'start time ready to work {end_time - start_time} secs')
    try:
        await start_session(agent,console=console)
    finally:
        await conn.close()
        if MCP_MANAGER is not None:
            await MCP_MANAGER.aclose()


def cli():
    asyncio.run(main())

if __name__ == "__main__":
    cli()
