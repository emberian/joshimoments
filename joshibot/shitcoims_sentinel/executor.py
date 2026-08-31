from __future__ import annotations

import asyncio
import base64
import csv
from dataclasses import dataclass
from typing import Any

import httpx
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from .clients import (
    SIMULATION_ADDRESS_LIMIT,
    WIDE_EXIT_REASONS,
    ExternalServiceError,
    JupiterClient,
    SolanaRpc,
    exit_slippage_bps,
)
from .config import AppConfig
from .domain import DecisionKind, PoolSnapshot, TokenHolding, utc_now
from .notifier import Notifier
from .reserves import reserve_minimum_out
from .secrets import read_secret_file
from .storage import StateStore
from .transaction import (
    LANDING_BID_FLOOR_MICRO_LAMPORTS,
    TransactionRejected,
    ValidatedTransaction,
    sign_validated_transaction,
    validate_jupiter_exit_transaction,
    validate_simulated_exit,
)

# A submitted signature is resolved to a terminal state before any retry. The
# window must be able to outlive blockhash expiry (150 slots, ~60s), because
# "the cluster has never heard of this signature" only becomes proof of death
# once the transaction can no longer be included in a block.
RESOLUTION_POLL_ATTEMPTS = 50
RESOLUTION_POLL_SECONDS = 2.0

# The safety simulation must cover every owned token account, and Helius accepts
# at most SIMULATION_ADDRESS_LIMIT of them per call, so a fat wallet is covered by
# several passes over the same signed transaction. The chunk cap only exists so a
# pathological wallet fails loudly instead of issuing unbounded RPC traffic.
SIMULATION_CHUNK_LIMIT = 24
SIMULATION_CONCURRENCY = 4

# Statuses whose stored signature may still land on chain.
UNRESOLVED_STATUSES = frozenset({"submitting", "submitted", "submitted_unconfirmed"})


class SimulationCoverageError(RuntimeError):
    """The wallet holds more token accounts than the safety simulation can cover."""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: str
    signature: str | None
    attempts: int
    message: str
    input_amount: int
    output_lamports: int | None = None


@dataclass(frozen=True, slots=True)
class SignatureResolution:
    """Terminal verdict on a submitted signature.

    ``confirmed`` — it landed and the balance moved.
    ``dead``      — it can never move the balance (on-chain error, or its
                    blockhash expired before inclusion). Only this permits a retry.
    ``unresolved``— still ambiguous. Never retry; a second order could over-sell.
    """

    state: str
    detail: str
    leftover: int | None = None


