# RESULT — wallet_estimator: the standing per-wallet behavioral layer, and the iceberg detector

**The ask, verbatim.** *"did we ever get around to bolting an estimator of wallet behavior onto
all the wallets, and using that as any kind of anything? for example some bundles might be
selling piecewise to make the chart look less plungy."*

**The answer before this module: no.** The pieces existed across lanes and were never assembled
into a standing layer keyed by wallet:

- `unrealized_pnl.py` — the realization-policy fingerprint (a strong PER-wallet signature, AUC
  0.775 on coin-disjoint halves; it FAILED cross-wallet actor attribution at 0.518).
- `cluster_map.py` — the guild taxonomy (accumulator / harvester / flash / slow / aftermarket)
  and the 8-second scheduler/ladder.
- `pvp_vamps.py` — the rotation cohort (324k wallets, 54% of buy SOL) and the exact
  full-SOL-leg tape (58.7M priced legs).

This module assembles them into `state/wallets/estimator.parquet` (one row per active wallet)
and builds the detector the ask actually names — **iceberg / piecewise distribution** — plus a
per-coin exit signal a live desk joins against. It is `studies/wallet_estimator.py`.

---

## 0. Substrate and scope

Built on `studies/data/pvp_vamps/trades.parquet` — **58,718,411 executable-priced legs**, the
counterparty-resolved trade tape with the exact SOL leg on both routes (curve constant-product
identity; PumpSwap vault delta). Window **2026-08-05 .. 2026-08-14** (10 days). Universe: the
33,880-coin `curve_touches >= 100` cohort **plus the four operator coins**. 1,110,501 distinct
owners touch it; **728,017** clear the `>= 3 priced legs` activity threshold and enter the layer.

Everything is average-cost, executable-exit priced, and computed with the same recursion
`unrealized_pnl.py` validated against a literal Python loop. Per-leg basis over the whole tape
runs in **30 s**; the wallet aggregation in **7 s**; the iceberg pass + timing null in **~25 s**.
Nothing here touches the network or the sentinel.

---

## 1. The feature set (`estimator.parquet`, 728,017 rows, keyed by base58 `owner`)

| group | columns |
|---|---|
| identity / activity | `owner`, `owner_id`, `n_legs`, `n_buys`, `n_sells`, `n_coins`, `active_days`, `span_days`, `t_first`, `t_last` |
| buy/sell asymmetry | `gross_sol`, `buy_sol`, `sell_sol`, `sol_asymmetry` (=(buy−sell)/gross), `sell_buy_leg_ratio`, `roundtrip_frac` |
| PnL (executable, realized only) | `net_realized_sol`, `win_rate`, `n_coins_closed`, `n_coins_win`, `median_realized_sol_closed` |
| hold time | `median_hold_s`, `p90_hold_s` |
| realization-policy fingerprint | `n_priced_sells`, `rp_frac_in_profit`, `rp_frac_at_loss`, `rp_frac_breakeven`, `rp_p10/p50/p90` (realized frac), `holds_through_red`, `rp_mode` |
| guild / structure | `guild` (resolved), `guild_cluster` (bulk-map, authoritative), `guild_solo` (per-wallet analog), `cid`, `fresh_frac`, `exit_ratio` |
| entry timing / scheduler | `median_entry_latency_s`, `on_ladder` |
| rotation / mercenary | `in_rotation`, `rotation_hours` |
| meta | `updated_through`, `schema_version` |

**Executable PnL, not marginal.** `net_realized_sol` is cash realized on the SOLD fraction only
— SOL received minus average-cost SOL paid for the tokens actually sold — and never marks unsold
inventory into profit. That is the discipline the ask's sibling lane paid for: a marginal mark
booked **+950 SOL** where the executable exit was **+35**. The bounded, executable measure says
the **crowd nets −738,301 SOL over the 10 days; only 32.5% of wallets are net-positive** on
closed positions (median wallet −0.003 SOL). That is the extractive PvP structure priced at the
wallet grain, not a bug.

**Guild economics** (the resolved `guild`, over all 728k):

| guild | n | win_rate | in_rotation | median PnL (SOL) | break-even-preset rate |
|---|---:|---:|---:|---:|---:|
| HARVESTER | 326,180 | 0.355 | 0.49 | −0.065 | 0.116 |
| SLOW | 148,526 | 0.337 | 0.40 | −0.004 | 0.122 |
| ACCUMULATOR | 128,766 | 0.292 | 0.42 | 0.000 | 0.089 |
| FLASH | 123,431 | 0.370 | 0.40 | −0.013 | **0.201** |
| AFTERMARKET | 1,114 | **0.512** | 0.44 | **+0.107** | 0.208 |

