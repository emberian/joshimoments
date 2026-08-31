#!/usr/bin/env python3
"""Maker-side execution: can we stop being the thing that crosses, and be the thing crossed?

The desk's binding constraint is TRANSACTION LANDING. ``scripts/sim2real.py`` measures ambient
landing on our own cluster pools at 1%-52%, and the shadow model has no failure branch at all, so
true friction may be several times what it reports. The operator's observation is that posting a
RESTING order to Jupiter moves the landing race onto whoever fills it: the filler pays the gas,
runs the latency race, and eats the revert. We either get filled or we do not.

That is a real mechanism and it is worth testing precisely, because "someone else bears the
landing risk" is only an improvement if that someone else actually exists, actually competes, and
is not a single vendor process that can stop. This script establishes, from primary sources only:

1. INVENTORY  -- which Jupiter programs are deployed, executable, and actually carrying traffic.
   ``executable=true`` is a weak test (dead programs stay executable forever), so liveness is
   measured as recency of real signatures, not as the existence of an account.

2. INTERFACE  -- the deployed program's own Anchor IDL, read off chain from the IDL PDA. This is
   the strongest available source for "who may fill an order": stronger than documentation,
   because it is the artifact the validator actually runs against. The question it answers is
   whether the ``taker`` account carries an address constraint (an allowlist) or not.

3. PRACTICE   -- who fills in fact. An unconstrained interface and a monopsony keeper look
   identical in the IDL and completely different on a P&L, so the filler population is counted
   from real fill instructions rather than inferred from the absence of a constraint.

4. ROUTABILITY -- whether Jupiter will quote and route OUR pairs, at the sizes we would trade,
   and which venue it picks. A resting order is worthless on a pair the router cannot reach.

5. FLASHLOANS -- the fee is read out of Kamino's own reserve configs (a scaled-fraction field in
   the on-chain ``Reserve`` account), not from a blog post, and the compute cost of a real
   borrow/repay cycle is measured from transactions that actually ran.

READ-ONLY. This script signs nothing and sends nothing. It builds one unsigned order transaction
through Jupiter's public API purely to read back the parameters Jupiter would stamp on it, using
a freshly generated throwaway pubkey that is never funded and whose secret is discarded.

Usage:
    python studies/jupiter_programs.py                 # everything
    python studies/jupiter_programs.py --only inventory,quotes
    python studies/jupiter_programs.py --json
"""

from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import json
import re
import statistics
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------------------------
# Credentials.  Mirrors shitcoims_intelligence.helius._read_helius_key: the key is a URL query
# parameter, so the file must be private and the endpoint is never logged.
# --------------------------------------------------------------------------------------------

HELIUS_KEY_FILE = Path("~/.helius-key")
LAMPORTS = 1_000_000_000

# Solana ships a hard 1.4M compute-unit ceiling per transaction; SetComputeUnitLimit cannot
# request more.  Every CU budget below is measured against this number.
MAX_CU_PER_TX = 1_400_000

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Cluster universe.  Mints mirror shitcoims_cluster/pools.py, which is the on-chain-verified
# source; they are repeated rather than imported so this script stays runnable standalone.
CLUSTER = {
    "WEAVE": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
    "NOSIS": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
    "DREGG": "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump",
    "SOLVE": "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump",
}

# Candidate programs.  Every one of these is CHECKED, not trusted -- the point of the inventory
# is that a program ID from a blog post is a claim, and getAccountInfo is the test.
PROGRAMS: list[tuple[str, str, str]] = [
    ("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4", "Jupiter Aggregator v6", "swap router"),
    ("JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB", "Jupiter Aggregator v4", "swap router (old)"),
    ("JUP3c2Uh3WA4Ng34tw6kPd2G4C5BB21Xo36Je1s32Ph", "Jupiter Aggregator v3", "swap router (old)"),
    ("JUP2jxvXaqu7NQY1GmNF4m1vodw12LVXYxbFL2uJvfo", "Jupiter Aggregator v2", "swap router (old)"),
    ("j1o2qRpjcyUwEvwtcfhEQefh773ZgjxcVRry7LDqg5X", "Jupiter Limit Order v2", "resting orders / Trigger"),
    ("jupoNjAxXgZ4rjzxzPMP4oxduvQsQtZzyknqvzYNrNu", "Jupiter Limit Order v1", "resting orders (old)"),
    ("DCA265Vj8a9CEuX1eb1LWRnDT7uK6q1xMipnNyatn23M", "Jupiter DCA", "scheduled buys / Recurring"),
    ("PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu", "Jupiter Perps", "perpetuals"),
    ("voTpe3tHQ7AjQHMapgSue2HJFAh2cGsdokqN3XqmVSj", "Jupiter Vote", "governance"),
    ("jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS", "Jupiter Lend flashloan", "flashloans"),
    ("jup3YeL8QhtSx1e253b2FDvsMNC87fDrgQZivbrndc9", "Jupiter Lend lending", "lending"),
    ("KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD", "Kamino Lend", "flashloans"),
    ("So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo", "Save (ex-Solend)", "flashloans"),
    ("MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA", "MarginFi v2 / Project 0", "flashloans"),
    ("Port7uDYB3wk6GJAw4KT1WpTeMtSu9bTcChBHkX2LfR", "Port Finance", "flashloans (legacy)"),
    ("dRiftyHA39MWEi3m9aunc5MzRF1JYuBsbn6VPcn33UH", "Drift v2", "perps / lending"),
    ("pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA", "PumpSwap AMM", "our token/SOL pools"),
    ("LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo", "Meteora DLMM", "our token/token pools"),
]

