"""Offline tests for the dregg gate: verify flow, 1:1 binding, /bind, approvals, outbox.

No live Telegram or Helius call anywhere: transports are httpx.MockTransport,
Helius is either the real client against canned RPC JSON (balance math) or a
programmable stub (flows and failures). Signatures are real ed25519 via solders.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from solders.keypair import Keypair

from dregg_gate.approvals import enqueue_approval, read_decision
from dregg_gate.config import Config, GateConfigError, read_secret
from dregg_gate.gateway import SIGNER_URL, GateGateway, format_tokens
from dregg_gate.helius import Helius, HeliusError
from dregg_gate.state import GateState, GateStateError
from dregg_gate.telegram import Telegram

OPERATOR = 6913902526
MINT = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
NOW = 1_756_000_000  # 2025-08-24 02:26:40 UTC
THRESHOLD_RAW = 888_888 * 10**6


def make_config(tmp_path: Path, **overrides) -> Config:
    cfg = Config(
        telegram_token_file=tmp_path / "token",
        helius_key_file=tmp_path / "helius",
        db_path=tmp_path / "gate.sqlite",
        heartbeat_path=tmp_path / "heartbeat.json",
    )
    return replace(cfg, **overrides) if overrides else cfg


class Clock:
    def __init__(self, now: float = NOW):
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeHelius:
    """Programmable Helius stand-in with the same two-method surface."""

    def __init__(self, decimals: int = 6, balances: dict[str, int] | None = None):
        self.decimals = decimals
        self.balances = balances or {}
        self.fail_wallets: set[str] = set()
        self.fail_decimals = False
        self.balance_calls = 0

    async def mint_decimals(self, mint: str) -> int:
        if self.fail_decimals:
            raise HeliusError("decimals unavailable")
        return self.decimals

    async def balance_raw(self, owner: str, mint: str) -> int:
        self.balance_calls += 1
        if owner in self.fail_wallets:
            raise HeliusError("helius down")
        return self.balances[owner]


def dm_update(update_id: int, uid: int, text: str, *, date: int = NOW - 5) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "date": date,
            "text": text,
            "chat": {"id": uid, "type": "private"},
            "from": {"id": uid, "is_bot": False},
        },
    }


def group_update(update_id: int, chat_id: int, uid: int, text: str, *, date: int = NOW - 5) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "date": date,
            "text": text,
            "chat": {"id": chat_id, "type": "group"},
            "from": {"id": uid, "is_bot": False},
        },
    }


def callback_update(update_id: int, uid: int, data: str) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "from": {"id": uid, "is_bot": False},
            "data": data,
            "message": {"chat": {"id": OPERATOR, "type": "private"}},
        },
    }


def outbox_texts(state: GateState) -> list[str]:
    return [item.payload.get("text", "") for item in state.pending() if item.method == "sendMessage"]


def challenge_text_from(state: GateState) -> str:
    """The challenge rides alone in its own plain-text message (no markup), so a
    tap-and-hold copy grabs exactly it and nothing extra is ever signed."""

    texts = [t for t in outbox_texts(state) if "dregg wire wants proof" in t]
    assert texts, "no challenge DM enqueued"
    return texts[-1]


def ok_telegram_handler(invites: list[dict]):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/createChatInviteLink"):
            invites.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {"invite_link": "https://t.me/+gate"}})
        return httpx.Response(200, json={"ok": True, "result": {}})

    return handler


# -- challenge lifecycle ------------------------------------------------------------


async def test_full_verify_flow_grants_single_use_hour_invite(tmp_path: Path) -> None:
    keypair = Keypair()
    wallet = str(keypair.pubkey())
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    state.bind_group(-100_500)
    clock = Clock()
    helius = FakeHelius(balances={wallet: THRESHOLD_RAW})  # exactly N passes
    invites: list[dict] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(ok_telegram_handler(invites))) as http:
        gateway = GateGateway(cfg, state, Telegram("TESTTOKEN", http, state), helius, clock=clock)
        await gateway.process_update(dm_update(1, 777, f"/verify {wallet}"))
        challenge = challenge_text_from(state)
        assert challenge.startswith(f"dregg wire wants proof you hold {wallet}\nnonce: ")
        assert challenge.endswith("expires: 10min")
        signature = str(keypair.sign_message(challenge.encode()))
        await gateway.process_update(dm_update(2, 777, signature))

        member = state.member(777)
        assert member is not None and member.wallet == wallet and member.status == "ok"
        assert member.last_balance_raw == THRESHOLD_RAW
        assert len(invites) == 1
        assert invites[0]["member_limit"] == 1
        assert invites[0]["expire_date"] == int(NOW) + 3600
        assert any("https://t.me/+gate" in text for text in outbox_texts(state))

        # single-use: the same signature can never grant again
        await gateway.process_update(dm_update(3, 777, signature))
        assert len(invites) == 1
        assert any("No live challenge" in text for text in outbox_texts(state))
    state.close()


async def test_challenge_rides_alone_and_copy_points_at_signer(tmp_path: Path) -> None:
    """/verify sends instructions (with the signer page URL) and then the bare
    challenge as a tap-to-copy <pre> block; /help carries the URL too."""

    keypair = Keypair()
    wallet = str(keypair.pubkey())
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    clock = Clock()
    gateway = GateGateway(cfg, state, None, FakeHelius(), clock=clock)  # type: ignore[arg-type]
    await gateway.process_update(dm_update(1, 777, f"/verify {wallet}"))

    payloads = [item.payload for item in state.pending() if item.method == "sendMessage"]
    assert len(payloads) == 2, "instructions and challenge must be separate messages"
    instructions, challenge_dm = payloads

    assert SIGNER_URL in str(instructions["text"])
    assert "sends nothing" in str(instructions["text"])
    assert "parse_mode" not in instructions

    challenge = challenge_text_from(state)
    assert challenge_dm["text"] == challenge, "nothing but the challenge is in that message"
    assert "parse_mode" not in challenge_dm, "plain text, no markup to mis-render"
    assert str(keypair.sign_message(challenge.encode()))  # exact text is signable as-is

    await gateway.process_update(dm_update(2, 777, "/help"))
    assert any(SIGNER_URL in text for text in outbox_texts(state))
    state.close()


async def test_expired_challenge_is_rejected_and_a_fresh_one_is_offered(tmp_path: Path) -> None:
    keypair = Keypair()
    wallet = str(keypair.pubkey())
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    clock = Clock()
    helius = FakeHelius(balances={wallet: THRESHOLD_RAW})
    gateway = GateGateway(cfg, state, None, helius, clock=clock)  # type: ignore[arg-type]
    await gateway.process_update(dm_update(1, 777, f"/verify {wallet}"))
    stale = challenge_text_from(state)
    signature = str(keypair.sign_message(stale.encode()))
    clock.now = NOW + cfg.challenge_ttl_seconds + 1
    await gateway.process_update(dm_update(2, 777, signature, date=int(clock.now) - 5))
    # the stale signature granted nothing...
    assert state.member(777) is None
    assert any("challenge expired" in text for text in outbox_texts(state))
    # ...but a FRESH challenge for the same wallet is already waiting (new nonce,
    # so the stale signature can never verify against it)
    fresh = state.get_challenge(777, now=clock.now)
    assert fresh is not None and fresh.wallet == wallet
    assert fresh.message != stale
    # and signing the fresh one completes verification normally
    await gateway.process_update(
        dm_update(3, 777, str(keypair.sign_message(fresh.message.encode())), date=int(clock.now) - 5)
    )
    assert state.member(777) is not None
    state.close()


async def test_wrong_signer_is_rejected_and_challenge_survives(tmp_path: Path) -> None:
    holder = Keypair()
    impostor = Keypair()
    wallet = str(holder.pubkey())
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    clock = Clock()
    gateway = GateGateway(cfg, state, None, FakeHelius(balances={wallet: THRESHOLD_RAW}), clock=clock)  # type: ignore[arg-type]
    await gateway.process_update(dm_update(1, 777, f"/verify {wallet}"))
    challenge = challenge_text_from(state)
    await gateway.process_update(dm_update(2, 777, str(impostor.sign_message(challenge.encode()))))
    assert state.member(777) is None
    assert any("does not verify" in text for text in outbox_texts(state))
    assert state.get_challenge(777, now=clock.now) is not None  # honest retry still possible
    state.close()


async def test_insufficient_balance_consumes_challenge_without_membership(tmp_path: Path) -> None:
    keypair = Keypair()
    wallet = str(keypair.pubkey())
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    clock = Clock()
    gateway = GateGateway(
        cfg, state, None, FakeHelius(balances={wallet: THRESHOLD_RAW - 1}), clock=clock  # type: ignore[arg-type]
    )
    await gateway.process_update(dm_update(1, 777, f"/verify {wallet}"))
    challenge = challenge_text_from(state)
    await gateway.process_update(dm_update(2, 777, str(keypair.sign_message(challenge.encode()))))
    assert state.member(777) is None
    assert state.get_challenge(777, now=clock.now) is None
    assert any("888,887.999999" in text and "888,888" in text for text in outbox_texts(state))
    state.close()


async def test_helius_outage_during_verify_keeps_challenge_and_alerts_operator(tmp_path: Path) -> None:
    keypair = Keypair()
    wallet = str(keypair.pubkey())
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    clock = Clock()
    helius = FakeHelius(balances={wallet: THRESHOLD_RAW})
    helius.fail_wallets.add(wallet)
    gateway = GateGateway(cfg, state, None, helius, clock=clock)  # type: ignore[arg-type]
    await gateway.process_update(dm_update(1, 777, f"/verify {wallet}"))
    challenge = challenge_text_from(state)
    await gateway.process_update(dm_update(2, 777, str(keypair.sign_message(challenge.encode()))))
    assert state.member(777) is None
    assert state.get_challenge(777, now=clock.now) is not None
    operator_alerts = [
        item.payload
        for item in state.pending()
        if item.method == "sendMessage" and item.payload["chat_id"] == OPERATOR
    ]
    assert any("Helius error" in payload["text"] for payload in operator_alerts)
    state.close()


# -- 1:1 wallet <-> account -----------------------------------------------------------


async def test_wallet_can_bind_to_exactly_one_telegram_account(tmp_path: Path) -> None:
    keypair = Keypair()
    wallet = str(keypair.pubkey())
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    state.bind_group(-100_500)
    clock = Clock()
    helius = FakeHelius(balances={wallet: THRESHOLD_RAW})
    invites: list[dict] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(ok_telegram_handler(invites))) as http:
        gateway = GateGateway(cfg, state, Telegram("TESTTOKEN", http, state), helius, clock=clock)
        # user B opens a challenge on the wallet BEFORE user A completes
        await gateway.process_update(dm_update(1, 888, f"/verify {wallet}"))
        challenge_b = challenge_text_from(state)
        # user A verifies fully
        await gateway.process_update(dm_update(2, 777, f"/verify {wallet}"))
        challenge_a = challenge_text_from(state)
        await gateway.process_update(dm_update(3, 777, str(keypair.sign_message(challenge_a.encode()))))
        assert state.member(777) is not None
        # user B pasting a VALID signature is still refused: the wallet is taken
        await gateway.process_update(dm_update(4, 888, str(keypair.sign_message(challenge_b.encode()))))
        assert state.member(888) is None
        assert state.member_by_wallet(wallet).tg_user_id == 777
        # and a fresh /verify for the taken wallet is refused up front
        await gateway.process_update(dm_update(5, 888, f"/verify {wallet}"))
        assert state.get_challenge(888, now=clock.now) is None
        assert any("already linked" in text for text in outbox_texts(state))
    state.close()


async def test_same_user_may_rebind_to_a_new_wallet(tmp_path: Path) -> None:
    first, second = Keypair(), Keypair()
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    state.bind_group(-100_500)
    clock = Clock()
    helius = FakeHelius(
        balances={str(first.pubkey()): THRESHOLD_RAW, str(second.pubkey()): THRESHOLD_RAW * 2}
    )
    invites: list[dict] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(ok_telegram_handler(invites))) as http:
        gateway = GateGateway(cfg, state, Telegram("TESTTOKEN", http, state), helius, clock=clock)
        for offset, keypair in ((0, first), (10, second)):
            await gateway.process_update(dm_update(offset + 1, 777, f"/verify {keypair.pubkey()}"))
            challenge = challenge_text_from(state)
            signature = str(keypair.sign_message(challenge.encode()))
            await gateway.process_update(dm_update(offset + 2, 777, signature))
        member = state.member(777)
        assert member is not None and member.wallet == str(second.pubkey())
        assert state.member_by_wallet(str(first.pubkey())) is None
    state.close()


# -- balance math against the REAL Helius client --------------------------------------


async def test_helius_sums_all_token_accounts_and_reads_decimals_on_chain() -> None:
    def account(amount: str) -> dict:
        return {"account": {"data": {"parsed": {"info": {"tokenAmount": {"amount": amount}}}}}}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "getTokenSupply":
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": {"decimals": 6}}}
            )
        assert body["method"] == "getTokenAccountsByOwner"
        assert body["params"][1] == {"mint": MINT}
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"value": [account("400000000000"), account("488888000000")]},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        helius = Helius("KEY", http)
        assert await helius.mint_decimals(MINT) == 6
        assert await helius.balance_raw("ownerwallet", MINT) == 888_888_000_000


@pytest.mark.parametrize(
    "body",
    [
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "nope"}},
        {"jsonrpc": "2.0", "id": 1, "result": {"value": "not-a-list"}},
        {"jsonrpc": "2.0", "id": 1, "result": {"value": [{"account": {}}]}},
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "value": [
                    {"account": {"data": {"parsed": {"info": {"tokenAmount": {"amount": 12}}}}}}
                ]
            },
        },
    ],
)
async def test_helius_malformed_bodies_raise_instead_of_reading_zero(body: dict) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(HeliusError):
            await Helius("KEY", http).balance_raw("owner", MINT)


async def test_helius_empty_account_list_is_an_honest_zero() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        assert await Helius("KEY", http).balance_raw("owner", MINT) == 0


def test_format_tokens() -> None:
    assert format_tokens(888_888_000_000, 6) == "888,888"
    assert format_tokens(888_887_999_999, 6) == "888,887.999999"
    assert format_tokens(0, 6) == "0"


# -- /bind is operator-only -----------------------------------------------------------


async def test_bind_records_group_only_for_operator(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    clock = Clock()
    gateway = GateGateway(cfg, state, None, FakeHelius(), clock=clock)  # type: ignore[arg-type]
    await gateway.process_update(group_update(1, -100_500, 999, "/bind"))
    assert state.group_id is None
    await gateway.process_update(group_update(2, -100_500, OPERATOR, "/bind"))
    assert state.group_id == -100_500
    assert any("Bound the gated group" in text for text in outbox_texts(state))
    # supergroup migration follows automatically
    migration = {
        "update_id": 3,
        "message": {
            "date": NOW - 5,
            "chat": {"id": -100_500, "type": "group"},
            "from": {"id": 42, "is_bot": False},
            "migrate_to_chat_id": -1_000_100_500,
        },
    }
    await gateway.process_update(migration)
    assert state.group_id == -1_000_100_500
    state.close()


# -- approvals round-trip -------------------------------------------------------------


async def test_approvals_round_trip_from_enqueue_to_decision(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    clock = Clock()
    # a foreign service inserts while the gate holds the db open (WAL, second connection)
    approval_id = enqueue_approval(
        cfg.db_path, "wire", "draft", "Post draft #7 to the channel?", {"draft_id": 7}, now=NOW
    )
    assert read_decision(cfg.db_path, approval_id) is None

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        gateway = GateGateway(cfg, state, Telegram("TESTTOKEN", http, state), FakeHelius(), clock=clock)
        assert gateway.present_approvals() == 1
        assert gateway.present_approvals() == 0  # presented exactly once
        button_payloads = [
            item.payload for item in state.pending() if "reply_markup" in item.payload
        ]
        assert button_payloads[0]["chat_id"] == OPERATOR
        buttons = button_payloads[0]["reply_markup"]["inline_keyboard"][0]
        assert [b["callback_data"] for b in buttons] == [
            f"gate:a:{approval_id}",
            f"gate:r:{approval_id}",
        ]
        # a stranger pressing the button decides nothing
        await gateway.process_update(callback_update(10, 999, f"gate:a:{approval_id}"))
        assert read_decision(cfg.db_path, approval_id) is None
        # the operator approves; the decision is durable and the payload comes back unchanged
        await gateway.process_update(callback_update(11, OPERATOR, f"gate:a:{approval_id}"))
        decision = read_decision(cfg.db_path, approval_id)
        assert decision is not None
        assert decision.decision == "approve"
        assert decision.payload == {"draft_id": 7}
        assert decision.source == "wire" and decision.kind == "draft"
        # a second press cannot flip it
        await gateway.process_update(callback_update(12, OPERATOR, f"gate:r:{approval_id}"))
        assert read_decision(cfg.db_path, approval_id).decision == "approve"
    state.close()


# -- transport: exclusive poller lock, ordered outbox, drop-vs-retry ------------------


def test_second_gate_state_refuses_to_start(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    with pytest.raises(GateStateError, match="refusing to start"):
        GateState(cfg.db_path)
    state.close()


async def test_outbox_retries_transport_failures_and_drops_definitive_rejections(
    tmp_path: Path,
) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    state.enqueue("a", "sendMessage", {"chat_id": 1, "text": "first"})
    state.enqueue("b", "sendMessage", {"chat_id": 2, "text": "second"})
    responses = [httpx.Response(500, json={"ok": False})]

    async def handler(_request: httpx.Request) -> httpx.Response:
        if responses:
            return responses.pop(0)
        return httpx.Response(403, json={"ok": False, "description": "bot was blocked by the user"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        telegram = Telegram("TESTTOKEN", http, state)
        await telegram.flush_outbox()
        # 500 defers the head and preserves order: nothing later was attempted
        deferred = state.pending(now=9e12)
        assert [item.payload["text"] for item in deferred] == ["first", "second"]
        assert deferred[0].attempts == 1
        state.connection.execute("UPDATE outbox SET next_attempt_at = 0")
        await telegram.flush_outbox()
        # 403 is definitive: both dropped rather than damming the queue forever
        assert state.pending(now=9e12) == []
        assert [method for method, _ in telegram.drain_dropped()] == ["sendMessage", "sendMessage"]
        assert telegram.drain_dropped() == []
    state.close()


async def test_eject_ban_lands_before_unban(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    state.enqueue("e:ban", "banChatMember", {"chat_id": -1, "user_id": 7})
    state.enqueue("e:unban", "unbanChatMember", {"chat_id": -1, "user_id": 7, "only_if_banned": True})
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, json={"ok": True, "result": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await Telegram("TESTTOKEN", http, state).flush_outbox()
    assert seen == ["banChatMember", "unbanChatMember"]
    state.close()


# -- config ---------------------------------------------------------------------------


def test_example_config_carries_the_locked_decisions(tmp_path: Path) -> None:
    example = Path(__file__).resolve().parent.parent / "dregg_gate" / "config.example.toml"
    cfg = Config.load(example)
    assert cfg.mint == MINT
    assert cfg.threshold_tokens == 888_888
    assert cfg.operator_chat_id == OPERATOR
    assert cfg.grace_hours == 48
    assert cfg.challenge_ttl_seconds == 600
    assert cfg.invite_ttl_seconds == 3600


def test_unknown_config_key_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "gate.toml"
    path.write_text("[gate]\nthreshhold = 5\n")
    with pytest.raises(GateConfigError, match="unknown gate config key"):
        Config.load(path)


def test_read_secret_rejects_group_readable_files(tmp_path: Path) -> None:
    secret = tmp_path / "token"
    secret.write_text("abc123\n")
    secret.chmod(0o644)
    with pytest.raises(GateConfigError, match="0600"):
        read_secret(secret, "Telegram bot token")
    secret.chmod(0o600)
    assert read_secret(secret, "Telegram bot token") == "abc123"


def test_threshold_override_honored_at_verify_and_status(tmp_path):
    """A per-user override admits at its own line; validation refuses garbage."""
    from dataclasses import replace

    import pytest

    from dregg_gate.config import GateConfigError, _validate
    from dregg_gate.gateway import GateGateway
    from dregg_gate.state import GateState

    cfg = replace(make_config(tmp_path), threshold_overrides={"6913902526": 88_888})
    state = GateState(cfg.db_path)
    gateway = GateGateway(cfg, state, None, FakeHelius(), clock=lambda: 0.0)  # type: ignore[arg-type]
    assert gateway.effective_tokens(6913902526) == 88_888
    assert gateway.effective_tokens(12345) == cfg.threshold_tokens
    with pytest.raises(GateConfigError):
        _validate(replace(cfg, threshold_overrides={"notanid": 1}))
    with pytest.raises(GateConfigError):
        _validate(replace(cfg, threshold_overrides={"99": 0}))
    state.close()