def describe_execution_failure(exc: BaseException) -> str:
    """Name the failure class without carrying a URL, key, or response payload.

    An operator has to be able to tell a security stop from a timeout. Helius puts
    its API key in the query string, so httpx exceptions are reduced to their type;
    our own error types build their messages from static text plus public data.
    """
    if isinstance(exc, TransactionRejected):
        return f"security stop ({type(exc).__name__}): {exc}"
    if isinstance(exc, SimulationCoverageError):
        return f"simulation coverage ({type(exc).__name__}): {exc}"
    if isinstance(exc, ExternalServiceError):
        return f"external service ({type(exc).__name__}): {exc}"
    if isinstance(exc, httpx.HTTPError):
        return f"transport failure ({type(exc).__name__}); request detail withheld"
    if isinstance(exc, TimeoutError):
        return f"timeout ({type(exc).__name__}) waiting for an execution response"
    return f"unexpected {type(exc).__name__}; detail withheld"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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

    # ------------------------------------------------------------------
    # Signature resolution. Nothing may be re-submitted until a prior
    # signature has been shown to be either landed or impossible to land.
    # ------------------------------------------------------------------

    async def _resolve_signature(
        self,
        *,
        signature: str,
        blockhash: str | None,
        mint: str,
        expected_remaining: int,
    ) -> SignatureResolution:
        detail = "signature never reached a terminal state"
        for poll in range(RESOLUTION_POLL_ATTEMPTS):
            if poll:
                await asyncio.sleep(RESOLUTION_POLL_SECONDS)
            status = await self.rpc.signature_status(signature)
            if status == "failed":
                return SignatureResolution("dead", "transaction landed with an on-chain error")
            if status == "confirmed":
                remaining = await self._holding(mint)
                leftover = 0 if remaining is None else remaining.amount
                if leftover <= expected_remaining:
                    return SignatureResolution("confirmed", "confirmed onchain", leftover)
                detail = "confirmed signature has not yet reduced the balance"
                continue
            detail = f"signature status is {status}"
            if status == "unknown" and blockhash:
                # Only blockhash expiry proves a never-seen transaction is dead.
                try:
                    still_valid = await self.rpc.blockhash_valid(blockhash)
                except ExternalServiceError:
                    still_valid = True
                if not still_valid:
                    return SignatureResolution(
                        "dead", "blockhash expired before the transaction landed"
                    )
        return SignatureResolution("unresolved", detail)

    async def _finalize_confirmed(
        self,
        *,
        mint: str,
        name: str,
        reason: DecisionKind | str,
        signature: str,
        sold_amount: int,
        output_lamports: int | None,
        attempt: int,
    ) -> ExecutionResult:
        if str(reason) == DecisionKind.EXIT_DISPOSE.value:
            # A dispose mark is a one-shot instruction. Persistently disable it
            # after confirmed completion so a later reacquisition cannot inherit
            # the old trigger.
            self.state.set_dispose_policy(mint, enabled=False)
        self.state.delete("pending_exits", mint)
        self._append_trade(
            {
                "timestamp": utc_now().isoformat(),
                "wallet": "shitcoims",
                "mint": mint,
                "name": name,
                "reason": str(reason),
                "input_amount": sold_amount,
                "output_lamports": output_lamports,
                "signature": signature,
            }
        )
        scaled = str(reason) == DecisionKind.EXIT_SCALE.value
        message = (
            f"SCALE CONFIRMED: {name} sold {sold_amount} from shitcoims"
            if scaled
            else f"EXIT CONFIRMED: {name} sold from shitcoims"
        )
        await self.notifier.send(
            severity="critical" if str(reason) == DecisionKind.EXIT_RUG.value else "warning",
            category="execution",
            message=message,
            context={
                "mint": mint,
                "signature": signature,
                "reason": str(reason),
                "amount": sold_amount,
            },
            dedup_seconds=0,
        )
        return ExecutionResult("success", signature, attempt, message, sold_amount, output_lamports)

    async def _block_on_unresolved(
        self,
        *,
        mint: str,
        name: str,
        reason: DecisionKind | str,
        intent: dict[str, Any],
        signature: str,
        detail: str,
        attempt: int,
        amount: int,
    ) -> ExecutionResult:
        intent.update(
            {"status": "submitted_unconfirmed", "signature": signature, "last_error": detail}
        )
        self.state.set("pending_exits", mint, value=intent)
        message = (
            f"EXIT UNRESOLVED: {name} on shitcoims has a submitted transaction that has not "
            "resolved; no replacement will be sent — MANUAL ACTION REQUIRED"
        )
        await self.notifier.send(
            severity="critical",
            category="execution",
            message=message,
            context={
                "mint": mint,
                "signature": signature,
                "reason": str(reason),
                "detail": detail,
            },
            # An unresolved exit is re-entered by `reconcile_pending_exits` every
            # cycle, so this is keyed per signature rather than fired every poll.
            dedup_key=f"exit-unresolved:{mint}:{signature}",
            dedup_seconds=300,
        )
        return ExecutionResult("unresolved", signature, attempt, message, amount)

    async def resolve_pending_exit(
        self, *, mint: str, name: str, reason: DecisionKind | str
    ) -> ExecutionResult | None:
        """Public entry point for settling a signature the engine found at startup.

        The engine must be able to resolve a signature left behind by a crash *before* it
        deletes the pending entry, or a fill that confirmed while the process was down never
        reaches `trades.csv` — realised money missing from the ledger, which is the class of
        hole that made a 7.47 SOL loss invisible in the first place.

        Exposed as a real method rather than reached for through `getattr` on the private one:
        an attribute probe silently degrades to "skip resolution" the moment the private name
        changes, and the degradation looks like normal operation.
        """
        return await self._resolve_prior_submission(mint=mint, name=name, reason=reason)

    async def _resolve_prior_submission(
        self, *, mint: str, name: str, reason: DecisionKind | str
    ) -> ExecutionResult | None:
        """Settle a signature left behind by an earlier call before selling again.

        Returns None only when the prior transaction provably cannot land.
        """
        prior = self.state.get("pending_exits", mint, default=None)
        if not isinstance(prior, dict):
            return None
        signature = prior.get("signature")
        if not signature or str(prior.get("status")) not in UNRESOLVED_STATUSES:
            return None
        signature = str(signature)
        prior_reason = str(prior.get("reason") or reason)
        prior_name = str(prior.get("name") or name)
        expected_remaining = _int_or_none(prior.get("expected_remaining"))
        sold_amount = _int_or_none(prior.get("sell_amount")) or 0
        blockhash = prior.get("recent_blockhash")
        if expected_remaining is None or expected_remaining < 0:
            # A malformed intent cannot be reasoned about, and it still carries a
            # signature. Fail closed rather than risk a second sale.
            return await self._block_on_unresolved(
                mint=mint,
                name=prior_name,
                reason=prior_reason,
                intent=dict(prior),
                signature=signature,
                detail="stored exit intent is malformed and cannot be resolved",
                attempt=0,
                amount=sold_amount,
            )
        resolution = await self._resolve_signature(
            signature=signature,
            blockhash=str(blockhash) if blockhash else None,
            mint=mint,
            expected_remaining=expected_remaining,
        )
        if resolution.state == "confirmed":
            return await self._finalize_confirmed(
                mint=mint,
                name=prior_name,
                reason=prior_reason,
                signature=signature,
                sold_amount=sold_amount,
                output_lamports=_int_or_none(prior.get("output_lamports")),
                attempt=0,
            )
        if resolution.state == "unresolved":
            return await self._block_on_unresolved(
                mint=mint,
                name=prior_name,
                reason=prior_reason,
                intent=dict(prior),
                signature=signature,
                detail=resolution.detail,
                attempt=0,
                amount=sold_amount,
            )
        return None

    # ------------------------------------------------------------------
    # Simulation coverage.
    # ------------------------------------------------------------------

    def _simulation_chunks(
        self, holdings: list[TokenHolding], target_mint: str
    ) -> list[list[TokenHolding]]:
        """Split the wallet so every chunk still proves the full invariant.

        Each chunk carries the wallet SOL account and the whole target holding, so
        each simulation independently proves "the target is disposed as intended and
        the output lands in our own SOL account". Together the chunks prove "no other
        owned token moved". A holding is never split across chunks: the validator
        sums a holding's accounts, so a partial view would compare against the wrong
        total.
        """
        target = [holding for holding in holdings if holding.mint == target_mint]
        others = [holding for holding in holdings if holding.mint != target_mint]
        if not target:
            raise SimulationCoverageError(
                f"target mint {target_mint} is not a current shitcoims holding"
            )
        fixed = 1 + sum(len(holding.token_accounts) for holding in target)
        if fixed > SIMULATION_ADDRESS_LIMIT:
            raise SimulationCoverageError(
                f"the target holds {fixed - 1} token accounts, so covering it plus the wallet "
                f"needs {fixed} simulation addresses and the ceiling is {SIMULATION_ADDRESS_LIMIT}"
            )
        budget = SIMULATION_ADDRESS_LIMIT - fixed
        chunks: list[list[TokenHolding]] = []
        current: list[TokenHolding] = []
        used = 0
        for holding in others:
            count = len(holding.token_accounts)
            if count > budget:
                raise SimulationCoverageError(
                    f"holding {holding.mint} spans {count} token accounts and only {budget} "
                    f"fit alongside the target under the {SIMULATION_ADDRESS_LIMIT}-address ceiling"
                )
            if used + count > budget:
                chunks.append([*target, *current])
                current = []
                used = 0
            current.append(holding)
            used += count
        if current or not chunks:
            chunks.append([*target, *current])
        if len(chunks) > SIMULATION_CHUNK_LIMIT:
            raise SimulationCoverageError(
                f"covering {len(holdings)} holdings needs {len(chunks)} simulation passes and the "
                f"cap is {SIMULATION_CHUNK_LIMIT} at {SIMULATION_ADDRESS_LIMIT} addresses each"
            )
        return chunks

    async def _simulate_exit(
        self,
        *,
        signed: str,
        holdings: list[TokenHolding],
        target_mint: str,
        pre_sol_lamports: int,
        minimum_output_lamports: int,
        expected_remaining: int,
    ) -> int | None:
        """Validate the signed exit against simulation. Returns compute units consumed.

        The consumption figure is the only measurement of how much compute this swap really
        needs. It was discarded before; it is returned now because the requested LIMIT is
        charged to every writable account against the block budget whether or not it is used,
        so a request far above consumption throttles the pool we are exiting and is paid for
        in fees on top.
        """

        chunks = self._simulation_chunks(holdings, target_mint)
        wallet = str(self.keypair.pubkey())
        address_sets = [
            [wallet, *[account for holding in chunk for account in holding.token_accounts]]
            for chunk in chunks
        ]
        semaphore = asyncio.Semaphore(SIMULATION_CONCURRENCY)

        async def simulate(addresses: list[str]) -> dict[str, Any]:
            async with semaphore:
                return await self.rpc.simulate_transaction_accounts(signed, addresses)

        simulations = await asyncio.gather(*(simulate(addresses) for addresses in address_sets))
        consumed: list[int] = []
        for chunk, simulation in zip(chunks, simulations, strict=True):
            validate_simulated_exit(
                simulation=simulation,
                holdings=chunk,
                target_mint=target_mint,
                pre_sol_lamports=pre_sol_lamports,
                minimum_output_lamports=minimum_output_lamports,
                max_sol_cost_lamports=self.config.execution.max_sol_cost_lamports,
                expected_remaining=expected_remaining,
            )
            units = simulation.get("units_consumed")
            if isinstance(units, int) and not isinstance(units, bool) and units > 0:
                consumed.append(units)
        return max(consumed) if consumed else None

    async def _reserve_floor_refusal(
        self,
        *,
        mint: str,
        name: str,
        reason: DecisionKind | str,
        pool: PoolSnapshot | None,
        holding: TokenHolding,
        amount: int,
        order: dict[str, Any],
    ) -> ExecutionResult | None:
        """Refuse an order that authorises paying away more than the pool itself would take.

        `jupiter.slippage_bps` is a TOLERANCE — a budget an adversary may spend in full, and
        at 1500 it is their unconstrained optimum. This is the other kind of bound: what the
        observed pool must pay by its own arithmetic, via the Lean-mirrored constant-product
        fill in `shitcoims_kernel`. The order's on-chain `otherAmountThreshold` is what
        actually constrains the fill, so that is what is compared.

        Two deliberate asymmetries:
        - It is ONE-SIDED. An order that pays MORE than the model is never questioned.
        - An emergency exit is never blocked. On a rug or a panic, not selling is the worse
          outcome by a wide margin, so those are reported and allowed through.

        Returns None when the sale should proceed, which includes every case where the pool
        cannot be modelled — see `reserves.py`. There is no fabricated floor.
        """

        floor = reserve_minimum_out(pool, holding, amount)
        if floor is None:
            return None
        try:
            authorised = int(order.get("otherAmountThreshold") or 0)
        except (TypeError, ValueError):
            return None
        if authorised >= floor:
            return None

        context = {
            "mint": mint,
            "amount": amount,
            "reason": str(reason),
            "authorised_minimum_out_lamports": authorised,
            "reserve_floor_lamports": floor,
            "dex_id": pool.dex_id if pool is not None else None,
            "auto_action": False,
        }
        if str(reason) in WIDE_EXIT_REASONS:
            await self.notifier.send(
                severity="critical",
                category="execution",
                message=(
                    f"EMERGENCY EXIT PRICED BELOW THE POOL for {name}: order authorises "
                    f"{authorised} lamports against a {floor} reserve floor. Selling anyway."
                ),
                context=context,
                dedup_key=f"reserve-floor-emergency:{mint}",
                dedup_seconds=0,
            )
            return None

        message = (
            f"SELL REFUSED: {name} order authorises {authorised} lamports, below the "
            f"{floor} floor computed from the observed pool reserves"
        )
        await self.notifier.send(
            severity="critical",
            category="execution",
            message=message,
            context=context,
            dedup_key=f"reserve-floor:{mint}",
            dedup_seconds=300,
        )
        self.state.delete("pending_exits", mint)
        return ExecutionResult("skipped", None, 0, message, 0)

    async def _record_landing_bid(
        self,
        *,
        mint: str,
        name: str,
        validated: ValidatedTransaction,
        units_consumed: int | None,
        signature: str,
    ) -> None:
        """Instrument the bid on every send, and alarm when it sits under the landing cliff.

        Measured, not assumed: Jupiter-routed transactions land 29.6% below 50,000
        microlamports/CU and 97.2% at or above it (studies/RESULT_execution_landing.md §4).
        We do not build this transaction, so the bid is Jupiter's choice; what we own is
        knowing what was bid and saying so out loud. Never blocks the sale -- an unsent exit
        on a rugging bag is the worse failure, and this is a sell-only system.
        """

        context = {
            "mint": mint,
            "signature": signature,
            "compute_unit_price_micro_lamports": validated.compute_unit_price_micro_lamports,
            "compute_unit_limit": validated.compute_unit_limit,
            "simulated_units_consumed": units_consumed,
            "priority_fee_lamports": validated.priority_fee_lamports,
            "landing_bid_floor_micro_lamports": LANDING_BID_FLOOR_MICRO_LAMPORTS,
            "auto_action": False,
        }
        if validated.bid_below_landing_floor:
            await self.notifier.send(
                severity="critical",
                category="execution",
                message=(
                    f"LOW LANDING BID on {name}: "
                    f"{validated.compute_unit_price_micro_lamports} microlamports/CU is below "
                    f"the measured {LANDING_BID_FLOOR_MICRO_LAMPORTS} cliff "
                    "(29.6% vs 97.2% landing). Submitting anyway."
                ),
                context=context,
                dedup_key=f"low-bid:{mint}",
                dedup_seconds=300,
            )
        elif validated.limit_is_oversized_against(units_consumed):
            await self.notifier.send(
                severity="warning",
                category="execution",
                message=(
                    f"OVERSIZED COMPUTE REQUEST on {name}: asked for "
                    f"{validated.compute_unit_limit} CU against {units_consumed} simulated. "
                    "The block cost tracker charges the request to every writable account, "
                    "so this throttles the pool we are exiting and is paid for in fee."
                ),
                context=context,
                dedup_key=f"oversized-cu:{mint}",
                dedup_seconds=3600,
            )
        else:
            await self.notifier.send(
                severity="info",
                category="execution",
                message=(
                    f"bid {validated.compute_unit_price_micro_lamports} microlamports/CU "
                    f"x {validated.compute_unit_limit} CU for {name}"
                ),
                context=context,
                dedup_key=f"bid:{mint}:{signature}",
                dedup_seconds=0,
            )

    # ------------------------------------------------------------------

    async def sell(
        self,
        *,
        mint: str,
        name: str,
        reason: DecisionKind | str,
        observed_holding: TokenHolding,
        amount: int | None = None,
        pool: PoolSnapshot | None = None,
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

        settled = await self._resolve_prior_submission(mint=mint, name=name, reason=reason)
        if settled is not None:
            return settled

        intent = {
            "created_at": utc_now().isoformat(),
            "wallet": "shitcoims",
            "mint": mint,
            "name": name,
            "reason": str(reason),
            "status": "intent",
            "last_observed_amount": observed_holding.amount,
            "sell_amount": requested,
            "expected_remaining": observed_holding.amount - requested,
        }
        self.state.set("pending_exits", mint, value=intent)
        last_error = "unknown execution failure"
        pending_signature: str | None = None
        pending_blockhash: str | None = None
        pending_expected_remaining = 0
        pending_amount = requested
        pending_output_lamports: int | None = None

        def clear_pending_signature(detail: str) -> None:
            nonlocal pending_signature, pending_blockhash, pending_output_lamports
            pending_signature = None
            pending_blockhash = None
            pending_output_lamports = None
            intent.pop("signature", None)
            intent.pop("recent_blockhash", None)
            intent.update({"status": "retrying", "last_error": detail})
            self.state.set("pending_exits", mint, value=intent)

        for attempt in range(1, self.config.execution.max_attempts + 1):
            try:
                if pending_signature is not None:
                    # A signature survived the previous attempt. Resolving it is the
                    # only thing that may happen until it reaches a terminal state.
                    resolution = await self._resolve_signature(
                        signature=pending_signature,
                        blockhash=pending_blockhash,
                        mint=mint,
                        expected_remaining=pending_expected_remaining,
                    )
                    if resolution.state == "confirmed":
                        return await self._finalize_confirmed(
                            mint=mint,
                            name=name,
                            reason=reason,
                            signature=pending_signature,
                            sold_amount=pending_amount,
                            output_lamports=pending_output_lamports,
                            attempt=attempt,
                        )
                    if resolution.state == "unresolved":
                        return await self._block_on_unresolved(
                            mint=mint,
                            name=name,
                            reason=reason,
                            intent=intent,
                            signature=pending_signature,
                            detail=f"{last_error}; {resolution.detail}",
                            attempt=attempt,
                            amount=pending_amount,
                        )
                    last_error = f"{last_error}; prior submission is dead ({resolution.detail})"
                    clear_pending_signature(last_error)

                current = await self._holding(mint)
                # Inlined rather than bound to a local: routing the `is None` test through a
                # boolean loses the narrowing, so every later `current.amount` becomes an
                # unchecked deref that only a human reading the whole block can rule out.
                if (
                    current is None
                    or current.amount == 0
                    or current.amount <= observed_holding.amount - requested
                ):
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
                    mint,
                    sell_now,
                    str(self.keypair.pubkey()),
                    slippage_bps=exit_slippage_bps(str(reason), self.config.jupiter),
                )
                refusal = await self._reserve_floor_refusal(
                    mint=mint,
                    name=name,
                    reason=reason,
                    pool=pool,
                    holding=current,
                    amount=sell_now,
                    order=order,
                )
                if refusal is not None:
                    return refusal
                validated = await validate_jupiter_exit_transaction(
                    encoded=str(order["transaction"]),
                    shitcoims_pubkey=self.keypair.pubkey(),
                    rpc=self.rpc,
                    max_priority_fee_lamports=self.config.jupiter.max_priority_fee_lamports,
                )
                signed = sign_validated_transaction(validated, self.keypair)
                # The signature is a property of what we signed, so it is known
                # before anything is broadcast. Persisting it here is what makes an
                # ambiguous /execute response resolvable instead of a coin flip.
                derived_signature = str(
                    VersionedTransaction.from_bytes(base64.b64decode(signed)).signatures[0]
                )
                recent_blockhash = str(validated.transaction.message.recent_blockhash)
                all_holdings = await self._holdings()
                pre_sol_lamports = await self.rpc.sol_balance(str(self.keypair.pubkey()))
                units_consumed = await self._simulate_exit(
                    signed=signed,
                    holdings=all_holdings,
                    target_mint=mint,
                    pre_sol_lamports=pre_sol_lamports,
                    minimum_output_lamports=int(order.get("otherAmountThreshold") or 0),
                    expected_remaining=expected_remaining,
                )
                await self._record_landing_bid(
                    mint=mint,
                    name=name,
                    validated=validated,
                    units_consumed=units_consumed,
                    signature=derived_signature,
                )
                pending_signature = derived_signature
                pending_blockhash = recent_blockhash
                pending_expected_remaining = expected_remaining
                pending_amount = sell_now
                pending_output_lamports = None
                intent.update(
                    {
                        "status": "submitting",
                        "attempt": attempt,
                        "request_id": str(order["requestId"]),
                        "last_observed_amount": current.amount,
                        "sell_amount": sell_now,
                        "expected_remaining": expected_remaining,
                        "signature": derived_signature,
                        "recent_blockhash": recent_blockhash,
                    }
                )
                self.state.set("pending_exits", mint, value=intent)
                result = await self.jupiter.execute(
                    signed_transaction=signed, request_id=str(order["requestId"])
                )
                if result.get("status") == "Success" and int(result.get("code", 0)) == 0:
                    reported = str(result.get("signature") or "")
                    if reported and reported != derived_signature:
                        raise TransactionRejected(
                            "Jupiter reported a signature that is not the transaction we signed"
                        )
                    pending_output_lamports = int(result.get("totalOutputAmount") or 0)
                    intent.update(
                        {"status": "submitted", "output_lamports": pending_output_lamports}
                    )
                    self.state.set("pending_exits", mint, value=intent)
                    resolution = await self._resolve_signature(
                        signature=derived_signature,
                        blockhash=recent_blockhash,
                        mint=mint,
                        expected_remaining=expected_remaining,
                    )
                    if resolution.state == "confirmed":
                        return await self._finalize_confirmed(
                            mint=mint,
                            name=name,
                            reason=reason,
                            signature=derived_signature,
                            sold_amount=sell_now,
                            output_lamports=pending_output_lamports,
                            attempt=attempt,
                        )
                    if resolution.state == "unresolved":
                        return await self._block_on_unresolved(
                            mint=mint,
                            name=name,
                            reason=reason,
                            intent=intent,
                            signature=derived_signature,
                            detail=resolution.detail,
                            attempt=attempt,
                            amount=sell_now,
                        )
                    last_error = f"submitted exit did not land ({resolution.detail})"
                    clear_pending_signature(last_error)
                else:
                    # Jupiter reported a failure, but the transaction we signed may
                    # still have gone out. The signature stays pending so the next
                    # attempt resolves it before building anything new.
                    last_error = f"Jupiter execute code {result.get('code', 'unknown')}"
            except Exception as exc:
                # Everything after signing may already have broadcast. The next
                # attempt starts by resolving `pending_signature` to a terminal
                # state and never builds a new order while one could still land.
                last_error = describe_execution_failure(exc)
            if attempt < self.config.execution.max_attempts:
                await asyncio.sleep(self.config.execution.retry_delay_seconds)

        if pending_signature is not None:
            return await self._block_on_unresolved(
                mint=mint,
                name=name,
                reason=reason,
                intent=intent,
                signature=pending_signature,
                detail=last_error,
                attempt=self.config.execution.max_attempts,
                amount=pending_amount,
            )
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
