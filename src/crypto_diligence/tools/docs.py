"""Documentation tools: fetch a public page as text, read GitHub repositories."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any
from urllib.parse import urlsplit

from .context import ToolContext
from .http import ToolError, get_json, get_text, html_to_text

GITHUB = "https://api.github.com"
MAX_PAGE_CHARS = 40_000


def _gh_headers(ctx: ToolContext) -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if ctx.settings.github_token:
        h["Authorization"] = f"Bearer {ctx.settings.github_token}"
    return h


async def _assert_public_host(ctx: ToolContext, url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ToolError("only http(s) URLs are fetched")
    host = parts.hostname or ""
    if not host or host == "localhost" or host.endswith(".local"):
        raise ToolError("refusing to fetch a local address")
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise ToolError("refusing to fetch a private address")
        return
    except ValueError:
        pass
    if not ctx.resolve_hosts:
        return
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ToolError(f"cannot resolve {host}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ToolError(f"refusing to fetch {host}: resolves to a private address")


async def fetch_page(ctx: ToolContext, url: str, max_chars: int = MAX_PAGE_CHARS) -> dict[str, Any]:
    """Public web page as plain text (HTML stripped), capped at max_chars."""
    url = url.strip()
    await _assert_public_host(ctx, url)
    max_chars = max(1000, min(int(max_chars), MAX_PAGE_CHARS))
    text, ctype, final_url, status = await get_text(url)
    if status >= 400:
        raise ToolError(f"GET {url}: HTTP {status}")
    if "html" in ctype or text.lstrip()[:1] == "<":
        text = html_to_text(text)
    truncated = len(text) > max_chars
    return {
        "url": url,
        "final_url": final_url,
        "status": status,
        "content_type": ctype.split(";")[0],
        "chars": len(text),
        "truncated": truncated,
        "text": text[:max_chars],
    }


def _repo_path(owner_repo: str) -> str:
    s = owner_repo.strip()
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
    s = s.strip("/")
    parts = s.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ToolError(f"expected owner/repo, got {owner_repo!r}")
    return f"{parts[0]}/{parts[1].removesuffix('.git')}"


async def github_repo(ctx: ToolContext, owner_repo: str) -> dict[str, Any]:
    """Repository facts: dates, stars, licence, archived flag, latest commit, contributors."""
    path = _repo_path(owner_repo)
    headers = _gh_headers(ctx)
    url = f"{GITHUB}/repos/{path}"
    r = await get_json(url, headers=headers)
    out: dict[str, Any] = {
        "source_url": url,
        "html_url": r.get("html_url"),
        "full_name": r.get("full_name"),
        "description": r.get("description"),
        "created_at": r.get("created_at"),
        "pushed_at": r.get("pushed_at"),
        "updated_at": r.get("updated_at"),
        "stars": r.get("stargazers_count"),
        "forks": r.get("forks_count"),
        "open_issues": r.get("open_issues_count"),
        "archived": r.get("archived"),
        "disabled": r.get("disabled"),
        "fork": r.get("fork"),
        "license": (r.get("license") or {}).get("spdx_id"),
        "language": r.get("language"),
        "default_branch": r.get("default_branch"),
        "topics": (r.get("topics") or [])[:10],
        "latest_commit": None,
        "contributors": None,
        "notes": [],
    }
    try:
        commits = await get_json(f"{url}/commits", params={"per_page": 1}, headers=headers)
        if commits:
            c = commits[0]
            out["latest_commit"] = {
                "sha": (c.get("sha") or "")[:12],
                "date": ((c.get("commit") or {}).get("committer") or {}).get("date"),
                "message": ((c.get("commit") or {}).get("message") or "")[:120],
            }
    except ToolError as exc:
        out["notes"].append(f"commits: {exc}")
    try:
        contribs = await get_json(f"{url}/contributors",
                                  params={"per_page": 100, "anon": "true"}, headers=headers)
        n = len(contribs)
        out["contributors"] = "100+" if n >= 100 else n
    except ToolError as exc:
        out["notes"].append(f"contributors: {exc}")
    if not ctx.settings.github_token:
        out["notes"].append("unauthenticated GitHub API: 60 requests per hour per IP")
    return out


async def github_search_repos(ctx: ToolContext, query: str) -> dict[str, Any]:
    """Search repositories by name or keywords (top 5 by stars)."""
    url = f"{GITHUB}/search/repositories"
    r = await get_json(url, params={"q": query, "per_page": 5, "sort": "stars"},
                       headers=_gh_headers(ctx))
    items = []
    for it in r.get("items") or []:
        items.append({"full_name": it.get("full_name"), "html_url": it.get("html_url"),
                      "description": it.get("description"), "stars": it.get("stargazers_count"),
                      "pushed_at": it.get("pushed_at"), "archived": it.get("archived"),
                      "license": (it.get("license") or {}).get("spdx_id")})
    return {"source_url": f"{url}?q={query}", "total_count": r.get("total_count"),
            "items": items}
