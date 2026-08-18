//! Private Wave 5 G0 sole-store authority spine.
//!
//! The adapters in this module resolve exact earlier store rows and allocate all durable clocks,
//! cutoffs, digests, queue generations, and receipts. Public semantic crates supply validators and
//! canonical DTOs only; none of their values is accepted as a durability receipt.

#![allow(
    clippy::items_after_statements,
    clippy::missing_errors_doc,
    clippy::too_many_lines,
    clippy::type_complexity
)]

use crate::{
    BackupManifest, IdempotencyStatus, OperationalCommitContext, ProductionExportCommitReceipt,
    Result, SqliteStore, StoreError, VerifyDepth, Wave5CommitContext, Wave5CommitReceipt,
};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest, WireU64};
use joshi_export::{
    G0ImportArtifactReadbackV1, OperationalExportRequestV2, export_operational_snapshot_v2,
};
pub use joshi_pairing::PairingOccurrenceKind;
use joshi_pairing::{
    PairingClockSample, PairingEpoch, PairingOccurrence, PairingOrigin, PairingWallInstant,
    pairing_epoch_occurrence_id, pairing_occurrence_id, parse_pairing_occurrence,
};
use joshi_projection::ProjectionAuthority;
use joshi_publication::{
    COCKPIT_V2_PUBLICATION_CONTRACT, CockpitPublicationId, CockpitV2CheckpointV1,
    CockpitV2CoverageRefV1, CockpitV2CoverageState, CockpitV2CutoffV1, CockpitV2GapRefV1,
    CockpitV2HeadV1, CockpitV2MembershipKind, CockpitV2MembershipRefV1,
    CockpitV2ObservedUniverseRefV1, CockpitV2OmissionV1, CockpitV2PublicationV1,
    CockpitV2ResolvedSourceFactsInputV1, CockpitV2SourceFactRefV1, CockpitV2SurfaceFieldRefV1,
    CockpitV2SurfaceProfileRefV1, PreparedCockpitV2, ProtectionDomain, finalize_cockpit_v2,
    parse_cockpit_v2_checkpoint, parse_cockpit_v2_head, parse_cockpit_v2_publication,
    parse_cockpit_v2_resolved_source_facts_input, prepare_cockpit_v2_from_resolved_source_facts,
};
use joshi_scientific_memory::{
    EpisodeCompleteness, LotAssociation, MemoryKernel, MemoryOccurrence, PresentationBinding,
    SceneBinding, parse_memory_occurrence_exact,
};
use rusqlite::{Connection, OptionalExtension, Transaction, TransactionBehavior, params};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest as _, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Component, Path, PathBuf},
};

const AUTHORITY: &str = "read_only_no_execution";
const SOURCE_DESCRIPTOR_CONTRACT: &str = "joshi.store.wave5.source_occurrence.v1";
const SOURCE_SURFACE_ID: &str = "pump.discovery.public_c0";
const SOURCE_FIELD_ID: &str = "mint";
const MEMORY_QUALIFICATION: &str = "fixture_authority_unverified_semantic";
const PAIRING_AUTHORITY: &str = "read_only_pairing_exchange";
const MAX_CONTROL_BYTES: usize = 4 * 1024 * 1024;
const MAX_HEADED_COCKPIT_V2_PUBLICATIONS: usize = 256;

/// Store-derived source and coverage occurrence. It is intentionally narrower than raw source
/// bytes and remains fixture authority for G0.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Wave5SourceOccurrenceV1 {
    pub contract: StableString,
    pub schema_version: u16,
    pub source_occurrence_id: StableString,
    pub run_registration_id: StableString,
    pub catalog_admission_id: StableString,
    pub source_receipt_digest: ValueDigest,
    pub source_id: StableString,
    pub surface_profile: CockpitV2SurfaceProfileRefV1,
    pub facts: Vec<CockpitV2SourceFactRefV1>,
    pub eligible_subjects: Vec<StableString>,
    pub memberships: Vec<CockpitV2MembershipRefV1>,
    pub coverage: Vec<CockpitV2CoverageRefV1>,
    pub gaps: Vec<CockpitV2GapRefV1>,
    pub rendered_subjects: Vec<StableString>,
    pub omissions: Vec<CockpitV2OmissionV1>,
    pub known_through_commit_seq: CommitSeq,
    pub maximum_input_available_at: UtcTimestamp,
    pub protection: ProtectionDomain,
    pub authority: ProjectionAuthority,
}

/// Exact source occurrence rederived from its retained public C0 receipt and observation bytes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredWave5SourceOccurrence {
    pub occurrence: Wave5SourceOccurrenceV1,
    pub descriptor_bytes: Vec<u8>,
    pub descriptor_digest: ValueDigest,
    pub commit_seq: CommitSeq,
}

/// Exact prepared V2 material retained in its own crash-visible commit.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredCockpitV2Preparation {
    pub preparation_id: StableString,
    pub source_occurrence_id: StableString,
    pub resolved_input_bytes: Vec<u8>,
    pub resolved_input_digest: ValueDigest,
    pub prepared: PreparedCockpitV2,
    pub commit_seq: CommitSeq,
}

/// Exact immutable V2 body read back and revalidated after restart.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredCockpitV2Publication {
    pub preparation_id: StableString,
    pub source_occurrence_id: StableString,
    pub publication: CockpitV2PublicationV1,
    pub publication_bytes: Vec<u8>,
    pub publication_bytes_digest: ValueDigest,
    pub commit_seq: CommitSeq,
}

/// Exact append-only head read back and revalidated after restart.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredCockpitV2Head {
    pub source_occurrence_id: StableString,
    pub head: CockpitV2HeadV1,
    pub head_bytes: Vec<u8>,
    pub head_digest: ValueDigest,
    pub commit_seq: CommitSeq,
}

/// Store-owned body receipt. Fields are not deserializable or publicly constructible.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CockpitV2CommitReceipt {
    publication_id: CockpitPublicationId,
    publication_digest: ValueDigest,
    publication_bytes_digest: ValueDigest,
    commit_seq: CommitSeq,
    status: IdempotencyStatus,
}

impl CockpitV2CommitReceipt {
    #[must_use]
    pub const fn publication_id(&self) -> &CockpitPublicationId {
        &self.publication_id
    }
    #[must_use]
    pub const fn publication_digest(&self) -> &ValueDigest {
        &self.publication_digest
    }
    #[must_use]
    pub const fn publication_bytes_digest(&self) -> &ValueDigest {
        &self.publication_bytes_digest
    }
    #[must_use]
    pub const fn commit_seq(&self) -> CommitSeq {
        self.commit_seq
    }
    #[must_use]
    pub const fn status(&self) -> IdempotencyStatus {
        self.status
    }
}

/// Exact fixture-authority act or episode revalidated from the durable semantic prefix.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredScientificMemoryOccurrence {
    pub occurrence: MemoryOccurrence,
    pub occurrence_bytes: Vec<u8>,
    pub occurrence_digest: ValueDigest,
    pub scene_publication_id: CockpitPublicationId,
    pub queue_generation: u64,
    pub commit_seq: CommitSeq,
}

/// Private structural receipt for one durable memory append.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScientificMemoryCommitReceipt {
    occurrence_id: StableString,
    occurrence_digest: ValueDigest,
    scene_publication_id: CockpitPublicationId,
    queue_generation: u64,
    commit_seq: CommitSeq,
    status: IdempotencyStatus,
}

impl ScientificMemoryCommitReceipt {
    #[must_use]
    pub const fn occurrence_id(&self) -> &StableString {
        &self.occurrence_id
    }
    #[must_use]
    pub const fn occurrence_digest(&self) -> &ValueDigest {
        &self.occurrence_digest
    }
    #[must_use]
    pub const fn scene_publication_id(&self) -> &CockpitPublicationId {
        &self.scene_publication_id
    }
    #[must_use]
    pub const fn queue_generation(&self) -> u64 {
        self.queue_generation
    }
    #[must_use]
    pub const fn commit_seq(&self) -> CommitSeq {
        self.commit_seq
    }
    #[must_use]
    pub const fn status(&self) -> IdempotencyStatus {
        self.status
    }
}

/// Neutral V9 status identity exposed to the G0 harness/exporter.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave5G0StatusOccurrence {
    pub record_id: StableString,
    pub run_registration_id: StableString,
    pub record_digest: ValueDigest,
    pub record_bytes_digest: ValueDigest,
    pub record_byte_length: u64,
    pub predecessor_record_id: Option<StableString>,
    pub evidence_commit_seq: Option<CommitSeq>,
    pub available_commit_seq: CommitSeq,
}

/// Neutral V9 export-request identity exposed without export authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave5G0ExportOccurrence {
    pub export_binding_id: StableString,
    pub run_registration_id: StableString,
    pub export_request_id: StableString,
    pub validation_id: StableString,
    pub snapshot_id: ValueDigest,
    pub binding_digest: ValueDigest,
    pub binding_bytes_digest: ValueDigest,
    pub binding_byte_length: u64,
    pub truth_fingerprint_digest: ValueDigest,
    pub available_commit_seq: CommitSeq,
    pub available_commit_digest: ValueDigest,
}

/// Neutral V9 restricted-import identity and exact part descriptor.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave5G0ImportOccurrence {
    pub import_id: StableString,
    pub run_registration_id: StableString,
    pub export_binding_id: StableString,
    pub export_request_id: StableString,
    pub analysis_run_id: StableString,
    pub artifact_id: ValueDigest,
    pub manifest_digest: ValueDigest,
    pub snapshot_id: ValueDigest,
    pub registration_digest: ValueDigest,
    pub registration_bytes_digest: ValueDigest,
    pub registration_byte_length: u64,
    pub cas_physical_digest: ValueDigest,
    pub cas_byte_length: u64,
    pub available_commit_seq: CommitSeq,
}

/// Connected, explicitly selected G0 identities. No field means latest/current.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave5G0OccurrencePorts {
    pub run_registration_id: StableString,
    pub source: StoredWave5SourceOccurrence,
    pub publication: StoredCockpitV2Publication,
    pub head: StoredCockpitV2Head,
    pub memory: Vec<StoredScientificMemoryOccurrence>,
    pub status: Vec<Wave5G0StatusOccurrence>,
    pub export: Option<Wave5G0ExportOccurrence>,
    pub import: Option<Wave5G0ImportOccurrence>,
}

#[derive(Clone, Debug)]
struct SourceCapability {
    document: Wave5SourceOccurrenceV1,
    bytes: Vec<u8>,
    digest: ValueDigest,
}

#[derive(Clone, Debug)]
struct StoredReceiptResolution {
    catalog_admission_id: StableString,
    run_registration_id: StableString,
    receipt_digest: ValueDigest,
    store_commit: CommitSeq,
    source_id: StableString,
}

