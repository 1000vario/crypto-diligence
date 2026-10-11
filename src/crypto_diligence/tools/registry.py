"""Tool specifications per agent and the dispatcher that runs them.

Schemas are strict (every property required, no extras) so the model cannot invent
parameters; optional values are nullable instead.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from ..providers.base import ToolSpec
from . import docs, incidents, market, onchain
from .context import ToolContext
from .http import ToolError

ToolFn = Callable[..., Awaitable[dict[str, Any]]]


def _schema(props: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


ADDRESS = {
    "type": "string",
    "description": "EVM contract address, 0x followed by 40 hex characters",
}

_SPECS: dict[str, tuple[ToolSpec, ToolFn | None]] = {}


def _register(name: str, description: str, props: dict[str, dict[str, Any]], fn: ToolFn) -> None:
    _SPECS[name] = (ToolSpec(name=name, description=description, input_schema=_schema(props)), fn)


_register(
    "get_contract_source",
    "Verification status of a contract on Sourcify and, when a key is configured, Etherscan "
    "(contract name, compiler, licence, proxy flag).",
    {"address": ADDRESS, "chain_id": {"type": "integer", "description": "1 for Ethereum mainnet"}},
    onchain.get_contract_source,
)
_register(
    "analyze_bytecode",
    "Read the deployed bytecode: size, sensitive function selectors present (mint, pause, "
    "blacklist, upgrade, owner), proxy pattern and implementation address, owner() and "
    "paused() values. Follows the implementation of a proxy.",
    {"address": ADDRESS},
    onchain.analyze_bytecode,
)
_register(
    "get_token_metadata",
    "name, symbol, decimals and totalSupply read from the token contract over JSON-RPC.",
    {"address": ADDRESS},
    onchain.get_token_metadata,
)
_register(
    "get_contract_creation",
    "Creation transaction, creator and date of a contract (needs ETHERSCAN_API_KEY).",
    {"address": ADDRESS, "chain_id": {"type": "integer", "description": "1 for Ethereum mainnet"}},
    onchain.get_contract_creation,
)
_register(
    "get_token_holders",
    "Top token holders with their share of supply and whether each is a contract "
    "(Ethereum mainnet, Ethplorer).",
    {"address": ADDRESS,
     "limit": {"type": "integer", "description": "number of holders, 1 to 100"}},
    onchain.get_token_holders,
)
_register(
    "coingecko_search",
    "Find CoinGecko coin ids by name or symbol.",
    {"query": {"type": "string", "description": "name or symbol"}},
    market.coingecko_search,
)
_register(
    "coingecko_coin",
    "CoinGecko coin page: price, market cap, volume, supply, ATH/ATL with dates, links, "
    "developer data. lookup is 'id' (CoinGecko id) or 'contract' (Ethereum address).",
    {"id_or_address": {"type": "string", "description": "CoinGecko id or Ethereum address"},
     "lookup": {"type": "string", "enum": ["id", "contract"]}},
    market.coingecko_coin,
)
_register(
    "coingecko_market_chart",
    "Price and volume history summary over N days (first, last, min, max with dates, "
    "change, max drawdown, sampled points).",
    {"coin_id": {"type": "string", "description": "CoinGecko id"},
     "days": {"type": "integer", "description": "1 to 365, use 90 by default"}},
    market.coingecko_market_chart,
)
_register(
    "defillama_search",
    "Find DeFiLlama protocol slugs by name, symbol or CoinGecko id.",
    {"query": {"type": "string", "description": "name, symbol or CoinGecko id"}},
    market.defillama_search,
)
_register(
    "defillama_protocol",
    "DeFiLlama protocol page: TVL now and 90 days ago, chains, category, audits and audit "
    "links, dated hallmarks (events), listing date.",
    {"slug": {"type": "string", "description": "DeFiLlama slug"}},
    market.defillama_protocol,
)
_register(
    "defillama_price",
    "Current price of a token from DeFiLlama's coins service (second price source).",
    {"address": ADDRESS, "chain": {"type": "string", "description": "chain name, e.g. ethereum"}},
    market.defillama_price,
)
_register(
    "dexscreener_token",
    "DEX trading pairs of a token: price per venue, liquidity, 24h volume, pair age "
    "(third price source and liquidity check).",
    {"address": ADDRESS},
    market.dexscreener_token,
)
_register(
    "fetch_page",
    "Fetch a public web page and return its text (HTML stripped, capped). Use it on project "
    "sites, documentation, audit reports, post-mortems, official statements and press.",
    {"url": {"type": "string", "description": "http(s) URL"},
     "max_chars": {"type": "integer", "description": "1000 to 40000"}},
    docs.fetch_page,
)
_register(
    "github_repo",
    "GitHub repository facts: creation and last push dates, stars, licence, archived flag, "
    "latest commit, contributor count.",
    {"owner_repo": {"type": "string", "description": "owner/repo or GitHub URL"}},
    docs.github_repo,
)
_register(
    "github_search_repos",
    "Search GitHub repositories by keywords.",
    {"query": {"type": "string", "description": "search keywords"}},
    docs.github_search_repos,
)
_register(
    "defillama_hacks",
    "Search DeFiLlama's public exploit database by protocol name: date, technique, amount, "
    "funds returned, source link.",
    {"name_filter": {"type": "string", "description": "protocol name or part of it"}},
    incidents.defillama_hacks,
)

WEB_SEARCH = ToolSpec(
    name="web_search",
    description="Provider-hosted web search.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    server="web_search",
)

TOOLSETS: dict[str, list[str]] = {
    "onchain": ["get_contract_source", "analyze_bytecode", "get_token_metadata",
                "get_contract_creation", "get_token_holders"],
    "market": ["coingecko_search", "coingecko_coin", "coingecko_market_chart",
               "defillama_search", "defillama_protocol", "defillama_price", "dexscreener_token"],
    "docs": ["fetch_page", "github_repo", "github_search_repos", "defillama_protocol",
             "web_search"],
    "incidents": ["defillama_hacks", "defillama_protocol", "fetch_page", "web_search"],
}
TOOLSETS["single"] = sorted({n for names in TOOLSETS.values() for n in names})


def tools_for(agent: str) -> list[ToolSpec]:
    out: list[ToolSpec] = []
    for name in TOOLSETS[agent]:
        out.append(WEB_SEARCH if name == "web_search" else _SPECS[name][0])
    return out


def all_specs() -> dict[str, ToolSpec]:
    return {name: spec for name, (spec, _) in _SPECS.items()}


async def run_tool(ctx: ToolContext, name: str, input: dict[str, Any]) -> tuple[str, bool]:
    """Run a tool; return (JSON text, is_error). Never raises."""
    entry = _SPECS.get(name)
    if entry is None or entry[1] is None:
        return json.dumps({"error": f"unknown tool {name!r}"}), True
    try:
        result = await entry[1](ctx, **input)
        return json.dumps(result, ensure_ascii=False, default=str), False
    except ToolError as exc:
        return json.dumps({"error": str(exc)}), True
    except TypeError as exc:
        return json.dumps({"error": f"bad arguments for {name}: {exc}"}), True
    except Exception as exc:  # noqa: BLE001  (reported to the model, kept in the trace)
        return json.dumps({"error": f"{name} failed: {exc.__class__.__name__}: {exc}"}), True
