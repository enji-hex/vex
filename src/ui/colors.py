from dataclasses import dataclass
from rich.theme import Theme


@dataclass
class Palette:
    name: str
    primary: str  # shell prompt
    accent: str  # tool exec / warnings
    success: str  # done marks
    muted: str  # thinking/secondary

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


EVA_03 = Palette(
    name="EVA-03",
    primary="#9d4edd",  # Unit-03 Violet
    accent="#ff3b00",  # Infected Orange-Red
    success="#00ff66",  # Toxic Green
    muted="#727d85",  # Dark Steel Grey
)

CYBERPUNK = Palette(
    name="Cyberpunk",
    primary="#ff007f",
    accent="#00f0ff",
    success="#00ff66",
    muted="#6272a4",
)

FALLOUT = Palette(
    name="Fallout 3 Dark Mode",
    primary="#18FF62",  # Bright HUD text green
    accent="#00CC44",  # Deep green for active states / buttons
    success="#39FF14",  # High-visibility neon green
    muted="#5A5A5A",  # Mid-tone dark green for secondary text / borders
)
