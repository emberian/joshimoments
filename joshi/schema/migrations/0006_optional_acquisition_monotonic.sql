-- Forward-only migration 0006: an acquisition wall clock does not imply a monotonic reading.
--
-- The migration runner disables FK rewriting and enables legacy ALTER behavior around this one
-- table rebuild, then re-enables and checks every foreign key before returning success. This lets
-- existing child tables continue to reference the replacement table by its canonical name.

ALTER TABLE acquisition RENAME TO acquisition_v5;

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
    local_clock_id TEXT CHECK (local_clock_id IS NULL OR local_clock_id <> ''),
    started_mono_ns TEXT CHECK (
        started_mono_ns IS NULL OR started_mono_ns = '0' OR (
            started_mono_ns NOT GLOB '*[^0-9]*'
            AND substr(started_mono_ns, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    source_locator_redacted TEXT,
    CHECK (parent_acquisition_id IS NULL OR parent_acquisition_id <> acquisition_id),
    CHECK (
        (local_clock_id IS NULL AND started_mono_ns IS NULL)
        OR (local_clock_id IS NOT NULL AND started_mono_ns IS NOT NULL)
    )
) STRICT;

INSERT INTO acquisition
    (acquisition_id, source_id, acquisition_kind, transport_kind, registered_commit_seq,
     parent_acquisition_id, request_fingerprint, started_wall_us, local_clock_id,
     started_mono_ns, source_locator_redacted)
SELECT acquisition_id, source_id, acquisition_kind, transport_kind, registered_commit_seq,
       parent_acquisition_id, request_fingerprint, started_wall_us, local_clock_id,
       started_mono_ns, source_locator_redacted
FROM acquisition_v5;

DROP TABLE acquisition_v5;

CREATE TRIGGER no_update_acquisition BEFORE UPDATE ON acquisition
BEGIN SELECT RAISE(ABORT, 'acquisition is append-only'); END;
CREATE TRIGGER no_delete_acquisition BEFORE DELETE ON acquisition
BEGIN SELECT RAISE(ABORT, 'acquisition is append-only'); END;
