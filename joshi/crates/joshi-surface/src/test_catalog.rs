//! One real committed catalog, shared by every test in this crate that needs one.
//!
//! Nothing in here hands a DTO to the adapter. Every row is written with the real single-writer
//! `joshi-store` through `SqliteStore::commit_ingest`, so a test that reads a surface back is
//! reading rows a real writer committed, in a real catalog file, at real commit sequences.
//!
//! [`build_catalog_at`] is deliberately separate from [`catalog`]: the restart proof needs to
//! build the same history at a caller-owned path in a child process and keep the writer open, and
//! the in-process tests need a temporary directory that cleans itself up.

use std::{collections::BTreeMap, path::Path, str::FromStr, time::Duration};

use joshi_domain::{
    AcquisitionClocks, AcquisitionId, AssertionId, BatchDigest, CoverageId, ObservationId,
    OpenVariant, RequestFingerprint, SourceEventId, SourceId, StableString, UtcTimestamp,
    ValueDigest, WireU64,
};
use joshi_evidence::{
    AcquisitionRecord, AssertionDraft, AssertionEvidence, Boundary, CoverageGap, CoverageRecovery,
    CoverageScope, CoverageWindow, DurableIngestBatch, EventValidInterval, MonotonicReading,
    ObservationDraft, ObservationEventTime, ObservationMetadata, ObservationSourceEvent,
    ObservationTiming, SourceEventRecord,
};
use joshi_store::{
    ObservationStorage, SourceRegistration, SqliteStore, StoreConfig, StoreIngestBatch, StoreMode,
};
use sha2::{Digest, Sha256};
use tempfile::TempDir;

use crate::{
    AccessibilityEvidence, DailyUseSurfaceProfileV1, READ_ONLY_AUTHORITY, SURFACE_CONTRACT,
    SURFACE_SCHEMA_VERSION, SurfaceCatalogReadback, SurfaceEntryV1, SurfaceKind, SurfaceStatus,
    SurfaceTaskV1, surface_field_semantic_key,
};

pub(crate) const PUMP: &str = "pump";
pub(crate) const SOLANA: &str = "solana";
pub(crate) const CONTRACT_VERSION: &str = "v1";

pub(crate) fn s(value: &str) -> StableString {
    StableString::new(value).expect("stable string")
}

pub(crate) fn t(value: &str) -> UtcTimestamp {
    UtcTimestamp::from_str(value).expect("exact timestamp")
}

pub(crate) fn micros_later(value: UtcTimestamp, micros: i64) -> UtcTimestamp {
    UtcTimestamp::new(value.as_datetime() + time::Duration::microseconds(micros))
        .expect("shifted timestamp")
}

pub(crate) fn zero_digest(fill: char) -> ValueDigest {
    ValueDigest::new(format!("sha256:{}", fill.to_string().repeat(64))).expect("digest")
}

pub(crate) fn content_digest(payload: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(payload))
}

/// Mirrors the store's own assertion-value material so the test commits a real digest rather
/// than a placeholder the writer would reject.
#[derive(serde::Serialize)]
pub(crate) struct AssertionValueMaterial<'a> {
    contract: &'static str,
    assertion_kind: &'a OpenVariant,
    producer: &'a StableString,
    producer_version: &'a StableString,
    extension: &'a serde_json::Value,
}

pub(crate) fn assertion_value_digest(
    kind: &OpenVariant,
    producer: &StableString,
    producer_version: &StableString,
    extension: &serde_json::Value,
) -> ValueDigest {
    let encoded = serde_json::to_vec(&AssertionValueMaterial {
        contract: "joshi.assertion_value.v1",
        assertion_kind: kind,
        producer,
        producer_version,
        extension,
    })
    .expect("assertion value material");
    ValueDigest::new(content_digest(&encoded)).expect("assertion value digest")
}

pub(crate) fn config(root: &Path) -> StoreConfig {
    StoreConfig {
        catalog_path: root.join("catalog.sqlite"),
        blob_root: root.join("blobs"),
        export_root: root.join("exports"),
        inline_blob_max_bytes: 4_096,
        busy_timeout: Duration::from_secs(1),
        catalog_id: s("catalog:surface-readback"),
        max_observations_per_batch: 64,
        max_raw_bytes_per_batch: 4 * 1024 * 1024,
    }
}

