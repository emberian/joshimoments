"""Lot generations: a flat bag is a new coin next time it appears.

Runtime trail/dispose state is keyed by mint. If we keep it across a sell,
a rebuy inherits the old peak and can EXIT_TRAIL immediately. This module
is the only place that decides when a mint's lot dies and when a new bag
is due for the delayed default rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from .domain import PositionState, utc_now

# -10 was a scalp against a just-stamped Jupiter quote: first wick sold
# the bag and the coin then swung. Default SL is a death floor. Rug
# still handles actual death. Runner handles the upside.
DEFAULT_NEW_BAG_STOP_LOSS_PCT = Decimal("-35")
DEFAULT_NEW_BAG_TAKE_PROFIT_PCT = Decimal("80")
DEFAULT_NEW_BAG_TRAILING_STOP_PCT = Decimal("20")
DEFAULT_NEW_BAG_PROTECT_DELAY_SECONDS = 600
# Grace before an auto-protect stop goes live. The original reason was that basis was
# invented from the current quote, so a stop against that number had to be held off; that
# fabrication is gone and basis is now reconstructed from observed on-chain buys. The grace
# is kept for a different and still-valid reason: basis reconstruction is an RPC round trip
# that can fail transiently, and a stop must not fire on the first poll after a bag appears
# while its basis is still unresolved.
DEFAULT_NEW_BAG_SL_GRACE_SECONDS = 600
ORIGIN_OPERATOR = "operator"
ORIGIN_DEFAULT = "default"


@dataclass(frozen=True, slots=True)
class LotRecord:
    mint: str
    generation: int
    opened_at: str | None
    flat_since: str | None
    auto_protect_after: str | None
    auto_protect_skipped: bool
    origin: str | None
    needs_basis: bool = False
    sl_live_after: str | None = None

    @property
    def is_flat(self) -> bool:
        return self.flat_since is not None


def empty_runtime_state() -> PositionState:
    return PositionState()


def record_from_mapping(mint: str, raw: Any) -> LotRecord:
    data = raw if isinstance(raw, dict) else {}
    generation = data.get("generation", 0)
    try:
        generation_int = int(generation)
    except (TypeError, ValueError):
        generation_int = 0
    origin = data.get("origin")
    return LotRecord(
        mint=mint,
        generation=max(generation_int, 0),
        opened_at=_iso(data.get("opened_at")),
        flat_since=_iso(data.get("flat_since")),
        auto_protect_after=_iso(data.get("auto_protect_after")),
        auto_protect_skipped=bool(data.get("auto_protect_skipped", False)),
        origin=origin if origin in {ORIGIN_OPERATOR, ORIGIN_DEFAULT} else None,
        needs_basis=bool(data.get("needs_basis", False)),
        sl_live_after=_iso(data.get("sl_live_after")),
    )


def retire(record: LotRecord, *, now: datetime | None = None) -> LotRecord:
    """Bag went to zero. Kill trail inheritance. Default rules do not survive."""

    stamp = _stamp(now)
    origin = record.origin if record.origin == ORIGIN_OPERATOR else None
    return LotRecord(
        mint=record.mint,
        generation=record.generation,
        opened_at=None,
        flat_since=stamp,
        auto_protect_after=None,
        auto_protect_skipped=False,
        origin=origin,
        # Operator (or legacy unstamped) YAML keeps SL/TP; the lot's cash basis dies.
        needs_basis=origin == ORIGIN_OPERATOR or record.origin is None,
        sl_live_after=None,
    )


def note_seen(
    record: LotRecord | None,
    mint: str,
    *,
    delay_seconds: float = DEFAULT_NEW_BAG_PROTECT_DELAY_SECONDS,
    now: datetime | None = None,
) -> tuple[LotRecord, bool]:
    """A nonzero unmonitored holding is visible.

    Returns (record, newly_scheduled). A rebuy after flat is a new generation
    and gets a fresh delay. An operator policy that still exists is not this path.
    """

    observed = now or utc_now()
    stamp = observed.isoformat()
    if record is None or record.is_flat or _is_unscheduled_ghost(record):
        generation = 1 if record is None else max(record.generation, 0) + 1
        after = _plus_seconds(observed, delay_seconds)
        return (
            LotRecord(
                mint=mint,
                generation=generation,
                opened_at=stamp,
                flat_since=None,
                auto_protect_after=after,
                auto_protect_skipped=False,
                origin=None,
                needs_basis=False,
                sl_live_after=None,
            ),
            True,
        )
    return record, False


def reopen_held(record: LotRecord, *, now: datetime | None = None) -> LotRecord:
    """A configured mint is nonzero again after being flat. New lot, need a new basis."""

    if not record.is_flat:
        return record
    stamp = _stamp(now)
    return LotRecord(
        mint=record.mint,
        generation=record.generation + 1,
        opened_at=stamp,
        flat_since=None,
        auto_protect_after=None,
        auto_protect_skipped=True,
        origin=record.origin,
        needs_basis=True,
        sl_live_after=None,
    )


def basis_applied(record: LotRecord) -> LotRecord:
    return LotRecord(
        mint=record.mint,
        generation=record.generation,
        opened_at=record.opened_at,
        flat_since=record.flat_since,
        auto_protect_after=record.auto_protect_after,
        auto_protect_skipped=record.auto_protect_skipped,
        origin=record.origin,
        needs_basis=False,
        sl_live_after=record.sl_live_after,
    )


def due_for_default(record: LotRecord | None, *, now: datetime | None = None) -> bool:
    if record is None or record.auto_protect_skipped or record.origin is not None:
        return False
    if record.auto_protect_after is None:
        return False
    try:
        deadline = datetime.fromisoformat(record.auto_protect_after)
    except ValueError:
        return False
    return (now or utc_now()) >= deadline


def mark_origin(
    record: LotRecord,
    origin: str,
    *,
    now: datetime | None = None,
    sl_grace_seconds: float | None = None,
) -> LotRecord:
    if origin not in {ORIGIN_OPERATOR, ORIGIN_DEFAULT}:
        raise ValueError("lot origin must be operator or default")
    observed = now or utc_now()
    if origin == ORIGIN_DEFAULT:
        grace = (
            DEFAULT_NEW_BAG_SL_GRACE_SECONDS
            if sl_grace_seconds is None
            else sl_grace_seconds
        )
        sl_live_after = _plus_seconds(observed, grace) if grace > 0 else None
    else:
        sl_live_after = None
    return LotRecord(
        mint=record.mint,
        generation=max(record.generation, 1),
        opened_at=record.opened_at,
        flat_since=None,
        auto_protect_after=record.auto_protect_after,
        auto_protect_skipped=origin == ORIGIN_OPERATOR or record.auto_protect_skipped,
        origin=origin,
        needs_basis=record.needs_basis,
        sl_live_after=sl_live_after,
    )


def skip_auto(record: LotRecord) -> LotRecord:
    return LotRecord(
        mint=record.mint,
        generation=record.generation,
        opened_at=record.opened_at,
        flat_since=record.flat_since,
        auto_protect_after=record.auto_protect_after,
        auto_protect_skipped=True,
        origin=record.origin,
        needs_basis=record.needs_basis,
        sl_live_after=record.sl_live_after,
    )


def to_mapping(record: LotRecord) -> dict[str, Any]:
    return {
        "generation": record.generation,
        "opened_at": record.opened_at,
        "flat_since": record.flat_since,
        "auto_protect_after": record.auto_protect_after,
        "auto_protect_skipped": record.auto_protect_skipped,
        "origin": record.origin,
        "needs_basis": record.needs_basis,
        "sl_live_after": record.sl_live_after,
    }


def sl_is_live(record: LotRecord | None, *, now: datetime | None = None) -> bool:
    """Operator SL is live immediately. Default SL waits out the post-stamp grace."""

    if record is None or record.sl_live_after is None:
        return True
    try:
        deadline = datetime.fromisoformat(record.sl_live_after)
    except ValueError:
        return False
    return (now or utc_now()) >= deadline


def _is_unscheduled_ghost(record: LotRecord) -> bool:
    """Empty lot rows (gen 0, no clock) must not block the 10m default."""

    return (
        record.origin is None
        and not record.auto_protect_skipped
        and record.auto_protect_after is None
        and record.opened_at is None
    )


def _iso(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return None
    return value


def _stamp(now: datetime | None) -> str:
    return (now or utc_now()).isoformat()


def _plus_seconds(now: datetime, seconds: float) -> str:
    from datetime import timedelta

    return (now + timedelta(seconds=max(0, float(seconds)))).isoformat()
