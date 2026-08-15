#!/usr/bin/env python3
"""Do imitation swarms carry information about the host's forward return?

The operator's hypothesis, verbatim: *"noticing when scam/imitators start popping up. i'm
willing to bet that if we are fast we can setup positions that will massively gain from them
when they are even slightly legitimate."*

WHY THIS IS NOT THE CALLOUT CHANNEL AGAIN
-----------------------------------------
``studies/RESULT_callout_edge.md`` closed the social channel with a null that had a sign:
buying a callout returns **−11.9% at 1 h**, the callout block *lowers* test AUC from 0.796 to
0.665, and permuting caller identity **beat** the real identity in 24 of 24 draws. The
structural reading offered there is that talking is free, so the loudest callers are
recruiting exit liquidity and the "signal" is an advertisement.

An imitator is not talking. A clone costs a create transaction plus a dev buy, and it is
aimed at a chosen target. So a swarm is a *costly* signal: N adversaries each spending money
to say "this specific coin has attention worth stealing." That is the one theoretical reason
to expect a different answer, and it is the thing this study makes survive the data or die.

It is also the reason the answer might still be the same. Nothing says a parasite's
attention estimate is *early*. If clones only show up once a coin has already run, the swarm
is a lagging indicator of a move that has finished, and paying to attach yourself to it is
perfectly consistent with the host being over. That is a measurement, and §2 makes it.

THE THREE THINGS THAT COULD MAKE A FALSE POSITIVE HERE
-------------------------------------------------------
1. **Ambient collisions.** Only 23.6% of launches carry a ticker unique within 30 minutes
   (measured by the callout study's cashtag resolver). ``SOLANA`` launches 25 times in four
   hours with nobody imitating anybody. Handled by **two** detector-level nulls in §6 — an
   i.i.d. identity shuffle (the collision floor) and a block rotation (same burst, different
   host) — because PROGRAM.md §3.13 is explicit that one null is a knob rather than a test,
   and here the two answer genuinely different questions.
2. **The free columns.** Market cap and age at onset are the reigning champions at AUC
   0.796. A coin that attracts clones is a coin that is already big, and "big coins keep
   moving" is not the hypothesis. Handled by the matched control arm (§3) and by the
   incremental-AUC test (§4), which is the only question that matters: *conditional*
   information.
3. **Survivorship.** Half these coins stop trading within the hour. Dropping the ones that
   die flipped the callout cohort's 8 h return from −14.6% to **+25%**. Handled by pricing
   every row mark-to-last-trade and by reporting {up, down, dead} as three exclusive states
   (§5) rather than a mean over survivors.

WHY MARK-TO-LAST-TRADE IS AN EXECUTABLE PRICE HERE, UNLIKE ON AN AMM
--------------------------------------------------------------------
The callout study had to caveat its marks: a coin that stopped trading has a *quote* but no
counterparty. On the pump.fun bonding curve that caveat is weaker, because the curve **is**
the counterparty — a sell into a curve with vSol reserves executes against the program at a
deterministic price whether or not another human is present. So forward-filling the last
close is both the correct mark and, net of fee and one's own curve impact, roughly an
attainable exit. The study still reports ``live`` (did anything trade in the window) beside
every return, because "attainable" is not "attained" and post-graduation rows are back on an
ordinary AMM where the caveat returns in full.

DATA
----
* launches — ``state/firehose/new_token/`` (PumpPortal socket) unioned with
  ``state/swarms/census-*.jsonl`` (pump.fun REST list, which the socket cannot supply
  ``image_uri`` for), deduped by mint, restricted to the ledger's demonstrated listening
  windows. See :mod:`shitcoims_scalper.swarm_detect`.
* prices — ``https://swap-api.pump.fun/v1/coins/<mint>/candles?interval=1m&currency=SOL``.
  Free, keyless, one request per mint, retains at least a month, and a candle exists only
  for a minute in which the pool traded. Validated against the socket's own
  ``marketCapSol`` on 24 fresh mints: ``candle[0].open × 1e9 / marketCapSol`` has median
  **0.974** (the open is the bucket's first print, i.e. usually just before the dev buy
  that the socket's market cap already includes).
  **Total spend for this study: $0.00.** No paid API is touched.

Run::

    python -m studies.imitation_signal --fetch     # network; caches candles
    python -m studies.imitation_signal --report    # offline analysis over the cache
    python -m studies.imitation_signal --report --json
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import math
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shitcoims_scalper.swarm_detect import (  # noqa: E402
    PUMP_SUPPLY,
    SWARMS,
    Launch,
    SwarmDetector,
    _census_paths,
    _default_paths,
    build_stream,
    listening_intervals,
    plant_swarms,
    rotate_stream,
    shuffle_stream,
    taxonomy,
)

CANDLES = SWARMS / "candles"
CANDLE_URL = "https://swap-api.pump.fun/v1/coins/{mint}/candles?interval=1m&limit=1000&currency=SOL"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) joshibot-research/1.0"

#: Forward horizons in seconds. The short end is not decoration: Marino's median
#: time-to-graduation is 4.4 minutes, so a pump.fun coin's whole distribution lives inside
#: the first hour and a 4 h horizon is already the long end of this market.
HORIZONS_S = (300, 900, 1800, 3600, 7200)

#: Matching window the study pins, in seconds, against the detector's more permissive
#: default. Two reasons, both measured rather than chosen: the observed lag from host launch
#: to onset has p90 ≈ 1600 s, so 1800 s keeps ~92% of real families; and a window comparable
#: to the tape's own length leaves the i.i.d. null **no room to scatter** — on 1.9 h of tape
#: a 3600 s window let a shuffled stream reproduce the real family count to within 3%, which
#: is a statement about the window, not about imitation. Swept in §7b either way.
STUDY_WINDOW_S = 1800.0

#: Round-trip cost on the pump.fun curve at the sizing ``studies/exploration_map.py``
#: derives (1% protocol+creator each way plus curve impact). Every headline return is
#: reported gross, and the verdict is taken net of this.
FRICTION_ROUND_TRIP = 0.0226

#: Free columns — what a trader already knows for nothing, and the bar any new signal has
#: to clear. RESULT_callout_edge.md §4 scores this block alone at AUC 0.796.
FREE_COLUMNS = (
    "log_mcap_at_onset",
    "log_age_at_onset_s",
    "log_dev_buy_sol",
    "traded_minutes_so_far",
    "log_vol_sol_so_far",
    "momentum_so_far",
)

#: The swarm block — everything the detector knows at the onset instant and nothing it
#: learns afterwards.
SWARM_COLUMNS = (
    "clone_count",
    "distinct_clone_deployers",
    "log_clone_spend_sol",
    "log_lag_from_host_s",
    "log_lag_from_first_clone_s",
    "clone_deployer_max_share",
    "clone_devs_first_launch_frac",
    "is_parasite",
    "is_farm",
    "match_uri",
    "match_image",
    "match_symbol",
    "match_name",
)


# ---------------------------------------------------------------------------
# prices
# ---------------------------------------------------------------------------


class CandleStore:
    """On-disk cache of per-minute SOL prices, keyed by mint.

    Stored as ``[[bucket_start_epoch_s, close_sol_per_token], ...]`` — the close, not the
    open, because the close is the last price at which anyone actually transacted inside
    that minute and is therefore the only one usable as a mark at the minute's end.
    """

    def __init__(self, root: Path = CANDLES) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, list[tuple[float, float]] | None] = {}
        self._lock = threading.Lock()

    def path(self, mint: str) -> Path:
        return self.root / f"{mint}.json"

    def get(self, mint: str) -> list[tuple[float, float]] | None:
        with self._lock:
            if mint in self._mem:
                return self._mem[mint]
        p = self.path(mint)
        out: list[tuple[float, float]] | None
        if not p.exists():
            out = None
        else:
            try:
                raw = json.loads(p.read_text())
                out = [(float(a), float(b)) for a, b in raw["candles"]]
            except (json.JSONDecodeError, KeyError, ValueError):
                out = None
        with self._lock:
            self._mem[mint] = out
        return out

    def has(self, mint: str) -> bool:
        return self.path(mint).exists()

    def fetched_at(self, mint: str) -> float:
        try:
            return float(json.loads(self.path(mint).read_text())["fetched_at"])
        except Exception:  # noqa: BLE001
            return 0.0

    def put(self, mint: str, candles: list[list[Any]], fetched_at: float) -> None:
        rows = [
            (float(c["timestamp"]) / 1000.0, float(c["close"]))
            for c in candles
            if c.get("close") is not None
        ]
        rows.sort()
        self.path(mint).write_text(
            json.dumps({"fetched_at": fetched_at, "n": len(rows), "candles": rows})
        )
        with self._lock:
            self._mem[mint] = rows


def fetch_candles(mint: str, timeout: float = 20.0) -> list[dict[str, Any]]:
    req = urllib.request.Request(
        CANDLE_URL.format(mint=mint), headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.loads(resp.read())
    return out if isinstance(out, list) else []


def fetch_all(
    mints: Sequence[str],
    store: CandleStore,
    *,
    workers: int = 3,
    pause: float = 0.6,
    refresh_older_than: float = 900.0,
    dead_after: float = 2400.0,
    verbose: bool = True,
) -> dict[str, int]:
    """Fill the cache. Re-fetches a mint whose cache is stale enough to be missing candles.

    A cached series is only good up to ``fetched_at``; a row whose horizon extends past that
    would be silently marked with a price that had not happened yet at fetch time. So the
    refresh rule is time-based, not existence-based, and :func:`build_rows` independently
    refuses any horizon running past the series' own fetch time.
    """
    now = time.time()
    todo = []
    stats = Counter({"total": len(mints)})
    for m in mints:
        if not store.has(m):
            todo.append(m)
            continue
        if store.fetched_at(m) >= now - refresh_older_than:
            stats["fresh"] += 1
            continue
        # A coin that had already stopped trading when we cached it is unlikely to acquire
        # new candles, and on this market most coins are in that state within minutes, so a
        # warming loop can skip them cheaply.
        #
        # It can ONLY be a warming optimisation, never the state the analysis runs on. A
        # cached series is authoritative only up to its own ``fetched_at``, and
        # :func:`price_row` correctly refuses any horizon past that — so leaving dead coins
        # on a stale timestamp would admin-censor precisely the coins that died early and
        # quietly reintroduce the survivorship this study exists to avoid. Hence
        # ``dead_after <= 0`` disables the skip, and ``--full`` (used before every reported
        # run) sets it that way.
        if dead_after > 0:
            series = store.get(m)
            if series and store.fetched_at(m) - series[-1][0] > dead_after:
                stats["settled"] += 1
                continue
        todo.append(m)
    stats["todo"] = len(todo)
    if not todo:
        return dict(stats)
    lock = threading.Lock()
    done = [0]

    def work(mint: str) -> None:
        for attempt in range(3):
            try:
                c = fetch_candles(mint)
                store.put(mint, c, time.time())
                with lock:
                    stats["ok"] += 1
                    if not c:
                        stats["empty"] += 1
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    with lock:
                        stats["throttled"] += 1
                    time.sleep(2.0 * (attempt + 1))
                    continue
                with lock:
                    stats[f"http_{exc.code}"] += 1
                break
            except Exception:  # noqa: BLE001
                time.sleep(1.0 * (attempt + 1))
                with lock:
                    stats["retry"] += 1
        else:
            with lock:
                stats["failed"] += 1
        time.sleep(pause)
        with lock:
            done[0] += 1
            if verbose and done[0] % 250 == 0:
                print(f"  [candles] {done[0]}/{len(todo)}", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, todo))
    return dict(stats)


def mark_at(series: Sequence[tuple[float, float]], t: float) -> float | None:
    """Last close at or before ``t``. Forward-fill; never interpolate, never look ahead."""
    if not series:
        return None
    i = bisect.bisect_right([s[0] for s in series], t) - 1
    if i < 0:
        return None
    return series[i][1]


def _traded_between(series: Sequence[tuple[float, float]], a: float, b: float) -> bool:
    ts = [s[0] for s in series]
    i = bisect.bisect_right(ts, a)
    return i < len(ts) and ts[i] <= b


def vol_before(series: Sequence[tuple[float, float]], t: float) -> int:
    """Number of traded minutes at or before ``t`` — the cheap, causal activity count."""
    if not series:
        return 0
    return bisect.bisect_right([s[0] for s in series], t)


# ---------------------------------------------------------------------------
# cohort construction
# ---------------------------------------------------------------------------


def make_traction_probe(store: CandleStore) -> Callable[[str, float], float | None]:
    """Host-selection probe: SOL-equivalent turnover a coin had done before ``t``.

    Defined from observables only, and stated here because "genuine traction" has to mean
    something mechanical: it is ``Σ over traded minutes ≤ t of close × 1e9``, i.e. the sum of
    the coin's market cap over the minutes in which somebody actually transacted. It rewards
    a coin that is both *large* and *repeatedly traded* and gives zero to one that printed a
    dev buy and was never touched again. Only candles at or before ``t`` are read, so the
    probe cannot see the future the study is about to measure.
    """

    def probe(mint: str, t: float) -> float | None:
        series = store.get(mint)
        if not series:
            return None
        n = vol_before(series, t)
        if n == 0:
            return 0.0
        return float(sum(c for _ts, c in series[:n]) * PUMP_SUPPLY)

    return probe


def run_detector(
    launches: Sequence[Launch],
    store: CandleStore | None,
    *,
    k: int = 3,
    window_s: float = 1800.0,
    name_threshold: float = 0.82,
) -> tuple[list[dict[str, Any]], SwarmDetector]:
    det = SwarmDetector(
        window_s=window_s,
        k=k,
        name_threshold=name_threshold,
        traction=make_traction_probe(store) if store is not None else None,
    )
    onsets: list[dict[str, Any]] = []
    for ln in launches:
        onsets.extend(det.push(ln))
    return onsets, det


def _epoch(iso: str) -> float:
    return dt.datetime.fromisoformat(iso).timestamp()


def _log1p(x: float | None, floor: float = 0.0) -> float:
    v = float(x) if x is not None else floor
    return math.log1p(max(v, 0.0))


def price_row(
    mint: str,
    t0: float,
    store: CandleStore,
    launch: Launch | None,
    tape_end: float,
) -> dict[str, Any] | None:
    """Everything about one (coin, evaluation-instant) pair that the outcome side needs."""
    series = store.get(mint)
    if series is None:
        return None
    p0 = mark_at(series, t0)
    if p0 is None or p0 <= 0:
        # never traded at or before t0 — for a launch this can only happen if the coin's
        # create transaction is outside the candle series, which is a data defect, not a
        # coin with no price. Excluded and counted.
        return None
    fetched = store.fetched_at(mint)
    limit = min(tape_end, fetched)
    launch_p = series[0][1] if series else None
    t_last = series[-1][0] if series else t0
    n_before = vol_before(series, t0)
    row: dict[str, Any] = {
        "mint": mint,
        "t_post": t0,
        "p0": p0,
        "mcap_at_onset": p0 * PUMP_SUPPLY,
        "launch_mcap": (launch_p or p0) * PUMP_SUPPLY,
        "momentum_so_far": (p0 / launch_p - 1.0) if launch_p else 0.0,
        "traded_minutes_so_far": n_before,
        "vol_sol_so_far": float(sum(c for _ts, c in series[:n_before]) * PUMP_SUPPLY),
        "t_last_trade": t_last,
        "died": t_last < limit - 600.0,
        "death_s": max(t_last - t0, 0.0),
    }
    for h in HORIZONS_S:
        past = t0 + h > limit
        p1 = mark_at(series, t0 + h)
        row[f"r{h}"] = (p1 / p0 - 1.0) if (p1 and not past) else 0.0
        row[f"live{h}"] = bool(_traded_between(series, t0, t0 + h)) and not past
        row[f"admin{h}"] = past
        # path extremes, for the "was there ever a good exit" question that a mean hides
        if not past:
            ts = [s[0] for s in series]
            i0 = bisect.bisect_right(ts, t0)
            i1 = bisect.bisect_right(ts, t0 + h)
            seg = [c for _t, c in series[i0:i1]]
            row[f"max{h}"] = (max(seg) / p0 - 1.0) if seg else 0.0
            row[f"min{h}"] = (min(seg) / p0 - 1.0) if seg else 0.0
        else:
            row[f"max{h}"] = 0.0
            row[f"min{h}"] = 0.0
    if launch is not None:
        row["dev_buy_sol"] = launch.sol_amount if launch.sol_amount is not None else float("nan")
        row["t_launch"] = launch.t
        row["age_at_onset_s"] = max(t0 - launch.t, 1.0)
        row["deployer"] = launch.deployer
        row["symbol"] = launch.symbol
    return row


def add_features(row: dict[str, Any]) -> dict[str, Any]:
    row["log_mcap_at_onset"] = math.log(max(row["mcap_at_onset"], 1e-9))
    row["log_age_at_onset_s"] = math.log(max(row.get("age_at_onset_s", 1.0), 1.0))
    dev = row.get("dev_buy_sol")
    row["log_dev_buy_sol"] = _log1p(dev if dev == dev else 0.0)  # NaN-safe
    row["log_vol_sol_so_far"] = _log1p(row["vol_sol_so_far"])
    return row


def build_cohort(
    launches: Sequence[Launch],
    onsets: Sequence[dict[str, Any]],
    store: CandleStore,
    tape_end: float,
    *,
    require_uncensored: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One row per swarm onset, on the HOST, evaluated at the onset instant."""
    by_mint = {l.mint: l for l in launches}
    rows: list[dict[str, Any]] = []
    drops = Counter()
    for ev in onsets:
        if require_uncensored and ev.get("host_left_censored"):
            drops["host_left_censored"] += 1
            continue
        host = by_mint.get(ev["host_mint"])
        if host is None:
            drops["host_not_in_stream"] += 1
            continue
        t0 = _epoch(ev["onset_t"])
        pr = price_row(ev["host_mint"], t0, store, host, tape_end)
        if pr is None:
            drops["no_price"] += 1
            continue
        kinds = ev.get("match_kinds") or {}
        clones = max(int(ev["clone_count"]), 1)
        pr.update(
            {
                "family": ev["family_id"],
                "treated": 1,
                "taxonomy": ev["taxonomy"],
                "host_rule": ev.get("host_rule", "earliest"),
                "clone_count": float(ev["clone_count"]),
                "distinct_clone_deployers": float(ev["distinct_clone_deployers"]),
                "log_clone_spend_sol": _log1p(ev.get("clone_spend_sol")),
                "log_lag_from_host_s": math.log(max(ev["lag_from_host_s"], 1.0)),
                "log_lag_from_first_clone_s": math.log(max(ev["lag_from_first_clone_s"], 1.0)),
                "clone_deployer_max_share": float(ev["clone_deployer_max_share"]),
                "clone_devs_first_launch_frac": float(ev.get("clone_devs_first_launch", 0)) / clones,
                "is_parasite": 1.0 if ev["taxonomy"] == "parasite" else 0.0,
                "is_farm": 1.0 if ev["taxonomy"] in ("farm", "self_farm") else 0.0,
                "match_uri": 1.0 if kinds.get("uri") else 0.0,
                "match_image": 1.0 if kinds.get("image") else 0.0,
                "match_symbol": 1.0 if (kinds.get("symbol") or kinds.get("symbol_squashed")) else 0.0,
                "match_name": 1.0 if (kinds.get("name") or kinds.get("name_near")) else 0.0,
                "lag_from_host_s": float(ev["lag_from_host_s"]),
                "members": ev["members"],
            }
        )
        rows.append(add_features(pr))
    rows.sort(key=lambda r: r["t_post"])
    return rows, dict(drops)


