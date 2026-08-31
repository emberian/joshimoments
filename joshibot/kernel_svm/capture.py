"""Replay a REAL mainnet swap against a snapshot of the state it actually executed on.

The soundness argument, which is the whole value of this file:

  A snapshot read at slot S reflects mainnet at the END of slot S. If T is the FIRST
  transaction after slot S that successfully touches the pool, then no committed state change
  separates the snapshot from T -- so the snapshot IS T's pre-state, exactly. Replaying T's
  instruction against it and comparing to what mainnet recorded is therefore a real
  end-to-end check, not a self-consistency check.

That "first successful transaction after S" condition is enforced, not assumed. If a second
successful transaction slipped in between, the run is rejected rather than reported.

This is the mechanism by which recorded swaps become parity fixtures: the pre-state and the
observed answer are both captured, so the Lean model can later be held to the same pair with
no network access at all.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import base58

import idl
import snapshot as snapshot_mod
from rpc import get_account, rpc
from svm import DlmmSvm, SwapFailed

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

# Exact-input swap variants. `swap_exact_out*` is a different question (solve for input) and
# is deliberately not replayed here rather than being replayed wrongly.
EXACT_IN_VARIANTS = ("swap", "swap2", "swap_with_price_impact", "swap_with_price_impact2")


class NoCleanReplay(RuntimeError):
    """No transaction satisfying the first-successful-after-S condition was found."""


def _discriminators() -> dict[bytes, str]:
    layout = idl.layout()
    return {bytes(layout.instruction(n)["discriminator"]): n for n in EXACT_IN_VARIANTS}


def _all_keys(tx: dict[str, Any]) -> list[str]:
    msg = tx["transaction"]["message"]
    loaded = tx["meta"].get("loadedAddresses") or {}
    return msg["accountKeys"] + loaded.get("writable", []) + loaded.get("readonly", [])


def pool_instructions(
    tx: dict[str, Any], pool: str, program_id: str = idl.DLMM_PROGRAM
) -> list[str]:
    """Names of the DLMM instructions in `tx` that were actually handed this pool.

    `getSignaturesForAddress` returns any transaction that MENTIONS the address, and
    aggregators routinely resolve large lookup tables listing pools they did not end up
    routing through. Such a transaction names the pool -- even as writable -- while never
    passing it to the DLMM program, and so cannot have modified it: only the owning program
    can write an account, and only one it was actually invoked with.

    Distinguishing those from real mutations is what lets a replay chain step over them
    instead of stopping, and stops a capture run from discarding a perfectly good snapshot.
    """
    layout = idl.layout()
    names = {bytes(ix["discriminator"]): ix["name"] for ix in layout.idl["instructions"]}
    keys = _all_keys(tx)

    candidates = list(tx["transaction"]["message"]["instructions"])
    for group in tx["meta"].get("innerInstructions") or []:
        candidates.extend(group["instructions"])

    found: list[str] = []
    for ix in candidates:
        if keys[ix["programIdIndex"]] != program_id:
            continue
        if pool not in [keys[i] for i in ix["accounts"]]:
            continue
        name = names.get(base58.b58decode(ix["data"])[:8])
        if name is not None:
            found.append(name)
    return found


def touches_pool(tx: dict[str, Any], pool: str, program_id: str = idl.DLMM_PROGRAM) -> bool:
    """Did this transaction actually invoke the DLMM program on this pool?"""
    return bool(pool_instructions(tx, pool, program_id))


def find_dlmm_swap(
    tx: dict[str, Any], pool: str, program_id: str = idl.DLMM_PROGRAM
) -> dict[str, Any] | None:
    """Find the exact-input DLMM swap against `pool`, top-level or CPI'd by an aggregator."""
    keys = _all_keys(tx)
    discs = _discriminators()

    candidates: list[dict[str, Any]] = list(tx["transaction"]["message"]["instructions"])
    for group in tx["meta"].get("innerInstructions") or []:
        candidates.extend(group["instructions"])

    for ix in candidates:
        if keys[ix["programIdIndex"]] != program_id:
            continue
        data = base58.b58decode(ix["data"])
        name = discs.get(data[:8])
        if name is None:
            continue
        accounts = [keys[i] for i in ix["accounts"]]
        if not accounts or accounts[0] != pool:
            continue
        return {
            "variant": name,
            "amount_in": int.from_bytes(data[8:16], "little"),
            "min_amount_out": int.from_bytes(data[16:24], "little"),
            "accounts": accounts,
            "data": data.hex(),
        }
    return None


