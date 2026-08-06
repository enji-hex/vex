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


def cli_command(cmd, console, token_usage) -> CliOutput:
    llm_config = config.get_config()

    if cmd == "/q":
        return CliOutput.RES_EXIT
    if cmd == "/stat":
        mcp_state = "enabled" if llm_config['chat']['use_mcp'] == True else "disabled"
        content = (
            f"\nInput: {token_usage.tok_in:>6} | "
            f"Output: {token_usage.tok_out:>6} | "
            f"Total: {token_usage.tok_total:>6}\n"
            f"Model: {llm_config['model']['name']}\n"
            f"MCP:   {mcp_state}\n"
        )
        show_transient_panel(content, "Usage Metrics", console)
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

    # Feedback for unrecognized slash commands
    if cmd.startswith("/"):
        show_transient_panel(
            f"[bold red]Unknown command:[/bold red] {cmd}", "Error", console
        )

    return CliOutput.RES_SKIP
