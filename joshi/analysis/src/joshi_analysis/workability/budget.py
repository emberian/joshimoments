"""Append-only request ledger with the budget check in front of every spend.

The callout_entry_window study's pattern, promoted to a tested module: a spend is reserved
BEFORE the request is made, a refusal at the ceiling is an explicit exception carrying the
arithmetic, and the ledger file is append-only JSONL so the receipt trail survives crashes.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


class BudgetExhausted(SystemExit):
    """Raised instead of spending past the ceiling. The refusal is the deliverable."""


class Ledger:
    """One append-only JSONL request ledger for the whole study."""

    def __init__(self, root: Path, budget: int) -> None:
        self.path = Path(root) / "ledger.jsonl"
        self.budget = budget

    def spent(self) -> int:
        if not self.path.exists():
            return 0
        total = 0
        with self.path.open() as handle:
            for line in handle:
                if line.strip():
                    total += int(json.loads(line).get("requests", 0))
        return total

    def reserve(self, expected: int) -> None:
        """Refuse before spending, never after."""
        spent = self.spent()
        if spent + expected > self.budget:
            raise BudgetExhausted(
                f"REFUSED: {spent} requests spent, {expected} more would cross the budget "
                f"of {self.budget}. This refusal is the deliverable, not a failure."
            )

    def record(self, entry: dict) -> None:
        stamped = {"at": dt.datetime.now(dt.UTC).isoformat(), **entry}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as handle:
            handle.write(json.dumps(stamped) + "\n")

    def by_phase(self) -> dict[str, int]:
        """Requests spent per phase tag, for the receipt table."""
        totals: dict[str, int] = {}
        if not self.path.exists():
            return totals
        with self.path.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                entry = json.loads(line)
                phase = str(entry.get("phase", "unphased"))
                totals[phase] = totals.get(phase, 0) + int(entry.get("requests", 0))
        return totals