def build_clone_cohort(
    launches: Sequence[Launch],
    onsets: Sequence[dict[str, Any]],
    det: SwarmDetector,
    store: CandleStore,
    tape_end: float,
) -> list[dict[str, Any]]:
    """The other reading of the hypothesis: buy the *imitators*, at their own launch.

    "Positions that will massively gain from them when they are even slightly legitimate"
    parses at least as naturally as *buy the clones* as it does *buy the host* — a clone
    launched into a live attention wave is the cheapest possible way to be long that wave,
    and unlike the host it can be entered at its own launch price with no chase.

    A row exists only for a clone that launched **at or after** its family's onset, because
    only then did a detector know the swarm existed; a clone that launched before the third
    member is not a decision anybody could have made. Entry is the clone's own launch minute,
    which is the first price a taker could pay.
    """
    by_mint = {l.mint: l for l in launches}
    # Join event -> family by HOST MINT, never by family id: a merge renames the family, so
    # the id on an already-emitted onset row can refer to a lineage that no longer exists.
    onset_by_host: dict[str, dict[str, Any]] = {}
    for ev in onsets:
        prev = onset_by_host.get(ev["host_mint"])
        if prev is None or ev["onset_t"] < prev["onset_t"]:
            onset_by_host[ev["host_mint"]] = ev

    rows: list[dict[str, Any]] = []
    for fam in det.families():
        if len(fam.members) < 2:
            continue
        candidates = [onset_by_host[m.mint] for m in fam.members if m.mint in onset_by_host]
        if not candidates:
            continue
        ev = min(candidates, key=lambda e: e["onset_t"])
        t_onset = _epoch(ev["onset_t"])
        host_mint = ev["host_mint"]
        ordered = sorted(fam.members, key=lambda m: m.t)
        for i, m in enumerate(ordered):
            if m.mint == host_mint or m.t < t_onset:
                continue
            ln = by_mint.get(m.mint)
            if ln is None:
                continue
            pr = price_row(m.mint, m.t, store, ln, tape_end)
            if pr is None:
                continue
            host_series = store.get(host_mint)
            host_mcap = (mark_at(host_series, m.t) or 0.0) * PUMP_SUPPLY if host_series else 0.0
            pr.update(
                {
                    "family": fam.fid,
                    "treated": 1,
                    "taxonomy": ev["taxonomy"],
                    "clone_index": float(i),
                    "log_since_host_s": math.log(max(m.t - _epoch(ev["host_t"]), 1.0)),
                    "log_since_onset_s": math.log(max(m.t - t_onset, 1.0)),
                    "log_host_mcap_now": math.log(max(host_mcap, 1e-9)),
                    "swarm_size_at_launch": float(sum(1 for o in ordered if o.t <= m.t)),
                }
            )
            rows.append(add_features(pr))
    rows.sort(key=lambda r: r["t_post"])
    return rows