pub(crate) fn profile() -> DailyUseSurfaceProfileV1 {
    let mut value = DailyUseSurfaceProfileV1 {
        contract: s(SURFACE_CONTRACT),
        schema_version: SURFACE_SCHEMA_VERSION,
        profile_id: s("daily-readback"),
        profile_version: WireU64::new(1),
        ember_approval_id: s("ember-approval-readback"),
        approved_at: t("2026-08-18T09:00:00.000000Z"),
        surfaces: vec![
            SurfaceEntryV1 {
                surface_id: s("launch"),
                kind: SurfaceKind::LaunchNew,
                critical: true,
                route: s("/launch"),
                // The declared source is the exact registered catalog `source.source_id`.
                source: s(PUMP),
                personalization: s("none"),
                ordering: s("newest"),
                pagination: s("cursor"),
                cadence: s("60s"),
                fields_media: vec![s("mint"), s("name")],
                field_status: BTreeMap::from([
                    (s("mint"), SurfaceStatus::PromotedContinuous),
                    (s("name"), SurfaceStatus::PromotedContinuous),
                ]),
                status: SurfaceStatus::PromotedContinuous,
                approval: None,
                tasks: vec![SurfaceTaskV1 {
                    task_id: s("open-launch"),
                    name: s("open launch"),
                    critical: true,
                    accessibility: AccessibilityEvidence {
                        keyboard: true,
                        large_target: true,
                        screen_reader: true,
                        reduced_motion: true,
                        evidence_id: s("a11y-launch"),
                    },
                }],
            },
            SurfaceEntryV1 {
                surface_id: s("chain-lifecycle"),
                kind: SurfaceKind::LifecycleMigrationPools,
                critical: true,
                route: s("/chain"),
                source: s(SOLANA),
                personalization: s("none"),
                ordering: s("slot"),
                pagination: s("none"),
                cadence: s("event"),
                fields_media: vec![s("migration")],
                field_status: BTreeMap::from([(
                    s("migration"),
                    SurfaceStatus::PublicChainAlternativeNotProductParity,
                )]),
                status: SurfaceStatus::PublicChainAlternativeNotProductParity,
                approval: None,
                tasks: vec![SurfaceTaskV1 {
                    task_id: s("inspect-lifecycle"),
                    name: s("inspect lifecycle"),
                    critical: true,
                    accessibility: AccessibilityEvidence {
                        keyboard: true,
                        large_target: true,
                        screen_reader: true,
                        reduced_motion: true,
                        evidence_id: s("a11y-chain"),
                    },
                }],
            },
        ],
        profile_digest: zero_digest('0'),
        authority: s(READ_ONLY_AUTHORITY),
    };
    value.profile_digest = value.computed_digest().expect("profile digest");
    value
}

pub(crate) struct Batch {
    pub(crate) id: &'static str,
    pub(crate) at: UtcTimestamp,
    pub(crate) mono: u64,
    pub(crate) observations: Vec<ObservationDraft>,
    pub(crate) storage: BTreeMap<String, ObservationStorage>,
    pub(crate) source_events: Vec<SourceEventRecord>,
    pub(crate) assertions: Vec<AssertionDraft>,
    pub(crate) coverage_windows: Vec<CoverageWindow>,
    pub(crate) coverage_gaps: Vec<CoverageGap>,
    pub(crate) coverage_recoveries: Vec<CoverageRecovery>,
    pub(crate) gap_severity: BTreeMap<String, StableString>,
}

impl Batch {
    pub(crate) fn new(id: &'static str, at: &str, mono: u64) -> Self {
        Self {
            id,
            at: t(at),
            mono,
            observations: Vec::new(),
            storage: BTreeMap::new(),
            source_events: Vec::new(),
            assertions: Vec::new(),
            coverage_windows: Vec::new(),
            coverage_gaps: Vec::new(),
            coverage_recoveries: Vec::new(),
            gap_severity: BTreeMap::new(),
        }
    }

