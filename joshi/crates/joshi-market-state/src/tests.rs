use crate::*;
use joshi_attention::AttentionDataset;
use joshi_domain::{
    AccountId, AcquisitionId, AssertionId, AssetId, CommitSeq, CoverageId, ObservationId, PoolId,
    PositionId, ProtocolProfileId, SourceId, StableString, UtcTimestamp, ValueDigest, VenueId,
    WireU64, WireU128,
};
use serde::Deserialize;
use std::collections::{BTreeMap, BTreeSet};

const ATTENTION_FIXTURE: &str = include_str!("../../../fixtures/attention/study-ready.valid.json");
const SCENARIO_FIXTURE: &str = include_str!("../../../fixtures/market-state/adversarial.v1.json");

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ScenarioFixture {
    contract: String,
    cut: MarketStateCut,
    cases: Vec<ScenarioCase>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ScenarioCase {
    name: String,
    expected: String,
}

#[derive(Clone, Default)]
struct MemoryReader {
    history: BTreeMap<String, Vec<EffectiveFactRecord>>,
}

impl MemoryReader {
    fn insert(&mut self, assertion: EffectiveFactRecord) {
        self.history
            .entry(assertion.semantic_key.as_str().to_owned())
            .or_default()
            .push(assertion);
    }
}

impl EffectiveFactReader for MemoryReader {
    fn effective_assertions_as_known(
        &self,
        semantic_key: &str,
        cutoff: CommitSeq,
    ) -> Result<Vec<EffectiveFactRecord>, ReaderError> {
        let candidates: Vec<_> = self
            .history
            .get(semantic_key)
            .into_iter()
            .flatten()
            .filter(|assertion| assertion.produced_commit <= cutoff)
            .cloned()
            .collect();
        let superseded: BTreeSet<String> = candidates
            .iter()
            .filter_map(|assertion| assertion.supersedes_assertion_id.as_ref())
            .map(|id| id.as_str().to_owned())
            .collect();
        let mut effective: Vec<_> = candidates
            .into_iter()
            .filter(|assertion| !superseded.contains(assertion.assertion_id.as_str()))
            .collect();
        effective.sort_by(|left, right| {
            (&left.produced_commit, &left.assertion_id)
                .cmp(&(&right.produced_commit, &right.assertion_id))
        });
        Ok(effective)
    }
}

#[test]
fn four_stream_snapshot_is_deterministic_and_evidence_closed() {
    let fixture = scenarios();
    assert_case(&fixture, "complete_four_stream_snapshot", "accepted");
    let (reader, query) = accepted_inputs(&fixture.cut);
    let first = MarketStateReducer::new(&reader).reduce(query.clone());
    let second = MarketStateReducer::new(&reader).reduce(query);
    assert_eq!(first, second);
    let MarketStateOutcome::Accepted(snapshot) = first else {
        panic!("complete closure must be accepted");
    };
    assert_eq!(snapshot.authority.as_str(), READ_ONLY_AUTHORITY);
    assert_eq!(snapshot.social_product.len(), 1);
    assert_eq!(snapshot.lifecycle.len(), 1);
    assert_eq!(snapshot.pool_state.len(), 1);
    assert_eq!(snapshot.attention.len(), 1);
    assert_eq!(snapshot.input_closure.len(), 4);
    assert!(
        snapshot
            .input_closure
            .iter()
            .all(|input| !input.evidence.observation_ids.is_empty())
    );
    let json = serde_json::to_value(&snapshot).expect("snapshot JSON");
    assert_eq!(json["authority"], READ_ONLY_AUTHORITY);
    assert!(json.get("quote").is_none());
    assert!(json.get("execution").is_none());
    let first_bytes = serde_json_canonicalizer::to_vec(&json).expect("canonical snapshot");
    let second_bytes = serde_json_canonicalizer::to_vec(
        &serde_json::to_value(&snapshot).expect("snapshot JSON again"),
    )
    .expect("canonical snapshot again");
    assert_eq!(first_bytes, second_bytes);
}

#[test]
fn future_context_correction_cannot_enter_old_cut() {
    let fixture = scenarios();
    assert_case(
        &fixture,
        "future_context_correction_old_cut",
        "accepted_old_branch",
    );
    let (mut reader, query) = accepted_inputs(&fixture.cut);
    let old = reader.history["market:attention"].first().unwrap().clone();
    let mut corrected_fact: MarketFactV1 =
        serde_json::from_value(old.value.clone()).expect("old attention fact");
    corrected_fact.available_at = time("2026-08-16T12:10:00.000000Z");
    corrected_fact.available_commit = CommitSeq::new(20);
    if let MarketFactPayload::Attention(attention) = &mut corrected_fact.payload {
        attention.event.available_at = time("2026-08-16T12:10:00.000000Z");
        attention.event.available_commit = CommitSeq::new(20);
        if let Some(identity) = &mut attention.selected_identity {
            identity.display_name = Some(stable("future-corrected-name"));
            identity.knowledge_time.known_from = time("2026-08-16T12:10:00.000000Z");
            identity.knowledge_time.available_commit = CommitSeq::new(20);
        }
    } else {
        unreachable!("fixture attention payload");
    }
    reader.insert(assertion(
        "assertion:attention:future",
        "market:attention",
        20,
        Some("assertion:attention"),
        corrected_fact,
    ));
    let MarketStateOutcome::Accepted(snapshot) = MarketStateReducer::new(&reader).reduce(query)
    else {
        panic!("future correction must be invisible at old cutoff");
    };
    assert_eq!(
        snapshot.attention[0].effective.assertion_id.as_str(),
        "assertion:attention"
    );
    assert_ne!(
        snapshot.attention[0]
            .value
            .selected_identity
            .as_ref()
            .and_then(|identity| identity.display_name.as_ref())
            .map(StableString::as_str),
        Some("future-corrected-name")
    );
}

#[test]
fn capture_attestation_cannot_supply_valid_time() {
    let fixture = scenarios();
    assert_case(
        &fixture,
        "capture_interval_as_validity",
        "capture_attestation_is_not_validity",
    );
    let (mut reader, query) = accepted_inputs(&fixture.cut);
    mutate_fact(&mut reader, "market:social", |fact| {
        fact.validity_basis = ValidityBasis::CaptureAttestationOnly;
        fact.valid_time = None;
        fact.capture_attestation = Some(CaptureAttestation {
            started_at: time("2026-08-16T11:59:59.000000Z"),
            ended_at: time("2026-08-16T12:00:03.000000Z"),
            acquisition_id: AcquisitionId::new("capture:companion:1").unwrap(),
        });
    });
    assert_refusal(
        MarketStateReducer::new(&reader).reduce(query),
        RefusalCode::CaptureAttestationIsNotValidity,
    );
}

#[test]
fn ambiguous_store_branch_refuses_instead_of_choosing() {
    let fixture = scenarios();
    assert_case(
        &fixture,
        "ambiguous_effective_branch",
        "ambiguous_effective_branch",
    );
    let (mut reader, query) = accepted_inputs(&fixture.cut);
    let fact: MarketFactV1 =
        serde_json::from_value(reader.history["market:social"][0].value.clone())
            .expect("social fact");
    reader.insert(assertion(
        "assertion:social:competing",
        "market:social",
        10,
        None,
        fact,
    ));
    assert_refusal(
        MarketStateReducer::new(&reader).reduce(query),
        RefusalCode::AmbiguousEffectiveBranch,
    );
}

#[test]
fn missing_mixed_nonfinal_and_unsupported_pool_closures_refuse() {
    let fixture = scenarios();
    let cases = [
        (
            "pool_missing_fee_account",
            RefusalCode::PoolClosureIncomplete,
            PoolMutation::MissingFee,
        ),
        (
            "pool_mixed_slot",
            RefusalCode::PoolClosureMixedSlot,
            PoolMutation::MixedSlot,
        ),
        (
            "pool_confirmed_not_finalized",
            RefusalCode::PoolClosureNotFinalized,
            PoolMutation::Confirmed,
        ),
        (
            "pool_unsupported_extension",
            RefusalCode::PoolClosureUnsupported,
            PoolMutation::Unsupported,
        ),
    ];
    for (case_name, expected, mutation) in cases {
        assert!(fixture.cases.iter().any(|case| case.name == case_name));
        let (mut reader, query) = accepted_inputs(&fixture.cut);
        mutate_fact(&mut reader, "market:pool", |fact| {
            let MarketFactPayload::PoolState(bundle) = &mut fact.payload else {
                unreachable!("pool payload");
            };
            match mutation {
                PoolMutation::MissingFee => bundle
                    .accounts
                    .retain(|account| account.role != PoolAccountRole::FeeConfiguration),
                PoolMutation::MixedSlot => bundle.accounts[0].slot = WireU64::new(101),
                PoolMutation::Confirmed => {
                    bundle.accounts[0].finality = ChainFinality::Confirmed;
                }
                PoolMutation::Unsupported => bundle.accounts[0]
                    .unsupported_fields
                    .push(stable("new-layout-field")),
            }
        });
        assert_refusal(MarketStateReducer::new(&reader).reduce(query), expected);
    }
}

#[test]
#[cfg(feature = "sqlite-store")]
fn sqlite_store_implements_only_the_narrow_historical_read_seam() {
    fn assert_reader<T: EffectiveFactReader>() {}
    assert_reader::<joshi_store::SqliteStore>();
}

#[test]
#[cfg(feature = "sqlite-store")]
fn accepted_snapshot_builds_exact_v7_market_state_capability() {
    let fixture = scenarios();
    let (reader, query) = accepted_inputs(&fixture.cut);
    let MarketStateOutcome::Accepted(mut snapshot) = MarketStateReducer::new(&reader).reduce(query)
    else {
        panic!("accepted fixture snapshot");
    };
    let capability = snapshot_store_capability(
        &snapshot,
        joshi_store::ArtifactProtectionClass::PublicIntegrity,
    )
    .expect("public market-state capability");
    assert_eq!(capability.artifact_id(), &snapshot.artifact_id);
    assert!(capability.artifact_digest().as_str().starts_with("sha256:"));

    snapshot.input_closure[0].evidence.protection = FactProtection::AuthenticatedPrivate;
    assert!(matches!(
        snapshot_store_capability(
            &snapshot,
            joshi_store::ArtifactProtectionClass::PublicIntegrity,
        ),
        Err(StoreArtifactError::ProtectionMismatch)
    ));
    assert!(
        snapshot_store_capability(
            &snapshot,
            joshi_store::ArtifactProtectionClass::AuthenticatedPrivate,
        )
        .is_ok()
    );
}

#[test]
fn product_lifecycle_hint_cannot_claim_chain_truth() {
    let observation_id = observation("observation:product:migration-hint");
    let source_id = source("source:pump-product");
    let result = adapt_lifecycle_fact(
        LifecycleFactContext {
            subject_id: stable("solana:mint:hinted"),
            valid_time: event_interval(),
            validity_basis: ValidityBasis::FinalizedChainSlot,
            available_at: time("2026-08-16T12:00:02.000000Z"),
            available_commit: CommitSeq::new(10),
            capture_attestation: None,
            chain: Some(ChainPoint {
                slot: WireU64::new(100),
                finality: ChainFinality::Finalized,
            }),
            evidence: evidence(observation_id.clone(), source_id.clone()),
        },
        LifecycleFact::ProductHint {
            mint_id: asset("solana:mint:hinted"),
            hint: ProductLifecycleHint::Migrated,
            observation_id,
            source_id,
            provider_revision: stable("pump-product:revision:1"),
        },
    );
    assert_eq!(
        result,
        Err(LifecycleAdapterError::ProductHintClaimsChainTruth)
    );
}

#[test]
fn attention_adapter_retains_response_coverage_and_censoring_at_its_later_cut() {
    let dataset: AttentionDataset =
        serde_json::from_str(ATTENTION_FIXTURE).expect("valid attention fixture");
    let fact = adapt_attention_event(
        stable("solana:mint:Coin111111111111111111111111111111111111"),
        &dataset,
        &dataset.attention_events[0].attention_event_id,
    )
    .expect("attention response adapter");
    let MarketFactPayload::Attention(attention) = fact.payload else {
        unreachable!("attention payload");
    };
    assert_eq!(attention.response_observations.len(), 2);
    assert!(
        attention
            .response_observations
            .iter()
            .any(|response| matches!(
                response.censoring,
                joshi_attention::ResponseCensoring::SourceLoss { .. }
            ))
    );
    assert_eq!(fact.available_at, time("2026-08-16T13:00:00.000000Z"));
}

#[test]
fn all_three_pool_families_require_complete_closure_before_kernel_use() {
    let fixture = scenarios();
    let (_, query) = accepted_inputs(&fixture.cut);
    let MarketFactPayload::PoolState(pump_curve) =
        pool_fact(query.subject_id.clone(), &query.cut).payload
    else {
        unreachable!("pool fixture");
    };
    assert!(matches!(
        adapt_pool_bundle(&pump_curve),
        Ok(PoolProjection::PumpCurve {
            quote_state_admitted: true,
            ..
        })
    ));
    assert!(matches!(
        adapt_pool_bundle(&pump_swap_bundle(query.cut.finalized_chain_slot)),
        Ok(PoolProjection::PumpSwapCanonical {
            quote_state_admitted: true,
            ..
        })
    ));
    let dlmm = adapt_pool_bundle(&dlmm_bundle(query.cut.finalized_chain_slot));
    assert!(matches!(
        dlmm,
        Ok(PoolProjection::MeteoraDlmmPosition {
            principal: AssetPairV1 {
                x_atoms,
                y_atoms,
            },
            inventory_state_admitted: true,
            ..
        }) if x_atoms.get() == 500 && y_atoms.get() == 1_000
    ));
}

fn accepted_inputs(cut: &MarketStateCut) -> (MemoryReader, MarketStateQuery) {
    let mut dataset: AttentionDataset =
        serde_json::from_str(ATTENTION_FIXTURE).expect("valid attention fixture");
    dataset.validate().expect("attention fixture validation");
    // The event-time branch is created before post-anchor outcomes. A later superseding branch
    // may include the response rows at their own analysis cutoff.
    dataset.response_observations.clear();
    let subject = stable("solana:mint:Coin111111111111111111111111111111111111");
    let social = adapt_social_input(subject.clone(), dataset.exact_inputs[0].clone(), None)
        .expect("social adapter");
    let attention = adapt_attention_event(
        subject.clone(),
        &dataset,
        &dataset.attention_events[0].attention_event_id,
    )
    .expect("attention adapter");
    let lifecycle = lifecycle_fact(subject.clone(), cut);
    let pool = pool_fact(subject.clone(), cut);
    let mut reader = MemoryReader::default();
    reader.insert(assertion(
        "assertion:social",
        "market:social",
        10,
        None,
        social,
    ));
    reader.insert(assertion(
        "assertion:lifecycle",
        "market:lifecycle",
        10,
        None,
        lifecycle,
    ));
    reader.insert(assertion("assertion:pool", "market:pool", 10, None, pool));
    reader.insert(assertion(
        "assertion:attention",
        "market:attention",
        10,
        None,
        attention,
    ));
    (
        reader,
        MarketStateQuery {
            artifact_id: stable("artifact:market-state:fixture:1"),
            subject_id: subject,
            cut: cut.clone(),
            social_product: stream("market:social"),
            lifecycle: stream("market:lifecycle"),
            pool_state: stream("market:pool"),
            attention: stream("market:attention"),
        },
    )
}

fn lifecycle_fact(subject: StableString, cut: &MarketStateCut) -> MarketFactV1 {
    let observation_id = observation("observation:lifecycle:create");
    let source_id = source("source:solana:finalized");
    adapt_lifecycle_fact(
        LifecycleFactContext {
            subject_id: subject,
            valid_time: event_interval(),
            validity_basis: ValidityBasis::FinalizedChainSlot,
            available_at: cut.known_by,
            available_commit: cut.known_by_commit,
            capture_attestation: None,
            chain: Some(ChainPoint {
                slot: cut.finalized_chain_slot,
                finality: ChainFinality::Finalized,
            }),
            evidence: evidence(observation_id.clone(), source_id.clone()),
        },
        LifecycleFact::FinalizedChain {
            mint_id: asset("solana:mint:Coin111111111111111111111111111111111111"),
            event: ChainLifecycleEvent::Created {
                pool_id: pool_id("pump:curve:fixture"),
            },
            observation_id,
            source_id,
        },
    )
    .expect("finalized lifecycle adapter")
}

fn pool_fact(subject: StableString, cut: &MarketStateCut) -> MarketFactV1 {
    let source_id = source("source:solana:account-closure");
    let state_observation = observation("observation:pool:curve");
    let fee_observation = observation("observation:pool:fees");
    let global_observation = observation("observation:pool:global");
    let mint_observation = observation("observation:pool:mint");
    let pool_id = pool_id("pump:curve:fixture");
    let slot = cut.finalized_chain_slot;
    let accounts = vec![
        account(
            PoolAccountRole::Curve,
            "account:curve",
            state_observation.clone(),
            slot,
        ),
        account(
            PoolAccountRole::GlobalConfiguration,
            "account:pump-global",
            global_observation,
            slot,
        ),
        account(
            PoolAccountRole::FeeConfiguration,
            "account:pump-fees",
            fee_observation.clone(),
            slot,
        ),
        account(
            PoolAccountRole::BaseMint,
            "account:base-mint",
            mint_observation,
            slot,
        ),
    ];
    let observation_ids = accounts
        .iter()
        .map(|account| account.observation_id.clone())
        .collect();
    MarketFactV1 {
        contract: stable(MARKET_FACT_CONTRACT),
        stream: MarketStream::PoolState,
        subject_id: subject,
        valid_time: Some(event_interval()),
        validity_basis: ValidityBasis::FinalizedChainSlot,
        available_at: cut.known_by,
        available_commit: cut.known_by_commit,
        capture_attestation: None,
        chain: Some(ChainPoint {
            slot,
            finality: ChainFinality::Finalized,
        }),
        evidence: FactEvidence {
            observation_ids,
            source_ids: vec![source_id],
            coverage_ids: vec![CoverageId::new("coverage:pool:slot-100").unwrap()],
            gap_ids: Vec::new(),
            protection: FactProtection::PublicIntegrity,
        },
        payload: MarketFactPayload::PoolState(Box::new(PoolBundleV1 {
            bundle_id: stable("pool-bundle:slot-100"),
            pool_kind: PoolKind::PumpCurve,
            pool_id: pool_id.clone(),
            slot,
            accounts,
            decoded_state: DecodedPoolStateV1::PumpCurve(PumpCurveWireState {
                profile: ProtocolProfileV1 {
                    id: ProtocolProfileId::new("profile:pump:fixture").unwrap(),
                    venue_id: VenueId::new("pump:bonding-curve").unwrap(),
                    program_identity: stable("program:pump:fixture"),
                    source_revision: stable("source-revision:fixture"),
                },
                pool_id,
                base_asset_id: asset("solana:mint:Coin111111111111111111111111111111111111"),
                quote_asset_id: asset("solana:native:SOL"),
                state_observation_id: state_observation,
                fee_observation_id: fee_observation,
                slot,
                lifecycle: VenueLifecycleV1::Trading,
                virtual_base_reserves: WireU64::new(1_000_000),
                virtual_quote_reserves: WireU64::new(30_000),
                real_base_reserves: WireU64::new(900_000),
                real_quote_reserves: WireU64::new(20_000),
                base_mint_supply: WireU64::new(1_000_000),
                is_mayhem_mode: false,
                fee_policy: FeePolicyV1::Flat(FeeScheduleV1 {
                    lp_basis_points: 20,
                    protocol_basis_points: 5,
                    creator: CreatorFeeV1::NotApplicable,
                }),
            }),
        })),
    }
}

fn pump_swap_bundle(slot: WireU64) -> PoolBundleV1 {
    let state_observation = observation("observation:pumpswap:pool");
    let fee_observation = observation("observation:pumpswap:fee");
    let roles = [
        (
            PoolAccountRole::Pool,
            "account:pumpswap:pool",
            state_observation.clone(),
        ),
        (
            PoolAccountRole::GlobalConfiguration,
            "account:pumpswap:global",
            observation("observation:pumpswap:global"),
        ),
        (
            PoolAccountRole::FeeConfiguration,
            "account:pumpswap:fee",
            fee_observation.clone(),
        ),
        (
            PoolAccountRole::BaseMint,
            "account:pumpswap:base-mint",
            observation("observation:pumpswap:base-mint"),
        ),
        (
            PoolAccountRole::QuoteMint,
            "account:pumpswap:quote-mint",
            observation("observation:pumpswap:quote-mint"),
        ),
        (
            PoolAccountRole::BaseVault,
            "account:pumpswap:base-vault",
            observation("observation:pumpswap:base-vault"),
        ),
        (
            PoolAccountRole::QuoteVault,
            "account:pumpswap:quote-vault",
            observation("observation:pumpswap:quote-vault"),
        ),
    ];
    let pool_id = pool_id("pumpswap:pool:fixture");
    PoolBundleV1 {
        bundle_id: stable("pool-bundle:pumpswap:slot-100"),
        pool_kind: PoolKind::PumpSwapCanonical,
        pool_id: pool_id.clone(),
        slot,
        accounts: roles
            .into_iter()
            .map(|(role, id, observation_id)| account(role, id, observation_id, slot))
            .collect(),
        decoded_state: DecodedPoolStateV1::PumpSwapCanonical(PumpSwapWireState {
            profile: profile("profile:pumpswap:fixture", "pump:pumpswap"),
            pool_id,
            base_asset_id: asset("solana:mint:base"),
            quote_asset_id: asset("solana:mint:quote"),
            state_observation_id: state_observation,
            fee_observation_id: fee_observation,
            slot,
            lifecycle: VenueLifecycleV1::Trading,
            base_reserves: WireU64::new(1_000_000),
            raw_quote_reserves: WireU64::new(50_000),
            virtual_quote_reserves: stable("1000"),
            base_mint_supply: WireU64::new(1_000_000),
            fee_policy: FeePolicyV1::Flat(FeeScheduleV1 {
                lp_basis_points: 20,
                protocol_basis_points: 5,
                creator: CreatorFeeV1::NotApplicable,
            }),
        }),
    }
}

#[allow(clippy::similar_names)] // X/Y account evidence is deliberately symmetric.
fn dlmm_bundle(slot: WireU64) -> PoolBundleV1 {
    let position_observation = observation("observation:dlmm:position");
    let mint_x_observation = observation("observation:dlmm:mint-x");
    let mint_y_observation = observation("observation:dlmm:mint-y");
    let roles = [
        (
            PoolAccountRole::Position,
            "account:dlmm:position",
            position_observation.clone(),
        ),
        (
            PoolAccountRole::LbPair,
            "account:dlmm:pair",
            observation("observation:dlmm:pair"),
        ),
        (
            PoolAccountRole::FeeConfiguration,
            "account:dlmm:fee",
            observation("observation:dlmm:fee"),
        ),
        (
            PoolAccountRole::ReserveX,
            "account:dlmm:reserve-x",
            observation("observation:dlmm:reserve-x"),
        ),
        (
            PoolAccountRole::ReserveY,
            "account:dlmm:reserve-y",
            observation("observation:dlmm:reserve-y"),
        ),
        (
            PoolAccountRole::MintX,
            "account:dlmm:mint-x",
            mint_x_observation.clone(),
        ),
        (
            PoolAccountRole::MintY,
            "account:dlmm:mint-y",
            mint_y_observation.clone(),
        ),
        (
            PoolAccountRole::BinArray,
            "account:dlmm:bin-array",
            observation("observation:dlmm:bin-array"),
        ),
    ];
    let pool_id = pool_id("dlmm:pool:fixture");
    PoolBundleV1 {
        bundle_id: stable("pool-bundle:dlmm:slot-100"),
        pool_kind: PoolKind::MeteoraDlmmPosition,
        pool_id: pool_id.clone(),
        slot,
        accounts: roles
            .into_iter()
            .map(|(role, id, observation_id)| account(role, id, observation_id, slot))
            .collect(),
        decoded_state: DecodedPoolStateV1::MeteoraDlmmPosition(DlmmPositionWireState {
            profile: profile("profile:dlmm:fixture", "meteora:dlmm"),
            pool_id,
            position_id: PositionId::new("position:dlmm:fixture").unwrap(),
            observation_id: position_observation,
            slot,
            version: DlmmPositionVersionV1::V2,
            lifecycle: DlmmPositionLifecycleV1::Open,
            token_x: token_definition("solana:mint:x", mint_x_observation),
            token_y: token_definition("solana:mint:y", mint_y_observation),
            lower_bin_id: 0,
            upper_bin_id: 0,
            active_bin_id: 0,
            bin_step_basis_points: 25,
            bins: vec![DlmmBinV1 {
                bin_id: 0,
                price_q64: WireU128::new(1_u128 << 64),
                pool_amounts: AssetPairV1 {
                    x_atoms: WireU64::new(1_000),
                    y_atoms: WireU64::new(2_000),
                },
                liquidity_supply: WireU128::new(100),
                position_share: WireU128::new(50),
                accrual: DlmmAccrualV1::Observed {
                    fees: AssetPairV1 {
                        x_atoms: WireU64::new(2),
                        y_atoms: WireU64::new(3),
                    },
                    rewards: Vec::new(),
                },
            }],
            unsupported_fields: Vec::new(),
        }),
    }
}

fn profile(id: &str, venue: &str) -> ProtocolProfileV1 {
    ProtocolProfileV1 {
        id: ProtocolProfileId::new(id).unwrap(),
        venue_id: VenueId::new(venue).unwrap(),
        program_identity: stable("program:fixture"),
        source_revision: stable("source-revision:fixture"),
    }
}

fn token_definition(asset_id: &str, observation_id: ObservationId) -> TokenDefinitionV1 {
    TokenDefinitionV1 {
        asset_id: asset(asset_id),
        decimals: 6,
        token_program: stable("spl-token:v1"),
        observation_id,
        decoded_extensions: Vec::new(),
        unsupported_extensions: Vec::new(),
    }
}

fn account(
    role: PoolAccountRole,
    account_id: &str,
    observation_id: ObservationId,
    slot: WireU64,
) -> PoolAccountObservation {
    PoolAccountObservation {
        role,
        account_id: AccountId::new(account_id).unwrap(),
        observation_id,
        slot,
        finality: ChainFinality::Finalized,
        data_digest: digest('a'),
        decoder_profile: stable("decoder:pump:fixture:v1"),
        unsupported_fields: Vec::new(),
    }
}

fn evidence(observation_id: ObservationId, source_id: SourceId) -> FactEvidence {
    FactEvidence {
        observation_ids: vec![observation_id],
        source_ids: vec![source_id],
        coverage_ids: vec![CoverageId::new("coverage:fixture").unwrap()],
        gap_ids: Vec::new(),
        protection: FactProtection::PublicIntegrity,
    }
}

fn assertion(
    assertion_id: &str,
    semantic_key: &str,
    commit: u64,
    supersedes: Option<&str>,
    fact: MarketFactV1,
) -> EffectiveFactRecord {
    EffectiveFactRecord {
        assertion_id: AssertionId::new(assertion_id).unwrap(),
        semantic_key: stable(semantic_key),
        produced_commit: CommitSeq::new(commit),
        value: serde_json::to_value(fact).expect("market fact JSON"),
        value_digest: digest('d'),
        supersedes_assertion_id: supersedes.map(|value| AssertionId::new(value).unwrap()),
    }
}

fn mutate_fact(reader: &mut MemoryReader, key: &str, mutation: impl FnOnce(&mut MarketFactV1)) {
    let assertion = reader.history.get_mut(key).unwrap().first_mut().unwrap();
    let mut fact: MarketFactV1 =
        serde_json::from_value(assertion.value.clone()).expect("market fact");
    mutation(&mut fact);
    assertion.value = serde_json::to_value(fact).expect("mutated market fact");
}

fn scenarios() -> ScenarioFixture {
    let fixture: ScenarioFixture =
        serde_json::from_str(SCENARIO_FIXTURE).expect("strict scenario fixture");
    assert_eq!(
        fixture.contract,
        "joshi.market-state.adversarial-fixture.v1"
    );
    let names: BTreeSet<_> = fixture
        .cases
        .iter()
        .map(|case| case.name.as_str())
        .collect();
    assert_eq!(names.len(), fixture.cases.len());
    fixture
}

fn assert_case(fixture: &ScenarioFixture, name: &str, expected: &str) {
    assert_eq!(
        fixture
            .cases
            .iter()
            .find(|case| case.name == name)
            .map(|case| case.expected.as_str()),
        Some(expected)
    );
}

fn assert_refusal(outcome: MarketStateOutcome, expected: RefusalCode) {
    let MarketStateOutcome::Refused(refusal) = outcome else {
        panic!("expected reducer refusal");
    };
    assert_eq!(refusal.code, expected);
    assert_eq!(refusal.authority.as_str(), READ_ONLY_AUTHORITY);
}

fn stream(key: &str) -> StreamQuery {
    StreamQuery {
        enabled: true,
        semantic_keys: vec![stable(key)],
    }
}

fn event_interval() -> ValidInterval {
    ValidInterval {
        lower: time("2026-08-16T12:00:00.000000Z"),
        upper: Some(time("2026-08-16T12:00:01.000000Z")),
    }
}

fn digest(character: char) -> ValueDigest {
    ValueDigest::new(format!("sha256:{}", character.to_string().repeat(64))).unwrap()
}

fn stable(value: &str) -> StableString {
    StableString::new(value).unwrap()
}

fn time(value: &str) -> UtcTimestamp {
    value.parse().unwrap()
}

fn observation(value: &str) -> ObservationId {
    ObservationId::new(value).unwrap()
}

fn source(value: &str) -> SourceId {
    SourceId::new(value).unwrap()
}

fn asset(value: &str) -> AssetId {
    AssetId::new(value).unwrap()
}

fn pool_id(value: &str) -> PoolId {
    PoolId::new(value).unwrap()
}

#[derive(Clone, Copy)]
enum PoolMutation {
    MissingFee,
    MixedSlot,
    Confirmed,
    Unsupported,
}
