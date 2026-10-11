from helpers import sample_report

from crypto_diligence.report import to_json, to_markdown
from crypto_diligence.schemas import DISCLAIMER, Report


def test_markdown_opens_with_the_disclaimer_and_flags_unsourced_claims():
    md = to_markdown(sample_report())
    lines = md.splitlines()
    assert lines[0].startswith("# ")
    first_body = next(line for line in lines[1:] if line.strip())
    assert first_body.startswith("> ") and "not advice" in first_body
    assert "NO SOURCE" in md
    assert "onchain-1" in md and "https://sourcify.dev" in md
    assert "Which venue carries the volume?" in md
    assert chr(0x2014) not in md and "&mdash;" not in md


def test_json_round_trips():
    report = sample_report()
    back = Report.model_validate_json(to_json(report))
    assert back == report
    assert back.disclaimer == DISCLAIMER
