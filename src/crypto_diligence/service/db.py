"""SQLite storage: reports, daily quota per email hash, watchlist (paid tier, off)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    subject_key TEXT NOT NULL,
    query TEXT NOT NULL,
    title TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    cost_usd REAL,
    claims INTEGER NOT NULL,
    contradictions INTEGER NOT NULL,
    unsourced INTEGER NOT NULL,
    json TEXT NOT NULL,
    markdown TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reports_subject ON reports (subject_key, created_at);
CREATE TABLE IF NOT EXISTS quota (
    email_hash TEXT NOT NULL,
    day TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (email_hash, day)
);
CREATE TABLE IF NOT EXISTS watchlist (
    email_hash TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (email_hash, subject_key)
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def save_report(self, row: dict[str, Any]) -> None:
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self.connect() as con:
            con.execute(f"INSERT OR REPLACE INTO reports ({cols}) VALUES ({marks})",
                        list(row.values()))

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        with self.connect() as con:
            r = con.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return dict(r) if r else None

    def latest_for_subject(self, subject_key: str, since_iso: str) -> dict[str, Any] | None:
        """Newest report whose resolved subject or raw query equals `subject_key`."""
        with self.connect() as con:
            r = con.execute(
                "SELECT * FROM reports WHERE (subject_key = ? OR lower(query) = ?) "
                "AND created_at >= ? "
                "ORDER BY created_at DESC LIMIT 1",
                (subject_key, subject_key, since_iso)).fetchone()
        return dict(r) if r else None

    def list_reports(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT id, subject_key, query, title, mode, created_at, cost_usd, claims, "
                "contradictions, unsourced FROM reports ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    def quota_used(self, email_hash: str, day: str) -> int:
        with self.connect() as con:
            r = con.execute("SELECT count FROM quota WHERE email_hash = ? AND day = ?",
                            (email_hash, day)).fetchone()
        return int(r["count"]) if r else 0

    def quota_increment(self, email_hash: str, day: str) -> int:
        with self.connect() as con:
            con.execute(
                "INSERT INTO quota (email_hash, day, count) VALUES (?, ?, 1) "
                "ON CONFLICT(email_hash, day) DO UPDATE SET count = count + 1",
                (email_hash, day))
            r = con.execute("SELECT count FROM quota WHERE email_hash = ? AND day = ?",
                            (email_hash, day)).fetchone()
        return int(r["count"])

    def watch(self, email_hash: str, subject_key: str, created_at: str) -> None:
        with self.connect() as con:
            con.execute("INSERT OR IGNORE INTO watchlist VALUES (?, ?, ?)",
                        (email_hash, subject_key, created_at))

    def watchlist(self, email_hash: str) -> list[str]:
        with self.connect() as con:
            rows = con.execute("SELECT subject_key FROM watchlist WHERE email_hash = ? "
                               "ORDER BY created_at", (email_hash,)).fetchall()
        return [r["subject_key"] for r in rows]
