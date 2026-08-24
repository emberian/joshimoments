use crate::{
    AdmissionBatch, AdmissionError, AdmissionPolicy, PublicStoreReceiptV1, Sha256Digest,
    SourceDraftBatch, batch::source_registration, source_drafts,
};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use joshi_domain::{
    AcquisitionClocks, AcquisitionId, CoverageId, ObservationId, OpenVariant, RequestFingerprint,
    SourceId, StableString, UtcTimestamp, WireU64,
};
use joshi_evidence::{
    AcquisitionRecord, Boundary, CoverageGap, CoverageScope, CoverageWindow, EvidenceDraft,
    MonotonicReading, ObservationDraft, ObservationEventTime, ObservationMetadata,
    ObservationSourceEvent, ObservationTiming, SourceEventRecord,
};
use joshi_pump_api::{
    AccessClass, BodyCapture, FetchOutcome, IdentityStore, ROUTE_CATALOG, RouteId, RouteSpec,
    SOURCE_CONTRACT,
};
use std::collections::BTreeSet;

const PUMP_SOURCE_ID: &str = "pump.api.product.v1";

#[derive(Clone, Debug)]
pub struct PumpAdmission {
    pub batch: AdmissionBatch,
    pub acquisition_ids: Vec<String>,
    pub coverage_gap_ids: Vec<String>,
}

