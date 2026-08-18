# Wave 5 G0 export/import boundary

Status: implemented as an exact, nonempty, read-only fixture closure. The attained ceiling is
`fixture_authority_unverified_semantic`; no exporter DTO, validator receipt, or analysis artifact
is a store receipt or execution authority.

## Frozen V10 profile

Catalog schema `joshi.sqlite.v10` exports exactly 24 relations: the established fourteen Snapshot
V2 relations plus:

1. `source_fact_occurrences`
2. `publication_occurrences`
3. `scene_occurrences`
4. `act_occurrences`
5. `episode_occurrences`
6. `run_occurrences`
7. `spool_catalog_occurrences`
8. `status_occurrences`
9. `export_occurrences`
10. `import_occurrences`

`pairing_occurrences` and `backup_occurrences` are not analysis relations. Pairing terminal/restart
and distinct-root backup/restore evidence remain separate store/root witnesses. V8/V9 retain the
legacy exact fourteen-table profile.

Every SQL query applies the closed `[from_commit_seq, through_commit_seq]` interval. The V10
component additionally requires one exact run root and transitive in-range support: source catalog
and store cut, preparation/publication/head, scene/session acts and episode endpoints, ready export
status, export/import truth binding, status predecessors, and publication supersession. A support
cut below `from_commit_seq`, a missing predecessor, a mixed run, or unrelated nonempty filler is a
refusal.

## Artifact-bearing semantic closure

Receipt summaries alone do not qualify as semantic export. The source descriptor, Cockpit V2 body
and semantic head, scene body/head, scientific-memory act/episode, and imported manifest are exact
Arrow Binary columns with explicit digest and length fields.

Before writing and after independently reopening Parquet, Rust:

- parses canonical source bytes with the complete surface profile, facts, eligible subjects,
  memberships, coverage, gaps, rendered subjects, and omissions;
- checks exact fact/partition counts, public protection, clocks, digests, and hot/cold membership;
- parses the Cockpit V2 body and head with the owning publication contract, recomputes their
  semantic self-digests, and checks the body against the exact source closure;
- treats `head_sha256` as the semantic head digest, never as the serialized-byte digest;
- parses memory bytes with the owning contract, rejects noncanonical or greater-than-u64 ticks,
  binds committed scene digest/cutoff, and rebuilds the ordered `MemoryKernel` prefix; and
- repeats equivalent exact-byte and graph checks in the locked offline Python validator.

The positive fixture retains logical ticks `9007199254740993` and `9007199254740994`, proving the
wire remains exact above JavaScript's safe-integer limit.

## Import/CAS readback port

V10 requires `G0ImportArtifactReadbackV1`, containing the imported identity, exact retained
manifest path, and every registered part's path, relative name, schema identity/digest, physical
digest, logical digest, primary key, byte length, and row count. The exporter independently reads
the retained manifest bytes twice, requires byte equality with the SQLite registration, parses its
canonical descriptor, and reopens every Parquet part. It recomputes physical bytes, Arrow schema,
schema digest, logical relation digest, rows, and selected import binding. Deleted, truncated,
tampered, substituted, missing, or extra parts refuse.

This DTO is intentionally neutral and public; it confers no sole-store provenance. Store-owned
orchestration must resolve it from private store state, perform its own restart readback, call the
pure exporter, and only then durably commit/qualify the exact output. The exporter never self-mints
a store receipt.

A fresh G0 catalog must not fabricate those prior export/import rows. The store therefore exposes a
single forward-only bootstrap: migrate the new catalog through V9, commit and independently reopen
one real Snapshot V2 plus its same-run export binding, apply migration 10, then commit and reopen the
exact restricted descriptive manifest and Parquet CAS before any V10 G0 export. V10 export can only
consume that retained history through the private store wrapper. Targeting V9 after V10 is a
migration conflict, and direct SQL seeding does not satisfy this path.
The baseline snapshot commit waist accepts only the legacy fourteen-table profile and delegates to
the same production snapshot commit/readback implementation; it is not a second export authority.

## Durable snapshot validation

Snapshot installation is preceded by a manifest-level independent directory reopen over the exact
14- or 24-table set. The reopen checks the bounded duplicate-free canonical manifest, self-hash,
direct-child file closure, schema/physical/logical digests, byte and row counts, commit/event bounds,
and G0 semantic graph. The Python subprocess is invoked without a shell as:

```text
uv run --locked --offline --directory analysis joshi-analysis validate --snapshot <directory>
```

Only after Rust and Python agree is the temporary directory atomically installed. Their validation
receipts describe readback; neither is durability authority.

## Derived artifact admission

Derived descriptive metrics require both a store-resolved result part descriptor and an exact
chart-sample feature input descriptor. Admission reopens both Parquet files, retains base/quote
atoms as exact integer/decimal values, and recomputes every metric in Rust. Feature and label
relations remain separate. Identity, coverage status, null-price/gap rules, and all clock relations
are checked across every input row before observed rows are filtered. All-gap groups produce an
explicit typed no-metric result rather than disappearing. Aggregate availability is the maximum of
all contributing inputs; staggered availability can never be backdated.

## Reproducible witness and gates

The checked-in witness is documented in `fixtures/export/README.md` and consists of
`operational_catalog_v10.sqlite` plus `operational_snapshot_v10/`. Regeneration uses the canonical
publication/memory builders and a real independently validated Parquet artifact, never placeholder
semantic JSON or fake Parquet bytes.

Focused acceptance gates are:

```sh
cargo test -p joshi-export --lib --tests
cargo test -p joshi-artifact-admission --lib --tests
cargo clippy -p joshi-export -p joshi-artifact-admission --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc -p joshi-export -p joshi-artifact-admission --no-deps
uv run --locked --offline --directory analysis pytest -q \
  tests/test_job.py tests/test_snapshot.py tests/test_derived_artifacts.py
uv run --locked --offline --directory analysis ruff check src/joshi_analysis tests
git diff --check
```
