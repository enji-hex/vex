from prompt_toolkit.completion import WordCompleter
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings

from rich.console import Console


class Prompt:
    def __init__(self, console: Console, commands: list[str]):
        self.console = console

        kb = KeyBindings()

        @kb.add("s-left", "enter")
        @kb.add("s-right", "enter")
        @kb.add(
            "escape", "enter"
        )  # Alt + Enter / Esc + Enter (Universal terminal fallback)
        def _(event):
            """Inserts a newline without submitting the prompt."""
            event.current_buffer.insert_text("\n")

        vex_completer       = WordCompleter(commands, ignore_case=True, sentence=True)
        self.prompt_session = PromptSession(completer=vex_completer, key_bindings=kb)

    async def ask(self, markup: str,default:str = "") -> str:
        """Converts Rich markup string directly into prompt_toolkit ANSI format."""
        with self.console.capture() as capture:
            self.console.print(markup, end="")
        self.console.file.flush()

        captured = ANSI(capture.get().strip("\r\n"))
        return (
            await self.prompt_session.prompt_async(captured,default=default)
        ).strip()
