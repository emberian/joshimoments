"""The PumpSwap swap event, decoded — because the vault balance is NOT the curve reserve.

WHAT THIS FIXES
---------------
``pools.py`` asserted ``replay_sufficient_reserves=True`` for every PumpSwap pool, meaning
"the fill is an exact function of the two vault balances". That is false, and two independent
studies measured the falseness before anyone found the mechanism:

- ``studies/RESULT_copytrading.md`` §9(b) inverted the constant product on each pool's own
  fills and got an implied ``g = 1 - fee`` **above 1** on nosis/SOL and weave/SOL — impossible
  for a real curve — while DREGG/SOL and SOLVE/SOL returned exactly 0.998. Fitting a token-side
  haircut reconciled it at 4.8% and 8.8%, agreeing to 0.03pp and 0.35pp between buys and sells.
- ``studies/RESULT_circuit_model.md`` §7.3 saw the same two pools sitting at a persistent
  multiplicative offset against DexScreener, -493 bps and -896 bps, and guessed "unclaimed fee
  balances sitting in the pool token accounts".

Both hypotheses were wrong, and so was the shape. The offset is not a token-side percentage
and not an accumulation: it is a **constant additive quantity on the QUOTE leg**, and it is
carried in the swap event as its own field. Decoded from chain on 2026-08-15:

===========  ==================  ==================  =========  ===========
pool         pool_quote (event)  virtual_quote       can_boost  creator bps
===========  ==================  ==================  =========  ===========
nosis/SOL    == our vault, exact     17,584,505,383  True       85
weave/SOL    == our vault, exact     17,584,505,468  True       90
DREGG/SOL    == our vault, exact                  0  False      75
SOLVE/SOL    == our vault, exact                  0  False      95
===========  ==================  ==================  =========  ===========

So: **the discriminator is pump.fun's "boost" feature.** A boosted pool prices against
``pool_quote_token_reserves + virtual_quote_reserves``; an unboosted one has
``virtual_quote_reserves == 0`` and its vault *is* its curve, which is why DREGG and SOLVE
fitted to exactly zero. 17.58 SOL against nosis's ~382 SOL vault is 4.6% and against weave's
~183 SOL vault is 9.6% — the two fitted percentages were one number seen through two pool
sizes.

Note also that ``pool_quote_token_reserves`` in the event equalled the recorded vault balance
to the digit on all 12 sampled fills, so the parser's vault reading was never the problem.

WHY THIS IS DECODED PER TRANSACTION AND NOT TABULATED
-----------------------------------------------------
The obvious cheap repair is a per-pool constant. It would be wrong. The virtual reserve is not
a property of the pool — nosis and weave carry values 85 lamports apart, and nosis's own value
moved ~1.48M lamports over a single day against the earlier fitted estimate. A hard-coded
17.5845 would be a number that silently rots, which is the failure mode this tape exists to
avoid. The event carries the exact value on every fill for free, inside a transaction the
recorder already fetched, so it is read rather than assumed.

The layouts are transcribed from the pump_amm IDL. ``shitcoims_intelligence/pump_layouts.py``
carries the same table, and is deliberately **not imported**: this package must not depend on
the intelligence daemon, the same rule ``rpc.py`` follows for the sentinel's ``secrets.py``.
The cost is one duplicated table; the alternative is a research collector that cannot run
without a daemon it has nothing to do with.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Final

#: Anchor's self-CPI event wrapper. Every emitted event is an inner instruction to the
#: program whose data begins with this tag, then the 8-byte event discriminator, then borsh.
ANCHOR_CPI_EVENT_TAG: Final[bytes] = bytes.fromhex("e445a52e51cb9a1d")

BUY_EVENT: Final[bytes] = bytes((103, 244, 82, 31, 44, 245, 119, 119))
SELL_EVENT: Final[bytes] = bytes((62, 47, 55, 10, 165, 3, 220, 42))

_Field = tuple[str, str]

#: Only the prefix up to the fields this module reports is transcribed for each event; the
#: layouts agree field-for-field until they diverge at the amount name, and the tail after
#: ``virtual_quote_reserves`` is not needed. Every field IS listed rather than seeking by
#: offset, because an offset constant is a number that cannot be checked against the IDL.
_BUY_FIELDS: Final[tuple[_Field, ...]] = (
    ("timestamp", "i64"),
    ("base_amount_out", "u64"),
    ("max_quote_amount_in", "u64"),
    ("user_base_token_reserves", "u64"),
    ("user_quote_token_reserves", "u64"),
    ("pool_base_token_reserves", "u64"),
    ("pool_quote_token_reserves", "u64"),
    ("quote_amount_in", "u64"),
    ("lp_fee_basis_points", "u64"),
    ("lp_fee", "u64"),
    ("protocol_fee_basis_points", "u64"),
    ("protocol_fee", "u64"),
    ("quote_amount_in_with_lp_fee", "u64"),
    ("user_quote_amount_in", "u64"),
    ("pool", "pubkey"),
    ("user", "pubkey"),
    ("user_base_token_account", "pubkey"),
    ("user_quote_token_account", "pubkey"),
    ("protocol_fee_recipient", "pubkey"),
    ("protocol_fee_recipient_token_account", "pubkey"),
    ("coin_creator", "pubkey"),
    ("coin_creator_fee_basis_points", "u64"),
    ("coin_creator_fee", "u64"),
    ("track_volume", "bool"),
    ("total_unclaimed_tokens", "u64"),
    ("total_claimed_tokens", "u64"),
    ("current_sol_volume", "u64"),
    ("last_update_timestamp", "i64"),
    ("min_base_amount_out", "u64"),
    ("ix_name", "string"),
    ("cashback_fee_basis_points", "u64"),
    ("cashback", "u64"),
    ("buyback_fee_basis_points", "u64"),
    ("buyback_fee", "u64"),
    ("virtual_quote_reserves", "i128"),
    ("can_boost", "bool"),
)
_SELL_FIELDS: Final[tuple[_Field, ...]] = (
    ("timestamp", "i64"),
    ("base_amount_in", "u64"),
    ("min_quote_amount_out", "u64"),
    ("user_base_token_reserves", "u64"),
    ("user_quote_token_reserves", "u64"),
    ("pool_base_token_reserves", "u64"),
    ("pool_quote_token_reserves", "u64"),
    ("quote_amount_out", "u64"),
    ("lp_fee_basis_points", "u64"),
    ("lp_fee", "u64"),
    ("protocol_fee_basis_points", "u64"),
    ("protocol_fee", "u64"),
    ("quote_amount_out_without_lp_fee", "u64"),
    ("user_quote_amount_out", "u64"),
    ("pool", "pubkey"),
    ("user", "pubkey"),
    ("user_base_token_account", "pubkey"),
    ("user_quote_token_account", "pubkey"),
    ("protocol_fee_recipient", "pubkey"),
    ("protocol_fee_recipient_token_account", "pubkey"),
    ("coin_creator", "pubkey"),
    ("coin_creator_fee_basis_points", "u64"),
    ("coin_creator_fee", "u64"),
    ("cashback_fee_basis_points", "u64"),
    ("cashback", "u64"),
    ("buyback_fee_basis_points", "u64"),
    ("buyback_fee", "u64"),
    ("virtual_quote_reserves", "i128"),
    ("can_boost", "bool"),
)

_SIZES: Final[dict[str, int]] = {"i64": 8, "u64": 8, "i128": 16, "pubkey": 32, "bool": 1}

_B58_ALPHABET: Final[str] = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58_encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    out: list[str] = []
    while number:
        number, remainder = divmod(number, 58)
        out.append(_B58_ALPHABET[remainder])
    for byte in raw:
        if byte:
            break
        out.append(_B58_ALPHABET[0])
    return "".join(reversed(out)) or _B58_ALPHABET[0]


class EventDecodeError(ValueError):
    """The bytes were not a decodable event. Callers route this to a defect, never a guess."""


@dataclass(frozen=True, slots=True)
class SwapEvent:
    """The reserves and fee schedule the PROGRAM used, as the program reported them."""

    side: str
    pool: str
    pool_base_raw: int
    pool_quote_raw: int
    #: The quote-side reserve the curve prices against but the vault does not hold. Zero on an
    #: unboosted pool, in which case the vault balance IS the curve reserve.
    virtual_quote_raw: int
    can_boost: bool
    lp_fee_bps: int
    protocol_fee_bps: int
    coin_creator_fee_bps: int

    @property
    def curve_quote_raw(self) -> int:
        """What ``x * y = k`` actually uses on the quote leg."""

        return self.pool_quote_raw + self.virtual_quote_raw

    def to_json(self) -> dict[str, Any]:
        return {
            "source": "pumpswap_event",
            "side": self.side,
            "pool_base_raw": str(self.pool_base_raw),
            "pool_quote_raw": str(self.pool_quote_raw),
            "virtual_quote_raw": str(self.virtual_quote_raw),
            "curve_quote_raw": str(self.curve_quote_raw),
            "can_boost": self.can_boost,
            "lp_fee_bps": self.lp_fee_bps,
            "protocol_fee_bps": self.protocol_fee_bps,
            "coin_creator_fee_bps": self.coin_creator_fee_bps,
        }


def _read(body: bytes, fields: tuple[_Field, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    offset = 0
    for name, kind in fields:
        if kind == "string":
            if offset + 4 > len(body):
                raise EventDecodeError(f"event truncated before {name}")
            (length,) = struct.unpack_from("<I", body, offset)
            offset += 4
            if offset + length > len(body):
                raise EventDecodeError(f"event truncated inside {name}")
            out[name] = body[offset : offset + length].decode("utf-8", "replace")
            offset += length
            continue
        size = _SIZES[kind]
        if offset + size > len(body):
            raise EventDecodeError(f"event truncated before {name}")
        raw = body[offset : offset + size]
        offset += size
        if kind == "pubkey":
            out[name] = _b58_encode(raw)
        elif kind == "bool":
            out[name] = bool(raw[0])
        else:
            out[name] = int.from_bytes(raw, "little", signed=kind.startswith("i"))
    return out


def decode_swap_event(raw: bytes) -> SwapEvent | None:
    """Decode one inner-instruction payload, or return ``None`` if it is not a swap event.

    ``None`` means "not this kind of thing" — most inner instructions are token transfers.
    :class:`EventDecodeError` means "this WAS a swap event and it did not parse", which is a
    real defect and must not be swallowed into the same silence.
    """

    if not raw.startswith(ANCHOR_CPI_EVENT_TAG):
        return None
    discriminator, body = raw[8:16], raw[16:]
    if discriminator == BUY_EVENT:
        side, fields = "buy", _BUY_FIELDS
    elif discriminator == SELL_EVENT:
        side, fields = "sell", _SELL_FIELDS
    else:
        return None
    decoded = _read(body, fields)
    return SwapEvent(
        side=side,
        pool=str(decoded["pool"]),
        pool_base_raw=int(decoded["pool_base_token_reserves"]),
        pool_quote_raw=int(decoded["pool_quote_token_reserves"]),
        virtual_quote_raw=int(decoded["virtual_quote_reserves"]),
        can_boost=bool(decoded["can_boost"]),
        lp_fee_bps=int(decoded["lp_fee_basis_points"]),
        protocol_fee_bps=int(decoded["protocol_fee_basis_points"]),
        coin_creator_fee_bps=int(decoded["coin_creator_fee_basis_points"]),
    )
