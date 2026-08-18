//! Private Phase-0 source-spool-catalog orchestration.
//!
//! This module owns ordering only. It performs no provider I/O and grants no publication,
//! execution, retention, or deletion authority.

use joshi_admission::{
    PublicStatus, PublicStoreReceiptV1, Sha256Digest,
    operational::{
        AUTHORITY, ExactByteClosureV1, OperationalStatus, PublicProtectionClass,
        SPOOL_CATALOG_RECEIPT_CONTRACT, SpoolBatchClosureV1, SpoolCatalogReceiptV1,
    },
};
use joshi_domain::{StableString, UtcTimestamp};
use joshi_pump_adapter::PreparedPumpAdmission;
use joshi_spool::{
    CatalogAdmissionAck, LocalSpool, ProtectionDomainId, ProtectionRequest, SegmentClosure,
    SegmentId, SpoolEntry, encode_segment,
};
use joshi_store::{IdempotencyStatus, SqliteStore, Wave5CommitReceipt, Wave5SpoolCatalogBindingV1};
use thiserror::Error;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CirculationFaultPoint {
    AfterStoreCommit,
    AfterCatalogBinding,
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct RegisteredWave5Run<'a> {
    pub run_id: &'a str,
    pub registration_digest: &'a str,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct Wave5CirculationClosure {
    pub segment: SegmentClosure,
    pub origin_segment_bytes: Vec<u8>,
    pub structural_receipt: joshi_store::DurableReceipt,
    pub catalog_receipt_bytes: Vec<u8>,
    pub binding_bytes: Vec<u8>,
    pub binding_receipt: Wave5CommitReceipt,
    pub catalog_ack: CatalogAdmissionAck,
}

/// Seals one public C0 batch before store I/O, commits it once, durably binds the exact catalog
/// receipt to the registered run, and only then records the local catalog ACK.
#[allow(clippy::too_many_arguments, clippy::too_many_lines)] // Keep the fault-ordered closure visible.
pub(crate) fn circulate_public_c0(
    store: &mut SqliteStore,
    spool: &LocalSpool,
    registered_run: RegisteredWave5Run<'_>,
    prepared: &PreparedPumpAdmission,
    segment_id: &str,
    protection_domain: &str,
    created_at: UtcTimestamp,
    binding_id: &str,
    writer_build: &str,
    fault: Option<CirculationFaultPoint>,
) -> Result<Wave5CirculationClosure, Wave5CirculationError> {
    let precommit_entry = prepared.spool_entry(None)?;
    if precommit_entry.closure.admission_digest.is_some() {
        return Err(Wave5CirculationError::Invariant(
            "origin segment contains a postcommit admission digest",
        ));
    }
    let exact_batch_bytes = prepared.exact_batch_bytes();
    let exact_policy_bytes = prepared.exact_policy_bytes();
    let (origin_segment_bytes, segment) = encode_segment(
        SegmentId::new(segment_id)?,
        created_at,
        &[SpoolEntry::EvidenceBatch(precommit_entry.clone())],
        &ProtectionRequest::Public {
            domain: ProtectionDomainId::new(protection_domain)?,
        },
        None,
    )?;
    spool.append_segment(&origin_segment_bytes, &segment)?;
    if spool.read_segment(&segment)? != origin_segment_bytes {
        return Err(Wave5CirculationError::Invariant(
            "durable origin segment readback changed bytes",
        ));
    }

    for source in &prepared.admission_batch().registrations {
        store.register_source(source)?;
    }
    let structural = store.commit_ingest(&prepared.admission_batch().store)?;
    let mut public = PublicStoreReceiptV1::from_committed(
        &structural,
        &prepared.admission_batch().store.evidence,
    )?;
    // The immutable closure describes the one accepted durable occurrence. Invocation-level
    // idempotency is carried by the outer store receipt and must not mutate these retained bytes.
    public.status = PublicStatus::Accepted;
    if fault == Some(CirculationFaultPoint::AfterStoreCommit) {
        return Err(Wave5CirculationError::Injected(
            CirculationFaultPoint::AfterStoreCommit,
        ));
    }

    let catalog_receipt = SpoolCatalogReceiptV1 {
        contract: SPOOL_CATALOG_RECEIPT_CONTRACT.into(),
        schema_version: 1,
        segment_id: segment.segment_id.to_string(),
        protection_domain: segment.domain.to_string(),
        protection_class: PublicProtectionClass::PublicIntegrity,
        exact_segment: ExactByteClosureV1::new(&origin_segment_bytes)?,
        batch: SpoolBatchClosureV1 {
            batch_id: precommit_entry.closure.batch_id,
            exact_batch: ExactByteClosureV1::new(exact_batch_bytes)?,
            logical_batch_digest: Sha256Digest::parse(precommit_entry.closure.logical_digest)?,
            exact_policy: ExactByteClosureV1::new(exact_policy_bytes)?,
            store_admission_digest: Sha256Digest::parse(structural.admission_digest.to_string())?,
        },
        catalog_receipt: public,
        status: OperationalStatus::Accepted,
        authority: AUTHORITY.into(),
    };
    catalog_receipt.validate()?;
    let catalog_receipt_bytes = serde_json::to_vec(&catalog_receipt)?;
    let binding = Wave5SpoolCatalogBindingV1 {
        contract: "joshi.wave5.spool_catalog_binding.v1".into(),
        schema_version: 1,
        catalog_admission_id: binding_id.into(),
        run_registration_id: registered_run.run_id.into(),
        run_registration_digest: registered_run.registration_digest.into(),
        receipt_digest: Sha256Digest::of_bytes(&catalog_receipt_bytes).to_string(),
        authority: AUTHORITY.into(),
    };
    let binding_bytes = serde_json::to_vec(&binding)?;
    let context = store.begin_wave5_commit(
        StableString::new(format!("commit:{binding_id}"))?,
        StableString::new(writer_build)?,
    )?;
    let binding_receipt = store.commit_wave5_spool_catalog_binding_v1(
        &binding_bytes,
        &origin_segment_bytes,
        exact_batch_bytes,
        exact_policy_bytes,
        &catalog_receipt_bytes,
        &context,
    )?;
    if !matches!(
        binding_receipt.status,
        IdempotencyStatus::Accepted | IdempotencyStatus::Idempotent
    ) {
        return Err(Wave5CirculationError::Invariant(
            "catalog binding returned an unsupported status",
        ));
    }
    if fault == Some(CirculationFaultPoint::AfterCatalogBinding) {
        return Err(Wave5CirculationError::Injected(
            CirculationFaultPoint::AfterCatalogBinding,
        ));
    }
    let catalog_ack = spool.record_catalog_receipt(&segment.segment_id, &structural)?;
    if catalog_ack.admission_digest != structural.admission_digest.to_string()
        || catalog_ack.logical_digest != structural.batch_digest.to_string()
        || catalog_ack.from_commit_seq != structural.from_commit_seq.get()
        || catalog_ack.through_commit_seq != structural.through_commit_seq.get()
    {
        return Err(Wave5CirculationError::Invariant(
            "durable catalog ACK differs from the exact store receipt",
        ));
    }
    if spool.read_segment(&segment)? != origin_segment_bytes {
        return Err(Wave5CirculationError::Invariant(
            "catalog ACK rewrote the retained origin segment",
        ));
    }
    Ok(Wave5CirculationClosure {
        segment,
        origin_segment_bytes,
        structural_receipt: structural,
        catalog_receipt_bytes,
        binding_bytes,
        binding_receipt,
        catalog_ack,
    })
}

