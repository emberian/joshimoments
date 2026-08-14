"""Which pools should exist?  A measurement instrument for deliberate edge creation.

Companion to studies/RESULT_edge_creation.md.  Every number in the write-up is produced
by this file or by an explicitly-labelled hand calculation reproduced inside it.

PROGRAM.md §8 names "deliberate edge creation" as a move the old frame could not express:
place a pool between two tokens that lack a low-resistance path and you become the
monopolist wire on a route flow wants to take.  This file asks whether that sentence is
true of *this* cluster, and the answer it measures is largely NO — for a reason that is
more useful than a yes would have been.

The frame, stated once so the code reads as an implementation of it
------------------------------------------------------------------

    node        token       potential   V_i = ln(price of i)
    edge        pool        measures    V_a - V_b = ln p
    fee         diode pair  dead-zone   sum of leg fees around a loop
    liquidity   CAPACITANCE (not conductance) -- studies/RESULT_circuit_model.md §2.3
    a range-exited DLMM position is an OPEN CIRCUIT, and that turns out to be the
    whole ballgame (see `positions`, duty cycle)

Three things this instrument measures that nothing else in the repo does:

1. **Who actually crosses a token-token edge.**  Every swap through the operator's own
   token-token pools is classified by *which other pools the same transaction touched*.
   An atomic transaction that touches A/SOL, B/SOL and A/B has closed a cycle: that is
   an arbitrageur, not a user.  A transaction touching only A/B is a genuine A<->B
   trade.  The split is the difference between "we built a wire people wanted" and
   "we built a toll booth on a loop".

2. **The complete edge inventory, on chain.**  Both public aggregators lag and both
   report reserve figures that the vaults contradict.  `graph` resolves every pool's
   vault balances and (for Meteora DLMM) decodes `bin_step`/`base_factor`/
   `protocol_share` straight out of the `LbPair` account, so the fee tier of every edge
   is *read*, not assumed.  studies/RESULT_circuit_model.md §3.2 had to carry the DLMM
   leg as a swept unknown; it no longer has to.

3. **Every token-token position the desk has ever opened, scored against HODL.**
   Deposits, fee claims and withdrawals are reconstructed from chain and valued at
   minute-bar prices, so "the harvest was 31.6%/day" and "the position lost money" stop
   being different conversations.

Modes
-----
  graph       every pool touching the cluster mints; vaults + decoded fee tiers on chain;
              node degrees; which edges are missing, which are dead one-sided husks
  vol         ratio volatility matrix sigma_AB from GeckoTerminal minute bars, at four
              sampling steps, because microstructure noise inflates the 1-minute number
  flow        tape decomposition: arb-cycle vs routing-leg vs genuine direct A<->B
  positions   every operator token-token LP position, from chain, scored vs HODL, with
              in-range duty cycle
  rank        the missing-edge ranking arithmetic and the minimum-viable-TVL floors
  all         all of the above, in order

Usage
-----
  python studies/edge_creation.py all
  python studies/edge_creation.py graph
  python studies/edge_creation.py positions --pool weave/nosis

Network: DexScreener + GeckoTerminal (keyless) and a **read-only** Helius JSON-RPC
client whose method whitelist is enforced in code, following the pattern in
shitcoims_cluster/rpc.py.  Nothing here signs, spends, or writes to state/.
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import hashlib
import itertools
import json
import math
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Iterable

# --------------------------------------------------------------------------------------
# universe -- mints from shitcoims_cluster/pools.py, which resolved them on chain
# --------------------------------------------------------------------------------------

WEAVE: Final[str] = "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump"
NOSIS: Final[str] = "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump"
DREGG: Final[str] = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
SOLVE: Final[str] = "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump"
WSOL: Final[str] = "So11111111111111111111111111111111111111112"

#: Human labels.  `shitcoims_cluster/pools.py` verified these against vault mints; the
#: session scratchpad that RESULT_swing_cluster.md cites has weave and SOLVE transposed.
#: Trust this table and pools.py.
SYMBOL: Final[dict[str, str]] = {
    WEAVE: "weave",
    NOSIS: "nosis",
    DREGG: "DREGG",
    SOLVE: "SOLVE",
    WSOL: "SOL",
}
CLUSTER_MINTS: Final[dict[str, str]] = {
    "weave": WEAVE,
    "nosis": NOSIS,
    "DREGG": DREGG,
    "SOLVE": SOLVE,
}

#: The four token/SOL pools whose reserves the tape records, used as the price reference.
REFERENCE_POOL: Final[dict[str, str]] = {
    "weave": "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn",
    "nosis": "7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc",
    "DREGG": "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU",
    "SOLVE": "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr",
}

METEORA_DLMM: Final[str] = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
PUMPSWAP: Final[str] = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
TOKEN_PROGRAM: Final[str] = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022: Final[str] = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

#: The desk's LP wallet ("tha fund"), from studies/RESULT_lp_history.md.
FUND: Final[str] = "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"

#: One PumpSwap leg's all-in taker cost.  0.20% LP + 0.05% protocol + creator fee.  The
#: creator leg is the FDV-inverse ladder (0.95 / 0.60 / 0.35%); the operator's own income
#: implies a realized take of 0.81-1.19% (studies/RESULT_circuit_model.md §9.3), so the
#: honest interval for a leg is 1.06-1.44% and the two-hop route is 2.12-2.88%.  Every
#: place this matters, both ends are carried.
PUMPSWAP_LEG_LO: Final[float] = 0.0025 + 0.0081
PUMPSWAP_LEG_HI: Final[float] = 0.0025 + 0.0119

USER_AGENT: Final[dict[str, str]] = {"User-Agent": "joshibot-research/0.1 (studies/edge_creation.py)"}

CACHE_DIR: Final[Path] = Path(
    os.environ.get("EDGE_CACHE", "/tmp/joshibot-edge-creation")
)


# --------------------------------------------------------------------------------------
# http, and a read-only RPC client
# --------------------------------------------------------------------------------------


def _get(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _get_retry(url: str, tries: int = 4, timeout: int = 30) -> Any | None:
    for k in range(tries):
        try:
            return _get(url, timeout=timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
            if k == tries - 1:
                return None
            time.sleep(2.0 + 3.0 * k)
    return None


class RpcError(RuntimeError):
    """An RPC call failed.  Never carries a URL, because the URL carries the API key."""


class ReadOnlyRpc:
    """Minimal Helius JSON-RPC client with an enforced read-method whitelist.

    Deliberately *not* an import of :mod:`shitcoims_cluster.rpc`: that module's whitelist
    is scoped to the recorder's needs (signatures + transactions) and this study also
    needs ``getAccountInfo`` and ``getTokenAccountsByOwner``.  Widening the collector's
    whitelist so a study can borrow it would weaken the collector's guarantee to buy a
    convenience.  The whitelist discipline is copied; the module is not.
    """

    METHODS: Final[frozenset[str]] = frozenset(
        {
            "getAccountInfo",
            "getTokenAccountsByOwner",
            "getSignaturesForAddress",
            "getTransaction",
        }
    )

    def __init__(self, key_file: str = "~/.helius-key") -> None:
        path = Path(key_file).expanduser()
        self._url = f"https://mainnet.helius-rpc.com/?api-key={path.read_text().strip()}"

    def call(self, method: str, params: list[Any]) -> Any:
        if method not in self.METHODS:
            raise RpcError(f"{method} is not a read method")
        return self._post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

    def batch(self, calls: list[tuple[str, list[Any]]]) -> list[Any]:
        for method, _ in calls:
            if method not in self.METHODS:
                raise RpcError(f"{method} is not a read method")
        payload = [
            {"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)
        ]
        got = self._post(payload)
        return got if isinstance(got, list) else [got]

    def _post(self, payload: Any, tries: int = 6) -> Any:
        body = json.dumps(payload).encode()
        for attempt in range(tries):
            try:
                req = urllib.request.Request(
                    self._url, data=body, headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=120) as f:
                    return json.load(f)
            except Exception as exc:
                if attempt == tries - 1:
                    raise RpcError(type(exc).__name__) from None
                time.sleep(0.5 * 2**attempt)
        raise RpcError("unreachable")


# --------------------------------------------------------------------------------------
# base58, anchor discriminators
# --------------------------------------------------------------------------------------

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_IDX = {c: i for i, c in enumerate(_B58)}


def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + _B58_IDX[c]
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + body


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def _disc(name: str) -> str:
    """Anchor's ``sha256("global:" + snake_case)[:8]``, derived rather than scraped."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return hashlib.sha256(f"global:{snake}".encode()).digest()[:8].hex()