impl SqliteStore {
    fn ensure_g0_backup_reservation(
        &mut self,
        backup_id: &StableString,
        run_registration_id: &StableString,
        catalog_destination: &Path,
        artifact_destination_root: &Path,
        context: &Wave5CommitContext,
    ) -> Result<CommitSeq> {
        type Row = (String, String, Vec<u8>, i64, String, String, i64);
        let existing: Option<Row> = self
            .connection
            .query_row(
                "SELECT run_registration_id,reservation_sha256,reservation_bytes,
                        reservation_byte_length,catalog_destination,
                        artifact_destination_root,created_commit_seq
                 FROM wave5_g0_backup_reservation_v1 WHERE backup_id=?1",
                [backup_id.as_str()],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                        row.get(6)?,
                    ))
                },
            )
            .optional()?;
        if let Some((run, raw, bytes, length, catalog, artifacts, seq)) = existing {
            let document: BackupReservationDocumentV1 = serde_json::from_slice(&bytes)?;
            let digest = bytes_digest(&bytes)?;
            if serde_json::to_vec(&document)? != bytes
                || document.backup_id != *backup_id
                || document.run_registration_id != *run_registration_id
                || document.catalog_destination != catalog_destination.to_string_lossy()
                || document.artifact_destination_root != artifact_destination_root.to_string_lossy()
                || run != run_registration_id.as_str()
                || catalog != catalog_destination.to_string_lossy()
                || artifacts != artifact_destination_root.to_string_lossy()
                || raw_digest(&digest, "G0 backup reservation")? != raw
                || usize_i64(bytes.len(), "G0 backup reservation bytes")? != length
            {
                return Err(StoreError::IdentityConflict {
                    kind: "G0 backup reservation",
                    identity: backup_id.to_string(),
                });
            }
            return Ok(CommitSeq::new(as_u64(seq, "G0 backup reservation commit")?));
        }

        validate_backup_destinations(
            &self.config.catalog_path,
            &self.config.blob_root,
            &self.config.export_root,
            catalog_destination,
            artifact_destination_root,
        )?;
        let document = BackupReservationDocumentV1 {
            contract: stable("joshi.store.wave5.g0.backup_reservation.v1")?,
            schema_version: 1,
            backup_id: backup_id.clone(),
            run_registration_id: run_registration_id.clone(),
            catalog_destination: catalog_destination.to_string_lossy().into_owned(),
            artifact_destination_root: artifact_destination_root.to_string_lossy().into_owned(),
            authority: stable(AUTHORITY)?,
        };
        let bytes = serde_json::to_vec(&document)?;
        let digest = bytes_digest(&bytes)?;
        let reservation_context = reservation_context(context, "backup", backup_id)?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        insert_commit(&tx, &reservation_context, "maintenance", &digest)?;
        let seq = tx.last_insert_rowid();
        tx.execute(
            "INSERT INTO wave5_g0_backup_reservation_v1
             (backup_id,run_registration_id,reservation_sha256,reservation_bytes,
              reservation_byte_length,catalog_destination,artifact_destination_root,
              authority,created_commit_seq)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)",
            params![
                backup_id.as_str(),
                run_registration_id.as_str(),
                raw_digest(&digest, "G0 backup reservation")?,
                bytes,
                sqlite_usize(bytes.len(), "G0 backup reservation bytes")?,
                document.catalog_destination,
                document.artifact_destination_root,
                AUTHORITY,
                seq,
            ],
        )?;
        tx.commit()?;
        Ok(CommitSeq::new(as_u64(seq, "G0 backup reservation commit")?))
    }

    fn ensure_g0_backup_restore_reservation(
        &mut self,
        restore_id: &StableString,
        backup_id: &StableString,
        catalog_destination: &Path,
        artifact_destination_root: &Path,
        context: &Wave5CommitContext,
    ) -> Result<CommitSeq> {
        type Row = (String, String, Vec<u8>, i64, String, String, i64);
        let existing: Option<Row> = self
            .connection
            .query_row(
                "SELECT backup_id,reservation_sha256,reservation_bytes,
                        reservation_byte_length,catalog_destination,
                        artifact_destination_root,created_commit_seq
                 FROM wave5_g0_backup_restore_reservation_v1 WHERE restore_id=?1",
                [restore_id.as_str()],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                        row.get(6)?,
                    ))
                },
            )
            .optional()?;
        if let Some((backup, raw, bytes, length, catalog, artifacts, seq)) = existing {
            let document: BackupRestoreReservationDocumentV1 = serde_json::from_slice(&bytes)?;
            let digest = bytes_digest(&bytes)?;
            if serde_json::to_vec(&document)? != bytes
                || document.restore_id != *restore_id
                || document.backup_id != *backup_id
                || document.catalog_destination != catalog_destination.to_string_lossy()
                || document.artifact_destination_root != artifact_destination_root.to_string_lossy()
                || backup != backup_id.as_str()
                || catalog != catalog_destination.to_string_lossy()
                || artifacts != artifact_destination_root.to_string_lossy()
                || raw_digest(&digest, "G0 restore reservation")? != raw
                || usize_i64(bytes.len(), "G0 restore reservation bytes")? != length
            {
                return Err(StoreError::IdentityConflict {
                    kind: "G0 backup restore reservation",
                    identity: restore_id.to_string(),
                });
            }
            return Ok(CommitSeq::new(as_u64(
                seq,
                "G0 restore reservation commit",
            )?));
        }

        validate_restore_destinations(
            &self.config.catalog_path,
            &self.config.blob_root,
            &self.config.export_root,
            catalog_destination,
            artifact_destination_root,
        )?;
        let document = BackupRestoreReservationDocumentV1 {
            contract: stable("joshi.store.wave5.g0.backup_restore_reservation.v1")?,
            schema_version: 1,
            restore_id: restore_id.clone(),
            backup_id: backup_id.clone(),
            catalog_destination: catalog_destination.to_string_lossy().into_owned(),
            artifact_destination_root: artifact_destination_root.to_string_lossy().into_owned(),
            authority: stable(AUTHORITY)?,
        };
        let bytes = serde_json::to_vec(&document)?;
        let digest = bytes_digest(&bytes)?;
        let reservation_context = reservation_context(context, "restore", restore_id)?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        insert_commit(&tx, &reservation_context, "maintenance", &digest)?;
        let seq = tx.last_insert_rowid();
        tx.execute(
            "INSERT INTO wave5_g0_backup_restore_reservation_v1
             (restore_id,backup_id,reservation_sha256,reservation_bytes,
              reservation_byte_length,catalog_destination,artifact_destination_root,
              authority,created_commit_seq)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)",
            params![
                restore_id.as_str(),
                backup_id.as_str(),
                raw_digest(&digest, "G0 restore reservation")?,
                bytes,
                sqlite_usize(bytes.len(), "G0 restore reservation bytes")?,
                document.catalog_destination,
                document.artifact_destination_root,
                AUTHORITY,
                seq,
            ],
        )?;
        tx.commit()?;
        Ok(CommitSeq::new(as_u64(
            seq,
            "G0 restore reservation commit",
        )?))
    }

    /// Resolves exact accepted public C0 receipt bytes into a deterministic fact/coverage
    /// occurrence and appends it atomically.
    ///
    /// # Errors
    ///
    /// Refuses non-retained/substituted receipts, private inputs, unsupported C0 shapes, empty or
    /// one-subject denominators, later clocks, conflicts, or failed durable commit.
    pub fn commit_wave5_c0_source_occurrence_v1(
        &mut self,
        exact_public_receipt_bytes: &[u8],
        context: &Wave5CommitContext,
    ) -> Result<Wave5CommitReceipt> {
        let capability = self.resolve_c0_source(exact_public_receipt_bytes)?;
        let operation = digest_json(&(
            "joshi.store.wave5_c0_source_occurrence_commit.v1",
            capability.document.source_occurrence_id.as_str(),
            capability.digest.as_str(),
            capability.document.known_through_commit_seq.get(),
        ))?;
        let occurrence_id = capability.document.source_occurrence_id.clone();
        let exact_digest = capability.digest.clone();
        self.commit_wave5(
            context,
            "projection",
            &occurrence_id,
            &exact_digest,
            &operation,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO wave5_source_occurrence_v1
                     (source_occurrence_id,run_registration_id,catalog_admission_id,source_id,
                      receipt_sha256,descriptor_contract,descriptor_sha256,descriptor_bytes,
                      descriptor_byte_length,surface_profile_sha256,fact_count,
                      eligible_subject_count,membership_count,coverage_count,gap_count,
                      rendered_subject_count,omission_count,hot_subject_count,
                      cold_control_subject_count,
                      known_through_commit_seq,maximum_input_available_wall_us,protection_class,
                      authority,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,
                             ?15,?16,?17,?18,?19,?20,?21,'public_integrity',?22,?23)",
                    params![
                        capability.document.source_occurrence_id.as_str(),
                        capability.document.run_registration_id.as_str(),
                        capability.document.catalog_admission_id.as_str(),
                        capability.document.source_id.as_str(),
                        raw_digest(&capability.document.source_receipt_digest, "C0 receipt")?,
                        SOURCE_DESCRIPTOR_CONTRACT,
                        raw_digest(&capability.digest, "source descriptor")?,
                        capability.bytes,
                        sqlite_usize(capability.bytes.len(), "source descriptor bytes")?,
                        raw_digest(
                            &capability.document.surface_profile.profile_digest,
                            "surface profile",
                        )?,
                        sqlite_usize(capability.document.facts.len(), "source facts")?,
                        sqlite_usize(
                            capability.document.eligible_subjects.len(),
                            "eligible subjects",
                        )?,
                        sqlite_usize(capability.document.memberships.len(), "memberships")?,
                        sqlite_usize(capability.document.coverage.len(), "source coverage")?,
                        sqlite_usize(capability.document.gaps.len(), "source gaps")?,
                        sqlite_usize(
                            capability.document.rendered_subjects.len(),
                            "rendered subjects",
                        )?,
                        sqlite_usize(capability.document.omissions.len(), "omissions")?,
                        sqlite_usize(
                            capability
                                .document
                                .memberships
                                .iter()
                                .filter(|value| value.membership == CockpitV2MembershipKind::Hot)
                                .count(),
                            "hot subjects",
                        )?,
                        sqlite_usize(
                            capability
                                .document
                                .memberships
                                .iter()
                                .filter(|value| value.membership
                                    == CockpitV2MembershipKind::ColdControl)
                                .count(),
                            "cold-control subjects",
                        )?,
                        sqlite_u64(
                            capability.document.known_through_commit_seq.get(),
                            "source cutoff",
                        )?,
                        timestamp_us(
                            capability.document.maximum_input_available_at,
                            "source maximum availability",
                        )?,
                        AUTHORITY,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )
    }

    /// Loads and fully rederives one C0 source occurrence after restart.
    ///
    /// # Errors
    ///
    /// Refuses changed descriptor bytes/digests/counts/cutoffs or changed retained source bytes.
    pub fn load_wave5_source_occurrence_v1(
        &self,
        source_occurrence_id: &StableString,
    ) -> Result<Option<StoredWave5SourceOccurrence>> {
        type Row = (
            String,
            Vec<u8>,
            String,
            i64,
            String,
            i64,
            i64,
            i64,
            i64,
            i64,
            i64,
            i64,
            i64,
            i64,
            String,
            i64,
            i64,
        );
        let row: Option<Row> = self
            .connection
            .query_row(
                "SELECT catalog_admission_id,descriptor_bytes,descriptor_sha256,
                        descriptor_byte_length,receipt_sha256,fact_count,eligible_subject_count,
                        membership_count,coverage_count,gap_count,rendered_subject_count,
                        omission_count,hot_subject_count,cold_control_subject_count,
                        surface_profile_sha256,known_through_commit_seq,created_commit_seq
                 FROM wave5_source_occurrence_v1 WHERE source_occurrence_id=?1",
                [source_occurrence_id.as_str()],
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
                        row.get(8)?,
                        row.get(9)?,
                        row.get(10)?,
                        row.get(11)?,
                        row.get(12)?,
                        row.get(13)?,
                        row.get(14)?,
                        row.get(15)?,
                        row.get(16)?,
                    ))
                },
            )
            .optional()?;
        let Some((
            catalog_admission,
            bytes,
            raw,
            length,
            receipt_raw,
            facts,
            subjects,
            memberships,
            coverage,
            gaps,
            rendered,
            omissions,
            hot,
            cold,
            profile_raw,
            cut,
            seq,
        )) = row
        else {
            return Ok(None);
        };
        let receipt_bytes: Vec<u8> = self.connection.query_row(
            "SELECT s.receipt_bytes FROM spool_catalog_admission s
             JOIN wave5_spool_catalog_binding_v1 b
               ON b.segment_id=s.segment_id AND b.batch_id=s.batch_id
             WHERE b.catalog_admission_id=?1",
            [&catalog_admission],
            |row| row.get(0),
        )?;
        let capability = self.resolve_c0_source(&receipt_bytes)?;
        let stored_digest = qualified_raw_digest(&raw, "source descriptor")?;
        if capability.document.source_occurrence_id != *source_occurrence_id
            || capability.bytes != bytes
            || capability.digest != stored_digest
            || usize_i64(capability.bytes.len(), "source descriptor bytes")? != length
            || raw_digest(&capability.document.source_receipt_digest, "C0 receipt")? != receipt_raw
            || usize_i64(capability.document.facts.len(), "source facts")? != facts
            || usize_i64(
                capability.document.eligible_subjects.len(),
                "eligible subjects",
            )? != subjects
            || usize_i64(capability.document.memberships.len(), "memberships")? != memberships
            || usize_i64(capability.document.coverage.len(), "source coverage")? != coverage
            || usize_i64(capability.document.gaps.len(), "source gaps")? != gaps
            || usize_i64(
                capability.document.rendered_subjects.len(),
                "rendered subjects",
            )? != rendered
            || usize_i64(capability.document.omissions.len(), "omissions")? != omissions
            || usize_i64(
                capability
                    .document
                    .memberships
                    .iter()
                    .filter(|value| value.membership == CockpitV2MembershipKind::Hot)
                    .count(),
                "hot subjects",
            )? != hot
            || usize_i64(
                capability
                    .document
                    .memberships
                    .iter()
                    .filter(|value| value.membership == CockpitV2MembershipKind::ColdControl)
                    .count(),
                "cold-control subjects",
            )? != cold
            || raw_digest(
                &capability.document.surface_profile.profile_digest,
                "surface profile",
            )? != profile_raw
            || sqlite_u64(
                capability.document.known_through_commit_seq.get(),
                "source cutoff",
            )? != cut
        {
            return Err(StoreError::InvalidBatch(
                "stored C0 source occurrence differs from store rederivation".into(),
            ));
        }
        Ok(Some(StoredWave5SourceOccurrence {
            occurrence: capability.document,
            descriptor_bytes: bytes,
            descriptor_digest: stored_digest,
            commit_seq: CommitSeq::new(as_u64(seq, "source occurrence commit")?),
        }))
    }

    /// Derives canonical publication input from one reverified source occurrence and retains the
    /// exact prepare stage in its own transaction.
    ///
    /// # Errors
    ///
    /// Refuses unknown/corrupt source input, invalid hot/control fixture partition, a future cut,
    /// an identity conflict, or failed commit.
    pub fn prepare_cockpit_v2_from_store_v1(
        &mut self,
        source_occurrence_id: &StableString,
        context: &Wave5CommitContext,
    ) -> Result<Wave5CommitReceipt> {
        let source = self
            .load_wave5_source_occurrence_v1(source_occurrence_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 5 source occurrence",
                identity: source_occurrence_id.to_string(),
            })?;
        let input = resolved_publication_input(&source.occurrence)?;
        let input_bytes = input.canonical_bytes().map_err(publication_error)?;
        let input_digest = bytes_digest(&input_bytes)?;
        let prepared =
            prepare_cockpit_v2_from_resolved_source_facts(input).map_err(publication_error)?;
        let preparation_id = stable(format!(
            "cockpit-v2-prep:{}",
            raw_digest(&prepared.manifest.container_digest, "Cockpit V2 container")?
        ))?;
        let checkpoint_bytes = serde_json::to_vec(&prepared.checkpoint)?;
        let operation = digest_json(&(
            "joshi.store.cockpit_v2_prepare_commit.v1",
            preparation_id.as_str(),
            source_occurrence_id.as_str(),
            input_digest.as_str(),
            prepared.manifest.semantic_digest.as_str(),
            prepared.manifest.container_digest.as_str(),
            prepared.checkpoint.checkpoint_digest.as_str(),
        ))?;
        self.commit_wave5(
            context,
            "projection",
            &preparation_id,
            &prepared.manifest.container_digest,
            &operation,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO cockpit_v2_preparation_v1
                     (preparation_id,source_occurrence_id,resolved_input_sha256,
                      resolved_input_bytes,resolved_input_byte_length,semantic_sha256,
                      semantic_bytes,semantic_byte_length,container_sha256,container_bytes,
                      container_byte_length,checkpoint_sha256,checkpoint_bytes,
                      checkpoint_byte_length,through_commit_seq,knowledge_wall_us,authority,
                      created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18)",
                    params![
                        preparation_id.as_str(),
                        source_occurrence_id.as_str(),
                        raw_digest(&input_digest, "resolved input")?,
                        input_bytes,
                        sqlite_usize(input_bytes.len(), "resolved input bytes")?,
                        raw_digest(&prepared.manifest.semantic_digest, "Cockpit semantic")?,
                        prepared.semantic_bytes,
                        sqlite_usize(prepared.semantic_bytes.len(), "Cockpit semantic bytes")?,
                        raw_digest(&prepared.manifest.container_digest, "Cockpit container")?,
                        prepared.container_bytes,
                        sqlite_usize(prepared.container_bytes.len(), "Cockpit container bytes")?,
                        raw_digest(&prepared.checkpoint.checkpoint_digest, "Cockpit checkpoint")?,
                        checkpoint_bytes,
                        sqlite_usize(checkpoint_bytes.len(), "Cockpit checkpoint bytes")?,
                        sqlite_u64(
                            prepared
                                .manifest
                                .cutoff
                                .commit_through
                                .ok_or_else(|| {
                                    StoreError::InvalidBatch(
                                        "G0 Cockpit cut requires catalog commit".into(),
                                    )
                                })?
                                .get(),
                            "Cockpit cutoff",
                        )?,
                        timestamp_us(
                            prepared.manifest.cutoff.knowledge_at,
                            "Cockpit knowledge cut"
                        )?,
                        AUTHORITY,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )
    }

    /// Loads and revalidates exact V2 preparation bytes after restart.
    pub fn load_cockpit_v2_preparation_v1(
        &self,
        preparation_id: &StableString,
    ) -> Result<Option<StoredCockpitV2Preparation>> {
        type Row = (String, Vec<u8>, String, Vec<u8>, Vec<u8>, Vec<u8>, i64);
        let row: Option<Row> = self
            .connection
            .query_row(
                "SELECT source_occurrence_id,resolved_input_bytes,resolved_input_sha256,
                    semantic_bytes,container_bytes,checkpoint_bytes,created_commit_seq
             FROM cockpit_v2_preparation_v1 WHERE preparation_id=?1",
                [preparation_id.as_str()],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                        row.get(6)?,
                    ))
                },
            )
            .optional()?;
        let Some((
            source_id,
            input_bytes,
            input_raw,
            semantic_bytes,
            container_bytes,
            checkpoint_bytes,
            seq,
        )) = row
        else {
            return Ok(None);
        };
        let source_id = stable(source_id)?;
        let source = self
            .load_wave5_source_occurrence_v1(&source_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Wave 5 source occurrence",
                identity: source_id.to_string(),
            })?;
        let derived = resolved_publication_input(&source.occurrence)?;
        if derived.canonical_bytes().map_err(publication_error)? != input_bytes {
            return Err(StoreError::InvalidBatch(
                "persisted Cockpit resolved input differs from source rederivation".into(),
            ));
        }
        let parsed = parse_cockpit_v2_resolved_source_facts_input(&input_bytes)
            .map_err(publication_error)?;
        let prepared =
            prepare_cockpit_v2_from_resolved_source_facts(parsed).map_err(publication_error)?;
        let checkpoint: CockpitV2CheckpointV1 =
            parse_cockpit_v2_checkpoint(&checkpoint_bytes).map_err(publication_error)?;
        let digest = bytes_digest(&input_bytes)?;
        if raw_digest(&digest, "resolved input")? != input_raw
            || prepared.semantic_bytes != semantic_bytes
            || prepared.container_bytes != container_bytes
            || prepared.checkpoint != checkpoint
            || stable(format!(
                "cockpit-v2-prep:{}",
                raw_digest(&prepared.manifest.container_digest, "container")?
            ))? != *preparation_id
        {
            return Err(StoreError::InvalidBatch(
                "persisted Cockpit V2 preparation is corrupt".into(),
            ));
        }
        Ok(Some(StoredCockpitV2Preparation {
            preparation_id: preparation_id.clone(),
            source_occurrence_id: source_id,
            resolved_input_bytes: input_bytes,
            resolved_input_digest: digest,
            prepared,
            commit_seq: CommitSeq::new(as_u64(seq, "Cockpit prepare commit")?),
        }))
    }

    /// Allocates the catalog commit and finalizes one exact immutable V2 publication inside the
    /// same SQL transaction. The caller supplies identities, never commit clocks or a receipt.
    #[allow(clippy::needless_pass_by_value)]
    pub fn commit_cockpit_v2_publication_v1(
        &mut self,
        preparation_id: &StableString,
        publication_id: CockpitPublicationId,
        supersedes_publication_id: Option<CockpitPublicationId>,
        context: &Wave5CommitContext,
    ) -> Result<CockpitV2CommitReceipt> {
        self.require_writer()?;
        let preparation = self
            .load_cockpit_v2_preparation_v1(preparation_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Cockpit V2 preparation",
                identity: preparation_id.to_string(),
            })?;
        let previous = supersedes_publication_id
            .as_ref()
            .map(|id| self.load_cockpit_v2_publication_v1(id))
            .transpose()?
            .flatten();
        let operation = digest_json(&(
            "joshi.store.cockpit_v2_publication_commit.v1",
            preparation_id.as_str(),
            publication_id.as_str(),
            preparation.prepared.manifest.container_digest.as_str(),
            supersedes_publication_id
                .as_ref()
                .map(CockpitPublicationId::as_str),
        ))?;
        if let Some((seq, existing)) = existing_commit(&self.connection, context.batch_id.as_str())?
        {
            if existing != raw_digest(&operation, "Cockpit operation")? {
                return Err(StoreError::IdentityConflict {
                    kind: "Cockpit V2 publication batch",
                    identity: context.batch_id.to_string(),
                });
            }
            let loaded = self
                .load_cockpit_v2_publication_v1(&publication_id)?
                .ok_or_else(|| StoreError::IdentityConflict {
                    kind: "Cockpit V2 publication",
                    identity: publication_id.to_string(),
                })?;
            if loaded.commit_seq.get() != as_u64(seq, "Cockpit commit")?
                || loaded.preparation_id != *preparation_id
            {
                return Err(StoreError::IdentityConflict {
                    kind: "Cockpit V2 publication",
                    identity: publication_id.to_string(),
                });
            }
            return Ok(cockpit_receipt(&loaded, IdempotencyStatus::Idempotent));
        }
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        insert_commit(&tx, context, "projection", &operation)?;
        let seq_i64 = tx.last_insert_rowid();
        let seq = CommitSeq::new(as_u64(seq_i64, "Cockpit publication commit")?);
        let publication = finalize_cockpit_v2(
            &preparation.prepared,
            publication_id.clone(),
            seq,
            supersedes_publication_id.clone(),
            previous.as_ref().map(|value| &value.publication),
        )
        .map_err(publication_error)?;
        let publication_bytes = publication.canonical_bytes().map_err(publication_error)?;
        let publication_bytes_digest = bytes_digest(&publication_bytes)?;
        tx.execute(
            "INSERT INTO cockpit_v2_publication_v1
             (publication_id,preparation_id,source_occurrence_id,publication_contract,
              publication_sha256,publication_bytes_sha256,publication_bytes,
              publication_byte_length,semantic_sha256,container_sha256,checkpoint_sha256,
              through_commit_seq,supersedes_publication_id,authority,created_commit_seq)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15)",
            params![
                publication_id.as_str(),
                preparation_id.as_str(),
                preparation.source_occurrence_id.as_str(),
                COCKPIT_V2_PUBLICATION_CONTRACT,
                raw_digest(&publication.publication_digest, "Cockpit publication")?,
                raw_digest(&publication_bytes_digest, "Cockpit publication bytes")?,
                publication_bytes,
                sqlite_usize(publication_bytes.len(), "Cockpit publication bytes")?,
                raw_digest(&publication.manifest.semantic_digest, "Cockpit semantic")?,
                raw_digest(&publication.manifest.container_digest, "Cockpit container")?,
                raw_digest(
                    &publication.checkpoint.checkpoint_digest,
                    "Cockpit checkpoint"
                )?,
                sqlite_u64(
                    publication
                        .manifest
                        .cutoff
                        .commit_through
                        .ok_or_else(|| StoreError::InvalidBatch(
                            "G0 publication requires commit cutoff".into()
                        ))?
                        .get(),
                    "Cockpit cutoff"
                )?,
                supersedes_publication_id
                    .as_ref()
                    .map(CockpitPublicationId::as_str),
                AUTHORITY,
                seq_i64,
            ],
        )?;
        tx.commit()?;
        Ok(CockpitV2CommitReceipt {
            publication_id,
            publication_digest: publication.publication_digest,
            publication_bytes_digest,
            commit_seq: seq,
            status: IdempotencyStatus::Accepted,
        })
    }

    /// Loads exact immutable body bytes by explicit publication identity.
    pub fn load_cockpit_v2_publication_v1(
        &self,
        publication_id: &CockpitPublicationId,
    ) -> Result<Option<StoredCockpitV2Publication>> {
        type Row = (String, String, Vec<u8>, String, String, i64);
        let row: Option<Row> = self
            .connection
            .query_row(
                "SELECT preparation_id,source_occurrence_id,publication_bytes,publication_sha256,
                    publication_bytes_sha256,created_commit_seq
             FROM cockpit_v2_publication_v1 WHERE publication_id=?1",
                [publication_id.as_str()],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                    ))
                },
            )
            .optional()?;
        let Some((prep, source, bytes, semantic_raw, bytes_raw, seq)) = row else {
            return Ok(None);
        };
        let publication = parse_cockpit_v2_publication(&bytes).map_err(publication_error)?;
        let bytes_digest = bytes_digest(&bytes)?;
        if publication.publication_id != *publication_id
            || raw_digest(&publication.publication_digest, "Cockpit publication")? != semantic_raw
            || raw_digest(&bytes_digest, "Cockpit publication bytes")? != bytes_raw
            || publication.commit_seq.get() != as_u64(seq, "Cockpit publication commit")?
        {
            return Err(StoreError::InvalidBatch(
                "persisted Cockpit V2 publication is corrupt".into(),
            ));
        }
        let prep = stable(prep)?;
        let prepared = self.load_cockpit_v2_preparation_v1(&prep)?.ok_or_else(|| {
            StoreError::MissingIdentity {
                kind: "Cockpit V2 preparation",
                identity: prep.to_string(),
            }
        })?;
        if publication.manifest != prepared.prepared.manifest
            || publication.checkpoint != prepared.prepared.checkpoint
        {
            return Err(StoreError::InvalidBatch(
                "Cockpit V2 body differs from exact preparation".into(),
            ));
        }
        Ok(Some(StoredCockpitV2Publication {
            preparation_id: prep,
            source_occurrence_id: stable(source)?,
            publication,
            publication_bytes: bytes,
            publication_bytes_digest: bytes_digest,
            commit_seq: CommitSeq::new(as_u64(seq, "Cockpit publication commit")?),
        }))
    }

    /// Appends the immutable head in a transaction later than the body commit.
    pub fn append_cockpit_v2_head_v1(
        &mut self,
        publication_id: &CockpitPublicationId,
        context: &Wave5CommitContext,
    ) -> Result<Wave5CommitReceipt> {
        let body = self
            .load_cockpit_v2_publication_v1(publication_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Cockpit V2 publication",
                identity: publication_id.to_string(),
            })?;
        let head =
            CockpitV2HeadV1::from_publication(&body.publication).map_err(publication_error)?;
        let head_bytes = head.canonical_bytes().map_err(publication_error)?;
        let head_digest = bytes_digest(&head_bytes)?;
        let occurrence_id = stable(format!("cockpit-v2-head:{}", publication_id.as_str()))?;
        let operation = digest_json(&(
            "joshi.store.cockpit_v2_head_commit.v1",
            publication_id.as_str(),
            head.head_digest.as_str(),
            body.publication
                .supersedes_publication_id
                .as_ref()
                .map(CockpitPublicationId::as_str),
        ))?;
        self.commit_wave5(
            context,
            "projection",
            &occurrence_id,
            &head_digest,
            &operation,
            |tx, seq| {
                tx.execute(
                    "INSERT INTO cockpit_v2_head_v1
                 (publication_id,source_occurrence_id,head_sha256,head_bytes,head_byte_length,
                  supersedes_head_publication_id,authority,created_commit_seq)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8)",
                    params![
                        publication_id.as_str(),
                        body.source_occurrence_id.as_str(),
                        raw_digest(&head.head_digest, "Cockpit head")?,
                        head_bytes,
                        sqlite_usize(head_bytes.len(), "Cockpit head bytes")?,
                        body.publication
                            .supersedes_publication_id
                            .as_ref()
                            .map(CockpitPublicationId::as_str),
                        AUTHORITY,
                        seq
                    ],
                )?;
                Ok(())
            },
        )
    }

    /// Loads one exact head by its explicit publication identity.
    pub fn load_cockpit_v2_head_v1(
        &self,
        publication_id: &CockpitPublicationId,
    ) -> Result<Option<StoredCockpitV2Head>> {
        type Row = (String, Vec<u8>, String, i64);
        let row: Option<Row> = self
            .connection
            .query_row(
                "SELECT source_occurrence_id,head_bytes,head_sha256,created_commit_seq
             FROM cockpit_v2_head_v1 WHERE publication_id=?1",
                [publication_id.as_str()],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .optional()?;
        let Some((source, bytes, raw, seq)) = row else {
            return Ok(None);
        };
        let head = parse_cockpit_v2_head(&bytes).map_err(publication_error)?;
        let body = self
            .load_cockpit_v2_publication_v1(publication_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Cockpit V2 publication",
                identity: publication_id.to_string(),
            })?;
        head.validate_against(&body.publication)
            .map_err(publication_error)?;
        let exact = bytes_digest(&bytes)?;
        if raw_digest(&head.head_digest, "Cockpit head")? != raw || exact != bytes_digest(&bytes)? {
            return Err(StoreError::InvalidBatch(
                "persisted Cockpit V2 head is corrupt".into(),
            ));
        }
        Ok(Some(StoredCockpitV2Head {
            source_occurrence_id: stable(source)?,
            head,
            head_bytes: bytes,
            head_digest: exact,
            commit_seq: CommitSeq::new(as_u64(seq, "Cockpit head commit")?),
        }))
    }

    /// Lists the bounded exact set of headed Cockpit V2 publications in durable head order.
    ///
    /// Every returned body and head is reparsed and cross-validated through the same exact
    /// readback path as an individual lookup. The method refuses an oversized catalog rather than
    /// truncating an eligible publication set into a misleading index.
    pub fn list_headed_cockpit_v2_publications_v1(
        &self,
    ) -> Result<Vec<(StoredCockpitV2Publication, StoredCockpitV2Head)>> {
        let mut statement = self.connection.prepare(
            "SELECT publication_id FROM cockpit_v2_head_v1
             ORDER BY created_commit_seq ASC, publication_id ASC
             LIMIT ?1",
        )?;
        let limit = i64::try_from(MAX_HEADED_COCKPIT_V2_PUBLICATIONS + 1).map_err(|_| {
            StoreError::InvalidBatch("Cockpit V2 index bound does not fit SQLite".into())
        })?;
        let rows = statement.query_map([limit], |row| row.get::<_, String>(0))?;
        let identifiers = rows.collect::<std::result::Result<Vec<_>, _>>()?;
        drop(statement);
        if identifiers.len() > MAX_HEADED_COCKPIT_V2_PUBLICATIONS {
            return Err(StoreError::InvalidBatch(
                "headed Cockpit V2 publication index exceeds its exact bound".into(),
            ));
        }
        identifiers
            .into_iter()
            .map(|raw| {
                let publication_id = CockpitPublicationId::new(raw)
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
                let publication = self
                    .load_cockpit_v2_publication_v1(&publication_id)?
                    .ok_or_else(|| StoreError::MissingIdentity {
                        kind: "Cockpit V2 publication",
                        identity: publication_id.to_string(),
                    })?;
                let head = self
                    .load_cockpit_v2_head_v1(&publication_id)?
                    .ok_or_else(|| StoreError::MissingIdentity {
                        kind: "Cockpit V2 head",
                        identity: publication_id.to_string(),
                    })?;
                if publication.source_occurrence_id != head.source_occurrence_id
                    || publication.commit_seq >= head.commit_seq
                {
                    return Err(StoreError::InvalidBatch(
                        "headed Cockpit V2 index lineage differs".into(),
                    ));
                }
                Ok((publication, head))
            })
            .collect()
    }

    /// Privately admits one exact canonical scientific-memory act or episode.
    ///
    /// G0 remains fixture authority: the store reconstructs the exact prefix, resolves the scene
    /// to an immutable headed Cockpit publication, and does not promote public kernel state.
    pub fn commit_scientific_memory_occurrence_v1(
        &mut self,
        exact_occurrence_bytes: &[u8],
        context: &Wave5CommitContext,
    ) -> Result<ScientificMemoryCommitReceipt> {
        self.require_writer()?;
        let parsed = parse_memory_occurrence_exact(exact_occurrence_bytes).map_err(|error| {
            StoreError::InvalidBatch(format!("scientific-memory bytes: {error}"))
        })?;
        let occurrence_digest = bytes_digest(exact_occurrence_bytes)?;
        let occurrence_id = stable(parsed.occurrence_id())?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        if let Some((seq, _)) = existing_commit(&tx, context.batch_id.as_str())? {
            let exact: Option<(Vec<u8>, i64)> = tx
                .query_row(
                    "SELECT occurrence_bytes,created_commit_seq
                     FROM scientific_memory_occurrence_v1 WHERE occurrence_id=?1",
                    [occurrence_id.as_str()],
                    |row| Ok((row.get(0)?, row.get(1)?)),
                )
                .optional()?;
            if exact.as_ref().is_none_or(|(bytes, stored_seq)| {
                bytes.as_slice() != exact_occurrence_bytes || *stored_seq != seq
            }) {
                return Err(StoreError::IdentityConflict {
                    kind: "scientific-memory batch",
                    identity: context.batch_id.to_string(),
                });
            }
            drop(tx);
            let loaded = self
                .load_scientific_memory_occurrence_v1(&occurrence_id)?
                .ok_or_else(|| StoreError::IdentityConflict {
                    kind: "scientific-memory occurrence",
                    identity: occurrence_id.to_string(),
                })?;
            if loaded.occurrence_bytes != exact_occurrence_bytes
                || loaded.commit_seq.get() != as_u64(seq, "memory commit")?
            {
                return Err(StoreError::IdentityConflict {
                    kind: "scientific-memory occurrence",
                    identity: occurrence_id.to_string(),
                });
            }
            return Ok(memory_receipt(
                &occurrence_id,
                &loaded,
                IdempotencyStatus::Idempotent,
            ));
        }
        let metadata = Self::validate_memory_append(&tx, &parsed)?;
        let operation = digest_json(&(
            "joshi.store.scientific_memory_commit.v1",
            occurrence_id.as_str(),
            occurrence_digest.as_str(),
            metadata.scene_publication_id.as_str(),
        ))?;
        insert_commit(&tx, context, "command", &operation)?;
        let seq = tx.last_insert_rowid();
        let generation: i64 = tx.query_row(
            "SELECT COALESCE(MAX(queue_generation),0)+1 FROM scientific_memory_occurrence_v1",
            [],
            |row| row.get(0),
        )?;
        tx.execute(
            "INSERT INTO scientific_memory_occurrence_v1
             (occurrence_id,occurrence_kind,occurrence_sha256,occurrence_bytes,
              occurrence_byte_length,session_id,scene_publication_id,opening_act_id,
              closing_act_id,logical_start_tick,logical_end_tick,queue_generation,
              qualification,authority,created_commit_seq)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15)",
            params![
                occurrence_id.as_str(),
                metadata.kind,
                raw_digest(&occurrence_digest, "memory occurrence")?,
                exact_occurrence_bytes,
                sqlite_usize(exact_occurrence_bytes.len(), "memory bytes")?,
                metadata.session_id.as_str(),
                metadata.scene_publication_id.as_str(),
                metadata.opening_act_id.as_ref().map(StableString::as_str),
                metadata.closing_act_id.as_ref().map(StableString::as_str),
                metadata.start_tick.to_string(),
                metadata.end_tick.map(|v| v.to_string()),
                generation,
                MEMORY_QUALIFICATION,
                AUTHORITY,
                seq
            ],
        )?;
        tx.commit()?;
        Ok(ScientificMemoryCommitReceipt {
            occurrence_id,
            occurrence_digest,
            scene_publication_id: metadata.scene_publication_id,
            queue_generation: as_u64(generation, "memory queue generation")?,
            commit_seq: CommitSeq::new(as_u64(seq, "memory commit")?),
            status: IdempotencyStatus::Accepted,
        })
    }

    /// Loads and revalidates one exact memory occurrence and the complete prior prefix.
    pub fn load_scientific_memory_occurrence_v1(
        &self,
        occurrence_id: &StableString,
    ) -> Result<Option<StoredScientificMemoryOccurrence>> {
        type Row = (Vec<u8>, String, String, i64, i64);
        let row:Option<Row>=self.connection.query_row("SELECT occurrence_bytes,occurrence_sha256,scene_publication_id,queue_generation,created_commit_seq FROM scientific_memory_occurrence_v1 WHERE occurrence_id=?1",[occurrence_id.as_str()],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?))).optional()?;
        let Some((bytes, raw, scene, generation, seq)) = row else {
            return Ok(None);
        };
        let occurrence = parse_memory_occurrence_exact(&bytes).map_err(|error| {
            StoreError::InvalidBatch(format!("stored scientific-memory bytes: {error}"))
        })?;
        let digest = bytes_digest(&bytes)?;
        if occurrence.occurrence_id() != occurrence_id.as_str()
            || raw_digest(&digest, "memory occurrence")? != raw
        {
            return Err(StoreError::InvalidBatch(
                "stored scientific-memory occurrence is corrupt".into(),
            ));
        }
        Self::rebuild_memory_prefix(&self.connection, Some(occurrence_id))?;
        let scene_publication_id = CockpitPublicationId::new(scene)
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        Self::validate_memory_scene(&self.connection, &occurrence, &scene_publication_id)?;
        Ok(Some(StoredScientificMemoryOccurrence {
            occurrence,
            occurrence_bytes: bytes,
            occurrence_digest: digest,
            scene_publication_id,
            queue_generation: as_u64(generation, "memory queue generation")?,
            commit_seq: CommitSeq::new(as_u64(seq, "memory commit")?),
        }))
    }

    fn resolve_c0_source(&self, exact_receipt: &[u8]) -> Result<SourceCapability> {
        if exact_receipt.is_empty() || exact_receipt.len() > MAX_CONTROL_BYTES {
            return Err(StoreError::InvalidBatch(
                "C0 receipt is empty or oversized".into(),
            ));
        }
        let receipt_digest = bytes_digest(exact_receipt)?;
        type ReceiptRow = (String, String, Vec<u8>, i64, String);
        let row: Option<ReceiptRow> = self
            .connection
            .query_row(
                "SELECT b.catalog_admission_id,b.run_registration_id,s.receipt_bytes,
                    s.store_commit_seq,s.protection_class
             FROM spool_catalog_admission s JOIN wave5_spool_catalog_binding_v1 b
               ON b.segment_id=s.segment_id AND b.batch_id=s.batch_id
             WHERE s.receipt_sha256=?1",
                [raw_digest(&receipt_digest, "C0 receipt")?],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                    ))
                },
            )
            .optional()?;
        let Some((catalog_admission, run, stored_receipt, store_commit, protection)) = row else {
            return Err(StoreError::MissingIdentity {
                kind: "accepted public C0 receipt",
                identity: receipt_digest.to_string(),
            });
        };
        if stored_receipt != exact_receipt || protection != "public_integrity" {
            return Err(StoreError::InvalidBatch(
                "C0 receipt bytes/protection differ from retained public admission".into(),
            ));
        }
        validate_accepted_c0_receipt(
            exact_receipt,
            self.config.catalog_id.as_str(),
            &self.catalog_schema_id()?,
        )?;
        let store_commit = CommitSeq::new(as_u64(store_commit, "C0 store commit")?);
        let sources: Vec<String> = {
            let mut statement = self.connection.prepare(
                "SELECT DISTINCT source_id FROM observation WHERE commit_seq=?1 ORDER BY source_id",
            )?;
            statement
                .query_map([sqlite_u64(store_commit.get(), "C0 commit")?], |row| {
                    row.get(0)
                })?
                .collect::<std::result::Result<Vec<_>, _>>()?
        };
        if sources.len() != 1 {
            return Err(StoreError::InvalidBatch(
                "C0 source occurrence requires exactly one durable source".into(),
            ));
        }
        let resolution = StoredReceiptResolution {
            catalog_admission_id: stable(catalog_admission)?,
            run_registration_id: stable(run)?,
            receipt_digest,
            store_commit,
            source_id: stable(sources[0].clone())?,
        };
        build_source_capability(self, &resolution)
    }

    fn validate_memory_append(
        connection: &Connection,
        occurrence: &MemoryOccurrence,
    ) -> Result<MemoryMetadata> {
        Self::rebuild_memory_prefix(connection, None)?
            .append(occurrence.clone())
            .map_err(|error| {
                StoreError::InvalidBatch(format!("scientific-memory semantic refusal: {error}"))
            })?;
        match occurrence {
            MemoryOccurrence::OperatorAct(act) => {
                let scene = scene_from_binding(&act.scene)?;
                Self::validate_memory_scene(connection, occurrence, &scene)?;
                Ok(MemoryMetadata {
                    kind: "operator_act",
                    session_id: stable(act.session_id.as_str().to_owned())?,
                    scene_publication_id: scene,
                    opening_act_id: None,
                    closing_act_id: None,
                    start_tick: act.occurred_at.value(),
                    end_tick: None,
                })
            }
            MemoryOccurrence::Episode(episode) => {
                if episode.completeness == EpisodeCompleteness::Complete
                    || episode
                        .segments
                        .iter()
                        .any(|segment| matches!(segment.lot, LotAssociation::Resolved { .. }))
                {
                    return Err(StoreError::InvalidBatch(
                        "G0 scientific memory remains fixture-authority partial/unresolved".into(),
                    ));
                }
                let first = episode
                    .act_ids
                    .first()
                    .ok_or_else(|| StoreError::InvalidBatch("episode has no opening act".into()))?;
                let last = episode
                    .act_ids
                    .last()
                    .ok_or_else(|| StoreError::InvalidBatch("episode has no closing act".into()))?;
                let opening = stable(format!("act:{}", first.as_str()))?;
                let closing = stable(format!("act:{}", last.as_str()))?;
                let scene_raw:String=connection.query_row("SELECT scene_publication_id FROM scientific_memory_occurrence_v1 WHERE occurrence_id=?1",[opening.as_str()],|row|row.get(0)).optional()?.ok_or_else(||StoreError::MissingIdentity{kind:"episode opening act",identity:opening.to_string()})?;
                for act in &episode.act_ids {
                    let act_id = format!("act:{}", act.as_str());
                    let exact:bool=connection.query_row("SELECT EXISTS(SELECT 1 FROM scientific_memory_occurrence_v1 WHERE occurrence_id=?1 AND occurrence_kind='operator_act' AND session_id=?2 AND scene_publication_id=?3)",params![act_id,episode.session_id.as_str(),scene_raw],|row|row.get(0))?;
                    if !exact {
                        return Err(StoreError::InvalidBatch(
                            "episode act/session/scene closure differs".into(),
                        ));
                    }
                }
                let scene = CockpitPublicationId::new(scene_raw)
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
                Ok(MemoryMetadata {
                    kind: "episode",
                    session_id: stable(episode.session_id.as_str().to_owned())?,
                    scene_publication_id: scene,
                    opening_act_id: Some(opening),
                    closing_act_id: Some(closing),
                    start_tick: episode.started_at.value(),
                    end_tick: episode
                        .ended_at
                        .map(joshi_scientific_memory::LogicalSessionTick::value),
                })
            }
            _ => Err(StoreError::InvalidBatch(
                "G0 store admits only scientific-memory act/episode occurrences".into(),
            )),
        }
    }

    fn validate_memory_scene(
        connection: &Connection,
        occurrence: &MemoryOccurrence,
        expected: &CockpitPublicationId,
    ) -> Result<()> {
        type SceneRow = (Vec<u8>, String, String, i64, Vec<u8>, String);
        let row: SceneRow = connection
            .query_row(
                "SELECT publication.publication_bytes,publication.publication_sha256,
                        publication.publication_bytes_sha256,publication.created_commit_seq,
                        head.head_bytes,head.head_sha256
                 FROM cockpit_v2_publication_v1 publication
                 JOIN cockpit_v2_head_v1 head
                   ON head.publication_id=publication.publication_id
                  AND head.source_occurrence_id=publication.source_occurrence_id
                 WHERE publication.publication_id=?1",
                [expected.as_str()],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                    ))
                },
            )
            .map_err(|_| StoreError::MissingIdentity {
                kind: "headed Cockpit V2 scene",
                identity: expected.to_string(),
            })?;
        let body = parse_cockpit_v2_publication(&row.0).map_err(publication_error)?;
        let head = parse_cockpit_v2_head(&row.4).map_err(publication_error)?;
        head.validate_against(&body).map_err(publication_error)?;
        if &body.publication_id != expected
            || raw_digest(&body.publication_digest, "memory scene publication")? != row.1
            || raw_digest(&bytes_digest(&row.0)?, "memory scene publication bytes")? != row.2
            || raw_digest(&head.head_digest, "memory scene head")? != row.5
        {
            return Err(StoreError::InvalidBatch(
                "scientific-memory headed scene readback differs".into(),
            ));
        }
        if let MemoryOccurrence::OperatorAct(act) = occurrence {
            let SceneBinding::Committed(scene) = &act.scene else {
                return Err(StoreError::InvalidBatch(
                    "durable G0 act requires committed scene".into(),
                ));
            };
            if scene.scene_id.as_str() != expected.as_str()
                || scene.scene_digest.as_str() != body.publication_digest.as_str()
                || scene.catalog_cutoff.value() != as_u64(row.3, "memory scene commit")?
            {
                return Err(StoreError::InvalidBatch(
                    "scientific-memory scene differs from exact Cockpit publication".into(),
                ));
            }
            if let PresentationBinding::Occurrence(value) = &act.presentation
                && value.scene != *scene
            {
                return Err(StoreError::InvalidBatch(
                    "presentation occurrence changes exact scene".into(),
                ));
            }
        }
        Ok(())
    }

    fn rebuild_memory_prefix(
        connection: &Connection,
        through: Option<&StableString>,
    ) -> Result<MemoryKernel> {
        let mut statement=connection.prepare("SELECT occurrence_id,occurrence_bytes FROM scientific_memory_occurrence_v1 ORDER BY queue_generation")?;
        let rows = statement.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, Vec<u8>>(1)?))
        })?;
        let mut kernel = MemoryKernel::new();
        for row in rows {
            let (id, bytes) = row?;
            let occurrence = parse_memory_occurrence_exact(&bytes).map_err(|error| {
                StoreError::InvalidBatch(format!("stored memory prefix: {error}"))
            })?;
            kernel.append(occurrence).map_err(|error| {
                StoreError::InvalidBatch(format!("stored memory prefix: {error}"))
            })?;
            if through.is_some_and(|value| value.as_str() == id) {
                break;
            }
        }
        Ok(kernel)
    }
}

