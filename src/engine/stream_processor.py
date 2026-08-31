import asyncio
from typing import (
    AsyncIterator,
    List,
    Optional,
)
import warnings
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import StateGraph,CompiledStateGraph
from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.prebuilt import ToolCallTransformer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite

from utils.file_access import file_access_control

from mcp_tools.tools_mcp import MCPManager
from utils.config import LOGGER,Settings
from ui import prompt
from ui.events import *
from tools.tools import _glob_tool,_read_files

warnings.filterwarnings("ignore", message=".*v3 streaming protocol.*")


async def process(stream) -> AsyncIterator[AgentEvent]:
    async for event in stream:
        method = event.get("method")
        params = event.get("params", {})
        data = params.get("data", {})
        # LOGGER.debug(f"messages: {method} {data}")

        if method == "tools":
            LOGGER.debug(f"tools: {method} {data}")

            event_type = data.get("event")
            if event_type == "tool-started":
                raw_args = data.get("input")
                if isinstance(raw_args, dict):
                    args_str = ", ".join(f"{k}={v!r}" for k, v in raw_args.items())
                else:
                    args_str = str(raw_args or "")
                yield ToolStart(
                    data.get("tool_call_id"),
                    str(data.get("tool_name")),
                    args_str,
                )
            elif event_type == "tool-finished":
                yield ToolStop(data.get("tool_call_id"), str(data.get("output")))
            continue

        if method == "messages":
            if isinstance(data, (list, tuple)) and len(data) >= 2:
                msg_data, graph_meta = data[0], data[1]
            else:
                continue

            if not isinstance(msg_data, dict) or not isinstance(graph_meta, dict):
                continue
            event_type = msg_data.get("event")

            # message
            block = msg_data.get("fields") or msg_data.get("delta") or {}
            delta_type = block.get("type")

            if delta_type == "text-delta":
                text = block.get("text", "")
                if text:
                    yield TextDelta(text)
            elif delta_type in ("reasoning-delta", "reasoningch"):
                reasoning = (
                    block.get("reasoning")
                    or block.get("reasoning_content")
                    or block.get("text", "")
                )
                if reasoning:
                    yield ReasoningDelta(reasoning)

            if event_type == "message-finish" and "usage" in msg_data:
                usage = msg_data["usage"]
                yield TokenUsage(
                    tok_in=usage.get("input_tokens", 0),
                    tok_out=usage.get("output_tokens", 0),
                    tok_total=usage.get("total_tokens", 0),
                )

class Agent:
    def __init__(
        self,
        compiled_graph: CompiledStateGraph,
        session_id: str,
        settings: Settings,
        conn: aiosqlite.Connection,
        mcp_manager: Optional[MCPManager] = None,
    ) -> None:
        self.graph = compiled_graph
        self.settings = settings
        self.mcp_manager = mcp_manager
        self.conn = conn
        self.config: RunnableConfig = {
            "configurable": {
                "thread_id": session_id,
                "use_vision": settings.model.get("use_vision", False),
            }
        }
        self.token_usage = TokenUsage()

    @classmethod
    async def create(
        cls, # class instance
        graph:StateGraph,
        session_id:str,
        settings:Settings,
        mcp_manager:Optional[MCPManager] = None
    ):
        conn = await aiosqlite.connect(settings.db_path)
        checkpointer = AsyncSqliteSaver(conn)
        await checkpointer.setup()
        compiled_graph = graph.compile(checkpointer=checkpointer)

        return cls(compiled_graph,session_id,settings,conn,mcp_manager)

    
    async def get_state(self):
        return await self.graph.aget_state(self.config)
    
    async def read_files(self,pattern) -> List[str]:
        current_state = await self.get_state()
        state_values = current_state.values if current_state else {}

        files = _glob_tool([pattern])
        LOGGER.info(f'gloab found {str(files)} files')
        loaded,msgs = _read_files(files,self.config,state_values)

        await self.graph.aupdate_state(
            self.config,
            {"loaded_files":loaded},
            as_node="llm_call")
        LOGGER.info(f'manual caching, cached total {len(loaded)} files')
        return msgs
    

    async def restore_token_usage(self) -> TokenUsage:
        current_state = await self.get_state()

        # empty token usage
        if "messages" not in current_state.values:  
            return self.token_usage
        
        for m in current_state.values["messages"]:
            if hasattr(m, "usage_metadata"):
                try:
                    u = m.usage_metadata
                    self.token_usage.tok_in    += u.get("input_tokens", 0)
                    self.token_usage.tok_out   += u.get("output_tokens", 0)
                    self.token_usage.tok_total += u.get("total_tokens", 0)
                except Exception as err:
                    LOGGER.error(f'Error get token usage metrics, {err}')
        
        return self.token_usage
    
    async def restore_history(self) -> List[AnyMessage]:
        state = await self.get_state()
        messages:Optional[List[AnyMessage]] = state.values.get("messages")
        if not messages:
            return []
        
        recent_messages = []
        for m in messages:
            if m.type == "human":
                recent_messages.append(m)
            if m.type == "ai":

                if isinstance(m.content,str):
                    recent_messages.append(m)
                    LOGGER.info('restore history, msg str')
                elif isinstance(m.content, list) and \
                    any(isinstance(c, dict) \
                        and c.get("type") == "text" for c in m.content
                    ):
                    LOGGER.info('restore history, msg list')
                    recent_messages.append(m)

        return recent_messages


    async def run_step(self,user_input:str) -> AsyncIterator[AgentEvent]:
        stream = self.graph.astream_events(
            {"messages": [HumanMessage(content=user_input)]},
            config=self.config,
            version="v3",
            transformers=[ToolCallTransformer],
        )

        async for event in process(stream):
            if isinstance(event,TokenUsage):
                self.token_usage.tok_in += event.tok_in
                self.token_usage.tok_out += event.tok_out
                self.token_usage.tok_total += event.tok_total
                LOGGER.info(
                    f"token usage for message in:{event.tok_in} out:{event.tok_out} total:{event.tok_total}"
                )
            yield event
    
    async def close(self):
        await self.conn.close()
        if self.mcp_manager:
            await self.mcp_manager.aclose()
