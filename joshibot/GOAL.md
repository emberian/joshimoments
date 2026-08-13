# GOAL — build out the joshibot research program

Standing goal set 2026-08-13. Spine: `PROGRAM.md` (what the evidence establishes) and
`SWARM.md` (how to build it without the fleet building a mirror).

## Current thrust

**Phase 0 — the 8 shared interfaces.** Not swarmed, by design: an agent that cannot see a
foundation reconstructs it from prose and verifies against its own reconstruction. Everything
downstream reads these, so they get authored tight, in-session, as real types that build.

## Next 3 moves

1. Tape event schema (#1) + entity-resolution output (#7) + propensity-log (#8) — `shitcoims_tape/`.
   Do-first: data compounds regardless of which strategy wins and cannot be recorded retroactively.
2. Lean kernel type signatures (#2–#6): fills → accounting → history/causal index → DSL → envelope.
3. CI + mypy — the thing that makes the *next* swarm's output safe to accept at merge.

## Done log

- 2026-08-13 — Track A landed (`e509cc3`): fabricated cost basis killed at all four sites (engine
  auto-protect, `policies.from_quote`, dashboard client-side, `overview.tsx`); executor made safe to
  retry (local signature before execute, `isBlockhashValid` as proof-of-death, `unresolved` terminal
  state); 32-address simulation ceiling chunked; blanket 1500bps replaced by reason-conditional
  computed `minOut`; config lost-update race closed; `--status` made incapable of executing.
  416 pytest + 5 dashboard tests, ruff/tsc/eslint clean. Every lane falsified its own tests.
- 2026-08-13 — sentinel restarted onto the hardened code (pid 15101, live, zero tracebacks). First
  time the running process has carried a real cost basis.
