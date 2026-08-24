//! Typed read-back of durable source observations as known at an exact catalog cutoff.
//!
//! This is deliberately not a general SQL-to-analysis projection API. It returns exactly the
//! observation identities, clocks, chain coordinates and retained provider bytes that a renderer
//! needs in order to name a real occurrence, and nothing that would let a caller invent one.
//!
//! Two bounded reads share one row shape and differ in which end of the history their window
//! anchors to: [`SqliteStore::source_observations_as_known`] returns the oldest window (a stable
//! prefix, for readback paths that re-walk history from its beginning), and
//! [`SqliteStore::source_observations_newest_as_known`] returns the newest window with the
//! source's true delivered-through watermark (for live surfaces, whose cutoff must keep moving
//! however large the catalog grows).

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
    /// The watermark this read stands behind, and the two reads mean different things by it.
    ///
    /// [`SqliteStore::source_observations_newest_as_known`] puts the source's TRUE watermark
    /// here: the highest commit at or before the cutoff that carries an observation from this
    /// source, regardless of `limit`. [`SqliteStore::source_observations_as_known`] puts the
    /// highest commit of its returned window here, which sits BELOW the true watermark whenever
    /// the window is truncated — the historical prefix semantics its readback callers hold.
    pub delivered_through: CommitSeq,
    pub observations: Vec<DurableSourceObservation>,
    /// True when the source has more observations at the cutoff than `limit` allowed.
    pub truncated: bool,
    /// How many observations at or before the cutoff `limit` left out of `observations`.
    ///
    /// A render/readback window bound, never an absence claim: the catalog retains every elided
    /// observation and a wider or explicit-cutoff read still reaches it. Zero exactly when
    /// `truncated` is false.
    pub elided: u64,
}

/// Which end of the source's history a bounded read anchors its window to.
#[derive(Clone, Copy, Eq, PartialEq)]
enum WindowAnchor {
    /// The oldest `limit` observations at the cutoff — a stable prefix of the history.
    Oldest,
    /// The newest `limit` observations at the cutoff — the live end of the history.
    Newest,
}

impl SqliteStore {
    /// Reads durable observations for one source as known at an exact cutoff.
    ///
    /// The returned window is the OLDEST `limit` observations at the cutoff — a stable prefix of
    /// the source's history — and `delivered_through` is the highest commit of that window, not
    /// of the source. Readback paths that re-walk a history from its beginning rely on exactly
    /// these prefix semantics. A LIVE consumer must not: once a source outgrows `limit`, this
    /// read's window and watermark stop moving forever. The live surface reads
    /// [`Self::source_observations_newest_as_known`] instead.
    ///
    /// `cutoff` of `None` resolves to the highest durable commit. Returns `Ok(None)` when the
    /// source delivered nothing at or before the cutoff; an empty result is never reported as an
    /// absence claim about the world.
    ///
    /// # Errors
    ///
    /// Fails on a missing cutoff commit, stored clock/blob corruption, or `SQLite` errors.
    pub fn source_observations_as_known(
        &self,
        source_id: &SourceId,
        cutoff: Option<CommitSeq>,
        limit: usize,
    ) -> Result<Option<DurableSourceObservations>> {
        self.source_observations_window(source_id, cutoff, limit, WindowAnchor::Oldest)
    }

    /// Reads the NEWEST durable observations for one source as known at an exact cutoff.
    ///
    /// This is the live-surface read, and it differs from the prefix read above in the two ways
    /// a live head needs:
    ///
    /// - `delivered_through` is the source's TRUE watermark at the cutoff — the highest commit
    ///   at or before it that carries an observation from this source — regardless of `limit`,
    ///   so a follower's cutoff keeps tracking the source however large the catalog grows.
    /// - The returned window is the newest `limit` observations at the cutoff, still in
    ///   ascending commit order. When the source holds more than `limit`, `truncated` is true
    ///   and `elided` counts the OLDER observations the window had no room for. Falling outside
    ///   the window is a render bound on this one read, never a claim those observations did not
    ///   happen: the catalog retains them, and a wider or explicit-cutoff read still reaches
    ///   them.
    ///
    /// `cutoff` of `None` resolves to the highest durable commit. Returns `Ok(None)` when the
    /// source delivered nothing at or before the cutoff; an empty result is never reported as an
    /// absence claim about the world.
    ///
    /// # Errors
    ///
    /// Fails on a missing cutoff commit, stored clock/blob corruption, or `SQLite` errors.
    pub fn source_observations_newest_as_known(
        &self,
        source_id: &SourceId,
        cutoff: Option<CommitSeq>,
        limit: usize,
    ) -> Result<Option<DurableSourceObservations>> {
        self.source_observations_window(source_id, cutoff, limit, WindowAnchor::Newest)
    }

