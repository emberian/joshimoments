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

1. Census ingest: Pump + PumpSwap program signatures -> transactions -> mints as surface subjects,
   with real coverage windows and an explicit gap row for anything not covered.
2. Bind the census occurrence to a registered run with a real supervisor reservation and settlement.
3. Render a surface from the store and prove mint + count + digest survive kill and reopen.

## Done log

- 2026-08-21 wire verified: 13 real observations, 3 ingest commits, slots 440345530 / 440345975.
