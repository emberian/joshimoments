"""Stratified sampling of the enumerated mints (STUDY.md section 1). Deterministic by seed.

Cells with fewer members than their quota take everything they have; the shortfall is
reported per cell and never back-filled from fatter cells, so a thin stratum stays visibly
thin instead of being silently re-weighted.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

AGE_BUCKETS = ("0-6h", "6-24h", "24-48h", "48-72h")
MCAP_BUCKETS = ("under_10k", "10k_50k", "over_50k")
HOURS_72 = 72.0


def age_bucket(age_hours: float) -> str | None:
    if age_hours < 0 or age_hours > HOURS_72:
        return None
    if age_hours <= 6:
        return "0-6h"
    if age_hours <= 24:
        return "6-24h"
    if age_hours <= 48:
        return "24-48h"
    return "48-72h"


def mcap_bucket(usd_market_cap: float | None) -> str:
    """Read-time, provider-asserted. An absent cap is its own answer, bucketed low."""
    if usd_market_cap is None or usd_market_cap < 10_000:
        return "under_10k"
    if usd_market_cap <= 50_000:
        return "10k_50k"
    return "over_50k"


@dataclass(frozen=True)
class StratumDraw:
    age: str
    mcap: str
    graduated: bool
    quota: int
    available: int
    drawn: tuple[str, ...]  # mints, sorted draw from a seeded generator

    @property
    def shortfall(self) -> int:
        return max(0, self.quota - len(self.drawn))


def stratify(
    candidates: list[dict],
    census_instant_ms: int,
    quota_per_cell: int,
    seed: int,
) -> list[StratumDraw]:
    """Draw the sample. Each candidate: {mint, created_timestamp, usd_market_cap, complete}.

    Candidates without a created_timestamp cannot be aged and are excluded (counted by the
    caller); duplicates keep their first enumeration row.
    """
    cells: dict[tuple[str, str, bool], list[str]] = {}
    seen: set[str] = set()
    for row in candidates:
        mint = row.get("mint")
        created = row.get("created_timestamp")
        if not mint or mint in seen or not isinstance(created, int | float):
            continue
        seen.add(mint)
        age_hours = (census_instant_ms - float(created)) / 3_600_000
        age = age_bucket(age_hours)
        if age is None:
            continue
        cap = row.get("usd_market_cap")
        cap_value = float(cap) if isinstance(cap, int | float) else None
        key = (age, mcap_bucket(cap_value), bool(row.get("complete")))
        cells.setdefault(key, []).append(str(mint))
    draws: list[StratumDraw] = []
    for age in AGE_BUCKETS:
        for cap_name in MCAP_BUCKETS:
            for graduated in (False, True):
                members = sorted(cells.get((age, cap_name, graduated), []))
                generator = random.Random((seed, age, cap_name, graduated).__repr__())
                drawn = (
                    tuple(sorted(generator.sample(members, quota_per_cell)))
                    if len(members) > quota_per_cell
                    else tuple(members)
                )
                draws.append(
                    StratumDraw(
                        age=age,
                        mcap=cap_name,
                        graduated=graduated,
                        quota=quota_per_cell,
                        available=len(members),
                        drawn=drawn,
                    )
                )
    return draws