impl SqliteStore {
    /// Resolves the sole registered import and its external CAS paths, runs the pure V10 exporter,
    /// reopens the import closure, and only then commits the validated snapshot.
    pub fn commit_wave5_g0_operational_export_v2(
        &mut self,
        import_id: &StableString,
        backup_id: &StableString,
        mut request: OperationalExportRequestV2,
        validation_id: &StableString,
        context: &OperationalCommitContext,
    ) -> Result<ProductionExportCommitReceipt> {
        if request.catalog_schema.as_str() != "joshi.sqlite.v10"
            || request.g0_import_artifact.is_some()
        {
            return Err(StoreError::InvalidBatch(
                "G0 export requires V10 and a store-owned import readback".into(),
            ));
        }
        let backup = self.load_wave5_g0_backup_v1(backup_id)?.ok_or_else(|| {
            StoreError::MissingIdentity {
                kind: "G0 export backup",
                identity: backup_id.to_string(),
            }
        })?;
        let import = self
            .load_wave5_g0_import_occurrence_v1(import_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "G0 export import",
                identity: import_id.to_string(),
            })?;
        if backup.run_registration_id != import.run_registration_id
            || import.available_commit_seq > backup.source_max_commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "G0 export backup does not close the selected registered import".into(),
            ));
        }
        request
            .catalog_snapshot_path
            .clone_from(&backup.catalog_path);
        request.catalog_id = self.config.catalog_id.clone();
        request.catalog_schema = stable("joshi.sqlite.v10")?;
        request.from_commit_seq = CommitSeq::new(1);
        request.through_commit_seq = backup.source_max_commit_seq;
        request.created_at = context.committed_at();
        let before = self.resolve_wave5_g0_import_artifact_v1(import_id)?;
        let before_digest = g0_import_artifact_readback_digest(&before)?;
        request.g0_import_artifact = Some(before);
        let snapshot = export_operational_snapshot_v2(&request).map_err(|error| {
            StoreError::InvalidBatch(format!("Wave 5 G0 export refused: {error}"))
        })?;
        let after = self.resolve_wave5_g0_import_artifact_v1(import_id)?;
        let backup_after = self.load_wave5_g0_backup_v1(backup_id)?.ok_or_else(|| {
            StoreError::MissingIdentity {
                kind: "G0 export backup",
                identity: backup_id.to_string(),
            }
        })?;
        if g0_import_artifact_readback_digest(&after)? != before_digest
            || backup_after.catalog_digest != backup.catalog_digest
            || backup_after.artifact_inventory_digest != backup.artifact_inventory_digest
            || backup_after.source_max_commit_seq != backup.source_max_commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "G0 backup/import CAS closure changed across export".into(),
            ));
        }
        self.commit_production_export_snapshot_v2(validation_id, &snapshot, context)
    }

    /// Returns one exact neutral status occurrence after the typed V9 readback has revalidated it.
    pub fn load_wave5_g0_status_occurrence_v1(
        &self,
        record_id: &StableString,
    ) -> Result<Option<Wave5G0StatusOccurrence>> {
        let Some(stored) = self.load_wave5_operational_record_v1(record_id)? else {
            return Ok(None);
        };
        let bytes_digest = bytes_digest(&stored.exact_bytes)?;
        if bytes_digest != stored.exact_digest {
            return Err(StoreError::InvalidBatch(
                "status semantic/byte digest differs".into(),
            ));
        }
        Ok(Some(Wave5G0StatusOccurrence {
            record_id: stable(stored.record.record_id)?,
            run_registration_id: stable(stored.record.run_registration_id)?,
            record_digest: stored.exact_digest,
            record_bytes_digest: bytes_digest,
            record_byte_length: u64::try_from(stored.exact_bytes.len()).map_err(|_| {
                StoreError::IntegerRange {
                    field: "status bytes",
                    value: stored.exact_bytes.len().to_string(),
                }
            })?,
            predecessor_record_id: stored
                .record
                .predecessor_record_id
                .map(stable)
                .transpose()?,
            evidence_commit_seq: stored
                .record
                .evidence_commit_seq
                .map(|value| {
                    value.parse::<u64>().map(CommitSeq::new).map_err(|_| {
                        StoreError::InvalidBatch("status evidence commit is not canonical".into())
                    })
                })
                .transpose()?,
            available_commit_seq: stored.commit_seq,
        }))
    }

    /// Returns one exact neutral export binding and revalidates canonical bytes and truth closure.
    pub fn load_wave5_g0_export_occurrence_v1(
        &self,
        export_binding_id: &StableString,
    ) -> Result<Option<Wave5G0ExportOccurrence>> {
        type Row = (
            String,
            String,
            String,
            String,
            Vec<u8>,
            i64,
            String,
            i64,
            String,
        );
        let row: Option<Row> = self
            .connection
            .query_row(
                "SELECT b.run_registration_id,b.export_request_id,b.validation_id,b.snapshot_id,
                    b.binding_bytes,b.binding_byte_length,b.binding_sha256,b.created_commit_seq,
                    c.commit_digest
             FROM wave5_export_validation_binding_v1 b
             JOIN ingest_commit c ON c.commit_seq=b.created_commit_seq
             WHERE b.export_binding_id=?1",
                [export_binding_id.as_str()],
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
                        row.get(8)?,
                    ))
                },
            )
            .optional()?;
        let Some((run, request, validation, snapshot, bytes, length, raw, seq, commit_digest)) =
            row
        else {
            return Ok(None);
        };
        let binding: crate::Wave5ExportValidationBindingV1 = serde_json::from_slice(&bytes)?;
        if serde_json::to_vec(&binding)? != bytes
            || binding.export_binding_id != export_binding_id.as_str()
            || binding.run_registration_id != run
            || binding.export_request_id != request
            || binding.validation_id != validation
            || binding.snapshot_id != snapshot
        {
            return Err(StoreError::InvalidBatch(
                "export binding readback differs".into(),
            ));
        }
        let digest = bytes_digest(&bytes)?;
        if raw_digest(&digest, "export binding")? != raw
            || usize_i64(bytes.len(), "export binding bytes")? != length
        {
            return Err(StoreError::InvalidBatch(
                "export binding digest/length differs".into(),
            ));
        }
        let truth_raw: String = self.connection.query_row(
            "SELECT truth_fingerprint_sha256 FROM production_export_request_v2
             WHERE export_request_id=?1 AND validation_id=?2 AND snapshot_id=?3",
            params![&request, &validation, &snapshot],
            |row| row.get(0),
        )?;
        if binding.truth_fingerprint != format!("sha256:{truth_raw}") {
            return Err(StoreError::InvalidBatch(
                "export truth fingerprint differs".into(),
            ));
        }
        Ok(Some(Wave5G0ExportOccurrence {
            export_binding_id: export_binding_id.clone(),
            run_registration_id: stable(run)?,
            export_request_id: stable(request)?,
            validation_id: stable(validation)?,
            snapshot_id: ValueDigest::new(snapshot)
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            binding_digest: digest.clone(),
            binding_bytes_digest: digest,
            binding_byte_length: as_u64(length, "export binding bytes")?,
            truth_fingerprint_digest: qualified_raw_digest(&truth_raw, "truth fingerprint")?,
            available_commit_seq: CommitSeq::new(as_u64(seq, "export binding commit")?),
            available_commit_digest: qualified_raw_digest(&commit_digest, "export binding commit")?,
        }))
    }

    /// Returns one neutral restricted import only after registration, manifest and CAS readback.
    pub fn load_wave5_g0_import_occurrence_v1(
        &self,
        import_id: &StableString,
    ) -> Result<Option<Wave5G0ImportOccurrence>> {
        let Some(stored) = self.load_wave5_restricted_artifact_v1(import_id)? else {
            return Ok(None);
        };
        let registration_bytes_digest = bytes_digest(&stored.registration_bytes)?;
        if registration_bytes_digest != stored.registration_digest
            || bytes_digest(&stored.artifact_bytes)? != stored.artifact_digest
        {
            return Err(StoreError::InvalidBatch(
                "restricted import readback digest differs".into(),
            ));
        }
        Ok(Some(Wave5G0ImportOccurrence {
            import_id: import_id.clone(),
            run_registration_id: stable(stored.registration.run_registration_id)?,
            export_binding_id: stable(stored.registration.export_binding_id)?,
            export_request_id: stable(stored.registration.export_request_id)?,
            analysis_run_id: stable(stored.registration.analysis_run_id)?,
            artifact_id: ValueDigest::new(stored.registration.artifact_id)
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            manifest_digest: ValueDigest::new(stored.registration.manifest_digest)
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            snapshot_id: ValueDigest::new(stored.registration.snapshot_id)
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            registration_digest: stored.registration_digest,
            registration_bytes_digest,
            registration_byte_length: u64::try_from(stored.registration_bytes.len()).map_err(
                |_| StoreError::IntegerRange {
                    field: "import registration bytes",
                    value: stored.registration_bytes.len().to_string(),
                },
            )?,
            cas_physical_digest: stored.artifact_digest,
            cas_byte_length: u64::try_from(stored.artifact_bytes.len()).map_err(|_| {
                StoreError::IntegerRange {
                    field: "import CAS bytes",
                    value: stored.artifact_bytes.len().to_string(),
                }
            })?,
            available_commit_seq: stored.commit_seq,
        }))
    }

    /// Loads one explicitly selected, connected G0 closure; no component is chosen as "latest".
    pub fn load_wave5_g0_occurrence_ports_v1(
        &self,
        source_occurrence_id: &StableString,
        publication_id: &CockpitPublicationId,
        memory_occurrence_ids: &[StableString],
        status_record_ids: &[StableString],
        export_binding_id: Option<&StableString>,
        import_id: Option<&StableString>,
    ) -> Result<Wave5G0OccurrencePorts> {
        if memory_occurrence_ids
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
            || status_record_ids.windows(2).any(|pair| pair[0] >= pair[1])
        {
            return Err(StoreError::InvalidBatch(
                "G0 selected occurrence IDs must be strictly sorted and unique".into(),
            ));
        }
        let source = self
            .load_wave5_source_occurrence_v1(source_occurrence_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "G0 source occurrence",
                identity: source_occurrence_id.to_string(),
            })?;
        let publication = self
            .load_cockpit_v2_publication_v1(publication_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "G0 Cockpit V2 publication",
                identity: publication_id.to_string(),
            })?;
        let head = self
            .load_cockpit_v2_head_v1(publication_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "G0 Cockpit V2 head",
                identity: publication_id.to_string(),
            })?;
        if publication.source_occurrence_id != *source_occurrence_id
            || head.source_occurrence_id != *source_occurrence_id
        {
            return Err(StoreError::InvalidBatch(
                "G0 publication/head do not close the selected source occurrence".into(),
            ));
        }
        let run_registration_id = source.occurrence.run_registration_id.clone();
        let mut memory = Vec::with_capacity(memory_occurrence_ids.len());
        for id in memory_occurrence_ids {
            let value = self
                .load_scientific_memory_occurrence_v1(id)?
                .ok_or_else(|| StoreError::MissingIdentity {
                    kind: "G0 scientific-memory occurrence",
                    identity: id.to_string(),
                })?;
            if value.scene_publication_id != *publication_id {
                return Err(StoreError::InvalidBatch(
                    "G0 memory occurrence is outside the selected headed publication".into(),
                ));
            }
            memory.push(value);
        }
        let mut status = Vec::with_capacity(status_record_ids.len());
        for id in status_record_ids {
            let value = self
                .load_wave5_g0_status_occurrence_v1(id)?
                .ok_or_else(|| StoreError::MissingIdentity {
                    kind: "G0 status occurrence",
                    identity: id.to_string(),
                })?;
            if value.run_registration_id != run_registration_id {
                return Err(StoreError::InvalidBatch(
                    "G0 status occurrence is outside the selected run".into(),
                ));
            }
            status.push(value);
        }
        let export = export_binding_id
            .map(|id| {
                self.load_wave5_g0_export_occurrence_v1(id)?.ok_or_else(|| {
                    StoreError::MissingIdentity {
                        kind: "G0 export occurrence",
                        identity: id.to_string(),
                    }
                })
            })
            .transpose()?;
        if export
            .as_ref()
            .is_some_and(|value| value.run_registration_id != run_registration_id)
        {
            return Err(StoreError::InvalidBatch(
                "G0 export occurrence is outside the selected run".into(),
            ));
        }
        let import = import_id
            .map(|id| {
                self.load_wave5_g0_import_occurrence_v1(id)?.ok_or_else(|| {
                    StoreError::MissingIdentity {
                        kind: "G0 import occurrence",
                        identity: id.to_string(),
                    }
                })
            })
            .transpose()?;
        if import.as_ref().is_some_and(|value| {
            value.run_registration_id != run_registration_id
                || export
                    .as_ref()
                    .is_none_or(|selected| selected.export_binding_id != value.export_binding_id)
        }) {
            return Err(StoreError::InvalidBatch(
                "G0 import occurrence is outside the selected run/export closure".into(),
            ));
        }
        Ok(Wave5G0OccurrencePorts {
            run_registration_id,
            source,
            publication,
            head,
            memory,
            status,
            export,
            import,
        })
    }
}

#[derive(Clone, Debug)]
struct MemoryMetadata {
    kind: &'static str,
    session_id: StableString,
    scene_publication_id: CockpitPublicationId,
    opening_act_id: Option<StableString>,
    closing_act_id: Option<StableString>,
    start_tick: u64,
    end_tick: Option<u64>,
}

fn build_source_capability(
    store: &SqliteStore,
    resolution: &StoredReceiptResolution,
) -> Result<SourceCapability> {
    let mut statement = store.connection.prepare(
        "SELECT o.observation_id,c.source_variant,o.received_wall_us,o.available_wall_us,
                b.storage_mode,b.inline_bytes,b.relative_path,b.stored_sha256,b.stored_length
         FROM observation o JOIN observation_contract c USING(observation_id)
         JOIN observation_blob_contract r USING(observation_id)
         JOIN blob_object b ON b.blob_id=r.blob_id AND b.storage_domain=r.storage_domain
         WHERE o.commit_seq=?1 AND o.source_id=?2 AND c.source_variant='provider_body'
           AND o.parse_disposition='decoded'
           AND c.parse_disposition_recognition='known'
           AND c.source_variant_recognition='known'
           AND r.content_type='application/json'
           AND r.retention_class IN ('public_chain','public_source','fixture')
         ORDER BY o.observation_id",
    )?;
    let rows = statement.query_map(
        params![
            sqlite_u64(resolution.store_commit.get(), "C0 commit")?,
            resolution.source_id.as_str()
        ],
        |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, i64>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, Option<Vec<u8>>>(5)?,
                row.get::<_, Option<String>>(6)?,
                row.get::<_, String>(7)?,
                row.get::<_, i64>(8)?,
            ))
        },
    )?;
    let mut facts = Vec::new();
    let mut eligible = BTreeMap::<StableString, Vec<StableString>>::new();
    let surface = stable(SOURCE_SURFACE_ID)?;
    let field = stable(SOURCE_FIELD_ID)?;
    let mut maximum = None;
    for row in rows {
        let (
            observation,
            _variant,
            received,
            available,
            mode,
            inline,
            path,
            stored_sha,
            stored_len,
        ) = row?;
        let payload = read_blob(
            store,
            &mode,
            inline,
            path.as_deref(),
            &stored_sha,
            as_u64(stored_len, "source blob length")?,
        )?;
        let value: Value = serde_json::from_slice(&payload)?;
        let items = value.as_array().ok_or_else(|| {
            StoreError::InvalidBatch("public C0 provider body is not an array".into())
        })?;
        let observed = timestamp_from_us(received, "source observed_at")?;
        let known = timestamp_from_us(available, "source known_at")?;
        maximum = Some(maximum.map_or(known, |prior: UtcTimestamp| prior.max(known)));
        for item in items {
            let mint = item
                .as_object()
                .and_then(|object| object.get("mint"))
                .and_then(Value::as_str)
                .ok_or_else(|| {
                    StoreError::InvalidBatch(
                        "public C0 discovery row lacks exact mint string".into(),
                    )
                })?;
            let subject = stable(mint.to_owned())?;
            let digest = digest_json(&(
                "joshi.store.wave5.source_fact.v1",
                &observation,
                mint,
                resolution.store_commit.get(),
            ))?;
            let fact_id = stable(format!(
                "fact:{observation}:{}",
                raw_digest(&digest, "source fact")?
            ))?;
            eligible
                .entry(subject.clone())
                .or_default()
                .push(fact_id.clone());
            facts.push(CockpitV2SourceFactRefV1 {
                fact_id,
                fact_digest: digest,
                surface_id: surface.clone(),
                source_id: resolution.source_id.clone(),
                subject,
                field: field.clone(),
                protection: ProtectionDomain::Public,
                observed_at: observed,
                known_at: known,
                commit_seq: Some(resolution.store_commit),
            });
        }
    }
    facts.sort_by(|left, right| left.fact_id.cmp(&right.fact_id));
    let eligible_subjects = eligible.keys().cloned().collect::<Vec<_>>();
    if eligible_subjects.len() < 2 || facts.is_empty() {
        return Err(StoreError::InvalidBatch(
            "G0 public C0 source requires at least two exact eligible subjects".into(),
        ));
    }
    let semantic = resolve_source_semantic_closure(store, resolution, &eligible, &surface, &field)?;
    maximum = Some(
        maximum.map_or(semantic.maximum_available_at, |prior: UtcTimestamp| {
            prior.max(semantic.maximum_available_at)
        }),
    );
    let profile_raw: String = store.connection.query_row(
        "SELECT daily_surface_profile_sha256 FROM wave5_run_registration_v1
         WHERE run_registration_id=?1 AND created_commit_seq < ?2",
        params![
            resolution.run_registration_id.as_str(),
            sqlite_u64(resolution.store_commit.get(), "C0 commit")?
        ],
        |row| row.get(0),
    )?;
    let surface_profile = CockpitV2SurfaceProfileRefV1 {
        profile_id: stable(format!(
            "daily-surface:{}",
            resolution.run_registration_id.as_str()
        ))?,
        profile_digest: qualified_raw_digest(&profile_raw, "daily surface profile")?,
        field_cells: vec![CockpitV2SurfaceFieldRefV1 {
            surface_id: surface,
            source_id: resolution.source_id.clone(),
            field,
        }],
    };
    let maximum = maximum.ok_or_else(|| {
        StoreError::InvalidBatch("public C0 source has no availability clock".into())
    })?;
    let occurrence_id = stable(format!(
        "source-c0:{}",
        raw_digest(&resolution.receipt_digest, "C0 receipt")?
    ))?;
    let document = Wave5SourceOccurrenceV1 {
        contract: stable(SOURCE_DESCRIPTOR_CONTRACT)?,
        schema_version: 1,
        source_occurrence_id: occurrence_id,
        run_registration_id: resolution.run_registration_id.clone(),
        catalog_admission_id: resolution.catalog_admission_id.clone(),
        source_receipt_digest: resolution.receipt_digest.clone(),
        source_id: resolution.source_id.clone(),
        surface_profile,
        facts,
        eligible_subjects,
        memberships: semantic.memberships,
        coverage: semantic.coverage,
        gaps: semantic.gaps,
        rendered_subjects: semantic.rendered_subjects,
        omissions: semantic.omissions,
        known_through_commit_seq: resolution.store_commit,
        maximum_input_available_at: maximum,
        protection: ProtectionDomain::Public,
        authority: ProjectionAuthority::ReadOnlyNoExecution,
    };
    let bytes = serde_json::to_vec(&document)?;
    let parsed: Wave5SourceOccurrenceV1 = serde_json::from_slice(&bytes)?;
    if parsed != document {
        return Err(StoreError::InvalidBatch(
            "source descriptor canonical roundtrip failed".into(),
        ));
    }
    let digest = bytes_digest(&bytes)?;
    Ok(SourceCapability {
        document,
        bytes,
        digest,
    })
}

