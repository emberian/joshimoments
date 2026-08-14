#!/usr/bin/env python3
"""The control arm for the operator's "survival filter".

studies/RESULT_lp_history.md records the operator's claimed edge as a *survival* filter --
"the team is real, the dev is a chad" -- and scores it 12 tokens touched, 9 alive, 3 dying,
0 dead. Against a population where most of these tokens die in a day that reads as strong.
It is not evidence, for two reasons that this file exists to remove:

  1. There is no counterfactual. "12 for 12" is unfalsifiable without the population the
     picks were drawn FROM, measured over the SAME window. PROGRAM.md section 5 lists
     "no control group" as one of the four reasons the LP result is not yet evidence.
  2. The population figure it was scored against came from a paper, and the pump.fun
     graduation base rate moved >25x in 30 months (PROGRAM.md section 3.6, section 5.3).
     A base rate from another regime is a historical fact, not a null.

So: build the counterfactual from chain, over the operator's own window, and test.

WHAT THE UNIVERSE IS, AND WHY
-----------------------------
The choice of universe IS the experiment. Three are computed here; the primary one is U1.

  U1  PUMP.FUN GRADUATES (primary).  Every pump.fun token whose bonding curve completed and
      whose PumpSwap pool was created inside the window, enumerated from chain -- the
      migration authority 39azUY... emits exactly one CREATE_POOL per graduation, with the
      standardised ~85 SOL / 206.9M token deposit. Graduation is the chain event that makes
      a token LP-able off the curve, i.e. the moment it enters the set the operator could
      actually have chosen. Complete census, chain time, no API ranking anywhere in the
      path, and no survivorship in the frame: a token that graduated and died an hour later
      is in it.

  U0  ALL PUMP.FUN LAUNCHES (alternative, deliberately unfair to the null).  Read from the
      tape's launch cohort frame. ~98-99% of launches never graduate, so scoring the filter
      against U0 credits it for a screen every LP on Solana passes for free -- you cannot LP
      a token with no pool. Reported to show exactly how much the "godlike filter" reading
      is manufactured by the universe choice.

  U2  SEASONED-MATCHED GRADUATES (the confound arm).  U1, but each operator pick is scored
      only against graduates that had reached the SAME AGE the pick had when the operator
      bought it. This is the left-truncation correction and it is the whole ballgame: the
      operator does not buy fresh graduates. Their median pick was already days old, one was
      231 days old. A token that is 20 days past graduation has already survived the part of
      the curve where everything dies, and crediting the filter for that is crediting it for
      arithmetic.

WHAT IS MEASURED
----------------
Outcome per mint, at one observation time, from DexScreener (max-liquidity Solana pair):
liquidity_usd, 24h volume, pair creation time. Status thresholds are stated at the point of
use and swept -- PROGRAM.md section 3.7, there is no ground truth for "dead" in this field.

Sources, in order of trust:
  1. chain, via Helius -- the graduation census, the operator's transactions, all timestamps.
  2. DexScreener -- current liquidity / 24h volume. The only outcome source.
  3. pump.fun frontend API -- bonding-curve creation time and completion flag, used for the
     time-on-curve covariate. Never used for enumeration: it ranks, and ranking is
     survivorship.

Mints only, never symbols. There are two live tokens called "nosis" in the operator's own
book and they are not the same token.

Run:
  python studies/control_arm.py --collect        # network; caches under .cache/control_arm
  python studies/control_arm.py                  # offline analysis over the cache
  python studies/control_arm.py --json           # machine-readable
  python studies/control_arm.py --seed 20260814  # sampling seed (default 20260814)
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
import math
import os
import random
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, ".cache", "control_arm")

OPERATOR_WALLET = "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"
# pump.fun's migration authority. Every bonding-curve completion routes its ~85 SOL /
# 206.9M token deposit through this account and emits one PumpSwap CREATE_POOL.
PUMPFUN_MIGRATION_AUTHORITY = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"

WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
QUOTE_MINTS = frozenset({WSOL, USDC, USDT})

# The operator's LP window, from the wallet's own first and last transaction (chain time).
WINDOW_START = dt.datetime(2026, 7, 18, 0, 0, tzinfo=dt.UTC)
WINDOW_END = dt.datetime(2026, 8, 14, 4, 0, tzinfo=dt.UTC)
# The census reaches further back than the window because operator picks are SEASONED: to
# score a pick that was 55 days past graduation when it was bought, the control cohort has
# to contain tokens that are 55 days past graduation.
CENSUS_START = dt.datetime(2026, 5, 30, 0, 0, tzinfo=dt.UTC)

UA = "joshibot-research/1.0 (control-arm study; read-only)"

# Helius credit accounting. Enhanced Transactions calls are billed per call and return up to
# 100 parsed transactions; standard JSON-RPC is billed per call. Both rates are stated so the
# ledger can be checked rather than believed.
CREDITS_ENHANCED_CALL = 10
CREDITS_RPC_CALL = 1


# --------------------------------------------------------------------------------------
# status thresholds
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Thresholds:
    """Where "dead" is drawn. Swept in the sensitivity grid; nothing here is ground truth.

    `dead_liq` / `dead_vol` reproduce studies/scripts survival.py so the headline number is
    comparable to the one in RESULT_lp_history.md; `dying_liq` / `dying_vol` likewise.
    """

    dead_liq: float = 1_000.0
    dead_vol: float = 100.0
    dying_liq: float = 10_000.0
    dying_vol: float = 1_000.0


DEAD, DYING, ALIVE = "dead", "dying", "alive"


def classify(
    liquidity_usd: float | None,
    volume_24h_usd: float | None,
    th: Thresholds,
    *,
    has_market: bool = True,
) -> str:
    """Status of one mint at observation time.

    `has_market=False` -- DexScreener lists no pair at all -- is DEAD. Verified against an
    independent source before it was trusted: of twelve sampled graduates with no DexScreener
    pair, eleven had a pump.fun market cap under $2k and none had traded that day.

    `liquidity_usd=None` with a market means the pair exists but reports no liquidity figure,
    which is what DexScreener does for a token still on its pump.fun bonding curve. Calling
    that DEAD would have buried a token doing $13k a day in trades, so it is scored on volume
    alone and the liquidity rung is skipped.
    """
    if not has_market:
        return DEAD
    vol = 0.0 if volume_24h_usd is None else volume_24h_usd
    if liquidity_usd is None:
        if vol < th.dead_vol:
            return DEAD
        return DYING if vol < th.dying_vol else ALIVE
    if liquidity_usd < th.dead_liq or vol < th.dead_vol:
        return DEAD
    if liquidity_usd < th.dying_liq or vol < th.dying_vol:
        return DYING
    return ALIVE


def survived(status: str, strict: bool) -> bool:
    """`strict` counts DYING as a failure. The operator's claim is about death, so the
    primary reading is strict=False; both are reported."""
    return status == ALIVE if strict else status != DEAD


# --------------------------------------------------------------------------------------
# exact tests, in pure python (this tree has no scipy)
# --------------------------------------------------------------------------------------


def log_choose(n: int, k: int) -> float:
    if k < 0 or k > n:
        return -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_exact_greater(a: int, b: int, c: int, d: int) -> float:
    """One-sided Fisher's exact p for the 2x2 table [[a, b], [c, d]].

    Returns P(X >= a) under the hypergeometric null with both margins fixed -- i.e. the
    probability of a survival record at least this good for the picks arm by chance.
    """
    if min(a, b, c, d) < 0:
        raise ValueError("counts must be non-negative")
    n = a + b + c + d
    if n == 0:
        return 1.0
    row1, col1 = a + b, a + c
    hi = min(row1, col1)
    den = log_choose(n, col1)
    total = 0.0
    for x in range(a, hi + 1):
        total += math.exp(log_choose(row1, x) + log_choose(n - row1, col1 - x) - den)
    return min(1.0, max(0.0, total))


def poisson_binomial_pmf(ps: Sequence[float]) -> list[float]:
    """Distribution of the number of successes among independent trials with unequal p.

    This is the null for the matched comparison: each operator pick has its OWN survival
    probability under the null, because each was bought at a different token age.
    """
    dp = [1.0]
    for p in ps:
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"probability out of range: {p}")
        nxt = [0.0] * (len(dp) + 1)
        for k, v in enumerate(dp):
            nxt[k] += v * (1.0 - p)
            nxt[k + 1] += v * p
        dp = nxt
    return dp


def poisson_binomial_at_least(ps: Sequence[float], k: int) -> float:
    """P(successes >= k). The exact one-sided p-value for the matched design."""
    pmf = poisson_binomial_pmf(ps)
    return min(1.0, max(0.0, sum(pmf[max(0, k) :])))


def picks_needed_perfect(p_null: float, alpha: float = 0.05) -> int | None:
    """How many picks a PERFECT record needs before it clears `alpha`.

    Under the null each pick survives independently with probability `p_null`, so a run of k
    survivors has p = p_null**k. Returns the smallest k with p_null**k <= alpha; None when
    the null survival probability is 1 (no record length can ever be significant).
    """
    if p_null >= 1.0:
        return None
    if p_null <= 0.0:
        return 1
    return math.ceil(math.log(alpha) / math.log(p_null))


def picks_needed_fisher(control_alive: int, control_n: int, alpha: float = 0.05) -> int | None:
    """Same question against a FINITE control arm, via Fisher's exact.

    `picks_needed_perfect` treats the base rate as known exactly. It is not -- it is estimated
    from `control_n` observations, and Fisher's exact pays for that. Returns the smallest k
    such that k picks with a perfect record beat `alpha`.
    """
    if control_n <= 0:
        return None
    dead = control_n - control_alive
    if dead == 0:
        return None
    for k in range(1, 2001):
        if fisher_exact_greater(k, 0, control_alive, dead) <= alpha:
            return k
    return None


def benjamini_hochberg(pvals: Sequence[float]) -> list[float]:
    """BH-adjusted p-values, order preserved."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    running = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        running = min(running, pvals[i] * m / (rank + 1))
        adj[i] = min(1.0, running)
    return adj


