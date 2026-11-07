from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, Literal, TypedDict

from langchain_core.messages import AIMessage, SystemMessage

if TYPE_CHECKING:
    from langchain.tools import BaseTool
    from langchain_core.runnables import RunnableConfig

    from vex_shell.utils.config import Settings

from vex_shell.utils.config import LOGGER
from vex_shell.utils.file_access import file_access_control
from vex_shell.utils.fs import sync_cwd_tree, sync_loaded_files
from vex_shell.engine.schema_generator import get_schema

from .state import FileData, State

class ValidatorResponse(TypedDict):
    accepted: Annotated[bool, "Is agent response accepted"]
    content: Annotated[str, "The reason of decision"]

def newAIMessage(text,role,usage,tool_calls=None):
    return AIMessage(
        content=text,
        response_metadata={"role":role},
        usage_metadata=usage,
        tool_calls=tool_calls or [])


def build_llm(settings: Settings):
    from langchain_openai import ChatOpenAI
    import os

    llm_cfg = settings.model
    stream_chunk_timeout = llm_cfg.get("ollama", {}).get("stream_chunk_timeout", "0")
    return ChatOpenAI(
        openai_proxy=llm_cfg.get("proxy"),
        model=llm_cfg["name"],
        base_url=llm_cfg.get("llm_url", "http://localhost:11434/v1"),
        api_key=os.environ.get("VEX_API_KEY", "llama"),
        temperature=llm_cfg["temperature"],
        max_completion_tokens=llm_cfg.get("max_completion_tokens"),
        max_retries=int(llm_cfg["max_retries"]),
        streaming=True,
        stream_usage=True,
        stream_chunk_timeout=int(stream_chunk_timeout),
        extra_body=llm_cfg.get("extra_body"),
        reasoning=llm_cfg.get("reasoning"),
    )

# LLM NODES

# LLM NODES
async def writer_node(
    state: State, config: RunnableConfig, settings: Settings, tools: list[BaseTool]
):
    from langchain.messages import HumanMessage, SystemMessage
    from .helpers import (
        format_file_context,
        get_safe_window,
        normalize_tool_calls,
    )

    role = "writer"
    tool_names = [e.name for e in tools]

    max_llm_calls = int(settings.model.get("max_llm_calls", 3))
    calls = state.get("llm_calls", 0) + 1
    final_call = max_llm_calls != -1 and calls >= max_llm_calls

    # sync all loaded files — returns FRESH dict with updated content
    old_files = state.get("loaded_files", {})
    new_files = sync_loaded_files(old_files)
    loaded_update: dict[str, FileData | None] = {p: d for p, d in new_files.items()}
    loaded_update.update({p: None for p in old_files.keys() - new_files.keys()})
    cwd_tree = (
        sync_cwd_tree(state) if settings.chat.get("autosync_cwd_tree", False) else None
    )

    window = int(settings.model.get("context_sliding_window", 10))
    recent = get_safe_window(state["messages"], window)
    env_block = file_access_control.build_environment_context()
    context_blocks, image_paths = format_file_context(
        new_files,
        env_block,
        config.get("configurable", {}).get("use_vision", False),
        cwd_tree=cwd_tree,
    )

    for p in image_paths:
        loaded_update[p] = None

    # reasoning
    # https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
    llm = build_llm(settings)
    system_prompt = settings.system_prompt
    if final_call:
        LOGGER.warning(f"final call {calls}")
        system_prompt += (
            "\nThis is your final response for this user turn. "
            "Do not call tools. Give the user the best answer you can "
            "based on the available information."
        )

    # full active context
    ephemeral_context_msg = HumanMessage(content=context_blocks)
    payload_messages = (
        [SystemMessage(content=system_prompt)] + recent + [ephemeral_context_msg]
    )
    model = llm if final_call else llm.bind_tools(tools)
    resp = await model.ainvoke(payload_messages, config=config)
    usage = getattr(resp, "usage_metadata", None)

    LOGGER.debug(f"writer {resp!s}")

    if final_call:
        resp.tool_calls = []
    else:
        resp = normalize_tool_calls(resp, tool_names)

    # standard message
    messages = [newAIMessage(resp.content, role, usage,resp.tool_calls)]
    # check it
    finish_reason = (
        resp.response_metadata.get("finish_reason")
        or resp.additional_kwargs.get("finish_reason")
        )

    text_exists = isinstance(resp.content,list) and len(resp.content) > 0 and resp.content[0].get("text") is not None
    LOGGER.debug(f'text exists {text_exists}')
    # use later to eliminate empty responses
    truncated = finish_reason == "length"
    if truncated:
        LOGGER.warning(
            f'response was truncated by token limit {settings.model.get("max_completion_tokens")}, fallback'
        )
        resp.tool_calls = []
        warning_msg = SystemMessage(
            content="[SYSTEM: Your previous response was truncated due to token limits. "
            "Please continue exactly where you left off in your next response.]"
        )
        messages = [newAIMessage(resp.content, role, usage), warning_msg]

    # Check if response contains valid text
    has_text = False
    if isinstance(resp.content, str):
        has_text = bool(resp.content.strip())
    elif isinstance(resp.content, list):
        has_text = any(
            isinstance(block, dict) and block.get("type") == "text" and block.get("text")
            for block in resp.content
        )

    # Routing logic
    if truncated:
        next_node = "writer"
    elif resp.tool_calls:
        next_node = "tool_node"
    elif not has_text and not final_call:
        # Writer provided no text and called no tools -> route back to retry
        next_node = "writer"
    elif settings.chat.get("duo") and not final_call:
        next_node = "validator"
    else:
        next_node = "end" 
    
    return {
        "messages": messages,
        "llm_calls": calls,
        "loaded_files": loaded_update,
        "cwd_tree": cwd_tree,
        "next": next_node,
        "agent_role": "writer",
    }


