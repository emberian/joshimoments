"""Fixture-only domain counterexamples for the Wave 6 ``N01/W6-K`` gate.

The battery closes seven deliberately small counterexamples that the generic signed-flow,
protocol-arithmetic, and structural batteries do not express.  Its inputs are generated in this
module and its results are useful only as deterministic fixture checks.  Nothing here resolves a
source, identifies a person or mechanism, values a portfolio, or authorizes an action.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ..canonical import canonical_json_bytes, iso_utc, qualified_sha256_bytes
from ..errors import ManifestError

DOMAIN_BATTERY_SCHEMA = "joshi.analysis.wave6-domain-known-truth/v1"
DOMAIN_BATTERY_AUTHORITY = (
    "fixture_domain_counterexamples_only_no_market_identity_causal_policy_or_economic_claim"
)


class DomainAdversaryKind(StrEnum):
    """Frozen domain counterexamples still missing from the first three N01 batteries."""

    VENUE_PROFILE_TRANSFER = "venue_profile_transfer"
    PLATFORM_WIDE_BURST = "platform_wide_burst"
    SAME_CHART_DIFFERENT_MECHANISM = "same_chart_different_mechanism"
    OPERATOR_LABEL_INDUCTION = "operator_label_induction"
    RUNNER_LIQUIDATION_DIVERGENCE = "runner_liquidation_divergence"
    HOUSEHOLD_SELF_FLOW = "household_self_flow"
    FROZEN_FUTURE_EXIT_REENTRY = "frozen_future_exit_reentry"


class DomainValueKind(StrEnum):
    """Closed wire carriers for generated domain outputs."""

    DECIMAL_INTEGER = "decimal_integer"
    IDENTIFIER = "identifier"
    SHA256 = "sha256"
    DISPOSITION = "disposition"


def _stable(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ManifestError(f"{field} must be a bounded, unpadded stable string")
    return value


def _decimal(value: Any, field: str, *, signed: bool = False) -> int:
    if not isinstance(value, str) or not value.isascii():
        raise ManifestError(f"{field} must be a canonical decimal string")
    digits = value.removeprefix("-") if signed else value
    if (
        not digits
        or not digits.isdigit()
        or (len(digits) > 1 and digits.startswith("0"))
        or (not signed and value.startswith("-"))
        or value == "-0"
    ):
        raise ManifestError(f"{field} must be a canonical decimal string")
    parsed = int(value)
    if not signed and parsed < 0:
        raise ManifestError(f"{field} must be nonnegative")
    if parsed < -(2**127) or parsed > 2**128 - 1:
        raise ManifestError(f"{field} exceeds the fixture integer carrier")
    return parsed


def _digest(value: Any) -> str:
    return qualified_sha256_bytes(canonical_json_bytes(value))


def _qualified_digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ManifestError(f"{field} must be sha256:<64 lowercase hex>")
    return value


def _ceil_div(numerator: int, denominator: int) -> int:
    if numerator < 0 or denominator <= 0:
        raise ManifestError("fixture division requires nonnegative/positive operands")
    return (numerator + denominator - 1) // denominator


def derive_exit_reentry_at_cut(
    rows: tuple[dict[str, Any], ...],
    cut_time: datetime,
    cut_commit: int,
) -> tuple[int, str, str]:
    """Resolve a fixture inventory state after gating solely on availability and commit.

    Semantic payload is checked only for eligible rows, so a malformed future re-entry cannot
    poison an earlier cut. The result remains caller-fed fixture semantics, not store authority.
    """

    if cut_time.tzinfo is None or cut_time.utcoffset() is None:
        raise ManifestError("exit/re-entry cut time must be timezone-aware")
    if isinstance(cut_commit, bool) or not isinstance(cut_commit, int) or cut_commit < 0:
        raise ManifestError("exit/re-entry cut commit must be a nonnegative integer")
    eligible: list[dict[str, Any]] = []
    for row in rows:
        available_at = row.get("available_at")
        commit_seq = row.get("commit_seq")
        if (
            not isinstance(available_at, datetime)
            or available_at.tzinfo is None
            or available_at.utcoffset() is None
        ):
            raise ManifestError("exit/re-entry availability must be timezone-aware")
        if isinstance(commit_seq, bool) or not isinstance(commit_seq, int) or commit_seq < 0:
            raise ManifestError("exit/re-entry commit must be a nonnegative integer")
        if available_at.astimezone(UTC) <= cut_time.astimezone(UTC) and commit_seq <= cut_commit:
            eligible.append(row)
    if not eligible:
        raise ManifestError("exit/re-entry cut has no eligible state")

    material: list[dict[str, str]] = []
    for row in eligible:
        if set(row) != {
            "event_id",
            "available_at",
            "commit_seq",
            "inventory_atoms",
            "inventory_epoch",
        }:
            raise ManifestError("exit/re-entry row fields differ from the fixture contract")
        event_id = _stable(row["event_id"], "exit/re-entry event ID")
        inventory_epoch = _stable(row["inventory_epoch"], "exit/re-entry inventory epoch")
        inventory_atoms = row["inventory_atoms"]
        if (
            isinstance(inventory_atoms, bool)
            or not isinstance(inventory_atoms, int)
            or inventory_atoms < 0
        ):
            raise ManifestError("exit/re-entry inventory must be exact nonnegative atoms")
        material.append(
            {
                "event_id": event_id,
                "available_at": iso_utc(row["available_at"]),
                "commit_seq": str(row["commit_seq"]),
                "inventory_atoms": str(inventory_atoms),
                "inventory_epoch": inventory_epoch,
            }
        )
    material.sort(key=lambda row: (row["available_at"], int(row["commit_seq"]), row["event_id"]))
    latest = material[-1]
    return int(latest["inventory_atoms"]), latest["inventory_epoch"], _digest(material)


@dataclass(frozen=True, slots=True)
class DomainOutput:
    """One typed output recovered from a generated domain counterexample."""

    name: str
    kind: DomainValueKind
    value: str

    def __post_init__(self) -> None:
        _stable(self.name, "domain output name")
        if self.kind == DomainValueKind.DECIMAL_INTEGER:
            _decimal(self.value, "domain decimal output", signed=True)
        elif self.kind in {DomainValueKind.IDENTIFIER, DomainValueKind.DISPOSITION}:
            _stable(self.value, "domain symbolic output")
        elif self.kind == DomainValueKind.SHA256:
            _qualified_digest(self.value, "domain digest output")
        else:  # pragma: no cover - defensive against an unsafe enum bypass
            raise ManifestError("unknown domain output carrier")


def _output_material(output: DomainOutput) -> dict[str, str]:
    return {"kind": output.kind.value, "name": output.name, "value": output.value}


def _case_material(case: DomainTruthCase) -> dict[str, Any]:
    return {
        "schema_id": DOMAIN_BATTERY_SCHEMA,
        "case_id": case.case_id,
        "adversary": case.adversary.value,
        "fixture_ids": list(case.fixture_ids),
        "exact_outputs": [_output_material(output) for output in case.exact_outputs],
        "negative_control_id": case.negative_control_id,
        "falsifier": case.falsifier,
        "authority": DOMAIN_BATTERY_AUTHORITY,
    }


@dataclass(frozen=True, slots=True)
class DomainTruthCase:
    """One generated domain truth with a complete typed output closure."""

    case_id: str
    adversary: DomainAdversaryKind
    fixture_ids: tuple[str, ...]
    exact_outputs: tuple[DomainOutput, ...]
    negative_control_id: str
    falsifier: str
    truth_digest: str

    def __post_init__(self) -> None:
        _stable(self.case_id, "domain case_id")
        _stable(self.negative_control_id, "domain negative control")
        _stable(self.falsifier, "domain falsifier")
        if self.fixture_ids != tuple(sorted(set(self.fixture_ids))) or not self.fixture_ids:
            raise ManifestError("domain fixture IDs must be sorted, unique, and nonempty")
        names = tuple(output.name for output in self.exact_outputs)
        if names != tuple(sorted(set(names))) or not names:
            raise ManifestError("domain outputs must be sorted, unique, and nonempty")
        if self.truth_digest != _digest(_case_material(self)):
            raise ManifestError("domain truth digest mismatch")

    @classmethod
    def build(
        cls,
        case_id: str,
        adversary: DomainAdversaryKind,
        fixture_ids: tuple[str, ...],
        exact_outputs: tuple[DomainOutput, ...],
        negative_control_id: str,
        falsifier: str,
    ) -> DomainTruthCase:
        provisional = cls.__new__(cls)
        for field, value in (
            ("case_id", case_id),
            ("adversary", adversary),
            ("fixture_ids", fixture_ids),
            ("exact_outputs", exact_outputs),
            ("negative_control_id", negative_control_id),
            ("falsifier", falsifier),
        ):
            object.__setattr__(provisional, field, value)
        object.__setattr__(provisional, "truth_digest", "sha256:" + "0" * 64)
        return cls(
            case_id,
            adversary,
            fixture_ids,
            exact_outputs,
            negative_control_id,
            falsifier,
            _digest(_case_material(provisional)),
        )


@dataclass(frozen=True, slots=True)
class DomainKnownTruthBattery:
    """Exact seven-case domain N01 battery."""

    suite_id: str
    cases: tuple[DomainTruthCase, ...]
    authority: str = DOMAIN_BATTERY_AUTHORITY

    def __post_init__(self) -> None:
        _stable(self.suite_id, "domain suite_id")
        ids = tuple(case.case_id for case in self.cases)
        if (
            ids != tuple(sorted(set(ids)))
            or len(self.cases) != len(DomainAdversaryKind)
            or {case.adversary for case in self.cases} != set(DomainAdversaryKind)
            or self.authority != DOMAIN_BATTERY_AUTHORITY
        ):
            raise ManifestError("domain suite must close every adversary exactly once")

    @property
    def suite_digest(self) -> str:
        return _digest(
            {
                "schema_id": DOMAIN_BATTERY_SCHEMA,
                "suite_id": self.suite_id,
                "truth_digests": [case.truth_digest for case in self.cases],
                "authority": self.authority,
            }
        )


def _candidate_material(result: DomainCandidateResult) -> dict[str, Any]:
    return {
        "schema_id": DOMAIN_BATTERY_SCHEMA,
        "case_id": result.case_id,
        "truth_digest": result.truth_digest,
        "exact_outputs": [_output_material(output) for output in result.exact_outputs],
        "authority": result.authority,
    }


@dataclass(frozen=True, slots=True)
class DomainCandidateResult:
    """One candidate's exact result for a domain fixture case."""

    case_id: str
    truth_digest: str
    exact_outputs: tuple[DomainOutput, ...]
    authority: str
    result_digest: str

    @classmethod
    def build(
        cls,
        case: DomainTruthCase,
        *,
        exact_outputs: tuple[DomainOutput, ...] | None = None,
    ) -> DomainCandidateResult:
        outputs = case.exact_outputs if exact_outputs is None else exact_outputs
        provisional = cls(
            case.case_id,
            case.truth_digest,
            outputs,
            DOMAIN_BATTERY_AUTHORITY,
            "sha256:" + "0" * 64,
        )
        return cls(
            case.case_id,
            case.truth_digest,
            outputs,
            DOMAIN_BATTERY_AUTHORITY,
            _digest(_candidate_material(provisional)),
        )


