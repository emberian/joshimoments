"""Signal #1 -- coordinated-cluster detection by Statistically Validated Networks.

Question (pre-registered, PROGRAM.md §4 item 1 and §4.1): over a set of wallets and a set of
tokens, which wallet PAIRS co-occur in the same trading state on more tokens than an explicit
null model can produce, and do the validated links assemble into communities?

Method: Tumminello, Lillo, Piilo & Mantegna 2012 (New J. Phys. 14:013041 / arXiv:1107.3942),
implemented against §4.1's four corrections to our own first reading of it. Everything here is
deterministic given ``--seed`` and touches no network at run time.

Seven decisions are load-bearing. Each one is a documented error -- ours, or the literature's.

**Nine typed tests per pair, not one.** A wallet's state on a token is a 3-valued variable
(buy-only / sell-only / round-trip), crossed with itself. §4.1: "It is nine typed tests per
pair, not one -- which is exactly where Bonferroni's x9 comes from." Collapsing to a single
"did they both trade it" test understates the correction by 9x AND throws away the direction
information that separates an accumulation ring from two strangers on the same hot token.

**T is pair-specific.** The index size for the pair (i, j) is the number of tokens that existed
inside the INTERSECTION of the two wallets' activity periods, and each wallet's marginal is
recounted inside that same window. A global T for a wallet that lived four hours inflates its
significance without bound, and short-lived wallets are the entire population here.

**Two null models, compared at matched link DENSITY.** Cimini et al. 2022 (Comms Phys 5:76):
validated-link density varies by an ORDER OF MAGNITUDE across nulls at the same p-value
threshold, so a p-matched comparison compares nothing. The second null is a degree-preserving
randomisation (curveball on the wallet x token incidence, then a within-wallet relabel of the
states), which is also the direct answer to §4.1's blocking risk: the hypergeometric assumes
roughly uniform marginals across the index, and memecoin token popularity is heavy-tailed, so
under it "everybody bought the hot token" reads as coordination. §7 of the RESULT measures
exactly how large that artefact is.

**The degree-preserving null cannot be thresholded on p, and that is a finding, not a nuisance.**
Its p-value floor is ``1/(B+1)`` for B randomisations; the Bonferroni threshold at any realistic
wallet count is 1e-9 or smaller. No feasible B closes that gap. Matched density is therefore not
merely Cimini's preference, it is the only comparison that exists.

**Union-find is reported as the documented FAILURE mode, never as the answer.** §4.1: connected
components put 99.6% of the FDR network and 81% of the Bonferroni network in one blob. The
clustering is weighted map-equation optimisation (Infomap's two-level core), weights = number of
validated same-action test types (1-3). ``giant_component_share`` is printed next to it so the
pathology stays visible rather than becoming folklore.

**Opposite-action links are kept, separately.** The paper removes them before clustering. For us
a validated (buy, sell) co-occurrence is the likeliest wash-trading signature there is, so
adopting the recipe verbatim would discard the thing we most want to see. They are excluded from
the clustering weight and reported as their own network.

**The feasibility gate is checkable before a credit is spent.** With ``n`` wallets, ``T`` tokens
and ``N`` tokens per wallet, the smallest p a pair can attain is ``1 / C(T, N)``; Bonferroni over
nine tests per pair demands ``C(T, N) >= 9 n(n-1) / (2 alpha)``. §4.1 shows our own original power
claim failed this by ~2,700x. It is computed here first and printed whether or not it passes.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from typing import Any

from solders.pubkey import Pubkey

from shitcoims_tape.backfill import load_intelligence_wallet_transactions
from shitcoims_tape.schema import EntityLink

# ---------------------------------------------------------------------------------------------
# Study parameters. Declared up front so the hypothesis family is countable rather than guessed.
# ---------------------------------------------------------------------------------------------

#: Familywise level for the Bonferroni threshold. Tumminello uses 0.01; kept.
ALPHA: float = 0.01

#: BH-FDR level, reported ALONGSIDE Bonferroni rather than instead of it: Bonferroni buys
#: specificity (which is what an entity-resolution output needs, since a false merge lets one
#: actor straddle a train/test split) and BH buys coverage.
FDR_Q: float = 0.05

#: Randomisations for the degree-preserving null. Its p-floor is 1/(B+1), which is why this
#: null is compared at matched density and never thresholded at the Bonferroni level.
RANDOMISATIONS: int = 200

#: Below this the "network" has no community structure to find. This is NOT a power threshold --
#: a 2-wallet panel passes the Bonferroni feasibility gate easily and still cannot support the
#: claim, because with one pair there is nothing to cluster and no multiplicity to correct.
MIN_WALLETS: int = 20

VERDICT_NULL = "NULL"
VERDICT_UNRESOLVABLE = "UNRESOLVABLE-AT-THIS-N"
VERDICT_SUGGESTIVE = "SUGGESTIVE"

#: Helius, from `shitcoims_tape.recorder`: getTransactionsForAddress is 10 credits per 100 txs.
CREDITS_PER_TRANSACTION_PAGE: int = 10

#: Reported by :func:`max_feasible_wallets` when multiplicity has stopped being the binding
#: constraint. A larger number would be arithmetically true and operationally meaningless.
UNBOUNDED_WALLETS: int = 1_000_000_000


class SvnError(RuntimeError):
    """The estimator cannot proceed on this input. Fail closed rather than publish a number."""


class TradeState(StrEnum):
    """A wallet's state on one index element. Three states, hence nine typed tests per pair."""

    BUY = "b"
    SELL = "s"
    ROUND_TRIP = "r"


STATES: tuple[TradeState, ...] = (TradeState.BUY, TradeState.SELL, TradeState.ROUND_TRIP)

#: All nine typed tests, in a fixed order so the family is reproducible.
TEST_TYPES: tuple[tuple[TradeState, TradeState], ...] = tuple(
    (a, b) for a in STATES for b in STATES
)

#: The three types that carry the clustering weight. §4.1 records the paper's weights as 1-3,
#: which is exactly |{(b,b), (s,s), (r,r)}|.
SAME_ACTION: frozenset[tuple[TradeState, TradeState]] = frozenset(
    {
        (TradeState.BUY, TradeState.BUY),
        (TradeState.SELL, TradeState.SELL),
        (TradeState.ROUND_TRIP, TradeState.ROUND_TRIP),
    }
)

#: Kept and reported separately rather than dropped: one wallet buying exactly where another
#: sells, over and over, is the wash-trading signature signal #4 exists to find.
OPPOSITE_ACTION: frozenset[tuple[TradeState, TradeState]] = frozenset(
    {(TradeState.BUY, TradeState.SELL), (TradeState.SELL, TradeState.BUY)}
)


# ---------------------------------------------------------------------------------------------
# Exact and log-space hypergeometric tails
# ---------------------------------------------------------------------------------------------


def _log_comb(n: int, k: int) -> float:
    if k < 0 or k > n or n < 0:
        return -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def _logsumexp(values: Sequence[float]) -> float:
    finite = [v for v in values if v > -math.inf]
    if not finite:
        return -math.inf
    top = max(finite)
    return top + math.log(sum(math.exp(v - top) for v in finite))


def log_hypergeom_sf(*, total: int, successes: int, draws: int, observed: int) -> float:
    """``log P(X >= observed)`` for ``X ~ Hypergeometric(total, successes, draws)``.

    Log space throughout, because the interesting p-values here run past 1e-300 and a float
    p-value would underflow to exactly zero -- which then compares equal to every other
    underflowed pair and silently destroys the ranking the whole method rests on.

    The tail is summed from whichever end is numerically safe: above the mean the upper tail is
    summed directly, at or below it the complement of the lower tail is used, where the
    subtraction ``log1p(-cdf)`` is well conditioned.
    """
    if total < 0 or successes < 0 or draws < 0:
        raise SvnError("hypergeometric parameters must be non-negative")
    if successes > total or draws > total:
        raise SvnError("successes and draws cannot exceed the population")
    low = max(0, draws - (total - successes))
    high = min(successes, draws)
    if observed <= low:
        return 0.0
    if observed > high:
        return -math.inf
    denominator = _log_comb(total, draws)
    mean = successes * draws / total if total else 0.0
    if observed > mean:
        terms = [
            _log_comb(successes, x) + _log_comb(total - successes, draws - x) - denominator
            for x in range(observed, high + 1)
        ]
        return min(_logsumexp(terms), 0.0)
    terms = [
        _log_comb(successes, x) + _log_comb(total - successes, draws - x) - denominator
        for x in range(low, observed)
    ]
    log_cdf = min(_logsumexp(terms), -1e-16)
    return math.log1p(-math.exp(log_cdf))


def hypergeom_sf_exact(*, total: int, successes: int, draws: int, observed: int) -> Fraction:
    """Exact rational ``P(X >= observed)``. The reference the log-space path is tested against."""
    low = max(0, draws - (total - successes))
    high = min(successes, draws)
    if observed <= low:
        return Fraction(1)
    if observed > high:
        return Fraction(0)
    numerator = sum(
        math.comb(successes, x) * math.comb(total - successes, draws - x)
        for x in range(observed, high + 1)
    )
    return Fraction(numerator, math.comb(total, draws))


# ---------------------------------------------------------------------------------------------
# Feasibility gate -- run BEFORE spending anything
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Feasibility:
    """Can ANY pair clear Bonferroni at this scope? §4.1's gate, arithmetic not hope."""

    n_wallets: int
    n_index_elements: int
    tokens_per_wallet: int
    alpha: float
    n_tests: int
    log_bonferroni_threshold: float
    log_min_attainable_p: float
    feasible: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "n_wallets": self.n_wallets,
            "n_index_elements": self.n_index_elements,
            "tokens_per_wallet": self.tokens_per_wallet,
            "alpha": self.alpha,
            "n_tests": self.n_tests,
            "log10_bonferroni_threshold": self.log_bonferroni_threshold / math.log(10.0),
            "log10_min_attainable_p": self.log_min_attainable_p / math.log(10.0),
            "feasible": self.feasible,
        }


