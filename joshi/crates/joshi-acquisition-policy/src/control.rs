use std::collections::BTreeMap;

use joshi_domain::{StableString, UtcTimestamp, ValueDigest, WireU64};
use joshi_evidence::{Boundary, CoverageScope};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{
    APPLIED_CONTRACT, CONTROL_COMMAND_CONTRACT, CONTROL_RECEIPT_CONTRACT, CollectorGeneration,
    EffectiveScope, HotScopeAppliedV1, HotScopeRecordV1, PolicyError, PolicyJournal,
    PolicyRecordHead, ScopePresence,
    policy::{all_latest_targets, latest_semantic_record, semantic_target, target_needs_control},
};

const SUPERVISOR_CONTRACT: &str = "joshi.supervisor.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum SupervisorAttemptKind {
    HttpRequest,
    WebSocketConnection,
    Poll,
    ControlWrite,
}

/// Non-secret supervisor protection profile retained across the adapter.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "class", rename_all = "snake_case", deny_unknown_fields)]
pub enum SupervisorProtectionProfileV1 {
    PublicIntegrity {
        domain: StableString,
    },
    AuthenticatedPrivate {
        domain: StableString,
        key_id: StableString,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SupervisorAttemptReservationWire {
    contract: String,
    reservation_id: String,
    installation_id: String,
    source_key: String,
    operation_key: String,
    generation: u64,
    attempt_ordinal: u64,
    kind: SupervisorAttemptKind,
    scope: CoverageScope,
    lower: Boundary,
    protection: SupervisorProtectionProfileV1,
    reserved_at: UtcTimestamp,
    authority: String,
}

/// Expected durable control-write coordinates supplied from reconstructed supervisor state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlReservationExpectation {
    pub source_key: StableString,
    pub operation_key: StableString,
    pub generation: WireU64,
    pub attempt_ordinal: WireU64,
    pub target_record_id: StableString,
}

/// Strict, lossless adapter result for one canonical fsync-complete supervisor reservation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CollectorControlReservationV1 {
    supervisor_contract: StableString,
    supervisor_reservation_digest: ValueDigest,
    reservation_id: StableString,
    installation_id: StableString,
    source_key: StableString,
    operation_key: StableString,
    generation: WireU64,
    attempt_ordinal: WireU64,
    scope: CoverageScope,
    lower: Boundary,
    protection: SupervisorProtectionProfileV1,
    reserved_at: UtcTimestamp,
    authority: StableString,
    target_record_id: StableString,
}

