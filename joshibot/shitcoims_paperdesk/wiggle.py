"""The WIGGLE book: post-collapse bottom scalps on a hard clock. The anti-hold book.

WHY THIS BOOK EXISTS, AND WHY IT IS DELIBERATELY THE OPPOSITE OF THE OTHERS
---------------------------------------------------------------------------
The operator's live trading was reconstructed from chain over a 36 h window, and the
result was not "the method is wrong". Split by holding time it is two different traders:

    holding time     round trips    winners    net
    under 5 min          13          7 / 13    +$3.09
    every bucket beyond  20          1 / 20    -$61

The method works. The leak is **discipline drift** -- a scalp that stops being a scalp and
becomes a hold. That is a behavioural failure, not an analytical one, and it is the kind of
failure a rule can actually fix, because it needs no forecast: it needs a clock.

So this book has exactly one exit philosophy and it is not negotiable. A position leaves at
a jittered five minutes, or earlier on a wiggle-up bracket. It never leaves later. There is
no deterioration arm, no trailing stop that could extend the hold, and no path in this
module by which a deadline moves outward once set. The other three books hold; this one
does not, and the whole comparison depends on nobody splitting the difference.

TWO POPULATIONS, TWO DISCIPLINES
--------------------------------
This is not a claim that holding is wrong. It is a claim that *which* coin you are holding
decides:

* a **quality-cluster bag** (DREGG, SOLVE, weave, nosis -- coins with a real pool, a real
  community, and a measured fee stream) is held unless it rugs. That is the MEDIUM book.
* a **ghost-town bottom** is a price nobody has tested, and holding one is not patience, it
  is being the last bid. That is this book, and it gets a clock.

``studies/RESULT_crime_signatures.md`` §7.1 is where the second half of that comes from,
and it is worth quoting because it is the entry rule's whole justification: ``$TOPG`` fell
**-98.3% in a single hour** from $3.0M with starvation at the 92nd percentile and turnover
at the 91st. "Nobody was trading it; the quoted market cap was a fossil -- a price nobody
had tested, and the 'rug' is just the first real seller discovering that the capacitance
was gone." In the circuit frame that is ``dV = dQ/C`` with ``C -> 0``. **For an operator,
GHOST_TOWN is the more dangerous archetype than METERED_CLIMB, because there is no exit at
the quoted price at all.**

THE GHOST-TOWN GUARD, DERIVED RATHER THAN PICKED
------------------------------------------------
The guard therefore refuses entries where *our own exit is the cliff*, and the bound comes
from the clip size against the pool depth rather than from a round number. Under the
constant-product linearisation that ``shitcoims_scalper.policy.round_trip_friction`` already
uses, a clip of ``B`` into a pool holding ``Y`` SOL moves the price by ``B / Y`` on the way
in and again on the way out. At the operator's own 0.1 SOL clip:

======================  ==============  =================================================
pool depth ``Y``        one-way impact  reading
======================  ==============  =================================================
5 SOL                   2.00%           PROGRAM.md §1.4's impact ceiling exactly. At this
                                        depth the exit costs as much as the smallest
                                        bracket earns; it is the floor, not a target.
10 SOL                  1.00%           impact is a fifth of a 5% bracket.
25 SOL                  0.40%           impact is under a tenth of the bracket -- the
                                        wiggle is the market's, not ours.
======================  ==============  =================================================

So the jitter box for ``ghost_min_pool_sol`` is **[5, 25] SOL**, both endpoints derived
above, and the propensity log turns the choice between them into something the ledger can
settle rather than something this docstring has to be right about.

**WHERE THIS GUARD DOES AND DOES NOT BIND, stated because it is not obvious.** On a
bonding curve the depth is the VIRTUAL reserve, which the launch parameters floor at 30
SOL -- so the depth leg is slack for every pre-graduation mint by construction, and that is
correct rather than a hole: a curve is an AMM with guaranteed liquidity, so you can always
sell into it at the curve price for an impact of ``B / Y``. There is no ``C -> 0`` on a
curve. GHOST_TOWN in the ``$TOPG`` sense is a **post-graduation** condition, where the
counterparty is a pool with a real vault balance that can be drained to nothing, and that
is exactly where this leg starts binding.

Which makes the OTHER half of the guard the one that does the work pre-graduation. A fossil
quote is thin *and* stale, and on a curve only the staleness is available: the rule demands
recent trading and, where the desk has seen the coin more than once, evidence that the price
has actually moved BOTH WAYS. That is the thing a wiggle-scalper is paid for; a one-way
slide into a curve with 30 SOL of virtual depth clears every impact test and has nothing
whatsoever to harvest.

WHAT THE ENTRY RULE INHERITS FROM THE STUDY, AND WHAT IT DOES NOT
------------------------------------------------------------------
``studies/RESULT_callout_volatility.md`` asked whether callout activity marks harvestable
two-sided flow, conditional on market cap and age, over 337 treated and 169 matched control
rows on 428 mints. Its verdict, in the order it changes decisions:

1. **Callouts do not predict realized volatility.** Conditional on the free columns, every
   ``rv`` cell is flat (|z| 0.3-1.8, none surviving BY-FDR under the flow-controlled
   specification). Whatever a callout is, it is not a volatility forecast.
2. **Callouts DO mark two-sided flow and wiggle amplitude**, strongly, and the effect
   clears BOTH nulls -- rotation (timing) and mint-swap (identity) -- at each null's own
   p floor of 0.005 over 200 draws.
3. **And it is redundant.** Partial out the trades already visible on chain in the ten
   minutes BEFORE the callout, and the observed max |z| falls from 6.29 to 4.35 against a
   flow-controlled rotation null whose own median is 3.79: **p = 0.31**. The callout is a
   slower view of a variable the operator can read directly, which is exactly what
   ``RESULT_caller_wallets.md`` predicted when it measured the callout arriving a median
   26 s after the buy burst it echoes.

So ``CALLOUT_ARM`` is ``"ignored"``: the callout feed remains a **candidate generator** --
:class:`~shitcoims_paperdesk.feeds.CalloutSource` still routes mints into the desk's view
that the boards may never carry -- and is **not an entry condition**. That is the same
conclusion ``RESULT_callout_edge.md`` §6 reached about direction, now independently reached
about volatility, and the entry rule conditions on the thing that survived instead:
observed two-sided flow.

``callout_n_60m`` is still written into every logged feature vector. Nothing acts on it, so
it costs nothing, and because the epsilon arm gives overlap on the action it stays
identifiable off-policy -- which is how "should it gate after all?" gets settled by the
ledger rather than by re-reading this docstring.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, Deque, Final

from shitcoims_paperdesk import Book
from shitcoims_paperdesk.books import MintBook
from shitcoims_paperdesk.feeds import MintObservation
from shitcoims_paperdesk.friction import Friction

# One zigzag, not two. ``studies.callout_volatility`` derived and validated it and the desk
# must score its candidates with the same estimator the study scored the corpus with, or
# "wiggle" means one thing in the RESULT and another on the book. Precedent: ``friction.py``
# imports the LP constants from the study that derived them for exactly this reason.
from studies.callout_volatility import zigzag

__all__ = [
    "CALLOUT_ARM",
    "CALLOUT_WINDOW_S",
    "WIGGLE_DEPARTURE_TIMEOUT_S",
    "CalloutActivity",
    "WiggleBook",
    "WiggleWatch",
    "ghost_town_impact",
]

#: How long a wiggle position may go unobserved before the desk stops pretending it is
#: still marking it. The mint books allow 600 s; that is TWICE this book's entire holding
#: horizon, and a five-minute book that will sit unmarked for ten minutes is not a
#: five-minute book. 420 s is the clock's own upper jitter bound plus one refresh interval.
WIGGLE_DEPARTURE_TIMEOUT_S: Final[float] = 420.0

#: How many recent observations of a mint the wiggle watch keeps. At the boards cadence
#: (~37 s per board, and a mint typically sits on more than one) this is roughly the last
#: fifteen minutes -- long enough to contain several five-minute scalps, short enough that
#: an hour-old oscillation is not counted as present evidence.
WATCH_DEPTH: Final[int] = 48

#: How many mints the watch remembers at once. The boards tape carries 15,300 distinct
#: mints over a day; the watch is a working set, not an archive, and it is deliberately
#: NOT persisted across restarts -- two minutes of observations rebuild it, and a
#: reconstructed one is honest where a stale one restored from disk would claim evidence
#: about a price path the desk did not actually watch.
WATCH_CAPACITY: Final[int] = 4_000

#: The verdict of ``studies/RESULT_callout_volatility.md``, carried as ONE constant so that
#: re-running the study on a wider tape moves one line rather than three call sites.
#: ``"required"``  -- callout activity is a measured precondition; entry needs it.
#: ``"preferred"`` -- it beats its nulls but not the flow it echoes, so it relaxes the
#:                    two-sidedness bar rather than gating on its own.
#: ``"ignored"``   -- it adds nothing over on-chain flow (p = 0.31 flow-controlled); the
#:                    feed is a candidate generator and the rule conditions on flow.
#: CURRENT: ``"ignored"``, on 337 treated rows over one 9.6 h window. That is one window of
#: one day and this market's regime shifts in weeks (PROGRAM.md §3.6), so it is a verdict
#: with an expiry date, not a law.
CALLOUT_ARM: Final[str] = "ignored"


#: The window over which callout activity is counted, matching the study's exposure window
#: exactly so that ``callout_n_60m`` on a ledger row and ``n_callouts`` in the RESULT are
#: the same quantity rather than two things with the same name.
CALLOUT_WINDOW_S: Final[float] = 3_600.0


@dataclass
class CalloutActivity:
    """Per-mint callout counts over the last hour. Logged on every decision, gating none.

    The study demoted callouts from an entry condition to a candidate generator (see the
    module docstring, item 3), so this exists to keep the column MEASURABLE rather than to
    make it act. Because the epsilon arm gives overlap on the action, a logged-but-unused
    feature is still identifiable off-policy -- so ``shitcoims_replay.ope`` can score "the
    same book, but requiring a callout" off this ledger without the desk ever having run
    that policy. That is the whole reason the desk logs skips.

    Timestamps come from ``t_event`` where the source has one. The callout feed is the only
    source on the desk that carries a real event clock (the post's own time), and using our
    ingest clock instead would make ``recency`` a measurement of the poll interval -- the
    exact error ``feeds.py``'s first refusal exists to prevent.
    """

    window_s: float = CALLOUT_WINDOW_S
    seen: dict[str, list[float]] = field(default_factory=dict)

    def record(self, mint: str, t_event_unix: float) -> None:
        self.seen.setdefault(mint, []).append(float(t_event_unix))

    def expire(self, now: float) -> None:
        cutoff = now - self.window_s
        for mint in list(self.seen):
            kept = [t for t in self.seen[mint] if t >= cutoff]
            if kept:
                self.seen[mint] = kept
            else:
                del self.seen[mint]

    def features(self, mint: str, now: float) -> dict[str, float]:
        times = sorted(t for t in self.seen.get(mint, ()) if t >= now - self.window_s)
        gaps = [b - a for a, b in pairwise(times)]
        return {
            "callout_n_60m": float(len(times)),
            # ``window_s`` for "no callout observed", never 0.0: a zero would read as a
            # callout this instant, which is the loudest possible value of the column.
            "callout_recency_s": (now - times[-1]) if times else self.window_s,
            "callout_cadence_s": (sum(gaps) / len(gaps)) if gaps else self.window_s,
        }


def ghost_town_impact(clip_lamports: int, pool_sol_lamports: int) -> float:
    """One-way price impact of our own clip: ``B / Y``. The whole guard in one line.

    Not a fee and not a spread -- the amount by which the act of leaving moves the price
    against us. When it approaches the bracket we are trying to earn, the wiggle we would
    be harvesting is our own, and ``C -> 0`` is the name for what happens next.
    """
    if clip_lamports <= 0 or pool_sol_lamports <= 0:
        return float("inf")
    return clip_lamports / pool_sol_lamports


@dataclass
class WiggleWatch:
    """Per-mint oscillation evidence, measured on what the desk has actually observed.

    ``two_sided_frac`` is the share of consecutive observation pairs whose price direction
    differs from the pair before. A coin sliding steadily to zero scores ~0; a coin
    oscillating scores ~1. It is the cheapest available stand-in for "buys AND sells are
    both happening", because a board snapshot carries a price and a last-trade stamp but
    never a side -- and inventing a side from a price move would put a guess in the same
    field as a measurement.

    ``wiggle_n`` / ``wiggle_amp`` are the study's zigzag at the coin's own round-trip cost,
    so a "wiggle" on this desk is the same object the RESULT measured.
    """

    prices: Deque[float] = field(default_factory=lambda: deque(maxlen=WATCH_DEPTH))
    times: Deque[float] = field(default_factory=lambda: deque(maxlen=WATCH_DEPTH))
    #: The venue the stored prices are quoted on. A bonding curve carries 30+ SOL of
    #: VIRTUAL reserves against a billion tokens; a graduated pool carries real vault
    #: balances. The same mint quoted on both is two series with no common scale, and
    #: splicing them would manufacture a several-hundred-percent "wiggle" out of a
    #: migration. Same defect ``MintBook._same_price_basis`` exists to prevent, same fix.
    basis: str | None = None
    basis_changes: int = 0

    def observe(self, price: float, now: float, *, basis: str | None = None) -> None:
        if not (price > 0 and math.isfinite(price)):
            return
        if self.prices and basis != self.basis:
            self.prices.clear()
            self.times.clear()
            self.basis_changes += 1
        self.basis = basis
        self.prices.append(price)
        self.times.append(now)

    @property
    def observations(self) -> int:
        return len(self.prices)

    def moves(self) -> int:
        """How many times the price actually CHANGED across the stored path.

        Split out because :meth:`two_sided_frac` returns ``0.0`` for two states that a
        DISPLAY must not merge: a coin whose price moved several times and never reversed
        (a measured zero -- a one-way slide, which is exactly what the wiggle rule wants to
        refuse), and a coin whose price has not moved at all or moved once (unmeasured --
        there is no second move to compare a direction against).

        The RULE is right to treat both as failing, and does: ``>= bar`` with ``bar > 0``
        rejects either. A CARD is not, because "this thing is dead flat" and "we have not
        seen enough of it yet" are different things to put in front of somebody about to
        commit 0.1 SOL. Measured on the live boards: a coin can sit on five boards for 80
        sightings with ONE distinct price, and the card was rendering that as 0% two-sided
        beside a sample size of 48, which reads as a measurement and is not one.
        """
        signs = [(1 if b > a else -1 if b < a else 0) for a, b in pairwise(self.prices)]
        return sum(1 for s in signs if s != 0)

    def two_sided_frac(self) -> float:
        if len(self.prices) < 3:
            return 0.0
        signs = [(1 if b > a else -1 if b < a else 0) for a, b in pairwise(self.prices)]
        moves = [s for s in signs if s != 0]
        if len(moves) < 2:
            return 0.0
        flips = sum(1 for a, b in pairwise(moves) if a != b)
        return flips / (len(moves) - 1)

    def zigzag_at(self, threshold: float) -> tuple[int, float]:
        if not math.isfinite(threshold) or threshold <= 0 or len(self.prices) < 3:
            return 0, 0.0
        return zigzag([math.log(p) for p in self.prices], threshold)

    def features(self, *, friction: Friction, obs: MintObservation, clip_lamports: int) -> dict[str, float]:
        """The wiggle block, ready to be merged into the policy's feature vector.

        Every value is derived from observations the desk already made and stored, so this
        adds no vendor traffic and no second view of the market.
        """
        take_bps = friction.take_bps_for(obs.pool_label)
        cost = friction.round_trip(clip_lamports, obs.vsol_lamports, take_bps=take_bps)
        threshold = math.log1p(cost) if math.isfinite(cost) and cost > 0 else float("inf")
        swings, amplitude = self.zigzag_at(threshold)
        return {
            "wiggle_observations": float(self.observations),
            "wiggle_obs_per_min": self.observations_per_minute(),
            "wiggle_two_sided_frac": self.two_sided_frac(),
            "wiggle_n": float(swings),
            "wiggle_amp": amplitude,
            "wiggle_net": amplitude - swings * threshold if swings else 0.0,
            "round_trip_cost": cost if math.isfinite(cost) else 1.0,
            "own_exit_impact": ghost_town_impact(clip_lamports, obs.vsol_lamports),
        }

    def observations_per_minute(self) -> float:
        """How often the desk actually SEES this coin. An entry condition, not a diagnostic.

        Measured on a live probe before this existed: a stop armed at -16.5% filled at
        **-64.7%**, because the next observation of that coin arrived 43 seconds later and
        it had gapped straight through. The desk cannot trade the tick that told it to
        trade, so the only lever on that loss is how soon the NEXT tick arrives -- and a
        coin the desk sees twice in fifteen minutes cannot be scalped on a five-minute
        clock by anybody, whatever its drawdown and depth say.

        Returns 0.0 with fewer than two observations: unmeasured, and the rule must not
        read an unmeasured cadence as a fast one.
        """
        if len(self.times) < 2:
            return 0.0
        span = self.times[-1] - self.times[0]
        if span <= 0:
            return 0.0
        return (len(self.times) - 1) * 60.0 / span


class WiggleBook(MintBook):
    """A :class:`~shitcoims_paperdesk.books.MintBook` that cannot become a hold.

    Everything about filling, marking, censoring and the close row is inherited unchanged,
    because those rules were paid for once and must not be re-derived per book -- the
    ``+21.77% -> -12.24%`` censoring correction and the ``-151%`` partial-row incident are
    both in the base class and both stay there.

    What this subclass adds is the discipline:

    * a departure timeout scaled to a five-minute horizon rather than a ten-minute one,
    * a per-mint :class:`WiggleWatch` whose features enter the LOGGED decision, so the
      oscillation evidence is part of the policy the propensity describes rather than a
      filter sitting invisibly upstream of it,
    * an assertion, at decision time, that the drawn holding horizon really is a clock:
      a wiggle decision whose deadline is further out than :data:`MAX_HOLD_S` is a defect
      row rather than a position, because the one failure this book exists to prevent is
      precisely a scalp quietly turning into a hold.
    """

    #: The hard ceiling on this book's horizon. The policy's jitter box sits well inside
    #: it; this is the tripwire that fires if anybody ever widens the box, which is exactly
    #: how discipline drift would enter the code rather than the trading.
    MAX_HOLD_S: Final[float] = 900.0

    def __init__(self, *args: Any, clip_lamports: int = 100_000_000, **kwargs: Any) -> None:
        kwargs.setdefault("departure_timeout_s", WIGGLE_DEPARTURE_TIMEOUT_S)
        super().__init__(*args, **kwargs)
        self.clip_lamports = clip_lamports
        self.watch: dict[str, WiggleWatch] = {}
        self.counters.setdefault("refused_horizon", 0)

    def observe(self, obs: MintObservation, *, source_stale: bool) -> None:
        watch = self.watch.get(obs.mint)
        if watch is None:
            watch = self.watch[obs.mint] = WiggleWatch()
        watch.observe(obs.price, obs.t_ingest_unix, basis=obs.pool_label)
        if len(self.watch) > WATCH_CAPACITY:
            # Bounded: the boards feed carries 15,300 distinct mints over a day and a desk
            # that remembered all of them would be remembering a market, not a book.
            # Insertion order is oldest-first, so the head is the right thing to evict --
            # but never a mint the book is actually in or about to be in, or the position
            # would lose the oscillation evidence its own exit bracket was sized against.
            live = {p.mint for p in self.positions.values()} | set(self.pending)
            for mint in list(self.watch)[: WATCH_CAPACITY // 4]:
                if mint not in live:
                    self.watch.pop(mint, None)
        super().observe(obs, source_stale=source_stale)

    def consider(
        self, obs: MintObservation, *, extra_features: dict[str, float] | None = None
    ) -> None:
        watch = self.watch.get(obs.mint) or WiggleWatch()
        features = watch.features(
            friction=self.friction, obs=obs, clip_lamports=self.clip_lamports
        )
        if extra_features:
            features.update(extra_features)
        super().consider(obs, extra_features=features)

    def _size_for(self, obs: MintObservation) -> int:
        """The operator's own clip, capped by the pool and by what is left of the bankroll.

        NOT ``B* = sqrt(priority * Y)``. The mint books size for impact-optimality, which at
        these depths lands around 0.03-0.06 SOL; this book is a paper reconstruction of
        trades the operator actually made at ~0.1 SOL, and sizing it differently would make
        the comparison against their own measured 7/13 a comparison of two different
        strategies. The impact cap still binds -- ``rho_max_bps`` is the shared friction
        model's, not this book's -- so a thin pool shrinks the clip rather than being handed
        one it cannot absorb, and the GHOST_TOWN guard refuses it outright before that.
        """
        cap = min(self.free_lamports, self.bankroll_lamports)
        rho_cap = obs.vsol_lamports * self.friction.rho_max_bps // 10_000
        return max(0, min(self.clip_lamports, rho_cap, cap))

    def _pending_entry(self, obs: MintObservation, decision: Any) -> dict[str, Any] | None:
        entry = super()._pending_entry(obs, decision)
        if entry is None:
            return None
        horizon = float(entry["deadline_unix"]) - obs.t_ingest_unix
        if horizon > self.MAX_HOLD_S:
            self.counters["refused_horizon"] += 1
            self.ledger.emit(
                "defect",
                str(self.book),
                t_ingest_unix=obs.t_ingest_unix,
                t_event_unix=obs.t_event_unix,
                t_event_source=obs.t_event_source,
                key=obs.mint,
                decision_id=decision.decision_id,
                detail="wiggle_horizon_exceeds_hard_clock",
                horizon_s=horizon,
                max_hold_s=self.MAX_HOLD_S,
            )
            return None
        return entry

    def state(self) -> dict[str, Any]:
        return {**super().state(), "clip_lamports": self.clip_lamports}

    def restore(self, state: dict[str, Any]) -> None:
        super().restore(state)
        self.clip_lamports = int(state.get("clip_lamports") or self.clip_lamports)


def _book_is_wiggle(book: Book) -> bool:  # pragma: no cover - readability helper
    return book is Book.WIGGLE
