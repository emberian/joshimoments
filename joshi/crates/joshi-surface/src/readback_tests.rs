//! Store-readback tests.
//!
//! Every test here writes rows with the real single-writer `joshi-store` and then reads the
//! surface back through the adapter. Nothing hands the adapter a struct literal: if the derivation
//! stopped reading the catalog, these tests would fail rather than keep passing.

use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
    str::FromStr,
    time::Duration,
};

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
    AccessibilityEvidence, DailyUseSurfaceProfileV1, FieldState, READ_ONLY_AUTHORITY,
    SURFACE_CONTRACT, SURFACE_SCHEMA_VERSION, SurfaceCatalogReadback, SurfaceEntryV1, SurfaceKind,
    SurfaceMembership, SurfaceStatus, SurfaceTaskV1, UnresolvedSurfaceInput,
    parse_surface_derivation_receipt, surface_event_identity, surface_field_semantic_key,
};

const PUMP: &str = "pump";
const SOLANA: &str = "solana";
const CONTRACT_VERSION: &str = "v1";

fn s(value: &str) -> StableString {
    StableString::new(value).expect("stable string")
}

fn t(value: &str) -> UtcTimestamp {
    UtcTimestamp::from_str(value).expect("exact timestamp")
}

fn micros_later(value: UtcTimestamp, micros: i64) -> UtcTimestamp {
    UtcTimestamp::new(value.as_datetime() + time::Duration::microseconds(micros))
        .expect("shifted timestamp")
}

fn zero_digest(fill: char) -> ValueDigest {
    ValueDigest::new(format!("sha256:{}", fill.to_string().repeat(64))).expect("digest")
}

fn content_digest(payload: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(payload))
}

/// Mirrors the store's own assertion-value material so the test commits a real digest rather
/// than a placeholder the writer would reject.
#[derive(serde::Serialize)]
struct AssertionValueMaterial<'a> {
    contract: &'static str,
    assertion_kind: &'a OpenVariant,
    producer: &'a StableString,
    producer_version: &'a StableString,
    extension: &'a serde_json::Value,
}

