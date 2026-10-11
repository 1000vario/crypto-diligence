"""Provider-neutral types. History items are plain dicts so cassettes serialise as JSON.

History item shapes:
  {"role": "user", "text": str}
  {"role": "assistant", "raw": <provider-specific>, "text": str, "tool_calls": [ToolCall dicts]}
  {"role": "tool_results", "results": [ToolResult dicts]}
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from ..schemas import Usage


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    server: str | None = None  # "web_search" marks a provider-hosted search tool


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class ServerToolEvent:
    """A provider-side tool call observed in a response (web search)."""

    name: str
    input: dict[str, Any]
    output: str
    is_error: bool = False


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str  # end_turn | tool_use | max_tokens | pause_turn | refusal | other
    usage: Usage
    raw_assistant: Any
    server_tool_events: list[ServerToolEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": [asdict(t) for t in self.tool_calls],
            "stop_reason": self.stop_reason,
            "usage": self.usage.model_dump(),
            "raw_assistant": self.raw_assistant,
            "server_tool_events": [asdict(e) for e in self.server_tool_events],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Turn:
        return cls(
            text=d.get("text", ""),
            tool_calls=[ToolCall(**t) for t in d.get("tool_calls", [])],
            stop_reason=d.get("stop_reason", "end_turn"),
            usage=Usage(**d.get("usage", {})),
            raw_assistant=d.get("raw_assistant"),
            server_tool_events=[ServerToolEvent(**e) for e in d.get("server_tool_events", [])],
        )


class ModelProvider(Protocol):
    name: str

    async def complete(
        self,
        *,
        model: str,
        system: str,
        history: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int,
        response_schema: dict[str, Any] | None = None,
        max_web_searches: int = 0,
        tag: str = "",
    ) -> Turn: ...


def assistant_item(turn: Turn) -> dict[str, Any]:
    return {
        "role": "assistant",
        "raw": turn.raw_assistant,
        "text": turn.text,
        "tool_calls": [asdict(t) for t in turn.tool_calls],
    }


def tool_results_item(results: list[ToolResult]) -> dict[str, Any]:
    return {"role": "tool_results", "results": [asdict(r) for r in results]}
