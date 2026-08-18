-- Forward-only migration 0003: witnessed/retrospective scenes and evidence-only commands.

CREATE TABLE scene (
    scene_id TEXT PRIMARY KEY CHECK (
        length(scene_id) BETWEEN 1 AND 512 AND scene_id = trim(scene_id)
    ),
    scene_mode TEXT NOT NULL CHECK (
        scene_mode IN ('witnessed', 'knowledge_cutoff', 'retrospective')
    ),
    captured_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    knowledge_cutoff_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    outcome_cutoff_commit_seq INTEGER REFERENCES ingest_commit(commit_seq),
    basis_scene_id TEXT REFERENCES scene(scene_id),
    client_session_id TEXT NOT NULL CHECK (client_session_id <> ''),
    client_scene_seq INTEGER NOT NULL CHECK (client_scene_seq >= 0),
    ui_build TEXT NOT NULL CHECK (ui_build <> ''),
    view_contract TEXT NOT NULL CHECK (view_contract <> ''),
    view_contract_version INTEGER NOT NULL CHECK (view_contract_version > 0),
    source_mode TEXT NOT NULL CHECK (
        source_mode IN ('fixture', 'manual_nomination', 'companion', 'replacement', 'observatory')
    ),
    rendered_wall_us INTEGER NOT NULL CHECK (rendered_wall_us > 0),
    client_clock_id TEXT NOT NULL CHECK (client_clock_id <> ''),
    rendered_mono_ns TEXT NOT NULL CHECK (
        rendered_mono_ns = '0' OR (
            rendered_mono_ns NOT GLOB '*[^0-9]*'
            AND substr(rendered_mono_ns, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    view_blob_id TEXT NOT NULL REFERENCES blob(blob_id),
    screenshot_blob_id TEXT REFERENCES blob(blob_id),
    view_sha256 TEXT NOT NULL CHECK (
        length(view_sha256) = 64 AND view_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    UNIQUE (client_session_id, client_scene_seq),
    CHECK (knowledge_cutoff_commit_seq <= captured_commit_seq),
    CHECK (view_sha256 = view_blob_id),
    CHECK (
        (scene_mode = 'witnessed'
            AND outcome_cutoff_commit_seq IS NULL
            AND basis_scene_id IS NULL)
        OR
        (scene_mode = 'knowledge_cutoff'
            AND outcome_cutoff_commit_seq IS NULL
            AND basis_scene_id IS NOT NULL)
        OR
        (scene_mode = 'retrospective'
            AND outcome_cutoff_commit_seq IS NOT NULL
            AND outcome_cutoff_commit_seq >= knowledge_cutoff_commit_seq
            AND basis_scene_id IS NOT NULL)
    )
) STRICT;

CREATE TABLE scene_watermark (
    scene_id TEXT NOT NULL REFERENCES scene(scene_id),
    watermark_namespace TEXT NOT NULL CHECK (watermark_namespace <> ''),
    source_id TEXT REFERENCES source(source_id),
    projection_name TEXT,
    projection_version TEXT,
    delivered_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    state_sha256 TEXT CHECK (
        state_sha256 IS NULL OR (
            length(state_sha256) = 64 AND state_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    PRIMARY KEY (scene_id, watermark_namespace),
    CHECK (source_id IS NOT NULL OR projection_name IS NOT NULL),
    CHECK (
        (projection_name IS NULL AND projection_version IS NULL)
        OR (projection_name IS NOT NULL AND projection_version IS NOT NULL)
    )
) STRICT, WITHOUT ROWID;

CREATE TRIGGER scene_watermark_respects_boundary
BEFORE INSERT ON scene_watermark
BEGIN
    SELECT CASE
        WHEN (SELECT scene_mode FROM scene WHERE scene_id = NEW.scene_id)
                 IN ('witnessed', 'knowledge_cutoff')
             AND NEW.delivered_commit_seq >
                 (SELECT knowledge_cutoff_commit_seq FROM scene WHERE scene_id = NEW.scene_id)
        THEN RAISE(ABORT, 'scene watermark exceeds knowledge cutoff')
    END;
    SELECT CASE
        WHEN (SELECT scene_mode FROM scene WHERE scene_id = NEW.scene_id) = 'retrospective'
             AND NEW.delivered_commit_seq >
                 (SELECT outcome_cutoff_commit_seq FROM scene WHERE scene_id = NEW.scene_id)
        THEN RAISE(ABORT, 'scene watermark exceeds outcome cutoff')
    END;
END;

CREATE TABLE scene_choice_member (
    scene_id TEXT NOT NULL REFERENCES scene(scene_id),
    set_kind TEXT NOT NULL CHECK (
        set_kind IN ('eligible', 'surfaced', 'rendered', 'viewport', 'interacted', 'compared')
    ),
    subject_kind TEXT NOT NULL CHECK (subject_kind <> ''),
    subject_key TEXT NOT NULL CHECK (subject_key <> ''),
    source_rank INTEGER CHECK (source_rank IS NULL OR source_rank >= 0),
    rendered_ordinal INTEGER CHECK (rendered_ordinal IS NULL OR rendered_ordinal >= 0),
    evidence_assertion_id TEXT REFERENCES assertion(assertion_id),
    PRIMARY KEY (scene_id, set_kind, subject_kind, subject_key)
) STRICT, WITHOUT ROWID;

CREATE TRIGGER witnessed_choice_has_no_future_assertion
BEFORE INSERT ON scene_choice_member
WHEN NEW.evidence_assertion_id IS NOT NULL
BEGIN
    SELECT CASE
        WHEN (SELECT scene_mode FROM scene WHERE scene_id = NEW.scene_id) = 'witnessed'
             AND (SELECT produced_commit_seq FROM assertion
                  WHERE assertion_id = NEW.evidence_assertion_id) >
                 (SELECT knowledge_cutoff_commit_seq FROM scene WHERE scene_id = NEW.scene_id)
        THEN RAISE(ABORT, 'witnessed choice assertion exceeds knowledge cutoff')
    END;
END;

CREATE TABLE command (
    command_id TEXT PRIMARY KEY CHECK (
        length(command_id) BETWEEN 1 AND 512 AND command_id = trim(command_id)
    ),
    committed_commit_seq INTEGER NOT NULL REFERENCES ingest_commit(commit_seq),
    scene_id TEXT REFERENCES scene(scene_id),
    client_session_id TEXT NOT NULL CHECK (client_session_id <> ''),
    client_command_seq INTEGER NOT NULL CHECK (client_command_seq >= 0),
    idempotency_key TEXT NOT NULL CHECK (idempotency_key <> ''),
    command_kind TEXT NOT NULL CHECK (command_kind <> ''),
    subject_kind TEXT NOT NULL CHECK (subject_kind <> ''),
    subject_key TEXT NOT NULL CHECK (subject_key <> ''),
    payload_blob_id TEXT NOT NULL REFERENCES blob(blob_id),
    issued_wall_us INTEGER NOT NULL CHECK (issued_wall_us > 0),
    client_clock_id TEXT NOT NULL CHECK (client_clock_id <> ''),
    issued_mono_ns TEXT NOT NULL CHECK (
        issued_mono_ns = '0' OR (
            issued_mono_ns NOT GLOB '*[^0-9]*'
            AND substr(issued_mono_ns, 1, 1) BETWEEN '1' AND '9'
        )
    ),
    received_wall_us INTEGER NOT NULL CHECK (received_wall_us >= issued_wall_us),
    effect_ceiling TEXT NOT NULL CHECK (effect_ceiling = 'observe_only'),
    authority_class TEXT NOT NULL CHECK (authority_class = 'evidence_only'),
    UNIQUE (client_session_id, client_command_seq),
    UNIQUE (client_session_id, idempotency_key)
) STRICT;

CREATE TRIGGER command_cannot_precede_scene
BEFORE INSERT ON command
WHEN NEW.scene_id IS NOT NULL
BEGIN
    SELECT CASE
        WHEN NEW.committed_commit_seq <
             (SELECT captured_commit_seq FROM scene WHERE scene_id = NEW.scene_id)
        THEN RAISE(ABORT, 'command cannot precede referenced scene')
    END;
END;

CREATE TABLE assertion_command_evidence (
    assertion_id TEXT NOT NULL REFERENCES assertion(assertion_id),
    command_id TEXT NOT NULL REFERENCES command(command_id),
    evidence_role TEXT NOT NULL CHECK (
        evidence_role IN ('prompted_by', 'records_intent', 'records_operator_claim', 'context')
    ),
    PRIMARY KEY (assertion_id, command_id, evidence_role)
) STRICT, WITHOUT ROWID;

CREATE TRIGGER assertion_command_evidence_is_causal
BEFORE INSERT ON assertion_command_evidence
BEGIN
    SELECT CASE
        WHEN (SELECT committed_commit_seq FROM command WHERE command_id = NEW.command_id)
             > (SELECT produced_commit_seq FROM assertion WHERE assertion_id = NEW.assertion_id)
        THEN RAISE(ABORT, 'assertion command evidence cannot come from a later commit')
    END;
END;

CREATE INDEX scene_cutoffs
    ON scene(scene_mode, knowledge_cutoff_commit_seq, outcome_cutoff_commit_seq);
CREATE INDEX command_subject
    ON command(subject_kind, subject_key, committed_commit_seq);