def feasibility_gate(
    *, n_wallets: int, n_index_elements: int, tokens_per_wallet: int, alpha: float = ALPHA
) -> Feasibility:
    """§4.1's gate: ``C(T, N) >= 9 n(n-1) / (2 alpha)``, expressed in logs so it never overflows.

    The most favourable configuration available to a pair of wallets each active on ``N`` of
    ``T`` tokens is *complete* overlap, whose hypergeometric p is exactly ``1 / C(T, N)``. If that
    best case does not clear the Bonferroni threshold, no data can rescue the design and the
    correct action is to change the scope, not to collect.
    """
    if n_wallets < 2:
        raise SvnError("a pair test needs at least two wallets")
    n_tests = 9 * (n_wallets * (n_wallets - 1) // 2)
    log_threshold = math.log(alpha) - math.log(n_tests)
    log_min_p = -_log_comb(n_index_elements, min(tokens_per_wallet, n_index_elements))
    return Feasibility(
        n_wallets=n_wallets,
        n_index_elements=n_index_elements,
        tokens_per_wallet=tokens_per_wallet,
        alpha=alpha,
        n_tests=n_tests,
        log_bonferroni_threshold=log_threshold,
        log_min_attainable_p=log_min_p,
        feasible=log_min_p <= log_threshold,
    )


def max_feasible_wallets(
    *, n_index_elements: int, tokens_per_wallet: int, alpha: float = ALPHA
) -> int:
    """Largest wallet universe at which ANY pair can still clear Bonferroni. The collection plan.

    Inverting the gate is what turns it from a post-hoc excuse into a scoping decision. Pairs grow
    as ``n^2`` while the smallest attainable p is fixed by ``T`` and the activity floor, so the
    universe has a hard ceiling and the only knobs are "watch more tokens" or "raise the activity
    floor". §4.1 records the version of this we got wrong: a design that works at 1,415 wallets
    was quoted as working at 50,000, and the difference is two orders of magnitude of `n`.
    """
    if tokens_per_wallet < 1 or n_index_elements < 1:
        raise SvnError("an activity floor and an index size are both required")
    # 9 * n(n-1)/2 <= alpha * C(T, N), in logs so C(3000, 20) does not overflow a float.
    log_budget = (
        math.log(alpha)
        + _log_comb(n_index_elements, min(tokens_per_wallet, n_index_elements))
        - math.log(9.0)
    )
    if log_budget > 40.0:
        # Beyond ~1e9 wallets the binding constraint stopped being multiplicity and became data
        # collection, so a larger number would be arithmetically true and operationally noise.
        return UNBOUNDED_WALLETS

    def ok(candidate: int) -> bool:
        return (
            candidate >= 2
            and feasibility_gate(
                n_wallets=candidate,
                n_index_elements=n_index_elements,
                tokens_per_wallet=tokens_per_wallet,
                alpha=alpha,
            ).feasible
        )

    n = max(int((1.0 + math.sqrt(1.0 + 8.0 * math.exp(log_budget))) / 2.0), 2)
    for _ in range(8):
        if ok(n + 1):
            n += 1
        elif not ok(n) and n > 2:
            n -= 1
        else:
            break
    return max(n, 2)


# ---------------------------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Print:
    """One directional fill, reduced to what the co-trading index needs.

    ``at`` is CHAIN time, always. Amounts are deliberately absent: this estimator uses only the
    sign, so there is no raw amount here to lose precision on.
    """

    wallet: str
    element: str
    is_buy: bool
    at: float


@dataclass(frozen=True, slots=True)
class Panel:
    """Who was in which state on which index element, and over what period each wallet lived."""

    states: Mapping[str, Mapping[str, TradeState]]
    element_time: Mapping[str, float]
    wallet_span: Mapping[str, tuple[float, float]]
    source: str
    n_prints: int
    bucket_hours: int | None = None
    n_dropped_no_time: int = 0
    #: True when the wallet set was chosen by a human watchlist rather than sampled from the
    #: population. A validated edge on such a set is conditioned on our own selection, so the
    #: study refuses to draw inference from it however good the p-value looks.
    wallets_are_a_watchlist: bool = False

    @property
    def wallets(self) -> tuple[str, ...]:
        return tuple(sorted(self.states))

    @property
    def elements(self) -> tuple[str, ...]:
        return tuple(sorted(self.element_time))


def panel_from_prints(
    prints: Iterable[Print],
    *,
    source: str,
    bucket_hours: int | None = None,
    wallets_are_a_watchlist: bool = False,
    n_dropped_no_time: int = 0,
) -> Panel:
    """Build the index. With ``bucket_hours`` the index element is ``mint@bucket``, else the mint.

    Tumminello indexes over (asset, trading day). Indexing over tokens alone is the
    coarsest honest analogue; the bucketed index is finer and therefore more powerful, at the
    cost of assuming that coordination is same-bucket. Both are available and the choice is
    recorded in the params, because §3 rule 7 says report the threshold with every number.
    """
    per_element: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    element_time: dict[str, float] = {}
    spans: dict[str, tuple[float, float]] = {}
    count = 0
    for item in prints:
        count += 1
        if bucket_hours is None:
            key = item.element
        else:
            bucket = int(item.at // (bucket_hours * 3600))
            key = f"{item.element}@{bucket}"
        per_element[key][item.wallet].append(item.is_buy)
        previous = element_time.get(key)
        element_time[key] = item.at if previous is None else min(previous, item.at)
        span = spans.get(item.wallet)
        spans[item.wallet] = (
            (item.at, item.at) if span is None else (min(span[0], item.at), max(span[1], item.at))
        )
    states: dict[str, dict[str, TradeState]] = defaultdict(dict)
    for key, wallets in per_element.items():
        for wallet, sides in wallets.items():
            if all(sides):
                states[wallet][key] = TradeState.BUY
            elif not any(sides):
                states[wallet][key] = TradeState.SELL
            else:
                states[wallet][key] = TradeState.ROUND_TRIP
    return Panel(
        states={w: dict(v) for w, v in states.items()},
        element_time=element_time,
        wallet_span=spans,
        source=source,
        n_prints=count,
        bucket_hours=bucket_hours,
        n_dropped_no_time=n_dropped_no_time,
        wallets_are_a_watchlist=wallets_are_a_watchlist,
    )


def prints_from_store(store: Path, *, bucket_hours: int | None = None) -> Panel:
    """Read a COPY of ``intelligence.sqlite3`` through the tape's own importer.

    The importer is used rather than the raw rows because it is the one place that knows this
    store INVERTS its two clocks between row kinds: for ``wallet_transaction`` the block time is
    in ``emitted_at`` and the fetch stamp is in ``observed_at``, the reverse of its social rows.
    It also refuses multi-leg transactions instead of splitting one SOL delta across legs. Both
    behaviours are load-bearing and neither should be re-derived at a call site.
    """
    if not store.exists():
        raise SvnError(f"no store at {store}; copy it first, the daemon holds a lock")
    connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT subject_id, observed_at, emitted_at, payload_json FROM observations "
            "WHERE kind='wallet_transaction'"
        ).fetchall()
    finally:
        connection.close()
    shaped = [
        {
            "subject_id": subject,
            "observed_at": observed_at,
            "emitted_at": emitted_at,
            "payload": json.loads(payload_json),
        }
        for subject, observed_at, emitted_at, payload_json in rows
    ]
    prints: list[Print] = []
    dropped = 0
    for event in load_intelligence_wallet_transactions(shaped):
        body = getattr(event, "body", None)
        chain = getattr(event, "chain", None)
        if body is None or chain is None:
            continue
        if chain.block_time is None:
            dropped += 1
            continue
        prints.append(
            Print(
                wallet=body.wallet,
                element=body.mint,
                is_buy=body.token_delta_raw > 0,
                at=float(chain.block_time),
            )
        )
    return panel_from_prints(
        prints,
        source="intelligence.wallet_transaction",
        bucket_hours=bucket_hours,
        wallets_are_a_watchlist=True,
        n_dropped_no_time=dropped,
    )


# ---------------------------------------------------------------------------------------------
# Pair statistics with a PAIR-SPECIFIC index size
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PairTest:
    """One of the nine typed tests for one pair. ``log_p`` is the hypergeometric survival."""

    left: int
    right: int
    left_state: TradeState
    right_state: TradeState
    total: int
    left_marginal: int
    right_marginal: int
    observed: int
    log_p: float

    @property
    def key(self) -> tuple[int, int]:
        return (self.left, self.right)

    @property
    def type_key(self) -> tuple[TradeState, TradeState]:
        return (self.left_state, self.right_state)


class _Index:
    """Time-sorted views that make a pair-specific window an O(log T) lookup rather than O(T)."""

    def __init__(self, panel: Panel) -> None:
        self.wallets = panel.wallets
        self.position = {wallet: i for i, wallet in enumerate(self.wallets)}
        self.element_times = sorted(panel.element_time.values())
        self.span = [panel.wallet_span[w] for w in self.wallets]
        # Per wallet: its elements sorted by time, plus a prefix count per state, so a marginal
        # restricted to the pair's overlap window is two subtractions.
        self.times: list[list[float]] = []
        self.prefix: list[dict[TradeState, list[int]]] = []
        self.state_of: list[dict[str, TradeState]] = []
        for wallet in self.wallets:
            items = sorted(
                panel.states[wallet].items(), key=lambda kv: (panel.element_time[kv[0]], kv[0])
            )
            self.times.append([panel.element_time[key] for key, _ in items])
            counts = {state: [0] for state in STATES}
            for _, state in items:
                for candidate in STATES:
                    counts[candidate].append(counts[candidate][-1] + (1 if candidate is state else 0))
            self.prefix.append(counts)
            self.state_of.append(dict(items))

    def overlap(self, left: int, right: int) -> tuple[float, float] | None:
        low = max(self.span[left][0], self.span[right][0])
        high = min(self.span[left][1], self.span[right][1])
        return (low, high) if low <= high else None

    def total_in(self, window: tuple[float, float]) -> int:
        low, high = window
        return bisect_right(self.element_times, high) - bisect_left(self.element_times, low)

    def marginal_in(self, wallet: int, state: TradeState, window: tuple[float, float]) -> int:
        low, high = window
        times = self.times[wallet]
        start = bisect_left(times, low)
        end = bisect_right(times, high)
        counts = self.prefix[wallet][state]
        return counts[end] - counts[start]


def pair_tests(panel: Panel) -> tuple[list[PairTest], int, int]:
    """All nine typed tests for every pair with a non-empty co-occurrence, plus family sizes.

    Returns ``(tests, n_tests_performed, n_testable_pairs)``. Pairs with zero co-occurrence have
    ``p = 1`` by definition and are not enumerated -- they can never be rejected by BH or
    Bonferroni, so omitting them changes no decision, and enumerating O(n^2) certainties would
    dominate the runtime for no information.

    The multiplicity correction is applied over the tests actually PERFORMED, which is nine per
    pair whose activity periods overlap. The naive ``9 C(n,2)`` upper bound is reported next to
    it so the choice is visible rather than assumed.
    """
    index = _Index(panel)
    observed: dict[tuple[int, int], dict[tuple[TradeState, TradeState], int]] = defaultdict(
        lambda: defaultdict(int)
    )
    by_element: dict[str, list[int]] = defaultdict(list)
    for position, wallet in enumerate(index.wallets):
        for key in panel.states[wallet]:
            by_element[key].append(position)
    for key, members in by_element.items():
        moment = panel.element_time[key]
        members.sort()
        for a_pos in range(len(members)):
            left = members[a_pos]
            for b_pos in range(a_pos + 1, len(members)):
                right = members[b_pos]
                window = index.overlap(left, right)
                if window is None or not window[0] <= moment <= window[1]:
                    continue
                observed[(left, right)][
                    (index.state_of[left][key], index.state_of[right][key])
                ] += 1

    testable = 0
    for left in range(len(index.wallets)):
        for right in range(left + 1, len(index.wallets)):
            if index.overlap(left, right) is not None:
                testable += 1

    tests: list[PairTest] = []
    for (left, right), counts in observed.items():
        window = index.overlap(left, right)
        if window is None:
            continue
        total = index.total_in(window)
        if total <= 0:
            continue
        for (left_state, right_state), count in counts.items():
            left_marginal = index.marginal_in(left, left_state, window)
            right_marginal = index.marginal_in(right, right_state, window)
            if left_marginal == 0 or right_marginal == 0:
                continue
            log_p = log_hypergeom_sf(
                total=total, successes=left_marginal, draws=right_marginal, observed=count
            )
            tests.append(
                PairTest(
                    left=left,
                    right=right,
                    left_state=left_state,
                    right_state=right_state,
                    total=total,
                    left_marginal=left_marginal,
                    right_marginal=right_marginal,
                    observed=count,
                    log_p=log_p,
                )
            )
    tests.sort(key=lambda t: (t.left, t.right, t.left_state, t.right_state))
    return tests, 9 * testable, testable


# ---------------------------------------------------------------------------------------------
# Multiplicity
# ---------------------------------------------------------------------------------------------


def bonferroni_log_threshold(*, alpha: float, family_size: int) -> float:
    if family_size <= 0:
        raise SvnError("an empty family has no Bonferroni threshold")
    return math.log(alpha) - math.log(family_size)


def bh_fdr_log(
    log_p_values: Sequence[float], *, q: float, family_size: int
) -> tuple[list[bool], float]:
    """Benjamini-Hochberg on log p-values over a family that may be LARGER than the input.

    ``family_size`` is the number of tests performed, not the number enumerated here. Tests whose
    p is exactly 1 (a pair with zero co-occurrence in that type) sort last and can never be
    rejected, so leaving them out of the array is free -- but leaving them out of the DENOMINATOR
    would understate the correction by orders of magnitude. That is the mistake this signature
    exists to make impossible.
    """
    if family_size < len(log_p_values):
        raise SvnError("family_size cannot be smaller than the number of enumerated tests")
    if not log_p_values:
        return [], -math.inf
    order = sorted(range(len(log_p_values)), key=lambda i: log_p_values[i])
    log_q = math.log(q)
    log_m = math.log(family_size)
    cut = -1
    for rank, position in enumerate(order, start=1):
        if log_p_values[position] <= log_q + math.log(rank) - log_m:
            cut = rank
    flags = [False] * len(log_p_values)
    if cut < 0:
        return flags, -math.inf
    for rank, position in enumerate(order, start=1):
        if rank <= cut:
            flags[position] = True
    return flags, log_q + math.log(cut) - log_m


# ---------------------------------------------------------------------------------------------
# Null model 2 -- degree-preserving randomisation
# ---------------------------------------------------------------------------------------------


def curveball(rows: Sequence[frozenset[int]], *, rng: random.Random, swaps: int) -> list[set[int]]:
    """Curveball trades on a binary incidence matrix. Preserves BOTH row and column sums exactly.

    Row sums are each wallet's token count; column sums are each token's participant count. The
    second is the one that matters here: it is what makes "everyone was in the hot token"
    un-surprising under this null, which is precisely the artefact the hypergeometric cannot see.
    """
    current = [set(row) for row in rows]
    size = len(current)
    if size < 2:
        return current
    for _ in range(swaps):
        left = rng.randrange(size)
        right = rng.randrange(size)
        if left == right:
            continue
        shared = current[left] & current[right]
        only_left = current[left] - shared
        only_right = current[right] - shared
        pool = sorted(only_left | only_right)
        if not pool:
            continue
        rng.shuffle(pool)
        take = len(only_left)
        current[left] = shared | set(pool[:take])
        current[right] = shared | set(pool[take:])
    return current


@dataclass(frozen=True, slots=True)
class NullDraw:
    """Per (pair, type): how often the null reached the observed count, and how far out it sat."""

    tail_count: int
    draws: int
    mean: float

    @property
    def empirical_p(self) -> float:
        return (1.0 + self.tail_count) / (1.0 + self.draws)

    @property
    def p_floor(self) -> float:
        return 1.0 / (1.0 + self.draws)

    def log_score(self, observed: int) -> float:
        """A total order over pairs, empirical where the null resolves and extrapolated below.

        The empirical p cannot go below ``1/(B+1)``, and at any realistic multiplicity most
        interesting pairs are pinned there -- including a pair that co-occurred once against a
        null mean of 0.02 and a pair that co-occurred seven times against a null mean of 0.5,
        which are not remotely equally surprising. Matched density needs those separated.

        Below the floor the score is therefore a POISSON upper tail calibrated to the null's own
        mean, floored at the null's resolution. It is a RANKING DEVICE for the density-matched
        comparison and is never reported as a p-value; a z-score would not do, because a null that
        produced the same value in every draw has zero variance and would send every such pair to
        the same infinity -- which is precisely the degeneracy this replaced.
        """
        if self.tail_count > 0:
            return math.log(self.empirical_p)
        rate = max(self.mean, self.p_floor)
        return min(math.log(self.p_floor), _log_poisson_sf(observed, rate))


def _log_poisson_sf(k: int, rate: float) -> float:
    """``log P(X >= k)`` for ``X ~ Poisson(rate)``. Upper tail only, summed in log space."""
    if k <= 0:
        return 0.0
    if rate <= 0.0:
        return -math.inf
    terms: list[float] = []
    log_rate = math.log(rate)
    index = k
    while True:
        term = -rate + index * log_rate - math.lgamma(index + 1)
        terms.append(term)
        index += 1
        if index > k + 5 and term < terms[0] - 40.0:
            break
        if index > k + 2000:
            break
    return min(_logsumexp(terms), 0.0)


def degree_preserving_null(
    panel: Panel,
    tests: Sequence[PairTest],
    *,
    rng: random.Random,
    draws: int = RANDOMISATIONS,
    swaps_per_draw: int | None = None,
    burn_in: int | None = None,
) -> dict[tuple[int, int, TradeState, TradeState], NullDraw]:
    """Empirical tail probabilities for the enumerated tests under a degree-preserving null.

    The randomisation preserves, exactly: every wallet's token count, every token's participant
    count, and every wallet's own multiset of states. It does NOT preserve each token's state
    composition -- that would require a joint model this sample cannot identify, and claiming it
    does would be the kind of quiet overreach this file exists to avoid.

    The pair-specific window is applied to the randomised panel exactly as to the observed one,
    so the comparison is like-for-like rather than a randomised count against a windowed one.
    """
    index = _Index(panel)
    wallets = index.wallets
    element_ids = {key: i for i, key in enumerate(sorted(panel.element_time))}
    element_time = [0.0] * len(element_ids)
    for key, position in element_ids.items():
        element_time[position] = panel.element_time[key]
    rows = [
        frozenset(element_ids[key] for key in panel.states[wallet]) for wallet in wallets
    ]
    state_bags = [
        sorted(panel.states[wallet].values(), key=lambda s: s.value) for wallet in wallets
    ]
    wanted = {(t.left, t.right, t.left_state, t.right_state): t.observed for t in tests}
    tail: dict[tuple[int, int, TradeState, TradeState], int] = dict.fromkeys(wanted, 0)
    total: dict[tuple[int, int, TradeState, TradeState], float] = dict.fromkeys(wanted, 0.0)

    ones = sum(len(row) for row in rows)
    steps = swaps_per_draw if swaps_per_draw is not None else max(200, 2 * ones)
    state = [set(row) for row in rows]
    if burn_in is None:
        burn_in = steps * 5
    state = curveball([frozenset(row) for row in state], rng=rng, swaps=burn_in)
    for _ in range(draws):
        state = curveball([frozenset(row) for row in state], rng=rng, swaps=steps)
        assigned: list[dict[int, TradeState]] = []
        for position, row in enumerate(state):
            bag = list(state_bags[position])
            rng.shuffle(bag)
            assigned.append(dict(zip(sorted(row), bag, strict=True)))
        members: dict[int, list[int]] = defaultdict(list)
        for position, row in enumerate(state):
            for element in row:
                members[element].append(position)
        counts: dict[tuple[int, int, TradeState, TradeState], int] = defaultdict(int)
        for element, present in members.items():
            moment = element_time[element]
            present.sort()
            for a_pos in range(len(present)):
                left = present[a_pos]
                for b_pos in range(a_pos + 1, len(present)):
                    right = present[b_pos]
                    window = index.overlap(left, right)
                    if window is None or not window[0] <= moment <= window[1]:
                        continue
                    counts[(left, right, assigned[left][element], assigned[right][element])] += 1
        for key, observed in wanted.items():
            value = counts.get(key, 0)
            total[key] += value
            if value >= observed:
                tail[key] += 1
    out: dict[tuple[int, int, TradeState, TradeState], NullDraw] = {}
    for key in wanted:
        mean = total[key] / draws if draws else 0.0
        out[key] = NullDraw(tail_count=tail[key], draws=draws, mean=mean)
    return out


# ---------------------------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Network:
    """A validated network: same-action edges carry the weight, everything else is reported."""

    name: str
    edges: Mapping[tuple[int, int], int]
    opposite_edges: Mapping[tuple[int, int], int]
    mixed_edges: Mapping[tuple[int, int], int]
    n_validated_tests: int

    @property
    def n_edges(self) -> int:
        return len(self.edges)

    @property
    def nodes(self) -> tuple[int, ...]:
        return tuple(sorted({node for edge in self.edges for node in edge}))


def network_from(
    tests: Sequence[PairTest], accepted: Sequence[bool], *, name: str
) -> Network:
    same: dict[tuple[int, int], int] = defaultdict(int)
    opposite: dict[tuple[int, int], int] = defaultdict(int)
    mixed: dict[tuple[int, int], int] = defaultdict(int)
    validated = 0
    for test, flag in zip(tests, accepted, strict=True):
        if not flag:
            continue
        validated += 1
        if test.type_key in SAME_ACTION:
            same[test.key] += 1
        elif test.type_key in OPPOSITE_ACTION:
            opposite[test.key] += 1
        else:
            mixed[test.key] += 1
    return Network(
        name=name,
        edges=dict(same),
        opposite_edges=dict(opposite),
        mixed_edges=dict(mixed),
        n_validated_tests=validated,
    )


def union_find_components(edges: Mapping[tuple[int, int], int]) -> dict[int, int]:
    """Connected components. Present ONLY as the documented failure mode -- see the docstring."""
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        parent.setdefault(node, node)
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    for left, right in edges:
        a, b = find(left), find(right)
        if a != b:
            parent[min(a, b)] = min(a, b)
            parent[max(a, b)] = min(a, b)
    return {node: find(node) for node in parent}


def giant_component_share(edges: Mapping[tuple[int, int], int]) -> float:
    """Fraction of nodes in the largest connected component. §4.1 measured 0.996 on the FDR net."""
    labels = union_find_components(edges)
    if not labels:
        return 0.0
    sizes: dict[int, int] = defaultdict(int)
    for label in labels.values():
        sizes[label] += 1
    return max(sizes.values()) / len(labels)


def _plogp(value: float) -> float:
    return value * math.log2(value) if value > 0.0 else 0.0


class _MapEquation:
    """Two-level map equation over an undirected weighted graph, optimised by local moving.

    This is Infomap's core objective and its core move set (Rosvall & Bergstrom 2008), not a
    modularity proxy: modularity has a resolution limit that would merge exactly the small
    validated cliques this study is looking for. Aggregation is replaced by an explicit
    module-merge pass, which is adequate at the size of a validated network and keeps the
    implementation deterministic and auditable.
    """

    def __init__(self, edges: Mapping[tuple[int, int], int]) -> None:
        self.adjacency: dict[int, dict[int, float]] = defaultdict(dict)
        for (left, right), weight in edges.items():
            self.adjacency[left][right] = float(weight)
            self.adjacency[right][left] = float(weight)
        self.nodes = sorted(self.adjacency)
        self.strength = {node: sum(self.adjacency[node].values()) for node in self.nodes}
        self.two_w = sum(self.strength.values())
        self.p = {node: self.strength[node] / self.two_w for node in self.nodes} if self.two_w else {}
        self.module = {node: node for node in self.nodes}
        self.module_p = {node: self.p.get(node, 0.0) for node in self.nodes}
        self.module_exit = {node: self.strength[node] for node in self.nodes}

    def _q(self, module: int) -> float:
        return self.module_exit[module] / self.two_w

    def code_length(self) -> float:
        q_total = sum(self._q(m) for m in self.module_p)
        value = _plogp(q_total) - sum(self._plogp_p(node) for node in self.nodes)
        for module in self.module_p:
            q = self._q(module)
            value += -2.0 * _plogp(q) + _plogp(q + self.module_p[module])
        return value

    def _plogp_p(self, node: int) -> float:
        return _plogp(self.p[node])

    def _weights_to_modules(self, node: int) -> dict[int, float]:
        out: dict[int, float] = defaultdict(float)
        for neighbour, weight in self.adjacency[node].items():
            out[self.module[neighbour]] += weight
        return out

    def _delta(
        self,
        *,
        node: int,
        source: int,
        target: int,
        to_source: float,
        to_target: float,
        q_total: float,
    ) -> tuple[float, float, float]:
        strength = self.strength[node]
        exit_source = self.module_exit[source] - strength + 2.0 * to_source
        exit_target = self.module_exit[target] + strength - 2.0 * to_target
        q_source, q_target = exit_source / self.two_w, exit_target / self.two_w
        p_source = self.module_p[source] - self.p[node]
        p_target = self.module_p[target] + self.p[node]
        old_q_source, old_q_target = self._q(source), self._q(target)
        new_total = q_total - old_q_source - old_q_target + q_source + q_target
        delta = _plogp(new_total) - _plogp(q_total)
        delta -= 2.0 * (_plogp(q_source) + _plogp(q_target) - _plogp(old_q_source) - _plogp(old_q_target))
        delta += _plogp(q_source + p_source) + _plogp(q_target + p_target)
        delta -= _plogp(old_q_source + self.module_p[source]) + _plogp(
            old_q_target + self.module_p[target]
        )
        return delta, exit_source, exit_target

    def optimise(self, *, rounds: int = 50) -> dict[int, int]:
        if not self.two_w:
            return {}
        for _ in range(rounds):
            moved = self._local_moving()
            merged = self._merge_modules()
            if not moved and not merged:
                break
        labels = sorted(set(self.module.values()))
        relabel = {label: i for i, label in enumerate(labels)}
        return {node: relabel[self.module[node]] for node in self.nodes}

    def _local_moving(self) -> bool:
        changed = False
        for _ in range(20):
            round_moved = False
            for node in self.nodes:
                source = self.module[node]
                weights = self._weights_to_modules(node)
                q_total = sum(self._q(m) for m in self.module_p)
                best_delta, best_target, best_exits = 0.0, source, None
                for target, to_target in sorted(weights.items()):
                    if target == source:
                        continue
                    delta, exit_source, exit_target = self._delta(
                        node=node,
                        source=source,
                        target=target,
                        to_source=weights.get(source, 0.0),
                        to_target=to_target,
                        q_total=q_total,
                    )
                    if delta < best_delta - 1e-12:
                        best_delta, best_target, best_exits = delta, target, (exit_source, exit_target)
                if best_exits is None:
                    continue
                exit_source, exit_target = best_exits
                self.module_exit[source] = exit_source
                self.module_exit[best_target] = exit_target
                self.module_p[source] -= self.p[node]
                self.module_p[best_target] += self.p[node]
                self.module[node] = best_target
                if self.module_p[source] <= 1e-15:
                    self.module_p.pop(source, None)
                    self.module_exit.pop(source, None)
                round_moved = changed = True
            if not round_moved:
                break
        return changed

    def _merge_modules(self) -> bool:
        changed = False
        for _ in range(20):
            between: dict[tuple[int, int], float] = defaultdict(float)
            for node in self.nodes:
                for neighbour, weight in self.adjacency[node].items():
                    a, b = self.module[node], self.module[neighbour]
                    if a < b:
                        between[(a, b)] += weight
            q_total = sum(self._q(m) for m in self.module_p)
            best_delta, best_pair, best_exit = 0.0, None, 0.0
            for (a, b), weight in sorted(between.items()):
                exit_merged = self.module_exit[a] + self.module_exit[b] - 2.0 * weight
                q_merged = exit_merged / self.two_w
                q_a, q_b = self._q(a), self._q(b)
                p_merged = self.module_p[a] + self.module_p[b]
                new_total = q_total - q_a - q_b + q_merged
                delta = _plogp(new_total) - _plogp(q_total)
                delta -= 2.0 * (_plogp(q_merged) - _plogp(q_a) - _plogp(q_b))
                delta += _plogp(q_merged + p_merged)
                delta -= _plogp(q_a + self.module_p[a]) + _plogp(q_b + self.module_p[b])
                if delta < best_delta - 1e-12:
                    best_delta, best_pair, best_exit = delta, (a, b), exit_merged
            if best_pair is None:
                break
            a, b = best_pair
            for node in self.nodes:
                if self.module[node] == b:
                    self.module[node] = a
            self.module_exit[a] = best_exit
            self.module_p[a] += self.module_p[b]
            self.module_p.pop(b, None)
            self.module_exit.pop(b, None)
            changed = True
        return changed


def infomap_communities(edges: Mapping[tuple[int, int], int]) -> dict[int, int]:
    """Weighted two-level map-equation partition. §4.1: NOT union-find, which returns one blob."""
    return _MapEquation(edges).optimise()


# ---------------------------------------------------------------------------------------------
# Matched-density comparison (Cimini et al. 2022)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatchedDensity:
    """Two nulls compared at the SAME number of edges, which is the only valid comparison."""

    density: int
    overlap: int
    jaccard: float
    hyper_only: int
    degree_only: int
    adjusted_rand: float
    hyper_edges_at_own_threshold: int
    degree_edges_at_p_floor_uncorrected: int
    degree_edges_at_bh: int
    degree_p_floor: float

    def to_json(self) -> dict[str, Any]:
        return {
            "matched_density_edges": self.density,
            "overlap": self.overlap,
            "jaccard": self.jaccard,
            "hypergeometric_only": self.hyper_only,
            "degree_preserving_only": self.degree_only,
            "adjusted_rand_index": self.adjusted_rand,
            "hypergeometric_edges_at_bonferroni": self.hyper_edges_at_own_threshold,
            # Both of the next two are UNUSABLE, and are printed so that is visible rather than
            # asserted. The first is an uncorrected 1/(B+1) cut over tens of thousands of tests.
            # The second is BH applied to p-values that are all TIED at their floor, which makes
            # it a step function of how many tests happen to tie there: below the BH rank it
            # rejects nothing, and one test past it the whole tied block is rejected at once.
            # Neither is a threshold. Matched density is the comparison.
            "degree_preserving_edges_at_p_floor_uncorrected": self.degree_edges_at_p_floor_uncorrected,
            "degree_preserving_edges_at_bh_on_discrete_p": self.degree_edges_at_bh,
            "degree_preserving_p_floor": self.degree_p_floor,
        }


def adjusted_rand_index(left: Mapping[int, int], right: Mapping[int, int]) -> float:
    """ARI over the union of nodes, unlabelled nodes counted as singletons.

    Singletons matter: a null model that validates nothing yields all-singletons, and a measure
    that ignored them would score that as perfect agreement with anything.
    """
    nodes = sorted(set(left) | set(right))
    if len(nodes) < 2:
        return 1.0
    next_left = max(left.values(), default=-1) + 1
    next_right = max(right.values(), default=-1) + 1
    a_labels: dict[int, int] = {}
    b_labels: dict[int, int] = {}
    for node in nodes:
        if node in left:
            a_labels[node] = left[node]
        else:
            a_labels[node] = next_left
            next_left += 1
        if node in right:
            b_labels[node] = right[node]
        else:
            b_labels[node] = next_right
            next_right += 1
    table: dict[tuple[int, int], int] = defaultdict(int)
    rows: dict[int, int] = defaultdict(int)
    columns: dict[int, int] = defaultdict(int)
    for node in nodes:
        table[(a_labels[node], b_labels[node])] += 1
        rows[a_labels[node]] += 1
        columns[b_labels[node]] += 1
    total = len(nodes)
    sum_table = sum(math.comb(v, 2) for v in table.values())
    sum_rows = sum(math.comb(v, 2) for v in rows.values())
    sum_columns = sum(math.comb(v, 2) for v in columns.values())
    expected = sum_rows * sum_columns / math.comb(total, 2)
    maximum = 0.5 * (sum_rows + sum_columns)
    if maximum == expected:
        return 1.0
    return (sum_table - expected) / (maximum - expected)


# ---------------------------------------------------------------------------------------------
# Baselines and metrics (§3 rule 4: baselines BEFORE models; rule 5: base-rate-preserving)
# ---------------------------------------------------------------------------------------------


def average_precision(scored: Sequence[tuple[float, bool]], *, n_positive_total: int) -> float:
    """Average precision with tie-aware groups. ``n_positive_total`` includes unranked positives.

    AUPRC, never ROC-AUC: the positive class here (pairs inside one planted cluster) is a few
    percent of all pairs, and ROC-AUC at that base rate reads ~0.99 for a scorer that is useless
    at the only operating point anyone would use.
    """
    if n_positive_total <= 0:
        return 0.0
    ordered = sorted(scored, key=lambda item: -item[0])
    total = 0.0
    seen = 0
    hits = 0
    position = 0
    while position < len(ordered):
        end = position
        while end < len(ordered) and ordered[end][0] == ordered[position][0]:
            end += 1
        block = ordered[position:end]
        block_positive = sum(1 for _, label in block if label)
        for step in range(len(block)):
            seen += 1
            precision = (hits + block_positive * (step + 1) / len(block)) / seen
            if step < block_positive:
                total += precision
        hits += block_positive
        position = end
    return total / n_positive_total


def precision_at_k(scored: Sequence[tuple[float, bool]], *, k: int) -> float:
    if k <= 0:
        return 0.0
    ordered = sorted(scored, key=lambda item: -item[0])[:k]
    return sum(1 for _, label in ordered if label) / max(len(ordered), 1)


# ---------------------------------------------------------------------------------------------
# Study result
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NetworkSummary:
    name: str
    n_validated_tests: int
    n_same_action_edges: int
    n_opposite_action_edges: int
    n_mixed_edges: int
    n_clusters: int
    largest_cluster: int
    n_clustered_wallets: int
    giant_component_share: float
    union_find_components: int

    def to_json(self) -> dict[str, Any]:
        return {
            "null_model": self.name,
            "validated_tests": self.n_validated_tests,
            "same_action_edges": self.n_same_action_edges,
            "opposite_action_edges": self.n_opposite_action_edges,
            "mixed_edges": self.n_mixed_edges,
            "clusters": self.n_clusters,
            "largest_cluster": self.largest_cluster,
            "clustered_wallets": self.n_clustered_wallets,
            "union_find_giant_component_share": self.giant_component_share,
            "union_find_components": self.union_find_components,
        }


@dataclass(frozen=True, slots=True)
class RecoveryMetrics:
    """Only computable against planted ground truth, i.e. never on real data."""

    method: str
    average_precision: float
    precision_at_k: float
    k: int
    base_rate: float

    def to_json(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "average_precision": self.average_precision,
            "precision_at_k": self.precision_at_k,
            "k": self.k,
            "pair_base_rate": self.base_rate,
        }


@dataclass(frozen=True, slots=True)
class Holdout:
    """Temporal out-of-sample check: cluster on the early half, re-test on the late half."""

    n_train_elements: int
    n_test_elements: int
    n_train_edges: int
    #: Train edges whose BOTH wallets are still active in the test half. A cluster that operated
    #: entirely inside one fold has an eligibility of zero, and its zero reconfirmation is then a
    #: STRUCTURAL fact about time-localised rings, not evidence the cluster was spurious. Reading
    #: the rate without this denominator would turn "we could not look" into "we looked and found
    #: nothing", which is the same error as a displacement-censored graduation rate.
    n_train_edges_eligible: int
    n_reconfirmed: int
    reconfirmation_rate: float
    n_control_pairs: int
    n_control_pairs_eligible: int
    control_rate: float

    def to_json(self) -> dict[str, Any]:
        return {
            "train_elements": self.n_train_elements,
            "test_elements": self.n_test_elements,
            "train_edges": self.n_train_edges,
            "train_edges_eligible_in_holdout": self.n_train_edges_eligible,
            "reconfirmed_in_holdout": self.n_reconfirmed,
            "reconfirmation_rate_over_eligible": self.reconfirmation_rate,
            "control_pairs": self.n_control_pairs,
            "control_pairs_eligible": self.n_control_pairs_eligible,
            "control_reconfirmation_rate_over_eligible": self.control_rate,
        }


@dataclass(frozen=True, slots=True)
class StudyResult:
    verdict: str
    reason: str
    source: str
    n_wallets: int
    n_index_elements: int
    n_prints: int
    n_dropped_no_time: int
    n_testable_pairs: int
    n_tests_performed: int
    n_tests_naive_upper_bound: int
    log10_bonferroni_threshold: float
    log10_bh_threshold: float
    feasibility: Feasibility | None
    bonferroni: NetworkSummary | None = None
    fdr: NetworkSummary | None = None
    degree_preserving: NetworkSummary | None = None
    robust: NetworkSummary | None = None
    matched: MatchedDensity | None = None
    recovery: tuple[RecoveryMetrics, ...] = ()
    holdout: Holdout | None = None
    entity_links: tuple[Any, ...] = ()
    notes: tuple[str, ...] = ()
    params: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "source": self.source,
            "n_wallets": self.n_wallets,
            "n_index_elements": self.n_index_elements,
            "n_prints": self.n_prints,
            "n_dropped_no_block_time": self.n_dropped_no_time,
            "n_testable_pairs": self.n_testable_pairs,
            "n_tests_performed": self.n_tests_performed,
            "n_tests_naive_upper_bound": self.n_tests_naive_upper_bound,
            "log10_bonferroni_threshold": self.log10_bonferroni_threshold,
            "log10_bh_threshold": self.log10_bh_threshold,
            "feasibility": None if self.feasibility is None else self.feasibility.to_json(),
            "bonferroni": None if self.bonferroni is None else self.bonferroni.to_json(),
            "fdr": None if self.fdr is None else self.fdr.to_json(),
            "degree_preserving": (
                None if self.degree_preserving is None else self.degree_preserving.to_json()
            ),
            "robust": None if self.robust is None else self.robust.to_json(),
            "matched_density": None if self.matched is None else self.matched.to_json(),
            "recovery": [item.to_json() for item in self.recovery],
            "holdout": None if self.holdout is None else self.holdout.to_json(),
            "entity_links": [link.to_json() for link in self.entity_links],
            "notes": list(self.notes),
            "params": dict(self.params),
        }


