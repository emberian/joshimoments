//! Study M0: round-trip cost as a function of size, at two real venue states.
//!
//! The state comes from `fixtures/protocol/m0_venue_geometry_2026-08-21.json` — account bytes read
//! at one finalized slot, with the same arithmetic that reproduces six landed fills to the atom in
//! `joshi-market-math`'s M0 test. No network is used here.
//!
//! Run with `--nocapture` to print the surface.

use joshi_liquidity::round_trip::{CostCurve, DeclaredFixedCosts};
use joshi_market_math::{
    fee::{CreatorFee, FeeBps, FeeSchedule},
    stack::{ExactCurveState, VenueFormula},
};
use serde_json::Value;

const FIXTURE: &str = include_str!("../../../fixtures/protocol/m0_venue_geometry_2026-08-21.json");
const LAMPORTS_PER_SOL: u128 = 1_000_000_000;

fn number(value: &Value, key: &str) -> u128 {
    value[key]
        .as_str()
        .expect("string integer")
        .parse()
        .expect("integer")
}

fn state(id: &str, formula: VenueFormula) -> ExactCurveState {
    let fixture: Value = serde_json::from_str(FIXTURE).expect("fixture parses");
    let entry = fixture["venues"]
        .as_array()
        .expect("venues")
        .iter()
        .find(|entry| entry["id"] == id)
        .expect("venue")
        .clone();
    ExactCurveState {
        formula,
        base_atoms: number(&entry, "effectiveBaseAtoms"),
        effective_quote_atoms: number(&entry, "effectiveQuoteAtoms"),
        schedule: FeeSchedule {
            lp: FeeBps::new(u16::try_from(number(&entry, "feeLpBps")).expect("fits")).expect("lp"),
            protocol: FeeBps::new(u16::try_from(number(&entry, "feeProtocolBps")).expect("fits"))
                .expect("protocol"),
            creator: CreatorFee::Charged(
                FeeBps::new(u16::try_from(number(&entry, "feeCreatorBps")).expect("fits"))
                    .expect("creator"),
            ),
        },
    }
}

/// Network cost observed on the landed transactions in the fixture, not a default.
fn observed_costs(per_transaction_lamports: u128, note: &str) -> DeclaredFixedCosts {
    DeclaredFixedCosts {
        provenance: note.to_owned(),
        per_transaction_quote_atoms: per_transaction_lamports,
        transactions: 2,
        flat_route_quote_atoms: 0,
        unrecovered_rent_quote_atoms: 0,
    }
}

fn ladder(state: &ExactCurveState) -> Vec<u128> {
    [
        1, 10, 50, 100, 250, 500, 1_000, 2_000, 5_000, 10_000, 25_000, 50_000, 100_000,
    ]
    .into_iter()
    .map(|milli| milli * LAMPORTS_PER_SOL / 1_000)
    .filter(|size| *size < state.effective_quote_atoms / 4)
    .collect()
}