async def validator_node(
    state: State, config: RunnableConfig, settings: Settings, tools: list[BaseTool]
):
    role = "validator"
    calls = state.get("llm_calls", 0) + 1

    llm = build_llm(settings)
    base_prompt = settings.chat.get("validator_system_prompt", "You are a validator.")
    system_prompt = f"{base_prompt}\n\nRespond ONLY with JSON matching this schema:{get_schema(ValidatorResponse)}"
    payload_messages = [SystemMessage(content=system_prompt)] + state["messages"][-1:]

    model = llm.with_structured_output(ValidatorResponse, include_raw=True)
    resp_out = await model.ainvoke(payload_messages, config=config)

    accepted = False
    usage = None
    content = "No content provided."
    try:
        data = resp_out["parsed"]
        usage = getattr(resp_out["raw"], "usage_metadata", None)
        accepted = data.get("accepted", False)
        content = data.get("content", "No content provided.")
        messages = [newAIMessage(content, role, usage)]
    except Exception as err:
        LOGGER.error(f"error parse validator response {err}")
        messages = [
            newAIMessage(f"[FAIL] Error parsing validator response: {err}", role, usage)
        ]

    next_node = "writer" if not accepted else "end"
    return {
        "messages": messages,
        "llm_calls": calls,
        "next": next_node,
        "agent_role": "validator",
    }

def should_verify(state: State, settings: Settings):
    """deprcated"""
    from langchain_core.messages import ToolMessage
    last_msg = state["messages"][-1]

    need_verify = settings.verification.get("check_command") \
        or settings.verification.get("observe_command")

    if (isinstance(last_msg, ToolMessage)
        and last_msg.name == "write_file"
        and need_verify):
        LOGGER.info("should verify , last mesage write")
        return "verification_node"

    return "writer"


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

    duo = settings.chat.get("duo",False)
    next_role = "validator" if duo else "writer"

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

    return {
        "messages": [HumanMessage(content=content)],
        "next": next_role
        }

def should_continue(state: State) -> Literal["tool_node","end"]:
    END = "__end__"
    from langchain_core.messages import AIMessage

    LOGGER.info(str())

    messages = state.get("messages", [])
    if not messages:
        return "end"

    last = messages[-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        LOGGER.info('route to tool node')
        return "tool_node"
    return "end"
