use joshi_accounting::amount::AtomQty;
use joshi_domain::{
    AssetId, ObservationId, PoolId, ProtocolProfileId, QuoteId, StableString, VenueId, WireU64,
};
use proptest::prelude::*;
use serde::Deserialize;

use crate::{
    fee::{CreatorFee, FeeBps, FeePolicy, FeeSchedule, FeeTier},
    profile::{ProtocolFamily, ProtocolProfile, VenueLifecycle},
    pump::{PumpCurveState, PumpSwapState},
    quote::{QuoteOutcome, QuoteRefusal, QuoteRequest, QuoteSize},
};

const FIXTURE: &str = include_str!("../../../fixtures/protocol/pump_quotes.json");

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
    chain_marks: Vec<ChainMark>,
    quote_vectors: Vec<QuoteVector>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct OfficialSource {
    repository: String,
    revision: String,
    pump_sdk: String,
    pump_swap_sdk: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ChainMark {
    id: String,
    provenance: String,
    rpc_commitment: String,
    slot: String,
    program: String,
    curve_account: String,
    mint: String,
    account_length: String,
    virtual_base_reserves: String,
    virtual_quote_reserves: String,
    real_base_reserves: String,
    real_quote_reserves: String,
    base_mint_supply: String,
    complete: bool,
    is_mayhem_mode: bool,
    expected_mark_numerator: String,
    expected_mark_denominator: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct QuoteVector {
    id: String,
    provenance: String,
    venue: String,
    virtual_base_reserves: String,
    virtual_quote_reserves: String,
    real_base_reserves: String,
    real_quote_reserves: String,
    base_mint_supply: String,
    raw_quote_reserves: String,
    virtual_quote_reserves_signed: String,
    lp_bps: String,
    protocol_bps: String,
    creator_mode: String,
    creator_bps: String,
    size_kind: String,
    size_atoms: String,
    expected: Option<ExpectedQuote>,
    refusal: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
#[allow(clippy::struct_field_names)]
struct ExpectedQuote {
    raw_quote_atoms: String,
    lp_fee_atoms: String,
    protocol_fee_atoms: String,
    creator_fee_atoms: String,
    input_atoms: String,
    output_atoms: String,
}

#[test]
fn official_provenance_and_finalized_chain_mark_are_retained() {
    let fixture: Fixture = serde_json::from_str(FIXTURE).unwrap();
    assert_eq!(fixture.contract, "joshi.protocol-fixtures.pump.v1");
    assert_eq!(
        fixture.official_source.repository,
        "pump-fun/pump-public-docs"
    );
    assert_eq!(fixture.official_source.revision.len(), 40);
    assert_eq!(fixture.official_source.pump_sdk, "1.36.0");
    assert_eq!(fixture.official_source.pump_swap_sdk, "1.19.0");
    for vector in fixture.chain_marks {
        assert_eq!(vector.provenance, "mainnet_observation", "{}", vector.id);
        assert_eq!(vector.rpc_commitment, "finalized", "{}", vector.id);
        assert_eq!(
            vector.program,
            "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
        );
        assert_eq!(parse_u64(&vector.account_length), 115);
        let state = PumpCurveState {
            profile: profile(ProtocolFamily::PumpCurve),
            pool_id: pool(&vector.curve_account),
            base_asset_id: asset(&format!("solana:spl:{}", vector.mint)),
            quote_asset_id: asset("solana:native:SOL"),
            state_observation_id: observation(&format!("fixture:{}:state", vector.id)),
            fee_observation_id: observation(&format!("fixture:{}:fee-unavailable", vector.id)),
            slot: WireU64::new(parse_u64(&vector.slot)),
            lifecycle: if vector.complete {
                VenueLifecycle::Complete
            } else {
                VenueLifecycle::Trading
            },
            virtual_base_reserves: atoms(&vector.virtual_base_reserves),
            virtual_quote_reserves: atoms(&vector.virtual_quote_reserves),
            real_base_reserves: atoms(&vector.real_base_reserves),
            real_quote_reserves: atoms(&vector.real_quote_reserves),
            base_mint_supply: atoms(&vector.base_mint_supply),
            is_mayhem_mode: vector.is_mayhem_mode,
            fee_policy: FeePolicy::Flat(schedule(0, 0, CreatorFee::Unknown)),
        };
        let mark = state.mark().unwrap();
        assert_eq!(
            mark.atomic_price.numerator_quote_atoms(),
            parse_u128(&vector.expected_mark_numerator),
            "{}",
            vector.id
        );
        assert_eq!(
            mark.atomic_price.denominator_base_atoms(),
            parse_u128(&vector.expected_mark_denominator),
            "{}",
            vector.id
        );
    }
}

#[test]
fn quote_goldens_preserve_formula_order_and_refusals() {
    let fixture: Fixture = serde_json::from_str(FIXTURE).unwrap();
    for vector in fixture.quote_vectors {
        assert_eq!(vector.provenance, "synthetic_boundary", "{}", vector.id);
        let family = match vector.venue.as_str() {
            "pump_curve" => ProtocolFamily::PumpCurve,
            "pumpswap_canonical" => ProtocolFamily::PumpSwapCanonical,
            other => panic!("{}: unsupported test venue {other}", vector.id),
        };
        let profile = profile(family);
        let request = request(&profile, parse_size(&vector));
        let creator = match vector.creator_mode.as_str() {
            "none" => CreatorFee::NotApplicable,
            "charged" => CreatorFee::Charged(bps(&vector.creator_bps)),
            "unknown" => CreatorFee::Unknown,
            other => panic!("{}: unsupported creator mode {other}", vector.id),
        };
        let selected_schedule = schedule(
            parse_u16(&vector.lp_bps),
            parse_u16(&vector.protocol_bps),
            creator,
        );
        let fee_policy = match family {
            ProtocolFamily::PumpSwapCanonical => FeePolicy::MarketCapTiers(vec![FeeTier {
                threshold_quote_atoms: 0,
                schedule: selected_schedule,
            }]),
            _ => FeePolicy::Flat(selected_schedule),
        };
        let result = match family {
            ProtocolFamily::PumpCurve => PumpCurveState {
                profile,
                pool_id: pool("fixture:pool"),
                base_asset_id: asset("fixture:base"),
                quote_asset_id: asset("fixture:quote"),
                state_observation_id: observation("fixture:state"),
                fee_observation_id: observation("fixture:fee"),
                slot: WireU64::new(7),
                lifecycle: VenueLifecycle::Trading,
                virtual_base_reserves: atoms(&vector.virtual_base_reserves),
                virtual_quote_reserves: atoms(&vector.virtual_quote_reserves),
                real_base_reserves: atoms(&vector.real_base_reserves),
                real_quote_reserves: atoms(&vector.real_quote_reserves),
                base_mint_supply: atoms(&vector.base_mint_supply),
                is_mayhem_mode: true,
                fee_policy,
            }
            .calculate(&request)
            .into_result(),
            ProtocolFamily::PumpSwapCanonical => PumpSwapState {
                profile,
                pool_id: pool("fixture:pool"),
                base_asset_id: asset("fixture:base"),
                quote_asset_id: asset("fixture:quote"),
                state_observation_id: observation("fixture:state"),
                fee_observation_id: observation("fixture:fee"),
                slot: WireU64::new(7),
                lifecycle: VenueLifecycle::Trading,
                base_reserves: atoms(&vector.real_base_reserves),
                raw_quote_reserves: atoms(&vector.raw_quote_reserves),
                virtual_quote_reserves: vector.virtual_quote_reserves_signed.parse().unwrap(),
                base_mint_supply: atoms(&vector.base_mint_supply),
                fee_policy,
            }
            .calculate(&request)
            .into_result(),
            _ => unreachable!(),
        };

        match (vector.expected, vector.refusal) {
            (Some(expected), None) => {
                let quote = result.unwrap_or_else(|error| panic!("{}: {error}", vector.id));
                assert_eq!(
                    quote.raw_quote_atoms.get(),
                    parse_u64(&expected.raw_quote_atoms)
                );
                assert_eq!(quote.fees.lp_atoms, parse_u64(&expected.lp_fee_atoms));
                assert_eq!(
                    quote.fees.protocol_atoms,
                    parse_u64(&expected.protocol_fee_atoms)
                );
                assert_eq!(
                    quote.fees.creator_atoms,
                    parse_u64(&expected.creator_fee_atoms)
                );
                assert_eq!(quote.input.atoms.get(), parse_u64(&expected.input_atoms));
                assert_eq!(quote.output.atoms.get(), parse_u64(&expected.output_atoms));
                assert_eq!(
                    quote.binding.observed.state_observation_id.as_str(),
                    "fixture:state"
                );
                assert_eq!(
                    quote.binding.observed.fee_observation_id.as_str(),
                    "fixture:fee"
                );
            }
            (None, Some(expected)) => assert_eq!(refusal_code(result.unwrap_err()), expected),
            _ => panic!("{}: expected exactly one outcome", vector.id),
        }
    }
}

#[test]
fn refusal_artifact_keeps_intended_and_observed_state_identity() {
    let profile = profile(ProtocolFamily::PumpCurve);
    let state = PumpCurveState {
        profile: profile.clone(),
        pool_id: pool("fixture:pool"),
        base_asset_id: asset("fixture:base"),
        quote_asset_id: asset("fixture:quote"),
        state_observation_id: observation("fixture:observed-state"),
        fee_observation_id: observation("fixture:fee"),
        slot: WireU64::new(8),
        lifecycle: VenueLifecycle::Trading,
        virtual_base_reserves: AtomQty::new(1_000),
        virtual_quote_reserves: AtomQty::new(500),
        real_base_reserves: AtomQty::new(800),
        real_quote_reserves: AtomQty::new(400),
        base_mint_supply: AtomQty::new(2_000),
        is_mayhem_mode: true,
        fee_policy: FeePolicy::Flat(schedule(0, 0, CreatorFee::NotApplicable)),
    };
    let mut stale_request = request(&profile, QuoteSize::ExactBaseOutBuy(AtomQty::new(100)));
    stale_request.intended_state_observation = Some(observation("fixture:intended-state"));
    let calculation = state.calculate(&stale_request);
    assert_eq!(
        calculation.binding.intended_state_observation,
        stale_request.intended_state_observation
    );
    assert_eq!(
        calculation.binding.observed.state_observation_id,
        state.state_observation_id
    );
    assert_eq!(
        calculation.outcome,
        QuoteOutcome::Refused(QuoteRefusal::IntendedStateMismatch)
    );
}

proptest! {
    #[test]
    fn zero_fee_pumpswap_quotes_preserve_directional_amounts(
        base_reserve in 2_u64..1_000_000,
        quote_reserve in 1_u64..1_000_000,
        requested in 1_u64..500_000,
    ) {
        prop_assume!(requested < base_reserve);
        let profile = profile(ProtocolFamily::PumpSwapCanonical);
        let state = PumpSwapState {
            profile: profile.clone(),
            pool_id: pool("fixture:pool"),
            base_asset_id: asset("fixture:base"),
            quote_asset_id: asset("fixture:quote"),
            state_observation_id: observation("fixture:state"),
            fee_observation_id: observation("fixture:fee"),
            slot: WireU64::new(7),
            lifecycle: VenueLifecycle::Trading,
            base_reserves: AtomQty::new(base_reserve),
            raw_quote_reserves: AtomQty::new(quote_reserve),
            virtual_quote_reserves: 0,
            base_mint_supply: AtomQty::new(base_reserve),
            fee_policy: FeePolicy::MarketCapTiers(vec![FeeTier {
                threshold_quote_atoms: 0,
                schedule: schedule(0, 0, CreatorFee::NotApplicable),
            }]),
        };
        let calculation = state.calculate(&request(
            &profile,
            QuoteSize::ExactBaseOutBuy(AtomQty::new(requested)),
        ));
        prop_assert_eq!(calculation.binding.quote_id.as_str(), "fixture:quote-id");
        let quote = calculation.into_result().unwrap();
        prop_assert_eq!(quote.output.atoms.get(), requested);
        prop_assert_eq!(quote.input.atoms, quote.raw_quote_atoms);
        prop_assert!(quote.input.atoms.get() > 0);
    }
}

fn request(profile: &ProtocolProfile, size: QuoteSize) -> QuoteRequest {
    QuoteRequest {
        quote_id: QuoteId::new("fixture:quote-id").unwrap(),
        intent_command_id: None,
        intended_state_observation: Some(observation("fixture:state")),
        expected_profile_id: profile.id.clone(),
        venue_id: profile.venue.clone(),
        pool_id: pool("fixture:pool"),
        base_asset_id: asset("fixture:base"),
        quote_asset_id: asset("fixture:quote"),
        size,
    }
}

fn profile(family: ProtocolFamily) -> ProtocolProfile {
    let family_name = match family {
        ProtocolFamily::PumpCurve => "curve",
        ProtocolFamily::PumpSwapCanonical => "swap-canonical",
        ProtocolFamily::PumpSwapNonCanonical => "swap-noncanonical",
        ProtocolFamily::MeteoraDlmm => "dlmm",
    };
    ProtocolProfile {
        id: ProtocolProfileId::new(format!("fixture:profile:{family_name}")).unwrap(),
        venue: VenueId::new("fixture:venue").unwrap(),
        family,
        program_identity: StableString::new("fixture:program").unwrap(),
        source_revision: StableString::new("fixture:revision").unwrap(),
    }
}

fn schedule(lp: u16, protocol: u16, creator: CreatorFee) -> FeeSchedule {
    FeeSchedule {
        lp: FeeBps::new(lp).unwrap(),
        protocol: FeeBps::new(protocol).unwrap(),
        creator,
    }
}

fn bps(value: &str) -> FeeBps {
    FeeBps::new(parse_u16(value)).unwrap()
}

fn parse_size(vector: &QuoteVector) -> QuoteSize {
    let amount = atoms(&vector.size_atoms);
    match vector.size_kind.as_str() {
        "exact_base_out_buy" => QuoteSize::ExactBaseOutBuy(amount),
        "exact_base_in_sell" => QuoteSize::ExactBaseInSell(amount),
        "exact_quote_in_buy" => QuoteSize::ExactQuoteInBuy(amount),
        "exact_quote_out_sell" => QuoteSize::ExactQuoteOutSell(amount),
        other => panic!("{}: unsupported size kind {other}", vector.id),
    }
}

fn refusal_code(refusal: QuoteRefusal) -> String {
    match refusal {
        QuoteRefusal::CreatorFeeApplicabilityUnknown => "creator_fee_applicability_unknown",
        QuoteRefusal::UnsupportedSizeKind => "unsupported_size_kind",
        QuoteRefusal::InsufficientRealQuote => "insufficient_real_quote",
        other => panic!("unexpected refusal: {other:?}"),
    }
    .to_owned()
}

fn atoms(value: &str) -> AtomQty {
    AtomQty::new(parse_u64(value))
}

fn parse_u16(value: &str) -> u16 {
    value.parse().unwrap()
}

fn parse_u64(value: &str) -> u64 {
    value.parse().unwrap()
}

fn parse_u128(value: &str) -> u128 {
    value.parse().unwrap()
}

fn asset(value: &str) -> AssetId {
    AssetId::new(value).unwrap()
}

fn pool(value: &str) -> PoolId {
    PoolId::new(value).unwrap()
}

fn observation(value: &str) -> ObservationId {
    ObservationId::new(value).unwrap()
}

fn assert_no_json_numbers(value: &serde_json::Value) {
    match value {
        serde_json::Value::Number(number) => panic!("JSON number is forbidden: {number}"),
        serde_json::Value::Array(values) => values.iter().for_each(assert_no_json_numbers),
        serde_json::Value::Object(values) => values.values().for_each(assert_no_json_numbers),
        serde_json::Value::Null | serde_json::Value::Bool(_) | serde_json::Value::String(_) => {}
    }
}
