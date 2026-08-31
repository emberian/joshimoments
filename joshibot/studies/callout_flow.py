"""Signal #3 — does a mint-resolved callout move that mint's buy-arrival intensity?

Question (pre-registered, §4 item 3 of PROGRAM.md): given a social callout that resolves to a
specific mint at time ``t0``, is the mint's buy-arrival intensity over ``[t0, t0 + 30min)``
different from an **hour-matched** baseline for the same mint?

Everything here is deterministic given ``--seed`` and reads a *copy* of the intelligence store.
No network, no signing, no writes to ``intelligence_state/``.

Five decisions are load-bearing, and each one is a bug some study actually shipped.

**The two clocks are INVERTED between kinds in this store, and reading them wrong is the whole
study.** For a social observation (``x_mint_mention``, ``claudekol_claim``) ``observed_at`` is when
the post appeared in the world and ``emitted_at`` is when our collector ingested it. For
``wallet_transaction`` it is the other way round: ``observed_at`` is the Helius fetch timestamp and
``emitted_at`` is the **block time**. Verified: regressing ``slot`` on ``emitted_at`` over the
1,337 stamped transactions yields 0.4213 s/slot, which is Solana's slot time; regressing on
``observed_at`` yields nonsense, because the backfiller walks history in reverse and its latest
fetch carries the *oldest* slot. Using ``observed_at`` as trade time silently reverses the arrow
of causation. ``trade_chain_time`` and ``callout_origin_time`` exist so that this is never
re-derived at a call site.

**Non-overlap between placebo windows uses ``max(pre, post)``, never just ``post``.** A prior study
separated placebos by the post window alone, so with its own defaults accepted placebos sat 1h
apart while each consumed a 24h pre-window — ~96% overlap, advertised as independent. Separation
here is ``max(pre_window, post_window)`` against every real callout *and* every already-accepted
placebo on the same mint. :func:`sample_placebos` is the only production source of placebo times;
``run_study`` accepts an alternative sampler solely so the falsification suite can substitute a
broken one and prove the null test can fail.

**Hour matching is mandatory.** Diurnal amplitude in this market is 3.6x-5.4x, which is larger than
any callout effect anyone has claimed. An unmatched baseline manufactures an effect out of
time-of-day alone. A placebo must fall in the same UTC hour-of-day band as the callout it matches.

**Pooling is partial, never fully pooled and never per-token.** Fully pooled is dominated by the
highest-volume mint; unpooled at this sample size is prior-dominated mush. All three are computed
and reported side by side so the reader can see the contrast rather than take it on faith.

**``p_floor = 1/(1 + n_placebo_replicates)`` is reported with every p.** With few independent
replicates the achievable resolution is coarser than any p worth quoting, and the honest output in
that regime is "the instrument cannot resolve this", not a number.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from shitcoims_tape.schema import Callout, Side, Trade

# ---------------------------------------------------------------------------------------------
# Study parameters. Declared here so the hypothesis family is countable rather than guessed.
# ---------------------------------------------------------------------------------------------

#: The primary window, in minutes. The question names 0-30min; 10 and 60 are sensitivity only.
PRIMARY_WINDOW_MINUTES: int = 30
WINDOW_MINUTES: tuple[int, ...] = (10, 30, 60)

#: Outcomes. ``new_wallets`` is structurally degenerate when the responder set is tiny -- see
#: ``StudyResult.eligible_wallets``, which is exactly the number that decides whether it means
#: anything at all.
OUTCOMES: tuple[str, ...] = ("buy_arrivals", "new_wallets")

#: The effective number of hypotheses = |OUTCOMES| x |WINDOW_MINUTES|. BH-FDR corrects over it.
FDR_Q: float = 0.10

#: Kinds in the intelligence store whose payload carries a resolved ``mint``. A cashtag is a
#: *claim* and a mint/URL is an *identifier*; the tape schema keeps ``resolved_from`` for exactly
#: this reason and pooling the two corrupts the study, so cashtag-only kinds are excluded.
CALLOUT_KINDS: tuple[str, ...] = ("x_mint_mention", "claudekol_claim")

#: Wallets that CONSUME the callout stream as a policy input. Our own sentinel subscribes to the
#: intelligence store, so counting its buys as a "response" measures our own reaction function in
#: a closed loop, not market propagation. Excluded from the responder set by default; the study
#: reports the endogenous arm separately and never draws inference from it.
POLICY_WALLETS: frozenset[str] = frozenset({"Sh1WNJ8g68rXJGyDjVPcfxWN1WbMrLsgdXmSb6cccuE"})


class StudyError(RuntimeError):
    """The study cannot proceed on this input. Always fail closed rather than publish a number."""


# ---------------------------------------------------------------------------------------------
# Time handling
# ---------------------------------------------------------------------------------------------


def _parse_utc(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise StudyError(f"timestamp {text!r} carries no timezone; naive stamps are refused")
    return parsed.astimezone(UTC)


def trade_chain_time(observation: Mapping[str, Any]) -> datetime | None:
    """Chain time of a ``wallet_transaction`` row. This is ``emitted_at``, NOT ``observed_at``.

    Returns ``None`` when the RPC gave no block time; such rows cannot be ordered against a
    callout and are dropped rather than back-filled from the fetch clock.
    """
    emitted = observation.get("emitted_at")
    if not emitted:
        return None
    return _parse_utc(str(emitted))


def callout_origin_time(observation: Mapping[str, Any]) -> datetime:
    """World time a social post appeared. This is ``observed_at``, NOT ``emitted_at``.

    There is no chain time for a tweet, so the post time *is* the origin; our ingest stamp
    (``emitted_at``) is delayed entry and is reported separately as observer lag.
    """
    return _parse_utc(str(observation["observed_at"]))


# ---------------------------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CalloutEvent:
    """A callout, at its origin time, with the ingest lag that bounds real-time tradeability."""

    at: datetime
    ingest_lag_seconds: float
    body: Callout
    kind: str

    @property
    def mint(self) -> str:
        return self.body.mint


@dataclass(frozen=True, slots=True)
class TradeEvent:
    """One fill leg at chain time. ``body`` is the tape's ``Trade``, so amounts stay integral."""

    at: datetime
    body: Trade

    @property
    def mint(self) -> str:
        return self.body.mint

    @property
    def wallet(self) -> str:
        return self.body.wallet

    @property
    def side(self) -> Side:
        return self.body.side


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_callouts(
    connection: sqlite3.Connection, *, kinds: Sequence[str] = CALLOUT_KINDS
) -> tuple[list[CalloutEvent], list[str]]:
    """Read mint-resolved callouts. Returns ``(events, rejected)``, sorted by origin time.

    The tape schema stores only a hash of the post text, so nothing scraped is carried forward.

    Rows that violate the tape contract are DROPPED AND COUNTED, never repaired and never
    silently accepted. Aborting the whole study because one upstream scraper row is malformed
    would be wrong; hiding the reject rate would be worse, because it is a measurement of the
    collector. The live store contains exactly one such row -- a mint address that arrived
    lowercased, which base58 cannot represent and no amount of care can recover.
    """
    placeholders = ",".join("?" for _ in kinds)
    rows = connection.execute(
        f"SELECT kind, observed_at, emitted_at, payload_json, source_id FROM observations "
        f"WHERE kind IN ({placeholders})",
        tuple(kinds),
    ).fetchall()
    events: dict[tuple[str, str, str], CalloutEvent] = {}
    rejected: list[str] = []
    for kind, observed_at, emitted_at, payload_json, source_id in rows:
        payload = json.loads(payload_json)
        mint = payload.get("mint")
        if not mint:
            continue
        origin = callout_origin_time({"observed_at": observed_at})
        lag = (_parse_utc(str(emitted_at)) - origin).total_seconds() if emitted_at else float("nan")
        author = str(payload.get("author_username") or source_id)
        summary = str(payload.get("summary") or "")
        try:
            body = Callout(
                mint=str(mint),
                platform=kind,
                author=author,
                # A mint pasted in the post is an identifier; anything else is a claim.
                resolved_from="mint_in_text" if mint in summary else "adapter_resolved",
                text_sha256=_sha256(summary),
                author_followers=int(payload.get("author_followers") or 0),
                engagement=int(payload.get("view_count") or 0),
            )
        except Exception as exc:
            rejected.append(f"{kind} {observed_at} mint={mint!r}: {exc}")
            continue
        # Same mint, same author, same instant is one event however many rows carry it.
        events[(body.mint, author, origin.isoformat())] = CalloutEvent(
            at=origin, ingest_lag_seconds=lag, body=body, kind=kind
        )
    return sorted(events.values(), key=lambda event: (event.at, event.mint)), rejected