/// Validate exact canonical bytes emitted by `joshi_supervisor::AttemptReservation` and bind them
/// to the policy target whose ID was placed in the supervisor coverage scope.
///
/// # Errors
///
/// Refuses noncanonical bytes, wrong contract/kind/authority, wrong generation or attempt ordinal,
/// changed source/operation, or a scope that does not name the exact target record.
pub fn adapt_supervisor_control_reservation(
    exact_bytes: &[u8],
    expected: &ControlReservationExpectation,
) -> Result<CollectorControlReservationV1, PolicyError> {
    let wire: SupervisorAttemptReservationWire = serde_json::from_slice(exact_bytes)?;
    if serde_json::to_vec(&wire)? != exact_bytes {
        return Err(PolicyError::ControlReceipt(
            "supervisor reservation bytes are not canonical".into(),
        ));
    }
    if wire.contract != SUPERVISOR_CONTRACT
        || wire.kind != SupervisorAttemptKind::ControlWrite
        || wire.authority != "read_only_no_execution"
        || wire.source_key != expected.source_key.as_str()
        || wire.operation_key != expected.operation_key.as_str()
        || wire.generation != expected.generation.get()
        || wire.attempt_ordinal != expected.attempt_ordinal.get()
        || wire.generation == 0
        || wire.attempt_ordinal == 0
        || wire.scope.subject.as_ref() != Some(&expected.target_record_id)
    {
        return Err(PolicyError::ControlReceipt(
            "supervisor reservation does not match the exact control-write expectation".into(),
        ));
    }
    validate_supervisor_key(&wire.source_key, "source key")?;
    validate_supervisor_key(&wire.operation_key, "operation key")?;
    Ok(CollectorControlReservationV1 {
        supervisor_contract: stable(wire.contract)?,
        supervisor_reservation_digest: digest(exact_bytes)?,
        reservation_id: stable(wire.reservation_id)?,
        installation_id: stable(wire.installation_id)?,
        source_key: stable(wire.source_key)?,
        operation_key: stable(wire.operation_key)?,
        generation: WireU64::new(wire.generation),
        attempt_ordinal: WireU64::new(wire.attempt_ordinal),
        scope: wire.scope,
        lower: wire.lower,
        protection: wire.protection,
        reserved_at: wire.reserved_at,
        authority: stable(wire.authority)?,
        target_record_id: expected.target_record_id.clone(),
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CollectorControlAction {
    Apply,
    Remove,
}

/// Inert exact command bytes for a collector-owned source adapter.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CollectorControlCommandV1 {
    pub contract: StableString,
    pub schema_version: WireU64,
    pub command_id: StableString,
    pub control_write_reservation_id: StableString,
    pub supervisor_contract: StableString,
    pub control_write_kind: StableString,
    pub installation_id: StableString,
    pub source_key: StableString,
    pub operation_key: StableString,
    pub attempt_ordinal: WireU64,
    pub generation: WireU64,
    pub target_record_id: StableString,
    pub intent_id: StableString,
    pub action: CollectorControlAction,
    pub scope: Option<EffectiveScope>,
    pub adapter_version: StableString,
    pub authority: StableString,
    pub supervisor_reservation_digest: ValueDigest,
    pub reservation_scope: CoverageScope,
    pub reservation_lower: Boundary,
    pub reservation_protection: SupervisorProtectionProfileV1,
    pub reservation_reserved_at: UtcTimestamp,
}

impl CollectorControlCommandV1 {
    /// Exact deterministic JSON bytes handed to a source adapter after durable reservation.
    ///
    /// # Errors
    ///
    /// Returns an encoding error only when serialization fails.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, PolicyError> {
        serde_json::to_vec(self).map_err(Into::into)
    }

    /// SHA-256 closure of [`Self::canonical_bytes`].
    ///
    /// # Errors
    ///
    /// Returns an error when JSON encoding or digest identity validation fails.
    pub fn bytes_digest(&self) -> Result<ValueDigest, PolicyError> {
        let bytes = self.canonical_bytes()?;
        digest(&bytes)
    }
}

/// Exact local source-control write receipt; provider acceptance and coverage are out of scope.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CollectorControlReceiptV1 {
    pub contract: StableString,
    pub schema_version: WireU64,
    pub receipt_id: StableString,
    pub command_id: StableString,
    pub control_write_reservation_id: StableString,
    pub supervisor_reservation_digest: ValueDigest,
    pub source_key: StableString,
    pub operation_key: StableString,
    pub generation: WireU64,
    pub attempt_ordinal: WireU64,
    pub target_record_id: StableString,
    pub control_bytes_digest: ValueDigest,
    pub adapter_version: StableString,
    pub handed_to_source_adapter_at: UtcTimestamp,
    pub provider_acceptance: StableString,
    pub coverage_status: StableString,
}

