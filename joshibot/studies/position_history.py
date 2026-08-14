#!/usr/bin/env python3
"""The operator's complete position, reconstructed from chain across all five wallets.

WHY THIS EXISTS
---------------
Every financial number this project has produced was computed from a *partial* store: one
wallet, one window, one collector's view.  On 2026-08-13 a single session found eight separate
accounting defects and every one of them was plumbing -- a unit confusion, a sign, a
misclassified counterparty -- not a modelling choice.  The operator's framing is the right one:
"most of them are just bugs/flaws, not model misparameterizations."

The specific defect this file was built to kill is **counterparty misclassification**.  The
2026-08-12 reconstruction recorded a 4.47 SOL inbound transfer from ``PrvpTgc...`` as an
unidentified external counterparty.  ``PrvpTgc`` is the operator's own pre-migration wallet.
Money moved from the operator's left pocket to their right pocket and the books called it
income.  That is a *class* of bug, not an instance, and the only structural fix is to hold all
five wallets in one ledger and net the internal edges out by construction.

THE FIVE WALLETS (ownership stated by the operator)
---------------------------------------------------
    Sh1WNJ8g...  shitcoims      the live trading wallet
    Funv3Qdb...  tha funds      Meteora DLMM LP wallet
    PmpDh2BQ...  pumpfun main   SOL creator fees are withdrawn here
    Dev2GmPW...  Ember dev      DREGG token unlocks are deposited here
    PrvpTgcu...  og shitcoims   pre-migration wallet (Phantom era)

WHY RPC AND NOT BIGQUERY
------------------------
``scripts/bulk_history.py`` established a validated BigQuery path into
``crypto_solana_mainnet_us.Transactions``, and for pool-level tape it is the right tool by a
wide margin.  It is the wrong tool here, and the reason is worth recording so nobody re-derives
it: BigQuery bills by *column*, and the columns that carry wallet identity are the expensive
ones -- ``pre_token_balances``/``post_token_balances`` at ~114 GB/day each, ``accounts`` at
267 GB/day, ``balance_changes`` at 434 GB/day.  This reconstruction spans 2026-06-27 .. now,
49 days.  One column over that window is ~5.6 TB.  The free tier has ~171 GB left.

Measured instead: **2,009 signatures across all five wallets over their entire lifetimes.**
The whole history is smaller than a single day of one BigQuery column.  ``getSignaturesForAddress``
plus batched ``getTransaction`` costs a few thousand credits against a 10M/month plan.  When the
subject is five addresses rather than the whole chain, per-transaction RPC is both cheaper and
exact.

TOKEN-ACCOUNT CLOSURE -- the gap that would have silently eaten the DREGG unlocks
----------------------------------------------------------------------------------
``getSignaturesForAddress(owner)`` does **not** return every transaction that moves the owner's
tokens.  An SPL transfer names the *token account* (the ATA), the mint and the authority; when
somebody sends tokens **to** us, our owner pubkey need not appear in the transaction at all.
Enumerating only the five owner addresses therefore misses inbound token transfers -- which is
exactly what a DREGG unlock is, and (d) is the claim that nothing in this project has ever
accounted for.  So this tool runs a **fixed-point closure**: enumerate the owners, fetch, read
every ``pre/postTokenBalances`` entry whose ``owner`` is one of ours, resolve its
``accountIndex`` back to a pubkey, and re-enumerate on any token account not yet covered.
Repeat until a round discovers nothing.  ``getTokenAccountsByOwner`` seeds the currently-open
accounts; the closure finds the closed ones, which are invisible to that call and are where
history lives.

Resolving ``accountIndex`` is itself a place to go wrong: on a versioned transaction the index
addresses the *full* key list, which is static keys followed by ``meta.loadedAddresses.writable``
followed by ``meta.loadedAddresses.readonly``.  Using ``message.accountKeys`` alone silently
misattributes every ALT-using transaction, and aggregator-routed swaps all use ALTs.
:func:`full_account_keys` does it properly.

NO FLOATS IN THE LEDGER
-----------------------
Lamports and raw token base units are Python ``int`` end to end, per PROGRAM.md ss2.  Decimals
are applied only at the display boundary, and every USD figure carries the price and timestamp
used to produce it.  This is not fastidiousness: the raw-units/UI-amount/lamports/SOL confusion
is a live hazard in this codebase and has already cost real money.

READ-ONLY
---------
No signing, no sending, no keypair.  The only credential read is the Helius API key file, with
the same private-mode check ``shitcoims_intelligence/helius.py`` applies.  This module never
imports ``shitcoims_sentinel``.

USAGE
-----
    python3 studies/position_history.py fetch      # cached; safe to re-run
    python3 studies/position_history.py ledger     # build + classify, writes ledger.json
    python3 studies/position_history.py report     # the validations
"""

from __future__ import annotations

import argparse
import json
import stat
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Iterable

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / ".cache" / "position_history"

# --------------------------------------------------------------------------------------
# The subject
# --------------------------------------------------------------------------------------

WALLETS: Final[dict[str, str]] = {
    "Sh1WNJ8g68rXJGyDjVPcfxWN1WbMrLsgdXmSb6cccuE": "shitcoims",
    "Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ": "tha_funds",
    "PmpDh2BQCMMseKYPxseWTSoX3aAouHE4sWyFWTdkqYE": "pumpfun_main",
    "Dev2GmPW2Jv28KW8D7DLqh7TM9hRf8adTDF5p6Jk3CHc": "ember_dev",
    "PrvpTgcuAzN337qSmmKizTMSmhpLPJmZ5Vt8WKCzagf": "og_shitcoims",
}

WSOL: Final[str] = "So11111111111111111111111111111111111111112"
DREGG: Final[str] = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
WEAVE: Final[str] = "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump"
NOSIS: Final[str] = "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump"
SOLVE: Final[str] = "GwyWFsDKW9a2ref1EWqdUS7B37Toii433zrAh9Dipump"

