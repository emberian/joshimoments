#!/usr/bin/env python3
"""Copy-trading and app-mediated flow on the cluster pools: hazard, edge, or noise?

THE QUESTION
------------
Copy-trading products and "follow this wallet" apps are a live force in memecoin
markets and we have never measured their effect on the coins we actually hold.
Two readings are actionable and opposite. As a HAZARD: a followed wallet enters,
a crowd follows, and the operator is the exit liquidity when the leader turns. As
a SIGNAL: a leader's entry is an observable event with a measurable lag, and a lag
you can measure is a lag you can trade.

Both readings assume the phenomenon is DETECTABLE at our resolution. That is the
claim this study tests first, because if it fails, the rest is decoration.

THE SIGNATURE, DEFINED OPERATIONALLY
------------------------------------
A copied trade produces a characteristic mark: after a trade by wallet L on pool P
in direction D at slot s, an unusual density of trades on P, in direction D, by
DISTINCT wallets, in slots (s, s+delta]. Three things wear that costume and are
not copying, and each is excluded by construction rather than by judgement:

(a) ORDINARY MOMENTUM. Same-direction flow clusters because the market clusters.
    This is handled by the null, not by a filter — see below, it is the whole ball
    game and the reason the naive answer is off by a factor of fifty.
(b) MEV / ATOMIC BUNDLES. PROGRAM.md 4 names this the dominant false positive.
    Excluded by requiring lag >= 1 SLOT: a bundle is same-slot by construction.
    With BigQuery's `index` column we can go further and show that 14% of
    same-slot consecutive pairs are tx_index-ADJACENT, i.e. bundle-shaped.
(c) ONE ENTITY, MANY WALLETS. This is bundling (PROGRAM.md 1.1, MELT's 36.5%),
    a different phenomenon with a different implication, and it inflates a naive
    "distinct wallets" count directly. Addressed by entity resolution — with a
    caveat about circularity that turned out to matter more than the resolution
    itself. See ENTITY RESOLUTION IS CIRCULAR HERE below.

THE UNIT OF TIME IS THE SLOT, NOT THE SECOND. `block_time` is second-resolution
and quantises ~2.5 slots into one stamp, which would smear exactly the 0.4-2s band
where a bot copier has to live. Slots are exact and are what a copier's latency is
actually measured in.

WHAT THE NULL HAS TO PRESERVE, AND WHY THIS IS THE ENTIRE METHOD
----------------------------------------------------------------
studies/RESULT_flow_signals.md found that an i.i.d. null alone would have shipped
a bogus changepoint alarm on this exact data. It does the same thing here, and the
size of the error is worth stating because it is the difference between a headline
and a null:

  Against a null that resamples each wallet's trade times UNIFORMLY over the tape
  (preserving each wallet's rate, as a naive reading of "time-shuffled" suggests),
  the observed density of distinct-wallet same-direction trades at lag 1 slot is
  73x expected on nosis/SOL buys (1,815 against 25.0), and 149x at lag 0. Against
  a null that also preserves the market's own aggregate intensity, the same number
  is 1.01x. That factor of seventy is entirely spurious: it says only that trading
  is bursty in wall-clock time, which we already knew.

A null for a burst detector must therefore hold the market's own aggregate
intensity FIXED and destroy only the association between wallets and times. Two do:

  PERM  — permute the wallet labels across the observed (slot, side) events.
          Preserves the aggregate arrival process exactly and each wallet's trade
          count exactly. Destroys within-wallet autocorrelation, which is a real
          cost: a wallet that slices one order into six clips looks, under PERM,
          like six wallets' worth of independent draws. PERM therefore
          UNDER-states the null and OVER-rejects.
  ROT   — circularly rotate the wallet-label vector along the event-ordered
          sequence by a random offset. Preserves the aggregate process, each
          wallet's count, AND each wallet's own run/burst structure (a block of
          consecutive trades stays a block). This is the autocorrelation-preserving
          block null the binding asks for, and it is the one to believe.

The two disagree, and the disagreement is the finding in miniature: at wallet
level PERM flags four of eight pair-level tests at p<0.05 and ROT flags none.

ENTITY RESOLUTION IS CIRCULAR HERE, AND SAYING SO IS PART OF THE RESULT
-----------------------------------------------------------------------
PROGRAM.md 3 binds us to group wallets into entities BEFORE splitting. The natural
grouping rule on chain — wallets that repeatedly land in the same slot on the same
pool are one operator — is a TEMPORAL rule. Feeding its output into a test of
TEMPORAL proximity is circular, and it does not fail quietly: the co-slot union-find
builds one 138-wallet mega-entity whose events cluster in time *because that is how
it was built*, and the entity-level pair test then reports max pair 67 against a null
of 28.7, p_rot = 0.005, on nosis/SOL buys. The same test at wallet level on the same
data reports max pair 9 against a null of 9.3, p_rot = 0.552.

The resolution adopted here: entity grouping is correct and is used for the
OUTCOME analyses (P&L, round trips, the adversarial read), where the concern it
answers — one operator counted many times — is real. For the TIMING test it is
circular, so wallet level is primary and entity level is reported beside it as a
demonstration of the artifact. Both are printed; neither is hidden.

A NULL IS A RESULT, BUT ONLY IF IT COMES WITH AN MDE
-----------------------------------------------------
"Not detectable" is worth nothing without knowing what would have been detectable.
Section 6 injects a synthetic copier into the real tape at a known lag and counts
how often the test finds it. Apesteguia (Mgmt Sci 2020) reports that real copy
graphs are extremely heavy-tailed — 20.7-59.5% of copied leaders have exactly ONE
copier, and the top 5% of leaders hold 61-93% of all copy relationships — so the
detector must be judged on its ability to find a SINGLE follower, not a crowd.

ON THE 14%-VS-3% NUMBER WE HAVE BEEN CITING
--------------------------------------------
PROGRAM.md 4 records "identified smart money averages ~14%/trade while a copier
gets ~3% from bonding-curve imitation penalty alone." Reading the source
(memecoin-copytrading-manipulative-bots-2601.08641) changes what that sentence can
support. The 14.4% is measured. The 2.9% is NOT: the copier in that paper is a
closed-form construct (Lemma 1 / Theorem 2), a hypothetical one-to-one immediate
imitator evaluated analytically on the leader's trade sequence. No copier was ever
observed. The paper contains no leader-follower detector, no lag distribution, and
no empirical copier at all. Its mechanism is exact and portable —

    cost ratio = Y / (Y - 2d)      Y = effective reserve, d = leader's clip

— and Sections 7 and 8 evaluate it on our own pools, where d/Y is three orders of
magnitude smaller than on a fresh bonding curve. The conclusion does not transfer.

USAGE
-----
    python3 studies/copytrading.py                      # live tape only
    python3 studies/copytrading.py --bq-dir DIR         # + full-day replication
    python3 studies/copytrading.py --sql                # print the BigQuery SQL

The BigQuery replication needs two artifacts in --bq-dir, both regenerable and both
documented by --sql:
    swaps/<YYYYMMDD>.jsonl   scripts/bulk_history.py pull --with-signers  (531 GB, $3.02)
    cp_<YYYYMMDD>.json       the full-balance query printed by --sql      (248 GB, $1.41)
The second exists because bulk_history filters token balances to pool-owned accounts,
which is enough for reserves but throws away the non-pool owner whose delta identifies
the TRADER. The columns are already read either way, so the marginal cost is only the
partition scan. Counterparty derived this way agreed with the live collector's
independent parse on 791 of 791 overlapping swaps, and side on 791 of 791.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import random
import statistics
from itertools import pairwise
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
LIVE_TAPE = ROOT / "state" / "cluster_tape" / "swaps"
BOARDS = ROOT / "state" / "boards"

WSOL = "So11111111111111111111111111111111111111112"

#: `AgmLJBMD..` is the gas-sponsoring relayer for FOMO (fomo.family), the social
#: trading + copy-trading app. Identified three independent ways, not guessed:
#:   1. Manifest DEX's `client/ts/src/aggregators.ts` lists it in ORIGINATING_PROTOCOL_IDS
#:      as 'fomo', beside verified entries for jupiter, phantom, binance, coinbase.
#:   2. Its transactions pay USDC into `R4rNJHaffSUotNmqSKNEfDcJE8A7zJUkaoM5Jkd7cYX`,
#:      which DefiLlama's fee adapter defines as FOMO's fee wallet (43 of 60 sampled).
#:   3. Structure: always fee payer, always multi-signer, 30 distinct co-signers in 30
#:      sampled transactions, 0% failure rate — pre-simulated retail order flow.
#: THE MECHANISM MATTERS AND IT IS NOT AUTO-MIRRORING. FOMO's own documentation:
#: "When a trader you follow buys or sells a token, you receive a notification and can
#: choose to make the same trade. Copy trading gives you control — you decide whether to
#: execute each trade." So FOMO follow-trades land at HUMAN reaction latency, not bot
#: latency. That is a prediction about the lag distribution, and Section 3 tests it.
FOMO_RELAYER = "AgmLJBMDCqWynYnQiPCuj9ewsNNsBJXyzoUhD9LJzN51"

#: Jupiter's gasless sponsor wallet, named in Jupiter's own docs. It fires when the taker
#: holds < 0.01 SOL, so it is a CROSS-APP artifact: a hit means "routed through Jupiter
#: gasless", never "user of app X". Kept labelled so it is never read as one venue.
JUPITER_GASLESS = "gasTzr94Pmp4Gf8vknQnqxeYxdgwFjbgdJa4msYRpnB"

KNOWN_RELAYER = {FOMO_RELAYER: "FOMO (fomo.family)", JUPITER_GASLESS: "Jupiter gasless"}

#: shitcoims_cluster/pools.py is the on-chain-verified authority; this mirrors it for
#: labelling only. Nothing here trusts the symbol — pool address is the key throughout.
POOL_LABEL: dict[str, str] = {
    "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn": "weave/SOL",
    "7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc": "nosis/SOL",
    "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU": "DREGG/SOL",
    "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr": "SOLVE/SOL",
    "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD": "weave/nosis",
    "FNxnyS3hkVJDUvQmP9LYGLUg9icvc7n4ZwTTQ3R1vtJD": "DREGG/nosis",
}
POOL_SET = frozenset(POOL_LABEL)

#: The operator's four mints, for the boards check. Prefixes only — full mints live in
#: pools.py and the prefix is unambiguous at 8 chars.
OPERATOR_MINT_PREFIX = {"8PecVcCG": "weave", "FPfi9q1A": "nosis",
                        "XkeTXo11": "DREGG", "GwyWFsDK": "SOLVE"}

#: PumpSwap constant-product fee, recovered exactly from DREGG/SOL and SOLVE/SOL where
#: the vault balances ARE the curve: implied g = 1 - fee = 0.99800 on every trade, both
#: directions, p05 == p95. Not assumed; measured. See Section 7.
AMM_G = 0.998

BQ_SQL_FULL_BALANCES = """\
-- Trader identity for every swap touching a cluster pool, one UTC day.
-- bulk_history.py filters pre/post_token_balances to pool-owned accounts, which
-- keeps reserves but discards the non-pool owner whose delta identifies the trader.
-- The balance columns are read in full either way (BigQuery bills columns, not
-- predicates), so this costs only the partition scan again: 247.6 GB = $1.41.
-- Dry-run bound was 247.575554919 GB; run it with --maximum_bytes_billed as a cap.
--
-- NOTE: do NOT add `AND err IS NULL`. On this table that predicate makes the planner
-- estimate 0 bytes and return nothing. The `EXISTS` clause below already requires a
-- pool vault to have MOVED, and a failed transaction moves nothing.
SELECT signature, block_slot, index AS tx_index, UNIX_SECONDS(block_timestamp) AS block_time,
  ARRAY(SELECT AS STRUCT owner, mint, CAST(amount AS STRING) AS amount, decimals, account_index
        FROM UNNEST(pre_token_balances)) AS pre,
  ARRAY(SELECT AS STRUCT owner, mint, CAST(amount AS STRING) AS amount, decimals, account_index
        FROM UNNEST(post_token_balances)) AS post
