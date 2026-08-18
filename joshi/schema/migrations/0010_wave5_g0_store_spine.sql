-- Wave 5 G0 sole-store authority spine.
--
-- This forward-only migration retains exact store-resolved C0 source descriptors, immutable
-- Cockpit V2 prepare/body/head stages, fixture-authority scientific-memory occurrences, pairing
-- journal transitions, and backup occurrences.  It adds no provider, wallet, signer, transaction,
-- submission, trading, or liquidity authority. SHA-256 values omit the `sha256:` wire prefix.

CREATE TABLE wave5_source_occurrence_v1 (
    source_occurrence_id TEXT PRIMARY KEY CHECK (
        length(source_occurrence_id) BETWEEN 1 AND 512
        AND source_occurrence_id = trim(source_occurrence_id)
    ),
    run_registration_id TEXT NOT NULL
        REFERENCES wave5_run_registration_v1(run_registration_id),
    catalog_admission_id TEXT NOT NULL UNIQUE
        REFERENCES wave5_spool_catalog_binding_v1(catalog_admission_id),
    source_id TEXT NOT NULL REFERENCES source(source_id),
    receipt_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(receipt_sha256) = 64 AND receipt_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    descriptor_contract TEXT NOT NULL CHECK (
        descriptor_contract = 'joshi.store.wave5.source_occurrence.v1'
    ),
    descriptor_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(descriptor_sha256) = 64 AND descriptor_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    descriptor_bytes BLOB NOT NULL,
    descriptor_byte_length INTEGER NOT NULL CHECK (
        descriptor_byte_length > 0 AND length(descriptor_bytes) = descriptor_byte_length
    ),
    surface_profile_sha256 TEXT NOT NULL CHECK (
        length(surface_profile_sha256) = 64
        AND surface_profile_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    fact_count INTEGER NOT NULL CHECK (fact_count > 0),
    eligible_subject_count INTEGER NOT NULL CHECK (eligible_subject_count > 0),
    membership_count INTEGER NOT NULL CHECK (membership_count > 0),
    coverage_count INTEGER NOT NULL CHECK (coverage_count > 0),
    gap_count INTEGER NOT NULL CHECK (gap_count >= 0),
    rendered_subject_count INTEGER NOT NULL CHECK (rendered_subject_count > 0),
    omission_count INTEGER NOT NULL CHECK (omission_count > 0),
    hot_subject_count INTEGER NOT NULL CHECK (hot_subject_count > 0),
    cold_control_subject_count INTEGER NOT NULL CHECK (cold_control_subject_count > 0),
    known_through_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    maximum_input_available_wall_us INTEGER NOT NULL CHECK (
        maximum_input_available_wall_us > 0
    ),
    protection_class TEXT NOT NULL CHECK (protection_class = 'public_integrity'),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    CHECK (known_through_commit_seq < created_commit_seq)
) STRICT;

CREATE TRIGGER wave5_source_occurrence_closes_exact_c0
BEFORE INSERT ON wave5_source_occurrence_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave5_spool_catalog_binding_v1 b
        JOIN spool_catalog_admission s
          ON s.segment_id = b.segment_id AND s.batch_id = b.batch_id
        JOIN observation o ON o.commit_seq = s.store_commit_seq
        WHERE b.catalog_admission_id = NEW.catalog_admission_id
          AND b.run_registration_id = NEW.run_registration_id
          AND s.receipt_sha256 = NEW.receipt_sha256
          AND s.protection_class = NEW.protection_class
          AND s.store_commit_seq = NEW.known_through_commit_seq
          AND o.source_id = NEW.source_id
          AND b.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'source occurrence does not close an exact prior public C0 receipt') END;
    SELECT CASE WHEN json_extract(CAST(NEW.descriptor_bytes AS TEXT), '$.contract')
            <> NEW.descriptor_contract
        OR json_extract(CAST(NEW.descriptor_bytes AS TEXT), '$.sourceOccurrenceId')
            <> NEW.source_occurrence_id
        OR json_array_length(CAST(NEW.descriptor_bytes AS TEXT), '$.facts') <> NEW.fact_count
        OR json_extract(CAST(NEW.descriptor_bytes AS TEXT), '$.surfaceProfile.profileDigest')
            <> 'sha256:' || NEW.surface_profile_sha256
        OR json_array_length(CAST(NEW.descriptor_bytes AS TEXT), '$.eligibleSubjects')
            <> NEW.eligible_subject_count
        OR json_array_length(CAST(NEW.descriptor_bytes AS TEXT), '$.memberships')
            <> NEW.membership_count
        OR json_array_length(CAST(NEW.descriptor_bytes AS TEXT), '$.coverage')
            <> NEW.coverage_count
        OR json_array_length(CAST(NEW.descriptor_bytes AS TEXT), '$.gaps') <> NEW.gap_count
        OR json_array_length(CAST(NEW.descriptor_bytes AS TEXT), '$.renderedSubjects')
            <> NEW.rendered_subject_count
        OR json_array_length(CAST(NEW.descriptor_bytes AS TEXT), '$.omissions')
            <> NEW.omission_count
        OR (SELECT COUNT(*) FROM json_each(CAST(NEW.descriptor_bytes AS TEXT), '$.memberships')
            WHERE json_extract(value, '$.membership') = 'hot') <> NEW.hot_subject_count
        OR (SELECT COUNT(*) FROM json_each(CAST(NEW.descriptor_bytes AS TEXT), '$.memberships')
            WHERE json_extract(value, '$.membership') = 'cold_control')
            <> NEW.cold_control_subject_count
    THEN RAISE(ABORT, 'source occurrence scalar closure differs from exact descriptor bytes') END;