#[allow(clippy::too_many_lines)]
/// Adapt a completed direct-Pump fetch outcome into one durable admission batch.
///
/// # Errors
///
/// Returns an error for invalid contracts, clocks, bodies, coverage, identities, or wire values.
pub fn admit_pump_outcome(
    outcome: &FetchOutcome,
    batch_id: &str,
    committed_at: UtcTimestamp,
    committed_mono_ns: u64,
) -> Result<PumpAdmission, AdmissionError> {
    if outcome.contract != "joshi.pump_api.fetch_outcome.v1"
        || outcome.request_group_id.trim().is_empty()
    {
        return Err(AdmissionError::Contract(
            "unsupported Pump fetch outcome".into(),
        ));
    }
    let source_id = SourceId::new(PUMP_SOURCE_ID)?;
    let mut drafts = Vec::new();
    let mut source_events: Vec<SourceEventRecord> = Vec::new();
    let mut private_observations = BTreeSet::new();
    let mut acquisition_ids = Vec::new();
    for attempt in &outcome.attempts {
        if attempt.contract != SOURCE_CONTRACT || attempt.catalog_version != ROUTE_CATALOG {
            return Err(AdmissionError::Contract(
                "Pump attempt contract/catalog mismatch".into(),
            ));
        }
        let route_id = attempt.route_id.parse::<RouteId>().map_err(|_| {
            AdmissionError::SourceEnvelope("Pump attempt has an unknown route".into())
        })?;
        let route = RouteSpec::for_id(route_id);
        if attempt.access_class != route.access.to_string()
            || attempt.stability != route.stability.to_string()
            || attempt.transport != route.transport.to_string()
        {
            return Err(AdmissionError::SourceEnvelope(
                "Pump attempt route policy differs from the pinned catalog".into(),
            ));
        }
        validate_sha(&attempt.request_fingerprint)?;
        let acquisition = acquisition(attempt, source_id.clone(), committed_at)?;
        let envelope_id = ObservationId::new(format!("obs:{}:attempt", attempt.acquisition_id))?;
        let is_private = requires_private_retention(route.access, &attempt.session_class);
        let envelope = serde_json::to_vec(attempt)?;
        let mut envelope_draft = observation(
            acquisition.clone(),
            envelope_id.clone(),
            0,
            "attempt_envelope",
            "application/vnd.joshi.pump-api-acquisition+json",
            envelope,
            timestamp(&attempt.clocks.received_at)?,
            committed_at,
        )?;
        // A mint the envelope carries as a request-resolved public path segment becomes a durable
        // source event — the same mint-as-subject mechanism the chain census uses, so a candles
        // acquisition and a wallet sweep about one coin converge on one `solana.token_mint`
        // natural key. The link hangs off the *attempt envelope*, because those retained bytes
        // are what actually state the mint; the provider body never does, and linking the body
        // would claim it did. The event identity is pump-scoped because the store refuses one
        // event identity owned by two sources, and the census already owns `mint:<mint>`.
        if let Some(mint) = attempt.resolved_public_path.get("mint") {
            let event = mint_source_event(&source_id, mint)?;
            envelope_draft.observation.source_events = vec![ObservationSourceEvent {
                source_event_id: event.source_event_id.clone(),
                relation: OpenVariant::known("contains")?,
                event_ordinal: None,
            }];
            if !source_events.iter().any(|existing: &SourceEventRecord| {
                existing.source_event_id == event.source_event_id
            }) {
                source_events.push(event);
            }
        }
        drafts.push(EvidenceDraft::Observation(envelope_draft));
        if is_private {
            private_observations.insert(envelope_id.to_string());
        }
        match &attempt.body {
            BodyCapture::Exact {
                boundary,
                media_type,
                bytes_base64,
                byte_length,
                blob_id,
            } => {
                if boundary.trim().is_empty() {
                    return Err(AdmissionError::SourceEnvelope(
                        "missing Pump exact-body boundary".into(),
                    ));
                }
                let bytes = STANDARD.decode(bytes_base64).map_err(|_| {
                    AdmissionError::SourceEnvelope("invalid Pump exact-body base64".into())
                })?;
                validate_body(&bytes, byte_length, blob_id)?;
                let observation_id =
                    ObservationId::new(format!("obs:{}:body", attempt.acquisition_id))?;
                drafts.push(EvidenceDraft::Observation(observation(
                    acquisition.clone(),
                    observation_id.clone(),
                    1,
                    "provider_body",
                    media_type,
                    bytes,
                    timestamp(&attempt.clocks.received_at)?,
                    committed_at,
                )?));
                if is_private {
                    private_observations.insert(observation_id.to_string());
                }
            }
            BodyCapture::Truncated {
                boundary,
                media_type,
                prefix_base64,
                prefix_length,
                received_at_least,
                prefix_blob_id,
                limit_bytes,
            } => {
                if boundary.trim().is_empty() {
                    return Err(AdmissionError::SourceEnvelope(
                        "missing Pump prefix boundary".into(),
                    ));
                }
                let bytes = STANDARD.decode(prefix_base64).map_err(|_| {
                    AdmissionError::SourceEnvelope("invalid Pump prefix base64".into())
                })?;
                validate_body(&bytes, prefix_length, prefix_blob_id)?;
                let received = parse_u64(received_at_least)?;
                let limit = parse_u64(limit_bytes)?;
                if received < bytes.len() as u64 || limit != bytes.len() as u64 {
                    return Err(AdmissionError::SourceEnvelope(
                        "Pump truncated-body bounds mismatch".into(),
                    ));
                }
                let observation_id =
                    ObservationId::new(format!("obs:{}:prefix", attempt.acquisition_id))?;
                drafts.push(EvidenceDraft::Observation(observation(
                    acquisition.clone(),
                    observation_id.clone(),
                    1,
                    "provider_body_prefix",
                    media_type,
                    bytes,
                    timestamp(&attempt.clocks.received_at)?,
                    committed_at,
                )?));
                if is_private {
                    private_observations.insert(observation_id.to_string());
                }
            }
            BodyCapture::Missing { reason } if reason.trim().is_empty() => {
                return Err(AdmissionError::SourceEnvelope(
                    "Pump missing-body reason is empty".into(),
                ));
            }
            BodyCapture::Missing { .. } => {}
        }
        acquisition_ids.push(attempt.acquisition_id.clone());
    }

    for window in &outcome.coverage_windows {
        let scope = pump_scope(&source_id, &window.scope)?;
        drafts.push(EvidenceDraft::CoverageWindow(CoverageWindow {
            coverage_id: CoverageId::new(window.window_id.clone())?,
            scope,
            lower: Boundary::Wall {
                value: timestamp(&window.observed_from)?,
            },
            upper: Some(Boundary::Wall {
                value: timestamp(&window.observed_to)?,
            }),
            state: OpenVariant::known(window.completeness.clone())?,
            available_at: committed_at,
        }));
    }
    let mut coverage_gap_ids = Vec::new();
    for gap in &outcome.coverage_gaps {
        let scope = pump_scope(&source_id, &gap.scope)?;
        let coverage_id = CoverageId::new(format!("coverage:pump-gap:{}", gap.gap_id))?;
        let lower = gap
            .boundary
            .last_accepted_cursor_fingerprint
            .as_ref()
            .map_or_else(
                || {
                    OpenVariant::known("source_boundary_missing")
                        .map(|reason| Boundary::Unknown { reason })
                },
                |value| {
                    StableString::new(value.clone()).map(|value| Boundary::SourceCursor { value })
                },
            )?;
        let upper = gap
            .boundary
            .first_resumed_cursor_fingerprint
            .as_ref()
            .map(|value| {
                StableString::new(value.clone()).map(|value| Boundary::SourceCursor { value })
            })
            .transpose()?;
        drafts.push(EvidenceDraft::CoverageWindow(CoverageWindow {
            coverage_id: coverage_id.clone(),
            scope: scope.clone(),
            lower: lower.clone(),
            upper: upper.clone(),
            state: OpenVariant::known("degraded")?,
            available_at: committed_at,
        }));
        drafts.push(EvidenceDraft::CoverageGap(CoverageGap {
            gap_id: CoverageId::new(gap.gap_id.clone())?,
            coverage_id,
            scope,
            lower,
            upper,
            reason: OpenVariant::known(gap.reason.clone())?,
            detected_at: timestamp(&gap.detected_at)?,
        }));
        coverage_gap_ids.push(gap.gap_id.clone());
    }
    acquisition_ids.sort();
    acquisition_ids.dedup();
    coverage_gap_ids.sort();
    coverage_gap_ids.dedup();
    let registration = source_registration(
        source_id,
        "pump_product_api",
        SOURCE_CONTRACT,
        env!("CARGO_PKG_VERSION"),
    )?;
    let mut batch = source_drafts(SourceDraftBatch {
        batch_id: StableString::new(batch_id)?,
        drafts,
        source_events,
        cursor_advances: Vec::new(),
        registrations: vec![registration],
        policy: AdmissionPolicy::public_source()?,
        committed_at,
        writer_clock_id: StableString::new("joshi-core-writer")?,
        committed_mono_ns,
        writer_build: StableString::new(env!("CARGO_PKG_VERSION"))?,
    })?;
    for id in private_observations {
        let policy = batch
            .store
            .observation_storage
            .get_mut(&id)
            .ok_or_else(|| {
                AdmissionError::SourceEnvelope(
                    "private Pump observation missing storage policy".into(),
                )
            })?;
        policy.retention_class = StableString::new("app_private")?;
        policy.force_external = true;
    }
    // Storage policy is outside the logical digest and is bound by the store admission digest.
    Ok(PumpAdmission {
        batch,
        acquisition_ids,
        coverage_gap_ids,
    })
}

