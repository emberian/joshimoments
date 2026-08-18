# Lane 01 handoff: Rust contract spine

Implemented and verified an offline, keyless fixture-to-query spine:

- root Cargo workspace (`crates/*`, explicit `apps/core`) pinned to Rust 1.97.1 / edition 2024;
- first-party workspace package metadata uses `AGPL-3.0-or-later`;
- `joshi-domain`: validated opaque identities, canonical decimal-string `u64`/`u128`, independent
  clock domains and as-of vectors with non-lossy scoped cursor watermarks, exact microsecond UTC
  JSON timestamps, open-world discriminators, shared asset/account/episode/lot/effect and
  venue/pool/position/quote/protocol-profile identities, and distinct witnessed versus
  retrospective views;
- `joshi-evidence`: separate acquisition, observation, source-event, assertion, and SHA-256 content
  identities; a storage-ready atomic batch/digest/cursor contract; many-event observation links;
  versioned/superseding assertions; append-only coverage windows, gaps, and recoveries; payload and
  queue bounds; explicit full/closed backpressure; and idempotent as-known fixture replay;
- `joshi-core`: embedded/offline JSON fixture runner and versioned deterministic query. The fixture
  proves that equal bytes in distinct occurrences produce two observations but one blob, and that
  late unknown evidence and gap recovery are absent from the witnessed scene but present
  retrospectively. Rust tests also bind the TypeScript glass golden's exact bytes/SHA-256 and check
  its scene indices, references, and scoped-watermark bounds.

Dependencies are deliberately narrow: `serde`/`serde_json` for versioned wire contracts, `time` for
validated UTC instants, `thiserror` for typed failures, `sha2` for evidence/CAS identity, Tokio's
runtime/sync features for bounded single-writer ingress, and `clap` for the local CLI. The core
dependency tree contains no HTTP/RPC, Solana, wallet, signing, transaction-building, submission, or
database package. BLAKE3 was not retained; SHA-256 is the only evidence/CAS hash in this lane.

Verification on the pinned toolchain:

```text
cargo test --locked --workspace --all-targets       108 passed
cargo clippy -p joshi-domain -p joshi-evidence \
  -p joshi-core --all-targets -- -D warnings        passed
RUSTDOCFLAGS='-D warnings' cargo doc (three crates)  passed
cargo run -p joshi-core -- --pretty                 passed
```

Continuation boundary: `InMemoryCatalog` is intentionally a deterministic fixture/replay seam, not
durability. The storage lane should preserve `CommitReceipt`, identity-conflict, append ordering,
exact-byte hash, gap, and `CatalogSnapshot::at_commit` semantics behind SQLite. Binary observations
already enter through `ObservationDraft::payload`; only the convenience CLI fixture encoding is
UTF-8. `BlobId` identifies content only: media type belongs to the observation reference, while
encoding, retention, storage, privacy, and protection-domain dedupe belong to store policy and
physical records. Only committed `CursorAdvance` values may populate sorted scoped as-of cursors;
descriptive acquisition/observation cursors never do. Canonical typed economics must use the wire
integer/newtype contracts rather than numeric values inside the non-authoritative assertion
extension field.