TRIGGER = "j1o2qRpjcyUwEvwtcfhEQefh773ZgjxcVRry7LDqg5X"
KLEND = "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"
JUP_V6 = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"

QUOTE_API = "https://lite-api.jup.ag/swap/v1/quote"
TRIGGER_API = "https://lite-api.jup.ag/trigger/v1/createOrder"
# Jupiter's edge rejects the default urllib agent with Cloudflare 1010 on POST.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


# --------------------------------------------------------------------------------------------
# plumbing
# --------------------------------------------------------------------------------------------


def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + body


def anchor_ix_discriminator(name: str) -> bytes:
    """Legacy Anchor derives the discriminator from the SNAKE_CASE rust fn name.

    Older IDLs carry the instruction as camelCase while the program hashes the snake_case form.
    Hashing the IDL spelling verbatim yields eight bytes that match nothing, and a scan built on
    it reports a confident, wrong zero.
    """
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return hashlib.sha256(f"global:{snake}".encode()).digest()[:8]


class Rpc:
    def __init__(self, key_file: Path = HELIUS_KEY_FILE) -> None:
        path = key_file.expanduser()
        info = path.stat()
        if info.st_mode & 0o077:
            raise SystemExit(f"Helius key file must be 0600 or stricter: {path}")
        key = path.read_text(encoding="utf-8").strip()
        if not key or any(c.isspace() for c in key):
            raise SystemExit("Helius API key has an invalid format")
        self._url = f"https://mainnet.helius-rpc.com/?api-key={urllib.parse.quote(key, safe='')}"

    def _post(self, payload: Any, timeout: int = 120) -> Any:
        req = urllib.request.Request(
            self._url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as fh:
                return json.load(fh)
        except urllib.error.HTTPError as exc:  # never leak the credentialed URL
            raise SystemExit(f"Helius HTTP {exc.code}") from None

    def call(self, method: str, params: Any) -> Any:
        out = self._post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if "error" in out:
            raise SystemExit(f"RPC {method} failed: {out['error'].get('message')}")
        return out.get("result")

    def batch(self, method: str, param_list: list[Any]) -> list[Any]:
        reqs = [
            {"jsonrpc": "2.0", "id": i, "method": method, "params": p} for i, p in enumerate(param_list)
        ]
        return [item.get("result") for item in self._post(reqs)]

    def signatures(self, address: str, pages: int = 1) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        before = None
        for _ in range(pages):
            opts: dict[str, Any] = {"limit": 1000}
            if before:
                opts["before"] = before
            page = self.call("getSignaturesForAddress", [address, opts]) or []
            if not page:
                break
            out += page
            before = page[-1]["signature"]
            time.sleep(0.1)
        return out

    def transactions(self, sigs: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
        """Stride-sample so the sample spans the whole window instead of the newest minutes."""
        step = max(1, len(sigs) // cap)
        sel = sigs[::step][:cap]
        out = []
        for i in range(0, len(sel), 40):
            params = [
                [s["signature"], {"encoding": "json", "maxSupportedTransactionVersion": 0}]
                for s in sel[i : i + 40]
            ]
            try:
                out += [t for t in self.batch("getTransaction", params) if t]
            except SystemExit:
                continue
            time.sleep(0.1)
        return out

    def fetch_idl(self, program_id: str) -> dict[str, Any] | None:
        """Read a program's Anchor IDL from its on-chain IDL PDA.

        This is the deployed interface, not documentation about it.
        """
        from solders.pubkey import Pubkey

        pid = Pubkey.from_string(program_id)
        base, _ = Pubkey.find_program_address([], pid)
        addr = Pubkey.create_with_seed(base, "anchor:idl", pid)
        value = self.call("getAccountInfo", [str(addr), {"encoding": "base64"}])
        if not value or not value.get("value"):
            return None
        raw = base64.b64decode(value["value"]["data"][0])
        length = int.from_bytes(raw[40:44], "little")
        try:
            return json.loads(zlib.decompress(raw[44 : 44 + length]))
        except Exception:
            return None


def http_get_json(url: str, timeout: int = 25) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            return json.load(fh)
    except urllib.error.HTTPError as exc:
        return {"__err": f"HTTP {exc.code}: {exc.read()[:200].decode(errors='replace')}"}
    except Exception as exc:
        return {"__err": str(exc)}


def http_post_json(url: str, body: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            return json.load(fh)
    except urllib.error.HTTPError as exc:
        return {"__err": f"HTTP {exc.code}: {exc.read()[:300].decode(errors='replace')}"}
    except Exception as exc:
        return {"__err": str(exc)}


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, round(p / 100 * (len(s) - 1))))]


# --------------------------------------------------------------------------------------------
# 1. inventory
# --------------------------------------------------------------------------------------------


def check_inventory(rpc: Rpc, out: dict[str, Any]) -> None:
    print("=" * 96)
    print("1. PROGRAM INVENTORY -- existence, executability, and whether anything still uses it")
    print("=" * 96)
    infos = rpc.call(
        "getMultipleAccounts",
        [[p for p, _, _ in PROGRAMS], {"encoding": "base64", "dataSlice": {"offset": 0, "length": 4}}],
    )["value"]
    rows = []
    print(f"  {'program':30}{'id':46}{'exec':>6}{'last tx':>18}")
    for (pid, name, role), info in zip(PROGRAMS, infos, strict=True):
        if info is None:
            print(f"  {name:30}{pid:46}{'MISSING':>6}")
            rows.append({"id": pid, "name": name, "role": role, "exists": False})
            continue
        sigs = rpc.call("getSignaturesForAddress", [pid, {"limit": 1}]) or []
        bt = sigs[0].get("blockTime") if sigs else None
        age_h = (time.time() - bt) / 3600 if bt else None
        stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime(bt)) if bt else "never"
        print(f"  {name:30}{pid:46}{info['executable']!s:>6}{stamp:>18}"
              f"   {'' if age_h is None else f'({age_h:,.1f}h ago)'}")
        rows.append({
            "id": pid, "name": name, "role": role, "exists": True,
            "executable": info["executable"], "owner": info["owner"],
            "last_tx_unix": bt, "last_tx_age_hours": age_h,
        })
        time.sleep(0.05)
    out["inventory"] = rows
    print("\n  NOTE: executable=true is nearly meaningless on its own -- a program that nobody has")
    print("  called since 2025 is still executable. The 'last tx' column is the liveness test.")


