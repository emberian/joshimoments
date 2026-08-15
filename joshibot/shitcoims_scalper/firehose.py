"""Push-mode ingestion of pump.fun lifecycle events from the PumpPortal firehose.

Everything upstream of this module polls. Polling produced a board tape with 30-second
granularity — coarser than the thing being measured, since a token's first minute is where
the whole distribution lives — and, worse, a callout feed that stopped returning rows for
24 hours while every process stayed green, because a poller that gets an empty page and a
poller that is dead look identical from the outside. This module is the other shape: the
server pushes, so freshness is bounded by the network rather than by a sleep, and absence
is a *recorded* fact rather than the default state of the world.

Transport
---------
``wss://pumpportal.fun/api/data``. No key, no auth, no account. Subscribe by sending
``{"method": "subscribeNewToken"}`` / ``{"method": "subscribeMigration"}``; frames arrive as
JSON text.

The ``websockets`` package (17.0.1) is **not** declared in ``pyproject.toml`` — it is present
only as a transitive dependency of ``uvicorn[standard]``. That is a real footgun: dropping the
``standard`` extra would silently break ingestion. It is imported lazily in
:func:`_default_connector` so the tests never depend on it, but it belongs in ``[project]
dependencies`` and this module does not own that file.

**Measured 2026-08-14, 114 seconds on the live socket:** 54 ``create`` frames (~28/min,
median inter-arrival ~2.1s) and 2 ``migrate`` frames (~1/min). Zero drops, zero malformed
frames, one connection.

**``subscribeTokenTrade`` and ``subscribeAccountTrade`` are NOT free.** Both were sent with
valid ``keys`` and both came back with::

    {"message": "'subscribeTokenTrade' and 'subscribeAccountTrade' methods are only
                 available when connecting with an API key funded with at least 0.02 SOL."}

The subscription is *accepted* at the protocol level and then silently produces no data, which
is precisely the failure this module exists to make loud. So the two trade feeds are wired up
here but are dead without a funded key, and a rejection like that is recorded as a ``control``
row and logged at WARNING rather than being dropped on the floor.

Payload shapes actually observed
--------------------------------
``txType == "create"`` (15 keys, every frame identical in shape)::

    signature, mint, traderPublicKey, txType, initialBuy, solAmount, bondingCurveKey,
    vTokensInBondingCurve, vSolInBondingCurve, marketCapSol, name, symbol, uri,
    is_mayhem_mode, pool

``txType == "migrate"`` (4 keys)::

    signature, mint, txType, pool

Note ``pool`` is a *venue label*, not an address: ``"pump"`` on creates, ``"pump-amm"`` on
migrations. The bonding-curve account is ``bondingCurveKey``. Anything that treats ``pool`` as
a base58 account will fail validation, and should.

Two clocks, never mixed
-----------------------
Every row carries ``t_ingest`` — our clock, UTC, ISO8601 with microseconds, stamped the
instant the frame came off the socket. Every row also carries ``t_event`` and
``t_event_source``.

**No PumpPortal payload observed carries an event clock at all** — no ``timestamp``, no
``blockTime``, no ``slot``. So ``t_event`` is ``null`` and ``t_event_source`` says why, in
words, on every row. It is never backfilled from ``t_ingest``. A prior bug in this repo did
exactly that substitution and made 169 rows look timestamped when they were not; the
invariant that replaces it is mechanical and testable:

    ``t_event`` is non-null **iff** the vendor supplied a clock.

Locally generated rows (heartbeat, watch ledger, defects) get ``t_event: null`` with source
``local_row_has_no_vendor_clock``, so the invariant holds for every row in every file without
a reader needing to know which kinds are ours.

The practical consequence: **you cannot measure vendor latency from these files.** The gap
between block time and ``t_ingest`` is unobservable through PumpPortal. If that number is
needed, the Helius fallback below is the only way to get it.

Money is vendor float, and it is marked as such
-----------------------------------------------
PumpPortal sends *no* exact integer amounts. Every quantity is a decimal already rounded by
the vendor: ``initialBuy``, ``solAmount``, ``vTokensInBondingCurve``, ``vSolInBondingCurve``,
``marketCapSol`` — see :data:`VENDOR_FLOAT_FIELDS`. They are stored exactly as received and
**never** converted to lamports here, because multiplying a vendor-rounded float by 1e9 and
calling the result an integer manufactures nine digits of precision that were never on chain.
A row's floats are good for ranking and triage; they are not good for accounting. Anything
that touches money settles against on-chain amounts, not against this tape.

One trap worth naming, because it will bite a consumer rather than this module: **the JSON
type of a money field is not stable.** ``solAmount`` arrived as ``0.059259258`` on one frame
and as ``2`` — a bare JSON integer — on another, in the same minute of the same feed. So a
reader that does ``isinstance(value, float)`` will silently skip round-numbered trades, which
are exactly the large deliberate ones. These are vendor floats whatever JSON says they are.

Watch-window ledger
-------------------
Same discipline as :mod:`shitcoims_cluster.watch`, and it reuses that module's vocabulary
(:class:`shitcoims_tape.schema.WatchClose`, ``INFORMATIVE_CLOSES``) rather than inventing a
parallel one. It does **not** reuse ``WatchWindow`` itself: that type validates its subject as
a 32-byte base58 address, and the subject here is a subscription name, so the constraint would
not hold and stretching it would be a lie the type checker cannot catch.

Every connection opens a window (``watch_open``) and every connection ends one
(``watch_close``) with an explicit reason. The interval between a close and the next open is
emitted as its own ``gap`` row. Therefore a stretch of file with no events resolves
unambiguously:

* inside a window, with heartbeats → the market was quiet, and that zero is real data;
* between ``watch_close`` and ``watch_open`` → **we were not listening**, and a study must
  exclude the interval rather than zero-fill it;
* no heartbeat rows at all → the *process* was dead, which no in-band row can ever say.

Downtime that spans a restart is recorded identically: on startup the recorder reads the last
``watch_close`` already on disk (:func:`last_close_on_disk`) and emits a ``gap`` labelled
``process_not_running``. A day of blindness because nobody restarted the daemon is the same
blindness as a dropped socket, and it gets the same row.

Heartbeat and staleness
-----------------------
The intelligence daemon died on a DNS error and nobody noticed for a day, because nothing
screamed. A heartbeat row every :data:`DEFAULT_HEARTBEAT_SECONDS` is written whether or not
anything happened, so liveness has a positive signal instead of being inferred from data that
may legitimately be absent. If no *event* arrives for ``stale_after_seconds`` while the socket
is open, a ``stale`` row is written and the alarm logs at WARNING; it repeats on the same
interval for as long as the silence lasts, so a long outage leaves a trail rather than one
row, and ``stale_cleared`` records the total silent span when data resumes.

``busy_hours`` is the "hours the feed is normally busy" knob. It defaults to all 24 because
creation ran at ~28/min in the only window we have actually measured and we have **not**
measured a diurnal profile — narrowing the set on intuition would suppress real alarms. The
row is written regardless of the hour; the hour only decides WARNING versus INFO.

Fallback: Helius ``transactionSubscribe`` (documented, not implemented)
----------------------------------------------------------------------
PumpPortal is a free third party with no SLA, and it is a *reinterpretation* of chain data —
if it drops a frame we have no way to know. The same events are available first-hand from
Helius by subscribing to the pump.fun program
``6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P``, with the pattern already established in
:mod:`shitcoims_intelligence.helius` (``HeliusTransactionStream``).

What it costs:

* **Decoding.** Helius delivers transactions, not events; the create/migrate semantics come
  out of the Borsh instruction data. ``shitcoims_intelligence.pump_layouts`` already carries
  those layouts, so this is wiring, not research — but it is real work and a real ongoing
  maintenance surface every time pump.fun changes a layout.
* **Block time.** A ``transactionSubscribe`` notification carries a ``slot`` and **no**
  ``blockTime``. ``shitcoims_intelligence.helius`` fixes this with ``SlotBlockTimeCache`` over
  ``getBlockTime`` (bounded cache, failures deliberately not cached, unresolved rows defected
  as ``block_time_unresolved`` rather than stamped with our clock). That is the piece worth
  having: it is the *only* route to a real ``t_event``, which PumpPortal cannot give at all.
* **Credits.** One RPC call per uncached slot on top of the subscription, against the same
  paid key the sentinel and the intelligence collector already depend on. At ~28 creates/min
  the slot cache collapses most of that, but the floor is not zero and it competes with
  execution for the same quota.

Implement it when PumpPortal actually proves unreliable — the ledger and staleness rows here
are what will show that, with dates and durations attached. It did not misbehave once in
testing, so paying the decode-plus-credits cost today would buy nothing measurable.

CLI
---
``uv run python -m shitcoims_scalper.firehose --minutes 3 --subscribe newToken,migration``
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import random
import signal
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol, TextIO
from uuid import uuid4

from shitcoims_tape.schema import INFORMATIVE_CLOSES, WatchClose

LOGGER = logging.getLogger("shitcoims.scalper.firehose")

PUMPPORTAL_URL: Final[str] = "wss://pumpportal.fun/api/data"

#: The pump.fun program, for the Helius fallback described in the module docstring.
PUMP_FUN_PROGRAM: Final[str] = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

FIREHOSE_DIR_ENV: Final[str] = "JOSHIBOT_FIREHOSE_DIR"
DEFAULT_FIREHOSE_DIR: Final[str] = "state/firehose"

DEFAULT_HEARTBEAT_SECONDS: Final[float] = 30.0
DEFAULT_STALE_AFTER_SECONDS: Final[float] = 120.0

#: Vendor-rounded quantities. Stored verbatim, never scaled into integers. See the module
#: docstring: these are for ranking and triage, never for accounting. ``newTokenBalance`` is
#: documented by the vendor for the trade feeds and has NOT been observed, since those feeds
#: need a funded key; the rest were all observed on the free feeds.
VENDOR_FLOAT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "initialBuy",
        "solAmount",
        "vTokensInBondingCurve",
        "vSolInBondingCurve",
        "marketCapSol",
        "newTokenBalance",
    }
)

#: Payload keys that would carry a vendor event clock if PumpPortal ever supplied one. None of
#: these has ever been observed on this feed; the list exists so that the day one appears we
#: start recording it instead of silently continuing to write nulls.
EVENT_CLOCK_KEYS: Final[tuple[str, ...]] = (
    "timestamp",
    "blockTime",
    "block_time",
    "eventTime",
    "time",
)

#: ``t_event_source`` values. Every row carries one, and the invariant is mechanical:
#: ``t_event`` is non-null iff the vendor supplied a clock.
CLOCK_ABSENT: Final[str] = "absent:vendor_payload_carries_no_event_clock"
CLOCK_LOCAL: Final[str] = "absent:local_row_has_no_vendor_clock"

#: Operational rows all land in one partition so the ledger reads as a timeline; event rows are
#: partitioned by their own kind. See :func:`partition_of`.
LEDGER_PARTITION: Final[str] = "ledger"


class Feed(StrEnum):
    """A subscription. ``value`` is the CLI spelling; :attr:`method` is the wire spelling."""

    NEW_TOKEN = "newToken"
    MIGRATION = "migration"
    TOKEN_TRADE = "tokenTrade"
    ACCOUNT_TRADE = "accountTrade"

    @property
    def method(self) -> str:
        return {
            Feed.NEW_TOKEN: "subscribeNewToken",
            Feed.MIGRATION: "subscribeMigration",
            Feed.TOKEN_TRADE: "subscribeTokenTrade",
            Feed.ACCOUNT_TRADE: "subscribeAccountTrade",
        }[self]

    @property
    def needs_keys(self) -> bool:
        """Whether the subscribe frame must carry a ``keys`` list of mints/wallets."""

        return self in (Feed.TOKEN_TRADE, Feed.ACCOUNT_TRADE)

    @property
    def needs_funded_key(self) -> bool:
        """Observed 2026-08-14: the trade feeds require an API key funded with >= 0.02 SOL."""

        return self in (Feed.TOKEN_TRADE, Feed.ACCOUNT_TRADE)


def parse_feeds(spec: str) -> tuple[Feed, ...]:
    """``"newToken,migration"`` -> feeds, order preserved, duplicates dropped."""

    out: list[Feed] = []
    for raw in spec.split(","):
        name = raw.strip()
        if not name:
            continue
        try:
            feed = Feed(name)
        except ValueError as exc:
            allowed = ", ".join(f.value for f in Feed)
            raise ValueError(f"unknown subscription {name!r}; expected one of: {allowed}") from exc
        if feed not in out:
            out.append(feed)
    if not out:
        raise ValueError("no subscriptions requested")
    return tuple(out)


#: ``txType`` -> row kind. An unmapped ``txType`` is kept as ``event_unclassified`` rather than
#: dropped: an unknown event we stored is recoverable, an unknown event we discarded is not.
_TX_TYPE_KIND: Final[dict[str, str]] = {
    "create": "new_token",
    "migrate": "migration",
    "buy": "trade",
    "sell": "trade",
}

KIND_UNCLASSIFIED: Final[str] = "event_unclassified"

_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {*_TX_TYPE_KIND.values(), KIND_UNCLASSIFIED}
)


def partition_of(kind: str) -> str:
    """Which directory a row of this kind belongs to.

    Event kinds get their own partition so a reader can tail one stream. Operational rows —
    the watch ledger, heartbeats, staleness, defects, vendor control messages — share the
    ``ledger`` partition, because the question they answer ("were we listening, and was the
    socket alive?") requires reading them interleaved and in order.
    """

    return kind if kind in _EVENT_KINDS else LEDGER_PARTITION


def iso(moment: datetime) -> str:
    """UTC ISO8601 with microseconds. Never abbreviated, so rows sort lexicographically."""

    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def utc_now() -> datetime:
    return datetime.now(UTC)


def event_clock(payload: Mapping[str, Any]) -> tuple[str | None, str]:
    """Extract the vendor's event clock. Returns ``(t_event, t_event_source)``.

    Returns ``(None, reason)`` when the payload has no clock — which is every PumpPortal
    payload observed to date. It never falls back to our clock. A key that is present but
    unparseable also yields ``None``, with a source that names the offending key, so a vendor
    changing its encoding surfaces as nulls with an explanation rather than as garbage
    timestamps.
    """

    for key in EVENT_CLOCK_KEYS:
        if key not in payload:
            continue
        raw = payload[key]
        if isinstance(raw, bool) or raw is None:
            return None, f"unparseable:{key}"
        if isinstance(raw, (int, float)):
            seconds = float(raw)
            unit = "unix_s"
            # Unix seconds stay below 1e11 until the year 5138; anything larger is milliseconds.
            if abs(seconds) >= 1e11:
                seconds /= 1000.0
                unit = "unix_ms"
            try:
                return iso(datetime.fromtimestamp(seconds, tz=UTC)), f"vendor:{key}:{unit}"
            except (OverflowError, OSError, ValueError):
                return None, f"unparseable:{key}"
        if isinstance(raw, str):
            try:
                parsed = datetime.fromisoformat(raw)
            except ValueError:
                return None, f"unparseable:{key}"
            if parsed.tzinfo is None:
                return None, f"unparseable:{key}:naive"
            return iso(parsed), f"vendor:{key}:iso8601"
        return None, f"unparseable:{key}"
    return None, CLOCK_ABSENT


def _base_row(kind: str, t_ingest: datetime, *, local: bool) -> dict[str, Any]:
    """Every row in every file starts here, so the two-clock invariant is structural."""

    return {
        "kind": kind,
        "t_ingest": iso(t_ingest),
        "t_event": None,
        "t_event_source": CLOCK_LOCAL if local else CLOCK_ABSENT,
    }


class MalformedFrame(ValueError):
    """A frame that could not be turned into a row. Recorded as a defect, never raised out."""


def classify(raw: str | bytes, t_ingest: datetime) -> dict[str, Any]:
    """Turn one wire frame into a row. Raises :class:`MalformedFrame` on garbage.

    The vendor payload is stored verbatim under ``payload`` — normalization here is additive
    only. If this module's idea of the schema is wrong, the bytes are still on disk.
    """

    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalformedFrame("frame is not utf-8") from exc
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise MalformedFrame("frame is not json") from exc
    if not isinstance(payload, dict):
        raise MalformedFrame(f"frame is json {type(payload).__name__}, not an object")

    # Vendor control frames: subscription acks, and the funded-key rejection for the trade feeds.
    if "message" in payload and "txType" not in payload:
        row = _base_row("control", t_ingest, local=False)
        row["message"] = payload["message"]
        row["payload"] = payload
        return row

    tx_type = payload.get("txType")
    if isinstance(tx_type, str):
        kind = _TX_TYPE_KIND.get(tx_type, KIND_UNCLASSIFIED)
    elif tx_type is None:
        kind = KIND_UNCLASSIFIED
    else:
        raise MalformedFrame(f"txType is {type(tx_type).__name__}, not a string")

    t_event, source = event_clock(payload)
    row = _base_row(kind, t_ingest, local=False)
    row["t_event"] = t_event
    row["t_event_source"] = source
    row["tx_type"] = tx_type
    # Promoted for indexing only; `payload` remains the authority.
    for key, column in (("mint", "mint"), ("signature", "signature"), ("pool", "venue")):
        value = payload.get(key)
        if isinstance(value, str):
            row[column] = value
    row["payload"] = payload
    return row


def defect_row(t_ingest: datetime, reason: str, raw: Any) -> dict[str, Any]:
    """A frame we could not parse, kept with a bounded excerpt of what arrived."""

    row = _base_row("defect", t_ingest, local=True)
    row["reason"] = reason
    excerpt = raw if isinstance(raw, str) else repr(raw)
    row["raw_excerpt"] = excerpt[:2000]
    row["raw_length"] = len(excerpt)
    return row


@dataclass(frozen=True, slots=True)
class PreviousClose:
    """The last moment a previous process admits to having been listening."""

    closed_at: datetime
    reason: str
    source: str


def last_close_on_disk(root: Path, *, max_files: int = 3) -> PreviousClose | None:
    """Find the most recent ``watch_close`` already written under ``root``.

    This is what makes a restart gap first-class. Without it, downtime that spans a process
    boundary is only recoverable by joining the tail of one run's ledger to the head of the
    next — which is exactly the sort of reconstruction nobody performs until after the fact.

    Bounded on purpose: at most ``max_files`` day-partitions, newest first. A tape that has
    been dark longer than that reports nothing rather than scanning an unbounded history, and
    "nothing" is honest — the first ``watch_open`` with no preceding gap row means we do not
    know how long we were down, which is a different claim from "we were down zero seconds".
    """

    ledger_dir = Path(root) / LEDGER_PARTITION
    if not ledger_dir.is_dir():
        return None
    days = sorted((p for p in ledger_dir.glob("*.jsonl") if p.is_file()), reverse=True)
    for path in days[:max_files]:
        found: PreviousClose | None = None
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or '"watch_close"' not in line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue  # a torn final line; health tooling counts these, we skip
                    if row.get("kind") != "watch_close":
                        continue
                    window = row.get("window") or {}
                    closed_at = window.get("closed_at")
                    if not isinstance(closed_at, str):
                        continue
                    try:
                        moment = datetime.fromisoformat(closed_at)
                    except ValueError:
                        continue
                    if moment.tzinfo is None:
                        continue
                    found = PreviousClose(
                        closed_at=moment,
                        reason=str(window.get("close_reason", "unknown")),
                        source=str(path),
                    )
        except OSError:
            continue
        if found is not None:
            return found
    return None


class Sink(Protocol):
    """Where rows go. A protocol so tests can collect rows without touching a disk."""

    def write(self, partition: str, row: Mapping[str, Any]) -> None: ...

    def close(self) -> None: ...


class JsonlSink:
    """Append-only JSONL under ``root/<partition>/<UTC day>.jsonl``.

    Flushed per row so a ``tail -f`` sees the tape live, but ``fsync``'d only when a day
    partition is closed — a per-row fsync at ~28 events/min is affordable, but the pattern that
    survives the trade feeds' rate is not, and the loss window (one buffer) is bounded and
    visible as a truncated final line.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._handles: dict[tuple[str, str], TextIO] = {}
        self.rows_written = 0

    @staticmethod
    def _day(row: Mapping[str, Any]) -> str:
        stamp = str(row.get("t_ingest", ""))
        return stamp[:10] if len(stamp) >= 10 else utc_now().date().isoformat()

    def path_for(self, partition: str, day: str) -> Path:
        return self.root / partition / f"{day}.jsonl"

    def write(self, partition: str, row: Mapping[str, Any]) -> None:
        day = self._day(row)
        key = (partition, day)
        handle = self._handles.get(key)
        if handle is None:
            self._rotate_out(partition, day)
            path = self.path_for(partition, day)
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("a", encoding="utf-8")
            self._handles[key] = handle
        handle.write(json.dumps(row, separators=(",", ":"), sort_keys=False) + "\n")
        handle.flush()
        self.rows_written += 1

    def _rotate_out(self, partition: str, day: str) -> None:
        """Close any older day still open for this partition, durably."""

        for key in [k for k in self._handles if k[0] == partition and k[1] != day]:
            self._close_handle(key)

    def _close_handle(self, key: tuple[str, str]) -> None:
        handle = self._handles.pop(key)
        try:
            handle.flush()
            os.fsync(handle.fileno())
        except OSError:  # pragma: no cover - a dead fd is not worth crashing the recorder over
            LOGGER.warning("fsync failed for %s/%s", *key)
        finally:
            handle.close()

    def close(self) -> None:
        for key in list(self._handles):
            self._close_handle(key)


class ListSink:
    """In-memory sink for tests and for callers that want rows without files."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, dict[str, Any]]] = []

    def write(self, partition: str, row: Mapping[str, Any]) -> None:
        self.rows.append((partition, dict(row)))

    def close(self) -> None:
        return None

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [row for _, row in self.rows if row.get("kind") == kind]


@dataclass
class Backoff:
    """Exponential backoff with jitter, reset on every successful connection."""

    base: float = 1.0
    factor: float = 2.0
    cap: float = 60.0
    jitter: float = 0.25
    attempts: int = 0

    def reset(self) -> None:
        self.attempts = 0

    def next_delay(self, rand: Callable[[], float] = random.random) -> float:
        delay = min(self.cap, self.base * (self.factor**self.attempts))
        self.attempts += 1
        spread = delay * self.jitter
        return max(0.0, delay - spread + 2 * spread * rand())


@dataclass
class FeedWatch:
    """One connection's watch window: when we started listening, when we stopped, and why."""

    window_id: str
    url: str
    feeds: tuple[str, ...]
    opened_at: datetime
    closed_at: datetime | None = None
    close_reason: WatchClose | None = None
    close_detail: str | None = None
    events: int = 0
    defects: int = 0
    controls: int = 0

    def _window(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "window_id": self.window_id,
            "url": self.url,
            "feeds": list(self.feeds),
            "opened_at": iso(self.opened_at),
        }
        if self.closed_at is not None:
            out["closed_at"] = iso(self.closed_at)
            out["close_reason"] = str(self.close_reason)
            out["seconds"] = round((self.closed_at - self.opened_at).total_seconds(), 6)
            if self.close_detail:
                out["close_detail"] = self.close_detail
        return out

    def open_row(self) -> dict[str, Any]:
        row = _base_row("watch_open", self.opened_at, local=True)
        row["window"] = self._window()
        return row

    def close(self, now: datetime, reason: WatchClose, detail: str | None = None) -> dict[str, Any]:
        self.closed_at = now
        self.close_reason = reason
        self.close_detail = detail
        row = _base_row("watch_close", now, local=True)
        row["events"] = self.events
        row["defects"] = self.defects
        row["controls"] = self.controls
        row["informative_censoring"] = self.is_informatively_censored
        row["window"] = self._window()
        return row

    @property
    def is_informatively_censored(self) -> bool:
        return self.close_reason in INFORMATIVE_CLOSES


@dataclass
class WatchLedger:
    """The run-level ledger: successive windows plus the gaps between them.

    A gap row is emitted on *reopen* rather than being left implicit in the close/open pair,
    so "we were not listening from A to B" is a single greppable fact rather than a join a
    downstream reader has to remember to perform.

    The gap between two *processes* is recorded the same way, via :meth:`seed_from_disk` — a
    downtime that spans a restart is not a lesser kind of blindness, and it is the exact shape
    of the outage this module was built after: nothing was listening for a day, and no row
    anywhere said so.
    """

    url: str
    feeds: tuple[str, ...]
    run_id: str = field(default_factory=lambda: uuid4().hex[:12])
    windows: int = 0
    current: FeedWatch | None = None
    last_closed_at: datetime | None = None
    last_close_reason: WatchClose | None = None
    last_close_label: str | None = None
    gap_seconds: float = 0.0
    gaps: int = 0

    def seed_from_disk(self, closed_at: datetime, previous_reason: str) -> None:
        """Resume accounting from a previous process's last close."""

        self.last_closed_at = closed_at
        self.last_close_label = f"process_not_running:{previous_reason}"

    def open(self, now: datetime) -> list[dict[str, Any]]:
        self.windows += 1
        watch = FeedWatch(
            window_id=f"{self.run_id}-{self.windows:04d}",
            url=self.url,
            feeds=self.feeds,
            opened_at=now,
        )
        self.current = watch
        rows: list[dict[str, Any]] = []
        if self.last_closed_at is not None:
            seconds = (now - self.last_closed_at).total_seconds()
            self.gaps += 1
            self.gap_seconds += seconds
            gap = _base_row("gap", now, local=True)
            gap["started_at"] = iso(self.last_closed_at)
            gap["ended_at"] = iso(now)
            gap["seconds"] = round(seconds, 6)
            gap["reason"] = f"not_listening:{self.last_close_label}"
            gap["window_id"] = watch.window_id
            rows.append(gap)
        rows.append(watch.open_row())
        return rows

    def close(self, now: datetime, reason: WatchClose, detail: str | None = None) -> dict[str, Any] | None:
        watch = self.current
        if watch is None:
            return None
        row = watch.close(now, reason, detail)
        self.current = None
        self.last_closed_at = now
        self.last_close_reason = reason
        self.last_close_label = str(reason)
        return row

    def connect_failed(self, now: datetime, detail: str, retry_in: float) -> dict[str, Any]:
        """A connection we never established. There is no window to close, and that is the point.

        Without this row the interval reads as "no events", which is the exact confusion this
        module exists to prevent — so the failure is recorded even though nothing was open.
        """

        row = _base_row("connect_failed", now, local=True)
        row["url"] = self.url
        row["detail"] = detail
        row["retry_in_seconds"] = round(retry_in, 3)
        if self.last_closed_at is not None:
            row["not_listening_since"] = iso(self.last_closed_at)
        return row


@dataclass
class LivenessMonitor:
    """Heartbeat scheduling and the staleness alarm. Pure: it is handed a clock, never reads one.

    Kept separate from the socket loop precisely so it can be tested without any I/O at all.
    """

    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS
    busy_hours: frozenset[int] = field(default_factory=lambda: frozenset(range(24)))
    started_at: datetime | None = None
    last_event_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    stale_since: datetime | None = None
    last_stale_row_at: datetime | None = None
    events_total: int = 0
    events_since_heartbeat: int = 0
    heartbeats: int = 0
    stale_alarms: int = 0

    def start(self, now: datetime) -> None:
        self.started_at = now
        self.last_heartbeat_at = now

    @property
    def _reference(self) -> datetime | None:
        """Silence is measured from the last event, or from the start if none has ever come."""

        return self.last_event_at or self.started_at

    def note_event(self, now: datetime) -> dict[str, Any] | None:
        """Record an event; returns a ``stale_cleared`` row if this ends a silent stretch."""

        self.events_total += 1
        self.events_since_heartbeat += 1
        previous = self._reference
        self.last_event_at = now
        if self.stale_since is None:
            return None
        row = _base_row("stale_cleared", now, local=True)
        row["stale_since"] = iso(self.stale_since)
        row["silent_seconds"] = round((now - previous).total_seconds(), 6) if previous else None
        row["threshold_seconds"] = self.stale_after_seconds
        self.stale_since = None
        self.last_stale_row_at = None
        return row

    def next_deadline_seconds(self, now: datetime) -> float:
        """Seconds until the next scheduled tick. Never negative, never unbounded.

        This is what bounds the socket read: the loop can never block past the moment a
        heartbeat or a staleness alarm comes due, which is what lets the alarm fire during
        silence rather than only when the next frame happens to arrive.
        """

        if self.last_heartbeat_at is None:
            candidates = [self.heartbeat_seconds]
        else:
            candidates = [self.heartbeat_seconds - (now - self.last_heartbeat_at).total_seconds()]
        reference = self.last_stale_row_at or self._reference
        if reference is not None:
            candidates.append(self.stale_after_seconds - (now - reference).total_seconds())
        return max(0.0, min(candidates))

    def due(self, now: datetime, *, connected: bool, window_id: str | None) -> list[dict[str, Any]]:
        """Rows the clock owes us: a heartbeat if one is due, a stale alarm if silence persists."""

        rows: list[dict[str, Any]] = []
        silent = self.silent_seconds(now)
        reference = self.last_stale_row_at or self._reference
        if (
            connected
            and reference is not None
            and (now - reference).total_seconds() >= self.stale_after_seconds
        ):
            if self.stale_since is None:
                self.stale_since = self._reference or now
            self.last_stale_row_at = now
            self.stale_alarms += 1
            row = _base_row("stale", now, local=True)
            row["stale_since"] = iso(self.stale_since)
            row["silent_seconds"] = round(silent, 6) if silent is not None else None
            row["threshold_seconds"] = self.stale_after_seconds
            row["busy_hour"] = now.hour in self.busy_hours
            row["events_total"] = self.events_total
            row["window_id"] = window_id
            rows.append(row)
            message = (
                "firehose silent for %.1fs (threshold %.0fs, window %s) — socket open, no events"
            )
            if now.hour in self.busy_hours:
                LOGGER.warning(message, silent or 0.0, self.stale_after_seconds, window_id)
            else:
                LOGGER.info(message, silent or 0.0, self.stale_after_seconds, window_id)

        if (
            self.last_heartbeat_at is not None
            and (now - self.last_heartbeat_at).total_seconds() >= self.heartbeat_seconds
        ):
            self.last_heartbeat_at = now
            self.heartbeats += 1
            row = _base_row("heartbeat", now, local=True)
            row["connected"] = connected
            row["window_id"] = window_id
            row["events_total"] = self.events_total
            row["events_since_last_heartbeat"] = self.events_since_heartbeat
            row["silent_seconds"] = round(silent, 6) if silent is not None else None
            row["stale"] = self.stale_since is not None
            row["last_event_at"] = iso(self.last_event_at) if self.last_event_at else None
            self.events_since_heartbeat = 0
            rows.append(row)
        return rows

    def silent_seconds(self, now: datetime) -> float | None:
        reference = self._reference
        if reference is None:
            return None
        return (now - reference).total_seconds()


class Socket(Protocol):
    """The slice of a websocket connection this module uses."""

    async def send(self, message: str) -> Any: ...

    async def recv(self) -> str | bytes: ...


Connector = Callable[[str], AbstractAsyncContextManager[Socket]]


def _default_connector(url: str) -> AbstractAsyncContextManager[Socket]:
    import websockets  # imported lazily so tests never need the package or a network stack

    return websockets.connect(url, open_timeout=15, ping_interval=20, ping_timeout=20)


@dataclass(frozen=True, slots=True)
class FirehoseStats:
    """What the run actually did. Reported, never inferred."""

    run_id: str
    started_at: str
    ended_at: str
    windows: int
    gaps: int
    gap_seconds: float
    events_by_kind: dict[str, int]
    defects: int
    controls: int
    connect_failures: int
    heartbeats: int
    stale_alarms: int
    rows_written: int

    @property
    def events(self) -> int:
        return sum(self.events_by_kind.values())

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "windows": self.windows,
            "gaps": self.gaps,
            "gap_seconds": round(self.gap_seconds, 3),
            "events": self.events,
            "events_by_kind": dict(sorted(self.events_by_kind.items())),
            "defects": self.defects,
            "controls": self.controls,
            "connect_failures": self.connect_failures,
            "heartbeats": self.heartbeats,
            "stale_alarms": self.stale_alarms,
            "rows_written": self.rows_written,
        }


