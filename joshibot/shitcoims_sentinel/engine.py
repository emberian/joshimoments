from __future__ import annotations

import asyncio
import contextlib
import copy
import dataclasses
import logging
import time
from collections import deque
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx

from .clients import (
    DexScreenerClient,
    ExternalServiceError,
    JupiterClient,
    PumpMetadataClient,
    SolanaRpc,
)
from .config import AppConfig
from .domain import (
    DEFAULTS,
    LAMPORTS_PER_SOL,
    PUMP_MINT_AUTHORITY,
    DecisionKind,
    PositionPolicy,
    PositionState,
    RugSignal,
    TokenHolding,
    evaluate_position,
    to_jsonable,
    utc_now,
)
from .executor import ExecutionGate, ExecutionResult, SellExecutor
from .lots import (
    DEFAULT_NEW_BAG_PROTECT_DELAY_SECONDS,
    ORIGIN_DEFAULT,
    basis_applied,
    due_for_default,
    empty_runtime_state,
    mark_origin,
    note_seen,
    record_from_mapping,
    reopen_held,
    retire,
    skip_auto,
    sl_is_live,
    to_mapping,
)
from .notifier import Notifier
from .policies import (
    persist_positions,
    policies_for_unmonitored,
    policy_to_api_mapping,
    policy_without_basis,
)
from .rug_detector import RugDetector
from .secrets import load_shitcoims_keypair
from .storage import EventJournal, StateStore

log = logging.getLogger(__name__)

# Cost basis is a provenance type here: the only constructor walks this wallet's
# own confirmed transactions for the mint. There is deliberately no constructor
# that takes a quote. An exit quote is what the bag is worth *now*; stamping one
# as basis makes PnL start at 0% by construction, so every stop fires that far
# below wherever the coin had already fallen (2026-08-12: -7.47 SOL over 16
# fabricated-basis round trips at -29.1% mean, against +18.1% on 3 operator-typed).
OBSERVED_BASIS_MAX_SIGNATURES = 100
OBSERVED_BASIS_MAX_TRANSACTIONS = 40
# A transport failure clears up; a history that does not reach the lot start does
# not. Both fail closed, but they must not be retried at the same rate.
OBSERVED_BASIS_RETRY_SECONDS = 180.0
OBSERVED_BASIS_STRUCTURAL_RETRY_SECONDS = 3600.0
# `failed` is terminal: the operator already got MANUAL ACTION REQUIRED for it.
TERMINAL_INTENT_STATUSES = frozenset({"failed"})


@dataclasses.dataclass(frozen=True, slots=True)
class ObservedBasis:
    """Net SOL this wallet actually paid for the lot it currently holds."""

    mint: str
    lamports_spent: int
    base_units_acquired: int
    decimals: int
    signatures: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.lamports_spent <= 0 or self.base_units_acquired <= 0:
            raise ValueError("observed basis requires a positive SOL outflow and token inflow")
        if self.decimals < 0:
            raise ValueError("observed basis requires the mint decimals")
        if not self.signatures:
            raise ValueError("observed basis requires at least one acquiring signature")

    @property
    def ui_amount_acquired(self) -> Decimal:
        return Decimal(self.base_units_acquired) / (Decimal(10) ** self.decimals)

    @property
    def total_sol(self) -> Decimal:
        return Decimal(self.lamports_spent) / LAMPORTS_PER_SOL

    @property
    def unit_price_sol(self) -> Decimal:
        """Average SOL paid per UI token across the lot.

        A per-unit price, not a bag total: partial scale-outs shrink the bag but
        must not move the entry price the stop is measured against.
        """

        return self.total_sol / self.ui_amount_acquired


def _account_keys(transaction: dict[str, Any]) -> list[str]:
    inner = transaction.get("transaction")
    message = inner.get("message") if isinstance(inner, dict) else None
    keys = message.get("accountKeys") if isinstance(message, dict) else None
    if not isinstance(keys, list):
        return []
    return [str(key.get("pubkey")) if isinstance(key, dict) else str(key) for key in keys]


def _wallet_token_delta(
    transaction: dict[str, Any],
    *,
    owner: str,
    mint: str,
    token_accounts: tuple[str, ...],
) -> int:
    """Signed base-unit change of the wallet's balance in `mint` for this transaction."""

    meta = transaction.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    keys = _account_keys(transaction)
    owned = set(token_accounts)

    def side(entries: Any) -> int:
        total = 0
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or str(entry.get("mint")) != mint:
                continue
            index = entry.get("accountIndex")
            key = keys[index] if isinstance(index, int) and 0 <= index < len(keys) else None
            recorded_owner = entry.get("owner")
            if recorded_owner is not None:
                if str(recorded_owner) != owner:
                    continue
            elif key not in owned:
                continue
            amount = entry.get("uiTokenAmount")
            total += int((amount or {})["amount"])
        return total

    return side(meta.get("postTokenBalances")) - side(meta.get("preTokenBalances"))


def _wallet_lamport_outflow(transaction: dict[str, Any], *, owner: str) -> int | None:
    """Lamports that left the wallet, excluding the network/priority fee it paid.

    Returns None when the wallet is not an account of this transaction, i.e. the
    tokens arrived without this wallet paying for them.
    """

    meta = transaction.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    keys = _account_keys(transaction)
    if owner not in keys:
        return None
    index = keys.index(owner)
    pre = meta.get("preBalances")
    post = meta.get("postBalances")
    if not isinstance(pre, list) or not isinstance(post, list):
        return None
    if index >= len(pre) or index >= len(post):
        return None
    outflow = int(pre[index]) - int(post[index])
    if keys[0] == owner:
        # The wallet paid the fee; the fee is not part of what the tokens cost.
        outflow -= int(meta.get("fee") or 0)
    return outflow


async def _confirmed_signatures(
    rpc: Any, accounts: tuple[str, ...], *, commitment: str, limit: int
) -> list[tuple[int, str]]:
    """Successful signatures touching the wallet's token accounts, newest first."""

    slots: dict[str, int] = {}
    for account in accounts:
        result = await rpc.call(
            "getSignaturesForAddress",
            [account, {"limit": int(limit), "commitment": commitment}],
        )
        if not isinstance(result, list):
            raise ExternalServiceError("Helius returned malformed signature history")
        for entry in result:
            # A failed transaction moved no tokens. It only burned a fee.
            if not isinstance(entry, dict) or entry.get("err") is not None:
                continue
            signature = str(entry.get("signature") or "")
            slot = entry.get("slot")
            if signature and isinstance(slot, int):
                slots.setdefault(signature, slot)
    return sorted(((slot, signature) for signature, slot in slots.items()), reverse=True)


async def reconstruct_observed_basis(
    *,
    rpc: Any,
    owner: str,
    holding: TokenHolding,
    commitment: str = "confirmed",
    max_signatures: int = OBSERVED_BASIS_MAX_SIGNATURES,
    max_transactions: int = OBSERVED_BASIS_MAX_TRANSACTIONS,
) -> tuple[ObservedBasis | None, str]:
    """Read back what this wallet paid for the units it holds right now.

    Walks the mint's own token-account history newest first, rebuilding the
    balance backwards until the lot opens (balance 0), and sums the SOL paid by
    the acquisitions inside that lot. Everything before the lot opened belongs to
    a previous generation and is deliberately not counted.

    Returns ``(None, reason)`` whenever the answer cannot be established from
    chain data. A missing basis is a known-unknown: the caller must fall back to
    rug-only protection rather than invent a number.
    """

    if holding.amount <= 0:
        return None, "holding is empty"
    if not holding.token_accounts:
        return None, "wallet has no token account for this mint"
    signatures = await _confirmed_signatures(
        rpc, holding.token_accounts, commitment=commitment, limit=max_signatures
    )
    if not signatures:
        return None, "no confirmed transaction history for this token account"

    running = holding.amount
    acquired = 0
    lamports = 0
    used: list[str] = []
    window = signatures[: max(1, int(max_transactions))]
    for _slot, signature in window:
        transaction = await rpc.call(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "jsonParsed",
                    "commitment": commitment,
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )
        if not isinstance(transaction, dict):
            return None, f"transaction {signature[:8]} is unavailable"
        try:
            delta = _wallet_token_delta(
                transaction,
                owner=owner,
                mint=holding.mint,
                token_accounts=holding.token_accounts,
            )
            outflow = _wallet_lamport_outflow(transaction, owner=owner)
        except (KeyError, TypeError, ValueError):
            return None, f"transaction {signature[:8]} could not be parsed"
        opening = running - delta
        if opening < 0:
            return None, "token balance history is inconsistent with the current holding"
        if delta > 0:
            if outflow is None:
                return None, f"transaction {signature[:8]} does not debit this wallet"
            if outflow <= 0:
                return None, "tokens were acquired without a SOL payment (transfer or airdrop)"
            acquired += delta
            lamports += outflow
            used.append(signature)
        running = opening
        if opening == 0:
            break
    else:
        return None, f"lot start not reached within {len(window)} inspected transaction(s)"

    if acquired < holding.amount:
        return None, "observed buys do not cover the current holding"
    return (
        ObservedBasis(
            mint=holding.mint,
            lamports_spent=lamports,
            base_units_acquired=acquired,
            decimals=holding.decimals,
            signatures=tuple(used),
        ),
        f"{len(used)} observed buy(s)",
    )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _default_rule_text() -> str:
    """Describe the auto-protect rule from the rule itself, not from a remembered copy."""

    parts = [
        "no stop" if DEFAULTS.stop_loss_pct is None else f"SL {DEFAULTS.stop_loss_pct}%",
        (
            "no take profit"
            if DEFAULTS.take_profit_pct is None
            else f"arm +{DEFAULTS.take_profit_pct}%"
        ),
        "no runner" if DEFAULTS.runner_tightness is None else "runner",
        "rug exit on" if DEFAULTS.rug_exit else "rug exit OFF",
    ]
    return ", ".join(parts)


