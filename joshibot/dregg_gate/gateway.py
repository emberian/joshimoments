"""The gate gateway: multi-user verify/status/invite, operator lane, group /bind.

This is deliberately NOT the scout gateway (which is pinned to one operator).
Any human may DM the bot; what they can do is decided per message:

- anyone, in a private chat: /start /help /verify /status /invite, or a pasted
  base58 signature answering their live challenge
- the operator, in a private chat: additionally /pending, and the inline
  approve/reject buttons the approvals presenter pushes
- the operator, inside the (future) gated group: /bind records that group's id

Replies ride the durable outbox keyed by update id, so a crash between
processing and delivery re-sends rather than double-processes. The one direct
call in the flow is createChatInviteLink, whose response (the link) we need.
"""

from __future__ import annotations

import logging
import re
import time

from .config import Config
from .helius import Helius, HeliusError
from .state import Challenge, GateState
from .telegram import Telegram, TelegramError
from .verify import build_challenge, new_nonce, parse_pubkey, parse_signature, signature_matches

log = logging.getLogger(__name__)

CALLBACK_DATA = re.compile(r"gate:(a|r):([0-9]{1,12})\Z")

HELP_TEXT = (
    "This bot gates the $DREGG holders group.\n\n"
    "/verify <wallet> — start holder verification for a Solana wallet\n"
    "/status — your current standing\n"
    "/invite — mint a fresh invite link if you are already verified\n\n"
    "Verification: I send a challenge message; sign it with your wallet's "
    "signMessage (any wallet app) and paste the base58 signature back here. "
    "I never ask you to send funds or share keys — only a signature."
)


def format_tokens(raw: int, decimals: int) -> str:
    scale = 10**decimals
    whole, frac = divmod(raw, scale)
    text = f"{whole:,}"
    if frac:
        text += f".{frac:0{decimals}d}".rstrip("0")
    return text


