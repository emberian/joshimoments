# V18 Fixture Research-Disposition Persistence

Status: implemented and verified at `unverified_semantic_fixture_only`; explicitly not an
authenticated human review or approval.

Migration `0018_wave6_research_disposition.sql` and the `joshi-store` research adapter retain the
exact checked caller-fed disposition only after resolving the exact prior V17 proposal. Commit and
readback reparse both documents, recompute the disposition identity and physical content digest,
and require the disposition clock to follow proposal creation.

## Frozen fixture

- disposition ID: `human-disposition-f203c6ccee72320de0adf61e805f8e65`
- physical content digest: `sha256:a43c7d584056f4dc536f61dbbb80ee670c1797412f9d8d32024d09b250d42577`
- proposal ID: `research-proposal-482af6e85fb9edae5a00eccf29af12b2`
- disposition: `hold`
- caller reviewer ID: `fixture-reviewer-unverified`
- migration SHA-256: `95af445b4fda3bb8beb919d6adb7570471335f74418ecebb5579b1c0cd8f3850`

The row fixes `identity_authority` to `caller_fed_fixture_unverified` and structurally fixes
`human_review_verified`, `approval_authority`, `execution_authority`, and `result_authority` to
false. The public receipt exposes one closed no-authority state whose accessors return those false
values. Persistence therefore proves exact append,
proposal lineage, idempotent retry, and restart readback—not that the named reviewer exists or made
a decision. Changed bytes, a missing proposal, a second batch for one identity, and backdated or
foreign proposal binding refuse.

Core report `joshi.core.wave6_program_registration_report.v9` and root witness
`joshi.wave6.fixture_foundation_witness.v8` carry the exact disposition/proposal binding and
retain authenticated human review, proposal execution, and research-result qualification as
false.

## Verification

```sh
./schema/validate.sh
cargo test --locked --offline -p joshi-store --all-targets
cargo clippy --locked --offline -p joshi-store --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline -p joshi-store --no-deps
```
