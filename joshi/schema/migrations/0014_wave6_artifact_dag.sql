-- Exact fixture artifact-DAG documents over prior durable Wave 6 content rows.
--
-- The retained clocks are explicitly fixture-declared. This migration provides no Wave 5 gate,
-- empirical, operational, product, live, causal, identity, policy-value, or economic authority.

CREATE TABLE wave6_fixture_artifact_dag_v1 (
    dag_id TEXT PRIMARY KEY CHECK (
        length(dag_id) BETWEEN 1 AND 127 AND dag_id = trim(dag_id)
    ),
    program_id TEXT NOT NULL REFERENCES wave6_program_registration_v1(program_id),
    registration_semantic_sha256 TEXT NOT NULL CHECK (
        length(registration_semantic_sha256) = 64
        AND registration_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    dag_semantic_sha256 TEXT NOT NULL CHECK (
        length(dag_semantic_sha256) = 64
        AND dag_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    dag_document_sha256 TEXT NOT NULL CHECK (
        length(dag_document_sha256) = 64
        AND dag_document_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    dag_bytes BLOB NOT NULL,
    dag_byte_length INTEGER NOT NULL CHECK (
        dag_byte_length > 0 AND length(dag_bytes) = dag_byte_length
    ),
    artifact_count INTEGER NOT NULL CHECK (artifact_count > 0),
    maximum_information_cutoff_wall_us INTEGER NOT NULL CHECK (
        maximum_information_cutoff_wall_us > 0
    ),
    maximum_produced_wall_us INTEGER NOT NULL CHECK (
        maximum_produced_wall_us >= maximum_information_cutoff_wall_us
    ),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    UNIQUE (program_id, dag_semantic_sha256),
    UNIQUE (program_id, dag_document_sha256)
) STRICT;

CREATE TABLE wave6_fixture_artifact_dag_member_v1 (
    dag_id TEXT NOT NULL REFERENCES wave6_fixture_artifact_dag_v1(dag_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    artifact_id TEXT NOT NULL REFERENCES wave6_fixture_artifact_content_v1(artifact_id),
    kind_id TEXT NOT NULL CHECK (
        length(kind_id) BETWEEN 1 AND 255 AND kind_id = trim(kind_id)
    ),
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    information_cutoff_wall_us INTEGER NOT NULL CHECK (information_cutoff_wall_us > 0),
    produced_wall_us INTEGER NOT NULL CHECK (produced_wall_us >= information_cutoff_wall_us),
    parent_count INTEGER NOT NULL CHECK (parent_count >= 0),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    PRIMARY KEY (dag_id, ordinal),
    UNIQUE (dag_id, artifact_id),
    UNIQUE (dag_id, content_sha256)
) WITHOUT ROWID, STRICT;

CREATE TRIGGER wave6_fixture_dag_matches_registration
BEFORE INSERT ON wave6_fixture_artifact_dag_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave6_program_registration_v1 registration
        WHERE registration.program_id = NEW.program_id
          AND registration.registration_semantic_sha256 = NEW.registration_semantic_sha256
          AND registration.semantic_ceiling = NEW.semantic_ceiling
    ) THEN RAISE(ABORT, 'Wave 6 artifact DAG lacks its exact registration') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.created_commit_seq
          AND commit_row.commit_class = 'maintenance'
    ) THEN RAISE(ABORT, 'Wave 6 artifact DAG lacks a store maintenance commit') END;
END;

CREATE TRIGGER wave6_fixture_dag_member_matches_content
BEFORE INSERT ON wave6_fixture_artifact_dag_member_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave6_fixture_artifact_content_v1 artifact
        JOIN wave6_fixture_artifact_dag_v1 dag ON dag.dag_id = NEW.dag_id
        WHERE artifact.artifact_id = NEW.artifact_id
          AND artifact.program_id = dag.program_id
          AND artifact.kind_id = NEW.kind_id
          AND artifact.content_sha256 = NEW.content_sha256
          AND artifact.semantic_ceiling = NEW.semantic_ceiling
          AND artifact.created_commit_seq < dag.created_commit_seq
    ) THEN RAISE(ABORT, 'Wave 6 DAG member lacks exact prior durable content') END;
END;

CREATE TRIGGER no_update_wave6_fixture_artifact_dag_v1
BEFORE UPDATE ON wave6_fixture_artifact_dag_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_artifact_dag_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_fixture_artifact_dag_v1
BEFORE DELETE ON wave6_fixture_artifact_dag_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_artifact_dag_v1 is append-only'); END;

CREATE TRIGGER no_update_wave6_fixture_artifact_dag_member_v1
BEFORE UPDATE ON wave6_fixture_artifact_dag_member_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_artifact_dag_member_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_fixture_artifact_dag_member_v1
BEFORE DELETE ON wave6_fixture_artifact_dag_member_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_artifact_dag_member_v1 is append-only'); END;
