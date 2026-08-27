# jupiter_base_rate v1 — pre-registered base-rate + chop study

Registration version: `joshi.jupiter_base_rate.registration.v1`
Registered: 2026-08-27, BEFORE the reference series was fetched and BEFORE any window
statistic, base rate, or signature curve was computed.

## Author knowledge disclosure

The choices below were made with the following prior knowledge, disclosed in full:

- `docs/reference/JUPITER_PREDICTION_MAP.md` in its entirety: the settlement mechanics, the
  ties→Up rule, the fee model (`fee ≈ 0.070·p(1−p)`, ≈1.75% of the $1 payout at p=0.5, a
  working floor of ~2–3.5% with spread and overround), and the trading thesis under test
  ("SOL is choppy at 5/15m, so both sides keep printing cheap" — i.e. an expectation of
  mean reversion / falling σ²(τ)). The author therefore knows what result would flatter
  the thesis. The estimands and gates below were fixed before looking.
- The live collector's output (`state/prediction/collect-*.jsonl`): round metadata for five
  SOL rounds of 2026-08-27, including the discovery that current rounds settle on a
  **TWAP** rule while an older stale round carries the endpoint (close-vs-open) rule, and
  one stale round's terminal pricing (1.000000 / 0.001 micro-USD). No implied-probability
  path was plotted or aggregated.
- From probing the candidate reference APIs (2026-08-27, immediately before this
  registration): ~11 minutes of Coinbase SOL-USD 1-minute candles (13:00–13:10 UTC, prices
  in the $104.4–104.8 band) and the head of a Kraken OHLC response from ~12 hours earlier
  (prices near $101.5). The author therefore knows SOL trades near $104 and rose roughly
  3% over the preceding half-day. No statistic beyond eyeballing those two snippets was
  computed.

Any deviation from this protocol requires a new registration version; results produced
under a deviation must say so.

## 1. The settlement reference, and what this study actually measures

The contracts settle on **Chainlink SOL/USD data streams** — per the captured
`rulesPrimary` text, current (2026-08-27) rounds use the **TWAP** variant: the round
resolves Up iff the time-weighted average price of the window, from the Chainlink
`sol-usd-twap-60s-streams` product, is ≥ the price at the beginning of the range. An
older captured round uses the endpoint variant (close ≥ open on the `sol-usd` stream).
Both streams are credentialed, pull-based products; neither is freely retrievable.

**This study runs on an APPROXIMATION of that reference and says so on every number:**

- Primary series: **Coinbase Exchange SOL-USD 1-minute candles** (public, keyless,
  USD-quoted, arbitrary history). Point-price at grid instant T := the OPEN of the
  1-minute candle stamped T (first trade at/after T). Window TWAP := the arithmetic mean
  of the 1-minute closes inside the window.
- Declared basis risks: (1) single-venue spot vs Chainlink's multi-venue aggregate — the
  rule text explicitly disclaims spot markets; (2) last-trade minute sampling vs a
  continuous 60s-TWAP stream; (3) candle discreteness at the boundary (first trade at/after
  T vs the stream value at T); (4) the rule's "price at the beginning of that range" is
  taken as the point-price at T — whether the protocol reads it from the TWAP stream or the
  point stream at T is ambiguous in the rule text and is NOT resolved here.
- Cross-venue dispersion is quantified (not assumed): Kraken SOLUSD 1-minute closes over
  the available overlap (~720 minutes), reported as median and p95 absolute relative
  difference against Coinbase closes at identical timestamps. This bounds the venue half
  of the basis, not the aggregation half.
- The settlement-exact version requires **Chainlink Data Streams API access**
  (credentialed): historical report retrieval for stream `sol-usd-twap-60s-streams` (and
  `sol-usd` for endpoint-rule rounds). Until that exists, no number in this study is a
  settlement-exact base rate, and none will be quoted as one.

## 2. Data windows and denominators (fixed in advance)

