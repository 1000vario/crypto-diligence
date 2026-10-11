"""Neutrality check: a report must contain no recommendation. Checked by a pattern list."""

from __future__ import annotations

import re
from importlib import resources

from .schemas import Report

_PATTERNS: list[re.Pattern[str]] | None = None


def patterns() -> list[re.Pattern[str]]:
    global _PATTERNS
    if _PATTERNS is None:
        text = resources.files("crypto_diligence.data").joinpath("neutrality_patterns.txt")
        compiled: list[re.Pattern[str]] = []
        for raw in text.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            compiled.append(re.compile(line, re.IGNORECASE))
        _PATTERNS = compiled
    return _PATTERNS


def find_violations(text: str) -> list[str]:
    """Return the matched snippets found in `text`."""
    found: list[str] = []
    for pat in patterns():
        for m in pat.finditer(text):
            found.append(m.group(0))
    return found


def check_report(report: Report) -> list[dict[str, str]]:
    """Scan every model-written field of a report. The fixed disclaimer is not scanned."""
    violations: list[dict[str, str]] = []
    for claim in report.claims:
        for snippet in find_violations(claim.text):
            violations.append({"where": claim.id, "match": snippet})
    for agent, finding in report.findings.items():
        for i, q in enumerate(finding.open_questions):
            for snippet in find_violations(q):
                violations.append({"where": f"{agent}.open_questions[{i}]", "match": snippet})
    for i, c in enumerate(report.contradictions):
        for snippet in find_violations(c.description):
            violations.append({"where": f"contradictions[{i}]", "match": snippet})
    for i, note in enumerate(report.orchestrator_notes):
        for snippet in find_violations(note):
            violations.append({"where": f"orchestrator_notes[{i}]", "match": snippet})
    return violations
