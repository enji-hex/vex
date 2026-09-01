from typing import (
    AsyncIterator,
    List,
    Optional,
)
from rich.box import SQUARE
from rich.console import Console, Group
from rich.panel import Panel
from rich.status import Status
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.live import Live
from rich.text import Text
import sys,io
from utils.file_access import file_access_control

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    AnyMessage,
    AIMessage,
    ToolMessage,
)

from utils.config import LOGGER
from ui import prompt
from ui.commands import cli_command, CliOutput
from utils import config
from ui.events import *

from engine.stream_processor import Agent
from engine import stream_processor

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")

# Alternative duck-typing check
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def clean_snippet(text:str , limit:int = 60) -> str:
    cleaned = " ".join(text.splitlines()).strip()
    return cleaned[:limit] if cleaned else ""

async def execute_agent_step(stream, 
                             keep_tool_logs:bool,
                             console: Console
                             ) -> str:
    """
    Process text only
    """
    content_str = ""
    thinking_str = ""
    active_tools: dict[str, ToolStart] = {}
    tool_logs: list[str] = []
    current_status = "VEX thinking..."

    def generate_temp_ui() -> Panel:
        safe_width = max(console.width - 2, 20)
        inner_width = max(safe_width - 4, 16)

        to_render = []

        if tool_logs:
            max_tool_logs = 3
            visible_logs = tool_logs[-max_tool_logs:]

            formatted_logs = []
            for log in visible_logs:
                t = Text.from_markup(log,overflow="ellipsis")
                t.no_wrap = True
                formatted_logs.append(t)
            to_render.append(Group(*formatted_logs))

        if thinking_str:
            lines = [l.strip() for l in thinking_str.splitlines() if l.strip()]
            tail_lines = lines[-2:] if lines else ["..."]
            tail = "\n".join(tail_lines)

            to_render.append(
                Panel(
                    Text(tail, style="vex.muted",overflow='ellipsis'),
                    title="[vex.think]🧠 Thinking[/vex.think]",
                    title_align="left",
                    border_style="vex.think",
                    width=inner_width,
                    box=SQUARE,
                )
            )

        if current_status:
            spinner_text = Text.from_markup(
                current_status,
                overflow='ellipsis')
            spinner_text.no_wrap = True
            to_render.append(Spinner("star", text=spinner_text, style="vex.prompt"))

        return Panel(
            Group(*to_render), 
            border_style="vex.prompt", 
            box=SQUARE,
            width=safe_width,
            expand=False
            )

    with Live(
        generate_temp_ui(),
        console=console,
        refresh_per_second=12,
        transient=keep_tool_logs,
    ) as live:
        async for ev in stream:
            if isinstance(ev, ToolStart):
                current_status = (
                    f"[vex.tool]Executing {ev.tool_name}({ev.tool_in[:60]})...[/vex.tool]"
                )
                active_tools[ev.tool_id] = ev
                live.update(generate_temp_ui())
            elif isinstance(ev, ToolStop):
                tool_start = active_tools.pop(ev.tool_id)
                if tool_start:
                    out_snippet = clean_snippet(ev.tool_out) or "done"
                    in_snippet  = clean_snippet(tool_start.tool_in)
                    tool_logs.append(
                        f"[vex.tool]{tool_start.tool_name}[/vex.tool] [vex.muted]({in_snippet})[/vex.muted]\n"
                        f"  [vex.success]✓[/vex.success] [vex.muted]{out_snippet}[/vex.muted]"
                    )
                current_status = "VEX is thinking..."
                live.update(generate_temp_ui())
            elif isinstance(ev, ReasoningDelta):
                thinking_str += ev.text
                current_status = "[vex.think]Thinking...[/vex.think]"
                live.update(generate_temp_ui())
            elif isinstance(ev, TextDelta):
                content_str += ev.text
                current_status = "[vex.prompt]Generating response...[/vex.prompt]"
                live.update(generate_temp_ui())

        if content_str:
            console.print("\n[vex.tool]VEX >[/vex.tool]")
            console.print(Markdown(content_str, code_theme="monokai"))
            console.print()

    return content_str



# move to Agent
async def restore_history(agent, console: Console):
    messages: List[AnyMessage] = await agent.restore_history()
    load_last_n = agent.settings.chat["load_last_n"]

    LOGGER.info(f"found messages {len(messages)}")
    # -1 - load entire history
    if load_last_n != -1:
        messages = messages[-load_last_n:]

    for m in messages:
        if m.type == "human":
            console.print(f"\n[vex.prompt]SHELL > [/vex.prompt] {m.content}")
        if m.type == "ai" and m.content:
            for c in m.content:
                if c["type"] == "text":
                    console.print("\n[vex.tool]VEX >[/vex.tool]")
                    console.print(Markdown(c["text"], code_theme="monokai"))
                    console.print()

async def start_session(
    agent: Agent, 
    console: Console, 
):
    console.clear()
    keep_tool_logs:bool      = not agent.settings.chat["keep_tool_logs"]
    await restore_history(agent, console)

    commands = ["/q", "/help", "/stat",'/env','/cached','/read']
    prompt_session = prompt.Prompt(console, commands)

    while True:
        user_input = await prompt_session.ask("\n[vex.prompt]SHELL > [/vex.prompt]")
        if not user_input:
            continue

        # BUILTIN CMD
        if user_input.startswith("/"):
            sys.stdout.write("\x1b[1A\x1b[2K")
            sys.stdout.flush()
            cmd_resp = await cli_command(user_input.lower(),
                                   agent,
                                   console
                                   )
            if cmd_resp == CliOutput.RES_SKIP:
                continue
            if cmd_resp == CliOutput.RES_EXIT:
                break

        # clean history
        LOGGER.info(f'user: {user_input.replace("\n"," ")}')
        
        stream = agent.run_step(user_input)
        resp = await execute_agent_step(stream,keep_tool_logs, console)
        LOGGER.info(f'agent: {resp.replace("\n"," ")}')