def permutation_test_mean_diff(
    xs: Sequence[float], ys: Sequence[float], *, rounds: int, rng: random.Random
) -> tuple[float, float]:
    """Two-sided permutation test on the difference in means. Returns (observed_diff, p).

    Deterministic given `rng`. Used for the size-confound comparison, where the covariates
    are heavy-tailed enough that a t-test would be a lie.
    """
    if not xs or not ys:
        return (float("nan"), 1.0)
    obs = sum(xs) / len(xs) - sum(ys) / len(ys)
    pool = list(xs) + list(ys)
    n = len(xs)
    hits = 0
    for _ in range(rounds):
        rng.shuffle(pool)
        diff = sum(pool[:n]) / n - sum(pool[n:]) / (len(pool) - n)
        if abs(diff) >= abs(obs) - 1e-12:
            hits += 1
    return (obs, (hits + 1) / (rounds + 1))


# --------------------------------------------------------------------------------------
# survival curve from a cross-section
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Cohort:
    """One token in the control universe, aged from its own graduation."""

    mint: str
    grad_ts: int
    age_days: float
    status: str
    liquidity_usd: float | None
    volume_24h_usd: float | None
    mig_sol: float
    curve_days: float | None  # graduation time minus bonding-curve creation time
    has_market: bool = True
    mig_tokens: float = 0.0


def wilson_upper(alive: int, n: int, z: float = 1.645) -> float:
    """One-sided upper confidence limit on a binomial rate (Wilson score interval).

    Needed because a bin with zero survivors gives a POINT estimate of S = 0, and a null that
    says "certain death" turns any survivor at all into infinite evidence -- the study would
    report p = 0 off eighteen observations. The null is therefore built from the upper limit,
    which is the strongest survival the control data will support, so the arm has to beat the
    best case for chance rather than the point estimate.
    """
    if n <= 0:
        return 1.0
    p = alive / n
    z2 = z * z
    centre = p + z2 / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return min(1.0, (centre + half) / (1 + z2 / n))


def survival_curve(
    cohort: Iterable[Cohort], *, strict: bool, edges: Sequence[float], upper_bound: bool = False
) -> list[tuple[float, int, float]]:
    """S(age) read off the cross-section, as [(bin_mid_days, n_in_bin, fraction_alive)].

    THE ASSUMPTION, stated because it is the load-bearing one: a memecoin's death is
    absorbing. Nobody re-adds liquidity to a token that lost it, so a token observed alive at
    age A was alive at every age below A. Each token contributes to exactly ONE point -- the
    bin its own age falls in -- so the estimate at age A is the alive-fraction of an age-A
    cohort and nothing else. This is a current-status (cross-sectional) estimator, not
    Kaplan-Meier; it needs no death times, which we do not have.

    THE PRICE, also stated: it conflates age with calendar. A token that is 60 days past
    graduation both had 60 days to die AND graduated in a different market regime. The
    regime split in the output is there to check whether that matters over this census.

    `upper_bound=True` reports the one-sided 95% upper limit per bin instead of the point
    estimate. Use it for the NULL; use the point estimate for the picture.
    """
    rows = list(cohort)
    out: list[tuple[float, int, float]] = []
    for lo, hi in itertools.pairwise(edges):
        band = [c for c in rows if lo <= c.age_days < hi]
        mid = (lo + hi) / 2.0
        if not band:
            out.append((mid, 0, float("nan")))
            continue
        alive = sum(1 for c in band if survived(c.status, strict))
        rate = wilson_upper(alive, len(band)) if upper_bound else alive / len(band)
        out.append((mid, len(band), rate))
    return out


def isotonic_decreasing(values: Sequence[float], weights: Sequence[float]) -> list[float]:
    """Weighted pool-adjacent-violators fit of a NON-INCREASING sequence.

    This replaced a running minimum, and the swap was forced by the known-zero control in
    tests/test_control_arm.py rather than by taste. A running min takes the smallest noisy bin
    and never lets the curve back up, so on a flat true S = 0.35 with 20 noisy bins it settles
    near 0.20 -- the null then demands far fewer survivors than the truth and the instrument
    manufactures a filter out of nothing. It fired in 34 of 40 null worlds.

    PAVA is the maximum-likelihood fit under the monotonicity constraint: unbiased where the
    data already obey it, and pooling only where they do not.
    """
    if len(values) != len(weights):
        raise ValueError("values and weights must be the same length")
    kept = [i for i, w in enumerate(weights) if w > 0 and not math.isnan(values[i])]
    blocks: list[list[float]] = []  # [weighted sum, weight, points absorbed]
    for i in kept:
        blocks.append([values[i] * weights[i], float(weights[i]), 1.0])
        while len(blocks) >= 2 and blocks[-2][0] / blocks[-2][1] < blocks[-1][0] / blocks[-1][1]:
            s2, w2, c2 = blocks.pop()
            s1, w1, c1 = blocks.pop()
            blocks.append([s1 + s2, w1 + w2, c1 + c2])
    flat: list[float] = []
    for s, w, c in blocks:
        flat.extend([s / w] * int(c))
    out = [float("nan")] * len(values)
    for pos, i in enumerate(kept):
        out[i] = flat[pos]
    return out


def conditional_survival(curve: Sequence[tuple[float, int, float]], a: float, b: float) -> float:
    """P(alive at age b | alive at age a) = S(b)/S(a), clamped to [0, 1].

    Monotone-corrected by isotonic regression before the ratio is taken, because a finite
    cross-section wiggles and a wiggle upward would produce a conditional survival above 1
    and silently break the null.
    """
    if b <= a:
        return 1.0
    pts = [p for p in curve if p[1] > 0 and not math.isnan(p[2])]
    if not pts:
        return 1.0
    ages = [p[0] for p in pts]
    mono = isotonic_decreasing([p[2] for p in pts], [float(p[1]) for p in pts])

    def s_at(x: float) -> float:
        if x <= ages[0]:
            return 1.0
        if x >= ages[-1]:
            return mono[-1]
        for i in range(1, len(ages)):
            if ages[i] >= x:
                lo, hi = ages[i - 1], ages[i]
                w = 0.0 if hi == lo else (x - lo) / (hi - lo)
                return mono[i - 1] + w * (mono[i] - mono[i - 1])
        return mono[-1]

    sa, sb = s_at(a), s_at(b)
    if sa <= 0.0:
        return 1.0
    return max(0.0, min(1.0, sb / sa))


# --------------------------------------------------------------------------------------
# collection (network). everything below writes to CACHE and is resumable.
# --------------------------------------------------------------------------------------


def _helius_key() -> str:
    with open(os.path.expanduser("~/.helius-key")) as fh:
        return fh.read().strip()


def _get_json(url: str, *, body: bytes | None = None, tries: int = 6, timeout: int = 120) -> Any:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            headers = {"User-Agent": UA}
            if body is not None:
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as fh:
                return json.load(fh)
        except Exception as exc:
            last = exc
            if attempt == tries - 1:
                break
            time.sleep(0.5 * 2**attempt)
    raise RuntimeError(f"GET failed after {tries} tries: {url.split('?')[0]}: {last}")


class CreditLedger:
    """Helius spend, logged as it happens rather than estimated afterwards."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.runs: list[dict[str, Any]] = []
        if os.path.exists(path):
            with open(path) as fh:
                self.runs = json.load(fh).get("runs", [])

    def log(self, stage: str, *, enhanced: int = 0, rpc: int = 0, note: str = "") -> None:
        credits = enhanced * CREDITS_ENHANCED_CALL + rpc * CREDITS_RPC_CALL
        self.runs.append(
            {
                "at": dt.datetime.now(dt.UTC).isoformat(),
                "stage": stage,
                "enhanced_calls": enhanced,
                "rpc_calls": rpc,
                "credits": credits,
                "note": note,
            }
        )
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as fh:
            json.dump({"runs": self.runs, "total_credits": self.total}, fh, indent=1)

    @property
    def total(self) -> int:
        return sum(int(r.get("credits", 0)) for r in self.runs)


def collect_operator(cache: str, ledger: CreditLedger) -> list[dict[str, Any]]:
    """Every transaction of the operator's wallet, parsed. ~6 enhanced calls."""
    path = os.path.join(cache, "wallet_enh.json")
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    key = _helius_key()
    base = f"https://api.helius.xyz/v0/addresses/{OPERATOR_WALLET}/transactions?api-key={key}&limit=100"
    out: list[dict[str, Any]] = []
    before: str | None = None
    calls = 0
    while True:
        page = _get_json(base + (f"&before={before}" if before else ""))
        calls += 1
        if not page:
            break
        out.extend(page)
        before = page[-1]["signature"]
        if len(page) < 100 or calls > 40:
            break
        time.sleep(0.1)
    with open(path, "w") as fh:
        json.dump(out, fh)
    ledger.log("operator_wallet", enhanced=calls, note=f"{len(out)} transactions")
    return out