/// One SPL mint the request path named, as a durable source event owned by the pump source.
///
/// The namespace and natural key are exactly the census's — `solana.token_mint`, the address as
/// the caller spelled it — so cross-source reconciliation happens on the public key itself. The
/// event kind states how the mint was established and claims nothing stronger: the request asked
/// about it. Not observed in a body, not a launch, not a trade, not a price.
fn mint_source_event(
    source_id: &SourceId,
    mint: &str,
) -> Result<SourceEventRecord, AdmissionError> {
    Ok(SourceEventRecord {
        source_event_id: joshi_domain::SourceEventId::new(format!("mint:pump:{mint}"))?,
        source_id: source_id.clone(),
        namespace: StableString::new("solana.token_mint")?,
        natural_key: StableString::new(mint)?,
        source_order_key: None,
        event_kind: OpenVariant::known("named_in_request_path")?,
    })
}

fn requires_private_retention(access_class: AccessClass, session_class: &str) -> bool {
    // `shared_product_key` is the provider's own shipped-to-every-visitor product key
    // (coin-communities' x-api-key): every browser sends the same value, it identifies the
    // product rather than a person, and the key itself never reaches an envelope — so a read
    // made with it carries nothing of Ember's and retains as public, exactly like a bare
    // anonymous read.
    !matches!(
        access_class,
        AccessClass::OfficiallyDescribedPublic | AccessClass::ObservedPublicProduct
    ) || !matches!(session_class, "none" | "public" | "shared_product_key")
}

