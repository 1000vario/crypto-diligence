"""Builders for synthetic turns, findings and reports used across the tests."""

from __future__ import annotations

import json
from typing import Any

from crypto_diligence.orchestrator import cost_summary
from crypto_diligence.schemas import Claim, Finding, Identity, Quality, Report, Source
from crypto_diligence.trace import Trace

RPC = "https://ethereum-rpc.publicnode.com"


def turn(text: str = "", tool_calls: list[dict[str, Any]] | None = None,
         stop: str = "end_turn", input_tokens: int = 1000, output_tokens: int = 200) -> dict:
    return {
        "text": text, "tool_calls": tool_calls or [], "stop_reason": stop,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "raw_assistant": None, "server_tool_events": [],
    }


def finding_json(agent: str, unsourced: bool = False) -> str:
    claims = [
        {"text": f"{agent}: fact one, read from a tool in this conversation.",
         "tags": ["contract"], "confidence": "high", "date": "2026-10-11",
         "sources": [{"url": RPC, "title": "JSON-RPC", "note": ""}]},
        {"text": f"{agent}: fact two, with a dated source.",
         "tags": ["price"], "confidence": "medium", "date": "",
         "sources": [] if unsourced else
         [{"url": "https://api.coingecko.com/api/v3/coins/uniswap", "title": "", "note": ""}]},
    ]
    return json.dumps({"claims": claims, "open_questions": [f"{agent}: what remains open?"]})


def contradictions_json(claim_ids: list[str]) -> str:
    return json.dumps({
        "contradictions": [{"topic": "price", "claim_ids": claim_ids,
                            "description": "Two sources give prices 3 percent apart.",
                            "severity": "low"}],
        "notes": ["one contradiction flagged, none smoothed"],
    })


def sample_report(query: str = "Uniswap", run_id: str = "20261011-deadbeef") -> Report:
    c1 = Claim(id="onchain-1", agent="onchain", text="The contract is verified on Sourcify.",
               tags=["contract"], confidence="high", date="2026-10-11",
               sources=[Source(url="https://sourcify.dev/server/v2/contract/1/0x1f98",
                               accessed="2026-10-11", title="Sourcify")])
    c2 = Claim(id="market-1", agent="market", text="Volume was 10 million USD on 2026-10-10.",
               tags=["volume"], confidence="medium", date="2026-10-10", sources=[],
               unsourced=True)
    findings = {"onchain": Finding(agent="onchain", claims=[c1]),
                "market": Finding(agent="market", claims=[c2],
                                  open_questions=["Which venue carries the volume?"])}
    report = Report(
        run_id=run_id, mode="multi_agent", generated_at="2026-10-11T12:00:00+00:00",
        identity=Identity(query=query, resolved=True, name="Uniswap", symbol="UNI",
                          coingecko_id="uniswap"),
        findings=findings, claims=[c1, c2], contradictions=[], quality=Quality(),
        cost=cost_summary(Trace()),
        duration_s=12.5, provider="replay", models={"orchestrator": "x", "subagent": "x"},
    )
    report.quality.unsourced_claim_ids = ["market-1"]
    return report
