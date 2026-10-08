import csv
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from rich.theme import Theme
from vex_shell.utils.config import LOGGER

@dataclass
class Palette:
    name: str
    primary: str  # shell prompt
    accent: str   # tool exec / warnings
    success: str  # done marks
    muted: str    # thinking/secondary

    def to_rich_theme(self) -> Theme:
        return Theme(
            {
                "vex.prompt": f"bold {self.primary}",
                "vex.border": self.primary,
                "vex.tool": f"bold {self.accent}",
                "vex.success": f"bold {self.success}",
                "vex.muted": f"dim {self.muted}",
                "vex.think": f"italic {self.muted}",
            }
        )

def load_theme(theme_name:str) -> tuple[Palette | None, list[str]]:
    user_themes     = Path().home() / ".vex" / "themes.csv"
    themes = []
    sel_theme = None

    if user_themes.exists():
        LOGGER.info('load user themes.csv')
        file = user_themes.read_text()
    else:
        file = (
            resources.files('vex_shell.templates')
            .joinpath('themes.csv')
            .read_text(encoding='utf-8')
        )

    reader = csv.DictReader(file.splitlines(),delimiter=',')
    for row in reader:
        themes.append(row['name'])
        if row['name'] == theme_name:
            sel_theme =  Palette(**row)
    
    return sel_theme,themes

