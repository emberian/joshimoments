"""Transaction -> swap row, and the honest accounting of what a transaction does not contain.

--------------------------------------------------------------------------------------
WHAT IS RECOVERABLE FROM ONE ``getTransaction`` RESPONSE
--------------------------------------------------------------------------------------

**Recoverable exactly**, in raw integer units, no float anywhere on the path:

- ``signature``, ``slot``, ``blockTime`` (the event clock), ``confirmationStatus``.
- Both vault balances **before and after** the transaction, from ``pre/postTokenBalances``.
  Both DEXes hold the SOL side as a wrapped-SOL token account, so the SOL leg needs no
  separate lamport reconstruction and arrives in the same integer form as any token.
- The **net** amount in and out of the pool, as the two vault deltas.
- The fee payer (Solana defines it as ``accountKeys[0]``), the total transaction fee, and
  every account that signed.
- The count of instructions that invoked the pool's own program with the pool as
  ``accounts[0]`` — the *leg count* — and each leg's Anchor discriminator.

**Recoverable but net, not per-leg.** ``pre/postTokenBalances`` are transaction-scoped. A
transaction that swaps through the *same* pool twice (a same-pool arbitrage cycle) yields one
netted row, not two. This is why ``swap_legs`` is recorded: a row with ``swap_legs > 1`` is a
net and must not be treated as a single fill. It is not inferred after the fact — the
literature's dominant false positive for flow work is exactly this kind of silent aggregation.

**Recoverable only sometimes: the counterparty.** For a direct swap, exactly one non-pool
owner's delta exactly mirrors the pool on the **token** leg, and that owner is the trader. It
has to be one leg rather than both, and that is measured, not assumed: across 13 live cluster
swaps, requiring the mirror on both legs identified the trader **0 times**. Two independent
reasons, both real —

- *the wrapped-SOL account is transient*: a seller receives WSOL and closes the account to
  unwrap inside the same transaction, so its post balance is gone, and a buyer wraps into an
  account created in that transaction, so its pre balance never existed;
- *fees are skimmed between the pool and the trader*: on a live nosis sell the pool paid
  75,666,317 lamports while the trader received 74,983,955, with 18,954 + 644,453 + 18,955
  going to three fee accounts.

For a multi-hop route the trader's net position on the intermediate mint is zero, so no owner
mirrors this pool on either leg and ``counterparty`` is ``None``. ``None`` means NOT
IDENTIFIED, never "the fee payer" — attributing a routed fill to the signer would fabricate
exactly the kind of provenance this project lost 7.47 SOL to.

**NOT recoverable, and the gap that matters most:**

- **A DLMM fill is not a function of the vault totals.** Meteora's concentrated liquidity
  lives in bins; the price is the active bin's, and the fill walks bins. The two vault
  balances are the *sum over all bins* and do not determine the marginal price or the depth.
  So a Meteora reserve row here is a state **summary**, not a replay input. PumpSwap is
  constant-product, where the two reserves do determine the fill exactly, and
  :attr:`shitcoims_cluster.pools.PoolSpec.replay_sufficient_reserves` records which is which.
  Recovering DLMM replay fidelity needs the ``lb_pair`` account plus its ``bin_array``s read
  at the swap's slot — a different instrument, not a parser change.
- **The position of a transaction inside its block.** ``getTransaction`` returns ``slot`` but
  no block index, so :attr:`Chainstamp.tx_index` is left ``None`` and two transactions in the
  same slot are unordered. This is not hypothetical here: 57 of 158 observed slots on the
  nosis/SOL pool and 79 of 117 on weave/nosis carried more than one transaction. Recovering it
  needs ``getBlock``. The measured consequence is bounded and worth stating precisely — across
  every pool, *every* adjacent pair of single-transaction slots chains exactly
  (``post_raw == pre_raw``, 187 pairs, **0** breaks), so the reserve path is complete and the
  ambiguity is strictly intra-slot. It is also resolvable offline without more RPC, because
  within a slot only one permutation chains.
- **Per-leg amounts inside a multi-leg transaction** (see above).
- **Fee split.** ``meta.fee`` is the transaction's total network fee. The LP fee and protocol
  fee taken by the pool are inside the swap event payload, not in the balance deltas, and are
  not decoded here.
- **Priority-fee vs base-fee split**, and any Jito tip, which is an ordinary transfer.

--------------------------------------------------------------------------------------
WHERE ``shitcoims_tape.schema`` FITS, AND WHERE IT DOES NOT
--------------------------------------------------------------------------------------

Used as the real thing, constructed and validated:

- :class:`~shitcoims_tape.schema.Chainstamp` — exact fit. Note that its ``block_time`` is
  ``int | None``; **this recorder makes it mandatory**, and a transaction without one goes to
  the defect stream. That narrowing is the SWARM.md Track B finding applied at the boundary.
- :class:`~shitcoims_tape.schema.Provenance` — exact fit; ``fetched_at`` is ``t_ingest``.
- :class:`~shitcoims_tape.schema.Trade` — fits a SOL-quoted swap with an identified
  counterparty, and :meth:`ClusterSwap.as_trade` returns a real one. It returns ``None``
  otherwise, for two reasons rather than one.
- :class:`~shitcoims_tape.schema.WatchWindow` — used verbatim by
  :mod:`shitcoims_cluster.watch`, with the *pool* address in the field named ``mint``. The
  field is validated as a 32-byte base58 address, which a pool address is; the name is a
  mint-indexed-tape assumption, and it is stretched here rather than forked.

Where it does not fit, and why bending it would be worse:

1. **``Trade`` assumes a SOL leg.** ``sol_delta_lamports`` and ``token_delta_raw`` encode a
   token/SOL pair. Half this cluster is token-token: a weave/nosis swap has no SOL leg at all,
   and there is no non-arbitrary choice of which side is "the token". Writing ``0`` into
   ``sol_delta_lamports`` would make a real zero indistinguishable from an absent
   denomination — the same disease as ``Launch.has_twitter`` defaulting to ``False``, which
   that schema already refuses. So :class:`ClusterSwap` carries both legs symmetrically as
   ``(mint, raw_amount)`` pairs and projects to ``Trade`` only when a SOL leg exists.

2. **``Reserves`` models a pump.fun bonding curve.** Its four fields are
   virtual/real x SOL/token: SOL-denominated, and split into a virtual component that only a
   bonding curve has. A token-token DLMM has no SOL side to put in ``real_sol``.
   :meth:`ClusterSwap.as_tape_reserves` therefore returns a real ``Reserves`` **only** for the
   SOL-quoted constant-product pools, where ``virtual_* = 0`` is not a missing value but the
   exact algebraic statement that a constant-product pool has no virtual component. For the
   Meteora pools it returns ``None`` and :class:`PoolReserves` is the record.

3. **``Trade`` has no ``trader_paid_fee``** (SWARM.md Track B, gap 2). It has ``fee_payer``
   and ``signers``, from which the discriminator is derivable, so :class:`ClusterSwap`
   computes it explicitly as a **tri-state**: ``True``/``False`` when the counterparty is
   identified, ``None`` when it is not. Note that on Solana ``accountKeys[0]`` *is* the fee
   payer by construction, so "did a signer pay the fee" is vacuous; the informative question
   is whether the **trader** paid, which is what is recorded.

4. **No same-slot atomic/bundle field** (Track B, gap 3). ``slot`` plus ``signature`` is
   recorded on every row, so same-slot co-occurrence is computable downstream; the Jito
   bundle id is not on chain at all and cannot be recovered from a transaction.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from shitcoims_cluster.pools import (
    KNOWN_DISCRIMINATORS,
    PUMPSWAP_PROGRAM,
    WSOL_MINT,
    PoolSpec,
)
from shitcoims_cluster.pumpswap import (
    ANCHOR_CPI_EVENT_TAG,
    EventDecodeError,
    SwapEvent,
    decode_swap_event,
)
from shitcoims_tape.schema import Chainstamp, Provenance, Reserves, Side, Trade

SOURCE: Final[str] = "shitcoims_cluster.record"

_B58_ALPHABET: Final[str] = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX: Final[dict[str, int]] = {c: i for i, c in enumerate(_B58_ALPHABET)}


class DefectReason:
    """Why a transaction could not become a tape row. Strings, so the stream is greppable."""

    NO_BLOCK_TIME: Final[str] = "no_block_time"
    TX_MISSING: Final[str] = "tx_missing"
    UNBALANCED_VAULTS: Final[str] = "unbalanced_vaults"
    MINT_MISMATCH: Final[str] = "mint_mismatch"
    MALFORMED: Final[str] = "malformed_transaction"


class RowKind:
    """What a transaction did to the pool, decided by the SIGN STRUCTURE of the vault deltas.

    ``swap`` is one vault up and one down. ``liquidity`` is every nonzero delta pointing the
    same way — an add, a withdrawal or a fee claim. Measured on chain, a Meteora
    ``RemoveLiquidityByRange2`` presents as ``(-1632183148906, -278)`` on the two vaults, which
    a naive "the pool moved, so it was a swap" parser would have booked as an enormous fill.
    The signs decide, not the instruction name, so an unrecognised instruction cannot smuggle
    a fabricated fill onto the tape.

    ``reference`` is every delta zero, *or* the pool's vaults not appearing in the transaction
    at all. Both mean the pool was named and not traded, and this is the **dominant** case:
    across a live three-minute pass, 846 of 1,162 fetched transactions on the six pools were
    references. They are routers carrying the pool in an address-lookup table and filling
    somewhere else.

    Keeping them is deliberate. When the vaults *are* present, a zero-delta row is a **free
    reserve reading at that slot** — it confirms the pool state between swaps at no extra RPC,
    which is exactly what a reserve path wants and what an hourly OHLCV bar destroys. When the
    vaults are absent the row carries no reserves at all (``reserves.vaults == ()``), which is
    a truthful "nothing observed" rather than a defect: a swap *cannot* happen without moving
    a pool-owned token account, and moving one puts it in ``pre/postTokenBalances``, so absent
    vaults is positive evidence of no fill. Routing it to the defect stream, as an earlier
    version did, produced 134 false defects on the DREGG/SOL pool in one pass and would have
    made the defect count uninterpretable — which is the metric that has to stay clean, because
    it is the one that catches the block-time bug.

    Filter on ``kind`` to get flow; read every kind to get the state series.
    """

    SWAP: Final[str] = "swap"
    LIQUIDITY: Final[str] = "liquidity"
    REFERENCE: Final[str] = "reference"
    ATTEMPT: Final[str] = "attempt"
    GAP: Final[str] = "gap"


def _b58_decode(text: str) -> bytes:
    total = 0
    for ch in text:
        index = _B58_INDEX.get(ch)
        if index is None:
            return b""
        total = total * 58 + index
    pad = len(text) - len(text.lstrip("1"))
    body = total.to_bytes((total.bit_length() + 7) // 8, "big") if total else b""
    return b"\x00" * pad + body


def discriminator_of(data_b58: str) -> str:
    """The first 8 bytes of an Anchor instruction payload, as hex. ``""`` when undecodable."""

    raw = _b58_decode(str(data_b58))
    return raw[:8].hex() if len(raw) >= 8 else ""


def utc_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def unix_to_iso(seconds: int) -> str:
    return datetime.fromtimestamp(int(seconds), tz=UTC).isoformat()


@dataclass(frozen=True, slots=True)
class VaultState:
    """One pool vault across a transaction. Raw integer units only."""

    account: str
    mint: str
    decimals: int
    pre_raw: int
    post_raw: int

    @property
    def delta_raw(self) -> int:
        return self.post_raw - self.pre_raw

    def to_json(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "mint": self.mint,
            "decimals": self.decimals,
            "pre_raw": str(self.pre_raw),
            "post_raw": str(self.post_raw),
            "delta_raw": str(self.delta_raw),
        }


@dataclass(frozen=True, slots=True)
class PoolReserves:
    """Pool state either side of the transaction, symmetric in the two mints.

    Deliberately not :class:`shitcoims_tape.schema.Reserves` — see the module docstring, gap 2.
    ``replay_sufficient`` is copied from the pool spec so a downstream replayer never has to
    know which DEX a row came from to know whether it may fill against it.
    """

    pool: str
    dex: str
    vaults: tuple[VaultState, ...]
    #: The pool's TYPE admits exact replay (constant product). Necessary, not sufficient —
    #: see :attr:`replay_exact`.
    replay_sufficient: bool
    #: The reserves the program itself priced against, when it told us. ``None`` means the
    #: vault balances are all we have.
    curve: SwapEvent | None = None

    @property
    def replay_exact(self) -> bool:
        """Whether these numbers are enough to reproduce the fill. The honest flag.

        ``replay_sufficient`` used to carry this claim on its own and it was WRONG for two of
        the four PumpSwap pools: a boosted pool prices against
        ``pool_quote + virtual_quote_reserves``, and the vault holds only the first term (see
        :mod:`shitcoims_cluster.pumpswap`). On nosis/SOL and weave/SOL that is a 4.6% and 9.6%
        error, large enough to invert the sign of a fitted fee. So a constant-product pool is
        replayable only when the curve reserves were actually READ, and a row that lacks the
        event says so instead of asserting from the pool's type.
        """

        if not self.replay_sufficient:
            return False
        if self.dex != "pumpswap":
            return True
        return self.curve is not None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "pool": self.pool,
            "dex": self.dex,
            "replay_sufficient": self.replay_exact,
            "replay_sufficient_by_type": self.replay_sufficient,
            "vaults": [v.to_json() for v in self.vaults],
        }
        # `curve` is the reserve pair the AMM used. It is emitted whenever it was read, even
        # when it equals the vault balances, so a consumer never has to infer which case it is.
        out["curve"] = self.curve.to_json() if self.curve is not None else {"source": "absent"}
        return out

    def vault_for(self, mint: str) -> VaultState | None:
        for vault in self.vaults:
            if vault.mint == mint:
                return vault
        return None


@dataclass(frozen=True, slots=True)
class Defect:
    """A transaction that must never reach the main tape, with the reason preserved."""

    reason: str
    pool: str
    signature: str
    t_ingest: str
    slot: int | None = None
    t_event: str | None = None
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": "defect",
            "reason": self.reason,
            "pool": self.pool,
            "signature": self.signature,
            "t_ingest": self.t_ingest,
            "detail": self.detail,
        }
        if self.slot is not None:
            out["slot"] = self.slot
        if self.t_event is not None:
            out["t_event"] = self.t_event
        return out


@dataclass(frozen=True, slots=True)
class ClusterSwap:
    """One transaction's net effect on one cluster pool.

    Both clocks are present and named so they cannot invert: ``t_event`` is chain time from
    ``blockTime`` and is **mandatory**; ``t_ingest`` is when this process saw it. Analysis
    joins on ``t_event`` only.
    """

    pool: str
    dex: str
    label: str
    row_kind: str
    chain: Chainstamp
    t_event: str
    t_ingest: str
    confirmation_status: str | None
    fee_payer: str
    signers: tuple[str, ...]
    counterparty: str | None
    counterparty_paid_fee: bool | None
    fee_lamports: int
    #: Into the pool / out of the pool. ``None`` on a liquidity row, where there is no
    #: direction: both vaults move the same way.
    token_in_mint: str | None
    token_in_raw: int
    token_out_mint: str | None
    token_out_raw: int
    reserves: PoolReserves
    swap_legs: int
    leg_discriminators: tuple[str, ...]
    leg_names: tuple[str, ...]
    compute_units: int | None
    provenance: Provenance

    # -- derived --------------------------------------------------------------------

    @property
    def is_sol_quoted(self) -> bool:
        return any(v.mint == WSOL_MINT for v in self.reserves.vaults)

    @property
    def side(self) -> Side | None:
        """Buy/sell from the **trader's** view, defined only when one leg is wrapped SOL."""

        if self.row_kind != RowKind.SWAP or not self.is_sol_quoted:
            return None
        # SOL into the pool means the trader spent SOL and received the token: a buy.
        if self.token_in_mint == WSOL_MINT:
            return Side.BUY
        if self.token_out_mint == WSOL_MINT:
            return Side.SELL
        return None

    def as_trade(self) -> Trade | None:
        """Project onto the real tape ``Trade``, or ``None`` when the shape does not fit.

        Returns ``None`` for a token-token pool (no SOL leg to denominate) and for a routed
        swap with no identified counterparty (no wallet to attribute the fill to). Both are
        refusals to fabricate, not failures.
        """

        side = self.side
        if side is None or self.counterparty is None:
            return None
        sol_leg = self.reserves.vault_for(WSOL_MINT)
        token_vault = next((v for v in self.reserves.vaults if v.mint != WSOL_MINT), None)
        if sol_leg is None or token_vault is None:
            return None
        # The trader's deltas are the mirror of the pool's.
        return Trade(
            mint=token_vault.mint,
            wallet=self.counterparty,
            side=side,
            sol_delta_lamports=-sol_leg.delta_raw,
            token_delta_raw=-token_vault.delta_raw,
            pool=self.pool,
            fee_lamports=self.fee_lamports,
            signers=self.signers,
            fee_payer=self.fee_payer,
        )

    def as_tape_reserves(self) -> Reserves | None:
        """A real :class:`~shitcoims_tape.schema.Reserves`, post-state, or ``None``.

        Only for a SOL-quoted constant-product pool whose CURVE reserves were read.

        This used to fill ``virtual_sol=0`` with the comment "a constant-product pool *has* no
        virtual component — that is an exact statement about the AMM, not an unfilled field".
        The statement was false. A boosted PumpSwap pool carries a nonzero
        ``virtual_quote_reserves`` and prices against ``pool_quote + virtual`` (17.58 SOL on
        both nosis/SOL and weave/SOL, 0 on DREGG/SOL and SOLVE/SOL), so the zero was not exact
        — it was the "a zero there reads as measured" failure ``RESULT_bulk_history.md``
        warns about, asserted in a docstring. It now carries the value the program reported.

        ``virtual_tokens`` stays 0, and *that* one is structural: the event layout has no
        base-side virtual field at all.
        """

        curve = self.reserves.curve
        if not self.reserves.replay_exact or not self.is_sol_quoted:
            return None
        sol_leg = self.reserves.vault_for(WSOL_MINT)
        token_vault = next((v for v in self.reserves.vaults if v.mint != WSOL_MINT), None)
        if sol_leg is None or token_vault is None:
            return None
        return Reserves(
            pool=self.pool,
            virtual_sol=0 if curve is None else curve.virtual_quote_raw,
            virtual_tokens=0,
            real_sol=sol_leg.post_raw,
            real_tokens=token_vault.post_raw,
        )

    @property
    def row_id(self) -> str:
        """Content hash over (pool, signature) — the dedupe key across overlapping polls."""

        return hashlib.sha256(f"{self.pool}:{self.chain.signature}".encode()).hexdigest()

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "row_id": self.row_id,
            "kind": self.row_kind,
            "pool": self.pool,
            "dex": self.dex,
            "label": self.label,
            "t_event": self.t_event,
            "t_ingest": self.t_ingest,
            "chain": self.chain.to_json(),
            "confirmation_status": self.confirmation_status,
            "fee_payer": self.fee_payer,
            "signers": list(self.signers),
            "counterparty": self.counterparty,
            "counterparty_paid_fee": self.counterparty_paid_fee,
            "fee_lamports": str(self.fee_lamports),
            "token_in_mint": self.token_in_mint,
            "token_in_raw": str(self.token_in_raw),
            "token_out_mint": self.token_out_mint,
            "token_out_raw": str(self.token_out_raw),
            "swap_legs": self.swap_legs,
            "leg_discriminators": list(self.leg_discriminators),
            "leg_names": list(self.leg_names),
            "reserves": self.reserves.to_json(),
            "provenance": self.provenance.to_json(),
        }
        if self.compute_units is not None:
            out["compute_units"] = self.compute_units
        side = self.side
        if side is not None:
            out["side"] = str(side)
        return out


