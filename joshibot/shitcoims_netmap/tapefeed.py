"""Read the cluster tape. Read-only, event-time, and tolerant of a file being written to.

Three rules this module exists to enforce, each earned:

**1. Two clocks, and only one of them may be joined on.** Every row carries ``t_event`` (chain
time, mandatory) and ``t_ingest`` (when the collector saw it). Backfill paginates newest-first,
so ingest order ran *backwards* against chain order at Spearman -0.77 on real data. Everything
here filters, buckets and reports on ``t_event``. ``t_ingest`` is read for exactly one purpose:
counting rows whose ingest clock precedes their event clock, which is a corruption alarm.

**2. "No flow" is not "not watching".** A pool with zero swaps in an hour is a measured zero
only if the watch ledger says the collector was polling it for that hour; outside a window the
same absence is no information at all. Presence is always evidence — a recorded swap happened —
so rows outside a window are counted, and counted *separately*, as a lower bound on activity
that licenses no statement about absence. :class:`PoolTape` keeps the two apart in the data, not
just in the prose, and the renderer cannot collapse them because the JSON has no field that
means both.

**3. The tape is being appended to while we read it.** The final line of a file may be a partial
JSON object mid-``write``. A trailing line with no terminating newline is therefore *presumed
partial* and skipped silently; a malformed line anywhere else is counted and surfaced, because
that one is a real defect rather than a race.

Watch windows are wall-clock intervals (they are about the observer) and swaps are event-time
(they are about the chain). Joining them requires a rule: a window's trailing edge is trimmed by
one poll interval, because chain time inside the last poll gap has not been asked about yet.
Without the trim, every window would claim coverage of a slice it has not yet polled and
manufacture a zero at the leading edge.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shitcoims_cluster.pools import CLUSTER_POOLS, PoolSpec
from shitcoims_cluster.tape import SWAPS, WATCH, default_tape_root

#: Row kinds the tape writes. Mirrored rather than imported as a group because the map treats
#: them differently: only ``swap`` is flow, and ``reference`` is explicitly *not* absence.
KIND_SWAP = "swap"
KIND_LIQUIDITY = "liquidity"
KIND_REFERENCE = "reference"
KIND_ATTEMPT = "attempt"

#: Meteora instructions that mean somebody's LP position changed on this pool. The fee payer of
#: such a row is a *candidate* liquidity provider — evidence, never an ownership claim.
LP_LEG_NAMES = frozenset(
    {"add_liquidity", "remove_liquidity", "remove_liquidity_by_range2", "claim_fee2"}
)

EVIDENCE_OBSERVED = "observed"
EVIDENCE_OBSERVED_ZERO = "observed_zero"
EVIDENCE_NOT_WATCHING = "not_watching"


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Interval:
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment <= self.end


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    """Union of intervals, oldest first. Overlapping watch windows must not double-count time."""

    ordered = sorted((i for i in intervals if i.seconds > 0), key=lambda i: i.start)
    merged: list[Interval] = []
    for interval in ordered:
        if merged and interval.start <= merged[-1].end:
            if interval.end > merged[-1].end:
                merged[-1] = Interval(merged[-1].start, interval.end)
            continue
        merged.append(interval)
    return merged


def subtract_intervals(base: Sequence[Interval], holes: Sequence[Interval]) -> list[Interval]:
    """``base`` minus ``holes``. A gap row means the observer was not looking; that time is not
    coverage, and zero-filling it is the failure mode the watch ledger exists to prevent."""

    result = list(base)
    for hole in merge_intervals(holes):
        carved: list[Interval] = []
        for piece in result:
            if hole.end <= piece.start or hole.start >= piece.end:
                carved.append(piece)
                continue
            if piece.start < hole.start:
                carved.append(Interval(piece.start, hole.start))
            if hole.end < piece.end:
                carved.append(Interval(hole.end, piece.end))
        result = carved
    return [i for i in result if i.seconds > 0]


def clip_intervals(intervals: Sequence[Interval], window: Interval) -> list[Interval]:
    clipped = [
        Interval(max(i.start, window.start), min(i.end, window.end))
        for i in intervals
        if i.end > window.start and i.start < window.end
    ]
    return [i for i in clipped if i.seconds > 0]


def covered_seconds(intervals: Sequence[Interval]) -> float:
    return sum(i.seconds for i in merge_intervals(intervals))


@dataclass(slots=True)
class ReadStats:
    """What the reader had to tolerate. Surfaced, never swallowed."""

    files_read: int = 0
    rows: int = 0
    partial_final_lines: int = 0
    malformed_lines: int = 0
    unreadable_files: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "files_read": self.files_read,
            "rows": self.rows,
            "partial_final_lines": self.partial_final_lines,
            "malformed_lines": self.malformed_lines,
            "unreadable_files": list(self.unreadable_files),
        }


def read_jsonl(path: Path, stats: ReadStats) -> Iterator[dict[str, Any]]:
    """Yield rows from one append-only JSONL file that may be mid-write.

    The last line is presumed partial when the file does not end in a newline: the writer holds
    the handle and a row is written as ``line + "\\n"``, so an unterminated tail is a race, not
    corruption. Anything else that fails to parse is counted as malformed and reported.
    """

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        stats.unreadable_files.append(str(path))
        return
    stats.files_read += 1
    if not text:
        return
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    elif lines:
        stats.partial_final_lines += 1
        lines.pop()
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            stats.malformed_lines += 1
            continue
        if isinstance(row, dict):
            stats.rows += 1
            yield row


def _day_keys(window: Interval) -> list[str]:
    """UTC day partitions a window can touch, inclusive of both ends."""

    days: list[str] = []
    cursor = window.start.astimezone(UTC).date()
    last = window.end.astimezone(UTC).date()
    while cursor <= last:
        days.append(cursor.strftime("%Y%m%d"))
        cursor += timedelta(days=1)
    return days


@dataclass(slots=True)
class PoolTape:
    """One pool's slice of the tape over one event-time window."""

    pool: str
    label: str
    window: Interval

    swaps: int = 0
    liquidity: int = 0
    references: int = 0
    attempts: int = 0
    unattributed_swaps: int = 0
    multi_leg_swaps: int = 0
    ingest_before_event_rows: int = 0

    # Split by whether the collector was demonstrably watching at that chain instant.
    swaps_watched: int = 0
    attempts_watched: int = 0
    watched_seconds: float = 0.0
    watch_intervals: list[Interval] = field(default_factory=list)
    watch_windows_open: int = 0
    gap_seconds: float = 0.0

    first_t_event: str | None = None
    last_t_event: str | None = None
    last_swap_t_event: str | None = None

    #: Gross value that crossed the edge, per mint, in token units: one contribution per swap,
    #: taken from the leg that LEFT the pool. Summing both legs would double-count the notional.
    gross_out_units: dict[str, float] = field(default_factory=dict)
    #: Net change of each vault **from swaps only**, in token units. This is the ΔQ that moves
    #: the potential: `ΔV = ΔQ/C`.
    net_delta_units: dict[str, float] = field(default_factory=dict)
    #: Net change from liquidity rows — adds, withdrawals, fee claims. Deliberately kept apart:
    #: an LP deposit raises `Q` **and** `C` together and moves the potential by *nothing*, so
    #: folding it into ΔQ would manufacture a price displacement that never happened.
    liquidity_delta_units: dict[str, float] = field(default_factory=dict)
    decimals: dict[str, int] = field(default_factory=dict)

    #: Latest observed vault balances and the chain time they are from. A reserve reading, free,
    #: from any row whose vaults appear — including zero-delta reference rows.
    last_reserves_units: dict[str, float] = field(default_factory=dict)
    last_reserves_t_event: str | None = None
    last_reserves_slot: int | None = None

    attempt_errors: Counter[str] = field(default_factory=Counter)
    lp_candidates: Counter[str] = field(default_factory=Counter)

    @property
    def evidence(self) -> str:
        """What the tape licenses about this edge's flow over the window.

        ``not_watching`` — no watched seconds: absence here is not a zero, it is silence.
        ``observed_zero`` — watched, and nothing crossed: a real measured zero.
        ``observed`` — watched, and flow crossed.
        """

        if self.watched_seconds <= 0:
            return EVIDENCE_NOT_WATCHING
        return EVIDENCE_OBSERVED if self.swaps_watched > 0 else EVIDENCE_OBSERVED_ZERO

    @property
    def swaps_per_hour(self) -> float | None:
        """Flow intensity, defined only inside watch coverage. ``None`` means *not measured*."""

        if self.watched_seconds <= 0:
            return None
        return self.swaps_watched * 3600.0 / self.watched_seconds

    @property
    def swaps_unwatched(self) -> int:
        return self.swaps - self.swaps_watched

    @property
    def failed_attempt_rate(self) -> float | None:
        """Failed / (failed + landed), over transactions that meant to touch this pool.

        ``reference`` rows are excluded from the denominator on purpose: a router that named the
        pool in a lookup table and filled elsewhere never intended a fill here, and counting
        those would push every rate toward zero. Both counts are in the JSON so the reader can
        take the other convention if they want it.
        """

        landed = self.swaps + self.liquidity
        total = landed + self.attempts
        return self.attempts / total if total else None

    def to_json(self) -> dict[str, Any]:
        return {
            "window": {
                "from_t_event": self.window.start.isoformat(),
                "to_t_event": self.window.end.isoformat(),
                "hours": round(self.window.seconds / 3600.0, 4),
                "clock": "event_time (chain blockTime); ingest time is never joined on",
            },
            "counts": {
                "swaps": self.swaps,
                "liquidity": self.liquidity,
                "references": self.references,
                "attempts": self.attempts,
                "unattributed_swaps": self.unattributed_swaps,
                "multi_leg_swaps": self.multi_leg_swaps,
            },
            "flow": {
                "evidence": self.evidence,
                "watched_seconds": round(self.watched_seconds, 1),
                "watch_windows_open": self.watch_windows_open,
                "gap_seconds": round(self.gap_seconds, 1),
                "swaps_watched": self.swaps_watched,
                "swaps_per_hour": (
                    None if self.swaps_per_hour is None else round(self.swaps_per_hour, 3)
                ),
                "swaps_unwatched": self.swaps_unwatched,
                "unwatched_note": (
                    "swaps recorded outside any watch window: evidence of flow, never of absence"
                ),
                "last_swap_t_event": self.last_swap_t_event,
            },
            "attempts": {
                "attempts": self.attempts,
                "attempts_watched": self.attempts_watched,
                "landed": self.swaps + self.liquidity,
                "failed_attempt_rate": (
                    None if self.failed_attempt_rate is None else round(self.failed_attempt_rate, 4)
                ),
                "denominator": "attempts + swaps + liquidity (references excluded)",
                "top_errors": [
                    {"error": err, "count": n} for err, n in self.attempt_errors.most_common(3)
                ],
            },
            "charge": {
                "gross_out_units": {m: round(v, 6) for m, v in self.gross_out_units.items()},
                "net_delta_units": {m: round(v, 6) for m, v in self.net_delta_units.items()},
                "net_delta_note": (
                    "ΔQ per vault from SWAPS ONLY, in token units — the charge injection that "
                    "displaces the potential"
                ),
                "liquidity_delta_units": {
                    m: round(v, 6) for m, v in self.liquidity_delta_units.items()
                },
                "liquidity_delta_note": (
                    "vault changes from LP adds/withdrawals/fee claims: these change C, not V, "
                    "and are excluded from ΔQ on purpose"
                ),
                "last_reserves_units": {
                    m: round(v, 6) for m, v in self.last_reserves_units.items()
                },
                "last_reserves_t_event": self.last_reserves_t_event,
                "last_reserves_slot": self.last_reserves_slot,
            },
            "clock_alarms": {"rows_with_ingest_before_event": self.ingest_before_event_rows},
            "lp_candidates_from_tape": [
                {"wallet": w, "liquidity_rows": n} for w, n in self.lp_candidates.most_common(5)
            ],
            "first_t_event": self.first_t_event,
            "last_t_event": self.last_t_event,
        }


