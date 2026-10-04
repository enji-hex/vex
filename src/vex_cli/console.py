from typing import (
    List,
)
import os
from rich.box import SQUARE
from rich.console import Console, Group
from rich.panel import Panel
from rich.status import Status
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.live import Live
from rich.text import Text
import sys, io,time


from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    AnyMessage,
    AIMessage,
    ToolMessage,
)

from vex_shell.utils.config import LOGGER
from vex_shell.utils.fs import sync_cwd_tree
from vex_cli.commands import cli_command, CliOutput,CliResult
from vex_shell.engine.events import *
from vex_shell.engine.agent import Agent
from vex_cli import prompt

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")

# Alternative duck-typing check
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def clean_snippet(text: str, limit: int = 60) -> str:
    cleaned = " ".join(text.splitlines()).strip()
    return cleaned[:limit] if cleaned else ""

def wait_for_key():
    if os.name == "nt":
        import msvcrt

        msvcrt.getch()
        while msvcrt.kbhit():
            msvcrt.getch()
    else:
        import tty, termios, select

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            sys.stdin.read(1)
            while select.select([sys.stdin], [], [], 0.001)[0]:
                sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def show_transient_panel(content: str, title: str, console: Console):
    """Displays a popup panel that self-destructs after a keypress."""

    panel = Panel(
        content,
        title=title,
        title_align="left",
        box=SQUARE,
        border_style="vex.prompt",
        expand=False,
        width=max(console.width - 2, 20),
    )
    console.show_cursor(False)
    try:
        with console.screen():
            console.print(panel)
            wait_for_key()
    finally:
        console.show_cursor(True)
        console.file.flush()


async def execute_agent_step(stream, keep_tool_logs: bool, console: Console) -> str:
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
                t = Text.from_markup(log, overflow="ellipsis")
                t.no_wrap = True
                formatted_logs.append(t)
            to_render.append(Group(*formatted_logs))

        if thinking_str:
            lines = [l.strip() for l in thinking_str.splitlines() if l.strip()]
            tail_lines = lines[-2:] if lines else ["..."]
            tail = "\n".join(tail_lines)

            to_render.append(
                Panel(
                    Text(tail, style="vex.muted", overflow="ellipsis"),
                    title="[vex.think]🧠 Thinking[/vex.think]",
                    title_align="left",
                    border_style="vex.think",
                    width=inner_width,
                    box=SQUARE,
                )
            )

        if current_status:
            spinner_text = Text.from_markup(current_status, overflow="ellipsis")
            spinner_text.no_wrap = True
            to_render.append(Spinner("star", text=spinner_text, style="vex.prompt"))

        return Panel(
            Group(*to_render),
            border_style="vex.prompt",
            box=SQUARE,
            width=safe_width,
            expand=False,
        )

    with Live(
        generate_temp_ui(),
        console=console,
        refresh_per_second=12,
        transient=keep_tool_logs,
    ) as live:
        async for ev in stream:
            if isinstance(ev, ToolStart):
                current_status = f"[vex.tool]Executing {ev.tool_name}({ev.tool_in[:60]})...[/vex.tool]"
                active_tools[ev.tool_id] = ev
                live.update(generate_temp_ui())
            elif isinstance(ev, ToolStop):
                tool_start = active_tools.pop(ev.tool_id)
                if tool_start:
                    out_snippet = clean_snippet(ev.tool_out) or "done"
                    in_snippet = clean_snippet(tool_start.tool_in)
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
                if isinstance(c, dict) and c["type"] == "text":
                    console.print("\n[vex.tool]VEX >[/vex.tool]")
                    console.print(Markdown(c["text"], code_theme="monokai"))
                    console.print()


async def start_session(
    agent: Agent,
    console: Console,
):
    console.clear()
    keep_tool_logs: bool = not agent.settings.chat["keep_tool_logs"]
    await restore_history(agent, console)

    commands = ["/q", "/help", "/stat", "/env", "/cached", "/read", "/del","/voice"]
    prompt_session = prompt.Prompt(console, commands)

    user_input_default = ""
    
    start_ns = os.environ.get("VEX_START_NS")
    if start_ns:
        elapsed_ms = (time.perf_counter_ns() - int(start_ns)) / 1_000_000
        LOGGER.debug(f'console started, elapsed time {elapsed_ms:.2f}ms')

    while True:
        user_input = await prompt_session.ask(
            "\n[vex.prompt]SHELL > [/vex.prompt]",
            # pass recorded string in user input if exists
            default=user_input_default) 
        user_input_default = ""

        if not user_input:
            continue

        # BUILTIN CMD
        if user_input.startswith("/"):
            sys.stdout.write("\x1b[1A\x1b[2K")
            sys.stdout.flush()
            cmd_resp = await cli_command(user_input.lower(), agent, 
                                         console=console,
                                         prompt_session=prompt_session.prompt_session)
            
            match cmd_resp.result:
                case CliOutput.SKIP:
                    show_transient_panel(cmd_resp.content,cmd_resp.title,console)
                    continue
                case CliOutput.EXIT:
                    break
                case CliOutput.RENDER:
                    # /voice
                    user_input_default = cmd_resp.content
                    LOGGER.info(f'user transcription {cmd_resp}')
                    continue
                

        # clean history
        LOGGER.info(f'user: {user_input.replace("\n"," ")}')

        stream = agent.run_step(user_input)
        resp = await execute_agent_step(stream, keep_tool_logs, console)
        LOGGER.info(f'agent: {resp.replace("\n"," ")}')