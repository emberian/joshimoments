"""The gated pages, rendered ON HBOX from the desk's own archives.

These are the same answers ``@ltshitcoims_bot`` gives, laid out for a screen instead of a
chat bubble. Two rules keep the web and the bot from becoming two products:

* **One data source.** Every figure here comes from the exact call the bot makes —
  ``Dossier.coin``, ``Dossier.wallet``, ``build_leaderboard``, ``load_scores`` — never
  from a re-query that could answer differently.
* **One vocabulary.** The framing sentences (the timing caveat, the realized-only PnL
  discipline, the guild and preset blurbs) are IMPORTED from ``dregg_dossier.cards``
  rather than rewritten. Layout is medium-specific; language is not, because the language
  is where the honesty lives and a paraphrase is how a caveat quietly weakens.

Deterministic: no clock of its own. ``now`` is an argument, so the same inputs and the
same ``now`` produce the same bytes — the property ``dregg_site`` already holds itself to.

Every page carries ``FRESHNESS_MARKER``. The service replaces it with an age computed at
READ time and REFUSES to serve a page that lacks it, so "undated numbers cannot ship" is
enforced by the reader's server, not by this file remembering.
"""

from __future__ import annotations

from typing import Any

from dregg_dossier.cards import (
    _GUILD_BLURB,
    _RP_BLURB,
    PNL_FRAMING,
    PUMP_COIN_URL,
    SOLSCAN_URL,
    TIMING_CAVEAT,
    as_of_line,
    crowd_line,
    fmt_dur,
    fmt_pct,
    fmt_sol,
    short,
)
from dregg_site.chrome import CSS, VERDICT_COLOR, VERDICT_ORDER, absent, esc, src, tile, verdict_bar

from . import FRESHNESS_MARKER
from .render import NAV, PORTAL_CSS

STANDING_LINE = (
    "Screens rank; they do not convict. Provider claims are labeled as claims, and absent "
    "data is stated rather than zeroed."
)

# The verdict filter is CSS ONLY — hidden radios plus sibling selectors. The gated pages
# inherit the site's "no JavaScript" posture, and a filter that needs a script is a filter
# that silently does nothing the day a CSP tightens.
FILTER_CSS = """
.vfilter input { position: absolute; opacity: 0; pointer-events: none; }
.vfilter label {
  display: inline-block; cursor: pointer; margin: 0 6px 6px 0; padding: 4px 12px;
  border-radius: 999px; border: 1px solid #1d2733; background: #10161c;
  font-size: 0.78rem; color: #a8b3bd;
}
.vfilter label i {
  display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 6px;
}
.vfilter { margin: 14px 0 6px; }
#vf-ALL:checked ~ .vfilter label[for=vf-ALL],
#vf-CLEAN:checked ~ .vfilter label[for=vf-CLEAN],
#vf-BUNDLED:checked ~ .vfilter label[for=vf-BUNDLED],
#vf-NOT_CLEAN:checked ~ .vfilter label[for=vf-NOT_CLEAN],
#vf-KNOWN_CREW:checked ~ .vfilter label[for=vf-KNOWN_CREW],
#vf-UNSCORED:checked ~ .vfilter label[for=vf-UNSCORED] {
  border-color: #0ca30c; color: #e8eef2; background: #14201a;
}
#vf-CLEAN:checked ~ .feed tr.row:not(.v-CLEAN),
#vf-BUNDLED:checked ~ .feed tr.row:not(.v-BUNDLED),
#vf-NOT_CLEAN:checked ~ .feed tr.row:not(.v-NOT_CLEAN),
#vf-KNOWN_CREW:checked ~ .feed tr.row:not(.v-KNOWN_CREW),
#vf-UNSCORED:checked ~ .feed tr.row:not(.v-UNSCORED) { display: none; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 7px; }
.nowrap { white-space: nowrap; }
"""


def _color(verdict: str) -> str:
    return VERDICT_COLOR.get(verdict, "#5f6b77")


def _reasons(row: dict) -> str:
    return ", ".join(str(r) for r in (row.get("reasons") or [])[:4]) or "no reasons recorded"


def _coin_href(mint: str) -> str:
    return PUMP_COIN_URL.format(mint=esc(mint))


def _wallet_href(owner: str) -> str:
    return SOLSCAN_URL.format(owner=esc(owner))


