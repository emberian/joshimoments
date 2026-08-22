//! Study M0: the exact stack, checked against fills that actually landed.
//!
//! Every number here comes from `fixtures/protocol/m0_venue_geometry_2026-08-21.json`, which holds
//! account bytes read in one `getMultipleAccounts` call at one finalized slot, plus six swaps that
//! landed on those two venues. The test needs no network: the bytes are already retained.
//!
//! The point of checking against landed fills rather than against a golden the same code produced
//! is that a formula which agrees with itself has proved nothing. These assertions fail if the
//! operation order, the rounding direction, the fee basis, or the reserve set is wrong by one atom.

use joshi_market_math::{
    fee::{CreatorFee, FeeBps, FeeSchedule},
    stack::{
        DeclaredStress, DeclaredToleranceBps, ExactCurveState, PriceObject, PriceStack,
        VenueFormula,
    },
};
use serde_json::Value;

const FIXTURE: &str = include_str!("../../../fixtures/protocol/m0_venue_geometry_2026-08-21.json");

fn fixture() -> Value {
    serde_json::from_str(FIXTURE).expect("fixture parses")
}

fn number(value: &Value, key: &str) -> u128 {
    value[key]
        .as_str()
        .unwrap_or_else(|| panic!("{key} is a string-encoded integer"))
        .parse()
        .unwrap_or_else(|error| panic!("{key}: {error}"))
}

fn venue(fixture: &Value, id: &str) -> Value {
    fixture["venues"]
        .as_array()
        .expect("venues")
        .iter()
        .find(|entry| entry["id"] == id)
        .unwrap_or_else(|| panic!("venue {id}"))
        .clone()
}

fn schedule(lp: u16, protocol: u16, creator: u16) -> FeeSchedule {
    FeeSchedule {
        lp: FeeBps::new(lp).expect("lp rate"),
        protocol: FeeBps::new(protocol).expect("protocol rate"),
        creator: CreatorFee::Charged(FeeBps::new(creator).expect("creator rate")),
    }
}

fn state_from(fixture: &Value, id: &str, formula: VenueFormula) -> ExactCurveState {
    let entry = venue(fixture, id);
    ExactCurveState {
        formula,
        base_atoms: number(&entry, "effectiveBaseAtoms"),
        effective_quote_atoms: number(&entry, "effectiveQuoteAtoms"),
        schedule: schedule(
            u16::try_from(number(&entry, "feeLpBps")).expect("lp fits"),
            u16::try_from(number(&entry, "feeProtocolBps")).expect("protocol fits"),
            u16::try_from(number(&entry, "feeCreatorBps")).expect("creator fits"),
        ),
    }
}

fn fills(fixture: &Value, venue_id: &str, instruction: &str) -> Vec<Value> {
    fixture["landedFills"]
        .as_array()
        .expect("landedFills")
        .iter()
        .filter(|fill| fill["venue"] == venue_id && fill["instruction"] == instruction)
        .cloned()
        .collect()
}

#[test]
fn the_fixture_names_its_own_evidence_and_its_own_gaps() {
    let fixture = fixture();
    assert_eq!(fixture["contract"], "joshi.m0.venue_geometry.v1");
    assert_eq!(fixture["commitment"], "finalized");
    // A quote read at a slot that can be rolled back is not evidence about the chain.
    assert!(number(&fixture, "contextSlot") > 0);
    // The fixture must state what it could not reconstruct. An empty list would mean the work was
    // not done, not that everything was known.
    assert!(
        fixture["unsupported"]
            .as_array()
            .expect("unsupported")
            .len()
            >= 4,
        "the reconstruction had gaps and the fixture must name them"
    );
}

