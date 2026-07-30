

# File Context Management 

VEX Shell use deterministic file context management system, in a nutshell I can 
describe it as "Mark once, hot-reload forever". How it works ?

VEX cli experiment CLI agentic system focused on **low memory footprint** and **extremely high flexibility**. \
Current prefered workflow looks follow: user create own CONFIG.yaml and setup necessary tools for hist project, \
also he provides AGENT.md file with project description and important details (just like usual), and after VEX ready to work.

![alt text](file_ctx_1.png)

As result LLM always gets the last version of tracked files and gives more attention to file context than to messages in chat.

## References
1. [cat_tool](../src/utils/tools.py)
1. [file context update](../src/utils/fs.py)