def ensure_host_fee_account(snap: dict[str, Any], swap_ix: dict[str, Any]) -> str | None:
    """If the recorded swap named a referral account, load it into the snapshot.

    The host takes a cut of the protocol fee, so a replay that leaves this out matches
    `amount_out` and `fee` exactly and reports a `protocol_fee` too high by the host's share.
    Injecting the account here keeps fixtures self-contained -- a fixture must be replayable
    with no network, and the host account is part of the input.
    """
    host = swap_ix["accounts"][9]
    if host == snap["program_id"]:
        return None
    if host not in snap["accounts"]:
        acct = get_account(host)
        if acct is None:
            raise NoCleanReplay(f"host fee account {host} no longer exists and cannot be loaded")
        snap["accounts"][host] = {
            "lamports": acct["lamports"],
            "owner": acct["owner"],
            "executable": acct["executable"],
            "rent_epoch": min(int(acct.get("rentEpoch", 0)), 2**63 - 1),
            "data": acct["data"][0],
        }
    return host


def _mint_of(tx: dict[str, Any], account: str) -> str | None:
    """The mint of a token account, from the transaction's own balance records."""
    keys = _all_keys(tx)
    for field in ("preTokenBalances", "postTokenBalances"):
        for entry in tx["meta"].get(field) or []:
            if keys[entry["accountIndex"]] == account:
                return entry["mint"]
    return None


def _swap_for_y(tx: dict[str, Any], swap_ix: dict[str, Any], lb_pair: dict[str, Any]) -> bool:
    """Direction, decided from the transaction's own record of the swapped accounts' mints.

    Deliberately not read from the emitted Swap event. The event is part of what we are
    checking, and lifting a swap parameter out of it would let a harness bug cancel itself
    out -- the replay would be "predicting" a direction it had been handed.

    Aggregators routinely open an ephemeral input account and close it in the same
    transaction, so `user_token_in` may have no balance record and may no longer exist;
    `user_token_out` then settles it, since the two sides are complementary by construction.
    """
    in_mint = _mint_of(tx, swap_ix["accounts"][4])
    if in_mint is not None:
        return in_mint == lb_pair["token_x_mint"]
    out_mint = _mint_of(tx, swap_ix["accounts"][5])
    if out_mint is not None:
        return out_mint == lb_pair["token_y_mint"]
    raise NoCleanReplay(
        f"cannot determine direction: neither {swap_ix['accounts'][4]} nor "
        f"{swap_ix['accounts'][5]} has a token balance record in "
        f"{tx['transaction']['signatures'][0]}"
    )


def check_pre_state(snap: dict[str, Any], tx: dict[str, Any], observed: dict[str, Any]) -> list[str]:
    """Prove the snapshot really is this transaction's pre-state. Returns the failures.

    The RPC's `context.slot` turned out NOT to identify the state it returns -- a snapshot
    whose context slot preceded a transaction was measured holding that transaction's
    POST-state. Slot arithmetic is therefore not evidence and is not used as evidence. These
    three checks are, because all three read mainnet's own record of the pre-state:

      * the two reserve balances the transaction recorded before it ran, and
      * `start_bin_id`, which is the active bin the program observed on entry.

    Two independent 64-bit balances and the active bin agreeing exactly is a strong witness
    that no state change separates the snapshot from the transaction.
    """
    import base64

    failures: list[str] = []
    keys = _all_keys(tx)
    pre = {
        keys[e["accountIndex"]]: int(e["uiTokenAmount"]["amount"])
        for e in tx["meta"].get("preTokenBalances") or []
    }
    for side in ("reserve_x", "reserve_y"):
        account = snap["lb_pair"][side]
        snap_amount = int.from_bytes(base64.b64decode(snap["accounts"][account]["data"])[64:72], "little")
        tx_amount = pre.get(account)
        if tx_amount is None:
            failures.append(f"{side}: transaction has no pre-balance record for {account}")
        elif tx_amount != snap_amount:
            failures.append(f"{side}: snapshot {snap_amount} != transaction pre-balance {tx_amount}")

    if observed["start_bin_id"] != snap["lb_pair"]["active_id"]:
        failures.append(
            f"active_id: snapshot {snap['lb_pair']['active_id']} != "
            f"observed start_bin_id {observed['start_bin_id']}"
        )
    return failures


