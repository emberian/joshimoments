use crate::{APPLICATION_ID, MINIMUM_SQLITE_VERSION_NUMBER, Result, StoreError};
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use sha2::{Digest, Sha256};

struct Migration {
    id: i64,
    name: &'static str,
    sql: &'static str,
}

const MIGRATIONS: &[Migration] = &[
    Migration {
        id: 1,
        name: "0001_evidence.sql",
        sql: include_str!("../../../schema/migrations/0001_evidence.sql"),
    },
    Migration {
        id: 2,
        name: "0002_assertions_coverage.sql",
        sql: include_str!("../../../schema/migrations/0002_assertions_coverage.sql"),
    },
    Migration {
        id: 3,
        name: "0003_scenes_commands.sql",
        sql: include_str!("../../../schema/migrations/0003_scenes_commands.sql"),
    },
    Migration {
        id: 4,
        name: "0004_operations_exports.sql",
        sql: include_str!("../../../schema/migrations/0004_operations_exports.sql"),
    },
    Migration {
        id: 5,
        name: "0005_lossless_contract.sql",
        sql: include_str!("../../../schema/migrations/0005_lossless_contract.sql"),
    },
    Migration {
        id: 6,
        name: "0006_optional_acquisition_monotonic.sql",
        sql: include_str!("../../../schema/migrations/0006_optional_acquisition_monotonic.sql"),
    },
    Migration {
        id: 7,
        name: "0007_operational_exocortex.sql",
        sql: include_str!("../../../schema/migrations/0007_operational_exocortex.sql"),
    },
    Migration {
        id: 8,
        name: "0008_semantic_artifact_durability.sql",
        sql: include_str!("../../../schema/migrations/0008_semantic_artifact_durability.sql"),
    },
    Migration {
        id: 9,
        name: "0009_wave5_living_instrument.sql",
        sql: include_str!("../../../schema/migrations/0009_wave5_living_instrument.sql"),
    },
    Migration {
        id: 10,
        name: "0010_wave5_g0_store_spine.sql",
        sql: include_str!("../../../schema/migrations/0010_wave5_g0_store_spine.sql"),
    },
    Migration {
        id: 11,
        name: "0011_wave6_program_registry.sql",
        sql: include_str!("../../../schema/migrations/0011_wave6_program_registry.sql"),
    },
    Migration {
        id: 12,
        name: "0012_wave6_artifact_schemas.sql",
        sql: include_str!("../../../schema/migrations/0012_wave6_artifact_schemas.sql"),
    },
    Migration {
        id: 13,
        name: "0013_wave6_fixture_artifacts.sql",
        sql: include_str!("../../../schema/migrations/0013_wave6_fixture_artifacts.sql"),
    },
    Migration {
        id: 14,
        name: "0014_wave6_artifact_dag.sql",
        sql: include_str!("../../../schema/migrations/0014_wave6_artifact_dag.sql"),
    },
    Migration {
        id: 15,
        name: "0015_wave6_fixture_decisions.sql",
        sql: include_str!("../../../schema/migrations/0015_wave6_fixture_decisions.sql"),
    },
    Migration {
        id: 16,
        name: "0016_wave6_campaign_bundle.sql",
        sql: include_str!("../../../schema/migrations/0016_wave6_campaign_bundle.sql"),
    },
    Migration {
        id: 17,
        name: "0017_wave6_research_proposal.sql",
        sql: include_str!("../../../schema/migrations/0017_wave6_research_proposal.sql"),
    },
    Migration {
        id: 18,
        name: "0018_wave6_research_disposition.sql",
        sql: include_str!("../../../schema/migrations/0018_wave6_research_disposition.sql"),
    },
    Migration {
        id: 19,
        name: "0019_wave6_market_atlas_fixture.sql",
        sql: include_str!("../../../schema/migrations/0019_wave6_market_atlas_fixture.sql"),
    },
    Migration {
        id: 20,
        name: "0020_wave6_store_input_census.sql",
        sql: include_str!("../../../schema/migrations/0020_wave6_store_input_census.sql"),
    },
    Migration {
        id: 21,
        name: "0021_cockpit_v2_browser_presentation.sql",
        sql: include_str!("../../../schema/migrations/0021_cockpit_v2_browser_presentation.sql"),
    },
    Migration {
        id: 22,
        name: "0022_wave6_operator_evidence_input.sql",
        sql: include_str!("../../../schema/migrations/0022_wave6_operator_evidence_input.sql"),
    },
    Migration {
        id: 23,
        name: "0023_wave5_c1_activation.sql",
        sql: include_str!("../../../schema/migrations/0023_wave5_c1_activation.sql"),
    },
    Migration {
        id: 24,
        name: "0024_retire_wave5_c1_activation.sql",
        sql: include_str!("../../../schema/migrations/0024_retire_wave5_c1_activation.sql"),
    },
];

