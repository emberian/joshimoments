from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from typing import Any

from solders.keypair import Keypair

from .clients import JupiterClient, SolanaRpc
from .config import AppConfig
from .domain import DecisionKind, TokenHolding, utc_now
from .notifier import Notifier
from .secrets import read_secret_file
from .storage import StateStore
from .transaction import (
    sign_validated_transaction,
    validate_jupiter_exit_transaction,
    validate_simulated_exit,
)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: str
    signature: str | None
    attempts: int
    message: str
    input_amount: int
    output_lamports: int | None = None


class ExecutionGate:
    def __init__(self, config: AppConfig, keypair: Keypair, *, cli_live: bool):
        self.config = config
        self.keypair = keypair
        self.cli_live = cli_live

    @property
    def expected_arm_value(self) -> str:
        return f"shitcoims:{self.keypair.pubkey()}"

    def status(self, *, jupiter_ready: bool) -> tuple[bool, list[str]]:
        failures: list[str] = []
        if not self.config.execution.enabled:
            failures.append("execution.enabled is false")
        if not self.cli_live:
            failures.append("process was not started with --live")
        arm = read_secret_file(self.config.execution.arm_file, required=False)
        if arm != self.expected_arm_value:
            failures.append("shitcoims live arm file is absent or does not match this wallet")
        if not jupiter_ready:
            failures.append("Jupiter API key is unavailable")
        return not failures, failures


