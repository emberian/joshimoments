# Operator admission fixtures

The canonical cross-language bytes remain owned by Glass:

- `apps/glass/src/contract/golden.ts` contains the exact `joshi.glass.view` V1 bytes and digest;
- `apps/glass/src/operator/golden.ts` contains the exact `joshi.operator.command` V1 payload,
  command bytes, and digests.

`joshi-operator` reads those files directly in its Rust tests. The command golden deliberately uses
a placeholder view digest and candidate (`radon`), so the admission test first proves that it does
not bind to the Glass golden, then constructs an exact paired command using the parsed Glass digest
and rendered `coin-a` candidate. This prevents an accidental test-only claim that the two frozen
independent goldens were one witnessed occurrence.

V1 binds scene ID and exact view digest. It does **not** bind intended presentation policy,
per-occurrence assignment, or proven viewport exposure. Those require exact registered bytes and a
future V2 or a separately admitted binding artifact; digest-only references are insufficient.

