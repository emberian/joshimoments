-- Forward-only migration 0005: lossless typed-contract sidecars for durable store admission.
--
-- Migrations 0001-0004 retain the deliberately narrow indexed columns. These one-to-one and
-- one-to-many sidecars retain the rest of the public joshi-evidence contract without overloading
-- an unrelated locator/detail column or pretending open-world recognition is derivable later.

CREATE TABLE acquisition_contract (
    acquisition_id TEXT PRIMARY KEY REFERENCES acquisition(acquisition_id),
    contract_version TEXT NOT NULL CHECK (contract_version <> ''),
    acquisition_kind_recognition TEXT NOT NULL CHECK (
        acquisition_kind_recognition IN ('known', 'unknown')
    ),
    transport_kind_recognition TEXT NOT NULL CHECK (
        transport_kind_recognition IN ('known', 'unknown')
    ),
    requested_wall_us INTEGER,
    received_wall_us INTEGER NOT NULL CHECK (received_wall_us > 0),
    persisted_wall_us INTEGER NOT NULL CHECK (persisted_wall_us >= received_wall_us),
    elapsed_mono_ns TEXT,
    elapsed_clock_id TEXT,
    source_cursor_text TEXT,
    CHECK (requested_wall_us IS NULL OR requested_wall_us <= received_wall_us),
    CHECK (
        (elapsed_mono_ns IS NULL AND elapsed_clock_id IS NULL)
        OR (
            elapsed_mono_ns IS NOT NULL AND elapsed_clock_id IS NOT NULL
            AND elapsed_clock_id <> ''
            AND (
                elapsed_mono_ns = '0'
                OR (
                    elapsed_mono_ns NOT GLOB '*[^0-9]*'
                    AND substr(elapsed_mono_ns, 1, 1) BETWEEN '1' AND '9'
                )
            )
        )
    )
) STRICT;

CREATE TABLE observation_contract (
    observation_id TEXT PRIMARY KEY REFERENCES observation(observation_id),
    observation_kind_recognition TEXT NOT NULL CHECK (
        observation_kind_recognition IN ('known', 'unknown')
    ),
    source_variant TEXT NOT NULL CHECK (source_variant <> ''),
    source_variant_recognition TEXT NOT NULL CHECK (
        source_variant_recognition IN ('known', 'unknown')
    ),
    event_time_status_recognition TEXT NOT NULL CHECK (
        event_time_status_recognition IN ('known', 'unknown')
    ),
    chain_commitment_recognition TEXT CHECK (
        chain_commitment_recognition IS NULL
        OR chain_commitment_recognition IN ('known', 'unknown')
    ),
    parse_disposition_recognition TEXT NOT NULL CHECK (
        parse_disposition_recognition IN ('known', 'unknown')
    )
) STRICT;

-- Content identity is global, while protection/retention and representation are reference-local.
-- V1's blob table remains a compatibility content catalog; V5 store reads these tables as
-- authoritative for physical placement and observation-specific media policy.
CREATE TABLE blob_object (
    blob_id TEXT NOT NULL REFERENCES blob(blob_id),
    storage_domain TEXT NOT NULL CHECK (storage_domain <> ''),
    storage_mode TEXT NOT NULL CHECK (storage_mode IN ('inline', 'external')),
    inline_bytes BLOB,
    relative_path TEXT,
    stored_length INTEGER NOT NULL CHECK (stored_length >= 0),
    stored_sha256 TEXT NOT NULL CHECK (
        length(stored_sha256) = 64 AND stored_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    compression TEXT NOT NULL CHECK (compression IN ('identity', 'zstd')),
    PRIMARY KEY (blob_id, storage_domain),
    UNIQUE (relative_path),
    CHECK (
        (storage_mode = 'inline' AND inline_bytes IS NOT NULL AND relative_path IS NULL)
        OR (storage_mode = 'external' AND inline_bytes IS NULL AND relative_path IS NOT NULL
            AND relative_path <> '' AND substr(relative_path, 1, 1) <> '/'
            AND relative_path NOT GLOB '*../*' AND relative_path NOT GLOB '../*')
    )
) STRICT, WITHOUT ROWID;

CREATE TABLE observation_blob_contract (
    observation_id TEXT PRIMARY KEY REFERENCES observation(observation_id),
    blob_id TEXT NOT NULL REFERENCES blob(blob_id),
    storage_domain TEXT NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type <> ''),
    content_encoding TEXT,
    retention_class TEXT NOT NULL CHECK (
        retention_class IN (
            'public_chain', 'public_source', 'social_media', 'app_private',
            'operator_private', 'fixture', 'disposable'
        )
    ),
    FOREIGN KEY (blob_id, storage_domain) REFERENCES blob_object(blob_id, storage_domain)
) STRICT;

