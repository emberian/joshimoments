"""Assemble and render the whole measurement: census, outcomes, scores, power.

The rendering rule this module exists to enforce: a reader who skims must not be able to
take away a flattering number. Every score is printed next to the count of decisions it
rests on and the count of outcomes that were absent, the verdict sentence carries its own
caveat, and when nothing is measurable the report says that in those words rather than
printing a statistic computed on nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .events import ReconstructionCensus, SelectionEventV1, reconstruct_many
from .outcomes import EventOutcomeV1, ForwardPriceIndex, build_price_index, measure_all
from .power import PowerStatementV1, power_statement, render_power_statement
from .preregistration import (
    DEFAULT_FEE_FLOOR_BPS,
    HORIZONS_SECONDS,
    PREREGISTERED_ON,
    PREREGISTRATION_ID,
    PRIMARY_HORIZON_SECONDS,
)
from .score import SelectionScoreV1, score


@dataclass(frozen=True, slots=True)
class SelectionReportV1:
    schema: str
    preregistration_id: str
    preregistered_on: str
    catalogs: tuple[str, ...]
    censuses: tuple[ReconstructionCensus, ...]
    events: tuple[SelectionEventV1, ...]
    outcomes: dict[int, list[EventOutcomeV1]]
    scores: dict[int, SelectionScoreV1]
    power: PowerStatementV1
    price_index_mints: int
    price_index_observations: int

    def to_json_obj(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "preregistrationId": self.preregistration_id,
            "preregisteredOn": self.preregistered_on,
            "catalogs": list(self.catalogs),
            "reconstruction": [c.to_json_obj() for c in self.censuses],
            "events": [e.to_json_obj() for e in self.events],
            "priceIndex": {
                "mints": self.price_index_mints,
                "observations": self.price_index_observations,
            },
            "scores": {str(h): s.to_json_obj() for h, s in sorted(self.scores.items())},
            "power": self.power.to_json_obj(),
        }


def build_report(
    catalogs: Sequence[Path],
    horizons: Sequence[int] = HORIZONS_SECONDS,
    fee_floor_bps: int = DEFAULT_FEE_FLOOR_BPS,
    price_catalogs: Sequence[Path] | None = None,
) -> SelectionReportV1:
    """Reconstruct, measure, score and power-state, in that order.

    `price_catalogs` defaults to `catalogs`: forward prices are drawn from the same durable
    scene bytes. A wider set can be passed when later observation lives in another catalog.
    """
    paths = [Path(c) for c in catalogs]
    events, censuses = reconstruct_many(paths)
    index: ForwardPriceIndex = build_price_index(
        [Path(c) for c in (price_catalogs if price_catalogs is not None else paths)]
    )
    outcomes = measure_all(events, index, horizons)
    scores = {h: score(outcomes[h], h, fee_floor_bps) for h in horizons}
    primary = scores.get(PRIMARY_HORIZON_SECONDS)
    n_scored_primary = primary.n_scored if primary is not None else 0
    typical_k = 8
    if events:
        sizes = sorted(e.choice_set_size for e in events)
        typical_k = max(2, sizes[len(sizes) // 2])
    return SelectionReportV1(
        schema="joshi.selection.report.v1",
        preregistration_id=PREREGISTRATION_ID,
        preregistered_on=PREREGISTERED_ON,
        catalogs=tuple(str(p) for p in paths),
        censuses=tuple(censuses),
        events=tuple(events),
        outcomes=outcomes,
        scores=scores,
        power=power_statement(n_scored_now=n_scored_primary, k=typical_k),
        price_index_mints=len(index.mints),
        price_index_observations=sum(index.observation_count(m) for m in index.mints),
    )


def render_report(report: SelectionReportV1) -> str:
    out: list[str] = []
    out.append("JOSHI OPERATOR SELECTION MEASUREMENT")
    out.append("=" * 72)
    out.append(f"pre-registration: {report.preregistration_id} (frozen {report.preregistered_on})")
    out.append("The scoring rule was fixed before this ran. See selection/preregistration.py.")
    out.append("")

    out.append("1. RECONSTRUCTION -- what the catalogs contained")
    out.append("-" * 72)
    total_cmds = sum(c.commands_total for c in report.censuses)
    total_scenes = sum(c.scenes_total for c in report.censuses)
    out.append(f"  catalogs read (read-only): {len(report.catalogs)}")
    for path in report.catalogs:
        out.append(f"    {path}")
    out.append(f"  operator acts found:       {total_cmds}")
    out.append(f"  scenes found:              {total_scenes}")
    out.append(f"  selection events rebuilt:  {len(report.events)}")
    merged: dict[str, int] = {}
    for census in report.censuses:
        for reason, n in census.exclusions.items():
            merged[reason] = merged.get(reason, 0) + n
    if merged:
        out.append("  acts NOT scored, and why (nothing is dropped silently):")
        for reason, n in sorted(merged.items()):
            out.append(f"    {n:>5}  {reason}")
    reconciles = all(c.reconciles() for c in report.censuses)
    out.append(f"  act census reconciles:     {reconciles}")
    out.append("")

    if report.events:
        out.append("  per event:")
        for e in report.events:
            out.append(
                f"    {e.event_id}  scene={e.scene_id}"
            )
            out.append(
                f"      choice set: {e.choice_set_size} ({e.choice_set_kind}), "
                f"chosen {len(e.chosen)}, passed {len(e.passed)}"
            )
            out.append(
                f"      scene digest {e.view_sha256[:16]}...  mode={e.scene_mode} "
                f"knowledge cutoff commit {e.knowledge_cutoff_commit_seq}, "
                f"captured at commit {e.captured_commit_seq}"
            )
            out.append(
                f"      decision at commit {e.decision_commit_seq}; scene was "
                f"{e.staleness_us / 1e6:.0f}s stale when marked"
            )
            out.append(
                f"      view blob vs choice-set table: {e.blob_agreement}"
                + (f"  flags={list(e.integrity_flags)}" if e.integrity_flags else "")
            )
            out.append(f"      chosen: {', '.join(c.subject_key for c in e.chosen)}")
            out.append(f"      passed: {', '.join(c.subject_key for c in e.passed)}")
        out.append("")

    out.append("2. OUTCOMES -- forward moves, measured only on data later than the act")
    out.append("-" * 72)
    out.append(
        f"  forward price index: {report.price_index_observations} priced observations "
        f"across {report.price_index_mints} mints, from retained scene bytes"
    )
    out.append("")
    for horizon in sorted(report.scores):
        sc = report.scores[horizon]
        mark = "  <-- headline" if horizon == PRIMARY_HORIZON_SECONDS else ""
        out.append(f"  horizon {horizon}s{mark}")
        out.append(f"    events: {sc.n_events}   scored: {sc.n_scored}")
        if sc.absence_reasons:
            for reason, n in sorted(sc.absence_reasons.items()):
                out.append(f"      absent: {n:>4}  {reason}")
        if sc.n_scored:
            out.append(
                f"    S1 mean normalised rank {sc.s1_mean_normalised_rank:.4f} "
                f"(null 0.5000, permutation p={sc.s1_permutation_p:.4f})"
            )
            out.append(
                f"    S2 within-scene excess  {sc.s2_mean_excess_log:+.4f} log "
                f"[{sc.s2_ci[0]:+.4f}, {sc.s2_ci[1]:+.4f}]  "
                f"sign {sc.s2_sign_positives}/{sc.s2_sign_n} p={sc.s2_sign_p:.4f}"
            )
            out.append(
                f"    S3 net of {sc.fee_floor_bps} bps floor {sc.s3_mean_net_log:+.4f} log "
                f"[{sc.s3_ci[0]:+.4f}, {sc.s3_ci[1]:+.4f}]  "
                f"sign {sc.s3_sign_positives}/{sc.s3_sign_n} p={sc.s3_sign_p:.4f}"
            )
        out.append(f"    VERDICT: {sc.verdict}")
        for line in _wrap(sc.verdict_note, 68):
            out.append(f"      {line}")
        out.append("")

    out.append("3. POWER -- how much sitting-in-it is required")
    out.append("-" * 72)
    for line in render_power_statement(report.power).splitlines():
        out.append(f"  {line}")
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        if current and sum(len(w) + 1 for w in current) + len(word) > width:
            lines.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines
