
# VEX SHELL

<style>
    a{color:orange}
</style>
<pre style="color:orange;background-color:transparent">
██╗   ██╗███████╗██╗  ██╗
██║   ██║██╔════╝╚██╗██╔╝
██║   ██║█████╗   ╚███╔╝ 
╚██╗ ██╔╝██╔══╝   ██╔██╗ 
 ╚████╔╝ ███████╗██╔╝ ██╗
  ╚═══╝  ╚══════╝╚═╝  ╚═╝
</pre>

VEX is a **terminal‑first AI agent** that keeps your workspace in sync while you interact with large language models. It combines LangChain, LangGraph, and OpenRouter to give you a fast, secure, and extensible development assistant.


## Core Highlights
- **State‑graph agent** with async SQLite checkpointing – sessions survive crashes and can be resumed.
- **Active Working Context** – the latest versions of all files you read are injected into the LLM prompt,
  dramatically cutting token usage.
- **Sandboxed file access** – strict read/write prefix validation prevents path‑traversal attacks.
- **Sliding‑window context manager** (≤ 4 k tokens) keeps prompts within model limits.
- **Dynamic MCP tool loading** – plug‑in external tools at runtime via MCP.
- **Rich UI theming** – three ready‑made palettes (Fallout, Cyberpunk, EVA‑03) built on Rich.
- **Sub‑second local response** – LLM calls return in under a second thanks to token‑budgeted prompts and async I/O.



## Quick Start
```bash
# Clone and install
git clone https://codeberg.org/Enji/vex.git
cd vex
pip install -e .

# Initialise a workspace
vex --init

# Start an interactive session
vex
```


Example Workflow

1. read_file path/to/module.py – caches the file in the active context.
2. Ask the agent: “Refactor module.py to use async I/O.”
3. VEX injects the cached file into the prompt, the LLM returns the refactored code, and you can write_file the changes
   back.

Extending VEX

- Add new LangChain tools in src/tools/tools.py.
- Drop an MCP config in .vex/mcp_config.json to load external services.
- Create a custom Rich palette in src/ui/colors.py.

## In-depth

- [File Context Management](./docs/file_context_management.md)


## License

GPL-3 – feel free to fork, improve, and share.