from dataclasses import dataclass
from typing import Union

@dataclass
class ToolStart:
    tool_id: str
    tool_name: str
    tool_in: str

@dataclass
class ToolStop:
    tool_id: str
    tool_out: str

@dataclass
class TextDelta:
    text: str

@dataclass
class TokenUsage:
    tok_in: int = 0
    tok_out: int = 0
    tok_total: int = 0

AgentEvent = Union[ToolStart, ToolStop, TextDelta, TokenUsage]