class SellExecutor:
    def __init__(
        self,
        *,
        config: AppConfig,
        keypair: Keypair,
        gate: ExecutionGate,
        rpc: SolanaRpc,
        jupiter: JupiterClient,
        state: StateStore,
        notifier: Notifier,
    ):
        self.config = config
        self.keypair = keypair
        self.gate = gate
        self.rpc = rpc
        self.jupiter = jupiter
        self.state = state
        self.notifier = notifier

    async def _holding(self, mint: str) -> TokenHolding | None:
        holdings = await self._holdings()
        return next((holding for holding in holdings if holding.mint == mint), None)

    async def _holdings(self) -> list[TokenHolding]:
        return await self.rpc.token_holdings(str(self.keypair.pubkey()))

    def _append_trade(self, row: dict[str, Any]) -> None:
        path = self.config.trades_file
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "timestamp",
            "wallet",
            "mint",
            "name",
            "reason",
            "input_amount",
            "output_lamports",
            "signature",
        ]
        exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            if not exists:
                writer.writeheader()
            writer.writerow({field: row.get(field) for field in fields})
            handle.flush()

    async def sell(
        self,
        *,
        mint: str,
        name: str,
        reason: DecisionKind | str,
        observed_holding: TokenHolding,
        amount: int | None = None,
    ) -> ExecutionResult:
        requested = observed_holding.amount if amount is None else int(amount)
        if requested <= 0 or requested > observed_holding.amount:
            message = f"SELL SKIPPED: {name} requested {requested} of {observed_holding.amount}"
            await self.notifier.send(
                severity="warning",
                category="execution",
                message=message,
                context={"mint": mint, "amount": requested, "reason": str(reason)},
                dedup_key=f"bad-amount:{mint}:{reason}",
            )
            return ExecutionResult("skipped", None, 0, message, 0)

        live, failures = self.gate.status(jupiter_ready=self.jupiter.ready)
        slice_label = "all" if requested == observed_holding.amount else f"{requested} raw"
        if not live:
            message = (
                f"DRY RUN: would sell {slice_label} {name} from shitcoims "
                f"({'; '.join(failures)})"
            )
            await self.notifier.send(
                severity="warning",
                category="execution",
                message=message,
                context={"mint": mint, "amount": requested, "reason": str(reason)},
                dedup_key=f"dry-exit:{mint}:{reason}:{requested}",
            )
            return ExecutionResult("dry_run", None, 0, message, requested)

        intent = {
            "created_at": utc_now().isoformat(),
            "wallet": "shitcoims",
            "mint": mint,
            "name": name,
            "reason": str(reason),
            "status": "intent",
            "last_observed_amount": observed_holding.amount,
            "sell_amount": requested,
        }
        self.state.set("pending_exits", mint, value=intent)
        last_error = "unknown execution failure"
        for attempt in range(1, self.config.execution.max_attempts + 1):
            try:
                current = await self._holding(mint)
                already_filled = (
                    current is None
                    or current.amount == 0
                    or current.amount <= observed_holding.amount - requested
                )
                if already_filled:
                    if str(reason) == DecisionKind.EXIT_DISPOSE.value:
                        self.state.set_dispose_policy(mint, enabled=False)
                    self.state.delete("pending_exits", mint)
                    leftover = 0 if current is None else current.amount
                    message = (
                        f"{name} pending exit already filled; remaining {leftover}"
                    )
                    await self.notifier.send(
                        severity="info",
                        category="execution",
                        message=message,
                        context={"mint": mint, "attempt": attempt},
                        dedup_seconds=0,
                    )
                    return ExecutionResult("reconciled", None, attempt - 1, message, leftover)

                sell_now = min(requested, current.amount)
                expected_remaining = current.amount - sell_now

                order = await self.jupiter.executable_order(
                    mint, sell_now, str(self.keypair.pubkey())
                )
                validated = await validate_jupiter_exit_transaction(
                    encoded=str(order["transaction"]),
                    shitcoims_pubkey=self.keypair.pubkey(),
                    rpc=self.rpc,
                    max_priority_fee_lamports=self.config.jupiter.max_priority_fee_lamports,
                )
                signed = sign_validated_transaction(validated, self.keypair)
                all_holdings = await self._holdings()
                simulation_addresses = [
                    str(self.keypair.pubkey()),
                    *[
                        account
                        for wallet_holding in all_holdings
                        for account in wallet_holding.token_accounts
                    ],
                ]
                pre_sol_lamports = await self.rpc.sol_balance(str(self.keypair.pubkey()))
                simulation = await self.rpc.simulate_transaction_accounts(
                    signed, simulation_addresses
                )
                validate_simulated_exit(
                    simulation=simulation,
                    holdings=all_holdings,
                    target_mint=mint,
                    pre_sol_lamports=pre_sol_lamports,
                    minimum_output_lamports=int(order.get("otherAmountThreshold") or 0),
                    max_sol_cost_lamports=self.config.execution.max_sol_cost_lamports,
                    expected_remaining=expected_remaining,
                )
                intent.update(
                    {
                        "status": "submitting",
                        "attempt": attempt,
                        "request_id": str(order["requestId"]),
                        "last_observed_amount": current.amount,
                    }
                )
                self.state.set("pending_exits", mint, value=intent)
                result = await self.jupiter.execute(
                    signed_transaction=signed, request_id=str(order["requestId"])
                )
                if result.get("status") == "Success" and int(result.get("code", 0)) == 0:
                    signature = str(result.get("signature") or "")
                    output_lamports = int(result.get("totalOutputAmount") or 0)
                    if not signature:
                        raise RuntimeError("Jupiter success omitted signature")
                    confirmed = False
                    remaining = None
                    for confirmation_attempt in range(6):
                        if confirmation_attempt:
                            await asyncio.sleep(2)
                        if not await self.rpc.signature_confirmed(signature):
                            continue
                        remaining = await self._holding(mint)
                        leftover = 0 if remaining is None else remaining.amount
                        if leftover <= expected_remaining:
                            confirmed = True
                            break
                    if not confirmed:
                        intent.update(
                            {
                                "status": "submitted_unconfirmed",
                                "signature": signature,
                                "last_observed_amount": (
                                    remaining.amount if remaining is not None else 0
                                ),
                            }
                        )
                        self.state.set("pending_exits", mint, value=intent)
                        raise RuntimeError("submitted exit was not confirmed onchain")
                    if str(reason) == DecisionKind.EXIT_DISPOSE.value:
                        # A dispose mark is a one-shot instruction. Persistently
                        # disable it after confirmed completion so a later
                        # reacquisition cannot inherit the old trigger.
                        self.state.set_dispose_policy(mint, enabled=False)
                    self.state.delete("pending_exits", mint)
                    self._append_trade(
                        {
                            "timestamp": utc_now().isoformat(),
                            "wallet": "shitcoims",
                            "mint": mint,
                            "name": name,
                            "reason": str(reason),
                            "input_amount": sell_now,
                            "output_lamports": output_lamports,
                            "signature": signature,
                        }
                    )
                    scaled = str(reason) == DecisionKind.EXIT_SCALE.value
                    message = (
                        f"SCALE CONFIRMED: {name} sold {sell_now} from shitcoims"
                        if scaled
                        else f"EXIT CONFIRMED: {name} sold from shitcoims"
                    )
                    await self.notifier.send(
                        severity="critical" if str(reason) == DecisionKind.EXIT_RUG else "warning",
                        category="execution",
                        message=message,
                        context={
                            "mint": mint,
                            "signature": signature,
                            "reason": str(reason),
                            "amount": sell_now,
                        },
                        dedup_seconds=0,
                    )
                    return ExecutionResult(
                        "success", signature, attempt, message, sell_now, output_lamports
                    )
                last_error = f"Jupiter execute code {result.get('code', 'unknown')}"
            except Exception as exc:
                # The next attempt begins by reconciling the on-chain balance, so an
                # ambiguous response cannot cause a duplicate full-balance exit.
                last_error = f"{type(exc).__name__}: execution response unavailable"
            if attempt < self.config.execution.max_attempts:
                await asyncio.sleep(self.config.execution.retry_delay_seconds)

        intent.update({"status": "failed", "last_error": last_error})
        self.state.set("pending_exits", mint, value=intent)
        message = f"EXIT FAILED: {name} on shitcoims — MANUAL ACTION REQUIRED"
        await self.notifier.send(
            severity="critical",
            category="execution",
            message=message,
            context={"mint": mint, "error": last_error},
            dedup_seconds=0,
        )
        return ExecutionResult(
            "failed",
            None,
            self.config.execution.max_attempts,
            message,
            observed_holding.amount,
        )
