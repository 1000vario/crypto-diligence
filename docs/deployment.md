# Deployment

What the service needs, the local procedure that was tested, what it cost, and what a public
host would take. Dates are the dates of the tests; nothing here is estimated.

## What the service needs

- Python 3.12 or 3.13 and one process: `crypto-diligence serve` runs uvicorn in the foreground.
- A writable directory for its state, `CD_DATA_DIR` (default `./data`): the SQLite file
  `service.sqlite3` (reports, quota counters, watchlist), and `traces/<run id>.jsonl`, one
  file per report.
- Outbound HTTPS to the model provider and to the public data sources listed in the README
  (CoinGecko, DeFiLlama, Etherscan, DexScreener, GitHub, the Ethereum RPC of `CD_RPC_URL`,
  and the pages the docs investigator fetches).
- `ANTHROPIC_API_KEY` for reports. Without it the service starts and answers every read
  route; a `POST /reports` fails at the first model call.
- No database server, no queue, no worker: one report runs at a time behind an in-process
  lock, so a second form submission waits for the first one to finish.

## The local procedure, tested on 2026-10-11

```bash
git clone https://github.com/1000vario/crypto-diligence
cd crypto-diligence
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env            # then fill the keys you have
crypto-diligence serve --host 127.0.0.1 --port 8011
```

The default port is 8000; any free port works. The test ran on Windows 11 with Python 3.13,
`CD_DATA_DIR` pointing to an empty directory and no API key at all. Observed answers:

| Request | Answer |
|---|---|
| `GET /health` | 200, body `ok` |
| `GET /tiers` | 200, JSON: free tier 3 reports per day, deployment cap 30, paid tier `enabled: false` |
| `GET /` | 200, the HTML form, 3115 bytes, the sentence "Information tool, not advice." visible |
| `GET /reports` | 200, the (empty) list |
| `POST /watchlist` | 403, "portfolio watch belongs to the paid tier, which is not enabled on this deployment" |
| `POST /reports` with query `<x>` | 400, the allowed characters are named |
| `GET /reports/nope` | 404 |

The SQLite file appeared in `CD_DATA_DIR` at the first request. No report was produced during
this test because no model key was configured, so no model call was made and the per-email and
deployment counters stayed at zero.

Stopping the process is enough; the state survives in `CD_DATA_DIR`. Back that directory up
if the cached reports matter.

## Measured cost

| Item | Cost | How it is known |
|---|---|---|
| Hosting on a local machine | 0 USD | nothing to pay |
| Public data sources | 0 USD | free tiers and keyless endpoints, rate limits listed in the README |
| Model calls per report | not measured yet | each run prints its cost and writes it in the report and the trace; no run has been made without an Anthropic key |
| Web search | billed per request by Anthropic, on top of tokens | bounded by `CD_MAX_WEB_SEARCHES` per investigator call |

The daily model spend of a deployment is bounded by `CD_GLOBAL_REPORTS_PER_DAY` times the cost
of one report. The first measured cost per report will be published in the README with the
evals, and this table will carry it.

## A public host

Not done, and not decided: a public host means an account and a monthly price, which the
author decides on once the price is known. When it happens, what the service needs
from the host:

- one long-running process (`crypto-diligence serve --host 0.0.0.0 --port $PORT`) with HTTPS
  terminated in front of it, since uvicorn serves plain HTTP here;
- a persistent disk for `CD_DATA_DIR`, otherwise the cache and the quotas vanish at each
  restart;
- a proxy timeout above the duration of a report, which is minutes, because the form submission
  holds the connection until the report is written;
- the environment of `.env.example`: the model key, the free data keys, a private
  `CD_EMAIL_SALT`, and `PAID_TIER_ENABLED` left unset.

Expect the free tier to be abused if the cap is high: the deployment cap exists so that the
worst day costs a known amount.