END;

CREATE TABLE cockpit_v2_preparation_v1 (
    preparation_id TEXT PRIMARY KEY CHECK (
        length(preparation_id) BETWEEN 1 AND 512 AND preparation_id = trim(preparation_id)
    ),
    source_occurrence_id TEXT NOT NULL UNIQUE
        REFERENCES wave5_source_occurrence_v1(source_occurrence_id),
    resolved_input_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(resolved_input_sha256) = 64
        AND resolved_input_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    resolved_input_bytes BLOB NOT NULL,
    resolved_input_byte_length INTEGER NOT NULL CHECK (
        resolved_input_byte_length > 0
        AND length(resolved_input_bytes) = resolved_input_byte_length
    ),
    semantic_sha256 TEXT NOT NULL CHECK (
        length(semantic_sha256) = 64 AND semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    semantic_bytes BLOB NOT NULL,
    semantic_byte_length INTEGER NOT NULL CHECK (
        semantic_byte_length > 0 AND length(semantic_bytes) = semantic_byte_length
    ),
    container_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(container_sha256) = 64 AND container_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    container_bytes BLOB NOT NULL,
    container_byte_length INTEGER NOT NULL CHECK (
        container_byte_length > 0 AND length(container_bytes) = container_byte_length
    ),
    checkpoint_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(checkpoint_sha256) = 64 AND checkpoint_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    checkpoint_bytes BLOB NOT NULL,
    checkpoint_byte_length INTEGER NOT NULL CHECK (
        checkpoint_byte_length > 0 AND length(checkpoint_bytes) = checkpoint_byte_length
    ),
    through_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    knowledge_wall_us INTEGER NOT NULL CHECK (knowledge_wall_us > 0),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    CHECK (through_commit_seq < created_commit_seq)
) STRICT;

CREATE TRIGGER cockpit_v2_preparation_closes_source
BEFORE INSERT ON cockpit_v2_preparation_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_source_occurrence_v1 s
        WHERE s.source_occurrence_id = NEW.source_occurrence_id
          AND s.known_through_commit_seq = NEW.through_commit_seq
          AND s.maximum_input_available_wall_us <= NEW.knowledge_wall_us
          AND s.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'Cockpit V2 prepare does not close exact store-resolved source input') END;
END;

CREATE TABLE cockpit_v2_publication_v1 (
    publication_id TEXT PRIMARY KEY CHECK (
        length(publication_id) BETWEEN 1 AND 512 AND publication_id = trim(publication_id)
    ),
    preparation_id TEXT NOT NULL UNIQUE
        REFERENCES cockpit_v2_preparation_v1(preparation_id),
    source_occurrence_id TEXT NOT NULL
        REFERENCES wave5_source_occurrence_v1(source_occurrence_id),
    publication_contract TEXT NOT NULL CHECK (
        publication_contract = 'joshi.cockpit.v2.publication'
    ),
    publication_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(publication_sha256) = 64 AND publication_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    publication_bytes_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(publication_bytes_sha256) = 64
        AND publication_bytes_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    publication_bytes BLOB NOT NULL,
    publication_byte_length INTEGER NOT NULL CHECK (
        publication_byte_length > 0
        AND length(publication_bytes) = publication_byte_length
    ),
    semantic_sha256 TEXT NOT NULL CHECK (
        length(semantic_sha256) = 64 AND semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    container_sha256 TEXT NOT NULL CHECK (
        length(container_sha256) = 64 AND container_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    checkpoint_sha256 TEXT NOT NULL CHECK (
        length(checkpoint_sha256) = 64 AND checkpoint_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    through_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    supersedes_publication_id TEXT REFERENCES cockpit_v2_publication_v1(publication_id),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    CHECK (through_commit_seq < created_commit_seq),
    CHECK (supersedes_publication_id IS NULL OR supersedes_publication_id <> publication_id)
) STRICT;

CREATE TRIGGER cockpit_v2_publication_closes_prepare
BEFORE INSERT ON cockpit_v2_publication_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM cockpit_v2_preparation_v1 p
        WHERE p.preparation_id = NEW.preparation_id
          AND p.source_occurrence_id = NEW.source_occurrence_id
          AND p.semantic_sha256 = NEW.semantic_sha256
          AND p.container_sha256 = NEW.container_sha256
          AND p.checkpoint_sha256 = NEW.checkpoint_sha256
          AND p.through_commit_seq = NEW.through_commit_seq
          AND p.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'Cockpit V2 publication does not close exact preparation') END;
    SELECT CASE WHEN NEW.supersedes_publication_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM cockpit_v2_publication_v1 prior
        WHERE prior.publication_id = NEW.supersedes_publication_id
          AND prior.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'Cockpit V2 publication supersession is missing or nonprior') END;
END;

CREATE TABLE cockpit_v2_head_v1 (
    publication_id TEXT PRIMARY KEY REFERENCES cockpit_v2_publication_v1(publication_id),
    source_occurrence_id TEXT NOT NULL
        REFERENCES wave5_source_occurrence_v1(source_occurrence_id),
    head_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(head_sha256) = 64 AND head_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    head_bytes BLOB NOT NULL,
    head_byte_length INTEGER NOT NULL CHECK (
        head_byte_length > 0 AND length(head_bytes) = head_byte_length
    ),
    supersedes_head_publication_id TEXT REFERENCES cockpit_v2_head_v1(publication_id),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    UNIQUE (supersedes_head_publication_id),
    CHECK (
        supersedes_head_publication_id IS NULL
        OR supersedes_head_publication_id <> publication_id
    )
) STRICT;

CREATE TRIGGER cockpit_v2_head_closes_publication
BEFORE INSERT ON cockpit_v2_head_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM cockpit_v2_publication_v1 p
        WHERE p.publication_id = NEW.publication_id
          AND p.source_occurrence_id = NEW.source_occurrence_id
          AND p.supersedes_publication_id IS NEW.supersedes_head_publication_id
          AND p.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'Cockpit V2 head does not close exact prior publication lineage') END;
    SELECT CASE WHEN NEW.supersedes_head_publication_id IS NULL AND EXISTS (
        SELECT 1 FROM cockpit_v2_head_v1
    ) THEN RAISE(ABORT, 'Cockpit V2 head chain already has a genesis') END;