class FirehoseClient:
    """Subscribe, reconnect, and write rows. All I/O is injected so tests run fully offline."""

    def __init__(
        self,
        *,
        sink: Sink,
        feeds: Sequence[Feed] = (Feed.NEW_TOKEN, Feed.MIGRATION),
        keys: Sequence[str] = (),
        url: str = PUMPPORTAL_URL,
        connect: Connector | None = None,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], Any] | None = None,
        heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
        busy_hours: Iterable[int] | None = None,
        backoff: Backoff | None = None,
        max_attempts: int | None = None,
        poll_seconds: float = 1.0,
        resume_from: PreviousClose | None = None,
    ) -> None:
        if not feeds:
            raise ValueError("at least one subscription is required")
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.sink = sink
        self.feeds = tuple(feeds)
        self.keys = tuple(keys)
        self.url = url
        self._connect = connect or _default_connector
        self._clock = clock
        self._sleep = sleep or asyncio.sleep
        self._backoff = backoff or Backoff()
        self._max_attempts = max_attempts
        #: Upper bound on how long a blocked read may delay a SIGINT. See :meth:`_pump`.
        self._poll_seconds = poll_seconds
        self.attempts = 0
        self.monitor = LivenessMonitor(
            heartbeat_seconds=heartbeat_seconds,
            stale_after_seconds=stale_after_seconds,
            busy_hours=frozenset(busy_hours) if busy_hours is not None else frozenset(range(24)),
        )
        self.ledger = WatchLedger(url=url, feeds=tuple(f.value for f in self.feeds))
        if resume_from is not None:
            self.ledger.seed_from_disk(resume_from.closed_at, resume_from.reason)
        self.events_by_kind: dict[str, int] = {}
        self.defects = 0
        self.controls = 0
        self.connect_failures = 0
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    def _emit(self, row: Mapping[str, Any]) -> None:
        self.sink.write(partition_of(str(row.get("kind", "unknown"))), row)

    def _emit_all(self, rows: Iterable[Mapping[str, Any]]) -> None:
        for row in rows:
            self._emit(row)

    def _subscribe_frames(self) -> list[str]:
        frames: list[str] = []
        for feed in self.feeds:
            body: dict[str, Any] = {"method": feed.method}
            if feed.needs_keys:
                if not self.keys:
                    LOGGER.warning(
                        "%s requested with no keys; the vendor will accept it and send nothing",
                        feed.value,
                    )
                body["keys"] = list(self.keys)
            if feed.needs_funded_key:
                LOGGER.warning(
                    "%s requires a PumpPortal API key funded with >= 0.02 SOL; "
                    "without one the subscription is accepted and stays silent",
                    feed.value,
                )
            frames.append(json.dumps(body))
        return frames

    async def run(self, deadline: datetime | None = None) -> FirehoseStats:
        """Connect, pump, reconnect, until ``deadline`` or :meth:`stop`."""

        started_at = self._clock()
        self.monitor.start(started_at)
        try:
            while not self._finished(deadline):
                await self._one_connection(deadline)
        finally:
            now = self._clock()
            if self.ledger.current is not None:
                reason = WatchClose.OPERATOR if self._stop.is_set() else WatchClose.DEADLINE
                row = self.ledger.close(now, reason, "run ended without a socket close")
                if row is not None:
                    self._emit(row)
            self.sink.close()
        return self._stats(started_at, self._clock())

    def _finished(self, deadline: datetime | None) -> bool:
        if self._stop.is_set():
            return True
        if self._max_attempts is not None and self.attempts >= self._max_attempts:
            return True
        return deadline is not None and self._clock() >= deadline

    async def _one_connection(self, deadline: datetime | None) -> None:
        """One attempt: connect, subscribe, pump until it ends, close the window with a reason.

        Two failure shapes, deliberately kept distinct on disk. A socket that dropped while we
        held it closes its window with ``OBSERVER_LOST``. A socket we never got emits
        ``connect_failed`` and closes nothing, because there was nothing open — and without
        that row the interval would read as "no events", which is the confusion this module
        exists to prevent.
        """

        self.attempts += 1
        opened = False
        try:
            async with self._connect(self.url) as socket:
                now = self._clock()
                self._emit_all(self.ledger.open(now))
                opened = True
                self._backoff.reset()
                for frame in self._subscribe_frames():
                    await socket.send(frame)
                reason, detail = await self._pump(socket, deadline)
        except (asyncio.CancelledError, KeyboardInterrupt):
            row = self.ledger.close(self._clock(), WatchClose.OPERATOR, "cancelled")
            if row is not None:
                self._emit(row)
            raise
        except Exception as exc:
            # Any transport failure at all means we lost the observer. Narrowing this to known
            # websocket exceptions would let a DNS error kill the loop silently, which is the
            # exact way the intelligence daemon died unnoticed for a day.
            now = self._clock()
            failure = f"{type(exc).__name__}: {exc}"
            if opened:
                LOGGER.warning("firehose connection lost: %s", failure)
                row = self.ledger.close(now, WatchClose.OBSERVER_LOST, failure)
                if row is not None:
                    self._emit(row)
            else:
                self.connect_failures += 1
                LOGGER.warning("firehose connect failed: %s", failure)
            if self._finished(deadline):
                if not opened:
                    self._emit(self.ledger.connect_failed(now, failure, 0.0))
                return
            delay = self._backoff.next_delay()
            if not opened:
                self._emit(self.ledger.connect_failed(now, failure, delay))
            await self._sleep(delay)
            # Heartbeat through the outage too. Without this the only liveness signal during a
            # long vendor outage would be the reconnect attempts themselves, and a process that
            # wedged mid-backoff would look identical to one patiently retrying.
            self._tick(self._clock())
            return
        row = self.ledger.close(self._clock(), reason, detail)
        if row is not None:
            self._emit(row)

    async def _pump(
        self, socket: Socket, deadline: datetime | None
    ) -> tuple[WatchClose, str | None]:
        """Read until the deadline, a stop, or an exception (which the caller turns into a loss).

        The read is bounded three ways, and the tightest wins: the next heartbeat or staleness
        deadline, the run deadline, and :attr:`_poll_seconds`. That last one is what bounds
        SIGINT latency — without it a quiet feed would hold the read for a full heartbeat
        interval and Ctrl-C would appear to hang, closing the watch window late or not at all.
        Cancelling ``recv`` to do this is explicitly safe in ``websockets``: no message is lost,
        the next call returns it.
        """

        while True:
            now = self._clock()
            if self._stop.is_set():
                return WatchClose.OPERATOR, "stop requested"
            if deadline is not None and now >= deadline:
                return WatchClose.DEADLINE, "run deadline reached"
            try:
                raw = await asyncio.wait_for(
                    socket.recv(), timeout=self.read_timeout(now, deadline)
                )
            except TimeoutError:
                self._tick(self._clock())
                continue
            self._handle_frame(raw, self._clock())
            self._tick(self._clock())

    def read_timeout(self, now: datetime, deadline: datetime | None) -> float:
        """How long the next socket read may block: the tightest of the three bounds."""

        timeout = min(self.monitor.next_deadline_seconds(now), self._poll_seconds)
        if deadline is not None:
            timeout = min(timeout, max(0.0, (deadline - now).total_seconds()))
        return max(timeout, 0.001)

    def _tick(self, now: datetime) -> None:
        window = self.ledger.current
        self._emit_all(
            self.monitor.due(
                now,
                connected=window is not None,
                window_id=window.window_id if window is not None else None,
            )
        )

    def _handle_frame(self, raw: str | bytes, now: datetime) -> None:
        window = self.ledger.current
        try:
            row = classify(raw, now)
        except MalformedFrame as exc:
            self.defects += 1
            if window is not None:
                window.defects += 1
            LOGGER.warning("firehose defect: %s", exc)
            self._emit(defect_row(now, str(exc), raw))
            return
        kind = str(row["kind"])
        if window is not None:
            row["window_id"] = window.window_id
        if kind == "control":
            self.controls += 1
            if window is not None:
                window.controls += 1
            message = str(row.get("message", ""))
            if "only available" in message or "error" in message.lower():
                LOGGER.warning("firehose vendor control: %s", message)
            else:
                LOGGER.info("firehose vendor control: %s", message)
            self._emit(row)
            return
        self.events_by_kind[kind] = self.events_by_kind.get(kind, 0) + 1
        if window is not None:
            window.events += 1
        cleared = self.monitor.note_event(now)
        self._emit(row)
        if cleared is not None:
            LOGGER.info("firehose recovered after %.1fs of silence", cleared["silent_seconds"] or 0.0)
            self._emit(cleared)

    def _stats(self, started_at: datetime, ended_at: datetime) -> FirehoseStats:
        rows = getattr(self.sink, "rows_written", None)
        if rows is None:
            rows = len(getattr(self.sink, "rows", ()))
        return FirehoseStats(
            run_id=self.ledger.run_id,
            started_at=iso(started_at),
            ended_at=iso(ended_at),
            windows=self.ledger.windows,
            gaps=self.ledger.gaps,
            gap_seconds=self.ledger.gap_seconds,
            events_by_kind=dict(self.events_by_kind),
            defects=self.defects,
            controls=self.controls,
            connect_failures=self.connect_failures,
            heartbeats=self.monitor.heartbeats,
            stale_alarms=self.monitor.stale_alarms,
            rows_written=int(rows),
        )


