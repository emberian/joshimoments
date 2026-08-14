"""Deterioration: is this coin ready to ditch?

The operator holds four "strong techproject" coins (weave, nosis, DREGG, SOLVE) and wants a
read on when one is deteriorating enough to exit. This module builds that instrument.

**The design principle, and why it is not a mistake.** Ninety percent of pump.fun launches die
within hours; ~21,859 launch per day (Marino/Lillo, arXiv:2602.14860, verified). Training a
model on that population to say something about a coin with 986 holders, $348k FDV and a
six-week trading history is a category error — those are different populations and the large
one is not a superset in any useful sense. So we condition *hard* on survival first and study
what is left. Marino already measured the size of this effect: graduation runs 0.63%
unconditionally and 2.55% among tokens with >=30 swaps — a 4x move from one weak condition.
Conditioning is what makes the reference class both relevant and small enough to collect
keyless.

**The method is memorisation, on purpose.** For a coin-state today we retrieve the most
similar historical coin-states and report what happened next. Rationale, in the order it
matters: (i) it is interpretable — the operator can read the analogues and overrule them;
(ii) it makes no distributional assumption; (iii) it works at 10^4 states rather than 10^7.
PROGRAM.md 1.5 records that EdgeBank, a zero-parameter hash table, ranks 2nd across 13
temporal-graph benchmarks, and that on the crypto benchmark a decayed popularity counter beat
both it and TGN by 14 MRR points. Memorisation is the baseline to beat, not the fallback.

**What is keyless-available, precisely.** This matters more than any modelling choice, so it
is stated up front and enforced in code rather than left to prose:

===================================  ===========  =============================================
quantity                             historical?  source
===================================  ===========  =============================================
price (hourly OHLC)                  YES          GeckoTerminal /ohlcv/hour, 1000 candles = 41d
volume (hourly, USD)                 YES          same call
pool age                             YES          pool_created_at
FDV / market cap                     derived      fdv_now * price(t)/price(now), constant supply
liquidity (reserve_in_usd)           **NO**       current snapshot only
holders + top-10 concentration       **NO**       current snapshot only (GT /tokens/{a}/info)
buys/sells, buyers/sellers           **NO**       current snapshot only (GT pool detail)
===================================  ===========  =============================================

So the historical analogue space is a *price-and-volume* space. The liquidity half of the
operator's hypothesis is **not testable on keyless history** and this module does not pretend
otherwise: see :func:`liquidity_counterfactual` for why the constant-product reconstruction
cannot substitute (the deviation from it *is* the LP flow, which is the unobservable).

To fix that going forward the module snapshots the full vector — liquidity, holders,
concentration, wallet-level and transaction-level flow — on every live read, appending to
``state/deterioration/snapshots.jsonl``. Run it daily and in a month the full vector becomes
historical. That is cheap and it is the only keyless route to it.

CLI::

    python -m studies.deterioration selftest          # calibrate on worlds with known answers
    python -m studies.deterioration discover          # find candidate pools (GT listings)
    python -m studies.deterioration ohlcv             # pull hourly history for candidates
    python -m studies.deterioration panel             # build the survivor-conditioned panel
    python -m studies.deterioration cohort            # what the cohort contains, and its attrition
    python -m studies.deterioration evaluate          # protocol + nulls (PROGRAM.md 3)
    python -m studies.deterioration evaluate --adjusted   # ... vs market-adjusted returns
    python -m studies.deterioration hypothesis        # the lead/lag test, stated to fail
    python -m studies.deterioration read <mint|label> # live read + analogues
    python -m studies.deterioration live              # the operator's four coins

Run ``selftest`` before believing anything ``evaluate`` says. It reports the pipeline's own
false-positive band on pure noise, and that band is wider than most people would guess.
"""

from __future__ import annotations

import argparse
import calendar
import json
import math
import random
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

# ---------------------------------------------------------------------------------------
# paths and constants
# ---------------------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
STATE = REPO / "state" / "deterioration"
OHLCV_DIR = STATE / "ohlcv"
DISCOVERY = STATE / "discovery.jsonl"
SNAPSHOTS = STATE / "snapshots.jsonl"
PANEL = STATE / "panel.jsonl"
RATE_STATE = STATE / "ratelimit.json"

GT = "https://api.geckoterminal.com/api/v2"
DS = "https://api.dexscreener.com"
WSOL = "So11111111111111111111111111111111111111112"

#: Quote tokens we accept. A pool quoted in a random memecoin has a price series that is a
#: ratio of two things we are trying to measure, which is not a state we can reason about.
QUOTE_OK = {
    WSOL,
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}

#: Tokens too large to be in the operator's reference class. A $2B coin's hourly state is not
#: an analogue for a $350k coin's, and including them just wastes neighbour slots.
MAJOR_MINTS = {
    WSOL,
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
    "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs",  # ETH (wormhole)
    "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh",  # WBTC
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # jitoSOL
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",  # JUP
    "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4",  # JLP
}

#: The operator's cluster. Mints from ``shitcoims_cluster/pools.py`` (on-chain verified there;
#: this module re-reads that module rather than copying, so a correction propagates).
try:  # pragma: no cover - import shape depends on how the module is invoked
    sys.path.insert(0, str(REPO))
    from shitcoims_cluster.pools import DREGG, NOSIS, SOLVE, WEAVE

    CLUSTER = {"weave": WEAVE, "nosis": NOSIS, "DREGG": DREGG, "SOLVE": SOLVE}
except Exception:  # the study must still run if the package moves
    CLUSTER = {
        "weave": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
        "nosis": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
        "DREGG": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
        "SOLVE": "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
    }

HOUR = 3600

# ---------------------------------------------------------------------------------------
# polite HTTP
# ---------------------------------------------------------------------------------------


class Fetcher:
    """Rate-limited keyless HTTP with persistent pacing and adaptive backoff.

    Six sibling agents share this IP and GeckoTerminal's free tier is a per-IP budget, so the
    pacing state lives on disk: a second invocation of this module inherits the first one's
    clock instead of resetting it. A 429 widens the interval multiplicatively and it recovers
    only after a long unbroken run of successes — additive-increase/multiplicative-decrease,
    because the contention is other processes finishing, which is exactly what a success streak
    is evidence of. Returning to the old rate immediately after a 429 just re-triggers it.
    """

    def __init__(self, min_interval: float = 3.0, verbose: bool = True) -> None:
        self.floor = min_interval
        self.min_interval = min_interval
        self.verbose = verbose
        self.calls = 0
        self.throttles = 0
        self.streak = 0

    def _wait(self) -> None:
        RATE_STATE.parent.mkdir(parents=True, exist_ok=True)
        try:
            last = json.loads(RATE_STATE.read_text()).get("last", 0.0)
        except Exception:
            last = 0.0
        delta = time.time() - last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        RATE_STATE.write_text(json.dumps({"last": time.time()}))

    def get(self, url: str, tries: int = 5) -> Any | None:
        for attempt in range(tries):
            self._wait()
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json;version=20230302",
                    "User-Agent": "joshibot-deterioration-study/0.1 (research; keyless)",
                },
            )
            try:
                self.calls += 1
                with urllib.request.urlopen(req, timeout=40) as resp:
                    payload = json.loads(resp.read())
                self.streak += 1
                if self.streak >= 15 and self.min_interval > self.floor:
                    self.min_interval = max(self.floor, self.min_interval * 0.85)
                    self.streak = 0
                return payload
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    self.throttles += 1
                    self.streak = 0
                    self.min_interval = min(self.min_interval * 1.4 + 0.5, 30.0)
                    wait = min(6.0 * (attempt + 1), 45.0)
                    if self.verbose:
                        print(
                            f"    429 -> interval now {self.min_interval:.1f}s, sleeping {wait:.0f}s",
                            file=sys.stderr,
                        )
                    time.sleep(wait)
                    continue
                if exc.code in (404, 400):
                    return None
                time.sleep(3.0 * (attempt + 1))
            except Exception as exc:  # network flake
                if self.verbose and attempt == tries - 1:
                    print(f"    give up {url}: {exc}", file=sys.stderr)
                time.sleep(2.0 * (attempt + 1))
        return None


