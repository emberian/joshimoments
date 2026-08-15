"""Decide WHICH bins, HOW MUCH, and WHAT IT COSTS -- before anything is built.

Two plans, both pure functions of chain state so they can be tested without a network.

THE TRIM. A DLMM position holds token X only in bins strictly above the active bin and
token Y only below, so "the nosis side" is not a fraction of the position -- it is a
contiguous, identifiable set of bins, and trimming nosis exposure is a bin-range choice.

Which end to cut from is the real decision and the answer is THE TOP. The bins nearest spot
are where the flow is; they earn fees and they are the ones that will convert. The bins at
the far end of the range are inventory parked at a price the market has not reached, earning
nothing -- `RESULT_lp_strategy.md` §11(c): "never let inventory sit outside a range", and the
top of a wide range is functionally outside it. So the retained $200 stays in the productive
bins and the withdrawn part leaves from the dead ones. The alternative -- a uniform bps
across every nosis bin -- is what an SDK makes easiest and it dilutes the good bins to spare
the bad ones.

THE LADDER. One-sided token X above spot on a token/SOL pool. `RESULT_lp_strategy.md` §10:
"dated cash should not sit in token-token pools" -- a token-token position needs two exit
legs and its fill direction is a bet on the ratio; a token/SOL position needs one and
converts to SOL automatically as price rises. `RESULT_toll_positioning.md` §4 measured the
resulting fills at +1.4-2.0% against routing the same flow through Jupiter.

Ladder width is chosen against three constraints at once, which is why it is a search and
not a constant:
  reach     the top rung should sit far enough above spot to be worth posting;
  atomicity MAX_BIN_LENGTH_ALLOWED_IN_ONE_TX is 26, and a ladder split across transactions
            is a ladder that can half-exist;
  rent      each new 70-bin array is 0.0714 SOL that never comes back, so a width that
            crosses an array boundary for one extra rung is a bad trade at this size.
`plan_ladder` enumerates candidate widths, prices each one's non-refundable rent against the
value being deployed, and picks the cheapest that reaches the target -- then reports the
runner-up so the choice is visible rather than asserted.

NOTHING HERE SIGNS, BUILDS, OR SENDS. The output is a description an operator can read and
a builder can execute, plus the rent bill, and every number in it is derived from a chain
read taken at plan time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .binmath import (
    BIN_ARRAY_RENT_LAMPORTS,
    LAMPORTS_PER_SOL,
    MAX_BINS_PER_TX,
    RentQuote,
    bin_array_indexes,
    bin_price_ui,
    quote_rent,
)

# A ladder whose non-refundable rent eats more than this share of what it deploys is not an
# execution improvement, it is a donation to the pool. 4% is roughly two-and-a-half times the
# measured +1.4-2.0% ladder edge, so above it the trade is negative before it starts.
MAX_RENT_SHARE_OF_DEPLOYED = 0.04

# Default reach of an ask ladder above spot. Wide enough that a normal day's range fills
# several rungs, tight enough that the whole ladder is live inventory rather than a wish.
DEFAULT_LADDER_REACH_PCT = 20.0


class PlanRefused(ValueError):
    """The plan is unsound. Raised before anything is built, never caught to retry."""


@dataclass(frozen=True, slots=True)
class BinHolding:
    bin_id: int
    price_per_token: float
    amount_x_raw: int
    amount_y_raw: int


@dataclass(frozen=True, slots=True)
class RemoveStep:
    """One `remove_liquidity(from_bin_id, to_bin_id, bps)` call.

    `bps` is per-bin: 10_000 empties every bin in the range. A trim that lands on a fraction
    of a bin therefore needs two steps -- the whole bins, then the partial one -- rather than
    one averaged call, because averaging would pull from bins we chose to keep.
    """

    from_bin_id: int
    to_bin_id: int
    bps: int
    expected_x_raw: int
    expected_y_raw: int
    reason: str


@dataclass(frozen=True, slots=True)
class TrimPlan:
    pool: str
    position: str
    token_x_symbol: str
    active_bin_id: int
    bin_step: int
    decimals_x: int
    held_x_raw: int
    held_x_usd: float
    target_x_usd: float
    remove_x_raw: int
    remove_x_usd: float
    retained_x_raw: int
    retained_x_usd: float
    steps: tuple[RemoveStep, ...]
    price_x_usd: float
    rent: RentQuote
    notes: tuple[str, ...] = ()

    @property
    def removed_bin_ids(self) -> tuple[int, ...]:
        out: list[int] = []
        for step in self.steps:
            out.extend(range(step.from_bin_id, step.to_bin_id + 1))
        return tuple(sorted(set(out)))


@dataclass(frozen=True, slots=True)
class LadderRung:
    bin_id: int
    price_ui: float
    price_usd: float
    amount_x_raw: int
    pct_above_spot: float


@dataclass(frozen=True, slots=True)
class LadderPlan:
    pool: str
    label: str
    token_x_symbol: str
    token_y_symbol: str
    active_bin_id: int
    bin_step: int
    decimals_x: int
    decimals_y: int
    min_bin_id: int
    max_bin_id: int
    deposit_x_raw: int
    deposit_x_usd: float
    rungs: tuple[LadderRung, ...]
    rent: RentQuote
    rent_share_of_deposit: float
    spot_price_ui: float
    reach_pct: float
    alternatives: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = ()


def _raw_to_ui(raw: int, decimals: int) -> float:
    return raw / (10.0**decimals)


def _ui_to_raw(ui: float, decimals: int) -> int:
    return int(ui * (10.0**decimals))


def plan_trim(
    *,
    pool: str,
    position: str,
    bins: list[BinHolding],
    active_bin_id: int,
    bin_step: int,
    decimals_x: int,
    price_x_usd: float,
    target_x_usd: float,
    token_x_symbol: str = "X",
    existing_bin_arrays: frozenset[int] | None = None,
) -> TrimPlan:
    """Remove token-X liquidity from the TOP of the range until exposure reaches the target.

    Removal reclaims nothing and creates nothing, so its rent is zero -- but the quote is
    still produced and reported so that "this step is rent-free" is a stated fact rather
    than an omission the reader has to infer.
    """
    if price_x_usd <= 0:
        raise PlanRefused("token price must be positive to size a trim")
    if target_x_usd < 0:
        raise PlanRefused("target exposure cannot be negative")

    x_bins = sorted((b for b in bins if b.amount_x_raw > 0), key=lambda b: b.bin_id)
    if not x_bins:
        raise PlanRefused(f"position {position} holds no {token_x_symbol}; nothing to trim")

    held_raw = sum(b.amount_x_raw for b in x_bins)
    held_usd = _raw_to_ui(held_raw, decimals_x) * price_x_usd
    notes: list[str] = []

    if held_usd <= target_x_usd:
        notes.append(
            f"held ${held_usd:,.2f} is already at or below the ${target_x_usd:,.2f} target; "
            "no removal planned"
        )
        return TrimPlan(
            pool=pool,
            position=position,
            token_x_symbol=token_x_symbol,
            active_bin_id=active_bin_id,
            bin_step=bin_step,
            decimals_x=decimals_x,
            held_x_raw=held_raw,
            held_x_usd=held_usd,
            target_x_usd=target_x_usd,
            remove_x_raw=0,
            remove_x_usd=0.0,
            retained_x_raw=held_raw,
            retained_x_usd=held_usd,
            steps=(),
            price_x_usd=price_x_usd,
            rent=quote_rent(
                lower_bin_id=active_bin_id,
                upper_bin_id=active_bin_id,
                existing_bin_arrays=existing_bin_arrays or frozenset(),
                opens_position=False,
            ),
            notes=tuple(notes),
        )

    want_usd = held_usd - target_x_usd
    want_raw = _ui_to_raw(want_usd / price_x_usd, decimals_x)

    # Walk down from the top bin, taking whole bins while they fit.
    taken = 0
    full_from: int | None = None
    partial: tuple[int, int] | None = None  # (bin_id, raw amount still needed)
    for holding in reversed(x_bins):
        remaining = want_raw - taken
        if remaining <= 0:
            break
        if holding.amount_x_raw <= remaining:
            taken += holding.amount_x_raw
            full_from = holding.bin_id
        else:
            partial = (holding.bin_id, remaining)
            taken += remaining
            break

    steps: list[RemoveStep] = []
    top_bin = x_bins[-1].bin_id
    if full_from is not None:
        whole = sum(b.amount_x_raw for b in x_bins if full_from <= b.bin_id <= top_bin)
        steps.append(
            RemoveStep(
                from_bin_id=full_from,
                to_bin_id=top_bin,
                bps=10_000,
                expected_x_raw=whole,
                expected_y_raw=sum(b.amount_y_raw for b in x_bins if full_from <= b.bin_id <= top_bin),
                reason=(
                    f"empty bins {full_from}..{top_bin} -- the far end of the range, inventory "
                    "parked above where the flow is"
                ),
            )
        )
    if partial is not None:
        bin_id, needed = partial
        holding = next(b for b in x_bins if b.bin_id == bin_id)
        # Round the bps UP so the trim reaches the target rather than stopping just short;
        # overshooting by a fraction of one bin is the harmless direction.
        bps = min(10_000, math.ceil(needed * 10_000 / holding.amount_x_raw))
        actual = holding.amount_x_raw * bps // 10_000
        steps.append(
            RemoveStep(
                from_bin_id=bin_id,
                to_bin_id=bin_id,
                bps=bps,
                expected_x_raw=actual,
                expected_y_raw=holding.amount_y_raw * bps // 10_000,
                reason=f"take {bps / 100:.2f}% of bin {bin_id} to land on the target",
            )
        )
        taken = taken - needed + actual

    if not steps:
        raise PlanRefused("trim resolved to no removal despite being above target; refusing to guess")

    remove_raw = sum(step.expected_x_raw for step in steps)
    remove_usd = _raw_to_ui(remove_raw, decimals_x) * price_x_usd
    retained_raw = held_raw - remove_raw

    if steps and steps[0].from_bin_id <= active_bin_id:
        notes.append(
            f"removal reaches the active bin {active_bin_id}, which holds both tokens; the "
            "step will also withdraw its token-Y share"
        )

    return TrimPlan(
        pool=pool,
        position=position,
        token_x_symbol=token_x_symbol,
        active_bin_id=active_bin_id,
        bin_step=bin_step,
        decimals_x=decimals_x,
        held_x_raw=held_raw,
        held_x_usd=held_usd,
        target_x_usd=target_x_usd,
        remove_x_raw=remove_raw,
        remove_x_usd=remove_usd,
        retained_x_raw=retained_raw,
        retained_x_usd=_raw_to_ui(retained_raw, decimals_x) * price_x_usd,
        steps=tuple(steps),
        price_x_usd=price_x_usd,
        # Removing from an existing position touches only accounts that already exist.
        rent=quote_rent(
            lower_bin_id=steps[0].from_bin_id,
            upper_bin_id=steps[-1].to_bin_id if steps[-1].to_bin_id > steps[0].from_bin_id else top_bin,
            existing_bin_arrays=frozenset(
                bin_array_indexes(steps[0].from_bin_id, top_bin)
            ),
            opens_position=False,
        ),
        notes=tuple(notes),
    )


def _ladder_candidate(
    *,
    active_bin_id: int,
    bin_step: int,
    width: int,
    existing_bin_arrays: frozenset[int],
    deposit_usd: float,
) -> dict[str, Any]:
    lower = active_bin_id + 1
    upper = lower + width - 1
    rent = quote_rent(
        lower_bin_id=lower,
        upper_bin_id=upper,
        existing_bin_arrays=existing_bin_arrays,
        opens_position=True,
    )
    reach = ((1.0 + bin_step / 10_000.0) ** width - 1.0) * 100.0
    share = rent.non_refundable / LAMPORTS_PER_SOL if deposit_usd <= 0 else 0.0
    return {
        "width": width,
        "min_bin_id": lower,
        "max_bin_id": upper,
        "reach_pct": reach,
        "new_bin_arrays": list(rent.new_bin_arrays),
        "non_refundable_lamports": rent.non_refundable,
        "rent": rent,
        "_share_placeholder": share,
    }


def plan_ladder(
    *,
    pool: str,
    label: str,
    active_bin_id: int,
    bin_step: int,
    decimals_x: int,
    decimals_y: int,
    deposit_x_raw: int,
    price_x_usd: float,
    sol_price_usd: float,
    existing_bin_arrays: frozenset[int],
    reach_pct: float = DEFAULT_LADDER_REACH_PCT,
    token_x_symbol: str = "X",
    token_y_symbol: str = "Y",
    max_width: int = MAX_BINS_PER_TX,
) -> LadderPlan:
    """Choose the ladder range, then price it. Refuses a ladder that rent makes negative."""
    if deposit_x_raw <= 0:
        raise PlanRefused("a ladder needs something to deposit")
    if bin_step <= 0:
        raise PlanRefused("bin step must be positive")

    deposit_usd = _raw_to_ui(deposit_x_raw, decimals_x) * price_x_usd

    # The narrowest width that reaches the target, then everything up to the atomicity cap.
    step_ratio = 1.0 + bin_step / 10_000.0
    needed = max(1, math.ceil(math.log1p(reach_pct / 100.0) / math.log(step_ratio)))
    candidates = [
        _ladder_candidate(
            active_bin_id=active_bin_id,
            bin_step=bin_step,
            width=width,
            existing_bin_arrays=existing_bin_arrays,
            deposit_usd=deposit_usd,
        )
        for width in range(needed, min(max_width, needed + 12) + 1)
    ]
    if not candidates:
        raise PlanRefused(
            f"a ladder reaching +{reach_pct:.1f}% needs {needed} bins at bin step {bin_step}, "
            f"above the {max_width}-bin single-transaction limit"
        )

    # Cheapest non-refundable rent wins; ties break toward the NARROWER ladder.
    #
    # Free extra reach is tempting and wrong. Every extra rung takes inventory out of the
    # bins that will actually trade and parks it at a price the market has not reached --
    # the same "never let inventory sit outside a range" failure the trim step exists to
    # undo, reintroduced at the other end. A tight ladder that just clears the reach target
    # fills sooner and concentrates the fee capture where the flow is.
    chosen = min(candidates, key=lambda c: (c["non_refundable_lamports"], c["width"]))
    rent: RentQuote = chosen["rent"]

    rent_usd = rent.non_refundable / LAMPORTS_PER_SOL * sol_price_usd
    share = rent_usd / deposit_usd if deposit_usd > 0 else float("inf")
    if share > MAX_RENT_SHARE_OF_DEPLOYED:
        raise PlanRefused(
            f"ladder would pay ${rent_usd:,.2f} of non-refundable bin-array rent to deploy "
            f"${deposit_usd:,.2f} ({share:.1%} > {MAX_RENT_SHARE_OF_DEPLOYED:.0%}). Every "
            f"candidate width needs a virgin bin array; deploy more, or wait for someone else "
            f"to open the range."
        )

    lower = int(chosen["min_bin_id"])
    upper = int(chosen["max_bin_id"])
    width = upper - lower + 1
    per_rung = deposit_x_raw // width
    spot = bin_price_ui(active_bin_id, bin_step, decimals_x=decimals_x, decimals_y=decimals_y)

    rungs: list[LadderRung] = []
    for offset, bin_id in enumerate(range(lower, upper + 1)):
        price = bin_price_ui(bin_id, bin_step, decimals_x=decimals_x, decimals_y=decimals_y)
        amount = per_rung + (deposit_x_raw - per_rung * width if offset == width - 1 else 0)
        rungs.append(
            LadderRung(
                bin_id=bin_id,
                price_ui=price,
                price_usd=price * sol_price_usd if decimals_y == 9 else price,
                amount_x_raw=amount,
                pct_above_spot=(price / spot - 1.0) * 100.0 if spot > 0 else 0.0,
            )
        )

    notes: list[str] = []
    if not rent.new_bin_arrays:
        notes.append("every bin array in the range already exists: no non-refundable rent")
    else:
        notes.append(
            f"{len(rent.new_bin_arrays)} virgin bin array(s) at "
            f"{BIN_ARRAY_RENT_LAMPORTS / LAMPORTS_PER_SOL:.6f} SOL each, never refunded"
        )
    notes.append(
        f"Spot distribution: {_raw_to_ui(per_rung, decimals_x):,.0f} {token_x_symbol} per rung "
        f"across {width} rungs"
    )

    alternatives = tuple(
        {
            "width": c["width"],
            "reach_pct": round(float(c["reach_pct"]), 2),
            "new_bin_arrays": c["new_bin_arrays"],
            "non_refundable_sol": round(c["non_refundable_lamports"] / LAMPORTS_PER_SOL, 6),
        }
        for c in candidates
        if c["width"] != width
    )

    return LadderPlan(
        pool=pool,
        label=label,
        token_x_symbol=token_x_symbol,
        token_y_symbol=token_y_symbol,
        active_bin_id=active_bin_id,
        bin_step=bin_step,
        decimals_x=decimals_x,
        decimals_y=decimals_y,
        min_bin_id=lower,
        max_bin_id=upper,
        deposit_x_raw=deposit_x_raw,
        deposit_x_usd=deposit_usd,
        rungs=tuple(rungs),
        rent=rent,
        rent_share_of_deposit=share,
        spot_price_ui=spot,
        reach_pct=float(chosen["reach_pct"]),
        alternatives=alternatives,
        notes=tuple(notes),
    )
