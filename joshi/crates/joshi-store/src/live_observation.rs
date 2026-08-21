//! Typed read-back of durable source observations as known at an exact catalog cutoff.
//!
//! This is deliberately not a general SQL-to-analysis projection API. It returns exactly the
//! observation identities, clocks, chain coordinates and retained provider bytes that a renderer
//! needs in order to name a real occurrence, and nothing that would let a caller invent one.

use crate::{
    error::{Result, StoreError},
    store::{SqliteStore, load_blob_object},
};
use joshi_domain::{CommitSeq, SourceId, StableString, UtcTimestamp};
use rusqlite::{OptionalExtension as _, params};

/// Exact column tuple one observation readback row carries.
type ObservationRow = (
    String,
    i64,
    String,
    String,
    String,
    Option<String>,
    i64,
    i64,
    Option<i64>,
    Option<i64>,
    Option<i64>,
    Option<String>,
    String,
    Option<String>,
    String,
    String,
);

/// Exact column tuple one operator-command readback row carries.
type CommandRow = (
    String,
    i64,
    Option<String>,
    Option<String>,
    String,
    i64,
    String,
    String,
    String,
    String,
    i64,
    i64,
    String,
    String,
    String,
    String,
    String,
);

/// One durable observation, as known at a cutoff, with its exact retained payload bytes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableSourceObservation {
    pub observation_id: StableString,
    pub commit_seq: CommitSeq,
    pub source_id: SourceId,
    pub acquisition_id: StableString,
    pub observation_kind: String,
    /// Redacted logical locator recorded by the acquisition (never a URL or a secret).
    pub source_locator_redacted: Option<String>,
    /// Acquisition receive clock (`ingestedAt` in Glass terms).
    pub received_at: UtcTimestamp,
    /// Knowledge-availability clock (`knownAt` in Glass terms).
    pub available_at: UtcTimestamp,
    /// Lower bound of the provider event clock, when the provider stated one.
    pub source_event_lower: Option<UtcTimestamp>,
    /// Upper bound of the provider event clock, when the provider stated one.
    pub source_event_upper: Option<UtcTimestamp>,
    pub chain_slot: Option<u64>,
    pub chain_commitment: Option<String>,
    pub parse_disposition: String,
    /// Exact stored refusal/quality note, when the adapter recorded one.
    pub quality_code: Option<String>,
    /// Exact retained bytes for the observation payload.
    pub payload: Vec<u8>,
}

/// Every observation one source delivered through an exact durable cutoff.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableSourceObservations {
    pub source_id: SourceId,
    /// Cutoff the read was resolved against.
    pub through_commit_seq: CommitSeq,
    /// Wall clock of the commit named by `through_commit_seq`.
    pub through_committed_at: UtcTimestamp,
    /// Highest commit that actually carries an observation from this source at the cutoff.
    pub delivered_through: CommitSeq,
    pub observations: Vec<DurableSourceObservation>,
    /// True when the source has more observations at the cutoff than `limit` allowed.
    pub truncated: bool,
}