def _evaluation_material(evaluation: DomainBatteryEvaluation) -> dict[str, Any]:
    return {
        "schema_id": DOMAIN_BATTERY_SCHEMA,
        "suite_id": evaluation.suite_id,
        "suite_digest": evaluation.suite_digest,
        "candidate_id": evaluation.candidate_id,
        "passed_case_ids": list(evaluation.passed_case_ids),
        "result_digests": list(evaluation.result_digests),
        "authority": evaluation.authority,
    }


@dataclass(frozen=True, slots=True)
class DomainBatteryEvaluation:
    """Exact all-cases evaluation at fixture-only authority."""

    suite_id: str
    suite_digest: str
    candidate_id: str
    passed_case_ids: tuple[str, ...]
    result_digests: tuple[str, ...]
    evaluation_digest: str
    authority: str = DOMAIN_BATTERY_AUTHORITY

    def __post_init__(self) -> None:
        _stable(self.suite_id, "domain evaluation suite_id")
        _stable(self.candidate_id, "domain evaluation candidate_id")
        if self.passed_case_ids != tuple(sorted(set(self.passed_case_ids))) or not (
            self.passed_case_ids
        ):
            raise ManifestError("domain passed case IDs must be sorted, unique, and nonempty")
        if len(self.result_digests) != len(self.passed_case_ids):
            raise ManifestError("domain evaluation must bind one result digest per case")
        for case_id in self.passed_case_ids:
            _stable(case_id, "domain passed case ID")
        for digest in (self.suite_digest, self.evaluation_digest, *self.result_digests):
            _qualified_digest(digest, "domain evaluation digest")
        if self.authority != DOMAIN_BATTERY_AUTHORITY:
            raise ManifestError("domain evaluation widened its fixture-only authority")
        if self.evaluation_digest != _digest(_evaluation_material(self)):
            raise ManifestError("domain evaluation self-digest mismatch")

    def as_dict(self) -> dict[str, Any]:
        """Return the exact, not-yet-registered evaluation artifact fields."""

        return {
            "suite_id": self.suite_id,
            "suite_digest": self.suite_digest,
            "candidate_id": self.candidate_id,
            "passed_case_ids": list(self.passed_case_ids),
            "result_digests": list(self.result_digests),
            "evaluation_digest": self.evaluation_digest,
            "authority": self.authority,
        }

    def exact_bytes(self) -> bytes:
        """Serialize canonical fixture bytes without conferring registry/store authority."""

        return canonical_json_bytes(self.as_dict(), newline=True)


