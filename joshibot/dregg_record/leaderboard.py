"""THE CALLOUT RECORD's board: ranked by MEASURED outcome, framed by the anti-signal.

The ranking rule (deliberate, and the whole point):

* rank = median measured 24h return of the caller's callouts in the window — our
  candle closes (outcomes method v1), never the provider's recomputed peak multiple,
  never follower counts.
* a caller appears only with ``min_n`` (default 5) MEASURED calls in the window — one
  lucky call is not a record.
* the median is robust: one moonshot (or one pumped own-coin) cannot carry a rank.
* deletion is inert: callouts are archived at first sighting and priced from retained
  candles, so a deleted call still counts — and its published removal verdict renders
  ON the board row. The gameable move (delete your losers) makes your row WORSE.

Two side tables: most-called coins, and the claimed-vs-measured gap — the provider's
own peak multiple beside what our close series actually did, widest gaps first.

Renderers: ``render_text`` (Telegram: PLAIN TEXT, bare URLs, no parse_mode — the
dregg_feed.compose discipline; provider names are whitespace-flattened and clamped so
a hostile handle cannot add lines) and ``render_markdown`` (site/wire artifact).
Every render ends with the standing line; no code path ships a board without it.
"""

from __future__ import annotations

from pathlib import Path
from statistics import mean, median

from dregg_archive.store import MS_DAY
from dregg_wire.facts import ANTI_SIGNAL, caller_color

from .records import (
    METHOD_VERSION,
    WINDOW_DAYS,
    _connect_ro,
    fmt_mult,
    fmt_pct,
    handle,
    short_wallet,
    utc_day,
)

MIN_N = 5
TOP_N = 8
MAX_COINS = 4
MAX_GAPS = 4
TELEGRAM_MAX = 4096
PUMP_COIN_URL = "https://pump.fun/coin/{mint}"

STANDING_LINE = (
    "Records are measurements, not endorsements. Buying the callout feed was measured as an "
    f"anti-signal ({fmt_pct(ANTI_SIGNAL['ret_1h_mean'])} avg at 1h, "
    f"{fmt_pct(ANTI_SIGNAL['ret_8h_mean'])} at 8h; {ANTI_SIGNAL['burst_definition']} ran "
    f"{fmt_pct(ANTI_SIGNAL['burst_ret_8h_median'])} median at 8h), and shuffled caller identity "
    "matched or beat the real assignment 24/24 — no caller here has demonstrated measured skill "
    f"({ANTI_SIGNAL['short_source']})."
)
REMOVAL_LINE = (
    "Deleting a callout changes nothing here: calls are archived at first sight and priced from "
    "our own candles — a vanished one stays counted and gains a removal verdict beside it."
)


# -- aggregation -----------------------------------------------------------------------