/// Acknowledge pre-I/O occurrence reservations after an exact durable receipt.
///
/// # Errors
///
/// Returns an error if the receipt closure differs or an identity reservation cannot be acknowledged.
pub fn acknowledge_pump_reservations(
    identity: &IdentityStore,
    admission: &PumpAdmission,
    receipt: &PublicStoreReceiptV1,
) -> Result<(), AdmissionError> {
    if receipt.batch_id != admission.batch.store.evidence.batch_id.as_str()
        || receipt.batch_digest.as_str() != admission.batch.store.evidence.expected_digest.as_str()
    {
        return Err(AdmissionError::Receipt(
            "Pump ACK receipt does not close the submitted durable batch".into(),
        ));
    }
    if receipt.acquisition_ids != admission.acquisition_ids {
        return Err(AdmissionError::Receipt(
            "Pump ACK acquisition closure mismatch".into(),
        ));
    }
    for acquisition_id in &admission.acquisition_ids {
        identity.acknowledge_id(acquisition_id)?;
    }
    Ok(())
}

fn acquisition(
    attempt: &joshi_pump_api::Acquisition,
    source_id: SourceId,
    persisted_at: UtcTimestamp,
) -> Result<AcquisitionRecord, AdmissionError> {
    let started_at = timestamp(&attempt.clocks.started_at)?;
    let received_at = timestamp(&attempt.clocks.received_at)?;
    let started_ns = parse_u64(&attempt.clocks.started_monotonic_ns)?;
    let received_ns = parse_u64(&attempt.clocks.received_monotonic_ns)?;
    let elapsed = parse_u64(&attempt.clocks.elapsed_ns)?;
    if received_ns.checked_sub(started_ns) != Some(elapsed) || received_at < started_at {
        return Err(AdmissionError::SourceEnvelope(
            "Pump acquisition clocks are inconsistent".into(),
        ));
    }
    let clock = StableString::new(attempt.clocks.monotonic_clock_id.clone())?;
    Ok(AcquisitionRecord {
        acquisition_id: AcquisitionId::new(attempt.acquisition_id.clone())?,
        source_id,
        acquisition_kind: OpenVariant::known("poll")?,
        transport_kind: OpenVariant::known("http")?,
        parent_acquisition_id: None,
        request_fingerprint: RequestFingerprint::new(attempt.request_fingerprint.clone())?,
        contract_version: StableString::new(attempt.contract.clone())?,
        started_at,
        started_monotonic: Some(MonotonicReading {
            clock_id: clock.clone(),
            nanoseconds: WireU64::new(started_ns),
        }),
        source_locator: Some(StableString::new(attempt.source_locator.clone())?),
        source_cursor: None,
        clocks: AcquisitionClocks {
            requested_at: Some(started_at),
            received_at,
            persisted_at,
            monotonic_elapsed_ns: Some(WireU64::new(elapsed)),
            monotonic_domain: Some(clock),
        },
    })
}

