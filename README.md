# VEX SHELL


<pre >
██╗   ██╗███████╗██╗  ██╗
██║   ██║██╔════╝╚██╗██╔╝
██║   ██║█████╗   ╚███╔╝ 
╚██╗ ██╔╝██╔══╝   ██╔██╗ 
 ╚████╔╝ ███████╗██╔╝ ██╗
  ╚═══╝  ╚══════╝╚═╝  ╚═╝
</pre>

VEX is a **terminal‑first AI agent** (and *open source async agentic runtime*) that keeps your workspace continuously in sync with your LLM session using Active Working Context.

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


## Quick Start

### As Tool
```bash
# Install directly from the repository (no manual clone needed)
uv tool install "git+https://codeberg.org/Enji/vex.git"

# Initialize global config folder ~/.vex
vex

# Initialize a local workspace in the current directory
vex --init

# Set your API key (required for OpenRouter, nanoGPT or other providers)
#   Global: edit ~/.vex/.env
#   Local : edit .vex/.env
# Example content:
#   VEX_API_KEY="your‑api‑key‑here"

# Start an interactive session (uses the local .vex if present, otherwise the global one)
vex
```


### As Python Library

```bash
uv add git+https://codeberg.org/Enji/vex.git
```

```python
from vex_shell.engine.core import build_graph, get_tools
from vex_shell.engine.agent import Agent
from vex_shell.utils.config import Settings
from vex_shell.utils.file_access import file_access_control
from vex_shell.engine import events

import asyncio

async def main():
    # file access control reconfigured inside settings
    settings = Settings() # default settings for agent from .vex/CONFIG.toml
    
    # gather tools and mcp_manager ( control foreign tools )
    tools,mcp_manager = await get_tools(settings)

    # build graph for an Agent
    graph = build_graph(settings,tools)
    agent = await Agent.create(graph,"session-name",settings,mcp_manager)
    
    # We are ready to start
    stream = agent.run_step("read ./main.py and print here")
    print(f'used key from {agent.settings.env_path}')
    async for ev in stream:
        if isinstance(ev,events.TextFinish): # prints ready message
            print(ev.text)
        elif isinstance(ev,events.ToolStart):
            print(f'[start tool: {ev.tool_name} ]',end='',flush=True)
    
    print('total token usage: '+str(agent.token_usage.tok_total))
    await agent.close()

if __name__ == "__main__":
    asyncio.run(main())

```

Full agent functionality out of the box!!

## Security Note

> [!IMPORTANT] 
> File-access permissions apply to VEX’s built-in file tools only. They do not restrict MCP tools or commands configured under check_command and observe_command. \
> These commands execute in the working directory; configure only trusted MCP servers and commands.

## Example Workflow
1. `read_files path/to/module.py` – caches the file in the active context.
2. Ask the agent: “Refactor `module.py` to use async I/O.”
3. VEX injects the cached file into the prompt, the LLM returns the refactored code and writes back to  `module.py` with  `write_file` tool. 

## Extending VEX
- **Custom Tools**: Add standard LangChain tools inside src/vex_shell/tools/tools.py.
- **MCP Servers**: Configure external Model Context Protocol endpoints inside .vex/mcp_config.json.
- **UI Themes**: Define custom terminal color schemes inside src/vex_cli/colors.py.


## CLI Flags
 
| Flag | Description |
|------|-------------|
| `-i`, `--init` | Initialise a new `.vex` workspace (creates folder and template files). |
| `-s`, `--session <name>` | Choose a session identifier; defaults to `default`. |
| `-ls`, `--list-sessions` | List all saved session IDs stored in the SQLite checkpoint database. |
| `-lt`, `--list-themes`   | List available color themes. |
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
| `/voice` | Voice input integration, works only with [v2t](https://codeberg.org/Enji/v2t) app in daemon mode. |
| `/q` | Quit the current VEX session. |


## **Metrics (25.10.2026)**

- **Footprint**
```
---------------------
Module    LOC
VEX_SHELL 1183
VEX_CLI   519
TOTAL     1702
---------------------
```
- **Start time:** ~2.12s
- **utility functions (-ls/--help):** ~400ms

## Additional Documentation
- [Agentic Awareness](./docs/vex_agentic_awareness.md)
- [Architecture Deep Dive: Startup Time & Import Optimization](./docs/vex_startup_time_optimization.md)

## Enhancement Proposals (EPs)
- 01 [DONE] On-demand `write_file` appending, remove if write access denied.
- 02 [DONE] On-The-Fly RW permission update (in CONFIG.toml)


- 03 [Maybe] Add manual RAG-DB document insert by wildcard pattern with `/index <path> <domain>`

Pros:
- more deterministic index system
Cons:
- interface overhead, requirement for direct MCP** **tools calling(but it's likely good improvements)
```py
res = await mcp_manager.call_tool("insert_doc",{
    "title":"Misra_talk_CppMeeting775955.pdf",
    "domain":"compilers",
    "path":"./sandbox/Misra_talk_CppMeeting775955.pdf"})
print(res)
```
*Example of usage `/index compiler/*.pdf compilers`*

## License
GPL‑3 – feel free to fork, improve, and share.