def shell(*, title: str, here: str, body: str, base: str) -> str:
    """The portal shell, with the gated nav. Same stylesheet as the public site."""

    links = []
    for suffix, label in NAV:
        cls = ' class="here"' if label == here else ""
        links.append(f'<a href="{esc(base + suffix)}/"{cls}>{esc(label)}</a>')
    links.append('<a href="/index.html">public site</a>')
    links.append('<a href="/wire/">wire archive</a>')
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        f"<title>{esc(title)}</title>\n<style>{CSS}{PORTAL_CSS}{FILTER_CSS}</style>\n</head>\n<body>\n"
        f'<div class="topbar"><a class="brand" href="{esc(base)}/">the shitcoims wire · portal</a>'
        f"<nav>{''.join(links)}</nav></div>\n"
        f"<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


def _head(title: str, tagline: str, stamp: str) -> str:
    """Title block + the freshness slot. The marker sits where the reader looks first."""

    return (
        f"<h1>{esc(title)}</h1>\n"
        f'<p class="tag">{esc(tagline)}</p>\n'
        f'<p class="stampline">{esc(stamp)}</p>\n'
        f"{FRESHNESS_MARKER}\n"
    )


def _footer() -> str:
    return (
        f'<p class="fine">{esc(STANDING_LINE)} '
        "The same lookups answer in Telegram: "
        '<a href="https://t.me/ltshitcoims_bot">@ltshitcoims_bot</a>.</p>'
    )


# -- the feed ------------------------------------------------------------------------


def page_screen(rows: list[dict], facts: dict, day: str, *, base: str, data_through: str | None) -> str:
    screen = facts.get("screen") or {}
    counts: dict[str, int] = {}
    for row in rows:
        verdict = str(row.get("verdict") or "UNSCORED")
        counts[verdict] = counts.get(verdict, 0) + 1

    if not rows:
        table = absent(
            f"No launches were scored into {esc(day)}'s ledger. That is the absence of a FILE, "
            "not a quiet day on chain: if the screen was down, nothing was observed and nothing "
            "is being claimed about what launched."
        )
        chips = ""
    else:
        chips_parts = []
        radios = []
        for name in ("ALL", *VERDICT_ORDER):
            checked = " checked" if name == "ALL" else ""
            radios.append(f'<input type="radio" name="vf" id="vf-{name}"{checked}>')
            color = VERDICT_COLOR.get(name, "#5f6b77")
            count = len(rows) if name == "ALL" else counts.get(name, 0)
            label = "everything" if name == "ALL" else name
            chips_parts.append(
                f'<label for="vf-{name}"><i style="background:{color}"></i>{esc(label)} {count}</label>'
            )
        body_rows = []
        for row in sorted(rows, key=lambda r: str(r.get("t_scored") or ""), reverse=True):
            verdict = str(row.get("verdict") or "UNSCORED")
            mint = str(row.get("mint") or "")
            symbol = str(row.get("symbol") or row.get("name") or "?")
            features = row.get("features") or {}
            share = features.get("dev_buy_share")
            history = row.get("deployer_history") or {}
            reasons = row.get("reasons") or []
            body_rows.append(
                f'<tr class="row v-{esc(verdict)}">'
                f'<td class="nowrap"><i class="dot" style="background:{_color(verdict)}">'
                f"</i>{esc(verdict)}</td>"
                f'<td><a href="{_coin_href(mint)}">{esc(symbol)}</a><br>'
                f'<a class="mono" style="font-size:0.72rem" href="{esc(base)}/coin/{esc(mint)}">'
                f"{esc(short(mint))} — dossier</a></td>"
                f'<td class="num">{esc(_pct(share))}</td>'
                f'<td class="num">{esc(history.get("launches", "n/a"))} / {esc(history.get("rips", "n/a"))}'
                f' / {esc(history.get("dumps", "n/a"))}</td>'
                f"<td>{esc(', '.join(str(r) for r in reasons[:3]) or '—')}</td>"
                f'<td class="num win">{esc(str(row.get("t_scored") or "")[11:16])}</td>'
                "</tr>"
            )
        chips = (
            "".join(radios)
            + f'<div class="vfilter">{"".join(chips_parts)}</div>'
            + '<div class="feed"><div class="tablewrap"><table><thead><tr>'
            "<th>verdict</th><th>coin</th><th>dev buy</th><th>deployer L/R/D</th>"
            "<th>reasons</th><th>utc</th></tr></thead><tbody>"
            + "".join(body_rows)
            + "</tbody></table></div></div>"
        )
        table = ""

    if screen.get("absent"):
        summary = absent(str(screen["absent"]))
    else:
        validated = screen.get("validated") or {}
        mayhem = screen.get("mayhem") or {}
        op = validated.get("operating_point") or {}
        tiles = [
            tile(f"{screen.get('launches_scored', len(rows)):,}", "launches scored"),
            tile(f"{validated.get('count', 0):,}", "in validated population"),
            tile(f"{validated.get('clean', 0):,}", "clean admits"),
            tile(esc(_pct(mayhem.get("share"))), "mayhem-mode creates"),
        ]
        op_line = ""
        if op.get("admit_rate") is not None:
            op_line = (
                f"<p>Operating point stamped on today's scores: admit rate "
                f'<span class="stat">{esc(_pct(op.get("admit_rate")))}</span>, clean precision '
                f'<span class="stat">{esc(_pct(op.get("clean_precision")))}</span> — validated '
                f"{esc(op.get('validated_span', '?'))}.</p>"
            )
        summary = (
            f'<div class="tiles">{"".join(tiles)}</div>'
            + verdict_bar(counts)
            + op_line
            + src(str(screen.get("source", "screen ledger")))
        )

    body = (
        _head(
            "the launch screen",
            "every pump.fun create the screen saw today, with its verdict",
            f"UTC day {day}" + (f" · data through {data_through}" if data_through else ""),
        )
        + f"<section><h2>Today</h2>{summary}</section>"
        + f"<section><h2>The feed</h2>{chips}{table}"
        + '<p class="src">filter is CSS only — no script runs on this page</p></section>'
        + _footer()
    )
    return shell(title=f"screen · {day} · portal", here="screen", body=body, base=base)


