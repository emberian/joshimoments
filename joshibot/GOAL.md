# GOAL — build out the joshibot research program

Standing goal set 2026-08-13. Spine: `PROGRAM.md` (what the evidence establishes) and
`SWARM.md` (how to build it without the fleet building a mirror).

## Current thrust

**Phase 0 is DONE — all 8 interfaces exist as types that build.** Tracks B, C and E are now
unblocked and swarmable, because a lane can be handed real signatures instead of prose.

## Next 3 moves

1. CI + mypy — gates the next swarm's output at merge; do before fanning out further.
2. Swarm wave 1: Track B (tape recorder → `/tank`, bootstrapped from MELT + RED-PUMP) and
   Track E spike #3 (callout→flow, runs today on the existing intelligence store).
3. Track C: deepen the kernel (competing-risks accounting, envelope daily-loss budget) and
   wire the `@[export]` C ABI so Python/Rust call into the emitted artifact.

## Done log

- 2026-08-13 — Track A landed (`e509cc3`): fabricated cost basis killed at all four sites (engine
  auto-protect, `policies.from_quote`, dashboard client-side, `overview.tsx`); executor made safe to
  retry (local signature before execute, `isBlockhashValid` as proof-of-death, `unresolved` terminal
  state); 32-address simulation ceiling chunked; blanket 1500bps replaced by reason-conditional
  computed `minOut`; config lost-update race closed; `--status` made incapable of executing.
  416 pytest + 5 dashboard tests, ruff/tsc/eslint clean. Every lane falsified its own tests.
- 2026-08-13 — sentinel restarted onto the hardened code (pid 15101, live, zero tracebacks). First
  time the running process has carried a real cost basis.
- 2026-08-13 — Phase 0 tape contract (`3f0c1b1`): interfaces #1/#7/#8 in `shitcoims_tape/`.
  Raw amounts as strings on the wire (f64 cliff), two clocks never conflated, censoring
  recorded explicitly with informative closes flagged, reserves recorded not prices.
  18 tests, all falsified by four probes.
- 2026-08-13 — Phase 0 Lean kernel: interfaces #2–#6 in `kernel/Joshi/`. Fills (payout bounded
  by reserve, monotone in size), Basis (quote-derived basis is unconstructible; no-basis can
  never fire a stop), History (no-lookahead as a theorem over all strategies), Dsl (trial count
  N computable from the grammar: 110,880 predicates at 8 features/depth 1), Envelope (exposure
  bounded over EVERY action sequence, i.e. every learner). Zero sorries; axiom audit shows only
  propext/Quot.sound/Classical.choice. Lean core only, no mathlib — builds in ~2s.
- 2026-08-13 — merge gate: `scripts/check.sh` (ruff, mypy, pytest, dashboard tsc/eslint/render,
  lake build, no-sorry, axiom audit). mypy introduced with a GATED set — executor, transaction,
  domain, tape must stay clean; 65 findings elsewhere are tracked debt surfaced by `--full`.
  Two real narrowing holes closed in the money path while gating (executor reconciliation,
  domain no-quote guard); both now fail closed instead of relying on a reader's inference.
- 2026-08-13 — stale-doc sweep: README no longer claims full-balance-only exits and now states
  the cost-basis contract (never inferred from a quote; unknown basis ⇒ rug-only); Scout's
  "cannot sell" corrected to "cannot sell directly" (it can write a rule that causes a later
  sale); `lots.py` grace comment no longer describes the deleted fabrication. `policy_to_mapping`
  float exception documented with the condition under which it must be split.
- 2026-08-13 — Track C: the kernel is now load-bearing, not a parallel document. `@[export]`
  C ABI (`joshi_sell_out`, `joshi_accepts`) with a proof that narrowing back to UInt64 is
  lossless — `sellOut_le_reserve` is what licenses the signature. Shipped as `joshi-oracle`
  (macOS dylib linking dropped the objects; the executable is lake-supported and robust).
  `shitcoims_kernel/` is the Python binding: an authoritative subprocess oracle plus a fast
  path for replay, held to exact agreement by 15 parity tests over adversarial sizes and 600
  random pools. Falsified with two transcription bugs (dropped denominator term; round vs
  floor — the latter only diverges at scale, which is the class that silently corrupts a
  backtest). Parity tests skipping is now itself a gate failure.
- 2026-08-13 — Track E spike #3 (callout→flow): **UNRESOLVABLE-AT-THIS-N**, not null — the
  exogenous outcome was never observed (0 of 61 called-out mints touched by the exogenous
  wallet). The finding that matters is the TRAP: including our own sentinel wallet yields
  p=0.00498 and 6/6 surviving FDR, from a closed loop plus a mechanically-floored p
  (n_placebo_arrivals=0 across 32,400 windows). Structural-zero guard added and pinned.
  8/8 mutations killed their test. Also: the store's two clocks are INVERTED between kinds
  (`emitted_at` is block time for wallet_transaction, post time is `observed_at` for social).
- 2026-08-13 — Envelope completed: daily-loss breaker with `tripped_breaker_is_absorbing` —
  once the budget is blown, `run` is the IDENTITY on desk state for any learner and any
  sequence length. Structural, not lucky: `apply` never touches the loss field. Zero sorries,
  propext only.
- 2026-08-13 — `resolve_pending_exit` promoted to the executor's public contract; the engine
  no longer reaches through `getattr` into a private name, where a rename would have silently
  degraded to "delete the intent without resolving it" — i.e. drop a confirmed fill from the
  ledger. Still probed (test stubs legitimately omit it), but probing a public name makes a
  rename a visible break.
- 2026-08-13 — Track B landed the tape recorder (`2d93305`, 96 tests, 31/31 mutations caught,
  and it found a clock bug in its own instrument: graduation median 0.5s on the observer clock,
  now 250s against Marino's 264s). It then found three holes in MY contract, now closed:
  social flags are tri-state (`None` = not observed — `False` was a fabricated negative, the
  same disease as a quote-stamped cost basis); `Callout` gained `posted_at` (ingest lag median
  368s / p95 2h, so anchoring on ingest measures a closed window); and `_mint` now DECODES to
  32 bytes instead of matching a character class, which catches ~3 in 4 lowercased addresses.
  Falsification found a gap in my own test — the first probe was a no-op — so the missing
  case (absent post time must not be fabricated) is now pinned too.
- 2026-08-13 — `prints_from_wallet_payload` no longer splits one native SOL delta evenly
  across multiple token legs (a route/arb carries one delta and no way to attribute it, so
  the split invented a per-leg price on every leg). Multi-leg rows are refused, keeping the
  ambiguity visible as a smaller n rather than confident noise. Also made the lowercase-address
  test a deterministic RATE test — a single case flaked on the minority that still decodes to
  32 bytes, which would have hidden the residual risk instead of measuring it.
