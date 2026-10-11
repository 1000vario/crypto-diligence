import json

import pytest
from conftest import UNI
from helpers import finding_json, turn

from crypto_diligence.agents.base import extract_json, parse_finding, run_agent
from crypto_diligence.agents.prompts import PROMPTS
from crypto_diligence.providers.replay import ReplayProvider
from crypto_diligence.tools.registry import tools_for
from crypto_diligence.trace import Trace

TODAY = "2026-10-11"


async def _run(cassette, ctx, settings, tmp_path, agent="onchain"):
    provider = ReplayProvider({"recorded": False, "note": "synthetic", "turns": cassette})
    trace = Trace(tmp_path / "trace.jsonl", run_id="test")
    finding = await run_agent(
        agent=agent, provider=provider, model="claude-opus-5-5", system=PROMPTS[agent],
        task="Investigate UNI", tools=tools_for(agent), ctx=ctx, trace=trace, settings=settings,
        today=TODAY,
    )
    return finding, trace, provider


async def test_tool_turn_then_answer(ctx, settings, tmp_path):
    cassette = {
        "onchain:1": [turn(tool_calls=[{"id": "t1", "name": "get_token_metadata",
                                        "input": {"address": UNI}}], stop="tool_use")],
        "onchain:2": [turn(text=finding_json("onchain", unsourced=True))],
    }
    finding, trace, provider = await _run(cassette, ctx, settings, tmp_path)
    assert not finding.failed and finding.tool_errors == []
    assert [c.unsourced for c in finding.claims] == [False, True]
    assert finding.claims[0].sources[0].accessed == TODAY
    assert finding.claims[1].date is None and finding.claims[0].date == TODAY
    assert finding.open_questions == ["onchain: what remains open?"]

    assert len(trace.model_calls) == 2 and len(trace.tool_calls) == 1
    rec = trace.tool_calls[0]
    assert rec.tool == "get_token_metadata" and not rec.is_error and "UNI" in rec.output_excerpt
    assert trace.model_calls[0].cost_usd == pytest.approx(1000 / 1e6 * 4 + 200 / 1e6 * 20)
    kinds = [json.loads(line)["kind"]
             for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert kinds.count("model_call") == 2 and kinds.count("tool_call") == 1
    # the second request carried the tool result back to the model
    assert provider.requests[1]["turns"] == 3


async def test_tool_error_is_reported_not_raised(ctx, settings, tmp_path):
    cassette = {
        "onchain:1": [turn(tool_calls=[{"id": "t1", "name": "get_token_metadata",
                                        "input": {"address": "not-an-address"}}],
                           stop="tool_use")],
        "onchain:2": [turn(text=finding_json("onchain"))],
    }
    finding, trace, _ = await _run(cassette, ctx, settings, tmp_path)
    assert not finding.failed
    assert trace.tool_calls[0].is_error and len(finding.tool_errors) == 1


async def test_exhausted_cassette_fails_the_investigator(ctx, settings, tmp_path):
    cassette = {"onchain:1": [turn(tool_calls=[{"id": "t1", "name": "get_token_metadata",
                                                "input": {"address": UNI}}], stop="tool_use")]}
    finding, trace, _ = await _run(cassette, ctx, settings, tmp_path)
    assert finding.failed and "model call failed" in finding.failure_reason
    assert finding.claims == []


async def test_refusal_and_bad_json(ctx, settings, tmp_path):
    finding, _, _ = await _run({"onchain:1": [turn(text="", stop="refusal")]},
                               ctx, settings, tmp_path)
    assert finding.failed and "refusal" in finding.failure_reason
    finding, _, _ = await _run({"onchain:1": [turn(text="I could not find anything.")]},
                               ctx, settings, tmp_path)
    assert finding.failed and "not JSON" in finding.failure_reason


def test_parse_finding_tolerates_fences_and_prose():
    text = "Here is the answer:\n```json\n" + finding_json("docs") + "\n```\nDone."
    assert extract_json(text)["claims"]
    finding = parse_finding("docs", text, TODAY)
    assert len(finding.claims) == 2 and not finding.failed
    bad = parse_finding("docs", json.dumps({"claims": [{"text": "x", "confidence": "sure",
                                                        "date": "last year", "sources": []}]}),
                        TODAY)
    assert bad.claims[0].confidence == "low" and bad.claims[0].date is None