SYMBOLS: Final[dict[str, str]] = {
    WSOL: "WSOL",
    DREGG: "DREGG",
    WEAVE: "weave",
    NOSIS: "nosis",
    SOLVE: "SOLVE",
}

TOKEN_PROGRAMS: Final[frozenset[str]] = frozenset(
    {
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    }
)

METEORA_DLMM: Final[str] = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
PUMPSWAP: Final[str] = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
PUMPFUN: Final[str] = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
JUPITER_V6: Final[str] = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
SYSTEM_PROGRAM: Final[str] = "11111111111111111111111111111111"

#: Programs whose presence means "this transaction is a swap", used only for labelling.
SWAP_PROGRAMS: Final[frozenset[str]] = frozenset(
    {PUMPSWAP, PUMPFUN, JUPITER_V6, METEORA_DLMM, "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"}
)


# --------------------------------------------------------------------------------------
# Credential + RPC
# --------------------------------------------------------------------------------------


def read_helius_key(path: Path = Path("~/.helius-key")) -> str:
    """The same private-file discipline as ``shitcoims_intelligence.helius._read_helius_key``.

    Duplicated rather than imported on purpose: this study must not couple its lifetime to a
    live module another agent may be editing, and the check is six lines.
    """

    path = path.expanduser()
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"Helius key path is not a regular file: {path}")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError(f"Helius key file must be 0600 or stricter: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value or any(c.isspace() for c in value):
        raise RuntimeError("Helius key file is empty or malformed")
    return value


class Rpc:
    """A minimal batching JSON-RPC client. Read methods only -- it cannot sign or send."""

    #: Methods this client is permitted to call. A hard allowlist rather than a convention,
    #: so that "read-only" is a property of the code and not of the caller's good intentions.
    ALLOWED: Final[frozenset[str]] = frozenset(
        {
            "getSignaturesForAddress",
            "getTransaction",
            "getBalance",
            "getTokenAccountsByOwner",
            "getTokenSupply",
            "getAccountInfo",
            "getMultipleAccounts",
            "getTokenAccountBalance",
        }
    )

    def __init__(self, key: str) -> None:
        self._url = f"https://mainnet.helius-rpc.com/?api-key={key}"
        self.calls = 0

    def _post(self, payload: Any) -> Any:
        body = json.dumps(payload).encode()
        last: Exception | None = None
        for attempt in range(6):
            try:
                req = urllib.request.Request(
                    self._url, data=body, headers={"content-type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return json.loads(resp.read())
            except Exception as exc:
                last = exc
                time.sleep(min(2 ** attempt, 20))
        raise RuntimeError(f"Helius RPC failed after retries: {type(last).__name__}")

    def call(self, method: str, params: list[Any]) -> Any:
        if method not in self.ALLOWED:
            raise RuntimeError(f"method {method!r} is not on the read-only allowlist")
        self.calls += 1
        out = self._post({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if "error" in out:
            raise RuntimeError(f"RPC error on {method}: {out['error']}")
        return out.get("result")

    def batch(self, method: str, param_list: list[list[Any]], *, size: int = 100) -> list[Any]:
        if method not in self.ALLOWED:
            raise RuntimeError(f"method {method!r} is not on the read-only allowlist")
        results: list[Any] = []
        for start in range(0, len(param_list), size):
            chunk = param_list[start : start + size]
            self.calls += len(chunk)
            payload = [
                {"jsonrpc": "2.0", "id": i, "method": method, "params": p}
                for i, p in enumerate(chunk)
            ]
            out = self._post(payload)
            if not isinstance(out, list):
                raise RuntimeError("batch RPC did not return a list")
            by_id = {item.get("id"): item for item in out}
            for i in range(len(chunk)):
                item = by_id.get(i, {})
                if "error" in item:
                    raise RuntimeError(f"RPC error in batch on {method}: {item['error']}")
                results.append(item.get("result"))
        return results


# --------------------------------------------------------------------------------------
# Transaction shape helpers
# --------------------------------------------------------------------------------------


def full_account_keys(tx: dict[str, Any]) -> list[str]:
    """The complete account-key list a ``accountIndex`` addresses.

    Static keys, then loaded-writable, then loaded-readonly. Getting this wrong misattributes
    every address-lookup-table transaction, and every aggregator-routed swap uses one.
    """

    message = tx.get("transaction", {}).get("message", {})
    keys: list[str] = []
    for entry in message.get("accountKeys") or []:
        keys.append(entry["pubkey"] if isinstance(entry, dict) else entry)
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    keys.extend(loaded.get("writable") or [])
    keys.extend(loaded.get("readonly") or [])
    return keys


def iter_instructions(tx: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Every instruction, top-level and inner, in one flat stream."""

    message = tx.get("transaction", {}).get("message", {})
    yield from message.get("instructions") or []
    for group in (tx.get("meta") or {}).get("innerInstructions") or []:
        yield from group.get("instructions") or []


def programs_touched(tx: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for ins in iter_instructions(tx):
        program_id = ins.get("programId")
        if isinstance(program_id, str):
            out.add(program_id)
    return out


# --------------------------------------------------------------------------------------
# Fetch: signature enumeration + token-account closure
# --------------------------------------------------------------------------------------


def signatures_for(rpc: Rpc, address: str) -> list[dict[str, Any]]:
    """Every signature for an address, oldest-last, following the ``before`` cursor.

    A short page is NOT the exhaustion signal for ``getSignaturesForAddress`` -- it is, unlike
    the Helius ``getTransactionsForAddress`` cursor, but only because this method has no
    server-side filter that can empty a page.  Stop on an empty page and on a short page both;
    the loop is idempotent either way because the cursor is a signature.
    """

    out: list[dict[str, Any]] = []
    before: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 1000}
        if before is not None:
            params["before"] = before
        page = rpc.call("getSignaturesForAddress", [address, params]) or []
        if not page:
            return out
        out.extend(page)
        before = page[-1]["signature"]
        if len(page) < 1000:
            return out
        if len(out) > 500_000:
            raise RuntimeError(f"signature list for {address} is implausibly long")


def token_accounts_now(rpc: Rpc, owner: str) -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    for program in TOKEN_PROGRAMS:
        res = rpc.call(
            "getTokenAccountsByOwner", [owner, {"programId": program}, {"encoding": "jsonParsed"}]
        )
        accounts.extend((res or {}).get("value") or [])
    return accounts


def cmd_fetch(args: argparse.Namespace) -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    tx_dir = CACHE / "tx"
    tx_dir.mkdir(exist_ok=True)
    rpc = Rpc(read_helius_key())

    # Seed the address frontier with the owners and their currently-open token accounts.
    frontier: set[str] = set(WALLETS)
    holdings: dict[str, list[dict[str, Any]]] = {}
    for owner in WALLETS:
        accounts = token_accounts_now(rpc, owner)
        holdings[owner] = accounts
        frontier.update(a["pubkey"] for a in accounts)
    (CACHE / "holdings_now.json").write_text(json.dumps(holdings, indent=1))

    covered: set[str] = set()
    all_sigs: dict[str, dict[str, Any]] = {}
    have: set[str] = {p.stem for p in tx_dir.glob("*.json")}

    for round_index in range(12):
        todo = sorted(frontier - covered)
        if not todo:
            break
        print(f"[fetch] round {round_index}: {len(todo)} new addresses", file=sys.stderr)
        for address in todo:
            for record in signatures_for(rpc, address):
                all_sigs.setdefault(record["signature"], record)
            covered.add(address)

        missing = sorted(set(all_sigs) - have)
        print(f"[fetch] {len(all_sigs)} signatures, {len(missing)} to download", file=sys.stderr)
        for start in range(0, len(missing), 100):
            chunk = missing[start : start + 100]
            params = [
                [s, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}] for s in chunk
            ]
            for signature, tx in zip(chunk, rpc.batch("getTransaction", params), strict=True):
                if tx is None:
                    print(f"[fetch] WARNING: {signature} returned null", file=sys.stderr)
                    continue
                (tx_dir / f"{signature}.json").write_text(json.dumps(tx))
                have.add(signature)
            print(f"[fetch]   {min(start + 100, len(missing))}/{len(missing)}", file=sys.stderr)

        # Closure step: any token account owned by one of ours, seen anywhere, joins the frontier.
        for signature in sorted(have):
            tx = json.loads((tx_dir / f"{signature}.json").read_text())
            keys = full_account_keys(tx)
            meta = tx.get("meta") or {}
            for side in ("preTokenBalances", "postTokenBalances"):
                for entry in meta.get(side) or []:
                    if entry.get("owner") in WALLETS:
                        index = entry.get("accountIndex")
                        if isinstance(index, int) and 0 <= index < len(keys):
                            frontier.add(keys[index])
    else:
        raise RuntimeError("token-account closure did not converge in 12 rounds")

    (CACHE / "signatures.json").write_text(json.dumps(all_sigs, indent=1))
    (CACHE / "covered_addresses.json").write_text(json.dumps(sorted(covered), indent=1))
    print(
        f"[fetch] done: {len(covered)} addresses, {len(all_sigs)} signatures, "
        f"{len(have)} transactions cached, {rpc.calls} RPC calls",
        file=sys.stderr,
    )
    return 0


# --------------------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------------------


@dataclass
class TxLedger:
    """One transaction's complete effect on the operator's five wallets.

    ``sol`` is in lamports and ``tokens`` in raw base units, both signed, both exact integers.
    ``sol`` for the fee payer is net of the transaction fee, which is the correct treatment:
    the fee is a real cost the operator paid and belongs in the position.
    """

    signature: str
    slot: int
    block_time: int | None
    err: Any
    fee: int
    fee_payer: str
    sol: dict[str, int] = field(default_factory=dict)
    tokens: dict[tuple[str, str], int] = field(default_factory=dict)
    programs: set[str] = field(default_factory=set)
    kind: str = "unclassified"
    counterparties: set[str] = field(default_factory=set)

    @property
    def is_internal(self) -> bool:
        """True when every SOL and token leg nets to ~zero across our own five wallets.

        The rent-exempt/fee residue means an internal SOL transfer does not net to exactly
        zero -- the network takes 5,000 lamports and an ATA creation takes ~2,039,280.  So the
        test is "does the value move stay inside the set", implemented as: some wallet gained,
        some wallet lost, and no external counterparty received value.
        """

        return self.kind.startswith("internal")


def build_ledger() -> list[TxLedger]:
    tx_dir = CACHE / "tx"
    ledgers: list[TxLedger] = []
    for path in tx_dir.glob("*.json"):
        tx = json.loads(path.read_text())
        meta = tx.get("meta") or {}
        keys = full_account_keys(tx)
        entry = TxLedger(
            signature=path.stem,
            slot=int(tx.get("slot") or 0),
            block_time=tx.get("blockTime"),
            err=meta.get("err"),
            fee=int(meta.get("fee") or 0),
            fee_payer=keys[0] if keys else "",
            programs=programs_touched(tx),
        )
        pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
        for index, key in enumerate(keys):
            if key in WALLETS and index < len(pre) and index < len(post):
                delta = int(post[index]) - int(pre[index])
                if delta:
                    entry.sol[key] = entry.sol.get(key, 0) + delta

        raw: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        for side, slot_index in (("preTokenBalances", 0), ("postTokenBalances", 1)):
            for item in meta.get(side) or []:
                owner = item.get("owner")
                if owner not in WALLETS:
                    continue
                mint = item.get("mint")
                amount = int((item.get("uiTokenAmount") or {}).get("amount") or 0)
                raw[(owner, mint)][slot_index] += amount
        for (owner, mint), (before, after) in raw.items():
            if after - before:
                entry.tokens[(owner, mint)] = after - before

        classify(tx, entry, keys)
        ledgers.append(entry)

    ledgers.sort(key=lambda e: (e.block_time or 0, e.slot))
    return ledgers


def classify(tx: dict[str, Any], entry: TxLedger, keys: list[str]) -> None:
    """Assign a kind, and record who the value actually moved to or from.

    The classification that matters is ``internal_*``: a movement between two of the
    operator's own wallets is neither income nor loss, and calling it either is the exact
    defect this study was commissioned to find.
    """

    meta = tx.get("meta") or {}

    # Who else moved value in this transaction? Read the parsed transfer instructions rather
    # than inferring from balance deltas, because a delta cannot name a counterparty.
    external: set[str] = set()
    internal_pairs = 0
    for ins in iter_instructions(tx):
        parsed = ins.get("parsed")
        if not isinstance(parsed, dict):
            continue
        info = parsed.get("info") or {}
        kind = parsed.get("type")
        src = info.get("source") or info.get("from")
        dst = info.get("destination") or info.get("to")
        authority = info.get("authority") or info.get("owner") or info.get("multisigAuthority")
        if kind in {"transfer", "transferChecked", "transferWithSeed"}:
            # For SPL transfers the source/destination are token accounts, so resolve to
            # owners through the balance records where possible.
            src_owner = owner_of_token_account(meta, keys, src) or src
            dst_owner = owner_of_token_account(meta, keys, dst) or dst
            if src_owner in WALLETS and dst_owner in WALLETS:
                internal_pairs += 1
            else:
                for party in (src_owner, dst_owner):
                    if party and party not in WALLETS:
                        external.add(party)
            if authority in WALLETS and dst_owner not in WALLETS and dst_owner:
                external.add(dst_owner)

    entry.counterparties = external

    swap = bool(entry.programs & SWAP_PROGRAMS)
    dlmm = METEORA_DLMM in entry.programs
    sol_in = sum(v for v in entry.sol.values() if v > 0)
    sol_out = -sum(v for v in entry.sol.values() if v < 0)
    token_moved = any(entry.tokens.values())

    if entry.err is not None:
        entry.kind = "failed"
    elif dlmm:
        entry.kind = "lp_dlmm"
    elif swap:
        entry.kind = "swap"
    elif internal_pairs and not external:
        entry.kind = "internal_transfer"
    elif not external and not token_moved and len(entry.sol) >= 2:
        # Pure SOL movement whose only participants are ours: system transfers between our
        # wallets show up here when the parsed instruction stream is a plain system transfer.
        entry.kind = "internal_transfer"
    elif token_moved and sol_in == 0 and sol_out <= entry.fee + 2_100_000:
        entry.kind = "token_transfer"
    elif sol_in > sol_out:
        entry.kind = "sol_in"
    elif sol_out > sol_in:
        entry.kind = "sol_out"
    else:
        entry.kind = "other"

    # A system transfer between two of ours is internal regardless of what else the
    # transaction did, and it is worth naming separately from a token-side internal move.
    if entry.kind in {"sol_in", "sol_out", "token_transfer", "other"}:
        senders = {k for k, v in entry.sol.items() if v < 0}
        receivers = {k for k, v in entry.sol.items() if v > 0}
        if senders and receivers and not external:
            entry.kind = "internal_transfer"


def owner_of_token_account(
    meta: dict[str, Any], keys: list[str], account: str | None
) -> str | None:
    """Resolve a token account pubkey to its owner using the transaction's own balance records."""

    if account is None:
        return None
    for side in ("preTokenBalances", "postTokenBalances"):
        for item in meta.get(side) or []:
            index = item.get("accountIndex")
            if isinstance(index, int) and 0 <= index < len(keys) and keys[index] == account:
                return item.get("owner")
    return None


def cmd_ledger(args: argparse.Namespace) -> int:
    ledgers = build_ledger()
    out = {
        "built_at": datetime.now(UTC).isoformat(),
        "transactions": len(ledgers),
        "entries": [
            {
                "signature": e.signature,
                "slot": e.slot,
                "block_time": e.block_time,
                "iso": iso(e.block_time),
                "kind": e.kind,
                "err": e.err,
                "fee": e.fee,
                "fee_payer": WALLETS.get(e.fee_payer, e.fee_payer),
                "sol": {WALLETS[k]: v for k, v in e.sol.items()},
                "tokens": {f"{WALLETS[o]}|{m}": v for (o, m), v in e.tokens.items()},
                "programs": sorted(e.programs),
                "counterparties": sorted(e.counterparties),
            }
            for e in ledgers
        ],
    }
    (CACHE / "ledger.json").write_text(json.dumps(out, indent=1))
    counts: dict[str, int] = defaultdict(int)
    for e in ledgers:
        counts[e.kind] += 1
    for kind, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"{kind:22s} {n:5d}")
    print(f"{'TOTAL':22s} {len(ledgers):5d}")
    return 0


def iso(block_time: int | None) -> str | None:
    if not block_time:
        return None
    return datetime.fromtimestamp(block_time, UTC).isoformat()


# --------------------------------------------------------------------------------------
# Attribution
# --------------------------------------------------------------------------------------

#: The pump.fun fee program. Creator fees do NOT arrive as a system transfer -- the program
#: reassigns lamports on the PDA directly -- so the parsed instruction stream shows nothing
#: and only the balance delta records them. Attribution is therefore by *instruction name*
#: read from the log, which is why this study parses ``Program log: Instruction: X``.
PUMP_FEE_PROGRAM: Final[str] = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"

#: Log-line instruction names that mean "creator fee arrived".
CREATOR_FEE_IX: Final[frozenset[str]] = frozenset(
    {"ClaimSocialFeePda", "ClaimSocialFeePdaV2", "DistributeCreatorFees", "DistributeCreatorFeesV2"}
)
LP_FEE_IX: Final[frozenset[str]] = frozenset({"ClaimFee", "ClaimFee2"})
LP_ADD_IX: Final[frozenset[str]] = frozenset(
    {"AddLiquidityByStrategy", "AddLiquidityByStrategy2", "AddLiquidity", "RebalanceLiquidity"}
)
LP_REMOVE_IX: Final[frozenset[str]] = frozenset(
    {"RemoveLiquidity", "RemoveLiquidityByRange", "RemoveLiquidityByRange2", "ClosePositionIfEmpty"}
)

#: The operator's Coinbase receiving address, **confirmed by the operator**. Chain shape agrees
#: and is worth recording because it is what distinguishes this address from the three below:
#: near-zero balance, immediate forward of everything received, and -- the discriminating
#: property -- it receives *essentially only from us*. A per-user exchange deposit address has
#: exactly one depositor. Flows here are the operator moving their own capital: outbound is
#: cashing out, inbound is funding from off-chain, and **neither belongs in PnL**.
COINBASE: Final[str] = "Cbx3NneVa8dKpFbWJeVGARH9pmx4ZttdAfWVqm3HP3Eh"

#: Three further high-throughput destinations that took 223.35 SOL between 2026-06-28 and
#: 2026-07-28, after which payments to them **stop dead** and 100% of claimed fees go to
#: Coinbase instead.
#:
#: The first draft of this study lumped them in with Coinbase as "exchange-deposit-shaped".
#: **That was wrong and is retracted.** Sampling their recent history distinguishes them
#: sharply from ``COINBASE``: each receives from 4-8 *distinct* senders, none of which are the
#: operator's wallets. A per-user deposit address has one depositor; these are shared. What
#: they are is **not resolvable from chain** and is deliberately not guessed at here -- they
#: are simply not classifiable as treasury movement, which is the only claim the first draft
#: made and the only one that had to be withdrawn.
UNIDENTIFIED_HUBS: Final[dict[str, str]] = {
    "WYoLt8fH8NzZWwuU3JqiVNDWoa8mvFDHY3qB8uwYhB1": "unidentified, 84.997 SOL, ends 2026-07-23",
    "Drg3Mo7KksZLEJFUbcamAv46AqZZb9oCKodxQP6D2Dbq": "unidentified, 82.328 SOL, ends 2026-07-28",
    "6RTFsqEWgZsqWePk5F1aZVKK42DjCdZDGE6ZG4H5aXXn": "unidentified, 56.022 SOL, ends 2026-07-26",
}

SWEEP_HUBS: Final[dict[str, str]] = {COINBASE: "Coinbase (operator-confirmed)", **UNIDENTIFIED_HUBS}

#: The two accounts that actually PAY the creator fees. Identified by finding which account's
#: lamports *decrease* in each inflow transaction -- the only test that cannot be fooled by a
#: program merely appearing in ``accountKeys``.
#:
#: ``FEE_VAULT_DREGG`` is a **WSOL token account**; wrapped SOL keeps its value in the token
#: account's own lamports, which is why a fee payment shows as a lamport delta on a token
#: account and never as a parsed ``system.transfer``. The DREGG mint is present in **154 of
#: 154** transactions it funds.
#:
#: ``FEE_VAULT_SOCIAL`` is a 179-byte account owned by the pump.fun fee program carrying the
#: ASCII social-account id ``704250``. It funds 104 transactions and **carries no coin mint at
#: all**, so its 287.235 SOL is not attributable to DREGG and would not appear on any single
#: coin's page.
FEE_VAULT_DREGG: Final[str] = "2dQa7pRL8czyJJsQfGyMBacqf9FSV96cwirov5KyUE4A"
FEE_VAULT_SOCIAL: Final[str] = "8buZegTzEGrEPvHLyeJfP3ppcUFiuPHvTHGCArVcV7kF"

#: The Streamflow vesting escrow holding the operator's own locked DREGG. A bare token transfer
#: into it is a LOCK, not a distribution -- the tokens stay the operator's and vest back to
#: ``ember_dev``. Counting it as a giveaway would inflate the distributed figure 3.5x.
STREAMFLOW_ESCROW: Final[str] = "9Go2paWtmAMK4sJnQ2RJ7BZ3QsGE6FSz5Ec5NZc8ZBhK"
STREAMFLOW_PROGRAM: Final[str] = "strmRqUCoQUgy2XeFptbhSJH2sfF4uYdgLcaAdEbQaQ"

BUCKETS: Final[tuple[str, ...]] = (
    "creator_fee",
    "lp_fee",
    "lp_deposit",
    "lp_withdraw",
    "swap",
    "internal_in",
    "internal_out",
    "external_in",
    "external_out",
    "gas",
    "rent_and_other",
)


def instruction_names(tx: dict[str, Any]) -> set[str]:
    """Anchor instruction names as the programs themselves logged them.

    Preferred over discriminator tables: the name is what the program printed, so it cannot
    drift out of sync with an IDL we do not control, and pump.fun has already shipped V2
    variants of half these instructions during the window this study covers.
    """

    import re

    logs = "\n".join((tx.get("meta") or {}).get("logMessages") or [])
    return set(re.findall(r"Program log: Instruction: (\w+)", logs))


def attribute(tx: dict[str, Any], entry: TxLedger) -> dict[str, dict[str, int]]:
    """Split each wallet's SOL delta into buckets that sum back to the delta EXACTLY.

    The decomposition is: parsed system transfers are attributed by counterparty (internal vs
    external), the transaction fee is attributed to ``gas``, and whatever remains -- the part
    the *programs* moved, which is where creator fees and swap proceeds live -- is attributed
    by instruction name.  Because the residual is computed rather than matched, the buckets
    reconcile to the lamport by construction and an unattributable flow shows up as
    ``rent_and_other`` rather than silently vanishing.
    """

    meta = tx.get("meta") or {}
    keys = full_account_keys(tx)
    names = instruction_names(tx)
    out: dict[str, dict[str, int]] = {w: dict.fromkeys(BUCKETS, 0) for w in entry.sol}

    for wallet in entry.sol:
        out[wallet]["gas"] = -entry.fee if wallet == entry.fee_payer else 0

    # Two ways a naive counterparty rule turns the operator's own plumbing into a payment to a
    # stranger, both of which materially inflate any "how much did we give away" figure:
    #
    #  1. **Wrapping SOL.** Depositing SOL into a DLMM position is a ``system.transfer`` to the
    #     wallet's own WSOL token account, whose *address* is an ATA and is therefore not in
    #     WALLETS.  Resolving the destination through the transaction's own token-balance owner
    #     records fixes it; without that, 77 SOL of LP deposits read as gifts.
    #  2. **Protocol plumbing.** Inside a swap or an LP action the system transfers are rent,
    #     wrapping and vault funding -- the operation itself, not a discretionary payment.  Only
    #     a BARE transfer, in a transaction that invoked no DEX and no LP instruction, can be a
    #     distribution to a third party.
    owner_of: dict[str, str | None] = {}
    for side in ("preTokenBalances", "postTokenBalances"):
        for item in meta.get(side) or []:
            index = item.get("accountIndex")
            if isinstance(index, int) and 0 <= index < len(keys):
                owner_of[keys[index]] = item.get("owner")

    is_protocol = bool(entry.programs & SWAP_PROGRAMS) or bool(
        names & (LP_ADD_IX | LP_REMOVE_IX | LP_FEE_IX | CREATOR_FEE_IX)
    )
    for ins in () if is_protocol else iter_instructions(tx):
        parsed = ins.get("parsed")
        if not isinstance(parsed, dict) or parsed.get("type") not in {"transfer", "transferWithSeed"}:
            continue
        if ins.get("program") != "system":
            continue
        info = parsed.get("info") or {}
        src, dst = info.get("source"), info.get("destination")
        src = owner_of.get(src, src)
        dst = owner_of.get(dst, dst)
        lamports = int(info.get("lamports") or 0)
        if src in out:
            out[src]["internal_out" if dst in WALLETS else "external_out"] -= lamports
        if dst in out:
            out[dst]["internal_in" if src in WALLETS else "external_in"] += lamports

    for wallet, delta in entry.sol.items():
        residual = delta - sum(out[wallet].values())
        if residual == 0:
            continue
        if names & CREATOR_FEE_IX and residual > 0:
            bucket = "creator_fee"
        elif names & LP_FEE_IX and not (names & LP_REMOVE_IX):
            bucket = "lp_fee"
        elif names & LP_REMOVE_IX:
            bucket = "lp_withdraw"
        elif names & LP_ADD_IX:
            bucket = "lp_deposit"
        elif entry.programs & SWAP_PROGRAMS:
            bucket = "swap"
        else:
            bucket = "rent_and_other"
        out[wallet][bucket] += residual

    return out


def attribute_tokens(tx: dict[str, Any], entry: TxLedger) -> dict[tuple[str, str], dict[str, int]]:
    """The same decomposition for token deltas, in raw base units."""

    meta = tx.get("meta") or {}
    keys = full_account_keys(tx)
    names = instruction_names(tx)
    owner_of: dict[str, str | None] = {}
    for side in ("preTokenBalances", "postTokenBalances"):
        for item in meta.get(side) or []:
            index = item.get("accountIndex")
            if isinstance(index, int) and 0 <= index < len(keys):
                owner_of[keys[index]] = item.get("owner")

    out: dict[tuple[str, str], dict[str, int]] = {
        k: dict.fromkeys(BUCKETS, 0) for k in entry.tokens
    }

    # A swap or an LP action moves tokens with ordinary SPL transfers into accounts owned by
    # the pool -- which is an address we do not own, so a naive counterparty rule books every
    # swap leg as a gift to a stranger.  That single mistake would have reported ~121M DREGG
    # of "distributions" that were in fact sell-side swap legs.  Inside a DEX transaction the
    # transfers ARE the operation, so attribution falls through to the instruction bucket and
    # only genuinely bare transfers are counterparty-classified.
    is_protocol = bool(entry.programs & SWAP_PROGRAMS) or bool(
        names & (LP_ADD_IX | LP_REMOVE_IX | LP_FEE_IX | CREATOR_FEE_IX)
    )
    for ins in () if is_protocol else iter_instructions(tx):
        parsed = ins.get("parsed")
        if not isinstance(parsed, dict) or parsed.get("type") not in {"transfer", "transferChecked"}:
            continue
        if ins.get("program") == "system":
            continue
        info = parsed.get("info") or {}
        src, dst = info.get("source"), info.get("destination")
        amount = int(info.get("amount") or (info.get("tokenAmount") or {}).get("amount") or 0)
        src_owner, dst_owner = owner_of.get(src), owner_of.get(dst)
        mint = info.get("mint")
        if mint is None:
            for candidate in (src, dst):
                for side in ("preTokenBalances", "postTokenBalances"):
                    for item in meta.get(side) or []:
                        index = item.get("accountIndex")
                        if isinstance(index, int) and index < len(keys) and keys[index] == candidate:
                            mint = item.get("mint")
        if mint is None:
            continue
        if (src_owner, mint) in out:
            key = "internal_out" if dst_owner in WALLETS else "external_out"
            out[(src_owner, mint)][key] -= amount
        if (dst_owner, mint) in out:
            key = "internal_in" if src_owner in WALLETS else "external_in"
            out[(dst_owner, mint)][key] += amount

    for key, delta in entry.tokens.items():
        residual = delta - sum(out[key].values())
        if residual == 0:
            continue
        if names & LP_FEE_IX and not (names & LP_REMOVE_IX):
            bucket = "lp_fee"
        elif names & LP_REMOVE_IX:
            bucket = "lp_withdraw"
        elif names & LP_ADD_IX:
            bucket = "lp_deposit"
        elif entry.programs & SWAP_PROGRAMS:
            bucket = "swap"
        else:
            bucket = "rent_and_other"
        out[key][bucket] += residual

    return out


def cmd_report(args: argparse.Namespace) -> int:
    ledgers = build_ledger()
    tx_dir = CACHE / "tx"
    sol_book: dict[str, dict[str, int]] = {w: dict.fromkeys(BUCKETS, 0) for w in WALLETS}
    tok_book: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: dict.fromkeys(BUCKETS, 0)
    )
    for entry in ledgers:
        tx = json.loads((tx_dir / f"{entry.signature}.json").read_text())
        for wallet, buckets in attribute(tx, entry).items():
            for bucket, value in buckets.items():
                sol_book[wallet][bucket] += value
        for key, buckets in attribute_tokens(tx, entry).items():
            for bucket, value in buckets.items():
                tok_book[key][bucket] += value

    print("=" * 96)
    print("SOL BOOK, lamports -> SOL, by wallet and bucket. Columns sum to the live balance.")
    print("=" * 96)
    header = f"{'bucket':16s}" + "".join(f"{WALLETS[w]:>15s}" for w in WALLETS) + f"{'TOTAL':>15s}"
    print(header)
    for bucket in BUCKETS:
        row = [sol_book[w][bucket] for w in WALLETS]
        if not any(row):
            continue
        print(f"{bucket:16s}" + "".join(f"{v/1e9:>15.6f}" for v in row) + f"{sum(row)/1e9:>15.6f}")
    totals = [sum(sol_book[w].values()) for w in WALLETS]
    print("-" * 96)
    print(
        f"{'NET (= balance)':16s}"
        + "".join(f"{v/1e9:>15.6f}" for v in totals)
        + f"{sum(totals)/1e9:>15.6f}"
    )

    print()
    print("=" * 96)
    print("TOKEN BOOK, raw base units -> UI units, by mint. Rows sum to the live balance.")
    print("=" * 96)
    agg: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(BUCKETS, 0))
    for (_owner, mint), buckets in tok_book.items():
        for bucket, value in buckets.items():
            agg[mint][bucket] += value
    interesting = sorted(agg, key=lambda m: -max(abs(v) for v in agg[m].values()))
    print(f"{'mint':14s}{'lp_deposit':>16s}{'lp_withdraw':>16s}{'lp_fee':>14s}{'swap':>16s}{'ext_out':>16s}{'ext_in':>14s}{'NET':>14s}")
    for mint in interesting[:14]:
        b = agg[mint]
        net = sum(b.values())
        print(
            f"{SYMBOLS.get(mint, mint[:12]):14s}"
            f"{b['lp_deposit']/1e6:>16,.0f}{b['lp_withdraw']/1e6:>16,.0f}{b['lp_fee']/1e6:>14,.0f}"
            f"{b['swap']/1e6:>16,.0f}{b['external_out']/1e6:>16,.0f}{b['external_in']/1e6:>14,.0f}"
            f"{net/1e6:>14,.2f}"
        )

    print()
    print("=" * 96)
    print("EXTERNAL OUTFLOW, split treasury-movement vs discretionary distribution")
    print("=" * 96)
    sol_to: dict[str, int] = defaultdict(int)
    sol_n: dict[str, int] = defaultdict(int)
    tok_to: dict[tuple[str, str], int] = defaultdict(int)
    for entry in ledgers:
        tx = json.loads((tx_dir / f"{entry.signature}.json").read_text())
        names = instruction_names(tx)
        if (entry.programs & SWAP_PROGRAMS) or (
            names & (LP_ADD_IX | LP_REMOVE_IX | LP_FEE_IX | CREATOR_FEE_IX)
        ):
            continue
        meta = tx.get("meta") or {}
        keys = full_account_keys(tx)
        owner_of: dict[str, str | None] = {}
        mint_of: dict[str, str | None] = {}
        for side in ("preTokenBalances", "postTokenBalances"):
            for item in meta.get(side) or []:
                index = item.get("accountIndex")
                if isinstance(index, int) and 0 <= index < len(keys):
                    owner_of[keys[index]] = item.get("owner")
                    mint_of[keys[index]] = item.get("mint")
        for ins in iter_instructions(tx):
            parsed = ins.get("parsed")
            if not isinstance(parsed, dict) or parsed.get("type") not in {"transfer", "transferChecked"}:
                continue
            info = parsed.get("info") or {}
            src, dst = info.get("source"), info.get("destination")
            src_owner = owner_of.get(src, src)
            dst_owner = owner_of.get(dst, dst)
            if src_owner not in WALLETS or dst_owner in WALLETS:
                continue
            if ins.get("program") == "system":
                sol_to[dst_owner] += int(info.get("lamports") or 0)
                sol_n[dst_owner] += 1
            else:
                mint = info.get("mint") or mint_of.get(src) or mint_of.get(dst)
                amount = int(info.get("amount") or (info.get("tokenAmount") or {}).get("amount") or 0)
                if mint:
                    tok_to[(dst_owner, mint)] += amount

    hub_sol = sum(v for a, v in sol_to.items() if a in SWEEP_HUBS)
    other_sol = sum(v for a, v in sol_to.items() if a not in SWEEP_HUBS)
    print(
        f"  SOL to sweep hubs (treasury/off-ramp) : {hub_sol/1e9:12.4f} SOL"
        f" over {len(SWEEP_HUBS)} addresses"
    )
    print(f"  SOL to everyone else (distributions)  : {other_sol/1e9:12.4f} SOL over "
          f"{sum(1 for a in sol_to if a not in SWEEP_HUBS)} addresses")
    one_shot = [a for a, n in sol_n.items() if n == 1 and a not in SWEEP_HUBS]
    print(f"    of which one-shot recipients        : {sum(sol_to[a] for a in one_shot)/1e9:12.4f} SOL "
          f"over {len(one_shot)} addresses")
    for mint in {m for _, m in tok_to}:
        total = sum(v for (a, m), v in tok_to.items() if m == mint)
        locked = sum(v for (a, m), v in tok_to.items() if m == mint and a == STREAMFLOW_ESCROW)
        hub = sum(v for (a, m), v in tok_to.items() if m == mint and a in SWEEP_HUBS)
        recipients = {a for (a, m) in tok_to if m == mint}
        if total - locked - hub < 1_000_000:
            continue
        print(
            f"  {SYMBOLS.get(mint, mint[:12]):12s} out {total/1e6:>16,.0f}"
            f" | vesting-lock {locked/1e6:>14,.0f} | hubs {hub/1e6:>12,.0f}"
            f" | DISTRIBUTED {(total-locked-hub)/1e6:>14,.0f} to {len(recipients)} addresses"
        )

    (CACHE / "book.json").write_text(
        json.dumps(
            {
                "sol": {WALLETS[w]: b for w, b in sol_book.items()},
                "tokens": {f"{WALLETS[o]}|{m}": b for (o, m), b in tok_book.items()},
                "external_sol_out": {a: v for a, v in sorted(sol_to.items(), key=lambda kv: -kv[1])},
                "external_token_out": {f"{a}|{m}": v for (a, m), v in tok_to.items()},
            },
            indent=1,
        )
    )
    return 0


def cmd_fees(args: argparse.Namespace) -> int:
    """Split the creator-fee stream by the account that actually PAID it, and trace it out.

    This exists because the first version of this study attributed fees by asking "does the
    pump.fun fee program appear in this transaction?", which is a much weaker test than it
    looks: the program appears in every claim *attempt*, including the ones that pay nothing.
    Asking instead "whose lamports went down?" is unfoolable, and it splits one 757 SOL
    aggregate into two streams with different coin identities.
    """

    pumpfun = next(k for k, v in WALLETS.items() if v == "pumpfun_main")
    tx_dir = CACHE / "tx"
    inflow: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    counts: dict[str, int] = defaultdict(int)
    outflow: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    usdc_moved = 0
    no_fee_logs = 0

    for entry in build_ledger():
        tx = json.loads((tx_dir / f"{entry.signature}.json").read_text())
        meta = tx.get("meta") or {}
        keys = full_account_keys(tx)
        month = (iso(entry.block_time) or "?")[:7]
        delta = entry.sol.get(pumpfun, 0)

        if delta > 0:
            balances = zip(
                meta.get("preBalances") or [], meta.get("postBalances") or [], strict=False
            )
            payers = [
                keys[i]
                for i, (before, after) in enumerate(balances)
                if after - before < -1_000_000 and keys[i] != pumpfun
            ]
            if FEE_VAULT_DREGG in payers:
                stream = "DREGG coin vault"
            elif FEE_VAULT_SOCIAL in payers:
                stream = "social-fee PDA 704250"
            else:
                stream = "other"
            inflow[stream][month] += delta
            counts[stream] += 1
            if "No fees available to claim" in "\n".join(meta.get("logMessages") or []):
                no_fee_logs += 1
            usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            pre = {b["accountIndex"]: int((b["uiTokenAmount"] or {}).get("amount") or 0)
                   for b in meta.get("preTokenBalances") or [] if b.get("mint") == usdc}
            post = {b["accountIndex"]: int((b["uiTokenAmount"] or {}).get("amount") or 0)
                    for b in meta.get("postTokenBalances") or [] if b.get("mint") == usdc}
            usdc_moved += sum(abs(post.get(i, 0) - pre.get(i, 0)) for i in set(pre) | set(post))

        for ins in iter_instructions(tx):
            parsed = ins.get("parsed")
            if not isinstance(parsed, dict) or parsed.get("type") != "transfer":
                continue
            info = parsed.get("info") or {}
            if info.get("source") != pumpfun:
                continue
            dest = info.get("destination")
            label = (
                "Coinbase" if dest == COINBASE
                else "3 unidentified hubs" if dest in UNIDENTIFIED_HUBS
                else "own wallets" if dest in WALLETS
                else "everything else"
            )
            outflow[label][month] += int(info.get("lamports") or 0)

    months = sorted({m for s in inflow.values() for m in s} | {m for s in outflow.values() for m in s})
    print("CREATOR-FEE INFLOW to pumpfun_main, by the account that PAID it (SOL)")
    print(f"{'stream':26s}" + "".join(f"{m:>12s}" for m in months) + f"{'TOTAL':>12s}{'txs':>6s}")
    for stream in ("DREGG coin vault", "social-fee PDA 704250", "other"):
        row = [inflow[stream][m] for m in months]
        print(f"{stream:26s}" + "".join(f"{v/1e9:>12.4f}" for v in row)
              + f"{sum(row)/1e9:>12.4f}{counts[stream]:>6d}")
    grand = sum(sum(s.values()) for s in inflow.values())
    print(f"{'TOTAL':26s}" + " " * (12 * len(months)) + f"{grand/1e9:>12.4f}")
    print(f"\n  USDC that actually moved across every inflow transaction: {usdc_moved/1e6:.6f}")
    print(f"  inflow transactions logging 'No fees available to claim': {no_fee_logs}")

    print("\nOUTFLOW from pumpfun_main (SOL)")
    print(f"{'destination':26s}" + "".join(f"{m:>12s}" for m in months) + f"{'TOTAL':>12s}")
    for label in ("Coinbase", "3 unidentified hubs", "own wallets", "everything else"):
        row = [outflow[label][m] for m in months]
        print(f"{label:26s}" + "".join(f"{v/1e9:>12.4f}" for v in row) + f"{sum(row)/1e9:>12.4f}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch").set_defaults(func=cmd_fetch)
    sub.add_parser("ledger").set_defaults(func=cmd_ledger)
    sub.add_parser("report").set_defaults(func=cmd_report)
    sub.add_parser("fees").set_defaults(func=cmd_fees)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
