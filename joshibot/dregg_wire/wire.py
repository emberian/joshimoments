"""Compose the Daily PvP Wire from a facts dict. Pure templates — no model call in v0.

Two renderings from one facts dict:

* ``compose_telegram`` — the channel text, ~30-50 tight lines, Telegram HTML
  parse_mode. Every coin mentioned is a pump.fun hyperlink on its symbol (or short
  mint), never a raw URL. Every provider-derived string (symbol, name, thesis,
  username, mint) is HTML-escaped, so hostile text renders inert; static template
  copy avoids literal angle brackets entirely.
* ``compose_markdown`` — the fuller artifact saved to ``state/dregg_wire/<day>.md``,
  normal markdown links, full mint addresses, methodology footer.

Both are deterministic: same facts, same bytes.
"""

from __future__ import annotations

import html
from pathlib import Path

PUMP_COIN_URL = "https://pump.fun/coin/{mint}"
TELEGRAM_HARD_LIMIT = 4096

DISCLAIMER = "Scores rank risk; they do not establish intent. No number here is a promise."


# -- escaping + tiny formatters --------------------------------------------------------


def _e(value: object) -> str:
    """HTML-escape a provider-derived string for Telegram HTML parse_mode."""

    return html.escape(str(value), quote=True)


def _sym(symbol: object) -> str:
    """Symbols come from the launch event verbatim; keep them one short token.

    A leading ``$`` is stripped because every template adds its own cashtag sigil.
    """

    text = " ".join(str(symbol or "?").split()).lstrip("$")
    return text[:12] if text else "?"


def _md_text(value: object) -> str:
    """Neutralize markdown link syntax in provider-derived link text."""

    text = " ".join(str(value or "?").split())
    for ch in ("\\", "[", "]", "(", ")"):
        text = text.replace(ch, "\\" + ch)
    return text


def _short_mint(mint: str) -> str:
    return f"{mint[:4]}…{mint[-4:]}" if len(mint) > 12 else mint


def _coin_html(mint: str, symbol: object = None) -> str:
    label = f"${_sym(symbol)}" if symbol is not None else _short_mint(str(mint))
    return f'<a href="{_e(PUMP_COIN_URL.format(mint=mint))}">{_e(label)}</a>'


def _coin_md(mint: str, symbol: object = None) -> str:
    label = f"${_md_text(_sym(symbol))}" if symbol is not None else _short_mint(str(mint))
    return f"[{label}]({PUMP_COIN_URL.format(mint=mint)})"


def _pct(x: float | None, digits: int = 1) -> str:
    return "?" if x is None else f"{100.0 * x:.{digits}f}%"


def _devbuy(share: float | None) -> str:
    """A dev buy that is tiny-but-real never rounds to a pretend zero."""

    if not share:
        return "0%"
    if share < 0.0001:
        return "<0.01%"  # escaped at the HTML render site
    return _pct(share, 2)