FROM `bigquery-public-data.crypto_solana_mainnet_us.Transactions`
WHERE block_timestamp >= TIMESTAMP('{day}') AND block_timestamp < TIMESTAMP('{next_day}')
  AND EXISTS(
    SELECT 1 FROM UNNEST(post_token_balances) po
    JOIN UNNEST(pre_token_balances) pr ON pr.account_index = po.account_index
    WHERE po.owner IN ({pool_list})
      AND CAST(po.amount AS BIGNUMERIC) != CAST(pr.amount AS BIGNUMERIC))
"""


# --------------------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------------------

class Event(dict):
    """One realised swap. `trader` is the identified counterparty, never the fee payer.

    shitcoims_cluster/parse.py is explicit that an unidentified counterparty means NOT
    IDENTIFIED and must never fall back to the signer — "attributing a routed fill to the
    signer would fabricate exactly the kind of provenance this project lost 7.47 SOL to."
    Events without a trader are dropped from every wallet-level statistic and counted.
    """

    @property
    def price(self) -> float:
        """Realised SOL per token. Model-free: read off the two exact leg amounts."""
        ai = self["in_raw"] / 10 ** self["in_dec"]
        ao = self["out_raw"] / 10 ** self["out_dec"]
        return (ai / ao) if self["side"] == "buy" else (ao / ai)

    @property
    def sol(self) -> float:
        return (self["in_raw"] / 1e9) if self["side"] == "buy" else (self["out_raw"] / 1e9)

    @property
    def tokens(self) -> float:
        return (self["out_raw"] / 10 ** self["out_dec"]) if self["side"] == "buy" \
            else (self["in_raw"] / 10 ** self["in_dec"])


def _mk_event(*, sig: str, pool: str, slot: int, tx_index: int | None, t: int,
              side: str | None, in_mint: str, in_raw: int, in_dec: int,
              out_mint: str, out_raw: int, out_dec: int, trader: str | None,
              payer: str | None, signers: Sequence[str], dex: str | None,
              reserves: dict[str, tuple[int, int]] | None) -> Event:
    return Event(sig=sig, pool=pool, label=POOL_LABEL.get(pool, pool[:8]), slot=slot,
                 tx_index=tx_index, t=t, side=side, in_mint=in_mint, in_raw=in_raw,
                 in_dec=in_dec, out_mint=out_mint, out_raw=out_raw, out_dec=out_dec,
                 trader=trader, payer=payer, signers=list(signers), dex=dex,
                 reserves=reserves)


def load_live(tape: Path) -> tuple[list[Event], dict[str, int]]:
    """The live RPC collector's tape. Exact counterparty, exact reserves, no tx_index.

    parse.py documents the tx_index gap: getTransaction returns a slot but no block
    index, so two transactions in the same slot are unordered here. That is precisely
    why the copy signature requires lag >= 1 slot rather than trying to order within one.
    """
    out: list[Event] = []
    stats: collections.Counter[str] = collections.Counter()
    for path in sorted(glob.glob(str(tape / "*.jsonl"))):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    stats["undecodable"] += 1
                    continue
                if r.get("kind") != "swap":
                    stats["kind:" + str(r.get("kind"))] += 1
                    continue
                vaults = (r.get("reserves") or {}).get("vaults") or []
                if len(vaults) != 2:
                    stats["vaults!=2"] += 1
                    continue
                dec = {v["mint"]: int(v["decimals"]) for v in vaults}
                res = {v["mint"]: (int(v["pre_raw"]), int(v["post_raw"])) for v in vaults}
                tin, tout = r.get("token_in_mint"), r.get("token_out_mint")
                if not tin or not tout or tin not in dec or tout not in dec:
                    stats["mints missing"] += 1
                    continue
                out.append(_mk_event(
                    sig=r["chain"]["signature"], pool=r["pool"], slot=int(r["chain"]["slot"]),
                    tx_index=None, t=int(r["chain"]["block_time"]), side=r.get("side"),
                    in_mint=tin, in_raw=int(r["token_in_raw"]), in_dec=dec[tin],
                    out_mint=tout, out_raw=int(r["token_out_raw"]), out_dec=dec[tout],
                    trader=r.get("counterparty"), payer=r.get("fee_payer"),
                    signers=r.get("signers") or [], dex=r.get("dex"), reserves=res))
                stats["ok"] += 1
    return out, dict(stats)


def _counterparty(pre: dict[int, dict], post: dict[int, dict], *, pool: str,
                  in_mint: str, out_mint: str, in_raw: int, out_raw: int) -> str | None:
    """The one non-pool owner whose delta EXACTLY mirrors the pool on a leg, else None.

    Reimplements shitcoims_cluster.parse._counterparty against BigQuery's balance arrays.
    Equality, never tolerance: a magnitude tolerance would quietly admit a router's
    intermediate account. Ambiguity (two owners matching, or none) returns None.
    """
    per: dict[str, dict[str, int]] = {}
    for i in set(pre) | set(post):
        e = post.get(i) or pre.get(i)
        owner, mint = e.get("owner"), e.get("mint")
        if not isinstance(owner, str) or not isinstance(mint, str) or owner == pool:
            continue
        d = int(post[i]["amount"]) if i in post else 0
        d -= int(pre[i]["amount"]) if i in pre else 0
        per.setdefault(owner, {}).setdefault(mint, 0)
        per[owner][mint] += d
    hits = {o for o, dd in per.items()
            if dd.get(in_mint, 0) == -in_raw or dd.get(out_mint, 0) == out_raw}
    return next(iter(hits)) if len(hits) == 1 else None


def load_chain_rows_bq(bq_dir: Path) -> list[tuple[str, int, str, dict[str, tuple[int, int]]]]:
    """Same chain audit inputs for the BigQuery day: every reserve-bearing row, not just swaps."""
    rows: list[tuple[str, int, str, dict[str, tuple[int, int]]]] = []
    for path in sorted(glob.glob(str(bq_dir / "swaps" / "*.jsonl"))):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("kind") not in ("swap", "reference", "liquidity"):
                    continue
                v = (r.get("reserves") or {}).get("vaults") or []
                if not v or r["pool"] not in POOL_SET:
                    continue
                rows.append((r["pool"], int(r["chain"]["slot"]), r["chain"]["signature"],
                             {x["mint"]: (int(x["pre_raw"]), int(x["post_raw"])) for x in v}))
    return rows


def load_bq(bq_dir: Path) -> tuple[list[Event], dict[str, int]]:
    """Full-day BigQuery replication: exact counterparty AND tx_index (intra-slot order)."""
    meta: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(glob.glob(str(bq_dir / "swaps" / "*.jsonl"))):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("kind") != "swap":
                    continue
                meta[(r["chain"]["signature"], r["pool"])] = r
    out: list[Event] = []
    stats: collections.Counter[str] = collections.Counter()
    for path in sorted(glob.glob(str(bq_dir / "cp_*.json"))):
        with open(path) as fh:
            rows = json.load(fh)
        for r in rows:
            pre = {int(b["account_index"]): b for b in r["pre"]}
            post = {int(b["account_index"]): b for b in r["post"]}
            moved: dict[str, dict[str, tuple[int, int]]] = collections.defaultdict(dict)
            for i in set(pre) | set(post):
                e = post.get(i) or pre.get(i)
                if e["owner"] not in POOL_SET:
                    continue
                a0 = int(pre[i]["amount"]) if i in pre else 0
                a1 = int(post[i]["amount"]) if i in post else 0
                moved[e["owner"]][e["mint"]] = (a0, a1)
            cands = [(p, v) for p, v in moved.items()
                     if len(v) == 2 and any(a1 != a0 for a0, a1 in v.values())]
            if len(cands) != 1:
                stats["not-exactly-1-pool"] += 1
                continue
            pool, v = cands[0]
            legs = sorted(v.items(), key=lambda kv: kv[1][1] - kv[1][0])
            (om, (o0, o1)), (im, (i0, i1)) = legs[0], legs[1]
            in_raw, out_raw = i1 - i0, o0 - o1
            if in_raw <= 0 or out_raw <= 0:
                stats["bad-legs"] += 1
                continue
            m = meta.get((r["signature"], pool))
            if m is None:
                stats["no-bulk-row"] += 1
                continue
            dec = {x["mint"]: int(x["decimals"]) for x in m["reserves"]["vaults"]}
            side = None
            if WSOL in (im, om):
                side = "buy" if im == WSOL else "sell"
            out.append(_mk_event(
                sig=r["signature"], pool=pool, slot=int(r["block_slot"]),
                tx_index=int(r["tx_index"]), t=int(r["block_time"]), side=side,
                in_mint=im, in_raw=in_raw, in_dec=dec.get(im, 0),
                out_mint=om, out_raw=out_raw, out_dec=dec.get(om, 0),
                trader=_counterparty(pre, post, pool=pool, in_mint=im, out_mint=om,
                                     in_raw=in_raw, out_raw=out_raw),
                payer=(m.get("signers") or [None])[0], signers=m.get("signers") or [],
                dex=m.get("dex"),
                reserves={x["mint"]: (int(x["pre_raw"]), int(x["post_raw"]))
                          for x in m["reserves"]["vaults"]}))
            stats["ok"] += 1
    return out, dict(stats)


_ED_P = 2 ** 255 - 19
_ED_D = (-121665 * pow(121666, _ED_P - 2, _ED_P)) % _ED_P
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + _B58.index(c)
    body = n.to_bytes(40, "big").lstrip(b"\0")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + body


def on_curve(addr: str) -> bool | None:
    """True if `addr` is a real ed25519 public key, i.e. an account that CAN sign.

    A pool, a vault, or any program-derived address is off the curve by construction —
    PDA derivation bumps until it lands off-curve precisely so nobody holds its key.
    This is pure arithmetic: no RPC, no label list, no maintenance.

    IT CATCHES A LIVE DEFECT. `shitcoims_cluster.parse._counterparty` excludes only the
    pool being traded (`owner == pool`), so any OTHER pool that happens to hold the mint
    can satisfy the exact-mirror test and be recorded as the trader. On the 2026-08-13
    tape that admits 16 such accounts carrying 584 of 7,760 swaps (7.5%), the largest
    being `C889ex3M..` at 304 swaps — an off-curve Meteora DLMM lb_pair (nosis/wSOL),
    owned by `LBUZKhRx..`, which is a POOL and has never signed anything. Left in, it is
    the second most profitable "wallet" in the tape at +68.9 SOL realised, which is not
    profit but reserve movement. Any smart-money leaderboard built on this tape would
    have ranked a liquidity pool second.
    """
    try:
        b = _b58decode(addr)
    except (ValueError, KeyError):
        return None
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign = (y >> 255) & 1
    y &= (1 << 255) - 1
    if y >= _ED_P:
        return False
    u = (y * y - 1) % _ED_P
    v = (_ED_D * y * y + 1) % _ED_P
    x = pow((u * pow(v, _ED_P - 2, _ED_P)) % _ED_P, (_ED_P + 3) // 8, _ED_P)
    if (v * x * x - u) % _ED_P != 0:
        x = (x * pow(2, (_ED_P - 1) // 4, _ED_P)) % _ED_P
        if (v * x * x - u) % _ED_P != 0:
            return False
    return not (x == 0 and sign == 1)


def validate_on_curve_guard(events: Sequence[Event]) -> None:
    """Hard invariant: every address that SIGNED a transaction must be on the curve.

    A signature requires the private key, and a private key requires an on-curve point, so a
    signer that tests off-curve would be a bug in `on_curve` — a false positive that silently
    deletes real wallets. Checking it costs nothing and makes the guard falsifiable rather
    than merely plausible. Measured on the live tape: 970 distinct signers, 0 off-curve.
    """
    signers = {s for e in events for s in e["signers"]}
    bad = [s for s in signers if on_curve(s) is False]
    status = "OK" if not bad else f"BUG — {len(bad)} signers test off-curve: {bad[:3]}"
    print(f"      guard check: {len(signers):,} distinct signers, all on-curve? {status}")


def tradeable(events: Iterable[Event], *, report: bool = False) -> list[Event]:
    """Events usable for wallet-level work: identified trader, a real KEYPAIR, SOL-quoted.

    Three exclusions, in order of how much damage they do if skipped:
      - unidentified counterparty  — parse.py's None means NOT IDENTIFIED, never the signer
      - off-curve address          — a pool or PDA masquerading as a trader (see on_curve)
      - non-SOL-quoted leg         — token/token swaps have no non-arbitrary direction
    """
    out, dropped = [], collections.Counter()
    for e in events:
        w = e["trader"]
        if not w:
            dropped["unidentified counterparty"] += 1
        elif w in POOL_SET:
            dropped["cluster pool as trader"] += 1
        elif on_curve(w) is False:
            dropped["off-curve (pool/PDA, cannot sign)"] += 1
        elif e["side"] not in ("buy", "sell"):
            dropped["not SOL-quoted"] += 1
        else:
            out.append(e)
            continue
    if report and dropped:
        for k, v in dropped.most_common():
            print(f"      dropped {v:>6}  {k}")
    return out


# --------------------------------------------------------------------------------------
# 0. Completeness
# --------------------------------------------------------------------------------------

def load_chain_rows(tape: Path) -> list[tuple[str, int, str, dict[str, tuple[int, int]]]]:
    """Every row that carries reserves, not just swaps.

    Liquidity adds/removes move the vaults too, so a chain audit over swaps ALONE reports
    a false gap wherever an LP event landed. `reference` rows (delta 0) are harmless and
    densify the chain. Including all three is the difference between "4 GAPS" and "0" on
    weave/nosis.
    """
    rows: list[tuple[str, int, str, dict[str, tuple[int, int]]]] = []
    for path in sorted(glob.glob(str(tape / "*.jsonl"))):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("kind") not in ("swap", "reference", "liquidity"):
                    continue
                v = (r.get("reserves") or {}).get("vaults") or []
                if not v:
                    continue
                rows.append((r["pool"], int(r["chain"]["slot"]), r["chain"]["signature"],
                             {x["mint"]: (int(x["pre_raw"]), int(x["post_raw"])) for x in v}))
    return rows


def certify_completeness(events: Sequence[Event],
                         chain_rows: Sequence[tuple[str, int, str, dict]] | None = None) -> None:
    """A missing swap breaks the reserve chain. This is an exact, free, offline audit.

    parse.py measured that every adjacent pair of single-transaction slots chains exactly
    (post_raw == pre_raw). Turned around, that is a COMPLETENESS CERTIFICATE: if the tape
    dropped a swap between two observed single-tx slots, the chain breaks. It says nothing
    about what happened before the collector started, only that nothing is missing inside
    the recorded window — which is the property a burst detector actually needs.

    Cross-checked against BigQuery, which is the reason to trust it: for every pool-hour
    after the collector's first partial hour, the live tape's signature set and BigQuery's
    are IDENTICAL in both directions (nosis 149/149, 159/159, 203/203; weave 18/18, 58/58,
    48/48; SOLVE 133/133 for the whole day) — 0 missing, 0 extra. The apparent 91% shortfall
    on 2026-08-13 is entirely the hours before each pool's collector started, not sampling.
    """
    print("\n0. COMPLETENESS  — a dropped swap breaks the reserve chain; count the breaks")
    print("   A burst detector on a sampled tape measures nothing. This is not a spot check.")
    by_pool: dict[str, list[Any]] = collections.defaultdict(list)
    if chain_rows:
        for pool, slot, sig, res in chain_rows:
            by_pool[pool].append(Event(pool=pool, slot=slot, sig=sig, reserves=res))
    else:
        for e in events:
            if e["reserves"]:
                by_pool[e["pool"]].append(e)
    print(f"   {'pool':14s}{'rows':>8}{'chained':>9}{'breaks':>8}   verdict")
    for pool, rows in sorted(by_pool.items(), key=lambda kv: -len(kv[1])):
        rows.sort(key=lambda e: (e["slot"], e["sig"]))
        per_slot: dict[int, list[Event]] = collections.defaultdict(list)
        for e in rows:
            per_slot[e["slot"]].append(e)
        prev: dict[str, tuple[int, int]] | None = None
        chained = breaks = 0
        sizes: list[float] = []
        for s in sorted(per_slot):
            grp = per_slot[s]
            if len(grp) != 1:
                prev = None          # intra-slot order unknown -> cannot chain across
                continue
            cur = grp[0]["reserves"]
            if prev is not None:
                rel = [abs(cur[m][0] - prev[m][1]) / max(1, prev[m][1])
                       for m in cur if m in prev]
                if max(rel, default=0.0) == 0.0:
                    chained += 1
                else:
                    breaks += 1
                    sizes.append(max(rel))
            prev = cur
        rate = breaks / max(1, chained + breaks)
        # A MISSING SWAP moves a reserve by a trade-sized fraction; a dust transfer into the
        # vault moves it by ~0. Reporting the magnitude is what separates "the tape dropped a
        # fill" from "someone sent tokens to the pool" — and §9(b) shows the latter really
        # happens here, to the tune of 4.8% (nosis) and 8.8% (weave) of accumulated excess.
        if breaks == 0:
            verdict = "complete in window"
        elif rate < 0.02:
            verdict = (f"{rate * 100:.2f}% unchained, median jump "
                       f"{statistics.median(sizes) * 100:.2f}% of reserve — a few uncaptured events")
        else:
            verdict = (f"{rate * 100:.1f}% GAPS, median jump "
                       f"{statistics.median(sizes) * 100:.2f}% — DO NOT TRUST")
        print(f"   {POOL_LABEL.get(pool, pool[:8]):14s}{len(rows):>8}{chained:>9}{breaks:>8}   {verdict}")


# --------------------------------------------------------------------------------------
# 1. Venue map — where app-mediated flow is actually visible
# --------------------------------------------------------------------------------------

def venue_map(events: Sequence[Event]) -> dict[str, set[str]]:
    """One fee payer paying for many DIFFERENT traders is an app relayer. That is a
    mechanical observation, not an inference.

    parse.py computes `counterparty_paid_fee` as a tri-state precisely because "did the
    trader pay their own fee" is the informative question. When they did not, someone
    else did, and that someone is infrastructure: a trading terminal, a gas sponsor, or
    a copy-trading engine. Which of the three it is, is what Section 5 tests.
    """
    print("\n1. VENUE MAP  — fee payer serving many distinct traders = app-mediated flow")
    p2t: dict[str, set[str]] = collections.defaultdict(set)
    for e in events:
        if e["payer"]:
            p2t[e["payer"]].add(e["trader"])
    traders = {e["trader"] for e in events}
    multi = sorted(((p, ts) for p, ts in p2t.items() if len(ts) > 1), key=lambda kv: -len(kv[1]))
    print(f"   {len(traders):,} distinct traders · {len(p2t):,} distinct fee payers · "
          f"{len(multi):,} payers serve >1 trader")
    print(f"   {'fee payer':46s}{'traders':>9}{'swaps':>7}{'share':>8}   identified as")
    for p, ts in multi[:6]:
        n = sum(1 for e in events if e["payer"] == p)
        print(f"   {p:46s}{len(ts):>9}{n:>7}{len(ts) / len(traders) * 100:>7.1f}%   "
              f"{KNOWN_RELAYER.get(p, '—')}")
    if multi:
        top, ts = multi[0]
        print(f"   -> {KNOWN_RELAYER.get(top, top[:12] + '..')} relays "
              f"{len(ts) / len(traders) * 100:.0f}% of all traders seen on the operator's coins.")
    print("\n   THE BLIND SPOT, measured rather than hand-waved. This test finds GAS-SPONSORED")
    print("   relayers only. Sampling 30 recent transactions at each product's known fee")
    print("   wallet: FOMO and Jupiter-gasless are 30/30 multi-signer with a shared payer;")
    print("   Trojan, BullX, Photon, GMGN, Axiom, Bloom, Maestro, Nova, Banana Gun, Pepeboost")
    print("   and Vector are all 30/30 SINGLE-signer — the app hands the user a keypair and")
    print("   that wallet pays its own gas. Their flow is INDISTINGUISHABLE from an ordinary")
    print("   wallet here and can only be found via each product's fee wallet, which we do")
    print("   not collect. So this is a LOWER BOUND on app-mediated share, not an estimate.")
    return dict(p2t)


# --------------------------------------------------------------------------------------
# 2. Entity resolution
# --------------------------------------------------------------------------------------

def resolve_entities(events: Sequence[Event], min_coslot: int = 2) -> dict[str, str]:
    """Union wallets that land in the same (pool, slot) at least `min_coslot` times.

    The justification is the one the literature uses (2601.08641 Alg. 1): with no public
    mempool and a ~400 ms block, repeated same-slot co-occurrence "is unlikely to be
    achieved by independent frontrunners and instead indicates pre-coordinated control."

    It is also, on this data, an over-merge waiting to happen — independent bots racing
    the same opportunity co-slot too — and it is CIRCULAR as input to a timing test.
    Both facts are measured and printed rather than argued about.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    per_slot: dict[tuple[str, int], set[str]] = collections.defaultdict(set)
    for e in events:
        per_slot[(e["pool"], e["slot"])].add(e["trader"])
    pair: collections.Counter[tuple[str, str]] = collections.Counter()
    for ws in per_slot.values():
        s = sorted(ws)
        for i in range(len(s)):
            for j in range(i + 1, len(s)):
                pair[(s[i], s[j])] += 1
    links = 0
    for (a, b), c in pair.items():
        if c >= min_coslot:
            union(a, b)
            links += 1
    wallets = {e["trader"] for e in events}
    mapping = {w: find(w) for w in wallets}
    sizes = collections.Counter(mapping.values())
    multi = sorted((v for v in sizes.values() if v > 1), reverse=True)
    print("\n2. ENTITY RESOLUTION  — co-slot union-find (threshold: >= "
          f"{min_coslot} same-slot co-occurrences)")
    print(f"   {len(wallets):,} wallets -> {len(set(mapping.values())):,} entities "
          f"({links:,} qualifying pair links)")
    print(f"   multi-wallet entity sizes: {multi[:12]}{' ...' if len(multi) > 12 else ''}")
    if multi and multi[0] >= 20:
        print(f"   WARNING: largest entity has {multi[0]} wallets. This rule merges on TEMPORAL")
        print("   proximity, so feeding it into a TEMPORAL test is circular. Section 4 runs both")
        print("   levels and the divergence is the point — wallet level is primary.")
    return mapping


