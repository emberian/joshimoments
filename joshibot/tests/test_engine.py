"""Engine tests: observed cost basis, and startup reconciliation of pending exits.

The cost-basis tests exist because of 2026-08-12: the sentinel stamped cost basis
from the *current* Jupiter exit quote, so PnL started at 0% by construction and a
"-10% stop" fired ten percent below wherever the coin had already fallen. Every
test here that names a number is chosen so the old behaviour would produce a
different, wrong answer.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from solders.keypair import Keypair

from shitcoims_sentinel import engine as engine_module
from shitcoims_sentinel.clients import ExternalServiceError
from shitcoims_sentinel.config import load_config
from shitcoims_sentinel.domain import (
    TOKEN_PROGRAM,
    ExitQuote,
    MintSafety,
    PositionState,
    TokenHolding,
    utc_now,
)
from shitcoims_sentinel.engine import SentinelEngine, reconstruct_observed_basis
from shitcoims_sentinel.executor import ExecutionResult
from shitcoims_sentinel.lots import ORIGIN_DEFAULT, ORIGIN_OPERATOR, LotRecord, to_mapping
from shitcoims_sentinel.policies import policy_from_payload

DECIMALS = 6
UNIT = 10**DECIMALS
WALLET_SOL = 5_000_000_000
FEE = 5_000


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #


def token_balance(index: int, mint: str, owner: str, amount: int) -> dict[str, Any]:
    return {
        "accountIndex": index,
        "mint": mint,
        "owner": owner,
        "uiTokenAmount": {"amount": str(amount), "decimals": DECIMALS},
    }


def swap_transaction(
    *,
    wallet: str,
    token_account: str,
    mint: str,
    token_delta: int,
    lamport_delta: int,
    pre_tokens: int,
    fee: int = FEE,
    wallet_is_payer: bool = True,
) -> dict[str, Any]:
    """One confirmed swap. `lamport_delta` is the trade leg, fee applied on top."""

    keys = (
        [{"pubkey": wallet}, {"pubkey": token_account}]
        if wallet_is_payer
        else [{"pubkey": token_account}, {"pubkey": wallet}]
    )
    wallet_index = 0 if wallet_is_payer else 1
    pre = [0, 0]
    post = [0, 0]
    pre[wallet_index] = WALLET_SOL
    post[wallet_index] = WALLET_SOL + lamport_delta - (fee if wallet_is_payer else 0)
    return {
        "meta": {
            "fee": fee,
            "preBalances": pre,
            "postBalances": post,
            "preTokenBalances": (
                [] if pre_tokens == 0 else [token_balance(1, mint, wallet, pre_tokens)]
            ),
            "postTokenBalances": (
                []
                if pre_tokens + token_delta == 0
                else [token_balance(1, mint, wallet, pre_tokens + token_delta)]
            ),
        },
        "transaction": {"message": {"accountKeys": keys}},
    }


class FakeRpc:
    """Only the surface `SolanaRpc` already exposes: `call` plus typed helpers."""

    def __init__(
        self,
        *,
        holdings: list[TokenHolding] | None = None,
        signatures: dict[str, list[dict[str, Any]]] | None = None,
        transactions: dict[str, dict[str, Any]] | None = None,
        error: Exception | None = None,
    ):
        self.holdings = list(holdings or [])
        self.signatures = dict(signatures or {})
        self.transactions = dict(transactions or {})
        self.error = error
        self.fetched: list[str] = []

    async def call(self, method: str, params: list[Any] | None = None) -> Any:
        if self.error is not None:
            raise self.error
        params = params or []
        if method == "getSignaturesForAddress":
            limit = int((params[1] or {}).get("limit", 1000))
            return self.signatures.get(str(params[0]), [])[:limit]
        if method == "getTransaction":
            signature = str(params[0])
            self.fetched.append(signature)
            return self.transactions.get(signature)
        raise AssertionError(f"unexpected RPC method {method}")

    async def token_holdings(self, _owner: str) -> list[TokenHolding]:
        return list(self.holdings)

    async def mint_safety(self, _mint: str) -> MintSafety:
        return MintSafety(
            mint_authority=None,
            freeze_authority=None,
            supply=1_000_000 * UNIT,
            decimals=DECIMALS,
            token_program=TOKEN_PROGRAM,
        )

    async def confirmed_slot(self) -> int:
        return 5_000


class FakeDex:
    async def discover_primary_pool(self, _mint: str) -> None:
        return None

    async def pool(self, _mint: str, _pair: str) -> None:
        return None


class FakeJupiter:
    def __init__(self, out_lamports: int | None):
        self.out_lamports = out_lamports
        self.ready = out_lamports is not None

    async def quote_exit(self, mint: str, amount: int) -> ExitQuote:
        assert self.out_lamports is not None
        return ExitQuote(
            input_mint=mint,
            input_amount=amount,
            out_lamports=self.out_lamports,
            minimum_out_lamports=self.out_lamports - 1,
            price_impact_pct=None,
            router="metis",
            received_at=utc_now(),
        )


class RecordingExecutor:
    def __init__(self, result: ExecutionResult | None = None):
        self.calls: list[dict[str, Any]] = []
        self.result = result or ExecutionResult("dry_run", None, 0, "dry run", 0)

    async def sell(
        self,
        *,
        mint: str,
        name: str,
        reason: Any,
        observed_holding: TokenHolding,
        amount: int | None = None,
    ) -> ExecutionResult:
        self.calls.append(
            {
                "mint": mint,
                "name": name,
                "reason": str(reason),
                "observed": observed_holding.amount,
                "amount": amount,
            }
        )
        return self.result


# --------------------------------------------------------------------------- #
# harness
# --------------------------------------------------------------------------- #


def holding_of(mint: str, amount: int, account: str) -> TokenHolding:
    return TokenHolding(
        mint=mint,
        amount=amount,
        decimals=DECIMALS,
        token_accounts=(account,),
        program_ids=(TOKEN_PROGRAM,),
    )


def build_engine(tmp_path: Path, positions: list[dict[str, Any]]) -> SentinelEngine:
    wallet = tmp_path / "wallet"
    wallet.write_text(str(Keypair()), encoding="utf-8")
    wallet.chmod(0o600)
    helius = tmp_path / "helius"
    helius.write_text("helius-key", encoding="utf-8")
    helius.chmod(0o600)
    document = {
        "rpc": {"helius_api_key_file": str(helius)},
        "wallet": {"name": "shitcoims", "secret_key_file": str(wallet)},
        # Absent files: no Jupiter key, no Telegram token, never armed.
        "jupiter": {"api_key_file": str(tmp_path / "no-jupiter-key")},
        "execution": {"enabled": False, "arm_file": str(tmp_path / "never-armed")},
        "notifications": {"telegram_bot_token_file": str(tmp_path / "no-telegram")},
        "experiments": {"pump_metadata": False, "wallet_activity_stream": False},
        "state_dir": str(tmp_path / "state"),
        "auto_discover": True,
        "positions": positions,
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    engine = SentinelEngine(load_config(config_path), cli_live=False)
    engine.dex = FakeDex()
    engine.jupiter = FakeJupiter(None)
    engine.executor = RecordingExecutor()
    return engine


def default_policy(mint: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mint": mint,
        "name": "SULLY",
        "stop_loss_pct": -35,
        "take_profit_pct": 80,
        "trailing_stop_pct": 20,
        "exit_style": "fixed_trail",
        "floor_confirm_quotes": 1,
    }
    payload.update(overrides)
    return payload


def write_lot(engine: SentinelEngine, mint: str, **fields: Any) -> None:
    record = LotRecord(
        mint=mint,
        generation=fields.get("generation", 1),
        opened_at=fields.get("opened_at", utc_now().isoformat()),
        flat_since=fields.get("flat_since"),
        auto_protect_after=fields.get("auto_protect_after"),
        auto_protect_skipped=fields.get("auto_protect_skipped", True),
        origin=fields.get("origin", ORIGIN_DEFAULT),
        needs_basis=fields.get("needs_basis", False),
        sl_live_after=fields.get("sl_live_after"),
    )
    engine.state.set("lots", mint, value=to_mapping(record))


def messages(engine: SentinelEngine) -> list[str]:
    return [event["message"] for event in engine.journal.recent()]


# --------------------------------------------------------------------------- #
# reconstruction unit tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_basis_is_the_net_sol_paid_across_every_buy_in_the_lot() -> None:
    wallet, account, mint = "wallet", "account", "mint"
    rpc = FakeRpc(
        signatures={
            account: [
                {"signature": "buy-2", "slot": 20, "err": None},
                {"signature": "buy-1", "slot": 10, "err": None},
            ]
        },
        transactions={
            "buy-2": swap_transaction(
                wallet=wallet,
                token_account=account,
                mint=mint,
                token_delta=400 * UNIT,
                lamport_delta=-60_000_000,
                pre_tokens=600 * UNIT,
            ),
            "buy-1": swap_transaction(
                wallet=wallet,
                token_account=account,
                mint=mint,
                token_delta=600 * UNIT,
                lamport_delta=-90_000_000,
                pre_tokens=0,
            ),
        },
    )

    basis, reason = await reconstruct_observed_basis(
        rpc=rpc, owner=wallet, holding=holding_of(mint, 1_000 * UNIT, account)
    )

    assert basis is not None, reason
    # 0.06 + 0.09 SOL of trade legs. The two 5000-lamport fees are not what the
    # tokens cost, so 150_010_000 would be wrong.
    assert basis.lamports_spent == 150_000_000
    assert basis.base_units_acquired == 1_000 * UNIT
    assert basis.total_sol == Decimal("0.15")
    assert basis.unit_price_sol == Decimal("0.00015")
    assert basis.signatures == ("buy-2", "buy-1")


@pytest.mark.asyncio
async def test_basis_stops_at_the_lot_boundary_and_ignores_the_previous_generation() -> None:
    wallet, account, mint = "wallet", "account", "mint"
    rpc = FakeRpc(
        signatures={
            account: [
                {"signature": "rebuy", "slot": 30, "err": None},
                {"signature": "old-sell", "slot": 6, "err": None},
                {"signature": "old-buy", "slot": 5, "err": None},
            ]
        },
        transactions={
            "rebuy": swap_transaction(
                wallet=wallet,
                token_account=account,
                mint=mint,
                token_delta=500 * UNIT,
                lamport_delta=-50_000_000,
                pre_tokens=0,
            ),
            "old-sell": swap_transaction(
                wallet=wallet,
                token_account=account,
                mint=mint,
                token_delta=-1_000 * UNIT,
                lamport_delta=900_000_000,
                pre_tokens=1_000 * UNIT,
            ),
            "old-buy": swap_transaction(
                wallet=wallet,
                token_account=account,
                mint=mint,
                token_delta=1_000 * UNIT,
                lamport_delta=-1_000_000_000,
                pre_tokens=0,
            ),
        },
    )

    basis, reason = await reconstruct_observed_basis(
        rpc=rpc, owner=wallet, holding=holding_of(mint, 500 * UNIT, account)
    )

    assert basis is not None, reason
    # The dead lot paid 1 SOL/1000 tokens. This one paid 0.05 SOL/500 tokens.
    assert basis.unit_price_sol == Decimal("0.0001")
    assert basis.signatures == ("rebuy",)
    assert rpc.fetched == ["rebuy"], "the walk must stop the moment the lot opens"


@pytest.mark.asyncio
async def test_basis_is_unavailable_when_history_never_reaches_the_lot_open() -> None:
    wallet, account, mint = "wallet", "account", "mint"
    rpc = FakeRpc(
        signatures={account: [{"signature": "partial", "slot": 40, "err": None}]},
        transactions={
            "partial": swap_transaction(
                wallet=wallet,
                token_account=account,
                mint=mint,
                token_delta=400 * UNIT,
                lamport_delta=-40_000_000,
                pre_tokens=600 * UNIT,
            )
        },
    )

    basis, reason = await reconstruct_observed_basis(
        rpc=rpc, owner=wallet, holding=holding_of(mint, 1_000 * UNIT, account)
    )

    assert basis is None
    assert "lot start not reached" in reason


@pytest.mark.asyncio
async def test_basis_refuses_tokens_that_arrived_without_a_sol_payment() -> None:
    wallet, account, mint = "wallet", "account", "mint"
    rpc = FakeRpc(
        signatures={account: [{"signature": "airdrop", "slot": 12, "err": None}]},
        transactions={
            "airdrop": swap_transaction(
                wallet=wallet,
                token_account=account,
                mint=mint,
                token_delta=1_000 * UNIT,
                lamport_delta=0,
                pre_tokens=0,
            )
        },
    )

    basis, reason = await reconstruct_observed_basis(
        rpc=rpc, owner=wallet, holding=holding_of(mint, 1_000 * UNIT, account)
    )

    assert basis is None
    assert "without a SOL payment" in reason


@pytest.mark.asyncio
async def test_basis_skips_failed_transactions_entirely() -> None:
    wallet, account, mint = "wallet", "account", "mint"
    rpc = FakeRpc(
        signatures={
            account: [
                {"signature": "reverted", "slot": 21, "err": {"InstructionError": [0, "x"]}},
                {"signature": "buy", "slot": 20, "err": None},
            ]
        },
        transactions={
            "buy": swap_transaction(
                wallet=wallet,
                token_account=account,
                mint=mint,
                token_delta=1_000 * UNIT,
                lamport_delta=-100_000_000,
                pre_tokens=0,
            )
        },
    )

    basis, reason = await reconstruct_observed_basis(
        rpc=rpc, owner=wallet, holding=holding_of(mint, 1_000 * UNIT, account)
    )

    assert basis is not None, reason
    assert basis.unit_price_sol == Decimal("0.0001")
    assert "reverted" not in rpc.fetched


# --------------------------------------------------------------------------- #
# engine-level cost basis
# --------------------------------------------------------------------------- #


def chain_with_single_buy(
    wallet: str, account: str, mint: str, *, tokens: int, lamports: int
) -> FakeRpc:
    return FakeRpc(
        signatures={account: [{"signature": f"buy-{mint[:6]}", "slot": 30, "err": None}]},
        transactions={
            f"buy-{mint[:6]}": swap_transaction(
                wallet=wallet,
                token_account=account,
                mint=mint,
                token_delta=tokens,
                lamport_delta=-lamports,
                pre_tokens=0,
            )
        },
    )


@pytest.mark.asyncio
async def test_inspect_position_prices_pnl_off_the_observed_buy_not_the_exit_quote(
    tmp_path: Path,
) -> None:
    mint = str(Keypair().pubkey())
    account = "token-account"
    # The YAML still carries the fabricated number the old code stamped: the exit
    # quote at discovery time, 0.05 SOL, which makes PnL exactly 0%.
    engine = build_engine(tmp_path, [default_policy(mint, cost_basis_sol=0.05)])
    engine.rpc = chain_with_single_buy(
        engine.wallet_address, account, mint, tokens=1_000 * UNIT, lamports=100_000_000
    )
    engine.jupiter = FakeJupiter(50_000_000)
    write_lot(engine, mint, origin=ORIGIN_DEFAULT)
    holding = holding_of(mint, 1_000 * UNIT, account)

    row, _execution = await engine._inspect_position(
        holding, engine.config.positions[0], None
    )
    await engine.close()

    # Paid 0.1 SOL, bag is worth 0.05 SOL: that is -50%, not the 0% the quote-
    # stamped basis reported.
    assert row["basis_source"] == "observed"
    assert Decimal(row["pnl_pct"]) == Decimal("-50")
    assert row["entry_unit_price_sol"] == "0.0001"
    assert row["decision"] == "exit_stop"
    assert engine.executor.calls == [
        {
            "mint": mint,
            "name": "SULLY",
            "reason": "exit_stop",
            "observed": 1_000 * UNIT,
            "amount": None,
        }
    ]
    refilled = engine._basis_refills[0]
    assert refilled.buy_price_sol == Decimal("0.0001")
    assert refilled.cost_basis_sol is None
    assert any("COST BASIS OBSERVED" in message for message in messages(engine))


@pytest.mark.asyncio
async def test_inspect_position_falls_back_to_rug_only_when_basis_cannot_be_read(
    tmp_path: Path,
) -> None:
    mint = str(Keypair().pubkey())
    account = "token-account"
    engine = build_engine(tmp_path, [default_policy(mint, cost_basis_sol=0.05)])
    engine.rpc = FakeRpc(error=ExternalServiceError("Helius RPC transport failed"))
    engine.jupiter = FakeJupiter(50_000_000)
    write_lot(engine, mint, origin=ORIGIN_DEFAULT)
    holding = holding_of(mint, 1_000 * UNIT, account)

    row, _execution = await engine._inspect_position(
        holding, engine.config.positions[0], None
    )
    await engine.close()

    # The fabricated 0.05 would have priced this at -50% and sold it. No basis
    # means no PnL, and no PnL means rug protection only.
    assert row["basis_source"] == "unavailable"
    assert row["pnl_pct"] is None
    assert row["entry_unit_price_sol"] is None
    assert row["decision"] == "hold"
    assert engine.executor.calls == []
    assert engine._basis_refills == []
    assert any("cost basis unavailable" in error for error in row["errors"])
    assert any("NO OBSERVED COST BASIS" in message for message in messages(engine))


@pytest.mark.asyncio
async def test_a_failed_basis_read_is_not_retried_until_the_cooldown_expires(
    tmp_path: Path,
) -> None:
    mint = str(Keypair().pubkey())
    engine = build_engine(tmp_path, [default_policy(mint)])
    engine.rpc = FakeRpc(signatures={"token-account": []})
    write_lot(engine, mint, origin=ORIGIN_DEFAULT)
    holding = holding_of(mint, 1_000 * UNIT, "token-account")
    lot = engine._lot(mint)

    first, reason = await engine._observed_basis(holding, lot)
    engine.rpc = FakeRpc(error=AssertionError("cooldown must suppress the second read"))
    second, cached_reason = await engine._observed_basis(holding, lot)
    # A rebuy is a new lot and must not inherit the backoff.
    engine.rpc = chain_with_single_buy(
        engine.wallet_address, "token-account", mint, tokens=1_000 * UNIT, lamports=100_000_000
    )
    next_generation, _ = await engine._observed_basis(
        holding, LotRecord(**{**vars_of(lot), "generation": lot.generation + 1})
    )
    await engine.close()

    assert first is None and second is None
    assert cached_reason == reason
    assert next_generation is not None
    assert next_generation.unit_price_sol == Decimal("0.0001")


def vars_of(record: LotRecord) -> dict[str, Any]:
    return {field: getattr(record, field) for field in LotRecord.__slots__}


@pytest.mark.asyncio
async def test_a_rebuy_gets_a_new_generation_and_inherits_neither_basis_nor_peak(
    tmp_path: Path,
) -> None:
    mint = str(Keypair().pubkey())
    account = "token-account"
    engine = build_engine(
        tmp_path, [default_policy(mint, cost_basis_sol=9.0, take_profit_pct=1000)]
    )
    write_lot(engine, mint, generation=1, origin=ORIGIN_OPERATOR)
    engine._persist_position_state(
        mint,
        PositionState(
            trailing_active=True,
            trailing_peak_unit_price_sol=Decimal("0.05"),
            below_stop_streak=3,
        ),
    )

    # The bag goes to zero, then the operator buys it again at a new price.
    assert engine._retire_absent_lot(mint) == "strip"
    engine.rpc = chain_with_single_buy(
        engine.wallet_address, account, mint, tokens=500 * UNIT, lamports=100_000_000
    )
    engine.jupiter = FakeJupiter(120_000_000)
    row, _execution = await engine._inspect_position(
        holding_of(mint, 500 * UNIT, account), engine.config.positions[0], None
    )
    await engine.close()

    assert engine._lot(mint).generation == 2
    assert engine._lot(mint).is_flat is False
    assert row["trailing_active"] is False
    assert row["trailing_peak_unit_price_sol"] is None
    assert row["runner"]["below_stop_streak"] == 0
    # 0.1 SOL for 500 tokens, now worth 0.12 SOL: +20%. The retired lot's 9 SOL
    # basis is gone, and no exit fires off an inherited peak.
    assert row["basis_source"] == "observed"
    assert Decimal(row["pnl_pct"]) == Decimal("20")
    assert row["decision"] == "hold"
    assert engine.executor.calls == []


@pytest.mark.asyncio
async def test_auto_protect_never_seeds_basis_from_the_exit_quote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    priced = str(Keypair().pubkey())
    unreadable = str(Keypair().pubkey())
    engine = build_engine(tmp_path, [])
    monkeypatch.setattr(engine_module, "DEFAULT_NEW_BAG_PROTECT_DELAY_SECONDS", 0)
    engine.rpc = FakeRpc(
        signatures={
            "priced-account": [{"signature": "buy", "slot": 30, "err": None}],
            "unreadable-account": [],
        },
        transactions={
            "buy": swap_transaction(
                wallet=engine.wallet_address,
                token_account="priced-account",
                mint=priced,
                token_delta=1_000 * UNIT,
                lamport_delta=-200_000_000,
                pre_tokens=0,
            )
        },
    )
    holdings = {
        priced: holding_of(priced, 1_000 * UNIT, "priced-account"),
        unreadable: holding_of(unreadable, 1_000 * UNIT, "unreadable-account"),
    }
    rows = [
        {"mint": priced, "name": "PRICED", "exit_sol": "0.05"},
        {"mint": unreadable, "name": "DARK", "exit_sol": "0.07"},
    ]

    await engine._schedule_and_apply_defaults(rows, holdings)
    await engine.close()

    written = {policy.mint: policy for policy in load_config(engine.config.config_path).positions}
    assert set(written) == {priced, unreadable}
    # Paid 0.2 SOL for 1000 tokens. The exit quote said the bag is worth 0.05 now,
    # and that number must appear nowhere.
    assert written[priced].buy_price_sol == Decimal("0.0002")
    assert written[priced].cost_basis_sol is None
    # No readable history: rug-only, not a guess.
    assert written[unreadable].buy_price_sol is None
    assert written[unreadable].cost_basis_sol is None
    assert written[unreadable].rug_exit is True


@pytest.mark.asyncio
async def test_auto_protect_does_not_clobber_a_concurrent_operator_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reverse direction of the config lost-update race.

    The auto-protect pass reads the policy list, reads cost basis off chain, and
    writes the merged list back. If the read and the write straddle that RPC, an
    operator rule written from the dashboard in between is silently reverted.
    """

    discovered = str(Keypair().pubkey())
    operator_mint = str(Keypair().pubkey())
    engine = build_engine(tmp_path, [])
    monkeypatch.setattr(engine_module, "DEFAULT_NEW_BAG_PROTECT_DELAY_SECONDS", 0)
    gate = asyncio.Event()

    class GatedRpc(FakeRpc):
        async def call(self, method: str, params: list[Any] | None = None) -> Any:
            if method == "getSignaturesForAddress":
                await gate.wait()
            return await super().call(method, params)

    engine.rpc = GatedRpc(
        signatures={"discovered-account": [{"signature": "buy", "slot": 30, "err": None}]},
        transactions={
            "buy": swap_transaction(
                wallet=engine.wallet_address,
                token_account="discovered-account",
                mint=discovered,
                token_delta=1_000 * UNIT,
                lamport_delta=-200_000_000,
                pre_tokens=0,
            )
        },
    )
    rows = [{"mint": discovered, "name": "NEW", "exit_sol": "0.05"}]
    holdings = {discovered: holding_of(discovered, 1_000 * UNIT, "discovered-account")}

    task = asyncio.create_task(engine._schedule_and_apply_defaults(rows, holdings))
    for _ in range(10):
        await asyncio.sleep(0)
    operator = policy_from_payload(operator_mint, {"name": "TYPED", "cost_basis_sol": 2.5})
    await engine.apply_positions([operator], origin=ORIGIN_OPERATOR, touch=[operator_mint])
    gate.set()
    await task
    await engine.close()

    written = {policy.mint: policy for policy in load_config(engine.config.config_path).positions}
    assert set(written) == {operator_mint, discovered}
    assert written[operator_mint].cost_basis_sol == Decimal("2.5")
    assert written[discovered].buy_price_sol == Decimal("0.0002")


