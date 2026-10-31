from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, TypedDict
import json
from langchain_core.messages import AIMessage

if TYPE_CHECKING:
    from langchain.tools import BaseTool
    from langchain_core.runnables import RunnableConfig

    from vex_shell.utils.config import Settings

from vex_shell.utils.config import LOGGER
from vex_shell.utils.file_access import file_access_control
from vex_shell.utils.fs import sync_cwd_tree, sync_loaded_files
from .state import FileData, State

class ValidatorResponse(TypedDict):
    accepted:bool
    description:str

# LLM NODES
async def llm_call_node(
    state: State, config: RunnableConfig, settings: Settings, tools: list[BaseTool]
):
    """
    Handle errors
    - 429
    - Bad model
    - No tool support
    """
    from langchain.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from .helpers import (
        format_file_context,
        get_safe_window,
        normalize_tool_calls,
    )

    role = state.get("agent_role", "writer")
    tool_names = [e.name for e in tools]

    llm_cfg = settings.model
    max_llm_calls = int(llm_cfg.get("max_llm_calls", 3))
    if max_llm_calls == -1:
        final_call = False
    else:
        calls = state.get("llm_calls", 0) + 1
        final_call = calls >= max_llm_calls

    # sync all loaded files — returns FRESH dict with updated content
    old_files = state.get("loaded_files", {})
    new_files = sync_loaded_files(old_files)
    loaded_update: dict[str, FileData | None] = {p: d for p, d in new_files.items()}
    loaded_update.update({p: None for p in old_files.keys() - new_files.keys()})

    # !! Move to model scope
    cwd_tree = (
        sync_cwd_tree(state) if settings.chat.get("autosync_cwd_tree", False) else None
    )
    LOGGER.debug(f"CWD tree: {cwd_tree}")

    # handle sliding window
    window: int = llm_cfg.get("context_sliding_window", 10)
    recent = get_safe_window(state["messages"], window)

    # system prompt mutation
    if role == "validator":
        system_prompt = settings.system_prompt + (
            "\nYou are a strict validator. Review the input for correctness, flaws, and constraints. "
            'Respond ONLY with JSON follow schema {"accepted": bool, "description": "critique or approval"}'
        )
    else:
        system_prompt = settings.system_prompt
        if final_call:
            system_prompt += (
                "\nThis is your final response for this user turn. "
                "Do not call tools. Give the user the best answer you can "
                "based on the available information."
            )
    system_msg = SystemMessage(content=system_prompt)

    # Handle file_context — use FRESH snap, not stale state
    env_block = file_access_control.build_environment_context()
    context_blocks, image_paths = format_file_context(
        new_files,
        env_block,
        config.get("configurable", {}).get("use_vision", False),
        cwd_tree=cwd_tree,
    )

    if image_paths:
        for p in image_paths:
            loaded_update[p] = None
        LOGGER.debug(
            f"Purged {len(image_paths)} image(s) from loaded_files after injection"
        )

    ephemeral_context_msg = HumanMessage(content=context_blocks)
    payload_messages = [system_msg] + recent + [ephemeral_context_msg]

    # reasoning
    # https://openrouter.ai/docs/guides/best-practices/reasoning-tokens

    stream_chunk_timeout = llm_cfg.get("ollama", {}).get("stream_chunk_timeout", "0")
    llm = ChatOpenAI(
        openai_proxy=llm_cfg.get("proxy"),
        model=llm_cfg["name"],
        base_url=llm_cfg.get("llm_url", "http://localhost:11434/v1"),
        api_key=os.environ.get("VEX_API_KEY", "llama"),  # fallback for local model
        temperature=llm_cfg["temperature"],
        max_completion_tokens=llm_cfg.get("max_completion_tokens"),
        max_retries=int(llm_cfg["max_retries"]),
        streaming=True,
        stream_usage=True,
        stream_chunk_timeout=int(stream_chunk_timeout),
        extra_body=llm_cfg.get("extra_body"),
        reasoning=llm_cfg.get("reasoning")
    )
    LOGGER.debug(f'extra body {llm_cfg.get("extra_body",{})}')
    
    
    
    if role == "writer":
        model = llm if final_call else llm.bind_tools(tools)
        resp  = await model.ainvoke(payload_messages, config=config)
        LOGGER.debug(f'writer {str(resp)}')
        
        if final_call:
            resp.tool_calls = []
        else:
            resp = normalize_tool_calls(resp, tool_names)

        messages = [resp] # standard message
        
        # may be incorrect
        finish_reason = resp.additional_kwargs.get("finish_reason")
        if finish_reason == "length":
            LOGGER.warning(
                f'response was truncated by token limit {settings.model.get("max_completion_tokens")}, fallback'
            )
            resp.tool_calls = []
            warning_msg = SystemMessage(
                content="[SYSTEM: Your previous response was truncated due to token limits. "
                "Please continue exactly where you left off in your next response.]"
            )
            messages = [resp, warning_msg]
        
        if resp.tool_calls:
            route,next_role = "tool_node","writer"
        else:
            if settings.chat.get("duo") == True:
                route,next_role = "llm_call","validator"
            else:
                route,next_role = "end","writer"
    
    else: # curr role validator
        model = llm.with_structured_output(ValidatorResponse,include_raw=True)
        resp_out = await model.ainvoke(payload_messages,config=config)

        LOGGER.info(str(resp_out))

        try:
            data = resp_out['parsed']
            
            accepted    = data.get("accepted", False)
            description = data.get("description", "No description provided.")

            if accepted:
                route,next_role = "end","writer"
            else:
                route,next_role = "llm_call","writer"
            
            status      = "OK" if accepted else "FAIL"
            msg         = f"[{status}] {description}"
            
            LOGGER.debug('validator '+msg)
            messages = [AIMessage(content=msg)]

        except Exception as err:
            LOGGER.warning(f"error parse validator response {err}")
            route, next_role = "llm_call", "writer"
            messages = [AIMessage(content=f"[FAIL] Error parsing validator response: {err}")]

    return {
        "messages": messages,
        "llm_calls": calls,
        "loaded_files": loaded_update,
        "cwd_tree": cwd_tree,
        "route": route,
        "agent_role": next_role
    }