# --------------------------------------------------------------------------------------
# 3-4. The copy signature: correlogram and pair-level test
# --------------------------------------------------------------------------------------

def _cross_correlogram(pts: Sequence[tuple[int, str]], max_lag: int) -> collections.Counter[int]:
    """Ordered cross-wallet pair counts by slot lag. Lag 0 is same-slot and is EXCLUDED
    downstream as atomic/bundle; it is counted here only so the exclusion is visible."""
    pts = sorted(pts)
    h: collections.Counter[int] = collections.Counter()
    n = len(pts)
    for i in range(n):
        si, wi = pts[i]
        for j in range(i + 1, n):
            sj, wj = pts[j]
            d = sj - si
            if d > max_lag:
                break
            if wj != wi:
                h[d] += 1
    return h


def _null_perm(pts: Sequence[tuple[int, str]], rng: random.Random) -> list[tuple[int, str]]:
    slots = [a for a, _ in pts]
    labs = [b for _, b in pts]
    rng.shuffle(labs)
    return list(zip(slots, labs, strict=True))


def _null_rot(pts: Sequence[tuple[int, str]], rng: random.Random) -> list[tuple[int, str]]:
    p = sorted(pts)
    slots = [a for a, _ in p]
    labs = [b for _, b in p]
    k = rng.randrange(1, len(labs))
    return list(zip(slots, labs[k:] + labs[:k], strict=True))


