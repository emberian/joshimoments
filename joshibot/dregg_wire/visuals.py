"""The wire's panels: deterministic PNG renderers in the feed's house style.

Three images per issue, phone-thumbnail legible, same dark grammar as
``dregg_feed.charts`` (its color tokens are imported, not copied, so the wire and
the feed cannot drift apart):

* THE DAY AT A GLANCE — hourly verdict mix as a stacked bar strip, the CLEAN-admit
  rate drawn against its validated operating point, mayhem share, launch volume.
* THE CREW BOARD — the day's active crews. When a ``dregg_d4m`` crew-graph artifact
  is present it draws a real graph (nodes sized by launches today, edges weighted by
  shared birth-slot wallets, deterministic circular layout); otherwise it degrades to
  a crew x day recidivism heatmap built from the screen's own score ledgers. Caps are
  stated on the image, never silent.
* THE CALLOUT DESK — claimed-vs-measured on one log-scale multiple axis: the day's
  boldest provider claim, matured callout outcomes as dumbbells (claim -> measured
  peak), and the season anti-signal baselines as reference lines.

Every renderer is a pure function of plain dicts (the wire's facts dict and the
crew-board dict): no clocks, no network, PNG metadata pinned — same inputs, same
bytes. NOTHING here invents data: an empty section renders an honest empty panel
that says WHY it is empty, never a blank chart.

Captions are composed here too — plain text, no parse_mode, bare URLs only (the
gate's hard production rule) — and respect Telegram's 1024-char photo-caption cap
by construction.

LANGUAGE AND FIT (the copy-pass rules, applied to pixels): a PNG can't be hovered
for a gloss, so images carry LESS jargon than text, not more. Verdicts draw as the
short human labels below (an unknown future verdict de-codes generically — enum
glue never reaches a pixel), "validated population"/"operating point" render as
"standard launches"/"long-run rate" — the same true claims in the digest's words
(dregg_screen.digest, dregg_gate.lookup). And every variable-length string is drawn
through ``_fit``, which measures the rendered extent and ellipsizes to its column,
so no input can push text off the canvas; ``figure_texts`` hands every drawn string
to the copy-invariant tests.
"""

from __future__ import annotations

import io
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from matplotlib import ticker
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure

from dregg_feed.charts import (
    AMBER,
    GRID,
    INK,
    INK_MUTED,
    PRICE_DOWN,
    PRICE_FLAT,
    PRICE_UP,
    SURFACE,
    VOLUME,
    VOLUME_NOW,
)
from dregg_wire.wire import _pct, _ret_pct

SOFTWARE = "dregg_wire.visuals v1"  # pinned: bytes stay deterministic
CAPTION_MAX = 1024  # Telegram's photo-caption cap

#: Verdict -> house color. Direction is never color alone: every count is restated
#: as text in the legend row and the caption.
VERDICT_COLORS = {
    "CLEAN": PRICE_UP,
    "KNOWN_CREW": AMBER,
    "BUNDLED": AMBER,
    "NOT_CLEAN": PRICE_DOWN,
    "UNSCORED": PRICE_FLAT,
}
VERDICT_ORDER = ["CLEAN", "KNOWN_CREW", "BUNDLED", "NOT_CLEAN", "UNSCORED"]

#: Image-width versions of ``dregg_screen.digest.VERDICT_GLOSS`` — same meaning,
#: legend-sized. A PNG offers no hover gloss, so the enum name itself never draws.
VERDICT_LABELS = {
    "CLEAN": "clean",
    "KNOWN_CREW": "known crew",
    "BUNDLED": "bundled at birth",
    "NOT_CLEAN": "dev buy over the line",
    "UNSCORED": "couldn't read",
}


def verdict_label(verdict: str) -> str:
    """Human label; an unknown future enum de-codes generically (the copy-pass rule:
    machine syntax must never surface, even from codes that don't exist yet)."""

    return VERDICT_LABELS.get(verdict, verdict.replace("_", " ").replace(":", " ").lower())


MAX_GRAPH_NODES = 10
MAX_GRAPH_LABELS = 5


def _crew_tag(crew_id: object) -> str:
    """The on-canvas crew tag. Real ledger ids are a few digits; a pathological id is
    visibly elided (never silently truncated into a DIFFERENT id) so the tag can't
    overflow its column — the full id stays in the caption and the wire text."""

    tag = f"#{crew_id}"
    return tag if len(tag) <= 10 else tag[:9] + "…"


MAX_HEAT_CREWS = 8
HEAT_DAYS = 7
MAX_DUMBBELLS = 6

FOOT = "awareness, not advice"


class Panel(NamedTuple):
    """One deliverable image: stable name (drives the PNG filename and the outbox
    dedup key), a human title (approval DMs name it), bytes, and its own caption."""

    name: str
    title: str
    png: bytes
    caption: str


