"""Append-only JSONL on disk, partitioned by (pool, UTC day).

Layout under the tape root (default ``state/cluster_tape``)::

    swaps/<pool>-<YYYYMMDD>.jsonl     swap, liquidity and attempt rows
    defects/<pool>-<YYYYMMDD>.jsonl   anything that must never reach the main tape
    watch/<pool>-<YYYYMMDD>.jsonl     WatchWindow open/close and poll-gap rows
    cursors.json                      last processed signature and last poll time per pool

**The day partition is chain time, not wall time.** A row's file is chosen by its ``t_event``
UTC day, so a backfill lands in the day it happened rather than the day it was fetched. The
inverted-clock finding in SWARM.md Track B is what makes this non-obvious worth stating:
ingest order ran *backwards* against chain order at Spearman -0.77 because backfill paginates
newest-first, so partitioning by ingest time would scatter one chain-hour across several files
and collapse 29 hours of chain time into one. Watch and gap rows have no chain time and are
partitioned by their own wall clock, which is what they are about.

**JSONL, one row per line, never rewritten** (PROGRAM.md §3 rule 11; memecoin symbols contain
commas by design, and this tape carries labels).

**Raw amounts are strings on the wire.** JSON numbers are f64 and lose exactness above 2**53.
A 1e9-supply 6-decimal token is 1e15 raw units, already inside one order of magnitude of that
cliff, and the pools here hold ~1e14 raw units today. The integers stay integers in memory and
become decimal strings on disk — the same rule ``shitcoims_tape.schema`` sets, followed here
rather than re-litigated.
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, TextIO

DEFAULT_TAPE_ROOT: Final[Path] = Path("state/cluster_tape")
TAPE_ROOT_ENV: Final[str] = "JOSHIBOT_CLUSTER_TAPE_DIR"

SWAPS: Final[str] = "swaps"
DEFECTS: Final[str] = "defects"
WATCH: Final[str] = "watch"

DEFAULT_DEDUPE_WINDOW: Final[int] = 100_000


class TapeWriteError(RuntimeError):
    """The tape could not be written. Fail closed: a dropped row is not recoverable."""


def default_tape_root() -> Path:
    configured = os.environ.get(TAPE_ROOT_ENV)
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_TAPE_ROOT


def _day_of(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(UTC).strftime("%Y%m%d")


class ClusterTape:
    """One tape root, many (stream, pool, day) files, all append-only.

    Handles are kept open per file and closed on :meth:`close`. Six pools across a day
    boundary is at most a couple of dozen descriptors, so no LRU is needed.
    """

    def __init__(
        self,
        root: Path | None = None,
        *,
        dedupe_window: int = DEFAULT_DEDUPE_WINDOW,
    ) -> None:
        self._root = (root if root is not None else default_tape_root()).expanduser()
        self._handles: dict[Path, TextIO] = {}
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._dedupe_window = dedupe_window
        self.rows_written = 0
        self.rows_deduped = 0
        self.per_stream: dict[str, int] = {}
        self.per_pool: dict[str, int] = {}
        self.per_pool_defects: dict[str, int] = {}

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, stream: str, pool: str, day: str) -> Path:
        return self._root / stream / f"{pool}-{day}.jsonl"

    def _handle(self, path: Path) -> TextIO:
        handle = self._handles.get(path)
        if handle is not None:
            return handle
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("a", encoding="utf-8")
        except OSError as exc:
            raise TapeWriteError(f"cannot open tape file {path}") from exc
        self._handles[path] = handle
        return handle

    def _append(self, stream: str, pool: str, day: str, payload: Mapping[str, Any]) -> bool:
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if "\n" in line:  # pragma: no cover - json.dumps escapes newlines
            raise TapeWriteError("a tape line must not contain a newline")
        handle = self._handle(self.path_for(stream, pool, day))
        handle.write(line + "\n")
        self.rows_written += 1
        self.per_stream[stream] = self.per_stream.get(stream, 0) + 1
        return True

    # -- public writes ---------------------------------------------------------------

    def write_row(self, row: Any) -> bool:
        """Append a swap / liquidity / attempt row. Returns False if already recorded.

        Dedupe is on ``(pool, signature)``: overlapping polls re-see the same signature by
        construction, and a double-counted fill corrupts every intensity estimate downstream.
        """

        payload = row.to_json()
        row_id = str(payload.get("row_id", ""))
        if row_id and row_id in self._seen:
            self._seen.move_to_end(row_id)
            self.rows_deduped += 1
            return False
        pool = str(payload["pool"])
        written = self._append(SWAPS, pool, _day_of(str(payload["t_event"])), payload)
        if row_id:
            self._seen[row_id] = None
            while len(self._seen) > self._dedupe_window:
                self._seen.popitem(last=False)
        self.per_pool[pool] = self.per_pool.get(pool, 0) + 1
        return written

    def write_defect(self, defect: Any) -> bool:
        """Append to the defect stream. A defect is never deduped away: a repeat is a signal."""

        payload = defect.to_json()
        pool = str(payload["pool"])
        anchor = payload.get("t_event") or payload["t_ingest"]
        self.per_pool_defects[pool] = self.per_pool_defects.get(pool, 0) + 1
        return self._append(DEFECTS, pool, _day_of(str(anchor)), payload)

    def write_watch(self, pool: str, payload: Mapping[str, Any], *, at: str) -> bool:
        return self._append(WATCH, pool, _day_of(at), dict(payload))

    # -- cursors ---------------------------------------------------------------------

    @property
    def cursor_path(self) -> Path:
        return self._root / "cursors.json"

    def load_cursors(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.cursor_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def save_cursors(self, cursors: Mapping[str, Mapping[str, Any]]) -> None:
        """Write via a temp file and rename, so a crash cannot leave a half-written cursor."""

        try:
            self._root.mkdir(parents=True, exist_ok=True)
            temp = self.cursor_path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(dict(cursors), indent=1, sort_keys=True), encoding="utf-8")
            temp.replace(self.cursor_path)
        except OSError as exc:
            raise TapeWriteError(f"cannot persist cursors to {self.cursor_path}") from exc

    # -- lifecycle -------------------------------------------------------------------

    def flush(self) -> None:
        for handle in self._handles.values():
            handle.flush()

    def close(self) -> None:
        """Flush, fsync every open file, then fsync the directories holding them.

        The directory fsync is what makes a *newly created* file's name durable, not just its
        bytes; without it a crash loses the whole file rather than its tail.
        """

        directories: set[Path] = set()
        for path, handle in self._handles.items():
            try:
                handle.flush()
                os.fsync(handle.fileno())
            except OSError:  # pragma: no cover - a closed/failed fd is not worth crashing on
                pass
            finally:
                handle.close()
            directories.add(path.parent)
        self._handles.clear()
        for directory in directories:
            try:
                fd = os.open(directory, os.O_RDONLY)
            except OSError:  # pragma: no cover - platform without directory fds
                continue
            try:
                os.fsync(fd)
            except OSError:  # pragma: no cover - filesystems that refuse directory fsync
                pass
            finally:
                os.close(fd)

    def __enter__(self) -> ClusterTape:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
