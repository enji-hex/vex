

# File Context Management 


VEX Shell use deterministic file context management system, in a nutshell I can 
describe it as "Mark once, hot-reload forever". 

**How it works ?**

When the user asks agent for file content, like "What does func test() from ./main.py ?"
agent request `cat_tool` for this file, `cat_tool` read file, store in file_context and in future before each user request file content is updated in history if file was changed (It checked by file modification time info provided by OS(mtime)).

![alt text](file_ctx_1.png)

As result LLM always gets the last version of tracked files and gives more attention to file context than to messages in chat.


```py
file_context = format_file_context(new_files_snap)
messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]

if file_context:
    last_msg = messages[-1]
    updated_content = (
        f"{last_msg.content}\n\n"
        f"--- ACTIVE WORKING CONTEXT (GROUND TRUTH) ---\n"
        f"{file_context}"
    )
    if isinstance(last_msg, HumanMessage):
        messages[-1] = HumanMessage(content=updated_content, id=last_msg.id)
    elif isinstance(last_msg, ToolMessage):
        messages[-1] = ToolMessage(
            content=updated_content,
            tool_call_id=last_msg.tool_call_id,
            id=last_msg.id,
        )
```
