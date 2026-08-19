//! Sole-store append/readback for browser-reported Cockpit V2 presentation evidence.

use crate::{
    IdempotencyStatus, Result, SqliteStore, StoreError,
    wave6::{digest_bytes, raw_digest, sqlite_len, sqlite_u64, stable, u64_from_i64},
};
use joshi_domain::{CommitSeq, StableString, UtcTimestamp, ValueDigest};
use joshi_pairing::{PairingScope, PairingSessionDescriptor};
use joshi_publication::{
    CockpitPublicationId, CockpitV2BrowserPresentationClaimV1, CockpitV2DocumentVisibility,
    parse_cockpit_v2_browser_presentation_claim, parse_cockpit_v2_head,
    parse_cockpit_v2_publication,
};
use rusqlite::{OptionalExtension as _, params};
use serde::Serialize;

const MAX_CLAIM_BYTES: usize = 64 * 1024;
const AUTHORITY: &str = "read_only_no_execution";
const CEILING: &str = "browser_reported_not_pixel_verified";

type HeadedPublicationRow = (Vec<u8>, String, String, i64, String, Vec<u8>, String, i64);
type PresentationClaimScalarRow = (
    String,
    String,
    String,
    String,
    i64,
    i64,
    i64,
    String,
    String,
    i64,
    i64,
    i64,
    String,
    bool,
    String,
    String,
);

/// Exact browser claim reloaded from its sole-store append.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredCockpitV2BrowserPresentation {
    pub batch_id: StableString,
    pub claim: CockpitV2BrowserPresentationClaimV1,
    pub claim_bytes: Vec<u8>,
    pub claim_bytes_digest: ValueDigest,
    pub pairing_consumed_occurrence_id: StableString,
    pub pairing_session_id: StableString,
    pub pairing_origin: StableString,
    pub pairing_epoch: u64,
    pub commit_seq: CommitSeq,
    pub commit_digest: ValueDigest,
}

/// Store-owned receipt for one accepted or exactly retried browser presentation claim.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CockpitV2BrowserPresentationCommitReceipt {
    catalog_id: StableString,
    catalog_schema: StableString,
    client_presentation_id: StableString,
    claim_digest: ValueDigest,
    claim_bytes_digest: ValueDigest,
    pairing_session_id: StableString,
    publication_id: CockpitPublicationId,
    commit_seq: CommitSeq,
    status: IdempotencyStatus,
}

impl CockpitV2BrowserPresentationCommitReceipt {
    #[must_use]
    pub const fn catalog_id(&self) -> &StableString {
        &self.catalog_id
    }

    #[must_use]
    pub const fn catalog_schema(&self) -> &StableString {
        &self.catalog_schema
    }

    #[must_use]
    pub const fn client_presentation_id(&self) -> &StableString {
        &self.client_presentation_id
    }

    #[must_use]
    pub const fn claim_digest(&self) -> &ValueDigest {
        &self.claim_digest
    }

    #[must_use]
    pub const fn claim_bytes_digest(&self) -> &ValueDigest {
        &self.claim_bytes_digest
    }

    #[must_use]
    pub const fn pairing_session_id(&self) -> &StableString {
        &self.pairing_session_id
    }

