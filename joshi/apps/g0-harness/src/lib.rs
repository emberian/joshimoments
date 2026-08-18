//! Adapter-free G0 fault/backup qualification harness.
//!
//! This package is intentionally not part of the root workspace.  It freezes
//! the Phase-0 witness shape and deterministic fake crash schedule, but has no
//! store, collector, publication, pairing, Glass, export, or backup adapter.
//! Consequently every current step is typed `not_implemented` or `blocked` and
//! this package can never emit a positive `fullOfflineFaultWalk` claim.

use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use std::collections::BTreeSet;
use thiserror::Error;

pub const MANIFEST_CONTRACT: &str = "joshi.g0.fault_run_manifest.v1";
pub const RESULT_CONTRACT: &str = "joshi.g0.fault_result.v1";
pub const SCHEDULE_CONTRACT: &str = "joshi.g0.fake_fault_schedule.v1";
pub const EVIDENCE_CONTRACT: &str = "joshi.g0.evidence_bundle.v1";
pub const BACKUP_REQUIREMENTS_CONTRACT: &str = "joshi.g0.backup_requirements.v1";
pub const AUTHORITY_CEILING: &str = "fixture_harness_no_execution";
pub const SCHEMA_VERSION: u16 = 1;

/// Published top-level JSON Schema documents. The Rust DTO deserializers and
/// validators below are the strict schema authority: they refuse unknown nested
/// fields, literals, exact step coverage/order, digest closure, and promotion.
pub const RUN_MANIFEST_JSON_SCHEMA: &str = r#"{
  "$schema":"https://json-schema.org/draft/2020-12/schema",
  "$id":"joshi.g0.fault_run_manifest.v1",
  "type":"object","additionalProperties":false,
  "required":["contract","schemaVersion","runId","buildDigest","fixtureDigest","scheduleDigest","steps","authority","requestedFullOfflineFaultWalk"],
  "properties":{
    "contract":{"const":"joshi.g0.fault_run_manifest.v1"},
    "schemaVersion":{"const":1},
    "runId":{"type":"string","pattern":"^[a-z0-9_.-]{1,160}$"},
    "buildDigest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},
    "fixtureDigest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},
    "scheduleDigest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},
    "steps":{"type":"array","minItems":18,"maxItems":18,"uniqueItems":true},
    "authority":{"const":"fixture_harness_no_execution"},
    "requestedFullOfflineFaultWalk":{"const":false}
  }
}"#;
pub const RESULT_JSON_SCHEMA: &str = r#"{
  "$schema":"https://json-schema.org/draft/2020-12/schema",
  "$id":"joshi.g0.fault_result.v1",
  "type":"object","additionalProperties":false,
  "required":["contract","schemaVersion","manifestDigest","scheduleDigest","stepResults","evidenceBundle","qualification","authority"],
  "properties":{
    "contract":{"const":"joshi.g0.fault_result.v1"},
    "schemaVersion":{"const":1},
    "manifestDigest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},
    "scheduleDigest":{"type":"string","pattern":"^sha256:[0-9a-f]{64}$"},
    "stepResults":{"type":"array","minItems":18,"maxItems":18},
    "evidenceBundle":{"type":"object"},
    "qualification":{"type":"object","properties":{"fullOfflineFaultWalk":{"const":false}}},
    "authority":{"const":"fixture_harness_no_execution"}
  }
}"#;