def build_leaderboard(
    archive_db: Path,
    *,
    now_ms: int,
    window_days: int = WINDOW_DAYS,
    min_n: int = MIN_N,
    top_n: int = TOP_N,
    max_coins: int = MAX_COINS,
    max_gaps: int = MAX_GAPS,
    wallet_parquet: Path | None = None,
    method_version: str = METHOD_VERSION,
) -> dict:
    window_start = now_ms - window_days * MS_DAY
    source = (
        f"dregg_archive {archive_db.name}; outcomes method {method_version}; "
        f"window {utc_day(window_start)}..{utc_day(now_ms)} UTC"
    )
    base = {
        "source": source,
        "window_days": window_days,
        "window_start": utc_day(window_start),
        "window_end": utc_day(now_ms),
        "min_n": min_n,
        "method_version": method_version,
    }
    if not archive_db.exists():
        return {**base, "absent": f"callout archive not present at {archive_db}"}
    db = _connect_ro(archive_db)
    try:
        rows = db.execute(
            "SELECT c.callout_id, c.wallet, c.mint, c.t_event_ms,"
            "       c.username_last, c.x_username_last, c.provider_multiple_last,"
            "       o.ret_24h, o.max_close_multiple, o.max_drawdown, o.dead_flag"
            "  FROM callouts c"
            "  LEFT JOIN outcomes o ON o.callout_id = c.callout_id AND o.method_version = ?"
            " WHERE c.t_event_ms IS NOT NULL AND c.t_event_ms >= ? AND c.t_event_ms < ?",
            (method_version, window_start, now_ms),
        ).fetchall()
        removals_by_wallet = dict(
            db.execute(
                "SELECT c.wallet, count(*) FROM removal_verdicts v"
                "  JOIN callouts c ON c.callout_id = v.callout_id"
                " WHERE v.published = 1 GROUP BY c.wallet"
            ).fetchall()
        )
    finally:
        db.close()
    if not rows:
        return {**base, "absent": f"no dated callouts archived in the trailing {window_days}d window"}

    by_wallet: dict[str, list] = {}
    for r in rows:
        by_wallet.setdefault(r["wallet"], []).append(r)

    board: list[dict] = []
    thin = 0
    for wallet, calls in by_wallet.items():
        measured = [r["ret_24h"] for r in calls if r["ret_24h"] is not None]
        if len(measured) < min_n:
            thin += 1
            continue
        newest = max(calls, key=lambda r: r["t_event_ms"])
        finals = [r for r in calls if r["dead_flag"] is not None]
        claims = [r["provider_multiple_last"] for r in calls
                  if r["provider_multiple_last"] is not None]
        board.append(
            {
                "wallet": wallet,
                "handle": handle(newest["username_last"], newest["x_username_last"], wallet),
                "n_callouts": len(calls),
                "n_measured": len(measured),
                "median_ret_24h": median(measured),
                "mean_ret_24h": mean(measured),
                "above_0": sum(1 for v in measured if v > 0),
                "dead": {"n_final": len(finals), "n_dead": sum(1 for r in finals if r["dead_flag"])},
                "removals_published": int(removals_by_wallet.get(wallet, 0)),
                "claim": (
                    {"n": len(claims), "median_multiple": median(claims)}
                    if claims
                    else {"n": 0, "absent": "no provider multiples published"}
                ),
            }
        )
    board.sort(key=lambda row: (-row["median_ret_24h"], -row["n_measured"], row["wallet"]))
    board = board[:top_n]
    for rank, row in enumerate(board, start=1):
        row["rank"] = rank

    by_mint: dict[str, list] = {}
    for r in rows:
        by_mint.setdefault(r["mint"], []).append(r)
    repeat_called = [(m, calls) for m, calls in by_mint.items() if len(calls) >= 2]
    coins = []
    for mint, calls in sorted(repeat_called, key=lambda kv: (-len(kv[1]), kv[0]))[:max_coins]:
        rets = [r["ret_24h"] for r in calls if r["ret_24h"] is not None]
        coins.append(
            {
                "mint": mint,
                "n_callouts": len(calls),
                "n_callers": len({r["wallet"] for r in calls}),
                "measured_24h": (
                    {"n": len(rets), "median": median(rets)}
                    if rets
                    else {"n": 0, "absent": "no priced 24h closes yet"}
                ),
            }
        )

    gaps = []
    gap_rows = [
        r for r in rows
        if r["provider_multiple_last"] and r["max_close_multiple"]
        and r["provider_multiple_last"] > 0 and r["max_close_multiple"] > 0
    ]
    for r in sorted(gap_rows, key=lambda r: (-r["provider_multiple_last"] / r["max_close_multiple"],
                                             r["callout_id"]))[:max_gaps]:
        gaps.append(
            {
                "handle": handle(r["username_last"], r["x_username_last"], r["wallet"]),
                "wallet": r["wallet"],
                "mint": r["mint"],
                "claimed_multiple": r["provider_multiple_last"],
                "measured_close_multiple": r["max_close_multiple"],
                "ret_24h": r["ret_24h"],
                "gap_ratio": r["provider_multiple_last"] / r["max_close_multiple"],
            }
        )

    n_measured_total = sum(1 for r in rows if r["ret_24h"] is not None)
    return {
        **base,
        "coverage": {
            "n_callouts": len(rows),
            "n_callers": len(by_wallet),
            "n_measured_24h": n_measured_total,
            "note": (
                None
                if n_measured_total
                else "no callout in the window has a priced 24h close yet (they mature at T+25h)"
            ),
        },
        "rows": board,
        "rows_note": (
            None
            if board
            else f"no caller has {min_n}+ measured calls in this window yet — "
            "the record needs evidence before it ranks anyone"
        ),
        "excluded_thin": thin,
        "coins": coins,
        "coins_note": None if coins else "no coin drew 2+ callouts in the window",
        "gaps": gaps,
        "gaps_note": (
            None
            if gaps
            else "no call in the window has both a provider claim and a finalized 7d close series"
        ),
        "caller_color": caller_color(wallet_parquet, [row["wallet"] for row in board]),
    }


# -- renderers -------------------------------------------------------------------------


