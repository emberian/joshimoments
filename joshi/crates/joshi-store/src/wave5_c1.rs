//! Sole-store durability and one-shot claiming for an inert Wave 5 C1 activation.
//!
//! Parsing an activation is deliberately not enough to reach a future transport.  This module
//! retains both exact documents, revalidates their complete closure at each durable boundary, and
//! returns an unconstructable, non-serializable capability only after an append-only claim commits.

use crate::{IdempotencyStatus, Result, SqliteStore, StoreError, Wave5CommitContext};
use joshi_domain::{CommitSeq, StableString, ValueDigest};
use joshi_wave5_c1_activation::{Wave5C1ActivationV1, parse_c1_activation_exact};
use rusqlite::{OptionalExtension as _, params};
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};

const ACTIVATION_OPERATION_DOMAIN: &str = "joshi.store.wave5_c1_activation_commit.v1";
const CLAIM_OPERATION_DOMAIN: &str = "joshi.store.wave5_c1_activation_claim.v1";

/// Publicly inspectable evidence that an activation document was durably retained.
///
/// This structural receipt is intentionally not accepted by any claim API and conveys no
/// execution or provider authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave5C1ActivationReceipt {
    pub catalog_id: StableString,
    pub catalog_schema: StableString,
    pub activation_id: StableString,
    pub installation_id: StableString,
    pub activation_digest: ValueDigest,
    pub run_registration_id: StableString,
    pub run_registration_digest: ValueDigest,
    pub plan_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
    pub status: IdempotencyStatus,
}

/// Exact C1 activation and plan re-parsed after a durable readback.
///
/// This is evidence only. It cannot be passed to the claim method and does not authorize I/O.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave5C1Activation {
    pub activation_id: StableString,
    pub installation_id: StableString,
    pub run_registration_id: StableString,
    pub run_registration_digest: ValueDigest,
    pub exact_activation_bytes: Vec<u8>,
    pub activation_digest: ValueDigest,
    pub exact_plan_bytes: Vec<u8>,
    pub exact_plan_digest: ValueDigest,
    pub plan_template_digest: ValueDigest,
    pub final_plan_digest: ValueDigest,
    pub activation: Wave5C1ActivationV1,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
}

/// Structural evidence that an activation was irreversibly consumed.
///
/// Like an activation receipt, this is not a capability and cannot be used to claim again.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave5C1ActivationClaimReceipt {
    pub activation_id: StableString,
    pub installation_id: StableString,
    pub activation_digest: ValueDigest,
    pub exact_plan_digest: ValueDigest,
    pub claimed_commit_seq: CommitSeq,
    pub claim_commit_digest: ValueDigest,
}

/// In-process result of a committed one-shot claim.
///
/// Its fields are private, it has no public constructor, and it implements neither `Serialize`
/// nor `Deserialize`. A future supervised runtime can inspect exact bounded inputs through these
/// accessors, but a receipt, identifier, or deserialized data can never manufacture this value.
#[must_use]
pub struct ClaimedWave5C1Activation {
    activation: Wave5C1ActivationV1,
    exact_activation_bytes: Vec<u8>,
    exact_plan_bytes: Vec<u8>,
    activation_commit_seq: CommitSeq,
    claim_receipt: Wave5C1ActivationClaimReceipt,
}

impl ClaimedWave5C1Activation {
    #[must_use]
    pub fn activation(&self) -> &Wave5C1ActivationV1 {
        &self.activation
    }

    #[must_use]
    pub fn exact_activation_bytes(&self) -> &[u8] {
        &self.exact_activation_bytes
    }

    #[must_use]
    pub fn exact_plan_bytes(&self) -> &[u8] {
        &self.exact_plan_bytes
    }

    #[must_use]
    pub const fn activation_commit_seq(&self) -> CommitSeq {
        self.activation_commit_seq
    }

