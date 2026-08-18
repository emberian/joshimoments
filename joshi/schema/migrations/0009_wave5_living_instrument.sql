-- Wave 5 Phase-0 authority spine.
--
-- These tables close exact run, circulation, operational-status, export-validation, and
-- restricted-import occurrences. They add no network, wallet, signing, submission, trading, or
-- liquidity authority. SHA-256 values are stored without the `sha256:` wire prefix.

CREATE TABLE wave5_run_registration_v1 (
    run_registration_id TEXT PRIMARY KEY CHECK (
        length(run_registration_id) BETWEEN 1 AND 512
        AND run_registration_id = trim(run_registration_id)
    ),
    registration_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(registration_sha256) = 64
        AND registration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    registration_bytes BLOB NOT NULL,
    registration_byte_length INTEGER NOT NULL CHECK (
        registration_byte_length > 0
        AND length(registration_bytes) = registration_byte_length
    ),
    build_sha256 TEXT NOT NULL CHECK (
        length(build_sha256) = 64 AND build_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    build_bytes BLOB NOT NULL,
    build_byte_length INTEGER NOT NULL CHECK (
        build_byte_length > 0 AND length(build_bytes) = build_byte_length
    ),
    source_tree_sha256 TEXT NOT NULL CHECK (
        length(source_tree_sha256) = 64 AND source_tree_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    source_tree_bytes BLOB NOT NULL,
    source_tree_byte_length INTEGER NOT NULL CHECK (
        source_tree_byte_length > 0 AND length(source_tree_bytes) = source_tree_byte_length
    ),
    configuration_sha256 TEXT NOT NULL CHECK (
        length(configuration_sha256) = 64 AND configuration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    configuration_bytes BLOB NOT NULL,
    configuration_byte_length INTEGER NOT NULL CHECK (
        configuration_byte_length > 0 AND length(configuration_bytes) = configuration_byte_length
    ),
    budget_sha256 TEXT NOT NULL CHECK (
        length(budget_sha256) = 64 AND budget_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    budget_bytes BLOB NOT NULL,
    budget_byte_length INTEGER NOT NULL CHECK (
        budget_byte_length > 0 AND length(budget_bytes) = budget_byte_length
    ),
    privacy_sha256 TEXT NOT NULL CHECK (
        length(privacy_sha256) = 64 AND privacy_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    privacy_bytes BLOB NOT NULL,
    privacy_byte_length INTEGER NOT NULL CHECK (
        privacy_byte_length > 0 AND length(privacy_bytes) = privacy_byte_length
    ),
    daily_surface_profile_sha256 TEXT NOT NULL CHECK (
        length(daily_surface_profile_sha256) = 64
        AND daily_surface_profile_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    daily_surface_profile_bytes BLOB NOT NULL,
    daily_surface_profile_byte_length INTEGER NOT NULL CHECK (
        daily_surface_profile_byte_length > 0
        AND length(daily_surface_profile_bytes) = daily_surface_profile_byte_length
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TABLE wave5_spool_catalog_binding_v1 (
    catalog_admission_id TEXT PRIMARY KEY CHECK (
        length(catalog_admission_id) BETWEEN 1 AND 512
        AND catalog_admission_id = trim(catalog_admission_id)
    ),
    run_registration_id TEXT NOT NULL REFERENCES wave5_run_registration_v1(run_registration_id),
    run_registration_sha256 TEXT NOT NULL CHECK (
        length(run_registration_sha256) = 64
        AND run_registration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    segment_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    binding_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(binding_sha256) = 64 AND binding_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    binding_bytes BLOB NOT NULL,
    binding_byte_length INTEGER NOT NULL CHECK (
        binding_byte_length > 0 AND length(binding_bytes) = binding_byte_length
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    FOREIGN KEY (segment_id, batch_id)
        REFERENCES spool_catalog_admission(segment_id, batch_id),
    UNIQUE (segment_id, batch_id)
) STRICT;

CREATE TRIGGER wave5_spool_catalog_binding_closes_run
BEFORE INSERT ON wave5_spool_catalog_binding_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_run_registration_v1 r
        WHERE r.run_registration_id = NEW.run_registration_id
          AND r.registration_sha256 = NEW.run_registration_sha256
          AND r.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'spool/catalog binding does not close an earlier exact run') END;
END;

CREATE TABLE wave5_operational_record_v1 (
    record_id TEXT PRIMARY KEY CHECK (
        length(record_id) BETWEEN 1 AND 512 AND record_id = trim(record_id)
    ),
    run_registration_id TEXT NOT NULL REFERENCES wave5_run_registration_v1(run_registration_id),
    run_registration_sha256 TEXT NOT NULL CHECK (
        length(run_registration_sha256) = 64
        AND run_registration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    component TEXT NOT NULL CHECK (component IN (
        'supervisor', 'source', 'evidence_queue', 'spool', 'replica', 'catalog',
        'normalizer', 'projection', 'glass', 'export', 'analysis', 'host'
    )),
    record_kind TEXT NOT NULL CHECK (record_kind IN (
        'status', 'degradation', 'recovery_started', 'recovery_verified', 'stopped'
    )),
    state TEXT NOT NULL CHECK (state IN (
        'ready', 'degraded', 'unavailable', 'gap', 'backlogged', 'stale',
        'recovering', 'refused', 'stopped'
    )),
    cause TEXT CHECK (cause IS NULL OR (cause <> '' AND cause = trim(cause))),
    predecessor_record_id TEXT REFERENCES wave5_operational_record_v1(record_id),
    evidence_commit_seq INTEGER REFERENCES ingest_commit(commit_seq),
    observed_wall_us INTEGER NOT NULL CHECK (observed_wall_us > 0),
    detail_sha256 TEXT CHECK (
        detail_sha256 IS NULL OR (
            length(detail_sha256) = 64 AND detail_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    record_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(record_sha256) = 64 AND record_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    record_bytes BLOB NOT NULL,
    record_byte_length INTEGER NOT NULL CHECK (
        record_byte_length > 0 AND length(record_bytes) = record_byte_length
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    CHECK (predecessor_record_id IS NULL OR predecessor_record_id <> record_id),
    CHECK (evidence_commit_seq IS NULL OR evidence_commit_seq < created_commit_seq),
    CHECK (
        (record_kind IN ('recovery_started', 'recovery_verified')
            AND predecessor_record_id IS NOT NULL)
        OR (record_kind NOT IN ('recovery_started', 'recovery_verified')
            AND predecessor_record_id IS NULL)
    ),
    CHECK (
        (record_kind = 'degradation' AND state IN (
            'degraded', 'unavailable', 'gap', 'backlogged', 'stale', 'refused'
        ))
        OR (record_kind = 'recovery_started' AND state = 'recovering')
        OR (record_kind = 'recovery_verified' AND state IN ('ready', 'degraded'))
        OR (record_kind = 'stopped' AND state = 'stopped')
        OR record_kind = 'status'
    )
) STRICT;

CREATE TRIGGER wave5_operational_record_closes_run_and_predecessor
BEFORE INSERT ON wave5_operational_record_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_run_registration_v1 r
        WHERE r.run_registration_id = NEW.run_registration_id
          AND r.registration_sha256 = NEW.run_registration_sha256
          AND r.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'operational record does not close an earlier exact run') END;
    SELECT CASE WHEN NEW.predecessor_record_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM wave5_operational_record_v1 p
        WHERE p.record_id = NEW.predecessor_record_id
          AND p.run_registration_id = NEW.run_registration_id
          AND p.component = NEW.component
          AND p.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'operational predecessor is foreign, cross-component, or nonprior') END;
END;

CREATE TABLE wave5_export_validation_binding_v1 (
    export_binding_id TEXT PRIMARY KEY CHECK (
        length(export_binding_id) BETWEEN 1 AND 512 AND export_binding_id = trim(export_binding_id)
    ),
    run_registration_id TEXT NOT NULL REFERENCES wave5_run_registration_v1(run_registration_id),
    run_registration_sha256 TEXT NOT NULL CHECK (
        length(run_registration_sha256) = 64
        AND run_registration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    export_request_id TEXT NOT NULL REFERENCES production_export_request_v2(export_request_id),
    validation_id TEXT NOT NULL REFERENCES export_validation(validation_id),
    snapshot_id TEXT NOT NULL REFERENCES export_snapshot(export_snapshot_id),
    binding_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(binding_sha256) = 64 AND binding_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    binding_bytes BLOB NOT NULL,
    binding_byte_length INTEGER NOT NULL CHECK (
        binding_byte_length > 0 AND length(binding_bytes) = binding_byte_length
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    UNIQUE (export_request_id)
) STRICT;

CREATE TRIGGER wave5_export_binding_closes_run_and_validated_export
BEFORE INSERT ON wave5_export_validation_binding_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_run_registration_v1 r
        WHERE r.run_registration_id = NEW.run_registration_id
          AND r.registration_sha256 = NEW.run_registration_sha256
          AND r.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'export binding does not close an earlier exact run') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM production_export_request_v2 e
        JOIN export_validation v ON v.validation_id = e.validation_id
        WHERE e.export_request_id = NEW.export_request_id
          AND e.validation_id = NEW.validation_id
          AND e.snapshot_id = NEW.snapshot_id
          AND e.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'export binding does not close one exact validated export') END;
END;

CREATE TABLE wave5_restricted_artifact_v1 (
    import_id TEXT PRIMARY KEY CHECK (
        length(import_id) BETWEEN 1 AND 512 AND import_id = trim(import_id)
    ),
    run_registration_id TEXT NOT NULL REFERENCES wave5_run_registration_v1(run_registration_id),
    run_registration_sha256 TEXT NOT NULL CHECK (
        length(run_registration_sha256) = 64
        AND run_registration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    export_binding_id TEXT NOT NULL
        REFERENCES wave5_export_validation_binding_v1(export_binding_id),
    export_request_id TEXT NOT NULL REFERENCES production_export_request_v2(export_request_id),
    analysis_run_id TEXT NOT NULL UNIQUE CHECK (
        length(analysis_run_id) BETWEEN 1 AND 512 AND analysis_run_id = trim(analysis_run_id)
    ),
    artifact_id TEXT NOT NULL UNIQUE CHECK (
        length(artifact_id) BETWEEN 1 AND 512 AND artifact_id = trim(artifact_id)
    ),
    artifact_contract TEXT NOT NULL CHECK (artifact_contract <> ''),
    manifest_sha256 TEXT NOT NULL CHECK (
        length(manifest_sha256) = 64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    manifest_bytes BLOB NOT NULL,
    manifest_byte_length INTEGER NOT NULL CHECK (
        manifest_byte_length > 0 AND length(manifest_bytes) = manifest_byte_length
    ),
    snapshot_id TEXT NOT NULL REFERENCES export_snapshot(export_snapshot_id),
    claim_scope TEXT NOT NULL CHECK (claim_scope = 'descriptive_noncausal'),
    truth_fingerprint_sha256 TEXT NOT NULL CHECK (
        length(truth_fingerprint_sha256) = 64
        AND truth_fingerprint_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    maximum_input_available_wall_us INTEGER NOT NULL CHECK (
        maximum_input_available_wall_us > 0
    ),
    registration_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(registration_sha256) = 64
        AND registration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    registration_bytes BLOB NOT NULL,
    registration_byte_length INTEGER NOT NULL CHECK (
        registration_byte_length > 0 AND length(registration_bytes) = registration_byte_length
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TRIGGER wave5_restricted_artifact_closes_export_and_run
BEFORE INSERT ON wave5_restricted_artifact_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM wave5_export_validation_binding_v1 b
        JOIN wave5_run_registration_v1 r
          ON r.run_registration_id = b.run_registration_id
        JOIN production_export_request_v2 e
          ON e.export_request_id = b.export_request_id
        WHERE b.export_binding_id = NEW.export_binding_id
          AND b.export_request_id = NEW.export_request_id
          AND b.run_registration_id = NEW.run_registration_id
          AND b.run_registration_sha256 = NEW.run_registration_sha256
          AND r.registration_sha256 = NEW.run_registration_sha256
          AND e.snapshot_id = NEW.snapshot_id
          AND e.truth_fingerprint_sha256 = NEW.truth_fingerprint_sha256
          AND b.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'restricted artifact does not close exact run/export/truth') END;
END;

CREATE TABLE wave5_restricted_artifact_part_v1 (
    import_id TEXT NOT NULL REFERENCES wave5_restricted_artifact_v1(import_id),
    part_ordinal INTEGER NOT NULL CHECK (part_ordinal = 0),
    blob_id TEXT NOT NULL,
    storage_domain TEXT NOT NULL CHECK (storage_domain = 'public_source'),
    physical_sha256 TEXT NOT NULL CHECK (
        length(physical_sha256) = 64
        AND physical_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    byte_length INTEGER NOT NULL CHECK (byte_length > 0),
    PRIMARY KEY (import_id, part_ordinal),
    FOREIGN KEY (blob_id, storage_domain) REFERENCES blob_object(blob_id, storage_domain),
    CHECK (physical_sha256 = blob_id)
) STRICT, WITHOUT ROWID;

CREATE TRIGGER wave5_restricted_artifact_part_closes_blob
BEFORE INSERT ON wave5_restricted_artifact_part_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM blob_object b
        WHERE b.blob_id = NEW.blob_id
          AND b.storage_domain = NEW.storage_domain
          AND b.stored_sha256 = NEW.physical_sha256
          AND b.stored_length = NEW.byte_length
    ) THEN RAISE(ABORT, 'restricted artifact part does not close exact durable CAS bytes') END;
END;

CREATE TRIGGER no_update_wave5_run_registration_v1
BEFORE UPDATE ON wave5_run_registration_v1
BEGIN SELECT RAISE(ABORT, 'wave5_run_registration_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_run_registration_v1
BEFORE DELETE ON wave5_run_registration_v1
BEGIN SELECT RAISE(ABORT, 'wave5_run_registration_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_spool_catalog_binding_v1
BEFORE UPDATE ON wave5_spool_catalog_binding_v1
BEGIN SELECT RAISE(ABORT, 'wave5_spool_catalog_binding_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_spool_catalog_binding_v1
BEFORE DELETE ON wave5_spool_catalog_binding_v1
BEGIN SELECT RAISE(ABORT, 'wave5_spool_catalog_binding_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_operational_record_v1
BEFORE UPDATE ON wave5_operational_record_v1
BEGIN SELECT RAISE(ABORT, 'wave5_operational_record_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_operational_record_v1
BEFORE DELETE ON wave5_operational_record_v1
BEGIN SELECT RAISE(ABORT, 'wave5_operational_record_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_export_validation_binding_v1
BEFORE UPDATE ON wave5_export_validation_binding_v1
BEGIN SELECT RAISE(ABORT, 'wave5_export_validation_binding_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_export_validation_binding_v1
BEFORE DELETE ON wave5_export_validation_binding_v1
BEGIN SELECT RAISE(ABORT, 'wave5_export_validation_binding_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_restricted_artifact_v1
BEFORE UPDATE ON wave5_restricted_artifact_v1
BEGIN SELECT RAISE(ABORT, 'wave5_restricted_artifact_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_restricted_artifact_v1
BEFORE DELETE ON wave5_restricted_artifact_v1
BEGIN SELECT RAISE(ABORT, 'wave5_restricted_artifact_v1 is append-only'); END;
CREATE TRIGGER no_update_wave5_restricted_artifact_part_v1
BEFORE UPDATE ON wave5_restricted_artifact_part_v1
BEGIN SELECT RAISE(ABORT, 'wave5_restricted_artifact_part_v1 is append-only'); END;
CREATE TRIGGER no_delete_wave5_restricted_artifact_part_v1
BEFORE DELETE ON wave5_restricted_artifact_part_v1
BEGIN SELECT RAISE(ABORT, 'wave5_restricted_artifact_part_v1 is append-only'); END;