# --------------------------------------------------------------------------- #
# pending-exit reconciliation
# --------------------------------------------------------------------------- #


def pending_engine(
    tmp_path: Path, intent: dict[str, Any], *, held: int | None, mint: str | None = None
) -> tuple[SentinelEngine, str]:
    mint = mint or str(Keypair().pubkey())
    engine = build_engine(tmp_path, [])
    holdings = [holding_of(mint, held, "token-account")] if held else []
    engine.rpc = FakeRpc(holdings=holdings)
    engine.state.set("pending_exits", mint, value=intent)
    return engine, mint


@pytest.mark.asyncio
async def test_a_terminal_failed_intent_is_never_auto_resumed(tmp_path: Path) -> None:
    engine, mint = pending_engine(
        tmp_path,
        {
            "status": "failed",
            "name": "SULLY",
            "reason": "exit_stop",
            "sell_amount": 1_000 * UNIT,
            "last_error": "RuntimeError: execution response unavailable",
        },
        held=1_000 * UNIT,
    )

    await engine.reconcile_pending_exits()
    await engine.close()

    assert engine.executor.calls == []
    stored = engine.state.get("pending_exits", mint)
    assert stored is not None, "the operator must still see the intent they were paged about"
    assert stored["resume_blocked_at"]
    assert any("NOT AUTO-RESUMED" in message for message in messages(engine))


