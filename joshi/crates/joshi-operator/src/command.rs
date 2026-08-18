use crate::{
    OperatorAdmissionError, Result, ValidatedGlassViewV1,
    error::{invalid, json_error},
    glass::{parse_instant, parse_wire_u64},
};
use joshi_domain::{
    ClientSessionId, CommandId, CommitSeq, SceneId, StableString, UtcTimestamp, ValueDigest,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

const COMMAND_CONTRACT: &str = "joshi.operator.command";

/// Frozen evidence-only operator command variants.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperatorCommandKind {
    RecordFocus,
    NominateCandidate,
    RequestHotScope,
    RecordDisposition,
    RecordCrackleFamily,
    RecordGesture,
    RecordAnnotation,
    RecordChoiceSet,
    RecordPostActionReport,
    LinkInterview,
    CompensateCommand,
}

impl OperatorCommandKind {
    /// Frozen wire discriminator.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::RecordFocus => "record_focus",
            Self::NominateCandidate => "nominate_candidate",
            Self::RequestHotScope => "request_hot_scope",
            Self::RecordDisposition => "record_disposition",
            Self::RecordCrackleFamily => "record_crackle_family",
            Self::RecordGesture => "record_gesture",
            Self::RecordAnnotation => "record_annotation",
            Self::RecordChoiceSet => "record_choice_set",
            Self::RecordPostActionReport => "record_post_action_report",
            Self::LinkInterview => "link_interview",
            Self::CompensateCommand => "compensate_command",
        }
    }
}

/// Typed subject carried by an admitted command.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorSubject {
    kind: StableString,
    key: StableString,
}

impl OperatorSubject {
    /// Subject family.
    #[must_use]
    pub fn kind(&self) -> &StableString {
        &self.kind
    }

    /// Exact subject identity.
    #[must_use]
    pub fn key(&self) -> &StableString {
        &self.key
    }
}

/// Validated exact command bytes and server-derived digests.
#[derive(Clone, Debug)]
pub struct ValidatedOperatorCommandV1 {
    command_id: CommandId,
    idempotency_key: StableString,
    client_session_id: ClientSessionId,
    client_command_seq: u64,
    scene_id: SceneId,
    view_digest: ValueDigest,
    issued_at: UtcTimestamp,
    client_clock_id: StableString,
    client_monotonic_ns: u64,
    kind: OperatorCommandKind,
    subject: OperatorSubject,
    payload: OperatorPayload,
    payload_bytes: Vec<u8>,
    canonical_bytes: Vec<u8>,
    payload_digest: ValueDigest,
    command_digest: ValueDigest,
}

impl ValidatedOperatorCommandV1 {
    /// Parses strict V1 JSON and requires its one canonical byte representation.
    ///
    /// # Errors
    ///
    /// Rejects unknown keys, wrong literals, malformed clocks/digests/identities, invalid
    /// kind-specific payloads, noncanonical array order, and noncanonical bytes.
    pub fn parse_exact(bytes: &[u8]) -> Result<Self> {
        let head: CommandHeadWire =
            serde_json::from_slice(bytes).map_err(json_error("operator command V1"))?;
        validate_head(&head)?;
        let payload = parse_payload(&head.command_kind, head.payload.clone())?;
        validate_payload(&payload)?;
        let payload_bytes = payload.canonical_bytes()?;
        let canonical_bytes = payload.canonical_command_bytes(&head)?;
        if canonical_bytes != bytes {
            return Err(OperatorAdmissionError::NonCanonical {
                contract: COMMAND_CONTRACT,
            });
        }
        let payload_digest = digest(&payload_bytes)?;
        let command_digest = digest(&canonical_bytes)?;
        let command_id = CommandId::new(head.command_id)
            .map_err(|error| invalid("commandId", error.to_string()))?;
        let client_session_id = ClientSessionId::new(head.client_session_id)
            .map_err(|error| invalid("clientSessionId", error.to_string()))?;
        Ok(Self {
            command_id,
            idempotency_key: StableString::new(head.idempotency_key)
                .map_err(|error| invalid("idempotencyKey", error.to_string()))?,
            client_session_id,
            client_command_seq: parse_wire_u64(&head.client_command_seq, "clientCommandSeq")?,
            scene_id: SceneId::new(head.scene.scene_id)
                .map_err(|error| invalid("sceneId", error.to_string()))?,
            view_digest: ValueDigest::new(head.scene.view_digest)
                .map_err(|error| invalid("viewDigest", error.to_string()))?,
            issued_at: parse_instant(&head.issued_at, "issuedAt")?,
            client_clock_id: StableString::new(head.client_clock.clock_id)
                .map_err(|error| invalid("client clockId", error.to_string()))?,
            client_monotonic_ns: parse_wire_u64(
                &head.client_clock.monotonic_ns,
                "client monotonicNs",
            )?,
            kind: parse_kind(&head.command_kind)?,
            subject: OperatorSubject {
                kind: StableString::new(head.subject.kind)
                    .map_err(|error| invalid("subject kind", error.to_string()))?,
                key: StableString::new(head.subject.key)
                    .map_err(|error| invalid("subject key", error.to_string()))?,
            },
            payload,
            payload_bytes,
            canonical_bytes,
            payload_digest,
            command_digest,
        })
    }