/// Reconstruct exact source-control commands that are not applied in the current generation.
///
/// # Errors
///
/// Rejects a missing/changed reservation, generation mismatch, duplicate reservation target, or
/// malformed authority. A caller must durably reserve every returned attempt before invoking this
/// function; the reservation is part of the command bytes.
pub fn pending_control_commands(
    journal: &PolicyJournal,
    generations: &[CollectorGeneration],
    reservations: &[CollectorControlReservationV1],
    adapter_version: &StableString,
) -> Result<Vec<CollectorControlCommandV1>, PolicyError> {
    let generation_by_source: BTreeMap<_, _> = generations
        .iter()
        .map(|generation| (generation.source_key.clone(), generation.generation))
        .collect();
    if generation_by_source.len() != generations.len() {
        return Err(PolicyError::InvalidValue(
            "collector generations contain duplicate source keys".into(),
        ));
    }
    let mut reservation_by_target = BTreeMap::new();
    for reservation in reservations {
        if reservation_by_target
            .insert(reservation.target_record_id.clone(), reservation)
            .is_some()
        {
            return Err(PolicyError::ControlReceipt(
                "more than one reservation names the same target record".into(),
            ));
        }
    }
    let mut commands = Vec::new();
    for target in all_latest_targets(journal.records()) {
        let Some((intent, source, operation, presence, scope)) = semantic_target(target) else {
            continue;
        };
        let Some(generation) = generation_by_source.get(source).copied() else {
            continue;
        };
        if !target_needs_control(journal.records(), target, generation)? {
            continue;
        }
        let reservation = reservation_by_target
            .get(&target.head().record_id)
            .ok_or_else(|| {
                PolicyError::ControlReceipt(format!(
                    "missing durable reservation for target {}",
                    target.head().record_id
                ))
            })?;
        if &reservation.source_key != source
            || &reservation.operation_key != operation
            || reservation.generation != generation
        {
            return Err(PolicyError::ControlReceipt(
                "reservation source/operation/generation does not match target".into(),
            ));
        }
        let command_id = stable(format!("{}:control", reservation.reservation_id.as_str()))?;
        commands.push(CollectorControlCommandV1 {
            contract: stable(CONTROL_COMMAND_CONTRACT)?,
            schema_version: WireU64::new(1),
            command_id,
            control_write_reservation_id: reservation.reservation_id.clone(),
            supervisor_contract: reservation.supervisor_contract.clone(),
            control_write_kind: stable("control_write")?,
            installation_id: reservation.installation_id.clone(),
            source_key: source.clone(),
            operation_key: operation.clone(),
            attempt_ordinal: reservation.attempt_ordinal,
            generation,
            target_record_id: target.head().record_id.clone(),
            intent_id: intent.clone(),
            action: if presence == ScopePresence::Active {
                CollectorControlAction::Apply
            } else {
                CollectorControlAction::Remove
            },
            scope: scope.cloned(),
            adapter_version: adapter_version.clone(),
            authority: stable("read_only_no_execution")?,
            supervisor_reservation_digest: reservation.supervisor_reservation_digest.clone(),
            reservation_scope: reservation.scope.clone(),
            reservation_lower: reservation.lower.clone(),
            reservation_protection: reservation.protection.clone(),
            reservation_reserved_at: reservation.reserved_at,
        });
    }
    commands.sort_by(|left, right| {
        (&left.source_key, &left.operation_key, &left.intent_id).cmp(&(
            &right.source_key,
            &right.operation_key,
            &right.intent_id,
        ))
    });
    Ok(commands)
}

