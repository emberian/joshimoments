# What to pull next, and why

Three extractions, ranked by value per dollar. Costs are joshibot's own billed measurements from
`scripts/pump_history.py` plus tonight's re-derivation, not estimates.

The existing corpus (`bulk_pump`, 2026-08-05..14, 106,639,238 rows) is not defective. It is bounded
in three specific ways, and each ask below removes exactly one of them.

## 1. `log_messages` — about +1.2% on the current query

**Removes: unmeasured recall.**

Selection today is `EXISTS(post_token_balances b WHERE b.mint LIKE '%pump')`. That is a **vanity
suffix convention**, not a protocol fact. Precision is high and recall is *unknown*: a pump.fun coin
whose mint does not end in `pump` is invisible, and we cannot say how many there are. The
structurally exact filter is the pump.fun program id appearing in `log_messages`, and that column is
empty for the current window because it was not selected.

It also gives instruction identity, which we currently infer. M0 found that every landed PumpSwap
buy used `BuyExactQuoteIn` while our kernel only supported exact-base-out — the kind of thing that
is obvious in a log line and invisible in balance deltas.

**Cheapest ask on the list and it fixes the one bound we cannot even measure.**

## 2. Relax `pre != post` — a re-pull at roughly 40x the row count

**Removes: the structural absence of failures.**

`err` is empty on all 106,639,238 rows and *cannot* be otherwise. The extraction keeps a transaction
only when a pump-mint balance changed; a reverted transaction's balances roll back, so `pre == post`
and the row is dropped before `err` is ever consulted.

Consequence: **no attempt, landing, selection or adverse-selection study can be built on these
bytes.** Not "is hard to build" — cannot. Every fill in the corpus is a fill that landed, so the
corpus is a survivorship sample of the execution process by construction.

This matters right now because Ember reports she cannot execute on her trades efficiently, and the
data that would say why is precisely the data this predicate discards. A separate JOSHI observation
of the same day found 13 of 13 listed transactions for one wallet carrying a non-null error — from a
different source, because this corpus structurally cannot show one.

Note the row count explodes (~40x), so scope it: one week, or a sampled mint set, rather than the
full window.

## 3. `balance_changes` — 434 GB/day billed

**Removes: the missing SOL leg on the bonding curve.**

The pump.fun curve holds SOL as **native lamports in the PDA**, and native lamport balances are not
carried. So 21.6% of trades — the curve ones, which is where pre-migration coins live — have no
observed SOL amount at all. `sol_leg_lamports_exact` is NULL for every one of them.

This is the **lowest priority of the three**, because the gap is already covered honestly: a
separately named `sol_leg_lamports_curve_model` column carries a constant-product readout that was
validated against pump.fun's own `virtual_sol_reserves`/`virtual_token_reserves` from an independent
tape — 6,115 matched observations across 2,086 mints, 99.23% exact to better than 1e-6 relative,
median relative error 4.8e-9. Paying 434 GB/day to replace a model that good is poor value until
something depends on the difference.

## Also absent, no ask attached yet

The `accounts` array is not carried, so there is **no signer and no fee payer** on any row. Vaults
are keyed by mint rather than address. Any parent-flow, wallet-clustering or "who is actually
trading" question is limited to token-account owners, which is not the same thing as the actor.

## Not a BigQuery problem

The binding uncertainty for execution is **state age**, and no historical extraction fixes it. M0
measured a pool mark drifting 35.6 bps in 49 seconds and a curve marginal price falling ~3,575 bps
in 13.6 minutes. That is a live-subscription problem — `accountSubscribe` on the pool account — and
it should not be confused with a data-completeness problem.
