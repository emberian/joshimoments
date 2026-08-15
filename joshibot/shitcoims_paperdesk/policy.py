"""Four policies, one design: jittered thresholds, an epsilon flip, a logged propensity.

WHY THE DESK RANDOMISES ITSELF ON PURPOSE
-----------------------------------------
``studies/RESULT_bandit_search.md`` had to fall back on a simulator, not because the board
tape was small -- it was 77,623 rows -- but because it was OBSERVATIONAL. Nothing had ever
recorded the probability with which an action was taken, so no counterfactual could be
identified and every "what if the threshold were looser" question had to be answered by a
model of the market instead of by the market. The paper desk fixes that at the source: it
generates its own propensities.

Two layers, both logged at decision time, exactly as ``shitcoims_scalper.policy`` does:

1. **Threshold jitter.** Every cutoff is drawn per decision from a range. A deterministic
   filter cannot answer "what if it were looser"; a jittered one makes every nearby filter
   a counterfactual policy that ``shitcoims_replay.ope`` can score off this ledger.
2. **The epsilon flip.** With probability ``explore_eps`` the desk acts AGAINST its own
   verdict. Every candidate then has nonzero propensity for both actions, which is the
   overlap condition OPE needs.

The epsilon flip matters most on the TOLL book, and it is worth being explicit about why.
Every measured churn number in this cluster is below 1 (``eta`` 0.055-0.235 on the SOL
pools, 0.59-1.08 on the live DLMM), and ``VR`` at the holding horizon is near 1, so the
``eta * D > VR`` gate refuses essentially everything. A desk that only ever acted on its
gate would therefore accumulate zero evidence about whether the gate is right. The
exploration arm is the only reason the toll book can ever be *falsified* rather than
merely obeyed.

THESE PARAMETERS ARE PRIORS, NOT CONCLUSIONS
--------------------------------------------
The short book's bracket is centred on the operator's own trade, +12%/-30%, which is the
best-behaved arm of the 18-rule exit grid at **+0.156% per round** -- and ``t = 0.24``,
which is no evidence of anything. Its breakeven haircut is 0.4%: one to two percent of
adverse fill consumes the entire advantage. The jitter range spans +30%/-30% (+0.504%,
t = 0.56) so the desk can compare them on its own fills rather than on a study's.

The grid's headline cell (+100%/-50% behind a dd<0.30 filter) is deliberately NOT the
default: it scored +18.30 pp paired against baseline, and its permutation floor put
**p = 0.455**. It is inside the jitter range's reach and nowhere near its centre.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final, Mapping

from shitcoims_paperdesk import Book
from shitcoims_tape.schema import PropensityRecord

__all__ = [
    "DeskDecision",
    "DeskPolicy",
    "MediumPolicy",
    "OperatorPolicy",
    "ShortPolicy",
    "TollPolicy",
    "WigglePolicy",
    "policy_for",
]

#: Every book explores at the same rate, because the books must be comparable and an arm
#: that explores more collects more information about its own tails.
DEFAULT_EPS: Final[float] = 0.05


@dataclass(frozen=True, slots=True)
class DeskDecision:
    """One decision, counterfactual-ready, over one candidate.

    ``propensity`` is the probability of the action ACTUALLY TAKEN under this policy given
    the drawn thresholds. It is computed here and never reconstructed later, because it is
    not reconstructible later.
    """

    decision_id: str
    decided_at: str
    policy_id: str
    book: str
    key: str
    action: str
    verdict_pass: bool
    explored: bool
    propensity: float
    thresholds: dict[str, float]
    features: dict[str, float]
    features_sha256: str
    size_lamports: int
    deadline_unix: float
    #: Per-leg entry-gate verdicts, when the policy computed them. Empty for the four books
    #: whose gates ARE the verdict -- there the pass/fail is already in ``verdict_pass`` and
    #: naming the legs again would be two records of one fact. It is populated only by the
    #: OPERATOR book, where the gates are computed and deliberately do not gate, so which
    #: leg disagreed with the operator is the entire measurement.
    gates: dict[str, bool] = field(default_factory=dict)

    @property
    def acted(self) -> bool:
        return self.action == "enter"

    def record(self) -> PropensityRecord:
        """Construct the REAL tape contract type. The anti-mirror gate.

        ``mint`` is validated by base58 DECODE, not by a character-class regex, so a
        lowercased or otherwise corrupted key raises here instead of reaching the ledger.
        """
        return PropensityRecord(
            decision_id=self.decision_id,
            decided_at=self.decided_at,
            policy_id=self.policy_id,
            action=self.action,
            propensity=self.propensity,
            features_sha256=self.features_sha256,
            envelope_verdict="paper",
            mint=self.key,
        )

    def ledger_fields(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "verdict_pass": self.verdict_pass,
            "explored": self.explored,
            "thresholds": self.thresholds,
            "features": self.features,
            "size_lamports": self.size_lamports,
            "deadline_unix": self.deadline_unix,
        }
        if self.gates:
            out["gates"] = self.gates
            # Named separately from the map so the report can count vetoes without
            # re-deriving which polarity means "would have refused".
            out["gates_would_veto"] = sorted(k for k, ok in self.gates.items() if not ok)
        return out


class DeskPolicy:
    """Draw thresholds, apply the rule, flip with epsilon, log the propensity.

    Subclasses supply ``ranges`` (the jitter box) and ``rule`` (the verdict). Everything
    that makes the record scoreable -- the flip, the propensity arithmetic, the feature
    hash -- lives here once, so no book can accidentally log a propensity of a different
    thing from the action it took.
    """

    book: Book = Book.SHORT
    policy_id: str = "paperdesk-v1"
    #: The jitter box. A ClassVar because it is the POLICY's definition, shared by every
    #: decision the policy makes -- per-instance mutation would silently fork the logged
    #: policy from the one that ran.
    ranges: ClassVar[dict[str, tuple[float, float]]] = {}

    def __init__(self, *, explore_eps: float = DEFAULT_EPS, seed: int | None = None) -> None:
        if not 0.0 < explore_eps < 0.5:
            raise ValueError("explore_eps must be in (0, 0.5)")
        self.explore_eps = explore_eps
        self.rng = random.Random(seed)

    def draw(self) -> dict[str, float]:
        return {name: self.rng.uniform(lo, hi) for name, (lo, hi) in self.ranges.items()}

    def rule(self, features: Mapping[str, float], t: Mapping[str, float]) -> bool:
        raise NotImplementedError

    def decide(
        self,
        *,
        key: str,
        features: Mapping[str, float],
        now_unix: float,
        decided_at: str,
        size_lamports: int,
        actionable: bool = True,
        thresholds: Mapping[str, float] | None = None,
    ) -> DeskDecision:
        """``actionable`` folds the friction check INTO the logged verdict.

        A candidate whose optimal size cannot beat the round-trip cost is not tradeable at
        any threshold. Folding that in here rather than filtering it out upstream keeps
        the filter inside the policy the propensity describes -- an invisible upstream
        filter would make every downstream estimate about a policy nobody logged.

        ``thresholds`` may be supplied by a caller that had to draw them EARLIER than the
        decision -- the toll book must know the range width before it can compute the
        capacitance that the gate features depend on. Passing them back in is what keeps
        the logged propensity a description of the policy that actually ran; re-drawing
        here would log one policy and act on another.
        """
        thresholds = dict(thresholds) if thresholds is not None else self.draw()
        verdict = bool(self.rule(features, thresholds)) and actionable

        flip = self.rng.random() < self.explore_eps
        enter = verdict != flip  # XOR: act against the verdict on an epsilon flip
        p_enter = (1.0 - self.explore_eps) if verdict else self.explore_eps
        propensity = p_enter if enter else 1.0 - p_enter

        feat = {k: float(v) for k, v in sorted(features.items())}
        digest = hashlib.sha256(
            json.dumps(feat, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        horizon = thresholds.get("hold_seconds", 3600.0)

        return DeskDecision(
            decision_id=f"{self.book}-{key[:10]}-{int(now_unix * 1000)}",
            decided_at=decided_at,
            policy_id=self.policy_id,
            book=str(self.book),
            key=key,
            action="enter" if enter else "skip",
            verdict_pass=verdict,
            explored=flip,
            propensity=propensity,
            thresholds=thresholds,
            features=feat,
            features_sha256=digest,
            size_lamports=size_lamports if enter else 0,
            deadline_unix=now_unix + horizon,
        )


class ShortPolicy(DeskPolicy):
    """Minutes-to-hours. The 108-cell entry grid, jittered instead of chosen.

    Entry is ``studies/bandit_search.py``'s ``EnterRule`` with its cutoffs drawn per
    decision rather than fixed: drawdown below a threshold in [0.30, 0.70], SOL in curve
    above [10, 30], market cap above [$10k, $100k]. Two additions the grid did not have,
    both of which the live setting forces:

    * ``drawdown_known`` -- the vendor serves ``-1.0`` for "no ATH", and ``-1.0`` passes
      every ``drawdown < x`` test. The grid's cohort builder dropped those rows up front;
      a live desk sees them arrive and must refuse them explicitly.
    * ``trade_recency_s`` -- a coin nobody has traded in an hour is not a minutes-horizon
      candidate, whatever its drawdown.

    TWO REGIMES, ONE POLICY. A mint thirty seconds old has no all-time high, so its
    drawdown is not merely unmeasured, it does not exist -- and the firehose delivers 18-28
    of those a minute. Rejecting them all would leave the short book unable to act on its
    fastest feed except by exploration. So the rule branches on whether a drawdown exists:
    with one, the 108-cell board grid applies; without one, the scalper's liveness band
    (old enough not to be a snipe, young enough to still be moving, recently traded, deep
    enough to size into) applies instead. Both branches draw from the same jitter box and
    both are logged, so the branch is part of the policy the propensity describes rather
    than a fork hidden upstream of it.
    """

    book = Book.SHORT
    policy_id = "paperdesk-short-v1"
    ranges: ClassVar[dict[str, tuple[float, float]]] = {
        "dd_max": (0.30, 0.70),
        "sol_min": (10.0, 30.0),
        "mcap_min": (1.0e4, 1.0e5),
        "max_trade_recency_s": (60.0, 600.0),
        # The no-drawdown branch: the liveness band from shitcoims_scalper.policy.
        "min_age_s": (20.0, 90.0),
        "max_age_s": (900.0, 3600.0),
        "hold_seconds": (1800.0, 14400.0),
        # Centred on the operator's own +12%/-30%; the range reaches +30%/-30%, the arm
        # that scored better (+0.504%/round, t = 0.56) on the same 18-rule grid.
        "take_profit": (0.10, 0.35),
        "stop_loss": (0.20, 0.40),
    }

    def rule(self, f: Mapping[str, float], t: Mapping[str, float]) -> bool:
        common = (
            f["sol_in_curve"] >= t["sol_min"]
            and f["trade_recency_s"] <= t["max_trade_recency_s"]
        )
        if not common:
            return False
        if f.get("drawdown_known", 0.0) > 0.5:
            return (
                f["drawdown_from_ath"] < t["dd_max"]
                and f["usd_market_cap"] >= t["mcap_min"]
            )
        return t["min_age_s"] <= f["age_s"] <= t["max_age_s"]


class MediumPolicy(DeskPolicy):
    """Hours-to-days. Survivorship in, deterioration out, wide tolerance throughout.

    The entry condition is deliberately almost nothing: a candidate qualifies by having
    been CONTINUOUSLY OBSERVED for hours, which is the medium horizon's only real claim --
    that a mint still alive after four hours is a different animal from one four minutes
    old. Drawdown tolerance is wide (up to 0.90) because the medium book is not trying to
    catch a bounce; it is trying to hold something.

    Exit is where the medium book earns its keep, and it uses only the two signals that
    survived ``studies/RESULT_deterioration.md``: ``drawdown`` (Spearman **+0.105**
    [+0.040, +0.170] at 24h -- further below peak predicts WORSE forward, i.e. momentum,
    not reversion) and ``active_frac`` (**-0.078** [-0.140, -0.010] -- continuously traded
    coins do worse forward). Both are weak. The study's headline ``divergence`` signal was
    REFUTED -- sign flipped across consecutive windows, CIs spanning zero -- and is
    deliberately absent from this policy.
    """

    book = Book.MEDIUM
    policy_id = "paperdesk-medium-v1"
    ranges: ClassVar[dict[str, tuple[float, float]]] = {
        "min_observed_s": (7200.0, 21600.0),
        "min_observations": (8.0, 40.0),
        "dd_max": (0.50, 0.90),
        "sol_min": (5.0, 20.0),
        "hold_seconds": (43200.0, 259200.0),
        "take_profit": (0.75, 2.00),
        "stop_loss": (0.40, 0.60),
        # Deterioration exit: fire when the position is this far below its own peak AND
        # the trade-activity fraction is above this. Both drawn, both weak priors.
        "deterioration_drawdown": (0.25, 0.45),
        "deterioration_active_frac": (0.55, 0.85),
    }

    def rule(self, f: Mapping[str, float], t: Mapping[str, float]) -> bool:
        return (
            f.get("observed_seconds", 0.0) >= t["min_observed_s"]
            and f.get("observations", 0.0) >= t["min_observations"]
            and f.get("drawdown_known", 0.0) > 0.5
            and f["drawdown_from_ath"] < t["dd_max"]
            and f["sol_in_curve"] >= t["sol_min"]
        )


class TollPolicy(DeskPolicy):
    """The LP book. ``eta * D > VR``, with every term measured rather than assumed.

    ``eta = 2 f N / (C * RV)`` is the churn number: fee income in units of loss-versus-
    rebalancing. ``VR`` is the Lo-MacKinlay variance ratio at the holding horizon. ``D`` is
    the realised duty cycle. The gate is exact, from ``studies/RESULT_circuit_theory.md``
    §4.2 and ``RESULT_lp_strategy.md`` §2, and it is worth restating the part that keeps
    getting hoped away:

        **Concentration is SIGN-PRESERVING.** A DLMM position has ``C = T/W``, and BOTH
        terms of the ledger scale with ``C``. Narrowing the range multiplies the answer by
        ``4/W`` and cannot change its sign. It levers the loss exactly as hard as the gain.

    So the width parameter here is not a rescue mechanism, and the jitter range sits where
    ``RESULT_lp_strategy.md`` §5 recommends -- WIDE, ``h >= 0.5`` -- because harvest falls
    only as ``h^-0.2`` while duty cycle collapses fast when the range is narrow.

    ``gate_margin`` jitters the strictness of the inequality itself, which turns the gate
    from a rule the desk obeys into a rule the desk can measure.
    """

    book = Book.TOLL
    policy_id = "paperdesk-toll-v1"
    ranges: ClassVar[dict[str, tuple[float, float]]] = {
        "gate_margin": (0.90, 1.30),
        # Half-width of the paper range in log price. "Run wide" per RESULT_lp_strategy §5.
        "half_width": (0.30, 0.70),
        # Rebalance trigger: log distance BEYOND the range edge before a one-sided
        # redeploy. RESULT_lp_strategy §4 item 3: d = 0 to 0.15, targeting D > 95%.
        "rebalance_trigger": (0.0, 0.15),
        "hold_seconds": (86400.0, 345600.0),
        # Duty cycle the gate is evaluated AT on entry. The realised D is measured after.
        "assumed_duty": (0.90, 0.99),
    }

    def rule(self, f: Mapping[str, float], t: Mapping[str, float]) -> bool:
        eta = f.get("eta", 0.0)
        vr = f.get("variance_ratio", 1.0)
        if eta <= 0.0 or vr <= 0.0:
            return False
        return eta * t["assumed_duty"] > vr * t["gate_margin"]


class WigglePolicy(DeskPolicy):
    """Minutes, and only minutes. Post-collapse bottom scalps behind a ghost-town guard.

    THE EXIT IS THE POLICY. ``hold_seconds`` is drawn in **[240, 420] s**, a jitter box
    centred on the five minutes that splits the operator's own reconstructed trades into a
    winning book and a losing one (7/13 and +$3.09 under five minutes; 1/20 and -$61 in
    every bucket beyond it). Its upper bound is inside
    ``shitcoims_paperdesk.wiggle.WiggleBook.MAX_HOLD_S``, which refuses anything longer as
    a defect rather than trading it -- the failure this book exists to prevent is a scalp
    becoming a hold, and that failure would enter the CODE as a widened jitter box.

    ``take_profit`` is drawn in [0.03, 0.09]. The floor is not a preference: round-trip
    friction at the operator's 0.1 SOL clip is ~2.4% (``friction.round_trip``, corrected to
    full three-leg taker costs), so a bracket below ~3% is a bracket that books a loss on a
    win. ``stop_loss`` [0.10, 0.25] is wide *because* the clock is the real exit -- a tight
    stop on a coin oscillating at 5% amplitude just pays friction to be shaken out.

    THE ENTRY RULE, term by term, each with the measurement behind it:

    * ``drawdown_from_ath >= dd_min`` in [0.60, 0.85], with ``drawdown_known``. The
      operator's pattern is a *bottom* scalp; a coin still near its high is a momentum
      trade and belongs to the short book. The vendor serves ``-1.0`` for "no ATH" and
      ``-1.0 >= 0.70`` is false, so the unknown case fails closed here -- but
      ``drawdown_known`` is asserted anyway, because failing closed by arithmetic accident
      is not the same as refusing on purpose.
    * ``sol_in_curve >= ghost_min_pool_sol`` in [5, 25] SOL. The GHOST_TOWN guard, derived
      in :mod:`shitcoims_paperdesk.wiggle` from clip-against-depth: at 0.1 SOL, 5 SOL of
      depth is a 2.00% one-way impact (PROGRAM.md §1.4's ceiling) and 25 SOL is 0.40%.
      ``RESULT_crime_signatures.md`` §7.1: a fossil quote is a price nobody has tested, and
      the rug is just the first real seller finding that ``C -> 0``. We must not be that
      seller. Note where it binds: a bonding curve's VIRTUAL reserve floors at 30 SOL, so
      this leg is slack pre-graduation and does its work on migrated pools, whose vault can
      actually be drained. That is by design; see the module docstring.
    * ``trade_recency_s <= max_trade_recency_s`` in [30, 180] s. The second half of
      GHOST_TOWN -- thin AND stale. A coin nobody has traded in three minutes has no
      wiggle to harvest whatever its depth says.
    * ``wiggle_obs_per_min >= min_obs_per_min`` in [0.5, 2.0] per minute. Not a data-quality
      filter -- an ENTRY condition, and the one this book learned the hard way. On a live
      probe a stop armed at -16.5% filled at **-64.7%**, because the next observation of
      that coin came 43 s later and it had gapped through. A position cannot be exited on a
      five-minute clock if the desk sees the coin twice in fifteen minutes, whatever its
      drawdown and depth say, so an unmarkable coin is refused rather than entered and
      hoped over. (The complementary fix is on the other side: the desk refreshes wiggle
      holdings as PRIORITY, at a shorter interval than the mint books' -- see
      ``MintRefreshSource.refresh``.)
    * ``wiggle_two_sided_frac >= min_two_sided`` in [0.25, 0.60], **once the desk has seen
      the coin at least three times**. Direction flips in the observed price path are the
      only two-sidedness a board snapshot can support: it carries a price and a last-trade
      stamp, never a side. Below three observations the term is unmeasured and the rule
      does not pretend otherwise -- it falls back to depth and recency alone and the
      propensity log records which branch ran.
    * ``own_exit_impact <= take_profit / impact_margin`` with ``impact_margin`` in [3, 8].
      The guard restated as the thing it protects: our own exit must not move the price by
      a meaningful fraction of the bracket we are trying to earn. Depth alone cannot say
      that, because it does not know the bracket.

    CALLOUT ACTIVITY enters through ``wiggle.CALLOUT_ARM``, which carries the verdict of
    ``studies/RESULT_callout_volatility.md`` as one constant. Under ``"preferred"`` a
    callout in the last hour RELAXES the two-sidedness bar rather than gating on it, which
    is the honest encoding of a signal that survived its nulls but did not survive having
    contemporaneous on-chain flow controlled: it is evidence, not a licence.
    """

    book = Book.WIGGLE
    policy_id = "paperdesk-wiggle-v1"
    ranges: ClassVar[dict[str, tuple[float, float]]] = {
        # THE CLOCK. Centred on the operator's measured five-minute edge window.
        "hold_seconds": (240.0, 420.0),
        # Must clear ~2.4% round-trip friction at a 0.1 SOL clip, with room to spare.
        "take_profit": (0.03, 0.09),
        "stop_loss": (0.10, 0.25),
        # Collapse conditioning: this is a bottom book.
        "dd_min": (0.60, 0.85),
        # GHOST_TOWN: depth, staleness, and our own exit against the bracket.
        "ghost_min_pool_sol": (5.0, 25.0),
        "max_trade_recency_s": (30.0, 180.0),
        "impact_margin": (3.0, 8.0),
        # Two-sidedness, measured on the desk's own observation path.
        "min_two_sided": (0.25, 0.60),
        # Marking cadence: can this position be EXITED on a five-minute clock at all?
        "min_obs_per_min": (0.5, 2.0),
        # How much a live callout stream relaxes the two-sidedness bar under CALLOUT_ARM
        # == "preferred". Jittered so the ledger can price the relaxation itself.
        "callout_relief": (0.05, 0.30),
    }

    def legs(self, f: Mapping[str, float], t: Mapping[str, float]) -> dict[str, bool]:
        """Each entry condition, evaluated SEPARATELY and named. ``rule`` is their AND.

        Split out of :meth:`rule` because the OPERATOR book needs the per-leg verdicts as
        DATA -- it enters on the operator's gesture whatever the gates say, and logs which
        gates would have vetoed, so "which of our rules disagrees with their taste, and is
        it right to?" becomes a question the ledger can settle. A second copy of these legs
        written for that purpose would answer a question about the copy; this is the same
        object both books read.

        A leg that is UNMEASURED is ABSENT from the mapping rather than ``True``. The
        two-sidedness and cadence legs are only defined once the desk has seen the coin
        three times, and recording an unevaluated condition as a pass would put a guess in
        the same dict as a measurement -- the same refusal ``drawdown_known`` exists for.
        """
        from shitcoims_paperdesk.wiggle import CALLOUT_ARM

        out: dict[str, bool] = {
            "drawdown_known": f.get("drawdown_known", 0.0) > 0.5,
            "collapsed": f.get("drawdown_from_ath", -1.0) >= t["dd_min"],
            "depth": f.get("sol_in_curve", 0.0) >= t["ghost_min_pool_sol"],
            "recently_traded": f.get("trade_recency_s", 1e9) <= t["max_trade_recency_s"],
            "own_exit_impact": (
                f.get("own_exit_impact", 1.0) <= t["take_profit"] / t["impact_margin"]
            ),
        }
        callouts = f.get("callout_n_60m", 0.0)
        if CALLOUT_ARM == "required":
            out["callout"] = callouts >= 1.0
        bar = t["min_two_sided"]
        if CALLOUT_ARM == "preferred" and callouts >= 1.0:
            bar = max(0.0, bar - t["callout_relief"])
        if f.get("wiggle_observations", 0.0) >= 3.0:
            out["markable_cadence"] = f.get("wiggle_obs_per_min", 0.0) >= t["min_obs_per_min"]
            out["two_sided"] = f.get("wiggle_two_sided_frac", 0.0) >= bar
        # Fewer than three observations: two-sidedness is UNMEASURED, not zero. Depth and
        # recency stand on their own, the candidate is admitted, and the ledger records the
        # branch through ``wiggle_observations`` in the hashed feature vector.
        return out

    def rule(self, f: Mapping[str, float], t: Mapping[str, float]) -> bool:
        return all(self.legs(f, t).values())


class OperatorPolicy(WigglePolicy):
    """The operator's gesture, logged as the policy it is: exogenous, and always ``enter``.

    THE JITTER BOX IS INHERITED, NOT RESTATED. Every threshold this policy draws is
    :class:`WigglePolicy`'s -- the same clock in [240, 420] s, the same bracket, the same
    ghost-town cutoffs. Two consequences, both deliberate:

    * the EXIT the operator's pick gets is drawn from the same distribution the rule-chosen
      pick gets, which is what makes the two books' returns differ by selection alone;
    * the GATES are evaluated against the same drawn thresholds the wiggle book would have
      used on that candidate, so "this hunch would have been vetoed" is a statement about
      the actual rule and not about a nearby one.

    WHY THE PROPENSITY IS 1.0 AND THERE IS NO EPSILON ARM. The other four policies randomise
    themselves so that off-policy evaluation can ask what a nearby threshold would have
    earned. There is no nearby threshold here: the logging policy is a person, it is not
    parameterised by anything the desk holds, and flipping one in twenty of their calls
    would corrupt the measurement rather than enrich it -- the whole point is to observe
    THEIR selection, undisturbed. So the action is ``enter`` with probability 1, which is
    exactly what the propensity field then says. Note what that costs, plainly: this book's
    own rows carry no overlap and are therefore NOT reweightable to a counterfactual entry
    policy. They are a treatment arm, compared against the wiggle book's arm under identical
    execution, and that comparison is the design -- not an OPE estimate.
    """

    book = Book.OPERATOR
    policy_id = "paperdesk-operator-v1"

    def __init__(self, *, explore_eps: float = DEFAULT_EPS, seed: int | None = None) -> None:
        # Accepted and ignored: ``policy_for`` hands every book the same eps, and refusing
        # the argument here would make the OPERATOR book the one that cannot be built the
        # same way as the others. Recorded as 0.0 because that is the truth of it.
        super().__init__(explore_eps=explore_eps, seed=seed)
        self.explore_eps = 0.0

    def decide(
        self,
        *,
        key: str,
        features: Mapping[str, float],
        now_unix: float,
        decided_at: str,
        size_lamports: int,
        actionable: bool = True,
        thresholds: Mapping[str, float] | None = None,
    ) -> DeskDecision:
        """Always ``enter``, at propensity 1.0, with the gate verdict carried alongside.

        ``actionable`` -- the friction check that folds into every other book's verdict --
        is computed and reported through :meth:`legs` like any other gate, and does not
        stop the entry. The operator outranks the gate; the gate still gets to speak, and
        an unaffordable round trip is one of the things this book exists to find out about.
        """
        drawn = dict(thresholds) if thresholds is not None else self.draw()
        gates = self.legs(features, drawn)
        gates["affordable"] = bool(actionable)
        feat = {k: float(v) for k, v in sorted(features.items())}
        digest = hashlib.sha256(
            json.dumps(feat, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return DeskDecision(
            decision_id=f"{self.book}-{key[:10]}-{int(now_unix * 1000)}",
            decided_at=decided_at,
            policy_id=self.policy_id,
            book=str(self.book),
            key=key,
            action="enter",
            verdict_pass=all(gates.values()),
            explored=False,
            propensity=1.0,
            thresholds=drawn,
            features=feat,
            features_sha256=digest,
            size_lamports=size_lamports,
            deadline_unix=now_unix + drawn.get("hold_seconds", 300.0),
            gates=gates,
        )


_POLICIES: Final[dict[Book, type[DeskPolicy]]] = {
    Book.SHORT: ShortPolicy,
    Book.MEDIUM: MediumPolicy,
    Book.TOLL: TollPolicy,
    Book.WIGGLE: WigglePolicy,
    Book.OPERATOR: OperatorPolicy,
}


def policy_for(book: Book, *, explore_eps: float = DEFAULT_EPS, seed: int | None = None) -> DeskPolicy:
    return _POLICIES[book](explore_eps=explore_eps, seed=seed)