def _basis_needs_observation(lot: Any, policy: Any) -> bool:
    """Is this lot's PnL reference still missing an on-chain origin?

    ``needs_basis`` is the lot lifecycle declaring the previous lot's cash basis
    dead. The second clause is the migration: every basis the sentinel wrote for
    itself before this fix was a Jupiter exit quote stamped as ``cost_basis_sol``,
    so a default-origin policy is trusted only once it carries an observed
    ``buy_price_sol``. Operator-typed numbers are never overwritten.
    """

    if lot.needs_basis:
        return True
    return lot.origin == ORIGIN_DEFAULT and policy.buy_price_sol is None


class SentinelEngine:
    def __init__(self, config: AppConfig, *, cli_live: bool):
        self.config = config
        self.keypair = load_shitcoims_keypair(config.wallet.secret_key_file)
        self.wallet_address = str(self.keypair.pubkey())
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=5),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"user-agent": "shitcoims-sentinel/0.1"},
        )
        self.state = StateStore(config.state_file)
        self.journal = EventJournal(config.events_file)
        self.rpc = SolanaRpc(config.rpc, self.http)
        self.jupiter = JupiterClient(config.jupiter, self.http)
        self.dex = DexScreenerClient(self.http)
        self.pump = PumpMetadataClient(
            self.http,
            cache_seconds=config.experiments.pump_metadata_poll_interval_seconds,
        )
        self.notifier = Notifier(config.notifications, self.http, self.journal)
        self.rug_detector = RugDetector(config.rug, self.state)
        self._policy_lock = asyncio.Lock()
        self._basis_refills: list[Any] = []
        # mint -> (lot generation, monotonic retry-after, last failure reason).
        # A wallet whose basis cannot be read is retried, not hammered.
        self._basis_retry: dict[str, tuple[int, float, str]] = {}
        self.gate = ExecutionGate(config, self.keypair, cli_live=cli_live)
        self.executor = SellExecutor(
            config=config,
            keypair=self.keypair,
            gate=self.gate,
            rpc=self.rpc,
            jupiter=self.jupiter,
            state=self.state,
            notifier=self.notifier,
        )
        self.running = False
        self.last_cycle_at = None
        self.last_cycle_error: str | None = None
        self._snapshot_lock = asyncio.Lock()
        self._known_unmonitored: set[str] = set()
        self._unmonitored_cache: dict[str, dict[str, Any]] = {}
        self._next_observe_sweep = 0.0
        self._cycle_wakeup = asyncio.Event()
        self._wallet_activity: deque[dict[str, Any]] = deque(maxlen=30)
        self._wallet_stream_health = "disabled"
        self._wallet_stream_last_sample_at: str | None = None
        self._wallet_stream_last_error_type: str | None = None
        self._advisory_activity: dict[str, deque[dict[str, Any]]] = {
            wallet.id: deque(maxlen=30) for wallet in config.experiments.advisory_wallets
        }
        self._advisory_health: dict[str, dict[str, Any]] = {
            wallet.id: {
                "health": "connecting",
                "last_sample_at": None,
                "last_error_type": None,
            }
            for wallet in config.experiments.advisory_wallets
        }
        self._telegram_probe_attempted = False
        self._enrichment_semaphore = asyncio.Semaphore(
            config.experiments.max_enrichment_concurrency
        )
        self._snapshot = self._empty_snapshot()

    def _empty_snapshot(self) -> dict[str, Any]:
        live, gate_failures = self.gate.status(jupiter_ready=self.jupiter.ready)
        return {
            "schema_version": 2,
            "generated_at": utc_now().isoformat(),
            "system": {
                "wallet_name": "shitcoims",
                "wallet_address": self.wallet_address,
                "mode": "live" if live else "dry-run",
                "protection_state": "STARTING",
                "running": False,
                "rpc_ready": False,
                "jupiter_ready": self.jupiter.ready,
                "telegram_ready": self.notifier.telegram_ready,
                "telegram_configured": self.notifier.telegram_configured,
                "gate_failures": gate_failures,
                "poll_interval_seconds": self.config.poll_interval_seconds,
                "last_cycle_at": None,
                "last_cycle_error": None,
                "unprotected_count": 0,
            },
            "wallet": {"sol_lamports": None, "sol": None, "portfolio_exit_sol": None},
            "positions": [],
            "unmonitored": [],
            "readiness": {"overall": "blocked", "capabilities": []},
            "freshness": [],
            "experiments": self._experiment_rows(),
            "signals": [],
            "events": [],
        }

    async def snapshot(self) -> dict[str, Any]:
        async with self._snapshot_lock:
            value = copy.deepcopy(self._snapshot)
        value["events"] = self.journal.recent()
        return value

    async def _set_snapshot(self, value: dict[str, Any]) -> None:
        async with self._snapshot_lock:
            self._snapshot = value

    def _experiment_rows(self) -> list[dict[str, Any]]:
        pump = self.pump.status()
        rows = [
            {
                "id": "helius_wallet_activity",
                "label": "shitcoims activity stream",
                "mode": (
                    "ingest_only"
                    if self.config.experiments.wallet_activity_stream
                    else "disabled"
                ),
                "health": self._wallet_stream_health,
                "last_sample_at": self._wallet_stream_last_sample_at,
                "last_error_type": self._wallet_stream_last_error_type,
                "signals_seen": len(self._wallet_activity),
                "can_execute": False,
                "note": "confirmed wallet wakeups; no gap recovery yet",
            },
            {
                "id": "pump_metadata",
                "label": "Pump.fun token context",
                "mode": "ingest_only" if self.config.experiments.pump_metadata else "disabled",
                "health": pump["health"] if self.config.experiments.pump_metadata else "disabled",
                "last_sample_at": pump["last_sample_at"],
                "last_error_type": pump["last_error_type"],
                "signals_seen": pump["successes"],
                "success_rate": pump["success_rate"],
                "can_execute": False,
                "note": "official metadata, cached; never a safety oracle",
            },
            {
                "id": "pump_callouts",
                "label": "Pump.fun callouts",
                "mode": "disabled",
                "health": "unknown",
                "last_sample_at": None,
                "last_error_type": None,
                "signals_seen": 0,
                "can_execute": False,
                "note": "sign-in feed; no supported public API contract",
            },
        ]
        for wallet in self.config.experiments.advisory_wallets:
            health = self._advisory_health[wallet.id]
            rows.append(
                {
                    "id": f"advisory_wallet_{wallet.id}",
                    "label": wallet.label,
                    "mode": "ingest_only",
                    "health": health["health"],
                    "last_sample_at": health["last_sample_at"],
                    "last_error_type": health["last_error_type"],
                    "signals_seen": len(self._advisory_activity[wallet.id]),
                    "can_execute": False,
                    "note": "canonical wallet receipts only; labels and narrative are untrusted",
                }
            )
        return rows

    def _signal_rows(
        self, positions: list[dict[str, Any]], unmonitored: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        for row in [*positions, *unmonitored]:
            metadata = row.get("pump_metadata")
            if not metadata:
                continue
            complete = metadata.get("complete")
            phase = "graduated / complete" if complete else "bonding curve active"
            received_at = metadata.get("received_at") or utc_now().isoformat()
            signals.append(
                {
                    "id": f"pump-context:{row['mint']}",
                    "mint": row["mint"],
                    "token_name": metadata.get("name") or row.get("name"),
                    "kind": "pump_token_context",
                    "severity": "info",
                    "status": "active",
                    "summary": f"Pump.fun recognizes this mint; {phase}.",
                    "source_ids": ["pump_metadata"],
                    "corroboration_count": 0,
                    "first_seen_at": received_at,
                    "last_seen_at": received_at,
                    "expires_at": None,
                    "policy_effect": "observe",
                    "provenance": [
                        {
                            "source_id": "pump_metadata",
                            "observed_at": metadata.get("last_trade_at") or received_at,
                            "received_at": received_at,
                            "adapter_version": "pump-metadata-v1",
                            "endpoint_family": "frontend-api-v3/coins-v2",
                            "evidence": {
                                "creator": metadata.get("creator"),
                                "complete": complete,
                                "quote_mint": metadata.get("quote_mint"),
                                "token_program": metadata.get("token_program"),
                            },
                        }
                    ],
                }
            )
        for event in reversed(self._wallet_activity):
            kind = "pump_wallet_activity" if (
                event.get("pump_program") or event.get("pump_amm_program")
            ) else "wallet_activity"
            signals.append(
                {
                    "id": f"wallet-activity:{event['signature']}",
                    "mint": None,
                    "token_name": None,
                    "kind": kind,
                    "severity": "info",
                    "status": "active",
                    "summary": (
                        "Confirmed Pump transaction touched shitcoims."
                        if kind == "pump_wallet_activity"
                        else "Confirmed transaction touched shitcoims."
                    ),
                    "source_ids": ["helius_wallet_activity"],
                    "corroboration_count": 0,
                    "first_seen_at": event["received_at"],
                    "last_seen_at": event["received_at"],
                    "expires_at": None,
                    "policy_effect": "observe",
                    "signature": event["signature"],
                    "slot": event["slot"],
                    "provenance": [
                        {
                            "source_id": "helius_wallet_activity",
                            "observed_at": event["received_at"],
                            "received_at": event["received_at"],
                            "adapter_version": "wallet-logs-v1",
                            "endpoint_family": "logsSubscribe",
                            "evidence": {
                                "slot": event["slot"],
                                "pump_program": event.get("pump_program", False),
                                "pump_amm_program": event.get("pump_amm_program", False),
                            },
                        }
                    ],
                }
            )
        for wallet in self.config.experiments.advisory_wallets:
            for event in reversed(self._advisory_activity[wallet.id]):
                signals.append(
                    {
                        "id": f"{wallet.id}:{event['signature']}",
                        "mint": None,
                        "token_name": wallet.label,
                        "kind": (
                            "pump_advisory_wallet_activity"
                            if event.get("pump_program") or event.get("pump_amm_program")
                            else "advisory_wallet_activity"
                        ),
                        "severity": "info",
                        "status": "active",
                        "summary": (
                            f"Confirmed Pump transaction touched {wallet.label}."
                            " Asset identity is intentionally not inferred from its narrative."
                        ),
                        "source_ids": [f"advisory_wallet_{wallet.id}"],
                        "corroboration_count": 0,
                        "first_seen_at": event["received_at"],
                        "last_seen_at": event["received_at"],
                        "expires_at": None,
                        "policy_effect": "observe",
                        "signature": event["signature"],
                        "slot": event["slot"],
                        "provenance": [
                            {
                                "source_id": f"advisory_wallet_{wallet.id}",
                                "observed_at": event["received_at"],
                                "received_at": event["received_at"],
                                "adapter_version": "public-wallet-logs-v1",
                                "endpoint_family": "logsSubscribe",
                                "evidence": {
                                    "wallet": wallet.address,
                                    "slot": event["slot"],
                                    "pump_program": event.get("pump_program", False),
                                    "pump_amm_program": event.get("pump_amm_program", False),
                                },
                            }
                        ],
                    }
                )
        return signals[:50]

    def _operational_sections(
        self,
        *,
        positions: list[dict[str, Any]],
        unmonitored: list[dict[str, Any]],
        live: bool,
        configured_errors: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        now = utc_now().isoformat()
        all_rows = [*positions, *unmonitored]
        latest_quote = max(
            (row["quote_received_at"] for row in all_rows if row.get("quote_received_at")),
            default=None,
        )
        latest_pool = max(
            (
                row["pool"]["observed_at"]
                for row in all_rows
                if row.get("pool") and row["pool"].get("observed_at")
            ),
            default=None,
        )
        if unmonitored:
            evaluate_state = "degraded"
            evaluate_reason = (
                f"{len(unmonitored)} unprotected bag"
                f"{'' if len(unmonitored) == 1 else 's'} will not auto-exit"
            )
            if configured_errors:
                evaluate_reason += "; one or more required checks failed"
        elif not positions:
            evaluate_state = "disabled"
            evaluate_reason = "no configured positions"
        elif configured_errors:
            evaluate_state = "degraded"
            evaluate_reason = "one or more required checks failed"
        else:
            evaluate_state = "ready"
            evaluate_reason = None
        capabilities = [
            {
                "id": "observe_wallet",
                "label": "Observe shitcoims holdings",
                "state": "ready",
                "reason": None,
                "checked_at": now,
                "required_for": ["observe", "shadow", "live"],
            },
            {
                "id": "quote_full_exits",
                "label": "Quote constrained full exits",
                "state": "ready" if self.jupiter.ready else "blocked",
                "reason": None if self.jupiter.ready else "Jupiter credential unavailable",
                "checked_at": latest_quote,
                "required_for": ["shadow", "live"],
            },
            {
                "id": "evaluate_policy",
                "label": "Evaluate explicit local policy",
                "state": evaluate_state,
                "reason": evaluate_reason,
                "checked_at": now,
                "required_for": ["shadow", "live"],
            },
            {
                "id": "deliver_alerts",
                "label": "Deliver loud Telegram alerts",
                "state": "ready" if self.notifier.telegram_ready else (
                    "blocked" if self.notifier.telegram_configured else "disabled"
                ),
                "reason": (
                    None
                    if self.notifier.telegram_ready
                    else (
                        "configured but verification failed"
                        if self.notifier.telegram_configured
                        else "chat is not paired"
                    )
                ),
                "checked_at": now if self._telegram_probe_attempted else None,
                "required_for": ["live"],
            },
            {
                "id": "submit_sell",
                "label": "Sign and submit sell-only exits",
                "state": "ready" if live else "blocked",
                "reason": None if live else "local live gates are not all satisfied",
                "checked_at": now,
                "required_for": ["live"],
            },
        ]
        overall = "ready" if live else ("degraded" if configured_errors else "blocked")
        freshness = [
            {
                "id": "wallet_rpc",
                "label": "Wallet / RPC",
                "status": "fresh",
                "observed_at": now,
                "received_at": now,
                "ttl_seconds": max(30, int(self.config.poll_interval_seconds * 3)),
                "last_error": None,
            },
            {
                "id": "jupiter_quotes",
                "label": "Jupiter exit routes",
                "status": "fresh" if latest_quote else ("never" if self.jupiter.ready else "disabled"),
                "observed_at": latest_quote,
                "received_at": latest_quote,
                "ttl_seconds": max(30, int(self.config.poll_interval_seconds * 3)),
                "last_error": None,
            },
            {
                "id": "pool_liquidity",
                "label": "Pool liquidity",
                "status": "fresh" if latest_pool else "never",
                "observed_at": latest_pool,
                "received_at": latest_pool,
                "ttl_seconds": max(90, int(self.config.rug.poll_interval_seconds * 3)),
                "last_error": None,
            },
            {
                "id": "wallet_stream",
                "label": "Wallet activity stream",
                "status": (
                    "fresh"
                    if self._wallet_stream_health == "healthy"
                    else self._wallet_stream_health
                ),
                "observed_at": self._wallet_stream_last_sample_at,
                "received_at": self._wallet_stream_last_sample_at,
                "ttl_seconds": 120,
                "last_error": self._wallet_stream_last_error_type,
            },
            {
                "id": "pump_metadata",
                "label": "Pump.fun metadata",
                "status": (
                    "fresh"
                    if self.pump.health == "healthy"
                    else self.pump.health
                ),
                "observed_at": self.pump.last_sample_at,
                "received_at": self.pump.last_sample_at,
                "ttl_seconds": int(
                    self.config.experiments.pump_metadata_poll_interval_seconds * 3
                ),
                "last_error": self.pump.last_error_type,
            },
        ]
        return {"overall": overall, "capabilities": capabilities}, freshness

    async def _wallet_stream_loop(self) -> None:
        if not self.config.experiments.wallet_activity_stream:
            self._wallet_stream_health = "disabled"
            return
        backoff = 1.0
        while self.running:
            try:
                self._wallet_stream_health = "connecting"
                async for notice in self.rpc.wallet_activity_stream(self.wallet_address):
                    self._wallet_stream_health = "healthy"
                    self._wallet_stream_last_error_type = None
                    if notice.get("type") == "ready":
                        self._wallet_stream_last_sample_at = notice["received_at"]
                        backoff = 1.0
                        continue
                    self._wallet_stream_last_sample_at = notice["received_at"]
                    backoff = 1.0
                    if notice["failed"]:
                        continue
                    if any(
                        event.get("signature") == notice["signature"]
                        for event in self._wallet_activity
                    ):
                        continue
                    self._wallet_activity.append(notice)
                    self.state.set("wallet_stream_cursor", value={
                        "signature": notice["signature"],
                        "slot": notice["slot"],
                        "received_at": notice["received_at"],
                    })
                    await self.notifier.send(
                        severity="info",
                        category="wallet_activity",
                        message=(
                            "Confirmed Pump activity touched shitcoims"
                            if notice.get("pump_program") or notice.get("pump_amm_program")
                            else "Confirmed activity touched shitcoims"
                        ),
                        context={
                            "signature": notice["signature"],
                            "slot": notice["slot"],
                            "pump": bool(
                                notice.get("pump_program") or notice.get("pump_amm_program")
                            ),
                            "auto_action": False,
                        },
                        dedup_key=f"wallet-activity:{notice['signature']}",
                        dedup_seconds=0,
                    )
                    self._cycle_wakeup.set()
                raise ExternalServiceError("wallet activity stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._wallet_stream_health = "degraded"
                self._wallet_stream_last_error_type = type(exc).__name__
                await self.notifier.send(
                    severity="warning",
                    category="wallet_activity",
                    message="shitcoims activity stream disconnected; polling remains active",
                    context={"error_type": type(exc).__name__, "auto_action": False},
                    dedup_key="wallet-stream-disconnected",
                    dedup_seconds=300,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _advisory_wallet_stream_loop(self, wallet: Any) -> None:
        backoff = 1.0
        health = self._advisory_health[wallet.id]
        activity = self._advisory_activity[wallet.id]
        while self.running:
            try:
                health["health"] = "connecting"
                async for notice in self.rpc.wallet_activity_stream(wallet.address):
                    health["health"] = "healthy"
                    health["last_error_type"] = None
                    if notice.get("type") == "ready":
                        health["last_sample_at"] = notice["received_at"]
                        backoff = 1.0
                        continue
                    health["last_sample_at"] = notice["received_at"]
                    if notice["failed"] or any(
                        event.get("signature") == notice["signature"] for event in activity
                    ):
                        continue
                    activity.append(notice)
                    await self.notifier.send(
                        severity="info",
                        category="advisory_wallet",
                        message=f"Confirmed activity touched {wallet.label}",
                        context={
                            "source_id": wallet.id,
                            "signature": notice["signature"],
                            "slot": notice["slot"],
                            "auto_action": False,
                        },
                        dedup_key=f"advisory:{wallet.id}:{notice['signature']}",
                        dedup_seconds=0,
                    )
                    self._cycle_wakeup.set()
                raise ExternalServiceError("advisory wallet stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                health["health"] = "degraded"
                health["last_error_type"] = type(exc).__name__
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _lot(self, mint: str):
        return record_from_mapping(mint, self.state.get("lots", mint, default={}))

    def _write_lot(self, record) -> None:
        self.state.set("lots", record.mint, value=to_mapping(record))

    def _clear_runtime_lot(self, mint: str) -> None:
        self._persist_position_state(mint, empty_runtime_state())

    def _retire_absent_lot(self, mint: str) -> str | None:
        """Wipe trail state. Default YAML is lifted; operator YAML loses its basis."""

        before = self._lot(mint)
        self._write_lot(retire(before))
        self._clear_runtime_lot(mint)
        if before.origin == ORIGIN_DEFAULT:
            return "drop"
        return "strip"

    def mark_policy_origin(self, mints: list[str], origin: str) -> None:
        for mint in mints:
            self._write_lot(mark_origin(self._lot(mint), origin))

    def skip_auto_protect(self, mint: str) -> None:
        self._write_lot(skip_auto(self._lot(mint)))

    def _position_state(self, mint: str) -> PositionState:
        raw = self.state.get("positions", mint, default={})
        peak = raw.get("trailing_peak_unit_price_sol")
        last_pnl = raw.get("last_pnl_pct")
        trigger_slot = raw.get("dispose_trigger_slot")
        fired = raw.get("scale_rungs_fired") or ()
        if isinstance(fired, str):
            fired = (fired,)
        floor = raw.get("runner_floor_multiple")
        original = raw.get("original_amount")
        streak = raw.get("below_floor_streak", 0)
        stop_streak = raw.get("below_stop_streak", 0)
        try:
            streak_int = int(streak)
        except (TypeError, ValueError):
            streak_int = 0
        try:
            stop_streak_int = int(stop_streak)
        except (TypeError, ValueError):
            stop_streak_int = 0
        try:
            original_int = int(original) if original is not None else None
        except (TypeError, ValueError):
            original_int = None
        return PositionState(
            trailing_active=bool(raw.get("trailing_active", False)),
            trailing_peak_unit_price_sol=(Decimal(str(peak)) if peak is not None else None),
            last_pnl_pct=(Decimal(str(last_pnl)) if last_pnl is not None else None),
            dispose_trigger_slot=(int(trigger_slot) if trigger_slot is not None else None),
            below_floor_streak=max(streak_int, 0),
            below_stop_streak=max(stop_streak_int, 0),
            scale_rungs_fired=tuple(str(item) for item in fired if str(item)),
            original_amount=original_int if original_int is not None and original_int > 0 else None,
            runner_floor_multiple=(Decimal(str(floor)) if floor is not None else None),
        )

    def _dispose_enabled(self, mint: str, policy: Any) -> bool:
        override = self.state.get("dispose_policies", mint, default=None)
        if isinstance(override, dict) and isinstance(override.get("enabled"), bool):
            return bool(override["enabled"])
        return bool(policy.dispose_after_break_even)

    def _persist_position_state(self, mint: str, state: PositionState) -> None:
        self.state.set(
            "positions",
            mint,
            value={
                "trailing_active": state.trailing_active,
                "trailing_peak_unit_price_sol": (
                    str(state.trailing_peak_unit_price_sol)
                    if state.trailing_peak_unit_price_sol is not None
                    else None
                ),
                "last_pnl_pct": (
                    str(state.last_pnl_pct) if state.last_pnl_pct is not None else None
                ),
                "dispose_trigger_slot": state.dispose_trigger_slot,
                "below_floor_streak": state.below_floor_streak,
                "below_stop_streak": state.below_stop_streak,
                "scale_rungs_fired": list(state.scale_rungs_fired),
                "original_amount": state.original_amount,
                "runner_floor_multiple": (
                    str(state.runner_floor_multiple)
                    if state.runner_floor_multiple is not None
                    else None
                ),
            },
        )

    async def _pool_for(self, mint: str):
        pinned = self.rug_detector.pinned_pair(mint)
        if pinned:
            return await self.dex.pool(mint, pinned)
        return await self.dex.discover_primary_pool(mint)

    async def _pump_metadata_for(self, mint: str) -> tuple[Any | None, str | None]:
        if not self.config.experiments.pump_metadata:
            return None, None
        try:
            return await self.pump.token(mint), None
        except ExternalServiceError as exc:
            return None, type(exc).__name__

    async def _observed_basis(
        self, holding: TokenHolding, lot: Any
    ) -> tuple[ObservedBasis | None, str]:
        """Chain-derived basis for this lot, with a cooldown between failed reads.

        The cooldown is keyed to the lot generation: a rebuy is a new lot and gets
        an immediate fresh attempt instead of inheriting the old one's backoff.
        """

        now = time.monotonic()
        cached = self._basis_retry.get(holding.mint)
        if cached is not None and cached[0] == lot.generation and now < cached[1]:
            return None, cached[2]
        cooldown = OBSERVED_BASIS_STRUCTURAL_RETRY_SECONDS
        try:
            basis, reason = await reconstruct_observed_basis(
                rpc=self.rpc,
                owner=self.wallet_address,
                holding=holding,
                commitment=self.config.rpc.commitment,
            )
        except ExternalServiceError as exc:
            basis, reason = None, f"chain history unavailable ({type(exc).__name__})"
            cooldown = OBSERVED_BASIS_RETRY_SECONDS
        if basis is None:
            self._basis_retry[holding.mint] = (lot.generation, now + cooldown, reason)
        else:
            self._basis_retry.pop(holding.mint, None)
        return basis, reason

    @staticmethod
    def _safety_json(safety: Any | None) -> dict[str, Any] | None:
        if safety is None:
            return None
        value = to_jsonable(safety)
        value["mint_authority_class"] = (
            "revoked"
            if safety.mint_authority is None
            else (
                "pump_managed"
                if safety.mint_authority == PUMP_MINT_AUTHORITY
                else "active_unknown"
            )
        )
        return value

    async def _inspect_position(
        self,
        holding: TokenHolding,
        policy: Any,
        confirmed_slot: int | None,
    ) -> tuple[dict[str, Any], ExecutionResult | None]:
        lot = self._lot(holding.mint)
        if lot.is_flat:
            lot = reopen_held(lot)
            self._write_lot(lot)
        quote = None
        pool = None
        safety = None
        errors: list[str] = []
        if policy.cost_basis_sol is None and policy.buy_price_sol is None:
            basis_source = "unset"
        elif lot.origin == ORIGIN_DEFAULT:
            # The only basis the sentinel writes for itself now is an observed one.
            basis_source = "observed"
        else:
            basis_source = "operator"

        if _basis_needs_observation(lot, policy):
            # Whatever number the YAML carries for this lot is not evidence.
            # Drop it first so no branch below can fall back onto it.
            policy = policy_without_basis(policy)
            basis, basis_reason = await self._observed_basis(holding, lot)
            if basis is None:
                basis_source = "unavailable"
                errors.append(f"cost basis unavailable: {basis_reason}")
                await self.notifier.send(
                    severity="warning",
                    category="policy",
                    message=(
                        f"NO OBSERVED COST BASIS for {policy.name}: {basis_reason}. "
                        "Rug protection only — no stop, take-profit or trail on this bag."
                    ),
                    context={
                        "mint": holding.mint,
                        "generation": lot.generation,
                        "auto_action": False,
                    },
                    dedup_key=f"no-observed-basis:{holding.mint}:{lot.generation}",
                    dedup_seconds=3600,
                )
            else:
                basis_source = "observed"
                policy = dataclasses.replace(
                    policy, buy_price_sol=basis.unit_price_sol, cost_basis_sol=None
                )
                self._basis_refills.append(policy)
                lot = basis_applied(lot)
                self._write_lot(lot)
                await self.notifier.send(
                    severity="info",
                    category="policy",
                    message=(
                        f"COST BASIS OBSERVED {policy.name}: paid {basis.total_sol:.6f} SOL "
                        f"for {basis.ui_amount_acquired:.4f} tokens across "
                        f"{len(basis.signatures)} on-chain buy(s)"
                    ),
                    context={
                        "mint": holding.mint,
                        "generation": lot.generation,
                        "lamports_spent": basis.lamports_spent,
                        "base_units_acquired": basis.base_units_acquired,
                        "unit_price_sol": str(basis.unit_price_sol),
                        "signatures": list(basis.signatures),
                        "auto_action": False,
                    },
                    dedup_key=f"observed-basis:{holding.mint}:{lot.generation}",
                    dedup_seconds=0,
                )

        if self.jupiter.ready:
            try:
                quote = await self.jupiter.quote_exit(holding.mint, holding.amount)
            except ExternalServiceError as exc:
                errors.append(str(exc))
                await self.notifier.send(
                    severity="critical",
                    category="quote",
                    message=f"EXIT DOOR UNAVAILABLE for {policy.name}: {exc}",
                    context={"mint": holding.mint},
                    dedup_key=f"quote:{holding.mint}",
                )
        else:
            errors.append("Jupiter API key missing")

        pool_result, safety_result, metadata_result = await asyncio.gather(
            self._pool_for(holding.mint),
            self.rpc.mint_safety(holding.mint),
            self._pump_metadata_for(holding.mint),
            return_exceptions=True,
        )
        if isinstance(pool_result, Exception):
            errors.append(f"pool check failed ({type(pool_result).__name__})")
        else:
            pool = pool_result
        if isinstance(safety_result, Exception):
            errors.append(f"mint check failed ({type(safety_result).__name__})")
        else:
            safety = safety_result
        metadata = None
        advisory_errors: list[str] = []
        if isinstance(metadata_result, Exception):
            advisory_errors.append(
                f"Pump metadata failed ({type(metadata_result).__name__})"
            )
        else:
            metadata, metadata_error = metadata_result
            if metadata_error:
                advisory_errors.append(f"Pump metadata failed ({metadata_error})")

        rug = self.rug_detector.assess(
            holding=holding, pool=pool, mint_safety=safety, quote=quote
        )
        record_pool = pool
        if rug.emergency and rug.needs_confirmation:
            await asyncio.sleep(self.config.rug.confirm_delay_seconds)
            try:
                confirmation_pool = await self._pool_for(holding.mint)
                confirmed = self.rug_detector.assess(
                    holding=holding,
                    pool=confirmation_pool,
                    mint_safety=safety,
                    quote=quote,
                )
                if confirmed.emergency:
                    rug = confirmed
                    pool = confirmation_pool
                else:
                    rug = RugSignal(False, "transient liquidity sample rejected")
                    record_pool = None
            except ExternalServiceError:
                # A second independent request that fails is not confirmation.
                rug = RugSignal(False, "liquidity signal could not be confirmed")
                record_pool = None

        prior_state = self._position_state(holding.mint)
        dispose_enabled = self._dispose_enabled(holding.mint, policy)
        if dispose_enabled and confirmed_slot is None:
            errors.append("dispose check blocked: confirmed slot unavailable")
        pump_complete = metadata.complete if metadata is not None else None
        # The post-discovery grace is expressed as a policy WITHOUT a stop rather than as a
        # flag beside one. A stop that is held off and a stop that does not exist are the
        # same thing to the decision, and saying it two ways is how they drift apart.
        stop_live = sl_is_live(lot)
        effective_policy = (
            policy if stop_live else dataclasses.replace(policy, stop_loss_pct=None)
        )
        decision = evaluate_position(
            policy=effective_policy,
            holding=holding,
            quote=quote,
            state=prior_state,
            rug=rug,
            confirmed_slot=confirmed_slot,
            dispose_enabled=dispose_enabled,
            pump_complete=pump_complete,
        )
        self._persist_position_state(holding.mint, decision.next_state)

        if (
            prior_state.dispose_trigger_slot is None
            and decision.next_state.dispose_trigger_slot is not None
        ):
            await self.notifier.send(
                severity="warning",
                category="policy",
                message=(
                    f"DISPOSE TRIGGERED: {policy.name} crossed break-even; "
                    "waiting one confirmed block"
                ),
                context={
                    "mint": holding.mint,
                    "pnl_pct": decision.pnl_pct,
                    "trigger_slot": decision.next_state.dispose_trigger_slot,
                },
                dedup_key=(
                    f"dispose-trigger:{holding.mint}:"
                    f"{decision.next_state.dispose_trigger_slot}"
                ),
                dedup_seconds=0,
            )

        if decision.kind == DecisionKind.ACTIVATE_TRAIL:
            await self.notifier.send(
                severity="info",
                category="policy",
                message=decision.reason,
                context={
                    "mint": holding.mint,
                    "pnl_pct": decision.pnl_pct,
                    "runner_tightness": (
                        str(policy.runner_tightness)
                        if policy.runner_tightness is not None
                        else None
                    ),
                },
                dedup_key=f"trail-activate:{holding.mint}",
                dedup_seconds=86_400,
            )

        execution = None
        if decision.exits:
            if decision.kind == DecisionKind.EXIT_RUG:
                await self.notifier.send(
                    severity="critical",
                    category="rug",
                    message=f"RUG SIGNAL: {policy.name} — {decision.reason}",
                    context={"mint": holding.mint, "pnl_pct": decision.pnl_pct},
                    dedup_key=f"rug:{holding.mint}",
                    dedup_seconds=0,
                )
            if (
                decision.kind == DecisionKind.EXIT_DISPOSE
                and not self._dispose_enabled(holding.mint, policy)
            ):
                cancelled_state = dataclasses.replace(
                    decision.next_state,
                    last_pnl_pct=None,
                    dispose_trigger_slot=None,
                )
                decision = dataclasses.replace(
                    decision,
                    kind=DecisionKind.HOLD,
                    reason="dispose was cancelled before execution",
                    next_state=cancelled_state,
                )
                self._persist_position_state(holding.mint, cancelled_state)
            else:
                execution = await self.executor.sell(
                    mint=holding.mint,
                    name=policy.name,
                    reason=decision.kind,
                    observed_holding=holding,
                    amount=decision.sell_amount,
                )

        self.rug_detector.record(
            holding=holding, pool=record_pool, mint_safety=safety, quote=quote
        )
        entry_unit_price = policy.entry_unit_price(holding)
        row = {
            "mint": holding.mint,
            "name": policy.name,
            "amount": str(holding.amount),
            "ui_amount": str(holding.ui_amount),
            "decimals": holding.decimals,
            "exit_lamports": quote.out_lamports if quote else None,
            "exit_sol": str(Decimal(quote.out_lamports) / 1_000_000_000) if quote else None,
            "unit_price_sol": str(quote.unit_price_sol(holding)) if quote else None,
            "price_impact_pct": (
                str(quote.price_impact_pct)
                if quote and quote.price_impact_pct is not None
                else None
            ),
            "quote_received_at": quote.received_at.isoformat() if quote else None,
            "pnl_pct": str(decision.pnl_pct) if decision.pnl_pct is not None else None,
            "basis_source": basis_source,
            "entry_unit_price_sol": (
                str(entry_unit_price) if entry_unit_price is not None else None
            ),
            "decision": decision.kind.value,
            "decision_reason": decision.reason,
            "trailing_active": decision.next_state.trailing_active,
            "trailing_peak_unit_price_sol": (
                str(decision.next_state.trailing_peak_unit_price_sol)
                if decision.next_state.trailing_peak_unit_price_sol is not None
                else None
            ),
            "dispose_after_break_even": dispose_enabled,
            "dispose_trigger_slot": decision.next_state.dispose_trigger_slot,
            "dispose_wait_until_slot": (
                decision.next_state.dispose_trigger_slot + 1
                if decision.next_state.dispose_trigger_slot is not None
                else None
            ),
            "confirmed_slot": confirmed_slot,
            # None is rendered as null, never as a number. A dashboard that shows "0" for
            # an absent stop is showing a stop.
            "thresholds": {
                "stop_loss_pct": _optional_str(policy.stop_loss_pct),
                "take_profit_pct": _optional_str(policy.take_profit_pct),
                "runner_tightness": _optional_str(policy.runner_tightness),
                "floor_confirm_quotes": policy.floor_confirm_quotes,
                "hold_trail_until_graduated": policy.hold_trail_until_graduated,
            },
            "runner": {
                "floor_multiple": (
                    str(decision.next_state.runner_floor_multiple)
                    if decision.next_state.runner_floor_multiple is not None
                    else None
                ),
                "below_floor_streak": decision.next_state.below_floor_streak,
                "below_stop_streak": decision.next_state.below_stop_streak,
                "scale_rungs_fired": list(decision.next_state.scale_rungs_fired),
                "original_amount": decision.next_state.original_amount,
                "sell_amount": decision.sell_amount,
            },
            # "a stop would fire now", not "a stop exists": a bag with no stop at all and a
            # bag still inside its basis grace are both not stopping out.
            "stop_live": stop_live and policy.stop_loss_pct is not None,
            "sl_live_after": lot.sl_live_after,
            "rug": to_jsonable(rug),
            "pool": to_jsonable(pool) if pool else None,
            "mint_safety": self._safety_json(safety),
            "pump_metadata": to_jsonable(metadata) if metadata else None,
            "advisory_errors": advisory_errors,
            # LP-token burn is not a sound generic concept for CLMM/DLMM pools.
            "lp_lock_status": "unsupported_for_pool_type",
            "errors": errors,
        }
        return row, execution

    async def _inspect_unmonitored(self, holding: TokenHolding) -> dict[str, Any]:
        quote = None
        errors: list[str] = []
        if self.jupiter.ready:
            try:
                quote = await self.jupiter.quote_exit(holding.mint, holding.amount)
            except ExternalServiceError as exc:
                errors.append(str(exc))
        pool_result, safety_result, metadata_result = await asyncio.gather(
            self._pool_for(holding.mint),
            self.rpc.mint_safety(holding.mint),
            self._pump_metadata_for(holding.mint),
            return_exceptions=True,
        )
        pool = None if isinstance(pool_result, Exception) else pool_result
        safety = None if isinstance(safety_result, Exception) else safety_result
        if isinstance(pool_result, Exception):
            errors.append(f"pool check failed ({type(pool_result).__name__})")
        if isinstance(safety_result, Exception):
            errors.append(f"mint check failed ({type(safety_result).__name__})")
        metadata = None
        advisory_errors: list[str] = []
        if isinstance(metadata_result, Exception):
            advisory_errors.append(
                f"Pump metadata failed ({type(metadata_result).__name__})"
            )
        else:
            metadata, metadata_error = metadata_result
            if metadata_error:
                advisory_errors.append(f"Pump metadata failed ({metadata_error})")
        rug = self.rug_detector.assess(
            holding=holding, pool=pool, mint_safety=safety, quote=quote
        )
        if rug.emergency:
            await self.notifier.send(
                severity="critical",
                category="rug",
                message=(
                    f"RUG SIGNAL on observe-only shitcoims holding "
                    f"{pool.token_symbol if pool and pool.token_symbol else holding.mint}: {rug.reason}"
                ),
                context={"mint": holding.mint, "auto_exit": False},
                dedup_key=f"observe-rug:{holding.mint}",
            )
        self.rug_detector.record(
            holding=holding, pool=pool, mint_safety=safety, quote=quote
        )
        symbol = pool.token_symbol if pool and pool.token_symbol else None
        return {
            "mint": holding.mint,
            "name": symbol or (holding.mint[:6] + "…" + holding.mint[-4:]),
            "token_name": pool.token_name if pool else None,
            "amount": str(holding.amount),
            "ui_amount": str(holding.ui_amount),
            "decimals": holding.decimals,
            "protection": "observe-only",
            "exit_sol": (
                str(Decimal(quote.out_lamports) / 1_000_000_000) if quote is not None else None
            ),
            "quote_received_at": quote.received_at.isoformat() if quote else None,
            "pool": to_jsonable(pool) if pool else None,
            "mint_safety": self._safety_json(safety),
            "pump_metadata": to_jsonable(metadata) if metadata else None,
            "rug": to_jsonable(rug),
            "errors": errors,
            "advisory_errors": advisory_errors,
        }

    async def _inspect_unmonitored_bounded(self, holding: TokenHolding) -> dict[str, Any]:
        async with self._enrichment_semaphore:
            return await self._inspect_unmonitored(holding)

    async def _observe_unmonitored(
        self, holdings: list[TokenHolding]
    ) -> list[dict[str, Any]]:
        if not self.config.auto_discover:
            return [
                {
                    "mint": holding.mint,
                    "name": holding.mint[:6] + "…" + holding.mint[-4:],
                    "amount": str(holding.amount),
                    "ui_amount": str(holding.ui_amount),
                    "decimals": holding.decimals,
                    "protection": "discovery-disabled",
                    "errors": ["automatic discovery disabled"],
                }
                for holding in holdings
            ]
        limit = self.config.experiments.max_unmonitored_holdings
        active_holdings = holdings[:limit]
        quarantined_holdings = holdings[limit:]
        now = time.monotonic()
        mints = {holding.mint for holding in active_holdings}
        needs_sweep = now >= self._next_observe_sweep or not mints.issubset(self._unmonitored_cache)
        if needs_sweep and active_holdings:
            rows = await asyncio.gather(
                *(self._inspect_unmonitored_bounded(holding) for holding in active_holdings)
            )
            self._unmonitored_cache = {row["mint"]: row for row in rows}
            self._next_observe_sweep = now + self.config.rug.poll_interval_seconds
        else:
            self._unmonitored_cache = {
                mint: row for mint, row in self._unmonitored_cache.items() if mint in mints
            }
        output = []
        for holding in active_holdings:
            cached = copy.deepcopy(
                self._unmonitored_cache.get(
                    holding.mint,
                    {
                        "mint": holding.mint,
                        "name": holding.mint[:6] + "…" + holding.mint[-4:],
                        "protection": "observe-only",
                        "errors": ["awaiting safety sweep"],
                    },
                )
            )
            cached.update(
                {
                    "amount": str(holding.amount),
                    "ui_amount": str(holding.ui_amount),
                    "decimals": holding.decimals,
                }
            )
            output.append(cached)
        output.extend(
            {
                "mint": holding.mint,
                "name": holding.mint[:6] + "…" + holding.mint[-4:],
                "amount": str(holding.amount),
                "ui_amount": str(holding.ui_amount),
                "decimals": holding.decimals,
                "protection": "quarantined",
                "errors": ["discovery budget exceeded; no external enrichment"],
            }
            for holding in quarantined_holdings
        )
        return output

    async def _hold_terminal_intent(
        self, mint: str, intent: dict[str, Any], *, name: str
    ) -> None:
        """A failed intent is terminal. Never replay it from a restart.

        The operator was already paged with MANUAL ACTION REQUIRED for this exact
        sale. `KeepAlive` in the launchd plist means a crash loop would otherwise
        re-attempt it silently, and re-page on every restart forever. The entry
        stays visible and clears itself once the bag is gone; the page fires once.
        """

        if intent.get("resume_blocked_at"):
            log.warning(
                "pending exit for %s stays blocked pending operator action (%s)",
                name,
                intent.get("last_error"),
            )
            return
        blocked = dict(intent)
        blocked["resume_blocked_at"] = utc_now().isoformat()
        self.state.set("pending_exits", mint, value=blocked)
        await self.notifier.send(
            severity="critical",
            category="reconciliation",
            message=(
                f"PENDING EXIT NOT AUTO-RESUMED for {name}: the previous attempt failed and "
                "MANUAL ACTION REQUIRED was already sent. Sell by hand, or acknowledge the "
                "intent before the sentinel will retry it."
            ),
            context={
                "mint": mint,
                "prior_status": intent.get("status"),
                "last_error": intent.get("last_error"),
                "auto_action": False,
            },
            dedup_seconds=0,
        )

    async def _settle_absent_holding(
        self, mint: str, intent: dict[str, Any], *, name: str
    ) -> bool:
        """The bag is gone. If a submitted signature is on file, settle it first.

        A sale that confirmed while the sentinel was down is realized money.
        Deleting the intent without resolving its signature drops that fill out of
        `trades.csv` and out of every performance number computed from it — the
        same class of accounting hole that kept -7.47 SOL invisible.

        Returns True when the executor has taken ownership of the entry. The
        resolver is reached defensively so a stubbed executor (and any build
        predating it) degrades to the previous clear-and-notify behaviour.
        """

        signature = intent.get("signature")
        # `resolve_pending_exit` is the executor's public contract. Still probed rather than
        # called directly, because the test suite substitutes stub executors that legitimately
        # do not implement it — but probing a PUBLIC name means a rename is a visible break
        # instead of a silent degradation to "never resolve, just delete".
        resolve = getattr(self.executor, "resolve_pending_exit", None)
        if not signature or resolve is None:
            return False
        settled = await resolve(
            mint=mint,
            name=name,
            reason=str(intent.get("reason") or "resume_pending_exit"),
        )
        return settled is not None

    async def _clear_pending_exit(
        self, mint: str, *, name: str, message: str, context: dict[str, Any]
    ) -> None:
        self.state.delete("pending_exits", mint)
        await self.notifier.send(
            severity="warning",
            category="reconciliation",
            message=message,
            context={"mint": mint, "name": name, "auto_action": False, **context},
            dedup_seconds=0,
        )

    async def reconcile_pending_exits(self) -> None:
        pending = self.state.get("pending_exits", default={})
        if not isinstance(pending, dict) or not pending:
            return
        holdings = {
            holding.mint: holding
            for holding in await self.rpc.token_holdings(self.wallet_address)
        }
        for mint, intent in pending.items():
            if not isinstance(intent, dict):
                self.state.delete("pending_exits", mint)
                continue
            name = str(intent.get("name") or mint[:8])
            holding = holdings.get(mint)
            if holding is None:
                if await self._settle_absent_holding(mint, intent, name=name):
                    continue
                self.state.delete("pending_exits", mint)
                await self.notifier.send(
                    severity="info",
                    category="reconciliation",
                    message=f"Cleared completed pending exit for {name}",
                    context={"mint": mint},
                    dedup_seconds=0,
                )
                continue
            if (
                str(intent.get("status") or "") in TERMINAL_INTENT_STATUSES
                and intent.get("operator_resume_ack") is not True
            ):
                await self._hold_terminal_intent(mint, intent, name=name)
                continue
            resume_amount = intent.get("sell_amount")
            try:
                resume_int = int(resume_amount) if resume_amount is not None else None
            except (TypeError, ValueError):
                resume_int = None
            if (
                resume_int is not None
                and not 0 < resume_int <= holding.amount
                # An intent carrying a signature is the executor's to settle: it
                # polls that signature before anything else and may still have a
                # ledger row to write. Only an intent with nothing in flight can
                # be cleared here.
                and not intent.get("signature")
            ):
                # A fill landed while the sentinel was down, so the recorded amount
                # can no longer execute. The executor's SELL SKIPPED branch returns
                # before it can clear the entry, which re-pages on every restart
                # forever. Clear it here and let the policy loop decide again on
                # fresh data instead of replaying a stale sell.
                await self._clear_pending_exit(
                    mint,
                    name=name,
                    message=(
                        f"Cleared unexecutable pending exit for {name}: intent wanted "
                        f"{resume_int} of {holding.amount} held"
                    ),
                    context={"sell_amount": resume_int, "held_amount": holding.amount},
                )
                continue
            await self.notifier.send(
                severity="critical",
                category="reconciliation",
                message=f"Resuming pending shitcoims exit for {name}",
                context={"mint": mint, "prior_status": intent.get("status")},
                dedup_seconds=0,
            )
            result = await self.executor.sell(
                mint=mint,
                name=name,
                reason=str(intent.get("reason") or "resume_pending_exit"),
                observed_holding=holding,
                amount=resume_int,
            )
            if getattr(result, "status", None) == "skipped":
                # The executor refused the amount and returned before touching
                # state. Without this the entry outlives every restart.
                await self._clear_pending_exit(
                    mint,
                    name=name,
                    message=(
                        f"Cleared pending exit for {name}: the executor skipped it "
                        "and it will not be retried automatically"
                    ),
                    context={"sell_amount": resume_int, "held_amount": holding.amount},
                )

    async def cycle(self) -> dict[str, Any]:
        # One lock hold covers read, widen and write, so a dashboard edit landing
        # mid-cycle cannot be reverted by a stale copy of the policy list.
        await self.mutate_positions(self._policies_relaxed_to_default_stop)
        async with self._policy_lock:
            policies = tuple(self.config.positions)
        if not self._telegram_probe_attempted:
            await self.notifier.probe()
            self._telegram_probe_attempted = True
        rpc_ok, sol_lamports, holdings = await asyncio.gather(
            self.rpc.health(),
            self.rpc.sol_balance(self.wallet_address),
            self.rpc.token_holdings(self.wallet_address),
        )
        if not rpc_ok:
            raise RuntimeError("Helius RPC health check failed")
        holdings_by_mint = {holding.mint: holding for holding in holdings}
        policies_by_mint = {policy.mint: policy for policy in policies}
        dispose_needs_slot = any(
            self._dispose_enabled(policy.mint, policy) for policy in policies
        )
        confirmed_slot = None
        if dispose_needs_slot:
            try:
                confirmed_slot = await self.rpc.confirmed_slot()
            except ExternalServiceError as exc:
                log.warning("confirmed slot unavailable: %s", type(exc).__name__)
        positions: list[dict[str, Any]] = []
        portfolio_exit_lamports = 0
        configured_errors = False

        drop_default_mints: list[str] = []
        strip_basis_mints: list[str] = []
        self._basis_refills: list[Any] = []
        persisted = self.state.get("positions", default={})
        if isinstance(persisted, dict):
            for mint in list(persisted):
                if mint not in holdings_by_mint:
                    action = self._retire_absent_lot(mint)
                    if action == "drop":
                        drop_default_mints.append(mint)
                    elif action == "strip":
                        strip_basis_mints.append(mint)
        for policy in policies:
            holding = holdings_by_mint.get(policy.mint)
            if holding is None:
                action = self._retire_absent_lot(policy.mint)
                if action == "drop":
                    drop_default_mints.append(policy.mint)
                elif action == "strip":
                    strip_basis_mints.append(policy.mint)
                positions.append(
                    {
                        "mint": policy.mint,
                        "name": policy.name,
                        "amount": "0",
                        "ui_amount": "0",
                        "decision": "absent",
                        "decision_reason": "shitcoims has no non-zero balance",
                        "dispose_after_break_even": self._dispose_enabled(
                            policy.mint, policy
                        ),
                        "confirmed_slot": confirmed_slot,
                        "errors": ["configured position has zero balance"],
                    }
                )
                continue
            row, _execution = await self._inspect_position(
                holding, policy, confirmed_slot
            )
            positions.append(row)
            if row["exit_lamports"] is not None:
                portfolio_exit_lamports += int(row["exit_lamports"])
            if row["errors"]:
                configured_errors = True

        unmonitored_holdings = []
        current_unmonitored = set(holdings_by_mint) - set(policies_by_mint)
        for mint in sorted(current_unmonitored):
            holding = holdings_by_mint[mint]
            unmonitored_holdings.append(holding)
            if mint not in self._known_unmonitored:
                await self.notifier.send(
                    severity="warning",
                    category="discovery",
                    message=f"UNMONITORED POSITION on shitcoims: {mint}",
                    context={"mint": mint, "ui_amount": holding.ui_amount},
                    dedup_key=f"unmonitored:{mint}",
                    dedup_seconds=86_400,
                )
        self._known_unmonitored = current_unmonitored
        if len(unmonitored_holdings) > self.config.experiments.max_unmonitored_holdings:
            await self.notifier.send(
                severity="warning",
                category="discovery",
                message=(
                    f"shitcoims discovery budget exceeded: {len(unmonitored_holdings)} holdings; "
                    f"enriching at most {self.config.experiments.max_unmonitored_holdings}"
                ),
                context={"auto_action": False},
                dedup_key="discovery-budget-exceeded",
                dedup_seconds=3600,
            )
        unmonitored = await self._observe_unmonitored(unmonitored_holdings)
        await self._schedule_and_apply_defaults(unmonitored, holdings_by_mint)
        portfolio_exit_lamports += sum(
            int(Decimal(str(row["exit_sol"])) * 1_000_000_000)
            for row in unmonitored
            if row.get("exit_sol") is not None
        )

        live, gate_failures = self.gate.status(jupiter_ready=self.jupiter.ready)
        if configured_errors or (policies and not self.jupiter.ready) or unmonitored:
            protection_state = "DEGRADED"
        elif live:
            protection_state = "LIVE_ARMED"
        elif policies:
            protection_state = "DRY_RUN"
        else:
            protection_state = "OBSERVE_ONLY"

        self.last_cycle_at = utc_now()
        self.last_cycle_error = None
        readiness, freshness = self._operational_sections(
            positions=positions,
            unmonitored=unmonitored,
            live=live,
            configured_errors=configured_errors,
        )
        snapshot = {
            "schema_version": 2,
            "generated_at": self.last_cycle_at.isoformat(),
            "system": {
                "wallet_name": "shitcoims",
                "wallet_address": self.wallet_address,
                "mode": "live" if live else "dry-run",
                "protection_state": protection_state,
                "running": self.running,
                "rpc_ready": True,
                "jupiter_ready": self.jupiter.ready,
                "telegram_ready": self.notifier.telegram_ready,
                "telegram_configured": self.notifier.telegram_configured,
                "telegram_last_error_type": self.notifier.telegram_last_error_type,
                "gate_failures": gate_failures,
                "poll_interval_seconds": self.config.poll_interval_seconds,
                "last_cycle_at": self.last_cycle_at.isoformat(),
                "last_cycle_error": None,
                "unprotected_count": len(unmonitored),
            },
            "wallet": {
                "sol_lamports": sol_lamports,
                "sol": str(Decimal(sol_lamports) / 1_000_000_000),
                "portfolio_exit_sol": str(Decimal(portfolio_exit_lamports) / 1_000_000_000),
            },
            "positions": positions,
            "unmonitored": unmonitored,
            "readiness": readiness,
            "freshness": freshness,
            "experiments": self._experiment_rows(),
            "signals": self._signal_rows(positions, unmonitored),
            "events": self.journal.recent(),
        }
        await self._set_snapshot(snapshot)
        await self._maybe_heartbeat(snapshot)
        drop = set(drop_default_mints)
        strip = set(strip_basis_mints)
        refills = getattr(self, "_basis_refills", [])
        await self.mutate_positions(
            lambda current: self._rewrite_lots_yaml(
                current, drop=drop, strip=strip, refills=refills
            )
        )
        return snapshot

    def _rewrite_lots_yaml(
        self,
        current: tuple[Any, ...],
        *,
        drop: set[str],
        strip: set[str],
        refills: list[Any],
    ) -> list[Any] | None:
        refill_by_mint = {item.mint: item for item in refills}
        next_policies: list[Any] = []
        changed = False
        for policy in current:
            if policy.mint in drop:
                changed = True
                continue
            if policy.mint in refill_by_mint:
                next_policies.append(refill_by_mint[policy.mint])
                changed = True
                continue
            if policy.mint in strip and (
                policy.cost_basis_sol is not None or policy.buy_price_sol is not None
            ):
                next_policies.append(policy_without_basis(policy))
                changed = True
                continue
            next_policies.append(policy)
        return next_policies if changed else None

    def _policies_relaxed_to_default_stop(
        self, policies: tuple[Any, ...]
    ) -> list[Any] | None:
        """Bring sentinel-authored bags to the current default stop. Operator YAML is not touched.

        Direction matters and is enforced below: this only ever LOOSENS. It lifted leftover
        -10 scalp stops back when the default was -35, and now that the default is no stop
        at all it removes the stop from bags the sentinel protected for itself. It can never
        add a stop to a bag or tighten one, whatever the default becomes.
        """

        default_stop = DEFAULTS.stop_loss_pct
        next_policies: list[Any] = []
        relaxed: list[str] = []
        for policy in policies:
            lot = self._lot(policy.mint)
            if (
                lot.origin == ORIGIN_DEFAULT
                and policy.stop_loss_pct is not None
                and (default_stop is None or policy.stop_loss_pct > default_stop)
            ):
                next_policies.append(dataclasses.replace(policy, stop_loss_pct=default_stop))
                relaxed.append(policy.mint)
                continue
            next_policies.append(policy)
        if not relaxed:
            return None
        log.warning(
            "relaxed the auto-protect stop to %s on %d bag(s): %s",
            "none" if default_stop is None else f"{default_stop}%",
            len(relaxed),
            ", ".join(relaxed),
        )
        return next_policies

    async def _maybe_heartbeat(self, snapshot: dict[str, Any]) -> None:
        import datetime as dt

        last_raw = self.state.get("last_heartbeat_at")
        last = dt.datetime.fromisoformat(last_raw) if last_raw else None
        now = utc_now()
        due = last is None or (now - last).total_seconds() >= (
            self.config.notifications.heartbeat_interval_hours * 3600
        )
        if due:
            await self.notifier.send(
                severity="info",
                category="heartbeat",
                message=(
                    f"Sentinel alive. Watching {len(snapshot['positions'])} configured shitcoims "
                    f"positions; {len(snapshot['unmonitored'])} unmonitored."
                ),
                context={"protection_state": snapshot["system"]["protection_state"]},
                dedup_key="heartbeat",
                dedup_seconds=0,
            )
            self.state.set("last_heartbeat_at", value=now.isoformat())

    async def run(self) -> None:
        self.running = True
        stream_task = asyncio.create_task(
            self._wallet_stream_loop(), name="shitcoims-wallet-activity"
        )
        advisory_tasks = [
            asyncio.create_task(
                self._advisory_wallet_stream_loop(wallet),
                name=f"advisory-wallet-{wallet.id}",
            )
            for wallet in self.config.experiments.advisory_wallets
        ]
        await self.notifier.send(
            severity="info",
            category="system",
            message=f"shitcoims Sentinel starting with {len(self.config.positions)} configured positions",
            context={"wallet": self.wallet_address},
            dedup_key="startup",
            dedup_seconds=0,
        )
        try:
            await self.reconcile_pending_exits()
            while True:
                self._cycle_wakeup.clear()
                await self.cycle()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._cycle_wakeup.wait(),
                        timeout=self.config.poll_interval_seconds,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.running = False
            self.last_cycle_error = f"{type(exc).__name__}: {exc}"
            snapshot = await self.snapshot()
            snapshot["system"].update(
                {
                    "running": False,
                    "protection_state": "DOWN",
                    "last_cycle_error": self.last_cycle_error,
                }
            )
            await self._set_snapshot(snapshot)
            await self.notifier.send(
                severity="critical",
                category="system",
                message=f"SENTINEL DOWN: {self.last_cycle_error}",
                dedup_key="sentinel-down",
                dedup_seconds=0,
            )
            raise
        finally:
            self.running = False
            stream_task.cancel()
            for task in advisory_tasks:
                task.cancel()
            await asyncio.gather(stream_task, *advisory_tasks, return_exceptions=True)

    async def panic(self) -> list[ExecutionResult]:
        holdings = await self.rpc.token_holdings(self.wallet_address)
        names = {policy.mint: policy.name for policy in self.config.positions}
        results = []
        for holding in holdings:
            results.append(
                await self.executor.sell(
                    mint=holding.mint,
                    name=names.get(holding.mint, holding.mint[:8]),
                    reason="panic",
                    observed_holding=holding,
                )
            )
        return results

    def list_policies(self) -> list[dict[str, Any]]:
        return [policy_to_api_mapping(policy) for policy in self.config.positions]

    async def mutate_positions(
        self,
        mutate: Callable[[tuple[PositionPolicy, ...]], list[PositionPolicy] | None],
        *,
        origin: str | None = None,
        touch: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read-modify-write `config.positions` under one uninterrupted lock hold.

        `mutate` is synchronous on purpose. An await between reading the current
        policies and writing the new ones is exactly the window in which a
        concurrent operator edit is silently dropped. Return None for a no-op.
        """

        async with self._policy_lock:
            proposed = mutate(tuple(self.config.positions))
            if proposed is None:
                return self.list_policies()
            persist_positions(self.config.config_path, proposed)
            self.config = dataclasses.replace(self.config, positions=tuple(proposed))
            items = self.list_policies()
        if origin is not None:
            for mint in touch or [item.mint for item in proposed]:
                self.mark_policy_origin([mint], origin)
        # Do not wait for the next poll: newly written YAML should be evaluated
        # on the following cycle so the dashboard stops screaming unprotected.
        self._cycle_wakeup.set()
        return items

    async def apply_positions(
        self,
        policies: list[PositionPolicy],
        *,
        origin: str | None = None,
        touch: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Replace the policy list wholesale. Callers that derive the new list
        from the current one must use `mutate_positions` instead."""

        return await self.mutate_positions(
            lambda _current: list(policies), origin=origin, touch=touch
        )

    async def _schedule_and_apply_defaults(
        self,
        unmonitored: list[dict[str, Any]],
        holdings_by_mint: dict[str, TokenHolding],
    ) -> None:
        delay = DEFAULT_NEW_BAG_PROTECT_DELAY_SECONDS
        due_rows: list[dict[str, Any]] = []
        for row in unmonitored:
            mint = str(row.get("mint") or "")
            if not mint:
                continue
            record, fresh = note_seen(self._lot(mint), mint, delay_seconds=delay)
            self._write_lot(record)
            if fresh:
                await self.notifier.send(
                    severity="warning",
                    category="discovery",
                    message=(
                        f"NEW BAG {row.get('name') or mint[:8]}: default rule "
                        f"({_default_rule_text()}) in {int(delay / 60)}m; "
                        f"rug-only until then"
                    ),
                    context={"mint": mint, "auto_action": False},
                    dedup_key=f"new-bag:{mint}:{record.generation}",
                    dedup_seconds=0,
                )
            if due_for_default(record):
                due_rows.append(row)
        if not due_rows:
            return
        # Read every basis off chain BEFORE touching the policy list: the merge
        # below has to be one synchronous read-modify-write, and an RPC round trip
        # in the middle of it is how a concurrent operator edit gets clobbered.
        observed_price: dict[str, Decimal] = {}
        for row in due_rows:
            mint = str(row.get("mint") or "")
            holding = holdings_by_mint.get(mint)
            basis: ObservedBasis | None = None
            reason = "holding disappeared before its basis could be read"
            if holding is not None:
                basis, reason = await self._observed_basis(holding, self._lot(mint))
            if basis is None:
                # Fail closed. `_inspect_position` retries the read every cycle
                # (behind its cooldown) because a default-origin policy with no
                # observed buy price still needs one.
                log.warning("no observed cost basis for %s: %s", mint, reason)
                continue
            observed_price[mint] = basis.unit_price_sol

        outcome: dict[str, Any] = {"created": [], "skipped": []}

        def merge(current: tuple[Any, ...]) -> list[Any] | None:
            merged, created, skipped = policies_for_unmonitored(
                unmonitored=due_rows,
                current=list(current),
                # Never seed a basis from the exit quote. `from_quote` is the
                # fabrication that made PnL start at 0% and turned every stop into
                # a realized loss. A default bag is rug-only until its real basis
                # has been read back off chain.
                mode="rug_only",
            )
            outcome["created"] = created
            outcome["skipped"] = skipped
            if not created:
                return None
            fresh = set(created)
            for index, policy in enumerate(merged):
                price = observed_price.get(policy.mint)
                if price is not None and policy.mint in fresh:
                    merged[index] = dataclasses.replace(
                        policy, buy_price_sol=price, cost_basis_sol=None
                    )
            return merged

        await self.mutate_positions(merge)
        created = list(outcome["created"])
        skipped = outcome["skipped"]
        if not created:
            return
        self.mark_policy_origin(created, ORIGIN_DEFAULT)
        observed = [mint for mint in created if mint in observed_price]
        rug_only = [mint for mint in created if mint not in observed_price]
        await self.notifier.send(
            severity="warning" if rug_only else "info",
            category="policy",
            message=(
                f"Auto-protected {len(created)} bag(s): {len(observed)} with an observed "
                f"on-chain cost basis ({_default_rule_text()}), "
                f"{len(rug_only)} rug-only until a basis can be read"
            ),
            context={
                "mints": created,
                "observed_basis": observed,
                "rug_only": rug_only,
                "skipped": skipped,
                "auto_action": False,
            },
            dedup_key=f"auto-protect:{','.join(created)}",
            dedup_seconds=0,
        )

    async def close(self) -> None:
        await self.http.aclose()
