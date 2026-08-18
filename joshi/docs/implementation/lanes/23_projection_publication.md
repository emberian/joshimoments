# Lane 23 — durable deterministic projection publication

Status: **pure publication contract and crash/conformance vectors complete; durable store adapter,
migration, and HTTP mounting remain W4-00 integration gates**  
Authority: `read_only_no_execution`  
Code: [`crates/joshi-publication`](../../../crates/joshi-publication),
[`crates/joshi-projection`](../../../crates/joshi-projection)  
Fixture: [`fixtures/publication/publication_vectors.json`](../../../fixtures/publication/publication_vectors.json)

## Delivered boundary

This lane turns one already validated, finalized `ProjectionArtifactV1` into immutable bytes and
append-only publication records. It does not collect market state, value a position, own a
database, select a trade, or expose execution authority. `joshi-publication` depends on the
projection contract for semantic validation and stays above a caller-supplied neutral persistence
port; it must not become a dependency of `joshi-store` or create a store/export cycle.

The public flow is:

```text
complete finalized ProjectionArtifactV1
 -> prepare_projection (pure validation + exact bytes/digests/checkpoint)
 -> durable CAS fsync/readback and PreparedProjectionArtifactReceiptV1
 -> one atomic checkpoint + ProjectionPublicationV1 catalog commit
 -> immutable query by explicit ID or digest
 -> separate later CockpitPublicationV1 append naming exact scene + publication
```

`PublicationFinality` has only `finalized` in V1. A provisional market snapshot can be a separately
named source input and presentation, but it cannot populate landed balances, lots, realized PnL,
or this publication contract. There is no boolean that silently relaxes finality.

## Digest domains are intentionally different

| Field | Exact preimage and meaning |
| --- | --- |
| `resultDigest` | Projection calculator's semantic/result closure, excluding its self field |
| `artifactDigest` | SHA-256 of exact schema-ordered `ProjectionArtifactV1` JSON bytes |
| `inputClosureDigest` | SHA-256 of exact serialized `ProjectionInputClosure` |
| `checkpointDigest` | Immutable resume-checkpoint body, excluding its self field |
| `publicationDigest` | Immutable projection-publication body, excluding its self field |
| `cockpitPublicationDigest` | Immutable cockpit-publication body, excluding its self field |

Receipts echo these domains instead of allowing one digest to stand in for another. In particular,
the cockpit receipt binds `cockpitPublicationDigest`, `projectionPublicationDigest`,
`resultDigest`, and `artifactDigest`; a consumer can prove both the exact head bytes and the exact
financial artifact closure. Receipt retry status is not part of immutable publication bytes.

All digests use lowercase `sha256:` wire form. Commit sequences and byte lengths retain the domain
crate's decimal-string wire representation. Serialization rejects unknown fields and follows Rust
struct order for the exact byte artifact. The fixture independently canonicalizes its JSON
manifest, but canonical object-key sorting is not substituted for the versioned artifact
serializer.

## Full and incremental materialization

`build_projection_incremental(prior, target_draft)` validates the prior artifact, exact
supersession identity, strictly advancing input cutoff, and unchanged calculator build. The target
draft remains a complete point-in-time closure and is passed through the ordinary
`build_projection` path. No “incremental” flag, accumulator residue, or build-path identity enters
the artifact, so a full rebuild and an incremental materialization of the same target draft emit
identical objects, bytes, and `resultDigest`.

The prior checkpoint is a resume aid, never financial truth by itself. A reducer that cannot
produce the complete target closure must refuse rather than publish a delta as a snapshot.

## Prepare, commit, and cockpit-head crash semantics

Preparation is pure. A persistence adapter must write the artifact under its digest-derived blob
identity, fsync, read it back, verify its length and digest, and only then return
`PreparedProjectionArtifactReceiptV1`. Prepared-but-unreferenced CAS bytes are safe garbage.

The first SQL transaction allocates a catalog commit and atomically inserts the exact checkpoint
and immutable `ProjectionPublicationV1`. The second, later transaction appends a
`CockpitPublicationV1` only when its exact scene and projection-publication foreign keys resolve.
It never mutates the preceding cockpit row.

| Crash point | New publication queryable? | Named cockpit selection |
| --- | ---: | --- |
| before or during prepare | no | prior complete publication, explicitly stale |
| after prepare / during SQL commit | no | prior complete publication, explicitly stale |
| after publication commit | yes | prior complete publication, explicitly stale |
| during cockpit append | yes | prior complete publication, explicitly stale |
| after cockpit append | yes | new complete publication |

Thus no failure exposes a half-new financial projection. Recovery retries the same immutable
identity and exact body: a byte-identical retry returns `idempotent`; the same identity with a
different body must conflict. Publication and cockpit supersession links must name the prior
selected row, and both commit sequences must advance.

## Query and freshness semantics