def _color_line(color: dict, wallet: str) -> str | None:
    """One indented wallet-layer line for a board row, stale-stamped; None when absent."""

    entries = {e.get("wallet"): e for e in color.get("entries", [])}
    entry = entries.get(wallet)
    if entry is None or "absent" in entry:
        return None
    win = entry.get("win_rate")
    bits = [f"realized {entry.get('net_realized_sol'):+,.1f} SOL"]
    if win is not None:
        bits.append(f"win {win:.0%} over {entry.get('n_coins_closed')} closed")
    if entry.get("rp_mode"):
        bits.append(str(entry["rp_mode"]))
    return (
        f"   their own trading (wallet snapshot of {color.get('as_of')} — stale): "
        + " · ".join(bits)
    )


def _board_line(row: dict) -> str:
    dead = row["dead"]
    dead_bit = (
        f"dead by 7d: {dead['n_dead']}/{dead['n_final']}"
        if dead["n_final"]
        else "7d gates pending"
    )
    claim = row["claim"]
    claim_bit = (
        f"claimed median {fmt_mult(claim['median_multiple'])} (their number, n={claim['n']})"
        if claim["n"]
        else "no provider claims"
    )
    removal_bit = f" · removals on record: {row['removals_published']}" if row["removals_published"] else ""
    return (
        f"{row['rank']}. {row['handle']} ({short_wallet(row['wallet'])}) · "
        f"median 24h {fmt_pct(row['median_ret_24h'])} (n={row['n_measured']}) · "
        f"mean {fmt_pct(row['mean_ret_24h'])} · above 0%: {row['above_0']}/{row['n_measured']} · "
        f"{dead_bit} · {claim_bit}{removal_bit}"
    )


def render_text(board: dict) -> str:
    """The Telegram shape: plain text, bare URLs, standing line last, <= 4096 chars."""

    header = (
        f"📇 THE CALLOUT RECORD — trailing {board['window_days']}d "
        f"({board['window_start']}..{board['window_end']} UTC)"
    )
    if "absent" in board:
        text = "\n".join([header, board["absent"], "", STANDING_LINE])
        assert len(text) <= TELEGRAM_MAX
        return text
    lines = [
        header,
        f"Ranked by median MEASURED 24h return of each caller's archived calls, min "
        f"{board['min_n']} measured — priced from our own archived candles, "
        "never the provider's multiples, never follower counts.",
    ]
    cov = board["coverage"]
    coverage = (
        f"Window: {cov['n_callouts']} callouts by {cov['n_callers']} callers; "
        f"{cov['n_measured_24h']} carry a measured 24h close."
    )
    if cov["note"]:
        coverage += f" ({cov['note']})"
    lines += [coverage, ""]

    if board["rows"]:
        color = board["caller_color"]
        for row in board["rows"]:
            lines.append(_board_line(row))
            if row["rank"] <= 3:
                color_line = _color_line(color, row["wallet"])
                if color_line:
                    lines.append(color_line)
    else:
        lines.append(board["rows_note"])
    if board["excluded_thin"]:
        lines.append(
            f"(+{board['excluded_thin']} caller(s) under {board['min_n']} measured calls "
            "this window — a record needs evidence, not one lucky print)"
        )

    lines += ["", f"MOST-CALLED COINS ({board['window_days']}d)"]
    if board["coins"]:
        for coin in board["coins"]:
            m = coin["measured_24h"]
            measured_bit = (
                f"median 24h {fmt_pct(m['median'])} (n={m['n']})" if m["n"] else m["absent"]
            )
            plural = "s" if coin["n_callers"] != 1 else ""
            lines.append(
                f"{PUMP_COIN_URL.format(mint=coin['mint'])} · {coin['n_callouts']} callouts / "
                f"{coin['n_callers']} caller{plural} · {measured_bit}"
            )
    else:
        lines.append(board["coins_note"])

    lines += ["", "CLAIMED vs MEASURED — widest gaps (their peak multiple vs our close series)"]
    if board["gaps"]:
        for gap in board["gaps"]:
            ret_bit = fmt_pct(gap["ret_24h"]) if gap["ret_24h"] is not None else "unpriced"
            lines.append(
                f"{gap['handle']} · {PUMP_COIN_URL.format(mint=gap['mint'])} · "
                f"claimed {fmt_mult(gap['claimed_multiple'])} · measured close-peak "
                f"{fmt_mult(gap['measured_close_multiple'])} · 24h {ret_bit}"
            )
    else:
        lines.append(board["gaps_note"])

    lines += ["", "Any caller's full record: DM me /caller <wallet or @name>."]
    lines += ["", REMOVAL_LINE, STANDING_LINE]
    text = "\n".join(lines)
    # Sized by construction (clamped handles, capped rows); the assert is the belt.
    assert len(text) <= TELEGRAM_MAX, "leaderboard text exceeded Telegram's cap"
    return text