def _pct(value: object, digits: int = 0) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "n/a"
    return f"{100 * float(value):.{digits}f}%"


# -- the record ----------------------------------------------------------------------


def page_record(rec: dict, board: dict, *, base: str, day: str, data_through: str | None) -> str:
    coverage = board.get("coverage") or {}
    if board.get("absent"):
        board_body = absent(str(board["absent"]))
    else:
        rows = board.get("rows") or []
        if not rows:
            board_body = absent(str(board.get("rows_note") or "No caller cleared the minimum sample."))
        else:
            body_rows = []
            for row in rows:
                claim = row.get("claim") or {}
                claim_cell = (
                    f"{esc(claim['median_multiple']):}× claimed (n={esc(claim['n'])})"
                    if claim.get("n")
                    else '<span class="win">no claim</span>'
                )
                dead = row.get("dead") or {}
                body_rows.append(
                    f'<tr><td class="num">{esc(row.get("rank", ""))}</td>'
                    f'<td><a href="{esc(base)}/wallet/{esc(row.get("wallet", ""))}">'
                    f"{esc(row.get('handle') or short(str(row.get('wallet', ''))))}</a></td>"
                    f'<td class="num">{esc(row.get("n_callouts", 0))}</td>'
                    f'<td class="num">{esc(row.get("n_measured", 0))}</td>'
                    f'<td class="num">{esc(_signed_pct(row.get("median_ret_24h")))}</td>'
                    f'<td class="num">{esc(row.get("above_0", 0))}</td>'
                    f'<td class="num">{esc(dead.get("n_dead", 0))}/{esc(dead.get("n_final", 0))}</td>'
                    f"<td>{claim_cell}</td></tr>"
                )
            rows_note = board.get("rows_note")
            board_body = (
                '<div class="tablewrap"><table><thead><tr><th>#</th><th>caller</th>'
                "<th>calls</th><th>measured</th><th>median 24h</th><th>up at 24h</th>"
                "<th>dead</th><th>their claim</th></tr></thead><tbody>"
                + "".join(body_rows)
                + "</tbody></table></div>"
                + src(str(board.get("source", "callout archive")))
                + (f'<p class="win">{esc(rows_note)}</p>' if rows_note else "")
            )

    board_meta = (
        f'<p class="src">window {esc(board.get("window_days", "?"))}d · minimum sample '
        f"{esc(board.get('min_n', '?'))} calls · {esc(coverage.get('n_callouts', 0))} callouts from "
        f"{esc(coverage.get('n_callers', 0))} callers, "
        f"{esc(coverage.get('n_measured_24h', 0))} priced at 24h</p>"
    )

    gaps = board.get("gaps") or []
    if gaps:
        gap_rows = "".join(
            f'<tr><td>{esc(g.get("handle") or short(str(g.get("wallet", ""))))}</td>'
            f'<td><a href="{_coin_href(str(g.get("mint", "")))}">'
            f'{esc(short(str(g.get("mint", ""))))}</a></td>'
            f'<td class="num">{esc(g.get("claimed_multiple", "?"))}×</td>'
            f'<td class="num">{esc(g.get("measured_close_multiple", "?"))}×</td>'
            f'<td class="num">{esc(_signed_pct(g.get("ret_24h")))}</td></tr>'
            for g in gaps
        )
        gap_body = (
            '<div class="tablewrap"><table><thead><tr><th>caller</th><th>coin</th>'
            "<th>claimed</th><th>measured close</th><th>24h</th></tr></thead><tbody>"
            + gap_rows
            + "</tbody></table></div>"
        )
    else:
        gap_body = absent(str(board.get("gaps_note") or "No claim-versus-measured gaps in this window."))

    # The record page is the removal ledger's home, so a zero here is an answer (the
    # ledger is the feature) — one sentence, not a count of nothing plus a caption.
    removals = rec.get("removals") or {}
    if removals.get("verdicts"):
        removal_body = (
            f'<p>{esc(removals.get("removed", 0))} of {esc(removals.get("verdicts", 0))} '
            "archived callouts are no longer published where they were posted.</p>"
        )
    else:
        removal_body = (
            f'<p>{esc(removals.get("note") or "nothing has vanished from the provider board yet")}.'
            "</p>"
        )
    body = (
        _head(
            "the caller record",
            "what the callers claimed, and what the chart did",
            f"UTC day {day}" + (f" · data through {data_through}" if data_through else ""),
        )
        + f"<section><h2>Leaderboard</h2>{board_body}{board_meta}</section>"
        + f"<section><h2>Claimed versus measured</h2>{gap_body}</section>"
        + f"<section><h2>Removals</h2>{removal_body}</section>"
        + _footer()
    )
    return shell(title=f"record · {day} · portal", here="record", body=body, base=base)


