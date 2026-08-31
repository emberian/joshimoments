"""Stand up a LiteSVM machine from a snapshot and execute a real DLMM swap in it.

The program executing here is the *deployed mainnet SBF binary*, byte for byte, running on
the real Agave SVM against real mainnet account state. Nothing about the swap math is
reimplemented in this file -- this module only sets the table and reads the plates. That is
the entire point: a reimplementation could not be an oracle for the Lean model, because then
two guesses would be agreeing with each other.

What IS synthetic: the user and the user's two token accounts, cloned from the pool's own
reserve accounts so their mint, extension shape and program owner are correct by
construction. Everything else -- pool, bin arrays, reserves, oracle, mints, and the program
itself -- is mainnet's own bytes.

The clock is set explicitly rather than left to default, because it is a real input: the
program decays `volatility_reference` by the time since the pool's last update, and the
dynamic fee rides on that. It defaults to the snapshot's block time and should be set to the
timestamp of the swap being modelled. Getting this wrong does not fail loudly -- the bin
arithmetic stays exact to the lamport while `amount_out` quietly moves.
"""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from solders.account import Account
from solders.clock import Clock
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.litesvm import LiteSVM
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

import idl

# SPL Token account base layout, shared by Token and Token-2022.
_TA_OWNER = slice(32, 64)
_TA_AMOUNT = slice(64, 72)
_TA_STATE = 108
_TA_IS_NATIVE_TAG = slice(109, 113)

SWAP_EVENT_DISCRIMINATOR = bytes.fromhex("516ce3becdd00ac4")
_ANCHOR_CPI_EVENT = bytes.fromhex("e445a52e51cb9a1d")


class SwapFailed(RuntimeError):
    """The deployed program rejected the swap. Carries the program logs.

    This is a real answer from the oracle -- "this swap does not execute" -- and callers must
    treat it as such rather than substituting a computed default.
    """

    def __init__(self, message: str, logs: list[str] | None = None) -> None:
        super().__init__(message)
        self.logs = logs or []


class HarnessUnsupported(RuntimeError):
    """The snapshot describes a pool this harness cannot faithfully drive (e.g. transfer hooks)."""


@dataclass(frozen=True, slots=True)
class BinState:
    """One bin's observable state."""

    bin_id: int
    amount_x: int
    amount_y: int
    price: int
    liquidity_supply: int
    fee_amount_x_per_token_stored: int
    fee_amount_y_per_token_stored: int


@dataclass(frozen=True, slots=True)
class PoolState:
    """The part of a DLMM pool a swap can move."""

    active_id: int
    reserve_x: int
    reserve_y: int
    protocol_fee_x: int
    protocol_fee_y: int
    volatility_accumulator: int
    volatility_reference: int
    index_reference: int
    last_update_timestamp: int
    raw_bin_arrays: dict[str, tuple[int, bytes]]
    """Bin arrays as raw account bytes, keyed by address, valued (array index, bytes).

    Held undecoded on purpose. A pool commonly carries several bin arrays of which a swap
    touches one or two, and eagerly decoding all 70 bins of each through the IDL reader cost
    more than executing the swap did -- 7.4 ms of decode against 8.2 ms of execution on a
    nine-array pool, paid twice per swap for the before and after states. Comparing bytes
    first means only the arrays that actually moved are ever decoded.
    """

    _layout: Any = None

    def bins(self) -> dict[int, BinState]:
        """Decode every bin. Costs real time; `bin_diff` avoids it where it can."""
        out: dict[int, BinState] = {}
        for index, raw in self.raw_bin_arrays.values():
            out.update(_decode_bins(self._layout, index, raw))
        return out

    def bin_diff(self, other: PoolState) -> dict[int, dict[str, int]]:
        """Which bins changed between two states, and by how much."""
        out: dict[int, dict[str, int]] = {}
        for key, (index, raw) in self.raw_bin_arrays.items():
            other_entry = other.raw_bin_arrays.get(key)
            if other_entry is None or other_entry[1] == raw:
                continue
            mine = _decode_bins(self._layout, index, raw)
            theirs = _decode_bins(self._layout, other_entry[0], other_entry[1])
            for bin_id in sorted(set(mine) | set(theirs)):
                a, b = mine.get(bin_id), theirs.get(bin_id)
                if a is None or b is None:
                    out[bin_id] = {"appeared_or_vanished": 1}
                    continue
                if a == b:
                    continue
                delta = {
                    "amount_x": b.amount_x - a.amount_x,
                    "amount_y": b.amount_y - a.amount_y,
                    "fee_x_per_token": b.fee_amount_x_per_token_stored - a.fee_amount_x_per_token_stored,
                    "fee_y_per_token": b.fee_amount_y_per_token_stored - a.fee_amount_y_per_token_stored,
                }
                if any(delta.values()):
                    out[bin_id] = delta
        return out