def validate_domain_candidate_result(
    case: DomainTruthCase,
    result: DomainCandidateResult,
) -> None:
    """Require exact typed outputs, truth identity, authority, and result digest."""

    for output in result.exact_outputs:
        output.__post_init__()
    if (
        result.case_id != case.case_id
        or result.truth_digest != case.truth_digest
        or result.exact_outputs != case.exact_outputs
        or result.authority != DOMAIN_BATTERY_AUTHORITY
    ):
        raise ManifestError("domain candidate differs from exact generated truth")
    if result.result_digest != _digest(_candidate_material(result)):
        raise ManifestError("domain candidate result digest mismatch")


def evaluate_domain_candidate(
    battery: DomainKnownTruthBattery,
    candidate_id: str,
    results: tuple[DomainCandidateResult, ...],
) -> DomainBatteryEvaluation:
    """Require exactly one passing result for every domain adversary."""

    _stable(candidate_id, "domain candidate_id")
    by_id = {result.case_id: result for result in results}
    if len(by_id) != len(results) or set(by_id) != {case.case_id for case in battery.cases}:
        raise ManifestError("domain candidate must report every case exactly once")
    for case in battery.cases:
        validate_domain_candidate_result(case, by_id[case.case_id])
    passed = tuple(case.case_id for case in battery.cases)
    result_digests = tuple(by_id[case_id].result_digest for case_id in passed)
    provisional = DomainBatteryEvaluation.__new__(DomainBatteryEvaluation)
    for field, value in (
        ("suite_id", battery.suite_id),
        ("suite_digest", battery.suite_digest),
        ("candidate_id", candidate_id),
        ("passed_case_ids", passed),
        ("result_digests", result_digests),
        ("authority", DOMAIN_BATTERY_AUTHORITY),
    ):
        object.__setattr__(provisional, field, value)
    object.__setattr__(provisional, "evaluation_digest", "sha256:" + "0" * 64)
    return DomainBatteryEvaluation(
        battery.suite_id,
        battery.suite_digest,
        candidate_id,
        passed,
        result_digests,
        _digest(_evaluation_material(provisional)),
    )


