"""Assemble and render the session debrief: the recap she rereads over coffee.

One markdown artifact per operator day (UTC), reconstructed from durable records only.
The rendering rules are the house honesty rules, applied to prose:

  - her words are quoted VERBATIM or not at all -- never summarized, never trimmed;
  - absent is absent: a coin with no post-hold observation is an absent record, stated in
    those words, never a zero and never a guess;
  - every number carries its clock and its source;
  - no net-of-fees claim is made for a coin unless a venue floor was measured for that
    coin -- and no per-coin floor measurement store exists yet, so the artifact says
    "floor unmeasured" instead of borrowing a number;
  - the instrument's tally REPORTS the selection measurement (selection/report.py) and the
    pre-registered power requirement (selection/power.py, constants frozen in
    selection/preregistration.py); the debrief never re-scores by rules of its own;
  - a section with nothing to say says so in one line.

The artifact states what it is: a reconstruction from durable records, listing what it
could not reconstruct.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from joshi_analysis.selection.events import BLOB_AGREES, SelectionEventV1
from joshi_analysis.selection.preregistration import (
    CHOICE_SET_KIND_PREFERENCE,
    HORIZONS_SECONDS,
    PREREGISTERED_ON,
    PREREGISTRATION_ID,
    PRIMARY_HORIZON_SECONDS,
)
from joshi_analysis.selection.report import SelectionReportV1, build_report

from .stores import (
    US,
    MintCatalogView,
    OperatorAct,
    PairedWindow,
    Reading,
    read_live_scenes,
    read_mint_catalog_view,
    read_operator_acts,
    read_paired_windows,
    read_witnessed_scenes,
)

#: Effects the power tally quotes, read off the pre-registered power tables: the 0.10
#: rank shift is the skill verdict's yardstick, the 0.05 net log is the tradeable-edge
#: yardstick. Both numbers are COMPUTED from selection/power.py at render time.
SKILL_RANK_SHIFT = 0.10
EDGE_NET_LOG = 0.05

_EXCLUSION_GLOSS = {
    "act_names_no_candidate": "acts naming no candidate (scene-bound journal/focus acts; "
    "journal material, not selections)",
    "act_bound_to_no_scene": "acts bound to no scene, so no choice set exists for them",
    "act_subject_absent_from_choice_set": "acts naming a coin absent from the scene's "
    "choice set",
    "scene_recorded_no_choice_set": "acts on scenes that recorded no choice set",
    "scene_chosen_set_is_whole_choice_set": "acts marking every candidate in the scene "
    "(no counterfactual remains)",
}


# --- assembled inputs -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DebriefInputs:
    """Everything read from the stores, before any per-day partitioning."""

    session_state: Path
    catalog_dir: Path
    catalog_sqlite: Path | None
    acts: tuple[OperatorAct, ...]
    mint_view: MintCatalogView
    paired: tuple[PairedWindow, ...]
    live_scenes: tuple
    witnessed: tuple
    selection: SelectionReportV1
    store_notes: tuple[str, ...]


def read_inputs(session_state: Path, catalog_dir: Path) -> DebriefInputs:
    session_state = Path(session_state)
    catalog_dir = Path(catalog_dir)
    notes: list[str] = []
    catalog_sqlite: Path | None = catalog_dir / "catalog.sqlite"
    if not catalog_sqlite.is_file():
        notes.append(
            f"no catalog at {catalog_sqlite}; acts, scenes and readings cannot be reconstructed"
        )
        catalog_sqlite = None
    acts: list[OperatorAct] = []
    mint_view = MintCatalogView()
    witnessed = []
    if catalog_sqlite is not None:
        acts = read_operator_acts(catalog_sqlite)
        mint_view = read_mint_catalog_view(catalog_sqlite)
        witnessed = read_witnessed_scenes(catalog_sqlite)
    paired, pairing_notes = read_paired_windows(session_state)
    live_scenes, live_notes = read_live_scenes(session_state)
    notes.extend(pairing_notes)
    notes.extend(live_notes)
    selection = build_report([catalog_sqlite] if catalog_sqlite is not None else [])
    return DebriefInputs(
        session_state=session_state,
        catalog_dir=catalog_dir,
        catalog_sqlite=catalog_sqlite,
        acts=tuple(acts),
        mint_view=mint_view,
        paired=tuple(paired),
        live_scenes=tuple(live_scenes),
        witnessed=tuple(witnessed),
        selection=selection,
        store_notes=tuple(notes),
    )


def _day_of(wall_us: int) -> str:
    return datetime.fromtimestamp(wall_us / US, tz=UTC).date().isoformat()


def session_days(inputs: DebriefInputs) -> list[str]:
    """Every UTC day any durable session record touches, oldest first."""
    days: set[str] = set()
    for act in inputs.acts:
        days.add(_day_of(act.issued_wall_us))
    for window in inputs.paired:
        days.add(_day_of(window.established_wall_us))
    for scene in inputs.live_scenes:
        if scene.derived_wall_us is not None:
            days.add(_day_of(scene.derived_wall_us))
    for scene in inputs.witnessed:
        days.add(_day_of(scene.rendered_wall_us))
    return sorted(days)


# --- formatting -----------------------------------------------------------------------


def _iso(wall_us: int) -> str:
    return (
        datetime.fromtimestamp(wall_us / US, tz=UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _clock(wall_us: int, day: str) -> str:
    """Time-of-day when the instant falls on the artifact's day, full instant otherwise."""
    full = _iso(wall_us)
    return full[11:] if full.startswith(day) else full


