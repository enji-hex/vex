from typing import List, Optional

from aiohttp import web
import aiohttp_cors
import json
import asyncio
from pathlib import Path
from vex_shell.engine.events import *
from langchain_core.messages import AnyMessage

from vex_shell.mcp_tools.tools_mcp import MCPManager
from vex_shell.utils.config import LOGGER,Settings
from vex_shell.engine.agent import Agent
from vex_cli.commands import CliOutput, cli_command

def clean_snippet(text: str, limit: int = 60) -> str:
    cleaned = " ".join(text.splitlines()).strip()
    return cleaned[:limit] if cleaned else ""

class VexWeb:
    def __init__(self,
                 session_id:str,
                 settings:Settings,
                 static_dir:str,
                 host:str,
                 port:int,):

        self.agent = None
        self.settings = settings
        self.host  = host
        self.port  = port
        self.static_dir = (Path(__file__).parent / static_dir).resolve()
        self.clients = set()
        self.runner  = None
        
        self.app = web.Application()
        self.app.router.add_get("/",self.h_index)
        self.app.router.add_get("/ws",self.h_ws)
        self.app.router.add_get("/api/history/{session}",self.h_history)
        self.app.router.add_get("/api/ls",self.h_list_sessions)
        self.app.router.add_get("/{path:.*}",self.h_static)

        cors = aiohttp_cors.setup(self.app,defaults={
            "*":aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*"
            )
        })
        for route in list(self.app.router.routes()):
            cors.add(route)

    @classmethod
    async def create(cls,
                     session_id:str,
                     settings:Settings,
                     static_dir:str = "./static",
                     host:str = "127.0.0.1",
                     port:int = 40_000):

        v = VexWeb(session_id,settings,static_dir,host,port)
        # start session only if present and not default
        if session_id and session_id != "default":
            await v.init_agent(session_id)
        return v
        
    async def init_agent(self,session_id):
        from vex_shell.engine import core
        from vex_shell.engine.agent import Agent

        self.session_id = session_id

        tools,mcp_manager = await core.get_tools(self.settings)
        graph = core.build_graph(self.settings, tools)
        agent = await Agent.create(graph, session_id, self.settings, mcp_manager)
        
        self.agent = agent

    async def h_index(self, req: web.Request) -> web.StreamResponse:
        index_file = self.static_dir / "index.html"
        print(index_file)
        if not index_file.is_file():
            return web.Response(text="404 Index Not Found", status=404)
        return web.FileResponse(index_file)
    
    async def h_static(self, request: web.Request):
        rel_path = request.match_info.get("path", "")
        target_path = (self.static_dir / rel_path).resolve()

        if not str(target_path).startswith(str(self.static_dir)) \
            or not target_path.is_file():
            return web.Response(text="404 Not Found", status=404)

        return web.FileResponse(target_path)


    async def h_list_sessions(self,req:web.Request):
        from vex_shell.engine.helpers import get_saved_sessions
        return web.json_response([id for id in 
            await get_saved_sessions(self.settings.db_path)])

    async def h_history(self, req: web.Request) -> web.Response:
        session_id = req.match_info['session']
        if self.agent:
            await self.agent.close()
        await self.init_agent(session_id)
        
        messages: List[AnyMessage] = await self.agent.restore_history()
        load_last_n = self.settings.chat["load_last_n"]

        LOGGER.info(f"found messages {len(messages)}")
        if load_last_n != -1:
            messages = messages[-load_last_n:]

        resp = []
        for m in messages:
            if m.type == "human":
                content_text = m.content if isinstance(m.content, str) else str(m.content)
                resp.append({"from":"user","content":content_text})

            if m.type == "ai" and m.content:
                if isinstance(m.content,str):
                    LOGGER.debug('msg as str')
                    resp.append({"from":"user","content":m.content})
                elif isinstance(m.content,list):
                    for c in m.content:
                        if isinstance(c, dict) and c["type"] == "text":
                            resp.append({"from":"ai","content":c["text"]})

        return web.json_response(resp)

    async def h_ws(self,req:web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(req)

        if not self.agent: 
            await ws.send_json({"type":"err","content":"agent is not running"})
            return ws

        curr_task:asyncio.Task | None = None

        async def run_agent(prompt:str):
            try:
                stream = self.agent.run_step(prompt)

                content_str = ""
                active_tools: dict[str, ToolStart] = {}
                
                async for ev in stream:
                    if isinstance(ev,TextDelta):
                        content_str += ev.text
                    elif isinstance(ev,ToolStart):
                        active_tools[ev.tool_id] = ev
                    elif isinstance(ev,ToolStop):
                        tool_start = active_tools.pop(ev.tool_id)
                        if tool_start:
                            out_snippet = clean_snippet(ev.tool_out) or "done"
                            in_snippet = clean_snippet(tool_start.tool_in)
                        await ws.send_json({
                            "type":"tool",
                            "content":f"**{tool_start.tool_name}** ({in_snippet})\n"+
                            f" ✓ {out_snippet}"
                            })
                
                await ws.send_json({"type":"ai","content":content_str})
            except asyncio.CancelledError:
                await ws.send_json({"type":"status","content":"cancelled"})

        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue

            data = json.loads(msg.data)
            content:str = data.get("content")
            if not content: continue

            # later pass to command handler
            if content.startswith("/"):
                if content == "/q":
                    if curr_task and not curr_task.done():
                        curr_task.cancel()
                    await ws.send_json({"type":"ai","content":"Current task canceled"})
                    continue
                else:
                    cmd_resp = await cli_command(content,self.agent)
                    match cmd_resp.result:
                        case CliOutput.SKIP:
                            await ws.send_json({
                            "type":"tool",
                            "content":cmd_resp.content,
                            "title":cmd_resp.title
                            })
                            continue
                        # potentially we can send audio, but it should be recorded in browser

            if curr_task and not curr_task.done():
                await ws.send_json({"type":"err","content":"Agent is busy"})
                continue
            curr_task = asyncio.create_task(run_agent(content))
        
        return ws


    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner,self.host,self.port)
        await site.start()

        print(f"[VEX] Web server live on http://{self.host}:{self.port}")
        
    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
        if self.agent:
            await self.agent.close()


async def start_session_web(port,settings,session_id:str):
    app = await VexWeb.create(session_id,settings,port=port)
    await app.start()

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await app.stop()