def _decode_bins(layout: idl.Layout, index: int, raw: bytes) -> dict[int, BinState]:
    arr = layout.decode_account("BinArray", raw)
    base = index * idl.BINS_PER_ARRAY
    return {
        base + offset: BinState(
            bin_id=base + offset,
            amount_x=b["amount_x"],
            amount_y=b["amount_y"],
            price=b["price"],
            liquidity_supply=b["liquidity_supply"],
            fee_amount_x_per_token_stored=b["fee_amount_x_per_token_stored"],
            fee_amount_y_per_token_stored=b["fee_amount_y_per_token_stored"],
        )
        for offset, b in enumerate(arr["bins"])
    }


@dataclass(frozen=True, slots=True)
class SwapResult:
    """Everything one execution of the real program tells us."""

    amount_in: int
    amount_out: int
    swap_for_y: bool
    before: PoolState
    after: PoolState
    event: dict[str, Any] | None
    compute_units: int
    logs: list[str]

    @property
    def bin_diff(self) -> dict[int, dict[str, int]]:
        return self.before.bin_diff(self.after)


def _token_amount(data: bytes) -> int:
    return int.from_bytes(data[_TA_AMOUNT], "little")


def _decode_swap_event(meta: Any, layout: idl.Layout) -> dict[str, Any] | None:
    """Pull the program's own `Swap` event out of the transaction.

    Anchor's `emit_cpi!` does not write a `Program data:` log line -- it self-invokes the
    program with the event as *instruction data*, so the event lives in the inner
    instructions, not the logs. Reading it gives the program stating its own answer
    (amount_in/out, fee, protocol_fee, bin range) independently of the account deltas we
    read back, and the two disagreeing would mean the harness is misreading state.
    """
    for inner in meta.inner_instructions():
        for entry in inner:
            blob = bytes(entry.instruction().data)
            body = blob[8:] if blob[:8] == _ANCHOR_CPI_EVENT else blob
            if body[:8] != SWAP_EVENT_DISCRIMINATOR:
                continue
            try:
                value, _ = layout._read({"defined": {"name": "Swap"}}, body, 8)
            except Exception:
                return None
            return value
    return None


