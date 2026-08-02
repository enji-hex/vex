import re
from typing import Any, Callable, Iterator, List, Literal, Optional, Union
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolCallTransformer
from rich.box import SQUARE
from rich.console import Console, Group
from rich.panel import Panel
from rich.status import Status
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.live import Live
from rich.text import Text
from rich.markup import escape
import sys
import warnings


from utils.config import LOGGER,get_config
from dataclasses import dataclass
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    AnyMessage,
    AIMessage,
    ToolMessage,
)
from ui import prompt

from pathlib import Path
from langgraph.checkpoint.sqlite import SqliteSaver
import ui.colors as colors

from tools.tools import tools, tools_by_name
from ui.commands import cli_command, CliOutput
from utils import config

warnings.filterwarnings("ignore", message=".*v3 streaming protocol.*")


@dataclass
class ToolStart:
    tool_id: str
    tool_name: str
    tool_in: str


@dataclass
class ToolStop:
    tool_id: str
    tool_out: str


@dataclass
class ReasoningDelta:
    text: str


@dataclass
class TextDelta:
    text: str


@dataclass
class TokenUsage:
    tok_in: int = 0
    tok_out: int = 0
    tok_total: int = 0


AgentEvent = Union[ToolStart, ToolStop, ReasoningDelta, TextDelta, TokenUsage]


def agent_stream(stream) -> Iterator[AgentEvent]:
    for event in stream:
        method = event.get("method")
        params = event.get("params", {})
        data = params.get("data", {})

        # LOGGER.info(f"{method} {data}")
        if method == "tools":
            event_type = data.get("event")
            if event_type == "tool-started":
                raw_args = data.get("input")
                if isinstance(raw_args, dict):
                    args_str = ", ".join(f"{k}={v!r}" for k, v in raw_args.items())
                else:
                    args_str = str(raw_args or "")
                yield ToolStart(
                    data.get("tool_call_id"),
                    escape(str(data.get("tool_name"))),
                    args_str,
                )
            elif event_type == "tool-finished":
                yield ToolStop(data.get("tool_call_id"), str(data.get("output")))
            continue

        if method == "messages":
            if isinstance(data, (list, tuple)) and len(data) >= 2:
                msg_data, graph_meta = data[0], data[1]
            else:
                continue

            if not isinstance(msg_data, dict) or not isinstance(graph_meta, dict):
                continue
            event_type = msg_data.get("event")

            # message
            block = msg_data.get("fields") or msg_data.get("delta") or {}
            delta_type = block.get("type")

            if delta_type == "text-delta":
                text = block.get("text", "")
                if text:
                    yield TextDelta(text)
            elif delta_type in ("reasoning-delta", "reasoningch"):
                reasoning = (
                    block.get("reasoning")
                    or block.get("reasoning_content")
                    or block.get("text", "")
                )
                if reasoning:
                    yield ReasoningDelta(reasoning)

            if event_type == "message-finish" and "usage" in msg_data:
                usage = msg_data["usage"]
                yield TokenUsage(
                    tok_in=usage.get("input_tokens", 0),
                    tok_out=usage.get("output_tokens", 0),
                    tok_total=usage.get("total_tokens", 0),
                )