@dataclass(frozen=True, slots=True)
class Attempt:
    """A transaction that touched the pool and failed on chain.

    Emitted from the signature listing alone — signature, slot, block time and ``err`` all
    arrive there — so an attempt row costs **zero** additional RPC. That matters twice over:
    on the busiest cluster pool 25 of 40 recent transactions had a non-null ``err``, so
    skipping the ``getTransaction`` for failures cut the batched fetch by ~60%, *and* the
    failed-attempt rate is itself a measurement (competition for the same fill) that a
    success-only tape would have thrown away.

    What it deliberately does not carry: the signer and the amounts. Both would require the
    ``getTransaction`` this row exists to avoid.
    """

    pool: str
    dex: str
    label: str
    chain: Chainstamp
    t_event: str
    t_ingest: str
    confirmation_status: str | None
    error: str
    provenance: Provenance

    @property
    def row_id(self) -> str:
        return hashlib.sha256(f"{self.pool}:{self.chain.signature}".encode()).hexdigest()

    def to_json(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "kind": RowKind.ATTEMPT,
            "pool": self.pool,
            "dex": self.dex,
            "label": self.label,
            "t_event": self.t_event,
            "t_ingest": self.t_ingest,
            "chain": self.chain.to_json(),
            "confirmation_status": self.confirmation_status,
            "error": self.error,
            "provenance": self.provenance.to_json(),
        }


