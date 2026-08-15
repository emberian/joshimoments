"""The SHORT and MEDIUM books: one position machine, two sets of triggers.

Both books buy a bonding-curve mint and mark it on the curve, so they share a state
machine and differ only in policy and exit rule. Sharing it is the point -- the operator's
question is which HORIZON pays, and two horizons measured by two pieces of code answer a
different question than the one asked.

THE STATE MACHINE, AND WHY IT HAS AN "ARMED" STATE
--------------------------------------------------
``pending -> open -> armed -> closed``

* **pending** -- a decision exists; nothing is filled. The entry fills at the NEXT
  observation of the mint, never at the snapshot that produced the decision. Filling at
  the deciding snapshot is lookahead worth several percent a round on this feed.
* **open** -- filled. Each further observation updates the mark, the running peak, and the
  trade-activity record.
* **armed** -- a trigger fired at observation N. The exit fills at observation N+1. This
  is stricter than the study grid, which resolves at the observation that revealed the
  trigger; you cannot trade on the tick that told you to trade.
* **closed** -- exactly one close row, built by one function, carrying every field.

WHEN THE FEED LOSES A MINT
--------------------------
Departure is not one event, so it does not get one treatment:

* the source itself went quiet -> ``OBSERVER_LOST``. Our observer died; informative.
* the source is busy but this mint stopped appearing -> ``DISPLACED``. Attention moved on;
  informative, and the single most common outcome on a boards feed.
* the mint graduated (``complete``) -> ``GRADUATED``. A terminal outcome, not a loss: it
  is tradeable elsewhere, we simply stopped watching it here.
* the curve drained to nothing -> ``DIED``. Total loss, and the only case where the
  headline and the pessimistic numbers agree by construction.

In the first three the position is marked at the last price observed AT OR BEFORE the
trigger -- never after -- and the row is flagged ``censored``. That single rule is the
difference between ``RESULT_board_entry.md``'s +21.77% and its true -12.24%. The
pessimistic figure (departure = total loss) is carried in the same row so the report can
print both and the reader can see how much of the answer is assumption.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Final

from shitcoims_paperdesk import Book
from shitcoims_paperdesk.feeds import MintObservation
from shitcoims_paperdesk.friction import Friction
from shitcoims_paperdesk.ledger import Ledger, close_row, iso
from shitcoims_paperdesk.policy import DeskPolicy
from shitcoims_scalper.book import CircuitBreaker
from shitcoims_scalper.shadow import CurveState, curve_buy, curve_sell
from shitcoims_tape.schema import WatchClose

__all__ = ["MintBook", "PaperPosition"]

#: How long a mint may go unobserved before the desk concludes it left observation. Set
#: against the boards poll cadence (5 boards / 30s) with generous slack: shorter and a
#: routine board reshuffle reads as a departure.
DEPARTURE_TIMEOUT_S: Final[float] = 600.0

#: Below this the curve is drained and the position is genuinely worthless, not merely
#: unobserved. 0.5 SOL of virtual reserve is under the 30 SOL floor a live curve starts at.
DEAD_CURVE_LAMPORTS: Final[int] = 500_000_000

#: Rolling window over which the medium book measures ``active_frac`` -- the share of
#: recent observations that showed a NEW trade. RESULT_deterioration.md measured it over
#: 24 hourly candles; the desk measures it over its own observations, which is the same
#: quantity at whatever cadence the feed actually delivers.
ACTIVITY_WINDOW: Final[int] = 24


@dataclass
class PaperPosition:
    """One paper position. Serialisable in full: the desk resumes its book on restart."""

    position_id: str
    decision_id: str
    book: str
    mint: str
    source: str
    label: str | None
    spend_lamports: int
    take_bps: int
    tokens_raw: int
    entry_price: float
    entry_unix: float
    entry_t_event: float | None
    entry_t_event_source: str
    deadline_unix: float
    take_profit: float
    stop_loss: float
    deterioration_drawdown: float
    deterioration_active_frac: float
    peak_price: float
    last_price: float
    last_vsol: int
    last_vtok: int
    last_obs_unix: float
    last_obs_t_event: float | None
    last_obs_t_event_source: str
    last_trade_unix: float | None
    observations: int = 0
    activity: list[int] = field(default_factory=list)
    armed_reason: str | None = None
    armed_unix: float | None = None
    armed_price: float | None = None

    @property
    def ratio(self) -> float:
        return self.last_price / self.entry_price if self.entry_price > 0 else 1.0

    @property
    def drawdown_from_peak(self) -> float:
        return 1.0 - (self.last_price / self.peak_price) if self.peak_price > 0 else 0.0

    @property
    def active_frac(self) -> float:
        if not self.activity:
            return 0.0
        return sum(self.activity) / len(self.activity)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class MintBook:
    """A book over bonding-curve mints. SHORT and MEDIUM are two instances of this.

    Capital and friction come in from outside and are identical across books by
    construction -- that is what makes the cross-book table a comparison. The circuit
    breaker is shared too: N concurrent positions on fresh mints are secretly one bet on
    market-wide degen appetite (measured hourly Fano 16.7), so the breaker converts
    overdispersion from a silent killer into a state the heartbeat reports.
    """

    def __init__(
        self,
        book: Book,
        *,
        policy: DeskPolicy,
        friction: Friction,
        ledger: Ledger,
        bankroll_lamports: int,
        max_positions: int = 8,
        decision_cooldown_s: float = 300.0,
        deterioration_exit: bool = False,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self.book = book
        self.policy = policy
        self.friction = friction
        self.ledger = ledger
        self.bankroll_lamports = bankroll_lamports
        self.max_positions = max_positions
        self.decision_cooldown_s = decision_cooldown_s
        self.deterioration_exit = deterioration_exit
        self.breaker = breaker or CircuitBreaker()

        self.pending: dict[str, dict[str, Any]] = {}
        self.positions: dict[str, PaperPosition] = {}
        self.last_decided: dict[str, float] = {}
        #: mint -> (first_seen_unix, observation_count). The medium book's survivorship
        #: gate reads it; it is also how the desk knows a mint it never traded is alive.
        self.seen: dict[str, tuple[float, int]] = {}
        self.counters: dict[str, int] = {
            "observations": 0,
            "decisions": 0,
            "enters": 0,
            "explored": 0,
            "fills": 0,
            "closes": 0,
            "censored": 0,
            "skipped_bankroll": 0,
            "skipped_breaker": 0,
        }

    # ---------------------------------------------------------------- accounting

    @property
    def deployed_lamports(self) -> int:
        return sum(p.spend_lamports for p in self.positions.values()) + sum(
            int(p["size_lamports"]) for p in self.pending.values()
        )

    @property
    def free_lamports(self) -> int:
        return max(0, self.bankroll_lamports - self.deployed_lamports)

    # ---------------------------------------------------------------- observation

    def observe(self, obs: MintObservation, *, source_stale: bool) -> None:
        """One observation: fill pendings, mark opens, arm or close. In that order.

        The order is the pessimism. A pending entry filling on THIS observation must not
        also be marked and exited on it, so fills are taken first and the freshly-filled
        position sees its first mark on the observation after.
        """
        now = obs.t_ingest_unix
        self.counters["observations"] += 1
        first, count = self.seen.get(obs.mint, (now, 0))
        self.seen[obs.mint] = (first, count + 1)

        self._fill_pending(obs)
        self._mark(obs, source_stale=source_stale)

    def _fill_pending(self, obs: MintObservation) -> None:
        pending = self.pending.get(obs.mint)
        if pending is None:
            return
        # The fill must happen on the same venue the decision was sized against, or the
        # position opens at one price basis and is marked at another.
        if pending.get("pool_label") != obs.pool_label:
            return
        del self.pending[obs.mint]
        take_bps = self.friction.take_bps_for(obs.pool_label)
        tokens = curve_buy(obs.curve, int(pending["size_lamports"]), fee_bps=take_bps)
        if tokens <= 0:
            self.ledger.emit(
                "defect",
                str(self.book),
                t_ingest_unix=obs.t_ingest_unix,
                t_event_unix=obs.t_event_unix,
                t_event_source=obs.t_event_source,
                key=obs.mint,
                decision_id=pending["decision_id"],
                detail="entry_would_receive_zero_tokens",
            )
            return
        position = PaperPosition(
            position_id=f"{pending['decision_id']}-p",
            decision_id=str(pending["decision_id"]),
            book=str(self.book),
            mint=obs.mint,
            source=obs.source,
            label=obs.pool_label,
            spend_lamports=int(pending["size_lamports"]),
            take_bps=take_bps,
            tokens_raw=tokens,
            entry_price=obs.price,
            entry_unix=obs.t_ingest_unix,
            entry_t_event=obs.t_event_unix,
            entry_t_event_source=obs.t_event_source,
            deadline_unix=float(pending["deadline_unix"]),
            take_profit=float(pending["take_profit"]),
            stop_loss=float(pending["stop_loss"]),
            deterioration_drawdown=float(pending.get("deterioration_drawdown", 1.0)),
            deterioration_active_frac=float(pending.get("deterioration_active_frac", 2.0)),
            peak_price=obs.price,
            last_price=obs.price,
            last_vsol=obs.vsol_lamports,
            last_vtok=obs.vtok_raw,
            last_obs_unix=obs.t_ingest_unix,
            last_obs_t_event=obs.t_event_unix,
            last_obs_t_event_source=obs.t_event_source,
            last_trade_unix=obs.last_trade_unix,
            observations=1,
        )
        self.positions[position.position_id] = position
        self.counters["fills"] += 1
        self.ledger.emit(
            "fill",
            str(self.book),
            t_ingest_unix=obs.t_ingest_unix,
            t_event_unix=obs.t_event_unix,
            t_event_source=obs.t_event_source,
            position_id=position.position_id,
            decision_id=position.decision_id,
            key=obs.mint,
            source=obs.source,
            spend_lamports=position.spend_lamports,
            tokens_raw=tokens,
            entry_price=obs.price,
            take_bps=take_bps,
            take_profit=position.take_profit,
            stop_loss=position.stop_loss,
            deadline=iso(position.deadline_unix),
            # The pessimism, stated on the row: this fill is one observation LATER than
            # the decision that produced it.
            fill_lag_s=obs.t_ingest_unix - float(pending["decided_unix"]),
        )

    @staticmethod
    def _same_price_basis(position: PaperPosition, obs: MintObservation) -> bool:
        """Refuse to mark a position against a price from a different venue.

        A bonding-curve mint and a graduated pool quote the SAME mint on completely
        different reserve scales: the curve carries 30+ SOL of VIRTUAL reserves against a
        billion-token supply, the pool carries real vault balances. Marking a
        pool-priced position against a curve observation (or the reverse) produces a
        ratio with no meaning, and a meaningless ratio trips the stop-loss immediately --
        an instant fabricated loss that looks exactly like a real one.
        """
        return position.label == obs.pool_label

    def _mark(self, obs: MintObservation, *, source_stale: bool) -> None:
        for position in list(self.positions.values()):
            if position.mint != obs.mint or not self._same_price_basis(position, obs):
                continue
            if position.armed_reason is not None:
                # The trigger fired on a PREVIOUS observation. This is the first
                # observation after it, so this is where the exit fills.
                self._close_observed(position, obs)
                continue
            self._update(position, obs)
            if obs.vsol_lamports <= DEAD_CURVE_LAMPORTS:
                self._close_marked(
                    position,
                    now=obs.t_ingest_unix,
                    reason="curve_drained",
                    close_reason=WatchClose.DIED,
                    total_loss=True,
                )
                continue
            if obs.complete:
                self._close_marked(
                    position,
                    now=obs.t_ingest_unix,
                    reason="graduated",
                    close_reason=WatchClose.GRADUATED,
                    total_loss=False,
                )
                continue
            trigger = self._trigger(position, obs.t_ingest_unix)
            if trigger is not None:
                position.armed_reason = trigger
                position.armed_unix = obs.t_ingest_unix
                position.armed_price = obs.price
                self.ledger.emit(
                    "mark",
                    str(self.book),
                    t_ingest_unix=obs.t_ingest_unix,
                    t_event_unix=obs.t_event_unix,
                    t_event_source=obs.t_event_source,
                    position_id=position.position_id,
                    key=position.mint,
                    armed=trigger,
                    ratio=position.ratio,
                    drawdown_from_peak=position.drawdown_from_peak,
                    active_frac=position.active_frac,
                    observations=position.observations,
                )
        _ = source_stale  # staleness is consulted at sweep time, not per observation

    @staticmethod
    def _update(position: PaperPosition, obs: MintObservation) -> None:
        traded = (
            obs.last_trade_unix is not None
            and position.last_trade_unix is not None
            and obs.last_trade_unix > position.last_trade_unix
        )
        position.activity.append(1 if traded else 0)
        del position.activity[:-ACTIVITY_WINDOW]
        position.last_price = obs.price
        position.peak_price = max(position.peak_price, obs.price)
        position.last_vsol = obs.vsol_lamports
        position.last_vtok = obs.vtok_raw
        position.last_obs_unix = obs.t_ingest_unix
        position.last_obs_t_event = obs.t_event_unix
        position.last_obs_t_event_source = obs.t_event_source
        position.last_trade_unix = obs.last_trade_unix or position.last_trade_unix
        position.observations += 1

    def _trigger(self, position: PaperPosition, now: float) -> str | None:
        ratio = position.ratio
        if ratio >= 1.0 + position.take_profit:
            return "take_profit"
        if ratio <= 1.0 - position.stop_loss:
            return "stop_loss"
        if now >= position.deadline_unix:
            return "deadline"
        if (
            self.deterioration_exit
            and len(position.activity) >= ACTIVITY_WINDOW // 2
            and position.drawdown_from_peak >= position.deterioration_drawdown
            and position.active_frac >= position.deterioration_active_frac
        ):
            # The conjunction of the only two signals that survived
            # RESULT_deterioration.md. Both are weak (|Spearman| 0.08-0.11); this is a
            # prior to be beaten, and the ledger is what will beat it.
            return "deterioration"
        return None

    # ---------------------------------------------------------------- sweeping

    def sweep(self, now: float, *, source_stale: bool) -> None:
        """Close positions that stopped being observed, and expire stale pendings.

        This is where absence of data becomes a priced outcome rather than a silent hold.
        A position that is merely past its deadline stays open until the next observation
        arrives to fill it -- the deadline arms the trigger, it does not fill the exit.
        """
        for position in list(self.positions.values()):
            silent = now - position.last_obs_unix
            if silent < DEPARTURE_TIMEOUT_S:
                continue
            reason = position.armed_reason or ("deadline" if now >= position.deadline_unix else "departed")
            self._close_marked(
                position,
                now=now,
                reason=reason,
                close_reason=(WatchClose.OBSERVER_LOST if source_stale else WatchClose.DISPLACED),
                total_loss=False,
            )
        for mint, pending in list(self.pending.items()):
            if now - float(pending["decided_unix"]) >= DEPARTURE_TIMEOUT_S:
                # Never filled: the mint left observation between the decision and the
                # next sighting. Nothing was spent, so there is no close row -- but the
                # decision row still stands, which is what keeps the propensity log
                # complete for OPE.
                del self.pending[mint]
                self.ledger.emit(
                    "defect",
                    str(self.book),
                    t_ingest_unix=now,
                    key=mint,
                    decision_id=pending["decision_id"],
                    detail="entry_never_filled_mint_left_observation",
                    waited_s=now - float(pending["decided_unix"]),
                )

    # ---------------------------------------------------------------- closing

    def _close_observed(self, position: PaperPosition, obs: MintObservation) -> None:
        """The clean case: the exit fills against reserves observed after the trigger."""
        state = CurveState(
            t_ingest_unix=obs.t_ingest_unix,
            vsol_lamports=obs.vsol_lamports,
            vtok_raw=obs.vtok_raw,
        )
        proceeds = curve_sell(state, position.tokens_raw, fee_bps=position.take_bps)
        self._emit_close(
            position,
            now=obs.t_ingest_unix,
            t_event_unix=obs.t_event_unix,
            t_event_source=obs.t_event_source,
            proceeds=proceeds,
            exit_price=obs.price,
            exit_reason=position.armed_reason or "unknown",
            censored=False,
            censor_reason=None,
            mark_source="observed",
            pessimistic_proceeds=proceeds,
        )

    def _close_marked(
        self,
        position: PaperPosition,
        *,
        now: float,
        reason: str,
        close_reason: WatchClose,
        total_loss: bool,
    ) -> None:
        """The censored case: mark at the last price observed AT OR BEFORE the trigger.

        ``position.armed_price`` is that price when a trigger had already fired; otherwise
        it is the last mark. Either way it is never a price observed after the trigger,
        which is the whole content of the correction.
        """
        state = CurveState(
            t_ingest_unix=position.last_obs_unix,
            vsol_lamports=max(1, position.last_vsol),
            vtok_raw=max(1, position.last_vtok),
        )
        proceeds = 0 if total_loss else curve_sell(state, position.tokens_raw, fee_bps=position.take_bps)
        exit_price = position.armed_price if position.armed_price is not None else position.last_price
        censored = close_reason in {WatchClose.DISPLACED, WatchClose.OBSERVER_LOST}
        self._emit_close(
            position,
            now=now,
            t_event_unix=position.last_obs_t_event,
            t_event_source=position.last_obs_t_event_source,
            proceeds=proceeds,
            exit_price=exit_price,
            exit_reason=reason,
            censored=censored,
            censor_reason=str(close_reason) if censored else None,
            mark_source="total_loss" if total_loss else "last_observed_before_trigger",
            # The pessimistic book: a position that left observation is worth nothing,
            # because in live trading an unsellable bag is worth its floor, not its last
            # quote. Carried alongside, never instead of, the marked-out figure.
            pessimistic_proceeds=0 if censored or total_loss else proceeds,
        )

    def _emit_close(
        self,
        position: PaperPosition,
        *,
        now: float,
        t_event_unix: float | None,
        t_event_source: str,
        proceeds: int,
        exit_price: float,
        exit_reason: str,
        censored: bool,
        censor_reason: str | None,
        mark_source: str,
        pessimistic_proceeds: int,
    ) -> None:
        priority = 2 * self.friction.priority_fee_lamports
        pnl = proceeds - position.spend_lamports - priority
        pnl_pess = pessimistic_proceeds - position.spend_lamports - priority
        self.positions.pop(position.position_id, None)
        self.counters["closes"] += 1
        if censored:
            self.counters["censored"] += 1
        self.breaker.record_close(pnl, now)
        self.ledger.write(
            close_row(
                run_id=self.ledger.run_id,
                book=str(self.book),
                position_id=position.position_id,
                decision_id=position.decision_id,
                key=position.mint,
                label=position.source,
                opened_at_unix=position.entry_unix,
                closed_at_unix=now,
                t_event_unix=t_event_unix,
                t_event_source=t_event_source,
                spend_lamports=position.spend_lamports,
                proceeds_lamports=proceeds,
                priority_fees_lamports=priority,
                pnl_lamports=pnl,
                pnl_pessimistic_lamports=pnl_pess,
                exit_reason=exit_reason,
                censored=censored,
                censor_reason=censor_reason,
                mark_source=mark_source,
                observations=position.observations,
                entry_price=position.entry_price,
                exit_price=exit_price,
                peak_price=position.peak_price,
                extra={
                    "source": position.source,
                    "take_bps": position.take_bps,
                    "take_profit": position.take_profit,
                    "stop_loss": position.stop_loss,
                    "tokens_raw": position.tokens_raw,
                    "active_frac": position.active_frac,
                    "drawdown_from_peak": position.drawdown_from_peak,
                    "armed_at": iso(position.armed_unix) if position.armed_unix else None,
                },
            )
        )

    # ---------------------------------------------------------------- deciding

    def consider(self, obs: MintObservation, *, extra_features: dict[str, float] | None = None) -> None:
        """Decide on one candidate, logging the propensity whatever the verdict.

        Skips are logged too. They cost nothing on paper and they buy the
        selection-versus-luck decomposition: without the rejected candidates the ledger
        cannot say whether the book made money by choosing well or by being lucky in what
        it was shown.
        """
        now = obs.t_ingest_unix
        if obs.complete or obs.mint in self.pending:
            return
        if any(p.mint == obs.mint for p in self.positions.values()):
            return
        if now - self.last_decided.get(obs.mint, 0.0) < self.decision_cooldown_s:
            return
        self.last_decided[obs.mint] = now

        first_seen, count = self.seen.get(obs.mint, (now, 0))
        features = obs.features()
        features["observed_seconds"] = now - first_seen
        features["observations"] = float(count)
        if extra_features:
            features.update(extra_features)

        take_bps = self.friction.take_bps_for(obs.pool_label)
        size = self.friction.size_lamports(
            obs.vsol_lamports, bankroll_cap_lamports=min(self.free_lamports, self.bankroll_lamports)
        )
        actionable = self.friction.affordable(size, obs.vsol_lamports, take_bps=take_bps)

        decision = self.policy.decide(
            key=obs.mint,
            features=features,
            now_unix=now,
            decided_at=iso(now),
            size_lamports=size,
            actionable=actionable,
        )
        self.counters["decisions"] += 1
        if decision.explored:
            self.counters["explored"] += 1

        blocked: str | None = None
        if decision.acted:
            if self.breaker.paused(now):
                blocked = "circuit_breaker"
                self.counters["skipped_breaker"] += 1
            elif decision.size_lamports > self.free_lamports or decision.size_lamports <= 0:
                blocked = "bankroll"
                self.counters["skipped_bankroll"] += 1
            elif len(self.positions) + len(self.pending) >= self.max_positions:
                blocked = "max_positions"

        self.ledger.decision(
            book=str(self.book),
            record=decision.record(),
            t_ingest_unix=now,
            t_event_unix=obs.t_event_unix,
            t_event_source=obs.t_event_source,
            source=obs.source,
            blocked=blocked,
            **decision.ledger_fields(),
        )

        if not decision.acted or blocked is not None:
            return
        self.counters["enters"] += 1
        self.pending[obs.mint] = {
            "decision_id": decision.decision_id,
            "decided_unix": now,
            "size_lamports": decision.size_lamports,
            "deadline_unix": decision.deadline_unix,
            "take_profit": decision.thresholds["take_profit"],
            "stop_loss": decision.thresholds["stop_loss"],
            "deterioration_drawdown": decision.thresholds.get("deterioration_drawdown", 1.0),
            "deterioration_active_frac": decision.thresholds.get("deterioration_active_frac", 2.0),
            "pool_label": obs.pool_label,
        }

    # ---------------------------------------------------------------- persistence

    def state(self) -> dict[str, Any]:
        return {
            "pending": self.pending,
            "positions": {k: v.to_json() for k, v in self.positions.items()},
            "counters": self.counters,
            "seen": {k: list(v) for k, v in self.seen.items()},
        }

    def restore(self, state: dict[str, Any]) -> None:
        self.pending = dict(state.get("pending") or {})
        self.positions = {
            k: PaperPosition(**v) for k, v in (state.get("positions") or {}).items()
        }
        self.counters.update(state.get("counters") or {})
        self.seen = {
            k: (float(v[0]), int(v[1]))
            for k, v in (state.get("seen") or {}).items()
            if isinstance(v, list) and len(v) == 2
        }

    def drain(self, now: float | None = None) -> None:
        """Close everything still open, pessimistically, with the FULL row.

        The drain path is where the -151% bug lived. It goes through the same close
        builder as every other exit, so a partial row is not expressible here.
        """
        when = now if now is not None else time.time()
        for position in list(self.positions.values()):
            self._close_marked(
                position,
                now=when,
                reason="drain",
                close_reason=WatchClose.OPERATOR,
                total_loss=False,
            )
