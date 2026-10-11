"""Cassette providers for tests and evals without network access.

A cassette is a JSON file: {"recorded": bool, "note": str, "turns": {tag: [Turn dicts]}}.
`ReplayProvider` returns the recorded turns in order for each tag. `RecordingProvider`
wraps a live provider and writes what it saw, so a synthetic cassette can later be replaced
by a real one with CD_RECORD=1.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from .base import ModelProvider, ToolSpec, Turn


class ReplayProvider:
    name = "replay"

    def __init__(self, cassette: dict[str, Any]) -> None:
        self.cassette = cassette
        self.queues: dict[str, deque[dict[str, Any]]] = {
            tag: deque(turns) for tag, turns in cassette.get("turns", {}).items()
        }
        self.requests: list[dict[str, Any]] = []

    @classmethod
    def from_file(cls, path: Path) -> ReplayProvider:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    async def complete(
        self,
        *,
        model: str,
        system: str,
        history: list[dict[str, Any]],
        tools: list[ToolSpec],
        max_tokens: int,
        response_schema: dict[str, Any] | None = None,
        max_web_searches: int = 0,
        tag: str = "",
    ) -> Turn:
        self.requests.append(
            {"tag": tag, "model": model, "tools": [t.name for t in tools], "turns": len(history)}
        )
        queue = self.queues.get(tag)
        if not queue:
            raise RuntimeError(f"cassette exhausted for tag {tag!r}")
        turn = Turn.from_dict(queue.popleft())
        known = {t.name for t in tools}
        for call in turn.tool_calls:
            if call.name not in known:
                raise RuntimeError(f"cassette calls unknown tool {call.name!r} for {tag!r}")
        return turn


class RecordingProvider:
    name = "recording"

    def __init__(self, inner: ModelProvider, note: str = "") -> None:
        self.inner = inner
        self.name = inner.name
        self.turns: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.note = note

    async def complete(self, **kwargs: Any) -> Turn:
        turn = await self.inner.complete(**kwargs)
        self.turns[kwargs.get("tag", "")].append(turn.to_dict())
        return turn

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"recorded": True, "note": self.note, "turns": dict(self.turns)}
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
