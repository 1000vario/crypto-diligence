"""Run the evals: one report per case, scored against its truth sheet, rates published.

    python evals/run.py --mode multi_agent              # the four investigators
    python evals/run.py --mode single_agent             # one agent with every tool
    python evals/run.py --cases euler usdc --max-usd 5  # a subset, with a budget stop
    python evals/run.py --dry-run                       # validate the cases, call no model
    python evals/run.py --from-results evals/results/20261011-multi_agent  # rescore only

Every run writes `evals/results/<date>-<mode>/<case>.json` and `.md` (the reports), the
traces under `traces/`, then `evals/results/<date>-<mode>.json` and `.md` (the rates).
Each model call costs money: the run stops when the cumulated cost exceeds --max-usd.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from crypto_diligence.config import Settings, load_dotenv
from crypto_diligence.evals import (
    CATEGORIES,
    Case,
    CaseScore,
    load_cases,
    read_trace,
    score,
    summarise,
    to_markdown,
)
from crypto_diligence.orchestrator import run_report
from crypto_diligence.report import to_json
from crypto_diligence.report import to_markdown as report_markdown
from crypto_diligence.schemas import Report
from crypto_diligence.tools import http

ROOT = Path(__file__).resolve().parent


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def rescore(cases: list[Case], results_dir: Path) -> list[CaseScore]:
    scores = []
    for case in cases:
        path = results_dir / f"{case.id}.json"
        if not path.is_file():
            print(f"{case.id}: no saved report in {results_dir}, skipped", file=sys.stderr)
            continue
        report = Report.model_validate_json(path.read_text(encoding="utf-8"))
        trace = read_trace(results_dir / "traces" / f"{report.run_id}.jsonl")
        scores.append(score(case, report, trace))
    return scores


async def run(cases: list[Case], settings: Settings, mode: str, results_dir: Path,
              max_usd: float, pause_s: float) -> list[CaseScore]:
    scores: list[CaseScore] = []
    spent = 0.0
    for i, case in enumerate(cases, 1):
        if spent > max_usd:
            print(f"budget: {spent:.2f} USD spent, above --max-usd {max_usd}; stopping before "
                  f"{case.id}", file=sys.stderr)
            break
        t0 = time.monotonic()
        try:
            report = await run_report(case.query, settings, mode=mode,
                                      trace_dir=results_dir / "traces")
        except Exception as exc:  # noqa: BLE001  (one failed case must not lose the others)
            print(f"{case.id}: report failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
            continue
        _write(results_dir / f"{case.id}.json", to_json(report))
        _write(results_dir / f"{case.id}.md", report_markdown(report))
        s = score(case, report, read_trace(report.trace_path))
        scores.append(s)
        spent += s.cost_usd or 0.0
        print(f"[{i}/{len(cases)}] {case.id:14} recall {s.recall:.2f}  invention "
              f"{s.invention_failures}  coherence {s.coherence:.2f}  neutrality "
              f"{s.neutrality_violations}  claims {s.claims}  {s.cost_usd or 0:.3f} USD  "
              f"{time.monotonic() - t0:.0f} s  (run total {spent:.2f} USD)")
        if i < len(cases):
            await asyncio.sleep(pause_s)
    return scores


def publish(scores: list[CaseScore], results_dir: Path, date: str) -> None:
    summary = summarise(scores, date)
    doc = {"summary": summary, "cases": [asdict(s) for s in scores]}
    _write(results_dir.with_suffix(".json"), json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    _write(results_dir.with_suffix(".md"), to_markdown(summary, scores))
    print()
    print(to_markdown(summary, scores))
    print("written:", results_dir.with_suffix(".json"), "and", results_dir.with_suffix(".md"))


def dry_run(cases: list[Case]) -> int:
    counts = {c: sum(1 for x in cases if x.category == c) for c in CATEGORIES}
    print(f"{len(cases)} cases:", ", ".join(f"{k} {v}" for k, v in counts.items()))
    for case in cases:
        print(f"  {case.id:14} {case.category:9} truth {case.truth_date}  "
              f"{len(case.expected_facts)} expected, {len(case.forbidden_facts)} forbidden, "
              f"{len(case.expected_contradictions)} contradictions, {len(case.checks)} checks")
    print("no model called; cost per report is measured only by a real run")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["multi_agent", "single_agent"], default="multi_agent")
    ap.add_argument("--cases", nargs="*", help="case ids (default: all)")
    ap.add_argument("--cases-dir", type=Path, default=ROOT / "cases")
    ap.add_argument("--results-dir", type=Path, default=ROOT / "results")
    ap.add_argument("--max-usd", type=float, default=60.0, help="stop above this spend")
    ap.add_argument("--pause", type=float, default=5.0, help="seconds between cases")
    ap.add_argument("--env", default=".env")
    ap.add_argument("--dry-run", action="store_true", help="validate the cases, call no model")
    ap.add_argument("--from-results", type=Path,
                    help="rescore the reports saved in this directory, call no model")
    a = ap.parse_args(argv)

    cases = load_cases(a.cases_dir, a.cases)
    if not cases:
        print("no case matched", file=sys.stderr)
        return 2
    if a.dry_run:
        return dry_run(cases)
    if a.from_results:
        scores = rescore(cases, a.from_results)
        publish(scores, a.from_results, datetime.now(UTC).date().isoformat())
        return 0 if scores else 1

    load_dotenv(a.env)
    settings = Settings.from_env()
    date = datetime.now(UTC).date().isoformat()
    results_dir = a.results_dir / f"{date}-{a.mode}"

    async def go() -> list[CaseScore]:
        try:
            return await run(cases, settings, a.mode, results_dir, a.max_usd, a.pause)
        finally:
            await http.aclose()

    scores = asyncio.run(go())
    if not scores:
        print("no report produced", file=sys.stderr)
        return 1
    publish(scores, results_dir, date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