struct SourceSemanticClosure {
    memberships: Vec<CockpitV2MembershipRefV1>,
    coverage: Vec<CockpitV2CoverageRefV1>,
    gaps: Vec<CockpitV2GapRefV1>,
    rendered_subjects: Vec<StableString>,
    omissions: Vec<CockpitV2OmissionV1>,
    maximum_available_at: UtcTimestamp,
}

fn resolve_source_semantic_closure(
    store: &SqliteStore,
    resolution: &StoredReceiptResolution,
    facts: &BTreeMap<StableString, Vec<StableString>>,
    surface: &StableString,
    field: &StableString,
) -> Result<SourceSemanticClosure> {
    type WindowRow = (
        String,
        String,
        String,
        String,
        i64,
        Option<String>,
        String,
        Option<String>,
        String,
        String,
        i64,
    );
    let cut = sqlite_u64(resolution.store_commit.get(), "C0 commit")?;
    let mut statement = store.connection.prepare(
        "SELECT w.coverage_id,w.scope_kind,w.scope_key,w.coverage_level,w.opened_wall_us,
                c.scope_subject,c.lower_boundary_json,c.upper_boundary_json,c.state,
                c.state_recognition,c.available_wall_us
         FROM coverage_window w JOIN coverage_window_contract c USING(coverage_id)
         WHERE w.opened_commit_seq=?1 AND w.source_id=?2
           AND c.scope_family_recognition='known' AND c.state_recognition='known'
         ORDER BY w.coverage_id",
    )?;
    let rows = statement
        .query_map(params![cut, resolution.source_id.as_str()], |row| {
            Ok((
                row.get(0)?,
                row.get(1)?,
                row.get(2)?,
                row.get(3)?,
                row.get(4)?,
                row.get(5)?,
                row.get(6)?,
                row.get(7)?,
                row.get(8)?,
                row.get(9)?,
                row.get(10)?,
            ))
        })?
        .collect::<std::result::Result<Vec<WindowRow>, _>>()?;
    let mut memberships = Vec::with_capacity(facts.len());
    let mut coverage = Vec::with_capacity(facts.len());
    let mut gaps = Vec::new();
    let mut rendered_subjects = Vec::new();
    let mut omissions = Vec::new();
    let mut hot_count = 0_usize;
    let mut cold_count = 0_usize;
    let mut maximum: Option<UtcTimestamp> = None;
    for (subject, fact_ids) in facts {
        let unknown_windows: i64 = store.connection.query_row(
            "SELECT COUNT(*) FROM coverage_window w
             JOIN coverage_window_contract c USING(coverage_id)
             WHERE w.opened_commit_seq=?1 AND w.source_id=?2
               AND w.scope_key=?3 AND c.scope_subject=?3
               AND (c.scope_family_recognition<>'known' OR c.state_recognition<>'known')",
            params![cut, resolution.source_id.as_str(), subject.as_str()],
            |row| row.get(0),
        )?;
        if unknown_windows != 0 {
            return Err(StoreError::InvalidBatch(
                "unknown coverage semantics cannot qualify a source cell".into(),
            ));
        }
        let matched = rows
            .iter()
            .filter(|row| {
                row.2 == subject.as_str()
                    && row.5.as_deref() == Some(subject.as_str())
                    && matches!(
                        (row.1.as_str(), row.3.as_str()),
                        ("hot_lane" | "hot", "hot") | ("market_census" | "census", "census")
                    )
            })
            .collect::<Vec<_>>();
        if matched.len() != 1 {
            return Err(StoreError::InvalidBatch(format!(
                "subject {subject} requires exactly one exact hot/control coverage selection"
            )));
        }
        let window = matched[0];
        let membership = match (window.1.as_str(), window.3.as_str()) {
            ("hot_lane" | "hot", "hot") => {
                hot_count += 1;
                rendered_subjects.push(subject.clone());
                CockpitV2MembershipKind::Hot
            }
            ("market_census" | "census", "census") => {
                cold_count += 1;
                omissions.push(CockpitV2OmissionV1 {
                    subject: subject.clone(),
                    reason: stable("cold_control_not_rendered")?,
                    membership: CockpitV2MembershipKind::ColdControl,
                });
                CockpitV2MembershipKind::ColdControl
            }
            _ => unreachable!("filtered exact role"),
        };
        let available = timestamp_from_us(window.10, "coverage available_at")?;
        maximum = Some(maximum.map_or(available, |prior| prior.max(available)));
        let evidence_digest = digest_json(&(
            "joshi.store.wave5.membership_window.v1",
            &window.0,
            &window.1,
            &window.2,
            &window.3,
            window.4,
            &window.5,
            &window.6,
            &window.7,
            &window.8,
            &window.9,
            window.10,
        ))?;
        memberships.push(CockpitV2MembershipRefV1 {
            subject: subject.clone(),
            membership,
            observed_at: available,
            evidence_digest,
        });
        type GapRow = (
            String,
            i64,
            String,
            Option<i64>,
            String,
            Option<String>,
            String,
            i64,
        );
        let mut gap_statement = store.connection.prepare(
            "SELECT g.gap_id,g.detected_wall_us,g.cause_code,g.event_upper_us,
                    c.lower_boundary_json,c.upper_boundary_json,c.reason_recognition,
                    g.detected_commit_seq
             FROM coverage_gap g JOIN coverage_gap_contract c USING(gap_id)
             WHERE g.coverage_id=?1 AND g.detected_commit_seq<=?2
               AND c.scope_source_id=?3 AND c.scope_subject=?4
               AND c.scope_family_recognition='known' AND c.reason_recognition='known'
             ORDER BY g.gap_id",
        )?;
        let unknown_gaps: i64 = store.connection.query_row(
            "SELECT COUNT(*) FROM coverage_gap g JOIN coverage_gap_contract c USING(gap_id)
             WHERE g.coverage_id=?1 AND g.detected_commit_seq<=?2
               AND (c.scope_family_recognition<>'known' OR c.reason_recognition<>'known')",
            params![&window.0, cut],
            |row| row.get(0),
        )?;
        if unknown_gaps != 0 {
            return Err(StoreError::InvalidBatch(
                "unknown gap semantics cannot qualify a source cell".into(),
            ));
        }
        let gap_rows = gap_statement
            .query_map(
                params![
                    &window.0,
                    cut,
                    resolution.source_id.as_str(),
                    subject.as_str()
                ],
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
            )?
            .collect::<std::result::Result<Vec<GapRow>, _>>()?;
        if window.8 == "complete" && !gap_rows.is_empty() {
            return Err(StoreError::InvalidBatch(
                "complete coverage contradicts an exact retained gap".into(),
            ));
        }
        for gap in &gap_rows {
            let since = timestamp_from_us(gap.1, "coverage gap detected_at")?;
            maximum = Some(maximum.map_or(since, |prior| prior.max(since)));
            let gap_digest = digest_json(&(
                "joshi.store.wave5.coverage_gap.v1",
                &window.0,
                &gap.0,
                gap.1,
                &gap.2,
                gap.3,
                &gap.4,
                &gap.5,
                &gap.6,
                gap.7,
            ))?;
            gaps.push(CockpitV2GapRefV1 {
                gap_id: stable(gap.0.clone())?,
                surface_id: surface.clone(),
                source_id: resolution.source_id.clone(),
                subject: subject.clone(),
                field: field.clone(),
                reason: stable(gap.2.clone())?,
                since,
                until: gap
                    .3
                    .map(|value| timestamp_from_us(value, "coverage gap until"))
                    .transpose()?,
                evidence_digest: Some(gap_digest),
            });
        }
        let state = match window.8.as_str() {
            "complete" => CockpitV2CoverageState::Complete,
            "partial" | "degraded" => CockpitV2CoverageState::Partial,
            "stale" => CockpitV2CoverageState::Stale,
            "unknown" => CockpitV2CoverageState::Unknown,
            "unavailable" => CockpitV2CoverageState::Unavailable,
            "refused" => CockpitV2CoverageState::Refused,
            other => {
                return Err(StoreError::InvalidBatch(format!(
                    "coverage state {other} has no Cockpit V2 meaning"
                )));
            }
        };
        let coverage_digest = digest_json(&(
            "joshi.store.wave5.coverage_cell.v1",
            &window.0,
            &window.1,
            &window.2,
            &window.6,
            &window.7,
            &window.8,
            &window.9,
            fact_ids
                .iter()
                .map(StableString::as_str)
                .collect::<Vec<_>>(),
            gap_rows
                .iter()
                .map(|row| row.0.as_str())
                .collect::<Vec<_>>(),
        ))?;
        coverage.push(CockpitV2CoverageRefV1 {
            surface_id: surface.clone(),
            source_id: resolution.source_id.clone(),
            subject: subject.clone(),
            field: field.clone(),
            fact_ids: fact_ids.clone(),
            state,
            coverage_digest,
        });
    }
    if hot_count == 0 || cold_count == 0 {
        return Err(StoreError::InvalidBatch(
            "G0 publication requires independent nonempty hot and cold-control selections".into(),
        ));
    }
    memberships.sort_by(|left, right| left.subject.cmp(&right.subject));
    coverage.sort_by(|left, right| {
        (
            &left.surface_id,
            &left.source_id,
            &left.subject,
            &left.field,
        )
            .cmp(&(
                &right.surface_id,
                &right.source_id,
                &right.subject,
                &right.field,
            ))
    });
    gaps.sort_by(|left, right| left.gap_id.cmp(&right.gap_id));
    rendered_subjects.sort();
    omissions.sort();
    Ok(SourceSemanticClosure {
        memberships,
        coverage,
        gaps,
        rendered_subjects,
        omissions,
        maximum_available_at: maximum.ok_or_else(|| {
            StoreError::InvalidBatch("source closure has no coverage availability clock".into())
        })?,
    })
}

fn resolved_publication_input(
    source: &Wave5SourceOccurrenceV1,
) -> Result<CockpitV2ResolvedSourceFactsInputV1> {
    if source.contract.as_str() != SOURCE_DESCRIPTOR_CONTRACT
        || source.protection != ProtectionDomain::Public
        || source.eligible_subjects.len() < 2
    {
        return Err(StoreError::InvalidBatch(
            "source occurrence cannot form G0 publication input".into(),
        ));
    }
    let mut observed_universe = CockpitV2ObservedUniverseRefV1 {
        universe_id: stable(format!("universe:{}", source.source_occurrence_id.as_str()))?,
        universe_digest: ValueDigest::new(format!("sha256:{}", "0".repeat(64)))
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
        eligible_count: WireU64::new(u64::try_from(source.eligible_subjects.len()).map_err(
            |_| StoreError::IntegerRange {
                field: "eligible subjects",
                value: source.eligible_subjects.len().to_string(),
            },
        )?),
        eligible_subjects: source.eligible_subjects.clone(),
    };
    observed_universe.universe_digest = observed_universe
        .computed_digest()
        .map_err(publication_error)?;
    let input = CockpitV2ResolvedSourceFactsInputV1 {
        contract: stable(joshi_publication::COCKPIT_V2_RESOLVED_SOURCE_FACTS_INPUT_CONTRACT)?,
        schema_version: joshi_publication::COCKPIT_V2_SCHEMA_VERSION,
        surface_profile: source.surface_profile.clone(),
        observed_universe,
        cutoff: CockpitV2CutoffV1 {
            knowledge_at: source.maximum_input_available_at,
            commit_through: Some(source.known_through_commit_seq),
            chain_slot: None,
        },
        source_facts: source.facts.clone(),
        memberships: source.memberships.clone(),
        coverage: source.coverage.clone(),
        gaps: source.gaps.clone(),
        rendered_subjects: source.rendered_subjects.clone(),
        omissions: source.omissions.clone(),
        ordering_policy: stable("store_resolved_membership_then_subject")?,
        pagination_policy: stable("store_resolved_complete_partition")?,
        authority: ProjectionAuthority::ReadOnlyNoExecution,
        ceiling: joshi_publication::CockpitV2Ceiling::UnverifiedSemantic,
    };
    input.clone().into_manifest().map_err(publication_error)?;
    Ok(input)
}

fn validate_accepted_c0_receipt(
    bytes: &[u8],
    catalog_id: &str,
    catalog_schema: &StableString,
) -> Result<()> {
    let value: Value = serde_json::from_slice(bytes)?;
    let object = value
        .as_object()
        .ok_or_else(|| StoreError::InvalidBatch("C0 receipt is not an object".into()))?;
    let nested = object
        .get("catalogReceipt")
        .and_then(Value::as_object)
        .ok_or_else(|| StoreError::InvalidBatch("C0 receipt lacks catalogReceipt".into()))?;
    let accepted = object.get("contract").and_then(Value::as_str)
        == Some("joshi.spool.catalog_admission_receipt")
        && object.get("status").and_then(Value::as_str) == Some("accepted")
        && object.get("authority").and_then(Value::as_str) == Some(AUTHORITY)
        && object.get("protectionClass").and_then(Value::as_str) == Some("public_integrity")
        && nested.get("contract").and_then(Value::as_str) == Some("joshi.store.ingest_receipt")
        && nested.get("status").and_then(Value::as_str) == Some("accepted")
        && nested.get("catalogId").and_then(Value::as_str) == Some(catalog_id)
        && nested.get("catalogSchema").and_then(Value::as_str) == Some(catalog_schema.as_str());
    if !accepted {
        return Err(StoreError::InvalidBatch(
            "receipt is not the exact accepted public C0 closure for this catalog".into(),
        ));
    }
    Ok(())
}

fn read_blob(
    store: &SqliteStore,
    mode: &str,
    inline: Option<Vec<u8>>,
    path: Option<&str>,
    raw: &str,
    length: u64,
) -> Result<Vec<u8>> {
    let bytes = match (mode, inline, path) {
        ("inline", Some(bytes), None) => bytes,
        ("external", None, Some(path)) => fs::read(store.config.blob_root.join(path))
            .map_err(|source| StoreError::io(store.config.blob_root.join(path), source))?,
        _ => {
            return Err(StoreError::InvalidBatch(
                "source blob placement is invalid".into(),
            ));
        }
    };
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) != length
        || format!("{:x}", Sha256::digest(&bytes)) != raw
    {
        return Err(StoreError::InvalidBatch(
            "source blob readback digest/length mismatch".into(),
        ));
    }
    Ok(bytes)
}

fn scene_from_binding(binding: &SceneBinding) -> Result<CockpitPublicationId> {
    match binding {
        SceneBinding::Committed(scene) => {
            CockpitPublicationId::new(scene.scene_id.as_str().to_owned())
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))
        }
        SceneBinding::Missing { .. } => Err(StoreError::InvalidBatch(
            "durable G0 memory requires an exact scene".into(),
        )),
    }
}

fn cockpit_receipt(
    value: &StoredCockpitV2Publication,
    status: IdempotencyStatus,
) -> CockpitV2CommitReceipt {
    CockpitV2CommitReceipt {
        publication_id: value.publication.publication_id.clone(),
        publication_digest: value.publication.publication_digest.clone(),
        publication_bytes_digest: value.publication_bytes_digest.clone(),
        commit_seq: value.commit_seq,
        status,
    }
}
fn memory_receipt(
    id: &StableString,
    value: &StoredScientificMemoryOccurrence,
    status: IdempotencyStatus,
) -> ScientificMemoryCommitReceipt {
    ScientificMemoryCommitReceipt {
        occurrence_id: id.clone(),
        occurrence_digest: value.occurrence_digest.clone(),
        scene_publication_id: value.scene_publication_id.clone(),
        queue_generation: value.queue_generation,
        commit_seq: value.commit_seq,
        status,
    }
}

fn insert_commit(
    tx: &Transaction<'_>,
    context: &Wave5CommitContext,
    class: &str,
    digest: &ValueDigest,
) -> Result<()> {
    let committed = timestamp_us(context.committed_at, "G0 commit time")?;
    let latest: Option<i64> = tx
        .query_row(
            "SELECT committed_wall_us FROM ingest_commit ORDER BY commit_seq DESC LIMIT 1",
            [],
            |row| row.get(0),
        )
        .optional()?;
    if latest.is_some_and(|prior| committed < prior) {
        return Err(StoreError::InvalidBatch("G0 store clock regressed".into()));
    }
    let prior: Option<String> = tx
        .query_row(
            "SELECT commit_digest FROM ingest_commit ORDER BY commit_seq DESC LIMIT 1",
            [],
            |row| row.get(0),
        )
        .optional()?;
    tx.execute("INSERT INTO ingest_commit (commit_id,commit_class,committed_wall_us,writer_clock_id,committed_mono_ns,writer_build,prior_commit_digest,commit_digest) VALUES (?1,?2,?3,?4,?5,?6,?7,?8)",params![context.batch_id.as_str(),class,committed,context.writer_clock_id.as_str(),context.committed_mono_ns.to_string(),context.writer_build.as_str(),prior,raw_digest(digest,"G0 operation")?])?;
    Ok(())
}
fn existing_commit(connection: &rusqlite::Connection, id: &str) -> Result<Option<(i64, String)>> {
    connection
        .query_row(
            "SELECT commit_seq,commit_digest FROM ingest_commit WHERE commit_id=?1",
            [id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()
        .map_err(StoreError::from)
}
fn digest_json(value: &impl Serialize) -> Result<ValueDigest> {
    bytes_digest(&serde_json::to_vec(value)?)
}
fn g0_import_artifact_readback_digest(value: &G0ImportArtifactReadbackV1) -> Result<ValueDigest> {
    digest_json(&(
        value.import_id.as_str(),
        value.artifact_id.as_str(),
        value.manifest_path.to_string_lossy(),
        value
            .parts
            .iter()
            .map(|part| {
                (
                    part.path.to_string_lossy(),
                    part.relative_path.as_str(),
                    part.schema_id.as_str(),
                    part.schema_digest.as_str(),
                    part.physical_digest.as_str(),
                    part.logical_digest.as_str(),
                    part.primary_key
                        .iter()
                        .map(StableString::as_str)
                        .collect::<Vec<_>>(),
                    part.byte_length,
                    part.row_count,
                )
            })
            .collect::<Vec<_>>(),
    ))
}
fn bytes_digest(bytes: &[u8]) -> Result<ValueDigest> {
    ValueDigest::new(format!("sha256:{:x}", Sha256::digest(bytes)))
        .map_err(|error| StoreError::InvalidBatch(error.to_string()))
}
fn qualified_raw_digest(value: &str, kind: &'static str) -> Result<ValueDigest> {
    ValueDigest::new(format!("sha256:{value}")).map_err(|_| StoreError::InvalidDigest {
        kind,
        value: value.to_owned(),
    })
}
fn raw_digest<'a>(value: &'a ValueDigest, kind: &'static str) -> Result<&'a str> {
    let Some(raw) = value.as_str().strip_prefix("sha256:") else {
        return Err(StoreError::InvalidDigest {
            kind,
            value: value.to_string(),
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
            value: value.to_string(),
        })
    }
}
fn stable(value: impl Into<String>) -> Result<StableString> {
    StableString::new(value).map_err(|error| StoreError::InvalidBatch(error.to_string()))
}
fn publication_error(error: impl std::fmt::Display) -> StoreError {
    StoreError::InvalidBatch(format!("Cockpit V2 contract: {error}"))
}
fn sqlite_u64(value: u64, field: &'static str) -> Result<i64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}
fn sqlite_usize(value: usize, field: &'static str) -> Result<i64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}
fn usize_i64(value: usize, field: &'static str) -> Result<i64> {
    sqlite_usize(value, field)
}
fn as_u64(value: i64, field: &'static str) -> Result<u64> {
    value.try_into().map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}
fn timestamp_us(value: UtcTimestamp, field: &'static str) -> Result<i64> {
    let nanos = value.as_datetime().unix_timestamp_nanos();
    if nanos % 1_000 != 0 {
        return Err(StoreError::TimestampRange { field });
    }
    let micros = nanos / 1_000;
    if micros <= 0 {
        return Err(StoreError::TimestampRange { field });
    }
    micros
        .try_into()
        .map_err(|_| StoreError::TimestampRange { field })
}
fn timestamp_from_us(value: i64, field: &'static str) -> Result<UtcTimestamp> {
    let nanos = i128::from(value)
        .checked_mul(1_000)
        .ok_or(StoreError::TimestampRange { field })?;
    let datetime = time::OffsetDateTime::from_unix_timestamp_nanos(nanos)
        .map_err(|_| StoreError::TimestampRange { field })?;
    UtcTimestamp::new(datetime).map_err(|_| StoreError::TimestampRange { field })
}

/// Exact, nonsecret pairing occurrence reconstructed from durable canonical bytes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredPairingOccurrence {
    pub occurrence: PairingOccurrence,
    pub document_bytes: Vec<u8>,
    pub document_digest: ValueDigest,
    pub commit_seq: CommitSeq,
}

/// Store-owned receipt for a pairing append. It is only created after exact post-commit readback.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairingJournalReceipt {
    occurrence_id: StableString,
    document_digest: ValueDigest,
    readback_bytes: Vec<u8>,
    commit_seq: CommitSeq,
    status: IdempotencyStatus,
}

impl PairingJournalReceipt {
    #[must_use]
    pub const fn occurrence_id(&self) -> &StableString {
        &self.occurrence_id
    }
    #[must_use]
    pub const fn document_digest(&self) -> &ValueDigest {
        &self.document_digest
    }
    #[must_use]
    pub fn readback_bytes(&self) -> &[u8] {
        &self.readback_bytes
    }
    #[must_use]
    pub const fn commit_seq(&self) -> CommitSeq {
        self.commit_seq
    }
    #[must_use]
    pub const fn status(&self) -> IdempotencyStatus {
        self.status
    }
}

/// Store-derived epoch and restart-invalidation receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairingEpochReceipt {
    pub origin: PairingOrigin,
    pub epoch: u64,
    pub invalidated_issue_count: u32,
    pub invalidated_session_count: u32,
    pub next_ordinal: u64,
    pub rate: PairingRateBootstrap,
    pub epoch_occurrence: PairingJournalReceipt,
    pub invalidations: Vec<PairingJournalReceipt>,
    pub commit_seq: CommitSeq,
    pub status: IdempotencyStatus,
}

/// Frozen rate policy persisted with every pairing epoch.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PairingRatePolicyV1 {
    pub max_failed_attempts: u32,
    pub attempt_window_ms: u64,
    pub max_issued_per_window: u32,
    pub issue_window_ms: u64,
}

/// Exact still-live fixed wall window reconstructed by the store.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairingRateWindowBootstrap {
    pub window_id: Option<StableString>,
    pub used: u32,
    pub expires_at: Option<PairingWallInstant>,
}

/// Durable restart rate state. Process monotonic state is initialized from this wall closure.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairingRateBootstrap {
    pub last_observed_at: PairingWallInstant,
    pub attempt: PairingRateWindowBootstrap,
    pub issue: PairingRateWindowBootstrap,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct PairingResolvedRateWindow {
    window_id: StableString,
    started_wall_us: i64,
    expires_wall_us: i64,
}

fn validate_pairing_rate_policy(policy: PairingRatePolicyV1) -> Result<()> {
    if !(1..=8).contains(&policy.max_failed_attempts)
        || !(10_000..=300_000).contains(&policy.attempt_window_ms)
        || !(1..=8).contains(&policy.max_issued_per_window)
        || !(10_000..=300_000).contains(&policy.issue_window_ms)
    {
        return Err(StoreError::InvalidBatch(
            "pairing rate policy exceeds the frozen protocol bounds".into(),
        ));
    }
    Ok(())
}

fn load_live_pairing_predecessors_tx(
    tx: &Transaction<'_>,
    origin: &PairingOrigin,
) -> Result<Vec<StoredPairingOccurrence>> {
    type Row = (String, String, Vec<u8>, String, i64, i64);
    let mut statement = tx.prepare(
        "SELECT p.pairing_occurrence_id,p.occurrence_kind,p.document_bytes,
                p.document_sha256,p.document_byte_length,p.created_commit_seq
         FROM wave5_g0_pairing_occurrence_v1 p
         WHERE p.origin=?1 AND p.occurrence_kind IN ('issued','consumed')
           AND NOT EXISTS (SELECT 1 FROM wave5_g0_pairing_occurrence_v1 child
                           WHERE child.predecessor_occurrence_id=p.pairing_occurrence_id)
         ORDER BY p.pairing_occurrence_id",
    )?;
    let rows = statement
        .query_map([origin.as_str()], |row| {
            Ok((
                row.get(0)?,
                row.get(1)?,
                row.get(2)?,
                row.get(3)?,
                row.get(4)?,
                row.get(5)?,
            ))
        })?
        .collect::<std::result::Result<Vec<Row>, _>>()?;
    rows.into_iter()
        .map(|(id, kind, bytes, raw, length, seq)| {
            let occurrence = parse_pairing_occurrence(&bytes)
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
            let digest = bytes_digest(&bytes)?;
            if occurrence.occurrence_id.as_str() != id
                || occurrence.origin != *origin
                || pairing_kind(occurrence.kind) != kind
                || !matches!(
                    occurrence.kind,
                    PairingOccurrenceKind::Issued | PairingOccurrenceKind::Consumed
                )
                || raw_digest(&digest, "pairing live predecessor")? != raw
                || usize_i64(bytes.len(), "pairing live predecessor bytes")? != length
            {
                return Err(StoreError::InvalidBatch(
                    "pairing live predecessor differs from its exact durable bytes".into(),
                ));
            }
            Ok(StoredPairingOccurrence {
                occurrence,
                document_bytes: bytes,
                document_digest: digest,
                commit_seq: CommitSeq::new(as_u64(seq, "pairing predecessor commit")?),
            })
        })
        .collect()
}