def _outputs(values: dict[str, tuple[DomainValueKind, str]]) -> tuple[DomainOutput, ...]:
    return tuple(DomainOutput(name, kind, value) for name, (kind, value) in sorted(values.items()))


def _venue_profile_case() -> DomainTruthCase:
    base_reserve = 1_000
    quote_reserve = 1_000
    input_atoms = 100
    cpmm_output = base_reserve - _ceil_div(
        base_reserve * quote_reserve,
        quote_reserve + input_atoms,
    )
    fixed_price_usable = input_atoms - _ceil_div(input_atoms * 100, 10_000)
    if cpmm_output == fixed_price_usable:
        raise ManifestError("venue-profile counterexample collapsed")
    return DomainTruthCase.build(
        "domain-case-01-venue-profile-transfer",
        DomainAdversaryKind.VENUE_PROFILE_TRANSFER,
        ("profile:cpmm-v1", "profile:fixed-bin-v1", "size:quote-100"),
        _outputs(
            {
                "compatible_profile_count": (DomainValueKind.DECIMAL_INTEGER, "2"),
                "cpmm_output_atoms": (DomainValueKind.DECIMAL_INTEGER, str(cpmm_output)),
                "disposition": (DomainValueKind.DISPOSITION, "profile_specific_outputs"),
                "fixed_bin_output_atoms": (
                    DomainValueKind.DECIMAL_INTEGER,
                    str(fixed_price_usable),
                ),
            }
        ),
        "negative_apply_one_venue_profile_to_both_mechanisms",
        "a venue-specific size output is transferred to a distinct profile",
    )


