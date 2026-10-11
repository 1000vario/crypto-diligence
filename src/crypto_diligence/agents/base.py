"""The loop that runs one investigator: model turn, tool calls, until a JSON answer.

Every model call and every tool call goes to the trace with its input, its output and its
token usage. The final answer is requested as structured JSON matching FINDING_SCHEMA.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from .. import pricing
from ..config import Settings
from ..providers.base import (
    ModelProvider,
    ToolCall,
    ToolResult,
    ToolSpec,
    assistant_item,
    tool_results_item,
)
from ..schemas import Claim, Finding, ModelCallRecord, Source
from ..tools.context import ToolContext
from ..tools.registry import run_tool
from ..trace import Trace

SOURCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "URL read through a tool in this conversation"},
        "title": {"type": "string", "description": "page or dataset title, empty when unknown"},
        "note": {"type": "string", "description": "what this source states, empty when obvious"},
    },
    "required": ["url", "title", "note"],
    "additionalProperties": False,
}

CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "one checkable fact, one or two sentences"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "date": {"type": "string", "description": "YYYY-MM-DD, or empty when the fact has no date"},
        "sources": {"type": "array", "items": SOURCE_SCHEMA},
    },
    "required": ["text", "tags", "confidence", "date", "sources"],
    "additionalProperties": False,
}

FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": CLAIM_SCHEMA},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claims", "open_questions"],
    "additionalProperties": False,
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def extract_json(text: str) -> Any:
    """Parse the model's final text as JSON, tolerating prose or a code fence around it."""
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("no JSON object in the model's final text")


def parse_finding(agent: str, text: str, today: str) -> Finding:
    try:
        data = extract_json(text)
    except ValueError as exc:
        return Finding(agent=agent, failed=True, failure_reason=f"final answer not JSON: {exc}")
    if not isinstance(data, dict):
        return Finding(agent=agent, failed=True, failure_reason="final answer is not an object")
    claims: list[Claim] = []
    for item in data.get("claims") or []:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        sources: list[Source] = []
        for s in item.get("sources") or []:
            if isinstance(s, dict) and str(s.get("url", "")).strip():
                sources.append(Source(url=str(s["url"]).strip(), accessed=today,
                                      title=(s.get("title") or None),
                                      note=(s.get("note") or None)))
            elif isinstance(s, str) and s.strip():
                sources.append(Source(url=s.strip(), accessed=today))
        date = str(item.get("date") or "").strip() or None
        if date and not _DATE_RE.match(date):
            date = date[:10] if _DATE_RE.match(date[:10]) else None
        confidence = item.get("confidence") if item.get("confidence") in ("high", "medium",
                                                                           "low") else "low"
        tags = [str(t) for t in (item.get("tags") or []) if str(t).strip()]
        claims.append(Claim(agent=agent, text=str(item["text"]).strip(), tags=tags,
                            confidence=confidence, date=date, sources=sources,
                            unsourced=not sources))
    questions = [str(q) for q in (data.get("open_questions") or []) if str(q).strip()]
    return Finding(agent=agent, claims=claims, open_questions=questions)


async def _run_one(ctx: ToolContext, trace: Trace, agent: str, call: ToolCall) -> ToolResult:
    t0 = time.perf_counter()
    content, is_error = await run_tool(ctx, call.name, call.input)
    trace.tool_call(agent=agent, tool=call.name, input=call.input, output=content,
                    is_error=is_error, duration_ms=int((time.perf_counter() - t0) * 1000))
    return ToolResult(call_id=call.id, name=call.name, content=content, is_error=is_error)


async def run_agent(
    *,
    agent: str,
    provider: ModelProvider,
    model: str,
    system: str,
    task: str,
    tools: list[ToolSpec],
    ctx: ToolContext,
    trace: Trace,
    settings: Settings,
    today: str,
    response_schema: dict[str, Any] | None = None,
) -> Finding:
    schema = FINDING_SCHEMA if response_schema is None else response_schema
    history: list[dict[str, Any]] = [{"role": "user", "text": task}]
    tool_errors: list[str] = []
    for turn_no in range(1, settings.max_turns + 1):
        t0 = time.perf_counter()
        try:
            turn = await provider.complete(
                model=model, system=system, history=history, tools=tools,
                max_tokens=settings.max_tokens, response_schema=schema,
                max_web_searches=settings.max_web_searches, tag=f"{agent}:{turn_no}",
            )
        except Exception as exc:  # noqa: BLE001  (the failure is the finding)
            reason = f"model call failed: {exc.__class__.__name__}: {exc}"
            trace.event("model_error", agent=agent, turn=turn_no, error=reason)
            return Finding(agent=agent, failed=True, failure_reason=reason,
                           tool_errors=tool_errors)
        trace.model_call(ModelCallRecord(
            agent=agent, provider=provider.name, model=model, turn=turn_no, usage=turn.usage,
            cost_usd=pricing.cost_usd(model, turn.usage), stop_reason=turn.stop_reason,
            duration_ms=int((time.perf_counter() - t0) * 1000),
        ))
        for ev in turn.server_tool_events:
            trace.tool_call(agent=agent, tool=ev.name, input=ev.input, output=ev.output,
                            is_error=ev.is_error, duration_ms=0, server_side=True)
            if ev.is_error:
                tool_errors.append(f"{ev.name}: {ev.output[:300]}")
        history.append(assistant_item(turn))
        if turn.tool_calls:
            results = await asyncio.gather(
                *(_run_one(ctx, trace, agent, call) for call in turn.tool_calls)
            )
            for r in results:
                if r.is_error:
                    tool_errors.append(f"{r.name}: {r.content[:300]}")
            history.append(tool_results_item(list(results)))
            continue
        if turn.stop_reason in ("pause_turn", "tool_use"):
            continue
        if turn.stop_reason in ("refusal", "max_tokens"):
            return Finding(agent=agent, failed=True, failure_reason=f"stopped: {turn.stop_reason}",
                           tool_errors=tool_errors)
        finding = parse_finding(agent, turn.text, today)
        finding.tool_errors = tool_errors
        return finding
    return Finding(agent=agent, failed=True,
                   failure_reason=f"no final answer after {settings.max_turns} turns",
                   tool_errors=tool_errors)
