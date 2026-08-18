-- Exact caller-fed Wave 6 market-atlas fixture under its prior registered schema.
--
-- This table proves sole-store byte retention and exact cross-runtime parser closure only. It
-- confers no source, field-release, market, causal, strategy, product, or execution authority.

CREATE TABLE wave6_fixture_market_atlas_v1 (
    artifact_id TEXT PRIMARY KEY CHECK (
        length(artifact_id) BETWEEN 1 AND 127 AND artifact_id = trim(artifact_id)
    ),
    program_id TEXT NOT NULL REFERENCES wave6_program_registration_v1(program_id),
    kind_id TEXT NOT NULL CHECK (kind_id = 'market_atlas_fixture'),
    schema_id TEXT NOT NULL CHECK (
        schema_id = 'joshi.analysis.wave6-market-atlas-snapshot/v1'
    ),
    schema_sha256 TEXT NOT NULL CHECK (
        length(schema_sha256) = 64 AND schema_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    schema_created_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    artifact_semantic_sha256 TEXT NOT NULL CHECK (
        length(artifact_semantic_sha256) = 64
        AND artifact_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    atlas_snapshot_id TEXT NOT NULL CHECK (
        length(atlas_snapshot_id) BETWEEN 1 AND 127
        AND atlas_snapshot_id = trim(atlas_snapshot_id)
    ),
    atlas_snapshot_sha256 TEXT NOT NULL CHECK (
        length(atlas_snapshot_sha256) = 64
        AND atlas_snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    input_snapshot_id TEXT NOT NULL CHECK (
        length(input_snapshot_id) BETWEEN 1 AND 127
        AND input_snapshot_id = trim(input_snapshot_id)
    ),
    input_logical_sha256 TEXT NOT NULL CHECK (
        length(input_logical_sha256) = 64
        AND input_logical_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    cut_id TEXT NOT NULL CHECK (
        length(cut_id) BETWEEN 1 AND 127 AND cut_id = trim(cut_id)
    ),
    state_time TEXT NOT NULL CHECK (
        length(state_time) = 27 AND substr(state_time, 27, 1) = 'Z'
    ),
    knowledge_cutoff TEXT NOT NULL CHECK (
        length(knowledge_cutoff) = 27 AND substr(knowledge_cutoff, 27, 1) = 'Z'
    ),
    input_as_of_commit_seq INTEGER NOT NULL CHECK (input_as_of_commit_seq > 0),
    artifact_bytes BLOB NOT NULL,
    artifact_byte_length INTEGER NOT NULL CHECK (
        artifact_byte_length > 0 AND length(artifact_bytes) = artifact_byte_length
    ),
    row_count INTEGER NOT NULL CHECK (row_count = 6),
    authority TEXT NOT NULL CHECK (
        authority = 'caller_fed_unverified_semantic_fixture_only'
    ),
    claim_scope TEXT NOT NULL CHECK (
        claim_scope =
          'descriptive_point_in_time_typed_market_atlas_not_scalar_pressure_causal_or_strategy_claim'
    ),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    UNIQUE (program_id, kind_id),
    FOREIGN KEY (program_id, kind_id)
        REFERENCES wave6_registered_artifact_schema_v1(program_id, kind_id)
) STRICT;

CREATE TRIGGER wave6_fixture_market_atlas_matches_registered_schema
BEFORE INSERT ON wave6_fixture_market_atlas_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave6_registered_artifact_schema_v1 schema_row
        WHERE schema_row.program_id = NEW.program_id
          AND schema_row.kind_id = NEW.kind_id
          AND schema_row.schema_id = NEW.schema_id
          AND schema_row.schema_sha256 = NEW.schema_sha256
          AND schema_row.created_commit_seq = NEW.schema_created_commit_seq
          AND schema_row.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'Wave 6 market atlas lacks its exact prior registered schema') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.created_commit_seq
          AND commit_row.commit_class = 'maintenance'
    ) THEN RAISE(ABORT, 'Wave 6 market atlas lacks a store maintenance commit') END;
    SELECT CASE WHEN (
        (SELECT count(*) FROM wave6_fixture_artifact_content_v1
         WHERE program_id = NEW.program_id)
        +
        (SELECT count(*) FROM wave6_fixture_market_atlas_v1
         WHERE program_id = NEW.program_id)
    ) >= CAST((
        SELECT json_extract(
            CAST(registration.registration_bytes AS TEXT), '$.budgets.maxArtifacts'
        )
        FROM wave6_program_registration_v1 registration
        WHERE registration.program_id = NEW.program_id
    ) AS INTEGER)
    THEN RAISE(ABORT, 'Wave 6 fixture artifact budget exhausted') END;
END;

CREATE TRIGGER wave6_fixture_evaluation_global_budget_v19
BEFORE INSERT ON wave6_fixture_artifact_content_v1
BEGIN
    SELECT CASE WHEN (
        (SELECT count(*) FROM wave6_fixture_artifact_content_v1
         WHERE program_id = NEW.program_id)
        +
        (SELECT count(*) FROM wave6_fixture_market_atlas_v1
         WHERE program_id = NEW.program_id)
    ) >= CAST((
        SELECT json_extract(
            CAST(registration.registration_bytes AS TEXT), '$.budgets.maxArtifacts'
        )
        FROM wave6_program_registration_v1 registration
        WHERE registration.program_id = NEW.program_id
    ) AS INTEGER)
    THEN RAISE(ABORT, 'Wave 6 fixture artifact budget exhausted') END;
END;

CREATE TRIGGER no_update_wave6_fixture_market_atlas_v1
BEFORE UPDATE ON wave6_fixture_market_atlas_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_market_atlas_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_fixture_market_atlas_v1
BEFORE DELETE ON wave6_fixture_market_atlas_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_market_atlas_v1 is append-only'); END;
