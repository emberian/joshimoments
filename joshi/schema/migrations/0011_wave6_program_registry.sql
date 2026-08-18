-- Wave 6 fixture-program registration spine.
--
-- This table makes one exact, zero-provider, zero-mutation N00 registration restart-safe. It does
-- not resolve Wave 5 gates, execute a campaign, admit model output, or confer empirical, causal,
-- economic, presentation, wallet, signing, transaction, or external-mutation authority.

CREATE TABLE wave6_program_registration_v1 (
    program_id TEXT PRIMARY KEY CHECK (
        length(program_id) BETWEEN 1 AND 255 AND program_id = trim(program_id)
    ),
    program_family_id TEXT NOT NULL CHECK (
        length(program_family_id) BETWEEN 1 AND 255 AND program_family_id = trim(program_family_id)
    ),
    semantic_version TEXT NOT NULL CHECK (
        length(semantic_version) BETWEEN 1 AND 127 AND semantic_version = trim(semantic_version)
    ),
    registration_semantic_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(registration_semantic_sha256) = 64
        AND registration_semantic_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    registration_document_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(registration_document_sha256) = 64
        AND registration_document_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    registration_bytes BLOB NOT NULL,
    registration_byte_length INTEGER NOT NULL CHECK (
        registration_byte_length > 0
        AND length(registration_bytes) = registration_byte_length
    ),
    source_tree_sha256 TEXT NOT NULL CHECK (
        length(source_tree_sha256) = 64 AND source_tree_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    build_sha256 TEXT NOT NULL CHECK (
        length(build_sha256) = 64 AND build_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    environment_sha256 TEXT NOT NULL CHECK (
        length(environment_sha256) = 64 AND environment_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    config_sha256 TEXT NOT NULL CHECK (
        length(config_sha256) = 64 AND config_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    consumed_wave5_gate_count INTEGER NOT NULL CHECK (consumed_wave5_gate_count = 0),
    artifact_kind_count INTEGER NOT NULL CHECK (artifact_kind_count > 0),
    local_symbol_count INTEGER NOT NULL CHECK (local_symbol_count > 0),
    compute_units INTEGER NOT NULL CHECK (compute_units >= 0),
    read_units INTEGER NOT NULL CHECK (read_units >= 0),
    attention_units INTEGER NOT NULL CHECK (attention_units >= 0),
    provider_units INTEGER NOT NULL CHECK (provider_units = 0),
    external_mutation_units INTEGER NOT NULL CHECK (external_mutation_units = 0),
    max_artifacts INTEGER NOT NULL CHECK (max_artifacts > 0),
    fixture_registered_wall_us INTEGER NOT NULL CHECK (fixture_registered_wall_us > 0),
    authority TEXT NOT NULL CHECK (authority = 'read_record_replay_propose_shadow_only'),
    semantic_ceiling TEXT NOT NULL CHECK (
        semantic_ceiling = 'unverified_semantic_fixture_only'
    ),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TRIGGER wave6_program_registration_closes_exact_bytes
BEFORE INSERT ON wave6_program_registration_v1
BEGIN
    SELECT CASE WHEN json_extract(CAST(NEW.registration_bytes AS TEXT), '$.contract')
            <> 'joshi.wave6.program-registration.v1'
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.programId')
            <> NEW.program_id
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.programFamilyId')
            <> NEW.program_family_id
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.semanticVersion')
            <> NEW.semantic_version
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.registrationDigest')
            <> 'sha256:' || NEW.registration_semantic_sha256
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.sourceTreeDigest')
            <> 'sha256:' || NEW.source_tree_sha256
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.buildDigest')
            <> 'sha256:' || NEW.build_sha256
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.environmentDigest')
            <> 'sha256:' || NEW.environment_sha256
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.configDigest')
            <> 'sha256:' || NEW.config_sha256
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.authority')
            <> NEW.authority
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.semanticCeiling')
            <> NEW.semantic_ceiling
        OR json_array_length(CAST(NEW.registration_bytes AS TEXT), '$.consumedWave5Gates')
            <> NEW.consumed_wave5_gate_count
        OR json_array_length(CAST(NEW.registration_bytes AS TEXT), '$.artifactKinds')
            <> NEW.artifact_kind_count
        OR json_array_length(CAST(NEW.registration_bytes AS TEXT), '$.localSymbols')
            <> NEW.local_symbol_count
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.budgets.computeUnits')
            <> CAST(NEW.compute_units AS TEXT)
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.budgets.readUnits')
            <> CAST(NEW.read_units AS TEXT)
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.budgets.attentionUnits')
            <> CAST(NEW.attention_units AS TEXT)
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.budgets.providerUnits')
            <> CAST(NEW.provider_units AS TEXT)
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.budgets.externalMutationUnits')
            <> CAST(NEW.external_mutation_units AS TEXT)
        OR json_extract(CAST(NEW.registration_bytes AS TEXT), '$.budgets.maxArtifacts')
            <> CAST(NEW.max_artifacts AS TEXT)
    THEN RAISE(ABORT, 'Wave 6 program row differs from exact registration bytes') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.created_commit_seq
          AND commit_row.commit_class = 'maintenance'
          AND commit_row.committed_wall_us >= NEW.fixture_registered_wall_us
    ) THEN RAISE(ABORT, 'Wave 6 registration lacks a nonbackdated store commit') END;
END;

CREATE TRIGGER no_update_wave6_program_registration_v1
BEFORE UPDATE ON wave6_program_registration_v1
BEGIN SELECT RAISE(ABORT, 'wave6_program_registration_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave6_program_registration_v1
BEFORE DELETE ON wave6_program_registration_v1
BEGIN SELECT RAISE(ABORT, 'wave6_program_registration_v1 is append-only'); END;
