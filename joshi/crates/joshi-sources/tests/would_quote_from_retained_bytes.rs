//! Offline regression over the exact bytes Helius mainnet returned for one real `PumpSwap` pool.
//!
//! This walks the same path the live harness walks, minus the network and the catalog: decode the
//! retained response, state the observed inventory, derive the size from that inventory, resolve
//! the fee schedule from the retained fee configuration, and compute the exact quote. Every number
//! asserted here is a function of the checked-in provider bytes and nothing else.

use joshi_accounting::amount::AtomQty;
use joshi_domain::{
    AssetId, ObservationId, PoolId, ProtocolProfileId, QuoteId, StableString, VenueId, WireU64,
};
use joshi_liquidity::pool_depth::{DepthFractionBps, ObservedPoolDepth};
use joshi_market_math::{
    fee::{CreatorFee, FeeBps, FeePolicy, FeeSchedule, FeeTier},
    profile::{ProtocolFamily, ProtocolProfile, VenueLifecycle},
    pump::PumpSwapState,
    quote::{QuoteRequest, QuoteSize},
    wide::{Rounding, mul_div_u128},
    would_quote::{
        ChainSecond, ChainToReceiptAge, LocalReceipt, NOT_AN_EXECUTION, WOULD_QUOTE_AUTHORITY,
    },
};
use joshi_sources::{
    PUMP_AMM_PROGRAM_ID, PUMP_FEE_CONFIG_ADDRESS, PumpFeeConfig, PumpSwapPool, TokenMint,
    TokenVault, WRAPPED_SOL_MINT, read_multiple_accounts,
};

const MAINNET: &str = include_str!("../fixtures/pump_swap_accounts_mainnet.json");
const POOL: &str = "FnzKY6x7entQ1eR3D225dQyT7ybfka4PskBMQhb8L3CC";
const BASE_MINT: &str = "9cRCn9rGT8V2imeM2BaKs13yhMEais3ruM3rPvTGpump";
const SIZE_BPS: u16 = 25;

fn addresses() -> Vec<String> {
    [
        POOL,
        "BmCXK8QFCHgjiqGm7peAtBbZpFPJNsp5fYP5rSRazMS8",
        "DaXhQ3pfN3J5dQnXxVU8YqW9bwA3RUVxXvq2iBjTDVt4",
        BASE_MINT,
        WRAPPED_SOL_MINT,
        PUMP_FEE_CONFIG_ADDRESS,
    ]
    .iter()
    .map(|value| (*value).to_owned())
    .collect()
}

struct Decoded {
    slot: u64,
    depth: ObservedPoolDepth,
    supply: u64,
    market_cap: u128,
    fee_policy: FeePolicy,
    schedule: FeeSchedule,
}

fn decode() -> Decoded {
    let addresses = addresses();
    let response =
        read_multiple_accounts(MAINNET.as_bytes(), &addresses).expect("captured response decodes");
    let pool = PumpSwapPool::decode(response.require(POOL).expect("pool")).expect("pool decodes");
    let base_vault = TokenVault::decode(
        response
            .require(&pool.pool_base_token_account)
            .expect("base vault"),
    )
    .expect("base vault decodes");
    let quote_vault = TokenVault::decode(
        response
            .require(&pool.pool_quote_token_account)
            .expect("quote vault"),
    )
    .expect("quote vault decodes");
    let base_mint =
        TokenMint::decode(response.require(&pool.base_mint).expect("base mint")).expect("mint");
    let fee_config = PumpFeeConfig::decode(
        response
            .require(PUMP_FEE_CONFIG_ADDRESS)
            .expect("fee config"),
    )
    .expect("fee config decodes");

    let depth = ObservedPoolDepth {
        pool_id: PoolId::new(pool.address.clone()).expect("pool id"),
        base_asset_id: AssetId::new(pool.base_mint.clone()).expect("base asset"),
        quote_asset_id: AssetId::new(pool.quote_mint.clone()).expect("quote asset"),
        state_observation_id: ObservationId::new("obs:fixture:pump_swap_accounts_mainnet")
            .expect("observation id"),
        slot: WireU64::new(response.context_slot),
        base_atoms: AtomQty::new(base_vault.amount),
        raw_quote_atoms: AtomQty::new(quote_vault.amount),
        virtual_quote_reserves: pool.virtual_quote_reserves,
    };
    let effective = depth.effective_quote_atoms().expect("effective quote");
    let market_cap = mul_div_u128(
        effective,
        u128::from(base_mint.supply),
        u128::from(depth.base_atoms.get()),
        Rounding::Down,
    )
    .expect("market cap");
    let agreed = fee_config
        .agreed_rates(market_cap)
        .expect("every retained tier table agrees at this market cap");
    let creator = if pool.has_coin_creator() {
        CreatorFee::Charged(FeeBps::new(u16::try_from(agreed.creator).expect("bps")).expect("bps"))
    } else {
        CreatorFee::NotApplicable
    };
    let fee_policy = FeePolicy::MarketCapTiers(
        fee_config.tier_tables[0]
            .iter()
            .map(|row| FeeTier {
                threshold_quote_atoms: row.threshold_quote_atoms,
                schedule: FeeSchedule {
                    lp: FeeBps::new(u16::try_from(row.rates.lp).expect("bps")).expect("bps"),
                    protocol: FeeBps::new(u16::try_from(row.rates.protocol).expect("bps"))
                        .expect("bps"),
                    creator: if pool.has_coin_creator() {
                        CreatorFee::Charged(
                            FeeBps::new(u16::try_from(row.rates.creator).expect("bps"))
                                .expect("bps"),
                        )
                    } else {
                        CreatorFee::NotApplicable
                    },
                },
            })
            .collect(),
    );
    let schedule = fee_policy.select(market_cap).expect("tier selects");
    assert_eq!(schedule.creator, creator);
    Decoded {
        slot: response.context_slot,
        depth,
        supply: base_mint.supply,
        market_cap,
        fee_policy,
        schedule,
    }
}