class DlmmSvm:
    """A loaded machine. Reusable: `swap()` may be called repeatedly, each from the snapshot state."""

    def __init__(self, snap: dict[str, Any]) -> None:
        self.snap = snap
        self.layout = idl.layout()
        self.pool = snap["pool"]
        self.program_id = Pubkey.from_string(snap["program_id"])
        self.lb_pair = snap["lb_pair"]
        self.user = Keypair()
        self._build()

    # -- setup ---------------------------------------------------------------------------

    def _build(self) -> None:
        snap = self.snap
        # A snapshot's blockhash is meaningless here and we sign with a throwaway user, so
        # both checks would only reject transactions the mainnet program never sees.
        svm = (
            LiteSVM()
            .with_sigverify(False)
            .with_blockhash_check(False)
            .with_log_bytes_limit(None)
            .with_feature_set(LiteSVM.mainnet_feature_set())
        )
        import snapshot as snapshot_mod

        for pid, entry in snap["programs"].items():
            svm.add_program(Pubkey.from_string(pid), snapshot_mod.load_program(entry))
        for key, acct in snap["accounts"].items():
            svm.set_account(
                Pubkey.from_string(key),
                Account(
                    lamports=acct["lamports"],
                    data=base64.b64decode(acct["data"]),
                    owner=Pubkey.from_string(acct["owner"]),
                    executable=False,
                    rent_epoch=acct["rent_epoch"],
                ),
            )
        self.set_clock(snap["block_time"], snap["slot"], svm=svm)
        svm.airdrop(self.user.pubkey(), 100 * 10**9)
        self.svm = svm

        self.user_x = self._clone_token_account(self.lb_pair["reserve_x"], funding=0)
        self.user_y = self._clone_token_account(self.lb_pair["reserve_y"], funding=0)

    def set_clock(self, unix_timestamp: int, slot: int, *, svm: LiteSVM | None = None) -> None:
        """Set the wall clock the program will read.

        This is a real semantic input to a DLMM swap, not harness bookkeeping. The dynamic
        fee is driven by `volatility_reference`, which the program DECAYS on entry by the
        time elapsed since `last_update_timestamp` (against `filter_period` and
        `decay_period`). Replay a swap with the wrong timestamp and the bin math still comes
        out to the lamport while the fee -- and so `amount_out` -- silently does not.

        Any model of these semantics has to take the timestamp as an input for the same
        reason.
        """
        target = svm if svm is not None else self.svm
        epoch = slot // 432_000
        target.set_clock(
            Clock(
                slot=slot,
                epoch_start_timestamp=unix_timestamp,
                epoch=epoch,
                leader_schedule_epoch=epoch + 1,
                unix_timestamp=unix_timestamp,
            )
        )

    def _clone_token_account(self, template: str, *, funding: int) -> Pubkey:
        """Make a token account for our synthetic user with the same shape as the pool's reserve.

        Cloning rather than constructing means Token-2022 extension state (transfer-fee
        bookkeeping, immutable owner, and so on) is correct by construction. Constructing a
        bare 165-byte account would be rejected by Token-2022 for any mint whose extensions
        require matching account extensions.
        """
        acct = self.snap["accounts"][template]
        data = bytearray(base64.b64decode(acct["data"]))
        data[_TA_OWNER] = bytes(self.user.pubkey())
        data[_TA_AMOUNT] = funding.to_bytes(8, "little")
        if data[_TA_STATE] != 1:
            raise HarnessUnsupported(f"reserve {template} is not in the Initialized state")

        lamports = acct["lamports"]
        is_native = int.from_bytes(data[_TA_IS_NATIVE_TAG], "little") == 1
        if is_native:
            # A wrapped-SOL account's spendable balance must be backed by real lamports.
            lamports = self.svm.minimum_balance_for_rent_exemption(len(data)) + funding

        key = Keypair().pubkey()
        self.svm.set_account(
            key,
            Account(
                lamports=lamports,
                data=bytes(data),
                owner=Pubkey.from_string(acct["owner"]),
                executable=False,
                rent_epoch=0,
            ),
        )
        return key

    def to_snapshot(self) -> dict[str, Any]:
        """Serialise the machine's CURRENT pool state back into a snapshot.

        Mid-chain, this state has been checked against mainnet's own event at every step, so
        it is mainnet's state at that point -- which makes it a legitimate pre-state to pin a
        fixture on. That is what makes a corpus affordable: one live capture yields as many
        offline fixtures as the chain has verified steps, instead of one RPC round trip and
        5 MB per swap.
        """
        snap = dict(self.snap)
        accounts = {}
        for key, acct in self.snap["accounts"].items():
            live = self.svm.get_account(Pubkey.from_string(key))
            if live is None:
                accounts[key] = acct
                continue
            accounts[key] = {
                "lamports": live.lamports,
                "owner": str(live.owner),
                "executable": False,
                "rent_epoch": acct["rent_epoch"],
                "data": base64.b64encode(bytes(live.data)).decode(),
            }
        snap["accounts"] = accounts
        pair = self.svm.get_account(Pubkey.from_string(self.pool))
        assert pair is not None
        snap["lb_pair"] = self.layout.decode_account("LbPair", bytes(pair.data))
        snap["derived_from"] = self.snap.get("pool")
        return snap

    def load_snapshot_account(self, key: str) -> None:
        """Write one snapshot account into the machine, if it is not already there.

        Host fee accounts are per-transaction, so they arrive after construction. Loading
        lazily beats rebuilding the machine (which would cost the ELF verification again) and
        beats silently dropping the account (which would change the fee split).
        """
        if self.svm.get_account(Pubkey.from_string(key)) is not None:
            return
        acct = self.snap["accounts"].get(key)
        if acct is None:
            raise HarnessUnsupported(
                f"account {key} is needed for this swap but the snapshot does not carry it"
            )
        self.svm.set_account(
            Pubkey.from_string(key),
            Account(
                lamports=acct["lamports"],
                data=base64.b64decode(acct["data"]),
                owner=Pubkey.from_string(acct["owner"]),
                executable=False,
                rent_epoch=acct["rent_epoch"],
            ),
        )

    def reset_pool_state(self) -> None:
        """Restore every pool account to the snapshot, so swaps do not compound.

        Without this, asking the same question twice gives two different answers: the second
        swap runs against the state the first one left behind. Measured drifting the reserves
        by exactly one swap per call while `amount_out` held steady -- which is the dangerous
        version, because a shallow test would see a stable number and call it deterministic.
        """
        for key, acct in self.snap["accounts"].items():
            self.svm.set_account(
                Pubkey.from_string(key),
                Account(
                    lamports=acct["lamports"],
                    data=base64.b64decode(acct["data"]),
                    owner=Pubkey.from_string(acct["owner"]),
                    executable=False,
                    rent_epoch=acct["rent_epoch"],
                ),
            )

    def _fund(self, account: Pubkey, amount: int) -> None:
        existing = self.svm.get_account(account)
        assert existing is not None
        data = bytearray(existing.data)
        data[_TA_AMOUNT] = amount.to_bytes(8, "little")
        lamports = existing.lamports
        if int.from_bytes(data[_TA_IS_NATIVE_TAG], "little") == 1:
            lamports = self.svm.minimum_balance_for_rent_exemption(len(data)) + amount
        self.svm.set_account(
            account,
            Account(
                lamports=lamports,
                data=bytes(data),
                owner=existing.owner,
                executable=False,
                rent_epoch=0,
            ),
        )

    # -- reading -------------------------------------------------------------------------

    def read_state(self) -> PoolState:
        pair_acct = self.svm.get_account(Pubkey.from_string(self.pool))
        assert pair_acct is not None
        pair = self.layout.decode_account("LbPair", bytes(pair_acct.data))

        raw_bin_arrays: dict[str, tuple[int, bytes]] = {}
        for key, index in self.snap["bin_arrays"].items():
            acct = self.svm.get_account(Pubkey.from_string(key))
            if acct is None:
                continue
            raw_bin_arrays[key] = (index, bytes(acct.data))

        rx = self.svm.get_account(Pubkey.from_string(self.lb_pair["reserve_x"]))
        ry = self.svm.get_account(Pubkey.from_string(self.lb_pair["reserve_y"]))
        assert rx is not None and ry is not None
        return PoolState(
            active_id=pair["active_id"],
            reserve_x=_token_amount(bytes(rx.data)),
            reserve_y=_token_amount(bytes(ry.data)),
            protocol_fee_x=pair["protocol_fee"]["amount_x"],
            protocol_fee_y=pair["protocol_fee"]["amount_y"],
            volatility_accumulator=pair["v_parameters"]["volatility_accumulator"],
            volatility_reference=pair["v_parameters"]["volatility_reference"],
            index_reference=pair["v_parameters"]["index_reference"],
            last_update_timestamp=pair["v_parameters"]["last_update_timestamp"],
            raw_bin_arrays=raw_bin_arrays,
            _layout=self.layout,
        )

    # -- executing -----------------------------------------------------------------------

    def _bin_array_metas(self, swap_for_y: bool) -> list[AccountMeta]:
        """Bin arrays in traversal order: descending when selling X, ascending when buying X."""
        ordered = sorted(self.snap["bin_arrays"].items(), key=lambda kv: kv[1], reverse=swap_for_y)
        return [AccountMeta(Pubkey.from_string(k), False, True) for k, _ in ordered]

    def swap_instruction(
        self,
        amount_in: int,
        *,
        swap_for_y: bool,
        min_amount_out: int = 0,
        host_fee_in: str | None = None,
    ) -> Instruction:
        snap = self.snap
        user_in, user_out = (self.user_x, self.user_y) if swap_for_y else (self.user_y, self.user_x)
        ix = self.layout.instruction("swap2")
        data = bytes(ix["discriminator"]) + struct.pack("<QQ", amount_in, min_amount_out)
        data += struct.pack("<I", 0)  # RemainingAccountsInfo { slices: [] } -- no transfer hooks

        bitmap = snap["bitmap_extension"] or snap["program_id"]
        metas = [
            AccountMeta(Pubkey.from_string(self.pool), False, True),
            AccountMeta(Pubkey.from_string(bitmap), False, snap["bitmap_extension"] is not None),
            AccountMeta(Pubkey.from_string(self.lb_pair["reserve_x"]), False, True),
            AccountMeta(Pubkey.from_string(self.lb_pair["reserve_y"]), False, True),
            AccountMeta(user_in, False, True),
            AccountMeta(user_out, False, True),
            AccountMeta(Pubkey.from_string(self.lb_pair["token_x_mint"]), False, False),
            AccountMeta(Pubkey.from_string(self.lb_pair["token_y_mint"]), False, False),
            AccountMeta(Pubkey.from_string(self.lb_pair["oracle"]), False, True),
            # host_fee_in. Anchor's optional-account convention is to pass the program id
            # when absent. Supplying a real one splits the protocol fee -- 20% of it is
            # diverted to the host -- so a replay that ignores a recorded referral account
            # reproduces `fee` and `amount_out` exactly while reporting a `protocol_fee` that
            # is too high by precisely the host's cut. Measured, not theorised.
            AccountMeta(
                Pubkey.from_string(host_fee_in) if host_fee_in else self.program_id,
                False,
                host_fee_in is not None,
            ),
            AccountMeta(self.user.pubkey(), True, False),
            AccountMeta(Pubkey.from_string(snap["token_x_program"]), False, False),
            AccountMeta(Pubkey.from_string(snap["token_y_program"]), False, False),
            AccountMeta(Pubkey.from_string(snap["memo_program"]), False, False),
            AccountMeta(Pubkey.from_string(snap["event_authority"]), False, False),
            AccountMeta(self.program_id, False, False),
            *self._bin_array_metas(swap_for_y),
        ]
        return Instruction(self.program_id, data, metas)

    def swap(
        self,
        amount_in: int,
        *,
        swap_for_y: bool,
        min_amount_out: int = 0,
        unix_timestamp: int | None = None,
        slot: int | None = None,
        persist: bool = False,
        host_fee_in: str | None = None,
    ) -> SwapResult:
        """Execute one swap against the deployed program. Raises `SwapFailed` if it reverts.

        `unix_timestamp` defaults to the snapshot's block time. Pass the timestamp of the
        swap being modelled when replaying a recorded one -- see `set_clock`.

        By default the pool is restored to the snapshot first, so each call answers a question
        about the SAME state. Pass `persist=True` to chain swaps instead, which is what a
        forward replay of a recorded transaction stream wants: there, each swap really did
        run on the state the previous one left.
        """
        if amount_in <= 0:
            raise ValueError("amount_in must be positive")
        if not persist:
            self.reset_pool_state()
        if unix_timestamp is not None or slot is not None:
            self.set_clock(
                unix_timestamp if unix_timestamp is not None else self.snap["block_time"],
                slot if slot is not None else self.snap["slot"],
            )
        user_in, user_out = (self.user_x, self.user_y) if swap_for_y else (self.user_y, self.user_x)
        self._fund(user_in, amount_in)
        self._fund(user_out, 0)

        if host_fee_in is not None:
            self.load_snapshot_account(host_fee_in)

        before = self.read_state()
        ix = self.swap_instruction(
            amount_in,
            swap_for_y=swap_for_y,
            min_amount_out=min_amount_out,
            host_fee_in=host_fee_in,
        )
        msg = Message.new_with_blockhash([ix], self.user.pubkey(), self.svm.latest_blockhash())
        tx = Transaction([self.user], msg, self.svm.latest_blockhash())

        result = self.svm.send_transaction(tx)
        if type(result).__name__ == "FailedTransactionMetadata":
            raise SwapFailed(
                f"deployed program rejected the swap: {result.err()}", list(result.meta().logs())
            )

        after = self.read_state()
        out_acct = self.svm.get_account(user_out)
        assert out_acct is not None
        return SwapResult(
            amount_in=amount_in,
            amount_out=_token_amount(bytes(out_acct.data)),
            swap_for_y=swap_for_y,
            before=before,
            after=after,
            event=_decode_swap_event(result, self.layout),
            compute_units=result.compute_units_consumed(),
            logs=list(result.logs()),
        )


def from_snapshot_file(path: str | Path) -> DlmmSvm:
    import snapshot as snapshot_mod

    return DlmmSvm(snapshot_mod.load(Path(path)))
