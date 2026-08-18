//! Consolidated, explicitly partial Wave 5 G0 root evidence.
//!
//! This joins the durable source/publication component to the ordinary-pairing HTTP open and
//! restart smoke over the same store state. It closes all eighteen baseline evidence roles, but
//! it does not execute or qualify the deterministic 37-scenario fault schedule.

use crate::{
    g0_inspector_smoke::{G0InspectorSmokeError, G0InspectorSmokeReport, run_g0_inspector_smoke},
    wave5_g0::{
        Wave5G0SourcePublicationError, Wave5G0SourcePublicationReport,
        run_wave5_g0_source_publication,
    },
};
use joshi_admission::Sha256Digest;
use joshi_g0_harness::{EVIDENCE_CONTRACT, EvidenceBundle, EvidenceItem, EvidenceRole};
use serde::Serialize;
use std::path::Path;
use thiserror::Error;

const CONTRACT: &str = "joshi.wave5.g0_root_evidence.v1";
const AUTHORITY: &str = "offline_fixture_evidence_no_fault_qualification";

const REQUIRED_ROLES: [EvidenceRole; 18] = [
    EvidenceRole::Reservation,
    EvidenceRole::OriginSegment,
    EvidenceRole::StoreReceipt,
    EvidenceRole::CatalogBinding,
    EvidenceRole::CatalogAck,
    EvidenceRole::SemanticFact,
    EvidenceRole::PublicationPrepare,
    EvidenceRole::PublicationHead,
    EvidenceRole::PairingExchange,
    EvidenceRole::GlassRead,
    EvidenceRole::MemoryAct,
    EvidenceRole::MemoryEpisode,
    EvidenceRole::ExportManifest,
    EvidenceRole::ImportReceipt,
    EvidenceRole::StatusReadback,
    EvidenceRole::BackupManifest,
    EvidenceRole::RestoreReadback,
    EvidenceRole::ReopenReadback,
];

/// Exact joined result. Nested reports retain the complete producer evidence rather than reducing
/// it to booleans or a detached digest.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct Wave5G0RootEvidenceReport {
    pub contract: &'static str,
    pub schema_version: u16,
    pub authority: &'static str,
    pub status: &'static str,
    pub component_report_digest: String,
    pub inspector_report_digest: String,
    pub run_registration_id: String,
    pub run_registration_digest: String,
    pub publication_id: String,
    pub publication_digest: String,
    pub head_semantic_digest: String,
    pub head_bytes_digest: String,
    pub v10_export_snapshot_id: String,
    pub evidence_bundle: EvidenceBundle,
    pub component: Wave5G0SourcePublicationReport,
    pub inspector: G0InspectorSmokeReport,
    pub partial_root_evidence_closed: bool,
    pub full_offline_fault_walk: bool,
    pub browser_presented: bool,
    pub product_qualified: bool,
    pub live_qualified: bool,
}