fn assertion_value_digest(
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

fn config(root: &Path) -> StoreConfig {
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

fn profile() -> DailyUseSurfaceProfileV1 {
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

struct Batch {
    id: &'static str,
    at: UtcTimestamp,
    mono: u64,
    observations: Vec<ObservationDraft>,
    storage: BTreeMap<String, ObservationStorage>,
    source_events: Vec<SourceEventRecord>,
    assertions: Vec<AssertionDraft>,
    coverage_windows: Vec<CoverageWindow>,
    coverage_gaps: Vec<CoverageGap>,
    coverage_recoveries: Vec<CoverageRecovery>,
    gap_severity: BTreeMap<String, StableString>,
}

impl Batch {
    fn new(id: &'static str, at: &str, mono: u64) -> Self {
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
    fn observed(
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

    fn covering(mut self, source: &str, coverage: &str, subject: &str, family: &str) -> Self {
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
    fn cell(
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

    fn gap(mut self, source: &str, coverage: &str, gap: &str, subject: &str) -> Self {
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

    fn recovered(mut self, recovery: &str, gap: &str) -> Self {
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

    fn commit(mut self, store: &mut SqliteStore) -> u64 {
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

struct Catalog {
    _root: TempDir,
    path: std::path::PathBuf,
    seq: BTreeMap<&'static str, u64>,
}

impl Catalog {
    fn open(&self) -> SurfaceCatalogReadback {
        SurfaceCatalogReadback::open(&self.path, Duration::from_secs(1)).expect("read-only catalog")
    }

    fn at(&self, label: &str) -> u64 {
        *self.seq.get(label).expect("commit label")
    }
}

const PAYLOAD_A: &[u8] = br#"{"mint":"mint-a","name":"Alpha"}"#;

/// One catalog with a real committed history:
///
/// * `declare` -- census coverage for `mint-a` and `mint-b`, and the first `mint-a` frame.
/// * `assert`  -- accepted per-cell assertions for `launch/mint-a/{name,mint}`.
/// * `gap`     -- a `mint-a` coverage gap.
/// * `recover` -- terminal recovery for that gap.
fn catalog() -> Catalog {
    let root = TempDir::new().expect("temporary root");
    let path = root.path().join("catalog.sqlite");
    let mut store =
        SqliteStore::open(config(root.path()), StoreMode::SingleWriter).expect("open store");
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
    drop(store);
    Catalog {
        _root: root,
        path,
        seq,
    }
}

fn cell(cut: &crate::SurfaceCutV1, subject: &str, field: &str) -> FieldState {
    cut.source_states
        .iter()
        .find(|state| state.subject.as_str() == subject && state.field.as_str() == field)
        .map(|state| state.state.clone())
        .expect("derived cell")
}

#[test]
fn population_facts_and_clocks_are_derived_from_committed_rows() {
    let catalog = catalog();
    let profile = profile();
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("assert"), 10)
        .expect("derive at assert cutoff");

    // The cutoff wall time is the catalog's own commit clock, not a caller value.
    assert_eq!(derived.derivation.cutoff, t("2026-08-18T10:05:00.000000Z"));
    assert_eq!(derived.cut.cutoff, derived.derivation.cutoff);

    // The population is declared coverage scope union observed subjects, recomputed here.
    let subjects: Vec<_> = derived
        .cut
        .universe
        .eligible_subjects
        .iter()
        .map(|value| value.as_str().to_owned())
        .collect();
    assert_eq!(subjects, vec!["mint-a".to_owned(), "mint-b".to_owned()]);
    assert_eq!(derived.cut.universe.eligible_count.get(), 2);
    assert_eq!(derived.derivation.declared_subjects.get(), 2);
    assert_eq!(derived.derivation.observed_subjects.get(), 1);
    // The declared digest is the recomputed one; the DTO refuses any other.
    derived.cut.universe.validate().expect("universe closure");

    // The single rendered row is the committed observation, keyed by its real identities and
    // carrying the sha256 of the exact ingested provider bytes.
    assert_eq!(derived.cut.rendered.len(), 1);
    let row = &derived.cut.rendered[0];
    assert_eq!(row.subject.as_str(), "mint-a");
    assert_eq!(
        row.event_id.as_str(),
        surface_event_identity("launch", "obs-a")
    );
    assert_eq!(row.evidence_digest.as_str(), content_digest(PAYLOAD_A));
    assert_eq!(row.memberships, vec![SurfaceMembership::Census]);
    assert_eq!(row.observed_at, t("2026-08-18T09:59:30.000000Z"));
    assert_eq!(row.known_at, t("2026-08-18T10:00:00.000000Z"));

    // Cells come from effective assertions; a fresh one is covered and an old one is stale.
    assert_eq!(
        cell(&derived.cut, "mint-a", "name"),
        FieldState::Covered {
            observed_at: t("2026-08-18T10:04:30.000000Z")
        }
    );
    assert_eq!(
        cell(&derived.cut, "mint-a", "mint"),
        FieldState::Stale {
            observed_at: t("2026-08-18T09:50:00.000000Z"),
            age_seconds: WireU64::new(900)
        }
    );
    // A declared but unobserved subject keeps explicit unknown cells rather than vanishing.
    assert!(matches!(
        cell(&derived.cut, "mint-b", "name"),
        FieldState::Unknown { .. }
    ));
    assert!(matches!(
        cell(&derived.cut, "mint-a", "migration"),
        FieldState::Unknown { .. }
    ));

    derived
        .cut
        .validate_against(&profile)
        .expect("cut closes against the approved profile");
}

#[test]
fn derivation_receipt_names_every_input_it_could_not_resolve() {
    let catalog = catalog();
    let profile = profile();
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("assert"), 10)
        .expect("derive");
    let unresolved = &derived.derivation.unresolved;
    for expected in [
        UnresolvedSurfaceInput::HotLeaseReceipts,
        UnresolvedSurfaceInput::QualificationSessions,
        UnresolvedSurfaceInput::WorldEligibility,
        // `chain-lifecycle` declares cadence `event` and ordering `slot`.
        UnresolvedSurfaceInput::CadenceStalenessBound,
        UnresolvedSurfaceInput::RenderOrderingPolicy,
    ] {
        assert!(unresolved.contains(&expected), "missing {expected:?}");
    }
    assert!(!unresolved.contains(&UnresolvedSurfaceInput::FieldAssertionsAbsent));

    // The receipt is exact-byte canonical, like every other artifact this crate emits.
    let bytes = derived
        .derivation
        .canonical_bytes()
        .expect("canonical receipt bytes");
    let parsed = parse_surface_derivation_receipt(&bytes).expect("round trip");
    assert_eq!(parsed, derived.derivation);
    let mut padded = vec![b' '];
    padded.extend(bytes);
    assert!(parse_surface_derivation_receipt(&padded).is_err());
}

#[test]
fn an_earlier_cutoff_cannot_see_later_committed_knowledge() {
    let catalog = catalog();
    let profile = profile();
    let early = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("declare"), 10)
        .expect("derive at declare cutoff");
    assert_eq!(early.derivation.field_assertion_rows.get(), 0);
    assert!(
        early
            .derivation
            .unresolved
            .contains(&UnresolvedSurfaceInput::FieldAssertionsAbsent)
    );
    assert!(matches!(
        cell(&early.cut, "mint-a", "name"),
        FieldState::Unknown { .. }
    ));
    assert_eq!(early.derivation.cutoff, t("2026-08-18T10:00:00.000000Z"));

    let late = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("assert"), 10)
        .expect("derive at assert cutoff");
    assert!(matches!(
        cell(&late.cut, "mint-a", "name"),
        FieldState::Covered { .. }
    ));
}

#[test]
fn an_open_gap_becomes_a_derived_cell_and_a_terminal_recovery_clears_it() {
    let catalog = catalog();
    let profile = profile();
    let during = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("gap"), 10)
        .expect("derive at gap cutoff");
    assert_eq!(during.derivation.open_gaps.len(), 1);
    assert!(during.derivation.open_gaps[0].expressed_in_cut);
    assert_eq!(
        during.derivation.open_gaps[0]
            .subject
            .as_ref()
            .map(|value| value.as_str()),
        Some("mint-a")
    );
    assert_eq!(
        cell(&during.cut, "mint-a", "name"),
        FieldState::Gap {
            gap_id: s("gap-mint-a"),
            // Gap knowledge time is the commit that made the gap durable.
            since: t("2026-08-18T10:10:00.000000Z")
        }
    );

    let after = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("recover"), 10)
        .expect("derive at recovery cutoff");
    assert!(after.derivation.open_gaps.is_empty());
    // The cell falls back to its assertion evidence. By 10:15 that evidence is older than the
    // profile's 60s cadence, so the recomputed state is stale rather than covered.
    assert!(matches!(
        cell(&after.cut, "mint-a", "name"),
        FieldState::Stale { .. }
    ));
}

#[test]
fn stale_age_is_recomputed_against_each_cutoff() {
    let catalog = catalog();
    let profile = profile();
    let early = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("assert"), 10)
        .expect("derive");
    let late = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("recover"), 10)
        .expect("derive");
    let age = |state: FieldState| match state {
        FieldState::Stale { age_seconds, .. } => age_seconds.get(),
        other => panic!("expected a stale cell, got {other:?}"),
    };
    // 10:05:00 - 09:50:00 and 10:15:00 - 09:50:00 against the same stored assertion.
    assert_eq!(age(cell(&early.cut, "mint-a", "mint")), 900);
    assert_eq!(age(cell(&late.cut, "mint-a", "mint")), 1_500);
}

#[test]
fn an_uncommitted_cutoff_is_refused_rather_than_projected() {
    let catalog = catalog();
    let profile = profile();
    let beyond = catalog.seq.values().max().copied().expect("commits") + 1;
    let error = catalog
        .open()
        .derive_surface_cut(&profile, beyond, 10)
        .expect_err("uncommitted cutoff");
    assert!(matches!(
        error,
        crate::SurfaceReadbackError::UnknownCutoff { .. }
    ));
}

#[test]
fn an_unregistered_surface_source_is_named_rather_than_silently_empty() {
    let catalog = catalog();
    let mut profile = profile();
    profile.surfaces[1].source = s("never-registered");
    profile.profile_digest = profile.computed_digest().expect("profile digest");
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("assert"), 10)
        .expect("derive");
    assert!(
        derived
            .derivation
            .unresolved
            .contains(&UnresolvedSurfaceInput::SurfaceSourceNotRegistered)
    );
    let binding = derived
        .derivation
        .bindings
        .iter()
        .find(|value| value.surface_id.as_str() == "chain-lifecycle")
        .expect("binding row");
    assert!(binding.catalog_source_id.is_none());
    let bound: BTreeSet<_> = derived
        .derivation
        .bindings
        .iter()
        .filter_map(|value| value.catalog_source_id.as_ref())
        .map(|value| value.as_str().to_owned())
        .collect();
    assert_eq!(bound, BTreeSet::from([PUMP.to_owned()]));
}

#[test]
fn a_gap_on_an_unobserved_subject_is_named_rather_than_quietly_dropped() {
    let catalog = catalog();
    let profile = profile();
    let derived = catalog
        .open()
        .derive_surface_cut(&profile, catalog.at("gap-unobserved"), 10)
        .expect("derive at unobserved-gap cutoff");
    let row = derived
        .derivation
        .open_gaps
        .iter()
        .find(|value| value.gap_id.as_str() == "gap-mint-b")
        .expect("the gap is on the receipt");
    // `mint-b` is declared in coverage but was never observed, so no cut row can carry the gap.
    assert!(!row.expressed_in_cut);
    assert!(
        derived
            .derivation
            .unresolved
            .contains(&UnresolvedSurfaceInput::GapCellsForUnobservedSubjects)
    );
    assert!(matches!(
        cell(&derived.cut, "mint-b", "name"),
        FieldState::Unknown { .. }
    ));
}
