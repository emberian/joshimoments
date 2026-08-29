"""Gate configuration: TOML, frozen, validated whole. Keep-last-good is the service's job."""

from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass, replace
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any

DREGG_MINT = "XkeTXo1125vz5H9svJpGiw4JvLbN8VmMu9cmMvspump"
OPERATOR_CHAT_ID = 6913902526


class GateConfigError(RuntimeError):
    """Raised when the gate cannot start safely from its configuration."""


@dataclass(frozen=True, slots=True)
class Config:
    telegram_token_file: Path
    helius_key_file: Path
    db_path: Path
    heartbeat_path: Path
    # Where the live screen (dregg_screen.live) writes <utc-day>.jsonl score files.
    # Laptop default; on hbox: /home/hbox/dregg-data/screen/scores.
    screen_scores_dir: Path = Path("state/dregg_screen/scores")
    mint: str = DREGG_MINT
    threshold_tokens: int = 888_888
    # Per-user threshold overrides: tg_user_id (string) -> tokens. For operator
    # testing and comped seats; honored by BOTH /verify and the daily sweep so an
    # override seat is never warned or ejected against the standard line.
    threshold_overrides: dict = dc_field(default_factory=dict)
    operator_chat_id: int = OPERATOR_CHAT_ID
    poll_timeout_seconds: int = 25
    message_max_age_seconds: int = 300
    challenge_ttl_seconds: int = 600
    invite_ttl_seconds: int = 3600
    grace_hours: int = 48
    sweep_hour_utc: int = 14
    sweep_spread_seconds: int = 3600
    sweep_batch_size: int = 10
    screen_rate_per_minute: int = 10

    @property
    def grace_seconds(self) -> int:
        return self.grace_hours * 3600

    @classmethod
    def load(cls, path: Path) -> "Config":
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise GateConfigError(f"gate config unreadable at {path} ({type(exc).__name__})") from None
        except tomllib.TOMLDecodeError as exc:
            raise GateConfigError(f"gate config is not valid TOML: {exc}") from None
        base = path.resolve().parent

        def _path(section: dict[str, Any], key: str, default: str) -> Path:
            value = Path(os.path.expanduser(str(section.get(key, default))))
            return value if value.is_absolute() else base / value

        paths = _mapping(raw.get("paths"), "paths")
        gate = _mapping(raw.get("gate"), "gate")
        cfg = cls(
            telegram_token_file=_path(paths, "telegram_token", "~/.shitcoims-tg"),
            helius_key_file=_path(paths, "helius_key", "~/.helius-key"),
            db_path=_path(paths, "db", "state/dregg_gate/gate.sqlite"),
            heartbeat_path=_path(paths, "heartbeat", "state/dregg_gate/heartbeat.json"),
            screen_scores_dir=_path(paths, "screen_scores", "state/dregg_screen/scores"),
        )
        for key, value in gate.items():
            if (
                not hasattr(cfg, key)
                or key.endswith("_file")
                or key in ("db_path", "heartbeat_path", "screen_scores_dir")
            ):
                raise GateConfigError(f"unknown gate config key {key!r}")
            current = getattr(cfg, key)
            if isinstance(value, bool) or not isinstance(value, type(current)):
                raise GateConfigError(f"gate config key {key!r}: expected {type(current).__name__}")
            cfg = replace(cfg, **{key: value})
        _validate(cfg)
        return cfg


def _mapping(value: object, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise GateConfigError(f"config section {name!r} must be a table")
    return value


def _validate(cfg: Config) -> None:
    if not (32 <= len(cfg.mint) <= 44) or not cfg.mint.isalnum():
        raise GateConfigError("gate.mint must be a base58 mint address")
    if cfg.threshold_tokens <= 0:
        raise GateConfigError("gate.threshold_tokens must be positive")
    for uid, tokens in cfg.threshold_overrides.items():
        if not str(uid).isdigit():
            raise GateConfigError("gate.threshold_overrides keys must be tg user ids")
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens <= 0:
            raise GateConfigError("gate.threshold_overrides values must be positive ints")
    if cfg.operator_chat_id <= 0:
        raise GateConfigError("gate.operator_chat_id must be a positive Telegram user id")
    if not 1 <= cfg.poll_timeout_seconds <= 50:
        raise GateConfigError("gate.poll_timeout_seconds must be between 1 and 50")
    if not 10 <= cfg.message_max_age_seconds <= 3600:
        raise GateConfigError("gate.message_max_age_seconds must be between 10 and 3600")
    if not 60 <= cfg.challenge_ttl_seconds <= 3600:
        raise GateConfigError("gate.challenge_ttl_seconds must be between 60 and 3600")
    if not 60 <= cfg.invite_ttl_seconds <= 86_400:
        raise GateConfigError("gate.invite_ttl_seconds must be between 60 and 86400")
    if not 1 <= cfg.grace_hours <= 24 * 14:
        raise GateConfigError("gate.grace_hours must be between 1 and 336")
    if not 0 <= cfg.sweep_hour_utc <= 23:
        raise GateConfigError("gate.sweep_hour_utc must be between 0 and 23")
    if not 0 <= cfg.sweep_spread_seconds <= 4 * 3600:
        raise GateConfigError("gate.sweep_spread_seconds must be between 0 and 14400")
    if cfg.sweep_batch_size <= 0:
        raise GateConfigError("gate.sweep_batch_size must be positive")
    if not 1 <= cfg.screen_rate_per_minute <= 600:
        raise GateConfigError("gate.screen_rate_per_minute must be between 1 and 600")


def read_secret(path: Path, name: str) -> str:
    """Private-file hygiene shared by the bot token and the Helius key."""

    try:
        metadata = path.lstat()
    except OSError:
        raise GateConfigError(f"{name} file is unavailable at {path}") from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise GateConfigError(f"{name} path must be a regular file, not a symlink")
    if metadata.st_uid != os.getuid():
        raise GateConfigError(f"{name} file must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise GateConfigError(f"{name} file permissions must be 0600 or stricter")
    try:
        secret = path.read_text(encoding="utf-8").strip()
    except OSError:
        raise GateConfigError(f"{name} file could not be read") from None
    if not secret or any(character.isspace() for character in secret):
        raise GateConfigError(f"{name} file is empty or malformed")
    return secret
