"""The daily re-verify sweep: batched, spread over ~an hour, and outage-safe.

Design constraints, in order of importance:

1. A PROVIDER ERROR NEVER EJECTS ANYONE. Any Helius failure (after one retry)
   aborts the whole day's sweep, alerts the operator, and marks the day skipped.
   Grace clocks that were already running simply wait for the next good sweep.
2. The bot keeps answering DMs while the sweep runs. So the sweep never sleeps:
   it is an incremental plan — one batch per poll cycle once the inter-batch gap
   has elapsed — and the long-poll loop supplies the spacing.
3. Restart-safe and idempotent: the day marker is written only at completion (or
   skip), and every DM/eject carries a (day, user) dedup key, so a mid-sweep
   crash re-runs the day without double-warning or double-ejecting.

Transitions per member:
  balance >= N            -> status ok (a DM celebrates recovery from grace)
  balance < N, was ok     -> status grace (48h), warning DM
  balance < N, in grace   -> nothing until grace_until, then ban + immediate
                             unban (eject; rejoin allowed after /verify) + DM
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import Config
from .gateway import GateGateway, format_tokens
from .helius import Helius, HeliusError
from .state import GateState

log = logging.getLogger(__name__)

SWEEP_DAY_KEY = "last_sweep_day"
SWEEP_RESULT_KEY = "last_sweep_result"


def utc_day(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")


def utc_hour(now: float) -> int:
    return datetime.fromtimestamp(now, tz=timezone.utc).hour


@dataclass
class SweepPlan:
    day: str
    pending: list[int] = field(default_factory=list)
    next_batch_at: float = 0.0
    checked: int = 0
    warned: int = 0
    ejected: int = 0
    restored: int = 0


class Sweeper:
    def __init__(
        self,
        config: Config,
        state: GateState,
        gateway: GateGateway,
        helius: Helius,
        *,
        clock=time.time,
    ):
        self.config = config
        self.state = state
        self.gateway = gateway
        self.helius = helius
        self.clock = clock
        self.plan: SweepPlan | None = None

    def _due(self, now: float) -> bool:
        day = utc_day(now)
        if self.state.day_marker(SWEEP_DAY_KEY) == day:
            return False
        return utc_hour(now) >= self.config.sweep_hour_utc

    def _batch_gap(self, member_count: int) -> float:
        batches = max(1, -(-member_count // self.config.sweep_batch_size))
        return self.config.sweep_spread_seconds / batches

    async def _balance_with_retry(self, wallet: str) -> int:
        try:
            return await self.helius.balance_raw(wallet, self.config.mint)
        except HeliusError:
            return await self.helius.balance_raw(wallet, self.config.mint)

    def _skip(self, day: str, reason: str) -> None:
        """Skip THE DAY: no ejection may ride on a provider outage."""

        self.plan = None
        self.state.set_day_marker(SWEEP_DAY_KEY, day)
        self.state.set_day_marker(SWEEP_RESULT_KEY, f"{day} skipped: {reason}"[:200])
        self.gateway.alert_operator(
            f"re-verify sweep for {day} SKIPPED ({reason}); nobody was warned or ejected",
            f"sweep:{day}:skipped",
        )
        log.error("sweep skipped for %s (%s)", day, reason)

    async def tick(self) -> None:
        """Called once per poll cycle; starts, advances, or finishes the day's plan."""

        now = self.clock()
        if self.plan is None:
            if not self._due(now):
                return
            members = [m for m in self.state.members() if m.status != "ejected"]
            self.plan = SweepPlan(day=utc_day(now), pending=[m.tg_user_id for m in members])
            log.info("sweep started for %s (%d members)", self.plan.day, len(members))
            if not members:
                self._finish(now)
                return
        if now < self.plan.next_batch_at:
            return
        await self._run_batch(now)

    async def _run_batch(self, now: float) -> None:
        plan = self.plan
        assert plan is not None
        try:
            # Pins decimals once; per-member effective thresholds are computed below.
            await self.gateway.threshold_raw()
        except HeliusError as exc:
            self._skip(plan.day, str(exc))
            return
        batch, plan.pending = (
            plan.pending[: self.config.sweep_batch_size],
            plan.pending[self.config.sweep_batch_size :],
        )
        for uid in batch:
            member = self.state.member(uid)
            if member is None or member.status == "ejected":
                continue
            try:
                balance = await self._balance_with_retry(member.wallet)
            except HeliusError as exc:
                self._skip(plan.day, str(exc))
                return
            self.state.record_balance(uid, balance, self.clock())
            plan.checked += 1
            needed = await self.gateway.threshold_raw(uid)
            self._apply(plan, member, balance, needed)
        if plan.pending:
            plan.next_batch_at = now + self._batch_gap(plan.checked + len(plan.pending))
        else:
            self._finish(self.clock())

    def _apply(self, plan: SweepPlan, member, balance: int, needed: int) -> None:
        decimals = self.state.mint_decimals or 0
        uid = member.tg_user_id
        now = self.clock()
        if balance >= needed:
            if member.status == "grace":
                self.state.set_member_status(uid, "ok", None)
                self.gateway.dm(
                    uid,
                    f"Back above the threshold ({format_tokens(balance, decimals)} $DREGG). "
                    "Your seat is safe.",
                    f"sweep:{plan.day}:{uid}:restored",
                )
                plan.restored += 1
            return
        if member.status == "ok":
            self.state.set_member_status(uid, "grace", now + self.config.grace_seconds)
            self.gateway.dm(
                uid,
                f"Heads up: your wallet holds {format_tokens(balance, decimals)} $DREGG, below the "
                f"{self.gateway.effective_tokens(uid):,} threshold. You have {self.config.grace_hours}h to "
                "top up before removal from the holders group.",
                f"sweep:{plan.day}:{uid}:warn",
            )
            plan.warned += 1
            return
        # status == 'grace'
        if member.grace_until is not None and now < member.grace_until:
            return
        group_id = self.state.group_id
        if group_id is None:
            self.gateway.alert_operator(
                "a grace period expired but no group is bound; cannot eject — /bind the group",
                f"sweep:{plan.day}:unbound",
            )
            return
        # Eject: ban then immediate unban (ordered outbox), so rejoin stays possible
        # after a future re-verify. only_if_banned keeps a retried unban from ever
        # kicking someone on its own.
        self.state.enqueue(
            f"eject:{plan.day}:{uid}:ban",
            "banChatMember",
            {"chat_id": group_id, "user_id": uid},
        )
        self.state.enqueue(
            f"eject:{plan.day}:{uid}:unban",
            "unbanChatMember",
            {"chat_id": group_id, "user_id": uid, "only_if_banned": True},
        )
        self.state.set_member_status(uid, "ejected", None)
        self.gateway.dm(
            uid,
            "Your grace period ended below the threshold, so you've been removed from the "
            "holders group. Stack back up and /verify to rejoin any time.",
            f"sweep:{plan.day}:{uid}:ejected",
        )
        plan.ejected += 1

    def _finish(self, now: float) -> None:
        plan = self.plan
        assert plan is not None
        self.plan = None
        self.state.set_day_marker(SWEEP_DAY_KEY, plan.day)
        result = (
            f"{plan.day} ok: checked={plan.checked} warned={plan.warned} "
            f"ejected={plan.ejected} restored={plan.restored}"
        )
        self.state.set_day_marker(SWEEP_RESULT_KEY, result)
        log.info("sweep finished: %s", result)
