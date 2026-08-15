"""The OPERATOR book: the wiggle book's execution, with the operator's taste as the entry.

THE EXPERIMENT, STATED AS AN EXPERIMENT
---------------------------------------
Every entry-selection study in this repo returned null -- the 108-cell board grid, the
bandit search, the callout arms, the exploration map's 542 cells of which 8 survived and
none cleared friction. One thing in the record is repeatedly positive and it is not a rule:
on the same pattern under the same clock, the rule-chosen wiggle book's first closes ran
**-14.08%** and the operator's hand-picked equivalents measured **+3.14%**.

That difference has exactly one candidate explanation and it is selection. This book is the
treatment arm that tests it:

======================  =========================  =========================
                        WIGGLE                     OPERATOR
======================  =========================  =========================
entry                   the jittered rule          a person, pointing
sizing                  0.1 SOL clip               the same clip
exit                    240-420 s, jittered        the same draw, same box
brackets                take_profit / stop_loss    the same box
friction                shared ``Friction``        the same object
marking                 next observation, censored the same code path
propensity              1 - eps / eps              1.0, exogenous
======================  =========================  =========================

Everything below the first row is *inherited*, not reimplemented, and that is load-bearing
rather than tidy: if the operator's arm had its own fill logic, its own clock or its own
friction, the difference between the two columns would be a difference between two programs
and the study would be unfalsifiable. :class:`OperatorBook` subclasses
:class:`~shitcoims_paperdesk.wiggle.WiggleBook` for the same reason the wiggle book
subclasses ``MintBook``.

THE GATES ARE COMPUTED AND THEY DO NOT GATE
-------------------------------------------
Every entry condition the wiggle rule would have applied is evaluated on the same drawn
thresholds and written onto the decision row as ``gates`` / ``gates_would_veto``. None of
them can stop an entry. Two reasons, and the second is the interesting one:

1. The operator's gesture IS the entry signal. A gate that vetoes it is measuring the rule,
   not the operator, and the rule is the thing under suspicion.
2. **Which gate disagrees with them, and whether that gate is right, is the beginning of
   distillation.** If ``two_sided`` vetoes forty hunches and thirty-five of those lose, the
   rule has found something the operator has not. If it vetoes forty and thirty win, the
   rule is what is wrong. Neither sentence is writable unless the veto is *logged and
   overruled*, which is what this book does. ``hunch report`` prints that table, descriptive
   only -- no model is fitted here, and nothing distils automatically.

THE GHOST-TOWN EXCEPTION
------------------------
One gate gets a louder treatment: depth. ``RESULT_crime_signatures.md`` §7.1 is about a
coin whose quoted market cap was a fossil -- ``$TOPG`` fell 98.3% in an hour because the
first real seller discovered the capacitance was gone. In that state there is no exit at the
quoted price *at all*, so the failure is not a bad trade, it is an unsellable bag. The
operator still outranks the gate; the gate still gets to shout. A hunch entered against a
failing depth leg is **tagged** on its rows (``ghost_town: true``) and the capture surface
prints the warning back in the operator's face at the moment of the click. Overruling a
warning you have read is a decision; not being told is a hole in the instrument.

WHY A HUNCH DOES NOT FILL AT THE MOMENT IT IS SPOKEN
-----------------------------------------------------
The desk's first accounting rule is that entries fill at the NEXT observation after the
decision, because filling at the snapshot that produced the decision is lookahead worth
several percent a round. A gesture is not an observation, so the sequence here is:

    hunch recorded -> first observation of the mint: decision logged (gates, propensity 1.0)
    -> next observation: FILL -> clock -> close

which costs one refresh interval (~8 s, the wiggle priority cadence) and buys the same
pessimism every other book pays. A gesture the desk cannot observe within
:data:`WAIT_TIMEOUT_S` never becomes a position, and says so on a row: the hunch survives on
the tape, the fill does not get invented.

DOWN, UP AND WATCH ARE NOT POSITIONS
------------------------------------
There is no short on this desk, and the only execution it has measured is a five-minute
scalp. So ``down`` / ``up`` / ``watch`` hunches compile to a :class:`Watch` -- a claim with
a horizon, an invalidation level and a scoring hook, exactly ``design/domain-model.md`` §6's
``Expectation`` minus the compiler's proposal diff. They consume no capital, they are marked
off the same observations, and at their horizon they are SCORED (Brier for the directional
claims, direction-free statistics for ``watch``). A claim whose horizon arrives while the
coin is unobservable resolves **censored**, recorded and counted, never dropped.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Final

from shitcoims_paperdesk.feeds import MintObservation
from shitcoims_paperdesk.hunch import HUNCH_ACTIONABLE_S, Hunch, Retraction
from shitcoims_paperdesk.ledger import iso
from shitcoims_paperdesk.wiggle import WiggleBook, WiggleWatch

__all__ = [
    "ANY_BASIS",
    "OPERATOR_SOURCE",
    "WAIT_TIMEOUT_S",
    "OperatorBook",
    "Watch",
    "brier",
]

#: The pending-entry sentinel meaning "fill on whatever venue this coin is first observed
#: on". Every other book decides against an observation and therefore already knows the
#: price basis it sized against; a gesture does not name a venue, and demanding one would
#: mean silently dropping hunches on graduated coins.
ANY_BASIS: Final[str] = "\x00any"

#: Stamped on every position this book opens, in place of the feed that happened to deliver
#: the filling tick. The provenance of an operator position is the operator; the observation
#: that filled it is still named on the fill row, so nothing is lost by saying so.
OPERATOR_SOURCE: Final[str] = "operator"

#: How long a recorded hunch may wait for its first observation before the desk gives up.
#: Set to the wiggle book's departure timeout, because a coin the desk cannot see inside one
#: departure window is a coin it could not have exited on the clock either.
WAIT_TIMEOUT_S: Final[float] = 420.0

#: How many acted-on hunch ids the book carries across restarts. The tape is replayed from
#: the start on every boot, so this set is what makes acting on a hunch idempotent; it is
#: bounded because it is a dedupe cache, not the record (the record is the tape).
ACTED_CAPACITY: Final[int] = 20_000


def brier(confidence: float, outcome: int) -> float:
    """``(p - o)^2``. One claim's contribution to the calibration score.

    Kept as a named function with a name from the literature rather than inlined, because
    the number it produces is the one thing on the operator's scorecard that is not
    self-explanatory: LOWER is better, 0.25 is the score of always saying 0.5, and anything
    above 0.25 means the declared confidence was worse than a coin flip.
    """
    return (float(confidence) - float(outcome)) ** 2


@dataclass
class Watch:
    """A claim with a horizon and no capital: the ``down`` / ``up`` / ``watch`` kinds.

    Field-for-field this is ``Expectation`` in flight -- the utterance, the claim, the
    declared confidence that Brier will score, the invalidation level that makes it a
    position in belief-space with a stop, and the resolution clock. It is serialised whole
    into the desk state, so a claim survives a restart mid-horizon; a scorecard that
    silently loses its long claims is a scorecard biased toward the short ones.
    """

    hunch_id: str
    mint: str
    claim: str
    utterance: str
    confidence: float
    horizon_s: float
    recorded_unix: float
    basis: str | None = None
    entry_price: float | None = None
    entry_unix: float | None = None
    invalidation: float | None = None
    last_price: float | None = None
    last_unix: float | None = None
    peak_price: float | None = None
    trough_price: float | None = None
    observations: int = 0
    falsified_unix: float | None = None

    @property
    def deadline_unix(self) -> float:
        return self.recorded_unix + self.horizon_s

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class OperatorBook(WiggleBook):
    """The fifth book. Same machine, different hand on the entry.

    Adds exactly four things to :class:`~shitcoims_paperdesk.wiggle.WiggleBook`, and nothing
    that touches filling, marking, censoring or the close row:

    * :attr:`waiting` -- hunches recorded and awaiting their first observation;
    * :attr:`watches` -- non-positional claims with horizons;
    * :attr:`acted` -- the idempotence set that makes replaying the hunch tape safe;
    * a decision path that always enters, logs the gates, and tags the ghost-town case.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.waiting: dict[str, dict[str, Any]] = {}
        self.watches: dict[str, Watch] = {}
        self.acted: list[str] = []
        self._acted_set: set[str] = set()
        self.counters.setdefault("hunches", 0)
        self.counters.setdefault("hunches_expired", 0)
        self.counters.setdefault("watches", 0)
        self.counters.setdefault("watches_resolved", 0)
        self.counters.setdefault("watches_censored", 0)
        self.counters.setdefault("falsified", 0)
        self.counters.setdefault("ghost_town_entries", 0)
        self.counters.setdefault("retractions", 0)

    # ---------------------------------------------------------------- intake

    def _remember(self, hunch_id: str) -> None:
        self._acted_set.add(hunch_id)
        self.acted.append(hunch_id)
        if len(self.acted) > ACTED_CAPACITY:
            dropped = self.acted[: ACTED_CAPACITY // 4]
            del self.acted[: ACTED_CAPACITY // 4]
            self._acted_set.difference_update(dropped)

    def accept(self, hunch: Hunch, now: float) -> str:
        """Take one hunch off the tape. Returns what the desk did with it, and logs it.

        Every branch writes a ``hunch`` row, including the refusals, because a refusal is
        the most informative thing this book can record: it says the operator asked for
        something and the desk could not honour it, which is a fact about the INSTRUMENT and
        would otherwise be invisible behind a hunch that merely never appears in the P&L.
        """
        if hunch.hunch_id in self._acted_set:
            return "duplicate"
        self._remember(hunch.hunch_id)
        self.counters["hunches"] += 1

        common: dict[str, Any] = {
            "t_ingest_unix": now,
            # The event clock on this row is the GESTURE. The desk's own ingest clock says
            # when it read the tape, and the gap between them is how long the operator's
            # hand was ahead of the machine -- worth being able to measure.
            "t_event_unix": hunch.t_gesture_unix,
            "t_event_source": "operator:gesture",
            "key": hunch.mint,
            "hunch_id": hunch.hunch_id,
            "utterance": hunch.utterance,
            "claim": hunch.claim,
            "kind": hunch.kind,
            "confidence": hunch.confidence,
            "symbol": hunch.symbol,
            "hunch_run_id": hunch.run_id,
            "resolution": hunch.resolution,
            "gesture_lag_s": now - hunch.t_gesture_unix,
        }

        age = now - hunch.t_gesture_unix
        if age > HUNCH_ACTIONABLE_S:
            self.counters["hunches_expired"] += 1
            self.ledger.emit(
                "hunch",
                str(self.book),
                **common,
                detail="expired_before_the_desk_saw_it",
                # Said plainly on the row: this is a hole in OUR observation, not a
                # judgement about the coin or the call.
                censor_reason="OBSERVER_LOST",
                actionable_bound_s=HUNCH_ACTIONABLE_S,
            )
            return "expired"

        if hunch.claim != "wiggle":
            horizon = hunch.horizon_s or 3_600.0
            self.watches[hunch.hunch_id] = Watch(
                hunch_id=hunch.hunch_id,
                mint=hunch.mint,
                claim=hunch.claim,
                utterance=hunch.utterance,
                confidence=hunch.confidence,
                horizon_s=horizon,
                recorded_unix=now,
            )
            self.counters["watches"] += 1
            self.ledger.emit(
                "expectation",
                str(self.book),
                **common,
                detail="recorded",
                horizon_s=horizon,
                resolves_at=iso(now + horizon),
            )
            return "watching"

        if hunch.mint in self.waiting:
            # ``waiting`` is keyed by MINT, because a coin can have at most one pending
            # entry. Two gestures on one coin inside one wait window would therefore have
            # silently overwritten the first, leaving a hunch that was acknowledged as
            # accepted and then never resolved by anything -- the exact failure mode this
            # book exists to make impossible, in the book itself. The second gesture is a
            # fact and gets a row; it does not get a second position, because that would
            # double the clip behind what is plainly one call.
            self.ledger.emit(
                "hunch",
                str(self.book),
                **common,
                detail="already_awaiting_on_this_mint",
                awaiting=self.waiting[hunch.mint]["hunch_id"],
            )
            return "already_waiting"

        self.waiting[hunch.mint] = {
            "hunch_id": hunch.hunch_id,
            "recorded_unix": now,
            "size_lamports": hunch.size_lamports or self.clip_lamports,
            "utterance": hunch.utterance,
            "confidence": hunch.confidence,
            "symbol": hunch.symbol,
            "gesture_unix": hunch.t_gesture_unix,
        }
        self.ledger.emit(
            "hunch",
            str(self.book),
            **common,
            detail="accepted_awaiting_first_observation",
            size_lamports=hunch.size_lamports or self.clip_lamports,
            wait_timeout_s=WAIT_TIMEOUT_S,
        )
        return "accepted"

    def retract(self, retraction: Retraction, now: float) -> str:
        """"That was not a gesture." Drops it from the live book; the tape keeps both rows.

        What this CAN undo is everything the desk has not done yet: a hunch still waiting for
        its first observation, and a standing expectation. What it cannot undo is a FILL --
        a paper position that already opened is a thing that happened at a price, and
        deleting it would make the operator book's P&L a function of what the operator later
        wished. So a retraction arriving after the fill is recorded against the position and
        the clock still closes it. The report can then exclude retracted rows honestly,
        which is a decision made at analysis time on visible data rather than by quietly
        losing a row.
        """
        self._remember(retraction.retracts)
        state = "not_found"
        for mint, waiting in list(self.waiting.items()):
            if waiting["hunch_id"] == retraction.retracts:
                del self.waiting[mint]
                state = "withdrawn_before_entry"
        if retraction.retracts in self.watches:
            del self.watches[retraction.retracts]
            state = "expectation_withdrawn"
        for mint, pending in list(self.pending.items()):
            if pending.get("hunch_id") == retraction.retracts:
                del self.pending[mint]
                state = "withdrawn_before_fill"
        if state == "not_found":
            state = "retracted_after_position_opened_or_already_resolved"
        self.counters["retractions"] += 1
        self.ledger.emit(
            "hunch",
            str(self.book),
            t_ingest_unix=now,
            t_event_unix=retraction.t_event_unix,
            t_event_source="operator:retraction",
            hunch_id=retraction.retracts,
            detail=f"retracted:{state}",
            reason=retraction.reason,
        )
        return state

    @property
    def mints_of_interest(self) -> set[str]:
        """Every mint this book needs observed: positions, pendings, waits and watches.

        The desk feeds this to :class:`~shitcoims_paperdesk.feeds.MintRefreshSource`. A
        watch with no observations cannot be scored and would resolve censored -- which
        would be a true statement about a desk that forgot to look, and a useless one.
        """
        return (
            {p.mint for p in self.positions.values()}
            | set(self.pending)
            | set(self.waiting)
            | {w.mint for w in self.watches.values()}
        )

    # ---------------------------------------------------------------- observing

    def observe(self, obs: MintObservation, *, source_stale: bool) -> None:
        """Adopt the venue for a waiting hunch, then everything the wiggle book does.

        The basis fix-up happens BEFORE ``super().observe`` because that is where the fill
        runs, and a pending whose ``pool_label`` still says "any" would be refused by the
        base class's basis check -- correctly, since marking a position across two venues is
        the fabricated-loss defect ``_same_price_basis`` exists to prevent. Adopting the
        first observed basis is not a relaxation of that rule: from the fill onward, the
        position is pinned to one venue like every other.
        """
        pending = self.pending.get(obs.mint)
        if pending is not None and pending.get("pool_label") == ANY_BASIS:
            pending["pool_label"] = obs.pool_label

        opened = set(self.positions)
        super().observe(obs, source_stale=source_stale)
        for position_id in set(self.positions) - opened:
            self.positions[position_id].source = OPERATOR_SOURCE

        self._observe_watches(obs)

    def consider(
        self, obs: MintObservation, *, extra_features: dict[str, float] | None = None
    ) -> None:
        """Refuse to be driven by the feeds. The ONLY entry into this book is a gesture.

        The desk routes every board and callout observation to every book's ``consider``.
        Letting those through here would fill the operator book with rule-chosen entries
        under the label "operator", which is the one thing that would destroy the
        comparison -- silently, and in a direction that flatters nothing in particular.
        Entries arrive through :meth:`accept` and are armed by :meth:`arm_waiting`.
        """
        return

    def arm_waiting(self, obs: MintObservation) -> None:
        """First observation of a waited-on mint: log the decision and open the pending.

        This is the operator book's whole decision path, and it is deliberately the ONLY
        place in this module that touches the policy. The propensity is 1.0, the action is
        ``enter``, the gates are computed against the same drawn thresholds the wiggle book
        would have used, and none of them can stop it.
        """
        waiting = self.waiting.get(obs.mint)
        if waiting is None:
            return
        if obs.mint in self.pending:
            # An entry from an earlier gesture is already queued on this coin. Drop the
            # wait NOW with the accurate reason rather than leaving it to time out as
            # "never observed" -- it was observed, and a wrong reason on a row is worse
            # than a missing one because it reads as a measurement of the feed.
            del self.waiting[obs.mint]
            self.ledger.emit(
                "hunch",
                str(self.book),
                t_ingest_unix=obs.t_ingest_unix,
                t_event_unix=waiting["gesture_unix"],
                t_event_source="operator:gesture",
                key=obs.mint,
                hunch_id=waiting["hunch_id"],
                detail="entry_already_queued_for_this_mint",
            )
            return
        if any(p.mint == obs.mint for p in self.positions.values()):
            # Already in it from an earlier hunch on the same coin. The gesture stands on
            # the tape; a second concurrent position would double the clip behind one call.
            del self.waiting[obs.mint]
            self.ledger.emit(
                "hunch",
                str(self.book),
                t_ingest_unix=obs.t_ingest_unix,
                t_event_unix=waiting["gesture_unix"],
                t_event_source="operator:gesture",
                key=obs.mint,
                hunch_id=waiting["hunch_id"],
                detail="already_holding_this_mint",
            )
            return
        del self.waiting[obs.mint]

        now = obs.t_ingest_unix
        watch = self.watch.get(obs.mint) or WiggleWatch()
        features = watch.features(
            friction=self.friction, obs=obs, clip_lamports=self.clip_lamports
        )
        features.update(obs.features())
        first_seen, count = self.seen.get(obs.mint, (now, 0))
        features["observed_seconds"] = now - first_seen
        features["observations"] = float(count)
        # The operator's own reaction time, as a feature. Nothing conditions on it; it is
        # here because a distillation model fitted to this tape will want to know whether
        # fast calls and slow calls are the same animal.
        features["gesture_lag_s"] = now - float(waiting["gesture_unix"])

        size = min(int(waiting["size_lamports"]), self.free_lamports, self.bankroll_lamports)
        take_bps = self.friction.take_bps_for(obs.pool_label)
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
        ghost = not decision.gates.get("depth", True)
        if ghost:
            self.counters["ghost_town_entries"] += 1

        blocked: str | None = None
        if size <= 0:
            # Not a gate: there is no capital. A hunch cannot conjure bankroll, and pretending
            # otherwise would put a position on the books that the desk could not have taken.
            blocked = "bankroll"
            self.counters["skipped_bankroll"] += 1
        elif len(self.positions) + len(self.pending) >= self.max_positions:
            blocked = "max_positions"

        self.ledger.decision(
            book=str(self.book),
            record=decision.record(),
            t_ingest_unix=now,
            t_event_unix=float(waiting["gesture_unix"]),
            t_event_source="operator:gesture",
            source=OPERATOR_SOURCE,
            blocked=blocked,
            hunch_id=waiting["hunch_id"],
            utterance=waiting["utterance"],
            confidence=waiting["confidence"],
            ghost_town=ghost,
            observed_source=obs.source,
            **decision.ledger_fields(),
        )
        if blocked is not None:
            return

        entry = self._pending_entry(obs, decision)
        if entry is None:
            return
        entry["pool_label"] = ANY_BASIS if obs.pool_label is None else obs.pool_label
        entry["hunch_id"] = waiting["hunch_id"]
        entry["ghost_town"] = ghost
        self.counters["enters"] += 1
        self.pending[obs.mint] = entry

    def _size_for(self, obs: MintObservation) -> int:  # pragma: no cover - not on this path
        """Unused: this book sizes from the gesture's own clip in :meth:`arm_waiting`."""
        return super()._size_for(obs)

    # ---------------------------------------------------------------- watches

    def _observe_watches(self, obs: MintObservation) -> None:
        """Mark every non-positional claim on this coin, and fire the falsifier if it trips."""
        for watch in self.watches.values():
            if watch.mint != obs.mint:
                continue
            if watch.entry_price is None:
                watch.entry_price = obs.price
                watch.entry_unix = obs.t_ingest_unix
                watch.basis = obs.pool_label
                watch.peak_price = watch.trough_price = obs.price
                watch.invalidation = self._invalidation(watch, obs.price)
                continue
            if watch.basis != obs.pool_label:
                # Same refusal as ``_same_price_basis``: a curve quote and a pool quote are
                # two scales, and a claim scored across them is scored against a migration.
                continue
            watch.last_price = obs.price
            watch.last_unix = obs.t_ingest_unix
            watch.peak_price = max(watch.peak_price or obs.price, obs.price)
            watch.trough_price = min(watch.trough_price or obs.price, obs.price)
            watch.observations += 1
            if watch.falsified_unix is None and self._falsified(watch, obs.price):
                watch.falsified_unix = obs.t_ingest_unix
                self.counters["falsified"] += 1
                self.ledger.emit(
                    "expectation",
                    str(self.book),
                    t_ingest_unix=obs.t_ingest_unix,
                    t_event_unix=obs.t_event_unix,
                    t_event_source=obs.t_event_source,
                    key=watch.mint,
                    hunch_id=watch.hunch_id,
                    claim=watch.claim,
                    utterance=watch.utterance,
                    detail="falsifier_tripped",
                    # An expectation is a position in belief-space and gets a stop. This row
                    # is that stop firing: not an automatic withdrawal, a PROMPT -- the glass
                    # and the report both surface it and the operator decides.
                    entry_price=watch.entry_price,
                    invalidation=watch.invalidation,
                    price=obs.price,
                    seconds_in=obs.t_ingest_unix - float(watch.entry_unix or obs.t_ingest_unix),
                )

    def _invalidation(self, watch: Watch, price: float) -> float | None:
        """The level at which the claim is in trouble, drawn from the wiggle bracket.

        Not a round number and not a preference: it is a move of the size the wiggle book
        would have called a WIN, drawn from that book's own ``take_profit`` box. A claim
        that "this keeps going down", contradicted by a rise big enough to have been worth
        trading, is a claim whose author should be asked again -- and sizing the falsifier
        off anything smaller would fire it on friction-scale noise.
        """
        move = self.policy.draw().get("take_profit", 0.06)
        if watch.claim == "drift_down":
            return price * (1.0 + move)
        if watch.claim == "drift_up":
            return price * (1.0 - move)
        return None

    @staticmethod
    def _falsified(watch: Watch, price: float) -> bool:
        if watch.invalidation is None:
            return False
        if watch.claim == "drift_down":
            return price >= watch.invalidation
        if watch.claim == "drift_up":
            return price <= watch.invalidation
        return False

    def resolve_watches(self, now: float, *, source_stale: bool) -> None:
        """Score every claim whose horizon has arrived. Censoring is a RESULT, not a gap."""
        for hunch_id, watch in list(self.watches.items()):
            if now < watch.deadline_unix:
                continue
            del self.watches[hunch_id]
            common: dict[str, Any] = {
                "t_ingest_unix": now,
                "key": watch.mint,
                "hunch_id": hunch_id,
                "claim": watch.claim,
                "utterance": watch.utterance,
                "confidence": watch.confidence,
                "horizon_s": watch.horizon_s,
                "observations": watch.observations,
                "entry_price": watch.entry_price,
                "last_price": watch.last_price,
                "peak_price": watch.peak_price,
                "trough_price": watch.trough_price,
                "falsified_at": iso(watch.falsified_unix) if watch.falsified_unix else None,
            }
            if watch.entry_price is None or watch.last_price is None or watch.entry_price <= 0:
                self.counters["watches_censored"] += 1
                self.ledger.emit(
                    "expectation",
                    str(self.book),
                    **common,
                    detail="censored",
                    censor_reason=("OBSERVER_LOST" if source_stale else "DISPLACED"),
                    # Counted in the denominator on the scorecard, exactly as a censored
                    # position is counted in the book's. A calibration rate computed only
                    # over the claims that stayed observable is the +21.77% error wearing a
                    # different hat.
                    note=(
                        "the horizon arrived and the coin was not observable;"
                        " scored as neither right nor wrong"
                    ),
                )
                continue

            change = watch.last_price / watch.entry_price - 1.0
            if watch.claim == "drift_down":
                # PESSIMISTIC: a tie scores against the claim. Unchanged is not "down".
                outcome = 1 if watch.last_price < watch.entry_price else 0
            elif watch.claim == "drift_up":
                outcome = 1 if watch.last_price > watch.entry_price else 0
            else:
                outcome = None
            self.counters["watches_resolved"] += 1
            realised_range = (
                (watch.peak_price / watch.trough_price - 1.0)
                if watch.peak_price and watch.trough_price
                else None
            )
            self.ledger.emit(
                "expectation",
                str(self.book),
                **common,
                detail="resolved",
                change=change,
                log_change=math.log1p(change) if change > -1.0 else None,
                realised_range=realised_range,
                outcome=outcome,
                brier=brier(watch.confidence, outcome) if outcome is not None else None,
            )

    # ---------------------------------------------------------------- sweeping

    def sweep(self, now: float, *, source_stale: bool) -> None:
        super().sweep(now, source_stale=source_stale)
        for mint, waiting in list(self.waiting.items()):
            if now - float(waiting["recorded_unix"]) < WAIT_TIMEOUT_S:
                continue
            del self.waiting[mint]
            self.counters["hunches_expired"] += 1
            self.ledger.emit(
                "hunch",
                str(self.book),
                t_ingest_unix=now,
                t_event_unix=float(waiting["gesture_unix"]),
                t_event_source="operator:gesture",
                key=mint,
                hunch_id=waiting["hunch_id"],
                utterance=waiting["utterance"],
                detail="never_observed_no_position_opened",
                censor_reason=("OBSERVER_LOST" if source_stale else "DISPLACED"),
                waited_s=now - float(waiting["recorded_unix"]),
            )
        self.resolve_watches(now, source_stale=source_stale)

    # ---------------------------------------------------------------- persistence

    def state(self) -> dict[str, Any]:
        return {
            **super().state(),
            "waiting": self.waiting,
            "watches": {k: v.to_json() for k, v in self.watches.items()},
            "acted": self.acted,
        }

    def restore(self, state: dict[str, Any]) -> None:
        super().restore(state)
        self.waiting = dict(state.get("waiting") or {})
        self.watches = {}
        for key, payload in (state.get("watches") or {}).items():
            try:
                self.watches[key] = Watch(**payload)
            except TypeError:
                # A watch written by an older shape is dropped from the LIVE set and stays
                # on the ledger, where its ``recorded`` row already is. Refusing to restore
                # a record we cannot interpret beats restoring it wrong and scoring it.
                continue
        self.acted = [str(x) for x in (state.get("acted") or [])]
        self._acted_set = set(self.acted)