# -- parsing ------------------------------------------------------------------------


def _account_keys(message: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    keys = message.get("accountKeys")
    if not isinstance(keys, list):
        return []
    return [k for k in keys if isinstance(k, Mapping)]


def _token_balances(meta: Mapping[str, Any], field: str) -> dict[int, Mapping[str, Any]]:
    out: dict[int, Mapping[str, Any]] = {}
    entries = meta.get(field)
    if not isinstance(entries, list):
        return out
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        index = entry.get("accountIndex")
        if isinstance(index, int):
            out[index] = entry
    return out


def _raw_amount(entry: Mapping[str, Any] | None) -> int:
    """Raw base units as an int. ``uiTokenAmount.amount`` is a decimal STRING, never a float."""

    if entry is None:
        return 0
    ui = entry.get("uiTokenAmount")
    if not isinstance(ui, Mapping):
        return 0
    return int(str(ui.get("amount", "0")))


def _decimals(entry: Mapping[str, Any] | None) -> int:
    if entry is None:
        return 0
    ui = entry.get("uiTokenAmount")
    if not isinstance(ui, Mapping):
        return 0
    return int(ui.get("decimals", 0))


def _all_instructions(tx: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    message = tx.get("transaction", {}).get("message", {})
    top = message.get("instructions")
    if isinstance(top, list):
        out.extend(i for i in top if isinstance(i, Mapping))
    meta = tx.get("meta") or {}
    inner = meta.get("innerInstructions")
    if isinstance(inner, list):
        for group in inner:
            if not isinstance(group, Mapping):
                continue
            items = group.get("instructions")
            if isinstance(items, list):
                out.extend(i for i in items if isinstance(i, Mapping))
    return out


def _pool_legs(tx: Mapping[str, Any], spec: PoolSpec) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Discriminators of the instructions that invoked this pool's program on this pool.

    Both PumpSwap and Meteora DLMM put the pool account first, so ``accounts[0] == pool``
    identifies a leg on *this* pool and excludes the other pools a routed transaction visits.
    Verified on a live route that carried two ``swap2`` instructions on two different DLMM
    pairs: only one of them counted for the pair being recorded.
    """

    discriminators: list[str] = []
    names: list[str] = []
    for ins in _all_instructions(tx):
        if ins.get("programId") != spec.program:
            continue
        accounts = ins.get("accounts")
        if not isinstance(accounts, list) or not accounts or accounts[0] != spec.address:
            continue
        disc = discriminator_of(str(ins.get("data", "")))
        if not disc:
            continue
        if disc == ANCHOR_CPI_EVENT_TAG.hex():
            # An emitted event is a self-CPI back into the same program. It is a REPORT of the
            # swap, not a second swap, and counting it would double `swap_legs` and read a
            # single fill as a multi-leg route.
            continue
        discriminators.append(disc)
        names.append(KNOWN_DISCRIMINATORS.get(disc, ""))
    return tuple(discriminators), tuple(names)


def _pool_swap_event(tx: Mapping[str, Any], spec: PoolSpec) -> SwapEvent | None:
    """The PumpSwap swap event emitted FOR THIS POOL, or ``None`` if there is not exactly one.

    The pool filter is not optional. A routed transaction emits one event per pool it crosses,
    and taking the first would attribute another pool's reserves to this one — the first
    version of this lookup did exactly that and read a 25 SOL reserve onto a 173 SOL pool.

    More than one event for the same pool in one transaction means the pool was crossed twice
    (a sandwich or a cycle), and the reserves then have no single value for the row: that
    returns ``None`` rather than silently picking a side.
    """

    if spec.program != PUMPSWAP_PROGRAM:
        return None
    found: list[SwapEvent] = []
    for ins in _all_instructions(tx):
        if ins.get("programId") != spec.program:
            continue
        raw = _b58_decode(str(ins.get("data", "")))
        if not raw:
            continue
        try:
            event = decode_swap_event(raw)
        except EventDecodeError:
            # The bytes announced themselves as a swap event and did not parse. That is an
            # IDL drift, not a routing detail, and it must not read as "no event".
            return None
        if event is not None and event.pool == spec.address:
            found.append(event)
    return found[0] if len(found) == 1 else None


def _counterparty(
    pre: Mapping[int, Mapping[str, Any]],
    post: Mapping[int, Mapping[str, Any]],
    *,
    pool: str,
    in_mint: str,
    out_mint: str,
    in_raw: int,
    out_raw: int,
) -> str | None:
    """The one non-pool owner whose delta *exactly* mirrors the pool on a leg, or ``None``.

    **Why one leg and not both**, measured on 13 live cluster swaps: requiring the mirror on
    both legs identified the trader in **0** of them. The wrapped-SOL leg is transient — a
    seller receives WSOL and closes the account to unwrap in the same transaction, so its post
    balance is gone; a buyer wraps into a freshly created account, so its pre balance never
    existed. Either way the trader's *net* WSOL delta is not the swap amount. On the token leg
    the account persists, and the mirror is exact: ``delta == -in_raw`` on a sell (8 of 8),
    ``delta == +out_raw`` on a buy (4 of 4). The remaining transaction matched on neither leg
    and is a routed fill, correctly left unattributed.

    **Exactness is still the point.** A magnitude tolerance would quietly admit a router's
    intermediate account, and PROGRAM.md §3 rule 7 is about exactly that kind of knob. So the
    rule stays equality on a leg, and any ambiguity — two owners matching, or none — returns
    ``None``. Unattributed is a true statement; a guessed wallet is not.
    """

    per_owner: dict[str, dict[str, int]] = {}
    for index in set(pre) | set(post):
        entry = post.get(index) or pre.get(index)
        if entry is None:
            continue
        owner = entry.get("owner")
        mint = entry.get("mint")
        if not isinstance(owner, str) or not isinstance(mint, str) or owner == pool:
            continue
        delta = _raw_amount(post.get(index)) - _raw_amount(pre.get(index))
        per_owner.setdefault(owner, {}).setdefault(mint, 0)
        per_owner[owner][mint] += delta
    matches = {
        owner
        for owner, deltas in per_owner.items()
        if deltas.get(in_mint, 0) == -in_raw or deltas.get(out_mint, 0) == out_raw
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _compute_units(meta: Mapping[str, Any]) -> int | None:
    value = meta.get("computeUnitsConsumed")
    return int(value) if isinstance(value, int) else None


def parse_transaction(
    tx: Mapping[str, Any] | None,
    spec: PoolSpec,
    *,
    signature: str,
    t_ingest: datetime,
    listing_block_time: int | None = None,
    confirmation_status: str | None = None,
    cursor: str | None = None,
) -> ClusterSwap | Defect:
    """Turn one transaction into a row, or into a defect. Never into a silently-wrong row."""

    ingest_iso = utc_iso(t_ingest)
    provenance = Provenance(source=SOURCE, fetched_at=ingest_iso, cursor=cursor)
    if tx is None:
        return Defect(
            reason=DefectReason.TX_MISSING,
            pool=spec.address,
            signature=signature,
            t_ingest=ingest_iso,
            detail="getTransaction returned no transaction for this signature",
        )

    meta = tx.get("meta")
    message = tx.get("transaction", {}).get("message")
    if not isinstance(meta, Mapping) or not isinstance(message, Mapping):
        return Defect(
            reason=DefectReason.MALFORMED,
            pool=spec.address,
            signature=signature,
            t_ingest=ingest_iso,
            detail="transaction has no meta or message",
        )

    slot_raw = tx.get("slot")
    slot = int(slot_raw) if isinstance(slot_raw, int) else None

    # RULE: the event clock is mandatory. SWARM.md Track B — a row without a block time has no
    # position on the chain clock, and joining it against anything fabricates a latency.
    block_time = tx.get("blockTime")
    if block_time is None:
        block_time = listing_block_time
    if not isinstance(block_time, int) or block_time <= 0:
        return Defect(
            reason=DefectReason.NO_BLOCK_TIME,
            pool=spec.address,
            signature=signature,
            slot=slot,
            t_ingest=ingest_iso,
            detail="neither getTransaction nor the signature listing carried a blockTime",
        )
    if slot is None:
        return Defect(
            reason=DefectReason.MALFORMED,
            pool=spec.address,
            signature=signature,
            t_ingest=ingest_iso,
            t_event=unix_to_iso(block_time),
            detail="transaction has no slot",
        )

    keys = _account_keys(message)
    if not keys:
        return Defect(
            reason=DefectReason.MALFORMED,
            pool=spec.address,
            signature=signature,
            slot=slot,
            t_ingest=ingest_iso,
            t_event=unix_to_iso(block_time),
            detail="transaction has no account keys",
        )
    fee_payer = str(keys[0].get("pubkey", ""))
    signers = tuple(str(k["pubkey"]) for k in keys if k.get("signer") and k.get("pubkey"))

    pre = _token_balances(meta, "preTokenBalances")
    post = _token_balances(meta, "postTokenBalances")

    vaults: list[VaultState] = []
    for index in sorted(set(pre) | set(post)):
        entry = post.get(index) or pre.get(index)
        if entry is None or entry.get("owner") != spec.address:
            continue
        account = str(keys[index].get("pubkey", "")) if index < len(keys) else ""
        vaults.append(
            VaultState(
                account=account,
                mint=str(entry.get("mint", "")),
                decimals=_decimals(entry),
                pre_raw=_raw_amount(pre.get(index)),
                post_raw=_raw_amount(post.get(index)),
            )
        )

    mismatch = spec.mint_mismatch(frozenset(v.mint for v in vaults))
    if mismatch is not None:
        return Defect(
            reason=DefectReason.MINT_MISMATCH,
            pool=spec.address,
            signature=signature,
            slot=slot,
            t_ingest=ingest_iso,
            t_event=unix_to_iso(block_time),
            detail=mismatch,
        )

    reserves = PoolReserves(
        pool=spec.address,
        dex=spec.dex,
        vaults=tuple(vaults),
        replay_sufficient=spec.replay_sufficient_reserves,
        curve=_pool_swap_event(tx, spec),
    )

    inflows = [v for v in vaults if v.delta_raw > 0]
    outflows = [v for v in vaults if v.delta_raw < 0]
    discriminators, names = _pool_legs(tx, spec)
    token_in_mint: str | None
    token_out_mint: str | None

    if len(inflows) == 1 and len(outflows) == 1:
        row_kind = RowKind.SWAP
        in_vault, out_vault = inflows[0], outflows[0]
        token_in_mint, token_in_raw = in_vault.mint, in_vault.delta_raw
        token_out_mint, token_out_raw = out_vault.mint, -out_vault.delta_raw
        counterparty = _counterparty(
            pre,
            post,
            pool=spec.address,
            in_mint=token_in_mint,
            out_mint=token_out_mint,
            in_raw=token_in_raw,
            out_raw=token_out_raw,
        )
    elif inflows and outflows:
        # More than two vaults moving in opposite directions is not a shape either DEX
        # produces; refusing it is cheaper than inventing a direction for it.
        return Defect(
            reason=DefectReason.UNBALANCED_VAULTS,
            pool=spec.address,
            signature=signature,
            slot=slot,
            t_ingest=ingest_iso,
            t_event=unix_to_iso(block_time),
            detail=f"{len(inflows)} vaults in and {len(outflows)} out",
        )
    else:
        # Everything nonzero moved the same way (liquidity, fee claim) or nothing moved at
        # all (a router named the pool and traded elsewhere). Recorded, but never as flow.
        row_kind = RowKind.LIQUIDITY if (inflows or outflows) else RowKind.REFERENCE
        token_in_mint = token_out_mint = None
        token_in_raw = token_out_raw = 0
        counterparty = None

    counterparty_paid_fee = None if counterparty is None else counterparty == fee_payer

    return ClusterSwap(
        pool=spec.address,
        dex=spec.dex,
        label=spec.label,
        row_kind=row_kind,
        chain=Chainstamp(slot=slot, signature=signature, block_time=block_time),
        t_event=unix_to_iso(block_time),
        t_ingest=ingest_iso,
        confirmation_status=confirmation_status,
        fee_payer=fee_payer,
        signers=signers,
        counterparty=counterparty,
        counterparty_paid_fee=counterparty_paid_fee,
        fee_lamports=int(meta.get("fee", 0) or 0),
        token_in_mint=token_in_mint,
        token_in_raw=token_in_raw,
        token_out_mint=token_out_mint,
        token_out_raw=token_out_raw,
        reserves=reserves,
        swap_legs=len(discriminators),
        leg_discriminators=discriminators,
        leg_names=names,
        compute_units=_compute_units(meta),
        provenance=provenance,
    )


def parse_failed_signature(
    entry: Mapping[str, Any],
    spec: PoolSpec,
    *,
    t_ingest: datetime,
    cursor: str | None = None,
) -> Attempt | Defect:
    """Build an :class:`Attempt` from a signature-listing entry, with no ``getTransaction``."""

    ingest_iso = utc_iso(t_ingest)
    signature = str(entry.get("signature", ""))
    slot_raw = entry.get("slot")
    slot = int(slot_raw) if isinstance(slot_raw, int) else None
    block_time = entry.get("blockTime")
    if not isinstance(block_time, int) or block_time <= 0 or slot is None:
        return Defect(
            reason=DefectReason.NO_BLOCK_TIME,
            pool=spec.address,
            signature=signature,
            slot=slot,
            t_ingest=ingest_iso,
            detail="signature listing carried no blockTime or no slot",
        )
    return Attempt(
        pool=spec.address,
        dex=spec.dex,
        label=spec.label,
        chain=Chainstamp(slot=slot, signature=signature, block_time=block_time),
        t_event=unix_to_iso(block_time),
        t_ingest=ingest_iso,
        confirmation_status=entry.get("confirmationStatus"),
        error=str(entry.get("err")),
        provenance=Provenance(source=SOURCE, fetched_at=ingest_iso, cursor=cursor),
    )


def listing_is_usable(entry: Mapping[str, Any]) -> bool:
    """A listing entry with no block time or no signature can never become a tape row."""

    return (
        isinstance(entry.get("blockTime"), int)
        and int(entry.get("blockTime") or 0) > 0
        and isinstance(entry.get("signature"), str)
        and isinstance(entry.get("slot"), int)
    )


def sort_listing(entries: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Oldest first, so a cursor only ever moves forward."""

    return sorted(entries, key=lambda e: (int(e.get("slot") or 0), str(e.get("signature") or "")))
