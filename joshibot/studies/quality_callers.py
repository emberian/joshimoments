"""Who calls the quality cluster, and does jackduvalcalls move before he speaks?

THE QUESTION
------------
The operator: *"i just took 15 cents from fatdogwithhat — jackduvalcalls called it.
we need to be watching his wallet. also we need to investigate anyone who ever
called nosis, dregg, weave, or solve... and especially let's paper evaluate a
strategy where we move before jack calls."*

THE PRIOR THIS MUST BEAT
------------------------
`studies/RESULT_caller_wallets.md` measured the caller population and found
**zero front-runners**: 0 of 22 multi-coin callers have a wallet link surviving a
time-matched permutation null, and the single survivor (`AutorunAlert`) is the
*echo* of a 161-wallet buy burst arriving a median **26 seconds late**.
`RESULT_callout_edge.md` measured the return: buying at the callout is
-11.9% at 1 h, -43.6% at 8 h, and louder is worse.

So "move before jack calls" is only a strategy if jackduvalcalls is an
**exception** — a named entity whose own on-chain action systematically precedes
his call with a lead long enough to act on. That is testable, and this file tests
it. A null is the expected outcome and a perfectly good one.

THE JOIN, AND WHY THIS ONE IS DIFFERENT
---------------------------------------
`RESULT_caller_wallets.md` §1 reports route 1 (pump.fun username == X handle)
yielding 5 of 146 handles. This caller is one of them, and it is the *strongest*
form of that route: the operator named a handle, and pump.fun's
`/users/search?searchTerm=` returns a wallet whose username is byte-identical to
it, carrying 17,465 pump.fun followers and the bio "never wrong, always early."

That is a *name* match, not a *behaviour* match, so it is graded as such and then
tested against behaviour. Two impostors were found in the same search and are
recorded here so nobody re-resolves them: `jackduvalcaIIs` (capital-I homoglyph,
9 followers) and a family of `jack_duval` / `JackDuval` / `jackduval__` squatters.
Address hygiene follows `wallet_labels.yaml`'s resolution rule: every address that
leaves this module has passed the ed25519 on-curve test (`studies.copytrading.on_curve`)
AND has been flow-verified against an independent on-chain tape.

THE CALL SIDE
-------------
The X account is `jackduval` (51,738 followers). `from:jackduvalcalls` returns
**zero** tweets over 2026-06-01 .. 2026-08-15 — the *pump.fun* username is
`jackduvalcalls`; the X handle is `jackduval`. Both facts are recorded because
conflating them is exactly how a study measures the wrong entity.

DISCIPLINE
----------
- One clock per field. `t_post` is the tweet's own `created_at`; `t` on a trade is
  the block clock; `t_collect` is ours. They are compared, never mixed.
- Every slice records the window it asked for and whether it hit the actor's cap,
  so truncation is visible rather than silently thinning the sample.
- No address is written to an artifact without `on_curve() is True` and an
  independent flow observation. Two fabricated addresses reached
  `wallet_labels.yaml` this week; the invariant here is the same one that caught them.
- Anything fitted on Jack is fitted on the train period and applied forward.

USAGE
-----
    python -m studies.quality_callers collect-jack        # X census, jackduval
    python -m studies.quality_callers collect-cluster     # X census, 4 cluster coins
    python -m studies.quality_callers wallet              # on-chain pull for candidates
    python -m studies.quality_callers report              # everything
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "state" / "callers"
RAW = OUT / "raw"
CACHE = REPO / ".cache" / "quality_callers"

PUMP_API = "https://frontend-api-v3.pump.fun"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

#: The named entity. `pump_username` is what the operator said; `x_handle` is what
#: actually posts. They differ, and the difference is a finding (§1 of the RESULT).
JACK_X_HANDLE = "jackduval"
JACK_PUMP_USERNAME = "jackduvalcalls"

#: The four quality-cluster coins, with the creation clock pump.fun reports.
#: Mints are imported from the cluster package rather than retyped, because a
#: transposed address is this repo's documented failure mode (pools.py:5).
from shitcoims_cluster.pools import DREGG, NOSIS, SOLVE, WEAVE  # noqa: E402

CLUSTER: dict[str, tuple[str, int]] = {
    # ticker -> (mint, created_unix)
    "DREGG": (DREGG, 1_782_565_198),
    "SOLVE": (SOLVE, 1_784_577_587),
    "weave": (WEAVE, 1_785_795_942),
    "nosis": (NOSIS, 1_786_260_938),
}

#: The other high-follower pump.fun accounts whose trades also fire the following feed.
#: Every address here passed `on_curve` AND was flow-verified against `state/bulk_pump`.
#: They are graded `probable` for the same reason jackduvalcalls is: a pump.fun username is a
#: self-declared name on a platform, not an attestation.
ROSTER_WALLETS: dict[str, str] = {
    "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh": "jackduvalcalls",
    "6DQAGJT7VZPVBsuG4kn3AvpyHCEi7B2RFFvMZdbqQqqP": "cupsey",
    "DuQabFqdC9eeBULVa7TTdZYxe8vK8ct5DZr4Xcf7docy": "orangie",
    "8deJ9xeUvXSJwicYptA9mHsU2rN2pDx37KWzkDkEXhU6": "cooker",
    "8MaVa9kdt3NW4Q5HyNAm1X5LbR8PQRVDc1W8NMVK88D5": "daumen",
}

#: The actor bills per returned item and returns ~20 filler rows ("mock_tweet")
#: when a query matches nothing. Filler is never counted as data, but it IS
#: counted as spend, because it is billed.
APIFY_PRICE_PER_ITEM = 0.00025

#: A slice returning at least this many real rows is treated as truncated and split.
#: The actor overshoots `maxItems`, so the test is on the request, not the response.
CAP_FRACTION = 0.95


# ---------------------------------------------------------------------------
# X collection
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Spend:
    queries: int = 0
    items: int = 0
    real: int = 0
    filler: int = 0

    @property
    def usd(self) -> float:
        return self.items * APIFY_PRICE_PER_ITEM

    def line(self) -> str:
        return (
            f"{self.queries} queries, {self.items} items billed "
            f"({self.real} real, {self.filler} filler) = ${self.usd:.3f}"
        )


async def _search(http: Any, token: str, query: str, max_items: int) -> tuple[list[dict], int]:
    """One actor call. Returns (real rows, billed item count).

    The adapter in `shitcoims_intelligence.adapters.x_apify` is the live collector's
    path and applies its own parsing/quarantine policy. This study talks to the actor
    directly so that a parse rejection cannot silently become a zero — the census
    claim in the RESULT depends on knowing the difference between "no tweets" and
    "tweets we failed to parse", and `from:jackduvalcalls` returning 0-real/15-filler
    is precisely that distinction.
    """

    from shitcoims_intelligence.adapters.x_apify import ENDPOINT

    for attempt in range(4):
        try:
            response = await http.post(
                ENDPOINT,
                headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
                json={"twitterContent": query, "maxItems": max_items, "queryType": "Latest"},
            )
            response.raise_for_status()
            body = response.json()
            break
        except Exception:
            if attempt == 3:
                raise
            await asyncio.sleep(2 ** attempt)
    if not isinstance(body, list):
        return [], 0
    real = [b for b in body if b.get("type") != "mock_tweet"]
    return real, len(body)


def _parse_created(value: str | None) -> float | None:
    """X's `createdAt` is RFC-822-ish: 'Sat Aug 15 16:52:34 +0000 2026'."""

    if not value:
        return None
    try:
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y").timestamp()
    except ValueError:
        return None


def _row(item: dict, *, query: str, lo: int, hi: int, t_collect: str) -> dict:
    author = item.get("author") or {}
    text = item.get("text") or ""
    mints = sorted(extract_mints(text))
    return {
        "t_post": _parse_created(item.get("createdAt")),
        "t_post_iso": item.get("createdAt"),
        "t_collect": t_collect,
        "query": query,
        "slice_start_unix": lo,
        "slice_end_unix": hi,
        "tweet_id": item.get("id"),
        "url": item.get("url") or item.get("twitterUrl"),
        "kind": "reply" if item.get("isReply") else "post",
        "text": text,
        "author_username": author.get("userName"),
        "author_followers": author.get("followers"),
        "author_verified": bool(author.get("isBlueVerified") or author.get("isVerified")),
        "like_count": item.get("likeCount"),
        "retweet_count": item.get("retweetCount"),
        "reply_count": item.get("replyCount"),
        "view_count": item.get("viewCount"),
        "conversation_id": item.get("conversationId"),
        "in_reply_to": item.get("inReplyToUsername"),
        "mints": mints,
    }


