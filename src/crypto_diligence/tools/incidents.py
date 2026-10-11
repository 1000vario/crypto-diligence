"""Incident tools: DeFiLlama's public hack database. Web search and fetch_page complete it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .context import ToolContext, cached_json
from .http import ToolError

LLAMA_HACKS = "https://api.llama.fi/hacks"
HACKS_CACHE_S = 24 * 3600


async def defillama_hacks(ctx: ToolContext, name_filter: str) -> dict[str, Any]:
    """Exploits whose protocol name contains name_filter (case-insensitive), newest first."""
    q = name_filter.strip().lower()
    if len(q) < 2:
        raise ToolError("name_filter needs at least two characters")
    hacks = await cached_json(ctx, "defillama_hacks", LLAMA_HACKS, HACKS_CACHE_S)
    rows = []
    for h in hacks:
        name = str(h.get("name") or "")
        if q not in name.lower():
            continue
        rows.append({
            "date": datetime.fromtimestamp(int(h["date"]), tz=UTC).date().isoformat()
            if h.get("date") else None,
            "name": name,
            "classification": h.get("classification"),
            "technique": h.get("technique"),
            "amount_usd": h.get("amount"),
            "returned_funds_usd": h.get("returnedFunds"),
            "chains": h.get("chain"),
            "target_type": h.get("targetType"),
            "bridge": h.get("bridgeHack"),
            "source": h.get("source"),
            "defillama_id": h.get("defillamaId"),
        })
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return {"source_url": LLAMA_HACKS, "database_size": len(hacks), "query": name_filter,
            "matches": rows[:20], "matches_total": len(rows)}