# -- small shared pieces ---------------------------------------------------------------


def _fig(height: float = 4.5) -> Figure:
    fig = Figure(figsize=(8.0, height), dpi=100, facecolor=SURFACE)
    FigureCanvasAgg(fig)
    return fig


def _finish(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE, metadata={"Software": SOFTWARE})
    return buf.getvalue()


def _bare(ax) -> None:
    ax.set_facecolor(SURFACE)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=INK_MUTED, labelsize=7.5, length=0)


def _fit(fig: Figure, x: float, y: float, text: str, *, right: float = 0.985,
         left: float = 0.015, **kw):
    """``fig.text`` with a MEASURED clamp: the rendered extent must stay inside
    [left, right] of the canvas, and a string that doesn't fit is ellipsized until
    it does. Every variable-length figure-level string draws through this — an input
    can shape a label, never push it off the canvas."""

    artist = fig.text(x, y, text, **kw)
    renderer = fig.canvas.get_renderer()
    width = fig.get_figwidth() * fig.dpi
    content = str(text)
    while content:
        box = artist.get_window_extent(renderer)
        if box.x0 >= left * width and box.x1 <= right * width:
            break
        content = content[:-1].rstrip()
        artist.set_text(content + "…")
    return artist


def figure_texts(fig: Figure) -> list[str]:
    """Every string drawn on a figure — labels, annotations, tick labels — so the
    copy-invariant tests can hold panel language to the same bar as channel text."""

    texts = [t.get_text() for t in fig.texts]
    for ax in fig.axes:
        texts += [t.get_text() for t in ax.texts]
        texts += [t.get_text() for t in (*ax.get_xticklabels(), *ax.get_yticklabels())]
    return [t for t in texts if t]


def _header(fig: Figure, title: str, right: str) -> None:
    fig.text(0.03, 0.945, title, color=INK, fontsize=13, fontweight="bold", va="center")
    fig.text(0.97, 0.945, right, color=INK_MUTED, fontsize=9, ha="right", va="center")


def _footer(fig: Figure, text: str) -> None:
    _fit(fig, 0.5, 0.022, text, color=INK_MUTED, fontsize=7, ha="center")


def _empty_figure(title: str, day: str, reason: str, source: str) -> Figure:
    """The honest empty state: the panel exists, says why it is empty, and looks like
    the product — never a blank chart, never invented zeros."""

    fig = _fig()
    _header(fig, title, day)
    fig.text(0.5, 0.56, "nothing to draw", color=INK_MUTED, fontsize=15, ha="center")
    _fit(fig, 0.5, 0.44, reason, color=INK, fontsize=9.5, ha="center")
    _footer(fig, f"{source} · {FOOT}")
    return fig


def _tight(value: object, limit: int = 24) -> str:
    """Whitespace-flattened and clamped: a hostile provider string cannot add caption
    lines or blow the cap."""

    text = " ".join(str(value if value is not None else "?").split())
    return text[:limit] if text else "?"


def _cap(text: str) -> str:
    """Captions are built to fit; the clamp is the belt, the assert the witness."""

    if len(text) > CAPTION_MAX:
        text = text[: CAPTION_MAX - 1] + "…"
    assert len(text) <= CAPTION_MAX
    return text


def _mult(x: float) -> str:
    return f"{x:g}×"  # noqa: RUF001 — the brand's multiplication sign, per OFFER_BRIEF.md


# -- panel a: the day at a glance ------------------------------------------------------


