"""Her position's actual history, reconstructed from retained transaction bytes.

The unit of truth is one retained ``getTransaction`` result. From each, this module takes:
the ``lb_clmm`` events the transaction emitted (deposit, withdrawal, claim, rebalance,
create, close), the pre/post token balances of the pool's two reserve accounts, the
transaction fee, and the lamport deltas of any position account created or closed. Events
are then **reconciled against the reserve deltas of the same transaction**: a transaction
whose emitted amounts and balance deltas disagree is carried with its disagreement stated,
never averaged into the totals silently.

Every leg is valued at its own transaction's active-bin price — state age zero by
construction — and money that is summed is ``Decimal`` on atom integers. The panel
separates, with windows and denominators attached:

* **gross fee rate** — fees claimed (plus pending, age stated) over time-weighted deployed
  value;
* **net rate** — the same numerator minus the inventory shift each exit or recenter
  crystallized (exit legs versus holding that position's entry legs, both at the exit
  transaction's own price), minus transaction fees and net rent.

The net rate is therefore **LP-versus-holding-the-same-legs**: price drift on inventory she
would have held anyway is not charged to the policy, and the absolute total including drift
is its own field. What this file cannot state: deployed value between events drifts with
price and is marked at the last leg-priced value (method named on the panel), and the open
episode's shift is unrealized until she closes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .events import decode_transaction_events
from .layouts import bin_price_ratio

__all__ = [
    "LedgerEvent",
    "PoolIdentity",
    "ReconstructionPanel",
    "build_ledger",
    "reconstruct",
]

LAMPORTS_PER_SOL = Decimal(1_000_000_000)


@dataclass(frozen=True)
class PoolIdentity:
    """What the pool's own bytes plus the mint accounts state about the pair."""

    address: str
    bin_step: int
    token_x_mint: str
    token_y_mint: str
    reserve_x: str
    reserve_y: str
    x_decimals: int
    y_decimals: int
    #: True when Y is the quote (the side prices are stated in). Derived from mints by the
    #: caller, an outside attribution the pool bytes never make.
    quote_is_y: bool

    def quote_per_base_display(self, bin_id: int) -> Decimal:
        """Display-unit price of the base token in quote units at one bin."""
        ratio = bin_price_ratio(self.bin_step, bin_id)  # Y atoms per X atom
        scale = Decimal(10) ** (self.x_decimals - self.y_decimals)
        if self.quote_is_y:
            return ratio * scale
        return 1 / (ratio * scale)

    def display_x(self, atoms: int) -> Decimal:
        return Decimal(atoms) / Decimal(10) ** self.x_decimals

    def display_y(self, atoms: int) -> Decimal:
        return Decimal(atoms) / Decimal(10) ** self.y_decimals

    def value_in_quote(self, x_atoms: int, y_atoms: int, bin_id: int) -> Decimal:
        """Value of an (x, y) leg pair in display quote units at one bin's price."""
        price = self.quote_per_base_display(bin_id)
        if self.quote_is_y:
            return self.display_y(y_atoms) + self.display_x(x_atoms) * price
        return self.display_x(x_atoms) + self.display_y(y_atoms) * price


@dataclass(frozen=True)
class LedgerEvent:
    """One position-affecting action, as one transaction stated it.

    ``x_in/y_in`` are atoms that entered the pool from her; ``x_out/y_out`` atoms that left
    the pool to her (principal); ``fee_x/fee_y`` atoms that left the pool to her as fees.
    A rebalance carries both directions in one row.
    """

    signature: str
    slot: int
    block_time: int
    kind: str  # deposit | withdraw | claim | rebalance | create | close | failed
    position: str
    active_id: int | None
    x_in: int
    y_in: int
    x_out: int
    y_out: int
    fee_x: int
    fee_y: int
    tx_fee_lamports: int
    rent_lamports: int  # signed: positive when rent left her wallet (create)
    reconciled: bool
    note: str


def _account_keys(transaction: dict) -> list[str]:
    message = transaction["transaction"]["message"]
    keys = []
    for entry in message.get("accountKeys", []):
        keys.append(entry["pubkey"] if isinstance(entry, dict) else entry)
    loaded = (transaction.get("meta") or {}).get("loadedAddresses") or {}
    keys.extend(loaded.get("writable") or [])
    keys.extend(loaded.get("readonly") or [])
    return keys


