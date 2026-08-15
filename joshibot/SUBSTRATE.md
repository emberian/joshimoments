# SUBSTRATE — the v1.5 consolidation plan

Written 2026-08-15, after the operator pressed the point twice and was right both times. This is
the standing brief for the consolidation wave; it fires when the current lanes land.

## Why (the operator's argument, endorsed)

Two distinct costs, and the second is the one that decides:

1. **Speed.** Three lanes saturating a laptop to row-loop 106M parquet rows in stdlib Python.
2. **Error rate.** *"It's SOO easy to fall into trivial errors... you don't even notice/care when
   you make them, because it's just slop python."* The repo's own history is the evidence: the
   censored-96% drop, the −151% partial-row average, the 24× attempt overcount, five divergent
   default sites — every one lived in hand-rolled imperative plumbing that a declarative engine or
   a shared library would have made *unwritable*. Vectorized/columnar/SQL code is not just faster;
   it has **fewer places for that class of bug to exist**, the same way lifelines makes censoring
   part of the model spec instead of a thing an analyst can forget.
3. And the meta-reason: **we iterate on how we study, and study-iteration time is the binding
   resource.** A study that takes an hour gets refined; a study that takes a day gets shipped as-is.

Measured duplication being consolidated: 22 JSONL writers, 23 partial-line-tolerance loops,
42 HTTP client sites, 12 DexScreener fetchers, 9 pump.fun fetchers, ≥3 friction tables.

## The five packages

1. **`tapecraft`** — the one JSONL/parquet substrate: append/read, partial-tail tolerance, run_id,
   two clocks, watch windows, heartbeats, staleness. The house disciplines become imports, not
   prompt recitations.
2. **`marketdata`** — one client layer: pump.fun, DexScreener, GeckoTerminal, Meteora, Helius,
   pumpportal. Shared retry/backoff/rate-limit/pacing, provenance stamps, per-provider budgets
   (the RPC-router that moves poll load onto free tiers lives here). One throat for the watchdog.
3. **`friction`** — sizing, fees, priority, impact, rent (position AND binArray pioneer rent), the
   per-swap fee schedule read from chain. The measured constants in exactly one place; the
   500k-lamport and 20-bps incidents are the case law.
4. **`cohortkit`** — the study kit on real engines: **DuckDB over parquet** for corpus-scale
   aggregation/joins (out-of-core, multicore), **polars** for pipeline shapes, **numba** for the
   irreducibly-loopy kernels (Lomb–Scargle, NCD), **lifelines** for anything censored, plus the
   validated harnesses promoted from studies: dCor+permutation (with known-zero/known-effect
   selftests), rotation/block nulls, BY-FDR, `vol-control`, entity-clustered CIs, the
   forward-return machinery. **No study row-loops a corpus again.**
5. **Contracts stay the seams** — `shitcoims_tape.schema` and its siblings; language per layer
   (TS glass, Python-with-engines research, Lean kernel) talking through data, never through code.

## Compute residency

- **persvati** (24c/83G/617G free, never sleeps): primary corpus node + collectors + watchdog +
  reactive guardian. Checkout + research venv + `corpus/bulk_pump/`.
- **hbox** (24c/123G, /tank 1.9T): secondary corpus node for wide sweeps. **Co-tenant with codex's
  datacake HOL build**: `nice`, bounded jobs, `swarm-build` for anything compiled, small waves.
- Corpus is rsynced to both; the Mac becomes interactive-only.

## Untouchable in this wave

The Lean kernel and its FFI oracle; `shitcoims_tape.schema`; the sentinel's signer-isolation
pattern; `shitcoims_lpexec`'s guard (builder-level allowlists, no broadcast path). These are the
proven cores the substrate serves.

## The tripwire (goes in agent briefs and SWARM.md)

**No new JSONL writer, HTTP client, friction constant, or hand-rolled statistic.** Extend the
substrate or say in your report why you could not. Corpus work uses DuckDB/polars over parquet —
a `for` loop over corpus rows in pure Python is a defect, not a style choice. Same shape as the
Lean/AIR tripwire, same reason: this drift happens every time and is only caught the next day.

## Migration order

1. `cohortkit` first (highest error-rate leverage; studies are the active workload).
2. `marketdata` + watchdog integration (kills the 42-client sprawl; enables the free-tier router).
3. `tapecraft`, migrating collectors one at a time, full suite green each step.
4. `friction` extraction (paperdesk + lpexec + probe converge on it).
5. Delete the duplicated code as each consumer moves. The metric of done: the counts in "Why"
   go to ~1 each.
