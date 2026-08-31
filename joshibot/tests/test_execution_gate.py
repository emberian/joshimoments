import os
from pathlib import Path

from solders.keypair import Keypair

from shitcoims_sentinel.config import load_config
from shitcoims_sentinel.executor import ExecutionGate


def test_live_execution_requires_all_three_local_gates_and_jupiter(tmp_path: Path) -> None:
    wallet = Keypair()
    wallet_path = tmp_path / "wallet"
    wallet_path.write_text(str(wallet), encoding="utf-8")
    os.chmod(wallet_path, 0o600)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
rpc:
  helius_api_key_file: ./helius
wallet:
  name: shitcoims
  secret_key_file: ./wallet
execution:
  enabled: true
  arm_file: ./LIVE_ARMED
positions: []
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    gate = ExecutionGate(config, wallet, cli_live=True)
    assert gate.status(jupiter_ready=True)[0] is False
    config.execution.arm_file.write_text(gate.expected_arm_value, encoding="utf-8")
    os.chmod(config.execution.arm_file, 0o600)
    assert gate.status(jupiter_ready=True) == (True, [])
    assert gate.status(jupiter_ready=False)[0] is False