def _null_uniform(pts: Sequence[tuple[int, str]], rng: random.Random) -> list[tuple[int, str]]:
    """The NAIVE null: each wallet keeps its trade COUNT, times redrawn uniformly over the
    span. This is what "time-shuffled preserving each wallet's rate" sounds like it means,
    and it is wrong here — it destroys the market's aggregate burstiness along with the
    wallet association, so ordinary momentum reads as copy-trading. Kept and reported so
    the size of the error is on the record."""
    lo = min(a for a, _ in pts)
    span = max(a for a, _ in pts) - lo + 1
    cnt = collections.Counter(b for _, b in pts)
    return [(lo + rng.randrange(span), w) for w, c in cnt.items() for _ in range(c)]


def correlogram_test(events: Sequence[Event], mapping: dict[str, str] | None,
                     *, nsim: int, seed: int, max_lag: int = 200, min_n: int = 200) -> None:
    print("\n3. THE COPY SIGNATURE — cross-wallet same-direction density by slot lag")
    print("   Statistic: ordered pairs (i,j), same pool, same side, DIFFERENT wallet,")
    print("   slot_j - slot_i = lag. Copying would show EXCESS at small positive lag.")
    key: Callable[[Event], str] = (lambda e: mapping[e["trader"]]) if mapping else (lambda e: e["trader"])
    grp: dict[tuple[str, str], list[tuple[int, str]]] = collections.defaultdict(list)
    for e in events:
        grp[(e["label"], e["side"])].append((e["slot"], key(e)))
    rng = random.Random(seed)
    buckets = [(0, 0), (1, 1), (2, 2), (3, 5), (6, 10), (11, 25), (26, 75), (76, 200)]
    for k in sorted(grp, key=lambda k: -len(grp[k])):
        pts = grp[k]
        if len(pts) < min_n:
            continue
        obs = _cross_correlogram(pts, max_lag)
        sims = {name: [_cross_correlogram(fn(pts, rng), max_lag) for _ in range(nsim)]
                for name, fn in (("perm", _null_perm), ("rot", _null_rot), ("unif", _null_uniform))}
        print(f"\n   === {k[0]} {k[1]}   n={len(pts)}  units={len(set(w for _, w in pts))}")
        print(f"   {'lag':>9}{'observed':>10}{'PERM':>9}{'ROT':>9}{'naive':>9}"
              f"{'obs/ROT':>9}{'p_perm':>8}{'p_rot':>8}")
        for a, b in buckets:
            o = sum(obs[d] for d in range(a, b + 1))
            tot = {nm: [sum(h[d] for d in range(a, b + 1)) for h in hs] for nm, hs in sims.items()}
            mp, mr, mu = (statistics.mean(tot[x]) for x in ("perm", "rot", "unif"))
            pp = (sum(1 for v in tot["perm"] if v >= o) + 1) / (nsim + 1)
            pr = (sum(1 for v in tot["rot"] if v >= o) + 1) / (nsim + 1)
            tag = "  <- same-slot: ATOMIC/BUNDLE, excluded" if a == 0 else ""
            print(f"   {a:>4}-{b:<4}{o:>10}{mp:>9.1f}{mr:>9.1f}{mu:>9.1f}"
                  f"{(o / mr if mr else float('nan')):>8.2f}x{pp:>8.3f}{pr:>8.3f}{tag}")


