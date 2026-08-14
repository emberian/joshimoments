"""Pull the exact set of mainnet accounts a DLMM swap touches, into a JSON snapshot.

A snapshot is self-contained: given one, `svm.py` can stand up a machine that executes the
real deployed program with no network access at all. That matters for the oracle contract --
a parity run over a large corpus must not be at the mercy of an RPC, and a snapshot that
silently fell back to a partial account set would produce a swap that "worked" against the
wrong liquidity.

Read-only. Nothing here signs or sends.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from solders.pubkey import Pubkey

import idl
from rpc import get_account, get_multiple_accounts_at_slot, rpc

BPF_UPGRADEABLE = "BPFLoaderUpgradeab1e11111111111111111111111"
BPF_LOADER_2 = "BPFLoader2111111111111111111111111111111111"
MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


class SnapshotIncomplete(RuntimeError):
    """A required account was missing. Never degrade to a partial account set."""


def _enc(acct: dict[str, Any]) -> dict[str, Any]:
    return {
        "lamports": acct["lamports"],
        "owner": acct["owner"],
        "executable": acct["executable"],
        "rent_epoch": min(int(acct.get("rentEpoch", 0)), 2**63 - 1),
        "data": acct["data"][0],
    }


PROGRAM_CACHE = Path(__file__).resolve().parent / "cache" / "programs"


def store_program(elf: bytes) -> str:
    """Put an ELF in the shared content-addressed cache and return its digest.

    Program binaries are immutable for a deployment and identical across every snapshot of
    every pool, but they are ~4.7 MB. Inlining them made each fixture 4.7 MB of program and
    ~30 KB of the pool state that actually varies, which puts a corpus of a few thousand
    swaps into the tens of gigabytes for no information. Storing them once by digest keeps
    fixtures small enough to hold a large corpus, and keeps them exact: a digest mismatch is
    a different binary, which is precisely when a recorded result stops being reproducible.
    """
    digest = hashlib.sha256(elf).hexdigest()
    PROGRAM_CACHE.mkdir(parents=True, exist_ok=True)
    path = PROGRAM_CACHE / f"{digest}.so"
    if not path.exists():
        path.write_bytes(elf)
    return digest


def load_program(entry: str) -> bytes:
    """Resolve a snapshot's program entry: either a cache digest or an inline base64 ELF."""
    if len(entry) == 64 and all(c in "0123456789abcdef" for c in entry):
        path = PROGRAM_CACHE / f"{entry}.so"
        if not path.exists():
            raise SnapshotIncomplete(
                f"program {entry[:12]}... is not in {PROGRAM_CACHE}; re-run snapshot.py for "
                "this pool to repopulate the program cache"
            )
        return path.read_bytes()
    return base64.b64decode(entry)


def _fetch_elf(program_id: str) -> str:
    """Return the base64 SBF ELF for a deployed program, following the upgradeable loader."""
    acct = get_account(program_id)
    if acct is None:
        raise SnapshotIncomplete(f"program {program_id} does not exist on mainnet")
    if not acct["executable"]:
        raise SnapshotIncomplete(f"{program_id} is not executable")
    data = base64.b64decode(acct["data"][0])
    if acct["owner"] == BPF_UPGRADEABLE:
        # UpgradeableLoaderState::Program { programdata_address } = 4-byte enum tag + pubkey
        programdata = str(Pubkey(data[4:36]))
        pd = get_account(programdata)
        if pd is None:
            raise SnapshotIncomplete(f"programdata {programdata} for {program_id} is missing")
        raw = base64.b64decode(pd["data"][0])
        # ProgramData { slot: u64, upgrade_authority: Option<Pubkey> } = 4 + 8 + 33 = 45
        return store_program(raw[45:])
    return store_program(data)


