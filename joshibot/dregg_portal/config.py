"""Portal service configuration: TOML, frozen, validated whole. Same shape as the gate's.

WHAT IS DELIBERATELY ABSENT: the mint, the decimals, and the threshold. Those are FACTS
ABOUT THE GATE, and the gate ships them in the roster it publishes. A copy here would be
a second place they could be wrong, and the failure mode of a threshold that disagrees
with the bot's is a person told they hold enough who then cannot get into the group.
Read them off ``roster.json`` or do not have them.

Equally absent: any provider key, any bot token, any upstream URL. The service on the
anchor cannot reach a chain provider because it has nothing to reach one with, and the
config schema is where that is enforced — an unknown key is a refusal, so a future
``helius_key`` cannot be quietly added to a deployed box's TOML.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


class PortalConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Config:
    # Loopback only, always. Caddy is the front door; a public bind here would be a
    # second one with no TLS and none of the headers the Caddyfile argues for.
    bind_host: str = "127.0.0.1"
    bind_port: int = 8791
    # Where the pushed bundle lands. NOT under /var/www: deploy.sh unlinks every file
    # under /var/www that dregg-infra does not declare, and these are generated.
    artifacts_dir: Path = Path("/var/lib/dregg-portal/artifacts")
    state_db: Path = Path("/var/lib/dregg-portal/portal.sqlite")
    session_key_file: Path = Path("/var/lib/dregg-portal/keys/session.key")
    heartbeat_path: Path = Path("/var/lib/dregg-portal/heartbeat.json")
    # 12h bounds how long a stolen cookie is useful. It does NOT bound how long a lost
    # seat keeps working — the roster does that, on every request.
    session_ttl_seconds: int = 12 * 3600
    challenge_ttl_seconds: int = 600
    # The base path this service is mounted at, so links it renders match the Caddy block.
    base_path: str = "/portal"
    nonce_per_hour_per_ip: int = 12
    nonce_per_hour_per_wallet: int = 6
    session_per_hour_per_ip: int = 20
    reads_per_hour_per_ip: int = 600
    max_body_bytes: int = 4096

    @classmethod
    def load(cls, path: Path) -> "Config":
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise PortalConfigError(f"portal config unreadable at {path} ({type(exc).__name__})") from None
        except tomllib.TOMLDecodeError as exc:
            raise PortalConfigError(f"portal config is not valid TOML: {exc}") from None
        base = path.resolve().parent

        def _path(section: dict[str, Any], key: str, default: Path) -> Path:
            value = Path(os.path.expanduser(str(section.get(key, default))))
            return value if value.is_absolute() else base / value

        paths = _mapping(raw.get("paths"), "paths")
        service = _mapping(raw.get("service"), "service")
        cfg = cls(
            artifacts_dir=_path(paths, "artifacts", cls.artifacts_dir),
            state_db=_path(paths, "state_db", cls.state_db),
            session_key_file=_path(paths, "session_key", cls.session_key_file),
            heartbeat_path=_path(paths, "heartbeat", cls.heartbeat_path),
        )
        path_keys = {"artifacts_dir", "state_db", "session_key_file", "heartbeat_path"}
        for key, value in service.items():
            if not hasattr(cfg, key) or key in path_keys:
                raise PortalConfigError(f"unknown portal config key {key!r}")
            current = getattr(cfg, key)
            if isinstance(value, bool) or not isinstance(value, type(current)):
                raise PortalConfigError(f"portal config key {key!r}: expected {type(current).__name__}")
            cfg = replace(cfg, **{key: value})
        _validate(cfg)
        return cfg


def _mapping(value: object, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PortalConfigError(f"config section {name!r} must be a table")
    return value


def _validate(cfg: Config) -> None:
    if cfg.bind_host not in ("127.0.0.1", "::1", "localhost"):
        raise PortalConfigError(
            "service.bind_host must be loopback — Caddy is the only front door on this box"
        )
    if not 1 <= cfg.bind_port <= 65535:
        raise PortalConfigError("service.bind_port must be a valid port")
    if not cfg.base_path.startswith("/") or cfg.base_path.endswith("/"):
        raise PortalConfigError("service.base_path must start with / and not end with one")
    if not 300 <= cfg.session_ttl_seconds <= 7 * 86_400:
        raise PortalConfigError("service.session_ttl_seconds must be between 300 and 604800")
    if not 60 <= cfg.challenge_ttl_seconds <= 3600:
        raise PortalConfigError("service.challenge_ttl_seconds must be between 60 and 3600")
    for key in (
        "nonce_per_hour_per_ip",
        "nonce_per_hour_per_wallet",
        "session_per_hour_per_ip",
        "reads_per_hour_per_ip",
    ):
        if getattr(cfg, key) <= 0:
            raise PortalConfigError(f"service.{key} must be positive")
    if not 256 <= cfg.max_body_bytes <= 65_536:
        raise PortalConfigError("service.max_body_bytes must be between 256 and 65536")
