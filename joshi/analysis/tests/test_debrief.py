"""Tests for the session debrief.

Catalog fixtures are built on the REAL migration SQL (via test_selection.CatalogBuilder),
and the operator-act payloads carry the REAL frozen wire shapes: a hold, a hold note, a
journal entry and a disposition are exactly the bytes apps/glass would commit, so a label
drift between the debrief and the cockpit would fail here rather than silently orphaning
her words. Network-free; everything is a tmp_path.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from test_selection import MIGRATIONS, T0, US, CatalogBuilder, _iso

from joshi_analysis.debrief import (
    HOLD_NOTE_UI_LABEL,
    HOLD_UI_LABEL,
    JOURNAL_UI_LABEL,
    read_inputs,
    read_paired_windows,
    render_day_debrief,
    session_days,
    write_day_debrief,
)
from joshi_analysis.debrief.artifact import EDGE_NET_LOG, SKILL_RANK_SHIFT
from joshi_analysis.selection.power import (
    scenes_needed_for_net_return,
    scenes_needed_for_rank_shift,
)

DAY = "2027-01-15"  # the UTC day T0 falls on
NOW = T0 + 6 * 3600 * US


def _context(ui_label: str, note: str | None) -> dict[str, object]:
    return {
        "uiLabel": ui_label,
        "uiLabelVersion": "1",
        "confidencePpm": None,
        "urgency": None,
        "whyNow": None,
        "note": note,
    }


def hold_payload() -> dict[str, object]:
    return {"context": _context(HOLD_UI_LABEL, None), "dwellMilliseconds": None}


def hold_note_payload(words: str) -> dict[str, object]:
    return {"context": _context(HOLD_NOTE_UI_LABEL, words), "dwellMilliseconds": None}


def journal_payload(words: str) -> dict[str, object]:
    return {"context": _context(JOURNAL_UI_LABEL, words), "dwellMilliseconds": None}


def disposition_payload(words: str, provisional: bool = True) -> dict[str, object]:
    return {
        "context": _context("Record disposition", None),
        "disposition": words,
        "provisional": provisional,
    }


class RichCatalogBuilder(CatalogBuilder):
    """CatalogBuilder plus identity/mcap-bearing scenes and wire-shaped operator acts."""

    def add_rich_scene(
        self,
        scene_id: str,
        rendered_wall_us: int,
        candidates: list[tuple[str, str | None, str | None, float | None, float | None, int]],
        *,
        session: str = "s-1",
        scene_seq: int = 0,
    ) -> None:
        """candidates: (mint, symbol, name, price_sol, mcap_usd, market_clock_us)."""
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
                        "symbol": symbol,
                        "name": name,
                        "board": "watch",
                        "lifecycle": "unknown",
                        "firstKnownAt": _iso(rendered_wall_us),
                        "lastObservedAt": _iso(clock),
                        "rank": str(i + 1),
                        "metrics": {"priceSol": price, "marketCapUsd": mcap},
                        "attentionReason": "",
                        "socialSummary": "",
                        "tags": [],
                        "evidence": [],
                        "candles": [],
                    }
                    for i, (mint, symbol, name, price, mcap, clock) in enumerate(
                        sorted(candidates)
                    )
                ],
                "episodes": [],
                "socialEvents": [],
            },
        }
        raw = json.dumps(view, separators=(",", ":")).encode()
        blob_id = self.put_blob(raw, commit_seq)
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
        for ordinal, (mint, *_rest) in enumerate(sorted(candidates)):
            self.conn.execute(
                "INSERT INTO scene_choice_member (scene_id, set_kind, subject_kind,"
                " subject_key, source_rank, rendered_ordinal, evidence_assertion_id)"
                " VALUES (?, 'rendered', 'candidate', ?, ?, ?, NULL)",
                (scene_id, mint, ordinal + 1, ordinal),
            )
        self.conn.execute(
            "INSERT INTO scene_watermark (scene_id, watermark_namespace, source_id,"
            " projection_name, projection_version, delivered_commit_seq, state_sha256)"
            " VALUES (?, 'source:test.source.v1', 'test.source.v1', NULL, NULL, ?, NULL)",
            (scene_id, commit_seq),
        )

    def add_wire_act(
        self,
        scene_id: str | None,
        subject_kind: str,
        subject_key: str,
        issued_wall_us: int,
        payload: dict[str, object] | bytes,
        *,
        command_kind: str = "record_focus",
        session: str = "s-1",
        command_seq: int = 1,
    ) -> str:
        commit_seq = self.commit(issued_wall_us)
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        blob_id = self.put_blob(raw, commit_seq)
        command_id = f"cmd-{session}-{command_seq}"
        self.conn.execute(
            "INSERT INTO command (command_id, committed_commit_seq, scene_id,"
            " client_session_id, client_command_seq, idempotency_key, command_kind,"
            " subject_kind, subject_key, payload_blob_id, issued_wall_us, client_clock_id,"
            " issued_mono_ns, received_wall_us, effect_ceiling, authority_class)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?, 'test-clock', '0', ?, 'observe_only',"
            " 'evidence_only')",
            (command_id, commit_seq, scene_id, session, command_seq, f"idem-{command_id}",
             command_kind, subject_kind, subject_key, blob_id, issued_wall_us,
             issued_wall_us),
        )
        self.conn.execute(
            "INSERT INTO command_payload_contract (command_id, blob_id, storage_domain)"
            " VALUES (?,?, 'operator_private')",
            (command_id, blob_id),
        )
        return command_id


HOLD_FABLE_US = T0 + 60 * US
NOTE_WORDS = "same wick as yesterday\nand the room is thin"
DISPOSITION_WORDS = "crackle then runner, might send it"
JOURNAL_WORDS = "on this day we discussed the thin open over these charts"


def _rich_catalog(root: Path) -> Path:
    """One day: two holds over one scene, words in her voice, a partial forward path."""
    b = RichCatalogBuilder(root / "catalog")
    b.add_rich_scene(
        "scene-1",
        T0,
        [
            ("fable", "FABLE", "Fable Coin", 1.0, 8400.0, T0 - 10 * US),
            ("moss", "MOSS", None, 2.0, 21000.0, T0 - 10 * US),
            ("copper", None, None, 3.0, None, T0 - 10 * US),
            ("dust", None, None, 4.0, 9000.0, T0 - 10 * US),
        ],
    )
    b.add_wire_act("scene-1", "candidate", "fable", HOLD_FABLE_US, hold_payload(),
                   command_seq=1)
    b.add_wire_act("scene-1", "candidate", "fable", T0 + 120 * US,
                   hold_note_payload(NOTE_WORDS), command_seq=2)
    b.add_wire_act("scene-1", "candidate", "fable", T0 + 180 * US,
                   disposition_payload(DISPOSITION_WORDS), command_kind="record_disposition",
                   command_seq=3)
    b.add_wire_act("scene-1", "scene", "scene-1", T0 + 200 * US,
                   journal_payload(JOURNAL_WORDS), command_seq=4)
    b.add_wire_act("scene-1", "candidate", "moss", T0 + 240 * US, hold_payload(),
                   command_seq=5)
    # forward scene an hour on: fable moved, moss was never observed again
    b.add_rich_scene(
        "scene-2",
        T0 + 3660 * US,
        [
            ("fable", "FABLE", "Fable Coin", 1.25, 10500.0, T0 + 3660 * US),
            ("copper", None, None, 2.7, None, T0 + 3660 * US),
            ("dust", None, None, 3.6, 8100.0, T0 + 3660 * US),
        ],
        session="s-2",
    )
    # a later-rendered scene whose fable price carries a market clock AT the hold instant:
    # admissible nowhere, because forward is strictly after the act
    b.add_rich_scene(
        "scene-leak",
        T0 + 7200 * US,
        [("fable", "FABLE", "Fable Coin", 99.0, 999000.0, HOLD_FABLE_US)],
        session="s-3",
    )
    return b.close()


def _artifact_for(tmp_path: Path, catalog_dir: Path) -> str:
    session_state = tmp_path / "cockpit-state"
    session_state.mkdir(exist_ok=True)
    inputs = read_inputs(session_state, catalog_dir)
    assert DAY in session_days(inputs)
    return render_day_debrief(inputs, DAY, NOW)


# --- her words ------------------------------------------------------------------------


def test_words_are_quoted_verbatim_and_holds_stay_in_hold_order(tmp_path: Path) -> None:
    catalog = _rich_catalog(tmp_path)
    text = _artifact_for(tmp_path, catalog.parent)

    # every line of every utterance, byte for byte, as a quote
    assert "> same wick as yesterday" in text
    assert "> and the room is thin" in text
    assert f"> {DISPOSITION_WORDS}" in text
    assert f"> {JOURNAL_WORDS}" in text
    assert "Disposition (provisional)" in text
    # hold order: fable was held before moss
    assert text.index("FABLE — Fable Coin (`fable`)") < text.index("MOSS (`moss`)")
    # identity comes from the retained scene; the mint rides along
    assert "FABLE — Fable Coin (`fable`)" in text


def test_forward_path_carries_deltas_ages_and_sources(tmp_path: Path) -> None:
    catalog = _rich_catalog(tmp_path)
    text = _artifact_for(tmp_path, catalog.parent)

    # at the hold: the decision scene's own reading, with its age relative to the act
    assert "price 1 SOL" in text
    assert "mcap $8,400" in text
    # forward: provider-asserted deltas with clock and source
    assert "+25.0% vs the held scene" in text
    assert "mcap $10,500 (+25.0%)" in text
    assert "source test.source.v1" in text
    assert "scene `scene-2`" in text
    # no net-of-fees claim without a measured floor for the coin
    assert text.count("venue floor: unmeasured") == 2
    assert "net of fees" not in text.lower()


def test_forward_path_never_reads_an_observation_at_or_before_the_act(
    tmp_path: Path,
) -> None:
    """scene-leak's fable price (99 SOL) has a market clock AT the hold: inadmissible."""
    catalog = _rich_catalog(tmp_path)
    text = _artifact_for(tmp_path, catalog.parent)
    assert "99 SOL" not in text
    assert "999,000" not in text


