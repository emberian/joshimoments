use joshi_domain::{AssetId, CoverageId, OpenVariant, StableString, UtcTimestamp, WireU64};
use joshi_evidence::EvidenceDraft;
use joshi_sources::{
    ContentType, EvidenceContext, FrameDirection, LogicalSourceLocator, ProviderEventTime,
    RawSourceFrame, RetainedFrameEnvelope, SourceId, StreamClass, Transport, UnixMillis,
};
use joshi_wallet_source::{
    AcquisitionPlanner, AcquisitionResponseContext, AcquisitionSurface, AttentionPromotionError,
    AttentionPromotionInput, BudgetLedger, BudgetUse, CandidateEpistemicStatus, Canonicality,
    ChainCorrectionKind, Commitment, CoverageVerificationStatus, DecodedSwapInput,
    FundingHypothesisInput, InstructionAccount, InstructionFact, LeaseBook, LeaseError,
    NormalizationError, NormalizationIssue, PlanConfig, PlanError, PublicKey, ReadBudget,
    ReadRequestTemplate, ScopeInput, ScopeLease, ScopeTarget, Venue, admit_decoded_swap,
    apply_pinned_protocol_decoder, decode_pinned_protocol_instruction, normalize_frame,
    propose_funding_hypothesis, reconcile_transaction_facts, summarize_mint_relative,
    to_topology_facts,
};
use joshi_wallet_topology::{
    ReducerConfig, SnapshotId, SnapshotRequest, TOPOLOGY_CONTRACT_VERSION, TopologyFact,
    TopologyInput, TopologyReducer,
};

const RAW_HISTORY: &[u8] = include_bytes!(
    "../../../fixtures/wallet-source/helius_get_transactions_for_address_finalized.json"
);
const FAILED_TRANSACTION: &[u8] =
    include_bytes!("../../../fixtures/wallet-source/solana_get_transaction_failed_finalized.json");
const ENHANCED: &[u8] = include_bytes!(
    "../../../fixtures/wallet-source/helius_legacy_enhanced_projection_finalized.json"
);
const FUTURE_SCOPE: &[u8] =
    include_bytes!("../../../fixtures/wallet-source/scope_input_future_known_rejected.json");
const CALLOUT_PROMOTION: &[u8] =
    include_bytes!("../../../fixtures/wallet-source/attention_promotion_callout.json");
const PUMP_DIFFERENTIAL: &[u8] =
    include_bytes!("../../../fixtures/wallet-source/pump_decoder_differential.json");
const FINALIZED_PUMP_EXACT: &[u8] =
    include_bytes!("../../../fixtures/wallet-source/finalized_pump_pumpswap_exact.json");

fn timestamp(value: &str) -> UtcTimestamp {
    value.parse().unwrap()
}