def build_launch_controls(
    treated: Sequence[dict[str, Any]],
    launches: Sequence[Launch],
    excluded: set[str],
    store: CandleStore,
    tape_end: float,
    *,
    ratio: int = 2,
    caliper: float = 0.35,
    seed: int = 20260815,
) -> list[dict[str, Any]]:
    """Controls for the clone arm: ordinary launches, entered at *their* launch minute.

    The relevant covariates collapse to two here, because at launch every coin has the same
    age (zero) and the same trading history (none): the dev buy and the resulting market cap.
    Calendar proximity is enforced separately — a control must launch within ten minutes of
    its treated clone, so both are entered into the same market.
    """
    import numpy as np

    rng = random.Random(seed)
    pool = [ln for ln in launches if ln.mint not in excluded and store.get(ln.mint)]
    pool.sort(key=lambda l: l.t)
    pool_t = [l.t for l in pool]
    feats = ("log_dev_buy_sol", "log_mcap_at_onset")
    tmat = np.nan_to_num(
        np.array([[r[f] for f in feats] for r in treated], dtype=float), nan=0.0
    )
    mu, sd = tmat.mean(axis=0), tmat.std(axis=0)
    sd[sd == 0] = 1.0

    used: set[str] = set()
    out: list[dict[str, Any]] = []
    order = list(range(len(treated)))
    rng.shuffle(order)
    for idx in order:
        tr = treated[idx]
        t0 = tr["t_post"]
        lo = bisect.bisect_left(pool_t, t0 - 600.0)
        hi = bisect.bisect_right(pool_t, t0 + 600.0)
        target = (np.array([tr[f] for f in feats], dtype=float) - mu) / sd
        cands = []
        for ln in pool[lo:hi]:
            if ln.mint in used or ln.mint == tr["mint"]:
                continue
            pr = price_row(ln.mint, ln.t, store, ln, tape_end)
            if pr is None:
                continue
            pr = add_features(pr)
            v = (np.array([pr[f] for f in feats], dtype=float) - mu) / sd
            if not np.all(np.isfinite(v)):
                continue
            dist = float(np.sqrt(((v - target) ** 2).sum()))
            if dist > caliper * math.sqrt(len(feats)):
                continue
            cands.append((dist, pr))
        cands.sort(key=lambda x: x[0])
        for dist, pr in cands[:ratio]:
            used.add(pr["mint"])
            pr.update(
                {
                    "family": f"ctl:{tr['family']}",
                    "treated": 0,
                    "taxonomy": "control",
                    "matched_to": tr["mint"],
                    "match_distance": dist,
                }
            )
            out.append(pr)
    out.sort(key=lambda r: r["t_post"])
    return out


def swarmed_mints(det: SwarmDetector, min_size: int = 2) -> set[str]:
    out: set[str] = set()
    for fam in det.families():
        if len(fam.members) >= min_size:
            out.update(m.mint for m in fam.members)
    return out


#: Covariates the match must balance. `momentum_so_far` and `log_vol_sol_so_far` are the
#: load-bearing ones and the reason a first attempt at this study would be wrong: a coin
#: that attracts clones is, by construction, a coin that has *already moved*, and "coins
#: that just moved keep mean-reverting" is not the operator's hypothesis. Matching only on
#: (mcap, age, dev buy) left |SMD| up to 0.67 and produced a −11% "effect" that was mostly
#: this.
MATCH_COLUMNS = (
    "log_mcap_at_onset",
    "log_age_at_onset_s",
    "log_dev_buy_sol",
    "log_vol_sol_so_far",
    "momentum_so_far",
    "traded_minutes_so_far",
)