def onchain_swap_event(
    tx: dict[str, Any], pool: str, program_id: str = idl.DLMM_PROGRAM
) -> dict[str, Any] | None:
    """The `Swap` event mainnet recorded, decoded from the emit_cpi inner instruction."""
    from svm import _ANCHOR_CPI_EVENT, SWAP_EVENT_DISCRIMINATOR

    layout = idl.layout()
    keys = _all_keys(tx)
    for group in tx["meta"].get("innerInstructions") or []:
        for ix in group["instructions"]:
            if keys[ix["programIdIndex"]] != program_id:
                continue
            blob = base58.b58decode(ix["data"])
            body = blob[8:] if blob[:8] == _ANCHOR_CPI_EVENT else blob
            if body[:8] != SWAP_EVENT_DISCRIMINATOR:
                continue
            value, _ = layout._read({"defined": {"name": "Swap"}}, body, 8)
            if value["lb_pair"] == pool:
                return value
    return None


def successful_after(pool: str, slot: int, *, limit: int = 100) -> list[dict[str, Any]]:
    """Successful signatures touching `pool` with slot > `slot`, oldest first."""
    sigs = rpc("getSignaturesForAddress", [pool, {"limit": limit}])
    fresh = [s for s in sigs if s["slot"] > slot and s.get("err") is None]
    return list(reversed(fresh))


def known_signatures(pool: str, limit: int = 100) -> set[str]:
    return {s["signature"] for s in rpc("getSignaturesForAddress", [pool, {"limit": limit}])}


