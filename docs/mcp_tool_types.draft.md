

| Dimension           | Direct Tools                | Network MCP (HTTP/SSE)       | Stdio MCP (Subprocess)        |
| ------------------- | --------------------------- | ---------------------------- | ----------------------------- |
| Execution Context   | Same Python process         | Remote or local microservice | Spawned background subprocess |
| Overhead            | None (0ms)                  | Low-Medium (HTTP latency)    | Low (OS Pipe IPC)             |
| State Integration   | Full LangGraph State access | Isolated / Stateless         | Isolated / Stateless          |
| Port / Network Req. | None                        | Requires HTTP Port (:8000)   | None (Uses OS Pipes)          |
| Primary Advantage   | Speed & Deep State Access   | Distribution & Isolation     | Off-the-shelf CLI ecosystem   |