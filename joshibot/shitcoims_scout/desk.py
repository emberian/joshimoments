"""Telegram desk: YAML policy buttons. Never sells, arms, or panics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_NEW_BAG_STOP_LOSS_PCT = -35
DEFAULT_NEW_BAG_TAKE_PROFIT_PCT = 80
DEFAULT_NEW_BAG_TRAILING_STOP_PCT = 20

SL_PRESETS = (-20, -35, -50, -80)
TP_PRESETS = (30, 80, 120)
TRAIL_PRESETS = (10, 20, 30)


@dataclass(frozen=True)
class BagView:
    mint: str
    name: str
    exit_sol: str | None
    kind: str
    stop_loss_pct: float | None
    take_profit_pct: float | None
    trailing_stop_pct: float | None
    rug_exit: bool | None
    auto_note: str | None
    exit_style: str | None
    floor_multiple: str | None
    peak: str | None
    scale_rungs_fired: tuple[str, ...]
    decision_reason: str | None
    stop_live: bool = True


def bags_from_snapshot(snapshot: dict[str, Any], policies: list[dict[str, Any]]) -> list[BagView]:
    by_mint = {str(item.get("mint")): item for item in policies if isinstance(item, dict)}
    rows: list[BagView] = []
    for raw in [*(snapshot.get("positions") or []), *(snapshot.get("unmonitored") or [])]:
        if not isinstance(raw, dict) or not raw.get("mint"):
            continue
        mint = str(raw["mint"])
        policy = by_mint.get(mint)
        thresholds = raw.get("thresholds") if isinstance(raw.get("thresholds"), dict) else {}
        runner = raw.get("runner") if isinstance(raw.get("runner"), dict) else {}
        style = None
        if isinstance(policy, dict):
            style = policy.get("exit_style") or thresholds.get("exit_style")
        elif thresholds.get("exit_style"):
            style = thresholds.get("exit_style")
        if policy and style not in {"runner", "fixed_trail"}:
            style = "runner"
        rungs = runner.get("scale_rungs_fired")
        scale = tuple(str(item) for item in rungs) if isinstance(rungs, list) else ()
        floor = runner.get("floor_multiple")
        rows.append(
            BagView(
                mint=mint,
                name=str(raw.get("name") or mint[:8])[:32],
                exit_sol=None if raw.get("exit_sol") is None else str(raw.get("exit_sol")),
                kind="protected" if policy else "observe",
                stop_loss_pct=_num(policy.get("stop_loss_pct") if policy else None),
                take_profit_pct=_num(policy.get("take_profit_pct") if policy else None),
                trailing_stop_pct=_num(policy.get("trailing_stop_pct") if policy else None),
                rug_exit=None if policy is None else bool(policy.get("rug_exit", True)),
                auto_note=(
                    None
                    if policy
                    else "default SL -35 / arm +80 / runner after 10m; SL waits another 10m"
                ),
                exit_style=str(style) if style in {"runner", "fixed_trail"} else None,
                floor_multiple=None if floor in (None, "") else str(floor),
                peak=_peak_multiple(raw),
                scale_rungs_fired=scale,
                decision_reason=_optional_text(raw.get("decision_reason")),
                stop_live=raw.get("stop_live") is not False,
            )
        )
    return rows


def render_desk(snapshot: dict[str, Any], policies: list[dict[str, Any]]) -> str:
    system = snapshot.get("system") if isinstance(snapshot.get("system"), dict) else {}
    wallet = snapshot.get("wallet") if isinstance(snapshot.get("wallet"), dict) else {}
    rows = bags_from_snapshot(snapshot, policies)
    lines = [
        "🎛 Desk — YAML rules only. Cannot sell directly, cannot arm; a rule can still cause a later sale.",
        f"Mode: {system.get('mode', '?')} / {system.get('protection_state', '?')}",
        f"SOL: {wallet.get('sol', '?')} · book {wallet.get('portfolio_exit_sol', '?')}",
        "",
    ]
    if not rows:
        lines.append("No bags on shitcoims.")
        return "\n".join(lines)
    for bag in rows:
        rule = (
            _rule_line(bag, compact=True)
            if bag.kind == "protected"
            else bag.auto_note or "observe-only"
        )
        lines.append(f"• {bag.name}: {bag.exit_sol or '?'} SOL · {rule}")
    return "\n".join(lines)


def render_bag(bag: BagView) -> str:
    lines = [
        f"🎛 {bag.name}",
        f"{bag.mint}",
        f"Quoted exit: {bag.exit_sol or '?'} SOL",
        "Writes config.yaml only. Cannot sell directly or arm; a rule you set can cause a later sale.",
    ]
    if bag.kind == "protected":
        lines.insert(3, _rule_line(bag, compact=False))
        tape = _runner_tape(bag)
        if tape:
            lines.insert(4, tape)
        if bag.kind == "protected" and not bag.stop_live:
            lines.insert(5 if tape else 4, "SL warming — rug only")
        if bag.decision_reason and "graduation" in bag.decision_reason.lower():
            lines.insert(5 if tape else 4, "waiting for graduation")
        if bag.scale_rungs_fired:
            lines.append(f"scaled {' · '.join(bag.scale_rungs_fired)}")
    else:
        lines.insert(3, bag.auto_note or "No rule yet.")
    return "\n".join(lines)


def default_policy_body(bag: BagView) -> dict[str, Any]:
    style = bag.exit_style if bag.exit_style in {"runner", "fixed_trail"} else "runner"
    body: dict[str, Any] = {
        "name": bag.name,
        "stop_loss_pct": (
            bag.stop_loss_pct if bag.stop_loss_pct is not None else DEFAULT_NEW_BAG_STOP_LOSS_PCT
        ),
        "take_profit_pct": (
            bag.take_profit_pct if bag.take_profit_pct is not None else DEFAULT_NEW_BAG_TAKE_PROFIT_PCT
        ),
        "trailing_stop_pct": (
            bag.trailing_stop_pct if bag.trailing_stop_pct is not None else DEFAULT_NEW_BAG_TRAILING_STOP_PCT
        ),
        "rug_exit": True if bag.rug_exit is None else bag.rug_exit,
        "dispose_after_break_even": False,
        "exit_style": style,
    }
    if bag.exit_sol:
        try:
            basis = float(bag.exit_sol)
        except ValueError:
            basis = None
        if basis is not None and basis > 0:
            body["cost_basis_sol"] = basis
    return body


def render_candidates(payload: object) -> str:
    if not isinstance(payload, dict):
        return "Candidates API not up yet."
    items = payload.get("items")
    if not isinstance(items, list):
        items = payload.get("candidates")
    if not isinstance(items, list):
        return "Candidates API not up yet."
    lines = ["🔎 Candidates — observe only. Cannot sell."]
    for raw in items[:30]:
        if not isinstance(raw, dict):
            continue
        verdict = raw.get("verdict", "?")
        mint = raw.get("mint", "?")
        reasons = raw.get("reasons")
        if isinstance(reasons, list):
            reason_text = ", ".join(str(part) for part in reasons if part not in (None, ""))
        elif reasons in (None, ""):
            reason_text = ""
        else:
            reason_text = str(reasons)
        line = f"• {verdict} · {mint}"
        if reason_text:
            line += f" — {reason_text}"
        lines.append(line)
    if len(lines) == 1:
        lines.append("No candidates.")
    return "\n".join(lines)


def _num(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _fmt_signed(value: float | None) -> str:
    if value is None:
        return "?"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _fmt_arm(value: float | None) -> str:
    if value is None:
        return "?"
    magnitude = _fmt_signed(value)
    if value > 0 and not magnitude.startswith("+"):
        return f"+{magnitude}"
    return magnitude


def _fmt_x(value: object) -> str | None:
    number = _num(value)
    if number is None:
        return None
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return f"{text}x"


def _peak_multiple(raw: dict[str, Any]) -> str | None:
    unit = _num(raw.get("unit_price_sol"))
    peak_unit = _num(raw.get("trailing_peak_unit_price_sol"))
    pnl = _num(raw.get("pnl_pct"))
    if unit is None or peak_unit is None or unit <= 0 or pnl is None:
        return None
    now_x = 1 + pnl / 100
    peak_x = (peak_unit / unit) * now_x
    text = f"{peak_x:.4f}".rstrip("0").rstrip(".")
    return text or None


def _rule_line(bag: BagView, *, compact: bool) -> str:
    sl = _fmt_signed(bag.stop_loss_pct)
    if bag.exit_style == "fixed_trail":
        tp = _fmt_signed(bag.take_profit_pct)
        trail = _fmt_signed(bag.trailing_stop_pct)
        if compact:
            return f"SL {sl} / TP {tp} / trail {trail}%"
        return f"SL {sl} · TP {tp} · trail {trail}% · rug {bag.rug_exit}"
    arm = _fmt_arm(bag.take_profit_pct)
    floor = _fmt_x(bag.floor_multiple)
    runner = f"runner floor {floor}" if floor else "runner"
    if compact:
        return f"SL {sl} / arm {arm} / {runner}"
    return f"SL {sl} · arm {arm} · {runner} · rug {bag.rug_exit}"


def _runner_tape(bag: BagView) -> str | None:
    if bag.exit_style == "fixed_trail":
        return None
    parts: list[str] = []
    peak = _fmt_x(bag.peak)
    floor = _fmt_x(bag.floor_multiple)
    if peak:
        parts.append(f"peak {peak}")
    if floor:
        parts.append(f"floor {floor}")
    if not parts:
        return None
    return " · ".join(parts)
