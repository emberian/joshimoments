# Joshi SQLite schema

This directory is the fixed home of the operational schema. `crates/joshi-store` must apply these
files in lexical order; migrations are forward-only and must never be edited after they have been
applied to a durable database.

The schema deliberately separates:

- an acquisition occurrence (`acquisition`, `observation`);
- exact content identity (`blob`), physical protection-domain copies (`blob_object`), and
  reference-local media/retention (`observation_blob_contract`);
- an upstream identity (`source_event`);
- a versioned interpretation (`assertion`);
- source completeness (`coverage_*`, `source_cursor`);
- what the operator was shown and did (`scene`, `command`); and
- rebuildable work and exports (`outbox_item`, `projection_checkpoint`, `export_snapshot`,
  `export_manifest`).

Equal bytes may be observed more than once. One observation may contain several source events. Two
source events may have equal economic values. None of those equalities is a license to collapse the
other identities.

## Applying migrations

The production runner must:

1. select a SQLite runtime at or above 3.51.3 (or an explicitly reviewed fixed backport);
2. verify `application_id`, WAL, `synchronous=FULL`, foreign keys, and strict-table behavior;
3. take a verified backup before applying a migration to a non-fixture database;
4. acquire the only writer, compare the complete ordered migration prefix and SHA-256 values with
   `schema_migration`, and refuse a changed, missing, reordered, or unknown file;
5. apply one new file and its ledger row in the same `BEGIN IMMEDIATE` transaction; and
6. advance `user_version` only in that transaction.

Migration SQL contains no `BEGIN`, `COMMIT`, downgrade, or runtime PRAGMA. The runner owns the
transaction and verifies runtime settings instead of assuming they persisted. V6 is the one
reviewed table rebuild: the runner disables FK rename rewriting around its atomic replacement,
restores the normal PRAGMAs, and refuses completion unless `foreign_key_check` is clean.

## Local verification

Run:

```sh
schema/validate.sh
```

The script prefers the fixed Homebrew SQLite runtime on this host, refuses versions below 3.51.3,
builds a fresh WAL/FULL database, applies and records every migration checksum, separately proves
the V4-to-V8 upgrade edge, loads the adversarial
tape fixture, verifies external blob hashes, and executes both general and fixture-specific SQL
invariants. Set `JOSHI_SQLITE_BIN` to validate another safe runtime or `JOSHI_KEEP_VALIDATION_DB=1`
to retain the temporary database.

The validation proves schema and fixture behavior on a clean database. It is not the required
process-kill, APFS durability, checkpoint, backup/restore, or Parquet interoperability campaign.