def _glance_figure(facts: dict) -> Figure:
    day = facts.get("day", "?")
    screen = facts.get("screen") or {}
    if screen.get("absent"):
        return _empty_figure(
            "DREGG WIRE — the day at a glance", day, str(screen["absent"]),
            str(screen.get("source", "dregg_screen")),
        )

    verdicts: dict[str, int] = screen.get("verdicts") or {}
    order = [v for v in VERDICT_ORDER if v in verdicts]
    order += sorted(v for v in verdicts if v not in VERDICT_ORDER)
    hourly: dict[str, dict] = screen.get("hourly") or {}
    unplaced = int(screen.get("hourly_unplaced") or 0)

    fig = _fig()
    _header(fig, "DREGG WIRE — the day at a glance", f"UTC day {day}")

    # Left: the hourly verdict-mix strip (launch volume IS the bar heights).
    ax = fig.add_axes((0.055, 0.16, 0.56, 0.60))
    _bare(ax)
    ax.grid(axis="y", color=GRID, linewidth=0.6, alpha=0.8)
    hours = list(range(24))
    bottoms = [0.0] * 24
    for verdict in order:
        heights = [float((hourly.get(f"{h:02d}") or {}).get(verdict, 0)) for h in hours]
        ax.bar(hours, heights, bottom=bottoms, width=0.8,
               color=VERDICT_COLORS.get(verdict, VOLUME), linewidth=0)
        bottoms = [b + h for b, h in zip(bottoms, heights, strict=True)]
    ax.set_xlim(-0.7, 23.7)
    ax.set_xticks([0, 6, 12, 18, 23])
    ax.set_xticklabels(["00:00", "06:00", "12:00", "18:00", "23:00"])
    ax.set_ylim(bottom=0)
    if max(bottoms) <= 0 and hourly == {}:
        ax.text(0.5, 0.5, "no rows carried a placeable hour", transform=ax.transAxes,
                color=INK_MUTED, fontsize=8.5, ha="center", va="center")

    # Legend row: human verdict labels with counts (color redundant by design), laid
    # out by MEASURED extent — entries that would run past the row are cut and the
    # cut is stated (right-aligned marker; kept entries yield room as needed), never
    # drawn off-canvas.
    renderer = fig.canvas.get_renderer()
    width_px = fig.get_figwidth() * fig.dpi
    kept: list[tuple] = []  # (swatch, entry, end_px)
    x = 0.055
    cut_index: int | None = None
    for index, verdict in enumerate(order):
        label = f"{verdict_label(verdict)} {verdicts[verdict]}"
        swatch = fig.text(x, 0.815, "■", color=VERDICT_COLORS.get(verdict, VOLUME),
                          fontsize=8, va="center")
        entry = fig.text(x + 0.016, 0.815, label, color=INK, fontsize=8, va="center")
        end_px = entry.get_window_extent(renderer).x1
        if end_px > 0.955 * width_px:
            swatch.remove()
            entry.remove()
            cut_index = index
            break
        kept.append((swatch, entry, end_px))
        x = end_px / width_px + 0.018
    if cut_index is not None:
        n_more = len(order) - cut_index
        marker = fig.text(0.985, 0.815, f"+{n_more} more (see caption)",
                          color=INK_MUTED, fontsize=8, ha="right", va="center")
        marker_x0 = marker.get_window_extent(renderer).x0
        while kept and kept[-1][2] > marker_x0 - 10:
            swatch, entry, _end = kept.pop()
            swatch.remove()
            entry.remove()
            n_more += 1
        marker.set_text(f"+{n_more} more (see caption)")

    # Right column: the numbers that make the day, in the digest's vocabulary.
    fig.text(0.66, 0.755, f"{screen.get('launches_scored', 0)}", color=INK,
             fontsize=26, fontweight="bold", va="center")
    fig.text(0.66, 0.675, "launches scored", color=INK_MUTED, fontsize=8.5, va="center")

    validated = screen.get("validated") or {}
    op = validated.get("operating_point") or {}
    _bullet(
        fig, y=0.50, rate=validated.get("clean_rate"), ref=op.get("admit_rate"),
        color=PRICE_UP, ref_label="long-run",
        title=(
            f"clean rate on standard launches: {validated.get('clean', 0)}"
            f" of {validated.get('count', 0)}"
            if validated.get("count")
            else "no standard-type launches today"
        ),
    )
    _fit(fig, 0.66, 0.415, "the launch type where accuracy was measured",
         color=INK_MUTED, fontsize=6.5, va="center")
    mayhem = screen.get("mayhem") or {}
    _bullet(
        fig, y=0.25, rate=mayhem.get("share"), ref=None, color=AMBER, ref_label="",
        title=f"mayhem-mode launches: {mayhem.get('count', 0)} of {screen.get('launches_scored', 0)}",
    )
    _fit(fig, 0.66, 0.175, "outside that measured slice — labeled, not blended",
         color=INK_MUTED, fontsize=6.5, va="center")

    note = f" · {unplaced} rows without a placeable hour" if unplaced else ""
    _footer(fig, f"source: {screen.get('source', 'dregg_screen')}{note} · "
                 f"scores rank risk; they do not establish intent")
    return fig


def render_day_glance(facts: dict) -> bytes:
    return _finish(_glance_figure(facts))


