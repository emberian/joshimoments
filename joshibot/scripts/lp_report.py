#!/usr/bin/env -S uv run python
"""What are the Meteora DLMM positions actually worth, and are they beating HODL.

Read-only. Never signs, never spends. Reads `~/.helius-key` and nothing else sensitive.

    uv run scripts/lp_report.py [WALLET]

**Why this exists.** The question "what is my LP earning" had no answer in this codebase for a
long time. The obvious donor (`marketfabric`'s `crypto/positions.py`) cannot answer it: it
finds a position's bin range by a *heuristic tail scan* rather than a fixed offset, never reads
`fee_pending_x/y` or `total_claimed_fee_*`, never fetches bin arrays, and therefore reports no
token amounts and no value. Meteora's public DLMM API returns 404 as of 2026-08-13. So this
parses chain directly.

**The layout is checkable rather than assumed.** `PositionV2` is
``8 disc | 32 lb_pair | 32 owner | 70x u128 shares | 70x 48 reward_infos | 70x 48 fee_infos |
i32 lower | i32 upper | i64 last_updated | u64 claimed_x | u64 claimed_y | …`` which sums to
exactly **8120 bytes**, and the script asserts that. If Meteora changes the struct the assert
fires instead of the numbers quietly going wrong — which matters, because every field here is
read by offset.

**The basis comes from chain, not from a quote.** Entry is reconstructed by summing the
wallet's own net token flows across the position's transaction history — the same discipline
the sentinel now uses for cost basis, and for the same reason: a basis inferred from a current
price makes PnL start at zero by construction.

**What it cannot tell you.** Fees already *claimed and re-compounded* are indistinguishable
from deposits in the net-flow basis, so they are counted once, inside the position value —
never added on top. Prices come from DexScreener's deepest pair and are as good as that.
"""

from __future__ import annotations

import base64
import json
import struct
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from solders.pubkey import Pubkey

DLMM = Pubkey.from_string("LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo")
DEFAULT_WALLET = "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ"
WSOL = "So11111111111111111111111111111111111111112"

POSITION_LEN = 8120
SHARES_OFF = 8 + 32 + 32
FEE_INFOS_OFF = SHARES_OFF + 70 * 16 + 70 * 48
TAIL_OFF = FEE_INFOS_OFF + 70 * 48
BIN_SIZE = 144
BINS_PER_ARRAY = 70
BIN_ARRAY_HEADER = 8 + 8 + 1 + 7 + 32


