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
import os
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
#: One liveness row per pool per this many seconds, written whether or not the pool traded.
#:
#: Without it a healthy recorder watching a dead-quiet pool writes NOTHING, which is
#: byte-for-byte what a wedged process writes — the exact confusion ``watch.py`` exists to
#: prevent, left open on the only stream that has to survive a laptop sleeping. 11 pools at
#: 60s is ~16k rows/day against a 100 MB/day tape, so the cost is noise and the information is
#: the difference between "zero flow" and "no observer".
DEFAULT_HEARTBEAT_SECONDS = 60.0
#: Vault addresses are swept every Nth tick rather than every tick. See ``Collector.watch_set``.
DEFAULT_VAULT_POLL_FACTOR = 6


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

    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS
    vault_poll_factor: int = DEFAULT_VAULT_POLL_FACTOR

    watches: dict[str, PoolWatch] = field(default_factory=dict)
    stats: dict[str, PoolStats] = field(default_factory=dict)
    cursors: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Pool address -> the addresses whose signatures are swept for it. See :meth:`watch_set`.
    vaults: dict[str, tuple[str, ...]] = field(default_factory=dict)
    stopping: bool = False
    ticks: int = 0
    last_heartbeat: dict[str, datetime] = field(default_factory=dict)

    # -- setup -----------------------------------------------------------------------

    def resolve_vaults(self) -> None:
        """Ask the chain which token accounts each pool owns, and watch those too.

        ``getSignaturesForAddress`` on the *pool* address returns transactions that name the
        pool. A transaction can move a vault without naming the pool — a direct SPL transfer
        into or out of a vault does exactly that, and so does any program that holds the vault
        by address. The recorder's own v1 report closed that hole *empirically* (no such
        transaction was observed) and not *structurally*, which is the weaker claim: it says
        the hole was not exercised in one window, not that it cannot be.

        Watching the vaults closes it structurally. Discovery is by ``owner``, matching
        ``pools.py``'s rule that a pool's vaults are exactly the token accounts it owns, so
        there is still no hard-coded vault table to drift.

        A resolution failure is not fatal: the pool address alone is what v1 watched, so the
        recorder degrades to v1 behaviour rather than refusing to run — but it says so.
        """

        for spec in self.pools:
            self.touch("resolving_vaults", spec)
            try:
                accounts = self.rpc.token_accounts_by_owner(spec.address)
            except Exception as exc:
                self.log(f"[{spec.label}] vault discovery failed ({type(exc).__name__}); "
                         "watching the pool address only")
                self.vaults[spec.address] = ()
                continue
            found = tuple(str(a["account"]) for a in accounts if a.get("account"))
            self.vaults[spec.address] = found
            observed = frozenset(str(a["mint"]) for a in accounts if a.get("mint"))
            mismatch = spec.mint_mismatch(observed)
            if mismatch is not None:
                self.log(f"[{spec.label}] WARNING vault discovery: {mismatch}")
            self.log(f"[{spec.label}] watching {len(found) + 1} addresses "
                     f"(pool + {len(found)} vault(s))")

    def watch_set(self, spec: PoolSpec, *, include_vaults: bool) -> tuple[str, ...]:
        """The addresses swept on this tick: always the pool, periodically its vaults.

        Vaults are swept every ``vault_poll_factor`` ticks rather than every tick. This is the
        only credit-consuming collector in the tree and a vault sweep is a listing call per
        vault per pool; at the default 20s tick that would be ~95k extra calls/day for a hole
        that has never been observed to fire. Every sweep is cursor-based, so a slower cadence
        costs latency on such a transaction and never costs the transaction itself.
        """

        vaults = self.vaults.get(spec.address, ())
        return (spec.address, *vaults) if include_vaults else (spec.address,)

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

    def renew_watches(self, now: datetime) -> None:
        """Close and re-open any window that has reached its deadline.

        The module constant :data:`WATCH_HORIZON` always documented this ("a run longer than
        this re-opens them") and nothing implemented it, so a daemon-mode run silently emitted
        a ``watch_close`` whose ``closed_at`` was days past its own ``deadline``.
        """

        for spec in self.pools:
            watch = self.watches.get(spec.address)
            if watch is None or now < watch.deadline:
                continue
            self.tape.write_watch(
                spec.address, watch.close(now, WatchClose.DEADLINE), at=utc_iso(now)
            )
            watch.renew(now, WATCH_HORIZON)
            self.tape.write_watch(spec.address, watch.open_row(), at=utc_iso(now))

    def close_watches(self, reason: WatchClose) -> None:
        now = self.clock()
        for spec in self.pools:
            watch = self.watches.get(spec.address)
            if watch is None:
                continue
            self.tape.write_watch(spec.address, watch.close(now, reason), at=utc_iso(now))

    # -- fetching --------------------------------------------------------------------

    def _listing(self, spec: PoolSpec, address: str) -> list[Mapping[str, Any]]:
        """Every signature newer than ``address``'s cursor, oldest-first, paginated."""

        until = self._cursor_for(spec, address)
        collected: list[Mapping[str, Any]] = []
        before: str | None = None
        # A first run has no cursor and takes the backfill; an incremental run walks back to
        # `until` and stops. The cap bounds both so one busy pool cannot starve the others.
        cap = self.backfill if not isinstance(until, str) else MAX_SIGNATURE_LIMIT * 10
        while len(collected) < cap:
            page_limit = min(MAX_SIGNATURE_LIMIT, cap - len(collected))
            page = self.rpc.signatures_for_address(
                address,
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
            # A pool resuming from a day-old cursor paginates for a while; stamp liveness on
            # each page so the supervisor sees work rather than silence.
            self.touch("listing", spec)
            self.sleep(self.batch_sleep)
        return collected

    def _cursor_for(self, spec: PoolSpec, address: str) -> str | None:
        state = self.cursors.get(spec.address, {})
        if address == spec.address:
            value = state.get("last_signature")
        else:
            value = (state.get("vault_cursors") or {}).get(address)
        return value if isinstance(value, str) else None

    def _set_cursor(self, spec: PoolSpec, address: str, signature: str) -> None:
        state = self.cursors.setdefault(spec.address, {})
        if address == spec.address:
            state["last_signature"] = signature
        else:
            state.setdefault("vault_cursors", {})[address] = signature

    def touch(self, phase: str, spec: PoolSpec | None = None) -> None:
        """Stamp process liveness. Called on work, not on completion — see ClusterTape."""

        self.tape.touch_heartbeat(
            {
                "t": utc_iso(self.clock()),
                "pid": os.getpid(),
                "phase": phase,
                "pool": None if spec is None else spec.label,
                "ticks": self.ticks,
                "rows_written": self.tape.rows_written,
                "poll_interval_seconds": self.poll_seconds,
            }
        )

    def poll_pool(self, spec: PoolSpec, *, include_vaults: bool = False) -> None:
        now = self.clock()
        watch = self.watches[spec.address]
        stats = self.stats[spec.address]
        addresses = self.watch_set(spec, include_vaults=include_vaults)
        self.touch("polling", spec)

        listing: list[Mapping[str, Any]] = []
        # Dedupe across addresses before any getTransaction: a swap names the pool AND both
        # vaults, so without this the vault sweep would triple the fetch cost of every fill.
        seen_signatures: set[str] = set()
        newest: dict[str, str] = {}
        for address in addresses:
            try:
                page = self._listing(spec, address)
            except RpcError as exc:
                gap = watch.note_failure(now, type(exc).__name__)
                self.tape.write_watch(spec.address, gap.to_json(), at=utc_iso(now))
                self.log(f"[{spec.label}] poll of {address[:8]} failed: {exc}")
                return
            if page:
                newest[address] = str(sort_listing(page)[-1].get("signature"))
            for entry in page:
                signature = str(entry.get("signature"))
                if signature and signature not in seen_signatures:
                    seen_signatures.add(signature)
                    listing.append(entry)

        poll_gap = watch.note_poll(now)
        if poll_gap is not None:
            self.tape.write_watch(spec.address, poll_gap.to_json(), at=utc_iso(now))

        # UNCONDITIONALLY, before the early return. The cursor's `last_poll_at` is the only
        # per-poll liveness signal this collector has, and it used to advance only when a poll
        # returned rows — so a dead-quiet pool's clock froze and looked exactly like a dead
        # process. That is the signal scripts/watchdog.py reads.
        state = self.cursors.setdefault(spec.address, {})
        state["last_poll_at"] = utc_iso(now)
        state["label"] = spec.label
        state["watched_addresses"] = list(addresses)
        self.note_heartbeat(spec, now, addresses)

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
            if self.stopping:
                # Stop at a BATCH boundary, not a pool boundary. A pool resuming from a
                # day-old cursor has thousands of pending signatures, so "finish the current
                # pool" made SIGTERM take upwards of ten minutes — during which launchd had
                # already respawned a successor that sat spinning on the tape lock. Returning
                # here leaves `newest` unapplied, so the cursor does not advance past rows
                # that were never written and the successor simply re-reads them.
                self.log(f"[{spec.label}] stopping mid-pool; cursor left where it was")
                return
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
            self.touch("fetching", spec)
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

        # Per address, and only now: every batch above is written, so a crash before this
        # point re-reads the same signatures rather than skipping them (the tape dedupes on
        # (pool, signature), so a re-read costs a duplicate fetch and never a duplicate row).
        for address, signature in newest.items():
            self._set_cursor(spec, address, signature)

    def note_heartbeat(
        self, spec: PoolSpec, now: datetime, addresses: Sequence[str]
    ) -> None:
        """Write this pool's liveness row if one is due. See :data:`DEFAULT_HEARTBEAT_SECONDS`."""

        if self.heartbeat_seconds <= 0:
            return
        last = self.last_heartbeat.get(spec.address)
        if last is not None and (now - last).total_seconds() < self.heartbeat_seconds:
            return
        self.last_heartbeat[spec.address] = now
        watch = self.watches.get(spec.address)
        if watch is None:
            return
        self.tape.write_watch(
            spec.address, watch.heartbeat_row(now, watched=addresses), at=utc_iso(now)
        )

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
        self.ticks += 1
        factor = max(1, int(self.vault_poll_factor))
        include_vaults = (self.ticks - 1) % factor == 0
        for spec in self.pools:
            if self.stopping:
                return
            self.poll_pool(spec, include_vaults=include_vaults)

    def run(self, *, minutes: float | None, once: bool = False) -> None:
        started = self.clock()
        deadline = None if minutes is None else started + timedelta(minutes=minutes)
        self.resolve_vaults()
        self.open_watches()
        reason = WatchClose.DEADLINE
        try:
            while True:
                self.tick()
                self.renew_watches(self.clock())
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
        help="stop after this many minutes; <= 0 runs until killed (the daemon mode), which "
             "is also what omitting the flag does",
    )
    parser.add_argument("--once", action="store_true", help="one pass over every pool, then exit")
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=DEFAULT_HEARTBEAT_SECONDS,
        help="write a liveness row per pool this often even when nothing traded (0 disables)",
    )
    parser.add_argument(
        "--vault-poll-factor",
        type=int,
        default=DEFAULT_VAULT_POLL_FACTOR,
        help="sweep each pool's vault addresses every Nth tick (1 = every tick)",
    )
    parser.add_argument(
        "--allow-concurrent",
        action="store_true",
        help="skip the single-instance lock (two recorders on one tape write duplicate rows)",
    )
    parser.add_argument(
        "--lock-wait",
        type=float,
        default=120.0,
        help="seconds to wait for a draining predecessor to release the tape lock",
    )
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