    #[must_use]
    pub fn claim_receipt(&self) -> &Wave5C1ActivationClaimReceipt {
        &self.claim_receipt
    }
}

struct ActivationRow {
    installation_id: String,
    run_registration_id: String,
    run_registration_raw: String,
    activation_raw: String,
    activation_bytes: Vec<u8>,
    activation_length: i64,
    plan_id: String,
    port_version: String,
    plan_raw: String,
    plan_bytes: Vec<u8>,
    plan_length: i64,
    template_raw: String,
    final_raw: String,
    budget_raw: String,
    budget_bytes: Vec<u8>,
    budget_length: i64,
    source_key: String,
    method_key: String,
    source_contract_raw: String,
    method_schema_raw: String,
    coverage_family: String,
    protection_domain: String,
    wallet_address: String,
    wallet_max_rows: i64,
    commitment: String,
    authority: String,
    commit_seq: i64,
    commit_digest_raw: String,
}

/// The established runtime configuration is independently re-parsed rather than trusting only
/// the activation's repeated final-plan closure.
#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeConfigurationWire {
    contract: String,
    schema_version: u64,
    plan_id: String,
    plan_template_digest: String,
    status_endpoint: RuntimeStatusEndpointWire,
    provider_execution: String,
    authority: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeStatusEndpointWire {
    address: String,
    port: u16,
}

/// Established runtime-accounting caps, retained as scalars in the prior run document.
#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeAccountingWire {
    contract: String,
    schema_version: u64,
    limits: RuntimeLimitWire,
    authority: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
#[allow(clippy::struct_field_names)]
struct RuntimeLimitWire {
    maximum_requests: u64,
    maximum_pages: u64,
    maximum_ingress_bytes: u64,
    maximum_durable_bytes: u64,
    maximum_provider_credits: u64,
    maximum_ingress_bytes_per_second: Option<u64>,
    maximum_elapsed_ms: u64,
    maximum_in_flight_attempts: u64,
    maximum_in_flight_elapsed_overshoot_ms: u64,
}

