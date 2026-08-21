import sys, os
from enum import Enum, auto
from typing import Text

from rich.box import SQUARE
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from utils import config


class CliOutput(Enum):
    RES_EXIT = auto()  # requrie app exit
    RES_SKIP = auto()  # require next prompt


def wait_for_key():
    if os.name == "nt":
        import msvcrt

        msvcrt.getch()
    else:
        import tty, termios

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def show_transient_panel(content: str, title: str, console: Console):
    """Displays a popup panel that self-destructs after a keypress."""
    with Live(
        Panel(
            content,
            title=title,
            title_align="left",
            box=SQUARE,
            border_style="vex.prompt",
        ),
        console=console,
        transient=True,
    ):
        wait_for_key()


def cli_command(cmd, settings:config.Settings,console,
                token_usage,state) -> CliOutput:
    if cmd == "/q":
        return CliOutput.RES_EXIT
    if cmd == "/stat":
        mcp_state = "enabled" if settings.chat['use_mcp'] == True else "disabled"
        content = (
            f"\n{'Input:':<10}{token_usage.tok_in} | "
            f"Output: {token_usage.tok_out} | "
            f"Total: {token_usage.tok_total}\n"
            f"{'Model:':<10}{settings.model['name']}\n"
            f"{'MCP:':<10}{mcp_state}\n"
        )
        show_transient_panel(content, "Usage Metrics", console)
        return CliOutput.RES_SKIP
    
    if cmd == "/env":
        show_transient_panel(f'Current ENV loaded from: {settings.config_path}',"Env Path",console)
        return CliOutput.RES_SKIP
    
    if cmd == "/help":
        content = (
            "██╗   ██╗███████╗██╗  ██╗\n"
            "██║   ██║██╔════╝╚██╗██╔╝\n"
            "██║   ██║█████╗   ╚███╔╝ \n"
            "╚██╗ ██╔╝██╔══╝   ██╔██╗ \n"
            " ╚████╔╝ ███████╗██╔╝ ██╗\n"
            "  ╚═══╝  ╚══════╝╚═╝  ╚═╝\n"
            "- - - - - - - - - - - - -\n\n"
            "VEX - lean CLI agentic control system\n\n"
            "AVAILABLE COMMANDS:\n"
            "  /q    - Quit session\n"
            "  /stat - Show token usage\n"
            "  /help - Show help menu\n"
        )
        show_transient_panel(content, "Help", console)
        return CliOutput.RES_SKIP

    if cmd == "/cached":
        loaded = state.values.get("loaded_files",{})
        cached = list(loaded.keys())
        if not cached:
            content = "No files are currently cached in the active working context."
        else:
            content = "Cached files:\n" + "\n".join(f"- {p}" for p in cached)
        show_transient_panel(content,"Cached Files",console)
        return CliOutput.RES_SKIP
    
    # Feedback for unrecognized slash commands
    if cmd.startswith("/"):
        show_transient_panel(
            f"[bold red]Unknown command:[/bold red] {cmd}", "Error", console
        )

    return CliOutput.RES_SKIP
