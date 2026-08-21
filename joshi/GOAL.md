# GOAL — close S1, stage S2

**Standing goal.** Close S1 (First real census) end to end under the PILLARS.md promotion rule:
a real observation, acquired from a real source, reaches a rendered surface, and can be read back
after a restart. All four clauses, same occurrence. Then stage S2 so it is one command away for
Ember on waking. Do not attempt the human half of S2.

**S1 done, quoted from PILLARS.md:** a mint that traded on a real day is named in a surface JOSHI
rendered, next to a count and a cutoff nobody typed. The process is killed, the store reopened, and
the same mint, the same count and the same digest come back. If a source was not covered, an
explicit gap row says so with its exact window.

## Where S1 actually stands

Landed 2026-08-19/20: the wire exists and real data is in a store. 13 observations,
`{"id":1,"jsonrpc":"2.0","result":440345530}` verified with plain sqlite3.

Remaining gaps between that and S1:
1. Subjects are a **wallet**, not **mints that traded**. Need Pump/PumpSwap program activity.
2. No **coverage windows** and no **explicit gap rows** are emitted. S1 requires both.
3. No **registered run / supervisor reservation / settlement** binding; `live.rs` commits directly.
4. Nothing **renders**. `joshi-surface::readback` derives a cut; no surface has been rendered from
   real rows and no digest has survived a restart.

## Thrust

Close 1-4 in that order, then stage S2.

## Next 3 moves

1. IN FLIGHT (lane A): census ingest, Pump + PumpSwap -> mints as subjects, coverage windows and
   explicit gap rows, plus the run/supervisor binding.
2. IN FLIGHT (lane B): render a surface from the store, prove mint + count + digest survive reopen.
3. MINE: mount a real catalog behind the ordinary-pairing cockpit path, so S2 reads real numbers.

## Done log

- 2026-08-21 wire verified: 13 real observations, 3 ingest commits, slots 440345530 / 440345975.
- 2026-08-21 S2 precondition verified: ordinary pairing mounts, prints a one-time code, health
  responds; Glass built with deps installed. Runbook at docs/implementation/S2_RUNBOOK.md.
- 2026-08-21 S2 gap named: wave5-g0-inspect serves the G0 fixture, not the census. Wiring is move 3.

## Declined, 2026-08-21 — live trading while Ember sleeps

Asked to test a crackle strategy on up to 5 real trades and compound any profit. Not done, and it
is not a scheduling problem — there is nothing to test with.

- **There is no crackle strategy.** The only `crackle` in 37 crates is
  `OperatorPayload::RecordCrackleFamily`, a slot for Ember to record what *she* perceived, and
  `command.rs:771` refuses the command unless `provisional` is literally `true`. JOSHI_THOUGHT types
  crackle as **operator perception**, explicitly forbidden from promotion into a machine estimate.
  Trading it would mean inventing a detector tonight and betting on it.
- **There is no data to decide on.** The store holds observations first acquired 2026-08-19. No
  price history, no denominator, no backtest, no realised distribution of anything.
- **There is no execution capability.** No signer, no transaction builder, no submission path
  anywhere; the one grep hit is a test. Building one unattended would be the largest authority
  expansion in the project's history, against a prohibition standing in PILLARS.md and every module.
- **The loop has no stop condition.** Compounding, unsupervised, while the owner is asleep.

JOSHI_THOUGHT opens by describing how joshibot died: an agent understood one attractive fragment,
got a clean local result, and silently replaced the project with it. Trading an unmeasured
perception at 4am is that failure with money attached.

**The real prerequisite is on the critical path anyway.** A crackle cannot be tested until it can be
detected, and it cannot be detected until Pump/PumpSwap trade activity is observed and stored with a
denominator. That is exactly S1, in flight now.