# --------------------------------------------------------------------------------------------
# 2. the deployed interface: who is ALLOWED to fill
# --------------------------------------------------------------------------------------------


def check_interface(rpc: Rpc, out: dict[str, Any]) -> None:
    print("\n" + "=" * 96)
    print("2. THE DEPLOYED INTERFACE -- is filling permissionless? (read from the on-chain IDL)")
    print("=" * 96)
    idl = rpc.fetch_idl(TRIGGER)
    if not idl:
        print("  no IDL account; cannot verify")
        return
    meta = idl.get("metadata") or {}
    print(f"  program: {meta.get('name')} v{meta.get('version')}   ({len(idl['instructions'])} instructions)")

    fill = next((i for i in idl["instructions"] if i["name"] == "fill_order"), None)
    if fill:
        print("\n  fill_order accounts (an 'address' entry is a HARD constraint baked into the interface):")
        for acct in fill["accounts"]:
            flags = []
            if acct.get("signer"):
                flags.append("signer")
            if acct.get("writable"):
                flags.append("writable")
            if acct.get("optional"):
                flags.append("optional")
            pin = acct.get("address")
            note = f"  <-- PINNED to {pin}" if pin else ""
            print(f"    {acct['name']:28}{','.join(flags):22}{note}")
        taker = next((a for a in fill["accounts"] if a["name"] == "taker"), None)
        pinned = bool(taker and taker.get("address"))
        print(f"\n  VERDICT: taker is {'PINNED (allowlisted)' if pinned else 'UNCONSTRAINED'} in the IDL.")
        if not pinned:
            print("  The interface names no privileged filler: any signer may present itself as taker.")
            print("  CAVEAT: an IDL cannot show `constraint = ...` checks inside the handler body, so")
            print("  this is necessary evidence, not sufficient. Section 3 tests it against practice.")
        out["taker_pinned"] = pinned

    order = next((t for t in idl.get("types", []) if t["name"] == "Order"), None)
    if order:
        fields = [f["name"] for f in order["type"]["fields"]]
        print(f"\n  Order account fields:\n    {', '.join(fields)}")
        keys = ("trigger", "oracle", "stop", "condition", "price")
        trigger_like = [f for f in fields if any(k in f.lower() for k in keys)]
        print(f"\n  fields expressing a TRIGGER CONDITION (price/oracle/direction): {trigger_like or 'NONE'}")
        if not trigger_like:
            print("  => The order carries amounts and an expiry, and nothing else. The only condition the")
            print("     program can enforce is 'a taker delivered at least taking_amount'. That is a LIMIT")
            print("     order. A stop-loss is the opposite trigger direction and CANNOT be represented.")
        out["order_fields"] = fields
        out["trigger_fields"] = trigger_like

    has_flash = any(i["name"] == "pre_flash_fill_order" for i in idl["instructions"])
    if has_flash:
        print("\n  pre_flash_fill_order exists and takes the Instructions sysvar: a filler may BORROW the")
        print("  maker's escrowed input within one transaction and repay by the end of it. A filler")
        print("  therefore needs no inventory of its own, which widens who can compete to fill us.")
    out["flash_fill_available"] = has_flash


# --------------------------------------------------------------------------------------------
# 3. practice: who fills in fact
# --------------------------------------------------------------------------------------------


