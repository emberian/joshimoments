"""Do the accounts that call coins out trade them first?

THE QUESTION
------------
`studies/RESULT_callout_edge.md` measured the callout channel and found an
anti-signal: buying a callout returns −11.9% at 1 h and −43.6% at 8 h, and
permuting caller identity *beats* the real assignment 24 of 24 times. The
natural mechanism for an anti-signal is that the callout is not the start of
the move but the **end** of it — the caller bought first, called second, and
the callout-induced flow is their exit. If that is what happens, the tradeable
object was never the callout: it was the caller's on-chain BUY, minutes
earlier, and the callout timestamp is a SELL marker.

Nobody has measured the buy → call → sell choreography. This does.

THE JOIN, WHICH IS THE HARD PART
--------------------------------
An X handle is not a wallet. Four routes are tried and each one's yield is
reported, because "we could not join" is a measurement about this market and
not a failure of effort:

1. **pump.fun username == X handle.** `/users/search?searchTerm=` is the live
   endpoint (discovered 2026-08-15; `/users/search?username=` and `?q=` both
   return `[]` unconditionally and would have read as a clean null). It matches
   pump.fun *usernames*, not X handles, so it only fires when a caller uses the
   same name on both.
2. **pump.fun's own X link.** The user object carries `x_username` / `x_id`.
   Present in the schema, and measured null on every profile probed — so the
   native link that would make this study a lookup is not served today.
3. **The coin's own X account.** pump.fun coin metadata carries `twitter`. When
   the handle in it *is* one of our callers, the caller is the project, and the
   coin's `creator` is a wallet we can attribute.
4. **The temporal join**, which is the fallback and is itself the evidence:
   wallets that repeatedly bought minutes before a *specific* account's
   callouts, across multiple coins. This is exactly the shape of claim that
   `RESULT_copytrading.md` watched collapse from 73× to 0.98× when the null
   learned to preserve burstiness, so it is run against a null that permutes
   caller identity while keeping every mint's own trading structure, and the
   per-caller p-values carry FDR.

THE INSTRUMENT
--------------
On-chain side: one BigQuery scan of
`bigquery-public-data.crypto_solana_mainnet_us.Transactions` over
2026-08-14 00:00 → 2026-08-15 03:00 UTC, reduced in-query to per-(mint, owner)
trade arrays. Token-balance `owner` *is* the trader, so the 267 GB/day
`accounts` column is never touched. Measured 191.2 GB scanned, ~$1.11.

Callout side: the census `studies/callout_backfill.py` already collected, and
`studies/callout_edge.py`'s cohort builder, imported rather than reimplemented
so the two studies cannot drift.

Reproducing the pull (`--emit-sql` prints exactly what was run; always dry-run
first, and the cap is not optional):

    python -m studies.caller_wallets --emit-sql > /tmp/cw.sql
    bq --project_id=<billing> query --use_legacy_sql=false --dry_run < /tmp/cw.sql
    bq --project_id=<billing> query --use_legacy_sql=false \
       --maximum_bytes_billed=250000000000 --format=json --max_rows=3000000 \
       < /tmp/cw.sql > .cache/caller_wallets/deltas.json
    python -m studies.caller_wallets --rebuild-tapes

A destination table would be tidier and does not work: this account can read
`bigquery-public-data` for a plain query and is denied the *same* read the
moment `--destination_table` is set. Streaming the result to JSON is the
workaround, hence the ARRAY_AGG that keeps the payload at 136 MB.

DISCIPLINE
----------
- One clock per field: `t_post` is the tweet's own clock, `t` on a trade is the
  block clock. They are compared, never mixed.
- Amounts are token base units as exact integers, never floats. SOL legs are
  not in token balances and are deliberately not guessed at; every volume
  statement here is in token units, normalised per mint.
- The pool is not a trader. Bonding-curve, associated-bonding-curve and
  PumpSwap pool addresses are excluded by *address from metadata*, not by a
  heuristic on trade size.
- Anything fitted on callers (the temporal linkage) is fitted on the TRAIN
  period only and applied to the test period, or it is leakage wearing a
  results table.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import glob
import json
import math
import pickle
import random
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / ".cache" / "caller_wallets"
DELTAS_JSON = CACHE / "deltas.json"
COMPACT = CACHE / "trades.pkl"
COINS = CACHE / "coins"
PROFILES = CACHE / "profiles"
JOIN_OUT = CACHE / "join.json"

PUMP_API = "https://frontend-api-v3.pump.fun"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

#: The tape pin `RESULT_callout_edge.md` reports against. Kept identical so the
#: two studies talk about the same 314 callouts and the same returns.
TAPE_END = 1786767709.0

#: BigQuery window actually pulled. Anything before this is invisible on chain,
#: which matters for the 80 of 276 cohort coins created before it.
BQ_LO = 1786752000 - 86400  # 2026-08-14 00:00:00 UTC
BQ_HI = 1786838400 + 10800 - 86400  # 2026-08-15 03:00:00 UTC

#: A "pre-buy" is a buy inside this many seconds before the callout. 30 min is
#: wide enough to catch a deliberate accumulate-then-shill and narrow enough
#: that the coincidence rate is not simply "everyone who ever held it".
PRE_BUY_WINDOW_S = 1800
#: The callout-induced flow window: where a caller's exit would land if the
#: callout is what they are selling into.
FLOW_WINDOW_S = 3600


# ---------------------------------------------------------------------------
# on-chain tape
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MintTape:
    """Every wallet's token-balance deltas on one mint, in block-time order."""

    mint: str
    # wallet -> [(t, delta_base_units)], time-ordered
    by_wallet: dict[str, list[tuple[int, int]]]
    # flat, time-ordered (t, wallet, delta)
    flat: list[tuple[int, str, int]]
    # block times of `flat`, kept alongside so window lookups can bisect
    times: list[int]

    @property
    def first_trade(self) -> int:
        return self.flat[0][0] if self.flat else 0

    def _slice(self, lo: float, hi: float) -> Iterable[tuple[int, str, int]]:
        """Trades in [lo, hi], found by bisect — the nulls call this ~10^5 times."""

        times = self.times
        i = bisect.bisect_left(times, math.ceil(lo))
        j = bisect.bisect_right(times, math.floor(hi))
        return self.flat[i:j]

    def buy_volume(self, lo: float, hi: float) -> int:
        return sum(d for _, _, d in self._slice(lo, hi) if d > 0)

    def sell_volume(self, lo: float, hi: float) -> int:
        return sum(-d for _, _, d in self._slice(lo, hi) if d < 0)

    def buyers_between(self, lo: float, hi: float) -> set[str]:
        return {w for _, w, d in self._slice(lo, hi) if d > 0}


