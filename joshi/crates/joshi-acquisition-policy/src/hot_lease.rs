//! Promotion of exactly one census subject into the executable terms of one hot lease.
//!
//! Nothing in this module decides anything. It reads a [`PolicyDecisionV1`] that was already
//! produced by [`crate::evaluate`] over an exact policy configuration and an exact resource
//! snapshot, and republishes the one active scope for one subject as the concrete ceilings a
//! collector may execute against: a bounded wall window, a finite connection count, a finite
//! frame count, and a finite ingress-byte count.
//!
//! The module deliberately cannot widen anything. Every ceiling here is copied from the effective
//! scope the reducer emitted; a subject with no active scope is a refusal that names why, never a
//! default lease.

use joshi_domain::{StableString, UtcTimestamp, WireU64};
use serde::{Deserialize, Serialize};

use crate::{
    DegradationChange, EffectiveScope, HotScopeRecordV1, PolicyDecisionV1, PolicyError,
    PressureStage, RecordId, ScopeSubject, SourceFamily,
};

/// Stable wire contract for executable lease terms.
pub const HOT_LEASE_TERMS_CONTRACT: &str = "joshi.hot_lease_terms/v1";

/// Literal authority ceiling every lease executed from these terms inherits.
pub const HOT_LEASE_AUTHORITY: &str = "read_only_no_execution";

/// The exact executable ceilings of one hot lease over one subject.
///
/// Every numeric field is copied from the effective scope a deterministic evaluation emitted. A
/// consumer that exceeds any of these has left the lease; it has not extended it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HotLeaseTermsV1 {
    pub contract: StableString,
    pub schema_version: WireU64,
    /// Evaluation occurrence that produced the scope these terms republish.
    pub decision_occurrence_id: StableString,
    pub intent_id: StableString,
    /// Append-only policy record (desired or degraded) the scope was read from.
    pub scope_record_id: RecordId,
    pub subject: ScopeSubject,
    pub source_key: StableString,
    pub operation_key: StableString,
    pub source_family: SourceFamily,
    /// Resource pressure the evaluation was taken under.
    pub pressure_stage: PressureStage,
    /// Wall instant the lease opens: the exact evaluation instant, never a later local clock.
    pub opened_at: UtcTimestamp,
    /// Wall instant the lease expires, already shortened by any pressure degradation.
    pub expires_at: UtcTimestamp,
    /// `expires_at - opened_at` in microseconds. Always positive.
    pub window_us: WireU64,
    /// Hard ceiling on provider connections this lease may open.
    pub max_connections: WireU64,
    /// Hard ceiling on retained provider frames.
    pub max_frames: WireU64,
    /// Hard ceiling on provider response bytes read into this process.
    pub max_ingress_bytes: WireU64,
    /// Hard ceiling on metered provider credits. Zero means no metered call is authorized.
    pub max_provider_credits: WireU64,
    /// Whether exact public provider bodies may be retained under this lease.
    pub exact_public_bodies: bool,
    /// Degradations the reducer attached to this scope. Empty means an undegraded desired scope.
    pub degradations: Vec<DegradationChange>,
    /// Census closures retained alongside the lease. They survive the lease.
    pub census_ids: Vec<StableString>,
    pub authority: StableString,
}

impl HotLeaseTermsV1 {
    /// Window length in whole milliseconds, rounded down.
    #[must_use]
    pub const fn window_ms(&self) -> u64 {
        self.window_us.get() / 1_000
    }

    /// Whether the reducer attached at least one degradation to this scope.
    #[must_use]
    pub const fn is_degraded(&self) -> bool {
        !self.degradations.is_empty()
    }
}

/// Promote exactly one subject to hot from one deterministic decision.
///
/// The decision must have been produced by [`crate::evaluate`] over the exact resource snapshot
/// the caller intends to execute under. Exactly one active scope for the subject is required: no
/// active scope is a refusal naming every reason the reducer gave, and more than one is a refusal
/// because one hot lease is one source operation.
///
/// # Errors
///
/// Refuses a subject with no active scope, a subject with more than one active scope, a
/// non-positive or unrepresentable window, a missing ingress/frame/connection ceiling, or any
/// scope that carries provider-currency or chain-native spending permission.
pub fn promote_one(
    decision: &PolicyDecisionV1,
    subject: &ScopeSubject,
) -> Result<HotLeaseTermsV1, PolicyError> {
    let (mut active, refusals) = scan_decision(decision, subject);
    let candidate = match active.len() {
        1 => active.remove(0),
        0 => {
            let detail = if refusals.is_empty() {
                "the evaluation emitted no scope for this subject at all".to_owned()
            } else {
                refusals.join("; ")
            };
            return Err(PolicyError::InvalidValue(format!(
                "subject {} was not promoted to hot: {detail}",
                subject.key.as_str()
            )));
        }
        count => {
            return Err(PolicyError::InvalidValue(format!(
                "one hot lease is exactly one source operation; subject {} has {count} active",
                subject.key.as_str()
            )));
        }
    };
    terms_from(decision, candidate)
}