def _platform_burst_case() -> DomainTruthCase:
    rows = (
        ("burst:event-a", "observed", 7),
        ("burst:event-b", "observed", 2),
        ("burst:subject-c", "gap", None),
    )
    observed_atoms = sum(
        value for _, status, value in rows if status == "observed" and value is not None
    )
    observed_count = sum(status == "observed" for _, status, _ in rows)
    gap_count = sum(status == "gap" for _, status, _ in rows)
    if gap_count == 0:
        raise ManifestError("platform burst fixture requires an explicit coverage gap")
    return DomainTruthCase.build(
        "domain-case-02-platform-wide-burst",
        DomainAdversaryKind.PLATFORM_WIDE_BURST,
        tuple(sorted(row[0] for row in rows)),
        _outputs(
            {
                "disposition": (DomainValueKind.DISPOSITION, "refused_incomplete_platform_scope"),
                "gap_count": (DomainValueKind.DECIMAL_INTEGER, str(gap_count)),
                "observed_atoms": (DomainValueKind.DECIMAL_INTEGER, str(observed_atoms)),
                "observed_event_count": (
                    DomainValueKind.DECIMAL_INTEGER,
                    str(observed_count),
                ),
            }
        ),
        "negative_scale_observed_hot_rows_to_platform_total",
        "an incomplete platform denominator is reported as a complete burst",
    )


def _same_chart_case() -> DomainTruthCase:
    display_points = (100, 110, 105)
    curve_material = {
        "mechanism": "bonding_curve",
        "topology": "curve-epoch-1",
        "native_events": ("curve-buy", "curve-sell"),
    }
    bin_material = {
        "mechanism": "discrete_bins",
        "topology": "bin-epoch-9",
        "native_events": ("bin-cross-up", "bin-cross-down"),
    }
    curve_digest = _digest(curve_material)
    bin_digest = _digest(bin_material)
    if curve_digest == bin_digest:
        raise ManifestError("different-mechanism fixture collided")
    return DomainTruthCase.build(
        "domain-case-03-same-chart-different-mechanism",
        DomainAdversaryKind.SAME_CHART_DIFFERENT_MECHANISM,
        ("trace:bonding-curve", "trace:discrete-bins"),
        _outputs(
            {
                "compatible_mechanism_count": (DomainValueKind.DECIMAL_INTEGER, "2"),
                "display_trace_digest": (DomainValueKind.SHA256, _digest(display_points)),
                "mechanism_1_digest": (DomainValueKind.SHA256, min(curve_digest, bin_digest)),
                "mechanism_2_digest": (DomainValueKind.SHA256, max(curve_digest, bin_digest)),
                "mechanism_disposition": (DomainValueKind.DISPOSITION, "compatible_set"),
            }
        ),
        "negative_identify_mechanism_from_equal_display_trace",
        "one mechanism label is inferred from chart shape alone",
    )


