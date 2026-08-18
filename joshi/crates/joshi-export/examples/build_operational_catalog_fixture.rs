//! Deterministically build the synthetic migrated V8 catalog used by the operational exporter.

use rusqlite::{Connection, params};
use sha2::{Digest, Sha256};
use std::{env, fs, path::PathBuf};

const MIGRATIONS: [(i64, &str, &str); 8] = [
    (
        1,
        "0001_evidence.sql",
        include_str!("../../../schema/migrations/0001_evidence.sql"),
    ),
    (
        2,
        "0002_assertions_coverage.sql",
        include_str!("../../../schema/migrations/0002_assertions_coverage.sql"),
    ),
    (
        3,
        "0003_scenes_commands.sql",
        include_str!("../../../schema/migrations/0003_scenes_commands.sql"),
    ),
    (
        4,
        "0004_operations_exports.sql",
        include_str!("../../../schema/migrations/0004_operations_exports.sql"),
    ),
    (
        5,
        "0005_lossless_contract.sql",
        include_str!("../../../schema/migrations/0005_lossless_contract.sql"),
    ),
    (
        6,
        "0006_optional_acquisition_monotonic.sql",
        include_str!("../../../schema/migrations/0006_optional_acquisition_monotonic.sql"),
    ),
    (
        7,
        "0007_operational_exocortex.sql",
        include_str!("../../../schema/migrations/0007_operational_exocortex.sql"),
    ),
    (
        8,
        "0008_semantic_artifact_durability.sql",
        include_str!("../../../schema/migrations/0008_semantic_artifact_durability.sql"),
    ),
];

