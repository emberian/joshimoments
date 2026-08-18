use crate::model::{
    AUTHORITY_CEILING, BackfillDisposition, CatalogReceiptSummaryV1, GapStatusV1,
    OperationalBoundaryV1, SourceFamily, unique_count,
};
use crate::{OperationalError, Result};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, WireU64};
use serde::{Deserialize, Serialize};

/// Typed plan contract. A plan has no provider client or execution method.
pub const BACKFILL_PLAN_CONTRACT: &str = "joshi.operational.backfill_plan/v1";
/// Typed result contract imported only after independent durable work occurred elsewhere.
pub const BACKFILL_RESULT_CONTRACT: &str = "joshi.operational.backfill_result/v1";
const MAX_EVIDENCE_REFS: usize = 512;

/// Hard provider/resource ceiling for a proposed backfill.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BackfillLimitsV1 {
    pub max_requests: WireU64,
    pub max_pages: WireU64,
    pub max_bytes: WireU64,
    pub max_provider_credits: WireU64,
    pub deadline_ms: WireU64,
}

/// A pure planning strategy. None of these variants contains a callable endpoint or credential.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum BackfillStrategyV1 {
    HeliusHttpHistory {
        acquisition_source: SourceFamily,
        lower: OperationalBoundaryV1,
        upper: OperationalBoundaryV1,
    },
    SameSourcePagination {
        source_family: SourceFamily,
        lower: OperationalBoundaryV1,
        upper: OperationalBoundaryV1,
    },
    CrossSourceReconstruction {
        reconstruction_source: SourceFamily,
        reconstruction_contract: StableString,
        lower: OperationalBoundaryV1,
        upper: OperationalBoundaryV1,
    },
    DeclareUnrecoverable {},
}

/// Request to construct a bounded immutable plan.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BackfillPlanRequestV1 {
    pub plan_id: StableString,
    pub policy_id: StableString,
    pub planned_at: UtcTimestamp,
    pub gap: GapStatusV1,
    pub strategy: BackfillStrategyV1,
    pub limits: BackfillLimitsV1,
}

/// Validated backfill proposal; it deliberately offers no `run` operation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BackfillPlanV1 {
    pub contract: String,
    pub plan_id: StableString,
    pub policy_id: StableString,
    pub planned_at: UtcTimestamp,
    pub authority: String,
    pub gap_id: StableString,
    pub original_source: SourceFamily,
    pub original_disposition: BackfillDisposition,
    pub strategy: BackfillStrategyV1,
    pub limits: BackfillLimitsV1,
    pub requires_exact_evidence_commit: bool,
    pub requires_append_only_recovery_record: bool,
}

impl BackfillPlanV1 {
    /// Revalidates an imported plan without performing I/O.
    ///
    /// # Errors
    ///
    /// Refuses `PumpPortal` same-source history, unbounded work, source mismatch, or a plan that
    /// could claim recovery without committed evidence and an append-only recovery record.
    pub fn validate(&self) -> Result<()> {
        validate_plan_fields(self)
    }
}

/// Purely validates and materializes a plan. It performs no live backfill.
///
/// # Errors
///
/// Refuses invalid strategy/source/capability combinations and unbounded limits.
pub fn plan_backfill(request: BackfillPlanRequestV1) -> Result<BackfillPlanV1> {
    let plan = BackfillPlanV1 {
        contract: BACKFILL_PLAN_CONTRACT.to_owned(),
        plan_id: request.plan_id,
        policy_id: request.policy_id,
        planned_at: request.planned_at,
        authority: AUTHORITY_CEILING.to_owned(),
        gap_id: request.gap.gap_id,
        original_source: request.gap.source_family,
        original_disposition: request.gap.disposition,
        strategy: request.strategy,
        limits: request.limits,
        requires_exact_evidence_commit: true,
        requires_append_only_recovery_record: true,
    };
    plan.validate()?;
    Ok(plan)
}

/// Finite failure class; raw provider/error text never enters this contract or metrics.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum BackfillFailureClass {
    BudgetExhausted,
    AuthenticationRejected,
    RateLimited,
    SourceUnavailable,
    SchemaDrift,
    IntegrityFailure,
    CatalogAdmissionFailure,
    DeadlineExceeded,
}

/// Exact same-source evidence and recovery-record closure.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecoveryProofV1 {
    pub evidence_receipt: CatalogReceiptSummaryV1,
    pub acquisition_ids: Vec<StableString>,
    pub observation_ids: Vec<StableString>,
    pub recovery_record_id: StableString,
    pub recovery_commit: CommitSeq,
    pub recovered_through: OperationalBoundaryV1,
}

/// Separate cross-source reconstruction. It never closes original-source coverage.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CrossSourceProofV1 {
    pub reconstruction_source: SourceFamily,
    pub reconstruction_contract: StableString,
    pub evidence_receipt: CatalogReceiptSummaryV1,
    pub observation_ids: Vec<StableString>,
    pub reconstruction_record_id: StableString,
    pub reconstructed_through: OperationalBoundaryV1,
    pub original_gap_remains_open: bool,
}

