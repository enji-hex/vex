import asyncio
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Tuple
from langchain_core.tools import BaseTool
from mcp import ClientSession, StdioServerParameters

from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
import time
import json, os
from pydantic import BaseModel, Field, create_model
from vex_shell.utils.config import LOGGER

# JSON mcp types to python types
JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}

def sanitize_arguments(raw_args: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(raw_args, BaseModel):
        raw_args = raw_args.model_dump(exclude_none=True)

    if isinstance(raw_args,dict):
        return {
            k: sanitize_arguments(v)
            for k,v in raw_args.items()
            if v is not None
        }
    
    if isinstance(raw_args,list):
        return [sanitize_arguments(v) for v in raw_args if v is not None]
    return raw_args


def create_pydantic_schema(tool_name: str, json_schema: dict) -> type[BaseModel]:
    properties = json_schema.get("properties", {})
    required_fields = set(json_schema.get("required", []))

    fields: dict[str,tuple[type,Any]] = {}
    for field_name, field_info in properties.items():
        field_type = field_info.get("type","any")

        is_required = field_name in required_fields
        default_val = ... if is_required else field_info.get("default", None)

        fields[field_name] = (
            JSON_TYPE_MAP.get(field_type,Any),
            Field(default=default_val, description=field_info.get("description", "")),
        )

    # Properly constructs __annotations__ so LangChain exports the full schema to Claude
    return create_model(f"{tool_name}Schema", **fields)


class MCPTool(BaseTool):
    """Langchain tool wrapper for MCP sessions """

    session: Any
    args_schema: type[Any] | None = None
    model_config = {"arbitrary_types_allowed": True}

    def _run(self):
        raise NotImplementedError("MCPTool support only _arun")

    async def _arun(self, **kwargs: Any) -> Any:
        try:
            clean_args = sanitize_arguments(kwargs)
            res = await self.session.call_tool(self.name, clean_args)
            if not res.content:
                return "Tool executed successfully with no output."

            output = []
            for chunk in res.content:
                # append text output
                if getattr(chunk,"type",None) == "text":
                    output.append(chunk.text)
                # append json output
                elif hasattr(chunk,"model_dump"):
                    output.append(json.dumps(chunk.model_dump()))
                # raw fallback
                else:
                    output.append(str(chunk))
            
            return "\n".join(output)
        
        except Exception as err:
            LOGGER.error(f"Error executing tool '{self.name}': {err}")
            return f"Error executing tool '{self.name}': {err}"

class MCPManager:
    """Manages background subprocess lifetimes and fetches tools into your custom MCPTool format."""

    def __init__(self):
        self.exit_stack = AsyncExitStack()

    async def _connect_and_load(self,transport) -> list[BaseTool]:
        """Binds transport streams to ClientSession and builds MCPTools"""

        read, write = await self.exit_stack.enter_async_context(transport)
        session = await self.exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        response = await session.list_tools()
        tools = []

        for t in response.tools:
            raw_schema = (
                t.input_schema
                if isinstance(t.input_schema, dict)
                else t.input_schema.model_dump()
            )
            clean_schema = create_pydantic_schema(t.name, raw_schema)

            LOGGER.info(str(clean_schema))
            tools.append(
                MCPTool(
                    name=t.name,
                    description=t.description or f"MCP tool {t.name}",
                    session=session,
                    args_schema=clean_schema,
                )
            )
        return tools

    async def load_server(self, name: str, cfg: dict) -> list[BaseTool]:
        if "url" in cfg:
            url:str = cfg['url']
            if url.endswith("/sse") or cfg.get("transport") == "sse":
                return await self._connect_and_load(sse_client(url))
            
            return await self._connect_and_load(streamable_http_client(url))
        
        elif "command" in cfg:
            env = {**os.environ.copy(),**cfg.get("env",{})}
            params = StdioServerParameters(
                command=cfg["command"], args=cfg.get("args", []), env=env
            )
            return await self._connect_and_load(stdio_client(params))
        else:
            raise ValueError(f"Invalid config for '{name}'!!")

    async def aclose(self):
        """Terminates all running stdio subprocesses on VEX exit."""
        try:
            await self.exit_stack.aclose()
        except Exception as e:
            LOGGER.warning(f"Error during MCP cleanup {e}")


async def load_mcp_tools() -> Tuple[List[BaseTool],MCPManager]:
    mcp_manager = MCPManager()
    conf_path  = os.path.join(os.getcwd(), ".vex/mcp_config.json")
    
    if not os.path.exists(conf_path):
        LOGGER.warning("mcp_config.json not found in .vex folder")
        return [], mcp_manager

    with open(conf_path, "r", encoding="utf-8") as f:
        config: dict = json.load(f)

    tools = []
    for name, cfg in config.get("mcpServers", {}).items():
        try:
            start_time = time.perf_counter()
            server_tools = await mcp_manager.load_server(name, cfg)
            tools.extend(server_tools)
            
            end_time = time.perf_counter()
            LOGGER.info(f"MCP tool loaded {name} in {end_time - start_time} secs")
        except Exception as err:
            LOGGER.error(f"Failed to load MCP tool {name} {err}")

    return tools, mcp_manager
