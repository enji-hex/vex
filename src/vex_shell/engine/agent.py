import asyncio
from pathlib import Path
from typing import (
    AsyncIterator,
    List,
    Optional,
    Self,
)
import warnings
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import StateGraph,CompiledStateGraph
from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.prebuilt import ToolCallTransformer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite
from fnmatch import fnmatch

from vex_shell.utils.file_access import file_access_control
from vex_shell.mcp_tools.tools_mcp import MCPManager
from vex_shell.utils.config import LOGGER,Settings
from vex_shell.ui.events import *
from vex_shell.tools.tools import _glob_tool,_read_files
from vex_shell.engine.helpers import get_model_context_length

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
        max_context_window:int,
        mcp_manager: Optional[MCPManager] = None,
    ) -> None:
        self.graph = compiled_graph
        self.settings = settings
        self.mcp_manager = mcp_manager
        self.conn = conn
        self.settings.model['max_context_window'] = max_context_window
        self.config: RunnableConfig = {
            "configurable": {
                "thread_id": session_id,
                "use_vision": settings.model.get("use_vision", False),
                "cache_on_write":settings.chat.get('cache_on_write',False),
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
    ) -> Self:
        conn = await aiosqlite.connect(settings.db_path)
        checkpointer = AsyncSqliteSaver(conn)
        await checkpointer.setup()
        compiled_graph = graph.compile(checkpointer=checkpointer)

        _context_window = None
        if settings.model['provider'] == 'openrouter':
            _context_window = get_model_context_length(settings.model['name'])
        
        # gather only for open router models
        max_context_window = _context_window if _context_window else 128_000 


        agent =  cls(compiled_graph,session_id,settings,conn,max_context_window,mcp_manager)
        await agent.restore_token_usage()
        return agent

    
    async def get_state(self):
        return await self.graph.aget_state(self.config)
    
    async def get_sessions(self) -> List[str]:
        cusrsor = await self.conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
        )
        rows = await cusrsor.fetchall()
        ids = [r[0] for r in rows if r[0] is not None]
        return ids
    
    async def read_files(self,pattern:str) -> List[str]:
        current_state = await self.get_state()
        state_values = current_state.values if current_state else {}

        files = _glob_tool([pattern])
        LOGGER.info(f'glob found {str(files)} files')
        
        loaded,msgs = _read_files(files,self.config,state_values)
        update_payload:dict = {"loaded_files":loaded}

        if "messages" not in state_values:
            update_payload["messages"] = []

        await self.graph.aupdate_state(
            self.config,
            update_payload,
            as_node="llm_call")
        LOGGER.info(f'manual caching, cached total {len(loaded)} files')
        return msgs
    
    async def purge_files(self,pattern:str) -> List[str]:
        current_state = await self.get_state()
        state_values = current_state.values if current_state else {}
        cwd = Path(file_access_control.cwd)

        loaded = state_values.get("loaded_files",{})
        new_loaded = loaded.copy()

        normalized_patterns = [pattern]
        for p in _glob_tool([pattern]):
            try:
                rel_p = Path(p).relative_to(cwd).as_posix()
                normalized_patterns.append(rel_p)
            
            # if not relative ( like other drive path)
            except ValueError:
                normalized_patterns.append(p)
        
        msgs = []
        purge_payloads = {}
        for key in list(new_loaded.keys()):
            for p in normalized_patterns:
                if fnmatch(key,p) or key == p:
                    purge_payloads[key] = None
                    msgs.append(f"del from cache {key}")
                    break
        
        if purge_payloads:
            await self.graph.aupdate_state(
                self.config,
                {"loaded_files":purge_payloads},
                as_node="llm_call")
        
        LOGGER.info(f'manual caching, del total {len(loaded)} files')
        return msgs


    async def restore_token_usage(self) -> TokenUsage:
        """Restore token usage for message history"""
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
        stream = await self.graph.astream_events(
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
