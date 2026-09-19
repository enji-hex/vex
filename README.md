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
- **State‑graph agent** - Powered by async SQLite checkpointing; sessions survive crashes and can be resumed anytime.
- **Active Working Context** – Automatically injects current file states and directory trees into the prompt, cutting context overhead.
- **Automatic cache purge** – Syncs loaded files on every LLM turn and purges references to deleted files.
- **Token usage tracking** – `/stat` shows input, output, and total token counts for the current session.
- **Sandboxed file access** – Strict read/write path validation prevents directory traversal attacks.
- **Dynamic MCP Tool Loading** – Plug external tools into the runtime at launch via `.vex/mcp_config.json`.
- **CWD Tree Integration** - Optional feature that injects the current working directory hierarchy directly into the active prompt.
- **Cache-on-Write** - Optional feature that automatically adds files generated or modified by the LLM into the FileContext.
- **Token Tracking & UI Themes** – Built-in /stat metrics and customizable Rich terminal themes (Fallout, Cyberpunk, EVA-03).


## TL;DR (News)
- Added `llama.cpp` support (compatible with any Hugging Face GGUF model).
- Fixed `extra_body` argument injection for the Ollama provider.


## Quick Start

### As Tool
```bash
# Install directly from the repository (no manual clone needed)
uv tool install "git+https://codeberg.org/Enji/vex.git#egg=vex_shell[cli]"

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

### Provider Configuration Notes

> Both **Ollama** and **llama.cpp** uses ollama as provider, cause of identical `ChatOpenAI` interface.

**Ollama**
- `custom_url` is optional (defaults to `http://localhost:11434/v1`).

**llama.cpp**
- Set port to `11434` or update `custom_url` in `CONFIG.toml`.
- Set `stream_chunk_timeout=0` to disable timeouts and prevent request errors.


### As Python Library

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

**Note**: The ReasoningDelta event is currently supported only when using the OpenRouter provider. Refer to [events.py](./src/vex_shell/ui/events.py) for the complete event schema.


## Example Workflow
1. `read_files path/to/module.py` – caches the file in the active context.
2. Ask the agent: “Refactor `module.py` to use async I/O.”
3. VEX injects the cached file into the prompt, the LLM returns the refactored code and writes back to  `module.py` with  `write_file` tool. 

## Extending VEX
- **Custom Tools**: Add standard LangChain tools inside src/vex_shell/engine/tools.py.
- **MCP Servers**: Configure external Model Context Protocol endpoints inside .vex/mcp_config.json.
- **UI Themes**: Define custom terminal color schemes inside src/vex_shell/ui/colors.py.

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
| `/read <glob>` | Load files into active context matching a glob pattern (e.g., /read ./src/**). |
| `/del <glob>` | Purge files from active context matching a glob pattern (e.g., /del ./src/engine/**.py). |
| `/stat` | Display token usage statistics (input, output, total) and the model being used. |
| `/env` | Reveal the path of the loaded environment configuration file (`.env`). |
| `/help` | Show the help screen with available slash commands. |
| `/q` | Quit the current VEX session. |

## Additional Documentation
- [Agentic Awareness](./docs/agentic_awareness.md)

## License
GPL‑3 – feel free to fork, improve, and share.