    fn source_observations_window(
        &self,
        source_id: &SourceId,
        cutoff: Option<CommitSeq>,
        limit: usize,
        anchor: WindowAnchor,
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

        let (total, source_max): (i64, Option<i64>) = self.connection.query_row(
            "SELECT COUNT(*),MAX(commit_seq) FROM observation
             WHERE source_id=?1 AND commit_seq<=?2",
            params![source_id.as_str(), cutoff_us],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )?;
        if total == 0 {
            return Ok(None);
        }
        let limit_rows = i64::try_from(limit).unwrap_or(i64::MAX);
        let mut observations =
            self.select_observation_window(source_id, cutoff_us, limit_rows, anchor)?;
        if anchor == WindowAnchor::Newest {
            // The newest-first scan is only a selection order; callers always receive the window
            // in ascending commit order, exactly like the prefix read.
            observations.reverse();
        }
        if observations.is_empty() {
            return Ok(None);
        }
        let delivered_through = match anchor {
            // Prefix semantics: the watermark of the returned window, which sits below the
            // source's true watermark whenever the window is truncated.
            WindowAnchor::Oldest => observations
                .last()
                .map_or(0, |observation| observation.commit_seq.get()),
            // Live semantics: the source's true watermark at the cutoff, whatever the limit.
            WindowAnchor::Newest => {
                as_u64(source_max.unwrap_or_default(), "source delivered_through")?
            }
        };
        let elided = u64::try_from(total)
            .unwrap_or(u64::MAX)
            .saturating_sub(u64::try_from(observations.len()).unwrap_or(u64::MAX));
        Ok(Some(DurableSourceObservations {
            source_id: source_id.clone(),
            through_commit_seq: cutoff,
            through_committed_at,
            delivered_through: CommitSeq::new(delivered_through),
            truncated: total > i64::try_from(observations.len()).unwrap_or(i64::MAX),
            observations,
            elided,
        }))
    }