    #[allow(clippy::too_many_arguments)] // One committed frame needs all of its real identities.
    pub(crate) fn observed(
        mut self,
        source: &str,
        acquisition: &str,
        observation: &str,
        event: &str,
        subject: &str,
        event_time: &str,
        payload: &[u8],
    ) -> Self {
        let at = self.at;
        let lower = t(event_time);
        self.source_events.push(SourceEventRecord {
            source_event_id: SourceEventId::new(event).expect("source event id"),
            source_id: SourceId::new(source).expect("source id"),
            namespace: s("market.subject"),
            natural_key: s(subject),
            source_order_key: None,
            event_kind: OpenVariant::known("mint").expect("event kind"),
        });
        self.storage.insert(
            observation.to_owned(),
            ObservationStorage {
                retention_class: s("public_source"),
                content_encoding: None,
                force_external: false,
            },
        );
        self.observations.push(ObservationDraft {
            acquisition: AcquisitionRecord {
                acquisition_id: AcquisitionId::new(acquisition).expect("acquisition id"),
                source_id: SourceId::new(source).expect("source id"),
                acquisition_kind: OpenVariant::known("live").expect("kind"),
                transport_kind: OpenVariant::known("http").expect("transport"),
                parent_acquisition_id: None,
                request_fingerprint: RequestFingerprint::new(format!("sha256:{}", "1".repeat(64)))
                    .expect("request fingerprint"),
                contract_version: s(CONTRACT_VERSION),
                started_at: lower,
                started_monotonic: Some(MonotonicReading {
                    clock_id: s("collector-clock"),
                    nanoseconds: WireU64::new(1),
                }),
                source_locator: Some(s("https://example.invalid/frame")),
                source_cursor: None,
                clocks: AcquisitionClocks {
                    requested_at: Some(lower),
                    received_at: lower,
                    persisted_at: at,
                    monotonic_elapsed_ns: Some(WireU64::new(1)),
                    monotonic_domain: Some(s("collector-clock")),
                },
            },
            observation: ObservationMetadata {
                observation_id: ObservationId::new(observation).expect("observation id"),
                acquisition_ordinal: WireU64::new(0),
                observation_kind: OpenVariant::known("frame").expect("observation kind"),
                source_events: vec![ObservationSourceEvent {
                    source_event_id: SourceEventId::new(event).expect("source event id"),
                    relation: OpenVariant::known("contains").expect("relation"),
                    event_ordinal: Some(WireU64::new(0)),
                }],
                source_variant: OpenVariant::known("market.frame").expect("variant"),
                event_time: ObservationEventTime {
                    status: OpenVariant::known("exact").expect("event status"),
                    lower: Some(lower),
                    upper: Some(micros_later(lower, 1)),
                    precision_us: Some(WireU64::new(1)),
                },
                chain: None,
                source_cursor: None,
                timing: ObservationTiming {
                    received_at: lower,
                    received_monotonic: MonotonicReading {
                        clock_id: s("collector-clock"),
                        nanoseconds: WireU64::new(2),
                    },
                    persisted_at: at,
                    available_at: at,
                },
                parse_disposition: OpenVariant::known("decoded").expect("parse disposition"),
                quality_code: None,
                media_type: s("application/json"),
            },
            payload: payload.to_vec(),
        });
        self
    }

    /// One more subject named by the observation this batch committed last.
    ///
    /// A provider frame is not one subject per row. A single Solana transaction names every mint
    /// in its token balances, so one committed observation carries several `contains` links, and a
    /// derived cut has to give each of them its own row identity rather than colliding them.
    pub(crate) fn also_naming(mut self, source: &str, event: &str, subject: &str) -> Self {
        self.source_events.push(SourceEventRecord {
            source_event_id: SourceEventId::new(event).expect("source event id"),
            source_id: SourceId::new(source).expect("source id"),
            namespace: s("market.subject"),
            natural_key: s(subject),
            source_order_key: None,
            event_kind: OpenVariant::known("mint").expect("event kind"),
        });
        let ordinal = self
            .observations
            .last()
            .map(|draft| draft.observation.source_events.len())
            .expect("an observation to extend");
        if let Some(draft) = self.observations.last_mut() {
            draft
                .observation
                .source_events
                .push(ObservationSourceEvent {
                    source_event_id: SourceEventId::new(event).expect("source event id"),
                    relation: OpenVariant::known("contains").expect("relation"),
                    event_ordinal: Some(WireU64::new(
                        u64::try_from(ordinal).expect("event ordinal"),
                    )),
                });
        }
        self
    }

    /// One committed observation that names no subject at all.
    ///
    /// This is the exact shape the first live Helius run committed: real response bytes, a real
    /// acquisition, and no `source_event`, because nothing had yet decoded a subject out of the
    /// body. The surface cannot see such a row, and the derivation has to say so out loud rather
    /// than report an empty population.
    pub(crate) fn observed_without_subject(
        mut self,
        source: &str,
        acquisition: &str,
        observation: &str,
        event_time: &str,
        payload: &[u8],
    ) -> Self {
        self = self.observed(
            source,
            acquisition,
            observation,
            "unused-source-event",
            "unused-subject",
            event_time,
            payload,
        );
        self.source_events.clear();
        if let Some(draft) = self.observations.last_mut() {
            draft.observation.source_events.clear();
        }
        self
    }

