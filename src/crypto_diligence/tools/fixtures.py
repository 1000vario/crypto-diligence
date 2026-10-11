"""Recorded HTTP responses for tests: replay by exact request key, record from live calls.

Layout of a fixture directory: `index.json` maps a request key (see `http.fixture_key`) to
{"file": ..., "status": ..., "content_type": ..., "recorded": "YYYY-MM-DD"}; the files sit
next to it. Credentials never enter the key (see `http.scrub_url`).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .http import fixture_key


def load_index(fixture_dir: Path) -> dict[str, dict]:
    path = fixture_dir / "index.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_index(fixture_dir: Path, index: dict[str, dict]) -> None:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def replay_transport(fixture_dir: Path) -> httpx.MockTransport:
    index = load_index(fixture_dir)

    def handler(request: httpx.Request) -> httpx.Response:
        key = fixture_key(request.method, str(request.url), request.content or None)
        entry = index.get(key)
        if entry is None:
            return httpx.Response(599, text=f"no fixture for {key}")
        body = (fixture_dir / entry["file"]).read_bytes()
        return httpx.Response(
            entry.get("status", 200),
            content=body,
            headers={"content-type": entry.get("content_type", "application/json")},
        )

    return httpx.MockTransport(handler)


class RecordingTransport(httpx.AsyncBaseTransport):
    """Passes requests to the network and stores every response under its key."""

    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir
        self.inner = httpx.AsyncHTTPTransport()
        self.index = load_index(fixture_dir)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        resp = await self.inner.handle_async_request(request)
        body = await resp.aread()  # decoded, so the stored body and the reply carry no encoding
        headers = {k: v for k, v in resp.headers.items()
                   if k.lower() not in ("content-encoding", "content-length",
                                        "transfer-encoding")}
        key = fixture_key(request.method, str(request.url), request.content or None)
        ctype = resp.headers.get("content-type", "application/octet-stream")
        if resp.status_code == 429:  # a rate limit is not a fixture; keep any older entry
            print("not recorded (429):", key)
            return httpx.Response(resp.status_code, content=body, headers=headers,
                                  request=request)
        ext = ".json" if "json" in ctype else ".html" if "html" in ctype else ".txt"
        name = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ext
        self.fixture_dir.mkdir(parents=True, exist_ok=True)
        (self.fixture_dir / name).write_bytes(body)
        self.index[key] = {
            "file": name,
            "status": resp.status_code,
            "content_type": ctype,
            "recorded": datetime.now(UTC).date().isoformat(),
        }
        save_index(self.fixture_dir, self.index)
        return httpx.Response(resp.status_code, content=body, headers=headers, request=request)

    async def aclose(self) -> None:
        await self.inner.aclose()