def _signed_pct(value: object) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "n/a"
    return f"{100 * float(value):+.0f}%"


# -- coin and wallet dossiers --------------------------------------------------------


def page_coin(
    mint: str,
    view: dict,
    meta: dict[str, Any],
    *,
    base: str,
    now: float,
    screen_row: dict | None = None,
) -> str:
    comp = view.get("comp") or {}
    traders = int(comp.get("n_traders") or 0)
    profiled = int(comp.get("n_profiled") or 0)
    mix_rows = [
        ("HARVESTER", comp.get("n_harvester")),
        ("SLOW", comp.get("n_slow")),
        ("ACCUMULATOR", comp.get("n_accumulator")),
        ("FLASH", comp.get("n_flash")),
        ("AFTERMARKET", comp.get("n_aftermarket")),
    ]
    mix = "".join(
        f'<tr><td>{esc(name)}</td><td class="num">{esc(count or 0)}</td>'
        f'<td class="num">{esc(fmt_pct(float(count or 0), float(profiled)))}</td>'
        f"<td>{esc(_GUILD_BLURB.get(name, ''))}</td></tr>"
        for name, count in mix_rows
    )
    tiles = [
        tile(f"{traders:,}", "traders seen"),
        tile(f"{profiled:,}", "profiled"),
        tile(f"{int(comp.get('n_breakeven_preset') or 0):,}", "preset bots"),
        tile(f"{int(comp.get('n_net_positive') or 0):,}", "net positive"),
    ]

    exit_view = view.get("exit")
    if exit_view:
        exit_body = (
            f"<p>{esc(exit_view.get('n_distributors', 0))} wallets show distribution behaviour; "
            f"the strongest iceberg score is "
            f'<span class="stat">{esc(round(float(exit_view.get("max_iceberg_score") or 0), 2))}</span>.</p>'
            + f'<p class="win">{esc(TIMING_CAVEAT)}</p>'
        )
    else:
        exit_body = absent(
            "No exit/distribution row for this coin in the dossier index. Nothing was measured, "
            "so nothing is being claimed either way."
        )

    icebergs = view.get("icebergs") or []
    if icebergs:
        ice_rows = "".join(
            f'<tr><td><a href="{_wallet_href(str(i.get("owner", "")))}">'
            f'{esc(short(str(i.get("owner", ""))))}</a></td>'
            f'<td class="num">{esc(round(float(i.get("iceberg_score") or 0), 2))}</td>'
            f'<td class="num">{esc(_pct(i.get("sold_frac_of_own")))}</td>'
            f'<td class="num">{esc(fmt_sol(i.get("dist_sold_sol"), signed=False))}</td>'
            f'<td class="num">{esc(fmt_dur(i.get("duration_s")))}</td></tr>'
            for i in icebergs
        )
        ice_body = (
            '<div class="tablewrap"><table><thead><tr><th>wallet</th><th>iceberg</th>'
            "<th>sold of own</th><th>distributed</th><th>over</th></tr></thead><tbody>"
            + ice_rows
            + "</tbody></table></div>"
        )
    else:
        ice_body = absent("No iceberg candidates recorded for this coin.")

    crews = view.get("crews") or []
    if crews:
        crew_body = "".join(
            f'<p>Crew <span class="stat">{esc(c.get("crew_id"))}</span> — '
            f"{esc(c.get('n_overlap', 0))} overlapping wallets, {esc(c.get('crew_coins', 0))} coins, "
            f"{esc(c.get('crew_rips', 0))} rips, {esc(c.get('crew_dumps', 0))} dumps"
            f"{' · flagged dirty' if c.get('dirty') else ''}.</p>"
            for c in crews
        )
    else:
        crew_body = absent("No crew overlap recorded for this coin in the crew ledger.")

    screen_bit = ""
    if screen_row:
        verdict = str(screen_row.get("verdict") or "UNSCORED")
        screen_bit = (
            f'<p><i class="dot" style="background:{VERDICT_COLOR.get(verdict, "#5f6b77")}"></i>'
            f'Launch screen verdict: <span class="stat">{esc(verdict)}</span> — '
            f"{esc(_reasons(screen_row))}.</p>"
        )

    symbol = str((screen_row or {}).get("symbol") or "")
    body = (
        _head(
            f"coin · {symbol or short(mint)}",
            "who traded it, how they trade, and who was leaving",
            f"mint {mint}",
        )
        + f'<section><h2>At a glance</h2>{screen_bit}<div class="tiles">{"".join(tiles)}</div>'
        + f'<p><a href="{_coin_href(mint)}">open on pump.fun</a></p>'
        + f'<p class="src">{esc(as_of_line(meta, now))}</p></section>'
        + '<section><h2>Guild mix</h2><div class="tablewrap"><table><thead><tr><th>guild</th>'
        + "<th>n</th><th>share</th><th>what that means</th></tr></thead><tbody>"
        + mix
        + "</tbody></table></div>"
        + f'<p class="win">{esc(crowd_line(meta))}</p></section>'
        + f"<section><h2>Distribution / exit</h2>{exit_body}{ice_body}</section>"
        + f"<section><h2>Crews</h2>{crew_body}</section>"
        + _footer()
    )
    return shell(title=f"coin {short(mint)} · portal", here="screen", body=body, base=base)


