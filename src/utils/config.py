from logging import Logger, FileHandler
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

    conf_path = os.path.join(os.getcwd(), ".vex/CONFIG.toml")
    if not os.path.exists(conf_path):
        raise Exception("CONFIG not found in .vex folder")

    with open(conf_path,'rb') as f:
        return tomllib.load(f)