def _summarise(network: Network) -> NetworkSummary:
    communities = infomap_communities(network.edges)
    sizes: dict[int, int] = defaultdict(int)
    for label in communities.values():
        sizes[label] += 1
    clusters = {label: size for label, size in sizes.items() if size >= 2}
    return NetworkSummary(
        name=network.name,
        n_validated_tests=network.n_validated_tests,
        n_same_action_edges=len(network.edges),
        n_opposite_action_edges=len(network.opposite_edges),
        n_mixed_edges=len(network.mixed_edges),
        n_clusters=len(clusters),
        largest_cluster=max(clusters.values(), default=0),
        n_clustered_wallets=sum(clusters.values()),
        giant_component_share=giant_component_share(network.edges),
        union_find_components=len(set(union_find_components(network.edges).values())),
    )


def _entity_links(
    network: Network,
    *,
    wallets: Sequence[str],
    tests: Sequence[PairTest],
    accepted: Sequence[bool],
    robust_edges: frozenset[tuple[int, int]],
    incident_from: Network,
    method: str,
) -> tuple[Any, ...]:
    """Interface #7 records, one per clustered wallet.

    ``confidence`` is the fraction of this wallet's validated same-action edges that SURVIVE the
    change of null model at matched density. That is Cimini's caveat turned into a number a
    consumer can threshold on: a link that exists only because the hypergeometric assumes uniform
    token popularity gets a low confidence rather than a footnote nobody reads.
    """
    communities = infomap_communities(network.edges)
    sizes: dict[int, int] = defaultdict(int)
    for label in communities.values():
        sizes[label] += 1
    best_log_p: dict[tuple[int, int], float] = {}
    for test, flag in zip(tests, accepted, strict=True):
        if flag and test.type_key in SAME_ACTION:
            key = test.key
            best_log_p[key] = min(best_log_p.get(key, math.inf), test.log_p)
    incident: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for edge in incident_from.edges:
        incident[edge[0]].append(edge)
        incident[edge[1]].append(edge)
    links: list[Any] = []
    for node, label in sorted(communities.items()):
        if sizes[label] < 2:
            continue
        mine = incident[node]
        robust = sum(1 for edge in mine if edge in robust_edges)
        confidence = robust / len(mine) if mine else 0.0
        strongest = min((best_log_p.get(edge, 0.0) for edge in mine), default=0.0)
        links.append(
            EntityLink(
                wallet=wallets[node],
                entity_id=f"svn:{label:05d}",
                method=method,
                confidence=round(confidence, 6),
                evidence=(
                    f"same_action_edges={len(mine)}",
                    f"weight_sum={sum(incident_from.edges[edge] for edge in mine)}",
                    f"log10_min_p={strongest / math.log(10.0):.4g}",
                    f"null_robust_edges={robust}/{len(mine)}",
                    f"cluster_size={sizes[label]}",
                ),
            )
        )
    return tuple(links)


