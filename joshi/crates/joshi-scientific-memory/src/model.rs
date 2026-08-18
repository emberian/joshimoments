use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use std::{collections::BTreeSet, fmt};

const MAX_TEXT: usize = 16 * 1024;

/// Exact wire clock: positive canonical decimal-string logical timeline ticks, preserving u64
/// values in JavaScript.
mod logical_time {
    use serde::{Deserialize, Deserializer, Serialize, Serializer};

    #[allow(clippy::trivially_copy_pass_by_ref)]
    pub fn serialize<S>(value: &super::LogicalSessionTick, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        value.serialize(serializer)
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<super::LogicalSessionTick, D::Error>
    where
        D: Deserializer<'de>,
    {
        super::LogicalSessionTick::deserialize(deserializer)
    }

    pub mod option {
        use serde::{Deserialize, Deserializer, Serializer};

        #[allow(clippy::ref_option)]
        pub fn serialize<S>(
            value: &Option<super::super::LogicalSessionTick>,
            serializer: S,
        ) -> Result<S::Ok, S::Error>
        where
            S: Serializer,
        {
            match value {
                Some(value) => super::serialize(value, serializer),
                None => serializer.serialize_none(),
            }
        }

        pub fn deserialize<'de, D>(
            deserializer: D,
        ) -> Result<Option<super::super::LogicalSessionTick>, D::Error>
        where
            D: Deserializer<'de>,
        {
            Option::<super::super::LogicalSessionTick>::deserialize(deserializer)
        }
    }
}

fn parse_positive_decimal_string(value: &str, kind: &str) -> Result<u64, String> {
    if value.is_empty()
        || value == "0"
        || value.starts_with('0')
        || !value.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(format!("invalid positive canonical decimal-string {kind}"));
    }
    value
        .parse::<u64>()
        .map_err(|_| format!("invalid positive canonical decimal-string {kind}"))
}

/// Session-local logical tick. This is deliberately distinct from `CatalogCommitSeq` even though
/// both use a positive decimal-string wire representation.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Hash)]
pub struct LogicalSessionTick(u64);

impl LogicalSessionTick {
    /// Creates a positive session-local logical tick.
    ///
    /// # Errors
    ///
    /// Returns an error for zero, which is not a valid cutoff/timeline tick.
    pub fn new(value: u64) -> Result<Self, String> {
        if value == 0 {
            return Err("logical session tick must be positive".into());
        }
        Ok(Self(value))
    }

    /// Returns the numeric tick for same-domain comparisons.
    #[must_use]
    pub const fn value(self) -> u64 {
        self.0
    }
}

impl serde::Serialize for LogicalSessionTick {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(&self.0.to_string())
    }
}

impl<'de> serde::Deserialize<'de> for LogicalSessionTick {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        parse_positive_decimal_string(&value, "LogicalSessionTick")
            .map(Self)
            .map_err(serde::de::Error::custom)
    }
}

/// Immutable catalog commit sequence; it is not a session clock tick.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Hash)]
pub struct CatalogCommitSeq(u64);

impl CatalogCommitSeq {
    /// Creates a positive catalog commit sequence.
    ///
    /// # Errors
    ///
    /// Returns an error for zero, which is not a valid immutable catalog cutoff.
    pub fn new(value: u64) -> Result<Self, String> {
        if value == 0 {
            return Err("catalog commit sequence must be positive".into());
        }
        Ok(Self(value))
    }

    /// Returns the numeric sequence for same-domain comparisons.
    #[must_use]
    pub const fn value(self) -> u64 {
        self.0
    }
}

impl serde::Serialize for CatalogCommitSeq {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(&self.0.to_string())
    }
}

impl<'de> serde::Deserialize<'de> for CatalogCommitSeq {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        parse_positive_decimal_string(&value, "CatalogCommitSeq")
            .map(Self)
            .map_err(serde::de::Error::custom)
    }
}

