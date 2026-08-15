"""Behavioral tests for the only module that spends money.

Every test drives the real `SellExecutor` against a fake Jupiter and a fake
Helius. Transaction validation, signing, and the simulation gate are the real
implementations from `shitcoims_sentinel.transaction`; only the network edge is
faked. The fake wallet moves only when a signature is observed confirmed, which
is what makes the double-submit tests meaningful.
"""

from __future__ import annotations

import base64
import csv
import os
import struct
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction

from shitcoims_sentinel import executor as executor_module
from shitcoims_sentinel.clients import ExternalServiceError
from shitcoims_sentinel.config import AppConfig, load_config
from shitcoims_sentinel.domain import WSOL_MINT, PoolSnapshot, TokenHolding, utc_now
from shitcoims_sentinel.executor import ExecutionGate, SellExecutor
from shitcoims_sentinel.storage import StateStore
from shitcoims_sentinel.transaction import (
    COMPUTE_BUDGET_PROGRAM,
    JUPITER_V6_PROGRAM,
    LANDING_BID_FLOOR_MICRO_LAMPORTS,
)

WALLET_SOL = 1_000_000_000
OUT_AMOUNT = 500_000_000


def build_config(tmp_path: Path, *, enabled: bool = True, max_attempts: int = 3) -> AppConfig:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
rpc:
  helius_api_key_file: ./helius
wallet:
  name: shitcoims
  secret_key_file: ./wallet
jupiter:
  api_key_file: ./jupiter
  slippage_bps: 1500
execution:
  enabled: {"true" if enabled else "false"}
  arm_file: ./LIVE_ARMED
  max_attempts: {max_attempts}
  retry_delay_seconds: 0.001
  max_sol_cost_lamports: 20000000
state_dir: ./state
positions: []
""",
        encoding="utf-8",
    )
    return load_config(config_path)


def unsigned_jupiter_transaction(
    payer: Keypair, *, compute_unit_price: int | None = None, compute_unit_limit: int | None = None
) -> str:
    budget = Pubkey.from_string(COMPUTE_BUDGET_PROGRAM)
    instructions = []
    if compute_unit_limit is not None:
        instructions.append(Instruction(budget, bytes([2]) + struct.pack("<I", compute_unit_limit), []))
    if compute_unit_price is not None:
        instructions.append(Instruction(budget, bytes([3]) + struct.pack("<Q", compute_unit_price), []))
    swap = Instruction(Pubkey.from_string(JUPITER_V6_PROGRAM), b"swap", [])
    instructions.append(swap)
    message = MessageV0.try_compile(payer.pubkey(), instructions, [], Hash.new_unique())
    unsigned = VersionedTransaction.populate(message, [Signature.default()])
    return base64.b64encode(bytes(unsigned)).decode("ascii")


def signature_of(encoded_signed: str) -> str:
    return str(VersionedTransaction.from_bytes(base64.b64decode(encoded_signed)).signatures[0])


def token_account_blob(amount: int) -> dict[str, Any]:
    raw = bytearray(165)
    struct.pack_into("<Q", raw, 64, amount)
    return {"lamports": 2_039_280, "data": [base64.b64encode(raw).decode(), "base64"]}


def holding(mint: str, amount: int, *, accounts: tuple[str, ...] | None = None) -> TokenHolding:
    return TokenHolding(
        mint=mint,
        amount=amount,
        decimals=6,
        token_accounts=accounts or (f"{mint}-account",),
        program_ids=("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",),
    )


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(
        self,
        *,
        severity: str,
        category: str,
        message: str,
        context: dict[str, Any] | None = None,
        dedup_key: str | None = None,
        dedup_seconds: float = 300,
    ) -> None:
        self.sent.append(
            {
                "severity": severity,
                "category": category,
                "message": message,
                "context": context or {},
            }
        )

    def messages(self) -> list[str]:
        return [item["message"] for item in self.sent]


class FakeJupiter:
    """Jupiter's order/execute edge, with a scripted `execute` response list."""

    def __init__(
        self,
        *,
        payer: Keypair,
        ready: bool = True,
        out_amount: int = OUT_AMOUNT,
        threshold: int | None = None,
        responses: list[dict[str, Any]] | None = None,
        signature_override: str | None = None,
        compute_unit_price: int | None = None,
        compute_unit_limit: int | None = None,
    ) -> None:
        self.ready = ready
        self.compute_unit_price = compute_unit_price
        self.compute_unit_limit = compute_unit_limit
        self._payer = payer
        self.out_amount = out_amount
        self.threshold = out_amount - 1 if threshold is None else threshold
        self._responses = responses
        self.signature_override = signature_override
        self.order_calls: list[dict[str, Any]] = []
        self.execute_calls: list[dict[str, Any]] = []
        self.order_hook: Callable[[int], None] | None = None

    async def executable_order(
        self, mint: str, amount: int, taker: str, *, slippage_bps: int | None = None
    ) -> dict[str, Any]:
        self.order_calls.append(
            {"mint": mint, "amount": amount, "taker": taker, "slippage_bps": slippage_bps}
        )
        if self.order_hook is not None:
            self.order_hook(len(self.order_calls))
        return {
            # A fresh order carries a fresh blockhash, so every re-quote is a
            # different transaction with a different signature.
            "transaction": unsigned_jupiter_transaction(
                self._payer,
                compute_unit_price=self.compute_unit_price,
                compute_unit_limit=self.compute_unit_limit,
            ),
            "requestId": f"request-{len(self.order_calls)}",
            "inputMint": mint,
            "outputMint": WSOL_MINT,
            "inAmount": str(amount),
            "outAmount": str(self.out_amount),
            "otherAmountThreshold": str(self.threshold),
            "router": "metis",
        }

    async def execute(self, *, signed_transaction: str, request_id: str) -> dict[str, Any]:
        self.execute_calls.append(
            {"request_id": request_id, "signature": signature_of(signed_transaction)}
        )
        if self._responses is not None:
            index = min(len(self.execute_calls) - 1, len(self._responses) - 1)
            return dict(self._responses[index])
        return {
            "status": "Success",
            "code": 0,
            "signature": self.signature_override or signature_of(signed_transaction),
            "totalOutputAmount": str(OUT_AMOUNT),
        }


