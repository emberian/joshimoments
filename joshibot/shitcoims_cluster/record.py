"""The collector. ``uv run python -m shitcoims_cluster.record --minutes N``

Poll-based on purpose. A websocket subscription is the obvious v1 and it is the wrong one
here: ``transactionNotification`` carries a slot but **no block time**, which is precisely the
bug that left 169 of 169 live rows with no event clock (SWARM.md, Track B). Polling
``getSignaturesForAddress`` gets the signature, the slot, the block time, the confirmation
status *and* the error in one response, which is what lets this recorder make the event clock
mandatory rather than best-effort.

The loop, per pool, per tick:

1. ``getSignaturesForAddress`` newer than the stored cursor (paginated with ``before`` when a
   page fills, so a burst larger than one page is not silently truncated).
2. Entries with a non-null ``err`` become :class:`~shitcoims_cluster.parse.Attempt` rows
   straight from the listing — **no ``getTransaction``**, so they are free. On the busiest
   cluster pool that is ~60% of recent transactions.
3. The rest are fetched in batched ``getTransaction`` calls, 25 per call, with a sleep between
   batches and exponential backoff with jitter on 429.
4. Each result becomes a row or a defect. A row without a block time is a defect, always.
5. The cursor advances to the newest signature only after the batch is written.

Gentleness knobs are all flags, and the defaults are the conservative ones.
"""

from __future__ import annotations

import argparse
import contextlib
import signal
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from shitcoims_cluster.parse import (
    Attempt,
    ClusterSwap,
    Defect,
    RowKind,
    listing_is_usable,
    parse_failed_signature,
    parse_transaction,
    sort_listing,
    utc_iso,
)
from shitcoims_cluster.pools import CLUSTER_POOLS, PoolSpec
from shitcoims_cluster.rpc import MAX_SIGNATURE_LIMIT, HeliusRpc, RpcError
from shitcoims_cluster.tape import ClusterTape
from shitcoims_cluster.watch import DEFAULT_GAP_FACTOR, PoolWatch
from shitcoims_tape.schema import WatchClose

DEFAULT_POLL_SECONDS = 20.0
DEFAULT_BACKFILL = 2000
DEFAULT_TX_BATCH = 25
DEFAULT_BATCH_SLEEP = 0.25
#: Watches are opened with a real clock deadline; a run longer than this re-opens them.
WATCH_HORIZON = timedelta(days=1)


@dataclass
class PoolStats:
    swaps: int = 0
    liquidity: int = 0
    references: int = 0
    attempts: int = 0
    defects: int = 0
    signatures_seen: int = 0
    transactions_fetched: int = 0
    deduped: int = 0
    unattributed: int = 0
    multi_leg: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "swaps": self.swaps,
            "liquidity": self.liquidity,
            "references": self.references,
            "attempts": self.attempts,
            "defects": self.defects,
            "signatures_seen": self.signatures_seen,
            "transactions_fetched": self.transactions_fetched,
            "deduped": self.deduped,
            "unattributed_swaps": self.unattributed,
            "multi_leg_swaps": self.multi_leg,
        }


