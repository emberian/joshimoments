"""Local position-policy persistence. Never touches keys or execution gates."""

from __future__ import annotations

import dataclasses
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from solders.pubkey import Pubkey

from .config import load_config
from .domain import PositionPolicy, decimal_from
from .runner import EXIT_STYLE_RUNNER, EXIT_STYLES

POLICY_FIELDS = {
    "mint",
    "name",
    "buy_price_sol",
    "cost_basis_sol",
    "stop_loss_pct",
    "take_profit_pct",
    "trailing_stop_pct",
    "rug_exit",
    "dispose_after_break_even",
    "exit_style",
    "floor_confirm_quotes",
    "hold_trail_until_graduated",
}
_BLOCKED = {
    "execution",
    "enabled",
    "live",
    "secret",
    "keypair",
    "api_key",
    "wallet",
    "signed",
    "transaction",
}


class PolicyError(ValueError):
    pass


def _blocked(mapping: dict[str, Any]) -> None:
    for key in mapping:
        lowered = str(key).lower()
        if lowered in _BLOCKED or any(part in lowered for part in _BLOCKED):
            raise PolicyError(f"policy payload cannot include {key}")


def policy_to_mapping(policy: PositionPolicy) -> dict[str, Any]:
    """Render a policy for BOTH `config.yaml` persistence and the dashboard API.

    The `float()` calls break the otherwise end-to-end `Decimal` discipline, and that is a
    deliberate, bounded exception rather than an oversight. Two things keep it safe, and both
    must hold if anyone changes this:

    - These are SOL-denominated quantities and percentages, not raw base units. A SOL amount
      at 9 decimals below ~10^6 SOL sits well inside float64's ~15-17 significant digits. The
      exactness cliff that matters in this project is at 2**53 raw token units, which is
      reachable by a 1e9-supply 6-decimal memecoin — see `shitcoims_tape.schema`, where raw
      amounts therefore cross the wire as strings. Nothing raw passes through here.
    - This mapping is shared: `persist_positions` writes it to YAML and `server.list_policies`
      serves it to the browser, which types these fields as `number`. Switching to strings for
      precision would silently change the API contract.

    So: if a raw base-unit field is ever added to a policy, it must NOT be rendered with
    `float()` here — split the persistence and API mappings first.
    """
    payload: dict[str, Any] = {
        "mint": policy.mint,
        "name": policy.name,
        "stop_loss_pct": float(policy.stop_loss_pct),
        "take_profit_pct": float(policy.take_profit_pct),
        "trailing_stop_pct": float(policy.trailing_stop_pct),
        "rug_exit": policy.rug_exit,
        "dispose_after_break_even": policy.dispose_after_break_even,
        "exit_style": policy.exit_style,
        "floor_confirm_quotes": int(policy.floor_confirm_quotes),
        "hold_trail_until_graduated": policy.hold_trail_until_graduated,
    }
    if policy.cost_basis_sol is not None:
        payload["cost_basis_sol"] = float(policy.cost_basis_sol)
    if policy.buy_price_sol is not None:
        payload["buy_price_sol"] = float(policy.buy_price_sol)
    return payload


def policy_from_payload(mint: str, payload: dict[str, Any]) -> PositionPolicy:
    if not isinstance(payload, dict):
        raise PolicyError("policy payload must be an object")
    _blocked(payload)
    unknown = sorted(set(payload) - POLICY_FIELDS)
    if unknown:
        raise PolicyError(f"unknown policy fields: {', '.join(unknown)}")
    try:
        parsed_mint = str(Pubkey.from_string(mint.strip()))
    except Exception as exc:
        raise PolicyError("mint is not a Solana public key") from exc
    buy_price = payload.get("buy_price_sol")
    cost_basis = payload.get("cost_basis_sol")
    if buy_price not in {None, ""} and cost_basis not in {None, ""}:
        raise PolicyError("set exactly one of cost_basis_sol or buy_price_sol")
    try:
        policy = PositionPolicy(
            mint=parsed_mint,
            name=str(payload.get("name") or parsed_mint[:8])[:48],
            buy_price_sol=None if buy_price in {None, ""} else decimal_from(buy_price, field="buy_price_sol"),
            cost_basis_sol=(
                None if cost_basis in {None, ""} else decimal_from(cost_basis, field="cost_basis_sol")
            ),
            stop_loss_pct=decimal_from(payload.get("stop_loss_pct", -30), field="stop_loss_pct"),
            take_profit_pct=decimal_from(payload.get("take_profit_pct", 100), field="take_profit_pct"),
            trailing_stop_pct=decimal_from(payload.get("trailing_stop_pct", 20), field="trailing_stop_pct"),
            rug_exit=bool(payload.get("rug_exit", True)),
            dispose_after_break_even=bool(payload.get("dispose_after_break_even", False)),
            exit_style=str(payload.get("exit_style") or EXIT_STYLE_RUNNER).strip(),
            floor_confirm_quotes=int(payload.get("floor_confirm_quotes", 2)),
            hold_trail_until_graduated=bool(payload.get("hold_trail_until_graduated", True)),
        )
    except Exception as exc:
        raise PolicyError(str(exc)) from exc
    if policy.stop_loss_pct >= 0:
        raise PolicyError("stop_loss_pct must be negative")
    if policy.take_profit_pct <= 0:
        raise PolicyError("take_profit_pct must be positive")
    if not Decimal("0") < policy.trailing_stop_pct < Decimal("100"):
        raise PolicyError("trailing_stop_pct must be in (0, 100)")
    if policy.exit_style not in EXIT_STYLES:
        raise PolicyError("exit_style must be runner or fixed_trail")
    if not 1 <= policy.floor_confirm_quotes <= 6:
        raise PolicyError("floor_confirm_quotes must be in [1, 6]")
    if (policy.buy_price_sol is not None and policy.buy_price_sol <= 0) or (
        policy.cost_basis_sol is not None and policy.cost_basis_sol <= 0
    ):
        raise PolicyError("cost basis must be positive")
    return policy