class FakeRpc:
    """Helius' read + simulate edge.

    `holdings` is the live wallet. It changes only when a signature is observed
    confirmed, at which point `post_fill_holdings` becomes the wallet — the same
    ordering the real chain gives us.
    """

    def __init__(
        self,
        *,
        holdings: list[TokenHolding],
        post_fill_holdings: list[TokenHolding] | None = None,
        sol_lamports: int = WALLET_SOL,
        post_sol_lamports: int | None = None,
        post_token_amounts: dict[str, int] | None = None,
        blockhash_valid_value: bool = True,
        simulate_error: Exception | None = None,
        units_consumed: int = 123_615,
    ) -> None:
        self.units_consumed = units_consumed
        self.holdings = list(holdings)
        self.post_fill_holdings = post_fill_holdings
        self.sol_lamports = sol_lamports
        self.post_sol_lamports = (
            sol_lamports + OUT_AMOUNT if post_sol_lamports is None else post_sol_lamports
        )
        self.post_token_amounts = post_token_amounts or {}
        self.blockhash_valid_value = blockhash_valid_value
        self.blockhash_calls: list[str] = []
        self.simulate_error = simulate_error
        self.simulate_calls: list[list[str]] = []
        self.holdings_calls = 0
        self.signature_status_calls: list[str] = []
        # Default: whatever we submitted landed cleanly.
        self.status_hook: Callable[[str], str] = lambda _signature: "confirmed"

    async def token_holdings(self, _owner: str) -> list[TokenHolding]:
        self.holdings_calls += 1
        return list(self.holdings)

    async def sol_balance(self, _owner: str) -> int:
        return self.sol_lamports

    async def account_data(self, _address: str) -> bytes:
        raise AssertionError("fake exit transaction has no address lookup tables")

    async def simulate_transaction_accounts(
        self, _encoded: str, addresses: list[str]
    ) -> dict[str, Any]:
        self.simulate_calls.append(list(addresses))
        if self.simulate_error is not None:
            raise self.simulate_error
        if len(addresses) > 32 or len(addresses) != len(set(addresses)):
            raise ExternalServiceError(
                f"simulation account set of {len(addresses)} exceeds the 32-address ceiling"
            )
        current = {
            account: item.amount
            for item in self.holdings
            for account in item.token_accounts
        }
        accounts: list[dict[str, Any]] = [{"lamports": self.post_sol_lamports}]
        for address in addresses[1:]:
            accounts.append(
                token_account_blob(self.post_token_amounts.get(address, current.get(address, 0)))
            )
        # The measured median compute consumption of a real swap (238 sampled swaps,
        # studies/RESULT_execution_landing.md §8). A toy number here would make every
        # compute-limit assertion in this file meaningless.
        return {"accounts": accounts, "units_consumed": self.units_consumed}

    async def signature_status(self, signature: str) -> str:
        self.signature_status_calls.append(signature)
        state = self.status_hook(signature)
        if state == "confirmed" and self.post_fill_holdings is not None:
            self.holdings = list(self.post_fill_holdings)
        return state

    async def signature_confirmed(self, signature: str) -> bool:
        return await self.signature_status(signature) == "confirmed"

    async def blockhash_valid(self, blockhash: str) -> bool:
        self.blockhash_calls.append(blockhash)
        return self.blockhash_valid_value


