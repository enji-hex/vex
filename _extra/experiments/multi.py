# vex_shell/experiments/test_multi_agent.py

import asyncio
import copy
from pathlib import Path
import tomllib
from typing import Dict, List

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from vex_shell.utils import config
from vex_shell.engine.core import get_tools
from vex_shell.utils.file_access import file_access_control
from vex_shell.engine.state import State
from vex_shell.engine.nodes import llm_call_node, verification_node, should_continue, should_verify


def get_template(cfg:Dict,template_name:str) -> Dict | None:
    return cfg.get(template_name)

def create_agent_node(agent_settings:config.Settings, tools: List[BaseTool]):
    async def _node(state:State,config:RunnableConfig):
        return await llm_call_node(
            state,
            config=config,
            settings=agent_settings,
            tools=tools)
    return _node

def build_experimental_graph(
        agent_settings_map: Dict[str,config.Settings], 
        pipeline:List[str],
        tools:List[BaseTool]) -> StateGraph:
    
    graph = StateGraph(State)
    for agent_name in pipeline:
        ast = agent_settings_map[agent_name]
        graph.add_node(agent_name,create_agent_node(
            agent_settings=ast,
            tools=tools # now shared
            ))
    # add shared tools (Sorry)
    graph.add_node("tool_node",ToolNode(tools))


    first_agent = pipeline[0]
    graph.add_edge("__start__", pipeline[0])

    for i in range(len(pipeline)):
        cur_agent = pipeline[i]
        next_step = pipeline[i + 1] if (i + 1) < len(pipeline) else "__end__"

        graph.add_conditional_edges(
            cur_agent,
            should_continue, {
                "tool_node":"tool_node",
                "__end__":next_step
            })
    
    graph.add_edge("tool_node", first_agent)
    return graph
    
async def multi_agent():
    settings = config.Settings()
    file_access_control.reconfigure(settings)
    
    agents_file = Path(settings.vex_folder) / "AGENTS.toml"
    if not agents_file.exists(): 
        raise ValueError("AGENTS.md not found ")

    agents_cfg = tomllib.loads(agents_file.read_text(encoding='utf-8'))
    pipeline = agents_cfg['pipeline']['graph']

    agent_settings_map: Dict[str,config.Settings] = {}
    for aname in pipeline:
        if aname not in agents_cfg:
            raise ValueError('Defined agent not exists in AGENTS.toml')

        agent           = agents_cfg[aname]
        template_name   = agent.get("template","")

        base_model      = get_template(agents_cfg,template_name)
        model_override  = agent.get("model",{})

        merged_model = dict(base_model) if base_model else {}
        merged_model.update(model_override)

        ast = copy.copy(settings)
        ast.model = merged_model
        ast.system_prompt = agent['role'] # role SHOULD be defined
        agent_settings_map[aname] = ast

    tools,mcp_manager = await get_tools(settings) # shared tools
    compiled_graph = build_experimental_graph(
        agent_settings_map,
        pipeline,
        tools=tools).compile()
return compiled_graph

async def test_multi(compiled_graph, user_query:str):
    initial_state = {
        "messages":{
            "role":"user",
            "content":user_query
        }
    }
    print(f"User Query: {user_query}\n" + "=" * 50)


    config = {
        "recursion_limit":10
    }

    async for event in compiled_graph.astream(initial_state,stream_mode="updates",config=config):
        for node_name,state_update in event.items():
            print(f"\n[Node Executed]: {node_name}")

            if "messages" in state_update and state_update["messages"]:
                last_msg = state_update["messages"][-1]
                
                msg_type  = getattr(last_msg, "type", "assistant")
                tool_name = getattr(last_msg,"name",None)

                if msg_type == "tool":
                    print(f'[T {tool_name}]:  {last_msg.content[:200]}')
                elif msg_type == "ai":
                    print(f'[A {node_name}]: {last_msg.content}')
                    if hasattr(last_msg,"tool_calls") and last_msg.tool_calls:
                        for tc in last_msg.tool_calls:
                            print(f" -> Requested Tool Call: {tc['name']}({tc['args'][:200]})")


async def main():
    compiled_graph = await multi_agent()
    
    query = "Write a Python script in sandbox/v2t.py that converts video to text, then verify it."
    # await test_multi(compiled_graph, query)

asyncio.run(main())


