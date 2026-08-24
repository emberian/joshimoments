"""Read the durable records a session debrief is reconstructed from. Read-only throughout.

Three stores feed a debrief, and each one is opened with `mode=ro` (sqlite) or plain reads
(JSON state); nothing here ever writes, migrates or takes a writer lock:

  keeper catalog      `catalog.sqlite` beside its `blobs/` tree: operator acts in `command`
                      (payload blobs carry her exact words), witnessed scenes in `scene`,
                      and every priced candidate observation in the retained view blobs.
  pairing catalog     `<session-state>/live-follow/pairing/catalog.sqlite`: when a cockpit
                      was actually paired, and when the pairing ended.
  live-follow state   `<session-state>/live-follow/follow-state.json`: the scenes the live
                      derivation advanced through, with derivation and retirement times.

The act vocabulary is read, not invented. A hold, a hold note and a journal entry are all
ordinary `record_focus` evidence commands distinguished ONLY by the frozen `uiLabel` in
their payload context; the labels are mirrored byte for byte from their owners
(`apps/glass/src/operator/holds.ts`, `apps/glass/src/operator/journal.ts`,
`apps/core/src/live_journal.rs`). The verbatim-word extraction mirrors `verbatimWords` in
`apps/glass/src/operator/journal.ts`: stated free-text fields only, never a summary, never
a concatenation, and an act that carried no words yields an empty tuple rather than "".
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from joshi_analysis.selection.events import (
    _as_float,
    _iso_to_wall_us,
    load_blob_bytes,
    open_catalog,
    read_view_blob,
)

US = 1_000_000

#: Frozen in apps/glass/src/operator/holds.ts (HOLD_UI_LABEL). The label is the whole
#: discriminator; these strings are load-bearing bytes, not display text.
HOLD_UI_LABEL = "Hold coin"
#: Frozen in apps/glass/src/operator/holds.ts (HOLD_NOTE_UI_LABEL).
HOLD_NOTE_UI_LABEL = "Note on held coin"
#: Frozen in apps/glass/src/operator/journal.ts and apps/core/src/live_journal.rs.
JOURNAL_UI_LABEL = "Journal entry"


# --- operator acts --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerbatimField:
    """One stated field of an act: the reader's label and the operator's exact words."""

    label: str
    words: str


@dataclass(frozen=True, slots=True)
class OperatorAct:
    """One durable operator command, with its payload words decoded when readable."""

    command_id: str
    command_kind: str
    subject_kind: str
    subject_key: str
    scene_id: str | None
    client_session_id: str
    issued_wall_us: int
    committed_commit_seq: int
    #: `payload.context.uiLabel`, or None when the payload blob was absent or unreadable.
    ui_label: str | None
    payload_readable: bool
    verbatim: tuple[VerbatimField, ...]

    @property
    def is_hold(self) -> bool:
        return self.command_kind == "record_focus" and self.ui_label == HOLD_UI_LABEL

    @property
    def is_hold_note(self) -> bool:
        return self.command_kind == "record_focus" and self.ui_label == HOLD_NOTE_UI_LABEL

    @property
    def is_journal_entry(self) -> bool:
        return self.command_kind == "record_focus" and self.ui_label == JOURNAL_UI_LABEL


def _verbatim_fields(kind: str, payload: Mapping[str, object]) -> tuple[VerbatimField, ...]:
    """Mirror of `verbatimWords` in apps/glass/src/operator/journal.ts, plus nothing."""
    words: list[VerbatimField] = []
    context = payload.get("context")
    if isinstance(context, Mapping):
        why_now = context.get("whyNow")
        if isinstance(why_now, str):
            words.append(VerbatimField("Why now", why_now))
        note = context.get("note")
        if isinstance(note, str):
            words.append(VerbatimField("Note", note))
    if kind == "nominate_candidate" and isinstance(payload.get("nomination"), str):
        words.append(VerbatimField("Nomination", str(payload["nomination"])))
    if kind == "record_disposition" and isinstance(payload.get("disposition"), str):
        label = "Disposition (provisional)" if payload.get("provisional") else "Disposition"
        words.append(VerbatimField(label, str(payload["disposition"])))
    if kind == "record_crackle_family" and isinstance(payload.get("crackleFamily"), str):
        label = (
            "Crackle family (provisional)" if payload.get("provisional") else "Crackle family"
        )
        words.append(VerbatimField(label, str(payload["crackleFamily"])))
    if kind == "record_gesture" and isinstance(payload.get("gestureLabel"), str):
        words.append(VerbatimField("Gesture", str(payload["gestureLabel"])))
    if kind == "compensate_command" and isinstance(payload.get("reason"), str):
        words.append(VerbatimField("Correction reason", str(payload["reason"])))
    return tuple(words)


def read_operator_acts(catalog: Path, state_root: Path | None = None) -> list[OperatorAct]:
    """Every command in one catalog, in commit order, with payload words when readable."""
    catalog = Path(catalog)
    root = Path(state_root) if state_root is not None else catalog.parent
    acts: list[OperatorAct] = []
    conn = open_catalog(catalog)
    try:
        for row in conn.execute(
            "SELECT command_id, command_kind, subject_kind, subject_key, scene_id,"
            "       client_session_id, issued_wall_us, committed_commit_seq, payload_blob_id"
            " FROM command ORDER BY committed_commit_seq, command_id"
        ):
            raw = load_blob_bytes(conn, root, row["payload_blob_id"])
            payload: Mapping[str, object] | None = None
            if raw is not None:
                try:
                    parsed = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    parsed = None
                if isinstance(parsed, Mapping):
                    payload = parsed
            ui_label: str | None = None
            verbatim: tuple[VerbatimField, ...] = ()
            if payload is not None:
                context = payload.get("context")
                if isinstance(context, Mapping) and isinstance(context.get("uiLabel"), str):
                    ui_label = str(context["uiLabel"])
                verbatim = _verbatim_fields(row["command_kind"], payload)
            acts.append(
                OperatorAct(
                    command_id=row["command_id"],
                    command_kind=row["command_kind"],
                    subject_kind=row["subject_kind"],
                    subject_key=row["subject_key"],
                    scene_id=row["scene_id"],
                    client_session_id=row["client_session_id"],
                    issued_wall_us=int(row["issued_wall_us"]),
                    committed_commit_seq=int(row["committed_commit_seq"]),
                    ui_label=ui_label,
                    payload_readable=payload is not None,
                    verbatim=verbatim,
                )
            )
    finally:
        conn.close()
    return acts


# --- witnessed scenes -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WitnessedScene:
    scene_id: str
    rendered_wall_us: int
    scene_mode: str


def read_witnessed_scenes(catalog: Path) -> list[WitnessedScene]:
    conn = open_catalog(Path(catalog))
    try:
        return [
            WitnessedScene(
                scene_id=row["scene_id"],
                rendered_wall_us=int(row["rendered_wall_us"]),
                scene_mode=row["scene_mode"],
            )
            for row in conn.execute(
                "SELECT scene_id, rendered_wall_us, scene_mode FROM scene"
                " ORDER BY rendered_wall_us, scene_id"
            )
        ]
    finally:
        conn.close()


# --- retained market readings ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reading:
    """One provider-asserted observation of one mint, durably retained in a scene blob.

    The clock is the candidate's own `lastObservedAt` -- the market clock -- never the
    scene's render time. Price and market cap are the provider's asserted numbers exactly
    as retained; None means the scene showed no figure, which is an absent record and
    never a zero.
    """

    mint: str
    clock_wall_us: int
    price_sol: float | None
    market_cap_usd: float | None
    scene_id: str
    captured_commit_seq: int
    source_label: str


@dataclass
class MintCatalogView:
    """Everything the catalog's retained view blobs say about each mint, mint-keyed."""

    readings: dict[str, list[Reading]] = field(default_factory=dict)
    #: mint -> (symbol, name): the first non-null identity a retained scene asserted.
    identity: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)
    scenes_total: int = 0
    scene_blobs_unavailable: int = 0

    def readings_for(self, mint: str) -> list[Reading]:
        return self.readings.get(mint, [])

    def readings_after(self, mint: str, after_wall_us: int) -> list[Reading]:
        """Readings whose market clock is STRICTLY after the instant. The strict
        inequality is the no-leakage rule of the pre-registration, kept here too."""
        return [r for r in self.readings_for(mint) if r.clock_wall_us > after_wall_us]

    def reading_in_scene(self, mint: str, scene_id: str) -> Reading | None:
        for reading in self.readings_for(mint):
            if reading.scene_id == scene_id:
                return reading
        return None


