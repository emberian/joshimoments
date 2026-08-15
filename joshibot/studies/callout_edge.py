"""Does a callout carry information about forward return, over the free columns?

The question nobody has tested. The operator's original manual strategy — the
one that made money — was clicking every coin in the callout feed and glancing
at it. Every study since has measured something else: the probe polled the
general listing (a different population, −15%), and RESULT_llm_filter ran nine
arms across five elicitation styles and found rho ~ 0 for the *content* channel,
with a plain drawdown column beating every verbalised judgement. That study
could not test the callout channel at all: 10 of its 333 cohort mints appeared
in the intelligence store. So "an LLM cannot read a name and a description" is
measured; "who called this, and how loudly" is not.

What this study does.

1. Takes the callout stream over a window (backfilled from X with `since_time:`
   / `until_time:`, which the pinned Apify actor honours, so the sample is a
   census of those query patterns rather than whatever the daemon happened to
   catch).
2. Prices every called mint at minute resolution from GeckoTerminal, which
   prices a coin whether or not it is on a board — see `callout_prices` for why
   the board tape is the wrong instrument for *this* event.
3. Asks whether callout features beat the free numeric columns, entity-clustered,
   temporally split, against three nulls.

Censoring, which already destroyed one finding in this repo. RESULT_board_entry
reported +21.77% at 8 h; pricing the censored 96% instead of dropping them
reverses it to −12.24%. The rule here is that **no row is ever dropped for being
censored**. A coin whose pool stops trading is marked at its last traded price
and its death is modelled as a competing risk, not as missing data. Survival
quantities are reported as survival quantities and never as returns.

Reporting rules carried from PROGRAM.md §3: temporal split, a mint never
straddles it, no resampling, AUPRC alongside AUC with the base rate stated, the
threshold reported with every rate, cluster-robust inference on mint, and a null
that preserves autocorrelation rather than an i.i.d. shuffle that this repo has
twice caught manufacturing an effect.

Usage:
    uv run --group research python -m studies.callout_edge --report
"""

from __future__ import annotations

import argparse
import bisect
import glob
import itertools
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO = Path(__file__).resolve().parent.parent
CALLOUT_GLOB = str(REPO / "state" / "callouts" / "*.jsonl")
PRICES = REPO / "state" / "callouts" / "prices"
PUMP_SUPPLY = 1_000_000_000.0

HORIZONS_S: tuple[int, ...] = (3600, 28800)  # 1 h and 8 h, the brief's two anchors
#: A mark is "stale" past this; the return is still real, the *fill* is not.
FILL_TOLERANCE_S = 900
#: No trade for this long after the mark means the pool is dead, not quiet.
DEATH_SILENCE_S = 3600

FREE_COLUMNS = ("log_mcap", "log_age_s", "drawdown_60m", "log_vol_10m", "rv_30m")
#: Everything knowable at the instant of the call. `log_views` is deliberately
#: NOT here: the scraper reads a tweet's view count whenever it happens to
#: collect it, which for the backfill is hours after the tweet, so a coin that
#: stayed alive and kept attracting clicks lends its own future to the feature.
#: That is look-ahead, and it is the exact failure mode that produces this
#: field's 0.95 AUCs.
CALLOUT_COLUMNS = (
    "log_followers",
    "verified",
    "n_prior_callers",
    "is_first_caller",
    "log_since_first_call_s",
    "burst_10m",
    "mint_from_url",
    "caller_prior_calls",
    "caller_prior_hit_rate",
)
#: The same block plus the contaminated engagement counters, reported only to
#: show that even *with* look-ahead the callout channel does not win.
CALLOUT_COLUMNS_LEAKY = (*CALLOUT_COLUMNS, "log_views")


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def _is_mint(text: Any) -> bool:
    from shitcoims_intelligence.adapters.x_apify import is_solana_mint

    return isinstance(text, str) and is_solana_mint(text)


def load_callouts(paths: str = CALLOUT_GLOB) -> list[dict[str, Any]]:
    """One row per (mint, tweet). A tweet naming two mints is two callouts."""

    out: list[dict[str, Any]] = []
    for path in sorted(glob.glob(paths)):
        with open(path) as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # the collector may be mid-append
                stamp = row.get("t_post")
                if not stamp:
                    continue
                try:
                    t_post = datetime.fromisoformat(stamp).timestamp()
                except ValueError:
                    continue
                for mint in row.get("mints") or []:
                    if not _is_mint(mint):
                        continue
                    out.append(
                        {
                            "mint": mint,
                            "t_post": t_post,
                            "tweet_id": row.get("tweet_id"),
                            "author": row.get("author_username"),
                            "followers": row.get("author_followers"),
                            "verified": bool(row.get("author_verified")),
                            "views": row.get("view_count"),
                            "likes": row.get("like_count"),
                            "channel": row.get("query"),
                            "from_url": mint in (row.get("mint_candidates") or []),
                        }
                    )
    out.sort(key=lambda r: r["t_post"])
    return out