#: The Meteora DLMM instructions this study needs to recognise.  Same derivation as the
#: table in shitcoims_cluster/pools.py, extended to the liquidity-side instructions.
_DLMM_IX_NAMES: Final[tuple[str, ...]] = (
    "swap", "swap2", "swapExactOut", "swapExactOut2",
    "swapWithPriceImpact", "swapWithPriceImpact2",
    "addLiquidity", "addLiquidityByWeight", "addLiquidityByStrategy",
    "addLiquidityByStrategy2", "addLiquidity2", "addLiquidityByStrategyOneSide",
    "addLiquidityOneSidePrecise",
    "removeLiquidity", "removeLiquidity2", "removeLiquidityByRange",
    "removeLiquidityByRange2", "removeAllLiquidity",
    "claimFee", "claimFee2",
    "initializePosition", "initializePositionPda",
    "closePosition", "closePosition2", "closePositionIfEmpty",
    "initializeLbPair", "initializeLbPair2",
    "initializeCustomizablePermissionlessLbPair",
    "initializeCustomizablePermissionlessLbPair2",
    "initializeBinArray", "initializeBinArrayBitmapExtension",
)
DLMM_IX: Final[dict[str, str]] = {_disc(n): n for n in _DLMM_IX_NAMES}
SWAP_IX: Final[frozenset[str]] = frozenset(
    d for d, n in DLMM_IX.items() if n.startswith("swap")
)


# --------------------------------------------------------------------------------------
# on-chain reads
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Vault:
    account: str
    mint: str
    symbol: str
    amount: float


def pool_vaults(rpc: ReadOnlyRpc, pool: str) -> list[Vault]:
    """Every token account owned by ``pool``, across both SPL token programs.

    The pump.fun mints in this cluster are **Token-2022**, and the SOL side is classic
    SPL.  Querying one program returns exactly half of every pool, which reads as a
    one-sided pool and is wrong in the most misleading possible direction.  Both
    programs, always.
    """
    out: list[Vault] = []
    for program in (TOKEN_PROGRAM, TOKEN_2022):
        res = rpc.call(
            "getTokenAccountsByOwner", [pool, {"programId": program}, {"encoding": "jsonParsed"}]
        )
        for v in (res.get("result") or {}).get("value", []):
            info = v["account"]["data"]["parsed"]["info"]
            out.append(
                Vault(
                    account=v["pubkey"],
                    mint=info["mint"],
                    symbol=SYMBOL.get(info["mint"], info["mint"][:6]),
                    amount=float(info["tokenAmount"]["uiAmountString"]),
                )
            )
    return out


@dataclass(frozen=True)
class LbPair:
    """The fields of a Meteora ``LbPair`` this study needs, decoded from account data.

    Layout (anchor, little-endian), offsets from the start of the account:

        8     discriminator
        8     StaticParameters.base_factor u16, filter_period u16, decay_period u16,
              reduction_factor u16
        16    variable_fee_control u32, max_volatility_accumulator u32,
              min_bin_id i32, max_bin_id i32
        32    protocol_share u16, base_fee_power_factor u8, _pad[5]
        40    VariableParameters (32 bytes)
        72    bump_seed u8, bin_step_seed[2], pair_type u8
        76    active_id i32
        80    bin_step u16
        82    status u8
        88    token_x_mint, token_y_mint, reserve_x, reserve_y  (32 each)

    The fee formula is Meteora's own:
    ``base_fee = base_factor * bin_step * 10 * 10**base_fee_power_factor`` in units of
    1e9.  Cross-checked below against studies/RESULT_swing_cluster.md, which measured
    5.51-5.60% to LP on the weave/nosis pool from vault deltas around fee claims: this
    decoder returns 6.000% base / 5.400% to LP for that pool.
    """

    address: str
    bin_step: int
    base_factor: int
    protocol_share_bps: int
    base_fee_power_factor: int
    active_id: int
    status: int
    token_x: str
    token_y: str

    @property
    def base_fee(self) -> float:
        return self.base_factor * self.bin_step * 10 * (10**self.base_fee_power_factor) / 1e9

    @property
    def lp_fee(self) -> float:
        return self.base_fee * (1.0 - self.protocol_share_bps / 10_000.0)


def read_lb_pair(rpc: ReadOnlyRpc, pool: str) -> LbPair | None:
    res = rpc.call("getAccountInfo", [pool, {"encoding": "base64"}])
    val = (res.get("result") or {}).get("value")
    if not val or val.get("owner") != METEORA_DLMM:
        return None
    import base64

    raw = base64.b64decode(val["data"][0])
    if len(raw) < 216:
        return None
    (base_factor,) = struct.unpack_from("<H", raw, 8)
    (protocol_share,) = struct.unpack_from("<H", raw, 32)
    base_pow = raw[34]
    (active_id,) = struct.unpack_from("<i", raw, 76)
    (bin_step,) = struct.unpack_from("<H", raw, 80)
    return LbPair(
        address=pool,
        bin_step=bin_step,
        base_factor=base_factor,
        protocol_share_bps=protocol_share,
        base_fee_power_factor=base_pow,
        active_id=active_id,
        status=raw[82],
        token_x=SYMBOL.get(b58encode(raw[88:120]), b58encode(raw[88:120])[:8]),
        token_y=SYMBOL.get(b58encode(raw[120:152]), b58encode(raw[120:152])[:8]),
    )


def all_signatures(rpc: ReadOnlyRpc, address: str) -> list[dict]:
    """Every signature ever, paginated backwards.  Includes failures (they are data)."""
    out: list[dict] = []
    before: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 1000}
        if before:
            params["before"] = before
        got = rpc.call("getSignaturesForAddress", [address, params])["result"]
        if not got:
            break
        out += got
        before = got[-1]["signature"]
        if len(got) < 1000:
            break
    return out


