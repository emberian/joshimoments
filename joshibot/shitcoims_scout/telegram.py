from __future__ import annotations

import logging

import httpx

from .state import ScoutState

log = logging.getLogger(__name__)


class TelegramError(RuntimeError):
    pass


class Telegram:
    def __init__(self, token: str, http: httpx.AsyncClient, state: ScoutState):
        self._base = f"https://api.telegram.org/bot{token}"
        self.http = http
        self.state = state

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
            response.raise_for_status()
            body = response.json()
            updates = body.get("result") if isinstance(body, dict) else None
            if body.get("ok") is not True or not isinstance(updates, list):
                raise ValueError("malformed getUpdates response")
            return [value for value in updates if isinstance(value, dict)]
        except httpx.ReadTimeout:
            return []
        except Exception as exc:
            raise TelegramError(f"Telegram polling failed ({type(exc).__name__})") from None

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        try:
            response = await self.http.post(
                self._base + "/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": text[:200]},
            )
            response.raise_for_status()
        except Exception as exc:
            # Do not stringify errors: the request URL contains the bot token.
            log.warning("Telegram callback acknowledgement failed (%s)", type(exc).__name__)

    async def flush_outbox(self) -> None:
        for item in self.state.pending():
            try:
                response = await self.http.post(self._base + f"/{item.method}", json=item.payload)
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict) or body.get("ok") is not True:
                    raise ValueError("Telegram rejected outbox message")
                self.state.delivered(item.id)
            except Exception as exc:
                # Preserve ordering and retry later; never print token-bearing request URLs.
                self.state.delivery_failed(item.id, type(exc).__name__, item.attempts + 1)
                log.error("Telegram outbox delivery failed (%s)", type(exc).__name__)
                break
