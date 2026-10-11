"""OpenAI Chat Completions provider. Written to show the port; not exercised live yet.

Differences from the Anthropic provider, kept visible on purpose:
- no provider-hosted web search in Chat Completions, so the `web_search` ToolSpec is dropped
  and the agent sees a shorter tool list;
- tool results are one `role: tool` message per call instead of one user message;
- structured output goes through `response_format`.
"""

from __future__ import annotations

import json
from typing import Any

from ..schemas import Usage
from .base import ToolCall, ToolSpec, Turn


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()

    @staticmethod
    def wire_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for t in tools:
            if t.server is not None:
                continue
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                        "strict": True,
                    },
                }
            )
        return out

    @staticmethod
    def wire_messages(system: str, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for item in history:
            role = item["role"]
            if role == "user":
                msgs.append({"role": "user", "content": item["text"]})
            elif role == "assistant":
                msgs.append(item["raw"])
            elif role == "tool_results":
                for r in item["results"]:
                    msgs.append(
                        {"role": "tool", "tool_call_id": r["call_id"], "content": r["content"]}
                    )
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
            "messages": self.wire_messages(system, history),
            "max_completion_tokens": max_tokens,
        }
        wired = self.wire_tools(tools)
        if wired:
            params["tools"] = wired
        if response_schema is not None:
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "finding", "schema": response_schema, "strict": True},
            }
        resp = await self.client.chat.completions.create(**params)
        return self.parse_response(resp)

    @staticmethod
    def parse_response(resp: Any) -> Turn:
        choice = resp.choices[0]
        msg = choice.message
        tool_calls: list[ToolCall] = []
        raw_calls: list[dict[str, Any]] = []
        for tc in msg.tool_calls or []:
            args = tc.function.arguments or "{}"
            try:
                parsed = json.loads(args)
            except json.JSONDecodeError:
                parsed = {"_invalid_json": args}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, input=parsed))
            raw_calls.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": args},
                }
            )
        raw: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if raw_calls:
            raw["tool_calls"] = raw_calls
        if getattr(msg, "refusal", None):
            stop = "refusal"
        elif tool_calls:
            stop = "tool_use"
        elif choice.finish_reason == "length":
            stop = "max_tokens"
        else:
            stop = "end_turn"
        u = resp.usage
        cached = 0
        details = getattr(u, "prompt_tokens_details", None) if u else None
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        usage = Usage(
            input_tokens=max(0, (u.prompt_tokens if u else 0) - cached),
            output_tokens=u.completion_tokens if u else 0,
            cache_read_tokens=cached,
        )
        return Turn(
            text=msg.content or "",
            tool_calls=tool_calls,
            stop_reason=stop,
            usage=usage,
            raw_assistant=raw,
        )