fn print_surface(name: &str, state: &ExactCurveState, costs: &DeclaredFixedCosts) -> CostCurve {
    let sizes = ladder(state);
    let curve = CostCurve::walk(state, &sizes, costs).expect("surface walks");
    println!("\n=== {name} ===");
    println!(
        "  effective base reserve   {} atoms\n  effective quote reserve  {} atoms ({}.{:09} SOL)",
        state.base_atoms,
        state.effective_quote_atoms,
        state.effective_quote_atoms / LAMPORTS_PER_SOL,
        state.effective_quote_atoms % LAMPORTS_PER_SOL,
    );
    println!(
        "  fees lp {} bps, protocol {} bps, creator {}",
        state.schedule.lp.get(),
        state.schedule.protocol.get(),
        match state.schedule.creator {
            CreatorFee::Charged(rate) => format!("{} bps", rate.get()),
            CreatorFee::NotApplicable => "not applicable".to_owned(),
            CreatorFee::Unknown => "UNKNOWN".to_owned(),
        }
    );
    println!("  network cost input: {}", costs.provenance);
    println!(
        "\n  {:>12} {:>12} {:>14} {:>16} {:>18} {:>20}",
        "clip (SOL)",
        "clip/Qe bps",
        "abort cost bps",
        "hurdle bps",
        "hurdle+net bps",
        "others' buying (SOL)"
    );
    for point in &curve.points {
        let clip = point.hurdle.clip_quote_in_atoms;
        let bare = CostCurve::walk(
            state,
            &[clip],
            &DeclaredFixedCosts::none("venue only, stated control"),
        )
        .expect("control walks");
        println!(
            "  {:>5}.{:06} {:>12} {:>14} {:>16} {:>18} {:>13}.{:06}",
            clip / LAMPORTS_PER_SOL,
            (clip % LAMPORTS_PER_SOL) / 1_000,
            point
                .hurdle
                .clip_fraction_of_quote_reserve
                .bps_floor()
                .expect("bps"),
            point.self_round_trip.venue_cost.bps_ceil().expect("bps"),
            bare.points[0].hurdle.mark_lift.bps_ceil().expect("bps"),
            point.hurdle.mark_lift.bps_ceil().expect("bps"),
            point.hurdle.other_net_quote_inflow_atoms / LAMPORTS_PER_SOL,
            (point.hurdle.other_net_quote_inflow_atoms % LAMPORTS_PER_SOL) / 1_000,
        );
    }
    curve
}

#[test]
fn the_abort_cost_is_flat_in_size_because_traversal_reverses() {
    // Buying and immediately selling back walks the reserve out and straight back in. What is left
    // is fees and integer dust, so this number barely moves across four orders of magnitude of
    // size. Anyone quoting a single "round-trip cost in basis points" has measured this one.
    for (name, id, formula) in [
        ("pump curve", "pump_curve", VenueFormula::PumpBondingCurve),
        ("pumpswap", "pumpswap", VenueFormula::PumpSwapExactQuoteIn),
    ] {
        let state = state(id, formula);
        let costs = DeclaredFixedCosts::none("venue only, stated control");
        let curve = CostCurve::walk(&state, &ladder(&state), &costs).expect("walks");
        let first = curve.points.first().expect("points");
        let last = curve.points.last().expect("points");
        let low = first.self_round_trip.venue_cost.bps_floor().expect("bps");
        let high = last.self_round_trip.venue_cost.bps_floor().expect("bps");
        assert!(
            high <= low && low - high <= 2,
            "{name}: abort cost should be flat, saw {low} then {high}"
        );
    }
}

#[test]
fn the_crackle_hurdle_is_not_flat_and_that_is_the_whole_difference() {
    // The hurdle measures something else: how far the marginal price has to lift before the clip
    // pays for itself. Entry pays above the mark and exit receives below it, and unlike the abort
    // case those two gaps do not cancel — they are both charged against a mark that must make them
    // up. So this climbs with size while the abort cost does not.
    for (id, formula) in [
        ("pump_curve", VenueFormula::PumpBondingCurve),
        ("pumpswap", VenueFormula::PumpSwapExactQuoteIn),
    ] {
        let state = state(id, formula);
        let costs = DeclaredFixedCosts::none("venue only, stated control");
        let curve = CostCurve::walk(&state, &ladder(&state), &costs).expect("walks");
        let lifts: Vec<u128> = curve
            .points
            .iter()
            .map(|point| point.hurdle.mark_lift.bps_floor().expect("bps"))
            .collect();
        assert!(
            lifts.windows(2).all(|pair| pair[1] >= pair[0]),
            "{id}: the hurdle must be non-decreasing in size, saw {lifts:?}"
        );
        let first = *lifts.first().expect("points");
        let last = *lifts.last().expect("points");
        assert!(
            last >= first * 4,
            "{id}: the hurdle must climb materially over the ladder, {first} to {last}"
        );
    }
}

