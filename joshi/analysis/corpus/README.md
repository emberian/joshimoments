# bulk_pump corpus

Build and census scripts for the ten-day Solana pump corpus at
`~/dev/joshibot/state/bulk_pump/daily/*.parquet`. **106,639,238 rows**, 2026-08-05 to 2026-08-14,
29.6 GB, 449,723 distinct pump mints, 2,522,112 distinct owners.

The scripts are here; the 15 GB of derived parquet is not, and belongs in a scratch directory.
`SCHEMA.md` documents every derived column and carries query recipes.

## This corpus was already mined once

joshibot has roughly ten completed studies against these exact bytes — `seasonality.py`,
`callout_volatility.py`, `jackduval_workup.py`, `operator_crime.py`, `quality_callers.py`,
`failure_stream.py`, `cluster_map.py`, `bundle_hypothesizer.py`, `unrealized_pnl.py`, and the
`RESULT_*.md` files beside them. `joshibot/scripts/pump_history.py` documents the collection method,
the zero-failures property and the curve-price identity. The row count, the constant `err` and both
curve constants were independently re-derived here and all matched.

The corpus was composted along with a repository that had already read it. Treat further work as
**port and re-verify**, never as first contact.

## What it is, and is not

Selection is `EXISTS(post_token_balances b WHERE b.mint LIKE '%pump')` — a vanity-suffix
**convention**, not a guarantee. Precision is high; **recall is unmeasured**. The structurally exact
filter, a pump.fun program id in `log_messages`, was unavailable because that column is empty for
this window.

Only balance-changing transactions were kept, an approximately 40x reduction. Because a reverted
transaction's balances roll back, `pre == post` and the row is dropped before `err` is consulted:
**`err` is empty on all 106,639,238 rows and there cannot be a failed transaction in this corpus.**
That is structural. No attempt, landing, or adverse-selection study can be built on these bytes; it
needs a different extraction, which is a re-pull rather than a flag.

Native SOL lamports are not carried. The pump.fun bonding curve holds SOL as native lamports in the
PDA, so for curve transactions **no SOL amount is observed** and `sol_leg_lamports_exact` is NULL,
never filled. A separately named `sol_leg_lamports_curve_model` column carries the model and
`sol_leg_quality` says which you have. **Nothing coalesces them, and that separation must survive
into anything that joins this data or the honesty is lost at the first join.**

Coverage is 14,166 of the window's 14,400 UTC minutes. The 234 absent minutes fall entirely inside
2026-08-12 11:43 to 2026-08-13 02:25, one upstream reprocessing hole, and excluding blocks touching
it moves census totals by about 5% without changing anything qualitatively.

## Price objects

Never a bare `price`; every row carries `price_kind`.

- `amm_pool_vault_fill` (65%) — the exact ratio of two observed integers at the pool's own vaults.
  It is the **pool vault exchange rate for that transaction**, not a quote at any other size, and
  because protocol and creator fees leave to accounts outside the narrowed arrays it is **not** the
  taker's all-in cost and must never be labelled an average fill.
- `curve_constant_product_readout` (21.6%) — a **model**, validated against pump.fun's own
  `virtual_sol_reserves`/`virtual_token_reserves` from an independent joshibot boards tape: 6,115
  matched observations across 2,086 mints, **99.23% exact to better than 1e-6 relative, median
  relative error 4.8e-9**. Disagreement falls monotonically as more corpus trades land inside the
  board's one-second stamp, which is the signature of match error rather than model error.
- `unsupported` (13.4%) — no price. 45% of these have no venue account in the transaction at all
  (wallet-to-wallet transfers and airdrops); the rest are multi-venue routes, LP edits, creates and
  migrations.