def _pair_counts(pts: Sequence[tuple[int, str]], delta: int) -> collections.Counter[tuple[str, str]]:
    """n_AB = number of leader-events of A followed, within `delta` slots, by a B event.
    A follower is counted ONCE per leader event, so a wallet that slices six clips behind
    one leader trade scores 1, not 6."""
    pts = sorted(pts)
    c: collections.Counter[tuple[str, str]] = collections.Counter()
    n = len(pts)
    for i in range(n):
        si, wi = pts[i]
        seen: set[str] = set()
        for j in range(i + 1, n):
            sj, wj = pts[j]
            if sj - si > delta:
                break
            if sj - si < 1 or wj == wi or wj in seen:
                continue
            seen.add(wj)
            c[(wi, wj)] += 1
    return c


def pair_test(events: Sequence[Event], mapping: dict[str, str] | None, *,
              deltas: Sequence[int], nsim: int, seed: int, min_n: int = 200,
              level: str = "WALLET") -> None:
    """Family-wise test by MAX STATISTIC, which is the right multiplicity control here.

    The aggregate correlogram has no power against a heavy-tailed copy graph: Apesteguia
    reports 20.7-59.5% of copied leaders have exactly ONE copier. So the question is not
    "is flow more clustered" but "is there ANY ordered pair too tight to be chance". The
    null distribution of the MAXIMUM pair count over all pairs controls the family-wise
    error rate exactly, without Bonferroni's conservatism over ~10^5 pairs.
    """
    key: Callable[[Event], str] = (lambda e: mapping[e["trader"]]) if mapping else (lambda e: e["trader"])
    grp: dict[tuple[str, str], list[tuple[int, str]]] = collections.defaultdict(list)
    for e in events:
        grp[(e["label"], e["side"])].append((e["slot"], key(e)))
    rng = random.Random(seed)
    print(f"\n4. PAIR-LEVEL MAX-STATISTIC TEST — {level} level")
    print(f"   {'delta':>6}{'pool':>13}{'side':>6}{'n':>7}{'units':>7}{'pairs':>8}{'max n_AB':>10}"
          f"{'null PERM':>11}{'null ROT':>10}{'p_perm':>8}{'p_rot':>8}")
    for delta in deltas:
        for k in sorted(grp, key=lambda k: -len(grp[k])):
            pts = grp[k]
            if len(pts) < min_n:
                continue
            obs = _pair_counts(pts, delta)
            if not obs:
                continue
            mx = max(obs.values())
            np_ = [max(c.values()) if (c := _pair_counts(_null_perm(pts, rng), delta)) else 0
                   for _ in range(nsim)]
            nr = [max(c.values()) if (c := _pair_counts(_null_rot(pts, rng), delta)) else 0
                  for _ in range(nsim)]
            pp = (sum(1 for v in np_ if v >= mx) + 1) / (nsim + 1)
            pr = (sum(1 for v in nr if v >= mx) + 1) / (nsim + 1)
            print(f"   {delta:>6}{k[0]:>13}{k[1]:>6}{len(pts):>7}"
                  f"{len(set(w for _, w in pts)):>7}{len(obs):>8}{mx:>10}"
                  f"{statistics.mean(np_):>11.1f}{statistics.mean(nr):>10.1f}{pp:>8.3f}{pr:>8.3f}")


# --------------------------------------------------------------------------------------
# 5. Is the app relayer a COPY engine?
# --------------------------------------------------------------------------------------

def app_cohort_test(events: Sequence[Event], payer: str, *, nsim: int, seed: int,
                    delta: int = 25, min_n: int = 25) -> None:
    """The sharpest available test, because it needs no inference about who follows whom.

    If a relayer is a copy-trading engine, its OWN users must fire together: many distinct
    wallets, same coin, same direction, within seconds. If it is a trading terminal or a
    gas sponsor, its users arrive independently. The null draws each cohort wallet's trade
    times from the POOL'S OWN observed event times, so the comparison is against the
    market's real intensity, not a flat line.
    """
    rng = random.Random(seed)
    print(f"\n5. APP COHORT TEST — is {payer[:12]}.. a COPY engine or just a terminal?")
    print(f"   Cross-wallet same-direction pairs within {delta} slots, among that relayer's")
    print("   own flow only. Null: same wallets, same counts, times drawn from the pool's")
    print("   own event times (so the market's burstiness is held fixed).")
    print(f"   {'pool':13s}{'side':>6}{'swaps':>7}{'wallets':>9}{'observed':>10}{'null':>9}{'p':>8}")
    grp: dict[tuple[str, str], list[Event]] = collections.defaultdict(list)
    for e in events:
        grp[(e["label"], e["side"])].append(e)
    any_run = False
    for k, all_ev in sorted(grp.items(), key=lambda kv: -len(kv[1])):
        cohort = [e for e in all_ev if e["payer"] == payer]
        if len(cohort) < min_n:
            continue
        any_run = True
        pts = [(e["slot"], e["trader"]) for e in cohort]
        obs = sum(_cross_correlogram(pts, delta)[d] for d in range(1, delta + 1))
        pool_slots = [e["slot"] for e in all_ev]
        cnt = collections.Counter(w for _, w in pts)
        sims = []
        for _ in range(nsim):
            fake = [(rng.choice(pool_slots), w) for w, c in cnt.items() for _ in range(c)]
            sims.append(sum(_cross_correlogram(fake, delta)[d] for d in range(1, delta + 1)))
        p = (sum(1 for v in sims if v >= obs) + 1) / (nsim + 1)
        print(f"   {k[0]:13s}{k[1]:>6}{len(cohort):>7}{len(cnt):>9}{obs:>10}"
              f"{statistics.mean(sims):>9.1f}{p:>8.3f}")
    if not any_run:
        print(f"   (no pool/side reached the {min_n}-swap minimum for this relayer)")


# --------------------------------------------------------------------------------------
# 6. Power / MDE
# --------------------------------------------------------------------------------------

def power_curve(events: Sequence[Event], *, nsim: int, seed: int, delta: int = 12,
                trials: int = 40, copied: Sequence[int] = (3, 5, 8, 12, 20)) -> None:
    """Inject a synthetic copier into the REAL tape and count detections.

    This is what turns "we found nothing" into a bounded claim. The copier mirrors a real
    leader's trades at a uniform lag in [1, delta] slots — the friendliest case, a perfect
    follower with no missed trades — so the resulting MDE is a LOWER bound on how much
    copying would be needed before a messier real copier became visible.
    """
    rng = random.Random(seed)
    grp: dict[tuple[str, str], list[tuple[int, str]]] = collections.defaultdict(list)
    for e in events:
        grp[(e["label"], e["side"])].append((e["slot"], e["trader"]))
    def n_leaders(k: tuple[str, str]) -> int:
        return sum(1 for c in collections.Counter(w for _, w in grp[k]).values() if c >= 20)

    # The arena needs BOTH volume and a choice of leaders. Picking purely on size lands on
    # nosis/SOL sell, which has 4 candidate leaders, and the answer then swings on which
    # one is drawn. Require >= 5 leaders where possible.
    eligible = [k for k in grp if n_leaders(k) >= 5] or list(grp)
    arena_key = max(eligible, key=lambda k: len(grp[k]))
    pts0 = grp[arena_key]
    counts = collections.Counter(w for _, w in pts0)
    leaders = [w for w, c in counts.items() if c >= 20]
    print("\n6. DETECTOR POWER (MDE) — inject a synthetic copier into the real tape")
    print(f"   arena: {arena_key[0]} {arena_key[1]}  n={len(pts0)}  wallets={len(counts)}  "
          f"candidate leaders (>=20 trades): {len(leaders)}")
    if not leaders:
        print("   no leader has >= 20 trades in this arena; power undefined")
        return
    print("   NOTE the ROT null is CONSERVATIVE against a clustered copier: rotation keeps the")
    print("   copier's own run of trades intact, so a copier that mirrors one burst stays hard")
    print("   to distinguish. The MDE below is therefore an upper bound on what is needed.")
    print(f"   copier mirrors N of one leader's trades at lag U[1,{delta}] slots;")
    print("   detection = max-statistic p<0.05 vs ROT null AND the top pair is the copier")
    print(f"   {'N copied':>10}{'detected':>10}   ({trials} trials each)")
    for f in copied:
        hits = 0
        for _ in range(trials):
            leader = rng.choice(leaders)
            lt = sorted(s for s, w in pts0 if w == leader)
            pick = rng.sample(lt, min(f, len(lt)))
            pts = list(pts0) + [(s + rng.randint(1, delta), "SYNTHETIC_COPIER") for s in pick]
            obs = _pair_counts(pts, delta)
            mx = max(obs.values())
            nr = [max(c.values()) if (c := _pair_counts(_null_rot(pts, rng), delta)) else 0
                  for _ in range(nsim)]
            p = (sum(1 for v in nr if v >= mx) + 1) / (nsim + 1)
            if p < 0.05 and max(obs, key=obs.get)[1] == "SYNTHETIC_COPIER":
                hits += 1
        print(f"   {f:>10}{hits / trials * 100:>9.0f}%")


# --------------------------------------------------------------------------------------
# 7. The curve, and the counterfactual imitation penalty
# --------------------------------------------------------------------------------------

