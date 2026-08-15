"""Crime signatures: detecting a *manufactured* price path while you are still in it.

The operator's description, verbatim:

    "'criming' a token... one thing i've seen is a token that shoots to millions mcap,
    crawls ~linearly up to 20M with small amount of real trading activity (extremely
    small) and then the rug rips."

This module is an **exit-signal layer first**, an avoid-filter second, and a taxonomy of
manipulator strategies third. It is emphatically *not* an entry strategy for riding
manufactured pumps: every score it emits is a reason to reduce, never a reason to buy.

Why the pattern is measurable at all — the circuit frame (``PROGRAM.md`` §8)
-----------------------------------------------------------------------------
A CFMM pool is a nonlinear capacitor: reserves are charge, marginal price is voltage, and
``C = w_x·w_y·TVL`` (``TVL/4`` at 50/50) is exact to six significant figures
(``studies/RESULT_circuit_model.md``). The consequence that makes "criming" detectable is
a conservation law, not a heuristic:

    **A CFMM price cannot move without flow through the curve.** ``ΔV = ΔQ / C``.

So a price that climbs while measured volume stays tiny is not "a coin with strong hands."
It is one of exactly three things, and all three are adversarial:

1. the same actor is on both sides (wash trading inflates ``ΔQ`` without any real
   inventory changing hands, but it is *visible* as volume — so the crimed variant is the
   opposite: real displacement with *no* volume, i.e. supply metering);
2. supply is being metered by a controller who is the only seller, so a trickle of buys
   walks the price up a curve nobody is defending;
3. the pool is thin enough that ``C`` is tiny and the displacement is real but worthless —
   which is itself the setup for (1) and (2).

The measurable is therefore **displacement per unit flow**, ``|Δ ln p| / (volume / FDV)``,
and its *stability over time*. Organic price discovery has a noisy, fat-tailed
displacement-per-flow. A metered climb has a suspiciously constant one, because a
controller with a schedule produces a schedule.

The four signatures, and the honest status of each
--------------------------------------------------
S1 **displacement decoupled from flow** — measurable on price+volume alone. Implemented.
S2 **linearity** — organic paths are not linear in time; scheduled buy-bots are.
   Implemented as rolling R² of ``ln p`` (and of *level* p, since the operator's "crawls
   ~linearly" is a statement about market cap, not log market cap) against wall clock.
S3 **concentration and choreography** — needs signers. We have signers for the eleven
   cluster pools (``state/cluster_tape/``) and nothing else, so S3 is measured *only*
   there and is reported as a cluster-scoped result, never as a cohort-wide feature. Any
   claim that S3 generalises from eleven pools would be fiction.
S4 **the terminal event** — labelled mechanically from price and volume, deliberately
   re-derived here rather than imported from the sentinel's ``rug_detector`` thresholds
   (``config.yaml``: 40% liquidity drop, 20% quote collapse). Those are somebody's prior;
   this module measures the distribution and reports where those numbers land in it.

Two clocks, always
------------------
Vendor time is ``t_event`` (GeckoTerminal candle open, pump.fun timestamps); our time is
``t_ingest``. Alerts carry both. A window that we were not watching is a ``gap``, not a
zero — the firehose's discipline (``shitcoims_scalper/firehose.py``) applied to a study.

The answer, so nobody reads the code hoping for one
---------------------------------------------------
**The composite score does not work as an exit signal, and it fails in the informative
direction.** Across 12 pre-registered cells (2 splits × 2 labels × 3 horizons), 4 window
lengths and 18 post-hoc cells, it never beats its own rotation or mint-swap null. Precision at
every operating threshold is exactly zero. Against the cliff label it is *inverted* — AUC
0.259–0.489 — so a coin in the last day before an irreversible collapse looks *less* like a
manufactured climb than the ambient coin-hour does. ``studies/RESULT_crime_signatures.md`` has
the numbers and the six things that were established instead.

Two structural facts explain most of it, and both are worth more than the detector:
**16 of 23 mechanical cliffs happen in the pool's first 0–45 hours**, inside any usable feature
window; and **the rip itself is a frenzy of thousands of wallets**, not one seller, so whatever
is coordinated happened during accumulation and is not visible at the collapse.

Commands
--------
``cohort``          build the candidate list (boards tape + GT discovery) → ``cohort.jsonl``
``resolve``         mints → top pool + supply via GT ``tokens/multi`` → ``tokens.jsonl``
``fetch``           hourly OHLCV for cohort pools (cache shared with the deterioration study)
``label``           mechanical terminal-event labels → ``labels.jsonl``
``distributions``   where every threshold in the study came from
``eval``            cohort performance, lead times, nulls, BY-FDR — the pre-registered grid
``windows``         does a shorter window reach the fast cliffs? (it reaches them; it still fails)
``vol-control``     is a drawdown result just volatility scaling? **run this on any new one**
``breakdown``       POST-HOC: does the linear crawl break before it rips? (no)
``taxonomy``        manipulator strategy archetypes for the coins that cliffed
``held``            score the operator's four coins
``cluster``         S3 choreography on the eleven pools that have signers
``bq-pools``        choose the pool list for a BigQuery day
``bq-signers``      swap-level identity for cohort pools, aggregated in SQL (~$2.84/day)
``bq-choreography`` S3 on the cohort: ripping vs control vs the operator's own pools
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shitcoims_scalper.crime_detect import (
    ALERT_KINDS,
    FEATURE_KEYS,
    RIP_DROP,
    RIP_HOLD_H,
    RIP_RECOVER,
    RIP_WINDOW_H,
    SCORE_KEYS,
    Calibration,
    Series,
    alert_row,
    crime_score,
    defect_row,
    features_at,
    find_rip,
    new_run_id,
)
from studies.deterioration import (
    GT,
    MAJOR_MINTS,
    QUOTE_OK,
    Fetcher,
    fetch_ohlcv,
    jsonl_append,
    jsonl_read,
    ohlcv_path,
)

#: The measured half of the study lives here; the pure detector lives in
#: ``shitcoims_scalper.crime_detect`` and is imported rather than reimplemented, so what was
#: evaluated and what runs in production cannot drift apart.
_ = (ALERT_KINDS, SCORE_KEYS)

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "crime"
BOARDS_DIR = ROOT / "state" / "boards"
DISCOVERY = ROOT / "state" / "deterioration" / "discovery.jsonl"
COHORT = STATE / "cohort.jsonl"
TOKENS = STATE / "tokens.jsonl"
LABELS = STATE / "labels.jsonl"
SCORES = STATE / "scores.jsonl"
HEARTBEAT = STATE / "heartbeat.json"
ALERTS = STATE / "alerts.jsonl"

HOUR = 3600.0
WSOL = "So11111111111111111111111111111111111111112"

#: The operator's band. "shoots to millions mcap, crawls ~linearly up to 20M". Below this a
#: coin is a bonding-curve lottery ticket and the pattern has no room to express itself;
#: above it we are out of the reference class entirely.
BAND_LO = 1_000_000.0
BAND_HI = 250_000_000.0


# ---------------------------------------------------------------------------------------
# House discipline: two clocks, watch windows, heartbeats
# ---------------------------------------------------------------------------------------


def _now() -> float:
    return time.time()


def emit(path: Path, rows: Iterable[dict]) -> int:
    """Append rows, stamping our clock. Vendor clocks stay in ``t_event``."""

    stamped = []
    t = _now()
    for row in rows:
        r = dict(row)
        r.setdefault("t_ingest", t)
        r.setdefault("schema", "crime.v1")
        stamped.append(r)
    return jsonl_append(path, stamped)


def heartbeat(stage: str, **payload: Any) -> None:
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEARTBEAT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"stage": stage, "t_ingest": _now(), **payload}))
    tmp.replace(HEARTBEAT)


# ---------------------------------------------------------------------------------------
# Cohort construction
# ---------------------------------------------------------------------------------------
#
# The survivorship problem is the whole game here, and it deserves to be stated before the
# code rather than discovered in the results.
#
# GeckoTerminal's pool *listings* are ordered by current volume, so anything that rugged
# three weeks ago is invisible to them. A cohort built only from GT listings is a cohort of
# coins that are still alive, which is precisely the wrong sample for a rug study — it is
# the same conditioning error the deterioration study called out and then, for its own
# question, deliberately kept.
#
# The pump.fun boards tape is an *independent enumerator* that does not have this property:
# `state/boards/*.jsonl` records the market-cap / reply-count / last-trade boards, and a
# coin that died is still on the last-reply and market-cap boards with its ATH attached. So
# the cohort is built from the union, with the boards half supplying the deaths.
#
# One caveat recorded honestly: pump.fun's own `ath_market_cap` is unusable as a *level*
# (it returns values up to 1e26 for pre-migration coins — a units bug on their side, not
# ours). It is used here strictly as a *screen* and never as a measurement; every number in
# the results is computed from OHLCV plus on-chain supply.


def _boards_universe() -> dict[str, dict]:
    """Best-known state per mint across every board snapshot on disk."""

    best: dict[str, dict] = {}
    for path in sorted(BOARDS_DIR.glob("boards-*.jsonl")):
        with path.open() as fh:
            for line in fh:
                if '"board_snapshot"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("kind") != "board_snapshot":
                    continue
                for m in row.get("members") or []:
                    mint = m.get("mint")
                    if not mint:
                        continue
                    cur = best.get(mint)
                    if cur is None:
                        best[mint] = dict(m)
                        continue
                    cur["ath_market_cap"] = max(
                        cur.get("ath_market_cap") or 0.0, m.get("ath_market_cap") or 0.0
                    )
                    if (m.get("t_ingest") or 0) >= (cur.get("t_ingest") or 0):
                        cur["usd_market_cap"] = m.get("usd_market_cap")
                        cur["t_ingest"] = m.get("t_ingest")
                    cur["reply_count"] = max(cur.get("reply_count") or 0, m.get("reply_count") or 0)
                    cur["last_trade_unix"] = max(
                        cur.get("last_trade_unix") or 0.0, m.get("last_trade_unix") or 0.0
                    )
                    cur["created_unix"] = cur.get("created_unix") or m.get("created_unix")
                    cur["symbol"] = cur.get("symbol") or m.get("symbol")
    return best


def _discovery_universe() -> dict[str, dict]:
    """Best (highest-volume) discovery row per *base mint*, quote-token filtered."""

    best: dict[str, dict] = {}
    for row in jsonl_read(DISCOVERY):
        mint = row.get("base_mint")
        if not mint or mint in MAJOR_MINTS:
            continue
        if row.get("quote_mint") not in QUOTE_OK:
            continue
        prior = best.get(mint)
        if prior is None or float(row.get("vol_h24") or 0) > float(prior.get("vol_h24") or 0):
            best[mint] = row
    return best


def build_cohort() -> list[dict]:
    """Candidate mints worth spending a keyless API call on, with a stated reason each."""

    boards = _boards_universe()
    disc = _discovery_universe()
    out: dict[str, dict] = {}

    for mint, m in boards.items():
        ath = float(m.get("ath_market_cap") or 0.0)
        now = float(m.get("usd_market_cap") or 0.0)
        if ath < BAND_LO:
            continue
        ratio = now / ath if ath > 0 else None
        # `ath` is a screen, not a measurement (see module note). The *ratio* survives the
        # units bug because numerator and denominator share it.
        arm = "collapsed" if (ratio is not None and ratio < 0.20) else "standing"
        out[mint] = {
            "mint": mint,
            "symbol": m.get("symbol"),
            "source": "boards",
            "screen_arm": arm,
            "screen_ath_mcap": ath,
            "screen_now_mcap": now,
            "screen_ratio": ratio,
            "reply_count": m.get("reply_count"),
            "t_event_created": m.get("created_unix"),
            "t_event_last_trade": m.get("last_trade_unix"),
        }

    # The discovery arm's own screen is on *current* FDV, and that is a trap this study
    # walked into once: a coin that reached $1.4B and fell 99.9% now reads as a $1M coin, so
    # a `fdv >= BAND_LO` gate on the snapshot excludes precisely the collapsed coins the
    # study is about. Two corrections: the gate is on the *upper* bound only, and any
    # discovery mint whose history is already cached is admitted regardless — that history
    # is free, and its peak market cap (computed from the series in `build_coins`) is what
    # actually decides membership.
    for mint, d in disc.items():
        fdv = float(d.get("fdv_usd") or 0.0)
        cached = bool(d.get("pool")) and ohlcv_path(d["pool"]).exists()
        if fdv > BAND_HI:
            continue
        if not cached and fdv < BAND_LO:
            continue
        prior = out.get(mint)
        row = {
            "mint": mint,
            "symbol": (d.get("name") or "").split("/")[0].strip() or None,
            "source": "discovery",
            "screen_arm": "standing",
            "screen_ath_mcap": None,
            "screen_now_mcap": fdv,
            "screen_ratio": None,
            "pool_hint": d.get("pool"),
            "t_event_created": d.get("created_at"),
        }
        if prior is None:
            out[mint] = row
        else:
            prior.setdefault("pool_hint", d.get("pool"))
            prior["source"] = "boards+discovery"
    return list(out.values())


def cmd_cohort(args: argparse.Namespace) -> None:
    rows = build_cohort()
    STATE.mkdir(parents=True, exist_ok=True)
    COHORT.write_text("")
    emit(COHORT, rows)
    arms = defaultdict(int)
    for r in rows:
        arms[(r["source"], r["screen_arm"])] += 1
    print(f"cohort: {len(rows)} mints")
    for k, v in sorted(arms.items()):
        print(f"  {k[0]:18s} {k[1]:10s} {v:5d}")


# ---------------------------------------------------------------------------------------
# Resolution: mint -> pool + supply
# ---------------------------------------------------------------------------------------


def _known_tokens() -> dict[str, dict]:
    return {r["mint"]: r for r in jsonl_read(TOKENS) if r.get("mint")}


def cmd_resolve(args: argparse.Namespace) -> None:
    """GT ``tokens/multi`` gives top_pools + total_supply, 30 mints per call."""

    cohort = list(jsonl_read(COHORT))
    known = _known_tokens()
    todo = [r for r in cohort if r["mint"] not in known]
    # Deaths first: they are the scarce half of the cohort and the whole point.
    todo.sort(key=lambda r: (0 if r.get("screen_arm") == "collapsed" else 1, -(r.get("screen_ath_mcap") or 0)))
    todo = todo[: args.limit]
    print(f"resolve: {len(todo)} unresolved of {len(cohort)}")
    fetcher = Fetcher(min_interval=args.interval)
    STATE.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(todo), 30):
        chunk = todo[i : i + 30]
        url = GT + "/networks/solana/tokens/multi/" + ",".join(r["mint"] for r in chunk) + "?include=top_pools"
        payload = fetcher.get(url)
        rows = []
        got = {d.get("attributes", {}).get("address"): d for d in ((payload or {}).get("data") or [])}
        for r in chunk:
            d = got.get(r["mint"])
            if d is None:
                rows.append({"mint": r["mint"], "resolved": False, "reason": "absent_from_gt"})
                continue
            a = d.get("attributes") or {}
            pools = [p["id"].split("_", 1)[-1] for p in ((d.get("relationships") or {}).get("top_pools") or {}).get("data") or []]
            lp = a.get("launchpad_details") or {}
            rows.append(
                {
                    "mint": r["mint"],
                    "resolved": bool(pools),
                    "symbol": a.get("symbol"),
                    "name": a.get("name"),
                    "decimals": a.get("decimals"),
                    "total_supply": a.get("normalized_total_supply"),
                    "price_usd": a.get("price_usd"),
                    "fdv_usd": a.get("fdv_usd"),
                    "reserve_usd": a.get("total_reserve_in_usd"),
                    "vol_h24": (a.get("volume_usd") or {}).get("h24"),
                    "pools": pools,
                    "graduated": lp.get("completed"),
                    "t_event_graduated": lp.get("completed_at"),
                }
            )
        emit(TOKENS, rows)
        heartbeat("resolve", done=i + len(chunk), total=len(todo), calls=fetcher.calls)
        print(f"  {i + len(chunk)}/{len(todo)} resolved (+{sum(1 for r in rows if r.get('resolved'))})")


def cmd_fetch(args: argparse.Namespace) -> None:
    """Hourly OHLCV for every resolved cohort pool. Cache is shared with deterioration."""

    cohort = {r["mint"]: r for r in jsonl_read(COHORT)}
    tokens = _known_tokens()
    todo: list[tuple[str, str]] = []
    for mint, t in tokens.items():
        if not t.get("resolved") or not t.get("pools"):
            continue
        pool = t["pools"][0]
        if ohlcv_path(pool).exists():
            continue
        todo.append((mint, pool))
    todo.sort(
        key=lambda mp: (
            0 if cohort.get(mp[0], {}).get("screen_arm") == "collapsed" else 1,
            -(cohort.get(mp[0], {}).get("screen_ath_mcap") or 0),
        )
    )
    todo = todo[: args.limit]
    print(f"fetch: {len(todo)} pools need OHLCV")
    fetcher = Fetcher(min_interval=args.interval)
    ok = 0
    for i, (_mint, pool) in enumerate(todo, 1):
        rec = fetch_ohlcv(fetcher, pool, limit=1000)
        ok += 1 if rec else 0
        if i % 10 == 0 or i == len(todo):
            heartbeat("fetch", done=i, total=len(todo), ok=ok, calls=fetcher.calls, throttles=fetcher.throttles)
            print(f"  {i}/{len(todo)} ok={ok} interval={fetcher.min_interval:.1f}s")


# ---------------------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------------------



def load_series(pool: str, mint: str, symbol: str | None, supply: float | None) -> Series | None:
    """Read a cached GeckoTerminal OHLCV file into the detector's ``Series``.

    GT emits a candle only for an hour that traded, so the grid is regularised inside
    ``Series.from_ohlcv``: an absent hour becomes the previous close with zero volume. That
    is a *measured zero* — GT is the exchange's own aggregation, not a sampler — and
    collapsing those hours would delete exactly the "extremely small trading activity" the
    operator described.
    """

    path = ohlcv_path(pool)
    if not path.exists():
        return None
    try:
        rec = json.loads(path.read_text())
    except Exception:
        return None
    rows = rec.get("ohlcv") or []
    if len(rows) < 24:
        return None
    return Series.from_ohlcv(pool, mint, symbol, rows, supply=supply)


def cohort_series(min_candles: int = 72) -> list[Series]:
    """Every cohort mint with a usable history, deduplicated to one pool per mint."""

    tokens = _known_tokens()
    cohort = {r["mint"]: r for r in jsonl_read(COHORT)}
    out: list[Series] = []
    seen: set[str] = set()
    for mint, t in tokens.items():
        if mint in seen or not t.get("resolved"):
            continue
        supply = _f(t.get("total_supply"))
        best: Series | None = None
        # `pool_hint` recovers the deterioration study's already-cached histories when GT's
        # current top_pools disagrees with the pool that study happened to fetch — the cache
        # is shared, so this is free coverage rather than a second download.
        pools = list((t.get("pools") or [])[:2])
        hint = cohort.get(mint, {}).get("pool_hint")
        if hint and hint not in pools:
            pools.append(hint)
        for pool in pools:
            s = load_series(pool, mint, t.get("symbol") or cohort.get(mint, {}).get("symbol"), supply)
            if s is None:
                continue
            if best is None or len(s) > len(best):
                best = s
        if best is not None and len(best) >= min_candles:
            seen.add(mint)
            out.append(best)
    return out


def _f(x: Any) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None



def cmd_label(args: argparse.Namespace) -> None:
    series = cohort_series()
    STATE.mkdir(parents=True, exist_ok=True)
    LABELS.write_text("")
    rows, rips = [], 0
    for s in series:
        rip = find_rip(s)
        peak = max(s.close)
        peak_i = s.close.index(peak)
        row = {
            "mint": s.mint,
            "pool": s.pool,
            "symbol": s.symbol,
            "n_hours": len(s),
            "t_event_start": s.t[0],
            "t_event_end": s.t[-1],
            "supply": s.supply,
            "peak_mcap": s.mcap(peak_i),
            "final_mcap": s.mcap(len(s) - 1),
            "drawdown_from_peak": s.close[-1] / peak - 1.0 if peak else None,
            "total_volume_usd": sum(s.vol),
            "rip": rip,
        }
        rips += 1 if rip else 0
        rows.append(row)
    emit(LABELS, rows)
    print(f"labelled {len(rows)} series, {rips} with a mechanical rip ({rips / max(1, len(rows)):.1%})")


# ---------------------------------------------------------------------------------------
# S1/S2 — the in-flight feature set
# ---------------------------------------------------------------------------------------
#
# Everything below uses ONLY data at or before hour `i`. That is the difference between a
# detector and a post-mortem, and it is enforced structurally (the functions take a right
# edge and never see past it) rather than by discipline.

# ---------------------------------------------------------------------------------------
# The panel: every (coin, hour) state with its features, its label, and its lead time
# ---------------------------------------------------------------------------------------


@dataclass
class Coin:
    series: Series
    rip: dict | None
    feats: list[dict]
    peak_mcap: float | None

    @property
    def mint(self) -> str:
        return self.series.mint


#: Coins dropped by :func:`build_coins`, with the reason. Written by the last call and read
#: by the reporting commands, because a silently dropped coin is the one that flatters a
#: result. GeckoTerminal caps history at 1000 candles, so a coin that rugged inside its own
#: first two days is **left-truncated**: its rip precedes the first hour we can score, there
#: was never a decision to make, and it must be *counted* rather than quietly excluded.
BUILD_CENSORING: dict[str, Any] = {}


def build_coins(win: int = 48, stride: int = 1, min_peak_mcap: float = BAND_LO,
                min_candles: int = 120) -> list[Coin]:
    """Cohort → per-coin feature paths and mechanical labels.

    ``min_peak_mcap`` is a *sample definition*, not a signal: it restricts the study to the
    operator's band ("shoots to millions"), applied identically to both arms. It uses the
    whole series, which is legitimate for defining who is in the sample and would be a leak
    if it entered the score. It does not.
    """

    out: list[Coin] = []
    drops: dict[str, int] = defaultdict(int)
    truncated: list[dict] = []
    n_series = 0
    for s in cohort_series(min_candles=min_candles):
        n_series += 1
        if s.supply is None:
            drops["no_supply"] += 1
            continue
        peak = max(s.close) * s.supply
        if peak < min_peak_mcap:
            drops["below_band"] += 1
            continue
        rip = find_rip(s)
        feats = []
        for i in range(win, len(s), stride):
            f = features_at(s, i, win=win)
            if f is not None:
                feats.append(f)
        if len(feats) < 24:
            drops["history_too_short"] += 1
            continue
        if rip and feats and rip["i"] < feats[0]["i"]:
            # The cliff happened before our first scorable hour. There was no decision to
            # make and the coin cannot be scored — but it DID rug, so it is recorded here
            # rather than dropped in silence. Every recall figure in this study is therefore
            # conditional on "we could see the coin at all", and this is the count that says
            # by how much.
            drops["rip_left_truncated"] += 1
            truncated.append({"mint": s.mint, "symbol": s.symbol, "pool": s.pool,
                              "peak_mcap": peak, "rip_t_event": rip["t_event"],
                              "hours_of_history": len(s), "rip_i": rip["i"]})
            continue
        out.append(Coin(series=s, rip=rip, feats=feats, peak_mcap=peak))
    BUILD_CENSORING.clear()
    BUILD_CENSORING.update({
        "n_series_considered": n_series, "n_kept": len(out),
        "dropped": dict(drops), "left_truncated_rips": truncated,
        "window_hours": win, "min_peak_mcap": min_peak_mcap, "min_candles": min_candles,
    })
    return out


#: Two pre-registered outcomes, because there are two ways to lose money here and they need
#: different actions.
#:
#:   ``rip``  — an irreversible cliff (:func:`find_rip`). The exit you must make in minutes.
#:             Rare, and the operator's stated target.
#:   ``bleed``— forward return ≤ ``BLEED_DROP`` over the horizon without a cliff. The exit
#:             you can make on Tuesday. Dense enough to measure at this cohort size.
#:
#: Both are declared here rather than chosen after seeing which one worked. Reporting only
#: the one that came out well would be the single most common way a study like this lies.
LABEL_MODES: tuple[str, ...] = ("rip", "bleed")
BLEED_DROP = 0.50


def label_states(coins: Sequence[Coin], horizon_h: int = 24, mode: str = "rip") -> None:
    """Attach the forward label to each state, in place.

    ``rip``: a cliff begins within ``horizon_h`` hours. States *after* a rip has begun are
    dropped entirely — once the coin has ripped there is no exit decision left to make, and
    scoring the corpse would inflate every metric.

    ``bleed``: the price is at or below ``1 - BLEED_DROP`` of its current level ``horizon_h``
    hours from now. Right-censored states (no ``horizon_h`` of future in the series) are
    dropped rather than assumed alive; the count of dropped states is what makes the
    censoring visible instead of silent.
    """

    if mode not in LABEL_MODES:
        raise ValueError(f"unknown label mode {mode!r}; expected one of {LABEL_MODES}")
    for c in coins:
        rip_i = c.rip["i"] if c.rip else None
        cl = c.series.close
        n = len(cl)
        keep = []
        for f in c.feats:
            i = f["i"]
            if rip_i is not None and i > rip_i:
                continue
            f["hours_to_rip"] = (rip_i - i) if rip_i is not None else None
            if mode == "rip":
                f["y"] = 1 if (rip_i is not None and 0 <= rip_i - i <= horizon_h) else 0
            else:
                j = i + horizon_h
                if j >= n:
                    continue  # right-censored: no forward window, so no label
                p0, p1 = cl[i], cl[j]
                if p0 <= 0:
                    continue
                f["y"] = 1 if (p1 / p0 - 1.0) <= -BLEED_DROP else 0
                f["fwd_ret"] = p1 / p0 - 1.0
            keep.append(f)
        c.feats = keep


def auc(scores: Sequence[float], labels: Sequence[int]) -> float | None:
    """Mann–Whitney AUC, ties at ½.

    Vectorised because the nulls call it a few hundred times over tens of thousands of
    states; the pure-Python version made a full evaluation take minutes per cell.
    """

    import numpy as np

    y = np.asarray(labels, dtype=np.int8)
    n1 = int((y == 1).sum())
    n0 = int((y == 0).sum())
    if n1 == 0 or n0 == 0:
        return None
    x = np.asarray(scores, dtype=np.float64)
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    # average ranks within tie groups
    ranks = np.empty(len(xs), dtype=np.float64)
    i = 0
    n = len(xs)
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1] == xs[i]:
            j += 1
        ranks[i : j + 1] = (i + j) / 2.0 + 1.0
        i = j + 1
    out = np.empty(n, dtype=np.float64)
    out[order] = ranks
    rsum = float(out[y == 1].sum())
    return (rsum - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def entity_groups(coins: Sequence[Coin]) -> dict[str, str]:
    """Group coins that are plausibly the *same operator*.

    We do not have funding ancestry for the cohort (that needs signers, which exist only
    for the eleven cluster pools). What we do have is co-timing: a manipulator running a
    stable of coins rips them in bursts, and two coins whose rips land in the same hour are
    far more likely to be one entity than two. So the grouping key is the rip hour bucket —
    a *deliberately conservative* proxy that will over-merge (two unrelated coins caught in
    the same market-wide flush become one entity) and therefore makes every grouped
    confidence interval wider, not narrower. Over-merging is the safe direction.
    """

    groups: dict[str, str] = {}
    for c in coins:
        if c.rip:
            bucket = int(c.rip["t_event"] // (6 * 3600))
            groups[c.mint] = f"riphour:{bucket}"
        else:
            groups[c.mint] = f"solo:{c.mint}"
    return groups


def temporal_split(coins: Sequence[Coin], frac: float = 0.5) -> tuple[list[dict], list[Coin]]:
    """Calibrate on the earlier half of *wall-clock time*, evaluate on the later half.

    The split is on the state's own timestamp, not on the coin, because coins overlap in
    time. Calibration states are strictly earlier than every evaluation state, so no
    quantile the score uses was fitted on a future it is being asked to predict.
    """

    all_t = sorted(f["t_event"] for c in coins for f in c.feats)
    if not all_t:
        return [], []
    cut = all_t[min(len(all_t) - 1, int(frac * len(all_t)))]
    if frac >= 1.0:  # "calibrate on everything" — used by `held`, never by `eval`
        return [f for c in coins for f in c.feats], []
    train = [f for c in coins for f in c.feats if f["t_event"] < cut]
    test: list[Coin] = []
    for c in coins:
        later = [f for f in c.feats if f["t_event"] >= cut]
        if later:
            test.append(Coin(series=c.series, rip=c.rip, feats=later, peak_mcap=c.peak_mcap))
    return train, test


def grouped_cv(coins: Sequence[Coin], folds: int = 5, seed: int = 23) -> list[Coin]:
    """Entity-grouped K-fold: every coin is scored by a calibration fitted without it.

    The temporal split is the stricter design and it is still reported, but at this cohort
    size it is *underpowered in a specific and disqualifying way*: the cliffs are not
    uniform in time (four of them land inside three days), so a 50/50 split on state time
    strands almost all of them in the calibration half and leaves one positive coin in the
    test half. An AUC computed against one positive coin is that coin's fingerprint, not a
    skill measurement, and reporting it as skill would be the error this whole document is
    trying to avoid.

    Grouped CV keeps the thing that actually matters — **no coin contributes to its own
    calibration** — while using every coin as a test case. What it gives up is the temporal
    guarantee: a fold's calibration can contain states from *later* than the states it
    scores. That is a real weakness and it is why both are run. The calibration is a set of
    marginal quantiles over ~10⁵ ambient states, so the leak it admits is a slow-moving
    regime level rather than anything about the coin being scored.

    Folds are assigned by a hash of the mint, so the assignment is stable across runs and
    across cohort growth — a coin does not change fold when the collector adds another.
    """

    import copy
    import hashlib

    out: list[Coin] = []
    fold_of = {c.mint: int(hashlib.sha256(f"{seed}|{c.mint}".encode()).hexdigest(), 16) % folds
               for c in coins}
    for f in range(folds):
        train = [feat for c in coins if fold_of[c.mint] != f for feat in c.feats]
        if not train:
            continue
        cal = Calibration.fit(train, FEATURE_KEYS)
        for c in coins:
            if fold_of[c.mint] != f:
                continue
            held = Coin(series=c.series, rip=c.rip, feats=copy.deepcopy(c.feats),
                        peak_mcap=c.peak_mcap)
            score_coins([held], cal)
            for feat in held.feats:
                feat["fold"] = f
                feat["calibration_n"] = cal.n
            out.append(held)
    return out


# ---------------------------------------------------------------------------------------
# POST-HOC, and labelled as such wherever it appears
# ---------------------------------------------------------------------------------------
#
# This feature was not pre-registered. It came from reading the per-coin traces after the
# pre-registered grid had already been run and had already failed to show lead time, and
# every number attached to it inherits that status: it is a lead, not a result, and it is
# reported next to the count of things that were tried.
#
# What the traces showed, on the one coin the taxonomy called a METERED_CLIMB: `r2_linear`
# ran at 0.90–0.92 twenty-four to thirty-six hours before the cliff and had collapsed to
# 0.03 six hours before it. The crawl does not rip *while* it is linear. It stops being
# linear, and then it rips — which is what you would expect if the controller stops
# supporting the schedule before pulling, and is invisible to any feature that only looks at
# the current window.
#
# So the candidate is a SECOND DIFFERENCE, not a level: was this a schedule, and has the
# schedule just stopped? Both halves are causal — the lag is into the past.

BREAKDOWN_LAG_H = 24


def add_breakdown(coins: Sequence[Coin], lag_h: int = BREAKDOWN_LAG_H) -> None:
    """Attach ``r2_breakdown`` = (past linearity) × (loss of linearity since). In place.

    Multiplicative rather than additive so that both halves must hold: a coin that was never
    linear scores zero however much its (absent) linearity decays, and a coin still tracking
    its schedule scores zero however linear it is.
    """

    for c in coins:
        by_i = {f["i"]: f for f in c.feats}
        for f in c.feats:
            past = by_i.get(f["i"] - lag_h)
            if past is None:
                f["r2_breakdown"] = None
                f["r2_breakdown_log"] = None
                continue
            f["r2_breakdown"] = past["r2_linear"] * max(0.0, past["r2_linear"] - f["r2_linear"])
            f["r2_breakdown_log"] = past["r2_log"] * max(0.0, past["r2_log"] - f["r2_log"])


# ---------------------------------------------------------------------------------------
# The control that decides whether a drawdown result is real
# ---------------------------------------------------------------------------------------
#
# This is the most reusable thing in the module and it should be run against ANY future
# result on this panel that predicts a fixed-percentage drawdown.
#
# `rv_hourly` scores AUC 0.926 against "price is at least 50% lower in 72 hours", surviving a
# BY-FDR correction over 22 tests. That number is worthless, and the reason is arithmetic: a
# high-volatility coin is mechanically more likely to move 50% **in either direction**, and a
# one-sided fixed threshold counts only one of them. The feature is being rewarded for
# magnitude while the claim being made is about direction.
#
# The discriminating test is to ask the directional question instead: standardise the
# threshold by the coin's own volatility, so the label means "moved down further than this
# coin's own noise explains" rather than "moved down 50%". Measured: **0.893 → 0.302**, and
# the sign flips. Conditional on its own volatility, a high-`rv` coin is *less* likely than
# average to make a large downward excursion.


def cmd_vol_control(args: argparse.Namespace) -> None:
    """Re-measure a drawdown result against a volatility-standardised label."""

    coins = build_coins(win=args.win, min_peak_mcap=args.min_mcap, stride=args.stride)
    print(f"cohort: {len(coins)} coins, horizon {args.horizon}h\n")
    print(f"  {'label':22s} {'positives':>10s} {'base':>8s} "
          + "".join(f"{k[:12]:>14s}" for k in args.features))
    rows = []
    for standardise, k in [(False, args.drop)] + [(True, kk) for kk in args.k]:
        n_pos = 0
        n_tot = 0
        cols: dict[str, list[tuple[float, int]]] = {f: [] for f in args.features}
        for c in coins:
            cl = c.series.close
            n = len(cl)
            for f in c.feats:
                i = f["i"]
                j = i + args.horizon
                if j >= n or cl[i] <= 0 or cl[j] <= 0:
                    continue
                r = math.log(cl[j] / cl[i])
                if standardise:
                    rv = f.get("rv_hourly") or 0.0
                    if rv <= 0:
                        continue
                    thr = -k * rv * math.sqrt(args.horizon)
                else:
                    thr = math.log(1.0 - k)
                y = 1 if r <= thr else 0
                n_pos += y
                n_tot += 1
                for key in args.features:
                    v = f.get(key)
                    if isinstance(v, (int, float)) and math.isfinite(v):
                        cols[key].append((float(v), y))
        aucs = {}
        for key in args.features:
            pairs = cols[key]
            aucs[key] = auc([p[0] for p in pairs], [p[1] for p in pairs]) if pairs else None
        tag = f"standardised k={k}" if standardise else f"fixed -{k:.0%}"
        rows.append({"label": tag, "standardised": standardise, "k": k,
                     "positives": n_pos, "n": n_tot,
                     "base_rate": n_pos / max(1, n_tot), "auc": aucs})
        print(f"  {tag:22s} {n_pos:10d} {n_pos / max(1, n_tot):8.4f} "
              + "".join(f"{aucs[key]:14.3f}" if aucs[key] is not None else f"{'-':>14s}"
                        for key in args.features))
    out = STATE / "vol_control.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"t_ingest": _now(), "horizon_h": args.horizon,
                               "win": args.win, "rows": rows}, indent=1, default=str))
    print(f"\nwrote {out}")


def cmd_breakdown(args: argparse.Namespace) -> None:
    """Evaluate the post-hoc breakdown feature against the same nulls as everything else."""

    from studies.callout_edge import cluster_bootstrap_auc

    coins = build_coins(win=args.win, min_peak_mcap=args.min_mcap)
    print(f"cohort: {len(coins)} coins, {sum(1 for c in coins if c.rip)} with a cliff, "
          f"{len(BUILD_CENSORING['left_truncated_rips'])} left-truncated")
    print("\n*** POST-HOC. Not in the pre-registered family. Read as a lead. ***")
    out: dict[str, Any] = {"t_ingest": _now(), "post_hoc": True, "win": args.win,
                           "lag_h": args.lag, "cells": []}
    for mode in LABEL_MODES:
        for horizon in HORIZONS:
            import copy

            cc = [Coin(series=c.series, rip=c.rip, feats=copy.deepcopy(c.feats),
                       peak_mcap=c.peak_mcap) for c in coins]
            label_states(cc, horizon_h=horizon, mode=mode)
            add_breakdown(cc, lag_h=args.lag)
            for key in ("r2_breakdown", "r2_breakdown_log", "r2_linear"):
                s, y, g = _flat(cc, key=key)
                a = auc(s, y)
                if a is None:
                    continue
                lo, hi = cluster_bootstrap_auc(y, s, g, draws=400, seed=13)
                # rotation null on the feature itself, not on the composite
                for c2 in cc:
                    for f in c2.feats:
                        f["crime_score"] = f.get(key)
                rot = rotation_null(cc, Calibration(), horizon, reps=100)
                swp = mint_swap_null(cc, reps=100)
                ceil = max([b["p95"] for b in (rot, swp) if b] or [float("nan")])
                row = {"label_mode": mode, "horizon_h": horizon, "feature": key,
                       "auc": a, "ci95": [lo, hi], "n_states": len(s), "n_positive": int(sum(y)),
                       "rotation_p95": rot.get("p95"), "mint_swap_p95": swp.get("p95"),
                       "null_ceiling": ceil,
                       "beats_all_nulls": bool(a > ceil) if ceil == ceil else None}
                out["cells"].append(row)
                print(f"  {mode:6s} h{horizon:<3d} {key:18s} AUC {a:.3f} CI[{lo:.3f},{hi:.3f}] "
                      f"nulls<= {ceil:.3f}  {'BEATS' if row['beats_all_nulls'] else '.'}"
                      f"  (n+={int(sum(y))})")
    out["trials_this_command"] = len(out["cells"])
    p = STATE / "breakdown.json"
    p.write_text(json.dumps(out, indent=1, default=str))
    print(f"\ntrials in this post-hoc command: {out['trials_this_command']}")
    print(f"wrote {p}")


def score_coins(coins: Sequence[Coin], cal: Calibration) -> None:
    for c in coins:
        for f in c.feats:
            r = crime_score(f, cal)
            f["crime_score"] = r["score"]
            f["parts"] = r["parts"]


def lead_times(coins: Sequence[Coin], threshold: float) -> list[dict]:
    """For every ripped coin, minutes between the first crossing and the last pre-rip hour.

    A crossing that never happens is reported as a miss, not dropped. A crossing that
    happens *after* the rip cannot happen by construction (post-rip states are removed), so
    every number here is a genuine warning, never a hindsight one.
    """

    out = []
    for c in coins:
        if not c.rip:
            continue
        first = None
        for f in c.feats:
            s = f.get("crime_score")
            if s is not None and s >= threshold:
                first = f
                break
        if first is None:
            out.append({"mint": c.mint, "symbol": c.series.symbol, "warned": False,
                        "lead_minutes": None, "peak_mcap": c.peak_mcap})
            continue
        lead_h = (c.rip["t_event"] - first["t_event"]) / HOUR
        out.append({
            "mint": c.mint, "symbol": c.series.symbol, "warned": True,
            "lead_minutes": lead_h * 60.0,
            "score_at_warning": first["crime_score"],
            "price_at_warning": first["price"],
            "price_at_rip_ref": c.rip["ref_price"],
            "price_at_trough": c.rip["trough_price"],
            "mcap_at_warning": first["mcap"],
            "peak_mcap": c.peak_mcap,
            # What the warning was *worth*: exiting at the warning vs riding to the trough.
            "exit_vs_trough": (first["price"] / c.rip["trough_price"] - 1.0) if c.rip["trough_price"] else None,
            "exit_vs_ref": (first["price"] / c.rip["ref_price"] - 1.0) if c.rip["ref_price"] else None,
        })
    return out


def _summ(xs: Sequence[float]) -> dict:
    xs = sorted(x for x in xs if x is not None and math.isfinite(x))
    if not xs:
        return {}
    def q(p: float) -> float:
        return xs[min(len(xs) - 1, int(p * len(xs)))]
    return {"n": len(xs), "min": xs[0], "p10": q(0.1), "p25": q(0.25), "median": q(0.5),
            "p75": q(0.75), "p90": q(0.9), "max": xs[-1], "mean": sum(xs) / len(xs)}


def rotation_null(coins: Sequence[Coin], cal: Calibration, horizon_h: int, reps: int = 200,
                  seed: int = 11) -> dict:
    """Circularly rotate each coin's score path against its own labels.

    This destroys the *timing* relationship while preserving every marginal distribution:
    the same scores, the same labels, the same autocorrelation, the same cohort. If the
    detector's AUC sits inside this band it has learned "crimed coins look different on
    average", which is an avoid-filter, not an exit signal. Outside it, the score knows
    *when*.
    """

    import random

    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        scores, labels = [], []
        for c in coins:
            ss = [f.get("crime_score") for f in c.feats]
            ys = [f.get("y") for f in c.feats]
            if len(ss) < 4:
                continue
            k = rng.randrange(len(ss))
            rot = ss[k:] + ss[:k]
            for s, y in zip(rot, ys, strict=True):
                if s is not None and y is not None:
                    scores.append(s)
                    labels.append(y)
        a = auc(scores, labels)
        if a is not None:
            vals.append(a)
    if not vals:
        return {}
    vals.sort()
    return {"reps": len(vals), "p05": vals[int(0.05 * len(vals))], "median": vals[len(vals) // 2],
            "p95": vals[int(0.95 * len(vals))], "max": vals[-1]}


def mint_swap_null(coins: Sequence[Coin], reps: int = 200, seed: int = 17) -> dict:
    """Give coin A's score path to coin B's labels.

    Rotation asks "does the score know *when*". This asks "does it know *which coin*". A
    detector that beats rotation but not this one has learned a cohort-level fact ("crimed
    coins have lower turnover") rather than a coin-level one — which is still a useful
    avoid-filter, but it is not an exit signal, and the two must not be sold as each other.
    The house rule (``studies/exploration_map.py``) is that a result must beat *every*
    applicable null, not the friendliest, so the decision uses the max of the two bands.
    """

    import random

    rng = random.Random(seed)
    usable = [c for c in coins if any(f.get("crime_score") is not None for f in c.feats)]
    if len(usable) < 4:
        return {}
    vals = []
    for _ in range(reps):
        perm = list(range(len(usable)))
        rng.shuffle(perm)
        scores, labels = [], []
        for k, c in enumerate(usable):
            donor = usable[perm[k]]
            if donor is c:
                continue
            ds = [f.get("crime_score") for f in donor.feats if f.get("crime_score") is not None]
            if not ds:
                continue
            for j, f in enumerate(c.feats):
                y = f.get("y")
                if y is None:
                    continue
                scores.append(ds[j % len(ds)])
                labels.append(int(y))
        a = auc(scores, labels)
        if a is not None:
            vals.append(a)
    if not vals:
        return {}
    vals.sort()
    return {"reps": len(vals), "p05": vals[int(0.05 * len(vals))], "median": vals[len(vals) // 2],
            "p95": vals[int(0.95 * len(vals))], "max": vals[-1]}


def stratified_auc(coins: Sequence[Coin], by: str = "turnover", bins: int = 5) -> dict:
    """AUC of the score *within* strata of a confounder.

    The obvious alternative explanation for anything measured here is that the score is an
    elaborate way of saying "low turnover", and low-turnover coins die. Stratifying on
    turnover and re-measuring inside each stratum is the discriminating test: if the score
    separates only *across* strata, it is the confounder talking.
    """

    rows = [(f.get(by), f.get("crime_score"), f.get("y")) for c in coins for f in c.feats]
    rows = [r for r in rows
            if all(x is not None for x in r) and isinstance(r[0], (int, float)) and math.isfinite(r[0])]
    if len(rows) < 100:
        return {}
    rows.sort(key=lambda r: r[0])
    out: dict[str, Any] = {"by": by, "bins": bins, "strata": []}
    for b in range(bins):
        sl = rows[int(b * len(rows) / bins) : int((b + 1) * len(rows) / bins)]
        if not sl:
            continue
        a = auc([r[1] for r in sl], [int(r[2]) for r in sl])
        out["strata"].append({
            "bin": b, "n": len(sl), "lo": sl[0][0], "hi": sl[-1][0],
            "base_rate": sum(int(r[2]) for r in sl) / len(sl), "auc": a,
        })
    aucs = [s["auc"] for s in out["strata"] if s["auc"] is not None]
    out["min_auc"] = min(aucs) if aucs else None
    out["mean_auc"] = sum(aucs) / len(aucs) if aucs else None
    return out


def competing_risks(coins: Sequence[Coin], threshold: float, horizon_h: int = 72) -> dict:
    """Cumulative incidence of *rip* against the competing end — a quiet fade.

    A coin can stop being worth holding two ways, and they need different actions. A rip is
    an exit you must make in minutes; a fade is one you can make on Tuesday. Treating a fade
    as censoring would overstate the rip hazard, which is the standard error in this
    literature, so the two are estimated as competing events (Aalen–Johansen) rather than as
    one Kaplan–Meier per cause.

    Falls back to a counted-incidence table when ``lifelines`` is unavailable, and says so.
    """

    entries = []
    for c in coins:
        armed = [f for f in c.feats if (f.get("crime_score") or 0) >= threshold]
        if not armed:
            continue
        f0 = armed[0]
        i0 = f0["i"]
        n = len(c.series)
        if c.rip and c.rip["i"] >= i0:
            entries.append((min(horizon_h, c.rip["i"] - i0), 1, c.mint))
            continue
        # a fade: price at the horizon is under half, without a rip
        j = min(n - 1, i0 + horizon_h)
        p0, p1 = c.series.close[i0], c.series.close[j]
        if p0 > 0 and p1 / p0 <= 0.5:
            entries.append((j - i0, 2, c.mint))
        else:
            entries.append((j - i0, 0, c.mint))
    if not entries:
        return {}
    out: dict[str, Any] = {
        "threshold": threshold, "horizon_h": horizon_h, "n_armed_coins": len(entries),
        "counts": {"rip": sum(1 for e in entries if e[1] == 1),
                   "fade": sum(1 for e in entries if e[1] == 2),
                   "neither": sum(1 for e in entries if e[1] == 0)},
    }
    try:
        import numpy as np
        from lifelines import AalenJohansenFitter

        durations = np.array([max(1e-6, e[0]) for e in entries], dtype=float)
        events = np.array([e[1] for e in entries], dtype=int)
        for cause, name in ((1, "rip"), (2, "fade")):
            if not (events == cause).any():
                continue
            ajf = AalenJohansenFitter(calculate_variance=False, seed=3)
            ajf.fit(durations, events, event_of_interest=cause)
            cif = ajf.cumulative_density_
            col = cif.columns[0]
            grid = {}
            for t in (6, 12, 24, 48, 72):
                sel = cif.index[cif.index <= t]
                grid[str(t)] = float(cif.loc[sel[-1], col]) if len(sel) else 0.0
            out[f"cif_{name}"] = grid
    except Exception as exc:
        out["cif_error"] = repr(exc)
    return out


# ---------------------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------------------
#
# TRIALS COUNTED, declared before the run (PROGRAM.md §3):
#   * 11 univariate feature AUCs (FEATURE_KEYS) — one family, BY-corrected;
#   * 1 composite score AUC — the pre-registered primary;
#   * 3 horizons (6h, 24h, 72h) — reported, with the 24h horizon as primary;
#   * 3 operating thresholds for the lead-time table (0.70, 0.80, 0.90).
# Nothing else is searched. The score's weights are NOT fitted: it is an unweighted mean of
# five percentile ranks, chosen from the operator's description before any number was seen.
# That is deliberate — a fitted weight vector over 11 features and ~40 ripped coins would
# be the exact overfit `RESULT_bandit_search.md` already paid for.

HORIZONS: tuple[int, ...] = (6, 24, 72)
OPERATING: tuple[float, ...] = (0.70, 0.80, 0.90)


def _flat(coins: Sequence[Coin], key: str = "crime_score") -> tuple[list[float], list[int], list[str]]:
    scores, labels, groups = [], [], []
    grp = entity_groups(coins)
    for c in coins:
        for f in c.feats:
            v = f.get(key)
            y = f.get("y")
            if v is None or y is None or not isinstance(v, (int, float)) or not math.isfinite(v):
                continue
            scores.append(float(v))
            labels.append(int(y))
            groups.append(grp[c.mint])
    return scores, labels, groups


def evaluate_block(coins_all: Sequence[Coin], mode: str, horizon: int,
                   *, train_frac: float, split: str = "grouped", verbose: bool = True,
                   reps: int = 120, draws: int = 400) -> dict:
    """One (label mode, horizon, split) cell of the pre-registered grid."""

    import copy

    from studies.callout_edge import cluster_bootstrap_auc

    # Rebuild from the in-memory snapshot, never from disk: the collector may still be
    # appending, and a cohort that changes between cells is not a comparison.
    coins = [Coin(series=c.series, rip=c.rip, feats=copy.deepcopy(c.feats), peak_mcap=c.peak_mcap)
             for c in coins_all]
    label_states(coins, horizon_h=horizon, mode=mode)
    n_rip = sum(1 for c in coins if c.rip)

    if split == "temporal":
        train_states, test = temporal_split(coins, frac=train_frac)
        if not train_states or not test:
            return {"label_mode": mode, "horizon_h": horizon, "split": split, "error": "empty_split"}
        cal = Calibration.fit(train_states, FEATURE_KEYS)
        score_coins(test, cal)
    else:
        test = grouped_cv(coins)
        if not test:
            return {"label_mode": mode, "horizon_h": horizon, "split": split, "error": "empty_split"}
        cal = Calibration.fit([f for c in coins for f in c.feats], FEATURE_KEYS)
    scores, labels, groups = _flat(test)
    if not scores:
        return {"label_mode": mode, "horizon_h": horizon, "split": split, "error": "no_scored_states"}

    a = auc(scores, labels)
    lo, hi = cluster_bootstrap_auc(labels, scores, groups, draws=draws, seed=11) if a is not None else (None, None)
    null = rotation_null(test, cal, horizon, reps=reps)
    swap = mint_swap_null(test, reps=reps)
    # House rule: beat EVERY applicable null, not the friendliest one.
    ceilings = [b["p95"] for b in (null, swap) if b]
    null_ceiling = max(ceilings) if ceilings else None

    block: dict[str, Any] = {
        "label_mode": mode, "horizon_h": horizon, "split": split,
        "n_coins": len(coins), "n_ripped": n_rip,
        "n_test_coins": len(test), "n_test_states": len(scores),
        "n_positive": sum(labels),
        "base_rate": sum(labels) / len(labels),
        "auc": a, "auc_ci95": [lo, hi],
        "rotation_null": null, "mint_swap_null": swap,
        "null_ceiling_p95": null_ceiling,
        "beats_all_nulls": bool(a is not None and null_ceiling is not None and a > null_ceiling),
        "stratified_by_turnover": stratified_auc(test, by="turnover", bins=5),
        "calibration": {"n_states": cal.n, "t_first": cal.t_first, "t_last": cal.t_last},
    }
    if horizon == 24:
        block["competing_risks"] = {f"{t:.2f}": competing_risks(test, t) for t in OPERATING}

    uni = {}
    for k in FEATURE_KEYS:
        ks, ky, kg = _flat(test, key=k)
        ak = auc(ks, ky)
        if ak is None:
            continue
        klo, khi = cluster_bootstrap_auc(ky, ks, kg, draws=max(150, draws // 2), seed=13)
        uni[k] = {"auc": ak, "ci95": [klo, khi], "separates": bool(klo > 0.5 or khi < 0.5)}
    block["univariate"] = uni

    block["lead_times"] = {}
    for thr in OPERATING:
        lt = lead_times(test, thr)
        warned = [r for r in lt if r["warned"]]
        n_alert = sum(1 for x in scores if x >= thr)
        block["lead_times"][f"{thr:.2f}"] = {
            "n_ripped_in_test": len(lt), "n_warned": len(warned),
            "recall_coins": len(warned) / len(lt) if lt else None,
            "lead_minutes": _summ([r["lead_minutes"] for r in warned]),
            "exit_vs_trough": _summ([r["exit_vs_trough"] for r in warned if r.get("exit_vs_trough") is not None]),
            "alert_rate": n_alert / len(scores),
            "precision": (sum(1 for x, y in zip(scores, labels, strict=True) if x >= thr and y == 1) / n_alert) if n_alert else None,
            "recall_states": (sum(1 for x, y in zip(scores, labels, strict=True) if x >= thr and y == 1) / max(1, sum(labels))),
        }

    order = sorted(range(len(scores)), key=lambda k: scores[k])
    dec = []
    for d in range(10):
        sl = order[int(d * len(order) / 10) : int((d + 1) * len(order) / 10)]
        if not sl:
            continue
        dec.append({"decile": d, "n": len(sl), "score_lo": scores[sl[0]], "score_hi": scores[sl[-1]],
                    "hazard": sum(labels[i] for i in sl) / len(sl)})
    block["deciles"] = dec

    if verbose:
        print(f"\n=== label={mode} horizon={horizon}h split={split} ===")
        print(f"  coins {len(coins)} ({n_rip} with a cliff) | test coins {len(test)} | "
              f"states {len(scores)} | positives {sum(labels)} | base rate {block['base_rate']:.4f}")
        if a is not None:
            print(f"  AUC {a:.3f}  CI95 [{lo:.3f}, {hi:.3f}]")
        else:
            print("  AUC n/a (no positives in the test split)")
        if null:
            print(f"  rotation null : p05 {null['p05']:.3f} med {null['median']:.3f} p95 {null['p95']:.3f}")
        if swap:
            print(f"  mint-swap null: p05 {swap['p05']:.3f} med {swap['median']:.3f} p95 {swap['p95']:.3f}")
        if null_ceiling is not None:
            print(f"  beats every null: {block['beats_all_nulls']}  (ceiling {null_ceiling:.3f})")
        st = block["stratified_by_turnover"]
        if st.get("strata"):
            cells = " ".join(f"{s['auc']:.3f}" if s["auc"] is not None else "  -  " for s in st["strata"])
            mn = st.get("min_auc")
            print(f"  within turnover quintiles: {cells}" + (f"   min {mn:.3f}" if mn is not None else ""))
        for thr in OPERATING:
            b = block["lead_times"][f"{thr:.2f}"]
            lm = b["lead_minutes"] or {}
            med = lm.get("median")
            p10 = lm.get("p10")
            prec = b["precision"]
            print(f"  thr {thr:.2f}: alert-rate {b['alert_rate']:.4f} "
                  f"prec {prec:.4f}" % () if prec is not None else "", end="")
            print(f"  coin-recall {b['recall_coins'] if b['recall_coins'] is not None else float('nan'):.2f} "
                  f"({b['n_warned']}/{b['n_ripped_in_test']})"
                  + (f"  lead med {med / 60:.1f}h p10 {p10 / 60:.1f}h" if med is not None else "  lead n/a"))
    return block


def cmd_eval(args: argparse.Namespace) -> None:
    # `stride` thins the panel. Hourly states of one coin are heavily autocorrelated — they
    # are not independent observations and the entity bootstrap already treats them as one
    # coin — so evaluating every `stride`-th hour costs almost no information and makes the
    # null bands (which re-score the whole panel a few hundred times) affordable. It does not
    # quantise lead time to better than `stride` hours, which is why the window sweep — where
    # lead time is the whole point — runs at stride 1.
    coins_all = build_coins(win=args.win, min_peak_mcap=args.min_mcap, stride=args.stride)
    print(f"cohort: {len(coins_all)} coins with >= ${args.min_mcap:,.0f} peak mcap and a usable history")
    print(f"        {sum(1 for c in coins_all if c.rip)} carry a mechanical cliff")
    print(f"        censoring: {json.dumps(BUILD_CENSORING['dropped'])}")
    if BUILD_CENSORING["left_truncated_rips"]:
        print(f"        {len(BUILD_CENSORING['left_truncated_rips'])} coins rugged BEFORE our first "
              f"scorable hour and are excluded from every recall figure below:")
        for t in BUILD_CENSORING["left_truncated_rips"]:
            print(f"          {(t['symbol'] or '?')[:14]:14s} peak ${t['peak_mcap']:,.0f} "
                  f"rip at hour {t['rip_i']} of {t['hours_of_history']}")
    report: dict[str, Any] = {
        "run_id": new_run_id(), "t_ingest": _now(), "win": args.win,
        "min_peak_mcap": args.min_mcap, "n_coins": len(coins_all),
        "n_with_cliff": sum(1 for c in coins_all if c.rip),
        "censoring": dict(BUILD_CENSORING),
        "trials_declared": {
            "univariate_features": len(FEATURE_KEYS), "composite": 1,
            "horizons": len(HORIZONS), "operating_thresholds": len(OPERATING),
            "label_modes": len(LABEL_MODES), "splits": len(args.splits),
            "cells": len(HORIZONS) * len(LABEL_MODES) * len(args.splits),
        },
    }
    for split in args.splits:
        for mode in LABEL_MODES:
            for horizon in HORIZONS:
                report[f"{split}_{mode}_h{horizon}"] = evaluate_block(
                    coins_all, mode, horizon, train_frac=args.train_frac, split=split,
                    reps=args.reps, draws=args.draws)

    # BY-FDR over the univariate family. The family is the 11 features x 2 label modes at
    # the primary horizon; BY rather than BH because overlapping features on one panel are
    # dependent in an unknown direction (PROGRAM.md §3.9).
    fam: list[tuple[str, float, float, float]] = []
    for mode in LABEL_MODES:
        uni = (report.get(f"{args.splits[0]}_{mode}_h24") or {}).get("univariate") or {}
        for k, v in uni.items():
            klo, khi = v["ci95"]
            se = (khi - klo) / (2 * 1.96) if (khi is not None and klo is not None and khi > klo) else None
            pv = math.erfc(abs(v["auc"] - 0.5) / se / math.sqrt(2)) if se else 1.0
            fam.append((f"{mode}:{k}", v["auc"], pv, se or float("nan")))
    if fam:
        try:
            from studies.exploration_map import benjamini_yekutieli

            qv, rej, c_m = benjamini_yekutieli([f[2] for f in fam], q=0.10)
            report["by_fdr"] = {
                "q": 0.10, "c_m": float(c_m), "family_size": len(fam),
                "features": {fam[i][0]: {"auc": fam[i][1], "p": fam[i][2],
                                         "q": float(qv[i]), "rejected": bool(rej[i])}
                             for i in range(len(fam))},
            }
            print(f"\n=== BY-FDR (q=0.10, c_m={c_m:.3f}) over {len(fam)} univariate tests, horizon 24h ===")
            for i, (name, a_, p_, _se) in enumerate(fam):
                print(f"  {name:30s} AUC {a_:.3f}  p={p_:.4g}  q={qv[i]:.4g}  "
                      f"{'REJECT-NULL' if rej[i] else '.'}")
        except Exception as exc:
            report["by_fdr"] = {"error": repr(exc)}
            print(f"\nBY-FDR unavailable: {exc!r}")

    out = STATE / "eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str))
    print(f"\nwrote {out}")



# ---------------------------------------------------------------------------------------
# The acid test: the operator's own four coins
# ---------------------------------------------------------------------------------------
#
# If the detector flags a coin the operator holds, that is a FINDING and it is reported
# here in full, not suppressed. The four are scored on exactly the same code path as every
# cohort coin, against a calibration fitted on the cohort and never on them.

HELD: tuple[tuple[str, str, str], ...] = (
    ("weave", "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump", "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn"),
    ("nosis", "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump", "7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc"),
    ("DREGG", "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump", "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU"),
    ("SOLVE", "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump", "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr"),
)

#: pump.fun mints a fixed 1e9 supply. Used only when GT has no `normalized_total_supply`
#: for a cluster token; the resulting mcap is a scale, and every score component that uses
#: it (`turnover`) is a *ratio*, so a wrong constant would cancel — but it is recorded so
#: the number can be checked rather than trusted.
PUMP_SUPPLY = 1_000_000_000.0


def cmd_held(args: argparse.Namespace) -> None:
    coins = build_coins(win=args.win, min_peak_mcap=0.0)
    train_states, _ = temporal_split(coins, frac=args.train_frac)
    cal = Calibration.fit(train_states or [f for c in coins for f in c.feats], FEATURE_KEYS)
    print(f"calibration: {cal.n} cohort states, {len(coins)} coins\n")

    tokens = _known_tokens()
    run_id = new_run_id()
    rows: list[dict] = []
    for label, mint, pool in HELD:
        supply = _f((tokens.get(mint) or {}).get("total_supply")) or PUMP_SUPPLY
        s = load_series(pool, mint, label, supply)
        if s is None:
            rows.append(defect_row(run_id=run_id, mint=mint, reason="no_ohlcv_cached", detail=pool))
            print(f"{label:6s} DEFECT no cached OHLCV for {pool}")
            continue
        feats = [f for f in (features_at(s, i, win=args.win) for i in range(args.win, len(s))) if f]
        if not feats:
            rows.append(defect_row(run_id=run_id, mint=mint, reason="history_shorter_than_window", detail=len(s)))
            continue
        for f in feats:
            r = crime_score(f, cal)
            f["crime_score"] = r["score"]
            f["parts"] = r["parts"]
        rip = find_rip(s)
        scored = [f["crime_score"] for f in feats if f["crime_score"] is not None]
        latest = feats[-1]
        peak = max(scored) if scored else None
        peak_f = max(feats, key=lambda f: f["crime_score"] or -1)
        print(f"=== {label} ({mint[:8]}…) {len(s)}h of history ===")
        print(f"  latest score {latest['crime_score']:.3f} at mcap ${latest['mcap'] or 0:,.0f}"
              f"  (r2_linear {latest['r2_linear']:.2f}, disp/turnover {latest['disp_per_turnover'] or float('nan'):.2f},"
              f" turnover48h {latest['turnover'] or float('nan'):.4f}, dead-hours {latest['dead_hour_frac']:.2f})")
        print(f"  peak score   {peak:.3f} at {time.strftime('%Y-%m-%d %H:%M', time.gmtime(peak_f['t_event']))}")
        print(f"  hours over 0.80: {sum(1 for x in scored if x >= 0.80)}/{len(scored)}"
              f"   over 0.70: {sum(1 for x in scored if x >= 0.70)}/{len(scored)}")
        print(f"  mechanical rip in history: {'YES ' + time.strftime('%Y-%m-%d %H:%M', time.gmtime(rip['t_event'])) if rip else 'no'}")
        rows.append(alert_row(run_id=run_id, mint=mint, symbol=label, pool=pool, feat=latest,
                              threshold=args.threshold, cal=cal, arm="held"))
        rows.append({"schema": "crime.v1", "kind": "held_summary", "run_id": run_id, "mint": mint,
                     "symbol": label, "t_ingest": _now(), "t_event": latest["t_event"],
                     "t_event_source": "vendor:geckoterminal.ohlcv.hour",
                     "n_hours": len(s), "latest_score": latest["crime_score"], "peak_score": peak,
                     "peak_score_t_event": peak_f["t_event"],
                     "hours_over_080": sum(1 for x in scored if x >= 0.80),
                     "hours_scored": len(scored), "rip": rip, "supply_source":
                     "gt.normalized_total_supply" if _f((tokens.get(mint) or {}).get("total_supply")) else "assumed:pump_fixed_1e9"})
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    emit(ALERTS, rows)
    print(f"\nwrote {len(rows)} rows to {ALERTS}")


# ---------------------------------------------------------------------------------------
# S3 — concentration and choreography, measured where signers exist
# ---------------------------------------------------------------------------------------
#
# Scope statement, first, because this is the section most likely to be over-read: the
# cluster tape carries signers for eleven pools and nothing else does. Everything below is
# a measurement of *those eleven pools*. It is not a cohort feature, it does not enter the
# crime score, and no threshold derived here is claimed to generalise. What it is good for
# is the third deliverable — a taxonomy of what a manipulated tape looks like at swap
# resolution — and as a template for the day the tape is wide enough to score on.

CLUSTER_TAPE = ROOT / "state" / "cluster_tape" / "swaps"


def _load_cluster_swaps() -> dict[str, list[dict]]:
    by_pool: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(CLUSTER_TAPE.glob("*.jsonl")):
        with path.open() as fh:
            for line in fh:
                if '"swap"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("kind") != "swap":
                    continue
                by_pool[row["pool"]].append(row)
    for pool in by_pool:
        by_pool[pool].sort(key=lambda r: (r.get("chain") or {}).get("block_time") or 0)
    return by_pool


def _swap_size(r: dict) -> float:
    """Trade size in the pool's *quote* leg, from the exact vault deltas.

    The tape's ``swap_legs`` is a count, not a list — the amounts live in
    ``reserves.vaults[*].delta_raw`` as exact integers, which is the whole reason this
    tape was built (``RESULT_bulk_history.md``). SOL is the quote wherever it appears; on a
    token-token pool the second vault is used and the unit is that token, which is fine
    because every statistic below is a *share*, not a level.
    """

    vaults = ((r.get("reserves") or {}).get("vaults") or [])
    pick = None
    for v in vaults:
        if v.get("mint") == WSOL:
            pick = v
            break
    if pick is None and len(vaults) >= 2:
        pick = vaults[1]
    if pick is not None:
        try:
            return abs(float(pick.get("delta_raw") or 0)) / (10 ** int(pick.get("decimals") or 0))
        except Exception:
            return 0.0
    # No reserves recorded (DLMM summary rows). Fall back to the declared leg amounts.
    for mint_key, raw_key in (("token_in_mint", "token_in_raw"), ("token_out_mint", "token_out_raw")):
        if r.get(mint_key) == WSOL:
            try:
                return float(r.get(raw_key) or 0) / 1e9
            except Exception:
                return 0.0
    return 0.0


def choreography(swaps: Sequence[dict], coverage: Sequence[tuple[float, float]] | None = None) -> dict:
    """Concentration and choreography statistics for one pool's swap tape.

    The asymmetry to look for (Marino §VIII): accumulation is spread across many wallets,
    distribution is concentrated in one. So the statistic that matters is not "how many
    wallets" but *the difference in wallet concentration between the buy side and the sell
    side*, which is scale-free and needs no reference population.
    """

    buys: dict[str, float] = defaultdict(float)
    sells: dict[str, float] = defaultdict(float)
    seen: dict[str, list[int]] = defaultdict(list)
    times: list[int] = []
    n_buy = n_sell = 0
    side_defects = 0
    for r in swaps:
        signers = r.get("signers") or []
        who = signers[0] if signers else (r.get("fee_payer") or "?")
        sz = _swap_size(r)
        t = (r.get("chain") or {}).get("block_time") or 0
        seen[who].append(t)
        times.append(t)
        # Side from the *sign of the quote vault delta*, which is exact and defined on
        # token-token pools where the tape's `side` field is absent. Quote flowing into the
        # pool is a buy of the base. The tape's own `side` is used as a cross-check, and a
        # disagreement is counted rather than silently resolved.
        sign = _quote_delta_sign(r)
        if sign is None:
            side = r.get("side")
            is_buy = side == "buy"
        else:
            is_buy = sign > 0
            if r.get("side") in ("buy", "sell") and (r["side"] == "buy") != is_buy:
                side_defects += 1
        if is_buy:
            buys[who] += sz
            n_buy += 1
        else:
            sells[who] += sz
            n_sell += 1

    def hhi(d: dict[str, float]) -> float | None:
        tot = sum(d.values())
        if tot <= 0:
            return None
        return sum((v / tot) ** 2 for v in d.values())

    both = set(buys) & set(sells)
    tot_all = sum(buys.values()) + sum(sells.values())
    recycled = sum(min(buys[w], sells[w]) * 2 for w in both)
    hhi_b, hhi_s = hhi(buys), hhi(sells)
    return {
        "n_swaps": len(swaps),
        "n_buys": n_buy, "n_sells": n_sell,
        "distinct_signers": len(seen),
        "distinct_buyers": len(buys), "distinct_sellers": len(sells),
        "hhi_buy": hhi_b, "hhi_sell": hhi_s,
        # >0 means the sell side is more concentrated than the buy side — the dump signature
        "hhi_asymmetry": (hhi_s - hhi_b) if (hhi_b is not None and hhi_s is not None) else None,
        "top_seller_share": (max(sells.values()) / sum(sells.values())) if sells and sum(sells.values()) > 0 else None,
        "top_buyer_share": (max(buys.values()) / sum(buys.values())) if buys and sum(buys.values()) > 0 else None,
        "two_sided_wallets": len(both),
        # Round-tripped quote: volume that came back out of the same wallet it went in.
        # NOT by itself evidence of wash trading — a scalper round-trips by design — which
        # is why `wash_share` below applies the discriminating condition.
        "recycled_share": (recycled / tot_all) if tot_all > 0 else None,
        # The wash measurable: volume from wallets whose *net* position barely moved while
        # their *gross* was large. A real buyer accumulates (|net| ≈ gross); a wash wallet
        # ends flat (|net| ≈ 0) having generated volume. Threshold 0.10 is reported, and the
        # full distribution of |net|/gross is returned so it can be re-cut.
        "wash_share": _wash_share(buys, sells, 0.10),
        "net_over_gross_deciles": _net_over_gross_deciles(buys, sells),
        "swaps_per_signer": len(swaps) / max(1, len(seen)),
        "quote_volume": tot_all,
        # S2 at swap resolution: how regular is the tape's own clock? A scheduler collapses
        # the inter-arrival CV toward 0; a Poisson (memoryless) arrival process sits at
        # exactly 1.0, which is the reference value this is read against — no fitting needed.
        "interarrival_cv": _interarrival_cv(times, coverage),
        "interarrival_cv_unwatched": _interarrival_cv(times, None),
        "coverage_intervals": len(coverage or []),
        "side_defects": side_defects,
    }


def _quote_delta_sign(r: dict) -> int | None:
    vaults = ((r.get("reserves") or {}).get("vaults") or [])
    pick = None
    for v in vaults:
        if v.get("mint") == WSOL:
            pick = v
            break
    if pick is None and len(vaults) >= 2:
        pick = vaults[1]
    if pick is None:
        return None
    try:
        d = float(pick.get("delta_raw") or 0)
    except Exception:
        return None
    return 1 if d > 0 else (-1 if d < 0 else None)


def _wash_share(buys: dict[str, float], sells: dict[str, float], cut: float) -> float | None:
    tot = sum(buys.values()) + sum(sells.values())
    if tot <= 0:
        return None
    flat = 0.0
    for w in set(buys) | set(sells):
        b, s = buys.get(w, 0.0), sells.get(w, 0.0)
        gross = b + s
        if gross <= 0:
            continue
        if abs(b - s) / gross < cut:
            flat += gross
    return flat / tot


def _net_over_gross_deciles(buys: dict[str, float], sells: dict[str, float]) -> list[float]:
    vals = []
    for w in set(buys) | set(sells):
        b, s = buys.get(w, 0.0), sells.get(w, 0.0)
        g = b + s
        if g > 0:
            vals.append(abs(b - s) / g)
    if not vals:
        return []
    vals.sort()
    return [vals[min(len(vals) - 1, int(p * len(vals) / 10))] for p in range(11)]


def _interarrival_cv(times: Sequence[int], coverage: Sequence[tuple[float, float]] | None = None) -> float | None:
    """CV of inter-trade gaps, computed only *inside* watch coverage.

    This is the statistic the house discipline exists to protect. The recorder is not always
    running, and a gap that straddles a ``watch_close``/``watch_open`` pair is a gap in the
    *observer*, not in the market. Including one inflates the CV without limit — measured on
    nosis/SOL it took the CV from 2.4 to 33.4, an entirely fabricated "burstiness". So gaps
    are only counted between two trades that lie in the same coverage interval.

    The reference value is exact and needs no fitting: a memoryless (Poisson) arrival process
    has CV = 1. Below 1 the tape is *more regular than chance* — a scheduler. Above 1 it is
    bursty, which is what real attention looks like.
    """

    ts = sorted(t for t in times if t)
    if coverage is None:
        gaps = [ts[i] - ts[i - 1] for i in range(1, len(ts))]
    else:
        gaps = []
        for lo, hi in coverage:
            inside = [t for t in ts if lo <= t <= hi]
            gaps.extend(inside[i] - inside[i - 1] for i in range(1, len(inside)))
    gaps = [g for g in gaps if g >= 0]
    if len(gaps) < 20:
        return None
    m = sum(gaps) / len(gaps)
    if m <= 0:
        return None
    return math.sqrt(statistics.pvariance(gaps)) / m


def coverage_intervals(pool: str, hours: float = 336.0) -> list[tuple[float, float]]:
    """Watch coverage for one cluster pool, in unix seconds, gaps already carved out."""

    try:
        from datetime import UTC, datetime, timedelta

        from shitcoims_cluster.pools import pool_for
        from shitcoims_cluster.tape import default_tape_root
        from shitcoims_netmap.tapefeed import Interval, ReadStats, _read_watch
    except Exception:
        return []
    now = datetime.now(UTC)
    window = Interval(now - timedelta(hours=hours), now)
    try:
        spec = pool_for(pool)
    except Exception:
        return []
    intervals, _gap_s, _open = _read_watch(default_tape_root(), spec, window, now, ReadStats())
    return [(iv.start.timestamp(), iv.end.timestamp()) for iv in intervals]


def cmd_cluster(args: argparse.Namespace) -> None:
    from shitcoims_cluster.pools import CLUSTER_POOLS

    labels = {p.address: p.label for p in CLUSTER_POOLS}
    by_pool = _load_cluster_swaps()
    print(f"{'pool':22s} {'swaps':>6s} {'sign':>5s} {'buy%':>5s} {'HHIbuy':>7s} {'HHIsell':>7s} "
          f"{'asym':>7s} {'topsell':>7s} {'recyc':>6s} {'wash':>6s} {'iaCV':>6s} {'def':>4s}")
    rows = []
    for pool, swaps in sorted(by_pool.items(), key=lambda kv: -len(kv[1])):
        c = choreography(swaps, coverage_intervals(pool))
        c["pool"] = pool
        c["label"] = labels.get(pool, "?")
        rows.append(c)
        def f(x, w=7, p=3):
            return f"{x:>{w}.{p}f}" if isinstance(x, (int, float)) else " " * (w - 1) + "-"
        print(f"{c['label'][:22]:22s} {c['n_swaps']:6d} {c['distinct_signers']:5d} "
              f"{100 * c['n_buys'] / max(1, c['n_swaps']):5.1f} {f(c['hhi_buy'])} {f(c['hhi_sell'])} "
              f"{f(c['hhi_asymmetry'])} {f(c['top_seller_share'])} {f(c['recycled_share'], 6)} "
              f"{f(c['wash_share'], 6)} {f(c['interarrival_cv'], 6, 2)} {c['side_defects']:4d}")
    out = STATE / "cluster_choreography.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1))
    print(f"\nwrote {out}")


# ---------------------------------------------------------------------------------------
# S3 on the cohort: who was actually trading a coin while it was being crimed
# ---------------------------------------------------------------------------------------
#
# GeckoTerminal gives price and volume and no identity, so everything above is blind to *who*
# was on the other side. BigQuery has the identity, and the cost structure makes this cheap
# in a way worth stating because it is counter-intuitive:
#
#   **The scan is priced by COLUMNS, not by pools.** The same query over 4 pools and over 46
#   pools both dry-run at 415.8 GB — the `EXISTS(... owner IN (...))` filter does not reduce
#   the bytes read. So the marginal cost of adding a control group is exactly zero, and there
#   is no reason ever to pull a treatment arm without one.
#
# Measured: 415.8 GB/day with `--with-signers` (against ~263 GB/day without, which is the
# figure in RESULT_bulk_history.md — the `accounts` column is the difference). At $6.25/TiB
# that is **$2.36/day**, so a two-day treatment-plus-control pull costs about $4.72.
#
# What it buys: the four signatures' missing third. Concentration, the accumulation-vs-dump
# asymmetry, and wash share become measurable on coins that actually rugged instead of only
# on the eleven pools the desk happens to record.

BQ_DIR = STATE / "bq"
BQ_PROJECT_DEFAULT = "manifest-quasar-414607"


def _bq_plist(pools: Sequence[str]) -> str:
    for p in pools:
        # Addresses come from our own resolved tape, but a string spliced into SQL gets
        # checked anyway — the base58 alphabet has no quote character in it, so anything
        # outside it is a bug or an injection and both stop here.
        if not p or not all(ch.isalnum() for ch in p):
            raise ValueError(f"refusing to splice {p!r} into SQL")
    return ", ".join(f"'{p}'" for p in pools)


def _bq_pull_sql(day: str, pools: Sequence[str]) -> str:
    """Swap-level rows with signers for arbitrary pools.

    This deliberately does **not** reuse ``scripts/bulk_history.py``'s ``pull_sql``, and the
    reason is worth recording because the first attempt did and it failed:

    * that query keeps failed transactions on purpose (they are most of the competitive
      signal for its question), and here they are pure noise — ``RESULT_bulk_history.md``
      measured BigQuery ``failed`` rows outnumbering genuine attempts **24 to 1**, and over
      46 pools that blew straight through a 2,000,000-row cap and cost a scan for nothing;
    * its parser resolves every pool through ``shitcoims_cluster.pools.pool_for`` and raises
      on an address outside the cluster, which is right for its job and fatal for this one.

    The success predicate is ``err = ''``, and getting that wrong is a silent-zero trap worth
    recording: ``err`` is a non-nullable ``STRING`` on this table, so ``err IS NULL`` matches
    **nothing** — and BigQuery's dry run then reports **0 bytes**, which reads exactly like a
    free query rather than like an empty one. Measured on 2026-07-30: 824,013 rows with
    ``err = ''`` against ~62,000 carrying an error string, in five minutes of chain time.

    Filtering costs nothing extra to scan — the bytes are set by the columns — and cuts the
    returned rows by more than an order of magnitude.
    """

    plist = _bq_plist(pools)
    nxt = f"DATE_ADD(DATE('{day}'), INTERVAL 1 DAY)"
    return f"""
SELECT signature, block_slot, UNIX_SECONDS(block_timestamp) AS block_time, index AS tx_index,
       ARRAY(SELECT a.pubkey FROM UNNEST(accounts) a WHERE a.signer) AS signers,
       ARRAY(SELECT AS STRUCT owner, mint, CAST(amount AS STRING) AS amount, decimals
             FROM UNNEST(pre_token_balances) WHERE owner IN ({plist})) AS pre,
       ARRAY(SELECT AS STRUCT owner, mint, CAST(amount AS STRING) AS amount, decimals
             FROM UNNEST(post_token_balances) WHERE owner IN ({plist})) AS post
FROM `bigquery-public-data.crypto_solana_mainnet_us.Transactions`
WHERE block_timestamp >= TIMESTAMP('{day}')
  AND block_timestamp < TIMESTAMP({nxt})
  AND err = ''
  AND EXISTS(SELECT 1 FROM UNNEST(post_token_balances) b WHERE b.owner IN ({plist}))
ORDER BY block_slot, tx_index
""".strip()


def _bq_agg_sql(day: str, pools: Sequence[str], quote: str = WSOL) -> str:
    """Choreography statistics computed **in BigQuery**, returning one row per (pool, signer).

    This replaces an earlier design that downloaded raw swap rows, and the reason is a number:
    over 46 pools, one day of successful transactions touching them is **5,012,308 rows**. The
    `bq` CLI pages those over REST and it does not finish in useful time. The scan is billed
    identically either way — the bytes are set by the columns — so aggregating server-side is
    strictly better: same cost, a result measured in tens of thousands of rows instead of
    millions.

    The quote leg's signed delta is the whole measurement. Quote flowing **into** the pool is a
    buy of the base; out of it is a sell. That is exact, needs no DEX-specific decoding, and is
    defined on any pool holding a WSOL vault.
    """

    plist = _bq_plist(pools)
    nxt = f"DATE_ADD(DATE('{day}'), INTERVAL 1 DAY)"
    return f"""
WITH tx AS (
  SELECT
    signature,
    UNIX_SECONDS(block_timestamp) AS t,
    (SELECT a.pubkey FROM UNNEST(accounts) a WHERE a.signer LIMIT 1) AS signer,
    b.owner AS pool,
    b.decimals AS decimals,
    b.amount - IFNULL((SELECT p.amount FROM UNNEST(pre_token_balances) p
                       WHERE p.owner = b.owner AND p.mint = b.mint LIMIT 1), 0) AS dq
  FROM `bigquery-public-data.crypto_solana_mainnet_us.Transactions`,
       UNNEST(post_token_balances) AS b
  WHERE block_timestamp >= TIMESTAMP('{day}')
    AND block_timestamp < TIMESTAMP({nxt})
    AND err = ''
    AND b.owner IN ({plist})
    AND b.mint = '{quote}'
),
moved AS (SELECT * FROM tx WHERE dq != 0 AND signer IS NOT NULL),
gaps AS (
  SELECT pool,
         t - LAG(t) OVER (PARTITION BY pool ORDER BY t, signature) AS gap
  FROM moved
)
SELECT 'signer' AS kind, pool, signer,
       COUNT(*) AS n_trades,
       SUM(CASE WHEN dq > 0 THEN dq ELSE 0 END) / POW(10, ANY_VALUE(decimals)) AS buy_qty,
       SUM(CASE WHEN dq < 0 THEN -dq ELSE 0 END) / POW(10, ANY_VALUE(decimals)) AS sell_qty,
       MIN(t) AS t_first, MAX(t) AS t_last,
       NULL AS gap_n, NULL AS gap_mean, NULL AS gap_var
FROM moved GROUP BY pool, signer
UNION ALL
SELECT 'pool' AS kind, pool, NULL AS signer,
       COUNT(*) AS n_trades, NULL, NULL, NULL, NULL,
       COUNTIF(gap IS NOT NULL) AS gap_n,
       AVG(gap) AS gap_mean,
       VAR_POP(gap) AS gap_var
FROM gaps GROUP BY pool
""".strip()


def _bq_count_sql(day: str, pools: Sequence[str]) -> str:
    """How many rows the pull would return. Scans far fewer columns, so it is cheap."""

    plist = _bq_plist(pools)
    nxt = f"DATE_ADD(DATE('{day}'), INTERVAL 1 DAY)"
    return f"""
SELECT COUNT(*) AS n
FROM `bigquery-public-data.crypto_solana_mainnet_us.Transactions`
WHERE block_timestamp >= TIMESTAMP('{day}')
  AND block_timestamp < TIMESTAMP({nxt})
  AND err = ''
  AND EXISTS(SELECT 1 FROM UNNEST(post_token_balances) b WHERE b.owner IN ({plist}))
""".strip()


def _bq_parse(rows: Sequence[dict], pools: Sequence[str]) -> list[dict]:
    """Minimal swap extraction: signers plus the per-mint vault deltas for each pool.

    ``bulk_history``'s own parser is deliberately not reused here: it resolves every pool
    through ``shitcoims_cluster.pools.pool_for`` and raises on an address outside the
    cluster, which is correct for its job and wrong for this one. Only the fields this
    study needs are recovered, and nothing is inferred.
    """

    want = set(pools)
    out: list[dict] = []
    for tx in rows:
        pre, post = tx.get("pre") or [], tx.get("post") or []
        if not pre and not post:
            continue
        bal: dict[tuple[str, str], dict] = {}
        for side, recs in (("pre", pre), ("post", post)):
            for r in recs:
                owner, mint = r.get("owner"), r.get("mint")
                if owner not in want:
                    continue
                key = (owner, mint)
                e = bal.setdefault(key, {"pre": 0, "post": 0, "decimals": int(r.get("decimals") or 0)})
                try:
                    e[side] = int(r.get("amount") or 0)
                except Exception:
                    e[side] = 0
        by_pool: dict[str, list[dict]] = defaultdict(list)
        for (owner, mint), e in bal.items():
            delta = e["post"] - e["pre"]
            by_pool[owner].append({"mint": mint, "delta_raw": str(delta),
                                   "decimals": e["decimals"],
                                   "pre_raw": str(e["pre"]), "post_raw": str(e["post"])})
        for pool, vaults in by_pool.items():
            moved = [v for v in vaults if int(v["delta_raw"]) != 0]
            if len(moved) < 2:
                continue  # not a swap through this pool: no two-sided vault movement
            out.append({
                "kind": "swap",
                "pool": pool,
                "chain": {"block_time": int(tx.get("block_time") or 0),
                          "slot": int(tx.get("block_slot") or 0),
                          "signature": tx.get("signature"),
                          "tx_index": int(tx.get("tx_index") or 0)},
                "err": tx.get("err") or None,
                "signers": list(tx.get("signers") or []),
                "reserves": {"pool": pool, "vaults": vaults},
            })
    return out


def bq_pool_list(day_unix: int, max_pools: int = 250) -> list[dict]:
    """Cohort pools alive on ``day_unix``, plus every cluster pool.

    Adding pools to the scan is **free** (§ the module note), so the list is as wide as the
    query's `IN` clause comfortably takes. The cluster pools are included unconditionally so
    the operator's own coins land in the same cross-section as everybody else's rather than
    being compared to a constant.
    """

    from shitcoims_cluster.pools import CLUSTER_POOLS

    out: dict[str, dict] = {}
    for r in jsonl_read(LABELS):
        if not r.get("pool"):
            continue
        if not (r.get("t_event_start", 0) <= day_unix <= r.get("t_event_end", 0)):
            continue
        rip = r.get("rip")
        out[r["pool"]] = {
            "pool": r["pool"], "symbol": r.get("symbol"), "mint": r.get("mint"),
            "arm": "ripped" if rip else "control",
            "peak_mcap": r.get("peak_mcap"),
            "rip_t_event": (rip or {}).get("t_event"),
            "rip_same_day": bool(rip and abs((rip["t_event"] or 0) - day_unix) < 86400),
        }
    rows = sorted(out.values(), key=lambda r: (0 if r["arm"] == "ripped" else 1,
                                              -(r["peak_mcap"] or 0)))[:max_pools]
    have = {r["pool"] for r in rows}
    for spec in CLUSTER_POOLS:
        if spec.address not in have:
            rows.append({"pool": spec.address, "symbol": spec.label, "mint": None,
                         "arm": "cluster", "peak_mcap": None, "rip_t_event": None,
                         "rip_same_day": False})
    return rows


def cmd_bq_pools(args: argparse.Namespace) -> None:
    import time as _t

    day_unix = int(_t.mktime(_t.strptime(args.day, "%Y-%m-%d")))
    rows = bq_pool_list(day_unix, max_pools=args.max_pools)
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "bq_pools.json").write_text(json.dumps([r["pool"] for r in rows], indent=1))
    (STATE / "bq_pool_meta.json").write_text(json.dumps(rows, indent=1))
    arms = defaultdict(int)
    for r in rows:
        arms[r["arm"]] += 1
    print(f"{len(rows)} pools for {args.day}: " + ", ".join(f"{k}={v}" for k, v in sorted(arms.items())))
    print(f"  same-day rips: {sum(1 for r in rows if r['rip_same_day'])}")


def cmd_bq_signers(args: argparse.Namespace) -> None:
    import subprocess

    pools_path = STATE / "bq_pools.json"
    pools = json.loads(pools_path.read_text()) if pools_path.exists() else []
    if not pools:
        raise SystemExit(f"no pool list at {pools_path}")
    BQ_DIR.mkdir(parents=True, exist_ok=True)
    total_billed = 0
    for day in args.days:
        out = BQ_DIR / f"{day.replace('-', '')}.jsonl"
        meta = BQ_DIR / f"{day.replace('-', '')}.meta.json"
        if out.exists() and not args.force:
            print(f"{day}: cached ({out})")
            continue
        sql = _bq_agg_sql(day, pools)
        base = ["bq", f"--project_id={args.project}", "--format=json"]

        def dry(q: str, base: list[str] = base) -> int:
            e = subprocess.run([*base, "query", "--use_legacy_sql=false", "--dry_run"],
                               input=q, capture_output=True, text=True)
            if e.returncode != 0:
                raise SystemExit(f"dry run failed:\n{e.stderr}\n{e.stdout}")
            return int(json.loads(e.stdout)["statistics"]["totalBytesProcessed"])

        nbytes = dry(sql)
        usd = nbytes / 1.099511627776e12 * 6.25
        print(f"{day}: aggregate dry run {nbytes / 1e9:.1f} GB -> ${usd:.2f}")
        if nbytes > args.max_bytes:
            raise SystemExit(f"refusing: {nbytes / 1e9:.1f} GB over the cap {args.max_bytes / 1e9:.1f} GB")
        if args.dry_run:
            continue
        # The aggregate returns one row per (pool, signer) plus one per pool, so the row cap
        # is generous rather than computed — the earlier design needed a COUNT(*) first
        # because it downloaded 5,012,308 raw rows and `bq --max_rows` truncates silently.
        cap = 3_000_000
        proc = subprocess.run(
            [*base, "query", "--use_legacy_sql=false", "--nouse_cache",
             f"--max_rows={cap}", f"--maximum_bytes_billed={args.max_bytes}"],
            input=sql, capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"query failed:\n{proc.stderr}\n{proc.stdout}")
        raw = json.loads(proc.stdout or "[]")
        if len(raw) >= cap:
            raise SystemExit("hit the row cap; the day would be recorded short")
        with out.open("w") as fh:
            for row in raw:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        meta.write_text(json.dumps({
            "day": day, "pools": pools, "n_pools": len(pools),
            "rows": len(raw),
            "bytes_processed": nbytes, "usd_estimate": usd,
            "with_signers": True, "aggregated_in_sql": True, "t_ingest": _now(),
            "source": "bigquery.crypto_solana_mainnet_us.Transactions",
            "query_sha256": __import__("hashlib").sha256(sql.encode()).hexdigest(),
        }, indent=1))
        print(f"  {len(raw):,} aggregate rows  ->  {out}")
        total_billed += nbytes
        print(f"\ntotal scanned this run: {total_billed / 1e9:.1f} GB "
          f"(~${total_billed / 1.099511627776e12 * 6.25:.2f})")


def _cluster_addresses() -> frozenset[str]:
    try:
        from shitcoims_cluster.pools import CLUSTER_POOLS

        return frozenset(p.address for p in CLUSTER_POOLS)
    except Exception:
        return frozenset()


def _bq_choreography_from_agg() -> list[dict]:
    """Rebuild the per-pool choreography statistics from the SQL aggregate.

    Every statistic in :func:`choreography` is a function of per-(pool, signer) buy and sell
    totals plus the pool's inter-arrival moments, so nothing is lost by aggregating in the
    warehouse — which is the point, given the raw form was five million rows a day.
    """

    per_pool: dict[str, dict[str, tuple[float, float, int]]] = defaultdict(dict)
    gaps: dict[str, dict] = {}
    for path in sorted(BQ_DIR.glob("*.jsonl")):
        with path.open() as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                pool = r.get("pool")
                if not pool:
                    continue
                if r.get("kind") == "pool":
                    gaps[pool] = {"gap_n": int(float(r.get("gap_n") or 0)),
                                  "gap_mean": float(r.get("gap_mean") or 0.0),
                                  "gap_var": float(r.get("gap_var") or 0.0),
                                  "n_trades": int(float(r.get("n_trades") or 0))}
                    continue
                signer = r.get("signer")
                if not signer:
                    continue
                b = float(r.get("buy_qty") or 0.0)
                s = float(r.get("sell_qty") or 0.0)
                n = int(float(r.get("n_trades") or 0))
                prev = per_pool[pool].get(signer, (0.0, 0.0, 0))
                per_pool[pool][signer] = (prev[0] + b, prev[1] + s, prev[2] + n)

    out = []
    for pool, signers in per_pool.items():
        buys = {w: v[0] for w, v in signers.items() if v[0] > 0}
        sells = {w: v[1] for w, v in signers.items() if v[1] > 0}

        def hhi(d: dict[str, float]) -> float | None:
            tot = sum(d.values())
            return sum((v / tot) ** 2 for v in d.values()) if tot > 0 else None

        hb, hs = hhi(buys), hhi(sells)
        both = set(buys) & set(sells)
        tot_all = sum(buys.values()) + sum(sells.values())
        recycled = sum(min(buys[w], sells[w]) * 2 for w in both)
        g = gaps.get(pool) or {}
        cv = (math.sqrt(g["gap_var"]) / g["gap_mean"]
              if g.get("gap_mean") and g["gap_mean"] > 0 and g.get("gap_n", 0) >= 20 else None)
        out.append({
            "pool": pool,
            "n_swaps": g.get("n_trades") or sum(v[2] for v in signers.values()),
            "distinct_signers": len(signers),
            "distinct_buyers": len(buys), "distinct_sellers": len(sells),
            "hhi_buy": hb, "hhi_sell": hs,
            "hhi_asymmetry": (hs - hb) if (hb is not None and hs is not None) else None,
            "top_buyer_share": (max(buys.values()) / sum(buys.values())) if buys else None,
            "top_seller_share": (max(sells.values()) / sum(sells.values())) if sells else None,
            "two_sided_wallets": len(both),
            "recycled_share": (recycled / tot_all) if tot_all > 0 else None,
            "wash_share": _wash_share(buys, sells, 0.10),
            "swaps_per_signer": (sum(v[2] for v in signers.values()) / max(1, len(signers))),
            "quote_volume": tot_all,
            "interarrival_cv": cv,
            "gap_n": g.get("gap_n"),
        })
    return out


def _pct_rank_local(x: float, pop: Sequence[float]) -> float | None:
    if not pop or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return sum(1 for v in pop if v <= x) / len(pop)


def cmd_bq_choreography(args: argparse.Namespace) -> None:
    """S3 on the cohort: concentration and choreography, ripped vs control vs the cluster."""

    meta_path = STATE / "bq_pool_meta.json"
    meta = {r["pool"]: r for r in json.loads(meta_path.read_text())} if meta_path.exists() else {}
    rows = _bq_choreography_from_agg()
    if not rows:
        raise SystemExit(f"no BigQuery aggregate under {BQ_DIR}")

    for c in rows:
        m = meta.get(c["pool"]) or {}
        c["symbol"] = m.get("symbol")
        c["peak_mcap"] = m.get("peak_mcap")
        # Three arms, not two. A coin that ripped three weeks ago is a corpse on this day, not
        # a crime in progress, and pooling it with the same-day rips would blunt exactly the
        # contrast the day was bought for.
        if c["pool"] in _cluster_addresses():
            # Cluster membership is decided by address, not by which enumerator found the
            # pool first: three of the four held coins are also in the cohort, and letting
            # them sit in the control arm would both contaminate the control and hide the
            # comparison the operator actually wants.
            c["arm"] = "cluster"
        elif m.get("rip_same_day"):
            c["arm"] = "ripping"
        elif m.get("arm") == "ripped":
            c["arm"] = "post_rip"
        else:
            c["arm"] = "control"

    rows = [c for c in rows if c["n_swaps"] >= args.min_swaps]
    rows.sort(key=lambda c: (c["arm"], -c["n_swaps"]))
    print(f"{'sym':14s} {'arm':9s} {'swaps':>6s} {'sign':>5s} {'HHIbuy':>7s} {'HHIsell':>7s} "
          f"{'asym':>7s} {'topsell':>7s} {'recyc':>6s} {'wash':>6s} {'iaCV':>6s}")
    for c in rows:
        def f(x, w=7, p=3):
            return f"{x:>{w}.{p}f}" if isinstance(x, (int, float)) else " " * (w - 1) + "-"
        print(f"{(c['symbol'] or c['pool'][:8])[:14]:14s} {c['arm']:9s} {c['n_swaps']:6d} "
              f"{c['distinct_signers']:5d} {f(c['hhi_buy'])} {f(c['hhi_sell'])} "
              f"{f(c['hhi_asymmetry'])} {f(c['top_seller_share'])} {f(c['recycled_share'], 6)} "
              f"{f(c['wash_share'], 6)} {f(c['interarrival_cv'], 6, 2)}")

    # arm comparison with an exact permutation p, because n is small enough to do it right
    def arm_stat(key: str, arm_a: str = "ripping", arm_b: str = "control") -> dict:
        a = [r[key] for r in rows if r["arm"] == arm_a and isinstance(r.get(key), (int, float))]
        b = [r[key] for r in rows if r["arm"] == arm_b and isinstance(r.get(key), (int, float))]
        if len(a) < 2 or len(b) < 2:
            return {}
        import itertools

        obs = statistics.median(a) - statistics.median(b)
        pool_all = a + b
        n = len(a)
        combos = list(itertools.combinations(range(len(pool_all)), n))
        if len(combos) > 200_000:
            import random

            rng = random.Random(5)
            combos = [tuple(rng.sample(range(len(pool_all)), n)) for _ in range(20_000)]
        hits = 0
        for cmb in combos:
            sel = set(cmb)
            aa = [pool_all[i] for i in range(len(pool_all)) if i in sel]
            bb = [pool_all[i] for i in range(len(pool_all)) if i not in sel]
            if abs(statistics.median(aa) - statistics.median(bb)) >= abs(obs):
                hits += 1
        return {"arm_a": arm_a, "arm_b": arm_b,
                "a_median": statistics.median(a), "b_median": statistics.median(b),
                "diff": obs, "p_two_sided": hits / len(combos), "n_a": len(a), "n_b": len(b),
                "exact": len(combos) < 200_000}

    keys = ["hhi_buy", "hhi_sell", "hhi_asymmetry", "top_seller_share", "recycled_share",
            "wash_share", "interarrival_cv", "swaps_per_signer", "distinct_signers"]
    tests = {k: arm_stat(k) for k in keys}
    print("\n=== ripping vs control, median difference, exact/permuted two-sided p ===")
    print(f"  {'statistic':20s} {'ripping':>10s} {'control':>10s} {'diff':>10s} {'p':>8s}")
    pv = []
    for k in keys:
        t = tests[k]
        if not t:
            continue
        pv.append(t["p_two_sided"])
        print(f"  {k:20s} {t['a_median']:10.4f} {t['b_median']:10.4f} "
              f"{t['diff']:+10.4f} {t['p_two_sided']:8.4f}")
    if pv:
        try:
            from studies.exploration_map import benjamini_yekutieli

            qv, rej, c_m = benjamini_yekutieli(pv, q=0.10)
            print(f"\n  BY-FDR q=0.10 over {len(pv)} statistics (c_m={c_m:.3f}): "
                  f"{int(sum(rej))} survive")
            for i, k in enumerate([k for k in keys if tests[k]]):
                tests[k]["q"] = float(qv[i])
                tests[k]["rejected"] = bool(rej[i])
        except Exception as exc:
            print(f"  BY-FDR unavailable: {exc!r}")

    out = STATE / "bq_choreography.json"
    # For the operator's own pools a permutation test is the wrong instrument — there are
    # four of them. Their *percentile position* inside the same-day cross-section is the
    # honest statement, and it is what an operator can act on: "your coin sits at the 12th
    # percentile of seller concentration among 200 coins trading the same day".
    controls = [r for r in rows if r["arm"] == "control"]
    cluster_rows = [r for r in rows if r["arm"] == "cluster"]
    placement = {}
    print(f"\n=== the operator's pools placed in the same-day cross-section "
          f"(n={len(controls)} controls) ===")
    print(f"  {'pool':16s} {'swaps':>6s} " + "".join(f"{k[:12]:>13s}" for k in keys[:6]))
    for r in cluster_rows:
        cells = {}
        for k in keys:
            pop = sorted(x for x in (c.get(k) for c in controls)
                         if isinstance(x, (int, float)) and math.isfinite(x))
            v = r.get(k)
            cells[k] = _pct_rank_local(v, pop) if isinstance(v, (int, float)) else None
        placement[r["symbol"] or r["pool"]] = cells
        print(f"  {(r['symbol'] or r['pool'][:8])[:16]:16s} {r['n_swaps']:6d} "
              + "".join(f"{(cells[k] * 100):12.0f}%" if cells[k] is not None else f"{'-':>13s}"
                        for k in keys[:6]))
    print("  (cells are percentiles within the same-day control cross-section)")
    cluster_tests = {"placement_percentiles": placement, "n_controls": len(controls)}
    out.write_text(json.dumps({"pools": rows, "arm_tests": tests,
                               "cluster_vs_control": cluster_tests, "t_ingest": _now()},
                              indent=1, default=str))
    print(f"\nwrote {out}")


# ---------------------------------------------------------------------------------------
# The window sweep — the question the censoring count forced
# ---------------------------------------------------------------------------------------
#
# The left-truncation count is not a footnote, it is the finding: most mechanical cliffs in
# this cohort happen inside the detector's own warm-up. A 48-hour window cannot score an hour
# that does not have 48 hours behind it, so a coin that rugs on day 2 of its pool is invisible
# *by construction*, not by weakness of the score.
#
# That makes the window a first-class parameter rather than a convenience default, and it has
# a genuine trade-off in both directions: a shorter window covers more coins but measures
# "crawls linearly" over less path, which is exactly the statistic that needs path to be
# meaningful. The sweep measures both sides — coverage and discrimination — instead of
# assuming one dominates.
#
# Declared levels: 6, 12, 24, 48 hours. Fixed before running.

WINDOWS: tuple[int, ...] = (6, 12, 24, 48)


def cmd_windows(args: argparse.Namespace) -> None:
    rows = []
    print(f"{'win':>4s} {'coins':>6s} {'cliffs':>7s} {'trunc':>6s} {'AUC':>6s} {'null p95':>8s} "
          f"{'recall@.8':>10s} {'lead med h':>11s} {'lead p10 h':>11s} {'alerts':>7s}")
    for win in WINDOWS:
        coins = build_coins(win=win, min_peak_mcap=args.min_mcap)
        trunc = len(BUILD_CENSORING.get("left_truncated_rips") or [])
        block = evaluate_block(coins, "rip", 24, train_frac=1.0, split="grouped", verbose=False)
        lt = block.get("lead_times", {}).get("0.80", {})
        lm = lt.get("lead_minutes") or {}
        a = block.get("auc")
        nc = block.get("null_ceiling_p95")
        rows.append({"win": win, "n_coins": block.get("n_coins"), "n_cliffs": block.get("n_ripped"),
                     "n_left_truncated": trunc, "auc": a, "null_ceiling_p95": nc,
                     "recall_080": lt.get("recall_coins"), "n_warned": lt.get("n_warned"),
                     "n_ripped_in_test": lt.get("n_ripped_in_test"),
                     "lead_median_h": (lm.get("median") / 60) if lm.get("median") is not None else None,
                     "lead_p10_h": (lm.get("p10") / 60) if lm.get("p10") is not None else None,
                     "alert_rate": lt.get("alert_rate"), "precision": lt.get("precision"),
                     "censoring": dict(BUILD_CENSORING.get("dropped") or {})})
        r = rows[-1]
        def s(x, f="{:.3f}", w=6):
            return f.format(x).rjust(w) if isinstance(x, (int, float)) else "-".rjust(w)
        print(f"{win:4d} {r['n_coins'] or 0:6d} {r['n_cliffs'] or 0:7d} {trunc:6d} "
              f"{s(a)} {s(nc, '{:.3f}', 8)} "
              f"{s(r['recall_080'], '{:.2f}', 10)} {s(r['lead_median_h'], '{:.1f}', 11)} "
              f"{s(r['lead_p10_h'], '{:.1f}', 11)} {s(r['alert_rate'], '{:.4f}', 7)}")
    out = STATE / "windows.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"t_ingest": _now(), "windows": WINDOWS, "rows": rows},
                              indent=1, default=str))
    print(f"\nwrote {out}")


# ---------------------------------------------------------------------------------------
# Deliverable 3: a taxonomy of manipulator strategies
# ---------------------------------------------------------------------------------------
#
# With a handful of cliffs this is a *description*, not a clustering, and it is written that
# way on purpose: k-means over ten coins would produce clusters, and they would mean nothing.
# What the data can support is naming the archetypes and reporting each coin's pre-rip
# profile against the ambient distribution, so the operator can recognise the shape rather
# than trust a label.
#
# The axes come from the mechanism, not from the data:
#
#   * **metering** — is the ascent a schedule? (`r2_linear` high, `cv_vol` low)
#   * **starvation** — is there anybody there? (`dead_hour_frac` high, `turnover` low)
#   * **leverage** — how far does a dollar move it? (`disp_per_turnover` high)
#
# Their combinations name four strategies, and the naming is a hypothesis the profile table
# either supports or embarrasses:
#
#   METERED CLIMB   high metering, low starvation — a bot walking the price up through real
#                   (if thin) flow. The operator's description, literally.
#   GHOST TOWN      high starvation, low metering — nobody is trading at all and the quoted
#                   price is a fossil. The rip is just the first real seller.
#   THIN SPIKE      high leverage, low metering — a violent move on nothing, no schedule.
#   ORDINARY DEATH  none of the above — the coin simply lost.

def profile_ripped(coins: Sequence[Coin], cal: Calibration, lookback_h: int = 48) -> list[dict]:
    """Pre-rip feature profile of every coin that cliffed, as percentiles of the ambient."""

    out = []
    for c in coins:
        if not c.rip:
            continue
        i = c.rip["i"]
        feats = [f for f in c.feats if f["i"] <= i]
        if not feats:
            continue
        window = [f for f in feats if i - f["i"] <= lookback_h]
        if not window:
            window = feats[-1:]

        def med_rank(key: str, window: list[dict] = window) -> float | None:
            vals = [cal.rank(key, f.get(key)) for f in window]
            vals = [v for v in vals if v is not None]
            return statistics.median(vals) if vals else None

        prof = {k: med_rank(k) for k in FEATURE_KEYS}
        metering = statistics.median([x for x in (prof.get("r2_linear"),
                                                  1 - (prof.get("cv_vol") or 0.5)) if x is not None])
        starvation = statistics.median([x for x in (prof.get("dead_hour_frac"),
                                                    1 - (prof.get("turnover") or 0.5)) if x is not None])
        leverage = prof.get("disp_per_turnover") or 0.5
        if metering >= 0.70 and starvation < 0.70:
            strategy = "METERED_CLIMB"
        elif starvation >= 0.70 and metering < 0.70:
            strategy = "GHOST_TOWN"
        elif leverage >= 0.80 and metering < 0.70:
            strategy = "THIN_SPIKE"
        elif metering >= 0.70 and starvation >= 0.70:
            strategy = "METERED_GHOST"
        else:
            strategy = "ORDINARY_DEATH"
        out.append({
            "mint": c.mint, "symbol": c.series.symbol, "pool": c.series.pool,
            "peak_mcap": c.peak_mcap, "rip_t_event": c.rip["t_event"],
            "rip_mcap": c.rip["ref_mcap"], "fall_pct": c.rip["fall_pct"],
            "fall_hours": c.rip["fall_hours"],
            "metering": metering, "starvation": starvation, "leverage": leverage,
            "strategy": strategy,
            "profile_pct": prof,
            "peak_score_pre_rip": max((f.get("crime_score") or 0) for f in feats),
        })
    return out


def cmd_taxonomy(args: argparse.Namespace) -> None:
    coins = build_coins(win=args.win, min_peak_mcap=args.min_mcap)
    cal = Calibration.fit([f for c in coins for f in c.feats], FEATURE_KEYS)
    score_coins(coins, cal)
    rows = profile_ripped(coins, cal)
    rows.sort(key=lambda r: -(r["peak_mcap"] or 0))
    print(f"{'sym':12s} {'peak mcap':>13s} {'rip mcap':>12s} {'fall':>7s} {'hrs':>4s} "
          f"{'meter':>6s} {'starve':>6s} {'lever':>6s} {'score':>6s}  strategy")
    for r in rows:
        print(f"{(r['symbol'] or '?')[:12]:12s} {r['peak_mcap'] or 0:>13,.0f} {r['rip_mcap'] or 0:>12,.0f} "
              f"{r['fall_pct']:+7.3f} {r['fall_hours']:4d} {r['metering']:6.2f} {r['starvation']:6.2f} "
              f"{r['leverage']:6.2f} {r['peak_score_pre_rip']:6.3f}  {r['strategy']}")
    for t in BUILD_CENSORING.get("left_truncated_rips") or []:
        print(f"{(t['symbol'] or '?')[:12]:12s} {t['peak_mcap']:>13,.0f} {'-':>12s} "
              f"{'-':>7s} {'-':>4s} {'-':>6s} {'-':>6s} {'-':>6s} {'-':>6s}  LEFT_TRUNCATED")
    counts = defaultdict(int)
    for r in rows:
        counts[r["strategy"]] += 1
    counts["LEFT_TRUNCATED"] = len(BUILD_CENSORING.get("left_truncated_rips") or [])
    print("\nstrategy counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    out = STATE / "taxonomy.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"t_ingest": _now(), "n_coins": len(coins), "rows": rows,
                               "counts": dict(counts),
                               "censoring": dict(BUILD_CENSORING)}, indent=1, default=str))
    print(f"wrote {out}")


# ---------------------------------------------------------------------------------------
# Where every threshold in this study came from
# ---------------------------------------------------------------------------------------
#
# The brief's standing instruction is "derive thresholds from data, never assert". This
# command is the audit trail for that: it prints the measured distribution behind each
# number the study uses, including the numbers somebody else already chose (the sentinel's
# `rug_detector` config) placed against the same distribution so they can be judged rather
# than inherited.


def cmd_distributions(args: argparse.Namespace) -> None:
    coins = build_coins(win=args.win, min_peak_mcap=args.min_mcap)
    print(f"cohort: {len(coins)} coins\n")

    # --- 1. the terminal event ----------------------------------------------------------
    # For every coin-hour, the worst fall reachable in the next `window_h` hours, and
    # whether it stayed down. The rip threshold should sit where the *irreversible* tail
    # separates from the reversible body, not at a round number.
    worst_all: list[float] = []
    worst_irrev: list[float] = []
    for c in coins:
        cl = c.series.close
        n = len(cl)
        for i in range(n - 1):
            ref = cl[i]
            if ref <= 0:
                continue
            j_end = min(n, i + RIP_WINDOW_H + 1)
            trough = min(cl[i + 1 : j_end], default=ref)
            fall = trough / ref - 1.0
            worst_all.append(fall)
            tj = cl.index(trough, i + 1, j_end) if trough < ref else i
            tail = cl[tj : min(n, tj + RIP_HOLD_H + 1)]
            if tail and max(tail) <= ref * RIP_RECOVER:
                worst_irrev.append(fall)
    wa, wi = sorted(worst_all), sorted(worst_irrev)

    def frac_beyond(xs: Sequence[float], d: float) -> float:
        return sum(1 for x in xs if x <= -d) / len(xs) if xs else float("nan")

    print("=== S4: the terminal event ===")
    print(f"  {len(wa):,} coin-hours; worst {RIP_WINDOW_H}h fall quantiles:")
    print("   " + "  ".join(f"p{int(p*100):02d}={wa[int(p * len(wa))]:+.3f}"
                            for p in (0.001, 0.01, 0.05, 0.25, 0.5)) if wa else "   (none)")
    print(f"  {'drop':>6s} {'any-fall rate':>14s} {'irreversible rate':>18s} {'irreversible share':>19s}")
    for d in (0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90):
        a, b = frac_beyond(wa, d), frac_beyond(wi, d) * (len(wi) / len(wa) if wa else 0)
        share = (b / a) if a > 0 else float("nan")
        note = ""
        if abs(d - 0.20) < 1e-9:
            note = "  <- config.yaml quote_collapse_pct"
        if abs(d - 0.40) < 1e-9:
            note = "  <- config.yaml liquidity_drop_pct"
        if abs(d - RIP_DROP) < 1e-9:
            note = "  <- RIP_DROP used here"
        print(f"  {d:6.2f} {a:14.5f} {b:18.5f} {share:19.3f}{note}")

    # --- 2. the feature calibration -----------------------------------------------------
    train, _ = temporal_split(coins, frac=1.0)
    cal = Calibration.fit(train, FEATURE_KEYS)
    print(f"\n=== S1/S2: ambient feature quantiles ({cal.n:,} coin-hours) ===")
    print(f"  {'feature':22s} " + "".join(f"{f'p{int(p*100)}':>10s}" for p in (0.05, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)))
    for k in FEATURE_KEYS:
        vals = [cal.quantile(k, p) for p in (0.05, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)]
        print(f"  {k:22s} " + "".join(f"{v:10.4g}" if v is not None else f"{'-':>10s}" for v in vals))

    # --- 3. the score's own distribution ------------------------------------------------
    score_coins(coins, cal)
    ss = sorted(f["crime_score"] for c in coins for f in c.feats if f.get("crime_score") is not None)
    print(f"\n=== the composite score ({len(ss):,} coin-hours) ===")
    print("  " + "  ".join(f"p{int(p*100):02d}={ss[int(p * len(ss))]:.3f}"
                           for p in (0.5, 0.75, 0.9, 0.95, 0.99)) if ss else "  (none)")
    for thr in OPERATING:
        print(f"  score >= {thr:.2f}: {sum(1 for x in ss if x >= thr) / len(ss):.4f} of all coin-hours"
              if ss else "")

    out = STATE / "distributions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "t_ingest": _now(), "n_coins": len(coins), "win": args.win,
        "worst_fall_quantiles": {f"{p:.3f}": (wa[int(p * len(wa))] if wa else None)
                                 for p in (0.001, 0.01, 0.05, 0.25, 0.50)},
        "irreversibility_by_drop": {f"{d:.2f}": {
            "any_fall_rate": frac_beyond(wa, d),
            "irreversible_rate": frac_beyond(wi, d) * (len(wi) / len(wa) if wa else 0),
        } for d in (0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90)},
        "calibration": cal.to_json(),
        "score_quantiles": {f"{p:.2f}": (ss[int(p * len(ss))] if ss else None)
                            for p in (0.5, 0.75, 0.9, 0.95, 0.99)},
    }, indent=1, default=str))
    print(f"\nwrote {out}")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("cohort", help="build the candidate list")
    p.set_defaults(func=cmd_cohort)

    p = sub.add_parser("resolve", help="mint -> pool + supply via GT tokens/multi")
    p.add_argument("--limit", type=int, default=900)
    p.add_argument("--interval", type=float, default=3.0)
    p.set_defaults(func=cmd_resolve)

    p = sub.add_parser("fetch", help="hourly OHLCV for cohort pools")
    p.add_argument("--limit", type=int, default=600)
    p.add_argument("--interval", type=float, default=3.0)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("label", help="mechanical terminal-event labels")
    p.set_defaults(func=cmd_label)

    p = sub.add_parser("eval", help="cohort performance, lead times, nulls, FDR")
    p.add_argument("--win", type=int, default=48)
    p.add_argument("--min-mcap", type=float, default=BAND_LO, dest="min_mcap")
    p.add_argument("--train-frac", type=float, default=0.5, dest="train_frac")
    p.add_argument("--splits", nargs="+", default=["grouped", "temporal"],
                   choices=["grouped", "temporal"])
    p.add_argument("--stride", type=int, default=2)
    p.add_argument("--reps", type=int, default=120, help="null replications")
    p.add_argument("--draws", type=int, default=400, help="bootstrap draws")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("held", help="score the operator's four coins")
    p.add_argument("--win", type=int, default=48)
    p.add_argument("--train-frac", type=float, default=1.0, dest="train_frac")
    p.add_argument("--threshold", type=float, default=0.80)
    p.set_defaults(func=cmd_held)

    p = sub.add_parser("cluster", help="S3 choreography where signers exist")
    p.set_defaults(func=cmd_cluster)

    p = sub.add_parser("breakdown", help="POST-HOC: does the linear crawl break before it rips?")
    p.add_argument("--win", type=int, default=48)
    p.add_argument("--lag", type=int, default=BREAKDOWN_LAG_H)
    p.add_argument("--min-mcap", type=float, default=BAND_LO, dest="min_mcap")
    p.set_defaults(func=cmd_breakdown)

    p = sub.add_parser("vol-control", help="is a drawdown result just volatility scaling?")
    p.add_argument("--win", type=int, default=48)
    p.add_argument("--horizon", type=int, default=72)
    p.add_argument("--stride", type=int, default=2)
    p.add_argument("--drop", type=float, default=0.50, help="fixed drawdown threshold")
    p.add_argument("--k", type=float, nargs="+", default=[1.0, 1.5, 2.0],
                   help="standardised thresholds in units of the coin's own sigma")
    p.add_argument("--features", nargs="+",
                   default=["rv_hourly", "turnover", "fano_vol", "disp_per_turnover"])
    p.add_argument("--min-mcap", type=float, default=BAND_LO, dest="min_mcap")
    p.set_defaults(func=cmd_vol_control)

    p = sub.add_parser("windows", help="does a shorter window reach the fast cliffs?")
    p.add_argument("--min-mcap", type=float, default=BAND_LO, dest="min_mcap")
    p.set_defaults(func=cmd_windows)

    p = sub.add_parser("taxonomy", help="manipulator strategy archetypes for the ripped coins")
    p.add_argument("--win", type=int, default=48)
    p.add_argument("--min-mcap", type=float, default=BAND_LO, dest="min_mcap")
    p.set_defaults(func=cmd_taxonomy)

    p = sub.add_parser("bq-pools", help="choose the pool list for a BigQuery day")
    p.add_argument("--day", required=True)
    p.add_argument("--max-pools", type=int, default=250, dest="max_pools")
    p.set_defaults(func=cmd_bq_pools)

    p = sub.add_parser("bq-signers", help="pull swap-level signers for cohort pools (BigQuery)")
    p.add_argument("--days", nargs="+", required=True, help="YYYY-MM-DD")
    p.add_argument("--project", default=BQ_PROJECT_DEFAULT)
    p.add_argument("--max-bytes", type=int, default=600_000_000_000, dest="max_bytes")
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_bq_signers)

    p = sub.add_parser("bq-choreography", help="S3 on the cohort: ripped vs control")
    p.add_argument("--min-swaps", type=int, default=30, dest="min_swaps")
    p.set_defaults(func=cmd_bq_choreography)

    p = sub.add_parser("distributions", help="where every threshold came from")
    p.add_argument("--win", type=int, default=48)
    p.add_argument("--min-mcap", type=float, default=BAND_LO, dest="min_mcap")
    p.set_defaults(func=cmd_distributions)

    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
