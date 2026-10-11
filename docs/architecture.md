# Architecture

Information tool, not advice. This document describes how the code is organised and why.

## Modules

| Path | Role |
|---|---|
| `src/crypto_diligence/cli.py` | the `crypto-diligence` command: `report`, `tool`, `tools`, `identity`, `serve` |
| `orchestrator.py` | `run_report()`: identity, the four investigators in parallel, claim numbering, the contradiction pass, quality checks, cost, trace |
| `identity.py` | deterministic resolution of a name, symbol or address into the ids each source uses; ambiguities written in `Identity.notes` |
| `agents/base.py` | the loop that runs one investigator: model turn, tool calls, until a JSON answer matching `FINDING_SCHEMA` |
| `agents/prompts.py` | shared rules, then one system prompt per investigator, the single-investigator baseline and the contradiction pass |
| `providers/base.py` | `ModelProvider` protocol, `Turn`, `ToolSpec`, `ToolCall`, `ToolResult`; history items are plain dicts so cassettes serialise as JSON |
| `providers/anthropic_.py` | Messages API: adaptive thinking, cached system prompt, structured output, hosted web search, exact usage |
| `providers/openai_.py` | Chat Completions API; the hosted web search tool is dropped |
| `providers/replay.py` | `ReplayProvider` plays a cassette; `RecordingProvider` records one from a live provider |
| `tools/registry.py` | tool specs, the tool set of each investigator, `run_tool()` which never raises |
| `tools/onchain.py`, `market.py`, `docs.py`, `incidents.py` | the tools, one async function each, JSON in and out |
| `tools/http.py` | one `httpx` client, timeouts, bounded bodies, credential scrubbing in URLs, errors as values |
| `tools/fixtures.py` | recording and replaying transports for the tests |
| `schemas.py` | Pydantic models: `Claim`, `Finding`, `Contradiction`, `Identity`, `Report`, usage and cost records |
| `trace.py` | JSON Lines trace of every model call and tool call of a run |
| `pricing.py` | prices per million tokens with their date; a model missing from the table yields an unknown cost, never a guessed one |
| `neutrality.py` | the recommendation pattern check over a whole report |
| `report.py` | Markdown and JSON rendering; the disclaimer comes first, always |
| `evals.py` | truth sheet loading and scoring |
| `service/app.py`, `db.py`, `tiers.py` | FastAPI service, SQLite storage, free and paid tiers |
| `evals/run.py`, `evals/verify_cases.py`, `evals/cases/`, `evals/evidence/` | the eval runner, the live check of the sheets, the sheets, their evidence |
| `scripts/record_fixtures.py` | records the HTTP answers the tests replay |

## Data flow of one report

1. `resolve_identity()` queries CoinGecko (search, or the contract page when the query is an
   address), then DeFiLlama's protocol list, and reads the token metadata from the chain when
   CoinGecko has nothing. It fills `Identity` (name, symbol, address, CoinGecko id, DeFiLlama
   slug and parent, website, GitHub repositories) and writes every doubt in `notes`: other
   matches, a weak match without market cap rank, an address taken from DeFiLlama rather than
   CoinGecko. No model is involved, so the resolution is reproducible and testable.
2. The four investigators receive the same task message (the identity and today's date) and
   their own system prompt and tool set. They run concurrently with `asyncio.gather`; an
   exception in one becomes a failed `Finding` with its reason, and the others continue.
3. Each investigator loops: the model answers with text or tool calls; tool calls are executed
   concurrently, their results appended; when the model stops with `end_turn`, its final text
   is parsed against `FINDING_SCHEMA`. Structured output is requested from providers that
   support it. The loop stops after `CD_MAX_TURNS` turns or `CD_MAX_TOKENS` per call, and
   says so.
4. The orchestrator numbers the claims `<investigator>-<n>`, keeps the ones without a source
   (flagged, never dropped), and makes one model call with every claim as input to list the
   contradictions. It does not research anything and adds no claim.
5. `neutrality.check_report()` scans claims, open questions, contradictions and notes.
6. `cost_summary()` reads the trace: usage per model call priced by `pricing.py`, tool calls,
   hosted web search requests, cost by investigator.
7. `report.to_markdown()` and `to_json()` render; the CLI prints a one-line summary on stderr.

## The trace

`data/traces/<run id>.jsonl`, one JSON object per line:

- `run_start`, `run_end` with the run id;
- `model_call`: agent, model, turn, stop reason, input, output, cache read and cache write
  tokens, hosted web search requests, cost in USD (or null when the model is not in the pricing
  table), duration;
- `tool_call`: agent, tool, input, an excerpt of the output (2000 characters), the output size,
  an estimated token size of the output (characters divided by four, labelled as an estimate),
  error flag, duration, and whether the call ran on the provider's side (web search).

The exact tokens a tool output adds are visible in the `input_tokens` of the next model call.

## Decisions

- **Claims without a source stay in the report.** Dropping them would hide a model failure.
  They are marked in bold, listed in the quality checks and counted as invention by the evals.
- **No averaging of sources.** Two figures that disagree are written side by side with the tag
  `discrepancy`. The contradiction pass is told not to flag such a claim, since it already
  reports the disagreement.
- **The orchestrator makes exactly one model call.** Resolution is deterministic; research is
  the investigators' job; the one judgement the orchestrator makes is whether two claims can
  both be true. This keeps its cost small and its output checkable.
- **Tools never raise.** An error is a value: it reaches the model, which must report it as an
  open question, and the trace, where it can be counted. A tool that raised would end the
  investigator with no claim at all.
- **Credentials never reach a URL that is stored.** `http.scrub_url()` removes API key
  parameters before a URL is used as a fixture key, in a trace or in a report.
- **Emails are hashed.** The service keys its quota on a salted SHA-256 hash and stores no
  address.
- **The paid tier is coded and off.** `PAID_TIER_ENABLED=false` makes its routes answer 403;
  no payment provider is wired. The decision to enable it belongs to the author.
- **Prices carry a date.** `pricing.py` states the day its table was checked, and every report
  repeats it. A model absent from the table gives an unknown cost rather than a wrong one.
