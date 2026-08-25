"""Per-coin venue floor lookup from the retained fee-tier constants. No fee logic invented.

The tier rows below are the HEADS of the two tier vectors on the PumpSwap fee configuration
retained at slot 440840124, quoted verbatim from the tests of
``crates/joshi-liquidity/src/tier.rs`` (``retained_table_zero`` / ``retained_table_one``) —
the bytes, not a paraphrase. The two tables DISAGREE over a wide populated band and no
retained byte says which applies; per that module's ``TierBasis``, this study applies the
WORST of the disagreeing tables, which errs against the trade and never for it.

The retained heads stop at 2460 SOL (table zero) / 500 SOL (table one); the deployed ladders
continue with cheaper rows above. A market cap above a table's last retained threshold is
CLAMPED to that last row here and the result is labeled clamped — an overstatement of cost in
the unflattering direction, stated rather than smoothed.

The bonding-curve floor is Study M0's measured 247 bps round trip (the constant the
callout_entry_window study declared); the fee-tier ladder does not apply to a live curve.
"""

from __future__ import annotations

from dataclasses import dataclass

LAMPORTS_PER_SOL = 1_000_000_000

# (threshold_quote_atoms, leg_bps) — lp + protocol + creator per leg, verbatim from tier.rs.
TABLE_ZERO: tuple[tuple[int, int], ...] = (
    (0, 125),
    (420 * LAMPORTS_PER_SOL, 120),
    (1_470 * LAMPORTS_PER_SOL, 115),
    (2_460 * LAMPORTS_PER_SOL, 110),
)
TABLE_ONE: tuple[tuple[int, int], ...] = (
    (0, 125),
    (59 * LAMPORTS_PER_SOL, 120),
    (300 * LAMPORTS_PER_SOL, 115),
    (500 * LAMPORTS_PER_SOL, 110),
)

CURVE_ROUND_TRIP_BPS = 247


@dataclass(frozen=True)
class FloorLookup:
    """One coin's declared venue floor and how it was chosen."""

    round_trip_bps: int
    basis: str  # "curve_measured_m0" | "tier_worst_of_tables" | "tier_worst_of_tables_clamped"


def _leg_bps(table: tuple[tuple[int, int], ...], market_cap_quote_atoms: int) -> tuple[int, bool]:
    """Deployed selection: highest threshold not exceeding the cap, first row as fallback.

    Returns (leg_bps, clamped_at_table_top).
    """
    selected = table[0]
    for row in table:
        if row[0] <= market_cap_quote_atoms:
            selected = row
    clamped = selected == table[-1] and market_cap_quote_atoms > table[-1][0]
    return selected[1], clamped


def venue_floor(graduated: bool, market_cap_sol: float | None) -> FloorLookup:
    """The round-trip floor a coin's venue charges, per STUDY.md section 3.

    A graduated coin with no readable market cap gets the WORST retained rate (first row,
    125 bps a leg): an absent cap is never a cheap one.
    """
    if not graduated:
        return FloorLookup(round_trip_bps=CURVE_ROUND_TRIP_BPS, basis="curve_measured_m0")
    if market_cap_sol is None or market_cap_sol < 0:
        return FloorLookup(round_trip_bps=2 * 125, basis="tier_worst_of_tables")
    atoms = int(market_cap_sol * LAMPORTS_PER_SOL)
    leg_zero, clamp_zero = _leg_bps(TABLE_ZERO, atoms)
    leg_one, clamp_one = _leg_bps(TABLE_ONE, atoms)
    worst = max(leg_zero, leg_one)
    clamped = (clamp_zero and leg_zero >= leg_one) or (clamp_one and leg_one >= leg_zero)
    return FloorLookup(
        round_trip_bps=2 * worst,
        basis="tier_worst_of_tables_clamped" if clamped else "tier_worst_of_tables",
    )
