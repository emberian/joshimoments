"""Candidate sources, each with a watch window, each with both clocks.

The desk does not re-poll the vendors. Two collectors already run against them
(``shitcoims_scalper.boards`` and ``shitcoims_scalper.firehose``) and a third writes the
cluster tape; the desk TAILS what they write. That is not only politeness about rate
limits -- it means the desk's observations are exactly the observations the rest of the
repo can audit, byte for byte, rather than a second parallel view of the market that
happens to disagree.

FIVE THINGS THIS MODULE REFUSES TO DO
-------------------------------------
1. **Invent an event clock.** Not one firehose payload carries one -- verified over 396
   consecutive ``new_token`` rows, all ``t_event: null``. The desk propagates the null and
   the reason, so nobody later measures a poll interval and calls it latency.
2. **Treat unknown as zero.** ``drawdown_from_ath`` is ``-1.0`` when the vendor served no
   ATH, and ``-1.0 < 0.50`` is *true*, so a naive shallow-drawdown filter admits every
   unknown-drawdown coin as its best candidate. :meth:`MintObservation.drawdown_known`
   exists to make that impossible to write by accident.
3. **Count duplicates.** Two ``firehose`` processes overlapped on 2026-08-14 and 140 of
   158 signatures in that span are on disk twice. Dedupe is on ``signature`` for the
   firehose and ``row_id`` for the cluster tape, both of which the writers already
   compute.
4. **Read a truncated line.** The sinks flush per row but fsync only on rotation, so the
   final line of a live file is routinely half-written. The tailer buffers a partial line
   rather than discarding it, because discarding it silently drops one real event per
   poll.
5. **Confuse a cold collector with a quiet market.** Every source reports
   :attr:`Source.seconds_since_event`; the desk turns staleness past a bound into a
   ``watch_close`` with :class:`shitcoims_tape.schema.WatchClose.OBSERVER_LOST`, which is
   informative censoring and is counted as such.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Final, Iterator

from shitcoims_cluster.pools import CLUSTER_POOLS, WSOL_MINT, PoolSpec
from shitcoims_scalper.shadow import CurveState

__all__ = [
    "BoardsSource",
    "CalloutSource",
    "ClusterTapeSource",
    "FirehoseSource",
    "JsonlTail",
    "MintObservation",
    "MintRefreshSource",
    "PoolSwap",
    "Source",
    "swap_as_mint_observation",
]

STATE: Final[Path] = Path(__file__).resolve().parent.parent / "state"

#: The vendor sentinel meaning "no ATH served", never "at its peak".
DRAWDOWN_UNKNOWN: Final[float] = -1.0

CLOCK_ABSENT_VENDOR: Final[str] = "absent:vendor_payload_carries_no_event_clock"
CLOCK_LOCAL: Final[str] = "absent:local_row_has_no_vendor_clock"


# ---------------------------------------------------------------------- observations


@dataclass(frozen=True, slots=True)
class MintObservation:
    """One observation of one bonding-curve mint, from one source, at two clocks.

    ``vsol_lamports``/``vtok_raw`` are the VIRTUAL reserves, which is what the curve
    actually trades against. Real deposited SOL is ``vsol - 30e9``; the desk sizes on the
    virtual figure because that is the depth a fill walks.
    """

    mint: str
    source: str
    t_ingest_unix: float
    t_event_unix: float | None
    t_event_source: str
    vsol_lamports: int
    vtok_raw: int
    usd_market_cap: float = 0.0
    ath_market_cap: float = 0.0
    drawdown_from_ath: float = DRAWDOWN_UNKNOWN
    created_unix: float | None = None
    last_trade_unix: float | None = None
    complete: bool = False
    board: str | None = None
    symbol: str | None = None
    #: Set when the observation came from a NAMED pool rather than a bonding curve, so the
    #: book can charge that pool's MEASURED effective take instead of the 1% curve rate.
    #: The cluster pools differ by more than an order of magnitude (20 bps on DREGG/SOL,
    #: ~909 on weave/SOL), and charging one rate for all of them would make the medium
    #: book's held-cluster arm a fiction.
    pool_label: str | None = None

    @property
    def drawdown_known(self) -> bool:
        """The guard that stops ``-1.0`` reading as the shallowest drawdown on the board."""
        return self.drawdown_from_ath >= 0.0

    @property
    def curve(self) -> CurveState:
        return CurveState(
            t_ingest_unix=self.t_ingest_unix,
            vsol_lamports=self.vsol_lamports,
            vtok_raw=self.vtok_raw,
        )

    @property
    def sol_in_curve(self) -> float:
        return self.vsol_lamports / 1e9

    @property
    def price(self) -> float:
        """Marginal SOL per raw token. Ratio of the reserves; no vendor price involved."""
        return self.vsol_lamports / self.vtok_raw

    def features(self) -> dict[str, float]:
        """The decision features, hashed into the propensity record.

        Deliberately small and all directly observed. ``age_s`` and ``trade_recency_s``
        use the VENDOR's clocks against OUR ingest clock, which is the only comparison
        available -- and is why both clocks are on every row.
        """
        age = (
            self.t_ingest_unix - self.created_unix
            if self.created_unix is not None
            else float("nan")
        )
        recency = (
            self.t_ingest_unix - self.last_trade_unix
            if self.last_trade_unix is not None
            else float("nan")
        )
        return {
            "age_s": age if age == age else 1e9,
            "trade_recency_s": recency if recency == recency else 1e9,
            "sol_in_curve": self.sol_in_curve,
            "drawdown_from_ath": self.drawdown_from_ath,
            "usd_market_cap": self.usd_market_cap,
            "drawdown_known": 1.0 if self.drawdown_known else 0.0,
        }


@dataclass(frozen=True, slots=True)
class PoolSwap:
    """One observed swap on a cluster pool: flow, price, and which side moved.

    ``price`` is quote-per-base from the POST reserves -- the marginal price, which is the
    bounce-free series ``studies/lp_strategy.py`` uses. For a DLMM the vault totals do not
    determine the marginal price (that is what ``replay_sufficient=false`` means), so the
    ratio is a proxy and ``price_source`` says so rather than pretending otherwise.
    """

    pool: str
    label: str
    dex: str
    t_ingest_unix: float
    t_event_unix: float | None
    t_event_source: str
    price: float
    price_source: str
    quote_notional: float
    quote_reserve: float
    base_reserve: float
    base_mint: str
    quote_mint: str
    row_id: str

    @property
    def tvl_quote(self) -> float:
        """Both sides in quote units. A 50/50 CFMM holds equal value per side."""
        return 2.0 * self.quote_reserve


# ---------------------------------------------------------------------- tailing


class JsonlTail:
    """Follows a set of append-only JSONL files from wherever they are now.

    Attaches at END OF FILE by default: a desk starting at 21:00 must not replay the
    day's 150MB of boards history as if it were live, because every one of those rows
    would fill a paper position at a price the desk could not have acted on.
    """

    def __init__(
        self,
        paths_for: Callable[[float], list[Path]],
        *,
        from_start: bool = False,
        max_bytes_per_poll: int = 8_000_000,
    ) -> None:
        self._paths_for = paths_for
        self._from_start = from_start
        self._max_bytes = max_bytes_per_poll
        self._offsets: dict[Path, int] = {}
        self._partial: dict[Path, str] = {}
        self.bad_lines = 0

    def poll(self, now: float) -> Iterator[dict[str, Any]]:
        for path in self._paths_for(now):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if path not in self._offsets:
                self._offsets[path] = 0 if self._from_start else size
                self._partial[path] = ""
            start = self._offsets[path]
            if size < start:  # truncated or replaced under us
                start = 0
                self._partial[path] = ""
            if size <= start:
                self._offsets[path] = start
                continue
            end = min(size, start + self._max_bytes)
            try:
                with path.open("rb") as fh:
                    fh.seek(start)
                    chunk = fh.read(end - start)
            except OSError:
                continue
            self._offsets[path] = start + len(chunk)
            text = self._partial.get(path, "") + chunk.decode("utf-8", errors="replace")
            lines = text.split("\n")
            self._partial[path] = lines.pop()  # trailing partial, kept for the next poll
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    self.bad_lines += 1
                    continue
                if isinstance(payload, dict):
                    yield payload


class _Dedupe:
    """Bounded LRU of keys already seen. Overlapping collectors are a fact of this tree."""

    def __init__(self, capacity: int = 200_000) -> None:
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._cap = capacity
        self.dropped = 0

    def fresh(self, key: str) -> bool:
        if key in self._seen:
            self._seen.move_to_end(key)
            self.dropped += 1
            return False
        self._seen[key] = None
        if len(self._seen) > self._cap:
            self._seen.popitem(last=False)
        return True


# ---------------------------------------------------------------------- sources


class Source:
    """A candidate source with a watch window and an observable staleness.

    ``name`` is stable and appears on every row it produces, so a report can say which
    feed a book's positions came from -- the question the short book exists to answer.
    """

    name: str = "source"

    def __init__(self) -> None:
        self.opened_at_unix: float = time.time()
        self.events: int = 0
        self.last_event_unix: float = 0.0

    def seconds_since_event(self, now: float) -> float:
        """Time since this source last produced anything. Absence of DATA, measurably."""
        return now - (self.last_event_unix or self.opened_at_unix)

    def _tick(self, now: float, n: int) -> None:
        if n:
            self.events += n
            self.last_event_unix = now


class BoardsSource(Source):
    """Tails ``state/boards/boards-YYYYMMDD.jsonl`` written by ``shitcoims_scalper.boards``.

    Consumes ``board_entry`` rows -- a coin ARRIVING on a board is the event the operator
    actually reacts to, and ``studies/RESULT_board_entry.md`` was built on exactly that
    row. ``board_snapshot`` members are consumed too, because a position needs continued
    observation to be marked, and only the snapshot carries a coin that is sitting still.
    """

    name = "boards"

    def __init__(self, root: Path | None = None, *, from_start: bool = False) -> None:
        super().__init__()
        base = root or (STATE / "boards")
        self._tail = JsonlTail(
            lambda now: [base / f"boards-{datetime.fromtimestamp(now, tz=UTC):%Y%m%d}.jsonl"],
            from_start=from_start,
        )

    def poll(self, now: float) -> list[MintObservation]:
        out: list[MintObservation] = []
        for row in self._tail.poll(now):
            kind = row.get("kind")
            if kind == "board_entry":
                obs = self._observation(row, row.get("board"))
                if obs is not None:
                    out.append(obs)
            elif kind == "board_snapshot":
                board = row.get("board")
                for member in row.get("members") or ():
                    if isinstance(member, dict):
                        obs = self._observation(member, board)
                        if obs is not None:
                            out.append(obs)
        self._tick(now, len(out))
        return out

    @staticmethod
    def _observation(row: dict[str, Any], board: str | None) -> MintObservation | None:
        mint = row.get("mint")
        vsol, vtok = row.get("virtual_sol_reserves"), row.get("virtual_token_reserves")
        if not isinstance(mint, str) or not vsol or not vtok:
            return None
        t_ingest = float(row.get("t_ingest") or 0.0)
        if t_ingest <= 0:
            return None
        # The boards feed's vendor clocks: last_trade_unix is the closest thing to an
        # event clock this source has, and it is the coin's clock, not the row's.
        last_trade = row.get("last_trade_unix")
        return MintObservation(
            mint=mint,
            source="boards",
            t_ingest_unix=t_ingest,
            t_event_unix=float(last_trade) if last_trade else None,
            t_event_source=("vendor:last_trade_timestamp" if last_trade else CLOCK_ABSENT_VENDOR),
            vsol_lamports=int(vsol),
            vtok_raw=int(vtok),
            usd_market_cap=float(row.get("usd_market_cap") or 0.0),
            ath_market_cap=float(row.get("ath_market_cap") or 0.0),
            drawdown_from_ath=float(
                row.get("drawdown_from_ath", DRAWDOWN_UNKNOWN) or DRAWDOWN_UNKNOWN
            ),
            created_unix=float(row["created_unix"]) if row.get("created_unix") else None,
            last_trade_unix=float(last_trade) if last_trade else None,
            complete=bool(row.get("complete", False)),
            board=board,
            symbol=row.get("symbol"),
        )


class FirehoseSource(Source):
    """Tails ``state/firehose/new_token/YYYY-MM-DD.jsonl``.

    ~18-28 new mints a minute, each with the creator's own first buy already reflected in
    ``vSolInBondingCurve``. The payload's amounts are FLOATS IN WHOLE TOKENS, unlike every
    other feed in this tree -- converting them to raw integer units here, once, is why the
    rest of the desk can stay in integers.
    """

    name = "firehose"

    def __init__(
        self, root: Path | None = None, *, from_start: bool = False, decimals: int = 6
    ) -> None:
        super().__init__()
        base = root or (STATE / "firehose" / "new_token")
        self._decimals = decimals
        self._dedupe = _Dedupe()
        self._tail = JsonlTail(
            lambda now: [base / f"{datetime.fromtimestamp(now, tz=UTC):%Y-%m-%d}.jsonl"],
            from_start=from_start,
        )

    @property
    def duplicates_dropped(self) -> int:
        return self._dedupe.dropped

    def poll(self, now: float) -> list[MintObservation]:
        out: list[MintObservation] = []
        for row in self._tail.poll(now):
            if row.get("kind") != "new_token":
                continue
            signature = row.get("signature")
            if not isinstance(signature, str) or not self._dedupe.fresh(signature):
                continue
            payload = row.get("payload")
            mint = row.get("mint")
            if not isinstance(payload, dict) or not isinstance(mint, str):
                continue
            vsol = payload.get("vSolInBondingCurve")
            vtok = payload.get("vTokensInBondingCurve")
            if not vsol or not vtok:
                continue
            t_ingest = _parse_iso(row.get("t_ingest"))
            if t_ingest is None:
                continue
            out.append(
                MintObservation(
                    mint=mint,
                    source="firehose",
                    t_ingest_unix=t_ingest,
                    # Verified over 396 consecutive rows: not one payload carries an event
                    # clock. Propagate the null and the reason, never our own clock.
                    t_event_unix=None,
                    t_event_source=str(row.get("t_event_source") or CLOCK_ABSENT_VENDOR),
                    vsol_lamports=int(float(vsol) * 1e9),
                    vtok_raw=int(float(vtok) * (10**self._decimals)),
                    usd_market_cap=0.0,
                    ath_market_cap=0.0,
                    # A mint one second old has no ATH and no drawdown. Saying "unknown"
                    # is the truthful encoding; saying 0.0 would make every new mint the
                    # shallowest-drawdown candidate on the desk.
                    drawdown_from_ath=DRAWDOWN_UNKNOWN,
                    created_unix=t_ingest,
                    last_trade_unix=t_ingest,
                    complete=False,
                    board=None,
                    symbol=payload.get("symbol"),
                )
            )
        self._tick(now, len(out))
        return out


class CalloutSource(Source):
    """Callouts from the intelligence collector, via ``shitcoims_scalper.feed``.

    Reuses ``poll_callout_snapshots`` rather than re-querying the intelligence SQLite: it
    already handles the write-lock (it reads a *copy*, because the ``intel.py`` daemon
    holds the live file) and the three-way mint resolution. Returns ``[]`` and never
    raises when the collector is producing nothing, which is the current state -- and the
    watch window is what records the difference between that and a quiet market.
    """

    name = "callouts"

    def __init__(self, *, max_age_s: float = 900.0, min_interval_s: float = 30.0) -> None:
        super().__init__()
        self._max_age_s = max_age_s
        self._min_interval_s = min_interval_s
        self._last_poll = 0.0
        self._seen: _Dedupe = _Dedupe(capacity=20_000)

    def poll(self, now: float) -> list[MintObservation]:
        if now - self._last_poll < self._min_interval_s:
            return []
        self._last_poll = now
        try:
            from shitcoims_scalper.feed import poll_callout_snapshots

            pairs = poll_callout_snapshots(max_age_s=self._max_age_s)
        except Exception:  # a dead collector must not take the desk with it
            return []
        out: list[MintObservation] = []
        for snap, callout in pairs:
            if not self._seen.fresh(f"{callout.mint}:{int(callout.t_post_unix)}"):
                continue
            out.append(
                MintObservation(
                    mint=snap.mint,
                    source="callouts",
                    t_ingest_unix=snap.t_ingest_unix,
                    # The callout's post time IS a real event clock -- the only source on
                    # the desk that has one.
                    t_event_unix=callout.t_post_unix,
                    t_event_source=f"vendor:{callout.kind}",
                    vsol_lamports=snap.vsol_lamports,
                    vtok_raw=snap.vtok_raw,
                    created_unix=snap.created_unix,
                    last_trade_unix=snap.last_trade_unix,
                    complete=snap.complete,
                    board=None,
                    symbol=None,
                )
            )
        self._tick(now, len(out))
        return out


class MintRefreshSource(Source):
    """Re-observes the mints the desk is actually holding, so every book can mark.

    Without this the short book's firehose entries would be unmarkable: a brand-new mint
    is not on any board, so the boards feed will never observe it again, and every such
    position would resolve as "left observation" regardless of what it did. That is not
    censoring, it is a hole in the instrument.

    Reuses ``shitcoims_scalper.feed.poll_mint`` -- the same call the shadow scalper makes,
    so the vendor load pattern and the failure semantics (``None``, never an exception)
    are ones this tree already runs. Rate-limited two ways: a per-mint interval and a
    per-poll budget, because a book of eight positions must not turn into eight requests
    every three seconds.
    """

    name = "mint_refresh"

    def __init__(
        self,
        *,
        min_interval_s: float = 20.0,
        budget_per_poll: int = 4,
        priority_interval_s: float = 8.0,
    ) -> None:
        super().__init__()
        self._min_interval_s = min_interval_s
        self._priority_interval_s = priority_interval_s
        self._budget = budget_per_poll
        self._last: dict[str, float] = {}
        self.failures = 0

    def refresh(
        self, mints: list[str], now: float, *, priority: set[str] | None = None
    ) -> list[MintObservation]:
        """Re-observe held mints, PRIORITY ones first and on a shorter interval.

        Priority is not decoration. A book whose exit is a five-minute clock needs its
        positions marked at a cadence that can resolve five minutes; the mint books can
        wait, because a position they hold for hours is not misjudged by a twenty-second
        stale mark. Without the split, the queue is sorted purely by staleness and a
        long-horizon position with an older mark displaces the one whose exit is imminent
        -- which is a hole in the instrument dressed as fairness.
        """
        try:
            from shitcoims_scalper.feed import poll_mint
        except Exception:
            return []
        hot = priority or set()

        def interval(mint: str) -> float:
            return self._priority_interval_s if mint in hot else self._min_interval_s

        due = [m for m in mints if now - self._last.get(m, 0.0) >= interval(m)]
        # Priority first; within each group, the oldest observation first.
        due.sort(key=lambda m: (m not in hot, self._last.get(m, 0.0)))
        out: list[MintObservation] = []
        for mint in due[: self._budget]:
            self._last[mint] = now
            try:
                snap = poll_mint(mint)
            except Exception:
                self.failures += 1
                continue
            if snap is None:
                self.failures += 1
                continue
            out.append(
                MintObservation(
                    mint=snap.mint,
                    source="mint_refresh",
                    t_ingest_unix=snap.t_ingest_unix,
                    t_event_unix=snap.last_trade_unix,
                    t_event_source=(
                        "vendor:last_trade_timestamp" if snap.last_trade_unix else CLOCK_ABSENT_VENDOR
                    ),
                    vsol_lamports=snap.vsol_lamports,
                    vtok_raw=snap.vtok_raw,
                    # This endpoint serves no ATH, so drawdown stays unknown rather than
                    # being back-filled from a different source with a different clock.
                    drawdown_from_ath=DRAWDOWN_UNKNOWN,
                    created_unix=snap.created_unix,
                    last_trade_unix=snap.last_trade_unix,
                    complete=snap.complete,
                )
            )
        self._tick(now, len(out))
        return out


class ClusterTapeSource(Source):
    """Tails ``state/cluster_tape/swaps/<pool>-YYYYMMDD.jsonl`` for the toll book.

    Day-partitioned on CHAIN time by the writer, so the file to follow is chosen by
    ``t_event``, not by our clock -- the one place in this package where that is correct,
    because it is what the writer did.

    A swap's price comes from the POST vault balances, matched BY MINT (vault order is not
    fixed). ``attempt`` rows are skipped: a failed transaction moved nothing, and counting
    it as flow would inflate every fee accrual on the book.
    """

    name = "cluster_tape"

    def __init__(
        self,
        root: Path | None = None,
        *,
        pools: tuple[PoolSpec, ...] = CLUSTER_POOLS,
        from_start: bool = False,
        days_back: int = 1,
    ) -> None:
        super().__init__()
        base = root or (STATE / "cluster_tape" / "swaps")
        self._pools = {p.address: p for p in pools}
        self._dedupe = _Dedupe()
        self._days_back = days_back

        def paths(now: float) -> list[Path]:
            # OLDEST DAY FIRST. The tape is day-partitioned on chain time and a tail reads
            # one file at a time, so newest-first would append yesterday's prices after
            # today's and compute a realised variance out of jumps that never happened.
            out: list[Path] = []
            for back in range(self._days_back, -1, -1):
                day = datetime.fromtimestamp(now - back * 86400.0, tz=UTC)
                out.extend(base / f"{addr}-{day:%Y%m%d}.jsonl" for addr in self._pools)
            return out

        self._tail = JsonlTail(paths, from_start=from_start)

    def poll(self, now: float) -> list[PoolSwap]:
        out: list[PoolSwap] = []
        for row in self._tail.poll(now):
            if row.get("kind") != "swap":
                continue
            row_id = row.get("row_id")
            if not isinstance(row_id, str) or not self._dedupe.fresh(row_id):
                continue
            swap = self._to_swap(row)
            if swap is not None:
                out.append(swap)
        self._tick(now, len(out))
        return out

    def _to_swap(self, row: dict[str, Any]) -> PoolSwap | None:
        pool = row.get("pool")
        spec = self._pools.get(pool) if isinstance(pool, str) else None
        if spec is None:
            return None
        reserves = row.get("reserves") or {}
        vaults = reserves.get("vaults") or []
        if len(vaults) != 2:
            return None
        by_mint: dict[str, dict[str, Any]] = {}
        for vault in vaults:
            mint = vault.get("mint")
            if isinstance(mint, str):
                by_mint[mint] = vault
        quote_mint = WSOL_MINT if WSOL_MINT in by_mint else None
        if quote_mint is None:
            # A token/token pool: the quote is whichever side the pool spec names second.
            # Order within ``mints`` is not meaningful, so pick deterministically.
            quote_mint = sorted(by_mint)[0]
        base_mint = next((m for m in by_mint if m != quote_mint), None)
        if base_mint is None:
            return None
        try:
            q, b = by_mint[quote_mint], by_mint[base_mint]
            q_post = int(q["post_raw"]) / (10 ** int(q["decimals"]))
            b_post = int(b["post_raw"]) / (10 ** int(b["decimals"]))
            q_delta = abs(int(q["delta_raw"])) / (10 ** int(q["decimals"]))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None
        if q_post <= 0 or b_post <= 0:
            return None
        t_event = _parse_iso(row.get("t_event"))
        t_ingest = _parse_iso(row.get("t_ingest")) or t_event or time.time()
        return PoolSwap(
            pool=spec.address,
            label=spec.label,
            dex=spec.dex,
            t_ingest_unix=t_ingest,
            t_event_unix=t_event,
            t_event_source="chain:block_time" if t_event else CLOCK_LOCAL,
            price=q_post / b_post,
            price_source=(
                "vault_ratio_marginal"
                if spec.replay_sufficient_reserves
                else "vault_ratio_proxy_dlmm"
            ),
            quote_notional=q_delta,
            quote_reserve=q_post,
            base_reserve=b_post,
            base_mint=base_mint,
            quote_mint=quote_mint,
            row_id=str(row.get("row_id")),
        )


#: pump.fun tokens are 6-decimal without exception across the cluster. The scale only has
#: to be CONSISTENT for the constant-product fill to be right, but using the true value
#: keeps ``price`` comparable with the rest of the tree.
PUMP_TOKEN_DECIMALS: Final[int] = 6


def swap_as_mint_observation(swap: PoolSwap) -> MintObservation | None:
    """A SOL-quoted pool swap, re-expressed as a curve observation of the base token.

    The four SOL-quoted cluster pools are PumpSwap, i.e. genuine constant product, so
    their vault balances ARE a curve and the same ``curve_buy``/``curve_sell`` marking
    that prices a bonding-curve mint prices a held-cluster position exactly -- impact
    included. No second position type and no second accounting is needed, which is the
    only reason the medium book's two arms are comparable with each other.

    Returns ``None`` for token-token pools: those have no lamport-denominated curve, and
    inventing a cross rate here would put a fabricated price in the same field as a
    measured one.
    """
    if swap.quote_mint != WSOL_MINT:
        return None
    vsol = int(swap.quote_reserve * 1e9)
    vtok = int(swap.base_reserve * (10**PUMP_TOKEN_DECIMALS))
    if vsol <= 0 or vtok <= 0:
        return None
    return MintObservation(
        mint=swap.base_mint,
        source="cluster_tape",
        t_ingest_unix=swap.t_ingest_unix,
        t_event_unix=swap.t_event_unix,
        t_event_source=swap.t_event_source,
        vsol_lamports=vsol,
        vtok_raw=vtok,
        # A graduated token has no bonding-curve ATH from the boards vendor, and this
        # source serves none. Unknown stays unknown.
        drawdown_from_ath=DRAWDOWN_UNKNOWN,
        created_unix=None,
        last_trade_unix=swap.t_event_unix or swap.t_ingest_unix,
        complete=False,
        board=None,
        symbol=swap.label.split("/")[0] if "/" in swap.label else swap.label,
        pool_label=swap.label,
    )


def _parse_iso(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None