CREATE TABLE scene_artifact_contract (
    scene_id TEXT NOT NULL REFERENCES scene(scene_id),
    artifact_role TEXT NOT NULL CHECK (artifact_role IN ('view', 'screenshot')),
    blob_id TEXT NOT NULL,
    storage_domain TEXT NOT NULL,
    PRIMARY KEY (scene_id, artifact_role),
    FOREIGN KEY (blob_id, storage_domain) REFERENCES blob_object(blob_id, storage_domain)
) STRICT, WITHOUT ROWID;

CREATE TABLE command_payload_contract (
    command_id TEXT PRIMARY KEY REFERENCES command(command_id),
    blob_id TEXT NOT NULL,
    storage_domain TEXT NOT NULL,
    FOREIGN KEY (blob_id, storage_domain) REFERENCES blob_object(blob_id, storage_domain)
) STRICT;

CREATE TABLE source_event_contract (
    source_event_id TEXT PRIMARY KEY REFERENCES source_event(source_event_id),
    event_kind TEXT NOT NULL CHECK (event_kind <> ''),
    event_kind_recognition TEXT NOT NULL CHECK (
        event_kind_recognition IN ('known', 'unknown')
    )
) STRICT;

CREATE TABLE observation_source_event_contract (
    observation_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    relation_recognition TEXT NOT NULL CHECK (relation_recognition IN ('known', 'unknown')),
    PRIMARY KEY (observation_id, source_event_id, relation),
    FOREIGN KEY (observation_id, source_event_id, relation)
        REFERENCES observation_source_event(observation_id, source_event_id, relation)
) STRICT, WITHOUT ROWID;

CREATE TABLE assertion_contract (
    assertion_id TEXT PRIMARY KEY REFERENCES assertion(assertion_id),
    assertion_kind_recognition TEXT NOT NULL CHECK (
        assertion_kind_recognition IN ('known', 'unknown')
    ),
    assertion_status_recognition TEXT NOT NULL CHECK (
        assertion_status_recognition IN ('known', 'unknown')
    ),
    valid_time_status_recognition TEXT NOT NULL CHECK (
        valid_time_status_recognition IN ('known', 'unknown')
    ),
    available_wall_us INTEGER NOT NULL CHECK (available_wall_us > 0)
) STRICT;

CREATE TABLE assertion_observation_evidence_contract (
    assertion_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    evidence_role TEXT NOT NULL,
    role_recognition TEXT NOT NULL CHECK (role_recognition IN ('known', 'unknown')),
    PRIMARY KEY (assertion_id, observation_id, evidence_role),
    FOREIGN KEY (assertion_id, observation_id, evidence_role)
        REFERENCES assertion_observation_evidence(assertion_id, observation_id, evidence_role)
) STRICT, WITHOUT ROWID;

CREATE TABLE assertion_source_event_contract (
    assertion_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    relation_recognition TEXT NOT NULL CHECK (relation_recognition IN ('known', 'unknown')),
    PRIMARY KEY (assertion_id, source_event_id, relation),
    FOREIGN KEY (assertion_id, source_event_id, relation)
        REFERENCES assertion_source_event(assertion_id, source_event_id, relation)
) STRICT, WITHOUT ROWID;

