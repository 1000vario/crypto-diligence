"""FastAPI application: a form, a queue of one, public cached reports, a daily quota.

A report takes minutes and the request waits for it; this is a free service for a few
reports a day, not a job system. The paid routes answer 403 while PAID_TIER_ENABLED=false.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .. import __version__
from .. import report as render
from ..config import Settings
from ..orchestrator import run_report
from ..schemas import DISCLAIMER, Report
from .db import Database
from .tiers import PaidTierDisabled, email_hash, free_tier, require_paid, tier_for

TEMPLATES = Path(__file__).parent / "templates"
GLOBAL_QUOTA_KEY = "*"  # one row per day in the quota table caps the whole deployment
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
QUERY_RE = re.compile(r"^[\w .:/()&'-]{1,120}$")


def subject_key(report: Report) -> str:
    ident = report.identity
    return (ident.address or ident.coingecko_id or ident.query).strip().lower()


def report_row(report: Report) -> dict[str, Any]:
    title = report.identity.name or report.identity.query
    if report.identity.symbol:
        title += f" ({report.identity.symbol})"
    return {
        "id": report.run_id, "subject_key": subject_key(report), "query": report.identity.query,
        "title": title, "mode": report.mode, "created_at": report.generated_at,
        "cost_usd": report.cost.total_usd, "claims": len(report.claims),
        "contradictions": len(report.contradictions),
        "unsourced": len(report.quality.unsourced_claim_ids),
        "json": render.to_json(report), "markdown": render.to_markdown(report),
    }


def create_app(settings: Settings, runner=run_report) -> FastAPI:
    """`runner` is replaceable so the tests never call a model."""
    app = FastAPI(title="crypto-diligence", version=__version__,
                  description="Information tool, not advice.")
    templates = Jinja2Templates(directory=str(TEMPLATES))
    db = Database(settings.data_dir / "service.sqlite3")
    lock = asyncio.Lock()
    paid_hashes: set[str] = set()  # filled by a payment webhook once the tier is enabled
    state = {"settings": settings, "db": db, "paid_hashes": paid_hashes}
    app.state.cd = state

    def page(request: Request, name: str, **ctx: Any) -> HTMLResponse:
        base = {"request": request, "disclaimer": DISCLAIMER, "version": __version__,
                "free_per_day": settings.free_reports_per_day,
                "paid_enabled": settings.paid_tier_enabled}
        return templates.TemplateResponse(request, name, {**base, **ctx})

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, error: str = "") -> HTMLResponse:
        return page(request, "index.html", reports=db.list_reports(30), error=error)

    @app.get("/health", response_class=PlainTextResponse)
    async def health() -> str:
        return "ok"

    @app.post("/reports")
    async def create(request: Request, query: str = Form(...), email: str = Form(...)):
        query = query.strip()
        if not QUERY_RE.match(query):
            raise HTTPException(400, "query: letters, digits, spaces and . : / ( ) & - only")
        if not EMAIL_RE.match(email.strip()):
            raise HTTPException(400, "a valid email address is needed for the daily quota")
        eh = email_hash(email, settings.email_salt)
        tier = tier_for(eh, settings, paid_hashes)
        today = datetime.now(UTC).date().isoformat()
        since = (datetime.now(UTC) - timedelta(days=settings.cache_days)).isoformat()
        cached = db.latest_for_subject(query.lower(), since)
        if cached:
            return RedirectResponse(f"/reports/{cached['id']}", status_code=303)
        if tier.reports_per_day is not None and db.quota_used(eh, today) >= tier.reports_per_day:
            raise HTTPException(
                429, f"daily quota reached: {tier.reports_per_day} reports per day per email "
                     "on the free tier; cached reports stay readable")
        if db.quota_used(GLOBAL_QUOTA_KEY, today) >= settings.global_reports_per_day:
            raise HTTPException(
                503, f"this deployment produced its {settings.global_reports_per_day} reports "
                     "for today; cached reports stay readable, try again tomorrow")
        async with lock:  # one model run at a time on a free deployment
            if tier.reports_per_day is not None \
                    and db.quota_used(eh, today) >= tier.reports_per_day:
                raise HTTPException(429, "daily quota reached")
            if db.quota_used(GLOBAL_QUOTA_KEY, today) >= settings.global_reports_per_day:
                raise HTTPException(503, "deployment cap reached for today")
            db.quota_increment(eh, today)
            db.quota_increment(GLOBAL_QUOTA_KEY, today)
            try:
                rep = await runner(query, settings)
            except Exception as exc:  # noqa: BLE001  (shown to the user, logged by uvicorn)
                raise HTTPException(502, f"report failed: {exc.__class__.__name__}") from exc
        row = report_row(rep)
        existing = db.latest_for_subject(row["subject_key"], since)
        if existing is None or existing["id"] != row["id"]:
            db.save_report(row)
        return RedirectResponse(f"/reports/{rep.run_id}", status_code=303)

    @app.get("/reports", response_class=HTMLResponse)
    async def list_reports(request: Request) -> HTMLResponse:
        return page(request, "list.html", reports=db.list_reports(200))

    @app.get("/reports/{report_id}.json")
    async def show_json(report_id: str) -> Response:
        row = db.get_report(report_id)
        if row is None:
            raise HTTPException(404, "no such report")
        return Response(row["json"], media_type="application/json")

    @app.get("/reports/{report_id}.md", response_class=PlainTextResponse)
    async def show_md(report_id: str) -> str:
        row = db.get_report(report_id)
        if row is None:
            raise HTTPException(404, "no such report")
        return row["markdown"]

    @app.get("/reports/{report_id}", response_class=HTMLResponse)
    async def show(request: Request, report_id: str) -> HTMLResponse:
        row = db.get_report(report_id)
        if row is None:
            raise HTTPException(404, "no such report")
        rep = Report.model_validate_json(row["json"])
        return page(request, "report.html", row=row, report=rep)

    @app.get("/tiers")
    async def tiers() -> dict[str, Any]:
        free = free_tier(settings)
        return {
            "free": {"reports_per_day": free.reports_per_day, "watchlist": False,
                     "export": False, "enabled": True},
            "deployment_reports_per_day": settings.global_reports_per_day,
            "paid": {"reports_per_day": None, "watchlist": True, "export": True,
                     "enabled": settings.paid_tier_enabled,
                     "note": "designed, switched off: PAID_TIER_ENABLED=false"},
        }

    @app.post("/watchlist")
    async def watch(email: str = Form(...), subject: str = Form(...)) -> dict[str, Any]:
        try:
            require_paid(settings, "portfolio watch")
        except PaidTierDisabled as exc:
            raise HTTPException(403, str(exc)) from exc
        eh = email_hash(email, settings.email_salt)
        if tier_for(eh, settings, paid_hashes).name != "paid":
            raise HTTPException(403, "paid tier only")
        db.watch(eh, subject.strip().lower(), datetime.now(UTC).isoformat())
        return {"watching": db.watchlist(eh)}

    @app.get("/reports/{report_id}/export.csv")
    async def export_csv(report_id: str) -> Response:
        try:
            require_paid(settings, "CSV export")
        except PaidTierDisabled as exc:
            raise HTTPException(403, str(exc)) from exc
        row = db.get_report(report_id)
        if row is None:
            raise HTTPException(404, "no such report")
        rep = Report.model_validate_json(row["json"])
        lines = ["id,agent,confidence,date,tags,text,sources"]
        for c in rep.claims:
            text = c.text.replace('"', '""')
            srcs = " ".join(s.url for s in c.sources)
            lines.append(f'{c.id},{c.agent},{c.confidence},{c.date or ""},'
                         f'"{" ".join(c.tags)}","{text}","{srcs}"')
        return Response("\n".join(lines) + "\n", media_type="text/csv")

    return app
