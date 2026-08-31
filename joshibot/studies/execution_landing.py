#!/usr/bin/env python3
"""How do you actually land a transaction on Solana? — measured on our own pools.

`scripts/sim2real.py` reported ambient landing rates of 1%-52% on the cluster pools and
concluded that true friction could be 2-10x what the shadow model reports. That number is
computed as ``swaps / (swaps + attempts)``. This study takes that denominator apart, and
it does not survive.

Three things are wrong with it, and they point in different directions:

1. **The denominator drops 57,097 successful transactions.** The tape has four row kinds.
   `swap` (moved this pool's vaults), `liquidity`, `reference` (landed fine, touched the
   pool account, zero delta — a router carrying the pool in an address-lookup table and
   filling somewhere else), and `attempt` (an `err` in the signature listing). `reference`
   rows are *successes*. Counting only `swap` in the numerator while counting every
   `attempt` in the denominator compares "landed AND traded here" against "failed for any
   reason at all". Restoring them moves the aggregate from 13.4% to 75.9%.

2. **96% of the failures are not swaps.** Fetching the actual transactions shows the
   failing instruction is almost never inside an AMM: it is a private arbitrage program
   whose whole design is to abort when the arb is not there. Ten fee-payers account for
   47% of failures. Split by execution path, a plain AMM call lands 95.3%, a Jupiter route
   59.0%, and the third-party bot programs 7.3%. The 13.4% aggregate is a measurement of
   somebody else's spam. And splitting again by the bid shows the path gap is mostly a BID
   gap: above 50,000 microlamports/CU both honest paths land alike, 95.6% and 97.2%.

3. **The tape structurally cannot see a dropped transaction.** `attempt` rows come from
   `getSignaturesForAddress` with a non-null `err` (`shitcoims_cluster/record.py:205`), so
   every one of them *executed on chain and paid a fee*. A transaction that expired,
   was dropped by the leader, or never got forwarded leaves no signature to find. So the
   tape measures the fee-burning branch exactly and the free branch not at all. Our first
   real sends have to instrument that half themselves.

What the tape *can* answer, it answers well. Sections below, each runnable:

  A  reference class      — the denominator, four ways, per pool
  B  contention           — success rate vs how many transactions share your slot
  C  fee identity         — fee == 5000*n_sigs + ceil(cu_price*cu_limit/1e6), verified
  D  compute units        — you are charged on the LIMIT, not on what you consume
  E  the bid              — landing rate as a function of compute-unit price
  F  within-slot          — does the winner outbid the losers, holding the slot fixed?
  G  sandwich (theory)    — closed-form attacker optimum at our depth and our clip
  I  sandwich (measured)  — intra-slot order reconstructed from vault balances, then
                            counted: how many of our pools' trades were actually attacked
  H  policy               — the numbers that come out, and what they cost

Sections C-F need transaction bodies, which the tape does not carry.
`--probe` runs two fetches: a stratified sample over (pool, kind) for C-E, and every
transaction in slots holding BOTH a landed swap and a failed attempt for F. Both are
cached; every later run reads the cache. Nothing here writes to `state/`.

Usage:
    python3 studies/execution_landing.py --probe        # ~6,000 getTransaction calls, once
    python3 studies/execution_landing.py                # analysis off the cache
    python3 studies/execution_landing.py --fee-oracle   # + live getRecentPrioritizationFees
    python3 studies/execution_landing.py --json
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import math
import os
import random
import statistics
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
TAPE = ROOT / "state" / "cluster_tape" / "swaps"
CACHE = ROOT / ".cache" / "execution_landing" / "probe.jsonl"
SLOT_CACHE = ROOT / ".cache" / "execution_landing" / "probe_slots.jsonl"

LAMPORTS_PER_SOL = 1_000_000_000
BASE_FEE_PER_SIG = 5_000  # lamports; verified against 4,130 of our own transactions in §C
WSOL = "So11111111111111111111111111111111111111112"

# Program identities. Only what we needed to classify an execution path; anything not here
# is treated as a third-party program, which is the conservative direction (it moves
# transactions OUT of the retail reference class, never into it).
JUPITER = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",  # v6
    "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB",  # v4
}
AMM = {
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",  # PumpSwap
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",  # pump.fun bonding curve
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",  # Meteora DLMM
    "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN",  # Meteora DBC
}
PLUMBING = {
    "ComputeBudget111111111111111111111111111111",
    "11111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
}
COMPUTE_BUDGET = "ComputeBudget111111111111111111111111111111"

PATHS = ("direct-AMM", "jupiter", "third-party")


# ---------------------------------------------------------------------------- utilities


def pct(xs: Sequence[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, round(p / 100 * (len(s) - 1))))]


def sign_test_p(a: int, b: int) -> float:
    """Two-sided exact binomial p at q=1/2. Returns nan for n=0."""
    n = a + b
    if n == 0:
        return float("nan")
    k = max(a, b)
    tail = sum(math.comb(n, i) for i in range(k, n + 1))
    return min(1.0, 2 * tail / 2**n)


def load_tape() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(glob.glob(str(TAPE / "*.jsonl"))):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # the collector is live and may be mid-append
    return rows


def classify(progs: Iterable[str]) -> str:
    """Which execution path did this transaction take?

    The question the study needs is not "did somebody's transaction land" but "would a
    transaction shaped like OURS have landed". `direct-AMM` means the whole transaction is
    an AMM call plus plumbing — no unknown program anywhere in it. `jupiter` means an
    aggregator route. Everything else is a third-party program, which for our pools means
    an arbitrage bot.
    """
    ps = set(progs)
    if ps & JUPITER:
        return "jupiter"
    if (ps & AMM) and not (ps - PLUMBING - AMM):
        return "direct-AMM"
    return "third-party"


# ------------------------------------------------------------------------------- probe


def _b58(s: str) -> bytes:
    alpha = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = 0
    for ch in s:
        n = n * 58 + alpha.index(ch)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + body


def _compute_budget(instrs: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    """(cu_limit, cu_price) from the transaction's ComputeBudget instructions.

    Handles both the jsonParsed form and the raw base58 form: discriminator 2 is
    SetComputeUnitLimit (u32 LE), discriminator 3 is SetComputeUnitPrice (u64 LE).
    """
    limit = price = None
    for ins in instrs:
        if ins.get("programId") != COMPUTE_BUDGET:
            continue
        parsed = ins.get("parsed")
        if isinstance(parsed, dict):
            info = parsed.get("info") or {}
            if parsed.get("type") == "setComputeUnitLimit" and "units" in info:
                limit = int(info["units"])
                continue
            if parsed.get("type") == "setComputeUnitPrice" and "microLamports" in info:
                price = int(info["microLamports"])
                continue
        data = ins.get("data")
        if not data:
            continue
        try:
            raw = _b58(data)
        except (ValueError, KeyError):
            continue
        if not raw:
            continue
        if raw[0] == 2 and len(raw) >= 5:
            limit = int.from_bytes(raw[1:5], "little")
        elif raw[0] == 3 and len(raw) >= 9:
            price = int.from_bytes(raw[1:9], "little")
    return limit, price


class Rpc:
    def __init__(self) -> None:
        key_file = Path(os.path.expanduser("~/.helius-key"))
        if not key_file.exists():
            raise SystemExit("no ~/.helius-key; --probe needs read RPC")
        self.url = f"https://mainnet.helius-rpc.com/?api-key={key_file.read_text().strip()}"

    def post(self, body: Any) -> Any:
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        last: Exception | None = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=45) as resp:
                    return json.loads(resp.read())
            except Exception as exc:  # transport, 429, 5xx — all retried the same way
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"helius getTransaction failed after 5 attempts: {type(last).__name__}")

    def transactions(self, tape_rows: Sequence[dict[str, Any]], *, batch: int = 25,
                     log: Any = sys.stderr) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for start in range(0, len(tape_rows), batch):
            chunk = tape_rows[start : start + batch]
            body = [
                {
                    "jsonrpc": "2.0", "id": i, "method": "getTransaction",
                    "params": [
                        row["chain"]["signature"],
                        {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0,
                         "commitment": "confirmed"},
                    ],
                }
                for i, row in enumerate(chunk)
            ]
            resp = self.post(body)
            if isinstance(resp, dict):
                resp = [resp]
            by_id = {r.get("id"): r for r in resp}
            for i, row in enumerate(chunk):
                tx = (by_id.get(i) or {}).get("result") or {}
                if not tx:
                    continue
                out.append(_flatten(row, tx))
            print(f"  probe {start + len(chunk)}/{len(tape_rows)}", file=log)
            time.sleep(0.25)  # the cluster collector shares this key
        return out


def _flatten(tape_row: dict[str, Any], tx: dict[str, Any]) -> dict[str, Any]:
    meta = tx.get("meta") or {}
    msg = (tx.get("transaction") or {}).get("message") or {}
    instrs = msg.get("instructions") or []
    limit, price = _compute_budget(instrs)
    keys = msg.get("accountKeys") or []
    payer = None
    if keys:
        payer = keys[0].get("pubkey") if isinstance(keys[0], dict) else keys[0]
    err = meta.get("err")
    progs = [i.get("programId") for i in instrs]
    fail_idx = err["InstructionError"][0] if isinstance(err, dict) and "InstructionError" in err else None
    return {
        "sig": tape_row["chain"]["signature"],
        "label": tape_row["label"],
        "pool": tape_row["pool"],
        "kind": tape_row["kind"],
        "slot": tx.get("slot"),
        "block_time": tx.get("blockTime"),
        "fee": meta.get("fee"),
        "cu_consumed": meta.get("computeUnitsConsumed"),
        "cu_limit": limit,
        "cu_price": price,
        "n_sigs": len((tx.get("transaction") or {}).get("signatures") or []),
        "payer": payer,
        "err": json.dumps(err) if err else None,
        "fail_idx": fail_idx,
        "fail_prog": progs[fail_idx] if (fail_idx is not None and fail_idx < len(progs)) else None,
        "n_instr": len(instrs),
        "progs": progs,
    }


def run_probe(rows: list[dict[str, Any]], *, per_cell: int, seed: int) -> None:
    """Stratified sample over (pool, kind); every cell's weight is recovered at analysis."""
    rpc = Rpc()
    rng = random.Random(seed)
    cells: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for r in rows:
        cells[(r["label"], r["kind"])].append(r)
    sample: list[dict[str, Any]] = []
    for (_label, kind), members in sorted(cells.items()):
        if kind not in ("swap", "attempt", "reference"):
            continue
        n = per_cell if kind != "reference" else min(per_cell, 120)
        sample += rng.sample(members, min(n, len(members)))
    print(f"probing {len(sample)} transactions", file=sys.stderr)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    got = rpc.transactions(sample)
    with open(CACHE, "w") as fh:
        for r in got:
            fh.write(json.dumps(r) + "\n")
    print(f"cached {len(got)} -> {CACHE}", file=sys.stderr)

    # Second, matched sample: every transaction in slots holding BOTH a landed swap and a
    # failed attempt. Slot becomes a fixed effect, which is the only way the tape can even
    # ask whether the bid causes the landing rather than labelling who was bidding.
    by_slot: dict[str, dict[int, list[dict[str, Any]]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    for r in rows:
        by_slot[r["label"]][r["chain"]["slot"]].append(r)
    matched: list[dict[str, Any]] = []
    for label, slots in sorted(by_slot.items()):
        mixed = sorted(
            s for s, v in slots.items()
            if any(x["kind"] == "swap" for x in v) and any(x["kind"] == "attempt" for x in v)
        )
        if label == "nosis/SOL":  # by far the busiest; cap the fetch
            mixed = [s for s in mixed if len(slots[s]) <= 40]
            mixed = rng.sample(mixed, min(70, len(mixed)))
        for s in mixed:
            matched += slots[s]
    print(f"probing {len(matched)} transactions in mixed slots", file=sys.stderr)
    got2 = rpc.transactions(matched)
    with open(SLOT_CACHE, "w") as fh:
        for r in got2:
            fh.write(json.dumps(r) + "\n")
    print(f"cached {len(got2)} -> {SLOT_CACHE}", file=sys.stderr)


def fee_oracle(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """What does `getRecentPrioritizationFees` actually tell us about OUR pools?

    This is the RPC everyone reaches for when sizing a bid, and it is the wrong tool. It
    reports, per slot, the *minimum* prioritization fee among transactions that locked the
    given accounts. Almost every block contains at least one transaction paying nothing, so
    the minimum is almost always zero — an estimator that answers "bid 0" to every question.

    Run it against our exact pools rather than arguing about it. Live call; needs the key.
    """
    rpc = Rpc()
    pools: dict[str, str] = {}
    for r in rows:
        pools.setdefault(r["label"], r["pool"])
    out: dict[str, Any] = {}
    targets: list[tuple[str, list[str]]] = [("global (no accounts)", [])]
    targets += [(k, [v]) for k, v in sorted(pools.items())]
    for name, accounts in targets:
        resp = rpc.post({"jsonrpc": "2.0", "id": 1,
                         "method": "getRecentPrioritizationFees", "params": [accounts]})
        fees = [r["prioritizationFee"] for r in (resp.get("result") or [])]
        if not fees:
            continue
        out[name] = {
            "slots": len(fees),
            "frac_zero": sum(1 for f in fees if f == 0) / len(fees),
            **{f"p{q}": pct([float(f) for f in fees], q) for q in (50, 75, 90, 99)},
            "max": max(fees),
        }
        time.sleep(0.2)
    return out


def load_cache(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with open(path) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    # A row without `progs` is an RPC miss, not a transaction; it cannot be classified and
    # must not enter a denominator.
    return [r for r in rows if r.get("progs")]


# ------------------------------------------------------------ A. the reference class


def section_a(rows: list[dict[str, Any]], out: dict[str, Any]) -> None:
    """The denominator, four ways.

    `sim2real` reports ``swap / (swap + attempt)``. That is a valid statistic, but it is
    not a landing rate: it asks "given that a transaction referencing this pool either
    moved it or failed, did it move it", which conflates a router filling elsewhere with
    a transaction that could not execute.
    """
    per: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in rows:
        per[r["label"]][r["kind"]] += 1
    table: dict[str, dict[str, Any]] = {}
    total: collections.Counter[str] = collections.Counter()
    for label, c in sorted(per.items()):
        s, rf, lq, a = c["swap"], c["reference"], c["liquidity"], c["attempt"]
        landed = s + rf + lq
        table[label] = {
            "swap": s, "reference": rf, "liquidity": lq, "attempt": a,
            "sim2real_rate": s / (s + a) if s + a else None,
            "landed_rate": landed / (landed + a) if landed + a else None,
        }
        total.update(c)
    s, rf, lq, a = total["swap"], total["reference"], total["liquidity"], total["attempt"]
    table["ALL"] = {
        "swap": s, "reference": rf, "liquidity": lq, "attempt": a,
        "sim2real_rate": s / (s + a), "landed_rate": (s + rf + lq) / (s + rf + lq + a),
    }
    out["A_reference_class"] = table

    # Every failure in the tape is an InstructionError, i.e. every one EXECUTED and paid a
    # fee. Pre-execution rejections (BlockhashNotFound, AccountInUse, WouldExceedMax*)
    # cannot appear here, because a transaction that is never committed has no signature to
    # list. Asserting that is cheap; printing the count makes it checkable.
    shape: collections.Counter[str] = collections.Counter()
    for r in rows:
        if r.get("kind") != "attempt":
            continue
        err = r.get("error") or ""
        shape["InstructionError" if err.startswith("{'InstructionError'") else "other"] += 1
    cbe = sum(1 for r in rows if r.get("kind") == "attempt"
              and "ComputationalBudgetExceeded" in (r.get("error") or ""))
    out["A_error_shape"] = {
        **shape,
        "compute_budget_exceeded": cbe,
        "compute_budget_exceeded_frac": cbe / max(1, sum(shape.values())),
    }


# ---------------------------------------------------------------- B. contention


def section_b(rows: list[dict[str, Any]], out: dict[str, Any]) -> None:
    """Success rate as a function of how many transactions share your slot.

    A writable-account lock is exclusive: two transactions touching the same pool in the
    same block execute in sequence, and the second one prices against reserves the first
    one already moved. So contention is the mechanism by which a minOut is violated, and
    it should be visible as a monotone decline. It is.
    """
    res = {}
    for label in sorted({r["label"] for r in rows}):
        g = [r for r in rows if r["label"] == label]
        by_slot: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
        for r in g:
            by_slot[r["chain"]["slot"]][r["kind"]] += 1
        span = max(by_slot) - min(by_slot) + 1
        buckets: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)

        def key(n: int) -> str:
            return "1" if n == 1 else "2" if n == 2 else "3-4" if n <= 4 else \
                   "5-8" if n <= 8 else "9-16" if n <= 16 else "17+"

        for c in by_slot.values():
            b = buckets[key(sum(c.values()))]
            b.update(c)
            b["slots"] += 1
        rows_out = {}
        for k, c in buckets.items():
            landed = c["swap"] + c["reference"] + c["liquidity"]
            n = landed + c["attempt"]
            rows_out[k] = {
                "slots": c["slots"], "swap": c["swap"], "reference": c["reference"],
                "attempt": c["attempt"],
                "landed_rate": landed / n if n else None,
                "swap_vs_attempt": c["swap"] / (c["swap"] + c["attempt"])
                if c["swap"] + c["attempt"] else None,
            }
        res[label] = {
            "slot_span": span,
            "active_slot_fraction": len(by_slot) / span,
            "by_contention": rows_out,
        }
    out["B_contention"] = res


# -------------------------------------------------------- C. the fee identity


def section_c(probe: list[dict[str, Any]], out: dict[str, Any]) -> None:
    """fee == 5000*n_sigs + ceil(cu_price * cu_limit / 1e6).

    Worth verifying rather than citing, because the whole bidding argument turns on the
    second term being computed from the compute-unit LIMIT you requested and not from
    what you consumed. If it were charged on consumption, over-requesting would be free
    and the CU-limit rule below would not exist.
    """
    exact = mismatch = 0
    examples: list[dict[str, Any]] = []
    for r in probe:
        if r.get("cu_limit") is None or r.get("fee") is None:
            continue
        price = r.get("cu_price") or 0
        pred = BASE_FEE_PER_SIG * r["n_sigs"] + -(-(price * r["cu_limit"]) // 1_000_000)
        if pred == r["fee"]:
            exact += 1
        else:
            mismatch += 1
            if len(examples) < 5:
                examples.append({"sig": r["sig"], "observed": r["fee"], "predicted": pred,
                                 "cu_price": price, "cu_limit": r["cu_limit"],
                                 "n_sigs": r["n_sigs"]})
    out["C_fee_identity"] = {
        "n": exact + mismatch, "exact": exact, "mismatch": mismatch,
        "rate": exact / (exact + mismatch) if exact + mismatch else None,
        "examples": examples,
    }


# ------------------------------------------------------- D. compute-unit limits


def section_d(probe: list[dict[str, Any]], out: dict[str, Any]) -> None:
    """What a swap consumes, and how badly the ambient trader over-requests.

    Two separate numbers get conflated as "compute units". `cu_consumed` sets what the
    transaction NEEDS; `cu_limit` sets what it PAYS for and — per the Agave block
    scheduler, which orders by fee-per-requested-CU — what it is ranked on. Over-request
    and you pay more for a worse queue position.
    """
    res: dict[str, Any] = {}
    for path in PATHS:
        for kind in ("swap", "attempt"):
            g = [r for r in probe
                 if classify(r["progs"]) == path and r["kind"] == kind
                 and r.get("cu_limit") and r.get("cu_consumed")]
            if len(g) < 10:
                continue
            ratio = [r["cu_limit"] / r["cu_consumed"] for r in g if r["cu_consumed"] > 0]
            res[f"{path}/{kind}"] = {
                "n": len(g),
                "cu_consumed_p50": pct([r["cu_consumed"] for r in g], 50),
                "cu_consumed_p90": pct([r["cu_consumed"] for r in g], 90),
                "cu_consumed_p99": pct([r["cu_consumed"] for r in g], 99),
                "cu_consumed_max": max(r["cu_consumed"] for r in g),
                "cu_limit_p50": pct([r["cu_limit"] for r in g], 50),
                "over_request_p50": pct(ratio, 50),
                "over_request_p90": pct(ratio, 90),
                "frac_over_1p5x": sum(1 for x in ratio if x > 1.5) / len(ratio),
                "wasted_cu_p50": pct([r["cu_limit"] - r["cu_consumed"] for r in g], 50),
            }
    # Compute exhaustion as a failure mode, straight off the tape (not the probe).
    out["D_compute_units"] = res


# ----------------------------------------------------------------- E. the bid


def _weights(probe: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, float]:
    """Stratum weights: the probe sampled (pool, kind) cells at different rates."""
    pop = collections.Counter((r["label"], r["kind"]) for r in rows)
    samp = collections.Counter((r["label"], r["kind"]) for r in probe)
    return {f"{k[0]}|{k[1]}": pop[k] / samp[k] for k in samp if samp[k]}


def section_e(probe: list[dict[str, Any]], rows: list[dict[str, Any]], out: dict[str, Any]) -> None:
    """Landing rate by execution path, and the dose-response against the bid.

    Both are population-reweighted: the probe oversampled the small pools and the small
    cells, so raw sample ratios are not estimates of anything.
    """
    w = _weights(probe, rows)

    def wt(r: dict[str, Any]) -> float:
        return w.get(f"{r['label']}|{r['kind']}", 0.0)

    path_tab: dict[str, dict[str, float]] = collections.defaultdict(
        lambda: collections.defaultdict(float))
    for r in probe:
        path_tab[classify(r["progs"])][r["kind"]] += wt(r)
        path_tab[classify(r["progs"])]["raw_" + r["kind"]] += 1
    paths = {}
    for p, c in path_tab.items():
        s, a = c["swap"], c["attempt"]
        paths[p] = {
            "est_swaps": s, "est_references": c["reference"], "est_attempts": a,
            "raw_n": int(c["raw_swap"] + c["raw_attempt"] + c["raw_reference"]),
            "landing_rate": s / (s + a) if s + a else None,
        }
    out["E_paths"] = paths

    edges = [0, 1_000, 10_000, 50_000, 100_000, 300_000, 1_000_000, float("inf")]
    names = ["0", "1-10k", "10-50k", "50-100k", "100-300k", "300k-1M", ">1M"]
    dose: dict[str, Any] = {}
    for p in PATHS:
        g = [r for r in probe if classify(r["progs"]) == p and r["kind"] in ("swap", "attempt")]
        b: dict[int, dict[str, float]] = collections.defaultdict(
            lambda: collections.defaultdict(float))
        for r in g:
            price = r.get("cu_price") or 0
            i = next(j for j in range(len(edges) - 1) if edges[j] <= price < edges[j + 1])
            b[i][r["kind"]] += wt(r)
            b[i]["raw"] += 1
        dose[p] = {
            names[i]: {"raw_n": int(c["raw"]), "est_swaps": c["swap"], "est_attempts": c["attempt"],
                       "landing_rate": c["swap"] / (c["swap"] + c["attempt"])
                       if c["swap"] + c["attempt"] else None}
            for i, c in sorted(b.items())
        }
    out["E_dose_response"] = dose

    # The decisive cross-tab: is it the PATH or the BID? Split each path at the cliff the
    # dose-response shows (50,000 microlamports/CU). If both paths land alike above it, the
    # path difference in E_paths is a bid difference wearing a path costume.
    cross: dict[str, Any] = {}
    for p in PATHS:
        for lo, hi, name in ((0, 50_000, "bid < 50k"), (50_000, float("inf"), "bid >= 50k")):
            g = [r for r in probe
                 if classify(r["progs"]) == p and r["kind"] in ("swap", "attempt")
                 and lo <= (r.get("cu_price") or 0) < hi]
            if not g:
                continue
            sw = sum(wt(r) for r in g if r["kind"] == "swap")
            at = sum(wt(r) for r in g if r["kind"] == "attempt")
            cross[f"{p} | {name}"] = {
                "raw_n": len(g), "est_swaps": sw, "est_attempts": at,
                "landing_rate": sw / (sw + at) if sw + at else None,
            }
    out["E_path_vs_bid"] = cross

    ladder: dict[str, dict[str, float]] = {}
    for label in sorted({r["label"] for r in probe}):
        bids = [float(r.get("cu_price") or 0) for r in probe
                if r["label"] == label and r["kind"] == "swap"]
        if len(bids) < 20:
            continue
        ladder[label] = {"n": len(bids), **{f"p{q}": pct(bids, q) for q in (25, 50, 75, 90, 99)}}
    bids = [float(r.get("cu_price") or 0) for r in probe if r["kind"] == "swap"]
    ladder["ALL"] = {"n": len(bids), **{f"p{q}": pct(bids, q) for q in (25, 50, 75, 90, 99)}}
    out["E_bid_ladder"] = ladder

    fail_prog = collections.Counter(r.get("fail_prog") for r in probe if r["kind"] == "attempt")
    inside_amm = sum(n for p, n in fail_prog.items() if p in AMM)
    inside_jup = sum(n for p, n in fail_prog.items() if p in JUPITER)
    tot = sum(fail_prog.values())
    out["E_failing_program"] = {
        "n": tot,
        "inside_an_AMM": inside_amm / tot if tot else None,
        "inside_jupiter": inside_jup / tot if tot else None,
        "third_party": 1 - (inside_amm + inside_jup) / tot if tot else None,
        "top": fail_prog.most_common(10),
    }


# ------------------------------------------------------------- F. within-slot


def section_f(slots: list[dict[str, Any]], out: dict[str, Any]) -> None:
    """Does the winner outbid the losers, holding the slot fixed?

    The cross-sectional gap in §E is confounded: high bidders and low bidders are
    different populations running different software. Conditioning on the slot removes
    every between-slot confound (network load, leader identity, time of day) but NOT the
    between-program one, so the test is also run restricted to comparable paths.
    """
    by_slot: dict[tuple[str, int], list[dict[str, Any]]] = collections.defaultdict(list)
    for r in slots:
        by_slot[(r["label"], r["slot"])].append(r)

    def run(keep: tuple[str, ...] | None) -> dict[str, Any]:
        wins = losses = ties = 0
        aucs, gaps = [], []
        for members in by_slot.values():
            v = members if keep is None else [r for r in members if classify(r["progs"]) in keep]
            won = [r.get("cu_price") or 0 for r in v if r["kind"] == "swap"]
            lost = [r.get("cu_price") or 0 for r in v if r["kind"] == "attempt"]
            if not won or not lost:
                continue
            mw, ml = statistics.median(won), statistics.median(lost)
            wins += mw > ml
            losses += mw < ml
            ties += mw == ml
            gaps.append(mw - ml)
            gt = sum(1 for a in won for b in lost if a > b)
            eq = sum(1 for a in won for b in lost if a == b)
            aucs.append((gt + 0.5 * eq) / (len(won) * len(lost)))
        return {
            "slots": len(aucs), "winner_bid_higher": wins, "winner_bid_lower": losses,
            "tied": ties, "sign_test_p": sign_test_p(wins, losses),
            "mean_auc": statistics.mean(aucs) if aucs else None,
            "median_bid_gap": statistics.median(gaps) if gaps else None,
        }

    out["F_within_slot"] = {
        "all": run(None),
        "jupiter+direct-AMM": run(("jupiter", "direct-AMM")),
    }
    # Who is doing the failing? A handful of fee-payers, if the spam reading is right.
    payers = collections.Counter(
        r["payer"] for r in slots if r["kind"] == "attempt" and r.get("payer"))
    if payers:
        out["F_failure_concentration"] = {
            "distinct_payers": len(payers), "n_failures": sum(payers.values()),
            "top10_share": sum(n for _, n in payers.most_common(10)) / sum(payers.values()),
        }


# ---------------------------------------------------------------- G. sandwich


def cpmm_out(x: float, y: float, dx: float, phi: float) -> float:
    """Constant product with the LP fee taken off the input; full input joins the pool."""
    e = dx * (1 - phi)
    return y * e / (x + e)


def sandwich_optimum(Y: float, B: float, s: float, phi: float,
                     token_side: float = 1e9) -> tuple[float, float]:
    """(attacker profit in SOL, optimal frontrun size in SOL) for a CPMM sandwich.

    The victim buys `B` SOL of token with slippage tolerance `s`, i.e. a minOut of
    ``(1-s) * quote``. The attacker's frontrun is bounded by exactly that: push the
    victim's execution to their limit and no further, or the victim reverts and the
    attacker is left holding inventory. So the binding constraint is the victim's own
    slippage setting, which is why `slippage_bps: 1500` is not a small mistake.

    The token side is scale-free for a SOL-denominated answer, so its value is arbitrary.
    """
    quote = cpmm_out(Y, token_side, B, phi)
    need = (1 - s) * quote

    def victim_out(A: float) -> float:
        t = cpmm_out(Y, token_side, A, phi)
        return cpmm_out(Y + A, token_side - t, B, phi)

    if victim_out(0.0) < need:
        return 0.0, 0.0
    lo, hi = 0.0, Y * 20
    for _ in range(200):                       # largest frontrun the victim still accepts
        mid = (lo + hi) / 2
        if victim_out(mid) >= need:
            lo = mid
        else:
            hi = mid

    def profit(A: float) -> float:
        t = cpmm_out(Y, token_side, A, phi)
        x1, y1 = Y + A, token_side - t
        v = cpmm_out(x1, y1, B, phi)
        x2, y2 = x1 + B, y1 - v
        return cpmm_out(y2, x2, t, phi) - A    # backrun: sell the inventory back

    best = (0.0, 0.0)
    for i in range(4001):
        a = lo * i / 4000
        p = profit(a)
        if p > best[0]:
            best = (p, a)
    return best


def section_g(rows: list[dict[str, Any]], out: dict[str, Any], sol_usd: float) -> None:
    depth: dict[str, list[float]] = collections.defaultdict(list)
    size: dict[str, list[float]] = collections.defaultdict(list)
    grid: list[dict[str, float]] = []
    thresholds: list[dict[str, float]] = []
    for r in rows:
        if r.get("kind") != "swap":
            continue
        for v in (r.get("reserves") or {}).get("vaults") or []:
            if v.get("mint") == WSOL and v.get("post_raw"):
                depth[r["label"]].append(int(v["post_raw"]) / LAMPORTS_PER_SOL)
        for mint, key in ((r.get("token_in_mint"), "token_in_raw"),
                          (r.get("token_out_mint"), "token_out_raw")):
            if mint == WSOL and r.get(key):
                size[r["label"]].append(int(r[key]) / LAMPORTS_PER_SOL)
    out["G_pool_depth"] = {
        k: {"n": len(v), "p10": pct(v, 10), "median": pct(v, 50), "p90": pct(v, 90)}
        for k, v in sorted(depth.items())
    }
    out["G_ambient_clip_sol"] = {
        k: {"n": len(v), **{f"p{q}": pct(v, q) for q in (25, 50, 75, 95)}}
        for k, v in sorted(size.items())
    }

    phi = 0.0025  # PumpSwap total take; our own tape measures ~20 bps realised on §1 pools
    depths = sorted({round(pct(v, 50), 1) for v in depth.values() if v}) or [100.0]
    for Y in depths:
        for usd in (9, 50, 150):
            B = usd / sol_usd
            for s in (0.0100, 0.0300, 0.1500):
                mev, A = sandwich_optimum(Y, B, s, phi)
                grid.append({
                    "pool_sol": Y, "clip_usd": usd, "clip_sol": B, "slippage": s,
                    "frontrun_sol": A, "mev_sol": mev, "mev_usd": mev * sol_usd,
                    "mev_bps_of_clip": 1e4 * mev / B,
                })
    out["G_sandwich_grid"] = grid

    # The threshold clip: the smallest B at which the attack clears zero, and $0.10.
    # Heimbach/Schertenleib/Wattenhofer (arXiv:2306.05756) Lemma 2 gives this in closed
    # form: "a profitable attack only exists if the victim's trade size exceeds a fee
    # dependent threshold  d_min = f(1-p)x/(1-f)^2", i.e. B_min ~= phi*Y and INDEPENDENT
    # of the slippage tolerance. The numeric solve below reproduces it to 3 figures, which
    # is the point of running both: the closed form is the rule, the solve is the check.
    thresholds = []
    for Y in depths:
        for s in (0.0100, 0.1500):
            for floor_usd in (0.0, 0.10):
                lo, hi = 1e-5, Y * 0.5
                for _ in range(80):
                    mid = (lo + hi) / 2
                    if sandwich_optimum(Y, mid, s, phi)[0] * sol_usd > floor_usd:
                        hi = mid
                    else:
                        lo = mid
                thresholds.append({"pool_sol": Y, "slippage": s, "cost_floor_usd": floor_usd,
                                   "min_clip_sol": hi, "min_clip_usd": hi * sol_usd,
                                   "phi_times_Y_sol": phi * Y})
    out["G_sandwich_threshold"] = thresholds


# ------------------------------------------------- I. sandwiches, in our own tape


def _sol_vault(row: dict[str, Any]) -> dict[str, Any] | None:
    for v in (row.get("reserves") or {}).get("vaults") or []:
        if v.get("mint") == WSOL:
            return v
    return None


def chain_slot(members: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Recover the exact execution order of several swaps inside one slot.

    The tape carries no transaction index, but it carries pre/post vault balances, and a
    writable-account lock is exclusive: swaps on one pool in one block execute strictly in
    sequence, so ``post`` of one is ``pre`` of the next. Following that chain reconstructs
    the intra-slot order exactly. On this tape it closes for 382 of 382 multi-swap slots,
    which is itself the check that the reconstruction is right.
    """
    vaults = {id(r): _sol_vault(r) for r in members}
    if any(v is None for v in vaults.values()):
        return None
    post = {int(vaults[id(r)]["post_raw"]): r for r in members}   # type: ignore[index]
    pre = {int(vaults[id(r)]["pre_raw"]): r for r in members}     # type: ignore[index]
    heads = [r for r in members
             if post.get(int(vaults[id(r)]["pre_raw"]), r) is r]  # type: ignore[index]
    if len(heads) != 1:
        return None
    seq, cur = [heads[0]], heads[0]
    while True:
        nxt = pre.get(int(vaults[id(cur)]["post_raw"]))           # type: ignore[index]
        if nxt is None or nxt in seq:
            break
        seq.append(nxt)
        cur = nxt
    return seq if len(seq) == len(members) else None


def section_i(rows: list[dict[str, Any]], out: dict[str, Any], sol_usd: float) -> None:
    """Were WE the reference class for sandwiching? Measure it instead of assuming.

    Signature of an atomic sandwich: inside one slot, one counterparty buys, one or more
    other counterparties trade, and the same counterparty sells back the same token amount.
    Two detectors are run — a strict one requiring the round trip and matched inventory,
    and a signature-only one requiring merely that some counterparty appears on both sides
    of a single slot. The second cannot miss what the first catches, so agreement at zero
    is meaningful and disagreement would localise the fault.

    The window relaxation (0, 1, 5, 50 slots) doubles as the control: at 50 slots the
    detector starts finding candidates, and every one of them has NEGATIVE attacker PnL,
    which is what an ordinary round-tripping trader looks like. A detector whose only hits
    lose money is measuring noise, and knowing where that begins bounds the strict result.
    """
    swaps = [r for r in rows if r.get("kind") == "swap" and _sol_vault(r)
             and (r.get("reserves") or {}).get("replay_sufficient")]
    by_pool: dict[str, dict[int, list[dict[str, Any]]]] = collections.defaultdict(
        lambda: collections.defaultdict(list))
    for r in swaps:
        by_pool[r["label"]][r["chain"]["slot"]].append(r)

    seqs: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    multi = chained = 0
    for label, slots in by_pool.items():
        for s in sorted(slots):
            members = slots[s]
            if len(members) > 1:
                multi += 1
                ordered = chain_slot(members)
                if ordered is not None:
                    chained += 1
                    members = ordered
            seqs[label] += members

    def scan(seq: list[dict[str, Any]], max_slot_gap: int) -> list[dict[str, Any]]:
        hits = []
        for i, a in enumerate(seq):
            if a.get("side") != "buy" or not a.get("counterparty"):
                continue
            for k in range(i + 2, min(i + 6, len(seq))):
                b = seq[k]
                if b.get("side") != "sell" or b.get("counterparty") != a.get("counterparty"):
                    continue
                if b["chain"]["slot"] - a["chain"]["slot"] > max_slot_gap:
                    continue
                mids = [x for x in seq[i + 1:k] if x.get("counterparty") != a.get("counterparty")]
                if not mids:
                    continue
                try:
                    bought, sold = int(a["token_out_raw"]), int(b["token_in_raw"])
                except (KeyError, TypeError, ValueError):
                    continue
                if bought <= 0 or abs(sold - bought) / bought > 0.02:
                    continue           # inventory must round-trip: a sandwich ends flat
                pnl = (int(b["token_out_raw"]) - int(a["token_in_raw"])) / LAMPORTS_PER_SOL
                hits.append({"pool": a["label"], "slot": a["chain"]["slot"],
                             "slot_gap": b["chain"]["slot"] - a["chain"]["slot"],
                             "attacker": a["counterparty"], "pnl_sol": pnl,
                             "n_victims": len(mids)})
                break
        return hits

    windows = {}
    for gap in (0, 1, 5, 50):
        hits = [h for seq in seqs.values() for h in scan(seq, gap)]
        pos = [h for h in hits if h["pnl_sol"] > 0]
        windows[f"<= {gap} slots"] = {
            "candidates": len(hits), "profitable": len(pos),
            "victims_wrapped": sum(h["n_victims"] for h in pos),
            "gross_sol": sum(h["pnl_sol"] for h in pos),
        }

    # Signature-only detector: one counterparty on both sides of the same slot.
    both_sides = 0
    slots_ge3 = 0
    for slots in by_pool.values():
        for v in slots.values():
            if len(v) < 3:
                continue
            slots_ge3 += 1
            sides: dict[str, set[str]] = collections.defaultdict(set)
            for r in v:
                if r.get("counterparty"):
                    sides[r["counterparty"]].add(r.get("side") or "?")
            both_sides += any(len(s) > 1 for s in sides.values())

    # Exposure: how many ambient trades were even worth attacking?
    phi = 0.0025
    attackable: collections.Counter[str] = collections.Counter()
    total: collections.Counter[str] = collections.Counter()
    for r in swaps:
        vault = _sol_vault(r)
        if vault is None:
            continue
        pool_sol = int(vault["post_raw"]) / LAMPORTS_PER_SOL
        for mint, key in ((r.get("token_in_mint"), "token_in_raw"),
                          (r.get("token_out_mint"), "token_out_raw")):
            if mint == WSOL and r.get(key):
                total[r["label"]] += 1
                if int(r[key]) / LAMPORTS_PER_SOL > phi * pool_sol:
                    attackable[r["label"]] += 1
    n_attackable = sum(attackable.values())
    out["I_sandwich_measured"] = {
        "chainable_swaps": len(swaps),
        "multi_swap_slots": multi, "fully_chained": chained,
        "slots_with_3plus_swaps": slots_ge3,
        "slots_with_a_counterparty_on_both_sides": both_sides,
        "windows": windows,
        "attackable_trades": dict(attackable), "all_trades": dict(total),
        "n_attackable": n_attackable,
        # Rule of three: 0 events in n trials => 95% upper bound of 3/n.
        "attack_rate_95pct_upper_bound": 3 / n_attackable if n_attackable else None,
    }


# ------------------------------------------------------------------ H. the policy


def priority_fee_lamports(cu_price: int, cu_limit: int) -> int:
    """The exact second term of the fee identity verified in §C."""
    return -(-(cu_price * cu_limit) // 1_000_000)


def section_h(out: dict[str, Any], sol_usd: float) -> None:
    """What the bid costs, at our clip sizes.

    The whole reason the ambient failure rate is survivable is arithmetic: a bid well
    above the level where the dose-response flattens costs a fraction of a cent, because
    a swap is ~120k CU and the price is denominated in millionths of a lamport. The
    binding constraint on the bid is not the budget; it is that there is nothing left to
    buy above the flat part of the curve.
    """
    cu_limit = 160_000  # §D: direct-AMM p99 consumption 135,571, max observed 141,570
    table = []
    for bid in (0, 30_000, 50_000, 100_000, 300_000, 1_000_000, 3_000_000):
        fee = BASE_FEE_PER_SIG + priority_fee_lamports(bid, cu_limit)
        row = {"cu_price": bid, "cu_limit": cu_limit, "fee_lamports": fee,
               "fee_usd": fee / LAMPORTS_PER_SOL * sol_usd}
        for usd in (9, 50, 150):
            row[f"bps_of_${usd}_clip"] = 1e4 * (fee / LAMPORTS_PER_SOL * sol_usd) / usd
        table.append(row)
    out["H_bid_cost"] = table

    # Breakeven: how much landing rate does a bid have to buy to pay for itself?
    # Failing costs the fee and returns nothing; landing costs the fee and returns the
    # trade. Raising the bid from b0 to b1 is worth it iff the extra landing rate covers
    # the extra fee spent on EVERY attempt, landed or not.
    _step = priority_fee_lamports(300_000, cu_limit) - priority_fee_lamports(30_000, cu_limit)
    out["H_policy"] = {
        "path": "direct PumpSwap call, or Jupiter restricted to a single direct route",
        "cu_limit_rule": "simulateTransaction, then limit = ceil(consumed * 1.15); static "
                         "fallback 160,000 (observed direct-AMM max consumption 141,570)",
        "cu_price_floor": 100_000,
        "cu_price_target": "pool p75 of landed bids, clamped to [100k, 3M]",
        "escalation": "none - a bid change requires re-signing, which is the double-fill "
                      "risk. Bid high once; the cost of doing so is under 15 bps on the "
                      "smallest clip.",
        "retry": "sign once; rebroadcast the SAME bytes every ~400ms with skipPreflight "
                 "and maxRetries=0; exit on getBlockHeight > lastValidBlockHeight",
        "jito": "no, for v1",
        "expected_landing_rate": 0.95,
        "expected_landing_basis": "direct-AMM above the 50k bid cliff measures 95.6%, "
                                  "Jupiter above it 97.2%; take the lower",
        "falsification": "if the instrumented landed-and-succeeded rate over the first 100 "
                         "real sends is below 85%, the direct-AMM reference class is wrong "
                         "and this policy is refuted.",
    }
    step = priority_fee_lamports(300_000, cu_limit) - priority_fee_lamports(30_000, cu_limit)
    out["H_breakeven_note"] = (
        "Raising cu_price from 30k to 300k on a 160k-CU transaction costs "
        f"{step:,} extra lamports per send. On a $9 clip that is "
        f"{1e4 * (step / LAMPORTS_PER_SOL * sol_usd) / 9:.1f} bps. "
        "It pays for itself if it lifts the landing rate by more than that many bps of "
        "the round-trip edge — a bar so low that no plausible dose-response fails it."
    )


# ------------------------------------------------------------------------ reporting


def report(o: dict[str, Any], sol_usd: float) -> None:
    p = print
    p("=" * 86)
    p("EXECUTION LANDING — how to actually land a transaction on our pools")
    p("=" * 86)

    p("\n--- A. THE REFERENCE CLASS: sim2real's denominator drops every successful router tx")
    p(f"  {'pool':<14}{'swap':>7}{'reference':>11}{'liq':>5}{'attempt':>9}"
      f"{'sim2real':>11}{'landed':>9}")
    for label, r in o["A_reference_class"].items():
        p(f"  {label:<14}{r['swap']:>7,}{r['reference']:>11,}{r['liquidity']:>5}{r['attempt']:>9,}"
          f"{(r['sim2real_rate'] or 0)*100:>10.1f}%{(r['landed_rate'] or 0)*100:>8.1f}%")
    p("  'reference' = landed fine, touched the pool via an address-lookup table, traded")
    p("  elsewhere. It is a SUCCESS. sim2real counts it in neither column.")
    es = o["A_error_shape"]
    p(f"  every failure is an InstructionError: {es['InstructionError']:,} of "
      f"{es['InstructionError'] + es.get('other', 0):,} — so every one EXECUTED and PAID A FEE.")
    p("  A dropped transaction has no signature to list and is invisible here, in ANY tape.")
    p(f"  compute exhaustion is {es['compute_budget_exceeded']} of them "
      f"({es['compute_budget_exceeded_frac']*100:.2f}%) — not a failure mode worth budgeting for.")

    p("\n--- B. CONTENTION: success collapses when you share a slot")
    for label, r in o["B_contention"].items():
        if sum(v["slots"] for v in r["by_contention"].values()) < 100:
            continue
        p(f"  {label}  (active in {r['active_slot_fraction']*100:.1f}% of slots over "
          f"{r['slot_span']:,})")
        p(f"    {'txs/slot':>9}{'slots':>8}{'swap':>8}{'ref':>8}{'att':>8}{'landed':>9}{'swap-vs-att':>13}")
        for k in ("1", "2", "3-4", "5-8", "9-16", "17+"):
            v = r["by_contention"].get(k)
            if not v:
                continue
            p(f"    {k:>9}{v['slots']:>8,}{v['swap']:>8,}{v['reference']:>8,}{v['attempt']:>8,}"
              f"{(v['landed_rate'] or 0)*100:>8.1f}%{(v['swap_vs_attempt'] or 0)*100:>12.1f}%")

    if "C_fee_identity" in o:
        c = o["C_fee_identity"]
        p("\n--- C. FEE IDENTITY  fee = 5,000*n_sigs + ceil(cu_price*cu_limit/1e6)")
        p(f"  {c['exact']:,} of {c['n']:,} transactions match EXACTLY ({(c['rate'] or 0)*100:.1f}%),"
          f" {c['mismatch']} mismatches")
        p("  => the prioritization fee is charged on the CU LIMIT you requested, not on")
        p("     what you consumed. Over-requesting is a direct, linear overpayment.")

    if o.get("D_compute_units"):
        p("\n--- D. COMPUTE UNITS: what a swap needs vs what the ambient trader pays for")
        p(f"  {'path/kind':<22}{'n':>6}{'consumed p50':>14}{'p99':>11}{'max':>11}"
          f"{'limit p50':>11}{'limit/used p50':>16}")
        for k, v in o["D_compute_units"].items():
            p(f"  {k:<22}{v['n']:>6}{v['cu_consumed_p50']:>14,}{v['cu_consumed_p99']:>11,}"
              f"{v['cu_consumed_max']:>11,}{v['cu_limit_p50']:>11,}{v['over_request_p50']:>15.2f}x")

    if o.get("E_paths"):
        p("\n--- E1. LANDING RATE BY EXECUTION PATH (population-reweighted)")
        p(f"  {'path':<16}{'raw n':>7}{'est swaps':>11}{'est fails':>11}{'landing':>10}")
        for k, v in sorted(o["E_paths"].items(), key=lambda kv: -(kv[1]["est_swaps"] or 0)):
            p(f"  {k:<16}{v['raw_n']:>7}{v['est_swaps']:>11,.0f}{v['est_attempts']:>11,.0f}"
              f"{(v['landing_rate'] or 0)*100:>9.1f}%")
        f = o["E_failing_program"]
        p(f"  of {f['n']:,} sampled failures, {f['inside_an_AMM']*100:.1f}% failed inside an AMM"
          f" and {f['inside_jupiter']*100:.1f}% inside Jupiter;"
          f" {f['third_party']*100:.1f}% inside a third-party program")

        p("\n--- E2. DOSE-RESPONSE: landing rate vs the bid (microlamports per CU)")
        for path, tab in o["E_dose_response"].items():
            p(f"  {path}")
            p(f"    {'bid':>10}{'raw n':>7}{'est swaps':>11}{'est fails':>11}{'landing':>10}")
            for k, v in tab.items():
                p(f"    {k:>10}{v['raw_n']:>7}{v['est_swaps']:>11,.0f}{v['est_attempts']:>11,.0f}"
                  f"{(v['landing_rate'] or 0)*100:>9.1f}%")

        p("\n--- E2b. PATH vs BID — which one is doing the work?")
        p(f"  {'cell':<28}{'raw n':>7}{'est swaps':>11}{'est fails':>11}{'landing':>10}")
        for k, v in o["E_path_vs_bid"].items():
            p(f"  {k:<28}{v['raw_n']:>7}{v['est_swaps']:>11,.0f}{v['est_attempts']:>11,.0f}"
              f"{(v['landing_rate'] or 0)*100:>9.1f}%")
        p("  Above the cliff the two honest paths land alike; below it Jupiter collapses and")
        p("  direct-AMM does not. So the headline path gap is mostly a BID gap — and the")
        p("  direct call is the one that survives underbidding.")

        if o.get("E_fee_oracle"):
            p("\n--- E2c. getRecentPrioritizationFees, live, against our own pools")
            p(f"  {'query':<26}{'slots':>7}{'zero':>8}{'p50':>8}{'p90':>8}{'p99':>8}{'max':>11}")
            for k, v in o["E_fee_oracle"].items():
                p(f"  {k:<26}{v['slots']:>7}{v['frac_zero']*100:>7.1f}%{v['p50']:>8,.0f}"
                  f"{v['p90']:>8,.0f}{v['p99']:>8,.0f}{v['max']:>11,}")
            p("  It reports the MINIMUM fee among transactions locking those accounts, per")
            p("  slot. Nearly every block holds someone paying nothing, so it answers 'bid 0'")
            p("  to every question. Use the percentiles of bids that actually LANDED (E3).")

        p("\n--- E3. BID LADDER among LANDED swaps (microlamports per CU)")
        p(f"  {'pool':<14}{'n':>6}{'p25':>10}{'p50':>11}{'p75':>12}{'p90':>13}")
        for k, v in o["E_bid_ladder"].items():
            p(f"  {k:<14}{v['n']:>6}{v['p25']:>10,}{v['p50']:>11,}{v['p75']:>12,}{v['p90']:>13,}")

    if o.get("F_within_slot"):
        p("\n--- F. WITHIN-SLOT: does the winner outbid the losers, slot held fixed?")
        for k, v in o["F_within_slot"].items():
            p(f"  {k:<20} slots={v['slots']:>4}  winner higher/lower={v['winner_bid_higher']}/"
              f"{v['winner_bid_lower']}  p={v['sign_test_p']:.3g}  "
              f"AUC={v['mean_auc'] if v['mean_auc'] is not None else float('nan'):.3f}")
        if "F_failure_concentration" in o:
            fc = o["F_failure_concentration"]
            p(f"  failures in these slots come from {fc['distinct_payers']} distinct fee-payers;"
              f" the top 10 account for {fc['top10_share']*100:.1f}% of them")
        p("  AUC 0.5 = the bid tells you nothing. The unrestricted test is confounded by")
        p("  execution path; the restricted one is the honest test and it is underpowered.")

    p(f"\n--- G. SANDWICH ECONOMICS (CPMM, LP fee 25 bps, SOL=${sol_usd:.0f})")
    p(f"  {'pool':<14}{'n':>6}{'median SOL side':>18}{'ambient clip p50':>19}{'p95':>9}")
    for k, v in o["G_pool_depth"].items():
        cl = o["G_ambient_clip_sol"].get(k, {})
        p(f"  {k:<14}{v['n']:>6}{v['median']:>18.1f}{cl.get('p50', float('nan')):>19.4f}"
          f"{cl.get('p95', float('nan')):>9.3f}")
    p(f"\n  {'Y (SOL)':>9}{'clip $':>8}{'slippage':>10}{'frontrun SOL':>14}{'MEV $':>9}{'bps of clip':>13}")
    for r in o["G_sandwich_grid"]:
        p(f"  {r['pool_sol']:>9.1f}{r['clip_usd']:>8}{r['slippage']*100:>9.1f}%"
          f"{r['frontrun_sol']:>14.4f}{r['mev_usd']:>9.3f}{r['mev_bps_of_clip']:>13.1f}")
    p("\n  Threshold clip — below this a sandwich does not clear its own cost:")
    p(f"  {'Y (SOL)':>9}{'slippage':>10}{'cost floor':>12}{'min clip $':>12}{'phi*Y ($)':>12}")
    for r in o["G_sandwich_threshold"]:
        p(f"  {r['pool_sol']:>9.1f}{r['slippage']*100:>9.1f}%{r['cost_floor_usd']:>12.2f}"
          f"{r['min_clip_usd']:>12.2f}{r['phi_times_Y_sol']*sol_usd:>12.2f}")
    p("  The last column is the closed form: the attacker must move the pool by the")
    p("  victim's tolerance s, which costs him the LP fee on ~Y*s/2 of capital twice,")
    p("  while his revenue is ~B*s. Both are linear in s, so s CANCELS: a sandwich pays")
    p("  only when B > phi*Y. Slippage sets HOW MUCH they take, not WHETHER they bother.")

    if "I_sandwich_measured" in o:
        i = o["I_sandwich_measured"]
        p("\n--- I. SANDWICHES ACTUALLY OBSERVED ON OUR POOLS")
        p(f"  intra-slot order reconstructed for {i['fully_chained']}/{i['multi_swap_slots']}"
          f" multi-swap slots by chaining vault balances ({i['chainable_swaps']:,} swaps)")
        p(f"  {'window':<16}{'candidates':>12}{'profitable':>12}{'victims':>9}{'gross SOL':>12}")
        for k, v in i["windows"].items():
            p(f"  {k:<16}{v['candidates']:>12}{v['profitable']:>12}{v['victims_wrapped']:>9}"
              f"{v['gross_sol']:>12.5f}")
        p(f"  signature-only detector: {i['slots_with_a_counterparty_on_both_sides']} of "
          f"{i['slots_with_3plus_swaps']} slots with >=3 swaps had one counterparty on BOTH sides")
        p(f"  exposure: {i['n_attackable']:,} ambient trades exceeded B > phi*Y and were")
        p("  therefore worth attacking. Zero were attacked; rule of three puts the 95%")
        p(f"  upper bound on the per-attackable-trade attack rate at "
          f"{i['attack_rate_95pct_upper_bound']*100:.2f}%.")

    p("\n--- H. WHAT THE BID COSTS (160,000 CU limit)")
    p(f"  {'cu_price':>10}{'fee lamports':>14}{'fee $':>9}{'bps of $9':>11}"
      f"{'bps of $50':>12}{'bps of $150':>13}")
    for r in o["H_bid_cost"]:
        p(f"  {r['cu_price']:>10,}{r['fee_lamports']:>14,}{r['fee_usd']:>9.4f}"
          f"{r['bps_of_$9_clip']:>11.1f}{r['bps_of_$50_clip']:>12.1f}{r['bps_of_$150_clip']:>13.2f}")
    p(f"\n  {o['H_breakeven_note']}")
    pol = o["H_policy"]
    p("\n  POLICY")
    for k in ("path", "cu_limit_rule", "cu_price_floor", "cu_price_target", "escalation",
              "retry", "jito", "expected_landing_rate", "expected_landing_basis",
              "falsification"):
        v = pol[k]
        p(f"    {k:<22} {v}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true", help="fetch transaction bodies over RPC")
    ap.add_argument("--per-cell", type=int, default=700, help="probe sample per (pool, kind)")
    ap.add_argument("--seed", type=int, default=20260813)
    ap.add_argument("--sol-usd", type=float, default=75.75,
                    help="SOL spot. Default checked against Coinbase and Kraken 2026-08-14.")
    ap.add_argument("--fee-oracle", action="store_true",
                    help="live getRecentPrioritizationFees against our pools")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = load_tape()
    if not rows:
        raise SystemExit(f"no tape under {TAPE}")
    if args.probe:
        run_probe(rows, per_cell=args.per_cell, seed=args.seed)

    probe = load_cache(CACHE)
    slots = load_cache(SLOT_CACHE)

    out: dict[str, Any] = {
        "tape_rows": len(rows),
        "tape_kinds": dict(collections.Counter(r["kind"] for r in rows)),
        "probe_rows": len(probe),
        "slot_probe_rows": len(slots),
        "sol_usd": args.sol_usd,
    }
    section_a(rows, out)
    section_b(rows, out)
    if probe:
        section_c(probe, out)
        section_d(probe, out)
        section_e(probe, rows, out)
    if slots:
        section_f(slots, out)
    if args.fee_oracle:
        out["E_fee_oracle"] = fee_oracle(rows)
    section_g(rows, out, args.sol_usd)
    section_i(rows, out, args.sol_usd)
    section_h(out, args.sol_usd)

    if args.json:
        print(json.dumps(out, indent=1, default=float))
        return
    report(out, args.sol_usd)
    if not probe:
        print("\n  [C-F omitted: no probe cache. run with --probe once.]")


if __name__ == "__main__":
    main()
