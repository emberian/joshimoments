"""AMM cluster as an electrical circuit: measurement instrument.

Companion to studies/RESULT_circuit_model.md.  Everything printed by this file is
measured from a public keyless API (DexScreener, GeckoTerminal).  No number in the
write-up is allowed to exist unless this file (or an explicitly-labelled hand
calculation in the write-up) produced it.

The physics, stated once so the code reads as an implementation of it:

    node        token          potential  V_i = ln(price of token i in a numeraire)
    edge        pool           measures   V_base - V_quote = ln(p)
    KVL         no-arbitrage   sum of ln(p) around any cycle = 0
    curl        cycle residual C = sum_legs ln(p_leg), oriented consistently
    fee band    |C| <= sum_legs ln(1/(1-f_leg))       (derived in the write-up)

A cycle whose curl sits outside its fee band is a standing EMF: a loop trade that
returns more than it consumes at infinitesimal size.  Inside the band it is a
no-trade region, exactly like a diode dead-zone.

Modes
-----
  discover      re-resolve every pool touching the cluster mints; print the graph
  snapshot      one curl measurement across every cycle, both bands, the fee sweep
  poll          repeated snapshots -> JSONL  (--minutes, --interval)
  analyze       curl distribution, excursion relaxation, quote-staleness, from a JSONL
  crosscheck    DexScreener vs GeckoTerminal on the same pools: the instrument's noise floor
  rc            capacitance from depth; the parameter-free t_half ~ C check; implied 1/R
  ledger        the energy ledger of one swap, verified against (1/2)C(dV)^2 per pool
  dissipation   fee-yield audit: token-token pools vs token/SOL pools
  all           every one of the above, in order, off a single pool discovery

Usage
-----
  python studies/circuit_model.py all
  python studies/circuit_model.py poll --minutes 20 --interval 20 --out /tmp/curl.jsonl
  python studies/circuit_model.py analyze --in /tmp/curl.jsonl
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------------------
# universe
# --------------------------------------------------------------------------------------

# Mints as recorded in studies/RESULT_swing_cluster.md.  NOTE: the scratchpad script that
# produced that study had the weave/SOLVE labels transposed; the *table* in the study is
# correct and is what these labels follow.  Verified 2026-08-13 against the symbols
# DexScreener returns for each mint (see `discover`).
MINTS: dict[str, str] = {
    "weave": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
    "nosis": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
    "DREGG": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
    "SOLVE": "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
}
SOL = "So11111111111111111111111111111111111111112"

USER_AGENT = {"User-Agent": "joshibot-research/0.1 (studies/circuit_model.py)"}

# --------------------------------------------------------------------------------------
# fee schedule -- every entry carries its provenance, because the fee band IS the result
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FeeSpec:
    """Total round-trip-relevant swap fee charged on ONE leg, as a fraction of input.

    `taker` is what a cycle-arb actually pays per leg.  It is the sum of every component
    skimmed from the swap: LP fee + protocol fee + creator fee.  Only the LP component
    accrues to a liquidity provider; `lp_share` records that split for the dissipation
    audit, where the two are different questions.
    """

    taker: float
    lp_share: float  # fraction of `taker` that reaches the LP
    source: str
    uncertain: bool = False


# PumpSwap.  Two legs, two provenances:
#   LP + protocol = 0.20% + 0.05% = 0.25%.  Sourced 2026-08-13 from pump.fun's own public
#     docs repo (github.com/pump-fun/pump-public-docs, PUMP_SWAP_CREATOR_FEE_README) as
#     relayed by search; NOT read from chain here, so treat as a strong lead and sweep it.
#   creator = the dynamic FDV ladder in PROGRAM.md sec.0, itself double-sourced (operator
#     fee stream + Marino sec.VII on-chain observation): 0.95% under $300k FDV, 0.60% to
#     $1M, 0.35% above.  `dissipation` cross-checks this against the operator's own
#     reported DREGG creator income, which is an independent estimator of the same rate.
PUMPSWAP_LP_PROTOCOL = 0.0025  # 0.20% LP + 0.05% protocol. swept in `snapshot`.


def pumpswap_fee(fdv_usd: float) -> FeeSpec:
    if fdv_usd < 300_000:
        creator = 0.0095
    elif fdv_usd < 1_000_000:
        creator = 0.0060
    else:
        creator = 0.0035
    taker = PUMPSWAP_LP_PROTOCOL + creator
    return FeeSpec(
        taker=taker,
        lp_share=PUMPSWAP_LP_PROTOCOL / taker if taker else 0.0,
        source=(
            f"creator leg {creator:.2%} from PROGRAM.md sec.0 FDV ladder (FDV=${fdv_usd:,.0f}); "
            f"LP+protocol leg {PUMPSWAP_LP_PROTOCOL:.2%} UNSOURCED, swept"
        ),
        uncertain=True,
    )


# Meteora DLMM: base fee = bin_step * base_factor, plus a volatility-dependent dynamic fee.
# Neither is exposed by DexScreener or GeckoTerminal, and the dlmm-api pair endpoint 404s
# for these pools.  Carried as UNCERTAIN with a sweep.  The value below is the midpoint of
# the range the sweep covers, not a measurement.
DLMM_FEE_ASSUMED = 0.0100  # <-- UNCERTAIN. swept.
DLMM_SWEEP = (0.0020, 0.0050, 0.0100, 0.0200, 0.0500)
PUMPSWAP_SWEEP = (0.0005, 0.0020, 0.0030, 0.0050, 0.0100)


def dlmm_fee(rate: float = DLMM_FEE_ASSUMED) -> FeeSpec:
    return FeeSpec(
        taker=rate,
        lp_share=1.0,  # DLMM LP takes the base fee; protocol share not modelled
        source=f"DLMM base+dynamic fee {rate:.2%} UNSOURCED (no keyless endpoint), swept",
        uncertain=True,
    )


# --------------------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------------------


def _get(url: str, timeout: int = 25) -> Any:
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _get_retry(url: str, tries: int = 3, timeout: int = 25) -> Any | None:
    for k in range(tries):
        try:
            return _get(url, timeout=timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
            if k == tries - 1:
                return None
            time.sleep(1.0 + k)
    return None


# --------------------------------------------------------------------------------------
# pool model
# --------------------------------------------------------------------------------------


@dataclass
class Pool:
    addr: str
    dex: str
    labels: tuple[str, ...]
    base: str  # symbol
    quote: str  # symbol
    base_mint: str
    quote_mint: str
    price_native: float  # last-trade price of base in quote units
    price_usd: float
    liq_usd: float
    liq_base: float  # reserve, base units
    liq_quote: float  # reserve, quote units
    vol24: float
    txns24: int
    fdv: float
    created_at_ms: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def kind(self) -> str:
        """`cpmm` = constant product (marginal price recoverable from reserves).
        `dlmm` = discrete bins (marginal price is the ACTIVE BIN, not the reserve ratio).
        """
        if self.dex == "pumpswap":
            return "cpmm"
        if "DLMM" in self.labels:
            return "dlmm"
        return "other"

    @property
    def pair(self) -> tuple[str, str]:
        return (self.base, self.quote)

    def price_from_reserves(self) -> float | None:
        """Reserve-ratio price.  MEASURED TO BE BIASED IN LEVEL -- see the note below.

        Theory: for x*y=k the marginal price of base in quote units is exactly y/x.  For a
        DLMM the quantity is meaningless -- liquidity sits in discrete bins and the marginal
        price is the ACTIVE BIN's price, not a function of aggregate reserves.  Returning
        None for DLMM is the honest answer, not a missing feature.

        Measurement (2026-08-13, 15 samples at 20s, `analyze` reproduces it): on PumpSwap
        pools this ratio moves in lockstep with the last-trade price -- corr(dlog) = +0.99
        to +1.00 at lag 0, and no lead-lag at +-1 sample -- but sits at a PERSISTENT
        multiplicative offset from it that is stable to within a few bps over minutes:

            weave/SOL  -957 bps (sd 13)    nosis/SOL  -473 bps (sd 49)
            DREGG/SOL  +100 bps (sd  0)    SOLVE/SOL   -19 bps (sd  0)

        The offset magnitude orders with the pool's cumulative turnover, which is what
        unclaimed fee balances sitting in the pool token accounts would look like.  Whatever
        the mechanism, the consequence is sharp and it decides how this field may be used:

            LEVELS  are unusable -- the bias is up to 9.6%, an order of magnitude wider
                    than any fee band, so a curl built from reserve ratios is measuring
                    DexScreener's accounting, not the market's.
            CHANGES are clean -- a constant multiplicative bias cancels exactly in first
                    differences, so d log(price) from this field is usable, and that is
                    the input the Onsager estimator of sec. 7 actually needs.
        """
        if self.kind != "cpmm" or self.liq_base <= 0 or self.liq_quote <= 0:
            return None
        return self.liq_quote / self.liq_base

    def fee(self) -> FeeSpec:
        if self.kind == "cpmm":
            return pumpswap_fee(self.fdv)
        return dlmm_fee()


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _parse_pair(p: dict) -> Pool | None:
    try:
        liq = p.get("liquidity") or {}
        vol = p.get("volume") or {}
        tx = (p.get("txns") or {}).get("h24") or {}
        return Pool(
            addr=p["pairAddress"],
            dex=p.get("dexId", "?"),
            labels=tuple(p.get("labels") or ()),
            base=p["baseToken"]["symbol"],
            quote=p["quoteToken"]["symbol"],
            base_mint=p["baseToken"]["address"],
            quote_mint=p["quoteToken"]["address"],
            price_native=_f(p.get("priceNative")),
            price_usd=_f(p.get("priceUsd")),
            liq_usd=_f(liq.get("usd")),
            liq_base=_f(liq.get("base")),
            liq_quote=_f(liq.get("quote")),
            vol24=_f(vol.get("h24")),
            txns24=int(_f(tx.get("buys")) + _f(tx.get("sells"))),
            fdv=_f(p.get("fdv")),
            created_at_ms=int(_f(p.get("pairCreatedAt"))),
        )
    except (KeyError, TypeError):
        return None


def fetch_by_token(mint: str) -> list[Pool]:
    d = _get_retry(f"https://api.dexscreener.com/latest/dex/tokens/{mint}")
    if not d:
        return []
    return [q for q in (_parse_pair(p) for p in (d.get("pairs") or [])) if q]


def fetch_by_addresses(addrs: list[str]) -> list[Pool]:
    """Batch pool fetch.  DexScreener takes up to 30 comma-separated addresses."""
    out: list[Pool] = []
    for i in range(0, len(addrs), 25):
        chunk = addrs[i : i + 25]
        d = _get_retry("https://api.dexscreener.com/latest/dex/pairs/solana/" + ",".join(chunk))
        if not d:
            continue
        out += [q for q in (_parse_pair(p) for p in (d.get("pairs") or [])) if q]
    return out


# --------------------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------------------

MIN_LIQ_USD = 100.0  # below this a pool's quoted price is a fossil, not a market


def discover(min_liq: float = MIN_LIQ_USD, verbose: bool = True) -> list[Pool]:
    seen: dict[str, Pool] = {}
    for name, mint in MINTS.items():
        pools = fetch_by_token(mint)
        if verbose:
            print(f"  {name:<6} {mint[:8]}...  {len(pools)} pools")
        for p in pools:
            seen[p.addr] = p
        time.sleep(0.35)
    keep = sorted(seen.values(), key=lambda p: -p.liq_usd)
    if verbose:
        print(f"\n{'dex':<10} {'lbl':<6} {'pair':<16} {'liq $':>11} {'vol24 $':>11} {'tx24':>6}  addr")
        for p in keep:
            mark = " " if p.liq_usd >= min_liq else "x"
            print(
                f"{mark}{p.dex:<9} {(p.labels[0] if p.labels else '-'):<6} "
                f"{p.base + '/' + p.quote:<16} {p.liq_usd:>11,.0f} {p.vol24:>11,.0f} "
                f"{p.txns24:>6}  {p.addr}"
            )
        print("  (x = below the liquidity floor; price is a fossil, excluded from cycles)")
    return keep


# --------------------------------------------------------------------------------------
# the graph, cycles, and the curl
# --------------------------------------------------------------------------------------


@dataclass
class Cycle:
    nodes: tuple[str, ...]  # e.g. ("DREGG", "nosis", "SOL")
    legs: tuple[tuple[Pool, int], ...]  # (pool, orientation) with +1 = base->quote as written

    @property
    def name(self) -> str:
        return " -> ".join((*self.nodes, self.nodes[0]))

    @property
    def venues(self) -> str:
        return "+".join(f"{p.dex[:4]}:{p.addr[:4]}" for p, _ in self.legs)

    def fee_band(self, overrides: dict[str, float] | None = None) -> float:
        """Half-width of the no-trade band, in LOG price units.

        Derivation (write-up sec. 3): a cycle-arb of infinitesimal notional receives
        exp(C) per unit sent around the loop and pays (1 - f) on each leg, so it profits
        iff  exp(C) * prod(1 - f_leg) > 1, i.e.  C > sum ln(1/(1-f_leg)).  The band edges
        ARE the fee sum.  Gas is size-dependent and enters separately.
        """
        total = 0.0
        for pool, _ in self.legs:
            f = (overrides or {}).get(pool.kind, pool.fee().taker)
            total += math.log(1.0 / (1.0 - f))
        return total

    def sum_r(self, dlmm_span: float = 4.0) -> float:
        """Sum of leg resistances, r_e = 1/C_e, in log-price per unit of value pushed.

        r_e = 4/TVL for constant product (C = TVL/4, derived in the write-up sec. 2.1).
        For a DLMM, C = TVL / W where W is the log-price width the LP's liquidity spans, so
        r = W/TVL.  W is NOT observable from any keyless endpoint, so `dlmm_span` is the
        knob: dlmm_span = 4.0 reproduces the constant-product value (the pessimistic, no
        concentration bound), and a realistic concentrated position is 0.2 to 0.8.
        """
        tot = 0.0
        for pool, _ in self.legs:
            if pool.liq_usd <= 0:
                return float("inf")
            span = 4.0 if pool.kind == "cpmm" else dlmm_span
            tot += span / pool.liq_usd
        return tot

    def full_band(self, gas_usd: float, dlmm_span: float = 4.0) -> tuple[float, float, float]:
        """The band an arb actually faces, and the trade that clears it.

        Pushing notional X around the loop earns X*(C - sum f) at first order but moves every
        leg against itself, costing (1/2) X^2 * sum r_e (that is the (1/2)CV^2 term of the
        ledger, summed over legs), and pays a fixed gas G:

            profit(X) = X*(C - sum f) - (1/2) X^2 * sum r_e - G

        Maximising:  X* = (C - sum f)/sum r_e,  profit* = (C - sum f)^2 / (2 sum r_e) - G.
        Profit* > 0 iff

            |C|  >  sum f_e  +  sqrt( 2 * G * sum r_e )                              (*)

        So the band is the fee sum PLUS a gas-and-depth term.  The fee term alone is the
        zero-size, zero-gas limit; (*) is the band that decides whether money changes hands.
        Returns (band_total, gas_depth_term, X_star_at_that_band).
        """
        fee = self.fee_band()
        sr = self.sum_r(dlmm_span)
        extra = math.sqrt(2.0 * gas_usd * sr) if math.isfinite(sr) else float("inf")
        return fee + extra, extra, (extra / sr if sr else float("inf"))

    def arb_profit(self, curl_val: float, gas_usd: float, dlmm_span: float = 4.0) -> tuple[float, float]:
        """(optimal notional, profit in USD) for a given curl.  Negative profit = no trade."""
        sr = self.sum_r(dlmm_span)
        edge = abs(curl_val) - self.fee_band()
        if edge <= 0 or not math.isfinite(sr) or sr <= 0:
            return 0.0, -gas_usd
        x = edge / sr
        return x, edge * edge / (2.0 * sr) - gas_usd

    def curl(self, prices: dict[str, float]) -> float | None:
        """Sum of oriented log prices around the loop.  `prices` maps pool addr -> price
        of that pool's BASE in units of its QUOTE."""
        total = 0.0
        for pool, orient in self.legs:
            p = prices.get(pool.addr)
            if p is None or p <= 0:
                return None
            total += orient * math.log(p)
        return total