def acquire_tape_lock(tape: ClusterTape, *, wait_seconds: float = 120.0, sleep: Any = time.sleep) -> Any:
    """Exclusive advisory lock on the tape root. Returns the open handle (keep it alive).

    Two recorders on one tape is not a harmless race: dedupe is per-process (an in-memory
    ``OrderedDict`` in :class:`~shitcoims_cluster.tape.ClusterTape`), so a second process
    re-writes rows the first already wrote and every intensity estimate downstream doubles.
    launchd firing while the operator has a manual run open is exactly how that happens, so it
    is refused structurally rather than remembered.

    It **waits** rather than failing fast, because the common case is not a mistake: this
    recorder answers SIGTERM by draining the current pass over every pool, which with a stale
    cursor can take minutes, and launchd's ``KeepAlive`` respawns the successor long before
    the predecessor has let go. Failing fast there turns an orderly restart into a
    throttled crash loop — observed doing exactly that on the first install.
    """

    import fcntl

    tape.root.mkdir(parents=True, exist_ok=True)
    path = tape.root / "recorder.lock"
    handle = path.open("a+")
    deadline = time.monotonic() + max(0.0, wait_seconds)
    waited = False
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() >= deadline:
                handle.close()
                raise SystemExit(
                    f"another recorder still holds {path} after {wait_seconds:.0f}s; refusing "
                    "to write a second copy of every row (--allow-concurrent overrides, "
                    "--lock-wait waits longer)"
                ) from None
            if not waited:
                waited = True
                print(f"waiting for {path} to be released", file=sys.stderr, flush=True)
            sleep(1.0)
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()} {utc_iso(datetime.now(UTC))}\n")
    handle.flush()
    return handle