def _duration(us: int) -> str:
    seconds = abs(us) // US
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s" if seconds else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h" if hours else f"{days}d"


def _price(value: float) -> str:
    return f"{value:.10g} SOL"


def _mcap(value: float) -> str:
    return f"${value:,.0f}"


def _pct(now: float, base: float) -> str:
    return f"{(now / base - 1.0) * 100:+.1f}%"


def _quote(words: str) -> list[str]:
    return [f"> {line}" if line else ">" for line in words.split("\n")]


# --- held coins -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoinDay:
    mint: str
    first_hold: OperatorAct | None
    holds_today: tuple[OperatorAct, ...]
    words_today: tuple[OperatorAct, ...]


def _coins_of_day(acts: tuple[OperatorAct, ...], day: str) -> list[CoinDay]:
    """Coins touched this day: held today, or spoken about today. Hold order first."""
    first_hold: dict[str, OperatorAct] = {}
    for act in acts:
        if act.is_hold and act.subject_key not in first_hold:
            first_hold[act.subject_key] = act
    holds_today: dict[str, list[OperatorAct]] = {}
    words_today: dict[str, list[OperatorAct]] = {}
    anchor: dict[str, int] = {}
    for act in acts:
        if act.subject_kind != "candidate" or _day_of(act.issued_wall_us) != day:
            continue
        if act.is_hold:
            holds_today.setdefault(act.subject_key, []).append(act)
            anchor.setdefault(act.subject_key, act.issued_wall_us)
        elif act.verbatim or not act.payload_readable:
            words_today.setdefault(act.subject_key, []).append(act)
            anchor.setdefault(act.subject_key, act.issued_wall_us)
    return [
        CoinDay(
            mint=mint,
            first_hold=first_hold.get(mint),
            holds_today=tuple(holds_today.get(mint, [])),
            words_today=tuple(words_today.get(mint, [])),
        )
        for mint in sorted(anchor, key=lambda m: anchor[m])
    ]


def _coin_heading(mint: str, view: MintCatalogView) -> str:
    symbol, name = view.identity.get(mint, (None, None))
    if symbol and name:
        return f"{symbol} — {name} (`{mint}`)"
    if symbol or name:
        return f"{symbol or name} (`{mint}`)"
    return f"`{mint}` — no ticker or name was observed in any retained scene"


def _reading_line(reading: Reading, base: Reading | None, hold_us: int, day: str) -> str:
    offset = reading.clock_wall_us - hold_us
    parts: list[str] = []
    if reading.price_sol is not None:
        delta = (
            f" ({_pct(reading.price_sol, base.price_sol)} vs the held scene)"
            if base is not None and base.price_sol
            else ""
        )
        parts.append(f"price {_price(reading.price_sol)}{delta}")
    if reading.market_cap_usd is not None:
        delta = (
            f" ({_pct(reading.market_cap_usd, base.market_cap_usd)})"
            if base is not None and base.market_cap_usd
            else ""
        )
        parts.append(f"mcap {_mcap(reading.market_cap_usd)}{delta}")
    figures = ", ".join(parts) if parts else "no price or mcap figure"
    return (
        f"+{_duration(offset)} after the hold: {figures} — provider-asserted, observed "
        f"{_clock(reading.clock_wall_us, day)} (source {reading.source_label}, "
        f"scene `{reading.scene_id}`)"
    )