def _token_deltas(transaction: dict, keys: list[str]) -> dict[str, int]:
    """Token-account deltas in atoms, keyed by token-account pubkey."""
    meta = transaction.get("meta") or {}
    pre: dict[int, int] = {}
    post: dict[int, int] = {}
    for row in meta.get("preTokenBalances") or []:
        pre[row["accountIndex"]] = int(row["uiTokenAmount"]["amount"])
    for row in meta.get("postTokenBalances") or []:
        post[row["accountIndex"]] = int(row["uiTokenAmount"]["amount"])
    deltas: dict[str, int] = {}
    for index in set(pre) | set(post):
        if index < len(keys):
            deltas[keys[index]] = post.get(index, 0) - pre.get(index, 0)
    return deltas


def _lamport_delta(transaction: dict, keys: list[str], pubkey: str) -> int:
    meta = transaction.get("meta") or {}
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    try:
        index = keys.index(pubkey)
    except ValueError:
        return 0
    if index >= len(pre) or index >= len(post):
        return 0
    return post[index] - pre[index]


def build_ledger(transactions: list[dict], pool: PoolIdentity, wallet: str) -> list[LedgerEvent]:
    """Extracts and reconciles position-affecting events from retained transactions.

    Only events naming this pool (or a position already known to belong to it) are read.
    Transactions that failed (``meta.err`` set) contribute their fee and nothing else.
    """
    ledger: list[LedgerEvent] = []
    known_positions: set[str] = set()
    ordered = sorted(transactions, key=lambda t: (t["slot"], t["transaction"]["signatures"][0]))
    for transaction in ordered:
        signature = transaction["transaction"]["signatures"][0]
        slot = transaction["slot"]
        block_time = transaction.get("blockTime") or 0
        meta = transaction.get("meta") or {}
        keys = _account_keys(transaction)
        tx_fee = int(meta.get("fee") or 0) if keys[:1] == [wallet] else 0
        if meta.get("err") is not None:
            if tx_fee:
                ledger.append(
                    LedgerEvent(
                        signature, slot, block_time, "failed", "", None,
                        0, 0, 0, 0, 0, 0, tx_fee, 0, True, "failed transaction; fee only",
                    )
                )
            continue
        decoded = decode_transaction_events(transaction)
        deltas = _token_deltas(transaction, keys)
        reserve_x_delta = deltas.get(pool.reserve_x, 0)
        reserve_y_delta = deltas.get(pool.reserve_y, 0)
        expected_x = 0
        expected_y = 0
        rows: list[LedgerEvent] = []
        fee_charged = False  # charge the tx fee to the first row of the tx only
        # The program double-emits claims (legacy ClaimFee beside ClaimFee2, same amounts,
        # observed on retained mainnet bytes and confirmed by the reserve deltas matching
        # only a single claim). Keep the ClaimFee2 and drop its legacy twin.
        events = list(decoded.events)
        claim2_keys = [
            (e["position"], e["fee_x"], e["fee_y"]) for e in events if e["event"] == "ClaimFee2"
        ]
        deduped: list[dict] = []
        for event in events:
            if event["event"] == "ClaimFee":
                key = (event["position"], event["fee_x"], event["fee_y"])
                if key in claim2_keys:
                    claim2_keys.remove(key)
                    continue
            deduped.append(event)
        for event in deduped:
            name = event["event"]
            if event.get("lb_pair") not in (None, pool.address):
                continue
            if name in ("Swap", "Swap2Evt"):
                # Not a ledger row, but a zap-style transaction can swap against this very
                # pool, so the swap's flows belong in the reserve reconciliation.
                if event["swap_for_y"]:
                    expected_x += event["amount_in"]
                    expected_y -= event["amount_out"]
                else:
                    expected_y += event["amount_in"]
                    expected_x -= event["amount_out"]
                continue
            if name == "CompositionFee":
                continue  # charged inside the pool; reserve-neutral, not her flow
            if name == "PositionClose" and event["position"] not in known_positions:
                continue
            position = event.get("position", "")
            if position:
                known_positions.add(position)
            tx_fee_row = 0 if fee_charged else tx_fee
            fee_charged = True
            base = dict(
                signature=signature, slot=slot, block_time=block_time, position=position,
                x_in=0, y_in=0, x_out=0, y_out=0, fee_x=0, fee_y=0,
                tx_fee_lamports=tx_fee_row, rent_lamports=0, reconciled=True, note="",
            )
            if name == "AddLiquidity":
                expected_x += event["amount_x"]
                expected_y += event["amount_y"]
                rows.append(LedgerEvent(
                    kind="deposit", active_id=event["active_bin_id"],
                    **{**base, "x_in": event["amount_x"], "y_in": event["amount_y"]},
                ))
            elif name == "RemoveLiquidity":
                expected_x -= event["amount_x"]
                expected_y -= event["amount_y"]
                rows.append(LedgerEvent(
                    kind="withdraw", active_id=event["active_bin_id"],
                    **{**base, "x_out": event["amount_x"], "y_out": event["amount_y"]},
                ))
            elif name in ("ClaimFee", "ClaimFee2"):
                expected_x -= event["fee_x"]
                expected_y -= event["fee_y"]
                rows.append(LedgerEvent(
                    kind="claim", active_id=event.get("active_bin_id"),
                    **{**base, "fee_x": event["fee_x"], "fee_y": event["fee_y"]},
                ))
            elif name == "Rebalancing":
                expected_x += (
                    event["x_added_amount"] - event["x_withdrawn_amount"] - event["x_fee_amount"]
                )
                expected_y += (
                    event["y_added_amount"] - event["y_withdrawn_amount"] - event["y_fee_amount"]
                )
                rows.append(LedgerEvent(
                    kind="rebalance", active_id=event["active_bin_id"],
                    **{
                        **base,
                        "x_in": event["x_added_amount"], "y_in": event["y_added_amount"],
                        "x_out": event["x_withdrawn_amount"], "y_out": event["y_withdrawn_amount"],
                        "fee_x": event["x_fee_amount"], "fee_y": event["y_fee_amount"],
                        "note": (
                            f"band {event['old_min_id']}..{event['old_max_id']} -> "
                            f"{event['new_min_id']}..{event['new_max_id']}"
                        ),
                    },
                ))
            elif name == "PositionCreate":
                rent = _lamport_delta(transaction, keys, position)
                rows.append(LedgerEvent(
                    kind="create", active_id=None, **{**base, "rent_lamports": max(rent, 0)},
                ))
            elif name == "PositionClose":
                rent = _lamport_delta(transaction, keys, position)
                rows.append(LedgerEvent(
                    kind="close", active_id=None, **{**base, "rent_lamports": min(rent, 0)},
                ))
        if not rows:
            continue
        reconciled = expected_x == reserve_x_delta and expected_y == reserve_y_delta
        note = ""
        if not reconciled:
            note = (
                f"reserve deltas x={reserve_x_delta} y={reserve_y_delta} disagree with "
                f"events x={expected_x} y={expected_y}"
            )
            if decoded.logs_truncated:
                note += "; logs were truncated, the event set may be a floor"
        for row in rows:
            ledger.append(
                LedgerEvent(
                    row.signature, row.slot, row.block_time, row.kind, row.position,
                    row.active_id, row.x_in, row.y_in, row.x_out, row.y_out, row.fee_x,
                    row.fee_y, row.tx_fee_lamports, row.rent_lamports, reconciled,
                    row.note or note,
                )
            )
    return ledger