impl SqliteStore {
    /// Begins the next durable pairing epoch and invalidates every prior live issue/session in the
    /// same transaction. The store, not the route, derives the epoch and invalidation identities.
    pub fn begin_pairing_epoch_v1(
        &mut self,
        origin: &PairingOrigin,
        sample: PairingClockSample,
        policy: PairingRatePolicyV1,
        context: &Wave5CommitContext,
    ) -> Result<PairingEpochReceipt> {
        validate_pairing_rate_policy(policy)?;
        if sample.observed_at.get() > context.committed_at {
            return Err(StoreError::InvalidBatch(
                "pairing epoch sample is later than the store commit clock".into(),
            ));
        }
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        if let Some((seq, _)) = existing_commit(&tx, context.batch_id.as_str())? {
            drop(tx);
            let receipt = self.load_pairing_epoch_receipt(
                origin,
                seq,
                policy,
                IdempotencyStatus::Idempotent,
            )?;
            let exact = parse_pairing_occurrence(receipt.epoch_occurrence.readback_bytes())
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
            if exact.observed_at != sample.observed_at
                || exact.at_monotonic_ms != sample.monotonic_ms
            {
                return Err(StoreError::IdentityConflict {
                    kind: "pairing epoch sample",
                    identity: context.batch_id.to_string(),
                });
            }
            return Ok(receipt);
        }
        let prior_epoch: Option<i64> = tx.query_row(
            "SELECT MAX(epoch) FROM wave5_g0_pairing_epoch_v1 WHERE origin=?1",
            [origin.as_str()],
            |row| row.get(0),
        )?;
        let next_epoch = match prior_epoch {
            None => 1,
            Some(value) => {
                let value = as_u64(value, "pairing epoch")?;
                value.checked_add(1).ok_or(StoreError::IntegerRange {
                    field: "pairing epoch",
                    value: value.to_string(),
                })?
            }
        };
        let epoch_occurrence = PairingOccurrence {
            contract: stable(joshi_pairing::PAIRING_OCCURRENCE_CONTRACT)?,
            schema_version: joshi_pairing::PAIRING_SCHEMA_VERSION,
            occurrence_id: pairing_epoch_occurrence_id(origin, next_epoch),
            kind: PairingOccurrenceKind::EpochStarted,
            issue_id: None,
            session_id: None,
            predecessor_occurrence_id: None,
            origin: origin.clone(),
            epoch: PairingEpoch::new(next_epoch)
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            at_monotonic_ms: sample.monotonic_ms,
            observed_at: sample.observed_at,
            expires_at: None,
            scopes: Vec::new(),
            rate_window_id: None,
            rate_window_expires_at: None,
            failed_attempt_ordinal: None,
            attempt_window_started_monotonic_ms: None,
            reason: Some(stable("process_start")?),
            authority: stable(PAIRING_AUTHORITY)?,
        };
        let epoch_bytes = epoch_occurrence
            .canonical_bytes()
            .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
        let rate = Self::resolve_pairing_rate_bootstrap(&tx, origin, sample.observed_at, policy)?;
        let live = load_live_pairing_predecessors_tx(&tx, origin)?;
        let mut invalidations = Vec::with_capacity(live.len());
        for (index, predecessor) in live.iter().enumerate() {
            let prior = &predecessor.occurrence;
            let ordinal = u64::try_from(index)
                .map_err(|_| StoreError::IntegerRange {
                    field: "pairing restart ordinal",
                    value: index.to_string(),
                })?
                .checked_add(1)
                .ok_or(StoreError::IntegerRange {
                    field: "pairing restart ordinal",
                    value: index.to_string(),
                })?;
            let occurrence = PairingOccurrence {
                contract: stable(joshi_pairing::PAIRING_OCCURRENCE_CONTRACT)?,
                schema_version: joshi_pairing::PAIRING_SCHEMA_VERSION,
                occurrence_id: pairing_occurrence_id(origin, next_epoch, ordinal),
                kind: PairingOccurrenceKind::RestartInvalidated,
                issue_id: if prior.kind == PairingOccurrenceKind::Issued {
                    prior.issue_id.clone()
                } else {
                    None
                },
                session_id: if prior.kind == PairingOccurrenceKind::Consumed {
                    prior.session_id.clone()
                } else {
                    None
                },
                predecessor_occurrence_id: Some(prior.occurrence_id.clone()),
                origin: origin.clone(),
                epoch: PairingEpoch::new(next_epoch)
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                at_monotonic_ms: sample.monotonic_ms,
                observed_at: sample.observed_at,
                expires_at: None,
                scopes: prior.scopes.clone(),
                rate_window_id: None,
                rate_window_expires_at: None,
                failed_attempt_ordinal: None,
                attempt_window_started_monotonic_ms: None,
                reason: Some(stable("process_restart")?),
                authority: stable(PAIRING_AUTHORITY)?,
            };
            invalidations.push(
                occurrence
                    .canonical_bytes()
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
            );
        }
        let operation = digest_json(&(
            "joshi.store.pairing.begin_epoch.v1",
            origin.as_str(),
            next_epoch,
            policy.max_failed_attempts,
            policy.attempt_window_ms,
            policy.max_issued_per_window,
            policy.issue_window_ms,
            rate.attempt.window_id.as_ref().map(StableString::as_str),
            rate.attempt.used,
            rate.issue.window_id.as_ref().map(StableString::as_str),
            rate.issue.used,
            format!("{:x}", Sha256::digest(&epoch_bytes)),
            invalidations
                .iter()
                .map(|bytes| format!("{:x}", Sha256::digest(bytes)))
                .collect::<Vec<_>>(),
        ))?;
        let observed = timestamp_us(sample.observed_at.get(), "pairing epoch observed_at")?;
        let issue_count = live
            .iter()
            .filter(|value| value.occurrence.kind == PairingOccurrenceKind::Issued)
            .count();
        let session_count = live
            .iter()
            .filter(|value| value.occurrence.kind == PairingOccurrenceKind::Consumed)
            .count();
        insert_commit(&tx, context, "command", &operation)?;
        let seq = tx.last_insert_rowid();
        insert_pairing_occurrence(&tx, &epoch_occurrence, &epoch_bytes, None, seq)?;
        tx.execute(
            "INSERT INTO wave5_g0_pairing_epoch_v1
             (origin,epoch,observed_wall_us,max_failed_attempts,attempt_window_ms,
              max_issued_per_window,issue_window_ms,last_observed_wall_us,
              attempt_window_id,attempt_used,attempt_expires_wall_us,
              issue_window_id,issue_used,issue_expires_wall_us,
              invalidated_issue_count,invalidated_session_count,epoch_occurrence_id,
              created_commit_seq)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18)",
            params![
                origin.as_str(),
                sqlite_u64(next_epoch, "pairing epoch")?,
                observed,
                i64::from(policy.max_failed_attempts),
                sqlite_u64(policy.attempt_window_ms, "pairing attempt window")?,
                i64::from(policy.max_issued_per_window),
                sqlite_u64(policy.issue_window_ms, "pairing issue window")?,
                timestamp_us(rate.last_observed_at.get(), "pairing last observed_at")?,
                rate.attempt.window_id.as_ref().map(StableString::as_str),
                i64::from(rate.attempt.used),
                rate.attempt
                    .expires_at
                    .map(|value| timestamp_us(value.get(), "pairing attempt window expiry"))
                    .transpose()?,
                rate.issue.window_id.as_ref().map(StableString::as_str),
                i64::from(rate.issue.used),
                rate.issue
                    .expires_at
                    .map(|value| timestamp_us(value.get(), "pairing issue window expiry"))
                    .transpose()?,
                sqlite_usize(issue_count, "invalidated issue count")?,
                sqlite_usize(session_count, "invalidated session count")?,
                epoch_occurrence.occurrence_id.as_str(),
                seq
            ],
        )?;
        for bytes in &invalidations {
            let occurrence = parse_pairing_occurrence(bytes)
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
            insert_pairing_occurrence(&tx, &occurrence, bytes, None, seq)?;
        }
        tx.commit()?;
        self.load_pairing_epoch_receipt(origin, seq, policy, IdempotencyStatus::Accepted)
    }

    /// Atomically appends exact canonical nonsecret pairing occurrences for the active epoch.
    pub fn append_pairing_occurrences_v1(
        &mut self,
        exact_documents: &[Vec<u8>],
        context: &Wave5CommitContext,
    ) -> Result<Vec<PairingJournalReceipt>> {
        if exact_documents.is_empty() {
            return Err(StoreError::InvalidBatch("pairing append is empty".into()));
        }
        let mut parsed = Vec::with_capacity(exact_documents.len());
        for bytes in exact_documents {
            if bytes.len() > MAX_CONTROL_BYTES {
                return Err(StoreError::InvalidBatch(
                    "pairing occurrence exceeds bound".into(),
                ));
            }
            let occurrence = parse_pairing_occurrence(bytes).map_err(|error| {
                StoreError::InvalidBatch(format!("pairing occurrence: {error}"))
            })?;
            if matches!(
                occurrence.kind,
                PairingOccurrenceKind::EpochStarted | PairingOccurrenceKind::RestartInvalidated
            ) {
                return Err(StoreError::InvalidBatch(
                    "epoch/restart occurrences are allocated only by begin_pairing_epoch_v1".into(),
                ));
            }
            if occurrence.observed_at.get() > context.committed_at {
                return Err(StoreError::InvalidBatch(
                    "pairing occurrence is later than the store commit clock".into(),
                ));
            }
            parsed.push(occurrence);
        }
        let Some(first) = parsed.first() else {
            return Err(StoreError::InvalidBatch("pairing append is empty".into()));
        };
        if parsed
            .iter()
            .any(|value| value.origin != first.origin || value.epoch != first.epoch)
        {
            return Err(StoreError::InvalidBatch(
                "pairing atomic append crosses origin or epoch".into(),
            ));
        }
        let operation = digest_json(&(
            "joshi.store.pairing.append.v1",
            exact_documents
                .iter()
                .map(|bytes| format!("{:x}", Sha256::digest(bytes)))
                .collect::<Vec<_>>(),
        ))?;
        if let Some((seq, raw)) = existing_commit(&self.connection, context.batch_id.as_str())? {
            if raw != raw_digest(&operation, "pairing append")? {
                return Err(StoreError::IdentityConflict {
                    kind: "pairing append",
                    identity: context.batch_id.to_string(),
                });
            }
            return self.pairing_receipts_for_exact(
                exact_documents,
                seq,
                IdempotencyStatus::Idempotent,
            );
        }
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let active: i64 = tx
            .query_row(
                "SELECT MAX(epoch) FROM wave5_g0_pairing_epoch_v1 WHERE origin=?1",
                [first.origin.as_str()],
                |row| row.get(0),
            )
            .map_err(|_| StoreError::InvalidBatch("pairing origin has no durable epoch".into()))?;
        if as_u64(active, "active pairing epoch")? != first.epoch.get() {
            return Err(StoreError::InvalidBatch(
                "pairing occurrence names a stale epoch".into(),
            ));
        }
        insert_commit(&tx, context, "command", &operation)?;
        let seq = tx.last_insert_rowid();
        for (occurrence, bytes) in parsed.iter().zip(exact_documents) {
            validate_pairing_transition_clocks(&tx, occurrence)?;
            validate_pairing_origin_clock(&tx, occurrence)?;
            let rate = resolve_pairing_rate_window(&tx, occurrence)?;
            insert_pairing_occurrence(&tx, occurrence, bytes, rate.as_ref(), seq)?;
        }
        tx.commit()?;
        self.pairing_receipts_for_exact(exact_documents, seq, IdempotencyStatus::Accepted)
    }

    /// Reopens one pairing occurrence from exact bytes and rejects any scalar/digest substitution.
    pub fn load_pairing_occurrence_v1(
        &self,
        occurrence_id: &StableString,
    ) -> Result<Option<StoredPairingOccurrence>> {
        type Row = (
            String,
            Option<String>,
            Option<String>,
            Option<String>,
            Option<String>,
            String,
            i64,
            String,
            i64,
            Option<i64>,
            String,
            Option<i64>,
            Option<String>,
            String,
            Option<String>,
            Option<i64>,
            Option<i64>,
            String,
            Vec<u8>,
            i64,
            String,
            i64,
        );
        let row: Option<Row> = self.connection.query_row(
            "SELECT occurrence_kind,issue_id,session_id,predecessor_occurrence_id,reason,origin,
                    epoch,at_monotonic_ms,observed_wall_us,expires_wall_us,scopes_json,
                    failed_attempt_ordinal,attempt_window_started_monotonic_ms,document_sha256,
                    rate_window_id,rate_window_started_wall_us,rate_window_expires_wall_us,
                    authority,document_bytes,document_byte_length,pairing_occurrence_id,created_commit_seq
             FROM wave5_g0_pairing_occurrence_v1 WHERE pairing_occurrence_id=?1",
            [occurrence_id.as_str()],
            |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?,row.get(4)?,row.get(5)?,
                row.get(6)?,row.get(7)?,row.get(8)?,row.get(9)?,row.get(10)?,row.get(11)?,
                row.get(12)?,row.get(13)?,row.get(14)?,row.get(15)?,row.get(16)?,row.get(17)?,
                row.get(18)?,row.get(19)?,row.get(20)?,row.get(21)?)),
        ).optional()?;
        let Some((
            kind,
            issue,
            session,
            predecessor,
            reason,
            origin,
            epoch,
            monotonic,
            observed,
            expires,
            scopes,
            ordinal,
            window,
            raw,
            rate_window_id,
            rate_window_started,
            rate_window_expires,
            authority,
            bytes,
            length,
            id,
            seq,
        )) = row
        else {
            return Ok(None);
        };
        let occurrence = parse_pairing_occurrence(&bytes).map_err(|error| {
            StoreError::InvalidBatch(format!("stored pairing occurrence: {error}"))
        })?;
        let digest = bytes_digest(&bytes)?;
        let canonical_scopes = serde_json::to_string(&occurrence.scopes)?;
        if occurrence.occurrence_id.as_str() != id
            || occurrence.occurrence_id != *occurrence_id
            || pairing_kind(occurrence.kind) != kind
            || occurrence.issue_id.as_ref().map(StableString::as_str) != issue.as_deref()
            || occurrence.session_id.as_ref().map(StableString::as_str) != session.as_deref()
            || occurrence
                .predecessor_occurrence_id
                .as_ref()
                .map(StableString::as_str)
                != predecessor.as_deref()
            || occurrence.reason.as_ref().map(StableString::as_str) != reason.as_deref()
            || occurrence.origin.as_str() != origin
            || occurrence.epoch.get() != as_u64(epoch, "pairing epoch")?
            || occurrence.at_monotonic_ms.get().to_string() != monotonic
            || timestamp_us(occurrence.observed_at.get(), "pairing observed_at")? != observed
            || occurrence
                .expires_at
                .map(|value| timestamp_us(value.get(), "pairing expires_at"))
                .transpose()?
                != expires
            || canonical_scopes != scopes
            || occurrence.failed_attempt_ordinal.map(i64::from) != ordinal
            || occurrence
                .attempt_window_started_monotonic_ms
                .map(|value| value.get().to_string())
                != window
            || occurrence.rate_window_id.as_ref().map(StableString::as_str)
                != rate_window_id.as_deref()
            || occurrence
                .rate_window_expires_at
                .map(|value| timestamp_us(value.get(), "pairing rate window expiry"))
                .transpose()?
                != rate_window_expires
            || raw_digest(&digest, "pairing document")? != raw
            || authority != PAIRING_AUTHORITY
            || usize_i64(bytes.len(), "pairing document bytes")? != length
        {
            return Err(StoreError::InvalidBatch(
                "persisted pairing occurrence differs from exact canonical bytes".into(),
            ));
        }
        validate_pairing_rate_readback(
            &self.connection,
            &occurrence,
            rate_window_started,
            rate_window_expires,
        )?;
        Ok(Some(StoredPairingOccurrence {
            occurrence,
            document_bytes: bytes,
            document_digest: digest,
            commit_seq: CommitSeq::new(as_u64(seq, "pairing commit")?),
        }))
    }

    fn resolve_pairing_rate_bootstrap(
        connection: &Connection,
        origin: &PairingOrigin,
        observed_at: PairingWallInstant,
        policy: PairingRatePolicyV1,
    ) -> Result<PairingRateBootstrap> {
        let previous: Option<(i64, i64, i64, i64)> = connection
            .query_row(
                "SELECT max_failed_attempts,attempt_window_ms,max_issued_per_window,issue_window_ms
             FROM wave5_g0_pairing_epoch_v1 WHERE origin=?1 ORDER BY epoch DESC LIMIT 1",
                [origin.as_str()],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .optional()?;
        if let Some((attempt_max, attempt_ms, issue_max, issue_ms)) = previous {
            let prior = PairingRatePolicyV1 {
                max_failed_attempts: u32::try_from(attempt_max).map_err(|_| {
                    StoreError::InvalidBatch("stored attempt maximum is invalid".into())
                })?,
                attempt_window_ms: as_u64(attempt_ms, "stored attempt window")?,
                max_issued_per_window: u32::try_from(issue_max).map_err(|_| {
                    StoreError::InvalidBatch("stored issue maximum is invalid".into())
                })?,
                issue_window_ms: as_u64(issue_ms, "stored issue window")?,
            };
            if prior != policy {
                let old =
                    Self::rederive_pairing_rate(connection, origin, observed_at, prior, None)?;
                if old.attempt.window_id.is_some() || old.issue.window_id.is_some() {
                    return Err(StoreError::InvalidBatch(
                        "pairing rate policy changed while a durable window is live".into(),
                    ));
                }
            }
        }
        Self::rederive_pairing_rate(connection, origin, observed_at, policy, None)
    }

    fn rederive_pairing_rate(
        connection: &Connection,
        origin: &PairingOrigin,
        observed_at: PairingWallInstant,
        policy: PairingRatePolicyV1,
        before_commit: Option<i64>,
    ) -> Result<PairingRateBootstrap> {
        let observed_us = timestamp_us(observed_at.get(), "pairing rate observed_at")?;
        let last: Option<i64> = connection.query_row(
            "SELECT MAX(observed_wall_us) FROM wave5_g0_pairing_occurrence_v1
             WHERE origin=?1 AND (?2 IS NULL OR created_commit_seq < ?2)",
            params![origin.as_str(), before_commit],
            |row| row.get(0),
        )?;
        if last.is_some_and(|value| value > observed_us) {
            return Err(StoreError::InvalidBatch(
                "pairing restart wall clock regresses durable rate state".into(),
            ));
        }
        let last_observed_at = PairingWallInstant::new(timestamp_from_us(
            last.unwrap_or(observed_us),
            "pairing last observed_at",
        )?);
        Ok(PairingRateBootstrap {
            last_observed_at,
            attempt: Self::rederive_pairing_rate_window(
                connection,
                origin,
                "attempt_rejected",
                observed_at,
                policy.attempt_window_ms,
                before_commit,
            )?,
            issue: Self::rederive_pairing_rate_window(
                connection,
                origin,
                "issued",
                observed_at,
                policy.issue_window_ms,
                before_commit,
            )?,
        })
    }

    fn rederive_pairing_rate_window(
        connection: &Connection,
        origin: &PairingOrigin,
        kind: &'static str,
        observed_at: PairingWallInstant,
        duration_ms: u64,
        before_commit: Option<i64>,
    ) -> Result<PairingRateWindowBootstrap> {
        let mut statement = connection.prepare(
            "SELECT pairing_occurrence_id,observed_wall_us
             FROM wave5_g0_pairing_occurrence_v1
             WHERE origin=?1 AND occurrence_kind=?2
               AND (?3 IS NULL OR created_commit_seq < ?3)
             ORDER BY observed_wall_us,created_commit_seq,rowid",
        )?;
        let rows = statement
            .query_map(params![origin.as_str(), kind, before_commit], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        let mut window_id: Option<StableString> = None;
        let mut used = 0_u32;
        let mut expires_at: Option<PairingWallInstant> = None;
        for (id, observed) in rows {
            let observed =
                PairingWallInstant::new(timestamp_from_us(observed, "pairing rate event")?);
            if expires_at.is_none_or(|expiry| observed >= expiry) {
                window_id = Some(stable(id)?);
                used = 1;
                expires_at = Some(
                    observed
                        .checked_add_ms(duration_ms)
                        .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                );
            } else {
                used = used.checked_add(1).ok_or(StoreError::IntegerRange {
                    field: "pairing rate used",
                    value: used.to_string(),
                })?;
            }
        }
        if expires_at.is_some_and(|expiry| observed_at >= expiry) {
            window_id = None;
            used = 0;
            expires_at = None;
        }
        Ok(PairingRateWindowBootstrap {
            window_id,
            used,
            expires_at,
        })
    }

    fn pairing_receipts_for_exact(
        &self,
        documents: &[Vec<u8>],
        seq: i64,
        status: IdempotencyStatus,
    ) -> Result<Vec<PairingJournalReceipt>> {
        documents
            .iter()
            .map(|bytes| {
                let occurrence = parse_pairing_occurrence(bytes)
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?;
                let stored = self
                    .load_pairing_occurrence_v1(&occurrence.occurrence_id)?
                    .ok_or_else(|| StoreError::MissingIdentity {
                        kind: "pairing occurrence",
                        identity: occurrence.occurrence_id.to_string(),
                    })?;
                if stored.document_bytes != *bytes
                    || stored.commit_seq.get() != as_u64(seq, "pairing commit")?
                {
                    return Err(StoreError::InvalidBatch(
                        "pairing idempotent readback differs".into(),
                    ));
                }
                Ok(PairingJournalReceipt {
                    occurrence_id: occurrence.occurrence_id,
                    document_digest: stored.document_digest,
                    readback_bytes: stored.document_bytes,
                    commit_seq: stored.commit_seq,
                    status,
                })
            })
            .collect()
    }

    fn load_pairing_epoch_receipt(
        &self,
        origin: &PairingOrigin,
        seq: i64,
        policy: PairingRatePolicyV1,
        status: IdempotencyStatus,
    ) -> Result<PairingEpochReceipt> {
        type EpochRow = (
            String,
            i64,
            i64,
            i64,
            String,
            i64,
            i64,
            i64,
            i64,
            i64,
            Option<String>,
            i64,
            Option<i64>,
            Option<String>,
            i64,
            Option<i64>,
        );
        let row: EpochRow = self.connection.query_row(
            "SELECT origin,epoch,invalidated_issue_count,invalidated_session_count,
                        epoch_occurrence_id,max_failed_attempts,attempt_window_ms,
                        max_issued_per_window,issue_window_ms,last_observed_wall_us,
                        attempt_window_id,attempt_used,attempt_expires_wall_us,
                        issue_window_id,issue_used,issue_expires_wall_us
                 FROM wave5_g0_pairing_epoch_v1 WHERE created_commit_seq=?1",
            [seq],
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
                    row.get(8)?,
                    row.get(9)?,
                    row.get(10)?,
                    row.get(11)?,
                    row.get(12)?,
                    row.get(13)?,
                    row.get(14)?,
                    row.get(15)?,
                ))
            },
        )?;
        let (
            stored_origin,
            epoch,
            issue_count,
            session_count,
            epoch_id,
            attempt_max,
            attempt_ms,
            issue_max,
            issue_ms,
            last_observed,
            attempt_id,
            attempt_used,
            attempt_expires,
            issue_id,
            issue_used,
            issue_expires,
        ) = row;
        if stored_origin != origin.as_str() {
            return Err(StoreError::IdentityConflict {
                kind: "pairing epoch commit",
                identity: seq.to_string(),
            });
        }
        let epoch_id = stable(epoch_id)?;
        let epoch_stored = self.load_pairing_occurrence_v1(&epoch_id)?.ok_or_else(|| {
            StoreError::MissingIdentity {
                kind: "pairing epoch occurrence",
                identity: epoch_id.to_string(),
            }
        })?;
        if epoch_stored.occurrence.kind != PairingOccurrenceKind::EpochStarted {
            return Err(StoreError::InvalidBatch(
                "pairing epoch row points to non-epoch bytes".into(),
            ));
        }
        let stored_policy = PairingRatePolicyV1 {
            max_failed_attempts: u32::try_from(attempt_max).map_err(|_| {
                StoreError::InvalidBatch("stored attempt maximum is invalid".into())
            })?,
            attempt_window_ms: as_u64(attempt_ms, "stored attempt window")?,
            max_issued_per_window: u32::try_from(issue_max)
                .map_err(|_| StoreError::InvalidBatch("stored issue maximum is invalid".into()))?,
            issue_window_ms: as_u64(issue_ms, "stored issue window")?,
        };
        if stored_policy != policy {
            return Err(StoreError::IdentityConflict {
                kind: "pairing epoch rate policy",
                identity: seq.to_string(),
            });
        }
        let rate = Self::rederive_pairing_rate(
            &self.connection,
            origin,
            epoch_stored.occurrence.observed_at,
            policy,
            Some(seq),
        )?;
        let rate_matches = timestamp_us(rate.last_observed_at.get(), "pairing last observed_at")?
            == last_observed
            && rate.attempt.window_id.as_ref().map(StableString::as_str) == attempt_id.as_deref()
            && i64::from(rate.attempt.used) == attempt_used
            && rate
                .attempt
                .expires_at
                .map(|value| timestamp_us(value.get(), "pairing attempt window expiry"))
                .transpose()?
                == attempt_expires
            && rate.issue.window_id.as_ref().map(StableString::as_str) == issue_id.as_deref()
            && i64::from(rate.issue.used) == issue_used
            && rate
                .issue
                .expires_at
                .map(|value| timestamp_us(value.get(), "pairing issue window expiry"))
                .transpose()?
                == issue_expires;
        if !rate_matches {
            return Err(StoreError::InvalidBatch(
                "pairing epoch rate bootstrap differs from durable rederivation".into(),
            ));
        }
        let epoch_occurrence = PairingJournalReceipt {
            occurrence_id: epoch_id,
            document_digest: epoch_stored.document_digest,
            readback_bytes: epoch_stored.document_bytes,
            commit_seq: epoch_stored.commit_seq,
            status,
        };
        let mut statement = self.connection.prepare(
            "SELECT pairing_occurrence_id FROM wave5_g0_pairing_occurrence_v1
             WHERE created_commit_seq=?1 AND occurrence_kind='restart_invalidated'
             ORDER BY rowid",
        )?;
        let ids = statement
            .query_map([seq], |row| row.get::<_, String>(0))?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        let mut invalidations = Vec::with_capacity(ids.len());
        for id in ids {
            let id = stable(id)?;
            let stored = self.load_pairing_occurrence_v1(&id)?.ok_or_else(|| {
                StoreError::MissingIdentity {
                    kind: "pairing invalidation",
                    identity: id.to_string(),
                }
            })?;
            invalidations.push(PairingJournalReceipt {
                occurrence_id: id,
                document_digest: stored.document_digest,
                readback_bytes: stored.document_bytes,
                commit_seq: stored.commit_seq,
                status,
            });
        }
        if usize_i64(invalidations.len(), "pairing invalidation count")?
            != issue_count + session_count
        {
            return Err(StoreError::InvalidBatch(
                "pairing epoch invalidation count differs".into(),
            ));
        }
        for (index, receipt) in invalidations.iter().enumerate() {
            let ordinal = u64::try_from(index)
                .map_err(|_| StoreError::IntegerRange {
                    field: "pairing restart ordinal",
                    value: index.to_string(),
                })?
                .checked_add(1)
                .ok_or(StoreError::IntegerRange {
                    field: "pairing restart ordinal",
                    value: index.to_string(),
                })?;
            let expected = pairing_occurrence_id(origin, as_u64(epoch, "pairing epoch")?, ordinal);
            if receipt.occurrence_id != expected {
                return Err(StoreError::InvalidBatch(
                    "pairing restart invalidation ordinal sequence differs".into(),
                ));
            }
        }
        Ok(PairingEpochReceipt {
            origin: origin.clone(),
            epoch: as_u64(epoch, "pairing epoch")?,
            invalidated_issue_count: u32::try_from(issue_count).map_err(|_| {
                StoreError::IntegerRange {
                    field: "invalidated issue count",
                    value: issue_count.to_string(),
                }
            })?,
            invalidated_session_count: u32::try_from(session_count).map_err(|_| {
                StoreError::IntegerRange {
                    field: "invalidated session count",
                    value: session_count.to_string(),
                }
            })?,
            next_ordinal: u64::try_from(invalidations.len()).map_err(|_| {
                StoreError::IntegerRange {
                    field: "pairing next ordinal",
                    value: invalidations.len().to_string(),
                }
            })?,
            rate,
            epoch_occurrence,
            invalidations,
            commit_seq: CommitSeq::new(as_u64(seq, "pairing epoch commit")?),
            status,
        })
    }
}