macro_rules! id_type {
    ($name:ident) => {
        #[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            /// Creates a bounded stable identifier.
            ///
            /// # Errors
            ///
            /// Returns an error for empty, padded, control-bearing, or oversized values.
            pub fn new(value: impl Into<String>) -> Result<Self, String> {
                let value = value.into();
                if value.is_empty()
                    || value.len() > 255
                    || value.trim() != value
                    || value.chars().any(char::is_control)
                {
                    return Err(format!("invalid {}", stringify!($name)));
                }
                Ok(Self(value))
            }

            /// Returns the exact identifier.
            #[must_use]
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str(&self.0)
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
            where
                D: serde::Deserializer<'de>,
            {
                let value = String::deserialize(deserializer)?;
                Self::new(value).map_err(serde::de::Error::custom)
            }
        }
    };
}

id_type!(SceneId);
id_type!(PresentationId);
id_type!(PresentationOccurrenceId);
id_type!(ActId);
id_type!(SessionId);
id_type!(EpisodeId);
id_type!(SegmentId);
id_type!(CorrectionId);
id_type!(OntologyVersionId);
id_type!(AssertionId);
id_type!(ReplayId);
id_type!(KnowledgeClosureId);
id_type!(OutcomeId);
id_type!(InterviewId);

/// SHA-256 value in an explicit digest domain.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct Digest(String);

impl Digest {
    /// Parses a qualified SHA-256 digest.
    ///
    /// # Errors
    ///
    /// Returns an error when the value is not `sha256:` followed by 64 lowercase hex digits.
    pub fn new(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into();
        let valid = value.strip_prefix("sha256:").is_some_and(|hex| {
            hex.len() == 64
                && hex
                    .chars()
                    .all(|character| character.is_ascii_digit() || ('a'..='f').contains(&character))
        });
        if !valid {
            return Err("invalid SHA-256 digest".into());
        }
        Ok(Self(value))
    }

    /// Returns the exact digest text.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Computes a SHA-256 digest over bytes.
    #[must_use]
    pub fn of_bytes(bytes: &[u8]) -> Self {
        let mut digest = Sha256::new();
        digest.update(bytes);
        Self(format!("sha256:{:x}", digest.finalize()))
    }
}

impl<'de> Deserialize<'de> for Digest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(serde::de::Error::custom)
    }
}

/// Exact committed scene/publication reference.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SceneRef {
    pub scene_id: SceneId,
    pub scene_digest: Digest,
    pub catalog_cutoff: CatalogCommitSeq,
}

/// Actual render/mount occurrence, kept separate from the committed scene.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PresentationOccurrenceRef {
    pub occurrence_id: PresentationOccurrenceId,
    pub presentation_id: PresentationId,
    pub scene: SceneRef,
    pub render_digest: Digest,
    pub viewport: String,
    pub focus: String,
    #[serde(with = "logical_time")]
    pub occurred_at: LogicalSessionTick,
}

/// Typed presentation gap; a missing render never erases an operator act.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PresentationGap {
    pub gap_id: String,
    pub scene: Option<SceneRef>,
    pub reason: PresentationGapReason,
    #[serde(with = "logical_time")]
    pub detected_at: LogicalSessionTick,
}

/// Separate append-only repair/supersession of a prior presentation gap.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PresentationGapRepair {
    pub repair_id: PresentationOccurrenceId,
    pub gap_id: String,
    pub replacement: PresentationOccurrenceRef,
    #[serde(with = "logical_time")]
    pub recorded_at: LogicalSessionTick,
}

/// Why actual presentation evidence is unavailable.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PresentationGapReason {
    NotMounted,
    CaptureFailed,
    NavigationUnknown,
    Restart,
    Unavailable,
}

/// Scene binding retained with every act.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
#[serde(deny_unknown_fields)]
pub enum SceneBinding {
    Committed(SceneRef),
    Missing { reason: String },
}

/// Presentation binding retained with every act.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", content = "value", rename_all = "snake_case")]
#[serde(deny_unknown_fields)]
pub enum PresentationBinding {
    Occurrence(PresentationOccurrenceRef),
    Gap(PresentationGap),
}