@dataclass
class ReconstructionPanel:
    """The net-versus-gross verdict with its receipts. All money in display quote units.

    Rates cover only ANCHORED positions — those whose creation is inside the retained
    window, so every principal atom that ever entered them is on the ledger. Positions
    whose life began before the window are reported as unanchored flow totals and kept out
    of every rate, because a shift computed against unseen entries would be an invention.
    """

    window_start_unix: int
    window_end_unix: int
    elapsed_days: Decimal
    anchored_positions: int
    unanchored_positions: int
    deposits_quote: Decimal
    withdrawals_quote: Decimal
    fees_claimed_quote: Decimal
    fees_pending_quote: Decimal
    fees_pending_age_s: int
    open_value_quote: Decimal
    open_value_age_s: int
    realized_shift_quote: Decimal  # closed anchored positions: exits vs holding their legs
    open_shift_quote: Decimal  # open anchored positions, NAV included; unrealized
    tx_fees_quote: Decimal
    rent_net_quote: Decimal
    time_weighted_deployed_quote: Decimal
    gross_fee_rate_per_day: Decimal | None
    net_rate_per_day: Decimal | None
    absolute_net_quote: Decimal  # anchored: out + open + fees - in - costs, drift included
    unanchored_in_quote: Decimal
    unanchored_out_quote: Decimal
    unanchored_fees_quote: Decimal
    rebalance_transactions: int
    withdraw_transactions: int
    unreconciled_transactions: int
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        out = {}
        for key, value in self.__dict__.items():
            out[key] = str(value) if isinstance(value, Decimal) else value
        return out


@dataclass
class _PositionBook:
    created: bool = False
    closed: bool = False
    in_x: int = 0
    in_y: int = 0
    out_x: int = 0
    out_y: int = 0
    in_value: Decimal = Decimal(0)
    out_value: Decimal = Decimal(0)
    fees_value: Decimal = Decimal(0)
    last_bin: int | None = None


