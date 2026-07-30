from logging import Logger, FileHandler
import yaml
import logging
import os

LOGGER = Logger("VEX-SHELL")
LOGGER.setLevel(logging.INFO)
LOGGER.addHandler(FileHandler("vex.log", "w", "utf-8"))

conf_path = os.path.join(os.getcwd(), ".vex/CONFIG.yaml")
print(conf_path)
if not os.path.exists(conf_path):
    raise Exception("CONFIG not found in .vex folder")

with open(conf_path) as f:
    CONFIG = yaml.safe_load(f)
