# G0 fault and backup harness

Status: **strict schedule plus non-promoting partial evidence**. This is not a
W5-G0 witness and does not change `qualification.fullOfflineFaultWalk:false`.
`apps/g0-harness` is now a root workspace library because Core attaches exact
artifact evidence from the implemented offline source/publication/memory prefix.
The harness itself owns no store, route, source, or backup authority.

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
The adapter-free runner emits only `not_implemented` or `blocked`. The partial
runner may emit `observed_partial` only when exactly one evidence role is present
for that step; hidden evidence, duplicate roles, or an observed step without its
artifact is invalid. Both runners emit `fullOfflineFaultWalk:false`, and parsing
rejects `true`; neither fixture labels nor a manually changed result may promote
the claim.

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

Core now also exposes `wave5-g0-fault-ledger` and the wrapper
`scripts/wave5-g0-fault-ledger EMPTY_STATE_DIRECTORY`. It executes all 37
frozen rows on distinct fresh state roots, observes the mapped deterministic
interruption, attempts recovery on that same state, and records either the
complete eighteen-role root evidence bundle or a typed, hashed recovery
refusal. A deep verification run completed all 37 rows in 788.68 seconds.
This is materially stronger than the old adapter map, but its execution kind is
explicitly `deterministic_in_process_error_injection`: it does not impersonate
the schedule's literal process-kill, power-loss, or panic modes and therefore
still emits `fullOfflineFaultWalk:false`. It is intentionally excluded from the
ordinary fast readiness command.

Core also exposes a bounded `wave5-g0-process-kill-scenario` command. It starts
a separate Core child for one exact checked schedule row, arms only that row's
mapped fault boundary, waits for the child to publish a synchronized marker
*inside the fault check*, terminates the parked child process, and then recovers
the same state into the eighteen-role root evidence bundle. Ordinary
in-process fault paths never arm this behavior.

This closes actual process termination for one requested scenario at a time.
It deliberately emits `fullOfflineFaultWalk:false`: one row is not the 37-row
schedule, and an OS process kill is neither a power-loss nor a Rust-panic witness even
when the frozen row names one of those modes. The nonignored integration test
covers a real pre-reservation child kill; an explicit ignored test walks one
process-kill row from each of the supervisor, catalog, component, inspector,
and final-recovery adapter families.

The deliberately slow `wave5-g0-process-kill-ledger` command repeats that
operation for all 36 mapped before/after boundaries plus a no-fault baseline,
each under a fresh state root. Its narrow positive invariant is
`everyMappedBoundaryProcessKilled:true` together with an exact partition of
same-state root recoveries and typed, hashed recovery refusals. A kill after
provider I/O but before origin fsync, for example, must retain its abandoned-
attempt gap and refuse a gap-free root rather than silently re-fetch. The
ledger still sets `mixedScheduledModesFullyExecuted` and
`fullOfflineFaultWalk` false: twelve frozen rows ask for process kill, while
the remaining rows ask for power loss or panic and are not relabeled.

The first complete process-kill ledger finished with 36/36 exact boundary
markers and terminations, 33 complete same-state root bundles, and three typed
refusals: `before_origin_fsync`, `after_pre_io_reservation`, and
`after_origin_fsync`. The first and third lose or cannot durably associate a
provider response before the supervisor can prove local durability; the
second retains a terminal pre-I/O cancellation for the finite fixture run.
None is silently re-fetched or omitted. The exact ledger digest from that run
was
`sha256:79bfa81261897ca8ef386d3d3888d1f052f12d2fddf7f5ee049d7121f6b55552`.
An earlier run exposed that process death around restored reopen bypassed the
ordinary RAII root-restore guard. Recovery now first restores only the six
known quarantined roots, refuses symlinks/unknown ordinals/conflicts, and is
idempotent across another interruption; both reopen rows now close fully.

```text
cargo run --locked --offline -p joshi-core -- \
  wave5-g0-process-kill-scenario \
  --state /tmp/joshi-g0-process-kill.manual \
  --scenario-id 01_before_pre_io_reservation

cargo test --locked --offline -p joshi-core --test g0_process_kill
cargo test --locked --offline -p joshi-core --test g0_process_kill \
  actual_child_kill_reaches_every_adapter_family -- --ignored --nocapture

./scripts/wave5-g0-process-kill-ledger \
  /tmp/joshi-g0-process-kill-ledger.manual
```

For every injected crash, the future adapter must prove all of these from
durable producer/store readback rather than booleans:

- the prefix is either absent or exactly once durable after reopen;
- retry uses the same reservation/idempotency identity and exact origin bytes;
- no duplicate or conflicting receipt, catalog binding, fact, publication,
  pairing consumption, memory act/episode/closure, export/import, or backup record is
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
read, memory act/episode/censored closure, export/import, status, backup, restore, and reopen.
It must bind the corresponding physical bytes or store readback—not booleans.
The adapter-free result legitimately emits an empty, correctly digested bundle.
The current Core component result carries fifteen exact roles: supervisor reservation,
origin segment, store receipt, catalog binding, catalog ACK, semantic fact,
publication prepare, publication head, memory act, memory episode, the terminal disposition of the
six-occurrence censored closure, the committed nonempty V10
export manifest,
the V10 restricted-import readback, and durable export-recovery readback, plus an artifact-bearing
backup manifest and distinct-root restore readback. Their identities may contain
the colon separators used by actual store/spool contracts. The reservation and later origin are
now one ordered handoff: the supervisor fsyncs the exact Pump batch and the store consumes that
same immutable segment before the run binding and ACK. A separate one-shot root smoke now binds a
durable pairing-consume occurrence, exact Cockpit HTTP response, old-capability restart refusal,
and byte-identical fresh-session reopen. Those baseline artifacts are not yet attached to every
before/after fault scenario, so pairing/Glass fault evidence and the final no-original-root reopen
remain absent from this component bundle and therefore cannot appear
`observed_partial`. The partial backup contains the store-reachable external source object,
but not the separate supervisor spool inventory, and does not make the original roots unavailable.
The component-local recovery matrix now includes before/after interruption points around the
censored memory closure and the post-export restricted-import readback, for thirty-two exact points
total. The import boundary reopens and rehashes the already registered manifest/Parquet CAS after
the V10 export; it does not invent a second import commit. This does not add a harness step or turn
the separate 37-scenario root matrix true.
The one-shot paired route has its own six exact component-local interruptions: before/after
exchange, before/after exact Cockpit read, and before/after pairing reopen. Each injected run is
followed by a fresh-session recovery on the same catalog and an identical response-body check.
Together with the thirty-two source/publication/memory/export points this is 38 package-local fault
checks. A separate exact adapter map covers all 36 frozen transitions: four supervisor
reservation/origin process kills, six store/catalog transitions, sixteen component transitions,
four pairing/Glass transitions, and six final backup/restore/reopen transitions. Those
package-local checks still do not emit a result and evidence bundle for each frozen scenario and
therefore are not a root qualification.

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
G0 predicate only under a new reviewed qualifying boundary, when all required
seams, crash scenarios, recovered evidence, and distinct-root backup readback
are present. The present V1 result contract unconditionally remains false.
