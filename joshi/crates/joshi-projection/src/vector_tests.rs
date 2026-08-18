use std::collections::BTreeMap;

use joshi_accounting::{
    accounting::{AccountingState, CashEpoch, CashMovement, Classification},
    amount::AtomQty,
    basis::{Basis, BasisQuality, ExactRatio},
    effect::FinalizedWalletEffect,
    episode::EpisodeBook,
    lots::{BasisEpochRef, Lot, LotAllocation},
    model::{BalanceWire, WalletSnapshot},
};
use joshi_domain::{
    AsOfVector, ChainAsOf, CommitSeq, EpisodeId, LotId, ObservationId, OpenVariant, PoolId,
    PositionId, ProtocolProfileId, QuoteId, StableString, UtcTimestamp, ValueDigest, VenueId,
    WalletEffectId, WireU64,
};
use joshi_liquidity::{
    action::{
        AddLiquidityIntent, BinDeposit, BinRemoval, PositionIntentIdentity, RebalanceInPlaceIntent,
        RemoveBps, RemoveLiquidityIntent, SwapRequirement, project_add, project_rebalance_budget,
        project_remove,
    },
    position::{
        AccrualState, AssetPairAmounts, DlmmPositionState, ObservedAssetDefinition,
        PositionBinState, PositionLifecycle, PositionVersion,
    },
    q64::{BinId, BinStep, Q64x64},
};
use joshi_market_math::{
    fee::{CreatorFee, FeeBps, FeePolicy, FeeSchedule},
    profile::{ProtocolFamily, ProtocolProfile, VenueLifecycle},
    pump::PumpCurveState,
    quote::{ExecutableLiquidation, QuoteRequest, QuoteSize},
};
use serde::Deserialize;

use super::*;

const ADVERSARIAL: &str = include_str!("../../../fixtures/projection/adversarial.json");

fn stable(value: &str) -> StableString {
    StableString::new(value).expect("test stable string")
}

fn observation(value: &str) -> ObservationId {
    ObservationId::new(value).expect("test observation ID")
}

fn timestamp(value: &str) -> UtcTimestamp {
    value.parse().expect("test timestamp")
}

fn freshness() -> Freshness {
    Freshness::Fresh {
        state_received_at: timestamp("2026-08-16T12:00:00.000000Z"),
        evaluated_at: timestamp("2026-08-16T12:00:01.000000Z"),
        expires_at: timestamp("2026-08-16T12:00:03.000000Z"),
        monotonic: MonotonicValidityWindow {
            clock_id: stable("clock-fixture"),
            observed_mono_ns: WireU64::new(1_000),
            expires_mono_ns: WireU64::new(4_000),
        },
        evaluated_slot: WireU64::new(100),
        valid_through_slot: WireU64::new(102),
        coverage: ValidityCoverage::Complete,
    }
}

fn stale_freshness() -> Freshness {
    Freshness::Stale {
        state_received_at: timestamp("2026-08-16T12:00:00.000000Z"),
        evaluated_at: timestamp("2026-08-16T12:00:04.000000Z"),
        expires_at: timestamp("2026-08-16T12:00:03.000000Z"),
        monotonic: MonotonicValidityWindow {
            clock_id: stable("clock-fixture"),
            observed_mono_ns: WireU64::new(1_000),
            expires_mono_ns: WireU64::new(4_000),
        },
        evaluated_slot: WireU64::new(103),
        valid_through_slot: WireU64::new(102),
        coverage: ValidityCoverage::Complete,
        reason: stable("quote_window_expired"),
    }
}

fn definition(asset: &str, observation_id: &str, decimals: u8) -> AssetDefinitionDto {
    AssetDefinitionDto {
        asset_id: joshi_domain::AssetId::new(asset).expect("test asset ID"),
        mint: stable(&format!("mint-{asset}")),
        token_program: stable("spl-token-v1"),
        decimals,
        definition_observation_id: observation(observation_id),
    }
}