def _operator_label_case() -> DomainTruthCase:
    raw = b"idk, maybe thin; hard to say"
    labels = ("attention_rotation", "liquidity_hesitation")
    return DomainTruthCase.build(
        "domain-case-04-operator-label-induction",
        DomainAdversaryKind.OPERATOR_LABEL_INDUCTION,
        ("operator-assertion:ambiguous-001",),
        _outputs(
            {
                "compatible_label_count": (DomainValueKind.DECIMAL_INTEGER, str(len(labels))),
                "label_1": (DomainValueKind.IDENTIFIER, labels[0]),
                "label_2": (DomainValueKind.IDENTIFIER, labels[1]),
                "label_disposition": (DomainValueKind.DISPOSITION, "ambiguous_not_truth_label"),
                "raw_assertion_digest": (DomainValueKind.SHA256, qualified_sha256_bytes(raw)),
            }
        ),
        "negative_force_single_operator_state",
        "an ambiguous raw assertion is coerced into one latent truth label",
    )


def _runner_case() -> DomainTruthCase:
    starting_atoms = 10
    disposed_atoms = 6
    remaining_atoms = starting_atoms - disposed_atoms
    if remaining_atoms <= 0:
        raise ManifestError("runner fixture must retain positive inventory")
    return DomainTruthCase.build(
        "domain-case-05-runner-liquidation-divergence",
        DomainAdversaryKind.RUNNER_LIQUIDATION_DIVERGENCE,
        ("effect:sell-6", "mark:take-some", "terminal-quote:gap"),
        _outputs(
            {
                "disposed_atoms": (DomainValueKind.DECIMAL_INTEGER, str(disposed_atoms)),
                "episode_disposition": (DomainValueKind.DISPOSITION, "partial_with_runner"),
                "remaining_runner_atoms": (
                    DomainValueKind.DECIMAL_INTEGER,
                    str(remaining_atoms),
                ),
                "terminal_value_disposition": (
                    DomainValueKind.DISPOSITION,
                    "refused_missing_terminal_quote",
                ),
            }
        ),
        "negative_treat_mark_or_partial_effect_as_full_liquidation",
        "a take-some mark or partial effect is rewritten as a complete exit/value",
    )


def _household_self_flow_case() -> DomainTruthCase:
    transfers = (
        ("principal", "wallet-a", "wallet-b", 10, True, True),
        ("fee", "wallet-a", "wallet-b", 2, True, True),
    )
    internal_atoms = sum(
        atoms
        for _, _, _, atoms, sender_inside, receiver_inside in transfers
        if sender_inside and receiver_inside
    )
    external_atoms = sum(
        atoms
        for _, _, _, atoms, sender_inside, receiver_inside in transfers
        if sender_inside != receiver_inside
    )
    naive_self_fee_atoms = sum(atoms for kind, _, _, atoms, _, _ in transfers if kind == "fee")
    if internal_atoms != 12 or external_atoms != 0 or naive_self_fee_atoms != 2:
        raise ManifestError("household self-flow fixture changed")
    return DomainTruthCase.build(
        "domain-case-06-household-self-flow",
        DomainAdversaryKind.HOUSEHOLD_SELF_FLOW,
        ("household:h1", "transfer:principal-10", "transfer:self-fee-2"),
        _outputs(
            {
                "external_household_flow_atoms": (
                    DomainValueKind.DECIMAL_INTEGER,
                    str(external_atoms),
                ),
                "internal_counterleg_atoms": (
                    DomainValueKind.DECIMAL_INTEGER,
                    str(internal_atoms),
                ),
                "naive_self_fee_income_atoms": (
                    DomainValueKind.DECIMAL_INTEGER,
                    str(naive_self_fee_atoms),
                ),
                "posting_disposition": (
                    DomainValueKind.DISPOSITION,
                    "self_flow_removed_from_household_pnl",
                ),
            }
        ),
        "negative_post_self_routed_fee_as_household_profit",
        "an internal principal or fee counterleg is counted as external wealth",
    )