def test_a_coin_with_no_posthold_observation_is_an_absent_record(tmp_path: Path) -> None:
    catalog = _rich_catalog(tmp_path)
    text = _artifact_for(tmp_path, catalog.parent)
    moss = text[text.index("MOSS (`moss`)") :]
    moss = moss[: moss.index("## 3.")]
    assert "ABSENT RECORD" in moss
    assert "not a zero" in moss


# --- the tally reports, it does not re-score ------------------------------------------


def test_tally_reuses_the_selection_reconstruction_and_power_constants(
    tmp_path: Path,
) -> None:
    catalog = _rich_catalog(tmp_path)
    session_state = tmp_path / "cockpit-state"
    session_state.mkdir(exist_ok=True)
    inputs = read_inputs(session_state, catalog.parent)
    text = render_day_debrief(inputs, DAY, NOW)

    # both holds land on one scene: ONE selection event, exactly as the instrument counts
    assert len(inputs.selection.events) == 1
    assert "this day: 1 selection event(s) reconstructed" in text
    # the pre-registered requirement is computed from power.py, not re-hardcoded
    k = inputs.selection.power.choice_set_size
    skill = scenes_needed_for_rank_shift(SKILL_RANK_SHIFT, k=k)
    edge = scenes_needed_for_net_return(EDGE_NET_LOG)
    assert f"needs ~{skill} scored scenes" in text
    assert f"needs ~{edge}" in text
    # the verdict sentence is the instrument's own, quoted
    verdict = inputs.selection.scores[3600].verdict
    assert f"**{verdict}**" in text
    # the fallback denominator is counted, per the pre-registration's caveat
    assert "rendered: 1" in text
    assert "the first ten holds prove nothing" in text


