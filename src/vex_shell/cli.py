import argparse
import asyncio
from importlib import resources
from pathlib import Path
import sys

from rich.console import Console
from vex_shell.ui import colors
from vex_shell.utils import config
from vex_shell.utils.file_access import file_access_control
from vex_shell.engine.agent import Agent
import vex_shell.engine.core as core
from vex_shell.engine import core


def init_workspace(console: Console, home: bool = False) -> None:
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

async def list_sessions(agent:Agent, console: Console) -> None:
    ids = await agent.get_sessions()
    console.print(f"[vex.success][✓] Saved Session[/vex.success] DB_PATH: {agent.settings.db_path}")
    for id in ids:
        console.print(f"- {id}")

async def run_agent(args):
    settings = config.Settings()
    file_access_control.reconfigure(settings)

    theme_name = settings.chat.get('theme','Fallout 3 Dark Mode')
    sel_theme,themes = colors.load_theme(theme_name)
    if not sel_theme:
        raise Exception(f'Error theme {theme_name} doesnt exists in themes.csv')
    
    console = Console(theme=sel_theme.to_rich_theme())
    if args.init:
        init_workspace(console=console)
        return
    if args.reset:
        (Path.cwd() / ".vex" / "session.db").unlink(missing_ok=True)
        return
    if args.reset_global:
        (Path.home() / ".vex" / "session.db").unlink(missing_ok=True)
        return
    if args.list_themes:
        console.print(f"[vex.success][✓] Available themes[/vex.success]")
        for id in themes:
            console.print(f"- {id}")
        return

    # no args , init systemwide config
    vex_dir = Path.cwd() / ".vex"
    if not Path.exists(vex_dir):
        init_workspace(console=console, home=True)
        return

    
    tools,mcp_manager = await core.get_tools(settings)
    graph = core.build_graph(settings, tools)
    agent = await Agent.create(graph, args.session, settings, mcp_manager)
    
    try:
        if args.list_sessions:
            await list_sessions(agent,console)
            return

        from vex_shell.ui.console import start_session
        await start_session(agent, console)
    except (KeyboardInterrupt, asyncio.CancelledError):
        console.print(
            "\n[yellow]Session interrupted by user. Shutting down...[/yellow]"
        )
    except Exception as e:
        console.print(f"\n[red]Unexpected error: {e}[/red]")
    finally:
        await agent.close()

def cli() -> None:
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
    asyncio.run(run_agent(args))


if __name__ == "__main__":
    cli()
