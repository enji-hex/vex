import asyncio
from mcp.client.sse import sse_client
from mcp import ClientSession
from langchain_core.tools import BaseTool

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class MCPTool(BaseTool):
    server_url: str
    parameters: dict = {}

    @property
    def args(self) -> dict:
        """Exposes raw JSON schema properties directly to LangChain / LLM."""
        return self.parameters.get("properties", {})

    def _run(self, **kwargs) -> str:
        """Executes the remote MCP tool synchronously inside LangGraph."""

        async def _execute():
            url = (
                self.server_url
                if self.server_url.endswith("/")
                else f"{self.server_url}/"
            )
            async with streamable_http_client(url) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    res = await session.call_tool(self.name, kwargs)

                    # Extract pure text content from response
                    return "\n".join(
                        c.text
                        for c in res.content
                        if getattr(c, "type", None) == "text"
                    )

        return asyncio.run(_execute())

async def _fetch_tools(url) -> list[BaseTool]:
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            response = await session.list_tools()
            return [
                MCPTool(
                    name=t.name,
                        description=t.description or "",
                        parameters=t.input_schema,
                        server_url=url,
                    )
                    for t in response.tools ]

def load_mcp_tools(server_url: str) -> list[BaseTool]:
    """Fetches tools from any MCP server and returns them as LangChain BaseTools."""
    url = server_url if server_url.endswith("/") else f"{server_url}/"
    try:
        return asyncio.run(_fetch_tools(url))
    except Exception as e:
        print(f"⚠️ Failed to load MCP tools from {server_url}: {e}")
        return []