@dataclass
class Collector:
    """The recording loop, with its clock and its RPC injected so tests need no network."""

    rpc: Any
    tape: ClusterTape
    pools: Sequence[PoolSpec] = tuple(CLUSTER_POOLS)
    poll_seconds: float = DEFAULT_POLL_SECONDS
    backfill: int = DEFAULT_BACKFILL
    tx_batch: int = DEFAULT_TX_BATCH
    batch_sleep: float = DEFAULT_BATCH_SLEEP
    gap_factor: float = DEFAULT_GAP_FACTOR
    clock: Any = lambda: datetime.now(UTC)
    sleep: Any = time.sleep
    log: Any = lambda message: print(message, file=sys.stderr, flush=True)

    watches: dict[str, PoolWatch] = field(default_factory=dict)
    stats: dict[str, PoolStats] = field(default_factory=dict)
    cursors: dict[str, dict[str, Any]] = field(default_factory=dict)
    stopping: bool = False

    # -- setup -----------------------------------------------------------------------

    def open_watches(self) -> None:
        now = self.clock()
        self.cursors = self.tape.load_cursors()
        for spec in self.pools:
            state = self.cursors.get(spec.address, {})
            watch = PoolWatch(
                pool=spec.address,
                opened_at=now,
                deadline=now + WATCH_HORIZON,
                poll_interval=self.poll_seconds,
                gap_factor=self.gap_factor,
            )
            self.watches[spec.address] = watch
            self.stats.setdefault(spec.address, PoolStats())
            self.tape.write_watch(spec.address, watch.open_row(), at=utc_iso(now))
            last_poll = state.get("last_poll_at")
            if isinstance(last_poll, str):
                gap = watch.seed_from_cursor(datetime.fromisoformat(last_poll), now)
                if gap is not None:
                    self.tape.write_watch(spec.address, gap.to_json(), at=utc_iso(now))

    def close_watches(self, reason: WatchClose) -> None:
        now = self.clock()
        for spec in self.pools:
            watch = self.watches.get(spec.address)
            if watch is None:
                continue
            self.tape.write_watch(spec.address, watch.close(now, reason), at=utc_iso(now))

    # -- fetching --------------------------------------------------------------------

    def _listing(self, spec: PoolSpec) -> list[Mapping[str, Any]]:
        """Every signature newer than the cursor, oldest-first, paginated when a page fills."""

        state = self.cursors.get(spec.address, {})
        until = state.get("last_signature")
        collected: list[Mapping[str, Any]] = []
        before: str | None = None
        # A first run has no cursor and takes the backfill; an incremental run walks back to
        # `until` and stops. The cap bounds both so one busy pool cannot starve the others.
        cap = self.backfill if not isinstance(until, str) else MAX_SIGNATURE_LIMIT * 10
        while len(collected) < cap:
            page_limit = min(MAX_SIGNATURE_LIMIT, cap - len(collected))
            page = self.rpc.signatures_for_address(
                spec.address,
                limit=page_limit,
                before=before,
                until=until if isinstance(until, str) else None,
            )
            if not page:
                break
            collected.extend(page)
            if len(page) < page_limit:
                break
            before = str(page[-1].get("signature"))
            self.sleep(self.batch_sleep)
        return collected

    def poll_pool(self, spec: PoolSpec) -> None:
        now = self.clock()
        watch = self.watches[spec.address]
        stats = self.stats[spec.address]
        try:
            listing = self._listing(spec)
        except RpcError as exc:
            gap = watch.note_failure(now, type(exc).__name__)
            self.tape.write_watch(spec.address, gap.to_json(), at=utc_iso(now))
            self.log(f"[{spec.label}] poll failed: {exc}")
            return

        poll_gap = watch.note_poll(now)
        if poll_gap is not None:
            self.tape.write_watch(spec.address, poll_gap.to_json(), at=utc_iso(now))

        if not listing:
            return
        stats.signatures_seen += len(listing)
        ordered = sort_listing(listing)
        cursor_signature = str(ordered[-1].get("signature"))

        pending: list[Mapping[str, Any]] = []
        for entry in ordered:
            if not listing_is_usable(entry):
                # No block time in the listing at all: it cannot become a row, and it is not
                # allowed to become one silently either.
                self.tape.write_defect(
                    parse_failed_signature(entry, spec, t_ingest=now, cursor=cursor_signature)
                )
                stats.defects += 1
                continue
            if entry.get("err") is not None:
                attempt = parse_failed_signature(entry, spec, t_ingest=now, cursor=cursor_signature)
                self._emit(spec, attempt, stats)
                continue
            pending.append(entry)

        for start in range(0, len(pending), self.tx_batch):
            chunk = pending[start : start + self.tx_batch]
            signatures = [str(e["signature"]) for e in chunk]
            fetch_at = self.clock()
            try:
                results = self.rpc.transactions(signatures)
            except RpcError as exc:
                failure = watch.note_failure(fetch_at, type(exc).__name__)
                self.tape.write_watch(spec.address, failure.to_json(), at=utc_iso(fetch_at))
                self.log(f"[{spec.label}] getTransaction batch failed: {exc}")
                return
            stats.transactions_fetched += len(chunk)
            for entry, tx in zip(chunk, results, strict=True):
                row = parse_transaction(
                    tx,
                    spec,
                    signature=str(entry["signature"]),
                    t_ingest=fetch_at,
                    listing_block_time=entry.get("blockTime"),
                    confirmation_status=entry.get("confirmationStatus"),
                    cursor=cursor_signature,
                )
                self._emit(spec, row, stats)
            if start + self.tx_batch < len(pending):
                self.sleep(self.batch_sleep)

        self.cursors.setdefault(spec.address, {})
        self.cursors[spec.address]["last_signature"] = cursor_signature
        self.cursors[spec.address]["last_poll_at"] = utc_iso(now)
        self.cursors[spec.address]["label"] = spec.label

    def _emit(
        self, spec: PoolSpec, row: ClusterSwap | Attempt | Defect, stats: PoolStats
    ) -> None:
        if isinstance(row, Defect):
            self.tape.write_defect(row)
            stats.defects += 1
            return
        written = self.tape.write_row(row)
        if not written:
            stats.deduped += 1
            return
        if isinstance(row, Attempt):
            stats.attempts += 1
            return
        if row.row_kind == RowKind.SWAP:
            stats.swaps += 1
            if row.counterparty is None:
                stats.unattributed += 1
            if row.swap_legs > 1:
                stats.multi_leg += 1
        elif row.row_kind == RowKind.LIQUIDITY:
            stats.liquidity += 1
        else:
            stats.references += 1

    # -- loop ------------------------------------------------------------------------

    def tick(self) -> None:
        for spec in self.pools:
            if self.stopping:
                return
            self.poll_pool(spec)

    def run(self, *, minutes: float | None, once: bool = False) -> None:
        started = self.clock()
        deadline = None if minutes is None else started + timedelta(minutes=minutes)
        self.open_watches()
        reason = WatchClose.DEADLINE
        try:
            while True:
                self.tick()
                self.tape.flush()
                self.tape.save_cursors(self.cursors)
                if once or self.stopping:
                    if self.stopping:
                        reason = WatchClose.OPERATOR
                    break
                now = self.clock()
                if deadline is not None and now >= deadline:
                    break
                remaining = self.poll_seconds
                if deadline is not None:
                    remaining = min(remaining, (deadline - now).total_seconds())
                if remaining > 0:
                    self.sleep(remaining)
        except KeyboardInterrupt:  # pragma: no cover - interactive path
            reason = WatchClose.OPERATOR
        finally:
            self.close_watches(reason)
            self.tape.save_cursors(self.cursors)
            self.tape.close()

    # -- reporting -------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        return {
            "tape_root": str(self.tape.root),
            "rows_written": self.tape.rows_written,
            "rows_deduped": self.tape.rows_deduped,
            "per_stream": dict(self.tape.per_stream),
            "pools": {
                spec.label: {
                    "address": spec.address,
                    "dex": spec.dex,
                    **self.stats.get(spec.address, PoolStats()).to_json(),
                    "gaps": len(self.watches[spec.address].gaps)
                    if spec.address in self.watches
                    else 0,
                }
                for spec in self.pools
            },
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m shitcoims_cluster.record",
        description="Record every swap on the four-token cluster's pools, at slot resolution.",
    )
    parser.add_argument(
        "--minutes",
        type=float,
        default=None,
        help="stop after this many minutes (default: run until interrupted)",
    )
    parser.add_argument("--once", action="store_true", help="one pass over every pool, then exit")
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument(
        "--backfill",
        type=int,
        default=DEFAULT_BACKFILL,
        help=f"signatures to walk back on a pool's first run (default {DEFAULT_BACKFILL})",
    )
    parser.add_argument("--tx-batch", type=int, default=DEFAULT_TX_BATCH)
    parser.add_argument("--batch-sleep", type=float, default=DEFAULT_BATCH_SLEEP)
    parser.add_argument("--gap-factor", type=float, default=DEFAULT_GAP_FACTOR)
    parser.add_argument("--tape-dir", type=Path, default=None)
    parser.add_argument("--key-file", type=Path, default=None)
    parser.add_argument("--commitment", default="confirmed", choices=("confirmed", "finalized"))
    parser.add_argument(
        "--pool", action="append", default=None, help="restrict to one pool address or label; repeatable"
    )
    return parser


