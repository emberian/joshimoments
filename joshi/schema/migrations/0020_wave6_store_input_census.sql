-- Store-resolved Wave 5 input census exposed to the Wave 6 fixture program.
--
-- This bridge retains the complete, reverified Wave 5 source occurrence. It does not transform
-- those discovery facts into a Wave 6 market atlas and confers no field-release, empirical,
-- causal, strategy, product, execution, provider, or external-mutation authority.

CREATE TABLE wave6_store_input_census_v1 (
    binding_id TEXT PRIMARY KEY CHECK (
        length(binding_id) BETWEEN 1 AND 127 AND binding_id = trim(binding_id)
    ),
    program_id TEXT NOT NULL UNIQUE REFERENCES wave6_program_registration_v1(program_id),
    source_occurrence_id TEXT NOT NULL
        REFERENCES wave5_source_occurrence_v1(source_occurrence_id),
    source_descriptor_sha256 TEXT NOT NULL CHECK (
        length(source_descriptor_sha256) = 64
        AND source_descriptor_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    source_created_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    source_known_through_commit_seq INTEGER NOT NULL CHECK (
        source_known_through_commit_seq > 0
    ),
    document_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(document_sha256) = 64 AND document_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    document_bytes BLOB NOT NULL,
    document_byte_length INTEGER NOT NULL CHECK (
        document_byte_length > 0 AND length(document_bytes) = document_byte_length
    ),
    fact_count INTEGER NOT NULL CHECK (fact_count > 0),
    eligible_subject_count INTEGER NOT NULL CHECK (eligible_subject_count > 0),
    membership_count INTEGER NOT NULL CHECK (
        membership_count = eligible_subject_count
    ),
    coverage_count INTEGER NOT NULL CHECK (coverage_count > 0),
    gap_count INTEGER NOT NULL CHECK (gap_count >= 0),
    hot_subject_count INTEGER NOT NULL CHECK (hot_subject_count > 0),
    cold_control_subject_count INTEGER NOT NULL CHECK (cold_control_subject_count > 0),
    store_resolved_source INTEGER NOT NULL CHECK (store_resolved_source = 1),
    market_atlas_resolved INTEGER NOT NULL CHECK (market_atlas_resolved = 0),
    authority TEXT NOT NULL CHECK (authority = 'read_record_replay_propose_shadow_only'),
    claim_scope TEXT NOT NULL CHECK (
        claim_scope =
          'mint_discovery_input_census_not_market_atlas_field_release_causal_strategy_or_execution'
    ),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'store_resolved_offline_fixture_input_census_only'
    ),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    UNIQUE (program_id, source_occurrence_id)
) STRICT;

CREATE TRIGGER wave6_store_input_census_closes_exact_document
BEFORE INSERT ON wave6_store_input_census_v1
BEGIN
    SELECT CASE WHEN json_extract(CAST(NEW.document_bytes AS TEXT), '$.contract')
            <> 'joshi.store.wave6.input-census.v1'
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.schemaVersion') <> 1
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.bindingId') <> NEW.binding_id
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.programId') <> NEW.program_id
        OR json_extract(
            CAST(NEW.document_bytes AS TEXT), '$.sourceOccurrence.sourceOccurrenceId'
        ) <> NEW.source_occurrence_id
        OR json_extract(
            CAST(NEW.document_bytes AS TEXT), '$.sourceDescriptorDigest'
        ) <> 'sha256:' || NEW.source_descriptor_sha256
        OR json_extract(
            CAST(NEW.document_bytes AS TEXT), '$.sourceCreatedCommitSeq'
        ) <> CAST(NEW.source_created_commit_seq AS TEXT)
        OR json_extract(
            CAST(NEW.document_bytes AS TEXT),
            '$.sourceOccurrence.knownThroughCommitSeq'
        ) <> CAST(NEW.source_known_through_commit_seq AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.factCount')
            <> CAST(NEW.fact_count AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.eligibleSubjectCount')
            <> CAST(NEW.eligible_subject_count AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.membershipCount')
            <> CAST(NEW.membership_count AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.coverageCount')
            <> CAST(NEW.coverage_count AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.gapCount')
            <> CAST(NEW.gap_count AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.hotSubjectCount')
            <> CAST(NEW.hot_subject_count AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.coldControlSubjectCount')
            <> CAST(NEW.cold_control_subject_count AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.storeResolvedSource') <> 1
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.marketAtlasResolved') <> 0
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.authority') <> NEW.authority
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.claimScope') <> NEW.claim_scope
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.semanticCeiling')
            <> NEW.semantic_ceiling
    THEN RAISE(ABORT, 'Wave 6 input census row differs from exact store-built bytes') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave6_program_registration_v1 program
        WHERE program.program_id = NEW.program_id
          AND program.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'Wave 6 input census lacks its exact prior program') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_source_occurrence_v1 source
        WHERE source.source_occurrence_id = NEW.source_occurrence_id
          AND source.descriptor_sha256 = NEW.source_descriptor_sha256
          AND source.created_commit_seq = NEW.source_created_commit_seq
          AND source.known_through_commit_seq = NEW.source_known_through_commit_seq
          AND source.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'Wave 6 input census lacks its exact prior source occurrence') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.created_commit_seq
          AND commit_row.commit_class = 'maintenance'
    ) THEN RAISE(ABORT, 'Wave 6 input census lacks a store maintenance commit') END;
END;

CREATE TRIGGER no_update_wave6_store_input_census_v1
BEFORE UPDATE ON wave6_store_input_census_v1
BEGIN SELECT RAISE(ABORT, 'wave6_store_input_census_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_store_input_census_v1
BEFORE DELETE ON wave6_store_input_census_v1
BEGIN SELECT RAISE(ABORT, 'wave6_store_input_census_v1 is append-only'); END;
