"""Scoring of a report against a hand-written truth sheet, without any model call.

A case is one YAML file in `evals/cases/`. Its `expected_facts` are regular expressions that
the claims of a good report should match; its `forbidden_facts` are statements a good report
must never make; its `expected_contradictions` are disagreements between sources that the
report must flag rather than smooth over. The score also counts claims without a source,
claims whose cited hosts no tool reached during the run, and neutrality violations.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from . import neutrality
from .schemas import Report

CATEGORIES = ("healthy", "exploit", "abandoned", "sensitive")
HOST_RE = re.compile(r"https?://([a-z0-9.-]+)", re.IGNORECASE)
EVIDENCE_KINDS = ("tool_call", "identity")  # trace events whose URLs a report may cite


@dataclass
class Case:
    id: str
    query: str
    category: str
    truth_date: str
    summary: str = ""
    identity: dict[str, Any] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    expected_facts: list[dict[str, Any]] = field(default_factory=list)
    forbidden_facts: list[dict[str, Any]] = field(default_factory=list)
    expected_contradictions: list[dict[str, Any]] = field(default_factory=list)
    path: str = ""


def load_case(path: Path) -> Case:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a mapping")
    if data.get("category") not in CATEGORIES:
        raise ValueError(f"{path}: category must be one of {CATEGORIES}")
    for key in ("expected_facts", "forbidden_facts", "expected_contradictions"):
        for item in data.get(key) or []:
            if not item.get("id") or not item.get("pattern"):
                raise ValueError(f"{path}: every {key} entry needs an id and a pattern")
            re.compile(item["pattern"])
    known = {f.name for f in fields(Case)} - {"path"}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")
    return Case(**{k: v for k, v in data.items() if k in known}, path=str(path))


def load_cases(cases_dir: Path, only: list[str] | None = None) -> list[Case]:
    cases = [load_case(p) for p in sorted(cases_dir.glob("*.yaml"))]
    if only:
        cases = [c for c in cases if c.id in only]
    return cases


def hosts_reached(trace_events: list[dict[str, Any]]) -> set[str]:
    """Hosts that appear in tool inputs and outputs during the run."""
    hosts: set[str] = set()
    for ev in trace_events:
        if ev.get("kind") not in EVIDENCE_KINDS:
            continue
        for m in HOST_RE.finditer(json.dumps(ev, ensure_ascii=False)):
            hosts.add(m.group(1).lower())
    return hosts


def read_trace(path: str | Path | None) -> list[dict[str, Any]]:
    if not path or not Path(path).is_file():
        return []
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _matches(pattern: str, texts: list[str]) -> bool:
    rx = re.compile(pattern)
    return any(rx.search(t) for t in texts)


@dataclass
class CaseScore:
    case_id: str
    category: str
    mode: str
    run_id: str
    recall: float
    expected_total: int
    expected_found: list[str]
    expected_missing: list[str]
    found_by_expected_agent: int
    unsourced_claims: list[str]
    unseen_source_claims: list[str]
    forbidden_hits: list[str]
    invention_failures: int
    coherence: float
    contradictions_expected: int
    contradictions_matched: list[str]
    contradictions_total: int
    neutrality_violations: int
    agents_failed: list[str]
    claims: int
    cost_usd: float | None
    duration_s: float
    web_search_requests: int


def score(case: Case, report: Report, trace_events: list[dict[str, Any]]) -> CaseScore:
    texts = [c.text for c in report.claims]
    found: list[str] = []
    missing: list[str] = []
    by_agent = 0
    for fact in case.expected_facts:
        rx = re.compile(fact["pattern"])
        hits = [c for c in report.claims if rx.search(c.text)]
        if hits:
            found.append(fact["id"])
            if any(c.agent == fact.get("agent") for c in hits):
                by_agent += 1
        else:
            missing.append(fact["id"])
    forbidden = [f["id"] for f in case.forbidden_facts if _matches(f["pattern"], texts)]
    reached = hosts_reached(trace_events)
    unseen = []
    for c in report.claims:
        cited = {m.group(1).lower() for s in c.sources for m in HOST_RE.finditer(s.url)}
        if cited and not cited & reached:
            unseen.append(c.id)
    unsourced = list(report.quality.unsourced_claim_ids)
    contradiction_texts = [f"{c.topic} {c.description}" for c in report.contradictions]
    matched = [e["id"] for e in case.expected_contradictions
               if _matches(e["pattern"], contradiction_texts)]
    n_exp = len(case.expected_contradictions)
    violations = neutrality.check_report(report)
    return CaseScore(
        case_id=case.id, category=case.category, mode=report.mode, run_id=report.run_id,
        recall=len(found) / len(case.expected_facts) if case.expected_facts else 1.0,
        expected_total=len(case.expected_facts), expected_found=found,
        expected_missing=missing, found_by_expected_agent=by_agent,
        unsourced_claims=unsourced, unseen_source_claims=unseen, forbidden_hits=forbidden,
        invention_failures=len(unsourced) + len(unseen) + len(forbidden),
        coherence=len(matched) / n_exp if n_exp else 1.0, contradictions_expected=n_exp,
        contradictions_matched=matched, contradictions_total=len(report.contradictions),
        neutrality_violations=len(violations), agents_failed=list(report.quality.agents_failed),
        claims=len(report.claims), cost_usd=report.cost.total_usd, duration_s=report.duration_s,
        web_search_requests=report.cost.web_search_requests,
    )


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 3) if values else None


def summarise(scores: list[CaseScore], date: str) -> dict[str, Any]:
    n = len(scores)
    modes = sorted({s.mode for s in scores})
    costs = [s.cost_usd for s in scores if s.cost_usd is not None]
    out: dict[str, Any] = {
        "date": date,
        "cases": n,
        "mode": modes[0] if len(modes) == 1 else modes,
        "recall_mean": _mean([s.recall for s in scores]),
        "facts_expected": sum(s.expected_total for s in scores),
        "facts_found": sum(len(s.expected_found) for s in scores),
        "invention_free_cases": sum(1 for s in scores if s.invention_failures == 0),
        "invention_failures_total": sum(s.invention_failures for s in scores),
        "unsourced_claims_total": sum(len(s.unsourced_claims) for s in scores),
        "unseen_source_claims_total": sum(len(s.unseen_source_claims) for s in scores),
        "forbidden_hits_total": sum(len(s.forbidden_hits) for s in scores),
        "coherence_mean": _mean([s.coherence for s in scores]),
        "contradictions_expected": sum(s.contradictions_expected for s in scores),
        "contradictions_matched": sum(len(s.contradictions_matched) for s in scores),
        "neutrality_clean_cases": sum(1 for s in scores if s.neutrality_violations == 0),
        "agents_failed_total": sum(len(s.agents_failed) for s in scores),
        "claims_mean": _mean([float(s.claims) for s in scores]),
        "cost_usd_mean": round(statistics.mean(costs), 4) if costs else None,
        "cost_usd_total": round(sum(costs), 4) if costs else None,
        "duration_s_mean": _mean([s.duration_s for s in scores]),
        "web_search_requests_total": sum(s.web_search_requests for s in scores),
        "by_category": {},
    }
    for cat in CATEGORIES:
        sub = [s for s in scores if s.category == cat]
        if sub:
            out["by_category"][cat] = {
                "cases": len(sub),
                "recall_mean": _mean([s.recall for s in sub]),
                "invention_free_cases": sum(1 for s in sub if s.invention_failures == 0),
                "coherence_mean": _mean([s.coherence for s in sub]),
            }
    return out


def to_markdown(summary: dict[str, Any], scores: list[CaseScore]) -> str:
    n = summary["cases"]
    lines = [
        f"Evals of {summary['date']}: {n} cases, mode `{summary['mode']}`.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Recall (expected facts found) | {summary['recall_mean']} "
        f"({summary['facts_found']}/{summary['facts_expected']} facts) |",
        f"| Cases free of invention | {summary['invention_free_cases']}/{n} |",
        f"| Claims without a source | {summary['unsourced_claims_total']} |",
        f"| Claims citing a host no tool reached | {summary['unseen_source_claims_total']} |",
        f"| Forbidden statements | {summary['forbidden_hits_total']} |",
        f"| Coherence (expected contradictions flagged) | {summary['coherence_mean']} "
        f"({summary['contradictions_matched']}/{summary['contradictions_expected']}) |",
        f"| Cases with no neutrality violation | {summary['neutrality_clean_cases']}/{n} |",
        f"| Investigators that failed | {summary['agents_failed_total']} |",
        f"| Claims per report (mean) | {summary['claims_mean']} |",
        f"| Cost per report, USD (mean) | {summary['cost_usd_mean']} |",
        f"| Cost of the run, USD (total) | {summary['cost_usd_total']} |",
        f"| Duration per report, s (mean) | {summary['duration_s_mean']} |",
        f"| Web search requests (total) | {summary['web_search_requests_total']} |",
        "",
        "| Case | Category | Recall | Invention failures | Coherence | Neutrality violations"
        " | Claims | Cost USD | Duration s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        cost = f"{s.cost_usd:.4f}" if s.cost_usd is not None else "n/a"
        lines.append(
            f"| {s.case_id} | {s.category} | {s.recall:.2f} | {s.invention_failures} | "
            f"{s.coherence:.2f} | {s.neutrality_violations} | {s.claims} | {cost} | "
            f"{s.duration_s:.0f} |"
        )
    return "\n".join(lines) + "\n"