_BOARD_DEDUP_S = 5.0


def load_board_series(
    mints: set[str], paths: str | None = None
) -> dict[str, list[tuple[float, float, float]]]:
    """(unix, usd_market_cap, 0.0) from the board snapshots, for callout mints.

    Free, instant, 30-second cadence — and 74.8% of callout mints appear here,
    because the `last_trade_timestamp` board churns every few minutes and a
    freshly-called coin is by construction a freshly-traded one.

    The catch, and it is the whole point of this study's censoring discipline:
    a coin is priced here only while it is in some board's top 50, and it drops
    out when it stops trading. Board censoring is therefore *informative* — the
    coins that vanish are the ones that died — which is precisely the mechanism
    that turned RESULT_board_entry's +21.77% at 8 h into −12.24% once the
    censored 96% were priced instead of dropped. This source is used with that
    known, and cross-checked against GeckoTerminal wherever both exist.

    A mint can sit on up to five boards, so the same instant arrives up to five
    times; near-duplicate samples are collapsed the way `bandit_search` does.
    """

    pattern = paths or str(REPO / "state" / "boards" / "*.jsonl")
    raw: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for path in sorted(glob.glob(pattern)):
        with open(path) as fh:
            for line in fh:
                if '"board_snapshot"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = row.get("t_ingest")
                for member in row.get("members") or []:
                    mint = member.get("mint")
                    if mint not in mints:
                        continue
                    mcap = member.get("usd_market_cap") or 0.0
                    if mcap > 0 and t:
                        raw[mint].append((float(t), float(mcap)))
    out: dict[str, list[tuple[float, float, float]]] = {}
    for mint, points in raw.items():
        points.sort()
        kept: list[tuple[float, float, float]] = []
        for t, mcap in points:
            if kept and t - kept[-1][0] < _BOARD_DEDUP_S:
                continue
            kept.append((t, mcap, 0.0))
        out[mint] = kept
    return out


def load_prices(mint: str) -> list[tuple[float, float, float]] | None:
    """(unix, usd_market_cap, volume) minute candles, time-ordered. None = no pool.

    GeckoTerminal quotes a per-token USD price while the board tape quotes a USD
    market cap. Both are scaled here to *market cap* so the two sources are
    interchangeable row by row — pump.fun supply is fixed at 1e9, so the
    conversion is exact and returns are unaffected either way, but a level
    feature like `log_mcap` is meaningless if half the rows are 1e9 times the
    other half.
    """

    path = PRICES / f"{mint}.json"
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text())
    except Exception:
        return None
    candles = record.get("candles") or []
    if not candles:
        return None
    return [
        (float(c[0]), float(c[4]) * PUMP_SUPPLY, float(c[5]) if len(c) > 5 else 0.0)
        for c in candles
    ]


# ---------------------------------------------------------------------------
# pricing: censored rows are marked, never dropped
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Mark:
    price: float
    t_price: float
    staleness_s: float
    live: bool  # a fill at this price is plausible


def mark_at(series: Sequence[tuple[float, float, float]], t: float) -> Mark | None:
    """Last close at or before `t`. Never looks ahead; never returns None for
    a quiet pool, only for a pool that had not traded at all yet."""

    times = [c[0] for c in series]
    idx = bisect.bisect_right(times, t) - 1
    if idx < 0:
        return None
    ts, close, _ = series[idx]
    stale = t - ts
    return Mark(close, ts, stale, stale <= FILL_TOLERANCE_S)


