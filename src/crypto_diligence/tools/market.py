"""Market tools: CoinGecko, DeFiLlama, DexScreener. Responses are trimmed to what a report
needs; every result carries the URL it was read from."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .context import ToolContext, cached_json
from .http import ToolError, get_json

COINGECKO = "https://api.coingecko.com/api/v3"
LLAMA = "https://api.llama.fi"
LLAMA_COINS = "https://coins.llama.fi"
DEXSCREENER = "https://api.dexscreener.com/latest/dex"
PROTOCOLS_CACHE_S = 24 * 3600


def _cg_headers(ctx: ToolContext) -> dict[str, str] | None:
    key = ctx.settings.coingecko_api_key
    return {"x-cg-demo-api-key": key} if key else None


def _date(ms: float | int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(float(ms) / 1000, tz=UTC).date().isoformat()


def _iso_s(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat(timespec="seconds")


async def coingecko_search(ctx: ToolContext, query: str) -> dict[str, Any]:
    """Find CoinGecko ids by name or symbol."""
    url = f"{COINGECKO}/search"
    data = await get_json(url, params={"query": query}, headers=_cg_headers(ctx))
    coins = [
        {"id": c.get("id"), "name": c.get("name"), "symbol": c.get("symbol"),
         "market_cap_rank": c.get("market_cap_rank")}
        for c in (data.get("coins") or [])[:10]
    ]
    return {"source_url": f"{url}?query={query}", "coins": coins}


def trim_coin(c: dict[str, Any]) -> dict[str, Any]:
    md = c.get("market_data") or {}
    links = c.get("links") or {}
    dev = c.get("developer_data") or {}

    def usd(key: str) -> Any:
        v = md.get(key)
        return v.get("usd") if isinstance(v, dict) else v

    return {
        "id": c.get("id"),
        "symbol": c.get("symbol"),
        "name": c.get("name"),
        "asset_platform_id": c.get("asset_platform_id"),
        "platforms": {k: v for k, v in (c.get("platforms") or {}).items() if v},
        "genesis_date": c.get("genesis_date"),
        "market_cap_rank": c.get("market_cap_rank"),
        "categories": (c.get("categories") or [])[:8],
        "links": {
            "homepage": [h for h in (links.get("homepage") or []) if h][:3],
            "whitepaper": links.get("whitepaper") or None,
            "github": ((links.get("repos_url") or {}).get("github") or [])[:5],
            "twitter": links.get("twitter_screen_name") or None,
            "blockchain_sites": [b for b in (links.get("blockchain_site") or []) if b][:3],
        },
        "market": {
            "price_usd": usd("current_price"),
            "market_cap_usd": usd("market_cap"),
            "fully_diluted_valuation_usd": usd("fully_diluted_valuation"),
            "total_volume_24h_usd": usd("total_volume"),
            "circulating_supply": md.get("circulating_supply"),
            "total_supply": md.get("total_supply"),
            "max_supply": md.get("max_supply"),
            "ath_usd": usd("ath"),
            "ath_date": usd("ath_date"),
            "ath_change_pct": usd("ath_change_percentage"),
            "atl_usd": usd("atl"),
            "atl_date": usd("atl_date"),
            "change_24h_pct": md.get("price_change_percentage_24h"),
            "change_7d_pct": md.get("price_change_percentage_7d"),
            "change_30d_pct": md.get("price_change_percentage_30d"),
            "change_1y_pct": md.get("price_change_percentage_1y"),
        },
        "developer_data": {
            k: dev.get(k)
            for k in ("forks", "stars", "subscribers", "total_issues", "closed_issues",
                      "pull_requests_merged", "pull_request_contributors",
                      "commit_count_4_weeks")
        },
        "last_updated": c.get("last_updated"),
    }


async def coingecko_coin(ctx: ToolContext, id_or_address: str,
                         lookup: str = "id") -> dict[str, Any]:
    """Coin page by CoinGecko id (lookup="id") or by Ethereum contract (lookup="contract")."""
    if lookup == "contract":
        url = f"{COINGECKO}/coins/ethereum/contract/{id_or_address.strip().lower()}"
    elif lookup == "id":
        url = f"{COINGECKO}/coins/{id_or_address.strip().lower()}"
    else:
        raise ToolError("lookup must be 'id' or 'contract'")
    params = {"localization": "false", "tickers": "false", "community_data": "false",
              "sparkline": "false"}
    data = await get_json(url, params=params, headers=_cg_headers(ctx))
    out = trim_coin(data)
    out["source_url"] = url
    return out


def summarise_chart(data: dict[str, Any], days: int) -> dict[str, Any]:
    prices = data.get("prices") or []
    volumes = data.get("total_volumes") or []
    if not prices:
        raise ToolError("market_chart returned no prices")
    first_ts, first = prices[0]
    last_ts, last = prices[-1]
    lo = min(prices, key=lambda p: p[1])
    hi = max(prices, key=lambda p: p[1])
    peak = prices[0][1]
    max_dd = 0.0
    for _, p in prices:
        peak = max(peak, p)
        if peak > 0:
            max_dd = max(max_dd, (peak - p) / peak)
    vols = [v[1] for v in volumes]
    weekly = []
    step = max(1, len(prices) // 13)
    for i in range(0, len(prices), step):
        weekly.append({"date": _date(prices[i][0]), "price_usd": prices[i][1]})
    return {
        "days": days,
        "points": len(prices),
        "first": {"date": _date(first_ts), "price_usd": first},
        "last": {"date": _date(last_ts), "price_usd": last},
        "min": {"date": _date(lo[0]), "price_usd": lo[1]},
        "max": {"date": _date(hi[0]), "price_usd": hi[1]},
        "change_pct": round((last - first) / first * 100, 2) if first else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "mean_volume_usd": round(sum(vols) / len(vols), 2) if vols else None,
        "last_volume_usd": vols[-1] if vols else None,
        "sampled": weekly,
    }


async def coingecko_market_chart(ctx: ToolContext, coin_id: str, days: int = 90) -> dict[str, Any]:
    """Price and volume history summary over `days` (default 90)."""
    days = max(1, min(int(days), 365))
    url = f"{COINGECKO}/coins/{coin_id.strip().lower()}/market_chart"
    data = await get_json(url, params={"vs_currency": "usd", "days": days},
                          headers=_cg_headers(ctx))
    out = summarise_chart(data, days)
    out["source_url"] = f"{url}?vs_currency=usd&days={days}"
    return out


def trim_protocol(p: dict[str, Any]) -> dict[str, Any]:
    tvl_series = p.get("tvl") or []
    current = tvl_series[-1] if tvl_series else None
    ago = None
    if len(tvl_series) > 90:
        ago = tvl_series[-91]
    hallmarks = []
    for h in p.get("hallmarks") or []:
        if isinstance(h, list) and len(h) == 2:
            hallmarks.append({"date": _iso_s(h[0]), "text": h[1]})
    chain_tvls = p.get("currentChainTvls") or {}
    top_chains = sorted(
        ((k, v) for k, v in chain_tvls.items() if isinstance(v, (int, float)) and "-" not in k),
        key=lambda kv: -kv[1],
    )[:8]
    return {
        "name": p.get("name"),
        "slug": p.get("slug") or (p.get("id") or "").removeprefix("parent#") or None,
        "is_parent": bool(p.get("isParentProtocol")),
        "other_protocols": (p.get("otherProtocols") or [])[:12],
        "symbol": p.get("symbol"),
        "category": p.get("category"),
        "chains": (p.get("chains") or [k for k, _ in top_chains])[:10],
        "url": p.get("url"),
        "twitter": p.get("twitter"),
        "github": p.get("github"),
        "gecko_id": p.get("gecko_id"),
        "parent_protocol": p.get("parentProtocol"),
        "forked_from": p.get("forkedFrom"),
        "audits": p.get("audits"),
        "audit_links": p.get("audit_links"),
        "audit_note": p.get("audit_note"),
        "listed_at": _iso_s(p.get("listedAt")),
        "dead_from": p.get("deadFrom"),
        "description": (p.get("description") or "")[:600] or None,
        "tvl_current_usd": current.get("totalLiquidityUSD") if current else None,
        "tvl_date": _iso_s(current.get("date")) if current else None,
        "tvl_90d_ago_usd": ago.get("totalLiquidityUSD") if ago else None,
        "tvl_by_chain_usd": dict(top_chains),
        "hallmarks": hallmarks[:40],
    }


async def defillama_protocol(ctx: ToolContext, slug: str) -> dict[str, Any]:
    """DeFiLlama protocol page: TVL, chains, audits, hallmarks (dated events)."""
    url = f"{LLAMA}/protocol/{slug.strip().lower()}"
    data = await get_json(url, max_bytes=30_000_000)
    if isinstance(data, dict) and data.get("statusCode") == 400:
        raise ToolError(f"defillama: {data.get('message')}")
    out = trim_protocol(data)
    out["source_url"] = url
    return out


async def defillama_search(ctx: ToolContext, query: str) -> dict[str, Any]:
    """Find DeFiLlama slugs by name, symbol or CoinGecko id (list cached for a day)."""
    protocols = await cached_json(ctx, "defillama_protocols", f"{LLAMA}/protocols",
                                  PROTOCOLS_CACHE_S)
    q = query.strip().lower()
    hits = []
    for p in protocols:
        fields = [str(p.get(k) or "").lower() for k in ("name", "slug", "symbol", "gecko_id")]
        exact = q in fields
        if exact or any(q in f for f in fields if f):
            hits.append((0 if exact else 1, -(p.get("tvl") or 0), p))
    hits.sort(key=lambda t: (t[0], t[1]))
    out = []
    for _, _, p in hits[:10]:
        out.append({"name": p.get("name"), "slug": p.get("slug"), "symbol": p.get("symbol"),
                    "category": p.get("category"), "chains": (p.get("chains") or [])[:5],
                    "tvl_usd": p.get("tvl"), "gecko_id": p.get("gecko_id"),
                    "address": p.get("address"),
                    "parent_protocol": p.get("parentProtocol")})
    return {"source_url": f"{LLAMA}/protocols", "matches": out}


async def defillama_price(
    ctx: ToolContext, address: str, chain: str = "ethereum"
) -> dict[str, Any]:
    """Current price from DeFiLlama's coins service, with its own confidence figure."""
    key = f"{chain.strip().lower()}:{address.strip().lower()}"
    url = f"{LLAMA_COINS}/prices/current/{key}"
    data = await get_json(url)
    coin = (data.get("coins") or {}).get(key)
    if not coin:
        raise ToolError(f"defillama price: no entry for {key}")
    return {
        "source_url": url,
        "price_usd": coin.get("price"),
        "symbol": coin.get("symbol"),
        "decimals": coin.get("decimals"),
        "llama_confidence": coin.get("confidence"),
        "timestamp": _iso_s(coin.get("timestamp")),
    }


