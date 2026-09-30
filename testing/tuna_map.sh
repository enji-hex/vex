#!/bin/sh

echo "/q" | uv run python -X importtime ./src/vex_cli/cli.py 2> /tmp/vex_import.log && uvx tuna /tmp/vex_import.log