fn stable(value: &str) -> StableString {
    StableString::new(value).unwrap()
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct DifferentialCorpus {
    vectors: Vec<DifferentialVector>,
}

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct DifferentialVector {
    case_id: String,
    program_id: String,
    instruction_data_base58: String,
    instruction_data_hex: String,
    expected_kind: String,
    expected_intent_kind: String,
    expected_track_volume: String,
    first_atoms: String,
    second_atoms: String,
}

#[test]
fn pinned_decoder_matches_official_anchor_differential_vectors() {
    let corpus: DifferentialCorpus = serde_json::from_slice(PUMP_DIFFERENTIAL).unwrap();
    assert_eq!(corpus.vectors.len(), 8);
    let key = PublicKey::new("4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi").unwrap();
    for vector in corpus.vectors {
        let raw = bs58::decode(&vector.instruction_data_base58)
            .into_vec()
            .unwrap();
        let mut hex = String::with_capacity(raw.len() * 2);
        for byte in &raw {
            write!(&mut hex, "{byte:02x}").unwrap();
        }
        assert_eq!(hex, vector.instruction_data_hex, "{}", vector.case_id);
        let accounts = (0_u64..27)
            .map(|ordinal| InstructionAccount {
                account: key.clone(),
                ordinal: ordinal.into(),
                signer: true,
                writable: true,
                role: None,
            })
            .collect();
        let instruction = InstructionFact {
            instruction_id: stable(&format!("differential:{}", vector.case_id)),
            transaction_fact_id: stable("differential:transaction:v1"),
            outer_index: 0.into(),
            inner_index: None,
            program_id: Some(PublicKey::new(&vector.program_id).unwrap()),
            raw_data_base58: Some(stable(&vector.instruction_data_base58)),
            parsed_type: None,
            accounts,
            execution_succeeded: true,
        };
        let decoded = decode_pinned_protocol_instruction(&instruction)
            .unwrap()
            .unwrap();
        let value = serde_json::to_value(decoded).unwrap();
        assert_eq!(
            value["instructionKind"],
            serde_json::Value::String(vector.expected_kind),
            "{}",
            vector.case_id
        );
        assert_eq!(
            value["intent"]["kind"],
            serde_json::Value::String(vector.expected_intent_kind),
            "{}",
            vector.case_id
        );
        assert_eq!(
            value["trackVolume"]["kind"],
            serde_json::Value::String(vector.expected_track_volume),
            "{}",
            vector.case_id
        );
        let values = value["intent"].as_object().unwrap();
        let mut atoms = values
            .iter()
            .filter(|(name, _)| name.as_str() != "kind")
            .map(|(_, value)| value.as_str().unwrap().to_owned())
            .collect::<Vec<_>>();
        atoms.sort();
        let mut expected = vec![vector.first_atoms, vector.second_atoms];
        expected.sort();
        assert_eq!(atoms, expected, "{}", vector.case_id);
    }
}

#[test]
fn pinned_decoder_promotes_only_executed_instruction_scoped_legs() {
    let output = normalize_frame(
        frame(FINALIZED_PUMP_EXACT, 404),
        evidence_context(404),
        &response_context(AcquisitionSurface::HeliusGetTransactionsForAddress),
    )
    .unwrap();
    assert_eq!(output.normalized.raw_transactions.len(), 2);
    let mut pump_buy = output.normalized.raw_transactions[0].clone();
    let buy_results = apply_pinned_protocol_decoder(&mut pump_buy).unwrap();
    assert_eq!(buy_results.len(), 1);
    let buy = &pump_buy.decoded_swaps[0];
    assert_eq!(buy.input_atoms, WireU64::new(310));
    assert_eq!(buy.output_atoms, WireU64::new(300));
    assert_eq!(buy.venue, Venue::PumpBondingCurve);

    let mut pumpswap_sell = output.normalized.raw_transactions[1].clone();
    let sell_results = apply_pinned_protocol_decoder(&mut pumpswap_sell).unwrap();
    assert_eq!(sell_results.len(), 1);
    let sell = &pumpswap_sell.decoded_swaps[0];
    assert_eq!(sell.input_atoms, WireU64::new(800));
    assert_eq!(sell.output_atoms, WireU64::new(780));
    assert_eq!(sell.venue, Venue::PumpSwap);

    // The official instruction limit was 760, deliberately different from the landed 780.
    let intent_value = serde_json::to_value(&sell_results[0].instruction.intent).unwrap();
    assert_eq!(intent_value["min_quote_amount_out"], "760");
}

#[test]
fn pinned_decoder_keeps_intent_when_one_fill_leg_is_missing() {
    let mut value: serde_json::Value = serde_json::from_slice(FINALIZED_PUMP_EXACT).unwrap();
    value["result"]["data"][0]["meta"]["innerInstructions"][0]["instructions"]
        .as_array_mut()
        .unwrap()
        .pop();
    let bytes = serde_json::to_vec(&value).unwrap();
    let mut dynamic_frame = frame(FINALIZED_PUMP_EXACT, 405);
    dynamic_frame.body = bytes.into();
    let output = normalize_frame(
        dynamic_frame,
        evidence_context(405),
        &response_context(AcquisitionSurface::HeliusGetTransactionsForAddress),
    )
    .unwrap();
    let mut raw = output.normalized.raw_transactions[0].clone();
    let decoded = apply_pinned_protocol_decoder(&mut raw).unwrap();
    assert_eq!(decoded.len(), 1);
    assert!(decoded[0].exact_swap.is_none());
    assert!(raw.decoded_swaps.is_empty());
}

fn frame(bytes: &'static [u8], sequence: u64) -> RawSourceFrame {
    RawSourceFrame {
        contract_version: joshi_sources::ADAPTER_CONTRACT_VERSION.to_owned(),
        source: SourceId::HeliusHttp,
        transport: Transport::Fixture,
        stream_class: StreamClass::Backfill,
        direction: FrameDirection::Inbound,
        content_type: ContentType::Json,
        received_at: UnixMillis(1_786_881_600_000),
        connection_epoch: 0,
        sequence,
        http_status: Some(200),
        safe_headers: Vec::new(),
        body: bytes.to_vec().into(),
    }
}

fn evidence_context(sequence: u64) -> EvidenceContext {
    EvidenceContext {
        occurrence_namespace: "wallet-source-offline-001".to_owned(),
        redacted_request_fingerprint_material: format!("wallet fixture page {sequence}"),
        parent_acquisition_id: None,
        locator: LogicalSourceLocator::Fixture {
            name: format!("wallet-source-{sequence}"),
        },
        source_variant: OpenVariant::known("wallet_transaction_page").unwrap(),
        source_cursor: None,
        source_events: Vec::new(),
        provider_event_time: ProviderEventTime::Missing {
            reason: "page_contains_multiple_chain_times".to_owned(),
        },
        chain_slot: None,
        transaction_index: None,
        instruction_path: Vec::new(),
        log_index: None,
        finality: Some(OpenVariant::known("finalized").unwrap()),
        acquisition_started_at: timestamp("2026-08-16T12:00:00.000000Z"),
        requested_at: Some(timestamp("2026-08-16T12:00:00.000000Z")),
        monotonic_clock_id: "wallet-source-test-process".to_owned(),
        acquisition_started_monotonic_ns: 10,
        received_monotonic_ns: 30,
        persisted_at: timestamp("2026-08-16T12:00:00.000000Z"),
    }
}

fn response_context(surface: AcquisitionSurface) -> AcquisitionResponseContext {
    AcquisitionResponseContext {
        surface,
        scope_ids: vec![stable("scope:wallet:fixture")],
        requested_public_keys: vec![
            PublicKey::new("M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K").unwrap(),
        ],
        mint_filter: Some(PublicKey::new("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v").unwrap()),
        commitment: Commitment::Finalized,
        available_at: timestamp("2026-08-16T12:00:00.000000Z"),
        cursor_before: None,
        coverage_gap_ids: vec![stable("gap:before-fixture")],
        coverage_ids: vec![stable("coverage:wallet:fixture")],
        transaction_versions: Vec::new(),
    }
}

#[test]
fn raw_history_preserves_bytes_and_derives_only_direct_facts() {
    let output = normalize_frame(
        frame(RAW_HISTORY, 1),
        evidence_context(1),
        &response_context(AcquisitionSurface::HeliusGetTransactionsForAddress),
    )
    .unwrap();
    let EvidenceDraft::Observation(observation) = &output.evidence else {
        panic!("expected exact observation")
    };
    let retained: RetainedFrameEnvelope = serde_json::from_slice(&observation.payload).unwrap();
    assert_eq!(retained.body, RAW_HISTORY);
    let fact = &output.normalized.raw_transactions[0];
    assert!(fact.succeeded);
    assert_eq!(fact.version, WireU64::new(1));
    assert_eq!(fact.canonicality, Canonicality::ObservedAtCommitment);
    assert_eq!(
        fact.same_transaction_bundle.transaction_fact_id,
        fact.fact_id
    );
    assert_eq!(fact.transaction.transaction_index, Some(WireU64::new(7)));
    assert!(fact.account_roles[0].signer);
    assert_eq!(fact.executed_transfers.len(), 1);
    assert_eq!(fact.executed_transfers[0].atoms, WireU64::new(1_000));
    assert!(
        fact.programs
            .iter()
            .any(|program| program.venue == Venue::PumpBondingCurve)
    );
    assert_eq!(
        output
            .normalized
            .coverage
            .source_cursor_candidate
            .as_ref()
            .unwrap()
            .as_str(),
        "355001234:7"
    );
    assert!(!output.normalized.coverage.page_exhausted);
    assert_eq!(
        output.normalized.coverage.verification_status,
        CoverageVerificationStatus::RequestedUnverified
    );
}

#[test]
fn mint_relative_flow_is_balance_effect_not_buy_claim() {
    let output = normalize_frame(
        frame(RAW_HISTORY, 2),
        evidence_context(2),
        &response_context(AcquisitionSurface::HeliusGetTransactionsForAddress),
    )
    .unwrap();
    let mint = PublicKey::new("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v").unwrap();
    let wallet = PublicKey::new("M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K").unwrap();
    let flow = summarize_mint_relative(
        stable("cohort:fixture:v1"),
        &mint,
        &wallet,
        &output.normalized.raw_transactions,
        timestamp("2026-08-16T12:00:00.000000Z"),
    )
    .unwrap()
    .unwrap();
    assert_eq!(flow.gross_in_atoms, WireU64::new(0));
    assert_eq!(flow.gross_out_atoms, WireU64::new(1_000_000));
    assert_eq!(flow.transaction_count, WireU64::new(1));
}

#[test]
fn decoded_swap_and_funding_hypothesis_stay_evidence_bound() {
    let output = normalize_frame(
        frame(RAW_HISTORY, 22),
        evidence_context(22),
        &response_context(AcquisitionSurface::HeliusGetTransactionsForAddress),
    )
    .unwrap();
    let fact = &output.normalized.raw_transactions[0];
    let swap = admit_decoded_swap(
        DecodedSwapInput {
            decode_id: stable("swap:fixture:1"),
            decoder_version: stable("pump-idl-decoder:test-v1"),
            observation_id: fact.observation_id.clone(),
            transaction: fact.transaction.clone(),
            instruction_path: vec![1.into()],
            event_ordinal: 0.into(),
            trader_wallet: PublicKey::new("M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K").unwrap(),
            program_id: PublicKey::new("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P").unwrap(),
            pool: None,
            input_asset_id: stable("solana.mint:EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
            input_atoms: 1_000_000.into(),
            output_asset_id: stable("solana.mint:So11111111111111111111111111111111111111112"),
            output_atoms: 10_000.into(),
            available_at: timestamp("2026-08-16T12:00:00.000000Z"),
        },
        fact,
    )
    .unwrap();
    assert_eq!(swap.venue, Venue::PumpBondingCurve);

    let transfer = &fact.executed_transfers[0];
    let funding = propose_funding_hypothesis(
        FundingHypothesisInput {
            hypothesis_id: stable("funding-hypothesis:fixture:1"),
            transfer_flow_id: transfer.flow_id.clone(),
            candidate_recipient: transfer.to_account.clone(),
            method: stable("first_observed_native_transfer_candidate"),
            inference_version: stable("funding-resolver.test-v1"),
            evidence_observation_ids: vec![fact.observation_id.clone()],
            available_at: timestamp("2026-08-16T12:00:00.000000Z"),
        },
        transfer,
    )
    .unwrap();
    assert!(!funding.establishes_common_ownership);
}

#[test]
fn failed_transaction_retains_instruction_but_emits_no_executed_transfer() {
    let output = normalize_frame(
        frame(FAILED_TRANSACTION, 3),
        evidence_context(3),
        &response_context(AcquisitionSurface::SolanaGetTransaction),
    )
    .unwrap();
    let fact = &output.normalized.raw_transactions[0];
    assert!(!fact.succeeded);
    assert_eq!(fact.instructions.len(), 1);
    assert!(!fact.instructions[0].execution_succeeded);
    assert!(fact.executed_transfers.is_empty());
    assert!(
        output
            .normalized
            .issues
            .contains(&NormalizationIssue::MissingTransactionIndex)
    );
}

#[test]
fn enhanced_history_remains_a_non_authoritative_projection() {
    let output = normalize_frame(
        frame(ENHANCED, 4),
        evidence_context(4),
        &response_context(AcquisitionSurface::HeliusLegacyEnhancedCrossCheck),
    )
    .unwrap();
    assert!(output.normalized.raw_transactions.is_empty());
    let projection = &output.normalized.enhanced_projections[0];
    assert!(projection.claims_swap);
    assert!(projection.requires_raw_reconciliation);
    assert_eq!(projection.transfers.len(), 2);
}

#[test]
fn future_known_candidate_is_rejected_at_lease_admission() {
    let input: ScopeInput = serde_json::from_slice(FUTURE_SCOPE).unwrap();
    assert!(matches!(
        &input.target,
        ScopeTarget::Wallet { candidate }
            if candidate.epistemic_status == CandidateEpistemicStatus::Inferred
    ));
    let lease = ScopeLease {
        lease_id: stable("lease:future-known"),
        input,
        opened_at: timestamp("2026-08-16T12:05:00.000000Z"),
        expires_at: timestamp("2026-08-16T12:15:00.000000Z"),
        reason_input_ids: vec![stable("attention:callout:1")],
    };
    assert_eq!(
        LeaseBook::default().apply(lease),
        Err(LeaseError::FutureKnownCandidate)
    );
}

#[test]
fn strict_input_rejects_unknown_fields() {
    let mut value: serde_json::Value = serde_json::from_slice(FUTURE_SCOPE).unwrap();
    value["surpriseAuthority"] = serde_json::json!(true);
    assert!(serde_json::from_value::<ScopeInput>(value).is_err());
}

#[test]
fn normalized_availability_cannot_precede_retained_evidence() {
    let mut context = response_context(AcquisitionSurface::HeliusGetTransactionsForAddress);
    context.available_at = timestamp("2026-08-16T11:59:59.999999Z");
    assert!(matches!(
        normalize_frame(frame(RAW_HISTORY, 29), evidence_context(29), &context),
        Err(NormalizationError::InvalidAvailability)
    ));
}

#[test]
fn plan_identity_is_namespaced_and_legacy_projection_defaults_off() {
    let mut input: ScopeInput = serde_json::from_slice(FUTURE_SCOPE).unwrap();
    let ScopeTarget::Wallet { candidate } = &mut input.target else {
        panic!("expected wallet")
    };
    candidate.available_at = timestamp("2026-08-16T12:05:00.000000Z");
    let lease = ScopeLease {
        lease_id: stable("lease:valid"),
        input,
        opened_at: timestamp("2026-08-16T12:05:00.000000Z"),
        expires_at: timestamp("2026-08-16T12:15:00.000000Z"),
        reason_input_ids: vec![stable("attention:callout:1")],
    };
    let mut book = LeaseBook::default();
    book.apply(lease).unwrap();
    let active = book.active_at(timestamp("2026-08-16T12:06:00.000000Z"));
    let planner = AcquisitionPlanner::new(PlanConfig::default()).unwrap();
    let first = planner.plan(&stable("plan:run-one"), &active).unwrap();
    let second = planner.plan(&stable("plan:run-two"), &active).unwrap();
    assert_ne!(first.reads[0].request_id, second.reads[0].request_id);
    assert!(!first.legacy_enhanced_is_authoritative);
    assert!(
        first
            .reads
            .iter()
            .all(|read| read.surface != AcquisitionSurface::HeliusLegacyEnhancedCrossCheck)
    );
    for read in &first.reads {
        let ReadRequestTemplate::JsonRpc { method, .. } = read.request_template().unwrap() else {
            panic!("default planner emits modern JSON-RPC only")
        };
        assert!(matches!(
            method.as_str(),
            "transactionSubscribe" | "getTransactionsForAddress"
        ));
        assert!(!matches!(
            method.as_str(),
            "sendTransaction" | "simulateTransaction" | "getLatestBlockhash"
        ));
    }
    let mut tight = active;
    tight[0].budget.max_provider_credits = 10.into();
    assert_eq!(
        planner.plan(&stable("plan:over-budget"), &tight),
        Err(PlanError::BudgetExceeded)
    );
}

#[test]
fn independent_budget_dimensions_fail_closed() {
    let mut ledger = BudgetLedger::new(ReadBudget {
        max_requests: 2.into(),
        max_pages: 2.into(),
        max_response_bytes: 100.into(),
        max_provider_credits: 20.into(),
        max_public_keys: 1.into(),
    });
    ledger
        .admit(&BudgetUse {
            requests: 1.into(),
            pages: 1.into(),
            response_bytes: 90.into(),
            provider_credits: 10.into(),
        })
        .unwrap();
    assert!(
        ledger
            .admit(&BudgetUse {
                requests: 1.into(),
                pages: 1.into(),
                response_bytes: 11.into(),
                provider_credits: 10.into(),
            })
            .is_err()
    );
}

#[test]
fn social_promotion_keeps_only_evidence_references() {
    let promotion: AttentionPromotionInput = serde_json::from_slice(CALLOUT_PROMOTION).unwrap();
    assert_eq!(promotion.validate_cluster_binding(), Ok(()));
    assert_eq!(promotion.reason_variant.as_str(), "pump_callout_observed");
    assert_eq!(promotion.evidence_input_ids.len(), 1);
    assert_eq!(
        promotion
            .wallet_id
            .unwrap()
            .domain_account_id()
            .unwrap()
            .as_str(),
        "solana.account:M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K"
    );
}

#[test]
fn bare_current_cluster_hypothesis_is_rejected() {
    let mut promotion: serde_json::Value = serde_json::from_slice(CALLOUT_PROMOTION).unwrap();
    promotion["callerClusterContextId"] = serde_json::Value::Null;
    let promotion: AttentionPromotionInput = serde_json::from_value(promotion).unwrap();
    assert_eq!(
        promotion.validate_cluster_binding(),
        Err(AttentionPromotionError::BareClusterHypothesis)
    );
}

#[test]
#[allow(clippy::too_many_lines)]
fn transaction_version_and_topology_bind_every_dependent_fact() {
    let initial_output = normalize_frame(
        frame(RAW_HISTORY, 32),
        evidence_context(32),
        &response_context(AcquisitionSurface::HeliusGetTransactionsForAddress),
    )
    .unwrap();
    let initial_facts = to_topology_facts(&initial_output.normalized.raw_transactions[0]).unwrap();
    let mut context = response_context(AcquisitionSurface::HeliusGetTransactionsForAddress);
    context.coverage_ids = vec![
        stable("coverage:wallet:z"),
        stable("coverage:wallet:a"),
        stable("coverage:wallet:z"),
    ];
    context.transaction_versions.push(joshi_wallet_source::TransactionVersionInput {
        signature: stable("5h6xBEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv"),
        version: 2.into(),
        supersedes_transaction_fact_id: Some(stable(
            "solana.transaction:5h6xBEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv:v1",
        )),
        canonicality: Canonicality::Canonical,
    });
    let output = normalize_frame(frame(RAW_HISTORY, 30), evidence_context(30), &context).unwrap();
    let mut raw = output.normalized.raw_transactions[0].clone();
    let swap = admit_decoded_swap(
        DecodedSwapInput {
            decode_id: stable("swap:fixture:topology"),
            decoder_version: stable("pump-idl-decoder:test-v1"),
            observation_id: raw.observation_id.clone(),
            transaction: raw.transaction.clone(),
            instruction_path: vec![1.into()],
            event_ordinal: 0.into(),
            trader_wallet: PublicKey::new("M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K").unwrap(),
            program_id: PublicKey::new("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P").unwrap(),
            pool: None,
            input_asset_id: stable("solana.mint:EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
            input_atoms: 1_000_000.into(),
            output_asset_id: stable("solana.mint:So11111111111111111111111111111111111111112"),
            output_atoms: 10_000.into(),
            available_at: timestamp("2026-08-16T12:00:00.000000Z"),
        },
        &raw,
    )
    .unwrap();
    raw.decoded_swaps.push(swap);
    let facts = to_topology_facts(&raw).unwrap();
    let transaction_fact_id = facts
        .iter()
        .find_map(|fact| match fact {
            TopologyFact::Transaction(transaction) => {
                assert_eq!(transaction.version, WireU64::new(2));
                assert!(transaction.supersedes_transaction_fact_id.is_some());
                Some(transaction.transaction_fact_id.clone())
            }
            _ => None,
        })
        .unwrap();
    assert!(
        facts
            .iter()
            .all(|fact| fact.transaction_fact_id() == &transaction_fact_id)
    );
    assert!(
        facts
            .iter()
            .any(|fact| matches!(fact, TopologyFact::CallerAccount(_)))
    );
    assert!(
        facts
            .iter()
            .any(|fact| matches!(fact, TopologyFact::Transfer(_)))
    );
    assert!(
        facts
            .iter()
            .any(|fact| matches!(fact, TopologyFact::Swap(_)))
    );
    let bundle = facts
        .iter()
        .find_map(|fact| match fact {
            TopologyFact::SameTransactionBundle(bundle) => Some(bundle),
            _ => None,
        })
        .unwrap();
    assert!(!bundle.ordered_members.is_empty());
    assert_eq!(bundle.evidence.coverage_ids.len(), 2);
    assert_eq!(
        bundle.evidence.coverage_ids[0].as_str(),
        "coverage:wallet:a"
    );
    let mut versioned_facts = initial_facts;
    versioned_facts.extend(facts);
    let snapshot = TopologyReducer::new(ReducerConfig::new(100, 10, 100, 100).unwrap())
        .snapshot(
            &TopologyInput {
                contract: stable(TOPOLOGY_CONTRACT_VERSION),
                facts: versioned_facts,
                hypotheses: Vec::new(),
            },
            SnapshotRequest {
                snapshot_id: SnapshotId::new("snapshot:wallet-source:fixture").unwrap(),
                available_through: timestamp("2026-08-16T12:00:00.000000Z"),
                event_slot: raw.transaction.slot,
                event_time: timestamp("2026-08-16T12:00:00.000000Z"),
                accepted_finalities: vec![stable("finalized")],
                accepted_canonicalities: vec![stable("canonical")],
                focus_mint_ids: vec![
                    AssetId::new("solana.mint:EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
                        .unwrap(),
                ],
                requested_coverage_ids: vec![
                    CoverageId::new("coverage:wallet:a").unwrap(),
                    CoverageId::new("coverage:wallet:z").unwrap(),
                ],
                co_trade_window_slots: 10.into(),
                max_pair_rows: 100.into(),
            },
        )
        .unwrap();
    assert!(!snapshot.accepted_facts.is_empty());
}

#[test]
fn noncanonical_and_reappeared_corrections_are_append_only() {
    let output = normalize_frame(
        frame(RAW_HISTORY, 31),
        evidence_context(31),
        &response_context(AcquisitionSurface::HeliusGetTransactionsForAddress),
    )
    .unwrap();
    let canonical = output.normalized.raw_transactions[0].clone();
    let mut noncanonical = canonical.clone();
    noncanonical.canonicality = Canonicality::NonCanonical;
    noncanonical.observation_id = joshi_domain::ObservationId::new("obs:noncanonical").unwrap();
    assert_eq!(
        reconcile_transaction_facts(
            &canonical,
            &noncanonical,
            timestamp("2026-08-16T12:01:00.000000Z"),
        )
        .unwrap()
        .kind,
        ChainCorrectionKind::TransactionBecameUnavailable
    );
    assert_eq!(
        reconcile_transaction_facts(
            &noncanonical,
            &canonical,
            timestamp("2026-08-16T12:02:00.000000Z"),
        )
        .unwrap()
        .kind,
        ChainCorrectionKind::Reappeared
    );
}
use std::fmt::Write as _;