#[test]
fn pumpswap_buys_reproduce_four_landed_fills_to_the_atom() {
    let fixture = fixture();
    let entry = venue(&fixture, "pumpswap");
    let virtual_quote = number(&entry, "unattributedQuoteSideReserveAtoms");
    let fills = fills(&fixture, "pumpswap", "BuyExactQuoteIn");
    assert_eq!(fills.len(), 4);
    for fill in &fills {
        let state = ExactCurveState {
            formula: VenueFormula::PumpSwapExactQuoteIn,
            base_atoms: number(fill, "poolBaseVaultAtoms"),
            effective_quote_atoms: number(fill, "poolQuoteVaultAtoms") + virtual_quote,
            schedule: schedule(20, 5, 5),
        };
        let leg = state
            .buy_with_quote_in(number(fill, "quoteInAtoms"))
            .expect("the fill landed, so the arithmetic must produce it");
        assert_eq!(
            leg.base_out_atoms,
            number(fill, "observedBaseOutAtoms"),
            "base out"
        );
        assert_eq!(
            u128::from(leg.fees.protocol_atoms),
            number(fill, "observedProtocolFeeAtoms"),
            "protocol fee"
        );
        assert_eq!(
            u128::from(leg.fees.creator_atoms),
            number(fill, "observedCreatorFeeAtoms"),
            "creator fee"
        );
        assert_eq!(
            leg.raw_quote_atoms + u128::from(leg.fees.lp_atoms),
            number(fill, "observedPoolQuoteDeltaAtoms"),
            "what the pool's quote vault actually gained"
        );
    }
}

#[test]
fn dropping_the_unnamed_reserve_misprices_every_one_of_those_fills() {
    // This is the control for the assertion above. The unattributed field at pool offset 245 is not
    // decoration: without it the same code, on the same bytes, is wrong by more than the entire
    // round-trip fee, and wrong in the direction that flatters the trade.
    let fixture = fixture();
    let fills = fills(&fixture, "pumpswap", "BuyExactQuoteIn");
    for fill in &fills {
        let state = ExactCurveState {
            formula: VenueFormula::PumpSwapExactQuoteIn,
            base_atoms: number(fill, "poolBaseVaultAtoms"),
            effective_quote_atoms: number(fill, "poolQuoteVaultAtoms"),
            schedule: schedule(20, 5, 5),
        };
        let leg = state
            .buy_with_quote_in(number(fill, "quoteInAtoms"))
            .expect("still computes, just wrongly");
        let observed = number(fill, "observedBaseOutAtoms");
        let error_bps = (leg.base_out_atoms - observed) * 10_000 / observed;
        assert!(
            (118..=120).contains(&error_bps),
            "expected roughly 119 bps of overstatement, saw {error_bps}"
        );
    }
}

#[test]
fn pumpswap_sell_reproduces_the_landed_fill_to_the_atom() {
    let fixture = fixture();
    let entry = venue(&fixture, "pumpswap");
    let virtual_quote = number(&entry, "unattributedQuoteSideReserveAtoms");
    let fill = fills(&fixture, "pumpswap", "Sell")
        .into_iter()
        .next()
        .expect("one landed sell");
    let state = ExactCurveState {
        formula: VenueFormula::PumpSwapExactQuoteIn,
        base_atoms: number(&fill, "poolBaseVaultAtoms"),
        effective_quote_atoms: number(&fill, "poolQuoteVaultAtoms") + virtual_quote,
        schedule: schedule(20, 5, 5),
    };
    let leg = state
        .sell_base_in(number(&fill, "baseInAtoms"))
        .expect("the fill landed");
    assert_eq!(leg.raw_quote_atoms, number(&fill, "observedRawQuoteAtoms"));
    assert_eq!(
        leg.quote_out_atoms,
        number(&fill, "observedSellerProceedsAtoms")
    );
    assert_eq!(
        u128::from(leg.fees.protocol_atoms),
        number(&fill, "observedProtocolFeeAtoms")
    );
    assert_eq!(
        u128::from(leg.fees.creator_atoms),
        number(&fill, "observedCreatorFeeAtoms")
    );
}

#[test]
fn bonding_curve_sell_reproduces_the_landed_fill_to_the_atom() {
    let fixture = fixture();
    let fill = fills(&fixture, "pump_curve", "Sell")
        .into_iter()
        .next()
        .expect("one landed sell");
    let state = ExactCurveState {
        formula: VenueFormula::PumpBondingCurve,
        base_atoms: number(&fill, "virtualBaseAtoms"),
        effective_quote_atoms: number(&fill, "virtualQuoteAtoms"),
        schedule: schedule(0, 95, 30),
    };
    let leg = state
        .sell_base_in(number(&fill, "baseInAtoms"))
        .expect("the fill landed");
    assert_eq!(leg.raw_quote_atoms, number(&fill, "observedRawQuoteAtoms"));
    assert_eq!(
        u128::from(leg.fees.protocol_atoms),
        number(&fill, "observedProtocolFeeAtoms")
    );
    assert_eq!(
        u128::from(leg.fees.creator_atoms),
        number(&fill, "observedCreatorFeeAtoms")
    );
    assert_eq!(
        leg.quote_out_atoms,
        number(&fill, "observedSellerProceedsAtoms")
    );
}

