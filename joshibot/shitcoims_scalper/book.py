"""The position book: a deadline min-heap, a concurrency cap, and a correlation breaker.

The heap is what makes time-boxing free at any book size: O(1) to know the next
forced exit, O(log n) to schedule one. The exit trigger is the CLOCK, which noise
cannot trip — the structural replacement for the stop-loss that liquidated the
desk on 2026-08-12.

The circuit breaker exists because N concurrent scalps on fresh mints are
secretly one bet on market-wide degen appetite this hour (measured hourly Fano
16.7 — clustering dominates). When the trailing window of closed scalps goes
net-red past the bound, the book pauses and SAYS SO, converting overdispersion
from a silent killer into a visible state.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class OpenPosition:
    decision_id: str
    mint: str
    size_lamports: int
    deadline_unix: float


class DeadlineHeap:
    """Min-heap of open positions keyed on exit deadline."""

    def __init__(self) -> None:
        self._heap: list[tuple[float, str, OpenPosition]] = []
        self._open: dict[str, OpenPosition] = {}

    def __len__(self) -> int:
        return len(self._open)

    def push(self, pos: OpenPosition) -> None:
        if pos.decision_id in self._open:
            raise ValueError(f"position {pos.decision_id} already open")
        self._open[pos.decision_id] = pos
        heapq.heappush(self._heap, (pos.deadline_unix, pos.decision_id, pos))

    def due(self, now_unix: float) -> list[OpenPosition]:
        """Pop every position whose deadline has passed, in deadline order."""
        out: list[OpenPosition] = []
        while self._heap and self._heap[0][0] <= now_unix:
            _, decision_id, pos = heapq.heappop(self._heap)
            if self._open.pop(decision_id, None) is not None:
                out.append(pos)
        return out

    def exposure_lamports(self) -> int:
        return sum(p.size_lamports for p in self._open.values())


@dataclass
class CircuitBreaker:
    """Pause the book when the trailing window of closed scalps is net-red past a bound."""

    window: int = 10
    max_drawdown_lamports: int = 100_000_000  # 0.1 SOL across the window
    pause_seconds: float = 1800.0
    _closes: deque[int] = field(default_factory=deque)
    _paused_until: float = 0.0

    def record_close(self, pnl_lamports: int, now_unix: float) -> None:
        self._closes.append(pnl_lamports)
        while len(self._closes) > self.window:
            self._closes.popleft()
        if sum(self._closes) < -self.max_drawdown_lamports:
            self._paused_until = max(self._paused_until, now_unix + self.pause_seconds)
            self._closes.clear()  # re-arm against the post-pause window, not stale losses

    def paused(self, now_unix: float) -> bool:
        return now_unix < self._paused_until

    @property
    def paused_until(self) -> float:
        return self._paused_until


class Book:
    """Concurrency cap + heap + breaker. The shadow analogue of the envelope's exposure gate."""

    def __init__(
        self,
        *,
        max_positions: int = 8,
        max_exposure_lamports: int = 2_000_000_000,  # 2 SOL
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self.max_positions = max_positions
        self.max_exposure_lamports = max_exposure_lamports
        self.heap = DeadlineHeap()
        self.breaker = breaker or CircuitBreaker()
        self.open_mints: set[str] = set()

    def admits(self, *, mint: str, size_lamports: int, now_unix: float) -> bool:
        return (
            not self.breaker.paused(now_unix)
            and mint not in self.open_mints
            and len(self.heap) < self.max_positions
            and self.heap.exposure_lamports() + size_lamports <= self.max_exposure_lamports
        )

    def open(self, pos: OpenPosition) -> None:
        self.heap.push(pos)
        self.open_mints.add(pos.mint)

    def close(self, pos: OpenPosition, pnl_lamports: int, now_unix: float) -> None:
        self.open_mints.discard(pos.mint)
        self.breaker.record_close(pnl_lamports, now_unix)
