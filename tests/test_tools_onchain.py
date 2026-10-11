import pytest
from conftest import UNI, USDC

from crypto_diligence.tools import onchain
from crypto_diligence.tools.http import ToolError


async def test_token_metadata_read_from_the_contract(ctx):
    meta = await onchain.get_token_metadata(ctx, UNI)
    assert meta["symbol"] == "UNI" and meta["name"] == "Uniswap" and meta["decimals"] == 18
    assert meta["total_supply"] == pytest.approx(1_000_000_000, rel=0.01)
    assert "errors" not in meta
    with pytest.raises(ToolError):
        await onchain.get_token_metadata(ctx, "nope")


async def test_plain_token_is_not_a_proxy(ctx):
    out = await onchain.analyze_bytecode(ctx, UNI)
    assert out["has_code"] and out["code_size_bytes"] > 1000
    assert not out["proxy"]["detected"] and out["selectors_in_implementation"] is None
    found = out["selectors_in_proxy_or_contract"]
    assert "mint(address,uint256)" in found  # UNI has a minter-gated mint
    assert "pause()" not in found and "blacklist(address)" not in found
    assert out["paused"] is None


async def test_usdc_is_an_upgradeable_proxy_with_sensitive_functions(ctx):
    out = await onchain.analyze_bytecode(ctx, USDC)
    proxy = out["proxy"]
    assert proxy["detected"] and proxy["implementation"] and proxy["admin"]
    assert proxy["implementation"].startswith("0x") and len(proxy["implementation"]) == 42
    assert "upgradeTo(address)" in out["selectors_in_proxy_or_contract"]
    impl = out["selectors_in_implementation"]
    for sig in ("pause()", "unpause()", "blacklist(address)", "mint(address,uint256)",
                "transferOwnership(address)"):
        assert sig in impl, sig
    assert out["paused"] is False and out["owner"]
    assert any("Upgradeable proxy" in n for n in out["notes"])


def test_selector_scan_and_decoders():
    found = onchain.scan_selectors("0x6080" + onchain.SELECTORS["pause()"] + "00")
    assert found["pause()"] and not found["mint(address,uint256)"]
    assert onchain.decode_uint("0x" + "0" * 63 + "a") == 10
    assert onchain.decode_bool("0x" + "0" * 64) is False
    assert onchain.decode_address("0x" + "0" * 24 + "ab" * 20) == "0x" + "ab" * 20
    assert onchain.decode_string(
        "0x" + "0" * 62 + "20" + "0" * 62 + "03" + "554e49" + "0" * 58
    ) == "UNI"


async def test_sourcify_verification(ctx):
    for addr in (UNI, USDC):
        out = await onchain.get_contract_source(ctx, addr)
        assert out["sourcify"]["verified"] and out["sourcify"]["match"]
        assert out["sourcify"]["url"].endswith(addr.lower())
        assert out["etherscan"] is None
        assert any("ETHERSCAN_API_KEY" in n for n in out["notes"])


async def test_creation_needs_an_etherscan_key(ctx):
    with pytest.raises(ToolError) as exc:
        await onchain.get_contract_creation(ctx, UNI)
    assert "ETHERSCAN_API_KEY" in str(exc.value)


async def test_top_holders(ctx):
    out = await onchain.get_token_holders(ctx, UNI, limit=10)
    assert out["holders_count"] > 100_000 and out["top_n"] == 10
    assert 0 < out["top_n_share_pct"] <= 100
    assert all(r["address"].startswith("0x") for r in out["top_holders"])
    assert any(r["is_contract"] for r in out["top_holders"])
    assert all("apiKey=freekey" in u for u in out["source_urls"])
