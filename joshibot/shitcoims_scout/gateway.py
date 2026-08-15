from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import replace

from .commands import ParsedCommand, parse_command
from .config import ScoutConfig
from .desk import (
    SL_PRESETS,
    TP_PRESETS,
    TRAIL_PRESETS,
    bags_from_snapshot,
    default_policy_body,
    render_bag,
    render_candidates,
    render_desk,
)
from .local_api import LocalAPI, LocalAPIError, Query, render_payload
from .state import Callback, ScoutState
from .telegram import Telegram, TelegramError

log = logging.getLogger(__name__)

CALLBACK_DATA = re.compile(r"scout:([A-Za-z0-9_-]{20,40})\Z")


class ScoutGateway:
    def __init__(
        self,
        config: ScoutConfig,
        state: ScoutState,
        telegram: Telegram,
        local_api: LocalAPI,
        *,
        clock=time.time,
    ):
        if config.telegram_chat_id is None or config.telegram_user_id is None:
            raise ValueError("Scout requires exact Telegram chat and user IDs")
        self.config = config
        self.state = state
        self.telegram = telegram
        self.local_api = local_api
        self.clock = clock

    def _authorized_message(self, message: object, *, require_fresh: bool) -> bool:
        if not isinstance(message, dict):
            return False
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            return False
        if (
            chat.get("type") != "private"
            or str(chat.get("id")) != self.config.telegram_chat_id
            or str(sender.get("id")) != self.config.telegram_user_id
            or sender.get("is_bot") is not False
        ):
            return False
        if not require_fresh:
            return True
        sent_at = message.get("date")
        if isinstance(sent_at, bool) or not isinstance(sent_at, (int, float)):
            return False
        age = self.clock() - sent_at
        return -30 <= age <= self.config.message_max_age_seconds

    def _keyboard(self, command: str, query: Query, payload: object) -> dict:
        rows = []
        refresh = self.state.create_callback("refresh", {"command": command})
        row = [{"text": "↻ Refresh", "callback_data": f"scout:{refresh}"}]
        if isinstance(payload, dict):
            item = payload.get("item")
            items = payload.get("items")
            signal = payload.get("signal_id") or payload.get("id")
            if signal is None and isinstance(item, dict):
                signal = item.get("id")
            if signal is None and isinstance(items, list) and items and isinstance(items[0], dict):
                signal = items[0].get("id")
            if query.action != "why" and isinstance(signal, str) and len(signal) <= 64:
                evidence = self.state.create_callback("evidence", {"signal_id": signal})
                row.insert(0, {"text": "Evidence", "callback_data": f"scout:{evidence}"})
            cursor = payload.get("next_cursor")
            if isinstance(cursor, str) and 0 < len(cursor) <= 256:
                page = self.state.create_callback("page", {"command": command, "cursor": cursor})
                rows.append([{"text": "Next >", "callback_data": f"scout:{page}"}])
        rows.insert(0, row)
        return {"inline_keyboard": rows}

    async def _execute(self, parsed: ParsedCommand, command: str) -> tuple[str, dict | None]:
        if parsed.kind == "desk":
            return await self._desk_home()
        if parsed.kind == "candidates":
            return await self._candidates()
        if parsed.query is None:
            return parsed.message or "Use /help.", None
        try:
            payload = await self.local_api.get(parsed.query)
        except LocalAPIError as exc:
            return f"⚠️ {exc}", None
        return (
            render_payload(parsed.query.title, payload, action=parsed.query.action),
            self._keyboard(command, parsed.query, payload),
        )

    def _enqueue_response(
        self,
        update_id: int,
        text: str,
        keyboard: dict | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "chat_id": self.config.telegram_chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if keyboard is not None:
            payload["reply_markup"] = keyboard
        self.state.enqueue(f"update:{update_id}", "sendMessage", payload)

    async def _message(self, update_id: int, message: object) -> None:
        if not self._authorized_message(message, require_fresh=True):
            log.warning("Ignored unauthorized or stale Telegram message update %s", update_id)
            return
        assert isinstance(message, dict)
        text = message.get("text")
        parsed = parse_command(text)
        command = text if isinstance(text, str) else "/help"
        response, keyboard = await self._execute(parsed, command)
        self._enqueue_response(update_id, response, keyboard)

    def _callback_command(self, callback: Callback) -> tuple[ParsedCommand, str]:
        if callback.action == "evidence":
            signal_id = callback.parameters.get("signal_id")
            command = f"/why {signal_id}"
            return parse_command(command), command
        command = callback.parameters.get("command")
        if not isinstance(command, str):
            return ParsedCommand("invalid", message="This button is invalid."), "/help"
        parsed = parse_command(command)
        if callback.action == "page" and parsed.query is not None:
            cursor = callback.parameters.get("cursor")
            if not isinstance(cursor, str) or not 0 < len(cursor) <= 256:
                return ParsedCommand("invalid", message="This page button is invalid."), command
            parsed = replace(
                parsed,
                query=replace(parsed.query, params={**parsed.query.params, "cursor": cursor}),
            )
        return parsed, command

    async def _callback(self, update_id: int, raw: object) -> None:
        if not isinstance(raw, dict):
            return
        message = raw.get("message")
        synthetic = {
            "chat": message.get("chat") if isinstance(message, dict) else None,
            "from": raw.get("from"),
        }
        if not self._authorized_message(synthetic, require_fresh=False):
            log.warning("Ignored unauthorized Telegram callback update %s", update_id)
            return
        callback_id = raw.get("id")
        data = raw.get("data")
        if not isinstance(callback_id, str):
            return
        desk_actions = {
            "desk",
            "bag",
            "protect",
            "skip",
            "sl",
            "tp",
            "trail",
            "rug",
            "delete",
            "candidates",
        }
        match = CALLBACK_DATA.fullmatch(data) if isinstance(data, str) else None
        # Peek action without consuming so we can answer the spinner honestly.
        preview = None
        if match:
            preview = self.state.consume_callback(match.group(1))
        ack = "Updating desk…" if preview and preview.action in desk_actions else "Refreshing…"
        await self.telegram.answer_callback(callback_id, ack)
        if preview is None:
            self._enqueue_response(update_id, "This button expired or was already used. Refresh the command.")
            return
        if preview.action in desk_actions:
            response, keyboard = await self._desk_action(preview)
            self._enqueue_response(update_id, response, keyboard)
            return
        parsed, command = self._callback_command(preview)
        response, keyboard = await self._execute(parsed, command)
        self._enqueue_response(update_id, response, keyboard)

    async def _snapshot_and_policies(self) -> tuple[dict, list]:
        snapshot = await self.local_api.get(Query("sentinel", "/api/snapshot", {}, "Desk", "portfolio"))
        policies = await self.local_api.get(Query("sentinel", "/api/policies", {}, "Policies", "policies"))
        if not isinstance(snapshot, dict):
            raise LocalAPIError("snapshot unavailable")
        items = policies.get("items") if isinstance(policies, dict) else None
        return snapshot, items if isinstance(items, list) else []

    def _btn(self, text: str, action: str, parameters: dict) -> dict[str, str]:
        handle = self.state.create_callback(action, parameters)
        return {"text": text[:64], "callback_data": f"scout:{handle}"}

    def _desk_keyboard(self, bags) -> dict:
        rows = [
            [self._btn("↻ Desk", "desk", {})],
            [self._btn("Candidates", "candidates", {})],
        ]
        for bag in bags[:8]:
            label = f"{bag.name} · {bag.exit_sol or '?'} SOL"
            rows.append([self._btn(label, "bag", {"mint": bag.mint})])
        return {"inline_keyboard": rows}

    def _bag_keyboard(self, bag) -> dict:
        rows = [
            [self._btn(f"SL {value}%", "sl", {"mint": bag.mint, "value": value}) for value in SL_PRESETS],
            [self._btn(f"TP {value}%", "tp", {"mint": bag.mint, "value": value}) for value in TP_PRESETS],
            [
                self._btn(
                    f"Trail {value}%" if bag.exit_style == "fixed_trail" else f"Tight {value}",
                    "trail",
                    {"mint": bag.mint, "value": value},
                )
                for value in TRAIL_PRESETS
            ],
            [self._btn("Rug on/off", "rug", {"mint": bag.mint})],
            [
                self._btn("Protect now", "protect", {"mint": bag.mint}),
                self._btn("Skip 10m auto", "skip", {"mint": bag.mint}),
            ],
        ]
        if bag.kind == "protected":
            rows.append([self._btn("Delete rule", "delete", {"mint": bag.mint})])
        rows.append([self._btn("← Desk", "desk", {})])
        return {"inline_keyboard": rows}

    async def _desk_home(self) -> tuple[str, dict | None]:
        try:
            snapshot, policies = await self._snapshot_and_policies()
        except LocalAPIError as exc:
            return f"⚠️ {exc}", None
        bags = bags_from_snapshot(snapshot, policies)
        return render_desk(snapshot, policies), self._desk_keyboard(bags)

    def _candidates_keyboard(self) -> dict:
        return {
            "inline_keyboard": [
                [self._btn("↻ Candidates", "candidates", {})],
                [self._btn("← Desk", "desk", {})],
            ]
        }

    async def _candidates(self) -> tuple[str, dict | None]:
        payload: object | None = None
        try:
            payload = await self.local_api.get(
                Query("intel", "/api/intelligence/candidates", {}, "Candidates", "candidates")
            )
        except LocalAPIError:
            payload = None
        return render_candidates(payload), self._candidates_keyboard()

    async def _desk_action(self, callback: Callback) -> tuple[str, dict | None]:
        if callback.action == "desk":
            return await self._desk_home()
        if callback.action == "candidates":
            return await self._candidates()
        mint = callback.parameters.get("mint")
        if not isinstance(mint, str) or not (32 <= len(mint) <= 44):
            return "That bag button is invalid.", None
        try:
            snapshot, policies = await self._snapshot_and_policies()
        except LocalAPIError as exc:
            return f"⚠️ {exc}", None
        bags = bags_from_snapshot(snapshot, policies)
        bag = next((item for item in bags if item.mint == mint), None)
        if bag is None:
            return await self._desk_home()
        if callback.action == "bag":
            return render_bag(bag), self._bag_keyboard(bag)
        if callback.action == "skip":
            try:
                await self.local_api.post_json(f"/api/policies/{mint}/skip-auto", {})
            except LocalAPIError as exc:
                return f"⚠️ {exc}", self._bag_keyboard(bag)
            return (
                f"Skipped the 10m default for {bag.name}. Still observe-only. Cannot sell.",
                self._bag_keyboard(bag),
            )
        if callback.action == "protect":
            try:
                await self.local_api.put_json(f"/api/policies/{mint}", default_policy_body(bag))
            except LocalAPIError as exc:
                return f"⚠️ {exc}", self._bag_keyboard(bag)
            snapshot, policies = await self._snapshot_and_policies()
            bags = bags_from_snapshot(snapshot, policies)
            bag = next((item for item in bags if item.mint == mint), bag)
            return f"Wrote YAML for {bag.name}. Cannot sell.\n\n{render_bag(bag)}", self._bag_keyboard(bag)
        if callback.action == "delete":
            try:
                await self.local_api.delete_json(f"/api/policies/{mint}")
            except LocalAPIError as exc:
                return f"⚠️ {exc}", self._bag_keyboard(bag)
            snapshot, policies = await self._snapshot_and_policies()
            bags = bags_from_snapshot(snapshot, policies)
            return (
                f"Removed YAML rule for {bag.name}. Cannot sell.\n\n{render_desk(snapshot, policies)}",
                self._desk_keyboard(bags),
            )

        body = default_policy_body(bag)
        # A preset button carries its own number. When it does not, the field is left out
        # of the body entirely rather than being back-filled from a desk-local constant.
        pressed = callback.parameters.get("value")
        field = {"sl": "stop_loss_pct", "tp": "take_profit_pct", "trail": "trailing_stop_pct"}.get(
            callback.action
        )
        if field is not None and pressed is not None:
            body[field] = pressed
        elif callback.action == "rug":
            body["rug_exit"] = not bool(bag.rug_exit)
        try:
            await self.local_api.put_json(f"/api/policies/{mint}", body)
        except LocalAPIError as exc:
            return f"⚠️ {exc}", self._bag_keyboard(bag)
        snapshot, policies = await self._snapshot_and_policies()
        bags = bags_from_snapshot(snapshot, policies)
        bag = next((item for item in bags if item.mint == mint), bag)
        return render_bag(bag), self._bag_keyboard(bag)

    async def process_update(self, update: dict) -> None:
        update_id = update.get("update_id")
        if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
            return
        current = self.state.last_update_id
        if current is not None and update_id <= current:
            return
        try:
            if "message" in update:
                await self._message(update_id, update.get("message"))
            elif "callback_query" in update:
                await self._callback(update_id, update.get("callback_query"))
        except Exception as exc:
            # Never let one malformed update kill the sole durable consumer.
            log.error("Scout update processing failed (%s)", type(exc).__name__)
            self._enqueue_response(update_id, "⚠️ Scout could not process that request.")
        finally:
            self.state.advance_cursor(update_id)

    async def cycle(self) -> None:
        await self.telegram.flush_outbox()
        last = self.state.last_update_id
        updates = await self.telegram.updates(
            last + 1 if last is not None else None,
            self.config.poll_timeout_seconds,
        )
        for update in updates:
            await self.process_update(update)
            await self.telegram.flush_outbox()

    async def run(self) -> None:
        username = await self.telegram.probe()
        log.info("shitcoims Scout authenticated as @%s; read-only gateway ready", username)
        while True:
            try:
                await self.cycle()
            except TelegramError as exc:
                log.error("%s", exc)
                await asyncio.sleep(2)