fn insert_pairing_occurrence(
    tx: &Transaction<'_>,
    occurrence: &PairingOccurrence,
    bytes: &[u8],
    rate: Option<&PairingResolvedRateWindow>,
    seq: i64,
) -> Result<()> {
    let digest = bytes_digest(bytes)?;
    tx.execute(
        "INSERT INTO wave5_g0_pairing_occurrence_v1
         (pairing_occurrence_id,occurrence_kind,issue_id,session_id,predecessor_occurrence_id,
          origin,epoch,at_monotonic_ms,observed_wall_us,expires_wall_us,scopes_json,
          failed_attempt_ordinal,attempt_window_started_monotonic_ms,rate_window_id,
          rate_window_started_wall_us,rate_window_expires_wall_us,reason,document_sha256,
          document_bytes,document_byte_length,authority,created_commit_seq)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,
                 ?19,?20,?21,?22)",
        params![
            occurrence.occurrence_id.as_str(),
            pairing_kind(occurrence.kind),
            occurrence.issue_id.as_ref().map(StableString::as_str),
            occurrence.session_id.as_ref().map(StableString::as_str),
            occurrence
                .predecessor_occurrence_id
                .as_ref()
                .map(StableString::as_str),
            occurrence.origin.as_str(),
            sqlite_u64(occurrence.epoch.get(), "pairing epoch")?,
            occurrence.at_monotonic_ms.get().to_string(),
            timestamp_us(occurrence.observed_at.get(), "pairing observed_at")?,
            occurrence
                .expires_at
                .map(|value| timestamp_us(value.get(), "pairing expires_at"))
                .transpose()?,
            serde_json::to_string(&occurrence.scopes)?,
            occurrence.failed_attempt_ordinal.map(i64::from),
            occurrence
                .attempt_window_started_monotonic_ms
                .map(|value| value.get().to_string()),
            rate.map(|value| value.window_id.as_str()),
            rate.map(|value| value.started_wall_us),
            rate.map(|value| value.expires_wall_us),
            occurrence.reason.as_ref().map(StableString::as_str),
            raw_digest(&digest, "pairing document")?,
            bytes,
            sqlite_usize(bytes.len(), "pairing document bytes")?,
            PAIRING_AUTHORITY,
            seq,
        ],
    )?;
    Ok(())
}

fn resolve_pairing_rate_window(
    tx: &Transaction<'_>,
    occurrence: &PairingOccurrence,
) -> Result<Option<PairingResolvedRateWindow>> {
    let (kind, max_column, duration_column) = match occurrence.kind {
        PairingOccurrenceKind::Issued => ("issued", "max_issued_per_window", "issue_window_ms"),
        PairingOccurrenceKind::AttemptRejected => (
            "attempt_rejected",
            "max_failed_attempts",
            "attempt_window_ms",
        ),
        _ => {
            if occurrence.rate_window_id.is_some() || occurrence.rate_window_expires_at.is_some() {
                return Err(StoreError::InvalidBatch(
                    "non-budgeted pairing occurrence names a rate window".into(),
                ));
            }
            return Ok(None);
        }
    };
    let sql = format!(
        "SELECT {max_column},{duration_column}
         FROM wave5_g0_pairing_epoch_v1 WHERE origin=?1 AND epoch=?2"
    );
    let (maximum, duration_ms): (i64, i64) = tx.query_row(
        &sql,
        params![
            occurrence.origin.as_str(),
            sqlite_u64(occurrence.epoch.get(), "pairing epoch")?
        ],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;
    let observed = timestamp_us(occurrence.observed_at.get(), "pairing rate observed_at")?;
    let latest: Option<(String, i64, i64)> = tx
        .query_row(
            "SELECT rate_window_id,rate_window_started_wall_us,rate_window_expires_wall_us
             FROM wave5_g0_pairing_occurrence_v1
             WHERE origin=?1 AND occurrence_kind=?2
             ORDER BY observed_wall_us DESC,rowid DESC LIMIT 1",
            params![occurrence.origin.as_str(), kind],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()?;
    let resolved = if let Some((id, started, expiry)) = latest {
        if observed < expiry {
            PairingResolvedRateWindow {
                window_id: stable(id)?,
                started_wall_us: started,
                expires_wall_us: expiry,
            }
        } else {
            new_pairing_rate_window(occurrence, observed, duration_ms)?
        }
    } else {
        new_pairing_rate_window(occurrence, observed, duration_ms)?
    };
    if occurrence.rate_window_id.as_ref() != Some(&resolved.window_id)
        || occurrence
            .rate_window_expires_at
            .map(|value| timestamp_us(value.get(), "pairing rate window expiry"))
            .transpose()?
            != Some(resolved.expires_wall_us)
    {
        return Err(StoreError::InvalidBatch(
            "pairing occurrence rate window differs from store-derived fixed wall window".into(),
        ));
    }
    let used: i64 = tx.query_row(
        "SELECT COUNT(*) FROM wave5_g0_pairing_occurrence_v1
         WHERE origin=?1 AND occurrence_kind=?2 AND rate_window_id=?3",
        params![
            occurrence.origin.as_str(),
            kind,
            resolved.window_id.as_str()
        ],
        |row| row.get(0),
    )?;
    if used >= maximum {
        return Err(StoreError::InvalidBatch(
            "pairing durable rate budget is exhausted".into(),
        ));
    }
    if occurrence.kind == PairingOccurrenceKind::AttemptRejected
        && occurrence.failed_attempt_ordinal.map(i64::from) != used.checked_add(1)
    {
        return Err(StoreError::InvalidBatch(
            "pairing failed-attempt ordinal does not close its exact durable window".into(),
        ));
    }
    Ok(Some(resolved))
}

fn new_pairing_rate_window(
    occurrence: &PairingOccurrence,
    observed_wall_us: i64,
    duration_ms: i64,
) -> Result<PairingResolvedRateWindow> {
    let duration_delta_us = duration_ms
        .checked_mul(1_000)
        .ok_or(StoreError::IntegerRange {
            field: "pairing rate duration",
            value: duration_ms.to_string(),
        })?;
    let expires_wall_us =
        observed_wall_us
            .checked_add(duration_delta_us)
            .ok_or(StoreError::IntegerRange {
                field: "pairing rate expiry",
                value: observed_wall_us.to_string(),
            })?;
    Ok(PairingResolvedRateWindow {
        window_id: occurrence.occurrence_id.clone(),
        started_wall_us: observed_wall_us,
        expires_wall_us,
    })
}

fn validate_pairing_origin_clock(
    tx: &Transaction<'_>,
    occurrence: &PairingOccurrence,
) -> Result<()> {
    let prior: Option<i64> = tx.query_row(
        "SELECT MAX(observed_wall_us) FROM wave5_g0_pairing_occurrence_v1 WHERE origin=?1",
        [occurrence.origin.as_str()],
        |row| row.get(0),
    )?;
    let observed = timestamp_us(occurrence.observed_at.get(), "pairing observed_at")?;
    if prior.is_some_and(|value| observed < value) {
        return Err(StoreError::InvalidBatch(
            "pairing occurrence regresses the durable origin wall clock".into(),
        ));
    }
    Ok(())
}

fn validate_pairing_rate_readback(
    connection: &Connection,
    occurrence: &PairingOccurrence,
    started_wall_us: Option<i64>,
    expires_wall_us: Option<i64>,
) -> Result<()> {
    let kind = match occurrence.kind {
        PairingOccurrenceKind::Issued => "issued",
        PairingOccurrenceKind::AttemptRejected => "attempt_rejected",
        _ => {
            if started_wall_us.is_some()
                || expires_wall_us.is_some()
                || occurrence.rate_window_id.is_some()
                || occurrence.rate_window_expires_at.is_some()
            {
                return Err(StoreError::InvalidBatch(
                    "persisted non-budgeted occurrence has rate-window state".into(),
                ));
            }
            return Ok(());
        }
    };
    let window_id = occurrence.rate_window_id.as_ref().ok_or_else(|| {
        StoreError::InvalidBatch("persisted budgeted occurrence has no rate-window ID".into())
    })?;
    let started = started_wall_us.ok_or_else(|| {
        StoreError::InvalidBatch("persisted budgeted occurrence has no rate-window start".into())
    })?;
    let expires = expires_wall_us.ok_or_else(|| {
        StoreError::InvalidBatch("persisted budgeted occurrence has no rate-window expiry".into())
    })?;
    let opener: (String, String, i64, i64, i64, i64) = connection
        .query_row(
            "SELECT occurrence_kind,origin,epoch,observed_wall_us,
                    rate_window_started_wall_us,rate_window_expires_wall_us
             FROM wave5_g0_pairing_occurrence_v1
             WHERE pairing_occurrence_id=?1 AND rate_window_id=pairing_occurrence_id",
            [window_id.as_str()],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                ))
            },
        )
        .map_err(|_| StoreError::MissingIdentity {
            kind: "pairing rate-window opener",
            identity: window_id.to_string(),
        })?;
    let (opener_kind, opener_origin, opener_epoch, opener_observed, opener_started, opener_expires) =
        opener;
    if opener_kind != kind
        || opener_origin != occurrence.origin.as_str()
        || opener_observed != started
        || opener_started != started
        || opener_expires != expires
    {
        return Err(StoreError::InvalidBatch(
            "persisted pairing rate window does not close its exact opener".into(),
        ));
    }
    let duration_column = if occurrence.kind == PairingOccurrenceKind::Issued {
        "issue_window_ms"
    } else {
        "attempt_window_ms"
    };
    let duration_sql = format!(
        "SELECT {duration_column} FROM wave5_g0_pairing_epoch_v1 WHERE origin=?1 AND epoch=?2"
    );
    let duration_ms: i64 =
        connection.query_row(&duration_sql, params![opener_origin, opener_epoch], |row| {
            row.get(0)
        })?;
    let expected_expiry = started
        .checked_add(
            duration_ms
                .checked_mul(1_000)
                .ok_or(StoreError::IntegerRange {
                    field: "pairing rate duration",
                    value: duration_ms.to_string(),
                })?,
        )
        .ok_or(StoreError::IntegerRange {
            field: "pairing rate expiry",
            value: started.to_string(),
        })?;
    let observed = timestamp_us(occurrence.observed_at.get(), "pairing observed_at")?;
    if expires != expected_expiry || observed < started || observed >= expires {
        return Err(StoreError::InvalidBatch(
            "persisted pairing rate-window bounds differ".into(),
        ));
    }
    let (rowid, maximum): (i64, i64) = connection.query_row(
        &format!(
            "SELECT o.rowid,e.{} FROM wave5_g0_pairing_occurrence_v1 o
             JOIN wave5_g0_pairing_epoch_v1 e ON e.origin=o.origin AND e.epoch=o.epoch
             WHERE o.pairing_occurrence_id=?1",
            if occurrence.kind == PairingOccurrenceKind::Issued {
                "max_issued_per_window"
            } else {
                "max_failed_attempts"
            }
        ),
        [occurrence.occurrence_id.as_str()],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;
    let ordinal: i64 = connection.query_row(
        "SELECT COUNT(*) FROM wave5_g0_pairing_occurrence_v1
         WHERE origin=?1 AND occurrence_kind=?2 AND rate_window_id=?3 AND rowid<=?4",
        params![occurrence.origin.as_str(), kind, window_id.as_str(), rowid],
        |row| row.get(0),
    )?;
    if ordinal > maximum
        || (occurrence.kind == PairingOccurrenceKind::AttemptRejected
            && occurrence.failed_attempt_ordinal.map(i64::from) != Some(ordinal))
    {
        return Err(StoreError::InvalidBatch(
            "persisted pairing rate-window ordinal exceeds its exact budget".into(),
        ));
    }
    Ok(())
}

fn validate_pairing_transition_clocks(
    tx: &Transaction<'_>,
    occurrence: &PairingOccurrence,
) -> Result<()> {
    let Some(predecessor_id) = &occurrence.predecessor_occurrence_id else {
        return Ok(());
    };
    let bytes: Vec<u8> = tx
        .query_row(
            "SELECT document_bytes FROM wave5_g0_pairing_occurrence_v1
         WHERE pairing_occurrence_id=?1",
            [predecessor_id.as_str()],
            |row| row.get(0),
        )
        .map_err(|_| StoreError::MissingIdentity {
            kind: "pairing predecessor",
            identity: predecessor_id.to_string(),
        })?;
    let predecessor = parse_pairing_occurrence(&bytes)
        .map_err(|error| StoreError::InvalidBatch(format!("pairing predecessor: {error}")))?;
    if occurrence.observed_at < predecessor.observed_at
        || (occurrence.epoch == predecessor.epoch
            && occurrence.at_monotonic_ms < predecessor.at_monotonic_ms)
    {
        return Err(StoreError::InvalidBatch(
            "pairing transition regresses its durable clock chain".into(),
        ));
    }
    Ok(())
}