    pub(crate) fn covering(
        mut self,
        source: &str,
        coverage: &str,
        subject: &str,
        family: &str,
    ) -> Self {
        let at = self.at;
        self.coverage_windows.push(CoverageWindow {
            coverage_id: CoverageId::new(coverage).expect("coverage id"),
            scope: CoverageScope {
                source_id: SourceId::new(source).expect("source id"),
                family: OpenVariant::known(family).expect("family"),
                subject: Some(s(subject)),
            },
            lower: Boundary::Wall { value: at },
            upper: None,
            state: OpenVariant::known("open").expect("state"),
            available_at: at,
        });
        self
    }

    #[allow(clippy::too_many_arguments)] // One committed cell assertion, spelled out in full.
    pub(crate) fn cell(
        mut self,
        assertion: &str,
        surface: &str,
        subject: &str,
        field: &str,
        observation: &str,
        valid_lower: &str,
        status: &str,
    ) -> Self {
        let at = self.at;
        let lower = t(valid_lower);
        let kind = OpenVariant::known("surface_cell").expect("assertion kind");
        let producer = s("joshi-surface-readback-test");
        let producer_version = s("v1");
        let extension = serde_json::json!({});
        let value_digest = assertion_value_digest(&kind, &producer, &producer_version, &extension);
        self.assertions.push(AssertionDraft {
            assertion_id: AssertionId::new(assertion).expect("assertion id"),
            semantic_key: s(&surface_field_semantic_key(surface, subject, field)),
            assertion_kind: kind,
            producer,
            producer_version,
            assertion_status: OpenVariant::known(status).expect("assertion status"),
            valid_time: EventValidInterval {
                status: OpenVariant::known("exact").expect("valid status"),
                lower: Some(lower),
                upper: Some(micros_later(lower, 1)),
            },
            evidence: vec![AssertionEvidence {
                observation_id: ObservationId::new(observation).expect("observation id"),
                role: OpenVariant::known("decoded_from").expect("role"),
            }],
            source_events: Vec::new(),
            command_evidence: Vec::new(),
            supersedes_assertion_id: None,
            available_at: at,
            value_digest,
            extension,
        });
        self
    }

    pub(crate) fn gap(mut self, source: &str, coverage: &str, gap: &str, subject: &str) -> Self {
        let at = self.at;
        self.coverage_gaps.push(CoverageGap {
            gap_id: CoverageId::new(gap).expect("gap id"),
            coverage_id: CoverageId::new(coverage).expect("coverage id"),
            scope: CoverageScope {
                source_id: SourceId::new(source).expect("source id"),
                family: OpenVariant::known("market_census").expect("family"),
                subject: Some(s(subject)),
            },
            lower: Boundary::Wall { value: at },
            upper: None,
            reason: OpenVariant::known("provider_stream_drop").expect("reason"),
            detected_at: at,
        });
        self.gap_severity.insert(gap.to_owned(), s("degraded"));
        self
    }

    /// A source-wide gap whose window the producer bounded on both ends, and whose lower
    /// boundary is a source-native cursor rather than a wall clock.
    pub(crate) fn gap_bounded(
        mut self,
        source: &str,
        coverage: &str,
        gap: &str,
        cursor: &str,
        upper: &str,
    ) -> Self {
        let at = self.at;
        self.coverage_gaps.push(CoverageGap {
            gap_id: CoverageId::new(gap).expect("gap id"),
            coverage_id: CoverageId::new(coverage).expect("coverage id"),
            scope: CoverageScope {
                source_id: SourceId::new(source).expect("source id"),
                family: OpenVariant::known("market_census").expect("family"),
                subject: None,
            },
            lower: Boundary::SourceCursor { value: s(cursor) },
            upper: Some(Boundary::Wall { value: t(upper) }),
            reason: OpenVariant::known("provider_stream_drop").expect("reason"),
            detected_at: at,
        });
        self.gap_severity.insert(gap.to_owned(), s("scope_stopped"));
        self
    }

