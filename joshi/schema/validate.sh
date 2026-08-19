#!/usr/bin/env bash
set -euo pipefail

schema_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd "$schema_dir/.." && pwd -P)

if [[ -n "${JOSHI_SQLITE_BIN:-}" ]]; then
    sqlite_bin=$JOSHI_SQLITE_BIN
elif [[ -x /opt/homebrew/opt/sqlite/bin/sqlite3 ]]; then
    sqlite_bin=/opt/homebrew/opt/sqlite/bin/sqlite3
else
    sqlite_bin=$(command -v sqlite3)
fi

sqlite_version=$($sqlite_bin :memory: 'SELECT sqlite_version();')
if ! awk -F. '
    $1 > 3 || ($1 == 3 && ($2 > 51 || ($2 == 51 && $3 >= 3))) { ok = 1 }
    END { exit(ok ? 0 : 1) }
' <<<"$sqlite_version"; then
    echo "refusing SQLite $sqlite_version; validation requires 3.51.3 or later" >&2
    exit 1
fi

if [[ -n "${JOSHI_VALIDATION_DB:-}" ]]; then
    validation_db=$JOSHI_VALIDATION_DB
    validation_dir=
else
    validation_dir=$(mktemp -d "${TMPDIR:-/tmp}/joshi-schema.XXXXXX")
    validation_db=$validation_dir/joshi-validation.sqlite
fi

cleanup() {
    if [[ "${JOSHI_KEEP_VALIDATION_DB:-0}" == 1 || -z "$validation_dir" ]]; then
        echo "validation database: $validation_db"
        return
    fi
    for suffix in '' '-wal' '-shm'; do
        if [[ -f "$validation_db$suffix" ]]; then
            unlink "$validation_db$suffix"
        fi
    done
    rmdir "$validation_dir"
}
trap cleanup EXIT

setup_result=$($sqlite_bin -batch -bail "$validation_db" <<'SQL'
PRAGMA application_id = 0x4a4f5348;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA foreign_keys = ON;
SQL
)
if [[ "$setup_result" != wal ]]; then
    echo "failed to establish WAL mode: $setup_result" >&2
    exit 1
fi

