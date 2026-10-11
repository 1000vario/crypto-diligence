"""Render a Report as Markdown or JSON. The disclaimer comes first, always."""

from __future__ import annotations

from .schemas import AGENT_NAMES, Claim, Report

AGENT_TITLES = {
    "onchain": "On-chain",
    "market": "Market",
    "docs": "Documentation",
    "incidents": "Incidents",
    "single": "Single investigator (baseline)",
}


def _fmt_usd(value: float | None) -> str:
    return "unknown (model not in pricing table)" if value is None else f"${value:.4f}"


def _claim_line(c: Claim) -> str:
    meta = [f"confidence: {c.confidence}"]
    if c.date:
        meta.append(f"date: {c.date}")
    if c.tags:
        meta.append("tags: " + ", ".join(c.tags))
    line = f"- **{c.id}** {c.text} ({'; '.join(meta)})"
    if c.sources:
        refs = []
        for s in c.sources:
            label = s.title or s.url
            refs.append(f"[{label}]({s.url})" + (f" ({s.note})" if s.note else ""))
        line += "\n  Sources: " + "; ".join(refs)
    else:
        line += "\n  **NO SOURCE: this claim failed the sourcing rule and must not be relied on.**"
    return line


def to_markdown(report: Report) -> str:
    ident = report.identity
    title = ident.name or ident.query
    if ident.symbol:
        title += f" ({ident.symbol})"
    out: list[str] = [f"# Due-diligence report: {title}", "", f"> {report.disclaimer}", ""]
    out += [
        f"Generated {report.generated_at}. Mode: {report.mode}. Provider: {report.provider}. "
        f"Models: {', '.join(f'{k} {v}' for k, v in report.models.items())}. Run id: "
        f"{report.run_id}.",
        "",
        "## Subject",
        "",
        f"- Query: {ident.query}",
        f"- Resolved: {'yes' if ident.resolved else 'no'}",
    ]
    for label, value in (
        ("Name", ident.name), ("Symbol", ident.symbol), ("Chain", ident.chain),
        ("Contract", ident.address), ("CoinGecko id", ident.coingecko_id),
        ("DeFiLlama slug", ident.defillama_slug), ("DeFiLlama parent", ident.defillama_parent),
        ("Website", ident.website),
    ):
        if value:
            out.append(f"- {label}: {value}")
    for g in ident.github:
        out.append(f"- GitHub: {g}")
    for n in ident.notes:
        out.append(f"- Note: {n}")
    out.append("")

    out += ["## Claims", ""]
    order = [a for a in AGENT_NAMES if a in report.findings] + [
        a for a in report.findings if a not in AGENT_NAMES
    ]
    for agent in order:
        finding = report.findings[agent]
        out.append(f"### {AGENT_TITLES.get(agent, agent)} ({len(finding.claims)} claims)")
        out.append("")
        if finding.failed:
            out.append(f"Investigator failed: {finding.failure_reason}")
            out.append("")
        for c in finding.claims:
            out.append(_claim_line(c))
        if not finding.claims and not finding.failed:
            out.append("No claims.")
        out.append("")

    out += ["## Contradictions", ""]
    if report.contradictions:
        for c in report.contradictions:
            out.append(f"- **{c.topic}** (severity {c.severity}; claims {', '.join(c.claim_ids)}): "
                       f"{c.description}")
    else:
        out.append("None flagged by the contradiction pass.")
    out.append("")

    questions = [(a, q) for a in order for q in report.findings[a].open_questions]
    out += ["## Open questions", ""]
    if questions:
        out += [f"- {AGENT_TITLES.get(a, a)}: {q}" for a, q in questions]
    else:
        out.append("None.")
    out.append("")

    errors = [(a, e) for a in order for e in report.findings[a].tool_errors]
    if errors:
        out += ["## Tool errors", ""] + [f"- {AGENT_TITLES.get(a, a)}: {e}" for a, e in errors]
        out.append("")

    q = report.quality
    out += ["## Quality checks", "",
            f"- Claims: {len(report.claims)}",
            f"- Claims without a source: {len(q.unsourced_claim_ids)}"
            + (f" ({', '.join(q.unsourced_claim_ids)})" if q.unsourced_claim_ids else ""),
            f"- Neutrality violations: {len(q.neutrality_violations)}"
            + ("".join(f"\n  - {v['where']}: {v['match']!r}" for v in q.neutrality_violations)),
            f"- Investigators failed: {', '.join(q.agents_failed) if q.agents_failed else 'none'}",
            ""]
    for n in report.orchestrator_notes:
        out.append(f"- Orchestrator note: {n}")
    if report.orchestrator_notes:
        out.append("")

    cost = report.cost
    u = cost.usage
    out += ["## Cost and duration", "",
            "| Item | Value |", "|---|---|",
            f"| Total cost | {_fmt_usd(cost.total_usd)} |",
            f"| Model calls | {cost.model_calls} |",
            f"| Tool calls (client side) | {cost.tool_calls - cost.web_search_requests} |",
            f"| Web search requests (server side) | {cost.web_search_requests} |",
            f"| Input tokens | {u.input_tokens} |",
            f"| Output tokens | {u.output_tokens} |",
            f"| Cache read tokens | {u.cache_read_tokens} |",
            f"| Cache write tokens | {u.cache_write_tokens} |",
            f"| Duration | {report.duration_s} s |",
            "",
            "By agent: " + ", ".join(f"{a} {_fmt_usd(v)}" for a, v in cost.by_agent_usd.items()),
            "", f"Pricing: {cost.pricing_note}", ""]
    if report.trace_path:
        out += ["## Trace", "",
                f"Every model and tool call is in `{report.trace_path}` (JSON lines).", ""]
    return "\n".join(out)


def to_json(report: Report) -> str:
    return report.model_dump_json(indent=2) + "\n"