def page_wallet(owner: str, row: dict, meta: dict[str, Any], *, base: str, now: float) -> str:
    guild = str(row.get("guild") or "?")
    rp_mode = str(row.get("rp_mode") or "?")
    tiles = [
        tile(esc(fmt_sol(row.get("net_realized_sol"))), "net realized"),
        tile(esc(_pct(row.get("win_rate"))), "win rate"),
        tile(f"{int(row.get('n_coins') or 0):,}", "coins touched"),
        tile(esc(fmt_dur(row.get("median_hold_s"))), "median hold"),
    ]
    facts = [
        ("guild", f"{guild} — {_GUILD_BLURB.get(guild, 'no guild blurb for this label')}"),
        ("realized-PnL mode", f"{rp_mode} — {_RP_BLURB.get(rp_mode, 'no mode blurb for this label')}"),
        ("legs", f"{int(row.get('n_legs') or 0):,} ({int(row.get('n_buys') or 0):,} buys, "
                 f"{int(row.get('n_sells') or 0):,} sells)"),
        ("active days", f"{int(row.get('active_days') or 0):,}"),
        ("closed positions", f"{int(row.get('n_coins_closed') or 0):,}, "
                            f"{int(row.get('n_coins_win') or 0):,} of them up"),
        ("median realized (closed)", fmt_sol(row.get("median_realized_sol_closed"))),
        ("p90 hold", fmt_dur(row.get("p90_hold_s"))),
        ("break-even preset share", _pct(row.get("rp_frac_breakeven"))),
        ("on a ladder / in rotation",
         f"{'yes' if row.get('on_ladder') else 'no'} / {'yes' if row.get('in_rotation') else 'no'}"),
    ]
    fact_rows = "".join(
        f"<tr><td>{esc(name)}</td><td>{esc(value)}</td></tr>" for name, value in facts
    )
    body = (
        _head(
            f"wallet · {short(owner)}",
            "how this address actually trades, measured on closed positions",
            f"address {owner}",
        )
        + f'<section><h2>At a glance</h2><div class="tiles">{"".join(tiles)}</div>'
        + f'<p class="win">{esc(PNL_FRAMING)}</p>'
        + f'<p><a href="{_wallet_href(owner)}">open on solscan</a></p>'
        + f'<p class="src">{esc(as_of_line(meta, now))}</p></section>'
        + '<section><h2>The profile</h2><div class="tablewrap"><table><tbody>'
        + fact_rows
        + "</tbody></table></div>"
        + f'<p class="win">{esc(crowd_line(meta))}</p></section>'
        + _footer()
    )
    return shell(title=f"wallet {short(owner)} · portal", here="screen", body=body, base=base)