@pytest.mark.asyncio
async def test_a_blocked_intent_does_not_page_again_on_every_restart(tmp_path: Path) -> None:
    engine, _mint = pending_engine(
        tmp_path,
        {"status": "failed", "name": "SULLY", "sell_amount": 1_000 * UNIT},
        held=1_000 * UNIT,
    )

    await engine.reconcile_pending_exits()
    await engine.reconcile_pending_exits()
    await engine.reconcile_pending_exits()
    await engine.close()

    pages = [message for message in messages(engine) if "NOT AUTO-RESUMED" in message]
    assert len(pages) == 1
    assert engine.executor.calls == []


@pytest.mark.asyncio
async def test_an_operator_acknowledged_failed_intent_is_resumed(tmp_path: Path) -> None:
    engine, mint = pending_engine(
        tmp_path,
        {
            "status": "failed",
            "name": "SULLY",
            "reason": "exit_stop",
            "sell_amount": 400 * UNIT,
            "operator_resume_ack": True,
        },
        held=1_000 * UNIT,
    )

    await engine.reconcile_pending_exits()
    await engine.close()

    assert engine.executor.calls == [
        {
            "mint": mint,
            "name": "SULLY",
            "reason": "exit_stop",
            "observed": 1_000 * UNIT,
            "amount": 400 * UNIT,
        }
    ]