def default_firehose_dir() -> Path:
    configured = os.environ.get(FIREHOSE_DIR_ENV)
    return Path(configured).expanduser() if configured else Path(DEFAULT_FIREHOSE_DIR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m shitcoims_scalper.firehose",
        description="Record the PumpPortal firehose to partitioned JSONL with a watch ledger.",
    )
    parser.add_argument(
        "--minutes",
        type=float,
        default=None,
        help="stop after this many minutes; omit to run until SIGINT",
    )
    parser.add_argument(
        "--subscribe",
        default="newToken,migration",
        help="comma-separated: newToken, migration, tokenTrade, accountTrade",
    )
    parser.add_argument(
        "--keys",
        default="",
        help="comma-separated mints/wallets for tokenTrade/accountTrade (needs a funded key)",
    )
    parser.add_argument("--url", default=PUMPPORTAL_URL, help="websocket endpoint")
    parser.add_argument(
        "--out-dir",
        default=None,
        help=f"output root (default ${FIREHOSE_DIR_ENV} or {DEFAULT_FIREHOSE_DIR})",
    )
    parser.add_argument("--heartbeat-seconds", type=float, default=DEFAULT_HEARTBEAT_SECONDS)
    parser.add_argument("--stale-seconds", type=float, default=DEFAULT_STALE_AFTER_SECONDS)
    parser.add_argument(
        "--busy-hours",
        default=None,
        help="comma-separated UTC hours where staleness is WARNING (default: all 24)",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser


async def _run_cli(args: argparse.Namespace) -> FirehoseStats:
    feeds = parse_feeds(args.subscribe)
    keys = tuple(k.strip() for k in args.keys.split(",") if k.strip())
    busy_hours = (
        tuple(int(h) for h in args.busy_hours.split(",") if h.strip())
        if args.busy_hours
        else None
    )
    root = Path(args.out_dir).expanduser() if args.out_dir else default_firehose_dir()
    sink = JsonlSink(root)
    resume_from = last_close_on_disk(root)
    if resume_from is not None:
        down_for = (utc_now() - resume_from.closed_at).total_seconds()
        LOGGER.info(
            "previous run stopped listening at %s (%s); %.1fs of downtime will be recorded as a gap",
            iso(resume_from.closed_at),
            resume_from.reason,
            down_for,
        )
    client = FirehoseClient(
        sink=sink,
        feeds=feeds,
        keys=keys,
        url=args.url,
        heartbeat_seconds=args.heartbeat_seconds,
        stale_after_seconds=args.stale_seconds,
        busy_hours=busy_hours,
        resume_from=resume_from,
    )
    loop = asyncio.get_running_loop()
    installed: list[Any] = []
    for signame in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, signame, None)
        if sig is None:
            continue
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, client.stop)
            installed.append(sig)
    deadline = (
        utc_now() + timedelta(minutes=args.minutes) if args.minutes is not None else None
    )
    LOGGER.info(
        "firehose starting: feeds=%s url=%s out=%s deadline=%s",
        ",".join(f.value for f in feeds),
        args.url,
        root,
        iso(deadline) if deadline else "none",
    )
    try:
        return await client.run(deadline=deadline)
    finally:
        for sig in installed:
            with contextlib.suppress(NotImplementedError, ValueError):
                loop.remove_signal_handler(sig)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        stats = asyncio.run(_run_cli(args))
    except KeyboardInterrupt:  # pragma: no cover - the signal handler normally wins first
        LOGGER.warning("interrupted before the watch window could be closed cleanly")
        return 130
    print(json.dumps(stats.to_json(), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
