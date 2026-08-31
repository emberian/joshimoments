import os
from pathlib import Path

import pytest
from solders.keypair import Keypair

from shitcoims_sentinel.config import ConfigError, load_config
from shitcoims_sentinel.secrets import SecretError, load_shitcoims_keypair, read_secret_file

MINT = "5jUwEEKMawc1q1GCEKLgCYA77jbGfVvjz21nEpJrpump"


def write_config(path: Path, wallet_name: str = "shitcoims") -> None:
    path.write_text(
        f"""
rpc:
  helius_api_key_file: ./helius
wallet:
  name: {wallet_name}
  secret_key_file: ./wallet
positions:
  - mint: {MINT}
    name: TEST
    cost_basis_sol: 1
    stop_loss_pct: -30
    take_profit_pct: 100
    trailing_stop_pct: 20
""",
        encoding="utf-8",
    )


def test_config_requires_exact_wallet_name(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path, "not-shitcoims")
    with pytest.raises(ConfigError, match="exactly"):
        load_config(config_path)


def test_config_resolves_paths_and_defaults_dry(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config = load_config(config_path)
    assert config.wallet.name == "shitcoims"
    assert config.wallet.secret_key_file == tmp_path / "wallet"
    assert config.execution.enabled is False
    assert config.server.host == "127.0.0.1"
    assert config.jupiter.api_key_file.name == ".jup-shitcoims"
    assert config.notifications.telegram_bot_token_file is not None
    assert config.notifications.telegram_bot_token_file.name == ".shitcoims-tg"
    assert config.positions[0].dispose_after_break_even is False


def test_config_accepts_strict_dispose_after_break_even_flag(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "    trailing_stop_pct: 20",
            "    trailing_stop_pct: 20\n    dispose_after_break_even: true",
        ),
        encoding="utf-8",
    )
    assert load_config(config_path).positions[0].dispose_after_break_even is True

    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "dispose_after_break_even: true", "dispose_after_break_even: 'true'"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="dispose_after_break_even"):
        load_config(config_path)


def test_config_rejects_string_booleans_and_jupiter_credential_redirect(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    value = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        value
        + "\nexecution:\n  enabled: 'false'\n"
        + "jupiter:\n  base_url: https://attacker.example/swap/v2\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"official|true or false"):
        load_config(config_path)


def test_config_loads_rug_only_position_without_basis(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
rpc:
  helius_api_key_file: ./helius
wallet:
  name: shitcoims
  secret_key_file: ./wallet
positions:
  - mint: {MINT}
    name: RUGONLY
    stop_loss_pct: -30
    take_profit_pct: 100
    trailing_stop_pct: 20
    rug_exit: true
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.positions[0].name == "RUGONLY"
    assert config.positions[0].buy_price_sol is None
    assert config.positions[0].cost_basis_sol is None
    assert config.positions[0].rug_exit is True
    assert config.execution.enabled is False


def test_secret_reader_rejects_group_readable_file(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_text("value", encoding="utf-8")
    os.chmod(secret, 0o640)
    with pytest.raises(SecretError, match="group/world"):
        read_secret_file(secret)


def test_shitcoims_base58_key_loads_without_format_conversion(tmp_path: Path) -> None:
    expected = Keypair()
    secret = tmp_path / "shitcoims"
    secret.write_text(str(expected), encoding="utf-8")
    os.chmod(secret, 0o600)
    actual = load_shitcoims_keypair(secret)
    assert actual.pubkey() == expected.pubkey()
