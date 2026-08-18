-- Exact, non-executable Wave 6 research proposal over prior durable fixture evaluations.
--
-- Durability does not confer human review, execution, result, release, or claim authority.

CREATE TABLE wave6_fixture_research_proposal_v1 (
    proposal_id TEXT PRIMARY KEY CHECK (
        length(proposal_id) BETWEEN 1 AND 127 AND proposal_id = trim(proposal_id)
    ),
    program_id TEXT NOT NULL REFERENCES wave6_program_registration_v1(program_id),
    program_registration_sha256 TEXT NOT NULL CHECK (
        length(program_registration_sha256) = 64
        AND program_registration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    kind_id TEXT NOT NULL CHECK (kind_id = 'research_proposal_fixture'),
    schema_id TEXT NOT NULL CHECK (schema_id = 'joshi.analysis.wave6-research-desk/v1'),
    schema_sha256 TEXT NOT NULL CHECK (
        length(schema_sha256) = 64 AND schema_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    schema_created_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    proposal_semantic_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(proposal_semantic_sha256) = 64
        AND proposal_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    content_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    commitment_sha256 TEXT NOT NULL CHECK (
        length(commitment_sha256) = 64 AND commitment_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    policy_sha256 TEXT NOT NULL CHECK (
        length(policy_sha256) = 64 AND policy_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    evidence_closure_sha256 TEXT NOT NULL CHECK (
        length(evidence_closure_sha256) = 64
        AND evidence_closure_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    proposal_bytes BLOB NOT NULL,
    proposal_byte_length INTEGER NOT NULL CHECK (
        proposal_byte_length > 0 AND length(proposal_bytes) = proposal_byte_length
    ),
    descriptor_count INTEGER NOT NULL CHECK (descriptor_count > 0),
    counterexample_count INTEGER NOT NULL CHECK (counterexample_count > 0),
    experiment_count INTEGER NOT NULL CHECK (experiment_count > 0),
    total_experiment_units INTEGER NOT NULL CHECK (total_experiment_units > 0),
    maximum_fixture_alleged_commit_seq INTEGER NOT NULL CHECK (
        maximum_fixture_alleged_commit_seq > 0
    ),
    maximum_resolved_artifact_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    authority TEXT NOT NULL CHECK (
        authority = 'read_only_proposal_only_no_query_no_glass_no_action_no_claim_promotion'
    ),
    claim_scope TEXT NOT NULL CHECK (
        claim_scope = 'research_design_proposal_not_result_or_live_decision'
    ),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    FOREIGN KEY (program_id, kind_id)
        REFERENCES wave6_registered_artifact_schema_v1(program_id, kind_id)
) STRICT;

CREATE TABLE wave6_fixture_research_proposal_artifact_v1 (
    proposal_id TEXT NOT NULL REFERENCES wave6_fixture_research_proposal_v1(proposal_id),
    descriptor_ordinal INTEGER NOT NULL CHECK (descriptor_ordinal >= 0),
    descriptor_artifact_id TEXT NOT NULL CHECK (
        length(descriptor_artifact_id) BETWEEN 1 AND 127
        AND descriptor_artifact_id = trim(descriptor_artifact_id)
    ),
    provenance_sha256 TEXT NOT NULL CHECK (
        length(provenance_sha256) = 64 AND provenance_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    resolved_artifact_id TEXT NOT NULL REFERENCES wave6_fixture_artifact_content_v1(artifact_id),
    resolved_kind_id TEXT NOT NULL CHECK (
        resolved_kind_id IN (
            'known_truth_evaluation_fixture',
            'protocol_known_truth_evaluation_fixture',
            'structural_known_truth_evaluation_fixture'
        )
    ),
    fixture_alleged_commit_seq INTEGER NOT NULL CHECK (fixture_alleged_commit_seq > 0),
    resolved_artifact_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    role TEXT NOT NULL CHECK (role = 'design'),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    PRIMARY KEY (proposal_id, descriptor_ordinal),
    UNIQUE (proposal_id, descriptor_artifact_id),
    UNIQUE (proposal_id, resolved_artifact_id)
) STRICT;

CREATE TRIGGER wave6_fixture_research_proposal_matches_prior_schema
BEFORE INSERT ON wave6_fixture_research_proposal_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave6_program_registration_v1 registration
        JOIN wave6_registered_artifact_schema_v1 schema_row
          ON schema_row.program_id = registration.program_id
        WHERE registration.program_id = NEW.program_id
          AND registration.registration_semantic_sha256 = NEW.program_registration_sha256
          AND schema_row.kind_id = NEW.kind_id
          AND schema_row.schema_id = NEW.schema_id
          AND schema_row.schema_sha256 = NEW.schema_sha256
          AND schema_row.created_commit_seq = NEW.schema_created_commit_seq
          AND schema_row.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'Wave 6 research proposal lacks its exact prior program/schema') END;
    SELECT CASE WHEN NEW.maximum_resolved_artifact_commit_seq >= NEW.created_commit_seq
        THEN RAISE(ABORT, 'Wave 6 research proposal does not follow its resolved artifacts') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.created_commit_seq
          AND commit_row.commit_class = 'maintenance'
    ) THEN RAISE(ABORT, 'Wave 6 research proposal lacks a store maintenance commit') END;
END;

CREATE TRIGGER wave6_fixture_research_descriptor_matches_prior_artifact
BEFORE INSERT ON wave6_fixture_research_proposal_artifact_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave6_fixture_research_proposal_v1 proposal
        JOIN wave6_fixture_artifact_content_v1 artifact
          ON artifact.artifact_id = NEW.resolved_artifact_id
        WHERE proposal.proposal_id = NEW.proposal_id
          AND artifact.program_id = proposal.program_id
          AND artifact.kind_id = NEW.resolved_kind_id
          AND artifact.evaluation_semantic_sha256 = NEW.provenance_sha256
          AND artifact.created_commit_seq = NEW.resolved_artifact_commit_seq
          AND artifact.created_commit_seq < proposal.created_commit_seq
    ) THEN RAISE(ABORT, 'Wave 6 research descriptor lacks its exact prior evaluation artifact') END;
END;

CREATE TRIGGER no_update_wave6_fixture_research_proposal_v1
BEFORE UPDATE ON wave6_fixture_research_proposal_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_research_proposal_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_fixture_research_proposal_v1
BEFORE DELETE ON wave6_fixture_research_proposal_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_research_proposal_v1 is append-only'); END;

CREATE TRIGGER no_update_wave6_fixture_research_proposal_artifact_v1
BEFORE UPDATE ON wave6_fixture_research_proposal_artifact_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_research_proposal_artifact_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_fixture_research_proposal_artifact_v1
BEFORE DELETE ON wave6_fixture_research_proposal_artifact_v1
BEGIN SELECT RAISE(ABORT, 'wave6_fixture_research_proposal_artifact_v1 is append-only'); END;