impl SqliteStore {
    /// Reads durable observations for one source as known at an exact cutoff.
    ///
    /// `cutoff` of `None` resolves to the highest durable commit. Returns `Ok(None)` when the
    /// source delivered nothing at or before the cutoff; an empty result is never reported as an
    /// absence claim about the world.
    ///
    /// # Errors
    ///
    /// Fails on a missing cutoff commit, stored clock/blob corruption, or `SQLite` errors.
    #[allow(clippy::too_many_lines)] // One readback keeps its column closure visible in one place.
    pub fn source_observations_as_known(
        &self,
        source_id: &SourceId,
        cutoff: Option<CommitSeq>,
        limit: usize,
    ) -> Result<Option<DurableSourceObservations>> {
        let cutoff = match cutoff {
            Some(value) => value,
            None => self.max_commit_seq()?,
        };
        if cutoff.get() == 0 || limit == 0 {
            return Ok(None);
        }
        let cutoff_us = sqlite_u64(cutoff.get(), "observation cutoff")?;
        let committed_wall_us: Option<i64> = self
            .connection
            .query_row(
                "SELECT committed_wall_us FROM ingest_commit WHERE commit_seq=?1",
                [cutoff_us],
                |row| row.get(0),
            )
            .optional()?;
        let Some(committed_wall_us) = committed_wall_us else {
            return Err(StoreError::MissingIdentity {
                kind: "durable commit",
                identity: cutoff.get().to_string(),
            });
        };
        let through_committed_at = timestamp_from_us(committed_wall_us, "cutoff committed_at")?;

        let total: i64 = self.connection.query_row(
            "SELECT COUNT(*) FROM observation WHERE source_id=?1 AND commit_seq<=?2",
            params![source_id.as_str(), cutoff_us],
            |row| row.get(0),
        )?;
        if total == 0 {
            return Ok(None);
        }
        let limit_rows = i64::try_from(limit).unwrap_or(i64::MAX);

        let mut statement = self.connection.prepare(
            "SELECT o.observation_id,o.commit_seq,o.source_id,o.acquisition_id,o.observation_kind,
                    a.source_locator_redacted,o.received_wall_us,o.available_wall_us,
                    o.source_event_lower_us,o.source_event_upper_us,o.chain_slot,
                    o.chain_commitment,o.parse_disposition,o.quality_code,
                    o.blob_id,c.storage_domain
             FROM observation o
             JOIN acquisition a ON a.acquisition_id=o.acquisition_id
             JOIN observation_blob_contract c ON c.observation_id=o.observation_id
             WHERE o.source_id=?1 AND o.commit_seq<=?2
             ORDER BY o.commit_seq,o.intra_commit_seq
             LIMIT ?3",
        )?;
        let rows = statement
            .query_map(params![source_id.as_str(), cutoff_us, limit_rows], |row| {
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
            })?
            .collect::<std::result::Result<Vec<ObservationRow>, rusqlite::Error>>()?;

        let mut observations = Vec::with_capacity(rows.len());
        let mut delivered_through = 0_u64;
        for row in rows {
            let (
                observation_id,
                commit_seq,
                row_source_id,
                acquisition_id,
                observation_kind,
                source_locator_redacted,
                received_wall_us,
                available_wall_us,
                source_event_lower_us,
                source_event_upper_us,
                chain_slot,
                chain_commitment,
                parse_disposition,
                quality_code,
                blob_id,
                storage_domain,
            ) = row;
            let commit_seq = as_u64(commit_seq, "observation commit_seq")?;
            delivered_through = delivered_through.max(commit_seq);
            let payload = load_blob_object(
                &self.connection,
                &self.config.blob_root,
                &blob_id,
                &storage_domain,
            )?;
            observations.push(DurableSourceObservation {
                observation_id: stable(observation_id, "observation identity")?,
                commit_seq: CommitSeq::new(commit_seq),
                source_id: SourceId::new(row_source_id)
                    .map_err(|error| StoreError::InvalidBatch(error.to_string()))?,
                acquisition_id: stable(acquisition_id, "acquisition identity")?,
                observation_kind,
                source_locator_redacted,
                received_at: timestamp_from_us(received_wall_us, "observation received_at")?,
                available_at: timestamp_from_us(available_wall_us, "observation available_at")?,
                source_event_lower: source_event_lower_us
                    .map(|value| timestamp_from_us(value, "observation source event lower"))
                    .transpose()?,
                source_event_upper: source_event_upper_us
                    .map(|value| timestamp_from_us(value, "observation source event upper"))
                    .transpose()?,
                chain_slot: chain_slot
                    .map(|value| as_u64(value, "observation chain slot"))
                    .transpose()?,
                chain_commitment,
                parse_disposition,
                quality_code,
                payload,
            });
        }
        if observations.is_empty() {
            return Ok(None);
        }
        Ok(Some(DurableSourceObservations {
            source_id: source_id.clone(),
            through_commit_seq: cutoff,
            through_committed_at,
            delivered_through: CommitSeq::new(delivered_through),
            truncated: total > i64::try_from(observations.len()).unwrap_or(i64::MAX),
            observations,
        }))
    }
}

fn stable(value: String, field: &'static str) -> Result<StableString> {
    StableString::new(value).map_err(|error| StoreError::InvalidBatch(format!("{field}: {error}")))
}