def _exit_reentry_case() -> DomainTruthCase:
    rows = (
        {
            "event_id": "inventory:exit",
            "available_at": datetime(2026, 8, 18, 12, 0, 1, tzinfo=UTC),
            "commit_seq": 1,
            "inventory_atoms": 0,
            "inventory_epoch": "inventory-epoch-1",
        },
        {
            "event_id": "inventory:reentry",
            "available_at": datetime(2026, 8, 18, 12, 0, 3, tzinfo=UTC),
            "commit_seq": 3,
            "inventory_atoms": 7,
            "inventory_epoch": "inventory-epoch-2",
        },
    )

    early_cut = datetime(2026, 8, 18, 12, 0, 2, tzinfo=UTC)
    late_cut = datetime(2026, 8, 18, 12, 0, 4, tzinfo=UTC)
    early_atoms, early_epoch, early_digest = derive_exit_reentry_at_cut(rows, early_cut, 2)
    early_without_future = derive_exit_reentry_at_cut(rows[:1], early_cut, 2)
    malformed_future = (rows[0], rows[1] | {"inventory_atoms": "malformed-future"})
    early_with_malformed_future = derive_exit_reentry_at_cut(malformed_future, early_cut, 2)
    late_atoms, late_epoch, _ = derive_exit_reentry_at_cut(rows, late_cut, 4)
    if (
        early_atoms,
        early_epoch,
        early_digest,
    ) != early_without_future or early_with_malformed_future != early_without_future:
        raise ManifestError("future re-entry changed the earlier frozen cut")
    return DomainTruthCase.build(
        "domain-case-07-frozen-future-exit-reentry",
        DomainAdversaryKind.FROZEN_FUTURE_EXIT_REENTRY,
        ("inventory:exit", "inventory:reentry"),
        _outputs(
            {
                "early_input_digest": (DomainValueKind.SHA256, early_digest),
                "early_inventory_atoms": (
                    DomainValueKind.DECIMAL_INTEGER,
                    str(early_atoms),
                ),
                "early_state": (DomainValueKind.DISPOSITION, "watching_flat"),
                "early_inventory_epoch": (DomainValueKind.IDENTIFIER, early_epoch),
                "late_inventory_atoms": (
                    DomainValueKind.DECIMAL_INTEGER,
                    str(late_atoms),
                ),
                "late_inventory_epoch": (DomainValueKind.IDENTIFIER, late_epoch),
                "late_state": (DomainValueKind.DISPOSITION, "reentered_new_inventory_epoch"),
            }
        ),
        "negative_backfill_reentry_into_earlier_flat_cut",
        "future-known re-entry rewrites the prior flat interval or inventory epoch",
    )


def build_domain_known_truth_battery() -> DomainKnownTruthBattery:
    """Build all seven generated domain counterexamples in canonical case order."""

    cases = tuple(
        sorted(
            (
                _venue_profile_case(),
                _platform_burst_case(),
                _same_chart_case(),
                _operator_label_case(),
                _runner_case(),
                _household_self_flow_case(),
                _exit_reentry_case(),
            ),
            key=lambda case: case.case_id,
        )
    )
    return DomainKnownTruthBattery("wave6-domain-known-truth-v1", cases)
