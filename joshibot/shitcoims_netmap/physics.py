"""The circuit identities, as *corrected* by studies/RESULT_circuit_model.md.

Every function here is one of the derived identities from that study. The two identities the
first pass of PROGRAM.md §8 got wrong are called out in the code, because the failure mode is
re-introducing them:

**Liquidity is a capacitance, not a conductance.** Price displacement scales with accumulated
charge (`V = Q/C`), not with current (`V = IR`). A pool that has absorbed net buying sits at a
displaced potential *with no current flowing*, which is a capacitor's defining behaviour and not
a resistor's. So there is no ``conductance()`` in this module and there must never be one; the
only genuinely ohmic element in the model is the *behavioural* arbitrageur response, which is
the model's single free parameter and is not observable from any of this map's three feeds.

**The fee is a back-to-back diode pair, not an I²R resistor.** Fee dissipation is `f·|Φ|` —
linear in the value pushed, a constant fraction of throughput regardless of rate. That is
Coulomb friction, and it is what produces a *dead-zone*: a band of potential across which no
current flows at all, which no resistor ever does. :func:`fee_band_log` is that dead-zone.

Units, stated once: potentials and curls are natural logs of prices, reported in **bps** as
`1e4 x log`. Capacitance is in **dollars per unit of log-price**. Resistance in this module
means only `r_e ≡ 1/C_e`, the depth term of the arbitrage optimisation, in log-price per dollar
pushed — it is the capacitor's inverse, not an ohmic element, and it is named ``depth_term``
rather than ``resistance`` to keep that straight.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

#: An edge whose fill is an exact function of its two reserves: a nonlinear capacitor with
#: ``C(V) = Q(V)/2``, hence ``C = TVL/4`` at even weights.
ELEMENT_CAPACITOR: Final[str] = "capacitor"

#: A Meteora DLMM edge. Inside a bin the pool is constant-*sum*: `dV = 0` while `dQ ≠ 0`, so
#: `C = ∞`; at a bin edge `dQ = 0` while `dV = δ`, so `C = 0`. An element with locally infinite
#: capacitance at a fixed potential holding finite charge is an ideal voltage source with finite
#: capacity — a battery cell — and a DLMM is a series stack of them at EMFs spaced `δ` apart.
#: Coarse-grained: `C̄ = TVL / W`, with `W` the log-width the liquidity spans.
ELEMENT_BATTERY_STACK: Final[str] = "battery_cell_stack"

#: The fee element on every edge, both DEXes. Forward drop `f` per crossing, in either
#: direction, hence *back-to-back*.
ELEMENT_DIODE_PAIR: Final[str] = "back_to_back_diode_pair"

#: `W` for a constant-product pool: `C = TVL/4` is exactly `C = TVL/W` at `W = 4`.
CPMM_SPAN: Final[float] = 4.0

#: The DLMM concentration knob, unobservable from any keyless endpoint (study §2.2). `4.0`
#: reproduces the constant-product depth — the pessimistic, no-concentration bound — and a
#: realistic concentrated position is 0.2-0.8. Every DLMM-dependent number is reported as the
#: interval over this range rather than as a point estimate.
DLMM_SPAN_WIDE: Final[float] = 4.0
DLMM_SPAN_TIGHT: Final[float] = 0.2

#: A three-leg atomic route at the config's priority-fee cap, at ~$76/SOL (study §3.3).
DEFAULT_GAS_USD: Final[float] = 0.30


def bps(log_value: float) -> float:
    """A log-price quantity in basis points. The whole map reports curls and bands this way."""

    return 1e4 * log_value


@dataclass(frozen=True, slots=True)
class Fee:
    """The total swap fee skimmed on ONE leg, as a fraction of the input.

    ``taker`` is what a cycle arbitrageur actually pays: LP + protocol + creator. ``lp_share``
    is the fraction of it that reaches a liquidity provider, which is a different question and
    is the one that matters for "should we own this edge".
    """

    taker: float
    lp_share: float
    source: str
    uncertain: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "taker_bps": round(1e4 * self.taker, 2),
            "lp_share": round(self.lp_share, 4),
            "lp_bps": round(1e4 * self.taker * self.lp_share, 2),
            "source": self.source,
            "uncertain": self.uncertain,
            "element": ELEMENT_DIODE_PAIR,
            "dissipation": "f·|flow| — linear in the value pushed, NOT I²R",
        }


#: PumpSwap LP + protocol, from pump.fun's public docs repo as relayed in studies/circuit_model.py.
#: Not read from chain here, so it stays flagged uncertain rather than promoted to a measurement.
PUMPSWAP_LP_PROTOCOL: Final[float] = 0.0025

#: The creator-fee ladder, **read from the pump.fun fee program's own ``FeeConfig`` account**
#: ``5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx`` (owner ``pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ``)
#: on 2026-08-15 and verified against 1,058 decoded swaps across four pools with zero misses —
#: ``studies/RESULT_dregg_boundary.md``.
#:
#: This constant REPLACES a three-step ladder in **USD FDV** (0.95% under $300k, 0.60% to $1M,
#: 0.35% above) that this module and ``PROGRAM.md`` §0 both carried. That ladder was wrong in
#: three ways at once and every one of them mattered: the real schedule has **25 rungs 5 bps
#: apart**, the threshold is a market cap in **lamports** so each rung's dollar value moves with
#: the SOL price, and the bottom rung is a **cliff** — under 420 SOL of market cap the creator
#: takes 30 bps while the protocol takes 93.
#:
#: It is a SNAPSHOT and it will rot: pump.fun has changed this schedule before (Project Ascend,
#: 2025-09-01) and has said publicly it intends to again. Re-read the account rather than
#: trusting this tuple; ``studies/dregg_boundary.py:fee_config_raw`` does it in one RPC call.
#: (threshold in SOL of market cap, creator fee rate)
PUMPSWAP_CREATOR_TIERS_SOL: Final[tuple[tuple[float, float], ...]] = (
    (0.0, 0.0030), (420.0, 0.0095), (1_470.0, 0.0090), (2_460.0, 0.0085),
    (3_440.0, 0.0080), (4_420.0, 0.0075), (9_820.0, 0.0070), (14_740.0, 0.0065),
    (19_650.0, 0.0060), (24_560.0, 0.0055), (29_470.0, 0.0050), (34_380.0, 0.0045),
    (39_300.0, 0.0040), (44_210.0, 0.0035), (49_120.0, 0.0030), (54_030.0, 0.0028),
    (58_940.0, 0.0025), (63_860.0, 0.0023), (68_770.0, 0.0020), (73_681.0, 0.0018),
    (78_590.0, 0.0015), (83_500.0, 0.0013), (88_400.0, 0.0010), (93_330.0, 0.0008),
    (98_240.0, 0.0005),
)

#: Only used to translate a vendor's USD FDV into the SOL market cap the program actually reads.
#: A snapshot, and the reason :func:`pumpswap_fee` stays ``uncertain``: near a rung the tier
#: depends on the SOL price to two significant figures.
SOL_USD_REFERENCE: Final[float] = 75.449


def creator_fee_at_mcap_sol(mcap_sol: float) -> float:
    """The creator fee the program applies at this market cap, in SOL.

    pump.fun's own reference implementation, from ``docs/FEE_PROGRAM_README.md``::

        poolMarketCap = quoteReserve * baseMintSupply / baseReserve
        take the last tier whose marketCapLamportsThreshold is <= marketCap

    Evaluated fresh on every swap from live reserves — no TWAP, no oracle, no hysteresis, and
    no high-water mark. Measured: DREGG's applied rate flipped 80→75→80→75 bps inside four
    seconds on 2026-08-14, which no averaged or ratcheted input can produce.
    """

    rate = PUMPSWAP_CREATOR_TIERS_SOL[0][1]
    for threshold, r in PUMPSWAP_CREATOR_TIERS_SOL:
        if mcap_sol >= threshold:
            rate = r
    return rate


def pumpswap_fee(fdv_usd: float, *, sol_usd: float = SOL_USD_REFERENCE) -> Fee:
    """PumpSwap taker fee at this FDV.

    The FDV argument is kept because that is what the vendor quotes serve, but note that **USD
    is the wrong unit for this decision**: the program's thresholds are in lamports, so a token
    can change fee tier with no price move at all if SOL moves. Anything making a tier-boundary
    decision should carry market cap in SOL and call :func:`creator_fee_at_mcap_sol` directly.
    """

    mcap_sol = fdv_usd / sol_usd if sol_usd else 0.0
    creator = creator_fee_at_mcap_sol(mcap_sol)
    taker = PUMPSWAP_LP_PROTOCOL + creator
    return Fee(
        taker=taker,
        lp_share=PUMPSWAP_LP_PROTOCOL / taker if taker else 0.0,
        source=(
            f"creator {creator:.2%} from the on-chain FeeConfig tier table at "
            f"{mcap_sol:,.0f} SOL of market cap (FDV=${fdv_usd:,.0f} / ${sol_usd:,.2f} per SOL); "
            f"LP+protocol {PUMPSWAP_LP_PROTOCOL:.2%} from pump.fun public docs, not read from chain"
        ),
        uncertain=True,
    )


#: Used only when the DLMM pool endpoint does not answer. The study swept 0.20-5.00% precisely
#: because nothing keyless served the real number; this map prefers the served number when it
#: has one (see :func:`dlmm_fee`) and falls back to the swept midpoint, flagged, when it does not.
DLMM_FEE_FALLBACK: Final[float] = 0.0100


def dlmm_fee(base_pct: float | None = None, dynamic_pct: float | None = None) -> Fee:
    """DLMM taker fee from the pool's own config when served, else the swept midpoint.

    ``dlmm.datapi.meteora.ag/pools/{addr}`` returns ``pool_config.base_fee_pct`` and a live
    ``dynamic_fee_pct``; both are percentages. The taker pays their sum. This closes — for the
    pools that endpoint knows — the unknown the study had to sweep, and the map records which
    of the two it used, because the fee band *is* the result.

    **The percent reading is cross-checked, loosely, against our own income.** On 2026-08-13 the
    weave/nosis pool served ``base 6.0% + dynamic 0.71%`` while our position (96% of that pool's
    TVL) had accrued $68 of lifetime fees against roughly $700 of 24h flow measured independently
    from the tape — an implied ~10%, the same order as 6.71% and an order away from 0.671%. That
    is a sanity check at ~1.5x precision, not a verification: it does not pin the units, and the
    honest fix is reading the ``lb_pair`` account.
    """

    if base_pct is None:
        return Fee(
            taker=DLMM_FEE_FALLBACK,
            lp_share=1.0,
            source=f"DLMM fee {DLMM_FEE_FALLBACK:.2%} ASSUMED (pool config not served); study §3.2 sweep",
            uncertain=True,
        )
    dynamic = dynamic_pct or 0.0
    taker = (base_pct + dynamic) / 100.0
    return Fee(
        taker=taker,
        lp_share=1.0,  # protocol_fee_pct is a cut of the fee; the LP keeps the rest.
        source=f"meteora pool_config base {base_pct:.3f}% + dynamic {dynamic:.3f}% (served, not assumed)",
        uncertain=False,
    )


def capacitance_usd(tvl_usd: float, *, weight_base: float = 0.5) -> float:
    """`C = w_x·w_y·TVL` — dollars per unit of log-price. `TVL/4` at even weights.

    Derived, not analogised: with `V ≡ ln p` and `Q ≡ y`, a geometric-mean pool has
    `V = const + (ln y)/w_x`, hence `C ≡ dQ/dV = w_x·y = w_x·w_y·TVL`. Verified numerically
    against brute-force perturbation of the invariant to 6 significant figures (study §2.1).
    Maximised at 50/50: skewing the weights makes a pool *less* capacitive at its own price.
    """

    if tvl_usd <= 0 or not (0.0 < weight_base < 1.0):
        return 0.0
    return weight_base * (1.0 - weight_base) * tvl_usd


def dlmm_capacitance_bounds(
    tvl_usd: float,
    *,
    span_tight: float = DLMM_SPAN_TIGHT,
    span_wide: float = DLMM_SPAN_WIDE,
) -> tuple[float, float]:
    """Coarse-grained `C̄ = TVL / W` for a battery stack, as the (low, high) interval over `W`.

    `W` — the log-width the position spans — is not observable from any keyless endpoint, so a
    point estimate here would be a fabrication. Wide `W` (no concentration) gives the low bound
    and coincides with the constant-product value; tight `W` gives the high one, the 5-20x
    concentration factor of study §2.2.
    """

    if tvl_usd <= 0:
        return (0.0, 0.0)
    return (tvl_usd / span_wide, tvl_usd / span_tight)


def depth_term(tvl_usd: float, *, span: float) -> float:
    """`r_e ≡ 1/C_e = W_e / TVL_e`: log-price moved per dollar pushed through the edge.

    This is the inverse of a capacitance and NOT an ohmic resistance — it is the `½C(ΔV)²`
    price-impact term of the arbitrage optimisation. A thin edge has a huge `r_e`, which is why
    a thin pool *destroys* an arbitrage rather than creating one (study §3.3).
    """

    if tvl_usd <= 0:
        return math.inf
    return span / tvl_usd


def fee_band_log(fees: list[Fee] | tuple[Fee, ...]) -> float:
    """Half-width of the diode dead-zone: `Σ_e ln(1/(1-f_e))`, in log-price units.

    An arbitrageur sending notional around a loop receives `exp(curl)·Π(1-f_e)` per unit, so
    trading is profitable only outside this band. The band edges *are* the fee sum, exactly, in
    the zero-size limit — forward drops adding in series, one diode per leg.
    """

    total = 0.0
    for fee in fees:
        if fee.taker >= 1.0:
            return math.inf
        total += math.log(1.0 / (1.0 - fee.taker))
    return total


def curl_log(legs: list[tuple[float, int]] | tuple[tuple[float, int], ...]) -> float | None:
    """`Σ orientation · ln price` around a cycle. ``None`` when a leg has no usable price.

    KVL ⟺ curl = 0 ⟺ log-price is a genuine node potential ⟺ no cycle arbitrage. This is the
    discrete curl of the log-price 1-form on the pool graph.
    """

    total = 0.0
    for price, orientation in legs:
        if price is None or price <= 0 or not math.isfinite(price):
            return None
        total += orientation * math.log(price)
    return total


def full_band_log(fee_band: float, sum_depth: float, gas_usd: float) -> float:
    """The band that decides whether money moves: `Σf + √(2·G·Σr)` (study §3.3, ★).

    The fee sum alone answers "does an arbitrage exist". It does not answer "is it worth
    doing", and in this cluster the two differ by more than the first one is worth.
    """

    if not math.isfinite(sum_depth):
        return math.inf
    return fee_band + math.sqrt(2.0 * max(gas_usd, 0.0) * sum_depth)


def arb_value_usd(curl: float, fee_band: float, sum_depth: float, gas_usd: float) -> tuple[float, float]:
    """`(optimal notional, profit)` in dollars for this curl. Profit ≤ 0 means nobody trades.

    `profit(Φ) = Φ·(|C|-Σf) - ½Φ²·Σr - G`, maximised at `Φ* = (|C|-Σf)/Σr`. This is the number
    that must be printed next to every curl: the study measured the *largest* standing residual
    in this cluster as worth **$0.37-$9.86 per loop**, and a curl shown without it invites
    someone to trade noise.
    """

    edge = abs(curl) - fee_band
    if edge <= 0 or not math.isfinite(sum_depth) or sum_depth <= 0:
        return (0.0, -gas_usd)
    notional = edge / sum_depth
    return (notional, edge * edge / (2.0 * sum_depth) - gas_usd)
