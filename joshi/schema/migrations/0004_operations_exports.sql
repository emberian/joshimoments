-- Forward-only migration 0004: rebuildable projections, bounded work, and immutable exports.

CREATE TABLE projection_version (
    projection_name TEXT NOT NULL CHECK (projection_name <> ''),
    projection_version TEXT NOT NULL CHECK (projection_version <> ''),
    producer_build TEXT NOT NULL CHECK (producer_build <> ''),
    configuration_sha256 TEXT NOT NULL CHECK (
        length(configuration_sha256) = 64
        AND configuration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    schema_sha256 TEXT NOT NULL CHECK (
        length(schema_sha256) = 64 AND schema_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    deterministic INTEGER NOT NULL CHECK (deterministic IN (0, 1)),
    PRIMARY KEY (projection_name, projection_version)
) STRICT, WITHOUT ROWID;

CREATE TABLE projection_checkpoint (
    checkpoint_id TEXT PRIMARY KEY CHECK (
        length(checkpoint_id) BETWEEN 1 AND 512 AND checkpoint_id = trim(checkpoint_id)
    ),
    projection_name TEXT NOT NULL,
    projection_version TEXT NOT NULL,
    through_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    created_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    input_manifest_sha256 TEXT NOT NULL CHECK (
        length(input_manifest_sha256) = 64
        AND input_manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    output_sha256 TEXT NOT NULL CHECK (
        length(output_sha256) = 64 AND output_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    FOREIGN KEY (projection_name, projection_version)
        REFERENCES projection_version(projection_name, projection_version),
    UNIQUE (projection_name, projection_version, through_commit_seq),
    CHECK (through_commit_seq <= created_commit_seq)
) STRICT;

CREATE TABLE outbox_item (
    outbox_id TEXT PRIMARY KEY CHECK (
        length(outbox_id) BETWEEN 1 AND 512 AND outbox_id = trim(outbox_id)
    ),
    enqueued_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    item_kind TEXT NOT NULL CHECK (item_kind <> ''),
    effect_class TEXT NOT NULL CHECK (
        effect_class IN ('projection', 'export', 'thumbnail', 'analysis')
    ),
    payload_blob_id TEXT NOT NULL REFERENCES blob(blob_id),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (idempotency_key <> ''),
    not_before_wall_us INTEGER NOT NULL CHECK (not_before_wall_us > 0),
    status TEXT NOT NULL CHECK (status IN ('pending', 'leased', 'done', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_owner TEXT,
    lease_expires_wall_us INTEGER CHECK (lease_expires_wall_us IS NULL OR lease_expires_wall_us > 0),
    completed_wall_us INTEGER CHECK (completed_wall_us IS NULL OR completed_wall_us > 0),
    last_error_code TEXT,
    CHECK (
        (status = 'leased' AND lease_owner IS NOT NULL AND lease_expires_wall_us IS NOT NULL)
        OR (status <> 'leased' AND lease_owner IS NULL AND lease_expires_wall_us IS NULL)
    ),
    CHECK (
        (status = 'done' AND completed_wall_us IS NOT NULL)
        OR (status <> 'done' AND completed_wall_us IS NULL)
    )
) STRICT;

CREATE TABLE export_manifest (
    export_manifest_id TEXT PRIMARY KEY CHECK (
        length(export_manifest_id) BETWEEN 1 AND 512 AND export_manifest_id = trim(export_manifest_id)
    ),
    family TEXT NOT NULL CHECK (family <> ''),
    family_schema_version INTEGER NOT NULL CHECK (family_schema_version > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    part_ordinal INTEGER NOT NULL CHECK (part_ordinal >= 0),
    projection_name TEXT NOT NULL,
    projection_version TEXT NOT NULL,
    from_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    through_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    created_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    input_manifest_sha256 TEXT NOT NULL CHECK (
        length(input_manifest_sha256) = 64
        AND input_manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    relative_path TEXT NOT NULL UNIQUE CHECK (
        relative_path <> ''
        AND substr(relative_path, 1, 1) <> '/'
        AND relative_path NOT GLOB '*../*'
        AND relative_path NOT GLOB '../*'
    ),
    file_sha256 TEXT NOT NULL CHECK (
        length(file_sha256) = 64 AND file_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
    row_count INTEGER NOT NULL CHECK (row_count >= 0),
    format TEXT NOT NULL CHECK (format IN ('parquet', 'fixture_opaque')),
    compression TEXT NOT NULL CHECK (compression <> ''),
    writer_version TEXT NOT NULL CHECK (writer_version <> ''),
    schema_sha256 TEXT NOT NULL CHECK (
        length(schema_sha256) = 64 AND schema_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    event_lower_us INTEGER,
    event_upper_us INTEGER,
    min_chain_slot INTEGER CHECK (min_chain_slot IS NULL OR min_chain_slot >= 0),
    max_chain_slot INTEGER CHECK (max_chain_slot IS NULL OR max_chain_slot >= 0),
    retention_class TEXT NOT NULL CHECK (
        retention_class IN ('public_chain', 'public_source', 'social_media', 'app_private',
                            'operator_private', 'fixture', 'disposable')
    ),
    FOREIGN KEY (projection_name, projection_version)
        REFERENCES projection_version(projection_name, projection_version),
    UNIQUE (family, family_schema_version, generation, part_ordinal),
    CHECK (from_commit_seq <= through_commit_seq),
    CHECK (through_commit_seq <= created_commit_seq),
    CHECK (
        (event_lower_us IS NULL AND event_upper_us IS NULL)
        OR (event_lower_us IS NOT NULL AND event_upper_us IS NOT NULL
            AND event_upper_us > event_lower_us)
    ),
    CHECK (
        (min_chain_slot IS NULL AND max_chain_slot IS NULL)
        OR (min_chain_slot IS NOT NULL AND max_chain_slot IS NOT NULL
            AND max_chain_slot >= min_chain_slot)
    )
) STRICT;

CREATE TABLE export_supersession (
    supersession_id TEXT PRIMARY KEY CHECK (
        length(supersession_id) BETWEEN 1 AND 512 AND supersession_id = trim(supersession_id)
    ),
    old_export_manifest_id TEXT NOT NULL REFERENCES export_manifest(export_manifest_id),
    new_export_manifest_id TEXT NOT NULL REFERENCES export_manifest(export_manifest_id),
    committed_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    reason_code TEXT NOT NULL CHECK (reason_code <> ''),
    UNIQUE (old_export_manifest_id, new_export_manifest_id),
    CHECK (old_export_manifest_id <> new_export_manifest_id)
) STRICT;

CREATE TABLE blob_disposal (
    disposal_id TEXT PRIMARY KEY CHECK (
        length(disposal_id) BETWEEN 1 AND 512 AND disposal_id = trim(disposal_id)
    ),
    blob_id TEXT NOT NULL REFERENCES blob(blob_id),
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
    UNIQUE (blob_id, policy_id, disposition)
) STRICT;

CREATE INDEX projection_checkpoint_latest
    ON projection_checkpoint(projection_name, projection_version, through_commit_seq DESC);
CREATE INDEX outbox_ready
    ON outbox_item(status, not_before_wall_us, enqueued_commit_seq);
CREATE INDEX export_commit_range
    ON export_manifest(family, from_commit_seq, through_commit_seq);

CREATE VIEW latest_source_cursor AS
SELECT c.*
FROM source_cursor AS c
WHERE NOT EXISTS (
    SELECT 1
    FROM source_cursor AS later
    WHERE later.source_id = c.source_id
      AND later.scope_kind = c.scope_kind
      AND later.scope_key = c.scope_key
      AND later.cursor_kind = c.cursor_kind
      AND (later.advanced_commit_seq > c.advanced_commit_seq
           OR (later.advanced_commit_seq = c.advanced_commit_seq
               AND later.cursor_id > c.cursor_id))
);

-- Evidence rows are immutable in ordinary operation. Operational outbox leases are intentionally
-- excluded. Retention deletes bytes outside SQLite and appends blob_disposal; it does not rewrite
-- the evidence row.
CREATE TRIGGER no_update_ingest_commit BEFORE UPDATE ON ingest_commit
BEGIN SELECT RAISE(ABORT, 'ingest_commit is append-only'); END;
CREATE TRIGGER no_delete_ingest_commit BEFORE DELETE ON ingest_commit
BEGIN SELECT RAISE(ABORT, 'ingest_commit is append-only'); END;
CREATE TRIGGER no_update_source BEFORE UPDATE ON source
BEGIN SELECT RAISE(ABORT, 'source is append-only'); END;
CREATE TRIGGER no_delete_source BEFORE DELETE ON source
BEGIN SELECT RAISE(ABORT, 'source is append-only'); END;
CREATE TRIGGER no_update_acquisition BEFORE UPDATE ON acquisition
BEGIN SELECT RAISE(ABORT, 'acquisition is append-only'); END;
CREATE TRIGGER no_delete_acquisition BEFORE DELETE ON acquisition
BEGIN SELECT RAISE(ABORT, 'acquisition is append-only'); END;
CREATE TRIGGER no_update_acquisition_end BEFORE UPDATE ON acquisition_end
BEGIN SELECT RAISE(ABORT, 'acquisition_end is append-only'); END;
CREATE TRIGGER no_delete_acquisition_end BEFORE DELETE ON acquisition_end
BEGIN SELECT RAISE(ABORT, 'acquisition_end is append-only'); END;
CREATE TRIGGER no_update_blob BEFORE UPDATE ON blob
BEGIN SELECT RAISE(ABORT, 'blob is append-only'); END;
CREATE TRIGGER no_delete_blob BEFORE DELETE ON blob
BEGIN SELECT RAISE(ABORT, 'blob is append-only'); END;
CREATE TRIGGER no_update_observation BEFORE UPDATE ON observation
BEGIN SELECT RAISE(ABORT, 'observation is append-only'); END;
CREATE TRIGGER no_delete_observation BEFORE DELETE ON observation
BEGIN SELECT RAISE(ABORT, 'observation is append-only'); END;
CREATE TRIGGER no_update_source_event BEFORE UPDATE ON source_event
BEGIN SELECT RAISE(ABORT, 'source_event is append-only'); END;
CREATE TRIGGER no_delete_source_event BEFORE DELETE ON source_event
BEGIN SELECT RAISE(ABORT, 'source_event is append-only'); END;
CREATE TRIGGER no_update_observation_source_event BEFORE UPDATE ON observation_source_event
BEGIN SELECT RAISE(ABORT, 'observation_source_event is append-only'); END;
CREATE TRIGGER no_delete_observation_source_event BEFORE DELETE ON observation_source_event
BEGIN SELECT RAISE(ABORT, 'observation_source_event is append-only'); END;
CREATE TRIGGER no_update_assertion BEFORE UPDATE ON assertion
BEGIN SELECT RAISE(ABORT, 'assertion is append-only'); END;
CREATE TRIGGER no_delete_assertion BEFORE DELETE ON assertion
BEGIN SELECT RAISE(ABORT, 'assertion is append-only'); END;
CREATE TRIGGER no_update_assertion_observation_evidence BEFORE UPDATE ON assertion_observation_evidence
BEGIN SELECT RAISE(ABORT, 'assertion_observation_evidence is append-only'); END;
CREATE TRIGGER no_delete_assertion_observation_evidence BEFORE DELETE ON assertion_observation_evidence
BEGIN SELECT RAISE(ABORT, 'assertion_observation_evidence is append-only'); END;
CREATE TRIGGER no_update_assertion_source_event BEFORE UPDATE ON assertion_source_event
BEGIN SELECT RAISE(ABORT, 'assertion_source_event is append-only'); END;
CREATE TRIGGER no_delete_assertion_source_event BEFORE DELETE ON assertion_source_event
BEGIN SELECT RAISE(ABORT, 'assertion_source_event is append-only'); END;
CREATE TRIGGER no_update_assertion_amount BEFORE UPDATE ON assertion_amount
BEGIN SELECT RAISE(ABORT, 'assertion_amount is append-only'); END;
CREATE TRIGGER no_delete_assertion_amount BEFORE DELETE ON assertion_amount
BEGIN SELECT RAISE(ABORT, 'assertion_amount is append-only'); END;
CREATE TRIGGER no_update_assertion_command_evidence BEFORE UPDATE ON assertion_command_evidence
BEGIN SELECT RAISE(ABORT, 'assertion_command_evidence is append-only'); END;
CREATE TRIGGER no_delete_assertion_command_evidence BEFORE DELETE ON assertion_command_evidence
BEGIN SELECT RAISE(ABORT, 'assertion_command_evidence is append-only'); END;
CREATE TRIGGER no_update_coverage_window BEFORE UPDATE ON coverage_window
BEGIN SELECT RAISE(ABORT, 'coverage_window is append-only'); END;
CREATE TRIGGER no_delete_coverage_window BEFORE DELETE ON coverage_window
BEGIN SELECT RAISE(ABORT, 'coverage_window is append-only'); END;
CREATE TRIGGER no_update_coverage_event BEFORE UPDATE ON coverage_event
BEGIN SELECT RAISE(ABORT, 'coverage_event is append-only'); END;
CREATE TRIGGER no_delete_coverage_event BEFORE DELETE ON coverage_event
BEGIN SELECT RAISE(ABORT, 'coverage_event is append-only'); END;
CREATE TRIGGER no_update_coverage_gap BEFORE UPDATE ON coverage_gap
BEGIN SELECT RAISE(ABORT, 'coverage_gap is append-only'); END;
CREATE TRIGGER no_delete_coverage_gap BEFORE DELETE ON coverage_gap
BEGIN SELECT RAISE(ABORT, 'coverage_gap is append-only'); END;
CREATE TRIGGER no_update_coverage_gap_recovery BEFORE UPDATE ON coverage_gap_recovery
BEGIN SELECT RAISE(ABORT, 'coverage_gap_recovery is append-only'); END;
CREATE TRIGGER no_delete_coverage_gap_recovery BEFORE DELETE ON coverage_gap_recovery
BEGIN SELECT RAISE(ABORT, 'coverage_gap_recovery is append-only'); END;
CREATE TRIGGER no_update_source_cursor BEFORE UPDATE ON source_cursor
BEGIN SELECT RAISE(ABORT, 'source_cursor is append-only'); END;
CREATE TRIGGER no_delete_source_cursor BEFORE DELETE ON source_cursor
BEGIN SELECT RAISE(ABORT, 'source_cursor is append-only'); END;
CREATE TRIGGER no_update_source_cursor_evidence BEFORE UPDATE ON source_cursor_evidence
BEGIN SELECT RAISE(ABORT, 'source_cursor_evidence is append-only'); END;
CREATE TRIGGER no_delete_source_cursor_evidence BEFORE DELETE ON source_cursor_evidence
BEGIN SELECT RAISE(ABORT, 'source_cursor_evidence is append-only'); END;
CREATE TRIGGER no_update_scene BEFORE UPDATE ON scene
BEGIN SELECT RAISE(ABORT, 'scene is append-only'); END;
CREATE TRIGGER no_delete_scene BEFORE DELETE ON scene
BEGIN SELECT RAISE(ABORT, 'scene is append-only'); END;
CREATE TRIGGER no_update_scene_watermark BEFORE UPDATE ON scene_watermark
BEGIN SELECT RAISE(ABORT, 'scene_watermark is append-only'); END;
CREATE TRIGGER no_delete_scene_watermark BEFORE DELETE ON scene_watermark
BEGIN SELECT RAISE(ABORT, 'scene_watermark is append-only'); END;
CREATE TRIGGER no_update_scene_choice_member BEFORE UPDATE ON scene_choice_member
BEGIN SELECT RAISE(ABORT, 'scene_choice_member is append-only'); END;
CREATE TRIGGER no_delete_scene_choice_member BEFORE DELETE ON scene_choice_member
BEGIN SELECT RAISE(ABORT, 'scene_choice_member is append-only'); END;
CREATE TRIGGER no_update_command BEFORE UPDATE ON command
BEGIN SELECT RAISE(ABORT, 'command is append-only'); END;
CREATE TRIGGER no_delete_command BEFORE DELETE ON command
BEGIN SELECT RAISE(ABORT, 'command is append-only'); END;
CREATE TRIGGER no_update_projection_version BEFORE UPDATE ON projection_version
BEGIN SELECT RAISE(ABORT, 'projection_version is append-only'); END;
CREATE TRIGGER no_delete_projection_version BEFORE DELETE ON projection_version
BEGIN SELECT RAISE(ABORT, 'projection_version is append-only'); END;
CREATE TRIGGER no_update_projection_checkpoint BEFORE UPDATE ON projection_checkpoint
BEGIN SELECT RAISE(ABORT, 'projection_checkpoint is append-only'); END;
CREATE TRIGGER no_delete_projection_checkpoint BEFORE DELETE ON projection_checkpoint
BEGIN SELECT RAISE(ABORT, 'projection_checkpoint is append-only'); END;
CREATE TRIGGER no_update_export_manifest BEFORE UPDATE ON export_manifest
BEGIN SELECT RAISE(ABORT, 'export_manifest is append-only'); END;
CREATE TRIGGER no_delete_export_manifest BEFORE DELETE ON export_manifest
BEGIN SELECT RAISE(ABORT, 'export_manifest is append-only'); END;
CREATE TRIGGER no_update_export_supersession BEFORE UPDATE ON export_supersession
BEGIN SELECT RAISE(ABORT, 'export_supersession is append-only'); END;
CREATE TRIGGER no_delete_export_supersession BEFORE DELETE ON export_supersession
BEGIN SELECT RAISE(ABORT, 'export_supersession is append-only'); END;
CREATE TRIGGER no_update_blob_disposal BEFORE UPDATE ON blob_disposal
BEGIN SELECT RAISE(ABORT, 'blob_disposal is append-only'); END;
CREATE TRIGGER no_delete_blob_disposal BEFORE DELETE ON blob_disposal
BEGIN SELECT RAISE(ABORT, 'blob_disposal is append-only'); END;
CREATE TRIGGER no_update_schema_migration BEFORE UPDATE ON schema_migration
BEGIN SELECT RAISE(ABORT, 'schema_migration is append-only'); END;
CREATE TRIGGER no_delete_schema_migration BEFORE DELETE ON schema_migration
BEGIN SELECT RAISE(ABORT, 'schema_migration is append-only'); END;
