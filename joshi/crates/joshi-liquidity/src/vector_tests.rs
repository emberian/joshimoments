use joshi_accounting::amount::AtomQty;
use joshi_domain::{
    AssetId, ObservationId, PoolId, PositionId, ProtocolProfileId, StableString, VenueId, WireU64,
};
use joshi_market_math::profile::{ProtocolFamily, ProtocolProfile};
use proptest::prelude::*;
use serde::Deserialize;

use crate::{
    action::{
        AddLiquidityIntent, BinDeposit, BinRemoval, PositionIntentIdentity, RemoveBps,
        RemoveLiquidityIntent, project_add, project_remove,
    },
    dlmm_fee::{
        DynamicFeeParameters, fee_from_gross_amount, fee_from_net_amount, protocol_fee_amount,
        total_fee_rate,
    },
    position::{
        AccrualState, AssetPairAmounts, DlmmPositionState, ObservedAssetDefinition,
        PositionBinState, PositionLifecycle, PositionVersion, RewardAmount, inventory_for_share,
    },
    q64::{BinId, BinStep, Q64x64, price_from_bin_id},
};

const FIXTURE: &str = include_str!("../../../fixtures/protocol/dlmm.json");

#[test]
fn fixture_is_canonicalizable_and_contains_no_json_numbers() {
    let value: serde_json::Value = serde_json::from_str(FIXTURE).unwrap();
    assert_no_json_numbers(&value);
    let first = serde_json_canonicalizer::to_vec(&value).unwrap();
    let reparsed: serde_json::Value = serde_json::from_slice(&first).unwrap();
    assert_eq!(first, serde_json_canonicalizer::to_vec(&reparsed).unwrap());
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Fixture {
    contract: String,
    official_source: OfficialSource,
    chain_price_vectors: Vec<ChainPriceVector>,
    position_vectors: Vec<PositionVector>,
    fee_vectors: Vec<FeeVector>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct OfficialSource {
    repository: String,
    revision: String,
    package: String,
    program: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ChainPriceVector {
    id: String,
    provenance: String,
    rpc_commitment: String,
    pool: String,
    pool_observation_slot: String,
    active_bin_id: String,
    bin_step: String,
    bin_array: String,
    bin_array_observation_slot: String,
    bin_array_index: String,
    bin_array_version: String,
    amount_x: String,
    amount_y: String,
    stored_price_q64: String,
    liquidity_supply: String,
    expected_price_q64: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PositionVector {
    id: String,
    provenance: String,
    bin_id: String,
    bin_step: String,
    price_q64: String,
    pool_x_atoms: String,
    pool_y_atoms: String,
    liquidity_supply: String,
    position_share: String,
    expected_position_x_atoms: String,
    expected_position_y_atoms: String,
    deposit_x_atoms: String,
    deposit_y_atoms: String,
    expected_deposit_share: String,
    remove_bps: String,
    expected_removed_share: String,
    expected_removed_x_atoms: String,
    expected_removed_y_atoms: String,
    pending_fee_x_atoms: String,
    pending_fee_y_atoms: String,
    pending_reward_atoms: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct FeeVector {
    id: String,
    provenance: String,
    base_factor: String,
    bin_step: String,
    base_fee_power_factor: String,
    variable_fee_control: String,
    volatility_accumulator: String,
    protocol_share_bps: String,
    expected_total_fee_rate_1e9: String,
    amount_atoms: String,
    expected_fee_from_net_atoms: String,
    expected_fee_from_gross_atoms: String,
    expected_protocol_fee_from_gross_atoms: String,
}

#[test]
fn finalized_chain_price_matches_cached_bin_bits() {
    let fixture: Fixture = serde_json::from_str(FIXTURE).unwrap();
    assert_eq!(fixture.contract, "joshi.protocol-fixtures.dlmm.v1");
    assert_eq!(fixture.official_source.repository, "MeteoraAg/dlmm-sdk");
    assert_eq!(fixture.official_source.revision.len(), 40);
    assert_eq!(fixture.official_source.package, "1.9.14");
    assert_eq!(
        fixture.official_source.program,
        "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
    );
    for vector in fixture.chain_price_vectors {
        assert_eq!(vector.provenance, "mainnet_observation", "{}", vector.id);
        assert_eq!(vector.rpc_commitment, "finalized", "{}", vector.id);
        assert_eq!(vector.pool, "HTvjzsfX3yU6BUodCjZ5vZkUrAxMDTrBs3CJaq43ashR");
        assert_eq!(
            vector.bin_array,
            "2j5ep8wxApESNcqQdtKi6owCURUopnBbGgfRffUQ3CRF"
        );
        assert!(
            parse_u64(&vector.bin_array_observation_slot)
                >= parse_u64(&vector.pool_observation_slot)
        );
        assert_eq!(parse_i64(&vector.bin_array_index), -371);
        assert_eq!(parse_u64(&vector.bin_array_version), 2);
        assert_eq!(parse_u64(&vector.amount_x), 0);
        assert!(parse_u64(&vector.amount_y) > 0);
        assert!(parse_u128(&vector.liquidity_supply) > 0);
        let expected = parse_u128(&vector.expected_price_q64);
        assert_eq!(
            parse_u128(&vector.stored_price_q64),
            expected,
            "{}",
            vector.id
        );
        assert_eq!(
            price_from_bin_id(
                BinId::new(parse_i32(&vector.active_bin_id)),
                BinStep::new(parse_u16(&vector.bin_step)).unwrap(),
            )
            .unwrap()
            .bits(),
            expected,
            "{}",
            vector.id
        );
    }
}

#[test]
fn position_add_remove_and_claim_vectors_are_exact_and_separate() {
    let fixture: Fixture = serde_json::from_str(FIXTURE).unwrap();
    for vector in fixture.position_vectors {
        assert_eq!(vector.provenance, "synthetic_boundary", "{}", vector.id);
        let state = state_from_vector(&vector);
        let inventory = state.inventory().unwrap();
        assert_eq!(
            inventory.principal.x.get(),
            parse_u64(&vector.expected_position_x_atoms),
            "{}",
            vector.id
        );
        assert_eq!(
            inventory.principal.y.get(),
            parse_u64(&vector.expected_position_y_atoms),
            "{}",
            vector.id
        );
        assert_eq!(
            inventory.pending_fees,
            Some(AssetPairAmounts {
                x: atoms(&vector.pending_fee_x_atoms),
                y: atoms(&vector.pending_fee_y_atoms),
            })
        );
        assert_eq!(
            inventory.pending_rewards.as_ref().unwrap()[0].atoms,
            atoms(&vector.pending_reward_atoms)
        );

        let identity = identity(&state);
        let add = project_add(
            &state,
            &AddLiquidityIntent {
                identity: identity.clone(),
                deposits: vec![BinDeposit {
                    bin_id: BinId::new(parse_i32(&vector.bin_id)),
                    amounts: AssetPairAmounts {
                        x: atoms(&vector.deposit_x_atoms),
                        y: atoms(&vector.deposit_y_atoms),
                    },
                }],
            },
        )
        .unwrap();
        assert_eq!(
            add.deposits[0].projected_liquidity_share,
            Some(parse_u128(&vector.expected_deposit_share)),
            "{}",
            vector.id
        );

        let removal = project_remove(
            &state,
            &RemoveLiquidityIntent {
                identity,
                removals: vec![BinRemoval {
                    bin_id: BinId::new(parse_i32(&vector.bin_id)),
                    bps: RemoveBps::new(parse_u16(&vector.remove_bps)).unwrap(),
                }],
                claim_fees: true,
                claim_rewards: true,
                close_position_account: false,
            },
        )
        .unwrap();
        assert_eq!(
            removal.bins[0].removed_share,
            parse_u128(&vector.expected_removed_share)
        );
        assert_eq!(
            removal.principal,
            AssetPairAmounts {
                x: atoms(&vector.expected_removed_x_atoms),
                y: atoms(&vector.expected_removed_y_atoms),
            }
        );
        assert_eq!(removal.claimed_fees, inventory.pending_fees);
        assert_eq!(removal.claimed_rewards, inventory.pending_rewards);
    }
}

#[test]
fn dlmm_fee_vectors_preserve_units_and_rounding() {
    let fixture: Fixture = serde_json::from_str(FIXTURE).unwrap();
    for vector in fixture.fee_vectors {
        assert_eq!(vector.provenance, "synthetic_boundary", "{}", vector.id);
        let parameters = DynamicFeeParameters {
            base_factor: parse_u16(&vector.base_factor),
            bin_step: parse_u16(&vector.bin_step),
            base_fee_power_factor: parse_u8(&vector.base_fee_power_factor),
            variable_fee_control: parse_u32(&vector.variable_fee_control),
            volatility_accumulator: parse_u32(&vector.volatility_accumulator),
            protocol_share_bps: parse_u16(&vector.protocol_share_bps),
        };
        let rate = total_fee_rate(parameters).unwrap();
        assert_eq!(rate.get(), parse_u64(&vector.expected_total_fee_rate_1e9));
        let amount = parse_u64(&vector.amount_atoms);
        assert_eq!(
            fee_from_net_amount(amount, rate).unwrap(),
            parse_u64(&vector.expected_fee_from_net_atoms)
        );
        let gross_fee = fee_from_gross_amount(amount, rate).unwrap();
        assert_eq!(gross_fee, parse_u64(&vector.expected_fee_from_gross_atoms));
        assert_eq!(
            protocol_fee_amount(gross_fee, parameters.protocol_share_bps).unwrap(),
            parse_u64(&vector.expected_protocol_fee_from_gross_atoms)
        );
    }
}

proptest! {
    #[test]
    fn bin_price_is_monotone_or_returns_a_typed_fixed_width_refusal(
        bin_id in -10_000_i32..10_000,
        bin_step in 1_u16..400,
    ) {
        let step = BinStep::new(bin_step).unwrap();
        let left = price_from_bin_id(BinId::new(bin_id), step);
        let right = price_from_bin_id(BinId::new(bin_id + 1), step);
        if let (Ok(left), Ok(right)) = (left, right) {
            prop_assert!(left <= right);
        }
    }

    #[test]
    fn floor_entitlement_never_exceeds_pool_inventory(
        pool_x in any::<u64>(),
        pool_y in any::<u64>(),
        supply in 1_u128..u128::MAX,
        share_seed in any::<u128>(),
    ) {
        let share = share_seed % (supply + u128::from(supply != u128::MAX));
        let share = share.min(supply);
        let bin = PositionBinState {
            bin_id: BinId::new(0),
            price_q64: Q64x64::ONE,
            pool_amounts: AssetPairAmounts {
                x: AtomQty::new(pool_x),
                y: AtomQty::new(pool_y),
            },
            liquidity_supply: supply,
            position_share: share,
            accrual: AccrualState::ObservedPending {
                fees: AssetPairAmounts::default(),
                rewards: Vec::new(),
            },
        };
        let inventory = inventory_for_share(&bin, share).unwrap();
        prop_assert!(inventory.x.get() <= pool_x);
        prop_assert!(inventory.y.get() <= pool_y);
    }
}

fn state_from_vector(vector: &PositionVector) -> DlmmPositionState {
    let bin_id = BinId::new(parse_i32(&vector.bin_id));
    DlmmPositionState {
        profile: profile(),
        venue_id: VenueId::new("fixture:meteora").unwrap(),
        pool_id: PoolId::new("fixture:pool").unwrap(),
        position_id: PositionId::new("fixture:position").unwrap(),
        observation_id: ObservationId::new("fixture:position-state").unwrap(),
        slot: WireU64::new(9),
        version: PositionVersion::V2,
        lifecycle: PositionLifecycle::Open,
        token_x: asset_definition("fixture:x", "fixture:mint-x"),
        token_y: asset_definition("fixture:y", "fixture:mint-y"),
        lower_bin_id: bin_id,
        upper_bin_id: bin_id,
        active_bin_id: BinId::new(bin_id.get() + 1),
        bin_step: BinStep::new(parse_u16(&vector.bin_step)).unwrap(),
        bins: vec![PositionBinState {
            bin_id,
            price_q64: Q64x64::from_bits(parse_u128(&vector.price_q64)),
            pool_amounts: AssetPairAmounts {
                x: atoms(&vector.pool_x_atoms),
                y: atoms(&vector.pool_y_atoms),
            },
            liquidity_supply: parse_u128(&vector.liquidity_supply),
            position_share: parse_u128(&vector.position_share),
            accrual: AccrualState::ObservedPending {
                fees: AssetPairAmounts {
                    x: atoms(&vector.pending_fee_x_atoms),
                    y: atoms(&vector.pending_fee_y_atoms),
                },
                rewards: vec![RewardAmount {
                    asset_id: AssetId::new("fixture:reward").unwrap(),
                    atoms: atoms(&vector.pending_reward_atoms),
                }],
            },
        }],
        unsupported_fields: Vec::new(),
    }
}

fn identity(state: &DlmmPositionState) -> PositionIntentIdentity {
    PositionIntentIdentity {
        position_id: state.position_id.clone(),
        state_observation_id: state.observation_id.clone(),
        profile_id: state.profile.id.clone(),
    }
}

fn profile() -> ProtocolProfile {
    ProtocolProfile {
        id: ProtocolProfileId::new("fixture:dlmm-profile").unwrap(),
        venue: VenueId::new("fixture:meteora").unwrap(),
        family: ProtocolFamily::MeteoraDlmm,
        program_identity: StableString::new("fixture:dlmm-program").unwrap(),
        source_revision: StableString::new("fixture:dlmm-revision").unwrap(),
    }
}

fn asset_definition(asset: &str, observation: &str) -> ObservedAssetDefinition {
    ObservedAssetDefinition {
        asset_id: AssetId::new(asset).unwrap(),
        decimals: 6,
        token_program: StableString::new("spl-token").unwrap(),
        observation_id: ObservationId::new(observation).unwrap(),
    }
}

fn atoms(value: &str) -> AtomQty {
    AtomQty::new(parse_u64(value))
}

fn parse_u8(value: &str) -> u8 {
    value.parse().unwrap()
}

fn parse_u16(value: &str) -> u16 {
    value.parse().unwrap()
}

fn parse_u32(value: &str) -> u32 {
    value.parse().unwrap()
}

fn parse_u64(value: &str) -> u64 {
    value.parse().unwrap()
}

fn parse_u128(value: &str) -> u128 {
    value.parse().unwrap()
}

fn parse_i32(value: &str) -> i32 {
    value.parse().unwrap()
}

fn parse_i64(value: &str) -> i64 {
    value.parse().unwrap()
}

fn assert_no_json_numbers(value: &serde_json::Value) {
    match value {
        serde_json::Value::Number(number) => panic!("JSON number is forbidden: {number}"),
        serde_json::Value::Array(values) => values.iter().for_each(assert_no_json_numbers),
        serde_json::Value::Object(values) => values.values().for_each(assert_no_json_numbers),
        serde_json::Value::Null | serde_json::Value::Bool(_) | serde_json::Value::String(_) => {}
    }
}