def _select(names: Sequence[str] | None) -> tuple[PoolSpec, ...]:
    if not names:
        return tuple(CLUSTER_POOLS)
    wanted = set(names)
    chosen = tuple(p for p in CLUSTER_POOLS if p.address in wanted or p.label in wanted)
    if not chosen:
        raise SystemExit(f"no cluster pool matches {sorted(wanted)}")
    return chosen


def main(argv: Sequence[str] | None = None) -> int:
    import json

    args = build_parser().parse_args(argv)
    pools = _select(args.pool)
    tape = ClusterTape(args.tape_dir)
    rpc = HeliusRpc(key_file=args.key_file, commitment=args.commitment)
    collector = Collector(
        rpc=rpc,
        tape=tape,
        pools=pools,
        poll_seconds=args.poll_seconds,
        backfill=max(0, args.backfill),
        tx_batch=max(1, args.tx_batch),
        batch_sleep=max(0.0, args.batch_sleep),
        gap_factor=args.gap_factor,
    )

    def _stop(signum: int, frame: Any) -> None:  # pragma: no cover - signal path
        collector.stopping = True
        collector.log("stopping after the current pass")

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError):  # not the main thread
            signal.signal(sig, _stop)

    try:
        collector.run(minutes=args.minutes, once=args.once)
    finally:
        rpc.close()
    summary = collector.summary()
    summary["rpc_calls"] = getattr(rpc, "calls", None)
    summary["rate_limit_waits"] = getattr(rpc, "rate_limit_waits", None)
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