def _bullet(fig: Figure, *, y: float, rate: float | None, ref: float | None,
            color: str, ref_label: str, title: str) -> None:
    """A thin bullet bar with an optional reference tick — rate vs its yardstick.
    A None rate states itself instead of pretending to be zero."""

    _fit(fig, 0.66, y + 0.085, title, color=INK, fontsize=8.5, va="center")
    ax = fig.add_axes((0.66, y - 0.01, 0.30, 0.055))
    _bare(ax)
    ax.set_xticks([])
    ax.set_yticks([])
    if rate is None:
        ax.set_xlim(0, 1)
        ax.text(0.0, 0.5, "nothing to rate today", color=INK_MUTED,
                fontsize=7.5, va="center")
        return
    span = max(rate, ref or 0.0, 0.02) * 1.30
    ax.set_xlim(0, span)
    ax.set_ylim(0, 1)
    ax.barh([0.5], [span], height=0.6, color=GRID, linewidth=0)  # the runway
    ax.barh([0.5], [rate], height=0.6, color=color, linewidth=0)
    label_inside = rate > 0.72 * span
    ax.text(rate, 0.5, f" {_pct(rate)} ", color=INK, fontsize=8, va="center",
            ha="right" if label_inside else "left")
    if ref is not None:
        ax.plot([ref, ref], [-0.15, 1.15], color=INK, linewidth=1.2)
        # The yardstick label hangs BELOW the bar so it never collides with the
        # title; anchored toward the bar's interior so it cannot leave the canvas.
        ha = "left" if ref <= 0.5 * span else "right"
        ax.text(ref, -0.45, f"{ref_label} {_pct(ref)}", color=INK_MUTED, fontsize=7,
                ha=ha, va="top")


# -- panel b: the crew board -----------------------------------------------------------


def load_d4m_crew_graph(d4m_dir: Path | None, day: str) -> tuple[dict | None, str | None]:
    """The dregg_d4m seam. Consumes ``crew_graph-<day>.json`` (or ``crew_graph.json``
    stamped with the day) from the d4m state dir when present and well-shaped:

        {"day": "YYYY-MM-DD",
         "nodes": [{"crew_id": 7, "launches_today": 3,
                    "crew_coins": 4, "crew_rips": 1, "crew_dumps": 3}, ...],
         "edges": [{"a": 7, "b": 12, "shared_wallets": 5}, ...]}

    ``weight`` is accepted as an alias for ``shared_wallets``; extra keys are ignored.
    Anything missing, torn, or mis-shaped returns (None, reason) and the caller falls
    back to the score-ledger heatmap — the wire never blocks on the sibling lane.
    """

    if d4m_dir is None:
        return None, None
    for name in (f"crew_graph-{day}.json", "crew_graph.json"):
        path = d4m_dir / name
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"d4m artifact {name} unreadable ({type(exc).__name__})"
        if not isinstance(raw, dict):
            return None, f"d4m artifact {name} is not an object"
        if raw.get("day") not in (None, day):
            return None, f"d4m artifact {name} is for day {raw.get('day')!r}, not {day}"
        nodes, edges = raw.get("nodes"), raw.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return None, f"d4m artifact {name} lacks nodes/edges lists"
        clean_nodes: list[dict] = []
        for node in nodes:
            if not isinstance(node, dict) or not isinstance(node.get("crew_id"), int):
                return None, f"d4m artifact {name} has a node without an integer crew_id"
            clean_nodes.append(node)
        ids = {n["crew_id"] for n in clean_nodes}
        clean_edges: list[dict] = []
        for edge in edges:
            if not isinstance(edge, dict) or edge.get("a") not in ids or edge.get("b") not in ids:
                return None, f"d4m artifact {name} has an edge off the node set"
            weight = edge.get("shared_wallets", edge.get("weight", 1))
            if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight < 0:
                return None, f"d4m artifact {name} has a non-numeric edge weight"
            clean_edges.append({"a": edge["a"], "b": edge["b"], "weight": float(weight)})
        return {"source": name, "nodes": clean_nodes, "edges": clean_edges}, None
    return None, None