def _n(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _sol(x: float) -> str:
    return f"{x:+,.1f} SOL".replace("-", "−")  # noqa: RUF001 — typographic minus, house style


def _kb(n: int) -> str:
    return f"{n / 1024:.1f} KB"


def _lrd(history: dict) -> str:
    return f"{history.get('launches', 0)}/{history.get('rips', 0)}/{history.get('dumps', 0)}"


def _ret_pct(x: float) -> str:
    # The typographic minus is deliberate: it is the brand's printed form for measured
    # negative returns (see OFFER_BRIEF.md), same for the multiplication sign below.
    return f"{100.0 * x:+.1f}%".replace("-", "−")  # noqa: RUF001


# -- the lede --------------------------------------------------------------------------


def lede(facts: dict) -> str:
    """LEDE SLOT — v0 is a deterministic template.

    A later revision may let a model draft this one line (from `facts` and nothing
    else); it will still ride the same approval gate before anything posts.
    """

    screen = facts.get("screen", {})
    if screen.get("absent"):
        return "The desk is up; today's screen ledger is empty — the tape below is what we do have."
    mayhem = screen["mayhem"]
    validated = screen["validated"]
    if mayhem["share"] >= 0.20:
        return (
            f"{_pct(mayhem['share'])} of today's creates minted in mayhem mode — outside the "
            "population our precision numbers were earned on. We label what we can prove."
        )
    if validated["count"]:
        return (
            f"{validated['clean']} CLEAN admits from {validated['count']} validated launches today "
            "— the screen holds its line."
        )
    return f"{screen['launches_scored']} launches scored today; the tape is below."


# -- telegram --------------------------------------------------------------------------


def compose_telegram(facts: dict, issue: int) -> str:
    day = facts["day"]
    lines: list[str] = [f"📰 DREGG WIRE #{issue} — {day}", _e(lede(facts)), ""]

    screen = facts["screen"]
    lines.append(f"🔬 LAUNCH SCREEN (scores, UTC day {day})")
    if screen.get("absent"):
        lines.append(_e(screen["absent"]))
    else:
        verdict_bits = " · ".join(f"{_e(k)} {v}" for k, v in screen["verdicts"].items())
        lines.append(f"{screen['launches_scored']} launches scored — {verdict_bits}")
        validated = screen["validated"]
        op = validated.get("operating_point") or {}
        if validated["count"]:
            vs = ""
            if op.get("admit_rate") is not None:
                vs = (
                    f" vs the {_pct(op['admit_rate'])} operating point, "
                    f"validated {_e(op.get('validated_span', '?'))}"
                )
            lines.append(
                f"Validated population: {validated['count']} of {screen['launches_scored']}; "
                f"CLEAN admits there: {validated['clean']} ({_pct(validated['clean_rate'])}){vs}."
            )
        else:
            lines.append("Validated population: none of today's launches fell inside it.")
        mayhem = screen["mayhem"]
        lines.append(
            f"Mayhem-mode creates: {mayhem['count']} of {screen['launches_scored']} "
            f"({_pct(mayhem['share'])}) — outside the validated population; labeled, never blended."
        )
        if screen["notable_cleans"]:
            lines.append("Notable CLEANs (dev buy · deployer launches/rips/dumps):")
            for clean in screen["notable_cleans"]:
                tag = "" if clean["in_validated_population"] else " · unvalidated pop."
                lines.append(
                    f"• {_coin_html(clean['mint'], clean['symbol'])} — "
                    f"{_e(_devbuy(clean['dev_buy_share']))} · {_lrd(clean['deployer_history'])}{tag}"
                )
        lines.append("")
        lines.append("🕸 CREW WATCH")
        if screen["crews"]:
            for crew in screen["crews"]:
                coins = ", ".join(f"${_e(_sym(s))}" for s in crew["symbols"][:3])
                lines.append(
                    f"#{crew['crew_id']} — {_n(crew['launches_today'], 'launch', 'launches')} today "
                    f"({coins}), Jaccard {crew['max_jaccard']:.2f}; crew record {crew['crew_coins']} "
                    f"coins, {crew['crew_rips']} rips, {crew['crew_dumps']} insider dumps."
                )
        else:
            lines.append(_e(screen.get("crews_note") or "no crew-fingerprint matches today."))
    lines.append("")

    callouts = facts["callouts"]
    lines.append(f"📣 CALLOUT DESK (archived, UTC day {day})")
    if callouts.get("absent"):
        lines.append(_e(callouts["absent"]))
    else:
        if callouts["archived_today"]:
            lines.append(
                f"{callouts['archived_today']} callouts archived today · "
                f"{callouts['distinct_callers_today']} callers · {callouts['distinct_mints_today']} coins "
                f"(board lifetime: {callouts['board_total']} callouts, {callouts['board_callers']} callers)."
            )
        else:
            lines.append(
                f"No callouts first-archived today (board lifetime: {callouts['board_total']} "
                f"callouts, {callouts['board_callers']} callers)."
            )
        top = callouts.get("top_provider_claim")
        if top:
            by = f" by {_e(top['username'])}" if top.get("username") else ""
            lines.append(
                f"Boldest provider claim: {top['multiple']:.1f}× on {_coin_html(top['mint'])}{by} "  # noqa: RUF001
                "— their peak number, not our measurement."
            )
        anti = callouts["anti_signal"]
        lines.append(
            f"Season baseline ({_e(anti['short_source'])}): buying the feed averaged "
            f"{_ret_pct(anti['ret_1h_mean'])} @1h and {_ret_pct(anti['ret_8h_mean'])} @8h; "
            f"{_e(anti['burst_definition'])} → {_ret_pct(anti['burst_ret_8h_median'])} median @8h."
        )
        outcomes = callouts["outcomes"]
        if outcomes["note"]:
            lines.append(f"Real outcomes: {outcomes['rows']} rows computing — {_e(outcomes['note'])}.")
        else:
            lines.append(
                f"Real outcomes: {outcomes['priced_1h']} priced at 1h, {outcomes['final']} final "
                f"(of {outcomes['rows']} rows)."
            )
        removals = callouts["removals"]
        if removals["note"]:
            lines.append(f"Removal ledger: {_e(removals['note'])}.")
        else:
            lines.append(f"Removal ledger: {removals['today']} caught today, {removals['total']} all-time.")
        lines.extend(_caller_color_lines_html(facts))
    lines.append("")

    archive = facts["archive"]
    lines.append("🧾 RECEIPTS")
    if archive.get("absent"):
        lines.append(_e(archive["absent"]))
    else:
        anchor = (
            f"{archive['manifests_anchored']} daily manifests anchored"
            if archive["manifests_anchored"]
            else _e(archive["manifest_note"])
        )
        lines.append(
            f"{archive['fetches_today']} fetches archived today ({_kb(archive['zst_bytes_today'])} zstd), "
            f"every body sha256'd; {anchor}."
        )
    lines.append("")
    lines.append(f"{_e(DISCLAIMER)} — the DREGG desk")

    text = "\n".join(lines)
    if len(text) > TELEGRAM_HARD_LIMIT:
        raise ValueError(f"composed wire is {len(text)} chars; Telegram's limit is {TELEGRAM_HARD_LIMIT}")
    return text


def _caller_color_lines_html(facts: dict) -> list[str]:
    color = facts.get("caller_color") or {}
    entries = [e for e in (color.get("entries") or []) if "absent" not in e]
    if not entries:
        return []  # color is color; its absence is stated in the markdown artifact, not the channel
    top_callers = {c["wallet"]: c for c in facts["callouts"].get("top_callers", [])}
    lines = []
    for entry in entries[:1]:
        caller = top_callers.get(entry["wallet"], {})
        who = _e(caller.get("username") or _short_mint(entry["wallet"]))
        n = caller.get("callouts_today", "?")
        lines.append(
            f"Top caller today: {who} ({n} callouts). Wallet layer (as of {_e(color.get('as_of', '?'))} "
            f"— stale): {_sol(entry['net_realized_sol'])} realized, {_pct(entry['win_rate'])} win rate "
            f"over {int(entry['n_coins_closed'])} closed coins, {_e(entry['rp_mode'])}."
        )
    return lines


# -- markdown artifact -----------------------------------------------------------------


def compose_markdown(facts: dict, issue: int) -> str:
    day = facts["day"]
    out: list[str] = [
        f"# DREGG WIRE #{issue} — {day}",
        "",
        f"*{lede(facts)}*",
        "",
    ]

    screen = facts["screen"]
    out.append(f"## Launch screen\n\n`{screen['source']}`\n")
    if screen.get("absent"):
        out.append(f"{screen['absent']}\n")
    else:
        verdict_bits = " · ".join(f"**{k}** {v}" for k, v in screen["verdicts"].items())
        out.append(f"**{screen['launches_scored']} launches scored** — {verdict_bits}\n")
        validated = screen["validated"]
        op = validated.get("operating_point") or {}
        if validated["count"]:
            out.append(
                f"- Validated population: {validated['count']} of {screen['launches_scored']}; "
                f"CLEAN admits {validated['clean']} ({_pct(validated['clean_rate'])})"
                + (
                    f" vs the {_pct(op['admit_rate'])} operating point — "
                    f"validated {op.get('validated_span', '?')}, "
                    f"clean precision {_pct(op.get('clean_precision'), 2)}"
                    if op.get("admit_rate") is not None
                    else ""
                )
            )
        else:
            out.append("- Validated population: none of today's launches fell inside it")
        mayhem = screen["mayhem"]
        out.append(
            f"- Mayhem-mode creates: {mayhem['count']} of {screen['launches_scored']} "
            f"({_pct(mayhem['share'])}) — {mayhem['definition']}"
        )
        if screen["notable_cleans"]:
            out.append("\n### Notable CLEANs\n")
            out.append("| coin | mint | dev buy | deployer L/R/D | validated pop. |")
            out.append("|---|---|---|---|---|")
            for clean in screen["notable_cleans"]:
                out.append(
                    f"| {_coin_md(clean['mint'], clean['symbol'])} | `{clean['mint']}` "
                    f"| {_devbuy(clean['dev_buy_share'])} | {_lrd(clean['deployer_history'])} "
                    f"| {'yes' if clean['in_validated_population'] else 'no'} |"
                )
        out.append("\n### Crew watch\n")
        if screen["crews"]:
            for crew in screen["crews"]:
                coins = ", ".join(f"${_md_text(_sym(s))}" for s in crew["symbols"])
                out.append(
                    f"- fingerprint **#{crew['crew_id']}** — "
                    f"{_n(crew['launches_today'], 'launch', 'launches')} today "
                    f"({coins}), max Jaccard {crew['max_jaccard']:.2f}; crew corpus record: "
                    f"{crew['crew_coins']} coins, {crew['crew_rips']} rips, "
                    f"{crew['crew_dumps']} insider dumps"
                )
        else:
            out.append(screen.get("crews_note") or "no crew-fingerprint matches today")
    out.append("")

    callouts = facts["callouts"]
    out.append(f"## Callout desk\n\n`{callouts['source']}`\n")
    if callouts.get("absent"):
        out.append(f"{callouts['absent']}\n")
    else:
        out.append(
            f"- {callouts['archived_today']} callouts first-archived today · "
            f"{callouts['distinct_callers_today']} distinct callers · "
            f"{callouts['distinct_mints_today']} coins "
            f"(board lifetime: {callouts['board_total']} callouts / {callouts['board_callers']} callers)"
        )
        top = callouts.get("top_provider_claim")
        if top:
            thesis = f' — thesis: "{_md_text(top["thesis"])}"' if top.get("thesis") else ""
            out.append(
                f"- Boldest provider claim: **{top['multiple']:.1f}×** on {_coin_md(top['mint'])}"  # noqa: RUF001
                + (f" by {_md_text(top['username'])}" if top.get("username") else "")
                + f"{thesis} — *{top['label']}*"
            )
        anti = callouts["anti_signal"]
        out.append(
            f"- Season baseline: {_ret_pct(anti['ret_1h_mean'])} @1h, {_ret_pct(anti['ret_8h_mean'])} @8h; "
            f"{anti['burst_definition']} → {_ret_pct(anti['burst_ret_8h_median'])} median @8h "
            f"(*{anti['source']}*)"
        )
        outcomes = callouts["outcomes"]
        out.append(
            f"- Real outcomes: {outcomes['rows']} rows, {outcomes['priced_1h']} priced @1h, "
            f"{outcomes['final']} final" + (f" — {outcomes['note']}" if outcomes["note"] else "")
        )
        removals = callouts["removals"]
        out.append(
            f"- Removal ledger: {removals['today']} today, {removals['total']} all-time"
            + (f" — {removals['note']}" if removals["note"] else "")
        )
        if callouts.get("top_callers"):
            out.append("\n### Top callers today\n")
            color = facts.get("caller_color") or {}
            color_by_wallet = {e.get("wallet"): e for e in color.get("entries") or []}
            for caller in callouts["top_callers"]:
                who = _md_text(caller.get("username") or _short_mint(caller["wallet"]))
                line = f"- **{who}** (`{caller['wallet']}`) — {caller['callouts_today']} callouts today"
                entry = color_by_wallet.get(caller["wallet"])
                if entry is None:
                    line += f"; wallet layer: {color.get('absent', 'not joined')}"
                elif "absent" in entry:
                    line += f"; wallet layer (as of {color.get('as_of', '?')}, stale): {entry['absent']}"
                else:
                    line += (
                        f"; wallet layer (as of {color.get('as_of', '?')}, **stale**): "
                        f"{_sol(entry['net_realized_sol'])} realized, {_pct(entry['win_rate'])} win "
                        f"rate / {int(entry['n_coins_closed'])} closed, {entry['rp_mode']}"
                        + (f", guild {entry['guild']}" if entry.get("guild") else "")
                    )
                out.append(line)
            out.append(f"\n*{color.get('note', '')}*")
    out.append("")

    archive = facts["archive"]
    out.append(f"## Receipts\n\n`{archive['source']}`\n")
    if archive.get("absent"):
        out.append(f"{archive['absent']}\n")
    else:
        out.append(
            f"- {archive['fetches_today']} fetches archived today, {archive['zst_bytes_today']} bytes "
            "zstd-compressed, every body sha256'd"
        )
        out.append(
            f"- Daily manifests anchored: {archive['manifests_anchored']}"
            + (f" — {archive['manifest_note']}" if archive["manifest_note"] else "")
        )
    out.append("")
    out.append("---")
    out.append(
        f"*{DISCLAIMER} Every figure above names its source and window; absences are stated, "
        "not zero-filled. Composed deterministically from the desk's own archives by dregg_wire.*"
    )
    return "\n".join(out) + "\n"


# -- assembly --------------------------------------------------------------------------


def render(facts: dict, issue: int) -> tuple[str, str]:
    """(telegram_html, markdown_artifact) for one facts dict."""

    return compose_telegram(facts, issue), compose_markdown(facts, issue)


def write_artifact(state_dir: Path, day: str, markdown: str) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"{day}.md"
    path.write_text(markdown)
    return path