#[allow(clippy::too_many_lines)] // One linear, auditable fixture migration and seed transaction.
fn main() {
    let workspace = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(std::path::Path::parent)
        .expect("workspace")
        .to_owned();
    let destination = env::args_os().nth(1).map_or_else(
        || workspace.join("fixtures/export/operational_catalog_v8.sqlite"),
        PathBuf::from,
    );
    assert!(!destination.exists(), "catalog destination must be absent");
    fs::create_dir_all(destination.parent().expect("destination parent"))
        .expect("create destination parent");
    let mut connection = Connection::open(&destination).expect("create catalog");
    connection
        .execute_batch(
            "PRAGMA application_id=0x4a4f5348;
             PRAGMA journal_mode=WAL;
             PRAGMA synchronous=FULL;
             PRAGMA foreign_keys=ON;",
        )
        .expect("configure catalog");
    for (id, name, sql) in MIGRATIONS {
        if id == 6 {
            connection
                .execute_batch("PRAGMA foreign_keys=OFF; PRAGMA legacy_alter_table=ON;")
                .expect("prepare reviewed V6 rebuild");
        }
        let transaction = connection.transaction().expect("migration transaction");
        transaction.execute_batch(sql).expect("apply migration");
        transaction
            .execute(
                "INSERT INTO schema_migration
                 (migration_id,name,source_sha256,applied_at_us,sqlite_version)
                 VALUES (?1,?2,?3,?4,'fixture-fixed-sqlite')",
                params![
                    id,
                    name,
                    format!("{:x}", Sha256::digest(sql.as_bytes())),
                    id
                ],
            )
            .expect("record migration");
        transaction
            .pragma_update(None, "user_version", id)
            .expect("advance version");
        transaction.commit().expect("commit migration");
        if id == 6 {
            connection
                .execute_batch("PRAGMA legacy_alter_table=OFF; PRAGMA foreign_keys=ON;")
                .expect("restore migration settings");
        }
    }
    let load = include_str!("../../../fixtures/tape/load.sql")
        .strip_prefix("-- Hand-readable E0 data-platform fixture. It is synthetic and carries no market or PnL claim.\n.bail on\n")
        .expect("known tape fixture header");
    connection.execute_batch(load).expect("load tape fixture");
    connection
        .execute_batch(
            "INSERT INTO coverage_window
             (coverage_id,source_id,acquisition_id,scope_kind,scope_key,manifest_blob_id,
              opened_commit_seq,opened_wall_us,coverage_level)
             VALUES ('cov_export_wall','src_fixture_chain',NULL,'market_census','mint-fixture',
                     NULL,2,2000200,'census');
             INSERT INTO coverage_window_contract
             (coverage_id,scope_family_recognition,scope_subject,lower_boundary_json,
              upper_boundary_json,state,state_recognition,available_wall_us)
             VALUES ('cov_export_wall','known','mint-fixture',
                     '{\"clock\":\"wall\",\"value\":\"1970-01-01T00:00:02.000000Z\"}',
                     '{\"clock\":\"wall\",\"value\":\"1970-01-01T00:00:03.000000Z\"}',
                     'closed','known',2000200);
             INSERT INTO coverage_gap
             (gap_id,coverage_id,detected_commit_seq,detected_wall_us,cause_code,severity,
              lower_source_locator,upper_source_locator,event_lower_us,event_upper_us)
             VALUES ('gap_export_wall','cov_export_wall',3,2500000,'fixture_disconnect',
                     'degraded',NULL,NULL,NULL,NULL);
             INSERT INTO coverage_gap_contract
             (gap_id,scope_source_id,scope_family,scope_family_recognition,scope_subject,
              lower_boundary_json,upper_boundary_json,reason_recognition)
             VALUES ('gap_export_wall','src_fixture_chain','market_census','known','mint-fixture',
                     '{\"clock\":\"wall\",\"value\":\"1970-01-01T00:00:02.200000Z\"}',
                     NULL,'known');",
        )
        .expect("insert Snapshot V2-representable coverage fixture");
    let artifact = compact_json(include_bytes!(
        "../../../fixtures/publication/projection_artifact_v1.json"
    ));
    let publication = compact_json(include_bytes!(
        "../../../fixtures/publication/projection_publication_v1.json"
    ));
    assert_eq!(
        format!("{:x}", Sha256::digest(&artifact)),
        "54a044671521c467a312dd1b66853cda14afd8bf3f430fcc2c00919a91e7f583"
    );
    assert_eq!(
        format!("{:x}", Sha256::digest(&publication)),
        "3b2019584418c9a521e6bb4434733b70916d30a86a7a1f52621ce7a7e429a8b6"
    );
    let artifact_length = i64::try_from(artifact.len()).expect("artifact length fits SQLite");
    let publication_length =
        i64::try_from(publication.len()).expect("publication length fits SQLite");
    connection
        .execute(
            "INSERT INTO projection_publication
         (publication_id,projection_id,result_sha256,artifact_sha256,artifact_bytes,
          artifact_byte_length,input_closure_sha256,publication_sha256,
          publication_bytes_sha256,publication_bytes,publication_byte_length,
          through_commit_seq,supersedes_publication_id,authority,created_commit_seq)
         VALUES ('publication-001','projection-001',?1,?2,?3,?4,?5,?6,?7,?8,?9,10,NULL,
                 'read_only_no_execution',11)",
            params![
                "d7c6cbaf0736069a895d126fabeb94ec204bc22285611ba5f5d97098ee34a69b",
                "54a044671521c467a312dd1b66853cda14afd8bf3f430fcc2c00919a91e7f583",
                artifact,
                artifact_length,
                "b57ebaf6f3c0edfbc06f63241a0ec52d9cd6330beedfba7cf8bb545b3b949d9b",
                "1524b025b3e615358a53ac410600d0c386b6f18a93d9c1e19708ab034f87cb8d",
                "3b2019584418c9a521e6bb4434733b70916d30a86a7a1f52621ce7a7e429a8b6",
                publication,
                publication_length,
            ],
        )
        .expect("insert exact projection publication");
    let defects: i64 = connection
        .query_row("SELECT COUNT(*) FROM pragma_foreign_key_check", [], |row| {
            row.get(0)
        })
        .expect("foreign-key check");
    assert_eq!(defects, 0, "fixture has foreign-key defects");
    connection
        .execute_batch("PRAGMA wal_checkpoint(TRUNCATE);")
        .expect("checkpoint fixture");
    let journal_mode: String = connection
        .query_row("PRAGMA journal_mode=DELETE", [], |row| row.get(0))
        .expect("close fixture journal");
    assert_eq!(journal_mode, "delete");
    drop(connection);
    let bytes = fs::read(&destination).expect("catalog bytes");
    println!("sha256:{:x}", Sha256::digest(bytes));
}

fn compact_json(bytes: &[u8]) -> Vec<u8> {
    let connection = Connection::open_in_memory().expect("JSON compactor");
    connection
        .query_row("SELECT CAST(json(?1) AS BLOB)", [bytes], |row| row.get(0))
        .expect("compact fixture JSON")
}
