"""Configuration, and the caps that bound the damage.

lpexec reads its OWN file (`lpexec.yaml`), not the sentinel's `config.yaml`. That is not
tidiness: at the time this package was written `config.yaml` did not parse -- an orphaned
block of policy keys had been left indented under `positions: []` -- and a shared config
file means one package's broken edit disarms or misconfigures another package that is
holding money. Separate files, separate blast radius.

CAPS. Four, and they are all in SOL/USD rather than raw token units because a raw cap on a
6-decimal memecoin is a number nobody can sanity-check in a config file:

  per_tx_max_sol_lamports    net SOL the wallet may spend in one transaction (rent + fees +
                             any SOL-side deposit). The rent-aware number: one position plus
                             two virgin bin arrays is already 0.20 SOL.
  per_day_max_sol_lamports   the same, summed over the UTC day, read back from the ledger.
  per_tx_max_token_usd       USD value of token moved in one transaction.
  per_day_max_token_usd      the same over the UTC day.

The day window is the LEDGER's UTC day, so a cap and its accounting cannot disagree about
when the day started. Defaults are deliberately small -- roughly one playbook -- because a
cap you had to raise on purpose is a cap you thought about.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import yaml

from .allowlist import THA_FUNDS

DEFAULT_CONFIG_PATH = Path("lpexec.yaml")


class ConfigError(ValueError):
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class ExecutionConfig:
    enabled: bool
    arm_file: Path
    max_priority_fee_lamports: int
    per_tx_max_sol_lamports: int
    per_day_max_sol_lamports: int
    per_tx_max_token_usd: float
    per_day_max_token_usd: float
    min_seconds_between_transactions: float
    max_transactions_per_day: int


@dataclasses.dataclass(frozen=True, slots=True)
class LpExecConfig:
    config_path: Path
    wallet_address: str
    secret_key_file: Path
    helius_api_key_file: Path
    state_dir: Path
    execution: ExecutionConfig
    sidecar_dir: Path
    rpc_timeout_seconds: float

    @property
    def ledger_dir(self) -> Path:
        return self.state_dir / "lpexec"


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be a YAML boolean, not {value!r}")
    return value


def _path(value: Any, *, base: Path) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def _bounded_int(
    raw: dict[str, Any], key: str, default: int, low: int, high: int, *, prefix: str = "execution"
) -> int:
    value = int(raw.get(key, default))
    if not low <= value <= high:
        label = f"{prefix}.{key}" if prefix else key
        raise ConfigError(f"{label} must be in [{low}, {high}]")
    return value


def _bounded_float(
    raw: dict[str, Any], key: str, default: float, low: float, high: float, *, prefix: str = "execution"
) -> float:
    value = float(raw.get(key, default))
    if not low <= value <= high:
        label = f"{prefix}.{key}" if prefix else key
        raise ConfigError(f"{label} must be in [{low}, {high}]")
    return value


def default_config(path: Path | None = None) -> LpExecConfig:
    """The all-gates-closed configuration used when no file exists.

    Absence of config is dry-run, not an error: `--plan` must work on a machine that has
    never been armed, which is exactly the machine an operator reviews the plan on.
    """
    base = (path.parent if path is not None else Path.cwd()).resolve()
    return LpExecConfig(
        config_path=path if path is not None else DEFAULT_CONFIG_PATH,
        wallet_address=THA_FUNDS,
        secret_key_file=Path("~/.thafunds-wallet").expanduser(),
        helius_api_key_file=Path("~/.helius-key").expanduser(),
        state_dir=(base / "state").resolve(),
        execution=ExecutionConfig(
            enabled=False,
            arm_file=(base / "state" / "LPEXEC_ARMED").resolve(),
            max_priority_fee_lamports=1_000_000,
            per_tx_max_sol_lamports=300_000_000,
            per_day_max_sol_lamports=900_000_000,
            per_tx_max_token_usd=400.0,
            per_day_max_token_usd=1_200.0,
            min_seconds_between_transactions=5.0,
            max_transactions_per_day=40,
        ),
        sidecar_dir=(Path(__file__).resolve().parent / "node"),
        rpc_timeout_seconds=60.0,
    )


def load_config(path: str | Path | None = None) -> LpExecConfig:
    """Load `lpexec.yaml`. A missing file is the default (dry-run); a malformed one raises.

    The asymmetry is on purpose. Absence means "nobody has configured this yet", which is
    safe. A file that exists but does not parse means somebody wrote something they believed
    was in effect, and guessing which half they meant is how a cap silently becomes a
    default.
    """
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not target.exists():
        return default_config(target)
    try:
        raw_any = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{target} is not valid YAML: {exc}") from exc
    raw = _mapping(raw_any, str(target))
    base = target.parent.resolve()
    fallback = default_config(target)

    wallet_raw = _mapping(raw.get("wallet"), "wallet")
    address = str(wallet_raw.get("address", THA_FUNDS))
    if address != THA_FUNDS:
        raise ConfigError(
            f"wallet.address must be tha funds ({THA_FUNDS}); this package manages one wallet"
        )

    rpc_raw = _mapping(raw.get("rpc"), "rpc")
    execution_raw = _mapping(raw.get("execution"), "execution")

    execution = ExecutionConfig(
        enabled=_bool(execution_raw.get("enabled", False), "execution.enabled"),
        arm_file=_path(execution_raw.get("arm_file", "./state/LPEXEC_ARMED"), base=base),
        max_priority_fee_lamports=_bounded_int(
            execution_raw, "max_priority_fee_lamports", 1_000_000, 5_000, 50_000_000
        ),
        per_tx_max_sol_lamports=_bounded_int(
            execution_raw, "per_tx_max_sol_lamports", 300_000_000, 10_000, 5_000_000_000
        ),
        per_day_max_sol_lamports=_bounded_int(
            execution_raw, "per_day_max_sol_lamports", 900_000_000, 10_000, 20_000_000_000
        ),
        per_tx_max_token_usd=_bounded_float(execution_raw, "per_tx_max_token_usd", 400.0, 1.0, 50_000.0),
        per_day_max_token_usd=_bounded_float(
            execution_raw, "per_day_max_token_usd", 1_200.0, 1.0, 200_000.0
        ),
        min_seconds_between_transactions=_bounded_float(
            execution_raw, "min_seconds_between_transactions", 5.0, 0.0, 3_600.0
        ),
        max_transactions_per_day=_bounded_int(execution_raw, "max_transactions_per_day", 40, 1, 500),
    )
    if execution.per_day_max_sol_lamports < execution.per_tx_max_sol_lamports:
        raise ConfigError("execution.per_day_max_sol_lamports is below the per-transaction cap")
    if execution.per_day_max_token_usd < execution.per_tx_max_token_usd:
        raise ConfigError("execution.per_day_max_token_usd is below the per-transaction cap")

    return LpExecConfig(
        config_path=target,
        wallet_address=address,
        secret_key_file=_path(wallet_raw.get("secret_key_file", "~/.thafunds-wallet"), base=base),
        helius_api_key_file=_path(rpc_raw.get("helius_api_key_file", "~/.helius-key"), base=base),
        state_dir=_path(raw.get("state_dir", "./state"), base=base),
        execution=execution,
        sidecar_dir=fallback.sidecar_dir,
        rpc_timeout_seconds=_bounded_float(raw, "rpc_timeout_seconds", 60.0, 1.0, 300.0, prefix=""),
    )