fn snapshot(sol: u64, token: u64) -> WalletSnapshot {
    WalletSnapshot::from_wire(&[
        BalanceWire {
            account: "wallet-sol".into(),
            asset: "sol".into(),
            atoms: WireU64::new(sol),
        },
        BalanceWire {
            account: "wallet-token".into(),
            asset: "token".into(),
            atoms: WireU64::new(token),
        },
    ])
    .expect("test snapshot")
}

#[allow(clippy::too_many_lines)] // This is one hand-auditable accounting state-machine vector.
fn accounting_input(definitions: &[AssetDefinitionDto]) -> AccountingProjectionInput {
    let sol = joshi_domain::AssetId::new("sol").expect("sol ID");
    let token = joshi_domain::AssetId::new("token").expect("token ID");
    let episode_id = EpisodeId::new("episode-runner").expect("episode ID");
    let lot_id = LotId::new("lot-runner").expect("lot ID");
    let before = snapshot(1_000, 0);
    let after_buy = snapshot(899, 1_000);
    let after_sell = snapshot(1_018, 400);
    let buy_id = WalletEffectId::new("effect-buy").expect("effect ID");
    let sell_id = WalletEffectId::new("effect-sell-partial").expect("effect ID");
    let buy =
        FinalizedWalletEffect::between(buy_id.clone(), &before, &after_buy).expect("buy effect");
    let sell = FinalizedWalletEffect::between(sell_id.clone(), &after_buy, &after_sell)
        .expect("sell effect");
    let epoch = CashEpoch {
        episode: episode_id.clone(),
        index: 1,
        asset: sol.clone(),
    };
    let mut state = AccountingState::from_snapshot(&before).expect("state");
    state.apply_effect(buy.clone()).expect("apply buy");
    let acquisition = state
        .classify(
            &buy_id,
            Classification::Acquisition {
                asset: token.clone(),
                quantity: AtomQty::new(1_000),
                lot: lot_id.clone(),
                basis: Basis::known(sol.clone(), AtomQty::new(101)),
                epoch: Some(BasisEpochRef {
                    episode: episode_id.clone(),
                    index: 1,
                }),
                cash_spend: Some(CashMovement {
                    epoch: epoch.clone(),
                    amount: AtomQty::new(101),
                }),
            },
        )
        .expect("classify buy");
    state.apply_effect(sell.clone()).expect("apply sell");
    let disposal = state
        .classify(
            &sell_id,
            Classification::Disposal {
                asset: token.clone(),
                quantity: AtomQty::new(600),
                allocations: vec![LotAllocation {
                    lot: lot_id.clone(),
                    quantity: AtomQty::new(600),
                }],
                net_proceeds: BTreeMap::from([(sol.clone(), AtomQty::new(119))]),
                cash_return: Some(CashMovement {
                    epoch: epoch.clone(),
                    amount: AtomQty::new(119),
                }),
            },
        )
        .expect("classify sell");
    let remaining_lot = state.lots.get(&lot_id).expect("remaining lot").clone();
    let recovery = state.capital_recovery(&epoch).expect("recovery");
    let realized = RealizedInput::from_classification(
        sell_id.clone(),
        Some(episode_id.clone()),
        Some(1),
        &disposal,
    )
    .expect("disposal components");
    let mut episodes = EpisodeBook::default();
    episodes.begin(episode_id.clone()).expect("begin episode");
    let episode = episodes.get_mut(&episode_id).expect("episode");
    episode
        .observe_inventory(buy_id.clone(), AtomQty::new(1_000))
        .expect("episode buy");
    episode
        .observe_inventory(sell_id.clone(), AtomQty::new(400))
        .expect("episode partial sell");
    let remaining_basis = remaining_lot
        .remaining_basis
        .component(&sol)
        .expect("remaining SOL basis")
        .clone();
    AccountingProjectionInput {
        asset_definitions: definitions.to_vec(),
        finalized_snapshot: after_sell,
        snapshot_evidence: vec![observation("obs-snapshot-final")],
        inventory_asset_ids: vec![token.clone()],
        effects: vec![
            EvidencedWalletEffect {
                effect: buy,
                evidence: vec![observation("obs-effect-buy")],
                landed_commit: CommitSeq::new(10),
                classification: acquisition,
            },
            EvidencedWalletEffect {
                effect: sell,
                evidence: vec![observation("obs-effect-sell")],
                landed_commit: CommitSeq::new(11),
                classification: disposal,
            },
        ],
        lots: vec![remaining_lot],
        realized: vec![realized],
        episodes: vec![EvidencedEpisode {
            asset_id: token.clone(),
            projection: episodes.get(&episode_id).expect("episode output").clone(),
        }],
        capital_recovery: vec![CapitalRecoveryInput {
            epoch,
            status: recovery,
        }],
        unrealized: vec![UnrealizedInput {
            asset_id: token,
            reference_asset_id: sol,
            liquidation_quote_id: QuoteId::new("quote-full-runner").expect("quote ID"),
            basis_quality: BasisQuality::Known,
            liquidation_proceeds: ExactRatio::from_u64(38),
            remaining_known_basis: remaining_basis,
        }],
    }
}

