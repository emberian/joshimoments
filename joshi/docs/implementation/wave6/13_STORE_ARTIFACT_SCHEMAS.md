# Wave 6 exact artifact-schema catalog

Status: **PASS for durable exact schema bytes under N00; V13 retains three evaluation contents and
V14 separately retains their fixture DAG; BLOCKED for every empirical or operational claim.**

Migration V12 adds `wave6_registered_artifact_schema_v1`. It is a one-way join from the exact N00
program row to the six checked schema documents already named by that registration.

## Exact closure

For each registered artifact kind, the store:

1. read-only reparses the exact durable program registration;
2. resolves the requested `kindId`, `schemaId` and `schemaDigest` from that document;
3. requires a bounded JSON object with exactly one trailing newline;
4. hashes the supplied bytes and requires exact equality with the registered SHA-256;
5. commits program/kind/schema/digest/bytes/length under a store-owned maintenance commit; and
6. reloads, rehashes and rechecks the full registration mapping before returning a receipt.

The SQLite trigger independently requires the kind/schema/digest triple to occur in the exact
stored registration. Rows are append-only and unique by program/kind, program/schema and
program/digest. Exact retries reuse the original commit. Content substitution, invented kinds and
a second batch for the same kind refuse.

The six retained documents are:

| Kind | Schema |
| --- | --- |
| `campaign_registration_fixture` | `joshi.wave6.campaign-registration.v1` |
| `known_truth_evaluation_fixture` | `joshi.analysis.wave6-known-truth/v1` |
| `market_atlas_fixture` | `joshi.analysis.wave6-market-atlas-snapshot/v1` |
| `protocol_known_truth_evaluation_fixture` | `joshi.analysis.wave6-protocol-known-truth/v1` |
| `research_proposal_fixture` | `joshi.analysis.wave6-research-desk/v1` |
| `structural_known_truth_evaluation_fixture` | `joshi.analysis.wave6-structural-known-truth/v1` |

The Core `wave6-program-registration` command commits all six in this exact order. Its V5 report
emits each kind/schema/digest/commit tuple, requires `registeredSchemaCount="6"`, then proves the
same tuples and bytes through a read-only reopen. Re-running the command yields the same six
original commit identities.

## Authority boundary

A schema is not an artifact. No row in V12 claims that a fixture was evaluated, a campaign was
registered, a proposal was approved, an atlas was observed, a response was estimated or a policy
was useful. The store returns only `unverified_semantic_fixture_only`; it does not resolve a Wave 5
gate or introduce provider, presentation, wallet, signing, transaction, deployment or mutation
authority.

The three checked evaluation artifacts under `fixtures/wave6/artifacts` exactly implement their
registered schema fields and are independently regenerated and reparsed by the Python known-truth
suite. V13 retains those exact output bytes under a separate content-only receipt. V14 then binds
them in a distinct fixture occurrence with explicit fixture time and parent closure. Repository,
schema or content-row presence alone does not raise this catalog's ceiling.

## Verification

```bash
./schema/validate.sh
cargo test --locked --offline -p joshi-store --all-targets
cargo clippy --locked --offline -p joshi-store --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline -p joshi-store --no-deps
cargo test --locked --offline -p joshi-core wave6_registration --lib
```

The store suite commits, retries and read-only reopens all six exact schema files and exercises the
three refusal families above. The Core check confirms that latest-schema migration still preserves
the exact N00 registration witness without changing its false qualification fields.