fn sqlite_u64(value: u64, field: &'static str) -> Result<i64> {
    i64::try_from(value).map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn as_u64(value: i64, field: &'static str) -> Result<u64> {
    u64::try_from(value).map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

fn timestamp_from_us(value: i64, field: &'static str) -> Result<UtcTimestamp> {
    let nanos = i128::from(value)
        .checked_mul(1_000)
        .ok_or(StoreError::IntegerRange {
            field,
            value: value.to_string(),
        })?;
    let datetime = time::OffsetDateTime::from_unix_timestamp_nanos(nanos).map_err(|_| {
        StoreError::IntegerRange {
            field,
            value: value.to_string(),
        }
    })?;
    UtcTimestamp::new(datetime).map_err(|_| StoreError::IntegerRange {
        field,
        value: value.to_string(),
    })
}

/// One durable operator command read back after restart, with the scene bytes it was bound to.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredOperatorCommandV1 {
    pub command_id: StableString,
    pub commit_seq: CommitSeq,
    pub scene_id: Option<StableString>,
    /// SHA-256 of the exact view bytes the bound scene retains, without the `sha256:` prefix.
    pub scene_view_sha256: Option<String>,
    pub client_session_id: StableString,
    pub client_command_seq: u64,
    pub idempotency_key: StableString,
    pub command_kind: String,
    pub subject_kind: String,
    pub subject_key: String,
    pub issued_at: UtcTimestamp,
    pub received_at: UtcTimestamp,
    pub client_clock_id: String,
    pub effect_ceiling: String,
    pub authority_class: String,
    /// Exact retained command payload bytes.
    pub payload: Vec<u8>,
}

impl SqliteStore {
    /// Reads every durable operator command bound to one immutable scene, in commit order.
    ///
    /// # Errors
    ///
    /// Fails on stored clock/blob corruption or `SQLite` errors.
    #[allow(clippy::too_many_lines)] // One readback keeps its column closure visible in one place.
    pub fn operator_commands_for_scene_v1(
        &self,
        scene_id: &joshi_domain::SceneId,
    ) -> Result<Vec<StoredOperatorCommandV1>> {
        let mut statement = self.connection.prepare(
            "SELECT c.command_id,c.committed_commit_seq,c.scene_id,s.view_sha256,
                    c.client_session_id,c.client_command_seq,c.idempotency_key,c.command_kind,
                    c.subject_kind,c.subject_key,c.issued_wall_us,c.received_wall_us,
                    c.client_clock_id,c.effect_ceiling,c.authority_class,
                    p.blob_id,p.storage_domain
             FROM command c
             LEFT JOIN scene s ON s.scene_id=c.scene_id
             JOIN command_payload_contract p ON p.command_id=c.command_id
             WHERE c.scene_id=?1
             ORDER BY c.committed_commit_seq,c.command_id",
        )?;
        let rows = statement
            .query_map([scene_id.as_str()], |row| {
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
            })?
            .collect::<std::result::Result<Vec<CommandRow>, rusqlite::Error>>()?;
        let mut commands = Vec::with_capacity(rows.len());
        for row in rows {
            let (
                command_id,
                commit_seq,
                bound_scene_id,
                scene_view_sha256,
                client_session_id,
                client_command_seq,
                idempotency_key,
                command_kind,
                subject_kind,
                subject_key,
                issued_wall_us,
                received_wall_us,
                client_clock_id,
                effect_ceiling,
                authority_class,
                blob_id,
                storage_domain,
            ) = row;
            let payload = load_blob_object(
                &self.connection,
                &self.config.blob_root,
                &blob_id,
                &storage_domain,
            )?;
            commands.push(StoredOperatorCommandV1 {
                command_id: stable(command_id, "command identity")?,
                commit_seq: CommitSeq::new(as_u64(commit_seq, "command commit_seq")?),
                scene_id: bound_scene_id
                    .map(|value| stable(value, "command scene identity"))
                    .transpose()?,
                scene_view_sha256,
                client_session_id: stable(client_session_id, "command session identity")?,
                client_command_seq: as_u64(client_command_seq, "client command seq")?,
                idempotency_key: stable(idempotency_key, "command idempotency key")?,
                command_kind,
                subject_kind,
                subject_key,
                issued_at: timestamp_from_us(issued_wall_us, "command issued_at")?,
                received_at: timestamp_from_us(received_wall_us, "command received_at")?,
                client_clock_id,
                effect_ceiling,
                authority_class,
                payload,
            });
        }
        Ok(commands)
    }
}
