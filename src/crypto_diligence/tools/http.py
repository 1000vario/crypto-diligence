"""Shared async HTTP layer: one client, timeouts, bounded bodies, errors as values.

Tests and fixture recording swap the transport with `configure(transport=...)`.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

USER_AGENT = "crypto-diligence/0.1 (+https://github.com/1000vario/crypto-diligence)"
DEFAULT_TIMEOUT = 25.0
MAX_BYTES = 3_000_000

# Query parameters that carry credentials: never stored in fixture keys or reports.
SECRET_PARAMS = {"apikey", "x_cg_demo_api_key", "x_cg_pro_api_key", "token", "access_token"}


class ToolError(Exception):
    """A tool failure reported to the model as a value, never raised past the tool layer."""


_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None


def configure(transport: httpx.AsyncBaseTransport | None = None) -> None:
    global _transport, _client
    _transport = transport
    _client = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/html;q=0.9, */*;q=0.5",
            },
            transport=_transport,
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def scrub_url(url: str) -> str:
    """Drop credential query parameters from a URL (for keys, traces and reports)."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in SECRET_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def fixture_key(method: str, url: str, body: bytes | None) -> str:
    key = f"{method.upper()} {scrub_url(url)}"
    if body:
        key += " " + hashlib.sha256(body).hexdigest()[:16]
    return key


async def request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    max_bytes: int = MAX_BYTES,
) -> httpx.Response:
    content = None
    if json_body is not None:
        content = canonical_json(json_body).encode("utf-8")
        headers = {**(headers or {}), "Content-Type": "application/json"}
    try:
        resp = await client().request(method, url, params=params, headers=headers, content=content)
    except httpx.HTTPError as exc:
        raise ToolError(f"{method} {scrub_url(url)}: {exc.__class__.__name__}: {exc}") from exc
    if len(resp.content) > max_bytes:
        raise ToolError(f"{scrub_url(url)}: response larger than {max_bytes} bytes")
    return resp


def _check_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        shown = scrub_url(str(resp.request.url))
        raise ToolError(
            f"{resp.request.method} {shown}: HTTP {resp.status_code}: {resp.text[:200]}"
        )


async def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    max_bytes: int = MAX_BYTES,
) -> Any:
    resp = await request("GET", url, params=params, headers=headers, max_bytes=max_bytes)
    _check_status(resp)
    try:
        return resp.json()
    except ValueError as exc:
        raise ToolError(f"GET {scrub_url(url)}: not JSON: {resp.text[:200]}") from exc


async def post_json(url: str, payload: Any, *, headers: dict[str, str] | None = None) -> Any:
    resp = await request("POST", url, json_body=payload, headers=headers)
    _check_status(resp)
    try:
        return resp.json()
    except ValueError as exc:
        raise ToolError(f"POST {scrub_url(url)}: not JSON: {resp.text[:200]}") from exc


async def get_text(url: str, *, max_bytes: int = MAX_BYTES) -> tuple[str, str, str, int]:
    """Return (text, content_type, final_url, status)."""
    resp = await request("GET", url, max_bytes=max_bytes)
    ctype = resp.headers.get("content-type", "")
    return resp.text, ctype, str(resp.url), resp.status_code


_TAG_RE = re.compile(r"<[^>]+>")
_DROP_RE = re.compile(r"<(script|style|noscript|svg|head)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCK_RE = re.compile(r"</?(p|div|br|li|h[1-6]|tr|section|article|blockquote|pre)\b[^>]*>",
                       re.IGNORECASE)


def html_to_text(html: str) -> str:
    import html as html_mod

    text = _COMMENT_RE.sub(" ", html)
    text = _DROP_RE.sub(" ", text)
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html_mod.unescape(text)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln:
            out.append(ln)
        elif out and out[-1] != "":
            out.append("")
    return "\n".join(out).strip()
