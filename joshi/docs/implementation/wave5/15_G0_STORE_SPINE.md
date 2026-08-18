# Wave 5 G0 sole-store spine

Status: implemented as the forward-only `joshi.sqlite.v10` migration. This is a private storage
authority boundary. It adds no route, provider, wallet, signer, transaction, trading, liquidity,
or execution authority.

## Authority rules

- Receipts are created only after a durable commit and exact readback. Receipt fields are not
  deserializable and their constructors remain private to `joshi-store`.
- Callers supply exact canonical source/publication/memory/pairing documents. They never supply a
  durability receipt, commit sequence, queue generation, catalog cutoff, semantic count, or a
  store-qualified `StoreResolved` value.
- Every load reparses retained bytes, recomputes their SHA-256 and byte length, and rejoins the
  persisted predecessor/support rows. Reopening the process does not trust an earlier Rust value.
- All new semantic rows retain `read_only_no_execution`, except pairing occurrences, whose exact
  canonical authority is `read_only_pairing_exchange`. Pairing persists no code, capability,
  secret, secret hash, or other secret derivative.
- Cockpit and scientific-memory admission remains G0 fixture authority. It is not production
  semantic qualification. Scientific-memory receipts remain private and do not set a public
  kernel-wide verified flag.
- The offline G0 source fixture retains its exact hot/cold selection as a separate decoded
  `offline_fixture_selection` observation. Pump facts remain derived only from the exact
  `provider_body` observation. Ordinary direct admission does not accept or synthesize this
  selection, and the selection contract is permanently labeled `offline_fixture_only`.

## Forward-only V9 baseline bootstrap

`SqliteStore::migrate_wave5_baseline_v9` applies the compiled ledger only through migration 9 so
the same new catalog can commit one real prior Snapshot V2 export and same-run binding before G0
relations exist. It is idempotent only while the catalog remains at V9. The ordinary `migrate` call
then advances the same file to V10, where the exact restricted manifest and Parquet CAS import are
immediately committed before any V10 G0 export; any attempt to target V9 after that point refuses as
a migration conflict. This is not a downgrade, alternate schema authority, or permission to
operate indefinitely on an old catalog. Its sole purpose is to remove the first-V10 export/import
history cycle without inserting synthetic rows.

## Frozen V10 relations

Migration: `schema/migrations/0010_wave5_g0_store_spine.sql`.

The following table and column names are frozen for G0 readers:

- `wave5_source_occurrence_v1`: `source_occurrence_id`, `run_registration_id`,
  `catalog_admission_id`, `source_id`, `receipt_sha256`, `descriptor_contract`,
  `descriptor_sha256`, `descriptor_bytes`, `descriptor_byte_length`,
  `surface_profile_sha256`, `fact_count`, `eligible_subject_count`, `membership_count`,
  `coverage_count`, `gap_count`, `rendered_subject_count`, `omission_count`,
  `hot_subject_count`, `cold_control_subject_count`, `known_through_commit_seq`,
  `maximum_input_available_wall_us`, `protection_class`, `authority`, `created_commit_seq`.
- `cockpit_v2_preparation_v1`: `preparation_id`, `source_occurrence_id`,
  `resolved_input_sha256`, `resolved_input_bytes`, `resolved_input_byte_length`,
  `semantic_sha256`, `semantic_bytes`, `semantic_byte_length`, `container_sha256`,
  `container_bytes`, `container_byte_length`, `checkpoint_sha256`, `checkpoint_bytes`,
  `checkpoint_byte_length`, `through_commit_seq`, `knowledge_wall_us`, `authority`,
  `created_commit_seq`.
- `cockpit_v2_publication_v1`: `publication_id`, `preparation_id`, `source_occurrence_id`,
  `publication_contract`, `publication_sha256`, `publication_bytes_sha256`,
  `publication_bytes`, `publication_byte_length`, `semantic_sha256`, `container_sha256`,
  `checkpoint_sha256`, `through_commit_seq`, `supersedes_publication_id`, `authority`,
  `created_commit_seq`.
- `cockpit_v2_head_v1`: `publication_id`, `source_occurrence_id`, `head_sha256`, `head_bytes`,
  `head_byte_length`, `supersedes_head_publication_id`, `authority`, `created_commit_seq`.
