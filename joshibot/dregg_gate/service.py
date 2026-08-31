"""The gate service loop: ONE process, one long-poll, every lane on the same tick.

Each cycle:
1. Re-read config (keep-last-good: a broken edit changes nothing and says so).
2. Flush the durable outbox; alert the operator about dropped ban/unban actions.
3. Present any new approval requests to the operator DM.
4. Advance the daily re-verify sweep by at most one batch (never blocks polling).
5. Send the once-a-day operator heartbeat DM; write the heartbeat JSON.
6. Long-poll getUpdates (this IS the tick's pacing) and process each update.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from .config import Config, GateConfigError
from .gateway import GateGateway
from .helius import Helius
from .state import GateState
from .sweep import SWEEP_RESULT_KEY, Sweeper, utc_day
from .telegram import PollerConflict, Telegram, TelegramError

log = logging.getLogger(__name__)

HEARTBEAT_DAY_KEY = "last_heartbeat_day"


class GateService:
    def __init__(
        self,
        config_path: Path,
        config: Config,
        state: GateState,
        telegram: Telegram,
        helius: Helius,
        *,
        clock=time.time,
    ):
        self.config_path = config_path
        self.cfg = config
        self.cfg_status = "ok"
        self.state = state
        self.telegram = telegram
        self.helius = helius
        self.clock = clock
        self.gateway = GateGateway(config, state, telegram, helius, clock=clock)
        self.sweeper = Sweeper(config, state, self.gateway, helius, clock=clock)
        self.cycle_n = 0

    def _reload_config(self) -> None:
        """Keep-last-good: the running config only changes when the file parses whole."""

        try:
            fresh = Config.load(self.config_path)
        except GateConfigError as exc:
            self.cfg_status = f"kept_last_good: {exc}"
            return
        if fresh.db_path != self.cfg.db_path:
            self.cfg_status = "kept_last_good: db_path cannot change while running"
            return
        self.cfg = fresh
        self.cfg_status = "ok"
        self.gateway.config = fresh
        self.sweeper.config = fresh

    def _alert_drops(self) -> None:
        for method, description in self.telegram.drain_dropped():
            if method in ("banChatMember", "unbanChatMember"):
                self.gateway.alert_operator(
                    f"Telegram permanently rejected {method}: {description or 'no description'}",
                    f"drop:{time.time_ns()}",
                )

    def _daily_heartbeat(self) -> None:
        day = utc_day(self.clock())
        if self.state.day_marker(HEARTBEAT_DAY_KEY) == day:
            return
        self.state.set_day_marker(HEARTBEAT_DAY_KEY, day)
        counts = self.state.member_counts()
        group = self.state.group_id
        lines = [
            f"gate heartbeat {day}",
            f"members: {counts['ok']} ok, {counts['grace']} in grace, {counts['ejected']} ejected",
            f"group: {'bound (' + str(group) + ')' if group is not None else 'NOT BOUND — /bind pending'}",
            f"last sweep: {self.state.day_marker(SWEEP_RESULT_KEY) or 'never'}",
            f"approvals awaiting decision: {self.state.pending_approval_count()}",
            f"config: {self.cfg_status}",
        ]
        self.gateway.dm(self.cfg.operator_chat_id, "\n".join(lines), f"heartbeat:{day}")

    def write_heartbeat(self) -> dict:
        now = self.clock()
        counts = self.state.member_counts()
        payload = {
            "t": now,
            "cycle": self.cycle_n,
            "config_status": self.cfg_status,
            "group_bound": self.state.group_id is not None,
            "members": counts,
            "sweep": {
                "active": self.sweeper.plan is not None,
                "last_result": self.state.day_marker(SWEEP_RESULT_KEY),
            },
            "approvals_pending": self.state.pending_approval_count(),
            "outbox_depth": len(self.state.pending(limit=1000)),
        }
        path = self.cfg.heartbeat_path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
        tmp.replace(path)
        return payload

    async def cycle(self) -> None:
        self.cycle_n += 1
        self._reload_config()
        await self.telegram.flush_outbox()
        self._alert_drops()
        self.gateway.present_approvals()
        await self.sweeper.tick()
        self._daily_heartbeat()
        try:
            self.write_heartbeat()
        except OSError as exc:
            log.error("heartbeat write failed (%s)", type(exc).__name__)
        last = self.state.last_update_id
        updates = await self.telegram.updates(
            last + 1 if last is not None else None,
            self.cfg.poll_timeout_seconds,
        )
        for update in updates:
            await self.gateway.process_update(update)
            await self.telegram.flush_outbox()

    async def run(self) -> None:
        username = await self.telegram.probe()
        log.info("dregg gate authenticated as @%s", username)
        while True:
            try:
                await self.cycle()
            except PollerConflict as exc:
                # Alert rides the outbox: sendMessage still works during a
                # getUpdates conflict, so the next cycle's flush delivers it.
                self.gateway.alert_operator(
                    f"poller conflict: {exc} — check for a stale gate or scout process",
                    f"conflict:{utc_day(self.clock())}",
                )
                log.error("%s", exc)
                await asyncio.sleep(10)
            except TelegramError as exc:
                log.error("%s", exc)
                await asyncio.sleep(2)


async def run_service(config_path: Path, config: Config, token: str, helius_key: str) -> None:
    state = GateState(config.db_path)
    try:
        async with (
            httpx.AsyncClient(
                timeout=httpx.Timeout(15, connect=5), follow_redirects=False
            ) as telegram_http,
            httpx.AsyncClient(
                timeout=httpx.Timeout(20, connect=5), follow_redirects=False
            ) as helius_http,
        ):
            telegram = Telegram(token, telegram_http, state)
            helius = Helius(helius_key, helius_http)
            await GateService(config_path, config, state, telegram, helius).run()
    finally:
        state.close()