def load_trades(connection: sqlite3.Connection) -> list[TradeEvent]:
    """Read every observable fill leg at chain time, deduplicated by (signature, mint)."""
    rows = connection.execute(
        "SELECT subject_id, emitted_at, payload_json FROM observations WHERE kind='wallet_transaction'"
    ).fetchall()
    seen: set[tuple[str, str]] = set()
    trades: list[TradeEvent] = []
    for wallet, emitted_at, payload_json in rows:
        payload = json.loads(payload_json)
        if not payload.get("succeeded", True):
            continue
        at = trade_chain_time({"emitted_at": emitted_at})
        if at is None:
            continue
        signature = str(payload.get("signature") or "")
        for delta in payload.get("token_deltas", []):
            raw = int(delta["raw_delta"])
            if raw == 0:
                continue
            key = (signature, str(delta["mint"]))
            if key in seen:
                continue
            seen.add(key)
            trades.append(
                TradeEvent(
                    at=at,
                    body=Trade(
                        mint=str(delta["mint"]),
                        wallet=str(wallet),
                        side=Side.BUY if raw > 0 else Side.SELL,
                        # The store records the wallet's own SOL delta per transaction, not per
                        # leg; attributing it to one leg of a multi-token transaction would be a
                        # fabrication, so arrival counting uses the token delta alone.
                        sol_delta_lamports=0,
                        token_delta_raw=raw,
                    ),
                )
            )
    return sorted(trades, key=lambda event: (event.at, event.mint, event.wallet))