/// Linked runtime and active durability settings.
#[derive(Clone, Debug, Eq, PartialEq)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "each flag is one independent SQLite pragma read back off the live connection; the \
              lint's suggested remedies (a state machine, or two-variant enums) would obscure \
              that one-to-one correspondence rather than clarify it"
)]
pub struct RuntimeStatus {
    /// Linked `SQLite` version.
    pub sqlite_version: String,
    /// Numeric linked `SQLite` version.
    pub sqlite_version_number: i32,
    /// Active journal mode.
    pub journal_mode: String,
    /// Active synchronous level.
    pub synchronous: i64,
    /// Whether the connection asked its VFS for the platform's strongest commit-sync primitive.
    ///
    /// This records the requested `fullfsync` pragma, not a proof that any particular syscall ran.
    pub full_fsync: bool,
    /// Whether that same request also covers WAL checkpoint syncs (`checkpoint_fullfsync`).
    pub checkpoint_full_fsync: bool,
    /// Whether triggers fire for rows deleted by `INSERT OR REPLACE` (`recursive_triggers`).
    pub recursive_triggers: bool,
    /// Whether foreign keys are active.
    pub foreign_keys: bool,
    /// Catalog application identity.
    pub application_id: i32,
    /// Highest migration encoded in `user_version`.
    pub user_version: i64,
}

/// Result of a forward-only migration pass.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MigrationReport {
    /// Migration IDs newly applied in this invocation.
    pub applied: Vec<u64>,
    /// Highest migration after the pass.
    pub current: u64,
    /// Verified runtime settings.
    pub runtime: RuntimeStatus,
}

pub(crate) fn assert_linked_runtime() -> Result<()> {
    let actual_number = rusqlite::version_number();
    if actual_number < MINIMUM_SQLITE_VERSION_NUMBER {
        return Err(StoreError::UnsafeSqliteRuntime {
            actual: rusqlite::version().to_owned(),
        });
    }
    Ok(())
}

