from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from itertools import pairwise
from typing import Any

import pyarrow as pa

from .contracts import CHART_FEATURE_SCHEMA, CHART_FEATURE_VERSION, DESCRIPTIVE_CLAIM_SCOPE
from .errors import ManifestError

# This text is the versioned transform/configuration preimage. The implementation deliberately uses
# exact Python integers for every atom ratio and ppm rounding; no atom crosses a float boundary.
DESCRIPTIVE_CHART_SQL = """joshi.analysis.descriptive-chart-shape/exact-rational-v3
group=(scene_id,episode_id); order=sample_index;
ratio=(price_quote_atoms/price_base_atoms);
ppm=round_half_away_from_zero(exact_rational*1000000);
gaps=explicit; output_order=(scene_id,episode_id)
"""

_U64_MAX = 18_446_744_073_709_551_615
_I64_MIN = -(2**63)
_I64_MAX = 2**63 - 1


def _atoms(value: Any, field: str) -> int:
    if not isinstance(value, Decimal) or value != value.to_integral_value():
        raise ManifestError(f"{field} must be an exact integral decimal")
    integer = int(value)
    if not 0 <= integer <= _U64_MAX:
        raise ManifestError(f"{field} exceeds the frozen u64 atom boundary")
    return integer


def _ppm(numerator: int, denominator: int, field: str) -> int:
    if denominator <= 0:
        raise ManifestError(f"{field} has a non-positive exact denominator")
    sign = -1 if numerator < 0 else 1
    quotient, remainder = divmod(abs(numerator) * 1_000_000, denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    result = sign * quotient
    if not _I64_MIN <= result <= _I64_MAX:
        raise ManifestError(f"{field} exceeds the signed ppm output boundary")
    return result


def _compare_ratio(left: tuple[int, int], right: tuple[int, int]) -> int:
    left_cross = left[0] * right[1]
    right_cross = right[0] * left[1]
    return (left_cross > right_cross) - (left_cross < right_cross)


def _require_stable(group: list[dict[str, Any]], field: str) -> Any:
    values = {row[field] for row in group}
    if len(values) != 1:
        raise ManifestError(f"chart series changes {field}")
    return values.pop()


def _shape_row(group: list[dict[str, Any]]) -> dict[str, Any] | None:
    ordered = sorted(group, key=lambda row: row["sample_index"])
    if [row["sample_index"] for row in ordered] != list(range(len(ordered))):
        raise ManifestError("chart series sample indexes are not contiguous")
    if any(row["expected_sample_count"] != len(ordered) for row in ordered):
        raise ManifestError("chart series expected sample count differs")
    if any(
        not (
            row["event_time"]
            <= row["observed_at"]
            <= row["available_at"]
            <= row["decision_available_at"]
        )
        for row in ordered
    ):
        raise ManifestError("chart sample clocks are not ordered")
    if [row["event_time"] for row in ordered] != sorted(row["event_time"] for row in ordered):
        raise ManifestError("chart sample event times are not ordered")
    for field in (
        "scene_id",
        "decision_id",
        "episode_id",
        "candidate_id",
        "territory_id",
        "base_asset_id",
        "quote_asset_id",
        "coverage_scope_id",
        "coverage_window_id",
    ):
        _require_stable(ordered, field)
    for row in ordered:
        measured = (
            row["price_base_atoms"],
            row["price_quote_atoms"],
            row["buy_volume_base_atoms"],
            row["sell_volume_base_atoms"],
        )
        if row["coverage_status"] == "observed":
            if (
                any(value is None for value in measured)
                or row["coverage_gap_id"] is not None
                or row["source_assertion_id"] is None
                or row["source_observation_id"] is None
                or row["position_state"] not in {"exposed", "flat_watch", "runner"}
            ):
                raise ManifestError("chart feature/gap inputs are not separated exactly")
            for field, value in zip(
                (
                    "price_base_atoms",
                    "price_quote_atoms",
                    "buy_volume_base_atoms",
                    "sell_volume_base_atoms",
                ),
                measured,
                strict=True,
            ):
                _atoms(value, field)
        elif row["coverage_status"] == "gap":
            if (
                any(value is not None for value in measured)
                or row["position_state"] != "unknown"
                or row["coverage_gap_id"] is None
                or row["source_assertion_id"] is not None
                or row["source_observation_id"] is not None
            ):
                raise ManifestError("chart feature/gap inputs are not separated exactly")
        else:
            raise ManifestError("chart feature/gap inputs are not separated exactly")
    observed = [row for row in ordered if row["coverage_status"] == "observed"]
    if not observed:
        return None

    ratios: list[tuple[int, int]] = []
    for row in observed:
        base = _atoms(row["price_base_atoms"], "price_base_atoms")
        quote = _atoms(row["price_quote_atoms"], "price_quote_atoms")
        if base == 0 or quote == 0:
            raise ManifestError("observed exact price ratio must be positive")
        ratios.append((quote, base))

    start_quote, start_base = ratios[0]
    end_quote, end_base = ratios[-1]
    signed_change = _ppm(
        end_quote * start_base - start_quote * end_base,
        end_base * start_quote,
        "signed_change_ppm",
    )
    minimum = ratios[0]
    maximum = ratios[0]
    running_peak = ratios[0]
    max_drawdown = 0
    directions: list[int] = []
    symbols: list[str] = []
    previous = ratios[0]
    for index, ratio in enumerate(ratios):
        if _compare_ratio(ratio, minimum) < 0:
            minimum = ratio
        if _compare_ratio(ratio, maximum) > 0:
            maximum = ratio
        if _compare_ratio(ratio, running_peak) > 0:
            running_peak = ratio
        peak_quote, peak_base = running_peak
        quote, base = ratio
        drawdown = _ppm(
            peak_quote * base - quote * peak_base,
            base * peak_quote,
            "max_drawdown_ppm",
        )
        max_drawdown = max(max_drawdown, drawdown)
        if index == 0:
            continue
        direction = _compare_ratio(ratio, previous)
        directions.append(direction)
        symbols.append("+" if direction > 0 else "-" if direction < 0 else "0")
        previous = ratio
    nonzero = [direction for direction in directions if direction]
    direction_changes = sum(left != right for left, right in pairwise(nonzero))
    minimum_quote, minimum_base = minimum
    maximum_quote, maximum_base = maximum
    range_ppm = _ppm(
        (maximum_quote * minimum_base - minimum_quote * maximum_base) * start_base,
        maximum_base * minimum_base * start_quote,
        "range_ppm",
    )

    return {
        "scene_id": _require_stable(ordered, "scene_id"),
        "decision_id": _require_stable(ordered, "decision_id"),
        "episode_id": _require_stable(ordered, "episode_id"),
        "candidate_id": _require_stable(ordered, "candidate_id"),
        "territory_id": _require_stable(ordered, "territory_id"),
        "base_asset_id": _require_stable(ordered, "base_asset_id"),
        "quote_asset_id": _require_stable(ordered, "quote_asset_id"),
        "decision_available_at": max(row["decision_available_at"] for row in ordered),
        "first_event_time": min(row["event_time"] for row in observed),
        "last_event_time": max(row["event_time"] for row in observed),
        "expected_samples": len(ordered),
        "observed_samples": len(observed),
        "gap_samples": len(ordered) - len(observed),
        "coverage_ratio_ppm": len(observed) * 1_000_000 // len(ordered),
        "start_price_base_atoms": Decimal(start_base),
        "start_price_quote_atoms": Decimal(start_quote),
        "end_price_base_atoms": Decimal(end_base),
        "end_price_quote_atoms": Decimal(end_quote),
        "signed_change_ppm": signed_change,
        "range_ppm": range_ppm,
        "max_drawdown_ppm": max_drawdown,
        "direction_changes": direction_changes,
        "path_signature": "".join(symbols),
        "exposed_samples": sum(row["position_state"] == "exposed" for row in observed),
        "flat_watch_samples": sum(row["position_state"] == "flat_watch" for row in observed),
        "runner_samples": sum(row["position_state"] == "runner" for row in observed),
        "feature_version": CHART_FEATURE_VERSION,
        "claim_scope": DESCRIPTIVE_CLAIM_SCOPE,
    }


def descriptive_chart_features(chart_samples: pa.Table) -> pa.Table:
    if "price_base_atoms" not in chart_samples.column_names:
        raise ManifestError("chart relation does not have the frozen snapshot schema")
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in chart_samples.to_pylist():
        groups[(row["scene_id"], row["episode_id"])].append(row)
    rows = [result for key in sorted(groups) if (result := _shape_row(groups[key])) is not None]
    return pa.Table.from_pylist(rows, schema=CHART_FEATURE_SCHEMA)