impl SqliteStore {
    /// Re-parses, rebinds, and durably retains an inert exact C1 activation.
    ///
    /// The referenced Wave 5 run must already be durable. Retrying the same activation identity
    /// with exactly the same two byte strings returns the original structural receipt; any change
    /// is refused.
    ///
    /// # Errors
    ///
    /// Refuses malformed/noncanonical bytes, a foreign/nonprior run, insufficient durable limits,
    /// conflicting identities, or a failed append.
    #[allow(clippy::too_many_lines)]
    pub fn commit_wave5_c1_activation_v1(
        &mut self,
        exact_activation_bytes: &[u8],
        exact_plan_bytes: &[u8],
        context: &Wave5CommitContext,
    ) -> Result<Wave5C1ActivationReceipt> {
        let checked = parse_c1_activation_exact(exact_activation_bytes, exact_plan_bytes)
            .map_err(|error| StoreError::InvalidBatch(format!("invalid C1 activation: {error}")))?;
        let activation = checked.activation().clone();
        let activation_id = stable(&activation.activation_id, "C1 activation ID")?;
        require_supervisor_installation_shape(&activation.installation_id)?;
        if let Some(existing) = self.load_wave5_c1_activation_v1(&activation_id)? {
            if existing.exact_activation_bytes == exact_activation_bytes
                && existing.exact_plan_bytes == exact_plan_bytes
            {
                return self.activation_receipt(&existing, IdempotencyStatus::Idempotent);
            }
            return Err(StoreError::IdentityConflict {
                kind: "Wave 5 C1 activation",
                identity: activation_id.to_string(),
            });
        }

        let run_id = stable(&activation.run.run_id, "C1 activation run ID")?;
        let run = self
            .load_wave5_run_registration_v1(&run_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 5 C1 activation run",
                identity: run_id.to_string(),
            })?;
        let run_digest = digest(&activation.run.registration_digest, "C1 activation run")?;
        if run.exact_digest != run_digest {
            return Err(StoreError::InvalidBatch(
                "C1 activation run reference differs from durable registration".into(),
            ));
        }
        validate_run_c1_capacity(&run, &activation)?;
        let activation_digest = digest(checked.raw_activation_sha256(), "C1 activation")?;
        let plan_digest = digest(&activation.exact_plan.raw_exact_plan_sha256, "C1 plan")?;
        let operation_projection = activation.operations[0].clone();
        let operation =
            operation_digest(&(ACTIVATION_OPERATION_DOMAIN, activation_digest.as_str()))?;
        let receipt = self.commit_wave5(
            context,
            "maintenance",
            &activation_id,
            &activation_digest,
            &operation,
            |tx, seq| {
                let projection = serde_json::to_vec(&activation.budget)?;
                tx.execute(
                    "INSERT INTO wave5_c1_activation_v1
                     (activation_id,installation_id,run_registration_id,run_registration_sha256,
                      activation_sha256,activation_bytes,activation_byte_length,plan_id,port_version,
                      exact_plan_sha256,exact_plan_bytes,exact_plan_byte_length,plan_template_sha256,
                      final_plan_sha256,budget_projection_sha256,budget_projection_bytes,
                      budget_projection_byte_length,source_key,method_key,source_contract_sha256,
                      method_schema_sha256,coverage_family,protection_domain,wallet_address,
                      wallet_max_rows,commitment,authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,
                             ?18,?19,?20,?21,?22,?23,?24,?25,?26,?27,?28)",
                    params![
                        activation.activation_id.as_str(),
                        activation.installation_id.as_str(),
                        activation.run.run_id.as_str(),
                        raw_digest(&activation.run.registration_digest, "C1 activation run")?,
                        raw_digest(activation_digest.as_str(), "C1 activation")?,
                        exact_activation_bytes,
                        sqlite_usize(exact_activation_bytes.len(), "C1 activation bytes")?,
                        activation.exact_plan.plan_id.as_str(),
                        activation.exact_plan.port_version.as_str(),
                        raw_digest(plan_digest.as_str(), "C1 plan")?,
                        exact_plan_bytes,
                        sqlite_usize(exact_plan_bytes.len(), "C1 plan bytes")?,
                        raw_digest(&activation.exact_plan.plan_template_digest, "C1 template")?,
                        raw_digest(&activation.exact_plan.final_plan_digest, "C1 final plan")?,
                        raw_digest(digest_bytes(&projection)?.as_str(), "C1 budget projection")?,
                        projection,
                        sqlite_usize(
                            serde_json::to_vec(&activation.budget)?.len(),
                            "C1 budget projection bytes",
                        )?,
                        operation_projection.source_key.as_str(),
                        operation_projection.method_key.as_str(),
                        raw_digest(
                            &operation_projection.source_contract_fingerprint,
                            "C1 source contract",
                        )?,
                        raw_digest(
                            &operation_projection.method_schema_fingerprint,
                            "C1 method schema",
                        )?,
                        operation_projection.coverage_family.as_str(),
                        operation_projection.protection_domain.as_str(),
                        activation.wallet.address.as_str(),
                        i64::from(activation.wallet.max_rows),
                        "finalized",
                        activation.authority.as_str(),
                        seq,
                    ],
                )?;
                Ok(())
            },
        )?;
        let stored = self
            .load_wave5_c1_activation_v1(&activation_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "committed Wave 5 C1 activation",
                identity: activation_id.to_string(),
            })?;
        if stored.exact_activation_bytes != exact_activation_bytes
            || stored.exact_plan_bytes != exact_plan_bytes
            || stored.activation_digest != activation_digest
            || stored.commit_seq != receipt.commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "C1 activation readback differs from exact commit".into(),
            ));
        }
        self.activation_receipt(&stored, receipt.status)
    }

    /// Loads an activation only after re-parsing both exact documents and comparing every retained
    /// projection, digest, byte length, run closure, and commit lineage.
    ///
    /// # Errors
    ///
    /// Refuses malformed/tampered rows, divergent projections, or a foreign/nonprior durable run.
    pub fn load_wave5_c1_activation_v1(
        &self,
        activation_id: &StableString,
    ) -> Result<Option<StoredWave5C1Activation>> {
        let row = self.activation_row(activation_id)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let stored = verify_activation_row(row)?;
        if stored.activation_id != *activation_id {
            return Err(StoreError::InvalidBatch(
                "persisted C1 activation identity differs from exact bytes".into(),
            ));
        }
        let run = self
            .load_wave5_run_registration_v1(&stored.run_registration_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "C1 activation run",
                identity: stored.run_registration_id.to_string(),
            })?;
        if run.exact_digest != stored.run_registration_digest || run.commit_seq >= stored.commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "persisted C1 activation run closure is foreign or nonprior".into(),
            ));
        }
        validate_run_c1_capacity(&run, &stored.activation)?;
        Ok(Some(stored))
    }

    /// Atomically burns one durable activation and returns the sole opaque in-process capability.
    ///
    /// The claim row commits before this function returns, so a process crash before any future
    /// provider I/O leaves the activation consumed rather than reusable. The installation value
    /// is exact-bound data, not authentication; a future supervisor entry point must source it
    /// from the durable journal before consuming the returned capability.
    ///
    /// # Errors
    ///
    /// Refuses a foreign installation, an already consumed activation, a reused claim batch, an
    /// invalid durable closure, or any failed claim append.
    pub fn claim_wave5_c1_activation_v1(
        &mut self,
        activation_id: &StableString,
        installation_id: &StableString,
        context: &Wave5CommitContext,
    ) -> Result<ClaimedWave5C1Activation> {
        self.require_writer()?;
        require_supervisor_installation_shape(installation_id.as_str())?;
        let stored = self
            .load_wave5_c1_activation_v1(activation_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 5 C1 activation",
                identity: activation_id.to_string(),
            })?;
        if stored.installation_id != *installation_id {
            return Err(StoreError::InvalidBatch(
                "C1 activation installation does not match claim installation".into(),
            ));
        }
        if self.c1_claim_receipt(activation_id)?.is_some() {
            return Err(StoreError::IdentityConflict {
                kind: "Wave 5 C1 activation claim",
                identity: activation_id.to_string(),
            });
        }
        let operation = operation_digest(&(
            CLAIM_OPERATION_DOMAIN,
            stored.activation_digest.as_str(),
            stored.exact_plan_digest.as_str(),
        ))?;
        let generic = self.commit_wave5(
            context,
            "maintenance",
            activation_id,
            &stored.activation_digest,
            &operation,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave5_c1_activation_claim_v1
                     (activation_id,installation_id,activation_sha256,run_registration_id,
                      run_registration_sha256,exact_plan_sha256,claimed_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7)",
                    params![
                        stored.activation_id.as_str(),
                        stored.installation_id.as_str(),
                        raw_digest(stored.activation_digest.as_str(), "C1 activation")?,
                        stored.run_registration_id.as_str(),
                        raw_digest(stored.run_registration_digest.as_str(), "C1 run")?,
                        raw_digest(stored.exact_plan_digest.as_str(), "C1 plan")?,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )?;
        if generic.status == IdempotencyStatus::Idempotent {
            return Err(StoreError::IdentityConflict {
                kind: "Wave 5 C1 activation claim batch",
                identity: context.batch_id.to_string(),
            });
        }
        let claim =
            self.c1_claim_receipt(activation_id)?
                .ok_or_else(|| StoreError::MissingIdentity {
                    kind: "committed Wave 5 C1 activation claim",
                    identity: activation_id.to_string(),
                })?;
        if claim.claimed_commit_seq != generic.commit_seq {
            return Err(StoreError::InvalidBatch(
                "C1 activation claim readback differs from exact commit".into(),
            ));
        }
        Ok(ClaimedWave5C1Activation {
            activation: stored.activation,
            exact_activation_bytes: stored.exact_activation_bytes,
            exact_plan_bytes: stored.exact_plan_bytes,
            activation_commit_seq: stored.commit_seq,
            claim_receipt: claim,
        })
    }

    /// Reads structural evidence that a C1 activation was already consumed.
    ///
    /// The returned receipt is intentionally not accepted by the claim method and cannot create a
    /// [`ClaimedWave5C1Activation`].
    ///
    /// # Errors
    ///
    /// Refuses a malformed/tampered claim row or a claim that no longer closes its exact durable
    /// activation, run, and maintenance commit.
    pub fn load_wave5_c1_activation_claim_receipt_v1(
        &self,
        activation_id: &StableString,
    ) -> Result<Option<Wave5C1ActivationClaimReceipt>> {
        self.c1_claim_receipt(activation_id)
    }

    fn activation_row(&self, activation_id: &StableString) -> Result<Option<ActivationRow>> {
        self.connection
            .query_row(
                "SELECT a.installation_id,a.run_registration_id,a.run_registration_sha256,
                        a.activation_sha256,a.activation_bytes,a.activation_byte_length,
                        a.plan_id,a.port_version,a.exact_plan_sha256,a.exact_plan_bytes,
                        a.exact_plan_byte_length,a.plan_template_sha256,a.final_plan_sha256,
                        a.budget_projection_sha256,a.budget_projection_bytes,
                        a.budget_projection_byte_length,a.source_key,a.method_key,
                        a.source_contract_sha256,a.method_schema_sha256,a.coverage_family,
                        a.protection_domain,a.wallet_address,a.wallet_max_rows,a.commitment,
                        a.authority,a.created_commit_seq,c.commit_digest
                 FROM wave5_c1_activation_v1 a
                 JOIN ingest_commit c ON c.commit_seq=a.created_commit_seq
                 WHERE a.activation_id=?1",
                [activation_id.as_str()],
                |row| {
                    Ok(ActivationRow {
                        installation_id: row.get(0)?,
                        run_registration_id: row.get(1)?,
                        run_registration_raw: row.get(2)?,
                        activation_raw: row.get(3)?,
                        activation_bytes: row.get(4)?,
                        activation_length: row.get(5)?,
                        plan_id: row.get(6)?,
                        port_version: row.get(7)?,
                        plan_raw: row.get(8)?,
                        plan_bytes: row.get(9)?,
                        plan_length: row.get(10)?,
                        template_raw: row.get(11)?,
                        final_raw: row.get(12)?,
                        budget_raw: row.get(13)?,
                        budget_bytes: row.get(14)?,
                        budget_length: row.get(15)?,
                        source_key: row.get(16)?,
                        method_key: row.get(17)?,
                        source_contract_raw: row.get(18)?,
                        method_schema_raw: row.get(19)?,
                        coverage_family: row.get(20)?,
                        protection_domain: row.get(21)?,
                        wallet_address: row.get(22)?,
                        wallet_max_rows: row.get(23)?,
                        commitment: row.get(24)?,
                        authority: row.get(25)?,
                        commit_seq: row.get(26)?,
                        commit_digest_raw: row.get(27)?,
                    })
                },
            )
            .optional()
            .map_err(StoreError::from)
    }

    fn activation_receipt(
        &self,
        stored: &StoredWave5C1Activation,
        status: IdempotencyStatus,
    ) -> Result<Wave5C1ActivationReceipt> {
        Ok(Wave5C1ActivationReceipt {
            catalog_id: self.config.catalog_id.clone(),
            catalog_schema: self.catalog_schema_id()?,
            activation_id: stored.activation_id.clone(),
            installation_id: stored.installation_id.clone(),
            activation_digest: stored.activation_digest.clone(),
            run_registration_id: stored.run_registration_id.clone(),
            run_registration_digest: stored.run_registration_digest.clone(),
            plan_digest: stored.exact_plan_digest.clone(),
            commit_seq: stored.commit_seq,
            commit_digest: stored.commit_digest.clone(),
            status,
        })
    }

    fn c1_claim_receipt(
        &self,
        activation_id: &StableString,
    ) -> Result<Option<Wave5C1ActivationClaimReceipt>> {
        type ClaimRow = (String, String, String, String, String, i64, String, String);
        let row: Option<ClaimRow> = self
            .connection
            .query_row(
                "SELECT claim.installation_id,claim.activation_sha256,claim.exact_plan_sha256,
                        claim.run_registration_id,claim.run_registration_sha256,
                        claim.claimed_commit_seq,commit_row.commit_class,commit_row.commit_digest
                 FROM wave5_c1_activation_claim_v1 claim
                 JOIN ingest_commit commit_row ON commit_row.commit_seq=claim.claimed_commit_seq
                 WHERE claim.activation_id=?1",
                [activation_id.as_str()],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                        row.get(6)?,
                        row.get(7)?,
                    ))
                },
            )
            .optional()
            .map_err(StoreError::from)?;
        let Some((
            installation,
            activation_raw,
            plan_raw,
            run_id,
            run_raw,
            claimed_seq,
            commit_raw,
            commit_digest_raw,
        )) = row
        else {
            return Ok(None);
        };
        let stored = self
            .load_wave5_c1_activation_v1(activation_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "C1 activation for claim",
                identity: activation_id.to_string(),
            })?;
        let receipt = Wave5C1ActivationClaimReceipt {
            activation_id: activation_id.clone(),
            installation_id: stable(&installation, "C1 claim installation")?,
            activation_digest: raw_to_digest(&activation_raw, "C1 claim activation")?,
            exact_plan_digest: raw_to_digest(&plan_raw, "C1 claim plan")?,
            claimed_commit_seq: CommitSeq::new(as_u64(claimed_seq, "C1 claim sequence")?),
            claim_commit_digest: raw_to_digest(&commit_digest_raw, "C1 claim commit")?,
        };
        require_supervisor_installation_shape(receipt.installation_id.as_str())?;
        if receipt.installation_id != stored.installation_id
            || receipt.activation_digest != stored.activation_digest
            || receipt.exact_plan_digest != stored.exact_plan_digest
            || run_id != stored.run_registration_id.as_str()
            || raw_to_digest(&run_raw, "C1 claim run")? != stored.run_registration_digest
            || stored.commit_seq >= receipt.claimed_commit_seq
            || commit_raw != "maintenance"
        {
            return Err(StoreError::InvalidBatch(
                "persisted C1 activation claim differs from activation closure".into(),
            ));
        }
        Ok(Some(receipt))
    }
}