CREATE TABLE assertion_command_evidence_contract (
    assertion_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    evidence_role TEXT NOT NULL,
    role_recognition TEXT NOT NULL CHECK (role_recognition IN ('known', 'unknown')),
    PRIMARY KEY (assertion_id, command_id, evidence_role),
    FOREIGN KEY (assertion_id, command_id, evidence_role)
        REFERENCES assertion_command_evidence(assertion_id, command_id, evidence_role)
) STRICT, WITHOUT ROWID;

CREATE TABLE coverage_window_contract (
    coverage_id TEXT PRIMARY KEY REFERENCES coverage_window(coverage_id),
    scope_family_recognition TEXT NOT NULL CHECK (
        scope_family_recognition IN ('known', 'unknown')
    ),
    scope_subject TEXT,
    lower_boundary_json TEXT NOT NULL CHECK (
        json_valid(lower_boundary_json) AND json_type(lower_boundary_json) = 'object'
        AND json_extract(lower_boundary_json, '$.clock') IN
            ('wall', 'commit', 'source_cursor', 'unknown')
    ),
    upper_boundary_json TEXT CHECK (
        upper_boundary_json IS NULL OR (
            json_valid(upper_boundary_json) AND json_type(upper_boundary_json) = 'object'
            AND json_extract(upper_boundary_json, '$.clock') IN
                ('wall', 'commit', 'source_cursor', 'unknown')
        )
    ),
    state TEXT NOT NULL CHECK (state <> ''),
    state_recognition TEXT NOT NULL CHECK (state_recognition IN ('known', 'unknown')),
    available_wall_us INTEGER NOT NULL CHECK (available_wall_us > 0)
) STRICT;

CREATE TABLE coverage_gap_contract (
    gap_id TEXT PRIMARY KEY REFERENCES coverage_gap(gap_id),
    scope_source_id TEXT NOT NULL REFERENCES source(source_id),
    scope_family TEXT NOT NULL CHECK (scope_family <> ''),
    scope_family_recognition TEXT NOT NULL CHECK (
        scope_family_recognition IN ('known', 'unknown')
    ),
    scope_subject TEXT,
    lower_boundary_json TEXT NOT NULL CHECK (
        json_valid(lower_boundary_json) AND json_type(lower_boundary_json) = 'object'
        AND json_extract(lower_boundary_json, '$.clock') IN
            ('wall', 'commit', 'source_cursor', 'unknown')
    ),
    upper_boundary_json TEXT CHECK (
        upper_boundary_json IS NULL OR (
            json_valid(upper_boundary_json) AND json_type(upper_boundary_json) = 'object'
            AND json_extract(upper_boundary_json, '$.clock') IN
                ('wall', 'commit', 'source_cursor', 'unknown')
        )
    ),
    reason_recognition TEXT NOT NULL CHECK (reason_recognition IN ('known', 'unknown'))
) STRICT;

CREATE TABLE coverage_recovery_contract (
    recovery_id TEXT PRIMARY KEY REFERENCES coverage_gap_recovery(recovery_id),
    status_recognition TEXT NOT NULL CHECK (status_recognition IN ('known', 'unknown')),
    recovered_through_json TEXT CHECK (
        recovered_through_json IS NULL OR (
            json_valid(recovered_through_json) AND json_type(recovered_through_json) = 'object'
            AND json_extract(recovered_through_json, '$.clock') IN
                ('wall', 'commit', 'source_cursor', 'unknown')
        )
    ),
    available_wall_us INTEGER NOT NULL CHECK (available_wall_us > 0)
) STRICT;

