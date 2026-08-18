-- Forward-only migration 0002: bitemporal assertions, coverage, gaps, and cursors.

CREATE TABLE assertion (
    assertion_id TEXT PRIMARY KEY CHECK (
        length(assertion_id) BETWEEN 1 AND 512 AND assertion_id = trim(assertion_id)
    ),
    semantic_key TEXT NOT NULL CHECK (semantic_key <> ''),
    assertion_kind TEXT NOT NULL CHECK (assertion_kind <> ''),
    producer_id TEXT NOT NULL CHECK (producer_id <> ''),
    producer_version TEXT NOT NULL CHECK (producer_version <> ''),
    produced_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    produced_wall_us INTEGER NOT NULL CHECK (produced_wall_us > 0),
    valid_time_status TEXT NOT NULL CHECK (
        valid_time_status IN ('exact', 'bounded', 'unbounded', 'not_applicable')
    ),
    valid_lower_us INTEGER,
    valid_upper_us INTEGER,
    assertion_status TEXT NOT NULL CHECK (
        assertion_status IN ('candidate', 'accepted', 'unsupported', 'retraction')
    ),
    value_json TEXT NOT NULL CHECK (
        json_valid(value_json) AND json_type(value_json) = 'object'
    ),
    value_sha256 TEXT NOT NULL CHECK (
        length(value_sha256) = 64 AND value_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    supersedes_assertion_id TEXT REFERENCES assertion(assertion_id),
    CHECK (
        (valid_time_status IN ('exact', 'bounded')
            AND valid_lower_us IS NOT NULL
            AND valid_upper_us IS NOT NULL
            AND valid_upper_us > valid_lower_us)
        OR
        (valid_time_status IN ('unbounded', 'not_applicable')
            AND valid_lower_us IS NULL
            AND valid_upper_us IS NULL)
    ),
    CHECK (supersedes_assertion_id IS NULL OR supersedes_assertion_id <> assertion_id)
) STRICT;

CREATE TRIGGER assertion_supersession_is_forward
BEFORE INSERT ON assertion
WHEN NEW.supersedes_assertion_id IS NOT NULL
BEGIN
    SELECT CASE
        WHEN (SELECT produced_commit_seq
              FROM assertion
              WHERE assertion_id = NEW.supersedes_assertion_id) >= NEW.produced_commit_seq
        THEN RAISE(ABORT, 'assertion supersession must move knowledge forward')
    END;
    SELECT CASE
        WHEN (SELECT semantic_key
              FROM assertion
              WHERE assertion_id = NEW.supersedes_assertion_id) <> NEW.semantic_key
        THEN RAISE(ABORT, 'assertion supersession must preserve semantic key')
    END;
END;

CREATE TABLE assertion_observation_evidence (
    assertion_id TEXT NOT NULL REFERENCES assertion(assertion_id),
    observation_id TEXT NOT NULL REFERENCES observation(observation_id),
    evidence_role TEXT NOT NULL CHECK (
        evidence_role IN ('decoded_from', 'corroborates', 'contradicts', 'context')
    ),
    PRIMARY KEY (assertion_id, observation_id, evidence_role)
) STRICT, WITHOUT ROWID;

CREATE TRIGGER assertion_observation_evidence_is_causal
BEFORE INSERT ON assertion_observation_evidence
BEGIN
    SELECT CASE
        WHEN (SELECT commit_seq FROM observation WHERE observation_id = NEW.observation_id)
             > (SELECT produced_commit_seq FROM assertion WHERE assertion_id = NEW.assertion_id)
        THEN RAISE(ABORT, 'assertion evidence cannot come from a later commit')
    END;
END;

CREATE TABLE assertion_source_event (
    assertion_id TEXT NOT NULL REFERENCES assertion(assertion_id),
    source_event_id TEXT NOT NULL REFERENCES source_event(source_event_id),
    relation TEXT NOT NULL CHECK (relation IN ('claims_about', 'reconciles', 'context')),
    PRIMARY KEY (assertion_id, source_event_id, relation)
) STRICT, WITHOUT ROWID;

CREATE TRIGGER assertion_source_event_is_causal
BEFORE INSERT ON assertion_source_event
BEGIN
    SELECT CASE
        WHEN (SELECT identified_commit_seq FROM source_event
              WHERE source_event_id = NEW.source_event_id)
             > (SELECT produced_commit_seq FROM assertion WHERE assertion_id = NEW.assertion_id)
        THEN RAISE(ABORT, 'assertion source event cannot come from a later commit')
    END;
END;

CREATE TABLE assertion_amount (
    assertion_id TEXT NOT NULL REFERENCES assertion(assertion_id),
    amount_role TEXT NOT NULL CHECK (amount_role <> ''),
    asset_namespace TEXT NOT NULL CHECK (asset_namespace <> ''),
    asset_id TEXT NOT NULL CHECK (asset_id <> ''),
    signed_atoms TEXT NOT NULL CHECK (
        signed_atoms = '0'
        OR (
            signed_atoms NOT GLOB '*[^0-9]*'
            AND substr(signed_atoms, 1, 1) BETWEEN '1' AND '9'
        )
        OR (
            substr(signed_atoms, 1, 1) = '-'
            AND length(signed_atoms) > 1
            AND substr(signed_atoms, 2) NOT GLOB '*[^0-9]*'
            AND substr(signed_atoms, 2, 1) BETWEEN '1' AND '9'
        )
    ),
    decimals INTEGER NOT NULL CHECK (decimals BETWEEN 0 AND 255),
    unit TEXT NOT NULL DEFAULT 'atoms' CHECK (unit = 'atoms'),
    PRIMARY KEY (assertion_id, amount_role, asset_namespace, asset_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE coverage_window (
    coverage_id TEXT PRIMARY KEY CHECK (
        length(coverage_id) BETWEEN 1 AND 512 AND coverage_id = trim(coverage_id)
    ),
    source_id TEXT NOT NULL REFERENCES source(source_id),
    acquisition_id TEXT REFERENCES acquisition(acquisition_id),
    scope_kind TEXT NOT NULL CHECK (scope_kind <> ''),
    scope_key TEXT NOT NULL CHECK (scope_key <> ''),
    manifest_blob_id TEXT REFERENCES blob(blob_id),
    opened_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    opened_wall_us INTEGER NOT NULL CHECK (opened_wall_us > 0),
    coverage_level TEXT NOT NULL CHECK (
        coverage_level IN ('census', 'hot', 'manual', 'fixture')
    ),
    UNIQUE (source_id, scope_kind, scope_key, opened_commit_seq)
) STRICT;

CREATE TABLE coverage_event (
    coverage_event_id TEXT PRIMARY KEY CHECK (
        length(coverage_event_id) BETWEEN 1 AND 512 AND coverage_event_id = trim(coverage_event_id)
    ),
    coverage_id TEXT NOT NULL REFERENCES coverage_window(coverage_id),
    commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    event_kind TEXT NOT NULL CHECK (
        event_kind IN ('opened', 'heartbeat', 'degraded', 'recovering', 'recovered', 'closed')
    ),
    occurred_wall_us INTEGER NOT NULL CHECK (occurred_wall_us > 0),
    detail_code TEXT,
    UNIQUE (coverage_id, commit_seq, event_kind)
) STRICT;

CREATE TABLE coverage_gap (
    gap_id TEXT PRIMARY KEY CHECK (
        length(gap_id) BETWEEN 1 AND 512 AND gap_id = trim(gap_id)
    ),
    coverage_id TEXT NOT NULL REFERENCES coverage_window(coverage_id),
    detected_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    detected_wall_us INTEGER NOT NULL CHECK (detected_wall_us > 0),
    cause_code TEXT NOT NULL CHECK (cause_code <> ''),
    severity TEXT NOT NULL CHECK (severity IN ('degraded', 'scope_stopped', 'source_stopped')),
    lower_source_locator TEXT,
    upper_source_locator TEXT,
    event_lower_us INTEGER,
    event_upper_us INTEGER,
    CHECK (
        (event_lower_us IS NULL AND event_upper_us IS NULL)
        OR (event_lower_us IS NOT NULL AND event_upper_us IS NOT NULL
            AND event_upper_us > event_lower_us)
    )
) STRICT;

CREATE TABLE coverage_gap_recovery (
    recovery_id TEXT PRIMARY KEY CHECK (
        length(recovery_id) BETWEEN 1 AND 512 AND recovery_id = trim(recovery_id)
    ),
    gap_id TEXT NOT NULL REFERENCES coverage_gap(gap_id),
    recovery_acquisition_id TEXT REFERENCES acquisition(acquisition_id),
    commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    recovery_status TEXT NOT NULL CHECK (
        recovery_status IN ('partial', 'complete', 'unrecoverable')
    ),
    recovered_through_locator TEXT,
    evidence_blob_id TEXT REFERENCES blob(blob_id),
    UNIQUE (gap_id, commit_seq)
) STRICT;

CREATE TRIGGER coverage_recovery_after_detection
BEFORE INSERT ON coverage_gap_recovery
BEGIN
    SELECT CASE
        WHEN (SELECT detected_commit_seq FROM coverage_gap WHERE gap_id = NEW.gap_id)
             >= NEW.commit_seq
        THEN RAISE(ABORT, 'gap recovery must be known after gap detection')
    END;
END;

CREATE TRIGGER coverage_recovery_terminal_is_final
BEFORE INSERT ON coverage_gap_recovery
WHEN EXISTS (
    SELECT 1 FROM coverage_gap_recovery
    WHERE gap_id = NEW.gap_id AND recovery_status IN ('complete', 'unrecoverable')
)
BEGIN
    SELECT RAISE(ABORT, 'terminal gap recovery cannot be extended');
END;

CREATE TABLE source_cursor (
    cursor_id TEXT PRIMARY KEY CHECK (
        length(cursor_id) BETWEEN 1 AND 512 AND cursor_id = trim(cursor_id)
    ),
    source_id TEXT NOT NULL REFERENCES source(source_id),
    scope_kind TEXT NOT NULL CHECK (scope_kind <> ''),
    scope_key TEXT NOT NULL CHECK (scope_key <> ''),
    cursor_kind TEXT NOT NULL CHECK (cursor_kind <> ''),
    cursor_value TEXT NOT NULL CHECK (cursor_value <> ''),
    advanced_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    acquisition_id TEXT NOT NULL REFERENCES acquisition(acquisition_id),
    primary_evidence_observation_id TEXT NOT NULL REFERENCES observation(observation_id),
    predecessor_cursor_id TEXT REFERENCES source_cursor(cursor_id),
    evidence_count INTEGER NOT NULL CHECK (evidence_count > 0),
    UNIQUE (source_id, scope_kind, scope_key, cursor_kind, cursor_value),
    UNIQUE (source_id, scope_kind, scope_key, cursor_kind, advanced_commit_seq),
    UNIQUE (predecessor_cursor_id),
    CHECK (predecessor_cursor_id IS NULL OR predecessor_cursor_id <> cursor_id)
) STRICT;

CREATE TRIGGER cursor_primary_evidence_is_atomic
BEFORE INSERT ON source_cursor
BEGIN
    SELECT CASE
        WHEN (SELECT commit_seq FROM observation
              WHERE observation_id = NEW.primary_evidence_observation_id)
             <> NEW.advanced_commit_seq
        THEN RAISE(ABORT, 'cursor and primary evidence must share a commit')
    END;
    SELECT CASE
        WHEN (SELECT acquisition_id FROM observation
              WHERE observation_id = NEW.primary_evidence_observation_id)
             <> NEW.acquisition_id
        THEN RAISE(ABORT, 'cursor and primary evidence must share an acquisition')
    END;
END;

CREATE TABLE source_cursor_evidence (
    cursor_id TEXT NOT NULL REFERENCES source_cursor(cursor_id),
    observation_id TEXT NOT NULL REFERENCES observation(observation_id),
    PRIMARY KEY (cursor_id, observation_id)
) STRICT, WITHOUT ROWID;

CREATE TRIGGER cursor_evidence_not_from_future
BEFORE INSERT ON source_cursor_evidence
BEGIN
    SELECT CASE
        WHEN (SELECT commit_seq FROM observation WHERE observation_id = NEW.observation_id)
             <> (SELECT advanced_commit_seq FROM source_cursor WHERE cursor_id = NEW.cursor_id)
        THEN RAISE(ABORT, 'cursor evidence must share the cursor commit')
    END;
    SELECT CASE
        WHEN (SELECT acquisition_id FROM observation WHERE observation_id = NEW.observation_id)
             <> (SELECT acquisition_id FROM source_cursor WHERE cursor_id = NEW.cursor_id)
        THEN RAISE(ABORT, 'cursor evidence must belong to cursor acquisition')
    END;
END;

CREATE INDEX assertion_semantic_as_known
    ON assertion(semantic_key, produced_commit_seq, assertion_id);
CREATE INDEX assertion_valid_time
    ON assertion(assertion_kind, valid_lower_us, valid_upper_us, produced_commit_seq);
CREATE INDEX coverage_scope
    ON coverage_window(source_id, scope_kind, scope_key, opened_commit_seq);
CREATE INDEX coverage_gap_detected
    ON coverage_gap(coverage_id, detected_commit_seq);
CREATE INDEX source_cursor_latest
    ON source_cursor(source_id, scope_kind, scope_key, cursor_kind, advanced_commit_seq DESC);
