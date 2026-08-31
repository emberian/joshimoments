"""The montage caption: PLAIN TEXT, one line per coin, honesty line always last.

NO HTML, NO parse_mode — deliberately (2026-08-29): Telegram auto-links bare URLs, and
plain text makes every provider-supplied string (symbol, name) literal-inert; nothing
needs escaping, so nothing can be mis-escaped. The one injection that survives plain
text is a NEWLINE inside a provider symbol breaking the line-per-coin structure, so
symbols are whitespace-flattened and clamped before use.

Numbers are the provider's own (v5 is an undecoded compact key — see movers.py), so
the header labels them "provider claims" once for every line below it. The standing
line is a constant, not a template, so no code path can ship a caption without it.

Telegram caps photo captions at 1024 chars. Six lines fit by construction: symbol
clamped to 12 chars (18 for a disambiguated "SYM·mint" label), mint is 44, per-line
worst case ~137 chars, six lines plus header, the CLEAN gloss (added only when a
CLEAN verdict appears, kept under 63 chars for exactly this budget), and the standing
line lands under ~1010. `montage_caption` asserts the invariant anyway.
"""

from __future__ import annotations

from typing import Sequence

from dregg_screen.survival import CLEAN_FEED_GLOSS

from .movers import Alert

STANDING_LINE = "Awareness, not advice; momentum was measured to carry no entry edge."

CAPTION_MAX = 1024

#: Short verdict forms for the per-coin line. None (not in the last-2-days scores)
#: renders as pre-screen/unscored — never guessed.
_VERDICT_SHORT = {
    "CLEAN": "CLEAN",
    "BUNDLED": "BUNDLED",
    "KNOWN_CREW": "KNOWN-CREW",
    "NOT_CLEAN": "NOT-CLEAN",
    "UNSCORED": "UNSCORED",
}
_NO_VERDICT = "pre-screen/unscored"


def _symbol(alert: Alert) -> str:
    """Whitespace-flattened and clamped: a hostile symbol cannot add caption lines."""

    return ("".join((alert.symbol or "?").split()) or "?")[:12]


def verdict_short(verdict: str | None) -> str:
    if verdict is None:
        return _NO_VERDICT
    return _VERDICT_SHORT.get(verdict, verdict[:12])


def coin_line(alert: Alert, verdict: str | None, label: str | None = None) -> str:
    """`label` overrides the symbol when a montage disambiguates colliding tickers
    ("Pepsi·6AmL") — clamped wider (18) so the mint suffix survives."""

    shown = ("".join(label.split()) or "?")[:18] if label is not None else _symbol(alert)
    v5 = f"{alert.v5:,.0f}" if alert.v5 is not None else "?"
    return (
        f"${shown}  https://pump.fun/coin/{alert.mint}"
        f" · 5m {v5} SOL · birth: {verdict_short(verdict)}"
    )


def montage_caption(
    items: Sequence[tuple[Alert, str | None]], labels: dict[str, str] | None = None
) -> str:
    """One caption for the whole montage. `items` order MUST be the panel order
    (left-to-right, top-to-bottom) so line N describes tile N; `labels` (mint ->
    display name) must be the SAME mapping the tiles were titled with."""

    if not items:
        raise ValueError("a montage caption needs at least one coin")
    n = len(items)
    header = (
        f"📊 {n} mover{'s' if n != 1 else ''} on pump.fun right now"
        " · 5m window · volumes are provider claims"
    )
    lines = [
        header,
        *(
            coin_line(alert, verdict, (labels or {}).get(alert.mint))
            for alert, verdict in items
        ),
    ]
    if any(verdict == "CLEAN" for _, verdict in items):
        # A "birth: CLEAN" tag must not read as a buy call — one short gloss, only
        # when a CLEAN appears (its length is budgeted in the cap math above).
        lines.append(CLEAN_FEED_GLOSS)
    lines.append(STANDING_LINE)
    text = "\n".join(lines)
    # Belt for the invariant the clamps above establish; six max-length lines sit
    # ~880 chars. If this ever trips, the bug is upstream (an unclamped field).
    assert len(text) <= CAPTION_MAX, "montage caption exceeded Telegram's cap"
    return text