/// Backfill result status. “Recovered” is impossible without exact durable evidence closure.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "status",
    rename_all = "snake_case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum BackfillOutcomeV1 {
    Recovered { proof: RecoveryProofV1 },
    Partial { proof: RecoveryProofV1 },
    CrossSourceReconstructed { proof: CrossSourceProofV1 },
    Unrecoverable { disposition: BackfillDisposition },
    Failed { class: BackfillFailureClass },
}

/// Immutable result imported after a separately authorized collector/store workflow.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BackfillResultV1 {
    pub contract: String,
    pub result_id: StableString,
    pub plan_id: StableString,
    pub gap_id: StableString,
    pub original_source: SourceFamily,
    pub authority: String,
    pub completed_at: UtcTimestamp,
    pub outcome: BackfillOutcomeV1,
}

impl BackfillResultV1 {
    /// Validates durable proof and protects live-only source semantics.
    ///
    /// # Errors
    ///
    /// Refuses evidence-free recovery, noncanonical reference sets, `PumpPortal` same-source
    /// recovery, or cross-source reconstruction that claims to close the original gap.
    pub fn validate(&self) -> Result<()> {
        if self.contract != BACKFILL_RESULT_CONTRACT {
            return Err(OperationalError::Contract {
                expected: BACKFILL_RESULT_CONTRACT,
                received: self.contract.clone(),
            });
        }
        if self.authority != AUTHORITY_CEILING {
            return Err(OperationalError::Invalid(
                "backfill result authority must be read_only_no_execution",
            ));
        }
        match &self.outcome {
            BackfillOutcomeV1::Recovered { proof } | BackfillOutcomeV1::Partial { proof } => {
                if self.original_source == SourceFamily::PumpPortalWebsocket {
                    return Err(OperationalError::Invalid(
                        "PumpPortal is live-only and cannot produce same-source recovery",
                    ));
                }
                validate_recovery_proof(proof)?;
            }
            BackfillOutcomeV1::CrossSourceReconstructed { proof } => {
                if proof.reconstruction_source == self.original_source
                    || !proof.original_gap_remains_open
                {
                    return Err(OperationalError::Invalid(
                        "cross-source reconstruction must use another source and keep original gap open",
                    ));
                }
                validate_refs(&proof.observation_ids, "cross-source observation IDs")?;
                validate_receipt(&proof.evidence_receipt)?;
            }
            BackfillOutcomeV1::Unrecoverable { disposition } => {
                if !matches!(
                    disposition,
                    BackfillDisposition::LiveOnlyUnrecoverable
                        | BackfillDisposition::CrossSourceReconstructionOnly
                        | BackfillDisposition::Unsupported
                ) {
                    return Err(OperationalError::Invalid(
                        "unrecoverable result has a recoverable disposition",
                    ));
                }
            }
            BackfillOutcomeV1::Failed { .. } => {}
        }
        Ok(())
    }

    /// Validates that this result closes the exact immutable plan identity and strategy.
    ///
    /// # Errors
    ///
    /// Refuses a result for another gap/source/plan, a pre-plan completion time, or an outcome
    /// family that the frozen strategy could not produce.
    pub fn validate_against_plan(&self, plan: &BackfillPlanV1) -> Result<()> {
        plan.validate()?;
        self.validate()?;
        if self.plan_id != plan.plan_id
            || self.gap_id != plan.gap_id
            || self.original_source != plan.original_source
            || self.completed_at < plan.planned_at
        {
            return Err(OperationalError::Invalid(
                "backfill result does not close the exact plan/gap/source/time",
            ));
        }
        let compatible = match (&plan.strategy, &self.outcome) {
            (
                BackfillStrategyV1::CrossSourceReconstruction {
                    reconstruction_source,
                    reconstruction_contract,
                    ..
                },
                BackfillOutcomeV1::CrossSourceReconstructed { proof },
            ) if proof.reconstruction_source == *reconstruction_source
                && proof.reconstruction_contract == *reconstruction_contract =>
            {
                true
            }
            pair => matches!(
                pair,
                (
                    BackfillStrategyV1::DeclareUnrecoverable {},
                    BackfillOutcomeV1::Unrecoverable { .. }
                ) | (
                    BackfillStrategyV1::HeliusHttpHistory { .. }
                        | BackfillStrategyV1::SameSourcePagination { .. },
                    BackfillOutcomeV1::Recovered { .. }
                        | BackfillOutcomeV1::Partial { .. }
                        | BackfillOutcomeV1::Unrecoverable { .. }
                        | BackfillOutcomeV1::Failed { .. }
                ) | (
                    BackfillStrategyV1::CrossSourceReconstruction { .. },
                    BackfillOutcomeV1::Unrecoverable { .. } | BackfillOutcomeV1::Failed { .. }
                )
            ),
        };
        if !compatible {
            return Err(OperationalError::Invalid(
                "backfill result outcome is incompatible with frozen strategy",
            ));
        }
        Ok(())
    }
}