def fit_curve(events: Sequence[Event]) -> dict[str, float]:
    """Recover each pool's EFFECTIVE token reserve from its own fills.

    Constant product with fee g gives, for one fill,
        g = (a_out * R_in) / (a_in * (R_out - a_out))
    Evaluated against the raw vault balances this returns 0.998 exactly on DREGG/SOL and
    SOLVE/SOL (p05 == p95, both directions) — so those pools' vaults ARE the curve and the
    PumpSwap fee is 0.20%.

    It does NOT on nosis/SOL (0.950 on buys, 1.048 on sells) or weave/SOL (0.909 / 1.092).
    A value above 1 is impossible for a real curve, so the vault balance is not the
    pricing reserve there. One parameter reconciles it: a constant excess of tokens sitting
    in the vault that the curve does not count. Fitting that excess SEPARATELY on buys and
    on sells is a genuine test — the two are independent equations — and they agree to
    0.03pp on nosis and 0.35pp on weave.

    This matters beyond this study: anything replaying these pools from vault balances
    misprices by ~4.8% (nosis) / ~8.8% (weave), and `replay_sufficient: true` currently
    asserts otherwise for both.
    """
    print("\n7. THE CURVE — is the vault balance the pricing reserve?")

    def implied_g(e: Event, k: float) -> float | None:
        r = e["reserves"]
        if not r or e["in_mint"] not in r or e["out_mint"] not in r:
            return None
        rin, rout = r[e["in_mint"]][0], r[e["out_mint"]][0]
        if e["side"] == "sell":
            rin *= (1 - k)          # token is the IN leg
        else:
            rout *= (1 - k)         # token is the OUT leg
        ai, ao = e["in_raw"], e["out_raw"]
        if rout <= ao or ai <= 0:
            return None
        return (ao * rin) / (ai * (rout - ao))

    def fit_side(rows: Sequence[Event], side: str) -> float | None:
        rows = [e for e in rows if e["side"] == side]
        if len(rows) < 20:
            return None
        lo, hi = -0.02, 0.60
        for _ in range(70):
            mid = (lo + hi) / 2
            vs = [v for e in rows if (v := implied_g(e, mid)) is not None]
            if not vs:
                hi = mid
                continue
            m = statistics.median(vs)
            # increasing k lowers g on sells and raises it on buys: opposite monotonicity,
            # which is exactly why fitting the two sides separately is a real check.
            if side == "sell":
                lo, hi = (lo, mid) if m < AMM_G else (mid, hi)
            else:
                lo, hi = (mid, hi) if m < AMM_G else (lo, mid)
        return (lo + hi) / 2

    by_pool: dict[str, list[Event]] = collections.defaultdict(list)
    for e in events:
        if e["dex"] == "pumpswap" and e["reserves"]:
            by_pool[e["label"]].append(e)
    print(f"   {'pool':13s}{'n':>7}{'k from sells':>14}{'k from buys':>13}{'agreement':>11}   reading")
    out: dict[str, float] = {}
    for lab, rows in sorted(by_pool.items(), key=lambda kv: -len(kv[1])):
        ks, kb = fit_side(rows, "sell"), fit_side(rows, "buy")
        if ks is None or kb is None:
            continue
        out[lab] = (ks + kb) / 2
        exact = abs(ks) < 0.002 and abs(kb) < 0.002
        note = "vault IS the curve (fee 0.200%)" if exact else \
               "vault holds EXCESS tokens the curve ignores -> REPLAY FROM VAULTS MISPRICES"
        print(f"   {lab:13s}{len(rows):>7}{ks * 100:>13.3f}%{kb * 100:>12.3f}%"
              f"{abs(ks - kb) * 100:>10.3f}pp   {note}")
    return out


def counterfactual_penalty(events: Sequence[Event], k: dict[str, float]) -> None:
    """Theorem 2 of 2601.08641, evaluated on our pools instead of cited.

    The copier mirrors the leader's exact input size as the very next trade on the curve,
    i.e. the leader's own post-trade reserves are the copier's pre-trade reserves. This is
    the paper's `Y / (Y - 2d)` overpay, computed exactly rather than to first order, and it
    is the FLOOR on the cost of copying: pure price impact, no priority fee, no MEV, no
    adverse selection.
    """
    print("\n8a. COUNTERFACTUAL IMITATION PENALTY — the literature's mechanism, on our pools")
    print("    Copier mirrors the leader's input size as the next trade on the same curve.")
    print(f"    {'pool':13s}{'side':>6}{'n':>7}{'med d/Y':>10}{'p90 d/Y':>10}"
          f"{'median':>9}{'mean':>9}{'p90':>9}{'p99':>9}")
    allpen: list[float] = []
    for lab in sorted({e["label"] for e in events}):
        if lab not in k:
            continue
        for side in ("buy", "sell"):
            pen: list[float] = []
            dy: list[float] = []
            for e in events:
                if e["label"] != lab or e["side"] != side or not e["reserves"]:
                    continue
                r = e["reserves"]
                if e["in_mint"] not in r or e["out_mint"] not in r:
                    continue
                (pin, qin), (pout, qout) = r[e["in_mint"]], r[e["out_mint"]]
                kk = k[lab]
                if side == "sell":
                    pin, qin = pin * (1 - kk), qin * (1 - kk)
                else:
                    pout, qout = pout * (1 - kk), qout * (1 - kk)
                ai, ao = e["in_raw"], e["out_raw"]
                if pout <= ao or qout <= 0 or ao <= 0 or pin <= 0:
                    continue
                copier_out = qout * ai * AMM_G / (qin + ai * AMM_G)
                if copier_out <= 0:
                    continue
                pen.append(1 - copier_out / ao)
                dy.append(ai / pin)
            if len(pen) < 20:
                continue
            pen.sort()
            dy.sort()
            allpen += pen
            q = lambda v, p: v[min(len(v) - 1, int(p * len(v)))]  # noqa: E731
            print(f"    {lab:13s}{side:>6}{len(pen):>7}{q(dy, .5) * 100:>9.3f}%{q(dy, .9) * 100:>9.3f}%"
                  f"{q(pen, .5) * 100:>8.3f}%{statistics.mean(pen) * 100:>8.3f}%"
                  f"{q(pen, .9) * 100:>8.3f}%{q(pen, .99) * 100:>8.3f}%")
    if allpen:
        allpen.sort()
        print(f"    ALL: n={len(allpen)}  median={statistics.median(allpen) * 100:.3f}%  "
              f"mean={statistics.mean(allpen) * 100:.3f}%  "
              f"p90={allpen[int(.9 * len(allpen))] * 100:.3f}%  "
              f"p99={allpen[int(.99 * len(allpen))] * 100:.3f}%")
        print("    d/Y is ~3 orders of magnitude below a fresh bonding curve, which is why the")
        print("    paper's 11.5pp imitation penalty does NOT transfer to post-graduation pools.")


def empirical_penalty(events: Sequence[Event], *, deltas: Sequence[int] = (1, 2, 5, 12, 25, 75)) -> None:
    """What a real second mover actually paid. No curve model — realised fills only.

    For every ordered pair (leader, follower) on the same pool and side within `delta`
    slots, the follower's realised price disadvantage. Size-matched restricts to followers
    trading 0.5x-2x the leader's SOL size, because a bigger follower eats more of its own
    slippage and would otherwise be charged for it.
    """
    print("\n8b. EMPIRICAL SECOND-MOVER PENALTY — realised fills, no model")
    print(f"    {'delta':>7}{'pairs':>9}{'median':>9}{'mean':>9}{'% worse off':>13}"
          f"{'size-matched n':>16}{'median':>9}")
    grp: dict[tuple[str, str], list[Event]] = collections.defaultdict(list)
    for e in events:
        grp[(e["pool"], e["side"])].append(e)
    for g in grp.values():
        g.sort(key=lambda e: (e["slot"], e["tx_index"] if e["tx_index"] is not None else 0))
    for delta in deltas:
        pen: list[float] = []
        matched: list[float] = []
        for g in grp.values():
            n = len(g)
            for i in range(n):
                a = g[i]
                pa = a.price
                for j in range(i + 1, n):
                    b = g[j]
                    if b["slot"] - a["slot"] > delta:
                        break
                    if b["slot"] <= a["slot"] or b["trader"] == a["trader"]:
                        continue
                    r = (b.price / pa - 1) if a["side"] == "buy" else (1 - b.price / pa)
                    pen.append(r)
                    if a.sol > 0 and 0.5 <= b.sol / a.sol <= 2.0:
                        matched.append(r)
        if not pen:
            continue
        worse = sum(1 for v in pen if v > 0) / len(pen) * 100
        ms = f"{statistics.median(matched) * 100:>8.3f}%" if len(matched) > 20 else f"{'-':>9}"
        print(f"    {delta:>7}{len(pen):>9}{statistics.median(pen) * 100:>8.3f}%"
              f"{statistics.mean(pen) * 100:>8.3f}%{worse:>12.1f}%{len(matched):>16}{ms}")


# --------------------------------------------------------------------------------------
# 9. Round trips, censoring-aware
# --------------------------------------------------------------------------------------

def round_trips(events: Sequence[Event]) -> None:
    """What a completed round trip on these pools actually earns — the bar copying must clear.

    THE CENSORING IS INFORMATIVE AND IS REPORTED FIRST. A wallet that sells more tokens
    than it bought inside the window acquired them before it, or off these pools. Its
    "profit" is then just net SOL out and is meaningless. Those books are EXCLUDED, not
    marked to some price, and the exclusion rate is printed. What survives is wallets that
    entered flat inside the window, where average-cost accounting is exact.
    """
    print("\n9. ROUND TRIPS — the edge that copying has to clear (censoring-aware)")
    books: dict[tuple[str, str], list[Event]] = collections.defaultdict(list)
    for e in sorted(events, key=lambda e: (e["slot"], e["tx_index"] if e["tx_index"] is not None else 0)):
        books[(e["trader"], e["pool"])].append(e)
    censored = 0
    closed: list[dict[str, Any]] = []
    for (w, p), ts in books.items():
        pos = cost = realised = 0.0
        nb = ns = 0
        spent = 0.0
        bad = False
        for t in ts:
            if t["side"] == "buy":
                pos += t.tokens
                cost += t.sol
                spent += t.sol
                nb += 1
            else:
                if t.tokens > pos * (1 + 1e-9):
                    bad = True
                    break
                avg = cost / pos if pos > 0 else 0.0
                realised += t.sol - avg * t.tokens
                cost -= avg * t.tokens
                pos -= t.tokens
                ns += 1
        if bad:
            censored += 1
            continue
        closed.append({"w": w, "pool": p, "realised": realised, "open": pos,
                       "nb": nb, "ns": ns, "n": nb + ns, "spent": spent})
    print(f"   wallet-pool books: {len(books):,}   CENSORED (sold inventory from outside the "
          f"window): {censored:,} ({censored / max(1, len(books)) * 100:.1f}%)")
    have = [r for r in closed if r["ns"] > 0]
    full = [r for r in closed if r["ns"] > 0 and r["open"] < 1e-9]
    print(f"   uncensored books: {len(closed):,}   with a realising sell: {len(have):,}   "
          f"FULLY CLOSED: {len(full):,}")
    if full:
        rr = [r["realised"] for r in full]
        ret = sorted(r["realised"] / r["spent"] for r in full if r["spent"] > 0)
        pos = sum(1 for v in rr if v > 0) / len(rr) * 100
        print(f"   fully closed round trips: median {statistics.median(rr):+.5f} SOL, "
              f"mean {statistics.mean(rr):+.5f} SOL, {pos:.1f}% positive")
        if ret:
            print(f"   return on capital: median {statistics.median(ret) * 100:+.2f}%  "
                  f"mean {statistics.mean(ret) * 100:+.2f}%  "
                  f"p10 {ret[len(ret) // 10] * 100:+.2f}%  p90 {ret[9 * len(ret) // 10] * 100:+.2f}%")
            print("   THIS IS THE BAR: a copier pays the second-mover penalty out of this.")


