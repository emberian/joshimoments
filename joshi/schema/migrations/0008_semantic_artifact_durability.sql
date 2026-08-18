-- Lossless occurrence-to-content mappings and immutable derived-artifact part registration.
-- This migration adds no source, model, wallet, signing, transaction, or economic authority.

CREATE TABLE production_export_request_v2 (
    export_request_id TEXT PRIMARY KEY CHECK (
        length(export_request_id) BETWEEN 1 AND 512
        AND export_request_id = trim(export_request_id)
    ),
    validation_id TEXT NOT NULL UNIQUE REFERENCES export_validation(validation_id),
    snapshot_id TEXT NOT NULL UNIQUE REFERENCES export_snapshot(export_snapshot_id),
    snapshot_manifest_sha256 TEXT NOT NULL CHECK (
        length(snapshot_manifest_sha256) = 64
        AND snapshot_manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    truth_fingerprint_sha256 TEXT NOT NULL CHECK (
        length(truth_fingerprint_sha256) = 64
        AND truth_fingerprint_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TRIGGER production_export_request_closes_validation
BEFORE INSERT ON production_export_request_v2
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM export_validation v
        JOIN export_snapshot s ON s.export_snapshot_id = v.export_snapshot_id
        WHERE v.validation_id = NEW.validation_id
          AND v.export_snapshot_id = NEW.snapshot_id
          AND v.manifest_sha256 = NEW.snapshot_manifest_sha256
          AND v.created_commit_seq = NEW.created_commit_seq
          AND s.created_commit_seq = NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'export request does not close one exact validated snapshot') END;
END;

CREATE TABLE production_export_publication_v2 (
    export_request_id TEXT NOT NULL
        REFERENCES production_export_request_v2(export_request_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    publication_id TEXT NOT NULL CHECK (
        length(publication_id) BETWEEN 1 AND 512 AND publication_id = trim(publication_id)
    ),
    PRIMARY KEY (export_request_id, ordinal),
    UNIQUE (export_request_id, publication_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE analysis_artifact_import_v2 (
    import_id TEXT PRIMARY KEY REFERENCES derived_analysis_artifact(import_id),
    export_request_id TEXT NOT NULL REFERENCES production_export_request_v2(export_request_id),
    analysis_run_id TEXT NOT NULL UNIQUE CHECK (
        length(analysis_run_id) BETWEEN 1 AND 512 AND analysis_run_id = trim(analysis_run_id)
    ),
    snapshot_id TEXT NOT NULL REFERENCES export_snapshot(export_snapshot_id),
    artifact_id TEXT NOT NULL UNIQUE CHECK (
        length(artifact_id) BETWEEN 1 AND 512 AND artifact_id = trim(artifact_id)
    ),
    claim_scope TEXT NOT NULL CHECK (
        length(claim_scope) BETWEEN 1 AND 512 AND claim_scope = trim(claim_scope)
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TRIGGER analysis_artifact_import_closes_occurrences
BEFORE INSERT ON analysis_artifact_import_v2
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM derived_analysis_artifact d
        JOIN production_export_request_v2 e
          ON e.export_request_id = NEW.export_request_id
        WHERE d.import_id = NEW.import_id
          AND d.artifact_id = NEW.artifact_id
          AND d.input_snapshot_id = NEW.snapshot_id
          AND e.snapshot_id = NEW.snapshot_id
          AND d.created_commit_seq = NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'artifact import does not close exact request/run/content occurrences') END;
END;

CREATE TABLE derived_analysis_artifact_part_v2 (
    import_id TEXT NOT NULL REFERENCES analysis_artifact_import_v2(import_id),
    part_ordinal INTEGER NOT NULL CHECK (part_ordinal >= 0),
    relative_path TEXT NOT NULL UNIQUE CHECK (
        relative_path <> ''
        AND relative_path = trim(relative_path)
        AND relative_path NOT LIKE '/%'
        AND relative_path NOT LIKE '%/../%'
        AND relative_path NOT LIKE '../%'
    ),
    schema_id TEXT NOT NULL CHECK (schema_id <> ''),
    schema_sha256 TEXT NOT NULL CHECK (
        length(schema_sha256) = 64 AND schema_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    file_sha256 TEXT NOT NULL CHECK (
        length(file_sha256) = 64 AND file_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    logical_sha256 TEXT NOT NULL CHECK (
        length(logical_sha256) = 64 AND logical_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    byte_length INTEGER NOT NULL CHECK (byte_length > 0),
    row_count INTEGER NOT NULL CHECK (row_count >= 0),
    retention_class TEXT NOT NULL CHECK (
        retention_class IN ('analysis_derived_public_integrity')
    ),
    PRIMARY KEY (import_id, part_ordinal)
) STRICT, WITHOUT ROWID;

CREATE TRIGGER no_update_production_export_request_v2
BEFORE UPDATE ON production_export_request_v2
BEGIN SELECT RAISE(ABORT, 'production_export_request_v2 is append-only'); END;
CREATE TRIGGER no_delete_production_export_request_v2
BEFORE DELETE ON production_export_request_v2
BEGIN SELECT RAISE(ABORT, 'production_export_request_v2 is append-only'); END;
CREATE TRIGGER no_update_analysis_artifact_import_v2
BEFORE UPDATE ON analysis_artifact_import_v2
BEGIN SELECT RAISE(ABORT, 'analysis_artifact_import_v2 is append-only'); END;
CREATE TRIGGER no_update_production_export_publication_v2
BEFORE UPDATE ON production_export_publication_v2
BEGIN SELECT RAISE(ABORT, 'production_export_publication_v2 is append-only'); END;
CREATE TRIGGER no_delete_production_export_publication_v2
BEFORE DELETE ON production_export_publication_v2
BEGIN SELECT RAISE(ABORT, 'production_export_publication_v2 is append-only'); END;
CREATE TRIGGER no_delete_analysis_artifact_import_v2
BEFORE DELETE ON analysis_artifact_import_v2
BEGIN SELECT RAISE(ABORT, 'analysis_artifact_import_v2 is append-only'); END;
CREATE TRIGGER no_update_derived_analysis_artifact_part_v2
BEFORE UPDATE ON derived_analysis_artifact_part_v2
BEGIN SELECT RAISE(ABORT, 'derived_analysis_artifact_part_v2 is append-only'); END;
CREATE TRIGGER no_delete_derived_analysis_artifact_part_v2
BEFORE DELETE ON derived_analysis_artifact_part_v2
BEGIN SELECT RAISE(ABORT, 'derived_analysis_artifact_part_v2 is append-only'); END;
