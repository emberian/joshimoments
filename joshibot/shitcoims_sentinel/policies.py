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

from .domain import DEFAULTS, PolicyDefaults, PositionPolicy, decimal_from
from .runner import EXIT_STYLES

# Derived, not restated: a field added to the policy is accepted by the API and the YAML
# loader the moment it exists, and a field removed stops being accepted everywhere at once.
POLICY_FIELDS = frozenset(field.name for field in dataclasses.fields(PositionPolicy))
# Any real Solana pubkey works; `policy_defaults_from_payload` builds a policy it throws
# away, purely so the default set is checked by the same rules a written policy is.
_PROBE_MINT = str(Pubkey.default())
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


def _percent(value: Decimal | None) -> float | None:
    """Percent/SOL scalars only — NEVER a raw base-unit amount.

    `float()` breaks the otherwise end-to-end `Decimal` discipline, and that is a bounded
    exception rather than an oversight: a SOL amount at 9 decimals below ~10^6 SOL sits well
    inside float64's ~15-17 significant digits. The exactness cliff that matters in this
    project is at 2**53 raw token units, reachable by a 1e9-supply 6-decimal memecoin — see
    `shitcoims_tape.schema`, where raw amounts therefore cross the wire as strings.
    """

    return None if value is None else float(value)


def policy_to_yaml_mapping(policy: PositionPolicy) -> dict[str, Any]:
    """Render a policy for `config.yaml` persistence — the operator-readable file.

    Split from the API mapping on purpose. They coincide field-for-field today, and the one
    shared function that used to serve both carried a comment begging whoever added a field
    to split them first. They answer to different owners: this one to a file a human edits
    and to `load_config`, the other to a typed browser contract.
    """

    payload: dict[str, Any] = {
        "mint": policy.mint,
        "name": policy.name,
        "stop_loss_pct": _percent(policy.stop_loss_pct),
        "take_profit_pct": _percent(policy.take_profit_pct),
        "trailing_stop_pct": _percent(policy.trailing_stop_pct),
        "rug_exit": policy.rug_exit,
        "dispose_after_break_even": policy.dispose_after_break_even,
        "exit_style": policy.exit_style,
        "floor_confirm_quotes": int(policy.floor_confirm_quotes),
        "hold_trail_until_graduated": policy.hold_trail_until_graduated,
    }
    # Basis keys are omitted rather than written as null: their absence is what a
    # rug-only lot looks like in the file, and a null would read as "we looked".
    if policy.cost_basis_sol is not None:
        payload["cost_basis_sol"] = float(policy.cost_basis_sol)
    if policy.buy_price_sol is not None:
        payload["buy_price_sol"] = float(policy.buy_price_sol)
    return payload


def policy_to_api_mapping(policy: PositionPolicy) -> dict[str, Any]:
    """Render a policy for the local dashboard API.

    The browser types these fields as `number | null`, so switching to strings for precision
    would silently change the API contract.
    """

    payload: dict[str, Any] = {
        "mint": policy.mint,
        "name": policy.name,
        "stop_loss_pct": _percent(policy.stop_loss_pct),
        "take_profit_pct": _percent(policy.take_profit_pct),
        "trailing_stop_pct": _percent(policy.trailing_stop_pct),
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


def _strict_bool(value: Any, field: str) -> bool:
    """A quoted 'false' is truthy in Python and is how a rug exit gets silently disabled."""

    if not isinstance(value, bool):
        raise PolicyError(f"{field} must be true or false")
    return value


def _confirm_quotes(value: Any) -> int:
    if isinstance(value, bool):
        raise PolicyError("floor_confirm_quotes must be a whole number")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PolicyError("floor_confirm_quotes must be a whole number") from exc


def policy_from_payload(
    mint: str, payload: dict[str, Any], *, defaults: PolicyDefaults = DEFAULTS
) -> PositionPolicy:
    """THE validator. `config.yaml` and the dashboard API both come through here.

    They used to implement the same rules twice, with different exception types and
    drifting defaults, so a payload the API refused could still be loaded from YAML.
    """

    if not isinstance(payload, dict):
        raise PolicyError("policy payload must be an object")
    _blocked(payload)
    unknown = sorted(set(payload) - POLICY_FIELDS)
    if unknown:
        raise PolicyError(f"unknown policy fields: {', '.join(unknown)}")
    try:
        parsed_mint = str(Pubkey.from_string(str(mint).strip()))
    except Exception as exc:
        raise PolicyError("mint is not a Solana public key") from exc
    embedded = payload.get("mint")
    if embedded not in {None, ""} and str(embedded).strip() != parsed_mint:
        # PUT /api/policies/<A> with {"mint": "B"} used to write a rule for A under B's
        # numbers without a word.
        raise PolicyError("payload mint does not match the policy being written")
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
            stop_loss_pct=decimal_from(
                payload.get("stop_loss_pct", defaults.stop_loss_pct), field="stop_loss_pct"
            ),
            take_profit_pct=decimal_from(
                payload.get("take_profit_pct", defaults.take_profit_pct), field="take_profit_pct"
            ),
            trailing_stop_pct=decimal_from(
                payload.get("trailing_stop_pct", defaults.trailing_stop_pct), field="trailing_stop_pct"
            ),
            rug_exit=_strict_bool(payload.get("rug_exit", defaults.rug_exit), "rug_exit"),
            dispose_after_break_even=_strict_bool(
                payload.get("dispose_after_break_even", defaults.dispose_after_break_even),
                "dispose_after_break_even",
            ),
            exit_style=str(payload.get("exit_style") or defaults.exit_style).strip(),
            floor_confirm_quotes=_confirm_quotes(
                payload.get("floor_confirm_quotes", defaults.floor_confirm_quotes)
            ),
            hold_trail_until_graduated=_strict_bool(
                payload.get("hold_trail_until_graduated", defaults.hold_trail_until_graduated),
                "hold_trail_until_graduated",
            ),
        )
    except PolicyError:
        raise
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


def policy_defaults_from_payload(payload: dict[str, Any]) -> PolicyDefaults:
    """Read a caller-supplied default set, held to exactly the policy rules.

    Validated by building one throwaway policy rather than by a second copy of the rule
    list, so "what the dashboard may ask for" and "what may be written" cannot drift.
    """

    if not isinstance(payload, dict):
        raise PolicyError("policy defaults must be an object")
    names = [field.name for field in dataclasses.fields(PolicyDefaults)]
    probe = policy_from_payload(
        _PROBE_MINT, {key: value for key, value in payload.items() if key in names}
    )
    return PolicyDefaults(**{name: getattr(probe, name) for name in names})


def policies_for_unmonitored(
    *,
    unmonitored: list[dict[str, Any]],
    current: list[PositionPolicy],
    mode: str = "rug_only",
    defaults: PolicyDefaults = DEFAULTS,
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

        try:
            policy = policy_from_payload(
                mint,
                {"name": str(row.get("name") or mint[:8])[:48]},
                defaults=defaults,
            )
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
    # Imported here, not at module scope: `config` imports this module for THE validator,
    # and the read-back below is the only thing this module needs from it.
    from .config import load_config

    document = load_document(path)
    document["positions"] = [policy_to_yaml_mapping(policy) for policy in policies]
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