#[test]
fn the_retained_bytes_state_exactly_one_pool_inventory_at_exactly_one_slot() {
    let decoded = decode();
    assert_eq!(decoded.slot, 440_672_889);
    assert_eq!(decoded.depth.base_atoms.get(), 4_822_874_602_995);
    assert_eq!(decoded.depth.raw_quote_atoms.get(), 15_592_870_111_376);
    assert_eq!(decoded.depth.virtual_quote_reserves, 0);
    assert_eq!(
        decoded.depth.effective_quote_atoms(),
        Ok(15_592_870_111_376)
    );
    assert_eq!(decoded.supply, 997_760_526_216_819);
    assert_eq!(decoded.market_cap, 3_225_866_639_347_321);
}

#[test]
fn the_fee_schedule_is_the_one_every_retained_tier_table_agrees_on() {
    let decoded = decode();
    assert_eq!(decoded.schedule.lp.get(), 20);
    assert_eq!(decoded.schedule.protocol.get(), 5);
    assert_eq!(
        decoded.schedule.creator,
        CreatorFee::Charged(FeeBps::new(5).expect("bps"))
    );
}

#[test]
fn one_quote_recomputed_from_the_retained_bytes_is_exact_to_the_atom() {
    let decoded = decode();
    let size = decoded
        .depth
        .base_fraction_atoms(DepthFractionBps::new(SIZE_BPS).expect("fraction"))
        .expect("size");
    assert_eq!(size.get(), 12_057_186_507);
    // Both directions truncate, so the round trip loses a basis point rather than inventing one.
    // A size derived from inventory must never round up past what the vault was observed to hold.
    assert_eq!(decoded.depth.base_share_bps(size), Ok(24));
    assert!(decoded.depth.base_share_bps(size).expect("share") <= u128::from(SIZE_BPS));

    let profile = ProtocolProfile {
        id: ProtocolProfileId::new("joshi.pumpswap.canonical.v1").expect("profile id"),
        venue: VenueId::new("pumpswap").expect("venue"),
        family: ProtocolFamily::PumpSwapCanonical,
        program_identity: StableString::new(PUMP_AMM_PROGRAM_ID).expect("program"),
        source_revision: StableString::new("fixture").expect("revision"),
    };
    let state = PumpSwapState {
        profile: profile.clone(),
        pool_id: decoded.depth.pool_id.clone(),
        base_asset_id: decoded.depth.base_asset_id.clone(),
        quote_asset_id: decoded.depth.quote_asset_id.clone(),
        state_observation_id: decoded.depth.state_observation_id.clone(),
        fee_observation_id: decoded.depth.state_observation_id.clone(),
        slot: decoded.depth.slot,
        lifecycle: VenueLifecycle::Trading,
        base_reserves: decoded.depth.base_atoms,
        raw_quote_reserves: decoded.depth.raw_quote_atoms,
        virtual_quote_reserves: decoded.depth.virtual_quote_reserves,
        base_mint_supply: AtomQty::new(decoded.supply),
        fee_policy: decoded.fee_policy.clone(),
    };
    let request = QuoteRequest {
        quote_id: QuoteId::new("would-quote-fixture").expect("quote id"),
        intent_command_id: None,
        intended_state_observation: Some(decoded.depth.state_observation_id.clone()),
        expected_profile_id: profile.id.clone(),
        venue_id: profile.venue.clone(),
        pool_id: decoded.depth.pool_id.clone(),
        base_asset_id: decoded.depth.base_asset_id.clone(),
        quote_asset_id: decoded.depth.quote_asset_id.clone(),
        size: QuoteSize::ExactBaseOutBuy(size),
    };
    let quote = state
        .calculate(&request)
        .into_result()
        .expect("the retained state quotes");
    assert_eq!(quote.raw_quote_atoms.get(), 39_079_874_965);
    assert_eq!(quote.fees.lp_atoms, 78_159_750);
    assert_eq!(quote.fees.protocol_atoms, 19_539_938);
    assert_eq!(quote.fees.creator_atoms, 19_539_938);
    assert_eq!(quote.input.atoms.get(), 39_197_114_591);
    assert_eq!(quote.output.atoms.get(), size.get());
    assert_eq!(quote.input.asset_id.as_str(), WRAPPED_SOL_MINT);
    assert_eq!(quote.output.asset_id.as_str(), BASE_MINT);
    // The fee components are the whole difference between the raw consideration and the input.
    assert_eq!(
        quote.input.atoms.get() - quote.raw_quote_atoms.get(),
        quote.fees.checked_total().expect("fee total")
    );
}