END;

CREATE TABLE scientific_memory_occurrence_v1 (
    occurrence_id TEXT PRIMARY KEY CHECK (
        length(occurrence_id) BETWEEN 1 AND 512 AND occurrence_id = trim(occurrence_id)
    ),
    occurrence_kind TEXT NOT NULL CHECK (occurrence_kind IN ('operator_act', 'episode')),
    occurrence_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(occurrence_sha256) = 64 AND occurrence_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    occurrence_bytes BLOB NOT NULL,
    occurrence_byte_length INTEGER NOT NULL CHECK (
        occurrence_byte_length > 0 AND length(occurrence_bytes) = occurrence_byte_length
    ),
    session_id TEXT NOT NULL CHECK (session_id <> '' AND session_id = trim(session_id)),
    scene_publication_id TEXT NOT NULL REFERENCES cockpit_v2_head_v1(publication_id),
    opening_act_id TEXT REFERENCES scientific_memory_occurrence_v1(occurrence_id),
    closing_act_id TEXT REFERENCES scientific_memory_occurrence_v1(occurrence_id),
    logical_start_tick TEXT NOT NULL CHECK (
        logical_start_tick NOT GLOB '*[^0-9]*'
        AND substr(logical_start_tick, 1, 1) BETWEEN '1' AND '9'
    ),
    logical_end_tick TEXT CHECK (
        logical_end_tick IS NULL OR (
            logical_end_tick NOT GLOB '*[^0-9]*'
            AND substr(logical_end_tick, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    queue_generation INTEGER NOT NULL UNIQUE CHECK (queue_generation > 0),
    qualification TEXT NOT NULL CHECK (qualification = 'fixture_authority_unverified_semantic'),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    CHECK (
        (occurrence_kind = 'operator_act'
            AND opening_act_id IS NULL AND closing_act_id IS NULL)
        OR
        (occurrence_kind = 'episode' AND opening_act_id IS NOT NULL)
    )
) STRICT;

CREATE TRIGGER scientific_memory_occurrence_closes_head_and_acts
BEFORE INSERT ON scientific_memory_occurrence_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM cockpit_v2_head_v1 h
        WHERE h.publication_id = NEW.scene_publication_id
          AND h.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'scientific-memory occurrence does not close a prior Cockpit V2 head') END;
    SELECT CASE WHEN NEW.occurrence_kind = 'episode' AND NOT EXISTS (
        SELECT 1 FROM scientific_memory_occurrence_v1 first_act
        WHERE first_act.occurrence_id = NEW.opening_act_id
          AND first_act.occurrence_kind = 'operator_act'
          AND first_act.session_id = NEW.session_id
          AND first_act.scene_publication_id = NEW.scene_publication_id
          AND first_act.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'scientific-memory episode opening act is missing or foreign') END;
    SELECT CASE WHEN NEW.closing_act_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM scientific_memory_occurrence_v1 last_act
        WHERE last_act.occurrence_id = NEW.closing_act_id
          AND last_act.occurrence_kind = 'operator_act'
          AND last_act.session_id = NEW.session_id
          AND last_act.scene_publication_id = NEW.scene_publication_id
          AND last_act.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'scientific-memory episode closing act is missing or foreign') END;
END;

CREATE TABLE wave5_g0_pairing_epoch_v1 (
    origin TEXT NOT NULL CHECK (origin <> '' AND origin = trim(origin)),
    epoch INTEGER NOT NULL CHECK (epoch > 0),
    observed_wall_us INTEGER NOT NULL CHECK (observed_wall_us > 0),
    max_failed_attempts INTEGER NOT NULL CHECK (max_failed_attempts > 0),
    attempt_window_ms INTEGER NOT NULL CHECK (attempt_window_ms > 0),
    max_issued_per_window INTEGER NOT NULL CHECK (max_issued_per_window > 0),
    issue_window_ms INTEGER NOT NULL CHECK (issue_window_ms > 0),
    last_observed_wall_us INTEGER NOT NULL CHECK (last_observed_wall_us > 0),
    attempt_window_id TEXT REFERENCES wave5_g0_pairing_occurrence_v1(pairing_occurrence_id),
    attempt_used INTEGER NOT NULL CHECK (attempt_used >= 0),
    attempt_expires_wall_us INTEGER,
    issue_window_id TEXT REFERENCES wave5_g0_pairing_occurrence_v1(pairing_occurrence_id),
    issue_used INTEGER NOT NULL CHECK (issue_used >= 0),
    issue_expires_wall_us INTEGER,
    invalidated_issue_count INTEGER NOT NULL CHECK (invalidated_issue_count >= 0),
    invalidated_session_count INTEGER NOT NULL CHECK (invalidated_session_count >= 0),
    epoch_occurrence_id TEXT NOT NULL UNIQUE
        REFERENCES wave5_g0_pairing_occurrence_v1(pairing_occurrence_id),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    PRIMARY KEY (origin, epoch),
    UNIQUE (origin, created_commit_seq),
    CHECK (last_observed_wall_us <= observed_wall_us),
    CHECK ((attempt_window_id IS NULL AND attempt_used=0 AND attempt_expires_wall_us IS NULL)
        OR (attempt_window_id IS NOT NULL AND attempt_used>0
            AND attempt_expires_wall_us > observed_wall_us)),
    CHECK ((issue_window_id IS NULL AND issue_used=0 AND issue_expires_wall_us IS NULL)
        OR (issue_window_id IS NOT NULL AND issue_used>0
            AND issue_expires_wall_us > observed_wall_us))
) STRICT, WITHOUT ROWID;

CREATE TRIGGER wave5_g0_pairing_epoch_is_linear
BEFORE INSERT ON wave5_g0_pairing_epoch_v1
BEGIN
    SELECT CASE WHEN NEW.epoch <> COALESCE((
        SELECT MAX(epoch) + 1 FROM wave5_g0_pairing_epoch_v1 WHERE origin = NEW.origin
    ), 1) THEN RAISE(ABORT, 'pairing epoch must increase exactly once') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_g0_pairing_occurrence_v1 occurrence
        WHERE occurrence.pairing_occurrence_id = NEW.epoch_occurrence_id
          AND occurrence.occurrence_kind = 'epoch_started'
          AND occurrence.origin = NEW.origin
          AND occurrence.epoch = NEW.epoch
          AND occurrence.observed_wall_us = NEW.observed_wall_us
          AND occurrence.created_commit_seq = NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'pairing epoch does not close its exact epoch occurrence') END;
