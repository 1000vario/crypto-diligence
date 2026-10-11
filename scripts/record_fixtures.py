"""Record the HTTP responses the tests replay. Needs the network, no API key.

    python scripts/record_fixtures.py [tests/fixtures/http] [--only SUBSTRING] [--trim-only]

Large public answers are trimmed to what the tests use: the DeFiLlama /protocols and /hacks
lists keep a few entries, a /protocol/<slug> answer keeps its last 120 TVL points and loses
its per-chain and per-token series. The index marks trimmed entries. Re-run to refresh; a
rate-limited answer (429) is never stored, so re-run with --only to fill the gaps.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crypto_diligence.config import Settings  # noqa: E402
from crypto_diligence.identity import resolve_identity  # noqa: E402
from crypto_diligence.tools import docs, fixtures, http, incidents, market, onchain  # noqa: E402
from crypto_diligence.tools.context import ToolContext  # noqa: E402

UNI = "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984"
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
EUL = "0xd9Fcd98c322942075A5C3860693e9f4f03AAE07b"
KEEP_PROTOCOLS = {"uniswap", "uniswap-v3", "aave", "aave-v3", "euler", "euler-v2", "lido",
                  "curve-dex", "compound", "compound-v3", "makerdao", "sky", "rocket-pool",
                  "balancer-v2", "balancer-v3", "nomad", "beanstalk", "fei-protocol",
                  "iron-finance", "terra-classic", "chainlink", "circle-usdc", "tether",
                  "ethereum-name-service"}
KEEP_HACKS = ("euler", "curve", "nomad", "beanstalk", "balancer", "iron", "fei", "terra",
              "uniswap", "aave", "lido", "compound")
PROTOCOL_TVL_POINTS = 120  # trim_protocol reads the last point and the one 90 days before
PROTOCOL_DROP = ("chainTvls", "tokens", "tokensInUsd", "raises", "treasury")
PAUSE_S = 4.0


def _trim_list(fixture_dir: Path, url_key: str, keep: Callable[[dict], bool]) -> None:
    index = fixtures.load_index(fixture_dir)
    entry = index.get(url_key)
    if not entry or entry.get("trimmed"):
        return
    path = fixture_dir / entry["file"]
    data = json.loads(path.read_text(encoding="utf-8"))
    kept = [d for d in data if keep(d)]
    path.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8", newline="\n")
    entry["trimmed"] = f"{len(kept)} of {len(data)} entries kept"
    fixtures.save_index(fixture_dir, index)


def _trim_protocols(fixture_dir: Path) -> None:
    index = fixtures.load_index(fixture_dir)
    for key, entry in index.items():
        if "api.llama.fi/protocol/" not in key or entry.get("trimmed"):
            continue
        path = fixture_dir / entry["file"]
        data = json.loads(path.read_text(encoding="utf-8"))
        before = path.stat().st_size
        for k in PROTOCOL_DROP:
            data.pop(k, None)
        if isinstance(data.get("tvl"), list):
            data["tvl"] = data["tvl"][-PROTOCOL_TVL_POINTS:]
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
        entry["trimmed"] = (f"last {PROTOCOL_TVL_POINTS} TVL points kept, "
                            f"{', '.join(PROTOCOL_DROP)} dropped; {before} bytes before")
        print("trimmed:", key, entry["trimmed"])
    fixtures.save_index(fixture_dir, index)


def trim_all(fixture_dir: Path) -> None:
    _trim_list(fixture_dir, "GET https://api.llama.fi/protocols",
               lambda p: p.get("slug") in KEEP_PROTOCOLS)
    _trim_list(fixture_dir, "GET https://api.llama.fi/hacks",
               lambda h: any(k in str(h.get("name", "")).lower() for k in KEEP_HACKS))
    _trim_protocols(fixture_dir)


def _drop_failed(fixture_dir: Path) -> None:
    """Forget rate-limited answers recorded by an earlier run so they get retried."""
    index = fixtures.load_index(fixture_dir)
    for key in [k for k, v in index.items() if v.get("status") == 429]:
        (fixture_dir / index[key]["file"]).unlink(missing_ok=True)
        del index[key]
        print("dropped 429 fixture:", key)
    fixtures.save_index(fixture_dir, index)


def planned_calls(ctx: ToolContext) -> list[tuple[str, Callable]]:
    """Label and thunk for each call. Lists come last: fetched once, then trimmed on disk."""
    return [
        ("metadata UNI", lambda: onchain.get_token_metadata(ctx, UNI)),
        ("metadata USDC", lambda: onchain.get_token_metadata(ctx, USDC)),
        ("bytecode UNI", lambda: onchain.analyze_bytecode(ctx, UNI)),
        ("bytecode USDC", lambda: onchain.analyze_bytecode(ctx, USDC)),
        ("source UNI", lambda: onchain.get_contract_source(ctx, UNI)),
        ("source USDC", lambda: onchain.get_contract_source(ctx, USDC)),
        ("holders UNI", lambda: onchain.get_token_holders(ctx, UNI, 10)),
        ("coingecko_search Uniswap", lambda: market.coingecko_search(ctx, "Uniswap")),
        ("coingecko_search euler", lambda: market.coingecko_search(ctx, "euler")),
        ("coingecko_coin contract UNI", lambda: market.coingecko_coin(ctx, UNI, lookup="contract")),
        ("coingecko_coin uniswap", lambda: market.coingecko_coin(ctx, "uniswap", lookup="id")),
        ("coingecko_coin euler", lambda: market.coingecko_coin(ctx, "euler", lookup="id")),
        ("market_chart uniswap", lambda: market.coingecko_market_chart(ctx, "uniswap", 90)),
        ("defillama_price UNI", lambda: market.defillama_price(ctx, UNI)),
        ("dexscreener UNI", lambda: market.dexscreener_token(ctx, UNI)),
        ("github Uniswap/v3-core", lambda: docs.github_repo(ctx, "Uniswap/v3-core")),
        ("defillama_search Uniswap", lambda: market.defillama_search(ctx, "Uniswap")),
        ("defillama_hacks euler", lambda: incidents.defillama_hacks(ctx, "euler")),
        ("defillama_protocol uniswap", lambda: market.defillama_protocol(ctx, "uniswap")),
        ("defillama_protocol euler", lambda: market.defillama_protocol(ctx, "euler")),
        ("creation UNI (fails without ETHERSCAN_API_KEY)",
         lambda: onchain.get_contract_creation(ctx, UNI)),
        ("identity Uniswap", lambda: resolve_identity("Uniswap", ctx)),
        ("identity EUL", lambda: resolve_identity(EUL, ctx)),
    ]


async def main(fixture_dir: Path, only: str | None, trim_only: bool) -> None:
    if trim_only:
        trim_all(fixture_dir)
        return
    _drop_failed(fixture_dir)
    http.configure(fixtures.RecordingTransport(fixture_dir))
    settings = Settings(data_dir=fixture_dir / "_cache")
    ctx = ToolContext(settings, resolve_hosts=False)
    for label, thunk in planned_calls(ctx):
        if only and only.lower() not in label.lower():
            continue
        try:
            out = await thunk()
            print("ok:", label, "" if not hasattr(out, "model_dump_json")
                  else out.model_dump_json()[:300])
        except http.ToolError as exc:
            print("tool error:", label, ":", str(exc)[:300])
        await asyncio.sleep(PAUSE_S)  # CoinGecko's free tier throttles bursts
    await http.aclose()
    trim_all(fixture_dir)
    print("fixtures in", fixture_dir, ":", len(fixtures.load_index(fixture_dir)))


if __name__ == "__main__":
    argv = sys.argv[1:]
    only_arg = argv[argv.index("--only") + 1] if "--only" in argv else None
    trim_flag = "--trim-only" in argv
    positional = [a for i, a in enumerate(argv)
                  if not a.startswith("--") and (i == 0 or argv[i - 1] != "--only")]
    target = Path(positional[0]) if positional else Path("tests/fixtures/http")
    asyncio.run(main(target, only_arg, trim_flag))
