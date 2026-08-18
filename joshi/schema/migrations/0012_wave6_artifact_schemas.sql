-- Exact schema bytes for the artifact kinds registered by the fixture-only Wave 6 program.
--
-- These rows close registration-to-schema identity only. They do not admit an artifact
-- occurrence, resolve a Wave 5 gate, or confer empirical, causal, economic, product or live
-- authority.

CREATE TABLE wave6_registered_artifact_schema_v1 (
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
    schema_bytes BLOB NOT NULL,
    schema_byte_length INTEGER NOT NULL CHECK (
        schema_byte_length > 0 AND length(schema_bytes) = schema_byte_length
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_record_replay_propose_shadow_only'),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    PRIMARY KEY (program_id, kind_id),
    UNIQUE (program_id, schema_id),
    UNIQUE (program_id, schema_sha256)
) STRICT;

CREATE TRIGGER wave6_artifact_schema_matches_exact_registration
BEFORE INSERT ON wave6_registered_artifact_schema_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave6_program_registration_v1 registration,
             json_each(CAST(registration.registration_bytes AS TEXT), '$.artifactKinds') item
        WHERE registration.program_id = NEW.program_id
          AND json_extract(item.value, '$.kindId') = NEW.kind_id
          AND json_extract(item.value, '$.schemaId') = NEW.schema_id
          AND json_extract(item.value, '$.schemaDigest') = 'sha256:' || NEW.schema_sha256
          AND registration.authority = NEW.authority
          AND registration.semantic_ceiling = NEW.semantic_ceiling
    ) THEN RAISE(ABORT, 'Wave 6 schema row is absent from its exact registration') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.created_commit_seq
          AND commit_row.commit_class = 'maintenance'
    ) THEN RAISE(ABORT, 'Wave 6 schema lacks a store maintenance commit') END;
END;

CREATE TRIGGER no_update_wave6_registered_artifact_schema_v1
BEFORE UPDATE ON wave6_registered_artifact_schema_v1
BEGIN SELECT RAISE(ABORT, 'wave6_registered_artifact_schema_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_registered_artifact_schema_v1
BEFORE DELETE ON wave6_registered_artifact_schema_v1
BEGIN SELECT RAISE(ABORT, 'wave6_registered_artifact_schema_v1 is append-only'); END;
