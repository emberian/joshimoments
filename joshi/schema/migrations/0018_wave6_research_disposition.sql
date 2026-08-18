-- Caller-fed fixture research disposition bound to an exact prior durable proposal.
--
-- Persistence does not authenticate the reviewer or confer approval, execution, or result authority.

CREATE TABLE wave6_fixture_research_disposition_v1 (
    disposition_id TEXT PRIMARY KEY CHECK (
        length(disposition_id) BETWEEN 1 AND 127 AND disposition_id = trim(disposition_id)
    ),
    proposal_id TEXT NOT NULL REFERENCES wave6_fixture_research_proposal_v1(proposal_id),
    proposal_semantic_sha256 TEXT NOT NULL CHECK (
        length(proposal_semantic_sha256) = 64
        AND proposal_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    proposal_content_sha256 TEXT NOT NULL CHECK (
        length(proposal_content_sha256) = 64
        AND proposal_content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    disposition_kind TEXT NOT NULL CHECK (
        disposition_kind IN ('accept','reject','hold','supersede')
    ),
    reviewer_id TEXT NOT NULL CHECK (
        length(reviewer_id) BETWEEN 1 AND 512 AND reviewer_id = trim(reviewer_id)
    ),
    decided_at TEXT NOT NULL CHECK (
        length(decided_at) = 27 AND substr(decided_at, 27, 1) = 'Z'
    ),
    reason TEXT NOT NULL CHECK (
        length(reason) BETWEEN 1 AND 2000 AND reason = trim(reason)
    ),
    disposition_content_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(disposition_content_sha256) = 64
        AND disposition_content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    disposition_bytes BLOB NOT NULL,
    disposition_byte_length INTEGER NOT NULL CHECK (
        disposition_byte_length > 0 AND length(disposition_bytes) = disposition_byte_length
    ),
    identity_authority TEXT NOT NULL CHECK (
        identity_authority = 'caller_fed_fixture_unverified'
    ),
    human_review_verified INTEGER NOT NULL CHECK (human_review_verified = 0),
    approval_authority INTEGER NOT NULL CHECK (approval_authority = 0),
    execution_authority INTEGER NOT NULL CHECK (execution_authority = 0),
    result_authority INTEGER NOT NULL CHECK (result_authority = 0),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TRIGGER wave6_fixture_research_disposition_matches_prior_proposal
BEFORE INSERT ON wave6_fixture_research_disposition_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave6_fixture_research_proposal_v1 proposal
        WHERE proposal.proposal_id = NEW.proposal_id
          AND proposal.proposal_semantic_sha256 = NEW.proposal_semantic_sha256
          AND proposal.content_sha256 = NEW.proposal_content_sha256
          AND proposal.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'Wave 6 research disposition lacks its exact prior proposal') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.created_commit_seq
          AND commit_row.commit_class = 'maintenance'
    ) THEN RAISE(ABORT, 'Wave 6 research disposition lacks a store maintenance commit') END;
END;

CREATE TRIGGER no_update_wave6_fixture_research_disposition_v1
BEFORE UPDATE ON wave6_fixture_research_disposition_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_research_disposition_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_fixture_research_disposition_v1
BEFORE DELETE ON wave6_fixture_research_disposition_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_research_disposition_v1 is append-only'); END;