fn validate_plan_fields(plan: &BackfillPlanV1) -> Result<()> {
    if plan.contract != BACKFILL_PLAN_CONTRACT {
        return Err(OperationalError::Contract {
            expected: BACKFILL_PLAN_CONTRACT,
            received: plan.contract.clone(),
        });
    }
    if plan.authority != AUTHORITY_CEILING
        || !plan.requires_exact_evidence_commit
        || !plan.requires_append_only_recovery_record
    {
        return Err(OperationalError::Invalid(
            "backfill plan must remain read-only and require evidence commit plus recovery record",
        ));
    }
    match &plan.strategy {
        BackfillStrategyV1::DeclareUnrecoverable {} => {
            if plan.limits.max_requests.get() != 0
                || plan.limits.max_pages.get() != 0
                || plan.limits.max_bytes.get() != 0
                || plan.limits.max_provider_credits.get() != 0
            {
                return Err(OperationalError::Invalid(
                    "unrecoverable declaration cannot reserve provider work",
                ));
            }
        }
        BackfillStrategyV1::HeliusHttpHistory {
            acquisition_source, ..
        } => {
            if *acquisition_source != SourceFamily::HeliusHttp
                || !matches!(
                    plan.original_source,
                    SourceFamily::HeliusWebsocket
                        | SourceFamily::HeliusHttp
                        | SourceFamily::WalletPublicChain
                )
                || plan.original_disposition != BackfillDisposition::SameSourceBoundedHistory
            {
                return Err(OperationalError::Invalid(
                    "Helius HTTP history strategy is incompatible with the gap source/disposition",
                ));
            }
            validate_positive_limits(&plan.limits)?;
        }
        BackfillStrategyV1::SameSourcePagination { source_family, .. } => {
            if *source_family != plan.original_source
                || plan.original_source == SourceFamily::PumpPortalWebsocket
                || plan.original_disposition != BackfillDisposition::SameSourceBoundedHistory
            {
                return Err(OperationalError::Invalid(
                    "same-source pagination is incompatible with the gap source/disposition",
                ));
            }
            validate_positive_limits(&plan.limits)?;
        }
        BackfillStrategyV1::CrossSourceReconstruction {
            reconstruction_source,
            ..
        } => {
            if *reconstruction_source == plan.original_source
                || !matches!(
                    plan.original_disposition,
                    BackfillDisposition::CrossSourceReconstructionOnly
                        | BackfillDisposition::LiveOnlyUnrecoverable
                )
            {
                return Err(OperationalError::Invalid(
                    "cross-source reconstruction must use another source for a compatible gap",
                ));
            }
            validate_positive_limits(&plan.limits)?;
        }
    }
    Ok(())
}

fn validate_positive_limits(limits: &BackfillLimitsV1) -> Result<()> {
    if limits.max_requests.get() == 0
        || limits.max_pages.get() == 0
        || limits.max_bytes.get() == 0
        || limits.deadline_ms.get() == 0
    {
        return Err(OperationalError::Invalid(
            "backfill work requires positive request/page/byte/deadline bounds",
        ));
    }
    Ok(())
}

fn validate_recovery_proof(proof: &RecoveryProofV1) -> Result<()> {
    validate_refs(&proof.acquisition_ids, "backfill acquisition IDs")?;
    validate_refs(&proof.observation_ids, "backfill observation IDs")?;
    validate_receipt(&proof.evidence_receipt)?;
    if proof.recovery_commit < proof.evidence_receipt.through_commit_seq {
        return Err(OperationalError::Invalid(
            "recovery record cannot precede committed recovered evidence",
        ));
    }
    Ok(())
}

fn validate_refs(values: &[StableString], field: &'static str) -> Result<()> {
    if values.is_empty() || values.len() > MAX_EVIDENCE_REFS {
        return Err(OperationalError::BoundExceeded {
            field,
            maximum: u64::try_from(MAX_EVIDENCE_REFS).unwrap_or(u64::MAX),
        });
    }
    if values.windows(2).any(|pair| pair[0] >= pair[1])
        || unique_count(values.iter().cloned()) != values.len()
    {
        return Err(OperationalError::Invalid(
            "backfill proof references must be sorted and unique",
        ));
    }
    Ok(())
}

fn validate_receipt(receipt: &CatalogReceiptSummaryV1) -> Result<()> {
    if receipt.from_commit_seq != receipt.through_commit_seq
        || receipt.commit_seq != receipt.through_commit_seq
        || receipt.gap_outcome_count.get()
            != u64::try_from(receipt.gap_outcome_ids.len()).unwrap_or(u64::MAX)
        || receipt
            .gap_outcome_ids
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
    {
        return Err(OperationalError::Invalid(
            "backfill receipt does not preserve exact V1 commit/gap closure",
        ));
    }
    Ok(())
}
