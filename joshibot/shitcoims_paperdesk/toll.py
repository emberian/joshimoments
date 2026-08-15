"""The TOLL book: paper DLMM positions, gated on ``eta * D > VR``, fees from real flow.

WHAT THIS BOOK IS AND IS NOT
----------------------------
It is a paper liquidity book. It opens a Spot-shape range around the observed price of a
cluster pool, accrues fees from swaps that ACTUALLY CROSSED that range on the tape,
tracks the duty cycle, redeploys one-sided when price leaves the range, and closes on the
gate or the horizon. It never assumes a fee rate, never assumes a volume, and never
assumes the position was in range.

It is NOT a claim that the flow it observes would have routed to it. On a SOL-quoted
PumpSwap pool the observed swaps chose PumpSwap; a paper DLMM range alongside would have
captured some fraction of them, not all. So every accrual row carries
``flow_attribution="observed_venue_flow_upper_bound"``, and the reported fee income is an
upper bound on that pool. On the token-token DLMM pools the flow IS the pool's own flow
and the attribution is exact -- those rows say so.

THE DECISION RULE, EXACT
------------------------
From ``studies/RESULT_circuit_theory.md`` §4.2 and ``RESULT_lp_strategy.md`` §2::

    LP net > 0    <=>    eta * D > VR(T)

    eta   = 2 f N / (C * RV)     churn number: fee income in LVR units
    VR(T) = (dV_T)^2 / RV_T      Lo-MacKinlay variance ratio at the holding horizon
    D     = duty cycle           fraction of position life spent in range
    C     = T / W                capacitance of a DLMM position: value over log-width

    D* = VR / eta                the duty cycle a pool REQUIRES to break even

Two consequences this book is built around, both of which cost real money to learn:

**Concentration cannot rescue a -EV pool.** ``C = T/W`` multiplies BOTH terms of the
ledger, so narrowing the range scales the answer by ``4/W`` and preserves its sign. It
levers the loss exactly as hard as the gain. Measured on the operator's own position:
``W = 4.0`` gave ``eta = 2.36-2.80``; the same pool, same flow, at ``W = 1.005`` gave
``eta = 0.59-0.70``. Narrowing made it worse.

**Duty cycle is the whole game.** DREGG/nosis harvested BETTER per hour than weave/nosis
(67.6%/day vs 57.6%/day) and still lost $215.63, because it ran a **49.4%** duty cycle
against weave/nosis's **99.4%**. Hence the rebalance rule: never sit out of range, and
redeploy ONE-SIDED rather than swapping -- one-sided captures 87-95% of the fee income at
1/50th to 1/80th the cost ($1.31-1.72 vs $93-119 over three days), because a swap
re-center pays 2.88% round trip (two 1.44% PumpSwap taker legs, NOT the 0.20% LP leg).

WHAT THE DESK EXPECTS TO FIND
-----------------------------
Every measured eta in this cluster is below 1 -- 0.055 to 0.235 on the SOL pools, 0.59 to
1.08 on the live DLMM -- against VR near 1 at the holding horizon. The gate should refuse
almost everything. That is a prediction this book is here to test, not an assumption it
encodes: the epsilon-explore arm opens positions the gate refused, and those are the only
rows that can ever falsify it.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Final

from shitcoims_cluster.pools import CLUSTER_POOLS, WSOL_MINT
from shitcoims_paperdesk import Book
from shitcoims_paperdesk.feeds import PoolSwap
from shitcoims_paperdesk.friction import (
    LAMPORTS_PER_SOL,
    PROTOCOL_FEE_SHARE,
    PUMPSWAP_LP_FEE,
    Friction,
)
from shitcoims_paperdesk.ledger import Ledger, close_row, iso
from shitcoims_paperdesk.policy import DeskPolicy
from shitcoims_tape.schema import WatchClose
from studies.lp_strategy import DLMM_POOLS, SpotPosition, variance_ratio

__all__ = ["PaperRange", "PoolFlow", "TollBook", "lp_fee_rate"]

#: Grid for the return series the RV and VR are computed on. 5 minutes is the bounce-free
#: grid ``RESULT_circuit_theory.md`` §4.4 used; shorter grids read the bid-ask bounce as
#: volatility and deflate VR by up to 2.56x.
GRID_SECONDS: Final[float] = 300.0

#: VR horizon in grid steps. 12 x 5min = 1 hour, the shortest horizon at which the
#: measured VRs are stable across pools.
VR_LAG: Final[int] = 12

#: Rolling flow window. Long enough for VR_LAG to be estimable, short enough that the
#: gate reflects the regime the position would actually live in.
FLOW_WINDOW_S: Final[float] = 6 * 3600.0

#: A one-sided redeploy still fires no tighter than one bin-step of slack, or a ladder
#: sitting on its own edge rebalances every tick. Matches ``lp_strategy.simulate``.
MIN_REBALANCE_SLACK: Final[float] = 0.010

#: Beyond this the tape is not telling us about the present. The gate is still computed
#: and reported (it is a real measurement of a real window) but no position opens.
MAX_TAPE_STALENESS_S: Final[float] = 3600.0


def lp_fee_rate(pool: str) -> float:
    """The LP's share of the fee, after the protocol cut. Never the advertised rate.

    DLMM base fees come from ``studies.lp_strategy.DLMM_POOLS``; the protocol takes 10%
    on 148,226 of 153,867 mainnet pools. PumpSwap's LP leg is 0.20% -- using its 1.44%
    TAKER leg here would overstate LP income by 7x, which is a mistake this repo has
    already made once.
    """
    entry = DLMM_POOLS.get(pool)
    if entry is not None:
        return entry[2] * (1.0 - PROTOCOL_FEE_SHARE)
    return PUMPSWAP_LP_FEE


@dataclass
class PaperRange:
    """One paper LP position. Fully serialisable so the desk resumes it on restart."""

    position_id: str
    decision_id: str
    pool: str
    label: str
    quote_mint: str
    base_mint: str
    dex: str
    f_lp: float
    half_width: float
    rebalance_trigger: float
    #: DESK clock. Lifecycle -- horizon, holding time, the report's day buckets. It is
    #: deliberately NOT the tape's clock: the tape is read in historical bursts, and a
    #: position stamped with a two-day-old open would be past its horizon the instant it
    #: opened and would report a holding time it never had.
    opened_unix: float
    #: CHAIN clock of the flow the position was opened against.
    opened_event_unix: float | None
    opened_t_event: float | None
    opened_t_event_source: str
    deadline_unix: float
    #: Position value in QUOTE units at open, and the lamport basis it converts to.
    value_quote: float
    spend_lamports: int
    entry_price: float
    #: Reference price of the CURRENT range. Moves on every one-sided redeploy.
    ref_price: float
    a: float
    b: float
    ell: float
    last_price: float
    #: CHAIN clock of the last swap accrued. Fee and duty-cycle deltas are measured on
    #: this, because in-range TIME is a property of the market, not of when we read it.
    last_unix: float
    last_t_event: float | None
    last_t_event_source: str
    peak_price: float
    fees_quote: float = 0.0
    costs_quote: float = 0.0
    il_realised_quote: float = 0.0
    in_range_seconds: float = 0.0
    total_seconds: float = 0.0
    rebuilds: int = 0
    swaps_seen: int = 0
    notional_quote: float = 0.0
    gate_eta_entry: float = 0.0
    gate_vr_entry: float = 0.0
    flow_attribution: str = "observed_venue_flow_upper_bound"

    @property
    def position(self) -> SpotPosition:
        return SpotPosition(a=self.a, b=self.b, ell=self.ell)

    @property
    def displacement(self) -> float:
        return math.log(self.last_price / self.ref_price) if self.ref_price > 0 else 0.0

    @property
    def duty_cycle(self) -> float:
        """D. The number that decided DREGG/nosis (49.4%) against weave/nosis (99.4%)."""
        return self.in_range_seconds / self.total_seconds if self.total_seconds > 0 else 0.0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PoolFlow:
    """Rolling observed flow for one pool: the measurement side of the gate.

    Holds a price grid rather than every tick, because RV and VR are grid quantities and
    a tick series computes the bid-ask bounce instead of the volatility.
    """

    pool: str
    label: str
    grid: list[tuple[float, float]] = field(default_factory=list)  # (t, log price)
    notional: list[tuple[float, float]] = field(default_factory=list)  # (t, quote notional)
    last_price: float = 0.0
    last_unix: float = 0.0
    last_t_event: float | None = None
    tvl_quote: float = 0.0
    swaps: int = 0
    out_of_order: int = 0

    def ingest(self, swap: PoolSwap) -> None:
        self.swaps += 1
        when = swap.t_event_unix or swap.t_ingest_unix
        # The tape is day-partitioned on CHAIN time and read file by file, so a row can
        # arrive out of order across a partition boundary. A price series assembled out of
        # order computes a realised variance out of jumps that never happened, so such a
        # row is counted and dropped from the SERIES rather than silently appended.
        if self.grid and when < self.grid[-1][0]:
            self.out_of_order += 1
            return
        self.last_price = swap.price
        self.last_unix = when
        self.last_t_event = swap.t_event_unix
        self.tvl_quote = swap.tvl_quote
        self.notional.append((when, swap.quote_notional))
        lp = math.log(swap.price) if swap.price > 0 else None
        if lp is None:
            return
        if not self.grid or when - self.grid[-1][0] >= GRID_SECONDS:
            self.grid.append((when, lp))
        else:
            self.grid[-1] = (self.grid[-1][0], lp)  # last price wins within a grid cell

    def prune(self, now: float, window: float = FLOW_WINDOW_S) -> None:
        """Keep the last ``window`` of OBSERVED flow, measured on the flow's own clock.

        Pruning against wall time would empty the window whenever the collector is behind
        -- which would turn a stale tape into a silent "no flow" rather than into the
        measurable "flow from N hours ago" that it is. Staleness is reported separately,
        as a number, so the two facts stay separable.
        """
        anchor = self.last_unix or now
        cutoff = anchor - window
        self.grid = [g for g in self.grid if g[0] >= cutoff]
        self.notional = [n for n in self.notional if n[0] >= cutoff]

    @property
    def notional_total(self) -> float:
        return sum(n for _, n in self.notional)

    @property
    def realised_variance(self) -> float:
        """RV = sum of squared grid log-returns. TOTAL over the window, not annualised."""
        lp = [p for _, p in self.grid]
        return sum((lp[i + 1] - lp[i]) ** 2 for i in range(len(lp) - 1))

    @property
    def net_displacement(self) -> float:
        return self.grid[-1][1] - self.grid[0][1] if len(self.grid) >= 2 else 0.0

    def variance_ratio(self, lag: int = VR_LAG) -> float:
        """VR at the holding horizon. NaN when the window cannot support the estimate."""
        lp = [p for _, p in self.grid]
        if len(lp) <= lag + 1:
            return float("nan")
        return variance_ratio(lp, lag)

    @property
    def pool_capacitance(self) -> float:
        """The liquidity ALREADY in the pool, in the same units as a position's ``C``.

        ``C = w_x w_y TVL`` = ``TVL/4`` for a 50/50 CFMM, and ``TVL = 2 * quote_reserve``,
        so ``C_pool = quote_reserve / 2``. For a DLMM this is a proxy: the in-range
        liquidity is not recoverable from vault totals, which is exactly what the tape's
        ``replay_sufficient=false`` flag means.
        """
        return self.tvl_quote / 4.0

    def eta(self, *, f_lp: float, position_capacitance: float) -> float:
        """eta = 2 f N / ((C_position + C_pool) * RV). The DILUTION is not optional.

        A paper position does not capture the pool's whole notional -- it captures its
        SHARE of it, ``C_pos / (C_pos + C_pool)``. Substituting that into
        ``eta = 2 f N_mine / (C_pos RV)`` cancels ``C_pos`` from the numerator and leaves
        the sum in the denominator.

        Getting this wrong is not a rounding error. Computing ``eta`` against the position's
        own capacitance alone made a 1.25-SOL paper position in SOLVE/SOL read
        **eta = 13.7** where the pool-level measurement in
        ``studies/RESULT_circuit_theory.md`` is **0.055** -- a 250x false positive that
        would have opened the desk into every pool the studies proved to be -EV. As
        ``C_position -> 0`` this expression correctly converges to that pool-level number.
        """
        rv = self.realised_variance
        total = position_capacitance + self.pool_capacitance
        if total <= 0 or rv <= 0:
            return float("nan")
        return 2.0 * f_lp * self.notional_total / (total * rv)


class QuoteRates:
    """Quote-token -> lamports, taken from the SOL-quoted pools on the same tape.

    A token-token pool's P&L is denominated in a token, and the desk reports one currency
    so the three books are comparable. The cross rate is not assumed or fetched: it is the
    marginal price of that token's own SOL pool, as last observed, with an explicit
    staleness bound. No rate, no position -- the gate still reports.
    """

    def __init__(self, *, max_staleness_s: float = 6 * 3600.0) -> None:
        self._rates: dict[str, tuple[float, float]] = {}  # mint -> (lamports, t)
        self._max_staleness_s = max_staleness_s

    def observe(self, swap: PoolSwap) -> None:
        if swap.quote_mint != WSOL_MINT:
            return
        when = swap.t_event_unix or swap.t_ingest_unix
        self._rates[swap.base_mint] = (swap.price * LAMPORTS_PER_SOL, when)

    def lamports_per(self, mint: str, now: float) -> float | None:
        if mint == WSOL_MINT:
            return float(LAMPORTS_PER_SOL)
        entry = self._rates.get(mint)
        if entry is None or now - entry[1] > self._max_staleness_s:
            return None
        return entry[0]


class TollBook:
    """The paper LP book. One gate evaluation per pool per interval, positions on top."""

    def __init__(
        self,
        *,
        policy: DeskPolicy,
        friction: Friction,
        ledger: Ledger,
        bankroll_lamports: int,
        max_positions: int = 4,
        gate_interval_s: float = 600.0,
        pools: tuple[Any, ...] = CLUSTER_POOLS,
    ) -> None:
        self.book = Book.TOLL
        self.policy = policy
        self.friction = friction
        self.ledger = ledger
        self.bankroll_lamports = bankroll_lamports
        self.max_positions = max_positions
        self.gate_interval_s = gate_interval_s
        self.specs = {p.address: p for p in pools}
        self.flows: dict[str, PoolFlow] = {}
        self.rates = QuoteRates()
        self.positions: dict[str, PaperRange] = {}
        self.last_gate: dict[str, float] = {}
        self.counters: dict[str, int] = {
            "swaps": 0,
            "gates": 0,
            "decisions": 0,
            "enters": 0,
            "explored": 0,
            "closes": 0,
            "rebuilds": 0,
            "refused_stale_tape": 0,
            "refused_no_rate": 0,
            "insufficient_flow": 0,
        }

    @property
    def deployed_lamports(self) -> int:
        return sum(p.spend_lamports for p in self.positions.values())

    @property
    def free_lamports(self) -> int:
        return max(0, self.bankroll_lamports - self.deployed_lamports)

    # ---------------------------------------------------------------- flow

    def observe(self, swap: PoolSwap, *, now: float | None = None) -> None:
        """One observed swap: update the flow window, then every position on that pool.

        ``now`` is the DESK's clock and stamps the ledger rows. The swap's own clocks ride
        along in ``t_event`` and ``collector_t_ingest``; conflating the three is how a
        historical bootstrap ends up written into last week's ledger file.
        """
        when_seen = now if now is not None else time.time()
        self.counters["swaps"] += 1
        self.rates.observe(swap)
        flow = self.flows.setdefault(swap.pool, PoolFlow(pool=swap.pool, label=swap.label))
        flow.ingest(swap)
        for position in list(self.positions.values()):
            if position.pool == swap.pool:
                self._accrue(position, swap, when_seen)

    def _accrue(self, position: PaperRange, swap: PoolSwap, when_seen: float) -> None:
        """Fees from THIS swap's price path, but only the part inside the paper range.

        ``overlap`` is the fee-earning length of the move: a swap that walked past the
        range edge earns on the part inside it and nothing on the part outside, which is
        the mechanism the duty cycle is a summary of.
        """
        when = swap.t_event_unix or swap.t_ingest_unix
        dt = max(0.0, when - position.last_unix)
        pos = position.position
        m_prev = math.log(position.last_price / position.ref_price)
        m_now = math.log(swap.price / position.ref_price)

        fee = position.f_lp * pos.ell * pos.overlap(m_prev, m_now)
        position.fees_quote += fee
        position.notional_quote += swap.quote_notional
        position.swaps_seen += 1
        # In-range time is attributed to the interval's STARTING state: we know the price
        # was in range then, and we only learn it left when this swap arrives.
        if pos.in_range(m_prev):
            position.in_range_seconds += dt
        position.total_seconds += dt
        position.last_price = swap.price
        position.last_unix = when
        position.last_t_event = swap.t_event_unix
        position.last_t_event_source = swap.t_event_source
        position.peak_price = max(position.peak_price, swap.price)

        if fee > 0:
            self.ledger.emit(
                "accrual",
                str(self.book),
                t_ingest_unix=when_seen,
                t_event_unix=swap.t_event_unix,
                t_event_source=swap.t_event_source,
                collector_t_ingest=swap.t_ingest_unix,
                position_id=position.position_id,
                key=position.pool,
                label=position.label,
                fee_quote=fee,
                quote_mint=position.quote_mint,
                notional_quote=swap.quote_notional,
                displacement=m_now,
                in_range=pos.in_range(m_now),
                duty_cycle=position.duty_cycle,
                f_lp=position.f_lp,
                flow_attribution=position.flow_attribution,
                price_source=swap.price_source,
            )

        beyond = max(-position.a - m_now, m_now - position.b, 0.0)
        if beyond > max(position.rebalance_trigger, MIN_REBALANCE_SLACK):
            self._rebalance(position, swap, m_now, when_seen)

    def _rebalance(
        self, position: PaperRange, swap: PoolSwap, m_now: float, when_seen: float
    ) -> None:
        """One-sided redeploy: re-center at the current price, pay gas, never swap.

        The realised IL at the moment of redeploy is booked here, because re-centering
        crystallises it -- the position is 100% one token at the edge and the new range
        starts from that composition. Cost is GAS ONLY: two transactions, ~$0.015, versus
        2.88% round trip for a swap re-center. That ratio (1/50th to 1/80th) is why the
        rule is one-sided.
        """
        pos = position.position
        position.il_realised_quote += pos.il_quote(m_now)
        value_now = pos.value_quote(m_now)
        gas_quote = self._gas_in_quote(position, swap)
        position.costs_quote += gas_quote
        position.rebuilds += 1
        self.counters["rebuilds"] += 1

        redeployed = SpotPosition.from_value(
            max(value_now - gas_quote, 1e-12), a=position.half_width, b=position.half_width
        )
        position.ref_price = swap.price
        position.a = redeployed.a
        position.b = redeployed.b
        position.ell = redeployed.ell
        self.ledger.emit(
            "rebalance",
            str(self.book),
            t_ingest_unix=when_seen,
            t_event_unix=swap.t_event_unix,
            t_event_source=swap.t_event_source,
            collector_t_ingest=swap.t_ingest_unix,
            position_id=position.position_id,
            key=position.pool,
            label=position.label,
            style="one_sided_redeploy",
            beyond=max(-position.half_width - m_now, m_now - position.half_width, 0.0),
            new_ref_price=swap.price,
            value_quote=value_now,
            gas_quote=gas_quote,
            il_realised_quote=position.il_realised_quote,
            rebuilds=position.rebuilds,
            duty_cycle=position.duty_cycle,
        )

    def _gas_in_quote(self, position: PaperRange, swap: PoolSwap) -> float:
        rate = self.rates.lamports_per(position.quote_mint, swap.t_event_unix or swap.t_ingest_unix)
        if rate is None or rate <= 0:
            return 0.0
        return self.friction.gas_per_rebuild_lamports / rate

    # ---------------------------------------------------------------- gate

    def gate(self, now: float) -> None:
        """Evaluate ``eta * D > VR`` for every pool with flow, and act on the verdict.

        The gate row is emitted whether or not a position follows -- it is the standing
        measurement the operator has never had in one place, and it is meaningful even
        when the tape is too cold to trade on.
        """
        for pool, flow in self.flows.items():
            if now - self.last_gate.get(pool, 0.0) < self.gate_interval_s:
                continue
            self.last_gate[pool] = now
            flow.prune(now)
            self._gate_one(flow, now)

    def _gate_one(self, flow: PoolFlow, now: float) -> None:
        spec = self.specs.get(flow.pool)
        if spec is None:
            return
        self.counters["gates"] += 1
        f_lp = lp_fee_rate(flow.pool)
        rv = flow.realised_variance
        vr = flow.variance_ratio()
        staleness = now - flow.last_unix if flow.last_unix else float("inf")

        # Size first: eta depends on the capacitance C = T/W, so it is only defined once
        # we say how much capital and how wide. This is the concentration point made
        # operational -- there is no pool-level eta, only a position-level one.
        thresholds = self.policy.draw()
        half_width = thresholds["half_width"]
        width = 2.0 * half_width
        quote_mint = self._quote_mint(flow)
        rate = self.rates.lamports_per(quote_mint, now) if quote_mint else None

        per_position = self.bankroll_lamports // max(1, self.max_positions)
        cap = min(per_position, self.free_lamports)
        value_quote = (cap / rate) if (rate and rate > 0) else 0.0
        # Never take more than rho of the pool: the same 2% impact ceiling the other books
        # obey, applied to the side we would be adding to.
        rho_cap = flow.tvl_quote * self.friction.rho_max_bps / 10_000.0
        if rho_cap > 0:
            value_quote = min(value_quote, rho_cap)
        capacitance = value_quote / width if width > 0 else 0.0
        eta = flow.eta(f_lp=f_lp, position_capacitance=capacitance)

        usable = (
            len(flow.grid) > VR_LAG + 1
            and rv > 0
            and eta == eta
            and vr == vr
            and value_quote > 0
        )
        refusal: str | None = None
        if not usable:
            refusal = "insufficient_flow"
            self.counters["insufficient_flow"] += 1
        elif staleness > MAX_TAPE_STALENESS_S:
            refusal = "tape_stale"
            self.counters["refused_stale_tape"] += 1
        elif rate is None:
            refusal = "no_quote_rate"
            self.counters["refused_no_rate"] += 1

        self.ledger.emit(
            "gate",
            str(self.book),
            t_ingest_unix=now,
            t_event_unix=flow.last_t_event,
            t_event_source="chain:block_time" if flow.last_t_event else "absent:no_flow_observed",
            key=flow.pool,
            label=flow.label,
            dex=spec.dex,
            f_lp=f_lp,
            swaps=flow.swaps,
            grid_points=len(flow.grid),
            window_s=FLOW_WINDOW_S,
            notional_quote=flow.notional_total,
            realised_variance=rv,
            net_displacement=flow.net_displacement,
            variance_ratio=None if vr != vr else vr,
            vr_lag_minutes=VR_LAG * GRID_SECONDS / 60.0,
            half_width=half_width,
            capacitance_quote=capacitance,
            pool_capacitance_quote=flow.pool_capacitance,
            quote_mint=quote_mint,
            # On a CFMM the vault totals ARE the capacitance. On a DLMM only the IN-RANGE
            # liquidity is, and that is not recoverable from vault totals -- which is
            # precisely what the tape's replay_sufficient=false means. Using the vault
            # total OVERSTATES C_pool, and therefore UNDERSTATES eta, on every DLMM row.
            # Flagged rather than silently mixed in with the exact ones.
            capacitance_basis=(
                "vault_totals_exact_cfmm"
                if spec.replay_sufficient_reserves
                else "vault_totals_proxy_dlmm_overstates_pool_C"
            ),
            out_of_order_rows=flow.out_of_order,
            value_quote=value_quote,
            eta=None if eta != eta else eta,
            required_duty=None if (eta != eta or eta <= 0 or vr != vr) else vr / eta,
            tape_staleness_s=staleness,
            refusal=refusal,
            open_positions=len(self.positions),
        )
        if refusal is not None or flow.pool in {p.pool for p in self.positions.values()}:
            return
        self._consider(flow, now, thresholds, eta=eta, vr=vr, value_quote=value_quote, rate=rate, f_lp=f_lp)

    def _quote_mint(self, flow: PoolFlow) -> str | None:
        spec = self.specs.get(flow.pool)
        if spec is None:
            return None
        if WSOL_MINT in spec.mints:
            return WSOL_MINT
        return sorted(spec.mints)[0] if spec.mints else None

    def _consider(
        self,
        flow: PoolFlow,
        now: float,
        thresholds: dict[str, float],
        *,
        eta: float,
        vr: float,
        value_quote: float,
        rate: float | None,
        f_lp: float,
    ) -> None:
        if len(self.positions) >= self.max_positions or rate is None:
            return
        features = {
            "eta": eta,
            "variance_ratio": vr,
            "realised_variance": flow.realised_variance,
            "notional_quote": flow.notional_total,
            "swaps": float(flow.swaps),
            "tvl_quote": flow.tvl_quote,
        }
        spend = int(value_quote * rate)
        # The thresholds the gate was evaluated at ARE the thresholds logged. Re-drawing
        # inside decide() would log one policy and act on another, and the propensity
        # would describe a run that never happened.
        decision = self.policy.decide(
            key=flow.pool,
            features=features,
            now_unix=now,
            decided_at=iso(now),
            size_lamports=spend,
            actionable=spend > 0,
            thresholds=thresholds,
        )
        self.counters["decisions"] += 1
        if decision.explored:
            self.counters["explored"] += 1
        self.ledger.decision(
            book=str(self.book),
            record=decision.record(),
            t_ingest_unix=now,
            t_event_unix=flow.last_t_event,
            t_event_source="chain:block_time" if flow.last_t_event else "absent:no_flow_observed",
            source="cluster_tape",
            label=flow.label,
            blocked=None,
            **decision.ledger_fields(),
        )
        if not decision.acted or spend <= 0:
            return
        self._open(
            flow, decision, thresholds, now,
            value_quote=value_quote, spend=spend, eta=eta, vr=vr, f_lp=f_lp,
        )

    def _open(
        self,
        flow: PoolFlow,
        decision: Any,
        thresholds: dict[str, float],
        now: float,
        *,
        value_quote: float,
        spend: int,
        eta: float,
        vr: float,
        f_lp: float,
    ) -> None:
        half = thresholds["half_width"]
        pos = SpotPosition.from_value(value_quote, a=half, b=half)
        spec = self.specs[flow.pool]
        quote_mint = self._quote_mint(flow) or WSOL_MINT
        base_mint = next((m for m in sorted(spec.mints) if m != quote_mint), quote_mint)
        position = PaperRange(
            position_id=f"{decision.decision_id}-r",
            decision_id=decision.decision_id,
            pool=flow.pool,
            label=flow.label,
            quote_mint=quote_mint,
            base_mint=base_mint,
            dex=spec.dex,
            f_lp=f_lp,
            half_width=half,
            rebalance_trigger=thresholds["rebalance_trigger"],
            opened_unix=now,
            opened_event_unix=flow.last_unix or None,
            opened_t_event=flow.last_t_event,
            opened_t_event_source=(
                "chain:block_time" if flow.last_t_event else "absent:no_flow_observed"
            ),
            deadline_unix=now + thresholds["hold_seconds"],
            value_quote=value_quote,
            spend_lamports=spend,
            entry_price=flow.last_price,
            ref_price=flow.last_price,
            a=pos.a,
            b=pos.b,
            ell=pos.ell,
            last_price=flow.last_price,
            last_unix=flow.last_unix,
            last_t_event=flow.last_t_event,
            last_t_event_source="chain:block_time" if flow.last_t_event else "absent:no_flow_observed",
            peak_price=flow.last_price,
            gate_eta_entry=eta,
            gate_vr_entry=vr,
            flow_attribution=(
                "pool_own_flow_exact" if spec.dex == "meteora_dlmm" else "observed_venue_flow_upper_bound"
            ),
        )
        self.positions[position.position_id] = position
        self.counters["enters"] += 1
        self.ledger.emit(
            "fill",
            str(self.book),
            t_ingest_unix=now,
            t_event_unix=flow.last_t_event,
            t_event_source=position.opened_t_event_source,
            collector_t_ingest=flow.last_unix,
            position_id=position.position_id,
            decision_id=position.decision_id,
            key=flow.pool,
            label=flow.label,
            source="cluster_tape",
            spend_lamports=spend,
            value_quote=value_quote,
            quote_mint=quote_mint,
            half_width=half,
            ell=pos.ell,
            entry_price=flow.last_price,
            eta=eta,
            variance_ratio=vr,
            required_duty=vr / eta if eta > 0 else None,
            explored=decision.explored,
            verdict_pass=decision.verdict_pass,
            flow_attribution=position.flow_attribution,
        )

    # ---------------------------------------------------------------- closing

    def sweep(self, now: float, *, source_stale: bool) -> None:
        """Close on horizon, or when the position's OWN realised numbers fail the gate."""
        for position in list(self.positions.values()):
            flow = self.flows.get(position.pool)
            vr = flow.variance_ratio() if flow else float("nan")
            eta = (
                flow.eta(
                    f_lp=position.f_lp,
                    position_capacitance=position.value_quote / (2 * position.half_width),
                )
                if flow
                else float("nan")
            )
            realised_gate = (
                eta * position.duty_cycle
                if (eta == eta and position.total_seconds > 0)
                else float("nan")
            )
            if now >= position.deadline_unix:
                self._close(
                    position, now, "horizon", WatchClose.DEADLINE, source_stale=source_stale
                )
            elif (
                realised_gate == realised_gate
                and vr == vr
                and position.total_seconds > 3600.0
                and realised_gate < vr
            ):
                # Measured, not assumed: the position's own duty cycle and its pool's own
                # churn say it is -EV. This is the exit the DREGG/nosis position never had.
                self._close(
                    position, now, "gate_failed", WatchClose.DEADLINE, source_stale=source_stale
                )

    def _close(
        self,
        position: PaperRange,
        now: float,
        reason: str,
        close_reason: WatchClose,
        *,
        source_stale: bool,
    ) -> None:
        pos = position.position
        m = position.displacement
        value_quote = pos.value_quote(m)
        il_open = pos.il_quote(m)
        net_vs_hodl_quote = (
            position.fees_quote + il_open + position.il_realised_quote - position.costs_quote
        )
        rate = self.rates.lamports_per(position.quote_mint, now)
        # An operator-ordered close is a clean stop, not censoring, however stale the tape
        # was when it happened. Only a position we STOPPED BEING ABLE TO SEE is censored.
        censored = close_reason is not WatchClose.OPERATOR and (source_stale or rate is None)
        if censored and close_reason is WatchClose.DEADLINE:
            close_reason = WatchClose.OBSERVER_LOST

        # Without a cross rate the position cannot be marked in lamports at all. Rather
        # than invent one, fall back to the ENTRY rate and flag the row: a stale rate is a
        # measurable error, a made-up one is not.
        entry_rate = (
            position.spend_lamports / position.value_quote if position.value_quote > 0 else 0.0
        )
        used_rate = rate if (rate and rate > 0) else entry_rate
        proceeds = int(
            max(0.0, (value_quote + position.fees_quote - position.costs_quote) * used_rate)
        )
        priority = 2 * self.friction.priority_fee_lamports
        pnl = proceeds - position.spend_lamports - priority
        self.positions.pop(position.position_id, None)
        self.counters["closes"] += 1
        self.ledger.write(
            close_row(
                run_id=self.ledger.run_id,
                book=str(self.book),
                position_id=position.position_id,
                decision_id=position.decision_id,
                key=position.pool,
                label=position.label,
                opened_at_unix=position.opened_unix,
                closed_at_unix=now,
                t_event_unix=position.last_t_event,
                t_event_source=position.last_t_event_source,
                spend_lamports=position.spend_lamports,
                proceeds_lamports=proceeds,
                priority_fees_lamports=priority,
                pnl_lamports=pnl,
                # An LP position is not a bag that can go to zero on a lost feed: it is
                # two token balances in a pool. The pessimistic figure is the same number,
                # and saying so explicitly is better than leaving the field to be guessed.
                pnl_pessimistic_lamports=pnl,
                exit_reason=reason,
                censored=censored,
                censor_reason=str(close_reason) if censored else None,
                mark_source="last_observed_before_trigger" if censored else "observed",
                observations=position.swaps_seen,
                entry_price=position.entry_price,
                exit_price=position.last_price,
                peak_price=position.peak_price,
                extra={
                    "source": "cluster_tape",
                    "pool": position.pool,
                    "dex": position.dex,
                    "quote_mint": position.quote_mint,
                    "f_lp": position.f_lp,
                    "half_width": position.half_width,
                    "rebalance_trigger": position.rebalance_trigger,
                    "fees_quote": position.fees_quote,
                    "costs_quote": position.costs_quote,
                    "il_open_quote": il_open,
                    "il_realised_quote": position.il_realised_quote,
                    "net_vs_hodl_quote": net_vs_hodl_quote,
                    "net_vs_hodl_lamports": int(net_vs_hodl_quote * used_rate),
                    "duty_cycle": position.duty_cycle,
                    "rebuilds": position.rebuilds,
                    "notional_quote": position.notional_quote,
                    "value_quote_close": value_quote,
                    "gate_eta_entry": position.gate_eta_entry,
                    "gate_vr_entry": position.gate_vr_entry,
                    "quote_rate_source": "live" if (rate and rate > 0) else "entry_rate_fallback",
                    "flow_attribution": position.flow_attribution,
                },
            )
        )

    def drain(self, now: float | None = None) -> None:
        """Close every open range through the same builder every other exit uses."""
        when = now if now is not None else time.time()
        for position in list(self.positions.values()):
            self._close(position, when, "drain", WatchClose.OPERATOR, source_stale=False)

    # ---------------------------------------------------------------- persistence

    def state(self) -> dict[str, Any]:
        return {
            "positions": {k: v.to_json() for k, v in self.positions.items()},
            "counters": self.counters,
        }

    def restore(self, state: dict[str, Any]) -> None:
        self.positions = {k: PaperRange(**v) for k, v in (state.get("positions") or {}).items()}
        self.counters.update(state.get("counters") or {})