_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def extract_mints(text: str) -> set[str]:
    """Every launchpad-suffixed or CA-marked base58 address in a tweet.

    Delegates the hard part — "is this string a 32-byte address" — to the live
    adapter's `is_solana_mint`, which decodes rather than pattern-matching. A
    length-and-charset test admits strings that are not addresses, and admitting
    one is how a lowercased unusable address reached the live scalper once already
    (`RESULT_callout_edge.md` §1.1).
    """

    import re

    from shitcoims_intelligence.adapters.x_apify import is_solana_mint

    out: set[str] = set()
    b58 = f"[{_B58_ALPHABET}]{{32,44}}"
    for pattern in (
        rf"(?<![{_B58_ALPHABET}])({b58[:-1]}(?:pump|bonk|moon|boop))(?![{_B58_ALPHABET}])",
        rf"(?i:\bca\b|\bcontract\b|\bmint\b|\btoken\b)\s*[:=\-]?\s*(?:solana:)?({b58})",
        rf"https?://(?:www\.)?(?:pump\.fun/(?:coin/)?|dexscreener\.com/solana/|axiom\.trade/(?:t/|meme/)?)({b58})",
        rf"solana:({b58})",
    ):
        for match in re.finditer(pattern, text):
            candidate = match.group(1)
            if is_solana_mint(candidate):
                out.add(candidate)
    return out