# -- the gated home ------------------------------------------------------------------


def page_index(
    facts: dict,
    rec: dict,
    board: dict,
    *,
    base: str,
    day: str,
    data_through: str | None,
    coin_pages: int,
    wallet_pages: int,
    slice_window: str,
    latest_wire: str | None,
) -> str:
    screen = facts.get("screen") or {}
    counters = [
        tile(f"{screen.get('launches_scored', 0):,}", "launches scored today"),
        tile(f"{(rec.get('board') or {}).get('callouts', 0):,}", "callouts archived"),
        tile(f"{coin_pages:,}", "coin dossiers in this bundle"),
        tile(f"{wallet_pages:,}", "wallet dossiers in this bundle"),
    ]
    wire_line = (
        '<p>The daily wire is public and stays public: <a href="/wire/">the archive</a>'
        + (f' · <a href="{esc(latest_wire)}">the latest one</a>' if latest_wire else "")
        + ". It is not re-gated here — a piece already published to everyone would not become "
        "more valuable by hiding a second copy of it behind the door.</p>"
    )
    body = (
        _head(
            "the desk",
            "everything the bot answers, laid out for a screen",
            f"UTC day {day}" + (f" · data through {data_through}" if data_through else ""),
        )
        + f'<section><h2>Today</h2><div class="tiles">{"".join(counters)}</div>'
        + (verdict_bar(screen.get("verdicts") or {}) if screen.get("verdicts") else "")
        + f'<p class="src">{esc(slice_window)}</p></section>'
        + "<section><h2>Where to go</h2><ul>"
        + f'<li><a href="{esc(base)}/screen/">the launch screen</a> — every create the screen saw '
        "today with its verdict, filterable.</li>"
        + f'<li><a href="{esc(base)}/record/">the caller record</a> — the leaderboard, and claimed '
        "versus measured.</li>"
        + f'<li><a href="{esc(base)}/me">my seat</a> — standing, and your watchlist read-only.</li>'
        + "</ul>"
        + wire_line
        + "</section>"
        + "<section><h2>What is not here</h2>"
        + absent(
            "Coin and wallet dossiers are rendered for a bounded slice, not for all 728k profiled "
            "wallets. Anything outside it says so on its own page and points at the live lookup in "
            "Telegram, rather than rendering an empty card that reads like a finding."
        )
        + "</section>"
        + _footer()
    )
    return shell(title="the desk · portal", here="portal", body=body, base=base)