fn verify_activation_row(row: ActivationRow) -> Result<StoredWave5C1Activation> {
    let validated =
        parse_c1_activation_exact(&row.activation_bytes, &row.plan_bytes).map_err(|error| {
            StoreError::InvalidBatch(format!("persisted C1 activation is invalid: {error}"))
        })?;
    let activation = validated.activation();
    require_supervisor_installation_shape(&activation.installation_id)?;
    let activation_id = stable(&activation.activation_id, "C1 activation ID")?;
    let budget = serde_json::to_vec(&activation.budget)?;
    let exact = row.activation_length
        == sqlite_usize(row.activation_bytes.len(), "C1 activation bytes")?
        && row.plan_length == sqlite_usize(row.plan_bytes.len(), "C1 plan bytes")?
        && row.budget_length == sqlite_usize(budget.len(), "C1 budget projection bytes")?
        && row.budget_bytes == budget
        && row.activation_raw == raw_digest(validated.raw_activation_sha256(), "C1 activation")?
        && row.plan_raw == raw_digest(&activation.exact_plan.raw_exact_plan_sha256, "C1 plan")?
        && row.template_raw
            == raw_digest(&activation.exact_plan.plan_template_digest, "C1 template")?
        && row.final_raw == raw_digest(&activation.exact_plan.final_plan_digest, "C1 final plan")?
        && row.budget_raw == raw_digest(digest_bytes(&budget)?.as_str(), "C1 budget")?
        && row.installation_id == activation.installation_id
        && row.run_registration_id == activation.run.run_id
        && row.run_registration_raw == raw_digest(&activation.run.registration_digest, "C1 run")?
        && row.plan_id == activation.exact_plan.plan_id
        && row.port_version == activation.exact_plan.port_version
        && row.source_key == activation.operations[0].source_key
        && row.method_key == activation.operations[0].method_key
        && row.source_contract_raw
            == raw_digest(
                &activation.operations[0].source_contract_fingerprint,
                "C1 source",
            )?
        && row.method_schema_raw
            == raw_digest(
                &activation.operations[0].method_schema_fingerprint,
                "C1 method",
            )?
        && row.coverage_family == activation.operations[0].coverage_family
        && row.protection_domain == activation.operations[0].protection_domain
        && row.wallet_address == activation.wallet.address
        && row.wallet_max_rows == i64::from(activation.wallet.max_rows)
        && row.commitment == "finalized"
        && row.authority == activation.authority;
    if !exact {
        return Err(StoreError::InvalidBatch(
            "persisted C1 activation columns differ from exact byte closure".into(),
        ));
    }
    Ok(StoredWave5C1Activation {
        activation_id,
        installation_id: stable(&activation.installation_id, "C1 installation")?,
        run_registration_id: stable(&activation.run.run_id, "C1 run")?,
        run_registration_digest: digest(&activation.run.registration_digest, "C1 run")?,
        exact_activation_bytes: row.activation_bytes,
        activation_digest: digest(validated.raw_activation_sha256(), "C1 activation")?,
        exact_plan_bytes: row.plan_bytes,
        exact_plan_digest: digest(&activation.exact_plan.raw_exact_plan_sha256, "C1 plan")?,
        plan_template_digest: digest(&activation.exact_plan.plan_template_digest, "C1 template")?,
        final_plan_digest: digest(&activation.exact_plan.final_plan_digest, "C1 final plan")?,
        activation: activation.clone(),
        commit_seq: CommitSeq::new(as_u64(row.commit_seq, "C1 activation sequence")?),
        commit_digest: raw_to_digest(&row.commit_digest_raw, "C1 activation commit")?,
    })
}