- Span: the **30 days ending at the top of the last completed 5-minute grid boundary
  before fetch time** (2026-08-27). One fetch, bounded: ≤200 requests of ≤300 candles,
  receipts and gap lines under `state/prediction/reference/`.
- 5m windows: consecutive `[T, T+300)` for every unix T ≡ 0 (mod 300) in span. Expected
  denominator ≈ 8,640.
- 15m windows: consecutive `[T, T+900)` for every unix T ≡ 0 (mod 900) in span (matching
  the product's observed anchoring; overlapping 300s-shifted 15m windows are NOT computed).
  Expected denominator ≈ 2,880.
- A window is excluded (counted, with reason, never imputed) if the boundary candle at T
  or T+H is absent, or (TWAP outcome) any interior minute candle is absent.

## 3. Estimands (all of them, nothing post hoc)

Per horizon H ∈ {300 s, 900 s}:

1. **P(up), endpoint rule**: fraction of windows with `price(T+H) ≥ price(T)` (exact
   Decimal comparison; ties → Up, per the rule). With Wilson 95% interval and denominator.
2. **P(up), TWAP rule**: fraction with `TWAP[T, T+H) ≥ price(T)`, same treatment. This is
   the rule current rounds actually state.
3. **Rule-disagreement rate**: fraction of windows where the two outcomes differ — how
   often the rule variant flips the label.
4. **Return magnitude**: distribution of `log(price(T+H)/price(T))` — quantiles (1, 5, 10,
   25, 50, 75, 90, 95, 99), mean absolute value, and the fraction of windows with
   |simple return| < 10 bps (the near-tie zone where the TWAP/endpoint distinction and the
   snapshot mechanism dominate).
5. **σ²(τ) chop-vs-trend**: the EXISTING `joshi_analysis.signature` instrument, unmodified,
   on the full 1-minute series (bars = (timestamp_ms, close)). Read: wall-time σ²(τ) at
   τ = 60, 300, 900 s (and the instrument's other default lags). Falling curve ⇒ mean
   reversion (the thesis); rising ⇒ trend. The verdict is read off the curve, not fit.
6. **Fee floor, stated beside every base rate**: the ≈1.75% midpoint explicit fee and the
   ~2–3.5% working floor (map §4). No deviation of P(up) from 0.5 is quoted as an edge
   unless the implied per-contract value exceeds the working floor — and even then only as
   a *reference-approximate, retrospective* observation, never a live-executable claim.
7. **Collected-round inventory** (reporting, not inference): from
   `state/prediction/collect-*.jsonl`, the count of genuine live rounds captured per
   horizon (a round is genuine iff its `closeTime` falls inside the collection file's
   arrival span, padded by one horizon on each side — the API's `isLive` flag is known to
   leak stale rounds, and `openTime` on these CLOB rounds is the listing time, not the
   window start; the true window is `[closeTime − H, closeTime]`), rule-variant counts,
   and any settlements captured.

## 4. Explicitly out of scope for v1 (next wave, not silently absent)

- **Hawkes branching ratio / criticality** on SOL trade arrivals: no per-trade SOL
  arrival series exists in this repo's collections today (1-minute candles are not
  arrivals). Stated as a next-wave item; nothing is faked.
- **Mispricing / calibration of contract prices vs base rate**: requires the live-collected
  implied-probability paths to accumulate rounds (they only accrue from collector turn-on,
  2026-08-27). Not computable retrospectively; not attempted here.
- Any per-hour-of-day, per-weekday, or otherwise conditioned base rate: not registered,
  not computed (multiplicity discipline).

## 5. Verdict vocabulary

Results render as: `P(up)` with Wilson interval and denominator, per rule variant, each
line carrying `reference=coinbase-1m-approx (NOT settlement-exact)` and the fee floor.
If the interval contains 0.5, the pre-registered summary is "no directional edge
detectable at this reference approximation"; a deviation from 0.5 smaller than the
working floor renders as "below the fee floor — not tradable even if reference-exact".