def await_clean_replay(
    pool: str, *, bin_window: int = 4, timeout: float = 900.0, poll: float = 4.0, attempts: int = 4
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Snapshot, wait for the next successful pool transaction, replay it if the gate passes.

    A snapshot is the post-state of whatever last touched the pool, so it is the pre-state of
    whatever touches it next. When the gate says otherwise -- because a transaction landed
    between the snapshot read and the signature read -- the snapshot is stale and the only
    honest move is to take a fresh one, not to relax the gate.
    """
    deadline = time.time() + timeout
    last_failures: list[str] = []

    for attempt in range(attempts):
        seen = known_signatures(pool)
        snap = snapshot_mod.fetch_snapshot(pool, bin_window=bin_window)
        print(
            f"[attempt {attempt + 1}] snapshot active_id {snap['lb_pair']['active_id']} "
            f"(rpc context slot {snap['slot']}, not trusted); waiting for the next swap"
        )

        while time.time() < deadline:
            fresh = [
                s
                for s in reversed(rpc("getSignaturesForAddress", [pool, {"limit": 100}]))
                if s["signature"] not in seen and s.get("err") is None
            ]
            # Transactions that merely name the pool cannot have moved it, so they neither
            # invalidate the snapshot nor deserve to be replayed. Step over them.
            candidate = None
            for entry in fresh:
                seen.add(entry["signature"])
                tx = rpc(
                    "getTransaction",
                    [entry["signature"], {"encoding": "json", "maxSupportedTransactionVersion": 0}],
                )
                if tx is not None and touches_pool(tx, pool):
                    candidate = entry
                    break
            if candidate is None:
                time.sleep(poll)
                continue
            report = replay(snap, candidate["signature"], competing=0)
            if report.get("gate_failures"):
                last_failures = report["gate_failures"]
                print(f"  gate rejected {candidate['signature'][:16]}: {last_failures}; re-snapshotting")
                break
            return snap, report
        else:
            raise NoCleanReplay(f"no successful transaction touched {pool} within the {timeout:.0f}s budget")

    raise NoCleanReplay(
        f"could not obtain a gate-clean pre-state in {attempts} attempts; last: {last_failures}"
    )


def replay(snap: dict[str, Any], signature: str, *, competing: int = 0) -> dict[str, Any]:
    """Replay one recorded transaction against a snapshot and compare to what mainnet recorded."""
    pool = snap["pool"]
    tx = rpc("getTransaction", [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}])
    if tx is None:
        raise NoCleanReplay(f"transaction {signature} not found")

    swap_ix = find_dlmm_swap(tx, pool)
    if swap_ix is None:
        raise NoCleanReplay(
                f"transaction {signature} touches {pool} but contains no exact-input "
            "against it (it may be an exact-out swap, or a liquidity operation)"
        )

    swap_for_y = _swap_for_y(tx, swap_ix, snap["lb_pair"])
    observed = onchain_swap_event(tx, pool)
    if observed is None:
        raise NoCleanReplay(f"transaction {signature} emitted no decodable Swap event for {pool}")

    gate_failures = check_pre_state(snap, tx, observed)
    if gate_failures:
        return {
            "ok": False,
            "reason": "snapshot is not this transaction's pre-state",
            "gate_failures": gate_failures,
            "signature": signature,
            "snapshot_slot": snap["slot"],
            "tx_slot": tx["slot"],
        }

    host_fee_in = ensure_host_fee_account(snap, swap_ix)
    machine = DlmmSvm(snap)
    started = time.perf_counter()
    try:
        # The transaction's own block time and slot: the dynamic fee decays against the
        # clock, so replaying under the snapshot's clock would change the answer.
        result = machine.swap(
            swap_ix["amount_in"],
            swap_for_y=swap_for_y,
            unix_timestamp=tx["blockTime"],
            slot=tx["slot"],
            host_fee_in=host_fee_in,
        )
    except SwapFailed as exc:
        return {
            "ok": False,
            "reason": "replay reverted while mainnet succeeded",
            "error": str(exc),
            "logs": exc.logs[-15:],
            "signature": signature,
            "snapshot_slot": snap["slot"],
            "tx_slot": tx["slot"],
        }
    elapsed = time.perf_counter() - started

    fields = [
        "amount_in", "amount_out", "start_bin_id", "end_bin_id", "fee", "protocol_fee", "host_fee",
    ]
    comparison = {
        f: {"onchain": observed[f], "replay": result.event[f] if result.event else None} for f in fields
    }
    agree = result.event is not None and all(
        comparison[f]["onchain"] == comparison[f]["replay"] for f in fields
    )
    # The event is the program's claim; the token account delta is what actually moved.
    agree = agree and result.amount_out == observed["amount_out"]

    return {
        "ok": bool(agree),
        "signature": signature,
        "variant": swap_ix["variant"],
        "gate_failures": [],
        "snapshot_slot": snap["slot"],
        "tx_slot": tx["slot"],
        "competing_txs_between": competing,
        "swap_for_y": swap_for_y,
        "unix_timestamp": tx["blockTime"],
        "host_fee_in": host_fee_in,
        "bins_crossed": abs(observed["end_bin_id"] - observed["start_bin_id"]) + 1,
        "amount_in": swap_ix["amount_in"],
        "onchain_amount_out": observed["amount_out"],
        "replay_amount_out": result.amount_out,
        "comparison": comparison,
        "active_id": {"before": result.before.active_id, "after": result.after.active_id},
        "bin_diff": {str(k): v for k, v in result.bin_diff.items()},
        "compute_units": result.compute_units,
        "replay_seconds": elapsed,
    }


def save_fixture(snap: dict[str, Any], report: dict[str, Any]) -> Path:
    """Persist a gate-clean replay as an offline parity fixture.

    A fixture pins the pre-state, the swap input INCLUDING the timestamp, and what mainnet
    actually returned. Anything holding itself to one of these -- the Lean model included --
    is being held to mainnet, with no RPC in the loop.
    """
    fixture = {
        "version": 1,
        "signature": report["signature"],
        "pool": snap["pool"],
        "bin_step": snap["lb_pair"]["bin_step"],
        "tx_slot": report["tx_slot"],
        "input": {
            "amount_in": report["amount_in"],
            "swap_for_y": report["swap_for_y"],
            "unix_timestamp": report["unix_timestamp"],
            "slot": report["tx_slot"],
            "host_fee_in": report["host_fee_in"],
        },
        "observed": {k: v["onchain"] for k, v in report["comparison"].items()},
        "bins_crossed": report["bins_crossed"],
        "snapshot": snap,
    }
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{snap['pool'][:8]}-{report['signature'][:16]}.json"
    path.write_text(json.dumps(fixture))
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="replay a real mainnet DLMM swap against its true pre-state")
    ap.add_argument("pool")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--bin-window", type=int, default=4)
    ap.add_argument("--repeat", type=int, default=1, help="capture this many gate-clean replays")
    ap.add_argument("--save", action="store_true", help="write each clean replay as a parity fixture")
    args = ap.parse_args()

    failures = 0
    for i in range(args.repeat):
        try:
            snap, report = await_clean_replay(
                args.pool, bin_window=args.bin_window, timeout=args.timeout
            )
        except NoCleanReplay as exc:
            print(f"[{i + 1}/{args.repeat}] no clean replay: {exc}")
            failures += 1
            continue
        status = "EXACT" if report["ok"] else "MISMATCH"
        print(
            f"[{i + 1}/{args.repeat}] {status} {report['signature'][:16]} "
            f"amount_in={report['amount_in']} onchain_out={report['onchain_amount_out']} "
            f"replay_out={report['replay_amount_out']} bins_crossed={report['bins_crossed']} "
            f"({report['replay_seconds'] * 1e3:.1f} ms)"
        )
        if not report["ok"]:
            print(json.dumps(report["comparison"], indent=2))
            failures += 1
        elif args.save:
            print(f"    fixture -> {save_fixture(snap, report)}")

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
