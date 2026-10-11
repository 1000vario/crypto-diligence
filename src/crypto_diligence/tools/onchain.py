"""On-chain tools: verification status, bytecode analysis, holders, token metadata, age.

Data sources: a public JSON-RPC endpoint (default ethereum-rpc.publicnode.com), Sourcify v2,
Etherscan V2 (optional key), Ethplorer (free key). Everything read is returned with the URL
it came from so the agent can cite it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .context import ToolContext
from .http import ToolError, get_json, post_json
from .keccak import selector

SOURCIFY = "https://sourcify.dev/server/v2/contract"
ETHERSCAN = "https://api.etherscan.io/v2/api"
ETHPLORER = "https://api.ethplorer.io"

# Functions whose presence matters for a holder: who can mint, freeze, block or replace code.
SENSITIVE_SIGNATURES = [
    "mint(address,uint256)",
    "mint(uint256)",
    "burn(uint256)",
    "burnFrom(address,uint256)",
    "issue(uint256)",
    "redeem(uint256)",
    "pause()",
    "unpause()",
    "paused()",
    "owner()",
    "transferOwnership(address)",
    "renounceOwnership()",
    "setOwner(address)",
    "blacklist(address)",
    "unBlacklist(address)",
    "isBlacklisted(address)",
    "addBlackList(address)",
    "removeBlackList(address)",
    "destroyBlackFunds(address)",
    "freeze(address)",
    "upgradeTo(address)",
    "upgradeToAndCall(address,bytes)",
    "masterMinter()",
    "configureMinter(address,uint256)",
    "setFeeTo(address)",
    "setFee(uint256)",
]
SELECTORS: dict[str, str] = {sig: selector(sig) for sig in SENSITIVE_SIGNATURES}

# Storage slots used by common proxy patterns (value = implementation or admin address).
PROXY_SLOTS = {
    "eip1967_implementation": "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc",
    "eip1967_admin": "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103",
    "eip1967_beacon": "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50",
    "zeppelinos_implementation":
        "0x7050c9e0f4ca769c69bd3a8ef740bc37934f8e2c036e5a723fd8ee048ed3f8c3",
    "zeppelinos_admin": "0x10d6a54a4754c8869d6886b5f5d7fbfa5b4522237ea5c60d11bc4e7a1ff9390b",
    "eip1822_logic": "0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7",
}
EIP1167_PREFIX = "363d3d373d3d3d363d73"
EIP1167_SUFFIX = "5af43d82803e903d91602b57fd5bf3"


def _norm_address(address: str) -> str:
    a = address.strip().lower()
    if not (a.startswith("0x") and len(a) == 42 and all(c in "0123456789abcdef" for c in a[2:])):
        raise ToolError(f"not an EVM address: {address!r}")
    return a


def _iso(ts: int | str | None) -> str | None:
    if ts in (None, "", 0):
        return None
    return datetime.fromtimestamp(int(ts), tz=UTC).isoformat(timespec="seconds")


# Minimal ABI decoding for the return values we read.


def _hex_to_bytes(data: str) -> bytes:
    return bytes.fromhex(data[2:] if data.startswith("0x") else data)


def decode_uint(data: str) -> int | None:
    raw = _hex_to_bytes(data)
    return int.from_bytes(raw[:32], "big") if len(raw) >= 32 else None


def decode_address(data: str) -> str | None:
    raw = _hex_to_bytes(data)
    if len(raw) < 32:
        return None
    return "0x" + raw[12:32].hex()


def decode_bool(data: str) -> bool | None:
    v = decode_uint(data)
    return None if v is None else bool(v)


def decode_string(data: str) -> str | None:
    raw = _hex_to_bytes(data)
    if len(raw) == 32:  # bytes32 string (older tokens)
        return raw.rstrip(b"\x00").decode("utf-8", "replace") or None
    if len(raw) < 64:
        return None
    offset = int.from_bytes(raw[:32], "big")
    if offset + 32 > len(raw):
        return None
    length = int.from_bytes(raw[offset : offset + 32], "big")
    chunk = raw[offset + 32 : offset + 32 + length]
    return chunk.decode("utf-8", "replace")


async def rpc_batch(ctx: ToolContext, calls: list[tuple[str, list[Any]]]) -> list[Any]:
    payload = [
        {"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)
    ]
    out = await post_json(ctx.settings.rpc_url, payload)
    if not isinstance(out, list):
        raise ToolError(f"RPC {ctx.settings.rpc_url}: batch answer is not a list: {str(out)[:200]}")
    results: list[Any] = [{"error": "missing"}] * len(calls)
    for item in out:
        idx = item.get("id")
        if isinstance(idx, int) and 0 <= idx < len(calls):
            results[idx] = {"error": item["error"]} if "error" in item else item.get("result")
    return results


def _is_err(v: Any) -> bool:
    return isinstance(v, dict) and "error" in v


async def eth_call(ctx: ToolContext, to: str, data: str) -> Any:
    (res,) = await rpc_batch(ctx, [("eth_call", [{"to": to, "data": data}, "latest"])])
    return res


async def get_code(ctx: ToolContext, address: str) -> str:
    (code,) = await rpc_batch(ctx, [("eth_getCode", [address, "latest"])])
    if _is_err(code):
        raise ToolError(f"eth_getCode failed: {code['error']}")
    return code or "0x"


def scan_selectors(code_hex: str) -> dict[str, bool]:
    body = code_hex[2:].lower() if code_hex.startswith("0x") else code_hex.lower()
    return {sig: (sel in body) for sig, sel in SELECTORS.items()}


async def analyze_bytecode(ctx: ToolContext, address: str) -> dict[str, Any]:
    """Code size, sensitive selectors, proxy pattern and implementation, owner() and paused()."""
    address = _norm_address(address)
    rpc = ctx.settings.rpc_url
    calls: list[tuple[str, list[Any]]] = [("eth_getCode", [address, "latest"])]
    slot_names = list(PROXY_SLOTS)
    for name in slot_names:
        calls.append(("eth_getStorageAt", [address, PROXY_SLOTS[name], "latest"]))
    calls.append(("eth_call", [{"to": address, "data": "0x" + SELECTORS["owner()"]}, "latest"]))
    calls.append(("eth_call", [{"to": address, "data": "0x" + SELECTORS["paused()"]}, "latest"]))
    res = await rpc_batch(ctx, calls)
    code = res[0]
    if _is_err(code):
        raise ToolError(f"eth_getCode failed: {code['error']}")
    code = code or "0x"
    size = (len(code) - 2) // 2
    out: dict[str, Any] = {
        "address": address,
        "rpc_url": rpc,
        "has_code": size > 0,
        "code_size_bytes": size,
        "proxy": {"detected": False, "pattern": None, "implementation": None, "admin": None},
        "selectors_in_proxy_or_contract": {},
        "selectors_in_implementation": None,
        "owner": None,
        "paused": None,
        "notes": [],
    }
    if size == 0:
        out["notes"].append("No code at this address: an externally owned account or not deployed.")
        return out
    body = code[2:].lower()
    if body.startswith(EIP1167_PREFIX) and EIP1167_SUFFIX in body:
        impl = "0x" + body[len(EIP1167_PREFIX) : len(EIP1167_PREFIX) + 40]
        out["proxy"] = {"detected": True, "pattern": "eip1167_minimal_proxy",
                        "implementation": impl, "admin": None}
    slots = dict(zip(slot_names, res[1 : 1 + len(slot_names)], strict=True))
    for name, value in slots.items():
        if _is_err(value) or not value:
            continue
        addr = decode_address(value)
        if addr and addr != "0x" + "0" * 40:
            if name.endswith("_admin"):
                out["proxy"]["admin"] = addr
            else:
                out["proxy"]["detected"] = True
                out["proxy"]["pattern"] = name.rsplit("_", 1)[0]
                out["proxy"]["implementation"] = addr
    out["selectors_in_proxy_or_contract"] = {
        sig: True for sig, found in scan_selectors(code).items() if found
    }
    owner_res, paused_res = res[-2], res[-1]
    if not _is_err(owner_res) and owner_res and owner_res != "0x":
        out["owner"] = decode_address(owner_res)
    if not _is_err(paused_res) and paused_res and paused_res != "0x":
        out["paused"] = decode_bool(paused_res)
    impl = out["proxy"]["implementation"]
    if impl:
        try:
            impl_code = await get_code(ctx, impl)
            out["selectors_in_implementation"] = {
                sig: True for sig, found in scan_selectors(impl_code).items() if found
            }
            out["implementation_code_size_bytes"] = (len(impl_code) - 2) // 2
            out["notes"].append(
                "Upgradeable proxy: the implementation can be replaced by whoever controls the "
                "admin or owner, so today's code is not a guarantee about tomorrow's."
            )
        except ToolError as exc:
            out["notes"].append(f"could not read implementation code: {exc}")
    out["notes"].append(
        "Selector presence means the 4-byte signature appears in the bytecode; it is strong "
        "evidence the function exists but says nothing about who may call it."
    )
    return out


async def get_token_metadata(ctx: ToolContext, address: str) -> dict[str, Any]:
    """name, symbol, decimals, totalSupply read directly from the contract."""
    address = _norm_address(address)
    sigs = ["name()", "symbol()", "decimals()", "totalSupply()"]
    calls = [("eth_call", [{"to": address, "data": "0x" + selector(s)}, "latest"]) for s in sigs]
    res = await rpc_batch(ctx, calls)
    out: dict[str, Any] = {"address": address, "rpc_url": ctx.settings.rpc_url}
    out["name"] = decode_string(res[0]) if not _is_err(res[0]) and res[0] else None
    out["symbol"] = decode_string(res[1]) if not _is_err(res[1]) and res[1] else None
    decimals = decode_uint(res[2]) if not _is_err(res[2]) and res[2] else None
    supply = decode_uint(res[3]) if not _is_err(res[3]) and res[3] else None
    out["decimals"] = decimals
    out["total_supply_raw"] = str(supply) if supply is not None else None
    if supply is not None and decimals is not None and decimals <= 36:
        out["total_supply"] = supply / (10**decimals)
    errors = [f"{s}: {r['error']}" for s, r in zip(sigs, res, strict=True) if _is_err(r)]
    if errors:
        out["errors"] = errors
    return out


async def get_contract_source(ctx: ToolContext, address: str, chain_id: int = 1) -> dict[str, Any]:
    """Verification status on Sourcify (always) and Etherscan (when a key is set)."""
    address = _norm_address(address)
    out: dict[str, Any] = {"address": address, "chain_id": chain_id, "sourcify": None,
                           "etherscan": None, "notes": []}
    url = f"{SOURCIFY}/{chain_id}/{address}"
    try:
        s = await get_json(url)
        out["sourcify"] = {
            "url": url,
            "verified": bool(s.get("match")),
            "match": s.get("match"),
            "verified_at": s.get("verifiedAt"),
            "creation_match": s.get("creationMatch"),
            "runtime_match": s.get("runtimeMatch"),
        }
    except ToolError as exc:
        msg = str(exc)
        if "HTTP 404" in msg:
            out["sourcify"] = {"url": url, "verified": False, "match": None,
                               "note": "not found on Sourcify"}
        else:
            out["notes"].append(f"sourcify: {msg}")
    key = ctx.settings.etherscan_api_key
    if not key:
        out["notes"].append("ETHERSCAN_API_KEY not set: Etherscan verification not checked.")
        return out
    params = {"chainid": chain_id, "module": "contract", "action": "getsourcecode",
              "address": address, "apikey": key}
    try:
        e = await get_json(ETHERSCAN, params=params)
        result = e.get("result")
        if e.get("status") != "1" or not isinstance(result, list) or not result:
            out["notes"].append(f"etherscan: {e.get('message')}: {str(result)[:200]}")
            return out
        item = result[0]
        src = item.get("SourceCode") or ""
        out["etherscan"] = {
            "url": f"https://etherscan.io/address/{address}#code",
            "verified": bool(src),
            "contract_name": item.get("ContractName") or None,
            "compiler_version": item.get("CompilerVersion") or None,
            "license": item.get("LicenseType") or None,
            "proxy": item.get("Proxy") == "1",
            "implementation": (item.get("Implementation") or None),
            "source_chars": len(src),
        }
    except ToolError as exc:
        out["notes"].append(f"etherscan: {exc}")
    return out


async def get_contract_creation(
    ctx: ToolContext, address: str, chain_id: int = 1
) -> dict[str, Any]:
    """Creation transaction, block and date (Etherscan key required for the transaction)."""
    address = _norm_address(address)
    key = ctx.settings.etherscan_api_key
    if not key:
        raise ToolError(
            "ETHERSCAN_API_KEY not set: contract creation date unavailable. Lower bounds remain: "
            "Sourcify verified_at, CoinGecko genesis_date, DeFiLlama listedAt."
        )
    params = {"chainid": chain_id, "module": "contract", "action": "getcontractcreation",
              "contractaddresses": address, "apikey": key}
    e = await get_json(ETHERSCAN, params=params)
    result = e.get("result")
    if e.get("status") != "1" or not isinstance(result, list) or not result:
        raise ToolError(f"etherscan getcontractcreation: {e.get('message')}: {str(result)[:200]}")
    item = result[0]
    tx = item.get("txHash")
    out: dict[str, Any] = {
        "address": address,
        "creator": item.get("contractCreator"),
        "tx_hash": tx,
        "block_number": None,
        "created_at": None,
        "source_url": f"https://etherscan.io/address/{address}",
    }
    if item.get("timestamp"):
        out["created_at"] = _iso(item["timestamp"])
        out["block_number"] = item.get("blockNumber")
        return out
    (receipt,) = await rpc_batch(ctx, [("eth_getTransactionReceipt", [tx])])
    if _is_err(receipt) or not receipt:
        return out
    block_hex = receipt.get("blockNumber")
    (block,) = await rpc_batch(ctx, [("eth_getBlockByNumber", [block_hex, False])])
    if not _is_err(block) and block:
        out["block_number"] = int(block_hex, 16)
        out["created_at"] = _iso(int(block["timestamp"], 16))
    return out


async def get_token_holders(ctx: ToolContext, address: str, limit: int = 10) -> dict[str, Any]:
    """Top holders and their share (Ethplorer, Ethereum mainnet only), contract flag per holder."""
    address = _norm_address(address)
    limit = max(1, min(int(limit), 100))
    info_url = f"{ETHPLORER}/getTokenInfo/{address}"
    top_url = f"{ETHPLORER}/getTopTokenHolders/{address}"
    info = await get_json(info_url, params={"apiKey": "freekey"})
    if isinstance(info, dict) and info.get("error"):
        raise ToolError(f"ethplorer getTokenInfo: {info['error']}")
    top = await get_json(top_url, params={"apiKey": "freekey", "limit": limit})
    if isinstance(top, dict) and top.get("error"):
        raise ToolError(f"ethplorer getTopTokenHolders: {top['error']}")
    holders = top.get("holders") or []
    addrs = [h.get("address") for h in holders if h.get("address")]
    is_contract: dict[str, bool] = {}
    if addrs:
        try:
            codes = await rpc_batch(ctx, [("eth_getCode", [a, "latest"]) for a in addrs])
            for a, c in zip(addrs, codes, strict=True):
                if not _is_err(c):
                    is_contract[a] = bool(c and c != "0x")
        except ToolError:
            pass
    rows = []
    for h in holders:
        a = h.get("address")
        rows.append({"address": a, "share_pct": h.get("share"),
                     "is_contract": is_contract.get(a)})
    shares = [float(h.get("share") or 0) for h in holders]
    return {
        "address": address,
        "source_urls": [info_url + "?apiKey=freekey", top_url + "?apiKey=freekey"],
        "holders_count": info.get("holdersCount"),
        "owner_field": info.get("owner"),
        "decimals": info.get("decimals"),
        "total_supply_raw": info.get("totalSupply"),
        "top_holders": rows,
        "top_n_share_pct": round(sum(shares), 2),
        "top_n": len(rows),
        "notes": [
            "A large holder that is a contract is often an exchange, a bridge, a staking or a "
            "treasury contract; its share is not one person's. Say which when known."
        ],
    }