- `scientific_memory_occurrence_v1`: exact act, episode, replay, session-close, knowledge-closure,
  outcome-at-horizon, and interview-disposition bytes and SHA-256; session and headed-scene
  identities; opening/closing act identities; logical tick bounds; store-allocated
  `queue_generation`, fixture qualification, authority, and `created_commit_seq`.
- `wave5_g0_pairing_epoch_v1`: origin/epoch, exact wall sample, persisted rate policy, last wall
  observation, carried attempt/issue window IDs, used counts and wall deadlines, invalidation
  counts, exact epoch occurrence ID, and `created_commit_seq`.
- `wave5_g0_pairing_occurrence_v1`: exact canonical occurrence/DAG fields plus the exact
  `rate_window_id` and deadline and the store-derived `rate_window_started_wall_us`. Budget counts
  are scoped to this identity across restarts; expiry starts a new identity.
- `wave5_g0_restricted_manifest_cas_v1`: `import_id`, external manifest `blob_id`,
  `storage_domain`, `manifest_sha256`, `manifest_byte_length`, `created_commit_seq`.
- `wave5_g0_backup_reservation_v1`: `backup_id`, `run_registration_id`,
  `reservation_sha256`, `reservation_bytes`, `reservation_byte_length`,
  `catalog_destination`, `artifact_destination_root`, `authority`, `created_commit_seq`.
- `wave5_g0_backup_snapshot_v1`: `backup_id`, `snapshot_sha256`, `snapshot_bytes`,
  `snapshot_byte_length`, `staging_catalog_path`, `catalog_sha256`,
  `source_max_commit_seq`, `authority`, `created_commit_seq`.
- `wave5_g0_backup_v1`: exact catalog digest, canonical manifest bytes/digest, nonempty reachable
  artifact inventory bytes/digest/count, run identity, source cutoff, authority, and commit.
- `wave5_g0_backup_restore_reservation_v1`: `restore_id`, `backup_id`,
  `reservation_sha256`, `reservation_bytes`, `reservation_byte_length`,
  `catalog_destination`, `artifact_destination_root`, `authority`, `created_commit_seq`.
- `wave5_g0_backup_restore_v1`: exact backup identity, restored catalog and artifact-inventory
  digests, canonical artifact-bearing readback bytes/digest, restored cutoff, authority, commit.

Every V10 table is append-only. Cockpit head supersession has one genesis and one successor per
head. Pairing has one terminal child per issue/session lineage, with restart invalidation as the
only cross-epoch edge.

## Store APIs

Source and publication:

- `commit_wave5_c0_source_occurrence_v1` accepts an exact retained, accepted public C0 receipt. It
  resolves observations, content bytes, semantic recognition, subject membership, scoped
  coverage, gaps, omissions, cutoffs, and counts from the catalog.
- `prepare_cockpit_v2_from_store_v1`, `commit_cockpit_v2_publication_v1`, and
  `append_cockpit_v2_head_v1` preserve separate crash-visible prepare/body/head stages.
- Matching `load_*` methods reparse and recompute the entire retained closure.
- `joshi-core wave5-g0-source-publication` exercises that exact fixture-only join through the
  sole store, checks a two-subject one-hot/one-cold partition, commits prepare/body/head in strict
  order, reopens every exact artifact read-only, and proves an identical second invocation is
  idempotent. A component-local matrix additionally interrupts immediately before and after
  semantic fact, prepare, body, head, memory act, partial episode, and six-event censored closure,
  then proves exact convergence after reopen. The act is bound to the exact headed scene with a
  typed `not_mounted` presentation gap; the episode is partial with only
  unknown/unresolved/no-trade effects. The closure contains hidden replay, incomplete close,
  explicitly gapped partial knowledge, missing outcome, retrospective replay, and interview. Its
  report keeps `fullOfflineFaultWalk`, product and live qualification false because actual
  presentation, qualified knowledge/outcome, other G0 seams and the 18-step harness remain outside
  this component.

Scientific memory:

- `commit_scientific_memory_occurrence_v1` holds an immediate writer transaction while rebuilding
  the durable `MemoryKernel` prefix and validating the next occurrence. Queue generation is
  store-allocated. Only partial, unresolved G0 episodes and explicitly nonclosed/censored closure
  states are admitted; complete session, closed knowledge, and available outcome refuse.
