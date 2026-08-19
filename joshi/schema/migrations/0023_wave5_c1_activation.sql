-- Sole-store, one-shot activation ledger for the bounded Wave 5 C1 public read.
--
-- An activation is still only an inert, exact semantic closure.  A later claim is deliberately
-- append-only and consumes that closure before any future transport implementation can receive
-- an opaque in-process capability.  Neither table grants network, credential, wallet, signing,
-- trading, or provider-spend authority.

CREATE TABLE wave5_c1_activation_v1 (
    activation_id TEXT PRIMARY KEY CHECK (
        length(activation_id) BETWEEN 1 AND 200 AND activation_id = trim(activation_id)
    ),
    installation_id TEXT NOT NULL CHECK (
        length(installation_id) = 37
        AND substr(installation_id, 1, 5) = 'inst-'
        AND substr(installation_id, 6) NOT GLOB '*[^0-9a-f]*'
    ),
    run_registration_id TEXT NOT NULL REFERENCES wave5_run_registration_v1(run_registration_id),
    run_registration_sha256 TEXT NOT NULL CHECK (
        length(run_registration_sha256) = 64 AND run_registration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    activation_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(activation_sha256) = 64 AND activation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    activation_bytes BLOB NOT NULL,
    activation_byte_length INTEGER NOT NULL CHECK (
        activation_byte_length > 0 AND length(activation_bytes) = activation_byte_length
    ),
    plan_id TEXT NOT NULL CHECK (length(plan_id) BETWEEN 1 AND 200 AND plan_id = trim(plan_id)),
    port_version TEXT NOT NULL CHECK (
        length(port_version) BETWEEN 1 AND 200 AND port_version = trim(port_version)
    ),
    exact_plan_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(exact_plan_sha256) = 64 AND exact_plan_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    exact_plan_bytes BLOB NOT NULL,
    exact_plan_byte_length INTEGER NOT NULL CHECK (
        exact_plan_byte_length > 0 AND length(exact_plan_bytes) = exact_plan_byte_length
    ),
    plan_template_sha256 TEXT NOT NULL CHECK (
        length(plan_template_sha256) = 64 AND plan_template_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    final_plan_sha256 TEXT NOT NULL CHECK (
        length(final_plan_sha256) = 64 AND final_plan_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    budget_projection_sha256 TEXT NOT NULL CHECK (
        length(budget_projection_sha256) = 64
        AND budget_projection_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    budget_projection_bytes BLOB NOT NULL,
    budget_projection_byte_length INTEGER NOT NULL CHECK (
        budget_projection_byte_length > 0
        AND length(budget_projection_bytes) = budget_projection_byte_length
    ),
    source_key TEXT NOT NULL CHECK (length(source_key) BETWEEN 1 AND 512 AND source_key = trim(source_key)),
    method_key TEXT NOT NULL CHECK (length(method_key) BETWEEN 1 AND 512 AND method_key = trim(method_key)),
    source_contract_sha256 TEXT NOT NULL CHECK (
        length(source_contract_sha256) = 64
        AND source_contract_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    method_schema_sha256 TEXT NOT NULL CHECK (
        length(method_schema_sha256) = 64
        AND method_schema_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    coverage_family TEXT NOT NULL CHECK (
        length(coverage_family) BETWEEN 1 AND 512 AND coverage_family = trim(coverage_family)
    ),
    protection_domain TEXT NOT NULL CHECK (
        length(protection_domain) BETWEEN 1 AND 512 AND protection_domain = trim(protection_domain)
    ),
    wallet_address TEXT NOT NULL CHECK (
        length(wallet_address) BETWEEN 1 AND 512 AND wallet_address = trim(wallet_address)
    ),
    wallet_max_rows INTEGER NOT NULL CHECK (wallet_max_rows > 0),
    commitment TEXT NOT NULL CHECK (commitment = 'finalized'),
    authority TEXT NOT NULL CHECK (authority = 'read_only_no_execution'),
    created_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TRIGGER wave5_c1_activation_closes_prior_run
BEFORE INSERT ON wave5_c1_activation_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_run_registration_v1 run
        WHERE run.run_registration_id = NEW.run_registration_id
          AND run.registration_sha256 = NEW.run_registration_sha256
          AND run.created_commit_seq < NEW.created_commit_seq
    ) THEN RAISE(ABORT, 'C1 activation does not close an earlier exact run') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.created_commit_seq
          AND commit_row.commit_class = 'maintenance'
    ) THEN RAISE(ABORT, 'C1 activation lacks a store maintenance commit') END;
END;

CREATE TABLE wave5_c1_activation_claim_v1 (
    activation_id TEXT PRIMARY KEY REFERENCES wave5_c1_activation_v1(activation_id),
    installation_id TEXT NOT NULL CHECK (
        length(installation_id) = 37
        AND substr(installation_id, 1, 5) = 'inst-'
        AND substr(installation_id, 6) NOT GLOB '*[^0-9a-f]*'
    ),
    activation_sha256 TEXT NOT NULL CHECK (
        length(activation_sha256) = 64 AND activation_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    run_registration_id TEXT NOT NULL REFERENCES wave5_run_registration_v1(run_registration_id),
    run_registration_sha256 TEXT NOT NULL CHECK (
        length(run_registration_sha256) = 64 AND run_registration_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    exact_plan_sha256 TEXT NOT NULL CHECK (
        length(exact_plan_sha256) = 64 AND exact_plan_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    claimed_commit_seq INTEGER NOT NULL UNIQUE REFERENCES ingest_commit(commit_seq)
) STRICT;

CREATE TRIGGER wave5_c1_claim_closes_prior_activation
BEFORE INSERT ON wave5_c1_activation_claim_v1
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM wave5_c1_activation_v1 activation
        WHERE activation.activation_id = NEW.activation_id
          AND activation.installation_id = NEW.installation_id
          AND activation.activation_sha256 = NEW.activation_sha256
          AND activation.run_registration_id = NEW.run_registration_id
          AND activation.run_registration_sha256 = NEW.run_registration_sha256
          AND activation.exact_plan_sha256 = NEW.exact_plan_sha256
          AND activation.created_commit_seq < NEW.claimed_commit_seq
    ) THEN RAISE(ABORT, 'C1 claim does not close an earlier exact activation') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ingest_commit commit_row
        WHERE commit_row.commit_seq = NEW.claimed_commit_seq
          AND commit_row.commit_class = 'maintenance'
    ) THEN RAISE(ABORT, 'C1 claim lacks a store maintenance commit') END;
END;

CREATE TRIGGER no_update_wave5_c1_activation_v1
BEFORE UPDATE ON wave5_c1_activation_v1
BEGIN SELECT RAISE(ABORT, 'wave5_c1_activation_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave5_c1_activation_v1
BEFORE DELETE ON wave5_c1_activation_v1
BEGIN SELECT RAISE(ABORT, 'wave5_c1_activation_v1 is append-only'); END;

CREATE TRIGGER no_update_wave5_c1_activation_claim_v1
BEFORE UPDATE ON wave5_c1_activation_claim_v1
BEGIN SELECT RAISE(ABORT, 'wave5_c1_activation_claim_v1 is append-only'); END;

CREATE TRIGGER no_delete_wave5_c1_activation_claim_v1
BEFORE DELETE ON wave5_c1_activation_claim_v1
BEGIN SELECT RAISE(ABORT, 'wave5_c1_activation_claim_v1 is append-only'); END;