# ---------------------------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------------------------


def run_study(
    panel: Panel,
    *,
    seed: int,
    alpha: float = ALPHA,
    q: float = FDR_Q,
    randomisations: int = RANDOMISATIONS,
    min_wallets: int = MIN_WALLETS,
    planted: Mapping[str, int] | None = None,
    holdout: bool = True,
    swaps_per_draw: int | None = None,
) -> StudyResult:
    """Run the estimator and return one verdict. Deterministic given ``seed``.

    ``planted`` is ground truth for a SIMULATED panel and is structurally unavailable on real
    data; supplying it only enables the recovery metrics.
    """
    wallets = panel.wallets
    n_wallets = len(wallets)
    params: dict[str, Any] = {
        "seed": seed,
        "alpha": alpha,
        "fdr_q": q,
        "randomisations": randomisations,
        "min_wallets": min_wallets,
        "typed_tests_per_pair": len(TEST_TYPES),
        "clustering": "weighted two-level map equation (Infomap core)",
        "clustering_link_types": sorted(f"{a}{b}" for a, b in SAME_ACTION),
        "index": "token" if panel.bucket_hours is None else f"token-x-{panel.bucket_hours}h-bucket",
        "pair_specific_T": True,
    }
    naive = 9 * (n_wallets * (n_wallets - 1) // 2) if n_wallets >= 2 else 0
    base = StudyResult(
        verdict=VERDICT_UNRESOLVABLE,
        reason="",
        source=panel.source,
        n_wallets=n_wallets,
        n_index_elements=len(panel.element_time),
        n_prints=panel.n_prints,
        n_dropped_no_time=panel.n_dropped_no_time,
        n_testable_pairs=0,
        n_tests_performed=0,
        n_tests_naive_upper_bound=naive,
        log10_bonferroni_threshold=float("nan"),
        log10_bh_threshold=float("nan"),
        feasibility=None,
        params=params,
    )
    notes: list[str] = []
    if panel.wallets_are_a_watchlist:
        notes.append(
            "the wallet set is a hand-picked watchlist, not a sample of the wallet population; "
            "any validated edge is conditioned on our own selection and cannot be read as a "
            "population statement"
        )
    if n_wallets < min_wallets:
        return replace(
            base,
            reason=(
                f"{n_wallets} wallets is below the floor of {min_wallets}: a co-trading network "
                f"on {n_wallets * (n_wallets - 1) // 2} pair(s) has no community structure to "
                "find, whatever the p-values say"
            ),
            notes=tuple(notes),
        )
    if len(panel.element_time) < 2:
        return replace(base, reason="fewer than two index elements", notes=tuple(notes))

    activity = [len(panel.states[w]) for w in wallets]
    median_activity = sorted(activity)[len(activity) // 2]
    feasibility = feasibility_gate(
        n_wallets=n_wallets,
        n_index_elements=len(panel.element_time),
        tokens_per_wallet=median_activity,
        alpha=alpha,
    )
    base = replace(base, feasibility=feasibility)
    if not feasibility.feasible:
        return replace(
            base,
            reason=(
                "feasibility gate fails: the smallest p a median-activity pair can attain is "
                f"10^{feasibility.log_min_attainable_p / math.log(10.0):.2f}, above the Bonferroni "
                f"threshold 10^{feasibility.log_bonferroni_threshold / math.log(10.0):.2f}. No "
                "amount of data validates a pair at this scope; the scope has to change"
            ),
            notes=tuple(notes),
        )

    tests, family_size, testable = pair_tests(panel)
    if not tests:
        return replace(
            base,
            n_testable_pairs=testable,
            n_tests_performed=family_size,
            reason="no pair co-occurs on any index element inside its own activity overlap",
            notes=tuple(notes),
        )
    log_bonf = bonferroni_log_threshold(alpha=alpha, family_size=family_size)
    log_p = [t.log_p for t in tests]
    fdr_flags, log_bh = bh_fdr_log(log_p, q=q, family_size=family_size)
    bonf_flags = [value <= log_bonf for value in log_p]
    base = replace(
        base,
        n_testable_pairs=testable,
        n_tests_performed=family_size,
        log10_bonferroni_threshold=log_bonf / math.log(10.0),
        log10_bh_threshold=log_bh / math.log(10.0),
    )

    hyper_bonf = network_from(tests, bonf_flags, name="hypergeometric-bonferroni")
    hyper_fdr = network_from(tests, fdr_flags, name="hypergeometric-bh-fdr")

    rng = random.Random(seed)
    null = degree_preserving_null(
        panel, tests, rng=rng, draws=randomisations, swaps_per_draw=swaps_per_draw
    )
    p_floor = 1.0 / (1.0 + randomisations)
    degree_flags = [
        null[(t.left, t.right, t.left_state, t.right_state)].empirical_p <= p_floor for t in tests
    ]
    degree_net = network_from(tests, degree_flags, name="degree-preserving")
    degree_bh_flags, _ = bh_fdr_log(
        [
            math.log(null[(t.left, t.right, t.left_state, t.right_state)].empirical_p)
            for t in tests
        ],
        q=q,
        family_size=family_size,
    )
    degree_bh_net = network_from(tests, degree_bh_flags, name="degree-preserving-bh")

    # Cimini: match on DENSITY, not on p. The degree-preserving null cannot reach the Bonferroni
    # threshold at any feasible number of randomisations, so a p-matched comparison is not merely
    # inferior here, it does not exist.
    best_log_p: dict[tuple[int, int], float] = {}
    degree_scores: dict[tuple[int, int], float] = {}
    for test in tests:
        if test.type_key not in SAME_ACTION:
            continue
        best_log_p[test.key] = min(best_log_p.get(test.key, math.inf), test.log_p)
        draw = null[(test.left, test.right, test.left_state, test.right_state)]
        candidate = draw.log_score(test.observed)
        previous = degree_scores.get(test.key)
        if previous is None or candidate < previous:
            degree_scores[test.key] = candidate
    density = len(hyper_bonf.edges)
    hyper_ranked = sorted(hyper_bonf.edges, key=lambda edge: (best_log_p[edge], edge))[:density]
    degree_ranked = sorted(degree_scores, key=lambda edge: (degree_scores[edge], edge))[:density]
    left_set, right_set = set(hyper_ranked), set(degree_ranked)
    union = left_set | right_set
    matched = MatchedDensity(
        density=density,
        overlap=len(left_set & right_set),
        jaccard=len(left_set & right_set) / len(union) if union else 1.0,
        hyper_only=len(left_set - right_set),
        degree_only=len(right_set - left_set),
        adjusted_rand=adjusted_rand_index(
            infomap_communities({edge: hyper_bonf.edges[edge] for edge in hyper_ranked}),
            infomap_communities({edge: hyper_bonf.edges.get(edge, 1) for edge in degree_ranked}),
        ),
        hyper_edges_at_own_threshold=len(hyper_bonf.edges),
        degree_edges_at_p_floor_uncorrected=len(degree_net.edges),
        degree_edges_at_bh=len(degree_bh_net.edges),
        degree_p_floor=p_floor,
    )

    recovery: list[RecoveryMetrics] = []
    if planted is not None:
        recovery = _recovery_metrics(panel, tests, null, planted=planted, density=max(density, 1))

    holdout_report = _holdout(panel, alpha=alpha) if holdout else None

    # The object we are willing to hand downstream is the intersection, NOT the union and not the
    # hypergeometric network alone: an entity link that exists only under one null model would let
    # one actor straddle a train/test split on the strength of a modelling assumption.
    robust = frozenset(left_set & right_set)
    robust_net = Network(
        name="robust (validated under BOTH nulls at matched density)",
        edges={edge: hyper_bonf.edges[edge] for edge in sorted(robust)},
        opposite_edges={
            edge: weight for edge, weight in hyper_bonf.opposite_edges.items() if edge in robust
        },
        mixed_edges={
            edge: weight for edge, weight in hyper_bonf.mixed_edges.items() if edge in robust
        },
        n_validated_tests=sum(hyper_bonf.edges[edge] for edge in robust),
    )
    links = _entity_links(
        robust_net,
        wallets=wallets,
        tests=tests,
        accepted=bonf_flags,
        robust_edges=robust,
        incident_from=hyper_bonf,
        method="svn_cotrading",
    )

    bonf_summary = _summarise(hyper_bonf)
    fdr_summary = _summarise(hyper_fdr)
    degree_summary = _summarise(degree_net)
    robust_summary = _summarise(robust_net)

    notes.append(
        f"degree-preserving null p-floor is {p_floor:.3g}; the Bonferroni threshold is "
        f"10^{log_bonf / math.log(10.0):.2f}. No feasible number of randomisations closes that "
        "gap, which is why the two nulls are compared at matched density and never at matched p"
    )
    if hyper_bonf.opposite_edges:
        notes.append(
            f"{len(hyper_bonf.opposite_edges)} opposite-action edge(s) validated. Tumminello's "
            "recipe deletes these before clustering; they are excluded from the clustering weight "
            "here but reported, because a validated buy-against-sell pair is the wash-trading "
            "signature signal #4 is looking for"
        )

    verdict, reason = _verdict(
        bonf=bonf_summary, robust=robust_summary, matched=matched, panel=panel
    )
    return replace(
        base,
        verdict=verdict,
        reason=reason,
        bonferroni=bonf_summary,
        fdr=fdr_summary,
        degree_preserving=degree_summary,
        robust=robust_summary,
        matched=matched,
        recovery=tuple(recovery),
        holdout=holdout_report,
        entity_links=links,
        notes=tuple(notes),
    )


def _verdict(
    *, bonf: NetworkSummary, robust: NetworkSummary, matched: MatchedDensity, panel: Panel
) -> tuple[str, str]:
    """The ladder, in the order the evidence has to clear it.

    A null is a result and is reported as one. What is refused is a SUGGESTIVE built on edges
    that exist under one null model and vanish under another, because §4.1's blocking risk says
    that is exactly what heavy-tailed token popularity manufactures.
    """
    if panel.wallets_are_a_watchlist:
        return (
            VERDICT_UNRESOLVABLE,
            "the wallet set is a watchlist chosen by us, so a validated cluster measures our own "
            "selection rule and not coordination in the population",
        )
    if bonf.n_same_action_edges == 0:
        return (
            VERDICT_NULL,
            "no wallet pair co-occurs in the same trading state more often than the "
            "hypergeometric null produces, at the Bonferroni threshold over nine typed tests "
            "per pair",
        )
    if robust.n_same_action_edges == 0:
        return (
            VERDICT_NULL,
            f"{bonf.n_same_action_edges} edge(s) validate under the hypergeometric null and NONE "
            "of them survive a degree-preserving randomisation at matched density. Under a "
            "heavy-tailed index that is the artefact signature, not coordination: the "
            "hypergeometric assumes roughly uniform marginals and memecoin token popularity is "
            "not",
        )
    return (
        VERDICT_SUGGESTIVE,
        f"{bonf.n_same_action_edges} same-action edges validate under Bonferroni; "
        f"{matched.overlap} survive a degree-preserving null at matched density, assembling into "
        f"{robust.n_clusters} map-equation cluster(s) over {robust.n_clustered_wallets} wallets",
    )


def _holdout(panel: Panel, *, alpha: float) -> Holdout | None:
    """Temporal split: validate on the early half of the index, re-test on the late half.

    Temporal, never random (§3 rule 1), and the unit of the split is the index element rather
    than the print, so a wallet pair cannot appear on both sides through the same token. The
    control is the set of pairs that co-occur in the training half but do NOT validate: if
    validated pairs re-confirm at the same rate as those, the validation carried no information.
    """
    times = sorted(panel.element_time.values())
    if len(times) < 4:
        return None
    cut = times[len(times) // 2]
    early = {key for key, moment in panel.element_time.items() if moment < cut}
    late = {key for key, moment in panel.element_time.items() if moment >= cut}
    if not early or not late:
        return None

    def restrict(keys: set[str]) -> Panel:
        states = {
            wallet: {key: state for key, state in items.items() if key in keys}
            for wallet, items in panel.states.items()
        }
        states = {wallet: items for wallet, items in states.items() if items}
        element_time = {key: moment for key, moment in panel.element_time.items() if key in keys}
        spans = {
            wallet: (
                min(element_time[key] for key in items),
                max(element_time[key] for key in items),
            )
            for wallet, items in states.items()
        }
        return Panel(
            states=states,
            element_time=element_time,
            wallet_span=spans,
            source=panel.source,
            n_prints=sum(len(v) for v in states.values()),
        )

    train_panel, test_panel = restrict(early), restrict(late)
    train_tests, train_family, _ = pair_tests(train_panel)
    if not train_tests or train_family == 0:
        return None
    test_index = {w: i for i, w in enumerate(test_panel.wallets)}
    train_names = train_panel.wallets
    log_bonf = bonferroni_log_threshold(alpha=alpha, family_size=train_family)
    train_net = network_from(
        train_tests, [t.log_p <= log_bonf for t in train_tests], name="holdout-train"
    )

    test_tests, test_family, _ = pair_tests(test_panel)
    if not test_tests or test_family == 0:
        return None
    test_bonf = bonferroni_log_threshold(alpha=alpha, family_size=test_family)
    confirmed = {
        (t.left, t.right)
        for t in test_tests
        if t.log_p <= test_bonf and t.type_key in SAME_ACTION
    }
    trained_pairs = {
        (train_names[a], train_names[b]) for a, b in train_net.edges
    }
    candidate_pairs = {
        (train_names[t.left], train_names[t.right])
        for t in train_tests
        if t.type_key in SAME_ACTION and t.observed > 0
    }
    control_pairs = candidate_pairs - trained_pairs

    def eligible(pair: tuple[str, str]) -> bool:
        return pair[0] in test_index and pair[1] in test_index

    def confirms(pair: tuple[str, str]) -> bool:
        if not eligible(pair):
            return False
        a, b = test_index[pair[0]], test_index[pair[1]]
        return (min(a, b), max(a, b)) in confirmed

    trained_eligible = [pair for pair in trained_pairs if eligible(pair)]
    control_eligible = [pair for pair in control_pairs if eligible(pair)]
    reconfirmed = sum(1 for pair in trained_eligible if confirms(pair))
    control_hits = sum(1 for pair in control_eligible if confirms(pair))
    return Holdout(
        n_train_elements=len(early),
        n_test_elements=len(late),
        n_train_edges=len(trained_pairs),
        n_train_edges_eligible=len(trained_eligible),
        n_reconfirmed=reconfirmed,
        reconfirmation_rate=reconfirmed / len(trained_eligible) if trained_eligible else 0.0,
        n_control_pairs=len(control_pairs),
        n_control_pairs_eligible=len(control_eligible),
        control_rate=control_hits / len(control_eligible) if control_eligible else 0.0,
    )


def _recovery_metrics(
    panel: Panel,
    tests: Sequence[PairTest],
    null: Mapping[tuple[int, int, TradeState, TradeState], NullDraw],
    *,
    planted: Mapping[str, int],
    density: int,
) -> list[RecoveryMetrics]:
    """Baselines BEFORE models (§3 rule 4). The popularity baseline runs first and is reported."""
    wallets = panel.wallets
    labels = [planted.get(wallet, -1 - i) for i, wallet in enumerate(wallets)]
    n_wallets = len(wallets)
    positives = sum(
        1
        for a in range(n_wallets)
        for b in range(a + 1, n_wallets)
        if labels[a] >= 0 and labels[a] == labels[b]
    )
    all_pairs = n_wallets * (n_wallets - 1) // 2
    base_rate = positives / all_pairs if all_pairs else 0.0

    raw: dict[tuple[int, int], int] = defaultdict(int)
    hyper: dict[tuple[int, int], float] = {}
    degree: dict[tuple[int, int], float] = {}
    for test in tests:
        if test.type_key not in SAME_ACTION:
            continue
        raw[test.key] += test.observed
        hyper[test.key] = min(hyper.get(test.key, math.inf), test.log_p)
        draw = null[(test.left, test.right, test.left_state, test.right_state)]
        candidate = draw.log_score(test.observed)
        if test.key not in degree or candidate < degree[test.key]:
            degree[test.key] = candidate

    def labelled(scores: Mapping[tuple[int, int], float]) -> list[tuple[float, bool]]:
        scored = [
            (value, labels[edge[0]] >= 0 and labels[edge[0]] == labels[edge[1]])
            for edge, value in scores.items()
        ]
        scored.extend((-math.inf, False) for _ in range(all_pairs - len(scores)))
        return scored

    out = [
        RecoveryMetrics(
            method="popularity-baseline (raw same-action co-occurrence count)",
            average_precision=average_precision(
                labelled({k: float(v) for k, v in raw.items()}), n_positive_total=positives
            ),
            precision_at_k=precision_at_k(
                labelled({k: float(v) for k, v in raw.items()}), k=density
            ),
            k=density,
            base_rate=base_rate,
        ),
        RecoveryMetrics(
            method="svn-hypergeometric (-log p)",
            average_precision=average_precision(
                labelled({k: -v for k, v in hyper.items()}), n_positive_total=positives
            ),
            precision_at_k=precision_at_k(labelled({k: -v for k, v in hyper.items()}), k=density),
            k=density,
            base_rate=base_rate,
        ),
        RecoveryMetrics(
            method="svn-degree-preserving (-log score)",
            average_precision=average_precision(
                labelled({k: -v for k, v in degree.items()}), n_positive_total=positives
            ),
            precision_at_k=precision_at_k(labelled({k: -v for k, v in degree.items()}), k=density),
            k=density,
            base_rate=base_rate,
        ),
    ]
    return out


# ---------------------------------------------------------------------------------------------
# Simulation -- realistic worlds with KNOWN answers
# ---------------------------------------------------------------------------------------------


def _address(rng: random.Random) -> str:
    return str(Pubkey(bytes(rng.randbytes(32))))


@dataclass(frozen=True, slots=True)
class World:
    """A simulated panel plus the ground truth it was generated from."""

    panel: Panel
    planted: Mapping[str, int]
    popularity_exponent: float


def simulate(
    *,
    seed: int,
    n_wallets: int = 240,
    n_tokens: int = 400,
    n_clusters: int = 6,
    cluster_size: int = 8,
    cluster_tokens: int = 9,
    cluster_participation: float = 0.85,
    activity_low: int = 4,
    activity_high: int = 14,
    popularity_exponent: float = 1.1,
    lifetime_fraction: float = 0.35,
    horizon_hours: float = 24.0 * 14,
    sell_probability: float = 0.25,
    round_trip_probability: float = 0.20,
) -> World:
    """A launch-and-decay memecoin world with optional planted co-trading rings.

    Three properties are deliberate, and each one is a way this method can fail on real data:

    * **Token popularity is Zipf-heavy** (``popularity_exponent``). This is §4.1's blocking risk
      made concrete: the hypergeometric null assumes roughly uniform marginals over the index,
      and under a heavy tail "both wallets bought the token everybody bought" is not evidence.
      Set the exponent to 0 for the uniform world the null actually assumes.
    * **Wallets are short-lived and staggered** (``lifetime_fraction``). Pair-specific ``T`` is
      only load-bearing when activity periods differ, which is exactly our population.
    * **Planted rings buy together** and sell separately, per §1.1: accumulation is multi-wallet,
      the dump is frequently single-wallet.
    """
    rng = random.Random(seed)
    tokens = [_address(rng) for _ in range(n_tokens)]
    token_time = {
        token: rng.uniform(0.0, horizon_hours * 3600.0) for token in tokens
    }
    weights = [1.0 / ((i + 1) ** popularity_exponent) for i in range(n_tokens)]
    order = list(range(n_tokens))
    rng.shuffle(order)
    popularity = [0.0] * n_tokens
    for rank, position in enumerate(order):
        popularity[position] = weights[rank]
    popularity_of = {token: popularity[i] for i, token in enumerate(tokens)}

    wallets = [_address(rng) for _ in range(n_wallets)]
    span = horizon_hours * 3600.0
    planted: dict[str, int] = {}
    ring_tokens: dict[int, list[str]] = {}
    ring_window: dict[int, tuple[float, float]] = {}
    cursor = 0
    for ring in range(n_clusters):
        members = wallets[cursor : cursor + cluster_size]
        cursor += cluster_size
        if len(members) < 2:
            break
        for wallet in members:
            planted[wallet] = ring
        # A ring is funded and operates together, so its members share a window and its target
        # tokens exist inside that window. A ring whose tokens launched before half its members
        # were funded is not a ring, and pair-specific T would correctly refuse to see it.
        start = rng.uniform(0.0, span * (1.0 - lifetime_fraction))
        ring_window[ring] = (start, start + span * lifetime_fraction)
        inside = [t for t in tokens if start <= token_time[t] <= start + span * lifetime_fraction]
        ring_tokens[ring] = rng.sample(inside, min(cluster_tokens, len(inside)))

    prints: list[Print] = []
    for wallet in wallets:
        ring_of = planted.get(wallet)
        if ring_of is not None:
            start, end = ring_window[ring_of]
        else:
            start = rng.uniform(0.0, span * (1.0 - lifetime_fraction))
            end = start + span * lifetime_fraction
        pool = [token for token in tokens if start <= token_time[token] <= end]
        if len(pool) < 2:
            pool = tokens
        pool_weights = [popularity_of[token] for token in pool]
        target = rng.randint(activity_low, activity_high)
        chosen: set[str] = set()
        ring = ring_of
        if ring is not None:
            for token in ring_tokens[ring]:
                if rng.random() < cluster_participation:
                    chosen.add(token)
        guard = 0
        while len(chosen) < target and guard < target * 40:
            guard += 1
            chosen.add(rng.choices(pool, weights=pool_weights, k=1)[0])
        for token in sorted(chosen):
            moment = max(token_time[token], start) + rng.uniform(0.0, 600.0)
            if ring is not None and token in ring_tokens[ring]:
                prints.append(Print(wallet=wallet, element=token, is_buy=True, at=moment))
                continue
            roll = rng.random()
            if roll < round_trip_probability:
                prints.append(Print(wallet=wallet, element=token, is_buy=True, at=moment))
                prints.append(Print(wallet=wallet, element=token, is_buy=False, at=moment + 60.0))
            elif roll < round_trip_probability + sell_probability:
                prints.append(Print(wallet=wallet, element=token, is_buy=False, at=moment))
            else:
                prints.append(Print(wallet=wallet, element=token, is_buy=True, at=moment))
    panel = panel_from_prints(prints, source=f"simulated:seed={seed}")
    return World(panel=panel, planted=planted, popularity_exponent=popularity_exponent)


# ---------------------------------------------------------------------------------------------
# Budget arithmetic -- reported, never guessed
# ---------------------------------------------------------------------------------------------


def credit_estimate(*, n_tokens: int, trades_per_token: int) -> dict[str, Any]:
    """Helius cost of collecting a real panel. 10 credits per 100 transactions, parsed raw."""
    pages = math.ceil(trades_per_token / 100)
    credits = n_tokens * pages * CREDITS_PER_TRANSACTION_PAGE
    return {
        "n_tokens": n_tokens,
        "trades_per_token": trades_per_token,
        "pages_per_token": pages,
        "credits_per_page": CREDITS_PER_TRANSACTION_PAGE,
        "credits": credits,
        "monthly_plan_credits": 10_000_000,
        "share_of_monthly_plan": credits / 10_000_000,
    }


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mode", choices=("simulated", "store"), default="simulated")
    parser.add_argument("--store", type=Path, default=None, help="COPY of intelligence.sqlite3")
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--randomisations", type=int, default=RANDOMISATIONS)
    parser.add_argument("--wallets", type=int, default=240)
    parser.add_argument("--tokens", type=int, default=400)
    parser.add_argument("--clusters", type=int, default=6)
    parser.add_argument("--cluster-size", type=int, default=8)
    parser.add_argument(
        "--popularity-exponent",
        type=float,
        default=1.1,
        help="0 = the uniform index the hypergeometric null assumes; >0 = a heavy tail",
    )
    parser.add_argument("--out", type=Path, default=None, help="JSONL output path (never CSV)")
    args = parser.parse_args(argv)

    if args.mode == "store":
        if args.store is None:
            raise SystemExit("--mode store needs --store")
        panel = prints_from_store(args.store)
        result = run_study(panel, seed=args.seed, randomisations=args.randomisations)
    else:
        world = simulate(
            seed=args.seed,
            n_wallets=args.wallets,
            n_tokens=args.tokens,
            n_clusters=args.clusters,
            cluster_size=args.cluster_size,
            popularity_exponent=args.popularity_exponent,
        )
        result = run_study(
            world.panel,
            seed=args.seed,
            randomisations=args.randomisations,
            planted=world.planted,
        )
    payload = result.to_json()
    payload["credit_estimate_for_a_real_panel"] = credit_estimate(
        n_tokens=args.tokens, trades_per_token=5000
    )
    line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
