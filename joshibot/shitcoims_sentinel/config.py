from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from solders.pubkey import Pubkey

from .domain import PositionPolicy
from .policies import PolicyError, policy_from_payload


class ConfigError(ValueError):
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class RpcConfig:
    helius_api_key_file: Path
    http_url_template: str
    websocket_url_template: str
    commitment: str = "confirmed"


@dataclasses.dataclass(frozen=True, slots=True)
class WalletConfig:
    name: str
    secret_key_file: Path


@dataclasses.dataclass(frozen=True, slots=True)
class JupiterConfig:
    api_key_file: Path
    base_url: str
    slippage_bps: int
    max_priority_fee_lamports: int
    excluded_routers: tuple[str, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class ExecutionConfig:
    enabled: bool
    arm_file: Path
    max_attempts: int
    retry_delay_seconds: float
    max_sol_cost_lamports: int


@dataclasses.dataclass(frozen=True, slots=True)
class RugConfig:
    poll_interval_seconds: float
    liquidity_drop_pct: float
    mint_supply_growth_pct: float
    active_mint_liquidity_drop_pct: float
    confirm_delay_seconds: float
    quote_collapse_pct: float


@dataclasses.dataclass(frozen=True, slots=True)
class NotificationConfig:
    telegram_bot_token_file: Path | None
    telegram_chat_id: str | None
    heartbeat_interval_hours: float


@dataclasses.dataclass(frozen=True, slots=True)
class AdvisoryWalletConfig:
    id: str
    label: str
    address: str


@dataclasses.dataclass(frozen=True, slots=True)
class ExperimentConfig:
    wallet_activity_stream: bool
    pump_metadata: bool
    pump_metadata_poll_interval_seconds: float
    max_unmonitored_holdings: int
    max_enrichment_concurrency: int
    advisory_wallets: tuple[AdvisoryWalletConfig, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str
    port: int
    allowed_origins: tuple[str, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class AppConfig:
    config_path: Path
    rpc: RpcConfig
    wallet: WalletConfig
    jupiter: JupiterConfig
    execution: ExecutionConfig
    rug: RugConfig
    notifications: NotificationConfig
    experiments: ExperimentConfig
    server: ServerConfig
    poll_interval_seconds: float
    state_dir: Path
    auto_discover: bool
    positions: tuple[PositionPolicy, ...]

    @property
    def state_file(self) -> Path:
        return self.state_dir / "sentinel-state.json"

    @property
    def events_file(self) -> Path:
        return self.state_dir / "events.jsonl"

    @property
    def trades_file(self) -> Path:
        return self.state_dir / "trades.csv"


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _path(value: Any, *, base: Path) -> Path:
    raw = Path(str(value)).expanduser()
    return raw if raw.is_absolute() else (base / raw).resolve()


def _positive_float(value: Any, name: str) -> float:
    result = float(value)
    if result <= 0:
        raise ConfigError(f"{name} must be positive")
    return result


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be true or false")
    return value


def _official_https_url(value: Any, name: str, *, hostname: str, path_prefix: str) -> str:
    result = str(value).rstrip("/")
    parsed = urlparse(result)
    if (
        parsed.scheme != "https"
        or parsed.hostname != hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith(path_prefix)
    ):
        raise ConfigError(f"{name} must stay on the official {hostname}{path_prefix} origin")
    return result


def _helius_url_template(value: Any, name: str, *, scheme: str) -> str:
    result = str(value)
    parsed = urlparse(result)
    if (
        result.count("{api_key}") != 1
        or parsed.scheme != scheme
        or parsed.hostname != "mainnet.helius-rpc.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
        or parsed.query != "api-key={api_key}"
    ):
        raise ConfigError(
            f"{name} must stay on the official mainnet.helius-rpc.com origin"
        )
    return result


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc
    root = _mapping(raw, "config")
    base = config_path.parent

    rpc_raw = _mapping(root.get("rpc"), "rpc")
    wallet_raw = _mapping(root.get("wallet"), "wallet")
    jupiter_raw = _mapping(root.get("jupiter", {}), "jupiter")
    execution_raw = _mapping(root.get("execution", {}), "execution")
    rug_raw = _mapping(root.get("rug_detector", {}), "rug_detector")
    notifications_raw = _mapping(root.get("notifications", {}), "notifications")
    experiments_raw = _mapping(root.get("experiments", {}), "experiments")
    server_raw = _mapping(root.get("server", {}), "server")

    wallet_name = str(wallet_raw.get("name", ""))
    if wallet_name != "shitcoims":
        raise ConfigError('wallet.name must be exactly "shitcoims"')

    positions: list[PositionPolicy] = []
    seen_mints: set[str] = set()
    for index, item in enumerate(root.get("positions", [])):
        pos = _mapping(item, f"positions[{index}]")
        mint = str(pos.get("mint", "")).strip()
        if not mint or mint in seen_mints:
            raise ConfigError(f"positions[{index}].mint is missing or duplicated")
        seen_mints.add(mint)
        # ONE validator. This file used to carry a second copy of the same rules with a
        # different exception type and its own defaults, so a rule the dashboard refused
        # could still be loaded from YAML — and a typo'd key was silently ignored here,
        # which is how a position ends up running on defaults nobody chose.
        try:
            positions.append(
                policy_from_payload(mint, pos, source=f"{config_path}:positions[{index}]")
            )
        except PolicyError as exc:
            raise ConfigError(f"positions[{index}]: {exc}") from exc

    slippage_bps = int(jupiter_raw.get("slippage_bps", 1500))
    if not 1 <= slippage_bps <= 5000:
        raise ConfigError("jupiter.slippage_bps must be in [1, 5000]")

    host = str(server_raw.get("host", "127.0.0.1"))
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigError("server.host must be loopback; remote binding is intentionally unsupported")

    telegram_file = notifications_raw.get("telegram_bot_token_file")
    telegram_chat_id = (
        str(notifications_raw["telegram_chat_id"]).strip()
        if notifications_raw.get("telegram_chat_id") is not None
        else None
    )
    if telegram_chat_id is not None and not re.fullmatch(r"[1-9][0-9]{0,19}", telegram_chat_id):
        raise ConfigError("notifications.telegram_chat_id must be a private positive numeric ID")
    max_unmonitored = int(experiments_raw.get("max_unmonitored_holdings", 50))
    max_enrichment = int(experiments_raw.get("max_enrichment_concurrency", 6))
    if not 1 <= max_unmonitored <= 500:
        raise ConfigError("experiments.max_unmonitored_holdings must be in [1, 500]")
    if not 1 <= max_enrichment <= 20:
        raise ConfigError("experiments.max_enrichment_concurrency must be in [1, 20]")
    max_sol_cost = int(execution_raw.get("max_sol_cost_lamports", 20_000_000))
    if not 5_000 <= max_sol_cost <= 100_000_000:
        raise ConfigError("execution.max_sol_cost_lamports must be in [5000, 100000000]")
    advisory_wallets: list[AdvisoryWalletConfig] = []
    seen_wallet_ids: set[str] = set()
    for index, item in enumerate(experiments_raw.get("advisory_wallets", [])):
        entry = _mapping(item, f"experiments.advisory_wallets[{index}]")
        wallet_id = str(entry.get("id", "")).strip()
        label = str(entry.get("label", "")).strip()
        address = str(entry.get("address", "")).strip()
        if not re.fullmatch(r"[a-z0-9_]{1,40}", wallet_id) or wallet_id in seen_wallet_ids:
            raise ConfigError(
                f"experiments.advisory_wallets[{index}].id must be unique snake_case"
            )
        if not label or len(label) > 80:
            raise ConfigError(f"experiments.advisory_wallets[{index}].label is invalid")
        try:
            canonical_address = str(Pubkey.from_string(address))
        except Exception as exc:
            raise ConfigError(
                f"experiments.advisory_wallets[{index}].address is not a Solana public key"
            ) from exc
        seen_wallet_ids.add(wallet_id)
        advisory_wallets.append(AdvisoryWalletConfig(wallet_id, label, canonical_address))
    return AppConfig(
        config_path=config_path,
        rpc=RpcConfig(
            helius_api_key_file=_path(rpc_raw.get("helius_api_key_file", "~/.helius-key"), base=base),
            http_url_template=_helius_url_template(
                rpc_raw.get(
                    "http_url_template",
                    "https://mainnet.helius-rpc.com/?api-key={api_key}",
                ),
                "rpc.http_url_template",
                scheme="https",
            ),
            websocket_url_template=_helius_url_template(
                rpc_raw.get(
                    "websocket_url_template",
                    "wss://mainnet.helius-rpc.com/?api-key={api_key}",
                ),
                "rpc.websocket_url_template",
                scheme="wss",
            ),
            commitment=str(rpc_raw.get("commitment", "confirmed")),
        ),
        wallet=WalletConfig(
            name=wallet_name,
            secret_key_file=_path(wallet_raw.get("secret_key_file", "~/.shitcoims-wallet"), base=base),
        ),
        jupiter=JupiterConfig(
            api_key_file=_path(
                jupiter_raw.get("api_key_file", "~/.jup-shitcoims"), base=base
            ),
            base_url=_official_https_url(
                jupiter_raw.get("base_url", "https://api.jup.ag/swap/v2"),
                "jupiter.base_url",
                hostname="api.jup.ag",
                path_prefix="/swap/v2",
            ),
            slippage_bps=slippage_bps,
            max_priority_fee_lamports=int(
                jupiter_raw.get("max_priority_fee_lamports", 5_000_000)
            ),
            excluded_routers=tuple(jupiter_raw.get("excluded_routers", ["jupiterz", "dflow", "okx"])),
        ),
        execution=ExecutionConfig(
            enabled=_bool(execution_raw.get("enabled", False), "execution.enabled"),
            arm_file=_path(execution_raw.get("arm_file", "./state/LIVE_ARMED"), base=base),
            max_attempts=int(execution_raw.get("max_attempts", 3)),
            retry_delay_seconds=_positive_float(
                execution_raw.get("retry_delay_seconds", 2), "execution.retry_delay_seconds"
            ),
            max_sol_cost_lamports=max_sol_cost,
        ),
        rug=RugConfig(
            poll_interval_seconds=_positive_float(
                rug_raw.get("poll_interval_seconds", 30), "rug_detector.poll_interval_seconds"
            ),
            liquidity_drop_pct=float(rug_raw.get("liquidity_drop_pct", 40)),
            mint_supply_growth_pct=float(rug_raw.get("mint_supply_growth_pct", 5)),
            active_mint_liquidity_drop_pct=float(
                rug_raw.get("active_mint_liquidity_drop_pct", 20)
            ),
            confirm_delay_seconds=_positive_float(
                rug_raw.get("confirm_delay_seconds", 0.75), "rug_detector.confirm_delay_seconds"
            ),
            quote_collapse_pct=float(rug_raw.get("quote_collapse_pct", 20)),
        ),
        notifications=NotificationConfig(
            telegram_bot_token_file=(
                _path(telegram_file, base=base)
                if telegram_file
                else _path("~/.shitcoims-tg", base=base)
            ),
            telegram_chat_id=telegram_chat_id,
            heartbeat_interval_hours=_positive_float(
                notifications_raw.get("heartbeat_interval_hours", 6),
                "notifications.heartbeat_interval_hours",
            ),
        ),
        experiments=ExperimentConfig(
            wallet_activity_stream=_bool(
                experiments_raw.get("wallet_activity_stream", True),
                "experiments.wallet_activity_stream",
            ),
            pump_metadata=_bool(
                experiments_raw.get("pump_metadata", True),
                "experiments.pump_metadata",
            ),
            pump_metadata_poll_interval_seconds=_positive_float(
                experiments_raw.get("pump_metadata_poll_interval_seconds", 60),
                "experiments.pump_metadata_poll_interval_seconds",
            ),
            max_unmonitored_holdings=max_unmonitored,
            max_enrichment_concurrency=max_enrichment,
            advisory_wallets=tuple(advisory_wallets),
        ),
        server=ServerConfig(
            host=host,
            port=int(server_raw.get("port", 8787)),
            allowed_origins=tuple(
                server_raw.get(
                    "allowed_origins",
                    ["http://localhost:3000", "http://127.0.0.1:3000"],
                )
            ),
        ),
        poll_interval_seconds=_positive_float(
            root.get("poll_interval_seconds", 10), "poll_interval_seconds"
        ),
        state_dir=_path(root.get("state_dir", "./state"), base=base),
        auto_discover=_bool(root.get("auto_discover", True), "auto_discover"),
        positions=tuple(positions),
    )
