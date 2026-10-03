from __future__ import annotations
import argparse
import os,time
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vex_shell.engine.agent import Agent
    from rich.console import Console
    from vex_shell.utils.config import Settings

def init_workspace(console: Console, home: bool = False) -> None:
    from importlib import resources

    vex_dir = Path.home() / ".vex" if home else Path.cwd() / ".vex"
    vex_dir.mkdir(parents=True, exist_ok=True)

    for file in resources.files("vex_shell.templates").iterdir():
        if file.is_dir() or file.name == "__init__.py":
            continue

        content = file.read_text(encoding="utf-8")
        (vex_dir / file.name).write_text(content)

    # set default .env only for home
    if home: (vex_dir / ".env").write_text('VEX_API_KEY=""')
    console.print(
        f"[vex.success]✓[/vex.success] New .vex folder initialized at "
        f"[vex.prompt]{vex_dir.absolute()}[/vex.prompt]"
    )
    console.print(
        "[vex.muted]Initialization complete. "
        "Set API keys and adjust settings for your requirements.[/vex.muted]"
    )

async def list_sessions(settings:Settings, console: Console) -> None:
    from vex_shell.engine.helpers import get_saved_sessions
    ids = await get_saved_sessions(settings.db_path)
    console.print(f"[vex.success][✓] Saved Session[/vex.success] DB_PATH: {settings.db_path}")
    for id in ids:
        console.print(f"- {id}")

async def run_agent(args):
    # no args , init systemwide config
    if not Path.exists(Path.home() / ".vex"):
        from rich.console import Console
        console = Console()
        init_workspace(console=console, home=True)
        return

    if args.reset:
        (Path.cwd() / ".vex" / "session.db").unlink(missing_ok=True)
        return
    if args.reset_global:
        (Path.home() / ".vex" / "session.db").unlink(missing_ok=True)
        return

    # loading config themes
    from vex_cli import colors
    from vex_shell.utils import config
    from vex_shell.utils.file_access import file_access_control

    settings = config.Settings()
    file_access_control.reconfigure(settings)

    theme_name = settings.chat.get('theme','Fallout-3-Dark-Mode')
    sel_theme,themes = colors.load_theme(theme_name)
    if not sel_theme:
        raise Exception(f'Error theme {theme_name} doesnt exists in themes.csv')

    # start console for sane(pretty) output
    from rich.console import Console
    console = Console(theme=sel_theme.to_rich_theme())
    
    if args.init:
        init_workspace(console=console)
        return
    if args.list_themes:
        console.print(f"[vex.success][✓] Available themes[/vex.success]")
        for id in themes:
            console.print(f"- {id}")
        return
    if args.list_sessions:
        await list_sessions(settings,console)
        return
    
    # Start agent
    from vex_shell.engine import core
    from vex_shell.engine.agent import Agent

    # timings check
    # ---------------------
    t0 = time.perf_counter_ns()

    tools,mcp_manager = await core.get_tools(settings)
    t_tools = time.perf_counter_ns()

    graph = core.build_graph(settings, tools)
    t_graph = time.perf_counter_ns()

    agent = await Agent.create(graph, args.session, settings, mcp_manager)
    t_agent = time.perf_counter_ns()

    config.LOGGER.debug(
        "Startup breakdown:\n"
        f"- Tools & MCP:  {(t_tools - t0) / 1e6:.1f}ms\n"
        f"- Graph Build:  {(t_graph - t_tools) / 1e6:.1f}ms\n"
        f"- Agent Init:   {(t_agent - t_graph) / 1e6:.1f}ms\n"
        f"- Total Core:   {(t_agent - t0) / 1e6:.1f}ms"
    )
    # ---------------------
    
    try:
        from vex_cli.console import start_session
        await start_session(agent, console)
    finally:
        await agent.close()

def cli() -> None:
    # startup marker
    os.environ["VEX_START_NS"] = str(time.perf_counter_ns())

    parser = argparse.ArgumentParser(
        description=(
            "VEX Shell – initialise a workspace or start an agent session. "
            "If the current directory has no .vex folder, a user‑wide one is created."
        )
    )
    parser.add_argument(
        "--init", "-i", action="store_true", help="Initialize .vex project"
    )
    parser.add_argument(
        "--session", "-s", default="default", help="Initialize .vex project"
    )
    parser.add_argument(
        "--list-themes", "-lt",action="store_true", help="List available color schemes"
    )
    parser.add_argument(
        "--list-sessions", "-ls", action="store_true", help="List saved sessions"
    )
    parser.add_argument("--reset", action="store_true", help="reset sqlite database")
    parser.add_argument(
        "--reset-global",
        action="store_true",
        help="reset global sqlite database (in user home)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run_agent(args))
    except (KeyboardInterrupt, asyncio.CancelledError):
        from rich.console import Console
        Console().print("\n[yellow]Session interrupted by user. Shutting down...[/yellow]")
    except Exception as e:
        from rich.console import Console
        Console().print(f"\n[red][bold]Unexpected error:[/bold] {e}[/red]")
    

if __name__ == "__main__":
    cli()
