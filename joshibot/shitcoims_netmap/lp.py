"""Which edges are OURS — the LP meter, folded into the map.

This wraps ``scripts/meteora_lp_report.py`` rather than reimplementing it. That file already
knows the live API's shape, the claimed-vs-unclaimed semantic (``allTimeFees`` is fees *already
claimed*, verified against the ``claim_fee`` event log), and the age-weighted fee-rate
arithmetic. A second copy would drift from it, and the number this produces is the one the
desk's income claim rests on.

**Ownership is stated with its provenance, never bare.** Three ways this map can learn the LP
wallet, and they are not equally strong:

``declared`` — passed on the command line or in ``JOSHIBOT_LP_WALLET``. The operator said so.
``inferred_from_tape`` — a wallet that paid for an ``add_liquidity`` / ``remove_liquidity`` /
    ``claim_fee2`` transaction on a cluster pool, confirmed by the API to hold open positions
    there. That is strong evidence *somebody* LPs the edge and good evidence it is the desk,
    but it is an inference, and it is labelled as one everywhere it appears.
``unknown`` — no wallet resolved. Then every edge's ownership is ``null``, which is a third
    state and not ``false``: the map does not know, and saying "not ours" would be a claim it
    has no basis for.

A resolved wallet holding no position in a pool makes that edge ``is_ours = false`` **for that
wallet**. The desk may hold others; the JSON carries the basis so the reader can see the scope
of the negative rather than inheriting it silently.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WALLET_ENV = "JOSHIBOT_LP_WALLET"

PROVENANCE_DECLARED = "declared"
PROVENANCE_ENV = "declared_env"
PROVENANCE_INFERRED = "inferred_from_tape"
PROVENANCE_UNKNOWN = "unknown"

_REPORT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "meteora_lp_report.py"


def load_report_module(path: Path | None = None) -> Any:
    """Import ``scripts/meteora_lp_report.py`` by path — it is a script, not a package member."""

    target = path or _REPORT_PATH
    cached = sys.modules.get("meteora_lp_report")
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location("meteora_lp_report", target)
    if spec is None or spec.loader is None:  # pragma: no cover - only if the file is deleted
        raise ImportError(f"cannot load the LP reporter from {target}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["meteora_lp_report"] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True, slots=True)
class OurPosition:
    """One open LP position of ours on one pool, as the LP meter reports it."""

    pool: str
    position_address: str | None
    pair: str | None
    value_usd: float | None
    unclaimed_fees_usd: float | None
    claimed_fees_usd: float | None
    lifetime_fees_usd: float | None
    in_range: bool | None
    age_days: float | None
    fee_rate_per_day: float | None
    rate_is_thin: bool
    token_amounts: dict[str, float] = field(default_factory=dict)
    token_usd: dict[str, float] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "position": self.position_address,
            "pair": self.pair,
            "value_usd": self.value_usd,
            "unclaimed_fees_usd": self.unclaimed_fees_usd,
            "claimed_fees_usd": self.claimed_fees_usd,
            "lifetime_fees_usd": self.lifetime_fees_usd,
            "in_range": self.in_range,
            "age_days": self.age_days,
            "fee_rate_per_day": self.fee_rate_per_day,
            "fee_rate_is_thin_sample": self.rate_is_thin,
            "token_amounts": self.token_amounts,
            "token_usd": self.token_usd,
        }


@dataclass(slots=True)
class LpSnapshot:
    wallet: str | None
    provenance: str
    positions: dict[str, list[OurPosition]] = field(default_factory=dict)
    total_value_usd: float | None = None
    total_unclaimed_usd: float | None = None
    total_lifetime_fees_usd: float | None = None
    portfolio_fee_rate_per_day: float | None = None
    candidates: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.wallet is not None

    def ownership(self, pool: str) -> dict[str, Any] | None:
        """Ownership record for one edge, or ``None`` when no wallet resolved (unknown ≠ false)."""

        if not self.resolved:
            return None
        held = self.positions.get(pool, [])
        return {
            "is_ours": bool(held),
            "wallet": self.wallet,
            "provenance": self.provenance,
            "basis": "open DLMM positions held by the resolved wallet; other wallets are not searched",
            "positions": [p.to_json() for p in held],
            "value_usd": _sum([p.value_usd for p in held]) if held else None,
            "unclaimed_fees_usd": _sum([p.unclaimed_fees_usd for p in held]) if held else None,
            "lifetime_fees_usd": _sum([p.lifetime_fees_usd for p in held]) if held else None,
            "fee_rate_per_day": held[0].fee_rate_per_day if len(held) == 1 else None,
            "in_range": held[0].in_range if len(held) == 1 else None,
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "wallet": self.wallet,
            "provenance": self.provenance,
            "candidates_from_tape": self.candidates,
            "total_value_usd": self.total_value_usd,
            "total_unclaimed_usd": self.total_unclaimed_usd,
            "total_lifetime_fees_usd": self.total_lifetime_fees_usd,
            "portfolio_fee_rate_per_day": self.portfolio_fee_rate_per_day,
            "pools_with_positions": sorted(self.positions),
            "errors": list(self.errors),
        }


def _sum(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if isinstance(v, (int, float))]
    return float(sum(present)) if present else None


def positions_from_report(report: Any) -> dict[str, list[OurPosition]]:
    """Project the LP reporter's ``PortfolioReport`` onto per-pool position records."""

    out: dict[str, list[OurPosition]] = {}
    for position in getattr(report, "positions", []):
        pool = getattr(position, "pool_address", None)
        if not pool:
            continue
        amounts: dict[str, float] = {}
        usd: dict[str, float] = {}
        for leg in (getattr(position, "token_x", None), getattr(position, "token_y", None)):
            mint = getattr(leg, "mint", None)
            if not mint:
                continue
            amount = getattr(leg, "amount", None)
            value = getattr(leg, "usd", None)
            if amount is not None:
                amounts[str(mint)] = float(amount)
            if value is not None:
                usd[str(mint)] = float(value)
        out.setdefault(str(pool), []).append(
            OurPosition(
                pool=str(pool),
                position_address=getattr(position, "position_address", None),
                pair=getattr(position, "pair", None),
                value_usd=getattr(position, "value_usd", None),
                unclaimed_fees_usd=getattr(position, "unclaimed_fees_usd", None),
                claimed_fees_usd=getattr(position, "claimed_fees_usd", None),
                lifetime_fees_usd=getattr(position, "lifetime_fees_usd", None),
                in_range=getattr(position, "in_range", None),
                age_days=getattr(position, "age_days", None),
                fee_rate_per_day=getattr(position, "fee_rate_per_day", None),
                rate_is_thin=bool(getattr(position, "rate_is_thin", False)),
                token_amounts=amounts,
                token_usd=usd,
            )
        )
    return out


