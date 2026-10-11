# Example report

Information tool, not advice. This page shows the exact layout that `crypto-diligence report --md` produces.
It is rendered from the synthetic report used by the test suite (`tests/helpers.py`), so the format is
documented without inventing facts: the figures, the sources and the contradiction below are placeholders,
and no model was called to produce them. Real reports, with their date and their measured cost, will be
published under `evals/results/` once an eval run has been made.

What a reader finds, in this order: the disclaimer; the subject as resolved by the identity step; the claims
of each investigator with their sources, confidence level and date; the contradictions flagged by the
orchestrator; the open questions; the quality checks; the cost table; the path of the trace.

---

# Due-diligence report: Uniswap (UNI)

> Information tool, not advice. This report describes facts found in public sources, each with its source, its date and a confidence level. It does not recommend buying, selling or holding anything, and it may be incomplete or out of date.

Generated 2026-10-11T12:00:00+00:00. Mode: multi_agent. Provider: replay. Models: orchestrator x, subagent x. Run id: 20261011-deadbeef.

## Subject

- Query: Uniswap
- Resolved: yes
- Name: Uniswap
- Symbol: UNI
- Chain: ethereum
- CoinGecko id: uniswap

## Claims

### On-chain (1 claims)

- **onchain-1** The contract is verified on Sourcify. (confidence: high; date: 2026-10-11; tags: contract)
  Sources: [Sourcify](https://sourcify.dev/server/v2/contract/1/0x1f98)

### Market (1 claims)

- **market-1** Volume was 10 million USD on 2026-10-10. (confidence: medium; date: 2026-10-10; tags: volume)
  **NO SOURCE: this claim failed the sourcing rule and must not be relied on.**

## Contradictions

- **volume** (severity low; claims market-1, onchain-1): Illustration only: a synthetic contradiction.

## Open questions

- Market: Which venue carries the volume?

## Quality checks

- Claims: 2
- Claims without a source: 1 (market-1)
- Neutrality violations: 0
- Investigators failed: none

## Cost and duration

| Item | Value |
|---|---|
| Total cost | $0.0000 |
| Model calls | 0 |
| Tool calls (client side) | 0 |
| Web search requests (server side) | 0 |
| Input tokens | 0 |
| Output tokens | 0 |
| Cache read tokens | 0 |
| Cache write tokens | 0 |
| Duration | 12.5 s |

By agent: 

Pricing: Prices per MTok checked on 2026-10-11; web search billed per request.