# ---------------------------------------------------------------------------------------------
# Placebo construction
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Coverage:
    """The interval over which the tape could have recorded a fill by the responder set.

    A window that runs past ``end`` is not "zero arrivals", it is *unobserved*, and counting it as
    zero is how a truncated rate gets reported as a full-horizon one.
    """

    start: datetime
    end: datetime

    def contains_window(self, at: datetime, *, pre: timedelta, post: timedelta) -> bool:
        return self.start <= at - pre and at + post <= self.end


def responder_coverage(trades: Sequence[TradeEvent], wallets: Iterable[str]) -> Coverage | None:
    """Coverage of the eligible responder set: first to last observed fill by those wallets."""
    eligible = set(wallets)
    stamps = [event.at for event in trades if event.wallet in eligible]
    if not stamps:
        return None
    return Coverage(start=min(stamps), end=max(stamps))


def sample_placebos(
    *,
    callouts: Sequence[datetime],
    coverage: Coverage,
    pre: timedelta,
    post: timedelta,
    replicates: int,
    rng: random.Random,
    band_grid_minutes: int = 30,
) -> list[list[datetime]]:
    """Hour-matched, properly-separated placebo times: one matched time per callout, per replicate.

    Separation is ``max(pre, post)`` -- against every real callout on the mint AND every placebo
    already accepted in the same replicate. Separating on the post window alone is the documented
    bug this function exists to prevent: it lets a 1h-spaced placebo consume a 24h pre-window and
    call the result independent.

    Returns a list of replicates; a replicate may be SHORT (or empty) when the coverage window
    admits no legal match, and the caller must treat the realised count as the resolution of the
    instrument rather than assume ``replicates``.
    """
    if replicates < 1:
        raise StudyError("replicates must be >= 1")
    separation = max(pre, post)
    horizon_days = max(1, math.ceil((coverage.end - coverage.start).total_seconds() / 86400.0) + 1)
    day_zero = coverage.start.replace(hour=0, minute=0, second=0, microsecond=0)

    def candidates_for(callout_at: datetime) -> list[datetime]:
        found: list[datetime] = []
        for day in range(-1, horizon_days + 1):
            base = day_zero + timedelta(days=day, hours=callout_at.hour)
            for offset in range(0, 60, band_grid_minutes):
                moment = base + timedelta(minutes=offset)
                if not coverage.contains_window(moment, pre=pre, post=post):
                    continue
                # Never inside any real callout's contaminated neighbourhood.
                if any(
                    abs((moment - real).total_seconds()) < separation.total_seconds()
                    for real in callouts
                ):
                    continue
                found.append(moment)
        return found

    pools: dict[datetime, list[datetime]] = {at: candidates_for(at) for at in dict.fromkeys(callouts)}
    out: list[list[datetime]] = []
    for _ in range(replicates):
        accepted: list[datetime] = []
        for at in callouts:
            pool = [
                moment
                for moment in pools[at]
                if all(
                    abs((moment - taken).total_seconds()) >= separation.total_seconds()
                    for taken in accepted
                )
            ]
            if not pool:
                continue
            accepted.append(pool[rng.randrange(len(pool))])
        out.append(accepted)
    return out


