# crypto-diligence

**Information tool, not advice.** This software describes facts found in public sources about a
crypto protocol or token, each with its source, its date and a confidence level. It never
recommends buying, selling or holding anything, and its reports may be incomplete or out of date.

Ask "what is known about this protocol or this token?" and four specialised investigators look at
the chain, the market, the documentation and the incident history, in parallel. An orchestrator
resolves the subject's identity first, launches them, flags the contradictions between their
findings without smoothing them, and assembles a report in Markdown and JSON. Every claim carries
its sources, its date and one of three confidence levels. Every model call and every tool call is
logged with its input, its output and its token cost, and the cost of each report is printed in
the report.

```text
crypto-diligence report "Uniswap" --md uniswap.md --json uniswap.json
run <run id>: <n> claims, <m> contradictions, cost $<usd>, <seconds> s, trace data/traces/<run id>.jsonl
```

## How it works

```text
             query: a name, a symbol or an Ethereum contract address
                                     |
                     identity resolution (deterministic, no model)
         CoinGecko, DeFiLlama, the contract itself: ids, address, website, GitHub
                                     |
        +-------------+--------------+--------------+----------------+
        |             |                             |                |
     onchain        market                        docs           incidents
  public RPC,     CoinGecko,                  project site,    DeFiLlama hacks,
  Sourcify,       DeFiLlama,                  GitHub, audit    official statements,
  Ethplorer,      DexScreener                 pages, web       press, web search
  Etherscan                                   search
        |             |                             |                |
        +-------------+--------------+--------------+----------------+
                                     |
                      contradiction pass (one model call)
                                     |
                 report: Markdown and JSON, trace, cost, quality checks
```

Each investigator has its own system prompt, its own tools and no view of the others. It works
in a loop: the model asks for tool calls, the tools answer, until the model returns a JSON object
of claims and open questions that matches a schema. The orchestrator does no research. It resolves
the identity with the public APIs, runs the four investigators concurrently, numbers their claims,
makes a single model call to find contradictions between claims, computes the quality checks and
renders the report.

A claim is one checkable fact with:

- `sources`: the URLs the investigator read through a tool in that run. A claim with no source
  is kept, marked **NO SOURCE** in the report and counted as a failure. It is never dropped
  silently.
- `date`: the date of the event or of the reading, ISO format. Prices, volumes, TVL and holder
  shares are dated with the day of the run because they move.
- `confidence`: `high` when read from a primary source (the chain, the project's own contract or
  API, an official statement) or stated identically by two independent sources; `medium` for one
  secondary source with no contradiction found; `low` when inferred, partial, old or seen in one
  weak source only.
- `tags`: a fixed vocabulary per investigator (`contract`, `proxy`, `holders`, `price`,
  `discrepancy`, `audit`, `exploit`, `regulator` and so on).