/// Apply the single-writer durability and trigger-visibility contract, then read it back.
///
/// `synchronous=FULL` makes `SQLite` sync the WAL before a commit reports success, but the unix
/// VFS issues a plain `fsync(2)` for that sync unless `fullfsync` is set. On Darwin `fsync(2)`
/// returns once the data has reached the drive, not once the drive has flushed its own write
/// cache. Without `fullfsync` a power loss between a claim commit and the next checkpoint can
/// therefore drop the claim's WAL frame while the earlier activation frame is already on media,
/// which would present an already-consumed one-shot row as available again. `fullfsync` asks the VFS
/// for `F_FULLFSYNC` instead, which is the same primitive `std::fs::File::sync_all` already uses
/// for the supervisor journal on Apple targets, so the two layers stop disagreeing about what a
/// successful sync means. `checkpoint_fullfsync` extends the request to the checkpoint syncs that
/// move those frames into the main database file and then reset the WAL.
///
/// Stated honestly: these pragmas are a request to the VFS, not a durability proof. On platforms
/// with no `F_FULLFSYNC` (Linux among them) `SQLite` still issues `fsync(2)`; even on Darwin the
/// unix VFS falls back to `fsync(2)` whenever the `F_FULLFSYNC` `fcntl` fails, which it does on
/// file systems that do not implement it; and no pragma can compel a drive that reports a flush it
/// did not perform. What is verified here is only that the connection actually carries the
/// requested settings: each one is queried back below, so a silently ignored or misspelled pragma
/// fails the open instead of passing as durability.
///
/// `recursive_triggers` is enabled so the append-only `BEFORE DELETE` triggers also fire for rows
/// removed by `INSERT OR REPLACE`; with the pragma off, `SQLite` performs those deletions without
/// running delete triggers. No trigger body in `schema/migrations` issues `INSERT`, `UPDATE`,
/// `DELETE`, or `REPLACE` — every one is a `SELECT ... RAISE(ABORT, ...)` guard — so enabling the
/// pragma cannot introduce trigger recursion in this catalog.
pub(crate) fn configure_writer(connection: &Connection) -> Result<()> {
    connection.pragma_update(None, "fullfsync", "ON")?;
    connection.pragma_update(None, "checkpoint_fullfsync", "ON")?;
    connection.pragma_update(None, "recursive_triggers", "ON")?;
    connection.pragma_update(None, "foreign_keys", "ON")?;
    connection.pragma_update(None, "journal_mode", "WAL")?;
    connection.pragma_update(None, "synchronous", "FULL")?;
    connection.pragma_update(None, "wal_autocheckpoint", 1000_i64)?;
    connection.pragma_update(None, "trusted_schema", "OFF")?;
    connection.pragma_update(None, "temp_store", "MEMORY")?;
    connection.pragma_update(None, "busy_timeout", 5000_i64)?;
    let application_id: i32 =
        connection.pragma_query_value(None, "application_id", |row| row.get(0))?;
    if application_id == 0 {
        connection.pragma_update(None, "application_id", APPLICATION_ID)?;
    } else if application_id != APPLICATION_ID {
        return Err(StoreError::ApplicationId {
            actual: application_id,
        });
    }
    verify_runtime(connection, true).map(|_| ())
}

pub(crate) fn configure_reader(connection: &Connection) -> Result<()> {
    connection.pragma_update(None, "foreign_keys", "ON")?;
    connection.pragma_update(None, "trusted_schema", "OFF")?;
    connection.pragma_update(None, "query_only", "ON")?;
    let application_id: i32 =
        connection.pragma_query_value(None, "application_id", |row| row.get(0))?;
    if application_id != APPLICATION_ID {
        return Err(StoreError::ApplicationId {
            actual: application_id,
        });
    }
    verify_runtime(connection, false).map(|_| ())
}

pub(crate) fn migrate(connection: &mut Connection, applied_at_us: i64) -> Result<MigrationReport> {
    let target = MIGRATIONS.last().map_or(0, |migration| migration.id);
    migrate_through(connection, applied_at_us, target)
}

