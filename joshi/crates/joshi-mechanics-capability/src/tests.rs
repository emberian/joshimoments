use std::collections::BTreeMap;

use joshi_domain::{
    AsOfVector, ChainAsOf, ProtocolProfileId, SourceAsOf, SourceId, StableString, UtcTimestamp,
    VenueId,
};
use joshi_market_math::profile::{ProtocolFamily, ProtocolProfile};

use super::*;

fn stable(value: &str) -> StableString {
    StableString::new(value).unwrap_or_else(|_| unreachable!())
}

fn source() -> SourceId {
    SourceId::new("fixture/mechanics").unwrap_or_else(|_| unreachable!())
}

fn profile() -> ProtocolProfile {
    ProtocolProfile {
        id: ProtocolProfileId::new("pump-curve/v1").unwrap_or_else(|_| unreachable!()),
        venue: VenueId::new("pump").unwrap_or_else(|_| unreachable!()),
        family: ProtocolFamily::PumpCurve,
        program_identity: stable("pump-program-v1"),
        source_revision: stable("fixture-revision-1"),
    }
}

fn horizon(finality: Finality, coverage: CoverageState) -> EvidenceHorizon {
    let source_id = source();
    let mut sources = BTreeMap::new();
    sources.insert(
        source_id,
        SourceAsOf::without_cursors(
            joshi_domain::CommitSeq::new(8),
            Some(
                "2026-08-18T12:00:00.000000Z"
                    .parse::<UtcTimestamp>()
                    .unwrap_or_else(|_| unreachable!()),
            ),
        ),
    );
    let as_of = AsOfVector {
        catalog_commit: joshi_domain::CommitSeq::new(8),
        sources,
        chain: Some(ChainAsOf {
            cluster: stable("solana-mainnet"),
            slot: joshi_domain::WireU64::new(42),
            finality: joshi_domain::OpenVariant::known("finalized")
                .unwrap_or_else(|_| unreachable!()),
        }),
        projections: BTreeMap::new(),
        rendered_at: "2026-08-18T12:00:00.000000Z"
            .parse::<UtcTimestamp>()
            .unwrap_or_else(|_| unreachable!()),
    };
    let ids = matches!(coverage, CoverageState::Gap { .. })
        .then(|| vec![joshi_domain::CoverageId::new("gap-1").unwrap_or_else(|_| unreachable!())])
        .unwrap_or_default();
    EvidenceHorizon::new(as_of, finality, coverage, ids).unwrap_or_else(|_| unreachable!())
}

fn binding(kind: CapabilityKind, status: EvidenceStatus) -> CapabilityEvidence {
    let profile = profile();
    let source_id = source();
    let mut value = EvidenceBinding {
        source_id,
        profile_id: profile.id.clone(),
        state_observation_id: Some(
            joshi_domain::ObservationId::new("obs-1").unwrap_or_else(|_| unreachable!()),
        ),
        quote_id: None,
        attempt_id: None,
        fill_id: None,
        failure_id: None,
        liquidation_id: None,
        position_id: None,
        publication_id: None,
        calibration_id: None,
        terminal_closure_id: None,
        horizon: horizon(Finality::Finalized, CoverageState::Complete),
        source_digest: None,
    };
    if matches!(
        kind,
        CapabilityKind::MarginalQuote | CapabilityKind::SizeQuote
    ) {
        value.quote_id =
            Some(joshi_domain::QuoteId::new("quote-1").unwrap_or_else(|_| unreachable!()));
    }
    if matches!(
        kind,
        CapabilityKind::ObservedAttempt | CapabilityKind::LandedFillOrFailure
    ) {
        value.attempt_id = Some(stable("attempt-1"));
    }
    if matches!(kind, CapabilityKind::LandedFillOrFailure) {
        value.fill_id = Some(stable("fill-1"));
    }
    if matches!(kind, CapabilityKind::WholePositionLiquidation) {
        value.quote_id = Some(
            joshi_domain::QuoteId::new("quote-liquidation").unwrap_or_else(|_| unreachable!()),
        );
        value.liquidation_id = Some(stable("liquidation-1"));
    }
    if matches!(kind, CapabilityKind::TerminalPositionClosure) {
        value.liquidation_id = Some(stable("liquidation-1"));
        value.position_id =
            Some(joshi_domain::PositionId::new("position-1").unwrap_or_else(|_| unreachable!()));
        value.terminal_closure_id = Some(stable("terminal-1"));
    }
    if matches!(kind, CapabilityKind::Publication) {
        value.publication_id = Some(stable("publication-1"));
    }
    if matches!(kind, CapabilityKind::Calibration) {
        value.calibration_id = Some(stable("calibration-1"));
    }
    CapabilityEvidence::new(kind, status, value).unwrap_or_else(|_| unreachable!())
}

