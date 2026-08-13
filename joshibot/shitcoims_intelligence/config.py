"""Strict configuration for the isolated, read-only intelligence service."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from shitcoims_intelligence.adapters.x_apify import PINNED_ACTOR, normalize_actor_id

CONFIG_VERSION = 1
DEFAULT_MAX_DISK_BYTES = 5 * 1024**3
DEFAULT_WARN_DISK_BYTES = 4 * 1024**3


class IntelligenceConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    path: Path
    journal_mode: str
    busy_timeout_ms: int


@dataclass(frozen=True, slots=True)
class IngestionConfig:
    queue_capacity: int
    batch_size: int


@dataclass(frozen=True, slots=True)
class RetentionConfig:
    observation_days: int
    raw_blob_days: int
    max_observations: int
    max_disk_bytes: int
    warn_disk_bytes: int
    prune_batch_size: int


@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str
    port: int
    allowed_origins: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HeliusConfig:
    api_key_file: Path
    http_url_template: str
    websocket_url_template: str
    daily_credit_budget: int
    monthly_credit_budget: int
    history_pages_per_run: int
    history_transactions_per_run: int
    history_page_size: int
    watchlist_max_addresses: int
    keepalive_seconds: int
    reconnect_seconds: float
    seed_wallets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScoutConfig:
    enabled: bool
    telegram_bot_token_file: Path | None
    telegram_chat_id: str | None
    telegram_user_id: str | None
    state_file: Path
    api_base: str
    sentinel_api_base: str
    poll_timeout_seconds: int
    message_max_age_seconds: int


@dataclass(frozen=True, slots=True)
class ClaudeKolAdapterConfig:
    enabled: bool


@dataclass(frozen=True, slots=True)
class KagiAdapterConfig:
    enabled: bool
    env_file: Path
    key_name: str


@dataclass(frozen=True, slots=True)
class PumpCalloutsAdapterConfig:
    enabled: bool
    endpoint: str | None
    schema_version: str | None
    credential_env_file: Path | None
    credential_key_name: str


@dataclass(frozen=True, slots=True)
class KolWatchConfig:
    """One X account to follow. Handle is the identity; wallet is optional."""

    handle: str
    label: str
    wallet: str | None
    follow_replies: bool
    max_items: int
    notes: str


@dataclass(frozen=True, slots=True)
class XApifyAdapterConfig:
    enabled: bool
    token_file: Path
    actor_id: str
    max_items_per_query: int
    poll_interval_seconds: int
    max_items_per_day: int
    queries: tuple[str, ...]
    kols: tuple[KolWatchConfig, ...]
    kol_thread_limit: int


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    claudekol: ClaudeKolAdapterConfig
    kagi: KagiAdapterConfig
    pump_callouts: PumpCalloutsAdapterConfig
    x_apify: XApifyAdapterConfig


@dataclass(frozen=True, slots=True)
class IntelligenceConfig:
    config_path: Path
    version: int
    database: DatabaseConfig
    ingestion: IngestionConfig
    retention: RetentionConfig
    server: ServerConfig
    helius: HeliusConfig
    scout: ScoutConfig
    adapters: AdapterConfig


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise IntelligenceConfigError(f"{name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise IntelligenceConfigError(f"{name} keys must be strings")
    return value


def _only(mapping: dict[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise IntelligenceConfigError(f"{name} has unknown keys: {', '.join(unknown)}")


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise IntelligenceConfigError(f"{name} must be true or false")
    return value


def _int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntelligenceConfigError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise IntelligenceConfigError(f"{name} must be within [{minimum}, {maximum}]")
    return value


def _float(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise IntelligenceConfigError(f"{name} must be a number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise IntelligenceConfigError(f"{name} must be within [{minimum}, {maximum}]")
    return result


def _path(value: Any, base: Path, name: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise IntelligenceConfigError(f"{name} must be a nonempty path")
    raw = Path(value).expanduser()
    return raw.resolve() if raw.is_absolute() else (base / raw).resolve()


def _optional_path(value: Any, base: Path, name: str) -> Path | None:
    return None if value is None or value == "" else _path(value, base, name)


def _telegram_id(value: Any, name: str) -> str | None:
    if value is None or value == "":
        return None
    result = str(value)
    if not re.fullmatch(r"-?[1-9][0-9]{0,19}", result):
        raise IntelligenceConfigError(f"{name} must be a numeric Telegram ID")
    return result


def _loopback_origin(value: Any, name: str) -> str:
    result = str(value).rstrip("/")
    parsed = urlsplit(result)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise IntelligenceConfigError(f"{name} must be an explicit loopback HTTP origin")
    return result


def _helius_template(value: Any, name: str, scheme: str) -> str:
    result = str(value)
    parsed = urlsplit(result)
    if (
        result.count("{api_key}") != 1
        or parsed.scheme != scheme
        or parsed.hostname != "mainnet.helius-rpc.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query != "api-key={api_key}"
        or parsed.fragment
    ):
        raise IntelligenceConfigError(
            f"{name} must use the official mainnet.helius-rpc.com API-key template"
        )
    return result


def _protect_runtime_path(path: Path, base: Path, name: str) -> Path:
    sentinel_state = (base / "state").resolve()
    if path == sentinel_state or sentinel_state in path.parents:
        raise IntelligenceConfigError(f"{name} must not use Sentinel's state directory")
    if path in {(base / "config.yaml").resolve(), (base / "intelligence.yaml").resolve()}:
        raise IntelligenceConfigError(f"{name} must not overwrite a configuration file")
    return path


def load_intelligence_config(path: str | Path = "intelligence.yaml") -> IntelligenceConfig:
    config_path = Path(path).expanduser().resolve()
    try:
        if config_path.stat().st_size > 512 * 1024:
            raise IntelligenceConfigError("intelligence config exceeds 512 KiB")
        document = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise IntelligenceConfigError(f"intelligence config not found: {config_path}") from exc
    except (OSError, yaml.YAMLError) as exc:
        raise IntelligenceConfigError(f"cannot read intelligence config: {type(exc).__name__}") from None

    root = _mapping(document, "intelligence.yaml")
    _only(
        root,
        {"version", "database", "ingestion", "retention", "server", "helius", "scout", "adapters"},
        "intelligence.yaml",
    )
    version = _int(root.get("version", CONFIG_VERSION), "version", 1, CONFIG_VERSION)
    if version != CONFIG_VERSION:
        raise IntelligenceConfigError(f"unsupported intelligence config version: {version}")
    base = config_path.parent

    database = _mapping(root.get("database"), "database")
    _only(database, {"path", "journal_mode", "busy_timeout_ms"}, "database")
    journal_mode = str(database.get("journal_mode", "DELETE")).upper()
    if journal_mode not in {"DELETE", "TRUNCATE"}:
        raise IntelligenceConfigError("database.journal_mode must be DELETE or TRUNCATE; WAL is forbidden")
    database_path = _protect_runtime_path(
        _path(database.get("path", "./intelligence_state/intelligence.sqlite3"), base, "database.path"),
        base,
        "database.path",
    )

    ingestion = _mapping(root.get("ingestion"), "ingestion")
    _only(ingestion, {"queue_capacity", "batch_size"}, "ingestion")

    retention = _mapping(root.get("retention"), "retention")
    _only(
        retention,
        {
            "observation_days",
            "raw_blob_days",
            "max_observations",
            "max_disk_bytes",
            "warn_disk_bytes",
            "prune_batch_size",
        },
        "retention",
    )
    max_disk_bytes = _int(
        retention.get("max_disk_bytes", DEFAULT_MAX_DISK_BYTES),
        "retention.max_disk_bytes",
        64 * 1024**2,
        1024**4,
    )
    warn_disk_bytes = _int(
        retention.get("warn_disk_bytes", DEFAULT_WARN_DISK_BYTES),
        "retention.warn_disk_bytes",
        32 * 1024**2,
        max_disk_bytes,
    )
    if warn_disk_bytes >= max_disk_bytes:
        raise IntelligenceConfigError("retention.warn_disk_bytes must be below max_disk_bytes")

    server = _mapping(root.get("server"), "server")
    _only(server, {"host", "port", "allowed_origins"}, "server")
    server_host = str(server.get("host", "127.0.0.1"))
    if server_host not in {"127.0.0.1", "localhost", "::1"}:
        raise IntelligenceConfigError("server.host must be loopback")
    origins = server.get(
        "allowed_origins",
        [
            "http://127.0.0.1:8787",
            "http://localhost:8787",
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ],
    )
    if not isinstance(origins, list) or not origins or len(origins) > 10:
        raise IntelligenceConfigError("server.allowed_origins must be a nonempty bounded list")
    allowed_origins = tuple(
        _loopback_origin(item, f"server.allowed_origins[{index}]")
        for index, item in enumerate(origins)
    )

    helius = _mapping(root.get("helius"), "helius")
    _only(
        helius,
        {
            "api_key_file",
            "http_url_template",
            "websocket_url_template",
            "daily_credit_budget",
            "monthly_credit_budget",
            "history_pages_per_run",
            "history_transactions_per_run",
            "history_page_size",
            "watchlist_max_addresses",
            "keepalive_seconds",
            "reconnect_seconds",
            "seed_wallets",
        },
        "helius",
    )
    daily_credit_budget = _int(
        helius.get("daily_credit_budget", 10_000), "helius.daily_credit_budget", 1, 100_000_000
    )
    monthly_credit_budget = _int(
        helius.get("monthly_credit_budget", 300_000),
        "helius.monthly_credit_budget",
        daily_credit_budget,
        2_000_000_000,
    )
    seed_wallets_raw = helius.get("seed_wallets", [])
    if seed_wallets_raw is None:
        seed_wallets_raw = []
    if not isinstance(seed_wallets_raw, list) or len(seed_wallets_raw) > 20:
        raise IntelligenceConfigError("helius.seed_wallets must be a list of at most 20 addresses")
    wallet_re = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    helius_seed_wallets: list[str] = []
    seen_seeds: set[str] = set()
    for index, raw_wallet in enumerate(seed_wallets_raw):
        if not isinstance(raw_wallet, str) or not wallet_re.fullmatch(raw_wallet.strip()):
            raise IntelligenceConfigError(
                f"helius.seed_wallets[{index}] must be a Solana address"
            )
        seed = raw_wallet.strip()
        if seed in seen_seeds:
            raise IntelligenceConfigError(f"duplicate helius.seed_wallets entry: {seed}")
        seen_seeds.add(seed)
        helius_seed_wallets.append(seed)

    scout = _mapping(root.get("scout"), "scout")
    _only(
        scout,
        {
            "enabled",
            "telegram_bot_token_file",
            "telegram_chat_id",
            "telegram_user_id",
            "state_file",
            "api_base",
            "sentinel_api_base",
            "poll_timeout_seconds",
            "message_max_age_seconds",
        },
        "scout",
    )
    scout_state = _protect_runtime_path(
        _path(scout.get("state_file", "./intelligence_state/scout.sqlite3"), base, "scout.state_file"),
        base,
        "scout.state_file",
    )

    adapters = _mapping(root.get("adapters"), "adapters")
    _only(adapters, {"claudekol", "kagi", "pump_callouts", "x_apify"}, "adapters")
    claudekol = _mapping(adapters.get("claudekol"), "adapters.claudekol")
    _only(claudekol, {"enabled"}, "adapters.claudekol")
    kagi = _mapping(adapters.get("kagi"), "adapters.kagi")
    _only(kagi, {"enabled", "env_file", "key_name"}, "adapters.kagi")
    key_name = str(kagi.get("key_name", "KAGI_API_KEY"))
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key_name):
        raise IntelligenceConfigError("adapters.kagi.key_name must be an environment variable name")
    pump = _mapping(adapters.get("pump_callouts"), "adapters.pump_callouts")
    _only(
        pump,
        {"enabled", "endpoint", "schema_version", "credential_env_file", "credential_key_name"},
        "adapters.pump_callouts",
    )
    pump_enabled = _bool(pump.get("enabled", False), "adapters.pump_callouts.enabled")
    pump_endpoint = pump.get("endpoint")
    pump_schema = pump.get("schema_version")
    if pump_endpoint not in {None, "https://advanced-api-v2.pump.fun/callouts"}:
        raise IntelligenceConfigError("adapters.pump_callouts.endpoint is not the pinned experiment endpoint")
    if pump_schema not in {None, "pump-advanced-callouts-v0"}:
        raise IntelligenceConfigError("adapters.pump_callouts.schema_version is not recognized")
    if pump_enabled and (pump_endpoint is None or pump_schema is None):
        raise IntelligenceConfigError("enabled pump_callouts requires the pinned endpoint and schema")
    pump_key_name = str(pump.get("credential_key_name", "PUMP_CALLOUTS_TOKEN"))
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", pump_key_name):
        raise IntelligenceConfigError(
            "adapters.pump_callouts.credential_key_name must be an environment variable name"
        )

    x_apify = _mapping(adapters.get("x_apify"), "adapters.x_apify")
    _only(
        x_apify,
        {
            "enabled",
            "token_file",
            "actor_id",
            "max_items_per_query",
            "poll_interval_seconds",
            "max_items_per_day",
            "queries",
            "kols",
            "kol_thread_limit",
        },
        "adapters.x_apify",
    )
    x_actor = normalize_actor_id(str(x_apify.get("actor_id", PINNED_ACTOR)))
    if x_actor != PINNED_ACTOR:
        raise IntelligenceConfigError("adapters.x_apify.actor_id is not the pinned search actor")
    x_max_items = _int(
        x_apify.get("max_items_per_query", 8), "adapters.x_apify.max_items_per_query", 1, 100
    )
    x_queries_raw = x_apify.get("queries", ["pump.fun"] if x_apify.get("enabled") else [])
    if x_queries_raw is None:
        x_queries_raw = []
    if not isinstance(x_queries_raw, list) or len(x_queries_raw) > 8:
        raise IntelligenceConfigError("adapters.x_apify.queries must be a list of at most 8 queries")
    x_queries: list[str] = []
    for index, raw_query in enumerate(x_queries_raw):
        if not isinstance(raw_query, str):
            raise IntelligenceConfigError(f"adapters.x_apify.queries[{index}] must be a string")
        query = " ".join(raw_query.split())
        if not 1 <= len(query) <= 512:
            raise IntelligenceConfigError(
                f"adapters.x_apify.queries[{index}] must be 1-512 characters"
            )
        x_queries.append(query)

    handle_re = re.compile(r"^[A-Za-z0-9_]{1,15}$")
    wallet_re = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    kols_raw = x_apify.get("kols", [])
    if kols_raw is None:
        kols_raw = []
    if not isinstance(kols_raw, list) or len(kols_raw) > 40:
        raise IntelligenceConfigError("adapters.x_apify.kols must be a list of at most 40 watches")
    kols: list[KolWatchConfig] = []
    seen_handles: set[str] = set()
    for index, raw_kol in enumerate(kols_raw):
        item = _mapping(raw_kol, f"adapters.x_apify.kols[{index}]")
        _only(
            item,
            {"handle", "label", "wallet", "follow_replies", "max_items", "notes"},
            f"adapters.x_apify.kols[{index}]",
        )
        handle = str(item.get("handle", "")).strip().lstrip("@")
        if not handle_re.fullmatch(handle):
            raise IntelligenceConfigError(
                f"adapters.x_apify.kols[{index}].handle must be a 1-15 char X username"
            )
        folded = handle.lower()
        if folded in seen_handles:
            raise IntelligenceConfigError(f"duplicate KOL handle: {handle}")
        seen_handles.add(folded)
        label = str(item.get("label", handle)).strip()
        if not label or len(label) > 80:
            raise IntelligenceConfigError(f"adapters.x_apify.kols[{index}].label is invalid")
        wallet_raw = item.get("wallet")
        wallet = None if wallet_raw in {None, ""} else str(wallet_raw).strip()
        if wallet is not None and not wallet_re.fullmatch(wallet):
            raise IntelligenceConfigError(
                f"adapters.x_apify.kols[{index}].wallet must be a Solana address"
            )
        notes = str(item.get("notes", "")).strip()
        if len(notes) > 240:
            raise IntelligenceConfigError(f"adapters.x_apify.kols[{index}].notes is too long")
        kols.append(
            KolWatchConfig(
                handle=handle,
                label=label,
                wallet=wallet,
                follow_replies=_bool(
                    item.get("follow_replies", False),
                    f"adapters.x_apify.kols[{index}].follow_replies",
                ),
                max_items=_int(
                    item.get("max_items", 8),
                    f"adapters.x_apify.kols[{index}].max_items",
                    1,
                    40,
                ),
                notes=notes,
            )
        )

    return IntelligenceConfig(
        config_path=config_path,
        version=version,
        database=DatabaseConfig(
            path=database_path,
            journal_mode=journal_mode,
            busy_timeout_ms=_int(
                database.get("busy_timeout_ms", 5_000), "database.busy_timeout_ms", 100, 60_000
            ),
        ),
        ingestion=IngestionConfig(
            queue_capacity=_int(
                ingestion.get("queue_capacity", 10_000), "ingestion.queue_capacity", 100, 1_000_000
            ),
            batch_size=_int(ingestion.get("batch_size", 250), "ingestion.batch_size", 1, 10_000),
        ),
        retention=RetentionConfig(
            observation_days=_int(
                retention.get("observation_days", 180), "retention.observation_days", 1, 3_650
            ),
            raw_blob_days=_int(
                retention.get("raw_blob_days", 30), "retention.raw_blob_days", 1, 365
            ),
            max_observations=_int(
                retention.get("max_observations", 5_000_000),
                "retention.max_observations",
                1_000,
                1_000_000_000,
            ),
            max_disk_bytes=max_disk_bytes,
            warn_disk_bytes=warn_disk_bytes,
            prune_batch_size=_int(
                retention.get("prune_batch_size", 10_000),
                "retention.prune_batch_size",
                100,
                1_000_000,
            ),
        ),
        server=ServerConfig(
            host=server_host,
            port=_int(server.get("port", 8788), "server.port", 1_024, 65_535),
            allowed_origins=allowed_origins,
        ),
        helius=HeliusConfig(
            api_key_file=_path(helius.get("api_key_file", "~/.helius-key"), base, "helius.api_key_file"),
            http_url_template=_helius_template(
                helius.get(
                    "http_url_template", "https://mainnet.helius-rpc.com/?api-key={api_key}"
                ),
                "helius.http_url_template",
                "https",
            ),
            websocket_url_template=_helius_template(
                helius.get(
                    "websocket_url_template", "wss://mainnet.helius-rpc.com/?api-key={api_key}"
                ),
                "helius.websocket_url_template",
                "wss",
            ),
            daily_credit_budget=daily_credit_budget,
            monthly_credit_budget=monthly_credit_budget,
            history_pages_per_run=_int(
                helius.get("history_pages_per_run", 10), "helius.history_pages_per_run", 1, 10_000
            ),
            history_transactions_per_run=_int(
                helius.get("history_transactions_per_run", 1_000),
                "helius.history_transactions_per_run",
                1,
                1_000_000,
            ),
            history_page_size=_int(
                helius.get("history_page_size", 100), "helius.history_page_size", 1, 100
            ),
            watchlist_max_addresses=_int(
                helius.get("watchlist_max_addresses", 2_000),
                "helius.watchlist_max_addresses",
                1,
                50_000,
            ),
            keepalive_seconds=_int(
                helius.get("keepalive_seconds", 30), "helius.keepalive_seconds", 5, 300
            ),
            reconnect_seconds=_float(
                helius.get("reconnect_seconds", 1), "helius.reconnect_seconds", 0.1, 300
            ),
            seed_wallets=tuple(helius_seed_wallets),
        ),
        scout=ScoutConfig(
            enabled=_bool(scout.get("enabled", False), "scout.enabled"),
            telegram_bot_token_file=_optional_path(
                scout.get("telegram_bot_token_file"), base, "scout.telegram_bot_token_file"
            ),
            telegram_chat_id=_telegram_id(scout.get("telegram_chat_id"), "scout.telegram_chat_id"),
            telegram_user_id=_telegram_id(scout.get("telegram_user_id"), "scout.telegram_user_id"),
            state_file=scout_state,
            api_base=_loopback_origin(
                scout.get("api_base", "http://127.0.0.1:8788"), "scout.api_base"
            ),
            sentinel_api_base=_loopback_origin(
                scout.get("sentinel_api_base", "http://127.0.0.1:8787"),
                "scout.sentinel_api_base",
            ),
            poll_timeout_seconds=_int(
                scout.get("poll_timeout_seconds", 25), "scout.poll_timeout_seconds", 1, 50
            ),
            message_max_age_seconds=_int(
                scout.get("message_max_age_seconds", 120),
                "scout.message_max_age_seconds",
                10,
                3_600,
            ),
        ),
        adapters=AdapterConfig(
            claudekol=ClaudeKolAdapterConfig(
                enabled=_bool(claudekol.get("enabled", False), "adapters.claudekol.enabled")
            ),
            kagi=KagiAdapterConfig(
                enabled=_bool(kagi.get("enabled", False), "adapters.kagi.enabled"),
                env_file=_path(
                    kagi.get("env_file", "~/dev/allgame/.env"), base, "adapters.kagi.env_file"
                ),
                key_name=key_name,
            ),
            pump_callouts=PumpCalloutsAdapterConfig(
                enabled=pump_enabled,
                endpoint=pump_endpoint,
                schema_version=pump_schema,
                credential_env_file=_optional_path(
                    pump.get("credential_env_file"),
                    base,
                    "adapters.pump_callouts.credential_env_file",
                ),
                credential_key_name=pump_key_name,
            ),
            x_apify=XApifyAdapterConfig(
                enabled=_bool(x_apify.get("enabled", False), "adapters.x_apify.enabled"),
                token_file=_path(
                    x_apify.get("token_file", "~/.apify-token"),
                    base,
                    "adapters.x_apify.token_file",
                ),
                actor_id=x_actor,
                max_items_per_query=x_max_items,
                poll_interval_seconds=_int(
                    x_apify.get("poll_interval_seconds", 1_800),
                    "adapters.x_apify.poll_interval_seconds",
                    120,
                    86_400,
                ),
                max_items_per_day=_int(
                    x_apify.get("max_items_per_day", 200),
                    "adapters.x_apify.max_items_per_day",
                    1,
                    5_000,
                ),
                queries=tuple(x_queries),
                kols=tuple(kols),
                kol_thread_limit=_int(
                    x_apify.get("kol_thread_limit", 3),
                    "adapters.x_apify.kol_thread_limit",
                    0,
                    8,
                ),
            ),
        ),
    )
