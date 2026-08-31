"""Append-only JSONL tape segments on disk.

The recorder's durability layer. Three decisions here are load-bearing:

**Append-only, one event per line, never rewritten.** A tape segment is opened in append
mode and closed; no line is ever edited in place. That is what makes a recorded fill a fact
rather than a mutable belief, and it is the storage-level analogue of the accounting rule
that cost basis may only be constructed from observed chain fills.

**fsync on rotate, not per event.** A per-event ``fsync`` costs ~1ms on a spinning disk and
several hundred microseconds on NVMe, which is below pump.fun's peak trade rate; the recorder
would drop events to keep the disk honest, and dropped events are unrecoverable while a
truncated tail is not. So durability is a segment-boundary property: on rotate and on close we
``flush`` -> ``fsync(file)`` -> ``fsync(directory)``, and the directory fsync is what makes the
new segment's *name* durable, not just its bytes. A crash therefore costs at most the current
segment's unflushed tail, and :mod:`shitcoims_tape.health` counts the resulting malformed
final line rather than silently skipping it.

**Content-hash dedupe.** The same fill arrives twice whenever a websocket firehose and an
HTTP backfill overlap, which is exactly the configuration a gap-recovery design produces.
``TapeEvent.event_id`` is a content hash, so the second copy is dropped here rather than
double-counting in every downstream intensity estimate.

Storage target in production is ``/tank`` on hbox, set through ``JOSHIBOT_TAPE_DIR``. The
default is a local directory so nothing here can write to a production volume by accident.
"""

from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, Final

from shitcoims_tape.schema import TapeEvent

#: Production points this at ``/tank/joshibot/tape``. Never defaulted, so a stray run on a
#: laptop cannot try to write to a storage volume that does not exist here.
TAPE_ROOT_ENV: Final[str] = "JOSHIBOT_TAPE_DIR"
DEFAULT_TAPE_ROOT: Final[str] = "tape"

DEFAULT_SEGMENT_BYTES: Final[int] = 64 * 1024 * 1024
DEFAULT_DEDUPE_WINDOW: Final[int] = 200_000

_SEGMENT_SUFFIX: Final[str] = ".jsonl"


class TapeWriteError(RuntimeError):
    """The tape could not be written. Always fail closed: a lost event is unrecoverable."""


