# V17 Fixture Research-Proposal Persistence

Status: implemented and verified at `unverified_semantic_fixture_only`.

Migration `0017_wave6_research_proposal.sql` and the `joshi-store` research adapter persist one
exact N02 proposal only after resolving its three design descriptors to the corresponding prior
V14 evaluation artifacts. The adapter reparses the checked canonical bytes on commit and reopen,
recomputes the proposal, content, commitment, policy, and evidence-closure digests, and compares
the normalized descriptor relation with the exact earlier artifact IDs, kinds, semantic digests,
and store commit sequences.

## Frozen fixture

- proposal ID: `research-proposal-482af6e85fb9edae5a00eccf29af12b2`
- proposal digest: `sha256:482af6e85fb9edae5a00eccf29af12b24319e5b0ca2cce81fda3aceb9632d5c4`
- physical content digest: `sha256:5da44fffda071866e79f80624ecece320884f69a598a582b4a5362c37d731503`
- commitment digest: `sha256:b2ac507fe5b345e86597935cf0bf531ce724a47b1716a6fe34d3d324fc18074e`
- policy digest: `sha256:2496363c244f5d4f49dc884e2bd4efca50608986c1ad0f12d060b4646dd0a51b`
- evidence closure: `sha256:9fcff155013a8fd8121d6fccc377f0450c8ecc76e52b9be859b3f0fd7a0b0103`
- migration SHA-256: `88a16b721e4a7ac56150417255a0914aaffd6104992d56d74ee334c7b77155af`
- closure: three prior evaluations, 18 counterexamples, one zero-query/non-executable
  experiment, and three declared fixture resource units

The fixture's descriptor `commit_seq` values remain explicitly caller-fed fixture claims. The
store separately records and verifies the real commit sequence of every resolved evaluation; it
does not rewrite one clock domain into the other.

## Authority boundary

The durable receipt proves exact bytes, normalized prior-evaluation lineage, idempotent commit,
and restart readback. It does not prove human review, experiment execution, result production,
prospective registration, empirical support, operational release, policy value, or product or
economic capability. A changed proposal cannot replace the existing identity, and the same
proposal cannot be rebound to a second batch.

## Verification

```sh
./schema/validate.sh
cargo test --locked --offline -p joshi-store --all-targets
cargo clippy --locked --offline -p joshi-store --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline -p joshi-store --no-deps
```