def build_rows(
    callouts: Iterable[dict[str, Any]],
    *,
    tape_end: float,
    source: str = "auto",
) -> list[dict[str, Any]]:
    """Attach features and outcomes. A row survives iff it has a price at t_post.

    `source`: "gt" (GeckoTerminal candles only), "boards" (board snapshots only),
    or "auto" (GeckoTerminal where cached, boards otherwise). Running the same
    cohort under "gt" and "boards" and differencing the result *is* the
    survivorship measurement — the two sources disagree exactly where the board
    censoring bites.
    """

    by_mint: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in callouts:
        by_mint[c["mint"]].append(c)
    for group in by_mint.values():
        group.sort(key=lambda r: r["t_post"])

    # Burst = how many callouts named this mint in the ten minutes before now.
    stamps_by_mint = {m: [c["t_post"] for c in g] for m, g in by_mint.items()}

    boards = (
        load_board_series(set(by_mint)) if source in {"auto", "boards"} else {}
    )
    rows: list[dict[str, Any]] = []
    dropped = {"no_pool": 0, "no_price_yet": 0, "unfetched": 0}
    used_source: dict[str, int] = defaultdict(int)
    for mint, group in by_mint.items():
        series = load_prices(mint) if source in {"auto", "gt"} else None
        price_source = "gt"
        if series is None and source in {"auto", "boards"}:
            series = boards.get(mint) or None
            price_source = "boards"
        if series is None:
            # Three different things, and conflating them would be the same
            # mistake as calling censoring missingness: a mint we never asked
            # about, a mint GeckoTerminal does not index (no pool ever existed
            # — the "callout" named something untradeable), and a mint with a
            # pool but no candles. Only the first is fixable by more fetching.
            if not (PRICES / f"{mint}.json").exists():
                dropped["unfetched"] += len(group)
            else:
                dropped["no_pool"] += len(group)
            continue
        stamps = stamps_by_mint[mint]
        first_call = stamps[0]
        for order, call in enumerate(group):
            t0 = call["t_post"]
            entry = mark_at(series, t0)
            if entry is None or entry.price <= 0:
                # No trade had ever happened at the moment of the call. There is
                # no price to enter at, so there is no return to measure. This is
                # the one legitimate exclusion and it is counted.
                dropped["no_price_yet"] += 1
                continue
            prior = [c for c in series if c[0] <= t0]
            window_60m = [c for c in prior if c[0] >= t0 - 3600] or prior[-1:]
            window_30m = [c for c in prior if c[0] >= t0 - 1800]
            window_10m = [c for c in prior if c[0] >= t0 - 600]
            peak = max(c[1] for c in window_60m)
            closes = [c[1] for c in window_30m]
            rv = 0.0
            if len(closes) > 2:
                rets = [
                    math.log(b / a) for a, b in itertools.pairwise(closes) if a > 0 and b > 0
                ]
                if len(rets) > 1:
                    mean = sum(rets) / len(rets)
                    rv = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
            used_source[price_source] += 1
            row: dict[str, Any] = {
                "mint": mint,
                "t_post": t0,
                "author": call["author"],
                "channel": call["channel"],
                "price_source": price_source,
                "entry_price": entry.price,
                "entry_stale_s": entry.staleness_s,
                "entry_live": entry.live,
                # --- free numeric columns, all as-of t_post ---
                # `entry.price` is already a USD market cap for both sources.
                "log_mcap": math.log(max(entry.price, 1e-9)),
                "log_age_s": math.log(max(t0 - series[0][0], 60.0)),
                "drawdown_60m": 1.0 - entry.price / peak if peak > 0 else 0.0,
                "log_vol_10m": math.log1p(sum(c[2] for c in window_10m)),
                "rv_30m": rv,
                # --- callout columns ---
                "log_followers": math.log1p(float(call["followers"] or 0)),
                "verified": 1.0 if call["verified"] else 0.0,
                "n_prior_callers": float(order),
                "is_first_caller": 1.0 if order == 0 else 0.0,
                "log_since_first_call_s": math.log1p(max(t0 - first_call, 0.0)),
                "log_views": math.log1p(float(call["views"] or 0)),
                "burst_10m": float(sum(1 for s in stamps if t0 - 600 <= s <= t0)),
                "mint_from_url": 1.0 if call["from_url"] else 0.0,
            }
            last_trade = series[-1][0]
            for h in HORIZONS_S:
                exit_mark = mark_at(series, t0 + h)
                assert exit_mark is not None  # entry existed, so a prior mark exists
                row[f"r{h}"] = exit_mark.price / entry.price - 1.0
                row[f"live{h}"] = exit_mark.live
                row[f"stale{h}"] = exit_mark.staleness_s
                # Administrative censoring: the horizon runs past the tape.
                row[f"admin{h}"] = (t0 + h) > tape_end
            row["t_last_trade"] = last_trade
            row["death_s"] = last_trade - t0
            row["died"] = (tape_end - last_trade) > DEATH_SILENCE_S
            rows.append(row)
    rows.sort(key=lambda r: r["t_post"])
    attach_caller_track_record(rows)
    build_rows.dropped = dropped  # type: ignore[attr-defined]
    build_rows.sources = dict(used_source)  # type: ignore[attr-defined]
    return rows


def attach_caller_track_record(
    rows: list[dict[str, Any]], *, resolve_after_s: int = 3600
) -> None:
    """How this caller's *earlier, already-resolved* calls turned out.

    This is the sharpest form of the hypothesis: not "does a big account move a
    coin" but "are some callers reliably early". It has to be built causally or
    it is pure leakage, so a past call only counts once its own 1 h outcome was
    knowable at the moment of the current call — a call from 20 minutes ago is
    *not* yet evidence about the caller, and using it would be the same
    look-ahead that inflates every published AUC in this field to 0.95.

    Rows are consumed in time order; the accumulator is therefore an expanding
    window with no access to the future.
    """

    history: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for row in rows:  # already sorted by t_post
        author = row["author"] or "<unknown>"
        past = history[author]
        resolved = [hit for t_resolved, hit in past if t_resolved <= row["t_post"]]
        row["caller_prior_calls"] = float(len(resolved))
        row["caller_prior_hit_rate"] = (
            sum(resolved) / len(resolved) if resolved else 0.5  # no evidence = coin flip
        )
        past.append(
            (
                row["t_post"] + resolve_after_s,
                1 if row[f"r{HORIZONS_S[0]}"] > 0 else 0,
            )
        )


