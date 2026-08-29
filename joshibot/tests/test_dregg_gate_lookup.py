"""Offline tests for the bot-UX lane: /start onboarding, /screen lookups, verify-flow errors.

Same discipline as test_dregg_gate: no live Telegram or Helius anywhere. The screen's
score files are written by the tests themselves in the live service's exact JSONL shape.
"""

from __future__ import annotations

import html
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from solders.keypair import Keypair

from dregg_gate.config import Config
from dregg_gate.gateway import GateGateway
from dregg_gate.helius import HeliusError
from dregg_gate.state import GateState

OPERATOR = 6913902526
NOW = 1_756_000_000  # 2025-08-24 02:26:40 UTC
THRESHOLD_RAW = 888_888 * 10**6

TODAY = datetime.fromtimestamp(NOW, tz=UTC).date()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()


def make_config(tmp_path: Path, **overrides) -> Config:
    cfg = Config(
        telegram_token_file=tmp_path / "token",
        helius_key_file=tmp_path / "helius",
        db_path=tmp_path / "gate.sqlite",
        heartbeat_path=tmp_path / "heartbeat.json",
        screen_scores_dir=tmp_path / "scores",
    )
    return replace(cfg, **overrides) if overrides else cfg


class Clock:
    def __init__(self, now: float = NOW):
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeHelius:
    def __init__(self, decimals: int = 6, balances: dict[str, int] | None = None):
        self.decimals = decimals
        self.balances = balances or {}

    async def mint_decimals(self, mint: str) -> int:
        return self.decimals

    async def balance_raw(self, owner: str, mint: str) -> int:
        if owner not in self.balances:
            raise HeliusError("unknown wallet")
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


def dm_payloads(state: GateState) -> list[dict]:
    return [item.payload for item in state.pending() if item.method == "sendMessage"]


def outbox_texts(state: GateState) -> list[str]:
    return [payload.get("text", "") for payload in dm_payloads(state)]


def challenge_text_from(state: GateState) -> str:
    texts = [t for t in outbox_texts(state) if "dregg wire wants proof" in t]
    assert texts, "no challenge DM enqueued"
    text = texts[-1]
    if text.startswith("<pre>") and text.endswith("</pre>"):
        return html.unescape(text[len("<pre>") : -len("</pre>")])
    return text.split("\n\n", 1)[1]


def score_row(mint: str, **overrides) -> dict:
    """One score row in the live service's JSONL shape (dregg_screen.live _emit)."""

    row = {
        "mint": mint,
        "verdict": "CLEAN",
        "reasons": ["all_gates_passed"],
        "name": "test coin",
        "symbol": "TEST",
        "creator": "creatorwallet",
        "deployer": "deployerwallet",
        "hydrated": True,
        "in_validated_population": True,
        "population_notes": [],
        "features": {
            "dev_buy_share": 0.009,
            "dev_buy_source": "chain_exact",
            "n_snipers": 1,
            "prior_launches": 2,
        },
        "crew_match": None,
        "deployer_history": {"launches": 2, "rips": 0, "dumps": 0, "grads": 1},
        "base_rates": {},
        "tg_line": "unused by the card",
        "t_scored": "2025-08-24T02:20:00.000000+00:00",
    }
    row.update(overrides)
    return row


def write_scores(cfg: Config, day: str, rows: list[dict]) -> None:
    cfg.screen_scores_dir.mkdir(parents=True, exist_ok=True)
    with (cfg.screen_scores_dir / f"{day}.jsonl").open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def gate(cfg: Config, state: GateState, clock: Clock, helius: FakeHelius | None = None) -> GateGateway:
    return GateGateway(cfg, state, None, helius or FakeHelius(), clock=clock)  # type: ignore[arg-type]


def verified_member(state: GateState, uid: int = 777) -> str:
    wallet = str(Keypair().pubkey())
    state.record_verification(uid, wallet, THRESHOLD_RAW, NOW)
    return wallet


# -- /start front door ----------------------------------------------------------------


