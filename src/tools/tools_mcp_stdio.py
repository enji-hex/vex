import asyncio
from contextlib import AsyncExitStack
from typing import Any
from langchain_core.tools import BaseTool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import json,os
from utils.config import LOGGER


# REWRITE THIS SHIT IN PROPER WAY SOME TIME

def clean_mcp_schema(schema: dict) -> dict:
    """Removes meta fields like $schema that break LLM function specs."""
    if not isinstance(schema, dict):
        return {}
    return {k: v for k, v in schema.items() if not k.startswith("$")}

class RawJSONSchema:
    """Bypasses Pydantic schema generation by returning raw MCP JSON schema directly."""

    def __init__(self, schema: dict):
        self._schema = schema

    def model_json_schema(self, *args, **kwargs) -> dict:
        return self._schema

    def schema(self, *args, **kwargs) -> dict:
        return self._schema
    
class StdioMCPTool(BaseTool):
    session: Any
    parameters: dict
    loop: asyncio.AbstractEventLoop

    args_schema: type[Any] | None = None
    model_config = {"arbitrary_types_allowed": True}

    @property
    def args(self) -> dict:
        cleaned = clean_mcp_schema(self.parameters)
        return cleaned.get("properties", {})
    
    async def _arun(self, **kwargs: Any) -> Any:
        # 1. Unpack double-nested kwargs if the LLM wraps them
        if len(kwargs) == 1 and "kwargs" in kwargs and isinstance(kwargs["kwargs"], dict):
            kwargs = kwargs["kwargs"]

        schema_props = self.parameters.get("properties", {})
        required_params = self.parameters.get("required", [])

        # 2. Dynamic Auto-Mapper: If LLM sent an invalid key, remap it to a required schema parameter
        valid_kwargs = {}
        invalid_args = []

        for k, v in kwargs.items():
            if k in schema_props:
                valid_kwargs[k] = v
            else:
                invalid_args.append(v)

        # Fill missing required parameters with orphan values passed by the LLM
        missing_required = [req for req in required_params if req not in valid_kwargs]
        for req_key, orphan_val in zip(missing_required, invalid_args):
            valid_kwargs[req_key] = orphan_val

        # Pass clean, schema-compliant kwargs to the MCP server
        res = await self.session.call_tool(self.name, valid_kwargs)
        
        if not res.content:
            return "Tool executed successfully with no output."

        return "\n".join(
            c.text for c in res.content if getattr(c, "type", None) == "text"
        )

    def _run(self, **kwargs) -> str:
        return self.loop.run_until_complete(self._arun(**kwargs))


class LocalMCPManager:
    """Manages background subprocess lifetimes and fetches tools into your custom StdioMCPTool format."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.exit_stack = AsyncExitStack()

    async def load_mcp_tools(
        self, command: str, args: list[str], env: dict = None
    ) -> list[BaseTool]:
        
        """Spawns stdio subprocess, initializes session, and returns custom MCPTool instances."""
        server_params = StdioServerParameters(command=command, args=args, env=env)

        read, write = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        session = await self.exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        response = await session.list_tools()

        tools = []

        for t in response.tools:
            schema = (
                t.input_schema
                if isinstance(t.input_schema, dict)
                else t.input_schema.model_dump()
            )
            schema = clean_mcp_schema(schema)
            LOGGER.info(str(schema))

            tools.append(
                StdioMCPTool(
                    name=t.name,
                    description=t.description or "",
                    parameters=schema,
                    session=session,
                    loop=self.loop
                )
            )
        return tools

    def close(self):
        """Terminates all running stdio subprocesses on VEX exit."""
        if self.loop and not self.loop.is_closed():
            self.loop.run_until_complete(self.exit_stack.aclose())
        

def load_mcp_tools():
    mcp_manager = LocalMCPManager()

    conf_path = os.path.join(os.getcwd(), ".vex/mcp_config.json")
    if not os.path.exists(conf_path):
        raise Exception("mcp_config.json not found in .vex folder")
    
    with open(conf_path,'r',encoding='utf-8') as f:
        config:dict = json.load(f)
    
    tools = []
    servers = config.get('mcpServers',{})

    for name,cfg in servers.items():
        cmd = cfg.get('command')
        if not cmd: continue

        args = cfg.get("args",[])
        env = os.environ.copy()
        if 'env' in cfg:
            env.update(cfg['env'])

        try:
            server_tools = mcp_manager.loop.run_until_complete(
                mcp_manager.load_mcp_tools(command=cmd, args=args, env=env)
            )
            tools.extend(server_tools)
            LOGGER.info(f"MCP tool loaded {name}")
        except Exception as err:
            LOGGER.error(f'Failed to load MCP tool {name} {err}')
    
    return tools,mcp_manager