class PlaceboSampler(Protocol):
    """The one seam in the pipeline, so a broken sampler can be substituted to falsify the tests."""

    def __call__(
        self,
        *,
        callouts: Sequence[datetime],
        coverage: Coverage,
        pre: timedelta,
        post: timedelta,
        replicates: int,
        rng: random.Random,
    ) -> list[list[datetime]]: ...


# ---------------------------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------------------------


def count_window(
    trades_for_mint: Sequence[TradeEvent],
    *,
    at: datetime,
    post: timedelta,
    eligible: frozenset[str],
    outcome: str,
) -> int:
    """Arrivals in ``[at, at + post)``. ``new_wallets`` counts first-ever buyers of this mint."""
    end = at + post
    if outcome == "buy_arrivals":
        return sum(
            1
            for event in trades_for_mint
            if at <= event.at < end and event.side is Side.BUY and event.wallet in eligible
        )
    if outcome == "new_wallets":
        prior = {
            event.wallet
            for event in trades_for_mint
            if event.at < at and event.wallet in eligible
        }
        fresh = {
            event.wallet
            for event in trades_for_mint
            if at <= event.at < end and event.side is Side.BUY and event.wallet in eligible
        }
        return len(fresh - prior)
    raise StudyError(f"unknown outcome {outcome!r}")


# ---------------------------------------------------------------------------------------------
# Estimation
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MintCounts:
    """Per-mint sufficient statistics. ``exposure`` is window-seconds, so rates are comparable."""

    mint: str
    treated_events: int
    treated_count: int
    treated_exposure: float
    placebo_windows: int
    placebo_count: int
    placebo_exposure: float


@dataclass(frozen=True, slots=True)
class PooledEstimate:
    """Log rate ratio under the three pooling regimes PROGRAM.md 1.5 says to compare."""

    fully_pooled: float
    unpooled_mean: float
    unpooled_sd: float
    partial_mu: float
    partial_se: float
    partial_tau: float
    n_mints: int


_HALF = 0.5  # Anscombe-style continuity correction; keeps log rates finite at zero counts.


def _log_rate(count: int, exposure: float) -> float:
    if exposure <= 0:
        raise StudyError("exposure must be positive")
    return math.log((count + _HALF) / exposure)


def per_mint_effects(counts: Sequence[MintCounts]) -> list[tuple[str, float, float]]:
    """(mint, theta_hat, variance) where theta = log(rate_treated / rate_placebo)."""
    out: list[tuple[str, float, float]] = []
    for row in counts:
        if row.treated_exposure <= 0 or row.placebo_exposure <= 0:
            continue
        theta = _log_rate(row.treated_count, row.treated_exposure) - _log_rate(
            row.placebo_count, row.placebo_exposure
        )
        variance = 1.0 / (row.treated_count + _HALF) + 1.0 / (row.placebo_count + _HALF)
        out.append((row.mint, theta, variance))
    return out


def partial_pool(
    effects: Sequence[tuple[str, float, float]], *, iterations: int = 500
) -> tuple[float, float, float]:
    """Empirical-Bayes Normal-Normal partial pooling by EM. Returns ``(mu, se, tau)``.

    EM rather than DerSimonian-Laird because EM cannot return a negative variance component and
    is monotone, so the answer does not depend on where the iteration is truncated.
    """
    if not effects:
        return (0.0, float("inf"), 0.0)
    thetas = [theta for _, theta, _ in effects]
    variances = [max(variance, 1e-12) for _, _, variance in effects]
    n = len(thetas)
    mu = sum(thetas) / n
    tau2 = max(sum((theta - mu) ** 2 for theta in thetas) / n - sum(variances) / n, 1e-9)
    for _ in range(iterations):
        shrunk = [
            (tau2 * theta + variance * mu) / (tau2 + variance)
            for theta, variance in zip(thetas, variances, strict=True)
        ]
        post_var = [tau2 * variance / (tau2 + variance) for variance in variances]
        new_mu = sum(shrunk) / n
        new_tau2 = max(
            sum((value - new_mu) ** 2 + pv for value, pv in zip(shrunk, post_var, strict=True)) / n,
            1e-12,
        )
        if abs(new_mu - mu) < 1e-12 and abs(new_tau2 - tau2) < 1e-14:
            mu, tau2 = new_mu, new_tau2
            break
        mu, tau2 = new_mu, new_tau2
    precision = sum(1.0 / (tau2 + variance) for variance in variances)
    return (mu, math.sqrt(1.0 / precision) if precision > 0 else float("inf"), math.sqrt(tau2))