def collect_universe(cache: str, ledger: CreditLedger, *, start: dt.datetime = CENSUS_START) -> int:
    """Census of pump.fun graduations back to `start`, from chain. Resumable.

    One row per graduation: mint, chain graduation time, the SOL and token amounts deposited
    into the new pool. The SOL deposit is the only size covariate that is observable AT
    graduation, i.e. before any outcome exists, which is what the confound check needs.
    """
    key = _helius_key()
    base = (
        f"https://api.helius.xyz/v0/addresses/{PUMPFUN_MIGRATION_AUTHORITY}/transactions"
        f"?api-key={key}&limit=100&type=CREATE_POOL"
    )
    path = os.path.join(cache, "universe_grads.jsonl")
    seen: set[str] = set()
    before: str | None = None
    if os.path.exists(path):
        rows = _read_jsonl(path)
        seen = {r["mint"] for r in rows}
        if rows:
            oldest = min(rows, key=lambda r: r["grad_ts"])
            before = oldest["sig"]
    floor = int(start.timestamp())
    calls, added = 0, 0
    with open(path, "a") as fh:
        while True:
            page = _get_json(base + (f"&before={before}" if before else ""))
            calls += 1
            if not page:
                break
            for tx in page:
                mint, sol, tok = _migration_legs(tx)
                if mint is None or mint in seen:
                    continue
                seen.add(mint)
                added += 1
                fh.write(
                    json.dumps(
                        {
                            "mint": mint,
                            "grad_ts": tx.get("timestamp"),
                            "sig": tx.get("signature"),
                            "mig_sol": sol,
                            "mig_tokens": tok,
                        }
                    )
                    + "\n"
                )
            fh.flush()
            before = page[-1]["signature"]
            if (page[-1].get("timestamp") or 0) < floor or calls > 1400:
                break
            time.sleep(0.03)
    ledger.log("universe_census", enhanced=calls, note=f"{added} new graduations, {len(seen)} total")
    return len(seen)


def _migration_legs(tx: dict[str, Any]) -> tuple[str | None, float, float]:
    """(mint, SOL deposited, tokens deposited) from one CREATE_POOL transaction."""
    sol, tok, mint = 0.0, 0.0, None
    for tt in tx.get("tokenTransfers") or []:
        m = tt.get("mint")
        amt = float(tt.get("tokenAmount") or 0)
        if m == WSOL:
            sol = max(sol, amt)
        elif m and amt > tok:
            tok, mint = amt, m
    return mint, sol, tok


def collect_dexscreener(cache: str, mints: Sequence[str], name: str) -> dict[str, list[dict[str, Any]]]:
    """Current pairs for `mints`, 30 per request. Free; DexScreener 403s the default UA."""
    path = os.path.join(cache, f"dexscreener_{name}.json")
    out: dict[str, list[dict[str, Any]]] = {}
    if os.path.exists(path):
        with open(path) as fh:
            out = json.load(fh)
    todo = [m for m in mints if m not in out]
    for i in range(0, len(todo), 30):
        chunk = todo[i : i + 30]
        url = "https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk)
        try:
            pairs = _get_json(url, timeout=60)
        except RuntimeError:
            continue
        for m in chunk:
            out.setdefault(m, [])
        for pair in pairs if isinstance(pairs, list) else []:
            addr = (pair.get("baseToken") or {}).get("address")
            if addr in out:
                out[addr].append(pair)
        if i % 900 == 0:
            with open(path, "w") as fh:
                json.dump(out, fh)
            print(f"  dexscreener[{name}] {i + len(chunk)}/{len(todo)}", flush=True)
        time.sleep(0.25)
    with open(path, "w") as fh:
        json.dump(out, fh)
    return out


def collect_pumpfun(cache: str, mints: Sequence[str], name: str) -> dict[str, dict[str, Any]]:
    """Bonding-curve creation time and completion flag per mint. Free, one call per mint."""
    path = os.path.join(cache, f"pumpfun_{name}.json")
    out: dict[str, dict[str, Any]] = {}
    if os.path.exists(path):
        with open(path) as fh:
            out = json.load(fh)
    todo = [m for m in mints if m not in out]
    browser_ua = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    )
    for n, mint in enumerate(todo):
        try:
            req = urllib.request.Request(
                f"https://frontend-api-v3.pump.fun/coins/{mint}", headers={"User-Agent": browser_ua}
            )
            with urllib.request.urlopen(req, timeout=25) as fh:
                out[mint] = json.load(fh)
        except Exception as exc:
            out[mint] = {"_err": type(exc).__name__}
        if n % 300 == 0:
            with open(path, "w") as fh:
                json.dump(out, fh)
            print(f"  pumpfun[{name}] {n}/{len(todo)}", flush=True)
        time.sleep(0.08)
    with open(path, "w") as fh:
        json.dump(out, fh)
    return out


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not os.path.exists(path):
        return rows
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# --------------------------------------------------------------------------------------
# operator arm
# --------------------------------------------------------------------------------------


@dataclass
class Touch:
    """The operator's engagement with one mint, reconstructed from wallet balance deltas."""

    mint: str
    first_ts: int
    last_ts: int
    n_transfers: int = 0
    dlmm_txs: int = 0
    held_seconds: float = 0.0
    open_balance: float = 0.0
    sources: dict[str, int] = field(default_factory=dict)


def operator_touches(txs: Sequence[dict[str, Any]]) -> dict[str, Touch]:
    """Per-mint holding record. `held_seconds` is time with a strictly positive balance.

    The distinction matters: a mint that goes in and out inside ONE transaction is a routing
    hop through somebody else's pool, not a position, and counting it as a "pick" would put
    tokens the operator never chose into the arm.
    """
    ordered = sorted(txs, key=lambda t: t.get("timestamp") or 0)
    out: dict[str, Touch] = {}
    balance: dict[str, float] = {}
    last_seen: dict[str, int] = {}
    for tx in ordered:
        ts = int(tx.get("timestamp") or 0)
        src = tx.get("source") or "?"
        for tt in tx.get("tokenTransfers") or []:
            mint = tt.get("mint")
            if not mint:
                continue
            rec = out.get(mint)
            if rec is None:
                rec = out[mint] = Touch(mint=mint, first_ts=ts, last_ts=ts)
            rec.first_ts = min(rec.first_ts, ts)
            rec.last_ts = max(rec.last_ts, ts)
            rec.n_transfers += 1
            rec.sources[src] = rec.sources.get(src, 0) + 1
            if src == "METEORA":
                rec.dlmm_txs += 1
            delta = 0.0
            amt = float(tt.get("tokenAmount") or 0)
            if tt.get("toUserAccount") == OPERATOR_WALLET:
                delta += amt
            if tt.get("fromUserAccount") == OPERATOR_WALLET:
                delta -= amt
            if delta:
                prev = balance.get(mint, 0.0)
                if prev > 1e-9 and mint in last_seen:
                    rec.held_seconds += ts - last_seen[mint]
                balance[mint] = max(0.0, prev + delta)
                last_seen[mint] = ts
    now = max((int(t.get("timestamp") or 0) for t in ordered), default=0)
    for mint, bal in balance.items():
        if bal > 1e-9 and mint in last_seen:
            out[mint].held_seconds += now - last_seen[mint]
        out[mint].open_balance = bal
    return out


def is_pumpfun_mint(mint: str) -> bool:
    """pump.fun mints carry the launchpad's own `pump` vanity suffix.

    Mechanical and checkable, which is the point: it is fixed before any outcome is looked
    at, so it cannot be tuned to drop an inconvenient token.
    """
    return mint.endswith("pump")


# --------------------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Pick:
    mint: str
    symbol: str
    entry_ts: int
    grad_ts: int | None
    status: str
    liquidity_usd: float | None
    volume_24h_usd: float | None
    dlmm: bool
    held_hours: float
    mig_sol: float | None
    curve_days: float | None

    @property
    def entry_age_days(self) -> float | None:
        if self.grad_ts is None:
            return None
        return max(0.0, (self.entry_ts - self.grad_ts) / 86400.0)


def best_pair(pairs: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    if not pairs:
        return None
    return max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0.0))


@dataclass(frozen=True)
class Market:
    """What DexScreener knows about one mint right now."""

    has_market: bool  # False == no pair listed anywhere
    liquidity_usd: float | None  # None == pair exists but reports no liquidity (bonding curve)
    volume_24h_usd: float | None
    first_pair_ms: int | None
    symbol: str


