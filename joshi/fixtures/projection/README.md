# Exact projection vectors

These fixtures are language-neutral contract expectations for `joshi.read_projection` schema 1.
Every financial integer in an artifact is a JSON string; the only JSON numbers are small closed
schema/decimal-count fields. `adversarial.json` names failure or preservation behavior that the Rust
tests execute against the real accounting, market-math, liquidity, and projection state machines.

The deterministic Rust full-artifact vector is 27,146 compact UTF-8 bytes and has result digest
`sha256:015d40249861b17779ba782e0477bd28b3cadb383ecc6fafe708b0c5c6d72616`, pinned by
`crates/joshi-projection/src/vector_tests.rs`. It is a digest of the schema-ordered compact JSON
material with `resultDigest` excluded, not a hash of pretty-printed fixture text. There is not yet a
TypeScript or Python encoder/acceptance mirror; this is explicitly a single-runtime byte golden.