def main(argv: Sequence[str] | None = None) -> int:
    import json

    args = build_parser().parse_args(argv)
    pools = _select(args.pool)
    tape = ClusterTape(args.tape_dir)
    lock = None if args.allow_concurrent else acquire_tape_lock(tape, wait_seconds=args.lock_wait)
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
        heartbeat_seconds=max(0.0, args.heartbeat_seconds),
        vault_poll_factor=max(1, args.vault_poll_factor),
    )

    def _stop(signum: int, frame: Any) -> None:  # pragma: no cover - signal path
        collector.stopping = True
        collector.log("stopping after the current pass")

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError):  # not the main thread
            signal.signal(sig, _stop)

    # `--minutes 0` means "forever" here, matching shitcoims_scalper.boards. It used to mean
    # "one pass", so the obvious daemon spelling silently produced a single tick and exited —
    # which is the shape of the "collectors run with --minutes flags" complaint itself.
    minutes = None if args.minutes is not None and args.minutes <= 0 else args.minutes
    try:
        collector.run(minutes=minutes, once=args.once)
    finally:
        rpc.close()
        if lock is not None:
            lock.close()
    summary = collector.summary()
    summary["rpc_calls"] = getattr(rpc, "calls", None)
    summary["rate_limit_waits"] = getattr(rpc, "rate_limit_waits", None)
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
