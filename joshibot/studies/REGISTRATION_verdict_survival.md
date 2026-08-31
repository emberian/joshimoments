# REGISTRATION: survival by birth verdict — "what usually happens next" for the screen card

2026-08-29, registered BEFORE any survival estimand was computed. Instrument will be
`studies/verdict_survival.py`; caches to `studies/data/verdict_survival/`. Data: the fresh
corpus distillates `studies/data/operator_crime_fresh/` (panel.parquet for features and
verdicts, ledger/day=*.parquet for the collapse-crossing recompute), window 2026-08-26..28.

## Why this study (and why the two siblings were dropped)

Chosen over (b) time-to-first-iceberg and (d) failure-density-at-birth. (d) is unmeasurable
in this corpus BY DESIGN (`RESULT_failure_stream.md` §0: the export keeps only
balance-changing rows, so failures are structurally absent; buying failures for 100k births
is a new BigQuery superset whose aggregate form already failed 21 pre-registered tests).
(b) needs the wallet-level iceberg detector ported to per-coin first-onset — a build, and its
card sentence overlaps this study's time-to-collapse quantiles. This study ships directly:
every screen card gains one measured sentence of forward context conditioned on the verdict
the card already prints.

## Author-knowledge disclosure

I have seen `screen_fresh.json` (CLEAN admitted 0 rips and 3 collapses of 8,773 in this
window) and the standard arm's validation, so I EXPECT verdict-conditional lifetime
differences to exist in the direction CLEAN > others. The registered estimands are therefore
the QUANTITIES (curves, quantiles, fixed-horizon probabilities with CIs), not the existence
of a difference; the ship rule below is set on magnitude + CI, fixed now. I have not
computed any survival curve, quantile, or horizon probability on any stratum.

## Population and verdicts (causal, assigned from birth-time information only)

Population: standard-BORN fresh coins with an identified deployer (the validated screen
population). Verdict precedence, mirroring `dregg_screen/score.py` restricted to
panel-expressible arms (disclosed limitation: the live Jaccard crew-match arm is not in the
panel; its panel proxy is the three history arms):

  KNOWN_CREW := prior_rips > 0 ∨ prior_dumps > 0 ∨ sniper_prior_max > 0
  BUNDLED    := else n_snipers ≥ 2
  NOT_CLEAN  := else dev_buy_share ≥ 0.02
  CLEAN      := else (all five gates pass)

All history features in the panel are strictly causal (PANEL_SQL aggregates events with
their own timestamps before birth).

## Endpoints

- QUIET(G=3600 s): the coin's last in-window curve touch followed by ≥ G of silence to the
  window end. Event time = t_last − birth_time; right-censored at window_end − birth_time
  when window_end − t_last < G. Robustness cell: G = 21600 s. The in-window resurrection
  rate (a ≥G gap later followed by another trade) is reported as an endpoint-quality check;
  if > 20% at G=3600 the 6h cell becomes primary.
- COLLAPSE-crossing: first (slot, tx) where marginal price ≤ 10% of the running peak price
  AND the running-peak mcap ≥ 100 SOL (the validated collapse, given a time). Computed from
  the curve balance path: crossing when v_tok ≥ running_min_v_tok · √10.
- GRADUATION: first time curve balance ≤ 1e9 raw.

## Registered estimands

S1. By verdict: P(still trading at h) for h ∈ {1h, 6h, 24h} — "alive at h" := t_last −
    birth ≥ h — computed ONLY on coins with full exposure (birth ≤ window_end − h), n per
    cell, Wilson 95% CI, and a deployer-clustered bootstrap (2,000 draws) for the
    CLEAN − BUNDLED and CLEAN − KNOWN_CREW differences.
S2. By verdict: Kaplan–Meier median and IQR of time-to-QUIET (G=3600), censoring as above,
    stratified by birth day (curves must replicate per-day in sign; a pooled number whose
    per-day signs disagree is reported as unstable, not shipped).
S3. By verdict: P(collapse by 24h) on the 24h-exposure-complete subcohort, Wilson CI.
S4. By verdict: P(graduate by 24h) on the same subcohort, Wilson CI.
S5. The card quantiles: for each verdict, the {p25, p50, p75} of time-to-QUIET among
    event-observed coins, printed exactly as they would appear on the card.

## Structure-preserving concerns, handled in the design

Birth-day cohort effects: S1/S3/S4 are exposure-complete by construction and S2 is
day-stratified. Non-independence from multi-coin deployers: all difference CIs are
deployer-clustered. No i.i.d. permutation is used anywhere.

## Ship rule (fixed now)

The card sentence ships per verdict pair iff n ≥ 500 in each arm at the quoted horizon AND
the deployer-clustered 95% CI of the CLEAN-vs-that-verdict alive-at-6h difference excludes
0 AND the S2 per-day signs agree. Shipped form (numbers from the run): on the screen card,
under the verdict line — e.g. "CLEAN cohort (08-26..28, n=…): p50 last trade N min after
birth; X% still trading at 6h; collapse by 24h Y% (vs Z% for BUNDLED)." If separation fails
the CI test, the honest deliverable is the null: the wire states that verdicts predict
collapse but not lifetime, and no card sentence ships.

## Falsifiers

A verdict-conditional lifetime difference that reverses sign across the three birth days;
resurrection rate > 20% at both G values (endpoint invalid); or exposure-complete n < 500
in the CLEAN arm (window too short for the sentence).
