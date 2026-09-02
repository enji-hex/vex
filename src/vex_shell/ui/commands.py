import sys, os
from enum import Enum, auto
from rich.box import SQUARE
from rich.console import Console
from rich.panel import Panel
from vex_shell.engine.agent import Agent


class CliOutput(Enum):
    RES_EXIT = auto()  # requrie app exit
    RES_SKIP = auto()  # require next prompt


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


def _get_state_str(b: bool):
    return "enabled" if b else "disabled"


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


async def cli_command(
    cmd: str,
    agent: Agent,
    console,
) -> CliOutput:
    if cmd == "/q":
        return CliOutput.RES_EXIT
    if cmd == "/stat":
        use_mcp = agent.settings.chat["use_mcp"]
        token_usage = agent.token_usage
        model_name = agent.settings.model["name"]
        # Yes it's crutches
        autosync_cwd_tree = _get_state_str(
            agent.settings.chat.get("autosync_cwd_tree", False)
        )
        cache_on_write = _get_state_str(
            agent.settings.chat.get("cache_on_write", False)
        )

        mcp_state = "enabled" if use_mcp == True else "disabled"
        left_padding = 20
        content = (
            f"\n{'Input:':<{left_padding}}{token_usage.tok_in} | "
            f"Output: {token_usage.tok_out} | "
            f"Total: {token_usage.tok_total}\n"
            f"{'Model:':<{left_padding}}{model_name}\n"
            f"{'MCP:':<{left_padding}}{mcp_state}\n"
            f"{'CWD auto tree:':<{left_padding}}{autosync_cwd_tree}\n"
            f"{'Cache on Write:':<{left_padding}}{cache_on_write}\n"
        )
        show_transient_panel(content, "Usage Metrics", console)
        return CliOutput.RES_SKIP

    if cmd == "/env":
        show_transient_panel(
            (
                f"{'Current workspace directory: ':<30}{agent.settings.config_path}\n"
                f"{'Current env path: ':<30}{agent.settings.env_path}"
            ),
            "Env Info",
            console,
        )
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
        state = await agent.get_state()
        loaded = state.values.get("loaded_files", {})
        cached = list(loaded.keys())

        if not cached:
            content = "No files are currently cached in the active working context."
        else:
            content = "Cached files:\n" + "\n".join(f"- {p}" for p in cached)
        show_transient_panel(content, "Cached Files", console)
        return CliOutput.RES_SKIP

    if cmd.startswith("/read"):
        pattern = cmd.split("/read")[-1].strip()

        msgs = await agent.read_files(pattern)
        show_transient_panel("\n".join(msgs), f"Manual Read {pattern}", console)
        return CliOutput.RES_SKIP

    if cmd.startswith("/del"):
        pattern = cmd.split("/del")[-1].strip()

        msgs = await agent.purge_files(pattern)
        show_transient_panel("\n".join(msgs), f"Manual Cache Clear {pattern}", console)
        return CliOutput.RES_SKIP

    # Feedback for unrecognized slash commands
    if cmd.startswith("/"):
        show_transient_panel(
            f"[bold red]Unknown command:[/bold red] {cmd}", "Error", console
        )

    return CliOutput.RES_SKIP