def crew_day_history(scores_dir: Path, day: str, *, days: int = HEAT_DAYS) -> dict:
    """Crew x day launch counts from the screen's own score ledgers (trailing window
    ending on `day`, inclusive). Deterministic given the files on disk."""

    from dregg_wire.facts import load_scores

    end = datetime.strptime(day, "%Y-%m-%d")
    window = [(end - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(days - 1, -1, -1)]
    counts: dict[int, Counter] = {}
    records: dict[int, dict] = {}
    for d in window:
        for row in load_scores(scores_dir, d):
            match = row.get("crew_match")
            if not match or not isinstance(match.get("crew_id"), int):
                continue
            crew_id = match["crew_id"]
            counts.setdefault(crew_id, Counter())[d] += 1
            best = records.setdefault(crew_id, {"max_jaccard": 0.0})
            best["max_jaccard"] = max(best["max_jaccard"], float(match.get("jaccard") or 0.0))
            for key in ("crew_coins", "crew_rips", "crew_dumps"):
                if match.get(key) is not None:
                    best[key] = match[key]
    return {"days": window, "counts": counts, "records": records}


def crew_board_data(
    facts: dict, scores_dir: Path | None, d4m_dir: Path | None
) -> dict:
    """Choose what the crew board draws. Priority: d4m graph -> score-ledger heatmap
    -> stated emptiness. Always returns a dict the renderer can draw honestly."""

    day = facts.get("day", "?")
    screen = facts.get("screen") or {}
    graph, d4m_note = load_d4m_crew_graph(d4m_dir, day)
    if graph is not None:
        nodes = sorted(
            graph["nodes"],
            key=lambda n: (-int(n.get("launches_today") or 0), n["crew_id"]),
        )
        shown = nodes[:MAX_GRAPH_NODES]
        shown_ids = {n["crew_id"] for n in shown}
        edges = [e for e in graph["edges"] if e["a"] in shown_ids and e["b"] in shown_ids]
        cut_nodes = len(nodes) - len(shown)
        cut_edges = len(graph["edges"]) - len(edges)
        if shown:
            return {
                "mode": "graph", "day": day, "nodes": shown, "edges": edges,
                "source": f"dregg_d4m {graph['source']}",
                "note": (
                    f"showing top {len(shown)} of {len(nodes)} crews"
                    + (f"; {cut_edges} edges cut with them" if cut_edges else "")
                    if cut_nodes else None
                ),
            }
        d4m_note = f"d4m artifact {graph['source']} carries no crews"

    history = crew_day_history(scores_dir, day) if scores_dir is not None else None
    today_counts = {c: cnt.get(day, 0) for c, cnt in (history or {"counts": {}})["counts"].items()}
    active = sorted(
        (c for c, n in today_counts.items() if n > 0), key=lambda c: (-today_counts[c], c)
    )
    if history and active:
        rows = []
        for crew_id in active[:MAX_HEAT_CREWS]:
            rows.append(
                {
                    "crew_id": crew_id,
                    "counts": [history["counts"][crew_id].get(d, 0) for d in history["days"]],
                    "record": history["records"].get(crew_id, {}),
                }
            )
        note_bits = []
        if len(active) > MAX_HEAT_CREWS:
            note_bits.append(f"showing top {MAX_HEAT_CREWS} of {len(active)} active crews")
        if d4m_note:
            note_bits.append(d4m_note)
        return {
            "mode": "heatmap", "day": day, "days": history["days"], "rows": rows,
            "source": f"dregg_screen score ledgers, trailing {len(history['days'])} days",
            "note": "; ".join(note_bits) or None,
        }
    reason = str(
        screen.get("crews_note")
        or screen.get("absent")
        or "no crew-fingerprint matches among today's launches"
    )
    if d4m_note:
        reason += f" · {d4m_note}"
    return {
        "mode": "empty", "day": day, "reason": reason,
        "source": str(screen.get("source", "dregg_screen")),
    }


def _crew_board_figure(board: dict) -> Figure:
    day = str(board.get("day", "?"))
    if board["mode"] == "empty":
        return _empty_figure("THE CREW BOARD", day, board["reason"], board["source"])
    if board["mode"] == "graph":
        return _crew_graph_figure(board, day)
    return _crew_heatmap_figure(board, day)


def render_crew_board(board: dict) -> bytes:
    return _finish(_crew_board_figure(board))


def _crew_graph_figure(board: dict, day: str) -> Figure:
    nodes: list[dict] = board["nodes"]
    edges: list[dict] = board["edges"]
    fig = _fig()
    _header(fig, "THE CREW BOARD — shared birth-slot wallets", f"UTC day {day}")

    ax = fig.add_axes((0.02, 0.10, 0.56, 0.74))
    ax.set_facecolor(SURFACE)
    ax.set_aspect("equal")
    ax.set_xticks([])  # no ticks at all: axis("off") hides them but leaves phantom
    ax.set_yticks([])  # tick artists that the text-extent guard would still measure
    ax.axis("off")
    n = len(nodes)
    # Deterministic circular layout: rank order (already sorted) walks clockwise
    # from 12 o'clock. No force layout, no randomness, no hairball.
    pos: dict[int, tuple[float, float]] = {}
    for i, node in enumerate(nodes):
        angle = math.radians(90.0 - 360.0 * i / max(n, 1))
        pos[node["crew_id"]] = (math.cos(angle), math.sin(angle))
    max_w = max((e["weight"] for e in edges), default=1.0) or 1.0
    for edge in sorted(edges, key=lambda e: e["weight"]):
        (x1, y1), (x2, y2) = pos[edge["a"]], pos[edge["b"]]
        share = edge["weight"] / max_w
        ax.plot([x1, x2], [y1, y2], color=VOLUME_NOW, linewidth=0.7 + 2.6 * share,
                alpha=0.25 + 0.45 * share, zorder=1, solid_capstyle="round")
    max_launches = max((int(n_.get("launches_today") or 0) for n_ in nodes), default=1) or 1
    for node in nodes:
        launches = int(node.get("launches_today") or 0)
        x, y = pos[node["crew_id"]]
        dirty = int(node.get("crew_dumps") or 0) > 0
        ax.scatter([x], [y], s=140 + 900 * launches / max_launches,
                   color=PRICE_DOWN if dirty else PRICE_FLAT, edgecolors=SURFACE,
                   linewidths=1.2, zorder=3)
        lx, ly = x * 1.30, y * 1.30
        ax.text(lx, ly, _crew_tag(node["crew_id"]), color=INK, fontsize=8, ha="center",
                va="center", zorder=4)
    ax.set_xlim(-1.55, 1.55)
    ax.set_ylim(-1.55, 1.55)

    # Right column: the top few, spelled out (label the top few; state what's cut).
    fig.text(0.62, 0.80, "top crews today", color=INK_MUTED, fontsize=8.5)
    y = 0.73
    for node in nodes[:MAX_GRAPH_LABELS]:
        record = (
            f"{node.get('crew_coins', '?')} coins / {node.get('crew_rips', '?')} rips"
            f" / {node.get('crew_dumps', '?')} dumps"
        )
        _fit(fig, 0.62, y, f"#{node['crew_id']} — "
             f"{int(node.get('launches_today') or 0)} today · {record}",
             color=INK, fontsize=8.5)
        y -= 0.062
    fig.text(0.62, y - 0.01, "node size = launches today\nedge weight = shared birth-slot wallets\n"
             "red node = crew with insider dumps on record", color=INK_MUTED, fontsize=7.5,
             va="top")

    note = f" · {board['note']}" if board.get("note") else ""
    _footer(fig, f"source: {board['source']}{note} · {FOOT}")
    return fig


def _crew_heatmap_figure(board: dict, day: str) -> Figure:
    rows: list[dict] = board["rows"]
    days: list[str] = board["days"]
    fig = _fig()
    _header(fig, "THE CREW BOARD — recidivism, trailing week", f"UTC day {day}")

    heat = LinearSegmentedColormap.from_list("dregg_heat", [SURFACE, "#54333a", PRICE_DOWN])
    # Cell height caps out so a one-crew day draws a strip, not a monolith.
    ax_top = 0.80
    ax_height = min(0.64, 0.15 * len(rows))
    ax = fig.add_axes((0.115, ax_top - ax_height, 0.505, ax_height))
    _bare(ax)
    grid_vals = [row["counts"] for row in rows]
    vmax = max((max(counts) for counts in grid_vals), default=1) or 1
    ax.imshow(grid_vals, cmap=heat, vmin=0, vmax=vmax, aspect="auto", interpolation="nearest")
    for r, counts in enumerate(grid_vals):
        for c, value in enumerate(counts):
            if value:
                ax.text(c, r, str(value), color=INK, fontsize=8, ha="center", va="center")
    ax.set_xticks(range(len(days)))
    ax.set_xticklabels(["today" if d == day else d[5:] for d in days], fontsize=7.5)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([_crew_tag(row["crew_id"]) for row in rows], fontsize=8)

    # Right column: each crew's tracked record — the reason it is on a board at all.
    fig.text(0.66, 0.825, "crew record on file", color=INK_MUTED, fontsize=8.5)
    for i, row in enumerate(rows):
        record = row.get("record", {})
        text = (
            f"{record.get('crew_coins', '?')} coins · {record.get('crew_rips', '?')} rips · "
            f"{record.get('crew_dumps', '?')} insider dumps · "
            f"match {record.get('max_jaccard', 0.0):.2f}"
        )
        # Align each record line with its heatmap row (imshow rows run top-down).
        y = ax_top - ax_height * (i + 0.5) / len(rows)
        _fit(fig, 0.65, y, text, color=INK, fontsize=7.5, va="center")
    note = f" · {board['note']}" if board.get("note") else ""
    _footer(fig, f"cells = crew-fingerprint launches per UTC day · source: {board['source']}"
                 f"{note} · {FOOT}")
    return fig


# -- panel c: the callout desk ---------------------------------------------------------


def _desk_figure(facts: dict) -> Figure:
    day = facts.get("day", "?")
    callouts = facts.get("callouts") or {}
    if callouts.get("absent"):
        return _empty_figure(
            "THE CALLOUT DESK", day, str(callouts["absent"]),
            str(callouts.get("source", "dregg_archive")),
        )
    claim = callouts.get("top_provider_claim")
    measured: list[dict] = (callouts.get("measured") or [])[:MAX_DUMBBELLS]
    anti = callouts.get("anti_signal") or {}
    if not callouts.get("archived_today") and claim is None and not measured:
        return _empty_figure(
            "THE CALLOUT DESK", day,
            f"no callouts first-archived today (board lifetime: "
            f"{callouts.get('board_total', 0)} callouts, {callouts.get('board_callers', 0)} callers)",
            str(callouts.get("source", "dregg_archive")),
        )

    fig = _fig()
    _header(fig, "THE CALLOUT DESK — claimed vs measured", f"UTC day {day}")

    # Top strip: the day's desk numbers, plain.
    removals = callouts.get("removals") or {}
    strip = (
        f"{callouts.get('archived_today', 0)} callouts archived today · "
        f"{callouts.get('distinct_callers_today', 0)} callers · "
        f"{callouts.get('distinct_mints_today', 0)} coins · "
        f"removals caught: {removals.get('today', 0)} today / {removals.get('total', 0)} all-time"
    )
    _fit(fig, 0.03, 0.855, strip, color=INK, fontsize=9)

    ax = fig.add_axes((0.06, 0.20, 0.90, 0.56))
    _bare(ax)
    ax.set_xscale("log")
    ax.set_yticks([])
    ax.grid(axis="x", color=GRID, linewidth=0.6, alpha=0.8)

    # Rows: boldest claim on top, then matured claimed->measured dumbbells.
    rows: list[tuple[str, float | None, float | None, bool]] = []
    if claim is not None and claim.get("multiple") is not None:
        who = _tight(claim.get("username"), 16)
        rows.append((f"today's boldest claim — {who}", float(claim["multiple"]), None, False))
    for entry in measured:
        who = _tight(entry.get("username"), 16)
        got = entry.get("max_close_multiple")
        rows.append(
            (f"{who}{' (final)' if entry.get('final') else ''}",
             entry.get("claimed_multiple"), got, True)
        )

    values = [v for row in rows for v in (row[1], row[2]) if v is not None and v > 0]
    baselines = [
        (1.0 + anti["ret_1h_mean"], f"feed mean @1h {_ret_pct(anti['ret_1h_mean'])}"),
        (1.0 + anti["ret_8h_mean"], f"feed mean @8h {_ret_pct(anti['ret_8h_mean'])}"),
        (1.0 + anti["burst_ret_8h_median"], f"burst median @8h {_ret_pct(anti['burst_ret_8h_median'])}"),
    ] if anti else []
    values += [b for b, _ in baselines]
    lo = min([*values, 0.5]) * 0.55
    hi = max([*values, 2.0]) * 2.2
    ax.set_xlim(lo, hi)
    ax.set_ylim(-0.8, max(len(rows), 1))
    ticks = [t for t in (0.25, 0.5, 1, 2, 5, 10, 30, 100, 300, 1000, 3000) if lo <= t <= hi]
    ax.set_xticks(ticks)
    ax.set_xticklabels([_mult(t) for t in ticks], fontsize=7.5)
    ax.xaxis.set_minor_locator(ticker.NullLocator())

    ax.axvline(1.0, color=INK_MUTED, linewidth=1.0)
    ax.text(1.0, max(len(rows), 1) - 0.02, " 1× — break even",  # noqa: RUF001
            color=INK_MUTED, fontsize=7.5, va="top")
    for stagger, (value, label) in enumerate(baselines):
        ax.axvline(value, color=PRICE_DOWN, linewidth=0.9, linestyle=(0, (4, 3)), alpha=0.85)
        ax.text(value, -0.76 + 0.26 * stagger, f" {label}", color=PRICE_DOWN, fontsize=6.8,
                ha="left", va="bottom")

    for i, (label, claimed, got, is_measured) in enumerate(reversed(rows)):
        y = i + 0.35
        if claimed is not None and got is not None:
            color = PRICE_UP if got >= claimed else PRICE_DOWN
            ax.plot([claimed, got], [y, y], color=color, linewidth=1.4, alpha=0.7, zorder=2)
        if claimed is not None:
            ax.scatter([claimed], [y], s=52, facecolors=SURFACE, edgecolors=AMBER,
                       linewidths=1.4, zorder=3)
            ax.text(claimed, y + 0.22, f"claim {_mult(claimed)}", color=AMBER,
                    fontsize=7, ha="center")
        if got is not None:
            ax.scatter([got], [y], s=52, color=PRICE_DOWN if got < 1.0 else PRICE_UP, zorder=4)
            ax.text(got, y + 0.22, f"measured peak {_mult(round(got, 2))}",
                    color=INK, fontsize=7, ha="center")
        elif is_measured:
            label += " — no measured peak"
        ax.text(lo * 1.06, y - 0.02, label, color=INK, fontsize=7.5, va="center")
    if not measured:
        ax.text(0.0, 1.03, "no callout outcomes have matured yet (they mature T+25h, "
                "finalize T+7d) — the dumbbells land here as cohorts age",
                transform=ax.transAxes, color=INK_MUTED, fontsize=7.5, va="bottom")

    src = str(anti.get("short_source") or "season baseline study")
    _footer(fig, f"log multiple axis · hollow = provider claim, filled = our measured peak · "
                 f"dashed = season baseline ({src}) · {FOOT}")
    return fig


def render_callout_desk(facts: dict) -> bytes:
    return _finish(_desk_figure(facts))


# -- captions + assembly ---------------------------------------------------------------


def hero_caption(facts: dict, issue: int, lede: str) -> str:
    day = facts.get("day", "?")
    screen = facts.get("screen") or {}
    lines = [f"DREGG WIRE #{issue} — {day}", lede]
    if screen.get("absent"):
        lines.append(str(screen["absent"]))
    else:
        mix = " · ".join(
            f"{verdict_label(k)} {v}" for k, v in (screen.get("verdicts") or {}).items()
        )
        lines.append(f"{screen.get('launches_scored', 0)} launches scored — {mix}"[:300])
        validated = screen.get("validated") or {}
        op = validated.get("operating_point") or {}
        if validated.get("count"):
            vs = (
                f" vs the long-run {_pct(op['admit_rate'])}"
                if op.get("admit_rate") is not None else ""
            )
            lines.append(
                f"Clean rate on standard launches: {validated.get('clean', 0)} of "
                f"{validated.get('count', 0)} ({_pct(validated.get('clean_rate'))}){vs}"
            )
        mayhem = screen.get("mayhem") or {}
        lines.append(
            f"Mayhem-mode launches: {mayhem.get('count', 0)} ({_pct(mayhem.get('share'))}) "
            "— labeled, not blended"
        )
    lines.append("Full wire follows. Scores rank risk; they do not establish intent.")
    return _cap("\n".join(lines))


def crew_caption(board: dict) -> str:
    day = board.get("day", "?")
    if board["mode"] == "empty":
        return _cap(f"Crew board — {day}\n{board['reason']}")
    lines = [f"Crew board — {day}"]
    if board["mode"] == "graph":
        lines.append("Nodes = crews sized by launches today; edges = shared birth-slot wallets.")
        for node in board["nodes"][:3]:
            lines.append(
                f"#{node['crew_id']}: {int(node.get('launches_today') or 0)} launches today, "
                f"record {node.get('crew_coins', '?')} coins / {node.get('crew_rips', '?')} rips"
                f" / {node.get('crew_dumps', '?')} insider dumps"
            )
    else:
        lines.append("Crew-fingerprint launches per UTC day, trailing week.")
        for row in board["rows"][:3]:
            record = row.get("record", {})
            lines.append(
                f"#{row['crew_id']}: {row['counts'][-1]} today, "
                f"{sum(row['counts'])} this week; record {record.get('crew_coins', '?')} coins /"
                f" {record.get('crew_rips', '?')} rips / {record.get('crew_dumps', '?')} dumps"
            )
    if board.get("note"):
        lines.append(str(board["note"]))
    return _cap("\n".join(lines))


def desk_caption(facts: dict) -> str:
    day = facts.get("day", "?")
    callouts = facts.get("callouts") or {}
    if callouts.get("absent"):
        return _cap(f"Callout desk — {day}\n{callouts['absent']}")
    lines = [
        f"Callout desk — {day}",
        f"{callouts.get('archived_today', 0)} callouts archived · "
        f"{callouts.get('distinct_callers_today', 0)} callers · "
        f"{callouts.get('distinct_mints_today', 0)} coins",
    ]
    claim = callouts.get("top_provider_claim")
    if claim is not None and claim.get("multiple") is not None:
        lines.append(
            f"Boldest claim: {_mult(float(claim['multiple']))} by "
            f"{_tight(claim.get('username'), 16)} — their number, not our measurement."
        )
    anti = callouts.get("anti_signal") or {}
    if anti:
        lines.append(
            f"Season baseline: {_ret_pct(anti['ret_1h_mean'])} @1h, "
            f"{_ret_pct(anti['ret_8h_mean'])} @8h mean ({_tight(anti.get('short_source'), 60)})."
        )
    outcomes = callouts.get("outcomes") or {}
    if outcomes.get("note"):
        lines.append(f"Outcomes: {outcomes.get('rows', 0)} rows computing — {outcomes['note']}.")
    return _cap("\n".join(lines))


def build_panels(
    facts: dict, issue: int, lede: str, *,
    scores_dir: Path | None = None, d4m_dir: Path | None = None,
) -> list[Panel]:
    """The wire's panel set, in posting order. Deterministic given (facts, ledgers on
    disk, d4m artifact). Raises only on a genuine render failure — the caller decides
    whether to degrade to a text-only wire."""

    board = crew_board_data(facts, scores_dir, d4m_dir)
    return [
        Panel("glance", "the day at a glance", render_day_glance(facts),
              hero_caption(facts, issue, lede)),
        Panel("crews", "the crew board", render_crew_board(board), crew_caption(board)),
        Panel("desk", "the callout desk", render_callout_desk(facts), desk_caption(facts)),
    ]