def pool_addresses() -> set[str]:
    """Addresses that are liquidity, not traders — taken from metadata, never guessed.

    A size heuristic ("the biggest counterparty is the pool") would silently
    reclassify a whale as liquidity on a thin coin, which is precisely the row
    this study is hunting for.
    """

    out: set[str] = set()
    for path in glob.glob(str(COINS / "*.json")):
        try:
            meta = json.loads(Path(path).read_text())
        except Exception:
            continue
        if meta.get("_notfound"):
            continue
        for key in (
            "bonding_curve",
            "associated_bonding_curve",
            "pump_swap_pool",
            "pool_address",
        ):
            value = meta.get(key)
            if isinstance(value, str) and value:
                out.add(value)
    return out


def coin_meta() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in glob.glob(str(COINS / "*.json")):
        try:
            meta = json.loads(Path(path).read_text())
        except Exception:
            continue
        if not meta.get("_notfound") and meta.get("mint"):
            out[meta["mint"]] = meta
    return out


def load_tapes(*, rebuild: bool = False) -> dict[str, MintTape]:
    """Per-mint wallet tapes, cached compactly because the raw pull is 136 MB."""

    if COMPACT.exists() and not rebuild:
        with COMPACT.open("rb") as fh:
            return pickle.load(fh)
    raw = json.loads(DELTAS_JSON.read_text())
    pools = pool_addresses()
    by_mint: dict[str, dict[str, list[tuple[int, int]]]] = collections.defaultdict(dict)
    truncated = 0
    for row in raw:
        owner = row.get("owner")
        if not owner or owner in pools:
            continue
        if int(row["n_tx"]) > len(row["trades"]):
            truncated += 1
        trades = [(int(x["t"]), int(x["d"])) for x in row["trades"]]
        trades.sort()
        by_mint[row["mint"]][owner] = trades
    tapes: dict[str, MintTape] = {}
    for mint, wallets in by_mint.items():
        flat = sorted((t, w, d) for w, seq in wallets.items() for t, d in seq)
        tapes[mint] = MintTape(
            mint=mint,
            by_wallet=wallets,
            flat=flat,
            times=[t for t, _, _ in flat],
        )
    load_tapes.truncated = truncated  # type: ignore[attr-defined]
    CACHE.mkdir(parents=True, exist_ok=True)
    with COMPACT.open("wb") as fh:
        pickle.dump(tapes, fh, protocol=5)
    return tapes


# ---------------------------------------------------------------------------
# join route 1-3: pump.fun
# ---------------------------------------------------------------------------


def _get_json(client: Any, url: str) -> Any | None:
    try:
        response = client.get(url)
    except Exception:
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except Exception:
        return None


def probe_handles(handles: Sequence[str], *, pause: float = 0.2) -> dict[str, Any]:
    """Route 1 and 2: pump.fun username search, then the profile's own X link."""

    import httpx

    PROFILES.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {}
    with httpx.Client(
        timeout=20, headers={"User-Agent": BROWSER_UA, "Accept": "application/json"}
    ) as client:
        for handle in handles:
            cached = PROFILES / f"handle-{handle}.json"
            if cached.exists():
                out[handle] = json.loads(cached.read_text())
                continue
            hits = _get_json(client, f"{PUMP_API}/users/search?searchTerm={handle}") or []
            exact = [
                h
                for h in hits
                if str(h.get("username", "")).lower() == handle.lower()
            ]
            record: dict[str, Any] = {
                "handle": handle,
                "search_hits": len(hits),
                "exact_username_match": [h.get("address") for h in exact],
                "x_username_confirmed": [],
            }
            for hit in exact:
                profile = _get_json(client, f"{PUMP_API}/users/{hit.get('address')}")
                if profile and profile.get("x_username"):
                    record["x_username_confirmed"].append(
                        {"address": hit.get("address"), "x": profile["x_username"]}
                    )
                time.sleep(pause)
            cached.write_text(json.dumps(record))
            out[handle] = record
            time.sleep(pause)
    return out


def probe_wallet_profiles(
    wallets: Sequence[str], *, pause: float = 0.15
) -> dict[str, dict[str, Any] | None]:
    """Route 2 in reverse: ask each wallet who it says it is on X.

    This is the confirmation arm for the temporal join — the join *proposes* a
    wallet, and pump.fun's own `x_username` would *confirm* it. Its yield is
    reported whether or not it is zero, because a field that is always null is
    a fact about the platform and the next study should not re-derive it.
    """

    import httpx

    PROFILES.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict[str, Any] | None] = {}
    with httpx.Client(
        timeout=20, headers={"User-Agent": BROWSER_UA, "Accept": "application/json"}
    ) as client:
        for wallet in wallets:
            cached = PROFILES / f"w-{wallet}.json"
            if cached.exists():
                blob = json.loads(cached.read_text())
                out[wallet] = None if blob.get("_notfound") else blob
                continue
            profile = _get_json(client, f"{PUMP_API}/users/{wallet}")
            cached.write_text(json.dumps(profile or {"_notfound": True}))
            out[wallet] = profile
            time.sleep(pause)
    return out


_HANDLE_RE = re.compile(r"(?:x|twitter)\.com/(?:#!/)?@?([A-Za-z0-9_]{1,15})", re.I)