def pair_metrics(pairs: Sequence[dict[str, Any]]) -> Market:
    top = best_pair(pairs)
    if top is None:
        return Market(False, None, None, None, "?")
    liq_obj = top.get("liquidity") or {}
    liq = float(liq_obj["usd"]) if liq_obj.get("usd") is not None else None
    vol = float((top.get("volume") or {}).get("h24") or 0.0)
    created = min((p.get("pairCreatedAt") or 0) for p in pairs) or None
    sym = str((top.get("baseToken") or {}).get("symbol") or "?")
    return Market(True, liq, vol, created, sym)


@dataclass(frozen=True)
class CacheData:
    """Everything the offline analysis reads, loaded once.

    The threshold sweep re-derives the whole comparison four times over; re-reading a 40MB
    census from disk each pass turned a two-second analysis into a two-minute one.
    """

    grads: list[dict[str, Any]]
    dex_universe: dict[str, list[dict[str, Any]]]
    pf_universe: dict[str, dict[str, Any]]
    dex_operator: dict[str, list[dict[str, Any]]]
    pf_operator: dict[str, dict[str, Any]]
    dex_u0: dict[str, list[dict[str, Any]]]
    wallet_txs: list[dict[str, Any]]
    u0_frame: list[dict[str, Any]]


def load_cache(cache: str) -> CacheData:
    return CacheData(
        grads=_read_jsonl(os.path.join(cache, "universe_grads.jsonl")),
        dex_universe=_load(os.path.join(cache, "dexscreener_universe.json"), {}),
        pf_universe=_load(os.path.join(cache, "pumpfun_universe.json"), {}),
        dex_operator=_load(os.path.join(cache, "dexscreener_operator.json"), {}),
        pf_operator=_load(os.path.join(cache, "pumpfun_operator.json"), {}),
        dex_u0=_load(os.path.join(cache, "dexscreener_u0.json"), {}),
        wallet_txs=_load(os.path.join(cache, "wallet_enh.json"), []),
        u0_frame=_read_jsonl(os.path.join(REPO, "tape", "frames", "frame_stratumA_cohort.jsonl")),
    )


def build_universe(data: CacheData, observed_at: int) -> list[Cohort]:
    grads, dex, pf = data.grads, data.dex_universe, data.pf_universe
    out: list[Cohort] = []
    for row in grads:
        mint = row["mint"]
        if mint not in dex:
            continue
        mkt = pair_metrics(dex[mint])
        grad_ts = int(row["grad_ts"])
        meta = pf.get(mint) or {}
        curve_days = None
        if isinstance(meta.get("created_timestamp"), (int, float)):
            curve_days = max(0.0, (grad_ts - meta["created_timestamp"] / 1000.0) / 86400.0)
        out.append(
            Cohort(
                mint=mint,
                grad_ts=grad_ts,
                age_days=(observed_at - grad_ts) / 86400.0,
                status="",  # filled by caller with the active thresholds
                liquidity_usd=mkt.liquidity_usd,
                volume_24h_usd=mkt.volume_24h_usd,
                mig_sol=float(row.get("mig_sol") or 0.0),
                curve_days=curve_days,
                has_market=mkt.has_market,
                mig_tokens=float(row.get("mig_tokens") or 0.0),
            )
        )
    return out