def read_mint_catalog_view(catalog: Path, state_root: Path | None = None) -> MintCatalogView:
    """Walk every retained scene blob and index identity, price and market cap by mint."""
    catalog = Path(catalog)
    root = Path(state_root) if state_root is not None else catalog.parent
    view = MintCatalogView()
    conn = open_catalog(catalog)
    try:
        sources_by_scene: dict[str, list[str]] = {}
        for row in conn.execute(
            "SELECT scene_id, source_id FROM scene_watermark WHERE source_id IS NOT NULL"
            " ORDER BY scene_id, source_id"
        ):
            sources_by_scene.setdefault(row["scene_id"], []).append(row["source_id"])
        for scene in conn.execute(
            "SELECT scene_id, captured_commit_seq, view_blob_id, source_mode FROM scene"
            " ORDER BY captured_commit_seq, scene_id"
        ):
            view.scenes_total += 1
            parsed, _agreement = read_view_blob(conn, root, scene["view_blob_id"])
            if parsed is None:
                view.scene_blobs_unavailable += 1
                continue
            payload = parsed.get("payload")
            if not isinstance(payload, Mapping):
                continue
            candidates = payload.get("candidates")
            if not isinstance(candidates, list):
                continue
            source_ids = sources_by_scene.get(scene["scene_id"])
            source_label = ", ".join(source_ids) if source_ids else str(scene["source_mode"])
            for entry in candidates:
                if not isinstance(entry, Mapping):
                    continue
                key = entry.get("id") or entry.get("mint")
                if not isinstance(key, str) or not key:
                    continue
                symbol = entry.get("symbol") if isinstance(entry.get("symbol"), str) else None
                name = entry.get("name") if isinstance(entry.get("name"), str) else None
                known_symbol, known_name = view.identity.get(key, (None, None))
                view.identity[key] = (known_symbol or symbol, known_name or name)
                clock = _iso_to_wall_us(entry.get("lastObservedAt"))
                metrics = entry.get("metrics")
                price = _as_float(metrics.get("priceSol")) if isinstance(metrics, Mapping) else None
                mcap = (
                    _as_float(metrics.get("marketCapUsd"))
                    if isinstance(metrics, Mapping)
                    else None
                )
                if clock is None or (price is None and mcap is None):
                    continue
                view.readings.setdefault(key, []).append(
                    Reading(
                        mint=key,
                        clock_wall_us=clock,
                        price_sol=price,
                        market_cap_usd=mcap,
                        scene_id=scene["scene_id"],
                        captured_commit_seq=int(scene["captured_commit_seq"]),
                        source_label=source_label,
                    )
                )
    finally:
        conn.close()
    for series in view.readings.values():
        series.sort(key=lambda r: (r.clock_wall_us, r.captured_commit_seq, r.scene_id))
    return view


