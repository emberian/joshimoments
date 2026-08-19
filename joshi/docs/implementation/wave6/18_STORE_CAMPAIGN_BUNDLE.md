# Wave 6 exact campaign-bundle persistence

Status: **PASS for one atomic, exact fixture-bundle commit; BLOCKED for prospective execution and
every empirical claim.**

Migration V16 and `joshi-store` retain the five checked N03 campaign documents as one append-only
row:

- campaign registration;
- frozen enrollment;
- deterministic fixture assignment;
- evidence seal; and
- typed fixture adjudication.

The adapter first loads and reparses the exact N00 program, resolves the exact prior
`campaign_registration_fixture` schema, then parses the five documents in their contract order.
It preserves each semantic digest, physical document digest, exact bytes and byte length. A
domain-separated bundle digest closes those five physical digests. Eligible, included, assignment
and outcome counts are recomputed, and the greatest fixture-alleged commit sequence is retained
under that explicit name.

One maintenance transaction inserts the bundle and its store-owned commit. Exact retry returns the
original commit; a changed document under the same batch or a second batch for the campaign
refuses. Readback reloads the prior program/schema, reparses the full chain, recomputes the bundle
identity and every count/digest, and checks prior-schema-before-bundle ordering.

The durable boundary does **not** convert the documents into a prospective journal. Registration,
enrollment, assignment, seal and adjudication do not receive distinct store commits; no assignment
was randomized or blinded; evidence and outcome truth are not store-resolved; and all phase clocks
and alleged commit numbers remain caller-fed fixture content. The fixed ceiling is
`unverified_semantic_fixture_only`.

Frozen identifiers:

```text
bundleId       wave6-campaign:86e1bc6b7ae07e53d8cec7d14c4186718b31d68302f6c1f0af2566b86013aa2b
bundleDigest   sha256:9b4bdf7b4643bb2832f7e41bc7e8e22166c129648c87b88ca9a7b3dfbb9f7011
V16 migration  sha256:537dceffc27402e24cdff8fcb1eb9afcb3b8d9b5ec184260bb021f2a01673a0b
```

Verification:

```bash
./schema/validate.sh
cargo test --locked --offline -p joshi-store --all-targets
cargo clippy --locked --offline -p joshi-store --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline -p joshi-store --no-deps
```

The focused store result is 26 unit tests plus one authority integration test. The exact bundle
case asserts three eligible subjects, two included subjects, two assignments, two outcome
dispositions, maximum fixture-alleged commit sequence 21, idempotent retry and read-only restart.