def pool(counts: Sequence[MintCounts]) -> PooledEstimate:
    effects = per_mint_effects(counts)
    treated_count = sum(row.treated_count for row in counts)
    treated_exposure = sum(row.treated_exposure for row in counts)
    placebo_count = sum(row.placebo_count for row in counts)
    placebo_exposure = sum(row.placebo_exposure for row in counts)
    fully = (
        _log_rate(treated_count, treated_exposure) - _log_rate(placebo_count, placebo_exposure)
        if treated_exposure > 0 and placebo_exposure > 0
        else 0.0
    )
    thetas = [theta for _, theta, _ in effects]
    mean = sum(thetas) / len(thetas) if thetas else 0.0
    sd = (
        math.sqrt(sum((theta - mean) ** 2 for theta in thetas) / (len(thetas) - 1))
        if len(thetas) > 1
        else float("nan")
    )
    mu, se, tau = partial_pool(effects)
    return PooledEstimate(
        fully_pooled=fully,
        unpooled_mean=mean,
        unpooled_sd=sd,
        partial_mu=mu,
        partial_se=se,
        partial_tau=tau,
        n_mints=len(effects),
    )


# ---------------------------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------------------------


def placebo_p_value(observed: float, null_draws: Sequence[float]) -> tuple[float, float]:
    """Two-sided placebo p and its floor. ``p_floor = 1/(1 + len(null_draws))``, always reported.

    The floor is the resolution of the instrument. A p equal to its floor means "nothing in the
    null was as extreme", which at small replicate counts is not evidence of anything.
    """
    n = len(null_draws)
    p_floor = 1.0 / (1.0 + n)
    if n == 0:
        return (1.0, 1.0)
    beat = sum(1 for draw in null_draws if abs(draw) >= abs(observed))
    return ((1.0 + beat) / (1.0 + n), p_floor)


def bh_fdr(p_values: Sequence[float], *, q: float = FDR_Q) -> list[bool]:
    """Benjamini-Hochberg. Returns per-hypothesis rejection flags in the input order."""
    n = len(p_values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda index: p_values[index])
    threshold_rank = -1
    for rank, index in enumerate(order, start=1):
        if p_values[index] <= q * rank / n:
            threshold_rank = rank
    flags = [False] * n
    for rank, index in enumerate(order, start=1):
        if rank <= threshold_rank:
            flags[index] = True
    return flags


# ---------------------------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HypothesisResult:
    outcome: str
    window_minutes: int
    estimate: PooledEstimate
    p_value: float
    p_floor: float
    n_null_draws: int
    n_treated_events: int
    n_treated_arrivals: int
    n_placebo_windows: int
    n_placebo_arrivals: int
    #: Spread (max - min) of the placebo null draws. A null with no spread cannot produce a
    #: measured p: every draw is the same number and the p-value is an artefact of the tie rule.
    null_spread: float
    fdr_rejected: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "window_minutes": self.window_minutes,
            "n_treated_events": self.n_treated_events,
            "n_treated_arrivals": self.n_treated_arrivals,
            "n_placebo_windows": self.n_placebo_windows,
            "n_placebo_arrivals": self.n_placebo_arrivals,
            "n_mints": self.estimate.n_mints,
            "log_rate_ratio_fully_pooled": self.estimate.fully_pooled,
            "log_rate_ratio_unpooled_mean": self.estimate.unpooled_mean,
            "log_rate_ratio_unpooled_sd": self.estimate.unpooled_sd,
            "log_rate_ratio_partial_mu": self.estimate.partial_mu,
            "log_rate_ratio_partial_se": self.estimate.partial_se,
            "between_mint_tau": self.estimate.partial_tau,
            "p_value": self.p_value,
            "p_floor": self.p_floor,
            "n_null_draws": self.n_null_draws,
            "null_spread": self.null_spread,
            "fdr_rejected": self.fdr_rejected,
        }