#[derive(Debug, Error)]
pub enum Wave5CirculationError {
    #[error(transparent)]
    Digest(#[from] joshi_admission::DigestError),
    #[error(transparent)]
    Admission(#[from] joshi_admission::AdmissionError),
    #[error(transparent)]
    Pump(#[from] joshi_pump_adapter::PumpAdapterError),
    #[error(transparent)]
    Spool(#[from] joshi_spool::SpoolError),
    #[error(transparent)]
    Store(#[from] joshi_store::StoreError),
    #[error(transparent)]
    Wire(#[from] joshi_domain::WireStringError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("injected circulation interruption at {0:?}")]
    Injected(CirculationFaultPoint),
    #[error("Wave 5 circulation invariant failed: {0}")]
    Invariant(&'static str),
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wave5_readiness::{
        config, fixture_registration_bundles, now, spool_config, store_bundle,
    };
    use joshi_admission::operational::SpoolCatalogReceiptV1;
    use joshi_store::{StoreMode, Wave5SpoolCatalogBindingV1};

    const DIRECT_C0: &[u8] =
        include_bytes!("../../../fixtures/pump-api/direct-fetch-outcome.synthetic.json");

    fn registered(state: &std::path::Path) -> (SqliteStore, String, String) {
        let (registration, bundle, _) = fixture_registration_bundles().expect("fixture run");
        let mut store = SqliteStore::open(config(state).expect("config"), StoreMode::SingleWriter)
            .expect("store");
        store
            .migrate(now().expect("migration time"))
            .expect("migrate");
        let context = store
            .begin_wave5_commit(
                StableString::new("commit:test-run").expect("batch"),
                StableString::new("test-build").expect("build"),
            )
            .expect("context");
        let receipt = store
            .commit_wave5_run_registration_v1(&store_bundle(&bundle), &context)
            .expect("register run");
        (
            store,
            registration.run_id,
            receipt.exact_document_digest.to_string(),
        )
    }

    fn prepared() -> (PreparedPumpAdmission, UtcTimestamp) {
        let committed_at = now().expect("commit time");
        let prepared =
            joshi_pump_adapter::prepare_direct(DIRECT_C0, "batch:test-c0", committed_at, 10)
                .expect("prepare C0");
        (prepared, committed_at)
    }

    #[test]
    fn crash_after_store_commit_retries_to_one_exact_binding_and_ack() {
        let state = tempfile::tempdir().expect("state");
        let (mut store, run_id, run_digest) = registered(state.path());
        let spool = LocalSpool::open(spool_config(state.path())).expect("spool");
        let (prepared, committed_at) = prepared();
        let run = RegisteredWave5Run {
            run_id: &run_id,
            registration_digest: &run_digest,
        };
        assert!(matches!(
            circulate_public_c0(
                &mut store,
                &spool,
                run,
                &prepared,
                "segment:test-c0",
                "public-fixture-test",
                committed_at,
                "catalog-admission:test-c0",
                "test-build",
                Some(CirculationFaultPoint::AfterStoreCommit),
            ),
            Err(Wave5CirculationError::Injected(
                CirculationFaultPoint::AfterStoreCommit
            ))
        ));
        let closed = circulate_public_c0(
            &mut store,
            &spool,
            run,
            &prepared,
            "segment:test-c0",
            "public-fixture-test",
            committed_at,
            "catalog-admission:test-c0",
            "test-build",
            None,
        )
        .expect("retry circulation");
        assert_eq!(closed.binding_receipt.status, IdempotencyStatus::Accepted);
        assert_eq!(
            closed.catalog_ack.admission_digest,
            closed.structural_receipt.admission_digest.to_string()
        );
    }

    #[test]
    fn crash_after_catalog_binding_retries_exactly_without_rewriting_origin() {
        let state = tempfile::tempdir().expect("state");
        let (mut store, run_id, run_digest) = registered(state.path());
        let spool = LocalSpool::open(spool_config(state.path())).expect("spool");
        let (prepared, committed_at) = prepared();
        let run = RegisteredWave5Run {
            run_id: &run_id,
            registration_digest: &run_digest,
        };
        assert!(matches!(
            circulate_public_c0(
                &mut store,
                &spool,
                run,
                &prepared,
                "segment:test-c0",
                "public-fixture-test",
                committed_at,
                "catalog-admission:test-c0",
                "test-build",
                Some(CirculationFaultPoint::AfterCatalogBinding),
            ),
            Err(Wave5CirculationError::Injected(
                CirculationFaultPoint::AfterCatalogBinding
            ))
        ));
        let original = spool
            .list_segments()
            .expect("segments")
            .into_iter()
            .next()
            .expect("origin closure");
        let original_bytes = spool.read_segment(&original).expect("origin bytes");
        let closed = circulate_public_c0(
            &mut store,
            &spool,
            run,
            &prepared,
            "segment:test-c0",
            "public-fixture-test",
            committed_at,
            "catalog-admission:test-c0",
            "test-build",
            None,
        )
        .expect("retry circulation");
        assert_eq!(closed.binding_receipt.status, IdempotencyStatus::Idempotent);
        assert_eq!(closed.origin_segment_bytes, original_bytes);
        assert_eq!(
            spool.read_segment(&original).expect("retained"),
            original_bytes
        );
    }

    #[test]
    fn self_consistent_wrong_store_digest_is_refused_before_a_second_binding() {
        let state = tempfile::tempdir().expect("state");
        let (mut store, run_id, run_digest) = registered(state.path());
        let spool = LocalSpool::open(spool_config(state.path())).expect("spool");
        let (prepared, committed_at) = prepared();
        let closed = circulate_public_c0(
            &mut store,
            &spool,
            RegisteredWave5Run {
                run_id: &run_id,
                registration_digest: &run_digest,
            },
            &prepared,
            "segment:test-c0",
            "public-fixture-test",
            committed_at,
            "catalog-admission:test-c0",
            "test-build",
            None,
        )
        .expect("circulation");

        let mut receipt: SpoolCatalogReceiptV1 =
            serde_json::from_slice(&closed.catalog_receipt_bytes).expect("receipt");
        let wrong = Sha256Digest::parse(format!("sha256:{}", "f".repeat(64))).expect("digest");
        receipt.batch.store_admission_digest = wrong.clone();
        receipt.catalog_receipt.store_admission_digest = wrong;
        let wrong_receipt_bytes = serde_json::to_vec(&receipt).expect("wrong receipt bytes");
        let mut binding: Wave5SpoolCatalogBindingV1 =
            serde_json::from_slice(&closed.binding_bytes).expect("binding");
        binding.catalog_admission_id = "catalog-admission:wrong-digest".into();
        binding.receipt_digest = Sha256Digest::of_bytes(&wrong_receipt_bytes).to_string();
        let wrong_binding_bytes = serde_json::to_vec(&binding).expect("wrong binding bytes");
        let context = store
            .begin_wave5_commit(
                StableString::new("commit:wrong-digest").expect("batch"),
                StableString::new("test-build").expect("build"),
            )
            .expect("context");
        assert!(
            store
                .commit_wave5_spool_catalog_binding_v1(
                    &wrong_binding_bytes,
                    &closed.origin_segment_bytes,
                    prepared.exact_batch_bytes(),
                    prepared.exact_policy_bytes(),
                    &wrong_receipt_bytes,
                    &context,
                )
                .is_err()
        );
        let status = store
            .load_wave5_store_status_view_v1(&StableString::new(run_id).expect("run"))
            .expect("status");
        assert_eq!(
            status
                .durable_progress
                .iter()
                .filter(|item| {
                    item.progress_id.as_str() == "spool_catalog:catalog-admission:test-c0"
                })
                .count(),
            1
        );
    }
}
