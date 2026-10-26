import logging
import os
import tomllib
from logging import FileHandler
from pathlib import Path
from typing import Any

import dotenv

from vex_shell.utils.file_access import file_access_control

LOGGER = logging.getLogger("VEX-SHELL-DEBUG")

class Settings:
    def __init__(self) -> None:
        candidates = [
            Path.cwd()  / ".vex",
            Path.home() / ".vex",
        ]
        
        self.cfg_file_ac_time       = 0
        self.system_prompt_ac_time  = 0
        self.vex_folder:Path | None = None

        # separate loading env
        # search ENV in CWD/.vex -> HOME/.vex
        for p in candidates:
            env_file = p / ".env"
            if env_file.is_file():
                dotenv.load_dotenv(env_file,override=True)
                if os.getenv("VEX_API_KEY"):
                    break

        self.env_path = env_file.as_posix()
        
        for p in candidates:
            cfg_file =  p / "CONFIG.toml"
            if cfg_file.is_file():
                self.vex_folder = p
                break

        if not self.vex_folder:
            raise Exception(".vex folder not found")
        if not os.getenv("VEX_API_KEY"):
            raise Exception("VEX_API_KEY not found in env")
        
        self._configure()
        self.reconfigure_logger() # configure once
    
    def reconfigure_logger(self):
        LOGGER.setLevel(
            logging.getLevelNamesMapping()
                .get(self.cfg.get('logging_level','info').upper(),logging.INFO)
        )
        LOGGER.addHandler(FileHandler(f"{self.vex_folder}/vex.log", "w", "utf-8"))

    def _configure(self):
        """
        Read and load config file, 
        - set all internal fields,
        - reload settings      if modified
        - reload system prompt if modified
        """

        if self.vex_folder is None:
            raise Exception("vex_folder is not initialized")

        cfg_path = (self.vex_folder / "CONFIG.toml")        
        mtime = cfg_path.stat().st_mtime_ns

        # Update config only if it stale
        if mtime != self.cfg_file_ac_time:
            self.cfg_file_ac_time = mtime # update cfg mtime

            cfg =  tomllib.loads(cfg_path.read_text(encoding='utf-8'))
            self.cfg = cfg # raw config

            # separate settings
            self.verification = cfg.get('verification',{})
            self.model: dict[str, Any] = cfg["model"]
            self.chat: dict[str, Any] = cfg["chat"]
            self.permissions: dict[str, list[str]] = cfg["permissions"]
            self.config_path = cfg_path.as_posix()
            self.db_path = (Path(self.vex_folder) / "session.db").as_posix()

            LOGGER.debug('CONFIG reloaded, modified')
            file_access_control.reconfigure(self)
        
        # re-load system prompt on the fly
        self.system_prompt = self._get_system_prompt()

        
    def _get_system_prompt(self):
        # Location loaded once

        candidates = [
            Path.cwd()  / ".vex" / "AGENTS.md",
            Path.cwd()  /  "AGENTS.md", # keep as fallback for lazy devs
            Path.home() / ".vex" / "AGENTS.md"
        ]
        path = next((p for p in candidates if p.is_file()),None)
        if path is None:
            raise ValueError(f"System prompt not found in vex_folder {self.vex_folder}")
        
        mtime = path.stat().st_mtime_ns
        if mtime != self.system_prompt_ac_time:
            self.system_prompt_ac_time = mtime
            LOGGER.debug('SYSTEM prompt reloaded, modified')
            return path.read_text(encoding='utf-8')
        
        return self.system_prompt
    

        