@dataclass(slots=True)
class TapeSnapshot:
    root: str
    window: Interval
    pools: dict[str, PoolTape]
    read: ReadStats
    now: datetime


def _units(raw: Any, decimals: int) -> float:
    """Raw integer string -> token units. Raw amounts are strings on the wire, by design."""

    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return 0.0
    return value / (10.0**decimals)


def _read_watch(
    root: Path, spec: PoolSpec, window: Interval, now: datetime, stats: ReadStats
) -> tuple[list[Interval], float, int]:
    """Coverage intervals for one pool, gaps already carved out.

    Returns ``(intervals, gap_seconds, open_windows)``. Watch rows are partitioned by the wall
    clock they are about, which is why the day keys here are the observer's days.
    """

    opens: dict[str, tuple[datetime, datetime, float]] = {}
    closes: dict[str, datetime] = {}
    gaps: list[Interval] = []
    # A window can have opened before the analysis window began, so look one day further back.
    days = _day_keys(Interval(window.start - timedelta(days=1), window.end))
    for day in days:
        path = root / WATCH / f"{spec.address}-{day}.jsonl"
        if not path.exists():
            continue
        for row in read_jsonl(path, stats):
            kind = row.get("kind")
            if kind == "gap":
                start, end = _parse_iso(row.get("started_at")), _parse_iso(row.get("ended_at"))
                if start and end:
                    gaps.append(Interval(start, end))
                continue
            payload = row.get("window")
            if not isinstance(payload, dict):
                continue
            opened = _parse_iso(payload.get("opened_at"))
            if opened is None:
                continue
            key = payload["opened_at"]
            if kind == "watch_open":
                deadline = _parse_iso(payload.get("deadline")) or now
                interval_seconds = row.get("poll_interval_seconds")
                poll = float(interval_seconds) if isinstance(interval_seconds, (int, float)) else 0.0
                opens[key] = (opened, deadline, poll)
            elif kind == "watch_close":
                closed = _parse_iso(payload.get("closed_at"))
                if closed is not None:
                    closes[key] = closed

    intervals: list[Interval] = []
    still_open = 0
    for key, (opened, deadline, poll) in opens.items():
        closed = closes.get(key)
        if closed is None:
            still_open += 1
            end = min(now, deadline)
        else:
            end = closed
        # Trim the trailing poll gap: chain time newer than the last poll has not been asked
        # about, so claiming it as coverage would fabricate a zero at the leading edge.
        end = end - timedelta(seconds=poll)
        if end > opened:
            intervals.append(Interval(opened, end))

    covered = subtract_intervals(merge_intervals(intervals), gaps)
    clipped_gaps = clip_intervals(merge_intervals(gaps), window)
    return clip_intervals(covered, window), covered_seconds(clipped_gaps), still_open


