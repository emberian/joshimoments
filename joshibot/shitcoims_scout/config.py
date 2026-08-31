from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml


class ScoutConfigError(RuntimeError):
    """Raised when Scout cannot start safely from its configuration."""


@dataclass(frozen=True)
class ScoutConfig:
    config_path: Path
    enabled: bool
    telegram_bot_token_file: Path | None
    telegram_chat_id: str | None
    telegram_user_id: str | None
    state_file: Path
    api_base: str
    sentinel_api_base: str
    poll_timeout_seconds: int
    message_max_age_seconds: int


def _mapping(value: object, name: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ScoutConfigError(f"{name} must be a mapping")
    return value


def _integer(value: object, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ScoutConfigError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ScoutConfigError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ScoutConfigError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _identifier(value: object, name: str) -> str | None:
    if value is None or value == "":
        return None
    result = str(value)
    if not result.isascii() or not result.lstrip("-").isdigit():
        raise ScoutConfigError(f"{name} must be a Telegram numeric ID")
    return result


def _path(value: object, *, base: Path) -> Path | None:
    if value is None or value == "":
        return None
    path = Path(os.path.expanduser(str(value)))
    return path if path.is_absolute() else (base / path).resolve()


def _loopback_base(value: object, name: str) -> str:
    raw = str(value).rstrip("/")
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or parsed.port is None
    ):
        raise ScoutConfigError(f"{name} must be an explicit http://127.0.0.1:PORT origin with no path")
    return raw


def load_scout_config(path: str | Path = "intelligence.yaml") -> ScoutConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ScoutConfigError(
            f"Scout configuration not found at {config_path}; create intelligence.yaml "
            "with a scout section before starting the gateway"
        )
    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ScoutConfigError(f"could not read Scout configuration ({type(exc).__name__})") from None
    root = _mapping(document, "intelligence.yaml")
    raw = _mapping(root.get("scout"), "scout")
    base = config_path.parent
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ScoutConfigError("scout.enabled must be true or false")
    return ScoutConfig(
        config_path=config_path,
        enabled=enabled,
        telegram_bot_token_file=_path(raw.get("telegram_bot_token_file"), base=base),
        telegram_chat_id=_identifier(raw.get("telegram_chat_id"), "scout.telegram_chat_id"),
        telegram_user_id=_identifier(raw.get("telegram_user_id"), "scout.telegram_user_id"),
        state_file=_path(raw.get("state_file", "./intelligence_state/scout.sqlite3"), base=base)
        or (base / "intelligence_state/scout.sqlite3"),
        api_base=_loopback_base(raw.get("api_base", "http://127.0.0.1:8788"), "scout.api_base"),
        sentinel_api_base=_loopback_base(
            raw.get("sentinel_api_base", "http://127.0.0.1:8787"),
            "scout.sentinel_api_base",
        ),
        poll_timeout_seconds=_integer(
            raw.get("poll_timeout_seconds", 25),
            "scout.poll_timeout_seconds",
            minimum=1,
            maximum=50,
        ),
        message_max_age_seconds=_integer(
            raw.get("message_max_age_seconds", 120),
            "scout.message_max_age_seconds",
            minimum=10,
            maximum=3600,
        ),
    )


def read_private_token(path: Path | None) -> str:
    if path is None:
        raise ScoutConfigError("scout.telegram_bot_token_file is required")
    try:
        metadata = path.lstat()
    except OSError:
        raise ScoutConfigError(f"Telegram bot token file is unavailable at {path}") from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ScoutConfigError("Telegram bot token path must be a regular file, not a symlink")
    if metadata.st_uid != os.getuid():
        raise ScoutConfigError("Telegram bot token file must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ScoutConfigError("Telegram bot token file permissions must be 0600 or stricter")
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        raise ScoutConfigError("Telegram bot token file could not be read") from None
    if not token or any(character.isspace() for character in token):
        raise ScoutConfigError("Telegram bot token file is empty or malformed")
    return token