@pytest.mark.asyncio
async def test_a_non_terminal_intent_is_still_resumed(tmp_path: Path) -> None:
    engine, _mint = pending_engine(
        tmp_path,
        {
            "status": "submitted_unconfirmed",
            "name": "ZOO",
            "reason": "exit_rug",
            "sell_amount": 1_000 * UNIT,
        },
        held=1_000 * UNIT,
    )

    await engine.reconcile_pending_exits()
    await engine.close()

    assert len(engine.executor.calls) == 1
    assert engine.executor.calls[0]["amount"] == 1_000 * UNIT


@pytest.mark.asyncio
async def test_a_partial_fill_while_down_clears_the_unexecutable_intent(
    tmp_path: Path,
) -> None:
    engine, mint = pending_engine(
        tmp_path,
        {
            "status": "submitting",
            "name": "SULLY",
            "reason": "exit_stop",
            "sell_amount": 1_000 * UNIT,
        },
        held=400 * UNIT,
    )

    await engine.reconcile_pending_exits()
    await engine.reconcile_pending_exits()
    await engine.close()

    # The executor would take its SELL SKIPPED early return and leave the entry
    # behind, re-firing a critical alert on every restart forever.
    assert engine.executor.calls == []
    assert engine.state.get("pending_exits", mint) is None
    assert any("unexecutable pending exit" in message for message in messages(engine))
    assert not any("Resuming pending" in message for message in messages(engine))