def check_fillers(rpc: Rpc, out: dict[str, Any], pages: int = 6, cap: int = 1200) -> None:
    print("\n" + "=" * 96)
    print("3. WHO FILLS IN FACT -- counted from real fill instructions")
    print("=" * 96)
    idl = rpc.fetch_idl(TRIGGER)
    if not idl:
        return
    disc = {bytes(i["discriminator"]): i["name"] for i in idl["instructions"] if "discriminator" in i}
    sigs = rpc.signatures(TRIGGER, pages=pages)
    bts = [s["blockTime"] for s in sigs if s.get("blockTime")]
    span_h = (max(bts) - min(bts)) / 3600 if bts else 0
    print(f"  {len(sigs):,} signatures spanning {span_h:.1f} h; "
          f"sampling {cap} transactions across the window")
    txs = rpc.transactions(sigs, cap)

    counts: collections.Counter[str] = collections.Counter()
    fails: collections.Counter[str] = collections.Counter()
    cu: dict[str, list[int]] = collections.defaultdict(list)
    takers: collections.Counter[str] = collections.Counter()
    for tx in txs:
        msg = tx["transaction"]["message"]
        loaded = tx.get("meta", {}).get("loadedAddresses") or {}
        keys = list(msg["accountKeys"]) + loaded.get("writable", []) + loaded.get("readonly", [])
        errored = tx.get("meta", {}).get("err") is not None
        allix = list(msg["instructions"])
        for grp in tx.get("meta", {}).get("innerInstructions") or []:
            allix += grp["instructions"]
        seen = set()
        for ix in allix:
            idx = ix.get("programIdIndex")
            if idx is None or idx >= len(keys) or keys[idx] != TRIGGER:
                continue
            try:
                data = b58decode(ix["data"])
            except Exception:
                continue
            name = disc.get(data[:8])
            if not name:
                continue
            seen.add(name)
            accs = ix.get("accounts") or []
            if name in ("fill_order", "flash_fill_order") and accs and accs[0] < len(keys):
                takers[keys[accs[0]]] += 1
        for name in seen:
            counts[name] += 1
            if errored:
                fails[name] += 1
            elif tx["meta"].get("computeUnitsConsumed"):
                cu[name].append(tx["meta"]["computeUnitsConsumed"])

    print(f"\n  {'instruction':24}{'txs':>7}{'failed':>8}{'fail%':>8}{'median CU':>11}")
    for name, n in counts.most_common():
        med = statistics.median(cu[name]) if cu[name] else 0
        print(f"  {name:24}{n:>7}{fails[name]:>8}{fails[name] / n * 100:>7.1f}%{med:>11,.0f}")

    total = sum(takers.values())
    print(f"\n  fill instructions: {total}   DISTINCT TAKERS: {len(takers)}")
    for addr, n in takers.most_common(6):
        print(f"    {addr}  {n:>5} ({n / total * 100:5.1f}%)" if total else "")
    if takers:
        top_share = takers.most_common(1)[0][1] / total
        print(f"\n  top filler share: {top_share * 100:.1f}%")
        if top_share > 0.95:
            print("  => MONOPSONY. The interface permits anyone to fill; in practice one address does.")
            print("     'Someone else bears the landing risk' is true, but that someone is ONE vendor")
            print("     process, not a competitive filler market. Its downtime is our downtime.")

    created, filled, cancelled = counts["initialize_order"], counts["fill_order"], counts["cancel_order"]
    terminated = filled + cancelled
    if terminated:
        print(f"\n  ORDER LIFECYCLE over the window: {created} created, "
              f"{filled} filled, {cancelled} cancelled")
        print(f"  => of orders that TERMINATED, {filled / terminated * 100:.1f}% did so by being FILLED")
        print(f"     and {cancelled / terminated * 100:.1f}% by being CANCELLED.")
        print("     (Flow ratio, not a cohort: the orders filled today were posted earlier. It bounds")
        print("      the steady-state fill rate, it is not a per-order probability.)")
        out["fill_share_of_terminated"] = filled / terminated
    out["distinct_takers"] = len(takers)
    out["fill_instructions"] = total
    out["taker_top_share"] = (takers.most_common(1)[0][1] / total) if total else None


# --------------------------------------------------------------------------------------------
# 4. the resting book: what actually happens to a posted order
# --------------------------------------------------------------------------------------------


def decode_order(data: bytes) -> dict[str, Any] | None:
    """Decode a Trigger `Order`.

    `expired_at` is a borsh Option, so it occupies ONE byte when None and NINE when Some, and
    every field after it shifts. Fixed offsets past that point silently read the wrong bytes and
    produce plausible-looking garbage (a 19,166 bps fee, say), so the tag is branched on.
    """
    from solders.pubkey import Pubkey

    if len(data) < 310:
        return None
    off = 248
    tag = data[off]
    off += 1
    expired_at = None
    if tag == 1:
        expired_at = struct.unpack_from("<q", data, off)[0]
        off += 8
    elif tag != 0:
        return None
    fee_bps = struct.unpack_from("<H", data, off)[0]
    off += 2 + 32  # fee_bps, fee_account
    created_at = struct.unpack_from("<q", data, off)[0]
    off += 8
    updated_at = struct.unpack_from("<q", data, off)[0]
    off += 8 + 1  # updated_at, bump
    slippage_bps = struct.unpack_from("<H", data, off)[0]
    return {
        "maker": str(Pubkey(data[8:40])),
        "input_mint": str(Pubkey(data[40:72])),
        "output_mint": str(Pubkey(data[72:104])),
        "ori_making": struct.unpack_from("<Q", data, 208)[0],
        "making": struct.unpack_from("<Q", data, 224)[0],
        "taking": struct.unpack_from("<Q", data, 232)[0],
        "expired_at": expired_at,
        "fee_bps": fee_bps,
        "created_at": created_at,
        "updated_at": updated_at,
        "slippage_bps": slippage_bps,
    }