#[test]
fn the_hurdle_floor_is_twice_the_venue_fee_and_the_two_venues_differ_by_four_times() {
    // The floor of the hurdle, at a size small enough that traversal vanishes, is the two fees.
    // The bonding curve charges 125 bps a leg and the graduated pool 30, so their floors differ by
    // roughly four times before depth is even considered.
    let curve_floor = CostCurve::walk(
        &state("pump_curve", VenueFormula::PumpBondingCurve),
        &[LAMPORTS_PER_SOL / 100],
        &DeclaredFixedCosts::none("venue only"),
    )
    .expect("walks")
    .points[0]
        .hurdle
        .mark_lift
        .bps_ceil()
        .expect("bps");
    let swap_floor = CostCurve::walk(
        &state("pumpswap", VenueFormula::PumpSwapExactQuoteIn),
        &[LAMPORTS_PER_SOL / 100],
        &DeclaredFixedCosts::none("venue only"),
    )
    .expect("walks")
    .points[0]
        .hurdle
        .mark_lift
        .bps_ceil()
        .expect("bps");
    assert!(
        (250..=270).contains(&curve_floor),
        "curve floor {curve_floor}"
    );
    assert!(
        (55..=70).contains(&swap_floor),
        "pumpswap floor {swap_floor}"
    );
    assert!(curve_floor >= swap_floor * 4);
}

#[test]
fn the_other_side_of_the_hurdle_is_how_much_other_people_have_to_buy() {
    // The same hurdle read as a flow rather than as a price: the net quote inflow from everybody
    // else that makes the round trip free. It is close to fee rate times the effective quote
    // reserve, and it moves only slowly with clip size until the clip approaches the reserve.
    for (id, formula, expect_sol) in [
        ("pump_curve", VenueFormula::PumpBondingCurve, 0_u128),
        ("pumpswap", VenueFormula::PumpSwapExactQuoteIn, 4),
    ] {
        let state = state(id, formula);
        let costs = DeclaredFixedCosts::none("venue only");
        let curve = CostCurve::walk(&state, &ladder(&state), &costs).expect("walks");
        let smallest = curve.points[0].hurdle.other_net_quote_inflow_atoms;
        assert_eq!(smallest / LAMPORTS_PER_SOL, expect_sol);
        let approximation = state.effective_quote_atoms
            * u128::from(
                state.schedule.lp.get()
                    + state.schedule.protocol.get()
                    + match state.schedule.creator {
                        CreatorFee::Charged(rate) => rate.get(),
                        _ => 0,
                    },
            )
            / 10_000;
        let ratio = smallest * 100 / approximation;
        assert!(
            (95..=110).contains(&ratio),
            "{id}: inflow {smallest} vs fee-times-reserve {approximation}"
        );
    }
}

#[test]
fn fixed_network_cost_dominates_a_dust_clip_and_vanishes_on_a_real_one() {
    // Two landed transactions at the fee actually observed on this pool. At a thousandth of a SOL
    // the network is most of the cost; at one SOL it is a rounding error. This is why a cost
    // measured on dust trades cannot be reused at an operator's real clip, in either direction.
    let state = state("pumpswap", VenueFormula::PumpSwapExactQuoteIn);
    let costs = observed_costs(
        5_239,
        "two landed PumpSwap transactions on this pool, 5239 lamports each",
    );
    let bare = DeclaredFixedCosts::none("venue only, stated control");
    let hurdle = |clip: u128, costs: &DeclaredFixedCosts| {
        CostCurve::walk(&state, &[clip], costs)
            .expect("walks")
            .points[0]
            .hurdle
            .mark_lift
            .bps_ceil()
            .expect("bps")
    };
    let dust = LAMPORTS_PER_SOL / 1_000;
    let (dust_all_in, dust_venue) = (hurdle(dust, &costs), hurdle(dust, &bare));
    let (real_all_in, real_venue) = (
        hurdle(LAMPORTS_PER_SOL, &costs),
        hurdle(LAMPORTS_PER_SOL, &bare),
    );
    assert!(
        dust_all_in - dust_venue > dust_venue,
        "on a thousandth of a SOL the network should cost more than the venue does, \
         saw {dust_venue} bps of venue and {} bps of network",
        dust_all_in - dust_venue
    );
    assert!(
        real_all_in - real_venue <= 2,
        "at one SOL the network should be within two basis points, saw {}",
        real_all_in - real_venue
    );
}