    pub(crate) fn recovered(mut self, recovery: &str, gap: &str) -> Self {
        let at = self.at;
        self.coverage_recoveries.push(CoverageRecovery {
            recovery_id: CoverageId::new(recovery).expect("recovery id"),
            gap_id: CoverageId::new(gap).expect("gap id"),
            acquisition_id: None,
            status: OpenVariant::known("complete").expect("recovery status"),
            recovered_through: None,
            evidence: Vec::new(),
            available_at: at,
        });
        self
    }

    pub(crate) fn commit(mut self, store: &mut SqliteStore) -> u64 {
        self.observations.sort_by(|left, right| {
            (
                &left.acquisition.acquisition_id,
                left.observation.acquisition_ordinal,
                &left.observation.observation_id,
            )
                .cmp(&(
                    &right.acquisition.acquisition_id,
                    right.observation.acquisition_ordinal,
                    &right.observation.observation_id,
                ))
        });
        self.source_events
            .sort_by(|left, right| left.source_event_id.cmp(&right.source_event_id));
        self.assertions
            .sort_by(|left, right| left.assertion_id.cmp(&right.assertion_id));
        self.coverage_windows
            .sort_by(|left, right| left.coverage_id.cmp(&right.coverage_id));
        self.coverage_gaps
            .sort_by(|left, right| left.gap_id.cmp(&right.gap_id));
        self.coverage_recoveries
            .sort_by(|left, right| left.recovery_id.cmp(&right.recovery_id));
        let mut batch = StoreIngestBatch {
            evidence: DurableIngestBatch {
                contract_version: s("joshi.durable_ingest_batch.v1"),
                batch_id: s(self.id),
                expected_digest: BatchDigest::new(format!("sha256:{}", "0".repeat(64)))
                    .expect("placeholder digest"),
                observations: self.observations,
                source_events: self.source_events,
                assertions: self.assertions,
                coverage_windows: self.coverage_windows,
                coverage_gaps: self.coverage_gaps,
                coverage_recoveries: self.coverage_recoveries,
                cursor_advances: Vec::new(),
            },
            observation_storage: self.storage,
            coverage_gap_severity: self.gap_severity,
            committed_at: self.at,
            writer_clock_id: s("readback-writer-clock"),
            committed_mono_ns: self.mono,
            writer_build: s("readback-test"),
        };
        batch.evidence.expected_digest =
            SqliteStore::canonical_batch_digest(&batch.evidence).expect("canonical batch digest");
        store
            .commit_ingest(&batch)
            .expect("durable commit")
            .commit_seq
            .get()
    }
}

pub(crate) struct Catalog {
    pub(crate) _root: TempDir,
    pub(crate) path: std::path::PathBuf,
    pub(crate) seq: BTreeMap<&'static str, u64>,
}

impl Catalog {
    pub(crate) fn open(&self) -> SurfaceCatalogReadback {
        SurfaceCatalogReadback::open(&self.path, Duration::from_secs(1)).expect("read-only catalog")
    }

    pub(crate) fn at(&self, label: &str) -> u64 {
        *self.seq.get(label).expect("commit label")
    }
}

pub(crate) const PAYLOAD_A: &[u8] = br#"{"mint":"mint-a","name":"Alpha"}"#;
/// One frame whose retained bytes name two mints, the way a real transaction does.
pub(crate) const PAYLOAD_CENSUS: &[u8] =
    br#"{"tokenBalances":[{"mint":"mint-a"},{"mint":"mint-c"}]}"#;

/// One catalog with a real committed history:
///
/// * `declare` -- census coverage for `mint-a` and `mint-b`, and the first `mint-a` frame.
/// * `assert`  -- accepted per-cell assertions for `launch/mint-a/{name,mint}`.
/// * `gap`     -- a `mint-a` coverage gap.
/// * `recover` -- terminal recovery for that gap.
/// * `gap-unobserved` -- a gap on a declared but never observed subject.
/// * `unsubjected` -- one committed observation that names no subject at all.
/// * `gap-bounded` -- a source-wide gap whose window is bounded by a cursor and a wall clock.
/// * `census` -- one frame naming two subjects, one of which no coverage window declared.
pub(crate) fn catalog() -> Catalog {
    let root = TempDir::new().expect("temporary root");
    let path = root.path().join("catalog.sqlite");
    let (store, seq) = build_catalog_at(root.path());
    // The in-process tests reopen this catalog read-only, so the writer is closed cleanly here.
    // The restart proof deliberately does not: it keeps the writer open and has the process
    // killed underneath it.
    drop(store);
    Catalog {
        _root: root,
        path,
        seq,
    }
}