def collect_lp(
    *,
    wallet: str | None = None,
    tape_candidates: Sequence[str] = (),
    now_epoch_seconds: float,
    module: Any | None = None,
) -> LpSnapshot:
    """Resolve a wallet, then read its open DLMM positions. Network-free when ``module`` is a stub.

    Resolution order is strongest-evidence-first: an explicit wallet, then the environment, then
    wallets the *tape* saw touching liquidity on a cluster pool. A tape candidate is accepted
    only if the API confirms it actually holds positions — a wallet that once claimed fees and
    has since withdrawn would otherwise be reported as an owner of an edge it has left.
    """

    reporter = module if module is not None else load_report_module()
    declared = wallet or os.environ.get(WALLET_ENV) or None
    provenance = PROVENANCE_DECLARED if wallet else (PROVENANCE_ENV if declared else PROVENANCE_UNKNOWN)
    errors: list[str] = []

    attempts: list[tuple[str, str]] = []
    if declared:
        attempts.append((declared, provenance))
    attempts.extend((candidate, PROVENANCE_INFERRED) for candidate in tape_candidates if candidate)

    for candidate, candidate_provenance in attempts:
        try:
            report = reporter.collect_report(candidate, now_epoch_seconds=now_epoch_seconds)
        except Exception as exc:
            errors.append(f"{candidate[:8]}: {type(exc).__name__}: {exc}")
            continue
        positions = positions_from_report(report)
        if not positions and candidate_provenance == PROVENANCE_INFERRED:
            # An inferred candidate with no open positions is not our LP wallet today.
            continue
        return LpSnapshot(
            wallet=candidate,
            provenance=candidate_provenance,
            positions=positions,
            total_value_usd=getattr(report, "total_value_usd", None),
            total_unclaimed_usd=getattr(report, "total_unclaimed_usd", None),
            total_lifetime_fees_usd=getattr(report, "total_lifetime_fees_usd", None),
            portfolio_fee_rate_per_day=getattr(report, "portfolio_fee_rate_per_day", None),
            candidates=list(tape_candidates),
            errors=errors,
        )

    return LpSnapshot(
        wallet=None,
        provenance=PROVENANCE_UNKNOWN,
        candidates=list(tape_candidates),
        errors=errors,
    )
