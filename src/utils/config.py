from logging import Logger, FileHandler
from pathlib import Path
from typing import Any, Dict, List
import yaml
import logging
import os
import tomllib
import dotenv

LOGGER = Logger("VEX-SHELL")
LOGGER.setLevel(logging.DEBUG)
LOGGER.addHandler(FileHandler("vex.log", "w", "utf-8"))

class Settings:
    def __init__(self) -> None:
        candidates = [
            Path.cwd() / ".vex" ,
            Path.home() / ".vex",
        ]
        cfg = None

        # separate loading env
        for p in candidates:
            env_file = p /".env"
            if env_file.is_file():
                dotenv.load_dotenv(env_file)
                break

        for p in candidates:
            cfg_file =  p / "CONFIG.toml"
            if cfg_file.is_file():
                cfg =  tomllib.loads(cfg_file.read_text(encoding='utf-8'))
                provider = cfg.get("model",{}).get("VEX_API_KEY")
                if os.getenv("VEX_API_KEY") or provider == "ollama":
                    break

        if not cfg:
            raise Exception("CONFIG not found in .vex folder")
        if not os.getenv("VEX_API_KEY"):
            raise Exception("VEX_API_KEY not found in env")
        
        self.model: Dict[str, Any] = cfg["model"]
        self.chat: Dict[str, Any] = cfg["chat"]
        self.permissions: Dict[str, List[str]] = cfg["permissions"]
        self.config_path = p.as_posix()

        self.system_prompt = self._get_system_prompt()
        LOGGER.info(f'system prompt loaded from {self.config_path}')

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
        