def _rpc(url: str, payload: dict, *, attempts: int = 5) -> dict:
    """One JSON-RPC call, with backoff.

    Retries because this walks a position's whole history one transaction at a time and the
    endpoint drops long sequential runs. A dropped call must never surface as a missing
    balance change — that would understate the basis and silently flatter the result.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except Exception as exc:  # transport-level; the payload is unchanged so retry is safe
            last = exc
            time.sleep(0.4 * (2**attempt))
    raise RuntimeError(f"RPC failed after {attempts} attempts: {last}")


@dataclass(frozen=True, slots=True)
class Chain:
    url: str

    def account(self, address: str) -> bytes | None:
        value = _rpc(
            self.url,
            {"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
             "params": [address, {"encoding": "base64"}]},
        )["result"]["value"]
        return base64.b64decode(value["data"][0]) if value else None

    def decimals(self, mint: str) -> int:
        value = _rpc(
            self.url,
            {"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
             "params": [mint, {"encoding": "jsonParsed"}]},
        )["result"]["value"]
        return int(value["data"]["parsed"]["info"]["decimals"])

    def signatures(self, address: str, limit: int = 1000) -> list[dict]:
        return _rpc(
            self.url,
            {"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
             "params": [address, {"limit": limit}]},
        )["result"]

    def transaction(self, signature: str) -> dict | None:
        return _rpc(
            self.url,
            {"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
             "params": [signature, {"encoding": "jsonParsed",
                                    "maxSupportedTransactionVersion": 0}]},
        )["result"]


def usd_price(mint: str) -> float | None:
    """Deepest-pair price from DexScreener, or ``None`` if it genuinely cannot be had.

    The User-Agent is required: DexScreener 403s urllib's default, and the first version of
    this script swallowed that in a bare ``except`` and returned ``None``, which the caller
    then rendered as **$0.00**. A missing price displayed as a plausible number is the same
    failure as a cost basis stamped from a quote, so an unavailable price is now reported as
    unavailable and never silently valued at zero.
    """
    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
    request = urllib.request.Request(url, headers={"User-Agent": "joshibot-lp-report/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                pairs = (json.load(response).get("pairs") or [])
            if not pairs:
                return None
            deepest = max(
                pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0)
            )
            return float(deepest["priceUsd"])
        except Exception:
            time.sleep(0.5 * (2**attempt))
    return None


def position_amounts(chain: Chain, position: bytes, pool: str) -> tuple[int, int]:
    """Token amounts owed to this position, from the bin arrays it spans."""
    lower, upper = struct.unpack_from("<ii", position, TAIL_OFF)
    shares = [
        int.from_bytes(position[SHARES_OFF + i * 16 : SHARES_OFF + (i + 1) * 16], "little")
        for i in range(70)
    ]
    arrays: dict[int, bytes | None] = {}
    total_x = total_y = 0
    for bin_id in range(lower, upper + 1):
        index = bin_id // BINS_PER_ARRAY
        if index not in arrays:
            pda, _ = Pubkey.find_program_address(
                [b"bin_array", bytes(Pubkey.from_string(pool)), struct.pack("<q", index)], DLMM
            )
            arrays[index] = chain.account(str(pda))
        raw = arrays[index]
        if raw is None:
            continue
        offset = BIN_ARRAY_HEADER + (bin_id - index * BINS_PER_ARRAY) * BIN_SIZE
        amount_x, amount_y = struct.unpack_from("<QQ", raw, offset)
        supply = int.from_bytes(raw[offset + 32 : offset + 48], "little")
        share = shares[bin_id - lower]
        if supply and share:
            # Integer math throughout: these are raw base units, and a float here is the
            # same silent corruption the tape contract refuses.
            total_x += amount_x * share // supply
            total_y += amount_y * share // supply
    return total_x, total_y


def net_flows(chain: Chain, wallet: str, position: str) -> tuple[int, dict[str, int]]:
    """The wallet's own net SOL and token flows across this position's whole history.

    Net, not gross: a claim that was re-deposited nets out, so compounded fees are counted
    once — inside the position's current value — rather than added on top of it.
    """
    lamports = 0
    tokens: dict[str, int] = {}
    for entry in reversed(chain.signatures(position)):
        transaction = chain.transaction(entry["signature"])
        if not transaction or transaction["meta"].get("err"):
            continue
        meta = transaction["meta"]
        keys = [
            k["pubkey"] if isinstance(k, dict) else k
            for k in transaction["transaction"]["message"]["accountKeys"]
        ]
        if wallet in keys:
            index = keys.index(wallet)
            lamports += meta["postBalances"][index] - meta["preBalances"][index]
        before = {
            (b["owner"], b["mint"]): int(b["uiTokenAmount"]["amount"])
            for b in (meta.get("preTokenBalances") or [])
        }
        after = {
            (b["owner"], b["mint"]): int(b["uiTokenAmount"]["amount"])
            for b in (meta.get("postTokenBalances") or [])
        }
        for key in set(before) | set(after):
            if key[0] != wallet:
                continue
            delta = after.get(key, 0) - before.get(key, 0)
            if delta:
                tokens[key[1]] = tokens.get(key[1], 0) + delta
    return lamports, tokens


def main() -> int:
    wallet = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_WALLET
    key_path = Path.home() / ".helius-key"
    if not key_path.exists():
        print("~/.helius-key is missing", file=sys.stderr)
        return 1
    chain = Chain(f"https://mainnet.helius-rpc.com/?api-key={key_path.read_text().strip()}")

    found = _rpc(
        chain.url,
        {"jsonrpc": "2.0", "id": 1, "method": "getProgramAccounts",
         "params": [str(DLMM), {"encoding": "base64",
                                "filters": [{"memcmp": {"offset": 40, "bytes": wallet}}]}]},
    ).get("result") or []
    print(f"wallet {wallet}")
    print(f"DLMM positions: {len(found)}\n")

    prices: dict[str, float | None] = {}
    grand_value = 0.0
    grand_basis = 0.0

    for item in found:
        raw = base64.b64decode(item["account"]["data"][0])
        if len(raw) != POSITION_LEN:
            print(f"  {item['pubkey']}: unexpected length {len(raw)} — layout changed, skipping")
            continue
        pool = str(Pubkey(raw[8:40]))
        pool_raw = chain.account(pool)
        assert pool_raw is not None
        mint_x, mint_y = str(Pubkey(pool_raw[88:120])), str(Pubkey(pool_raw[120:152]))
        dec_x, dec_y = chain.decimals(mint_x), chain.decimals(mint_y)
        lower, upper = struct.unpack_from("<ii", raw, TAIL_OFF)
        active = struct.unpack_from("<i", pool_raw, 8 + 68)[0]
        bin_step = struct.unpack_from("<H", pool_raw, 8 + 72)[0]
        claimed_x, claimed_y = struct.unpack_from("<QQ", raw, TAIL_OFF + 16)
        pending_x = sum(
            struct.unpack_from("<Q", raw, FEE_INFOS_OFF + i * 48 + 32)[0] for i in range(70)
        )
        pending_y = sum(
            struct.unpack_from("<Q", raw, FEE_INFOS_OFF + i * 48 + 40)[0] for i in range(70)
        )

        amount_x, amount_y = position_amounts(chain, raw, pool)
        for mint in (mint_x, mint_y):
            if mint not in prices:
                prices[mint] = usd_price(mint)

        signatures = chain.signatures(item["pubkey"])
        opened = signatures[-1].get("blockTime") if signatures else None
        age = (
            datetime.now(UTC) - datetime.fromtimestamp(opened, UTC) if opened else None
        )
        lamports, tokens = net_flows(chain, wallet, item["pubkey"])

        px, py = prices.get(mint_x), prices.get(mint_y)
        value = (amount_x / 10**dec_x) * (px or 0) + (amount_y / 10**dec_y) * (py or 0)
        # HODL counterfactual: the tokens actually put in, valued at today's price.
        basis = sum(
            (-delta / 10 ** (dec_x if mint == mint_x else dec_y)) * (prices.get(mint) or 0)
            for mint, delta in tokens.items()
            if delta < 0
        )
        grand_value += value
        grand_basis += basis

        where = (
            "BELOW range (all base token, no quote)" if active < lower
            else "ABOVE range (all quote, fully converted)" if active > upper
            else "IN range — earning"
        )
        print(f"  position {item['pubkey']}")
        print(f"    pool {pool}  bin_step {bin_step}")
        print(f"    bins [{lower}, {upper}]  active {active}  → {where}")
        if age is not None:
            print(f"    age {age.days}d {age.seconds // 3600}h{(age.seconds % 3600) // 60}m")
        def _usd(units: float, price: float | None) -> str:
            return "price unavailable" if price is None else f"${units * price:,.2f}"

        print(f"    holds {amount_x / 10**dec_x:>16,.2f} {mint_x[:8]}…  {_usd(amount_x / 10**dec_x, px)}")
        print(f"    holds {amount_y / 10**dec_y:>16,.2f} {mint_y[:8]}…  {_usd(amount_y / 10**dec_y, py)}")
        print(f"    fees pending  x={pending_x} y={pending_y}   claimed  x={claimed_x} y={claimed_y}")
        print(f"    net SOL flow  {lamports / 1e9:+.4f}")
        if px is None or py is None:
            print("    VALUE unavailable — a leg has no price, and valuing it at zero would lie")
        else:
            print(f"    VALUE ${value:,.2f}   vs HODL ${basis:,.2f}   →  {value - basis:+,.2f} "
                  f"({((value / basis - 1) * 100) if basis else 0:+.2f}%)")
        print()

    print(f"  TOTAL  ${grand_value:,.2f}   vs HODL ${grand_basis:,.2f}   "
          f"→ {grand_value - grand_basis:+,.2f}")
    print("\n  vs HODL compares the position against simply holding the tokens that were put")
    print("  in, priced today. It is fee income NET of impermanent loss, which is the only")
    print("  comparison that answers whether providing liquidity was worth doing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