def _render_coin(coin: CoinDay, view: MintCatalogView, day: str, out: list[str]) -> None:
    out.append(f"### {_coin_heading(coin.mint, view)}")
    out.append("")
    hold = coin.first_hold
    if hold is not None:
        when = _clock(hold.issued_wall_us, day)
        scene = f" over scene `{hold.scene_id}`" if hold.scene_id else " bound to no scene"
        prior = "" if _day_of(hold.issued_wall_us) == day else " (held on an earlier day)"
        out.append(f"- held at {when}{scene}{prior}")
        extra = [a for a in coin.holds_today if a.command_id != hold.command_id]
        if extra:
            times = ", ".join(_clock(a.issued_wall_us, day) for a in extra)
            out.append(f"- held again at {times}")
    else:
        out.append("- never held — words only; no forward path is anchored without a hold")
    if coin.words_today:
        out.append("- her words, verbatim:")
        for act in coin.words_today:
            when = _clock(act.issued_wall_us, day)
            if not act.payload_readable:
                out.append(
                    f"  - {when} — the act's payload blob is not readable; whatever words "
                    "it carried are not reconstructable"
                )
                continue
            for words in act.verbatim:
                out.append(f"  - {when} — {words.label}:")
                out.extend("    " + line for line in _quote(words.words))
    elif any(a.verbatim for a in coin.holds_today):
        out.append("- her words, verbatim: (carried on the hold acts below)")
    else:
        out.append("- no words were recorded for this coin; the hold itself was the statement")
    for act in coin.holds_today:
        for words in act.verbatim:
            out.append(f"  - {_clock(act.issued_wall_us, day)} — {words.label}:")
            out.extend("    " + line for line in _quote(words.words))
    if hold is None:
        out.append("")
        return
    base = (
        view.reading_in_scene(coin.mint, hold.scene_id) if hold.scene_id is not None else None
    )
    if base is not None:
        figures = []
        if base.price_sol is not None:
            figures.append(f"price {_price(base.price_sol)}")
        if base.market_cap_usd is not None:
            figures.append(f"mcap {_mcap(base.market_cap_usd)}")
        age = hold.issued_wall_us - base.clock_wall_us
        out.append(
            f"- at the hold: {', '.join(figures)} — provider-asserted, observed "
            f"{_clock(base.clock_wall_us, day)} ({_duration(age)} before the act; "
            f"source {base.source_label}, scene `{base.scene_id}`)"
        )
    elif hold.scene_id is None:
        out.append("- at the hold: the act is bound to no scene, so no at-hold reading exists")
    else:
        out.append(
            "- at the hold: the decision scene retained no price or mcap for this mint "
            "(an absent record, not a zero)"
        )
    forward = view.readings_after(coin.mint, hold.issued_wall_us)
    if not forward:
        out.append(
            "- forward path: ABSENT RECORD — no retained observation of this mint after "
            "the hold. That is a gap in observation, not a zero and not a guess."
        )
    else:
        first, last = forward[0], forward[-1]
        span = (
            f"spanning {_clock(first.clock_wall_us, day)} to {_clock(last.clock_wall_us, day)}"
            if len(forward) > 1
            else f"at {_clock(first.clock_wall_us, day)}"
        )
        out.append(
            f"- forward path, from retained post-hold observations only "
            f"({len(forward)} reading(s), {span}):"
        )
        out.append(f"  - first: {_reading_line(first, base, hold.issued_wall_us, day)}")
        if len(forward) > 1:
            out.append(f"  - latest: {_reading_line(last, base, hold.issued_wall_us, day)}")
    out.append(
        "- venue floor: unmeasured for this coin — no net-of-fees claim is made. "
        "(No per-coin floor measurement exists in the stores.)"
    )
    out.append("")


# --- sections -------------------------------------------------------------------------