@dataclass(frozen=True, slots=True)
class StudyResult:
    verdict: str
    reason: str
    eligible_wallets: tuple[str, ...]
    n_callouts: int
    n_callout_mints: int
    n_rejected_callout_rows: int
    n_trade_legs: int
    n_trade_mints: int
    coverage_start: str | None
    coverage_end: str | None
    n_analysable_events: int
    n_analysable_mints: int
    median_ingest_lag_seconds: float
    hypotheses: tuple[HypothesisResult, ...] = ()
    notes: tuple[str, ...] = ()
    params: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "eligible_wallets": list(self.eligible_wallets),
            "n_eligible_wallets": len(self.eligible_wallets),
            "n_callouts": self.n_callouts,
            "n_callout_mints": self.n_callout_mints,
            "n_rejected_callout_rows": self.n_rejected_callout_rows,
            "n_trade_legs": self.n_trade_legs,
            "n_trade_mints": self.n_trade_mints,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "n_analysable_events": self.n_analysable_events,
            "n_analysable_mints": self.n_analysable_mints,
            "median_ingest_lag_seconds": self.median_ingest_lag_seconds,
            "hypotheses": [hypothesis.to_json() for hypothesis in self.hypotheses],
            "notes": list(self.notes),
            "params": dict(self.params),
        }


def _null_is_degenerate(hypothesis: HypothesisResult) -> bool:
    """True when every placebo draw landed on the same value, so p carries no information."""
    return hypothesis.n_null_draws > 0 and hypothesis.null_spread < 1e-9


VERDICT_NULL = "NULL"
VERDICT_UNRESOLVABLE = "UNRESOLVABLE-AT-THIS-N"
VERDICT_SUGGESTIVE = "SUGGESTIVE"


