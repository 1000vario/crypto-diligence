"""Price table used to compute the cost of a report from exact token usage.

Prices are USD per million tokens. The table was checked on PRICING_DATE against the
Anthropic model documentation; override or extend it with a JSON file (CD_PRICING_JSON)
of the same shape, for example to price an OpenAI model. An unknown model yields a cost of
None, never a guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .schemas import Usage

PRICING_DATE = "2026-10-11"
WEB_SEARCH_USD_PER_1000 = 10.0


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float
    cache_write: float


# cache_write is the 5-minute TTL write price (1.25 x input).
DEFAULT_TABLE: dict[str, Price] = {
    "claude-opus-5-5": Price(4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": Price(2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": Price(0.10, 0.50, 0.01, 0.125),
    "claude-fable-5-1": Price(10.0, 50.0, 0.25, 12.5),
}

_TABLE: dict[str, Price] | None = None
_NOTE = "Prices per MTok checked on " + PRICING_DATE + "; web search billed per request."


def load_table(extra: Path | None = None) -> dict[str, Price]:
    global _TABLE
    table = dict(DEFAULT_TABLE)
    if extra is not None and extra.is_file():
        raw = json.loads(extra.read_text(encoding="utf-8"))
        for model, p in raw.items():
            table[model] = Price(
                float(p["input"]),
                float(p["output"]),
                float(p.get("cache_read", p["input"] * 0.1)),
                float(p.get("cache_write", p["input"] * 1.25)),
            )
    _TABLE = table
    return table


def table() -> dict[str, Price]:
    return _TABLE if _TABLE is not None else load_table()


def note() -> str:
    return _NOTE


def cost_usd(model: str, usage: Usage) -> float | None:
    p = table().get(model)
    if p is None:
        return None
    m = 1_000_000
    total = (
        usage.input_tokens * p.input / m
        + usage.output_tokens * p.output / m
        + usage.cache_read_tokens * p.cache_read / m
        + usage.cache_write_tokens * p.cache_write / m
        + usage.web_search_requests * WEB_SEARCH_USD_PER_1000 / 1000
    )
    return round(total, 6)