def _load(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    with open(path) as fh:
        return json.load(fh)


def restatus(universe: Sequence[Cohort], th: Thresholds) -> list[Cohort]:
    return [
        Cohort(
            mint=c.mint,
            grad_ts=c.grad_ts,
            age_days=c.age_days,
            status=classify(c.liquidity_usd, c.volume_24h_usd, th, has_market=c.has_market),
            liquidity_usd=c.liquidity_usd,
            volume_24h_usd=c.volume_24h_usd,
            mig_sol=c.mig_sol,
            curve_days=c.curve_days,
            has_market=c.has_market,
            mig_tokens=c.mig_tokens,
        )
        for c in universe
    ]


# Bin edges for the survival curve, in days since graduation. Fine near zero because that is
# where the hazard lives (Marino/Lillo put the median pump.fun lifetime in minutes), coarse in
# the tail because by then almost nothing moves and the bins need tokens in them.
AGE_EDGES = [
    0.0,
    0.04,
    0.08,
    0.17,
    0.33,
    0.5,
    0.75,
    1.0,
    1.5,
    2.0,
    3.0,
    4.0,
    5.0,
    7.0,
    9.0,
    12.0,
    15.0,
    19.0,
    23.0,
    27.0,
    32.0,
    38.0,
    45.0,
    55.0,
    70.0,
    90.0,
]


def build_picks(data: CacheData, observed_at: int, th: Thresholds) -> dict[str, list[Pick]]:
    """The operator's arms. Three nested definitions, all reported.

      dlmm    mints the wallet actually opened a Meteora DLMM position in.
      graduate  pump.fun graduates held for >= 60s. The arm MATCHED to universe U1.
      touched   every non-quote mint the wallet held for >= 60s, matched or not.

    RESULT_lp_history.md scored twelve tokens. That twelve is reproduced here as `top12`
    because it was produced by `mints.most_common(20)[:12]` -- a rank by transaction count,
    which is a rank by how much the operator kept trading the token, which is a rank
    correlated with the token still being alive. It is in the output as a selection-bias
    exhibit, not as an arm.
    """
    touches = operator_touches(data.wallet_txs)
    dex, pf = data.dex_operator, data.pf_operator
    grads = {r["mint"]: r for r in data.grads}

    made: dict[str, Pick] = {}
    for mint, t in touches.items():
        if mint in QUOTE_MINTS:
            continue
        pairs = dex.get(mint) or []
        mkt = pair_metrics(pairs)
        grad_ts = None
        if mint in grads:
            grad_ts = int(grads[mint]["grad_ts"])
        elif mkt.first_pair_ms:
            grad_ts = int(mkt.first_pair_ms / 1000)
        meta = pf.get(mint) or {}
        curve_days = None
        if grad_ts and isinstance(meta.get("created_timestamp"), (int, float)):
            curve_days = max(0.0, (grad_ts - meta["created_timestamp"] / 1000.0) / 86400.0)
        made[mint] = Pick(
            mint=mint,
            symbol=mkt.symbol,
            entry_ts=t.first_ts,
            grad_ts=grad_ts,
            status=classify(mkt.liquidity_usd, mkt.volume_24h_usd, th, has_market=mkt.has_market),
            liquidity_usd=mkt.liquidity_usd,
            volume_24h_usd=mkt.volume_24h_usd,
            dlmm=t.dlmm_txs > 0,
            held_hours=t.held_seconds / 3600.0,
            mig_sol=float(grads[mint]["mig_sol"]) if mint in grads else None,
            curve_days=curve_days,
        )

    held = [p for p in made.values() if p.held_hours * 3600 >= 60]
    complete = {m: bool((pf.get(m) or {}).get("complete")) for m in made}
    arms = {
        "dlmm": sorted((p for p in held if p.dlmm), key=lambda p: p.entry_ts),
        "graduate": sorted(
            (p for p in held if is_pumpfun_mint(p.mint) and complete.get(p.mint)), key=lambda p: p.entry_ts
        ),
        "touched": sorted(held, key=lambda p: p.entry_ts),
    }
    ranked = sorted(made.values(), key=lambda p: -sum(touches[p.mint].sources.values()))
    arms["top12"] = ranked[:12]
    return arms


def matched_null(
    picks: Sequence[Pick], curve: Sequence[tuple[float, int, float]], observed_at: int
) -> list[float]:
    """Null survival probability per pick: S(age_now) / S(age_at_entry).

    Left truncation, applied. The operator bought token i when it was `a` days past
    graduation and has held the exposure until now, when it is `A` days past graduation. The
    honest null is not "what fraction of graduates survive A days" -- it is "what fraction of
    graduates that reached age a go on to reach age A", and those are very different numbers
    whenever a is large, which for this operator it usually is.
    """
    out: list[float] = []
    for p in picks:
        a = p.entry_age_days
        if a is None or p.grad_ts is None:
            out.append(float("nan"))
            continue
        big_a = (observed_at - p.grad_ts) / 86400.0
        out.append(conditional_survival(curve, a, big_a))
    return out


PRIMARY_TEST = "graduate/U2-age-matched"
UNMATCHED_NULL_LABEL = "U1 unmatched graduate base rate"
MATCHED_NULL_LABEL = "U2 age-matched null"


def analyse(cache: str, *, seed: int, th: Thresholds, strict: bool) -> dict[str, Any]:
    rng = random.Random(seed)
    observed_at = int(WINDOW_END.timestamp())
    data = load_cache(cache)
    census_n = len(data.grads)
    raw_universe = build_universe(data, observed_at)
    universe = restatus(raw_universe, th)
    picks = build_picks(data, observed_at, th)
    curve = survival_curve(universe, strict=strict, edges=AGE_EDGES)
    null_curve = survival_curve(universe, strict=strict, edges=AGE_EDGES, upper_bound=True)

    res: dict[str, Any] = {
        "seed": seed,
        "observed_at": observed_at,
        "thresholds": th.__dict__,
        "strict_counts_dying_as_failure": strict,
        "universe": {
            "n_census": census_n,
            "n_measured": len(universe),
            "window": [CENSUS_START.isoformat(), WINDOW_END.isoformat()],
            "max_age_days": max((c.age_days for c in universe), default=0.0),
            "status_counts": _counts(c.status for c in universe),
            "survival_curve": [{"age_days": a, "n": n, "S": s} for a, n, s in curve],
        },
        "arms": {},
        "tests": [],
    }

    in_window = [c for c in universe if WINDOW_START.timestamp() <= c.grad_ts <= WINDOW_END.timestamp()]
    res["universe"]["n_in_operator_window"] = len(in_window)
    res["universe"]["status_counts_in_window"] = _counts(c.status for c in in_window)
    res["universe"]["survival_in_window_day_weighted"] = day_weighted_survival(
        in_window, data.grads, strict=strict
    )
    res["universe"]["regime"] = regime_note(data.grads)
    res["universe"]["U0_all_launches"] = u0_block(data, th, strict=strict)

    for arm, plist in picks.items():
        alive = sum(1 for p in plist if survived(p.status, strict))
        nulls = matched_null(plist, null_curve, observed_at)
        usable = [(p, q) for p, q in zip(plist, nulls, strict=True) if not math.isnan(q)]
        res["arms"][arm] = {
            "n": len(plist),
            "survived": alive,
            "rate": alive / len(plist) if plist else float("nan"),
            "status_counts": _counts(p.status for p in plist),
            "picks": [
                {
                    "mint": p.mint,
                    "symbol": p.symbol,
                    "status": p.status,
                    "liquidity_usd": p.liquidity_usd,
                    "volume_24h_usd": p.volume_24h_usd,
                    "entry": dt.datetime.fromtimestamp(p.entry_ts, dt.UTC).isoformat(),
                    "entry_age_days": p.entry_age_days,
                    "held_hours": round(p.held_hours, 2),
                    "dlmm": p.dlmm,
                    "null_survival": q,
                }
                for p, q in zip(plist, nulls, strict=True)
            ],
            "matched_null_expected": sum(q for _, q in usable),
            "matched_null_n": len(usable),
            # A pick whose null survival is ~1 contributes no evidence either way: the control
            # says it should have survived, and it did. Counted so the effective n is visible.
            "picks_with_uninformative_null": sum(1 for _, q in usable if q >= 0.99),
        }

        # Test A: unmatched Fisher against the whole in-window graduate cohort.
        u_alive = sum(1 for c in in_window if survived(c.status, strict))
        p_fisher = fisher_exact_greater(alive, len(plist) - alive, u_alive, len(in_window) - u_alive)
        res["tests"].append(
            {
                "id": f"{arm}/U1-unmatched",
                "arm": arm,
                "universe": "U1 graduates in window, no age matching",
                "table": [alive, len(plist) - alive, u_alive, len(in_window) - u_alive],
                "p_one_sided": p_fisher,
                "test": "Fisher exact, one-sided (picks survive more)",
                "preregistered": arm != "top12",
            }
        )

        # Test B: the matched design. Each pick has its own null, so the null distribution of
        # the survivor count is Poisson-binomial rather than binomial.
        if usable:
            ps = [q for _, q in usable]
            k = sum(1 for p, _ in usable if survived(p.status, strict))
            res["tests"].append(
                {
                    "id": f"{arm}/U2-age-matched",
                    "arm": arm,
                    "universe": "U2 graduates matched on token age at entry (left-truncated)",
                    "observed_survivors": k,
                    "n": len(usable),
                    "expected_under_null": sum(ps),
                    "p_one_sided": poisson_binomial_at_least(ps, k),
                    "test": "Poisson-binomial exact, one-sided",
                    "preregistered": arm != "top12",
                }
            )

    # Multiplicity. Every arm x universe pairing above is a hypothesis, and reporting the
    # smallest of them without saying how many were computed is the failure PROGRAM.md
    # section 3.9 is about. `top12` is not counted: it is a selection-bias exhibit, not a
    # hypothesis, and it is reported precisely because it is contaminated.
    family = [t for t in res["tests"] if t["preregistered"]]
    ps = [t["p_one_sided"] for t in family]
    for t, adj in zip(family, benjamini_hochberg(ps), strict=True):
        t["p_bh"] = adj
        t["p_bonferroni"] = min(1.0, t["p_one_sided"] * len(ps))
    for t in res["tests"]:
        t.setdefault("p_bh", float("nan"))
        t.setdefault("p_bonferroni", float("nan"))
        t["primary"] = t["id"] == PRIMARY_TEST
    res["n_hypotheses"] = len(ps)
    res["primary_test"] = PRIMARY_TEST

    res["power"] = power_block(universe, in_window, picks, null_curve, strict=strict)
    res["confound"] = confound_block(universe, picks, null_curve, rng, strict=strict)
    res["threshold_sensitivity"] = threshold_sweep(data, raw_universe, strict=strict)
    res["instrument_agreement"] = instrument_agreement(
        data, universe, picks.get("graduate", []), observed_at
    )
    res["window_restricted"] = window_restricted(raw_universe, picks, th, strict=strict)
    res["leave_one_out"] = leave_one_out(picks.get("graduate", []), null_curve, observed_at, strict=strict)
    res["verdict"] = verdict(res)
    return res


def leave_one_out(
    arm: Sequence[Pick], curve: Sequence[tuple[float, int, float]], observed_at: int, *, strict: bool
) -> dict[str, Any]:
    """Drop each pick in turn and re-test. PROGRAM.md section 5: leave-k-out sensitivity.

    At n=14 a single token can carry the whole result. In an adjacent memecoin sample removing
    the top 3 of 190 trades flipped a +117.7% cumulative return to unprofitable; a survival
    record is no less fragile. If one omission moves the p-value across the threshold, the
    result belongs to that token and not to the filter.
    """
    if len(arm) < 3:
        return {"n": len(arm), "worst_p": float("nan"), "rows": []}
    rows = []
    for i, dropped in enumerate(arm):
        kept = [p for j, p in enumerate(arm) if j != i]
        nulls = matched_null(kept, curve, observed_at)
        usable = [(p, q) for p, q in zip(kept, nulls, strict=True) if not math.isnan(q)]
        k = sum(1 for p, _ in usable if survived(p.status, strict))
        rows.append(
            {
                "dropped_mint": dropped.mint,
                "dropped_symbol": dropped.symbol,
                "p_one_sided": poisson_binomial_at_least([q for _, q in usable], k) if usable else 1.0,
            }
        )
    return {
        "n": len(arm),
        "worst_p": max(r["p_one_sided"] for r in rows),
        "best_p": min(r["p_one_sided"] for r in rows),
        "rows": sorted(rows, key=lambda r: -r["p_one_sided"])[:5],
    }


def window_restricted(
    raw_universe: Sequence[Cohort], picks: dict[str, list[Pick]], th: Thresholds, *, strict: bool
) -> dict[str, Any]:
    """The same matched test with the control restricted to the operator's OWN window.

    The census reaches back 76 days so that a pick bought 55 days past graduation has
    same-aged controls. The price is that the old age bins are populated by cohorts that
    graduated in a visibly different regime -- graduations ran ~180/day in late May and
    ~1045/day by mid-August, a 6x shift inside one census -- so a cross-sectional S(age)
    conflates age with calendar. Restricting the control to graduations inside 18 Jul - 14 Aug
    removes the calendar confound and costs the picks whose entry age exceeds the window. If
    the verdict survives both cuts it is not a regime artefact.
    """
    inside = [
        c
        for c in raw_universe
        if WINDOW_START.timestamp() <= c.grad_ts <= WINDOW_END.timestamp()
    ]
    uni = restatus(inside, th)
    curve = survival_curve(uni, strict=strict, edges=AGE_EDGES, upper_bound=True)
    max_age = max((c.age_days for c in uni), default=0.0)
    arm = [
        p
        for p in picks.get("graduate", [])
        if p.entry_age_days is not None and p.entry_age_days <= max_age
    ]
    nulls = matched_null(arm, curve, int(WINDOW_END.timestamp()))
    usable = [(p, q) for p, q in zip(arm, nulls, strict=True) if not math.isnan(q)]
    k = sum(1 for p, _ in usable if survived(p.status, strict))
    return {
        "control_window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "control_n": len(uni),
        "max_control_age_days": max_age,
        "arm_n_in_support": len(usable),
        "arm_dropped_for_age": len(picks.get("graduate", [])) - len(arm),
        "observed_survivors": k,
        "expected_under_null": sum(q for _, q in usable),
        "p_one_sided": poisson_binomial_at_least([q for _, q in usable], k) if usable else float("nan"),
    }


def day_weighted_survival(
    sampled: Sequence[Cohort], census: Sequence[dict[str, Any]], *, strict: bool
) -> float:
    """Population survival rate, each sampled mint weighted by its day's sampling fraction.

    The outcome sample is 140 graduations per day everywhere plus complete coverage of the
    last four days, so a pooled average over the sample over-weights the recent regime. The
    per-age-bin rates are unaffected (each bin is a uniform draw within its own day) but a
    single headline number is not, so it gets the survey weight.
    """
    per_day_census: dict[str, int] = {}
    for row in census:
        day = dt.datetime.fromtimestamp(row["grad_ts"], dt.UTC).strftime("%Y-%m-%d")
        per_day_census[day] = per_day_census.get(day, 0) + 1
    per_day_sample: dict[str, int] = {}
    for c in sampled:
        day = dt.datetime.fromtimestamp(c.grad_ts, dt.UTC).strftime("%Y-%m-%d")
        per_day_sample[day] = per_day_sample.get(day, 0) + 1
    num = den = 0.0
    for c in sampled:
        day = dt.datetime.fromtimestamp(c.grad_ts, dt.UTC).strftime("%Y-%m-%d")
        w = per_day_census.get(day, 0) / max(1, per_day_sample.get(day, 1))
        den += w
        if survived(c.status, strict):
            num += w
    return num / den if den else float("nan")


def regime_note(census: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The regime the census spans, and the limit it puts on everything built from it.

    An earlier version of this function tried to split the census in half and compare S(age)
    between the halves. It cannot be done, and the reason is worth writing down rather than
    silently dropping: in a SINGLE cross-section, a token that is 60 days old necessarily
    graduated 60 days ago. Age and calendar are not merely correlated, they are the same
    variable. There is no half of this data that observes an old cohort at a young age.

    So the regime is reported, not tested. PROGRAM.md section 3.6 is the warning and this is
    the exposure: graduations per week over the census, which moved by roughly 6x. The
    mitigation is `window_restricted`, which throws away the age range that only old cohorts
    can populate. The fix is a SECOND cross-section a month from now: two of them separate age
    from calendar, one cannot.
    """
    per_week: dict[str, int] = {}
    days_seen: dict[str, set[str]] = {}
    for row in census:
        d = dt.datetime.fromtimestamp(row["grad_ts"], dt.UTC)
        key = (d - dt.timedelta(days=d.weekday())).strftime("%Y-%m-%d")
        per_week[key] = per_week.get(key, 0) + 1
        days_seen.setdefault(key, set()).add(d.strftime("%Y-%m-%d"))
    weeks = sorted(per_week.items())
    # Partial weeks at the ends of the census would otherwise set the range.
    counts = [c for w, c in weeks if len(days_seen[w]) == 7]
    return {
        "graduations_per_week": [{"week_of": w, "n": c} for w, c in weeks],
        "min_week": min(counts) if counts else 0,
        "max_week": max(counts) if counts else 0,
        "swing": (max(counts) / min(counts)) if counts and min(counts) else float("nan"),
        "identification_limit": (
            "age and calendar are the same variable in one cross-section; S(age) at 60 days "
            "can only be measured on the cohort that graduated 60 days ago"
        ),
    }


# A pump.fun bonding curve starts at a fixed market cap. A token still sitting at that number
# has had no net buying at all, which is a stronger and cheaper death test than any dollar
# threshold: it is the launch value itself, not a knob.
PUMPFUN_LAUNCH_MCAP_USD = 2_120.0


def u0_block(data: CacheData, th: Thresholds, *, strict: bool) -> dict[str, Any]:
    """U0: every pump.fun LAUNCH, graduated or not, from the tape's cohort frame.

    Included to show the size of the free lunch. A filter scored against U0 is credited for a
    condition every LP satisfies by existing, because you cannot put a position into a token
    that has no pool.

    Scored differently from U1, and the difference is stated rather than hidden: DexScreener
    reports NO liquidity figure for a pair still on its bonding curve, so a liquidity
    threshold is not available for 97% of this frame. Two threshold-free readings are given
    instead -- whether the curve ever completed, and whether the token has moved off its fixed
    launch market cap -- and the third, `still_trading_6h`, needs no dollar figure at all.
    """
    frame = os.path.join(REPO, "tape", "frames", "frame_stratumA_cohort.jsonl")
    rows = data.u0_frame
    if not rows:
        return {"available": False, "reason": f"{frame} not present (tape/ is gitignored data)"}
    dex = data.dex_u0
    measured = [m for m in dex if dex[m]]
    graduated_on_frame = sum(1 for r in rows if r.get("listed_complete"))
    off_curve = at_launch_mcap = trading_6h = 0
    for m in measured:
        pairs = dex[m]
        top = best_pair(pairs) or {}
        if (top.get("liquidity") or {}).get("usd") is not None:
            off_curve += 1
        mcap = float(top.get("marketCap") or top.get("fdv") or 0.0)
        if mcap <= PUMPFUN_LAUNCH_MCAP_USD * 1.02:
            at_launch_mcap += 1
        if float((top.get("volume") or {}).get("h6") or 0.0) > 0:
            trading_6h += 1
    n = len(measured) or 1
    return {
        "available": True,
        "frame": os.path.relpath(frame, REPO),
        "n_launches": len(rows),
        "n_with_any_dexscreener_pair": len(measured),
        "graduated_on_frame": graduated_on_frame,
        "graduation_rate": graduated_on_frame / len(rows),
        "off_bonding_curve_now": off_curve,
        "off_bonding_curve_rate": off_curve / n,
        "at_or_below_launch_market_cap": at_launch_mcap,
        "at_launch_market_cap_rate": at_launch_mcap / n,
        "still_trading_6h": trading_6h,
        "still_trading_6h_rate": trading_6h / n,
        "survival_rate_used_for_comparison": off_curve / n,
        "note": (
            "survival_rate_used_for_comparison is the share that reached a real AMM pool at "
            "all -- the loosest possible reading of 'did not die', and the one that makes the "
            "filter look best"
        ),
    }


def instrument_agreement(
    data: CacheData, universe: Sequence[Cohort], picks: Sequence[Pick], observed_at: int
) -> dict[str, Any]:
    """A second, independent read on "is this token alive", and how far it disagrees.

    DexScreener DELISTS pairs it considers inactive, so "no market" is partly an indexing
    policy and not purely a fact about the chain. pump.fun's own record carries
    `last_trade_timestamp`, which is a different instrument with a different failure mode.
    "Traded in the last 24 hours" needs no dollar threshold at all.

    If both instruments give the same verdict, the verdict is not the instrument. If they do
    not, the number to quote is the disagreement, not whichever one is more flattering.
    """
    day = 86_400

    def traded_recently(meta: dict[str, Any]) -> bool | None:
        ts = meta.get("last_trade_timestamp")
        if not isinstance(ts, (int, float)):
            return None
        return (observed_at - ts / 1000.0) <= day

    table = {"both_alive": 0, "both_dead": 0, "dex_alive_pf_dead": 0, "dex_dead_pf_alive": 0}
    pf_alive = pf_total = 0
    for c in universe:
        meta = data.pf_universe.get(c.mint) or {}
        pf = traded_recently(meta)
        if pf is None:
            continue
        pf_total += 1
        pf_alive += int(pf)
        dex = c.status != DEAD
        key = "both_alive" if (dex and pf) else "both_dead" if (not dex and not pf) else (
            "dex_alive_pf_dead" if dex else "dex_dead_pf_alive"
        )
        table[key] += 1
    agree = table["both_alive"] + table["both_dead"]
    total = sum(table.values())

    arm_pf_alive, arm_pf_total = 0, 0
    for p in picks:
        pf = traded_recently(data.pf_operator.get(p.mint) or {})
        if pf is None:
            continue
        arm_pf_total += 1
        arm_pf_alive += int(pf)
    return {
        "definition": "pump.fun last_trade_timestamp within 24h of the observation time",
        "universe_n_with_both": total,
        "universe_agreement": agree / total if total else float("nan"),
        "cross_tab": table,
        "universe_survival_dexscreener": (
            sum(1 for c in universe if c.status != DEAD) / len(universe) if universe else float("nan")
        ),
        "universe_survival_pumpfun_24h": pf_alive / pf_total if pf_total else float("nan"),
        "arm_n_with_pumpfun": arm_pf_total,
        "arm_survival_pumpfun_24h": arm_pf_alive / arm_pf_total if arm_pf_total else float("nan"),
    }


def threshold_sweep(
    data: CacheData, base_universe: Sequence[Cohort], *, strict: bool
) -> list[dict[str, Any]]:
    """The same comparison at every plausible place to draw "dead".

    PROGRAM.md section 3.7: the same NFT market yields wash estimates from 0.12% to 94.5%
    purely on knob settings. If the verdict moves with the knob, the verdict is the knob.
    """
    observed_at = int(WINDOW_END.timestamp())
    out: list[dict[str, Any]] = []
    for dead_liq, dead_vol in ((250.0, 0.0), (1_000.0, 100.0), (5_000.0, 500.0), (10_000.0, 1_000.0)):
        th = Thresholds(dead_liq=dead_liq, dead_vol=dead_vol)
        uni = restatus(base_universe, th)
        picks = build_picks(data, observed_at, th)
        curve = survival_curve(uni, strict=strict, edges=AGE_EDGES, upper_bound=True)
        arm = picks.get("graduate", [])
        nulls = matched_null(arm, curve, observed_at)
        usable = [(p, q) for p, q in zip(arm, nulls, strict=True) if not math.isnan(q)]
        k = sum(1 for p, _ in usable if survived(p.status, strict))
        in_window = [c for c in uni if WINDOW_START.timestamp() <= c.grad_ts <= WINDOW_END.timestamp()]
        u_alive = sum(1 for c in in_window if survived(c.status, strict))
        out.append(
            {
                "dead_liq": dead_liq,
                "dead_vol": dead_vol,
                "universe_survival": u_alive / len(in_window) if in_window else float("nan"),
                "arm_n": len(arm),
                "arm_survived": sum(1 for p in arm if survived(p.status, strict)),
                "expected_under_matched_null": sum(q for _, q in usable),
                "p_matched": poisson_binomial_at_least([q for _, q in usable], k) if usable else float("nan"),
                "picks_needed_perfect_a05": picks_needed_perfect(
                    u_alive / len(in_window) if in_window else 1.0, 0.05
                ),
            }
        )
    return out


def verdict(res: dict[str, Any]) -> dict[str, Any]:
    """FILTER-SHOWS-SIGNAL / INDISTINGUISHABLE / UNRESOLVABLE-AT-THIS-N.

    UNRESOLVABLE is not a softer INDISTINGUISHABLE. It is the strictly stronger statement
    that no outcome the arm could have produced -- including a perfect record -- would have
    cleared the bar at this sample size. That is a property of the design, not the data, and
    it is decided before the data is looked at.

    SIGNAL additionally requires the result to survive the threshold sweep. PROGRAM.md
    section 3.7: the same market yields wash-trade estimates from 0.12% to 94.5% purely on
    knob settings. A p-value that exists at one definition of "dead" and vanishes at the next
    is a report about the knob, and calling that a filter would be the exact failure this
    lane was built to prevent.
    """
    primary = next((t for t in res["tests"] if t.get("primary")), None)
    power_rows = res["power"]["rows"]
    matched = next((r for r in power_rows if r["null_label"] == MATCHED_NULL_LABEL), None)
    n = res["power"]["n_current_graduate_arm"]
    needed = matched["picks_needed_perfect_a05"] if matched else None
    alpha = 0.05 / max(1, res["n_hypotheses"])
    sweep = res.get("threshold_sensitivity") or []
    sweep_ps = [r["p_matched"] for r in sweep if not math.isnan(r["p_matched"])]
    robust = bool(sweep_ps) and all(p <= alpha for p in sweep_ps)
    worst = max(sweep_ps) if sweep_ps else float("nan")

    if needed is not None and needed > n:
        label = "UNRESOLVABLE-AT-THIS-N"
        why = (
            f"a PERFECT record needs {needed} picks to clear alpha=0.05 against the age-matched "
            f"null; the arm has {n}. No outcome at n={n} could have been significant."
        )
    elif primary and primary["p_one_sided"] <= alpha and robust:
        label = "FILTER-SHOWS-SIGNAL"
        why = (
            f"primary p={primary['p_one_sided']:.4f} <= Bonferroni alpha={alpha:.4f}, and it holds "
            f"at every threshold in the sweep (worst p={worst:.4f})"
        )
    elif primary and primary["p_one_sided"] <= alpha:
        label = "INDISTINGUISHABLE"
        why = (
            f"primary p={primary['p_one_sided']:.4f} clears alpha={alpha:.4f} at the headline "
            f"threshold but NOT across the sweep (worst p={worst:.4f}); the separation is the "
            f"choice of where 'dead' is drawn, not the picks"
        )
    else:
        p = primary["p_one_sided"] if primary else float("nan")
        label = "INDISTINGUISHABLE"
        why = f"primary p={p:.4f} > Bonferroni alpha={alpha:.4f}; the arm is powered but did not separate"
    return {
        "label": label,
        "why": why,
        "alpha_bonferroni": alpha,
        "picks_needed": needed,
        "n_now": n,
        "robust_across_thresholds": robust,
        "worst_threshold_p": worst,
    }


def power_block(
    universe: Sequence[Cohort],
    in_window: Sequence[Cohort],
    picks: dict[str, list[Pick]],
    curve: Sequence[tuple[float, int, float]],
    *,
    strict: bool,
) -> dict[str, Any]:
    """How long the operator must keep records before a perfect run means anything.

    This is the deliverable. Everything else in this file is a measurement; this is the
    number that tells the operator what to do.
    """
    u_alive = sum(1 for c in in_window if survived(c.status, strict))
    p_unmatched = u_alive / len(in_window) if in_window else float("nan")

    matched = matched_null(picks.get("graduate", []), curve, int(WINDOW_END.timestamp()))
    finite = [q for q in matched if not math.isnan(q)]
    p_matched = sum(finite) / len(finite) if finite else float("nan")

    rows = []
    nulls = ((UNMATCHED_NULL_LABEL, p_unmatched), (MATCHED_NULL_LABEL, p_matched))
    for label, p_null in nulls:
        if math.isnan(p_null):
            continue
        rows.append(
            {
                "null_label": label,
                "p_survive_null": p_null,
                "picks_needed_perfect_a05": picks_needed_perfect(p_null, 0.05),
                "picks_needed_perfect_a01": picks_needed_perfect(p_null, 0.01),
                "picks_needed_vs_finite_control_a05": picks_needed_fisher(u_alive, len(in_window), 0.05),
                "p_at_current_n": p_null ** len(picks.get("graduate", [])) if picks.get("graduate") else None,
            }
        )
    # The decision table. How many picks a perfect record needs depends almost entirely on
    # HOW SEASONED the tokens are when they are bought, because that is what sets the null.
    # Buying fresh graduates makes a run of survivors cheap to prove; buying two-week-old
    # tokens makes the same run nearly worthless as evidence.
    horizon = 21.0
    by_age = []
    for cutoff in (0.0, 0.25, 1.0, 3.0, 7.0, 14.0, 30.0):
        p_null = conditional_survival(curve, cutoff, cutoff + horizon)
        by_age.append(
            {
                "entry_age_days": cutoff,
                "follow_up_days": horizon,
                "p_survive_null": p_null,
                "picks_needed_perfect_a05": picks_needed_perfect(p_null, 0.05),
                "picks_needed_perfect_a01": picks_needed_perfect(p_null, 0.01),
            }
        )
    return {
        "rows": rows,
        "picks_needed_by_entry_age": by_age,
        "n_current_graduate_arm": len(picks.get("graduate", [])),
        "n_current_dlmm_arm": len(picks.get("dlmm", [])),
    }


def confound_block(
    universe: Sequence[Cohort],
    picks: dict[str, list[Pick]],
    curve: Sequence[tuple[float, int, float]],
    rng: random.Random,
    *,
    strict: bool,
) -> dict[str, Any]:
    """Is the filter doing anything a size or seasoning screen would not?

    The size axis turns out to be answered by the venue rather than by a test. Every pump.fun
    graduation deposits the SAME inventory into the new pool, so "the operator's projects
    were bigger at launch" cannot be true WITHIN this universe -- U1 is matched on initial
    size by construction, which is a large part of why it is the right universe. That is
    measured here rather than asserted (`initial_size`).

    What is left that is observable BEFORE any outcome exists:
      curve_days  time the token spent on the bonding curve before completing it -- a demand
                  signal, and the one real quality covariate available for the whole universe.
      entry_age   how old the token already was when the operator bought it. Not a property
                  of the token at all, and it does most of the work.

    `age_screen` is the question the lane was set: it compares the operator's realised
    survival against what a MECHANICAL screen -- "only buy graduates already N days old",
    chosen with no knowledge of any team -- returns on the same universe over the same
    follow-up horizons. If the mechanical screen matches the operator, the social filter is
    not the thing doing the work.
    """
    arm = picks.get("graduate", [])
    out: dict[str, Any] = {}

    tokens = [c.mig_tokens for c in universe if c.mig_tokens > 0]
    modal = 206_900_000.0
    out["initial_size"] = {
        "universe_n": len(tokens),
        "modal_token_deposit": modal,
        "share_at_modal_deposit": (
            sum(1 for t in tokens if abs(t - modal) < 1.0) / len(tokens) if tokens else float("nan")
        ),
        "note": (
            "pump.fun graduation is a standardised liquidity event, so U1 is matched on "
            "size-at-graduation by construction and a size confound cannot operate inside it. "
            "The SOL side of the deposit is NOT used: ~30% of migrations move native SOL "
            "rather than wrapped SOL, so it is not recoverable from the parsed token transfers "
            "and any average over the recoverable 70% would be a selected subset."
        ),
    }

    pick_curve = [p.curve_days for p in arm if p.curve_days is not None]
    uni_curve = [c.curve_days for c in universe if c.curve_days is not None]
    if pick_curve and uni_curve:
        diff, p = permutation_test_mean_diff(pick_curve, uni_curve, rounds=2000, rng=rng)
        out["curve_days"] = {
            "picks_n": len(pick_curve),
            "picks_median": _median(pick_curve),
            "universe_median": _median(uni_curve),
            "diff_of_means": diff,
            "p_permutation": p,
        }

    # PROGRAM.md section 3.8, the truncation check: observed time-to-graduation must reproduce
    # Marino/Lillo's median of ~4.4 minutes WITH A TAIL. A pipeline whose maximum is five
    # minutes is not measuring a fast market, it is measuring its own censoring.
    if uni_curve:
        srt = sorted(uni_curve)
        out["time_on_curve_instrument_check"] = {
            "n": len(srt),
            "median_minutes": _median(srt) * 1440,
            "p90_minutes": srt[int(0.90 * (len(srt) - 1))] * 1440,
            "p99_minutes": srt[int(0.99 * (len(srt) - 1))] * 1440,
            "max_days": srt[-1],
            "reference": "Marino/Lillo median time-to-graduation 4.4 min; a tail must exist",
        }

    ages = [p.entry_age_days for p in arm if p.entry_age_days is not None]
    out["entry_age_days"] = {
        "n": len(ages),
        "median": _median(ages) if ages else None,
        "min": min(ages) if ages else None,
        "max": max(ages) if ages else None,
        "note": "age at entry is the screen the operator is unknowingly applying",
    }

    # The mechanical alternative. For each cutoff, hold the operator's follow-up distribution
    # fixed and ask what a screen that knows nothing about any team would have returned.
    observed_at = int(WINDOW_END.timestamp())
    followups = [
        (observed_at - p.entry_ts) / 86400.0 for p in arm if p.entry_age_days is not None
    ]
    screens = []
    for cutoff in (0.0, 0.25, 1.0, 3.0, 7.0, 14.0):
        ps = [conditional_survival(curve, cutoff, cutoff + f) for f in followups]
        if not ps:
            continue
        screens.append(
            {
                "min_age_days_at_entry": cutoff,
                "expected_survival_rate": sum(ps) / len(ps),
                "expected_survivors_over_operator_followups": sum(ps),
                "n": len(ps),
            }
        )
    realised = sum(1 for p in arm if survived(p.status, strict))
    out["age_screen"] = {
        "operator_survivors": realised,
        "operator_n": len(arm),
        "operator_rate": realised / len(arm) if arm else float("nan"),
        "mechanical_screens": screens,
        "note": (
            "a screen of 'graduate at least X days old', applied with no social information, "
            "over the operator's own follow-up horizons"
        ),
    }
    return out


def _counts(values: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def _median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return float("nan")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


# --------------------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------------------


def do_collect(cache: str, seed: int, per_day: int) -> None:
    os.makedirs(cache, exist_ok=True)
    ledger = CreditLedger(os.path.join(cache, "credits.json"))
    print("== operator wallet ==", flush=True)
    txs = collect_operator(cache, ledger)
    print(f"   {len(txs)} transactions", flush=True)

    print("== graduation census (chain) ==", flush=True)
    n = collect_universe(cache, ledger)
    print(f"   {n} graduations cached", flush=True)

    touches = operator_touches(txs)
    op_mints = [m for m in touches if m not in QUOTE_MINTS]
    print(f"== outcomes: operator ({len(op_mints)} mints) ==", flush=True)
    collect_dexscreener(cache, op_mints, "operator")
    collect_pumpfun(cache, op_mints, "operator")

    grads = _read_jsonl(os.path.join(cache, "universe_grads.jsonl"))
    sample = stratified_sample(grads, per_day=per_day, seed=seed)
    print(f"== outcomes: universe ({len(sample)} of {len(grads)} graduations) ==", flush=True)
    collect_dexscreener(cache, [r["mint"] for r in sample], "universe")
    # The pump.fun record is one HTTP call per mint, so the second instrument and the
    # bonding-curve covariate run on a thinner stratified subsample of the same frame.
    covariate = stratified_sample(grads, per_day=max(1, per_day // 3), seed=seed)
    print(f"== covariates: universe ({len(covariate)} mints) ==", flush=True)
    collect_pumpfun(cache, [r["mint"] for r in covariate], "universe")

    u0 = _read_jsonl(os.path.join(REPO, "tape", "frames", "frame_stratumA_cohort.jsonl"))
    if u0:
        print(f"== outcomes: U0 all launches ({len(u0)} from tape) ==", flush=True)
        collect_dexscreener(cache, [r["mint"] for r in u0], "u0")
    print(f"\nhelius credits this study: {ledger.total}", flush=True)


def stratified_sample(grads: Sequence[dict[str, Any]], *, per_day: int, seed: int) -> list[dict[str, Any]]:
    """Uniform sample within each graduation DAY.

    Stratifying by day is not decoration: the graduation base rate is the thing PROGRAM.md
    section 3.6 says moves fastest, so a sample that happened to concentrate in one week
    would measure that week's regime and call it the population.
    """
    by_day: dict[str, list[dict[str, Any]]] = {}
    for row in grads:
        day = dt.datetime.fromtimestamp(row["grad_ts"], dt.UTC).strftime("%Y-%m-%d")
        by_day.setdefault(day, []).append(row)
    out: list[dict[str, Any]] = []
    for day in sorted(by_day):
        rows = sorted(by_day[day], key=lambda r: r["mint"])
        rng = random.Random(f"{seed}:{day}")
        out.extend(rows if len(rows) <= per_day else rng.sample(rows, per_day))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--collect", action="store_true", help="fetch and cache (network)")
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument("--seed", type=int, default=20260814)
    ap.add_argument("--per-day", type=int, default=140, help="universe mints sampled per graduation day")
    ap.add_argument("--strict", action="store_true", help="count DYING as a failure")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.collect:
        do_collect(args.cache, args.seed, args.per_day)
        return 0

    th = Thresholds()
    res = analyse(args.cache, seed=args.seed, th=th, strict=args.strict)
    if args.json:
        json.dump(res, sys.stdout, indent=1, default=str)
        print()
        return 0
    render(res)
    return 0


def render(res: dict[str, Any]) -> None:
    u = res["universe"]
    print(
        f"universe U1: {u['n_measured']} graduations measured, "
        f"census {u['window'][0][:10]} -> {u['window'][1][:10]}"
    )
    print(f"  status now : {u['status_counts']}")
    print(f"  in operator window: {u['n_in_operator_window']}  {u['status_counts_in_window']}")
    print("\nsurvival curve S(age) from the cross-section:")
    for pt in u["survival_curve"]:
        if pt["n"]:
            print(f"  {pt['age_days']:6.2f}d  n={pt['n']:5d}  S={pt['S']:.3f}")
    print(f"  day-weighted in-window survival: {u['survival_in_window_day_weighted']:.4f}")
    print(f"  regime: graduations/week {u['regime']['min_week']} -> {u['regime']['max_week']} "
          f"({u['regime']['swing']:.1f}x across the census)")
    print("\narms:")
    for name, arm in res["arms"].items():
        exp = arm["matched_null_expected"]
        print(
            f"  {name:9s} n={arm['n']:3d}  survived={arm['survived']:3d} "
            f"({arm['rate']:.3f})  expected under age-matched null={exp:.2f}  {arm['status_counts']}"
        )
    print("\ntests:")
    for t in res["tests"]:
        print(f"  {t['id']:26s} p={t['p_one_sided']:.4f}  BH={t['p_bh']:.4f}  bonf={t['p_bonferroni']:.4f}")
    print(f"  ({res['n_hypotheses']} hypotheses)")
    print("\npower:")
    for row in res["power"]["rows"]:
        print(
            f"  {row['null_label']:34s} p_null={row['p_survive_null']:.4f} "
            f"perfect-record picks needed: {row['picks_needed_perfect_a05']} (a=.05) "
            f"{row['picks_needed_perfect_a01']} (a=.01)"
        )
    print("  picks needed for a PERFECT record, by how seasoned the picks are (21d horizon):")
    for row in res["power"]["picks_needed_by_entry_age"]:
        print(
            f"    entry age >= {row['entry_age_days']:5.2f}d  p_null={row['p_survive_null']:.4f}  "
            f"picks needed: {row['picks_needed_perfect_a05']} (a=.05) "
            f"{row['picks_needed_perfect_a01']} (a=.01)"
        )
    print("\nU0 (every launch, not just graduates):")
    print(f"  {json.dumps(u['U0_all_launches'], default=str)}")
    print("\nwindow-restricted control (no calendar confound):")
    print(f"  {json.dumps(res['window_restricted'], default=str)}")
    print("\nleave-one-out:")
    print(f"  {json.dumps(res['leave_one_out'], default=str)}")
    print("\nthreshold sensitivity:")
    for row in res["threshold_sensitivity"]:
        print(
            f"  dead<${row['dead_liq']:>7,.0f}liq/${row['dead_vol']:>6,.0f}vol  "
            f"universe S={row['universe_survival']:.3f}  arm {row['arm_survived']}/{row['arm_n']}  "
            f"exp={row['expected_under_matched_null']:.2f}  p={row['p_matched']:.4f}  "
            f"picks needed={row['picks_needed_perfect_a05']}"
        )
    print("\ninstrument agreement (DexScreener vs pump.fun last-trade):")
    print(f"  {json.dumps(res['instrument_agreement'], default=str)}")
    print("\nconfound:")
    print(json.dumps(res["confound"], indent=1, default=str))
    print(f"\nVERDICT: {res['verdict']['label']}\n  {res['verdict']['why']}")


if __name__ == "__main__":
    raise SystemExit(main())