CREATE TABLE coverage_recovery_observation (
    recovery_id TEXT NOT NULL REFERENCES coverage_gap_recovery(recovery_id),
    observation_id TEXT NOT NULL REFERENCES observation(observation_id),
    PRIMARY KEY (recovery_id, observation_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE source_cursor_contract (
    cursor_id TEXT PRIMARY KEY REFERENCES source_cursor(cursor_id),
    scope_family_recognition TEXT NOT NULL CHECK (
        scope_family_recognition IN ('known', 'unknown')
    ),
    scope_subject TEXT,
    cursor_kind_recognition TEXT NOT NULL CHECK (
        cursor_kind_recognition IN ('known', 'unknown')
    )
) STRICT;

CREATE TABLE blob_object_disposal (
    disposal_id TEXT PRIMARY KEY CHECK (disposal_id <> ''),
    blob_id TEXT NOT NULL,
    storage_domain TEXT NOT NULL,
    committed_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    policy_id TEXT NOT NULL CHECK (policy_id <> ''),
    authorization_fingerprint TEXT NOT NULL CHECK (
        length(authorization_fingerprint) = 64
        AND authorization_fingerprint NOT GLOB '*[^0-9a-f]*'
    ),
    disposed_wall_us INTEGER NOT NULL CHECK (disposed_wall_us > 0),
    disposition TEXT NOT NULL CHECK (
        disposition IN ('external_bytes_erased', 'encryption_key_destroyed', 'backup_expired')
    ),
    FOREIGN KEY (blob_id, storage_domain) REFERENCES blob_object(blob_id, storage_domain),
    UNIQUE (blob_id, storage_domain, policy_id, disposition)
) STRICT;

CREATE TRIGGER block_ambiguous_v4_blob_disposal BEFORE INSERT ON blob_disposal
BEGIN SELECT RAISE(ABORT, 'use protection-domain-specific blob_object_disposal'); END;

CREATE TABLE export_snapshot (
    export_snapshot_id TEXT PRIMARY KEY CHECK (export_snapshot_id <> ''),
    contract TEXT NOT NULL CHECK (contract <> ''),
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    manifest_relative_path TEXT NOT NULL UNIQUE CHECK (
        manifest_relative_path <> '' AND substr(manifest_relative_path, 1, 1) <> '/'
        AND manifest_relative_path NOT GLOB '*../*'
        AND manifest_relative_path NOT GLOB '../*'
    ),
    manifest_sha256 TEXT NOT NULL CHECK (
        length(manifest_sha256) = 64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    manifest_byte_length INTEGER NOT NULL CHECK (manifest_byte_length >= 0),
    from_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    through_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    scene_id TEXT REFERENCES scene(scene_id),
    created_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    CHECK (from_commit_seq <= through_commit_seq),
    CHECK (through_commit_seq <= created_commit_seq)
) STRICT;

CREATE TABLE export_snapshot_part (
    export_snapshot_id TEXT NOT NULL REFERENCES export_snapshot(export_snapshot_id),
    export_manifest_id TEXT NOT NULL UNIQUE REFERENCES export_manifest(export_manifest_id),
    PRIMARY KEY (export_snapshot_id, export_manifest_id)
) STRICT, WITHOUT ROWID;

-- The store runs the matching completeness queries before commit. These triggers preserve the
-- append-only property after a complete row set exists without making parent-before-sidecar
-- insertion impossible inside one transaction.
CREATE TRIGGER no_update_acquisition_contract BEFORE UPDATE ON acquisition_contract
BEGIN SELECT RAISE(ABORT, 'acquisition_contract is append-only'); END;
CREATE TRIGGER no_delete_acquisition_contract BEFORE DELETE ON acquisition_contract
BEGIN SELECT RAISE(ABORT, 'acquisition_contract is append-only'); END;
CREATE TRIGGER no_update_observation_contract BEFORE UPDATE ON observation_contract
BEGIN SELECT RAISE(ABORT, 'observation_contract is append-only'); END;
CREATE TRIGGER no_delete_observation_contract BEFORE DELETE ON observation_contract
BEGIN SELECT RAISE(ABORT, 'observation_contract is append-only'); END;
CREATE TRIGGER no_update_blob_object BEFORE UPDATE ON blob_object
BEGIN SELECT RAISE(ABORT, 'blob_object is append-only'); END;
CREATE TRIGGER no_delete_blob_object BEFORE DELETE ON blob_object
BEGIN SELECT RAISE(ABORT, 'blob_object is append-only'); END;
CREATE TRIGGER no_update_observation_blob_contract BEFORE UPDATE ON observation_blob_contract
BEGIN SELECT RAISE(ABORT, 'observation_blob_contract is append-only'); END;
CREATE TRIGGER no_delete_observation_blob_contract BEFORE DELETE ON observation_blob_contract
BEGIN SELECT RAISE(ABORT, 'observation_blob_contract is append-only'); END;
CREATE TRIGGER no_update_scene_artifact_contract BEFORE UPDATE ON scene_artifact_contract
BEGIN SELECT RAISE(ABORT, 'scene_artifact_contract is append-only'); END;
CREATE TRIGGER no_delete_scene_artifact_contract BEFORE DELETE ON scene_artifact_contract
BEGIN SELECT RAISE(ABORT, 'scene_artifact_contract is append-only'); END;
CREATE TRIGGER no_update_command_payload_contract BEFORE UPDATE ON command_payload_contract
BEGIN SELECT RAISE(ABORT, 'command_payload_contract is append-only'); END;
CREATE TRIGGER no_delete_command_payload_contract BEFORE DELETE ON command_payload_contract
BEGIN SELECT RAISE(ABORT, 'command_payload_contract is append-only'); END;
CREATE TRIGGER no_update_source_event_contract BEFORE UPDATE ON source_event_contract
BEGIN SELECT RAISE(ABORT, 'source_event_contract is append-only'); END;
CREATE TRIGGER no_delete_source_event_contract BEFORE DELETE ON source_event_contract
BEGIN SELECT RAISE(ABORT, 'source_event_contract is append-only'); END;
CREATE TRIGGER no_update_observation_source_event_contract
BEFORE UPDATE ON observation_source_event_contract
BEGIN SELECT RAISE(ABORT, 'observation_source_event_contract is append-only'); END;
CREATE TRIGGER no_delete_observation_source_event_contract
BEFORE DELETE ON observation_source_event_contract
BEGIN SELECT RAISE(ABORT, 'observation_source_event_contract is append-only'); END;
CREATE TRIGGER no_update_assertion_contract BEFORE UPDATE ON assertion_contract
BEGIN SELECT RAISE(ABORT, 'assertion_contract is append-only'); END;
CREATE TRIGGER no_delete_assertion_contract BEFORE DELETE ON assertion_contract
BEGIN SELECT RAISE(ABORT, 'assertion_contract is append-only'); END;
CREATE TRIGGER no_update_assertion_observation_evidence_contract
BEFORE UPDATE ON assertion_observation_evidence_contract
BEGIN SELECT RAISE(ABORT, 'assertion_observation_evidence_contract is append-only'); END;
CREATE TRIGGER no_delete_assertion_observation_evidence_contract
BEFORE DELETE ON assertion_observation_evidence_contract
BEGIN SELECT RAISE(ABORT, 'assertion_observation_evidence_contract is append-only'); END;
CREATE TRIGGER no_update_assertion_source_event_contract
BEFORE UPDATE ON assertion_source_event_contract
BEGIN SELECT RAISE(ABORT, 'assertion_source_event_contract is append-only'); END;
CREATE TRIGGER no_delete_assertion_source_event_contract
BEFORE DELETE ON assertion_source_event_contract
BEGIN SELECT RAISE(ABORT, 'assertion_source_event_contract is append-only'); END;
CREATE TRIGGER no_update_assertion_command_evidence_contract
BEFORE UPDATE ON assertion_command_evidence_contract
BEGIN SELECT RAISE(ABORT, 'assertion_command_evidence_contract is append-only'); END;
CREATE TRIGGER no_delete_assertion_command_evidence_contract
BEFORE DELETE ON assertion_command_evidence_contract
BEGIN SELECT RAISE(ABORT, 'assertion_command_evidence_contract is append-only'); END;
CREATE TRIGGER no_update_coverage_window_contract BEFORE UPDATE ON coverage_window_contract
BEGIN SELECT RAISE(ABORT, 'coverage_window_contract is append-only'); END;
CREATE TRIGGER no_delete_coverage_window_contract BEFORE DELETE ON coverage_window_contract
BEGIN SELECT RAISE(ABORT, 'coverage_window_contract is append-only'); END;
CREATE TRIGGER no_update_coverage_gap_contract BEFORE UPDATE ON coverage_gap_contract
BEGIN SELECT RAISE(ABORT, 'coverage_gap_contract is append-only'); END;
CREATE TRIGGER no_delete_coverage_gap_contract BEFORE DELETE ON coverage_gap_contract
BEGIN SELECT RAISE(ABORT, 'coverage_gap_contract is append-only'); END;
CREATE TRIGGER no_update_coverage_recovery_contract BEFORE UPDATE ON coverage_recovery_contract
BEGIN SELECT RAISE(ABORT, 'coverage_recovery_contract is append-only'); END;
CREATE TRIGGER no_delete_coverage_recovery_contract BEFORE DELETE ON coverage_recovery_contract
BEGIN SELECT RAISE(ABORT, 'coverage_recovery_contract is append-only'); END;
CREATE TRIGGER no_update_coverage_recovery_observation
BEFORE UPDATE ON coverage_recovery_observation
BEGIN SELECT RAISE(ABORT, 'coverage_recovery_observation is append-only'); END;
CREATE TRIGGER no_delete_coverage_recovery_observation
BEFORE DELETE ON coverage_recovery_observation
BEGIN SELECT RAISE(ABORT, 'coverage_recovery_observation is append-only'); END;
CREATE TRIGGER no_update_source_cursor_contract BEFORE UPDATE ON source_cursor_contract
BEGIN SELECT RAISE(ABORT, 'source_cursor_contract is append-only'); END;
CREATE TRIGGER no_delete_source_cursor_contract BEFORE DELETE ON source_cursor_contract
BEGIN SELECT RAISE(ABORT, 'source_cursor_contract is append-only'); END;
CREATE TRIGGER no_update_blob_object_disposal BEFORE UPDATE ON blob_object_disposal
BEGIN SELECT RAISE(ABORT, 'blob_object_disposal is append-only'); END;
CREATE TRIGGER no_delete_blob_object_disposal BEFORE DELETE ON blob_object_disposal
BEGIN SELECT RAISE(ABORT, 'blob_object_disposal is append-only'); END;
CREATE TRIGGER no_update_export_snapshot BEFORE UPDATE ON export_snapshot
BEGIN SELECT RAISE(ABORT, 'export_snapshot is append-only'); END;
CREATE TRIGGER no_delete_export_snapshot BEFORE DELETE ON export_snapshot
BEGIN SELECT RAISE(ABORT, 'export_snapshot is append-only'); END;
CREATE TRIGGER no_update_export_snapshot_part BEFORE UPDATE ON export_snapshot_part
BEGIN SELECT RAISE(ABORT, 'export_snapshot_part is append-only'); END;
CREATE TRIGGER no_delete_export_snapshot_part BEFORE DELETE ON export_snapshot_part
BEGIN SELECT RAISE(ABORT, 'export_snapshot_part is append-only'); END;

CREATE VIEW durable_source_watermark AS
SELECT o.source_id,
       MAX(o.commit_seq) AS delivered_through_commit_seq,
       MAX(o.received_wall_us) AS received_through_wall_us,
       NULL AS justified_cursor_value
FROM observation AS o
GROUP BY o.source_id;