const fn pairing_kind(kind: PairingOccurrenceKind) -> &'static str {
    match kind {
        PairingOccurrenceKind::EpochStarted => "epoch_started",
        PairingOccurrenceKind::Issued => "issued",
        PairingOccurrenceKind::AttemptRejected => "attempt_rejected",
        PairingOccurrenceKind::Consumed => "consumed",
        PairingOccurrenceKind::Revoked => "revoked",
        PairingOccurrenceKind::Expired => "expired",
        PairingOccurrenceKind::RestartInvalidated => "restart_invalidated",
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BackupInventoryEntryV1 {
    root: StableString,
    relative_path: String,
    source_digest: ValueDigest,
    readback_digest: ValueDigest,
    byte_length: WireU64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BackupInventoryV1 {
    contract: StableString,
    schema_version: u16,
    entries: Vec<BackupInventoryEntryV1>,
    authority: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BackupReservationDocumentV1 {
    contract: StableString,
    schema_version: u16,
    backup_id: StableString,
    run_registration_id: StableString,
    catalog_destination: String,
    artifact_destination_root: String,
    authority: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BackupSnapshotDocumentV1 {
    contract: StableString,
    schema_version: u16,
    backup_id: StableString,
    staging_catalog_path: String,
    catalog_digest: ValueDigest,
    source_max_commit_seq: CommitSeq,
    authority: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BackupRestoreReservationDocumentV1 {
    contract: StableString,
    schema_version: u16,
    restore_id: StableString,
    backup_id: StableString,
    catalog_destination: String,
    artifact_destination_root: String,
    authority: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BackupDocumentV1 {
    contract: StableString,
    schema_version: u16,
    backup_id: StableString,
    run_registration_id: StableString,
    catalog_path: String,
    artifact_root: String,
    catalog_digest: ValueDigest,
    source_max_commit_seq: CommitSeq,
    artifact_inventory_digest: ValueDigest,
    artifact_count: WireU64,
    authority: StableString,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct BackupRestoreDocumentV1 {
    contract: StableString,
    schema_version: u16,
    restore_id: StableString,
    backup_id: StableString,
    restored_catalog_path: String,
    restored_artifact_root: String,
    restored_catalog_digest: ValueDigest,
    artifact_inventory_digest: ValueDigest,
    restored_max_commit_seq: CommitSeq,
    authority: StableString,
}

/// Exact G0 backup occurrence and distinct-root artifact readback.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave5G0BackupOccurrence {
    pub backup_id: StableString,
    pub run_registration_id: StableString,
    pub catalog_path: PathBuf,
    pub artifact_root: PathBuf,
    pub catalog_digest: ValueDigest,
    pub source_max_commit_seq: CommitSeq,
    pub artifact_inventory_digest: ValueDigest,
    pub artifact_count: u64,
    pub manifest_bytes: Vec<u8>,
    pub inventory_bytes: Vec<u8>,
    pub commit_seq: CommitSeq,
    pub committed_at: UtcTimestamp,
    pub status: IdempotencyStatus,
}

/// Exact restored-catalog readback bound to one prior G0 backup occurrence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Wave5G0BackupRestoreOccurrence {
    pub restore_id: StableString,
    pub backup_id: StableString,
    pub restored_catalog_path: PathBuf,
    pub restored_artifact_root: PathBuf,
    pub restored_catalog_digest: ValueDigest,
    pub artifact_inventory_digest: ValueDigest,
    pub restored_max_commit_seq: CommitSeq,
    pub readback_bytes: Vec<u8>,
    pub readback_digest: ValueDigest,
    pub commit_seq: CommitSeq,
    pub status: IdempotencyStatus,
}

impl SqliteStore {
    /// Creates a catalog backup, copies every referenced immutable object to a distinct root,
    /// re-hashes that copy, and commits the resulting exact inventory occurrence.
    pub fn commit_wave5_g0_backup_v1(
        &mut self,
        backup_id: &StableString,
        run_registration_id: &StableString,
        catalog_destination: &Path,
        artifact_destination_root: &Path,
        context: &Wave5CommitContext,
    ) -> Result<Wave5G0BackupOccurrence> {
        self.require_writer()?;
        if let Some((seq, _)) = existing_commit(&self.connection, context.batch_id.as_str())? {
            let mut loaded = self.load_wave5_g0_backup_v1(backup_id)?.ok_or_else(|| {
                StoreError::IdentityConflict {
                    kind: "G0 backup batch",
                    identity: context.batch_id.to_string(),
                }
            })?;
            if loaded.run_registration_id != *run_registration_id
                || loaded.catalog_path != catalog_destination
                || loaded.artifact_root != artifact_destination_root
                || loaded.commit_seq.get() != as_u64(seq, "G0 backup commit")?
            {
                return Err(StoreError::IdentityConflict {
                    kind: "G0 backup batch",
                    identity: context.batch_id.to_string(),
                });
            }
            loaded.status = IdempotencyStatus::Idempotent;
            return Ok(loaded);
        }
        let reservation_commit = self.ensure_g0_backup_reservation(
            backup_id,
            run_registration_id,
            catalog_destination,
            artifact_destination_root,
            context,
        )?;
        validate_reserved_destination_roots(
            &self.config.catalog_path,
            &self.config.blob_root,
            &self.config.export_root,
            catalog_destination,
            artifact_destination_root,
        )?;
        self.verify(VerifyDepth::Full)?;
        let backup = self.g0_create_or_reopen_catalog_backup(
            backup_id,
            catalog_destination,
            reservation_commit,
            context,
        )?;
        let inventory = self.g0_copy_backup_inventory(&backup, artifact_destination_root)?;
        if inventory.is_empty() {
            return Err(StoreError::InvalidBatch(
                "G0 backup requires a nonempty reachable immutable-artifact inventory".into(),
            ));
        }
        let inventory_document = BackupInventoryV1 {
            contract: stable("joshi.store.wave5.g0.backup_inventory.v1")?,
            schema_version: 1,
            entries: inventory,
            authority: stable(AUTHORITY)?,
        };
        let inventory_bytes = serde_json::to_vec(&inventory_document)?;
        let inventory_digest = bytes_digest(&inventory_bytes)?;
        let document = BackupDocumentV1 {
            contract: stable("joshi.store.wave5.g0.backup.v1")?,
            schema_version: 1,
            backup_id: backup_id.clone(),
            run_registration_id: run_registration_id.clone(),
            catalog_path: catalog_destination.to_string_lossy().into_owned(),
            artifact_root: artifact_destination_root.to_string_lossy().into_owned(),
            catalog_digest: backup.catalog_digest.clone(),
            source_max_commit_seq: backup.max_commit_seq,
            artifact_inventory_digest: inventory_digest.clone(),
            artifact_count: WireU64::new(u64::try_from(inventory_document.entries.len()).map_err(
                |_| StoreError::IntegerRange {
                    field: "G0 backup artifact count",
                    value: inventory_document.entries.len().to_string(),
                },
            )?),
            authority: stable(AUTHORITY)?,
        };
        let manifest_bytes = serde_json::to_vec(&document)?;
        let manifest_digest = bytes_digest(&manifest_bytes)?;
        let operation = digest_json(&(
            "joshi.store.wave5.g0.backup_commit.v1",
            backup_id.as_str(),
            run_registration_id.as_str(),
            manifest_digest.as_str(),
            inventory_digest.as_str(),
            backup.max_commit_seq.get(),
        ))?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current: i64 = tx.query_row(
            "SELECT COALESCE(MAX(commit_seq),0) FROM ingest_commit",
            [],
            |row| row.get(0),
        )?;
        if as_u64(current, "G0 backup source cutoff")? < backup.max_commit_seq.get() {
            return Err(StoreError::InvalidBatch(
                "catalog advanced while the G0 backup was being read back".into(),
            ));
        }
        insert_commit(&tx, context, "maintenance", &operation)?;
        let seq = tx.last_insert_rowid();
        tx.execute(
            "INSERT INTO wave5_g0_backup_v1
             (backup_id,run_registration_id,source_max_commit_seq,catalog_sha256,
              manifest_sha256,manifest_bytes,manifest_byte_length,
              artifact_inventory_sha256,artifact_inventory_bytes,
              artifact_inventory_byte_length,artifact_count,authority,created_commit_seq)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
            params![
                backup_id.as_str(),
                run_registration_id.as_str(),
                sqlite_u64(backup.max_commit_seq.get(), "G0 backup source cutoff")?,
                raw_digest(&backup.catalog_digest, "G0 backup catalog")?,
                raw_digest(&manifest_digest, "G0 backup manifest")?,
                manifest_bytes,
                sqlite_usize(manifest_bytes.len(), "G0 backup manifest bytes")?,
                raw_digest(&inventory_digest, "G0 backup inventory")?,
                inventory_bytes,
                sqlite_usize(inventory_bytes.len(), "G0 backup inventory bytes")?,
                sqlite_usize(inventory_document.entries.len(), "G0 backup artifacts")?,
                AUTHORITY,
                seq,
            ],
        )?;
        tx.commit()?;
        self.load_wave5_g0_backup_v1(backup_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "G0 backup",
                identity: backup_id.to_string(),
            })
    }

    /// Reopens and re-hashes the exact backup catalog and every distinct-root artifact copy.
    pub fn load_wave5_g0_backup_v1(
        &self,
        backup_id: &StableString,
    ) -> Result<Option<Wave5G0BackupOccurrence>> {
        type Row = (
            String,
            i64,
            String,
            String,
            Vec<u8>,
            i64,
            String,
            Vec<u8>,
            i64,
            i64,
            i64,
            i64,
        );
        let row: Option<Row> = self
            .connection
            .query_row(
                "SELECT run_registration_id,source_max_commit_seq,catalog_sha256,
                    manifest_sha256,manifest_bytes,manifest_byte_length,
                    artifact_inventory_sha256,artifact_inventory_bytes,
                    artifact_inventory_byte_length,artifact_count,backup.created_commit_seq,
                    ingest.committed_wall_us
             FROM wave5_g0_backup_v1 backup
             JOIN ingest_commit ingest ON ingest.commit_seq=backup.created_commit_seq
             WHERE backup.backup_id=?1",
                [backup_id.as_str()],
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
                        row.get(8)?,
                        row.get(9)?,
                        row.get(10)?,
                        row.get(11)?,
                    ))
                },
            )
            .optional()?;
        let Some((
            run,
            source_max,
            catalog_raw,
            manifest_raw,
            manifest_bytes,
            manifest_len,
            inventory_raw,
            inventory_bytes,
            inventory_len,
            count,
            seq,
            committed_wall_us,
        )) = row
        else {
            return Ok(None);
        };
        let document: BackupDocumentV1 = serde_json::from_slice(&manifest_bytes)?;
        let inventory: BackupInventoryV1 = serde_json::from_slice(&inventory_bytes)?;
        let manifest_digest = bytes_digest(&manifest_bytes)?;
        let inventory_digest = bytes_digest(&inventory_bytes)?;
        if serde_json::to_vec(&document)? != manifest_bytes
            || serde_json::to_vec(&inventory)? != inventory_bytes
            || document.backup_id != *backup_id
            || document.run_registration_id.as_str() != run
            || document.source_max_commit_seq.get() != as_u64(source_max, "G0 backup cutoff")?
            || document.catalog_digest != qualified_raw_digest(&catalog_raw, "G0 backup catalog")?
            || document.artifact_inventory_digest != inventory_digest
            || document.artifact_count.get() != as_u64(count, "G0 backup artifacts")?
            || raw_digest(&manifest_digest, "G0 backup manifest")? != manifest_raw
            || raw_digest(&inventory_digest, "G0 backup inventory")? != inventory_raw
            || usize_i64(manifest_bytes.len(), "G0 backup manifest bytes")? != manifest_len
            || usize_i64(inventory_bytes.len(), "G0 backup inventory bytes")? != inventory_len
            || inventory.entries.len() != usize::try_from(count).unwrap_or(usize::MAX)
        {
            return Err(StoreError::InvalidBatch(
                "persisted G0 backup scalar closure differs from exact bytes".into(),
            ));
        }
        let catalog_path = PathBuf::from(&document.catalog_path);
        let artifact_root = PathBuf::from(&document.artifact_root);
        validate_distinct_destination_roots(
            &self.config.catalog_path,
            &self.config.blob_root,
            &self.config.export_root,
            &catalog_path,
            &artifact_root,
        )?;
        verify_exact_path_digest(&catalog_path, &document.catalog_digest)?;
        let backup_connection =
            Connection::open_with_flags(&catalog_path, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        let integrity: String =
            backup_connection.query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
        let backup_maximum: i64 = backup_connection.query_row(
            "SELECT COALESCE(MAX(commit_seq),0) FROM ingest_commit",
            [],
            |row| row.get(0),
        )?;
        if integrity != "ok"
            || as_u64(backup_maximum, "G0 backup catalog cutoff")?
                != document.source_max_commit_seq.get()
        {
            return Err(StoreError::InvalidBatch(
                "G0 backup catalog integrity/cutoff differs".into(),
            ));
        }
        let (reachable_blobs, reachable_exports) =
            Self::g0_referenced_artifacts_from_connection(&backup_connection)?;
        let mut reachable = reachable_blobs
            .into_iter()
            .map(|(path, digest)| ("blob", path, digest))
            .chain(
                reachable_exports
                    .into_iter()
                    .map(|(path, digest)| ("export", path, digest)),
            )
            .collect::<Vec<_>>();
        reachable.sort_by(|left, right| {
            (left.0, &left.1, left.2.as_str()).cmp(&(right.0, &right.1, right.2.as_str()))
        });
        let retained = inventory
            .entries
            .iter()
            .map(|entry| {
                (
                    entry.root.as_str(),
                    PathBuf::from(&entry.relative_path),
                    entry.source_digest.as_str(),
                )
            })
            .collect::<Vec<_>>();
        if reachable.len() != retained.len()
            || reachable.iter().zip(&retained).any(|(left, right)| {
                left.0 != right.0 || left.1 != right.1 || left.2.as_str() != right.2
            })
        {
            return Err(StoreError::InvalidBatch(
                "G0 backup inventory differs from independently rederived catalog reachability"
                    .into(),
            ));
        }
        for entry in &inventory.entries {
            if entry.source_digest != entry.readback_digest {
                return Err(StoreError::InvalidBatch(
                    "G0 backup distinct-root digest differs from its source".into(),
                ));
            }
            let relative = checked_relative_path(&entry.relative_path)?;
            let path = artifact_root.join(entry.root.as_str()).join(relative);
            verify_exact_path_digest(&path, &entry.readback_digest)?;
            let metadata =
                fs::symlink_metadata(&path).map_err(|source| StoreError::io(&path, source))?;
            if metadata.len() != entry.byte_length.get() {
                return Err(StoreError::ArtifactVerification {
                    path,
                    detail: "G0 backup artifact length differs".into(),
                });
            }
        }
        verify_exact_inventory_tree(&artifact_root, &inventory.entries)?;
        Ok(Some(Wave5G0BackupOccurrence {
            backup_id: backup_id.clone(),
            run_registration_id: document.run_registration_id,
            catalog_path,
            artifact_root,
            catalog_digest: document.catalog_digest,
            source_max_commit_seq: document.source_max_commit_seq,
            artifact_inventory_digest: inventory_digest,
            artifact_count: as_u64(count, "G0 backup artifacts")?,
            manifest_bytes,
            inventory_bytes,
            commit_seq: CommitSeq::new(as_u64(seq, "G0 backup commit")?),
            committed_at: timestamp_from_us(committed_wall_us, "G0 backup commit time")?,
            status: IdempotencyStatus::Accepted,
        }))
    }

    /// Restores one exact catalog snapshot to a new root and commits only after reopening it.
    pub fn commit_wave5_g0_backup_restore_v1(
        &mut self,
        restore_id: &StableString,
        backup_id: &StableString,
        catalog_destination: &Path,
        artifact_destination_root: &Path,
        context: &Wave5CommitContext,
    ) -> Result<Wave5G0BackupRestoreOccurrence> {
        self.require_writer()?;
        if let Some((seq, _)) = existing_commit(&self.connection, context.batch_id.as_str())? {
            let mut loaded = self
                .load_wave5_g0_backup_restore_v1(restore_id)?
                .ok_or_else(|| StoreError::IdentityConflict {
                    kind: "G0 backup restore batch",
                    identity: context.batch_id.to_string(),
                })?;
            if loaded.backup_id != *backup_id
                || loaded.restored_catalog_path != catalog_destination
                || loaded.restored_artifact_root != artifact_destination_root
                || loaded.commit_seq.get() != as_u64(seq, "G0 restore commit")?
            {
                return Err(StoreError::IdentityConflict {
                    kind: "G0 backup restore batch",
                    identity: context.batch_id.to_string(),
                });
            }
            loaded.status = IdempotencyStatus::Idempotent;
            return Ok(loaded);
        }
        let backup = self.load_wave5_g0_backup_v1(backup_id)?.ok_or_else(|| {
            StoreError::MissingIdentity {
                kind: "G0 backup",
                identity: backup_id.to_string(),
            }
        })?;
        let _reservation_commit = self.ensure_g0_backup_restore_reservation(
            restore_id,
            backup_id,
            catalog_destination,
            artifact_destination_root,
            context,
        )?;
        validate_reserved_destination_roots(
            &self.config.catalog_path,
            &self.config.blob_root,
            &self.config.export_root,
            catalog_destination,
            artifact_destination_root,
        )?;
        let inventory: BackupInventoryV1 = serde_json::from_slice(&backup.inventory_bytes)?;
        if inventory.entries.is_empty() {
            return Err(StoreError::InvalidBatch(
                "G0 restore requires a nonempty artifact-bearing inventory".into(),
            ));
        }
        let restored_blob_root = artifact_destination_root.join("blob");
        let restored_export_root = artifact_destination_root.join("export");
        for entry in &inventory.entries {
            let relative = checked_relative_path(&entry.relative_path)?;
            let source = backup
                .artifact_root
                .join(entry.root.as_str())
                .join(&relative);
            verify_exact_path_digest(&source, &entry.readback_digest)?;
            let destination_root = match entry.root.as_str() {
                "blob" => &restored_blob_root,
                "export" => &restored_export_root,
                _ => {
                    return Err(StoreError::InvalidBatch(
                        "G0 restore inventory has an unknown artifact root".into(),
                    ));
                }
            };
            let target = destination_root.join(relative);
            copy_file_atomically(&source, &target, &entry.readback_digest)?;
        }
        verify_exact_inventory_tree(artifact_destination_root, &inventory.entries)?;
        let manifest = BackupManifest {
            catalog_path: backup.catalog_path.clone(),
            catalog_digest: backup.catalog_digest.clone(),
            max_commit_seq: backup.source_max_commit_seq,
            referenced_blobs: Vec::new(),
            referenced_exports: Vec::new(),
        };
        copy_file_atomically(
            &manifest.catalog_path,
            catalog_destination,
            &backup.catalog_digest,
        )?;
        let restored = SqliteStore::open(
            crate::StoreConfig {
                catalog_path: catalog_destination.to_owned(),
                blob_root: restored_blob_root,
                export_root: restored_export_root,
                inline_blob_max_bytes: self.config.inline_blob_max_bytes,
                busy_timeout: self.config.busy_timeout,
                catalog_id: self.config.catalog_id.clone(),
                max_observations_per_batch: self.config.max_observations_per_batch,
                max_raw_bytes_per_batch: self.config.max_raw_bytes_per_batch,
            },
            crate::StoreMode::ReadOnly,
        )?;
        let verification = restored.verify(VerifyDepth::Full)?;
        if verification.integrity != "ok"
            || verification.foreign_key_defects != 0
            || verification.max_commit_seq != backup.source_max_commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "restored G0 catalog/artifact roots fail full independent verification".into(),
            ));
        }
        let document = BackupRestoreDocumentV1 {
            contract: stable("joshi.store.wave5.g0.backup_restore.v1")?,
            schema_version: 1,
            restore_id: restore_id.clone(),
            backup_id: backup_id.clone(),
            restored_catalog_path: catalog_destination.to_string_lossy().into_owned(),
            restored_artifact_root: artifact_destination_root.to_string_lossy().into_owned(),
            restored_catalog_digest: backup.catalog_digest.clone(),
            artifact_inventory_digest: backup.artifact_inventory_digest.clone(),
            restored_max_commit_seq: backup.source_max_commit_seq,
            authority: stable(AUTHORITY)?,
        };
        let readback_bytes = serde_json::to_vec(&document)?;
        let readback_digest = bytes_digest(&readback_bytes)?;
        let operation = digest_json(&(
            "joshi.store.wave5.g0.backup_restore_commit.v1",
            restore_id.as_str(),
            backup_id.as_str(),
            readback_digest.as_str(),
        ))?;
        let tx = self
            .connection
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        insert_commit(&tx, context, "maintenance", &operation)?;
        let seq = tx.last_insert_rowid();
        tx.execute(
            "INSERT INTO wave5_g0_backup_restore_v1
             (restore_id,backup_id,restored_catalog_sha256,artifact_inventory_sha256,
              readback_sha256,readback_bytes,readback_byte_length,
              restored_max_commit_seq,authority,created_commit_seq)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
            params![
                restore_id.as_str(),
                backup_id.as_str(),
                raw_digest(&backup.catalog_digest, "G0 restored catalog")?,
                raw_digest(&backup.artifact_inventory_digest, "G0 restored inventory")?,
                raw_digest(&readback_digest, "G0 restore readback")?,
                readback_bytes,
                sqlite_usize(readback_bytes.len(), "G0 restore readback bytes")?,
                sqlite_u64(backup.source_max_commit_seq.get(), "G0 restored cutoff")?,
                AUTHORITY,
                seq,
            ],
        )?;
        tx.commit()?;
        self.load_wave5_g0_backup_restore_v1(restore_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "G0 backup restore",
                identity: restore_id.to_string(),
            })
    }

    /// Reopens one restored catalog and revalidates the exact backup/inventory binding.
    pub fn load_wave5_g0_backup_restore_v1(
        &self,
        restore_id: &StableString,
    ) -> Result<Option<Wave5G0BackupRestoreOccurrence>> {
        type Row = (String, String, String, String, Vec<u8>, i64, i64, i64);
        let row: Option<Row> = self
            .connection
            .query_row(
                "SELECT backup_id,restored_catalog_sha256,artifact_inventory_sha256,
                    readback_sha256,readback_bytes,readback_byte_length,
                    restored_max_commit_seq,created_commit_seq
             FROM wave5_g0_backup_restore_v1 WHERE restore_id=?1",
                [restore_id.as_str()],
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
            .optional()?;
        let Some((
            backup_id,
            catalog_raw,
            inventory_raw,
            readback_raw,
            bytes,
            length,
            maximum,
            seq,
        )) = row
        else {
            return Ok(None);
        };
        let document: BackupRestoreDocumentV1 = serde_json::from_slice(&bytes)?;
        let digest = bytes_digest(&bytes)?;
        if serde_json::to_vec(&document)? != bytes
            || document.restore_id != *restore_id
            || document.backup_id.as_str() != backup_id
            || raw_digest(&document.restored_catalog_digest, "G0 restored catalog")? != catalog_raw
            || raw_digest(&document.artifact_inventory_digest, "G0 restored inventory")?
                != inventory_raw
            || raw_digest(&digest, "G0 restore readback")? != readback_raw
            || usize_i64(bytes.len(), "G0 restore readback bytes")? != length
            || document.restored_max_commit_seq.get() != as_u64(maximum, "G0 restored cutoff")?
        {
            return Err(StoreError::InvalidBatch(
                "persisted G0 restore differs from exact readback bytes".into(),
            ));
        }
        let backup_id = stable(backup_id)?;
        let backup = self.load_wave5_g0_backup_v1(&backup_id)?.ok_or_else(|| {
            StoreError::MissingIdentity {
                kind: "G0 backup",
                identity: backup_id.to_string(),
            }
        })?;
        if backup.catalog_digest != document.restored_catalog_digest
            || backup.artifact_inventory_digest != document.artifact_inventory_digest
            || backup.source_max_commit_seq != document.restored_max_commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "G0 restore no longer closes exact backup".into(),
            ));
        }
        let path = PathBuf::from(&document.restored_catalog_path);
        let artifact_root = PathBuf::from(&document.restored_artifact_root);
        validate_distinct_destination_roots(
            &self.config.catalog_path,
            &self.config.blob_root,
            &self.config.export_root,
            &path,
            &artifact_root,
        )?;
        verify_exact_path_digest(&path, &document.restored_catalog_digest)?;
        let inventory: BackupInventoryV1 = serde_json::from_slice(&backup.inventory_bytes)?;
        verify_exact_inventory_tree(&artifact_root, &inventory.entries)?;
        verify_inventory_entry_readbacks(&artifact_root, &inventory.entries)?;
        let restored = SqliteStore::open(
            crate::StoreConfig {
                catalog_path: path.clone(),
                blob_root: artifact_root.join("blob"),
                export_root: artifact_root.join("export"),
                inline_blob_max_bytes: self.config.inline_blob_max_bytes,
                busy_timeout: self.config.busy_timeout,
                catalog_id: self.config.catalog_id.clone(),
                max_observations_per_batch: self.config.max_observations_per_batch,
                max_raw_bytes_per_batch: self.config.max_raw_bytes_per_batch,
            },
            crate::StoreMode::ReadOnly,
        )?;
        let verification = restored.verify(VerifyDepth::Full)?;
        if verification.integrity != "ok"
            || verification.foreign_key_defects != 0
            || verification.max_commit_seq != document.restored_max_commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "persisted G0 restore fails artifact-bearing restart verification".into(),
            ));
        }
        Ok(Some(Wave5G0BackupRestoreOccurrence {
            restore_id: restore_id.clone(),
            backup_id,
            restored_catalog_path: path,
            restored_artifact_root: artifact_root,
            restored_catalog_digest: document.restored_catalog_digest,
            artifact_inventory_digest: document.artifact_inventory_digest,
            restored_max_commit_seq: document.restored_max_commit_seq,
            readback_bytes: bytes,
            readback_digest: digest,
            commit_seq: CommitSeq::new(as_u64(seq, "G0 restore commit")?),
            status: IdempotencyStatus::Accepted,
        }))
    }

    fn g0_create_or_reopen_catalog_backup(
        &mut self,
        backup_id: &StableString,
        destination: &Path,
        reservation_commit: CommitSeq,
        context: &Wave5CommitContext,
    ) -> Result<BackupManifest> {
        let stage_digest = bytes_digest(backup_id.as_str().as_bytes())?;
        let stage_key = raw_digest(&stage_digest, "G0 backup staging identity")?.to_owned();
        let staging_root = self.config.export_root.join(".joshi-g0-backup-staging");
        let staging_catalog = staging_root.join(format!("{stage_key}.sqlite"));
        reject_unshared_symlink_ancestors(&[&self.config.export_root, &staging_root])?;
        fs::create_dir_all(&staging_root)
            .map_err(|source| StoreError::io(&staging_root, source))?;

        type SnapshotRow = (String, Vec<u8>, i64, String, String, i64, i64);
        let settled: Option<SnapshotRow> = self
            .connection
            .query_row(
                "SELECT snapshot_sha256,snapshot_bytes,snapshot_byte_length,
                        staging_catalog_path,catalog_sha256,source_max_commit_seq,
                        created_commit_seq
                 FROM wave5_g0_backup_snapshot_v1 WHERE backup_id=?1",
                [backup_id.as_str()],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                        row.get(6)?,
                    ))
                },
            )
            .optional()?;
        let mut staged = if let Some((
            snapshot_raw,
            snapshot_bytes,
            snapshot_length,
            stage_path,
            catalog_raw,
            maximum,
            _,
        )) = settled
        {
            let document: BackupSnapshotDocumentV1 = serde_json::from_slice(&snapshot_bytes)?;
            let snapshot_digest = bytes_digest(&snapshot_bytes)?;
            let expected_catalog = qualified_raw_digest(&catalog_raw, "G0 settled catalog")?;
            if serde_json::to_vec(&document)? != snapshot_bytes
                || document.backup_id != *backup_id
                || document.staging_catalog_path != staging_catalog.to_string_lossy()
                || stage_path != staging_catalog.to_string_lossy()
                || document.catalog_digest != expected_catalog
                || document.source_max_commit_seq.get()
                    != as_u64(maximum, "G0 settled backup cutoff")?
                || raw_digest(&snapshot_digest, "G0 backup snapshot")? != snapshot_raw
                || usize_i64(snapshot_bytes.len(), "G0 backup snapshot bytes")? != snapshot_length
            {
                return Err(StoreError::InvalidBatch(
                    "settled private G0 backup snapshot differs from exact bytes".into(),
                ));
            }
            let manifest = self.g0_manifest_for_catalog(&staging_catalog)?;
            if manifest.catalog_digest != document.catalog_digest
                || manifest.max_commit_seq != document.source_max_commit_seq
            {
                return Err(StoreError::InvalidBatch(
                    "private G0 backup stage differs from its durable settlement".into(),
                ));
            }
            manifest
        } else {
            if staging_catalog.exists() {
                let metadata = fs::symlink_metadata(&staging_catalog)
                    .map_err(|source| StoreError::io(&staging_catalog, source))?;
                if !metadata.file_type().is_file() {
                    return Err(StoreError::ArtifactVerification {
                        path: staging_catalog,
                        detail: "private G0 backup staging target is not a regular file".into(),
                    });
                }
                fs::remove_file(&staging_catalog)
                    .map_err(|source| StoreError::io(&staging_catalog, source))?;
            }
            self.backup_to(&staging_catalog)?;
            sync_file_and_directory_chain(&staging_catalog)?;
            let manifest = self.g0_manifest_for_catalog(&staging_catalog)?;
            if manifest.max_commit_seq.get() < reservation_commit.get() {
                return Err(StoreError::InvalidBatch(
                    "private G0 backup snapshot predates its durable reservation".into(),
                ));
            }
            let document = BackupSnapshotDocumentV1 {
                contract: stable("joshi.store.wave5.g0.backup_snapshot.v1")?,
                schema_version: 1,
                backup_id: backup_id.clone(),
                staging_catalog_path: staging_catalog.to_string_lossy().into_owned(),
                catalog_digest: manifest.catalog_digest.clone(),
                source_max_commit_seq: manifest.max_commit_seq,
                authority: stable(AUTHORITY)?,
            };
            let snapshot_bytes = serde_json::to_vec(&document)?;
            let snapshot_digest = bytes_digest(&snapshot_bytes)?;
            let snapshot_context = reservation_context(context, "backup-snapshot", backup_id)?;
            let tx = self
                .connection
                .transaction_with_behavior(TransactionBehavior::Immediate)?;
            insert_commit(&tx, &snapshot_context, "maintenance", &snapshot_digest)?;
            let seq = tx.last_insert_rowid();
            tx.execute(
                "INSERT INTO wave5_g0_backup_snapshot_v1
                 (backup_id,snapshot_sha256,snapshot_bytes,snapshot_byte_length,
                  staging_catalog_path,catalog_sha256,source_max_commit_seq,
                  authority,created_commit_seq)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)",
                params![
                    backup_id.as_str(),
                    raw_digest(&snapshot_digest, "G0 backup snapshot")?,
                    snapshot_bytes,
                    sqlite_usize(snapshot_bytes.len(), "G0 backup snapshot bytes")?,
                    document.staging_catalog_path,
                    raw_digest(&manifest.catalog_digest, "G0 staged backup catalog")?,
                    sqlite_u64(manifest.max_commit_seq.get(), "G0 staged backup cutoff")?,
                    AUTHORITY,
                    seq,
                ],
            )?;
            tx.commit()?;
            manifest
        };
        if staged.max_commit_seq.get() < reservation_commit.get() {
            return Err(StoreError::InvalidBatch(
                "private G0 backup snapshot predates its durable reservation".into(),
            ));
        }
        copy_file_atomically(&staging_catalog, destination, &staged.catalog_digest)?;
        destination.clone_into(&mut staged.catalog_path);
        Ok(staged)
    }

    fn g0_manifest_for_catalog(&self, catalog: &Path) -> Result<BackupManifest> {
        reject_unshared_symlink_ancestors(&[&self.config.catalog_path, catalog])?;
        let bytes = fs::read(catalog).map_err(|source| StoreError::io(catalog, source))?;
        let digest = bytes_digest(&bytes)?;
        let connection =
            Connection::open_with_flags(catalog, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        let integrity: String =
            connection.query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
        if integrity != "ok" {
            return Err(StoreError::InvalidBatch(
                "private G0 backup staging catalog fails integrity".into(),
            ));
        }
        let maximum: i64 = connection.query_row(
            "SELECT COALESCE(MAX(commit_seq),0) FROM ingest_commit",
            [],
            |row| row.get(0),
        )?;
        let maximum = as_u64(maximum, "G0 staged backup cutoff")?;
        if maximum == 0 {
            return Err(StoreError::InvalidBatch(
                "private G0 backup staging catalog has no durable commit".into(),
            ));
        }
        let staged_tip: String = connection.query_row(
            "SELECT commit_digest FROM ingest_commit WHERE commit_seq=?1",
            [sqlite_u64(maximum, "G0 staged backup cutoff")?],
            |row| row.get(0),
        )?;
        let live_tip: Option<String> = self
            .connection
            .query_row(
                "SELECT commit_digest FROM ingest_commit WHERE commit_seq=?1",
                [sqlite_u64(maximum, "G0 staged backup cutoff")?],
                |row| row.get(0),
            )
            .optional()?;
        if live_tip.as_deref() != Some(staged_tip.as_str()) {
            return Err(StoreError::InvalidBatch(
                "private G0 backup staging catalog is not an exact prefix of this store".into(),
            ));
        }
        let (referenced_blobs, referenced_exports) =
            Self::g0_referenced_artifacts_from_connection(&connection)?;
        Ok(BackupManifest {
            catalog_path: catalog.to_owned(),
            catalog_digest: digest,
            max_commit_seq: CommitSeq::new(maximum),
            referenced_blobs,
            referenced_exports,
        })
    }

    fn g0_referenced_artifacts_from_connection(
        connection: &Connection,
    ) -> Result<(Vec<(PathBuf, ValueDigest)>, Vec<(PathBuf, ValueDigest)>)> {
        let mut blobs = Vec::new();
        let mut statement = connection.prepare(
            "SELECT relative_path,stored_sha256 FROM blob_object
             WHERE storage_mode='external' ORDER BY relative_path",
        )?;
        for row in statement.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })? {
            let (path, digest) = row?;
            blobs.push((
                PathBuf::from(path),
                qualified_raw_digest(&digest, "G0 backup blob")?,
            ));
        }
        let mut exports = Vec::new();
        for (table, column, digest_column) in [
            ("export_manifest", "relative_path", "file_sha256"),
            (
                "export_snapshot",
                "manifest_relative_path",
                "manifest_sha256",
            ),
            (
                "derived_analysis_artifact_part_v2",
                "relative_path",
                "file_sha256",
            ),
        ] {
            let sql = format!(
                "SELECT {column},{digest_column} FROM {table} WHERE {column} IS NOT NULL ORDER BY {column}"
            );
            let mut statement = connection.prepare(&sql)?;
            for row in statement.query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })? {
                let (path, digest) = row?;
                exports.push((
                    PathBuf::from(path),
                    qualified_raw_digest(&digest, "G0 backup export")?,
                ));
            }
        }
        exports.sort();
        Ok((blobs, exports))
    }

    fn g0_copy_backup_inventory(
        &self,
        backup: &BackupManifest,
        destination_root: &Path,
    ) -> Result<Vec<BackupInventoryEntryV1>> {
        fs::create_dir_all(destination_root)
            .map_err(|source| StoreError::io(destination_root, source))?;
        let mut entries = Vec::new();
        for (root, source_root, values) in [
            (
                "blob",
                self.config.blob_root.as_path(),
                backup.referenced_blobs.as_slice(),
            ),
            (
                "export",
                self.config.export_root.as_path(),
                backup.referenced_exports.as_slice(),
            ),
        ] {
            for (relative, digest) in values {
                let relative = checked_relative_path(&relative.to_string_lossy())?;
                let source = source_root.join(&relative);
                verify_exact_path_digest(&source, digest)?;
                let target = destination_root.join(root).join(&relative);
                copy_file_atomically(&source, &target, digest)?;
                let metadata = fs::symlink_metadata(&target)
                    .map_err(|source| StoreError::io(&target, source))?;
                entries.push(BackupInventoryEntryV1 {
                    root: stable(root)?,
                    relative_path: relative.to_string_lossy().into_owned(),
                    source_digest: digest.clone(),
                    readback_digest: bytes_digest(
                        &fs::read(&target).map_err(|source| StoreError::io(&target, source))?,
                    )?,
                    byte_length: WireU64::new(metadata.len()),
                });
            }
        }
        entries.sort_by(|left, right| {
            (left.root.as_str(), left.relative_path.as_str())
                .cmp(&(right.root.as_str(), right.relative_path.as_str()))
        });
        verify_exact_inventory_tree(destination_root, &entries)?;
        Ok(entries)
    }
}