def _node_of(pool: Pool, side: str) -> str:
    return pool.base if side == "base" else pool.quote


def build_cycles(pools: list[Pool], min_liq: float = MIN_LIQ_USD) -> list[Cycle]:
    """Every independent-ish cycle we can actually price.

    Two families:
      * 2-cycles ("venue curl"): the same token pair on two venues.  KVL on a two-edge
        loop.  This is the degenerate cycle and it is the strongest-liquidity test in the
        cluster, so it is reported alongside the triangles rather than instead of them.
      * 3-cycles (triangles): i -> j -> k -> i through three distinct pools.
    """
    live = [p for p in pools if p.liq_usd >= min_liq and p.price_native > 0]
    cycles: list[Cycle] = []

    # --- 2-cycles: same unordered pair, different pools
    by_pair: dict[frozenset[str], list[Pool]] = {}
    for p in live:
        by_pair.setdefault(frozenset({p.base, p.quote}), []).append(p)
    for _pair, group in by_pair.items():
        if len(group) < 2:
            continue
        for a, b in itertools.combinations(group, 2):
            # traverse a forward (base->quote), b backward.  If b is written with the
            # opposite base/quote convention, flip the orientation.
            orient_b = -1 if (b.base, b.quote) == (a.base, a.quote) else +1
            cycles.append(Cycle(nodes=(a.base, a.quote), legs=((a, +1), (b, orient_b))))

    # --- 3-cycles
    #   pick one pool per unordered pair; a triangle needs pools spanning {i,j},{j,k},{k,i}
    best: dict[frozenset[str], Pool] = {}
    for p in live:
        key = frozenset({p.base, p.quote})
        if key not in best or p.liq_usd > best[key].liq_usd:
            best[key] = p
    nodes = sorted({n for p in live for n in (p.base, p.quote)})
    for tri in itertools.combinations(nodes, 3):
        i, j, k = tri
        e_ij, e_jk, e_ki = (
            best.get(frozenset({i, j})),
            best.get(frozenset({j, k})),
            best.get(frozenset({k, i})),
        )
        if not (e_ij and e_jk and e_ki):
            continue
        legs = []
        for a, b, pool in ((i, j, e_ij), (j, k, e_jk), (k, i, e_ki)):
            # we want the log of (price of a in units of b) = V_a - V_b
            legs.append((pool, +1 if (pool.base, pool.quote) == (a, b) else -1))
        cycles.append(Cycle(nodes=(i, j, k), legs=tuple(legs)))
    return cycles


