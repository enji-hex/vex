from logging import Logger, FileHandler
from pathlib import Path
import yaml
import logging
import os
import tomllib

LOGGER = Logger("VEX-SHELL")
LOGGER.setLevel(logging.INFO)
LOGGER.addHandler(FileHandler("vex.log", "w", "utf-8"))

CONFIG = None

def get_config():
    global CONFIG
    if CONFIG is not None: return CONFIG

    candidates = [
        Path.cwd() / ".vex" / "CONFIG.toml",
        Path.home() / ".vex" / "CONFIG.toml",
    ]
    for p in candidates:
        if p.is_file():
            CONFIG =  p.read_text(encoding='utf-8')
            return CONFIG
        
    raise Exception("CONFIG not found in .vex folder")