@pytest.mark.asyncio
async def test_an_executor_skip_deletes_the_pending_entry(tmp_path: Path) -> None:
    engine, mint = pending_engine(
        tmp_path,
        {"status": "submitting", "name": "SULLY", "reason": "exit_stop"},
        held=1_000 * UNIT,
    )
    engine.executor = RecordingExecutor(
        ExecutionResult("skipped", None, 0, "SELL SKIPPED: SULLY requested 0", 0)
    )

    await engine.reconcile_pending_exits()
    await engine.close()

    assert len(engine.executor.calls) == 1
    assert engine.state.get("pending_exits", mint) is None
    assert any("the executor skipped it" in message for message in messages(engine))


class ResolvingExecutor(RecordingExecutor):
    """Stands in for the executor's signature resolver.

    `confirmed=True` mimics the real finalizer: it writes the ledger row and
    deletes the intent. `confirmed=False` mimics a provably dead signature, which
    the real resolver reports by returning None.
    """

    def __init__(self, state: Any, *, confirmed: bool):
        super().__init__()
        self.state = state
        self.confirmed = confirmed
        self.resolved: list[dict[str, Any]] = []
        self.ledger: list[dict[str, Any]] = []

    async def resolve_pending_exit(
        self, *, mint: str, name: str, reason: str
    ) -> ExecutionResult | None:
        self.resolved.append({"mint": mint, "name": name, "reason": reason})
        if not self.confirmed:
            return None
        self.ledger.append({"mint": mint, "name": name, "signature": "landed-sig"})
        self.state.delete("pending_exits", mint)
        return ExecutionResult("success", "landed-sig", 0, "EXIT CONFIRMED", 1_000 * UNIT)


