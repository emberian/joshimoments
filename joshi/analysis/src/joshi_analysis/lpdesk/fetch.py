"""The bounded acquisition: everything the desk's arithmetic reads, retained first.

One call to :func:`acquire` runs the whole plan against a :class:`.rpc.RetainingSession`
whose budget the caller declares. The plan, in order, cheapest and most identifying first:

1. the pool's ``LbPair`` account and both mint accounts (decimals are not in pool bytes);
2. the pool's oracle ring — the long price path at observation cadence;
3. her open positions on this pool (``getProgramAccounts``, two memcmp filters);
4. bin arrays covering the open positions and the active bin (NAV and active-bin TVL);
5. per-position signature histories, then the wallet's recent signatures;
6. transaction bodies: every open-position transaction, plus the most recent wallet
   transactions up to a declared cap (closed-position recenters live here), plus the most
   recent contiguous pool window up to a declared cap (the dense swap tape).

Every response is already on disk (the session retains before returning) — this module
additionally writes a small ``manifest.json`` naming what was fetched, when, and what was
NOT (caps hit, budget left), because an absence unstated becomes a lie later.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

from .layouts import METEORA_DLMM_PROGRAM_ID
from .rpc import BudgetExhausted, RetainingSession
from .vocabulary import RETENTION_CONTRACT

__all__ = ["acquire"]

_TX_OPTS = {
    "encoding": "jsonParsed",
    "maxSupportedTransactionVersion": 0,
    "commitment": "confirmed",
}


def _mint_decimals(account_info_value: dict) -> int:
    """Decimals from an SPL mint account (byte 44 of the classic mint layout)."""
    data = base64.b64decode(account_info_value["data"][0])
    return data[44]


def acquire(
    session: RetainingSession,
    *,
    pool: str,
    wallet: str,
    wallet_body_cap: int = 90,
    pool_tape_cap: int = 110,
    pool_signature_pages: int = 3,
) -> dict:
    """Runs the plan; returns the manifest dict (also written to the retention dir)."""
    manifest: dict = {
        "contract": RETENTION_CONTRACT,
        "pool": pool,
        "wallet": wallet,
        "started_unix_ms": int(time.time() * 1000),
        "absences": [],
    }

    pool_info = session.call("getAccountInfo", [pool, {"encoding": "base64"}])
    pool_value = pool_info["value"]
    manifest["pool_account"] = {"slot": pool_info["context"]["slot"]}

    # Mints: offsets straight from the LbPair layout to avoid a decode dependency here.
    raw = base64.b64decode(pool_value["data"][0])
    token_x_mint = _b58(raw[88:120])
    token_y_mint = _b58(raw[120:152])
    oracle_address = _b58(raw[552:584])
    mints = session.call(
        "getMultipleAccounts", [[token_x_mint, token_y_mint], {"encoding": "base64"}]
    )
    manifest["mints"] = {
        token_x_mint: _mint_decimals(mints["value"][0]),
        token_y_mint: _mint_decimals(mints["value"][1]),
    }

    oracle_info = session.call("getAccountInfo", [oracle_address, {"encoding": "base64"}])
    manifest["oracle"] = {
        "address": oracle_address,
        "slot": oracle_info["context"]["slot"] if oracle_info else None,
    }

    positions = session.call(
        "getProgramAccounts",
        [
            METEORA_DLMM_PROGRAM_ID,
            {
                "encoding": "base64",
                "filters": [
                    {"memcmp": {"offset": 8, "bytes": pool}},
                    {"memcmp": {"offset": 40, "bytes": wallet}},
                ],
            },
        ],
    )
    position_addresses = [row["pubkey"] for row in positions or []]
    manifest["open_positions"] = position_addresses

    # Bin arrays covering the open positions plus the active bin's neighborhood.
    active_id = int.from_bytes(raw[76:80], "little", signed=True)
    manifest["active_id_at_fetch"] = active_id
    wanted_indexes: set[int] = set()
    for offset in (-1, 0, 1):
        wanted_indexes.add(active_id // 70 + offset)
    for row in positions or []:
        pdata = base64.b64decode(row["account"]["data"][0])
        lower = int.from_bytes(pdata[7912:7916], "little", signed=True)
        upper = int.from_bytes(pdata[7916:7920], "little", signed=True)
        wanted_indexes.update(range(lower // 70, upper // 70 + 1))
    bin_arrays: dict[str, int] = {}
    for index in sorted(wanted_indexes):
        found = session.call(
            "getProgramAccounts",
            [
                METEORA_DLMM_PROGRAM_ID,
                {
                    "encoding": "base64",
                    "filters": [
                        {"dataSize": 8 + 16 + 32 + 70 * 144},
                        {"memcmp": {"offset": 24, "bytes": pool}},
                        {
                            "memcmp": {
                                "offset": 8,
                                "bytes": _b58(index.to_bytes(8, "little", signed=True)),
                            }
                        },
                    ],
                },
            ],
        )
        for row in found or []:
            bin_arrays[row["pubkey"]] = index
    manifest["bin_arrays"] = bin_arrays

    # Signature histories: per open position (small), then the wallet.
    lp_signatures: dict[str, list] = {}
    for address in position_addresses:
        rows = session.call("getSignaturesForAddress", [address, {"limit": 1000}])
        lp_signatures[address] = [r["signature"] for r in rows or []]
    wallet_rows = session.call("getSignaturesForAddress", [wallet, {"limit": 1000}]) or []
    manifest["wallet_signatures"] = len(wallet_rows)
    if len(wallet_rows) == 1000:
        manifest["absences"].append(
            "wallet history capped at one signature page (1000); older activity unfetched"
        )

    # Bodies: open-position transactions first (they are exactly the LP transactions),
    # then recent wallet transactions not already covered, newest first, up to the cap.
    position_sigs = {sig for sigs in lp_signatures.values() for sig in sigs}
    wallet_sigs = [r["signature"] for r in wallet_rows if r.get("err") is None]
    body_order = sorted(position_sigs) + [s for s in wallet_sigs if s not in position_sigs]
    to_fetch = body_order[:wallet_body_cap]
    if len(body_order) > len(to_fetch):
        manifest["absences"].append(
            f"{len(body_order) - len(to_fetch)} wallet transaction bodies past the cap "
            "unfetched; the reconstruction window states its own start"
        )
    fetched = 0
    try:
        for start in range(0, len(to_fetch), 20):
            chunk = to_fetch[start : start + 20]
            session.batch("getTransaction", [[sig, _TX_OPTS] for sig in chunk])
            fetched += len(chunk)
    except BudgetExhausted:
        manifest["absences"].append(
            f"budget exhausted after {fetched} wallet/position bodies; remainder unfetched"
        )
    manifest["wallet_bodies_fetched"] = fetched

    # The pool tape: signature pages for intensity, bodies for the dense recent window.
    pool_pages = []
    before = None
    for _ in range(pool_signature_pages):
        params: list = [pool, {"limit": 1000}]
        if before is not None:
            params[1]["before"] = before
        rows = session.call("getSignaturesForAddress", params) or []
        pool_pages.extend(rows)
        if len(rows) < 1000:
            break
        before = rows[-1]["signature"]
    manifest["pool_signatures"] = len(pool_pages)
    dense = [r["signature"] for r in pool_pages if r.get("err") is None][:pool_tape_cap]
    fetched_tape = 0
    try:
        for start in range(0, len(dense), 20):
            chunk = dense[start : start + 20]
            session.batch("getTransaction", [[sig, _TX_OPTS] for sig in chunk])
            fetched_tape += len(chunk)
    except BudgetExhausted:
        manifest["absences"].append(
            f"budget exhausted after {fetched_tape} pool tape bodies; tape shorter than asked"
        )
    manifest["pool_tape_bodies_fetched"] = fetched_tape

    manifest["requests_spent"] = session.spent
    manifest["budget"] = session.budget
    manifest["finished_unix_ms"] = int(time.time() * 1000)
    (Path(session.retention_dir) / "manifest.json").write_text(
        json.dumps(manifest, indent=1)
    )
    return manifest


def _b58(raw: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    value = int.from_bytes(raw, "big")
    out = []
    while value:
        value, rem = divmod(value, 58)
        out.append(alphabet[rem])
    for byte in raw:
        if byte != 0:
            break
        out.append(alphabet[0])
    return "".join(reversed(out))