#[derive(Debug, Error)]
pub enum Wave5G0RootEvidenceError {
    #[error(transparent)]
    Component(#[from] Wave5G0SourcePublicationError),
    #[error(transparent)]
    Inspector(#[from] G0InspectorSmokeError),
    #[error(transparent)]
    Harness(#[from] joshi_g0_harness::HarnessError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("Wave 5 G0 root evidence invariant failed: {0}")]
    Invariant(&'static str),
}

/// Run and exact-join the existing offline component and paired route/restart smoke.
///
/// # Errors
///
/// Refuses any component failure, publication/run substitution, route-byte mismatch, missing or
/// duplicate evidence role, positive qualification, or malformed evidence digest.
pub async fn run_wave5_g0_root_evidence(
    state: &Path,
) -> Result<Wave5G0RootEvidenceReport, Wave5G0RootEvidenceError> {
    let component = run_wave5_g0_source_publication(state)?;
    let inspector = run_g0_inspector_smoke(state).await?;
    join_reports(component, inspector)
}

fn join_reports(
    component: Wave5G0SourcePublicationReport,
    inspector: G0InspectorSmokeReport,
) -> Result<Wave5G0RootEvidenceReport, Wave5G0RootEvidenceError> {
    validate_report_pair(&component, &inspector)?;
    let component_report_digest =
        Sha256Digest::of_bytes(&serde_json::to_vec(&component)?).to_string();
    let inspector_report_digest =
        Sha256Digest::of_bytes(&serde_json::to_vec(&inspector)?).to_string();

    let mut items = component.partial_fault_result.evidence_bundle.items.clone();
    items.extend([
        EvidenceItem {
            role: EvidenceRole::PairingExchange,
            evidence_id: inspector.pairing_occurrence_id.clone(),
            content_digest: inspector.pairing_occurrence_digest.clone(),
        },
        EvidenceItem {
            role: EvidenceRole::GlassRead,
            evidence_id: format!("glass-read:{}", inspector.session_id),
            content_digest: inspector.route_response_digest.clone(),
        },
        EvidenceItem {
            role: EvidenceRole::ReopenReadback,
            evidence_id: format!("reopen-readback:{}", inspector.publication_id),
            content_digest: inspector.reopened_response_digest.clone(),
        },
    ]);
    items.sort_by(|left, right| {
        (left.role, left.evidence_id.as_str()).cmp(&(right.role, right.evidence_id.as_str()))
    });
    let mut evidence_bundle = EvidenceBundle {
        contract: EVIDENCE_CONTRACT.into(),
        items,
        digest: String::new(),
    };
    evidence_bundle.digest = evidence_bundle.recompute_digest()?;
    validate_complete_bundle(&component, &inspector, &evidence_bundle)?;

    Ok(Wave5G0RootEvidenceReport {
        contract: CONTRACT,
        schema_version: 1,
        authority: AUTHORITY,
        status: "useful_partial",
        component_report_digest,
        inspector_report_digest,
        run_registration_id: component.run_registration_id.clone(),
        run_registration_digest: component.run_registration_digest.clone(),
        publication_id: component.publication_id.clone(),
        publication_digest: component.publication_digest.clone(),
        head_semantic_digest: inspector.head_digest.clone(),
        head_bytes_digest: component.head_digest.clone(),
        v10_export_snapshot_id: component.v10_export_snapshot_id.clone(),
        evidence_bundle,
        component,
        inspector,
        partial_root_evidence_closed: true,
        full_offline_fault_walk: false,
        browser_presented: false,
        product_qualified: false,
        live_qualified: false,
    })
}

fn validate_report_pair(
    component: &Wave5G0SourcePublicationReport,
    inspector: &G0InspectorSmokeReport,
) -> Result<(), Wave5G0RootEvidenceError> {
    component.partial_fault_result.validate()?;
    if component.partial_fault_result.evidence_bundle.items.len() != 15 {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "component must retain exactly its fifteen baseline evidence roles",
        ));
    }
    if component.run_registration_id != inspector.run_registration_id
        || component.run_registration_digest != inspector.run_registration_digest
        || component.source_occurrence_id != inspector.source_occurrence_id
        || component.publication_id != inspector.publication_id
        || component.publication_digest != inspector.publication_digest
        || component.head_digest != inspector.head_bytes_digest
    {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "component and inspector do not close the same run/source/publication/head",
        ));
    }
    if !component.restart_reverified
        || !inspector.paired_route_read_closed
        || !inspector.restart_old_capability_refused
        || !inspector.fresh_pairing_reopen_closed
        || inspector.route_response_digest != inspector.reopened_response_digest
    {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "component/restart/route readback evidence is incomplete",
        ));
    }
    if component.full_offline_fault_walk
        || component.provider_io
        || component.product_qualified
        || component.live_qualified
        || inspector.full_offline_fault_walk
        || inspector.browser_presented
        || inspector.product_qualified
        || inspector.live_qualified
    {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "partial root join cannot carry a positive fault/product/live claim",
        ));
    }
    Ok(())
}