    #[allow(clippy::too_many_lines)] // One readback keeps its column closure visible in one place.
    fn select_observation_window(
        &self,
        source_id: &SourceId,
        cutoff_us: i64,
        limit_rows: i64,
        anchor: WindowAnchor,
    ) -> Result<Vec<DurableSourceObservation>> {
        let order = match anchor {
            WindowAnchor::Oldest => "o.commit_seq,o.intra_commit_seq",
            WindowAnchor::Newest => "o.commit_seq DESC,o.intra_commit_seq DESC",
        };
        let mut statement = self.connection.prepare(&format!(
            "SELECT o.observation_id,o.commit_seq,o.source_id,o.acquisition_id,o.observation_kind,
                    a.source_locator_redacted,o.received_wall_us,o.available_wall_us,
                    o.source_event_lower_us,o.source_event_upper_us,o.chain_slot,
                    o.chain_commitment,o.parse_disposition,o.quality_code,
                    o.blob_id,c.storage_domain
             FROM observation o
             JOIN acquisition a ON a.acquisition_id=o.acquisition_id
             JOIN observation_blob_contract c ON c.observation_id=o.observation_id
             WHERE o.source_id=?1 AND o.commit_seq<=?2
             ORDER BY {order}
             LIMIT ?3"
        ))?;
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
        Ok(observations)
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

#[cfg(test)]
mod tests {
    use crate::{
        ObservationStorage, SourceRegistration, StoreConfig, StoreIngestBatch, StoreMode,
        store::SqliteStore,
    };
    use joshi_domain::{
        AcquisitionId, BatchDigest, CommitSeq, ObservationId, OpenVariant, RequestFingerprint,
        SourceId, StableString, UtcTimestamp, ValueDigest, WireU64,
    };
    use joshi_evidence::{
        AcquisitionRecord, DurableIngestBatch, MonotonicReading, ObservationDraft,
        ObservationEventTime, ObservationMetadata, ObservationTiming,
    };
    use std::{collections::BTreeMap, path::Path, time::Duration};

    const SOURCE: &str = "source-window-test";

    fn stable(value: &str) -> StableString {
        StableString::new(value).expect("test stable string")
    }

    fn known(value: &str) -> OpenVariant {
        OpenVariant::known(value).expect("test variant")
    }

    fn time(value: &str) -> UtcTimestamp {
        value.parse().expect("test timestamp")
    }

    fn digest_of(fill: char) -> String {
        format!("sha256:{}", fill.to_string().repeat(64))
    }

    fn open_migrated(root: &Path) -> SqliteStore {
        let config = StoreConfig {
            catalog_path: root.join("catalog.sqlite"),
            blob_root: root.join("blobs"),
            export_root: root.join("exports"),
            inline_blob_max_bytes: 1024,
            busy_timeout: Duration::from_secs(1),
            catalog_id: stable("catalog-window-test"),
            max_observations_per_batch: 16,
            max_raw_bytes_per_batch: 1024 * 1024,
        };
        let mut store =
            SqliteStore::open(config, StoreMode::SingleWriter).expect("open test store");
        store
            .migrate(time("2026-08-24T12:00:00.000000Z"))
            .expect("migrate test store");
        store
            .register_source(&SourceRegistration {
                source_id: SourceId::new(SOURCE).expect("source id"),
                namespace: stable("fixture.window"),
                contract_version: stable("v1"),
                collector_build: stable("collector-test"),
                configuration_digest: ValueDigest::new(digest_of('0'))
                    .expect("configuration digest"),
            })
            .expect("register source");
        store
    }

    /// One keeper-style commit carrying observations for the given ordinals.
    fn commit_ordinals(store: &mut SqliteStore, batch: u64, ordinals: std::ops::Range<u64>) {
        let acquisition = AcquisitionRecord {
            acquisition_id: AcquisitionId::new(format!("acquisition-window-{batch}"))
                .expect("acquisition id"),
            source_id: SourceId::new(SOURCE).expect("source id"),
            acquisition_kind: known("fixture"),
            transport_kind: known("fixture"),
            parent_acquisition_id: None,
            request_fingerprint: RequestFingerprint::new(digest_of('a'))
                .expect("request fingerprint"),
            contract_version: stable("v1"),
            started_at: time("2026-08-24T12:00:01.000000Z"),
            started_monotonic: Some(MonotonicReading {
                clock_id: stable("window-clock"),
                nanoseconds: WireU64::new(batch),
            }),
            source_locator: Some(stable("fixture://window")),
            source_cursor: None,
            clocks: joshi_domain::AcquisitionClocks {
                requested_at: Some(time("2026-08-24T12:00:01.000000Z")),
                received_at: time("2026-08-24T12:00:02.000000Z"),
                persisted_at: time("2026-08-24T12:00:02.000001Z"),
                monotonic_elapsed_ns: Some(WireU64::new(1_000)),
                monotonic_domain: Some(stable("window-clock")),
            },
        };
        let mut observations = Vec::new();
        let mut policies = BTreeMap::new();
        for ordinal in ordinals {
            let observation_id = ObservationId::new(format!("observation-window-{ordinal}"))
                .expect("observation id");
            policies.insert(
                observation_id.to_string(),
                ObservationStorage {
                    retention_class: stable("fixture"),
                    content_encoding: Some(stable("identity")),
                    force_external: false,
                },
            );
            observations.push(ObservationDraft {
                acquisition: acquisition.clone(),
                observation: ObservationMetadata {
                    observation_id,
                    acquisition_ordinal: WireU64::new(ordinal),
                    observation_kind: known("fixture"),
                    source_events: Vec::new(),
                    source_variant: known("fixture.payload"),
                    event_time: ObservationEventTime {
                        status: known("not_applicable"),
                        lower: None,
                        upper: None,
                        precision_us: None,
                    },
                    chain: None,
                    source_cursor: None,
                    timing: ObservationTiming {
                        received_at: time("2026-08-24T12:00:02.000000Z"),
                        received_monotonic: MonotonicReading {
                            clock_id: stable("window-clock"),
                            nanoseconds: WireU64::new(2 + ordinal),
                        },
                        persisted_at: time("2026-08-24T12:00:02.000001Z"),
                        available_at: time("2026-08-24T12:00:02.000002Z"),
                    },
                    parse_disposition: known("decoded"),
                    quality_code: None,
                    media_type: stable("application/json"),
                },
                payload: format!("{{\"ordinal\":\"{ordinal}\"}}").into_bytes(),
            });
        }
        let mut ingest = StoreIngestBatch {
            evidence: DurableIngestBatch {
                contract_version: stable("joshi.durable_ingest_batch.v1"),
                batch_id: stable(&format!("batch-window-{batch}")),
                expected_digest: BatchDigest::new(digest_of('0')).expect("batch digest"),
                observations,
                source_events: Vec::new(),
                assertions: Vec::new(),
                coverage_windows: Vec::new(),
                coverage_gaps: Vec::new(),
                coverage_recoveries: Vec::new(),
                cursor_advances: Vec::new(),
            },
            observation_storage: policies,
            coverage_gap_severity: BTreeMap::new(),
            committed_at: time("2026-08-24T12:00:03.000000Z"),
            writer_clock_id: stable("window-writer-clock"),
            committed_mono_ns: 10 + batch,
            writer_build: stable("test-writer"),
        };
        ingest.evidence.expected_digest =
            SqliteStore::canonical_batch_digest(&ingest.evidence).expect("canonical digest");
        store.commit_ingest(&ingest).expect("commit batch");
    }

    fn ordinals_of(durable: &super::DurableSourceObservations) -> Vec<String> {
        durable
            .observations
            .iter()
            .map(|observation| observation.observation_id.to_string())
            .collect()
    }

    /// Ember's frozen afternoon, at store resolution: with more observations than the limit, the
    /// prefix read keeps returning the oldest window and a watermark wedged at that window's
    /// top, while the newest-anchored read returns the live end of the history and the source's
    /// true delivered-through — with the truncation stated and the elision counted, never
    /// silent.
    #[test]
    fn the_newest_window_carries_the_true_watermark_and_states_its_truncation() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let mut store = open_migrated(directory.path());
        // Three keeper-style commits: observations 0-1, then 2-3, then 4.
        commit_ordinals(&mut store, 1, 0..2);
        commit_ordinals(&mut store, 2, 2..4);
        commit_ordinals(&mut store, 3, 4..5);
        let source = SourceId::new(SOURCE).expect("source id");

        // The prefix read keeps its historical semantics exactly: oldest window, watermark of
        // that window. Readback paths that re-walk history from the start depend on this.
        let prefix = store
            .source_observations_as_known(&source, None, 2)
            .expect("prefix read")
            .expect("the source delivered");
        assert_eq!(
            ordinals_of(&prefix),
            vec!["observation-window-0", "observation-window-1"]
        );
        assert_eq!(prefix.delivered_through, CommitSeq::new(1));
        assert!(prefix.truncated);
        assert_eq!(prefix.elided, 3);

        // The newest read returns the live end in ascending order, and its watermark is the
        // source's true delivered-through — commit 3 — however small the window.
        let newest = store
            .source_observations_newest_as_known(&source, None, 2)
            .expect("newest read")
            .expect("the source delivered");
        assert_eq!(
            ordinals_of(&newest),
            vec!["observation-window-3", "observation-window-4"]
        );
        assert_eq!(newest.delivered_through, CommitSeq::new(3));
        assert!(newest.truncated);
        assert_eq!(newest.elided, 3);
        assert_eq!(newest.through_commit_seq, prefix.through_commit_seq);

        // A limit-1 newest read is the follow tick's probe: one payload, the true watermark.
        let probe = store
            .source_observations_newest_as_known(&source, None, 1)
            .expect("probe read")
            .expect("the source delivered");
        assert_eq!(ordinals_of(&probe), vec!["observation-window-4"]);
        assert_eq!(probe.delivered_through, CommitSeq::new(3));
        assert_eq!(probe.elided, 4);

        // An explicit historical cutoff still resolves against that moment's true watermark.
        let historical = store
            .source_observations_newest_as_known(&source, Some(CommitSeq::new(2)), 2)
            .expect("historical read")
            .expect("the source had delivered");
        assert_eq!(
            ordinals_of(&historical),
            vec!["observation-window-2", "observation-window-3"]
        );
        assert_eq!(historical.delivered_through, CommitSeq::new(2));
        assert_eq!(historical.elided, 2);

        // With room for everything the two anchors agree field for field, and nothing is elided.
        let wide_prefix = store
            .source_observations_as_known(&source, None, 16)
            .expect("wide prefix read")
            .expect("the source delivered");
        let wide_newest = store
            .source_observations_newest_as_known(&source, None, 16)
            .expect("wide newest read")
            .expect("the source delivered");
        assert_eq!(wide_prefix, wide_newest);
        assert!(!wide_newest.truncated);
        assert_eq!(wide_newest.elided, 0);
        assert_eq!(wide_newest.observations.len(), 5);
        assert_eq!(wide_newest.delivered_through, CommitSeq::new(3));

        // Determinism: the same catalog and cutoff produce the identical window.
        let again = store
            .source_observations_newest_as_known(&source, None, 2)
            .expect("repeat read")
            .expect("the source delivered");
        assert_eq!(again, newest);
    }
}