def test_integrity_footnotes_carry_reconstruction_flags(tmp_path: Path) -> None:
    b = RichCatalogBuilder(tmp_path / "catalog")
    b.add_rich_scene("scene-1", T0, [("fable", None, None, 1.0, None, T0)])
    # the choice-set table asserts a member the served bytes never contained
    b.conn.execute(
        "INSERT INTO scene_choice_member (scene_id, set_kind, subject_kind, subject_key,"
        " source_rank, rendered_ordinal, evidence_assertion_id)"
        " VALUES ('scene-1', 'rendered', 'candidate', 'ghost', 2, 1, NULL)",
        (),
    )
    b.add_wire_act("scene-1", "candidate", "fable", T0 + 5 * US, hold_payload(),
                   command_seq=1)
    # an act whose payload blob is not JSON: its words are gone and the artifact says so
    b.add_wire_act("scene-1", "candidate", "fable", T0 + 9 * US, b"\xff not json",
                   command_seq=2)
    catalog = b.close()
    text = _artifact_for(tmp_path, catalog.parent)

    assert "disagrees" in text
    assert "ghost" in text
    assert "1 operator act payload blob(s) unreadable" in text
    assert "not readable" in text or "not reconstructable" in text


# --- the honest empty debrief ---------------------------------------------------------


