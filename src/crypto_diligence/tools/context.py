"""What every tool receives besides its own input."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Settings
from .http import get_json


@dataclass
class ToolContext:
    settings: Settings
    resolve_hosts: bool = True  # fetch_page resolves hostnames to block private networks

    @property
    def cache_dir(self) -> Path:
        return self.settings.data_dir / "cache"


async def cached_json(ctx: ToolContext, name: str, url: str, max_age_s: int,
                      max_bytes: int = 30_000_000) -> Any:
    """Download a large public list once per `max_age_s`, keep it on disk."""
    path = ctx.cache_dir / f"{name}.json"
    if path.is_file() and time.time() - path.stat().st_mtime < max_age_s:
        return json.loads(path.read_text(encoding="utf-8"))
    data = await get_json(url, max_bytes=max_bytes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8", newline="\n")
    return data