@pytest.mark.asyncio
async def test_a_fill_that_landed_while_down_is_settled_into_the_ledger(
    tmp_path: Path,
) -> None:
    engine, mint = pending_engine(
        tmp_path,
        {
            "status": "submitted_unconfirmed",
            "name": "SULLY",
            "reason": "exit_stop",
            "sell_amount": 1_000 * UNIT,
            "signature": "landed-sig",
        },
        held=None,
    )
    engine.executor = ResolvingExecutor(engine.state, confirmed=True)

    await engine.reconcile_pending_exits()
    await engine.close()

    # Realized money must not be dropped on the floor by a blind delete.
    assert engine.executor.resolved == [
        {"mint": mint, "name": "SULLY", "reason": "exit_stop"}
    ]
    assert engine.executor.ledger and engine.executor.ledger[0]["signature"] == "landed-sig"
    assert engine.state.get("pending_exits", mint) is None
    assert not any("Cleared completed pending exit" in m for m in messages(engine))


@pytest.mark.asyncio
async def test_a_dead_signature_on_an_absent_bag_is_still_cleared(tmp_path: Path) -> None:
    engine, mint = pending_engine(
        tmp_path,
        {
            "status": "submitted_unconfirmed",
            "name": "SULLY",
            "reason": "exit_stop",
            "sell_amount": 1_000 * UNIT,
            "signature": "dead-sig",
        },
        held=None,
    )
    engine.executor = ResolvingExecutor(engine.state, confirmed=False)

    await engine.reconcile_pending_exits()
    await engine.close()

    assert len(engine.executor.resolved) == 1
    assert engine.executor.ledger == []
    assert engine.state.get("pending_exits", mint) is None
    assert any("Cleared completed pending exit" in m for m in messages(engine))