class Harness:
    def __init__(self, config: AppConfig, keypair: Keypair, rpc: FakeRpc, jupiter: FakeJupiter):
        self.config = config
        self.keypair = keypair
        self.rpc = rpc
        self.jupiter = jupiter
        self.notifier = FakeNotifier()
        self.state = StateStore(config.state_file)
        self.gate = ExecutionGate(config, keypair, cli_live=True)
        self.executor = SellExecutor(
            config=config,
            keypair=keypair,
            gate=self.gate,
            rpc=rpc,  # type: ignore[arg-type]
            jupiter=jupiter,  # type: ignore[arg-type]
            state=self.state,
            notifier=self.notifier,  # type: ignore[arg-type]
        )

    def pending(self, mint: str) -> dict[str, Any] | None:
        return self.state.get("pending_exits", mint, default=None)

    def trades(self) -> list[dict[str, str]]:
        path = self.config.trades_file
        if not path.exists():
            return []
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))


def _after_fill(
    holdings: list[TokenHolding], post_token_amounts: dict[str, int]
) -> list[TokenHolding] | None:
    """The wallet the chain would show once the simulated post-state is real."""
    if not post_token_amounts:
        return None
    settled: list[TokenHolding] = []
    for item in holdings:
        amount = sum(
            post_token_amounts.get(account, item.amount // len(item.token_accounts))
            for account in item.token_accounts
        )
        if amount > 0:
            settled.append(
                TokenHolding(item.mint, amount, item.decimals, item.token_accounts, item.program_ids)
            )
    return settled


def make_harness(
    tmp_path: Path,
    *,
    holdings: list[TokenHolding] | None = None,
    post_token_amounts: dict[str, int] | None = None,
    post_fill_holdings: list[TokenHolding] | None = None,
    blockhash_valid_value: bool = True,
    responses: list[dict[str, Any]] | None = None,
    signature_override: str | None = None,
    simulate_error: Exception | None = None,
    threshold: int | None = None,
    jupiter_ready: bool = True,
    enabled: bool = True,
    cli_live: bool = True,
    armed: bool = True,
    max_attempts: int = 3,
    post_sol_lamports: int | None = None,
    compute_unit_price: int | None = None,
    compute_unit_limit: int | None = None,
) -> Harness:
    keypair = Keypair()
    config = build_config(tmp_path, enabled=enabled, max_attempts=max_attempts)
    wallet = holdings if holdings is not None else [holding("target", 1_000)]
    amounts = post_token_amounts or {}
    rpc = FakeRpc(
        holdings=wallet,
        post_fill_holdings=(
            post_fill_holdings if post_fill_holdings is not None else _after_fill(wallet, amounts)
        ),
        post_token_amounts=amounts,
        blockhash_valid_value=blockhash_valid_value,
        simulate_error=simulate_error,
        post_sol_lamports=post_sol_lamports,
    )
    jupiter = FakeJupiter(
        payer=keypair,
        ready=jupiter_ready,
        threshold=threshold,
        responses=responses,
        signature_override=signature_override,
        compute_unit_price=compute_unit_price,
        compute_unit_limit=compute_unit_limit,
    )
    harness = Harness(config, keypair, rpc, jupiter)
    harness.gate.cli_live = cli_live
    if armed:
        config.execution.arm_file.parent.mkdir(parents=True, exist_ok=True)
        config.execution.arm_file.write_text(harness.gate.expected_arm_value, encoding="utf-8")
        os.chmod(config.execution.arm_file, 0o600)
    return harness


@pytest.fixture(autouse=True)
def fast_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the signature-resolution window deterministic and instant."""
    monkeypatch.setattr(executor_module, "RESOLUTION_POLL_SECONDS", 0.0)
    monkeypatch.setattr(executor_module, "RESOLUTION_POLL_ATTEMPTS", 4)


# --------------------------------------------------------------------------
# Early return: nothing may be built or submitted for an impossible amount.
# --------------------------------------------------------------------------


async def test_sell_skips_when_requested_amount_exceeds_the_observed_balance(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path)
    target = holding("target", 1_000)

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target, amount=1_001
    )

    assert result.status == "skipped"
    assert result.input_amount == 0
    assert result.message.startswith("SELL SKIPPED")
    assert harness.jupiter.order_calls == []
    assert harness.jupiter.execute_calls == []
    assert harness.pending("target") is None
    assert harness.notifier.sent[0]["severity"] == "warning"


async def test_sell_skips_a_zero_amount_without_touching_jupiter(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    target = holding("target", 1_000)

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_scale", observed_holding=target, amount=0
    )

    assert result.status == "skipped"
    assert harness.jupiter.order_calls == []


# --------------------------------------------------------------------------
# The three local live gates, plus the Jupiter readiness gate.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected_failure"),
    [
        ({"enabled": False}, "execution.enabled is false"),
        ({"cli_live": False}, "process was not started with --live"),
        ({"armed": False}, "arm file is absent"),
        ({"jupiter_ready": False}, "Jupiter API key is unavailable"),
    ],
)
async def test_each_open_gate_forces_a_dry_run_that_cannot_submit(
    tmp_path: Path, kwargs: dict[str, Any], expected_failure: str
) -> None:
    harness = make_harness(tmp_path, **kwargs)
    target = holding("target", 1_000)

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "dry_run"
    assert result.signature is None
    assert result.input_amount == 1_000
    assert expected_failure in result.message
    assert harness.jupiter.order_calls == []
    assert harness.jupiter.execute_calls == []
    assert harness.pending("target") is None


async def test_dry_run_message_distinguishes_a_partial_slice_from_a_full_exit(
    tmp_path: Path,
) -> None:
    harness = make_harness(tmp_path, enabled=False)
    target = holding("target", 1_000)

    full = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )
    partial = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_scale", observed_holding=target, amount=300
    )

    assert "would sell all TGT" in full.message
    assert "would sell 300 raw TGT" in partial.message


# --------------------------------------------------------------------------
# The confirmed live path.
# --------------------------------------------------------------------------


async def test_confirmed_live_exit_clears_pending_state_and_appends_one_trade_row(
    tmp_path: Path,
) -> None:
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, post_token_amounts={"target-account": 0})

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "success"
    assert result.input_amount == 1_000
    assert result.output_lamports == OUT_AMOUNT
    assert result.signature == harness.jupiter.execute_calls[0]["signature"]
    assert harness.pending("target") is None
    rows = harness.trades()
    assert len(rows) == 1
    assert rows[0]["mint"] == "target"
    assert rows[0]["input_amount"] == "1000"
    assert rows[0]["output_lamports"] == str(OUT_AMOUNT)
    assert rows[0]["signature"] == result.signature
    assert "EXIT CONFIRMED" in result.message


async def test_a_bid_under_the_landing_cliff_alarms_but_never_blocks_the_sale(
    tmp_path: Path,
) -> None:
    """The 3x lever we do not own, made visible without becoming a new way to not sell.

    Jupiter builds this transaction and chooses its own ComputeBudget instructions. Measured
    landing is 29.6% below 50,000 microlamports/CU against 97.2% at or above it, so a cheap
    bid is worth shouting about — but refusing to submit would turn a price problem into a
    total-loss problem on a bag that may be rugging. This is a sell-only system.
    """

    target = holding("target", 1_000)
    harness = make_harness(
        tmp_path,
        post_token_amounts={"target-account": 0},
        compute_unit_price=LANDING_BID_FLOOR_MICRO_LAMPORTS - 1,
        compute_unit_limit=160_000,
    )

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_rug", observed_holding=target
    )

    assert result.status == "success"
    assert harness.jupiter.execute_calls  # it was submitted
    alarms = [item for item in harness.notifier.sent if "LOW LANDING BID" in item["message"]]
    assert alarms, harness.notifier.messages()
    alarm = alarms[0]
    assert alarm["severity"] == "critical"
    assert alarm["context"]["compute_unit_price_micro_lamports"] == (
        LANDING_BID_FLOOR_MICRO_LAMPORTS - 1
    )
    assert alarm["context"]["compute_unit_limit"] == 160_000
    assert alarm["context"]["auto_action"] is False


async def test_every_send_records_the_bid_and_what_the_swap_actually_consumed(
    tmp_path: Path,
) -> None:
    """The tape cannot supply these; only our own sends can. So they are recorded on all of them."""

    target = holding("target", 1_000)
    harness = make_harness(
        tmp_path,
        post_token_amounts={"target-account": 0},
        compute_unit_price=120_000,
        compute_unit_limit=160_000,
    )

    await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    records = [item for item in harness.notifier.sent if item["message"].startswith("bid ")]
    assert records, harness.notifier.messages()
    recorded = records[0]
    assert recorded["severity"] == "info"
    assert recorded["context"]["compute_unit_price_micro_lamports"] == 120_000
    assert recorded["context"]["compute_unit_limit"] == 160_000
    # Read back from our own simulateTransaction rather than assumed.
    assert recorded["context"]["simulated_units_consumed"] == 123_615
    assert not any("LOW LANDING BID" in item["message"] for item in harness.notifier.sent)


async def test_a_compute_request_far_above_consumption_is_reported(tmp_path: Path) -> None:
    target = holding("target", 1_000)
    harness = make_harness(
        tmp_path,
        post_token_amounts={"target-account": 0},
        compute_unit_price=120_000,
        compute_unit_limit=1_000_000,
    )

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "success"
    warnings = [
        item for item in harness.notifier.sent if "OVERSIZED COMPUTE REQUEST" in item["message"]
    ]
    assert warnings, harness.notifier.messages()
    warning = warnings[0]
    assert warning["severity"] == "warning"
    assert warning["context"]["simulated_units_consumed"] == 123_615


def cp_pool(mint: str = "target", *, dex_id: str = "pumpswap", sol: str = "40") -> PoolSnapshot:
    """A constant-product pool holding `sol` SOL against tokens priced at 1e-7 SOL each."""

    return PoolSnapshot(
        pair_address="pair",
        dex_id=dex_id,
        base_mint=mint,
        quote_mint=WSOL_MINT,
        liquidity_usd=Decimal("7000"),
        reserve_value=Decimal(sol),
        reserve_unit="SOL",
        price_native=Decimal("0.0000001"),
        observed_at=utc_now(),
    )


async def test_an_order_authorising_less_than_the_pool_would_pay_is_refused(
    tmp_path: Path,
) -> None:
    """The replacement for a 1500bps tolerance, which is an adversary's budget to spend.

    The threshold Jupiter puts on chain is what actually constrains the fill, so that is
    what is compared against the pool's own arithmetic. Here the order authorises far less
    than the reserves imply, which is the shape of a sandwich, and the sale does not happen.
    """

    target = holding("target", 1_000 * 10**6)
    harness = make_harness(
        tmp_path,
        holdings=[target],
        post_token_amounts={"target-account": 0},
        threshold=1,  # authorises giving essentially the whole fill away
    )

    result = await harness.executor.sell(
        mint="target",
        name="TGT",
        reason="exit_stop",
        observed_holding=target,
        pool=cp_pool(),
    )

    assert result.status == "skipped"
    assert "below the" in result.message
    assert harness.jupiter.execute_calls == []  # nothing was submitted
    assert harness.pending("target") is None
    refusal = [item for item in harness.notifier.sent if "SELL REFUSED" in item["message"]]
    assert refusal and refusal[0]["severity"] == "critical"
    assert refusal[0]["context"]["reserve_floor_lamports"] > 1


async def test_an_emergency_exit_is_never_blocked_by_the_reserve_floor(tmp_path: Path) -> None:
    """Not selling a rugging bag is the worse failure, by a wide margin."""

    target = holding("target", 1_000 * 10**6)
    harness = make_harness(
        tmp_path,
        holdings=[target],
        post_token_amounts={"target-account": 0},
        threshold=1,
    )

    result = await harness.executor.sell(
        mint="target",
        name="TGT",
        reason="exit_rug",
        observed_holding=target,
        pool=cp_pool(),
    )

    assert result.status == "success"
    assert harness.jupiter.execute_calls
    alarm = [item for item in harness.notifier.sent if "PRICED BELOW THE POOL" in item["message"]]
    assert alarm and alarm[0]["severity"] == "critical"


async def test_a_pool_that_cannot_be_modelled_never_blocks_a_sale(tmp_path: Path) -> None:
    """No pool, and a pool that does not price on the constant-product curve, both proceed.

    The floor is evidence or it is nothing. A fabricated one would be a new way to fail to
    sell, which is the failure this system exists to avoid.
    """

    for pool in (None, cp_pool(dex_id="meteora")):
        target = holding("target", 1_000 * 10**6)
        case = tmp_path / f"case-{pool.dex_id if pool else 'none'}"
        case.mkdir(parents=True, exist_ok=True)
        harness = make_harness(
            case,
            holdings=[target],
            post_token_amounts={"target-account": 0},
            threshold=1,
        )
        result = await harness.executor.sell(
            mint="target",
            name="TGT",
            reason="exit_stop",
            observed_holding=target,
            pool=pool,
        )
        assert result.status == "success"


async def test_an_order_at_or_above_the_pool_floor_is_never_questioned(tmp_path: Path) -> None:
    target = holding("target", 1_000 * 10**6)
    # 1000 tokens at 1e-7 SOL is ~1e-4 SOL = 100,000 lamports before impact; OUT_AMOUNT is
    # far above that, so the authorised threshold clears the floor comfortably.
    harness = make_harness(
        tmp_path, holdings=[target], post_token_amounts={"target-account": 0}
    )

    result = await harness.executor.sell(
        mint="target",
        name="TGT",
        reason="exit_stop",
        observed_holding=target,
        pool=cp_pool(),
    )

    assert result.status == "success"
    assert not any("SELL REFUSED" in item["message"] for item in harness.notifier.sent)


async def test_pending_exit_walks_intent_then_submitting_then_deletion(tmp_path: Path) -> None:
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, post_token_amounts={"target-account": 0})
    observed: list[str] = []
    harness.jupiter.order_hook = lambda _n: observed.append(
        str((harness.pending("target") or {}).get("status"))
    )
    original_execute = harness.jupiter.execute

    async def recording_execute(**kwargs: Any) -> dict[str, Any]:
        observed.append(str((harness.pending("target") or {}).get("status")))
        return await original_execute(**kwargs)

    harness.jupiter.execute = recording_execute  # type: ignore[method-assign]

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "success"
    assert observed == ["intent", "submitting"]
    assert harness.pending("target") is None


async def test_submitting_intent_records_the_signature_before_execute_is_called(
    tmp_path: Path,
) -> None:
    """The locally derived signature must be durable before the tx can be broadcast."""
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, post_token_amounts={"target-account": 0})
    captured: list[dict[str, Any]] = []
    original_execute = harness.jupiter.execute

    async def recording_execute(**kwargs: Any) -> dict[str, Any]:
        captured.append(harness.pending("target") or {})
        return await original_execute(**kwargs)

    harness.jupiter.execute = recording_execute  # type: ignore[method-assign]

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "success"
    assert captured[0]["signature"] == result.signature
    assert captured[0]["recent_blockhash"]
    assert captured[0]["expected_remaining"] == 0


async def test_balance_already_filled_reconciles_without_submitting_anything(
    tmp_path: Path,
) -> None:
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, holdings=[])

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "reconciled"
    assert harness.jupiter.order_calls == []
    assert harness.jupiter.execute_calls == []
    assert harness.pending("target") is None
    assert harness.trades() == []


async def test_scale_exit_sells_only_the_slice_and_binds_the_expected_remainder(
    tmp_path: Path,
) -> None:
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, post_token_amounts={"target-account": 700})

    result = await harness.executor.sell(
        mint="target",
        name="TGT",
        reason="exit_scale",
        observed_holding=target,
        amount=300,
    )

    assert result.status == "success"
    assert result.input_amount == 300
    assert harness.jupiter.order_calls[0]["amount"] == 300
    assert "SCALE CONFIRMED" in result.message
    assert harness.trades()[0]["input_amount"] == "300"


async def test_confirmed_dispose_exit_disables_the_dispose_policy(tmp_path: Path) -> None:
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, post_token_amounts={"target-account": 0})

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_dispose", observed_holding=target
    )

    assert result.status == "success"
    assert harness.state.get("dispose_policies", "target", "enabled") is False


# --------------------------------------------------------------------------
# The double-submit defect: an unresolved signature must block every retry.
# --------------------------------------------------------------------------


async def test_unconfirmed_submission_never_builds_a_second_order(tmp_path: Path) -> None:
    """The whole point: an in-flight signature must not be re-quoted and re-sent."""
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, post_token_amounts={"target-account": 0})
    # The cluster has never heard of the signature and the blockhash is still
    # valid, so the transaction may still land.
    harness.rpc.status_hook = lambda _signature: "unknown"

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "unresolved"
    assert len(harness.jupiter.order_calls) == 1
    assert len(harness.jupiter.execute_calls) == 1
    pending = harness.pending("target")
    assert pending is not None
    assert pending["status"] == "submitted_unconfirmed"
    assert pending["signature"] == harness.jupiter.execute_calls[0]["signature"]
    assert harness.trades() == []
    assert any("UNRESOLVED" in message for message in harness.notifier.messages())


async def test_expired_blockhash_proves_death_and_only_then_permits_a_new_order(
    tmp_path: Path,
) -> None:
    target = holding("target", 1_000)
    harness = make_harness(
        tmp_path, post_token_amounts={"target-account": 0}, blockhash_valid_value=False
    )
    harness.rpc.status_hook = lambda signature: (
        "unknown" if signature == harness.jupiter.execute_calls[0]["signature"] else "confirmed"
    )

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "success"
    assert len(harness.jupiter.execute_calls) == 2
    assert harness.rpc.blockhash_calls, "death must be proven by blockhash expiry, not assumed"
    assert harness.pending("target") is None
    assert len(harness.trades()) == 1


async def test_a_landed_but_failed_transaction_is_safe_to_retry(tmp_path: Path) -> None:
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, post_token_amounts={"target-account": 0})
    harness.rpc.status_hook = lambda signature: (
        "failed" if signature == harness.jupiter.execute_calls[0]["signature"] else "confirmed"
    )

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "success"
    assert len(harness.jupiter.execute_calls) == 2
    assert len(harness.trades()) == 1


async def test_execute_transport_failure_resolves_the_signature_before_retrying(
    tmp_path: Path,
) -> None:
    """A timed-out /execute may still have broadcast: resolve before re-quoting."""
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, post_token_amounts={"target-account": 0})

    async def failing_execute(*, signed_transaction: str, request_id: str) -> dict[str, Any]:
        harness.jupiter.execute_calls.append(
            {"request_id": request_id, "signature": signature_of(signed_transaction)}
        )
        raise ExternalServiceError("Jupiter execute transport failed (ReadTimeout)")

    harness.jupiter.execute = failing_execute  # type: ignore[method-assign]
    harness.rpc.status_hook = lambda _signature: "unknown"

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "unresolved"
    assert len(harness.jupiter.order_calls) == 1
    assert len(harness.jupiter.execute_calls) == 1
    pending = harness.pending("target")
    assert pending is not None
    assert pending["signature"] == harness.jupiter.execute_calls[0]["signature"]


async def test_resuming_an_unresolved_pending_exit_resolves_it_instead_of_reselling(
    tmp_path: Path,
) -> None:
    """`reconcile_pending_exits` re-enters `sell`; the stored signature must win."""
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, post_fill_holdings=[])
    harness.state.set(
        "pending_exits",
        "target",
        value={
            "created_at": "2026-08-12T00:00:00+00:00",
            "wallet": "shitcoims",
            "mint": "target",
            "name": "TGT",
            "reason": "exit_stop",
            "status": "submitted_unconfirmed",
            "signature": "prior-signature",
            "recent_blockhash": "prior-blockhash",
            "sell_amount": 1_000,
            "expected_remaining": 0,
            "last_observed_amount": 1_000,
            "output_lamports": 424_242,
        },
    )

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "success"
    assert result.signature == "prior-signature"
    assert harness.jupiter.order_calls == []
    assert harness.jupiter.execute_calls == []
    assert harness.pending("target") is None
    assert harness.trades()[0]["signature"] == "prior-signature"
    assert harness.trades()[0]["output_lamports"] == "424242"


async def test_resume_blocks_when_the_stored_signature_stays_unresolved(
    tmp_path: Path,
) -> None:
    target = holding("target", 1_000)
    harness = make_harness(tmp_path)
    harness.rpc.status_hook = lambda _signature: "unknown"
    harness.state.set(
        "pending_exits",
        "target",
        value={
            "mint": "target",
            "name": "TGT",
            "reason": "exit_stop",
            "status": "submitted_unconfirmed",
            "signature": "prior-signature",
            "recent_blockhash": "prior-blockhash",
            "sell_amount": 1_000,
            "expected_remaining": 0,
        },
    )

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "unresolved"
    assert harness.jupiter.order_calls == []
    assert (harness.pending("target") or {})["signature"] == "prior-signature"


async def test_jupiter_signature_mismatch_stops_the_exit_instead_of_retrying(
    tmp_path: Path,
) -> None:
    target = holding("target", 1_000)
    harness = make_harness(
        tmp_path,
        post_token_amounts={"target-account": 0},
        signature_override="4NotTheSignatureWeSigned",
    )
    harness.rpc.status_hook = lambda _signature: "unknown"

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "unresolved"
    assert len(harness.jupiter.execute_calls) == 1
    last_error = str((harness.pending("target") or {}).get("last_error"))
    assert "signature" in last_error


# --------------------------------------------------------------------------
# Retry loop and terminal failure.
# --------------------------------------------------------------------------


async def test_rejected_order_retries_up_to_max_attempts_then_fails_closed(
    tmp_path: Path,
) -> None:
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, post_token_amounts={"target-account": 0}, max_attempts=3)

    def reject(_call: int) -> None:
        raise ExternalServiceError("Jupiter order failed with code 429")

    harness.jupiter.order_hook = reject

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "failed"
    assert result.attempts == 3
    assert len(harness.jupiter.order_calls) == 3
    assert harness.jupiter.execute_calls == []
    pending = harness.pending("target")
    assert pending is not None
    assert pending["status"] == "failed"
    assert "429" in pending["last_error"]
    assert harness.notifier.sent[-1]["severity"] == "critical"
    assert "MANUAL ACTION REQUIRED" in result.message


async def test_a_non_success_execute_code_is_reported_verbatim(tmp_path: Path) -> None:
    target = holding("target", 1_000)
    harness = make_harness(
        tmp_path,
        post_token_amounts={"target-account": 0},
        responses=[{"status": "Failed", "code": 6001, "error": "slippage"}],
        max_attempts=1,
    )
    harness.rpc.status_hook = lambda _signature: "unknown"

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "unresolved"
    pending = harness.pending("target")
    assert pending is not None
    assert "6001" in str(pending.get("last_error"))


# --------------------------------------------------------------------------
# Failure legibility.
# --------------------------------------------------------------------------


async def test_a_security_stop_is_named_as_such_in_the_pending_intent(tmp_path: Path) -> None:
    target = holding("target", 1_000)
    harness = make_harness(
        tmp_path,
        # The simulation would leave half the bag behind: the exit must not go out.
        post_token_amounts={"target-account": 500},
        post_fill_holdings=[holding("target", 1_000)],
        max_attempts=1,
    )

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "failed"
    last_error = str((harness.pending("target") or {}).get("last_error"))
    assert "security stop" in last_error
    assert "TransactionRejected" in last_error
    assert "complete target balance" in last_error
    assert harness.jupiter.execute_calls == []


async def test_an_external_service_failure_is_distinguishable_from_a_security_stop(
    tmp_path: Path,
) -> None:
    target = holding("target", 1_000)
    harness = make_harness(
        tmp_path,
        simulate_error=ExternalServiceError("Helius RPC transport failed (ReadTimeout)"),
        max_attempts=1,
    )

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=target
    )

    assert result.status == "failed"
    last_error = str((harness.pending("target") or {}).get("last_error"))
    assert "external service" in last_error
    assert "ReadTimeout" in last_error
    assert "security stop" not in last_error


def test_transport_failures_are_classified_without_leaking_the_request() -> None:
    request = httpx.Request("GET", "https://mainnet.helius-rpc.com/?api-key=SECRET")
    described = executor_module.describe_execution_failure(
        httpx.ConnectTimeout("timed out", request=request)
    )

    assert "ConnectTimeout" in described
    assert "SECRET" not in described
    assert "helius-rpc.com" not in described


# --------------------------------------------------------------------------
# The 32-address simulation ceiling.
# --------------------------------------------------------------------------


async def test_a_wallet_past_the_32_account_ceiling_can_still_exit(tmp_path: Path) -> None:
    wallet = [holding("target", 1_000)] + [
        holding(f"bag{index}", 100 + index) for index in range(60)
    ]
    harness = make_harness(
        tmp_path,
        holdings=wallet,
        post_token_amounts={"target-account": 0},
        post_fill_holdings=wallet[1:],
    )

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=wallet[0]
    )

    assert result.status == "success"
    assert len(harness.rpc.simulate_calls) > 1
    covered: set[str] = set()
    for addresses in harness.rpc.simulate_calls:
        assert len(addresses) <= 32
        assert addresses[0] == str(harness.keypair.pubkey())
        assert "target-account" in addresses
        covered.update(addresses)
    every_account = {account for item in wallet for account in item.token_accounts}
    assert every_account <= covered, "every owned token must stay inside the invariant"


async def test_a_simulation_that_cannot_cover_the_wallet_fails_loudly(tmp_path: Path) -> None:
    fat_target = holding(
        "target", 4_000, accounts=tuple(f"target-account-{index}" for index in range(40))
    )
    harness = make_harness(
        tmp_path,
        holdings=[fat_target],
        post_token_amounts={f"target-account-{index}": 0 for index in range(40)},
        max_attempts=1,
    )

    result = await harness.executor.sell(
        mint="target", name="TGT", reason="exit_stop", observed_holding=fat_target
    )

    assert result.status == "failed"
    last_error = str((harness.pending("target") or {}).get("last_error"))
    assert "simulation coverage" in last_error
    assert "32" in last_error
    assert harness.jupiter.execute_calls == []


# --------------------------------------------------------------------------
# Computed minimum output instead of a blanket slippage percentage.
# --------------------------------------------------------------------------


async def test_ordinary_exits_use_the_tight_epsilon_not_the_configured_ceiling(
    tmp_path: Path,
) -> None:
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, post_token_amounts={"target-account": 0})

    await harness.executor.sell(
        mint="target", name="TGT", reason="exit_trail", observed_holding=target
    )

    assert harness.jupiter.order_calls[0]["slippage_bps"] == 250
    assert harness.config.jupiter.slippage_bps == 1500


@pytest.mark.parametrize("reason", ["panic", "exit_rug"])
async def test_panic_paths_keep_the_configured_wide_bound(tmp_path: Path, reason: str) -> None:
    target = holding("target", 1_000)
    harness = make_harness(tmp_path, post_token_amounts={"target-account": 0})

    await harness.executor.sell(
        mint="target", name="TGT", reason=reason, observed_holding=target
    )

    assert harness.jupiter.order_calls[0]["slippage_bps"] == 1500
