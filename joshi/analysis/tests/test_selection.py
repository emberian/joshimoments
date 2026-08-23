"""Tests for the operator-selection instrument.

The synthetic catalogs here are built by applying the REAL migration SQL from
`schema/migrations/`, not a hand-written mirror of it. That matters: a mirror would drift
from the store and the tests would keep passing against a schema that no longer exists.
Building on the real DDL means these tests exercise the actual CHECK constraints, the
actual append-only triggers, and the actual `command_cannot_precede_scene` ordering rule.

Network-free. Everything is a tmp_path.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from joshi_analysis.selection import (
    build_price_index,
    build_report,
    measure_event,
    power_statement,
    reconstruct_catalog,
    render_report,
    score,
)
from joshi_analysis.selection.events import BLOB_AGREES, BLOB_DISAGREES
from joshi_analysis.selection.power import (
    detectable_rank_shift,
    null_rank_variance,
    scenes_needed_for_net_return,
    scenes_needed_for_rank_shift,
)
from joshi_analysis.selection.preregistration import (
    CHOICE_SET_KIND_PREFERENCE,
    DEFAULT_FEE_FLOOR_BPS,
    HORIZONS_SECONDS,
    OUTCOME_ABSENT_NO_FORWARD,
    OUTCOME_ABSENT_NO_PASSED,
    OUTCOME_PRESENT,
    PRIMARY_HORIZON_SECONDS,
)
from joshi_analysis.selection.score import (
    VERDICT_ADVERSE,
    VERDICT_SKILL_AND_EDGE,
    VERDICT_SKILL_NO_EDGE,
    VERDICT_UNDERPOWERED,
    fee_floor_log_cost,
    midranks,
    scene_statistic,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "schema" / "migrations"
US = 1_000_000


def _iso(wall_us: int) -> str:
    from datetime import UTC, datetime

    return (
        datetime.fromtimestamp(wall_us / US, tz=UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


class CatalogBuilder:
    """Build a real-schema catalog on disk, the way joshi-store would."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "blobs").mkdir(exist_ok=True)
        self.path = self.root / "catalog.sqlite"
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA foreign_keys=ON")
        for sql_file in sorted(MIGRATIONS.glob("*.sql"))[:6]:
            self.conn.executescript(sql_file.read_text())
        self.conn.execute(
            "INSERT INTO source (source_id, namespace, source_contract_version,"
            " collector_build, configuration_fingerprint, effect_ceiling)"
            " VALUES ('test.source.v1','read_only_market_source','joshi.sources.v1','0.1.0',?,"
            " 'observe_only')",
            ("f" * 64,),
        )
        self._commit_seq = 0
        self._prior = None

    def commit(self, wall_us: int, commit_class: str = "command") -> int:
        self._commit_seq += 1
        seq = self._commit_seq
        digest = hashlib.sha256(f"commit-{seq}".encode()).hexdigest()
        self.conn.execute(
            "INSERT INTO ingest_commit (commit_seq, commit_id, commit_class, committed_wall_us,"
            " writer_clock_id, committed_mono_ns, writer_build, prior_commit_digest, commit_digest)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (seq, f"c-{seq}", commit_class, wall_us, "test-clock", str(seq), "0.1.0",
             self._prior, digest),
        )
        self._prior = digest
        return seq

    def put_blob(self, payload: bytes, commit_seq: int, *, external: bool = True) -> str:
        blob_id = hashlib.sha256(payload).hexdigest()
        retention = "operator_private" if external else "public_source"
        rel = (
            f"{retention}/sha256/{blob_id[0:2]}/{blob_id[2:4]}/{blob_id}.blob"
            if external
            else None
        )
        if external:
            assert rel is not None
            on_disk = self.root / "blobs" / rel
            on_disk.parent.mkdir(parents=True, exist_ok=True)
            on_disk.write_bytes(payload)
        self.conn.execute(
            "INSERT OR IGNORE INTO blob (blob_id, created_commit_seq, storage_mode, inline_bytes,"
            " relative_path, content_length, stored_length, stored_sha256, compression,"
            " content_type, content_encoding, retention_class)"
            " VALUES (?,?,?,?,?,?,?,?, 'identity', 'application/json', NULL, ?)",
            (
                blob_id,
                commit_seq,
                "external" if external else "inline",
                None if external else payload,
                rel,
                len(payload),
                len(payload),
                blob_id,
                retention,
            ),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO blob_object (blob_id, storage_domain, storage_mode,"
            " inline_bytes, relative_path, stored_length, stored_sha256, compression)"
            " VALUES (?,?,?,?,?,?,?, 'identity')",
            (
                blob_id,
                retention,
                "external" if external else "inline",
                None if external else payload,
                rel,
                len(payload),
                blob_id,
            ),
        )
        return blob_id

    def add_scene(
        self,
        scene_id: str,
        rendered_wall_us: int,
        candidates: Sequence[tuple[str, float | None, int | None]],
        *,
        choice_members: Sequence[str] | None = None,
        set_kind: str = "rendered",
        session: str = "s-1",
        scene_seq: int = 0,
        external_blob: bool = True,
    ) -> tuple[str, int]:
        """candidates: (mint, price_sol or None, market clock us or None)."""
        commit_seq = self.commit(rendered_wall_us)
        view = {
            "contract": "joshi.glass.view",
            "schemaVersion": 1,
            "mode": "witnessed",
            "sceneId": scene_id,
            "basisSceneId": None,
            "asOf": {
                "catalogCommit": str(commit_seq),
                "sources": [],
                "chain": {"cluster": "solana", "slot": "1", "finality": "unstated"},
                "projections": [],
                "renderedAt": _iso(rendered_wall_us),
            },
            "payload": {
                "sources": [],
                "candidates": [
                    {
                        "id": mint,
                        "mint": mint,
                        "board": "watch",
                        "lifecycle": "unknown",
                        "firstKnownAt": _iso(rendered_wall_us),
                        "lastObservedAt": _iso(clock) if clock is not None else None,
                        "rank": str(i + 1),
                        "metrics": {"priceSol": price, "marketCapUsd": None},
                        "attentionReason": "",
                        "socialSummary": "",
                        "tags": [],
                        "evidence": [],
                        "candles": [],
                    }
                    for i, (mint, price, clock) in enumerate(sorted(candidates))
                ],
                "episodes": [],
                "socialEvents": [],
            },
        }
        raw = json.dumps(view, separators=(",", ":")).encode()
        blob_id = self.put_blob(raw, commit_seq, external=external_blob)
        self.conn.execute(
            "INSERT INTO scene (scene_id, scene_mode, captured_commit_seq,"
            " knowledge_cutoff_commit_seq, outcome_cutoff_commit_seq, basis_scene_id,"
            " client_session_id, client_scene_seq, ui_build, view_contract,"
            " view_contract_version, source_mode, rendered_wall_us, client_clock_id,"
            " rendered_mono_ns, view_blob_id, screenshot_blob_id, view_sha256)"
            " VALUES (?, 'witnessed', ?, ?, NULL, NULL, ?, ?, 'test-0.1', 'joshi.glass.view',"
            " 1, 'observatory', ?, 'test-clock', '0', ?, NULL, ?)",
            (scene_id, commit_seq, commit_seq, session, scene_seq, rendered_wall_us,
             blob_id, blob_id),
        )
        self.conn.execute(
            "INSERT INTO scene_artifact_contract (scene_id, artifact_role, blob_id,"
            " storage_domain) VALUES (?, 'view', ?, ?)",
            (scene_id, blob_id, "operator_private" if external_blob else "public_source"),
        )
        members = choice_members if choice_members is not None else [m for m, _, _ in candidates]
        for ordinal, mint in enumerate(sorted(members)):
            self.conn.execute(
                "INSERT INTO scene_choice_member (scene_id, set_kind, subject_kind, subject_key,"
                " source_rank, rendered_ordinal, evidence_assertion_id)"
                " VALUES (?, ?, 'candidate', ?, ?, ?, NULL)",
                (scene_id, set_kind, mint, ordinal + 1, ordinal),
            )
        self.conn.execute(
            "INSERT INTO scene_watermark (scene_id, watermark_namespace, source_id,"
            " projection_name, projection_version, delivered_commit_seq, state_sha256)"
            " VALUES (?, 'source:test.source.v1', 'test.source.v1', NULL, NULL, ?, NULL)",
            (scene_id, commit_seq),
        )
        return scene_id, commit_seq

    def add_act(
        self,
        scene_id: str,
        subject_key: str,
        issued_wall_us: int,
        *,
        command_kind: str = "record_annotation",
        subject_kind: str = "candidate",
        session: str = "s-1",
        command_seq: int = 1,
    ) -> str:
        commit_seq = self.commit(issued_wall_us)
        payload = json.dumps({"note": subject_key, "seq": command_seq}).encode()
        blob_id = self.put_blob(payload, commit_seq)
        command_id = f"cmd-{session}-{command_seq}"
        self.conn.execute(
            "INSERT INTO command (command_id, committed_commit_seq, scene_id, client_session_id,"
            " client_command_seq, idempotency_key, command_kind, subject_kind, subject_key,"
            " payload_blob_id, issued_wall_us, client_clock_id, issued_mono_ns, received_wall_us,"
            " effect_ceiling, authority_class)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?, 'test-clock', '0', ?, 'observe_only',"
            " 'evidence_only')",
            (command_id, commit_seq, scene_id, session, command_seq, f"idem-{command_id}",
             command_kind, subject_kind, subject_key, blob_id, issued_wall_us, issued_wall_us),
        )
        self.conn.execute(
            "INSERT INTO command_payload_contract (command_id, blob_id, storage_domain)"
            " VALUES (?,?, 'operator_private')",
            (command_id, blob_id),
        )
        return command_id

    def close(self) -> Path:
        self.conn.commit()
        self.conn.close()
        return self.path


T0 = 1_800_000_000 * US


# --- reconstruction -------------------------------------------------------------------


def test_reconstructs_choice_set_and_counts_non_selections(tmp_path: Path) -> None:
    b = CatalogBuilder(tmp_path / "cat")
    b.add_scene("scene-1", T0, [("mintA", 1.0, T0), ("mintB", 2.0, T0),
                                ("mintC", 3.0, T0), ("mintD", 4.0, T0)])
    b.add_act("scene-1", "mintB", T0 + 60 * US, command_seq=1)
    # a record_focus names the SCENE, not a candidate: not a selection
    b.add_act("scene-1", "scene-1", T0 + 61 * US, command_kind="record_focus",
              subject_kind="scene", command_seq=2)
    path = b.close()

    events, census = reconstruct_catalog(path)
    assert len(events) == 1
    event = events[0]
    assert event.choice_set_size == 4
    assert [c.subject_key for c in event.chosen] == ["mintB"]
    assert sorted(c.subject_key for c in event.passed) == ["mintA", "mintC", "mintD"]
    assert event.choice_set_kind == "rendered"
    assert event.blob_agreement == BLOB_AGREES
    assert event.staleness_us == 60 * US
    assert census.commands_total == 2
    assert census.exclusions["act_names_no_candidate"] == 1
    assert census.reconciles()


def test_several_acts_on_one_scene_are_one_event(tmp_path: Path) -> None:
    """Three holds in one scene is ONE decision with three chosen, not three decisions."""
    b = CatalogBuilder(tmp_path / "cat")
    b.add_scene("scene-1", T0, [(f"mint{c}", 1.0, T0) for c in "ABCDEFGH"])
    for i, mint in enumerate(["mintA", "mintC", "mintE"]):
        b.add_act("scene-1", mint, T0 + (10 + i) * US, command_seq=i + 1)
    path = b.close()

    events, census = reconstruct_catalog(path)
    assert len(events) == 1
    assert len(events[0].chosen) == 3
    assert len(events[0].passed) == 5
    # the decision instant is the LAST act, so the outcome window opens after all of them
    assert events[0].decision_wall_us == T0 + 12 * US
    assert census.commands_scored_into_events == 3


def test_marking_every_candidate_has_no_counterfactual(tmp_path: Path) -> None:
    b = CatalogBuilder(tmp_path / "cat")
    b.add_scene("scene-1", T0, [("mintA", 1.0, T0), ("mintB", 2.0, T0)])
    b.add_act("scene-1", "mintA", T0 + 5 * US, command_seq=1)
    b.add_act("scene-1", "mintB", T0 + 6 * US, command_seq=2)
    path = b.close()

    events, census = reconstruct_catalog(path)
    assert events == []
    assert census.exclusions["scene_chosen_set_is_whole_choice_set"] == 2
    assert census.reconciles()


def test_blob_and_choice_table_disagreement_is_reported_not_resolved(tmp_path: Path) -> None:
    b = CatalogBuilder(tmp_path / "cat")
    b.add_scene(
        "scene-1",
        T0,
        [("mintA", 1.0, T0), ("mintB", 2.0, T0)],
        choice_members=["mintA", "mintB", "mintGHOST"],
    )
    b.add_act("scene-1", "mintA", T0 + 5 * US, command_seq=1)
    path = b.close()

    events, _ = reconstruct_catalog(path)
    assert events[0].blob_agreement == BLOB_DISAGREES
    assert events[0].table_only_subjects == ("mintGHOST",)
    assert events[0].blob_only_subjects == ()


def test_act_naming_a_subject_off_the_choice_set_is_counted(tmp_path: Path) -> None:
    b = CatalogBuilder(tmp_path / "cat")
    b.add_scene("scene-1", T0, [("mintA", 1.0, T0), ("mintB", 2.0, T0)])
    b.add_act("scene-1", "mintA", T0 + 5 * US, command_seq=1)
    b.add_act("scene-1", "mintNOTHERE", T0 + 6 * US, command_seq=2)
    path = b.close()

    events, census = reconstruct_catalog(path)
    assert len(events) == 1
    assert [c.subject_key for c in events[0].chosen] == ["mintA"]
    assert census.exclusions["act_subject_absent_from_choice_set"] == 1
    assert "act_subject_absent_from_choice_set" in events[0].integrity_flags


def test_viewport_wins_over_rendered_as_the_denominator(tmp_path: Path) -> None:
    """Scoring against a set she never saw would inflate skill for free."""
    assert CHOICE_SET_KIND_PREFERENCE[0] == "viewport"
    assert "eligible" not in CHOICE_SET_KIND_PREFERENCE
    b = CatalogBuilder(tmp_path / "cat")
    b.add_scene("scene-1", T0, [("mintA", 1.0, T0), ("mintB", 2.0, T0), ("mintC", 3.0, T0)])
    conn = b.conn
    for ordinal, mint in enumerate(["mintA", "mintB"]):
        conn.execute(
            "INSERT INTO scene_choice_member (scene_id, set_kind, subject_kind, subject_key,"
            " source_rank, rendered_ordinal, evidence_assertion_id)"
            " VALUES ('scene-1', 'viewport', 'candidate', ?, ?, ?, NULL)",
            (mint, ordinal + 1, ordinal),
        )
    b.add_act("scene-1", "mintA", T0 + 5 * US, command_seq=1)
    path = b.close()

    events, _ = reconstruct_catalog(path)
    assert events[0].choice_set_kind == "viewport"
    assert events[0].choice_set_size == 2  # mintC was rendered but never in the viewport


def test_inline_blobs_load_as_well_as_external(tmp_path: Path) -> None:
    b = CatalogBuilder(tmp_path / "cat")
    b.add_scene("scene-1", T0, [("mintA", 1.0, T0), ("mintB", 2.0, T0)], external_blob=False)
    b.add_act("scene-1", "mintA", T0 + 5 * US, command_seq=1)
    path = b.close()
    events, _ = reconstruct_catalog(path)
    assert events[0].blob_agreement == BLOB_AGREES
    assert events[0].chosen[0].price_sol == 1.0


def test_missing_external_blob_is_absent_not_a_crash(tmp_path: Path) -> None:
    b = CatalogBuilder(tmp_path / "cat")
    b.add_scene("scene-1", T0, [("mintA", 1.0, T0), ("mintB", 2.0, T0)])
    b.add_act("scene-1", "mintA", T0 + 5 * US, command_seq=1)
    path = b.close()
    for blob in (path.parent / "blobs").rglob("*.blob"):
        blob.unlink()
    events, _ = reconstruct_catalog(path)
    assert events[0].blob_agreement == "blob_absent"
    assert events[0].chosen[0].price_sol is None


# --- leakage --------------------------------------------------------------------------


def test_forward_leg_never_uses_an_observation_at_or_before_the_act(tmp_path: Path) -> None:
    """The whole no-leakage guarantee is one strict inequality. Pin it."""
    b = CatalogBuilder(tmp_path / "cat")
    decision = T0 + 60 * US
    b.add_scene("scene-1", T0, [("mintA", 1.0, T0), ("mintB", 1.0, T0)])
    b.add_act("scene-1", "mintA", decision, command_seq=1)
    # a scene rendered LATER but carrying market clocks BEFORE the decision: must not count
    b.add_scene(
        "scene-2",
        decision + 3600 * US,
        [("mintA", 99.0, decision - 1), ("mintB", 0.01, decision - 1)],
        session="s-2",
        scene_seq=0,
    )
    path = b.close()

    events, _ = reconstruct_catalog(path)
    index = build_price_index([path])
    outcome = measure_event(events[0], index, 3600)
    assert outcome.status == OUTCOME_ABSENT_NO_FORWARD
    assert all(c.log_return is None for c in outcome.candidates)


def test_render_time_is_not_used_as_the_market_clock(tmp_path: Path) -> None:
    """A scene rendered at the horizon whose prices were observed long before must not score."""
    b = CatalogBuilder(tmp_path / "cat")
    decision = T0 + 60 * US
    b.add_scene("scene-1", T0, [("mintA", 1.0, T0), ("mintB", 1.0, T0)])
    b.add_act("scene-1", "mintA", decision, command_seq=1)
    b.add_scene(
        "scene-2",
        decision + 3600 * US,
        [("mintA", 5.0, T0 - 10 * US), ("mintB", 0.1, T0 - 10 * US)],
        session="s-2",
    )
    path = b.close()
    events, _ = reconstruct_catalog(path)
    outcome = measure_event(events[0], build_price_index([path]), 3600)
    assert outcome.status == OUTCOME_ABSENT_NO_FORWARD


def test_forward_outside_the_tolerance_band_does_not_count(tmp_path: Path) -> None:
    """A real post-act observation at no admissible horizon is still absent at that horizon.

    +2h falls in the gap between the 1h band [2880s, 4320s] and the 4h band
    [11520s, 17280s]. It is a genuine forward price and it scores nothing, because the
    horizons are pre-registered and the bands are not stretched to reach it.
    """
    b = CatalogBuilder(tmp_path / "cat")
    decision = T0 + 60 * US
    b.add_scene("scene-1", T0, [("mintA", 1.0, T0), ("mintB", 1.0, T0)])
    b.add_act("scene-1", "mintA", decision, command_seq=1)
    b.add_scene(
        "scene-2",
        decision + 7200 * US,
        [("mintA", 2.0, decision + 7200 * US), ("mintB", 0.5, decision + 7200 * US)],
        session="s-2",
    )
    path = b.close()
    events, _ = reconstruct_catalog(path)
    index = build_price_index([path])
    for horizon in HORIZONS_SECONDS:
        assert measure_event(events[0], index, horizon).status == OUTCOME_ABSENT_NO_FORWARD

    b2 = CatalogBuilder(tmp_path / "cat2")
    b2.add_scene("scene-1", T0, [("mintA", 1.0, T0), ("mintB", 1.0, T0)])
    b2.add_act("scene-1", "mintA", decision, command_seq=1)
    b2.add_scene(
        "scene-2",
        decision + 3600 * US,
        [("mintA", 2.0, decision + 3600 * US), ("mintB", 0.5, decision + 3600 * US)],
        session="s-2",
    )
    path2 = b2.close()
    events2, _ = reconstruct_catalog(path2)
    assert measure_event(events2[0], build_price_index([path2]), 3600).status == OUTCOME_PRESENT


# --- absence --------------------------------------------------------------------------


def test_absent_outcome_is_counted_never_zero_filled(tmp_path: Path) -> None:
    b = CatalogBuilder(tmp_path / "cat")
    b.add_scene("scene-1", T0, [("mintA", 1.0, T0), ("mintB", 1.0, T0)])
    b.add_act("scene-1", "mintA", T0 + 60 * US, command_seq=1)
    path = b.close()

    report = build_report([path])
    assert len(report.events) == 1
    for horizon in HORIZONS_SECONDS:
        sc = report.scores[horizon]
        assert sc.n_events == 1
        assert sc.n_scored == 0
        assert sum(sc.absence_reasons.values()) == 1
        assert sc.verdict == VERDICT_UNDERPOWERED
        assert sc.s1_mean_normalised_rank != sc.s1_mean_normalised_rank  # NaN, not 0.5
    note = report.scores[PRIMARY_HORIZON_SECONDS].verdict_note
    assert "This is an absence of measurement, not a measurement of no effect." in note
    assert "absent" in render_report(report)


def test_chosen_scored_but_no_passed_scored_is_absent(tmp_path: Path) -> None:
    """A one-sided score would abandon the within-scene design. It must be absent instead."""
    b = CatalogBuilder(tmp_path / "cat")
    decision = T0 + 60 * US
    b.add_scene("scene-1", T0, [("mintA", 1.0, T0), ("mintB", 1.0, T0)])
    b.add_act("scene-1", "mintA", decision, command_seq=1)
    b.add_scene("scene-2", decision + 3600 * US,
                [("mintA", 2.0, decision + 3600 * US)], session="s-2")
    path = b.close()
    events, _ = reconstruct_catalog(path)
    outcome = measure_event(events[0], build_price_index([path]), 3600)
    assert outcome.status == OUTCOME_ABSENT_NO_PASSED
    assert scene_statistic(outcome) is None


# --- scoring --------------------------------------------------------------------------


def _picker_catalog(root: Path, n_scenes: int, chosen_rank: str, drift: float) -> Path:
    """n scenes of 4 candidates; `chosen_rank` says where the operator's pick lands.

    `drift` multiplies every candidate's forward price, so a whole-market move can be
    added without changing any within-scene ordering.
    """
    b = CatalogBuilder(root)
    for i in range(n_scenes):
        base = T0 + i * 100_000 * US
        decision = base + 60 * US
        mints = [f"m{i}{c}" for c in "ABCD"]
        b.add_scene(f"scene-{i}", base, [(m, 1.0, base) for m in mints],
                    session=f"s-{i}", scene_seq=0)
        pick = {"best": mints[0], "worst": mints[3], "middle": mints[1]}[chosen_rank]
        b.add_act(f"scene-{i}", pick, decision, session=f"s-{i}", command_seq=1)
        forward = base + 3660 * US
        # mints[0] best .. mints[3] worst, before the market-wide drift
        prices = [1.20, 1.10, 1.00, 0.90]
        b.add_scene(
            f"scene-{i}-fwd",
            forward,
            [(m, p * drift, forward) for m, p in zip(mints, prices, strict=True)],
            session=f"s-{i}-f",
            scene_seq=0,
        )
    return b.close()


def test_a_perfect_picker_scores_rank_one(tmp_path: Path) -> None:
    path = _picker_catalog(tmp_path / "cat", 12, "best", 1.0)
    report = build_report([path])
    sc = report.scores[PRIMARY_HORIZON_SECONDS]
    assert sc.n_scored == 12
    assert sc.s1_mean_normalised_rank == pytest.approx(1.0)
    assert sc.s1_permutation_p < 0.01
    assert sc.s2_mean_excess_log > 0
    assert sc.verdict == VERDICT_SKILL_AND_EDGE


def test_an_adverse_picker_is_reported_as_adverse(tmp_path: Path) -> None:
    path = _picker_catalog(tmp_path / "cat", 12, "worst", 1.0)
    sc = build_report([path]).scores[PRIMARY_HORIZON_SECONDS]
    assert sc.s1_mean_normalised_rank == pytest.approx(0.0)
    assert sc.s1_permutation_p < 0.01
    assert sc.verdict == VERDICT_ADVERSE


def test_market_wide_move_cancels_within_the_scene(tmp_path: Path) -> None:
    """The design's whole claim: 'everything went up' must not register as skill."""
    flat = build_report([_picker_catalog(tmp_path / "a", 12, "best", 1.0)])
    lifted = build_report([_picker_catalog(tmp_path / "b", 12, "best", 3.0)])
    f = flat.scores[PRIMARY_HORIZON_SECONDS]
    r = lifted.scores[PRIMARY_HORIZON_SECONDS]
    assert f.s1_mean_normalised_rank == pytest.approx(r.s1_mean_normalised_rank)
    assert f.s2_mean_excess_log == pytest.approx(r.s2_mean_excess_log)
    # S3 is not scene-relative and MUST move: a 3x market lift is a real tradeable gain
    assert r.s3_mean_net_log > f.s3_mean_net_log


def test_perfect_ranking_below_the_fee_floor_is_not_an_edge(tmp_path: Path) -> None:
    """Picking the best coin in a room that does not pay for the trade is not an edge."""
    b = CatalogBuilder(tmp_path / "cat")
    for i in range(15):
        base = T0 + i * 100_000 * US
        decision = base + 60 * US
        mints = [f"m{i}{c}" for c in "ABCD"]
        b.add_scene(f"scene-{i}", base, [(m, 1.0, base) for m in mints],
                    session=f"s-{i}", scene_seq=0)
        b.add_act(f"scene-{i}", mints[0], decision, session=f"s-{i}", command_seq=1)
        forward = base + 3660 * US
        # chosen wins every scene, but by less than the 247 bps round-trip floor
        prices = [1.005, 1.003, 1.001, 0.999]
        b.add_scene(f"scene-{i}-fwd", forward,
                    [(m, p, forward) for m, p in zip(mints, prices, strict=True)],
                    session=f"s-{i}-f", scene_seq=0)
    path = b.close()

    sc = build_report([path]).scores[PRIMARY_HORIZON_SECONDS]
    assert sc.s1_mean_normalised_rank == pytest.approx(1.0)
    assert sc.s1_permutation_p < 0.01
    assert sc.s2_mean_excess_log > 0
    assert sc.s3_mean_net_log < 0
    assert sc.verdict == VERDICT_SKILL_NO_EDGE
    assert "not an edge" in sc.verdict_note


def test_negative_control_a_random_picker_shows_no_evidence(tmp_path: Path) -> None:
    """The control that has to hold: a picker with no skill must not read as skilled.

    The pick is drawn from a fixed-seed RNG independent of the forward returns, so the
    null is true by construction. If this ever fails, the instrument manufactures skill.
    """
    import random as _r

    rng = _r.Random(4242)
    b = CatalogBuilder(tmp_path / "cat")
    for i in range(40):
        base = T0 + i * 100_000 * US
        decision = base + 60 * US
        mints = [f"m{i}{c}" for c in "ABCD"]
        b.add_scene(f"scene-{i}", base, [(m, 1.0, base) for m in mints],
                    session=f"s-{i}", scene_seq=0)
        b.add_act(f"scene-{i}", rng.choice(mints), decision, session=f"s-{i}", command_seq=1)
        forward = base + 3660 * US
        prices = [1.20, 1.10, 1.00, 0.90]
        b.add_scene(f"scene-{i}-fwd", forward,
                    [(m, p, forward) for m, p in zip(mints, prices, strict=True)],
                    session=f"s-{i}-f", scene_seq=0)
    path = b.close()

    sc = build_report([path]).scores[PRIMARY_HORIZON_SECONDS]
    assert sc.n_scored == 40
    assert sc.s1_permutation_p > 0.05
    assert sc.verdict not in {VERDICT_SKILL_AND_EDGE, VERDICT_ADVERSE}


# --- statistics -----------------------------------------------------------------------


def test_midranks_average_ties() -> None:
    assert midranks([1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]
    assert midranks([5.0, 5.0, 9.0]) == [1.5, 1.5, 3.0]
    assert midranks([2.0, 2.0, 2.0]) == [2.0, 2.0, 2.0]


def test_null_rank_variance_matches_simulation() -> None:
    """The closed form the power table rests on, checked against brute force."""
    import random as _r
    from statistics import pvariance

    for k, m in [(4, 1), (8, 1), (8, 3), (12, 2)]:
        grid = [(r - 1) / (k - 1) for r in range(1, k + 1)]
        rng = _r.Random(7)
        draws = [sum(rng.sample(grid, m)) / m for _ in range(200_000)]
        assert pvariance(draws) == pytest.approx(null_rank_variance(k, m), rel=0.03)


def test_choosing_everything_carries_no_information() -> None:
    assert null_rank_variance(4, 4) == 0.0
    with pytest.raises(ValueError):
        scenes_needed_for_rank_shift(0.1, k=4, m=4)


def test_fee_floor_log_cost_is_a_positive_cost() -> None:
    assert fee_floor_log_cost(247) == pytest.approx(0.02501, abs=1e-4)
    assert fee_floor_log_cost(60) < fee_floor_log_cost(247)
    assert fee_floor_log_cost(DEFAULT_FEE_FLOOR_BPS) > 0


def test_power_requirement_shrinks_with_effect_size() -> None:
    n = [scenes_needed_for_rank_shift(d, k=8) for d in (0.05, 0.10, 0.20)]
    assert n == sorted(n, reverse=True)
    assert n[1] == 85
    # the economic test is far more expensive than the discrimination test
    assert scenes_needed_for_net_return(0.05) > scenes_needed_for_rank_shift(0.10, k=8) * 5


def test_alpha_and_power_cannot_be_shopped() -> None:
    with pytest.raises(ValueError):
        scenes_needed_for_rank_shift(0.1, power=0.5)
    with pytest.raises(ValueError):
        scenes_needed_for_net_return(0.1, alpha=0.2)


def test_zero_scenes_detect_nothing() -> None:
    assert detectable_rank_shift(0) == float("inf")
    stmt = power_statement(n_scored_now=0)
    assert stmt.detectable_now == float("inf")
    assert "No effect of any size is" in render_report(build_report([]))


def test_score_on_nothing_invents_nothing() -> None:
    sc = score([], PRIMARY_HORIZON_SECONDS)
    assert sc.n_scored == 0
    assert sc.verdict == VERDICT_UNDERPOWERED
    assert "not a measurement of no effect" in sc.verdict_note