def fetch_snapshot(pool: str, *, bin_window: int = 4, program_id: str = idl.DLMM_PROGRAM) -> dict[str, Any]:
    """Snapshot every account a swap against `pool` can touch, at ONE confirmed slot.

    Two phases. The first reads the LbPair only, to learn which reserves, mints, oracle and
    bin arrays exist. The second re-reads *everything including the LbPair* in a single
    getMultipleAccounts, and that call's context slot is the snapshot's slot. Only the second
    read is kept: it is the one that is internally consistent.
    """
    layout = idl.layout()

    probe = get_account(pool)
    if probe is None:
        raise SnapshotIncomplete(f"pool {pool} does not exist")
    if probe["owner"] != program_id:
        raise SnapshotIncomplete(f"pool {pool} is owned by {probe['owner']}, not {program_id}")
    probe_pair = layout.decode_account("LbPair", base64.b64decode(probe["data"][0]))

    required = [
        pool,
        probe_pair["reserve_x"],
        probe_pair["reserve_y"],
        probe_pair["token_x_mint"],
        probe_pair["token_y_mint"],
        probe_pair["oracle"],
    ]
    bitmap_ext = str(idl.bitmap_extension_pda(pool, program_id))

    # Bin arrays: a window either side of the active bin. A swap walks outward from the
    # active id, so the window bounds how large a swap the snapshot can answer for; a swap
    # that runs off the end fails loudly inside the program rather than silently truncating.
    active_index = idl.bin_array_index(probe_pair["active_id"])
    wanted = list(range(active_index - bin_window, active_index + bin_window + 1))
    bin_pdas = [str(idl.bin_array_pda(pool, i, program_id)) for i in wanted]

    keys = [*required, bitmap_ext, *bin_pdas]
    slot, values = get_multiple_accounts_at_slot(keys)
    by_key = dict(zip(keys, values, strict=True))

    accounts: dict[str, dict[str, Any]] = {}
    for key in required:
        acct = by_key[key]
        if acct is None:
            raise SnapshotIncomplete(f"account {key} referenced by {pool} does not exist")
        accounts[key] = _enc(acct)

    if by_key[bitmap_ext] is not None:
        accounts[bitmap_ext] = _enc(by_key[bitmap_ext])

    bin_arrays: dict[str, int] = {}
    for index, key in zip(wanted, bin_pdas, strict=True):
        acct = by_key[key]
        if acct is None:
            continue
        accounts[key] = _enc(acct)
        bin_arrays[key] = index
    if not bin_arrays:
        raise SnapshotIncomplete(f"pool {pool} has no initialised bin arrays near active bin")

    # Is the window bounded by genuinely uninitialised bin arrays on both sides?
    #
    # This decides whether a revert can be believed. If the outermost arrays we asked for do
    # not exist on-chain, then the region we hold is walled in by real emptiness and a swap
    # that reverts at the wall would have reverted on mainnet too -- the revert is a semantic
    # answer. If they DO exist, there may be more liquidity beyond what we fetched, and a
    # revert cannot be distinguished from "the snapshot was too small". The oracle refuses to
    # call that a refusal.
    window_complete = by_key[bin_pdas[0]] is None and by_key[bin_pdas[-1]] is None

    lb_pair = layout.decode_account("LbPair", base64.b64decode(accounts[pool]["data"]))

    # Token programs are read off the reserve accounts' owners, not assumed.
    token_x_program = accounts[lb_pair["reserve_x"]]["owner"]
    token_y_program = accounts[lb_pair["reserve_y"]]["owner"]

    # ELFs are immutable for a given deployment, so fetching them outside the atomic read is
    # safe in a way that fetching mutable pool state outside it would not be.
    programs: dict[str, str] = {}
    for pid in dict.fromkeys([program_id, token_x_program, token_y_program, MEMO_PROGRAM]):
        programs[pid] = _fetch_elf(pid)

    block_time = rpc("getBlockTime", [slot])

    return {
        "version": 1,
        "captured_at": int(time.time()),
        "slot": slot,
        "block_time": block_time,
        "program_id": program_id,
        "pool": pool,
        "lb_pair": lb_pair,
        "token_x_program": token_x_program,
        "token_y_program": token_y_program,
        "memo_program": MEMO_PROGRAM,
        "event_authority": str(idl.event_authority_pda(program_id)),
        "bitmap_extension": bitmap_ext if bitmap_ext in accounts else None,
        "bin_arrays": bin_arrays,
        "bin_window_requested": [wanted[0], wanted[-1]],
        "window_complete": window_complete,
        "accounts": accounts,
        "programs": programs,
    }


def save(snap: dict[str, Any], path: Path | None = None) -> Path:
    path = path or SNAPSHOT_DIR / f"{snap['pool']}-{snap['slot']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap))
    return path


def load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def main() -> None:
    ap = argparse.ArgumentParser(description="snapshot a Meteora DLMM pool from mainnet")
    ap.add_argument("pool")
    ap.add_argument("--bin-window", type=int, default=4)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    snap = fetch_snapshot(args.pool, bin_window=args.bin_window)
    path = save(snap, args.out)
    size = path.stat().st_size
    pair = snap["lb_pair"]
    print(f"slot {snap['slot']}  active_id {pair['active_id']}  bin_step {pair['bin_step']}")
    print(
        f"accounts {len(snap['accounts'])}  bin_arrays {len(snap['bin_arrays'])}  "
        f"programs {len(snap['programs'])}"
    )
    print(f"wrote {path} ({size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