/// Rebind the C1 final plan to the exact configuration and accounting components of its already
/// durable Wave 5 run. This is intentionally repeated on commit, load, and claim paths.
fn validate_run_c1_capacity(
    run: &crate::StoredWave5RunRegistration,
    activation: &Wave5C1ActivationV1,
) -> Result<()> {
    let configuration: RuntimeConfigurationWire = serde_json::from_slice(&run.configuration_bytes)?;
    if serde_json::to_vec(&configuration)? != run.configuration_bytes
        || configuration.contract != "joshi.collector.runtime_config.v1"
        || configuration.schema_version != 1
        || configuration.plan_id != activation.exact_plan.plan_id
        || configuration.plan_template_digest != activation.exact_plan.plan_template_digest
        || configuration.status_endpoint.address.is_empty()
        || configuration.status_endpoint.port == 0
        || configuration.provider_execution != "offline_fixture_only"
        || configuration.authority != "read_only_no_execution"
    {
        return Err(StoreError::InvalidBatch(
            "durable Wave 5 configuration does not exactly bind the C1 final plan template".into(),
        ));
    }
    let accounting: RuntimeAccountingWire = serde_json::from_slice(&run.budget_bytes)?;
    if serde_json::to_vec(&accounting)? != run.budget_bytes
        || accounting.contract != "joshi.collector.execution_accounting.v1"
        || accounting.schema_version != 1
        || accounting.authority != "read_only_no_execution"
    {
        return Err(StoreError::InvalidBatch(
            "durable Wave 5 accounting document is not the exact bounded runtime contract".into(),
        ));
    }
    let hard = &activation.budget.hard_cap;
    let attempt = &activation.budget.attempt_cost;
    let limits = &accounting.limits;
    let rate_contained = match activation.budget.max_ingress_bytes_per_second {
        None => true,
        Some(rate) => limits
            .maximum_ingress_bytes_per_second
            .is_some_and(|ceiling| rate <= ceiling),
    };
    if limits.maximum_requests < hard.requests
        || limits.maximum_pages < hard.pages
        || limits.maximum_ingress_bytes < hard.ingress_bytes
        || limits.maximum_durable_bytes < hard.durable_bytes
        || limits.maximum_provider_credits < hard.provider_credits
        || limits.maximum_elapsed_ms < activation.budget.max_elapsed_ms
        || limits.maximum_in_flight_attempts < u64::from(activation.budget.max_in_flight_attempts)
        || limits.maximum_in_flight_elapsed_overshoot_ms < attempt.max_overshoot.wall_millis
        || !rate_contained
        || !hard.provider_currency_minor.is_empty()
        || !hard.chain_native_atoms.is_empty()
        || !attempt.max_overshoot.is_zero()
    {
        return Err(StoreError::InvalidBatch(
            "durable Wave 5 accounting caps do not contain the exact C1 plan".into(),
        ));
    }
    Ok(())
}