    /// Verifies scene/view identity and every candidate reference against an admitted view.
    ///
    /// # Errors
    ///
    /// Rejects a mismatched scene/digest or a candidate reference absent from the exact view.
    pub fn validate_against_view(&self, view: &ValidatedGlassViewV1) -> Result<()> {
        if self.scene_id != *view.scene_id() || self.view_digest != *view.digest() {
            return Err(OperatorAdmissionError::SceneBinding);
        }
        if self.subject.kind.as_str() == "candidate"
            && !view.contains_candidate(self.subject.key.as_str())
        {
            return Err(invalid(
                "command subject",
                "candidate is absent from the exact scene",
            ));
        }
        for candidate in self.payload.candidate_references() {
            if !view.contains_candidate(candidate) {
                return Err(invalid(
                    "command payload candidate",
                    format!("{candidate} is absent from the exact scene"),
                ));
            }
        }
        Ok(())
    }

    /// Command identity.
    #[must_use]
    pub fn command_id(&self) -> &CommandId {
        &self.command_id
    }

    /// Stable retry identity supplied by the client.
    #[must_use]
    pub fn idempotency_key(&self) -> &StableString {
        &self.idempotency_key
    }

    /// Client session identity.
    #[must_use]
    pub fn client_session_id(&self) -> &ClientSessionId {
        &self.client_session_id
    }

    /// Monotone client command sequence.
    #[must_use]
    pub const fn client_command_seq(&self) -> u64 {
        self.client_command_seq
    }

    /// Bound scene identity.
    #[must_use]
    pub fn scene_id(&self) -> &SceneId {
        &self.scene_id
    }

    /// Bound exact view digest.
    #[must_use]
    pub fn view_digest(&self) -> &ValueDigest {
        &self.view_digest
    }

    /// Client issue wall clock.
    #[must_use]
    pub const fn issued_at(&self) -> UtcTimestamp {
        self.issued_at
    }

    /// Client monotonic clock domain.
    #[must_use]
    pub fn client_clock_id(&self) -> &StableString {
        &self.client_clock_id
    }

    /// Client monotonic reading.
    #[must_use]
    pub const fn client_monotonic_ns(&self) -> u64 {
        self.client_monotonic_ns
    }

    /// Frozen command variant.
    #[must_use]
    pub const fn kind(&self) -> OperatorCommandKind {
        self.kind
    }

    /// Typed subject.
    #[must_use]
    pub fn subject(&self) -> &OperatorSubject {
        &self.subject
    }

    /// Exact canonical kind-specific payload bytes.
    #[must_use]
    pub fn payload_bytes(&self) -> &[u8] {
        &self.payload_bytes
    }

    /// Exact canonical full command bytes.
    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.canonical_bytes
    }

    /// Server-derived payload digest.
    #[must_use]
    pub fn payload_digest(&self) -> &ValueDigest {
        &self.payload_digest
    }

    /// Server-derived full command digest.
    #[must_use]
    pub fn command_digest(&self) -> &ValueDigest {
        &self.command_digest
    }

    /// Existing commands whose presence the store must prove before append.
    #[must_use]
    pub fn referenced_command_ids(&self) -> Vec<&str> {
        self.payload.command_references()
    }

    /// Prior command compensated by this append-only correction, if any.
    #[must_use]
    pub fn compensates_command_id(&self) -> Option<&str> {
        match &self.payload {
            OperatorPayload::CompensateCommand(value) => Some(&value.compensates_command_id),
            _ => None,
        }
    }
}

/// Public command receipt status.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OperatorCommandStatus {
    /// A new append became durable.
    Accepted,
    /// Exact command identity/content was already durable.
    Idempotent,
}

/// Exact public V1 acknowledgement, distinct from structural store receipts.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CommandReceiptV1 {
    contract: &'static str,
    schema_version: u64,
    catalog_id: StableString,
    catalog_schema: StableString,
    batch_id: StableString,
    command_id: CommandId,
    command_payload_digest: ValueDigest,
    command_digest: ValueDigest,
    scene: ReceiptScene,
    commit_seq: CommitSeq,
    status: OperatorCommandStatus,
}