def price_map(pools: list[Pool], source: str) -> dict[str, float]:
    """source in {'last', 'reserve', 'hybrid'}.

    last     -- DexScreener priceNative, i.e. the LAST TRADE.  Available for every pool.
    reserve  -- quote/base reserve ratio.  The true MARGINAL price, constant-product only.
    hybrid   -- reserve where valid, last otherwise.  What an arb bot would approximate.
    """
    out: dict[str, float] = {}
    for p in pools:
        if source == "last":
            v: float | None = p.price_native
        elif source == "reserve":
            v = p.price_from_reserves()
        else:
            v = p.price_from_reserves() or p.price_native
        if v and v > 0:
            out[p.addr] = v
    return out


# --------------------------------------------------------------------------------------
# snapshot
# --------------------------------------------------------------------------------------


def snapshot(pools: list[Pool] | None = None, verbose: bool = True) -> dict:
    pools = pools if pools is not None else discover(verbose=False)
    live = [p for p in pools if p.liq_usd >= MIN_LIQ_USD and p.price_native > 0]
    cycles = build_cycles(pools)
    ts = time.time()

    rec: dict = {"ts": ts, "pools": {}, "cycles": []}
    for p in live:
        rec["pools"][p.addr] = {
            "pair": f"{p.base}/{p.quote}",
            "dex": p.dex,
            "kind": p.kind,
            "last": p.price_native,
            "reserve": p.price_from_reserves(),
            "liq_usd": p.liq_usd,
            "vol24": p.vol24,
            "tx24": p.txns24,
        }

    if verbose:
        print("\n=== pool state (marginal price recoverable only for constant product) ===")
        print(
            f"{'pair':<14} {'dex':<9} {'kind':<5} {'last':>13} "
            f"{'from reserves':>14} {'gap bps':>9} {'liq $':>10}"
        )
        for p in sorted(live, key=lambda q: -q.liq_usd):
            r = p.price_from_reserves()
            gap = f"{1e4 * math.log(r / p.price_native):>9,.0f}" if r else f"{'--':>9}"
            rs = f"{r:>14.6g}" if r else f"{'n/a (bins)':>14}"
            print(
                f"{p.base + '/' + p.quote:<14} {p.dex:<9} {p.kind:<5} "
                f"{p.price_native:>13.6g} {rs} {gap} {p.liq_usd:>10,.0f}"
            )

    for src in ("last", "hybrid"):
        pm = price_map(live, src)
        for c in cycles:
            v = c.curl(pm)
            if v is None:
                continue
            band = c.fee_band()
            rec["cycles"].append(
                {
                    "name": c.name,
                    "venues": c.venues,
                    "src": src,
                    "curl_bps": 1e4 * v,
                    "band_bps": 1e4 * band,
                    "excess_bps": 1e4 * (abs(v) - band),
                    "min_liq_usd": min(p.liq_usd for p, _ in c.legs),
                    "kinds": "".join(p.kind[0] for p, _ in c.legs),
                }
            )

    if verbose:
        for src in ("last", "hybrid"):
            rows = [r for r in rec["cycles"] if r["src"] == src]
            if not rows:
                continue
            print(f"\n=== curl, price source = {src} ===")
            print(f"{'cycle':<34} {'curl bps':>10} {'band bps':>9} {'excess':>9} {'thin leg $':>11}  venues")
            for r in sorted(rows, key=lambda r: -r["excess_bps"]):
                flag = "  <-- EMF" if r["excess_bps"] > 0 else ""
                print(
                    f"{r['name']:<34} {r['curl_bps']:>10,.0f} {r['band_bps']:>9,.0f} "
                    f"{r['excess_bps']:>9,.0f} {r['min_liq_usd']:>11,.0f}  {r['venues']}{flag}"
                )
        _full_band_table(cycles, price_map(live, "last"))
        _band_sensitivity(cycles)
    return rec


