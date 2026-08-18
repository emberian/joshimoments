-- Exact, fixture-only evaluation artifact content under the registered Wave 6 schema catalog.
--
-- This table proves durable byte retention and exact parser closure only. It has no information
-- cutoff, artifact-DAG occurrence, Wave 5 gate receipt, empirical result, or operational authority.

CREATE TABLE wave6_fixture_artifact_content_v1 (
    artifact_id TEXT PRIMARY KEY CHECK (
        length(artifact_id) BETWEEN 1 AND 127 AND artifact_id = trim(artifact_id)
    ),
    program_id TEXT NOT NULL REFERENCES wave6_program_registration_v1(program_id),
    kind_id TEXT NOT NULL CHECK (
        length(kind_id) BETWEEN 1 AND 255 AND kind_id = trim(kind_id)
    ),
    schema_id TEXT NOT NULL CHECK (
        length(schema_id) BETWEEN 1 AND 255 AND schema_id = trim(schema_id)
    ),
    schema_sha256 TEXT NOT NULL CHECK (
        length(schema_sha256) = 64 AND schema_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    schema_created_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    evaluation_semantic_sha256 TEXT NOT NULL CHECK (
        length(evaluation_semantic_sha256) = 64
        AND evaluation_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    artifact_bytes BLOB NOT NULL,
    artifact_byte_length INTEGER NOT NULL CHECK (
        artifact_byte_length > 0 AND length(artifact_bytes) = artifact_byte_length
    ),
    result_count INTEGER NOT NULL CHECK (result_count > 0),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    UNIQUE (program_id, kind_id, content_sha256),
    FOREIGN KEY (program_id, kind_id)
        REFERENCES wave6_registered_artifact_schema_v1(program_id, kind_id)
) STRICT;

CREATE TRIGGER wave6_fixture_artifact_matches_registered_schema
BEFORE INSERT ON wave6_fixture_artifact_content_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave6_registered_artifact_schema_v1 schema_row
        WHERE schema_row.program_id = NEW.program_id
          AND schema_row.kind_id = NEW.kind_id
          AND schema_row.schema_id = NEW.schema_id
          AND schema_row.schema_sha256 = NEW.schema_sha256
          AND schema_row.created_commit_seq = NEW.schema_created_commit_seq
          AND schema_row.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'Wave 6 artifact lacks its exact prior registered schema') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.created_commit_seq
          AND commit_row.commit_class = 'maintenance'
    ) THEN RAISE(ABORT, 'Wave 6 artifact lacks a store maintenance commit') END;
    SELECT CASE WHEN (
        SELECT count(*) FROM wave6_fixture_artifact_content_v1 existing
        WHERE existing.program_id = NEW.program_id
    ) >= CAST((
        SELECT json_extract(
            CAST(registration.registration_bytes AS TEXT), '$.budgets.maxArtifacts'
        )
        FROM wave6_program_registration_v1 registration
        WHERE registration.program_id = NEW.program_id
    ) AS INTEGER)
    THEN RAISE(ABORT, 'Wave 6 fixture artifact budget exhausted') END;
END;

CREATE TRIGGER no_update_wave6_fixture_artifact_content_v1
BEFORE UPDATE ON wave6_fixture_artifact_content_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_artifact_content_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_fixture_artifact_content_v1
BEFORE DELETE ON wave6_fixture_artifact_content_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_artifact_content_v1 is append-only'); END;
