"""Pessimistic shadow marking against the pump.fun constant-product curve.

The rule that keeps shadow honest: a decision NEVER fills at the snapshot that
produced it. Entry fills at the NEXT observation of the mint (so simulated
latency >= one poll interval); exit fills at the FIRST observation at-or-after
the deadline. Both fills walk the constant-product curve on the reserves seen
THEN, pay the swap fee on the way in and out, and pay the priority fee twice.
A shadow return computed this way is a floor.

Integer lamports and raw token units throughout; // division only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CurveState:
    """Virtual reserves of a pump.fun bonding curve at one observation."""

    t_ingest_unix: float
    vsol_lamports: int
    vtok_raw: int

    def __post_init__(self) -> None:
        if self.vsol_lamports <= 0 or self.vtok_raw <= 0:
            raise ValueError("reserves must be positive")


def curve_buy(state: CurveState, spend_lamports: int, *, fee_bps: int) -> int:
    """Tokens out for spending ``spend_lamports`` SOL, fee taken on the SOL side."""
    if spend_lamports <= 0:
        return 0
    effective = spend_lamports * (10_000 - fee_bps) // 10_000
    k = state.vsol_lamports * state.vtok_raw
    new_tok = k // (state.vsol_lamports + effective)
    return state.vtok_raw - new_tok


def curve_sell(state: CurveState, tokens_raw: int, *, fee_bps: int) -> int:
    """SOL out for selling ``tokens_raw`` tokens, fee taken on the SOL side."""
    if tokens_raw <= 0:
        return 0
    k = state.vsol_lamports * state.vtok_raw
    new_sol = k // (state.vtok_raw + tokens_raw)
    gross = state.vsol_lamports - new_sol
    return gross * (10_000 - fee_bps) // 10_000


@dataclass(frozen=True, slots=True)
class ShadowFill:
    decision_id: str
    mint: str
    spend_lamports: int
    tokens_raw: int
    entry_state: CurveState


@dataclass(frozen=True, slots=True)
class ShadowClose:
    decision_id: str
    mint: str
    spend_lamports: int
    proceeds_lamports: int
    priority_fees_lamports: int
    pnl_lamports: int
    entry_t: float
    exit_t: float
    exit_reason: str  # "deadline" | "feed_lost"


class ShadowMarker:
    """Holds pending entries and open fills; marks both on later observations only."""

    def __init__(self, *, fee_bps: int = 100, priority_fee_lamports: int = 500_000) -> None:
        self.fee_bps = fee_bps
        self.priority_fee_lamports = priority_fee_lamports
        self._pending: dict[str, tuple[str, int]] = {}  # decision_id -> (mint, spend)
        self._fills: dict[str, ShadowFill] = {}

    def submit(self, decision_id: str, mint: str, spend_lamports: int) -> None:
        self._pending[decision_id] = (mint, spend_lamports)

    def on_observation(self, mint: str, state: CurveState) -> list[ShadowFill]:
        """Fill every pending entry for this mint at THIS (later) observation."""
        filled: list[ShadowFill] = []
        for decision_id, (m, spend) in list(self._pending.items()):
            if m != mint:
                continue
            tokens = curve_buy(state, spend, fee_bps=self.fee_bps)
            del self._pending[decision_id]
            if tokens <= 0:
                continue
            fill = ShadowFill(
                decision_id=decision_id,
                mint=mint,
                spend_lamports=spend,
                tokens_raw=tokens,
                entry_state=state,
            )
            self._fills[decision_id] = fill
            filled.append(fill)
        return filled

    def close(
        self, decision_id: str, state: CurveState | None, *, reason: str = "deadline"
    ) -> ShadowClose | None:
        """Mark the exit at the first at-or-after-deadline observation.

        ``state=None`` means the feed lost the mint before the deadline — scored as a
        total loss of the position, because in live trading an unsellable bag is worth
        its floor, not its last quote. Pessimism is the contract.
        """
        fill = self._fills.pop(decision_id, None)
        if fill is None:
            self._pending.pop(decision_id, None)
            return None
        prio = 2 * self.priority_fee_lamports
        if state is None:
            proceeds = 0
            reason = "feed_lost"
        else:
            proceeds = curve_sell(state, fill.tokens_raw, fee_bps=self.fee_bps)
        return ShadowClose(
            decision_id=decision_id,
            mint=fill.mint,
            spend_lamports=fill.spend_lamports,
            proceeds_lamports=proceeds,
            priority_fees_lamports=prio,
            pnl_lamports=proceeds - fill.spend_lamports - prio,
            entry_t=fill.entry_state.t_ingest_unix,
            exit_t=state.t_ingest_unix if state else fill.entry_state.t_ingest_unix,
            exit_reason=reason,
        )

    @property
    def open_count(self) -> int:
        return len(self._fills)