fn digest(value: &str, kind: &'static str) -> Result<ValueDigest> {
    ValueDigest::new(value.to_owned()).map_err(|_| StoreError::InvalidDigest {
        kind,
        value: value.to_owned(),
    })
}

fn raw_to_digest(raw: &str, kind: &'static str) -> Result<ValueDigest> {
    digest(&format!("sha256:{raw}"), kind)
}

fn raw_digest<'a>(value: &'a str, kind: &'static str) -> Result<&'a str> {
    let Some(raw) = value.strip_prefix("sha256:") else {
        return Err(StoreError::InvalidDigest {
            kind,
            value: value.to_owned(),
        });
    };
    if raw.len() == 64
        && raw
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        Ok(raw)
    } else {
        Err(StoreError::InvalidDigest {
            kind,
            value: value.to_owned(),
        })
    }
}

fn digest_bytes(bytes: &[u8]) -> Result<ValueDigest> {
    digest(
        &format!("sha256:{:x}", Sha256::digest(bytes)),
        "C1 exact bytes",
    )
}

fn operation_digest(value: &impl Serialize) -> Result<ValueDigest> {
    digest_bytes(&serde_json::to_vec(value)?)
}

fn stable(value: &str, kind: &'static str) -> Result<StableString> {
    StableString::new(value.to_owned())
        .map_err(|error| StoreError::InvalidBatch(format!("invalid {kind}: {error}")))
}

fn require_supervisor_installation_shape(value: &str) -> Result<()> {
    let Some(hex) = value.strip_prefix("inst-") else {
        return Err(StoreError::InvalidBatch(
            "C1 installation must be inst- followed by 32 lowercase hexadecimal characters".into(),
        ));
    };
    if hex.len() == 32
        && hex
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        Ok(())
    } else {
        Err(StoreError::InvalidBatch(
            "C1 installation must be inst- followed by 32 lowercase hexadecimal characters".into(),
        ))
    }
}

fn sqlite_usize(value: usize, field: &'static str) -> Result<i64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn as_u64(value: i64, field: &'static str) -> Result<u64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}