#[test]
fn print_the_surface_for_both_venues() {
    let curve = print_surface(
        "Pump bonding curve, mint BKdJofyhtW3sBgC8PGuXaawKHmrPjTdzxqaJfSpupump, slot 440832401",
        &state("pump_curve", VenueFormula::PumpBondingCurve),
        &observed_costs(
            10_291,
            "one landed bonding-curve transaction, 10291 lamports; the same transaction also paid a \
             flat 1000000 lamport route charge that is not counted here",
        ),
    );
    let swap = print_surface(
        "PumpSwap pool 7njsrpwivXWJYYTRbpJJ1UhfnjQHrhovuMbY6GLFfbBg, slot 440832401",
        &state("pumpswap", VenueFormula::PumpSwapExactQuoteIn),
        &observed_costs(
            5_239,
            "two landed PumpSwap transactions on this pool, 5239 lamports each",
        ),
    );
    for (name, found) in [
        ("pump curve", curve.knee(2).expect("knee")),
        ("pumpswap", swap.knee(2).expect("knee")),
    ] {
        match found {
            Some(point) => println!(
                "\n  {name}: hurdle first doubles off its floor at a clip of {}.{:06} SOL \
                 ({} bps of the effective quote reserve)",
                point.hurdle.clip_quote_in_atoms / LAMPORTS_PER_SOL,
                (point.hurdle.clip_quote_in_atoms % LAMPORTS_PER_SOL) / 1_000,
                point
                    .hurdle
                    .clip_fraction_of_quote_reserve
                    .bps_floor()
                    .expect("bps"),
            ),
            None => println!("\n  {name}: the hurdle never doubles across this ladder"),
        }
    }
}

#[test]
fn which_clips_a_crackle_can_actually_carry() {
    // The operator's own question, inverted, at the bottom and the top of the lift range this
    // apparatus was built to study. With a real network fee the answer is an interval and not a
    // ceiling: too small and the fee eats the trade, too large and the curve does. Both ends are
    // gross break-even, not profit.
    for (name, id, formula, network) in [
        (
            "pump curve",
            "pump_curve",
            VenueFormula::PumpBondingCurve,
            10_291_u128,
        ),
        (
            "pumpswap",
            "pumpswap",
            VenueFormula::PumpSwapExactQuoteIn,
            5_239,
        ),
    ] {
        let state = state(id, formula);
        let costs = observed_costs(network, "network fee observed on a landed transaction");
        let sol = |atoms: u128| {
            format!(
                "{}.{:06}",
                atoms / LAMPORTS_PER_SOL,
                (atoms % LAMPORTS_PER_SOL) / 1_000
            )
        };
        let hurdle_at = |clip: u128| {
            joshi_liquidity::round_trip::crackle_hurdle(&state, clip, &costs)
                .map_or(u128::MAX, |hurdle| {
                    hurdle.mark_lift.bps_floor().expect("bps")
                })
        };
        for lift_bps in [800_u128, 2_000] {
            let range = joshi_liquidity::round_trip::feasible_clips_within_declared_lift(
                &state, lift_bps, &costs,
            )
            .expect("some clip fits");
            println!(
                "  {name}: a {lift_bps} bps lift breaks even for clips from {} to {} SOL \
                 (the top is {} bps of the effective quote reserve)",
                sol(range.smallest.clip_quote_in_atoms),
                sol(range.largest.clip_quote_in_atoms),
                range
                    .largest
                    .clip_fraction_of_quote_reserve
                    .bps_floor()
                    .expect("bps"),
            );
            assert!(range.smallest.clip_quote_in_atoms < range.largest.clip_quote_in_atoms);
            for end in [&range.smallest, &range.largest] {
                assert!(end.mark_lift.bps_floor().expect("bps") <= lift_bps);
            }
            // Both ends must be tight: one lamport outside either of them must not fit.
            assert!(
                hurdle_at(range.largest.clip_quote_in_atoms + 1) > lift_bps,
                "{name}: top of the range is not tight"
            );
            assert!(
                hurdle_at(range.smallest.clip_quote_in_atoms - 1) > lift_bps,
                "{name}: bottom of the range is not tight"
            );
        }
    }
}