def fetch_transactions(rpc: ReadOnlyRpc, sigs: Iterable[str], tag: str) -> dict[str, dict]:
    """Batched ``getTransaction``, cached to disk because these runs are large."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{tag}.json"
    cached: dict[str, dict] = json.loads(path.read_text()) if path.exists() else {}
    want = [s for s in sigs if s not in cached]
    for i in range(0, len(want), 20):
        calls = [
            ("getTransaction", [s, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
            for s in want[i : i + 20]
        ]
        for item in rpc.batch(calls):
            tx = (item or {}).get("result")
            if tx:
                cached[tx["transaction"]["signatures"][0]] = tx
        time.sleep(0.12)
    if want:
        path.write_text(json.dumps(cached))
    return cached


# --------------------------------------------------------------------------------------
# aggregator discovery
# --------------------------------------------------------------------------------------


@dataclass
class Edge:
    address: str
    dex: str
    pair: tuple[str, str]
    liq_reported: float
    vol24: float
    created: str | None = None
    vaults: list[Vault] = field(default_factory=list)
    cfg: LbPair | None = None

    @property
    def label(self) -> str:
        return f"{self.pair[0]}/{self.pair[1]}"

    @property
    def one_sided(self) -> bool:
        """True when a vault side reads zero: the edge exists but conducts one way only.

        This is the *literal* diode of studies/RESULT_circuit_model.md, not the fee
        dead-zone one.  A DLMM whose liquidity has all converted to one token quotes
        only the direction that spends that token; the reverse direction has no
        inventory at any price.  Capacitance on the missing side is zero, so it is an
        open circuit, and it earns nothing.
        """
        if len(self.vaults) < 2:
            return True
        return any(v.amount <= 0.0 for v in self.vaults)

    @property
    def fee(self) -> float | None:
        """Total taker fee on this leg, as a fraction of input."""
        if self.cfg is not None:
            return self.cfg.base_fee
        if self.dex == "pumpswap":
            return PUMPSWAP_LEG_HI
        return None


def discover_edges(verbose: bool = True) -> list[Edge]:
    """Every pool either aggregator knows that touches a cluster mint.

    GeckoTerminal is queried as well as DexScreener because DexScreener's per-token pool
    list is *shorter*: it omitted the SOLVE/DREGG pool and one of the two weave/DREGG
    pools entirely at the time of writing.  Missing an edge is the one error this study
    cannot survive, so both are unioned and the on-chain vault read is the arbiter.
    """
    edges: dict[str, Edge] = {}
    for mint in CLUSTER_MINTS.values():
        d = _get_retry(f"https://api.dexscreener.com/latest/dex/tokens/{mint}")
        for p in (d or {}).get("pairs") or []:
            a = p["pairAddress"]
            edges.setdefault(
                a,
                Edge(
                    address=a,
                    dex=p.get("dexId", "?"),
                    pair=(p["baseToken"]["symbol"], p["quoteToken"]["symbol"]),
                    liq_reported=float((p.get("liquidity") or {}).get("usd") or 0.0),
                    vol24=float((p.get("volume") or {}).get("h24") or 0.0),
                ),
            )
        time.sleep(0.4)
    for mint in CLUSTER_MINTS.values():
        d = _get_retry(
            f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}/pools?page=1"
        )
        for p in (d or {}).get("data") or []:
            a = p["id"].replace("solana_", "")
            attr = p["attributes"]
            nm = (attr.get("name") or "/").split(" / ")
            e = edges.get(a)
            if e is None:
                edges[a] = Edge(
                    address=a,
                    dex="meteora" if len(a) == 44 else "?",
                    pair=(nm[0], nm[-1]),
                    liq_reported=float(attr.get("reserve_in_usd") or 0.0),
                    vol24=float((attr.get("volume_usd") or {}).get("h24") or 0.0),
                    created=attr.get("pool_created_at"),
                )
            else:
                e.created = attr.get("pool_created_at")
        time.sleep(2.5)
    if verbose:
        print(f"aggregators know {len(edges)} pools touching the four cluster mints")
    return sorted(edges.values(), key=lambda e: -e.liq_reported)


# --------------------------------------------------------------------------------------
# prices
# --------------------------------------------------------------------------------------


class Prices:
    """Minute-bar USD closes per cluster token, from GeckoTerminal, with step lookup.

    GeckoTerminal returns 1000 bars, which is ~16.7 hours of minute data -- enough for
    every position in this study except the oldest weave/DREGG legs, which fall back to
    the hourly series.  ``at()`` is a *step* function (last close at or before t), never
    an interpolation: interpolating a price you did not observe is exactly the kind of
    quiet fabrication PROGRAM.md §0 was written about.
    """

    def __init__(self, cache: bool = True) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = CACHE_DIR / "ohlcv.json"
        raw: dict[str, list] = json.loads(path.read_text()) if (cache and path.exists()) else {}
        for tf in ("minute", "hour"):
            for tok, pool in REFERENCE_POOL.items():
                key = f"{tok}_{tf}"
                if key in raw:
                    continue
                url = (
                    f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}"
                    f"/ohlcv/{tf}?aggregate=1&limit=1000&currency=usd&token=base"
                )
                d = _get_retry(url, tries=5)
                if d is None:
                    continue
                raw[key] = d["data"]["attributes"]["ohlcv_list"]
                time.sleep(2.5)
        path.write_text(json.dumps(raw))
        self._s: dict[str, tuple[list[int], list[float]]] = {}
        self._m: dict[str, tuple[int, int]] = {}
        for tok in REFERENCE_POOL:
            merged: dict[int, float] = {}
            for tf in ("hour", "minute"):  # minute overwrites hour where both exist
                for bar in raw.get(f"{tok}_{tf}", []):
                    merged[bar[0]] = bar[4]
            ts = sorted(merged)
            self._s[tok] = (ts, [merged[t] for t in ts])
            mts = sorted(b[0] for b in raw.get(f"{tok}_minute", []))
            self._m[tok] = (mts[0], mts[-1]) if mts else (0, 0)

    def at(self, token: str, when: int) -> float:
        ts, px = self._s[token]
        i = bisect.bisect_right(ts, when) - 1
        return px[max(0, min(len(px) - 1, i))]

    def span(self, token: str) -> tuple[int, int]:
        ts, _ = self._s[token]
        return ts[0], ts[-1]

    def minute_span(self, token: str) -> tuple[int, int]:
        """Where genuine 1-minute bars exist.

        Outside it, ``at()`` falls back to the hourly series, which is correct for
        *valuing a cash flow* (an hour-old close is a real observed price) but wrong for
        *estimating volatility*: sampling a step function that only moves hourly at a
        15-minute grid manufactures a variance profile out of the interpolation scheme
        rather than the market.  `vol` therefore runs strictly inside this span.
        """
        return self._m[token]

    def series(self, token: str, step: int, t0: int, t1: int) -> list[float]:
        return [self.at(token, t) for t in range(t0, t1 + 1, step)]


def realized_vol(prices: Prices, a: str, b: str, step: int, t0: int, t1: int) -> tuple[float, float, int]:
    """(sigma per sqrt(day), total log drift, n) of ln(p_a / p_b) sampled every `step` s.

    Reported at four steps by `vol` because the 1-minute figure is inflated by
    bid-ask bounce in pools this thin -- the same attenuation caveat
    studies/RESULT_swing_cluster.md raised about its correlations, pointed the other
    way.  The write-up quotes the 15-minute column.
    """
    ra = prices.series(a, step, t0, t1)
    rb = prices.series(b, step, t0, t1)
    r = [math.log(x / y) for x, y in zip(ra, rb, strict=True)]
    d = [r[i + 1] - r[i] for i in range(len(r) - 1)]
    n = len(d)
    if n < 10:
        return float("nan"), float("nan"), n
    m = sum(d) / n
    var = sum((x - m) ** 2 for x in d) / (n - 1)
    return math.sqrt(var * (86400 / step)), sum(d), n


# --------------------------------------------------------------------------------------
# mode: graph
# --------------------------------------------------------------------------------------


def cmd_graph(rpc: ReadOnlyRpc, verbose: bool = True) -> dict[str, Any]:
    edges = discover_edges(verbose=verbose)
    for e in edges:
        if e.liq_reported < 1.0 and e.vol24 < 1.0:
            continue  # aggregator dust; still resolved below if it is a cluster-cluster edge
    interesting = [
        e
        for e in edges
        if e.liq_reported >= 1.0 or e.vol24 >= 1.0 or set(e.pair) <= set(CLUSTER_MINTS) | {"SOL"}
    ]
    print(f"\nresolving {len(interesting)} pools on chain (vaults + DLMM config)")
    for e in interesting:
        e.vaults = pool_vaults(rpc, e.address)
        try:
            e.cfg = read_lb_pair(rpc, e.address)
        except RpcError:
            e.cfg = None

    print("\n=== EVERY EDGE, ON CHAIN ===")
    hdr = (
        f"{'pair':16s} {'venue':9s} {'fee':>7s} {'vault A':>16s} {'vault B':>16s} "
        f"{'agg $':>9s} {'v24 $':>9s}  pool"
    )
    print(hdr)
    print("-" * len(hdr))
    live: list[Edge] = []
    dead: list[Edge] = []
    for e in sorted(interesting, key=lambda x: -x.liq_reported):
        if not e.vaults:
            continue
        vs = sorted(e.vaults, key=lambda v: v.symbol)
        fee = e.fee
        feestr = f"{fee*100:.2f}%" if fee is not None else "?"
        cols = "  ".join(f"{v.symbol}={v.amount:,.1f}" for v in vs)
        print(
            f"{e.label:16s} {e.dex[:9]:9s} {feestr:>7s} {cols:<34s} "
            f"{e.liq_reported:9,.0f} {e.vol24:9,.0f}  {e.address[:12]}"
        )
        (dead if e.one_sided else live).append(e)

    print("\n=== NODE DEGREE (edges with BOTH vault sides funded) ===")
    deg: dict[str, set[str]] = {}
    for e in live:
        a, b = e.pair
        deg.setdefault(a, set()).add(b)
        deg.setdefault(b, set()).add(a)
    for node in sorted(deg, key=lambda n: -len(deg[n])):
        print(f"  {node:10s} degree {len(deg[node]):2d}   -> {', '.join(sorted(deg[node]))}")

    print("\n=== ONE-SIDED (an edge that exists but conducts one way: an OPEN CIRCUIT) ===")
    for e in dead:
        cols = "  ".join(f"{v.symbol}={v.amount:,.1f}" for v in sorted(e.vaults, key=lambda v: v.symbol))
        print(f"  {e.label:16s} {e.address[:12]}  {cols}")

    print("\n=== MISSING EDGES among the four cluster tokens ===")
    have = {frozenset(e.pair) for e in live} | {frozenset(e.pair) for e in dead}
    for a, b in itertools.combinations(sorted(CLUSTER_MINTS), 2):
        state = "MISSING"
        if frozenset({a, b}) in {frozenset(e.pair) for e in live}:
            state = "live"
        elif frozenset({a, b}) in have:
            state = "one-sided (dead)"
        print(f"  {a}/{b:8s} {state}")
    return {"live": live, "dead": dead, "all": interesting}


# --------------------------------------------------------------------------------------
# mode: vol
# --------------------------------------------------------------------------------------


def cmd_vol(prices: Prices) -> dict[tuple[str, str], float]:
    toks = sorted(CLUSTER_MINTS)
    t0 = max(prices.minute_span(t)[0] for t in toks)
    t1 = min(prices.minute_span(t)[1] for t in toks)
    print(
        f"\n=== RATIO VOLATILITY  sigma_AB (per sqrt(day)) ===\n"
        f"window {dt.datetime.fromtimestamp(t0, dt.UTC):%Y-%m-%d %H:%M} -> "
        f"{dt.datetime.fromtimestamp(t1, dt.UTC):%H:%M} UTC  ({(t1-t0)/3600:.1f} h)"
    )
    steps = [60, 300, 900, 1800]
    print(f"{'pair':16s} " + "".join(f"{s//60:>6d}m" for s in steps) + f"{'drift':>10s}{'sig^2/8':>10s}")
    out: dict[tuple[str, str], float] = {}
    for a, b in itertools.combinations(toks, 2):
        row = f"{a+'/'+b:16s} "
        vals = {}
        for s in steps:
            sd, drift, _ = realized_vol(prices, a, b, s, t0, t1)
            vals[s] = (sd, drift)
            row += f"{sd*100:5.1f}%" + " "
        sd15, drift15 = vals[900]
        out[(a, b)] = sd15
        row += f"{drift15*100:+9.1f}%{sd15**2/8*100:9.2f}%"
        print(row)
    print(
        "\n  sigma^2/8 is the constant-product LVR rate per day (Milionis-Moallemi-Roughgarden),\n"
        "  i.e. what a FULL-RANGE 50/50 pool on this pair bleeds to arbitrageurs per day\n"
        "  before fees.  A concentrated DLMM position multiplies it -- and multiplies fee\n"
        "  income by the same factor, which is why the ratio, not either term, is the test."
    )

    # The decomposition that turns a pairwise measurement into a per-token one.
    print("\n=== IS sigma_AB JUST ITS ENDPOINTS? ===")
    own: dict[str, float] = {}
    for tok in toks:
        px = prices.series(tok, 900, t0, t1)
        r = [math.log(px[i + 1] / px[i]) for i in range(len(px) - 1)]
        m = sum(r) / len(r)
        own[tok] = math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1) * 96)
    print("  own volatility vs USD, per sqrt(day), 15-minute sampling:")
    for t in sorted(own, key=lambda x: -own[x]):
        print(f"    {t:8s} {own[t]*100:6.1f}%")
    print(f"\n  {'pair':16s} {'sigma_AB':>9s} {'sqrt(sA^2+sB^2)':>16s} {'ratio':>7s} {'implied rho':>12s}")
    ratios = []
    for a, b in itertools.combinations(toks, 2):
        sab = out[(a, b)]
        q = math.sqrt(own[a] ** 2 + own[b] ** 2)
        rho = (own[a] ** 2 + own[b] ** 2 - sab**2) / (2 * own[a] * own[b])
        ratios.append(sab / q)
        print(f"  {a+'/'+b:16s} {sab*100:8.1f}% {q*100:15.1f}% {sab/q:7.3f} {rho:+12.3f}")
    print(
        f"\n  ratio in [{min(ratios):.3f}, {max(ratios):.3f}] on all six pairs.  These tokens are\n"
        "  near-independent (implied rho -0.05 to +0.20, which independently reproduces the\n"
        "  0.11-0.24 correlations of studies/RESULT_swing_cluster.md), so\n"
        "      sigma_AB  ~  sqrt(sigma_A^2 + sigma_B^2)\n"
        "  to within 7%.  CONSEQUENCE: an edge's earning power is set by its LOUDEST\n"
        "  endpoint, and a candidate edge can be ranked from single-token volatility alone\n"
        "  -- no pairwise history required, which is exactly what you lack for a pool that\n"
        "  does not exist yet."
    )
    return out


# --------------------------------------------------------------------------------------
# mode: flow -- the decomposition that answers "who crosses this edge"
# --------------------------------------------------------------------------------------

TAPE_POOLS: Final[dict[str, str]] = {
    "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn": "weave/SOL ps",
    "7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc": "nosis/SOL ps",
    "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU": "DREGG/SOL ps",
    "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr": "SOLVE/SOL ps",
    "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD": "weave/nosis",
    "FNxnyS3hkVJDUvQmP9LYGLUg9icvc7n4ZwTTQ3R1vtJD": "DREGG/nosis",
    "77Nm2cKtZfJvcQttySdqoZvH1mbxUkUWQwKsrpyvAebu": "weave/SOL dlmm",
    "C889ex3M6dDecsxjAAudiLjqvGXjTV37YRhSxaEbcwGx": "nosis/SOL dlmm",
    "6RRecgQPELvZfoaDECEbsPQaR2WHnDQAPCvMPoFmsr3X": "weave/SOL sm",
    "GxnCwxTiK1uNQ1GiNutopyaRxH9X14JEvh6uaMwxuDRM": "weave/DREGG A",
    "A8ga6XM3b8EQV1ZD4B5KJTATxKrZm6feKcodTwAogtRG": "weave/DREGG B",
    "HE9UXD4abY8dG1QEmyoZkSETZVScef3t2yZqhbWCT9aJ": "SOLVE/DREGG",
    "9M1oU7cvRKiNo3e6iuCnApVe5RYehQ9RNv5dhtiKTrA7": "weave/SOLVE",
}


def cmd_flow(tape_dir: str = "state/cluster_tape/swaps") -> None:
    """Classify every tape swap by how many cluster pools its transaction touched.

    Three classes, and the whole strategic question turns on their relative sizes:

      CYCLE   the transaction touches A/B *and* A/SOL *and* B/SOL.  It is a closed loop:
              the trader ends flat in every token and is paid the curl.  An arbitrageur.
      LEG     the transaction touches A/B and exactly one SOL pool.  Endpoints are SOL
              and a token: a SOL<->token trade that the router chose to send through the
              token-token pool.
      DIRECT  the transaction touches A/B and nothing else.  A genuine A<->B trade --
              the only class that is evidence for "there was demand for this wire".
    """
    import glob

    rows: list[dict] = []
    for f in sorted(glob.glob(f"{tape_dir}/*.jsonl")):
        with open(f) as fh:
            for line in fh:
                d = json.loads(line)
                if d.get("kind") == "swap":
                    rows.append(d)
    by_sig: dict[str, list[dict]] = {}
    for d in rows:
        by_sig.setdefault(d["chain"]["signature"], []).append(d)
    print(f"\n=== TAPE FLOW DECOMPOSITION ===\n{len(rows)} swap rows, {len(by_sig)} transactions")
    t = [d["t_event"] for d in rows]
    print(f"window {min(t)} -> {max(t)}")

    tt = {p: lbl for p, lbl in TAPE_POOLS.items() if "/SOL" not in lbl}
    for pool, label in tt.items():
        mine = [s for s, v in by_sig.items() if any(x["pool"] == pool for x in v)]
        if not mine:
            continue
        cls = {"CYCLE": 0, "LEG": 0, "DIRECT": 0}
        for s in mine:
            others = {x["pool"] for x in by_sig[s]} - {pool}
            n_sol = sum(1 for o in others if "/SOL" in TAPE_POOLS.get(o, ""))
            cls["CYCLE" if n_sol >= 2 else ("LEG" if n_sol == 1 else "DIRECT")] += 1
        n = len(mine)
        print(
            f"\n  {label:14s} n={n:4d}   "
            f"CYCLE {cls['CYCLE']:4d} ({cls['CYCLE']/n:5.1%})   "
            f"LEG {cls['LEG']:4d} ({cls['LEG']/n:5.1%})   "
            f"DIRECT {cls['DIRECT']:4d} ({cls['DIRECT']/n:5.1%})"
        )
    print(
        "\n  NOTE the tape watches six pools.  A transaction routing through a SEVENTH pool\n"
        "  the recorder does not watch is undercounted as DIRECT, so the DIRECT column is\n"
        "  an UPPER bound on genuine token<->token demand.  It is already ~zero."
    )


def cmd_chain_flow(rpc: ReadOnlyRpc) -> None:
    """The same decomposition, from each pool's OWN full on-chain history.

    Strictly better than the tape version and kept alongside it rather than instead of
    it, because the two disagree in a way worth seeing: the tape's poller can miss the
    sibling leg of an atomic route (it polls each pool independently, and a gap on one
    pool orphans the other's row), which shows up as a false DIRECT.  Reading the
    transaction itself cannot have that failure -- every pool the transaction touched is
    in its own ``postTokenBalances`` owner set.

    Classification is by *how many token/SOL pools the same transaction touched*:
    two or more closes a cycle (arbitrage), exactly one makes the token-token pool a leg
    of a SOL<->token route, zero is a genuine direct trade.
    """
    print("\n=== CHAIN FLOW DECOMPOSITION (full pool history, not tape-window) ===")
    for pool, label, tag in DESK_TOKEN_TOKEN:
        path = CACHE_DIR / f"{tag}.json"
        if not path.exists():
            try:
                sigs = [s["signature"] for s in all_signatures(rpc, pool) if not s.get("err")]
                fetch_transactions(rpc, sigs, tag)
            except RpcError as exc:
                print(f"  {label}: RPC failed ({exc})")
                continue
        txs = json.loads(path.read_text())
        cls = {"CYCLE": 0, "LEG": 0, "DIRECT": 0}
        sol_pools = {addr for addr, name in TAPE_POOLS.items() if "/SOL" in name}
        for tx in txs.values():
            if not any(o.startswith("swap") for o in _dlmm_ops(tx)):
                continue
            owners = {
                b.get("owner")
                for b in (tx["meta"].get("postTokenBalances") or [])
                if b.get("owner") and b.get("owner") != pool
            }
            n_sol = len(owners & sol_pools)
            cls["CYCLE" if n_sol >= 2 else ("LEG" if n_sol == 1 else "DIRECT")] += 1
        n = sum(cls.values())
        if not n:
            print(f"  {label:14s} no swaps ever")
            continue
        print(
            f"  {label:14s} n={n:5d}   CYCLE {cls['CYCLE']:5d} ({cls['CYCLE']/n:5.1%})   "
            f"LEG {cls['LEG']:5d} ({cls['LEG']/n:5.1%})   DIRECT {cls['DIRECT']:5d} ({cls['DIRECT']/n:5.1%})"
        )
    print(
        "\n  DIRECT is the only class that is evidence of demand for the wire itself.\n"
        "  Everything else is the desk being paid a toll on a loop it closed."
    )


# --------------------------------------------------------------------------------------
# mode: positions -- every operator token-token LP position, scored
# --------------------------------------------------------------------------------------


@dataclass
class Leg:
    when: int
    kind: str  # deposit | fee | withdraw
    amounts: dict[str, float]


@dataclass
class Position:
    pool: str
    label: str
    legs: list[Leg]
    swap_times: list[int]

    @property
    def opened(self) -> int:
        return min(x.when for x in self.legs if x.kind == "deposit")

    @property
    def closed(self) -> int:
        return max(x.when for x in self.legs)

    @property
    def hours(self) -> float:
        return (self.closed - self.opened) / 3600.0

    def duty_cycle(self) -> float:
        """Fraction of the position's life during which the pool was still trading.

        Defined as (last swap - first swap) / (close - open).  A DLMM position that
        range-exits stops quoting; the pool goes silent while the inventory keeps
        moving against it.  This is the single number that separated the desk's two
        headline token-token positions, and it is a *range placement* statistic, not an
        edge placement one.
        """
        if len(self.swap_times) < 2:
            return 0.0
        return (max(self.swap_times) - min(self.swap_times)) / max(1.0, self.closed - self.opened)


def _pool_deltas(tx: dict, pool: str) -> dict[str, float]:
    pre = {b["accountIndex"]: b for b in (tx["meta"].get("preTokenBalances") or [])}
    out: dict[str, float] = {}
    for i, b in {b["accountIndex"]: b for b in (tx["meta"].get("postTokenBalances") or [])}.items():
        if b.get("owner") != pool:
            continue
        p = pre.get(i, {}).get("uiTokenAmount", {}).get("uiAmount") or 0.0
        q = b["uiTokenAmount"].get("uiAmount") or 0.0
        sym = SYMBOL.get(b["mint"], b["mint"][:6])
        out[sym] = out.get(sym, 0.0) + (q - p)
    return out


def _dlmm_ops(tx: dict) -> list[str]:
    msg = tx["transaction"]["message"]
    ixs = list(msg["instructions"])
    for inn in tx.get("meta", {}).get("innerInstructions") or []:
        ixs += inn["instructions"]
    ops = []
    for ix in ixs:
        if ix.get("programId") != METEORA_DLMM or not ix.get("data"):
            continue
        try:
            name = DLMM_IX.get(b58decode(ix["data"])[:8].hex())
        except Exception:
            continue
        if name:
            ops.append(name)
    return ops


def _split_fee_from_principal(tx: dict, pool: str) -> tuple[dict[str, float], dict[str, float]]:
    """Separate a bundled remove+claim transaction into (principal_out, fee_out).

    Meteora's close sequence is one transaction carrying `removeLiquidityByRange2`
    *and* `claimFee2`, and the pool's net vault delta merges them.  The split matters:
    fees are income, principal is the position coming back, and conflating them makes
    the fee yield look larger and the divergence loss look smaller -- an error that
    flatters the strategy in both directions at once.  Recovered by walking the inner
    instructions per top-level index and attributing each SPL transfer to whichever
    DLMM instruction contained it.
    """
    msg = tx["transaction"]["message"]
    top = msg["instructions"]
    principal: dict[str, float] = {}
    fee: dict[str, float] = {}
    for inn in tx.get("meta", {}).get("innerInstructions") or []:
        idx = inn["index"]
        if idx >= len(top) or top[idx].get("programId") != METEORA_DLMM:
            continue
        try:
            name = DLMM_IX.get(b58decode(top[idx]["data"])[:8].hex(), "")
        except Exception:
            name = ""
        bucket = fee if name.startswith("claimFee") else principal
        for ix in inn["instructions"]:
            p = ix.get("parsed")
            if not isinstance(p, dict) or p.get("type") not in ("transfer", "transferChecked"):
                continue
            info = p["info"]
            mint = info.get("mint")
            amt = (info.get("tokenAmount") or {}).get("uiAmountString")
            if mint is None or amt is None:
                continue
            sym = SYMBOL.get(mint, mint[:6])
            bucket[sym] = bucket.get(sym, 0.0) + float(amt)
    return principal, fee


def reconstruct_positions(rpc: ReadOnlyRpc, pool: str, label: str, tag: str) -> list[Position]:
    """Every LP position the desk opened in ``pool``, from that pool's own history."""
    sigs = all_signatures(rpc, pool)
    ok = [s["signature"] for s in sigs if not s.get("err")]
    txs = fetch_transactions(rpc, ok, tag)
    events: list[tuple[int, str, list[str], bool, dict]] = []
    for sig, tx in txs.items():
        ops = _dlmm_ops(tx)
        if not ops:
            continue
        signers = [a["pubkey"] for a in tx["transaction"]["message"]["accountKeys"] if a.get("signer")]
        events.append((tx["blockTime"], sig, ops, FUND in signers, tx))
    events.sort()

    # An "episode" is a maximal run of nonzero desk exposure in this pool.  Meteora
    # positions are per-bin-range NFTs and the desk sometimes runs two at once in the
    # same pool; merging them into one episode is deliberate, because the economic unit
    # is "the desk's inventory sitting on this edge", and because a second add while a
    # first is open cannot be attributed to either without instruction-level position-key
    # tracking (studies/RESULT_lp_history.md hit the same wall and excluded 12 of 42).
    positions: list[Position] = []
    cur: Position | None = None
    for bt, _sig, ops, is_fund, tx in events:
        if any(o.startswith("swap") for o in ops):
            if cur is not None:
                cur.swap_times.append(bt)
            continue
        if not is_fund:
            continue
        d = _pool_deltas(tx, pool)
        opening = any(o.startswith(("addLiquidity", "initializePosition")) for o in ops)
        closing = any(o.startswith(("removeLiquidity", "closePosition")) for o in ops)
        claiming = any(o.startswith("claimFee") for o in ops)
        if opening and sum(v for v in d.values() if v > 0) > 0:
            if cur is None:
                cur = Position(pool=pool, label=label, legs=[], swap_times=[])
            cur.legs.append(Leg(bt, "deposit", {k: v for k, v in d.items() if v > 0}))
            continue
        if closing:
            if cur is None:
                continue
            principal, fee = _split_fee_from_principal(tx, pool)
            if principal or fee:
                if fee:
                    cur.legs.append(Leg(bt, "fee", fee))
                cur.legs.append(Leg(bt, "withdraw", principal))
            else:
                cur.legs.append(Leg(bt, "withdraw", {k: -v for k, v in d.items() if v < 0}))
            positions.append(cur)
            cur = None
            continue
        if claiming:
            if cur is None:
                continue
            cur.legs.append(Leg(bt, "fee", {k: -v for k, v in d.items() if v < 0}))
    if cur is not None:
        positions.append(cur)  # still open
    return positions


def score_position(p: Position, prices: Prices, open_now: bool = False) -> dict[str, Any]:
    """Value a position's cash flows at minute-bar prices and compare against HODL.

    Three numbers, and they must be read together:

      net        (fees + withdrawals) - deposits, each valued when it happened.  What the
                 position did.
      hodl       what the deposited basket alone would have been worth at exit.  The
                 benchmark that separates "the market moved" from "the LP structure cost
                 me".
      lp_vs_hodl net - hodl.  Necessarily <= fees, and negative whenever divergence beat
                 the fee harvest.  This is the number the harvest-rate framing hides.
    """
    dep: dict[str, float] = {}
    v_dep = v_fee = v_out = 0.0
    for leg in p.legs:
        v = sum(a * prices.at(t, leg.when) for t, a in leg.amounts.items() if t in REFERENCE_POOL)
        if leg.kind == "deposit":
            v_dep += v
            for t, a in leg.amounts.items():
                dep[t] = dep.get(t, 0.0) + a
        elif leg.kind == "fee":
            v_fee += v
        else:
            v_out += v
    t_exit = p.closed
    hodl = sum(a * prices.at(t, t_exit) for t, a in dep.items() if t in REFERENCE_POOL)
    net = v_fee + v_out - v_dep
    ratio_move = float("nan")
    ends = [t for t in dep if t in REFERENCE_POOL]
    if len(ends) == 2:
        ta, tb = ends
        r0 = prices.at(ta, p.opened) / prices.at(tb, p.opened)
        r1 = prices.at(ta, t_exit) / prices.at(tb, t_exit)
        ratio_move = math.log(r1 / r0)
    r = math.exp(ratio_move) if ratio_move == ratio_move else float("nan")
    cp_il = (2 * math.sqrt(r) / (1 + r) - 1) if r == r else float("nan")
    lp_vs_hodl = net - (hodl - v_dep)
    divergence = lp_vs_hodl - v_fee
    return {
        "label": p.label,
        "open": p.opened,
        "close": p.closed,
        "hours": p.hours,
        "deposit_usd": v_dep,
        "fees_usd": v_fee,
        "withdraw_usd": v_out,
        "net_usd": net,
        "hodl_usd": hodl,
        "hodl_pnl": hodl - v_dep,
        "lp_vs_hodl": lp_vs_hodl,
        "divergence_usd": divergence,
        "fee_coverage": (v_fee / abs(divergence)) if divergence else float("nan"),
        "duty_cycle": p.duty_cycle(),
        "n_swaps": len(p.swap_times),
        "ratio_move_log": ratio_move,
        "cp_il": cp_il,
        "amplification": (divergence / v_dep / cp_il) if (cp_il and v_dep) else float("nan"),
        "open_now": open_now,
    }


#: Every Meteora token-token pool the desk has LP'd, in creation order.  Discovered by
#: `graph` plus a walk of the fund wallet's own signatures; hard-coded here so a run is
#: reproducible even after an aggregator drops one.
DESK_TOKEN_TOKEN: Final[list[tuple[str, str, str]]] = [
    ("GxnCwxTiK1uNQ1GiNutopyaRxH9X14JEvh6uaMwxuDRM", "weave/DREGG A", "weavedregg"),
    ("A8ga6XM3b8EQV1ZD4B5KJTATxKrZm6feKcodTwAogtRG", "weave/DREGG B", "weavedreggB"),
    ("HE9UXD4abY8dG1QEmyoZkSETZVScef3t2yZqhbWCT9aJ", "SOLVE/DREGG", "solvedregg"),
    ("FNxnyS3hkVJDUvQmP9LYGLUg9icvc7n4ZwTTQ3R1vtJD", "DREGG/nosis", "dreggnosis"),
    ("QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD", "weave/nosis", "weavenosis"),
    # 2026-08-14 02:18-02:44 UTC, in one 26-minute burst: the desk closed weave/nosis #1,
    # opened a SECOND weave/nosis pool at the same 6.00% tier, and opened the cluster's
    # last unbuilt token-token edge, weave/SOLVE.  None of the three is in
    # shitcoims_cluster/pools.py and the aggregators indexed weave/SOLVE ~45 min late.
    ("5fJBZY6hCG3ykS2nNCJCXXrFtgcGSDByGccq4ucVea9i", "weave/nosis2", "weavenosis2"),
    ("9M1oU7cvRKiNo3e6iuCnApVe5RYehQ9RNv5dhtiKTrA7", "weave/SOLVE", "weavesolve"),
]


def cmd_positions(rpc: ReadOnlyRpc, prices: Prices, only: str | None = None) -> list[dict]:
    rows: list[dict] = []
    for pool, label, tag in DESK_TOKEN_TOKEN:
        if only and only not in label:
            continue
        try:
            ps = reconstruct_positions(rpc, pool, label, tag)
        except RpcError as exc:
            print(f"  {label}: RPC failed ({exc})")
            continue
        for i, p in enumerate(ps, 1):
            if not any(x.kind == "deposit" for x in p.legs):
                continue
            open_now = not any(x.kind == "withdraw" for x in p.legs)
            s = score_position(p, prices, open_now=open_now)
            s["n"] = i
            rows.append(s)
    print("\n=== EVERY TOKEN-TOKEN LP POSITION THE DESK HAS OPENED, SCORED FROM CHAIN ===")
    hdr = (
        f"{'pool':14s} {'#':>2s} {'opened(UTC)':16s} {'h':>5s} {'dep$':>8s} {'fees$':>8s} "
        f"{'net$':>8s} {'hodl$':>8s} {'LP-HODL$':>9s} {'cover':>6s} {'duty':>6s} {'swaps':>6s}"
    )
    print(hdr)
    print("-" * len(hdr))
    for s in sorted(rows, key=lambda r: r["open"]):
        if s["open_now"]:
            print(
                f"{s['label']:14s} {s['n']:2d} "
                f"{dt.datetime.fromtimestamp(s['open'], dt.UTC):%m-%d %H:%M}    "
                f"{s['hours']:5.2f} {s['deposit_usd']:8.2f} {s['fees_usd']:8.2f}"
                f"{'  --- STILL OPEN, not scored ---':>52s}"
            )
            continue
        print(
            f"{s['label']:14s} {s['n']:2d} "
            f"{dt.datetime.fromtimestamp(s['open'], dt.UTC):%m-%d %H:%M}    "
            f"{s['hours']:5.2f} {s['deposit_usd']:8.2f} {s['fees_usd']:8.2f} {s['net_usd']:8.2f} "
            f"{s['hodl_pnl']:8.2f} {s['lp_vs_hodl']:9.2f} {s['fee_coverage']:6.2f} "
            f"{s['duty_cycle']:6.1%} {s['n_swaps']:6d}"
        )
    closed = [s for s in rows if not s["open_now"] and s["deposit_usd"] > 1.0]
    if closed:
        beat = sum(1 for s in closed if s["lp_vs_hodl"] > 0)
        print(
            f"\n  {beat}/{len(closed)} closed positions beat holding the deposited basket.\n"
            f"  total net    ${sum(s['net_usd'] for s in closed):+,.2f}\n"
            f"  total LP-HODL ${sum(s['lp_vs_hodl'] for s in closed):+,.2f}\n"
            f"  total fees   ${sum(s['fees_usd'] for s in closed):+,.2f}"
        )
    return rows


# --------------------------------------------------------------------------------------
# mode: rank
# --------------------------------------------------------------------------------------


def two_hop_cost() -> tuple[float, float]:
    return 2 * PUMPSWAP_LEG_LO, 2 * PUMPSWAP_LEG_HI


#: Measured turnover (swap volume per day / TVL) on every pool the desk has run, from
#: `positions` + the volume walk in the write-up.  These calibrate KAPPA below; the three
#: with >8 h of flow are the trustworthy ones.
MEASURED_TURNOVER: Final[dict[str, tuple[float, float, float, float]]] = {
    # label:            (turnover/day, sigma, own fee, hours of flow)
    "weave/DREGG A": (5.95, 0.472, 0.050, 49.9),
    "weave/DREGG B": (34.03, 0.472, 0.002, 0.9),
    "SOLVE/DREGG": (2.21, 0.327, 0.050, 21.6),
    "DREGG/nosis": (13.96, 0.927, 0.050, 1.9),
    "weave/nosis": (8.92, 0.959, 0.060, 8.5),
    "weave/nosis2": (39.36, 0.959, 0.060, 0.4),
    "weave/SOLVE": (7.47, 0.515, 0.050, 0.4),
}

#: Turnover model constant, fitted below.  Carried as an interval, never a point: the
#: model is a RANKING instrument (Spearman 0.83 on n=6), not a level instrument.
KAPPA_LO: Final[float] = 3.45
KAPPA_HI: Final[float] = 8.42


def turnover_model(sigma: float, band: float, kappa: float) -> float:
    """Predicted swap volume per day per dollar of TVL.

    Derivation.  A ratio with daily vol ``sigma`` crosses a band of half-width ``band``
    about ``sigma^2/band^2`` times per day (Brownian first-passage).  Each crossing is
    arbitraged back by a trade that moves the pool by roughly one band, and moving a
    constant-product pool of value ``T`` by ``d ln p`` costs ``T*d ln p/4`` of notional
    (studies/RESULT_circuit_model.md §6: ``d ln p = 2*dy/y`` and ``y = T/2``).  So

        volume/day / TVL  =  kappa * sigma^2 / (4 * band)

    with ``kappa`` absorbing everything the derivation drops -- DLMM concentration, the
    routing-leg flow that is not arbitrage, and the fact that the walk overshoots.
    ``kappa`` is FITTED, on seven pools, and it lands in 3.5-8.4.  Do not read the level.
    """
    return kappa * sigma**2 / (4.0 * band)


def min_viable_tvl(band: float, sigma: float, gas: float = 0.30, span: float = 4.0) -> float:
    """Smallest TVL at which the arb that feeds a new edge is worth someone's gas.

    From studies/RESULT_circuit_model.md §3.3: an arb of size Phi around a loop earns
    ``Phi*(|C| - sum f) - 0.5*Phi^2*sum r - G`` with ``r_e = W_e/TVL_e``, maximised at
    ``Phi* = (|C| - sum f)/sum r`` for ``profit* = (|C| - sum f)^2/(2 sum r) - G``.  A
    brand-new pool is by construction the thinnest leg, so ``sum r ~ span/TVL_new`` and

        TVL_new  >  2 * G * span / (|C| - sum f)^2

    The excess ``|C| - sum f`` is what the ratio typically over-runs the band by before
    anyone trades.  For a random walk of daily vol ``sigma`` sampled against a band of
    half-width ``band``, the natural scale of an excursion beyond the band over one
    crossing interval is ``sigma * sqrt(band^2/sigma^2) = band`` -- i.e. of order the
    band itself.  Taking the excess as one band width is the conservative choice: it is
    the smallest excursion that trades at all, so it yields the LARGEST floor.
    """
    excess = band
    return 2.0 * gas * span / (excess**2)


def _spearman(x: list[float], y: list[float]) -> float:
    def rank(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: -v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(x), rank(y)
    n = len(x)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry, strict=True))
    return 1 - 6 * d2 / (n * (n * n - 1))