- `load_scientific_memory_occurrence_v1` rebuilds the prefix and revalidates the exact headed
  Cockpit V2 scene.

Pairing:

- `begin_pairing_epoch_v1` acquires the immediate transaction before reading the prior epoch,
  rate windows, or live issues/sessions. It uses `joshi-pairing` canonical ID helpers and creates
  exact new-epoch restart invalidations in deterministic predecessor order.
- `append_pairing_occurrences_v1` reparses canonical bytes, enforces the active epoch, nonregressing
  wall/predecessor clocks, exact fixed-wall rate-window identity/deadline/count, and strict
  idempotency.
- `load_pairing_occurrence_v1` returns exact bytes/digest/commit only. Pairing routes obtain an
  opaque store clock context through `begin_wave5_commit`.

Export/import/status and backup:

- `commit_wave5_baseline_export_snapshot_v2` accepts only an independently validated legacy
  fourteen-table Snapshot V2 while the same catalog is exactly V9. It reuses the production store
  commit/readback path and refuses once migration 10 has applied.
- `load_wave5_g0_status_occurrence_v1`, `load_wave5_g0_export_occurrence_v1`, and
  `load_wave5_g0_import_occurrence_v1` expose neutral identities only after V9 canonical/CAS
  readback. `load_wave5_g0_occurrence_ports_v1` requires explicit sorted IDs and refuses a
  disconnected run/source/publication/head/memory/status/export/import selection.
- `commit_wave5_g0_operational_export_v2` is the V10 authority path. It privately resolves the
  named durable G0 backup, fixes the catalog path/id/schema/range from that exact readback,
  resolves the registered import manifest and every part from external CAS, invokes the pure
  exporter with a neutral readback DTO, then reopens both backup and import closures before
  committing the exact validated snapshot. Caller catalog paths, cutoffs, and publication time
  are ignored; the last is taken from the opaque store commit context.
  Direct snapshot commit is crate-private. V8/V9 retain the exact legacy 14-table set; V10 requires
  the exact 24-table set (14 base plus ten occurrence relations), with no extras or omissions.
  The Core G0 component exercises this path from a store-created input backup and registered CAS
  import, then reopens the committed snapshot and captures its manifest/tables in a later nonempty
  backup. Export time is the immutable backup-commit time, so exact retry cannot mutate the
  content-derived snapshot under a fixed operation identity.
  Core then commits a canonical same-run export binding and uses only that binding commit/digest as
  the finite `RecoveryVerified/Ready` evidence. The production receipt alone cannot mint recovery.
- `commit_wave5_g0_backup_v1` creates an online catalog backup, independently rederives all
  reachable external objects, and reserves exact initially absent destinations before file I/O.
  A private stage is regenerated until its exact digest/cutoff has its own durable settlement;
  only then are file-and-directory-fsynced atomic copies made to the reserved roots. Retried
  partial copies must match that settlement. The final occurrence carries a nonempty exact
  inventory, and load repeats catalog reachability derivation.
- `commit_wave5_g0_backup_restore_v1` copies artifacts only from the backup root into new blob and
  export roots after its own durable destination reservation, restores the catalog with the same
  atomic/fsync discipline, opens a read-only `SqliteStore` against those roots, and runs full
  verification before commit. Restore load repeats full artifact-bearing verification.

## Export occurrence set

The V10 export relation names are frozen as:

`scenes`, `territories`, `candidates`, `candidate_social_assertions`, `decisions`,
`choice_members`, `episodes`, `chart_samples`, `operator_gestures`, `operator_interviews`,
`outcomes`, `provenance_assertions`, `coverage_windows`, `coverage_gaps`,
`source_fact_occurrences`, `publication_occurrences`, `scene_occurrences`, `act_occurrences`,
`episode_occurrences`, `run_occurrences`, `spool_catalog_occurrences`, `status_occurrences`,
`export_occurrences`, and `import_occurrences`.

Occurrence descriptors are neutral, sorted, and carry their exact available commit. They cannot
mint store authority and cannot widen a publication, memory, pairing, import, or backup boundary.
