"""Pydantic models shared by agents, orchestrator, report, service and evals."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from . import DISCLAIMER

Confidence = Literal["high", "medium", "low"]
Severity = Literal["high", "medium", "low"]
Mode = Literal["multi_agent", "single_agent"]

AGENT_NAMES = ("onchain", "market", "docs", "incidents")

# Tag vocabulary per agent. Tags make eval recall deterministic: an expected fact is a tag
# plus a regular expression over the claim text.
TAGS: dict[str, list[str]] = {
    "onchain": [
        "verified", "unverified", "proxy", "not_proxy", "owner", "mint", "pause", "blacklist",
        "upgrade", "holders", "age", "supply", "metadata", "other",
    ],
    "market": [
        "price", "volume", "liquidity", "market_cap", "tvl", "history", "discrepancy",
        "listing", "other",
    ],
    "docs": [
        "whitepaper", "documentation", "github", "activity", "contributors", "license",
        "audit", "audit_reservation", "team_identified", "team_anonymous", "other",
    ],
    "incidents": [
        "exploit", "depeg", "suspension", "regulator", "complaint", "bankruptcy", "funds_returned",
        "no_incident_found", "other",
    ],
}


class Source(BaseModel):
    """Where a claim comes from. `accessed` is the date the source was read (YYYY-MM-DD)."""

    url: str
    accessed: str
    title: str | None = None
    note: str | None = None


class Claim(BaseModel):
    """One dated, sourced statement with a three-level confidence."""

    id: str = ""
    agent: str = ""
    text: str
    tags: list[str] = Field(default_factory=list)
    confidence: Confidence = "low"
    date: str | None = None
    sources: list[Source] = Field(default_factory=list)
    unsourced: bool = False


class Finding(BaseModel):
    """Output of one sub-agent. No free-text summary: everything is a claim or a question."""

    agent: str
    claims: list[Claim] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    tool_errors: list[str] = Field(default_factory=list)
    failed: bool = False
    failure_reason: str | None = None


class Contradiction(BaseModel):
    topic: str
    claim_ids: list[str] = Field(default_factory=list)
    description: str
    severity: Severity = "medium"


class Identity(BaseModel):
    """What the orchestrator resolved from the user query, before any investigation."""

    query: str
    resolved: bool = False
    name: str | None = None
    symbol: str | None = None
    chain: str = "ethereum"
    chain_id: int = 1
    address: str | None = None
    coingecko_id: str | None = None
    defillama_slug: str | None = None
    defillama_parent: str | None = None
    github: list[str] = Field(default_factory=list)
    website: str | None = None
    notes: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_search_requests: int = 0

    def add(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            web_search_requests=self.web_search_requests + other.web_search_requests,
        )


class ModelCallRecord(BaseModel):
    agent: str
    provider: str
    model: str
    turn: int
    usage: Usage
    cost_usd: float | None
    stop_reason: str
    duration_ms: int


class ToolCallRecord(BaseModel):
    agent: str
    tool: str
    input: dict[str, Any]
    output_excerpt: str
    output_chars: int
    output_tokens_estimate: int
    is_error: bool
    duration_ms: int
    server_side: bool = False


class CostSummary(BaseModel):
    total_usd: float | None
    by_agent_usd: dict[str, float | None]
    model_calls: int
    tool_calls: int
    web_search_requests: int
    usage: Usage
    pricing_date: str
    pricing_note: str


class Quality(BaseModel):
    """Measured on the finished report; the same checks feed the evals."""

    unsourced_claim_ids: list[str] = Field(default_factory=list)
    neutrality_violations: list[dict[str, str]] = Field(default_factory=list)
    agents_failed: list[str] = Field(default_factory=list)


class Report(BaseModel):
    schema_version: str = "1"
    run_id: str
    mode: Mode
    generated_at: str
    identity: Identity
    findings: dict[str, Finding]
    claims: list[Claim]
    contradictions: list[Contradiction]
    orchestrator_notes: list[str] = Field(default_factory=list)
    quality: Quality
    cost: CostSummary
    duration_s: float
    provider: str
    models: dict[str, str]
    disclaimer: str = DISCLAIMER
    trace_path: str | None = None