def execute_agent_step(raw_stream, console: Console, token_usage) -> str:
    content_str = ""
    stream = agent_stream(raw_stream)
    active_tools: dict[str, ToolStart] = {}
    tool_logs: list[str] = []
    current_status = "VEX thinking..."

    def generate_temp_ui() -> Panel:
        to_render = list(tool_logs)
        spinner_text = Text.from_markup(current_status)
        to_render.append(Spinner("star", text=spinner_text, style="vex.prompt"))
        return Panel(Group(*to_render), border_style="vex.prompt", box=SQUARE)

    config = get_config()
    keep_tool_logs: bool = not config["chat"]["keep_tool_logs"]
    with Live(
        generate_temp_ui(),
        console=console,
        refresh_per_second=12,
        transient=keep_tool_logs,
    ) as live:
        for ev in stream:
            if isinstance(ev, ToolStart):
                current_status = (
                    f"[vex.tool]Executing {ev.tool_name}({ev.tool_in})...[/vex.tool]"
                )
                active_tools[ev.tool_id] = ev
                live.update(generate_temp_ui())
            elif isinstance(ev, ToolStop):
                tool_start = active_tools.pop(ev.tool_id)
                if tool_start:
                    out_snippet = ev.tool_out.replace("\n", "")[:60] or "done"
                    tool_logs.append(
                        f"[vex.tool]{tool_start.tool_name}[/vex.tool] [vex.muted]({tool_start.tool_in})[/vex.muted]\n"
                        f"  [vex.success]✓[/vex.success] [vex.muted]{out_snippet}[/vex.muted]"
                    )
                current_status = "VEX is thinking..."
                live.update(generate_temp_ui())
            elif isinstance(ev, ReasoningDelta):
                current_status = (
                    f"[vex.think]🧠 {escape(ev.text.strip())}...[/vex.think]"
                )
                live.update(generate_temp_ui())
            elif isinstance(ev, TextDelta):
                content_str += ev.text
                current_status = "[vex.prompt]Generating response...[/vex.prompt]"
                live.update(generate_temp_ui())
            elif isinstance(ev, TokenUsage):
                token_usage.tok_in += ev.tok_in
                token_usage.tok_out += ev.tok_out
                token_usage.tok_total += ev.tok_total
                LOGGER.info(
                    f"token usage for message in:{ev.tok_in} out:{ev.tok_out} total:{ev.tok_total}"
                )

        if content_str:
            console.print("\n[vex.tool]VEX >[/vex.tool]")
            console.print(Markdown(content_str, code_theme="monokai"))
            console.print()

    return content_str


def restore_token_usage(current_state) -> TokenUsage:
    tu = TokenUsage()
    if not "messages" in current_state.values:  # early start
        return tu
    for m in current_state.values["messages"]:
        if hasattr(m, "usage_metadata"):
            u = m.usage_metadata
            tu.tok_in += u.get("input_tokens", 0)
            tu.tok_out += u.get("output_tokens", 0)
            tu.tok_total += u.get("total_tokens", 0)
    return tu


def restore_history(state, console: Console):
    messages: Optional[List[AnyMessage]] = state.values.get("messages")
    load_last_n = config.CONFIG["chat"]["load_last_n"]
    if not messages:
        return

    recent_messages = []
    for m in messages:
        if m.type == "human":
            recent_messages.append(m)
        if (
            m.type == "ai"
            and m.content
            and any(c.get("type") == "text" for c in m.content)
        ):
            recent_messages.append(m)

    LOGGER.info(f"found messages {len(messages)}")
    # -1 - load entire history
    if load_last_n != -1:
        recent_messages = recent_messages[-load_last_n:]

    for m in recent_messages:
        if m.type == "human":
            console.print(f"\n[vex.prompt]SHELL > [/vex.prompt] {m.content}")
        if m.type == "ai" and m.content:
            for c in m.content:
                if c["type"] == "text":
                    console.print("\n[vex.tool]VEX >[/vex.tool]")
                    console.print(Markdown(c["text"], code_theme="monokai"))
                    console.print()


def start_session(agent: CompiledStateGraph, session_id: str = "default"):
    config: RunnableConfig = {"configurable": {"thread_id": session_id}}
    current_state = agent.get_state(config)

    console = Console(theme=colors.CYBERPUNK.to_rich_theme())
    console.clear()
    token_usage: TokenUsage = restore_token_usage(current_state)
    restore_history(current_state, console)

    commands = ["/q", "/help", "/stat"]
    prompt_session = prompt.Prompt(console, commands)

    while True:
        user_input = prompt_session.ask("\n[vex.prompt]SHELL > [/vex.prompt]")
        if not user_input:
            continue

        # BUILTIN CMD
        if user_input.startswith("/"):
            sys.stdout.write("\x1b[1A\x1b[2K")
            sys.stdout.flush()
            cmd_resp = cli_command(user_input.lower(), console, token_usage)
            if cmd_resp == CliOutput.RES_SKIP:
                continue
            if cmd_resp == CliOutput.RES_EXIT:
                break

        # clean history
        LOGGER.info(f'user: {user_input.replace("\n"," ")}')
        stream = agent.stream_events(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
            version="v3",
            transformers=[ToolCallTransformer],
        )

        resp = execute_agent_step(stream, console, token_usage)
        LOGGER.info(f'agent: {resp.replace("\n"," ")}')