def run_study(
    callouts: Sequence[CalloutEvent],
    trades: Sequence[TradeEvent],
    *,
    seed: int,
    replicates: int = 200,
    pre_minutes: int = 30,
    windows: Sequence[int] = WINDOW_MINUTES,
    outcomes: Sequence[str] = OUTCOMES,
    exclude_wallets: frozenset[str] = POLICY_WALLETS,
    min_analysable_events: int = 10,
    placebo_sampler: PlaceboSampler = sample_placebos,
    rejected_callout_rows: Sequence[str] = (),
) -> StudyResult:
    """Run the whole family and return one verdict. Deterministic given ``seed``.

    ``placebo_sampler`` is injectable for ONE reason: the falsification suite substitutes a
    deliberately broken sampler (unmatched baseline) to prove the null test can fail. Production
    callers must not pass it.
    """
    all_wallets = {event.wallet for event in trades}
    eligible = frozenset(all_wallets - exclude_wallets)
    lags = sorted(event.ingest_lag_seconds for event in callouts if not math.isnan(event.ingest_lag_seconds))
    median_lag = lags[len(lags) // 2] if lags else float("nan")
    notes: list[str] = [f"rejected callout row (tape contract): {row}" for row in rejected_callout_rows]
    params = {
        "seed": seed,
        "replicates_requested": replicates,
        "pre_minutes": pre_minutes,
        "windows": list(windows),
        "outcomes": list(outcomes),
        "excluded_wallets": sorted(exclude_wallets),
        "separation_rule": "max(pre_window, post_window)",
        "matching": "same UTC hour-of-day band",
    }

    trades_by_mint: dict[str, list[TradeEvent]] = defaultdict(list)
    for event in trades:
        trades_by_mint[event.mint].append(event)

    coverage = responder_coverage(trades, eligible)
    base = StudyResult(
        verdict=VERDICT_UNRESOLVABLE,
        reason="",
        eligible_wallets=tuple(sorted(eligible)),
        n_callouts=len(callouts),
        n_callout_mints=len({event.mint for event in callouts}),
        n_rejected_callout_rows=len(rejected_callout_rows),
        n_trade_legs=len(trades),
        n_trade_mints=len(trades_by_mint),
        coverage_start=coverage.start.isoformat() if coverage else None,
        coverage_end=coverage.end.isoformat() if coverage else None,
        n_analysable_events=0,
        n_analysable_mints=0,
        median_ingest_lag_seconds=median_lag,
        params=params,
    )
    if coverage is None:
        return replace(base, reason="no observable fills by any eligible responder wallet")

    # An event is analysable only if the responder set could have been observed over its whole
    # window. Outside coverage a zero is UNOBSERVED, not "no response", and the difference is the
    # displacement-censoring bug that turned a published 24h graduation rate into a 6-minute one.
    longest = timedelta(minutes=max(windows))
    pre = timedelta(minutes=pre_minutes)
    analysable = [
        event
        for event in callouts
        if coverage.contains_window(event.at, pre=pre, post=longest)
    ]
    analysable_mints = {event.mint for event in analysable}
    base = replace(
        base, n_analysable_events=len(analysable), n_analysable_mints=len(analysable_mints)
    )
    if len(eligible) < 2:
        notes.append(
            f"responder set has {len(eligible)} wallet(s); 'new_wallets' cannot exceed "
            f"{len(eligible)} across the entire study and is structurally uninformative"
        )
    if len(analysable) < min_analysable_events:
        return replace(
            base,
            reason=(
                f"only {len(analysable)} of {len(callouts)} callouts fall inside the responder "
                f"coverage window [{coverage.start.isoformat()}, {coverage.end.isoformat()}]; "
                f"minimum for estimation is {min_analysable_events}"
            ),
            notes=tuple(notes),
        )

    by_mint: dict[str, list[datetime]] = defaultdict(list)
    for event in analysable:
        by_mint[event.mint].append(event.at)

    rng = random.Random(seed)
    placebo_plan: dict[str, list[list[datetime]]] = {}
    for mint, times in sorted(by_mint.items()):
        placebo_plan[mint] = placebo_sampler(
            callouts=sorted(times),
            coverage=coverage,
            pre=pre,
            post=longest,
            replicates=replicates,
            rng=rng,
        )
    realised = min(
        (sum(1 for rep in reps if rep) for reps in placebo_plan.values()),
        default=0,
    )
    if realised < 2:
        return replace(
            base,
            reason=(
                "hour-matched, max(pre,post)-separated placebos could not be drawn: the "
                f"coverage window is {(coverage.end - coverage.start).total_seconds() / 3600:.2f}h, "
                "which admits fewer than 2 legal matches for at least one mint"
            ),
            notes=tuple(notes),
        )

    hypotheses: list[HypothesisResult] = []
    for outcome in outcomes:
        for window in windows:
            post = timedelta(minutes=window)
            counts: list[MintCounts] = []
            per_replicate: list[list[MintCounts]] = [[] for _ in range(replicates)]
            for mint, times in sorted(by_mint.items()):
                legs = trades_by_mint.get(mint, [])
                treated = sum(
                    count_window(legs, at=at, post=post, eligible=eligible, outcome=outcome)
                    for at in times
                )
                reps = placebo_plan[mint]
                rep_counts = [
                    (
                        len(rep),
                        sum(
                            count_window(legs, at=at, post=post, eligible=eligible, outcome=outcome)
                            for at in rep
                        ),
                    )
                    for rep in reps
                ]
                windows_total = sum(n for n, _ in rep_counts)
                arrivals_total = sum(c for _, c in rep_counts)
                counts.append(
                    MintCounts(
                        mint=mint,
                        treated_events=len(times),
                        treated_count=treated,
                        treated_exposure=len(times) * post.total_seconds(),
                        placebo_windows=windows_total,
                        placebo_count=arrivals_total,
                        placebo_exposure=windows_total * post.total_seconds(),
                    )
                )
                # Leave-one-out null: replicate r is the pseudo-treatment, the rest the baseline.
                for index, (n_windows, arrivals) in enumerate(rep_counts):
                    others_w = windows_total - n_windows
                    others_a = arrivals_total - arrivals
                    if n_windows == 0 or others_w == 0:
                        continue
                    per_replicate[index].append(
                        MintCounts(
                            mint=mint,
                            treated_events=n_windows,
                            treated_count=arrivals,
                            treated_exposure=n_windows * post.total_seconds(),
                            placebo_windows=others_w,
                            placebo_count=others_a,
                            placebo_exposure=others_w * post.total_seconds(),
                        )
                    )
            estimate = pool(counts)
            null_draws = [pool(rep).partial_mu for rep in per_replicate if rep]
            p_value, p_floor = placebo_p_value(estimate.partial_mu, null_draws)
            hypotheses.append(
                HypothesisResult(
                    outcome=outcome,
                    window_minutes=window,
                    estimate=estimate,
                    p_value=p_value,
                    p_floor=p_floor,
                    n_null_draws=len(null_draws),
                    n_treated_events=sum(row.treated_events for row in counts),
                    n_treated_arrivals=sum(row.treated_count for row in counts),
                    n_placebo_windows=sum(row.placebo_windows for row in counts),
                    n_placebo_arrivals=sum(row.placebo_count for row in counts),
                    null_spread=(max(null_draws) - min(null_draws)) if null_draws else 0.0,
                )
            )

    flags = bh_fdr([hypothesis.p_value for hypothesis in hypotheses], q=FDR_Q)
    hypotheses = [
        replace(hypothesis, fdr_rejected=flag)
        for hypothesis, flag in zip(hypotheses, flags, strict=True)
    ]

    # The primary hypothesis is pre-registered. A run that drops it is a different study, and
    # picking whichever hypothesis happens to be present would be primary-shopping by accident.
    primary = next(
        (
            hypothesis
            for hypothesis in hypotheses
            if hypothesis.outcome == "buy_arrivals"
            and hypothesis.window_minutes == PRIMARY_WINDOW_MINUTES
        ),
        None,
    )
    if primary is None:
        raise StudyError(
            f"the pre-registered primary hypothesis (buy_arrivals @ {PRIMARY_WINDOW_MINUTES}min) "
            f"is not in the requested family outcomes={list(outcomes)} windows={list(windows)}; "
            "a run without it is a different study and must say so"
        )
    if primary.n_treated_arrivals == 0 and primary.n_placebo_arrivals == 0:
        verdict, reason = (
            VERDICT_UNRESOLVABLE,
            "zero arrivals in both the treated and the placebo windows: the outcome variable is "
            "identically zero, so no estimator can distinguish any hypothesis from any other",
        )
    elif primary.n_placebo_arrivals == 0:
        # A structural zero baseline is NOT a huge effect, it is an unidentified one. With no
        # placebo arrivals the log rate ratio is fixed by the continuity correction rather than by
        # data, and the null draws all reduce to the same exposure ratio, so p hits its floor
        # mechanically. Including our own policy wallet produces exactly this: 15 treated arrivals
        # against 0 in 32,400 placebo windows, reported as a ~240x lift at p = 0.005. Only a
        # one-sided bound is available here, never a point estimate.
        verdict, reason = (
            VERDICT_UNRESOLVABLE,
            f"baseline is a structural zero ({primary.n_placebo_arrivals} arrivals in "
            f"{primary.n_placebo_windows} placebo windows): the log rate ratio is set by the "
            "continuity correction, not by data, and the placebo null is degenerate",
        )
    elif _null_is_degenerate(primary):
        verdict, reason = (
            VERDICT_UNRESOLVABLE,
            "the placebo null distribution has no spread, so p is mechanical rather than measured",
        )
    elif primary.fdr_rejected:
        verdict, reason = (VERDICT_SUGGESTIVE, "primary hypothesis survives BH-FDR")
    elif primary.p_value <= primary.p_floor + 1e-12 and primary.p_floor > 0.05:
        verdict, reason = (
            VERDICT_UNRESOLVABLE,
            f"p sits at its floor {primary.p_floor:.3g}; the instrument cannot resolve an effect",
        )
    else:
        verdict, reason = (VERDICT_NULL, "no hypothesis in the family survives BH-FDR")

    return replace(
        base, verdict=verdict, reason=reason, hypotheses=tuple(hypotheses), notes=tuple(notes)
    )


def study_from_store(store: Path, *, seed: int, **kwargs: Any) -> StudyResult:
    """Open a *copy* of the intelligence store read-only and run the study."""
    if not store.exists():
        raise StudyError(f"no store at {store}; copy it first, the daemon holds a lock")
    connection = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
    try:
        callouts, rejected = load_callouts(connection)
        return run_study(
            callouts, load_trades(connection), seed=seed, rejected_callout_rows=rejected, **kwargs
        )
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--store", type=Path, required=True, help="path to a COPY of intelligence.sqlite3")
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--replicates", type=int, default=200)
    parser.add_argument("--pre-minutes", type=int, default=30)
    parser.add_argument("--out", type=Path, default=None, help="JSONL output path (never CSV)")
    parser.add_argument(
        "--include-policy-wallets",
        action="store_true",
        help="ALSO count our own sentinel's fills. Closed loop; never valid for inference.",
    )
    args = parser.parse_args(argv)
    result = study_from_store(
        args.store,
        seed=args.seed,
        replicates=args.replicates,
        pre_minutes=args.pre_minutes,
        exclude_wallets=frozenset() if args.include_policy_wallets else POLICY_WALLETS,
    )
    payload = result.to_json()
    if args.include_policy_wallets:
        payload["INFERENCE_INVALID"] = "policy wallets included: this arm is a closed loop"
    line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
