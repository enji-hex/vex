import argparse
import asyncio
from importlib import resources
from pathlib import Path
import sys
from typing import Dict

from rich.console import Console
from ui import colors
from utils import config
from utils.file_access import file_access_control
import sqlite3
import engine.core as core
import uuid_utils

def init_workspace(console: Console, home: bool = False) -> None:
    vex_dir = Path.home() / ".vex" if home else Path.cwd() / ".vex"
    vex_dir.mkdir(parents=True, exist_ok=True)

    for file in resources.files("templates").iterdir():
        if file.is_dir() or file.name == "__init__.py":
            continue

        content = file.read_text(encoding="utf-8")
        (vex_dir / file.name).write_text(content)

    (vex_dir / ".env").write_text('VEX_API_KEY=""')

    console.print(
        f"[vex.success]✓[/vex.success] New .vex folder initialized at "
        f"[vex.prompt]{vex_dir.absolute()}[/vex.prompt]"
    )
    console.print(
        "[vex.muted]Initialization complete. "
        "Set API keys and adjust settings for your requirements.[/vex.muted]"
    )


def list_sessions(db_path: str, console: Console) -> None:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
        )
        rows = cursor.fetchall()
        ids = [r[0] for r in rows if r[0] is not None]

        console.print(
            f"[vex.success][✓] Saved Session[/vex.success] DB_PATH: {db_path}"
        )
        for id in ids:
            console.print(f"- {id}")


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
        "--list-sessions", "-ls", action="store_true", help="List saved sessions"
    )
    parser.add_argument("--reset", action="store_true", help="reset sqlite database")
    parser.add_argument(
        "--reset-global",
        action="store_true",
        help="reset global sqlite database (in user home)",
    )
    args = parser.parse_args()

    console = Console(theme=colors.FALLOUT.to_rich_theme())

    if args.init:
        init_workspace(console=console)
        sys.exit(0)
    if args.reset:
        (Path.cwd() / ".vex" / "session.db").unlink(missing_ok=True)
        sys.exit(0)
    if args.reset_global:
        (Path.home() / ".vex" / "session.db").unlink(missing_ok=True)
        sys.exit(0)

    # no args , init systemwide config
    vex_dir = Path.cwd() / ".vex"
    if not Path.exists(vex_dir):
        init_workspace(console=console, home=True)

    settings = config.Settings()
    file_access_control.reconfigure(settings)
    config.LOGGER.info(
        f"Read prefixes: {file_access_control.read_patterns} | "
        f"Write prefixes: {file_access_control.write_patterns}"
    )

    if args.list_sessions:
        list_sessions(settings.db_path, console)
        sys.exit(0)

    asyncio.run(core.run_agent(console, settings, args.session))


if __name__ == "__main__":
    cli()