def reconstruct(
    ledger: list[LedgerEvent],
    pool: PoolIdentity,
    *,
    now_unix: int,
    open_position_values: dict[str, tuple[int, int, int]] | None,
    pending_fees: tuple[int, int, int] | None,
    sol_is_base: bool,
) -> ReconstructionPanel:
    """Folds the ledger into the net-versus-gross panel.

    ``open_position_values`` maps an open position address to ``(x_atoms, y_atoms,
    read_unix)`` as read back from its shares and the bin arrays; ``pending_fees`` is the
    aggregate unclaimed-fee readback in the same shape. ``None`` means unread, carried as
    absence with a note. Lamport costs convert at each transaction's own active-bin price
    when SOL is a pool side.
    """
    events = sorted(ledger, key=lambda e: (e.slot, e.signature))
    if not any(e.kind != "failed" for e in events):
        raise ValueError("empty ledger: nothing to reconstruct")
    start = min(e.block_time for e in events)
    tx_bin: dict[str, int] = {}
    for event in events:
        if event.active_id is not None and event.signature not in tx_bin:
            tx_bin[event.signature] = event.active_id

    book: dict[str, _PositionBook] = {}
    tx_fees_quote = Decimal(0)
    rent_net_quote = Decimal(0)
    notes: list[str] = []
    last_price_bin: int | None = None
    rebalance_txs: set[str] = set()
    withdraw_txs: set[str] = set()
    unreconciled = {e.signature for e in ledger if not e.reconciled}

    # Time-weighted deployed value over anchored positions, integrated between events.
    twd_num = Decimal(0)
    twd_last_value = Decimal(0)
    twd_last_time = start

    def anchored_deployed(bin_id: int) -> Decimal:
        total = Decimal(0)
        for state in book.values():
            if not state.created or state.closed:
                continue
            net_x = max(state.in_x - state.out_x, 0)
            net_y = max(state.in_y - state.out_y, 0)
            total += pool.value_in_quote(net_x, net_y, bin_id)
        return total

    for event in events:
        cost_bin = tx_bin.get(event.signature, last_price_bin)
        if event.tx_fee_lamports and sol_is_base and cost_bin is not None:
            tx_fees_quote += (
                Decimal(event.tx_fee_lamports)
                / LAMPORTS_PER_SOL
                * pool.quote_per_base_display(cost_bin)
            )
        elif event.tx_fee_lamports:
            notes.append(
                f"tx fee of {event.tx_fee_lamports} lamports at {event.signature[:8]}... "
                "predates any priced state; carried unconverted"
            )
        if event.rent_lamports:
            if sol_is_base and cost_bin is not None:
                rent_net_quote += (
                    Decimal(event.rent_lamports)
                    / LAMPORTS_PER_SOL
                    * pool.quote_per_base_display(cost_bin)
                )
            else:
                notes.append(
                    f"rent of {event.rent_lamports} lamports at {event.signature[:8]}... "
                    "predates any priced state; carried unconverted"
                )
        if event.kind == "failed":
            continue
        state = book.setdefault(event.position, _PositionBook())
        if event.kind == "create":
            state.created = True
            continue
        if event.kind == "close":
            state.closed = True
            continue
        if event.active_id is not None:
            last_price_bin = event.active_id
        if last_price_bin is None:
            raise ValueError("no active bin observed before the first valued leg")
        bin_id = last_price_bin
        state.last_bin = bin_id

        twd_num += twd_last_value * Decimal(max(event.block_time - twd_last_time, 0))
        twd_last_time = event.block_time

        if event.fee_x or event.fee_y:
            state.fees_value += pool.value_in_quote(event.fee_x, event.fee_y, bin_id)
        if event.x_in or event.y_in:
            state.in_x += event.x_in
            state.in_y += event.y_in
            state.in_value += pool.value_in_quote(event.x_in, event.y_in, bin_id)
        if event.x_out or event.y_out:
            state.out_x += event.x_out
            state.out_y += event.y_out
            state.out_value += pool.value_in_quote(event.x_out, event.y_out, bin_id)
        if event.kind == "rebalance":
            rebalance_txs.add(event.signature)
        if event.kind == "withdraw":
            withdraw_txs.add(event.signature)
        twd_last_value = anchored_deployed(bin_id)

    twd_num += twd_last_value * Decimal(max(now_unix - twd_last_time, 0))
    elapsed_s = max(now_unix - start, 1)
    time_weighted_deployed = twd_num / Decimal(elapsed_s)

    deposits = Decimal(0)
    withdrawals = Decimal(0)
    fees_claimed = Decimal(0)
    realized_shift = Decimal(0)
    open_shift = Decimal(0)
    open_value = Decimal(0)
    open_age = -1
    unanchored_in = Decimal(0)
    unanchored_out = Decimal(0)
    unanchored_fees = Decimal(0)
    anchored = 0
    unanchored = 0

    for address, state in book.items():
        if not state.created:
            unanchored += 1
            unanchored_in += state.in_value
            unanchored_out += state.out_value
            unanchored_fees += state.fees_value
            continue
        anchored += 1
        deposits += state.in_value
        withdrawals += state.out_value
        fees_claimed += state.fees_value
        if state.closed:
            final_bin = state.last_bin if state.last_bin is not None else last_price_bin
            realized_shift += state.out_value - pool.value_in_quote(
                state.in_x, state.in_y, final_bin
            )
        else:
            readback = (open_position_values or {}).get(address)
            if readback is None:
                notes.append(
                    f"open anchored position {address[:8]}... has no NAV readback; its "
                    "shift is ABSENT from the net rate, not zero"
                )
                continue
            x_atoms, y_atoms, read_unix = readback
            if last_price_bin is None:
                raise ValueError("open position value with no priced state to value it at")
            nav = pool.value_in_quote(x_atoms, y_atoms, last_price_bin)
            open_value += nav
            open_age = max(open_age, max(now_unix - read_unix, 0))
            open_shift += (
                state.out_value
                + nav
                - pool.value_in_quote(state.in_x, state.in_y, last_price_bin)
            )

    fees_pending = Decimal(0)
    pending_age = -1
    if pending_fees is not None:
        pending_x, pending_y, read_unix = pending_fees
        if last_price_bin is not None:
            fees_pending = pool.value_in_quote(pending_x, pending_y, last_price_bin)
        pending_age = max(now_unix - read_unix, 0)
    else:
        notes.append("pending fees UNREAD; gross rate is a floor")

    elapsed_days = Decimal(elapsed_s) / Decimal(86_400)
    gross_rate = None
    net_rate = None
    if time_weighted_deployed > 0:
        gross_rate = (fees_claimed + fees_pending) / time_weighted_deployed / elapsed_days
        # Rent is excluded from the RATE: it is recoverable (paid at create, returned at
        # close) and nets toward zero over full cycles, while a bounded window sees the
        # recoveries of positions whose payments predate it. It stays in the absolute.
        net_numerator = (
            fees_claimed + fees_pending + realized_shift + open_shift - tx_fees_quote
        )
        net_rate = net_numerator / time_weighted_deployed / elapsed_days
    absolute_net = (
        withdrawals
        + open_value
        + fees_claimed
        + fees_pending
        - deposits
        - tx_fees_quote
        - rent_net_quote
    )
    if unreconciled:
        notes.append(
            f"{len(unreconciled)} transaction(s) did not reconcile events against reserve "
            "deltas; their rows are included and flagged"
        )
    if unanchored:
        notes.append(
            f"{unanchored} position(s) predate the retained window; their flows are "
            "reported apart and excluded from every rate"
        )
    notes.append(
        "shift = exits at their own prices plus NAV, versus holding each position's "
        "deposited legs to its final price; deployed value between events is marked at "
        "the last event's price on net contributed legs"
    )

    return ReconstructionPanel(
        window_start_unix=start,
        window_end_unix=now_unix,
        elapsed_days=elapsed_days,
        anchored_positions=anchored,
        unanchored_positions=unanchored,
        deposits_quote=deposits,
        withdrawals_quote=withdrawals,
        fees_claimed_quote=fees_claimed,
        fees_pending_quote=fees_pending,
        fees_pending_age_s=pending_age,
        open_value_quote=open_value,
        open_value_age_s=open_age,
        realized_shift_quote=realized_shift,
        open_shift_quote=open_shift,
        tx_fees_quote=tx_fees_quote,
        rent_net_quote=rent_net_quote,
        time_weighted_deployed_quote=time_weighted_deployed,
        gross_fee_rate_per_day=gross_rate,
        net_rate_per_day=net_rate,
        absolute_net_quote=absolute_net,
        unanchored_in_quote=unanchored_in,
        unanchored_out_quote=unanchored_out,
        unanchored_fees_quote=unanchored_fees,
        rebalance_transactions=len(rebalance_txs),
        withdraw_transactions=len(withdraw_txs),
        unreconciled_transactions=len(unreconciled),
        notes=notes,
    )
