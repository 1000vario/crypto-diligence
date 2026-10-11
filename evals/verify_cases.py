"""Run each case's deterministic checks against the live public APIs and keep the answers.

No model is involved. Every case lists `checks`, the tool calls whose answers back its truth
sheet; this script runs them and writes `evals/evidence/<case id>.json` with the access date,
so the facts in `evals/cases/*.yaml` can be traced to what the sources said on that day.

    python evals/verify_cases.py            # all cases
    python evals/verify_cases.py euler usdc # some cases
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from crypto_diligence.config import Settings, load_dotenv
from crypto_diligence.evals import load_cases
from crypto_diligence.tools import http
from crypto_diligence.tools.context import ToolContext
from crypto_diligence.tools.registry import run_tool

ROOT = Path(__file__).resolve().parent
PAUSE_S = 2.0
# CoinGecko's free tier throttles bursts: a long pause after each of its calls.
PAUSES_S = {"coingecko_search": 12.0, "coingecko_coin": 12.0, "coingecko_market_chart": 12.0}
MAX_OUTPUT_CHARS = 12_000


async def main(case_ids: list[str], cases_dir: Path, evidence_dir: Path) -> int:
    load_dotenv()
    settings = Settings.from_env()
    ctx = ToolContext(settings)
    cases = load_cases(cases_dir, case_ids or None)
    if not cases:
        print("no case matched", file=sys.stderr)
        return 2
    evidence_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for case in cases:
        results = []
        for chk in case.checks:
            text, is_error = await run_tool(ctx, chk["tool"], chk.get("input") or {})
            try:
                output = json.loads(text) if not is_error else text
            except json.JSONDecodeError:
                output = text
            if isinstance(output, str) and len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + "..."
            results.append({"tool": chk["tool"], "input": chk.get("input") or {},
                            "ok": not is_error, "output": output})
            flag = "ok " if not is_error else "ERR"
            print(f"{case.id:14} {flag} {chk['tool']}({json.dumps(chk.get('input') or {})})"
                  + ("" if not is_error else f": {text[:160]}"))
            failures += int(is_error)
            await asyncio.sleep(PAUSES_S.get(chk["tool"], PAUSE_S))
        doc = {"case": case.id, "query": case.query, "category": case.category,
               "accessed": datetime.now(UTC).date().isoformat(), "results": results}
        (evidence_dir / f"{case.id}.json").write_text(
            json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    await http.aclose()
    print(f"{len(cases)} cases, {failures} failed checks, evidence in {evidence_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cases", nargs="*", help="case ids (default: all)")
    ap.add_argument("--cases-dir", type=Path, default=ROOT / "cases")
    ap.add_argument("--evidence-dir", type=Path, default=ROOT / "evidence")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.cases, a.cases_dir, a.evidence_dir)))