fn market_projection(definitions: &[AssetDefinitionDto]) -> MarketProjectionDto {
    let profile = ProtocolProfile {
        id: ProtocolProfileId::new("pump-profile-v1").expect("profile ID"),
        venue: VenueId::new("pump").expect("venue ID"),
        family: ProtocolFamily::PumpCurve,
        program_identity: stable("pump-program-mainnet"),
        source_revision: stable("pump-fixture-revision"),
    };
    let state = PumpCurveState {
        profile: profile.clone(),
        pool_id: PoolId::new("pump-pool-token").expect("pool ID"),
        base_asset_id: joshi_domain::AssetId::new("token").expect("token ID"),
        quote_asset_id: joshi_domain::AssetId::new("sol").expect("sol ID"),
        state_observation_id: observation("obs-pump-state"),
        fee_observation_id: observation("obs-pump-fee"),
        slot: WireU64::new(100),
        lifecycle: VenueLifecycle::Trading,
        virtual_base_reserves: AtomQty::new(10_000),
        virtual_quote_reserves: AtomQty::new(1_000),
        real_base_reserves: AtomQty::new(5_000),
        real_quote_reserves: AtomQty::new(10_000),
        base_mint_supply: AtomQty::new(1_000_000),
        is_mayhem_mode: false,
        fee_policy: FeePolicy::Flat(FeeSchedule {
            lp: FeeBps::new(0).expect("zero fee"),
            protocol: FeeBps::new(0).expect("zero fee"),
            creator: CreatorFee::NotApplicable,
        }),
    };
    let request = QuoteRequest {
        quote_id: QuoteId::new("quote-full-runner").expect("quote ID"),
        intent_command_id: None,
        intended_state_observation: Some(observation("obs-pump-state")),
        expected_profile_id: profile.id.clone(),
        venue_id: profile.venue.clone(),
        pool_id: state.pool_id.clone(),
        base_asset_id: state.base_asset_id.clone(),
        quote_asset_id: state.quote_asset_id.clone(),
        size: QuoteSize::ExactBaseInSell(AtomQty::new(400)),
    };
    let calculation = state.calculate(&request);
    let quote = calculation
        .clone()
        .into_result()
        .expect("full runner quote");
    assert_eq!(quote.output.atoms.get(), 38);
    let liquidation = ExecutableLiquidation::from_full_position_quote(quote, AtomQty::new(400))
        .expect("full position promotion");
    project_market(
        definitions,
        &[FreshMark {
            mark_id: stable("mark-token"),
            mark: state.mark().expect("mark"),
            freshness: freshness(),
        }],
        &[FreshQuote {
            calculation,
            base_asset_id: request.base_asset_id,
            quote_asset_id: request.quote_asset_id,
            route_id: stable("route-pump-curve"),
            route_observation_ids: vec![observation("obs-route")],
            freshness: freshness(),
        }],
        &[FreshLiquidation {
            full_position_quote_id: stable("full-position-runner"),
            route_id: stable("route-pump-curve"),
            route_observation_ids: vec![observation("obs-route")],
            liquidation,
            freshness: freshness(),
        }],
    )
    .expect("market projection")
}