pub(crate) fn migrate_through(
    connection: &mut Connection,
    applied_at_us: i64,
    target: i64,
) -> Result<MigrationReport> {
    let current: i64 = connection.pragma_query_value(None, "user_version", |row| row.get(0))?;
    if current > target || !MIGRATIONS.iter().any(|migration| migration.id == target) {
        return Err(StoreError::MigrationConflict {
            migration: target.to_string(),
            detail: format!("cannot move forward from migration {current} to target {target}"),
        });
    }
    let mut applied = Vec::new();
    for migration in MIGRATIONS.iter().filter(|migration| migration.id <= target) {
        let digest = format!("{:x}", Sha256::digest(migration.sql.as_bytes()));
        let has_ledger: bool = connection
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_schema WHERE type='table' AND name='schema_migration')",
                [],
                |row| row.get(0),
            )?;
        if has_ledger {
            let existing: Option<(String, String)> = connection
                .query_row(
                    "SELECT name, source_sha256 FROM schema_migration WHERE migration_id=?1",
                    [migration.id],
                    |row| Ok((row.get(0)?, row.get(1)?)),
                )
                .optional()?;
            if let Some((name, source_sha256)) = existing {
                if name != migration.name || source_sha256 != digest {
                    return Err(StoreError::MigrationConflict {
                        migration: migration.id.to_string(),
                        detail: format!(
                            "catalog has {name}/{source_sha256}, source has {}/{digest}",
                            migration.name
                        ),
                    });
                }
                continue;
            }
        }
        let rebuilds_acquisition = migration.id == 6;
        if rebuilds_acquisition {
            connection.pragma_update(None, "foreign_keys", "OFF")?;
            connection.pragma_update(None, "legacy_alter_table", "ON")?;
        }
        let result = (|| -> Result<()> {
            let transaction =
                connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
            transaction.execute_batch(migration.sql)?;
            transaction.execute(
                "INSERT INTO schema_migration
                 (migration_id,name,source_sha256,applied_at_us,sqlite_version)
                 VALUES (?1,?2,?3,?4,?5)",
                params![
                    migration.id,
                    migration.name,
                    digest,
                    applied_at_us,
                    rusqlite::version()
                ],
            )?;
            transaction.pragma_update(None, "user_version", migration.id)?;
            transaction.commit()?;
            Ok(())
        })();
        if rebuilds_acquisition {
            connection.pragma_update(None, "legacy_alter_table", "OFF")?;
            connection.pragma_update(None, "foreign_keys", "ON")?;
            if result.is_ok() {
                let defects: i64 = connection.query_row(
                    "SELECT COUNT(*) FROM pragma_foreign_key_check",
                    [],
                    |row| row.get(0),
                )?;
                if defects != 0 {
                    return Err(StoreError::MigrationConflict {
                        migration: migration.id.to_string(),
                        detail: format!("foreign-key defects after table rebuild: {defects}"),
                    });
                }
            }
        }
        result?;
        applied.push(u64::try_from(migration.id).unwrap_or_default());
    }
    let runtime = verify_runtime(connection, true)?;
    Ok(MigrationReport {
        current: runtime.user_version.try_into().unwrap_or_default(),
        applied,
        runtime,
    })
}

pub(crate) fn verify_runtime(
    connection: &Connection,
    require_writer: bool,
) -> Result<RuntimeStatus> {
    assert_linked_runtime()?;
    let journal_mode: String =
        connection.pragma_query_value(None, "journal_mode", |row| row.get(0))?;
    if !journal_mode.eq_ignore_ascii_case("wal") {
        return Err(StoreError::RuntimeSetting {
            setting: "journal_mode",
            actual: journal_mode,
            expected: "wal",
        });
    }
    let synchronous: i64 = connection.pragma_query_value(None, "synchronous", |row| row.get(0))?;
    if require_writer && synchronous != 2 {
        return Err(StoreError::RuntimeSetting {
            setting: "synchronous",
            actual: synchronous.to_string(),
            expected: "2 (FULL)",
        });
    }
    let full_fsync = read_flag(connection, "fullfsync")?;
    let checkpoint_full_fsync = read_flag(connection, "checkpoint_fullfsync")?;
    let recursive_triggers = read_flag(connection, "recursive_triggers")?;
    if require_writer {
        require_flag("fullfsync", full_fsync)?;
        require_flag("checkpoint_fullfsync", checkpoint_full_fsync)?;
        require_flag("recursive_triggers", recursive_triggers)?;
    }
    let foreign_keys: i64 =
        connection.pragma_query_value(None, "foreign_keys", |row| row.get(0))?;
    if foreign_keys != 1 {
        return Err(StoreError::RuntimeSetting {
            setting: "foreign_keys",
            actual: foreign_keys.to_string(),
            expected: "1",
        });
    }
    let application_id: i32 =
        connection.pragma_query_value(None, "application_id", |row| row.get(0))?;
    if application_id != APPLICATION_ID {
        return Err(StoreError::ApplicationId {
            actual: application_id,
        });
    }
    let user_version: i64 =
        connection.pragma_query_value(None, "user_version", |row| row.get(0))?;
    Ok(RuntimeStatus {
        sqlite_version: rusqlite::version().to_owned(),
        sqlite_version_number: rusqlite::version_number(),
        journal_mode,
        synchronous,
        full_fsync,
        checkpoint_full_fsync,
        recursive_triggers,
        foreign_keys: true,
        application_id,
        user_version,
    })
}

/// Read one boolean pragma back from the live connection.
///
/// The readback is what makes the setting checkable: `SQLite` accepts an unknown pragma name
/// silently, so only the queried value distinguishes a configured connection from a typo.
fn read_flag(connection: &Connection, name: &'static str) -> Result<bool> {
    let value: i64 = connection.pragma_query_value(None, name, |row| row.get(0))?;
    Ok(value == 1)
}