END;

CREATE TABLE wave5_g0_pairing_occurrence_v1 (
    pairing_occurrence_id TEXT PRIMARY KEY CHECK (
        length(pairing_occurrence_id) BETWEEN 1 AND 512
        AND pairing_occurrence_id = trim(pairing_occurrence_id)
    ),
    occurrence_kind TEXT NOT NULL CHECK (
        occurrence_kind IN (
            'epoch_started', 'issued', 'attempt_rejected', 'consumed', 'revoked', 'expired',
            'restart_invalidated'
        )
    ),
    issue_id TEXT CHECK (issue_id IS NULL OR (issue_id <> '' AND issue_id = trim(issue_id))),
    session_id TEXT CHECK (
        session_id IS NULL OR (session_id <> '' AND session_id = trim(session_id))
    ),
    predecessor_occurrence_id TEXT REFERENCES wave5_g0_pairing_occurrence_v1(pairing_occurrence_id),
    origin TEXT NOT NULL CHECK (origin <> '' AND origin = trim(origin)),
    epoch INTEGER NOT NULL CHECK (epoch > 0),
    at_monotonic_ms TEXT NOT NULL CHECK (
        at_monotonic_ms = '0' OR (
            at_monotonic_ms NOT GLOB '*[^0-9]*'
            AND substr(at_monotonic_ms, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    observed_wall_us INTEGER NOT NULL CHECK (observed_wall_us > 0),
    expires_wall_us INTEGER CHECK (
        expires_wall_us IS NULL OR expires_wall_us > observed_wall_us
    ),
    scopes_json TEXT NOT NULL CHECK (
        json_valid(scopes_json) AND json_type(scopes_json) = 'array'
    ),
    failed_attempt_ordinal INTEGER CHECK (
        failed_attempt_ordinal IS NULL OR failed_attempt_ordinal > 0
    ),
    attempt_window_started_monotonic_ms TEXT CHECK (
        attempt_window_started_monotonic_ms IS NULL
        OR attempt_window_started_monotonic_ms = '0'
        OR (
            attempt_window_started_monotonic_ms NOT GLOB '*[^0-9]*'
            AND substr(attempt_window_started_monotonic_ms, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    rate_window_id TEXT REFERENCES wave5_g0_pairing_occurrence_v1(pairing_occurrence_id),
    rate_window_started_wall_us INTEGER CHECK (
        rate_window_started_wall_us IS NULL OR rate_window_started_wall_us > 0
    ),
    rate_window_expires_wall_us INTEGER CHECK (
        rate_window_expires_wall_us IS NULL OR rate_window_expires_wall_us > 0
    ),
    reason TEXT CHECK (reason IS NULL OR (reason <> '' AND reason = trim(reason))),
    document_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(document_sha256) = 64 AND document_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    document_bytes BLOB NOT NULL,
    document_byte_length INTEGER NOT NULL CHECK (
        document_byte_length > 0 AND length(document_bytes) = document_byte_length
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_only_pairing_exchange'),
    created_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    UNIQUE (origin, epoch, pairing_occurrence_id),
    CHECK (
        (occurrence_kind = 'epoch_started'
            AND issue_id IS NULL AND session_id IS NULL
            AND predecessor_occurrence_id IS NULL AND expires_wall_us IS NULL
            AND failed_attempt_ordinal IS NULL
            AND attempt_window_started_monotonic_ms IS NULL
            AND rate_window_id IS NULL AND rate_window_started_wall_us IS NULL
            AND rate_window_expires_wall_us IS NULL)
        OR
        (occurrence_kind = 'issued'
            AND issue_id IS NOT NULL AND session_id IS NULL
            AND predecessor_occurrence_id IS NOT NULL AND expires_wall_us IS NOT NULL
            AND failed_attempt_ordinal IS NULL
            AND attempt_window_started_monotonic_ms IS NULL
            AND rate_window_id IS NOT NULL AND rate_window_started_wall_us IS NOT NULL
            AND rate_window_expires_wall_us > observed_wall_us
            AND rate_window_started_wall_us <= observed_wall_us)
        OR
        (occurrence_kind = 'attempt_rejected'
            AND issue_id IS NULL AND session_id IS NULL
            AND predecessor_occurrence_id IS NOT NULL AND expires_wall_us IS NULL
            AND failed_attempt_ordinal IS NOT NULL
            AND attempt_window_started_monotonic_ms IS NOT NULL
            AND rate_window_id IS NOT NULL AND rate_window_started_wall_us IS NOT NULL
            AND rate_window_expires_wall_us > observed_wall_us
            AND rate_window_started_wall_us <= observed_wall_us)
        OR
        (occurrence_kind = 'consumed'
            AND issue_id IS NOT NULL AND session_id IS NOT NULL
            AND predecessor_occurrence_id IS NOT NULL AND expires_wall_us IS NOT NULL)
        OR
        (occurrence_kind = 'revoked'
            AND issue_id IS NULL AND session_id IS NOT NULL
            AND predecessor_occurrence_id IS NOT NULL AND expires_wall_us IS NULL)
        OR
        (occurrence_kind IN ('expired', 'restart_invalidated')
            AND (issue_id IS NULL) <> (session_id IS NULL)
            AND predecessor_occurrence_id IS NOT NULL AND expires_wall_us IS NULL)
    ),
    CHECK (occurrence_kind IN ('issued','attempt_rejected') OR
        (rate_window_id IS NULL AND rate_window_started_wall_us IS NULL
         AND rate_window_expires_wall_us IS NULL))
) STRICT;

CREATE TRIGGER wave5_g0_pairing_transition_is_linear
BEFORE INSERT ON wave5_g0_pairing_occurrence_v1
WHEN NEW.predecessor_occurrence_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_g0_pairing_occurrence_v1 p
        WHERE p.pairing_occurrence_id = NEW.predecessor_occurrence_id
          AND p.origin = NEW.origin
          AND p.created_commit_seq < NEW.created_commit_seq
          AND (
              (NEW.occurrence_kind = 'consumed'
                  AND p.occurrence_kind = 'issued' AND p.issue_id = NEW.issue_id
                  AND p.epoch = NEW.epoch)
              OR (NEW.occurrence_kind IN ('issued', 'attempt_rejected')
                  AND p.occurrence_kind = 'epoch_started' AND p.epoch = NEW.epoch)
              OR (NEW.occurrence_kind IN ('revoked', 'expired')
                  AND (
                      (NEW.session_id IS NULL AND p.occurrence_kind = 'issued'
                          AND p.issue_id = NEW.issue_id AND p.epoch = NEW.epoch)
                      OR
                      (NEW.session_id IS NOT NULL AND p.occurrence_kind = 'consumed'
                          AND p.session_id = NEW.session_id AND p.epoch = NEW.epoch)
                  ))
              OR (NEW.occurrence_kind = 'restart_invalidated'
                  AND NEW.epoch = p.epoch + 1
                  AND (
                      (NEW.session_id IS NULL AND p.occurrence_kind = 'issued'
                          AND p.issue_id = NEW.issue_id)
                      OR
                      (NEW.session_id IS NOT NULL AND p.occurrence_kind = 'consumed'
                          AND p.session_id = NEW.session_id)
                  ))
          )
    ) THEN RAISE(ABORT, 'pairing transition is foreign, cross-epoch, or nonprior') END;
END;

CREATE TRIGGER wave5_g0_pairing_occurrence_closes_epoch
BEFORE INSERT ON wave5_g0_pairing_occurrence_v1
WHEN NEW.occurrence_kind <> 'epoch_started'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_g0_pairing_epoch_v1 e
        WHERE e.origin = NEW.origin AND e.epoch = NEW.epoch
          AND e.created_commit_seq <= NEW.created_commit_seq
          AND (
              e.epoch = (SELECT MAX(current.epoch)
                         FROM wave5_g0_pairing_epoch_v1 current
                         WHERE current.origin = NEW.origin)
              OR (NEW.occurrence_kind = 'restart_invalidated' AND EXISTS (
                  SELECT 1 FROM wave5_g0_pairing_epoch_v1 restart
                  WHERE restart.origin = NEW.origin
                    AND restart.created_commit_seq = NEW.created_commit_seq
                    AND restart.epoch > NEW.epoch
              ))
          )
    ) THEN RAISE(ABORT, 'pairing occurrence does not close the active durable epoch') END;
END;

CREATE UNIQUE INDEX wave5_g0_pairing_one_issued_identity
ON wave5_g0_pairing_occurrence_v1(origin, epoch, issue_id)
WHERE occurrence_kind = 'issued';
CREATE UNIQUE INDEX wave5_g0_pairing_one_consumed_session
ON wave5_g0_pairing_occurrence_v1(origin, epoch, session_id)
WHERE occurrence_kind = 'consumed';
CREATE UNIQUE INDEX wave5_g0_pairing_one_terminal_child
ON wave5_g0_pairing_occurrence_v1(predecessor_occurrence_id)
WHERE predecessor_occurrence_id IS NOT NULL
  AND occurrence_kind IN ('consumed','revoked','expired','restart_invalidated');

CREATE TABLE wave5_g0_restricted_manifest_cas_v1 (
    import_id TEXT PRIMARY KEY REFERENCES wave5_restricted_artifact_v1(import_id),
    blob_id TEXT NOT NULL,
    storage_domain TEXT NOT NULL CHECK (storage_domain = 'public_source'),
    manifest_sha256 TEXT NOT NULL CHECK (
        length(manifest_sha256) = 64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    manifest_byte_length INTEGER NOT NULL CHECK (manifest_byte_length > 0),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    FOREIGN KEY (blob_id, storage_domain) REFERENCES blob_object(blob_id, storage_domain),
    CHECK (blob_id = manifest_sha256)
) STRICT;

CREATE TRIGGER wave5_g0_restricted_manifest_closes_exact_import
BEFORE INSERT ON wave5_g0_restricted_manifest_cas_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave5_restricted_artifact_v1 artifact
        JOIN blob_object blob
          ON blob.blob_id=NEW.blob_id AND blob.storage_domain=NEW.storage_domain
        WHERE artifact.import_id=NEW.import_id
          AND artifact.manifest_sha256=NEW.manifest_sha256
          AND artifact.manifest_byte_length=NEW.manifest_byte_length
          AND artifact.created_commit_seq=NEW.created_commit_seq
          AND blob.storage_mode='external'
          AND blob.stored_sha256=NEW.manifest_sha256
          AND blob.stored_length=NEW.manifest_byte_length
          AND blob.created_commit_seq=NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'G0 import manifest CAS differs from exact restricted import') END;
END;

CREATE TABLE wave5_g0_backup_reservation_v1 (
    backup_id TEXT PRIMARY KEY CHECK (
        length(backup_id) BETWEEN 1 AND 512 AND backup_id = trim(backup_id)
    ),
    run_registration_id TEXT NOT NULL
        REFERENCES wave5_run_registration_v1(run_registration_id),
    reservation_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(reservation_sha256) = 64 AND reservation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    reservation_bytes BLOB NOT NULL,
    reservation_byte_length INTEGER NOT NULL CHECK (
        reservation_byte_length > 0 AND length(reservation_bytes)=reservation_byte_length
    ),
    catalog_destination TEXT NOT NULL CHECK (catalog_destination <> ''),
    artifact_destination_root TEXT NOT NULL CHECK (artifact_destination_root <> ''),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TRIGGER wave5_g0_backup_reservation_closes_run
BEFORE INSERT ON wave5_g0_backup_reservation_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_run_registration_v1 run
        WHERE run.run_registration_id=NEW.run_registration_id
          AND run.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'G0 backup reservation has no prior run') END;
    SELECT CASE WHEN json_extract(CAST(NEW.reservation_bytes AS TEXT),'$.backupId')
            <> NEW.backup_id
        OR json_extract(CAST(NEW.reservation_bytes AS TEXT),'$.runRegistrationId')
            <> NEW.run_registration_id
        OR json_extract(CAST(NEW.reservation_bytes AS TEXT),'$.catalogDestination')
            <> NEW.catalog_destination
        OR json_extract(CAST(NEW.reservation_bytes AS TEXT),'$.artifactDestinationRoot')
            <> NEW.artifact_destination_root
    THEN RAISE(ABORT, 'G0 backup reservation differs from exact bytes') END;
END;

CREATE TABLE wave5_g0_backup_snapshot_v1 (
    backup_id TEXT PRIMARY KEY REFERENCES wave5_g0_backup_reservation_v1(backup_id),
    snapshot_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(snapshot_sha256) = 64 AND snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    snapshot_bytes BLOB NOT NULL,
    snapshot_byte_length INTEGER NOT NULL CHECK (
        snapshot_byte_length > 0 AND length(snapshot_bytes)=snapshot_byte_length
    ),
    staging_catalog_path TEXT NOT NULL CHECK (staging_catalog_path <> ''),
    catalog_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(catalog_sha256) = 64 AND catalog_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    source_max_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    CHECK (source_max_commit_seq < created_commit_seq)
) STRICT;

CREATE TRIGGER wave5_g0_backup_snapshot_closes_reservation
BEFORE INSERT ON wave5_g0_backup_snapshot_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_g0_backup_reservation_v1 reservation
        WHERE reservation.backup_id=NEW.backup_id
          AND reservation.created_commit_seq <= NEW.source_max_commit_seq
          AND reservation.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'G0 backup snapshot has no prior reservation') END;
    SELECT CASE WHEN json_extract(CAST(NEW.snapshot_bytes AS TEXT),'$.backupId')
            <> NEW.backup_id
        OR json_extract(CAST(NEW.snapshot_bytes AS TEXT),'$.stagingCatalogPath')
            <> NEW.staging_catalog_path
        OR json_extract(CAST(NEW.snapshot_bytes AS TEXT),'$.catalogDigest')
            <> 'sha256:' || NEW.catalog_sha256
        OR CAST(json_extract(CAST(NEW.snapshot_bytes AS TEXT),'$.sourceMaxCommitSeq') AS INTEGER)
            <> NEW.source_max_commit_seq
    THEN RAISE(ABORT, 'G0 backup snapshot differs from exact bytes') END;
END;

CREATE TABLE wave5_g0_backup_v1 (
    backup_id TEXT PRIMARY KEY CHECK (
        length(backup_id) BETWEEN 1 AND 512 AND backup_id = trim(backup_id)
    ),
    run_registration_id TEXT NOT NULL
        REFERENCES wave5_run_registration_v1(run_registration_id),
    source_max_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    catalog_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(catalog_sha256) = 64 AND catalog_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    manifest_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(manifest_sha256) = 64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    manifest_bytes BLOB NOT NULL,
    manifest_byte_length INTEGER NOT NULL CHECK (
        manifest_byte_length > 0 AND length(manifest_bytes) = manifest_byte_length
    ),
    artifact_inventory_sha256 TEXT NOT NULL CHECK (
        length(artifact_inventory_sha256) = 64
        AND artifact_inventory_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    artifact_inventory_bytes BLOB NOT NULL,
    artifact_inventory_byte_length INTEGER NOT NULL CHECK (
        artifact_inventory_byte_length > 0
        AND length(artifact_inventory_bytes) = artifact_inventory_byte_length
    ),
    artifact_count INTEGER NOT NULL CHECK (artifact_count > 0),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    CHECK (source_max_commit_seq < created_commit_seq)
) STRICT;

CREATE TRIGGER wave5_g0_backup_closes_run
BEFORE INSERT ON wave5_g0_backup_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_run_registration_v1 r
        WHERE r.run_registration_id = NEW.run_registration_id
          AND r.created_commit_seq <= NEW.source_max_commit_seq
          AND r.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'G0 backup does not close a registered run in its source snapshot') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_g0_backup_reservation_v1 reservation
        WHERE reservation.backup_id=NEW.backup_id
          AND reservation.run_registration_id=NEW.run_registration_id
          AND reservation.created_commit_seq <= NEW.source_max_commit_seq
          AND reservation.created_commit_seq < NEW.created_commit_seq
          AND json_extract(CAST(NEW.manifest_bytes AS TEXT),'$.catalogPath')
                = reservation.catalog_destination
          AND json_extract(CAST(NEW.manifest_bytes AS TEXT),'$.artifactRoot')
                = reservation.artifact_destination_root
    ) THEN RAISE(ABORT, 'G0 backup does not settle its exact durable reservation') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_g0_backup_snapshot_v1 snapshot
        WHERE snapshot.backup_id=NEW.backup_id
          AND snapshot.catalog_sha256=NEW.catalog_sha256
          AND snapshot.source_max_commit_seq=NEW.source_max_commit_seq
          AND snapshot.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'G0 backup differs from its settled private snapshot') END;
END;

CREATE TABLE wave5_g0_backup_restore_v1 (
    restore_id TEXT PRIMARY KEY CHECK (
        length(restore_id) BETWEEN 1 AND 512 AND restore_id = trim(restore_id)
    ),
    backup_id TEXT NOT NULL UNIQUE REFERENCES wave5_g0_backup_v1(backup_id),
    restored_catalog_sha256 TEXT NOT NULL CHECK (
        length(restored_catalog_sha256) = 64
        AND restored_catalog_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    artifact_inventory_sha256 TEXT NOT NULL CHECK (
        length(artifact_inventory_sha256) = 64
        AND artifact_inventory_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    readback_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(readback_sha256) = 64 AND readback_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    readback_bytes BLOB NOT NULL,
    readback_byte_length INTEGER NOT NULL CHECK (
        readback_byte_length > 0 AND length(readback_bytes) = readback_byte_length
    ),
    restored_max_commit_seq INTEGER NOT NULL CHECK (restored_max_commit_seq > 0),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TABLE wave5_g0_backup_restore_reservation_v1 (
    restore_id TEXT PRIMARY KEY CHECK (
        length(restore_id) BETWEEN 1 AND 512 AND restore_id = trim(restore_id)
    ),
    backup_id TEXT NOT NULL UNIQUE REFERENCES wave5_g0_backup_v1(backup_id),
    reservation_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(reservation_sha256) = 64 AND reservation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    reservation_bytes BLOB NOT NULL,
    reservation_byte_length INTEGER NOT NULL CHECK (
        reservation_byte_length > 0 AND length(reservation_bytes)=reservation_byte_length
    ),
    catalog_destination TEXT NOT NULL CHECK (catalog_destination <> ''),
    artifact_destination_root TEXT NOT NULL CHECK (artifact_destination_root <> ''),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TRIGGER wave5_g0_backup_restore_reservation_closes_backup
BEFORE INSERT ON wave5_g0_backup_restore_reservation_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_g0_backup_v1 backup
        WHERE backup.backup_id=NEW.backup_id
          AND backup.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'G0 restore reservation has no prior backup') END;
    SELECT CASE WHEN json_extract(CAST(NEW.reservation_bytes AS TEXT),'$.restoreId')
            <> NEW.restore_id
        OR json_extract(CAST(NEW.reservation_bytes AS TEXT),'$.backupId')
            <> NEW.backup_id
        OR json_extract(CAST(NEW.reservation_bytes AS TEXT),'$.catalogDestination')
            <> NEW.catalog_destination
        OR json_extract(CAST(NEW.reservation_bytes AS TEXT),'$.artifactDestinationRoot')
            <> NEW.artifact_destination_root
    THEN RAISE(ABORT, 'G0 restore reservation differs from exact bytes') END;
END;

CREATE TRIGGER wave5_g0_restore_closes_backup
BEFORE INSERT ON wave5_g0_backup_restore_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_g0_backup_v1 b
        WHERE b.backup_id = NEW.backup_id
          AND b.catalog_sha256 = NEW.restored_catalog_sha256
          AND b.artifact_inventory_sha256 = NEW.artifact_inventory_sha256
          AND b.source_max_commit_seq = NEW.restored_max_commit_seq
          AND b.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'G0 restore readback does not close exact backup inventory') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_g0_backup_restore_reservation_v1 reservation
        WHERE reservation.restore_id=NEW.restore_id
          AND reservation.backup_id=NEW.backup_id
          AND reservation.created_commit_seq < NEW.created_commit_seq
          AND json_extract(CAST(NEW.readback_bytes AS TEXT),'$.restoredCatalogPath')
                = reservation.catalog_destination
          AND json_extract(CAST(NEW.readback_bytes AS TEXT),'$.restoredArtifactRoot')
                = reservation.artifact_destination_root
    ) THEN RAISE(ABORT, 'G0 restore does not settle its exact durable reservation') END;
END;

CREATE TRIGGER no_update_wave5_source_occurrence_v1
BEFORE UPDATE ON wave5_source_occurrence_v1
BEGIN SELECT RAISE(ABORT, 'wave5_source_occurrence_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_source_occurrence_v1
BEFORE DELETE ON wave5_source_occurrence_v1
BEGIN SELECT RAISE(ABORT, 'wave5_source_occurrence_v1 is append-only'); END;
CREATE TRIGGER no_update_cockpit_v2_preparation_v1
BEFORE UPDATE ON cockpit_v2_preparation_v1
BEGIN SELECT RAISE(ABORT, 'cockpit_v2_preparation_v1 is append-only'); END;
CREATE TRIGGER no_delete_cockpit_v2_preparation_v1
BEFORE DELETE ON cockpit_v2_preparation_v1
BEGIN SELECT RAISE(ABORT, 'cockpit_v2_preparation_v1 is append-only'); END;
CREATE TRIGGER no_update_cockpit_v2_publication_v1
BEFORE UPDATE ON cockpit_v2_publication_v1
BEGIN SELECT RAISE(ABORT, 'cockpit_v2_publication_v1 is append-only'); END;
CREATE TRIGGER no_delete_cockpit_v2_publication_v1
BEFORE DELETE ON cockpit_v2_publication_v1
BEGIN SELECT RAISE(ABORT, 'cockpit_v2_publication_v1 is append-only'); END;
CREATE TRIGGER no_update_cockpit_v2_head_v1
BEFORE UPDATE ON cockpit_v2_head_v1
BEGIN SELECT RAISE(ABORT, 'cockpit_v2_head_v1 is append-only'); END;
CREATE TRIGGER no_delete_cockpit_v2_head_v1
BEFORE DELETE ON cockpit_v2_head_v1
BEGIN SELECT RAISE(ABORT, 'cockpit_v2_head_v1 is append-only'); END;
CREATE TRIGGER no_update_scientific_memory_occurrence_v1
BEFORE UPDATE ON scientific_memory_occurrence_v1
BEGIN SELECT RAISE(ABORT, 'scientific_memory_occurrence_v1 is append-only'); END;
CREATE TRIGGER no_delete_scientific_memory_occurrence_v1
BEFORE DELETE ON scientific_memory_occurrence_v1
BEGIN SELECT RAISE(ABORT, 'scientific_memory_occurrence_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_g0_pairing_occurrence_v1
BEFORE UPDATE ON wave5_g0_pairing_occurrence_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_pairing_occurrence_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_g0_pairing_occurrence_v1
BEFORE DELETE ON wave5_g0_pairing_occurrence_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_pairing_occurrence_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_g0_pairing_epoch_v1
BEFORE UPDATE ON wave5_g0_pairing_epoch_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_pairing_epoch_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_g0_pairing_epoch_v1
BEFORE DELETE ON wave5_g0_pairing_epoch_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_pairing_epoch_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_g0_restricted_manifest_cas_v1
BEFORE UPDATE ON wave5_g0_restricted_manifest_cas_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_restricted_manifest_cas_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_g0_restricted_manifest_cas_v1
BEFORE DELETE ON wave5_g0_restricted_manifest_cas_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_restricted_manifest_cas_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_g0_backup_reservation_v1
BEFORE UPDATE ON wave5_g0_backup_reservation_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_backup_reservation_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_g0_backup_reservation_v1
BEFORE DELETE ON wave5_g0_backup_reservation_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_backup_reservation_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_g0_backup_snapshot_v1
BEFORE UPDATE ON wave5_g0_backup_snapshot_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_backup_snapshot_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_g0_backup_snapshot_v1
BEFORE DELETE ON wave5_g0_backup_snapshot_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_backup_snapshot_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_g0_backup_v1
BEFORE UPDATE ON wave5_g0_backup_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_backup_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_g0_backup_v1
BEFORE DELETE ON wave5_g0_backup_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_backup_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_g0_backup_restore_reservation_v1
BEFORE UPDATE ON wave5_g0_backup_restore_reservation_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_backup_restore_reservation_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_g0_backup_restore_reservation_v1
BEFORE DELETE ON wave5_g0_backup_restore_reservation_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_backup_restore_reservation_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_g0_backup_restore_v1
BEFORE UPDATE ON wave5_g0_backup_restore_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_backup_restore_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_g0_backup_restore_v1
BEFORE DELETE ON wave5_g0_backup_restore_v1
BEGIN SELECT RAISE(ABORT, 'wave5_g0_backup_restore_v1 is append-only'); END;