#[test]
fn the_creator_rate_the_program_applied_is_not_the_rate_the_global_account_states() {
    // The bonding-curve program's Global account still carries creator_fee_basis_points = 5. The
    // landed transfer was 30 bps. Reading the stale field would understate one leg by 25 bps and a
    // round trip by 50. This test exists so that regression is loud.
    let fixture = fixture();
    let fill = fills(&fixture, "pump_curve", "Sell")
        .into_iter()
        .next()
        .expect("one landed sell");
    let raw = number(&fill, "observedRawQuoteAtoms");
    let stale = ExactCurveState {
        formula: VenueFormula::PumpBondingCurve,
        base_atoms: number(&fill, "virtualBaseAtoms"),
        effective_quote_atoms: number(&fill, "virtualQuoteAtoms"),
        schedule: schedule(0, 95, 5),
    };
    let leg = stale
        .sell_base_in(number(&fill, "baseInAtoms"))
        .expect("computes");
    let shortfall = number(&fill, "observedCreatorFeeAtoms") - u128::from(leg.fees.creator_atoms);
    assert_eq!(shortfall * 10_000 / raw, 25);
}

#[test]
fn the_seven_price_objects_are_seven_different_numbers() {
    let fixture = fixture();
    let state = state_from(&fixture, "pump_curve", VenueFormula::PumpBondingCurve);
    // One SOL in, and a runner of ten million whole tokens, on a six-decimal mint.
    let clip = 1_000_000_000_u128;
    let runner = 10_000_000_000_000_u128;
    let stack = PriceStack::build(
        state,
        None,
        clip,
        runner,
        DeclaredToleranceBps::new(500).expect("declared tolerance"),
        DeclaredStress {
            other_net_base_sold_atoms: runner * 4,
        },
    )
    .expect("stack builds");

    let marginal = stack.marginal_pool_price;
    let clip_price = stack.intended_clip.average_price;
    let runner_price = stack.full_runner.average_price;
    let stressed_price = stack.stressed_liquidation.average_price;

    // Buying pays above the marginal ratio; selling receives below it; selling into a worse state
    // receives less again. None of the four is interchangeable with any other.
    let cross = |a: joshi_market_math::quote::AtomicPrice,
                 b: joshi_market_math::quote::AtomicPrice| {
        a.numerator_quote_atoms() * b.denominator_base_atoms()
            < b.numerator_quote_atoms() * a.denominator_base_atoms()
    };
    assert!(cross(marginal, clip_price), "clip must cost above marginal");
    assert!(
        cross(runner_price, marginal),
        "runner must fetch below marginal"
    );
    assert!(
        cross(stressed_price, runner_price),
        "stressed liquidation must fetch below unstressed"
    );

    assert_eq!(stack.intended_clip.object, PriceObject::ExactSizeQuote);
    assert_eq!(
        stack.full_runner.object,
        PriceObject::FullPositionLiquidation
    );
    assert_eq!(
        stack.stressed_liquidation.object,
        PriceObject::StressedLiquidation
    );
    // An absent chart mark is an absent record, not a zero and not the marginal price.
    assert!(stack.chart_mark.is_none());

    // The instruction bounds bracket the quote by exactly the declared tolerance and nothing else.
    assert!(stack.buy_instruction_max_quote_in_atoms > stack.intended_clip.quote_atoms);
    assert!(stack.sell_instruction_min_quote_out_atoms < stack.full_runner.quote_atoms);
}

#[test]
fn a_budget_below_one_base_atom_is_refused_rather_than_rounded_to_nothing() {
    let fixture = fixture();
    let state = state_from(&fixture, "pump_curve", VenueFormula::PumpBondingCurve);
    assert!(state.buy_with_quote_in(0).is_err());
    assert!(state.buy_with_quote_in(1).is_err());
}