def jsonl_append(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            n += 1
    return n


def jsonl_read(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


# ---------------------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------------------

#: GeckoTerminal listing endpoints, each paginated to 10 pages of 20. Several sorts and
#: several DEXes because every one of them is a *top-N by something today* list, and the
#: union reaches further into the tail than any single one. The bias this leaves is named and
#: measured in ``RESULT_deterioration.md`` rather than waved at: pools that died so hard they
#: left every list are missing, which makes every death rate reported here a LOWER BOUND.
LISTINGS: tuple[tuple[str, str], ...] = (
    ("/networks/solana/pools", "h24_volume_usd_desc"),
    ("/networks/solana/pools", "h24_tx_count_desc"),
    ("/networks/solana/dexes/pumpswap/pools", "h24_volume_usd_desc"),
    ("/networks/solana/dexes/pumpswap/pools", "h24_tx_count_desc"),
    ("/networks/solana/dexes/raydium/pools", "h24_volume_usd_desc"),
    ("/networks/solana/dexes/meteora/pools", "h24_volume_usd_desc"),
    ("/networks/solana/dexes/orca/pools", "h24_volume_usd_desc"),
    ("/networks/solana/trending_pools", "h24_volume_usd_desc"),
    ("/networks/solana/new_pools", ""),
)


def _pool_row(item: dict, source: str) -> dict | None:
    attrs = item.get("attributes") or {}
    rel = item.get("relationships") or {}
    base = ((rel.get("base_token") or {}).get("data") or {}).get("id") or ""
    quote = ((rel.get("quote_token") or {}).get("data") or {}).get("id") or ""
    dex = ((rel.get("dex") or {}).get("data") or {}).get("id") or ""
    if not base.startswith("solana_") or not quote.startswith("solana_"):
        return None
    return {
        "pool": attrs.get("address"),
        "name": attrs.get("name"),
        "base_mint": base.split("_", 1)[1],
        "quote_mint": quote.split("_", 1)[1],
        "dex": dex,
        "created_at": attrs.get("pool_created_at"),
        "fdv_usd": attrs.get("fdv_usd"),
        "reserve_in_usd": attrs.get("reserve_in_usd"),
        "vol_h24": (attrs.get("volume_usd") or {}).get("h24"),
        "source": source,
        "seen_at": int(time.time()),
    }


def discover(fetcher: Fetcher, pages: int = 10) -> list[dict]:
    """Enumerate candidate Solana pools from every keyless listing GeckoTerminal exposes."""

    known = {row["pool"] for row in jsonl_read(DISCOVERY) if row.get("pool")}
    found: dict[str, dict] = {}

    def commit(rows: list[dict]) -> int:
        # Append per page, never once at the end. Under contention a full sweep takes the better
        # part of an hour, and a run that only persists on the last line throws away everything
        # it learned if it is killed on the second-to-last one.
        fresh = [r for r in rows if r["pool"] not in known]
        for r in fresh:
            known.add(r["pool"])
            found.setdefault(r["pool"], r)
        if fresh:
            jsonl_append(DISCOVERY, fresh)
        return len(fresh)

    for path, sort in LISTINGS:
        for page in range(1, pages + 1):
            query: dict[str, Any] = {"page": page}
            if sort:
                query["sort"] = sort
            url = f"{GT}{path}?{urllib.parse.urlencode(query)}"
            payload = fetcher.get(url)
            items = (payload or {}).get("data") or []
            if not items:
                break
            rows = [r for r in (_pool_row(i, f"{path}|{sort}") for i in items) if r and r["pool"]]
            added = commit(rows)
            print(
                f"  {path} sort={sort or '-'} page={page}: "
                f"{len(items)} items, +{added} new, {len(known)} total"
            )
    # The cluster is in the universe by construction, not by luck of a listing.
    for label, mint in CLUSTER.items():
        payload = fetcher.get(f"{GT}/networks/solana/tokens/{mint}/pools")
        rows = [r for r in (_pool_row(i, f"cluster|{label}") for i in ((payload or {}).get("data") or [])) if r and r["pool"]]
        commit(rows)
    print(f"discovery: {len(found)} new this run, {len(known)} pools known in total")
    return list(found.values())


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def pool_age_days(row: dict, now: float | None = None) -> float | None:
    if not row.get("created_at"):
        return None
    try:
        born = calendar.timegm(time.strptime(row["created_at"], "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return None
    return ((now or time.time()) - born) / 86400.0


def candidates(
    min_fdv: float = 20_000.0, max_fdv: float = 50_000_000.0, min_age_days: float = 2.0
) -> list[dict]:
    """Discovery rows worth spending an OHLCV call on.

    This is a *cheap pre-filter on the current snapshot*, not the cohort definition. The
    cohort itself is dated retrospectively from each pool's own history in :func:`build_panel`
    — a pool that is small today may have been large three weeks ago, and those are exactly
    the deterioration trajectories the instrument needs to have seen.

    **The age gate is the expensive lesson of this study, so it is enforced here rather than
    downstream.** The first fetch pass ordered candidates by "small FDV, high volume", which
    reads like the operator's scale band and is in fact the signature of a pump.fun launch four
    hours old: 70 pools fetched, **median 4 hourly candles**, 69 of 70 with fewer than 72. The
    small-and-busy corner of the cross-section *is* the 21,859-launches-per-day population this
    study exists to exclude. Age separates them and costs nothing — the creation time is already
    in the discovery row, so the gate is free and belongs before the call, not after it.
    """

    best: dict[str, dict] = {}
    for row in jsonl_read(DISCOVERY):
        pool = row.get("pool")
        if not pool:
            continue
        if row.get("quote_mint") not in QUOTE_OK:
            continue
        if row.get("base_mint") in MAJOR_MINTS:
            continue
        fdv = _f(row.get("fdv_usd"))
        if fdv is None or not (min_fdv <= fdv <= max_fdv):
            continue
        age = pool_age_days(row)
        if age is None or age < min_age_days:
            continue
        prior = best.get(pool)
        if prior is None or (_f(row.get("vol_h24")) or 0) > (_f(prior.get("vol_h24")) or 0):
            best[pool] = row
    return sorted(best.values(), key=lambda r: -(_f(r.get("vol_h24")) or 0.0))


# ---------------------------------------------------------------------------------------
# OHLCV history
# ---------------------------------------------------------------------------------------


def ohlcv_path(pool: str) -> Path:
    return OHLCV_DIR / f"{pool}.json"


def fetch_ohlcv(fetcher: Fetcher, pool: str, limit: int = 1000, refresh_hours: float = 6.0) -> dict | None:
    """Hourly OHLCV for one pool, cached. 1000 candles is 41.6 days, GT's keyless maximum."""

    path = ohlcv_path(pool)
    if path.exists():
        try:
            cached = json.loads(path.read_text())
            if time.time() - cached.get("fetched_at", 0) < refresh_hours * HOUR:
                return cached
        except Exception:
            pass
    url = f"{GT}/networks/solana/pools/{pool}/ohlcv/hour?aggregate=1&limit={limit}&currency=usd&token=base"
    payload = fetcher.get(url)
    if payload is None:
        return None
    rows = ((payload.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    if not rows:
        return None
    record = {
        "pool": pool,
        "fetched_at": int(time.time()),
        "source": "geckoterminal.ohlcv.hour",
        "currency": "usd",
        "token": "base",
        "ohlcv": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return record


#: Above this FDV a coin is not in the operator's reference class in any useful sense, so its
#: history is fetched only after every small one has been. The keyless budget is the binding
#: constraint (~30s/call under contention), and spending it on $40M coins to build analogues
#: for a $350k coin would be spending it in the wrong place.
PRIORITY_FDV = 2_000_000.0


def pull_histories(fetcher: Fetcher, limit_pools: int = 400) -> None:
    rows = candidates()
    rows.sort(key=lambda r: (0 if (_f(r.get("fdv_usd")) or 0) <= PRIORITY_FDV else 1, -(_f(r.get("vol_h24")) or 0.0)))
    todo = [r for r in rows[:limit_pools] if not ohlcv_path(r["pool"]).exists()]
    small = sum(1 for r in todo if (_f(r.get("fdv_usd")) or 0) <= PRIORITY_FDV)
    print(
        f"ohlcv: {len(rows)} candidates, {len(todo)} to fetch "
        f"({small} at or below ${PRIORITY_FDV:,.0f} FDV)"
    )
    for i, row in enumerate(todo, 1):
        got = fetch_ohlcv(fetcher, row["pool"])
        n = len(got["ohlcv"]) if got else 0
        print(f"  [{i}/{len(todo)}] {row['name'][:28]:28s} {row['pool'][:8]} -> {n} candles")


# ---------------------------------------------------------------------------------------
# panel construction
# ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class Series:
    """One pool's hourly history reindexed onto a gapless grid.

    GeckoTerminal omits hours with no trades. Forward-filling price and zero-filling volume is
    not a cosmetic choice: a run of zero-volume hours *is* the death signal, and dropping the
    gaps would delete exactly the observations the instrument exists to recognise.
    """

    pool: str
    mint: str
    name: str
    t0: int
    price: list[float]
    volume: list[float]
    created_at: int | None

    def __len__(self) -> int:
        return len(self.price)

    def index(self, ts: int) -> int:
        return (ts - self.t0) // HOUR


def load_series(pool: str, meta: dict) -> Series | None:
    record = None
    path = ohlcv_path(pool)
    if path.exists():
        try:
            record = json.loads(path.read_text())
        except Exception:
            record = None
    if not record:
        return None
    raw = sorted(record["ohlcv"], key=lambda r: r[0])
    raw = [r for r in raw if _f(r[4]) and _f(r[4]) > 0]
    if len(raw) < 72:
        return None
    t0 = int(raw[0][0]) // HOUR * HOUR
    t_end = int(raw[-1][0]) // HOUR * HOUR
    n = (t_end - t0) // HOUR + 1
    if n <= 0 or n > 5000:
        return None
    price = [math.nan] * n
    volume = [0.0] * n
    for row in raw:
        idx = (int(row[0]) // HOUR * HOUR - t0) // HOUR
        if 0 <= idx < n:
            price[idx] = float(row[4])
            volume[idx] = float(row[5] or 0.0)
    last = price[0]
    for i in range(n):
        if math.isnan(price[i]):
            price[i] = last
        else:
            last = price[i]
    # calendar.timegm, not time.mktime: the GT timestamp is UTC and mktime would read it as
    # local, which on this box is a seven-hour error in every age in the panel.
    created = None
    if meta.get("created_at"):
        try:
            created = calendar.timegm(time.strptime(meta["created_at"], "%Y-%m-%dT%H:%M:%SZ"))
        except Exception:
            created = None
    return Series(
        pool=pool,
        mint=meta.get("base_mint", ""),
        name=meta.get("name", pool[:8]),
        t0=t0,
        price=price,
        volume=volume,
        created_at=created,
    )


#: The matching space. Every entry is computable from price-and-volume history at or before
#: the state's own timestamp — the causality is a property of the code, not a promise.
FEATURES: tuple[str, ...] = (
    "log_age_days",
    "log_fdv",
    "log_turnover",
    "dvol_24",
    "log_vol_ratio_7d",
    "ret_24h",
    "ret_72h",
    "rv_24h",
    "drawdown",
    "active_frac_24h",
)

#: Reported alongside but deliberately NOT in the matching space, because it is a linear
#: combination of two features already in it. Including it would double-weight the very
#: quantity under test and make the kNN result unfalsifiable by construction.
DERIVED: tuple[str, ...] = ("divergence",)


def _sol_reference(fetcher: Fetcher | None) -> tuple[int, list[float]] | None:
    """Hourly SOL/USD, for denominating returns in the asset the operator would exit into.

    A coin that holds its USD price while SOL falls 20% has *gained* in the only unit that
    matters for the exit decision. Every forward return in this study is SOL-denominated.
    """

    cached = STATE / "sol_usd.json"
    if cached.exists():
        try:
            record = json.loads(cached.read_text())
            if time.time() - record.get("fetched_at", 0) < 6 * HOUR:
                return record["t0"], record["price"]
        except Exception:
            pass
    if fetcher is None:
        if cached.exists():
            record = json.loads(cached.read_text())
            return record["t0"], record["price"]
        return None
    # Largest SOL/USDC venue; resolved by asking rather than hard-coding a pool address.
    payload = fetcher.get(f"{GT}/networks/solana/tokens/{WSOL}/pools?page=1")
    pool = None
    for item in (payload or {}).get("data") or []:
        attrs = item.get("attributes") or {}
        # Must be SOL-as-BASE: on a "USDC / SOL" pool the base price is ~1 and the whole
        # denominator would silently become a constant.
        if (attrs.get("name") or "").upper().startswith("SOL /") and "USDC" in (attrs.get("name") or ""):
            pool = attrs.get("address")
            break
    if pool is None:
        return None
    url = f"{GT}/networks/solana/pools/{pool}/ohlcv/hour?aggregate=1&limit=1000&currency=usd&token=base"
    payload = fetcher.get(url)
    rows = sorted(((payload or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or [])
    if not rows:
        return None
    t0 = int(rows[0][0]) // HOUR * HOUR
    n = (int(rows[-1][0]) // HOUR * HOUR - t0) // HOUR + 1
    price = [math.nan] * n
    for row in rows:
        idx = (int(row[0]) // HOUR * HOUR - t0) // HOUR
        if 0 <= idx < n:
            price[idx] = float(row[4])
    last = next((p for p in price if not math.isnan(p)), 150.0)
    for i in range(n):
        if math.isnan(price[i]):
            price[i] = last
        else:
            last = price[i]
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps({"t0": t0, "price": price, "fetched_at": int(time.time()), "pool": pool}))
    return t0, price


class SolUsd:
    def __init__(self, ref: tuple[int, list[float]] | None) -> None:
        self.ok = ref is not None
        self.t0, self.price = ref if ref else (0, [])

    def at(self, ts: int) -> float:
        if not self.ok:
            return 1.0
        idx = (ts - self.t0) // HOUR
        idx = max(0, min(len(self.price) - 1, idx))
        return self.price[idx] or 1.0


def state_at(series: Series, i: int, fdv_now: float | None, sol: SolUsd) -> dict | None:
    """The state vector at hour ``i``, using only candles at or before ``i``."""

    if i < 72:
        return None
    price = series.price
    volume = series.volume
    p = price[i]
    if not p or p <= 0:
        return None
    ts = series.t0 + i * HOUR

    vol24 = sum(volume[i - 23 : i + 1])
    vol24_prev = sum(volume[i - 47 : i - 23])
    hist_start = max(0, i - 167)
    daily = []
    j = i
    while j - 23 >= hist_start and len(daily) < 7:
        daily.append(sum(volume[j - 23 : j + 1]))
        j -= 24
    med_daily = statistics.median(daily) if daily else 0.0

    def ret(h: int) -> float | None:
        if i - h < 0:
            return None
        p0, p1 = price[i - h], price[i]
        if not p0 or not p1:
            return None
        s0, s1 = sol.at(ts - h * HOUR), sol.at(ts)
        if s0 <= 0 or s1 <= 0:
            return None
        return math.log((p1 / s1) / (p0 / s0))

    r24, r72 = ret(24), ret(72)
    if r24 is None or r72 is None:
        return None
    hourly = []
    for k in range(i - 23, i + 1):
        if k > 0 and price[k - 1] > 0 and price[k] > 0:
            hourly.append(math.log(price[k] / price[k - 1]))
    rv = statistics.pstdev(hourly) if len(hourly) > 2 else 0.0
    peak = max(price[: i + 1])
    # Age must come from pool creation, never from the first candle: history is capped at 1000
    # hours, so a six-month-old pool measured off its own window would report 41 days and land
    # next to genuinely young coins in the matching space.
    if series.created_at is None:
        return None
    age_days = (ts - series.created_at) / 86400.0
    # FDV is reconstructed as fdv_now * price(t)/price(now), i.e. under CONSTANT SUPPLY. True
    # for a pump.fun mint (fixed 1B, authority revoked) and an assumption everywhere else. A
    # missing current FDV cannot be substituted with a default: log10(1) would place the state
    # at the bottom of the scale axis and hand it neighbours it has nothing in common with.
    if not fdv_now or fdv_now <= 0 or price[-1] <= 0:
        return None
    fdv = fdv_now * (p / price[-1])
    active = sum(1 for v in volume[i - 23 : i + 1] if v > 0) / 24.0

    dvol = math.log((vol24 + 50.0) / (vol24_prev + 50.0))
    return {
        "pool": series.pool,
        "mint": series.mint,
        "name": series.name,
        "t": ts,
        "i": i,
        "price_usd": p,
        "vol24": vol24,
        "fdv": fdv,
        "log_age_days": math.log10(max(age_days, 0.04)),
        "log_fdv": math.log10(max(fdv, 1.0)),
        "log_turnover": math.log10(max(vol24, 1.0) / max(fdv, 1.0)),
        "dvol_24": dvol,
        "log_vol_ratio_7d": math.log((vol24 + 50.0) / (med_daily + 50.0)),
        "ret_24h": r24,
        "ret_72h": r72,
        "rv_24h": rv,
        "drawdown": math.log(p / peak) if peak > 0 else 0.0,
        "active_frac_24h": active,
        # The hypothesis under test, in raw units. NOT the statistic the test uses: a 24h log
        # return lives on a +/-0.2 scale and a 24h log volume ratio on a +/-1.0 scale, so this
        # difference is ~80% volume decline wearing the word "divergence". The real statistic
        # standardises both legs against library-only scales -- see add_divergence_z.
        "divergence_raw": r24 - dvol,
    }


#: Cohort entry. The operator's own criterion is age > 2d AND holders > 500 AND 24h volume >
#: $100k; holders are not keyless-historical, so this substitutes a *liquidity-free,
#: holder-free* proxy on the two axes we can date retrospectively, and the volume floor is set
#: an order of magnitude below the operator's because their own coins sit there ($20k/day for
#: DREGG today). A cohort that excluded the query point would be useless.
COHORT_MIN_AGE_DAYS = 2.0
COHORT_MIN_VOL24 = 25_000.0
COHORT_MIN_FDV = 50_000.0


def build_panel(fetcher: Fetcher | None = None, stride: int = 4) -> list[dict]:
    """Every hourly state of every pool that has *ever* met the survivor condition.

    Entry is dated from the pool's own history, not from today's snapshot: a pool enters the
    panel at the first hour it clears the floors and every state after that is retained,
    collapse included. This is the whole point — the death half of the trajectory is the part
    the instrument has to recognise, and a cohort defined on today's numbers would not contain
    it.
    """

    sol = SolUsd(_sol_reference(fetcher))
    if not sol.ok:
        # Loud, because the failure mode is silent: SolUsd falls back to a constant 1.0, every
        # "SOL-denominated" return in the panel quietly becomes a USD return, and nothing in
        # the output would say so.
        print(
            "  WARNING: no SOL/USD reference series — forward returns will be USD-denominated,\n"
            "           not SOL-denominated. Re-run with network access before quoting numbers.",
            file=sys.stderr,
        )
    meta = {}
    for row in jsonl_read(DISCOVERY):
        if row.get("pool"):
            prior = meta.get(row["pool"])
            if prior is None or (_f(row.get("vol_h24")) or 0) > (_f(prior.get("vol_h24")) or 0):
                meta[row["pool"]] = row
    states: list[dict] = []
    pools_in = 0
    for path in sorted(OHLCV_DIR.glob("*.json")):
        pool = path.stem
        row = meta.get(pool)
        if not row:
            continue
        series = load_series(pool, row)
        if series is None:
            continue
        fdv_now = _f(row.get("fdv_usd"))
        entered = False
        got = 0
        for i in range(72, len(series), stride):
            st = state_at(series, i, fdv_now, sol)
            if st is None:
                continue
            if not entered:
                if (
                    10 ** st["log_age_days"] >= COHORT_MIN_AGE_DAYS
                    and st["vol24"] >= COHORT_MIN_VOL24
                    and st["fdv"] >= COHORT_MIN_FDV
                ):
                    entered = True
                else:
                    continue
            states.append(st)
            got += 1
        if got:
            pools_in += 1
    # forward returns, per pool, in SOL terms
    by_pool: dict[str, Series] = {}
    for st in states:
        if st["pool"] not in by_pool:
            by_pool[st["pool"]] = load_series(st["pool"], meta[st["pool"]])  # type: ignore[arg-type]
    for st in states:
        series = by_pool[st["pool"]]
        i, ts = st["i"], st["t"]
        for horizon in (24, 72, 168):
            j = i + horizon
            if j < len(series):
                p0, p1 = series.price[i], series.price[j]
                s0, s1 = sol.at(ts), sol.at(ts + horizon * HOUR)
                if p0 > 0 and p1 > 0 and s0 > 0 and s1 > 0:
                    st[f"fwd_{horizon}"] = math.log((p1 / s1) / (p0 / s0))
    market_adjust(states)
    PANEL.parent.mkdir(parents=True, exist_ok=True)
    with PANEL.open("w") as handle:
        for st in states:
            handle.write(json.dumps(st, sort_keys=True) + "\n")
    mints = {st["mint"] for st in states}
    print(
        f"panel: {len(states)} states / {pools_in} pools / {len(mints)} distinct mints "
        f"(stride {stride}h, written to {PANEL})"
    )
    return states


def market_adjust(states: Sequence[dict], bucket_hours: int = 6, min_cohort: int = 8) -> None:
    """Add ``fwd_{h}_adj`` = forward return minus the cohort median at the same time.

    **This is the falsification that decides whether the instrument is worth anything.** Every
    memecoin in this cohort moves with the same risk appetite, so a state vector that merely
    tracks the market will look predictive on raw returns and tell the operator nothing they
    could not read off a chart. Subtracting the contemporaneous cohort median removes the
    common factor exactly, leaving only what is specific to *this* coin. A signal that survives
    on raw returns and dies here is a market-direction signal wearing a deterioration costume.
    """

    for horizon in (24, 72, 168):
        key = f"fwd_{horizon}"
        buckets: dict[int, list[float]] = defaultdict(list)
        for s in states:
            if key in s:
                buckets[s["t"] // (bucket_hours * HOUR)].append(s[key])
        medians = {b: statistics.median(v) for b, v in buckets.items() if len(v) >= min_cohort}
        for s in states:
            if key in s:
                med = medians.get(s["t"] // (bucket_hours * HOUR))
                if med is not None:
                    s[f"{key}_adj"] = s[key] - med


def load_panel() -> list[dict]:
    return list(jsonl_read(PANEL))


def add_divergence_z(targets: Sequence[dict], library: Sequence[dict]) -> None:
    """Set ``divergence`` = z(ret_24h) - z(dvol_24), with both scales fitted on the library.

    High when price is holding up while volume erodes underneath — Marino's "persistent
    distribution, no reflexive dip support" rendered as one number. The scales come from the
    library alone so that the statistic a test state is scored on cannot have been calibrated
    on test outcomes; that is a small leak but it is free to close.
    """

    def robust(name: str) -> tuple[float, float]:
        vals = sorted(r[name] for r in library if name in r)
        if not vals:
            return 0.0, 1.0
        med = vals[len(vals) // 2]
        lo = vals[int(0.25 * (len(vals) - 1))]
        hi = vals[int(0.75 * (len(vals) - 1))]
        return med, max(hi - lo, 1e-9)

    (rc, rs), (vc, vs) = robust("ret_24h"), robust("dvol_24")
    for row in targets:
        if "ret_24h" in row and "dvol_24" in row:
            row["divergence"] = (row["ret_24h"] - rc) / rs - (row["dvol_24"] - vc) / vs


# ---------------------------------------------------------------------------------------
# kNN
# ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class Scaler:
    """Robust standardisation. Median/IQR, not mean/sd: these features are heavy-tailed by
    construction and a single 40x volume spike would otherwise set the scale for everything."""

    center: dict[str, float] = field(default_factory=dict)
    scale: dict[str, float] = field(default_factory=dict)

    @classmethod
    def fit(cls, rows: Sequence[dict], features: Sequence[str] = FEATURES) -> "Scaler":
        center, scale = {}, {}
        for f in features:
            vals = sorted(r[f] for r in rows if f in r and r[f] is not None)
            if not vals:
                center[f], scale[f] = 0.0, 1.0
                continue
            center[f] = vals[len(vals) // 2]
            lo = vals[int(0.25 * (len(vals) - 1))]
            hi = vals[int(0.75 * (len(vals) - 1))]
            scale[f] = max(hi - lo, 1e-9)
        return cls(center, scale)

    def vec(self, row: dict, features: Sequence[str] = FEATURES) -> list[float]:
        return [(row.get(f, self.center[f]) - self.center[f]) / self.scale[f] for f in features]


class Library:
    """The analogue store, held column-major so distances are computed a feature at a time.

    Stdlib only — this repo declares no numeric dependency and no other study imports one, so
    the speed has to come from the layout rather than from a library. Ten passes over N floats
    beats N passes over ten, by roughly the interpreter's loop overhead.
    """

    def __init__(self, rows: Sequence[dict], scaler: Scaler, features: Sequence[str] = FEATURES) -> None:
        self.rows = list(rows)
        self.scaler = scaler
        self.features = list(features)
        self.cols = [
            [(r.get(f, scaler.center[f]) - scaler.center[f]) / scaler.scale[f] for r in self.rows]
            for f in self.features
        ]
        self.mints = [r.get("mint", "") for r in self.rows]

    def __len__(self) -> int:
        return len(self.rows)

    def nearest(self, query: dict, k: int = 40, exclude_mint: str | None = None) -> list[tuple[float, dict]]:
        """Nearest states to ``query``.

        ``exclude_mint`` enforces PROGRAM.md 3 rule 2 at retrieval time rather than only at
        split time: a coin must never be its own analogue, because its own history is
        autocorrelated with the query and would supply a near-duplicate neighbour carrying a
        near-identical outcome.
        """

        qv = [
            (query.get(f, self.scaler.center[f]) - self.scaler.center[f]) / self.scaler.scale[f]
            for f in self.features
        ]
        n = len(self.rows)
        if n == 0:
            return []
        q0 = qv[0]
        acc = [(v - q0) * (v - q0) for v in self.cols[0]]
        # strict=True on both: a length mismatch here would silently drop a feature
        # dimension from every distance and the kNN would quietly match on nine of ten.
        for qf, col in zip(qv[1:], self.cols[1:], strict=True):
            acc = [a + (v - qf) * (v - qf) for a, v in zip(acc, col, strict=True)]
        if exclude_mint:
            idx = [i for i in range(n) if self.mints[i] != exclude_mint]
        else:
            idx = range(n)  # type: ignore[assignment]
        best = sorted(idx, key=acc.__getitem__)[:k]
        return [(math.sqrt(acc[i]), self.rows[i]) for i in best]


def knn(
    query: dict,
    library: Sequence[dict] | Library,
    scaler: Scaler | None = None,
    k: int = 40,
    exclude_mint: str | None = None,
    features: Sequence[str] = FEATURES,
) -> list[tuple[float, dict]]:
    """Convenience wrapper: accepts a prebuilt :class:`Library` or a bare list of states."""

    if not isinstance(library, Library):
        assert scaler is not None
        library = Library(library, scaler, features)
    return library.nearest(query, k=k, exclude_mint=exclude_mint)


def neighbour_forecast(
    neighbours: Sequence[tuple[float, dict]], horizon: int, threshold: float, key: str | None = None
) -> dict:
    key = key or f"fwd_{horizon}"
    vals = [n[key] for _, n in neighbours if key in n]
    if not vals:
        return {"n": 0}
    vals_sorted = sorted(vals)
    # How many DISTINCT coins supplied the analogues. A forecast whose 40 neighbours come from
    # three coins is three observations, not forty, and its percentiles are correspondingly
    # fictional. Same-mint exclusion stops a coin being its own analogue; it does not stop one
    # other coin from monopolising the neighbourhood, which is what happens at the edges of the
    # cohort where nothing else is nearby.
    distinct = len({n.get("mint") for _, n in neighbours if key in n})
    return {
        "n": len(vals),
        "distinct_mints": distinct,
        "median": vals_sorted[len(vals_sorted) // 2],
        "mean": sum(vals) / len(vals),
        "p10": vals_sorted[int(0.10 * (len(vals_sorted) - 1))],
        "p90": vals_sorted[int(0.90 * (len(vals_sorted) - 1))],
        "p_down": sum(1 for v in vals if v <= threshold) / len(vals),
        "p_up": sum(1 for v in vals if v >= -threshold) / len(vals),
    }


# ---------------------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------------------


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")

    def rank(vals: Sequence[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        out = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den > 0 else float("nan")


def brier(probs: Sequence[float], labels: Sequence[int]) -> float:
    return sum((p - y) ** 2 for p, y in zip(probs, labels, strict=True)) / max(len(probs), 1)


def block_bootstrap_ci(
    rows: Sequence[dict], stat, key: str = "mint", draws: int = 400, seed: int = 7
) -> tuple[float, float]:
    """Resample whole entities, never rows.

    Hourly states of one coin are one observation repeated, not many observations; a row-level
    bootstrap would report a confidence interval an order of magnitude too tight.
    """

    rng = random.Random(seed)
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row.get(key, "?")].append(row)
    names = list(groups)
    if len(names) < 3:
        return (float("nan"), float("nan"))
    vals = []
    for _ in range(draws):
        sample: list[dict] = []
        for _ in range(len(names)):
            sample.extend(groups[rng.choice(names)])
        try:
            v = stat(sample)
        except Exception:
            continue
        if v is not None and math.isfinite(v):
            vals.append(v)
    if len(vals) < 20:
        return (float("nan"), float("nan"))
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]


# ---------------------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------------------

DEATH_THRESHOLD = math.log(0.80)  # -20% in SOL terms. Reported with every number that uses it.


def temporal_split(
    states: Sequence[dict], horizon: int, test_frac: float = 0.35, key: str | None = None
) -> tuple[list[dict], list[dict]]:
    """Library strictly in the past, test strictly in the future, embargoed by one horizon.

    A library state's forward window must close *before* the cut, or the library knows what
    happened after the cut. That is the leak PROGRAM.md 3 rule 1 prices at 54 points of recall.
    """

    ts = sorted(s["t"] for s in states)
    if not ts:
        return [], []
    cut = ts[int((1 - test_frac) * (len(ts) - 1))]
    embargo = horizon * HOUR
    key = key or f"fwd_{horizon}"
    library = [s for s in states if s["t"] + horizon * HOUR <= cut and key in s]
    test = [s for s in states if s["t"] >= cut + embargo and key in s]
    return library, test


def thin(states: Sequence[dict], gap_hours: int) -> list[dict]:
    """At most one state per coin per ``gap_hours``.

    Overlapping forward windows are the single largest source of fake significance in a study
    like this: 200 hourly states of one coin over one week share almost all of their outcome,
    so counting them as 200 observations inflates every confidence interval's tightness by an
    order of magnitude. Test sets are thinned by the full forward horizon; the library is
    thinned less aggressively because a near-duplicate neighbour costs precision, not validity.
    Unthinned counts are reported alongside so the inflation is visible rather than hidden.
    """

    by_mint: dict[str, list[dict]] = defaultdict(list)
    for s in states:
        by_mint[s["mint"]].append(s)
    out = []
    for rows in by_mint.values():
        rows.sort(key=lambda r: r["t"])
        last = -math.inf
        for r in rows:
            if r["t"] - last >= gap_hours * HOUR:
                out.append(r)
                last = r["t"]
    return out


def evaluate(
    states: Sequence[dict],
    horizon: int = 72,
    k: int = 40,
    seed: int = 11,
    quiet: bool = False,
    max_test: int = 700,
    adjusted: bool = False,
) -> dict:
    """The full protocol: kNN against three baselines, with both controls.

    ``max_test`` caps the query set by *coin*, not by row — dropping whole entities keeps the
    entity bootstrap honest, whereas dropping random rows would silently correlate the test
    set's composition with nothing in particular and shrink the effective n without saying so.
    """

    key = f"fwd_{horizon}" + ("_adj" if adjusted else "")
    library_all, test_all = temporal_split(states, horizon, key=key)
    # Thin the library too. Neighbours 4h apart from one coin are one observation wearing k
    # hats: they would fill the neighbour set with copies and make the forward distribution
    # look far tighter than the evidence supports.
    library = thin(library_all, 12)
    test = thin(test_all, horizon)
    if len(test) > max_test:
        mints = sorted({s["mint"] for s in test})
        random.Random(1234).shuffle(mints)
        keep: set[str] = set()
        running = 0
        counts = defaultdict(int)
        for s in test:
            counts[s["mint"]] += 1
        for m in mints:
            if running >= max_test:
                break
            keep.add(m)
            running += counts[m]
        test = [s for s in test if s["mint"] in keep]
    if len(library) < 200 or len(test) < 40:
        return {"error": f"insufficient data: library={len(library)} test={len(test)}"}
    scaler = Scaler.fit(library)
    store = Library(library, scaler)
    add_divergence_z(library, library)
    add_divergence_z(test, library)
    base_rate = sum(1 for s in library if s[key] <= DEATH_THRESHOLD) / len(library)
    rng = random.Random(seed)

    rows = []
    for q in test:
        nn = store.nearest(q, k=k, exclude_mint=q["mint"])
        fc = neighbour_forecast(nn, horizon, DEATH_THRESHOLD, key=key)
        pool = [s for s in library if s["mint"] != q["mint"]]
        rand = [(0.0, s) for s in rng.sample(pool, min(k, len(pool)))]
        rfc = neighbour_forecast(rand, horizon, DEATH_THRESHOLD, key=key)
        actual = q[key]
        rows.append(
            {
                "mint": q["mint"],
                "name": q["name"],
                "t": q["t"],
                "actual": actual,
                "label": 1 if actual <= DEATH_THRESHOLD else 0,
                "knn_p": fc.get("p_down", base_rate),
                "knn_med": fc.get("median", 0.0),
                "rand_p": rfc.get("p_down", base_rate),
                "clim_p": base_rate,
                "divergence": q["divergence"],
                "dvol_24": q["dvol_24"],
            }
        )

    def metrics(rs: Sequence[dict]) -> dict:
        labels = [r["label"] for r in rs]
        b_knn = brier([r["knn_p"] for r in rs], labels)
        b_rand = brier([r["rand_p"] for r in rs], labels)
        b_clim = brier([r["clim_p"] for r in rs], labels)
        return {
            "n": len(rs),
            "base_rate_test": sum(labels) / len(labels) if labels else float("nan"),
            "brier_knn": b_knn,
            "brier_random_k": b_rand,
            "brier_climatology": b_clim,
            "skill_vs_climatology": 1 - b_knn / b_clim if b_clim > 0 else float("nan"),
            "skill_vs_random_k": 1 - b_knn / b_rand if b_rand > 0 else float("nan"),
            "spearman_pred_vs_actual": spearman([r["knn_med"] for r in rs], [r["actual"] for r in rs]),
        }

    result = metrics(rows)
    result["horizon_h"] = horizon
    result["k"] = k
    result["death_threshold_logret"] = DEATH_THRESHOLD
    result["death_threshold_pct"] = 100 * (math.exp(DEATH_THRESHOLD) - 1)
    result["library_n"] = len(library)
    result["library_n_unthinned"] = len(library_all)
    result["library_mints"] = len({s["mint"] for s in library})
    result["test_n_unthinned"] = len(test_all)
    result["base_rate_library"] = base_rate
    result["ci_skill_vs_climatology"] = block_bootstrap_ci(
        rows,
        lambda rs: 1 - brier([r["knn_p"] for r in rs], [r["label"] for r in rs])
        / max(brier([r["clim_p"] for r in rs], [r["label"] for r in rs]), 1e-12),
    )
    result["ci_spearman"] = block_bootstrap_ci(
        rows, lambda rs: spearman([r["knn_med"] for r in rs], [r["actual"] for r in rs])
    )

    # decile lift at a stated threshold
    ranked = sorted(rows, key=lambda r: -r["knn_p"])
    top = ranked[: max(1, len(ranked) // 10)]
    result["top_decile_n"] = len(top)
    result["top_decile_death_rate"] = sum(r["label"] for r in top) / len(top)
    result["top_decile_lift"] = (
        result["top_decile_death_rate"] / result["base_rate_test"] if result["base_rate_test"] > 0 else float("nan")
    )
    result["top_decile_mean_fwd"] = sum(r["actual"] for r in top) / len(top)
    result["all_mean_fwd"] = sum(r["actual"] for r in rows) / len(rows)

    # Operating points. A skill score is not a decision; "exit when P(down) exceeds x" is. Each
    # row is what that rule would actually have done on the test period, with the threshold
    # stated next to every number as PROGRAM.md 3 rule 7 requires.
    ops = []
    for cut in (0.40, 0.50, 0.60, 0.70):
        flagged = [r for r in rows if r["knn_p"] >= cut]
        held = [r for r in rows if r["knn_p"] < cut]
        if not flagged or not held:
            continue
        tp = sum(r["label"] for r in flagged)
        ops.append(
            {
                "threshold": cut,
                "n_flagged": len(flagged),
                "flag_rate": len(flagged) / len(rows),
                "precision": tp / len(flagged),
                "recall": tp / max(sum(r["label"] for r in rows), 1),
                "mean_fwd_flagged": sum(r["actual"] for r in flagged) / len(flagged),
                "mean_fwd_held": sum(r["actual"] for r in held) / len(held),
                "edge": sum(r["actual"] for r in held) / len(held) - sum(r["actual"] for r in flagged) / len(flagged),
            }
        )
    result["operating_points"] = ops
    result["rows"] = rows
    if not quiet:
        _print_metrics(result)
    return result


def _print_metrics(res: dict) -> None:
    if "error" in res:
        print("  " + res["error"])
        return
    thr = res["death_threshold_pct"]
    print(f"  horizon {res['horizon_h']}h  k={res['k']}  threshold: forward SOL return <= {thr:.0f}%")
    print(
        f"  library {res['library_n']} states / {res['library_mints']} "
        f"mints; test {res['n']} thinned states"
    )
    print(f"  base rate  library {res['base_rate_library']:.3f}  test {res['base_rate_test']:.3f}")
    print(
        f"  Brier   kNN {res['brier_knn']:.4f}   random-k "
        f"{res['brier_random_k']:.4f}   climatology {res['brier_climatology']:.4f}"
    )
    lo, hi = res["ci_skill_vs_climatology"]
    print(
        f"  skill vs climatology {res['skill_vs_climatology']:+.4f} "
        f" 95% CI [{lo:+.4f}, {hi:+.4f}] (entity bootstrap)"
    )
    print(f"  skill vs random-k    {res['skill_vs_random_k']:+.4f}")
    lo, hi = res["ci_spearman"]
    print(
        f"  Spearman(pred median, actual) "
        f"{res['spearman_pred_vs_actual']:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]"
    )
    print(
        f"  top decile by P(down): death rate {res['top_decile_death_rate']:.3f} vs base {res['base_rate_test']:.3f}"
        f"  lift {res['top_decile_lift']:.2f}x  (n={res['top_decile_n']})"
    )
    print(
        f"  mean forward return: top decile "
        f"{res['top_decile_mean_fwd']:+.4f} vs all {res['all_mean_fwd']:+.4f}"
    )
    if res.get("operating_points"):
        print(
            f"  {'exit if P(down) >=':<20} {'flagged':>8} {'prec':>7} "
            f"{'recall':>7} {'fwd|flag':>10} {'fwd|hold':>10} {'edge':>8}"
        )
        for op in res["operating_points"]:
            print(
                f"  {op['threshold']:<20.2f} {op['n_flagged']:>8} {op['precision']:>7.3f} {op['recall']:>7.3f}"
                f" {op['mean_fwd_flagged']:>+10.4f} {op['mean_fwd_held']:>+10.4f} {op['edge']:>+8.4f}"
            )


# ---------------------------------------------------------------------------------------
# controls
# ---------------------------------------------------------------------------------------


def control_zero(states: Sequence[dict], horizon: int = 72, k: int = 40, seed: int = 3, adjusted: bool = False) -> dict:
    """Known-ZERO world: outcomes permuted across states, features untouched.

    A working instrument must report no skill here.
    """

    rng = random.Random(seed)
    shuffled = [dict(s) for s in states]
    key = f"fwd_{horizon}" + ("_adj" if adjusted else "")
    vals = [s[key] for s in shuffled if key in s]
    rng.shuffle(vals)
    it = iter(vals)
    for s in shuffled:
        if key in s:
            s[key] = next(it)
    return evaluate(shuffled, horizon=horizon, k=k, quiet=True, adjusted=adjusted)


def null_band(states: Sequence[dict], horizon: int = 72, k: int = 40, seeds: int = 8, adjusted: bool = False) -> dict:
    """The zero-world control run repeatedly, to get a band rather than a point.

    A single null is a knob (PROGRAM.md 3 rule 13's lesson, applied to a different estimator).
    Run on synthetic noise this machinery produced a top-decile lift of **1.79x from nothing**
    on one seed out of eight — so a real lift of 1.5x is not a finding, it is inside the band.
    Every headline number in the RESULT is quoted against this.
    """

    out: dict[str, list[float]] = {"skill": [], "spearman": [], "lift": []}
    for seed in range(1, seeds + 1):
        res = control_zero(states, horizon=horizon, k=k, seed=seed, adjusted=adjusted)
        if "error" in res:
            continue
        out["skill"].append(res["skill_vs_climatology"])
        out["spearman"].append(res["spearman_pred_vs_actual"])
        out["lift"].append(res["top_decile_lift"])
    summary = {}
    for name, vals in out.items():
        vals = [v for v in vals if math.isfinite(v)]
        if vals:
            summary[name] = {
                "mean": statistics.mean(vals),
                "sd": statistics.pstdev(vals),
                "min": min(vals),
                "max": max(vals),
                "n_seeds": len(vals),
            }
    return summary


def control_effect(
    states: Sequence[dict], horizon: int = 72, k: int = 40, seed: int = 5, strength: float = 1.0,
    adjusted: bool = False,
) -> dict:
    """Known-EFFECT world: outcome is a stated function of a feature plus noise.

    PROGRAM.md 3 rule 12 — a null control alone is worthless, because a constant-zero estimator
    passes it perfectly. This is the recovery half: the outcome is made to depend on volume
    growth, and an instrument that cannot find *that* cannot be trusted to have found nothing.
    """

    rng = random.Random(seed)
    planted = [dict(s) for s in states]
    key = f"fwd_{horizon}" + ("_adj" if adjusted else "")
    dv = [s["dvol_24"] for s in planted]
    med = statistics.median(dv)
    iqr = max(statistics.median([abs(x - med) for x in dv]) * 2, 1e-9)
    for s in planted:
        if key in s:
            z = (s["dvol_24"] - med) / iqr
            s[key] = strength * 0.30 * z + rng.gauss(0, 0.30)
    return evaluate(planted, horizon=horizon, k=k, quiet=True, adjusted=adjusted)


def synthetic_worlds(n_mints: int = 250, hours: int = 1000, stride: int = 4, effect: float = 0.0, seed: int = 1) -> list[dict]:
    """A panel with a *known* answer, for calibrating the instrument before trusting it.

    Features are independent standard normals; the forward return is ``effect`` times a stated
    linear function of two of them plus noise. At ``effect=0`` there is nothing to find, and
    anything the pipeline reports is its own false-positive rate.
    """

    rng = random.Random(seed)
    states: list[dict] = []
    t0 = 1_780_000_000
    for m in range(n_mints):
        mint = f"SYNTH{m:04d}"
        for i in range(72, hours, stride):
            s: dict[str, Any] = {f: rng.gauss(0, 1) for f in FEATURES}
            s.update(mint=mint, name=mint, pool=f"P{m}", t=t0 + i * HOUR, i=i, price_usd=1.0, vol24=1e4, fdv=2e5)
            base = effect * (0.35 * s["dvol_24"] - 0.15 * s["ret_24h"])
            for h in (24, 72, 168):
                s[f"fwd_{h}"] = base + rng.gauss(0, 0.35)
            states.append(s)
    return states


def cohort_summary(states: Sequence[dict]) -> dict:
    """What the survivor cohort actually contains, including how much of it died."""

    by_mint: dict[str, list[dict]] = defaultdict(list)
    for s in states:
        by_mint[s["mint"]].append(s)
    peaks, ends, spans, fdvs = [], [], [], []
    collapsed_vol = collapsed_price = 0
    for rows in by_mint.values():
        rows.sort(key=lambda r: r["t"])
        vols = [r["vol24"] for r in rows]
        peak_v, last_v = max(vols), vols[-1]
        peaks.append(peak_v)
        ends.append(last_v)
        spans.append((rows[-1]["t"] - rows[0]["t"]) / 86400.0)
        fdvs.append(rows[-1]["fdv"])
        if peak_v > 0 and last_v / peak_v <= 0.05:
            collapsed_vol += 1
        if rows[-1]["drawdown"] <= math.log(0.20):
            collapsed_price += 1
    n = len(by_mint)
    fwd = [s["fwd_72"] for s in states if "fwd_72" in s]
    return {
        "states": len(states),
        "mints": n,
        "pools": len({s["pool"] for s in states}),
        "median_panel_span_days": statistics.median(spans) if spans else 0.0,
        "median_current_fdv": statistics.median(fdvs) if fdvs else 0.0,
        "fdv_p10": sorted(fdvs)[int(0.1 * (len(fdvs) - 1))] if fdvs else 0.0,
        "fdv_p90": sorted(fdvs)[int(0.9 * (len(fdvs) - 1))] if fdvs else 0.0,
        "coins_volume_collapsed_95pct": collapsed_vol,
        "coins_volume_collapsed_frac": collapsed_vol / n if n else 0.0,
        "coins_down_80pct_from_peak": collapsed_price,
        "coins_down_80pct_frac": collapsed_price / n if n else 0.0,
        "median_fwd_72h": statistics.median(fwd) if fwd else float("nan"),
        "frac_fwd_72h_below_minus20": (sum(1 for v in fwd if v <= DEATH_THRESHOLD) / len(fwd)) if fwd else float("nan"),
    }


# ---------------------------------------------------------------------------------------
# the lead/lag hypothesis
# ---------------------------------------------------------------------------------------


def hypothesis_test(states: Sequence[dict], horizon: int = 72, adjusted: bool = False) -> dict:
    """price LAGS, volume LEADS — stated so it can fail.

    The claim: a coin whose price is flat while volume erodes underneath is being distributed
    into, and its forward return is worse than a coin whose price and volume move together.
    The statistic is ``divergence = z(ret_24h) - z(dvol_24)`` with both scales fitted on the
    library — high when price holds up as support falls away. **If the claim is true, the
    Spearman correlation between divergence and forward return is NEGATIVE.** A positive or
    zero correlation refutes it, and that is a result worth having: it is exactly the check
    three prior studies in this repo skipped.

    Evaluated out of sample on the temporal split, never in sample, and reported per window
    because aggregate reporting hides regime collapse (PROGRAM.md 3 rule 6).
    """

    key = f"fwd_{horizon}" + ("_adj" if adjusted else "")
    library_all, test_all = temporal_split(states, horizon, key=key)
    library = thin(library_all, 12)
    test = thin(test_all, horizon)
    if len(test) < 40 or len(library) < 100:
        return {"error": f"insufficient data: library={len(library)} test={len(test)}"}
    add_divergence_z(library, library)
    add_divergence_z(test, library)
    out: dict[str, Any] = {"horizon_h": horizon, "n_test": len(test), "n_library": len(library)}

    for name in ("divergence", "dvol_24", "ret_24h", "log_vol_ratio_7d", "active_frac_24h", "drawdown"):
        xs = [s[name] for s in test]
        ys = [s[key] for s in test]
        rho = spearman(xs, ys)
        lo, hi = block_bootstrap_ci(
            [{"mint": s["mint"], "x": s[name], "y": s[key]} for s in test],
            lambda rs: spearman([r["x"] for r in rs], [r["y"] for r in rs]),
        )
        out[name] = {"spearman": rho, "ci95": [lo, hi]}

    # Terciles of divergence, fitted on the LIBRARY so the cut is not chosen on the test set.
    div = sorted(s["divergence"] for s in library)
    lo_cut = div[len(div) // 3]
    hi_cut = div[2 * len(div) // 3]
    buckets: dict[str, list[float]] = {"low": [], "mid": [], "high": []}
    deaths: dict[str, list[int]] = {"low": [], "mid": [], "high": []}
    for s in test:
        b = "low" if s["divergence"] < lo_cut else ("high" if s["divergence"] >= hi_cut else "mid")
        buckets[b].append(s[key])
        deaths[b].append(1 if s[key] <= DEATH_THRESHOLD else 0)
    out["tercile_cuts"] = {"low_below": lo_cut, "high_above": hi_cut}
    out["terciles"] = {
        b: {
            "n": len(v),
            "mean_fwd": (sum(v) / len(v)) if v else float("nan"),
            "median_fwd": statistics.median(v) if v else float("nan"),
            "death_rate": (sum(deaths[b]) / len(deaths[b])) if deaths[b] else float("nan"),
        }
        for b, v in buckets.items()
    }

    # Per-window breakdown: three equal slices of the test period.
    ts = sorted(s["t"] for s in test)
    edges = [ts[0], ts[len(ts) // 3], ts[2 * len(ts) // 3], ts[-1] + 1]
    windows = []
    for w in range(3):
        sub = [s for s in test if edges[w] <= s["t"] < edges[w + 1]]
        if len(sub) >= 15:
            windows.append(
                {
                    "from": time.strftime("%Y-%m-%d", time.gmtime(edges[w])),
                    "to": time.strftime("%Y-%m-%d", time.gmtime(edges[w + 1])),
                    "n": len(sub),
                    "spearman_divergence": spearman([s["divergence"] for s in sub], [s[key] for s in sub]),
                    "mean_fwd": sum(s[key] for s in sub) / len(sub),
                }
            )
    out["windows"] = windows
    return out


# ---------------------------------------------------------------------------------------
# live read
# ---------------------------------------------------------------------------------------


def dexscreener_pairs(mints: Sequence[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for chunk_start in range(0, len(mints), 20):
        chunk = mints[chunk_start : chunk_start + 20]
        url = f"{DS}/latest/dex/tokens/{','.join(chunk)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "joshibot-deterioration-study/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read())
        except Exception as exc:
            print(f"  dexscreener failed: {exc}", file=sys.stderr)
            continue
        for pair in payload.get("pairs") or []:
            base = (pair.get("baseToken") or {}).get("address")
            if base:
                out[base].append(pair)
        time.sleep(0.5)
    return out


def live_snapshot(fetcher: Fetcher, mint: str, label: str = "") -> dict:
    """The full current state vector, including the parts history cannot give us.

    Appended to ``state/deterioration/snapshots.jsonl`` on every call. That file is the only
    keyless route to a *historical* liquidity/holders/flow panel, and it only accumulates if
    this runs.
    """

    all_pairs = dexscreener_pairs([mint]).get(mint, [])
    # SOL/USDC-quoted only. weave has seven pairs including weave/nosis; picking that one would
    # make the price series a ratio of two cluster tokens and the "SOL-denominated return"
    # silently meaningless.
    pairs = [p for p in all_pairs if (p.get("quoteToken") or {}).get("address") in QUOTE_OK]
    pairs.sort(key=lambda p: -(_f((p.get("liquidity") or {}).get("usd")) or 0.0))
    top = pairs[0] if pairs else {}
    pool = top.get("pairAddress")
    gt_pool = fetcher.get(f"{GT}/networks/solana/pools/{pool}") if pool else None
    gt_attrs = ((gt_pool or {}).get("data") or {}).get("attributes") or {}
    info = fetcher.get(f"{GT}/networks/solana/tokens/{mint}/info")
    info_attrs = ((info or {}).get("data") or {}).get("attributes") or {}
    holders = info_attrs.get("holders") or {}

    snap = {
        "kind": "snapshot",
        "mint": mint,
        "label": label or (top.get("baseToken") or {}).get("symbol", ""),
        "t": int(time.time()),
        "pool": pool,
        "dex": top.get("dexId"),
        "price_usd": _f(top.get("priceUsd")),
        "price_native": _f(top.get("priceNative")),
        "fdv": _f(top.get("fdv")),
        "market_cap": _f(top.get("marketCap")),
        "liquidity_usd": _f((top.get("liquidity") or {}).get("usd")),
        "liquidity_quote": _f((top.get("liquidity") or {}).get("quote")),
        "pair_created_at": top.get("pairCreatedAt"),
        "volume": top.get("volume") or {},
        "price_change": top.get("priceChange") or {},
        "txns": top.get("txns") or {},
        # GeckoTerminal carries the distinction DexScreener does not: buyers/sellers are
        # WALLETS, buys/sells are TRANSACTIONS. The operator observed 73% of nosis wallets net
        # sellers against 54% of transactions being sells; those are different statistics and
        # the gap is the informative part.
        "gt_transactions": gt_attrs.get("transactions") or {},
        "gt_volume": gt_attrs.get("volume_usd") or {},
        "gt_reserve_usd": _f(gt_attrs.get("reserve_in_usd")),
        "gt_locked_liquidity_pct": _f(gt_attrs.get("locked_liquidity_percentage")),
        "gt_pool_created_at": gt_attrs.get("pool_created_at"),
        "holders_count": holders.get("count"),
        "holders_distribution": holders.get("distribution_percentage"),
        "gt_score": info_attrs.get("gt_score"),
        "n_pairs_sol_quoted": len(pairs),
        "n_pairs_all": len(all_pairs),
        "source": "dexscreener.tokens + geckoterminal.pool + geckoterminal.token_info",
    }
    jsonl_append(SNAPSHOTS, [snap])
    return snap


def liquidity_counterfactual(snap: dict, price_then_over_now: float) -> float | None:
    """What the pool's SOL side *would* be at a past price if nobody had added or removed LP.

    For a constant-product pool ``x*y=k`` with token price ``p = y/x``, the quote reserve obeys
    ``y = sqrt(k*p)``, so ``y(t)/y(now) = sqrt(p(t)/p(now))``. This is exact under trading and
    exact only under trading.

    It is reported as a *reference line*, never as a feature, and the reason is the whole point
    of the study: the deviation between this line and the true past reserve IS the net LP
    add/remove — which is precisely the deterioration signal we want and precisely the thing
    keyless history does not contain. Feeding the counterfactual to the model would be feeding
    it a deterministic function of price and calling the result a liquidity signal.
    """

    liq = snap.get("liquidity_quote")
    if not liq or price_then_over_now <= 0:
        return None
    return liq * math.sqrt(price_then_over_now)


def read_coin(
    fetcher: Fetcher,
    mint: str,
    label: str,
    states: Sequence[dict],
    horizon: int = 72,
    k: int = 40,
    show: int = 8,
) -> dict:
    snap = live_snapshot(fetcher, mint, label)
    print(f"\n=== {label or mint[:8]} ({mint}) ===")
    if not snap.get("price_usd"):
        print("  no DexScreener pair found")
        return {}
    age_days = (
        (time.time() - snap["pair_created_at"] / 1000.0) / 86400.0 if snap.get("pair_created_at") else float("nan")
    )
    txn = snap.get("txns", {}).get("h24", {})
    gtx = snap.get("gt_transactions", {}).get("h24", {})
    buys, sells = txn.get("buys", 0), txn.get("sells", 0)
    buyers, sellers = gtx.get("buyers", 0), gtx.get("sellers", 0)
    tx_sell_share = sells / (buys + sells) if (buys + sells) else float("nan")
    wallet_sell_share = sellers / (buyers + sellers) if (buyers + sellers) else float("nan")
    print(
        f"  price ${snap['price_usd']:.8g}  FDV ${snap['fdv']:,.0f}  liquidity ${snap['liquidity_usd']:,.0f}"
        f"  age {age_days:.1f}d  holders {snap.get('holders_count')}"
    )
    print(
        f"  vol 24h ${(snap.get('volume') or {}).get('h24', 0):,.0f}   "
        f"price change 5m/1h/6h/24h: "
        + "/".join(
            f"{(snap.get('price_change') or {}).get(h, float('nan')):+.1f}%" for h in ("m5", "h1", "h6", "h24")
        )
    )
    print(
        f"  24h flow: {buys} buys / {sells} sells (tx sell share {tx_sell_share:.0%})   "
        f"{buyers} buyers / {sellers} sellers (WALLET sell share {wallet_sell_share:.0%})   "
        f"divergence {wallet_sell_share - tx_sell_share:+.0%}"
    )
    dist = snap.get("holders_distribution") or {}
    if dist:
        print(
            f"  holder concentration: top10 {dist.get('top_10')}%  "
            f"11-20 {dist.get('11_20')}%  rest {dist.get('rest')}%"
        )

    query = query_state(fetcher, snap)
    if query is None:
        print("  could not build a comparable state vector (need >=72h of hourly history)")
        return {"snapshot": snap}
    library = thin([s for s in states if f"fwd_{horizon}" in s], 12)
    if len(library) < 100:
        print(f"  library too small ({len(library)}) for analogues")
        return {"snapshot": snap, "state": query}
    scaler = Scaler.fit(library)
    store = Library(library, scaler)
    add_divergence_z(library, library)
    add_divergence_z([query], library)
    nn = store.nearest(query, k=k, exclude_mint=mint)
    fc = neighbour_forecast(nn, horizon, DEATH_THRESHOLD)
    # How far outside the library is this query? A neighbour set that is 3x further away than a
    # typical library point's neighbours is extrapolation wearing the costume of an analogy.
    ref = []
    rng_ref = random.Random(19)
    for probe in rng_ref.sample(library, min(60, len(library))):
        pn = store.nearest(probe, k=k, exclude_mint=probe["mint"])
        if pn:
            ref.append(sum(d for d, _ in pn) / len(pn))
    mean_d = sum(d for d, _ in nn) / len(nn) if nn else float("nan")
    typical = statistics.median(ref) if ref else float("nan")
    print("  state: " + "  ".join(f"{f}={query[f]:+.2f}" for f in FEATURES))
    print(
        f"  divergence z(ret_24h) - z(dvol_24) = {query['divergence']:+.3f} "
        f" (positive = price holding up while volume erodes)"
    )
    print(f"\n  --- {fc['n']} nearest historical analogues, {horizon}h forward (SOL-denominated) ---")
    print(
        f"  median {fc['median']:+.1%}   mean {fc['mean']:+.1%} "
        f"  p10 {fc['p10']:+.1%}   p90 {fc['p90']:+.1%}"
    )
    print(f"  analogues drawn from {fc['distinct_mints']} distinct coins"
          + ("   <-- TOO FEW, the percentiles above are not {} independent observations".format(fc["n"])
             if fc["distinct_mints"] < 8 else ""))
    print(f"  P(<= -20%) = {fc['p_down']:.0%}   base rate in library = "
          f"{sum(1 for s in library if s[f'fwd_{horizon}'] <= DEATH_THRESHOLD) / len(library):.0%}")
    print(
        f"  match quality: mean neighbour distance {mean_d:.2f} vs {typical:.2f} typical "
        f"({mean_d / typical:.1f}x)" + ("  <-- EXTRAPOLATING, treat analogues as weak" if typical and mean_d > 2 * typical else "")
    )
    print(
        f"\n  {'analogue':<26} {'when':<11} {'dist':>5} {'fdv':>10} "
        f"{'vol24':>10} {'ret24h':>8} {'dvol':>7} {'-> fwd':>8}"
    )
    for dist_val, n in nn[:show]:
        print(
            f"  {n['name'][:26]:<26} {time.strftime('%Y-%m-%d', time.gmtime(n['t'])):<11} {dist_val:5.2f}"
            f" {n['fdv']:10,.0f} {n['vol24']:10,.0f} {n['ret_24h']:+8.2%} {n['dvol_24']:+7.2f}"
            f" {n.get(f'fwd_{horizon}', float('nan')):+8.1%}"
        )
    return {"snapshot": snap, "state": query, "forecast": fc, "neighbours": nn}


def dexscreener_by_pair(pairs: Sequence[str]) -> dict[str, dict]:
    """Bulk current state by pool address, 30 at a time.

    DexScreener's pair endpoint is the cheap half of the flow picture: transaction-level
    buys/sells for dozens of peers costs a handful of calls against a 300/min budget, where the
    wallet-level counts cost one contended GeckoTerminal call each.
    """

    out: dict[str, dict] = {}
    for start in range(0, len(pairs), 30):
        chunk = pairs[start : start + 30]
        url = f"{DS}/latest/dex/pairs/solana/{','.join(chunk)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "joshibot-deterioration-study/0.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read())
        except Exception as exc:
            print(f"  dexscreener pairs failed: {exc}", file=sys.stderr)
            continue
        for pair in payload.get("pairs") or []:
            if pair.get("pairAddress"):
                out[pair["pairAddress"]] = pair
        time.sleep(0.4)
    return out


def _sell_shares(pair: dict) -> tuple[float | None, int]:
    txn = (pair.get("txns") or {}).get("h24") or {}
    buys, sells = txn.get("buys", 0), txn.get("sells", 0)
    total = buys + sells
    return (sells / total if total else None), total


def peer_flow(fetcher: Fetcher, mint: str, label: str, n_peers: int = 60, n_gt: int = 12) -> dict:
    """Where this coin's sell pressure sits among *scale-matched peers today*.

    The operator's observation is the motivation: on nosis, 73% of wallets were net sellers
    while only 54% of transactions were sells — many small sellers against fewer larger buyers.
    Those are genuinely different statistics and their gap is informative, but a raw 73% means
    nothing without knowing what a normal coin of this size looks like on the same day. This
    puts a percentile on it.

    Transaction-level shares come from DexScreener in bulk (cheap). Wallet-level shares come
    from GeckoTerminal one pool at a time (contended), so only ``n_gt`` peers get them.
    """

    snap = live_snapshot(fetcher, mint, label)
    fdv = snap.get("fdv") or 0.0
    if not fdv:
        return {"error": "no FDV for query coin"}
    rows = candidates()
    band = [
        r
        for r in rows
        if r["pool"] != snap.get("pool")
        and 0.25 * fdv <= (_f(r.get("fdv_usd")) or 0) <= 4.0 * fdv
        and (_f(r.get("vol_h24")) or 0) > 0
    ]
    band.sort(key=lambda r: abs(math.log(max(_f(r.get("fdv_usd")) or 1.0, 1.0) / fdv)))
    band = band[:n_peers]
    if len(band) < 8:
        return {"error": f"only {len(band)} scale-matched peers in the discovery cache"}

    live = dexscreener_by_pair([r["pool"] for r in band])
    tx_shares: list[tuple[float, str]] = []
    for pool, pair in live.items():
        share, total = _sell_shares(pair)
        if share is not None and total >= 30:  # threshold stated: >=30 txs in 24h
            tx_shares.append((share, (pair.get("baseToken") or {}).get("symbol", pool[:6])))
    q_share, _q_total = _sell_shares({"txns": snap.get("txns") or {}})

    gtx = (snap.get("gt_transactions") or {}).get("h24") or {}
    buyers, sellers = gtx.get("buyers", 0), gtx.get("sellers", 0)
    q_wallet = sellers / (buyers + sellers) if (buyers + sellers) else None

    wallet_rows: list[tuple[float, float, str]] = []
    for row in band[:n_gt]:
        payload = fetcher.get(f"{GT}/networks/solana/pools/{row['pool']}")
        attrs = ((payload or {}).get("data") or {}).get("attributes") or {}
        h24 = (attrs.get("transactions") or {}).get("h24") or {}
        b, s = h24.get("buyers", 0), h24.get("sellers", 0)
        tb, ts = h24.get("buys", 0), h24.get("sells", 0)
        if (b + s) >= 20 and (tb + ts) >= 30:
            wallet_rows.append((s / (b + s), ts / (tb + ts), attrs.get("name", row["pool"][:8])))

    def pct(value: float, pool_vals: Sequence[float]) -> float:
        if not pool_vals:
            return float("nan")
        return 100.0 * sum(1 for v in pool_vals if v <= value) / len(pool_vals)

    return {
        "label": label,
        "fdv": fdv,
        "n_peers_tx": len(tx_shares),
        "n_peers_wallet": len(wallet_rows),
        "tx_sell_share": q_share,
        "tx_sell_share_pctile": pct(q_share, [s for s, _ in tx_shares]) if q_share is not None else float("nan"),
        "peer_tx_sell_share_median": statistics.median([s for s, _ in tx_shares]) if tx_shares else float("nan"),
        "wallet_sell_share": q_wallet,
        "wallet_sell_share_pctile": pct(q_wallet, [w for w, _, _ in wallet_rows]) if q_wallet is not None else float("nan"),
        "peer_wallet_sell_share_median": statistics.median([w for w, _, _ in wallet_rows]) if wallet_rows else float("nan"),
        "divergence": (q_wallet - q_share) if (q_wallet is not None and q_share is not None) else None,
        "peer_divergence_median": statistics.median([w - t for w, t, _ in wallet_rows]) if wallet_rows else float("nan"),
        "divergence_pctile": pct(q_wallet - q_share, [w - t for w, t, _ in wallet_rows])
        if (q_wallet is not None and q_share is not None and wallet_rows)
        else float("nan"),
        "peers_wallet_detail": [{"name": n, "wallet_sell": w, "tx_sell": t} for w, t, n in wallet_rows],
    }


def query_state(fetcher: Fetcher, snap: dict) -> dict | None:
    """Build the *historical-comparable* state vector for a live coin.

    Deliberately built from the same OHLCV pipeline as the panel rather than from the richer
    live snapshot. Matching a live vector containing holders and liquidity against a library
    that has neither would be comparing different spaces; the extra live fields are printed for
    the operator's judgement, not fed to the metric.
    """

    pool = snap.get("pool")
    if not pool:
        return None
    record = fetch_ohlcv(fetcher, pool, refresh_hours=1.0)
    if not record:
        return None
    meta = {
        "base_mint": snap["mint"],
        "name": snap.get("label") or pool[:8],
        "created_at": snap.get("gt_pool_created_at"),
        "fdv_usd": snap.get("fdv"),
    }
    series = load_series(pool, meta)
    if series is None:
        return None
    sol = SolUsd(_sol_reference(fetcher))
    return state_at(series, len(series) - 1, snap.get("fdv"), sol)


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------


def cmd_discover(args: argparse.Namespace) -> None:
    discover(Fetcher(min_interval=args.interval), pages=args.pages)


def cmd_ohlcv(args: argparse.Namespace) -> None:
    pull_histories(Fetcher(min_interval=args.interval), limit_pools=args.limit)


def cmd_panel(args: argparse.Namespace) -> None:
    build_panel(Fetcher(min_interval=args.interval), stride=args.stride)


def cmd_evaluate(args: argparse.Namespace) -> None:
    global DEATH_THRESHOLD
    if args.threshold_pct is not None:
        DEATH_THRESHOLD = math.log(1 + args.threshold_pct / 100.0)
    states = load_panel()
    print(f"panel: {len(states)} states, {len({s['mint'] for s in states})} mints")
    for horizon in args.horizons:
        tag = "market-adjusted" if args.adjusted else "raw SOL"
        print(f"\n### kNN, horizon {horizon}h, {tag} forward returns")
        res = evaluate(states, horizon=horizon, k=args.k, adjusted=args.adjusted)
        if "error" in res:
            continue
        print(f"\n  [control: known-ZERO world, outcomes permuted, {args.seeds} seeds]")
        band = null_band(states, horizon=horizon, k=args.k, seeds=args.seeds, adjusted=args.adjusted)
        for name in ("skill", "spearman", "lift"):
            if name in band:
                b = band[name]
                real = {
                    "skill": res["skill_vs_climatology"],
                    "spearman": res["spearman_pred_vs_actual"],
                    "lift": res["top_decile_lift"],
                }[name]
                verdict = "OUTSIDE null band" if real > b["max"] else "inside null band"
                print(
                    f"    {name:<9} null mean {b['mean']:+.4f} sd {b['sd']:.4f} max {b['max']:+.4f}"
                    f"   |  observed {real:+.4f}  -> {verdict}"
                )
        print("  [control: known-EFFECT world, outcome planted on dvol_24]")
        eff = control_effect(states, horizon=horizon, k=args.k, adjusted=args.adjusted)
        if "error" not in eff:
            print(
                f"    skill vs climatology {eff['skill_vs_climatology']:+.4f}   "
                f"Spearman {eff['spearman_pred_vs_actual']:+.4f}   top-decile lift {eff['top_decile_lift']:.2f}x"
            )


def cmd_hypothesis(args: argparse.Namespace) -> None:
    states = load_panel()
    for horizon in args.horizons:
        res = hypothesis_test(states, horizon=horizon, adjusted=args.adjusted)
        print(
            f"\n### lead/lag, horizon {horizon}h, "
            f"{'market-adjusted' if args.adjusted else 'raw SOL'} forward returns"
        )
        if "error" in res:
            print("  " + res["error"])
            continue
        print(f"  test states {res['n_test']} (thinned), library {res['n_library']}")
        for name in ("divergence", "dvol_24", "ret_24h", "log_vol_ratio_7d", "active_frac_24h", "drawdown"):
            r = res[name]
            lo, hi = r["ci95"]
            sig = "" if (math.isnan(lo) or lo <= 0 <= hi) else "  *"
            print(f"    Spearman({name:<18}, fwd) = {r['spearman']:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]{sig}")
        print(
            f"  divergence terciles (cuts from library: <{res['tercile_cuts']['low_below']:+.3f} "
            f"/ >{res['tercile_cuts']['high_above']:+.3f}):"
        )
        for b in ("low", "mid", "high"):
            t = res["terciles"][b]
            print(
                f"    {b:<5} n={t['n']:<5} mean fwd {t['mean_fwd']:+.4f}  median {t['median_fwd']:+.4f}"
                f"  death rate (<= -20%) {t['death_rate']:.3f}"
            )
        for w in res["windows"]:
            print(
                f"    window {w['from']}..{w['to']} n={w['n']:<4} Spearman(divergence) "
                f"{w['spearman_divergence']:+.4f}  mean fwd {w['mean_fwd']:+.4f}"
            )


def cmd_cohort(args: argparse.Namespace) -> None:
    summary = cohort_summary(load_panel())
    print("### survivor cohort")
    for key, value in summary.items():
        if isinstance(value, float):
            print(f"  {key:<34} {value:,.4f}")
        else:
            print(f"  {key:<34} {value:,}")


def cmd_selftest(args: argparse.Namespace) -> None:
    """Calibrate the instrument on worlds whose answer is known before reading the real one."""

    print(f"### synthetic worlds sized to {args.mints} coins\n")
    print("### known-EFFECT world (forward return = 0.35*dvol_24 - 0.15*ret_24h + noise)")
    evaluate(synthetic_worlds(n_mints=args.mints, effect=1.0), horizon=72, k=args.k)
    print(f"\n### known-ZERO world (independent features, pure-noise outcome), {args.seeds} seeds")
    print("    This is the instrument's own false-positive distribution. Any real number that")
    print("    does not clear this band is not a finding. The band WIDENS as the cohort shrinks,")
    print("    so calibrate --mints to the cohort actually achieved before quoting it.")
    for name, b in null_band(synthetic_worlds(n_mints=args.mints, effect=0.0), horizon=72, k=args.k, seeds=args.seeds).items():
        print(
            f"  {name:<9} mean {b['mean']:+.4f}  sd {b['sd']:.4f} "
            f" min {b['min']:+.4f}  max {b['max']:+.4f}"
        )


def cmd_peers(args: argparse.Namespace) -> None:
    fetcher = Fetcher(min_interval=args.interval)
    targets = CLUSTER.items() if args.coin == "all" else [(args.coin, CLUSTER.get(args.coin, args.coin))]
    for label, mint in targets:
        res = peer_flow(fetcher, mint, label, n_peers=args.n, n_gt=args.gt)
        print(f"\n=== {label}: sell pressure against scale-matched peers today ===")
        if "error" in res:
            print("  " + res["error"])
            continue
        print(f"  FDV ${res['fdv']:,.0f}; peers within 0.25x-4x FDV: {res['n_peers_tx']} (tx-level, >=30 txs/24h)"
              f", {res['n_peers_wallet']} (wallet-level)")
        print(
            f"  TRANSACTION sell share {res['tx_sell_share']:.1%}  vs peer median "
            f"{res['peer_tx_sell_share_median']:.1%}   -> {res['tx_sell_share_pctile']:.0f}th percentile"
        )
        if res["wallet_sell_share"] is not None:
            print(
                f"  WALLET      sell share {res['wallet_sell_share']:.1%}  vs peer median "
                f"{res['peer_wallet_sell_share_median']:.1%}   -> {res['wallet_sell_share_pctile']:.0f}th percentile"
            )
            print(
                f"  divergence (wallet - transaction) {res['divergence']:+.1%}  vs peer median "
                f"{res['peer_divergence_median']:+.1%}   -> {res['divergence_pctile']:.0f}th percentile"
            )


def cmd_read(args: argparse.Namespace) -> None:
    states = load_panel()
    fetcher = Fetcher(min_interval=args.interval)
    mint = CLUSTER.get(args.mint, args.mint)
    read_coin(fetcher, mint, args.mint, states, horizon=args.horizon, k=args.k)


def cmd_live(args: argparse.Namespace) -> None:
    states = load_panel()
    fetcher = Fetcher(min_interval=args.interval)
    print(f"library: {len(states)} panel states, {len({s['mint'] for s in states})} mints")
    for label, mint in CLUSTER.items():
        read_coin(fetcher, mint, label, states, horizon=args.horizon, k=args.k)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--interval", type=float, default=3.0, help="minimum seconds between API calls")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("discover")
    p.add_argument("--pages", type=int, default=10)
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("ohlcv")
    p.add_argument("--limit", type=int, default=400)
    p.set_defaults(func=cmd_ohlcv)

    p = sub.add_parser("panel")
    p.add_argument("--stride", type=int, default=4)
    p.set_defaults(func=cmd_panel)

    p = sub.add_parser("evaluate")
    p.add_argument("--horizons", type=int, nargs="+", default=[24, 72, 168])
    p.add_argument("--k", type=int, default=40)
    p.add_argument("--seeds", type=int, default=8, help="zero-world control seeds (the null band)")
    p.add_argument(
        "--threshold-pct",
        type=float,
        default=None,
        help="define 'deteriorated' as a forward SOL return at or below this percent (default -20)",
    )
    p.add_argument(
        "--adjusted",
        action="store_true",
        help="score against MARKET-ADJUSTED forward returns (coin minus contemporaneous cohort "
             "median). The decisive falsification: a signal that only survives on raw returns is "
             "reading market direction, not this coin.",
    )
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("hypothesis")
    p.add_argument("--horizons", type=int, nargs="+", default=[24, 72, 168])
    p.add_argument("--adjusted", action="store_true", help="market-adjusted forward returns")
    p.set_defaults(func=cmd_hypothesis)

    p = sub.add_parser("cohort")
    p.set_defaults(func=cmd_cohort)

    p = sub.add_parser("peers")
    p.add_argument("coin", nargs="?", default="all")
    p.add_argument("--n", type=int, default=60, help="scale-matched peers for transaction-level flow")
    p.add_argument("--gt", type=int, default=12, help="peers to also pull WALLET-level flow for (1 GT call each)")
    p.set_defaults(func=cmd_peers)

    p = sub.add_parser("selftest")
    p.add_argument("--k", type=int, default=40)
    p.add_argument("--seeds", type=int, default=8)
    p.add_argument("--mints", type=int, default=250, help="synthetic cohort size; set to the real one")
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("read")
    p.add_argument("mint")
    p.add_argument("--horizon", type=int, default=72)
    p.add_argument("--k", type=int, default=40)
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("live")
    p.add_argument("--horizon", type=int, default=72)
    p.add_argument("--k", type=int, default=40)
    p.set_defaults(func=cmd_live)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