class GateGateway:
    def __init__(
        self,
        config: Config,
        state: GateState,
        telegram: Telegram,
        helius: Helius,
        *,
        clock=time.time,
    ):
        self.config = config
        self.state = state
        self.telegram = telegram
        self.helius = helius
        self.clock = clock

    # -- plumbing ------------------------------------------------------------------

    def dm(self, chat_id: int, text: str, dedup: str, keyboard: dict | None = None) -> None:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if keyboard is not None:
            payload["reply_markup"] = keyboard
        self.state.enqueue(dedup, "sendMessage", payload)

    def alert_operator(self, text: str, dedup: str) -> None:
        self.dm(self.config.operator_chat_id, f"⚠️ {text}", dedup)

    async def threshold_raw(self) -> int:
        """Threshold in raw units; decimals verified on-chain once, then pinned."""

        decimals = self.state.mint_decimals
        if decimals is None:
            decimals = await self.helius.mint_decimals(self.config.mint)
            self.state.record_mint_decimals(decimals)
        return self.config.threshold_tokens * 10**decimals

    def _fresh_human(self, message: dict) -> bool:
        sender = message.get("from")
        if not isinstance(sender, dict) or sender.get("is_bot") is not False:
            return False
        sent_at = message.get("date")
        if isinstance(sent_at, bool) or not isinstance(sent_at, (int, float)):
            return False
        age = self.clock() - sent_at
        return -30 <= age <= self.config.message_max_age_seconds

    # -- update routing ------------------------------------------------------------

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
            # One malformed update must never kill the sole durable consumer.
            log.error("gate update processing failed (%s)", type(exc).__name__)
        finally:
            self.state.advance_cursor(update_id)

    async def _message(self, update_id: int, message: object) -> None:
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        chat_type = chat.get("type")
        if chat_type == "private":
            await self._private_message(update_id, message, chat)
        elif chat_type in ("group", "supergroup"):
            self._group_message(update_id, message, chat)

    # -- group lane: /bind and supergroup migration --------------------------------

    def _group_message(self, update_id: int, message: dict, chat: dict) -> None:
        chat_id = chat.get("id")
        if isinstance(chat_id, bool) or not isinstance(chat_id, int):
            return
        migrated = message.get("migrate_to_chat_id")
        if (
            not isinstance(migrated, bool)
            and isinstance(migrated, int)
            and self.state.group_id == chat_id
        ):
            self.state.bind_group(migrated)
            self.alert_operator(
                f"gated group migrated to supergroup; rebound group id to {migrated}",
                f"update:{update_id}:migrate",
            )
            return
        text = message.get("text")
        sender = message.get("from")
        if not isinstance(text, str) or not isinstance(sender, dict):
            return
        command = text.split()[0].lower().split("@")[0] if text.split() else ""
        if command != "/bind":
            return
        if sender.get("id") != self.config.operator_chat_id or not self._fresh_human(message):
            log.warning("ignored /bind from non-operator in chat %s", chat_id)
            return
        self.state.bind_group(chat_id)
        self.dm(
            self.config.operator_chat_id,
            f"Bound the gated group: chat id {chat_id}. Invite links and ejections now target it.",
            f"update:{update_id}",
        )

    # -- private lane ---------------------------------------------------------------

    async def _private_message(self, update_id: int, message: dict, chat: dict) -> None:
        chat_id = chat.get("id")
        sender = message.get("from")
        text = message.get("text")
        if (
            isinstance(chat_id, bool)
            or not isinstance(chat_id, int)
            or not isinstance(sender, dict)
            or not isinstance(text, str)
        ):
            return
        uid = sender.get("id")
        if isinstance(uid, bool) or not isinstance(uid, int):
            return
        if not self._fresh_human(message):
            log.warning("ignored stale or non-human private message, update %s", update_id)
            return
        parts = text.split()
        command = parts[0].lower().split("@")[0] if parts else ""
        dedup = f"update:{update_id}"
        if command in ("/start", "/help"):
            self.dm(chat_id, HELP_TEXT, dedup)
        elif command == "/verify":
            self._cmd_verify(uid, chat_id, parts[1] if len(parts) > 1 else None, dedup)
        elif command == "/status":
            self._cmd_status(uid, chat_id, dedup)
        elif command == "/invite":
            await self._cmd_invite(uid, chat_id, dedup)
        elif command == "/pending" and uid == self.config.operator_chat_id:
            n = self.state.pending_approval_count()
            self.dm(chat_id, f"{n} approval(s) awaiting a decision.", dedup)
        elif command.startswith("/"):
            self.dm(chat_id, "Unknown command. " + HELP_TEXT, dedup)
        else:
            await self._handle_signature(uid, chat_id, text, dedup)

    def _cmd_verify(self, uid: int, chat_id: int, wallet: str | None, dedup: str) -> None:
        if wallet is None or parse_pubkey(wallet) is None:
            self.dm(chat_id, "Usage: /verify <solana wallet address>", dedup)
            return
        claimed = self.state.member_by_wallet(wallet)
        if claimed is not None and claimed.tg_user_id != uid:
            self.dm(chat_id, "That wallet is already linked to a different Telegram account.", dedup)
            return
        now = self.clock()
        nonce = new_nonce()
        challenge_text = build_challenge(wallet, nonce, now)
        self.state.put_challenge(
            Challenge(
                tg_user_id=uid,
                wallet=wallet,
                nonce=nonce,
                message=challenge_text,
                issued_at=now,
                expires_at=now + self.config.challenge_ttl_seconds,
            )
        )
        self.dm(
            chat_id,
            "Sign this exact message with your wallet's signMessage, then paste the "
            "base58 signature back here:\n\n" + challenge_text,
            dedup,
        )

    async def _handle_signature(self, uid: int, chat_id: int, text: str, dedup: str) -> None:
        challenge = self.state.get_challenge(uid, now=self.clock())
        if challenge is None:
            self.dm(
                chat_id,
                "No live challenge (they expire after 10 minutes). Start with /verify <wallet>.",
                dedup,
            )
            return
        if parse_signature(text) is None:
            self.dm(
                chat_id,
                "That doesn't parse as a base58 signature. Paste only the signature, "
                "or /verify again for a fresh challenge.",
                dedup,
            )
            return
        if not signature_matches(challenge.message, challenge.wallet, text):
            self.dm(
                chat_id,
                f"Signature does not verify for {challenge.wallet}. Make sure that wallet "
                "signed the exact challenge text, then paste again.",
                dedup,
            )
            return
        claimed = self.state.member_by_wallet(challenge.wallet)
        if claimed is not None and claimed.tg_user_id != uid:
            self.state.consume_challenge(uid)
            self.dm(chat_id, "That wallet is already linked to a different Telegram account.", dedup)
            return
        try:
            needed = await self.threshold_raw()
            balance = await self.helius.balance_raw(challenge.wallet, self.config.mint)
        except HeliusError as exc:
            log.error("balance check unavailable (%s)", type(exc).__name__)
            self.dm(
                chat_id,
                "Signature verified, but I can't check balances right now. "
                "Paste the signature again in a few minutes.",
                dedup,
            )
            self.alert_operator(f"Helius error during a /verify balance check: {exc}", dedup + ":helius")
            return
        self.state.consume_challenge(uid)
        decimals = self.state.mint_decimals or 0
        if balance < needed:
            self.dm(
                chat_id,
                f"Wallet holds {format_tokens(balance, decimals)} $DREGG; the gate needs "
                f"{self.config.threshold_tokens:,}. Stack up and /verify again.",
                dedup,
            )
            return
        now = self.clock()
        self.state.record_verification(uid, challenge.wallet, balance, now)
        self.dm(
            chat_id,
            f"Verified: {format_tokens(balance, decimals)} $DREGG. Welcome.",
            dedup,
        )
        await self._grant_invite(uid, chat_id, dedup + ":invite")

    async def _cmd_invite(self, uid: int, chat_id: int, dedup: str) -> None:
        member = self.state.member(uid)
        if member is None:
            self.dm(chat_id, "You're not verified yet. Start with /verify <wallet>.", dedup)
            return
        if member.status == "ejected":
            self.dm(
                chat_id,
                "You were removed for dropping below the threshold. /verify again to rejoin.",
                dedup,
            )
            return
        await self._grant_invite(uid, chat_id, dedup)

    async def _grant_invite(self, uid: int, chat_id: int, dedup: str) -> None:
        group_id = self.state.group_id
        if group_id is None:
            self.dm(
                chat_id,
                "You're verified, but the holders group isn't open yet. "
                "I'll be able to mint your invite once it is — try /invite later.",
                dedup,
            )
            self.alert_operator(
                "a verified holder is waiting on an invite but no group is bound; "
                "create the group and /bind it",
                "alert:unbound-group",
            )
            return
        try:
            result = await self.telegram.call(
                "createChatInviteLink",
                {
                    "chat_id": group_id,
                    "member_limit": 1,
                    "expire_date": int(self.clock()) + self.config.invite_ttl_seconds,
                },
            )
            link = result.get("invite_link")
            if not isinstance(link, str):
                raise TelegramError("createChatInviteLink returned no link")
        except TelegramError as exc:
            log.error("invite link creation failed (%s)", type(exc).__name__)
            self.dm(
                chat_id,
                "Couldn't mint your invite link just now. Send /invite to retry.",
                dedup,
            )
            self.alert_operator(f"createChatInviteLink failed: {exc}", dedup + ":err")
            return
        self.dm(
            chat_id,
            f"Your single-use invite (expires in {self.config.invite_ttl_seconds // 60} min):\n{link}",
            dedup,
        )

    def _cmd_status(self, uid: int, chat_id: int, dedup: str) -> None:
        member = self.state.member(uid)
        challenge = self.state.get_challenge(uid, now=self.clock())
        if member is None:
            if challenge is not None:
                self.dm(
                    chat_id,
                    f"Challenge pending for {challenge.wallet} — sign it and paste the signature.",
                    dedup,
                )
            else:
                self.dm(chat_id, "Not verified. Start with /verify <wallet>.", dedup)
            return
        decimals = self.state.mint_decimals or 0
        held = (
            format_tokens(member.last_balance_raw, decimals)
            if member.last_balance_raw is not None
            else "unknown"
        )
        lines = [
            f"Wallet: {member.wallet}",
            f"Standing: {member.status}",
            f"Last checked balance: {held} $DREGG (threshold {self.config.threshold_tokens:,})",
        ]
        if member.status == "grace" and member.grace_until is not None:
            hours_left = max(0, int((member.grace_until - self.clock()) / 3600))
            lines.append(
                f"Below threshold — about {hours_left}h of grace left before removal. "
                "Top up to keep your seat."
            )
        if member.status == "ejected":
            lines.append("Removed for dropping below the threshold. /verify again to rejoin.")
        self.dm(chat_id, "\n".join(lines), dedup)

    # -- operator callbacks (approve/reject buttons) --------------------------------

    async def _callback(self, update_id: int, raw: object) -> None:
        if not isinstance(raw, dict):
            return
        callback_id = raw.get("id")
        sender = raw.get("from")
        data = raw.get("data")
        if not isinstance(callback_id, str) or not isinstance(sender, dict):
            return
        match = CALLBACK_DATA.fullmatch(data) if isinstance(data, str) else None
        if match is None:
            await self.telegram.answer_callback(callback_id, "Unknown button.")
            return
        if sender.get("id") != self.config.operator_chat_id:
            log.warning("ignored approval callback from non-operator, update %s", update_id)
            await self.telegram.answer_callback(callback_id, "Not authorized.")
            return
        decision = "approve" if match.group(1) == "a" else "reject"
        approval_id = int(match.group(2))
        decided = self.state.decide_approval(
            approval_id, decision, str(self.config.operator_chat_id), self.clock()
        )
        if not decided:
            await self.telegram.answer_callback(callback_id, "Already decided (or unknown).")
            return
        await self.telegram.answer_callback(callback_id, f"{decision}d")
        self.dm(
            self.config.operator_chat_id,
            f"Approval #{approval_id}: {decision}.",
            f"update:{update_id}",
        )

    # -- approvals presenter (called every cycle by the service) --------------------

    def present_approvals(self) -> int:
        presented = 0
        for request in self.state.unpresented_approvals():
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "✅ Approve", "callback_data": f"gate:a:{request.id}"},
                        {"text": "🚫 Reject", "callback_data": f"gate:r:{request.id}"},
                    ]
                ]
            }
            self.dm(
                self.config.operator_chat_id,
                f"Approval #{request.id} · {request.source}/{request.kind}\n\n{request.summary}",
                f"approval:{request.id}",
                keyboard,
            )
            self.state.mark_presented(request.id, self.clock())
            presented += 1
        return presented
