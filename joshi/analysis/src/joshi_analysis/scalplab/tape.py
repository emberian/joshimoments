"""One loader, two tape kinds, one canonical event frame.

Both recorder outputs — the ``coin_tape_live`` socket catalogs (PumpPortal frames) and the
``joshi-pump-product-read`` polled catalogs (pump.fun trades pages) — land in the same catalog
schema: ``observation`` rows pointing at ``blob`` payloads. This module reads a catalog
strictly read-only (sqlite ``mode=ro``), decodes the payloads it recognises, and emits
per-coin, time-ordered, deduplicated :class:`TapeEvent` lists with exact ``Decimal`` prices,
under a :class:`TapeProvenance` that states — per tape — which decision clock is honest.

Nothing is interpolated. Coverage gaps are carried from the catalog's own ``coverage_gap``
table; poll pages that were full and shared no row with anything previously seen are counted
as *possible* unobserved trades and never bridged.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from itertools import pairwise
from pathlib import Path

from .vocabulary import DEFAULT_VENUE_FLOOR_BPS

SOCKET_SOURCE = "pumpportal.websocket.data.v1"
POLLED_SOURCE = "pump.api.product.v1"

SOURCE_KIND_SOCKET = "pumpportal_socket"
SOURCE_KIND_POLLED = "pump_api_polled"

ARRIVAL_SOCKET = "socket_arrival"
ARRIVAL_POLL = "poll_receipt"
ARRIVAL_NONE = "retrospective_none"

_PRICE_PRECISION = 50
_SLOT_DIGITS = 12


class TapeError(Exception):
    """A tape this loader refuses to misread."""


@dataclass(frozen=True)
class TapeEvent:
    """One trade the venue printed, as one tape retained it."""

    ordinal: int  # index in the deduplicated per-coin tape; the tape's only order
    mint: str
    side: str  # "buy" | "sell" (taker side)
    price: Decimal  # marginal post-trade pool price, SOL per token
    fill_price: Decimal | None  # the trade's own average fill, where derivable
    base_signed: Decimal  # token amount, positive when the taker bought base
    quote_signed: Decimal  # SOL amount, positive when SOL entered the pool
    trader: str
    venue: str  # pool/program tag verbatim from the tape
    tx: str
    slot: int | None  # known for polled tapes only
    event_time_us: int | None  # venue-stated event time (1 s precision on polled tapes)
    arrival_wall_us: int | None  # when a live process could first have seen it


@dataclass(frozen=True)
class CoverageGap:
    cause_code: str
    severity: str
    lower_us: int | None
    upper_us: int | None


@dataclass(frozen=True)
class TapeProvenance:
    """What this tape is, what it failed to see, and which clock a policy may claim."""

    tape_path: str
    source_kind: str
    source_id: str
    n_observations: int
    n_events: int
    coins: tuple[tuple[str, int], ...]  # (mint, n_events), descending by count
    coverage_gaps: tuple[CoverageGap, ...]
    full_pages_without_overlap: int  # possible unobserved trades between polls; 0 for socket
    arrival_clock: str  # ARRIVAL_SOCKET | ARRIVAL_POLL | ARRIVAL_NONE
    arrival_floor_us: int | None  # 0-ish for socket, median poll gap for polled, None if none
    decision_clock_statement: str
    venue_floor_bps: int

    def as_dict(self) -> dict:
        return {
            "tapePath": self.tape_path,
            "sourceKind": self.source_kind,
            "sourceId": self.source_id,
            "nObservations": self.n_observations,
            "nEvents": self.n_events,
            "coins": [{"mint": mint, "nEvents": n} for mint, n in self.coins],
            "coverageGaps": [
                {
                    "causeCode": gap.cause_code,
                    "severity": gap.severity,
                    "lowerUs": gap.lower_us,
                    "upperUs": gap.upper_us,
                }
                for gap in self.coverage_gaps
            ],
            "fullPagesWithoutOverlap": self.full_pages_without_overlap,
            "arrivalClock": self.arrival_clock,
            "arrivalFloorUs": self.arrival_floor_us,
            "decisionClockStatement": self.decision_clock_statement,
            "venueFloorBps": self.venue_floor_bps,
        }


@dataclass(frozen=True)
class LoadedTape:
    provenance: TapeProvenance
    events_by_coin: dict[str, list[TapeEvent]]


def load_tape(tape_dir: str | Path, venue_floor_bps: int = DEFAULT_VENUE_FLOOR_BPS) -> LoadedTape:
    """Load one catalog directory, sniffing the tape kind from its ``source`` table."""
    tape_dir = Path(tape_dir)
    catalog = tape_dir / "catalog.sqlite"
    if not catalog.exists():
        raise TapeError(f"no catalog.sqlite under {tape_dir}")
    db = sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        sources = [row["source_id"] for row in db.execute("SELECT source_id FROM source")]
        if SOCKET_SOURCE in sources:
            return _load_socket(db, tape_dir, SOCKET_SOURCE, venue_floor_bps)
        if POLLED_SOURCE in sources:
            return _load_polled(db, tape_dir, POLLED_SOURCE, venue_floor_bps)
        raise TapeError(f"{tape_dir}: no recognised source among {sources}")
    finally:
        db.close()


# --- shared blob plumbing -----------------------------------------------------------------------


def _blob_bytes(tape_dir: Path, row: sqlite3.Row) -> bytes:
    if row["compression"] != "identity":
        raise TapeError(
            f"blob compression {row['compression']!r} is not readable in the locked env"
        )
    if row["storage_mode"] == "inline":
        data = row["inline_bytes"]
        return data if isinstance(data, bytes) else str(data).encode()
    return (tape_dir / "blobs" / row["relative_path"]).read_bytes()


def _coverage_gaps(db: sqlite3.Connection) -> tuple[CoverageGap, ...]:
    rows = db.execute(
        "SELECT cause_code, severity, event_lower_us, event_upper_us FROM coverage_gap"
        " ORDER BY detected_commit_seq"
    )
    return tuple(
        CoverageGap(
            cause_code=row["cause_code"],
            severity=row["severity"],
            lower_us=row["event_lower_us"],
            upper_us=row["event_upper_us"],
        )
        for row in rows
    )


def _finish(
    tape_dir: Path,
    source_kind: str,
    source_id: str,
    n_observations: int,
    events_by_coin: dict[str, list[TapeEvent]],
    gaps: tuple[CoverageGap, ...],
    full_pages: int,
    arrival_clock: str,
    arrival_floor_us: int | None,
    statement: str,
    venue_floor_bps: int,
) -> LoadedTape:
    coins = tuple(
        sorted(
            ((mint, len(events)) for mint, events in events_by_coin.items()),
            key=lambda item: (-item[1], item[0]),
        )
    )
    provenance = TapeProvenance(
        tape_path=str(tape_dir),
        source_kind=source_kind,
        source_id=source_id,
        n_observations=n_observations,
        n_events=sum(n for _, n in coins),
        coins=coins,
        coverage_gaps=gaps,
        full_pages_without_overlap=full_pages,
        arrival_clock=arrival_clock,
        arrival_floor_us=arrival_floor_us,
        decision_clock_statement=statement,
        venue_floor_bps=venue_floor_bps,
    )
    return LoadedTape(provenance=provenance, events_by_coin=events_by_coin)


# --- socket tapes -------------------------------------------------------------------------------


def _load_socket(
    db: sqlite3.Connection, tape_dir: Path, source_id: str, venue_floor_bps: int
) -> LoadedTape:
    rows = db.execute(
        "SELECT o.received_wall_us, b.storage_mode, b.compression, b.inline_bytes,"
        " b.relative_path FROM observation o JOIN blob b ON b.blob_id = o.blob_id"
        " WHERE o.observation_kind = 'frame' ORDER BY o.commit_seq, o.intra_commit_seq"
    ).fetchall()
    seen_tx: set[str] = set()
    events_by_coin: dict[str, list[TapeEvent]] = {}
    for row in rows:
        envelope = json.loads(_blob_bytes(tape_dir, row))
        try:
            body = bytes(envelope["body"]).decode("utf-8")
            frame = json.loads(body, parse_float=Decimal)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError):
            continue  # control frames, provider prose; counted via n_observations vs n_events
        if not isinstance(frame, dict) or frame.get("txType") not in ("buy", "sell"):
            continue
        tx = str(frame.get("signature", ""))
        mint = str(frame.get("mint", ""))
        tokens_in_pool = _as_decimal(frame.get("tokensInPool"))
        sol_in_pool = _as_decimal(frame.get("solInPool"))
        if not tx or not mint or tokens_in_pool is None or sol_in_pool is None:
            continue
        if tokens_in_pool <= 0 or tx in seen_tx:
            continue
        seen_tx.add(tx)
        side = frame["txType"]
        token_amount = _as_decimal(frame.get("tokenAmount")) or Decimal(0)
        sol_amount = _as_decimal(frame.get("solAmount")) or Decimal(0)
        sign = Decimal(1) if side == "buy" else Decimal(-1)
        with localcontext() as ctx:
            ctx.prec = _PRICE_PRECISION
            price = sol_in_pool / tokens_in_pool
            fill_price = sol_amount / token_amount if token_amount > 0 else None
        bucket = events_by_coin.setdefault(mint, [])
        bucket.append(
            TapeEvent(
                ordinal=len(bucket),
                mint=mint,
                side=side,
                price=price,
                fill_price=fill_price,
                base_signed=sign * token_amount,
                quote_signed=sign * sol_amount,
                trader=str(frame.get("traderPublicKey", "")),
                venue=str(frame.get("pool", "")),
                tx=tx,
                slot=None,
                event_time_us=None,
                arrival_wall_us=row["received_wall_us"],
            )
        )
    statement = (
        "socket arrival clock (received_wall_us); sub-second delivery, floor treated as 0. A "
        "live decision at event i sees exactly the events with arrival <= its own."
    )
    return _finish(
        tape_dir,
        SOURCE_KIND_SOCKET,
        source_id,
        len(rows),
        events_by_coin,
        _coverage_gaps(db),
        full_pages=0,
        arrival_clock=ARRIVAL_SOCKET,
        arrival_floor_us=0,
        statement=statement,
        venue_floor_bps=venue_floor_bps,
    )


# --- polled tapes -------------------------------------------------------------------------------


def _load_polled(
    db: sqlite3.Connection, tape_dir: Path, source_id: str, venue_floor_bps: int
) -> LoadedTape:
    mints_by_acq = _polled_mints(db, tape_dir)
    body_rows = db.execute(
        "SELECT o.acquisition_id, o.received_wall_us, b.storage_mode, b.compression,"
        " b.inline_bytes, b.relative_path FROM observation o"
        " JOIN blob b ON b.blob_id = o.blob_id"
        " WHERE o.parse_disposition = 'decoded' AND b.content_type LIKE 'application/json%'"
        " ORDER BY o.received_wall_us, o.commit_seq, o.intra_commit_seq"
    ).fetchall()
    n_observations = db.execute("SELECT count(*) FROM observation").fetchone()[0]
    seen: set[tuple[str, str]] = set()
    raw: list[tuple[str, dict, int]] = []  # (mint, trade row, arrival_wall_us)
    poll_receipts: list[int] = []
    full_pages = 0
    for row in body_rows:
        mint = mints_by_acq.get(row["acquisition_id"])
        if mint is None:
            continue
        page = json.loads(_blob_bytes(tape_dir, row).decode("utf-8"), parse_float=Decimal)
        trades = page.get("trades", [])
        poll_receipts.append(row["received_wall_us"])
        keys = {(str(t.get("slotIndexId", "")), str(t.get("tx", ""))) for t in trades}
        if seen and len(trades) >= 100 and not (keys & seen):
            full_pages += 1
        for trade in trades:
            key = (str(trade.get("slotIndexId", "")), str(trade.get("tx", "")))
            if key in seen or not key[0] or not key[1]:
                continue
            seen.add(key)
            raw.append((mint, trade, row["received_wall_us"]))
    events_by_coin: dict[str, list[TapeEvent]] = {}
    raw.sort(key=lambda item: (item[0], item[1]["slotIndexId"], item[1]["tx"]))
    event_times: list[int] = []
    for mint, trade, arrival in raw:
        event = _polled_event(mint, trade, arrival, len(events_by_coin.get(mint, [])))
        if event is None:
            continue
        events_by_coin.setdefault(mint, []).append(event)
        if event.event_time_us is not None:
            event_times.append(event.event_time_us)
    arrival_clock, floor_us, statement = _polled_clock(poll_receipts, event_times)
    return _finish(
        tape_dir,
        SOURCE_KIND_POLLED,
        source_id,
        n_observations,
        events_by_coin,
        _coverage_gaps(db),
        full_pages=full_pages,
        arrival_clock=arrival_clock,
        arrival_floor_us=floor_us,
        statement=statement,
        venue_floor_bps=venue_floor_bps,
    )


def _polled_mints(db: sqlite3.Connection, tape_dir: Path) -> dict[str, str]:
    rows = db.execute(
        "SELECT o.acquisition_id, b.storage_mode, b.compression, b.inline_bytes,"
        " b.relative_path FROM observation o JOIN blob b ON b.blob_id = o.blob_id"
        " WHERE b.content_type LIKE '%pump-api-acquisition%'"
    ).fetchall()
    out: dict[str, str] = {}
    for row in rows:
        envelope = json.loads(_blob_bytes(tape_dir, row))
        mint = envelope.get("resolvedPublicPath", {}).get("mint")
        if mint:
            out[row["acquisition_id"]] = str(mint)
    return out


def _polled_event(mint: str, trade: dict, arrival: int, ordinal: int) -> TapeEvent | None:
    side = trade.get("type")
    price = _as_decimal(trade.get("priceSol"))
    if side not in ("buy", "sell") or price is None or price <= 0:
        return None
    slot_index_id = str(trade["slotIndexId"])
    slot = int(slot_index_id[:_SLOT_DIGITS]) if len(slot_index_id) >= _SLOT_DIGITS else None
    base = _as_decimal(trade.get("baseAmount")) or Decimal(0)
    quote = _as_decimal(trade.get("quoteAmount")) or Decimal(0)
    sign = Decimal(1) if side == "buy" else Decimal(-1)
    timestamp = trade.get("timestamp")
    event_time_us = None
    if isinstance(timestamp, str):
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            event_time_us = int(parsed.astimezone(UTC).timestamp() * 1_000_000)
        except ValueError:
            event_time_us = None
    return TapeEvent(
        ordinal=ordinal,
        mint=mint,
        side=side,
        price=price,
        fill_price=_as_decimal(trade.get("fillPriceSol")),
        base_signed=sign * base,
        quote_signed=sign * quote,
        trader=str(trade.get("userAddress", "")),
        venue=str(trade.get("program", "")),
        tx=str(trade["tx"]),
        slot=slot,
        event_time_us=event_time_us,
        arrival_wall_us=arrival,
    )


def _polled_clock(
    poll_receipts: list[int], event_times: list[int]
) -> tuple[str, int | None, str]:
    if len(poll_receipts) >= 2 and len(event_times) >= 2:
        receipt_span = max(poll_receipts) - min(poll_receipts)
        event_span = max(event_times) - min(event_times)
        if event_span > 0 and receipt_span * 2 < event_span:
            return (
                ARRIVAL_NONE,
                None,
                "RETROSPECTIVE BACKFILL: the polls that retained these trades ran after the "
                "fact, so no live decision clock exists for this tape. Usable for label "
                "statistics; any policy claiming live execution on it alone is dishonest.",
            )
        gaps = [b - a for a, b in pairwise(sorted(poll_receipts)) if b > a]
        floor = int(statistics.median(gaps)) if gaps else None
        seconds = (floor or 0) / 1_000_000
        return (
            ARRIVAL_POLL,
            floor,
            f"venue timestamp (1 s precision) plus this tape's own poll floor "
            f"(~{seconds:.1f} s median between poll receipts); a live decision could not have "
            "acted before the retaining poll landed.",
        )
    return (
        ARRIVAL_NONE,
        None,
        "fewer than two polls or timestamps retained; no decision clock can be stated.",
    )


def _as_decimal(value: object) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value)
        except ArithmeticError:
            return None
    if isinstance(value, float):  # only if a parser let one through; exact literal is gone
        return Decimal(str(value))
    return None