def default_tape_root() -> Path:
    """Where segments go. ``JOSHIBOT_TAPE_DIR`` if set, else ``./tape``."""

    configured = os.environ.get(TAPE_ROOT_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path(DEFAULT_TAPE_ROOT)


@dataclass(frozen=True, slots=True)
class WriterStats:
    """What the writer actually did. Reported, never inferred."""

    events_written: int
    events_deduped: int
    bytes_written: int
    segments_opened: int
    rotations: int
    fsyncs: int
    current_segment: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "events_written": self.events_written,
            "events_deduped": self.events_deduped,
            "bytes_written": self.bytes_written,
            "segments_opened": self.segments_opened,
            "rotations": self.rotations,
            "fsyncs": self.fsyncs,
            "current_segment": self.current_segment,
        }


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TapeWriter:
    """One writer, one directory. Thread-safe; a tape has exactly one writer by design.

    ``prefix`` separates provenance families into their own segments — live recording,
    a MELT import and a RED-PUMP import must never share a file, because retention,
    re-import and deletion all operate at segment granularity.
    """

    def __init__(
        self,
        root: Path | None = None,
        *,
        prefix: str = "tape",
        max_segment_bytes: int = DEFAULT_SEGMENT_BYTES,
        dedupe_window: int = DEFAULT_DEDUPE_WINDOW,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not prefix or not prefix.replace("-", "").replace("_", "").isalnum():
            raise ValueError("segment prefix must be alphanumeric with - or _")
        if max_segment_bytes < 1024:
            raise ValueError("max_segment_bytes must be at least 1024")
        if dedupe_window < 0:
            raise ValueError("dedupe_window must not be negative")
        self._root = (root if root is not None else default_tape_root()).expanduser()
        self._prefix = prefix
        self._max_segment_bytes = max_segment_bytes
        self._dedupe_window = dedupe_window
        self._clock = clock
        self._lock = threading.Lock()
        self._handle: BinaryIO | None = None
        self._fileno: int | None = None
        self._path: Path | None = None
        self._segment_bytes = 0
        self._segment_day = ""
        self._sequence = 0
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._events_written = 0
        self._events_deduped = 0
        self._bytes_written = 0
        self._segments_opened = 0
        self._rotations = 0
        self._fsyncs = 0
        self._closed = False

    # -- public surface ------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def path(self) -> Path | None:
        """The segment currently open, or None before the first write."""

        return self._path

    def write(self, event: TapeEvent) -> bool:
        """Append one event. Returns False when the content hash was already recorded."""

        payload = event.to_json()
        event_id = str(payload["event_id"])
        # Serialise exactly as `TapeEvent.to_jsonl` does, from the payload we already
        # built, so the content hash is computed once on a firehose-rate path.
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if "\n" in line:  # pragma: no cover - json.dumps escapes newlines by construction
            raise TapeWriteError("a tape line must not contain a newline")
        with self._lock:
            if self._closed:
                raise TapeWriteError("tape writer is closed")
            if self._dedupe_window and event_id in self._seen:
                self._seen.move_to_end(event_id)
                self._events_deduped += 1
                return False
            encoded = (line + "\n").encode("utf-8")
            handle = self._ensure_segment(len(encoded))
            handle.write(encoded)
            self._segment_bytes += len(encoded)
            self._bytes_written += len(encoded)
            self._events_written += 1
            if self._dedupe_window:
                self._seen[event_id] = None
                while len(self._seen) > self._dedupe_window:
                    self._seen.popitem(last=False)
            return True

    def write_all(self, events: Iterable[TapeEvent]) -> int:
        """Append many. Returns the number actually written after dedupe."""

        return sum(1 for event in events if self.write(event))

    def checkpoint(self) -> None:
        """Flush and fsync without rotating. For a shutdown or an operator checkpoint."""

        with self._lock:
            self._sync_locked()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._sync_locked()
            self._close_locked()
            self._closed = True

    @property
    def stats(self) -> WriterStats:
        with self._lock:
            return WriterStats(
                events_written=self._events_written,
                events_deduped=self._events_deduped,
                bytes_written=self._bytes_written,
                segments_opened=self._segments_opened,
                rotations=self._rotations,
                fsyncs=self._fsyncs,
                current_segment=str(self._path) if self._path is not None else None,
            )

    def segments(self) -> tuple[Path, ...]:
        """Every segment this writer's prefix owns in the root, oldest name first."""

        if not self._root.is_dir():
            return ()
        return tuple(sorted(self._root.glob(f"{self._prefix}-*{_SEGMENT_SUFFIX}")))

    def __enter__(self) -> TapeWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # -- internals -----------------------------------------------------------------

    def _ensure_segment(self, incoming_bytes: int) -> BinaryIO:
        day = self._clock().strftime("%Y%m%d")
        if self._handle is None:
            return self._open_locked(day, 0)
        # Rotate on the UTC day boundary as well as on size: segments are the retention
        # and re-import unit, and a day-aligned boundary makes both trivially scriptable.
        if day != self._segment_day or self._segment_bytes + incoming_bytes > self._max_segment_bytes:
            self._sync_locked()
            self._close_locked()
            self._rotations += 1
            # Rotation must move FORWARD. Restarting the search at zero would re-open the
            # segment we just left whenever it happened to be under the size threshold,
            # turning every subsequent write into another rotation of the same file.
            return self._open_locked(day, 0 if day != self._segment_day else self._sequence + 1)
        return self._handle

    def _open_locked(self, day: str, min_sequence: int) -> BinaryIO:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TapeWriteError(f"tape root is not writable: {self._root}") from exc
        sequence = min_sequence
        while True:
            candidate = self._root / f"{self._prefix}-{day}-{sequence:04d}{_SEGMENT_SUFFIX}"
            existing = candidate.stat().st_size if candidate.exists() else 0
            if existing < self._max_segment_bytes:
                break
            sequence += 1
            if sequence > 9999:
                raise TapeWriteError("exhausted segment sequence numbers for one day")
        try:
            handle = candidate.open("ab", buffering=1024 * 1024)
        except OSError as exc:
            raise TapeWriteError(f"cannot open tape segment: {candidate}") from exc
        self._handle = handle
        self._fileno = handle.fileno()
        self._path = candidate
        self._segment_bytes = existing
        self._segment_day = day
        self._sequence = sequence
        self._segments_opened += 1
        return handle

    def _sync_locked(self) -> None:
        handle = self._handle
        if handle is None or self._fileno is None:
            return
        handle.flush()
        os.fsync(self._fileno)
        self._fsyncs += 1
        # The file's bytes are durable but its directory entry may not be. A crash between
        # the two loses the whole segment, not just its tail, so sync the directory too.
        try:
            directory_fd = os.open(self._root, os.O_RDONLY)
        except OSError:  # pragma: no cover - platform without directory fds
            return
        try:
            os.fsync(directory_fd)
        except OSError:  # pragma: no cover - some filesystems refuse directory fsync
            pass
        finally:
            os.close(directory_fd)

    def _close_locked(self) -> None:
        handle = self._handle
        if handle is not None:
            handle.close()
        self._handle = None
        self._fileno = None
