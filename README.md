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

VEX is a **terminal‑first AI agent** (and *open source async agentic runtime*) that keeps your workspace in sync while you interact with large language models. It combines LangChain, LangGraph, and OpenRouter(or ollama) to give you a fast, secure, and extensible development assistant.

## Core Highlights
- **State‑graph agent** with async SQLite checkpointing – sessions survive crashes and can be resumed.
- **Active Working Context** – the latest versions of all files you read and CWD tree are injected into the LLM prompt, dramatically cutting token usage.
- **Automatic cache purge** – on every LLM turn the system syncs loaded files and removes entries for files that no longer exist on disk.
- **Token usage tracking** – `/stat` shows input, output, and total token counts for the current session.
- **Sandboxed file access** – strict read/write prefix validation prevents path‑traversal attacks.
- **Sliding‑window context manager**  keeps prompts within model limits.
- **Dynamic MCP tool loading** – plug‑in external tools at runtime via MCP (`.vex/mcp_config.json`).
- **Rich UI theming** – three ready‑made palettes (Fallout, Cyberpunk, EVA‑03) built on Rich.
- **CWD tree** - optional feature automatically inject tree of curent working directory in LLM prompt (ActiveContext)
- **Cache on Write** - optional feature, automatically add to FileContext each file written by LLM


## Quick Start

### As Tool
```bash
# Install directly from the repository (no manual clone needed)
uv tool add git+[https://codeberg.org/Enji/vex.git#egg=vex_shell][cli]

# Initialize global config folder ~/.vex
vex

# Initialise a local workspace in the current directory
vex --init

# Set your API key (required for OpenRouter or other providers)
#   • Global: edit ~/.vex/.env
#   • Local : edit .vex/.env
# Example content:
#   VEX_API_KEY="your‑api‑key‑here"

# Start an interactive session (uses the local .vex if present, otherwise the global one)
vex
```

### As Library

```bash
uv add git+https://codeberg.org/Enji/vex.git
```

```python
from vex_shell.engine.core import build_graph, get_tools
from vex_shell.engine.agent import Agent
from vex_shell.utils.config import Settings
from vex_shell.utils.file_access import file_access_control
from vex_shell.ui import events

import asyncio

async def main():
    settings = Settings() # default settings for agent from .vex/CONFIG.toml
    # reconfigure file_access with respect to selected config
    file_access_control.reconfigure(settings)
    # gather tools and mcp_manager ( control foreign tools )
    tools,mcp_manager = await get_tools(settings)

    # build graph for an Agent
    graph = build_graph(settings,tools)
    agent = await Agent.create(graph,"4",settings,mcp_manager)
    
    # We are ready to start
    stream = agent.run_step("read ./main.py and print here")
    print(f'used key from {agent.settings.env_path}')
    async for ev in stream:
        if isinstance(ev,events.TextDelta):
            print(ev.text,end='',flush=True)
        elif isinstance(ev,events.ToolStart):
            print(f'[start tool: {ev.tool_name} ]',end='',flush=True)
    
    print('total token usage: '+str(agent.token_usage.tok_total))
    await agent.close()

if __name__ == "__main__":
    asyncio.run(main())

```

Full agent functionality out of the box!!
All information about available [Events](./src/vex_shell/ui/events.py).

> IMPORTANT **ReasoningDelta** event supported only by openrouter provider


## Example Workflow
1. `read_files path/to/module.py` – caches the file in the active context.
2. Ask the agent: “Refactor `module.py` to use async I/O.”
3. VEX injects the cached file into the prompt, the LLM returns the refactored code and writes back to  `module.py` with  `write_file` tool. 

## Extending VEX
- Add new LangChain tools in `src/tools/tools.py`.
- Drop an MCP config in `.vex/mcp_config.json` to load external services.
- Create a custom Rich palette in `src/ui/colors.py`.

## CLI Flags

| Flag | Description |
|------|-------------|
| `-i`, `--init` | Initialise a new `.vex` workspace (creates folder and template files). |
| `-s`, `--session <name>` | Choose a session identifier; defaults to `default`. |
| `-ls`, `--list-sessions` | List all saved session IDs stored in the SQLite checkpoint database. |
| `--reset` | Delete the local `.vex/session.db` database, clearing all cached sessions for the current workspace. |
| `--reset-global` | Delete the global `~/.vex/session.db`, clearing session database at home directory |

## CLI Commands (available during an interactive session)

| Command | Description |
|---------|-------------|
| `/cached` | Show a list of files currently cached in the active working context. |
| `/read` | Manual add files in FileContext by glob pattern `/read ./src/**` |
| `/del` | MAnual purge fiels from FileContext by glob pattern `/del ./src/engine/**.py` |
| `/stat` | Display token usage statistics (input, output, total) and the model being used. |
| `/env` | Reveal the path of the loaded environment configuration file (`.env`). |
| `/help` | Show the help screen with available slash commands. |
| `/q` | Quit the current VEX session. |

## In‑depth Docs
- [File Context Management](./docs/file_context_management.md)

## License
GPL‑3 – feel free to fork, improve, and share.