#[test]
fn a_quote_binds_to_the_observation_and_slot_it_was_computed_from() {
    let decoded = decode();
    let size = decoded
        .depth
        .base_fraction_atoms(DepthFractionBps::new(SIZE_BPS).expect("fraction"))
        .expect("size");
    let other = ObservationId::new("obs:some-other-read").expect("observation id");
    let profile = ProtocolProfile {
        id: ProtocolProfileId::new("joshi.pumpswap.canonical.v1").expect("profile id"),
        venue: VenueId::new("pumpswap").expect("venue"),
        family: ProtocolFamily::PumpSwapCanonical,
        program_identity: StableString::new(PUMP_AMM_PROGRAM_ID).expect("program"),
        source_revision: StableString::new("fixture").expect("revision"),
    };
    let state = PumpSwapState {
        profile: profile.clone(),
        pool_id: decoded.depth.pool_id.clone(),
        base_asset_id: decoded.depth.base_asset_id.clone(),
        quote_asset_id: decoded.depth.quote_asset_id.clone(),
        state_observation_id: decoded.depth.state_observation_id.clone(),
        fee_observation_id: decoded.depth.state_observation_id.clone(),
        slot: decoded.depth.slot,
        lifecycle: VenueLifecycle::Trading,
        base_reserves: decoded.depth.base_atoms,
        raw_quote_reserves: decoded.depth.raw_quote_atoms,
        virtual_quote_reserves: decoded.depth.virtual_quote_reserves,
        base_mint_supply: AtomQty::new(decoded.supply),
        fee_policy: decoded.fee_policy.clone(),
    };
    let request = QuoteRequest {
        quote_id: QuoteId::new("would-quote-fixture-mismatch").expect("quote id"),
        intent_command_id: None,
        intended_state_observation: Some(other),
        expected_profile_id: profile.id.clone(),
        venue_id: profile.venue.clone(),
        pool_id: decoded.depth.pool_id.clone(),
        base_asset_id: decoded.depth.base_asset_id.clone(),
        quote_asset_id: decoded.depth.quote_asset_id.clone(),
        size: QuoteSize::ExactBaseOutBuy(size),
    };
    let calculation = state.calculate(&request);
    assert_eq!(
        calculation.binding.observed.state_observation_id,
        decoded.depth.state_observation_id
    );
    assert!(calculation.into_result().is_err());
}

#[test]
fn the_age_attached_to_a_would_quote_is_an_interval_and_says_what_it_is_not() {
    let chain = ChainSecond {
        slot: 440_672_889,
        block_time_unix_s: 1_787_311_593,
    };
    let receipt = LocalReceipt {
        clock_id: "joshi-would-quote-fixture".to_owned(),
        monotonic_ns: 629_348_500,
        wall_unix_ms: 1_787_311_605_973,
    };
    let age = ChainToReceiptAge::measure(chain, &receipt).expect("age");
    assert_eq!(age.earliest_ms, 11_973);
    assert_eq!(age.latest_ms, 12_973);
    assert_eq!(age.width_ms(), 1_000);
    assert_eq!(WOULD_QUOTE_AUTHORITY, "read_only_no_execution");
    assert!(NOT_AN_EXECUTION.contains("No fill is inferred"));
}