def _pairing_occurrence_doc(occurrence_id: str) -> tuple[str, bytes]:
    body = json.dumps({"occurrenceId": occurrence_id}).encode()
    return hashlib.sha256(body).hexdigest(), body


def _build_pairing_catalog(root: Path) -> None:
    """Real-DDL pairing store: epoch -> issued -> consumed -> restart_invalidated."""
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "catalog.sqlite")
    conn.execute("PRAGMA foreign_keys=ON")
    for sql_file in sorted(MIGRATIONS.glob("*.sql"))[:10]:
        conn.executescript(sql_file.read_text())
    prior = None
    for seq in range(1, 6):
        digest = hashlib.sha256(f"pair-commit-{seq}".encode()).hexdigest()
        conn.execute(
            "INSERT INTO ingest_commit (commit_seq, commit_id, commit_class,"
            " committed_wall_us, writer_clock_id, committed_mono_ns, writer_build,"
            " prior_commit_digest, commit_digest) VALUES (?,?,?,?,?,?,?,?,?)",
            (seq, f"pc-{seq}", "command", T0 + seq, "test-clock", str(seq), "0.1.0",
             prior, digest),
        )
        prior = digest

    def occurrence(occurrence_id: str, **fields: object) -> None:
        sha, body = _pairing_occurrence_doc(occurrence_id)
        row: dict[str, object] = {
            "pairing_occurrence_id": occurrence_id,
            "issue_id": None,
            "session_id": None,
            "predecessor_occurrence_id": None,
            "origin": "http://127.0.0.1:4173",
            "epoch": 1,
            "at_monotonic_ms": "0",
            "expires_wall_us": None,
            "scopes_json": "[]",
            "failed_attempt_ordinal": None,
            "attempt_window_started_monotonic_ms": None,
            "rate_window_id": None,
            "rate_window_started_wall_us": None,
            "rate_window_expires_wall_us": None,
            "reason": None,
            "document_sha256": sha,
            "document_bytes": body,
            "document_byte_length": len(body),
            "authority": "read_only_pairing_exchange",
        }
        row.update(fields)
        columns = ", ".join(row)
        holes = ", ".join("?" for _ in row)
        conn.execute(
            f"INSERT INTO wave5_g0_pairing_occurrence_v1 ({columns}) VALUES ({holes})",
            tuple(row.values()),
        )

    def epoch(occurrence_id: str, epoch: int, observed_wall_us: int, commit_seq: int) -> None:
        occurrence(occurrence_id, occurrence_kind="epoch_started", epoch=epoch,
                   observed_wall_us=observed_wall_us, created_commit_seq=commit_seq)
        conn.execute(
            "INSERT INTO wave5_g0_pairing_epoch_v1 (origin, epoch, observed_wall_us,"
            " max_failed_attempts, attempt_window_ms, max_issued_per_window,"
            " issue_window_ms, last_observed_wall_us, attempt_window_id, attempt_used,"
            " attempt_expires_wall_us, issue_window_id, issue_used, issue_expires_wall_us,"
            " invalidated_issue_count, invalidated_session_count, epoch_occurrence_id,"
            " created_commit_seq)"
            " VALUES ('http://127.0.0.1:4173', ?, ?, 5, 60000, 4, 60000, ?, NULL, 0, NULL,"
            " NULL, 0, NULL, 0, 0, ?, ?)",
            (epoch, observed_wall_us, observed_wall_us, occurrence_id, commit_seq),
        )

    paired_at = T0 + 30 * US
    epoch("epoch-1", 1, T0 + 10 * US, 1)
    occurrence(
        "issued-1", occurrence_kind="issued", issue_id="issue-1",
        predecessor_occurrence_id="epoch-1", observed_wall_us=T0 + 20 * US,
        expires_wall_us=T0 + 120 * US, rate_window_id="issued-1",
        rate_window_started_wall_us=T0 + 20 * US,
        rate_window_expires_wall_us=T0 + 80 * US, created_commit_seq=2,
    )
    occurrence(
        "consumed-1", occurrence_kind="consumed", issue_id="issue-1",
        session_id="pair-session-test-1", predecessor_occurrence_id="issued-1",
        observed_wall_us=paired_at, expires_wall_us=paired_at + 900 * US,
        created_commit_seq=3,
    )
    epoch("epoch-2", 2, T0 + 600 * US, 4)
    occurrence(
        "invalidated-1", occurrence_kind="restart_invalidated", epoch=2,
        session_id="pair-session-test-1", predecessor_occurrence_id="consumed-1",
        observed_wall_us=T0 + 600 * US, reason="process_restart", created_commit_seq=5,
    )
    conn.commit()
    conn.close()


