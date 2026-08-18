# Wave 5 package gates

Status: package-level compile/test/lint gates are green for the focused Wave 5 set, but the
root readiness witness is blocked at the repository format gate. These results are build facts
only; they do not qualify live providers, durable store bindings, restart recovery, publication,
Glass, retention, scientific, or economic capabilities.

## Workspace enumeration

`cargo metadata --no-deps --format-version 1 --offline` reported 40 packages:

`joshi-collector`, `joshi-domain`, `joshi-spool`, `joshi-evidence`, `joshi-store`,
`joshi-artifact-admission`, `joshi-export`, `joshi-operational-status`, `joshi-operator`,
`joshi-publication`, `joshi-projection`, `joshi-accounting`, `joshi-liquidity`, `joshi-market-math`,
`joshi-surface`, `joshi-supervisor`, `joshi-admission`, `joshi-pump-api`, `joshi-sources`,
`joshi-core`, `joshi-acquisition-policy`, `joshi-attention`, `joshi-census-bakeoff`,
`joshi-episode-closure`, `joshi-epistemic-book`, `joshi-market-state`, `joshi-mechanics-capability`,
`joshi-operational-circulation`, `joshi-pairing`, `joshi-pump-adapter`, `joshi-retention`,
`joshi-scientific-memory`, `joshi-source-registry`, `joshi-wallet-admission`, `joshi-wallet-source`,
and `joshi-wallet-topology`.

## Focused gate evidence

All commands used `--locked --offline` and covered this focused set:

`joshi-retention`, `joshi-sources`, `joshi-source-registry`, `joshi-surface`,
`joshi-operational-circulation`, `joshi-admission`, `joshi-supervisor`, `joshi-publication`,
`joshi-scientific-memory`, `joshi-episode-closure`, `joshi-export`, `joshi-epistemic-book`,
`joshi-operational-status`, `joshi-census-bakeoff`, and `joshi-mechanics-capability`.

| Gate | Result | Command / qualification |
| --- | --- | --- |
| Formatting | PASS for focused invocation | `cargo fmt --all -- --check` completed before the root witness; the root rerun later exposed a source-set parse failure below. |
| Check | PASS | `cargo check --locked --offline -p ...` finished `dev` profile successfully. |
| Tests | PASS (build/test fact) | `cargo test --locked --offline -p ...` and scientific-memory all-target rerun completed without test failures. |
| Clippy | PASS | `cargo clippy --locked --offline -p ... --all-targets -- -D warnings` completed cleanly. |
| Rustdoc | BLOCKED | Strict `RUSTDOCFLAGS='-D warnings' cargo doc ... --no-deps` failed on scientific-memory model line 435. |

The earlier successful focused format invocation and later root format invocation disagree because
the shared workspace was being edited concurrently. The root readiness result is authoritative
for the settled source snapshot at its invocation; rerun all gates after the owning lane settles.

## Exact blockers

1. `cargo fmt --all -- --check` (first command in `scripts/offline-readiness`) failed while
   parsing `crates/joshi-scientific-memory/src/tests.rs:452:126`:

   `serde_json::json!("bad\u0000id")` uses a non-braced Unicode escape. Rust requires
   `\u{0000}`. Because this is the first root gate, no root status or Wave 5 digest was emitted.

2. Strict rustdoc failed at `crates/joshi-scientific-memory/src/model.rs:435:9` with
   `duplicate serde attribute deny_unknown_fields`. This independently blocks the root doc gate.

3. `/tmp/joshi-wave5-readiness.RBHriR/wave4-witness.json` exists but contains the captured
   Wave 4 format diff; it is not a valid Wave 5 witness. No `wave5-witness.json`, status, or digest
   was produced. The root script is therefore blocked at `offline-readiness` format, before
   `wave5-ignition-readiness`.

## Semantic ceiling

Per `99_INTEGRATION_REVIEW.md`, passing package gates cannot promote any capability. Current
ceilings remain fixture/offline or explicitly unverified: C0 sealed source policy only, pure
retention and scientific-memory kernels, unverified surface/publication/status projections,
fixture/sample census and mechanics checks, and no live/nonfixture/restart/sustained claims.

No provider calls, secrets, remote deploys, or transactions were performed.
