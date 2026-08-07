from logging import Logger, FileHandler
from pathlib import Path
from typing import Any, Dict, List
import yaml
import logging
import os
import tomllib

LOGGER = Logger("VEX-SHELL")
LOGGER.setLevel(logging.INFO)
LOGGER.addHandler(FileHandler("vex.log", "w", "utf-8"))

class Settings:
    def __init__(self) -> None:
        candidates = [
            Path.cwd() / ".vex" / "CONFIG.toml",
            Path.home() / ".vex" / "CONFIG.toml",
        ]
        cfg = None
        for p in candidates:
            if p.is_file():
                cfg =  tomllib.loads(p.read_text(encoding='utf-8'))
                break
        if not cfg:
            raise Exception("CONFIG not found in .vex folder")
        
        self.model: Dict[str, Any] = cfg["model"]
        self.chat: Dict[str, Any] = cfg["chat"]
        self.permissions: Dict[str, List[str]] = cfg["permissions"]

        self.system_prompt = self._get_system_prompt()
        LOGGER.info(f'system prompt loaded from {p.as_posix()}')

    def _get_system_prompt(self):
        candidates = [
            Path.cwd() / ".vex" / "AGENTS.md",
            Path.cwd() /  "AGENTS.md", # keep as fallback for lazy devs
            Path.home() / ".vex" / "AGENTS.md"
        ]
        for p in candidates:
            if p.is_file():
                return p.read_text(encoding='utf-8')
        return ""
        