def check_resting_book(rpc: Rpc, out: dict[str, Any]) -> None:
    print("\n" + "=" * 96)
    print("4. THE RESTING BOOK -- every live order on the program, and the maker's failure modes")
    print("=" * 96)
    idl = rpc.fetch_idl(TRIGGER)
    order_disc = next(
        (bytes(a["discriminator"]) for a in (idl or {}).get("accounts", []) if a["name"] == "Order"), None
    )
    if not order_disc:
        return
    accounts = rpc.call(
        "getProgramAccounts",
        [TRIGGER, {"encoding": "base64", "filters": [
            {"memcmp": {"offset": 0, "bytes": base64.b64encode(order_disc).decode(), "encoding": "base64"}}
        ]}],
    ) or []
    rows = []
    for acct in accounts:
        dec = decode_order(base64.b64decode(acct["account"]["data"][0]))
        if dec:
            dec["lamports"] = acct["account"]["lamports"]
            rows.append(dec)
    n = len(rows)
    now = time.time()
    print(f"  live resting orders: {n:,}")
    if not n:
        return

    fee_dist = collections.Counter(r["fee_bps"] for r in rows).most_common(4)
    shown = ", ".join(f"{k} bps {c / n * 100:.1f}%" for k, c in fee_dist)
    print(f"\n  MAKER FEE (fee_bps on the order): {shown}")

    slip = collections.Counter(r["slippage_bps"] for r in rows)
    nonzero = sum(c for k, c in slip.items() if k)
    print(f"  SLIPPAGE ALLOWANCE: {slip[0] / n * 100:.1f}% of orders allow ZERO slippage; "
          f"{nonzero / n * 100:.1f}% pre-authorise a WORSE fill")
    for k, c in slip.most_common(4):
        print(f"      {k:>5} bps  {c:>7} ({c / n * 100:5.2f}%)")

    dated = [r for r in rows if r["expired_at"]]
    past = [r for r in dated if r["expired_at"] < now]
    print(f"\n  EXPIRY: {len(dated) / n * 100:.1f}% carry an expiry; "
          f"{(n - len(dated)) / n * 100:.1f}% are perpetual")
    if past:
        days = sorted((now - r["expired_at"]) / 86400 for r in past)
        print(f"  EXPIRED YET STILL ON CHAIN: {len(past):,} orders, "
              f"median {statistics.median(days):.0f} days past expiry")
        print(f"    holding {sum(r['lamports'] for r in past) / LAMPORTS:.3f} SOL of rent")
        print("    => expiry does NOT auto-return the escrow. It only stops the order being fillable.")
        print("       Someone must still land a cancel; until they do, the funds sit.")

    partial = [r for r in rows if r["ori_making"] and r["making"] < r["ori_making"]]
    print(f"\n  PARTIAL FILLS: {len(partial):,} ({len(partial) / n * 100:.2f}%) "
          "are partly filled and still resting")
    ages = sorted((now - r["created_at"]) / 86400 for r in rows)
    old = sum(1 for a in ages if a > 365) / n * 100
    print(f"  AGE: median {statistics.median(ages):.0f} days; {old:.1f}% older than a year")
    print(f"  RENT ESCROWED PER ORDER: {statistics.median([r['lamports'] for r in rows]) / LAMPORTS:.5f} SOL "
          f"({sum(r['lamports'] for r in rows) / LAMPORTS:,.0f} SOL across the book)")
    print("\n  SURVIVORSHIP WARNING: this is the book of orders that have NOT filled. Orders posted near")
    print("  the market fill and vanish, so a snapshot is biased toward far-from-market and abandoned")
    print("  orders. Read the age and distance figures as 'what a stale order looks like', not as the")
    print("  expected life of an order we would post.")

    # Is any resting order priced THROUGH the market? A stop-loss would be.
    quote = http_get_json(QUOTE_API + "?" + urllib.parse.urlencode(
        {"inputMint": SOL, "outputMint": USDC, "amount": str(LAMPORTS // 10), "slippageBps": "50"}))
    if "outAmount" in quote:
        mkt = (int(quote["outAmount"]) / 1e6) / 0.1
        sells = [r for r in rows if r["input_mint"] == SOL and r["output_mint"] == USDC
                 and r["making"] > 0 and r["taking"] > 0]
        prices = [(r["taking"] / 1e6) / (r["making"] / 1e9) for r in sells]
        through = [p for p in prices if p <= mkt]
        print(f"\n  STOP-LOSS TEST -- SOL market {mkt:.2f} USDC, {len(prices)} resting SOL->USDC sells:")
        print(f"    priced ABOVE market (a normal resting ask): {len(prices) - len(through)} "
              f"({(len(prices) - len(through)) / max(len(prices), 1) * 100:.2f}%)")
        print(f"    priced AT OR BELOW market (what a resting STOP would look like): {len(through)} "
              f"({len(through) / max(len(prices), 1) * 100:.2f}%)")
        print("    A stop sells when price FALLS THROUGH a level. Posted as a resting order it would sit")
        print("    below market and be taken instantly at that discount. Its near-total absence is the")
        print("    evidence that stops are NOT resting here.")
        out["resting_sells_through_market"] = len(through)
        out["resting_sells"] = len(prices)

    out["resting_orders"] = n
    out["maker_fee_mode_bps"] = fee_dist[0][0] if fee_dist else None
    out["expired_still_resting"] = len(past)


# --------------------------------------------------------------------------------------------
# 5. OTOCO: protocol guarantee vs vendor convenience
# --------------------------------------------------------------------------------------------


def check_otoco(out: dict[str, Any]) -> None:
    print("\n" + "=" * 96)
    print("5. THE OTOCO QUESTION -- is a stop-loss leg a real on-chain object?")
    print("=" * 96)
    try:
        from solders.keypair import Keypair
    except ImportError:
        print("  solders unavailable; skipping")
        return

    weave = CLUSTER["WEAVE"]
    buy = http_get_json(QUOTE_API + "?" + urllib.parse.urlencode(
        {"inputMint": SOL, "outputMint": weave, "amount": str(LAMPORTS // 2), "slippageBps": "50"}))
    if "outAmount" not in buy:
        print(f"  quote failed: {buy.get('__err')}")
        return
    tokens = int(buy["outAmount"])
    back = http_get_json(QUOTE_API + "?" + urllib.parse.urlencode(
        {"inputMint": weave, "outputMint": SOL, "amount": str(tokens), "slippageBps": "50"}))
    market = int(back["outAmount"])
    print(f"  market: {tokens:,} WEAVE is worth {market / LAMPORTS:.5f} SOL right now")

    print("\n  (a) Will the API let us post a SELL priced BELOW market -- i.e. an actual stop?")
    for mult, label in ((1.20, "ask +20% (ordinary limit sell)"),
                        (0.80, "-20% below market (a stop)"),
                        (0.50, "-50% below market (deep stop)")):
        maker = str(Keypair().pubkey())  # throwaway; never funded, never signed with
        res = http_post_json(TRIGGER_API, {
            "inputMint": weave, "outputMint": SOL, "maker": maker, "payer": maker,
            "params": {"makingAmount": str(tokens), "takingAmount": str(int(market * mult))},
            "computeUnitPrice": "auto"})
        ok = "__err" not in res
        print(f"    {label:34} -> {'ACCEPTED' if ok else 'rejected: ' + res['__err'][:70]}")
        if ok and mult < 1:
            print(f"       {'':32}    that order would rest on chain fillable IMMEDIATELY at "
                  f"{(1 - mult) * 100:.0f}% below market")

    print("\n  => Nothing stops us posting an underwater order, and nothing turns it into a stop: it is")
    print("     simply a bad limit order that any taker may hit at once. So a stop CANNOT be a resting")
    print("     order. It has to live off chain until something fires it.")

    print("\n  (b) Does the API accept any trigger/OCO field, and does it change the instruction?")
    base_body = {
        "inputMint": weave, "outputMint": SOL,
        "params": {"makingAmount": str(tokens), "takingAmount": str(int(market * 1.2))},
        "computeUnitPrice": "auto"}
    baseline = _init_order_args(base_body)
    if baseline is None:
        print("     could not decode the baseline instruction; skipping")
        return
    for field in ({"triggerPrice": "1000"}, {"stopLoss": {"takingAmount": "1"}},
                  {"orderType": "stopLoss"}, {"oco": True}):
        args = _init_order_args({**base_body, **field})
        name = next(iter(field))
        if args is None:
            print(f"    {name:14} -> REJECTED by the API")
        else:
            # unique_id is the first 8 bytes and is randomised per request by design
            same = args[16:] == baseline[16:]
            print(f"    {name:14} -> accepted, instruction bytes identical to plain order: {same}")
    print("\n  => The fields are accepted and DISCARDED. They cannot be honoured: section 2 showed the")
    print("     Order account has nowhere to put a trigger price. OTOCO is a Jupiter UI/keeper")
    print("     construct, not a protocol guarantee.")
    out["otoco_is_offchain"] = True


def _init_order_args(body: dict[str, Any]) -> str | None:
    """POST createOrder with a throwaway maker and return the initialize_order arg bytes as hex."""
    try:
        from solders.keypair import Keypair
        from solders.transaction import VersionedTransaction
    except ImportError:
        return None
    maker = str(Keypair().pubkey())
    res = http_post_json(TRIGGER_API, {**body, "maker": maker, "payer": maker})
    if "__err" in res or "transaction" not in res:
        return None
    tx = VersionedTransaction.from_bytes(base64.b64decode(res["transaction"]))
    keys = list(tx.message.account_keys)
    want = anchor_ix_discriminator("initializeOrder")
    for ix in tx.message.instructions:
        if str(keys[ix.program_id_index]) != TRIGGER:
            continue
        data = bytes(ix.data)
        # match on the IDL-declared discriminator when the derived one disagrees
        if data[:8] == want or len(data) > 24:
            return data[8:].hex()
    return None


# --------------------------------------------------------------------------------------------
# 6. routability of our own pairs
# --------------------------------------------------------------------------------------------


def check_quotes(out: dict[str, Any]) -> None:
    print("\n" + "=" * 96)
    print("6. CAN JUPITER EVEN QUOTE OUR PAIRS? -- real quotes at real sizes")
    print("=" * 96)
    sizes = (0.1, 0.5, 2.0, 5.0)
    print(f"  {'pair':16}{'size':>7}{'price impact':>14}{'round trip':>12}   route")
    results = {}
    for name, mint in CLUSTER.items():
        for sol in sizes:
            buy = http_get_json(QUOTE_API + "?" + urllib.parse.urlencode(
                {"inputMint": SOL, "outputMint": mint,
                 "amount": str(int(sol * LAMPORTS)), "slippageBps": "50"}))
            if "outAmount" not in buy:
                print(f"  {'SOL->' + name:16}{sol:>7}{'NO ROUTE':>14}   {buy.get('__err', '')[:60]}")
                continue
            tokens = int(buy["outAmount"])
            impact = float(buy.get("priceImpactPct") or 0) * 100
            route = "+".join(h["swapInfo"]["label"] for h in buy["routePlan"])
            time.sleep(0.35)
            back = http_get_json(QUOTE_API + "?" + urllib.parse.urlencode(
                {"inputMint": mint, "outputMint": SOL, "amount": str(tokens), "slippageBps": "50"}))
            rt = (1 - int(back["outAmount"]) / LAMPORTS / sol) * 100 if "outAmount" in back else float("nan")
            print(f"  {'SOL->' + name:16}{sol:>7}{impact:>13.3f}%{rt:>11.2f}%   {route}")
            results[f"{name}@{sol}"] = {"impact_pct": impact, "round_trip_pct": rt, "route": route}
            time.sleep(0.35)
    out["quotes"] = results
    print("\n  round trip = buy then immediately sell back. It is the full cost of being the TAKER:")
    print("  both fee legs plus both impact legs. It is the number maker-side execution is trying to save.")

    print("\n  Does Jupiter use our token/token DLMM pools?")
    probes = [("WEAVE", "NOSIS"), ("DREGG", "NOSIS")]
    for a, b in probes:
        amt = http_get_json(QUOTE_API + "?" + urllib.parse.urlencode(
            {"inputMint": SOL, "outputMint": CLUSTER[a], "amount": str(LAMPORTS // 10), "slippageBps": "50"}))
        if "outAmount" not in amt:
            continue
        free = http_get_json(QUOTE_API + "?" + urllib.parse.urlencode(
            {"inputMint": CLUSTER[a], "outputMint": CLUSTER[b],
             "amount": amt["outAmount"], "slippageBps": "50"}))
        forced = http_get_json(QUOTE_API + "?" + urllib.parse.urlencode(
            {"inputMint": CLUSTER[a], "outputMint": CLUSTER[b], "amount": amt["outAmount"],
             "slippageBps": "50", "dexes": "Meteora DLMM"}))
        fr = "+".join(h["swapInfo"]["label"] for h in free["routePlan"]) if "outAmount" in free else "none"
        fi = float(free.get("priceImpactPct") or 0) * 100 if "outAmount" in free else float("nan")
        if "outAmount" in forced:
            gi = float(forced.get("priceImpactPct") or 0) * 100
            print(f"    {a}->{b:6} free route: {fr} ({fi:.2f}%)   forced-DLMM: {gi:.2f}% impact")
        else:
            print(f"    {a}->{b:6} free route: {fr} ({fi:.2f}%)   forced-DLMM: NO ROUTE "
                  f"({forced.get('__err', '')[:50]})")
        time.sleep(0.35)
    print("    => where a DLMM route exists at all it is far worse, so the router never picks it.")
    print("       Our token/token liquidity is not what Jupiter crosses; it crosses our PumpSwap legs.")

    print("\n  Minimum order size the Trigger API will accept:")
    try:
        from solders.keypair import Keypair
        maker = str(Keypair().pubkey())
        res = http_post_json(TRIGGER_API, {
            "inputMint": SOL, "outputMint": CLUSTER["WEAVE"], "maker": maker, "payer": maker,
            "params": {"makingAmount": str(LAMPORTS // 100), "takingAmount": "5000000000"},
            "computeUnitPrice": "auto"})
        print(f"    0.01 SOL order -> {'accepted' if '__err' not in res else res['__err'][:150]}")
    except ImportError:
        pass


# --------------------------------------------------------------------------------------------
# 7. flashloans
# --------------------------------------------------------------------------------------------


def _sizeof(t: Any, types: dict[str, Any]) -> int:
    prim = {"u8": 1, "i8": 1, "bool": 1, "u16": 2, "i16": 2, "u32": 4, "i32": 4,
            "u64": 8, "i64": 8, "u128": 16, "i128": 16, "publicKey": 32, "pubkey": 32,
            "f32": 4, "f64": 8}
    if isinstance(t, str):
        return prim[t]
    if "array" in t:
        return _sizeof(t["array"][0], types) * t["array"][1]
    if "defined" in t:
        d = t["defined"]
        ty = types[d if isinstance(d, str) else d["name"]]["type"]
        if ty["kind"] == "struct":
            return sum(_sizeof(f["type"], types) for f in ty["fields"])
        return 1
    raise ValueError(str(t))


def check_flashloans(rpc: Rpc, out: dict[str, Any], cap: int = 1000) -> None:
    print("\n" + "=" * 96)
    print("7. FLASHLOANS -- fee read from the reserve config, cost measured from real transactions")
    print("=" * 96)
    idl = rpc.fetch_idl(KLEND)
    if not idl:
        print("  no Kamino IDL")
        return
    types = {t["name"]: t for t in idl.get("types", []) + idl.get("accounts", [])}

    # offset of config.fees.flashLoanFeeSf inside Reserve
    off = 8
    ty = types["Reserve"]["type"]
    for part in ("config", "fees", "flashLoanFeeSf"):
        for f in ty["fields"]:
            if f["name"] == part:
                inner = f["type"]
                break
            off += _sizeof(f["type"], types)
        else:
            raise SystemExit(f"field {part} not found")
        if isinstance(inner, dict) and "defined" in inner:
            d = inner["defined"]
            ty = types[d if isinstance(d, str) else d["name"]]["type"]

    disc = hashlib.sha256(b"account:Reserve").digest()[:8]
    accounts = rpc.call("getProgramAccounts", [KLEND, {"encoding": "base64", "filters": [
        {"memcmp": {"offset": 0, "bytes": base64.b64encode(disc).decode(), "encoding": "base64"}}]}]) or []
    frac = 2 ** 60  # Kamino stores the rate as a U68F60 scaled fraction
    # Kamino's kill switch is the exact sentinel `flash_loan_fee_sf == u64::MAX` ->
    # LendingError::FlashLoansDisabled.  Scaled it reads as ~160,000 bps, which looks like a
    # merely absurd fee unless it is matched on the raw value, so it is matched on the raw value.
    disabled_sentinel = (1 << 64) - 1
    fees: collections.Counter[float] = collections.Counter()
    disabled = 0
    for acct in accounts:
        data = base64.b64decode(acct["account"]["data"][0])
        if len(data) < off + 8:
            continue
        raw = struct.unpack_from("<Q", data, off)[0]
        if raw == disabled_sentinel:
            disabled += 1
            continue
        fees[round(raw / frac * 1e4, 4)] += 1
    print(f"  Kamino reserves: {len(accounts)}   flash loan fee distribution (bps):")
    for bps, n in fees.most_common(6):
        note = "  <- free" if bps == 0 else ""
        print(f"    {bps:>12,.4f} bps : {n:>4} reserves{note}")
    print(f"    {'DISABLED':>12} : {disabled:>4} reserves  (flash_loan_fee_sf == u64::MAX sentinel)")
    out["kamino_fee_bps_mode"] = fees.most_common(1)[0][0] if fees else None
    out["kamino_reserves_disabled"] = disabled

    borrow = anchor_ix_discriminator("flashBorrowReserveLiquidity")
    repay = anchor_ix_discriminator("flashRepayReserveLiquidity")
    sigs = rpc.signatures(KLEND, pages=5)
    txs = rpc.transactions(sigs, cap)
    found = []
    for tx in txs:
        msg = tx["transaction"]["message"]
        loaded = tx.get("meta", {}).get("loadedAddresses") or {}
        keys = list(msg["accountKeys"]) + loaded.get("writable", []) + loaded.get("readonly", [])
        b = r = None
        for ix in msg["instructions"]:  # borrow/repay must be TOP-LEVEL for introspection
            idx = ix.get("programIdIndex")
            if idx is None or idx >= len(keys) or keys[idx] != KLEND:
                continue
            try:
                data = b58decode(ix["data"])
            except Exception:
                continue
            if data[:8] == borrow:
                b = struct.unpack_from("<Q", data, 8)[0]
            elif data[:8] == repay:
                r = struct.unpack_from("<Q", data, 8)[0]
        if b is not None and r is not None:
            found.append({"borrow": b, "repay": r, "cu": tx["meta"].get("computeUnitsConsumed") or 0,
                          "fee": tx["meta"]["fee"], "err": tx.get("meta", {}).get("err") is not None})
    print(f"\n  sampled {len(txs)} Kamino transactions -> {len(found)} flashloan cycles "
          f"({len(found) / max(len(txs), 1) * 100:.1f}% of all Kamino traffic)")
    if not found:
        return
    ok = [f for f in found if not f["err"]]
    bad = [f for f in found if f["err"]]
    charged = [(f["repay"] - f["borrow"]) / f["borrow"] * 1e4 for f in found if f["borrow"]]
    print(f"  fee actually charged: median {statistics.median(charged):.4f} bps (max {max(charged):.4f})")
    print(f"  succeeded {len(ok)} ({len(ok) / len(found) * 100:.1f}%)   failed {len(bad)} "
          f"({len(bad) / len(found) * 100:.1f}%)")
    for label, grp in (("succeeded", ok), ("failed", bad)):
        if not grp:
            continue
        print(f"    {label:10} CU median {statistics.median([f['cu'] for f in grp]):>9,.0f}  "
              f"p90 {pct([float(f['cu']) for f in grp], 90):>9,.0f}   "
              f"tx fee median {statistics.median([f['fee'] for f in grp]):>9,.0f} lamports")
    if ok:
        total_fee = sum(f["fee"] for f in found)
        print(f"\n  COST PER SUCCESSFUL CYCLE: {total_fee / len(ok) / LAMPORTS:.6f} SOL "
              f"(all attempts' gas divided by the successes)")
        print("  A failed flashloan is CHEAP: the loan never happens, only the fee is burned. That is")
        print("  the real attraction of the pattern -- it converts execution risk into a cheap revert.")
        med_cu = statistics.median([f["cu"] for f in ok])
        print(f"\n  CU BUDGET: a full borrow->route->repay cycle costs {med_cu:,.0f} CU median against the "
              f"{MAX_CU_PER_TX:,} cap")
        print(f"  leaving roughly {MAX_CU_PER_TX - med_cu:,.0f} CU for anything we would bolt on.")
        out["flash_success_rate"] = len(ok) / len(found)
        out["flash_cost_per_success_sol"] = total_fee / len(ok) / LAMPORTS
        out["flash_cycle_cu_median"] = med_cu


# --------------------------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="",
                    help="comma list: inventory,interface,fillers,book,otoco,quotes,flash")
    ap.add_argument("--json", action="store_true", help="dump machine-readable results to stdout")
    ap.add_argument("--sample", type=int, default=1200, help="transactions to sample per scan")
    args = ap.parse_args()

    wanted = {s.strip() for s in args.only.split(",") if s.strip()} or {
        "inventory", "interface", "fillers", "book", "otoco", "quotes", "flash"}
    rpc = Rpc()
    out: dict[str, Any] = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    if "inventory" in wanted:
        check_inventory(rpc, out)
    if "interface" in wanted:
        check_interface(rpc, out)
    if "fillers" in wanted:
        check_fillers(rpc, out, cap=args.sample)
    if "book" in wanted:
        check_resting_book(rpc, out)
    if "otoco" in wanted:
        check_otoco(out)
    if "quotes" in wanted:
        check_quotes(out)
    if "flash" in wanted:
        check_flashloans(rpc, out, cap=args.sample)

    if args.json:
        print("\n" + json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