def _render_shape(inputs: DebriefInputs, day: str, out: list[str]) -> None:
    out.append("## 1. The session's shape")
    out.append("")
    paired_today = [w for w in inputs.paired if _day_of(w.established_wall_us) == day]
    if paired_today:
        for window in paired_today:
            line = f"- paired at {_clock(window.established_wall_us, day)}"
            if window.lease_expires_wall_us is not None:
                line += f" (lease to {_clock(window.lease_expires_wall_us, day)})"
            if window.ended_wall_us is not None:
                reason = f": {window.ended_reason}" if window.ended_reason else ""
                line += (
                    f"; ended {_clock(window.ended_wall_us, day)} "
                    f"({window.ended_kind}{reason})"
                )
            else:
                line += "; no end was recorded"
            line += f" — `{window.session_id}`"
            out.append(line)
    else:
        out.append(
            "- no pairing record for this day: either no cockpit was paired or the "
            "pairing store did not retain it"
        )
    out.append("")
    witnessed_today = [s for s in inputs.witnessed if _day_of(s.rendered_wall_us) == day]
    if witnessed_today:
        out.append(f"- witnessed scenes durably recorded: {len(witnessed_today)}")
        shown = witnessed_today[:12]
        for scene in shown:
            out.append(
                f"  - {_clock(scene.rendered_wall_us, day)} `{scene.scene_id}` "
                f"({scene.scene_mode})"
            )
        if len(witnessed_today) > len(shown):
            out.append(f"  - … and {len(witnessed_today) - len(shown)} more")
    else:
        out.append("- no witnessed scene was durably recorded this day")
    live_today = [
        s
        for s in inputs.live_scenes
        if s.derived_wall_us is not None and _day_of(s.derived_wall_us) == day
    ]
    if live_today:
        first, last = live_today[0], live_today[-1]
        retired = sum(1 for s in live_today if s.retired_wall_us is not None)
        out.append(
            f"- live-follow advanced through {len(live_today)} scene(s), "
            f"{_clock(first.derived_wall_us, day)} to {_clock(last.derived_wall_us, day)}"
            + (f"; {retired} later retired" if retired else "")
        )
        out.append(
            "  (from the rolling follow-state file, which keeps only the current "
            "generation's list — earlier advancement may be absent, not disproven)"
        )
    else:
        out.append(
            "- no live-follow scene advancement is retained for this day (the follow "
            "state is a rolling file; absence here is not proof none happened)"
        )
    out.append("")
    acts_today = [a for a in inputs.acts if _day_of(a.issued_wall_us) == day]
    if acts_today:
        first, last = acts_today[0], acts_today[-1]
        span = last.issued_wall_us - first.issued_wall_us
        out.append(
            f"- attended, as marked by durable acts: {len(acts_today)} act(s), "
            f"{_clock(first.issued_wall_us, day)} to {_clock(last.issued_wall_us, day)} "
            f"({_duration(span)})"
        )
    else:
        out.append(
            "- attended: no durable operator act marks attended time this day; the "
            "pairing windows above are the only attendance evidence retained"
        )
    out.append("")
    journal_today = [
        a
        for a in inputs.acts
        if a.is_journal_entry and a.verbatim and _day_of(a.issued_wall_us) == day
    ]
    out.append("### Said over the scenes")
    out.append("")
    if journal_today:
        for act in journal_today:
            scene = f" over scene `{act.subject_key}`" if act.subject_kind == "scene" else ""
            out.append(f"- {_clock(act.issued_wall_us, day)}{scene}:")
            for words in act.verbatim:
                out.extend("  " + line for line in _quote(words.words))
    else:
        out.append("- no scene journal entries were recorded this day")
    out.append("")