impl CommandReceiptV1 {
    /// Builds the public DTO only after a typed persistence boundary reports durable commit.
    #[must_use]
    #[allow(clippy::too_many_arguments)] // Receipt closure is intentionally explicit.
    pub fn durable(
        catalog_id: StableString,
        catalog_schema: StableString,
        batch_id: StableString,
        command: &ValidatedOperatorCommandV1,
        commit_seq: CommitSeq,
        status: OperatorCommandStatus,
    ) -> Self {
        Self {
            contract: "joshi.store.command_receipt",
            schema_version: 1,
            catalog_id,
            catalog_schema,
            batch_id,
            command_id: command.command_id.clone(),
            command_payload_digest: command.payload_digest.clone(),
            command_digest: command.command_digest.clone(),
            scene: ReceiptScene {
                scene_id: command.scene_id.clone(),
                view_digest: command.view_digest.clone(),
            },
            commit_seq,
            status,
        }
    }

    /// Durable commit sequence.
    #[must_use]
    pub const fn commit_seq(&self) -> CommitSeq {
        self.commit_seq
    }

    /// Whether the append was new or an exact retry.
    #[must_use]
    pub const fn status(&self) -> OperatorCommandStatus {
        self.status
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
struct ReceiptScene {
    scene_id: SceneId,
    view_digest: ValueDigest,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CommandHeadWire {
    contract: String,
    schema_version: u64,
    command_id: String,
    idempotency_key: String,
    client_session_id: String,
    client_command_seq: String,
    scene: SceneReferenceWire,
    issued_at: String,
    client_clock: ClientClockWire,
    command_kind: String,
    subject: SubjectWire,
    payload: serde_json::Value,
    authority_class: String,
    effect_ceiling: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SceneReferenceWire {
    scene_id: String,
    view_digest: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ClientClockWire {
    clock_id: String,
    monotonic_ns: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SubjectWire {
    kind: String,
    key: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CanonicalCommand<'a, P: Serialize> {
    contract: &'a str,
    schema_version: u64,
    command_id: &'a str,
    idempotency_key: &'a str,
    client_session_id: &'a str,
    client_command_seq: &'a str,
    scene: &'a SceneReferenceWire,
    issued_at: &'a str,
    client_clock: &'a ClientClockWire,
    command_kind: &'a str,
    subject: &'a SubjectWire,
    payload: &'a P,
    authority_class: &'a str,
    effect_ceiling: &'a str,
}

#[derive(Clone, Debug)]
enum OperatorPayload {
    RecordFocus(RecordFocusPayload),
    NominateCandidate(NominateCandidatePayload),
    RequestHotScope(RequestHotScopePayload),
    RecordDisposition(RecordDispositionPayload),
    RecordCrackleFamily(RecordCrackleFamilyPayload),
    RecordGesture(RecordGesturePayload),
    RecordAnnotation(RecordAnnotationPayload),
    RecordChoiceSet(RecordChoiceSetPayload),
    RecordPostActionReport(RecordPostActionReportPayload),
    LinkInterview(LinkInterviewPayload),
    CompensateCommand(CompensateCommandPayload),
}

impl OperatorPayload {
    fn canonical_bytes(&self) -> Result<Vec<u8>> {
        match self {
            Self::RecordFocus(value) => encode(value, "record_focus payload"),
            Self::NominateCandidate(value) => encode(value, "nominate_candidate payload"),
            Self::RequestHotScope(value) => encode(value, "request_hot_scope payload"),
            Self::RecordDisposition(value) => encode(value, "record_disposition payload"),
            Self::RecordCrackleFamily(value) => encode(value, "record_crackle_family payload"),
            Self::RecordGesture(value) => encode(value, "record_gesture payload"),
            Self::RecordAnnotation(value) => encode(value, "record_annotation payload"),
            Self::RecordChoiceSet(value) => encode(value, "record_choice_set payload"),
            Self::RecordPostActionReport(value) => {
                encode(value, "record_post_action_report payload")
            }
            Self::LinkInterview(value) => encode(value, "link_interview payload"),
            Self::CompensateCommand(value) => encode(value, "compensate_command payload"),
        }
    }

    fn canonical_command_bytes(&self, head: &CommandHeadWire) -> Result<Vec<u8>> {
        match self {
            Self::RecordFocus(value) => encode_command(head, value),
            Self::NominateCandidate(value) => encode_command(head, value),
            Self::RequestHotScope(value) => encode_command(head, value),
            Self::RecordDisposition(value) => encode_command(head, value),
            Self::RecordCrackleFamily(value) => encode_command(head, value),
            Self::RecordGesture(value) => encode_command(head, value),
            Self::RecordAnnotation(value) => encode_command(head, value),
            Self::RecordChoiceSet(value) => encode_command(head, value),
            Self::RecordPostActionReport(value) => encode_command(head, value),
            Self::LinkInterview(value) => encode_command(head, value),
            Self::CompensateCommand(value) => encode_command(head, value),
        }
    }

    fn candidate_references(&self) -> Vec<&str> {
        match self {
            Self::RecordAnnotation(value) => vec![&value.chart.candidate_id],
            Self::RecordChoiceSet(value) => value
                .choice_set
                .subjects
                .iter()
                .map(|subject| subject.key.as_str())
                .collect(),
            _ => Vec::new(),
        }
    }

    fn command_references(&self) -> Vec<&str> {
        match self {
            Self::RecordPostActionReport(value) => value
                .related_command_id
                .iter()
                .map(String::as_str)
                .collect(),
            Self::LinkInterview(value) => value
                .source_command_ids
                .iter()
                .map(String::as_str)
                .collect(),
            Self::CompensateCommand(value) => vec![&value.compensates_command_id],
            _ => Vec::new(),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CaptureContext {
    ui_label: String,
    ui_label_version: String,
    confidence_ppm: Option<String>,
    urgency: Option<String>,
    why_now: Option<String>,
    note: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EpisodeReference {
    episode_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ChoiceSubject {
    kind: String,
    key: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecordFocusPayload {
    context: CaptureContext,
    dwell_milliseconds: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct NominateCandidatePayload {
    context: CaptureContext,
    nomination: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RequestHotScopePayload {
    context: CaptureContext,
    scope: HotScope,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct HotScope {
    family: String,
    subject: SubjectWire,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecordDispositionPayload {
    context: CaptureContext,
    disposition: String,
    provisional: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecordCrackleFamilyPayload {
    context: CaptureContext,
    crackle_family: String,
    provisional: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecordGesturePayload {
    context: CaptureContext,
    gesture_label: String,
    episode_ref: Option<EpisodeReference>,
    observed_externally: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "anchorKind", rename_all = "snake_case", deny_unknown_fields)]
enum ChartAnchor {
    Time {
        at: String,
    },
    Point {
        #[serde(rename = "sampleId")]
        sample_id: String,
        at: String,
    },
    Range {
        #[serde(rename = "startSampleId")]
        start_sample_id: String,
        #[serde(rename = "endSampleId")]
        end_sample_id: String,
        #[serde(rename = "startAt")]
        start_at: String,
        #[serde(rename = "endAt")]
        end_at: String,
    },
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecordAnnotationPayload {
    context: CaptureContext,
    annotation_id: String,
    chart: AnnotationChart,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AnnotationChart {
    candidate_id: String,
    series_id: String,
    anchor: ChartAnchor,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecordChoiceSetPayload {
    context: CaptureContext,
    choice_set: ChoiceSet,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ChoiceSet {
    set_kind: String,
    subjects: Vec<ChoiceSubject>,
    selected_subject: Option<ChoiceSubject>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecordPostActionReportPayload {
    context: CaptureContext,
    report_id: String,
    episode_ref: Option<EpisodeReference>,
    related_command_id: Option<String>,
    action_observed_at: Option<String>,
    outcome_hidden: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct LinkInterviewPayload {
    context: CaptureContext,
    interview_id: String,
    timing: String,
    outcome_visibility: String,
    episode_ref: Option<EpisodeReference>,
    source_command_ids: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CompensateCommandPayload {
    context: CaptureContext,
    compensates_command_id: String,
    reason: String,
}

fn parse_payload(kind: &str, payload: serde_json::Value) -> Result<OperatorPayload> {
    macro_rules! decode {
        ($variant:ident, $type:ty) => {
            serde_json::from_value::<$type>(payload)
                .map(OperatorPayload::$variant)
                .map_err(json_error("operator command payload"))
        };
    }
    match kind {
        "record_focus" => decode!(RecordFocus, RecordFocusPayload),
        "nominate_candidate" => decode!(NominateCandidate, NominateCandidatePayload),
        "request_hot_scope" => decode!(RequestHotScope, RequestHotScopePayload),
        "record_disposition" => decode!(RecordDisposition, RecordDispositionPayload),
        "record_crackle_family" => decode!(RecordCrackleFamily, RecordCrackleFamilyPayload),
        "record_gesture" => decode!(RecordGesture, RecordGesturePayload),
        "record_annotation" => decode!(RecordAnnotation, RecordAnnotationPayload),
        "record_choice_set" => decode!(RecordChoiceSet, RecordChoiceSetPayload),
        "record_post_action_report" => {
            decode!(RecordPostActionReport, RecordPostActionReportPayload)
        }
        "link_interview" => decode!(LinkInterview, LinkInterviewPayload),
        "compensate_command" => decode!(CompensateCommand, CompensateCommandPayload),
        _ => Err(invalid(
            "commandKind",
            format!("unsupported variant {kind}"),
        )),
    }
}

fn parse_kind(value: &str) -> Result<OperatorCommandKind> {
    match value {
        "record_focus" => Ok(OperatorCommandKind::RecordFocus),
        "nominate_candidate" => Ok(OperatorCommandKind::NominateCandidate),
        "request_hot_scope" => Ok(OperatorCommandKind::RequestHotScope),
        "record_disposition" => Ok(OperatorCommandKind::RecordDisposition),
        "record_crackle_family" => Ok(OperatorCommandKind::RecordCrackleFamily),
        "record_gesture" => Ok(OperatorCommandKind::RecordGesture),
        "record_annotation" => Ok(OperatorCommandKind::RecordAnnotation),
        "record_choice_set" => Ok(OperatorCommandKind::RecordChoiceSet),
        "record_post_action_report" => Ok(OperatorCommandKind::RecordPostActionReport),
        "link_interview" => Ok(OperatorCommandKind::LinkInterview),
        "compensate_command" => Ok(OperatorCommandKind::CompensateCommand),
        _ => Err(invalid(
            "commandKind",
            format!("unsupported variant {value}"),
        )),
    }
}

fn validate_head(value: &CommandHeadWire) -> Result<()> {
    if value.contract != COMMAND_CONTRACT || value.schema_version != 1 {
        return Err(invalid(
            "operator command contract",
            "expected joshi.operator.command schemaVersion 1",
        ));
    }
    for (field, identity) in [
        ("commandId", value.command_id.as_str()),
        ("idempotencyKey", value.idempotency_key.as_str()),
        ("clientSessionId", value.client_session_id.as_str()),
        ("sceneId", value.scene.scene_id.as_str()),
        ("client clockId", value.client_clock.clock_id.as_str()),
        ("subject kind", value.subject.kind.as_str()),
        ("subject key", value.subject.key.as_str()),
    ] {
        operator_identity(identity, field)?;
    }
    parse_wire_u64(&value.client_command_seq, "clientCommandSeq")?;
    require_digest(&value.scene.view_digest, "scene viewDigest")?;
    parse_instant(&value.issued_at, "issuedAt")?;
    parse_wire_u64(&value.client_clock.monotonic_ns, "client monotonicNs")?;
    parse_kind(&value.command_kind)?;
    if value.authority_class != "evidence_only" || value.effect_ceiling != "observe_only" {
        return Err(invalid(
            "command authority",
            "must be evidence_only / observe_only",
        ));
    }
    Ok(())
}

fn validate_payload(value: &OperatorPayload) -> Result<()> {
    let context = match value {
        OperatorPayload::RecordFocus(payload) => {
            if let Some(milliseconds) = &payload.dwell_milliseconds {
                parse_wire_u64(milliseconds, "dwellMilliseconds")?;
            }
            &payload.context
        }
        OperatorPayload::NominateCandidate(payload) => {
            exact_string(&payload.nomination, 240, "nomination")?;
            &payload.context
        }
        OperatorPayload::RequestHotScope(payload) => {
            operator_identity(&payload.scope.family, "scope family")?;
            validate_subject(&payload.scope.subject)?;
            &payload.context
        }
        OperatorPayload::RecordDisposition(payload) => {
            exact_string(&payload.disposition, 240, "disposition")?;
            if !payload.provisional {
                return Err(invalid("disposition provisional", "must be literal true"));
            }
            &payload.context
        }
        OperatorPayload::RecordCrackleFamily(payload) => {
            exact_string(&payload.crackle_family, 240, "crackleFamily")?;
            if !payload.provisional {
                return Err(invalid("crackle provisional", "must be literal true"));
            }
            &payload.context
        }
        OperatorPayload::RecordGesture(payload) => {
            exact_string(&payload.gesture_label, 240, "gestureLabel")?;
            optional_episode(payload.episode_ref.as_ref())?;
            &payload.context
        }
        OperatorPayload::RecordAnnotation(payload) => {
            operator_identity(&payload.annotation_id, "annotationId")?;
            operator_identity(&payload.chart.candidate_id, "annotation candidateId")?;
            operator_identity(&payload.chart.series_id, "annotation seriesId")?;
            validate_anchor(&payload.chart.anchor)?;
            &payload.context
        }
        OperatorPayload::RecordChoiceSet(payload) => {
            validate_choice_set(&payload.choice_set)?;
            &payload.context
        }
        OperatorPayload::RecordPostActionReport(payload) => {
            operator_identity(&payload.report_id, "reportId")?;
            optional_episode(payload.episode_ref.as_ref())?;
            if let Some(command) = &payload.related_command_id {
                operator_identity(command, "relatedCommandId")?;
            }
            if let Some(at) = &payload.action_observed_at {
                parse_instant(at, "actionObservedAt")?;
            }
            &payload.context
        }
        OperatorPayload::LinkInterview(payload) => {
            operator_identity(&payload.interview_id, "interviewId")?;
            one_of(&payload.timing, &["quick", "later"], "interview timing")?;
            one_of(
                &payload.outcome_visibility,
                &["hidden", "aware"],
                "outcomeVisibility",
            )?;
            optional_episode(payload.episode_ref.as_ref())?;
            if payload.source_command_ids.len() > 100 {
                return Err(invalid("sourceCommandIds", "maximum length is 100"));
            }
            let mut ids = BTreeSet::new();
            for command in &payload.source_command_ids {
                operator_identity(command, "sourceCommandId")?;
                if !ids.insert(command) {
                    return Err(invalid("sourceCommandIds", "must be unique"));
                }
            }
            &payload.context
        }
        OperatorPayload::CompensateCommand(payload) => {
            operator_identity(&payload.compensates_command_id, "compensatesCommandId")?;
            exact_string(&payload.reason, 800, "compensation reason")?;
            &payload.context
        }
    };
    validate_context(context)
}

fn validate_context(value: &CaptureContext) -> Result<()> {
    exact_string(&value.ui_label, 120, "context uiLabel")?;
    parse_wire_u64(&value.ui_label_version, "context uiLabelVersion")?;
    if let Some(confidence) = &value.confidence_ppm
        && parse_wire_u64(confidence, "context confidencePpm")? > 1_000_000
    {
        return Err(invalid("context confidencePpm", "must be at most 1000000"));
    }
    if let Some(urgency) = &value.urgency {
        one_of(
            urgency,
            &["low", "normal", "high", "immediate"],
            "context urgency",
        )?;
    }
    if let Some(why) = &value.why_now {
        exact_string(why, 800, "context whyNow")?;
    }
    if let Some(note) = &value.note {
        exact_string(note, 4_000, "context note")?;
    }
    Ok(())
}

fn validate_anchor(value: &ChartAnchor) -> Result<()> {
    match value {
        ChartAnchor::Time { at } => {
            parse_instant(at, "annotation time anchor")?;
        }
        ChartAnchor::Point { sample_id, at } => {
            operator_identity(sample_id, "annotation sampleId")?;
            parse_instant(at, "annotation point time")?;
        }
        ChartAnchor::Range {
            start_sample_id,
            end_sample_id,
            start_at,
            end_at,
        } => {
            operator_identity(start_sample_id, "annotation startSampleId")?;
            operator_identity(end_sample_id, "annotation endSampleId")?;
            let start = parse_instant(start_at, "annotation startAt")?;
            let end = parse_instant(end_at, "annotation endAt")?;
            if start.as_datetime() > end.as_datetime() {
                return Err(invalid("annotation range", "startAt exceeds endAt"));
            }
        }
    }
    Ok(())
}

fn validate_choice_set(value: &ChoiceSet) -> Result<()> {
    one_of(
        &value.set_kind,
        &["surfaced", "filtered", "viewport", "interacted", "compared"],
        "choice setKind",
    )?;
    if value.subjects.is_empty() || value.subjects.len() > 1_000 {
        return Err(invalid("choice subjects", "length must be 1..=1000"));
    }
    let mut prior: Option<&str> = None;
    for subject in &value.subjects {
        validate_choice_subject(subject)?;
        if prior.is_some_and(|before| before >= subject.key.as_str()) {
            return Err(invalid(
                "choice subjects",
                "must be unique and canonically sorted",
            ));
        }
        prior = Some(&subject.key);
    }
    if let Some(selected) = &value.selected_subject {
        validate_choice_subject(selected)?;
        if !value.subjects.iter().any(|value| value == selected) {
            return Err(invalid(
                "selectedSubject",
                "must be a member of the choice set",
            ));
        }
    }
    Ok(())
}

fn validate_choice_subject(value: &ChoiceSubject) -> Result<()> {
    if value.kind != "candidate" {
        return Err(invalid("choice subject kind", "must be candidate"));
    }
    operator_identity(&value.key, "choice subject key")
}

fn validate_subject(value: &SubjectWire) -> Result<()> {
    operator_identity(&value.kind, "subject kind")?;
    operator_identity(&value.key, "subject key")
}

fn optional_episode(value: Option<&EpisodeReference>) -> Result<()> {
    if let Some(value) = value {
        operator_identity(&value.episode_id, "episodeId")?;
    }
    Ok(())
}

fn operator_identity(value: &str, context: &'static str) -> Result<()> {
    if value.len() > 512
        || !value.bytes().enumerate().all(|(index, byte)| {
            byte.is_ascii_alphanumeric()
                || (index > 0 && matches!(byte, b'.' | b'_' | b':' | b'/' | b'-'))
        })
    {
        Err(invalid(context, "must be a canonical ASCII identity"))
    } else {
        Ok(())
    }
}

fn exact_string(value: &str, maximum: usize, context: &'static str) -> Result<()> {
    let units = value.encode_utf16().count();
    if value.is_empty() || units > maximum || value.trim() != value {
        Err(invalid(
            context,
            format!("must be trimmed and contain 1..={maximum} UTF-16 units"),
        ))
    } else {
        Ok(())
    }
}

fn require_digest(value: &str, context: &'static str) -> Result<()> {
    if value.len() == 71
        && value.starts_with("sha256:")
        && value[7..]
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        Ok(())
    } else {
        Err(invalid(context, "must be sha256:<64 lowercase hex>"))
    }
}

fn one_of(value: &str, allowed: &[&str], context: &'static str) -> Result<()> {
    if allowed.contains(&value) {
        Ok(())
    } else {
        Err(invalid(context, format!("unsupported value {value}")))
    }
}

fn encode<T: Serialize>(value: &T, context: &'static str) -> Result<Vec<u8>> {
    serde_json::to_vec(value).map_err(json_error(context))
}

fn encode_command<P: Serialize>(head: &CommandHeadWire, payload: &P) -> Result<Vec<u8>> {
    encode(
        &CanonicalCommand {
            contract: &head.contract,
            schema_version: head.schema_version,
            command_id: &head.command_id,
            idempotency_key: &head.idempotency_key,
            client_session_id: &head.client_session_id,
            client_command_seq: &head.client_command_seq,
            scene: &head.scene,
            issued_at: &head.issued_at,
            client_clock: &head.client_clock,
            command_kind: &head.command_kind,
            subject: &head.subject,
            payload,
            authority_class: &head.authority_class,
            effect_ceiling: &head.effect_ceiling,
        },
        "operator command V1",
    )
}

fn digest(bytes: &[u8]) -> Result<ValueDigest> {
    ValueDigest::new(format!("sha256:{:x}", Sha256::digest(bytes)))
        .map_err(|error| invalid("operator digest", error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::ValidatedOperatorCommandV1;
    use crate::ValidatedGlassViewV1;

    const GOLDEN: &str = include_str!("../../../apps/glass/src/operator/golden.ts");
    const VIEW_GOLDEN: &str = include_str!("../../../apps/glass/src/contract/golden.ts");

    fn extract<'a>(input: &'a str, prefix: &str, suffix: &str) -> &'a str {
        input
            .split_once(prefix)
            .and_then(|(_, after)| after.split_once(suffix))
            .map_or_else(|| panic!("missing golden {prefix}"), |(value, _)| value)
    }

    #[test]
    fn exact_typescript_goldens_match_rust() {
        let command = extract(
            GOLDEN,
            "export const GOLDEN_OPERATOR_COMMAND_V1_JSON = `",
            "`;\n\nexport const GOLDEN_OPERATOR_PAYLOAD_V1_DIGEST",
        );
        let payload_digest = extract(
            GOLDEN,
            "export const GOLDEN_OPERATOR_PAYLOAD_V1_DIGEST = \"",
            "\";",
        );
        let command_digest = extract(
            GOLDEN,
            "export const GOLDEN_OPERATOR_COMMAND_V1_DIGEST = \"",
            "\";",
        );
        let admitted = ValidatedOperatorCommandV1::parse_exact(command.as_bytes())
            .unwrap_or_else(|error| panic!("golden command: {error}"));
        assert_eq!(admitted.payload_digest().as_str(), payload_digest);
        assert_eq!(admitted.command_digest().as_str(), command_digest);

        let view = extract(
            VIEW_GOLDEN,
            "export const GOLDEN_VIEW_V1_JSON = `",
            "`;\n\nexport const GOLDEN_VIEW_V1_DIGEST",
        );
        let view_digest = extract(
            VIEW_GOLDEN,
            "export const GOLDEN_VIEW_V1_DIGEST = \"",
            "\";",
        );
        let view = ValidatedGlassViewV1::parse_exact(view.as_bytes(), Some(view_digest))
            .unwrap_or_else(|error| panic!("golden view: {error}"));
        // The frozen operator digest golden deliberately uses an all-`a` scene digest and is not
        // the paired Glass golden. Admission must reject that mismatch, then accept exact bytes
        // whose scene reference was replaced before canonical command parsing.
        assert!(admitted.validate_against_view(&view).is_err());
        let bound_command = command
            .replace(
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                view_digest,
            )
            .replace("\"key\":\"radon\"", "\"key\":\"coin-a\"");
        let bound = ValidatedOperatorCommandV1::parse_exact(bound_command.as_bytes())
            .unwrap_or_else(|error| panic!("bound command: {error}"));
        bound
            .validate_against_view(&view)
            .unwrap_or_else(|error| panic!("golden binding: {error}"));
    }

    #[test]
    fn all_eleven_kind_specific_payloads_have_one_canonical_shape() {
        let command = extract(
            GOLDEN,
            "export const GOLDEN_OPERATOR_COMMAND_V1_JSON = `",
            "`;\n\nexport const GOLDEN_OPERATOR_PAYLOAD_V1_DIGEST",
        );
        let original_payload = extract(
            GOLDEN,
            "export const GOLDEN_OPERATOR_PAYLOAD_V1_JSON = `",
            "`;\n\nexport const GOLDEN_OPERATOR_COMMAND_V1_JSON",
        );
        let context = r#"{"uiLabel":"Capture","uiLabelVersion":"1","confidencePpm":null,"urgency":null,"whyNow":null,"note":null}"#;
        let cases = [
            (
                "record_focus",
                format!(r#"{{"context":{context},"dwellMilliseconds":"1"}}"#),
            ),
            (
                "nominate_candidate",
                format!(r#"{{"context":{context},"nomination":"watch"}}"#),
            ),
            (
                "request_hot_scope",
                format!(
                    r#"{{"context":{context},"scope":{{"family":"pump","subject":{{"kind":"candidate","key":"radon"}}}}}}"#
                ),
            ),
            (
                "record_disposition",
                format!(r#"{{"context":{context},"disposition":"watch","provisional":true}}"#),
            ),
            (
                "record_crackle_family",
                format!(r#"{{"context":{context},"crackleFamily":"microdip","provisional":true}}"#),
            ),
            (
                "record_gesture",
                format!(
                    r#"{{"context":{context},"gestureLabel":"exit","episodeRef":null,"observedExternally":true}}"#
                ),
            ),
            (
                "record_annotation",
                format!(
                    r#"{{"context":{context},"annotationId":"annotation-1","chart":{{"candidateId":"radon","seriesId":"price","anchor":{{"anchorKind":"time","at":"2026-08-16T18:42:18.000000Z"}}}}}}"#
                ),
            ),
            (
                "record_choice_set",
                format!(
                    r#"{{"context":{context},"choiceSet":{{"setKind":"viewport","subjects":[{{"kind":"candidate","key":"radon"}}],"selectedSubject":{{"kind":"candidate","key":"radon"}}}}}}"#
                ),
            ),
            (
                "record_post_action_report",
                format!(
                    r#"{{"context":{context},"reportId":"report-1","episodeRef":null,"relatedCommandId":null,"actionObservedAt":null,"outcomeHidden":true}}"#
                ),
            ),
            (
                "link_interview",
                format!(
                    r#"{{"context":{context},"interviewId":"interview-1","timing":"quick","outcomeVisibility":"hidden","episodeRef":null,"sourceCommandIds":[]}}"#
                ),
            ),
            (
                "compensate_command",
                format!(
                    r#"{{"context":{context},"compensatesCommandId":"command-prior","reason":"operator correction"}}"#
                ),
            ),
        ];
        for (kind, payload) in cases {
            let encoded = command
                .replace(
                    "\"commandKind\":\"record_disposition\"",
                    &format!("\"commandKind\":\"{kind}\""),
                )
                .replace(original_payload, &payload);
            let admitted = ValidatedOperatorCommandV1::parse_exact(encoded.as_bytes())
                .unwrap_or_else(|error| panic!("{kind}: {error}"));
            assert_eq!(admitted.kind().as_str(), kind);
        }
    }

    #[test]
    fn rejects_reordered_and_unknown_fields() {
        let command = extract(
            GOLDEN,
            "export const GOLDEN_OPERATOR_COMMAND_V1_JSON = `",
            "`;\n\nexport const GOLDEN_OPERATOR_PAYLOAD_V1_DIGEST",
        );
        let reordered = command.replacen(
            "{\"contract\":\"joshi.operator.command\",\"schemaVersion\":1",
            "{\"schemaVersion\":1,\"contract\":\"joshi.operator.command\"",
            1,
        );
        assert!(ValidatedOperatorCommandV1::parse_exact(reordered.as_bytes()).is_err());
        let unknown = command.replacen(
            "\"effectCeiling\":\"observe_only\"}",
            "\"effectCeiling\":\"observe_only\",\"economicAuthority\":true}",
            1,
        );
        assert!(ValidatedOperatorCommandV1::parse_exact(unknown.as_bytes()).is_err());
    }
}
