# Research lanes

Each lane investigates one subsystem independently and may challenge the assumptions in
`../PROJECT.md`. Lane documents should separate:

- observed facts and source provenance;
- hypotheses and inferred mechanisms;
- proposed abstractions;
- failure modes and counterexamples;
- unresolved questions;
- the smallest useful experimental slice;
- dependencies on other lanes.

The lane outputs are inputs to reconciliation, not architecture decisions by themselves.

## Lane map

1. episode accounting;
2. operator language and elicitation;
3. event tape, clocks, scenes, and replay;
4. fancoin and social transitions;
5. crackle observation and eventual execution semantics;
6. consolidated portfolio and LP inventory;
7. estimation and learning from adaptive attention;
8. product glass and operator interaction;
9. infrastructure, reliability, and security boundaries;
10. build versus buy;
11. epistemic red team;
12. territory/ecology and followed-wallet candidate routing.

The cross-lane reviews are in [`reviews/`](reviews/). Accepted synthesis is in
[`../decisions/`](../decisions/); where a lane's provisional vocabulary conflicts with the
foundation decision, the foundation governs.

The second research wave investigates concrete implementation choices in
[`engineering/`](engineering/). Its lanes are numbered 13–24 and remain provisional until the
engineering synthesis and representative walking-fixture gate accept them.

Engineering reconciliation is in reviews 03–05. The resulting provisional decisions are
[`../decisions/ENGINEERING_FOUNDATION.md`](../decisions/ENGINEERING_FOUNDATION.md) and
[`../decisions/ENGINEERING_CORRIDOR.md`](../decisions/ENGINEERING_CORRIDOR.md).