#[derive(Debug, Error)]
pub enum HarnessError {
    #[error("invalid G0 {field}: {detail}")]
    Invalid { field: &'static str, detail: String },
    #[error("G0 JSON decode failed: {0}")]
    Json(#[from] serde_json::Error),
}

pub type Result<T> = std::result::Result<T, HarnessError>;

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HarnessStep {
    PreIoReservation,
    OriginFsync,
    StoreReceipt,
    CatalogBinding,
    CatalogAck,
    SemanticFact,
    PublicationPrepare,
    PublicationHead,
    PairingExchange,
    GlassRead,
    MemoryAct,
    MemoryEpisode,
    Export,
    Import,
    Status,
    Backup,
    Restore,
    Reopen,
}

pub const REQUIRED_STEPS: [HarnessStep; 18] = [
    HarnessStep::PreIoReservation,
    HarnessStep::OriginFsync,
    HarnessStep::StoreReceipt,
    HarnessStep::CatalogBinding,
    HarnessStep::CatalogAck,
    HarnessStep::SemanticFact,
    HarnessStep::PublicationPrepare,
    HarnessStep::PublicationHead,
    HarnessStep::PairingExchange,
    HarnessStep::GlassRead,
    HarnessStep::MemoryAct,
    HarnessStep::MemoryEpisode,
    HarnessStep::Export,
    HarnessStep::Import,
    HarnessStep::Status,
    HarnessStep::Backup,
    HarnessStep::Restore,
    HarnessStep::Reopen,
];

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct G0RunManifest {
    pub contract: String,
    pub schema_version: u16,
    pub run_id: String,
    pub build_digest: String,
    pub fixture_digest: String,
    pub schedule_digest: String,
    pub steps: Vec<HarnessStep>,
    pub authority: String,
    pub requested_full_offline_fault_walk: bool,
}

impl G0RunManifest {
    pub fn validate(&self) -> Result<()> {
        require_literal("manifest.contract", &self.contract, MANIFEST_CONTRACT)?;
        require_version("manifest.schemaVersion", self.schema_version)?;
        require_identifier("manifest.runId", &self.run_id)?;
        require_digest("manifest.buildDigest", &self.build_digest)?;
        require_digest("manifest.fixtureDigest", &self.fixture_digest)?;
        require_digest("manifest.scheduleDigest", &self.schedule_digest)?;
        require_literal("manifest.authority", &self.authority, AUTHORITY_CEILING)?;
        if self.requested_full_offline_fault_walk {
            return invalid(
                "manifest.requestedFullOfflineFaultWalk",
                "must be false for this adapter-free harness",
            );
        }
        require_exact_steps("manifest.steps", &self.steps)
    }

    pub fn digest(&self) -> Result<String> {
        self.validate()?;
        let bytes = serde_json::to_vec(self).map_err(HarnessError::Json)?;
        Ok(domain_digest(b"joshi.g0.run_manifest.v1\0", [&bytes]))
    }
}

pub fn parse_run_manifest(bytes: &[u8]) -> Result<G0RunManifest> {
    let manifest: G0RunManifest = serde_json::from_slice(bytes)?;
    manifest.validate()?;
    Ok(manifest)
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum StepDisposition {
    NotImplemented,
    Blocked,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StepResult {
    pub step: HarnessStep,
    pub disposition: StepDisposition,
    pub code: String,
    pub detail: String,
    pub recovery_invariants: Vec<RecoveryInvariant>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecoveryInvariant {
    PrefixIsDurableOrAbsent,
    RetryUsesSameIdempotencyIdentity,
    NoDuplicateOrConflictingReceipt,
    OriginBytesRemainImmutable,
    CatalogAckNeverAuthorizesDeletion,
    ReopenReadsOnlyCommittedPrefix,
    BackupReadbackMatchesManifest,
    NoSyntheticFactOrPublication,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceRole {
    Reservation,
    OriginSegment,
    StoreReceipt,
    CatalogBinding,
    CatalogAck,
    SemanticFact,
    PublicationPrepare,
    PublicationHead,
    PairingExchange,
    GlassRead,
    MemoryAct,
    MemoryEpisode,
    ExportManifest,
    ImportReceipt,
    StatusReadback,
    BackupManifest,
    RestoreReadback,
    ReopenReadback,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceItem {
    pub role: EvidenceRole,
    pub evidence_id: String,
    pub content_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceBundle {
    pub contract: String,
    pub items: Vec<EvidenceItem>,
    pub digest: String,
}

impl EvidenceBundle {
    #[must_use]
    pub fn empty() -> Self {
        let mut bundle = Self {
            contract: EVIDENCE_CONTRACT.into(),
            items: Vec::new(),
            digest: String::new(),
        };
        bundle.digest = bundle
            .recompute_digest()
            .expect("empty evidence bundle is valid");
        bundle
    }

    pub fn recompute_digest(&self) -> Result<String> {
        require_literal("evidenceBundle.contract", &self.contract, EVIDENCE_CONTRACT)?;
        let mut last: Option<(EvidenceRole, &str)> = None;
        for item in &self.items {
            require_identifier("evidenceBundle.items.evidenceId", &item.evidence_id)?;
            require_digest("evidenceBundle.items.contentDigest", &item.content_digest)?;
            if let Some(previous) = last
                && (item.role, item.evidence_id.as_str()) <= previous
            {
                return invalid(
                    "evidenceBundle.items",
                    "must be strictly sorted by role then evidenceId without duplicates",
                );
            }
            last = Some((item.role, item.evidence_id.as_str()));
        }
        let mut hasher = Sha256::new();
        hasher.update(b"joshi.g0.evidence_bundle.v1\0");
        hasher.update((self.items.len() as u64).to_be_bytes());
        for item in &self.items {
            hasher.update((item.role as u8).to_be_bytes());
            hash_length_prefixed(&mut hasher, item.evidence_id.as_bytes());
            hash_length_prefixed(&mut hasher, item.content_digest.as_bytes());
        }
        Ok(format!("sha256:{:x}", hasher.finalize()))
    }

    pub fn validate(&self) -> Result<()> {
        let actual = self.recompute_digest()?;
        if actual != self.digest {
            return invalid(
                "evidenceBundle.digest",
                "does not equal the domain-separated digest of the exact ordered items",
            );
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Qualification {
    pub full_offline_fault_walk: bool,
    pub ceiling: String,
    pub disqualifiers: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct G0Result {
    pub contract: String,
    pub schema_version: u16,
    pub manifest_digest: String,
    pub schedule_digest: String,
    pub step_results: Vec<StepResult>,
    pub evidence_bundle: EvidenceBundle,
    pub qualification: Qualification,
    pub authority: String,
}

impl G0Result {
    pub fn validate(&self) -> Result<()> {
        require_literal("result.contract", &self.contract, RESULT_CONTRACT)?;
        require_version("result.schemaVersion", self.schema_version)?;
        require_digest("result.manifestDigest", &self.manifest_digest)?;
        require_digest("result.scheduleDigest", &self.schedule_digest)?;
        require_literal("result.authority", &self.authority, AUTHORITY_CEILING)?;
        if self.qualification.full_offline_fault_walk {
            return invalid(
                "result.qualification.fullOfflineFaultWalk",
                "this harness has no adapters and must always emit false",
            );
        }
        require_literal(
            "result.qualification.ceiling",
            &self.qualification.ceiling,
            AUTHORITY_CEILING,
        )?;
        if self.qualification.disqualifiers.is_empty() {
            return invalid(
                "result.qualification.disqualifiers",
                "must name the non-qualification blockers",
            );
        }
        let actual_steps: Vec<_> = self.step_results.iter().map(|result| result.step).collect();
        require_exact_steps("result.stepResults", &actual_steps)?;
        for result in &self.step_results {
            if result.code.is_empty() || result.detail.is_empty() {
                return invalid(
                    "result.stepResults",
                    "typed disposition requires a nonempty code and detail",
                );
            }
            if result.recovery_invariants.is_empty() {
                return invalid(
                    "result.stepResults.recoveryInvariants",
                    "must state restart/idempotency invariants",
                );
            }
        }
        self.evidence_bundle.validate()
    }
}

pub fn parse_result(bytes: &[u8]) -> Result<G0Result> {
    let result: G0Result = serde_json::from_slice(bytes)?;
    result.validate()?;
    Ok(result)
}

/// Explicit crash/kill points. They name a potential process termination after
/// the corresponding seam has attempted its durable transition; an adapter must
/// bind the exact lower-level fsync/commit boundary before use.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum KillPoint {
    AfterPreIoReservation,
    AfterOriginFsync,
    AfterStoreReceipt,
    AfterCatalogBinding,
    AfterCatalogAck,
    AfterSemanticFact,
    AfterPublicationPrepare,
    AfterPublicationHead,
    AfterPairingExchange,
    AfterGlassRead,
    AfterMemoryAct,
    AfterMemoryEpisode,
    AfterExport,
    AfterImport,
    AfterStatus,
    AfterBackup,
    AfterRestore,
    AfterReopen,
}

/// The full crash namespace includes a pre-transition process loss as well as
/// every named post-transition kill point. A real adapter may refine one of
/// these into its local fsync/commit failpoints, but may not erase it.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CrashPoint {
    BeforePreIoReservation,
    BeforeOriginFsync,
    BeforeStoreReceipt,
    BeforeCatalogBinding,
    BeforeCatalogAck,
    BeforeSemanticFact,
    BeforePublicationPrepare,
    BeforePublicationHead,
    BeforePairingExchange,
    BeforeGlassRead,
    BeforeMemoryAct,
    BeforeMemoryEpisode,
    BeforeExport,
    BeforeImport,
    BeforeStatus,
    BeforeBackup,
    BeforeRestore,
    BeforeReopen,
    After(KillPoint),
}

pub const PRE_TRANSITION_CRASH_POINTS: [CrashPoint; 18] = [
    CrashPoint::BeforePreIoReservation,
    CrashPoint::BeforeOriginFsync,
    CrashPoint::BeforeStoreReceipt,
    CrashPoint::BeforeCatalogBinding,
    CrashPoint::BeforeCatalogAck,
    CrashPoint::BeforeSemanticFact,
    CrashPoint::BeforePublicationPrepare,
    CrashPoint::BeforePublicationHead,
    CrashPoint::BeforePairingExchange,
    CrashPoint::BeforeGlassRead,
    CrashPoint::BeforeMemoryAct,
    CrashPoint::BeforeMemoryEpisode,
    CrashPoint::BeforeExport,
    CrashPoint::BeforeImport,
    CrashPoint::BeforeStatus,
    CrashPoint::BeforeBackup,
    CrashPoint::BeforeRestore,
    CrashPoint::BeforeReopen,
];

impl KillPoint {
    #[must_use]
    pub const fn step(self) -> HarnessStep {
        match self {
            Self::AfterPreIoReservation => HarnessStep::PreIoReservation,
            Self::AfterOriginFsync => HarnessStep::OriginFsync,
            Self::AfterStoreReceipt => HarnessStep::StoreReceipt,
            Self::AfterCatalogBinding => HarnessStep::CatalogBinding,
            Self::AfterCatalogAck => HarnessStep::CatalogAck,
            Self::AfterSemanticFact => HarnessStep::SemanticFact,
            Self::AfterPublicationPrepare => HarnessStep::PublicationPrepare,
            Self::AfterPublicationHead => HarnessStep::PublicationHead,
            Self::AfterPairingExchange => HarnessStep::PairingExchange,
            Self::AfterGlassRead => HarnessStep::GlassRead,
            Self::AfterMemoryAct => HarnessStep::MemoryAct,
            Self::AfterMemoryEpisode => HarnessStep::MemoryEpisode,
            Self::AfterExport => HarnessStep::Export,
            Self::AfterImport => HarnessStep::Import,
            Self::AfterStatus => HarnessStep::Status,
            Self::AfterBackup => HarnessStep::Backup,
            Self::AfterRestore => HarnessStep::Restore,
            Self::AfterReopen => HarnessStep::Reopen,
        }
    }
}

pub const KILL_POINTS: [KillPoint; 18] = [
    KillPoint::AfterPreIoReservation,
    KillPoint::AfterOriginFsync,
    KillPoint::AfterStoreReceipt,
    KillPoint::AfterCatalogBinding,
    KillPoint::AfterCatalogAck,
    KillPoint::AfterSemanticFact,
    KillPoint::AfterPublicationPrepare,
    KillPoint::AfterPublicationHead,
    KillPoint::AfterPairingExchange,
    KillPoint::AfterGlassRead,
    KillPoint::AfterMemoryAct,
    KillPoint::AfterMemoryEpisode,
    KillPoint::AfterExport,
    KillPoint::AfterImport,
    KillPoint::AfterStatus,
    KillPoint::AfterBackup,
    KillPoint::AfterRestore,
    KillPoint::AfterReopen,
];

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CrashMode {
    ProcessKill,
    PowerLoss,
    Panic,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FaultScenario {
    pub scenario_id: String,
    pub crash_mode: CrashMode,
    pub crash_point: Option<CrashPoint>,
    pub expected_invariants: Vec<RecoveryInvariant>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct FakeFaultSchedule {
    pub contract: String,
    pub schema_version: u16,
    pub schedule_id: String,
    pub scenarios: Vec<FaultScenario>,
}

impl FakeFaultSchedule {
    pub fn validate(&self) -> Result<()> {
        require_literal("schedule.contract", &self.contract, SCHEDULE_CONTRACT)?;
        require_version("schedule.schemaVersion", self.schema_version)?;
        require_identifier("schedule.scheduleId", &self.schedule_id)?;
        if self.scenarios.len() != (KILL_POINTS.len() * 2) + 1 {
            return invalid(
                "schedule.scenarios",
                "must contain the baseline plus exactly one pre- and post-transition scenario for each required step",
            );
        }
        let baseline = self
            .scenarios
            .first()
            .ok_or_else(|| HarnessError::Invalid {
                field: "schedule.scenarios",
                detail: "baseline scenario is missing".into(),
            })?;
        if baseline.scenario_id != "baseline_no_fault" || baseline.crash_point.is_some() {
            return invalid(
                "schedule.scenarios[0]",
                "must be baseline_no_fault with no kill point",
            );
        }
        let actual: BTreeSet<_> = self
            .scenarios
            .iter()
            .skip(1)
            .filter_map(|scenario| scenario.crash_point)
            .collect();
        let mut expected = BTreeSet::from(PRE_TRANSITION_CRASH_POINTS);
        for point in KILL_POINTS {
            expected.insert(CrashPoint::After(point));
        }
        if actual != expected
            || self
                .scenarios
                .iter()
                .skip(1)
                .any(|scenario| scenario.crash_point.is_none())
        {
            return invalid(
                "schedule.scenarios",
                "must cover each enumerated pre- and post-transition crash point exactly once",
            );
        }
        if self
            .scenarios
            .iter()
            .any(|scenario| scenario.expected_invariants.is_empty())
        {
            return invalid("schedule.scenarios.expectedInvariants", "must be nonempty");
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<String> {
        self.validate()?;
        let bytes = serde_json::to_vec(self).map_err(HarnessError::Json)?;
        Ok(domain_digest(
            b"joshi.g0.fake_fault_schedule.v1\0",
            [&bytes],
        ))
    }
}

#[must_use]
pub fn deterministic_fake_schedule() -> FakeFaultSchedule {
    let mut scenarios = vec![FaultScenario {
        scenario_id: "baseline_no_fault".into(),
        crash_mode: CrashMode::ProcessKill,
        crash_point: None,
        expected_invariants: common_invariants(),
    }];
    for (index, point) in PRE_TRANSITION_CRASH_POINTS.into_iter().enumerate() {
        scenarios.push(FaultScenario {
            scenario_id: format!("{:02}_before_{point:?}", index + 1).to_lowercase(),
            crash_mode: match index % 3 {
                0 => CrashMode::ProcessKill,
                1 => CrashMode::PowerLoss,
                _ => CrashMode::Panic,
            },
            crash_point: Some(point),
            expected_invariants: common_invariants(),
        });
    }
    for (index, point) in KILL_POINTS.into_iter().enumerate() {
        scenarios.push(FaultScenario {
            scenario_id: format!("{:02}_after_{:?}", index + 1, point).to_lowercase(),
            crash_mode: match (index + 18) % 3 {
                0 => CrashMode::ProcessKill,
                1 => CrashMode::PowerLoss,
                _ => CrashMode::Panic,
            },
            crash_point: Some(CrashPoint::After(point)),
            expected_invariants: invariants_for(point.step()),
        });
    }
    FakeFaultSchedule {
        contract: SCHEDULE_CONTRACT.into(),
        schema_version: SCHEMA_VERSION,
        schedule_id: "g0_fake_full_boundary_matrix".into(),
        scenarios,
    }
}

/// Current deterministic outcome. Adapter absence is a result, not a success
/// surrogate: callers get all required typed outcomes and a hard false ceiling.
pub fn run_fake_schedule(
    manifest: &G0RunManifest,
    schedule: &FakeFaultSchedule,
) -> Result<G0Result> {
    manifest.validate()?;
    schedule.validate()?;
    let manifest_digest = manifest.digest()?;
    let schedule_digest = schedule.digest()?;
    if manifest.schedule_digest != schedule_digest {
        return invalid(
            "manifest.scheduleDigest",
            "does not bind the supplied deterministic schedule",
        );
    }
    let step_results = REQUIRED_STEPS.into_iter().map(|step| StepResult {
        step,
        disposition: if matches!(step, HarnessStep::SemanticFact | HarnessStep::PublicationPrepare | HarnessStep::PublicationHead | HarnessStep::PairingExchange | HarnessStep::GlassRead | HarnessStep::MemoryAct | HarnessStep::MemoryEpisode | HarnessStep::Export | HarnessStep::Import | HarnessStep::Backup | HarnessStep::Restore) { StepDisposition::Blocked } else { StepDisposition::NotImplemented },
        code: format!("G0_{step:?}_ADAPTER_ABSENT").to_uppercase(),
        detail: "No integrated owner adapter is installed; no receipt, fact, publication, readback, or recovery success is synthesized.".into(),
        recovery_invariants: invariants_for(step),
    }).collect();
    let result = G0Result {
        contract: RESULT_CONTRACT.into(),
        schema_version: SCHEMA_VERSION,
        manifest_digest,
        schedule_digest,
        step_results,
        evidence_bundle: EvidenceBundle::empty(),
        authority: AUTHORITY_CEILING.into(),
        qualification: Qualification {
            full_offline_fault_walk: false,
            ceiling: AUTHORITY_CEILING.into(),
            disqualifiers: vec![
                "adapter_absent".into(),
                "all_required_receipt_seams_not_observed".into(),
                "backup_restore_readback_not_observed".into(),
            ],
        },
    };
    result.validate()?;
    Ok(result)
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BackupArtifact {
    CatalogSnapshot,
    ReferencedArtifactInventory,
    PrivateMaterialInventory,
    OriginSpoolInventory,
    BackupManifest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BackupArtifactRequirement {
    pub artifact: BackupArtifact,
    pub required_contents: Vec<String>,
    pub required_readback: Vec<String>,
}

#[must_use]
pub fn backup_artifact_requirements() -> Vec<BackupArtifactRequirement> {
    vec![
        BackupArtifactRequirement {
            artifact: BackupArtifact::CatalogSnapshot,
            required_contents: vec![
                "consistent SQLite snapshot bytes".into(),
                "maximum included commit sequence".into(),
                "application and migration identity".into(),
                "SHA-256 physical digest and byte count".into(),
            ],
            required_readback: vec![
                "SQLite integrity_check is ok".into(),
                "foreign_key_check has no rows".into(),
                "catalog binding and operational records reopen at the declared cutoff".into(),
            ],
        },
        BackupArtifactRequirement {
            artifact: BackupArtifact::ReferencedArtifactInventory,
            required_contents: vec![
                "every catalog-referenced origin segment, publication body/head, export object, and CAS blob path, byte count, and SHA-256".into(),
                "no missing referenced artifact".into(),
            ],
            required_readback: vec![
                "restore is performed into a distinct empty root, without the original paths available".into(),
                "every listed origin/publication/export/CAS byte object is opened and rehashes".into(),
                "unreferenced extras are reported, never substituted".into(),
            ],
        },
        BackupArtifactRequirement {
            artifact: BackupArtifact::PrivateMaterialInventory,
            required_contents: vec![
                "retention/encryption class and key identifier only".into(),
                "erasure/tombstone disposition".into(),
            ],
            required_readback: vec![
                "private bytes remain unavailable without key-policy authority".into(),
                "disposed content is absent where policy requires".into(),
            ],
        },
        BackupArtifactRequirement {
            artifact: BackupArtifact::OriginSpoolInventory,
            required_contents: vec![
                "immutable origin segment identity, byte count, and SHA-256".into(),
                "catalog ACK is explicitly non-deletion authority".into(),
            ],
            required_readback: vec![
                "origin bytes match their recorded digest".into(),
                "retry does not create a conflicting segment".into(),
            ],
        },
        BackupArtifactRequirement {
            artifact: BackupArtifact::BackupManifest,
            required_contents: vec![
                "all artifact digests/counts/byte totals".into(),
                "backup time, cutoff, retention and encryption metadata".into(),
                "exact evidence-bundle digest".into(),
            ],
            required_readback: vec![
                "manifest digest rederives from canonical ordered entries".into(),
                "restore then reopen matches declared cutoff".into(),
            ],
        },
    ]
}

fn common_invariants() -> Vec<RecoveryInvariant> {
    vec![
        RecoveryInvariant::PrefixIsDurableOrAbsent,
        RecoveryInvariant::RetryUsesSameIdempotencyIdentity,
        RecoveryInvariant::NoDuplicateOrConflictingReceipt,
        RecoveryInvariant::ReopenReadsOnlyCommittedPrefix,
    ]
}

fn invariants_for(step: HarnessStep) -> Vec<RecoveryInvariant> {
    let mut values = common_invariants();
    if matches!(
        step,
        HarnessStep::OriginFsync
            | HarnessStep::StoreReceipt
            | HarnessStep::CatalogBinding
            | HarnessStep::CatalogAck
    ) {
        values.push(RecoveryInvariant::OriginBytesRemainImmutable);
    }
    if matches!(step, HarnessStep::CatalogAck) {
        values.push(RecoveryInvariant::CatalogAckNeverAuthorizesDeletion);
    }
    if matches!(
        step,
        HarnessStep::SemanticFact
            | HarnessStep::PublicationPrepare
            | HarnessStep::PublicationHead
            | HarnessStep::PairingExchange
            | HarnessStep::GlassRead
            | HarnessStep::MemoryAct
            | HarnessStep::MemoryEpisode
            | HarnessStep::Status
    ) {
        values.push(RecoveryInvariant::NoSyntheticFactOrPublication);
    }
    if matches!(
        step,
        HarnessStep::Backup | HarnessStep::Restore | HarnessStep::Reopen
    ) {
        values.push(RecoveryInvariant::BackupReadbackMatchesManifest);
    }
    values
}

fn require_exact_steps(field: &'static str, actual: &[HarnessStep]) -> Result<()> {
    if actual != REQUIRED_STEPS {
        return invalid(
            field,
            "must contain every required G0 step exactly once in canonical order",
        );
    }
    Ok(())
}

fn require_literal(field: &'static str, actual: &str, expected: &str) -> Result<()> {
    if actual != expected {
        return invalid(field, format!("must equal {expected:?}"));
    }
    Ok(())
}
fn require_version(field: &'static str, actual: u16) -> Result<()> {
    if actual != SCHEMA_VERSION {
        return invalid(field, format!("must equal {SCHEMA_VERSION}"));
    }
    Ok(())
}
fn require_identifier(field: &'static str, value: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 160
        || !value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'-' | b'_' | b'.')
        })
    {
        return invalid(
            field,
            "must be 1..=160 lowercase ASCII identifier characters",
        );
    }
    Ok(())
}
fn require_digest(field: &'static str, value: &str) -> Result<()> {
    let valid = value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte));
    if !valid {
        return invalid(
            field,
            "must be sha256: followed by exactly 64 lowercase hexadecimal characters",
        );
    }
    Ok(())
}
fn invalid<T>(field: &'static str, detail: impl Into<String>) -> Result<T> {
    Err(HarnessError::Invalid {
        field,
        detail: detail.into(),
    })
}
fn hash_length_prefixed(hasher: &mut Sha256, bytes: &[u8]) {
    hasher.update((bytes.len() as u64).to_be_bytes());
    hasher.update(bytes);
}
fn domain_digest<'a>(domain: &[u8], chunks: impl IntoIterator<Item = &'a Vec<u8>>) -> String {
    let mut hasher = Sha256::new();
    hasher.update(domain);
    for chunk in chunks {
        hash_length_prefixed(&mut hasher, chunk);
    }
    format!("sha256:{:x}", hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn digest(seed: &str) -> String {
        let mut value = String::from("sha256:");
        value.push_str(&"a".repeat(64));
        if seed == "b" {
            value.replace_range(7..8, "b");
        }
        value
    }
    fn manifest(schedule: &FakeFaultSchedule) -> G0RunManifest {
        G0RunManifest {
            contract: MANIFEST_CONTRACT.into(),
            schema_version: 1,
            run_id: "g0-fixture-run-1".into(),
            build_digest: digest("a"),
            fixture_digest: digest("b"),
            schedule_digest: schedule.digest().unwrap(),
            steps: REQUIRED_STEPS.to_vec(),
            authority: AUTHORITY_CEILING.into(),
            requested_full_offline_fault_walk: false,
        }
    }
    #[test]
    fn fake_schedule_covers_every_kill_point_once() {
        let schedule = deterministic_fake_schedule();
        schedule.validate().unwrap();
        assert_eq!(schedule.scenarios.len(), 37);
    }
    #[test]
    fn checked_in_schedule_covers_every_kill_point_once() {
        let schedule: FakeFaultSchedule = serde_json::from_slice(include_bytes!(
            "../../../fixtures/g0-fault/fake_fault_schedule.json"
        ))
        .unwrap();
        schedule.validate().unwrap();
    }
    #[test]
    fn missing_step_cannot_qualify() {
        let schedule = deterministic_fake_schedule();
        let mut run = manifest(&schedule);
        run.steps.pop();
        assert!(run.validate().is_err());
        let mut result = run_fake_schedule(&manifest(&schedule), &schedule).unwrap();
        result.step_results.pop();
        assert!(result.validate().is_err());
    }
    #[test]
    fn current_run_is_typed_and_never_promoted() {
        let schedule = deterministic_fake_schedule();
        let result = run_fake_schedule(&manifest(&schedule), &schedule).unwrap();
        assert!(!result.qualification.full_offline_fault_walk);
        assert!(result.step_results.iter().all(|item| matches!(
            item.disposition,
            StepDisposition::NotImplemented | StepDisposition::Blocked
        )));
    }
    #[test]
    fn evidence_digest_refuses_reordering_or_tampering() {
        let mut bundle = EvidenceBundle::empty();
        bundle.items.push(EvidenceItem {
            role: EvidenceRole::Reservation,
            evidence_id: "receipt-1".into(),
            content_digest: digest("a"),
        });
        bundle.digest = bundle.recompute_digest().unwrap();
        bundle.validate().unwrap();
        bundle.items[0].content_digest = digest("b");
        assert!(bundle.validate().is_err());
    }
}
