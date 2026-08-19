-- Exact store receipt boundary for one browser-reported Cockpit V2 mount.
--
-- This table records evidence from an already authorized, read-only pairing session. It proves
-- durable receipt and exact headed-publication linkage only. It does not prove pixels were
-- visible, confer product qualification, or add wallet, signing, transaction, or execution
-- authority.

CREATE TABLE cockpit_v2_browser_presentation_v1 (
    client_presentation_id TEXT PRIMARY KEY CHECK (
        length(client_presentation_id) BETWEEN 1 AND 512
        AND client_presentation_id = trim(client_presentation_id)
    ),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(idempotency_key) BETWEEN 1 AND 512
        AND idempotency_key = trim(idempotency_key)
    ),
    browser_page_id TEXT NOT NULL CHECK (
        length(browser_page_id) BETWEEN 1 AND 512 AND browser_page_id = trim(browser_page_id)
    ),
    presentation_seq TEXT NOT NULL CHECK (
        presentation_seq NOT GLOB '*[^0-9]*'
        AND substr(presentation_seq, 1, 1) BETWEEN '1' AND '9'
    ),
    pairing_consumed_occurrence_id TEXT NOT NULL
        REFERENCES wave5_g0_pairing_occurrence_v1(pairing_occurrence_id),
    pairing_session_id TEXT NOT NULL CHECK (
        length(pairing_session_id) BETWEEN 1 AND 512
        AND pairing_session_id = trim(pairing_session_id)
    ),
    pairing_origin TEXT NOT NULL CHECK (
        length(pairing_origin) BETWEEN 1 AND 512 AND pairing_origin = trim(pairing_origin)
    ),
    pairing_epoch INTEGER NOT NULL CHECK (pairing_epoch > 0),
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
    source_occurrence_id TEXT NOT NULL
        REFERENCES wave5_source_occurrence_v1(source_occurrence_id),
    claim_contract TEXT NOT NULL CHECK (
        claim_contract = 'joshi.cockpit.v2.browser_presentation_claim'
    ),
    claim_schema_version INTEGER NOT NULL CHECK (claim_schema_version = 1),
    claim_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(claim_sha256) = 64 AND claim_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    claim_bytes_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(claim_bytes_sha256) = 64 AND claim_bytes_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    claim_bytes BLOB NOT NULL,
    claim_byte_length INTEGER NOT NULL CHECK (
        claim_byte_length > 0 AND length(claim_bytes) = claim_byte_length
    ),
    rendered_subject_count INTEGER NOT NULL CHECK (rendered_subject_count >= 0),
    mounted_wall_us INTEGER NOT NULL CHECK (mounted_wall_us > 0),
    client_clock_id TEXT NOT NULL CHECK (
        length(client_clock_id) BETWEEN 1 AND 512 AND client_clock_id = trim(client_clock_id)
    ),
    mounted_mono_ns TEXT NOT NULL CHECK (
        mounted_mono_ns = '0' OR (
            mounted_mono_ns NOT GLOB '*[^0-9]*'
            AND substr(mounted_mono_ns, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    viewport_width_css_px INTEGER NOT NULL CHECK (
        viewport_width_css_px BETWEEN 1 AND 32768
    ),
    viewport_height_css_px INTEGER NOT NULL CHECK (
        viewport_height_css_px BETWEEN 1 AND 32768
    ),
    device_pixel_ratio_milli INTEGER NOT NULL CHECK (
        device_pixel_ratio_milli BETWEEN 100 AND 10000
    ),
    document_visibility TEXT NOT NULL CHECK (document_visibility IN ('visible', 'hidden')),
    document_has_focus INTEGER NOT NULL CHECK (document_has_focus IN (0, 1)),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    ceiling TEXT NOT NULL CHECK (ceiling = 'browser_reported_not_pixel_verified'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    UNIQUE (browser_page_id, presentation_seq),
    CHECK (publication_commit_seq < head_commit_seq),
    CHECK (head_commit_seq < created_commit_seq)
) STRICT;

CREATE TRIGGER cockpit_v2_browser_presentation_closes_exact_claim
BEFORE INSERT ON cockpit_v2_browser_presentation_v1
BEGIN
    SELECT CASE WHEN json_extract(CAST(NEW.claim_bytes AS TEXT), '$.contract')
            <> NEW.claim_contract
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.schemaVersion')
            <> NEW.claim_schema_version
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.idempotencyKey')
            <> NEW.idempotency_key
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.clientPresentationId')
            <> NEW.client_presentation_id
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.browserPageId')
            <> NEW.browser_page_id
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.presentationSeq')
            <> NEW.presentation_seq
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.publication.publicationId')
            <> NEW.publication_id
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.publication.publicationDigest')
            <> 'sha256:' || NEW.publication_sha256
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.publication.publicationBytesDigest')
            <> 'sha256:' || NEW.publication_bytes_sha256
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.publication.publicationCommitSeq')
            <> CAST(NEW.publication_commit_seq AS TEXT)
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.head.headDigest')
            <> 'sha256:' || NEW.head_sha256
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.head.headBytesDigest')
            <> 'sha256:' || NEW.head_bytes_sha256
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.head.headCommitSeq')
            <> CAST(NEW.head_commit_seq AS TEXT)
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.sourceOccurrenceId')
            <> NEW.source_occurrence_id
        OR json_array_length(CAST(NEW.claim_bytes AS TEXT), '$.renderedSubjects')
            <> NEW.rendered_subject_count
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.clientClockId')
            <> NEW.client_clock_id
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.monotonicNs')
            <> NEW.mounted_mono_ns
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.viewport.widthCssPx')
            <> CAST(NEW.viewport_width_css_px AS TEXT)
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.viewport.heightCssPx')
            <> CAST(NEW.viewport_height_css_px AS TEXT)
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.viewport.devicePixelRatioMilli')
            <> CAST(NEW.device_pixel_ratio_milli AS TEXT)
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.documentVisibility')
            <> NEW.document_visibility
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.documentHasFocus')
            <> NEW.document_has_focus
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.authority') <> NEW.authority
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.ceiling') <> NEW.ceiling
        OR json_extract(CAST(NEW.claim_bytes AS TEXT), '$.claimDigest')
            <> 'sha256:' || NEW.claim_sha256
    THEN RAISE(ABORT, 'browser presentation row differs from exact claim bytes') END;

    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM cockpit_v2_publication_v1 publication
        JOIN cockpit_v2_head_v1 head ON head.publication_id = publication.publication_id
        JOIN cockpit_v2_preparation_v1 preparation
          ON preparation.preparation_id = publication.preparation_id
        WHERE publication.publication_id = NEW.publication_id
          AND publication.source_occurrence_id = NEW.source_occurrence_id
          AND publication.publication_sha256 = NEW.publication_sha256
          AND publication.publication_bytes_sha256 = NEW.publication_bytes_sha256
          AND publication.created_commit_seq = NEW.publication_commit_seq
          AND head.source_occurrence_id = NEW.source_occurrence_id
          AND head.head_sha256 = NEW.head_sha256
          AND head.created_commit_seq = NEW.head_commit_seq
          AND preparation.knowledge_wall_us <= NEW.mounted_wall_us
    ) THEN RAISE(ABORT, 'browser presentation does not close exact headed publication') END;

    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave5_g0_pairing_occurrence_v1 consumed
        JOIN ingest_commit current_commit ON current_commit.commit_seq = NEW.created_commit_seq
        WHERE consumed.pairing_occurrence_id = NEW.pairing_consumed_occurrence_id
          AND consumed.occurrence_kind = 'consumed'
          AND consumed.session_id = NEW.pairing_session_id
          AND consumed.origin = NEW.pairing_origin
          AND consumed.epoch = NEW.pairing_epoch
          AND consumed.observed_wall_us <= NEW.mounted_wall_us
          AND NEW.mounted_wall_us <= current_commit.committed_wall_us
          AND consumed.expires_wall_us >= current_commit.committed_wall_us
          AND consumed.created_commit_seq < NEW.created_commit_seq
          AND EXISTS (
              SELECT 1 FROM json_each(consumed.scopes_json)
              WHERE value = 'presentation_evidence_write'
          )
          AND NOT EXISTS (
              SELECT 1 FROM wave5_g0_pairing_occurrence_v1 terminal
              WHERE terminal.predecessor_occurrence_id = consumed.pairing_occurrence_id
                AND terminal.occurrence_kind IN ('revoked', 'expired', 'restart_invalidated')
                AND terminal.created_commit_seq <= NEW.created_commit_seq
          )
    ) THEN RAISE(ABORT, 'browser presentation lacks an active exact paired write session') END;
END;

CREATE TRIGGER no_update_cockpit_v2_browser_presentation_v1
BEFORE UPDATE ON cockpit_v2_browser_presentation_v1
BEGIN SELECT RAISE(ABORT, 'cockpit_v2_browser_presentation_v1 is append-only'); END;

CREATE TRIGGER no_delete_cockpit_v2_browser_presentation_v1
BEFORE DELETE ON cockpit_v2_browser_presentation_v1
BEGIN SELECT RAISE(ABORT, 'cockpit_v2_browser_presentation_v1 is append-only'); END;