@pytest.mark.asyncio
async def test_an_in_flight_signature_is_never_cleared_by_the_amount_check(
    tmp_path: Path,
) -> None:
    """A partial fill plus a live signature belongs to the executor, not here."""

    engine, mint = pending_engine(
        tmp_path,
        {
            "status": "submitted_unconfirmed",
            "name": "SULLY",
            "reason": "exit_stop",
            "sell_amount": 1_000 * UNIT,
            "signature": "in-flight-sig",
        },
        held=400 * UNIT,
    )

    await engine.reconcile_pending_exits()
    await engine.close()

    # Handed to the executor (which resolves the signature first), not deleted.
    assert len(engine.executor.calls) == 1
    assert engine.state.get("pending_exits", mint) is not None
    assert not any("unexecutable pending exit" in m for m in messages(engine))


@pytest.mark.asyncio
async def test_a_pending_exit_for_a_bag_that_is_gone_is_cleared(tmp_path: Path) -> None:
    engine, mint = pending_engine(
        tmp_path,
        {"status": "failed", "name": "SULLY", "sell_amount": 1_000 * UNIT},
        held=None,
    )

    await engine.reconcile_pending_exits()
    await engine.close()

    assert engine.state.get("pending_exits", mint) is None
    assert engine.executor.calls == []
    assert any("Cleared completed pending exit" in message for message in messages(engine))