fn require_flag(setting: &'static str, actual: bool) -> Result<()> {
    if actual {
        Ok(())
    } else {
        Err(StoreError::RuntimeSetting {
            setting,
            actual: i64::from(actual).to_string(),
            expected: "1",
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wave5_baseline_target_is_forward_only_and_resumable() {
        let root = tempfile::tempdir().expect("temporary migration root");
        let path = root.path().join("catalog.sqlite");
        let mut connection = Connection::open(&path).expect("open catalog");
        configure_writer(&connection).expect("configure writer");

        let baseline =
            migrate_through(&mut connection, 1_786_000_000_000_000, 9).expect("apply V9 baseline");
        assert_eq!(baseline.current, 9);
        assert_eq!(baseline.applied, (1..=9).collect::<Vec<_>>());

        let retry = migrate_through(&mut connection, 1_786_000_000_000_001, 9)
            .expect("idempotent V9 retry");
        assert_eq!(retry.current, 9);
        assert!(retry.applied.is_empty());

        let g0 = migrate_through(&mut connection, 1_786_000_000_000_002, 10)
            .expect("advance to frozen G0 V10");
        assert_eq!(g0.current, 10);
        assert_eq!(g0.applied, vec![10]);

        let current = migrate(&mut connection, 1_786_000_000_000_003).expect("advance to V24");
        assert_eq!(current.current, 24);
        assert_eq!(
            current.applied,
            vec![11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]
        );

        let error = migrate_through(&mut connection, 1_786_000_000_000_004, 10)
            .expect_err("G0 migration cannot downgrade V24");
        assert!(matches!(error, StoreError::MigrationConflict { .. }));
    }

    /// A configured writer must actually carry the durability and trigger-visibility pragmas.
    ///
    /// Every value here is read back off the live connection rather than recomputed from the
    /// constants written in `configure_writer`, so a pragma that `SQLite` ignored, that a later
    /// statement reset, or whose name was misspelled fails this test.
    #[test]
    fn configured_writer_carries_full_fsync_and_recursive_triggers() {
        let root = tempfile::tempdir().expect("temporary durability root");
        let path = root.path().join("catalog.sqlite");
        let connection = Connection::open(&path).expect("open catalog");
        configure_writer(&connection).expect("configure writer");

        let full_fsync: i64 = connection
            .pragma_query_value(None, "fullfsync", |row| row.get(0))
            .expect("query fullfsync back");
        let checkpoint_full_fsync: i64 = connection
            .pragma_query_value(None, "checkpoint_fullfsync", |row| row.get(0))
            .expect("query checkpoint_fullfsync back");
        let recursive_triggers: i64 = connection
            .pragma_query_value(None, "recursive_triggers", |row| row.get(0))
            .expect("query recursive_triggers back");
        assert_eq!(
            full_fsync, 1,
            "writer must request F_FULLFSYNC commit syncs"
        );
        assert_eq!(
            checkpoint_full_fsync, 1,
            "writer must request F_FULLFSYNC checkpoint syncs"
        );
        assert_eq!(
            recursive_triggers, 1,
            "append-only delete triggers must fire for REPLACE-deleted rows"
        );

        let runtime = verify_runtime(&connection, true).expect("verified writer runtime");
        assert!(runtime.full_fsync);
        assert!(runtime.checkpoint_full_fsync);
        assert!(runtime.recursive_triggers);

        // Turning any one of them off must fail the writer contract rather than pass silently.
        for setting in ["fullfsync", "checkpoint_fullfsync", "recursive_triggers"] {
            connection
                .pragma_update(None, setting, "OFF")
                .expect("relax pragma for the negative case");
            let error = verify_runtime(&connection, true)
                .expect_err("a relaxed durability pragma must fail writer verification");
            assert!(
                matches!(error, StoreError::RuntimeSetting { setting: observed, .. } if observed == setting),
                "expected a RuntimeSetting refusal naming {setting}, got {error:?}"
            );
            connection
                .pragma_update(None, setting, "ON")
                .expect("restore pragma");
        }
        verify_runtime(&connection, true).expect("restored writer runtime");
    }

    /// `recursive_triggers` is what makes a `BEFORE DELETE` guard cover `INSERT OR REPLACE`.
    ///
    /// This exercises the append-only trigger shape this schema uses on a throwaway table, in
    /// both pragma states, so the pragma choice rests on observed `SQLite` behavior rather than on
    /// a reading of the documentation. It is a statement about that trigger shape, which several
    /// live tables carry, not about any one table.
    #[test]
    fn replace_reaches_append_only_delete_triggers_only_with_recursive_triggers() {
        let connection = Connection::open_in_memory().expect("scratch catalog");
        connection
            .execute_batch(
                "CREATE TABLE append_only (id TEXT PRIMARY KEY, payload TEXT NOT NULL) STRICT;
                 CREATE TRIGGER no_delete_append_only
                 BEFORE DELETE ON append_only
                 BEGIN SELECT RAISE(ABORT, 'append_only is append-only'); END;
                 INSERT INTO append_only VALUES ('a','first');",
            )
            .expect("seed scratch append-only table");

        connection
            .pragma_update(None, "recursive_triggers", "OFF")
            .expect("disable recursive triggers");
        connection
            .execute(
                "INSERT OR REPLACE INTO append_only VALUES ('a','overwritten')",
                [],
            )
            .expect("without recursive_triggers, REPLACE deletes past the delete trigger");
        let payload: String = connection
            .query_row("SELECT payload FROM append_only WHERE id='a'", [], |row| {
                row.get(0)
            })
            .expect("read scratch row");
        assert_eq!(
            payload, "overwritten",
            "this is the gap: the append-only guard did not fire"
        );

        connection
            .pragma_update(None, "recursive_triggers", "ON")
            .expect("enable recursive triggers");
        let refused = connection.execute(
            "INSERT OR REPLACE INTO append_only VALUES ('a','again')",
            [],
        );
        assert!(
            refused.is_err(),
            "with recursive_triggers the append-only delete guard aborts REPLACE"
        );
        let payload: String = connection
            .query_row("SELECT payload FROM append_only WHERE id='a'", [], |row| {
                row.get(0)
            })
            .expect("read scratch row");
        assert_eq!(
            payload, "overwritten",
            "the refused REPLACE changed nothing"
        );
    }

    /// No trigger in the compiled migration ledger issues DML, so `recursive_triggers` cannot
    /// make any trigger in this catalog fire another trigger.
    ///
    /// This is a textual check over the exact SQL this binary compiles in, not a proof about
    /// the trigger semantics of `SQLite`. It states the premise the `recursive_triggers` decision
    /// rests on and fails if a later migration breaks it. The scanned region runs from a trigger's
    /// `BEGIN` to the start of the next top-level `CREATE`, which deliberately over-approximates
    /// the body rather than stopping at the first `END;` — trigger bodies here contain `CASE ...
    /// END` and a first-`END` scan would read only part of them.
    #[test]
    fn no_compiled_trigger_body_issues_dml() {
        let mut triggers = 0_usize;
        for migration in MIGRATIONS {
            let lowered = migration.sql.to_ascii_lowercase();
            let mut cursor = 0_usize;
            while let Some(found) = lowered[cursor..].find("create trigger") {
                let start = cursor + found;
                let end = lowered[start + 1..]
                    .find("\ncreate ")
                    .map_or(lowered.len(), |offset| start + 1 + offset);
                let region = &lowered[start..end];
                let body = region
                    .find("begin")
                    .map_or(region, |offset| &region[offset..]);
                for statement in ["insert", "update", "delete", "replace"] {
                    assert!(
                        !body.contains(statement),
                        "a trigger body in {} mentions {statement}; recursive_triggers could let \
                         it fire another trigger, so re-check it before trusting that pragma",
                        migration.name
                    );
                }
                triggers += 1;
                cursor = end;
            }
        }
        assert!(
            triggers >= 271,
            "scanned only {triggers} triggers; the ledger had 271 when this scan was written, so \
             the scanner stopped matching rather than the triggers disappearing"
        );
    }
}