def _render_tally(inputs: DebriefInputs, day: str, out: list[str]) -> None:
    out.append("## 3. The instrument's tally")
    out.append("")
    report = inputs.selection
    out.append(
        f"Reported from the pre-registered selection instrument "
        f"(`{PREREGISTRATION_ID}`, frozen {PREREGISTERED_ON}). The debrief reports; "
        f"it never re-scores by rules of its own."
    )
    out.append("")
    day_events = [e for e in report.events if _day_of(e.decision_wall_us) == day]
    day_ids = {e.event_id for e in day_events}
    per_h_day = {
        h: sum(1 for o in report.outcomes.get(h, []) if o.event_id in day_ids and o.is_scored)
        for h in HORIZONS_SECONDS
    }
    sc = report.scores.get(PRIMARY_HORIZON_SECONDS)
    out.append(
        f"- this day: {len(day_events)} selection event(s) reconstructed; scored at "
        f"{PRIMARY_HORIZON_SECONDS}s (headline): {per_h_day.get(PRIMARY_HORIZON_SECONDS, 0)}"
        + (
            "; at "
            + ", ".join(
                f"{h}s: {per_h_day[h]}" for h in HORIZONS_SECONDS if h != PRIMARY_HORIZON_SECONDS
            )
            if day_events
            else ""
        )
    )
    if sc is not None:
        out.append(
            f"- cumulative, whole catalog: {sc.n_events} event(s); scored at "
            f"{PRIMARY_HORIZON_SECONDS}s: {sc.n_scored}"
        )
    _render_denominators(day_events, report.events, out)
    stmt = report.power
    skill_row = next((r for r in stmt.s1_rows if r.effect == SKILL_RANK_SHIFT), None)
    edge_row = next((r for r in stmt.s3_rows if r.effect == EDGE_NET_LOG), None)
    if skill_row is not None and edge_row is not None:
        out.append(
            f"- against the pre-registered requirement (computed from the frozen "
            f"constants, not re-derived): the skill verdict (S1, a {SKILL_RANK_SHIFT:.2f} "
            f"rank shift at k={stmt.choice_set_size}) needs ~{skill_row.scenes_needed} "
            f"scored scenes; the tradeable edge (S3, {EDGE_NET_LOG:.2f} net log, a LOWER "
            f"bound on heavy tails) needs ~{edge_row.scenes_needed}"
        )
    if sc is not None:
        out.append(f"- the instrument's own verdict at the headline horizon: **{sc.verdict}**")
        out.extend(_quote(sc.verdict_note))
    holds_total = sum(1 for a in inputs.acts if a.is_hold)
    out.append("")
    out.append(
        f"Caveats the pre-registration itself insists on: the first ten holds prove "
        f"nothing (holds durably recorded so far, all days: {holds_total}); absent "
        f"outcomes are counted, never zero-filled; horizons and scoring were frozen "
        f"{PREREGISTERED_ON}, before any real result."
    )
    out.append("")


def _render_denominators(
    day_events: list[SelectionEventV1],
    all_events: tuple[SelectionEventV1, ...],
    out: list[str],
) -> None:
    def census(events) -> str:
        counts = {kind: 0 for kind in CHOICE_SET_KIND_PREFERENCE}
        for event in events:
            counts[event.choice_set_kind] = counts.get(event.choice_set_kind, 0) + 1
        return ", ".join(f"{kind}: {n}" for kind, n in counts.items())

    out.append(
        f"- denominator kinds used (viewport is the honest set; rendered is the "
        f"fallback) — this day: {census(day_events)}; cumulative: {census(all_events)}"
    )


def _render_integrity(inputs: DebriefInputs, day: str, out: list[str]) -> None:
    out.append("## 4. Integrity footnotes")
    out.append("")
    lines: list[str] = []
    merged: dict[str, int] = {}
    for census in inputs.selection.censuses:
        for reason, count in census.exclusions.items():
            merged[reason] = merged.get(reason, 0) + count
    for reason, count in sorted(merged.items()):
        gloss = _EXCLUSION_GLOSS.get(reason, reason)
        lines.append(f"- {count} {gloss} (`{reason}`)")
    if inputs.selection.censuses and not all(c.reconciles() for c in inputs.selection.censuses):
        lines.append(
            "- the act census does NOT reconcile: some acts left the reconstruction "
            "unaccounted for"
        )
    for event in inputs.selection.events:
        if event.blob_agreement != BLOB_AGREES:
            detail = ""
            if event.table_only_subjects:
                detail += f"; table-only: {', '.join(event.table_only_subjects)}"
            if event.blob_only_subjects:
                detail += f"; blob-only: {', '.join(event.blob_only_subjects)}"
            lines.append(
                f"- scene `{event.scene_id}`: view blob vs choice-set table "
                f"{event.blob_agreement}{detail}"
            )
        for flag in event.integrity_flags:
            lines.append(f"- scene `{event.scene_id}`: flagged `{flag}`")
    fallback = sum(1 for e in inputs.selection.events if e.choice_set_kind != "viewport")
    if fallback:
        lines.append(
            f"- {fallback} event(s) scored against the `rendered` fallback denominator "
            "(no viewport set was recorded for those scenes)"
        )
    unreadable = sum(1 for a in inputs.acts if not a.payload_readable)
    if unreadable:
        lines.append(
            f"- {unreadable} operator act payload blob(s) unreadable; any words they "
            "carried are not reconstructable"
        )
    if inputs.mint_view.scene_blobs_unavailable:
        lines.append(
            f"- {inputs.mint_view.scene_blobs_unavailable} of "
            f"{inputs.mint_view.scenes_total} scene view blobs absent or unreadable; "
            "their observations are missing from every forward path above"
        )
    for note in inputs.store_notes:
        lines.append(f"- {note}")
    if lines:
        out.extend(lines)
    else:
        out.append("Nothing was flagged.")
    out.append("")