fn liquidity_state(definitions: &[AssetDefinitionDto]) -> DlmmPositionState {
    let profile = ProtocolProfile {
        id: ProtocolProfileId::new("meteora-profile-v1").expect("profile ID"),
        venue: VenueId::new("meteora-dlmm").expect("venue ID"),
        family: ProtocolFamily::MeteoraDlmm,
        program_identity: stable("meteora-dlmm-mainnet"),
        source_revision: stable("meteora-fixture-revision"),
    };
    let token = definitions
        .iter()
        .find(|value| value.asset_id.as_str() == "token")
        .expect("token definition");
    let sol = definitions
        .iter()
        .find(|value| value.asset_id.as_str() == "sol")
        .expect("SOL definition");
    DlmmPositionState {
        profile: profile.clone(),
        venue_id: profile.venue.clone(),
        pool_id: PoolId::new("dlmm-pool-token-sol").expect("pool ID"),
        position_id: PositionId::new("position-runner").expect("position ID"),
        observation_id: observation("obs-lp-state"),
        slot: WireU64::new(100),
        version: PositionVersion::V2,
        lifecycle: PositionLifecycle::Open,
        token_x: ObservedAssetDefinition {
            asset_id: token.asset_id.clone(),
            decimals: token.decimals,
            token_program: token.token_program.clone(),
            observation_id: token.definition_observation_id.clone(),
        },
        token_y: ObservedAssetDefinition {
            asset_id: sol.asset_id.clone(),
            decimals: sol.decimals,
            token_program: sol.token_program.clone(),
            observation_id: sol.definition_observation_id.clone(),
        },
        lower_bin_id: BinId::new(0),
        upper_bin_id: BinId::new(0),
        active_bin_id: BinId::new(0),
        bin_step: BinStep::new(25).expect("bin step"),
        bins: vec![PositionBinState {
            bin_id: BinId::new(0),
            price_q64: Q64x64::ONE,
            pool_amounts: AssetPairAmounts {
                x: AtomQty::new(1_000),
                y: AtomQty::new(2_000),
            },
            liquidity_supply: 1_000,
            position_share: 100,
            accrual: AccrualState::ObservedPending {
                fees: AssetPairAmounts {
                    x: AtomQty::new(1),
                    y: AtomQty::new(2),
                },
                rewards: Vec::new(),
            },
        }],
        unsupported_fields: Vec::new(),
    }
}

fn liquidity_actions(state: &DlmmPositionState) -> Vec<LiquidityActionProjectionInput> {
    let identity = PositionIntentIdentity {
        position_id: state.position_id.clone(),
        state_observation_id: state.observation_id.clone(),
        profile_id: state.profile.id.clone(),
    };
    let add = project_add(
        state,
        &AddLiquidityIntent {
            identity: identity.clone(),
            deposits: vec![BinDeposit {
                bin_id: BinId::new(0),
                amounts: AssetPairAmounts {
                    x: AtomQty::new(10),
                    y: AtomQty::new(20),
                },
            }],
        },
    );
    let rebalance = project_rebalance_budget(
        state,
        &RebalanceInPlaceIntent {
            identity: identity.clone(),
            target_deposits: vec![BinDeposit {
                bin_id: BinId::new(0),
                amounts: AssetPairAmounts {
                    x: AtomQty::new(100),
                    y: AtomQty::new(200),
                },
            }],
            top_up_limits: AssetPairAmounts::default(),
            minimum_withdrawals: AssetPairAmounts::default(),
            swap_requirement: SwapRequirement::Forbidden,
        },
    );
    let remove = project_remove(
        state,
        &RemoveLiquidityIntent {
            identity,
            removals: vec![BinRemoval {
                bin_id: BinId::new(0),
                bps: RemoveBps::new(5_000).expect("removal bps"),
            }],
            claim_fees: true,
            claim_rewards: true,
            close_position_account: false,
        },
    );
    vec![
        LiquidityActionProjectionInput::Add {
            action_id: stable("action-add"),
            result: add,
        },
        LiquidityActionProjectionInput::RebalanceInPlace {
            action_id: stable("action-rebalance-in-place"),
            result: rebalance,
        },
        LiquidityActionProjectionInput::Remove {
            action_id: stable("action-remove"),
            result: remove,
        },
    ]
}

