-- Store-resolved Wave 5 operator-evidence input exposed to the Wave 6 fixture program.
--
-- This bridge retains one exact discovery census, committed scene, durable operator act and later
-- browser-reported presentation claim. It deliberately preserves the act's original presentation
-- gap and confers no human-viewing, recognition, operator-model, product, or execution authority.

CREATE TABLE wave6_operator_evidence_input_v1 (
    binding_id TEXT PRIMARY KEY CHECK (
        length(binding_id) BETWEEN 1 AND 127 AND binding_id = trim(binding_id)
    ),
    program_id TEXT NOT NULL UNIQUE REFERENCES wave6_program_registration_v1(program_id),
    input_census_binding_id TEXT NOT NULL UNIQUE
        REFERENCES wave6_store_input_census_v1(binding_id),
    source_occurrence_id TEXT NOT NULL
        REFERENCES wave5_source_occurrence_v1(source_occurrence_id),
    publication_id TEXT NOT NULL REFERENCES cockpit_v2_publication_v1(publication_id),
    publication_sha256 TEXT NOT NULL CHECK (
        length(publication_sha256) = 64 AND publication_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    publication_bytes_sha256 TEXT NOT NULL CHECK (
        length(publication_bytes_sha256) = 64
        AND publication_bytes_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    publication_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    head_sha256 TEXT NOT NULL CHECK (
        length(head_sha256) = 64 AND head_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    head_bytes_sha256 TEXT NOT NULL CHECK (
        length(head_bytes_sha256) = 64 AND head_bytes_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    head_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    memory_occurrence_id TEXT NOT NULL UNIQUE
        REFERENCES scientific_memory_occurrence_v1(occurrence_id),
    memory_occurrence_sha256 TEXT NOT NULL CHECK (
        length(memory_occurrence_sha256) = 64
        AND memory_occurrence_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    memory_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    memory_queue_generation INTEGER NOT NULL CHECK (memory_queue_generation > 0),
    presentation_claim_id TEXT NOT NULL UNIQUE
        REFERENCES cockpit_v2_browser_presentation_v1(client_presentation_id),
    presentation_claim_sha256 TEXT NOT NULL CHECK (
        length(presentation_claim_sha256) = 64
        AND presentation_claim_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    presentation_claim_bytes_sha256 TEXT NOT NULL CHECK (
        length(presentation_claim_bytes_sha256) = 64
        AND presentation_claim_bytes_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    presentation_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    pairing_session_id TEXT NOT NULL CHECK (
        length(pairing_session_id) BETWEEN 1 AND 512 AND pairing_session_id = trim(pairing_session_id)
    ),
    subject_id TEXT NOT NULL CHECK (
        length(subject_id) BETWEEN 1 AND 512 AND subject_id = trim(subject_id)
    ),
    document_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(document_sha256) = 64 AND document_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    document_bytes BLOB NOT NULL,
    document_byte_length INTEGER NOT NULL CHECK (
        document_byte_length > 0 AND length(document_bytes) = document_byte_length
    ),
    act_presentation_gap_retained INTEGER NOT NULL CHECK (act_presentation_gap_retained = 1),
    presentation_repairs_act_gap INTEGER NOT NULL CHECK (presentation_repairs_act_gap = 0),
    session_equivalence_claimed INTEGER NOT NULL CHECK (session_equivalence_claimed = 0),
    human_viewing_verified INTEGER NOT NULL CHECK (human_viewing_verified = 0),
    recognition_observed INTEGER NOT NULL CHECK (recognition_observed = 0),
    operator_model_resolved INTEGER NOT NULL CHECK (operator_model_resolved = 0),
    authority TEXT NOT NULL CHECK (authority = 'read_record_replay_propose_shadow_only'),
    claim_scope TEXT NOT NULL CHECK (
        claim_scope =
          'store_resolved_act_gap_and_later_browser_report_not_human_recognition_or_operator_model'
    ),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'store_resolved_operator_evidence_input_only'
    ),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    CHECK (publication_commit_seq < head_commit_seq),
    CHECK (head_commit_seq < memory_commit_seq),
    CHECK (memory_commit_seq < presentation_commit_seq),
    CHECK (presentation_commit_seq < created_commit_seq)
) STRICT;

CREATE TRIGGER wave6_operator_evidence_input_closes_exact_document
BEFORE INSERT ON wave6_operator_evidence_input_v1
BEGIN
    SELECT CASE WHEN json_extract(CAST(NEW.document_bytes AS TEXT), '$.contract')
            <> 'joshi.store.wave6.operator-evidence-input.v1'
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.schemaVersion') <> 1
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.bindingId') <> NEW.binding_id
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.programId') <> NEW.program_id
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.inputCensusBindingId')
            <> NEW.input_census_binding_id
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.sourceOccurrenceId')
            <> NEW.source_occurrence_id
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.publicationId')
            <> NEW.publication_id
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.publicationDigest')
            <> 'sha256:' || NEW.publication_sha256
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.publicationBytesDigest')
            <> 'sha256:' || NEW.publication_bytes_sha256
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.publicationCommitSeq')
            <> CAST(NEW.publication_commit_seq AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.headDigest')
            <> 'sha256:' || NEW.head_sha256
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.headBytesDigest')
            <> 'sha256:' || NEW.head_bytes_sha256
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.headCommitSeq')
            <> CAST(NEW.head_commit_seq AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.memoryOccurrenceId')
            <> NEW.memory_occurrence_id
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.memoryOccurrenceDigest')
            <> 'sha256:' || NEW.memory_occurrence_sha256
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.memoryCommitSeq')
            <> CAST(NEW.memory_commit_seq AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.memoryQueueGeneration')
            <> CAST(NEW.memory_queue_generation AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.presentationClaimId')
            <> NEW.presentation_claim_id
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.presentationClaimDigest')
            <> 'sha256:' || NEW.presentation_claim_sha256
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.presentationClaimBytesDigest')
            <> 'sha256:' || NEW.presentation_claim_bytes_sha256
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.presentationCommitSeq')
            <> CAST(NEW.presentation_commit_seq AS TEXT)
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.pairingSessionId')
            <> NEW.pairing_session_id
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.subjectId') <> NEW.subject_id
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.actPresentationGapRetained') <> 1
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.presentationRepairsActGap') <> 0
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.sessionEquivalenceClaimed') <> 0
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.humanViewingVerified') <> 0
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.recognitionObserved') <> 0
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.operatorModelResolved') <> 0
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.authority') <> NEW.authority
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.claimScope') <> NEW.claim_scope
        OR json_extract(CAST(NEW.document_bytes AS TEXT), '$.semanticCeiling')
            <> NEW.semantic_ceiling
    THEN RAISE(ABORT, 'Wave 6 operator-evidence input row differs from exact store-built bytes') END;

    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave6_store_input_census_v1 census
        WHERE census.binding_id = NEW.input_census_binding_id
          AND census.program_id = NEW.program_id
          AND census.source_occurrence_id = NEW.source_occurrence_id
          AND census.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'operator-evidence input lacks its exact prior census') END;

    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM cockpit_v2_publication_v1 publication
        JOIN cockpit_v2_head_v1 head ON head.publication_id = publication.publication_id
        WHERE publication.publication_id = NEW.publication_id
          AND publication.source_occurrence_id = NEW.source_occurrence_id
          AND publication.publication_sha256 = NEW.publication_sha256
          AND publication.publication_bytes_sha256 = NEW.publication_bytes_sha256
          AND publication.created_commit_seq = NEW.publication_commit_seq
          AND head.head_sha256 = NEW.head_sha256
          AND head.created_commit_seq = NEW.head_commit_seq
    ) THEN RAISE(ABORT, 'operator-evidence input lacks its exact headed publication') END;

    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM scientific_memory_occurrence_v1 memory
        WHERE memory.occurrence_id = NEW.memory_occurrence_id
          AND memory.occurrence_kind = 'operator_act'
          AND memory.scene_publication_id = NEW.publication_id
          AND memory.occurrence_sha256 = NEW.memory_occurrence_sha256
          AND memory.queue_generation = NEW.memory_queue_generation
          AND memory.created_commit_seq = NEW.memory_commit_seq
    ) THEN RAISE(ABORT, 'operator-evidence input lacks its exact prior act') END;

    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM cockpit_v2_browser_presentation_v1 presentation
        WHERE presentation.client_presentation_id = NEW.presentation_claim_id
          AND presentation.publication_id = NEW.publication_id
          AND presentation.source_occurrence_id = NEW.source_occurrence_id
          AND presentation.claim_sha256 = NEW.presentation_claim_sha256
          AND presentation.claim_bytes_sha256 = NEW.presentation_claim_bytes_sha256
          AND presentation.pairing_session_id = NEW.pairing_session_id
          AND presentation.created_commit_seq = NEW.presentation_commit_seq
    ) THEN RAISE(ABORT, 'operator-evidence input lacks its exact later presentation claim') END;

    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.created_commit_seq
          AND commit_row.commit_class = 'maintenance'
    ) THEN RAISE(ABORT, 'operator-evidence input lacks a store maintenance commit') END;
END;

CREATE TRIGGER no_update_wave6_operator_evidence_input_v1
BEFORE UPDATE ON wave6_operator_evidence_input_v1
BEGIN SELECT RAISE(ABORT, 'wave6_operator_evidence_input_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_operator_evidence_input_v1
BEFORE DELETE ON wave6_operator_evidence_input_v1
BEGIN SELECT RAISE(ABORT, 'wave6_operator_evidence_input_v1 is append-only'); END;
