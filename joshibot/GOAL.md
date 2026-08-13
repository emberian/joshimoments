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
