# Implementation lane 25: production export and restricted artifact readback

Status: operational-store read, Snapshot V2, selected lossless coverage, cross-runtime validation,
restricted analysis V2, independent Rust readback, and store commit→import→restart readback are
implemented. The root export→analyze→import service walk remains an integration gate, and the
public V1 receipt does not yet echo the three occurrence identities. Prospective decision-study
export is correctly refused until a successor relation set can preserve its frozen DTOs.

## Production snapshot

`joshi-export::export_operational_snapshot_v2` opens an immutable V8 `SQLite` backup read-only at an
explicit commit cutoff and sorted publication closure. It verifies application/user versions,
every migration ledger name and source digest, the cutoff occurrence, catalog bytes before and
after the read, and distinct semantic-versus-byte publication digests. It has no dependency on
`joshi-publication`, `joshi-projection`, or `joshi-store`; the neutral descriptor breaks the
store→export→publication→projection→store cycle without weakening typed admission.

The exporter materializes all fourteen frozen Arrow schemas into new Parquet parts. Empty optional
relations retain their exact schema on readback. Every part is independently reopened in Rust;
schema, canonical logical digest, physical digest, byte length, row count, primary key, event and
commit bounds, and coverage summary are recomputed. Exact atom fields remain `decimal128(20,0)` or
refuse. The Python descriptive transform uses integer cross-products and checked half-away
rational PPM: adjacent atoms above 2^53 remain distinct and values above the frozen u64 boundary
refuse, so no `DOUBLE` cast can silently round financial atoms.

Snapshot V2 adds a strict operational origin, exact projection/cockpit publication tagged union,
and evidence/projection/count truth fingerprint while preserving Snapshot V1. The preregisterable
`origin.export_request_id` is distinct from the content-derived `snapshot_id`. Rust installs the
directory only after its readback and the locked Python semantic receipt agree on snapshot,
manifest, table count, row count, and as-known mode.

The deterministic operational identities are:

- catalog `sha256:b5812f0e6ef903e44049717d572755cdbc94a99721e4c64ed79451c745111e3e`;
- snapshot `sha256:667934d19480a9d6e88181e0b374aff07d5dc58864037630699becbb43938fe6`;
- manifest `sha256:0d6642232bba99d330ca1328f597f930808a0e90c75c56e5e26e7123c4b55cbe`.

## No green-by-omission

The exact adapter derives scenes and an explicit, sorted coverage-window selection. Snapshot V2
can represent coverage only when both window bounds are Wall, gap lower is Wall with absent upper,
and any latest recovery is terminal `complete` with Wall `recoveredThrough`. Open, Commit,
SourceCursor, Unknown, partial, or unrecoverable selected records refuse without mutating or
discarding their valid source evidence. Scope identities are canonical SHA-256s of the exact
source/family/subject tuple. The golden contains two scenes, one coverage window, and one gap and is
validated in both runtimes.

Snapshot V2 has no lossless protocol/launch/session/choice/outcome/interview relation. Export
therefore refuses `source_fact_artifact`, `episode_protocol_v1`, `episode_launch_v1`, pairing,
nomination, or explicit-abstention rows rather than synthesizing candidates, territories, or
choices from IDs and opaque bytes. Frozen episode-closure DTOs remain inputs to a future successor
relation set, not authorization to reinterpret V2.

A nonempty prospective export needs a frozen successor relation set or lossless adapters covering
eligible membership, selected candidate XOR explicit abstention, decision cutoff/deadline,
presentation/exposure, episode, fixed-horizon outcome/censoring, interview, provenance, and exact
coverage. Until then the root witness must report the prospective-export gate unavailable.

## Restricted artifact

Python retains derived V1 for the frozen research fixture. Operational publication requires strict
`joshi.analysis.derived-artifact/v2` and a preregistered `analysis_run_id`, distinct from the
content-derived `artifact_id`. Its manifest closes producer/build/config/lock digests, input
snapshot/manifest/cutoff/publications, fit and maximum input availability, support, windows/gaps,
uncertainty, exact Parquet schema/logical/physical bytes, and literal restrictions:

- no census ranking or hot-scope activation;
- no observation, fact, or financial-truth mutation;
- no economic authority; and
- descriptive, noncausal, non-strategy claims only.

`joshi-artifact-admission` returns a private-field capability only after duplicate-key and
canonical-JSON checks, safe direct-child closure, independent typed Parquet readback, support and
coverage closure, and future-known refusal. The checked operational artifact is
`sha256:c3bdb466464f40bd262500641b152320a4d2f4d404928e054be7fb9bd0c1ffa5`
for `analysis-run-production-fixture-001`.

## Durable integration contract

The private store seam now implements:

1. Store creates a consistent immutable backup plus a private neutral publication descriptor at
   an exact cutoff.
2. Exporter returns `ValidatedProductionSnapshotV2` only after both validations.
3. Store commits `export_request_id` and binds the later content `snapshot_id`, exact
   manifest/parts, both receipts, cutoff/publications, and a recomputed before/after truth
   fingerprint in one immutable registration.
4. Analysis runs under separately reserved `analysis_run_id`.
5. Store imports `ValidatedDerivedArtifactV2` under separately reserved `import_id`, rechecks the
   registered snapshot/publications and exact bytes, and proves the evidence/projection/financial
   truth fingerprint is unchanged before and after.
6. A restart reopens and re-verifies the exact derived part by durable `import_id`.

The remaining service integration must expose typed occurrence-complete receipts and never expose
structural insert methods. The current public V1 receipt does not echo `export_request_id`,
`analysis_run_id`, and `import_id`, so it cannot be claimed as the final root witness receipt.

Import may add only `derived_analysis_artifact` and its own ingest commit. It cannot write
observation, assertion, source-event, financial-effect, projection-publication, census order,
scope lease, or execution tables. The before/after truth guard remains required even though the
artifact contract also denies that authority.

## Gates and nonclaims

```sh
cargo test --locked -p joshi-export --test operational_snapshot
cargo test --locked -p joshi-artifact-admission
cargo test --locked -p joshi-store --all-targets
cargo clippy --locked -p joshi-export -p joshi-artifact-admission \
  --all-targets -- -D warnings
uv --directory analysis run --locked ruff check .
uv --directory analysis run --locked pytest -q
uv --directory analysis run --locked joshi-analysis validate \
  --snapshot ../fixtures/export/operational_snapshot_v2
```

Tests prove deterministic migrated-catalog construction, nonempty coverage readback, strict
coverage-selection ordering, unrepresentable-boundary refusal, Rust/Python agreement, exact
publication substitution rejection, future scene refusal, prospective-protocol omission refusal,
operational artifact reproducibility, altered-output rejection, required analysis occurrence
identity, and a self-rehashed future-known refusal. No test ranks or activates scope, claims
prediction, or obtains execution authority. A nonempty prospective choice/session export and the
root service walk remain explicit open gates rather than inferred completion.