When two sources disagree, the investigator writes both figures in one claim tagged
`discrepancy`. The contradiction pass then looks across investigators for claims that cannot both
be true (two dates for one event, "audited" against "no audit found", an incident against "no
incident found") and lists them with a severity. It adds no fact and resolves nothing.

Neutrality is checked by a list of regular expressions
(`src/crypto_diligence/data/neutrality_patterns.txt`) run over every claim, open question,
contradiction and note. Matches are listed in the report and counted by the evals. The list is
edited when it produces a false positive; the reports are never edited.

## Why a hand-written loop on the Anthropic SDK

The brief asked for the Claude Agent SDK or the OpenAI Agents SDK, with a justification. The
system runs on neither, for three reasons that were tested, not assumed:

- **Exact accounting.** Each investigator must log the token usage and cost of every model call
  and the input and output of every tool call. A loop on `anthropic.AsyncAnthropic().messages.create`
  gives the usage of each call directly (`src/crypto_diligence/agents/base.py`, about 200 lines).
  The Claude Agent SDK runs Claude Code's own runtime with its built-in tools and context
  management, which is the wrong surface for investigators that must only see their scoped tools.
- **Tests without a network.** The unit tests and the CI replay recorded HTTP answers
  (`tests/fixtures/http`) and recorded model turns (cassettes). A `ReplayProvider` plays a
  cassette and a `RecordingProvider` writes one from a live run. That needs the model call to be
  a plain function, which a framework hides.
- **A real port.** The OpenAI Agents SDK ties the orchestration to one vendor's abstractions. A
  thin `ModelProvider` protocol (`src/crypto_diligence/providers/base.py`) with two
  implementations keeps the agents, tools, traces, reports and evals vendor-neutral.
  `AnthropicProvider` uses the Messages API with adaptive thinking, a cached system prompt,
  structured JSON output and the hosted web search tool. `OpenAIProvider` uses the Chat
  Completions API and drops the hosted web search, which it does not have. `CD_PROVIDER=openai`
  switches the whole system.

## Installation

Python 3.12 or newer.

```bash
git clone https://github.com/1000vario/crypto-diligence
cd crypto-diligence
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env            # then fill in the keys you have
crypto-diligence tools          # lists the tools; needs no key
```

## API keys and how to get the free ones

| Variable | Needed for | Cost | Where |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | every report with the default provider | paid per token, prepaid credits | https://console.anthropic.com |
| `OPENAI_API_KEY` | only with `CD_PROVIDER=openai` | paid per token | https://platform.openai.com |
| `ETHERSCAN_API_KEY` | contract creation date and Etherscan verification status | free plan after creating an account | https://etherscan.io/myapikey |
| `COINGECKO_API_KEY` | optional, raises CoinGecko's rate limit | free "Demo" plan | https://www.coingecko.com/en/developers/dashboard |
| `GITHUB_TOKEN` | optional, raises the GitHub API limit from 60 to 5000 requests per hour | free, a fine-grained token with no permission | https://github.com/settings/tokens |

Without an Etherscan key, the `get_contract_creation` tool returns an error that the on-chain
investigator reports in its open questions; Sourcify still answers the verification question.
Without a CoinGecko key, the public endpoints work but throttle bursts with HTTP 429, which the
market investigator reports as a tool error.

No key at all is needed for Sourcify, DeFiLlama, DexScreener, Ethplorer (its public `freekey`)
and the public Ethereum RPC (`https://ethereum-rpc.publicnode.com`, changeable with `CD_RPC_URL`).

`.env` is ignored by git. A secret scan runs before every push, outside the CI.

## Usage

```bash
# A full report: four investigators, then the contradiction pass
crypto-diligence report "Uniswap" --md uniswap.md --json uniswap.json

# The same subject by contract address, which removes any symbol ambiguity
crypto-diligence report 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984 --json uni.json

# The baseline the evals compare against: one investigator with every tool
crypto-diligence report "Uniswap" --mode single_agent --md uniswap-single.md

# Record the model turns of a run as a cassette for the tests
crypto-diligence report "Uniswap" --record-cassette tests/cassettes/uniswap.json

# Resolve an identity without calling a model (exit code 1 when unresolved)
crypto-diligence identity "Tether"

# Call one tool directly, with JSON values when needed
crypto-diligence tool analyze_bytecode address=0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48
crypto-diligence tool coingecko_coin id_or_address=uniswap lookup=id
crypto-diligence tool get_token_holders address=0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984 limit=10

# The web service
crypto-diligence serve --host 127.0.0.1 --port 8000
```

`report` prints one line on stderr with the run id, the number of claims and contradictions, the
cost, the duration and the trace path, then writes the files you asked for (`--json-stdout`
prints the JSON instead). Every run also writes `data/traces/<run id>.jsonl`: one JSON line per
model call (agent, model, stop reason, input, output and cache tokens, cost) and per tool call
(agent, tool, input, an excerpt of the output, its size, duration, error flag).

Settings read from `.env` or the environment: `CD_MODEL_ORCHESTRATOR` and `CD_MODEL_SUBAGENT`
(default `claude-opus-5-5`), `CD_EFFORT` (default `medium`), `CD_MAX_TURNS` (12),
`CD_MAX_WEB_SEARCHES` (6 per investigator), `CD_MAX_TOKENS` (8000 per model call), `CD_RPC_URL`,
`CD_DATA_DIR` (`./data`). The full list is in `.env.example`.

### Tools, by investigator

| Investigator | Tool | Source | Key |
|---|---|---|---|
| onchain | `get_contract_source` | Sourcify v2, Etherscan v2 | Etherscan optional |
| onchain | `analyze_bytecode` | public RPC: code size, sensitive selectors (mint, pause, blacklist, upgrade, owner), proxy pattern and implementation, `owner()`, `paused()` | none |
| onchain | `get_token_metadata` | public RPC: name, symbol, decimals, total supply | none |
| onchain | `get_contract_creation` | Etherscan v2 | Etherscan |
| onchain | `get_token_holders` | Ethplorer: top holders, share, contract flag | none |
| market | `coingecko_search`, `coingecko_coin`, `coingecko_market_chart` | CoinGecko: ids, price, volume, market cap, supply, 90-day history, all-time high and low | CoinGecko optional |
| market | `defillama_search`, `defillama_protocol`, `defillama_price` | DeFiLlama: slugs, TVL by chain and over time, audits, hallmarks, price with its own confidence | none |
| market | `dexscreener_token` | DexScreener: pairs, venues, liquidity, 24 h volume, pair age | none |
| docs | `fetch_page` | any public http(s) page as text, private hosts refused | none |
| docs | `github_repo`, `github_search_repos` | GitHub REST: dates, licence, archived flag, latest commit, contributors | GitHub optional |
| docs, incidents | `defillama_protocol`, `web_search` | DeFiLlama audit links; the provider's hosted web search (Anthropic only) | none |
| incidents | `defillama_hacks` | DeFiLlama's exploit database | none |

Tool outputs are JSON. A tool never raises: an error is returned as a value, logged in the trace
and handed to the model, which must report it instead of guessing.

## Example report

`docs/example-report.md` shows the exact layout produced by `crypto-diligence report --md`:
the disclaimer first, then the subject as resolved, the claims per investigator with their
sources, confidence and date, the contradictions, the open questions, the tool errors, the
quality checks and the cost table. It is rendered from the synthetic report used by the test
suite, so that the format is documented without inventing facts. The first real reports will
be published under `evals/results/` with their date and their cost.

## The web service

```bash
crypto-diligence serve            # http://127.0.0.1:8000
```

| Route | What it does |
|---|---|
| `GET /` | the form (name, symbol or address; email) and the recent reports |
| `POST /reports` | produces a report, or redirects to the cached one for the same subject |
| `GET /reports` | every public report |
| `GET /reports/{id}`, `.md`, `.json` | one report, in HTML, Markdown or JSON |
| `GET /tiers` | the tiers and whether the paid one is enabled |
| `GET /health` | `ok` |
| `POST /watchlist`, `GET /reports/{id}/export.csv` | paid tier: HTTP 403 while it is off |

**Free tier.** Three reports per day per email address (`CD_FREE_REPORTS_PER_DAY`). The email
is never stored: the quota table keys on a salted SHA-256 hash (`CD_EMAIL_SALT`). Reports are
public and a subject already reported in the last seven days (`CD_CACHE_DAYS`) is served from
the cache instead of being run again. One report runs at a time. A deployment-wide cap
(`CD_GLOBAL_REPORTS_PER_DAY`) bounds the daily model spend whatever the number of email
addresses used.

**Paid tier, designed and switched off.** Unlimited reports, a portfolio watchlist and CSV
export exist in the code (`src/crypto_diligence/service/tiers.py`). The routes answer HTTP 403
while `PAID_TIER_ENABLED=false`, no payment provider is wired, and the membership set that a
payment webhook would fill stays empty. Switching it on is a decision by the author, not a
technical step, and it is not planned.

The tested local procedure and its measured cost are in `docs/deployment.md`.

## Evals

`evals/cases/` holds 20 hand-written truth sheets, dated 2026-10-11:

| Category | Cases |
|---|---|
| healthy | Uniswap, Chainlink, Aave, Lido, Maker (Sky), ENS, Rocket Pool, Compound |
| exploit or depeg | Terra (USTC), Euler, Curve, Nomad, Beanstalk, Balancer |
| abandoned | Fei, Iron Finance, SafeMoon |
| sensitive contract functions | USDC, USDT, WBTC |

Each sheet gives the query as a user would type it, the resolved identity, the facts a correct
report must contain (`expected_facts`, one regular expression each, with the investigator that
should find it), the statements it must not contain (`forbidden_facts`), the contradictions the
orchestrator must flag (`expected_contradictions`), the sources read with their access date, and
the deterministic `checks`: the tool calls whose answers back the sheet.

```bash
python evals/run.py --dry-run                 # validates the 20 sheets, calls no model
python evals/verify_cases.py                  # re-runs every check against the live APIs,
                                              # writes evals/evidence/<case>.json with the date
python evals/run.py --mode multi_agent        # one report per case, scored, rates published
python evals/run.py --mode single_agent       # the same with one investigator and every tool
python evals/run.py --cases euler usdc --max-usd 5
python evals/run.py --from-results evals/results/<date>-multi_agent   # rescore saved reports
```

Scores, per case and averaged (`src/crypto_diligence/evals.py`):

| Metric | Definition |
|---|---|
| recall | share of `expected_facts` matched by at least one claim |
| invention failures | claims without a source, plus claims citing a host that no tool reached during the run, plus `forbidden_facts` matched. A case is "free of invention" at zero. |
| coherence | share of `expected_contradictions` present in the contradiction list |
| neutrality violations | matches of the recommendation pattern list |
| investigators failed | investigators that returned no valid answer |
| cost, duration, web search requests | read from the report |

### Results

No eval run has been published yet. The code, the sheets and the scorer are in place; the
first run needs an Anthropic API key and a budget, both decided by the author. When it runs,
this section will carry the date, the number of cases, the rates for `multi_agent` and for
`single_agent` side by side, and the measured cost per report. Until then, every rate quoted
elsewhere about this system is unmeasured.

## Limits

- On-chain tools cover Ethereum mainnet only (RPC, Sourcify chain id 1, Ethplorer). For an asset
  on another chain the identity notes list its platforms and the market and documentation
  investigators still work.
- A symbol can match several assets. The resolver prefers an exact symbol, then an exact name,
  then the best market cap rank, and writes the other matches in the report. Pass the contract
  address when it matters.
- Selector presence in bytecode means the function exists; it says nothing about who may call
  it. The prompts enforce the wording "the bytecode contains".
- CoinGecko's free tier throttles bursts; DeFiLlama's protocol page for the largest protocols
  exceeds the 30 MB cap of the tool (Curve); GitHub allows 60 unauthenticated requests per hour
  and `github_repo` uses three. Each case is reported as a tool error, visible in the report.
- Hosted web search exists only with the Anthropic provider.
- A report takes minutes and the service runs one at a time: it is a free service for a few
  reports a day, not a job system.
- A report states what the sources said at the time of the run. It is not updated.
- Cost per report is measured by the run and printed in the report. No live run has been
  published yet, so no figure is quoted here.

## Tests and CI

```bash
pytest -q                               # no network, no API key
ruff check src tests evals scripts
```

The tests replay recorded HTTP answers from `tests/fixtures/http` (recorded by
`scripts/record_fixtures.py`, which needs the network but no key) and synthetic model turns.
GitHub Actions runs both commands on every push and pull request, on Python 3.12 and 3.13.

## Licence

MIT. See `LICENSE`.