async def test_start_onboards_cold_users_and_disarms_phishing(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    gateway = gate(cfg, state, Clock())
    await gateway.process_update(dm_update(1, 555, "/start"))
    texts = outbox_texts(state)
    assert len(texts) == 1
    start = texts[0]
    # what this is, what you get
    assert "pump.fun intelligence" in start
    assert "hourly launch-screen digests" in start
    assert "daily wire" in start
    assert "caller records" in start
    assert "/screen <mint>" in start
    # how to join
    assert "888,888 $DREGG" in start
    assert "/verify <your wallet address>" in start
    # the anti-phishing rule, stated as a rule
    assert "NEVER ask you to sign a transaction" in start
    assert "plain text message" in start
    # tight: a front door, not a wall
    assert len(start) < 1500
    # /help is its own reply and covers /screen
    await gateway.process_update(dm_update(2, 555, "/help"))
    assert any("/screen <mint>" in t and "/verify <wallet>" in t for t in outbox_texts(state)[1:])
    state.close()


# -- /screen: the verdict card --------------------------------------------------------


async def test_screen_renders_the_verdict_card_with_pump_fun_link(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    verified_member(state)
    mint = str(Keypair().pubkey())
    write_scores(cfg, TODAY.isoformat(), [
        score_row(str(Keypair().pubkey())),  # a different launch: must not match
        score_row(
            mint,
            verdict="KNOWN_CREW",
            symbol="RUN",
            name="lil bull run",
            hydrated=True,
            in_validated_population=False,
            population_notes=["vendor_flag:is_mayhem_mode"],
            reasons=["crew_fingerprint:#81422:jaccard=0.31:overlap=4"],
            features={"dev_buy_share": 0.0021, "dev_buy_source": "ws_vendor_float", "n_snipers": 4},
            crew_match={
                "crew_id": 81422, "deployer": "d", "matched_mint": "m", "jaccard": 0.31,
                "overlap": 4, "launch_set_size": 5, "matched_set_size": 6,
                "crew_coins": 9, "crew_rips": 3, "crew_dumps": 2, "dirty": True,
            },
            deployer_history={"launches": 6, "rips": 0, "dumps": 6, "grads": 0},
        ),
    ])
    gateway = gate(cfg, state, Clock())
    await gateway.process_update(dm_update(1, 777, f"/screen {mint}"))
    payloads = dm_payloads(state)
    assert len(payloads) == 1
    card = payloads[0]["text"]
    assert payloads[0].get("parse_mode") == "HTML"
    assert f'<a href="https://pump.fun/coin/{mint}">$RUN — lil bull run</a>' in card
    assert f"<code>{mint}</code>" in card
    assert "KNOWN-CREW" in card
    assert "Dev buy: 0.21% of supply (vendor estimate; gate is &lt;2%)" in card
    assert "Bundle: YES — 4 buyers in the birth slot" in card
    assert "Deployer record: 6 launches / 0 rips / 6 dumps" in card
    assert "fingerprint #81422 — Jaccard 0.31, 4 shared birth-slot wallets" in card
    assert "3 rips / 2 insider dumps" in card
    # the population caveat and the intent line are non-negotiable
    assert "Outside the validated population (vendor_flag:is_mayhem_mode)" in card
    assert "Scores rank risk; they do not establish intent." in card
    state.close()


async def test_screen_clean_card_and_yesterday_file(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    verified_member(state)
    mint = str(Keypair().pubkey())
    write_scores(cfg, YESTERDAY, [score_row(mint, symbol="OK", name="okay coin")])
    gateway = gate(cfg, state, Clock())
    await gateway.process_update(dm_update(1, 777, f"/screen {mint}"))
    card = outbox_texts(state)[0]
    assert "🟢 CLEAN" in card
    assert "Dev buy: 0.90% of supply (chain-exact; gate is &lt;2%)" in card
    assert "Bundle: none seen (1 birth-slot buyer)" in card
    assert "Crew: no fingerprint match" in card
    assert "Deployer record: 2 launches / 0 rips / 0 dumps / 1 graduations" in card
    assert "Outside the validated population" not in card
    assert "Scores rank risk; they do not establish intent." in card
    state.close()


async def test_screen_unhydrated_row_says_birth_slot_unread(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    verified_member(state)
    mint = str(Keypair().pubkey())
    row = score_row(
        mint,
        verdict="NOT_CLEAN",
        hydrated=False,
        reasons=["dev_buy_share=0.1249>= 0.02"],
        features={"dev_buy_share": 0.1249, "dev_buy_source": "ws_vendor_float"},
    )
    write_scores(cfg, TODAY.isoformat(), [row])
    gateway = gate(cfg, state, Clock())
    await gateway.process_update(dm_update(1, 777, f"/screen {mint}"))
    card = outbox_texts(state)[0]
    assert "NOT-CLEAN" in card
    assert "Bundle: unknown — birth slot not read" in card
    assert "Why: dev_buy_share=0.1249&gt;= 0.02" in card  # escaped, verbatim mechanism
    state.close()


async def test_screen_escapes_hostile_provider_strings(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    verified_member(state)
    mint = str(Keypair().pubkey())
    write_scores(cfg, TODAY.isoformat(), [
        score_row(mint, symbol='<b>EVIL', name='a & "b" <script>')
    ])
    gateway = gate(cfg, state, Clock())
    await gateway.process_update(dm_update(1, 777, f"/screen {mint}"))
    card = outbox_texts(state)[0]
    assert "&lt;b&gt;EVIL" in card and "&lt;script&gt;" in card and "&amp;" in card
    assert "<b>" not in card and "<script>" not in card
    # the only tags in the card are the ones we wrote
    for tag in ("<a ", "</a>", "<code>", "</code>"):
        assert card.count(tag) == 1
    state.close()


async def test_screen_not_found_is_honest_about_window_and_go_live(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    verified_member(state)
    mint = str(Keypair().pubkey())
    write_scores(cfg, TODAY.isoformat(), [score_row(str(Keypair().pubkey()))])
    gateway = gate(cfg, state, Clock())
    await gateway.process_update(dm_update(1, 777, f"/screen {mint}"))
    payloads = dm_payloads(state)
    text = payloads[0]["text"]
    assert "No screen record" in text
    assert "last two days" in text
    assert "2026-08-29" in text  # the screen's go-live date, named
    assert f'href="https://pump.fun/coin/{mint}"' in text  # still hand them the coin page
    assert payloads[0].get("parse_mode") == "HTML"
    state.close()


async def test_screen_missing_score_files_read_as_not_found(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)  # scores dir never created
    state = GateState(cfg.db_path)
    verified_member(state)
    gateway = gate(cfg, state, Clock())
    await gateway.process_update(dm_update(1, 777, f"/screen {Keypair().pubkey()}"))
    assert any("No screen record" in t for t in outbox_texts(state))
    state.close()


# -- /screen: gating and rate limiting ------------------------------------------------


async def test_screen_is_gated_teaser_for_unverified_users(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    mint = str(Keypair().pubkey())
    write_scores(cfg, TODAY.isoformat(), [score_row(mint, symbol="SECRET")])
    gateway = gate(cfg, state, Clock())
    await gateway.process_update(dm_update(1, 999, f"/screen {mint}"))
    payloads = dm_payloads(state)
    teaser = payloads[0]["text"]
    assert "verify to unlock" in teaser
    assert "░" in teaser  # the blurred sample line
    assert "888,888 $DREGG" in teaser and "/verify <wallet>" in teaser
    assert "SECRET" not in teaser  # no data leaks through the teaser
    assert payloads[0].get("parse_mode") is None  # plain copy, no HTML risk
    state.close()


async def test_screen_ejected_member_is_pointed_back_at_verify(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    verified_member(state)
    state.set_member_status(777, "ejected", None)
    gateway = gate(cfg, state, Clock())
    await gateway.process_update(dm_update(1, 777, f"/screen {Keypair().pubkey()}"))
    assert any("/verify" in t and "locked" in t for t in outbox_texts(state))
    state.close()


async def test_screen_rate_limit_admits_then_refuses_then_recovers(tmp_path: Path) -> None:
    cfg = make_config(tmp_path, screen_rate_per_minute=3)
    state = GateState(cfg.db_path)
    verified_member(state)
    clock = Clock()
    gateway = gate(cfg, state, clock)
    mint = str(Keypair().pubkey())
    for n in range(3):
        await gateway.process_update(dm_update(n + 1, 777, f"/screen {mint}"))
    assert sum("No screen record" in t for t in outbox_texts(state)) == 3
    await gateway.process_update(dm_update(4, 777, f"/screen {mint}"))
    assert any("capped at 3 lookups a minute" in t for t in outbox_texts(state))
    # another member has their own window
    verified_member(state, uid=778)
    await gateway.process_update(dm_update(5, 778, f"/screen {mint}"))
    assert sum("No screen record" in t for t in outbox_texts(state)) == 4
    # and the window slides open again
    clock.now = NOW + 61
    await gateway.process_update(dm_update(6, 777, f"/screen {mint}", date=int(clock.now) - 5))
    assert sum("No screen record" in t for t in outbox_texts(state)) == 5
    state.close()


async def test_screen_usage_copy_for_missing_or_malformed_mint(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    verified_member(state)
    gateway = gate(cfg, state, Clock())
    await gateway.process_update(dm_update(1, 777, "/screen"))
    await gateway.process_update(dm_update(2, 777, "/screen not-a-mint"))
    usage = [t for t in outbox_texts(state) if "Usage: /screen <mint>" in t]
    assert len(usage) == 2
    assert "base58" in usage[0]
    state.close()


# -- verify-flow error copy -----------------------------------------------------------


async def test_balance_short_copy_shows_held_needed_and_gap(tmp_path: Path) -> None:
    keypair = Keypair()
    wallet = str(keypair.pubkey())
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    clock = Clock()
    helius = FakeHelius(balances={wallet: 100_000 * 10**6})
    gateway = gate(cfg, state, clock, helius)
    await gateway.process_update(dm_update(1, 777, f"/verify {wallet}"))
    challenge = challenge_text_from(state)
    await gateway.process_update(dm_update(2, 777, str(keypair.sign_message(challenge.encode()))))
    assert state.member(777) is None
    short = [t for t in outbox_texts(state) if "balance is short" in t]
    assert len(short) == 1
    assert "100,000" in short[0]  # held, human units
    assert "888,888" in short[0]  # required, human units
    assert "788,888" in short[0]  # the gap, so nobody does the subtraction on a phone
    assert "/verify" in short[0]
    state.close()


async def test_invalid_wallet_copy_says_what_to_fix(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    gateway = gate(cfg, state, Clock())
    await gateway.process_update(dm_update(1, 777, "/verify"))
    await gateway.process_update(dm_update(2, 777, "/verify zzzz-not-base58"))
    texts = outbox_texts(state)
    assert any("Usage: /verify <wallet>" in t for t in texts)
    assert any("doesn't parse as a Solana address" in t and "base58" in t for t in texts)
    state.close()


async def test_invalid_signature_copy_says_what_to_fix(tmp_path: Path) -> None:
    keypair = Keypair()
    wallet = str(keypair.pubkey())
    cfg = make_config(tmp_path)
    state = GateState(cfg.db_path)
    gateway = gate(cfg, state, Clock(), FakeHelius(balances={wallet: THRESHOLD_RAW}))
    await gateway.process_update(dm_update(1, 777, f"/verify {wallet}"))
    await gateway.process_update(dm_update(2, 777, '{"signature": "abc"}'))
    assert any(
        "doesn't parse as a base58 signature" in t and "ONLY the signature" in t
        for t in outbox_texts(state)
    )
    # the challenge survives the fumble: pasting correctly afterwards still works
    assert state.get_challenge(777, now=NOW) is not None
    state.close()