apply_migration() {
    local migration=$1
    local basename version_text version_number source_sha existing existing_name has_ledger
    basename=${migration##*/}
    version_text=${basename%%_*}
    version_number=$((10#$version_text))
    source_sha=$(shasum -a 256 "$migration" | awk '{print $1}')
    has_ledger=$($sqlite_bin "$validation_db" \
        "SELECT count(*) FROM sqlite_schema WHERE type='table' AND name='schema_migration';")

    if [[ "$has_ledger" == 1 ]]; then
        existing=$($sqlite_bin "$validation_db" \
            "SELECT source_sha256 FROM schema_migration WHERE migration_id=$version_number;")
        if [[ -n "$existing" ]]; then
            existing_name=$($sqlite_bin "$validation_db" \
                "SELECT name FROM schema_migration WHERE migration_id=$version_number;")
            if [[ "$existing" != "$source_sha" ]]; then
                echo "migration $basename changed after application" >&2
                exit 1
            fi
            if [[ "$existing_name" != "$basename" ]]; then
                echo "migration $version_number was renamed after application" >&2
                exit 1
            fi
            return
        fi
        local expected_next
        expected_next=$($sqlite_bin "$validation_db" \
            'SELECT COALESCE(MAX(migration_id), 0) + 1 FROM schema_migration;')
        if [[ "$expected_next" != "$version_number" ]]; then
            echo "migration $basename is not the next forward migration ($expected_next)" >&2
            exit 1
        fi
    elif [[ "$version_number" != 1 ]]; then
        echo "first migration must be 0001" >&2
        exit 1
    fi

    local foreign_keys_before legacy_alter_before
    foreign_keys_before=ON
    legacy_alter_before=OFF
    if [[ "$version_number" == 6 ]]; then
        foreign_keys_before=OFF
        legacy_alter_before=ON
    fi

    $sqlite_bin -batch -bail "$validation_db" <<SQL
PRAGMA foreign_keys = $foreign_keys_before;
PRAGMA legacy_alter_table = $legacy_alter_before;
PRAGMA synchronous = FULL;
BEGIN IMMEDIATE;
.read '$migration'
INSERT INTO schema_migration
    (migration_id, name, source_sha256, applied_at_us, sqlite_version)
VALUES
    ($version_number, '$basename', '$source_sha',
     CAST(strftime('%s', 'now') AS INTEGER) * 1000000, sqlite_version());
PRAGMA user_version = $version_number;
COMMIT;
PRAGMA legacy_alter_table = OFF;
PRAGMA foreign_keys = ON;
SQL

    if [[ "$version_number" == 6 ]]; then
        local foreign_key_defects
        foreign_key_defects=$($sqlite_bin "$validation_db" 'SELECT count(*) FROM pragma_foreign_key_check;')
        if [[ "$foreign_key_defects" != 0 ]]; then
            echo "migration $basename left $foreign_key_defects foreign-key defects" >&2
            exit 1
        fi
    fi
}

migration_file_count=0
for migration in "$schema_dir"/migrations/*.sql; do
    migration_file_count=$((migration_file_count + 1))
    apply_migration "$migration"
done

# Prove a second pass is a checksum-verified no-op.
for migration in "$schema_dir"/migrations/*.sql; do
    apply_migration "$migration"
done

migration_ledger_count=$($sqlite_bin "$validation_db" 'SELECT count(*) FROM schema_migration;')
if [[ "$migration_ledger_count" != "$migration_file_count" ]]; then
    echo "database has migrations not represented by this source tree" >&2
    exit 1
fi

application_id=$($sqlite_bin "$validation_db" 'PRAGMA application_id;')
journal_mode=$($sqlite_bin "$validation_db" 'PRAGMA journal_mode;')
synchronous=$($sqlite_bin "$validation_db" 'PRAGMA synchronous;')
foreign_keys=$($sqlite_bin "$validation_db" 'PRAGMA foreign_keys=ON; PRAGMA foreign_keys;')
if [[ "$application_id" != 1246712648 || "$journal_mode" != wal \
      || "$synchronous" != 2 || "$foreign_keys" != 1 ]]; then
    echo "runtime PRAGMA verification failed: app=$application_id journal=$journal_mode sync=$synchronous fk=$foreign_keys" >&2
    exit 1
fi

# Exercise the production upgrade edges independently: create an exact V4 catalog, close it, then
# reopen and apply V5, the acquisition-table V6 rebuild, the additive V7 operational schema,
# narrow V8 semantic artifact mappings, the additive V9 authority spine, the G0 V10 spine, and
# the fixture-only Wave 6 registry/analysis spine through the V22 operator-evidence bridge.
fresh_validation_db=$validation_db
upgrade_db=$validation_dir/joshi-upgrade-v4.sqlite
validation_db=$upgrade_db
upgrade_setup_result=$($sqlite_bin -batch -bail "$validation_db" <<'SQL'
PRAGMA application_id = 0x4a4f5348;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA foreign_keys = ON;
SQL
)
if [[ "$upgrade_setup_result" != wal ]]; then
    echo "failed to establish WAL mode for V4-to-V5 upgrade: $upgrade_setup_result" >&2
    exit 1
fi
for migration in "$schema_dir"/migrations/000[1-4]_*.sql; do
    apply_migration "$migration"
done
apply_migration "$schema_dir/migrations/0005_lossless_contract.sql"
$sqlite_bin -batch -bail "$validation_db" <<'SQL'
INSERT INTO ingest_commit
    (commit_id,commit_class,committed_wall_us,writer_clock_id,committed_mono_ns,
     writer_build,prior_commit_digest,commit_digest)
VALUES
    ('upgrade-c1','fixture',1,'upgrade-clock','1','upgrade-test',NULL,
     '1111111111111111111111111111111111111111111111111111111111111111');
INSERT INTO source
    (source_id,namespace,source_contract_version,collector_build,configuration_fingerprint)
VALUES
    ('upgrade-source','fixture.upgrade','1','upgrade-test',
     '2222222222222222222222222222222222222222222222222222222222222222');
INSERT INTO acquisition
    (acquisition_id,source_id,acquisition_kind,transport_kind,registered_commit_seq,
     parent_acquisition_id,request_fingerprint,started_wall_us,local_clock_id,
     started_mono_ns,source_locator_redacted)
VALUES
    ('upgrade-acquisition','upgrade-source','fixture','fixture',1,NULL,
     '3333333333333333333333333333333333333333333333333333333333333333',
     1,'upgrade-source-clock','7','fixture://upgrade');
INSERT INTO acquisition_contract
    (acquisition_id,contract_version,acquisition_kind_recognition,
     transport_kind_recognition,requested_wall_us,received_wall_us,persisted_wall_us,
     elapsed_mono_ns,elapsed_clock_id,source_cursor_text)
VALUES
    ('upgrade-acquisition','1','known','known',1,1,1,NULL,NULL,NULL);
SQL
apply_migration "$schema_dir/migrations/0006_optional_acquisition_monotonic.sql"
apply_migration "$schema_dir/migrations/0007_operational_exocortex.sql"
apply_migration "$schema_dir/migrations/0008_semantic_artifact_durability.sql"
apply_migration "$schema_dir/migrations/0009_wave5_living_instrument.sql"
apply_migration "$schema_dir/migrations/0010_wave5_g0_store_spine.sql"
apply_migration "$schema_dir/migrations/0011_wave6_program_registry.sql"
apply_migration "$schema_dir/migrations/0012_wave6_artifact_schemas.sql"
apply_migration "$schema_dir/migrations/0013_wave6_fixture_artifacts.sql"
apply_migration "$schema_dir/migrations/0014_wave6_artifact_dag.sql"
apply_migration "$schema_dir/migrations/0015_wave6_fixture_decisions.sql"
apply_migration "$schema_dir/migrations/0016_wave6_campaign_bundle.sql"
apply_migration "$schema_dir/migrations/0017_wave6_research_proposal.sql"
apply_migration "$schema_dir/migrations/0018_wave6_research_disposition.sql"
apply_migration "$schema_dir/migrations/0019_wave6_market_atlas_fixture.sql"
apply_migration "$schema_dir/migrations/0020_wave6_store_input_census.sql"
apply_migration "$schema_dir/migrations/0021_cockpit_v2_browser_presentation.sql"
apply_migration "$schema_dir/migrations/0022_wave6_operator_evidence_input.sql"
upgrade_version=$($sqlite_bin "$validation_db" 'PRAGMA user_version;')
upgrade_integrity=$($sqlite_bin "$validation_db" 'PRAGMA integrity_check;')
upgrade_clock=$($sqlite_bin -separator '|' "$validation_db" \
    "SELECT local_clock_id,started_mono_ns FROM acquisition WHERE acquisition_id='upgrade-acquisition';")
if [[ "$upgrade_version" != 22 || "$upgrade_integrity" != ok \
      || "$upgrade_clock" != 'upgrade-source-clock|7' ]]; then
    echo "V4-to-V22 upgrade validation failed: version=$upgrade_version integrity=$upgrade_integrity" >&2
    exit 1
fi
for suffix in '' '-wal' '-shm'; do
    if [[ -f "$upgrade_db$suffix" ]]; then
        unlink "$upgrade_db$suffix"
    fi
done
validation_db=$fresh_validation_db

$sqlite_bin -batch -bail "$validation_db" < "$repo_root/fixtures/tape/load.sql"

verify_catalog_file() {
    local identity=$1 relative_path=$2 expected_sha=$3 expected_bytes=$4 path actual_sha actual_bytes
    path=$repo_root/$relative_path
    if [[ ! -f "$path" ]]; then
        echo "missing fixture file for $identity: $relative_path" >&2
        exit 1
    fi
    actual_sha=$(shasum -a 256 "$path" | awk '{print $1}')
    actual_bytes=$(wc -c < "$path" | tr -d ' ')
    if [[ "$actual_sha" != "$expected_sha" || "$actual_bytes" != "$expected_bytes" ]]; then
        echo "fixture file mismatch for $identity" >&2
        exit 1
    fi
}

while IFS='|' read -r blob_id relative_path stored_sha stored_length; do
    verify_catalog_file "$blob_id" "$relative_path" "$stored_sha" "$stored_length"
done < <($sqlite_bin -separator '|' "$validation_db" \
    "SELECT blob_id, relative_path, stored_sha256, stored_length
     FROM blob WHERE storage_mode='external' ORDER BY blob_id;")

while IFS='|' read -r manifest_id relative_path file_sha byte_length; do
    verify_catalog_file "$manifest_id" "$relative_path" "$file_sha" "$byte_length"
done < <($sqlite_bin -separator '|' "$validation_db" \
    'SELECT export_manifest_id, relative_path, file_sha256, byte_length
     FROM export_manifest ORDER BY export_manifest_id;')

manifest_valid=$($sqlite_bin :memory: \
    "SELECT json_valid(CAST(readfile('$repo_root/fixtures/tape/manifest.json') AS TEXT));")
if [[ "$manifest_valid" != 1 ]]; then
    echo 'fixtures/tape/manifest.json is not valid JSON' >&2
    exit 1
fi

while IFS='|' read -r relative_path expected_sha; do
    actual_sha=$(shasum -a 256 "$repo_root/$relative_path" | awk '{print $1}')
    if [[ "$actual_sha" != "$expected_sha" ]]; then
        echo "manifest checksum mismatch: $relative_path" >&2
        exit 1
    fi
done < <($sqlite_bin -separator '|' :memory: <<SQL
WITH document(value) AS (
    SELECT CAST(readfile('$repo_root/fixtures/tape/manifest.json') AS TEXT)
)
SELECT json_extract(value, '$.load_sql.path'), json_extract(value, '$.load_sql.sha256')
FROM document
UNION ALL
SELECT json_extract(value, '$.expected_sql.path'), json_extract(value, '$.expected_sql.sha256')
FROM document
UNION ALL
SELECT json_extract(item.value, '$.path'), json_extract(item.value, '$.sha256')
FROM document, json_each(json_extract(document.value, '$.migrations')) AS item;
SQL
)

while IFS='|' read -r relative_path expected_sha expected_bytes; do
    verify_catalog_file "fixture-manifest" "$relative_path" "$expected_sha" "$expected_bytes"
done < <($sqlite_bin -separator '|' :memory: <<SQL
WITH document(value) AS (
    SELECT CAST(readfile('$repo_root/fixtures/tape/manifest.json') AS TEXT)
)
SELECT json_extract(item.value, '$.path'), json_extract(item.value, '$.sha256'),
       json_extract(item.value, '$.bytes')
FROM document, json_each(json_extract(document.value, '$.artifacts')) AS item;
SQL
)

$sqlite_bin -batch -bail "$validation_db" ".read '$schema_dir/checks/catalog_invariants.sql'"
$sqlite_bin -batch -bail "$validation_db" ".read '$repo_root/fixtures/tape/expected.sql'"

# Negative checks: STRICT typing, append-only evidence, and idempotent command identity.
if $sqlite_bin -batch -bail "$validation_db" \
    "UPDATE observation SET quality_code='rewritten' WHERE observation_id='obs_equal_primary';" \
    >/dev/null 2>&1; then
    echo 'append-only observation mutation unexpectedly succeeded' >&2
    exit 1
fi

if $sqlite_bin -batch -bail "$validation_db" \
    "INSERT INTO command SELECT 'cmd_fixture_runner_retry', committed_commit_seq, scene_id,
       client_session_id, 99, idempotency_key, command_kind, subject_kind, subject_key,
       payload_blob_id, issued_wall_us, client_clock_id, issued_mono_ns, received_wall_us,
       effect_ceiling, authority_class
     FROM command WHERE command_id='cmd_fixture_runner';" >/dev/null 2>&1; then
    echo 'duplicate command idempotency key unexpectedly succeeded' >&2
    exit 1
fi

if $sqlite_bin -batch -bail "$validation_db" \
    "INSERT INTO ingest_commit(commit_seq,commit_id,commit_class,committed_wall_us,
       writer_clock_id,committed_mono_ns,writer_build,prior_commit_digest,commit_digest)
     VALUES('not-an-integer','cmt_bad','fixture',1,'clock','1','build',NULL,
       'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');" \
    >/dev/null 2>&1; then
    echo 'STRICT integer coercion probe unexpectedly succeeded' >&2
    exit 1
fi

integrity=$($sqlite_bin "$validation_db" 'PRAGMA integrity_check;')
foreign_key_defects=$($sqlite_bin "$validation_db" 'PRAGMA foreign_keys=ON; SELECT count(*) FROM pragma_foreign_key_check;')
if [[ "$integrity" != ok || "$foreign_key_defects" != 0 ]]; then
    echo "final integrity failure: integrity=$integrity foreign_keys=$foreign_key_defects" >&2
    exit 1
fi

echo "validated SQLite $sqlite_version: $migration_file_count migrations, 13 commits, 6 observations, 7 assertions"
