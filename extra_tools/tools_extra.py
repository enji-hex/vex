import subprocess
import os, sys
from langchain_core.tools import  tool
from utils.file_access import file_access_control

@tool
def ripgrep_tool(regex: str, path: str, filetype: str = "") -> str:
    """
    Search for files or text matching a regex pattern inside a path using ripgrep.
    regex - regex patter for searching
    path - path to target file
    filetype - target file extension (e.g. md,txt or empty string if not specified)
    """
    try:
        target = file_access_control.validate_read(path)
    except PermissionError as err:
        return f"rg: {err}"

    if not target.exists():
        return f"rg: path '{path}' does not exist."

    clean_regex = regex.strip("'\"")
    args = ["rg", "-e", clean_regex, "-l"]

    if filetype.strip():
        ext = filetype.strip().lstrip(".")
        args.extend(["-g", f"*.{ext}"])

    args.append(str(target))
    res = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if res.returncode != 0 or res.stdout == None:
        return f"rg: no matches found for '{regex}' in {path} {res.stderr}"
    return res.stdout.strip()


# @tool
def compile_check_tool(path: str, flags: str = "-Wall -Wextra") -> str:
    """
    Check C/C++ syntax and warnings without building binaries.
    file_path - path to .c or .cpp file
    flags - extra flags (default: '-Wall -Wextra')
    Suppored extensions: .c,.cpp,.h,.hpp,.cc
    """
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        return f"Error: File '{path}' does not exist or it's not a file, perform directory discover"
    if not abs_path.endswith((".cpp", ".c", ".cc", ".hpp", ".h")):
        return f"Wrong file extension for compile_checking"

    compiler = "g++" if abs_path.endswith((".cpp", ".hpp", ".cc")) else "gcc"
    cmd = [compiler, "-fsyntax-only"] + flags.split() + [abs_path]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return f"Compilation Check PASED for {path}"
        return f"Compilation check failed:\n{res.stderr}"
    except Exception as e:
        return f"Compiler check error {str(e)}"
