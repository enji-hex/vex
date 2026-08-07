
# VEX SHELL

<style>
    a{color:orange}
</style>
<pre style="color:orange;background-color:transparent">
██╗   ██╗███████╗██╗  ██╗
██║   ██║██╔════╝╚██╗██╔╝
██║   ██║█████╗   ╚███╔╝ 
╚██╗ ██╔╝██╔══╝   ██╔██╗ 
 ╚████╔╝ ███████╗██╔╝ ██╗
  ╚═══╝  ╚══════╝╚═╝  ╚═╝
</pre>

VEX cli experiment CLI agentic system focused on **low memory footprint** and **extremely high flexibility**. \
Current prefered workflow looks follow: user create own CONFIG.yaml and setup necessary tools for hist project, \
also he provides AGENTS.md file with project description and important details (just like usual), and after VEX ready to work.




## Current stack

| Domain        |                                    |
| ------------- | ---------------------------------- |
| Agent Control | Langgraph                          |
| Interface     | `rich`,`prompt_toolkit`            |
| History       | sqlite checkpointer from langgraph |

## In-depth

- [File Context Management](./docs/file_context_management.md)

## EPs 

1. Separate tools into packets, like `tools_nex`, `tools_c`, `tools_rust` etc. To prevent context overloading with tool specifications
2. create list of sessions
4. Polish UI