fn liquidity_projection(definitions: &[AssetDefinitionDto]) -> LiquidityProjectionDto {
    let state = liquidity_state(definitions);
    let actions = liquidity_actions(&state);
    project_liquidity(
        definitions,
        &[FreshPosition {
            state,
            freshness: freshness(),
            actions,
        }],
    )
    .expect("liquidity projection")
}

fn draft() -> ProjectionDraft {
    let definitions = vec![
        definition("sol", "obs-asset-sol", 9),
        definition("token", "obs-asset-token", 6),
    ];
    let accounting =
        project_accounting(&accounting_input(&definitions)).expect("accounting projection");
    let market = market_projection(&definitions);
    let liquidity = liquidity_projection(&definitions);
    let mut observation_ids = vec![
        observation("obs-asset-sol"),
        observation("obs-asset-token"),
        observation("obs-effect-buy"),
        observation("obs-effect-sell"),
        observation("obs-lp-state"),
        observation("obs-pump-fee"),
        observation("obs-pump-state"),
        observation("obs-route"),
        observation("obs-snapshot-final"),
    ];
    observation_ids.sort();
    ProjectionDraft {
        projection_id: stable("projection-fixture-001"),
        supersedes_projection_id: None,
        calculator_build: stable("joshi-projection-test-build"),
        request_digest: ValueDigest::new(format!("sha256:{}", "1".repeat(64)))
            .expect("request digest"),
        input: ProjectionInputClosure {
            from_commit_seq: CommitSeq::new(1),
            through_commit_seq: CommitSeq::new(20),
            as_of: AsOfVector {
                catalog_commit: CommitSeq::new(20),
                sources: BTreeMap::new(),
                chain: Some(ChainAsOf {
                    cluster: stable("solana-mainnet-beta"),
                    slot: WireU64::new(100),
                    finality: OpenVariant::known("finalized").expect("finality"),
                }),
                projections: BTreeMap::from([(
                    stable(PROJECTION_CONTRACT),
                    stable(PROJECTION_VERSION),
                )]),
                rendered_at: timestamp("2026-08-16T12:00:02.000000Z"),
            },
            controlled_domain_id: stable("wallet-domain-fixture"),
            effective_assertions: Vec::new(),
            observation_ids,
        },
        coverage: vec![
            ProjectionCoverage {
                scope: stable("accounting"),
                status: CoverageStatus::Complete,
                gap_ids: Vec::new(),
            },
            ProjectionCoverage {
                scope: stable("liquidity"),
                status: CoverageStatus::Complete,
                gap_ids: Vec::new(),
            },
            ProjectionCoverage {
                scope: stable("market"),
                status: CoverageStatus::Complete,
                gap_ids: Vec::new(),
            },
        ],
        accounting,
        market,
        liquidity,
    }
}

#[test]
fn full_artifact_is_deterministic_and_exact() {
    let first = build_projection(draft()).expect("projection");
    let second = build_projection(draft()).expect("projection replay");
    assert_eq!(first, second);
    let bytes = projection_bytes(&first).expect("projection bytes");
    assert_eq!(bytes, projection_bytes(&second).expect("replay bytes"));
    assert_eq!(
        first.result_digest.as_str(),
        "sha256:015d40249861b17779ba782e0477bd28b3cadb383ecc6fafe708b0c5c6d72616"
    );
    assert_eq!(bytes.len(), 27_146);
    assert_eq!(first.watermark().state_digest, first.result_digest);
    assert!(
        first
            .accounting
            .inventory
            .iter()
            .all(|value| matches!(value.runner, RunnerStateDto::Retained { .. }))
    );
    assert!(
        first.liquidity.positions[0]
            .actions
            .iter()
            .any(|action| matches!(
                &action.outcome,
                LiquidityActionOutcomeDto::Modeled { projection }
                    if matches!(projection.as_ref(), LiquidityActionSuccessDto::RebalanceInPlace { .. })
            ))
    );
}

