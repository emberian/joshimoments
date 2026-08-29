"""Telegram transport for the gate: long-poll, durable ordered outbox, direct calls.

Token hygiene: the bot token is embedded in every request URL, so exceptions are
never stringified into logs — only their type names.

Outbox semantics differ from the single-operator scout in one deliberate way: a
DEFINITIVE Telegram rejection (the API answered ok=false — e.g. a user blocked the
bot, 403) DROPS the item instead of retrying forever. This is a multi-user gate;
one blocked DM must not stall every later delivery behind it. Transport failures
still retry with backoff and preserve strict ordering (ban always lands before its
paired unban or neither does).
"""

from __future__ import annotations

import logging

import httpx

from .state import GateState

log = logging.getLogger(__name__)


class TelegramError(RuntimeError):
    """Transport-level failure: network, timeout, malformed body."""


class TelegramRejection(TelegramError):
    """The API answered ok=false: a definitive no, retrying will not help."""

    def __init__(self, description: str):
        super().__init__(description)
        self.description = description


class PollerConflict(TelegramError):
    """getUpdates answered 409: something else is consuming this bot token."""


class Telegram:
    def __init__(self, token: str, http: httpx.AsyncClient, state: GateState):
        self._base = f"https://api.telegram.org/bot{token}"
        self.http = http
        self.state = state
        self.dropped: list[tuple[str, str]] = []  # (method, description) since last drain

    async def probe(self) -> str:
        try:
            me_response = await self.http.post(self._base + "/getMe")
            me_response.raise_for_status()
            me = me_response.json()
            webhook_response = await self.http.post(self._base + "/getWebhookInfo")
            webhook_response.raise_for_status()
            webhook = webhook_response.json()
            username = str((me.get("result") or {})["username"])
            if (webhook.get("result") or {}).get("url"):
                raise ValueError("webhook configured")
            return username
        except Exception as exc:
            raise TelegramError(f"Telegram readiness failed ({type(exc).__name__})") from None

    async def updates(self, offset: int | None, poll_seconds: int) -> list[dict]:
        payload: dict[str, object] = {
            "timeout": poll_seconds,
            "limit": 20,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        try:
            response = await self.http.post(
                self._base + "/getUpdates",
                json=payload,
                timeout=httpx.Timeout(poll_seconds + 10, connect=5),
            )
            if response.status_code == 409:
                # Another consumer is polling this token. The flock stops our own
                # doubles; this catches a remote or stale one. sendMessage still
                # works during a conflict, so the operator alert can get out.
                raise PollerConflict("another getUpdates consumer holds this bot token")
            response.raise_for_status()
            body = response.json()
            updates = body.get("result") if isinstance(body, dict) else None
            if body.get("ok") is not True or not isinstance(updates, list):
                raise ValueError("malformed getUpdates response")
            return [value for value in updates if isinstance(value, dict)]
        except PollerConflict:
            raise
        except httpx.ReadTimeout:
            return []
        except Exception as exc:
            raise TelegramError(f"Telegram polling failed ({type(exc).__name__})") from None

    async def call(self, method: str, payload: dict) -> dict:
        """Direct call for methods whose RESPONSE matters (createChatInviteLink, ...)."""

        try:
            response = await self.http.post(self._base + f"/{method}", json=payload)
            body = response.json()
        except Exception as exc:
            raise TelegramError(f"Telegram {method} failed ({type(exc).__name__})") from None
        if not isinstance(body, dict) or body.get("ok") is not True:
            description = body.get("description") if isinstance(body, dict) else None
            raise TelegramRejection(str(description or f"Telegram rejected {method}"))
        result = body.get("result")
        return result if isinstance(result, dict) else {"result": result}

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        try:
            response = await self.http.post(
                self._base + "/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": text[:200]},
            )
            response.raise_for_status()
        except Exception as exc:
            log.warning("Telegram callback acknowledgement failed (%s)", type(exc).__name__)

    async def flush_outbox(self) -> None:
        for item in self.state.pending():
            try:
                response = await self.http.post(self._base + f"/{item.method}", json=item.payload)
                body = response.json()
            except Exception as exc:
                # Transport failure: retry later, keep strict order.
                self.state.delivery_failed(item.id, type(exc).__name__, item.attempts + 1)
                log.error("Telegram outbox delivery failed (%s)", type(exc).__name__)
                break
            if isinstance(body, dict) and body.get("ok") is True:
                self.state.delivered(item.id)
                continue
            description = str(body.get("description", "")) if isinstance(body, dict) else ""
            if response.status_code >= 500 or not isinstance(body, dict):
                # Server-side trouble is transient; retry in order.
                self.state.delivery_failed(item.id, f"http_{response.status_code}", item.attempts + 1)
                log.error("Telegram outbox delivery deferred (http %s)", response.status_code)
                break
            # Definitive rejection (400/403): drop so it cannot dam the queue.
            self.state.delivered(item.id)
            self.dropped.append((item.method, description[:200]))
            log.error("Telegram permanently rejected %s: %s", item.method, description[:200])

    def drain_dropped(self) -> list[tuple[str, str]]:
        drops, self.dropped = self.dropped, []
        return drops