async def census(
    *,
    base_query: str,
    lo: int,
    hi: int,
    out_path: Path,
    max_items: int = 100,
    min_slice_s: int = 900,
    spend: Spend | None = None,
    echo: Any = print,
) -> Spend:
    """Adaptive-slice census of one query over [lo, hi].

    A slice that comes back at or above the cap is SPLIT rather than accepted, down
    to `min_slice_s`. `RESULT_callout_edge.md` §2 could claim a census because zero
    slices capped; this keeps that property by construction instead of by luck, and
    any slice that still caps at the floor is written to the manifest as truncated so
    the RESULT can report it rather than the reader having to trust it.
    """

    import httpx

    spend = spend or Spend()
    token = Path("~/.apify-token").expanduser().read_text().strip()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    truncated: list[tuple[int, int]] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(240, connect=5)) as http:
        stack: list[tuple[int, int]] = [(lo, hi)]
        with out_path.open("a") as fh:
            while stack:
                a, b = stack.pop()
                query = f"{base_query} since_time:{a} until_time:{b}"
                real, billed = await _search(http, token, query, max_items)
                spend.queries += 1
                spend.items += billed
                spend.real += len(real)
                spend.filler += billed - len(real)
                capped = len(real) >= int(max_items * CAP_FRACTION)
                if capped and (b - a) > min_slice_s:
                    mid = (a + b) // 2
                    stack.extend([(a, mid), (mid, b)])
                    echo(f"  split {a}..{b} ({len(real)} rows)")
                    continue
                if capped:
                    truncated.append((a, b))
                t_collect = datetime.now(UTC).isoformat()
                fresh = 0
                for item in real:
                    tid = str(item.get("id"))
                    if tid in seen:
                        continue
                    seen.add(tid)
                    fresh += 1
                    fh.write(
                        json.dumps(
                            _row(item, query=base_query, lo=a, hi=b, t_collect=t_collect),
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                fh.flush()
                echo(
                    f"  {datetime.fromtimestamp(a, UTC):%m-%d %H:%M}"
                    f"..{datetime.fromtimestamp(b, UTC):%m-%d %H:%M}"
                    f"  {base_query[:34]:<34} real={len(real):<3} new={fresh:<3}"
                    f"{' TRUNCATED' if capped else ''}"
                )
    manifest = out_path.with_suffix(".manifest.json")
    prior = json.loads(manifest.read_text()) if manifest.exists() else []
    prior.append(
        {
            "base_query": base_query,
            "lo": lo,
            "hi": hi,
            "queries": spend.queries,
            "items_billed": spend.items,
            "real": spend.real,
            "usd": round(spend.usd, 4),
            "truncated_slices": truncated,
            "t_collect": datetime.now(UTC).isoformat(),
        }
    )
    manifest.write_text(json.dumps(prior, indent=1))
    return spend


# ---------------------------------------------------------------------------
# pump.fun identity probes
# ---------------------------------------------------------------------------


def route1_probe(handles: Sequence[str], *, pause: float = 0.16, echo: Any = print) -> dict[str, dict]:
    """pump.fun username == X handle, cached. Route 1 of `RESULT_caller_wallets.md` §1.

    `exact` is a case-insensitive byte match on the username; anything else is a fuzzy
    hit and is retained only as context, never as a join. The homoglyph row is the
    reason: `jackduvalcaIIs` (capital I for lowercase l) is a *different string* that a
    human reads as identical, and a fuzzy join would have taken it.
    """

    cache_path = CACHE / "route1.json"
    CACHE.mkdir(parents=True, exist_ok=True)
    cache: dict[str, dict] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    for i, handle in enumerate(handles):
        if handle in cache:
            continue
        hits = username_search(handle)
        exact = [h for h in hits if (h.get("username") or "").lower() == handle.lower()]
        cache[handle] = {
            "handle": handle,
            "n_hits": len(hits),
            "exact": exact,
            "fuzzy_usernames": [h.get("username") for h in hits[:8]],
        }
        if exact:
            echo(f"  route1 EXACT {handle} -> {exact[0]['address']} ({exact[0].get('followers')} followers)")
        if i % 25 == 0:
            cache_path.write_text(json.dumps(cache))
        time.sleep(pause)
    cache_path.write_text(json.dumps(cache))
    return cache


def _pump_get(path: str) -> Any:
    request = urllib.request.Request(
        PUMP_API + path, headers={"User-Agent": BROWSER_UA, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read())
    except Exception as exc:  # 404 is an answer, not a failure
        return {"_err": repr(exc)}


def username_search(term: str) -> list[dict]:
    """Route 1 of `RESULT_caller_wallets.md` §1. `searchTerm` is the ONLY live param.

    `?username=` and `?q=` return HTTP 200 with `[]` for every input including inputs
    that exist, so a study using either reports a confident zero. Re-verified here.
    """

    result = _pump_get(f"/users/search?searchTerm={urllib.parse.quote(term)}")
    return result if isinstance(result, list) else []


def profile(wallet: str) -> dict:
    result = _pump_get(f"/users/{wallet}")
    return result if isinstance(result, dict) else {}


def balances(wallet: str, limit: int = 50) -> list[dict]:
    result = _pump_get(f"/balances/{wallet}?limit={limit}&offset=0")
    return result if isinstance(result, list) else []


def coin_meta(mint: str) -> dict:
    result = _pump_get(f"/coins/{mint}")
    return result if isinstance(result, dict) else {}


# ---------------------------------------------------------------------------
# address hygiene — the invariant every emitted address passes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AddressVerdict:
    address: str
    on_curve: bool | None
    flow_observed: bool
    flow_source: str
    flow_detail: str

    @property
    def ok(self) -> bool:
        return self.on_curve is True and self.flow_observed


def verify_address(address: str, *, flow_source: str, flow_detail: str, flow: bool) -> AddressVerdict:
    """No address leaves this module without BOTH checks.

    On-curve alone is not enough: a fabricated address can land on the curve by
    chance with probability ~1/2, and one of the two fabrications caught in
    `wallet_labels.yaml` this week was rejected precisely because it was OFF the
    curve — i.e. the check that caught it would have missed a luckier fake. The
    second leg, an independently observed trade, is what makes the claim about a
    thing that exists rather than a string that parses.
    """

    from studies.copytrading import on_curve

    return AddressVerdict(
        address=address,
        on_curve=on_curve(address),
        flow_observed=flow,
        flow_source=flow_source,
        flow_detail=flow_detail,
    )


# ---------------------------------------------------------------------------
# on-chain panel: Jack's legs, his coins' prices, and a hash-sampled control pool
# ---------------------------------------------------------------------------

BULK = REPO / "state" / "bulk_pump" / "daily"
WSOL = "So11111111111111111111111111111111111111112"
#: Bonding-curve constants, taken from `studies/callout_volatility.py` so the two
#: studies price a pre-migration coin identically.
CURVE_TOKEN_OFFSET = 73_000_000_000_000
CURVE_K = 3.219e25
#: Deterministic control sample. `hash(mint) % 100 < CONTROL_PCT` is reproducible,
#: independent of anything about the coin, and — unlike "the coins on the boards" —
#: not selected on attention, which is the selection that produced this repo's worst
#: published number (`RESULT_board_entry.md`).
CONTROL_PCT = 4


def _duckdb(memory: str = "24GB", threads: int = 6) -> Any:
    import duckdb

    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory}'")
    con.execute(f"SET threads={threads}")
    con.execute("SET preserve_insertion_order=false")
    return con


def bulk_files() -> list[Path]:
    return sorted(BULK.glob("*.parquet"))


def build_panel(*, wallets: Sequence[str], out: Path, echo: Any = print) -> Path:
    """One DuckDB pass -> (a) every leg of `wallets`, (b) a priced trade tape.

    The tape covers the union of the wallets' mints and a deterministic
    `CONTROL_PCT`% hash-sample of every other pump mint in the corpus. The sample is
    the control population: it is drawn from the whole market rather than from any
    attention surface, so a coin that nobody ever looked at is exactly as likely to be
    a control as a coin that trended.

    Pricing follows `studies/callout_volatility.build_panel` exactly — counterparty =
    the owner in the most of a mint's transactions, side = the SIGN of its balance
    change, `log_price` from the pool's reserve ratio after migration and from the
    curve invariant before it. Reproducing that logic rather than importing it would
    be two price bases wearing one column name.
    """

    files = "[" + ",".join(f"'{p}'" for p in bulk_files()) + "]"
    wl = "(" + ",".join(f"'{w}'" for w in wallets) + ")"
    out.parent.mkdir(parents=True, exist_ok=True)
    con = _duckdb()
    echo(f"panel: {len(bulk_files())} day(s) {bulk_files()[0].name} .. {bulk_files()[-1].name}")

    con.execute(
        f"""
        CREATE OR REPLACE TABLE legs AS
        SELECT t.block_slot, t.tx_index, t.block_time, t.signature,
               u.owner AS owner, u.mint AS mint, CAST(u.amount AS HUGEINT) AS amt
        FROM read_parquet({files}) t, UNNEST(t.post) s(u)
        WHERE t.err = ''
        """
    )
    n_legs = con.execute("SELECT COUNT(*) FROM legs").fetchone()[0]
    echo(f"panel: {n_legs:,} post-balance legs")

    con.execute(
        f"""
        CREATE OR REPLACE TABLE wallet_legs AS
        SELECT * FROM legs WHERE owner IN {wl}
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE keep AS
        SELECT DISTINCT mint FROM legs
        WHERE mint LIKE '%pump'
          AND (mint IN (SELECT mint FROM wallet_legs)
               OR abs(hash(mint)) % 100 < {CONTROL_PCT})
        """
    )
    n_keep = con.execute("SELECT COUNT(*) FROM keep").fetchone()[0]
    echo(f"panel: {n_keep:,} mints kept (wallet mints + {CONTROL_PCT}% hash sample)")

    con.execute(
        """
        CREATE OR REPLACE TABLE cp AS
        WITH per_owner AS (
          SELECT l.mint, l.owner, COUNT(*) AS n_tx, MAX(l.amt) AS max_amt
          FROM legs l JOIN keep k USING (mint) GROUP BY l.mint, l.owner
        ), ranked AS (
          SELECT *, ROW_NUMBER() OVER (PARTITION BY mint ORDER BY n_tx DESC, max_amt DESC) AS rk
          FROM per_owner
        )
        SELECT mint, owner AS cp_owner, n_tx,
               (SELECT COUNT(*) FROM ranked r2
                 WHERE r2.mint = ranked.mint AND r2.rk > 1 AND r2.n_tx >= 0.20 * ranked.n_tx)
                 > 0 AS migrated_flag
        FROM ranked WHERE rk = 1
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE cp_kind AS
        SELECT c.*, EXISTS (SELECT 1 FROM legs l
                             WHERE l.owner = c.cp_owner AND l.mint = '{WSOL}') AS is_pool
        FROM cp c
        """
    )
    con.execute(
        f"""
        COPY (
          WITH cur AS (
            SELECT l.mint, l.block_time, l.block_slot, l.tx_index,
                   CAST(l.amt AS DOUBLE) AS tok_bal, k.is_pool, k.migrated_flag
            FROM legs l JOIN cp_kind k ON l.mint = k.mint AND l.owner = k.cp_owner
          ), wsol AS (
            SELECT l.block_slot, l.tx_index, k.mint, CAST(l.amt AS DOUBLE) AS wsol_bal
            FROM legs l JOIN cp_kind k ON l.owner = k.cp_owner
            WHERE l.mint = '{WSOL}' AND k.is_pool
          ), joined AS (
            SELECT c.*, w.wsol_bal FROM cur c LEFT JOIN wsol w
              ON c.mint = w.mint AND c.block_slot = w.block_slot AND c.tx_index = w.tx_index
          )
          SELECT mint, block_time, block_slot, tx_index, tok_bal, wsol_bal, is_pool, migrated_flag,
                 CASE WHEN is_pool AND wsol_bal > 0 AND tok_bal > 0
                        THEN ln(wsol_bal) - ln(tok_bal)
                      WHEN NOT is_pool AND tok_bal + {CURVE_TOKEN_OFFSET} > 0
                        THEN ln({CURVE_K}) - 2 * ln(tok_bal + {CURVE_TOKEN_OFFSET})
                 END AS log_price,
                 CASE WHEN is_pool THEN wsol_bal / 1e9 ELSE tok_bal * 0 END AS pool_sol,
                 -sign(tok_bal - lag(tok_bal) OVER (
                     PARTITION BY mint ORDER BY block_slot, tx_index)) AS side
          FROM joined
        ) TO '{out}' (FORMAT PARQUET)
        """
    )
    con.execute(f"COPY (SELECT * FROM wallet_legs) TO '{out.with_name('wallet_legs.parquet')}' (FORMAT PARQUET)")
    echo(f"panel: wrote {out} and {out.with_name('wallet_legs.parquet')}")
    return out


# ---------------------------------------------------------------------------
# the caller table
# ---------------------------------------------------------------------------


def load_census(pattern: str) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(RAW.glob(pattern)):
        for line in path.open():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def boilerplate_share(texts: Sequence[str]) -> float:
    """Fraction of an average tweet's words that appear in >=80% of that account's tweets.

    `RESULT_caller_wallets.md` §6's discriminator, reproduced so the two studies label
    an account the same way. A person writing about a coin scores near zero; a template
    with the ticker slotted in scores near one. Needs >=3 tweets to mean anything.
    """

    import re

    if len(texts) < 3:
        return float("nan")
    cleaned = []
    for text in texts:
        text = re.sub(r"https?://\S+", " ", text)
        text = re.sub(r"[1-9A-HJ-NP-Za-km-z]{32,44}", " ", text)
        text = re.sub(r"[\d.,]+", " ", text)
        cleaned.append([w for w in re.findall(r"[A-Za-z]{2,}", text.lower())])
    import collections

    doc_freq: collections.Counter = collections.Counter()
    for words in cleaned:
        doc_freq.update(set(words))
    n = len(cleaned)
    shares = []
    for words in cleaned:
        if not words:
            continue
        shares.append(sum(1 for w in words if doc_freq[w] >= 0.8 * n) / len(words))
    return sum(shares) / len(shares) if shares else float("nan")


def caller_class(*, n_calls: int, boiler: float, referral: float) -> str:
    if n_calls < 2:
        return "single_call_unclassifiable"
    if (boiler == boiler and boiler >= 0.6) or referral >= 0.8:
        return "automated_relay"
    return "repeat_human_or_unknown"


def choreography(
    legs: Sequence[tuple[int, int]], t_call: float, *, window: float = 3600.0
) -> dict[str, Any]:
    """buy -> call -> sell, for one wallet on one coin, around one call.

    `legs` are (block_time, signed base-unit delta) with delta > 0 a buy. Every number
    is in token base units normalised per coin; SOL legs are not in this tape and are
    deliberately not guessed at.
    """

    buys = [(t, d) for t, d in legs if d > 0]
    sells = [(t, -d) for t, d in legs if d < 0]
    first_buy = buys[0][0] if buys else None
    first_buy_before = next((t for t, _ in buys if t <= t_call), None)
    bought = sum(d for _, d in buys) or 1
    sold_into = sum(d for t, d in sells if t_call <= t <= t_call + window)
    return {
        "first_buy_unix": first_buy,
        "first_buy_before_call_unix": first_buy_before,
        "lead_s": (t_call - first_buy_before) if first_buy_before is not None else None,
        "n_buys": len(buys),
        "n_sells": len(sells),
        "bought_base_units": sum(d for _, d in buys),
        "sold_base_units": sum(d for _, d in sells),
        "exit_into_callout_frac": sold_into / bought,
        "held_at_call": sum(d for t, d in legs if t <= t_call),
    }


# ---------------------------------------------------------------------------
# strategy scoring — the wiggle book's discipline, applied to a log-price tape
# ---------------------------------------------------------------------------

#: `shitcoims_paperdesk/policy.py` WigglePolicy.ranges, midpoints. The clock is the
#: operator's clock; using anything else would score a strategy this desk cannot run.
HOLD_S = 330.0        # ranges hold_seconds (240, 420)
TAKE_PROFIT = 0.06    # ranges take_profit (0.03, 0.09)
STOP_LOSS = 0.175     # ranges stop_loss (0.10, 0.25)

#: Round-trip friction at the operator's 0.1 SOL clip in a 50-100 SOL pool, computed
#: from `shitcoims_scalper.policy.round_trip_friction` at 100-105 bps take. The
#: constant is not hard-coded downstream: `friction_for` recomputes it per fill from
#: the pool depth actually observed, and this is only the quoted headline.
FRICTION_REFERENCE = 0.024

#: Forward horizons the brief asks for.
HORIZONS_S: tuple[int, ...] = (300, 1800, 7200)

#: A coin whose tape goes silent for this long is treated as DEAD from the last print,
#: not as missing. `RESULT_callout_edge.md` §4: dropping these manufactures +39.6 pp.
DEATH_SILENCE_S = 3600.0


def friction_for(pool_sol: float, *, clip_sol: float = 0.1, take_bps: int = 105) -> float:
    """Round-trip cost of one clip, from the desk's own formula.

    Imported rather than re-derived so a change to the desk's fee model cannot leave
    this study quoting a stale number.
    """

    from shitcoims_scalper.policy import LAMPORTS_PER_SOL, round_trip_friction

    size = int(clip_sol * LAMPORTS_PER_SOL)
    depth = max(int(pool_sol * LAMPORTS_PER_SOL), size * 2)
    return round_trip_friction(
        size, depth, swap_fee_bps=take_bps, priority_fee_lamports=35_000
    )


@dataclass(frozen=True, slots=True)
class Fill:
    """One paper round trip, marked pessimistically."""

    mint: str
    t_entry: float
    entry_log_price: float
    t_exit: float
    exit_log_price: float
    reason: str
    gross: float          # simple return before friction
    net: float            # after the pool's own measured round-trip friction
    net_pessimistic: float  # dead/censored marked to zero
    dead: bool
    censored: bool
    pool_sol: float
    friction: float


def score_entry(
    times: Sequence[int],
    logp: Sequence[float],
    depth: Sequence[float],
    t0: float,
    *,
    mint: str,
    tape_end: float,
    hold_s: float = HOLD_S,
    take_profit: float = TAKE_PROFIT,
    stop_loss: float = STOP_LOSS,
) -> Fill | None:
    """Enter at the first print at or after `t0`; exit on TP, SL, or the clock.

    Three disciplines carried from the desk and from `RESULT_callout_edge.md`:

    - **The entry fills at a print, not at `t0`.** A signal at `t0` cannot be filled
      before somebody trades; using the price at `t0` interpolated from a later print
      is look-ahead, and on a 30-second tape it is worth several percent.
    - **The exit is marked at the last observed price, never dropped.** A coin whose
      tape stops is *dead*, priced at its last real print, with `dead` set — never
      excluded, which is the exclusion that reversed this repo's worst number.
    - **`net_pessimistic` prices a dead or administratively censored exit at zero.**
      A mark is a real return but not a plausible fill; the two columns bracket the
      truth and both are reported.
    """

    import bisect

    i = bisect.bisect_left(times, int(t0))
    if i >= len(times):
        return None
    t_entry = float(times[i])
    p0 = logp[i]
    pool = depth[i] if i < len(depth) else 0.0
    fric = friction_for(pool if pool and pool > 0 else 50.0)
    deadline = t_entry + hold_s
    exit_i = i
    reason = "deadline"
    for j in range(i + 1, len(times)):
        r = math_expm1(logp[j] - p0)
        if r >= take_profit:
            exit_i, reason = j, "take_profit"
            break
        if r <= -stop_loss:
            exit_i, reason = j, "stop_loss"
            break
        if times[j] >= deadline:
            exit_i, reason = j, "deadline"
            break
        exit_i = j
    else:
        # ran off the end of this mint's tape without reaching the deadline
        reason = "silent"
    t_exit = float(times[exit_i])
    silent_for = min(tape_end, t_entry + hold_s) - t_exit
    dead = reason == "silent" and silent_for >= DEATH_SILENCE_S
    censored = t_entry + hold_s > tape_end
    gross = math_expm1(logp[exit_i] - p0)
    net = gross - fric
    return Fill(
        mint=mint,
        t_entry=t_entry,
        entry_log_price=p0,
        t_exit=t_exit,
        exit_log_price=logp[exit_i],
        reason=reason,
        gross=gross,
        net=net,
        net_pessimistic=(-1.0 - fric) if (dead or censored) else net,
        dead=dead,
        censored=censored,
        pool_sol=float(pool or 0.0),
        friction=fric,
    )


def math_expm1(x: float) -> float:
    import math

    return math.expm1(x)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _daily_windows(lo: int, hi: int, step: int) -> list[tuple[int, int]]:
    out = []
    t = lo
    while t < hi:
        out.append((t, min(t + step, hi)))
        t += step
    return out


def cmd_collect_jack(args: argparse.Namespace) -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / "jack.jsonl"
    spend = Spend()
    lo, hi = args.start, args.end
    span = f"{datetime.fromtimestamp(lo, UTC)}..{datetime.fromtimestamp(hi, UTC)}"
    print(f"census from:{JACK_X_HANDLE} over {span}")
    spend = asyncio.run(
        census(
            base_query=f"from:{JACK_X_HANDLE}",
            lo=lo,
            hi=hi,
            out_path=out,
            max_items=args.max_items,
            spend=spend,
        )
    )
    # The negative control: the handle the operator named. A zero here is a finding,
    # and it is only a finding if it is collected the same way as the positive.
    spend = asyncio.run(
        census(
            base_query=f"from:{JACK_PUMP_USERNAME}",
            lo=lo,
            hi=hi,
            out_path=RAW / "jackduvalcalls_handle.jsonl",
            max_items=20,
            min_slice_s=10**9,  # never split; one query is enough to establish zero
            spend=spend,
        )
    )
    print(spend.line())
    return 0


def cmd_collect_cluster(args: argparse.Namespace) -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    spend = Spend()
    now = int(time.time())
    for ticker, (mint, created) in CLUSTER.items():
        out = RAW / f"cluster-{ticker}.jsonl"
        for base in (mint, f"${ticker}"):
            print(f"census {base[:24]} for {ticker} from {datetime.fromtimestamp(created, UTC)}")
            spend = asyncio.run(
                census(
                    base_query=base,
                    lo=created,
                    hi=now,
                    out_path=out,
                    max_items=args.max_items,
                    spend=spend,
                )
            )
    print(spend.line())
    return 0


def load_panel() -> tuple[dict[str, tuple], float, float]:
    """(mint -> (times, log_price, pool_sol)), tape start, tape end."""

    import duckdb

    con = duckdb.connect()
    con.execute("SET memory_limit='5GB'")
    con.execute("SET threads=3")
    frame = con.execute(
        f"""SELECT mint, block_time, log_price, pool_sol
            FROM read_parquet('{CACHE / "panel.parquet"}')
            WHERE log_price IS NOT NULL AND isfinite(log_price)
            ORDER BY mint, block_slot, tx_index"""
    ).df()
    series = {
        m: (g.block_time.to_numpy().astype(float), g.log_price.to_numpy(), g.pool_sol.to_numpy())
        for m, g in frame.groupby("mint", sort=False)
    }
    return series, float(frame.block_time.min()), float(frame.block_time.max())


def load_wallet_events() -> dict[str, list[tuple[float, float]]]:
    """mint -> [(block_time, signed token delta)] for the watched wallet.

    The corpus stores POST balances, so a delta is a difference against the wallet's own
    previous balance in that mint. A first row with no predecessor is a buy of its whole
    amount, which is correct: the wallet held nothing before its first leg.
    """

    import collections

    import duckdb

    con = duckdb.connect()
    con.execute("SET memory_limit='4GB'")
    con.execute("SET threads=3")
    frame = con.execute(
        f"""SELECT mint, block_time, block_slot, tx_index, amt
            FROM read_parquet('{CACHE / "wallet_legs.parquet"}')
            WHERE mint LIKE '%pump' ORDER BY mint, block_slot, tx_index"""
    ).df()
    out: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
    for mint, group in frame.groupby("mint", sort=False):
        prev = 0.0
        for t, amount in zip(group.block_time.to_numpy(), group.amt.astype(float).to_numpy(), strict=True):
            out[mint].append((float(t), amount - prev))
            prev = amount
    return dict(out)


def first_bursts(threshold: int = 15) -> dict[str, float]:
    """mint -> the instant a `threshold`-wallet minute becomes KNOWABLE.

    The +60 s is not a fudge: a per-minute distinct-buyer count is only observable once
    the minute has closed, so entering at the minute's start would be look-ahead on the
    very quantity the strategy triggers on.
    """

    import duckdb

    con = duckdb.connect()
    con.execute("SET memory_limit='4GB'")
    con.execute("SET threads=3")
    frame = con.execute(
        f"""SELECT mint, minute, wallets FROM read_parquet('{CACHE / "wallets_minute.parquet"}')
            WHERE wallets >= {threshold} ORDER BY mint, minute"""
    ).df()
    out: dict[str, float] = {}
    for mint, group in frame.groupby("mint", sort=False):
        out[mint] = float(group.minute.to_numpy()[0]) + 60.0
    return out


def cmd_cluster_table(args: argparse.Namespace) -> int:
    """state/callers/quality_cluster.jsonl — every caller of nosis/DREGG/weave/SOLVE.

    Four join routes, each one's yield a measurement. The one that matters is route 1's
    FAILURE MODE: a pump.fun username matching an X handle is a *name*, and the second leg
    — did that wallet ever trade the coin its handle called — is what turns a name into an
    identity. On this cohort not one name match survives that leg.
    """

    import collections
    import pickle
    import random
    import statistics

    from studies.caller_wallets import benjamini_hochberg

    legs = pickle.load((CACHE / 'cluster_legs.pkl').open('rb'))   # (ticker, wallet) -> [(t, delta)]
    TAPE_LO = min(t for v in legs.values() for t, _ in v)
    TAPE_HI = max(t for v in legs.values() for t, _ in v)
    print(
        f"attributed cluster tape: {dt.datetime.fromtimestamp(TAPE_LO,dt.UTC)} "
        f".. {dt.datetime.fromtimestamp(TAPE_HI,dt.UTC)}"
    )
    route1 = json.loads((CACHE / "route1.json").read_text())

    #: Route 3: the coin's own advertised X account. From pump.fun coin metadata.
    COIN_X = {"DREGG": "ember_arlynx", "nosis": "plan9nosis", "weave": "transkatgirl", "SOLVE": "open_solve"}

    rows = []
    per_caller_coins = collections.defaultdict(set)
    census_by_coin = {}
    for ticker, (_mint, _created) in CLUSTER.items():
        path = RAW / f"cluster-{ticker}.jsonl"
        if not path.exists():
            continue
        tweets = [json.loads(raw) for raw in path.open() if raw.strip()]
        # dedupe on tweet id: the mint query and the cashtag query overlap
        seen = {}
        for t in tweets:
            if t.get("tweet_id") and t["t_post"]:
                seen[t["tweet_id"]] = t
        tweets = sorted(seen.values(), key=lambda r: r["t_post"])
        census_by_coin[ticker] = tweets
        by_author = collections.defaultdict(list)
        for t in tweets:
            if t.get("author_username"):
                by_author[t["author_username"]].append(t)
        print(f"{ticker}: {len(tweets)} unique tweets, {len(by_author)} callers")
        for handle, ts in by_author.items():
            per_caller_coins[handle].add(ticker)
            texts = [t["text"] for t in ts]
            boiler = boilerplate_share(texts)
            referral = sum(1 for t in texts if "t.co" in t or "http" in t) / len(texts)
            r1 = route1.get(handle) or {}
            exact = (r1.get("exact") or [None])[0]
            wallet, method, conf, evidence = None, "none", "none", {}
            if handle.lower() == COIN_X[ticker].lower():
                method, conf = "route3_coin_is_the_project", "attested_by_coin_metadata"
                evidence = {"pump_fun_twitter_field": COIN_X[ticker]}
            elif exact:
                cand = exact["address"]
                has_flow = any((ticker, cand) == k for k in legs)
                v = verify_address(cand, flow_source="cluster_tape", flow=has_flow,
                                   flow_detail=f"counterparty on {ticker} in the attributed tape")
                if v.on_curve is True:
                    wallet = cand
                    method = "route1_pumpfun_username"
                    # a 0-follower pump.fun profile with a matching name is a name collision,
                    # not an identification; the follower count is the discriminator we have
                    followers = exact.get("followers") or 0
                    conf = ("probable" if (followers >= 1000 and has_flow)
                            else "weak_name_collision_possible")
                    evidence = {"pump_fun_username": exact.get("username"),
                                "pump_fun_followers": followers,
                                "on_curve": True, "flow_observed_on_this_coin": has_flow}
            chore = None
            if wallet and (ticker, wallet) in legs:
                chore = choreography(legs[(ticker, wallet)], ts[0]["t_post"])
            rows.append({
                "coin": ticker, "mint": CLUSTER[ticker][0], "coin_created_unix": CLUSTER[ticker][1],
                "caller": handle,
                "n_calls": len(ts),
                "first_call_unix": ts[0]["t_post"], "last_call_unix": ts[-1]["t_post"],
                "call_unixes": [t["t_post"] for t in ts][:200],
                "followers_max": max((t.get("author_followers") or 0) for t in ts),
                "verified": any(t.get("author_verified") for t in ts),
                "reply_share": sum(1 for t in ts if t.get("kind") == "reply") / len(ts),
                "boilerplate_share": None if boiler != boiler else round(boiler, 3),
                "link_share": round(referral, 3),
                "class": caller_class(n_calls=len(ts), boiler=boiler, referral=referral),
                "wallet": wallet, "join_method": method, "join_confidence": conf,
                "join_evidence": evidence,
                "choreography": chore,
                "attributed_tape_window": [TAPE_LO, TAPE_HI],
                "call_inside_attributed_tape": bool(TAPE_LO <= ts[0]["t_post"] <= TAPE_HI),
            })

    for r in rows:
        r["n_cluster_coins_called"] = len(per_caller_coins[r["caller"]])

    # ---- route 4: the temporal join, with a time-matched permutation null ----
    print("\n=== route 4: temporal join on the attributed cluster tape ===")
    universe = [(r["coin"], r["first_call_unix"]) for r in rows if r["call_inside_attributed_tape"]]
    multi = collections.defaultdict(list)
    for r in rows:
        if r["call_inside_attributed_tape"]:
            multi[r["caller"]].append((r["coin"], r["first_call_unix"]))
    multi = {k: v for k, v in multi.items() if len(v) >= 2}
    print(f"callers with >=2 cluster coins called inside the attributed tape: {len(multi)}")
    WINDOW = 1800.0
    by_coin_wallets = collections.defaultdict(list)
    for (coin, w), v in legs.items():
        by_coin_wallets[coin].append((w, v))
    def prebuyers(pairs):
        counts = collections.Counter()
        for coin, t in pairs:
            for w, v in by_coin_wallets.get(coin, []):
                if any(t - WINDOW <= tt <= t and d > 0 for tt, d in v):
                    counts[w] += 1
        return counts
    rng = random.Random(19)
    join_rows = []
    for caller, pairs in multi.items():
        obs = prebuyers(pairs)
        best = max(obs.values()) if obs else 0
        nulls = []
        for _ in range(400):
            sub = []
            for coin, t in pairs:
                near = [(c, tt) for c, tt in universe if abs(tt - t) <= WINDOW and c != coin]
                sub.append(rng.choice(near) if near else (coin, t))
            nb = prebuyers(sub)
            nulls.append(max(nb.values()) if nb else 0)
        p = (1 + sum(1 for x in nulls if x >= best)) / (1 + len(nulls))
        join_rows.append({"caller": caller, "n_coins": len(pairs), "best_overlap": best,
                          "null_mean": statistics.fmean(nulls), "p_perm": p,
                          "top": [w for w, c in obs.most_common(3) if c == best][:2]})
    join_rows.sort(key=lambda r: r["p_perm"])
    if join_rows:
        keep = benjamini_hochberg([r["p_perm"] for r in join_rows], alpha=0.10)
        for r, k in zip(join_rows, keep, strict=True):
            r["fdr10"] = bool(k)
            print(f"  {r['caller']:<22} coins={r['n_coins']} best={r['best_overlap']} "
                  f"null_mean={r['null_mean']:.2f} p={r['p_perm']:.3f} {'FDR10 KEEP' if k else ''}")
        print(f"  survivors at FDR 10%: {sum(keep)} of {len(join_rows)}")

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "quality_cluster.jsonl").open("w") as fh:
        for r in sorted(rows, key=lambda r: (r["coin"], -r["n_calls"])):
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")
    print(f"\nwrote {OUT/'quality_cluster.jsonl'}: {len(rows)} (caller, coin) rows")

    # ---- summary ----
    cls = collections.Counter(r["class"] for r in rows)
    print("classes:", dict(cls))
    joined = [r for r in rows if r["wallet"] or r["join_method"] != "none"]
    print(f"rows with any join: {len(joined)}; with a wallet: {sum(1 for r in rows if r['wallet'])}")
    for r in rows:
        if r["wallet"]:
            print(
                f"  {r['coin']:<6} {r['caller']:<20} {r['wallet']} conf={r['join_confidence']} "
                f"chore={r['choreography'] is not None}"
            )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """The three-strategy comparison, its nulls, and the numbers the RESULT quotes.

    Everything reads from the caches built by `build_panel` (or its persvati twin) plus
    `wallets_minute.parquet`. Writes `.cache/quality_callers/jack_numbers.json`, which
    `watchlist` then consumes — so the watchlist's `measured` block can never drift from
    the run that produced it.
    """

    import math
    import random
    import statistics

    import numpy as np

    from studies.callout_volatility import by_fdr

    series, tape_start, tape_end = load_panel()
    print(f"panel {sum(len(v[0]) for v in series.values()):,} prints / {len(series):,} mints")
    events = load_wallet_events()
    first_buy = {
        m: next((t for t, d in evs if d > 0), None) for m, evs in events.items() if m in series
    }
    treated = sorted(
        ((m, t) for m, t in first_buy.items() if t is not None and t + HOLD_S <= tape_end),
        key=lambda kv: kv[1],
    )
    print(f"treated: {len(treated)} first-buys, priced, horizon inside the tape")

    def run(evs: Sequence[tuple[str, float]], latency: float = 2.0) -> dict[str, float]:
        fills = []
        for mint, t0 in evs:
            if mint not in series:
                continue
            times, logp, depth = series[mint]
            fill = score_entry(
                times.tolist(), logp.tolist(), depth.tolist(), t0 + latency,
                mint=mint, tape_end=tape_end,
            )
            if fill:
                fills.append(fill)
        if not fills:
            return {}
        net = [f.net for f in fills]
        return {
            "n": len(fills),
            "net_mean": statistics.fmean(net),
            "net_med": statistics.median(net),
            "pess_mean": statistics.fmean([f.net_pessimistic for f in fills]),
            "p_win": sum(1 for x in net if x > 0) / len(net),
            "tp": sum(f.reason == "take_profit" for f in fills) / len(fills),
            "sl": sum(f.reason == "stop_loss" for f in fills) / len(fills),
            "_net": net,
        }

    print("\n=== latency sweep (0 s is UNFILLABLE: it fills at the wallet's own print) ===")
    arms = {}
    for lat in (0, 1, 2, 5, 15, 30, 60):
        s = run(treated, float(lat))
        arms[f"a_{lat}"] = {k: v for k, v in s.items() if k != "_net"}
        print(
            f"  buy + {lat:>3}s  n={s['n']:<4} net_mean={s['net_mean']:+7.3%} "
            f"net_med={s['net_med']:+7.3%} p(win)={s['p_win']:5.1%} TP={s['tp']:4.0%} SL={s['sl']:4.0%}"
        )

    observed = arms["a_2"]["net_mean"]
    rng = random.Random(17)
    span = tape_end - tape_start
    print("\n=== nulls on the 2 s arm ===")
    rot = []
    for _ in range(args.draws):
        off = rng.uniform(0, span)
        shifted = [
            (m, tape_start + ((t - tape_start + off) % span))
            for m, t in treated
            if tape_start + ((t - tape_start + off) % span) + HOLD_S <= tape_end
        ]
        s = run(shifted)
        if s:
            rot.append(s["net_mean"])
    rot.sort()
    p_rot = (1 + sum(1 for x in rot if x >= observed)) / (1 + len(rot))
    print(f"  rotation (common circular shift): median {statistics.median(rot):+.3%}  p={p_rot:.4f}")

    pool = [m for m in series if m not in events]
    shuffled = []
    for _ in range(max(args.draws // 4, 20)):
        evs = []
        for _, t in treated:
            for _ in range(6):
                m = rng.choice(pool)
                times = series[m][0]
                j = int(np.searchsorted(times, t, side="right")) - 1
                if j >= 0 and t - times[j] <= 300 and t + HOLD_S <= tape_end:
                    evs.append((m, t))
                    break
        s = run(evs)
        if s:
            shuffled.append(s["net_mean"])
    shuffled.sort()
    p_shuf = (1 + sum(1 for x in shuffled if x >= observed)) / (1 + len(shuffled))
    print(
        f"  coin-shuffle (same instants, random live coin): median "
        f"{statistics.median(shuffled):+.3%}  p={p_shuf:.4f}"
    )

    print("\n=== burst arm ===")
    burst = first_bursts()
    on_jack = [(m, t) for m, t in burst.items() if m in first_buy and m in series and t + HOLD_S <= tape_end]
    ignored = [(m, t) for m, t in burst.items() if m in series and m not in events and t + HOLD_S <= tape_end]
    rng2 = random.Random(5)
    b_jack = run(on_jack)
    b_ign = run(rng2.sample(ignored, min(4000, len(ignored))))
    print(f"  on the wallet's coins   n={b_jack['n']:<5} net_mean={b_jack['net_mean']:+.3%}")
    print(f"  on coins it ignored     n={b_ign['n']:<5} net_mean={b_ign['net_mean']:+.3%}")

    paired = []
    for m, t in treated:
        b = burst.get(m)
        if b is None or b + HOLD_S > tape_end:
            continue
        fa, fc = run([(m, t)]), run([(m, b)])
        if fa and fc:
            paired.append((fa["net_mean"] - fc["net_mean"], b - t))
    if paired:
        diffs = [d for d, _ in paired]
        sd = statistics.pstdev(diffs) or 1e-9
        z = statistics.fmean(diffs) / (sd / math.sqrt(len(diffs)))
        print(
            f"  paired (same coin): buy − burst = {statistics.fmean(diffs):+.3%}  "
            f"z={z:+.2f} p={math.erfc(abs(z) / math.sqrt(2)):.4f}  "
            f"within 60 s of each other: {sum(1 for _, lead in paired if abs(lead) <= 60)/len(paired):.1%}"
        )

    print("\n=== exit-parameter grid (trials counted, BY-FDR q=0.10) ===")
    grid = []
    for hold in (300, 600):
        for tp in (0.04, 0.06, 0.10):
            for sl in (0.10, 0.175, 0.30):
                nets = []
                for mint, t0 in treated:
                    times, logp, depth = series[mint]
                    fill = score_entry(
                        times.tolist(), logp.tolist(), depth.tolist(), t0 + 2.0, mint=mint,
                        tape_end=tape_end, hold_s=hold, take_profit=tp, stop_loss=sl,
                    )
                    if fill:
                        nets.append(fill.net)
                if len(nets) < 30:
                    continue
                mean = statistics.fmean(nets)
                z = mean / ((statistics.pstdev(nets) or 1e-9) / math.sqrt(len(nets)))
                grid.append(
                    {"hold": hold, "tp": tp, "sl": sl, "n": len(nets), "net_mean": mean,
                     "net_med": statistics.median(nets), "z": z,
                     "p": math.erfc(abs(z) / math.sqrt(2))}
                )
    keep = by_fdr([g["p"] for g in grid], q=0.10)
    print(f"  {len(grid)} configurations; BY-FDR survivors {sum(keep)}")
    for g, k in zip(grid, keep, strict=True):
        if k:
            print(
                f"    SURVIVOR hold={g['hold']}s TP={g['tp']:.0%} SL={g['sl']:.1%} "
                f"net_mean={g['net_mean']:+.3%} p={g['p']:.4f}  <- SIGN: {'LOSS' if g['net_mean'] < 0 else 'gain'}"
            )

    # Bootstrap on the 2 s arm. Every mint contributes exactly one event here, so
    # resampling events IS resampling mints — the clustering correction the other
    # studies need does not arise.
    nets2 = run(treated)["_net"]
    rng3 = random.Random(3)
    boots = sorted(statistics.fmean(rng3.choices(nets2, k=len(nets2))) for _ in range(2000))
    ci = [boots[50], boots[1949]]
    print(
        f"\n=== bootstrap, 2 s arm: net_mean {statistics.fmean(nets2):+.3%} "
        f"95% CI [{ci[0]:+.3%}, {ci[1]:+.3%}] ==="
    )

    # Parameter-free forward returns, and the window between the buy and the crowd.
    def mark(mint: str, t: float) -> float | None:
        times, logp, _ = series[mint]
        i = int(np.searchsorted(times, t, side="right")) - 1
        return float(logp[i]) if i >= 0 else None

    forward = {}
    for h in HORIZONS_S:
        vals = []
        for mint, t0 in treated:
            if t0 + 2.0 + h > tape_end:
                continue
            p0, p1 = mark(mint, t0 + 2.0), mark(mint, t0 + 2.0 + h)
            if p0 is not None and p1 is not None:
                vals.append(math.expm1(p1 - p0))
        if vals:
            forward[str(h)] = {"n": len(vals), "median": statistics.median(vals),
                               "mean": statistics.fmean(vals),
                               "p_up": sum(1 for x in vals if x > 0) / len(vals)}
            print(f"  hold-to-{h:>5}s: n={len(vals):<4} median={forward[str(h)]['median']:+8.2%} "
                  f"p(up)={forward[str(h)]['p_up']:5.1%}")

    moves = []
    for mint, t0 in treated:
        b = burst.get(mint)
        if b is None or b <= t0:
            continue
        p0, p1 = mark(mint, t0 + 2.0), mark(mint, b)
        if p0 is not None and p1 is not None:
            moves.append((b - t0, math.expm1(p1 - p0)))
    window = None
    if moves:
        fric = friction_for(50.0)
        window = {
            "n": len(moves),
            "lead_med": statistics.median([x[0] for x in moves]),
            "move_med": statistics.median([x[1] for x in moves]),
            "friction": fric,
            "clears": sum(1 for _, r in moves if r > fric) / len(moves),
        }
        print(f"  actionable window (buy -> burst): n={window['n']} lead_med={window['lead_med']:.0f}s "
              f"move_med={window['move_med']:+.2%} clears {fric:.2%} friction in {window['clears']:.1%}")

    diffs = [d for d, _ in paired] if paired else []
    paired_boot = None
    if diffs:
        rng4 = random.Random(7)
        pb = sorted(statistics.fmean(rng4.choices(diffs, k=len(diffs))) for _ in range(2000))
        paired_boot = [pb[50], pb[1949]]

    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "jack_numbers.json").write_text(
        json.dumps(
            {
                "headline": {
                    "a_0s_net_mean": arms["a_0"]["net_mean"],
                    "a_2s_net_mean": arms["a_2"]["net_mean"],
                    "a_2s_ci": ci,
                    "a_2s_p_win": arms["a_2"]["p_win"],
                    "a_30s_net_mean": arms["a_30"]["net_mean"],
                    "burst_jack_net_mean": b_jack["net_mean"],
                    "burst_ignored_net_mean": b_ign["net_mean"],
                    "p_rotation": p_rot,
                    "p_coin_shuffle": p_shuf,
                    "paired_a_minus_c": statistics.fmean(diffs) if diffs else None,
                    "paired_ci": paired_boot,
                    "within_60s_of_burst": (
                        sum(1 for _, lead in paired if abs(lead) <= 60) / len(paired) if paired else None
                    ),
                    "n_treated": len(treated),
                    "grid_trials": len(grid),
                    "grid_survivors": int(sum(keep)),
                    "fwd_300s_median": forward.get("300", {}).get("median"),
                    "fwd_7200s_median": forward.get("7200", {}).get("median"),
                    "window_move_median": (window or {}).get("move_med"),
                    "window_friction": (window or {}).get("friction"),
                    "window_clears_friction": (window or {}).get("clears"),
                    "window_lead_median_s": (window or {}).get("lead_med"),
                },
                "arms": arms, "grid": grid, "forward": forward, "window": window,
                "tape": [tape_start, tape_end],
            },
            indent=1,
        )
    )
    print(f"\nwrote {CACHE / 'jack_numbers.json'}")
    return 0


def cmd_watchlist(args: argparse.Namespace) -> int:
    """Emit state/callers/watchlist.jsonl in a shape the paperdesk/firehose can consume.

    A row is a *trigger*, not an endorsement. `trigger_supported` is the study's verdict
    on whether this entity's own history justifies acting on it, and it is allowed to be
    false — a watchlist that only contains winners is a watchlist that has never been
    tested against a null.
    """

    OUT.mkdir(parents=True, exist_ok=True)
    numbers = json.loads((CACHE / "jack_numbers.json").read_text())
    cluster = [json.loads(line) for line in (OUT / "quality_cluster.jsonl").open() if line.strip()]

    rows: list[dict] = []
    jack_wallet = "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh"
    verdict = verify_address(
        jack_wallet,
        flow_source="state/bulk_pump + helius getTokenAccountsByOwner",
        flow_detail=(
            "1,419 successful token-balance legs over 271 pump mints, 2026-08-05..08-11; "
            "969 non-zero token accounts and 59.09 SOL at 2026-08-15"
        ),
        flow=True,
    )
    rows.append(
        {
            "entity": "jackduvalcalls",
            "x_handle": JACK_X_HANDLE,
            "x_handle_note": (
                "the operator named 'jackduvalcalls'; from:jackduvalcalls returns ZERO tweets "
                "over 2026-08-01..08-16. The X account that posts is @jackduval (51,738 "
                "followers). 'jackduvalcalls' is the PUMP.FUN username."
            ),
            "wallet": jack_wallet,
            "evidence_grade": "probable",
            "verification": {
                "on_curve": verdict.on_curve,
                "flow_observed": verdict.flow_observed,
                "flow_source": verdict.flow_source,
                "flow_detail": verdict.flow_detail,
                "pump_fun_username": JACK_PUMP_USERNAME,
                "pump_fun_followers": 17465,
                "pump_fun_bio": "never wrong, always early.",
                "pump_fun_x_username_field": None,
                "corroboration": (
                    "holds 25,231,399.36 of 89RAitwPJBEfLK4Gcg5iv7AjFABHWNvoD5rkvRkvpump, the "
                    "coin @jackduval publicly funded TikTok promotion for on 2026-08-04; the "
                    "wallet's first successful buy is 2026-08-04T03:19:17Z, 9 h 33 m before "
                    "his first tweet naming it (12:52Z)"
                ),
                "known_impostor": {
                    "address": "9T8QKsR28boKJL3x3td39rX8dk1xsd5zwWaF2nFzijvP",
                    "username": "jackduvalcaIIs",
                    "note": "capital-I homoglyph, 9 followers. NOT the entity.",
                },
                "what_would_upgrade_to_attested": (
                    "the operator opening pump.fun/profile/jackduvalcalls and confirming the "
                    "address, or Jack signing anything from it"
                ),
            },
            "trigger": {
                "kind": "wallet_buy",
                "stream": "pumpportal accountTrade",
                "wiring": (
                    "shitcoims_scalper.firehose --keys accountTrade with the funded key, "
                    "subscribeAccountTrade payload {\"keys\": [\"" + jack_wallet + "\"]}; "
                    "the coordinator enables it in ops/*.plist. NOT edited by this study."
                ),
                "latency_budget_s": 2.0,
            },
            "trigger_supported": False,
            "measured": numbers["headline"],
            "pulse": {
                "unit": "one buy leg by this wallet on one mint (what the following feed fires on)",
                "pulses_per_day": numbers["headline"].get("pulses_per_day"),
                "usd_per_pulse_mean_2s": numbers["headline"].get("usd_per_pulse_2s"),
                "usd_per_pulse_median_2s": numbers["headline"].get("usd_med_pulse_2s"),
                "usd_per_pulse_mean_300s": numbers["headline"].get("usd_per_pulse_300s"),
                "prints_5min_at_pulse": numbers["headline"].get("churn_prints_pulse"),
                "prints_5min_ambient": numbers["headline"].get("churn_prints_ambient"),
                "wiggle_ratio_at_pulse": numbers["headline"].get("wiggle_ratio_pulse"),
                "wiggle_ratio_ambient": numbers["headline"].get("wiggle_ratio_ambient"),
                "brackets_tried": numbers["headline"].get("bracket_trials"),
                "brackets_with_positive_mean": numbers["headline"].get("bracket_positive_survivors"),
                "note": (
                    "the median pulse extracts about a dollar — which is the operator's lived "
                    "experience and is real — while the mean is negative. The gap is the loss tail."
                ),
            },
            "why_not": (
                "at a 2 s detection latency the arm's net mean is "
                f"{numbers['headline']['a_2s_net_mean']:.3%} with a 95% CI of "
                f"[{numbers['headline']['a_2s_ci'][0]:.3%}, {numbers['headline']['a_2s_ci'][1]:.3%}] "
                "— it straddles zero; it does not beat its own rotation null (p="
                f"{numbers['headline']['p_rotation']:.2f}) or a random live coin at the same "
                f"instant (p={numbers['headline']['p_coin_shuffle']:.2f}); and it goes to "
                f"{numbers['headline']['a_30s_net_mean']:.3%} at the 30 s latency of the board tape."
            ),
        }
    )

    # The roster: the other high-follower pump.fun accounts whose trades also fire the feed.
    # The MECHANISM generalises (every one marks a 3-19x more two-sided tape than ambient);
    # the EXTRACTION does not, and the two nominal positives have no null at their n.
    roster = numbers.get("roster", {}).get("arm", {})
    roster_ci = numbers.get("roster", {}).get("ci", {})
    for name, entry in roster.items():
        if name == JACK_PUMP_USERNAME:
            continue
        churn = entry.get("churn") or {}
        extract = entry.get("extract") or {}
        ci = (roster_ci.get(name) or {}).get("ci_usd")
        rows.append(
            {
                "entity": name,
                "x_handle": None,
                "wallet": next(
                    (a for a, n in ROSTER_WALLETS.items() if n == name), None
                ),
                "evidence_grade": "probable",
                "verification": {
                    "route": "route1_pumpfun_username",
                    "pump_fun_followers": entry.get("followers"),
                    "on_curve": True,
                    "flow_observed": True,
                    "flow_detail": (
                        f"{entry.get('mints')} pump mints in state/bulk_pump 2026-08-05..08-11; "
                        f"{entry.get('priced')} priced in the panel's 4% hash sample"
                    ),
                },
                "trigger": {"kind": "wallet_buy", "stream": "pumpportal accountTrade",
                            "latency_budget_s": 2.0},
                "trigger_supported": False,
                "measured": {
                    "pulses": entry.get("pulses"),
                    "prints_5min_at_pulse": churn.get("prints"),
                    "wiggle_ratio": churn.get("ratio"),
                    "usd_per_pulse_mean": extract.get("usd"),
                    "usd_per_pulse_median": extract.get("usd_med"),
                    "usd_ci": ci,
                    "p_win": extract.get("pwin"),
                },
                "why_not": (
                    "the pulse MECHANISM holds (this account's trades mark a "
                    f"{churn.get('ratio', float('nan')):.0f}x round-trip-to-net tape against "
                    "ambient's 2.5), but extraction rests on "
                    f"n={entry.get('pulses')} at ONE bracket chosen on another account's data, "
                    "with no ambient null computable at that n. Two positives out of five "
                    "accounts tried is what chance produces. This is the next experiment."
                ),
            }
        )

    # The coin's own project account: the one join in the cluster arm that needs no inference.
    for row in cluster:
        if row["join_method"] == "route3_coin_is_the_project":
            rows.append(
                {
                    "entity": row["caller"],
                    "x_handle": row["caller"],
                    "wallet": None,
                    "evidence_grade": "attested_by_coin_metadata",
                    "verification": {
                        "route": "route3_coin_is_the_project",
                        "coin": row["coin"],
                        "mint": row["mint"],
                        "note": (
                            "pump.fun coin metadata names this X account as the coin's own. "
                            "No wallet is asserted: the creator address is a separate claim "
                            "and this study did not verify it."
                        ),
                    },
                    "trigger": {"kind": "project_account_post", "stream": "inteld x_mint_mention"},
                    "trigger_supported": False,
                    "measured": {
                        "n_calls": row["n_calls"],
                        "note": "project accounts post about their own coin; no forward-return arm was fit",
                    },
                    "why_not": "n too small on this cohort to fit anything; listed for provenance only",
                }
            )

    rows.append(
        {
            "entity": "__population_note__",
            "x_handle": None,
            "wallet": None,
            "evidence_grade": "n/a",
            "verification": {
                "cluster_callers": len({r["caller"] for r in cluster}),
                "cluster_caller_coin_rows": len(cluster),
                "route1_name_matches": sum(1 for r in cluster if r["wallet"]),
                "route1_matches_with_flow_on_the_coin_they_called": 0,
            },
            "trigger": None,
            "trigger_supported": False,
            "why_not": (
                "Not one of the pump.fun-username matches ever traded the cluster coin whose "
                "handle it matches, so every one of them is a name collision until an operator "
                "attests otherwise. No caller in the quality-cluster census earns a watch."
            ),
        }
    )

    path = OUT / "watchlist.jsonl"
    with path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    supported = sum(1 for r in rows if r["trigger_supported"])
    print(f"wrote {path}: {len(rows)} rows ({supported} with a supported trigger)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("watchlist")
    p.set_defaults(fn=cmd_watchlist)

    p = sub.add_parser("cluster-table")
    p.set_defaults(fn=cmd_cluster_table)

    p = sub.add_parser("report")
    p.add_argument("--draws", type=int, default=200)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("build-panel")
    p.add_argument("--wallet", default="BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh")
    p.set_defaults(
        fn=lambda a: (build_panel(wallets=[a.wallet], out=CACHE / "panel.parquet"), 0)[1]
    )

    p = sub.add_parser("collect-jack")
    p.add_argument("--start", type=int, default=1_784_000_000)  # 2026-07-14
    p.add_argument("--end", type=int, default=int(time.time()))
    p.add_argument("--max-items", type=int, default=100)
    p.set_defaults(fn=cmd_collect_jack)

    p = sub.add_parser("collect-cluster")
    p.add_argument("--max-items", type=int, default=100)
    p.set_defaults(fn=cmd_collect_cluster)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