def policies_for_unmonitored(
    *,
    unmonitored: list[dict[str, Any]],
    current: list[PositionPolicy],
    mode: str = "rug_only",
    stop_loss_pct: Any = -30,
    take_profit_pct: Any = 100,
    trailing_stop_pct: Any = 20,
    rug_exit: bool = True,
    dispose_after_break_even: bool = False,
    exit_style: str = EXIT_STYLE_RUNNER,
    floor_confirm_quotes: int = 2,
    hold_trail_until_graduated: bool = True,
) -> tuple[list[PositionPolicy], list[str], list[dict[str, str]]]:
    """Merge rug-only policies for unmonitored holdings.

    Never overwrites an existing policy. Does not touch files, keys, or execution.

    A basis is NEVER seeded here. The old ``from_quote`` mode stamped the current
    Jupiter exit quote as cost basis, which made PnL start at 0% regardless of what
    was actually paid and turned every stop into a loss (measured: -29.1% mean over
    16 round trips on 2026-08-12, versus +18.1% over 3 with an operator-typed basis).
    Created policies carry no basis, so they are rug-only until the engine
    reconstructs the real basis from observed on-chain buys.
    """
    if mode != "rug_only":
        raise PolicyError(
            "mode must be rug_only; a basis is never seeded from an exit quote"
        )

    existing = {policy.mint: policy for policy in current}
    merged = list(current)
    created: list[str] = []
    skipped: list[dict[str, str]] = []

    for row in unmonitored:
        if not isinstance(row, dict):
            skipped.append({"mint": "", "reason": "unmonitored row must be an object"})
            continue
        raw_mint = str(row.get("mint") or "").strip()
        if not raw_mint:
            skipped.append({"mint": "", "reason": "missing mint"})
            continue
        try:
            mint = str(Pubkey.from_string(raw_mint))
        except Exception:
            skipped.append({"mint": raw_mint, "reason": "mint is not a Solana public key"})
            continue
        if mint in existing:
            continue

        payload: dict[str, Any] = {
            "name": str(row.get("name") or mint[:8])[:48],
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "trailing_stop_pct": trailing_stop_pct,
            "rug_exit": rug_exit,
            "dispose_after_break_even": dispose_after_break_even,
            "exit_style": exit_style,
            "floor_confirm_quotes": floor_confirm_quotes,
            "hold_trail_until_graduated": hold_trail_until_graduated,
        }
        try:
            policy = policy_from_payload(mint, payload)
        except PolicyError as exc:
            skipped.append({"mint": mint, "reason": str(exc)})
            continue
        existing[policy.mint] = policy
        merged.append(policy)
        created.append(policy.mint)

    return merged, created, skipped


def load_document(path: Path) -> dict[str, Any]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise PolicyError(f"config not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise PolicyError(f"invalid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise PolicyError("config root must be a mapping")
    return document


def policy_without_basis(policy: PositionPolicy) -> PositionPolicy:
    """Keep thresholds; drop lot-specific cash basis. Used when a bag goes flat."""

    return dataclasses.replace(policy, cost_basis_sol=None, buy_price_sol=None)


def persist_positions(path: Path, policies: list[PositionPolicy]) -> None:
    document = load_document(path)
    document["positions"] = [policy_to_mapping(policy) for policy in policies]
    serialized = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    load_config(path)