def read_tape(
    *,
    root: Path | None = None,
    window_hours: float = 24.0,
    now: datetime | None = None,
    pools: Sequence[PoolSpec] = CLUSTER_POOLS,
) -> TapeSnapshot:
    """Aggregate the tape for every pool over the last ``window_hours`` of **event** time."""

    tape_root = (root if root is not None else default_tape_root()).expanduser()
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    window = Interval(moment - timedelta(hours=window_hours), moment)
    stats = ReadStats()
    out: dict[str, PoolTape] = {}

    for spec in pools:
        pool_tape = PoolTape(pool=spec.address, label=spec.label, window=window)
        intervals, gap_seconds, still_open = _read_watch(tape_root, spec, window, moment, stats)
        pool_tape.watch_intervals = intervals
        pool_tape.watched_seconds = covered_seconds(intervals)
        pool_tape.watch_windows_open = still_open
        pool_tape.gap_seconds = gap_seconds

        for day in _day_keys(window):
            path = tape_root / SWAPS / f"{spec.address}-{day}.jsonl"
            if not path.exists():
                continue
            for row in read_jsonl(path, stats):
                _absorb(pool_tape, row, window)
        out[spec.address] = pool_tape

    return TapeSnapshot(
        root=str(tape_root),
        window=window,
        pools=out,
        read=stats,
        now=moment,
    )