fn reservation_context(
    context: &Wave5CommitContext,
    kind: &str,
    identity: &StableString,
) -> Result<Wave5CommitContext> {
    let digest = bytes_digest(
        format!(
            "joshi.store.wave5.g0.{kind}_reservation_commit.v1\0{}\0{}",
            context.batch_id.as_str(),
            identity.as_str()
        )
        .as_bytes(),
    )?;
    Ok(Wave5CommitContext {
        batch_id: stable(format!(
            "g0-{kind}-reservation-{}",
            raw_digest(&digest, "G0 reservation identity")?
        ))?,
        committed_at: context.committed_at,
        writer_clock_id: context.writer_clock_id.clone(),
        committed_mono_ns: context.committed_mono_ns,
        writer_build: context.writer_build.clone(),
    })
}

fn validate_backup_destinations(
    source_catalog: &Path,
    source_blob_root: &Path,
    source_export_root: &Path,
    catalog_destination: &Path,
    artifact_destination_root: &Path,
) -> Result<()> {
    validate_distinct_destination_roots(
        source_catalog,
        source_blob_root,
        source_export_root,
        catalog_destination,
        artifact_destination_root,
    )?;
    if catalog_destination.exists() {
        return Err(StoreError::RestoreDestinationExists(
            catalog_destination.to_owned(),
        ));
    }
    if artifact_destination_root.exists() {
        return Err(StoreError::RestoreDestinationExists(
            artifact_destination_root.to_owned(),
        ));
    }
    Ok(())
}

fn validate_restore_destinations(
    source_catalog: &Path,
    source_blob_root: &Path,
    source_export_root: &Path,
    catalog_destination: &Path,
    artifact_destination_root: &Path,
) -> Result<()> {
    validate_backup_destinations(
        source_catalog,
        source_blob_root,
        source_export_root,
        catalog_destination,
        artifact_destination_root,
    )
}

fn validate_distinct_destination_roots(
    source_catalog: &Path,
    source_blob_root: &Path,
    source_export_root: &Path,
    catalog_destination: &Path,
    artifact_destination_root: &Path,
) -> Result<()> {
    reject_unshared_symlink_ancestors(&[
        source_catalog,
        source_blob_root,
        source_export_root,
        catalog_destination,
        artifact_destination_root,
    ])?;
    let catalog = normalized_absolute_path(catalog_destination)?;
    let artifacts = normalized_absolute_path(artifact_destination_root)?;
    let sources = [
        normalized_absolute_path(source_catalog)?,
        normalized_absolute_path(source_blob_root)?,
        normalized_absolute_path(source_export_root)?,
    ];
    if catalog.starts_with(&artifacts) || artifacts.starts_with(&catalog) {
        return Err(StoreError::InvalidBatch(
            "G0 backup catalog and artifact destinations overlap".into(),
        ));
    }
    if sources.iter().any(|source| {
        catalog == *source
            || catalog.starts_with(source)
            || artifacts == *source
            || artifacts.starts_with(source)
            || source.starts_with(&artifacts)
    }) {
        return Err(StoreError::InvalidBatch(
            "G0 backup/restore destinations overlap a live store root".into(),
        ));
    }
    Ok(())
}

fn validate_reserved_destination_roots(
    source_catalog: &Path,
    source_blob_root: &Path,
    source_export_root: &Path,
    catalog_destination: &Path,
    artifact_destination_root: &Path,
) -> Result<()> {
    validate_distinct_destination_roots(
        source_catalog,
        source_blob_root,
        source_export_root,
        catalog_destination,
        artifact_destination_root,
    )?;
    if catalog_destination.exists() {
        let metadata = fs::symlink_metadata(catalog_destination)
            .map_err(|source| StoreError::io(catalog_destination, source))?;
        if !metadata.file_type().is_file() {
            return Err(StoreError::ArtifactVerification {
                path: catalog_destination.to_owned(),
                detail: "reserved G0 catalog destination is not a regular file".into(),
            });
        }
    }
    if artifact_destination_root.exists() {
        let metadata = fs::symlink_metadata(artifact_destination_root)
            .map_err(|source| StoreError::io(artifact_destination_root, source))?;
        if !metadata.file_type().is_dir() {
            return Err(StoreError::ArtifactVerification {
                path: artifact_destination_root.to_owned(),
                detail: "reserved G0 artifact destination is not a directory".into(),
            });
        }
    }
    Ok(())
}

fn reject_unshared_symlink_ancestors(paths: &[&Path]) -> Result<()> {
    let mut ancestors = Vec::with_capacity(paths.len());
    for path in paths {
        let normalized = normalized_absolute_path(path)?;
        let mut prefix = PathBuf::new();
        let mut found = BTreeSet::new();
        for component in normalized.components() {
            prefix.push(component.as_os_str());
            match fs::symlink_metadata(&prefix) {
                Ok(metadata) if metadata.file_type().is_symlink() => {
                    found.insert(prefix.clone());
                }
                Ok(_) => {}
                Err(source) if source.kind() == std::io::ErrorKind::NotFound => break,
                Err(source) => return Err(StoreError::io(&prefix, source)),
            }
        }
        ancestors.push(found);
    }
    for (index, values) in ancestors.iter().enumerate() {
        if let Some(path) = values
            .iter()
            .find(|value| ancestors.iter().any(|other| !other.contains(*value)))
        {
            return Err(StoreError::ArtifactVerification {
                path: path.clone(),
                detail: format!(
                    "G0 backup/restore path {index} traverses an unshared symbolic-link ancestor"
                ),
            });
        }
    }
    Ok(())
}

fn copy_file_atomically(source: &Path, target: &Path, digest: &ValueDigest) -> Result<()> {
    reject_unshared_symlink_ancestors(&[source, target])?;
    verify_exact_path_digest(source, digest)?;
    if target.exists() {
        verify_exact_path_digest(target, digest)?;
        return sync_file_and_directory_chain(target);
    }
    let parent = target.parent().ok_or_else(|| {
        StoreError::InvalidBatch("G0 backup/restore target has no parent directory".into())
    })?;
    fs::create_dir_all(parent).map_err(|source| StoreError::io(parent, source))?;
    reject_unshared_symlink_ancestors(&[source, parent])?;
    let mut temporary_name = target
        .file_name()
        .ok_or_else(|| {
            StoreError::InvalidBatch("G0 backup/restore target has no file name".into())
        })?
        .to_os_string();
    temporary_name.push(".joshi-g0-partial");
    let temporary = parent.join(temporary_name);
    if temporary.exists() {
        let metadata = fs::symlink_metadata(&temporary)
            .map_err(|source| StoreError::io(&temporary, source))?;
        if !metadata.file_type().is_file() {
            return Err(StoreError::ArtifactVerification {
                path: temporary,
                detail: "G0 partial target is not a regular file".into(),
            });
        }
        fs::remove_file(&temporary).map_err(|source| StoreError::io(&temporary, source))?;
    }
    fs::copy(source, &temporary).map_err(|source| StoreError::io(&temporary, source))?;
    verify_exact_path_digest(&temporary, digest)?;
    fs::File::open(&temporary)
        .and_then(|file| file.sync_all())
        .map_err(|source| StoreError::io(&temporary, source))?;
    fs::rename(&temporary, target).map_err(|source| StoreError::io(target, source))?;
    sync_file_and_directory_chain(target)?;
    verify_exact_path_digest(target, digest)
}

fn sync_file_and_directory_chain(path: &Path) -> Result<()> {
    fs::File::open(path)
        .and_then(|file| file.sync_all())
        .map_err(|source| StoreError::io(path, source))?;
    let mut directory = path.parent();
    while let Some(value) = directory {
        fs::File::open(value)
            .and_then(|file| file.sync_all())
            .map_err(|source| StoreError::io(value, source))?;
        directory = value.parent();
    }
    Ok(())
}

fn verify_exact_inventory_tree(root: &Path, entries: &[BackupInventoryEntryV1]) -> Result<()> {
    reject_unshared_symlink_ancestors(&[root])?;
    let expected = entries
        .iter()
        .map(|entry| {
            Ok(PathBuf::from(entry.root.as_str())
                .join(checked_relative_path(&entry.relative_path)?))
        })
        .collect::<Result<BTreeSet<_>>>()?;
    let mut actual = BTreeSet::new();
    collect_inventory_files(root, root, &mut actual)?;
    if actual != expected {
        return Err(StoreError::InvalidBatch(
            "G0 backup/restore root has missing or unreserved artifact paths".into(),
        ));
    }
    Ok(())
}

fn verify_inventory_entry_readbacks(root: &Path, entries: &[BackupInventoryEntryV1]) -> Result<()> {
    for entry in entries {
        let relative = checked_relative_path(&entry.relative_path)?;
        let path = root.join(entry.root.as_str()).join(relative);
        verify_exact_path_digest(&path, &entry.readback_digest)?;
        let metadata =
            fs::symlink_metadata(&path).map_err(|source| StoreError::io(&path, source))?;
        if metadata.len() != entry.byte_length.get() {
            return Err(StoreError::ArtifactVerification {
                path,
                detail: "G0 restored artifact length differs from exact inventory".into(),
            });
        }
    }
    Ok(())
}

fn collect_inventory_files(
    root: &Path,
    directory: &Path,
    values: &mut BTreeSet<PathBuf>,
) -> Result<()> {
    let metadata =
        fs::symlink_metadata(directory).map_err(|source| StoreError::io(directory, source))?;
    if metadata.file_type().is_symlink() || !metadata.file_type().is_dir() {
        return Err(StoreError::ArtifactVerification {
            path: directory.to_owned(),
            detail: "G0 inventory tree contains a symlink or non-directory root".into(),
        });
    }
    for item in fs::read_dir(directory).map_err(|source| StoreError::io(directory, source))? {
        let item = item.map_err(|source| StoreError::io(directory, source))?;
        let path = item.path();
        let metadata =
            fs::symlink_metadata(&path).map_err(|source| StoreError::io(&path, source))?;
        if metadata.file_type().is_symlink() {
            return Err(StoreError::ArtifactVerification {
                path,
                detail: "G0 inventory tree contains a symbolic link".into(),
            });
        }
        if metadata.file_type().is_dir() {
            collect_inventory_files(root, &path, values)?;
        } else if metadata.file_type().is_file() {
            let relative = path.strip_prefix(root).map_err(|_| {
                StoreError::InvalidBatch("G0 inventory path escapes its reserved root".into())
            })?;
            values.insert(relative.to_owned());
        } else {
            return Err(StoreError::ArtifactVerification {
                path,
                detail: "G0 inventory tree contains a non-regular entry".into(),
            });
        }
    }
    Ok(())
}

fn normalized_absolute_path(path: &Path) -> Result<PathBuf> {
    let absolute = if path.is_absolute() {
        path.to_owned()
    } else {
        std::env::current_dir()
            .map_err(|source| StoreError::io(path, source))?
            .join(path)
    };
    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::Prefix(_) | Component::RootDir | Component::Normal(_) => {
                normalized.push(component.as_os_str());
            }
            Component::CurDir => {}
            Component::ParentDir => {
                if !normalized.pop() {
                    return Err(StoreError::InvalidBatch(
                        "G0 destination escapes its filesystem root".into(),
                    ));
                }
            }
        }
    }
    if normalized.as_os_str().is_empty() {
        return Err(StoreError::InvalidBatch("G0 destination is empty".into()));
    }
    Ok(normalized)
}

fn checked_relative_path(value: &str) -> Result<PathBuf> {
    let path = PathBuf::from(value);
    if path.as_os_str().is_empty()
        || path.is_absolute()
        || path
            .components()
            .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err(StoreError::InvalidBatch(
            "G0 backup path is not a safe relative path".into(),
        ));
    }
    Ok(path)
}

fn verify_exact_path_digest(path: &Path, digest: &ValueDigest) -> Result<()> {
    let metadata = fs::symlink_metadata(path).map_err(|source| StoreError::io(path, source))?;
    if !metadata.file_type().is_file() {
        return Err(StoreError::ArtifactVerification {
            path: path.to_owned(),
            detail: "not a regular file".into(),
        });
    }
    let bytes = fs::read(path).map_err(|source| StoreError::io(path, source))?;
    if bytes_digest(&bytes)? != *digest {
        return Err(StoreError::ArtifactVerification {
            path: path.to_owned(),
            detail: "SHA-256 readback differs".into(),
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{StoreConfig, StoreMode};
    use joshi_pairing::{MonotonicMillis, PairingScope, pairing_origin_tag};
    use std::{path::Path, time::Duration};

    fn stable_test(value: impl Into<String>) -> StableString {
        StableString::new(value).expect("stable test value")
    }

    fn wall(value: &str) -> PairingWallInstant {
        PairingWallInstant::new(value.parse().expect("test timestamp"))
    }

    fn context(id: &str, observed: PairingWallInstant, mono: u64) -> Wave5CommitContext {
        Wave5CommitContext {
            batch_id: stable_test(id),
            committed_at: observed.get(),
            writer_clock_id: stable_test("pairing-test-clock"),
            committed_mono_ns: mono,
            writer_build: stable_test("pairing-test-build"),
        }
    }

    fn config(root: &Path) -> StoreConfig {
        StoreConfig {
            catalog_path: root.join("catalog.sqlite"),
            blob_root: root.join("blobs"),
            export_root: root.join("exports"),
            inline_blob_max_bytes: 1024,
            busy_timeout: Duration::from_secs(1),
            catalog_id: stable_test("pairing-g0-test-catalog"),
            max_observations_per_batch: 16,
            max_raw_bytes_per_batch: 1024 * 1024,
        }
    }

    fn open(root: &Path, migrated_at: PairingWallInstant) -> SqliteStore {
        let mut store =
            SqliteStore::open(config(root), StoreMode::SingleWriter).expect("open test store");
        store
            .migrate(migrated_at.get())
            .expect("migrate test store");
        store
    }

    fn issued(
        origin: &PairingOrigin,
        epoch: u64,
        ordinal: u64,
        observed: PairingWallInstant,
        monotonic: u64,
        rate_window_id: StableString,
        rate_expiry: PairingWallInstant,
    ) -> PairingOccurrence {
        let tag = pairing_origin_tag(origin);
        PairingOccurrence {
            contract: stable_test(joshi_pairing::PAIRING_OCCURRENCE_CONTRACT),
            schema_version: joshi_pairing::PAIRING_SCHEMA_VERSION,
            occurrence_id: pairing_occurrence_id(origin, epoch, ordinal),
            kind: PairingOccurrenceKind::Issued,
            issue_id: Some(stable_test(format!("pair-issue-{tag}-{epoch}-{ordinal}"))),
            session_id: None,
            predecessor_occurrence_id: Some(pairing_epoch_occurrence_id(origin, epoch)),
            origin: origin.clone(),
            epoch: PairingEpoch::new(epoch).expect("epoch"),
            at_monotonic_ms: MonotonicMillis::new(monotonic),
            observed_at: observed,
            expires_at: Some(observed.checked_add_ms(30_000).expect("code expiry")),
            scopes: vec![PairingScope::CockpitRead],
            rate_window_id: Some(rate_window_id),
            rate_window_expires_at: Some(rate_expiry),
            failed_attempt_ordinal: None,
            attempt_window_started_monotonic_ms: None,
            reason: None,
            authority: stable_test(PAIRING_AUTHORITY),
        }
    }

    #[test]
    fn pairing_rate_windows_survive_restart_then_expire_without_permanent_lockout() {
        let temporary = tempfile::tempdir().expect("temporary root");
        let start = wall("2026-08-18T12:00:00.000000Z");
        let origin = PairingOrigin::new("http://127.0.0.1:8787").expect("origin");
        let policy = PairingRatePolicyV1 {
            max_failed_attempts: 2,
            attempt_window_ms: 10_000,
            max_issued_per_window: 1,
            issue_window_ms: 10_000,
        };
        let mut store = open(temporary.path(), start);
        let epoch1 = store
            .begin_pairing_epoch_v1(
                &origin,
                PairingClockSample {
                    monotonic_ms: MonotonicMillis::new(0),
                    observed_at: start,
                },
                policy,
                &context("epoch-1", start, 0),
            )
            .expect("begin epoch 1");
        assert_eq!(
            epoch1.epoch_occurrence.occurrence_id(),
            &pairing_epoch_occurrence_id(&origin, 1)
        );

        let first_at = start.checked_add_ms(1_000).expect("first wall");
        let first_id = pairing_occurrence_id(&origin, 1, 1);
        let first_expiry = first_at.checked_add_ms(10_000).expect("window expiry");
        let first = issued(
            &origin,
            1,
            1,
            first_at,
            1_000,
            first_id.clone(),
            first_expiry,
        );
        let first_bytes = first.canonical_bytes().expect("canonical issue");
        let accepted = store
            .append_pairing_occurrences_v1(
                std::slice::from_ref(&first_bytes),
                &context("issue-1", first_at, 1_000),
            )
            .expect("persist first issue");
        assert_eq!(accepted[0].status(), IdempotencyStatus::Accepted);
        let retry = store
            .append_pairing_occurrences_v1(
                std::slice::from_ref(&first_bytes),
                &context("issue-1", first_at, 1_000),
            )
            .expect("retry first issue");
        assert_eq!(retry[0].status(), IdempotencyStatus::Idempotent);

        let second_at = start.checked_add_ms(2_000).expect("second wall");
        let second = issued(&origin, 1, 2, second_at, 2_000, first_id, first_expiry);
        assert!(
            store
                .append_pairing_occurrences_v1(
                    &[second.canonical_bytes().expect("second bytes")],
                    &context("issue-rate-limited", second_at, 2_000),
                )
                .is_err(),
            "the exact live fixed window must remain exhausted"
        );

        drop(store);
        let mut store = open(temporary.path(), second_at);
        let epoch2 = store
            .begin_pairing_epoch_v1(
                &origin,
                PairingClockSample {
                    monotonic_ms: MonotonicMillis::new(0),
                    observed_at: second_at,
                },
                policy,
                &context("epoch-2", second_at, 2_000),
            )
            .expect("restart epoch");
        assert_eq!(epoch2.next_ordinal, 1);
        assert_eq!(
            epoch2.rate.issue.window_id.as_ref(),
            Some(&first.occurrence_id)
        );
        assert_eq!(epoch2.rate.issue.used, 1);
        assert_eq!(epoch2.rate.issue.expires_at, Some(first_expiry));
        assert_eq!(epoch2.invalidations.len(), 1);
        let invalidation = parse_pairing_occurrence(epoch2.invalidations[0].readback_bytes())
            .expect("exact invalidation readback");
        assert_eq!(invalidation.epoch.get(), 2);
        assert_eq!(
            invalidation.predecessor_occurrence_id,
            Some(first.occurrence_id.clone())
        );

        let after_expiry = start.checked_add_ms(12_000).expect("post-expiry wall");
        let epoch3 = store
            .begin_pairing_epoch_v1(
                &origin,
                PairingClockSample {
                    monotonic_ms: MonotonicMillis::new(0),
                    observed_at: after_expiry,
                },
                policy,
                &context("epoch-3", after_expiry, 12_000),
            )
            .expect("post-expiry epoch");
        assert!(epoch3.rate.issue.window_id.is_none());
        let next_at = after_expiry.checked_add_ms(1_000).expect("next wall");
        let next_id = pairing_occurrence_id(&origin, 3, 1);
        let next = issued(
            &origin,
            3,
            1,
            next_at,
            1_000,
            next_id,
            next_at.checked_add_ms(10_000).expect("next expiry"),
        );
        let next_bytes = next.canonical_bytes().expect("next canonical issue");
        store
            .append_pairing_occurrences_v1(
                std::slice::from_ref(&next_bytes),
                &context("issue-after-expiry", next_at, 13_000),
            )
            .expect("rate window resets after exact expiry");
        drop(store);
        let store = open(temporary.path(), next_at);
        let readback = store
            .load_pairing_occurrence_v1(&next.occurrence_id)
            .expect("load issue")
            .expect("issue exists");
        assert_eq!(readback.document_bytes, next_bytes);
    }

    #[test]
    fn pairing_ids_are_origin_bound_and_future_or_changed_bytes_never_commit() {
        let temporary = tempfile::tempdir().expect("temporary root");
        let start = wall("2026-08-18T13:00:00.000000Z");
        let policy = PairingRatePolicyV1 {
            max_failed_attempts: 2,
            attempt_window_ms: 10_000,
            max_issued_per_window: 2,
            issue_window_ms: 10_000,
        };
        let first_origin = PairingOrigin::new("http://127.0.0.1:8787").expect("first origin");
        let second_origin = PairingOrigin::new("http://localhost:8787").expect("second origin");
        let mut store = open(temporary.path(), start);
        let first = store
            .begin_pairing_epoch_v1(
                &first_origin,
                PairingClockSample {
                    monotonic_ms: MonotonicMillis::new(0),
                    observed_at: start,
                },
                policy,
                &context("origin-1", start, 0),
            )
            .expect("first origin epoch");
        let second_at = start.checked_add_ms(1).expect("second origin wall");
        let second = store
            .begin_pairing_epoch_v1(
                &second_origin,
                PairingClockSample {
                    monotonic_ms: MonotonicMillis::new(0),
                    observed_at: second_at,
                },
                policy,
                &context("origin-2", second_at, 1),
            )
            .expect("second origin epoch");
        assert_ne!(
            first.epoch_occurrence.occurrence_id(),
            second.epoch_occurrence.occurrence_id()
        );

        let observed = second_at.checked_add_ms(1_000).expect("issue wall");
        let id = pairing_occurrence_id(&first_origin, 1, 1);
        let issue = issued(
            &first_origin,
            1,
            1,
            observed,
            1_000,
            id,
            observed.checked_add_ms(10_000).expect("window expiry"),
        );
        let bytes = issue.canonical_bytes().expect("canonical issue");
        let earlier_commit = observed.checked_add_ms(1).expect("earlier commit");
        let future_issue = issued(
            &first_origin,
            1,
            2,
            observed.checked_add_ms(2).expect("future observed"),
            1_002,
            issue.occurrence_id.clone(),
            issue.rate_window_expires_at.expect("rate expiry"),
        );
        assert!(
            store
                .append_pairing_occurrences_v1(
                    &[future_issue.canonical_bytes().expect("future bytes")],
                    &context("future-refused", earlier_commit, 1_001),
                )
                .is_err()
        );
        let mut changed = bytes.clone();
        *changed.last_mut().expect("nonempty bytes") ^= 1;
        assert!(
            store
                .append_pairing_occurrences_v1(
                    &[changed],
                    &context("changed-refused", observed, 1_000),
                )
                .is_err()
        );
    }

    #[cfg(unix)]
    #[test]
    fn backup_atomic_copy_recovers_partial_restart_and_refuses_symlink_ancestors() {
        use std::os::unix::fs::symlink;

        let temporary = tempfile::tempdir().expect("temporary root");
        let source = temporary.path().join("source.bin");
        fs::write(&source, b"exact backup bytes").expect("write source");
        let digest = bytes_digest(b"exact backup bytes").expect("source digest");
        let target = temporary.path().join("reserved/artifacts/object.bin");
        let parent = target.parent().expect("target parent");
        fs::create_dir_all(parent).expect("create partial parent");
        let partial = parent.join("object.bin.joshi-g0-partial");
        fs::write(&partial, b"crash-before-rename").expect("write partial");

        copy_file_atomically(&source, &target, &digest).expect("resume exact reserved copy");
        assert!(!partial.exists());
        copy_file_atomically(&source, &target, &digest).expect("restart exact readback");
        fs::write(&target, b"wrong bytes").expect("tamper target");
        assert!(copy_file_atomically(&source, &target, &digest).is_err());

        let live = temporary.path().join("live");
        fs::create_dir_all(live.join("blobs")).expect("blob root");
        fs::create_dir_all(live.join("exports")).expect("export root");
        fs::write(live.join("catalog.sqlite"), b"catalog").expect("catalog");
        let redirected = temporary.path().join("redirected");
        fs::create_dir_all(&redirected).expect("redirect target");
        let alias = temporary.path().join("alias");
        symlink(&redirected, &alias).expect("symlink ancestor");
        assert!(
            validate_backup_destinations(
                &live.join("catalog.sqlite"),
                &live.join("blobs"),
                &live.join("exports"),
                &alias.join("backup.sqlite"),
                &temporary.path().join("reserved-root"),
            )
            .is_err()
        );

        let restored_root = temporary.path().join("restored-inventory");
        let export_root = restored_root.join("export");
        fs::create_dir_all(&export_root).expect("restored export root");
        let manifest_path = export_root.join("manifest.json");
        let snapshot_path = export_root.join("snapshot.json");
        fs::write(&manifest_path, b"exact manifest").expect("manifest bytes");
        fs::write(&snapshot_path, b"exact snapshot").expect("snapshot bytes");
        let entries = [
            BackupInventoryEntryV1 {
                root: stable_test("export"),
                relative_path: "manifest.json".into(),
                source_digest: bytes_digest(b"exact manifest").expect("manifest digest"),
                readback_digest: bytes_digest(b"exact manifest").expect("manifest digest"),
                byte_length: WireU64::new(14),
            },
            BackupInventoryEntryV1 {
                root: stable_test("export"),
                relative_path: "snapshot.json".into(),
                source_digest: bytes_digest(b"exact snapshot").expect("snapshot digest"),
                readback_digest: bytes_digest(b"exact snapshot").expect("snapshot digest"),
                byte_length: WireU64::new(14),
            },
        ];
        verify_exact_inventory_tree(&restored_root, &entries).expect("exact restored paths");
        verify_inventory_entry_readbacks(&restored_root, &entries).expect("exact restored bytes");
        fs::write(&snapshot_path, b"tampered snap!").expect("tamper snapshot");
        assert!(verify_inventory_entry_readbacks(&restored_root, &entries).is_err());
    }
}