    #[must_use]
    pub const fn publication_id(&self) -> &CockpitPublicationId {
        &self.publication_id
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

impl SqliteStore {
    /// Strictly parses, transactionally resolves, appends, and rereads one browser presentation.
    ///
    /// The pairing descriptor must come from the mounted ordinary authorizer. The store resolves
    /// its exact consumed occurrence and required write scope inside the same immediate transaction
    /// that binds the canonical claim to the headed publication.
    ///
    /// # Errors
    ///
    /// Refuses noncanonical/oversized claims, missing or terminal pairing sessions, a body/head or
    /// source substitution, a conflicting idempotency identity, and any postcommit readback drift.
    #[allow(clippy::too_many_lines)]
    pub fn commit_cockpit_v2_browser_presentation_v1(
        &mut self,
        claim_bytes: &[u8],
        session: &PairingSessionDescriptor,
        writer_build: StableString,
    ) -> Result<CockpitV2BrowserPresentationCommitReceipt> {
        self.require_writer()?;
        if claim_bytes.is_empty() || claim_bytes.len() > MAX_CLAIM_BYTES {
            return Err(StoreError::InvalidBatch(
                "browser presentation claim exceeds its exact-byte bound".into(),
            ));
        }
        let claim =
            parse_cockpit_v2_browser_presentation_claim(claim_bytes).map_err(contract_error)?;
        session.validate().map_err(contract_error)?;
        if !session
            .scopes
            .contains(&PairingScope::PresentationEvidenceWrite)
        {
            return Err(StoreError::InvalidBatch(
                "paired session lacks presentation evidence scope".into(),
            ));
        }
        let claim_bytes_digest = digest_bytes(claim_bytes)?;
        let operation_digest = digest_json(&(
            "joshi.store.cockpit_v2_browser_presentation_commit.v1",
            claim.claim_digest.as_str(),
            claim_bytes_digest.as_str(),
            session.session_id.as_str(),
            session.origin.as_str(),
            session.epoch.get(),
            session.expires_at,
            &session.scopes,
        ))?;
        let context = self.begin_wave5_commit(claim.idempotency_key.clone(), writer_build)?;
        let client_presentation_id = claim.client_presentation_id.clone();
        let exact_claim_digest = claim.claim_digest.clone();
        let generic = self.commit_wave5(
            &context,
            "command",
            &client_presentation_id,
            &exact_claim_digest,
            &operation_digest,
            |tx, seq| {
                let headed: Option<HeadedPublicationRow> = tx
                    .query_row(
                        "SELECT publication.publication_bytes,publication.publication_sha256,
                                publication.publication_bytes_sha256,
                                publication.created_commit_seq,publication.source_occurrence_id,
                                head.head_bytes,head.head_sha256,head.created_commit_seq
                         FROM cockpit_v2_publication_v1 publication
                         JOIN cockpit_v2_head_v1 head
                           ON head.publication_id=publication.publication_id
                         WHERE publication.publication_id=?1",
                        [claim.publication.publication_id.as_str()],
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
                    publication_bytes,
                    publication_raw,
                    publication_bytes_raw,
                    publication_seq,
                    source_occurrence_id,
                    head_bytes,
                    head_raw,
                    head_seq,
                )) = headed
                else {
                    return Err(StoreError::MissingIdentity {
                        kind: "headed Cockpit V2 publication",
                        identity: claim.publication.publication_id.to_string(),
                    });
                };
                let publication =
                    parse_cockpit_v2_publication(&publication_bytes).map_err(contract_error)?;
                let head = parse_cockpit_v2_head(&head_bytes).map_err(contract_error)?;
                let publication_commit = CommitSeq::new(u64_from_i64(
                    publication_seq,
                    "browser presentation publication commit",
                )?);
                let head_commit =
                    CommitSeq::new(u64_from_i64(head_seq, "browser presentation head commit")?);
                let source_occurrence_id = stable(
                    &source_occurrence_id,
                    "browser presentation source occurrence",
                )?;
                claim
                    .validate_against(
                        &publication,
                        &publication_bytes,
                        publication_commit,
                        &head,
                        &head_bytes,
                        head_commit,
                        &source_occurrence_id,
                    )
                    .map_err(contract_error)?;
                if publication_raw
                    != raw_digest(&publication.publication_digest, "Cockpit publication")?
                    || publication_bytes_raw
                        != raw_digest(&digest_bytes(&publication_bytes)?, "Cockpit body bytes")?
                    || head_raw != raw_digest(&head.head_digest, "Cockpit head")?
                {
                    return Err(StoreError::InvalidBatch(
                        "headed Cockpit V2 SQL digest columns differ from exact bytes".into(),
                    ));
                }

                let consumed: Option<(String, String, i64, i64, i64, String, i64)> = tx
                    .query_row(
                        "SELECT pairing_occurrence_id,origin,epoch,observed_wall_us,
                                expires_wall_us,scopes_json,created_commit_seq
                         FROM wave5_g0_pairing_occurrence_v1
                         WHERE occurrence_kind='consumed' AND session_id=?1",
                        [session.session_id.as_str()],
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
                    consumed_id,
                    origin,
                    epoch,
                    consumed_wall_us,
                    expires_wall_us,
                    scopes_json,
                    consumed_seq,
                )) = consumed
                else {
                    return Err(StoreError::MissingIdentity {
                        kind: "paired consumed session",
                        identity: session.session_id.to_string(),
                    });
                };
                let scopes: Vec<PairingScope> = serde_json::from_str(&scopes_json)?;
                let committed_wall_us: i64 = tx.query_row(
                    "SELECT committed_wall_us FROM ingest_commit WHERE commit_seq=?1",
                    [seq],
                    |row| row.get(0),
                )?;
                let terminal: bool = tx.query_row(
                    "SELECT EXISTS(
                       SELECT 1 FROM wave5_g0_pairing_occurrence_v1
                       WHERE predecessor_occurrence_id=?1
                         AND occurrence_kind IN ('revoked','expired','restart_invalidated')
                         AND created_commit_seq<=?2
                     )",
                    params![consumed_id, seq],
                    |row| row.get(0),
                )?;
                let mounted_wall_us = timestamp_us(claim.mounted_at, "presentation mounted_at")?;
                if origin != session.origin.as_str()
                    || u64_from_i64(epoch, "browser presentation pairing epoch")?
                        != session.epoch.get()
                    || scopes != session.scopes
                    || timestamp_us(session.expires_at.get(), "paired session expiry")?
                        != expires_wall_us
                    || consumed_seq >= seq
                    || mounted_wall_us < consumed_wall_us
                    || mounted_wall_us > committed_wall_us
                    || committed_wall_us > expires_wall_us
                    || terminal
                {
                    return Err(StoreError::InvalidBatch(
                        "paired presentation session is foreign, terminal, or expired".into(),
                    ));
                }
                let consumed_id = stable(&consumed_id, "pairing consumed occurrence")?;
                tx.execute(
                    "INSERT INTO cockpit_v2_browser_presentation_v1
                     (client_presentation_id,idempotency_key,browser_page_id,presentation_seq,
                      pairing_consumed_occurrence_id,pairing_session_id,pairing_origin,
                      pairing_epoch,publication_id,publication_sha256,publication_bytes_sha256,
                      publication_commit_seq,head_sha256,head_bytes_sha256,head_commit_seq,
                      source_occurrence_id,claim_contract,claim_schema_version,claim_sha256,
                      claim_bytes_sha256,claim_bytes,claim_byte_length,rendered_subject_count,
                      mounted_wall_us,client_clock_id,mounted_mono_ns,viewport_width_css_px,
                      viewport_height_css_px,device_pixel_ratio_milli,document_visibility,
                      document_has_focus,authority,ceiling,created_commit_seq)
                     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,
                             ?17,?18,?19,?20,?21,?22,?23,?24,?25,?26,?27,?28,?29,?30,
                             ?31,?32,?33,?34)",
                    params![
                        claim.client_presentation_id.as_str(),
                        claim.idempotency_key.as_str(),
                        claim.browser_page_id.as_str(),
                        claim.presentation_seq.get().to_string(),
                        consumed_id.as_str(),
                        session.session_id.as_str(),
                        session.origin.as_str(),
                        sqlite_u64(session.epoch.get(), "pairing epoch")?,
                        claim.publication.publication_id.as_str(),
                        raw_digest(&claim.publication.publication_digest, "publication")?,
                        raw_digest(
                            &claim.publication.publication_bytes_digest,
                            "publication bytes"
                        )?,
                        sqlite_u64(
                            claim.publication.publication_commit_seq.get(),
                            "publication commit"
                        )?,
                        raw_digest(&claim.head.head_digest, "head")?,
                        raw_digest(&claim.head.head_bytes_digest, "head bytes")?,
                        sqlite_u64(claim.head.head_commit_seq.get(), "head commit")?,
                        claim.source_occurrence_id.as_str(),
                        claim.contract.as_str(),
                        i64::from(claim.schema_version),
                        raw_digest(&claim.claim_digest, "presentation claim")?,
                        raw_digest(&claim_bytes_digest, "presentation claim bytes")?,
                        claim_bytes,
                        sqlite_len(claim_bytes.len(), "presentation claim bytes")?,
                        sqlite_len(
                            claim.rendered_subjects.len(),
                            "presentation rendered subjects"
                        )?,
                        mounted_wall_us,
                        claim.client_clock_id.as_str(),
                        claim.monotonic_ns.get().to_string(),
                        sqlite_u64(claim.viewport.width_css_px.get(), "viewport width")?,
                        sqlite_u64(claim.viewport.height_css_px.get(), "viewport height")?,
                        sqlite_u64(
                            claim.viewport.device_pixel_ratio_milli.get(),
                            "device pixel ratio"
                        )?,
                        visibility_text(claim.document_visibility),
                        claim.document_has_focus,
                        AUTHORITY,
                        CEILING,
                        seq,
                    ],
                )?;
                Ok(())
            },
        )?;
        let stored = self
            .load_cockpit_v2_browser_presentation_v1(&client_presentation_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "browser presentation",
                identity: client_presentation_id.to_string(),
            })?;
        if stored.claim != claim
            || stored.claim_bytes != claim_bytes
            || stored.claim_bytes_digest != claim_bytes_digest
            || stored.pairing_session_id != session.session_id
            || stored.pairing_origin.as_str() != session.origin.as_str()
            || stored.pairing_epoch != session.epoch.get()
            || stored.commit_seq != generic.commit_seq
        {
            return Err(StoreError::InvalidBatch(
                "browser presentation postcommit readback differs from exact request".into(),
            ));
        }
        Ok(CockpitV2BrowserPresentationCommitReceipt {
            catalog_id: generic.catalog_id,
            catalog_schema: generic.catalog_schema,
            client_presentation_id,
            claim_digest: exact_claim_digest,
            claim_bytes_digest,
            pairing_session_id: session.session_id.clone(),
            publication_id: claim.publication.publication_id,
            commit_seq: generic.commit_seq,
            status: generic.status,
        })
    }

    /// Reloads and revalidates one exact browser presentation occurrence.
    ///
    /// # Errors
    ///
    /// Refuses malformed bytes, scalar/digest drift, broken body/head lineage, a foreign pairing
    /// session, or a terminal transition that predates the presentation commit.
    #[allow(clippy::too_many_lines)]
    pub fn load_cockpit_v2_browser_presentation_v1(
        &self,
        client_presentation_id: &StableString,
    ) -> Result<Option<StoredCockpitV2BrowserPresentation>> {
        type Row = (
            String,
            String,
            String,
            i64,
            String,
            i64,
            String,
            String,
            i64,
            String,
            String,
            i64,
            String,
            String,
            Vec<u8>,
            i64,
            String,
            i64,
            i64,
            String,
            String,
        );
        let row: Option<Row> = self
            .connection
            .query_row(
                "SELECT presentation.idempotency_key,presentation.pairing_consumed_occurrence_id,
                        presentation.pairing_session_id,presentation.pairing_epoch,
                        presentation.pairing_origin,presentation.publication_commit_seq,
                        presentation.publication_sha256,presentation.publication_bytes_sha256,
                        presentation.head_commit_seq,presentation.head_sha256,
                        presentation.head_bytes_sha256,presentation.created_commit_seq,
                        presentation.claim_sha256,presentation.claim_bytes_sha256,
                        presentation.claim_bytes,presentation.claim_byte_length,
                        presentation.source_occurrence_id,commit_row.commit_seq,
                        commit_row.committed_wall_us,commit_row.commit_id,
                        commit_row.commit_digest
                 FROM cockpit_v2_browser_presentation_v1 presentation
                 JOIN ingest_commit commit_row
                   ON commit_row.commit_seq=presentation.created_commit_seq
                 WHERE presentation.client_presentation_id=?1",
                [client_presentation_id.as_str()],
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
                        row.get(17)?,
                        row.get(18)?,
                        row.get(19)?,
                        row.get(20)?,
                    ))
                },
            )
            .optional()?;
        let Some((
            batch_id,
            consumed_id,
            session_id,
            epoch,
            origin,
            publication_seq,
            publication_raw,
            publication_bytes_raw,
            head_seq,
            head_raw,
            head_bytes_raw,
            created_seq,
            claim_raw,
            claim_bytes_raw,
            claim_bytes,
            claim_len,
            source_occurrence_id,
            commit_seq,
            committed_wall_us,
            commit_id,
            commit_digest,
        )) = row
        else {
            return Ok(None);
        };
        let claim =
            parse_cockpit_v2_browser_presentation_claim(&claim_bytes).map_err(contract_error)?;
        let claim_bytes_digest = digest_bytes(&claim_bytes)?;
        let scalars: PresentationClaimScalarRow = self.connection.query_row(
            "SELECT client_presentation_id,browser_page_id,presentation_seq,claim_contract,
                    claim_schema_version,rendered_subject_count,mounted_wall_us,client_clock_id,
                    mounted_mono_ns,viewport_width_css_px,viewport_height_css_px,
                    device_pixel_ratio_milli,document_visibility,document_has_focus,
                    authority,ceiling
             FROM cockpit_v2_browser_presentation_v1
             WHERE client_presentation_id=?1",
            [client_presentation_id.as_str()],
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
            scalar_client_id,
            browser_page_id,
            presentation_seq,
            claim_contract,
            claim_schema_version,
            rendered_subject_count,
            stored_mounted_wall_us,
            client_clock_id,
            mounted_mono_ns,
            viewport_width,
            viewport_height,
            device_pixel_ratio,
            document_visibility,
            document_has_focus,
            authority,
            ceiling,
        ) = scalars;
        let mounted_wall_us = timestamp_us(claim.mounted_at, "presentation mounted_at")?;
        if scalar_client_id != client_presentation_id.as_str()
            || scalar_client_id != claim.client_presentation_id.as_str()
            || browser_page_id != claim.browser_page_id.as_str()
            || presentation_seq != claim.presentation_seq.get().to_string()
            || claim_contract != claim.contract.as_str()
            || claim_schema_version != i64::from(claim.schema_version)
            || rendered_subject_count
                != sqlite_len(
                    claim.rendered_subjects.len(),
                    "presentation rendered subjects",
                )?
            || stored_mounted_wall_us != mounted_wall_us
            || client_clock_id != claim.client_clock_id.as_str()
            || mounted_mono_ns != claim.monotonic_ns.get().to_string()
            || viewport_width
                != sqlite_u64(
                    claim.viewport.width_css_px.get(),
                    "presentation viewport width",
                )?
            || viewport_height
                != sqlite_u64(
                    claim.viewport.height_css_px.get(),
                    "presentation viewport height",
                )?
            || device_pixel_ratio
                != sqlite_u64(
                    claim.viewport.device_pixel_ratio_milli.get(),
                    "presentation device pixel ratio",
                )?
            || document_visibility != visibility_text(claim.document_visibility)
            || document_has_focus != claim.document_has_focus
            || authority != AUTHORITY
            || ceiling != CEILING
            || batch_id != claim.idempotency_key.as_str()
            || commit_id != batch_id
            || claim_len != sqlite_len(claim_bytes.len(), "presentation claim readback")?
            || claim_raw != raw_digest(&claim.claim_digest, "presentation claim")?
            || claim_bytes_raw
                != raw_digest(&claim_bytes_digest, "presentation claim readback bytes")?
            || publication_raw != raw_digest(&claim.publication.publication_digest, "publication")?
            || publication_bytes_raw
                != raw_digest(
                    &claim.publication.publication_bytes_digest,
                    "publication bytes",
                )?
            || head_raw != raw_digest(&claim.head.head_digest, "head")?
            || head_bytes_raw != raw_digest(&claim.head.head_bytes_digest, "head bytes")?
            || source_occurrence_id != claim.source_occurrence_id.as_str()
            || publication_seq
                != sqlite_u64(
                    claim.publication.publication_commit_seq.get(),
                    "publication commit",
                )?
            || head_seq != sqlite_u64(claim.head.head_commit_seq.get(), "head commit")?
            || created_seq != commit_seq
            || created_seq <= head_seq
        {
            return Err(StoreError::InvalidBatch(
                "browser presentation scalar readback differs from exact claim bytes".into(),
            ));
        }
        let publication = self
            .load_cockpit_v2_publication_v1(&claim.publication.publication_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Cockpit V2 publication",
                identity: claim.publication.publication_id.to_string(),
            })?;
        let head = self
            .load_cockpit_v2_head_v1(&claim.publication.publication_id)?
            .ok_or_else(|| StoreError::MissingIdentity {
                kind: "Cockpit V2 head",
                identity: claim.publication.publication_id.to_string(),
            })?;
        claim
            .validate_against(
                &publication.publication,
                &publication.publication_bytes,
                publication.commit_seq,
                &head.head,
                &head.head_bytes,
                head.commit_seq,
                &publication.source_occurrence_id,
            )
            .map_err(contract_error)?;
        let pairing: Option<(String, i64, i64, i64, String)> = self
            .connection
            .query_row(
                "SELECT origin,epoch,observed_wall_us,expires_wall_us,scopes_json
                 FROM wave5_g0_pairing_occurrence_v1
                 WHERE pairing_occurrence_id=?1 AND occurrence_kind='consumed'
                   AND session_id=?2",
                params![consumed_id, session_id],
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
        let Some((paired_origin, paired_epoch, paired_wall_us, expires_wall_us, scopes_json)) =
            pairing
        else {
            return Err(StoreError::InvalidBatch(
                "browser presentation pairing predecessor is absent".into(),
            ));
        };
        let scopes: Vec<PairingScope> = serde_json::from_str(&scopes_json)?;
        let terminal_before: bool = self.connection.query_row(
            "SELECT EXISTS(
               SELECT 1 FROM wave5_g0_pairing_occurrence_v1
               WHERE predecessor_occurrence_id=?1
                 AND occurrence_kind IN ('revoked','expired','restart_invalidated')
                 AND created_commit_seq<=?2
             )",
            params![consumed_id, created_seq],
            |row| row.get(0),
        )?;
        if paired_origin != origin
            || paired_epoch != epoch
            || !scopes.contains(&PairingScope::PresentationEvidenceWrite)
            || mounted_wall_us < paired_wall_us
            || mounted_wall_us > committed_wall_us
            || committed_wall_us > expires_wall_us
            || terminal_before
        {
            return Err(StoreError::InvalidBatch(
                "browser presentation pairing readback was not active at commit".into(),
            ));
        }
        Ok(Some(StoredCockpitV2BrowserPresentation {
            batch_id: stable(&batch_id, "presentation batch")?,
            claim,
            claim_bytes,
            claim_bytes_digest,
            pairing_consumed_occurrence_id: stable(
                &consumed_id,
                "presentation pairing occurrence",
            )?,
            pairing_session_id: stable(&session_id, "presentation pairing session")?,
            pairing_origin: stable(&origin, "presentation pairing origin")?,
            pairing_epoch: u64_from_i64(epoch, "presentation pairing epoch")?,
            commit_seq: CommitSeq::new(u64_from_i64(created_seq, "presentation commit")?),
            commit_digest: ValueDigest::new(format!("sha256:{commit_digest}"))
                .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
        }))
    }
}

fn visibility_text(value: CockpitV2DocumentVisibility) -> &'static str {
    match value {
        CockpitV2DocumentVisibility::Visible => "visible",
        CockpitV2DocumentVisibility::Hidden => "hidden",
    }
}

fn timestamp_us(value: UtcTimestamp, field: &'static str) -> Result<i64> {
    let nanos = value.as_datetime().unix_timestamp_nanos();
    if nanos % 1_000 != 0 {
        return Err(StoreError::TimestampRange { field });
    }
    let micros: i64 = (nanos / 1_000)
        .try_into()
        .map_err(|_| StoreError::TimestampRange { field })?;
    if micros <= 0 {
        return Err(StoreError::TimestampRange { field });
    }
    Ok(micros)
}

fn contract_error(error: impl std::fmt::Display) -> StoreError {
    StoreError::InvalidBatch(format!("browser presentation contract: {error}"))
}

fn digest_json(value: &impl Serialize) -> Result<ValueDigest> {
    digest_bytes(&serde_json::to_vec(value)?)
}
