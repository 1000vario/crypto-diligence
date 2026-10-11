"""JSON Lines trace of every model call and every tool call of a run.

One line per event, with the agent, the input, an excerpt of the output, the duration and,
for model calls, the exact token usage and its cost. Tool outputs carry an estimated token
size (characters divided by four, labelled as an estimate); the exact tokens they add are
visible in the next model call input_tokens.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schemas import ModelCallRecord, ToolCallRecord, Usage

EXCERPT_CHARS = 2000


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def today_iso() -> str:
    return datetime.now(UTC).date().isoformat()


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class Trace:
    """Collects records in memory and appends them to a JSONL file when a path is given."""

    def __init__(self, path: Path | None = None, run_id: str = "") -> None:
        self.path = path
        self.run_id = run_id
        self.model_calls: list[ModelCallRecord] = []
        self.tool_calls: list[ToolCallRecord] = []
        self._lock = threading.Lock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.event("run_start", run_id=run_id)

    def event(self, kind: str, **fields: Any) -> None:
        if self.path is None:
            return
        record = {"ts": now_iso(), "kind": kind, **fields}
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")

    def model_call(self, rec: ModelCallRecord) -> None:
        with self._lock:
            self.model_calls.append(rec)
        self.event("model_call", **rec.model_dump())

    def tool_call(
        self,
        *,
        agent: str,
        tool: str,
        input: dict[str, Any],
        output: str,
        is_error: bool,
        duration_ms: int,
        server_side: bool = False,
    ) -> ToolCallRecord:
        rec = ToolCallRecord(
            agent=agent,
            tool=tool,
            input=input,
            output_excerpt=output[:EXCERPT_CHARS],
            output_chars=len(output),
            output_tokens_estimate=estimate_tokens(output),
            is_error=is_error,
            duration_ms=duration_ms,
            server_side=server_side,
        )
        with self._lock:
            self.tool_calls.append(rec)
        self.event("tool_call", **rec.model_dump())
        return rec

    def usage_total(self) -> Usage:
        total = Usage()
        for rec in self.model_calls:
            total = total.add(rec.usage)
        return total

    def cost_by_agent(self) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for rec in self.model_calls:
            if rec.agent in out and out[rec.agent] is None:
                continue
            if rec.cost_usd is None:
                out[rec.agent] = None
            else:
                out[rec.agent] = round((out.get(rec.agent) or 0.0) + rec.cost_usd, 6)
        return out
