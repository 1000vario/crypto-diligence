"""Anthropic Messages API provider: hand-written tool loop, server-side web search."""

from __future__ import annotations

import json
from typing import Any

from ..schemas import Usage
from .base import ServerToolEvent, ToolCall, ToolSpec, Turn

WEB_SEARCH_TOOL_TYPE = "web_search_20260209"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, effort: str = "medium") -> None:
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()
        self.effort = effort

    @staticmethod
    def wire_tools(tools: list[ToolSpec], max_web_searches: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for t in tools:
            if t.server == "web_search":
                spec: dict[str, Any] = {"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search"}
                if max_web_searches > 0:
                    spec["max_uses"] = max_web_searches
                out.append(spec)
            else:
                out.append(
                    {
                        "name": t.name,
                        "description": t.description,
                        "input_schema": t.input_schema,
                        "strict": True,
                    }
                )
        return out

    @staticmethod
    def wire_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = []
        for item in history:
            role = item["role"]
            if role == "user":
                msgs.append({"role": "user", "content": [{"type": "text", "text": item["text"]}]})
            elif role == "assistant":
                msgs.append({"role": "assistant", "content": item["raw"]})
            elif role == "tool_results":
                blocks = []
                for r in item["results"]:
                    block: dict[str, Any] = {
                        "type": "tool_result",
                        "tool_use_id": r["call_id"],
                        "content": r["content"],
                    }
                    if r.get("is_error"):
                        block["is_error"] = True
                    blocks.append(block)
                msgs.append({"role": "user", "content": blocks})
        return msgs

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
    ) -> Turn:
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": self.wire_messages(history),
            "thinking": {"type": "adaptive"},
        }
        wired = self.wire_tools(tools, max_web_searches)
        if wired:
            params["tools"] = wired
        output_config: dict[str, Any] = {}
        if self.effort:
            output_config["effort"] = self.effort
        if response_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": response_schema}
        if output_config:
            params["output_config"] = output_config
        resp = await self.client.messages.create(**params)
        return self.parse_response(resp)

    @staticmethod
    def parse_response(resp: Any) -> Turn:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        events: list[ServerToolEvent] = []
        pending_server: dict[str, dict[str, Any]] = {}
        raw: list[dict[str, Any]] = []
        for block in resp.content:
            raw.append(block.model_dump(mode="json", exclude_none=True))
            btype = block.type
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))
            elif btype == "server_tool_use":
                pending_server[block.id] = {"name": block.name, "input": dict(block.input)}
            elif btype == "web_search_tool_result":
                call = pending_server.pop(block.tool_use_id, {"name": "web_search", "input": {}})
                content = block.content
                if isinstance(content, list):
                    hits = []
                    for item in content:
                        hits.append(
                            {
                                "title": getattr(item, "title", None),
                                "url": getattr(item, "url", None),
                                "page_age": getattr(item, "page_age", None),
                            }
                        )
                    events.append(
                        ServerToolEvent(
                            name=call["name"],
                            input=call["input"],
                            output=json.dumps(hits, ensure_ascii=False),
                        )
                    )
                else:
                    code = getattr(content, "error_code", "unknown_error")
                    events.append(
                        ServerToolEvent(
                            name=call["name"],
                            input=call["input"],
                            output=json.dumps({"error_code": code}),
                            is_error=True,
                        )
                    )
        u = resp.usage
        stu = getattr(u, "server_tool_use", None)
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            web_search_requests=(getattr(stu, "web_search_requests", 0) or 0) if stu else 0,
        )
        return Turn(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason or "end_turn",
            usage=usage,
            raw_assistant=raw,
            server_tool_events=events,
        )