def coin_twitter_handles(meta: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Route 3: mint -> the X handle the coin itself advertises."""

    out: dict[str, str] = {}
    for mint, coin in meta.items():
        text = coin.get("twitter") or ""
        match = _HANDLE_RE.search(str(text))
        if match and match.group(1).lower() not in {"i", "intent", "search", "home"}:
            out[mint] = match.group(1).lower()
    return out


# ---------------------------------------------------------------------------
# choreography
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WalletLeg:
    """One wallet's relationship to one callout on one mint."""

    wallet: str
    first_buy: int | None
    last_buy_before: int | None
    bought_before: int  # base units accumulated strictly before t_post
    first_sell_after: int | None
    sold_in_flow: int  # base units sold inside [t_post, t_post + FLOW_WINDOW_S]
    sold_total_after: int
    peak_position: int


def wallet_legs(tape: MintTape, t_post: float) -> dict[str, WalletLeg]:
    legs: dict[str, WalletLeg] = {}
    for wallet, seq in tape.by_wallet.items():
        first_buy = None
        last_buy_before = None
        bought_before = 0
        first_sell_after = None
        sold_in_flow = 0
        sold_total_after = 0
        position = 0
        peak = 0
        for t, delta in seq:
            position += delta
            peak = max(peak, position)
            if delta > 0:
                if first_buy is None:
                    first_buy = t
                if t < t_post:
                    last_buy_before = t
                    bought_before += delta
            else:
                if t >= t_post:
                    if first_sell_after is None:
                        first_sell_after = t
                    sold_total_after += -delta
                    if t <= t_post + FLOW_WINDOW_S:
                        sold_in_flow += -delta
        legs[wallet] = WalletLeg(
            wallet=wallet,
            first_buy=first_buy,
            last_buy_before=last_buy_before,
            bought_before=bought_before,
            first_sell_after=first_sell_after,
            sold_in_flow=sold_in_flow,
            sold_total_after=sold_total_after,
            peak_position=peak,
        )
    return legs


# ---------------------------------------------------------------------------
# join route 4: the temporal join, with the null that decides it
# ---------------------------------------------------------------------------


def caller_mint_calls(
    callouts: Sequence[dict[str, Any]], tapes: dict[str, MintTape]
) -> dict[str, list[tuple[str, float]]]:
    """caller -> [(mint, t_post)], one entry per distinct mint (first call wins).

    A caller who names the same coin five times supplies one opportunity for a
    wallet to coincide, not five: counting the repeats would let one loud
    tweetstorm manufacture a p-value.
    """

    out: dict[str, dict[str, float]] = collections.defaultdict(dict)
    for call in callouts:
        mint = call["mint"]
        if mint not in tapes:
            continue
        author = call["author"] or "<unknown>"
        prior = out[author].get(mint)
        if prior is None or call["t_post"] < prior:
            out[author][mint] = call["t_post"]
    return {a: sorted(m.items(), key=lambda kv: kv[1]) for a, m in out.items()}


def prebuyers(
    tapes: dict[str, MintTape], pairs: Sequence[tuple[str, float]], window: int
) -> dict[str, int]:
    """wallet -> on how many of these (mint, t_post) it bought inside the window."""

    hits: collections.Counter[str] = collections.Counter()
    for mint, t_post in pairs:
        tape = tapes.get(mint)
        if tape is None:
            continue
        for wallet in tape.buyers_between(t_post - window, t_post):
            hits[wallet] += 1
    return dict(hits)


def _time_matched_pool(
    universe: Sequence[tuple[str, float]], *, radius_s: float = 1800.0
) -> dict[tuple[str, float], list[tuple[str, float]]]:
    """For each callout, the other callouts that happened at about the same time.

    A hypergeometric or free-permutation null over callouts is WRONG here and
    was tried first: it treats the cohort's 345 events as exchangeable, so a
    caller whose 51 calls are contiguous in one busy hour gets credited with
    "specificity" for every wallet that was simply awake that hour. It returned
    1,758 FDR-significant wallet-caller pairs, essentially all of them
    AutorunAlert's. Substituting only *contemporaneous* callouts holds the hour
    fixed and leaves identity as the one thing that varies — the same move
    RESULT_copytrading.md's ROT null makes against burstiness.
    """

    ordered = sorted(universe, key=lambda kv: kv[1])
    times = [t for _, t in ordered]
    pool: dict[tuple[str, float], list[tuple[str, float]]] = {}
    for key in universe:
        _, t = key
        i = bisect.bisect_left(times, t - radius_s)
        j = bisect.bisect_right(times, t + radius_s)
        near = [k for k in ordered[i:j] if k[0] != key[0]]
        pool[key] = near or [k for k in ordered if k[0] != key[0]]
    return pool


def temporal_join(
    callouts: Sequence[dict[str, Any]],
    tapes: dict[str, MintTape],
    *,
    window: int = PRE_BUY_WINDOW_S,
    min_mints: int = 2,
    draws: int = 400,
    seed: int = 17,
    radius_s: float = 1800.0,
) -> list[dict[str, Any]]:
    """Per caller: is any wallet pre-buying more of *their* coins than chance?

    The statistic is the largest number of a caller's distinct coins that any
    single wallet bought inside `window` before the call. The null replaces
    each of the caller's coins with a coin called by *somebody else within
    ±30 minutes*, holding fixed: the caller's call count, the hour of day, the
    market-wide burst structure, and every substituted coin's own trade tape.
    What varies is only whose callout it was.

    That is the identity-permutation null of `RESULT_callout_edge.md` §5.3
    pointed at the wallet channel, and it answers the question actually asked —
    not "do wallets buy before callouts" (they do, constantly: a called coin is
    a traded coin, median 294 distinct buyers in the half hour before a call)
    but "do *these* wallets buy before *this* caller's callouts".
    """

    by_caller = caller_mint_calls(callouts, tapes)
    universe = [(m, t) for pairs in by_caller.values() for m, t in pairs]
    pool = _time_matched_pool(universe, radius_s=radius_s)
    rng = random.Random(seed)
    results: list[dict[str, Any]] = []
    for caller, pairs in by_caller.items():
        if len(pairs) < min_mints:
            continue
        observed = prebuyers(tapes, pairs, window)
        best = max(observed.values(), default=0)
        null_best: list[int] = []
        for _ in range(draws):
            sample = [rng.choice(pool[key]) for key in pairs]
            null_best.append(max(prebuyers(tapes, sample, window).values(), default=0))
        ge = sum(1 for b in null_best if b >= best)
        results.append(
            {
                "caller": caller,
                "n_mints": len(pairs),
                "best_overlap": best,
                "n_wallets_at_best": sum(1 for v in observed.values() if v == best),
                "top_wallets": [w for w, v in observed.items() if v == best][:8],
                "null_mean_best": statistics.fmean(null_best) if null_best else 0.0,
                "p_perm": (ge + 1) / (draws + 1),
                "n_candidate_wallets": len(observed),
            }
        )
    results.sort(key=lambda r: (r["p_perm"], -r["best_overlap"]))
    return results


def benjamini_hochberg(pvalues: Sequence[float], alpha: float = 0.10) -> list[bool]:
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    n = len(pvalues)
    keep = [False] * n
    cutoff = -1
    for rank, idx in enumerate(order, start=1):
        if pvalues[idx] <= alpha * rank / n:
            cutoff = rank
    for rank, idx in enumerate(order, start=1):
        if rank <= cutoff:
            keep[idx] = True
    return keep


# ---------------------------------------------------------------------------
# on-chain features, all strictly backward-looking from t_post
# ---------------------------------------------------------------------------

ONCHAIN_COLUMNS = (
    "log_buyers_60s",
    "log_buyers_10m",
    "log_buyers_30m",
    "swarm_ratio",
    "log_buyvol_10m",
    "sell_buy_10m",
    "buyer_hhi_10m",
    "recycled_30m",
    "sniper_share",
    "sniper_share_known",
)

PUMP_BASE_UNITS = 1e15  # 1e9 supply × 1e6 decimals, for scale only


def onchain_features(tape: MintTape, t_post: float) -> dict[str, float]:
    """Flow structure visible on chain at the instant of the call.

    Nothing here needs to know who anybody is — that is the point. If the
    callout channel's content is really "a swarm just bought this", then these
    columns should carry it and the callout columns should stay empty.
    """

    b60 = tape.buyers_between(t_post - 60, t_post)
    b600 = tape.buyers_between(t_post - 600, t_post)
    b1800 = tape.buyers_between(t_post - 1800, t_post)
    buy10 = tape.buy_volume(t_post - 600, t_post)
    sell10 = tape.sell_volume(t_post - 600, t_post)

    per_wallet: collections.Counter[str] = collections.Counter()
    for _, wallet, delta in tape._slice(t_post - 600, t_post):
        if delta > 0:
            per_wallet[wallet] += delta
    total = sum(per_wallet.values())
    hhi = sum((v / total) ** 2 for v in per_wallet.values()) if total else 1.0

    # How much of what was bought in the last half hour is already back out.
    bought = 0
    prior_buyers: set[str] = set()
    for _, wallet, delta in tape._slice(t_post - 1800, t_post - 60):
        if delta > 0:
            bought += delta
            prior_buyers.add(wallet)
    resold = sum(
        -delta
        for _, wallet, delta in tape._slice(t_post - 1800, t_post)
        if delta < 0 and wallet in prior_buyers
    )

    # Snipers: wallets whose first buy landed inside the coin's first minute.
    # Only meaningful when the coin's genesis is inside the pull, otherwise the
    # "first trade" is just where our tape starts and the feature would be a
    # measurement of the pull window rather than of the coin.
    genesis_visible = tape.times[0] > BQ_LO + 600
    sniper_share = 0.0
    if genesis_visible:
        birth = tape.times[0]
        held = 0
        sniper_held = 0
        for seq in tape.by_wallet.values():
            position = 0
            first_buy = None
            for t, delta in seq:
                if t > t_post:
                    break
                if delta > 0 and first_buy is None:
                    first_buy = t
                position += delta
            if position <= 0:
                continue
            held += position
            if first_buy is not None and first_buy - birth <= 60:
                sniper_held += position
        sniper_share = sniper_held / held if held else 0.0

    return {
        "log_buyers_60s": math.log1p(len(b60)),
        "log_buyers_10m": math.log1p(len(b600)),
        "log_buyers_30m": math.log1p(len(b1800)),
        "swarm_ratio": len(b60) / max(len(b1800) / 30.0, 1e-9),
        "log_buyvol_10m": math.log1p(buy10 / PUMP_BASE_UNITS * 1e4),
        "sell_buy_10m": sell10 / buy10 if buy10 else 1.0,
        "buyer_hhi_10m": hhi,
        "recycled_30m": resold / bought if bought else 0.0,
        "sniper_share": sniper_share,
        "sniper_share_known": 1.0 if genesis_visible else 0.0,
    }


def log_loss_bits(labels: Sequence[int], scores: Sequence[float]) -> float:
    """Mean log loss in bits. Differences against the base-rate model are the
    "information gain" the brief asks for, in the unit it asks for."""

    total = 0.0
    for y, p in zip(labels, scores, strict=True):
        p = min(max(p, 1e-6), 1 - 1e-6)
        total += -(math.log2(p) if y else math.log2(1 - p))
    return total / len(labels) if labels else float("nan")


# ---------------------------------------------------------------------------
# reporting helpers
# ---------------------------------------------------------------------------


def quantiles(values: Sequence[float]) -> str:
    if not values:
        return "n=0"
    ordered = sorted(values)

    def q(p: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        i = p * (len(ordered) - 1)
        lo = math.floor(i)
        hi = min(lo + 1, len(ordered) - 1)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (i - lo)

    return (
        f"n={len(ordered)} p10={q(0.10):,.0f} med={q(0.50):,.0f} "
        f"p90={q(0.90):,.0f} mean={statistics.fmean(ordered):,.0f}"
    )


def pct(part: float, whole: float) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "n/a"


def describe(name: str, values: Sequence[float], unit: str = "s") -> None:
    if not values:
        print(f"  {name:<44} none")
        return
    ordered = sorted(values)
    n = len(ordered)
    print(
        f"  {name:<44} n={n:<5} p10={ordered[int(0.1 * n)]:+,.0f}{unit} "
        f"med={statistics.median(ordered):+,.0f}{unit} "
        f"p90={ordered[int(0.9 * (n - 1))]:+,.0f}{unit}"
    )


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------


def report(*, seed: int = 7, draws: int = 400) -> None:
    from studies import callout_edge as ce

    tapes = load_tapes()
    callouts = ce.load_callouts()
    meta = coin_meta()
    rng = random.Random(seed)

    print("=" * 78)
    print("0. THE INSTRUMENT")
    print("=" * 78)
    mints = {c["mint"] for c in callouts}
    print(f"  callouts (mint x tweet)                {len(callouts)}")
    print(f"  distinct mints                         {len(mints)}")
    print(f"  distinct caller handles                {len({c['author'] for c in callouts})}")
    print(f"  mints with pump.fun metadata           {len(meta)}")
    print(f"  mints with an on-chain tape            {len(tapes)}")
    print(
        f"  wallets / trades on those tapes        "
        f"{len({w for t in tapes.values() for w in t.by_wallet}):,} / "
        f"{sum(len(t.flat) for t in tapes.values()):,}"
    )
    genesis = sum(1 for t in tapes.values() if t.times[0] > BQ_LO + 600)
    print(f"  tapes whose coin genesis is inside     {genesis} of {len(tapes)}")

    print()
    print("=" * 78)
    print("1. THE JOIN — X handle to wallet, four routes, every yield reported")
    print("=" * 78)
    handles = sorted({c["author"] for c in callouts if c["author"]})
    probes = probe_handles(handles)
    exact = [h for h, r in probes.items() if r["exact_username_match"]]
    conf = [h for h, r in probes.items() if r["x_username_confirmed"]]
    print(f"  route 1  pump.fun username == X handle       {len(exact)} of {len(handles)}")
    print(f"  route 2  pump.fun profile x_username set     {len(conf)} of {len(handles)}")
    twitter = coin_twitter_handles(meta)
    profile_links = {
        m: h for m, h in twitter.items() if "/status/" not in str(meta[m].get("twitter") or "")
    }
    lowered = {h.lower() for h in handles}
    route3 = {m: h for m, h in profile_links.items() if h in lowered}
    print(
        f"  route 3  coin's own X profile is a caller    {len(route3)} coins "
        f"(of {len(profile_links)} coins linking a profile, {len(twitter)} linking anything)"
    )

    print()
    print("=" * 78)
    print("2. IS THERE ANY CALLOUT-INDUCED FLOW TO EXIT INTO?")
    print("=" * 78)
    events = _first_call_events(callouts, tapes)
    print(f"  events with full +-30 min on-chain coverage  {len(events)}")
    _flow_section(events, tapes, rng)

    print()
    print("=" * 78)
    print("3. THE TEMPORAL JOIN — does any wallet track a specific caller?")
    print("=" * 78)
    for window in (PRE_BUY_WINDOW_S, 300):
        res = temporal_join(callouts, tapes, window=window, draws=draws, seed=seed)
        keep = benjamini_hochberg([r["p_perm"] for r in res], 0.10)
        print(f"  -- pre-buy window {window}s, {len(res)} callers with >=2 on-chain mints")
        print(
            f"  {'caller':<22}{'mints':>6}{'best':>6}{'null':>8}{'p_perm':>9}  FDR10%"
        )
        for row, k in zip(res, keep, strict=True):
            if row["p_perm"] > 0.25 and not k:
                continue
            print(
                f"  {row['caller'][:21]:<22}{row['n_mints']:>6}{row['best_overlap']:>6}"
                f"{row['null_mean_best']:>8.2f}{row['p_perm']:>9.3f}  {'YES' if k else ''}"
            )
        print(f"     FDR-10% significant: {sum(keep)} of {len(res)}")

    print()
    print("=" * 78)
    print("4. THE CHOREOGRAPHY — buy, call, sell, for the one caller that joins")
    print("=" * 78)
    _choreography_section(callouts, tapes)

    print()
    print("=" * 78)
    print("5. THE CALLER-IS-THE-PROJECT ARM — an identified wallet, no inference")
    print("=" * 78)
    _project_arm(ce, callouts, tapes, meta, route3)

    print()
    print("=" * 78)
    print("6. WHAT THE CALLERS ACTUALLY ARE")
    print("=" * 78)
    _taxonomy_section()

    print()
    print("=" * 78)
    print("6.1 THE BAITER CLASS — wallets dressed to look like a track record")
    print("=" * 78)
    _dressed_wallets(callouts, tapes)

    print()
    print("=" * 78)
    print("7. WHAT THE LEAD IS WORTH")
    print("=" * 78)
    _lead_value(ce, callouts, tapes)

    print()
    print("=" * 78)
    print("8. INFORMATION GAIN — flow vs identity vs the free columns")
    print("=" * 78)
    for source in ("boards", "auto"):
        for horizon in ce.HORIZONS_S:
            _discrimination(ce, tapes, callouts, source=source, horizon=horizon, seed=seed)


def _choreography_section(
    callouts: Sequence[dict[str, Any]], tapes: dict[str, MintTape]
) -> None:
    """The buy -> call -> sell timeline for the caller whose wallets are joinable.

    Reported for AutorunAlert because it is the only caller whose wallet
    overlap survives the time-matched null (§3), and reported *with* the
    swarm count, because one wallet at 26 s would read as a private front-run
    and sixty wallets at 26 s does not.
    """

    by_caller = caller_mint_calls(callouts, tapes)
    for caller in ("AutorunAlert",):
        pairs = by_caller.get(caller)
        if not pairs:
            continue
        counts: collections.Counter[str] = collections.Counter()
        traded: collections.Counter[str] = collections.Counter()
        for mint, t_post in pairs:
            tape = tapes[mint]
            for wallet, seq in tape.by_wallet.items():
                buys = [t for t, d in seq if d > 0]
                if not buys:
                    continue
                traded[wallet] += 1
                if 5 <= t_post - buys[0] <= 60:
                    counts[wallet] += 1
        print(f"  {caller}: {len(pairs)} distinct coins on chain")
        print("  wallets whose FIRST buy lands 5-60 s before the tweet, top 8:")
        for wallet, hits in counts.most_common(8):
            print(f"    {hits:>3}/{traded[wallet]:<3}  {wallet}")
        print(f"    wallets with >=10 such coins: {sum(1 for v in counts.values() if v >= 10)}")
        # The size of the burst is what separates "a front-runner" from "a crowd".
        sizes: list[float] = []
        spreads: list[float] = []
        for mint, t_post in pairs:
            stamps = []
            for seq in tapes[mint].by_wallet.values():
                buys = [t for t, d in seq if d > 0]
                if buys and 5 <= t_post - buys[0] <= 60:
                    stamps.append(buys[0])
            if len(stamps) >= 5:
                sizes.append(len(stamps))
                spreads.append(max(stamps) - min(stamps))
        if sizes:
            print(
                f"    the burst itself: {len(sizes)} of {len(pairs)} coins carry one; "
                f"median {statistics.median(sizes):,.0f} distinct wallets "
                f"(p90 {sorted(sizes)[int(0.9 * (len(sizes) - 1))]:,.0f}) "
                f"over a median {statistics.median(spreads):.0f} s"
            )
        top = counts.most_common(1)[0][0] if counts else None
        if top is None:
            continue
        own: list[float] = []
        other: list[float] = []
        first_sell: list[float] = []
        closed = 0
        seen: set[tuple[str, str]] = set()
        for call in sorted(callouts, key=lambda r: r["t_post"]):
            key = (call["author"] or "", call["mint"])
            if key in seen or call["mint"] not in tapes:
                continue
            seen.add(key)
            seq = tapes[call["mint"]].by_wallet.get(top)
            if not seq:
                continue
            buys = [t for t, d in seq if d > 0]
            if not buys:
                continue
            lag = call["t_post"] - buys[0]
            if call["author"] == caller:
                own.append(lag)
                sells = [t for t, d in seq if d < 0]
                if sells:
                    first_sell.append(sells[0] - call["t_post"])
                position = 0
                for t, d in seq:
                    position += d
                    if position <= 0 and t <= call["t_post"]:
                        closed += 1
                        break
            else:
                other.append(lag)
        print(f"  the leading wallet {top}")
        describe(f"lag (tweet - its first buy) on {caller}'s coins", own)
        describe("same wallet, every other caller's coins", other)
        describe("its first sell, relative to the tweet", first_sell)
        print(f"    position already closed when the tweet lands: {closed} of {len(own)}")


def _project_arm(
    ce: Any,
    callouts: Sequence[dict[str, Any]],
    tapes: dict[str, MintTape],
    meta: dict[str, dict[str, Any]],
    route3: dict[str, str],
) -> None:
    by_call: dict[tuple[str, str], list[float]] = collections.defaultdict(list)
    for call in callouts:
        by_call[(call["mint"], (call["author"] or "").lower())].append(call["t_post"])
    at_genesis = later = 0
    later_lags: list[float] = []
    sell_lags: list[float] = []
    traded = 0
    for mint, handle in route3.items():
        tape = tapes.get(mint)
        creator = meta[mint].get("creator")
        stamps = sorted(by_call[(mint, handle)])
        if tape is None or not creator or not stamps:
            continue
        seq = tape.by_wallet.get(creator)
        if not seq:
            continue
        traded += 1
        buys = [t for t, d in seq if d > 0]
        sells = [t for t, d in seq if d < 0]
        if sells:
            sell_lags.append(sells[0] - stamps[0])
        if not buys:
            continue
        if buys[0] - tape.times[0] <= 5:
            at_genesis += 1
        else:
            later += 1
            later_lags.append(stamps[0] - buys[0])
    print(f"  coins where the caller IS the coin's advertised X profile: {len(route3)}")
    print(f"  of those, creator wallet visible on chain: {traded}")
    print(f"    first buy is the create-transaction dev buy: {at_genesis}")
    print(f"    bought later, a discretionary add:           {later}")
    describe("tweet minus that discretionary buy", later_lags)
    describe("creator's first sell, relative to the tweet", sell_lags)
    rows = ce.build_rows(callouts, tape_end=TAPE_END, source="boards")
    arm = [r["r3600"] for r in rows if r["mint"] in route3]
    rest = [r["r3600"] for r in rows if r["mint"] not in route3]
    for tag, values in (("caller is the project", arm), ("every other callout", rest)):
        if values:
            print(
                f"    1 h return, {tag:<22} n={len(values):<4} "
                f"median {100 * statistics.median(values):+.2f}% "
                f"mean {100 * statistics.fmean(values):+.2f}%"
            )


def _dressed_wallets(
    callouts: Sequence[dict[str, Any]], tapes: dict[str, MintTape], *, min_trades: int = 20
) -> None:
    """PROGRAM.md §4 records that wallets are deliberately dressed to look
    profitable so that copiers follow them. The measurable signature of
    dressing is *machine-uniform sizing*: dozens of buys of near-identical size
    on one coin, which no discretionary trader produces.

    This measures prevalence, not intent. A market maker and a wash-trader make
    the same shape, and nothing here separates them — the number is reported as
    "how much of the pre-callout crowd is machinery", which is what it can
    honestly support.
    """

    pre_wallets: set[str] = set()
    seen: set[tuple[str, str]] = set()
    for call in sorted(callouts, key=lambda r: r["t_post"]):
        key = (call["author"] or "", call["mint"])
        if key in seen or call["mint"] not in tapes:
            continue
        seen.add(key)
        tape = tapes[call["mint"]]
        pre_wallets |= tape.buyers_between(call["t_post"] - PRE_BUY_WINDOW_S, call["t_post"])

    uniform = 0
    examined = 0
    for tape in tapes.values():
        for wallet, seq in tape.by_wallet.items():
            if wallet not in pre_wallets:
                continue
            buys = [d for _, d in seq if d > 0]
            if len(buys) < min_trades:
                continue
            examined += 1
            mean = statistics.fmean(buys)
            if mean > 0 and statistics.pstdev(buys) / mean < 0.25:
                uniform += 1
    print(
        f"  wallets that pre-bought at least one callout: {len(pre_wallets):,}\n"
        f"  of those, (wallet, mint) legs with >={min_trades} buys on one coin: {examined:,}\n"
        f"  of THOSE, machine-uniform sizing (CV < 0.25): {uniform:,} "
        f"({pct(uniform, examined)})"
    )
    print(
        "  Read as prevalence of machinery in the pre-callout crowd, not as proven bait: a"
        " market maker and a wash-trader leave the same trace, and this cannot separate them."
    )


_BOILER_STRIP = re.compile(r"https?://\S+|[1-9A-HJ-NP-Za-km-z]{32,44}|[\d.,%$]+")
_REFERRAL = re.compile(r"axiom|gmgn|mevx|bullx|photon|trojan|bloom|t\.me/", re.I)


def _taxonomy_section(path: str | None = None) -> None:
    """How much of the "callout" feed is a person, and how much is a machine.

    Boilerplate share = the fraction of an average tweet's words that appear in
    at least 80% of that account's tweets, after stripping URLs, addresses and
    numbers. A human writing about a coin scores near zero; a template with the
    ticker slotted in scores near one.
    """

    pattern = path or str(REPO / "state" / "callouts" / "backfill-*.jsonl")
    tweets: list[dict[str, Any]] = []
    for file in sorted(glob.glob(pattern)):
        with open(file) as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("mints"):
                    tweets.append(row)
    by_author: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in tweets:
        by_author[row["author_username"]].append(row)

    def words(text: str) -> list[str]:
        return re.findall(r"[A-Za-z]{2,}", _BOILER_STRIP.sub(" ", text or "").lower())

    automated: list[tuple[str, int, float, float]] = []
    varied: list[tuple[str, int, float, float]] = []
    single: list[tuple[str, int, float, float]] = []
    for author, rows in by_author.items():
        tokenised = [words(r["text"]) for r in rows]
        doc_freq: collections.Counter[str] = collections.Counter()
        for toks in tokenised:
            doc_freq.update(set(toks))
        boiler = (
            {w for w, c in doc_freq.items() if c >= 0.8 * len(rows)} if len(rows) >= 2 else set()
        )
        share = statistics.fmean(
            [(sum(1 for w in t if w in boiler) / len(t)) if t else 0.0 for t in tokenised]
        )
        referral = sum(1 for r in rows if _REFERRAL.search(r["text"] or "")) / len(rows)
        entry = (author, len(rows), share, referral)
        if len(rows) == 1:
            single.append(entry)
        elif share >= 0.6 or referral >= 0.8:
            automated.append(entry)
        else:
            varied.append(entry)
    total = len(tweets)
    for tag, group in (
        ("automated relay / alert bot", automated),
        ("2+ calls, not template-detected", varied),
        ("a single call, unclassifiable from text", single),
    ):
        calls = sum(n for _, n, _, _ in group)
        print(
            f"  {tag:<40} accounts {len(group):>4}  callouts {calls:>4} "
            f"({pct(calls, total)})"
        )
    print("  the repeat callers, ranked by callout count:")

    for author, n, share, referral in sorted(
        automated + varied, key=lambda e: -e[1]
    )[:12]:
        tag = "AUTOMATED" if (share >= 0.6 or referral >= 0.8) else ""
        print(
            f"    {author[:22]:<23} calls {n:>3}  boilerplate {share:.2f}  "
            f"referral links {referral:.2f}  {tag}"
        )


def _lead_value(
    ce: Any, callouts: Sequence[dict[str, Any]], tapes: dict[str, MintTape]
) -> None:
    """How much of the move is already gone by the time the callout lands."""

    def series(mint: str) -> Any:
        found = ce.load_prices(mint)
        return found if found is not None else ce.load_board_series({mint}).get(mint)

    buckets: dict[str, list[float]] = collections.defaultdict(list)
    for call in callouts:
        points = series(call["mint"])
        if not points:
            continue
        t0 = call["t_post"]
        now = ce.mark_at(points, t0)
        if now is None or now.price <= 0:
            continue
        for lag in (60, 300, 900, 1800):
            past = ce.mark_at(points, t0 - lag)
            if past and past.price > 0:
                buckets[f"last {lag}s before the call"].append(now.price / past.price - 1.0)
        ahead = ce.mark_at(points, t0 + 3600)
        if ahead:
            buckets["forward 1 h from the call"].append(ahead.price / now.price - 1.0)
    for name, values in buckets.items():
        print(
            f"  {name:<32} n={len(values):<5} median {100 * statistics.median(values):+.2f}% "
            f"mean {100 * statistics.fmean(values):+.2f}%"
        )

    by_caller = caller_mint_calls(callouts, tapes)
    pairs = by_caller.get("AutorunAlert") or []
    counts: collections.Counter[str] = collections.Counter()
    for mint, t_post in pairs:
        for wallet, seq in tapes[mint].by_wallet.items():
            buys = [t for t, d in seq if d > 0]
            if buys and 5 <= t_post - buys[0] <= 60:
                counts[wallet] += 1
    if not counts:
        return
    top = counts.most_common(1)[0][0]
    same = differ = 0
    moves: list[float] = []
    for mint, t_post in pairs:
        seq = tapes[mint].by_wallet.get(top)
        points = series(mint)
        if not seq or not points:
            continue
        buys = [t for t, d in seq if d > 0]
        if not buys:
            continue
        at_buy = ce.mark_at(points, buys[0])
        at_call = ce.mark_at(points, t_post)
        if not at_buy or not at_call or at_buy.price <= 0:
            continue
        if at_buy.t_price == at_call.t_price:
            same += 1
        else:
            differ += 1
        moves.append(at_call.price / at_buy.price - 1.0)
    if moves:
        print(
            f"  the ~26 s lead, priced on the same tape: n={len(moves)}, "
            f"buy and callout land on the SAME price bar in {same} of {same + differ}; "
            f"median {100 * statistics.median(moves):+.3f}% mean {100 * statistics.fmean(moves):+.3f}%"
        )


def _first_call_events(
    callouts: Sequence[dict[str, Any]], tapes: dict[str, MintTape]
) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for call in sorted(callouts, key=lambda r: r["t_post"]):
        key = (call["author"] or "", call["mint"])
        if key in seen or call["mint"] not in tapes:
            continue
        seen.add(key)
        if call["t_post"] - 1800 < BQ_LO or call["t_post"] + 1800 > BQ_HI:
            continue
        out.append(call)
    return out


def _flow_section(
    events: Sequence[dict[str, Any]], tapes: dict[str, MintTape], rng: random.Random
) -> None:
    W = 1800

    def ratios(tape: MintTape, t0: float) -> tuple[float, float]:
        pre_v = tape.buy_volume(t0 - W, t0)
        post_v = tape.buy_volume(t0, t0 + W)
        pre_n = len(tape.buyers_between(t0 - W, t0))
        post_n = len(tape.buyers_between(t0, t0 + W))
        return (
            math.log((post_v + 1) / (pre_v + 1)),
            math.log((post_n + 1) / (pre_n + 1)),
        )

    def recycled(tape: MintTape, t0: float) -> float | None:
        pre = tape.buyers_between(t0 - W, t0)
        total = sold = 0
        for _, wallet, delta in tape._slice(t0, t0 + W):
            if delta < 0:
                total += -delta
                if wallet in pre:
                    sold += -delta
        return sold / total if total else None

    obs_v: list[float] = []
    obs_n: list[float] = []
    obs_r: list[float] = []
    matched_v: list[float] = []
    matched_n: list[float] = []
    age_r: list[float] = []
    both_r: list[float] = []
    naive_r: list[float] = []
    ages: list[float] = []
    crowds: list[float] = []
    have_crowd = have_age = have_both = 0
    mint_names = list(tapes)
    for call in events:
        tape = tapes[call["mint"]]
        t0 = call["t_post"]
        v, n = ratios(tape, t0)
        obs_v.append(v)
        obs_n.append(n)
        rec = recycled(tape, t0)
        if rec is not None:
            obs_r.append(rec)
        age = t0 - tape.times[0]
        crowd = len(tape.buyers_between(t0 - W, t0))
        # same coin, comparable recent crowd
        lo = max(tape.times[0] + W, BQ_LO + W)
        hi = min(tape.times[-1] - W, BQ_HI - W)
        got = 0
        for _ in range(120):
            if hi <= lo or got >= 4:
                break
            t = rng.uniform(lo, hi)
            if abs(t - t0) < W:
                continue
            if not (crowd * 0.75 <= len(tape.buyers_between(t - W, t)) <= crowd * 1.25 + 1):
                continue
            vv, nn = ratios(tape, t)
            matched_v.append(vv)
            matched_n.append(nn)
            got += 1
        # other coins at the same age (and optionally the same crowd)
        got_a = got_b = 0
        for _ in range(400):
            if got_a >= 4 and got_b >= 4:
                break
            other = tapes[rng.choice(mint_names)]
            if other.mint == call["mint"]:
                continue
            t = other.times[0] + age * rng.uniform(0.8, 1.25)
            if t - W < max(BQ_LO, other.times[0]) or t + W > BQ_HI:
                continue
            rr = recycled(other, t)
            if rr is None:
                continue
            if got_a < 4:
                age_r.append(rr)
                got_a += 1
            if got_b < 4 and 0.6 * crowd <= len(other.buyers_between(t - W, t)) <= 1.6 * crowd + 2:
                both_r.append(rr)
                got_b += 1
        # The NAIVE null, kept only to show the size of the trap: same coin,
        # any instant, no matching at all.
        drawn = 0
        for _ in range(60):
            if hi <= lo or drawn >= 4:
                break
            t = rng.uniform(lo, hi)
            if abs(t - t0) < W:
                continue
            rr = recycled(tape, t)
            if rr is not None:
                naive_r.append(rr)
                drawn += 1
        have_crowd += got > 0
        have_age += got_a > 0
        have_both += got_b > 0
        ages.append((t0 - tape.times[0]) / 60.0)
        crowds.append(crowd)

    def line(tag: str, values: Sequence[float]) -> None:
        print(
            f"    {tag:<42} n={len(values):<5} median {statistics.median(values):+.3f} "
            f"mean {statistics.fmean(values):+.3f}"
        )

    print(
        f"  callouts that HAVE a control: same-coin crowd-matched {have_crowd}, "
        f"age-matched {have_age}, age+crowd {have_both}, of {len(events)}. The ones without "
        "are the coin's own unique peak, so the comparison is conservative."
    )
    print("  log(buy volume after / before), 30 min each side")
    line("observed, at the callout", obs_v)
    line("same coin, crowd-matched instant", matched_v)
    print("  log(distinct buyers after / before)")
    line("observed, at the callout", obs_n)
    line("same coin, crowd-matched instant", matched_n)
    print(
        f"  the coin at the moment of the call: age median {statistics.median(ages):.1f} min "
        f"(p10 {sorted(ages)[int(0.1 * len(ages))]:.1f}); distinct buyers in the previous "
        f"30 min median {statistics.median(crowds):,.0f}"
    )
    print("  share of the next 30 min of SELLING done by the previous 30 min's buyers")
    line("observed, at the callout", obs_r)
    line("same coin, any instant (the NAIVE null)", naive_r)
    line("other coins, age-matched", age_r)
    line("other coins, age AND crowd matched", both_r)
    try:
        from scipy.stats import mannwhitneyu

        for name, null in (("age", age_r), ("age+crowd", both_r)):
            if null:
                _, p = mannwhitneyu(obs_r, null, alternative="two-sided")
                print(f"    Mann-Whitney vs {name}-matched: p = {p:.4g}")
    except Exception:
        pass


def _discrimination(
    ce: Any,
    tapes: dict[str, MintTape],
    callouts: Sequence[dict[str, Any]],
    *,
    source: str,
    horizon: int,
    seed: int,
) -> None:
    rows = ce.build_rows(callouts, tape_end=TAPE_END, source=source)
    keep: list[dict[str, Any]] = []
    for row in rows:
        tape = tapes.get(row["mint"])
        if tape is None or row["t_post"] - 1800 < BQ_LO or row["t_post"] > BQ_HI:
            continue
        row.update(onchain_features(tape, row["t_post"]))
        row["y"] = 1 if row[f"r{horizon}"] > 0 else 0
        keep.append(row)
    eligible = [r for r in keep if not r[f"admin{horizon}"]]
    train, test, cut = ce.temporal_entity_split(eligible)
    if len(test) < 10 or len({r["y"] for r in test}) < 2:
        print(f"  source={source} h={horizon}s: test set too small ({len(test)} rows)")
        return

    # Caller -> wallet link fitted on the TRAIN period only.
    linked: dict[str, set[str]] = {}
    for entry in temporal_join(
        [c for c in callouts if c["t_post"] < cut], tapes, draws=300, seed=seed
    ):
        if entry["p_perm"] <= 0.05:
            linked[entry["caller"]] = set(entry["top_wallets"])
    for row in train + test:
        wallets = linked.get(row["author"]) or set()
        pre = (
            tapes[row["mint"]].buyers_between(
                row["t_post"] - PRE_BUY_WINDOW_S, row["t_post"]
            )
            if wallets
            else set()
        )
        row["linked_wallet_prebuy"] = 1.0 if (wallets & pre) else 0.0
        row["linked_caller"] = 1.0 if wallets else 0.0

    base = statistics.fmean([r["y"] for r in train])
    floor = log_loss_bits([r["y"] for r in test], [base] * len(test))
    print(
        f"  -- source={source} h={horizon}s: {len(keep)} rows / "
        f"{len({r['mint'] for r in keep})} mints; eligible {len(eligible)}; "
        f"train {len(train)}/{len({r['mint'] for r in train})} "
        f"test {len(test)}/{len({r['mint'] for r in test})}; "
        f"test base rate {statistics.fmean([r['y'] for r in test]):.3f}; "
        f"base-rate log loss {floor:.3f} bits"
    )
    print(f"     train-period caller->wallet links: {[(k, len(v)) for k, v in linked.items()]}")
    sets = {
        "free": ce.FREE_COLUMNS,
        "callout": ce.CALLOUT_COLUMNS,
        "onchain flow": ONCHAIN_COLUMNS,
        "free+callout": (*ce.FREE_COLUMNS, *ce.CALLOUT_COLUMNS),
        "free+flow": (*ce.FREE_COLUMNS, *ONCHAIN_COLUMNS),
        "free+flow+linked wallet": (
            *ce.FREE_COLUMNS,
            *ONCHAIN_COLUMNS,
            "linked_wallet_prebuy",
            "linked_caller",
        ),
        "free+callout+flow": (*ce.FREE_COLUMNS, *ce.CALLOUT_COLUMNS, *ONCHAIN_COLUMNS),
    }
    for name, columns in sets.items():
        usable = ce.usable_columns(train, columns)
        if not usable:
            continue
        labels, scores = ce.fit_score(train, test, usable, "y")
        auc, auprc = ce.auc_auprc(labels, scores)
        lo, hi = ce.cluster_bootstrap_auc(
            labels, scores, [r["mint"] for r in test], draws=600
        )
        print(
            f"     {name:<24} AUC {auc:.3f} [{lo:.3f}, {hi:.3f}]  AUPRC {auprc:.3f}  "
            f"{floor - log_loss_bits(labels, scores):+.4f} bits"
        )
    singles: list[tuple[float, str]] = []
    for column in ONCHAIN_COLUMNS:
        labels, scores = ce.fit_score(train, test, [column], "y")
        auc, _ = ce.auc_auprc(labels, scores)
        if auc == auc:
            singles.append((auc, column))
    print(
        "     best single flow column:  "
        + ", ".join(f"{c} {a:.3f}" for a, c in sorted(singles, reverse=True)[:3])
    )


BQ_TX = "`bigquery-public-data.crypto_solana_mainnet_us.Transactions`"


def pull_sql(
    mints: Sequence[str],
    *,
    lo: str = "2026-08-14 00:00:00",
    hi: str = "2026-08-15 03:00:00",
) -> str:
    """Per-(mint, wallet) token deltas over the callout window.

    Cost is set by which columns are touched, not by how many mints are listed:
    `pre_token_balances` and `post_token_balances` are ~114 GB/day each and the
    filter lives inside them, so the mint list is free. The 500-trade
    `ARRAY_AGG` cap keeps the streamed payload manageable; `n_tx` carries the
    true count so truncation is visible rather than silent.
    """

    listing = ",".join(f"'{m}'" for m in mints)
    return f"""
WITH src AS (
  SELECT block_timestamp, signature, index AS tx_index,
         ARRAY(SELECT AS STRUCT owner, mint, CAST(amount AS STRING) AS amount, account_index
               FROM UNNEST(pre_token_balances) WHERE mint IN ({listing})) AS pre,
         ARRAY(SELECT AS STRUCT owner, mint, CAST(amount AS STRING) AS amount, account_index
               FROM UNNEST(post_token_balances) WHERE mint IN ({listing})) AS post
  FROM {BQ_TX}
  WHERE block_timestamp >= TIMESTAMP('{lo}')
    AND block_timestamp <  TIMESTAMP('{hi}')
    AND EXISTS(SELECT 1 FROM UNNEST(post_token_balances) b WHERE b.mint IN ({listing}))
),
po AS (
  SELECT signature, UNIX_SECONDS(block_timestamp) AS t, tx_index,
         b.mint AS mint, b.owner AS owner, b.account_index AS ai,
         CAST(b.amount AS BIGNUMERIC) AS amt
  FROM src, UNNEST(post) b
),
pr AS (
  SELECT signature, b.account_index AS ai, CAST(b.amount AS BIGNUMERIC) AS amt
  FROM src, UNNEST(pre) b
),
d AS (
  SELECT po.t, po.signature, po.tx_index, po.mint, po.owner,
         SUM(po.amt - IFNULL(pr.amt, 0)) AS delta
  FROM po LEFT JOIN pr ON po.signature = pr.signature AND po.ai = pr.ai
  GROUP BY 1,2,3,4,5
  HAVING SUM(po.amt - IFNULL(pr.amt, 0)) != 0
)
SELECT mint, owner, COUNT(*) AS n_tx,
       CAST(SUM(delta) AS STRING) AS net,
       ARRAY_AGG(STRUCT(t, tx_index AS ix, CAST(delta AS STRING) AS d)
                 ORDER BY t, tx_index LIMIT 500) AS trades
FROM d
GROUP BY mint, owner
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--rebuild-tapes", action="store_true")
    parser.add_argument("--emit-sql", action="store_true")
    parser.add_argument("--draws", type=int, default=400)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    if args.emit_sql:
        from studies.callout_edge import load_callouts

        print(pull_sql(sorted({c["mint"] for c in load_callouts()})))
        return
    if args.rebuild_tapes:
        load_tapes(rebuild=True)
    if args.report:
        report(seed=args.seed, draws=args.draws)


__all__ = [
    "MintTape",
    "WalletLeg",
    "benjamini_hochberg",
    "caller_mint_calls",
    "coin_meta",
    "coin_twitter_handles",
    "load_tapes",
    "onchain_features",
    "probe_handles",
    "probe_wallet_profiles",
    "report",
    "temporal_join",
    "wallet_legs",
]


if __name__ == "__main__":
    main()