Two readings fall straight out: **FLASH wallets carry the highest break-even-sell rate** (20%
of their sells land within ±5% of cost — the Trojan/BullX/Photon break-even preset, visible as a
4.9× spike at 0.0 in the realization distribution), and **AFTERMARKET wallets — the ones trading
established coins rather than sniping launches — are the only net-positive guild.** The
launch-biased cohort under-represents AFTERMARKET (1,114 solo-classified), so `guild_cluster`
from the ten-day bulk map is carried as the authoritative label where present (65,870 wallets in
a bulk cluster); `guild_solo` is the generalization for everyone else.

`rp_mode` labels the sell distribution: LOSS_CUTTER (305k — stops out in the red), MIXED (213k),
AVERAGES_DOWN (80k — buys below its own cost, the conviction signal), BREAKEVEN_PRESET (66k),
PROFIT_RUNNER (64k).

---

## 2. THE FLAGSHIP — iceberg / piecewise distribution

**The object.** An entity feeding a large exit out in many small same-direction sells so the
chart does not plunge: holdings draw down monotonically while the price stays propped, i.e. net
sell flow ≫ what the price impact would predict.

**Operationalization** (`state/wallets/iceberg.parquet`, one row per (wallet, coin) distribution
episode; 4,352,105 episodes over holders peaking ≥ 0.1% of supply). Per episode, measured strictly
after the wallet's peak holding:

- `drawdown` — how far the bag was drawn down (fraction of peak).
- `n_dist_sells`, `frag` — count and smallness of the sells (many small = iceberg; one big =
  dump).
- `sold_frac_of_own`, `dist_sold_sol` — how much of the bag left, in tokens and SOL.
- `resilience` = Δlog price from peak to end of distribution — **propped ≈ 0 or positive.**
- `absorption` (curve route, EXACT) — on a bonding curve a sell of Q moves price by a
  deterministic amount, so `1 − (realized Δlog price)/(Δlog W's own sells would have caused
  alone)` measures how much the rest of the market absorbed. 1 = fully propped; 0 = W's own
  dumping drove the whole move; <0 = others sold too and amplified it.

A **gated candidate** is drawdown ≥ 0.60, ≥ 8 sells, spread over ≥ 300 s (the duration floor
excludes single-slot bundle splits). **53,495** episodes qualify.

**The exact curve check separates the two populations cleanly:** gated candidates have **median
absorption 1.51** (price *held or rose* while they sold) against **−3.39** for non-candidates
(they dumped into weakness); median `resilience` **+0.25 vs −0.13**. This is the iceberg-vs-dump
split, measured, not asserted.

**The timing null — "sells piecewise to make the chart look less plungy," made a test.** Holding
the coin's whole price path fixed, relocate W's sell **minutes** at random among the coin's active
minutes *inside W's own [first_sell, last_sell] window* (rotation-null discipline: the coin's
trend and W's participation window are held fixed; only the placement is destroyed). Statistic:
the size-weighted average of *others'* net token flow at the minutes W actually sold into. If W
concentrated its sells into minutes when the rest of the book was net-buying, the observed statistic
beats the null. Permutation is at **minute** grain, not per-sell — so the effective sample is the
number of sell-minutes, not the (bursty) sell count, which is the `N_eff = bursts, not slots` trap
the program warns of. Entity-clustered by owner; **Benjamini-Yekutieli** FDR (dependency-safe).

Run on three strata so the base rate is honest:

| stratum | n | frac pass (p ≤ 0.05) | median p |
|---|---:|---:|---:|
| top by iceberg_score | 4,000 | **0.626** | 0.008 |
| **random gated candidates** | 1,499 | **0.309** | 0.293 |
| operator-coin episodes | 543 | 0.344 | 0.188 |

**iceberg_score strongly predicts timing-null passing — 63% in the high-score tail vs 31% among
random deep-distributors.** The score orders wallets by how iceberg-like they are; it works as a
ranking.

---

## 3. The confound — NULL-IS-A-RESULT honesty

**The random-gated floor is 31%, not 5%, and that is the finding to be careful about.** A wallet
that *successfully distributed a big bag over many minutes* has, by survivorship, sold during
minutes when buyers were present — you cannot fill a large chunked exit into an empty book. So the
timing null's absolute pass rate is inflated by selection on *having distributed at all*, and the
FDR-passing count (**1,822** episodes) **over-states the number of deliberate chart-managers.**
What is identified is the **differential** (63% vs 31%): the score is a valid ordering of
distribution intensity and an exit tell. What is **not** identified is intent.

Three things it cannot separate, stated plainly:

1. **Deliberate propping vs selling into exogenous demand.** A whale offloading into a genuine
   pump shows the same resilience as one manufacturing the pump. The top operator-coin
   distributors sold into coins whose price *rose 7–30×* during distribution — that is real
   demand as easily as it is a managed chart.
2. **Self-wash.** The partial discriminator is `self_wash` — the share of the absorbing buy flow
   coming from W's own same-slot cluster. It fires only where W is in a bulk cluster; for the top
   operator-coin distributors it is **None or ≈ 0** (they are not clustered, or their absorbers
   are not their peers), so **no self-washing is confirmed** — they look like distribution into
   organic demand.
