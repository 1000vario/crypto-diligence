from crypto_diligence import neutrality
from crypto_diligence.orchestrator import cost_summary
from crypto_diligence.schemas import Claim, Finding, Identity, Quality, Report
from crypto_diligence.trace import Trace


def test_recommendations_are_caught():
    assert neutrality.find_violations("Investors should buy now, it is undervalued.")
    assert neutrality.find_violations("We recommend holding through Q4.")
    assert neutrality.find_violations("Analysts see a price target of 12 dollars.")
    assert neutrality.find_violations("This is not financial advice, but the chart is bullish.")


def test_facts_pass():
    for text in (
        "The contract exposes pause() and the owner can call it (bytecode scan, 2026-10-11).",
        "TVL fell from 2.1 billion USD to 0.4 billion USD between 2022-05-07 and 2022-05-13.",
        "The exploit of 2023-03-13 drained about 197 million USD; 240 million USD were returned.",
        "Audits by two firms are published; one reservation concerns the upgrade path.",
    ):
        assert neutrality.find_violations(text) == [], text


def test_check_report_locates_the_violation():
    claim = Claim(id="market-1", agent="market", text="The token looks like a strong buy.",
                  sources=[])
    report = Report(
        run_id="r", mode="multi_agent", generated_at="2026-10-11T00:00:00+00:00",
        identity=Identity(query="x"), findings={"market": Finding(agent="market", claims=[claim])},
        claims=[claim], contradictions=[], quality=Quality(), cost=cost_summary(Trace()),
        duration_s=0.0,
        provider="replay", models={},
    )
    found = neutrality.check_report(report)
    assert len(found) == 1 and "market-1" in found[0]["where"]
