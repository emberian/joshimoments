"""The dossier cards: PLAIN TEXT, bare URLs, honesty lines welded on.

NO HTML, NO parse_mode — the dregg_feed/compose.py discipline: Telegram auto-links bare
URLs, and plain text makes every interpolated string literal-inert. The only strings a
card interpolates are (a) our own copy, (b) numbers, and (c) addresses that already
parsed as base58 pubkeys upstream — nothing here can smuggle markup, and the test suite
asserts no "<" ever appears in a rendered card.

Three lines are constants, not options, per state/wallets/JOIN_CONTRACT.md:
* the as-of stamp (rule 2: this is a batch layer over a fixed corpus, not live);
* the executable-PnL framing (realized-only; unsold bags are never marked into profit);
* the timing caveat (rule 3: timing_q ranks distribution intensity, it does not convict).

Misses render as null-with-reason (rule 1): an absent wallet is below the activity
floor, an absent exit row is a clean no-signal, an absent coin is outside the corpus —
never a zero, never a clean bill.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

PUMP_COIN_URL = "https://pump.fun/coin/{mint}"
SOLSCAN_URL = "https://solscan.io/account/{owner}"

#: Rule 3, rendered verbatim on every card that shows distribution rows.
TIMING_CAVEAT = (
    "timing ranks distribution intensity; it does not prove chart management — filling "
    "a big exit needs buyers present. Read it as an exit tell: a large bag is leaving."
)

#: The executable-PnL discipline, rendered wherever a PnL figure appears.
PNL_FRAMING = "Realized-only, executable pricing: unsold bags are never marked into profit."

_GUILD_BLURB = {
    "FLASH": "in and out inside a minute",
    "HARVESTER": "rides launches for minutes to an hour",
    "SLOW": "holds for hours",
    "ACCUMULATOR": "keeps buying, rarely exits (sells under 20% of what it buys)",
    "AFTERMARKET": "trades established coins rather than sniping launches",
}

_RP_BLURB = {
    "BREAKEVEN_PRESET": (
        "over 40% of its sells land within 5% of cost — the signature of a "
        "Trojan/BullX/Photon-style break-even preset bot"
    ),
    "LOSS_CUTTER": "most sells land in the red — it cuts losers rather than riding them",
    "PROFIT_RUNNER": "typically realizes deep into profit before selling",
    "AVERAGES_DOWN": "keeps buying below its own cost through drawdowns — conviction or bagholding",
    "MIXED": "no single realization habit dominates its sells",
}


# -- shared formatting ----------------------------------------------------------------


def fmt_sol(value: float | None, *, signed: bool = True) -> str:
    if value is None:
        return "n/a"
    sign = "+" if signed else ""
    if abs(value) >= 100:
        return f"{value:{sign},.0f} SOL"
    if abs(value) >= 1:
        return f"{value:{sign},.2f} SOL"
    return f"{value:{sign}.3f} SOL"


def fmt_dur(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    seconds = float(seconds)
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} d"


def fmt_pct(numerator: float, denominator: float) -> str:
    if denominator <= 0:
        return "n/a"
    return f"{100 * numerator / denominator:.0f}%"


def short(address: str) -> str:
    return f"{address[:4]}..{address[-4:]}" if len(address) > 12 else address


def as_of_line(meta: dict[str, Any], now: float) -> str:
    """Rule 2: every card says what window this is and how stale it has become."""

    span = meta.get("corpus_span") or ["?", "?"]
    end = meta.get("updated_through")
    stale = ""
    if end:
        days = max(0, int((now - end) / 86400))
        end_text = datetime.fromtimestamp(end, UTC).strftime("%Y-%m-%d %H:%M UTC")
        stale = f"; data ends {end_text}, {days} days old"
    return (
        f"Built from trades of {span[0]}..{span[1]}{stale}. "
        "A periodic snapshot, not a live feed."
    )


def crowd_line(meta: dict[str, Any]) -> str:
    crowd = meta.get("crowd") or {}
    total = crowd.get("net_realized_sol_sum")
    frac = crowd.get("frac_positive")
    if total is None or frac is None:
        return ""
    return (
        f"Context: across all {meta.get('n_wallets', 0):,} profiled wallets the crowd "
        f"netted {total:+,.0f} SOL this window; only {100 * frac:.1f}% closed positive."
    )


# -- /wallet --------------------------------------------------------------------------


def _guild_line(row: dict[str, Any], meta: dict[str, Any]) -> str:
    guild = row["guild"]
    blurb = _GUILD_BLURB.get(guild, "unclassified pattern")
    stats = (meta.get("guild_stats") or {}).get(guild) or {}
    extra = ""
    if stats:
        extra = (
            f" (guild of {stats.get('n', 0):,}: median wallet {fmt_sol(stats.get('median_net_sol'))}, "
            f"{100 * stats.get('breakeven_preset_rate', 0):.0f}% run break-even presets)"
        )
    basis = (
        "classified with its co-trading cluster"
        if row.get("guild_cluster")
        else "classified on its own record"
    )
    return f"Guild: {guild} — {blurb}{extra} ({basis})"


def wallet_card(row: dict[str, Any], meta: dict[str, Any], now: float) -> str:
    owner = row["owner"]
    lines = [
        f"WALLET DOSSIER {short(owner)}",
        SOLSCAN_URL.format(owner=owner),
        "",
        _guild_line(row, meta),
        f"Policy: {row['rp_mode']} — {_RP_BLURB.get(row['rp_mode'], 'unlabeled')}",
        "",
        (
            f"Record: {fmt_sol(row['net_realized_sol'])} realized across {row['n_coins']:,} coins "
            f"({row['n_legs']:,} legs, {row['active_days']} active days)."
        ),
    ]
    if row["n_coins_closed"]:
        lines.append(
            f"Closed positions: {row['n_coins_win']:,} of {row['n_coins_closed']:,} green "
            f"({fmt_pct(row['n_coins_win'], row['n_coins_closed'])} win rate), "
            f"median {fmt_sol(row['median_realized_sol_closed'])} per closed coin."
        )
    else:
        lines.append("Closed positions: none in-window — win rate has no basis yet, so none is quoted.")
    lines.append(PNL_FRAMING)
    lines.append("")
    hold = f"Median hold {fmt_dur(row['median_hold_s'])} (p90 {fmt_dur(row['p90_hold_s'])})."
    if row["median_entry_latency_s"] is not None:
        hold += f" Enters a median {fmt_dur(row['median_entry_latency_s'])} after launch."
    lines.append(hold)
    traits = []
    if row["on_ladder"]:
        traits.append("runs on the 8-second scheduler ladder (automation, not a human)")
    if row["in_rotation"]:
        traits.append(
            f"in the mercenary rotation cohort ({row['rotation_hours']} active hours) — "
            "capital that hops coin to coin"
        )
    if row["rp_frac_breakeven"] and row["rp_frac_breakeven"] > 0.10:
        traits.append(f"{100 * row['rp_frac_breakeven']:.0f}% of sells land within 5% of cost")
    if traits:
        lines.append("Tells: " + "; ".join(traits) + ".")
    context = crowd_line(meta)
    if context:
        lines.extend(["", context])
    lines.append("")
    lines.append(
        f"Next: /watch deployer {owner} DMs you if this wallet ever launches a coin."
    )
    lines.append(as_of_line(meta, now))
    return "\n".join(lines)


def wallet_miss(owner: str, meta: dict[str, Any], now: float) -> str:
    span = meta.get("corpus_span") or ["?", "?"]
    return "\n".join(
        [
            f"No dossier for {short(owner)}.",
            "",
            (
                f"That wallet is below the activity threshold (fewer than 3 priced trades) "
                f"in the {span[0]}..{span[1]} data window — an absence of data, not a zero "
                "score and not a clean bill. It may be new, dormant that week, or trading "
                "outside the pump.fun crowd this data covers."
            ),
            "",
            f"You can still /watch deployer {owner} to hear if it ever launches a coin.",
            as_of_line(meta, now),
        ]
    )


# -- /coin ----------------------------------------------------------------------------


def _comp_lines(comp: dict[str, Any], meta: dict[str, Any]) -> list[str]:
    source = meta.get("comp_source")
    who = (
        "Who traded it"
        if source == "trades"
        else "Significant holders (peaked at 0.1%+ of supply)"
    )
    n_traders = comp["n_traders"]
    n_profiled = comp["n_profiled"]
    lines = [
        (
            f"{who}: {n_traders:,} wallets; {n_profiled:,} profiled "
            "(3+ priced trades across our data)."
        )
    ]
    if n_profiled:
        mix = [
            (comp["n_harvester"], "harvester"),
            (comp["n_flash"], "flash"),
            (comp["n_slow"], "slow"),
            (comp["n_accumulator"], "accumulator"),
            (comp["n_aftermarket"], "aftermarket"),
        ]
        mix_text = " / ".join(
            f"{fmt_pct(n, n_profiled)} {name}" for n, name in sorted(mix, reverse=True) if n
        )
        lines.append(f"Guild mix: {mix_text}.")
        n_preset = comp["n_breakeven_preset"]
        lines.append(
            f"Preset bots: {n_preset:,} break-even-preset wallet{'s' if n_preset != 1 else ''} "
            f"({fmt_pct(n_preset, n_profiled)} of profiled). "
            f"Mercenary rotation (capital that hops coin to coin): "
            f"{fmt_pct(comp['n_in_rotation'], n_profiled)}. "
            f"Clockwork bots (trading on a fixed 8s schedule): {comp['n_on_ladder']:,}."
        )
        lines.append(
            f"Track records: {fmt_pct(comp['n_net_positive'], n_profiled)} of its profiled "
            "traders closed the window net-positive."
        )
    return lines


def _crew_lines(crews: list[dict[str, Any]], meta: dict[str, Any]) -> list[str]:
    if not meta.get("crew_ledger"):
        return ["Crews: the crew ledger was not reachable at build time — unknown, not clear."]
    if not crews:
        return ["Crews: no fingerprinted-crew launch or trader overlap on record."]
    lines = []
    for crew in crews:
        record = f"{crew['crew_rips']} rips / {crew['crew_dumps']} insider dumps"
        if crew["launched_by"] and crew["dirty"]:
            lines.append(
                f"Crews: LAUNCHED by fingerprinted crew #{crew['crew_id']} "
                f"({crew['crew_coins']} tracked coins, {record})."
            )
        elif crew["launched_by"]:
            # The ledger's own discipline: reuse of a CLEAN crew is continuity, not a
            # crime record — name it a serial deployer and show the clean record.
            lines.append(
                f"Crews: launched by a serial deployer (crew #{crew['crew_id']}: "
                f"{crew['crew_coins']} tracked coins, no rips or dumps on record)."
            )
        else:
            lines.append(
                f"Crew overlap: {crew['n_overlap']} of its wallets appear in crew "
                f"#{crew['crew_id']}'s birth-slot sets ({record})."
            )
    lines.append("(Trader overlap is participation context, not a fingerprint match.)")
    return lines


def _iceberg_lines(exit_row: dict[str, Any] | None, icebergs: list[dict[str, Any]]) -> list[str]:
    if exit_row is None:
        return [
            "Exit signal: no large holder tripped the distribution screen — a clean no-signal "
            "(nobody who peaked at 0.1%+ of supply drew down 60%+ across 8+ sells), "
            "not a zero score."
        ]
    # The contract's exit flag: n_timing_pass >= 1 AND any_recent. Anything short of
    # that renders as distribution WITHOUT the alarm head — DREGG itself is the honest
    # baseline here (4 distributors, 0 timing passes: benign chunked DCA-out).
    flag = bool(exit_row["n_timing_pass"] >= 1 and exit_row["any_recent"])
    n = exit_row["n_distributors"]
    plural = "s" if n != 1 else ""
    if flag:
        head = (
            f"EXIT SIGNAL: {n} large holder{plural} piecewise-distributing — "
            f"{exit_row['n_timing_pass']} passed the timing screen, recently active."
        )
    else:
        head = (
            f"Distribution: {n} large holder{plural} drew bags down piecewise; none "
            "passed the timing screen — consistent with benign chunked selling."
        )
    lines = [head]
    for row in icebergs:
        when = "?"
        if row["last_dist_t"]:
            when = datetime.fromtimestamp(row["last_dist_t"], UTC).strftime("%m-%d")
        propped = (row["resilience"] or 0) >= 0
        price = "price held or rose while it sold" if propped else "price fell as it sold"
        timing = (
            f"timing score {row['timing_q']:.2f} of 1"
            if row["timing_q"] is not None
            else "timing untested"
        )
        lines.append(
            f"- {short(row['owner'])}: fed out {fmt_sol(row['dist_sold_sol'], signed=False)} in "
            f"{row['n_dist_sells']:,} sells over {fmt_dur(row['duration_s'])} "
            f"({100 * (row['drawdown'] or 0):.0f}% of its peak bag); {price}; {timing}; "
            f"last sell {when}."
        )
    lines.append(f"Caveat: {TIMING_CAVEAT}")
    return lines


def coin_card(mint: str, view: dict[str, Any], meta: dict[str, Any], now: float) -> str:
    lines = [
        f"COIN DOSSIER {short(mint)}",
        PUMP_COIN_URL.format(mint=mint),
        "",
        *_comp_lines(view["comp"], meta),
        "",
        *_crew_lines(view["crews"], meta),
        "",
        *_iceberg_lines(view["exit"], view["icebergs"]),
        "",
        (
            f"Next: /wallet plus any address above profiles that trader · "
            f"/watch coin {mint} for DM alerts."
        ),
        as_of_line(meta, now),
    ]
    return "\n".join(lines)


def coin_miss(mint: str, meta: dict[str, Any], now: float) -> str:
    span = meta.get("corpus_span") or ["?", "?"]
    return "\n".join(
        [
            f"No dossier for {short(mint)} ({PUMP_COIN_URL.format(mint=mint)}).",
            "",
            (
                f"That coin is outside the {span[0]}..{span[1]} data window this was built "
                "on (33k active launches plus the operator coins) — launched outside the "
                "window, or too quiet to clear its floor. No data, not a clean bill. "
                "/screen covers launches from the last two days."
            ),
            "",
            as_of_line(meta, now),
        ]
    )