/// Convert an exact collector write receipt into an append-only applied occurrence.
///
/// # Errors
///
/// Refuses any command/receipt/digest/generation mismatch, nonliteral non-claims, a stale target,
/// or an append head that does not directly follow the supplied journal.
pub fn receipt_to_applied(
    journal: &PolicyJournal,
    command: &CollectorControlCommandV1,
    receipt: &CollectorControlReceiptV1,
    applied_record_id: StableString,
    recorded_at: UtcTimestamp,
) -> Result<HotScopeRecordV1, PolicyError> {
    if command.contract.as_str() != CONTROL_COMMAND_CONTRACT
        || receipt.contract.as_str() != CONTROL_RECEIPT_CONTRACT
        || command.schema_version.get() != 1
        || receipt.schema_version.get() != 1
        || command.authority.as_str() != "read_only_no_execution"
        || command.supervisor_contract.as_str() != SUPERVISOR_CONTRACT
        || command.control_write_kind.as_str() != "control_write"
    {
        return Err(PolicyError::InvalidContract(
            "collector control contract, schema, or authority mismatch".into(),
        ));
    }
    let expected_digest = command.bytes_digest()?;
    if receipt.command_id != command.command_id
        || receipt.control_write_reservation_id != command.control_write_reservation_id
        || receipt.supervisor_reservation_digest != command.supervisor_reservation_digest
        || receipt.source_key != command.source_key
        || receipt.operation_key != command.operation_key
        || receipt.generation != command.generation
        || receipt.attempt_ordinal != command.attempt_ordinal
        || receipt.target_record_id != command.target_record_id
        || receipt.adapter_version != command.adapter_version
        || receipt.control_bytes_digest != expected_digest
        || receipt.provider_acceptance.as_str() != "not_asserted"
        || receipt.coverage_status.as_str() != "not_asserted"
        || receipt.handed_to_source_adapter_at < command.reservation_reserved_at
    {
        return Err(PolicyError::ControlReceipt(
            "receipt does not exactly close over local control bytes and non-claims".into(),
        ));
    }
    let target = journal
        .records()
        .iter()
        .find(|record| record.head().record_id == command.target_record_id)
        .ok_or_else(|| PolicyError::ControlReceipt("target record is absent".into()))?;
    let Some((intent, source, operation, presence, _)) = semantic_target(target) else {
        return Err(PolicyError::ControlReceipt(
            "target is not a semantic control state".into(),
        ));
    };
    if intent != &command.intent_id
        || source != &command.source_key
        || operation != &command.operation_key
        || (presence == ScopePresence::Active) != (command.action == CollectorControlAction::Apply)
    {
        return Err(PolicyError::ControlReceipt(
            "command changes target scope meaning".into(),
        ));
    }
    if latest_semantic_record(
        journal.records(),
        &command.intent_id,
        &command.source_key,
        &command.operation_key,
    )
    .is_none_or(|latest| latest.head().record_id != command.target_record_id)
    {
        return Err(PolicyError::ControlReceipt(
            "control receipt targets a superseded semantic state".into(),
        ));
    }
    let head: PolicyRecordHead =
        journal.next_head(APPLIED_CONTRACT, applied_record_id, recorded_at)?;
    Ok(HotScopeRecordV1::Applied(HotScopeAppliedV1 {
        head,
        intent_id: command.intent_id.clone(),
        target_record_id: command.target_record_id.clone(),
        source_key: command.source_key.clone(),
        operation_key: command.operation_key.clone(),
        generation: command.generation,
        presence,
        control_command_id: command.command_id.clone(),
        control_bytes_digest: expected_digest,
        control_write_reservation_id: command.control_write_reservation_id.clone(),
        control_write_reservation_digest: command.supervisor_reservation_digest.clone(),
        control_write_attempt_ordinal: command.attempt_ordinal,
        control_write_receipt_id: receipt.receipt_id.clone(),
        control_handed_to_adapter_at: receipt.handed_to_source_adapter_at,
        adapter_version: command.adapter_version.clone(),
        provider_acceptance: stable("not_asserted")?,
        coverage_status: stable("not_asserted")?,
    }))
}

fn digest(bytes: &[u8]) -> Result<ValueDigest, PolicyError> {
    ValueDigest::new(format!("sha256:{:x}", Sha256::digest(bytes)))
        .map_err(|error| PolicyError::InvalidValue(error.to_string()))
}

fn stable(value: impl Into<String>) -> Result<StableString, PolicyError> {
    StableString::new(value).map_err(|error| PolicyError::InvalidValue(error.to_string()))
}

fn validate_supervisor_key(value: &str, label: &str) -> Result<(), PolicyError> {
    if value.is_empty()
        || value.len() > 255
        || value.trim() != value
        || value.chars().any(char::is_control)
        || value.contains('/')
        || value.contains('\\')
    {
        Err(PolicyError::ControlReceipt(format!(
            "supervisor {label} is malformed"
        )))
    } else {
        Ok(())
    }
}
