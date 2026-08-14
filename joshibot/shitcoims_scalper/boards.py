"""Board-membership recorder — attention shocks delivered by the platform itself.

The operator's observation: coins that appear on pump.fun's trending-style boards
are frequently in a drawdown when they arrive, and a small position taken then can
be exited for a mini profit. That contains two separable questions, and only the
second needs a model:

1. **What happens AFTER a coin joins a board?** A pure event study. Board entry is
   an attention shock with an exact timestamp, delivered exogenously by the
   platform. No prediction required.
2. **Which coins WILL join?** Harder — but board entry is a far better prediction
   target than graduation ever was: it is frequent, timestamped, observable, and
   has an obvious causal mechanism, where graduation is a 0.63%-base-rate one-shot.

We do NOT reverse-engineer pump.fun's ranking. We record membership of the boards
we can actually see and treat ENTRY as the event. Their algorithm is allowed to be
a black box; the entry timestamp is not.

Drawdown comes free: the API serves `ath_market_cap` alongside `market_cap`, so
"in an overall downslump" is measurable at the moment of entry rather than inferred.

Discipline carried from the cluster tape, each item earned:
- **Two clocks.** `t_ingest` is ours; `created_timestamp`/`last_trade_timestamp` are
  the platform's. Never mixed.
- **Watch windows.** A board we are not polling is an unknown, not an empty board.
  Absence is only evidence inside a window.
- **JSONL, never CSV** — memecoin symbols contain commas, quotes and newlines by
  design.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

STATE_DIR = Path(__file__).resolve().parent.parent / "state" / "boards"
BASE = "https://frontend-api-v3.pump.fun"
UA = "shitcoims-boards/0.1 (read-only research)"

#: The boards we can actually observe. `currently-live` has its own endpoint shape.
BOARDS: tuple[str, ...] = (
    "last_reply",       # most recent chat activity — the closest thing to live attention
    "reply_count",      # cumulative chat volume
    "market_cap",       # the big board
    "last_trade_timestamp",
    "currently-live",   # livestreaming right now
)


def _get(url: str, timeout: float = 15.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def fetch_board(board: str, limit: int = 50) -> list[dict[str, Any]]:
    """One board's current membership, in rank order. Never raises."""
    if board == "currently-live":
        url = f"{BASE}/coins/currently-live?offset=0&limit={limit}"
    else:
        url = f"{BASE}/coins?offset=0&limit={limit}&sort={board}&order=DESC&includeNsfw=false"
    try:
        data = _get(url)
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("coins") or []
    return [c for c in data if isinstance(c, dict) and c.get("mint")]


def coin_state(coin: dict[str, Any], rank: int, t_ingest: float) -> dict[str, Any]:
    """The observable state of a coin at a moment, with drawdown computed not guessed."""
    mc = float(coin.get("usd_market_cap") or 0.0)
    ath = float(coin.get("ath_market_cap") or 0.0)
    # Drawdown is the operator's "overall downslump", available directly because the
    # API serves the peak alongside the current value. -1.0 means unknown, never 0.0:
    # a missing ATH must not read as "at its peak".
    drawdown = (1.0 - mc / ath) if (ath > 0 and mc > 0) else -1.0
    created = coin.get("created_timestamp")
    last_trade = coin.get("last_trade_timestamp")
    return {
        "mint": coin["mint"],
        "symbol": coin.get("symbol"),
        "rank": rank,
        "usd_market_cap": mc,
        "ath_market_cap": ath,
        "drawdown_from_ath": drawdown,
        "ath_at_unix": (float(coin["ath_market_cap_timestamp"]) / 1000.0)
        if coin.get("ath_market_cap_timestamp")
        else None,
        "reply_count": coin.get("reply_count"),
        "is_currently_live": coin.get("is_currently_live"),
        "complete": bool(coin.get("complete", False)),
        "created_unix": (float(created) / 1000.0) if created else None,
        "last_trade_unix": (float(last_trade) / 1000.0) if last_trade else None,
        "virtual_sol_reserves": coin.get("virtual_sol_reserves"),
        "virtual_token_reserves": coin.get("virtual_token_reserves"),
        "t_ingest": t_ingest,
    }


@dataclass
class BoardWatcher:
    """Tracks membership per board and emits entry/exit events across polls."""

    limit: int = 50
    #: board -> set of mints seen on the previous poll
    _prev: dict[str, set[str]] = field(default_factory=dict)
    #: board -> unix time the current watch window opened
    _window_open: dict[str, float] = field(default_factory=dict)

    def poll(self, boards: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """Poll every board once; return entry/exit/snapshot records to append."""
        out: list[dict[str, Any]] = []
        for board in boards or BOARDS:
            t = time.time()
            coins = fetch_board(board, self.limit)
            if not coins:
                # A failed fetch CLOSES the window: we no longer know this board's
                # membership, and a gap must not read as "everyone left".
                if board in self._window_open:
                    out.append({
                        "kind": "watch_close", "board": board, "t_ingest": t,
                        "reason": "fetch_failed",
                        "window_opened_at": self._window_open.pop(board),
                    })
                    self._prev.pop(board, None)
                continue

            if board not in self._window_open:
                self._window_open[board] = t
                out.append({"kind": "watch_open", "board": board, "t_ingest": t})

            states = [coin_state(c, i, t) for i, c in enumerate(coins)]
            current = {s["mint"] for s in states}
            previous = self._prev.get(board)

            if previous is not None:
                for s in states:
                    if s["mint"] not in previous:
                        out.append({"kind": "board_entry", "board": board, **s})
                for mint in previous - current:
                    out.append({
                        "kind": "board_exit", "board": board, "mint": mint, "t_ingest": t,
                    })
            self._prev[board] = current
            out.append({
                "kind": "board_snapshot", "board": board, "t_ingest": t,
                "n": len(states), "members": states,
            })
        return out


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        for r in records:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Record pump.fun board membership over time")
    ap.add_argument("--minutes", type=float, default=60.0)
    ap.add_argument("--poll-seconds", type=float, default=30.0)
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    watcher = BoardWatcher(limit=args.limit)
    day = time.strftime("%Y%m%d", time.gmtime())
    path = STATE_DIR / f"boards-{day}.jsonl"
    end = time.time() + args.minutes * 60
    counts = {"board_entry": 0, "board_exit": 0, "board_snapshot": 0}

    while time.time() < end:
        start = time.time()
        records = watcher.poll()
        append_jsonl(path, records)
        for r in records:
            if r["kind"] in counts:
                counts[r["kind"]] += 1
        time.sleep(max(0.0, args.poll_seconds - (time.time() - start)))

    print(json.dumps(counts, indent=1))


if __name__ == "__main__":
    main()
