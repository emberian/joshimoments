from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from solders.keypair import Keypair

from shitcoims_sentinel.policies import (
    PolicyError,
    persist_positions,
    policies_for_unmonitored,
    policy_from_payload,
    policy_to_mapping,
    policy_without_basis,
)


def _config(path: Path) -> None:
    wallet = Keypair()
    path.write_text(
        """
rpc:
  helius_api_key_file: ./helius
wallet:
  name: shitcoims
  secret_key_file: ./wallet
execution:
  enabled: false
positions: []
""",
        encoding="utf-8",
    )
    (path.parent / "helius").write_text("k", encoding="utf-8")
    (path.parent / "wallet").write_text(str(wallet), encoding="utf-8")


def test_policy_rejects_execution_and_secret_fields() -> None:
    mint = str(Keypair().pubkey())
    with pytest.raises(PolicyError, match="cannot include"):
        policy_from_payload(mint, {"cost_basis_sol": 1, "execution": True})
    with pytest.raises(PolicyError, match="cannot include"):
        policy_from_payload(mint, {"cost_basis_sol": 1, "api_key": "x"})


def test_policy_requires_negative_stop_and_one_cost_basis() -> None:
    mint = str(Keypair().pubkey())
    with pytest.raises(PolicyError, match="negative"):
        policy_from_payload(mint, {"cost_basis_sol": 1, "stop_loss_pct": 10})
    with pytest.raises(PolicyError, match="exactly one"):
        policy_from_payload(mint, {"cost_basis_sol": 1, "buy_price_sol": 0.1})


def test_policy_without_basis_keeps_thresholds() -> None:
    mint = str(Keypair().pubkey())
    policy = policy_from_payload(
        mint,
        {
            "name": "CLOUT",
            "cost_basis_sol": 1.15,
            "stop_loss_pct": -10,
            "take_profit_pct": 80,
            "trailing_stop_pct": 20,
        },
    )
    cleared = policy_without_basis(policy)
    assert cleared.cost_basis_sol is None
    assert cleared.buy_price_sol is None
    assert cleared.stop_loss_pct == policy.stop_loss_pct
    assert "cost_basis_sol" not in policy_to_mapping(cleared)


def test_new_payload_defaults_to_runner_not_percent_leash() -> None:
    mint = str(Keypair().pubkey())
    policy = policy_from_payload(
        mint,
        {
            "name": "CLOUT",
            "cost_basis_sol": 1.15,
            "stop_loss_pct": -10,
            "take_profit_pct": 80,
            "trailing_stop_pct": 20,
        },
    )
    assert policy.exit_style == "runner"
    assert policy.floor_confirm_quotes == 2
    assert policy.hold_trail_until_graduated is True
    mapping = policy_to_mapping(policy)
    assert mapping["exit_style"] == "runner"


def test_policy_rejects_unknown_exit_style() -> None:
    mint = str(Keypair().pubkey())
    with pytest.raises(PolicyError, match="exit_style"):
        policy_from_payload(mint, {"cost_basis_sol": 1, "exit_style": "atr"})


def test_policy_allows_missing_basis_for_rug_only() -> None:
    mint = str(Keypair().pubkey())
    policy = policy_from_payload(
        mint,
        {
            "name": "RUG",
            "stop_loss_pct": -30,
            "take_profit_pct": 100,
            "trailing_stop_pct": 20,
            "rug_exit": True,
        },
    )
    assert policy.buy_price_sol is None
    assert policy.cost_basis_sol is None
    assert policy.rug_exit is True
    mapping = policy_to_mapping(policy)
    assert "cost_basis_sol" not in mapping
    assert "buy_price_sol" not in mapping


def test_policies_for_unmonitored_from_quote_uses_exit_sol_and_skips() -> None:
    existing_mint = str(Keypair().pubkey())
    new_mint = str(Keypair().pubkey())
    skip_mint = str(Keypair().pubkey())
    zero_mint = str(Keypair().pubkey())
    bad_mint = str(Keypair().pubkey())
    existing = policy_from_payload(
        existing_mint, {"name": "KEEP", "cost_basis_sol": 9}
    )
    merged, created, skipped = policies_for_unmonitored(
        unmonitored=[
            {"mint": existing_mint, "name": "OVERWRITE", "exit_sol": "1.0"},
            {"mint": new_mint, "name": "L00T", "exit_sol": "0.542"},
            {"mint": skip_mint, "name": "NOQUOTE", "exit_sol": None},
            {"mint": zero_mint, "name": "ZERO", "exit_sol": "0"},
            {"mint": bad_mint, "name": "BAD", "exit_sol": "nope"},
            {"mint": "not-a-mint", "name": "BOGUS", "exit_sol": "1"},
        ],
        current=[existing],
        mode="from_quote",
    )
    assert [policy.mint for policy in merged] == [existing_mint, new_mint]
    assert merged[0].name == "KEEP"
    assert merged[0].cost_basis_sol == existing.cost_basis_sol
    assert created == [new_mint]
    assert merged[1].name == "L00T"
    assert merged[1].cost_basis_sol is not None
    assert float(merged[1].cost_basis_sol) == 0.542
    assert merged[1].buy_price_sol is None
    skipped_by_mint = {item["mint"]: item["reason"] for item in skipped}
    assert skip_mint in skipped_by_mint
    assert zero_mint in skipped_by_mint
    assert bad_mint in skipped_by_mint
    assert "not-a-mint" in skipped_by_mint
    assert existing_mint not in skipped_by_mint


def test_policies_for_unmonitored_rug_only_has_no_cost_basis() -> None:
    mint = str(Keypair().pubkey())
    merged, created, skipped = policies_for_unmonitored(
        unmonitored=[{"mint": mint, "name": "AKitty", "exit_sol": "0.127"}],
        current=[],
        mode="rug_only",
    )
    assert created == [mint]
    assert skipped == []
    assert merged[0].cost_basis_sol is None
    assert merged[0].buy_price_sol is None
    assert merged[0].name == "AKitty"
    mapping = policy_to_mapping(merged[0])
    assert "cost_basis_sol" not in mapping
    assert "buy_price_sol" not in mapping


def test_policies_for_unmonitored_rejects_unknown_mode() -> None:
    with pytest.raises(PolicyError, match="mode"):
        policies_for_unmonitored(unmonitored=[], current=[], mode="panic")


def test_persist_positions_rewrites_only_positions_key(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _config(path)
    mint = str(Keypair().pubkey())
    policy = policy_from_payload(
        mint,
        {
            "name": "TEST",
            "cost_basis_sol": 0.5,
            "stop_loss_pct": -25,
            "take_profit_pct": 80,
            "trailing_stop_pct": 15,
            "rug_exit": True,
        },
    )
    persist_positions(path, [policy])
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert document["execution"]["enabled"] is False
    assert document["wallet"]["name"] == "shitcoims"
    assert document["positions"][0]["mint"] == mint
    assert document["positions"][0]["cost_basis_sol"] == 0.5


def test_persist_rug_only_omits_basis_and_leaves_execution(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _config(path)
    mint = str(Keypair().pubkey())
    policy = policy_from_payload(mint, {"name": "RUG", "rug_exit": True})
    persist_positions(path, [policy])
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert document["execution"]["enabled"] is False
    assert "cost_basis_sol" not in document["positions"][0]
    assert "buy_price_sol" not in document["positions"][0]
    assert document["positions"][0]["rug_exit"] is True
