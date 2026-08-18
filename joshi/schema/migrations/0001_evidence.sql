-- Forward-only migration 0001: immutable acquisition and evidence identity.

CREATE TABLE schema_migration (
    migration_id INTEGER PRIMARY KEY CHECK (migration_id > 0),
    name TEXT NOT NULL UNIQUE CHECK (name <> ''),
    source_sha256 TEXT NOT NULL CHECK (
        length(source_sha256) = 64 AND source_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    applied_at_us INTEGER NOT NULL CHECK (applied_at_us > 0),
    sqlite_version TEXT NOT NULL CHECK (sqlite_version <> '')
) STRICT;

CREATE TABLE ingest_commit (
    commit_seq INTEGER PRIMARY KEY AUTOINCREMENT CHECK (commit_seq > 0),
    commit_id TEXT NOT NULL UNIQUE CHECK (
        length(commit_id) BETWEEN 1 AND 512 AND commit_id = trim(commit_id)
    ),
    commit_class TEXT NOT NULL CHECK (
        commit_class IN ('ingest', 'command', 'projection', 'export', 'maintenance', 'fixture')
    ),
    committed_wall_us INTEGER NOT NULL CHECK (committed_wall_us > 0),
    writer_clock_id TEXT NOT NULL CHECK (writer_clock_id <> ''),
    committed_mono_ns TEXT NOT NULL CHECK (
        committed_mono_ns = '0' OR (
            committed_mono_ns NOT GLOB '*[^0-9]*'
            AND substr(committed_mono_ns, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    writer_build TEXT NOT NULL CHECK (writer_build <> ''),
    prior_commit_digest TEXT CHECK (
        prior_commit_digest IS NULL OR (
            length(prior_commit_digest) = 64
            AND prior_commit_digest NOT GLOB '*[^0-9a-f]*'
        )
    ),
    commit_digest TEXT NOT NULL UNIQUE CHECK (
        length(commit_digest) = 64 AND commit_digest NOT GLOB '*[^0-9a-f]*'
    )
) STRICT;

CREATE TABLE source (
    source_id TEXT PRIMARY KEY CHECK (
        length(source_id) BETWEEN 1 AND 512 AND source_id = trim(source_id)
    ),
    namespace TEXT NOT NULL CHECK (namespace <> ''),
    source_contract_version TEXT NOT NULL CHECK (source_contract_version <> ''),
    collector_build TEXT NOT NULL CHECK (collector_build <> ''),
    configuration_fingerprint TEXT NOT NULL CHECK (
        length(configuration_fingerprint) = 64
        AND configuration_fingerprint NOT GLOB '*[^0-9a-f]*'
    ),
    effect_ceiling TEXT NOT NULL DEFAULT 'observe_only' CHECK (effect_ceiling = 'observe_only'),
    UNIQUE (namespace, source_contract_version, configuration_fingerprint)
) STRICT;

CREATE TABLE acquisition (
    acquisition_id TEXT PRIMARY KEY CHECK (
        length(acquisition_id) BETWEEN 1 AND 512 AND acquisition_id = trim(acquisition_id)
    ),
    source_id TEXT NOT NULL REFERENCES source(source_id),
    acquisition_kind TEXT NOT NULL CHECK (
        acquisition_kind IN ('live', 'poll', 'backfill', 'recovery', 'manual', 'fixture')
    ),
    transport_kind TEXT NOT NULL CHECK (
        transport_kind IN ('rpc', 'websocket', 'http', 'browser', 'operator', 'fixture')
    ),
    registered_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    parent_acquisition_id TEXT REFERENCES acquisition(acquisition_id),
    request_fingerprint TEXT NOT NULL CHECK (
        length(request_fingerprint) = 64
        AND request_fingerprint NOT GLOB '*[^0-9a-f]*'
    ),
    started_wall_us INTEGER NOT NULL CHECK (started_wall_us > 0),
    local_clock_id TEXT NOT NULL CHECK (local_clock_id <> ''),
    started_mono_ns TEXT NOT NULL CHECK (
        started_mono_ns = '0' OR (
            started_mono_ns NOT GLOB '*[^0-9]*'
            AND substr(started_mono_ns, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    source_locator_redacted TEXT,
    CHECK (
        parent_acquisition_id IS NULL OR parent_acquisition_id <> acquisition_id
    )
) STRICT;

CREATE TABLE acquisition_end (
    acquisition_end_id TEXT PRIMARY KEY CHECK (
        length(acquisition_end_id) BETWEEN 1 AND 512 AND acquisition_end_id = trim(acquisition_end_id)
    ),
    acquisition_id TEXT NOT NULL UNIQUE REFERENCES acquisition(acquisition_id),
    ended_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    ended_wall_us INTEGER NOT NULL CHECK (ended_wall_us > 0),
    end_status TEXT NOT NULL CHECK (
        end_status IN ('complete', 'source_closed', 'failed', 'cancelled', 'superseded')
    ),
    detail_code TEXT
) STRICT;

CREATE TABLE blob (
    blob_id TEXT PRIMARY KEY CHECK (
        length(blob_id) = 64 AND blob_id NOT GLOB '*[^0-9a-f]*'
    ),
    created_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    storage_mode TEXT NOT NULL CHECK (storage_mode IN ('inline', 'external')),
    inline_bytes BLOB,
    relative_path TEXT,
    content_length INTEGER NOT NULL CHECK (content_length >= 0),
    stored_length INTEGER NOT NULL CHECK (stored_length >= 0),
    stored_sha256 TEXT NOT NULL CHECK (
        length(stored_sha256) = 64 AND stored_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    compression TEXT NOT NULL CHECK (compression IN ('identity', 'zstd')),
    content_type TEXT NOT NULL CHECK (content_type <> ''),
    content_encoding TEXT,
    retention_class TEXT NOT NULL CHECK (
        retention_class IN (
            'public_chain', 'public_source', 'social_media', 'app_private',
            'operator_private', 'fixture', 'disposable'
        )
    ),
    CHECK (
        (storage_mode = 'inline'
            AND inline_bytes IS NOT NULL
            AND relative_path IS NULL
            AND compression = 'identity'
            AND stored_sha256 = blob_id
            AND stored_length = content_length
            AND length(inline_bytes) = content_length
            AND retention_class IN ('public_chain', 'public_source', 'fixture'))
        OR
        (storage_mode = 'external'
            AND inline_bytes IS NULL
            AND relative_path IS NOT NULL
            AND relative_path <> ''
            AND substr(relative_path, 1, 1) <> '/'
            AND relative_path NOT GLOB '*../*'
            AND relative_path NOT GLOB '../*')
    ),
    CHECK (
        compression <> 'identity'
        OR (stored_sha256 = blob_id AND stored_length = content_length)
    )
) STRICT;

CREATE TABLE observation (
    observation_id TEXT PRIMARY KEY CHECK (
        length(observation_id) BETWEEN 1 AND 512 AND observation_id = trim(observation_id)
    ),
    commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    intra_commit_seq INTEGER NOT NULL CHECK (intra_commit_seq >= 0),
    acquisition_id TEXT NOT NULL REFERENCES acquisition(acquisition_id),
    acquisition_ordinal INTEGER NOT NULL CHECK (acquisition_ordinal >= 0),
    source_id TEXT NOT NULL REFERENCES source(source_id),
    blob_id TEXT NOT NULL REFERENCES blob(blob_id),
    observation_kind TEXT NOT NULL CHECK (
        observation_kind IN (
            'frame', 'response', 'snapshot', 'poll_result', 'operator_capture', 'fixture'
        )
    ),
    received_wall_us INTEGER NOT NULL CHECK (received_wall_us > 0),
    received_clock_id TEXT NOT NULL CHECK (received_clock_id <> ''),
    received_mono_ns TEXT NOT NULL CHECK (
        received_mono_ns = '0' OR (
            received_mono_ns NOT GLOB '*[^0-9]*'
            AND substr(received_mono_ns, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    persisted_wall_us INTEGER NOT NULL CHECK (persisted_wall_us >= received_wall_us),
    available_wall_us INTEGER NOT NULL CHECK (available_wall_us >= persisted_wall_us),
    event_time_status TEXT NOT NULL CHECK (
        event_time_status IN ('exact', 'bounded', 'source_missing', 'not_applicable')
    ),
    source_event_lower_us INTEGER,
    source_event_upper_us INTEGER,
    source_time_precision_us INTEGER CHECK (
        source_time_precision_us IS NULL OR source_time_precision_us > 0
    ),
    chain_slot INTEGER CHECK (chain_slot IS NULL OR chain_slot >= 0),
    chain_tx_index INTEGER CHECK (chain_tx_index IS NULL OR chain_tx_index >= 0),
    chain_instruction_path TEXT,
    chain_log_index INTEGER CHECK (chain_log_index IS NULL OR chain_log_index >= 0),
    chain_commitment TEXT CHECK (
        chain_commitment IS NULL OR chain_commitment IN ('processed', 'confirmed', 'finalized')
    ),
    source_cursor_text TEXT,
    parse_disposition TEXT NOT NULL CHECK (
        parse_disposition IN ('pending', 'decoded', 'unsupported_variant', 'malformed', 'opaque')
    ),
    quality_code TEXT,
    UNIQUE (commit_seq, intra_commit_seq),
    UNIQUE (acquisition_id, acquisition_ordinal),
    CHECK (
        (event_time_status IN ('exact', 'bounded')
            AND source_event_lower_us IS NOT NULL
            AND source_event_upper_us IS NOT NULL
            AND source_event_upper_us > source_event_lower_us
            AND source_time_precision_us IS NOT NULL)
        OR
        (event_time_status IN ('source_missing', 'not_applicable')
            AND source_event_lower_us IS NULL
            AND source_event_upper_us IS NULL
            AND source_time_precision_us IS NULL)
    ),
    CHECK (
        event_time_status <> 'exact'
        OR source_event_upper_us = source_event_lower_us + source_time_precision_us
    )
) STRICT;

CREATE TRIGGER observation_relationships_are_causal
BEFORE INSERT ON observation
BEGIN
    SELECT CASE
        WHEN (SELECT source_id FROM acquisition WHERE acquisition_id = NEW.acquisition_id)
             <> NEW.source_id
        THEN RAISE(ABORT, 'observation source must match acquisition source')
    END;
    SELECT CASE
        WHEN (SELECT registered_commit_seq FROM acquisition
              WHERE acquisition_id = NEW.acquisition_id) > NEW.commit_seq
        THEN RAISE(ABORT, 'observation cannot precede acquisition registration')
    END;
    SELECT CASE
        WHEN (SELECT created_commit_seq FROM blob WHERE blob_id = NEW.blob_id) > NEW.commit_seq
        THEN RAISE(ABORT, 'observation cannot precede blob metadata')
    END;
END;

CREATE TABLE source_event (
    source_event_id TEXT PRIMARY KEY CHECK (
        length(source_event_id) BETWEEN 1 AND 512 AND source_event_id = trim(source_event_id)
    ),
    source_id TEXT NOT NULL REFERENCES source(source_id),
    event_namespace TEXT NOT NULL CHECK (event_namespace <> ''),
    natural_key TEXT NOT NULL CHECK (natural_key <> ''),
    identified_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    source_order_key TEXT,
    UNIQUE (source_id, event_namespace, natural_key)
) STRICT;

CREATE TABLE observation_source_event (
    observation_id TEXT NOT NULL REFERENCES observation(observation_id),
    source_event_id TEXT NOT NULL REFERENCES source_event(source_event_id),
    relation TEXT NOT NULL CHECK (relation IN ('contains', 'revision', 'mentions')),
    event_ordinal INTEGER CHECK (event_ordinal IS NULL OR event_ordinal >= 0),
    PRIMARY KEY (observation_id, source_event_id, relation)
) STRICT, WITHOUT ROWID;

CREATE TRIGGER observation_source_event_source_matches
BEFORE INSERT ON observation_source_event
BEGIN
    SELECT CASE
        WHEN (SELECT source_id FROM observation WHERE observation_id = NEW.observation_id)
             <> (SELECT source_id FROM source_event WHERE source_event_id = NEW.source_event_id)
        THEN RAISE(ABORT, 'observation and source event must share a source')
    END;
END;

CREATE INDEX observation_commit_order
    ON observation(commit_seq, intra_commit_seq);
CREATE INDEX observation_source_receive
    ON observation(source_id, received_wall_us, observation_id);
CREATE INDEX observation_blob
    ON observation(blob_id, observation_id);
CREATE INDEX observation_source_event_event
    ON observation_source_event(source_event_id, observation_id);
