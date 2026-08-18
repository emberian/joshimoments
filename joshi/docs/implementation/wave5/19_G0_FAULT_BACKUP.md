# G0 fault and backup harness

Status: **contract and fake schedule only**. This is not a W5-G0 witness and
does not change `qualification.fullOfflineFaultWalk:false`. The isolated package
at `apps/g0-harness` is intentionally a nested workspace, is not in the root
manifest or lockfile, and has no access to store, collector, spool, publication,
pairing, Glass, memory, export/import, status, or backup implementations.

It freezes the seam shape called for by the Wave 5 G0 matrix. It follows the
existing spool/supervisor convention of named durable failpoints, but does not
pretend that their package-local points establish a root occurrence.

## Required run/result shape

A `joshi.g0.fault_run_manifest.v1` is strict JSON: unknown fields are refused;
the schema version, authority literal, lower-case IDs, and SHA-256 digests are
checked; and `steps` must equal this ordered list exactly once:

1. `pre_io_reservation`
2. `origin_fsync`
3. `store_receipt`
4. `catalog_binding`
5. `catalog_ack`
6. `semantic_fact`
7. `publication_prepare`
8. `publication_head`
9. `pairing_exchange`
10. `glass_read`
11. `memory_act`
12. `memory_episode`
13. `export`
14. `import`
15. `status`
16. `backup`
17. `restore`
18. `reopen`

The paired `joshi.g0.fault_result.v1` must bind the exact manifest and schedule
digests, include one ordered result for each step, provide typed recovery
invariants, and validate its exact evidence bundle digest. A missing,
duplicated, or reordered step is invalid before a result could be considered.
The current runner emits only `not_implemented` or `blocked`, with a nonempty
reason and `fullOfflineFaultWalk:false`. Parsing rejects `true`; neither fixture
labels nor a manually changed result may promote the claim.

The existing Wave 5 acceptance matrix remains authoritative: pre-I/O
reservation/readback, fsynced origin through store receipt and run-bound catalog
binding/ACK, exact semantic fact, atomic publication body/head, same-origin
paired Glass read, scene-bound memory chain, nonempty export/import, status,
and backup/restore/reopen are all required. An ACK never grants deletion
authority, and an origin segment remains immutable across retry.

## Deterministic fault matrix

`fixtures/g0-fault/fake_fault_schedule.json` lists the same eighteen coverage
steps and one pre-transition plus one `after_*` kill point for each. The Rust
harness enumerates both the eighteen pre-transition crash points and the
eighteen post-transition kill points. The deterministic schedule uses one
baseline plus exactly one injected process-kill/power-loss/panic scenario on
each side of each seam; no schedule may silently omit or duplicate a boundary.

For every injected crash, the future adapter must prove all of these from
durable producer/store readback rather than booleans:

- the prefix is either absent or exactly once durable after reopen;
- retry uses the same reservation/idempotency identity and exact origin bytes;
- no duplicate or conflicting receipt, catalog binding, fact, publication,
  pairing consumption, memory act/episode, export/import, or backup record is
  created;
- records after the injected seam are absent until their adapter replays them;
- catalog ACK does not authorize deletion; and
- recovery opens only the committed prefix and rederives every linked digest.

For publication, status, semantic fact, Glass, and memory, an adapter must not
fill an absent receipt with a caller DTO. For pairing, a crash around exchange
must prove one-time consume/revoke/restart behavior under the reviewed wire and
clock authority. These are currently typed blockers because those adapters do
not exist.

## Evidence bundle digest

An evidence bundle is `joshi.g0.evidence_bundle.v1` with strictly ordered
`(role, evidenceId, contentDigest)` items. `contentDigest` is a lowercase
`sha256:` digest of the exact producer/store artifact, not an asserted label.
The digest is:

```text
SHA-256(
  "joshi.g0.evidence_bundle.v1\\0" ||
  u64be(item_count) ||
  for every item ordered by enum role then UTF-8 evidenceId:
    u8(role_ordinal) || u64be(len(evidenceId)) || evidenceId ||
    u64be(len(contentDigest)) || contentDigest
)
```

Any duplicate, reordering, identifier change, or content-digest substitution is
invalid. A qualifying future bundle must contain exact producer/store identities
for the reservation, origin segment, durable store receipt, catalog binding,
catalog ACK, source/fact artifact, publication prepare/head, pairing and Glass
read, memory act/episode, export/import, status, backup, restore, and reopen.
It must bind the corresponding physical bytes or store readback—not booleans.
This isolated package legitimately emits an empty, correctly digested bundle
only because no step is represented as passed.

## Backup, restore, and reopen requirements

The backup boundary is a whole recovery set, not a copied database file. Its
manifest must name the snapshot cutoff and contain physical SHA-256 and byte
counts for:

- a consistent SQLite catalog snapshot, application/migration identity,
  maximum included commit sequence, successful integrity and foreign-key checks;
- every catalog-referenced immutable origin segment, publication body/head,
  exported object, and CAS object, with no missing reference;
- the origin-spool inventory and immutable segment identities; the catalog ACK
  is recorded as non-deletion authority;
- private-material inventory with retention/encryption class, key ID only, and
  erasure/tombstone disposition (never secret bytes); and
- exact artifact counts, byte totals, retention/encryption metadata, and the
  evidence-bundle digest.

Restore must target a distinct, empty root while the original paths are
unavailable. It must open and rehash every catalog-referenced origin,
publication, export, and CAS byte object; run SQLite integrity and foreign-key
checks; re-read catalog bindings and operational records at the declared
cutoff; and then reopen the restored root. Extras may be reported but never
substituted. Missing, malformed, unreverified, or original-path-dependent
material disqualifies the walk.

## Adoption boundary

Adapters may be added only by their owning integration work. They must retain
the strict step order and evidence rules, replace only their own typed blocker
with receipts derived from their durable owner, and add a fake crash/restart
test for their seam. A root-owned integration may evaluate a future positive
G0 predicate only when all required seams, crash scenarios, recovered evidence,
and distinct-root backup readback are present. This harness itself remains
false-only until then.