def render_markdown(board: dict) -> str:
    """The site/wire artifact: same numbers, table form, same standing lines."""

    title = (
        f"# The Callout Record — trailing {board['window_days']}d "
        f"({board['window_start']}..{board['window_end']} UTC)"
    )
    if "absent" in board:
        return "\n".join([title, "", board["absent"], "", f"*{STANDING_LINE}*", ""])
    lines = [
        title,
        "",
        f"Ranked by **median measured 24h return** (min {board['min_n']} measured calls; "
        f"outcomes method {board['method_version']}, our candle closes). Provider multiples "
        "appear only as their claims.",
        "",
    ]
    cov = board["coverage"]
    lines += [
        f"Coverage: {cov['n_callouts']} callouts by {cov['n_callers']} callers; "
        f"{cov['n_measured_24h']} with a measured 24h close."
        + (f" *({cov['note']})*" if cov["note"] else ""),
        "",
    ]
    if board["rows"]:
        lines += [
            "| # | caller | median 24h | mean 24h | n | >0% | dead by 7d | claimed (theirs) | removals |",
            "|--:|---|--:|--:|--:|--:|--:|--:|--:|",
        ]
        for row in board["rows"]:
            dead = row["dead"]
            dead_bit = f"{dead['n_dead']}/{dead['n_final']}" if dead["n_final"] else "pending"
            claim = row["claim"]
            claim_bit = fmt_mult(claim["median_multiple"]) if claim["n"] else "—"
            lines.append(
                f"| {row['rank']} | {row['handle']} (`{short_wallet(row['wallet'])}`) "
                f"| {fmt_pct(row['median_ret_24h'])} | {fmt_pct(row['mean_ret_24h'])} "
                f"| {row['n_measured']} | {row['above_0']}/{row['n_measured']} | {dead_bit} "
                f"| {claim_bit} | {row['removals_published']} |"
            )
    else:
        lines.append(board["rows_note"])
    if board["excluded_thin"]:
        lines.append(
            f"\n*{board['excluded_thin']} caller(s) held under the {board['min_n']}-measured-call gate.*"
        )

    lines += ["", f"## Most-called coins ({board['window_days']}d)", ""]
    if board["coins"]:
        for coin in board["coins"]:
            m = coin["measured_24h"]
            measured_bit = (
                f"median 24h {fmt_pct(m['median'])} (n={m['n']})" if m["n"] else m["absent"]
            )
            plural = "s" if coin["n_callers"] != 1 else ""
            lines.append(
                f"- [`{coin['mint']}`]({PUMP_COIN_URL.format(mint=coin['mint'])}) — "
                f"{coin['n_callouts']} callouts / {coin['n_callers']} caller{plural} · {measured_bit}"
            )
    else:
        lines.append(f"*{board['coins_note']}*")

    lines += ["", "## Claimed vs measured — widest gaps", ""]
    if board["gaps"]:
        for gap in board["gaps"]:
            ret_bit = fmt_pct(gap["ret_24h"]) if gap["ret_24h"] is not None else "unpriced"
            lines.append(
                f"- {gap['handle']} on [`{gap['mint']}`]({PUMP_COIN_URL.format(mint=gap['mint'])}): "
                f"claimed {fmt_mult(gap['claimed_multiple'])} vs measured close-peak "
                f"{fmt_mult(gap['measured_close_multiple'])} · 24h {ret_bit}"
            )
    else:
        lines.append(f"*{board['gaps_note']}*")

    color = board["caller_color"]
    lines += ["", "## Wallet layer (color only)", ""]
    if "entries" in color:
        lines.append(f"As of {color['as_of']} — **stale**; {color['note']}.")
        for entry in color["entries"]:
            if "absent" in entry:
                lines.append(f"- `{short_wallet(entry['wallet'])}` — {entry['absent']}")
            else:
                win = entry.get("win_rate")
                win_bit = (
                    f", win {win:.0%} over {entry.get('n_coins_closed')} closed"
                    if win is not None
                    else ""
                )
                lines.append(
                    f"- `{short_wallet(entry['wallet'])}` — realized "
                    f"{entry.get('net_realized_sol'):+,.1f} SOL{win_bit}, {entry.get('rp_mode')}"
                )
    else:
        lines.append(f"*{color.get('absent')}* — {color.get('note')}")

    lines += ["", f"*{REMOVAL_LINE}*", "", f"*{STANDING_LINE}*", ""]
    return "\n".join(lines)