#[allow(clippy::too_many_arguments)] // Explicit clock and evidence fields make fabrication visible.
fn observation(
    acquisition: AcquisitionRecord,
    observation_id: ObservationId,
    ordinal: u64,
    variant: &str,
    media_type: &str,
    payload: Vec<u8>,
    received_at: UtcTimestamp,
    persisted_at: UtcTimestamp,
) -> Result<ObservationDraft, AdmissionError> {
    let started = acquisition.started_monotonic.as_ref().ok_or_else(|| {
        AdmissionError::SourceEnvelope("Pump attempt lacks its required monotonic start".into())
    })?;
    let elapsed = acquisition.clocks.monotonic_elapsed_ns.ok_or_else(|| {
        AdmissionError::SourceEnvelope("Pump attempt lacks its required monotonic duration".into())
    })?;
    let monotonic = MonotonicReading {
        clock_id: started.clock_id.clone(),
        nanoseconds: WireU64::new(
            started
                .nanoseconds
                .get()
                .checked_add(elapsed.get())
                .ok_or_else(|| {
                    AdmissionError::SourceEnvelope("Pump monotonic clock overflow".into())
                })?,
        ),
    };
    Ok(ObservationDraft {
        acquisition,
        observation: ObservationMetadata {
            observation_id,
            acquisition_ordinal: WireU64::new(ordinal),
            observation_kind: OpenVariant::known("response")?,
            source_events: Vec::new(),
            source_variant: OpenVariant::known(variant)?,
            event_time: ObservationEventTime {
                status: OpenVariant::known("not_applicable")?,
                lower: None,
                upper: None,
                precision_us: None,
            },
            chain: None,
            source_cursor: None,
            timing: ObservationTiming {
                received_at,
                received_monotonic: monotonic,
                persisted_at,
                available_at: persisted_at,
            },
            parse_disposition: OpenVariant::known("opaque")?,
            quality_code: None,
            media_type: StableString::new(media_type)?,
        },
        payload,
    })
}

fn pump_scope(
    source_id: &SourceId,
    scope: &joshi_pump_api::CoverageScope,
) -> Result<CoverageScope, AdmissionError> {
    let subject = format!(
        "{}|{}|{}|{}|{}",
        scope.route_id,
        scope.request_fingerprint,
        scope.order_semantics,
        scope.cursor_in_fingerprint.as_deref().unwrap_or("none"),
        scope.page_size.as_deref().unwrap_or("none")
    );
    if subject.len() > 512 {
        return Err(AdmissionError::SourceEnvelope(
            "Pump coverage scope is too long".into(),
        ));
    }
    Ok(CoverageScope {
        source_id: source_id.clone(),
        family: OpenVariant::known("hot_lane")?,
        subject: Some(StableString::new(format!("pump-api:{subject}"))?),
    })
}

fn validate_body(bytes: &[u8], length: &str, digest: &str) -> Result<(), AdmissionError> {
    if parse_u64(length)?
        != u64::try_from(bytes.len())
            .map_err(|_| AdmissionError::SourceEnvelope("body length exceeds u64".into()))?
        || Sha256Digest::of_bytes(bytes).as_str() != validate_sha(digest)?.as_str()
    {
        return Err(AdmissionError::SourceEnvelope(
            "body length/digest mismatch".into(),
        ));
    }
    Ok(())
}

fn validate_sha(value: &str) -> Result<Sha256Digest, AdmissionError> {
    Ok(Sha256Digest::parse(value.to_owned())?)
}
fn parse_u64(value: &str) -> Result<u64, AdmissionError> {
    Ok(value.parse::<WireU64>()?.get())
}
fn timestamp(value: &str) -> Result<UtcTimestamp, AdmissionError> {
    value
        .parse()
        .map_err(|_| AdmissionError::SourceEnvelope("invalid six-digit UTC timestamp".into()))
}

#[cfg(test)]
mod tests {
    use super::{AccessClass, requires_private_retention};

    #[test]
    fn public_product_access_without_a_session_retains_as_public_source() {
        assert!(!requires_private_retention(
            AccessClass::OfficiallyDescribedPublic,
            "public"
        ));
        assert!(!requires_private_retention(
            AccessClass::ObservedPublicProduct,
            "none"
        ));
        assert!(
            !requires_private_retention(AccessClass::ObservedPublicProduct, "shared_product_key"),
            "the shipped product key is not a user credential; reads made with it are public"
        );
        assert!(requires_private_retention(
            AccessClass::AuthenticatedUserSession,
            "authenticated:fixture"
        ));
        assert!(
            requires_private_retention(AccessClass::AuthenticatedUserSession, "shared_product_key"),
            "a shared key never launders a session route into public retention"
        );
        assert!(requires_private_retention(
            AccessClass::ObservedPublicProduct,
            "authenticated:fixture"
        ));
    }
}