/// A required, bounded declaration explaining why the operator left the managed path.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct ExternalManualExecutionEscapeReason(String);

impl ExternalManualExecutionEscapeReason {
    /// Creates a nonempty, unpadded reason for an external manual execution escape.
    ///
    /// # Errors
    ///
    /// Returns an error for empty, padded, oversized, or control-bearing text.
    pub fn new(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into();
        validate_text(&value, "manual execution escape reason")?;
        if value.trim() != value {
            return Err("manual execution escape reason is padded".into());
        }
        Ok(Self(value))
    }

    /// Returns the exact declared reason.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for ExternalManualExecutionEscapeReason {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(serde::de::Error::custom)
    }
}

/// Stable coarse act taxonomy. Intentions describe operator intent only; they are never fills.
#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub enum ActKind {
    Notice,
    Inspect,
    Compare,
    Mark,
    WatchFlat,
    ArmShadow,
    DeclareTakeSome,
    DeclareKeepRemainder,
    ZapIntent,
    DeclareReentry,
    DeclareClose,
    ExternalManualExecutionEscape {
        reason: ExternalManualExecutionEscapeReason,
    },
    Correct,
}

impl ActKind {
    /// Whether the act is an evidence-only action intention rather than observation.
    #[must_use]
    pub const fn is_action_intention(&self) -> bool {
        matches!(
            self,
            Self::DeclareTakeSome
                | Self::DeclareKeepRemainder
                | Self::ZapIntent
                | Self::DeclareReentry
                | Self::DeclareClose
                | Self::ExternalManualExecutionEscape { .. }
        )
    }
}

/// Optional operator assertion retained independently of the stable act.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OperatorAssertion {
    pub assertion_id: AssertionId,
    pub disposition: AssertionDisposition,
}

/// Multi-valued assertion disposition; absence and inability to articulate are first-class.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    content = "value",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum AssertionDisposition {
    Verbatim { text: String },
    Opaque { token_digest: Digest },
    CannotArticulate,
}

/// Immediately retained operator act. The `presentation` may be a typed gap.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OperatorAct {
    pub act_id: ActId,
    pub session_id: SessionId,
    #[serde(with = "logical_time")]
    pub occurred_at: LogicalSessionTick,
    pub scene: SceneBinding,
    pub presentation: PresentationBinding,
    pub kind: ActKind,
    pub subject: Option<String>,
    pub assertion: Option<OperatorAssertion>,
}

/// Append-only correction naming the prior act; the source act remains immutable.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ActCorrection {
    pub correction_id: CorrectionId,
    pub act_id: ActId,
    pub corrected_kind: Option<ActKind>,
    pub corrected_subject: Option<String>,
    pub reason: String,
    #[serde(with = "logical_time")]
    pub recorded_at: LogicalSessionTick,
}

/// Versioned ontology mapping; historical acts are never rewritten.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OntologyVersion {
    pub version_id: OntologyVersionId,
    pub parent_version_id: Option<OntologyVersionId>,
    #[serde(with = "logical_time")]
    pub effective_at: LogicalSessionTick,
    pub mappings: Vec<OntologyMapping>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OntologyMapping {
    pub stable_kind: ActKind,
    pub label: String,
}

/// Bounded episode segment; no transaction, fill, or execution field exists in this contract.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EpisodeSegment {
    pub segment_id: SegmentId,
    #[serde(with = "logical_time")]
    pub start_at: LogicalSessionTick,
    #[serde(with = "logical_time::option")]
    pub end_at: Option<LogicalSessionTick>,
    pub path: EpisodePath,
    pub effect: EffectStatus,
    pub lot: LotAssociation,
}

/// Scientific-memory episode path vocabulary.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EpisodePath {
    PartialRealization,
    RunnerRetention,
    FullExit,
    FlatWatch,
    Reentry,
    NoTrade,
    UnknownInterval,
    UnresolvedEffect,
}

/// Explicit observational effect state; never inferred from an intention or UI gesture.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
#[serde(deny_unknown_fields)]
pub enum EffectStatus {
    Observed { evidence_digest: Digest },
    Unknown { reason: String },
    Unresolved { reason: String },
    NotApplicableByNoTrade,
}