def build_controls(
    treated: Sequence[dict[str, Any]],
    launches: Sequence[Launch],
    excluded: set[str],
    store: CandleStore,
    tape_end: float,
    *,
    ratio: int = 2,
    caliper: float = 0.25,
    per_covariate_caliper: float = 0.5,
    seed: int = 20260815,
    columns: Sequence[str] = MATCH_COLUMNS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Matched never-swarmed hosts, evaluated at the same wall-clock instant.

    The counterfactual has to hold four things fixed or it is not a counterfactual: the
    **market regime** (same minute of the same tape), the coin's **age**, its **size**, and —
    the one that is easy to forget and decides the answer — **how much it had already
    moved**. A control is a coin that already existed at the treated coin's onset instant, is
    priced at that instant, and never belonged to a family that reached onset size, so a
    clone can never enter as a "control".

    Greedy nearest-neighbour on standardized :data:`MATCH_COLUMNS`, without replacement, in a
    seeded random order over treated rows, under **two** calipers: a Euclidean one on the
    standardized vector and a per-covariate one, because a small total distance can still
    hide one badly-matched dimension. Balance is reported before and after; a run whose SMDs
    do not come inside 0.1 has not earned a causal reading and the report says so.
    """
    rng = random.Random(seed)
    import numpy as np

    pool: list[Launch] = [
        ln for ln in launches if ln.mint not in excluded and store.get(ln.mint)
    ]
    pool.sort(key=lambda l: l.t)
    pool_t = [l.t for l in pool]

    feats = list(columns)
    tmat = np.array([[r[f] for f in feats] for r in treated], dtype=float)
    tmat = np.nan_to_num(tmat, nan=0.0, posinf=0.0, neginf=0.0)
    mu, sd = tmat.mean(axis=0), tmat.std(axis=0)
    sd[sd == 0] = 1.0

    used: set[str] = set()
    controls: list[dict[str, Any]] = []
    order = list(range(len(treated)))
    rng.shuffle(order)
    unmatched = 0
    # cache priced candidates per evaluation instant — many treated rows share a minute
    for idx in order:
        tr = treated[idx]
        t0, age = tr["t_post"], tr["age_at_onset_s"]
        lo = bisect.bisect_left(pool_t, t0 - age * 6.0 - 60.0)
        hi = bisect.bisect_right(pool_t, t0 - max(age / 6.0, 5.0))
        target = (np.array([tr[f] for f in feats], dtype=float) - mu) / sd
        cands: list[tuple[float, dict[str, Any]]] = []
        for ln in pool[lo:hi]:
            if ln.mint in used or ln.mint == tr["mint"]:
                continue
            pr = price_row(ln.mint, t0, store, ln, tape_end)
            if pr is None:
                continue
            pr = add_features(pr)
            v = (np.array([pr[f] for f in feats], dtype=float) - mu) / sd
            if not np.all(np.isfinite(v)):
                continue
            delta = np.abs(v - target)
            if float(delta.max()) > per_covariate_caliper:
                continue
            dist = float(np.sqrt((delta**2).sum()))
            if dist > caliper * math.sqrt(len(feats)):
                continue
            cands.append((dist, pr))
        cands.sort(key=lambda x: x[0])
        taken = 0
        for dist, pr in cands[:ratio]:
            used.add(pr["mint"])
            pr.update(
                {
                    "family": f"ctl:{tr['family']}",
                    "treated": 0,
                    "taxonomy": "control",
                    "match_distance": dist,
                    "matched_to": tr["mint"],
                }
            )
            for c in SWARM_COLUMNS:
                pr.setdefault(c, 0.0)
            controls.append(pr)
            taken += 1
        if taken == 0:
            unmatched += 1
    controls.sort(key=lambda r: r["t_post"])
    matched_treated = {c["matched_to"] for c in controls}
    return controls, {
        "pool": len(pool),
        "controls": len(controls),
        "treated_matched": len(matched_treated),
        "treated_unmatched": unmatched,
        "ratio_target": ratio,
        "caliper_sd": caliper,
        "per_covariate_caliper_sd": per_covariate_caliper,
    }


def balance_table(
    treated: Sequence[dict[str, Any]], controls: Sequence[dict[str, Any]], columns: Sequence[str]
) -> list[dict[str, Any]]:
    """Standardized mean difference per covariate. |SMD| < 0.1 is the usual "balanced"."""
    import numpy as np

    out = []
    for c in columns:
        a = np.array([r[c] for r in treated], dtype=float)
        b = np.array([r[c] for r in controls], dtype=float)
        a, b = a[np.isfinite(a)], b[np.isfinite(b)]
        if len(a) < 2 or len(b) < 2:
            continue
        pooled = math.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2) or 1.0
        out.append(
            {
                "column": c,
                "treated_mean": float(a.mean()),
                "control_mean": float(b.mean()),
                "smd": float((a.mean() - b.mean()) / pooled),
            }
        )
    return out


# ---------------------------------------------------------------------------
# splits, metrics, nulls
# ---------------------------------------------------------------------------


def temporal_family_split(
    rows: Sequence[dict[str, Any]], *, frac: float = 0.5
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    """Temporal split with the **family** as the indivisible entity.

    A host and its clones are one entity: they share a deployer network, an image, and a
    minute of market regime. PROGRAM.md §3.2 — one actor must never straddle train and test.
    A control inherits its treated row's family id (prefixed) so a matched pair also never
    straddles, which is the leak a naive row-level split would introduce here.
    """
    if not rows:
        return [], [], 0.0
    ordered = sorted(rows, key=lambda r: r["t_post"])
    cut = ordered[int(len(ordered) * frac)]["t_post"]
    first: dict[str, float] = {}
    for r in ordered:
        key = r["family"].removeprefix("ctl:")
        first.setdefault(key, r["t_post"])
    train = [r for r in ordered if first[r["family"].removeprefix("ctl:")] < cut]
    test = [r for r in ordered if first[r["family"].removeprefix("ctl:")] >= cut]
    return train, test, cut


def auc_auprc(labels: Sequence[int], scores: Sequence[float]) -> tuple[float, float]:
    from sklearn.metrics import average_precision_score, roc_auc_score

    if len(set(labels)) < 2:
        return float("nan"), float("nan")
    return float(roc_auc_score(labels, scores)), float(average_precision_score(labels, scores))


def cluster_bootstrap_auc(
    labels: Sequence[int],
    scores: Sequence[float],
    groups: Sequence[str],
    *,
    draws: int = 1500,
    seed: int = 11,
) -> tuple[float, float]:
    import numpy as np
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(seed)
    index: dict[str, list[int]] = defaultdict(list)
    for i, g in enumerate(groups):
        index[g].append(i)
    keys = list(index)
    ya, sa = np.asarray(labels), np.asarray(scores)
    out = []
    for _ in range(draws):
        idx: list[int] = []
        for k in rng.choice(len(keys), size=len(keys), replace=True):
            idx.extend(index[keys[k]])
        y = ya[idx]
        if len(set(y.tolist())) < 2:
            continue
        out.append(float(roc_auc_score(y, sa[idx])))
    if not out:
        return float("nan"), float("nan")
    lo, hi = np.percentile(out, [2.5, 97.5])
    return float(lo), float(hi)


def usable_columns(
    rows: Sequence[dict[str, Any]], columns: Sequence[str], *, max_corr: float = 0.98
) -> list[str]:
    import numpy as np

    if not rows:
        return list(columns)
    matrix = np.array([[r.get(c, 0.0) for c in columns] for r in rows], dtype=float)
    matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)
    keep: list[str] = []
    kept: list[int] = []
    for i, name in enumerate(columns):
        col = matrix[:, i]
        if float(col.std()) < 1e-9:
            continue
        dup = False
        for j in kept:
            other = matrix[:, j]
            if float(other.std()) < 1e-9:
                continue
            corr = float(np.corrcoef(col, other)[0, 1])
            if corr == corr and abs(corr) >= max_corr:
                dup = True
                break
        if not dup:
            keep.append(name)
            kept.append(i)
    return keep


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

    def mat(rows: Sequence[dict[str, Any]]) -> Any:
        m = np.array([[r.get(c, 0.0) for c in columns] for r in rows], dtype=float)
        return np.nan_to_num(m, nan=0.0, posinf=0.0, neginf=0.0)

    x_train, x_test = mat(train), mat(test)
    y_train = np.array([r[label_key] for r in train], dtype=int)
    y_test = [int(r[label_key]) for r in test]
    if len(set(y_train.tolist())) < 2 or not len(x_test):
        return y_test, [0.5] * len(y_test)
    # No class weighting: it decalibrates the probability an EV decision needs, and the base
    # rate here is not extreme (PROGRAM.md §1.3, §3.3 — and never SMOTE).
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
    model.fit(x_train, y_train)
    return y_test, [float(p) for p in model.predict_proba(x_test)[:, 1]]


def null_iid(rows: Sequence[dict[str, Any]], label_key: str, rng: random.Random) -> list[dict]:
    labels = [r[label_key] for r in rows]
    rng.shuffle(labels)
    return [{**r, label_key: v} for r, v in zip(rows, labels, strict=True)]


def null_rotation(rows: Sequence[dict[str, Any]], label_key: str, rng: random.Random) -> list[dict]:
    """Circular shift of outcomes against features in time order.

    An i.i.d. shuffle destroys the outcome series' own autocorrelation and therefore
    understates how easily a correlated predictor lines up with a correlated target. Two
    prior lanes here saw an apparent 73× collapse to 0.98× when this null replaced that one.
    """
    ordered = sorted(rows, key=lambda r: r["t_post"])
    labels = [r[label_key] for r in ordered]
    n = len(labels)
    if n < 3:
        return list(ordered)
    shift = rng.randrange(1, n)
    return [
        {**r, label_key: v} for r, v in zip(ordered, labels[shift:] + labels[:shift], strict=True)
    ]


def null_swarm_permutation(rows: Sequence[dict[str, Any]], rng: random.Random) -> list[dict]:
    """Reassign the swarm block across rows, keeping every timing and market feature.

    The null aimed at the hypothesis itself, and the exact analogue of the caller-identity
    permutation that beat the real assignment 24/24 in RESULT_callout_edge.md. If *which*
    coin got swarmed carries nothing, scrambling the swarm block costs nothing.
    """
    donors = [tuple(r.get(c, 0.0) for c in SWARM_COLUMNS) for r in rows]
    rng.shuffle(donors)
    return [
        {**r, **dict(zip(SWARM_COLUMNS, d, strict=True))}
        for r, d in zip(rows, donors, strict=True)
    ]


def bh_fdr(pvals: Sequence[float], q: float = 0.10) -> list[bool]:
    """Benjamini–Hochberg. Returns the rejection vector at level ``q``."""
    n = len(pvals)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: pvals[i])
    out = [False] * n
    kmax = -1
    for rank, i in enumerate(order, 1):
        if pvals[i] <= q * rank / n:
            kmax = rank
    for rank, i in enumerate(order, 1):
        if rank <= kmax:
            out[i] = True
    return out


# ---------------------------------------------------------------------------
# reporting helpers
# ---------------------------------------------------------------------------


def summarise(rows: Sequence[dict[str, Any]], h: int, label: str, out=sys.stdout) -> dict[str, Any]:
    import numpy as np

    usable = [r for r in rows if not r[f"admin{h}"]]
    if not usable:
        print(f"  {label:<30} n=0 (all {len(rows)} rows run past the tape)", file=out)
        return {"label": label, "n": 0}
    r = np.array([x[f"r{h}"] for x in usable], dtype=float)
    live = np.array([x[f"live{h}"] for x in usable], dtype=bool)
    mx = np.array([x[f"max{h}"] for x in usable], dtype=float)
    stat = {
        "label": label,
        "n": int(len(r)),
        "mean": float(r.mean()),
        "median": float(np.median(r)),
        "p_up": float((r > 0).mean()),
        "p_2x": float((r >= 1.0).mean()),
        "live": float(live.mean()),
        "mean_max": float(mx.mean()),
        "dropped_past_tape": len(rows) - len(usable),
    }
    print(
        f"  {label:<30} n={stat['n']:<5} mean={stat['mean']:+8.2%} med={stat['median']:+8.2%} "
        f"p(up)={stat['p_up']:5.1%} p(2x)={stat['p_2x']:5.1%} live={stat['live']:5.1%} "
        f"max={stat['mean_max']:+7.2%}",
        file=out,
    )
    return stat


def decompose(
    treated: Sequence[dict[str, Any]],
    controls: Sequence[dict[str, Any]],
    h: int,
    out=sys.stdout,
) -> dict[str, Any]:
    """Split every arm into rows that traded inside the window and rows that did not.

    This is the diagnostic that decides whether a return difference is information or
    bookkeeping. A coin with no trade after entry is marked at its last close, so its return
    is **exactly 0.00%** — and an arm made mostly of such coins will "beat" an arm of live
    coins that are merely falling, without a single tradeable cent changing hands.

    Both halves are printed because neither alone is honest: the live-only half is the
    survivorship-biased number the callout study showed flipping −14.6% to +25%, and the
    all-rows half is the one that hides a composition difference. If the two arms differ only
    in the *dead* fraction, the headline is an artifact and the report says so.
    """
    import numpy as np

    res: dict[str, Any] = {}
    for name, rows in (("treated", treated), ("control", controls)):
        usable = [r for r in rows if not r[f"admin{h}"]]
        if not usable:
            continue
        live = [r for r in usable if r[f"live{h}"]]
        dead = [r for r in usable if not r[f"live{h}"]]
        lr = np.array([r[f"r{h}"] for r in live], dtype=float) if live else np.array([])
        dr = np.array([r[f"r{h}"] for r in dead], dtype=float) if dead else np.array([])
        res[name] = {
            "n": len(usable),
            "p_dead": len(dead) / len(usable),
            "mean_live": float(lr.mean()) if len(lr) else float("nan"),
            "median_live": float(np.median(lr)) if len(lr) else float("nan"),
            "mean_dead": float(dr.mean()) if len(dr) else float("nan"),
        }
        print(
            f"    {name:<9} n={len(usable):<5} no-trade-in-window={res[name]['p_dead']:5.1%} "
            f"(their mean return {res[name]['mean_dead']:+7.2%}, ~0 by construction) | "
            f"TRADED rows n={len(lr):<5} mean={res[name]['mean_live']:+8.2%} "
            f"med={res[name]['median_live']:+8.2%}",
            file=out,
        )
    if "treated" in res and "control" in res:
        a = [r[f"r{h}"] for r in treated if not r[f"admin{h}"] and r[f"live{h}"]]
        b = [r[f"r{h}"] for r in controls if not r[f"admin{h}"] and r[f"live{h}"]]
        _u, p = mannwhitney(a, b)
        res["live_only_p"] = p
        res["live_only_diff"] = res["treated"]["mean_live"] - res["control"]["mean_live"]
        print(
            f"    -> TRADED-ONLY difference {res['live_only_diff']:+.2%} mean, "
            f"Mann-Whitney p={p:.4f}   "
            f"(dead-fraction gap {res['treated']['p_dead'] - res['control']['p_dead']:+.1%})",
            file=out,
        )
    return res


def mde(
    treated: Sequence[dict[str, Any]],
    controls: Sequence[dict[str, Any]],
    h: int,
    *,
    seed: int = 20260815,
    draws: int = 300,
    power: float = 0.80,
    alpha: float = 0.05,
    out=sys.stdout,
) -> dict[str, Any]:
    """Smallest multiplicative return shift this cohort could have detected.

    A null without a power floor is not a finding, it is a shrug. This resamples the two
    observed arms with replacement, multiplies every treated return by ``(1+δ)``, and finds
    the smallest δ at which a two-sided Mann-Whitney rejects at ``alpha`` in ``power`` of
    draws. The answer is a statement about what the study *could* have seen, and it is the
    number that decides whether "no effect" means "no effect" or "no telescope".

    Multiplicative rather than additive because these are prices: adding 10 points to a coin
    that fell 90% is not a thing that can happen to a position.
    """
    import numpy as np

    a0 = np.array([r[f"r{h}"] for r in treated if not r[f"admin{h}"]], dtype=float)
    b0 = np.array([r[f"r{h}"] for r in controls if not r[f"admin{h}"]], dtype=float)
    if len(a0) < 8 or len(b0) < 8:
        return {"h": h, "mde": None, "reason": "too few rows"}
    from scipy.stats import mannwhitneyu

    rng = np.random.default_rng(seed)
    for delta in (0.05, 0.10, 0.15, 0.25, 0.40, 0.60, 1.00, 1.50, 2.50):
        hits = 0
        for _ in range(draws):
            a = rng.choice(a0, size=len(a0), replace=True)
            b = rng.choice(b0, size=len(b0), replace=True)
            shifted = (1.0 + a) * (1.0 + delta) - 1.0
            try:
                p = mannwhitneyu(shifted, b, alternative="two-sided").pvalue
            except ValueError:
                continue
            hits += p < alpha
        if hits / draws >= power:
            print(
                f"  MDE at {h//60}m (n={len(a0)} vs {len(b0)}): a multiplicative shift of "
                f"{delta:+.0%} would be detected at {power:.0%} power / α={alpha:.2f}. "
                f"Smaller effects are invisible to this cohort.",
                file=out,
            )
            return {"h": h, "n_treated": len(a0), "n_control": len(b0), "mde": delta}
    print(
        f"  MDE at {h//60}m (n={len(a0)} vs {len(b0)}): even a +250% shift is NOT reliably "
        f"detected. This cohort cannot answer the question at this horizon.",
        file=out,
    )
    return {"h": h, "n_treated": len(a0), "n_control": len(b0), "mde": None}


def mannwhitney(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    from scipy.stats import mannwhitneyu

    if len(a) < 3 or len(b) < 3:
        return float("nan"), float("nan")
    u, p = mannwhitneyu(a, b, alternative="two-sided")
    return float(u), float(p)


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------


def report(  # noqa: C901 - a study report is a linear script by nature
    *,
    k: int = 3,
    window_s: float = 1800.0,
    horizon: int = 3600,
    seed: int = 20260815,
    as_json: bool = False,
    emit_candidates: bool = True,
    days: int = 3,
    tape_end_pin: float | None = None,
    retro_day: str | None = None,
) -> dict[str, Any]:
    out = sys.stderr if as_json else sys.stdout
    store = CandleStore()
    result: dict[str, Any] = {"config": {"k": k, "window_s": window_s, "horizon": horizon, "seed": seed}}

    launches, stats, intervals = load_stream(days, retro_day)
    if tape_end_pin is not None:
        # The collectors are live, so every extra minute of tape makes one more row
        # horizon-eligible and moves every number. Pinning the end is what makes a reported
        # run reproducible from the same tapes -- the same discipline RESULT_callout_edge.md
        # used for exactly this reason.
        launches = [l for l in launches if l.t <= tape_end_pin]
        stats["pinned_tape_end"] = tape_end_pin
    if not launches:
        print("no launches in stream", file=out)
        return result
    tape_end = tape_end_pin if tape_end_pin is not None else max(l.t for l in launches)
    result["stream"] = {**stats, "tape_end": tape_end}

    print("=" * 92, file=out)
    print("IMITATION SIGNAL — does a swarm of clones say anything about the host?", file=out)
    print("=" * 92, file=out)
    span_h = (launches[-1].t - launches[0].t) / 3600
    listen_h = sum(b - a for a, b in intervals) / 3600 if intervals else span_h
    print(
        f"\nstream [{stats.get('source','?')}]: {len(launches)} launches over {span_h:.2f} h of tape "
        f"({listen_h:.2f} h demonstrably listening, {len(intervals) if intervals else 1} windows), "
        f"{stats['vendor_clock']} on the vendor clock, {stats.get('census_only',0)} REST-only, "
        f"{stats.get('firehose_dupe',0)} socket duplicates dropped",
        file=out,
    )
    cached = sum(1 for l in launches if store.has(l.mint))
    ages = [tape_end - store.fetched_at(l.mint) for l in launches if store.has(l.mint)]
    stale = sum(1 for a in ages if a > 300.0)
    print(
        f"        candles cached for {cached}/{len(launches)} ({cached/len(launches):.1%}); "
        f"{stale} ({stale/max(cached,1):.1%}) were fetched more than 5 min before the tape "
        f"ends",
        file=out,
    )
    if stale > cached * 0.05:
        print(
            "        WARNING: a stale cache admin-censors horizons and silently drops the "
            "coins that\n        died early — run `--fetch --full` before trusting any "
            "number below.",
            file=out,
        )
    result["cache"] = {"cached": cached, "stale": stale}

    # ---- 0. detection -----------------------------------------------------
    onsets, det = run_detector(launches, store, k=k, window_s=window_s)
    fams = [f for f in det.families() if len(f.members) >= 2]
    tax_fam = Counter(
        taxonomy(len(f.members) - 1, Counter(m.deployer for m in f.members[1:]), f.members[0].deployer)
        for f in fams
    )
    tax_onset = Counter(o["taxonomy"] for o in onsets)
    host_rule = Counter(o.get("host_rule", "earliest") for o in onsets)
    print(f"\n--- 0. TAXONOMY ---", file=out)
    print(f"  families size>=2: {len(fams)}   {dict(tax_fam)}", file=out)
    print(f"  onsets at k>={k}:  {len(onsets)}   {dict(tax_onset)}", file=out)
    print(f"  host rule fired:  {dict(host_rule)}", file=out)
    parasite_share = tax_onset.get("parasite", 0) / max(len(onsets), 1)
    print(
        f"  parasite share of onsets: {parasite_share:.1%}  "
        f"(farm+self_farm {(tax_onset.get('farm',0)+tax_onset.get('self_farm',0))/max(len(onsets),1):.1%})",
        file=out,
    )
    print(
        "  NOTE: distinct-deployer count is an UPPER bound on independence. Sybil wallets "
        "are free and\n        MELT puts 36.5% of supply in coordinated hands; nothing here "
        "clusters wallets by funding\n        ancestry, so a 'parasite' swarm of 4 wallets "
        "may be one actor. Treated as such in §7.",
        file=out,
    )
    result["taxonomy"] = {"families": dict(tax_fam), "onsets": dict(tax_onset), "host_rule": dict(host_rule)}

    # ---- 1. onset lag -----------------------------------------------------
    import numpy as np

    print(f"\n--- 1. ONSET LAG — how fast is 'fast'? ---", file=out)
    lag_host = np.array([o["lag_from_host_s"] for o in onsets], dtype=float)
    lag_clone = np.array([o["lag_from_first_clone_s"] for o in onsets], dtype=float)
    if len(lag_host):
        for name, arr in (("host launch -> onset", lag_host), ("first clone -> onset", lag_clone)):
            qs = np.percentile(arr, [10, 25, 50, 75, 90])
            print(
                f"  {name:<24} p10={qs[0]:7.0f}s p25={qs[1]:7.0f}s p50={qs[2]:7.0f}s "
                f"p75={qs[3]:7.0f}s p90={qs[4]:7.0f}s",
                file=out,
            )
        result["onset_lag"] = {
            "host_p50_s": float(np.median(lag_host)),
            "clone_p50_s": float(np.median(lag_clone)),
        }
        # The ingestion term, measured on this tape rather than quoted: for every launch the
        # census dated, how far behind pump.fun's own created_timestamp our socket was.
        lat = sorted(
            l.t_ingest - l.t
            for l in launches
            if l.t_source == "vendor" and l.t_ingest and 0 <= l.t_ingest - l.t < 60
        )
        if lat:
            lq = lambda p: lat[min(len(lat) - 1, int(p * len(lat)))]  # noqa: E731
            print(
                f"  ingestion lag (our socket minus pump.fun's created_timestamp, n={len(lat)}): "
                f"p50={lq(.5):.2f}s p95={lq(.95):.2f}s, never negative",
                file=out,
            )
            result["ingest_lag"] = {"p50": lq(0.5), "p95": lq(0.95), "n": len(lat)}
        print(
            "  So the budget decomposes: ~1 s to hear about a launch, then the detection lag\n"
            "  above to be sure it is a swarm. The second term dominates the first by two\n"
            "  orders of magnitude, which means 'being fast' is not an infrastructure problem —\n"
            "  it is a question of how many clones you are willing to wait for.",
            file=out,
        )

    # ---- 2. the event study ----------------------------------------------
    treated, drops = build_cohort(launches, onsets, store, tape_end)
    print(f"\n--- 2. EVENT STUDY — host forward return from ONSET (not from launch) ---", file=out)
    print(f"  treated rows: {len(treated)}   dropped: {dict(drops)}", file=out)
    if len(treated) < 12:
        print("  cohort too small to say anything. Stop here.", file=out)
        result["verdict"] = "insufficient_data"
        return result

    stats_by_h = {}
    for h in HORIZONS_S:
        print(f"  horizon {h//60:>3d}m:", file=out)
        stats_by_h[h] = {
            "all": summarise(treated, h, "all onsets", out),
            "parasite": summarise([r for r in treated if r["taxonomy"] == "parasite"], h, "parasite only", out),
            "farm": summarise([r for r in treated if r["taxonomy"] in ("farm", "self_farm")], h, "farm/self_farm only", out),
        }
    result["returns"] = stats_by_h

    # returns conditional on how early the clones arrived — the too-early / too-late question
    print(f"\n  return at {horizon//60}m by onset lag (is the clone arrival early or late?):", file=out)
    lag_bins = [(0, 60), (60, 300), (300, 900), (900, 3600), (3600, 1e9)]
    lag_rows = []
    for lo, hi in lag_bins:
        sub = [r for r in treated if lo <= r["lag_from_host_s"] < hi and not r[f"admin{horizon}"]]
        if len(sub) < 3:
            print(f"    lag {lo:>5.0f}-{hi if hi<1e8 else float('inf'):>6.0f}s  n={len(sub)} (too few)", file=out)
            continue
        r = np.array([x[f"r{horizon}"] for x in sub])
        m = np.array([x["momentum_so_far"] for x in sub])
        print(
            f"    lag {lo:>5.0f}-{hi if hi<1e8 else float('inf'):>6.0f}s  n={len(r):<4d} "
            f"mean={r.mean():+8.2%} med={np.median(r):+8.2%} p(up)={float((r>0).mean()):5.1%} "
            f"| momentum already banked at onset: med={np.median(m):+7.2%}",
            file=out,
        )
        lag_rows.append({"lo": lo, "hi": hi, "n": len(r), "mean": float(r.mean()), "p_up": float((r > 0).mean())})
    result["by_lag"] = lag_rows

    # ---- 2a. dose-response, which is what the theory actually predicts ----
    print(f"\n--- 2a. DOSE-RESPONSE — the sharpest form of the costly-signal claim ---", file=out)
    print(
        "  Pre-declared from the theory, not chosen after looking: if a swarm is a costly\n"
        "  signal, its information content must scale with the number of INDEPENDENT parties\n"
        "  paying (distinct clone deployers) and with the amount PAID (clone spend in SOL).\n"
        "  A binary swarmed/not contrast can be null while a real dose-response survives, and\n"
        "  a dose-response that is flat is a much stronger refutation than a failed t-test.\n"
        "  Reported as Spearman rank correlation with the host's forward return, one row per\n"
        "  onset, so no coin is counted twice.",
        file=out,
    )
    from scipy.stats import spearmanr

    dose_rows = []
    for h in HORIZONS_S:
        usable = [r for r in treated if not r[f"admin{h}"]]
        if len(usable) < 12:
            continue
        y = [r[f"r{h}"] for r in usable]
        for name in ("distinct_clone_deployers", "clone_count", "log_clone_spend_sol"):
            x = [r[name] for r in usable]
            if len(set(x)) < 3:
                continue
            rho, p = spearmanr(x, y)
            dose_rows.append({"h": h, "var": name, "rho": float(rho), "p": float(p), "n": len(y)})
            print(
                f"  r{h//60:>3d}m ~ {name:<26} rho={rho:+.3f} p={p:.4f} n={len(y)}",
                file=out,
            )
    result["dose_response"] = dose_rows

    # ---- 2b. the other reading: buy the clones ---------------------------
    print(
        f"\n--- 2b. THE CLONE ARM — buying the imitators at their own launch ---", file=out
    )
    print(
        '  "positions that will massively gain from THEM" reads as easily as buy-the-clones\n'
        "  as it does buy-the-host, and a clone is the cheaper entry: its own launch minute,\n"
        "  no chase. Only clones that launched AT OR AFTER their family's onset are counted —\n"
        "  a clone that arrived before the third member was not a decision anyone could make.",
        file=out,
    )
    clones = build_clone_cohort(launches, onsets, det, store, tape_end)
    clone_ctl = build_launch_controls(
        clones, launches, swarmed_mints(det, min_size=k), store, tape_end, seed=seed
    )
    print(f"  clone rows: {len(clones)}   matched launch controls: {len(clone_ctl)}", file=out)
    clone_out: dict[str, Any] = {"n": len(clones), "n_control": len(clone_ctl)}
    if len(clones) >= 12:
        cbal = balance_table(clones, clone_ctl, ("log_dev_buy_sol", "log_mcap_at_onset")) if clone_ctl else []
        for b in cbal:
            print(
                f"    balance {b['column']:<22} treated={b['treated_mean']:+8.3f} "
                f"control={b['control_mean']:+8.3f} smd={b['smd']:+.3f}",
                file=out,
            )
        clone_out["balance"] = cbal
        cdiffs = []
        for h in HORIZONS_S:
            ts = summarise(clones, h, f"clones ({h//60}m)", out)
            if clone_ctl:
                cs = summarise(clone_ctl, h, f"launch controls ({h//60}m)", out)
                if ts["n"] and cs["n"]:
                    a = [r[f"r{h}"] for r in clones if not r[f"admin{h}"]]
                    b2 = [r[f"r{h}"] for r in clone_ctl if not r[f"admin{h}"]]
                    _u, p = mannwhitney(a, b2)
                    print(
                        f"    -> difference {ts['mean']-cs['mean']:+.2%} mean, "
                        f"{ts['median']-cs['median']:+.2%} median, Mann-Whitney p={p:.4f}",
                        file=out,
                    )
                    cdiffs.append({"h": h, "diff_mean": ts["mean"] - cs["mean"], "p": p})
                    clone_out.setdefault("decompose", {})[h] = decompose(clones, clone_ctl, h, out)
        clone_out["diffs"] = cdiffs
        print(f"\n  POWER FLOOR for the clone arm:", file=out)
        clone_out["mde"] = [mde(clones, clone_ctl, h, seed=seed, out=out) for h in HORIZONS_S]
    result["clone_arm"] = clone_out

    # ---- 3. matched controls ---------------------------------------------
    print(f"\n--- 3. CONTROL ARM — matched, never-swarmed hosts at the same instant ---", file=out)
    # A coin excluded from the control pool is one that reached ONSET size, not merely one
    # that shared a ticker with somebody. At k=2 roughly 70% of all launches are in some
    # family — the ambient collision rate — and excluding all of them would leave a control
    # pool selected for having an unusual name, which is its own confound.
    excluded = swarmed_mints(det, min_size=k)
    controls, cstats = build_controls(treated, launches, excluded, store, tape_end, seed=seed)
    print(f"  {cstats}", file=out)
    result["control_stats"] = cstats
    matched_ids = {c["matched_to"] for c in controls}
    treated_m = [r for r in treated if r["mint"] in matched_ids]
    print(
        f"  comparison uses the {len(treated_m)} treated rows that FOUND a control; "
        f"{len(treated) - len(treated_m)} unmatched treated rows are excluded from §3 "
        f"(they remain in §2 and §4)",
        file=out,
    )
    if len(controls) >= 10 and len(treated_m) >= 10:
        bal = balance_table(treated_m, controls, MATCH_COLUMNS)
        worst = max((abs(b["smd"]) for b in bal), default=0.0)
        print("  covariate balance (|SMD| < 0.1 is balanced):", file=out)
        for b in bal:
            flag = "" if abs(b["smd"]) < 0.1 else ("  <- IMBALANCED" if abs(b["smd"]) >= 0.25 else "  <- marginal")
            print(
                f"    {b['column']:<24} treated={b['treated_mean']:+10.3f} "
                f"control={b['control_mean']:+10.3f} smd={b['smd']:+.3f}{flag}",
                file=out,
            )
        result["balance"] = bal
        result["balance_worst_smd"] = worst
        if worst >= 0.25:
            print(
                f"  WORST |SMD| = {worst:.2f}. The match did NOT succeed; every difference "
                f"below is\n  confounded by the covariate above and must not be read causally.",
                file=out,
            )
        print(f"\n  matched comparison at each horizon:", file=out)
        diffs = []
        for h in HORIZONS_S:
            ts = summarise(treated_m, h, f"treated ({h//60}m)", out)
            cs = summarise(controls, h, f"matched control ({h//60}m)", out)
            if ts["n"] and cs["n"]:
                a = [r[f"r{h}"] for r in treated_m if not r[f"admin{h}"]]
                b = [r[f"r{h}"] for r in controls if not r[f"admin{h}"]]
                _u, p = mannwhitney(a, b)
                d = ts["mean"] - cs["mean"]
                print(
                    f"    -> difference {d:+.2%} mean, {ts['median']-cs['median']:+.2%} median, "
                    f"{ts['p_up']-cs['p_up']:+.1%} p(up), Mann-Whitney p={p:.4f}",
                    file=out,
                )
                result.setdefault("decompose", {})[h] = decompose(treated_m, controls, h, out)
                diffs.append(
                    {
                        "h": h,
                        "diff_mean": d,
                        "diff_median": ts["median"] - cs["median"],
                        "diff_p_up": ts["p_up"] - cs["p_up"],
                        "p": p,
                    }
                )
        result["control_diffs"] = diffs
        print(f"\n  POWER FLOOR — what this cohort could have detected:", file=out)
        result["mde"] = [mde(treated_m, controls, h, seed=seed, out=out) for h in HORIZONS_S]

        # The hypothesis names PARASITES specifically. A farm's forty clones are one wallet's
        # inventory and say nothing about a host; pooling the two arms would let the farm
        # majority decide the answer to a question about the minority.
        par = [r for r in treated_m if r["taxonomy"] == "parasite"]
        par_ctl = [c for c in controls if c["matched_to"] in {r["mint"] for r in par}]
        if len(par) >= 8 and len(par_ctl) >= 8:
            print(f"\n  PARASITE arm only ({len(par)} treated, {len(par_ctl)} controls):", file=out)
            pdiffs = []
            for h in HORIZONS_S:
                ts = summarise(par, h, f"parasite ({h//60}m)", out)
                cs = summarise(par_ctl, h, f"their controls ({h//60}m)", out)
                if ts["n"] and cs["n"]:
                    a = [r[f"r{h}"] for r in par if not r[f"admin{h}"]]
                    b = [r[f"r{h}"] for r in par_ctl if not r[f"admin{h}"]]
                    _u, p = mannwhitney(a, b)
                    print(
                        f"    -> difference {ts['mean']-cs['mean']:+.2%} mean, "
                        f"{ts['median']-cs['median']:+.2%} median, Mann-Whitney p={p:.4f}",
                        file=out,
                    )
                    pdiffs.append({"h": h, "diff_mean": ts["mean"] - cs["mean"], "p": p})
            result["parasite_diffs"] = pdiffs

    # ---- 4. conditional information --------------------------------------
    print(f"\n--- 4. CONDITIONAL INFORMATION — does the swarm block beat the free columns? ---", file=out)
    pooled_all = sorted(treated + controls, key=lambda r: r["t_post"])
    # Two labels, because the sign of §2 decides which one is the trade. `up` is the
    # operator's original long framing. `down` is the one a short book consumes, and it is
    # the label with a usable base rate here: a dead coin marks *exactly* flat, so `r > 0`
    # collapses to a few percent and AUPRC on it is uninterpretable.
    labels = {
        f"up{horizon}": (lambda r: 1 if r[f"r{horizon}"] > 0 else 0, f"r{horizon//60}m > 0"),
        f"down{horizon}": (
            lambda r: 1 if r[f"r{horizon}"] <= -0.10 else 0,
            f"r{horizon//60}m <= -10% (a profitable short)",
        ),
    }
    model_out: dict[str, Any] = {}
    for label_key, (fn, desc) in labels.items():
        _model_block(pooled_all, label_key, fn, desc, horizon, seed, out, model_out)
    result["model"] = model_out

    # ---- 5. survival ------------------------------------------------------
    print(f"\n--- 5. SURVIVAL AND COMPETING RISKS — pricing the dead ---", file=out)
    result["survival"] = survival_block(treated, controls, horizon, out)

    # ---- 6. the two ambient nulls ----------------------------------------
    print(f"\n--- 6. AMBIENT NULLS — the same detector on two kinds of scrambled stream ---", file=out)
    print(
        "  PROGRAM.md §3.13: one null is a knob, not a test. Both are run and compared.\n"
        "    SHUFFLE  — launch identity permuted i.i.d. over the whole tape. Every symbol\n"
        "               keeps its frequency; same-symbol launches no longer arrive together.\n"
        "               This is the COLLISION FLOOR: what a detector finds in a world with\n"
        "               no imitation at all.\n"
        "    ROTATION — identity shifted as a block. Launch rate is near-constant, so a burst\n"
        "               survives intact and merely lands on a DIFFERENT host. This asks a\n"
        "               narrower question: is it the swarm, or just a coin with traction?",
        file=out,
    )
    amb: list[dict[str, Any]] = []
    for kind, streams in (
        ("shuffle", [shuffle_stream(launches, seed + i) for i in range(4)]),
        ("rotation", [rotate_stream(launches, s) for s in (900.0, 1800.0, 3600.0, 5400.0)]),
    ):
        for i, st in enumerate(streams):
            r_onsets, r_det = run_detector(st, store, k=k, window_s=window_s)
            r_fams = [f for f in r_det.families() if len(f.members) >= 2]
            r_treated, _ = build_cohort(st, r_onsets, store, tape_end)
            row: dict[str, Any] = {
                "null": kind,
                "draw": i,
                "families": len(r_fams),
                "onsets": len(r_onsets),
                "cohort": len(r_treated),
                "max_family": max((len(f.members) for f in r_fams), default=0),
            }
            usable = [r for r in r_treated if not r[f"admin{horizon}"]]
            if usable:
                rr = np.array([x[f"r{horizon}"] for x in usable])
                row.update({"mean": float(rr.mean()), "p_up": float((rr > 0).mean())})
            amb.append(row)
            print(
                f"  {kind:<9} draw {i}: families={row['families']:5d} onsets={row['onsets']:5d} "
                f"largest={row['max_family']:3d} "
                + (
                    f"mean r{horizon//60}m={row['mean']:+8.2%} p(up)={row['p_up']:5.1%}"
                    if "mean" in row
                    else "(no priced rows)"
                ),
                file=out,
            )
    real_max = max((len(f.members) for f in fams), default=0)
    print(
        f"  REAL: families={len(fams)} onsets={len(onsets)} largest={real_max}",
        file=out,
    )
    for kind in ("shuffle", "rotation"):
        sub = [a for a in amb if a["null"] == kind]
        if not sub:
            continue
        mf = float(np.mean([a["families"] for a in sub]))
        mo = float(np.mean([a["onsets"] for a in sub]))
        mm = float(np.mean([a["max_family"] for a in sub]))
        print(
            f"  vs {kind:<9}: families {len(fams)}/{mf:.0f} = {len(fams)/max(mf,1e-9):.2f}x   "
            f"onsets {len(onsets)}/{mo:.0f} = {len(onsets)/max(mo,1e-9):.2f}x   "
            f"largest family {real_max}/{mm:.0f} = {real_max/max(mm,1e-9):.2f}x",
            file=out,
        )
    result["ambient_null"] = {
        "draws": amb,
        "real_families": len(fams),
        "real_onsets": len(onsets),
        "real_max_family": real_max,
    }

    # ---- 6b. the known-EFFECT control for the detector itself -------------
    print(f"\n--- 6b. RECOVERY — can the detector find a swarm that is definitely there? ---", file=out)
    print(
        "  §6 is only the zero side. A detector that finds nothing passes every "
        "false-positive\n  test perfectly, so 40 textbook parasite swarms (3 fresh deployers, "
        "same ticker, inside\n  two minutes) are planted into the real stream and scored.",
        file=out,
    )
    planted_stream, planted = plant_swarms(launches, 40, clones=3, delay_s=120.0, seed=seed)
    p_onsets, p_det = run_detector(planted_stream, store, k=k, window_s=window_s)
    found_hosts = {o["host_mint"] for o in p_onsets}
    # a plant counts as recovered if an onset fired on a family containing its clones
    recovered = 0
    right_host = 0
    fam_of: dict[str, Any] = {}
    for fam in p_det.families():
        for m in fam.members:
            fam_of[m.mint] = fam
    for host_mint, clone_mints in planted.items():
        fam = fam_of.get(clone_mints[0])
        if fam is None:
            continue
        mints = {m.mint for m in fam.members}
        if all(c in mints for c in clone_mints) and host_mint in mints:
            recovered += 1
            if host_mint in found_hosts:
                right_host += 1
    print(
        f"  planted {len(planted)} swarms: {recovered} recovered as one family with their host "
        f"({recovered/max(len(planted),1):.0%}), of which {right_host} also had the host "
        f"correctly nominated ({right_host/max(len(planted),1):.0%})",
        file=out,
    )
    verdict = "RECOVERED" if recovered >= 0.8 * len(planted) else "*** DETECTOR FAILED RECOVERY ***"
    print(f"  {verdict}", file=out)
    result["detector_recovery"] = {
        "planted": len(planted),
        "recovered": recovered,
        "right_host": right_host,
    }

    # ---- 7. trials --------------------------------------------------------
    print(f"\n--- 7. TRIALS ACCOUNTING ---", file=out)
    pvals, names = [], []
    for d in result.get("control_diffs", []):
        if d["p"] == d["p"]:
            pvals.append(d["p"])
            names.append(f"treated-vs-control r{d['h']//60}m")
    if pvals:
        rejected = bh_fdr(pvals, q=0.10)
        for nm, p, rej in zip(names, pvals, rejected, strict=True):
            print(f"  {nm:<34} p={p:.4f}  {'SURVIVES' if rej else 'fails'} BH-FDR q=0.10", file=out)
        result["fdr"] = [
            {"test": n, "p": p, "rejected": r} for n, p, r in zip(names, pvals, rejected, strict=True)
        ]
    for d in result.get("dose_response", []):
        if d["p"] == d["p"]:
            pvals.append(d["p"])
            names.append(f"dose {d['var'][:18]} r{d['h']//60}m")
    for d in result.get("clone_arm", {}).get("diffs", []):
        if d["p"] == d["p"]:
            pvals.append(d["p"])
            names.append(f"clone-vs-launch-control r{d['h']//60}m")
    for d in result.get("parasite_diffs", []):
        if d["p"] == d["p"]:
            pvals.append(d["p"])
            names.append(f"parasite-vs-control r{d['h']//60}m")
    if pvals:
        rejected = bh_fdr(pvals, q=0.10)
        result["fdr"] = [
            {"test": n, "p": p, "rejected": r} for n, p, r in zip(names, pvals, rejected, strict=True)
        ]
        print(
            f"  BH-FDR over all {len(pvals)} control-arm tests at q=0.10: "
            f"{sum(rejected)} survive",
            file=out,
        )
    n_config = 3 * len(HORIZONS_S) * 2 * 2
    print(
        f"  configurations this file can produce: ~{n_config} (k in 3..5, {len(HORIZONS_S)} "
        f"horizons, 2 taxonomy arms, 2 labels).\n  PROGRAM.md §3.9: past ~7 independent "
        f"configurations an in-sample Sharpe of 1 is OOS zero.\n  Every headline above is from "
        f"ONE pre-declared configuration (k={k}, window={window_s/60:.0f}m, "
        f"horizon={horizon//60}m, primary = all onsets).",
        file=out,
    )

    # ---- 7b. sensitivity to the two knobs that are not pinned by anything -------
    print(f"\n--- 7b. SENSITIVITY — the detector's two free knobs ---", file=out)
    print(
        "  PROGRAM.md §3.7: report the threshold with every number. k and the matching window\n"
        "  are the only settings not fixed by an observable, so both are swept and the\n"
        "  headline's stability (or absence of it) is visible rather than asserted.",
        file=out,
    )
    sweep = []
    for kk in (3, 4, 5):
        for ww in (900.0, 1800.0, 3600.0):
            s_on, s_det = run_detector(launches, store, k=kk, window_s=ww)
            s_tr, _ = build_cohort(launches, s_on, store, tape_end)
            usable = [r for r in s_tr if not r[f"admin{horizon}"]]
            if not usable:
                continue
            rr = np.array([x[f"r{horizon}"] for x in usable])
            row = {
                "k": kk,
                "window_min": ww / 60,
                "onsets": len(s_on),
                "n": len(rr),
                "mean": float(rr.mean()),
                "median": float(np.median(rr)),
                "p_up": float((rr > 0).mean()),
            }
            sweep.append(row)
            print(
                f"  k={kk} window={ww/60:>4.0f}m: onsets={len(s_on):4d} n={len(rr):4d} "
                f"mean={row['mean']:+8.2%} med={row['median']:+8.2%} p(up)={row['p_up']:5.1%}",
                file=out,
            )
    result["sensitivity"] = sweep

    # ---- 8. candidates feed ----------------------------------------------
    if emit_candidates:
        path = write_candidates(onsets, treated, store)
        print(f"\n  candidates feed written: {path}", file=out)
        result["candidates_path"] = str(path)

    if as_json:
        print(json.dumps(result, indent=2, default=str))
    return result


def _model_block(
    pooled_all: Sequence[dict[str, Any]],
    label_key: str,
    label_fn: Callable[[dict[str, Any]], int],
    desc: str,
    horizon: int,
    seed: int,
    out,
    model_out: dict[str, Any],
) -> None:
    """Free vs free+swarm on one label, with three nulls and a planted-effect recovery."""
    import numpy as np

    pooled = [dict(r) for r in pooled_all if not r[f"admin{horizon}"]]
    for r in pooled:
        r[label_key] = label_fn(r)
    train, test, cut = temporal_family_split(pooled)
    base = sum(r[label_key] for r in pooled) / max(len(pooled), 1)
    print(
        f"\n  LABEL: {desc} | base rate {base:.1%} | train {len(train)} / test {len(test)} rows, "
        f"split at "
        f"{dt.datetime.fromtimestamp(cut, dt.timezone.utc).strftime('%H:%M:%S')}Z, "
        f"families never straddle",
        file=out,
    )
    block: dict[str, Any] = {"base_rate": base, "n_train": len(train), "n_test": len(test)}
    model_out[label_key] = block
    blocks = {
        "free only": usable_columns(train, FREE_COLUMNS),
        "swarm only": usable_columns(train, ("treated", *SWARM_COLUMNS)),
        "free + swarm": usable_columns(train, (*FREE_COLUMNS, "treated", *SWARM_COLUMNS)),
    }
    if len(train) < 30 or len(test) < 30 or len({r[label_key] for r in test}) < 2:
        print("    too few rows / one class only after the temporal split; no model fitted", file=out)
        return
    for name, cols in blocks.items():
        if not cols:
            continue
        y, s = fit_score(train, test, cols, label_key)
        auc, ap = auc_auprc(y, s)
        lo, hi = cluster_bootstrap_auc(
            y, s, [r["family"].removeprefix("ctl:") for r in test], seed=seed
        )
        print(
            f"    {name:<14} AUC={auc:.3f} [{lo:.3f}, {hi:.3f}]  AUPRC={ap:.3f} "
            f"(base {base:.3f})  {len(cols)} cols",
            file=out,
        )
        block[name] = {"auc": auc, "ci": [lo, hi], "auprc": ap, "columns": cols}

    cols = blocks["free + swarm"]
    if "free + swarm" not in block:
        return
    real_auc = block["free + swarm"]["auc"]
    rng = random.Random(seed)
    for null_name, fn in (
        ("label iid", lambda rs: null_iid(rs, label_key, rng)),
        ("label rotation", lambda rs: null_rotation(rs, label_key, rng)),
        ("swarm-block permutation", lambda rs: null_swarm_permutation(rs, rng)),
    ):
        draws = []
        for _ in range(24):
            nulled = fn([dict(r) for r in pooled])
            ntr, nte, _c = temporal_family_split(nulled)
            if len(nte) < 10 or len({r[label_key] for r in nte}) < 2:
                continue
            y, s = fit_score(ntr, nte, cols, label_key)
            a, _ = auc_auprc(y, s)
            if a == a:
                draws.append(a)
        if draws:
            beat = sum(1 for d in draws if d >= real_auc)
            print(
                f"    null: {null_name:<24} mean AUC={np.mean(draws):.3f} "
                f"[{min(draws):.3f},{max(draws):.3f}]  beats real in {beat}/{len(draws)} draws",
                file=out,
            )
            block[f"null_{null_name}"] = {
                "mean": float(np.mean(draws)),
                "beats_real": beat,
                "draws": len(draws),
            }

    # PROGRAM.md §3.12 — a green zero-control certifies a broken estimator exactly as
    # readily as a working one, so the estimator is also run against a KNOWN-EFFECT world.
    rng2 = random.Random(seed + 1)
    planted = []
    for r in pooled:
        q = dict(r)
        q[label_key] = 1 if rng2.random() < (0.85 if q["treated"] == 1 else 0.15) else 0
        planted.append(q)
    ptr, pte, _c = temporal_family_split(planted)
    if len(pte) >= 10 and len({r[label_key] for r in pte}) == 2:
        y, s = fit_score(ptr, pte, cols, label_key)
        a, _ = auc_auprc(y, s)
        yf, sf = fit_score(ptr, pte, usable_columns(ptr, FREE_COLUMNS), label_key)
        af, _ = auc_auprc(yf, sf)
        verdict = "RECOVERED" if a > af + 0.05 else "*** FAILED TO RECOVER ***"
        print(
            f"    recovery control (planted treated-> label): free+swarm AUC={a:.3f} vs "
            f"free-only AUC={af:.3f}  {verdict}",
            file=out,
        )
        block["recovery"] = {"free_plus_swarm": a, "free_only": af, "recovered": a > af + 0.05}



def survival_block(
    treated: Sequence[dict[str, Any]],
    controls: Sequence[dict[str, Any]],
    horizon: int,
    out=sys.stdout,
) -> dict[str, Any]:
    """Kaplan–Meier on time-to-last-trade, plus {up, down, dead} as exclusive states.

    "Mean return at 1 h" over the coins that were still trading at 1 h is a return times a
    survival probability with the survival term quietly set to 1. Dropping the dead flipped
    the callout cohort from −14.6% to +25%. So the dead are priced (mark-to-last-trade) in
    §2 and counted as their own state here.
    """
    import pandas as pd
    from lifelines import KaplanMeierFitter
    from lifelines.statistics import logrank_test

    res: dict[str, Any] = {}
    for name, rows in (("treated", treated), ("control", controls)):
        if len(rows) < 8:
            continue
        km = KaplanMeierFitter().fit(
            [max(r["death_s"], 60.0) for r in rows], [1 if r["died"] else 0 for r in rows]
        )
        med = float(km.median_survival_time_)
        res[name] = {"n": len(rows), "events": sum(1 for r in rows if r["died"]), "median_survival_s": med}
        print(
            f"  {name:<9} n={len(rows):<5} died={res[name]['events']:<5} "
            f"median survival from onset = {med/60:.1f} min",
            file=out,
        )
    if "treated" in res and "control" in res:
        lr = logrank_test(
            [max(r["death_s"], 60.0) for r in treated],
            [max(r["death_s"], 60.0) for r in controls],
            [1 if r["died"] else 0 for r in treated],
            [1 if r["died"] else 0 for r in controls],
        )
        res["logrank_p"] = float(lr.p_value)
        print(f"  log-rank treated vs control: p={lr.p_value:.4f}", file=out)

    print(f"\n  competing risks at {horizon//60}m — three exclusive states:", file=out)
    for name, rows in (("treated", treated), ("control", controls)):
        usable = [r for r in rows if not r[f"admin{horizon}"]]
        if not usable:
            continue
        states = Counter()
        for r in usable:
            if r["died"] and r["t_last_trade"] < r["t_post"] + horizon:
                states["dead"] += 1
            elif r[f"r{horizon}"] > 0:
                states["up"] += 1
            else:
                states["down"] += 1
        tot = max(sum(states.values()), 1)
        print(
            f"    {name:<9} n={tot:<5} up={states['up']/tot:5.1%} down={states['down']/tot:5.1%} "
            f"dead={states['dead']/tot:5.1%}",
            file=out,
        )
        res[f"{name}_states"] = {k: v / tot for k, v in states.items()}
    return res


def write_candidates(
    onsets: Sequence[dict[str, Any]],
    treated: Sequence[dict[str, Any]],
    store: CandleStore,
    path: Path = SWARMS / "candidates.jsonl",
) -> Path:
    """The feed contract another desk can consume. One row per onset, append-only.

    Deliberately carries the *evidence*, not a verdict: clone count, distinct deployers,
    spend, both lags, taxonomy, and the host's market state at onset. A consumer decides
    direction and size; this file never says "buy".
    """
    by_mint = {r["mint"]: r for r in treated}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for ev in onsets:
            tr = by_mint.get(ev["host_mint"])
            fh.write(
                json.dumps(
                    {
                        "kind": "swarm_candidate",
                        "schema": 1,
                        # ISO for a human reading the file; unix floats because every
                        # paperdesk Source speaks `t_ingest_unix` / `t_event_unix` and a
                        # consumer should not need a translation layer to tail this.
                        "t_ingest": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "t_ingest_unix": time.time(),
                        "t_event": ev["onset_t"],
                        "t_event_unix": _epoch(ev["onset_t"]),
                        "t_event_source": ev["t_event_source"],
                        "family_id": ev["family_id"],
                        "host_mint": ev["host_mint"],
                        "host_symbol": ev["host_symbol"],
                        "host_launch_t": ev["host_t"],
                        "host_left_censored": ev.get("host_left_censored"),
                        "host_rule": ev.get("host_rule"),
                        "taxonomy": ev["taxonomy"],
                        "clone_count": ev["clone_count"],
                        "distinct_clone_deployers": ev["distinct_clone_deployers"],
                        "clone_spend_sol": ev["clone_spend_sol"],
                        "lag_from_host_s": ev["lag_from_host_s"],
                        "lag_from_first_clone_s": ev["lag_from_first_clone_s"],
                        "match_kinds": ev["match_kinds"],
                        "host_mcap_sol_at_onset": (tr or {}).get("mcap_at_onset"),
                        "host_age_s_at_onset": (tr or {}).get("age_at_onset_s"),
                        "host_momentum_at_onset": (tr or {}).get("momentum_so_far"),
                        "host_traded_minutes_at_onset": (tr or {}).get("traded_minutes_so_far"),
                        "members": ev["members"],
                    }
                )
                + "\n"
            )
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_stream(
    days: int = 3, retro_day: str | None = None
) -> tuple[list[Launch], dict[str, Any], list[tuple[float, float]] | None]:
    """The launch stream, from either the live socket window or a retro day.

    The two are never pooled. The live window is a socket tape with holes, restricted to the
    ledger's demonstrated listening intervals; the retro day is a *census* built from the
    bulk pull, complete by construction, and restricting it to socket windows would throw
    away the entire point of it. They are separate cohorts and separate reported runs — a
    replication, not extra n.
    """
    if retro_day:
        path = SWARMS / f"retro-{retro_day}.jsonl"
        launches, stats = build_stream([], [path], None)
        stats["source"] = f"retro:{retro_day}"
        return launches, stats, None
    fh, led, cen = (
        _default_paths("new_token", days),
        _default_paths("ledger", days),
        _census_paths(days),
    )
    intervals = listening_intervals(led)
    launches, stats = build_stream(fh, cen, intervals)
    stats["source"] = "live_socket_window"
    return launches, stats, intervals


def retro_fetch_set(
    launches: Sequence[Launch], k: int, window_s: float, sample: int, seed: int
) -> list[str]:
    """Which mints a retro day actually needs candles for.

    A full day is ~30k launches and pricing all of them is hours of polite fetching for no
    gain. Two sets are needed and no more: every member of a family that reached onset size
    (the treated rows, and the traction probe reads every member), plus a **random** sample
    of everything else to serve as the control pool. Random is load-bearing — a control pool
    chosen by any property of the coin would confound the very comparison it exists for.
    """
    _onsets, det = run_detector(launches, None, k=k, window_s=window_s)
    need: set[str] = set()
    for fam in det.families():
        if len(fam.members) >= k:
            need.update(m.mint for m in fam.members)
    rest = [l.mint for l in launches if l.mint not in need]
    rng = random.Random(seed)
    rng.shuffle(rest)
    return sorted(need) + rest[:sample]


def cmd_fetch(args: argparse.Namespace) -> int:
    store = CandleStore()
    launches, stats, _iv = load_stream(args.days, args.retro_day)
    if args.retro_day:
        mints = retro_fetch_set(launches, args.k, args.window, args.sample, args.seed)
        print(
            f"[fetch] retro {args.retro_day}: {len(launches)} launches -> {len(mints)} mints "
            f"to price (family members at k>={args.k}, plus {args.sample} random controls)",
            file=sys.stderr,
        )
    else:
        mints = [l.mint for l in launches]
    print(f"[fetch] {len(mints)} mints in stream ({stats})", file=sys.stderr)
    t0 = time.time()
    got = fetch_all(
        mints,
        store,
        workers=args.workers,
        pause=args.pause,
        refresh_older_than=0.0 if args.full else args.refresh_older_than,
        dead_after=0.0 if args.full else args.dead_after,
    )
    print(f"[fetch] {got} in {time.time()-t0:.0f}s   spend: $0.00 (keyless endpoint)", file=sys.stderr)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", action="store_true", help="fill the candle cache (network)")
    ap.add_argument("--report", action="store_true", help="offline analysis over the cache")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--window", type=float, default=1800.0)
    ap.add_argument("--horizon", type=int, default=3600)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--seed", type=int, default=20260815)
    ap.add_argument("--tape-end", type=float, default=None,
                    help="pin the analysis window end (epoch seconds); required for a "
                         "reproducible reported run while the collectors are live")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--pause", type=float, default=0.6)
    ap.add_argument("--loop", type=float, default=0.0, help="repeat --fetch every N seconds")
    ap.add_argument("--refresh-older-than", type=float, default=900.0)
    ap.add_argument("--dead-after", type=float, default=2400.0,
                    help="warming loop skips coins already settled this long; <=0 disables")
    ap.add_argument("--full", action="store_true",
                    help="refresh EVERY mint regardless of staleness; required before a "
                         "reported run so no row is admin-censored by a stale cache")
    ap.add_argument("--no-candidates", action="store_true")
    ap.add_argument("--retro-day", default=None,
                    help="analyse a past UTC day from state/swarms/retro-<day>.jsonl instead "
                         "of the live socket window; never pooled with it")
    ap.add_argument("--sample", type=int, default=12000,
                    help="retro only: size of the random control pool to price")
    args = ap.parse_args(argv)

    if args.fetch:
        while True:
            cmd_fetch(args)
            if not args.loop:
                break
            time.sleep(args.loop)
    if args.report or not args.fetch:
        report(
            k=args.k,
            window_s=args.window,
            horizon=args.horizon,
            seed=args.seed,
            as_json=args.json,
            emit_candidates=not args.no_candidates,
            days=args.days,
            tape_end_pin=args.tape_end,
            retro_day=args.retro_day,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
