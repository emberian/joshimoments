-- Forward-only migration 0007: immutable operational artifact and acknowledgement closure.

CREATE TABLE source_fact_artifact (
    artifact_id TEXT PRIMARY KEY CHECK (
        length(artifact_id) BETWEEN 1 AND 512 AND artifact_id = trim(artifact_id)
    ),
    artifact_family TEXT NOT NULL CHECK (artifact_family IN (
        'source_fact', 'wallet_topology', 'social_attention', 'lifecycle',
        'pool_state', 'market_state', 'acquisition_policy'
    )),
    artifact_contract TEXT NOT NULL CHECK (artifact_contract <> ''),
    artifact_schema_version INTEGER NOT NULL CHECK (artifact_schema_version > 0),
    artifact_sha256 TEXT NOT NULL CHECK (
        length(artifact_sha256) = 64 AND artifact_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    artifact_bytes BLOB NOT NULL,
    artifact_byte_length INTEGER NOT NULL CHECK (
        artifact_byte_length > 0 AND length(artifact_bytes) = artifact_byte_length
    ),
    input_closure_sha256 TEXT NOT NULL CHECK (
        length(input_closure_sha256) = 64 AND input_closure_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    known_through_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    maximum_input_available_wall_us INTEGER NOT NULL CHECK (maximum_input_available_wall_us > 0),
    protection_class TEXT NOT NULL CHECK (
        protection_class IN ('public_integrity', 'authenticated_private')
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    UNIQUE (artifact_contract, artifact_sha256)
) STRICT;

CREATE TABLE projection_publication (
    publication_id TEXT PRIMARY KEY CHECK (
        length(publication_id) BETWEEN 1 AND 512 AND publication_id = trim(publication_id)
    ),
    projection_id TEXT NOT NULL CHECK (
        length(projection_id) BETWEEN 1 AND 512 AND projection_id = trim(projection_id)
    ),
    result_sha256 TEXT NOT NULL CHECK (
        length(result_sha256) = 64 AND result_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    artifact_sha256 TEXT NOT NULL CHECK (
        length(artifact_sha256) = 64 AND artifact_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    artifact_bytes BLOB NOT NULL,
    artifact_byte_length INTEGER NOT NULL CHECK (
        artifact_byte_length > 0 AND length(artifact_bytes) = artifact_byte_length
    ),
    input_closure_sha256 TEXT NOT NULL CHECK (
        length(input_closure_sha256) = 64 AND input_closure_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    publication_sha256 TEXT NOT NULL CHECK (
        length(publication_sha256) = 64 AND publication_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    publication_bytes_sha256 TEXT NOT NULL CHECK (
        length(publication_bytes_sha256) = 64
        AND publication_bytes_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    publication_bytes BLOB NOT NULL,
    publication_byte_length INTEGER NOT NULL CHECK (
        publication_byte_length > 0 AND length(publication_bytes) = publication_byte_length
    ),
    through_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    supersedes_publication_id TEXT REFERENCES projection_publication(publication_id),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    UNIQUE (projection_id, result_sha256, through_commit_seq),
    CHECK (supersedes_publication_id IS NULL OR supersedes_publication_id <> publication_id),
    CHECK (through_commit_seq < created_commit_seq)
) STRICT;

CREATE TABLE cockpit_publication (
    cockpit_publication_id TEXT PRIMARY KEY CHECK (
        length(cockpit_publication_id) BETWEEN 1 AND 512
        AND cockpit_publication_id = trim(cockpit_publication_id)
    ),
    scene_id TEXT NOT NULL REFERENCES scene(scene_id),
    projection_publication_id TEXT NOT NULL REFERENCES projection_publication(publication_id),
    projection_publication_sha256 TEXT NOT NULL CHECK (
        length(projection_publication_sha256) = 64
        AND projection_publication_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    projection_result_sha256 TEXT NOT NULL CHECK (
        length(projection_result_sha256) = 64
        AND projection_result_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    projection_artifact_sha256 TEXT NOT NULL CHECK (
        length(projection_artifact_sha256) = 64
        AND projection_artifact_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    query_policy TEXT NOT NULL CHECK (query_policy <> ''),
    manifest_sha256 TEXT NOT NULL CHECK (
        length(manifest_sha256) = 64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    cockpit_publication_sha256 TEXT NOT NULL CHECK (
        length(cockpit_publication_sha256) = 64
        AND cockpit_publication_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    manifest_bytes BLOB NOT NULL,
    manifest_byte_length INTEGER NOT NULL CHECK (
        manifest_byte_length > 0 AND length(manifest_bytes) = manifest_byte_length
    ),
    supersedes_cockpit_publication_id TEXT REFERENCES cockpit_publication(cockpit_publication_id),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    CHECK (
        supersedes_cockpit_publication_id IS NULL
        OR supersedes_cockpit_publication_id <> cockpit_publication_id
    )
) STRICT;

CREATE TABLE presentation_scene_v1 (
    presentation_id TEXT PRIMARY KEY CHECK (
        length(presentation_id) BETWEEN 1 AND 512 AND presentation_id = trim(presentation_id)
    ),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(idempotency_key) BETWEEN 1 AND 512 AND idempotency_key = trim(idempotency_key)
    ),
    assignment_id TEXT NOT NULL CHECK (assignment_id <> ''),
    scene_id TEXT NOT NULL REFERENCES scene(scene_id),
    view_sha256 TEXT NOT NULL CHECK (
        length(view_sha256) = 64 AND view_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    policy_sha256 TEXT NOT NULL CHECK (
        length(policy_sha256) = 64 AND policy_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    presentation_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(presentation_sha256) = 64 AND presentation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    admission_sha256 TEXT NOT NULL CHECK (
        length(admission_sha256) = 64 AND admission_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    admission_bytes BLOB NOT NULL,
    admission_byte_length INTEGER NOT NULL CHECK (
        admission_byte_length > 0 AND length(admission_bytes) = admission_byte_length
    ),
    client_session_id TEXT NOT NULL CHECK (client_session_id <> ''),
    presentation_seq TEXT NOT NULL CHECK (
        presentation_seq = '0' OR (
            presentation_seq NOT GLOB '*[^0-9]*'
            AND substr(presentation_seq, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    captured_wall_us INTEGER NOT NULL CHECK (captured_wall_us > 0),
    client_clock_id TEXT NOT NULL CHECK (client_clock_id <> ''),
    captured_mono_ns TEXT NOT NULL CHECK (
        captured_mono_ns = '0' OR (
            captured_mono_ns NOT GLOB '*[^0-9]*'
            AND substr(captured_mono_ns, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    authority_class TEXT NOT NULL CHECK (authority_class = 'evidence_only'),
    effect_ceiling TEXT NOT NULL CHECK (effect_ceiling = 'observe_only'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TABLE presentation_event_v1 (
    event_id TEXT PRIMARY KEY CHECK (
        length(event_id) BETWEEN 1 AND 512 AND event_id = trim(event_id)
    ),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(idempotency_key) BETWEEN 1 AND 512 AND idempotency_key = trim(idempotency_key)
    ),
    presentation_id TEXT NOT NULL REFERENCES presentation_scene_v1(presentation_id),
    presentation_sha256 TEXT NOT NULL CHECK (
        length(presentation_sha256) = 64 AND presentation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    scene_id TEXT NOT NULL REFERENCES scene(scene_id),
    view_sha256 TEXT NOT NULL CHECK (
        length(view_sha256) = 64 AND view_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    event_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(event_sha256) = 64 AND event_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    event_bytes BLOB NOT NULL,
    event_byte_length INTEGER NOT NULL CHECK (
        event_byte_length > 0 AND length(event_bytes) = event_byte_length
    ),
    client_session_id TEXT NOT NULL CHECK (client_session_id <> ''),
    presentation_event_seq TEXT NOT NULL CHECK (
        presentation_event_seq = '0' OR (
            presentation_event_seq NOT GLOB '*[^0-9]*'
            AND substr(presentation_event_seq, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'focus_started', 'focus_ended', 'visibility_started', 'visibility_ended',
        'control_changed', 'voice_capture_hook', 'usefulness_reported'
    )),
    occurred_wall_us INTEGER NOT NULL CHECK (occurred_wall_us > 0),
    client_clock_id TEXT NOT NULL CHECK (client_clock_id <> ''),
    occurred_mono_ns TEXT NOT NULL CHECK (
        occurred_mono_ns = '0' OR (
            occurred_mono_ns NOT GLOB '*[^0-9]*'
            AND substr(occurred_mono_ns, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    authority_class TEXT NOT NULL CHECK (authority_class = 'evidence_only'),
    effect_ceiling TEXT NOT NULL CHECK (effect_ceiling = 'observe_only'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    UNIQUE (presentation_id, client_session_id, presentation_event_seq)
) STRICT;

CREATE TABLE export_validation (
    validation_id TEXT PRIMARY KEY CHECK (
        length(validation_id) BETWEEN 1 AND 512 AND validation_id = trim(validation_id)
    ),
    export_snapshot_id TEXT NOT NULL REFERENCES export_snapshot(export_snapshot_id),
    manifest_sha256 TEXT NOT NULL CHECK (
        length(manifest_sha256) = 64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    rust_validation_sha256 TEXT NOT NULL CHECK (
        length(rust_validation_sha256) = 64 AND rust_validation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    python_validation_sha256 TEXT NOT NULL CHECK (
        length(python_validation_sha256) = 64 AND python_validation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    validation_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(validation_sha256) = 64 AND validation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    validation_bytes BLOB NOT NULL,
    validation_byte_length INTEGER NOT NULL CHECK (
        validation_byte_length > 0 AND length(validation_bytes) = validation_byte_length
    ),
    validator_build TEXT NOT NULL CHECK (validator_build <> ''),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TABLE derived_analysis_artifact (
    import_id TEXT PRIMARY KEY CHECK (
        length(import_id) BETWEEN 1 AND 512 AND import_id = trim(import_id)
    ),
    artifact_id TEXT NOT NULL UNIQUE CHECK (
        length(artifact_id) BETWEEN 1 AND 512 AND artifact_id = trim(artifact_id)
    ),
    artifact_contract TEXT NOT NULL CHECK (artifact_contract <> ''),
    artifact_schema_version INTEGER NOT NULL CHECK (artifact_schema_version > 0),
    artifact_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(artifact_sha256) = 64 AND artifact_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    artifact_byte_length INTEGER NOT NULL CHECK (artifact_byte_length > 0),
    manifest_sha256 TEXT NOT NULL CHECK (
        length(manifest_sha256) = 64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    manifest_bytes BLOB NOT NULL,
    manifest_byte_length INTEGER NOT NULL CHECK (
        manifest_byte_length > 0 AND length(manifest_bytes) = manifest_byte_length
    ),
    input_snapshot_id TEXT NOT NULL REFERENCES export_snapshot(export_snapshot_id),
    input_snapshot_sha256 TEXT NOT NULL CHECK (
        length(input_snapshot_sha256) = 64 AND input_snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    fit_through_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    maximum_input_available_wall_us INTEGER NOT NULL CHECK (maximum_input_available_wall_us > 0),
    support_sha256 TEXT NOT NULL CHECK (
        length(support_sha256) = 64 AND support_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    coverage_sha256 TEXT NOT NULL CHECK (
        length(coverage_sha256) = 64 AND coverage_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    uncertainty_sha256 TEXT NOT NULL CHECK (
        length(uncertainty_sha256) = 64 AND uncertainty_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    claim_scope TEXT NOT NULL CHECK (claim_scope IN (
        'descriptive_noncausal', 'model_inference', 'analog_retrieval',
        'kernel_estimate', 'field_estimate'
    )),
    truth_fingerprint_before TEXT NOT NULL CHECK (
        length(truth_fingerprint_before) = 64
        AND truth_fingerprint_before NOT GLOB '*[^0-9a-f]*'
    ),
    truth_fingerprint_after TEXT NOT NULL CHECK (
        truth_fingerprint_after = truth_fingerprint_before
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    CHECK (fit_through_commit_seq < created_commit_seq)
) STRICT;

CREATE TABLE spool_catalog_admission (
    segment_id TEXT NOT NULL CHECK (
        length(segment_id) BETWEEN 1 AND 512 AND segment_id = trim(segment_id)
    ),
    batch_id TEXT NOT NULL CHECK (
        length(batch_id) BETWEEN 1 AND 512 AND batch_id = trim(batch_id)
    ),
    protection_domain TEXT NOT NULL CHECK (protection_domain <> ''),
    protection_class TEXT NOT NULL CHECK (
        protection_class IN ('public_integrity', 'authenticated_private')
    ),
    segment_sha256 TEXT NOT NULL CHECK (
        length(segment_sha256) = 64 AND segment_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    segment_byte_length INTEGER NOT NULL CHECK (segment_byte_length > 0),
    exact_batch_sha256 TEXT NOT NULL CHECK (
        length(exact_batch_sha256) = 64 AND exact_batch_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    exact_policy_sha256 TEXT NOT NULL CHECK (
        length(exact_policy_sha256) = 64 AND exact_policy_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    logical_batch_sha256 TEXT NOT NULL CHECK (
        length(logical_batch_sha256) = 64 AND logical_batch_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    store_admission_sha256 TEXT NOT NULL CHECK (
        length(store_admission_sha256) = 64 AND store_admission_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    store_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    receipt_sha256 TEXT NOT NULL CHECK (
        length(receipt_sha256) = 64 AND receipt_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    receipt_bytes BLOB NOT NULL,
    receipt_byte_length INTEGER NOT NULL CHECK (
        receipt_byte_length > 0 AND length(receipt_bytes) = receipt_byte_length
    ),
    recorded_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    PRIMARY KEY (segment_id, batch_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE episode_protocol_v1 (
    protocol_registration_id TEXT PRIMARY KEY CHECK (
        length(protocol_registration_id) BETWEEN 1 AND 512
        AND protocol_registration_id = trim(protocol_registration_id)
    ),
    protocol_definition_id TEXT NOT NULL CHECK (
        length(protocol_definition_id) BETWEEN 1 AND 512
        AND protocol_definition_id = trim(protocol_definition_id)
    ),
    protocol_revision INTEGER NOT NULL CHECK (protocol_revision > 0),
    protocol_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(protocol_sha256) = 64 AND protocol_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    protocol_bytes BLOB NOT NULL,
    protocol_byte_length INTEGER NOT NULL CHECK (
        protocol_byte_length > 0 AND length(protocol_bytes) = protocol_byte_length
    ),
    build_sha256 TEXT NOT NULL CHECK (
        length(build_sha256) = 64 AND build_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    configuration_sha256 TEXT NOT NULL CHECK (
        length(configuration_sha256) = 64 AND configuration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    budget_sha256 TEXT NOT NULL CHECK (
        length(budget_sha256) = 64 AND budget_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    privacy_sha256 TEXT NOT NULL CHECK (
        length(privacy_sha256) = 64 AND privacy_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    duration_us INTEGER NOT NULL CHECK (duration_us > 0),
    warmup_offset_us INTEGER NOT NULL CHECK (
        warmup_offset_us >= 0 AND warmup_offset_us < duration_us
    ),
    choice_deadline_offset_us INTEGER NOT NULL CHECK (
        choice_deadline_offset_us > warmup_offset_us
        AND choice_deadline_offset_us <= duration_us
    ),
    outcome_horizon_offset_us INTEGER NOT NULL CHECK (
        outcome_horizon_offset_us > duration_us
    ),
    knowledge_deadline_offset_us INTEGER NOT NULL CHECK (
        knowledge_deadline_offset_us > outcome_horizon_offset_us
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TABLE episode_launch_v1 (
    launch_id TEXT PRIMARY KEY CHECK (
        length(launch_id) BETWEEN 1 AND 512 AND launch_id = trim(launch_id)
    ),
    protocol_registration_id TEXT NOT NULL
        REFERENCES episode_protocol_v1(protocol_registration_id),
    prospective_session_id TEXT NOT NULL UNIQUE CHECK (
        length(prospective_session_id) BETWEEN 1 AND 512
        AND prospective_session_id = trim(prospective_session_id)
    ),
    launch_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(launch_sha256) = 64 AND launch_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    launch_bytes BLOB NOT NULL,
    launch_byte_length INTEGER NOT NULL CHECK (
        launch_byte_length > 0 AND length(launch_bytes) = launch_byte_length
    ),
    t0_wall_us INTEGER NOT NULL CHECK (t0_wall_us > 0),
    catalog_cutoff_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq),
    CHECK (catalog_cutoff_commit_seq < created_commit_seq)
) STRICT;

CREATE TABLE episode_launch_reference_v1 (
    launch_id TEXT NOT NULL REFERENCES episode_launch_v1(launch_id),
    reference_kind TEXT NOT NULL CHECK (reference_kind IN (
        'source_receipt', 'census', 'hot_scope', 'choice_member', 'projection_publication',
        'cockpit_publication', 'scene', 'presentation', 'nomination_contract',
        'abstention_contract', 'outcome_contract', 'interview_contract', 'export_contract',
        'reserved_presentation', 'reserved_hot_decision', 'reserved_hot_intent',
        'reserved_command', 'reserved_command_idempotency', 'reserved_outcome',
        'reserved_interview', 'reserved_export_request', 'reserved_analysis_run',
        'reserved_artifact_import'
    )),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    reference_id TEXT NOT NULL CHECK (
        length(reference_id) BETWEEN 1 AND 512 AND reference_id = trim(reference_id)
    ),
    reference_sha256 TEXT CHECK (
        reference_sha256 IS NULL OR (
            length(reference_sha256) = 64 AND reference_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    cutoff_commit_seq INTEGER REFERENCES ingest_commit(commit_seq),
    originated_wall_us INTEGER CHECK (originated_wall_us IS NULL OR originated_wall_us > 0),
    reference_status TEXT NOT NULL CHECK (
        reference_status IN ('durable_existing', 'reserved_future')
    ),
    CHECK (
        (reference_kind LIKE 'reserved_%' AND reference_status = 'reserved_future'
            AND cutoff_commit_seq IS NULL AND originated_wall_us IS NULL)
        OR
        (reference_kind NOT LIKE 'reserved_%' AND reference_status = 'durable_existing')
    ),
    PRIMARY KEY (launch_id, reference_kind, ordinal),
    UNIQUE (launch_id, reference_kind, reference_id)
) STRICT, WITHOUT ROWID;

-- This binds an opaque authenticated UI session occurrence to one preregistered launch without
-- persisting, logging, or hashing the secret capability bytes. `prospective_session_id` remains the
-- study/run occurrence and is intentionally not the browser pairing session identity.
CREATE TABLE episode_pairing_session_v1 (
    pairing_session_id TEXT PRIMARY KEY CHECK (
        length(pairing_session_id) BETWEEN 1 AND 512
        AND pairing_session_id = trim(pairing_session_id)
    ),
    launch_id TEXT NOT NULL UNIQUE REFERENCES episode_launch_v1(launch_id),
    scope_sha256 TEXT NOT NULL CHECK (
        length(scope_sha256) = 64 AND scope_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TABLE operator_explicit_abstention_v1 (
    abstention_id TEXT PRIMARY KEY CHECK (
        length(abstention_id) BETWEEN 1 AND 512 AND abstention_id = trim(abstention_id)
    ),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(idempotency_key) BETWEEN 1 AND 512 AND idempotency_key = trim(idempotency_key)
    ),
    episode_launch_id TEXT NOT NULL UNIQUE REFERENCES episode_launch_v1(launch_id),
    client_session_id TEXT NOT NULL CHECK (
        length(client_session_id) BETWEEN 1 AND 512 AND client_session_id = trim(client_session_id)
    ),
    scene_id TEXT NOT NULL REFERENCES scene(scene_id),
    presentation_id TEXT NOT NULL REFERENCES presentation_scene_v1(presentation_id),
    presentation_sha256 TEXT NOT NULL CHECK (
        length(presentation_sha256) = 64 AND presentation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    abstention_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(abstention_sha256) = 64 AND abstention_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    abstention_bytes BLOB NOT NULL,
    abstention_byte_length INTEGER NOT NULL CHECK (
        abstention_byte_length > 0 AND length(abstention_bytes) = abstention_byte_length
    ),
    issued_wall_us INTEGER NOT NULL CHECK (issued_wall_us > 0),
    client_clock_id TEXT NOT NULL CHECK (client_clock_id <> ''),
    issued_mono_ns TEXT NOT NULL CHECK (
        issued_mono_ns = '0' OR (
            issued_mono_ns NOT GLOB '*[^0-9]*'
            AND substr(issued_mono_ns, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    authority_class TEXT NOT NULL CHECK (authority_class = 'evidence_only'),
    effect_ceiling TEXT NOT NULL CHECK (effect_ceiling = 'observe_only'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TABLE operator_prospective_nomination_v1 (
    nomination_id TEXT PRIMARY KEY CHECK (
        length(nomination_id) BETWEEN 1 AND 512 AND nomination_id = trim(nomination_id)
    ),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(idempotency_key) BETWEEN 1 AND 512 AND idempotency_key = trim(idempotency_key)
    ),
    episode_launch_id TEXT NOT NULL UNIQUE REFERENCES episode_launch_v1(launch_id),
    client_session_id TEXT NOT NULL CHECK (
        length(client_session_id) BETWEEN 1 AND 512 AND client_session_id = trim(client_session_id)
    ),
    subject_id TEXT NOT NULL CHECK (
        length(subject_id) BETWEEN 1 AND 512 AND subject_id = trim(subject_id)
    ),
    choice_universe_sha256 TEXT NOT NULL CHECK (
        length(choice_universe_sha256) = 64
        AND choice_universe_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    membership_sha256 TEXT NOT NULL CHECK (
        length(membership_sha256) = 64 AND membership_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    scene_id TEXT NOT NULL REFERENCES scene(scene_id),
    presentation_id TEXT NOT NULL REFERENCES presentation_scene_v1(presentation_id),
    presentation_sha256 TEXT NOT NULL CHECK (
        length(presentation_sha256) = 64 AND presentation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    nomination_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(nomination_sha256) = 64 AND nomination_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    nomination_bytes BLOB NOT NULL,
    nomination_byte_length INTEGER NOT NULL CHECK (
        nomination_byte_length > 0 AND length(nomination_bytes) = nomination_byte_length
    ),
    issued_wall_us INTEGER NOT NULL CHECK (issued_wall_us > 0),
    client_clock_id TEXT NOT NULL CHECK (client_clock_id <> ''),
    issued_mono_ns TEXT NOT NULL CHECK (
        issued_mono_ns = '0' OR (
            issued_mono_ns NOT GLOB '*[^0-9]*'
            AND substr(issued_mono_ns, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    authority_class TEXT NOT NULL CHECK (authority_class = 'evidence_only'),
    effect_ceiling TEXT NOT NULL CHECK (effect_ceiling = 'observe_only'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TRIGGER projection_publication_supersession_is_forward
BEFORE INSERT ON projection_publication
WHEN NEW.supersedes_publication_id IS NOT NULL
BEGIN
    SELECT CASE WHEN (
        SELECT created_commit_seq FROM projection_publication
        WHERE publication_id = NEW.supersedes_publication_id
    ) >= NEW.created_commit_seq
    THEN RAISE(ABORT, 'projection publication supersession must advance knowledge') END;
END;

CREATE TRIGGER cockpit_publication_supersession_is_forward
BEFORE INSERT ON cockpit_publication
WHEN NEW.supersedes_cockpit_publication_id IS NOT NULL
BEGIN
    SELECT CASE WHEN (
        SELECT created_commit_seq FROM cockpit_publication
        WHERE cockpit_publication_id = NEW.supersedes_cockpit_publication_id
    ) >= NEW.created_commit_seq
    THEN RAISE(ABORT, 'cockpit publication supersession must advance knowledge') END;
END;

CREATE TRIGGER cockpit_publication_closes_projection
BEFORE INSERT ON cockpit_publication
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM projection_publication p
        WHERE p.publication_id = NEW.projection_publication_id
          AND p.publication_sha256 = NEW.projection_publication_sha256
          AND p.result_sha256 = NEW.projection_result_sha256
          AND p.artifact_sha256 = NEW.projection_artifact_sha256
          AND p.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'cockpit publication does not close to prior projection') END;
END;

CREATE TRIGGER presentation_event_closes_scene
BEFORE INSERT ON presentation_event_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM presentation_scene_v1 p
        WHERE p.presentation_id = NEW.presentation_id
          AND p.presentation_sha256 = NEW.presentation_sha256
          AND p.scene_id = NEW.scene_id
          AND p.view_sha256 = NEW.view_sha256
          AND p.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'presentation event does not close to prior presentation') END;
END;

CREATE TRIGGER episode_launch_precedes_t0
BEFORE INSERT ON episode_launch_v1
BEGIN
    SELECT CASE WHEN (
        SELECT committed_wall_us FROM ingest_commit WHERE commit_seq = NEW.created_commit_seq
    ) >= NEW.t0_wall_us
    THEN RAISE(ABORT, 'episode launch must be durably registered before T0') END;
END;

CREATE TRIGGER explicit_abstention_closes_presentation
BEFORE INSERT ON operator_explicit_abstention_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM presentation_scene_v1 p
        WHERE p.presentation_id = NEW.presentation_id
          AND p.presentation_sha256 = NEW.presentation_sha256
          AND p.scene_id = NEW.scene_id
          AND p.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'explicit abstention lacks a prior exact presentation') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM operator_prospective_nomination_v1 n
        WHERE n.episode_launch_id = NEW.episode_launch_id
    ) THEN RAISE(ABORT, 'episode choice branch is already consumed') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM episode_launch_v1 l
        JOIN episode_protocol_v1 p
          ON p.protocol_registration_id = l.protocol_registration_id
        JOIN episode_pairing_session_v1 s ON s.launch_id = l.launch_id
        JOIN ingest_commit c ON c.commit_seq = NEW.created_commit_seq
        WHERE l.launch_id = NEW.episode_launch_id
          AND s.pairing_session_id = NEW.client_session_id
          AND c.committed_wall_us >= l.t0_wall_us + p.warmup_offset_us
          AND c.committed_wall_us < l.t0_wall_us + p.choice_deadline_offset_us
    ) THEN RAISE(ABORT, 'explicit abstention is unpaired or committed after choice deadline') END;
END;

CREATE TRIGGER prospective_nomination_closes_presentation
BEFORE INSERT ON operator_prospective_nomination_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM presentation_scene_v1 p
        WHERE p.presentation_id = NEW.presentation_id
          AND p.presentation_sha256 = NEW.presentation_sha256
          AND p.scene_id = NEW.scene_id
          AND p.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'prospective nomination lacks a prior exact presentation') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM operator_explicit_abstention_v1 a
        WHERE a.episode_launch_id = NEW.episode_launch_id
    ) THEN RAISE(ABORT, 'episode choice branch is already consumed') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM episode_launch_v1 l
        JOIN episode_protocol_v1 p
          ON p.protocol_registration_id = l.protocol_registration_id
        JOIN episode_pairing_session_v1 s ON s.launch_id = l.launch_id
        JOIN ingest_commit c ON c.commit_seq = NEW.created_commit_seq
        WHERE l.launch_id = NEW.episode_launch_id
          AND s.pairing_session_id = NEW.client_session_id
          AND c.committed_wall_us >= l.t0_wall_us + p.warmup_offset_us
          AND c.committed_wall_us < l.t0_wall_us + p.choice_deadline_offset_us
    ) THEN RAISE(ABORT, 'prospective nomination is unpaired or committed after choice deadline') END;
END;

CREATE TRIGGER no_update_source_fact_artifact BEFORE UPDATE ON source_fact_artifact
BEGIN SELECT RAISE(ABORT, 'source_fact_artifact is append-only'); END;
CREATE TRIGGER no_delete_source_fact_artifact BEFORE DELETE ON source_fact_artifact
BEGIN SELECT RAISE(ABORT, 'source_fact_artifact is append-only'); END;
CREATE TRIGGER no_update_projection_publication BEFORE UPDATE ON projection_publication
BEGIN SELECT RAISE(ABORT, 'projection_publication is append-only'); END;
CREATE TRIGGER no_delete_projection_publication BEFORE DELETE ON projection_publication
BEGIN SELECT RAISE(ABORT, 'projection_publication is append-only'); END;
CREATE TRIGGER no_update_cockpit_publication BEFORE UPDATE ON cockpit_publication
BEGIN SELECT RAISE(ABORT, 'cockpit_publication is append-only'); END;
CREATE TRIGGER no_delete_cockpit_publication BEFORE DELETE ON cockpit_publication
BEGIN SELECT RAISE(ABORT, 'cockpit_publication is append-only'); END;
CREATE TRIGGER no_update_presentation_scene_v1 BEFORE UPDATE ON presentation_scene_v1
BEGIN SELECT RAISE(ABORT, 'presentation_scene_v1 is append-only'); END;
CREATE TRIGGER no_delete_presentation_scene_v1 BEFORE DELETE ON presentation_scene_v1
BEGIN SELECT RAISE(ABORT, 'presentation_scene_v1 is append-only'); END;
CREATE TRIGGER no_update_presentation_event_v1 BEFORE UPDATE ON presentation_event_v1
BEGIN SELECT RAISE(ABORT, 'presentation_event_v1 is append-only'); END;
CREATE TRIGGER no_delete_presentation_event_v1 BEFORE DELETE ON presentation_event_v1
BEGIN SELECT RAISE(ABORT, 'presentation_event_v1 is append-only'); END;
CREATE TRIGGER no_update_export_validation BEFORE UPDATE ON export_validation
BEGIN SELECT RAISE(ABORT, 'export_validation is append-only'); END;
CREATE TRIGGER no_delete_export_validation BEFORE DELETE ON export_validation
BEGIN SELECT RAISE(ABORT, 'export_validation is append-only'); END;
CREATE TRIGGER no_update_derived_analysis_artifact BEFORE UPDATE ON derived_analysis_artifact
BEGIN SELECT RAISE(ABORT, 'derived_analysis_artifact is append-only'); END;
CREATE TRIGGER no_delete_derived_analysis_artifact BEFORE DELETE ON derived_analysis_artifact
BEGIN SELECT RAISE(ABORT, 'derived_analysis_artifact is append-only'); END;
CREATE TRIGGER no_update_spool_catalog_admission BEFORE UPDATE ON spool_catalog_admission
BEGIN SELECT RAISE(ABORT, 'spool_catalog_admission is append-only'); END;
CREATE TRIGGER no_delete_spool_catalog_admission BEFORE DELETE ON spool_catalog_admission
BEGIN SELECT RAISE(ABORT, 'spool_catalog_admission is append-only'); END;
CREATE TRIGGER no_update_episode_protocol_v1 BEFORE UPDATE ON episode_protocol_v1
BEGIN SELECT RAISE(ABORT, 'episode_protocol_v1 is append-only'); END;
CREATE TRIGGER no_delete_episode_protocol_v1 BEFORE DELETE ON episode_protocol_v1
BEGIN SELECT RAISE(ABORT, 'episode_protocol_v1 is append-only'); END;
CREATE TRIGGER no_update_episode_launch_v1 BEFORE UPDATE ON episode_launch_v1
BEGIN SELECT RAISE(ABORT, 'episode_launch_v1 is append-only'); END;
CREATE TRIGGER no_delete_episode_launch_v1 BEFORE DELETE ON episode_launch_v1
BEGIN SELECT RAISE(ABORT, 'episode_launch_v1 is append-only'); END;
CREATE TRIGGER no_update_episode_launch_reference_v1 BEFORE UPDATE ON episode_launch_reference_v1
BEGIN SELECT RAISE(ABORT, 'episode_launch_reference_v1 is append-only'); END;
CREATE TRIGGER no_delete_episode_launch_reference_v1 BEFORE DELETE ON episode_launch_reference_v1
BEGIN SELECT RAISE(ABORT, 'episode_launch_reference_v1 is append-only'); END;
CREATE TRIGGER no_update_episode_pairing_session_v1 BEFORE UPDATE ON episode_pairing_session_v1
BEGIN SELECT RAISE(ABORT, 'episode_pairing_session_v1 is append-only'); END;
CREATE TRIGGER no_delete_episode_pairing_session_v1 BEFORE DELETE ON episode_pairing_session_v1
BEGIN SELECT RAISE(ABORT, 'episode_pairing_session_v1 is append-only'); END;
CREATE TRIGGER no_update_operator_explicit_abstention_v1 BEFORE UPDATE ON operator_explicit_abstention_v1
BEGIN SELECT RAISE(ABORT, 'operator_explicit_abstention_v1 is append-only'); END;
CREATE TRIGGER no_delete_operator_explicit_abstention_v1 BEFORE DELETE ON operator_explicit_abstention_v1
BEGIN SELECT RAISE(ABORT, 'operator_explicit_abstention_v1 is append-only'); END;
CREATE TRIGGER no_update_operator_prospective_nomination_v1 BEFORE UPDATE ON operator_prospective_nomination_v1
BEGIN SELECT RAISE(ABORT, 'operator_prospective_nomination_v1 is append-only'); END;
CREATE TRIGGER no_delete_operator_prospective_nomination_v1 BEFORE DELETE ON operator_prospective_nomination_v1
BEGIN SELECT RAISE(ABORT, 'operator_prospective_nomination_v1 is append-only'); END;
