import pytest
from conftest import UNI

from crypto_diligence.tools import market
from crypto_diligence.tools.http import ToolError


async def test_coingecko_search_and_coin_pages(ctx):
    s = await market.coingecko_search(ctx, "Uniswap")
    assert any(c["id"] == "uniswap" for c in s["coins"])
    assert s["source_url"].endswith("search?query=Uniswap")
    coin = await market.coingecko_coin(ctx, "uniswap")
    assert coin["id"] == "uniswap" and coin["symbol"] == "uni"
    assert coin["platforms"]["ethereum"] == UNI.lower()
    assert coin["market"]["price_usd"] > 0 and coin["links"]["homepage"]
    by_address = await market.coingecko_coin(ctx, UNI, lookup="contract")
    assert by_address["id"] == "uniswap"


async def test_market_chart_summary(ctx):
    chart = await market.coingecko_market_chart(ctx, "uniswap", 90)
    assert chart["days"] == 90 and chart["points"] > 80
    assert chart["first"]["date"] < chart["last"]["date"]
    assert chart["min"]["price_usd"] <= chart["max"]["price_usd"]
    assert 0 <= chart["max_drawdown_pct"] <= 100 and len(chart["sampled"]) >= 10
    assert chart["source_url"].endswith("uniswap/market_chart?vs_currency=usd&days=90")


def test_summarise_chart_on_a_known_series():
    day = 86_400_000
    prices = [[i * day, p] for i, p in enumerate([10, 12, 6, 9])]
    out = market.summarise_chart({"prices": prices, "total_volumes": [[0, 5], [day, 15]]}, 4)
    assert out["change_pct"] == -10.0 and out["max_drawdown_pct"] == 50.0
    assert out["min"]["price_usd"] == 6 and out["max"]["price_usd"] == 12
    assert out["mean_volume_usd"] == 10.0 and out["last_volume_usd"] == 15
    assert out["first"]["date"] == "1970-01-01" and out["last"]["date"] == "1970-01-04"
    with pytest.raises(ToolError):
        market.summarise_chart({"prices": []}, 4)


async def test_defillama_protocol_search_and_price(ctx):
    p = await market.defillama_protocol(ctx, "uniswap")
    assert p["slug"] == "uniswap" and p["tvl_current_usd"] > 0 and p["tvl_date"]
    assert p["tvl_by_chain_usd"] and p["chains"]
    assert p["source_url"].endswith("/protocol/uniswap")
    euler = await market.defillama_protocol(ctx, "euler")
    assert euler["hallmarks"] and all(h["date"][:4].isdigit() for h in euler["hallmarks"])
    assert euler["slug"] == "euler" and euler["is_parent"]

    found = await market.defillama_search(ctx, "Uniswap")
    assert found["matches"] and all("uniswap" in m["slug"] for m in found["matches"][:1])
    assert (ctx.cache_dir / "defillama_protocols.json").is_file()

    price = await market.defillama_price(ctx, UNI)
    assert price["symbol"] == "UNI" and price["price_usd"] > 0 and price["timestamp"]
    with pytest.raises(ToolError):
        await market.defillama_price(ctx, "0x" + "0" * 40)


async def test_dexscreener_pairs(ctx):
    out = await market.dexscreener_token(ctx, UNI)
    assert out["pairs_total"] >= 1 and out["total_liquidity_usd"] > 0
    assert out["price_min_usd"] <= out["price_max_usd"]
    top = out["top_pairs"][0]
    assert top["chain"] and top["dex"] and top["url"].startswith("https://")
    assert top["liquidity_usd"] >= (out["top_pairs"][-1]["liquidity_usd"] or 0)