async def dexscreener_token(ctx: ToolContext, address: str) -> dict[str, Any]:
    """DEX pairs for a token: price per venue, liquidity, 24h volume, pair age."""
    url = f"{DEXSCREENER}/tokens/{address.strip().lower()}"
    data = await get_json(url)
    pairs = data.get("pairs") or []
    pairs.sort(key=lambda p: -((p.get("liquidity") or {}).get("usd") or 0))
    rows = []
    for p in pairs[:6]:
        liq = (p.get("liquidity") or {}).get("usd")
        rows.append({
            "chain": p.get("chainId"),
            "dex": p.get("dexId"),
            "url": p.get("url"),
            "base": (p.get("baseToken") or {}).get("symbol"),
            "quote": (p.get("quoteToken") or {}).get("symbol"),
            "price_usd": float(p["priceUsd"]) if p.get("priceUsd") else None,
            "liquidity_usd": liq,
            "volume_24h_usd": (p.get("volume") or {}).get("h24"),
            "txns_24h": (p.get("txns") or {}).get("h24"),
            "pair_created": _date(p.get("pairCreatedAt")),
        })
    prices = [r["price_usd"] for r in rows if r["price_usd"]]
    return {
        "source_url": url,
        "pairs_total": len(pairs),
        "total_liquidity_usd": round(sum((p.get("liquidity") or {}).get("usd") or 0
                                         for p in pairs), 2),
        "price_min_usd": min(prices) if prices else None,
        "price_max_usd": max(prices) if prices else None,
        "top_pairs": rows,
    }