# --------------------------------------------------------------------------------------
# 10. Adversarial read
# --------------------------------------------------------------------------------------

def adversarial(events: Sequence[Event], mapping: dict[str, str] | None) -> None:
    """Treat every apparently-profitable wallet as constructed until shown otherwise.

    2601.08641's threat model: pick a historically profitable wallet, buy very early,
    conceal the position across controlled wallets, fake volume and sentiment, then exit
    into copier demand while the record still looks clean. Two of its detectors are
    computable from our window and are run verbatim, thresholds included.

    The third feature — profit that exists only as inventory nobody can exit — is ours,
    and is the one that matters for a pool the operator holds: a leaderboard cannot tell
    the difference between a wallet that made SOL and a wallet that is marked up in a
    token it has not sold.
    """
    print("\n10. ADVERSARIAL READ — is anyone building a profitable-looking wallet here?")
    print("    Rule (2601.08641 Alg.3, bump bot): consecutive opposite-direction trades of")
    print("    IDENTICAL token quantity; alpha = flips / (|net position| + 1); flag alpha >= 50.")
    books: dict[tuple[str, str], list[Event]] = collections.defaultdict(list)
    for e in sorted(events, key=lambda e: (e["slot"], e["tx_index"] if e["tx_index"] is not None else 0)):
        books[(e["trader"], e["pool"])].append(e)
    scored: list[tuple[float, int, float, str, str]] = []
    for (w, p), ts in books.items():
        if len(ts) < 4:
            continue
        flips = 0
        for x, y in pairwise(ts):
            if x["side"] != y["side"] and abs(x.tokens - y.tokens) / max(x.tokens, y.tokens) < 1e-9:
                flips += 1
        if not flips:
            continue
        net = abs(sum(t.tokens if t["side"] == "buy" else -t.tokens for t in ts))
        scored.append((flips / (net + 1), flips, net, w, p))
    scored.sort(reverse=True)
    flagged = [s for s in scored if s[0] >= 50]
    print(f"    wallet-pools with >=1 identical-quantity flip: {len(scored)};  alpha >= 50: {len(flagged)}")
    for a, f, net, w, p in scored[:3]:
        print(f"      alpha={a:.3g} flips={f} |net|={net:.4g}  {w[:16]}.. on {POOL_LABEL.get(p, p)[:12]}")
    if not flagged:
        print("    -> NO wash-trading bots at the literature's own threshold. The volume on")
        print("       these pools is not being manufactured by identical-quantity flipping.")
    print("\n    Bait shape: marked profit that is NOT realisable (carried as open inventory).")
    inv_only = tot = 0
    for _key, ts in books.items():
        if len(ts) < 6:
            continue
        pos = cost = realised = 0.0
        bad = False
        for t in ts:
            if t["side"] == "buy":
                pos += t.tokens
                cost += t.sol
            else:
                if t.tokens > pos * (1 + 1e-9):
                    bad = True
                    break
                avg = cost / pos if pos > 0 else 0.0
                realised += t.sol - avg * t.tokens
                cost -= avg * t.tokens
                pos -= t.tokens
        if bad:
            continue
        tot += 1
        if realised <= 0 and pos > 0:
            inv_only += 1
    if tot:
        print(f"    uncensored wallet-pools with >=6 trades: {tot};  zero-or-negative realised SOL")
        print(f"    while still holding inventory: {inv_only} ({inv_only / tot * 100:.0f}%)")
        print("    Any 'smart money' list built on marked P&L would rank these as winners.")


def _describe_largest_burst(events: Sequence[Event], relayer: str, *, gap: int = 200) -> None:
    """The single largest run of relayer BUYS, and what price did around it.

    Printed so the anecdote in RESULT §6 is regenerable rather than remembered — and printed
    immediately above the test that refuses to credit it, which is the point.
    """
    import datetime as _dt
    best: list[Event] = []
    by_pool: dict[str, list[Event]] = collections.defaultdict(list)
    for e in events:
        if e["payer"] == relayer and e["side"] == "buy":
            by_pool[e["pool"]].append(e)
    for rows in by_pool.values():
        rows.sort(key=lambda e: e["slot"])
        run: list[Event] = []
        for e in rows:
            if run and e["slot"] - run[-1]["slot"] > gap:
                if len(run) > len(best):
                    best = run
                run = []
            run.append(e)
        if len(run) > len(best):
            best = run
    if len(best) < 20:
        print("   (no relayer buy burst of >=20 trades in this window)")
        return
    pool, s0, s1 = best[0]["pool"], best[0]["slot"], best[-1]["slot"]
    same = sorted((e for e in events if e["pool"] == pool), key=lambda e: e["slot"])

    def seg(lo: int, hi: int) -> tuple[list[Event], float | None]:
        rows = [e for e in same if lo <= e["slot"] <= hi]
        move = (rows[-1].price / rows[0].price - 1) if len(rows) > 1 else None
        return rows, move

    windows = [("before", s0 - 3000, s0 - 1), ("during", s0, s1), ("after", s1 + 1, s1 + 9000)]
    print(f"   LARGEST RELAYER BUY BURST — {POOL_LABEL.get(pool, pool[:8])}, slots {s0}..{s1}, "
          f"{best[-1]['t'] - best[0]['t']}s from "
          f"{_dt.datetime.fromtimestamp(best[0]['t'], _dt.UTC):%Y-%m-%d %H:%M:%S} UTC")
    print(f"     {'segment':>8}{'swaps':>7}{'relayed':>9}{'share':>8}{'price move':>12}")
    for tag, lo, hi in windows:
        rows, move = seg(lo, hi)
        if not rows:
            continue
        rel = sum(1 for e in rows if e["payer"] == relayer)
        print(f"     {tag:>8}{len(rows):>7}{rel:>9}{rel / len(rows) * 100:>7.0f}%"
              f"{(move * 100 if move is not None else float('nan')):>11.1f}%")
    wallets = {e["trader"] for e in best}
    sizes = sorted(e.sol for e in best)
    print(f"     {len(best)} buys by {len(wallets)} DISTINCT relayed wallets, median clip "
          f"{statistics.median(sizes):.4f} SOL, {sum(sizes):.1f} SOL total")
    rows, _ = seg(s0, s1)
    peak = max((e.price for e in rows), default=None)
    if peak and rows:
        print(f"     peak during burst: +{(peak / rows[0].price - 1) * 100:.1f}% from burst start")
    for h in (600, 1800, 3600, 14400):
        later = [e for e in same if 0 < e["t"] - best[-1]["t"] <= h]
        if later and rows:
            print(f"       +{h:>5}s: {(later[-1].price / rows[-1].price - 1) * 100:+7.2f}% "
                  f"from burst end   (n={len(later)})")
    print("   Read alone this is an exit-liquidity story. The test below declines to credit it.")