#[test]
fn full_and_incremental_paths_emit_identical_target_bytes() {
    let mut prior_draft = draft();
    prior_draft.projection_id = stable("projection-fixture-000");
    prior_draft.input.through_commit_seq = CommitSeq::new(19);
    prior_draft.input.as_of.catalog_commit = CommitSeq::new(19);
    let prior = build_projection(prior_draft).expect("prior projection");

    let mut target_draft = draft();
    target_draft.supersedes_projection_id = Some(prior.projection_id.clone());
    let full = build_projection(target_draft.clone()).expect("full target projection");
    let incremental =
        build_projection_incremental(&prior, target_draft).expect("incremental target projection");

    assert_eq!(full, incremental);
    assert_eq!(
        projection_bytes(&full).expect("full bytes"),
        projection_bytes(&incremental).expect("incremental bytes")
    );
}

#[test]
fn stale_quote_cannot_support_known_unrealized_result() {
    let mut value = draft();
    value.market.full_position_quotes[0].freshness = stale_freshness();
    assert!(matches!(
        build_projection(value),
        Err(ProjectionError::UnrealizedFromNonFreshQuote)
    ));
}

#[test]
fn assertion_conflict_and_partial_coverage_remain_visible() {
    let mut value = draft();
    let first = EffectiveAssertionRef {
        assertion_id: joshi_domain::AssertionId::new("assertion-a").expect("assertion ID"),
        semantic_key: stable("wallet:effect:classification"),
        produced_commit_seq: CommitSeq::new(12),
        value_digest: ValueDigest::new(format!("sha256:{}", "2".repeat(64))).expect("value digest"),
        supersedes_assertion_id: None,
    };
    let mut second = first.clone();
    second.assertion_id = joshi_domain::AssertionId::new("assertion-b").expect("assertion ID");
    second.value_digest =
        ValueDigest::new(format!("sha256:{}", "3".repeat(64))).expect("value digest");
    value.input.effective_assertions = vec![first, second];
    assert!(matches!(
        build_projection(value.clone()),
        Err(ProjectionError::UnacknowledgedAssertionConflict)
    ));
    value.coverage[0].status = CoverageStatus::Conflicting {
        reason: stable("two_effective_classification_branches"),
    };
    let artifact = build_projection(value).expect("visible conflict");
    assert!(
        artifact
            .residuals
            .iter()
            .any(|residual| { matches!(residual.state, ResidualStateDto::Conflicting { .. }) })
    );

    let mut partial = draft();
    partial.coverage[2].status = CoverageStatus::Partial {
        reason: stable("route_account_extension_unobserved"),
    };
    let artifact = build_projection(partial).expect("partial projection");
    assert!(
        artifact
            .residuals
            .iter()
            .any(|residual| { matches!(residual.state, ResidualStateDto::Partial { .. }) })
    );
}