3. **Funding-tree attribution** (PROGRAM.md signal #2) would close 1–2 and is not in local data
   (no fee-payer, no native-SOL legs).

The benign null is therefore a real population, not a straw man: **~69% of deep chunk-distributors
do NOT beat the within-coin null** — DCA-out and tax-lot-style unwinding that sold into whatever
the market was doing.

---

## 4. The four coins, scored on the freshest flow

`state/wallets/operator_scan.json`. "Now" is the tail of the priced tape (**ends 2026-08-14
23:59 UTC**); this layer is not yet wired to the live desk feed (see the join contract).

| coin | gated candidates | pass FDR≤0.10 timing | recent (48h) candidates | rank of 5,345 coins | verdict |
|---|---:|---:|---:|---:|---|
| **nosis** | 146 | **32** | 62 | **#3** | ICEBERG-DISTRIBUTING in-window, recent |
| **weave** | 34 | **7** | 19 | #68 | ICEBERG-DISTRIBUTING in-window, recent |
| DREGG | 4 | 0 | 2 | #5,146 | benign chunked DCA-out only |
| SOLVE | 5 | 0 | 2 | #4,659 | benign chunked DCA-out only |

**The prominent finding.** **weave and nosis both have large holders iceberg-distributing them,
recently, and passing the timing null; DREGG and SOLVE do not.** nosis's single worst distributor
held **1.10% of supply** and fed out **1,066 SOL across 2,174 tiny sells** while the price *rose
7.8×* (resilience +2.06; timing q = 0.06). weave's worst held **2.70% of supply**. These are the
exact "big holder quietly emptying the bag without cratering the chart" pattern the ask describes —
and the crucial caveat from §3 applies: they sold into strong demand with **no confirmed
self-wash**, so this is best read as **an exit tell for other holders** (a big bag is leaving,
absorbed for now) rather than proof of a manufactured chart. **But it is a standing signal, not an
hour-one one** — unlike the launch-sniping crime lane, which only works in the first hour, this
fires on graduated coins at any age, which is exactly where all four operator coins live.

Framing check: nosis at **#3 of 5,345** is genuinely elevated, but iceberg distribution is a
*common* market structure (5,345 coins carry gated candidates). The operator coins are not
singular; nosis simply sits in the top tier by activity.

---

## 5. The join contract (how paperdesk / the glass consume this — nothing here edits them)

The estimator is a **read-only, standing lookup layer**. Consumers join it; they never write it.
Full contract in `state/wallets/JOIN_CONTRACT.md`; the essentials:

- **Wallet card / hunch.** Key on the base58 `owner`. `LEFT JOIN state/wallets/estimator.parquet
  USING (owner)`. A miss is a wallet below the activity floor — render it as the glass's four-state
  `null` with reason `"below activity threshold"`, never a zero. Surface `guild`, `rp_mode`,
  `in_rotation`, `win_rate`, `net_realized_sol`, `median_hold_s`.
- **Coin card exit-risk gate.** Key on `mint`. `LEFT JOIN state/wallets/coin_exit_signal.parquet
  USING (mint)`. `n_timing_pass >= 1 AND any_recent` is the "someone is iceberg-distributing this
  coin" flag; `max_iceberg_score` ranks it. Ship it as `gates_would_veto`-style context, not an
  auto-action.
- **Per-holder drill-down.** `state/wallets/iceberg.parquet`, key `(owner, mint)`: `iceberg_score`,
  `resilience`, `absorption`, `timing_p/q`, `self_wash`, `is_recent`.
- **Freshness.** Every table carries the tape end (`updated_through` / `corpus_end`). The desk
  must render a figure older than its refresh horizon as stale, per the "never render an absence
  as a zero" rule. Regenerating against a live tape is `basis → wallet → iceberg → operator`.
- **Stability.** `owner`, `mint`, `schema_version` are the stable keys; treat the confound in §3
  as attached to `timing_q` — it ranks, it does not convict.

---

## 6. Reproduce / limitations

```
uv run --group research python -m studies.wallet_estimator all      # basis→wallet→iceberg→operator→report
# or stage by stage: basis | wallet | iceberg | operator | report
```

- **Left-censoring.** Positions predating 2026-08-05 have no observable entry; a wallet whose
  first in-corpus leg is a sell is dropped from basis (1.15M of 58.7M legs). `drawdown` /
  `sold_frac_of_own` > 1 (pre-window bags) are clipped to 1.
- **Pool route has no exact absorption.** All four operator coins are graduated/pool, so their
  iceberg signal is resilience + the timing null; the exact curve absorption is available only for
  the curve-route majority and is what validates the split.
- **Launch-biased universe.** The cohort is `curve_touches >= 100` launches, so AFTERMARKET /
  old-coin behavior is under-sampled at the solo grain; `guild_cluster` (ten-day bulk map) covers
  it where the wallet clustered.
- **The estimator is a ranking and a context layer, not a conviction.** §3 is load-bearing.
