"""Who has ever called the operator's own four coins — a census, not a sample.

The operator asked a plain question: *investigate anyone who ever called nosis,
dregg, weave, or solve*. Those four are the operator's own launches, and DREGG is
the income source, so the question behind the question is whether the promotion
those coins receive is organic or purchased.

This module is the instrument. Three things about its shape are deliberate.

**It is a census over query patterns, not over the internet.** The pinned Apify
actor honours X's ``since_time:`` / ``until_time:`` operators (established in
`RESULT_callout_edge.md` §2), so each coin's whole life is walkable. What is
walked, though, is four query shapes — the contract address as text, the cashtag,
and the two launchpad URL forms — and `RESULT_caller_wallets.md` §6 is blunt
about what such queries are: queries for *links posted by tooling*. A human who
wrote "dregg is going to run" and nothing else is invisible here by construction.
"First caller" therefore means first *in this census*, never first on the
internet.

**A cashtag hit is not a callout.** ``$SOLVE`` matches an unrelated older token
and ordinary English; ``$weave`` and ``$nosis`` likewise. Every row records which
query shape matched it and whether the tweet carries the actual mint, so the
CA-confirmed subset is analysable apart from the cashtag-only subset. The
contamination rate is measured, not assumed.

**Truncation is never silent.** The actor returns at most ~100 items per query.
A slice that comes back at the cap is *truncated*, and its sample is biased
toward the newest tweets inside it. Rather than record that and move on, the
walker bisects a capped slice until it fits or hits a floor, and any slice still
capped at the floor is reported as such.

Clocks: ``t_post`` is the tweet's own ``created_at``; ``t_collect`` is ours. They
are never mixed and every statistic keys on ``t_post``.

Cost: the actor bills $0.00025 per returned tweet. Gross tweets purchased and
unique tweets kept are both reported, because bisection re-buys rows it already
has and the difference is real money.

Usage::

    uv run --group research python -m studies.cluster_callers pilot
    uv run --group research python -m studies.cluster_callers census
    uv run --group research python -m studies.cluster_callers profile
    uv run --group research python -m studies.cluster_callers report
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import random
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import httpx

from shitcoims_intelligence.adapters.x_apify import (
    HARD_MAX_ITEMS,
    XApifyAdapter,
    XApifyConfig,
    XTweet,
)

OUT_DIR = Path(__file__).resolve().parent.parent / "state" / "callouts"
CENSUS_PATH = OUT_DIR / "cluster_census.jsonl"
PILOT_PATH = OUT_DIR / "cluster_pilot.jsonl"
PROFILE_PATH = OUT_DIR / "cluster_profiles.jsonl"

#: Apify's pay-per-result price, 2026-08.
USD_PER_TWEET = 0.00025

#: The actor's ceiling. A batch at or above this is truncated, not complete.
CAP = HARD_MAX_ITEMS

#: Tweets per day past which an account is not a person. Deliberately far above
#: any human power-user; see `Account.classify` for why boilerplate alone misses
#: these and §3f for the distribution the threshold sits in.
HIGH_POST_RATE = 200.0

#: Jaccard at which two tweets by different accounts are called the same template.
#: Reported alongside the full pairwise distribution so it reads as a choice.
TEMPLATE_THRESHOLD = 0.6


@dataclass(frozen=True, slots=True)
class Coin:
    ticker: str
    name: str
    mint: str
    created_unix: int


#: Resolved and verified 2026-08-15. `created_unix` is the pump.fun creation time.
COINS: tuple[Coin, ...] = (
    Coin("nosis", "9gnosis", "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump", 1786260938),
    Coin("weave", "universal weave", "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump", 1785795942),
    Coin("SOLVE", "OpenSolve", "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump", 1784577587),
    Coin("DREGG", "Dregg", "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump", 1782565198),
)
BY_TICKER = {c.ticker.lower(): c for c in COINS}
BY_MINT = {c.mint.lower(): c for c in COINS}

#: The operator and the operator's own project account. `DreggNet` writes in
#: ember's first person ("my (@ember_arlynx) writing is historically poorly
#: received"), so it is the project speaking, not a third party promoting it.
#: These are not *callers* in the sense the question asks about, and folding them
#: into the roster would answer "who promotes your coins" with "you do".
PROJECT_HANDLES = {"ember_arlynx", "dreggnet"}


def query_shapes(coin: Coin) -> dict[str, str]:
    """The four tasked query shapes, keyed by the name recorded on every row.

    ``ca`` is the canonical callout form — the address pasted as text. The two
    ``url_*`` shapes are what tooling posts. ``cashtag`` is the loosest and the
    only one that can match a coin that is not ours; it is kept precisely so the
    contamination it carries can be measured rather than assumed away.
    """

    return {
        "ca": coin.mint,
        "cashtag": f"${coin.ticker}",
        "url_pump": f"url:pump.fun/{coin.mint}",
        "url_dex": f"url:dexscreener.com/solana/{coin.mint}",
    }


# ---------------------------------------------------------------------------
# collection
# ---------------------------------------------------------------------------


def _row(
    tweet: XTweet,
    *,
    coin: Coin,
    shape: str,
    query: str,
    slice_start: int,
    slice_end: int,
    capped: bool,
    t_collect: str,
) -> dict:
    d = asdict(tweet)
    d.pop("provenance", None)
    created = d.pop("created_at", None)
    mints_lower = {m.lower() for m in tweet.all_mints}
    tags_upper = {t.upper() for t in tweet.cashtags}
    return {
        "t_post": created.isoformat() if created is not None else None,
        "t_post_unix": int(created.timestamp()) if created is not None else None,
        "t_collect": t_collect,
        "coin": coin.ticker,
        "coin_mint": coin.mint,
        "shape": shape,
        "query": query,
        "slice_start_unix": slice_start,
        "slice_end_unix": slice_end,
        "slice_capped": capped,
        # The join that decides everything downstream. URL-derived mints come
        # back case-mangled from some sources (a lowercased address is in the
        # existing census), so the match is case-insensitive and the exact-case
        # flag travels alongside rather than being thrown away.
        "mint_hit": coin.mint.lower() in mints_lower,
        "mint_hit_exact_case": coin.mint in tweet.all_mints,
        "cashtag_hit": coin.ticker.upper() in tags_upper,
        "other_cluster_mints": sorted(
            {BY_MINT[m].ticker for m in mints_lower if m in BY_MINT and m != coin.mint.lower()}
        ),
        **d,
        "mints": list(tweet.all_mints),
    }


async def _search(
    adapter: XApifyAdapter, query: str, *, attempts: int = 3, max_items: int = CAP
) -> tuple[tuple[XTweet, ...], int]:
    """Return (tweets, gross_returned). Retries transport failure, never silently."""

    last: Exception | None = None
    for i in range(attempts):
        try:
            batch = await adapter.search(query, max_items=max_items)
            return batch.results, len(batch.results)
        except Exception as exc:  # a dead slice must not kill the run
            last = exc
            await asyncio.sleep(2 * (i + 1))
    raise RuntimeError(f"query failed after {attempts} attempts: {query}") from last


class Ledger:
    """Counts money and truncation. Both are things a run must never hide."""

    def __init__(self, budget_tweets: int) -> None:
        self.gross = 0
        self.unique = 0
        self.queries = 0
        self.failed = 0
        self.capped_at_floor = 0
        self.bisections = 0
        self.budget = budget_tweets
        self.seen: set[str] = set()

    def over_budget(self) -> bool:
        return self.gross >= self.budget

    def usd(self) -> float:
        return self.gross * USD_PER_TWEET

    def summary(self) -> dict:
        return {
            "queries": self.queries,
            "gross_tweets_purchased": self.gross,
            "unique_tweets_kept": self.unique,
            "failed_queries": self.failed,
            "bisections": self.bisections,
            "slices_capped_at_floor": self.capped_at_floor,
            "usd": round(self.usd(), 4),
        }


async def walk(
    adapter: XApifyAdapter,
    *,
    coin: Coin,
    shape: str,
    base: str,
    lo: int,
    hi: int,
    floor_seconds: int,
    ledger: Ledger,
    sink: Any,
    manifest: Any = None,
    depth: int = 0,
) -> None:
    """Collect [lo, hi) for one query shape, bisecting whenever the actor caps.

    A capped batch is a *truncated* one: the actor returned as much as it was
    willing to and the remainder is invisible. Bisecting until the halves fit is
    the only way to turn that into a census; where a slice is still capped at the
    floor the truncation is recorded and reported instead of being swallowed.
    """

    if lo >= hi or ledger.over_budget():
        return
    query = f"{base} since_time:{lo} until_time:{hi}"
    ledger.queries += 1
    try:
        tweets, gross = await _search(adapter, query)
    except RuntimeError as exc:
        ledger.failed += 1
        print(f"  ! {exc}", flush=True)
        return
    ledger.gross += gross
    capped = gross >= CAP
    span = hi - lo
    if capped and span > floor_seconds:
        ledger.bisections += 1
        mid = lo + span // 2
        await walk(
            adapter, coin=coin, shape=shape, base=base, lo=lo, hi=mid,
            floor_seconds=floor_seconds, ledger=ledger, sink=sink,
            manifest=manifest, depth=depth + 1,
        )
        await walk(
            adapter, coin=coin, shape=shape, base=base, lo=mid, hi=hi,
            floor_seconds=floor_seconds, ledger=ledger, sink=sink,
            manifest=manifest, depth=depth + 1,
        )
        return
    if capped:
        ledger.capped_at_floor += 1
    t_collect = datetime.now(UTC).isoformat()
    # The manifest of ASKED windows is separate data from the rows returned,
    # and it has to be, because a known-zero control's whole output is an empty
    # result. Without this, "we asked and got nothing" is indistinguishable from
    # "we never asked" — and §0 would quietly report the second as the first.
    if manifest is not None:
        manifest.write(
            json.dumps(
                {"coin": coin.ticker, "shape": shape, "lo": lo, "hi": hi,
                 "n": gross, "capped": capped, "t_collect": t_collect},
                separators=(",", ":"),
            )
            + "\n"
        )
        manifest.flush()
    fresh = 0
    for tweet in tweets:
        key = f"{coin.ticker}:{tweet.tweet_id}"
        if key in ledger.seen:
            continue
        ledger.seen.add(key)
        fresh += 1
        ledger.unique += 1
        sink.write(
            json.dumps(
                _row(
                    tweet, coin=coin, shape=shape, query=query,
                    slice_start=lo, slice_end=hi, capped=capped, t_collect=t_collect,
                ),
                separators=(",", ":"),
            )
            + "\n"
        )
    sink.flush()
    print(
        f"  {coin.ticker:<5} {shape:<8} {datetime.fromtimestamp(lo, UTC):%m-%d %H:%M}"
        f"+{span // 3600:>3}h got={gross:<4} new={fresh:<4} capped={capped}",
        flush=True,
    )


async def run_collection(
    *,
    coins: Sequence[Coin],
    shapes: dict[str, dict[str, str]],
    windows: dict[str, tuple[int, int]],
    slice_seconds: int,
    floor_seconds: int,
    budget_tweets: int,
    out: Path,
) -> dict:
    """`shapes` maps coin ticker -> {shape name: query base}."""

    cfg = XApifyConfig(enabled=True, token_file=Path("~/.apify-token"), max_items_per_query=CAP)
    out.parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(budget_tweets)
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5)) as http:
        adapter = XApifyAdapter(cfg, http)
        mpath = out.with_suffix(out.suffix + ".slices.jsonl")
        with out.open("a") as fh, mpath.open("a") as mf:
            for coin in coins:
                lo0, hi0 = windows[coin.ticker]
                for shape, base in shapes[coin.ticker].items():
                    lo = lo0
                    while lo < hi0 and not ledger.over_budget():
                        hi = min(lo + slice_seconds, hi0)
                        await walk(
                            adapter, coin=coin, shape=shape, base=base, lo=lo, hi=hi,
                            floor_seconds=floor_seconds, ledger=ledger, sink=fh,
                            manifest=mf,
                        )
                        lo = hi
    if ledger.over_budget():
        print("!! BUDGET EXHAUSTED — collection is incomplete and must be reported as such")
    return {**ledger.summary(), "out": str(out)}


async def run_profiles(handles: Sequence[str], *, per_handle: int, out: Path) -> dict:
    """Buy a recent-tweet sample per handle, for the boilerplate classifier.

    `RESULT_caller_wallets.md` §6 defines boilerplate share over an account's
    tweets. Classifying an account from the one tweet that named a cluster coin
    is not possible — that study's own "single call, unclassifiable" bucket was
    25.9% of its feed. A `from:` sample fixes that for a few tenths of a cent per
    account, and is bought only for accounts the census actually surfaced.
    """

    cfg = XApifyConfig(enabled=True, token_file=Path("~/.apify-token"), max_items_per_query=CAP)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Resumable: a handle already sampled is never re-bought. The census finishes
    # per coin at different times, so this gets run more than once.
    # Resume must see EVERY shard's output, not just this one's, or eight parallel
    # shards re-buy each other's work.
    done = {
        r["handle"].lower()
        for r in load_rows(str(out.parent / "cluster_profiles*.jsonl"))
    }
    pending = [h for h in handles if h.lower() not in done]
    print(f"  {len(done)} handles already sampled, {len(pending)} to buy")
    ledger = Ledger(10_000_000)
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5)) as http:
        adapter = XApifyAdapter(cfg, http)
        with out.open("a") as fh:
            for handle in pending:
                ledger.queries += 1
                try:
                    # 25 is plenty for a boilerplate share and a quarter of the
                    # cost of the actor's ceiling, over ~300 handles.
                    tweets, gross = await _search(
                        adapter, f"from:{handle}", max_items=per_handle
                    )
                except RuntimeError as exc:
                    ledger.failed += 1
                    print(f"  ! {exc}", flush=True)
                    continue
                ledger.gross += gross
                kept = 0
                for tweet in tweets[:per_handle]:
                    d = asdict(tweet)
                    d.pop("provenance", None)
                    created = d.pop("created_at", None)
                    fh.write(
                        json.dumps(
                            {
                                "handle": handle,
                                "t_post": created.isoformat() if created else None,
                                "t_post_unix": int(created.timestamp()) if created else None,
                                **d,
                            },
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                    kept += 1
                    ledger.unique += 1
                fh.flush()
                print(f"  from:{handle:<20} got={gross:<4} kept={kept}", flush=True)
    return {**ledger.summary(), "out": str(out)}


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://\S+")
_B58_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{25,44}")
_NUM_RE = re.compile(r"[\d][\d,.%$+\-eE]*")
_WORD_RE = re.compile(r"[A-Za-z']+")

#: Hosts and phrasings that mark a referral relay. `RESULT_caller_wallets.md` §6
#: used expanded URLs; this adapter does not retain them (X shortens to t.co), so
#: this fires on what survives in the visible text and is a FLOOR, not a rate.
_REFERRAL_HINTS = (
    "axiom.trade", "bullx", "photon-sol", "gmgn.ai", "trojan", "maestro",
    "?ref=", "&ref=", "/ref/", "referral", "bloom",
)


def _normalise(text: str) -> list[str]:
    """Strip URLs, addresses and numbers, then lowercase-word-split.

    Exactly `RESULT_caller_wallets.md` §6's normalisation: what is left is the
    account's *prose*, so a template with a ticker slotted in scores near one and
    a person writing about a coin scores near zero.
    """

    t = _URL_RE.sub(" ", text)
    t = _B58_RE.sub(" ", t)
    t = _NUM_RE.sub(" ", t)
    return [w.lower() for w in _WORD_RE.findall(t)]


def boilerplate_share(texts: Sequence[str], *, threshold: float = 0.8) -> float:
    """Fraction of an average tweet's words appearing in >=80% of the account's tweets."""

    docs = [_normalise(t) for t in texts]
    docs = [d for d in docs if d]
    if len(docs) < 2:
        return float("nan")
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    common = {w for w, c in df.items() if c >= threshold * len(docs)}
    shares = [sum(1 for w in d if w in common) / len(d) for d in docs]
    return statistics.fmean(shares)


def referral_share(texts: Sequence[str]) -> float:
    if not texts:
        return float("nan")
    hits = sum(1 for t in texts if any(h in t.lower() for h in _REFERRAL_HINTS))
    return hits / len(texts)


def shared_template_groups(
    rows: Sequence[dict],
    *,
    coin: Coin | None,
    threshold: float,
    min_words: int = 5,
    stop: set[str] | None = None,
) -> tuple[list[dict], list[float]]:
    """Find one template posted by MANY accounts — purchased promotion's signature.

    Within-account boilerplate (§6 of `RESULT_caller_wallets.md`) catches a bot
    repeating itself. It cannot catch the other shape, which is the one that
    matters to a coin's owner: twenty *different* accounts posting one copywriter's
    text within an hour. That is a campaign, and it looks like organic breadth in
    every account-level statistic.

    Similarity is Jaccard over normalised word sets with the coin's own ticker and
    name removed — otherwise every tweet about a coin shares the coin's name and
    the measure reports the subject rather than the source. The full pairwise
    distribution is returned alongside the groups so the threshold is visible as a
    choice rather than hidden as a constant.
    """

    if stop is None:
        assert coin is not None
        stop = {w.lower() for w in (coin.ticker, *coin.name.split())}
    docs: list[tuple[int, frozenset[str]]] = []
    for i, r in enumerate(rows):
        words = {w for w in _normalise(r.get("text") or "") if w not in stop}
        if len(words) >= min_words:
            docs.append((i, frozenset(words)))

    sims: list[float] = []
    parent = list(range(len(docs)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in range(len(docs)):
        for b in range(a + 1, len(docs)):
            wa, wb = docs[a][1], docs[b][1]
            j = len(wa & wb) / len(wa | wb)
            if rows[docs[a][0]]["author_username"] != rows[docs[b][0]]["author_username"]:
                sims.append(j)
            if j >= threshold:
                parent[find(a)] = find(b)

    comps: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(docs)):
        comps[find(idx)].append(docs[idx][0])

    wordset = {i: w for i, w in docs}
    groups = []
    for members in comps.values():
        handles = {rows[i]["author_username"] for i in members}
        if len(handles) < 2:
            continue
        times = sorted(rows[i]["t_post_unix"] for i in members)
        # Single-linkage chains: A~B and B~C puts A and C in one group even when
        # A and C share nothing. Reporting the group's WEAKEST internal pair makes
        # a chained group look like what it is instead of like a campaign.
        pair_j = [
            len(wordset[x] & wordset[y]) / len(wordset[x] | wordset[y])
            for ix, x in enumerate(members) for y in members[ix + 1:]
        ]
        groups.append({
            "coin": coin.ticker if coin else "|".join(
                sorted({rows[i]["coin"] for i in members})
            ),
            "coins": sorted({rows[i]["coin"] for i in members}),
            "n_tweets": len(members),
            "accounts": sorted(handles),
            "span_s": times[-1] - times[0],
            "first": times[0],
            "cohesion_min": min(pair_j) if pair_j else 1.0,
            "cohesion_mean": statistics.fmean(pair_j) if pair_j else 1.0,
            "sample": (rows[members[0]].get("text") or "")[:150].replace("\n", " "),
        })
    groups.sort(key=lambda g: (-len(g["accounts"]), -g["n_tweets"]))
    return groups, sims


@dataclass
class Account:
    handle: str
    followers: int | None
    verified: bool
    tweets: list[dict]          # census rows authored by this handle
    sample: list[dict]          # `from:` profile sample, may be empty

    @property
    def texts(self) -> list[str]:
        seen: dict[str, str] = {}
        for r in self.tweets + self.sample:
            seen[r["tweet_id"]] = r.get("text") or ""
        return [t for t in seen.values() if t]

    @property
    def post_rate(self) -> float:
        """Tweets per day over the `from:` sample's own span.

        Account age is not obtainable through this adapter — the actor's author
        object is not carried past the parser — so the age question the brief
        asks cannot be answered directly. Posting *rate* is the available
        substitute and is the more diagnostic of the two anyway: 25 tweets in two
        hours is a machine whatever the account's birthday says.
        """

        ts = sorted(r["t_post_unix"] for r in self.sample if r.get("t_post_unix"))
        if len(ts) < 3:
            return float("nan")
        span = ts[-1] - ts[0]
        return float("inf") if span <= 0 else len(ts) * 86400 / span

    def classify(self) -> tuple[str, dict]:
        """Four classes, with the evidence that produced each one attached.

        Thresholds are `RESULT_caller_wallets.md` §6's, unchanged, so the numbers
        here are comparable to that study's 51.4%: boilerplate >= 0.6 or referral
        share >= 0.8 is a machine. What is new is the middle: an account with a
        `from:` sample and low boilerplate is positively evidenced as human-ish
        rather than merely unclassified.
        """

        texts = self.texts
        bp = boilerplate_share(texts)
        ref = referral_share(texts)
        n = len(texts)
        ev = {"n_texts": n, "boilerplate": None if bp != bp else round(bp, 3),
              "referral_share": None if ref != ref else round(ref, 3)}
        rate = self.post_rate
        ev["posts_per_day"] = None if rate != rate else round(rate, 1)
        if n < 3:
            return "unclassifiable", ev
        if ref >= 0.8:
            return "referral_bot", ev
        if bp == bp and bp >= 0.6:
            return "automated_relay", ev
        # Boilerplate is a WITHIN-account measure and it has a blind spot this
        # cohort walks straight into: a farm that posts a different copywriter's
        # template on each coin repeats nothing, so it scores near zero. Measured
        # here — 23 of the 33 accounts caught posting a shared template across two
        # or more of the four coins are boilerplate-"human". Posting rate is what
        # separates them, and it is not close: those accounts run at 250-1,200
        # tweets/day. A person does not. The threshold is high on purpose, well
        # past any human power-user, and the rate distribution is printed beside
        # it so it reads as a choice rather than a constant.
        if rate == rate and rate >= HIGH_POST_RATE:
            return "high_rate_bot", ev
        if bp == bp and bp >= 0.35:
            return "templated_shill", ev
        return "human", ev


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------


def load_rows(spec: str | Path) -> list[dict]:
    """Load one path, a comma-separated list, or a glob. The census runs per coin."""

    rows: list[dict] = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        # `Path().glob` refuses absolute patterns; `glob.glob` takes either.
        paths = (
            [Path(p) for p in sorted(glob.glob(part))]
            if any(c in part for c in "*?[")
            else [Path(part)]
        )
        for path in paths:
            if not path.exists():
                continue
            with path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
    return rows


def dedupe(rows: Iterable[dict]) -> list[dict]:
    """One row per (coin, tweet). Query shapes overlap; the union is the census.

    Which shapes matched is preserved as a set, because "the cashtag found it but
    the CA query did not" is exactly the distinction §2 of the brief demands.
    """

    by_key: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["coin"], r["tweet_id"])
        cur = by_key.get(key)
        if cur is None:
            r = dict(r)
            r["shapes"] = [r["shape"]]
            by_key[key] = r
        else:
            if r["shape"] not in cur["shapes"]:
                cur["shapes"].append(r["shape"])
            cur["mint_hit"] = cur["mint_hit"] or r["mint_hit"]
            cur["cashtag_hit"] = cur["cashtag_hit"] or r["cashtag_hit"]
            # `mints` decides contamination downstream, so the union survives the
            # merge rather than whichever copy happened to be read first.
            cur["mints"] = list(dict.fromkeys([*cur.get("mints", []), *r.get("mints", [])]))
    return list(by_key.values())


def _fmt_ts(unix: int | None) -> str:
    if unix is None:
        return "?"
    return datetime.fromtimestamp(unix, UTC).strftime("%Y-%m-%d %H:%M")


def burst_statistic(times: Sequence[int], accounts: Sequence[str], *, window: int) -> float:
    """Mean number of DISTINCT OTHER accounts calling within +/-`window` seconds.

    Distinct-other is the point. A single relay firing five times in a minute is
    not a burst of promoters, and counting raw neighbours would score it as one.
    """

    if len(times) < 2:
        return 0.0
    order = sorted(range(len(times)), key=lambda i: times[i])
    ts = [times[i] for i in order]
    acc = [accounts[i] for i in order]
    total = 0.0
    for i, t in enumerate(ts):
        near = set()
        j = i - 1
        while j >= 0 and t - ts[j] <= window:
            if acc[j] != acc[i]:
                near.add(acc[j])
            j -= 1
        j = i + 1
        while j < len(ts) and ts[j] - t <= window:
            if acc[j] != acc[i]:
                near.add(acc[j])
            j += 1
        total += len(near)
    return total / len(ts)


def _draw_envelope(rng: random.Random, ages: Sequence[int], n: int, bandwidth: int) -> list[int]:
    """n draws from the coin's own call-age distribution, smoothed by `bandwidth`.

    This is the structure-preserving null's engine. Resampling an observed age
    and jittering it by a kernel far wider than the burst scale keeps the coarse
    envelope — the launch-decay ramp, the quiet nights, the campaign days — and
    destroys only the fine-scale alignment the burst hypothesis is about.
    """

    out = []
    for _ in range(n):
        base = rng.choice(ages)
        out.append(int(base + rng.gauss(0, bandwidth)))
    return out


def burst_null(
    rows: Sequence[dict],
    *,
    coin: Coin,
    window: int,
    bandwidth: int,
    draws: int,
    seed: int,
) -> dict:
    """Observed fine-scale clustering against two nulls at a matched statistic.

    Null 1 (naive) draws every call time uniformly over the coin's observed span.
    It is reported only to show the size of the trap: a coin gets most of its
    calls in its first hours purely because it is new, so a uniform null will
    manufacture "clustering" out of the launch ramp alone. This repo has been
    burned by exactly that three times (`RESULT_flow_signals`, `RESULT_copytrading`
    73x -> 0.98x, `RESULT_caller_wallets` §2.1).

    Null 2 (envelope) preserves each account's own call count and the coin's
    coarse temporal profile, and is the one that decides. Time-of-day survives to
    within the bandwidth by construction, since draws are jittered observed times
    rather than fresh uniform ones.
    """

    times = [r["t_post_unix"] for r in rows if r.get("t_post_unix")]
    accounts = [r["author_username"] for r in rows if r.get("t_post_unix")]
    if len(times) < 4:
        return {"coin": coin.ticker, "n": len(times), "verdict": "too few calls to test"}
    observed = burst_statistic(times, accounts, window=window)
    lo, hi = min(times), max(times)
    ages = [t - coin.created_unix for t in times]
    per_account = Counter(accounts)
    rng = random.Random(seed)

    naive = []
    for _ in range(draws):
        sim = [rng.randint(lo, hi) for _ in times]
        naive.append(burst_statistic(sim, accounts, window=window))

    env = []
    for _ in range(draws):
        sim_t: list[int] = []
        sim_a: list[str] = []
        for handle, k in per_account.items():
            for age in _draw_envelope(rng, ages, k, bandwidth):
                sim_t.append(coin.created_unix + age)
                sim_a.append(handle)
        env.append(burst_statistic(sim_t, sim_a, window=window))

    def _p(sims: list[float]) -> float:
        # +1 smoothing: with `draws` samples the smallest reportable p is 1/(draws+1).
        return (sum(1 for s in sims if s >= observed) + 1) / (draws + 1)

    return {
        "coin": coin.ticker,
        "n": len(times),
        "n_accounts": len(per_account),
        "window_s": window,
        "bandwidth_s": bandwidth,
        "draws": draws,
        "observed": round(observed, 4),
        "naive_mean": round(statistics.fmean(naive), 4),
        "naive_p": round(_p(naive), 4),
        "envelope_mean": round(statistics.fmean(env), 4),
        "envelope_p": round(_p(env), 4),
    }


#: Address-bearing query shapes. A match on one of these is itself evidence: the
#: query string CONTAINS the 44-character mint, and X returned the tweet for it.
#: A 44-char base58 address has no plausible false-positive mode, and the
#: pre-creation control (§0) is what turns that from an argument into a
#: measurement — ask the same query over the window before the coin existed and
#: a working join returns nothing.
ADDRESS_SHAPES = ("ca", "url_pump", "url_dex")


#: Tickers that are NOT unique to the operator's cluster, with the rival mint the
#: pre-creation control turned up. `$DREGG` was in use from at least 2026-05-10 by
#: `Bv7yfJJvYGssW7UYwMqBNxHkX8psurDzsaw6Vu1Dpump` — a duck meme coin whose dev
#: (@KalebOnChain) says so in as many words. Any `$DREGG` tweet is therefore
#: ambiguous unless it carries an address, and this is the concrete reason the
#: cashtag channel is reported apart from the mint-bearing one rather than merged.
KNOWN_RIVAL_MINTS: dict[str, str] = {
    "Bv7yfJJvYGssW7UYwMqBNxHkX8psurDzsaw6Vu1Dpump": "DREGG (the 2026-05 duck coin, not ours)",
}


def contamination_kind(row: dict, coin: Coin) -> str:
    """For a row with no mint of ours: is it provably about a different coin?

    A cashtag row carrying somebody *else's* contract address is contamination
    that needs no judgement call — the tweet names its subject and the subject is
    not this coin. A cashtag row carrying no address at all cannot be resolved
    from text, and saying so is more useful than guessing.
    """

    others = [m for m in row.get("mints", []) if m.lower() != coin.mint.lower()]
    if not others:
        return "ambiguous_no_address"
    for m in others:
        if m in KNOWN_RIVAL_MINTS:
            return "rival_named"
    # A tweet can name several coins. One that uses OUR ticker and also links a
    # different contract is a multi-coin post that does mention us, not a tweet
    # about somebody else that happened to collide on the ticker.
    return "multicoin_post" if row.get("cashtag_hit") else "other_mint_only"


def evidence_tier(row: dict, coin: Coin) -> str:
    """How strongly this row is tied to this coin. Four tiers, weakest last.

    The tiers exist because the extractor is not the join. Three real rows from
    this census make the point: an all-caps `SOLANA:8PECVCC…PUMP` decodes to
    nothing under base58 so nothing is extracted, and a vote-farm tweet whose
    only link is a t.co shortener carries the mint solely in the expanded URL
    that X indexed and the adapter never saw. Both are calls. Demanding that the
    extractor re-find the address would silently discard them, which is exactly
    the class of exclusion this repo has been burned by.
    """

    if row["mint_hit"]:
        return "extracted"
    text = (row.get("text") or "").lower()
    if coin.mint.lower() in text:
        return "text_ci"
    if any(s in row["shapes"] for s in ADDRESS_SHAPES):
        return "index"
    return "cashtag_only"


def _q(values: Sequence[int], p: float) -> str:
    v = values[min(len(values) - 1, int(p * len(values)))]
    return f"{v / 3600:.1f}h" if abs(v) < 172800 else f"{v / 86400:.1f}d"


def report(
    *,
    census: str,
    profiles: str,
    slices_spec: str,
    window: int,
    bandwidth: int,
    draws: int,
    seed: int,
) -> None:
    raw = load_rows(census)
    rows = dedupe(raw)
    slices = load_rows(slices_spec)
    sample_rows = load_rows(profiles)
    samples: dict[str, list[dict]] = defaultdict(list)
    for r in sample_rows:
        samples[r["handle"].lower()].append(r)

    print("=" * 78)
    print("CLUSTER CALLER CENSUS")
    print("=" * 78)
    print(f"raw rows purchased+kept : {len(raw)}")
    print(f"unique (coin, tweet)    : {len(rows)}")
    capped = [r for r in raw if r.get("slice_capped")]
    print(f"rows from capped slices : {len(capped)}  <- truncated, biased to newest in slice")

    # ---- 0. both controls, per PROGRAM.md §3.12 ----------------------------
    # A green zero-control alone certifies a broken instrument as readily as a
    # working one, so the pre-creation mirror window carries BOTH halves at once.
    # For `ca` / `url_*` it is a known-ZERO world: the address did not exist, so
    # any hit is a false positive of the join. For `cashtag` it is the channel's
    # BACKGROUND rate — every `$SOLVE` tweet predating OpenSolve is, definitionally,
    # about something else, which turns "expect contamination" into a measurement.
    print()
    print("-- 0. controls: the pre-creation mirror window ----------------------------")
    # "We asked and got zero" is a control. "We never asked" is not, and the two
    # must never print the same. The test is whether any SLICE reached back past
    # creation, not whether any row did — a working known-zero control returns no
    # rows by construction, so row counts cannot tell them apart.
    asked_pre = {
        (m["coin"], m["shape"])
        for m in slices
        if m["lo"] < BY_TICKER[m["coin"].lower()].created_unix
    }
    if not asked_pre:
        print("  NOT RUN — no pre-creation window was collected. The known-zero control")
        print("  and the cashtag background rate are both UNMEASURED for this census.")
        print("  Run: `census --pre-window --shapes ca,cashtag`")
    else:
        print(f"{'coin':<7}{'shape':<10}{'pre':>7}{'post':>7}{'pre/post':>10}"
              f"{'pre hrs':>9}  interpretation")
        for coin in COINS:
            cr = [r for r in rows if r["coin"] == coin.ticker]
            for shape in ("ca", "cashtag", "url_pump", "url_dex"):
                if (coin.ticker, shape) not in asked_pre:
                    continue
                sr = [r for r in cr if shape in r["shapes"]]
                pre = [r for r in sr if (r.get("t_post_unix") or 0) < coin.created_unix]
                post = [r for r in sr if (r.get("t_post_unix") or 0) >= coin.created_unix]
                pre_h = sum(
                    m["hi"] - m["lo"] for m in slices
                    if m["coin"] == coin.ticker and m["shape"] == shape
                    and m["lo"] < coin.created_unix
                ) / 3600
                ratio = f"{len(pre) / len(post):.2f}" if post else "-"
                if shape == "cashtag":
                    note = "background rate of this cashtag"
                elif pre:
                    note = "FALSE POSITIVE — the address did not exist yet"
                else:
                    note = "known-zero control PASSES"
                print(f"{coin.ticker:<7}{shape:<10}{len(pre):>7}{len(post):>7}{ratio:>10}"
                      f"{pre_h:>9.0f}  {note}")

    # ---- 1. per-coin census, split by what actually matched ----------------
    excluded: Counter[str] = Counter()
    per_coin: dict[str, list[dict]] = {}
    for coin in COINS:
        cr = [r for r in rows if r["coin"] == coin.ticker]
        # A tweet posted before the coin existed cannot be a call of it. Rows are
        # itemised, never dropped in silence.
        pre = [r for r in cr if (r.get("t_post_unix") or 0) < coin.created_unix]
        excluded[f"{coin.ticker}: posted before coin creation"] += len(pre)
        cr = [r for r in cr if (r.get("t_post_unix") or 0) >= coin.created_unix]
        notime = [r for r in cr if not r.get("t_post_unix")]
        excluded[f"{coin.ticker}: no parseable t_post"] += len(notime)
        cr = [r for r in cr if r.get("t_post_unix")]
        for r in cr:
            r["tier"] = evidence_tier(r, coin)
        per_coin[coin.ticker] = cr

    print()
    print("-- 1. how each row is tied to its coin ------------------------------------")
    print("  extracted    the adapter parsed this coin's mint out of the tweet")
    print("  text_ci      the mint is in the visible text but not base58-decodable")
    print("               (an ALL-CAPS paste), so the extractor could not see it")
    print("  index        no visible mint, but an address-BEARING query returned it:")
    print("               X indexed the address in an expanded URL or card")
    print("  cashtag_only only the $TICKER query matched, and no mint appears anywhere")
    print()
    print(f"{'coin':<7}{'rows':>7}{'extract':>9}{'text_ci':>9}{'index':>7}{'tag_only':>10}"
          f"{'accts':>7}{'first call':>18}")
    for coin in COINS:
        cr = per_coin[coin.ticker]
        t = Counter(r["tier"] for r in cr)
        confirmed = [r for r in cr if r["tier"] != "cashtag_only"]
        first = min((r["t_post_unix"] for r in confirmed), default=None)
        print(f"{coin.ticker:<7}{len(cr):>7}{t['extracted']:>9}{t['text_ci']:>9}"
              f"{t['index']:>7}{t['cashtag_only']:>10}"
              f"{len({r['author_username'].lower() for r in cr}):>7}{_fmt_ts(first):>18}")
    allr = [r for v in per_coin.values() for r in v]
    ta = Counter(r["tier"] for r in allr)
    print(f"{'TOTAL':<7}{len(allr):>7}{ta['extracted']:>9}{ta['text_ci']:>9}"
          f"{ta['index']:>7}{ta['cashtag_only']:>10}")
    if allr:
        print(f"\ncashtag-only share: {100 * ta['cashtag_only'] / len(allr):.1f}% of in-window "
              f"rows carry no mint by any route")

    # What the cashtag-only rows actually are. A row naming somebody else's
    # contract is contamination that needs no judgement; a row naming no contract
    # at all cannot be resolved from text, and the honest report says which is which.
    print()
    print("-- 1c. what the cashtag-only rows are ------------------------------------")
    print(f"{'coin':<7}{'tag_only':>9}{'rival':>7}{'multicoin':>11}{'other only':>12}"
          f"{'ambiguous':>11}")
    for coin in COINS:
        tagonly = [r for r in per_coin[coin.ticker] if r["tier"] == "cashtag_only"]
        k = Counter(contamination_kind(r, coin) for r in tagonly)
        print(f"{coin.ticker:<7}{len(tagonly):>9}{k['rival_named']:>7}{k['multicoin_post']:>11}"
              f"{k['other_mint_only']:>12}{k['ambiguous_no_address']:>11}")
    print("  rival      carries a contract known to share this ticker (KNOWN_RIVAL_MINTS)")
    print("  multicoin  uses our ticker AND links some other coin — a multi-coin post")
    print("  other only links a contract that is not ours and does not use our ticker")
    print("  ambiguous  names no contract at all; text alone cannot resolve it")

    # per-shape yield, the thing that decides what a rerun should buy
    print()
    print("-- 1b. yield by query shape (unique rows; a row can match >1 shape) -------")
    print(f"{'shape':<10}{'rows':>7}{'mint-bearing':>14}{'precision':>11}{'accounts':>10}")
    for shape in ("ca", "cashtag", "url_pump", "url_dex"):
        sr = [r for r in allr if shape in r["shapes"]]
        ca = [r for r in sr if r["tier"] != "cashtag_only"]
        prec = f"{100 * len(ca) / len(sr):.1f}%" if sr else "-"
        accts = {r["author_username"].lower() for r in sr}
        print(f"{shape:<10}{len(sr):>7}{len(ca):>14}{prec:>11}{len(accts):>10}")

    print()
    print("-- exclusions (itemised, never silent) ------------------------------------")
    for reason, n in sorted(excluded.items()):
        if n:
            print(f"  {n:>5}  {reason}")
    if not any(excluded.values()):
        print("  none")

    # ---- 2. the roster ------------------------------------------------------
    all_rows = [r for v in per_coin.values() for r in v]
    accounts: dict[str, Account] = {}
    for r in all_rows:
        h = r["author_username"].lower()
        a = accounts.get(h)
        if a is None:
            a = accounts[h] = Account(
                handle=r["author_username"],
                followers=r.get("author_followers"),
                verified=bool(r.get("author_verified")),
                tweets=[],
                sample=samples.get(h, []),
            )
        a.tweets.append(r)
        if (r.get("author_followers") or 0) > (a.followers or 0):
            a.followers = r.get("author_followers")

    print()
    print("-- 2. the roster ----------------------------------------------------------")
    print(f"distinct accounts, any match   : {len(accounts)}")
    ca_accounts = {r["author_username"].lower() for r in all_rows if r["tier"] != "cashtag_only"}
    print(f"distinct accounts, CA-confirmed: {len(ca_accounts)}")
    third = {h for h in accounts if h not in PROJECT_HANDLES}
    print(f"third parties (excl. the operator's own accounts): {len(third)}")
    print(f"  operator/project accounts found: "
          f"{', '.join('@' + accounts[h].handle for h in accounts if h in PROJECT_HANDLES) or '-'}")

    rows_out = []
    for a in accounts.values():
        coins_any = sorted({r["coin"] for r in a.tweets})
        coins_ca = sorted({r["coin"] for r in a.tweets if r["tier"] != "cashtag_only"})
        cls, ev = a.classify()
        if a.handle.lower() in PROJECT_HANDLES:
            cls = "project_self"
        first_by_coin = {}
        for r in a.tweets:
            c = r["coin"]
            if c not in first_by_coin or r["t_post_unix"] < first_by_coin[c]:
                first_by_coin[c] = r["t_post_unix"]
        lags = {
            c: first_by_coin[c] - BY_TICKER[c.lower()].created_unix for c in first_by_coin
        }
        rate = a.post_rate
        rows_out.append({
            "handle": a.handle, "followers": a.followers, "verified": a.verified,
            "n_calls": len(a.tweets), "coins_any": coins_any, "coins_ca": coins_ca,
            "class": cls, **ev, "lag_s": lags,
            "posts_per_day": None if rate != rate else round(rate, 1),
        })
    rows_out.sort(key=lambda r: (-len(r["coins_ca"]), -len(r["coins_any"]), -r["n_calls"]))

    print()
    print("-- 2b. classification (RESULT_caller_wallets §6 thresholds) ---------------")
    cls_counter = Counter(r["class"] for r in rows_out)
    call_counter: Counter[str] = Counter()
    for r in rows_out:
        call_counter[r["class"]] += r["n_calls"]
    print(f"{'class':<18}{'accounts':>10}{'calls':>8}{'share of feed':>15}")
    for cls, n in cls_counter.most_common():
        share = f"{100 * call_counter[cls] / max(1, len(all_rows)):.1f}%"
        print(f"{cls:<18}{n:>10}{call_counter[cls]:>8}{share:>15}")
    fired = sum(1 for r in rows_out if (r["referral_share"] or 0) > 0)
    print(f"\n  NOTE: the referral-link arm fired on {fired} of {len(rows_out)} accounts.")
    print("  X rewrites every outbound link to t.co and this adapter keeps only the")
    print("  visible text, so the expanded host RESULT_caller_wallets §6 classified on")
    print("  is not available here. Read a low referral share as UNMEASURED, not as")
    print("  absent; boilerplate carries the classification in this study.")
    unc = sum(1 for r in rows_out if r["class"] == "unclassifiable")
    print(f"  {unc} accounts have fewer than 3 tweets of text and cannot be classified;")
    print("  `profile` buys a from: sample to shrink that bucket.")

    # ---- 3. cross-coin overlap, the headline --------------------------------
    print()
    print("-- 3. cross-coin overlap --------------------------------------------------")
    for label, key in (("any match", "coins_any"), ("CA-confirmed only", "coins_ca")):
        dist = Counter(len(r[key]) for r in rows_out if r[key])
        print(f"  {label}: " + ", ".join(f"{k} coin(s): {dist[k]}" for k in sorted(dist)))
    multi = [r for r in rows_out if len(r["coins_any"]) >= 2]
    print(f"\n  multi-coin callers ({len(multi)}), named:")
    if multi:
        print(f"    {'handle':<20}{'flw':>8}{'calls':>7}  {'class':<17}{'coins (CA-conf)'}")
        for r in multi:
            ca = ",".join(r["coins_ca"]) or "-"
            print(f"    @{r['handle']:<19}{r['followers'] or 0:>8}{r['n_calls']:>7}  "
                  f"{r['class']:<17}{','.join(r['coins_any'])}  (mint-bearing: {ca})")
            # A promoter paid per launch shows up fast EVERY time; a genuine
            # follower does not have to. The per-coin lag is where that shows.
            lags = ", ".join(
                f"{c}+{v / 3600:.1f}h" if abs(v) < 172800 else f"{c}+{v / 86400:.1f}d"
                for c, v in sorted(r["lag_s"].items(), key=lambda kv: kv[1])
            )
            print(f"      lag after each launch: {lags}")
    else:
        print("    none")

    # a pairwise overlap matrix says more than a distribution when n is small
    print("\n  pairwise: accounts calling BOTH (any match / CA-confirmed)")
    tickers = [c.ticker for c in COINS]
    for i, a in enumerate(tickers):
        for b in tickers[i + 1:]:
            aa = {r["handle"] for r in rows_out if a in r["coins_any"]}
            bb = {r["handle"] for r in rows_out if b in r["coins_any"]}
            ca_a = {r["handle"] for r in rows_out if a in r["coins_ca"]}
            ca_b = {r["handle"] for r in rows_out if b in r["coins_ca"]}
            print(f"    {a:<6} & {b:<6} {len(aa & bb):>4} / {len(ca_a & ca_b):>4}")

    print()
    print("-- 3b. full roster, ordered by cross-coin reach ---------------------------")
    print(f"{'handle':<20}{'flw':>8}{'calls':>6}{'bp':>6}{'post/d':>8}  {'class':<17}"
          f"{'coins':<18}{'first lag'}")
    for r in rows_out:
        bp = "-" if r["boilerplate"] is None else f"{r['boilerplate']:.2f}"
        ppd = "-" if r["posts_per_day"] is None else f"{r['posts_per_day']:.0f}"
        lag = min(r["lag_s"].values()) if r["lag_s"] else None
        lagtxt = "-" if lag is None else (
            f"+{lag / 3600:.1f}h" if abs(lag) < 172800 else f"+{lag / 86400:.1f}d"
        )
        print(f"@{r['handle']:<19}{r['followers'] or 0:>8}{r['n_calls']:>6}{bp:>6}{ppd:>8}  "
              f"{r['class']:<17}{','.join(r['coins_any']):<18}{lagtxt}")

    print()
    print("-- 3f. the posting-rate distribution the threshold sits in ---------------")
    rr = sorted(r["posts_per_day"] for r in rows_out if r["posts_per_day"] is not None)
    if rr:
        print(f"  n={len(rr)} accounts with a from: sample.  "
              f"p50 {rr[len(rr) // 2]:.0f}  p75 {rr[int(0.75 * len(rr))]:.0f}  "
              f"p90 {rr[int(0.90 * len(rr))]:.0f}  p99 {rr[int(0.99 * len(rr))]:.0f}  "
              f"max {rr[-1]:.0f} tweets/day")
        print(f"  at or above HIGH_POST_RATE={HIGH_POST_RATE:.0f}: "
              f"{sum(1 for x in rr if x >= HIGH_POST_RATE)} accounts "
              f"({100 * sum(1 for x in rr if x >= HIGH_POST_RATE) / len(rr):.0f}%)")

    print()
    print("-- 3e. followers and posting rate by class -------------------------------")
    print("(account AGE is not obtainable through this adapter; posting rate stands in)")
    print(f"{'class':<18}{'n':>5}{'median flw':>12}{'p90 flw':>10}{'median post/d':>15}")
    for cls in cls_counter:
        grp = [r for r in rows_out if r["class"] == cls]
        flw = sorted(r["followers"] or 0 for r in grp)
        rates = sorted(r["posts_per_day"] for r in grp if r["posts_per_day"] is not None)
        med_r = f"{rates[len(rates) // 2]:.0f}" if rates else "-"
        print(f"{cls:<18}{len(grp):>5}{flw[len(flw) // 2]:>12}"
              f"{flw[int(0.9 * (len(flw) - 1))]:>10}{med_r:>15}")

    # ---- 3c. one template, many mouths --------------------------------------
    print()
    print("-- 3c. shared templates across DIFFERENT accounts -------------------------")
    print(f"Jaccard over normalised words, ticker and coin name removed, "
          f"threshold {TEMPLATE_THRESHOLD}")
    all_sims: list[float] = []
    n_groups = 0
    for coin in COINS:
        cr = [r for r in per_coin[coin.ticker] if r["tier"] != "cashtag_only"]
        groups, sims = shared_template_groups(cr, coin=coin, threshold=TEMPLATE_THRESHOLD)
        all_sims.extend(sims)
        for g in groups:
            n_groups += 1
            print(f"  {g['coin']:<6} {len(g['accounts'])} accounts / {g['n_tweets']} tweets "
                  f"over {g['span_s'] / 3600:.1f}h from {_fmt_ts(g['first'])}  "
                  f"[cohesion min {g['cohesion_min']:.2f} mean {g['cohesion_mean']:.2f}]")
            print(f"         {', '.join('@' + h for h in g['accounts'])}")
            print(f"         e.g. {g['sample']!r}")
    if not n_groups:
        print("  none — no two accounts posted near-identical text about the same coin")
    if all_sims:
        # The threshold is a choice; showing the distribution it sits in is what
        # keeps it from being a knob that manufactures the finding.
        ss = sorted(all_sims)
        print(f"\n  cross-account pairwise Jaccard, all coins (n={len(ss)}): "
              f"p50 {ss[len(ss) // 2]:.3f}  p90 {ss[int(0.90 * len(ss))]:.3f}  "
              f"p99 {ss[int(0.99 * len(ss))]:.3f}  max {ss[-1]:.3f}")
        print(f"  pairs at or above threshold: {sum(1 for x in ss if x >= TEMPLATE_THRESHOLD)}"
              f" ({100 * sum(1 for x in ss if x >= TEMPLATE_THRESHOLD) / len(ss):.2f}%)")

    # ---- 3d. the same template across DIFFERENT coins -----------------------
    # This is the question behind the operator's question. One template repeated
    # by many accounts on ONE coin is a campaign for that coin. The SAME template
    # showing up on several of the operator's coins, months apart, is a standing
    # service that gets hired every time — and that is a fact about the operator's
    # income, not about any single launch.
    print()
    print("-- 3d. templates spanning MORE THAN ONE of the four coins -----------------")
    pooled_stop = {w.lower() for c in COINS for w in (c.ticker, *c.name.split())}
    pooled = [r for v in per_coin.values() for r in v if r["tier"] != "cashtag_only"]
    groups, _ = shared_template_groups(
        pooled, coin=None, threshold=TEMPLATE_THRESHOLD, stop=pooled_stop
    )
    cross = [g for g in groups if len(g["coins"]) >= 2]
    if not cross:
        print("  none — no template recurs across two or more of the four coins")
    for g in cross:
        print(f"  {'+'.join(g['coins']):<24} {len(g['accounts'])} accounts / "
              f"{g['n_tweets']} tweets  [cohesion min {g['cohesion_min']:.2f} "
              f"mean {g['cohesion_mean']:.2f}]")
        print(f"      {', '.join('@' + h for h in g['accounts'])}")
        print(f"      e.g. {g['sample']!r}")

    # ---- 4. arrival timing and the burst null -------------------------------
    print()
    print("-- 4. arrival relative to coin creation (mint-bearing rows) --------------")
    print(f"{'coin':<7}{'n':>5}{'p10':>10}{'median':>10}{'p90':>10}")
    for coin in COINS:
        lags = sorted(
            r["t_post_unix"] - coin.created_unix
            for r in per_coin[coin.ticker] if r["tier"] != "cashtag_only"
        )
        if not lags:
            print(f"{coin.ticker:<7}{0:>5}{'-':>10}{'-':>10}{'-':>10}")
            continue

        print(f"{coin.ticker:<7}{len(lags):>5}{_q(lags, 0.1):>10}{_q(lags, 0.5):>10}"
              f"{_q(lags, 0.9):>10}")

    print()
    print("-- 5. the burst null ------------------------------------------------------")
    print("statistic: mean distinct OTHER accounts calling within +/- window")
    print(f"window = {window}s, draws = {draws}, seed = {seed}")
    print(f"{'coin':<7}{'n':>5}{'accts':>7}{'obs':>8}{'naive':>8}{'p_naive':>9}"
          f"{'envelope':>10}{'p_env':>8}")
    for coin in COINS:
        cr = [r for r in per_coin[coin.ticker] if r["tier"] != "cashtag_only"]
        res = burst_null(cr, coin=coin, window=window, bandwidth=bandwidth,
                         draws=draws, seed=seed)
        if "verdict" in res:
            print(f"{coin.ticker:<7}{res['n']:>5}   {res['verdict']}")
            continue
        print(f"{coin.ticker:<7}{res['n']:>5}{res['n_accounts']:>7}{res['observed']:>8.3f}"
              f"{res['naive_mean']:>8.3f}{res['naive_p']:>9.4f}"
              f"{res['envelope_mean']:>10.3f}{res['envelope_p']:>8.4f}")

    # The envelope null has one knob and it is the bandwidth: too narrow and the
    # null absorbs the very clustering being tested, too wide and it degenerates
    # toward the naive one. A single bandwidth is a knob, not a test
    # (PROGRAM.md §3.13), so the whole range is shown and the reader can see
    # whether the verdict is a property of the data or of the setting.
    print()
    print("-- 5a. envelope-null bandwidth sensitivity (p_env) ------------------------")
    bands = (900, 3600, 14400, 86400)
    print(f"{'coin':<7}" + "".join(f"{b // 60:>10}m" for b in bands))
    for coin in COINS:
        cr = [r for r in per_coin[coin.ticker] if r["tier"] != "cashtag_only"]
        cells = []
        for b in bands:
            res = burst_null(cr, coin=coin, window=window, bandwidth=b,
                             draws=max(400, draws // 4), seed=seed)
            cells.append("   n/a" if "verdict" in res else f"{res['envelope_p']:.4f}")
        print(f"{coin.ticker:<7}" + "".join(f"{c:>11}" for c in cells))

    # the largest single burst, named — it is the object the operator can act on
    print()
    print("-- 5b. tightest observed windows (CA-confirmed) --------------------------")
    for coin in COINS:
        cr = sorted(
            (r for r in per_coin[coin.ticker] if r["tier"] != "cashtag_only"),
            key=lambda r: r["t_post_unix"],
        )
        best = (0, None, ())
        for i, r in enumerate(cr):
            grp = [x for x in cr[i:] if x["t_post_unix"] - r["t_post_unix"] <= window]
            handles = {x["author_username"] for x in grp}
            if len(handles) > best[0]:
                best = (len(handles), r["t_post_unix"], tuple(sorted(handles)))
        if best[0] >= 2:
            print(f"  {coin.ticker:<6} {best[0]} distinct accounts within {window}s at "
                  f"{_fmt_ts(best[1])}: {', '.join('@' + h for h in best[2])}")
        else:
            print(f"  {coin.ticker:<6} no window with 2+ distinct accounts")

    print()
    print("-- spend ------------------------------------------------------------------")
    print(f"census rows purchased (net of dedupe): {len(raw)}  "
          f"profile rows: {len(sample_rows)}")
    print("gross purchase totals are printed by the `census` / `profile` subcommands;")
    print("this figure is rows KEPT and is a lower bound on spend.")


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pilot", help="one slice, one coin, all shapes — measure before spending")
    p.add_argument("--coin", default="DREGG")
    p.add_argument("--hours", type=float, default=6.0)
    p.add_argument("--from-creation", action="store_true", default=True)
    p.add_argument("--extra-shape", action="append", default=[],
                   help="an additional raw query base to price, e.g. a bare word")
    p.add_argument("--out", default=str(PILOT_PATH))

    c = sub.add_parser("census", help="walk every coin's whole life")
    c.add_argument("--coins", default=",".join(x.ticker for x in COINS))
    c.add_argument("--shapes", default="ca,cashtag,url_pump,url_dex")
    c.add_argument("--slice-hours", type=float, default=24.0)
    c.add_argument("--floor-minutes", type=float, default=15.0)
    c.add_argument("--budget-tweets", type=int, default=40_000)
    c.add_argument("--end-unix", type=int, default=None)
    c.add_argument("--pre-window", action="store_true",
                   help="collect the MIRROR window before creation instead — the controls")
    c.add_argument("--out", default=str(CENSUS_PATH))

    f = sub.add_parser("profile", help="buy a from: sample for each surfaced handle")
    f.add_argument("--census", default=str(CENSUS_PATH))
    f.add_argument("--min-calls", type=int, default=1)
    f.add_argument("--per-handle", type=int, default=25)
    f.add_argument("--limit", type=int, default=500)
    f.add_argument("--handles", default=None,
                   help="comma-separated handles to sample instead of deriving them from "
                        "the census — used to prioritise the accounts an answer turns on")
    f.add_argument("--shard", default="0/1",
                   help="i/n — take every n-th handle. Lets several processes split "
                        "the buy without re-buying; each skips what is already on disk.")
    f.add_argument("--out", default=str(PROFILE_PATH))

    r = sub.add_parser("report", help="the analysis")
    r.add_argument("--census", default=str(CENSUS_PATH))
    r.add_argument("--profiles", default=str(PROFILE_PATH))
    r.add_argument("--slices", default=str(OUT_DIR / "*.slices.jsonl"),
                   help="manifest of the windows the collector ASKED about. Without it a "
                        "known-zero control cannot be told apart from a control never run.")
    r.add_argument("--window", type=int, default=300)
    r.add_argument("--bandwidth", type=int, default=3600)
    r.add_argument("--draws", type=int, default=2000)
    r.add_argument("--seed", type=int, default=20260815)

    args = ap.parse_args()

    if args.cmd == "pilot":
        coin = BY_TICKER[args.coin.lower()]
        lo = coin.created_unix
        hi = lo + int(args.hours * 3600)
        shapes = query_shapes(coin)
        for i, extra in enumerate(args.extra_shape):
            shapes[f"extra{i}"] = extra
        print(f"PILOT {coin.ticker} {_fmt_ts(lo)} -> {_fmt_ts(hi)} ({args.hours}h)")
        out = Path(args.out)
        stats = asyncio.run(
            run_collection(
                coins=[coin], shapes={coin.ticker: shapes}, windows={coin.ticker: (lo, hi)},
                slice_seconds=int(args.hours * 3600), floor_seconds=int(args.hours * 3600),
                budget_tweets=5_000, out=out,
            )
        )
        # A pilot's whole job is the extrapolation, so it does the arithmetic here
        # rather than leaving it to be eyeballed.
        rows = [r for r in load_rows(out) if r["slice_start_unix"] == lo]
        by_shape: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_shape[r["shape"]].append(r)
        print("\n-- pilot yield -----------------------------------------------------")
        print(f"{'shape':<10}{'query':<52}{'rows':>6}{'CA':>5}{'prec':>8}")
        for shape, base in shapes.items():
            sr = by_shape.get(shape, [])
            ca = [x for x in sr if x["mint_hit"]]
            prec = f"{100 * len(ca) / len(sr):.0f}%" if sr else "-"
            print(f"{shape:<10}{base[:50]:<52}{len(sr):>6}{len(ca):>5}{prec:>8}")
        print(json.dumps(stats, indent=1))
        now = int(datetime.now(UTC).timestamp())
        life_h = {c.ticker: (now - c.created_unix) / 3600 for c in COINS}
        print("\n-- extrapolation (this slice's rate x each coin's life) ------------")
        per_h = stats["gross_tweets_purchased"] / args.hours
        total = sum(life_h.values())
        print(f"pilot rate: {per_h:.1f} tweets/h across {len(shapes)} shapes")
        print(f"cluster life-hours: {total:.0f}  ->  worst-case {per_h * total:.0f} tweets "
              f"= ${per_h * total * USD_PER_TWEET:.2f}")
        print("NOTE: this is a CEILING. The pilot sits at DREGG's launch, the busiest")
        print("hours any of these coins will ever have; a flat extrapolation of launch-hour")
        print("volume across 93 coin-days overstates the real cost by a large factor.")

    elif args.cmd == "census":
        now = args.end_unix or int(datetime.now(UTC).timestamp())
        coins = [BY_TICKER[t.strip().lower()] for t in args.coins.split(",") if t.strip()]
        wanted = [s.strip() for s in args.shapes.split(",") if s.strip()]
        shapes = {
            c.ticker: {k: v for k, v in query_shapes(c).items() if k in wanted} for c in coins
        }
        if args.pre_window:
            # Same length, immediately before creation. Equal length matters: the
            # cashtag background rate is only comparable to the post rate if the
            # two windows are the same size.
            windows = {
                c.ticker: (c.created_unix - (now - c.created_unix), c.created_unix)
                for c in coins
            }
        else:
            windows = {c.ticker: (c.created_unix, now) for c in coins}
        for c in coins:
            lo, hi = windows[c.ticker]
            print(f"  {c.ticker:<6} {_fmt_ts(lo)} -> {_fmt_ts(hi)} "
                  f"({(hi - lo) / 86400:.1f}d){' [PRE-CREATION CONTROL]' if args.pre_window else ''}")
        stats = asyncio.run(
            run_collection(
                coins=coins, shapes=shapes, windows=windows,
                slice_seconds=int(args.slice_hours * 3600),
                floor_seconds=int(args.floor_minutes * 60),
                budget_tweets=args.budget_tweets, out=Path(args.out),
            )
        )
        print(json.dumps(stats, indent=1))

    elif args.cmd == "profile":
        rows = dedupe(load_rows(args.census))
        counts: Counter[str] = Counter()
        for r in rows:
            counts[r["author_username"]] += 1
        if args.handles:
            handles = [h.strip() for h in args.handles.split(",") if h.strip()]
        else:
            handles = [h for h, n in counts.most_common() if n >= args.min_calls][: args.limit]
        si, sn = (int(x) for x in args.shard.split("/"))
        handles = handles[si::sn]
        print(f"buying from: samples for {len(handles)} handles (shard {si}/{sn})")
        stats = asyncio.run(
            run_profiles(handles, per_handle=args.per_handle, out=Path(args.out))
        )
        print(json.dumps(stats, indent=1))

    else:
        report(
            census=args.census, profiles=args.profiles, slices_spec=args.slices,
            window=args.window, bandwidth=args.bandwidth,
            draws=args.draws, seed=args.seed,
        )


if __name__ == "__main__":
    main()
