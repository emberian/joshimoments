# jupiter_backfill — historical SOL up/down rounds for the opportunity census

Backfilled 2026-08-27 by the backfill deputy. Read-only throughout: GET requests against
Polymarket's public surfaces, bounded by a hard request budget, receipted. No order was
constructed, signed, or submitted. Feeds the registered opportunity census
(`../jupiter_conditional/REGISTRATION.md`, amendment v1.3) with weeks of real settled
rounds so it need not wait on the live collector (`../jupiter_collect/`) to accrue.

## Why this works at all (and its boundary)

The SOL up/down rounds surfaced in Jupiter are **Polymarket CLOB** markets
(`docs/reference/JUPITER_PREDICTION_MAP.md` §0). Jupiter's own API does not serve
historical round pricing — but Polymarket's public data plane does:

| surface | endpoint | role |
|---|---|---|
| Gamma | `gamma-api.polymarket.com/events?series_id=…&closed=true` | round enumeration + Polymarket's own resolution |
| data-api | `data-api.polymarket.com/trades?market={conditionId}` | tick-level FILLS, both outcome tokens per call — the primary price data |
| CLOB | `clob.polymarket.com/prices-history?market={tokenId}&fidelity=1` | 1-minute price points — fallback for fill-thin rounds |

The recurring series are `sol-up-or-down-5m` (gamma series id **10686**) and
`sol-up-or-down-15m` (id **10423**). Slugs are deterministic:
`sol-updown-{5m,15m}-{windowStartUnix}` — the suffix is the TRUE window start
(closeTime − horizon) on the 300 s grid. (Jupiter's `openTime` is LISTING time, not the
window start; rounds are listed ~24 h ahead and trade before their window.) The 5m series'
oldest closed round observed via keyset probing is **2025-12-18** — months more history is
reachable than was pulled; the pull was bounded deliberately.

## The rule-era discovery (read this before joining with the SOL reference)

Polymarket **changed the settlement rule mid-history**. Each round's `resolutionSource`
names its era, recorded per round as `ruleEra`:

- `endpoint` — `…/streams/sol-usd`: close ≥ open on the raw SOL/USD stream
  (`cryptoMarketConfig.twapEnabled: false`; e.g. the Aug 5 rounds).
- `twap60` — `…/streams/sol-usd-twap-60s-streams`: the 60 s-TWAP rule
  (`sol-5m-twap-60` config). This is the rule the jupiter_conditional step-0 gate proved
  15/15 against real outcomes — **that proof covers twap60-era rounds only**. Any census
  settlement reconstruction on endpoint-era rounds must use the endpoint rule (rule (c)
  of the registration's candidate set) and say so.

The receipt reports the per-era counts; the era boundary falls inside the backfilled span.

## Files (under `state/prediction/backfill/`)

- `backfill-<stamp>-{enum,trades,prices,reconcile}.jsonl` — RAW retention: one line per
  HTTP request with `url`, `httpStatus`, `attempt`, `bodyText` (verbatim provider bytes as
  text), and both local clocks (`arrivalUnixUs`, `arrivalMonotonicNs`). Provider
  timestamps live inside the bodies in their declared units.
- `backfill-<stamp>-rounds.jsonl` — the DERIVED join shape (below), one line per round.
- `backfill-<stamp>.receipt.json` — budget, per-stage request counts, spans, grid
  reconciliation, gaps (durable, never silent), label-source and rule-era tallies.

## The round record (`contract: joshi.jupiter_backfill.round.v1`)

```json
{
  "roundKey": "5m-1787845500",          // horizon-windowStart; THE join key
  "horizon": "5m",                       // 5m | 15m
  "windowStartUnix": 1787845500,         // true window start (slug-derived, grid-checked)
  "closeTimeUnix": 1787845800,           // windowStart + horizon (checked at parse)
  "slug": "sol-updown-5m-1787845500",
  "gammaEventId": "916172", "gammaMarketId": "3903657",
  "conditionId": "0x…",                  // Polymarket condition (both outcomes)
  "clobTokenIds": ["…", "…"],           // ERC1155 token ids, index-aligned to outcomes
  "outcomes": ["Up", "Down"],
  "ruleEra": "twap60",                   // twap60 | endpoint | unknown
  "resolutionSource": "https://…",
  "listedAt": "2026-08-26T15:52:39Z",   // market creation = listing (pre-window quoting)
  "volumeUsd": 1088.9,                   // provider claim
  "trades": {
    "fetched": true, "requests": 1, "truncated": false, "count": 180,
    "inWindowCount": {"up": 54, "down": 120, "preWindow": 6, "postClose": 0},
    "rows": [[t, outcomeIndex, price, size, side], …]   // ascending t; FULL lifetime:
  },                                     // pre-window + in-window + post-close pin
  "priceHistory": {"fetched": false, "up": [[t, p], …], "down": […]},
                                         // 1-min points, [start−3600, close+300], thin rounds only
  "settlement": {
    "label": "Down", "labelSource": "gamma-resolution",
    "labelGamma": "Down", "labelPin": "Down",
    "gamma": {"closed": true, "umaResolutionStatus": "resolved",
               "outcomePrices": ["0", "1"], "closedTime": "…"}
  }
}
```

Zone semantics: window is `[windowStartUnix, closeTimeUnix)`; a trade at exactly close is
post-close (settlement-pin zone). `rows` prices are dollars-per-share in [0,1], provider
claims verbatim; trades are **fills** — realistic transacted prices, never guaranteed
fillable size. `side` is the taker side.

## Settlement labels, by reliability

1. `gamma-resolution` — Polymarket's own resolution: `closed=true` AND `outcomePrices`
   exactly 1/0. The cleanest source; cross-checked against the live collector's
   settlement records where both exist (they matched on the overlap round sampled).
2. `terminal-pin` — fallback: last post-close trade per side, winner ≥ 0.90 with the
   other side ≤ 0.10; conflicted pins stay unlabeled. Corroborated 3/4 vs the Chainlink
   reference by the conditional deputy.
3. `gamma-resolution-pin-disagrees` — both computed, they differ; both stored; gamma
   label carried, the disagreement is data.
4. `unlabeled` — neither source; counted, never guessed.

A near-pin (0.9995/0.0005) with `closed=false` — the stuck-open Aug 5 zombie shape — is
NOT a gamma resolution and falls through to the pin labeler. Enumeration covers gamma
`closed=true` rounds only; stuck-open rounds are absent by construction (receipted grid
`absentSlots` marks the holes).

## Consuming it (the census)

```python
from joshi_analysis.jupiter_backfill import reads, legin
rounds = reads.load_rounds(path)                       # round dicts as above
zones = reads.split_zones(r["trades"]["rows"], r["windowStartUnix"], r["closeTimeUnix"])
```

Join to the SOL reference (`state/prediction/fine/`, Kraken/Coinbase trades) on
`roundKey`'s window against the step-function series — same 300 s grid. The fine Kraken
span covers ~10 days back from 2026-08-27; backfilled rounds older than that have
settlement labels but NO reference join (regime conditioning is unavailable there — count
them out explicitly, don't impute).

The first-pass estimand (`python -m joshi_analysis.jupiter_backfill --rounds …`) runs the
v1.2(a)/(b) leg-in min-combined-cost as its FILLS-BASED ANALOG, writing
`state/prediction/study/backfill-legin-<stamp>.json` with the fee floor and the
oracle-window caveat printed beside every number. The registered quoted-price version
still belongs to the collector data when it ripens.