#[test]
fn external_unknown_basis_and_flat_reentry_are_not_collapsed() {
    let token = joshi_domain::AssetId::new("token").expect("token ID");
    let lot = Lot::external_unknown(
        LotId::new("lot-external").expect("lot ID"),
        token.clone(),
        AtomQty::new(7),
    )
    .expect("external lot");
    assert_eq!(lot.remaining_basis.quality, BasisQuality::Unknown);
    assert!(!lot.remaining_basis.is_exact_zero());

    let episode_id = EpisodeId::new("episode-reentry").expect("episode ID");
    let mut episodes = EpisodeBook::default();
    episodes.begin(episode_id.clone()).expect("begin episode");
    let episode = episodes.get_mut(&episode_id).expect("episode");
    episode
        .observe_inventory(
            WalletEffectId::new("buy-one").expect("effect ID"),
            AtomQty::new(10),
        )
        .expect("first buy");
    episode
        .observe_inventory(
            WalletEffectId::new("sell-flat").expect("effect ID"),
            AtomQty::ZERO,
        )
        .expect("flat");
    episode.continue_watching_flat().expect("watching flat");
    episode
        .observe_inventory(
            WalletEffectId::new("buy-reentry").expect("effect ID"),
            AtomQty::new(3),
        )
        .expect("reentry");
    assert_eq!(episode.epochs.len(), 2);
    assert_eq!(episode.current_epoch_index(), Some(2));

    let definitions = vec![
        definition("sol", "obs-asset-sol", 9),
        definition("token", "obs-asset-token", 6),
    ];
    let before = snapshot(1_000, 0);
    let after = snapshot(1_000, 7);
    let effect_id = WalletEffectId::new("effect-external-inflow").expect("effect ID");
    let effect = FinalizedWalletEffect::between(effect_id.clone(), &before, &after)
        .expect("external effect");
    let external_lot_id = LotId::new("lot-external-projected").expect("lot ID");
    let mut state = AccountingState::from_snapshot(&before).expect("state");
    state.apply_effect(effect.clone()).expect("apply external");
    let classification = state
        .classify(
            &effect_id,
            Classification::ExternalInflowUnknown {
                asset: token.clone(),
                quantity: AtomQty::new(7),
                lot: external_lot_id.clone(),
            },
        )
        .expect("classify external");
    let projected = project_accounting(&AccountingProjectionInput {
        asset_definitions: definitions,
        finalized_snapshot: after,
        snapshot_evidence: vec![observation("obs-external-final")],
        inventory_asset_ids: vec![token],
        effects: vec![EvidencedWalletEffect {
            effect,
            evidence: vec![observation("obs-external-effect")],
            landed_commit: CommitSeq::new(30),
            classification,
        }],
        lots: vec![
            state
                .lots
                .get(&external_lot_id)
                .expect("external projected lot")
                .clone(),
        ],
        realized: Vec::new(),
        episodes: Vec::new(),
        capital_recovery: Vec::new(),
        unrealized: Vec::new(),
    })
    .expect("external projection");
    assert_eq!(
        projected.lots[0].remaining_basis.quality,
        BasisQualityDto::Unknown
    );
    assert!(matches!(
        projected.landed_effects[0].classification,
        EffectClassificationDto::ExternalInflowUnknown
    ));

    let mut unclassified = draft();
    unclassified.accounting.landed_effects[1].classification =
        EffectClassificationDto::Unclassified;
    let unclassified = build_projection(unclassified).expect("unclassified remains visible");
    assert!(unclassified.residuals.iter().any(|residual| {
        residual.category.as_str() == "unclassified_landed_effect"
            && matches!(residual.state, ResidualStateDto::Unknown { .. })
    }));
}

#[derive(Deserialize)]
struct AdversarialFixture {
    contract: String,
    cases: Vec<AdversarialCase>,
}

#[derive(Deserialize)]
struct AdversarialCase {
    name: String,
    expected: String,
}

#[test]
fn language_neutral_adversarial_manifest_is_closed_and_canonical() {
    let fixture: AdversarialFixture = serde_json::from_str(ADVERSARIAL).expect("fixture JSON");
    assert_eq!(fixture.contract, "joshi.projection.adversarial.v1");
    assert_eq!(fixture.cases.len(), 6);
    assert!(
        fixture
            .cases
            .iter()
            .all(|case| !case.name.is_empty() && !case.expected.is_empty())
    );
    let value: serde_json::Value = serde_json::from_str(ADVERSARIAL).expect("fixture value");
    let canonical = serde_json_canonicalizer::to_vec(&value).expect("canonical fixture");
    let reparsed: serde_json::Value = serde_json::from_slice(&canonical).expect("canonical JSON");
    assert_eq!(value, reparsed);
}