def _absorb(pool_tape: PoolTape, row: dict[str, Any], window: Interval) -> None:
    """Fold one tape row into the pool's aggregate, on event time only."""

    t_event_raw = row.get("t_event")
    event = _parse_iso(t_event_raw)
    if event is None or not window.contains(event):
        return
    t_event = str(t_event_raw)
    ingest = _parse_iso(row.get("t_ingest"))
    if ingest is not None and ingest < event:
        pool_tape.ingest_before_event_rows += 1

    if pool_tape.first_t_event is None or t_event < pool_tape.first_t_event:
        pool_tape.first_t_event = t_event
    if pool_tape.last_t_event is None or t_event > pool_tape.last_t_event:
        pool_tape.last_t_event = t_event

    watched = any(i.contains(event) for i in pool_tape.watch_intervals)
    kind = row.get("kind")

    if kind == KIND_ATTEMPT:
        pool_tape.attempts += 1
        pool_tape.attempts_watched += int(watched)
        pool_tape.attempt_errors[str(row.get("error", ""))[:120]] += 1
        return

    reserves = row.get("reserves")
    raw_vaults = reserves.get("vaults") if isinstance(reserves, dict) else None
    vaults: list[Any] = raw_vaults if isinstance(raw_vaults, list) else []
    balances: dict[str, float] = {}
    for vault in vaults:
        if not isinstance(vault, dict):
            continue
        mint = str(vault.get("mint", ""))
        if not mint:
            continue
        decimals = int(vault.get("decimals", 0) or 0)
        pool_tape.decimals[mint] = decimals
        balances[mint] = _units(vault.get("post_raw", "0"), decimals)
        delta = _units(vault.get("delta_raw", "0"), decimals)
        if delta:
            # Swap flow moves the potential (ΔV = ΔQ/C); an LP add moves Q and C together and
            # moves the potential by nothing. Two different books, kept apart.
            book = (
                pool_tape.net_delta_units
                if kind == KIND_SWAP
                else pool_tape.liquidity_delta_units
            )
            book[mint] = book.get(mint, 0.0) + delta

    if balances and (
        pool_tape.last_reserves_t_event is None or t_event >= pool_tape.last_reserves_t_event
    ):
        pool_tape.last_reserves_units = balances
        pool_tape.last_reserves_t_event = t_event
        chain = row.get("chain")
        slot = chain.get("slot") if isinstance(chain, dict) else None
        pool_tape.last_reserves_slot = int(slot) if isinstance(slot, int) else None

    if kind == KIND_SWAP:
        pool_tape.swaps += 1
        pool_tape.swaps_watched += int(watched)
        if row.get("counterparty") is None:
            pool_tape.unattributed_swaps += 1
        if int(row.get("swap_legs", 0) or 0) > 1:
            pool_tape.multi_leg_swaps += 1
        if pool_tape.last_swap_t_event is None or t_event > pool_tape.last_swap_t_event:
            pool_tape.last_swap_t_event = t_event
        out_mint = row.get("token_out_mint")
        if isinstance(out_mint, str) and out_mint:
            amount = _units(row.get("token_out_raw", "0"), pool_tape.decimals.get(out_mint, 0))
            pool_tape.gross_out_units[out_mint] = (
                pool_tape.gross_out_units.get(out_mint, 0.0) + amount
            )
    elif kind == KIND_LIQUIDITY:
        pool_tape.liquidity += 1
        legs = row.get("leg_names")
        payer = row.get("fee_payer")
        touched_lp = isinstance(legs, list) and any(str(name) in LP_LEG_NAMES for name in legs)
        if isinstance(payer, str) and payer and touched_lp:
            pool_tape.lp_candidates[payer] += 1
    elif kind == KIND_REFERENCE:
        pool_tape.references += 1
