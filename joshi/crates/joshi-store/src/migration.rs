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
];

/// Linked runtime and active durability settings.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeStatus {
    /// Linked `SQLite` version.
    pub sqlite_version: String,
    /// Numeric linked `SQLite` version.
    pub sqlite_version_number: i32,
    /// Active journal mode.
    pub journal_mode: String,
    /// Active synchronous level.
    pub synchronous: i64,
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

pub(crate) fn configure_writer(connection: &Connection) -> Result<()> {
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
        foreign_keys: true,
        application_id,
        user_version,
    })
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

        let current = migrate(&mut connection, 1_786_000_000_000_003).expect("advance to V16");
        assert_eq!(current.current, 16);
        assert_eq!(current.applied, vec![11, 12, 13, 14, 15, 16]);

        let error = migrate_through(&mut connection, 1_786_000_000_000_004, 10)
            .expect_err("G0 migration cannot downgrade V16");
        assert!(matches!(error, StoreError::MigrationConflict { .. }));
    }
}