/// One active scope the reducer emitted for the requested subject.
#[derive(Clone, Copy)]
struct ActiveScope<'a> {
    record_id: &'a RecordId,
    scope: &'a EffectiveScope,
    intent_id: &'a StableString,
    degradations: &'a [DegradationChange],
}

fn scan_decision<'a>(
    decision: &'a PolicyDecisionV1,
    subject: &ScopeSubject,
) -> (Vec<ActiveScope<'a>>, Vec<String>) {
    let mut active = Vec::new();
    let mut refusals = Vec::new();
    for record in &decision.new_records {
        match record {
            HotScopeRecordV1::Desired(value) if value.scope.subject == *subject => {
                active.push(ActiveScope {
                    record_id: &value.head.record_id,
                    scope: &value.scope,
                    intent_id: &value.intent_id,
                    degradations: &[],
                });
            }
            HotScopeRecordV1::Degraded(value) => match value.effective_scope.as_ref() {
                // An absent scope carries no subject of its own, so the refusal is reported
                // against the exact source operation the reducer named.
                None => refusals.extend(value.changes.iter().map(|change| {
                    format!(
                        "{}/{} absent: {:?} ({})",
                        value.source_key.as_str(),
                        value.operation_key.as_str(),
                        change.reason,
                        change.detail.as_str()
                    )
                })),
                Some(scope) if scope.subject == *subject => active.push(ActiveScope {
                    record_id: &value.head.record_id,
                    scope,
                    intent_id: &value.intent_id,
                    degradations: value.changes.as_slice(),
                }),
                Some(_) => {}
            },
            HotScopeRecordV1::Closed(value) => refusals.push(format!(
                "{}/{} closed: {}",
                value.source_key.as_str(),
                value.operation_key.as_str(),
                value.reason.as_str()
            )),
            HotScopeRecordV1::Desired(_)
            | HotScopeRecordV1::Intent(_)
            | HotScopeRecordV1::Applied(_) => {}
        }
    }
    (active, refusals)
}

fn terms_from(
    decision: &PolicyDecisionV1,
    candidate: ActiveScope<'_>,
) -> Result<HotLeaseTermsV1, PolicyError> {
    let scope = candidate.scope;
    if !scope.budget.provider_currency.is_empty() || !scope.budget.chain_native.is_empty() {
        return Err(PolicyError::InvalidValue(
            "a hot lease may not carry provider-currency or chain-native spending permission"
                .into(),
        ));
    }
    if scope.budget.max_requests.get() == 0
        || scope.budget.max_pages.get() == 0
        || scope.budget.max_response_bytes.get() == 0
    {
        return Err(PolicyError::InvalidValue(
            "a hot lease requires positive connection, frame, and ingress-byte ceilings".into(),
        ));
    }
    let opened_at = decision.evaluated_at;
    if opened_at >= scope.expires_at {
        return Err(PolicyError::InvalidValue(
            "hot lease window is empty at its own evaluation instant".into(),
        ));
    }
    let window_us = (scope.expires_at.as_datetime() - opened_at.as_datetime()).whole_microseconds();
    let window_us = u64::try_from(window_us)
        .map_err(|_| PolicyError::InvalidValue("hot lease window is not representable".into()))?;

    let mut degradations = candidate.degradations.to_vec();
    degradations.sort();
    degradations.dedup();
    Ok(HotLeaseTermsV1 {
        contract: stable(HOT_LEASE_TERMS_CONTRACT)?,
        schema_version: WireU64::new(1),
        decision_occurrence_id: decision.decision_occurrence_id.clone(),
        intent_id: candidate.intent_id.clone(),
        scope_record_id: candidate.record_id.clone(),
        subject: scope.subject.clone(),
        source_key: scope.source_key.clone(),
        operation_key: scope.operation_key.clone(),
        source_family: scope.source_family,
        pressure_stage: decision.pressure_stage,
        opened_at,
        expires_at: scope.expires_at,
        window_us: WireU64::new(window_us),
        max_connections: scope.budget.max_requests,
        max_frames: scope.budget.max_pages,
        max_ingress_bytes: scope.budget.max_response_bytes,
        max_provider_credits: scope.budget.max_provider_credits,
        exact_public_bodies: scope.fidelity.exact_public_bodies,
        degradations,
        census_ids: scope
            .census_denominators
            .iter()
            .map(|denominator| denominator.census_id.clone())
            .collect(),
        authority: stable(HOT_LEASE_AUTHORITY)?,
    })
}

/// Refuse a lease whose pressure stage means hot acquisition must not run at all.
///
/// [`promote_one`] already refuses these because the reducer emits no active scope under them.
/// This is the explicit, separately callable statement of the same rule for a caller that holds
/// only a pressure stage.
#[must_use]
pub const fn pressure_permits_hot_acquisition(stage: PressureStage) -> bool {
    !matches!(
        stage,
        PressureStage::DenominatorOnly | PressureStage::StopBeforeReserve
    )
}

fn stable(value: &str) -> Result<StableString, PolicyError> {
    StableString::new(value).map_err(|error| PolicyError::InvalidValue(error.to_string()))
}
