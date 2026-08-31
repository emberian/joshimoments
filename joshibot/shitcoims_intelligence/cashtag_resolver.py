"""Resolve a `$TICKER` callout to a mint, or refuse to.

Why this exists. `x_cashtag` observations outnumber `x_mint_mention` roughly
five to one in the live store, and until now every one of them was a dead end:
the adapter deliberately refuses to treat a cashtag as a mint (correctly — a
ticker is not an address and the live scalper reads these records). So the
loudest part of the callout stream has been unjoinable to any outcome.

The firehose changes that. `state/firehose/new_token/` carries `name`, `symbol`
and `mint` for every pump.fun launch, so a ticker *can* be resolved — but only
when the resolution is unambiguous, and tickers on this platform are anything
but unique: the same three letters are launched dozens of times a day, often
deliberately, to farm exactly this confusion.

So the contract here is refusal-first:

- A ticker resolves only when **exactly one** launch in the lookback window
  carries it. Two candidates is `ambiguous`, and ambiguous returns nothing.
- The window ends at the callout's own timestamp. A coin launched *after* the
  tweet cannot be what the tweet meant, and letting one through would be
  look-ahead dressed up as a join.
- Every refusal carries a machine-readable reason, so the study can report how
  much of the cashtag stream is genuinely unresolvable rather than silently
  analysing the resolvable minority and calling it the population.

`evaluate()` is the paired control PROGRAM.md §3.12 demands: a known-effect
arm (tweets that carry both a cashtag and a URL-derived mint, where the right
answer is known) and a known-zero arm (tickers that were never launched, where
any resolution at all is a false positive). A resolver that passes only the
zero arm is indistinguishable from one that always refuses.
"""

from __future__ import annotations

import glob
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

FIREHOSE = Path(__file__).resolve().parent.parent / "state" / "firehose" / "new_token"
DEFAULT_LOOKBACK_S = 86_400.0
_TICKER = re.compile(r"^[A-Za-z0-9_]{1,20}$")


@dataclass(frozen=True, slots=True)
class Launch:
    mint: str
    symbol: str
    name: str
    t_ingest: float


@dataclass(frozen=True, slots=True)
class Resolution:
    symbol: str
    mint: str | None
    reason: str  # resolved | ambiguous:<n> | not_launched | out_of_window | bad_ticker
    candidates: int


def load_launches(paths: str | None = None) -> list[Launch]:
    pattern = paths or str(FIREHOSE / "*.jsonl")
    out: list[Launch] = []
    for path in sorted(glob.glob(pattern)):
        with open(path) as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("kind") != "new_token":
                    continue
                payload = row.get("payload") or {}
                # ~0.7% of create frames omit name/symbol/uri entirely (a
                # zero-buy create). Those launches exist but are unnameable, so
                # they can never resolve a ticker and are skipped here rather
                # than KeyError-ing the loader.
                symbol = payload.get("symbol")
                mint = row.get("mint") or payload.get("mint")
                if not isinstance(symbol, str) or not isinstance(mint, str):
                    continue
                stamp = row.get("t_ingest")
                try:
                    t = datetime.fromisoformat(stamp).timestamp()
                except (TypeError, ValueError):
                    continue
                out.append(
                    Launch(mint, symbol.upper(), str(payload.get("name") or ""), t)
                )
    out.sort(key=lambda item: item.t_ingest)
    return out


class CashtagResolver:
    """Ticker -> mint, conservative by construction.

    Note the clock. The firehose has no vendor event clock at all — every row's
    `t_event` is null by construction — so `t_ingest` is the only timestamp
    available and it is *our* receive time, later than the launch by an unknown
    amount. That makes the window slightly generous at its start edge and is
    stated rather than hidden; it can never make a post-tweet launch resolve,
    which is the direction that would matter.
    """

    def __init__(self, launches: Iterable[Launch] | None = None) -> None:
        self._by_symbol: dict[str, list[Launch]] = defaultdict(list)
        for launch in launches if launches is not None else load_launches():
            self._by_symbol[launch.symbol].append(launch)
        for group in self._by_symbol.values():
            group.sort(key=lambda item: item.t_ingest)

    @property
    def symbols(self) -> int:
        return len(self._by_symbol)

    @property
    def launches(self) -> int:
        return sum(len(v) for v in self._by_symbol.values())

    def resolve(
        self, symbol: str, at_unix: float, *, lookback_s: float = DEFAULT_LOOKBACK_S
    ) -> Resolution:
        if not isinstance(symbol, str) or not _TICKER.fullmatch(symbol):
            return Resolution(str(symbol), None, "bad_ticker", 0)
        key = symbol.upper()
        group = self._by_symbol.get(key)
        if not group:
            return Resolution(key, None, "not_launched", 0)
        window = [
            item for item in group if at_unix - lookback_s <= item.t_ingest <= at_unix
        ]
        if not window:
            return Resolution(key, None, "out_of_window", len(group))
        if len(window) > 1:
            return Resolution(key, None, f"ambiguous:{len(window)}", len(window))
        return Resolution(key, window[0].mint, "resolved", 1)


def evaluate(
    resolver: CashtagResolver,
    known_effect: Iterable[tuple[str, float, str]],
    known_zero: Iterable[tuple[str, float]],
    *,
    lookback_s: float = DEFAULT_LOOKBACK_S,
) -> dict[str, Any]:
    """Both controls. A green zero-control alone certifies a broken resolver.

    `known_effect` is (symbol, t_post, true_mint) where the mint came from a URL
    in the same tweet; `known_zero` is (symbol, t_post) for tickers no launch
    ever carried.
    """

    effect = {"n": 0, "resolved": 0, "correct": 0, "wrong": 0, "refused": 0}
    reasons: dict[str, int] = defaultdict(int)
    for symbol, t_post, truth in known_effect:
        effect["n"] += 1
        got = resolver.resolve(symbol, t_post, lookback_s=lookback_s)
        reasons[got.reason] += 1
        if got.mint is None:
            effect["refused"] += 1
        else:
            effect["resolved"] += 1
            if got.mint == truth:
                effect["correct"] += 1
            else:
                effect["wrong"] += 1
    zero = {"n": 0, "false_positive": 0}
    for symbol, t_post in known_zero:
        zero["n"] += 1
        if resolver.resolve(symbol, t_post, lookback_s=lookback_s).mint is not None:
            zero["false_positive"] += 1
    return {
        "known_effect": {
            **effect,
            "recall": effect["resolved"] / effect["n"] if effect["n"] else 0.0,
            "precision": (
                effect["correct"] / effect["resolved"] if effect["resolved"] else float("nan")
            ),
            "refusal_reasons": dict(reasons),
        },
        "known_zero": {
            **zero,
            "false_positive_rate": (
                zero["false_positive"] / zero["n"] if zero["n"] else 0.0
            ),
        },
    }