# --- pairing --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PairedWindow:
    """One paired cockpit session, from the pairing store's own occurrence ledger."""

    session_id: str
    established_wall_us: int
    lease_expires_wall_us: int | None
    ended_wall_us: int | None
    ended_kind: str | None
    ended_reason: str | None


_SESSION_END_KINDS = ("revoked", "expired", "restart_invalidated")


def read_paired_windows(session_state: Path) -> tuple[list[PairedWindow], list[str]]:
    """Paired sessions from `<session-state>/live-follow/pairing/catalog.sqlite`.

    Returns (windows, notes): a note is a one-line integrity statement about what could
    not be read, never a guess about what it would have said.
    """
    db = Path(session_state) / "live-follow" / "pairing" / "catalog.sqlite"
    if not db.is_file():
        return [], [f"no pairing catalog at {db}; paired windows cannot be reconstructed"]
    conn = open_catalog(db)
    try:
        try:
            rows = conn.execute(
                "SELECT occurrence_kind, session_id, observed_wall_us, expires_wall_us, reason"
                " FROM wave5_g0_pairing_occurrence_v1 WHERE session_id IS NOT NULL"
                " ORDER BY observed_wall_us, pairing_occurrence_id"
            ).fetchall()
        except sqlite3.OperationalError:
            return [], [
                f"pairing catalog at {db} predates the pairing occurrence ledger;"
                " paired windows cannot be reconstructed"
            ]
    finally:
        conn.close()
    started: dict[str, sqlite3.Row] = {}
    ended: dict[str, sqlite3.Row] = {}
    order: list[str] = []
    for row in rows:
        sid = row["session_id"]
        if row["occurrence_kind"] == "consumed" and sid not in started:
            started[sid] = row
            order.append(sid)
        elif row["occurrence_kind"] in _SESSION_END_KINDS and sid not in ended:
            ended[sid] = row
    windows: list[PairedWindow] = []
    notes: list[str] = []
    for sid in order:
        start = started[sid]
        end = ended.get(sid)
        windows.append(
            PairedWindow(
                session_id=sid,
                established_wall_us=int(start["observed_wall_us"]),
                lease_expires_wall_us=(
                    int(start["expires_wall_us"]) if start["expires_wall_us"] is not None else None
                ),
                ended_wall_us=int(end["observed_wall_us"]) if end is not None else None,
                ended_kind=end["occurrence_kind"] if end is not None else None,
                ended_reason=end["reason"] if end is not None else None,
            )
        )
    orphaned = sorted(set(ended) - set(started))
    if orphaned:
        notes.append(
            "pairing ledger ends session(s) it never started: " + ", ".join(orphaned)
        )
    return windows, notes