def test_pairing_windows_reconstruct_from_the_real_ddl(tmp_path: Path) -> None:
    session_state = tmp_path / "cockpit-state"
    _build_pairing_catalog(session_state / "live-follow" / "pairing")
    windows, notes = read_paired_windows(session_state)
    assert notes == []
    assert len(windows) == 1
    window = windows[0]
    assert window.session_id == "pair-session-test-1"
    assert window.established_wall_us == T0 + 30 * US
    assert window.ended_kind == "restart_invalidated"
    assert window.ended_reason == "process_restart"


def test_empty_stores_yield_an_honest_empty_debrief(tmp_path: Path) -> None:
    """Paired, watched, held nothing: every section says so instead of inventing."""
    session_state = tmp_path / "cockpit-state"
    _build_pairing_catalog(session_state / "live-follow" / "pairing")
    (session_state / "live-follow" / "follow-state.json").write_text(
        json.dumps(
            {
                "contract": "joshi.core.live_follow_state",
                "schemaVersion": 2,
                "scenes": [
                    {
                        "sceneId": "scene-live-1",
                        "derivedAt": _iso(T0 + 40 * US),
                        "subjectCount": "2",
                        "observationCount": "16",
                        "derivationVersion": "1",
                    }
                ],
            }
        )
    )
    catalog_dir = tmp_path / "keeper-catalog"
    CatalogBuilder(catalog_dir).close()

    inputs = read_inputs(session_state, catalog_dir)
    assert session_days(inputs) == [DAY]
    text = render_day_debrief(inputs, DAY, NOW)

    assert "paired at" in text and "pair-session-test-1" in text
    assert "restart_invalidated: process_restart" in text
    assert "live-follow advanced through 1 scene(s)" in text
    assert "no durable operator act marks attended time" in text
    assert "No coin was held this day" in text
    assert "no scene journal entries were recorded this day" in text
    assert "0 selection event(s) reconstructed" in text
    assert "reconstruction from durable records" in text
    # nothing invented: no coin figures appear anywhere
    assert "SOL" not in text.split("## 2.")[1].split("## 3.")[0]


def test_a_missing_catalog_is_stated_not_guessed(tmp_path: Path) -> None:
    session_state = tmp_path / "cockpit-state"
    _build_pairing_catalog(session_state / "live-follow" / "pairing")
    inputs = read_inputs(session_state, tmp_path / "no-such-catalog")
    text = render_day_debrief(inputs, DAY, NOW)
    assert "cannot be reconstructed" in text


# --- writing: never clobber her words -------------------------------------------------


def test_written_artifact_refreshes_but_handwritten_content_is_never_overwritten(
    tmp_path: Path,
) -> None:
    out = tmp_path / "s2"
    path1, action1 = write_day_debrief(out, DAY, "first rendering\n")
    assert action1 == "written"
    assert path1.name == f"{DAY}-session.md"

    # a regenerated debrief refreshes its own file in place
    path2, action2 = write_day_debrief(out, DAY, "second rendering\n")
    assert (path2, action2) == (path1, "refreshed")
    assert "second rendering" in path1.read_text()

    # she edits the file by hand: from now on it is hers
    hand = path1.read_text().replace("second rendering", "second rendering, and my note")
    path1.write_text(hand)
    path3, action3 = write_day_debrief(out, DAY, "third rendering\n")
    assert path3 != path1
    assert path3.name == f"{DAY}-session-debrief.md"
    assert action3 == "written"
    assert path1.read_text() == hand  # untouched, byte for byte

    # a purely hand-written runbook file is likewise refused
    hand_only = out / "2027-01-16-session.md"
    hand_only.write_text("# my live notes\nrow 8: hands were fine today\n")
    path4, _ = write_day_debrief(out, "2027-01-16", "generated\n")
    assert path4 != hand_only
    assert hand_only.read_text().startswith("# my live notes")


def test_every_candidate_name_handwritten_refuses(tmp_path: Path) -> None:
    out = tmp_path / "s2"
    out.mkdir()
    (out / f"{DAY}-session.md").write_text("hers\n")
    (out / f"{DAY}-session-debrief.md").write_text("also hers\n")
    for i in range(2, 10):
        (out / f"{DAY}-session-debrief-{i}.md").write_text("hers too\n")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        write_day_debrief(out, DAY, "generated\n")
