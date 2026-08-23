"""Reconstruct what the operator was choosing among, from durably retained bytes.

Read-only against a Joshi catalog. Opens sqlite in `mode=ro` and never writes, never
migrates, never takes the writer lock. Safe to point at a catalog a live collector owns.

The reconstruction reads the store's own tables -- `command`, `scene`, `scene_choice_member`,
`scene_watermark`, `blob` -- and cross-checks the choice set against the retained view blob.
It does not re-derive the choice set from the blob alone: `scene_choice_member` is the store's
first-class record and carries the `set_kind` distinction the blob does not. The blob is used
as a CHECK, and disagreement is reported per event rather than resolved silently in either
direction.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .preregistration import (
    CHOICE_SET_KIND_PREFERENCE,
    EXCLUSION_ACT_NO_SCENE,
    EXCLUSION_ACT_NOT_SUBJECT_BOUND,
    EXCLUSION_ACT_SUBJECT_OFF_CHOICE_SET,
    EXCLUSION_NO_COUNTERFACTUAL,
    EXCLUSION_SCENE_NO_CHOICE_SET,
    SELECTABLE_SUBJECT_KIND,
)

BLOB_AGREES = "agrees"
BLOB_DISAGREES = "disagrees"
BLOB_ABSENT = "blob_absent"
BLOB_UNREADABLE = "blob_unreadable"


@dataclass(frozen=True, slots=True)
class ActRef:
    """One operator command that named a candidate inside a scene."""

    command_id: str
    command_kind: str
    subject_kind: str
    subject_key: str
    committed_commit_seq: int
    issued_wall_us: int
    received_wall_us: int
    client_session_id: str
    client_clock_id: str
    payload_blob_id: str


@dataclass(frozen=True, slots=True)
class CandidateRef:
    """One member of the choice set, with whatever price the scene showed for it."""

    subject_key: str
    subject_kind: str
    source_rank: int | None
    rendered_ordinal: int | None
    #: Price in SOL as retained in the scene's view blob, or None when the scene showed
    #: no price for this mint. None is an absent record and never a zero.
    price_sol: float | None
    #: Market clock of that price -- the candidate's own `lastObservedAt`, microseconds.
    #: NOT the scene's render time. See the pre-registration.
    price_observed_wall_us: int | None


@dataclass(frozen=True, slots=True)
class WatermarkRef:
    watermark_namespace: str
    source_id: str | None
    projection_name: str | None
    delivered_commit_seq: int


@dataclass(frozen=True, slots=True)
class SelectionEventV1:
    """One decision: a scene, the candidates in it, and which ones the operator marked.

    The unit is the SCENE. Several acts against one scene collapse into one event with a
    chosen set of several -- see the pre-registration on why this is not three events.
    """

    schema: str
    event_id: str
    catalog_path: str

    # --- the scene ---------------------------------------------------------------
    scene_id: str
    scene_mode: str
    view_sha256: str
    ui_build: str
    view_contract: str
    view_contract_version: int
    source_mode: str
    captured_commit_seq: int
    knowledge_cutoff_commit_seq: int
    outcome_cutoff_commit_seq: int | None
    scene_rendered_wall_us: int
    watermarks: tuple[WatermarkRef, ...]

    # --- the choice ---------------------------------------------------------------
    choice_set_kind: str
    choice_set_kind_available: tuple[str, ...]
    chosen: tuple[CandidateRef, ...]
    passed: tuple[CandidateRef, ...]
    acts: tuple[ActRef, ...]

    # --- the clocks ---------------------------------------------------------------
    #: The instant the decision locked: the LAST act against this scene. The outcome
    #: window opens here, never at scene_rendered_wall_us.
    decision_wall_us: int
    decision_commit_seq: int
    #: decision_wall_us - scene_rendered_wall_us. How stale the scene was when marked.
    #: Reported, never used to drop an event.
    staleness_us: int

    # --- integrity ---------------------------------------------------------------
    blob_agreement: str
    blob_only_subjects: tuple[str, ...] = ()
    table_only_subjects: tuple[str, ...] = ()
    integrity_flags: tuple[str, ...] = ()

    @property
    def choice_set_size(self) -> int:
        return len(self.chosen) + len(self.passed)

    def to_json_obj(self) -> dict[str, object]:
        def cand(c: CandidateRef) -> dict[str, object]:
            return {
                "subjectKey": c.subject_key,
                "subjectKind": c.subject_kind,
                "sourceRank": c.source_rank,
                "renderedOrdinal": c.rendered_ordinal,
                "priceSol": c.price_sol,
                "priceObservedWallUs": c.price_observed_wall_us,
            }

        return {
            "schema": self.schema,
            "eventId": self.event_id,
            "catalogPath": self.catalog_path,
            "sceneId": self.scene_id,
            "sceneMode": self.scene_mode,
            "viewSha256": self.view_sha256,
            "uiBuild": self.ui_build,
            "viewContract": f"{self.view_contract}/{self.view_contract_version}",
            "sourceMode": self.source_mode,
            "capturedCommitSeq": self.captured_commit_seq,
            "knowledgeCutoffCommitSeq": self.knowledge_cutoff_commit_seq,
            "outcomeCutoffCommitSeq": self.outcome_cutoff_commit_seq,
            "sceneRenderedWallUs": self.scene_rendered_wall_us,
            "watermarks": [
                {
                    "namespace": w.watermark_namespace,
                    "sourceId": w.source_id,
                    "projectionName": w.projection_name,
                    "deliveredCommitSeq": w.delivered_commit_seq,
                }
                for w in self.watermarks
            ],
            "choiceSetKind": self.choice_set_kind,
            "choiceSetKindAvailable": list(self.choice_set_kind_available),
            "choiceSetSize": self.choice_set_size,
            "chosen": [cand(c) for c in self.chosen],
            "passed": [cand(c) for c in self.passed],
            "acts": [
                {
                    "commandId": a.command_id,
                    "commandKind": a.command_kind,
                    "subjectKind": a.subject_kind,
                    "subjectKey": a.subject_key,
                    "committedCommitSeq": a.committed_commit_seq,
                    "issuedWallUs": a.issued_wall_us,
                    "clientSessionId": a.client_session_id,
                }
                for a in self.acts
            ],
            "decisionWallUs": self.decision_wall_us,
            "decisionCommitSeq": self.decision_commit_seq,
            "stalenessUs": self.staleness_us,
            "blobAgreement": self.blob_agreement,
            "blobOnlySubjects": list(self.blob_only_subjects),
            "tableOnlySubjects": list(self.table_only_subjects),
            "integrityFlags": list(self.integrity_flags),
        }


@dataclass
class ReconstructionCensus:
    """Everything the reconstruction saw and what became of it.

    Nothing leaves the reconstruction unaccounted for. `commands_total` reconciles exactly
    against the sum of the exclusion counters plus `commands_scored_into_events`.
    """

    catalog_path: str = ""
    commands_total: int = 0
    scenes_total: int = 0
    commands_scored_into_events: int = 0
    events: int = 0
    exclusions: dict[str, int] = field(default_factory=dict)
    blob_agreement: dict[str, int] = field(default_factory=dict)

    def exclude(self, reason: str, n: int = 1) -> None:
        self.exclusions[reason] = self.exclusions.get(reason, 0) + n

    def reconciles(self) -> bool:
        return self.commands_total == self.commands_scored_into_events + sum(
            self.exclusions.get(k, 0)
            for k in (
                EXCLUSION_ACT_NOT_SUBJECT_BOUND,
                EXCLUSION_ACT_NO_SCENE,
                EXCLUSION_ACT_SUBJECT_OFF_CHOICE_SET,
                EXCLUSION_SCENE_NO_CHOICE_SET,
                EXCLUSION_NO_COUNTERFACTUAL,
            )
        )

    def to_json_obj(self) -> dict[str, object]:
        return {
            "catalogPath": self.catalog_path,
            "commandsTotal": self.commands_total,
            "scenesTotal": self.scenes_total,
            "commandsScoredIntoEvents": self.commands_scored_into_events,
            "events": self.events,
            "exclusions": dict(sorted(self.exclusions.items())),
            "blobAgreement": dict(sorted(self.blob_agreement.items())),
            "reconciles": self.reconciles(),
        }


def _iso_to_wall_us(text: object) -> int | None:
    """Parse an RFC3339 instant into microseconds since the epoch, or None."""
    if not isinstance(text, str) or not text:
        return None
    raw = text.replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return int(moment.timestamp() * 1_000_000)


def _as_float(value: object) -> float | None:
    """Coerce a retained metric to float. Strings are used for big/exact numbers in the
    view contract, so both forms appear. Anything else is an absent record."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def open_catalog(path: Path) -> sqlite3.Connection:
    """Open a catalog strictly read-only."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_blob_bytes(conn: sqlite3.Connection, state_root: Path, blob_id: str) -> bytes | None:
    """Fetch a blob's content, inline or external.

    External blobs live content-addressed under the state root at the `relative_path`
    recorded in the `blob` row -- e.g. `operator_private/sha256/a2/25/<sha>.blob`.
    Returns None when the row is missing or the external file is not on disk (an
    externally stored blob whose bytes were disposed of is a real, expected state).

    `compression = 'zstd'` is recorded in the schema but the decompressor is not a
    dependency of this package; such a blob is reported as unreadable rather than
    guessed at.
    """
    # `blob_object` is authoritative for physical placement; `blob` is retained as a
    # compatibility content catalog (schema/migrations/0005_lossless_contract.sql). Read
    # the authoritative table first and fall back only if this catalog predates it.
    row = conn.execute(
        "SELECT storage_mode, inline_bytes, relative_path, compression"
        " FROM blob_object WHERE blob_id = ? ORDER BY storage_domain LIMIT 1",
        (blob_id,),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT storage_mode, inline_bytes, relative_path, compression"
            " FROM blob WHERE blob_id = ?",
            (blob_id,),
        ).fetchone()
    if row is None:
        return None
    if row["compression"] != "identity":
        return None
    if row["storage_mode"] == "inline":
        raw = row["inline_bytes"]
        return bytes(raw) if raw is not None else None
    rel = row["relative_path"]
    if not rel:
        return None
    on_disk = state_root / "blobs" / rel
    if not on_disk.is_file():
        return None
    return on_disk.read_bytes()


def _view_candidates(view: Mapping[str, object]) -> dict[str, tuple[float | None, int | None]]:
    """Pull mint -> (priceSol, market clock) out of a retained view blob.

    The market clock is the candidate's own `lastObservedAt`. It is deliberately NOT
    `asOf.renderedAt`: render time is when the picture was drawn, not when the price was
    true, and conflating them dates stale prices to the present.
    """
    payload = view.get("payload")
    if not isinstance(payload, Mapping):
        return {}
    candidates = payload.get("candidates")
    if not isinstance(candidates, Sequence):
        return {}
    out: dict[str, tuple[float | None, int | None]] = {}
    for entry in candidates:
        if not isinstance(entry, Mapping):
            continue
        # `id` is the join key: admission ties `command.subject_key` to `candidates[].id`
        # (joshi-operator/src/command.rs contains_candidate binary-searches on `.id`).
        # `mint` carries the same string on the live path but is a separate field and a
        # fixture could differ, so `id` wins and `mint` is only a fallback.
        key = entry.get("id") or entry.get("mint")
        if not isinstance(key, str) or not key:
            continue
        metrics = entry.get("metrics")
        price = _as_float(metrics.get("priceSol")) if isinstance(metrics, Mapping) else None
        clock = _iso_to_wall_us(entry.get("lastObservedAt"))
        out[key] = (price, clock)
    return out


def read_view_blob(
    conn: sqlite3.Connection, state_root: Path, view_blob_id: str
) -> tuple[dict[str, object] | None, str]:
    """Return (parsed view, agreement-state-if-unavailable)."""
    raw = load_blob_bytes(conn, state_root, view_blob_id)
    if raw is None:
        return None, BLOB_ABSENT
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, BLOB_UNREADABLE
    if not isinstance(parsed, dict):
        return None, BLOB_UNREADABLE
    return parsed, BLOB_AGREES


def _event_id(catalog_path: str, scene_id: str, chosen: Sequence[str]) -> str:
    digest = hashlib.sha256()
    digest.update(catalog_path.encode())
    digest.update(b"\x00")
    digest.update(scene_id.encode())
    for key in sorted(chosen):
        digest.update(b"\x00")
        digest.update(key.encode())
    return f"selection-{digest.hexdigest()[:32]}"


def _pick_choice_set_kind(available: Sequence[str]) -> str | None:
    for kind in CHOICE_SET_KIND_PREFERENCE:
        if kind in available:
            return kind
    return None


def reconstruct_catalog(
    catalog: Path, state_root: Path | None = None
) -> tuple[list[SelectionEventV1], ReconstructionCensus]:
    """Rebuild every scorable selection event in one catalog.

    `state_root` defaults to the catalog's own directory, which is where the `blobs/`
    tree sits beside `catalog.sqlite` in a live state root.
    """
    catalog = Path(catalog)
    root = Path(state_root) if state_root is not None else catalog.parent
    census = ReconstructionCensus(catalog_path=str(catalog))
    events: list[SelectionEventV1] = []

    conn = open_catalog(catalog)
    try:
        census.commands_total = int(conn.execute("SELECT count(*) FROM command").fetchone()[0])
        census.scenes_total = int(conn.execute("SELECT count(*) FROM scene").fetchone()[0])

        acts_by_scene: dict[str, list[ActRef]] = {}
        for row in conn.execute(
            "SELECT command_id, committed_commit_seq, scene_id, client_session_id,"
            "       command_kind, subject_kind, subject_key, payload_blob_id,"
            "       issued_wall_us, received_wall_us, client_clock_id"
            " FROM command ORDER BY committed_commit_seq, command_id"
        ):
            if row["subject_kind"] != SELECTABLE_SUBJECT_KIND:
                # `record_focus` names the scene itself; a focus is not a selection.
                census.exclude(EXCLUSION_ACT_NOT_SUBJECT_BOUND)
                continue
            if not row["scene_id"]:
                # `command.scene_id` is nullable: an act with no scene has no choice set
                # and no counterfactual, however clearly it names a mint.
                census.exclude(EXCLUSION_ACT_NO_SCENE)
                continue
            acts_by_scene.setdefault(row["scene_id"], []).append(
                ActRef(
                    command_id=row["command_id"],
                    command_kind=row["command_kind"],
                    subject_kind=row["subject_kind"],
                    subject_key=row["subject_key"],
                    committed_commit_seq=int(row["committed_commit_seq"]),
                    issued_wall_us=int(row["issued_wall_us"]),
                    received_wall_us=int(row["received_wall_us"]),
                    client_session_id=row["client_session_id"],
                    client_clock_id=row["client_clock_id"],
                    payload_blob_id=row["payload_blob_id"],
                )
            )

        for scene_id, acts in sorted(acts_by_scene.items()):
            event = _build_event(conn, root, str(catalog), scene_id, acts, census)
            if event is not None:
                events.append(event)
                census.commands_scored_into_events += len(acts)
                census.blob_agreement[event.blob_agreement] = (
                    census.blob_agreement.get(event.blob_agreement, 0) + 1
                )
    finally:
        conn.close()

    census.events = len(events)
    events.sort(key=lambda e: (e.decision_wall_us, e.event_id))
    return events, census


def _build_event(
    conn: sqlite3.Connection,
    root: Path,
    catalog_path: str,
    scene_id: str,
    acts: list[ActRef],
    census: ReconstructionCensus,
) -> SelectionEventV1 | None:
    scene = conn.execute(
        "SELECT scene_id, scene_mode, captured_commit_seq, knowledge_cutoff_commit_seq,"
        "       outcome_cutoff_commit_seq, ui_build, view_contract, view_contract_version,"
        "       source_mode, rendered_wall_us, view_blob_id, view_sha256"
        " FROM scene WHERE scene_id = ?",
        (scene_id,),
    ).fetchone()
    if scene is None:
        census.exclude(EXCLUSION_SCENE_NO_CHOICE_SET, len(acts))
        return None

    members = conn.execute(
        "SELECT set_kind, subject_kind, subject_key, source_rank, rendered_ordinal"
        " FROM scene_choice_member WHERE scene_id = ?",
        (scene_id,),
    ).fetchall()
    available = tuple(sorted({r["set_kind"] for r in members}))
    chosen_kind = _pick_choice_set_kind(available)
    if chosen_kind is None:
        census.exclude(EXCLUSION_SCENE_NO_CHOICE_SET, len(acts))
        return None

    view, agreement = read_view_blob(conn, root, scene["view_blob_id"])
    prices = _view_candidates(view) if view is not None else {}

    members_in_set = [
        r
        for r in members
        if r["set_kind"] == chosen_kind and r["subject_kind"] == SELECTABLE_SUBJECT_KIND
    ]
    table_keys = {r["subject_key"] for r in members_in_set}
    if not table_keys:
        census.exclude(EXCLUSION_SCENE_NO_CHOICE_SET, len(acts))
        return None

    blob_only: tuple[str, ...] = ()
    table_only: tuple[str, ...] = ()
    if view is not None:
        blob_keys = set(prices)
        blob_only = tuple(sorted(blob_keys - table_keys))
        table_only = tuple(sorted(table_keys - blob_keys))
        if chosen_kind == "rendered":
            agreement = BLOB_AGREES if not blob_only and not table_only else BLOB_DISAGREES
        else:
            # A client-observed set (viewport) is an honest SUBSET of the rendered view by
            # construction — the store admits each asserted member only after proving it against
            # the exact served bytes — so the blob listing more candidates than the table is the
            # design, not a disagreement. Only a table member missing from the blob disagrees.
            agreement = BLOB_AGREES if not table_only else BLOB_DISAGREES

    chosen_keys = {a.subject_key for a in acts}
    off_set = chosen_keys - table_keys
    integrity: list[str] = []
    if off_set:
        # The operator marked something the scene's choice set does not contain. The event
        # is still real; the off-set acts cannot be ranked against a set they are not in.
        integrity.append(EXCLUSION_ACT_SUBJECT_OFF_CHOICE_SET)
        census.exclude(
            EXCLUSION_ACT_SUBJECT_OFF_CHOICE_SET,
            sum(1 for a in acts if a.subject_key in off_set),
        )
        acts = [a for a in acts if a.subject_key not in off_set]
        chosen_keys -= off_set
        if not acts:
            return None

    if chosen_keys >= table_keys:
        # Marking every candidate is not a selection: there is nothing passed over.
        census.exclude(EXCLUSION_NO_COUNTERFACTUAL, len(acts))
        return None

    def to_candidate(row: sqlite3.Row) -> CandidateRef:
        price, clock = prices.get(row["subject_key"], (None, None))
        return CandidateRef(
            subject_key=row["subject_key"],
            subject_kind=row["subject_kind"],
            source_rank=row["source_rank"],
            rendered_ordinal=row["rendered_ordinal"],
            price_sol=price,
            price_observed_wall_us=clock,
        )

    def order(row: sqlite3.Row) -> tuple[int, int, str]:
        ordinal = row["rendered_ordinal"]
        rank = row["source_rank"]
        return (
            ordinal if ordinal is not None else 1 << 30,
            rank if rank is not None else 1 << 30,
            row["subject_key"],
        )

    ordered = sorted(members_in_set, key=order)
    chosen = tuple(to_candidate(r) for r in ordered if r["subject_key"] in chosen_keys)
    passed = tuple(to_candidate(r) for r in ordered if r["subject_key"] not in chosen_keys)

    watermarks = tuple(
        WatermarkRef(
            watermark_namespace=r["watermark_namespace"],
            source_id=r["source_id"],
            projection_name=r["projection_name"],
            delivered_commit_seq=int(r["delivered_commit_seq"]),
        )
        for r in conn.execute(
            "SELECT watermark_namespace, source_id, projection_name, delivered_commit_seq"
            " FROM scene_watermark WHERE scene_id = ? ORDER BY watermark_namespace",
            (scene_id,),
        )
    )

    decision_wall_us = max(a.issued_wall_us for a in acts)
    rendered = int(scene["rendered_wall_us"])
    staleness = decision_wall_us - rendered
    if staleness < 0:
        integrity.append("act_precedes_scene_render")

    return SelectionEventV1(
        schema="joshi.selection.event.v1",
        event_id=_event_id(catalog_path, scene_id, sorted(chosen_keys)),
        catalog_path=catalog_path,
        scene_id=scene_id,
        scene_mode=scene["scene_mode"],
        view_sha256=scene["view_sha256"],
        ui_build=scene["ui_build"],
        view_contract=scene["view_contract"],
        view_contract_version=int(scene["view_contract_version"]),
        source_mode=scene["source_mode"],
        captured_commit_seq=int(scene["captured_commit_seq"]),
        knowledge_cutoff_commit_seq=int(scene["knowledge_cutoff_commit_seq"]),
        outcome_cutoff_commit_seq=(
            int(scene["outcome_cutoff_commit_seq"])
            if scene["outcome_cutoff_commit_seq"] is not None
            else None
        ),
        scene_rendered_wall_us=rendered,
        watermarks=watermarks,
        choice_set_kind=chosen_kind,
        choice_set_kind_available=available,
        chosen=chosen,
        passed=passed,
        acts=tuple(acts),
        decision_wall_us=decision_wall_us,
        decision_commit_seq=max(a.committed_commit_seq for a in acts),
        staleness_us=staleness,
        blob_agreement=agreement,
        blob_only_subjects=blob_only,
        table_only_subjects=table_only,
        integrity_flags=tuple(integrity),
    )


def reconstruct_many(
    catalogs: Sequence[Path],
) -> tuple[list[SelectionEventV1], list[ReconstructionCensus]]:
    all_events: list[SelectionEventV1] = []
    censuses: list[ReconstructionCensus] = []
    for path in catalogs:
        events, census = reconstruct_catalog(Path(path))
        all_events.extend(events)
        censuses.append(census)
    all_events.sort(key=lambda e: (e.decision_wall_us, e.event_id))
    return all_events, censuses


def iter_scene_prices(
    catalog: Path, state_root: Path | None = None
) -> Iterator[tuple[str, int, str, float, int]]:
    """Yield (scene_id, captured_commit_seq, mint, price_sol, market_clock_us).

    Every priced candidate observation this catalog durably retains, from every scene.
    This is the raw material the forward leg of an outcome is drawn from.
    """
    catalog = Path(catalog)
    root = Path(state_root) if state_root is not None else catalog.parent
    conn = open_catalog(catalog)
    try:
        for scene in conn.execute(
            "SELECT scene_id, captured_commit_seq, view_blob_id FROM scene"
            " ORDER BY captured_commit_seq, scene_id"
        ):
            view, _ = read_view_blob(conn, root, scene["view_blob_id"])
            if view is None:
                continue
            for mint, (price, clock) in _view_candidates(view).items():
                if price is None or clock is None:
                    continue
                yield (
                    scene["scene_id"],
                    int(scene["captured_commit_seq"]),
                    mint,
                    price,
                    clock,
                )
    finally:
        conn.close()