fn validate_complete_bundle(
    component: &Wave5G0SourcePublicationReport,
    inspector: &G0InspectorSmokeReport,
    bundle: &EvidenceBundle,
) -> Result<(), Wave5G0RootEvidenceError> {
    bundle.validate()?;
    if bundle.items.len() != REQUIRED_ROLES.len() {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "root evidence bundle must contain exactly eighteen items",
        ));
    }
    for (item, role) in bundle.items.iter().zip(REQUIRED_ROLES) {
        if item.role != role {
            return Err(Wave5G0RootEvidenceError::Invariant(
                "root evidence roles are missing, duplicated, or reordered",
            ));
        }
    }
    let expected_pairing = EvidenceItem {
        role: EvidenceRole::PairingExchange,
        evidence_id: inspector.pairing_occurrence_id.clone(),
        content_digest: inspector.pairing_occurrence_digest.clone(),
    };
    let expected_glass = EvidenceItem {
        role: EvidenceRole::GlassRead,
        evidence_id: format!("glass-read:{}", inspector.session_id),
        content_digest: inspector.route_response_digest.clone(),
    };
    let expected_reopen = EvidenceItem {
        role: EvidenceRole::ReopenReadback,
        evidence_id: format!("reopen-readback:{}", inspector.publication_id),
        content_digest: inspector.reopened_response_digest.clone(),
    };
    let mut expected = component.partial_fault_result.evidence_bundle.items.clone();
    expected.extend([expected_pairing, expected_glass, expected_reopen]);
    expected.sort_by(|left, right| {
        (left.role, left.evidence_id.as_str()).cmp(&(right.role, right.evidence_id.as_str()))
    });
    if bundle.items != expected {
        return Err(Wave5G0RootEvidenceError::Invariant(
            "root evidence differs from the exact component and inspector artifacts",
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn joins_all_roles_and_refuses_cross_run_or_evidence_substitution() {
        let state = tempfile::tempdir().expect("temporary G0 root evidence state");
        let component = run_wave5_g0_source_publication(state.path()).expect("G0 component");
        let inspector = run_g0_inspector_smoke(state.path())
            .await
            .expect("G0 inspector");
        let report = join_reports(component.clone(), inspector.clone()).expect("root evidence");
        assert_eq!(report.evidence_bundle.items.len(), 18);
        assert_eq!(
            report
                .evidence_bundle
                .items
                .iter()
                .map(|item| item.role)
                .collect::<Vec<_>>(),
            REQUIRED_ROLES
        );
        assert!(report.partial_root_evidence_closed);
        assert!(!report.full_offline_fault_walk);
        assert!(!report.product_qualified);

        let mut wrong_run = inspector.clone();
        wrong_run.run_registration_id = "run:substituted".into();
        assert!(join_reports(component.clone(), wrong_run).is_err());

        let mut wrong_publication = inspector.clone();
        wrong_publication.publication_digest = format!("sha256:{}", "0".repeat(64));
        assert!(join_reports(component.clone(), wrong_publication).is_err());

        let mut wrong_route = inspector;
        wrong_route.reopened_response_digest = format!("sha256:{}", "1".repeat(64));
        assert!(join_reports(component, wrong_route).is_err());

        let mut missing = report.evidence_bundle.clone();
        missing.items.pop();
        missing.digest = missing
            .recompute_digest()
            .expect("recomputed partial digest");
        assert!(validate_complete_bundle(&report.component, &report.inspector, &missing).is_err());

        let mut duplicate = report.evidence_bundle.clone();
        duplicate.items.push(duplicate.items[0].clone());
        duplicate.items.sort_by(|left, right| {
            (left.role, left.evidence_id.as_str()).cmp(&(right.role, right.evidence_id.as_str()))
        });
        assert!(duplicate.recompute_digest().is_err());
    }
}
