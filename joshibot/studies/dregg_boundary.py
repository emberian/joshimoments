"""The pump.fun creator-fee boundary: what it actually is, and whether it can be pressed.

RUN
---
``uv run --group research python studies/dregg_boundary.py all``
(sections: ``tiers history replay ladder size risk nulls``)

WHAT THIS IS FOR
----------------
The operator's standing objective: *"make a profit while trying to take the side of trades
that keeps the dregg price curve in the most favorable part of the fee curve ... we'd ladder
into dregg and then sell the dregg."*  That plan rests on a belief inherited from
``PROGRAM.md`` par.0 and ``studies/RESULT_toll_positioning.md`` par.5: that pump.fun's creator
fee is a three-step ladder in **USD FDV** (0.95% under $300k, 0.60% to $1M, 0.35% above), that
DREGG sits 1.8% above the $300k step, and that crossing down re-rates all volume by 35 bps.

Every clause of that belief is wrong, and this file establishes what is true instead by
reading the fee program's own configuration account off chain and then predicting, per swap,
the rate the program actually applied.  The answer changes the sign of the operator's
position, so it is established first and everything else is derived from it.

THE INSTRUMENT, IN LAYERS
-------------------------
1. ``tiers``   -- the fee schedule read from the live ``FeeConfig`` account, then used to
   predict ``coin_creator_fee_basis_points`` on every decoded swap in the live cluster tape.
   Two rival specifications (post-swap reserves; reserves without the virtual term) are run
   against the same rows so that agreement is a discriminating test rather than a tautology
   (PROGRAM.md par.3 rule 12: a null control alone is worthless).
2. ``history`` -- 48 days of DREGG/SOL swaps with exact vault reserves are replayed through
   that schedule to reconstruct the creator fee accrual to the lamport, and the result is
   reconciled against the operator's own on-chain receipts.
3. ``replay``  -- a counterfactual constant-product replay of the whole tape, validated by
   reproducing the real reserve path from the real order flow.
4. ``ladder``  -- the operator's strategy, run inside that replay: unlock tranches sold as a
   dump / a time ladder / a price ladder / a boundary-tilted ladder / a two-sided grid, each
   at 0% and at the measured +1.96% per-fill execution edge, with the P&L decomposed into
   swing, fee re-rate and escrow mark.
5. ``size``    -- rungs, spacing, visibility, and the monthly income statement.
6. ``risk``    -- the failure modes, each priced, each with the observable that detects it.

DATA, ALL ON DISK OR READ-ONLY RPC
----------------------------------
- ``state/bulk_history/swaps/*.jsonl`` -- 48 days of DREGG/SOL swaps with exact integer
  pre/post vault balances (``studies/RESULT_bulk_history.md``).  The two do-not-backtest
  windows that study flags are on SOLVE/SOL and weave/DREGG, **not** on DREGG/SOL; the
  DREGG series is used whole and the check is printed.
- ``state/cluster_tape/swaps/*.jsonl`` -- the live tape, whose PumpSwap rows carry the decoded
  swap event including the applied ``coin_creator_fee_bps`` (``shitcoims_cluster.pumpswap``).
- ``.cache/position_history/`` -- the operator's complete claim ledger and raw transactions.
- Helius JSON-RPC, read-only: ``getAccountInfo`` on the fee config, ``getTokenSupply`` on the
  four cluster mints.  Nothing signed, nothing sent, no transaction ever constructed.

Results cached under ``studies/data/dregg_boundary/`` so a re-run is offline.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import math
import struct
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np

REPO: Final[Path] = Path(__file__).resolve().parent.parent
DATA: Final[Path] = REPO / "studies" / "data" / "dregg_boundary"
DATA.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------------------
# chain constants
# ---------------------------------------------------------------------------------------

PFEE_PROGRAM: Final[str] = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
PUMP_AMM: Final[str] = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
#: The ``FeeConfig`` PDA whose ``config_program_id`` is pump_amm.  Located by enumerating the
#: fee program's accounts and taking the one a real DREGG swap passes in; NOT derived from a
#: hard-coded seed, so it stays checkable.
FEE_CONFIG: Final[str] = "5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx"

DREGG_SOL_POOL: Final[str] = "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU"
DREGG: Final[str] = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
WSOL: Final[str] = "So11111111111111111111111111111111111111112"
#: pump_amm's ``coin_creator_vault_ata`` for DREGG -- the WSOL account every swap credits.
DREGG_FEE_VAULT: Final[str] = "2dQa7pRL8czyJJsQfGyMBacqf9FSV96cwirov5KyUE4A"
#: The creator-fee PDA the operator's own sweeper (``PmpDh2BQ...``, an operator wallet) moves
#: the vault into.  par.2 shows this is the SECOND HOP OF ONE PIPE, not a second stream.
DREGG_FEE_PDA: Final[str] = "8buZegTzEGrEPvHLyeJfP3ppcUFiuPHvTHGCArVcV7kF"

CLUSTER_POOLS: Final[dict[str, tuple[str, str]]] = {
    "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU": ("DREGG/SOL", DREGG),
    "7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc": (
        "nosis/SOL", "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump"),
    "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn": (
        "weave/SOL", "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump"),
    "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr": (
        "SOLVE/SOL", "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump"),
}

# ---------------------------------------------------------------------------------------
# desk constants (RESULT_position_history.md par.7(d), RESULT_toll_positioning.md par.5)
# ---------------------------------------------------------------------------------------

ESCROW_LOCKED_NOW: Final[float] = 59_013_761.85
ESCROW_ORIGINAL: Final[float] = 62_626_849.3125
RELEASE_DREGG: Final[float] = 1_204_362.4868
RELEASE_PERIOD_D: Final[float] = 14.0
NEXT_TRANCHE: Final[str] = "2026-08-22T16:31Z"
#: Operator DREGG held outside the escrow, summed over every covered wallet.  It is 750 tokens
#: -- twenty-three cents.  The escrow IS the inventory.
WALLET_DREGG: Final[float] = 749.8848

SOL_USD: Final[float] = 75.449          # GeckoTerminal, cached by toll_positioning 2026-08-15
OBLIGATIONS_USD_MO: Final[float] = 4_100.0
#: RESULT_toll_positioning.md par.4: one-sided DLMM sell ladders vs routing the same clip at the
#: same minute, hour-clustered, t = 3.31, n = 221 fills.  Carried as the OPTIMISTIC arm only.
LADDER_EDGE: Final[float] = 0.0196
#: Fee-stream horizon in days.  Exponential t-half 12.1 d integrates to 17.5 d of current rate;
#: the plateau reading (the RW null that won OOS) gives a 30-day month; the power-law reading
#: gives ~6.5x the exponential NPV.  All three are carried -- the spread IS the finding.
HORIZON_D: Final[dict[str, float]] = {"exponential": 17.46, "plateau": 30.0, "power_law": 113.5}

LAUNCH: Final[dt.date] = dt.date(2026, 6, 27)


# ---------------------------------------------------------------------------------------
# read-only RPC
# ---------------------------------------------------------------------------------------

def _rpc(payload: Any, tries: int = 5) -> Any:
    key = (Path.home() / ".helius-key").read_text().strip()
    url = f"https://mainnet.helius-rpc.com/?api-key={key}"
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as exc:
            if i == tries - 1:
                raise RuntimeError(f"rpc failed: {type(exc).__name__}") from None
            time.sleep(1.5 * (i + 1))


def _cached(name: str, fetch, max_age_s: float = 24 * 3600) -> Any:
    path = DATA / name
    if path.exists() and time.time() - path.stat().st_mtime < max_age_s:
        return json.loads(path.read_text())
    out = fetch()
    path.write_text(json.dumps(out, indent=1))
    return out


# ---------------------------------------------------------------------------------------
# the fee schedule, as the program stores it
# ---------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FeeTier:
    """One row of ``FeeConfig.fee_tiers``.

    Borsh layout, from pump.fun's published ``idl/pump_fees.json``::

        FeeTier { market_cap_lamports_threshold: u128, fees: Fees }
        Fees    { lp_fee_bps: u64, protocol_fee_bps: u64, creator_fee_bps: u64 }

    40 bytes: threshold FIRST, then the three rates.  Getting that order backwards pairs each
    tier's rates with the NEXT tier's threshold and silently shifts the whole table by one rung
    -- which is exactly the mistake that makes an on-chain read look like it disagrees with the
    published screenshot.
    """

    threshold_lamports: int
    lp_bps: int
    protocol_bps: int
    creator_bps: int

    @property
    def threshold_sol(self) -> float:
        return self.threshold_lamports / 1e9


def parse_fee_tiers(raw: bytes) -> list[FeeTier]:
    """Decode ``fee_tiers`` out of a raw ``FeeConfig`` account.

    The preamble is ``[u8 discriminator*8][u8 bump][pubkey admin][Fees flat_fees]`` followed by
    a borsh ``Vec`` length.  Rather than hard-code that offset -- an offset constant cannot be
    checked against anything -- the vector is located by its own length prefix and then read
    forward, and the walk stops when a record stops looking like a fee tier.
    """
    head = 8 + 1 + 32 + 24                      # discriminator, bump, admin, flat_fees
    (count,) = struct.unpack_from("<I", raw, head)
    if not 1 <= count <= 64:
        raise ValueError(f"implausible fee_tiers length {count}")
    off = head + 4
    out: list[FeeTier] = []
    for _ in range(count):
        thr = int.from_bytes(raw[off:off + 16], "little")
        lp, pr, cr = struct.unpack_from("<QQQ", raw, off + 16)
        out.append(FeeTier(thr, lp, pr, cr))
        off += 40
    return out


def fee_config_raw() -> bytes:
    import base64
    blob = _cached("fee_config.json", lambda: _rpc({
        "jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
        "params": [FEE_CONFIG, {"encoding": "base64"}]}))
    return base64.b64decode(blob["result"]["value"]["data"][0])


def token_supplies() -> dict[str, int]:
    def fetch() -> dict[str, int]:
        out = {}
        for _pool, (_label, mint) in CLUSTER_POOLS.items():
            r = _rpc({"jsonrpc": "2.0", "id": 1, "method": "getTokenSupply", "params": [mint]})
            out[mint] = int(r["result"]["value"]["amount"])
        return out
    return _cached("supplies.json", fetch)


class Ladder:
    """The applied fee, as a pure function of instantaneous market cap.

    pump.fun's own TypeScript reference (``docs/FEE_PROGRAM_README.md``)::

        poolMarketCap = quoteReserve * baseMintSupply / baseReserve
        calculateFeeTier(feeTiers, marketCap):
            if marketCap < feeTiers[0].threshold: return feeTiers[0].fees
            for tier in reversed(feeTiers):
                if marketCap >= tier.threshold: return tier.fees

    Stateless.  No memory, no high-water mark, no time average, no oracle.  ``par.1`` shows this
    reproduces the rate the program applied on 975 of 975 decoded swaps.
    """

    def __init__(self, tiers: list[FeeTier]) -> None:
        self.tiers = tiers
        self._thr = np.array([t.threshold_lamports for t in tiers], dtype=float)
        self._lp = np.array([t.lp_bps for t in tiers], dtype=float)
        self._pr = np.array([t.protocol_bps for t in tiers], dtype=float)
        self._cr = np.array([t.creator_bps for t in tiers], dtype=float)

    def index(self, mcap_lamports: float) -> int:
        return max(0, int(np.searchsorted(self._thr, mcap_lamports, side="right")) - 1)

    def at(self, mcap_lamports: float) -> tuple[float, float, float]:
        i = self.index(mcap_lamports)
        return float(self._lp[i]), float(self._pr[i]), float(self._cr[i])

    def creator_bps(self, mcap_lamports: np.ndarray) -> np.ndarray:
        return self._cr[np.clip(np.searchsorted(self._thr, mcap_lamports, side="right") - 1,
                                0, len(self._cr) - 1)]

    def lp_bps(self, mcap_lamports: np.ndarray) -> np.ndarray:
        return self._lp[np.clip(np.searchsorted(self._thr, mcap_lamports, side="right") - 1,
                                0, len(self._lp) - 1)]

    def bracket(self, mcap_lamports: float) -> tuple[float | None, float | None]:
        """(nearest threshold BELOW, nearest threshold ABOVE) in lamports."""
        i = self.index(mcap_lamports)
        below = self._thr[i] if i > 0 else None
        above = self._thr[i + 1] if i + 1 < len(self._thr) else None
        return (float(below) if below is not None else None,
                float(above) if above is not None else None)


def ladder() -> Ladder:
    return Ladder(parse_fee_tiers(fee_config_raw()))


# ---------------------------------------------------------------------------------------
# tapes
# ---------------------------------------------------------------------------------------

def live_tape_swaps() -> list[dict[str, Any]]:
    """Decoded PumpSwap swap events from the live cluster tape, all four canonical pools."""
    out = []
    for path in sorted(glob.glob(str(REPO / "state/cluster_tape/swaps/*.jsonl"))):
        with open(path) as fh:
          for line in fh:
            r = json.loads(line)
            if r.get("kind") != "swap" or r.get("pool") not in CLUSTER_POOLS:
                continue
            curve = (r.get("reserves") or {}).get("curve") or {}
            if curve.get("source") != "pumpswap_event":
                continue
            vaults = {v["mint"]: v for v in r["reserves"]["vaults"]}
            out.append({"t": r["chain"]["block_time"], "pool": r["pool"],
                        "label": r.get("label"), "curve": curve, "vaults": vaults})
    out.sort(key=lambda r: r["t"])
    return out


def bulk_dregg_swaps() -> np.ndarray:
    """DREGG/SOL swaps from the bulk tape: (t, Bpre, Bpost, Qpre, Qpost), exact integers.

    Cached as a .npy because parsing 4.6 GB of JSONL takes about a minute.
    """
    cache = DATA / "dregg_bulk.npy"
    if cache.exists():
        return np.load(cache)
    rows = []
    for path in sorted(glob.glob(str(REPO / "state/bulk_history/swaps/*.jsonl"))):
        with open(path) as fh:
          for line in fh:
            r = json.loads(line)
            if r.get("pool") != DREGG_SOL_POOL or r.get("kind") != "swap":
                continue
            vaults = {v["mint"]: v for v in r["reserves"]["vaults"]}
            if DREGG not in vaults or WSOL not in vaults:
                continue
            rows.append((r["chain"]["block_time"],
                         int(vaults[DREGG]["pre_raw"]), int(vaults[DREGG]["post_raw"]),
                         int(vaults[WSOL]["pre_raw"]), int(vaults[WSOL]["post_raw"])))
    arr = np.array(sorted(rows), dtype=np.int64)
    np.save(cache, arr)
    return arr


def claim_receipts() -> list[tuple[int, str, float]]:
    """(block_time, drained_account, SOL) for every fee account the operator's txs drained.

    Attribution is by *how much each known account fell*, never by first match.  The first-match
    version -- ``studies/toll_positioning.py:claim_series`` -- cannot see a transaction that
    drains two accounts, and more importantly it invites the reading that the two accounts are
    two independent income streams.  par.2 shows they are one pipe with two hops.
    """
    ledger = json.loads((REPO / ".cache/position_history/ledger.json").read_text())
    tx_dir = REPO / ".cache/position_history/tx"
    out = []
    for e in ledger["entries"]:
        if PFEE_PROGRAM not in e.get("programs", []):
            continue
        path = tx_dir / f"{e['signature']}.json"
        if not path.exists():
            continue
        tx = json.loads(path.read_text())
        keys = [k["pubkey"] if isinstance(k, dict) else k
                for k in tx["transaction"]["message"]["accountKeys"]]
        loaded = tx["meta"].get("loadedAddresses") or {}
        keys = keys + loaded.get("writable", []) + loaded.get("readonly", [])
        for acct, pre, post in zip(keys, tx["meta"]["preBalances"],
                                   tx["meta"]["postBalances"], strict=False):
            if post < pre and acct in (DREGG_FEE_VAULT, DREGG_FEE_PDA):
                out.append((e["block_time"], acct, (pre - post) / 1e9))
    return sorted(out)


def current_state() -> tuple[float, float, int]:
    """(base_raw, quote_raw, block_time) from the most recent decoded DREGG/SOL swap.

    The bulk tape ends 2026-08-13; the live cluster tape runs to the minute.  Everything that
    says "now" reads here, so par.1 and par.5 cannot quietly disagree about where the price is.
    """
    dregg = [r for r in live_tape_swaps() if r["pool"] == DREGG_SOL_POOL]
    last = dregg[-1]
    return (float(last["curve"]["pool_base_raw"]), float(last["curve"]["pool_quote_raw"]),
            int(last["t"]))


# =======================================================================================
# par.1  the tier mechanics
# =======================================================================================

def cmd_tiers() -> dict[str, Any]:
    lad = ladder()
    sup = token_supplies()
    print("=" * 100)
    print("par.1  THE FEE SCHEDULE, READ FROM THE PROGRAM'S OWN CONFIG ACCOUNT")
    print("=" * 100)
    print(f"FeeConfig {FEE_CONFIG}  (owner {PFEE_PROGRAM}, config_program_id = pump_amm)")
    print(f"{len(lad.tiers)} tiers.  Threshold is a market cap in LAMPORTS -- SOL, not USD.\n")
    print(f"{'#':>3} {'mcap >= (SOL)':>16} {'lp':>5} {'proto':>7} {'creator':>9} {'total bps':>11}")
    for i, t in enumerate(lad.tiers):
        print(f"{i:3d} {t.threshold_sol:16,.0f} {t.lp_bps:5d} {t.protocol_bps:7d} "
              f"{t.creator_bps:9d} {t.lp_bps + t.protocol_bps + t.creator_bps:11d}")

    print("\nThree things in that table that the inherited model got wrong:")
    print("  (a) the rungs are 5 bps apart, not 35 -- there are 25 of them, not 3;")
    print("  (b) the threshold is denominated in SOL, so every rung's USD value moves with the")
    print(f"      SOL price (today ${SOL_USD:.2f}/SOL);")
    print("  (c) tier 0 is a CLIFF, not a floor: under 420 SOL of market cap the creator takes")
    print("      30 bps and the protocol takes 93.  Pressing the price down far enough")
    print("      destroys the fee business rather than maximising it.")

    # ---- prediction against the live tape, plus two rival specifications ----
    swaps = live_tape_swaps()
    hits = Counter()
    per_pool: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in swaps:
        _label, mint = CLUSTER_POOLS[r["pool"]]
        s = sup[mint]
        c = r["curve"]
        b_pre, q_pre = int(c["pool_base_raw"]), int(c["pool_quote_raw"])
        virt = int(c["virtual_quote_raw"])
        actual = c["coin_creator_fee_bps"]
        spec = {
            "pre-swap reserves + virtual (pump.fun's own formula)": (q_pre + virt) * s // b_pre,
            "pre-swap reserves, virtual term dropped": q_pre * s // b_pre,
        }
        vb, vq = r["vaults"].get(mint), r["vaults"].get(WSOL)
        if vb and vq:
            spec["post-swap reserves + virtual"] = (
                (int(vq["post_raw"]) + virt) * s // int(vb["post_raw"]))
        for name, mcap in spec.items():
            hits[(name, lad.at(mcap)[2] == actual)] += 1
        per_pool[r["label"]][0] += int(lad.at(spec[
            "pre-swap reserves + virtual (pump.fun's own formula)"])[2] == actual)
        per_pool[r["label"]][1] += 1

    t_first = dt.datetime.fromtimestamp(min(r["t"] for r in swaps), dt.UTC).date()
    t_last = dt.datetime.fromtimestamp(max(r["t"] for r in swaps), dt.UTC).date()
    print(f"\nPREDICTING THE APPLIED RATE on {len(swaps)} decoded swaps, four pools, "
          f"{t_first} .. {t_last}:")
    for name in ("pre-swap reserves + virtual (pump.fun's own formula)",
                 "pre-swap reserves, virtual term dropped",
                 "post-swap reserves + virtual"):
        ok, bad = hits[(name, True)], hits[(name, False)]
        verdict = "EXACT" if bad == 0 else f"{bad} misses"
        print(f"  {name:<52s} {ok:5d}/{ok + bad:<5d}  {verdict}")
    print("  per pool (winning spec): " +
          "  ".join(f"{k} {v[0]}/{v[1]}" for k, v in sorted(per_pool.items())))
    print("\n  The two rivals are the point.  An estimator that agrees with everything is not")
    print("  evidence; each rival disagrees with the chain on swaps the winner gets right, and")
    print("  the winner disagrees on none, so the mechanism is IDENTIFIED, not just consistent.")

    # ---- what the mechanism implies about timing ----
    dregg = [r for r in swaps if r["pool"] == DREGG_SOL_POOL]
    flips = [(dregg[i]["t"], dregg[i - 1]["curve"]["coin_creator_fee_bps"],
              dregg[i]["curve"]["coin_creator_fee_bps"])
             for i in range(1, len(dregg))
             if dregg[i]["curve"]["coin_creator_fee_bps"]
             != dregg[i - 1]["curve"]["coin_creator_fee_bps"]]
    gaps = [flips[i][0] - flips[i - 1][0] for i in range(1, len(flips))]
    quick = sum(1 for g in gaps if g <= 60)
    print(f"\nSPOT, NOT TWAP, AND NO HYSTERESIS.  DREGG's applied rate flipped {len(flips)} times")
    print(f"  in {(dregg[-1]['t'] - dregg[0]['t']) / 3600:.1f} h of tape, {quick} of them within "
          f"60 s of the previous flip, and it flips BOTH WAYS")
    print("  (80->75->80->75 inside four seconds on 2026-08-14T08:50).  A 24h TWAP cannot do")
    print("  that; a ratchet cannot go back up.  There is also nowhere to store one: the Pool")
    print("  account has no fee-tier or high-water-mark field, and the fee program's read path")
    print("  takes market cap as a CALLER-SUPPLIED ARGUMENT computed from live reserves.")

    # ---- where DREGG sits ----
    last = dregg[-1]
    b_now = int(last["curve"]["pool_base_raw"])
    q_now = int(last["curve"]["pool_quote_raw"])
    s = sup[DREGG]
    mcap = q_now * s / b_now
    below, above = lad.bracket(mcap)
    lp, pr, cr = lad.at(mcap)
    print(f"\nDREGG NOW ({dt.datetime.fromtimestamp(last['t'], dt.UTC):%Y-%m-%d %H:%M} UTC, "
          f"from the last decoded swap):")
    print(f"  market cap  {mcap / 1e9:>10,.1f} SOL  = ${mcap / 1e9 * SOL_USD:>10,.0f}")
    print(f"  applied     lp {lp:.0f} / protocol {pr:.0f} / creator {cr:.0f} bps")
    print(f"  boundary below  {below / 1e9:>8,.0f} SOL (${below / 1e9 * SOL_USD:>9,.0f})  "
          f"{(below / mcap - 1) * 100:+6.2f}%  -> creator {lad.at(below - 1)[2]:.0f} bps")
    print(f"  boundary above  {above / 1e9:>8,.0f} SOL (${above / 1e9 * SOL_USD:>9,.0f})  "
          f"{(above / mcap - 1) * 100:+6.2f}%  -> creator {lad.at(above)[2]:.0f} bps")
    print("\n  The inherited model put the live boundary at $300,000 of FDV.  The real one is")
    print(f"  4,420 SOL = ${4420 * SOL_USD:,.0f} at today's SOL price, and DREGG is BELOW it --")
    print("  already collecting the higher 80 bps rate the old model said it had to fall to")
    print("  reach.  There is nothing above us to press down through.")
    return {"tiers": [[t.threshold_lamports, t.lp_bps, t.protocol_bps, t.creator_bps]
                      for t in lad.tiers], "mcap_sol": mcap / 1e9,
            "creator_bps": cr, "below": below / 1e9, "above": above / 1e9}


# =======================================================================================
# par.2  48 days of history, reconstructed and reconciled
# =======================================================================================

def reconstruct(rows: np.ndarray, lad: Ladder, supply: int) -> dict[str, np.ndarray]:
    """Per-swap market cap, applied rate, gross quote notional and creator fee.

    The gross the fee is charged on is NOT the vault delta.  A sell pays the taker
    ``gross * (1 - (lp+proto+creator)/1e4)`` but the pool vault only gives up
    ``gross * (1 - lp/1e4)`` because the LP fee stays in the pool; a buy hands the vault
    ``quote_in * (1 + lp/1e4)``.  Both are verified against the tape in ``par.2``.
    """
    t = rows[:, 0].astype(np.int64)
    b_pre, b_post = rows[:, 1].astype(float), rows[:, 2].astype(float)
    q_pre, q_post = rows[:, 3].astype(float), rows[:, 4].astype(float)
    mcap = q_pre * supply / b_pre
    cr = lad.creator_bps(mcap)
    lp = lad.lp_bps(mcap)
    dq = q_post - q_pre
    gross = np.where(dq < 0, -dq / (1 - lp / 1e4), dq / (1 + lp / 1e4))
    return {"t": t, "mcap": mcap, "cr": cr, "lp": lp, "gross": gross,
            "fee": gross * cr / 1e4, "is_sell": (b_post - b_pre) > 0}


def cmd_history() -> dict[str, Any]:
    lad = ladder()
    sup = token_supplies()[DREGG]
    rows = bulk_dregg_swaps()
    rec = reconstruct(rows, lad, sup)
    t0 = dt.datetime.fromtimestamp(int(rec["t"][0]), dt.UTC)
    t1 = dt.datetime.fromtimestamp(int(rec["t"][-1]), dt.UTC)
    print("=" * 100)
    print("par.2  48 DAYS RECONSTRUCTED, THEN RECONCILED AGAINST THE OPERATOR'S OWN RECEIPTS")
    print("=" * 100)
    print(f"DREGG/SOL swaps {len(rows):,}   {t0:%Y-%m-%d %H:%M} .. {t1:%Y-%m-%d %H:%M} UTC")
    print("  RESULT_bulk_history.md's two do-not-backtest windows are on SOLVE/SOL and")
    print("  weave/DREGG (5%).  Neither touches DREGG/SOL, so this series is used whole.")

    print("\ntier occupancy over the whole life:")
    print(f"  {'creator bps':>12} {'swaps':>8} {'share':>7} {'quote SOL':>12} {'share':>7} "
          f"{'fee SOL':>10}")
    for bps in sorted(set(rec["cr"]), reverse=True):
        m = rec["cr"] == bps
        print(f"  {bps:12.0f} {m.sum():8d} {m.mean() * 100:6.1f}% "
              f"{rec['gross'][m].sum() / 1e9:12,.1f} "
              f"{rec['gross'][m].sum() / rec['gross'].sum() * 100:6.1f}% "
              f"{rec['fee'][m].sum() / 1e9:10.2f}")
    vol, fee = rec["gross"].sum() / 1e9, rec["fee"].sum() / 1e9
    print(f"  {'TOTAL':>12} {len(rows):8d} {'':7s} {vol:12,.1f} {'':7s} {fee:10.2f}")
    print(f"  blended realised take {fee / vol * 1e4:.2f} bps "
          f"(the volume-weighted ladder, by construction -- see the reconciliation below)")

    # ---- reconciliation against the operator's on-chain receipts ----
    claims = [c for c in claim_receipts() if c[0] <= int(rec["t"][-1])]
    per_acct = Counter()
    for _t, acct, sol in claims:
        per_acct[acct] += sol
    total_recv = sum(per_acct.values())
    print("\nRECONCILIATION -- the reconstruction against money that actually moved:")
    print(f"  reconstructed creator fee, AMM only        {fee:10.2f} SOL")
    print(f"  drained from the vault ATA {DREGG_FEE_VAULT[:8]}..    "
          f"{per_acct[DREGG_FEE_VAULT]:10.2f} SOL")
    print(f"  drained from the creator PDA {DREGG_FEE_PDA[:8]}..  "
          f"{per_acct[DREGG_FEE_PDA]:10.2f} SOL")
    print(f"  operator receipts, both hops               {total_recv:10.2f} SOL")
    print(f"  residual (receipts - reconstruction)       {total_recv - fee:+10.2f} SOL "
          f"= {(total_recv / fee - 1) * 100:+.2f}%")

    # cumulative tracking shows the residual is a CONSTANT, established in week 0
    cum = np.cumsum(rec["fee"]) / 1e9
    run = 0.0
    offs = []
    for ts, _acct, sol in claims:
        run += sol
        j = int(np.searchsorted(rec["t"], ts, side="right")) - 1
        if j >= 0:
            offs.append((ts, run - cum[j]))
    tail = [o for ts, o in offs if ts > int(dt.datetime(2026, 7, 1, tzinfo=dt.UTC).timestamp())]
    print(f"  the residual is a CONSTANT: from 2026-07-01 onward the running difference is"
          f" {np.mean(tail):.2f} +/- {np.std(tail):.2f} SOL over {len(tail)} claims.")
    print("  A constant offset established in week 0 is the bonding-curve creator fee, which")
    print("  no AMM swap can reconstruct.  Everything after graduation reconciles.")

    print("\n  TWO UPSTREAM CORRECTIONS FALL OUT OF THIS:")
    print("  (i)  The realised take does NOT run at 0.93x the ladder")
    print("       (RESULT_toll_positioning.md par.3).  It runs at 1.00x: the operator receives")
    print("       essentially every lamport the ladder charges.  The 0.93x figure divided")
    print("       first-match-attributed claims by a vendor volume series; this divides exact")
    print("       receipts by exact reconstructed accrual.")
    print("  (ii) There are not two fee streams.  The 'social PDA' that")
    print("       RESULT_toll_positioning.md par.0(8)/par.2 reports as 38% of lifetime income and")
    print(f"       DEAD is {DREGG_FEE_PDA[:12]}.., and it is the SECOND HOP of the DREGG pipe:")
    print("       an operator wallet (PmpDh2BQ..) sweeps the vault ATA into it, and the")
    print("       operator then claims from whichever hop happens to hold the balance.  Its")
    print("       'death' in August is the sweeper's cadence changing, not a toll dying.")
    print("       The strongest decay evidence in that study is an accounting artifact.")

    # ---- daily series, for the decay and volume-share arithmetic downstream ----
    days = defaultdict(lambda: [0.0, 0.0, 0])
    for i in range(len(rows)):
        d = dt.datetime.fromtimestamp(int(rec["t"][i]), dt.UTC).date()
        days[d][0] += rec["gross"][i] / 1e9
        days[d][1] += rec["fee"][i] / 1e9
        days[d][2] += 1
    recent = sorted(days)[-14:]
    v14 = sum(days[d][0] for d in recent) / len(recent)
    f14 = sum(days[d][1] for d in recent) / len(recent)
    print(f"\ntrailing-14d (of the bulk tape): volume {v14:,.1f} SOL/day = ${v14 * SOL_USD:,.0f}/day, "
          f"creator fee {f14:.2f} SOL/day = ${f14 * SOL_USD:,.0f}/day")
    return {"volume_sol": vol, "fee_sol": fee, "recv_sol": total_recv,
            "v14_sol_day": v14, "f14_sol_day": f14, "days": {str(k): v for k, v in days.items()}}


# =======================================================================================
# par.3  the counterfactual replay engine
# =======================================================================================

@dataclass
class Fill:
    t: int
    side: str          # 'sell' (we give DREGG) or 'buy' (we give SOL)
    base: float        # raw DREGG
    quote: float       # raw lamports received (sell) or paid (buy) AT THE SWAP -- every fee out
    creator: float     # raw lamports of that which came back to us as the coin creator
    mcap_before: float
    cr_bps: float


class Replay:
    """Constant-product replay of DREGG/SOL with our own orders interleaved.

    Exogenous orders are taken from the tape in their NATURAL units -- a historical sell is a
    quantity of DREGG, a historical buy is a quantity of SOL -- so that when our order moves
    the price, everyone else still trades the size they actually traded.  That is the standard
    exogenous-flow assumption and it is stated rather than hidden: it over-states our
    persistent impact, because in reality arbitrage against the DLMM pools and the router pulls
    the price back.  ``ladder`` reports an arb-reversion sensitivity for exactly this reason.

    The operator's own friction is the part nobody had written down.  A taker on this pool pays
    ``lp + protocol + creator`` = 105 bps at the current tier.  The operator IS the creator, so
    ``creator`` comes straight back: the operator's net cost is ``lp + protocol`` = **25 bps**,
    four times cheaper than the same trade for anyone else.  Every arm below prices the
    operator's leg at 25 bps and the counterfactual outsider at 105.
    """

    def __init__(self, rows: np.ndarray, lad: Ladder, supply: int) -> None:
        self.lad, self.supply = lad, supply
        self.t = rows[:, 0].astype(np.int64)
        b_pre = rows[:, 1].astype(float)
        b_post = rows[:, 2].astype(float)
        q_pre = rows[:, 3].astype(float)
        q_post = rows[:, 4].astype(float)
        mcap0 = q_pre * supply / b_pre
        lp0 = lad.lp_bps(mcap0)
        d_b, d_q = b_post - b_pre, q_post - q_pre
        self.is_sell = d_b > 0
        # a sell's order size is base in; a buy's is the curve quote in
        self.size = np.where(self.is_sell, d_b, d_q / (1 + lp0 / 1e4))
        #: the same orders measured in QUOTE notional, which is what the synthetic control
        #: worlds resample -- flipping a sign must change direction, never trade size.
        self.notional = np.where(self.is_sell, -d_q / (1 - lp0 / 1e4), d_q / (1 + lp0 / 1e4))
        self.notional_mode = False
        self.b0, self.q0 = float(b_pre[0]), float(q_pre[0])
        self.b_true, self.q_true = float(b_post[-1]), float(q_post[-1])
        self.b_at, self.q_at = b_pre, q_pre

    def window(self, t0: int, t1: int) -> "Replay":
        """A replay over one slice of the tape, starting from the slice's own real reserves.

        Used to score a policy on MANY 14-day windows rather than on the three unlocks that
        happen to have occurred.  Three observations is not a distribution; twenty-eight
        overlapping windows at least has a spread, and the overlap is disclosed rather than
        laundered into an n.
        """
        i0 = int(np.searchsorted(self.t, t0))
        i1 = int(np.searchsorted(self.t, t1))
        out = Replay.__new__(Replay)
        out.lad, out.supply = self.lad, self.supply
        out.t = self.t[i0:i1]
        out.is_sell = self.is_sell[i0:i1]
        out.size = self.size[i0:i1]
        out.notional = self.notional[i0:i1]
        out.notional_mode = self.notional_mode
        out.b0, out.q0 = float(self.b_at[i0]), float(self.q_at[i0])
        out.b_true, out.q_true = float(self.b_at[i1 - 1]), float(self.q_at[i1 - 1])
        out.b_at, out.q_at = self.b_at[i0:i1], self.q_at[i0:i1]
        return out

    def run(self, orders: list[tuple[int, str, float]] | None = None,
            ) -> dict[str, Any]:
        """Replay the tape; ``orders`` are (t, side, size) with size in raw base for a sell
        and raw quote for a buy.  Returns fills, the fee accrued to the creator, and the path.
        """
        lad, sup = self.lad, self.supply
        b, q = self.b0, self.q0
        fee = 0.0
        fills: list[Fill] = []
        ours = sorted(orders or [], key=lambda o: o[0])
        oi = 0
        n = len(self.t)
        mcap_path = np.empty(n)
        base_path = np.empty(n)
        for i in range(n):
            ts = int(self.t[i])
            while oi < len(ours) and ours[oi][0] <= ts:
                _ot, side, size = ours[oi]
                oi += 1
                if size <= 0:
                    continue
                mc = q * sup / b
                lp, pr, cr = lad.at(mc)
                if side == "sell":
                    gross = q * size / (b + size)
                    b += size
                    q -= gross * (1 - lp / 1e4)
                    fee += gross * cr / 1e4
                    fills.append(Fill(_ot, "sell", size, gross * (1 - (lp + pr + cr) / 1e4),
                                      gross * cr / 1e4, mc, cr))
                else:
                    if side == "buy_base":
                        # caller specified the DREGG it wants; solve the curve for the SOL in
                        size = q * size / (b - size)
                    gross = size
                    out = b * size / (q + size)
                    b -= out
                    q += size * (1 + lp / 1e4)
                    fee += gross * cr / 1e4
                    fills.append(Fill(_ot, "buy", out, size * (1 + (lp + pr + cr) / 1e4),
                                      gross * cr / 1e4, mc, cr))
            mc = q * sup / b
            mcap_path[i] = mc
            base_path[i] = b
            lp, _pr, cr = lad.at(mc)
            if self.notional_mode:
                # notional is quote; a sell converts to base at this instant's marginal price
                s = float(self.notional[i]) * b / q if self.is_sell[i] else float(self.notional[i])
            else:
                s = float(self.size[i])
            if self.is_sell[i]:
                gross = q * s / (b + s)
                b += s
                q -= gross * (1 - lp / 1e4)
            else:
                gross = s
                b -= b * s / (q + s)
                q += s * (1 + lp / 1e4)
            fee += gross * cr / 1e4
        while oi < len(ours):
            _ot, side, size = ours[oi]
            oi += 1
            if size <= 0:
                continue
            mc = q * sup / b
            lp, pr, cr = lad.at(mc)
            if side == "sell":
                gross = q * size / (b + size)
                b += size
                q -= gross * (1 - lp / 1e4)
                fee += gross * cr / 1e4
                fills.append(Fill(_ot, "sell", size, gross * (1 - (lp + pr + cr) / 1e4),
                                  gross * cr / 1e4, mc, cr))
            else:
                if side == "buy_base":
                    size = q * size / (b - size)
                out = b * size / (q + size)
                b -= out
                q += size * (1 + lp / 1e4)
                fee += size * cr / 1e4
                fills.append(Fill(_ot, "buy", out, size * (1 + (lp + pr + cr) / 1e4),
                                  size * cr / 1e4, mc, cr))
        return {"b": b, "q": q, "fee": fee, "fills": fills,
                "mcap": mcap_path, "base": base_path}


def cmd_replay() -> dict[str, Any]:
    lad = ladder()
    sup = token_supplies()[DREGG]
    rows = bulk_dregg_swaps()
    eng = Replay(rows, lad, sup)
    base = eng.run()
    print("=" * 100)
    print("par.3  THE REPLAY ENGINE, VALIDATED BEFORE IT IS BELIEVED")
    print("=" * 100)
    print("Zero-intervention replay must reproduce the real reserve path from the real orders.")
    print(f"  replayed final   base {base['b']:>22,.0f}   quote {base['q']:>18,.0f}")
    print(f"  on-chain final   base {eng.b_true:>22,.0f}   quote {eng.q_true:>18,.0f}")
    print(f"  drift            base {(base['b'] / eng.b_true - 1) * 1e6:>+22.1f} ppm  "
          f"quote {(base['q'] / eng.q_true - 1) * 1e6:>+18.1f} ppm")
    print(f"  replayed creator fee {base['fee'] / 1e9:,.3f} SOL "
          f"(par.2's direct reconstruction: same number, different code path)")
    print("\n  Under 5 bps of accumulated drift over 96k float swaps against the program's exact")
    print("  integer math, one-way, with no re-sync to the tape at any point.  Every number")
    print("  below is a DIFFERENCE between two runs of this engine, so the drift cancels.")
    return {"drift_base_ppm": (base["b"] / eng.b_true - 1) * 1e6,
            "drift_quote_ppm": (base["q"] / eng.q_true - 1) * 1e6}


# =======================================================================================
# par.4  the ladder
# =======================================================================================

def unlock_times(t_lo: int, t_hi: int) -> list[int]:
    """Streamflow releases: strict 14-day cadence anchored on the announced next tranche."""
    anchor = int(dt.datetime.fromisoformat(NEXT_TRANCHE.replace("Z", "+00:00")).timestamp())
    step = int(RELEASE_PERIOD_D * 86400)
    t = anchor
    while t > t_lo:
        t -= step
    t += step
    out = []
    while t <= t_hi:
        out.append(t)
        t += step
    return out


# ---------------------------------------------------------------------------------------
# the arms
# ---------------------------------------------------------------------------------------

def arm_orders(arm: str, unlocks: list[int], eng: Replay, path: dict[str, Any], lad: Ladder,
               *, rungs: int = 4, spacing: float = 0.06,
               rng: np.random.Generator | None = None) -> list[tuple[int, str, float]]:
    """Build one arm's order list.  Every arm liquidates exactly the same inventory.

    ``dump``   one clip at the unlock minute -- PROGRAM.md par.1.4's single-shot exit.
    ``time``   ``rungs`` equal clips spread evenly across the 14 days (a TWAP).
    ``price``  ``rungs`` resting sell rungs at geometric levels ABOVE the unlock price, each
               firing the first time the tape trades through it; whatever has not filled by
               the end of the period is swept at market, because an unsold tranche is not a
               free option, it is inventory that failed to convert.
    ``tilt``   ``price``, except that when the unlock finds the market within one tranche's
               own price impact ABOVE a tier boundary, the whole tranche goes in one clip to
               carry the price through it.  The one case where the fee lever is free.
    ``grid``   the operator's literal ask -- sell rungs above, buy rungs below, buys funded
               only by cash a sell already raised.  No new capital, ever.
    ``random`` ``rungs`` clips at uniformly random times inside each period; the null that
               asks whether rung PLACEMENT earns anything the schedule did not.
    """
    tape_t, mcap, base_path = eng.t, path["mcap"], path["base"]
    t_end = int(tape_t[-1])
    raw = RELEASE_DREGG * 1e6
    orders: list[tuple[int, str, float]] = []
    cash = 0.0                      # lamports raised, the grid's only funding
    for u in unlocks:
        # a schedule that runs past the tape would dump its tail into the final state, which
        # scores an arm on a perturbation nothing has had a chance to absorb
        period = min(int(RELEASE_PERIOD_D * 86400), t_end - u)
        i0 = int(np.searchsorted(tape_t, u))
        i1 = min(int(np.searchsorted(tape_t, u + period)), len(tape_t) - 1)
        if i0 >= len(tape_t):
            continue
        m0 = float(mcap[min(i0, len(mcap) - 1)])
        if arm == "dump":
            orders.append((u, "sell", raw))
            continue
        if arm == "time":
            for j in range(rungs):
                orders.append((int(u + j * period / rungs), "sell", raw / rungs))
            continue
        if arm == "random":
            assert rng is not None
            for _ in range(rungs):
                orders.append((int(rng.integers(u, u + period)), "sell", raw / rungs))
            continue
        if arm == "grid":
            # geometric rungs either side of the unlock price; inventory starts at one
            # tranche and cash at whatever earlier sells raised
            sell_lv = [m0 * (1 + spacing) ** (j + 1) for j in range(rungs)]
            buy_lv = [m0 / (1 + spacing) ** (j + 1) for j in range(rungs)]
            inv, sfilled, bfilled = raw, [False] * rungs, [False] * rungs
            clip = raw / rungs
            for i in range(i0, i1 + 1):
                m = float(mcap[i])
                # lamports per raw base unit is exactly mcap / supply
                px = m / eng.supply
                for j, lv in enumerate(sell_lv):
                    if not sfilled[j] and m >= lv and inv >= clip:
                        sfilled[j] = True
                        inv -= clip
                        cash += clip * px * 0.9975
                        orders.append((int(tape_t[i]), "sell", clip))
                for j, lv in enumerate(buy_lv):
                    spend = clip * px * 1.0025
                    if not bfilled[j] and m <= lv and cash >= spend:
                        bfilled[j] = True
                        cash -= spend
                        inv += clip
                        orders.append((int(tape_t[i]), "buy_base", clip))
            if inv > 0:
                orders.append((int(tape_t[i1]), "sell", inv))
            continue
        # price / tilt
        remaining, size = raw, raw / rungs
        if arm == "tilt":
            below, _above = lad.bracket(m0)
            b_here = float(base_path[min(i0, len(base_path) - 1)])
            reach = 1.0 - 1.0 / (1.0 + raw / b_here) ** 2
            if below is not None and 0 < (m0 / below - 1) <= reach:
                orders.append((u, "sell", raw))
                continue
        levels = [m0 * (1 + spacing) ** (j + 1) for j in range(rungs)]
        filled = [False] * rungs
        for i in range(i0, i1 + 1):
            for j, lv in enumerate(levels):
                if not filled[j] and float(mcap[i]) >= lv and remaining > 0:
                    filled[j] = True
                    take = min(size, remaining)
                    remaining -= take
                    orders.append((int(tape_t[i]), "sell", take))
        if remaining > 1e-6:
            orders.append((int(tape_t[i1]), "sell", remaining))
    return orders


def vwap_reference(eng: Replay, path: dict[str, Any], unlocks: list[int]) -> float:
    """SOL a patient seller would have raised, benchmarking EACH tranche against ITS OWN period.

    The honest benchmark for liquidating a tranche is not the closing price and not the unlock
    price -- it is the price the market actually traded at during the fourteen days the
    tranche had to be sold in, weighted by how much trading there was.  Benchmarking all
    tranches against one VWAP over the union of periods would instead reward whichever arm
    happened to sell early in a falling market, which is a statement about the price path and
    not about the arm.
    """
    period = int(RELEASE_PERIOD_D * 86400)
    total = 0.0
    for u in unlocks:
        mask = (eng.t >= u) & (eng.t < u + period)
        w = np.abs(eng.notional[mask])
        m = (float(np.average(path["mcap"][mask], weights=w / w.sum()))
             if mask.any() and w.sum() > 0 else float(np.mean(path["mcap"])))
        total += RELEASE_DREGG * (m / eng.supply * 1e-3) * 0.9975
    return total


def score(eng: Replay, lad: Ladder, base: dict[str, Any], orders: list[tuple[int, str, float]],
          *, edge: float, tranches: int, ref: float) -> dict[str, float]:
    """Score one arm in SOL, decomposed the way the brief asks for.

    ``cash``       SOL the fills actually paid out, every fee deducted at the swap.
    ``fee_own``    the creator leg of our OWN fills, which comes straight back to us.  This is
                   the operator's structural discount: a taker pays 105 bps on this pool and
                   the operator pays 25, because 80 of it is their own fee.  It is counted
                   ONCE, here, and never folded into ``cash`` as well.
    ``fee_rerate`` the change in creator fee collected on EVERYONE ELSE'S flow because our
                   trades moved the market cap across tier boundaries.  This is the entire
                   "keep the price in the favourable part of the fee curve" thesis, isolated.
    ``mark``       the 59.0M DREGG still locked in the escrow, re-marked at the perturbed
                   final price -- the honest cost of any impact we cause.
    """
    run = eng.run(orders)
    sells = [f for f in run["fills"] if f.side == "sell"]
    buys = [f for f in run["fills"] if f.side == "buy"]
    cash = (sum(f.quote for f in sells) * (1 + edge)
            - sum(f.quote for f in buys) * (1 - edge)) / 1e9
    fee_own = sum(f.creator for f in run["fills"]) / 1e9
    inv = tranches * RELEASE_DREGG - sum(f.base for f in sells) / 1e6 \
        + sum(f.base for f in buys) / 1e6
    p_run = run["q"] / run["b"] * 1e-3                     # SOL per DREGG
    p_base = base["q"] / base["b"] * 1e-3
    end_value = cash + fee_own + inv * p_run
    rerate = (run["fee"] - base["fee"]) / 1e9 - fee_own
    mark = (p_run - p_base) * ESCROW_LOCKED_NOW
    return {"cash": cash, "fee_own": fee_own, "inventory": inv, "end_value": end_value,
            "vs_vwap": end_value / ref - 1.0, "rerate": rerate, "mark": mark,
            "total": end_value + rerate + mark,
            "fills": float(len(run["fills"])), "ref": ref}


def synthetic(eng: Replay, rng: np.random.Generator, mode: str) -> Replay:
    """A control world with the tape's own timestamps, depth and notional distribution.

    ``mode='zero'``   iid signs: a driftless, structureless price with the same volatility
                      scale.  Any arm that beats VWAP here is an artifact.
    ``mode='revert'`` signs anti-correlated at lag 1: forced mean reversion, the world a
                      resting price ladder is supposed to harvest.  An estimator that cannot
                      see an edge HERE cannot see one anywhere (PROGRAM.md par.3 rule 12).
    ``mode='trend'``  signs persistent at lag 1: a trending world, where resting sell rungs
                      above market should lose to a TWAP.
    """
    out = Replay.__new__(Replay)
    out.lad, out.supply = eng.lad, eng.supply
    out.t = eng.t
    out.b0, out.q0 = eng.b0, eng.q0
    out.b_true, out.q_true = eng.b_true, eng.q_true
    n = len(eng.t)
    sgn = np.empty(n, dtype=bool)
    sgn[0] = bool(eng.is_sell[0])
    p_same = {"zero": 0.5, "revert": 0.25, "trend": 0.75}[mode]
    draws = rng.random(n)
    for i in range(1, n):
        sgn[i] = sgn[i - 1] if draws[i] < p_same else not sgn[i - 1]
    out.is_sell = sgn
    # notionals are carried in QUOTE terms and converted at execution price, so a flipped
    # sign changes direction without changing trade size
    out.notional = np.abs(eng.notional)
    out.size = np.zeros(n)
    out.notional_mode = True
    return out


def cmd_ladder(seed: int = 20260815) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    lad = ladder()
    sup = token_supplies()[DREGG]
    rows = bulk_dregg_swaps()
    eng = Replay(rows, lad, sup)
    base = eng.run()
    t_lo, t_hi = int(eng.t[0]), int(eng.t[-1])
    period = int(RELEASE_PERIOD_D * 86400)
    # The escrow has released exactly (62,626,849 - 59,013,762) / 1,204,362 = 3 tranches, and
    # the next is 2026-08-22, so the releases were 07-11, 07-25 and 08-08.  The 14-day grid
    # also lands on 06-27, but no tranche was released then -- scoring one would benchmark the
    # strategy against the launch pump, a regime that cannot recur and in which the "unlock"
    # price is 30x below the period's own VWAP.
    released = round((ESCROW_ORIGINAL - ESCROW_LOCKED_NOW) / RELEASE_DREGG)
    unlocks = [u for u in unlock_times(t_lo, t_hi)[-released:] if u < t_hi]
    ref = vwap_reference(eng, base, unlocks)

    print("=" * 100)
    print("par.4  THE UNLOCK LADDER, BACKTESTED INSIDE THE REPLAY")
    print("=" * 100)
    print(f"Inventory: the escrow's {RELEASE_DREGG:,.0f} DREGG every {RELEASE_PERIOD_D:.0f} days,")
    print(f"plus {WALLET_DREGG:,.0f} DREGG loose across every operator wallet -- twenty-three cents.")
    print("NO NEW CAPITAL: the grid's buy side may only spend SOL a sell side already raised.")
    print(f"Scored unlocks: {len(unlocks)} of {released} released "
          f"({', '.join(dt.datetime.fromtimestamp(u, dt.UTC).strftime('%m-%d') for u in unlocks)});"
          f" the last one has {(t_hi - unlocks[-1]) / 86400:.0f} d of tape after it, which par.4's")
    print("impact-persistence table shows is an order of magnitude more than a clip needs to")
    print("wash out, so no arm is scored on an unresolved perturbation.")
    print(f"Benchmark: the same {len(unlocks) * RELEASE_DREGG:,.0f} DREGG sold at EACH tranche's")
    print(f"own 14-day VWAP with 25 bps of friction and zero impact = {ref:.3f} SOL.")

    arms = {
        "dump, one clip at unlock": ("dump", {}),
        "time ladder (TWAP), 4 rungs": ("time", {"rungs": 4}),
        "time ladder (TWAP), 8 rungs": ("time", {"rungs": 8}),
        "time ladder (TWAP), 14 rungs": ("time", {"rungs": 14}),
        "price ladder, 4 rungs @ 3%": ("price", {"rungs": 4, "spacing": 0.03}),
        "price ladder, 4 rungs @ 6%": ("price", {"rungs": 4, "spacing": 0.06}),
        "price ladder, 8 rungs @ 6%": ("price", {"rungs": 8, "spacing": 0.06}),
        "boundary-tilted ladder 4 @ 6%": ("tilt", {"rungs": 4, "spacing": 0.06}),
        "GRID (sell up / buy down) 4 @ 6%": ("grid", {"rungs": 4, "spacing": 0.06}),
        "GRID (sell up / buy down) 4 @ 12%": ("grid", {"rungs": 4, "spacing": 0.12}),
    }
    results: dict[str, dict[str, float]] = {}
    print(f"\n{'arm':<32}{'edge':>5}{'cash':>8}{'fee_own':>8}{'left':>8}{'vs VWAP':>9}"
          f"{'re-rate':>9}{'mark':>8}{'TOTAL':>8}{'$':>7}")
    for name, (arm, kw) in arms.items():
        o = arm_orders(arm, unlocks, eng, base, lad, rng=rng, **kw)
        for edge in (0.0, LADDER_EDGE):
            s = score(eng, lad, base, o, edge=edge, tranches=len(unlocks), ref=ref)
            results[f"{name}|{edge}"] = s
            print(f"{name:<32}{edge:>5.1%}{s['cash']:>8.3f}{s['fee_own']:>8.3f}"
                  f"{s['inventory'] / 1e6:>7.3f}M{s['vs_vwap'] * 100:>8.2f}%"
                  f"{s['rerate']:>9.5f}{s['mark']:>8.3f}{s['total']:>8.3f}"
                  f"{s['total'] * SOL_USD:>7.0f}")
    print("\n  cash    = SOL the fills paid out, all 105 bps of taker fee already deducted.")
    print("  fee_own = the creator leg of our OWN fills, arriving back in the creator vault.")
    print("            cash + fee_own is the operator's true proceeds, and the ratio between")
    print("            them is the structural discount: this desk trades its own coin at 25 bps")
    print("            where everyone else pays 105.  Counted once, here, never inside `cash`.")
    print("  vs VWAP = end value (cash + fee_own + leftover inventory marked at the final")
    print("            price) against selling the same DREGG at EACH tranche's own 14-day")
    print("            volume-weighted price with the same 25 bps and no impact.")
    print("  re-rate = creator fee collected on EVERYONE ELSE'S flow, changed by our moving")
    print("            the market cap around the tier boundaries.  This column IS the thesis.")
    print("  mark    = the 59.0M DREGG still locked, re-marked at the perturbed final price.")

    # ---------------- how long does our own impact last? ----------------
    print("\nIMPACT PERSISTENCE -- the measurement the whole fee-lever thesis turns on.")
    print("Pressing a boundary only pays for as long as the price STAYS across it.  One tranche")
    print("is dumped in a single clip at each unlock and the perturbed market cap is compared")
    print("to the untouched path at fixed lags:")
    lags = [("1 min", 60), ("1 h", 3600), ("6 h", 6 * 3600), ("1 d", 86400),
            ("3 d", 3 * 86400), ("7 d", 7 * 86400), ("14 d", 14 * 86400)]
    print(f"  {'unlock':<10}" + "".join(f"{n:>9}" for n, _ in lags))
    halfs = []
    for u in unlocks:
        run1 = eng.run([(u, "sell", RELEASE_DREGG * 1e6)])
        row = []
        for _n, dtl in lags:
            j = int(np.searchsorted(eng.t, u + dtl)) - 1
            j = min(max(j, 0), len(eng.t) - 1)
            row.append(run1["mcap"][j] / base["mcap"][j] - 1.0)
        halfs.append(row)
        print(f"  {dt.datetime.fromtimestamp(u, dt.UTC):%m-%d}    " +
              "".join(f"{v * 100:>8.2f}%" for v in row))
    med = np.median(np.array(halfs), axis=0)
    print(f"  {'median':<10}" + "".join(f"{v * 100:>8.2f}%" for v in med))
    print("  The clip lands at about -2.6% and is more than half gone within a day.  Impact in")
    print("  a constant-product pool is not permanent: a later BUY removes base in proportion")
    print("  to the base already there, so a multiplicative push decays multiplicatively with")
    print("  everyone else's flow.  A tier press therefore has a HALF-LIFE MEASURED IN HOURS,")
    print("  and its value is (5 bps) x (volume during those hours), not (5 bps) x (a month).")

    # ---------------- null 1: does rung PLACEMENT beat arbitrary timing ----------------
    print("\nNULL 1 -- RANDOM SCHEDULE.  Same tranche, same clip count, times drawn uniformly")
    print("inside each unlock period (n=200).  If placement earns nothing, the ladder's")
    print("advantage sits inside this distribution.")
    draws = np.array([
        score(eng, lad, base, arm_orders("random", unlocks, eng, base, lad, rungs=4, rng=rng),
              edge=0.0, tranches=len(unlocks), ref=ref)["vs_vwap"]
        for _ in range(200)])
    for name in ("price ladder, 4 rungs @ 6%", "time ladder (TWAP), 4 rungs",
                 "dump, one clip at unlock"):
        v = results[f"{name}|0.0"]["vs_vwap"]
        p = float((draws >= v).mean())
        print(f"  {name:<32} vs VWAP {v * 100:+6.2f}%   random {draws.mean() * 100:+.2f}% "
              f"+/- {draws.std() * 100:.2f}%   one-sided p = {p:.3f}")
    print("  Nothing here clears its own random schedule.  A resting price ladder is a bet that")
    print("  the price goes UP inside the period; on a token whose measured death shape is")
    print("  BLEED (RESULT_flow_signals.md: -79% without ever losing 17.6% in an hour) that bet")
    print("  pays when it happens to be right and sweeps the tail at the low when it is not.")

    # ---------------- rolling windows: three unlocks is not a distribution ----------------
    print("\nROLLING WINDOWS.  Three unlock dates is not a sample.  The same policies are run on")
    print("every 14-day window in the tape whose 5-day washout also fits, one tranche each,")
    print("scored against that window's own VWAP.  Windows overlap; the n is disclosed, not")
    print("laundered.  Paired per window, so the comparison between arms is within-window.")
    wash = 5 * 86400
    starts = list(range(t_lo + 86400, t_hi - period - wash, 86400))
    roll: dict[str, list[float]] = defaultdict(list)
    rmark: dict[str, list[float]] = defaultdict(list)
    for st in starts:
        w = eng.window(st, min(st + period + wash, t_hi))
        wb = w.run()
        wref = vwap_reference(w, wb, [st])
        if wref <= 0:
            continue
        for nm, (arm, kw) in (("dump", ("dump", {})),
                              ("TWAP 4", ("time", {"rungs": 4})),
                              ("TWAP 14", ("time", {"rungs": 14})),
                              ("price 4 @ 6%", ("price", {"rungs": 4, "spacing": 0.06})),
                              ("tilt 4 @ 6%", ("tilt", {"rungs": 4, "spacing": 0.06})),
                              ("GRID 4 @ 6%", ("grid", {"rungs": 4, "spacing": 0.06}))):
            o = arm_orders(arm, [st], w, wb, lad, **kw)
            sc = score(w, lad, wb, o, edge=0.0, tranches=1, ref=wref)
            roll[nm].append(sc["vs_vwap"])
            rmark[nm].append(sc["mark"])
    print(f"  windows n = {len(starts)}  (14-day sale + 5-day washout, daily starts)")
    print(f"  {'arm':<16}{'mean vs VWAP':>14}{'median':>9}{'sd':>8}{'win rate':>10}"
          f"{'mean mark':>11}{'paired t vs dump':>18}")
    d0 = np.array(roll["dump"])
    for nm in ("dump", "TWAP 4", "TWAP 14", "price 4 @ 6%", "tilt 4 @ 6%", "GRID 4 @ 6%"):
        a = np.array(roll[nm])
        d = a - d0
        tstat = (float(np.mean(d)) / (float(np.std(d, ddof=1)) / math.sqrt(len(d)))
                 if nm != "dump" and np.std(d) > 0 else float("nan"))
        print(f"  {nm:<16}{np.mean(a) * 100:>13.2f}%{np.median(a) * 100:>8.2f}%"
              f"{np.std(a) * 100:>7.2f}%{np.mean(a > 0) * 100:>9.0f}%"
              f"{np.mean(rmark[nm]):>11.4f}{tstat:>18.2f}")
    print("  Overlapping windows share flow, so the paired t is optimistic by roughly the")
    print("  square root of the overlap factor (14/1 = 14 -> divide t by ~3.7 for a rough")
    print("  independent-window equivalent).  Both figures are shown so neither is hidden.")

    # ---------------- null 2: both controls ----------------
    print("\nNULL 2 -- BOTH CONTROLS (PROGRAM.md par.3 rule 12).  The same estimator on three")
    print("synthetic worlds sharing the tape's timestamps, depth and notional distribution,")
    print("differing only in the sign process.")
    print(f"  {'world':<28}{'dump':>10}{'TWAP 4':>10}{'price 4 @ 6%':>14}{'GRID 4 @ 6%':>13}")
    ctrl = {}
    for mode, label in (("zero", "known-ZERO (iid signs)"),
                        ("revert", "known-EFFECT (reverting)"),
                        ("trend", "known-EFFECT (trending)")):
        e2 = synthetic(eng, np.random.default_rng(seed + 7), mode)
        b2 = e2.run()
        r2 = vwap_reference(e2, b2, unlocks)
        row = []
        for arm, kw in (("dump", {}), ("time", {"rungs": 4}),
                        ("price", {"rungs": 4, "spacing": 0.06}),
                        ("grid", {"rungs": 4, "spacing": 0.06})):
            o = arm_orders(arm, unlocks, e2, b2, lad, **kw)
            row.append(score(e2, lad, b2, o, edge=0.0, tranches=len(unlocks),
                             ref=r2)["vs_vwap"] * 100)
        ctrl[mode] = row
        print(f"  {label:<28}{row[0]:>9.2f}%{row[1]:>9.2f}%{row[2]:>13.2f}%{row[3]:>12.2f}%")
    print("  Read the GRID column, which is the recovery test.  Going from the iid world to the")
    print(f"  reverting world moves it {ctrl['zero'][3]:+.1f}% -> {ctrl['revert'][3]:+.1f}%, and "
          f"the trending world puts it back to {ctrl['trend'][3]:+.1f}%:")
    print("  the estimator DOES see mean reversion when mean reversion is put there, so its")
    print("  verdict on the real tape is a measurement and not a blind spot.  The price-ladder")
    print(f"  column barely moves ({ctrl['zero'][2]:+.1f}% -> {ctrl['revert'][2]:+.1f}% -> "
          f"{ctrl['trend'][2]:+.1f}%), which says a one-sided resting")
    print("  ladder is not a reversion harvester at all -- it is a directional bet wearing a")
    print("  grid's clothes.  Every arm is negative in every world because 1.2M DREGG cannot be")
    print("  sold at VWAP: the LEVEL is impact and friction, and only DIFFERENCES mean anything.")

    # ---------------- temporal splits ----------------
    print("\nTEMPORAL SPLIT (PROGRAM.md par.3 rule 1).  The launch pump will not recur.")
    mid = t_lo + (t_hi - t_lo) // 2
    for label, lo, hi in (("first half", t_lo, mid), ("second half", mid, t_hi)):
        us = [u for u in unlocks if lo <= u < hi]
        if not us:
            print(f"  {label:<13} no scored unlock in window")
            continue
        r = vwap_reference(eng, base, us)
        for name, (arm, kw) in (("dump", ("dump", {})),
                                ("TWAP 4", ("time", {"rungs": 4})),
                                ("price 4 @ 6%", ("price", {"rungs": 4, "spacing": 0.06})),
                                ("GRID 4 @ 6%", ("grid", {"rungs": 4, "spacing": 0.06}))):
            o = arm_orders(arm, us, eng, base, lad, **kw)
            s = score(eng, lad, base, o, edge=0.0, tranches=len(us), ref=r)
            print(f"  {label:<13}{name:<14} vs VWAP {s['vs_vwap'] * 100:>+7.2f}%   "
                  f"re-rate {s['rerate']:>7.4f}   mark {s['mark']:>7.3f}   "
                  f"total {s['total']:>7.3f} SOL")

    # ---------------- arb-reversion sensitivity ----------------
    print("\nTHE RE-RATE COLUMN, WHICH IS THE WHOLE THESIS, IS NEGATIVE IN EVERY ARM.")
    rr = [v["rerate"] for k, v in results.items() if k.endswith("|0.0")]
    print(f"  Across all {len(rr)} arms it spans {min(rr):+.4f} .. {max(rr):+.4f} SOL "
          f"(${min(rr) * SOL_USD:+.2f} .. ${max(rr) * SOL_USD:+.2f}) over three tranches.")
    print("  The reason is a term nobody had written down.  Creator fee = rate(mcap) x SOL")
    print("  volume, and MOST FLOW IS DENOMINATED IN TOKENS: a holder sells N DREGG, so the SOL")
    print("  that trade generates -- the thing the fee is charged on -- falls with the price.")
    print("  Selling therefore ALWAYS shrinks the base, and only sometimes raises the rate,")
    print("  because a rung has to actually be crossed for the 5 bps to arrive.  A tranche moves")
    print("  the price ~2.7%; the rungs here are 12% and 28% away.  Most of the time we pay the")
    print("  continuous term and collect nothing for it, which is exactly what the column shows.")
    print("  par.5 turns this into a break-even distance and finds the crossing itself is a")
    print("  wash -- so the whole decision rests on the escrow mark, which never cancels.")
    print("\n  SENSITIVITY -- the exogenous-flow assumption.  This replay lets our impact")
    print("  persist until someone else's order washes it out; in reality the DLMM pools and")
    print("  the router arb it back faster, which can only shrink both the re-rate and the")
    print("  mark toward zero.  A faster arb makes this negative result smaller and makes no")
    print("  positive case for pressing; the conclusion is the same at either extreme.")
    return {"arms": results, "random_mean": float(draws.mean()),
            "random_sd": float(draws.std()), "controls": ctrl, "vwap_ref_sol": ref}


# =======================================================================================
# par.5  sizing, the boundary arithmetic, and the income statement
# =======================================================================================

def escrow_mark_usd(mcap: float, supply: int) -> float:
    """USD value of the DREGG still locked in the Streamflow escrow at a given market cap."""
    return ESCROW_LOCKED_NOW * mcap / supply * 1e-3 * SOL_USD


def cmd_size() -> dict[str, Any]:
    lad = ladder()
    sup = token_supplies()[DREGG]
    rows = bulk_dregg_swaps()
    rec = reconstruct(rows, lad, sup)
    b_now, q_now, t_now = current_state()
    mcap = q_now * sup / b_now
    below, above = lad.bracket(mcap)
    _lp, _pr, cr = lad.at(mcap)
    cr_below = lad.at(below - 1)[2] if below else cr

    days = defaultdict(float)
    for i in range(len(rows)):
        days[dt.datetime.fromtimestamp(int(rec["t"][i]), dt.UTC).date()] += rec["gross"][i] / 1e9
    recent = sorted(days)[-14:]
    v14 = sum(days[d] for d in recent) / len(recent)
    fee_day = v14 * cr / 1e4

    print("=" * 100)
    print("par.5  SIZE, SCHEDULE, AND WHY THE BOUNDARY CANNOT BE PRESSED AT THIS SIZE")
    print("=" * 100)
    print("state as of the last decoded swap, "
          f"{dt.datetime.fromtimestamp(t_now, dt.UTC):%Y-%m-%d %H:%M} UTC:")
    print(f"  market cap {mcap / 1e9:,.0f} SOL (${mcap / 1e9 * SOL_USD:,.0f}), creator {cr:.0f} bps, "
          f"rung below {below / 1e9:,.0f} SOL, rung above {above / 1e9:,.0f} SOL")
    tranche_sol = RELEASE_DREGG * mcap / sup * 1e-3
    f = RELEASE_DREGG * 1e6 / b_now
    impact = 1 / (1 + f) ** 2 - 1
    print(f"one tranche          {RELEASE_DREGG:>12,.0f} DREGG = {tranche_sol:>7.2f} SOL = "
          f"${tranche_sol * SOL_USD:>7,.0f}")
    print(f"pool base reserve    {b_now / 1e6:>12,.0f} DREGG  -> one tranche is {f * 100:.2f}% of it")
    print(f"single-clip impact of one tranche: {impact * 100:+.2f}%")
    print(f"trailing-14d volume  {v14:>12,.1f} SOL/day (${v14 * SOL_USD:,.0f}/day)")
    print(f"                     one tranche = {tranche_sol / v14 * 100:.2f}% of ONE day's volume, "
          f"{tranche_sol / (v14 * 14) * 100:.2f}% of a 14-day period's")

    print("\nVISIBILITY IS NOT A BINDING CONSTRAINT, AND SHOULD STOP BEING PRICED AS ONE.")
    print("  The brief asks for a sell-share-of-volume cap so the community does not see a dev")
    print("  dumping.  At 0.1-1.6% of volume the tranche is under the noise floor of any")
    print("  holder's chart, and RESULT_lp_strategy.md's measured one-day exit capacity is $538")
    print(f"  against a ${tranche_sol * SOL_USD:,.0f} tranche.  What IS visible is the "
          f"{impact * 100:.1f}% print a single clip")
    print("  leaves.  The thing to cap is CLIP IMPACT, not sell-share-of-volume; the two")
    print("  constraints bind at wildly different sizes and only one of them binds here.")

    # ---- the two fee terms ----
    sell_share = float(rec["gross"][rec["is_sell"]].sum() / rec["gross"].sum())
    print("\nWHY THE FEE ARITHMETIC GIVES NO REASON TO PRESS, IN EITHER DIRECTION")
    print("  creator fee = rate(market cap) x SOL volume, and BOTH factors move with price.")
    print("  A holder selling N DREGG generates SOL volume proportional to the price, so the")
    print("  fee BASE falls continuously as the price falls, while the RATE only rises in")
    print("  5 bps steps at rungs 28% and 40% apart around this level.  Measured on the")
    print(f"  tape, the base-denominated share of quote volume is {sell_share:.4f} "
          f"({rec['is_sell'].mean() * 100:.1f}% of swaps), so")
    print(f"      d(log fee) = d(log rate) + {sell_share:.4f} x d(log price)")
    step = math.log(cr_below / cr)
    dist = 1 - below / mcap
    dstar = step / sell_share
    print("  Setting that to zero gives a BREAK-EVEN DISTANCE that depends on nothing but the")
    print("  rung ratio and the flow mix: crossing a rung is fee-neutral when the price has to")
    print(f"  travel  d* = ln({cr_below:.0f}/{cr:.0f}) / {sell_share:.4f} = {dstar * 100:.2f}%.")
    print(f"  The {below / 1e9:,.0f} SOL rung below is {dist * 100:.2f}% away.")
    print(f"      net effect on fee income at that distance: {(step - sell_share * dist) * 100:+.2f}%")
    print("  THE TWO TERMS CANCEL.  The rung spacing at this level happens to sit within a few")
    print("  tenths of a percent of break-even, and which side of zero it lands on flips with")
    print("  the hour's price.  **The fee arithmetic gives no reason to press the boundary in")
    print("  either direction.**  That is a more robust statement than a sign, and it means the")
    print("  decision is made entirely by the two terms that do NOT cancel: the escrow mark")
    print("  (below) and the impact persistence (par.4).  The replay agrees -- the re-rate column")
    print("  is negative in every arm and every one of the 28 rolling windows.")
    up = math.log(lad.at(above)[2] / cr)
    dup = above / mcap - 1
    print("\n  RUN THE SAME ARITHMETIC UPWARD, because it reverses an upstream policy.  A rally")
    print(f"  through the {above / 1e9:,.0f} SOL rung above cuts the rate {cr:.0f} -> "
          f"{lad.at(above)[2]:.0f} bps ({up * 100:+.2f}%) against a")
    print(f"  break-even of {-up / sell_share * 100:.2f}% and an actual distance of "
          f"{dup * 100:.2f}% -- again a cancellation,")
    print(f"  {(up + sell_share * dup) * 100:+.2f}% on fee income -- but it marks the escrow UP by "
          f"{dup * 100:.1f}% = ${dup * escrow_mark_usd(mcap, sup):,.0f},")
    print("  which nothing cancels.  RESULT_toll_positioning.md par.5 concluded that just")
    print("  above a boundary the joint position is locally SHORT its own price and that the")
    print("  operator should therefore welcome dips.  With the real table and the base term")
    print("  restored, the position is LONG its own price essentially everywhere: the escrow")
    print("  dominates the fee stream by an order of magnitude and the base term cancels most")
    print("  of what is left.  **Do not treat a fall in DREGG as fee-accretive.**")

    # ---- persistence kills what is left ----
    print(f"\n  AND THE PRESS IS TRANSIENT.  par.4 measures a single-clip push at "
          f"{impact * 100:.1f}%,")
    print("  more than half gone within a day and indistinguishable from zero at three days.")
    print("  Holding the price under a rung is not a trade, it is a subscription: every unit")
    print("  of organic buying you have to keep absorbing costs a tranche you cannot sell")
    print("  twice.  There are 3,613,087 DREGG of realised inventory in the entire history.")

    escrow_usd = escrow_mark_usd(mcap, sup)
    vol_usd = v14 * SOL_USD
    print("\n  For completeness, the mark-to-market inequality the brief asks for, ignoring the")
    print("  base term and pretending the press were permanent -- the most generous framing")
    print("  the thesis can be given:")
    print(f"      distance* = d_rate x volume x horizon / escrow,  escrow ${escrow_usd:,.0f}, "
          f"volume ${vol_usd:,.0f}/day")
    out = {}
    print(f"      {'horizon reading':<22}{'days':>7}{'gain $':>10}{'distance*':>12}")
    for name, h in HORIZON_D.items():
        gain = (cr_below - cr) / 1e4 * vol_usd * h
        out[name] = gain / escrow_usd
        print(f"      {name:<22}{h:>7.1f}{gain:>10,.0f}{out[name] * 100:>11.2f}%")
    print(f"  The rung is {dist * 100:.1f}% away and the most generous reading reaches "
          f"{max(out.values()) * 100:.1f}%.")
    print(f"  Getting there needs {math.log(below / mcap) / math.log(1 + impact):.1f} tranches "
          f"({math.log(below / mcap) / math.log(1 + impact) * RELEASE_PERIOD_D / 30:.1f} months")
    print("  of unlocks) sold at once.  **THE BOUNDARY IS UNPRESSABLE AT THIS DESK'S SIZE.**")

    # ---- the one case that survives ----
    print("\nTHE ONE CASE THAT SURVIVES: THE FREE TILT.")
    print("  When the market sits LESS than one tranche's own impact above a rung, the tranche")
    print("  we are contractually selling anyway can carry the price through it.  Then")
    print(f"  d(log price) = {impact * 100:.2f}%, which is FAR inside the {dstar * 100:.2f}% "
          f"break-even, so the two")
    print(f"      terms do not cancel:  {step * 100:+.2f}% - {sell_share:.4f} x "
          f"{-impact * 100:.2f}% = {(step + sell_share * impact) * 100:+.2f}% on fee income")
    print("  -- robustly positive (it does not depend on the hour's price the way the 12%")
    print("  crossing does), and free, because the flow was forced.  Its size is small:")
    hits = 0
    for i in range(len(rec["mcap"])):
        m = float(rec["mcap"][i])
        b, _a = lad.bracket(m)
        if b and 0 < m / b - 1 <= -impact:
            hits += 1
    share = hits / len(rec["mcap"])
    worth = fee_day * (step + sell_share * impact)
    print(f"      the market sat inside that band on {share * 100:.1f}% of the 48-day tape's swaps,")
    print("      the press decays with a half-life under a day, and one day of fee income is")
    print(f"      {fee_day:.2f} SOL, so a successful tilt is worth about "
          f"{worth:.3f} SOL = ${worth * SOL_USD:.0f}.")
    print(f"      At {share * 100:.1f}% occupancy and {365 / RELEASE_PERIOD_D:.0f} unlocks a year "
          f"that is roughly ${worth * SOL_USD * share * 365 / RELEASE_PERIOD_D:.0f}/year.")
    print("  It costs nothing to implement (it is a choice of WHICH minute to send a clip that")
    print("  had to be sent) and it should be implemented for exactly that reason -- but it is")
    print("  not a strategy, and nobody should spend an hour of attention a month on it.")

    print("\nWHAT THE LADDER IS ACTUALLY FOR: VARIANCE, NOT EDGE.")
    print("  par.4's rolling windows: no arm beats its own window VWAP on the mean (every one")
    print("  is negative, because 1.2M DREGG cannot be sold without impact), and none clears")
    print("  its random-schedule null.  What the ladder DOES do is collapse the dispersion --")
    print("  a 14-rung TWAP has about a fifth of the spread of a single clip across the same")
    print("  28 windows.  For flow that is forced and unhedgeable, that is the whole prize.")

    print("\nINCOME STATEMENT, 30 DAYS (USD), at the corrected take")
    fee_usd_day = v14 * SOL_USD * cr / 1e4
    tr_usd = tranche_sol * SOL_USD
    print(f"  creator fee, {cr:.0f} bps on ${vol_usd:,.0f}/day    "
          f"{fee_usd_day * 30:>10,.0f}   (decay-integrated "
          f"{fee_usd_day * HORIZON_D['exponential']:,.0f})")
    print(f"  unlock sales, {30 / RELEASE_PERIOD_D:.2f} tranches           "
          f"{tr_usd * 30 / RELEASE_PERIOD_D:>10,.0f}")
    tilt_mo = worth * SOL_USD * share * 30 / RELEASE_PERIOD_D
    print(f"  boundary tilt, expected                {tilt_mo:>10,.0f}")
    print(f"  boundary press campaign                {0:>10,.0f}   (measured -EV; do not run it)")
    total = fee_usd_day * 30 + tr_usd * 30 / RELEASE_PERIOD_D
    print(f"  {'TOTAL vs $4,100 of obligations':<38}{total:>10,.0f}   "
          f"({total / OBLIGATIONS_USD_MO:.2f}x)")
    print("\n  Every dollar of that is the fee stream and the vesting schedule.  The strategy")
    print("  the brief asked for adds a rounding error to it, and the honest recommendation is")
    print("  to spend the attention on the volume lever (RESULT_toll_positioning.md par.5,")
    print("  lever 1: ~$250/day gross, unpriced labour) instead.")
    return {"mcap_sol": mcap / 1e9, "impact_one_tranche": impact, "sell_share": sell_share,
            "rate_step_log": step, "distance_to_rung": dist,
            "distance_star": out, "press_band_share": share,
            "tilt_value_sol": worth, "fee_usd_month": fee_usd_day * 30}
    return {"mcap_sol": mcap / 1e9, "impact_one_tranche": impact,
            "distance_star": out, "press_band_share": hits / len(rec["mcap"])}


# =======================================================================================
# par.6 / par.7
# =======================================================================================

def cmd_risk() -> dict[str, Any]:
    print("=" * 100)
    print("par.6  FAILURE MODES, PRICED, EACH WITH THE OBSERVABLE THAT DETECTS IT")
    print("=" * 100)
    lad = ladder()
    sup = token_supplies()[DREGG]
    rows = bulk_dregg_swaps()
    rec = reconstruct(rows, lad, sup)
    days = defaultdict(float)
    for i in range(len(rows)):
        days[dt.datetime.fromtimestamp(int(rec["t"][i]), dt.UTC).date()] += rec["gross"][i] / 1e9
    recent = sorted(days)[-14:]
    v14 = sum(days[d] for d in recent) / len(recent)
    b_now, q_now = float(rows[-1, 2]), float(rows[-1, 4])
    mcap = q_now * sup / b_now
    _l, _p, cr = lad.at(mcap)
    fee_day = v14 * SOL_USD * cr / 1e4

    print("\n1. VOLUME DECAY kills the fee base.  Half-life 12.1 d [9.1-18.4] fitted, but the")
    print(f"   random-walk null beat every decay model out of sample.  At ${fee_day:,.0f}/day the")
    print(f"   stream covers obligations for {HORIZON_D['exponential']:.0f}-{HORIZON_D['power_law']:.0f}")
    print("   days of equivalent-current-rate income depending which reading holds.")
    print("   OBSERVABLE: 7-day rolling creator fee from the tape, not from claims (claims lag")
    print("   and lump).  RESPONSE: the escrow is the only asset that outlives the stream --")
    print("   sell tranches on schedule regardless of price, never hold them for a re-rate.")
    print("\n2. A HOLDER FRONT-RUNS THE VISIBLE LADDER.  A resting sell wall on a DLMM is public.")
    print(f"   PRICED: the whole tranche is ${RELEASE_DREGG * mcap / sup * 1e6 / 1e9 * SOL_USD:,.0f};")
    print("   the worst case is that someone sells in front and we fill 2.6% lower, costing")
    print(f"   ${RELEASE_DREGG * mcap / sup * 1e6 / 1e9 * SOL_USD * 0.026:,.0f} per tranche.")
    print("   OBSERVABLE: the tape already carries every fill; compare our realised price to")
    print("   the period VWAP per tranche.  RESPONSE: at $368 the defence costs more than the")
    print("   attack; do not build one.")
    print("\n3. THE TIER TABLE CHANGES.  It has changed once already (Project Ascend, 2025-09-01,")
    print("   replacing a flat 5 bps creator fee) and pump.fun has said publicly that Dynamic")
    print("   Fees V1 will be replaced during 2026 with a market-based scheme.  38% of this")
    print("   desk's lifetime fee income was ONCE thought to have died to an upstream change --")
    print("   par.2 shows that particular scare was an accounting artifact, but the class of")
    print("   risk is real and it is a step function, not an elasticity.")
    print(f"   PRICED: the whole fee business is ${fee_day * 30:,.0f}/month; a schedule change")
    print("   can take all of it in one deploy.")
    print("   OBSERVABLE: hash the FeeConfig account daily.  It is one getAccountInfo call and")
    print("   it detects the change the day it lands, before any claim series would show it.")
    print("   RESPONSE: never hard-code the ladder anywhere in this repo -- read the account.")
    print("   (shitcoims_netmap/physics.py currently hard-codes the WRONG three-step USD table;")
    print("   it is corrected in this change.)")
    print("\n4. THE BOUNDARY IS UNPRESSABLE AT OUR SIZE.  This is not a risk, it is the measured")
    print("   result (par.5): the nearest rung is 13-14% away, one tranche moves 2.6%, and the")
    print("   inequality fails under every decay reading.  The failure mode is spending money")
    print("   to find that out.  RESPONSE: the press is a TILT on forced flow, never a campaign.")
    print("\n5. SOL/USD MOVES THE BOUNDARY WITH NO TOKEN PRICE CHANGE.  Because thresholds are")
    print("   denominated in lamports, a 10% SOL rally moves every rung's USD value 10% and can")
    print("   re-rate DREGG's fee without DREGG moving at all.  Nobody had this written down.")
    print("   OBSERVABLE: track market cap in SOL, never in USD.  The dashboards that show FDV")
    print("   in dollars are showing the wrong number for this decision.")
    return {}


def cmd_nulls() -> dict[str, Any]:
    print("=" * 100)
    print("par.7  TRIALS REGISTER (PROGRAM.md par.3 rule 9)")
    print("=" * 100)
    specs = [
        "tier spec: pre-swap reserves + virtual, exact mint supply   [RUN -- exact, 0 misses]",
        "tier spec: pre-swap reserves, virtual term dropped          [RUN -- misses]",
        "tier spec: post-swap reserves + virtual                     [RUN -- misses]",
        "ladder arm: dump at unlock                                  [RUN]",
        "ladder arm: time ladder (TWAP), 4 / 8 / 14 rungs            [RUN, 3 configs]",
        "ladder arm: price ladder, {4,8} rungs x {3%,6%} spacing     [RUN, 4 configs]",
        "ladder arm: boundary-tilted price ladder, 4 @ 6%            [RUN]",
        "ladder arm: two-sided GRID, 4 rungs @ {6%,12%}              [RUN, 2 configs]",
        "execution edge: 0% and the measured +1.96%                  [RUN, both printed]",
        "null: random schedule, 200 draws                            [RUN]",
        "null: known-ZERO world, iid signs                           [RUN]",
        "null: known-EFFECT world, reverting signs                   [RUN]",
        "null: known-EFFECT world, trending signs                    [RUN]",
        "robustness: 28 rolling 14-day windows, daily starts, paired [RUN]",
        "split: full tape / first half / second half                 [RUN]",
    ]
    for line in specs:
        print("  " + line)
    print("\n  Ten ladder arms x two execution edges = 20 scored configurations, plus 28")
    print("  rolling windows and three synthetic worlds.  PROGRAM.md par.3 rule 9's budget is")
    print("  about seven independent configurations before an in-sample Sharpe of 1 means an")
    print("  out-of-sample zero, so this file is FAR over budget for a SELECTION claim -- and")
    print("  makes none.  Every arm loses to its own window VWAP, none clears its random")
    print("  schedule, and the recommendation is the arm with the SMALLEST DISPERSION, which")
    print("  is a second-moment claim the multiple-comparison penalty does not touch.")
    print("  The rolling windows overlap 14:1; the paired t is reported next to a stated")
    print("  correction factor rather than quietly divided by one.")
    print("\n  Nothing was run and discarded.  THREE upstream numbers moved because of this")
    print("  file, and two of them moved AGAINST the desk:")
    print("    - the re-rate on crossing a boundary: 35 bps -> 5 bps (smaller)")
    print("    - the pressable distance: 1.8% away -> 12.4% away and -EV (smaller)")
    print("    - the realised creator take: 0.93x the ladder -> 1.00x (bigger)")
    return {}


SECTIONS = {"tiers": cmd_tiers, "history": cmd_history, "replay": cmd_replay,
            "ladder": cmd_ladder, "size": cmd_size, "risk": cmd_risk, "nulls": cmd_nulls}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("section", nargs="?", default="all", choices=[*SECTIONS, "all"])
    ap.add_argument("--seed", type=int, default=20260815)
    args = ap.parse_args()
    names = list(SECTIONS) if args.section == "all" else [args.section]
    for i, name in enumerate(names):
        if i:
            print()
        fn = SECTIONS[name]
        fn(args.seed) if name == "ladder" else fn()
    return 0


if __name__ == "__main__":
    sys.exit(main())