# Solana priority-fee'd swap; config.yaml caps max_priority_fee_lamports at 5_000_000
# (0.005 SOL). A 3-leg atomic route is taken here as ~0.004 SOL total at a $76 SOL price.
GAS_USD = 0.30


def _full_band_table(cycles: list[Cycle], prices: dict[str, float]) -> None:
    print("\n=== the band that decides whether MONEY moves, not just log price ===")
    print("band = sum(fees) + sqrt(2 * gas * sum r_e). The second term is the depth-and-gas")
    print(f"cost of actually pushing size around the loop. gas = ${GAS_USD:.2f}/loop.")
    print("dlmm_span W: 4.0 = no concentration (pessimistic bound); 0.2 = a tight DLMM range.\n")
    print(
        f"{'cycle':<30} {'curl':>7} {'fee':>6} | {'W=4.0: band':>12} {'X* $':>7} {'profit $':>9}"
        f" | {'W=0.2: band':>12} {'X* $':>7} {'profit $':>9}"
    )
    seen: set[str] = set()
    for c in cycles:
        key = c.name + c.venues
        if key in seen:
            continue
        seen.add(key)
        v = c.curl(prices)
        if v is None:
            continue
        cells = []
        for W in (4.0, 0.2):
            band, _, _ = c.full_band(GAS_USD, W)
            x, prof = c.arb_profit(v, GAS_USD, W)
            cells.append((1e4 * band, x, prof))
        print(
            f"{c.name:<30} {1e4 * v:>7,.0f} {1e4 * c.fee_band():>6,.0f} | "
            + " | ".join(f"{b:>12,.0f} {x:>7,.0f} {p:>9,.2f}" for b, x, p in cells)
        )
    print("\n  A positive `profit` column is the entire economic content of a curl excursion.")
    print("  Note how much larger the full band is than the fee band on any loop with a thin")
    print("  leg: the thin leg's r = W/TVL dominates the sum, so a $433 pool can make an 8%")
    print("  standing residual worth under a dollar.")


def _band_sensitivity(cycles: list[Cycle]) -> None:
    print("\n=== fee-band sensitivity (the band is the whole result, and the fees are assumed) ===")
    print("band half-width in bps, as (pumpswap LP+protocol leg) x (DLMM leg):")
    uniq: dict[str, Cycle] = {}
    for c in cycles:
        uniq.setdefault(c.name + c.venues, c)
    for c in list(uniq.values()):
        kinds = [p.kind for p, _ in c.legs]
        n_cp, n_dl = kinds.count("cpmm"), kinds.count("dlmm")
        if not (n_cp or n_dl):
            continue
        print(f"\n  {c.name}   ({n_cp} cpmm leg(s), {n_dl} dlmm leg(s))")
        hdr = "    ps\\dlmm " + "".join(f"{d:>9.2%}" for d in DLMM_SWEEP)
        print(hdr)
        for ps in PUMPSWAP_SWEEP:
            cells = []
            for dl in DLMM_SWEEP:
                total = 0.0
                for pool, _ in c.legs:
                    if pool.kind == "cpmm":
                        cr = pumpswap_fee(pool.fdv).taker - PUMPSWAP_LP_PROTOCOL
                        f = ps + cr
                    else:
                        f = dl
                    total += math.log(1.0 / (1.0 - f))
                cells.append(f"{1e4 * total:>9,.0f}")
            print(f"    {ps:>8.2%} " + "".join(cells))


# --------------------------------------------------------------------------------------
# poll
# --------------------------------------------------------------------------------------


def poll(out_path: str, minutes: float, interval: float) -> None:
    addrs_pools = discover(verbose=False)
    addrs = [p.addr for p in addrs_pools if p.liq_usd >= MIN_LIQ_USD]
    deadline = time.time() + minutes * 60.0
    n = 0
    with open(out_path, "a") as fh:
        while time.time() < deadline:
            t0 = time.time()
            fresh = fetch_by_addresses(addrs)
            if fresh:
                rec = snapshot(fresh, verbose=False)
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                n += 1
                emf = sum(1 for c in rec["cycles"] if c["excess_bps"] > 0 and c["src"] == "hybrid")
                print(f"[{n:>3}] {time.strftime('%H:%M:%S')} pools={len(fresh)} emf_cycles={emf}", flush=True)
            time.sleep(max(0.5, interval - (time.time() - t0)))
    print(f"done: {n} samples -> {out_path}")


