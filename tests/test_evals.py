import json
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml
from helpers import sample_report

from crypto_diligence.evals import (
    CATEGORIES,
    Case,
    hosts_reached,
    load_case,
    load_cases,
    read_trace,
    score,
    summarise,
    to_markdown,
)

CASES_DIR = Path(__file__).resolve().parents[1] / "evals" / "cases"
EVALS_DIR = Path(__file__).resolve().parents[1] / "evals"

TRACE = [
    {"kind": "run_start", "run_id": "x"},
    {"kind": "tool_call", "agent": "onchain", "tool": "get_contract_source",
     "input": {"address": "0x1f98"},
     "output_excerpt": '{"sourcify": {"url": "https://sourcify.dev/server/v2/contract/1/0x1f98"}}'},
    {"kind": "report", "run_id": "x"},
]


def make_case(**over) -> Case:
    base = dict(
        id="uniswap", query="Uniswap", category="healthy", truth_date="2026-10-11",
        expected_facts=[
            {"id": "verified", "agent": "onchain", "pattern": r"verified on Sourcify"},
            {"id": "volume", "agent": "market", "pattern": r"[Vv]olume"},
            {"id": "missing", "agent": "docs", "pattern": r"MIT licen[cs]e"},
        ],
        forbidden_facts=[{"id": "no-exploit", "pattern": r"exploit(ed)? in 2026"}],
        expected_contradictions=[{"id": "price-gap", "pattern": r"price"}],
    )
    base.update(over)
    return Case(**base)


def test_score_counts_recall_invention_and_coherence():
    s = score(make_case(), sample_report(), TRACE)
    assert s.recall == pytest.approx(2 / 3)
    assert s.expected_found == ["verified", "volume"] and s.expected_missing == ["missing"]
    assert s.found_by_expected_agent == 2
    assert s.unsourced_claims == ["market-1"]
    assert s.unseen_source_claims == []  # sourcify.dev appears in the trace
    assert s.forbidden_hits == [] and s.invention_failures == 1
    assert s.coherence == 0.0 and s.contradictions_expected == 1
    assert s.neutrality_violations == 0 and s.claims == 2


def test_a_source_no_tool_reached_is_an_invention():
    s = score(make_case(), sample_report(), [])
    assert s.unseen_source_claims == ["onchain-1"]
    assert s.invention_failures == 2


def test_forbidden_statement_is_counted():
    case = make_case(forbidden_facts=[{"id": "vol", "pattern": r"10 million USD"}])
    s = score(case, sample_report(), TRACE)
    assert s.forbidden_hits == ["vol"] and s.invention_failures == 2


def test_summary_and_markdown():
    scores = [score(make_case(), sample_report(), TRACE),
              score(make_case(id="euler", category="exploit", expected_contradictions=[]),
                    sample_report(), TRACE)]
    summary = summarise(scores, "2026-10-11")
    assert summary["cases"] == 2 and summary["mode"] == "multi_agent"
    assert summary["invention_free_cases"] == 0 and summary["facts_found"] == 4
    assert summary["coherence_mean"] == pytest.approx(0.5)
    assert set(summary["by_category"]) == {"healthy", "exploit"}
    md = to_markdown(summary, scores)
    assert "| euler | exploit |" in md and "Cases free of invention | 0/2" in md
    assert chr(0x2014) not in md


def test_hosts_reached_and_trace_reader(tmp_path):
    assert hosts_reached(TRACE) == {"sourcify.dev"}
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in TRACE) + "\n\n", encoding="utf-8")
    assert read_trace(p) == TRACE and read_trace(tmp_path / "none.jsonl") == []


def test_load_case_rejects_bad_files(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("id: x\nquery: x\ncategory: weird\ntruth_date: '2026-10-11'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="category"):
        load_case(p)
    p.write_text("id: x\nquery: x\ncategory: healthy\ntruth_date: '2026-10-11'\n"
                 "expected_facts:\n  - id: a\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pattern"):
        load_case(p)
    p.write_text("id: x\nquery: x\ncategory: healthy\ntruth_date: '2026-10-11'\nextra: 1\n",
                 encoding="utf-8")
    with pytest.raises(ValueError, match="unknown keys"):
        load_case(p)


def test_the_twenty_truth_sheets_are_well_formed():
    cases = load_cases(CASES_DIR)
    assert len(cases) == 20
    assert Counter(c.category for c in cases) == {"healthy": 8, "exploit": 6, "abandoned": 3,
                                                  "sensitive": 3}
    assert len({c.id for c in cases}) == 20
    for c in cases:
        assert c.truth_date.startswith("2026-"), c.id
        assert len(c.expected_facts) >= 4 and c.sources and c.checks, c.id
        assert all(f.get("agent") in ("onchain", "market", "docs", "incidents")
                   for f in c.expected_facts), c.id
        assert all(s.get("url") and s.get("accessed") for s in c.sources), c.id
        text = Path(c.path).read_text(encoding="utf-8")
        assert chr(0x2014) not in text, c.id
    assert set(CATEGORIES) == {"healthy", "exploit", "abandoned", "sensitive"}


def test_cases_say_nothing_about_buying_or_selling():
    bad = ("buy", "sell", "hold", "invest", "bullish", "bearish", "price target")
    for p in CASES_DIR.glob("*.yaml"):
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        text = json.dumps(data).lower()
        for w in bad:
            assert f" {w} " not in text and f" {w}." not in text, (p.name, w)


def test_runner_dry_run_lists_the_cases(capsys):
    sys.path.insert(0, str(EVALS_DIR))
    try:
        import run as evals_run
    finally:
        sys.path.pop(0)
    assert evals_run.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("20 cases:") and "no model called" in out
