"""The orchestrator: resolves the subject, runs the investigators in parallel, assembles the
report. It does no research itself. Its only model call is the contradiction pass, which
reads the claims and nothing else.

`mode="single_agent"` runs the baseline used by the evals: one investigator with every tool
and the same contradiction pass, so the two modes differ only in the split of the work.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from . import neutrality, pricing
from .agents.base import extract_json, run_agent
from .agents.prompts import CONTRADICTIONS, PROMPTS, task_message
from .config import Settings
from .identity import resolve_identity
from .providers import make_provider
from .providers.base import ModelProvider
from .schemas import (
    AGENT_NAMES,
    Claim,
    Contradiction,
    CostSummary,
    Finding,
    Identity,
    ModelCallRecord,
    Quality,
    Report,
)
from .tools.context import ToolContext
from .tools.registry import tools_for
from .trace import Trace, now_iso, today_iso

CONTRADICTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "contradictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "claim_ids": {"type": "array", "items": {"type": "string"}},
                    "description": {"type": "string"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["topic", "claim_ids", "description", "severity"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["contradictions"],
    "additionalProperties": False,
}


def new_run_id(today: str) -> str:
    return f"{today.replace('-', '')}-{uuid.uuid4().hex[:8]}"


def number_claims(findings: dict[str, Finding]) -> list[Claim]:
    claims: list[Claim] = []
    for agent, finding in findings.items():
        for n, claim in enumerate(finding.claims, start=1):
            claim.id = f"{agent}-{n}"
            claim.agent = agent
            claims.append(claim)
    return claims


def claims_for_review(claims: list[Claim]) -> str:
    rows = [{"id": c.id, "agent": c.agent, "tags": c.tags, "date": c.date,
             "confidence": c.confidence, "text": c.text} for c in claims]
    return ("Claims, one JSON object per line:\n"
            + "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
            + "\n\nList the contradictions as the JSON object described.")


def parse_contradictions(text: str, known_ids: set[str]) -> tuple[list[Contradiction], str | None]:
    try:
        data = extract_json(text)
    except ValueError as exc:
        return [], f"contradiction pass returned no JSON ({exc})"
    out: list[Contradiction] = []
    for item in (data.get("contradictions") or []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        ids = [str(i) for i in item.get("claim_ids") or [] if str(i) in known_ids]
        if len(ids) < 2 or not str(item.get("description", "")).strip():
            continue
        sev = item.get("severity")
        if sev not in ("high", "medium", "low"):
            sev = "medium"
        out.append(Contradiction(topic=str(item.get("topic") or "").strip() or "unspecified",
                                 claim_ids=ids, description=str(item["description"]).strip(),
                                 severity=sev))
    return out, None


async def contradiction_pass(
    *, provider: ModelProvider, model: str, claims: list[Claim], trace: Trace, settings: Settings
) -> tuple[list[Contradiction], list[str]]:
    if len(claims) < 2:
        return [], ["contradiction pass skipped: fewer than two claims"]
    history = [{"role": "user", "text": claims_for_review(claims)}]
    t0 = time.perf_counter()
    try:
        turn = await provider.complete(
            model=model, system=CONTRADICTIONS, history=history, tools=[],
            max_tokens=settings.max_tokens, response_schema=CONTRADICTIONS_SCHEMA,
            max_web_searches=0, tag="orchestrator:1",
        )
    except Exception as exc:  # noqa: BLE001  (reported in the report, never hidden)
        reason = f"contradiction pass failed: {exc.__class__.__name__}: {exc}"
        trace.event("model_error", agent="orchestrator", turn=1, error=reason)
        return [], [reason]
    trace.model_call(ModelCallRecord(
        agent="orchestrator", provider=provider.name, model=model, turn=1, usage=turn.usage,
        cost_usd=pricing.cost_usd(model, turn.usage), stop_reason=turn.stop_reason,
        duration_ms=int((time.perf_counter() - t0) * 1000),
    ))
    if turn.stop_reason in ("refusal", "max_tokens"):
        return [], [f"contradiction pass stopped: {turn.stop_reason}"]
    found, note = parse_contradictions(turn.text, {c.id for c in claims})
    return found, [note] if note else []


def cost_summary(trace: Trace) -> CostSummary:
    by_agent = trace.cost_by_agent()
    total: float | None = 0.0
    for v in by_agent.values():
        if v is None:
            total = None
            break
        total += v
    usage = trace.usage_total()
    return CostSummary(
        total_usd=round(total, 6) if total is not None else None,
        by_agent_usd=by_agent,
        model_calls=len(trace.model_calls),
        tool_calls=len(trace.tool_calls),
        web_search_requests=usage.web_search_requests,
        usage=usage,
        pricing_date=pricing.PRICING_DATE,
        pricing_note=pricing.note(),
    )


async def run_report(
    query: str,
    settings: Settings,
    *,
    mode: str = "multi_agent",
    provider: ModelProvider | None = None,
    identity: Identity | None = None,
    trace_dir: Path | None = None,
    today: str | None = None,
    run_id: str | None = None,
) -> Report:
    """Produce one report. Everything the models and tools did is in the trace file."""
    if mode not in ("multi_agent", "single_agent"):
        raise ValueError(f"unknown mode {mode!r}")
    today = today or today_iso()
    run_id = run_id or new_run_id(today)
    trace_dir = trace_dir if trace_dir is not None else settings.data_dir / "traces"
    trace_path = trace_dir / f"{run_id}.jsonl"
    trace = Trace(trace_path, run_id=run_id)
    provider = provider or make_provider(settings)
    ctx = ToolContext(settings)
    started = time.perf_counter()
    trace.event("query", query=query, mode=mode, provider=provider.name)

    if identity is None:
        identity = await resolve_identity(query, ctx)
    trace.event("identity", **identity.model_dump())
    task = task_message(identity, today)
    sub_model = settings.model_for("subagent")

    agents = list(AGENT_NAMES) if mode == "multi_agent" else ["single"]
    runs = [
        run_agent(agent=a, provider=provider, model=sub_model, system=PROMPTS[a], task=task,
                  tools=tools_for(a), ctx=ctx, trace=trace, settings=settings, today=today)
        for a in agents
    ]
    results = await asyncio.gather(*runs, return_exceptions=True)
    findings: dict[str, Finding] = {}
    for agent, res in zip(agents, results, strict=True):
        if isinstance(res, BaseException):
            reason = f"investigator crashed: {res.__class__.__name__}: {res}"
            trace.event("agent_error", agent=agent, error=reason)
            findings[agent] = Finding(agent=agent, failed=True, failure_reason=reason)
        else:
            findings[agent] = res

    claims = number_claims(findings)
    contradictions, notes = await contradiction_pass(
        provider=provider, model=settings.model_for("orchestrator"), claims=claims,
        trace=trace, settings=settings,
    )
    if not identity.resolved:
        notes.append("identity not resolved: the investigators worked from the raw query")

    report = Report(
        run_id=run_id, mode=mode, generated_at=now_iso(), identity=identity,
        findings=findings, claims=claims, contradictions=contradictions,
        orchestrator_notes=notes, quality=Quality(), cost=cost_summary(trace),
        duration_s=round(time.perf_counter() - started, 1), provider=provider.name,
        models={"orchestrator": settings.model_for("orchestrator"), "subagent": sub_model},
        trace_path=str(trace_path),
    )
    report.quality = Quality(
        unsourced_claim_ids=[c.id for c in claims if c.unsourced],
        neutrality_violations=neutrality.check_report(report),
        agents_failed=[a for a, f in findings.items() if f.failed],
    )
    trace.event("report", run_id=run_id, claims=len(claims), contradictions=len(contradictions),
                unsourced=len(report.quality.unsourced_claim_ids),
                neutrality_violations=len(report.quality.neutrality_violations),
                cost_usd=report.cost.total_usd, duration_s=report.duration_s)
    return report
