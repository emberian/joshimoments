"""The alert text: HTML-safe, provider-claims labeled, honesty line always last.

Every provider-supplied string (symbol, name) is html.escape()d before it touches the
caption; the mint reaches the <a href> only after the base58 gate in movers.parse kept
it, and is escaped again for the attribute anyway. Numbers are the provider's own
(v5/v1h/... are undecoded compact keys — see movers.py), so the line that carries them
says "provider claims". The standing line is a constant, not a template, so no code
path can ship an alert without it.

Telegram caps photo captions at 1024 chars; symbol and name are clamped BEFORE
escaping so the assembled caption is under the cap by construction — a post-hoc
truncation could sever a tag and earn the outbox a definitive 400.
"""

from __future__ import annotations

import html

from .movers import Alert

STANDING_LINE = "Awareness, not advice; momentum was measured to carry no entry edge."

CAPTION_MAX = 1024

_VERDICT_LINES = {
    "CLEAN": "screen said CLEAN at birth",
    "BUNDLED": "screen said BUNDLED at birth",
    "KNOWN_CREW": "screen said KNOWN_CREW at birth",
    "NOT_CLEAN": "screen said NOT_CLEAN at birth",
    "UNSCORED": "screen could not score it at birth (UNSCORED)",
}
_NO_VERDICT = "born before the screen / unscored"

_REASONS = {
    "accel": "5m volume accelerating",
    "top5_entry": "new entry into the top-5 by 5m volume",
}


def _sol(value: float | None) -> str:
    return f"{value:,.1f} SOL" if value is not None else "?"


def _age(age_s: int | None) -> str:
    if age_s is None:
        return "age ?"
    if age_s < 3600:
        return f"age {age_s // 60}m"
    if age_s < 48 * 3600:
        return f"age {age_s / 3600:.1f}h"
    return f"age {age_s / 86400:.1f}d"


def verdict_line(verdict: str | None) -> str:
    if verdict is None:
        return _NO_VERDICT
    return _VERDICT_LINES.get(verdict, f"screen verdict at birth: {verdict}")


def reason_line(alert: Alert) -> str:
    base = _REASONS.get(alert.reason, alert.reason)
    if alert.reason == "accel" and alert.prev_v5 is not None and alert.prev_v5 > 0:
        return f"{base}: {alert.v5:,.1f} SOL vs {alert.prev_v5:,.1f} one poll earlier"
    return f"{base}: {alert.v5:,.1f} SOL"


def caption(alert: Alert, verdict: str | None) -> str:
    # Inputs are clamped BEFORE escaping so the assembled caption is under Telegram's
    # 1024-char cap by construction (worst case ~1010 with every char escaping to
    # 6 bytes) — a post-hoc truncation could sever the </a> and earn a definitive 400.
    symbol = html.escape(alert.symbol[:20])
    name = html.escape((alert.name or alert.symbol)[:64])
    mint_attr = html.escape(alert.mint, quote=True)
    claims = " · ".join(
        [
            f"5m {_sol(alert.v5)}",
            f"1h {_sol(alert.v1h)}",
            f"24h {_sol(alert.v24h)}",
            f"{alert.tx5:,} trades/5m" if alert.tx5 is not None else "trades/5m ?",
            f"mcap ${alert.mc_usd:,.0f}" if alert.mc_usd is not None else "mcap ?",
            _age(alert.age_s),
        ]
    )
    lines = [
        f"📊 ${symbol} is moving on pump.fun — "
        f'<a href="https://pump.fun/coin/{mint_attr}">{name}</a>',
        f"why: {reason_line(alert)}",
        f"provider claims: {claims}",
        f"birth screen: {verdict_line(verdict)}",
        STANDING_LINE,
    ]
    return "\n".join(lines)