def herd_event_study(events: Sequence[Event], relayer: str, *, window: int = 500,
                     thresholds: Sequence[float] = (0.30, 0.50),
                     horizons: Sequence[int] = (900, 2700, 5400, 10800),
                     nsim: int, seed: int) -> None:
    """Does a surge of app-relayed BUYING mark a local top on the operator's coins?

    This is the question that decides whether any of this is actionable, and it is the
    one place this study nearly fooled itself, so the failure is kept in view.

    WHAT EYEBALLING FOUND. On 2026-08-14 00:15:54 UTC, nosis/SOL ran a 492-second window
    in which FOMO's share of flow went 4% -> 33%, 90 distinct FOMO wallets bought (median
    clip 0.228 SOL), price rose +52.6% (peak +59.8%), and then gave back -19.0% at +10 min,
    -24.1% at +30 min and -27.7% at +4 h. `_describe_largest_burst` regenerates it rather
    than trusting this paragraph. Read on its own it is a perfect exit-liquidity story.

    WHY THAT READING IS NOT ALLOWED. The window was chosen by looking at it. So the test
    below pre-commits to a rule — trailing FOMO share of buys over `window` slots crosses
    `threshold`, take forward returns at fixed horizons — and runs it over every crossing
    in both datasets, against a null that PERMUTES THE RELAYER FLAG across trades while
    holding every timestamp and every price fixed. That null asks the only question worth
    asking: is it FOMO specifically, or would any busy window have looked like this?
    """
    print(f"\n11. HERD EVENT STUDY — does app-relayed buying mark a top? "
          f"(pre-committed rule, {nsim} permutations)")
    rng = random.Random(seed)
    _describe_largest_burst(events, relayer)
    by_pool: dict[str, list[Event]] = collections.defaultdict(list)
    for e in events:
        by_pool[e["label"]].append(e)
    for lab, rows in sorted(by_pool.items(), key=lambda kv: -len(kv[1])):
        rows = sorted(rows, key=lambda e: e["slot"])
        n_rel = sum(1 for e in rows if e["payer"] == relayer)
        if len(rows) < 300 or n_rel < 20:
            print(f"   {lab}: {len(rows)} trades, {n_rel} relayed — below the floor, skipped")
            continue
        prices = [e.price for e in rows]
        slots = [e["slot"] for e in rows]

        def crossings(flags: Sequence[bool], thresh: float,
                      rows: Sequence[Event] = rows, slots: Sequence[int] = slots) -> list[int]:
            out, hot_prev = [], False
            for i in range(len(rows)):
                lo = slots[i] - window
                js = [j for j in range(max(0, i - 400), i + 1)
                      if slots[j] >= lo and rows[j]["side"] == "buy"]
                if len(js) < 8:
                    hot_prev = False
                    continue
                hot = sum(flags[j] for j in js) / len(js) >= thresh
                if hot and not hot_prev:
                    out.append(i)
                hot_prev = hot
            return out

        def forward(i: int, h: int, rows: Sequence[Event] = rows,
                    slots: Sequence[int] = slots,
                    prices: Sequence[float] = prices) -> float | None:
            last = None
            for j in range(i + 1, len(rows)):
                if slots[j] - slots[i] > h:
                    break
                last = prices[j]
            return (last / prices[i] - 1) if last else None

        flags = [e["payer"] == relayer for e in rows]
        for thresh in thresholds:
            ev = crossings(flags, thresh)
            if len(ev) < 3:
                print(f"   {lab}  share>={thresh:.0%}: {len(ev)} events — too few to test")
                continue
            print(f"   {lab}  relayer buy-share >= {thresh:.0%} over {window} slots: "
                  f"{len(ev)} events   ({n_rel}/{len(rows)} trades relayed)")
            print(f"     {'horizon':>9}{'n':>5}{'median':>10}{'mean':>9}{'null median':>13}{'p':>8}")
            nulls: dict[int, list[float]] = {h: [] for h in horizons}
            for _ in range(nsim):
                f2 = flags[:]
                rng.shuffle(f2)
                e2 = crossings(f2, thresh)
                if not e2:
                    continue
                for h in horizons:
                    vs = [v for i in e2 if (v := forward(i, h)) is not None]
                    if vs:
                        nulls[h].append(statistics.median(vs))
            for h in horizons:
                vs = [v for i in ev if (v := forward(i, h)) is not None]
                if not vs:
                    continue
                med = statistics.median(vs)
                nm = nulls[h]
                p = (sum(1 for v in nm if v <= med) + 1) / (len(nm) + 1) if nm else float("nan")
                nmm = statistics.median(nm) if nm else float("nan")
                print(f"     {h:>8}s{len(vs):>5}{med * 100:>9.2f}%{statistics.mean(vs) * 100:>8.2f}%"
                      f"{nmm * 100:>12.2f}%{p:>8.3f}")


def boards_check() -> None:
    """The other half of the operator's question: FOMO-app ATTENTION, not copying.

    state/boards is the pump.fun board tape — the attention-distribution surface these
    apps actually run on. If the operator's coins never appear there, the FOMO channel
    cannot be moving them, whatever it is doing elsewhere.
    """
    paths = sorted(glob.glob(str(BOARDS / "*.jsonl")))
    if not paths:
        print("\n12. BOARDS — no board tape found; skipping")
        return
    seen: collections.Counter[str] = collections.Counter()
    where: dict[str, set[str]] = collections.defaultdict(set)
    snaps: collections.Counter[str] = collections.Counter()
    for path in paths:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("kind") != "board_snapshot":
                    continue
                snaps[r["board"]] += 1
                for m in r.get("members", []):
                    sym = OPERATOR_MINT_PREFIX.get(m["mint"][:8])
                    if sym:
                        seen[sym] += 1
                        where[sym].add(r["board"])
    print("\n12. FOMO-APP ATTENTION — do the operator's coins ever reach the boards?")
    print(f"    board snapshots: {dict(snaps)}")
    for sym in OPERATOR_MINT_PREFIX.values():
        n = seen.get(sym, 0)
        print(f"    {sym:6s} appearances: {n:5d}   boards: {sorted(where.get(sym, [])) or '—'}")
    print("    A coin absent from the boards is absent from the attention channel these")
    print("    apps distribute through. That is a structural answer, not a statistical one.")


# --------------------------------------------------------------------------------------

def _pool_list_sql() -> str:
    return ", ".join(f"'{p}'" for p in POOL_LABEL)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tape", type=Path, default=LIVE_TAPE)
    ap.add_argument("--bq-dir", type=Path, default=None,
                    help="directory with swaps/<day>.jsonl and cp_<day>.json (see --sql)")
    ap.add_argument("--sql", action="store_true", help="print the BigQuery SQL and exit")
    ap.add_argument("--day", default="2026-08-13")
    ap.add_argument("--nsim", type=int, default=200)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--trials", type=int, default=40, help="power-curve trials per level")
    ap.add_argument("--skip-power", action="store_true")
    args = ap.parse_args(argv)

    if args.sql:
        d = args.day
        y, m, dd = (int(x) for x in d.split("-"))
        import datetime as _dt
        nxt = (_dt.date(y, m, dd) + _dt.timedelta(days=1)).isoformat()
        print(BQ_SQL_FULL_BALANCES.format(day=d, next_day=nxt, pool_list=_pool_list_sql()))
        print("\n-- and, for reserves + signers + tx_index:")
        print(f"--   python3 scripts/bulk_history.py pull --start {d} --end {d} \\")
        print("--       --project <billing-project> --with-signers --out <DIR>   # 531 GB, $3.02")
        return 0

    print("=" * 92)
    print("COPY-TRADING AND APP-MEDIATED FLOW ON THE CLUSTER POOLS")
    print("=" * 92)

    datasets: list[tuple[str, list[Event]]] = []
    chain = load_chain_rows(args.tape)
    bq_chain: list = []
    live, lstats = load_live(args.tape)
    print(f"\nLIVE TAPE  {len(live):,} swaps parsed  ({lstats.get('ok', 0):,} usable) from {args.tape}")
    if live:
        ts = [e["t"] for e in live]
        import datetime as _dt
        print(f"  window {_dt.datetime.fromtimestamp(min(ts), _dt.UTC):%Y-%m-%d %H:%M} -> "
              f"{_dt.datetime.fromtimestamp(max(ts), _dt.UTC):%Y-%m-%d %H:%M} UTC "
              f"({(max(ts) - min(ts)) / 3600:.1f} h)")
        datasets.append(("LIVE TAPE", live))
    if args.bq_dir:
        bq_chain = load_chain_rows_bq(args.bq_dir)
        bq, bstats = load_bq(args.bq_dir)
        print(f"\nBIGQUERY REPLICATION  {len(bq):,} swaps  {bstats}")
        by_sig = {e["sig"]: e for e in live}
        both = [(by_sig[e["sig"]], e) for e in bq if e["sig"] in by_sig]
        if both:
            agree = sum(1 for a, b in both if a["trader"] == b["trader"])
            sides = sum(1 for a, b in both if a["side"] == b["side"])
            print(f"  cross-validation on {len(both)} overlapping swaps: "
                  f"counterparty {agree}/{len(both)}, side {sides}/{len(both)}")
        if bq:
            datasets.append(("BIGQUERY FULL DAY", bq))

    for name, ds in datasets:
        print("\n" + "=" * 92)
        print(f"DATASET: {name}   ({len(ds):,} swaps)")
        print("=" * 92)
        certify_completeness(ds, chain if name == "LIVE TAPE" else bq_chain)
        print(f"\n   usable for wallet-level work: filtering {len(ds):,} swaps")
        ev = tradeable(ds, report=True)
        print(f"      KEPT    {len(ev):>6}")
        validate_on_curve_guard(ds)
        if len(ev) < 100:
            print("   too few identified trades for the timing tests; skipping")
            continue
        if ev[0]["tx_index"] is not None:
            per_slot: dict[tuple[str, int], list[Event]] = collections.defaultdict(list)
            for e in ev:
                per_slot[(e["pool"], e["slot"])].append(e)
            adj = tot = 0
            for v in per_slot.values():
                if len(v) < 2:
                    continue
                v.sort(key=lambda e: e["tx_index"])
                for a, b in pairwise(v):
                    tot += 1
                    adj += (b["tx_index"] - a["tx_index"] == 1)
            if tot:
                print(f"   same-slot consecutive pairs: {tot}; tx_index-ADJACENT (bundle-shaped): "
                      f"{adj} ({adj / tot * 100:.0f}%) — excluded with all of lag 0")
        payers = venue_map(ev)
        mapping = resolve_entities(ev)
        correlogram_test(ev, None, nsim=args.nsim, seed=args.seed)
        pair_test(ev, None, deltas=(2, 12), nsim=args.nsim, seed=args.seed, level="WALLET")
        pair_test(ev, mapping, deltas=(2, 12), nsim=args.nsim, seed=args.seed,
                  level="ENTITY (circular — shown to demonstrate the artifact)")
        top = max(payers, key=lambda p: len(payers[p])) if payers else None
        if top and len(payers[top]) > 5:
            app_cohort_test(ev, top, nsim=args.nsim, seed=args.seed)
        if not args.skip_power:
            power_curve(ev, nsim=args.nsim, seed=args.seed, trials=args.trials)
        k = fit_curve(ds)
        counterfactual_penalty(ds, k)
        empirical_penalty(ev)
        round_trips(ev)
        adversarial(ev, mapping)
        herd_event_study(ev, FOMO_RELAYER, nsim=max(50, args.nsim), seed=args.seed)

    boards_check()
    print("\n" + "=" * 92)
    print("See studies/RESULT_copytrading.md for the reading.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
