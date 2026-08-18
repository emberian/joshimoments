-- Exact fixture-only decision ledgers over prior durable Wave 6 artifact DAGs.
--
-- These rows retain append-only fixture dispositions. They grant no Wave 5 gate, human approval,
-- operational release, empirical, product, live, causal, policy-value, or economic authority.

CREATE TABLE wave6_fixture_decision_ledger_v1 (
    ledger_id TEXT PRIMARY KEY CHECK (
        length(ledger_id) BETWEEN 1 AND 127 AND ledger_id = trim(ledger_id)
    ),
    program_id TEXT NOT NULL REFERENCES wave6_program_registration_v1(program_id),
    dag_id TEXT NOT NULL REFERENCES wave6_fixture_artifact_dag_v1(dag_id),
    registration_semantic_sha256 TEXT NOT NULL CHECK (
        length(registration_semantic_sha256) = 64
        AND registration_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    dag_semantic_sha256 TEXT NOT NULL CHECK (
        length(dag_semantic_sha256) = 64
        AND dag_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    ledger_semantic_sha256 TEXT NOT NULL CHECK (
        length(ledger_semantic_sha256) = 64
        AND ledger_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    ledger_document_sha256 TEXT NOT NULL CHECK (
        length(ledger_document_sha256) = 64
        AND ledger_document_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    ledger_bytes BLOB NOT NULL,
    ledger_byte_length INTEGER NOT NULL CHECK (
        ledger_byte_length > 0 AND length(ledger_bytes) = ledger_byte_length
    ),
    decision_count INTEGER NOT NULL CHECK (decision_count > 0),
    maximum_decided_wall_us INTEGER NOT NULL CHECK (maximum_decided_wall_us > 0),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    UNIQUE (program_id, ledger_semantic_sha256),
    UNIQUE (program_id, ledger_document_sha256)
) STRICT;

CREATE TABLE wave6_fixture_decision_v1 (
    ledger_id TEXT NOT NULL REFERENCES wave6_fixture_decision_ledger_v1(ledger_id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    decision_id TEXT NOT NULL CHECK (
        length(decision_id) BETWEEN 1 AND 127 AND decision_id = trim(decision_id)
    ),
    artifact_id TEXT NOT NULL REFERENCES wave6_fixture_artifact_content_v1(artifact_id),
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    predecessor_decision_id TEXT CHECK (
        predecessor_decision_id IS NULL OR (
            length(predecessor_decision_id) BETWEEN 1 AND 127
            AND predecessor_decision_id = trim(predecessor_decision_id)
        )
    ),
    decision_kind TEXT NOT NULL CHECK (
        decision_kind IN ('retain_contract_only','promote_fixture_roundtrip','park','reject')
    ),
    decided_wall_us INTEGER NOT NULL CHECK (decided_wall_us > 0),
    evidence_count INTEGER NOT NULL CHECK (evidence_count > 0),
    reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 255 AND reason = trim(reason)),
    authority TEXT NOT NULL CHECK (authority = 'read_record_replay_propose_shadow_only'),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    PRIMARY KEY (ledger_id, ordinal),
    UNIQUE (ledger_id, decision_id)
) WITHOUT ROWID, STRICT;

CREATE TABLE wave6_fixture_decision_evidence_v1 (
    ledger_id TEXT NOT NULL,
    decision_ordinal INTEGER NOT NULL,
    evidence_ordinal INTEGER NOT NULL CHECK (evidence_ordinal >= 0),
    artifact_id TEXT NOT NULL REFERENCES wave6_fixture_artifact_content_v1(artifact_id),
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    PRIMARY KEY (ledger_id, decision_ordinal, evidence_ordinal),
    UNIQUE (ledger_id, decision_ordinal, artifact_id),
    FOREIGN KEY (ledger_id, decision_ordinal)
        REFERENCES wave6_fixture_decision_v1(ledger_id, ordinal)
) WITHOUT ROWID, STRICT;

CREATE TRIGGER wave6_fixture_decision_ledger_matches_dag
BEFORE INSERT ON wave6_fixture_decision_ledger_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave6_fixture_artifact_dag_v1 dag
        JOIN wave6_program_registration_v1 registration
          ON registration.program_id = dag.program_id
        WHERE dag.dag_id = NEW.dag_id
          AND dag.program_id = NEW.program_id
          AND dag.registration_semantic_sha256 = NEW.registration_semantic_sha256
          AND dag.dag_semantic_sha256 = NEW.dag_semantic_sha256
          AND dag.semantic_ceiling = NEW.semantic_ceiling
          AND registration.registration_semantic_sha256 = NEW.registration_semantic_sha256
          AND dag.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'Wave 6 decision ledger lacks its exact prior durable DAG') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.created_commit_seq
          AND commit_row.commit_class = 'maintenance'
    ) THEN RAISE(ABORT, 'Wave 6 decision ledger lacks a store maintenance commit') END;
END;

CREATE TRIGGER wave6_fixture_decision_matches_dag_member
BEFORE INSERT ON wave6_fixture_decision_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave6_fixture_decision_ledger_v1 ledger
        JOIN wave6_fixture_artifact_dag_member_v1 member
          ON member.dag_id = ledger.dag_id
        WHERE ledger.ledger_id = NEW.ledger_id
          AND member.artifact_id = NEW.artifact_id
          AND member.content_sha256 = NEW.content_sha256
          AND member.semantic_ceiling = NEW.semantic_ceiling
    ) THEN RAISE(ABORT, 'Wave 6 decision target lacks exact DAG membership') END;
END;

CREATE TRIGGER wave6_fixture_decision_evidence_matches_dag_member
BEFORE INSERT ON wave6_fixture_decision_evidence_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave6_fixture_decision_ledger_v1 ledger
        JOIN wave6_fixture_artifact_dag_member_v1 member
          ON member.dag_id = ledger.dag_id
        WHERE ledger.ledger_id = NEW.ledger_id
          AND member.artifact_id = NEW.artifact_id
          AND member.content_sha256 = NEW.content_sha256
          AND member.semantic_ceiling = NEW.semantic_ceiling
    ) THEN RAISE(ABORT, 'Wave 6 decision evidence lacks exact DAG membership') END;
END;

CREATE TRIGGER no_update_wave6_fixture_decision_ledger_v1
BEFORE UPDATE ON wave6_fixture_decision_ledger_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_decision_ledger_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_fixture_decision_ledger_v1
BEFORE DELETE ON wave6_fixture_decision_ledger_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_decision_ledger_v1 is append-only'); END;

CREATE TRIGGER no_update_wave6_fixture_decision_v1
BEFORE UPDATE ON wave6_fixture_decision_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_decision_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_fixture_decision_v1
BEFORE DELETE ON wave6_fixture_decision_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_decision_v1 is append-only'); END;

CREATE TRIGGER no_update_wave6_fixture_decision_evidence_v1
BEFORE UPDATE ON wave6_fixture_decision_evidence_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_decision_evidence_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_fixture_decision_evidence_v1
BEFORE DELETE ON wave6_fixture_decision_evidence_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_decision_evidence_v1 is append-only'); END;
