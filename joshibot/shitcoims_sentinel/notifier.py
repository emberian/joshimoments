from __future__ import annotations

import logging

import httpx

from .config import NotificationConfig
from .secrets import read_secret_file
from .storage import EventJournal

log = logging.getLogger(__name__)


class Notifier:
    def __init__(
        self,
        config: NotificationConfig,
        http: httpx.AsyncClient,
        journal: EventJournal,
    ):
        self.config = config
        self.http = http
        self.journal = journal
        self._telegram_token = (
            read_secret_file(config.telegram_bot_token_file, required=False)
            if config.telegram_bot_token_file
            else None
        )
        self._telegram_verified = False
        self._telegram_probe_attempted = False
        self.telegram_last_error_type: str | None = None

    @property
    def telegram_configured(self) -> bool:
        return bool(self._telegram_token and self.config.telegram_chat_id)

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_configured and self._telegram_verified)

    async def probe(self) -> bool:
        if self._telegram_probe_attempted:
            return self.telegram_ready
        self._telegram_probe_attempted = True
        if not self.telegram_configured:
            return False
        assert self._telegram_token is not None
        try:
            me = await self.http.get(f"https://api.telegram.org/bot{self._telegram_token}/getMe")
            me.raise_for_status()
            me_body = me.json()
            chat = await self.http.get(
                f"https://api.telegram.org/bot{self._telegram_token}/getChat",
                params={"chat_id": self.config.telegram_chat_id},
            )
            chat.raise_for_status()
            chat_body = chat.json()
            if (
                not isinstance(me_body, dict)
                or me_body.get("ok") is not True
                or not isinstance(chat_body, dict)
                or chat_body.get("ok") is not True
                or (chat_body.get("result") or {}).get("type") != "private"
            ):
                raise ValueError("Telegram readiness response was invalid")
            self._telegram_verified = True
            self.telegram_last_error_type = None
        except Exception as exc:
            # Never stringify Telegram exceptions: the token is part of the URL.
            self._telegram_verified = False
            self.telegram_last_error_type = type(exc).__name__
            log.error("Telegram readiness probe failed (%s)", type(exc).__name__)
        return self.telegram_ready

    async def send(
        self,
        *,
        severity: str,
        category: str,
        message: str,
        context: dict | None = None,
        dedup_key: str | None = None,
        dedup_seconds: float = 300,
    ) -> None:
        event = self.journal.emit(
            severity=severity,
            category=category,
            message=message,
            context=context,
            dedup_key=dedup_key,
            dedup_seconds=dedup_seconds,
        )
        if event is None:
            return
        line = f"[{severity.upper()}] [{category}] {message}"
        if severity == "critical":
            log.critical(line)
        elif severity == "warning":
            log.warning(line)
        else:
            log.info(line)
        if not self.telegram_ready:
            return
        assert self._telegram_token is not None
        try:
            response = await self.http.post(
                f"https://api.telegram.org/bot{self._telegram_token}/sendMessage",
                json={"chat_id": self.config.telegram_chat_id, "text": message},
            )
            response.raise_for_status()
            self._telegram_verified = True
            self.telegram_last_error_type = None
        except Exception as exc:
            # Never stringify the request: the Telegram token is embedded in its URL.
            log.error("Telegram delivery failed (%s)", type(exc).__name__)
            self._telegram_verified = False
            self.telegram_last_error_type = type(exc).__name__
            self.journal.emit(
                severity="critical",
                category="notification",
                message="Telegram delivery failed; stdout/stderr remain active",
                context={"error_type": type(exc).__name__},
                dedup_key="telegram-delivery-failed",
            )


async def telegram_bot_identity(token: str, http: httpx.AsyncClient) -> tuple[str, bool, int]:
    """Return username, webhook-present flag, and pending count without leaking token URLs."""
    try:
        me_response = await http.get(f"https://api.telegram.org/bot{token}/getMe")
        me_response.raise_for_status()
        me = me_response.json()
        webhook_response = await http.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")
        webhook_response.raise_for_status()
        webhook = webhook_response.json()
        username = str((me.get("result") or {})["username"])
        webhook_result = webhook.get("result") or {}
        return (
            username,
            bool(webhook_result.get("url")),
            int(webhook_result.get("pending_update_count") or 0),
        )
    except Exception as exc:
        raise RuntimeError(f"Telegram API unavailable ({type(exc).__name__})") from None


async def telegram_send_test(token: str, chat_id: str, http: httpx.AsyncClient) -> None:
    try:
        chat_response = await http.get(
            f"https://api.telegram.org/bot{token}/getChat",
            params={"chat_id": chat_id},
        )
        chat_response.raise_for_status()
        chat = chat_response.json()
        if (chat.get("result") or {}).get("type") != "private":
            raise ValueError("configured recipient is not a private Telegram chat")
        response = await http.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": "💓 shitcoims Sentinel Telegram test. No trade was executed.",
            },
        )
        response.raise_for_status()
        if response.json().get("ok") is not True:
            raise ValueError("Telegram rejected the test message")
    except Exception as exc:
        raise RuntimeError(f"Telegram test failed ({type(exc).__name__})") from None


async def telegram_confirm_pairing(token: str, chat_id: str, http: httpx.AsyncClient) -> None:
    try:
        response = await http.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": ("✅ shitcoims Sentinel paired with this private chat. No trade was executed."),
            },
        )
        response.raise_for_status()
        if response.json().get("ok") is not True:
            raise ValueError("Telegram rejected the pairing confirmation")
    except Exception as exc:
        raise RuntimeError(f"Telegram pairing confirmation failed ({type(exc).__name__})") from None
