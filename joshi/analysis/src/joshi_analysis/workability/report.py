"""Render the census's results markdown from the run artifacts. Offline, read-only."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import STUDY_VERSION
from .budget import Ledger
from .interaction import median


def _fmt(value: object, digits: int = 3) -> str:
    if value is None:
        return "absent"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def _load_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open() if line.strip()]


def render(root: Path) -> str:
    manifest = _load(root / "manifest.json") or {}
    interaction = _load(root / "interaction.json") or {}
    replay = _load(root / "replay.json") or {}
    callouts = _load(root / "callouts.json") or {}
    measures = _load_lines(root / "measurements.jsonl")
    callout_measures = _load_lines(root / "callout_measures.jsonl")
    ledger = Ledger(root, budget=10**9)
    lines: list[str] = []
    add = lines.append
    add(f"# workability census — results ({STUDY_VERSION})")
    add("")
    add(f"Rendered {dt.datetime.now(dt.UTC).isoformat(timespec='seconds')} from `{root}`.")
    add("Registration: `analysis/src/joshi_analysis/workability/STUDY.md` (design written")
    add("before the run). Every tape is a retrospective backfill (`retrospective_none`):")
    add("EVERY number below is an oracle-window study number, never a live-executable claim.")
    add("")
    add("## Sample and spend")
    add("")
    census_ms = manifest.get("census_instant_ms")
    if census_ms:
        add(f"- census instant: {dt.datetime.fromtimestamp(census_ms / 1000, tz=dt.UTC)}")
    add(f"- sampled mints: {manifest.get('n_sampled', 'absent')} (seed {manifest.get('seed')})")
    verdicts: dict[str, int] = {}
    for record in measures:
        verdicts[record.get("verdict", "?")] = verdicts.get(record.get("verdict", "?"), 0) + 1
    add(f"- measurement verdicts: {json.dumps(verdicts)}")
    add(f"- requests spent: {ledger.spent()}, by phase {json.dumps(ledger.by_phase())}")
    add("")
    strata = manifest.get("strata", [])
    populated = [s for s in strata if s.get("available")]
    add(f"### Strata ({len(populated)} of {len(strata)} cells populated)")
    add("")
    add("| age | mcap | graduated | available | drawn | shortfall |")
    add("|-----|------|-----------|-----------|-------|-----------|")
    for cell in strata:
        if not cell.get("available") and not cell.get("drawn"):
            continue
        add(
            f"| {cell['age']} | {cell['mcap']} | {cell['graduated']} | {cell['available']} "
            f"| {cell['drawn']} | {cell['shortfall']} |"
        )
    add("")
    add("## The interaction test")
    add("")
    add(str(interaction.get("multiplicity_statement", "interaction phase not run")))
    add("")
    for cell in interaction.get("primary", []):
        add(
            f"- PRIMARY {cell['statistic']} -> {cell['outcome']}: rho={_fmt(cell['rho'])}, "
            f"p={_fmt(cell['p_permutation'], 5)}, n={cell['n']}"
        )
    add("")
    survivors = interaction.get("bonferroni_survivors", [])
    threshold = interaction.get("bonferroni_threshold")
    add(
        f"Naive Bonferroni threshold {_fmt(threshold, 5)}: {len(survivors)} of "
        f"{interaction.get('n_tests', 0)} cells below it (exploratory even so)."
    )
    for cell in survivors:
        add(
            f"- {cell['statistic']} -> {cell['outcome']}: rho={_fmt(cell['rho'])}, "
            f"p={_fmt(cell['p_permutation'], 6)}, n={cell['n']}"
        )
    add("")
    add("## The harvest arm (grid family, pump_amm-only)")
    add("")
    if replay.get("verdict") == "NO_ELIGIBLE_COINS":
        add(str(replay.get("statement")))
    elif replay:
        arms = replay.get("arms", {})
        medians = replay.get("median_held_out_net_bps", {})
        add(f"- eligible coins: {replay.get('n_eligible')} of {replay.get('n_measured')}")
        add(
            f"- top decile by S4: n={arms.get('top_decile_by_S4', {}).get('n')}, held-out "
            f"nets read {arms.get('top_decile_by_S4', {}).get('with_net')}, median "
            f"{_fmt(medians.get('top_decile'), 1)} bps"
        )
        add(
            f"- random control: n={arms.get('random_control', {}).get('n')}, held-out nets "
            f"read {arms.get('random_control', {}).get('with_net')}, median "
            f"{_fmt(medians.get('control'), 1)} bps"
        )
        add(f"- {replay.get('oracle_note')}")
    else:
        add("replay phase not run")
    add("")
    add("## The callout arm")
    add("")
    add(
        f"- callouts within {callouts.get('window_hours', '?')}h: {callouts.get('n', 0)}; "
        f"windows measured: {len(callout_measures)}"
    )
    covered = [m for m in callout_measures if m.get("entry_covered")]
    add(
        f"- entry-covered (tape reaches the callout instant): {len(covered)} of "
        f"{len(callout_measures)}; the rest are tail-only and excluded from the dip numbers"
    )
    if covered:
        dipped = [m for m in covered if m.get("dipped_below_anchor")]
        add(f"- dipped below the anchor: {len(dipped)}/{len(covered)}")
        depths = [-m["dip_depth_pct"] for m in dipped]
        add(f"- median dip depth of dippers: {_fmt(median(depths), 1)}%")
        anchor_clears = sum(bool(m.get("clears_hurdle_from_anchor")) for m in covered)
        trough_clears = sum(bool(m.get("clears_hurdle_from_trough")) for m in covered)
        add(
            f"- clears its per-coin floor from the anchor: {anchor_clears}/{len(covered)}; "
            f"from the trough: {trough_clears}/{len(covered)}"
        )
    add(str(callouts.get("confound", "")))
    add("")
    add("Provider claims are provider-asserted throughout; occurrence clocks are occurrence")
    add("clocks; absent numbers are printed as absent, never as zero.")
    add("")
    return "\n".join(lines)
