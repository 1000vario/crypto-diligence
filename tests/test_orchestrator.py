import json

import pytest
from conftest import UNI
from helpers import contradictions_json, finding_json, turn

from crypto_diligence.orchestrator import new_run_id, run_report
from crypto_diligence.providers.replay import ReplayProvider
from crypto_diligence.report import to_json, to_markdown
from crypto_diligence.schemas import AGENT_NAMES, Identity, Report

IDENTITY = Identity(query="Uniswap", resolved=True, name="Uniswap", symbol="UNI",
                    address=UNI.lower(), coingecko_id="uniswap", defillama_slug="uniswap")
PER_TURN = 1000 / 1e6 * 4 + 200 / 1e6 * 20


async def test_multi_agent_report(settings, ctx, tmp_path):
    turns = {f"{a}:1": [turn(text=finding_json(a, unsourced=(a == "market")))]
             for a in AGENT_NAMES}
    turns["onchain:1"] = [turn(tool_calls=[{"id": "t1", "name": "get_token_metadata",
                                            "input": {"address": UNI}}], stop="tool_use")]
    turns["onchain:2"] = [turn(text=finding_json("onchain"))]
    turns["orchestrator:1"] = [turn(text=contradictions_json(["market-1", "market-2"]))]
    provider = ReplayProvider({"recorded": False, "turns": turns})

    report = await run_report("Uniswap", settings, provider=provider, identity=IDENTITY,
                              trace_dir=tmp_path, today="2026-10-11")

    assert report.mode == "multi_agent" and list(report.findings) == list(AGENT_NAMES)
    assert [c.id for c in report.claims] == [f"{a}-{n}" for a in AGENT_NAMES for n in (1, 2)]
    assert report.quality.unsourced_claim_ids == ["market-2"]
    assert report.quality.agents_failed == [] and report.quality.neutrality_violations == []
    assert len(report.contradictions) == 1
    assert report.contradictions[0].claim_ids == ["market-1", "market-2"]
    assert report.cost.model_calls == 6 and report.cost.tool_calls == 1
    assert report.cost.total_usd == pytest.approx(6 * PER_TURN)
    assert set(report.cost.by_agent_usd) == set(AGENT_NAMES) | {"orchestrator"}
    assert report.models == {"orchestrator": "claude-opus-5-5", "subagent": "claude-opus-5-5"}
    # every investigator saw only its own tools
    seen = {r["tag"].split(":")[0]: r["tools"] for r in provider.requests}
    assert "analyze_bytecode" in seen["onchain"] and "analyze_bytecode" not in seen["market"]
    assert seen["orchestrator"] == []
    # trace on disk, in order
    kinds = [json.loads(line)["kind"]
             for line in open(report.trace_path, encoding="utf-8")]
    assert kinds[:2] == ["run_start", "query"] and kinds[-1] == "report"
    assert kinds.count("model_call") == 6
    # renderers
    assert Report.model_validate_json(to_json(report)) == report
    assert "market-2" in to_markdown(report)


async def test_single_agent_mode_and_a_crashed_contradiction_pass(settings, ctx, tmp_path):
    turns = {"single:1": [turn(text=finding_json("single"))],
             "orchestrator:1": [turn(text="no json here")]}
    provider = ReplayProvider({"recorded": False, "turns": turns})
    report = await run_report("Uniswap", settings, mode="single_agent", provider=provider,
                              identity=IDENTITY, trace_dir=tmp_path, today="2026-10-11")
    assert list(report.findings) == ["single"]
    assert [c.id for c in report.claims] == ["single-1", "single-2"]
    assert report.contradictions == []
    assert any("contradiction" in n.lower() for n in report.orchestrator_notes)


async def test_failed_investigator_is_recorded(settings, ctx, tmp_path):
    turns = {f"{a}:1": [turn(text=finding_json(a))] for a in AGENT_NAMES if a != "docs"}
    turns["orchestrator:1"] = [turn(text=contradictions_json([]))]
    provider = ReplayProvider({"recorded": False, "turns": turns})
    report = await run_report("Uniswap", settings, provider=provider, identity=IDENTITY,
                              trace_dir=tmp_path, today="2026-10-11")
    assert report.quality.agents_failed == ["docs"]
    assert report.findings["docs"].failed and len(report.claims) == 6


def test_run_ids_are_dated_and_unique():
    a, b = new_run_id("2026-10-11"), new_run_id("2026-10-11")
    assert a.startswith("20261011-") and a != b


async def test_unknown_mode(settings):
    with pytest.raises(ValueError):
        await run_report("x", settings, mode="duo")
