from conftest import EUL, UNI

from crypto_diligence.identity import pick_coin, resolve_identity


def test_pick_coin_prefers_exact_symbol_then_name_then_rank():
    coins = [
        {"id": "unicorn", "name": "Unicorn", "symbol": "UNIC", "market_cap_rank": 900},
        {"id": "uniswap", "name": "Uniswap", "symbol": "UNI", "market_cap_rank": 25},
        {"id": "unifi", "name": "UniFi", "symbol": "UNFI", "market_cap_rank": None},
    ]
    assert pick_coin("uni", coins)[0]["id"] == "uniswap"
    assert pick_coin("Uniswap", coins)[0]["id"] == "uniswap"
    best, others = pick_coin("unknown", coins)
    assert best["id"] == "uniswap" and [c["id"] for c in others] == ["unicorn", "unifi"]
    assert pick_coin("x", []) == (None, [])


async def test_resolve_by_name(ctx):
    ident = await resolve_identity("Uniswap", ctx)
    assert ident.resolved and ident.coingecko_id == "uniswap" and ident.symbol == "UNI"
    assert ident.address == UNI.lower()
    assert ident.defillama_slug and "uniswap" in ident.defillama_slug
    assert ident.website


async def test_resolve_by_address(ctx):
    ident = await resolve_identity(EUL, ctx)
    assert ident.resolved and ident.address == EUL.lower()
    assert ident.coingecko_id == "euler" and ident.symbol == "EUL"


BEAN = "0xBEA0000029AD1c77D3d5D23Ba2D8893dB9d1Efab"


def _fake_market(monkeypatch, llama_address):
    from crypto_diligence.tools import market

    async def search(ctx, q):
        return {"coins": [{"id": "beanstalk", "name": "Beanstalk", "symbol": "BEAN",
                           "market_cap_rank": None}]}

    async def coin(ctx, key, lookup="id"):
        return {"id": "beanstalk", "name": "Beanstalk", "symbol": "bean", "platforms": {},
                "links": {}}

    async def llama(ctx, q):
        return {"matches": [{"name": "Beanstalk", "slug": "beanstalk", "gecko_id": None,
                             "address": llama_address, "parent_protocol": None}]}

    monkeypatch.setattr(market, "coingecko_search", search)
    monkeypatch.setattr(market, "coingecko_coin", coin)
    monkeypatch.setattr(market, "defillama_search", llama)


async def test_unranked_match_is_flagged_and_defillama_fills_the_address(ctx, monkeypatch):
    _fake_market(monkeypatch, "ethereum:" + BEAN)
    ident = await resolve_identity("Beanstalk", ctx)
    assert ident.resolved and ident.defillama_slug == "beanstalk"
    assert ident.address == BEAN.lower()
    assert any("no market cap rank" in n for n in ident.notes)
    assert any("DeFiLlama" in n for n in ident.notes)


async def test_an_address_on_another_chain_is_not_adopted(ctx, monkeypatch):
    _fake_market(monkeypatch, "polygon:0x4a81f8796e0c6ad4877a51c86693b0de8093f2ef")
    ident = await resolve_identity("Beanstalk", ctx)
    assert ident.address is None and ident.defillama_slug == "beanstalk"
