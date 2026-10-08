import os
from dataclasses import dataclass
from enum import Enum, auto
import prompt_toolkit
from rich.console import Console
from vex_shell.engine.agent import Agent
from vex_shell.engine.state import FileData


class CliOutput(Enum):
    EXIT    = auto()  # requrie app exit
    SKIP    = auto()  # require next prompt
    RENDER  = auto()

@dataclass
class CliResult:
    result: CliOutput
    content: str = ""
    title: str = ""

def _get_state_str(b: bool):
    return "enabled" if b else "disabled"

class VoiceModeError(Exception):
    def __init__(self,message:str):
        message = f"\nError details: {message}"
        super().__init__(
            "Cannot connect to v2t daemon.\n"
            "Please make sure 'v2t --daemon' is running in the background.\n\n"
            "Docs: https://codeberg.org/Enji/v2t"
            +message
        )


async def voice_mode(console:Console,prompt_session:prompt_toolkit.PromptSession) -> str:
    from multiprocessing.connection import Client
    import msgspec
    
    def send_msgspec(conn,data):
        conn.send_bytes(msgspec.json.encode(data))
    
    if os.name == 'nt':
        addr,family = r'\\.\pipe\v2t_pipe', 'AF_PIPE'
    else:
        addr,family = '/tmp/v2t.sock', 'AF_UNIX'

    if not os.path.exists(addr):
        raise VoiceModeError(f'file descriptor not exists {addr}')

    with Client(addr,family) as conn:
        send_msgspec(conn,{"function":"transcribe_micro","mode":"pipe"})
        resp = msgspec.json.decode(conn.recv_bytes())
    
        if resp.get('msg') != "READY":
            raise VoiceModeError(f"start recording, {resp.get('err')}")
    
        with console.capture() as cap:
            console.print("[vex.prompt]Press Enter to stop recording... [/vex.prompt]",end="")
            prompt_msg = prompt_toolkit.ANSI(cap.get().strip("\r\n"))
            await prompt_session.prompt_async(prompt_msg)
    
            console.file.write("\x1b[1A\x1b[2K" * 2)
            console.file.flush()
    
            send_msgspec(conn,{"msg":"stop"})
            resp = msgspec.json.decode(conn.recv_bytes())
            return resp.get('msg','')
    

async def cli_command(
    cmd: str,
    agent: Agent,
    *,
    console:Console,
    prompt_session:prompt_toolkit.PromptSession
) -> CliResult:
    if cmd == "/q":
        return CliResult(CliOutput.EXIT)
    if cmd == "/stat":
        from vex_shell.engine.helpers import count_tokens
        from vex_shell.utils.file_access import file_access_control

        use_mcp = agent.settings.chat["use_mcp"]
        token_usage = agent.token_usage
        model_name = agent.settings.model["name"]
        # Yes it's crutches
        autosync_cwd_tree = _get_state_str(
            agent.settings.chat.get("autosync_cwd_tree", False)
        )
        cache_on_write = _get_state_str(
            agent.settings.chat.get("cache_on_write", False)
        )

        mcp_state = "enabled" if use_mcp == True else "disabled"
        left_padding = 20
        env_block = file_access_control.build_environment_context()
        content = (
            f"{'Input:':<{left_padding}}{token_usage.tok_in} | "
            f"Output: {token_usage.tok_out} | "
            f"Total: {token_usage.tok_total}\n"
            f"{'Model:':<{left_padding}}{model_name}\n"
            f"{'MCP:':<{left_padding}}{mcp_state}\n"
            f"{'CWD auto tree:':<{left_padding}}{autosync_cwd_tree}\n"
            f"{'Cache on Write:':<{left_padding}}{cache_on_write}\n\n"
            +env_block+"\n"
        )

        state = await agent.get_state()
        loaded: dict[str, FileData] = state.values.get("loaded_files", {})
        cwd_tree = state.values.get("cwd_tree", "")

        cached = list(loaded.keys())
        content += "\n[vex.prompt]ActiveContext[/vex.prompt]\n"
        total_tokens = 0

        LABEL_W = 26
        TOK_W = 8

        if loaded:
            file_tokens   = count_tokens(''.join([v['content'] for k, v in loaded.items()]))
            total_tokens += file_tokens

            label = f"Files Context ({len(loaded)} files)"
            tok_str  = f"~{file_tokens:,}"
            content += f"< {label:<{LABEL_W}} {tok_str:>{TOK_W}} tokens >\n"

        if cwd_tree:
            tree_tokens = count_tokens(cwd_tree)
            total_tokens += tree_tokens

            tok_str  = f"~{tree_tokens:,}"
            content += f"< {'CwdTree':<{LABEL_W}} {tok_str:>{TOK_W}} tokens >\n"

        content += f"\nTotal Context: ~{total_tokens:,} tokens"
        return CliResult(CliOutput.SKIP, content, "Usage Metrics")

    if cmd == "/env":
        return CliResult(CliOutput.SKIP,
            f"{'Current workspace directory: ':<30}{agent.settings.config_path}\n"+
            f"{'Current env path: ':<30}{agent.settings.env_path}",
            "Env Info"
        )

    if cmd == "/help":
        content = (
            "██╗   ██╗███████╗██╗  ██╗\n"
            "██║   ██║██╔════╝╚██╗██╔╝\n"
            "██║   ██║█████╗   ╚███╔╝ \n"
            "╚██╗ ██╔╝██╔══╝   ██╔██╗ \n"
            " ╚████╔╝ ███████╗██╔╝ ██╗\n"
            "  ╚═══╝  ╚══════╝╚═╝  ╚═╝\n"
            "- - - - - - - - - - - - -\n\n"
            "VEX - lean CLI agentic control system\n\n"
            "AVAILABLE COMMANDS:\n"
            "  /q    - Quit session\n"
            "  /help - Show help menu\n"
            "  /stat - Show token usage\n"
            "  /env  - Show current place of .env file\n"
            "  /cached - Shows all cached files\n"
            "  /read   - Read files in cache by pattern\n"
            "  /del    - Delete files from cache by pattern\n"
            "  /voice -  Voice input mode, works with v2t integration only, check readme for more details\n"
        )
        return CliResult(CliOutput.SKIP,content,"Help")

    if cmd == "/cached":
        state = await agent.get_state()
        loaded = state.values.get("loaded_files", {})
        cached = list(loaded.keys())

        if not cached:
            content = "No files are currently cached in the active working context."
        else:
            content = "Cached files:\n" + "\n".join(f"- {p}" for p in cached)
        return CliResult(CliOutput.SKIP,content, "Cached Files")

    if cmd == "/voice":
        try:
            text = await voice_mode(console,prompt_session)
            return CliResult(CliOutput.RENDER,text)
        except VoiceModeError as e:
            return CliResult(CliOutput.SKIP,str(e))

    if cmd.startswith("/read"):
        pattern = cmd.split("/read ")[-1].strip()

        msgs = await agent.read_files(pattern)
        return CliResult(CliOutput.SKIP,"\n".join(msgs), f"Manual Read {pattern}")

    if cmd.startswith("/del "):
        pattern = cmd.split("/del ")[-1].strip()

        msgs = await agent.purge_files(pattern)
        return CliResult(CliOutput.SKIP,"\n".join(msgs), f"Manual Cache Clear {pattern}")

    # Feedback for unrecognized slash commands
    if cmd.startswith("/"):
        return CliResult(CliOutput.SKIP,
            f"[bold red]Unknown command:[/bold red] {cmd}", "Error")