# ---------------------------------------------------------------------------
# split: temporal, entity-respecting
# ---------------------------------------------------------------------------


def temporal_entity_split(
    rows: Sequence[dict[str, Any]], *, frac: float = 0.5
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    """Split by time, then assign each mint wholly to the side of its first call.

    Splitting on rows alone lets a mint appear on both sides, which is the exact
    leak PROGRAM.md §3.2 forbids and which inflated the board-entry gap from
    16.3 pp to 34 pp when 1,271 rows turned out to be 189 mints.
    """

    if not rows:
        return [], [], 0.0
    cut = rows[int(len(rows) * frac)]["t_post"]
    first_call: dict[str, float] = {}
    for r in rows:
        first_call.setdefault(r["mint"], r["t_post"])
    train = [r for r in rows if first_call[r["mint"]] < cut]
    test = [r for r in rows if first_call[r["mint"]] >= cut]
    return train, test, cut


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def auc_auprc(labels: Sequence[int], scores: Sequence[float]) -> tuple[float, float]:
    from sklearn.metrics import average_precision_score, roc_auc_score

    if len(set(labels)) < 2:
        return float("nan"), float("nan")
    return (
        float(roc_auc_score(labels, scores)),
        float(average_precision_score(labels, scores)),
    )


def cluster_bootstrap_auc(
    labels: Sequence[int],
    scores: Sequence[float],
    groups: Sequence[str],
    *,
    draws: int = 2000,
    seed: int = 11,
) -> tuple[float, float]:
    """Percentile CI resampling MINTS, not rows.

    Resampling rows treats 8 callouts of one coin as 8 independent facts. They
    are one fact about one coin, and every metric here is a coin-level claim.
    """

    import numpy as np

    rng = np.random.default_rng(seed)
    index: dict[str, list[int]] = defaultdict(list)
    for i, g in enumerate(groups):
        index[g].append(i)
    keys = list(index)
    labels_a = np.asarray(labels)
    scores_a = np.asarray(scores)
    out: list[float] = []
    for _ in range(draws):
        picked = rng.choice(len(keys), size=len(keys), replace=True)
        idx: list[int] = []
        for k in picked:
            idx.extend(index[keys[k]])
        y = labels_a[idx]
        if len(set(y.tolist())) < 2:
            continue
        from sklearn.metrics import roc_auc_score

        out.append(float(roc_auc_score(y, scores_a[idx])))
    if not out:
        return float("nan"), float("nan")
    lo, hi = np.percentile(out, [2.5, 97.5])
    return float(lo), float(hi)


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


def fit_score(
    train: Sequence[dict[str, Any]],
    test: Sequence[dict[str, Any]],
    columns: Sequence[str],
    label_key: str,
) -> tuple[list[int], list[float]]:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    x_train = np.array([[r[c] for c in columns] for r in train], dtype=float)
    y_train = np.array([r[label_key] for r in train], dtype=int)
    x_test = np.array([[r[c] for c in columns] for r in test], dtype=float)
    y_test = [int(r[label_key]) for r in test]
    if len(set(y_train.tolist())) < 2:
        return y_test, [0.5] * len(y_test)
    # No class weighting: MELT's class-weighted BCE decalibrates the probability
    # an EV decision needs (PROGRAM.md §1.3), and the base rate here is not
    # extreme enough to need it.
    model = make_pipeline(
        StandardScaler(), LogisticRegression(max_iter=2000, C=1.0)
    )
    model.fit(x_train, y_train)
    return y_test, [float(p) for p in model.predict_proba(x_test)[:, 1]]


def usable_columns(
    rows: Sequence[dict[str, Any]], columns: Sequence[str], *, max_corr: float = 0.98
) -> list[str]:
    """Drop constant and near-duplicate columns before any fit.

    On this cohort the median mint has one callout, so `is_first_caller` is
    almost always 1 and is collinear with `n_prior_callers` and
    `log_since_first_call_s`. Feeding all three to a Cox or a clustered logit
    produces a singular information matrix and no estimate at all — which reads
    like a modelling failure but is really a statement about the cohort, so it
    is handled here explicitly and the dropped names are reported.
    """

    import numpy as np

    if not rows:
        return list(columns)
    matrix = np.array([[r[c] for c in columns] for r in rows], dtype=float)
    keep: list[str] = []
    kept_idx: list[int] = []
    for i, name in enumerate(columns):
        column = matrix[:, i]
        if float(column.std()) < 1e-9:
            continue
        duplicate = False
        for j in kept_idx:
            other = matrix[:, j]
            if float(other.std()) < 1e-9:
                continue
            corr = float(np.corrcoef(column, other)[0, 1])
            if corr == corr and abs(corr) >= max_corr:
                duplicate = True
                break
        if not duplicate:
            keep.append(name)
            kept_idx.append(i)
    return keep


def clustered_logit(
    rows: Sequence[dict[str, Any]], columns: Sequence[str], label_key: str
) -> tuple[Any, list[str]]:
    import numpy as np
    import statsmodels.api as sm

    columns = usable_columns(rows, columns)
    x = np.array([[r[c] for c in columns] for r in rows], dtype=float)
    # Standardize so coefficients are comparable and the optimizer behaves.
    mean, std = x.mean(axis=0), x.std(axis=0)
    std[std == 0] = 1.0
    x = (x - mean) / std
    x = sm.add_constant(x, has_constant="add")
    y = np.array([r[label_key] for r in rows], dtype=float)
    groups = np.array([r["mint"] for r in rows])
    model = sm.Logit(y, x)
    return model.fit(disp=0, cov_type="cluster", cov_kwds={"groups": groups}), list(columns)


# ---------------------------------------------------------------------------
# nulls
# ---------------------------------------------------------------------------


def null_iid(rows: Sequence[dict[str, Any]], label_key: str, rng: random.Random) -> list[dict]:
    labels = [r[label_key] for r in rows]
    rng.shuffle(labels)
    return [{**r, label_key: v} for r, v in zip(rows, labels, strict=True)]


def null_rotation(
    rows: Sequence[dict[str, Any]], label_key: str, rng: random.Random
) -> list[dict]:
    """Circularly shift outcomes against features in time order.

    An i.i.d. shuffle destroys the autocorrelation of the outcome series, so it
    understates how easily a correlated predictor lines up with a correlated
    target by chance. RESULT_flow_signals and RESULT_copytrading both had an
    apparent 73x collapse to 0.98x when this null replaced the i.i.d. one.
    """

    ordered = sorted(rows, key=lambda r: r["t_post"])
    labels = [r[label_key] for r in ordered]
    n = len(labels)
    if n < 3:
        return list(ordered)
    shift = rng.randrange(1, n)
    rotated = labels[shift:] + labels[:shift]
    return [{**r, label_key: v} for r, v in zip(ordered, rotated, strict=True)]


def null_caller_permutation(
    rows: Sequence[dict[str, Any]], rng: random.Random
) -> list[dict]:
    """Reassign caller identity across callouts, keeping timing and prices.

    This is the null aimed at the hypothesis itself: if *who* called it carries
    nothing, scrambling identity while leaving every timing and market feature
    intact should cost nothing.
    """

    identity_keys = (
        "log_followers",
        "verified",
        "log_views",
        "mint_from_url",
        "caller_prior_calls",
        "caller_prior_hit_rate",
    )
    donors = [tuple(r[k] for k in identity_keys) for r in rows]
    rng.shuffle(donors)
    return [
        {**r, **dict(zip(identity_keys, d, strict=True))}
        for r, d in zip(rows, donors, strict=True)
    ]


# ---------------------------------------------------------------------------
# survival / competing risks
# ---------------------------------------------------------------------------


def survival_report(rows: Sequence[dict[str, Any]], *, tape_end: float) -> dict[str, Any]:
    """Time from callout to the pool's last trade, with death as the event.

    Reported as survival, never converted into a return. `lifelines` makes the
    censoring indicator part of the model specification, which is exactly the
    discipline whose absence produced this repo's worst error.
    """

    import pandas as pd
    from lifelines import CoxPHFitter, KaplanMeierFitter

    frame = pd.DataFrame(
        {
            "duration": [max(r["death_s"], 60.0) for r in rows],
            "died": [1 if r["died"] else 0 for r in rows],
            "mint": [r["mint"] for r in rows],
        }
    )
    covariates = usable_columns(rows, (*FREE_COLUMNS, *CALLOUT_COLUMNS))
    for column in covariates:
        frame[column] = [float(r[column]) for r in rows]

    km = KaplanMeierFitter().fit(frame["duration"], frame["died"])
    out: dict[str, Any] = {
        "n": len(frame),
        "n_events": int(frame["died"].sum()),
        "median_survival_s": float(km.median_survival_time_),
        "covariates": covariates,
    }
    try:
        cox = CoxPHFitter(penalizer=0.1)
        cox.fit(
            frame[["duration", "died", *covariates, "mint"]],
            duration_col="duration",
            event_col="died",
            cluster_col="mint",
        )
        summary = cox.summary
        out["cox"] = {
            name: {
                "hazard_ratio": float(summary.loc[name, "exp(coef)"]),
                "p": float(summary.loc[name, "p"]),
            }
            for name in summary.index
        }
        out["cox_concordance"] = float(cox.concordance_index_)
    except Exception as exc:  # convergence on a small, collinear cohort
        out["cox_error"] = f"{type(exc).__name__}: {exc}"
    return out


def competing_risk_report(rows: Sequence[dict[str, Any]], horizon: int) -> dict[str, Any]:
    """Where a callout actually ends up at the horizon, as three exclusive states.

    "Up 8 h" conditional on still trading is not a return; it is a return times a
    survival probability, reported as though the survival term were 1. Splitting
    the outcome into {up, down, dead} keeps the survivorship visible instead of
    letting it hide in a mean.
    """

    states = {"up": 0, "down": 0, "dead": 0}
    for r in rows:
        if r["died"] and r["t_last_trade"] < r["t_post"] + horizon:
            states["dead"] += 1
        elif r[f"r{horizon}"] > 0:
            states["up"] += 1
        else:
            states["down"] += 1
    total = max(sum(states.values()), 1)
    return {
        "n": total,
        **{k: v for k, v in states.items()},
        **{f"p_{k}": v / total for k, v in states.items()},
    }


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def censoring_check(callouts: Sequence[dict[str, Any]], *, tape_end: float) -> None:
    """Price the same callouts both ways and difference them.

    The board tape stops pricing a coin when it leaves the top 50, which happens
    because it stopped trading — so a board-only study sees the survivors and a
    GeckoTerminal-priced study sees everyone. Where both sources cover the same
    (mint, t_post) this measures the gap directly on the callout population,
    rather than inheriting the board-entry lane's estimate of it.

    Two arms are reported. `board_dropped` is what a study that *discards*
    unpriceable rows would conclude — the mistake this repo already made once.
    `board_marked` is what the same source concludes with the mark-at-last-price
    rule, which is what this study actually uses.
    """

    import numpy as np

    gt_rows = build_rows(callouts, tape_end=tape_end, source="gt")
    board_rows = build_rows(callouts, tape_end=tape_end, source="boards")
    gt_index = {(r["mint"], r["t_post"]): r for r in gt_rows}
    pairs = [(gt_index[k], b) for b in board_rows if (k := (b["mint"], b["t_post"])) in gt_index]
    print(
        f"\n--- CENSORING CHECK: {len(pairs)} (mint, t_post) pairs priced by BOTH sources ---"
    )
    if len(pairs) < 8:
        print("  too few overlapping pairs to say anything; needs more GeckoTerminal coverage")
        return
    for h in HORIZONS_S:
        gt = np.array([g[f"r{h}"] for g, _ in pairs])
        board = np.array([b[f"r{h}"] for _, b in pairs])
        live = np.array([b[f"live{h}"] for _, b in pairs], dtype=bool)
        print(f"  horizon {h // 3600}h:")
        print(
            f"    GeckoTerminal (prices everyone)      mean={gt.mean():+8.2%} "
            f"median={np.median(gt):+8.2%} p(up)={float((gt > 0).mean()):5.1%}"
        )
        print(
            f"    boards, mark-at-last-price           mean={board.mean():+8.2%} "
            f"median={np.median(board):+8.2%} p(up)={float((board > 0).mean()):5.1%}"
        )
        if live.any():
            kept = board[live]
            print(
                f"    boards, CENSORED ROWS DROPPED        mean={kept.mean():+8.2%} "
                f"median={np.median(kept):+8.2%} p(up)={float((kept > 0).mean()):5.1%} "
                f"  <- {float(live.mean()):.1%} of rows survive this filter"
            )
            print(
                f"    survivorship gap (dropped - everyone) = "
                f"{kept.mean() - gt.mean():+.2%} mean, "
                f"{float((kept > 0).mean() - (gt > 0).mean()):+.1%} p(up)"
            )


def summarise_returns(rows: Sequence[dict[str, Any]], horizon: int, label: str) -> None:
    import numpy as np

    # A row whose horizon runs past the tape has no `horizon`-return at all; its
    # mark is simply the latest price, i.e. a shorter hold reported under a
    # longer label. Excluding it is the honest move, and the count is printed so
    # the exclusion is never invisible.
    usable = [x for x in rows if not x[f"admin{horizon}"]]
    if not usable:
        print(f"  {label:<26} n=0 (all {len(rows)} rows run past the tape)")
        return
    r = np.array([x[f"r{horizon}"] for x in usable], dtype=float)
    live = np.array([x[f"live{horizon}"] for x in usable], dtype=bool)
    print(
        f"  {label:<26} n={len(r):<5} mean={r.mean():+8.2%} median={np.median(r):+8.2%} "
        f"p(up)={float((r > 0).mean()):5.1%} live_marks={float(live.mean()):5.1%} "
        f"dropped_past_tape={len(rows) - len(usable)}"
    )


def report(rows: Sequence[dict[str, Any]], *, tape_end: float, seed: int = 7) -> None:
    import numpy as np

    print("=" * 88)
    print("CALLOUT EDGE — does a callout beat the free numeric columns?")
    print("=" * 88)
    mints = {r["mint"] for r in rows}
    print(
        f"\ncohort: {len(rows)} callouts on {len(mints)} mints, "
        f"{datetime.fromtimestamp(rows[0]['t_post'], UTC):%Y-%m-%d %H:%M} → "
        f"{datetime.fromtimestamp(rows[-1]['t_post'], UTC):%Y-%m-%d %H:%M} UTC"
    )
    per_mint = defaultdict(int)
    for r in rows:
        per_mint[r["mint"]] += 1
    print(
        f"callouts per mint: median {int(np.median(list(per_mint.values())))}, "
        f"max {max(per_mint.values())} — every metric below clusters on mint"
    )

    print("\n--- RETURNS (censored rows marked at last traded price, never dropped) ---")
    for h in HORIZONS_S:
        print(f"horizon {h // 3600}h:")
        summarise_returns(rows, h, "all callouts")
        summarise_returns(
            [r for r in rows if r["is_first_caller"] == 1.0], h, "first caller only"
        )
        summarise_returns(
            [r for r in rows if r["is_first_caller"] == 0.0], h, "a later caller"
        )
        summarise_returns([r for r in rows if r["burst_10m"] >= 2], h, "burst >= 2 callers/10m")
        summarise_returns(
            [r for r in rows if r["log_followers"] >= math.log1p(10_000)],
            h,
            "caller >= 10k followers",
        )
        summarise_returns(
            [r for r in rows if r["log_followers"] < math.log1p(1_000)],
            h,
            "caller < 1k followers",
        )
        summarise_returns([r for r in rows if r["verified"] == 1.0], h, "verified caller")
        print(f"  competing-risk states: {competing_risk_report(rows, h)}")

    print("\n--- SURVIVAL (reported as survival, never as a return) ---")
    surv = survival_report(rows, tape_end=tape_end)
    print(f"  n={surv['n']} deaths={surv['n_events']} median survival "
          f"{surv['median_survival_s'] / 3600:.2f} h")
    if "cox" in surv:
        print(f"  Cox concordance {surv['cox_concordance']:.3f} (mint-clustered)")
        ranked = sorted(surv["cox"].items(), key=lambda kv: kv[1]["p"])
        for name, stat in ranked[:6]:
            print(f"    {name:<24} HR={stat['hazard_ratio']:.3f}  p={stat['p']:.4f}")
    else:
        print(f"  cox unavailable: {surv.get('cox_error')}")

    print("\n--- DISCRIMINATION, temporal split, mint never straddles ---")
    trials = 0
    for h in HORIZONS_S:
        label = f"up{h}"
        for r in rows:
            r[label] = 1 if r[f"r{h}"] > 0 else 0
        # Horizon-eligibility comes BEFORE the split, not after. Splitting first
        # puts the late callouts in test, and the late callouts are exactly the
        # ones whose 8 h horizon runs past the tape — so the test set empties out
        # and the horizon looks unmeasurable when it merely needed the filter
        # applied in the right order.
        eligible = [{**r} for r in rows if not r[f"admin{h}"]]
        dropped_admin = len(rows) - len(eligible)
        if len(eligible) < 40:
            print(
                f"\n  horizon {h // 3600}h: only {len(eligible)} of {len(rows)} rows have a "
                f"full horizon inside the tape; not reportable"
            )
            continue
        train_l, test_l, cut = temporal_entity_split(eligible)
        if not train_l or not test_l:
            print(f"  horizon {h // 3600}h: split leaves one side empty")
            continue
        base = float(np.mean([r[label] for r in test_l]))
        print(
            f"\n  horizon {h // 3600}h — {dropped_admin} rows dropped for running past the "
            f"tape; split at {datetime.fromtimestamp(cut, UTC):%m-%d %H:%M} UTC"
        )
        print(
            f"    train {len(train_l)} rows / {len({r['mint'] for r in train_l})} mints, "
            f"test {len(test_l)} rows / {len({r['mint'] for r in test_l})} mints, "
            f"test base rate p(up) = {base:.1%}"
        )
        results: dict[str, tuple[float, float]] = {}
        for name, cols in (
            ("free columns only", FREE_COLUMNS),
            ("callout columns only", CALLOUT_COLUMNS),
            ("free + callout", (*FREE_COLUMNS, *CALLOUT_COLUMNS)),
            ("free + callout (leaky)", (*FREE_COLUMNS, *CALLOUT_COLUMNS_LEAKY)),
        ):
            trials += 1
            y, s = fit_score(train_l, test_l, cols, label)
            auc, ap = auc_auprc(y, s)
            lo, hi = cluster_bootstrap_auc(y, s, [r["mint"] for r in test_l])
            results[name] = (auc, ap)
            print(
                f"    {name:<22} AUC={auc:.3f} [{lo:.3f}, {hi:.3f}] "
                f"AUPRC={ap:.3f} (base {base:.3f})"
            )
        # Single free columns, so "beat the best free column" is checkable.
        best_single = None
        for col in FREE_COLUMNS:
            trials += 1
            y = [r[label] for r in test_l]
            s = [r[col] for r in test_l]
            auc, _ = auc_auprc(y, s)
            if auc == auc and (best_single is None or abs(auc - 0.5) > abs(best_single[1] - 0.5)):
                best_single = (col, auc)
        if best_single:
            print(f"    best single free column: {best_single[0]} AUC={best_single[1]:.3f}")

        print("    nulls (test-set AUC of free+callout under each):")
        rng = random.Random(seed + h)
        # `label` and `rng` are bound as defaults rather than closed over: these
        # lambdas outlive one iteration of the horizon loop, and a late-binding
        # closure would silently run every null against the last horizon's label.
        for null_name, maker in (
            ("i.i.d. label shuffle", lambda rs, k=label, g=rng: null_iid(rs, k, g)),
            (
                "label rotation (keeps autocorr)",
                lambda rs, k=label, g=rng: null_rotation(rs, k, g),
            ),
            ("caller identity permuted", lambda rs, g=rng: null_caller_permutation(rs, g)),
        ):
            aucs = []
            for _ in range(24):
                fake_train = maker(train_l)
                fake_test = maker(test_l)
                y, s = fit_score(
                    fake_train, fake_test, (*FREE_COLUMNS, *CALLOUT_COLUMNS), label
                )
                auc, _ = auc_auprc(y, s)
                if auc == auc:
                    aucs.append(auc)
            if aucs:
                arr = np.array(aucs)
                real = results["free + callout"][0]
                exceed = float((arr >= real).mean())
                print(
                    f"      {null_name:<32} AUC {arr.mean():.3f} "
                    f"[{np.percentile(arr, 5):.3f}, {np.percentile(arr, 95):.3f}] "
                    f"p(null >= observed) = {exceed:.3f}"
                )

        try:
            fit, used = clustered_logit(eligible, (*FREE_COLUMNS, *CALLOUT_COLUMNS), label)
            names = ["const", *used]
            print(
                f"    mint-clustered logit (n={len(eligible)}, "
                f"{len({r['mint'] for r in eligible})} mints), callout block:"
            )
            for i, name in enumerate(names):
                if name not in CALLOUT_COLUMNS:
                    continue
                print(
                    f"      {name:<24} beta={fit.params[i]:+.3f} "
                    f"z={fit.tvalues[i]:+.2f} p={fit.pvalues[i]:.4f}"
                )
            dropped = [c for c in CALLOUT_COLUMNS if c not in used]
            if dropped:
                print(f"      (dropped as constant/collinear on this cohort: {dropped})")
        except Exception as exc:
            print(f"    clustered logit unavailable: {type(exc).__name__}: {exc}")

    print(
        f"\n  trials counted this run: {trials}. PROGRAM.md §3.9: after ~7 independent "
        f"configurations an in-sample Sharpe of 1 corresponds to OOS zero. Read every "
        f"number above with that deflation in mind."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--callouts", default=CALLOUT_GLOB)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--dump", default=None, help="write the built cohort to JSONL")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--source", choices=("auto", "gt", "boards"), default="auto")
    ap.add_argument(
        "--tape-end",
        type=float,
        default=None,
        help=(
            "pin the end of the price tape (unix). The collectors are live, so an "
            "unpinned run drifts: every extra minute of tape makes one more row "
            "8 h-eligible and moves the 8 h numbers. Pin it to reproduce a result."
        ),
    )
    ap.add_argument(
        "--censoring-check",
        action="store_true",
        help="run the same mints under both price sources and difference them",
    )
    args = ap.parse_args()

    callouts = load_callouts(args.callouts)
    if not callouts:
        raise SystemExit("no callouts found; run studies.callout_backfill first")
    # The tape ends where the PRICE data ends, not where the callouts end, and
    # it must be read from whichever source is actually in use — taking it from
    # the GeckoTerminal cache while pricing from the board tape would date the
    # administrative-censoring cutoff to the wrong instrument entirely.
    tape_end = args.tape_end or 0.0
    if not tape_end:
        mints = {c["mint"] for c in callouts}
        if args.source in {"auto", "gt"}:
            for mint in mints:
                series = load_prices(mint)
                if series:
                    tape_end = max(tape_end, series[-1][0])
        if args.source in {"auto", "boards"}:
            for series in load_board_series(mints).values():
                if series:
                    tape_end = max(tape_end, series[-1][0])
    if not tape_end:
        tape_end = max(c["t_post"] for c in callouts) + max(HORIZONS_S)
    rows = build_rows(callouts, tape_end=tape_end, source=args.source)
    print(
        f"loaded {len(callouts)} callouts on {len({c['mint'] for c in callouts})} mints; "
        f"{len(rows)} priced rows on {len({r['mint'] for r in rows})} mints "
        f"(tape ends {datetime.fromtimestamp(tape_end, UTC):%m-%d %H:%M} UTC)"
    )
    print(f"price source: {getattr(build_rows, 'sources', {})}")
    print(f"unpriced callouts, by reason: {getattr(build_rows, 'dropped', {})}")
    if args.censoring_check:
        censoring_check(callouts, tape_end=tape_end)
    if args.dump:
        with open(args.dump, "w") as fh:
            for r in rows:
                fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    if args.report and rows:
        report(rows, tape_end=tape_end, seed=args.seed)


if __name__ == "__main__":
    main()
