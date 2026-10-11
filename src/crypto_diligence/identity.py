"""Deterministic identity resolution: from a name, symbol or address to the ids each source
uses (CoinGecko id, Ethereum address, DeFiLlama slug). No model involved; ambiguities are
written down in Identity.notes for the investigators and the reader."""

from __future__ import annotations

import re
from typing import Any

from .schemas import Identity
from .tools import market, onchain
from .tools.context import ToolContext
from .tools.http import ToolError

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _ranked(coins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(coins, key=lambda c: (c.get("market_cap_rank") is None,
                                        c.get("market_cap_rank") or 10**9))


def pick_coin(query: str, coins: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list]:
    """Exact symbol first, then exact name, then the best-ranked result."""
    q = query.strip().lower()
    for group in (
        [c for c in coins if (c.get("symbol") or "").lower() == q],
        [c for c in coins if (c.get("name") or "").lower() == q],
        list(coins),
    ):
        if group:
            ranked = _ranked(group)
            return ranked[0], ranked[1:4]
    return None, []


async def resolve_identity(query: str, ctx: ToolContext) -> Identity:
    q = query.strip()
    ident = Identity(query=q)
    coin: dict[str, Any] | None = None
    if ADDRESS_RE.match(q):
        ident.address = q.lower()
        try:
            coin = await market.coingecko_coin(ctx, ident.address, lookup="contract")
        except ToolError as exc:
            ident.notes.append(f"CoinGecko has no page for this contract ({exc})")
            try:
                meta = await onchain.get_token_metadata(ctx, ident.address)
                ident.name = meta.get("name")
                ident.symbol = meta.get("symbol")
            except ToolError as exc2:
                ident.notes.append(f"token metadata unreadable ({exc2})")
    else:
        try:
            found = await market.coingecko_search(ctx, q)
            best, others = pick_coin(q, found["coins"])
            if best is None:
                ident.notes.append("CoinGecko search returned nothing for this query")
            else:
                if others:
                    ident.notes.append(
                        "other CoinGecko matches, not investigated: "
                        + "; ".join(f"{c.get('name')} ({c.get('symbol')}, id {c.get('id')})"
                                    for c in others)
                    )
                if best.get("market_cap_rank") is None:
                    ident.notes.append("CoinGecko match has no market cap rank: weak match, "
                                       "check the name and the chain before trusting it")
                coin = await market.coingecko_coin(ctx, best["id"], lookup="id")
        except ToolError as exc:
            ident.notes.append(f"CoinGecko unavailable ({exc})")
    if coin:
        ident.coingecko_id = coin.get("id")
        ident.name = coin.get("name") or ident.name
        ident.symbol = (coin.get("symbol") or ident.symbol or "").upper() or None
        platforms = coin.get("platforms") or {}
        if not ident.address:
            eth = platforms.get("ethereum")
            if isinstance(eth, str) and ADDRESS_RE.match(eth):
                ident.address = eth.lower()
            elif platforms:
                shown = ", ".join(f"{k}: {v}" for k, v in list(platforms.items())[:5])
                ident.notes.append(f"no Ethereum mainnet contract on CoinGecko; platforms: {shown}")
            else:
                ident.notes.append("CoinGecko lists no contract for this asset (native coin or "
                                   "off-chain)")
        links = coin.get("links") or {}
        homepage = links.get("homepage") or []
        ident.website = homepage[0] if homepage else None
        ident.github = list(links.get("github") or [])
    try:
        for candidate in (ident.coingecko_id, ident.name, q):
            if not candidate:
                continue
            matches = (await market.defillama_search(ctx, candidate))["matches"]
            if not matches:
                continue
            best = None
            if ident.coingecko_id:
                best = next((m for m in matches if m.get("gecko_id") == ident.coingecko_id), None)
            if best is None:
                best = next((m for m in matches
                             if (m.get("name") or "").lower() == candidate.lower()), None)
            if best is None and candidate == q:
                best = matches[0]
                ident.notes.append(f"DeFiLlama match by search only: {best.get('name')}")
            if best:
                ident.defillama_slug = best.get("slug")
                ident.defillama_parent = best.get("parent_protocol")
                addr = str(best.get("address") or "").removeprefix("ethereum:")
                if not ident.address and ADDRESS_RE.match(addr):
                    ident.address = addr.lower()
                    ident.notes.append("Ethereum address taken from DeFiLlama's protocol "
                                       "list, not from CoinGecko")
                break
    except ToolError as exc:
        ident.notes.append(f"DeFiLlama search unavailable ({exc})")
    ident.resolved = bool(ident.coingecko_id or ident.address)
    return ident
