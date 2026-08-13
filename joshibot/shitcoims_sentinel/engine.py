from __future__ import annotations

import asyncio
import contextlib
import copy
import dataclasses
import logging
import time
from collections import deque
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
    DEFAULT_NEW_BAG_STOP_LOSS_PCT,
    DEFAULT_NEW_BAG_TAKE_PROFIT_PCT,
    DEFAULT_NEW_BAG_TRAILING_STOP_PCT,
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
from .policies import persist_positions, policies_for_unmonitored, policy_to_mapping, policy_without_basis
from .rug_detector import RugDetector
from .secrets import load_shitcoims_keypair
from .storage import EventJournal, StateStore

log = logging.getLogger(__name__)


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
        if lot.needs_basis:
            policy = policy_without_basis(policy)
        quote = None
        pool = None
        safety = None
        errors: list[str] = []

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

        if lot.needs_basis and quote is not None and quote.out_lamports > 0:
            basis = Decimal(quote.out_lamports) / LAMPORTS_PER_SOL
            policy = dataclasses.replace(policy, cost_basis_sol=basis, buy_price_sol=None)
            self._basis_refills.append(policy)
            self._write_lot(basis_applied(lot))
            await self.notifier.send(
                severity="info",
                category="policy",
                message=(
                    f"NEW LOT {policy.name}: cost basis reset to quoted {basis} SOL"
                ),
                context={"mint": holding.mint, "auto_action": False},
                dedup_key=f"new-lot-basis:{holding.mint}:{lot.generation}",
                dedup_seconds=0,
            )

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
        stop_enabled = sl_is_live(lot)
        decision = evaluate_position(
            policy=policy,
            holding=holding,
            quote=quote,
            state=prior_state,
            rug=rug,
            confirmed_slot=confirmed_slot,
            dispose_enabled=dispose_enabled,
            pump_complete=pump_complete,
            stop_enabled=stop_enabled,
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
                    "exit_style": policy.exit_style,
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
            "thresholds": {
                "stop_loss_pct": str(policy.stop_loss_pct),
                "take_profit_pct": str(policy.take_profit_pct),
                "trailing_stop_pct": str(policy.trailing_stop_pct),
                "exit_style": policy.exit_style,
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
            "stop_live": stop_enabled,
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

    async def reconcile_pending_exits(self) -> None:
        pending = self.state.get("pending_exits", default={})
        if not isinstance(pending, dict) or not pending:
            return
        holdings = {
            holding.mint: holding
            for holding in await self.rpc.token_holdings(self.wallet_address)
        }
        for mint, intent in pending.items():
            holding = holdings.get(mint)
            if holding is None:
                self.state.delete("pending_exits", mint)
                await self.notifier.send(
                    severity="info",
                    category="reconciliation",
                    message=f"Cleared completed pending exit for {intent.get('name', mint)}",
                    context={"mint": mint},
                    dedup_seconds=0,
                )
                continue
            await self.notifier.send(
                severity="critical",
                category="reconciliation",
                message=f"Resuming pending shitcoims exit for {intent.get('name', mint)}",
                context={"mint": mint, "prior_status": intent.get("status")},
                dedup_seconds=0,
            )
            resume_amount = intent.get("sell_amount")
            try:
                resume_int = int(resume_amount) if resume_amount is not None else None
            except (TypeError, ValueError):
                resume_int = None
            await self.executor.sell(
                mint=mint,
                name=str(intent.get("name") or mint[:8]),
                reason=str(intent.get("reason") or "resume_pending_exit"),
                observed_holding=holding,
                amount=resume_int,
            )

    async def cycle(self) -> dict[str, Any]:
        async with self._policy_lock:
            policies = tuple(self.config.positions)
        widened = self._policies_with_widened_default_stops(policies)
        if widened is not None:
            await self.apply_positions(widened)
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
        await self._schedule_and_apply_defaults(unmonitored)
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
        rewritten = self._rewrite_lots_yaml(
            drop=set(drop_default_mints),
            strip=set(strip_basis_mints),
            refills=getattr(self, "_basis_refills", []),
        )
        if rewritten is not None:
            await self.apply_positions(rewritten)
        return snapshot

    def _rewrite_lots_yaml(
        self,
        *,
        drop: set[str],
        strip: set[str],
        refills: list[Any],
    ) -> list[Any] | None:
        refill_by_mint = {item.mint: item for item in refills}
        next_policies: list[Any] = []
        changed = False
        for policy in self.config.positions:
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

    def _policies_with_widened_default_stops(
        self, policies: tuple[Any, ...]
    ) -> list[Any] | None:
        """Lift leftover -10 scalp defaults. Operator YAML is untouched."""

        next_policies: list[Any] = []
        changed = False
        for policy in policies:
            lot = self._lot(policy.mint)
            if (
                lot.origin == ORIGIN_DEFAULT
                and policy.stop_loss_pct > DEFAULT_NEW_BAG_STOP_LOSS_PCT
            ):
                next_policies.append(
                    dataclasses.replace(
                        policy, stop_loss_pct=DEFAULT_NEW_BAG_STOP_LOSS_PCT
                    )
                )
                changed = True
                continue
            next_policies.append(policy)
        return next_policies if changed else None

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
        return [policy_to_mapping(policy) for policy in self.config.positions]

    async def apply_positions(
        self,
        policies: list[PositionPolicy],
        *,
        origin: str | None = None,
        touch: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        async with self._policy_lock:
            persist_positions(self.config.config_path, policies)
            self.config = dataclasses.replace(self.config, positions=tuple(policies))
            items = self.list_policies()
        if origin is not None:
            for mint in touch or [item.mint for item in policies]:
                self.mark_policy_origin([mint], origin)
        # Do not wait for the next poll: newly written YAML should be evaluated
        # on the following cycle so the dashboard stops screaming unprotected.
        self._cycle_wakeup.set()
        return items

    async def _schedule_and_apply_defaults(self, unmonitored: list[dict[str, Any]]) -> None:
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
                        f"NEW BAG {row.get('name') or mint[:8]}: default SL "
                        f"{DEFAULT_NEW_BAG_STOP_LOSS_PCT}% / arm "
                        f"+{DEFAULT_NEW_BAG_TAKE_PROFIT_PCT}% in {int(delay / 60)}m "
                        f"(SL itself waits another 10m; rug-only until then)"
                    ),
                    context={"mint": mint, "auto_action": False},
                    dedup_key=f"new-bag:{mint}:{record.generation}",
                    dedup_seconds=0,
                )
            if due_for_default(record):
                due_rows.append(row)
        if not due_rows:
            return
        merged, created, skipped = policies_for_unmonitored(
            unmonitored=due_rows,
            current=list(self.config.positions),
            mode="from_quote",
            stop_loss_pct=DEFAULT_NEW_BAG_STOP_LOSS_PCT,
            take_profit_pct=DEFAULT_NEW_BAG_TAKE_PROFIT_PCT,
            trailing_stop_pct=DEFAULT_NEW_BAG_TRAILING_STOP_PCT,
            rug_exit=True,
            dispose_after_break_even=False,
        )
        if not created:
            return
        await self.apply_positions(merged, origin=ORIGIN_DEFAULT, touch=created)
        await self.notifier.send(
            severity="info",
            category="policy",
            message=(
                f"Auto-protected {len(created)} bag(s) with SL "
                f"{DEFAULT_NEW_BAG_STOP_LOSS_PCT}% / arm "
                f"+{DEFAULT_NEW_BAG_TAKE_PROFIT_PCT}%. SL live in 10m; rug until then"
            ),
            context={"mints": created, "skipped": skipped, "auto_action": False},
            dedup_key=f"auto-protect:{','.join(created)}",
            dedup_seconds=0,
        )

    async def close(self) -> None:
        await self.http.aclose()