`ProjectionPublicationQueryV1` permits only exact `publicationId`, `publicationDigest`,
`artifactDigest`, or `resultDigest` lookup. It deliberately has no `latest` variant.
`ProjectionSelectionV1` records a named durable query policy, requested finalized cutoff, catalog
commit at which the policy ran, and exactly one tagged outcome:

- `fresh`: the selected publication closes at the requested cutoff;
- `stale`: a prior complete publication plus exact commit lag and reason;
- `unsupported`: a typed reason and optional prior immutable publication;
- `missing`: a typed reason and no manufactured values; or
- `conflicting`: sorted distinct candidates with no silent winner.

Later-known publications are rejected at an earlier evaluation cut. Missing, stale, unsupported,
and conflicting are control states; none carries a numeric zero standing in for money.

## Store and Core integration request

W4-00 owns the implementation. The pure `ProjectionPublicationStore` port freezes the required
semantics without making publication depend on a concrete store:

1. prepare and read-verify an exact content-addressed artifact;
2. atomically commit checkpoint and projection publication with a store-assigned catalog commit;
3. append cockpit publication in a separate transaction; and
4. load exact publication plus exact artifact bytes by an immutable query.

The migration/API must enforce append-only rows, unique IDs and body digests, exact-id idempotency,
supersession foreign keys, artifact/checkpoint/publication closure, and scene/publication foreign
keys for cockpit rows. Store receipts must map every field in the Rust receipt DTOs, including
distinct result/artifact/publication/cockpit digests. A receipt status cannot rewrite a publication
digest.

Expected read routes are explicit identity routes such as
`/api/v1/projection/publications/{publicationId}` and
`/api/v1/cockpit/publications/{cockpitPublicationId}`. Digest lookup may use a typed query endpoint
or an unambiguous digest-key route, but must validate the returned body's exact query identity.
“Current” is a named selection policy evaluated at an explicit cutoff; it is not an in-memory
registry or a mutable latest row.

Glass's presentation-enriched transport is a distinct `joshi.glass.cockpit_launch` envelope. It
must echo the exact durable Rust `cockpitPublicationId` and `cockpitPublicationDigest`; it cannot
rehash a presentation object and impersonate `joshi.cockpit_publication`.

## Golden and adversarial gates

The current language-neutral manifest pins:

- artifact: 1,171 bytes,
  `sha256:54a044671521c467a312dd1b66853cda14afd8bf3f430fcc2c00919a91e7f583`;
- result:
  `sha256:d7c6cbaf0736069a895d126fabeb94ec204bc22285611ba5f5d97098ee34a69b`;
- input closure:
  `sha256:b57ebaf6f3c0edfbc06f63241a0ec52d9cd6330beedfba7cf8bb545b3b949d9b`;
- checkpoint:
  `sha256:61b33e123b45e7b1b831844541f4a9fbf95c04e63f440f38c82000b51276544c`;
- projection publication: 1,430 bytes,
  `sha256:1524b025b3e615358a53ac410600d0c386b6f18a93d9c1e19708ab034f87cb8d`;
- cockpit publication: 901 bytes,
  `sha256:f9ba49c1d85a43bb8ab85bf3ec0c446e53f35fb2e6b6da35bdae65d3557593d1`.

Tests cover full/incremental byte equality, every digest lookup, digest substitution refusal,
wrong cockpit-receipt digest refusal, all explicit selection states, finalized/provisional
separation, and every crash transition in the table.

Glass independently parses the cockpit fixture and recomputes its 800-byte digest preimage,
901-byte full record, and `f9ba49…593d1` digest in
[`contract.test.ts`](../../../apps/glass/src/operational/contract.test.ts), using the durable schema
and digest code in
[`contract.ts`](../../../apps/glass/src/operational/contract.ts) and exact vector in
[`golden.ts`](../../../apps/glass/src/operational/golden.ts). This closes the Rust/TypeScript
cockpit-publication byte seam; it does not imply that TypeScript recomputes financial projections.

Run the focused gates with:

```bash
cargo test --locked -p joshi-projection -p joshi-publication --all-targets
cargo clippy --locked -p joshi-projection -p joshi-publication --all-targets --no-deps -- -D warnings
cargo fmt -p joshi-projection -p joshi-publication -- --check
RUSTDOCFLAGS="-D warnings" cargo doc --locked -p joshi-publication --no-deps
```

## Honest remaining gates

The fixture and fake crash store prove the pure contracts, not SQLite durability. W4-06 is not
operational until the W4-00 owner lands the migration and neutral adapter, exercises real
fsync/readback plus transaction fault injection, exposes immutable authenticated read routes, and
proves the returned bytes against this fixture. TypeScript independently verifies the cockpit
publication preimage and bytes. The projection artifact and projection-publication preimages still
have only the Rust reference implementation and exact language-neutral byte fixtures; an
independent second-runtime recomputation remains open.

No contract in this lane claims live quote freshness, execution, profit, authorization to move
funds, or permission to sign or submit a transaction.
