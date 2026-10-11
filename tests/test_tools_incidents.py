import pytest

from crypto_diligence.tools.http import ToolError
from crypto_diligence.tools.incidents import defillama_hacks


async def test_euler_exploit_is_in_the_database(ctx):
    out = await defillama_hacks(ctx, "euler")
    assert out["database_size"] >= 20 and out["matches_total"] >= 1  # fixture is trimmed
    euler = next(m for m in out["matches"] if m["date"] == "2023-03-13")
    assert euler["amount_usd"] == 197_000_000
    assert euler["returned_funds_usd"] == 240_000_000
    assert out["matches"] == sorted(out["matches"], key=lambda m: m["date"] or "", reverse=True)
    # second call is served from the on-disk cache
    assert (ctx.cache_dir / "defillama_hacks.json").is_file()
    again = await defillama_hacks(ctx, "EULER")
    assert again["matches"] == out["matches"] and again["query"] == "EULER"


async def test_short_filters_are_refused(ctx):
    with pytest.raises(ToolError):
        await defillama_hacks(ctx, "e")
