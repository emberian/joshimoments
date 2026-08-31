"""Replay a whole run of recorded swaps forward from ONE snapshot.

Capturing a fresh snapshot per swap does not scale: it costs an RPC round trip and ~5 MB per
swap, and mainnet only produces swaps as fast as it produces them. But a snapshot does not
have to be spent on a single swap. If the harness reproduces a swap exactly, then the state
it holds afterwards IS mainnet's state afterwards -- so it is the pre-state of the next
recorded swap, and the next, for as long as agreement holds.

That turns one snapshot into an arbitrarily long validation run, and it is self-checking: the
chain is only allowed to continue while each step still matches the event mainnet recorded.
The moment a step disagrees the run STOPS, because every later step would be running on state
that has already diverged and their agreement or disagreement would mean nothing.

What breaks a chain legitimately, and is reported rather than skipped:

  * a transaction that mutates the pool by some means other than an exact-input swap
    (add/remove liquidity, fee claims, exact-OUT swaps). The harness does not replay those,
    so the chain must resynchronise from a fresh snapshot.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import capture
import snapshot as snapshot_mod
from oracle import DlmmOracle, OracleOutOfRange, OracleRejected, SwapRequest
from rpc import rpc

_FIXTURE_FIELDS = (
    "amount_in", "amount_out", "start_bin_id", "end_bin_id", "fee", "protocol_fee", "host_fee",
)


def pool_transactions(pool: str, *, limit: int = 100) -> list[dict[str, Any]]:
    """Successful transactions touching `pool`, oldest first."""
    sigs = rpc("getSignaturesForAddress", [pool, {"limit": limit}])
    return [s for s in reversed(sigs) if s.get("err") is None]


def replay_stream(
    snap: dict[str, Any],
    signatures: list[str],
    *,
    stop_on_mismatch: bool = True,
    save_fixtures: bool = False,
    seek_start: bool = True,
) -> dict[str, Any]:
    """Chain recorded swaps through one machine, checking each against mainnet.

    `seek_start` skips leading transactions the snapshot has already absorbed. A snapshot
    takes seconds to fetch, so on a busy pool a swap can commit while it is in flight: that
    swap looks "new" to a signature list captured beforehand, while its effects are already
    in the state we hold. Scanning forward to the first transaction whose recorded pre-state
    matches the snapshot finds the true start instead of guessing at it.

    The seek applies ONLY before the first replayed step. Once the chain is running, a
    pre-state mismatch means real divergence and stops it.
    """
    oracle = DlmmOracle(snap)
    steps: list[dict[str, Any]] = []
    matched = 0
    skipped = 0
    sought = 0
    written: list[str] = []
    started_all = time.perf_counter()

    for signature in signatures:
        tx = rpc("getTransaction", [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}])
        if tx is None:
            steps.append({"signature": signature, "status": "not_found"})
            break

        invoked = capture.pool_instructions(tx, snap["pool"])
        if not invoked:
            # Names the pool (usually via a lookup table) but never hands it to the program,
            # so it cannot have moved it. Step over it; the chain is intact.
            skipped += 1
            continue

        swap_ix = capture.find_dlmm_swap(tx, snap["pool"])
        observed = capture.onchain_swap_event(tx, snap["pool"])
        if swap_ix is None or observed is None:
            # Something that is not an exact-input swap moved the pool -- liquidity, fees, an
            # exact-out swap. The chain's pre-state assumption is dead from here on.
            steps.append(
                {
                    "signature": signature[:16],
                    "slot": tx["slot"],
                    "status": "chain_broken_non_swap_mutation",
                    "instructions": invoked,
                }
            )
            break

        # Load any referral account FIRST, so the pre-state we mint a fixture from carries it.
        # Without this the fixture replays standalone with no host account and reports a
        # protocol fee too high by the host's cut -- which the chain would not notice, because
        # in-chain the account is present.
        host_fee_in = capture.ensure_host_fee_account(snap, swap_ix)

        # The machine's state as it stands, which is what this recorded swap is about to see.
        pre_state = oracle._svm.to_snapshot()

        # Gate EVERY step, not just the first. Agreement on `amount_out` alone would let the
        # chain drift in state the swaps happen not to read yet, and a fixture minted mid-chain
        # would then pin an assumed pre-state rather than a measured one. Re-checking the
        # reserves and active bin against mainnet's own record of THIS transaction's pre-state
        # keeps every link independently anchored.
        gate = capture.check_pre_state(pre_state, tx, observed)
        if gate:
            if seek_start and matched == 0:
                # Already absorbed by the snapshot; keep looking for the real start.
                sought += 1
                continue
            steps.append({"signature": signature[:16], "status": "chain_drifted", "detail": gate})
            break

        request = SwapRequest(
            amount_in=swap_ix["amount_in"],
            swap_for_y=capture._swap_for_y(tx, swap_ix, snap["lb_pair"]),
            unix_timestamp=tx["blockTime"],
            slot=tx["slot"],
            host_fee_in=host_fee_in,
            persist=True,  # the whole point: continue from the state the last swap left
        )
        started = time.perf_counter()
        try:
            answer = oracle.answer(request)
        except (OracleRejected, OracleOutOfRange) as exc:
            steps.append(
                {
                    "signature": signature,
                    "slot": tx["slot"],
                    "status": "unanswerable",
                    "detail": str(exc)[:160],
                }
            )
            break
        elapsed = time.perf_counter() - started

        agree = (
            answer.amount_out == observed["amount_out"]
            and answer.fee == observed["fee"]
            and answer.protocol_fee == observed["protocol_fee"]
            and answer.host_fee == observed["host_fee"]
            and answer.start_bin_id == observed["start_bin_id"]
            and answer.end_bin_id == observed["end_bin_id"]
        )
        steps.append(
            {
                "signature": signature[:16],
                "slot": tx["slot"],
                "status": "exact" if agree else "MISMATCH",
                "amount_in": request.amount_in,
                "swap_for_y": request.swap_for_y,
                "onchain_amount_out": observed["amount_out"],
                "replay_amount_out": answer.amount_out,
                "bins": [observed["start_bin_id"], observed["end_bin_id"]],
                "ms": round(elapsed * 1e3, 2),
            }
        )
        if not agree:
            if stop_on_mismatch:
                break
        else:
            matched += 1
            if save_fixtures:
                written.append(
                    str(
                        capture.save_fixture(
                            pre_state,
                            {
                                "signature": signature,
                                "tx_slot": tx["slot"],
                                "amount_in": request.amount_in,
                                "swap_for_y": request.swap_for_y,
                                "unix_timestamp": tx["blockTime"],
                                "host_fee_in": request.host_fee_in,
                                "bins_crossed": abs(observed["end_bin_id"] - observed["start_bin_id"]) + 1,
                                "comparison": {
                                    k: {"onchain": observed[k]}
                                    for k in _FIXTURE_FIELDS
                                },
                            },
                        )
                    )
                )

    return {
        "pool": snap["pool"],
        "chained_exact": matched,
        "skipped_non_mutating": skipped,
        "skipped_already_absorbed": sought,
        "fixtures_written": written,
        "steps": steps,
        "wall_seconds": round(time.perf_counter() - started_all, 2),
    }


def follow(
    pool: str,
    *,
    bin_window: int = 4,
    timeout: float = 1800.0,
    poll: float = 4.0,
    save: bool = False,
    attempts: int = 8,
) -> dict[str, Any]:
    """Snapshot, then chain every swap that lands AFTER it.

    The direction matters and is easy to get backwards. A snapshot is the post-state of the
    pool's history, so it can only be the pre-state of transactions still to come -- chaining
    the last 100 recorded signatures against a fresh snapshot replays the past against the
    present, and the gate rejects it immediately. Signatures already present before the
    snapshot are recorded here precisely so they can be excluded.

    Even so, a snapshot takes a few seconds to fetch, and on a busy pool a swap can land
    inside that window -- making the "next" transaction one the snapshot already contains.
    That is a race, not a defect, and the answer is to take a fresh snapshot and try again
    rather than to loosen the gate that noticed.
    """
    deadline = time.time() + timeout
    last: dict[str, Any] = {"pool": pool, "chained_exact": 0, "steps": [], "skipped_non_mutating": 0}

    for attempt in range(attempts):
        if time.time() >= deadline:
            break
        seen = {s["signature"] for s in rpc("getSignaturesForAddress", [pool, {"limit": 200}])}
        snap = snapshot_mod.fetch_snapshot(pool, bin_window=bin_window)
        print(f"[attempt {attempt + 1}] snapshot active_id {snap['lb_pair']['active_id']}; following {pool}")

        collected: list[str] = []
        while time.time() < deadline:
            fresh = [
                s["signature"]
                for s in reversed(rpc("getSignaturesForAddress", [pool, {"limit": 200}]))
                if s["signature"] not in seen and s.get("err") is None
            ]
            if not fresh:
                time.sleep(poll)
                continue
            seen.update(fresh)
            collected.extend(fresh)
            report = replay_stream(snap, collected, save_fixtures=save)
            last = report
            if report["chained_exact"]:
                print(
                    f"  {report['chained_exact']} exact "
                    f"({report['skipped_non_mutating']} non-mutating skipped)"
                )
                return report
            broken = [s for s in report["steps"] if s["status"] != "exact"]
            if broken:
                if broken[0]["status"] == "chain_drifted":
                    print(f"  drifted ({broken[0]['detail'][0][:70]}...); re-snapshotting")
                    break  # fresh snapshot
                return report
            time.sleep(poll)

    last["timed_out"] = True
    return last


def main() -> None:
    ap = argparse.ArgumentParser(description="chain recorded swaps forward from one snapshot")
    ap.add_argument("pool")
    ap.add_argument("--snapshot", type=Path, default=None, help="reuse an existing snapshot file")
    ap.add_argument("--max-steps", type=int, default=20)
    ap.add_argument("--save", action="store_true", help="write each verified step as a fixture")
    ap.add_argument(
        "--replay-known",
        action="store_true",
        help="chain already-recorded signatures against --snapshot (needs a snapshot that predates them)",
    )
    ap.add_argument("--timeout", type=float, default=1800.0)
    args = ap.parse_args()

    if args.replay_known:
        if args.snapshot is None:
            raise SystemExit("--replay-known needs --snapshot taken before those transactions")
        snap = snapshot_mod.load(args.snapshot)
        known = [s["signature"] for s in pool_transactions(args.pool)]
        report = replay_stream(snap, known[: args.max_steps], save_fixtures=args.save)
    else:
        report = follow(args.pool, timeout=args.timeout, save=args.save)

    print(json.dumps(report, indent=2))
    print(f"\n{report['chained_exact']} consecutive recorded swaps replayed exactly from one snapshot")


if __name__ == "__main__":
    main()