/// Lot association remains unresolved unless independently witnessed.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
#[serde(deny_unknown_fields)]
pub enum LotAssociation {
    Resolved { lot_id: String },
    Unresolved { reason: String },
    NotApplicable,
}

/// Bounded episode with explicit partial/unknown status.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Episode {
    pub episode_id: EpisodeId,
    pub session_id: SessionId,
    pub act_ids: Vec<ActId>,
    #[serde(with = "logical_time")]
    pub decision_cutoff: LogicalSessionTick,
    #[serde(with = "logical_time")]
    pub started_at: LogicalSessionTick,
    #[serde(with = "logical_time::option")]
    pub ended_at: Option<LogicalSessionTick>,
    pub completeness: EpisodeCompleteness,
    pub segments: Vec<EpisodeSegment>,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EpisodeCompleteness {
    Partial,
    Complete,
    Unknown,
}

/// Outcome visibility phase for two-pass replay.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReplayPhase {
    OutcomeHiddenReconstruction,
    RetrospectiveInterpretation,
}

/// Replay/interview artifact with explicit outcome visibility.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReplayArtifact {
    pub replay_id: ReplayId,
    pub episode_id: EpisodeId,
    pub phase: ReplayPhase,
    pub visibility: OutcomeVisibility,
    pub content_role: ReplayContentRole,
    #[serde(with = "logical_time")]
    pub information_cutoff: LogicalSessionTick,
    pub witnessed_scene: Option<SceneRef>,
    pub blob_digest: Digest,
    #[serde(with = "logical_time")]
    pub recorded_at: LogicalSessionTick,
    pub qualification: Qualification,
}

/// Public semantic objects are explicitly unverified until a private store receipt exists.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Qualification {
    UnverifiedSemantic,
}

/// Explicit outcome visibility state; hidden replay has no implied reveal.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
#[serde(deny_unknown_fields)]
pub enum OutcomeVisibility {
    Hidden,
    Revealed {
        reveal_id: ReplayId,
        #[serde(with = "logical_time")]
        revealed_at: LogicalSessionTick,
    },
}

/// Role of replay bytes, preventing opaque retrospective content from masquerading as hidden data.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ReplayContentRole {
    WitnessedPrompt,
    OutcomeHiddenReconstruction,
    RetrospectiveInterpretation,
}

/// Session close semantics, independent of outcome maturity.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SessionClose {
    pub session_id: SessionId,
    #[serde(with = "logical_time")]
    pub closed_at: LogicalSessionTick,
    pub status: SessionCloseStatus,
    #[serde(with = "logical_time")]
    pub cutoff: LogicalSessionTick,
    #[serde(with = "logical_time")]
    pub recorded_at: LogicalSessionTick,
    #[serde(with = "logical_time")]
    pub committed_at: LogicalSessionTick,
    pub qualification: Qualification,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionCloseStatus {
    Complete,
    IncompleteEarly,
    IncompleteLate,
}

/// Knowledge-by-deadline closure.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct KnowledgeClosure {
    pub closure_id: KnowledgeClosureId,
    pub episode_id: EpisodeId,
    #[serde(with = "logical_time")]
    pub knowledge_deadline: LogicalSessionTick,
    #[serde(with = "logical_time")]
    pub evidence_cutoff: LogicalSessionTick,
    pub gap_ids: Vec<String>,
    pub state: KnowledgeState,
    #[serde(with = "logical_time")]
    pub recorded_at: LogicalSessionTick,
    #[serde(with = "logical_time")]
    pub committed_at: LogicalSessionTick,
    pub qualification: Qualification,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum KnowledgeState {
    Closed,
    Partial,
    Unknown,
}