/// Writes the history above at a caller-owned root and returns the still-open writer.
///
/// The writer is returned rather than dropped so a caller can be killed while it is open.
pub(crate) fn build_catalog_at(root: &Path) -> (SqliteStore, BTreeMap<&'static str, u64>) {
    let mut store = SqliteStore::open(config(root), StoreMode::SingleWriter).expect("open store");
    store
        .migrate(t("2026-08-18T08:00:00.000000Z"))
        .expect("migrate");
    for source in [PUMP, SOLANA] {
        store
            .register_source(&SourceRegistration {
                source_id: SourceId::new(source).expect("source id"),
                namespace: s(&format!("market.{source}")),
                contract_version: s(CONTRACT_VERSION),
                collector_build: s("readback-test"),
                configuration_digest: zero_digest('0'),
            })
            .expect("register source");
    }
    let mut seq = BTreeMap::new();
    seq.insert(
        "declare",
        Batch::new("batch-declare", "2026-08-18T10:00:00.000000Z", 1)
            .covering(PUMP, "coverage-mint-a", "mint-a", "market_census")
            .covering(PUMP, "coverage-mint-b", "mint-b", "market_census")
            .observed(
                PUMP,
                "acq-a",
                "obs-a",
                "event-a",
                "mint-a",
                "2026-08-18T09:59:30.000000Z",
                PAYLOAD_A,
            )
            .commit(&mut store),
    );
    seq.insert(
        "assert",
        Batch::new("batch-assert", "2026-08-18T10:05:00.000000Z", 2)
            .cell(
                "assert-name",
                "launch",
                "mint-a",
                "name",
                "obs-a",
                "2026-08-18T10:04:30.000000Z",
                "accepted",
            )
            .cell(
                "assert-mint",
                "launch",
                "mint-a",
                "mint",
                "obs-a",
                "2026-08-18T09:50:00.000000Z",
                "accepted",
            )
            .commit(&mut store),
    );
    seq.insert(
        "gap",
        Batch::new("batch-gap", "2026-08-18T10:10:00.000000Z", 3)
            .gap(PUMP, "coverage-mint-a", "gap-mint-a", "mint-a")
            .commit(&mut store),
    );
    seq.insert(
        "recover",
        Batch::new("batch-recover", "2026-08-18T10:15:00.000000Z", 4)
            .recovered("recovery-mint-a", "gap-mint-a")
            .commit(&mut store),
    );
    seq.insert(
        "gap-unobserved",
        Batch::new("batch-gap-unobserved", "2026-08-18T10:20:00.000000Z", 5)
            .gap(PUMP, "coverage-mint-b", "gap-mint-b", "mint-b")
            .commit(&mut store),
    );
    seq.insert(
        "unsubjected",
        Batch::new("batch-unsubjected", "2026-08-18T10:22:00.000000Z", 6)
            .observed_without_subject(
                SOLANA,
                "acq-unsubjected",
                "obs-unsubjected",
                "2026-08-18T10:21:30.000000Z",
                br#"{"jsonrpc":"2.0","id":1,"result":440345530}"#,
            )
            .commit(&mut store),
    );
    seq.insert(
        "gap-bounded",
        Batch::new("batch-gap-bounded", "2026-08-18T10:25:00.000000Z", 7)
            .gap_bounded(
                PUMP,
                "coverage-mint-a",
                "gap-pump-window",
                "cursor:pump/slot/440345530",
                "2026-08-18T10:24:00.000000Z",
            )
            .commit(&mut store),
    );
    // The census shape the first real Helius run committed: one frame naming two subjects at once,
    // one of them a mint no coverage window ever declared. This commit is last so that every
    // earlier cutoff above keeps the exact history it was written against.
    seq.insert(
        "census",
        Batch::new("batch-census", "2026-08-18T10:30:00.000000Z", 8)
            .observed(
                PUMP,
                "acq-census",
                "obs-census",
                // `source_event` is unique on (source, namespace, natural key), so a second
                // frame naming `mint-a` reuses the event identity the first one committed.
                "event-a",
                "mint-a",
                "2026-08-18T10:29:30.000000Z",
                PAYLOAD_CENSUS,
            )
            .also_naming(PUMP, "event-census-c", "mint-c")
            .commit(&mut store),
    );
    (store, seq)
}