def should_verify(state: State, settings: Settings):
    from langchain_core.messages import ToolMessage

    last_msg = state["messages"][-1]

    need_verify = settings.verification.get(
        "check_command"
    ) or settings.verification.get("observe_command")

    if (
        isinstance(last_msg, ToolMessage)
        and last_msg.name == "write_file"
        and need_verify
    ):
        LOGGER.info("should verify , last mesage write")
        return "verification_node"
    return "llm_call"


async def _exec(cmd: str) -> tuple:
    """Ret code, stdout, stderr"""
    proc = await asyncio.subprocess.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=file_access_control.cwd,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return (
        proc.returncode,
        stdout_bytes.decode("utf-8", errors="replace").strip(),
        stderr_bytes.decode("utf-8", errors="replace").strip(),
    )


async def verification_node(state: State, settings: Settings):
    from langchain_core.messages import HumanMessage

    check_cmd = settings.verification.get("check_command")
    observe_cmd = settings.verification.get("observe_command")

    content = ""
    if check_cmd:
        retcode, stdout, stderr = await _exec(check_cmd)
        LOGGER.info(f"VERIFY RES {stdout} {stderr}")
        content += f"Check result (`{check_cmd}`), return code {retcode}\n{(stdout or stderr)}\n"

    if observe_cmd:
        retcode, stdout, stderr = await _exec(observe_cmd)
        LOGGER.info(f"OBSERVE RES {stdout} {stderr}")
        content += f"Observer output (`{observe_cmd}`), return code {retcode}\n{(stdout or stderr)}\n"

    return {"messages": [HumanMessage(content=content)]}


def should_continue(state: State):
    END = "__end__"
    from langchain_core.messages import AIMessage

    messages = state.get("messages", [])
    if not messages:
        return END

    last = messages[-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tool_node"
    return END