#[test]
fn simulation_does_not_imply_attempt_or_fill() {
    let profile = profile();
    let profile_id = profile.id.clone();
    let mut registry = MechanicsCapabilityRegistry::default();
    assert!(registry.register_profile(&profile, source()).is_ok());
    assert!(
        registry
            .record(binding(
                CapabilityKind::ObservedSimulation,
                EvidenceStatus::Attained
            ))
            .is_ok()
    );

    let simulation = registry.check_prerequisites(&[ClaimPrerequisite::attained(
        profile_id.clone(),
        CapabilityKind::ObservedSimulation,
    )]);
    assert!(simulation.semantically_satisfied());
    let attempt = registry.check_prerequisites(&[ClaimPrerequisite::attained(
        profile_id.clone(),
        CapabilityKind::ObservedAttempt,
    )]);
    assert!(!attempt.semantically_satisfied());
    assert!(
        registry
            .capability(&profile_id, CapabilityKind::ObservedAttempt)
            .is_none()
    );
}

#[test]
fn refusal_is_a_status_and_keeps_quote_identity() {
    let refusal = binding(
        CapabilityKind::SizeQuote,
        EvidenceStatus::Refused {
            reason: RefusalReason::UnsupportedSize,
        },
    );
    assert_eq!(
        refusal.binding.quote_id.as_ref().map(ToString::to_string),
        Some("quote-1".into())
    );
    assert!(matches!(refusal.status, EvidenceStatus::Refused { .. }));
}

#[test]
fn strict_claim_requires_finality_and_complete_coverage() {
    let profile = profile();
    let profile_id = profile.id.clone();
    let mut registry = MechanicsCapabilityRegistry::default();
    assert!(registry.register_profile(&profile, source()).is_ok());

    let mut evidence = binding(CapabilityKind::Mark, EvidenceStatus::Attained);
    evidence.binding.horizon = horizon(
        Finality::Confirmed,
        CoverageState::Partial {
            reason: stable("one pool omitted"),
        },
    );
    assert!(registry.record(evidence).is_ok());
    let check = registry
        .check_prerequisites(&[ClaimPrerequisite::strict(profile_id, CapabilityKind::Mark)]);
    assert_eq!(check.failures.len(), 2);
}

#[test]
fn malformed_horizon_cannot_launder_complete_coverage() {
    let source_id = source();
    let mut sources = BTreeMap::new();
    sources.insert(
        source_id,
        SourceAsOf::without_cursors(joshi_domain::CommitSeq::new(1), None),
    );
    let as_of = AsOfVector {
        catalog_commit: joshi_domain::CommitSeq::new(1),
        sources,
        chain: None,
        projections: BTreeMap::new(),
        rendered_at: "2026-08-18T12:00:00.000000Z"
            .parse::<UtcTimestamp>()
            .unwrap_or_else(|_| unreachable!()),
    };
    let gap = joshi_domain::CoverageId::new("gap").unwrap_or_else(|_| unreachable!());
    assert!(matches!(
        EvidenceHorizon::new(
            as_of,
            Finality::Finalized,
            CoverageState::Complete,
            vec![gap]
        ),
        Err(HorizonError::CompleteWithGaps)
    ));
}

#[test]
fn semantic_preflight_is_explicitly_unverified() {
    let row = binding(CapabilityKind::Mark, EvidenceStatus::Attained);
    assert_eq!(row.authority, EvidenceAuthority::UnverifiedSemantic);
    let profile = profile();
    let mut registry = MechanicsCapabilityRegistry::default();
    assert!(registry.register_profile(&profile, source()).is_ok());
    assert!(registry.record(row).is_ok());
    let check = registry.check_prerequisites(&[ClaimPrerequisite::attained(
        profile.id,
        CapabilityKind::Mark,
    )]);
    assert!(check.semantically_satisfied());
    // A semantic preflight has no API named `is_satisfied` or any durable qualification token.
}

#[test]
fn mark_requires_a_state_observation() {
    let mut row = binding(CapabilityKind::Mark, EvidenceStatus::Attained);
    row.binding.state_observation_id = None;
    assert!(matches!(
        CapabilityEvidence::new(CapabilityKind::Mark, row.status, row.binding),
        Err(BindingError::MissingId("state_observation_id"))
    ));
}

#[test]
fn landed_failure_has_an_outcome_identity_without_a_fill() {
    let mut row = binding(
        CapabilityKind::LandedFillOrFailure,
        EvidenceStatus::Attained,
    );
    row.binding.fill_id = None;
    row.binding.failure_id = Some(stable("failure-1"));
    assert!(
        CapabilityEvidence::new(CapabilityKind::LandedFillOrFailure, row.status, row.binding)
            .is_ok()
    );
}

#[test]
fn liquidation_does_not_imply_terminal_closure() {
    let profile = profile();
    let profile_id = profile.id.clone();
    let mut registry = MechanicsCapabilityRegistry::default();
    assert!(registry.register_profile(&profile, source()).is_ok());
    assert!(
        registry
            .record(binding(
                CapabilityKind::WholePositionLiquidation,
                EvidenceStatus::Attained
            ))
            .is_ok()
    );
    let check = registry.check_prerequisites(&[ClaimPrerequisite::attained(
        profile_id,
        CapabilityKind::TerminalPositionClosure,
    )]);
    assert!(!check.semantically_satisfied());
}
