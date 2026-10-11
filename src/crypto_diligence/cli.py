"""Command line: one report, one tool call, identity resolution, or the web service."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from . import report as render
from .config import Settings, load_dotenv
from .identity import resolve_identity
from .orchestrator import run_report
from .providers import make_provider
from .providers.replay import RecordingProvider
from .tools import http
from .tools.context import ToolContext
from .tools.registry import all_specs, run_tool


def _parse_value(raw: str) -> object:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


async def _cmd_report(args: argparse.Namespace, settings: Settings) -> int:
    provider = make_provider(settings)
    recorder = RecordingProvider(provider, note=f"recorded for query {args.query!r}") \
        if args.record_cassette else None
    try:
        rep = await run_report(args.query, settings, mode=args.mode,
                               provider=recorder or provider)
    finally:
        await http.aclose()
    if recorder:
        recorder.save(Path(args.record_cassette))
    md = render.to_markdown(rep)
    if args.md:
        Path(args.md).write_text(md, encoding="utf-8", newline="\n")
    if args.json:
        Path(args.json).write_text(render.to_json(rep), encoding="utf-8", newline="\n")
    if not args.quiet:
        sys.stdout.write(md if not args.json_stdout else render.to_json(rep))
    cost = "unknown" if rep.cost.total_usd is None else f"${rep.cost.total_usd:.4f}"
    sys.stderr.write(f"run {rep.run_id}: {len(rep.claims)} claims, "
                     f"{len(rep.contradictions)} contradictions, cost {cost}, "
                     f"{rep.duration_s} s, trace {rep.trace_path}\n")
    return 0


async def _cmd_tool(args: argparse.Namespace, settings: Settings) -> int:
    specs = all_specs()
    if args.name not in specs:
        sys.stderr.write("unknown tool; available: " + ", ".join(sorted(specs)) + "\n")
        return 2
    params = {}
    for pair in args.params:
        key, _, raw = pair.partition("=")
        params[key] = _parse_value(raw)
    try:
        text, is_error = await run_tool(ToolContext(settings), args.name, params)
    finally:
        await http.aclose()
    sys.stdout.write(text + "\n")
    return 1 if is_error else 0


async def _cmd_identity(args: argparse.Namespace, settings: Settings) -> int:
    try:
        ident = await resolve_identity(args.query, ToolContext(settings))
    finally:
        await http.aclose()
    sys.stdout.write(ident.model_dump_json(indent=2) + "\n")
    return 0 if ident.resolved else 1


def _cmd_tools(_: argparse.Namespace, __: Settings) -> int:
    for name, spec in sorted(all_specs().items()):
        sys.stdout.write(f"{name}: {spec.description}\n")
    return 0


def _cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    from .service.app import create_app

    uvicorn.run(create_app(settings), host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crypto-diligence",
                                description="Sourced, dated facts about a protocol or token. "
                                            "Information tool, not advice.")
    p.add_argument("--env", default=".env", help="path of the .env file (default ./.env)")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("report", help="produce one report")
    r.add_argument("query", help="name, symbol or 0x contract address")
    r.add_argument("--mode", choices=["multi_agent", "single_agent"], default="multi_agent")
    r.add_argument("--md", help="write the Markdown report to this file")
    r.add_argument("--json", help="write the JSON report to this file")
    r.add_argument("--json-stdout", action="store_true", help="print JSON instead of Markdown")
    r.add_argument("--quiet", action="store_true", help="print nothing on stdout")
    r.add_argument("--record-cassette", help="save every model turn to this JSON file")

    t = sub.add_parser("tool", help="run one tool directly")
    t.add_argument("name")
    t.add_argument("params", nargs="*", help="key=value (JSON values accepted)")

    sub.add_parser("tools", help="list the tools")

    i = sub.add_parser("identity", help="resolve a query to its ids without any model call")
    i.add_argument("query")

    s = sub.add_parser("serve", help="run the web service")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(Path(args.env))
    settings = Settings.from_env()
    if args.command == "report":
        return asyncio.run(_cmd_report(args, settings))
    if args.command == "tool":
        return asyncio.run(_cmd_tool(args, settings))
    if args.command == "identity":
        return asyncio.run(_cmd_identity(args, settings))
    if args.command == "tools":
        return _cmd_tools(args, settings)
    if args.command == "serve":
        return _cmd_serve(args, settings)
    return 2


if __name__ == "__main__":
    sys.exit(main())
