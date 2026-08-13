from __future__ import annotations

import os
from pathlib import Path

import pytest

from shitcoims_scout.config import ScoutConfigError, load_scout_config, read_private_token


def test_missing_config_has_documented_error(tmp_path: Path) -> None:
    with pytest.raises(ScoutConfigError, match=r"create intelligence\.yaml with a scout section"):
        load_scout_config(tmp_path / "missing.yaml")


def test_config_defaults_are_disabled_and_loopback(tmp_path: Path) -> None:
    path = tmp_path / "intelligence.yaml"
    path.write_text("{}\n", encoding="utf-8")
    config = load_scout_config(path)

    assert config.enabled is False
    assert config.api_base == "http://127.0.0.1:8788"
    assert config.sentinel_api_base == "http://127.0.0.1:8787"
    assert config.state_file == tmp_path / "intelligence_state/scout.sqlite3"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8788",
        "http://localhost:8788",
        "http://0.0.0.0:8788",
        "http://example.test:8788",
        "http://127.0.0.1:8788/path",
        "http://user:pass@127.0.0.1:8788",
        "http://127.0.0.1",
    ],
)
def test_config_rejects_every_non_exact_loopback_origin(tmp_path: Path, url: str) -> None:
    path = tmp_path / "intelligence.yaml"
    path.write_text(f"scout:\n  api_base: {url!r}\n", encoding="utf-8")
    with pytest.raises(ScoutConfigError, match=r"127\.0\.0\.1"):
        load_scout_config(path)


def test_config_loads_explicit_authentication_ids(tmp_path: Path) -> None:
    path = tmp_path / "intelligence.yaml"
    path.write_text(
        """scout:
  enabled: true
  telegram_bot_token_file: ~/.shitcoims-tg
  telegram_chat_id: '123'
  telegram_user_id: 456
  poll_timeout_seconds: 30
  message_max_age_seconds: 180
""",
        encoding="utf-8",
    )
    config = load_scout_config(path)
    assert config.enabled is True
    assert config.telegram_chat_id == "123"
    assert config.telegram_user_id == "456"
    assert config.poll_timeout_seconds == 30
    assert config.message_max_age_seconds == 180


def test_token_reader_rejects_loose_permissions_and_symlink(tmp_path: Path) -> None:
    secret = tmp_path / "token"
    secret.write_text("123:secret\n", encoding="utf-8")
    os.chmod(secret, 0o644)
    with pytest.raises(ScoutConfigError, match="0600"):
        read_private_token(secret)
    os.chmod(secret, 0o600)
    assert read_private_token(secret) == "123:secret"

    link = tmp_path / "link"
    link.symlink_to(secret)
    with pytest.raises(ScoutConfigError, match="not a symlink"):
        read_private_token(link)