def render_day_debrief(inputs: DebriefInputs, day: str, now_wall_us: int) -> str:
    out: list[str] = []
    out.append(f"# Session debrief — {day}")
    out.append("")
    catalog_desc = (
        f"`{inputs.catalog_sqlite}`" if inputs.catalog_sqlite is not None else "no catalog found"
    )
    out.append(
        f"What this is: a reconstruction from durable records — the keeper catalog "
        f"({catalog_desc}) and the cockpit session state (`{inputs.session_state}`). It "
        f"reports only what those stores retain and states what it could not "
        f"reconstruct; nothing is filled in to complete a template. All clocks are UTC. "
        f"Written {_iso(now_wall_us)}."
    )
    out.append("")
    _render_shape(inputs, day, out)
    out.append("## 2. Held coins, in hold order")
    out.append("")
    coins = _coins_of_day(inputs.acts, day)
    if coins:
        for coin in coins:
            _render_coin(coin, inputs.mint_view, day, out)
    else:
        out.append("No coin was held this day, and no words were recorded about any coin.")
        out.append("")
    _render_tally(inputs, day, out)
    _render_integrity(inputs, day, out)
    return "\n".join(out).rstrip() + "\n"


# --- writing --------------------------------------------------------------------------

_MARKER_PREFIX = "<!-- joshi-debrief v1 sha256:"
_MARKER_SUFFIX = " -->"


def _with_marker(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{text}{_MARKER_PREFIX}{digest}{_MARKER_SUFFIX}\n"


def is_generated_debrief(path: Path) -> bool:
    """True only when the file is byte-for-byte a debrief this module wrote.

    A generated file she has since edited by hand no longer digests to its marker and is
    treated as hand-written from then on: her edits are never overwritten.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    lines = content.splitlines(keepends=True)
    if not lines:
        return False
    marker = lines[-1].strip()
    if not (marker.startswith(_MARKER_PREFIX) and marker.endswith(_MARKER_SUFFIX)):
        return False
    stated = marker[len(_MARKER_PREFIX) : -len(_MARKER_SUFFIX)].strip()
    body = "".join(lines[:-1])
    return hashlib.sha256(body.encode("utf-8")).hexdigest() == stated


def write_day_debrief(out_dir: Path, day: str, text: str) -> tuple[Path, str]:
    """Write one day's artifact under the runbook convention, refusing to clobber words.

    `<day>-session.md` is the first choice. An existing file that is not verifiably a
    generated debrief is hand-written content and is never overwritten; the artifact
    goes to a `-debrief` sibling instead. Returns (path, action) where action is one of
    `written`, `refreshed`.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = [f"{day}-session.md", f"{day}-session-debrief.md"] + [
        f"{day}-session-debrief-{i}.md" for i in range(2, 10)
    ]
    for name in candidates:
        path = out_dir / name
        if not path.exists():
            path.write_text(_with_marker(text), encoding="utf-8")
            return path, "written"
        if is_generated_debrief(path):
            path.write_text(_with_marker(text), encoding="utf-8")
            return path, "refreshed"
    raise RuntimeError(
        f"every candidate name for {day} under {out_dir} holds hand-written content; "
        "refusing to overwrite any of it"
    )
