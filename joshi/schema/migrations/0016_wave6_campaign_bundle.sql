-- Exact five-document caller-fed Wave 6 campaign fixture bundles.
--
-- One bundle commit is not a prospective campaign journal. Its phase clocks, alleged commit
-- sequences, evidence, assignments, outcomes and dispositions remain checked fixture material.

CREATE TABLE wave6_fixture_campaign_bundle_v1 (
    bundle_id TEXT PRIMARY KEY CHECK (
        length(bundle_id) BETWEEN 1 AND 127 AND bundle_id = trim(bundle_id)
    ),
    program_id TEXT NOT NULL REFERENCES wave6_program_registration_v1(program_id),
    program_registration_sha256 TEXT NOT NULL CHECK (
        length(program_registration_sha256) = 64
        AND program_registration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    campaign_id TEXT NOT NULL UNIQUE CHECK (
        length(campaign_id) BETWEEN 1 AND 127 AND campaign_id = trim(campaign_id)
    ),
    registration_semantic_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(registration_semantic_sha256) = 64
        AND registration_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    registration_document_sha256 TEXT NOT NULL CHECK (
        length(registration_document_sha256) = 64
        AND registration_document_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    registration_bytes BLOB NOT NULL,
    registration_byte_length INTEGER NOT NULL CHECK (
        registration_byte_length > 0 AND length(registration_bytes) = registration_byte_length
    ),
    enrollment_id TEXT NOT NULL UNIQUE CHECK (
        length(enrollment_id) BETWEEN 1 AND 127 AND enrollment_id = trim(enrollment_id)
    ),
    enrollment_semantic_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(enrollment_semantic_sha256) = 64
        AND enrollment_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    enrollment_document_sha256 TEXT NOT NULL CHECK (
        length(enrollment_document_sha256) = 64
        AND enrollment_document_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    enrollment_bytes BLOB NOT NULL,
    enrollment_byte_length INTEGER NOT NULL CHECK (
        enrollment_byte_length > 0 AND length(enrollment_bytes) = enrollment_byte_length
    ),
    assignment_id TEXT NOT NULL UNIQUE CHECK (
        length(assignment_id) BETWEEN 1 AND 127 AND assignment_id = trim(assignment_id)
    ),
    assignment_semantic_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(assignment_semantic_sha256) = 64
        AND assignment_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    assignment_document_sha256 TEXT NOT NULL CHECK (
        length(assignment_document_sha256) = 64
        AND assignment_document_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    assignment_bytes BLOB NOT NULL,
    assignment_byte_length INTEGER NOT NULL CHECK (
        assignment_byte_length > 0 AND length(assignment_bytes) = assignment_byte_length
    ),
    seal_id TEXT NOT NULL UNIQUE CHECK (
        length(seal_id) BETWEEN 1 AND 127 AND seal_id = trim(seal_id)
    ),
    seal_semantic_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(seal_semantic_sha256) = 64
        AND seal_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    seal_document_sha256 TEXT NOT NULL CHECK (
        length(seal_document_sha256) = 64
        AND seal_document_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    seal_bytes BLOB NOT NULL,
    seal_byte_length INTEGER NOT NULL CHECK (
        seal_byte_length > 0 AND length(seal_bytes) = seal_byte_length
    ),
    adjudication_id TEXT NOT NULL UNIQUE CHECK (
        length(adjudication_id) BETWEEN 1 AND 127 AND adjudication_id = trim(adjudication_id)
    ),
    adjudication_semantic_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(adjudication_semantic_sha256) = 64
        AND adjudication_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    adjudication_document_sha256 TEXT NOT NULL CHECK (
        length(adjudication_document_sha256) = 64
        AND adjudication_document_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    adjudication_bytes BLOB NOT NULL,
    adjudication_byte_length INTEGER NOT NULL CHECK (
        adjudication_byte_length > 0 AND length(adjudication_bytes) = adjudication_byte_length
    ),
    bundle_document_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(bundle_document_sha256) = 64
        AND bundle_document_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    eligible_subject_count INTEGER NOT NULL CHECK (eligible_subject_count > 0),
    included_subject_count INTEGER NOT NULL CHECK (
        included_subject_count > 0 AND included_subject_count <= eligible_subject_count
    ),
    assignment_count INTEGER NOT NULL CHECK (assignment_count = included_subject_count),
    outcome_count INTEGER NOT NULL CHECK (outcome_count = included_subject_count),
    maximum_fixture_alleged_commit_seq INTEGER NOT NULL CHECK (
        maximum_fixture_alleged_commit_seq > 0
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_record_replay_propose_shadow_only'),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TRIGGER wave6_fixture_campaign_bundle_matches_program_schema
BEFORE INSERT ON wave6_fixture_campaign_bundle_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave6_program_registration_v1 registration
        JOIN wave6_registered_artifact_schema_v1 schema_row
          ON schema_row.program_id = registration.program_id
        WHERE registration.program_id = NEW.program_id
          AND registration.registration_semantic_sha256 = NEW.program_registration_sha256
          AND registration.semantic_ceiling = NEW.semantic_ceiling
          AND schema_row.kind_id = 'campaign_registration_fixture'
          AND schema_row.schema_id = 'joshi.wave6.campaign-registration.v1'
          AND schema_row.semantic_ceiling = NEW.semantic_ceiling
          AND schema_row.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'Wave 6 campaign bundle lacks its exact prior program/schema') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.created_commit_seq
          AND commit_row.commit_class = 'maintenance'
    ) THEN RAISE(ABORT, 'Wave 6 campaign bundle lacks a store maintenance commit') END;
END;

CREATE TRIGGER no_update_wave6_fixture_campaign_bundle_v1
BEFORE UPDATE ON wave6_fixture_campaign_bundle_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_campaign_bundle_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_fixture_campaign_bundle_v1
BEFORE DELETE ON wave6_fixture_campaign_bundle_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_campaign_bundle_v1 is append-only'); END;