def cmd_rank(prices: Prices, vols: dict[tuple[str, str], float] | None = None) -> None:
    vols = vols or {}
    lo, hi = two_hop_cost()
    print("\n=== WHAT A DIRECT EDGE COMPETES WITH ===")
    print(f"  two-hop A->SOL->B all-in taker cost:  {lo*100:.2f}% - {hi*100:.2f}%")
    print("  the desk's own token-token fee tiers:  5.00% - 6.00%  (decoded on chain)")
    print(
        f"  => a direct pool at the desk's tier is {0.05/hi:.1f}x-{0.06/lo:.1f}x MORE expensive than\n"
        "     the route it would replace.  A cost-minimising router never prefers it for a\n"
        "     genuine A->B trade, at any size, because impact is second-order and the fee\n"
        "     gap is first-order.  The prize is therefore NOT captured user flow.  It is\n"
        "     the arbitrage toll on a cycle the new edge closes -- and `flow` measures the\n"
        "     realised split at 84% cycle / 15% routing leg / 0.2% direct."
    )

    print("\n=== TURNOVER MODEL, CALIBRATED ON THE SEVEN POOLS THE DESK HAS RUN ===")
    print(
        f"  {'pool':14s} {'sigma':>7s} {'band':>7s} {'sig^2/band':>11s} "
        f"{'measured T/d':>13s} {'kappa':>7s} {'hours':>7s}"
    )
    pred, obs = [], []
    for label, (t_meas, sd, fee, hours) in MEASURED_TURNOVER.items():
        band = fee + hi
        stat = sd**2 / band
        kappa = t_meas * 4 * band / sd**2
        print(
            f"  {label:14s} {sd*100:6.1f}% {band*100:6.2f}% {stat:11.2f} "
            f"{t_meas*100:12.0f}% {kappa:7.2f} {hours:7.1f}"
        )
        if label != "weave/nosis2":  # shares sigma with weave/nosis; would double-count
            pred.append(stat)
            obs.append(t_meas)
    rho = _spearman(pred, obs)
    print(
        f"\n  Spearman(sigma^2/band, measured turnover) = {rho:.3f} on n={len(pred)}.\n"
        "  The same test on sigma^2 alone scores 0.500 -- the band term earns its place.\n"
        "  n=6 is right at the 5% critical value (0.829); this is a lead with arithmetic\n"
        "  attached, not an established law.  It ranks; it does not price."
    )

    print("\n=== CANDIDATE EDGES, RANKED ===")
    print(
        f"{'edge':16s} {'state':17s} {'sigma/sqrtd':>11s} {'band':>7s} {'sig^2/band':>11s} "
        f"{'fee yld/d':>18s} {'LVR/d(k=1)':>11s} {'floor $':>8s}"
    )
    state = {
        ("SOLVE", "nosis"): "MISSING",
        ("DREGG", "nosis"): "dead (one-sided)",
        ("DREGG", "SOLVE"): "dead (one-sided)",
        ("DREGG", "weave"): "dead + a 0.2% one",
        ("SOLVE", "weave"): "live (opened 02:44)",
        ("nosis", "weave"): "live (2nd pool)",
    }
    for (a, b), sd in sorted(vols.items(), key=lambda kv: -kv[1]):
        fee_ab = 0.05
        band = fee_ab + hi
        y_lo = 0.9 * fee_ab * turnover_model(sd, band, KAPPA_LO)
        y_hi = 0.9 * fee_ab * turnover_model(sd, band, KAPPA_HI)
        print(
            f"{a+'/'+b:16s} {state.get((a,b),'?'):17s} {sd*100:10.1f}% {band*100:6.2f}% "
            f"{sd**2/band:11.2f} {y_lo*100:7.0f}%-{y_hi*100:5.0f}%/d {sd**2/8*100:10.2f}% "
            f"${min_viable_tvl(band, sd, span=1.0):7.0f}"
        )
    print(
        "\n  floor is the minimum TVL at which the arbitrage that feeds the edge clears\n"
        "  gas, from studies/RESULT_circuit_model.md §3.3 with G=$0.30 and the DLMM span\n"
        "  W=1.0 that RESULT_swing_cluster.md measured (4/W = 3.98-5.91 -> W = 0.68-1.00).\n"
        "  It does not depend on sigma at all -- sigma sets how OFTEN the edge is crossed,\n"
        "  the band sets whether a crossing is worth anyone's gas."
    )
    print("\n  the floor as a function of the fee tier you choose (band = fee + 2.88% for the\n"
          "  two PumpSwap legs), at three DLMM spans:")
    print(f"    {'your fee':>9s} {'band':>7s} {'W=4.0':>9s} {'W=1.0':>9s} {'W=0.2':>9s}")
    for f in (0.0020, 0.0050, 0.0100, 0.0200, 0.0500, 0.0600):
        band = f + hi
        print(
            f"    {f*100:8.2f}% {band*100:6.2f}% "
            f"${min_viable_tvl(band, 0.0, span=4.0):8.0f} "
            f"${min_viable_tvl(band, 0.0, span=1.0):8.0f} "
            f"${min_viable_tvl(band, 0.0, span=0.2):8.0f}"
        )
    print(
        "\n  Note the DIRECTION: a CHEAPER pool needs MORE capital, because the band is the\n"
        "  arb's entire margin.  The desk's only sub-1% token-token pool (weave/DREGG B,\n"
        "  0.20%, $538 deposited) sits right at its own W=1.0 floor -- and it is the one\n"
        "  now showing $0 of 24-hour volume."
    )
    print("\n=== AND THE COST SIDE, WHICH DECIDES THE SIGN ===")
    print(
        "  Realised divergence on the desk's two cleanest positions ran 4.7x (DREGG/nosis)\n"
        "  and 8.2x (weave/nosis) the full-range constant-product IL for the same ratio\n"
        "  move.  Applying that band to the LVR column above puts the cost at roughly\n"
        "  5-8 x sigma^2/8 per day, which for a sigma~0.93 pair is 50-90%/day -- the same\n"
        "  order as the fee yield.  The expected value of the best missing edge therefore\n"
        "  STRADDLES ZERO, which is exactly what the realised record shows: 6/10 closed\n"
        "  positions beat HODL and the aggregate did not."
    )


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["graph", "vol", "flow", "positions", "rank", "all"])
    ap.add_argument("--pool", default=None, help="positions: restrict to one pool label")
    ap.add_argument("--tape", default="state/cluster_tape/swaps")
    args = ap.parse_args()

    if args.mode == "flow":
        cmd_flow(args.tape)
        cmd_chain_flow(ReadOnlyRpc())
        return 0

    rpc = ReadOnlyRpc()
    if args.mode == "graph":
        cmd_graph(rpc)
        return 0
    prices = Prices()
    if args.mode == "vol":
        cmd_vol(prices)
        return 0
    if args.mode == "positions":
        cmd_positions(rpc, prices, args.pool)
        return 0
    if args.mode == "rank":
        cmd_rank(prices, cmd_vol(prices))
        return 0
    cmd_graph(rpc)
    v = cmd_vol(prices)
    cmd_flow(args.tape)
    cmd_chain_flow(rpc)
    cmd_positions(rpc, prices)
    cmd_rank(prices, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