# --- live-follow scene advancement ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveSceneAdvance:
    scene_id: str
    derived_wall_us: int | None
    subject_count: str | None
    observation_count: str | None
    derivation_version: str | None
    retired_wall_us: int | None
    retired_reason: str | None


def read_live_scenes(session_state: Path) -> tuple[list[LiveSceneAdvance], list[str]]:
    """Scene advancement from `follow-state.json`. A rolling state file, read as-is."""
    state_file = Path(session_state) / "live-follow" / "follow-state.json"
    if not state_file.is_file():
        return [], [f"no live-follow state at {state_file}; scene advancement not reconstructable"]
    try:
        parsed = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [], [f"live-follow state at {state_file} is unreadable"]
    if not isinstance(parsed, Mapping) or not isinstance(parsed.get("scenes"), list):
        return [], [f"live-follow state at {state_file} has no scene list"]
    scenes: list[LiveSceneAdvance] = []
    skipped = 0
    for entry in parsed["scenes"]:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("sceneId"), str):
            skipped += 1
            continue
        retirement = entry.get("retirement")
        retired_at = retired_reason = None
        if isinstance(retirement, Mapping):
            retired_at = _iso_to_wall_us(retirement.get("retiredAt"))
            reason = retirement.get("reason")
            retired_reason = reason if isinstance(reason, str) else None
        scenes.append(
            LiveSceneAdvance(
                scene_id=str(entry["sceneId"]),
                derived_wall_us=_iso_to_wall_us(entry.get("derivedAt")),
                subject_count=_stringish(entry.get("subjectCount")),
                observation_count=_stringish(entry.get("observationCount")),
                derivation_version=_stringish(entry.get("derivationVersion")),
                retired_wall_us=retired_at,
                retired_reason=retired_reason,
            )
        )
    notes = []
    if skipped:
        notes.append(f"{skipped} live-follow scene entr(ies) had no scene id and were skipped")
    scenes.sort(key=lambda s: (s.derived_wall_us or 0, s.scene_id))
    return scenes, notes


def _stringish(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None