# --------------------------------------------------------------------------------------
# analyze
# --------------------------------------------------------------------------------------


def _ar1(xs: list[float]) -> tuple[float, float, int]:
    """lag-1 autocorrelation, plus the Kendall small-sample debias used in
    RESULT_swing_cluster.md:  E[rho_hat] ~ rho - (1 + 3 rho)/n  =>  rho ~ (rho_hat + 1/n)/(1 - 3/n).
    """
    n = len(xs)
    if n < 6:
        return float("nan"), float("nan"), n
    m = statistics.fmean(xs)
    num = sum((xs[i] - m) * (xs[i + 1] - m) for i in range(n - 1))
    den = sum((x - m) ** 2 for x in xs)
    if den == 0:
        return float("nan"), float("nan"), n
    rho = num / den
    deb = (rho + 1.0 / n) / (1.0 - 3.0 / n) if n > 3 else float("nan")
    return rho, deb, n


def analyze(path: str) -> None:
    with open(path) as fh:
        recs = [json.loads(line) for line in fh if line.strip()]
    if not recs:
        print("no records")
        return
    span = (recs[-1]["ts"] - recs[0]["ts"]) / 60.0
    dts = [recs[i + 1]["ts"] - recs[i]["ts"] for i in range(len(recs) - 1)]
    dt = statistics.median(dts) if dts else float("nan")
    print(f"{len(recs)} samples over {span:.1f} min, median spacing {dt:.1f}s\n")

    series: dict[tuple[str, str, str], list[float]] = {}
    bands: dict[tuple[str, str, str], float] = {}
    for r in recs:
        for c in r["cycles"]:
            k = (c["src"], c["name"], c["venues"])
            series.setdefault(k, []).append(c["curl_bps"])
            bands[k] = c["band_bps"]

    print(
        f"{'src':<7} {'cycle':<32} {'n':>4} {'mean':>9} {'sd':>8} {'min':>9} {'max':>9} "
        f"{'band':>7} {'%out':>6} {'rho':>6} {'rho_db':>7} {'t_half':>9}"
    )
    for k, xs in sorted(series.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        src, name, _ = k
        band = bands[k]
        out = 100.0 * sum(1 for x in xs if abs(x) > band) / len(xs)
        rho, deb, _n = _ar1(xs)
        if math.isfinite(deb) and 0 < deb < 1:
            half = -dt * math.log(2) / math.log(deb) / 60.0
            hs = f"{half:>8.1f}m"
        elif math.isfinite(deb) and deb >= 1:
            hs = f"{'>=RW':>9}"
        else:
            hs = f"{'--':>9}"
        sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
        print(
            f"{src:<7} {name:<32} {len(xs):>4} {statistics.fmean(xs):>9,.0f} {sd:>8,.0f} "
            f"{min(xs):>9,.0f} {max(xs):>9,.0f} {band:>7,.0f} {out:>5.0f}% "
            f"{rho:>6.3f} {deb:>7.3f} {hs}"
        )
    print(
        "\nrho   = raw lag-1 autocorrelation of the curl series"
        "\nrho_db= Kendall-debiased, (rho + 1/n)/(1 - 3/n); at n~60 the correction is ~0.05"
        "\nt_half= CRUDE relaxation half-life implied by rho_db at the observed spacing."
        "\n        With n of this size the half-life is NOT identified -- read the sign, not the value."
    )

    # --- do excursions outside the band relax back toward it?
    print("\n=== excursions: do they relax? ===")
    print("For each cycle, look only at samples with |curl| > band, and ask whether the NEXT")
    print("step moves back toward the band. A restoring mechanism gives E[d|curl|] < 0 there.")
    print("Compare against the same quantity computed on the inside-band samples, which is the")
    print("control: with no restoring force the two are the same up to noise.\n")
    print(
        f"{'src':<7} {'cycle':<32} {'n_out':>6} {'runs':>5} {'med run':>8} "
        f"{'E[d|C|] out':>12} {'E[d|C|] in':>11}"
    )
    for k, xs in sorted(series.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        src, name, _ = k
        band = bands[k]
        out_mask = [abs(x) > band for x in xs]
        n_out = sum(out_mask)
        runs, cur = [], 0
        for m in out_mask:
            if m:
                cur += 1
            elif cur:
                runs.append(cur)
                cur = 0
        if cur:
            runs.append(cur)
        d_out = [abs(xs[i + 1]) - abs(xs[i]) for i in range(len(xs) - 1) if out_mask[i]]
        d_in = [abs(xs[i + 1]) - abs(xs[i]) for i in range(len(xs) - 1) if not out_mask[i]]
        mo = f"{statistics.fmean(d_out):>12,.1f}" if d_out else f"{'--':>12}"
        mi = f"{statistics.fmean(d_in):>11,.1f}" if d_in else f"{'--':>11}"
        mr = f"{statistics.median(runs) * dt:>7,.0f}s" if runs else f"{'--':>8}"
        print(f"{src:<7} {name:<32} {n_out:>6} {len(runs):>5} {mr} {mo} {mi}")
    print(
        "\n  A run that never ends inside the window is right-censored, and at this sample size\n"
        "  that is the normal case -- read `runs` as a lower bound and `med run` as censored."
    )

    # how much of the movement is real price movement vs. a stale quote not updating at all
    print("\nquote staleness: fraction of consecutive samples in which the price did not move")
    poolseries: dict[str, list[float]] = {}
    labels: dict[str, str] = {}
    for r in recs:
        for a, p in r["pools"].items():
            v = p.get("reserve") or p.get("last")
            if v:
                poolseries.setdefault(a, []).append(v)
                labels[a] = f"{p['pair']} {p['dex']}"
    for a, xs in sorted(poolseries.items(), key=lambda kv: labels[kv[0]]):
        if len(xs) < 2:
            continue
        frozen = sum(1 for i in range(len(xs) - 1) if xs[i] == xs[i + 1]) / (len(xs) - 1)
        print(f"  {labels[a]:<24} n={len(xs):>3}  frozen={frozen:>5.0%}")


# --------------------------------------------------------------------------------------
# dissipation audit
# --------------------------------------------------------------------------------------


def dissipation(pools: list[Pool] | None = None) -> None:
    pools = pools if pools is not None else discover(verbose=False)
    live = [p for p in pools if p.liq_usd > 0 and p.vol24 > 0]

    print("=== dissipation audit: fee yield per unit TVL, 24h window ===")
    print("Turnover is MEASURED. Fee tier is ASSUMED (see FeeSpec provenance). Yield = turnover x fee_lp.\n")
    print(
        f"{'pair':<16} {'dex':<9} {'kind':<5} {'TVL $':>10} {'vol24 $':>11} "
        f"{'turnover/d':>11} {'fee_lp':>8} {'yield/d':>9} {'yield/yr':>10}"
    )
    rows = []
    for p in sorted(live, key=lambda q: -(q.vol24 / q.liq_usd if q.liq_usd else 0)):
        turn = p.vol24 / p.liq_usd
        fee = p.fee()
        fee_lp = fee.taker * fee.lp_share
        y = turn * fee_lp
        rows.append((p, turn, fee_lp, y))
        tt = "TT" if SOL not in (p.base_mint, p.quote_mint) else "  "
        print(
            f"{p.base + '/' + p.quote:<14}{tt} {p.dex:<9} {p.kind:<5} {p.liq_usd:>10,.0f} "
            f"{p.vol24:>11,.0f} {turn:>10.1%} {fee_lp:>8.2%} {y:>8.2%} {y * 365:>9,.0f}%"
        )
    print("  TT = token-token pool (no SOL leg)\n")

    tt = [r for r in rows if SOL not in (r[0].base_mint, r[0].quote_mint)]
    ts = [r for r in rows if SOL in (r[0].base_mint, r[0].quote_mint)]
    print("=== the structural claim, tested ===")
    print("Claim (RESULT_swing_cluster.md): token-token pools are structurally higher-yield per TVL.")
    print("Turnover is the fee-tier-free half of that claim, so test it there first:\n")
    for label, group in (("token-token", tt), ("token/SOL ", ts)):
        if not group:
            continue
        turns = sorted(r[1] for r in group)
        print(
            f"  {label}  n={len(group):>2}  median turnover {statistics.median(turns):>8.1%}/d   "
            f"range {min(turns):.1%} - {max(turns):.1%}"
        )
    # robustness: the medians above include dust pools whose 24h volume is a handful of
    # dollars.  §3 rule 7 -- report the threshold with the number.
    print("\n  robustness to the liquidity floor (the medians above use every pool with vol>0):")
    for floor in (0.0, 100.0, 400.0):
        kt = [r[1] for r in tt if r[0].liq_usd >= floor]
        ks = [r[1] for r in ts if r[0].liq_usd >= floor]
        if not kt or not ks:
            continue
        mt, ms = statistics.median(kt), statistics.median(ks)
        print(
            f"    TVL floor ${floor:>6,.0f}:  TT n={len(kt)} median {mt:>7.1%}/d  |  "
            f"token/SOL n={len(ks)} median {ms:>8.1%}/d  |  deficit {ms / mt:>5.1f}x"
        )

    print("\n  per-pool turnover, sorted:")
    for p, turn, _, _ in sorted(rows, key=lambda r: -r[1]):
        tag = "TT" if SOL not in (p.base_mint, p.quote_mint) else "  "
        print(f"    {tag} {p.base + '/' + p.quote:<14} {p.dex:<9} {turn:>9.1%}/d  (TVL ${p.liq_usd:,.0f})")

    print("\n=== fee-tier break-even: how much higher must the DLMM tier be to win? ===")
    if tt and ts:
        med_tt = statistics.median([r[1] for r in tt])
        med_ts = statistics.median([r[1] for r in ts])
        print(
            f"  median turnover ratio (TT / token-SOL) = {med_tt:.3f} / {med_ts:.3f}"
            f" = {med_tt / med_ts:.3f}"
        )
        print(f"  so the token-token fee tier must exceed the token/SOL LP tier by {med_ts / med_tt:.1f}x")
        print("  just to break even on gross fee income per unit TVL.")
    # --- independent estimator of the creator fee rate, from the operator's own income
    dregg_vol = sum(p.vol24 for p in pools if "DREGG" in (p.base, p.quote))
    print("\n=== independent check on the creator-fee rate (the fee band depends on it) ===")
    print("PROGRAM.md sec.0 reports DREGG creator fees of $213-313/day. Creator fees are a")
    print("fixed rate on volume, so income/volume is an estimator of the rate:\n")
    if dregg_vol > 0:
        lo, hi = 213.0 / dregg_vol, 313.0 / dregg_vol
        print(f"  DREGG 24h volume across ALL its pools, measured now: ${dregg_vol:,.0f}")
        print(f"  implied creator rate = $213..$313 / ${dregg_vol:,.0f} = {lo:.2%} .. {hi:.2%}")
        candidates = (
            ("PumpSwap original flat", 0.0005),
            ("ladder, FDV>$300k", 0.0060),
            ("ladder, FDV<$300k", 0.0095),
        )
        for label, cand in candidates:
            verdict = "CONSISTENT" if lo <= cand <= hi else "excluded"
            print(f"    candidate {cand:>6.2%}  ({label:<22}) -> {verdict}")
        print("  CRUDE: the $213-313 figure and this volume figure are from different days, and")
        print("  DREGG volume is heavy-tailed. This is an order-of-magnitude discriminator only,")
        print("  and it is offered as such -- it separates 0.05% from ~1%, nothing finer.")
    print(
        "\n  NOT modelled here, and each one moves the answer:\n"
        "   * DLMM concentrates TVL into bins, so $1 of DLMM TVL is not $1 of constant-product depth.\n"
        "     Yield-per-TVL flatters DLMM by exactly the concentration factor, which is unmeasured here.\n"
        "   * impermanent loss: the swing study's whole argument is that IL is TEMPORARY on a\n"
        "     mean-reverting ratio.  That is a claim about the sign of IL, not about fee income,\n"
        "     and it is not tested by this table.\n"
        "   * 24h volume is one draw of a heavy-tailed variable on pools doing tens of trades a day."
    )


# --------------------------------------------------------------------------------------
# cross-API validation: what is this instrument's noise floor?
# --------------------------------------------------------------------------------------


def _txcount(tx: dict, window: str) -> int:
    v = tx.get(window) or {}
    return int(_f(v.get("buys")) + _f(v.get("sells")))


def crosscheck(pools: list[Pool] | None = None) -> None:
    """Two independent aggregators, same pools, same minute.

    The curl is a LEVEL statistic on the order of a few hundred bps.  If two aggregators
    disagree about a pool's price by more than the fee band, the instrument cannot resolve
    an EMF and every "standing arbitrage" it reports is an aggregator artifact.  This is
    the control that decides whether sec. 6 of the write-up says anything at all.
    """
    pools = pools if pools is not None else discover(verbose=False)
    live = [p for p in pools if p.liq_usd >= MIN_LIQ_USD and p.price_native > 0]
    addrs = [p.addr for p in live]
    gt = _get_retry(
        "https://api.geckoterminal.com/api/v2/networks/solana/pools/multi/" + ",".join(addrs[:30])
    )
    if not gt:
        print("geckoterminal unavailable (rate limit?) -- rerun in a minute")
        return
    gtp = {d["attributes"]["address"]: d["attributes"] for d in gt.get("data", [])}

    print("=== cross-API price agreement, and trade recency ===")
    print("A pool that has not traded recently has a FOSSIL quote; its contribution to any")
    print("cycle residual is staleness, not arbitrage.\n")
    print(
        f"{'pair':<14} {'dex':<9} {'DexScreener':>13} {'GeckoTerm':>13} "
        f"{'disagree bps':>13} {'tx m15':>7} {'tx h1':>6} {'tx h24':>7}"
    )
    gtprice: dict[str, float] = {}
    rows = []
    for p in sorted(live, key=lambda q: -q.liq_usd):
        g = gtp.get(p.addr)
        if not g:
            continue
        gq = _f(g.get("base_token_price_quote_token"))
        if gq > 0:
            gtprice[p.addr] = gq
        d = 1e4 * math.log(gq / p.price_native) if (gq > 0 and p.price_native > 0) else float("nan")
        tx = g.get("transactions") or {}
        n15, n1, n24 = (_txcount(tx, w) for w in ("m15", "h1", "h24"))
        rows.append((p, d, n1))
        print(
            f"{p.base + '/' + p.quote:<14} {p.dex:<9} {p.price_native:>13.6g} {gq:>13.6g} "
            f"{d:>13,.0f} {n15:>7} {n1:>6} {n24:>7}"
        )

    finite = [abs(d) for _, d, _ in rows if math.isfinite(d)]
    if finite:
        print(
            f"\n  median |disagreement| = {statistics.median(finite):,.0f} bps, "
            f"max = {max(finite):,.0f} bps"
        )

    cycles = build_cycles(pools)
    print("\n=== the same curl, computed independently from each aggregator ===")
    print(f"{'cycle':<34} {'DS bps':>9} {'GT bps':>9} {'spread':>9} {'band':>7}  verdict")
    for c in cycles:
        a = c.curl(price_map(live, "last"))
        b = c.curl(gtprice)
        if a is None or b is None:
            continue
        band = 1e4 * c.fee_band()
        a, b = 1e4 * a, 1e4 * b
        spread = abs(a - b)
        if spread > band:
            verdict = "UNRESOLVABLE: sources disagree by more than the band"
        elif abs(a) > band and abs(b) > band and a * b > 0:
            verdict = "EMF survives both sources, same sign"
        else:
            verdict = "inside band on at least one source"
        print(f"{c.name:<34} {a:>9,.0f} {b:>9,.0f} {spread:>9,.0f} {band:>7,.0f}  {verdict}")


# --------------------------------------------------------------------------------------
# the RC layer: capacitance from depth, and what tau buys us
# --------------------------------------------------------------------------------------

# Half-lives measured in studies/RESULT_swing_cluster.md (hourly GeckoTerminal OHLCV,
# AR(1) on log-ratios, Kendall-debiased).  Reproduced here as INPUTS, not re-measured.
MEASURED_HALF_LIVES_H = {
    ("DREGG", "SOLVE"): (7.2, "n=499, debiased rho 0.908, called robust"),
    ("weave", "nosis"): (8.9, "n=83, debiased rho 0.925, called reverting-but-noisy"),
}


def rc(pools: list[Pool] | None = None) -> None:
    """Capacitance from pool depth, and the one parameter-free prediction this model makes.

    Derivations (full text in RESULT_circuit_model.md secs. 2 and 4):

      constant product, x*y=k, potential V = ln p, charge Q = the quote-side reserve y:
          V = 2 ln y - ln k       =>   dQ/dV = y/2 = TVL/4
      so C = TVL/4, in units of VALUE per unit log-price.  Exact, not fitted.

      the same pool's impact resistance, current measured as value flow:
          d ln p = -2 dy/y = -4 dValue/TVL   =>   r = 4/TVL,  g = TVL/4
      so for a constant-product pool  C = g = TVL/4  identically.

      capacitors on a PATH between two tokens add in series (1/C = sum 1/C_i);
      parallel pools on the SAME pair add in parallel (C = sum C_i).
    """
    pools = pools if pools is not None else discover(verbose=False)
    live = [p for p in pools if p.liq_usd >= MIN_LIQ_USD]

    print("=== capacitance of each pool:  C = TVL/4  (constant product, exact) ===")
    print("For a DLMM this formula does NOT apply -- see the write-up sec. 2.2. The bin")
    print("structure makes C a comb (infinite inside a bin, zero at a boundary); the")
    print("coarse-grained value is (value in bin)/(bin width in log price), which needs the")
    print("active bin and is not exposed by any keyless endpoint. DLMM rows are shown with")
    print("the constant-product formula ONLY as a lower bound on their true depth.\n")
    print(f"{'pair':<14} {'dex':<9} {'kind':<5} {'TVL $':>10} {'C = TVL/4 $':>12}")
    cap: dict[frozenset[str], float] = {}
    for p in sorted(live, key=lambda q: -q.liq_usd):
        c = p.liq_usd / 4.0
        note = "" if p.kind == "cpmm" else "  (lower bound)"
        print(f"{p.base + '/' + p.quote:<14} {p.dex:<9} {p.kind:<5} {p.liq_usd:>10,.0f} {c:>12,.0f}{note}")
        key = frozenset({p.base, p.quote})
        cap[key] = cap.get(key, 0.0) + c  # parallel pools on one pair: capacitances add
    print("\n  parallel-combined capacitance per token pair (same pair, several venues):")
    for k, v in sorted(cap.items(), key=lambda kv: -kv[1]):
        print(f"    {'/'.join(sorted(k)):<18} C = ${v:,.0f}")

    print("\n=== series capacitance along the SOL path, per measured pair ===")
    preds = []
    for (a, b), (half, prov) in MEASURED_HALF_LIVES_H.items():
        ca = cap.get(frozenset({a, "SOL"}))
        cb = cap.get(frozenset({b, "SOL"}))
        if not ca or not cb:
            print(f"  {a}/{b}: missing a SOL leg, skipped")
            continue
        cser = 1.0 / (1.0 / ca + 1.0 / cb)
        preds.append((a, b, cser, half, prov))
        print(
            f"  {a}/{b}: C_{a}=${ca:,.0f}  C_{b}=${cb:,.0f}  ->  C_series=${cser:,.0f}"
            f"   measured t_half={half}h  ({prov})"
        )

    if len(preds) == 2:
        (a1, b1, c1, h1, _), (a2, b2, c2, h2, _) = preds
        print("\n=== the parameter-free prediction, and its check ===")
        print("  tau = R*C with a SINGLE population-level R (same arbitrageurs/traders for")
        print("  every pair in one community cluster) implies  t_half ratio == C ratio,")
        print("  with NO fitted parameter. Both sides are independently measured.\n")
        print(f"    predicted  C({a1}/{b1}) / C({a2}/{b2}) = {c1:,.0f} / {c2:,.0f} = {c1 / c2:.3f}")
        print(f"    measured   t({a1}/{b1}) / t({a2}/{b2}) = {h1} / {h2} = {h1 / h2:.3f}")
        print(f"    ratio of ratios = {(h1 / h2) / (c1 / c2):.2f}   (1.00 would be exact agreement)")
        print("\n  FALSIFICATION: this is one degree of freedom checked once, on a pair whose")
        print("  own study called it 'reverting, noisy' at n=83, using TODAY's TVL against a")
        print("  half-life fitted over weeks of very different TVL. It is a coincidence-grade")
        print("  check, not evidence. It fails if, on >=6 pairs with >=300 hourly obs each and")
        print("  TVL averaged over the estimation window, the rank correlation between")
        print("  C_series and t_half is not significantly positive.")

    print("\n=== implied response conductance 1/R, and its sanity check ===")
    print("  R is the ONE free parameter in the whole model: C is measured from depth and")
    print("  tau is measured from the panel, so R = tau/C is IDENTIFIED, not fitted.\n")
    for a, b, cser, half, _ in preds:
        tau_s = half * 3600.0 / math.log(2.0)  # half-life -> e-folding time
        g_arb = cser / tau_s  # dollars per second per unit log-price
        print(f"  {a}/{b}:  tau = {tau_s / 3600:.1f}h,  C = ${cser:,.0f}")
        print(f"        1/R = C/tau = ${g_arb:.4f}/s per unit log-price")
        for dev in (0.02, 0.10):
            per_day = g_arb * dev * 86400
            print(f"        at a {dev:.0%} mispricing this predicts ${per_day:,.0f}/day of restoring flow")
    print("\n  Sanity anchor: compare those to the pools' MEASURED 24h volume above. A predicted")
    print("  restoring flow far larger than total observed volume would falsify the model outright.")


# --------------------------------------------------------------------------------------
# the energy ledger for one swap -- exact, worked on a real pool
# --------------------------------------------------------------------------------------


def ledger(pools: list[Pool] | None = None, trade_usd: float = 500.0) -> None:
    """Trader's wealth change = LP fee + energy stored in the pool + gas.  Exactly.

    For x*y=k with fee f, a trader sending dy of quote gets out
        dx = x * dy(1-f) / (y + dy(1-f)),
    worth p0*dx at the PRE-TRADE mid.  Writing rho = dy(1-f)/y, the shortfall is

        dy - p0*dx = dy * [1 - (1-f)/(1+rho)]  =  f*dy  +  dy^2/y  + O(3)

    and the second term is EXACTLY the energy stored in the capacitor:
        Delta V = 2*dy/y,   C = y/2,   (1/2) C (Delta V)^2 = (1/2)(y/2)(2dy/y)^2 = dy^2/y.

    So: the fee term is I^2 R dissipation and is gone (it is the LP's income); the impact
    term is (1/2)CV^2 stored and comes back on the reverse trade.  That is the circuit
    statement of the round-trip identity already in PROGRAM.md sec. 1.4.
    """
    pools = pools if pools is not None else discover(verbose=False)
    cp = [p for p in pools if p.kind == "cpmm" and p.liq_usd >= MIN_LIQ_USD]
    print(f"=== energy ledger for one ${trade_usd:,.0f} buy, per pool, exact constant-product algebra ===\n")
    print(
        f"{'pair':<14} {'TVL $':>10} {'fee $':>8} {'impact $':>9} {'(1/2)CV^2':>10} "
        f"{'agree':>7} {'dV bps':>8} {'total $':>8}"
    )
    for p in sorted(cp, key=lambda q: -q.liq_usd):
        y = p.liq_usd / 2.0  # quote side value = half of TVL
        f = p.fee().taker
        dy = trade_usd
        dy_eff = dy * (1 - f)
        rho = dy_eff / y
        out_at_mid = dy_eff / (1 + rho)
        shortfall = dy - out_at_mid
        fee_paid = f * dy
        impact = shortfall - fee_paid
        dV = 2 * dy_eff / y  # exact-ish: d ln p for this size
        stored = 0.5 * (y / 2.0) * dV * dV
        agree = abs(impact - stored) / impact if impact else 0.0
        print(
            f"{p.base + '/' + p.quote:<14} {p.liq_usd:>10,.0f} {fee_paid:>8.2f} {impact:>9.2f} "
            f"{stored:>10.2f} {1 - agree:>6.1%} {1e4 * dV:>8,.0f} {shortfall:>8.2f}"
        )
    print(
        "\n  'agree' is how closely the brute-force impact cost matches (1/2)C(dV)^2 with C=TVL/4.\n"
        "  It is not 100% only because the closed form is a second-order expansion and the trade\n"
        "  sizes here are not infinitesimal; the gap IS the third-order term.\n"
        "\n  Read the columns: the FEE column is dissipated and is the LP's income. The IMPACT\n"
        "  column is stored in the pool and is returned to whoever trades back. Gas is a third,\n"
        "  size-independent dissipation term not shown (it does not scale with trade size, which\n"
        "  is exactly why it sets a MINIMUM profitable arb notional -- write-up sec. 3.3)."
    )


# --------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "mode",
        choices=[
            "discover", "snapshot", "poll", "analyze",
            "dissipation", "crosscheck", "rc", "ledger", "all",
        ],
    )
    ap.add_argument("--minutes", type=float, default=20.0)
    ap.add_argument("--interval", type=float, default=20.0)
    ap.add_argument("--out", default="curl_poll.jsonl")
    ap.add_argument("--in", dest="inp", default="curl_poll.jsonl")
    a = ap.parse_args()

    if a.mode == "discover":
        discover()
    elif a.mode == "snapshot":
        snapshot()
    elif a.mode == "poll":
        poll(a.out, a.minutes, a.interval)
    elif a.mode == "analyze":
        analyze(a.inp)
    elif a.mode == "dissipation":
        dissipation()
    elif a.mode == "crosscheck":
        crosscheck()
    elif a.mode == "rc":
        rc()
    elif a.mode == "ledger":
        ledger()
    elif a.mode == "all":
        pools = discover()
        snapshot(pools)
        print()
        crosscheck(pools)
        print()
        rc(pools)
        print()
        ledger(pools)
        print()
        dissipation(pools)
    return 0


if __name__ == "__main__":
    sys.exit(main())