/// Outcome-at-horizon closure, preserving censoring and conflict.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct OutcomeAtHorizon {
    pub outcome_id: OutcomeId,
    pub episode_id: EpisodeId,
    #[serde(with = "logical_time")]
    pub horizon: LogicalSessionTick,
    pub knowledge_closure_id: KnowledgeClosureId,
    pub state: OutcomeState,
    pub interpretation: Option<String>,
    #[serde(with = "logical_time")]
    pub outcome_known_at: LogicalSessionTick,
    #[serde(with = "logical_time")]
    pub recorded_at: LogicalSessionTick,
    #[serde(with = "logical_time")]
    pub committed_at: LogicalSessionTick,
    pub qualification: Qualification,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
#[serde(deny_unknown_fields)]
pub enum OutcomeState {
    Available { evidence_digest: Digest },
    Missing { reason: String },
    Conflicting { evidence_digests: BTreeSet<Digest> },
    Unsupported { reason: String },
    NotApplicableByAbstention,
}

/// Interview disposition is typed and append-only.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct InterviewDisposition {
    pub interview_id: InterviewId,
    pub episode_id: EpisodeId,
    pub disposition: InterviewDispositionKind,
    #[serde(with = "logical_time")]
    pub recorded_at: LogicalSessionTick,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InterviewDispositionKind {
    Useful,
    NotUseful,
    Burdensome,
    CannotRecall,
    Declined,
}

/// Append-only memory events.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    content = "value",
    rename_all = "snake_case",
    deny_unknown_fields
)]
#[allow(clippy::large_enum_variant)]
pub enum MemoryOccurrence {
    OperatorAct(OperatorAct),
    PresentationGapRepair(PresentationGapRepair),
    ActCorrection(ActCorrection),
    OntologyVersion(OntologyVersion),
    Episode(Episode),
    Replay(ReplayArtifact),
    SessionClose(SessionClose),
    KnowledgeClosure(KnowledgeClosure),
    OutcomeAtHorizon(OutcomeAtHorizon),
    InterviewDisposition(InterviewDisposition),
}

impl MemoryOccurrence {
    /// Returns the stable append identity.
    #[must_use]
    pub fn occurrence_id(&self) -> String {
        match self {
            Self::OperatorAct(value) => format!("act:{}", value.act_id),
            Self::PresentationGapRepair(value) => {
                format!("presentation-repair:{}", value.repair_id)
            }
            Self::ActCorrection(value) => format!("correction:{}", value.correction_id),
            Self::OntologyVersion(value) => format!("ontology:{}", value.version_id),
            Self::Episode(value) => format!("episode:{}", value.episode_id),
            Self::Replay(value) => format!("replay:{}", value.replay_id),
            Self::SessionClose(value) => format!("session-close:{}", value.session_id),
            Self::KnowledgeClosure(value) => format!("knowledge:{}", value.closure_id),
            Self::OutcomeAtHorizon(value) => format!("outcome:{}", value.outcome_id),
            Self::InterviewDisposition(value) => format!("interview:{}", value.interview_id),
        }
    }

    /// Returns the exact canonical occurrence digest.
    ///
    /// # Errors
    ///
    /// Returns an error if the occurrence cannot be serialized.
    pub fn exact_digest(&self) -> Result<Digest, serde_json::Error> {
        serde_json::to_vec(self).map(|bytes| Digest::of_bytes(&bytes))
    }
}

/// Parses one exact canonical memory occurrence.
///
/// # Errors
///
/// Returns an error for malformed JSON, unknown fields, or noncanonical bytes.
pub fn parse_memory_occurrence_exact(bytes: &[u8]) -> Result<MemoryOccurrence, String> {
    let occurrence: MemoryOccurrence =
        serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
    let canonical = serde_json::to_vec(&occurrence).map_err(|error| error.to_string())?;
    if canonical != bytes {
        return Err("memory occurrence bytes are not canonical".into());
    }
    Ok(occurrence)
}

/// Validates bounded text fields used by the kernel.
pub(crate) fn validate_text(value: &str, field: &str) -> Result<(), String> {
    if value.is_empty() || value.len() > MAX_TEXT || value.chars().any(char::is_control) {
        return Err(format!(
            "{field} is empty, oversized, or contains control text"
        ));
    }
    Ok(())
}
