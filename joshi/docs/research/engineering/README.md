# Engineering foundation lanes

These documents are the second pre-engineering research wave. They test concrete implementation
choices against the accepted semantic foundation and the August-to-September runway constraint.
They are evidence for an engineering decision; no individual lane is architecture authority.

## Lane map

13. runtime and language choice;
14. reference architecture and process topology;
15. data, replay, and storage;
16. product shell and UI;
17. Solana, Pump, PumpSwap, and Meteora protocol plane;
18. research and machine-learning environment;
19. verification and testing;
20. exact numerical and accounting core;
21. Pump product and social-surface acquisition;
22. streaming scale and provider cost;
23. developer experience and repository stewardship;
24. runway-aware delivery economics.

## Current convergence

The lanes agree on a local-first monorepo, modular source architecture, TypeScript/React glass,
one authoritative writer, SQLite plus content-addressed blobs, immutable Parquet exports, ephemeral
DuckDB analysis, Python-first research, explicit source gaps, and no transaction authority.

They intentionally disagree about the first durable core runtime. Rust has the strongest protocol,
numeric, columnar, and later-authority fit; Python has the shortest route to an initial truthful
local application; .NET/F# and OCaml offer credible semantic and developer-experience alternatives.
The cross-reviews and walking-fixture bakeoff must resolve that disagreement without delaying
ordinary cockpit use.

The provisional synthesis is in
[`../../decisions/ENGINEERING_FOUNDATION.md`](../../decisions/ENGINEERING_FOUNDATION.md), with the
bounded falsifier and first delivery corridor in
[`../../decisions/ENGINEERING_CORRIDOR.md`](../../decisions/ENGINEERING_CORRIDOR.md).
