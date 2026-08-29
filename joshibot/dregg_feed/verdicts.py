"""mint -> birth verdict, from the screen's scores JSONL — the feed's differentiator.

The screen scores every launch at birth (dregg_screen.live, scores/<day>.jsonl).
An alert that says "trending" is pump's frontend; an alert that says "trending — and
the screen said KNOWN_CREW at birth" is ours. Lookups cover the trailing N days of
day files (default 2, per the product decision); a mint absent from that window is
honestly "born before the screen / unscored", never guessed.

Day files are append-only, so the index reads INCREMENTALLY: per file it remembers the
byte offset after the last complete line and parses only what grew. A truncated file
(rotation, copy-back) rebuilds from zero. The last line of a live file may be a partial
write; the cursor never advances past the final newline, so a half-line is simply read
again next time, whole.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(slots=True)
class _Cursor:
    offset: int = 0
    verdicts: dict[str, str] = field(default_factory=dict)


class VerdictIndex:
    def __init__(self, scores_dir: Path, *, days: int = 2):
        self.scores_dir = scores_dir
        self.days = days
        self._cursors: dict[str, _Cursor] = {}

    def _day_names(self, now: float) -> list[str]:
        today = datetime.fromtimestamp(now, UTC).date()
        return [(today - timedelta(days=n)).isoformat() for n in range(self.days + 1)]

    def _refresh(self, day: str) -> _Cursor | None:
        path = self.scores_dir / f"{day}.jsonl"
        try:
            size = path.stat().st_size
        except OSError:
            self._cursors.pop(day, None)
            return None
        cursor = self._cursors.setdefault(day, _Cursor())
        if size < cursor.offset:  # truncated/replaced: our offset points at nothing
            self._cursors[day] = cursor = _Cursor()
        if size == cursor.offset:
            return cursor
        with path.open("rb") as fh:
            fh.seek(cursor.offset)
            chunk = fh.read(size - cursor.offset)
        last_newline = chunk.rfind(b"\n")
        if last_newline < 0:
            return cursor  # only a partial line so far; read it whole next time
        for line in chunk[: last_newline + 1].splitlines():
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            mint = row.get("mint")
            verdict = row.get("verdict")
            if isinstance(mint, str) and isinstance(verdict, str):
                cursor.verdicts[mint] = verdict
        cursor.offset += last_newline + 1
        return cursor

    def verdict(self, mint: str, now: float) -> str | None:
        days = self._day_names(now)
        for stale in [d for d in self._cursors if d not in days]:
            del self._cursors[stale]
        found: str | None = None
        for day in reversed(days):  # oldest first, so the newest day's row wins
            cursor = self._refresh(day)
            if cursor is not None and mint in cursor.verdicts:
                found = cursor.verdicts[mint]
        return found
