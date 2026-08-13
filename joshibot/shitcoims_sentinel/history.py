"""Read-only history, trades, and performance projections."""

from __future__ import annotations

import csv
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any


def _tail_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists() or limit <= 0:
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    items: list[dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            items.append(
                {
                    "timestamp": str(value.get("timestamp", ""))[:64],
                    "severity": str(value.get("severity", "info"))[:16],
                    "category": str(value.get("category", "event"))[:32],
                    "message": str(value.get("message", ""))[:500],
                }
            )
    return items


def read_events(path: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    return _tail_jsonl(path, min(limit, 500))


def read_trades(path: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    if not path.exists() or limit <= 0:
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    items: list[dict[str, Any]] = []
    for row in reversed(rows[-min(limit, 500) :]):
        items.append(
            {
                "timestamp": str(row.get("timestamp", ""))[:64],
                "mint": str(row.get("mint", ""))[:64],
                "name": str(row.get("name", ""))[:48],
                "reason": str(row.get("reason", ""))[:32],
                "input_amount": str(row.get("input_amount", ""))[:32],
                "output_lamports": str(row.get("output_lamports", ""))[:32],
                "signature": str(row.get("signature", ""))[:88],
            }
        )
    return items


def performance_summary(
    *,
    snapshot: dict[str, Any],
    trades: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    wallet = snapshot.get("wallet") if isinstance(snapshot.get("wallet"), dict) else {}
    realized = Decimal("0")
    for trade in trades:
        try:
            realized += Decimal(str(trade.get("output_lamports") or 0)) / Decimal(1_000_000_000)
        except Exception:
            continue
    counts = Counter(str(event.get("severity", "info")) for event in events)
    last_exit = trades[0]["timestamp"] if trades else None
    return {
        "native_sol": wallet.get("sol"),
        "portfolio_exit_sol": wallet.get("portfolio_exit_sol"),
        "realized_sol": str(realized),
        "trade_count": len(trades),
        "protected_positions": len(snapshot.get("positions") or []),
        "observe_only": len(snapshot.get("unmonitored") or []),
        "event_counts": dict(counts),
        "last_exit_at": last_exit,
        "mode": (snapshot.get("system") or {}).get("mode"),
        "protection_state": (snapshot.get("system") or {}).get("protection_state"),
    }
