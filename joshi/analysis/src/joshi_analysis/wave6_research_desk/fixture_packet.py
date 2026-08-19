"""N00/N01-bound fixture packet for the Wave 6 machine research desk.

The adapter reads only caller-supplied exact checked-in bytes. It can prove cross-contract fixture
closure, not durable registration, store provenance, a scientific result, or permission to query.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..canonical import canonical_json_bytes, qualified_sha256_bytes, require_qualified_sha256
from ..errors import ManifestError
from ..wave6_known_truth import (
    CandidateResult,
    KnownTruthEvaluation,
    KnownTruthSuite,
    ProtocolBatteryEvaluation,
    ProtocolCandidateResult,
    ProtocolKnownTruthBattery,
    StructuralBatteryEvaluation,
    StructuralCandidateResult,
    StructuralKnownTruthBattery,
    build_protocol_known_truth_battery,
    build_signed_flow_known_truth_suite,
    build_structural_known_truth_battery,
    evaluate_candidate_suite,
    evaluate_protocol_candidate,
    evaluate_structural_candidate,
)
from ..wave6_known_truth.lab import derive_truth
from .contracts import (
    ArtifactDescriptor,
    ArtifactRole,
    Control,
    CoverageStatus,
    DeskPolicy,
    Estimand,
    ExperimentManifest,
    Falsifier,
    Feature,
    ProposalKind,
    ProposalSpec,
    ResearchProposal,
)
from .desk import propose

PROGRAM_CONTRACT = "joshi.wave6.program-registration.v1"
PROGRAM_AUTHORITY = "read_record_replay_propose_shadow_only"
PROGRAM_CEILING = "unverified_semantic_fixture_only"
FIXTURE_PACKET_SCHEMA = "joshi.analysis.wave6-fixture-research-packet/v1"
FIXTURE_PACKET_AUTHORITY = "fixture_inspection_proposal_only_no_query_no_action_no_claim_promotion"
FIXTURE_PACKET_CLAIM_SCOPE = "protocol_draft_not_result_release_or_live_decision"
RESEARCH_KIND_ID = "research_proposal_fixture"
RESEARCH_SCHEMA_ID = "joshi.analysis.wave6-research-desk/v1"
DOMAIN_TRUTH_KIND_ID = "domain_known_truth_evaluation_fixture"
DOMAIN_TRUTH_SCHEMA_ID = "joshi.analysis.wave6-domain-known-truth/v1"
KNOWN_TRUTH_KIND_ID = "known_truth_evaluation_fixture"
KNOWN_TRUTH_SCHEMA_ID = "joshi.analysis.wave6-known-truth/v1"
PROTOCOL_TRUTH_KIND_ID = "protocol_known_truth_evaluation_fixture"
PROTOCOL_TRUTH_SCHEMA_ID = "joshi.analysis.wave6-protocol-known-truth/v1"
STRUCTURAL_TRUTH_KIND_ID = "structural_known_truth_evaluation_fixture"
STRUCTURAL_TRUTH_SCHEMA_ID = "joshi.analysis.wave6-structural-known-truth/v1"

_TOP_LEVEL_KEYS = (
    "contract",
    "programId",
    "programFamilyId",
    "semanticVersion",
    "sourceTreeDigest",
    "buildDigest",
    "environmentDigest",
    "configDigest",
    "authority",
    "semanticCeiling",
    "consumedWave5Gates",
    "artifactKinds",
    "localSymbols",
    "dataPolicy",
    "budgets",
    "permittedDeskOperations",
    "prohibitedSources",
    "prohibitedOutputs",
    "prohibitedClaims",
    "prohibitedSideEffects",
    "registeredAt",
    "registrationDigest",
)
_ARTIFACT_KIND_KEYS = (
    "kindId",
    "schemaId",
    "schemaDigest",
    "claimRung",
    "maxFixtureMaturity",
    "permittedClaim",
    "prohibitedInference",
)
_REQUIRED_SIDE_EFFECT_PROHIBITIONS = {
    "acquisition_or_hot_lease_mutation",
    "asset_reservation",
    "glass_or_presentation_mutation",
    "liquidity_installation",
    "transaction_construction_signing_or_submission",
}
_EXPECTED_DATA_POLICY = {
    "privacyClass": "fixture_public_no_personal_data",
    "retentionClass": "checked_in_fixture_only",
    "deletionClass": "repository_history_only",
    "exportClass": "fixture_artifact_only",
}
_EXPECTED_DESK_OPERATIONS = [
    "inspect_fixture_descriptor",
    "compare_fixture_artifacts",
    "draft_non_executable_protocol",
    "emit_refusal",
]
_EXPECTED_PROHIBITED_SOURCES = [
    "authenticated_live_source",
    "paid_provider_query",
    "wallet_or_signing_material",
]
_EXPECTED_PROHIBITED_OUTPUTS = [
    "live_alert_or_ranking",
    "operator_visible_forecast",
    "production_market_release",
]
_EXPECTED_PROHIBITED_CLAIMS = [
    "causal_identification",
    "economic_profit_or_advantage",
    "hidden_identity_or_intent",
    "operational_or_product_maturity",
]
_EXPECTED_ARTIFACT_KIND_BOUNDARIES = {
    "campaign_registration_fixture": (
        "joshi.wave6.campaign-registration.v1",
        "h5_policy",
        "fixture_campaign_protocol_only",
        "prospective_result_or_operational_campaign",
    ),
    DOMAIN_TRUTH_KIND_ID: (
        DOMAIN_TRUTH_SCHEMA_ID,
        "h1_protocol_kinematics",
        "fixture_domain_counterexample_recovery_or_refusal",
        "market_identity_causal_policy_or_economic_claim",
    ),
    "market_atlas_fixture": (
        "joshi.analysis.wave6-market-atlas-snapshot/v1",
        "h2_descriptive",
        "fixture_point_in_time_description",
        "market_or_strategy_claim",
    ),
    "known_truth_evaluation_fixture": (
        KNOWN_TRUTH_SCHEMA_ID,
        "h1_protocol_kinematics",
        "fixture_known_truth_recovery_or_refusal",
        "market_or_estimator_performance_claim",
    ),
    "protocol_known_truth_evaluation_fixture": (
        PROTOCOL_TRUTH_SCHEMA_ID,
        "h1_protocol_kinematics",
        "fixture_protocol_arithmetic_or_refusal",
        "quote_route_or_economic_claim",
    ),
    "research_proposal_fixture": (
        RESEARCH_SCHEMA_ID,
        "h5_policy",
        "non_executable_research_design_proposal",
        "study_result_or_policy_value",
    ),
    "structural_known_truth_evaluation_fixture": (
        STRUCTURAL_TRUTH_SCHEMA_ID,
        "h1_protocol_kinematics",
        "fixture_structural_transition_or_ambiguity",
        "identity_market_causal_or_economic_claim",
    ),
}
_RESEARCH_SCHEMA_DESCRIPTOR = {
    "authority": "read_only_proposal_only_no_query_no_glass_no_action_no_claim_promotion",
    "claimScope": "research_design_proposal_not_result_or_live_decision",
    "contract": RESEARCH_SCHEMA_ID,
    "fields": [
        {"name": "proposal_id", "type": "stable_string"},
        {"name": "proposal_digest", "type": "sha256"},
        {"name": "policy_id", "type": "stable_string"},
        {"name": "policy", "type": "DeskPolicy"},
        {"name": "policy_digest", "type": "sha256"},
        {"name": "evidence_closure_digest", "type": "sha256"},
        {"name": "commitment_digest", "type": "sha256"},
        {"name": "created_at", "type": "utc_microsecond"},
        {"name": "hypothesis_locked_at", "type": "utc_microsecond"},
        {"name": "specification", "type": "ProposalSpec"},
        {"name": "artifact_descriptors", "type": "sorted_list<ArtifactDescriptor>"},
        {"name": "authority", "type": "fixed_literal"},
        {"name": "claim_scope", "type": "fixed_literal"},
    ],
    "nestedContracts": {
        "ArtifactDescriptor": "point_in_time_no_data_handle",
        "DeskPolicy": "bounded_no_query_no_execution",
        "ExperimentManifest": "executable_false_query_count_zero",
        "ProposalSpec": "estimand_controls_features_counterexamples_falsifiers_experiments",
    },
}


def research_proposal_schema_bytes() -> bytes:
    """Return the exact checked schema descriptor expected by the Python contract."""

    return canonical_json_bytes(_RESEARCH_SCHEMA_DESCRIPTOR, newline=True)


def _stable(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ManifestError(f"{field} must be a bounded, unpadded stable string")
    return value


def _ordered_keys(value: dict[str, Any], expected: tuple[str, ...], field: str) -> None:
    if tuple(value) != expected:
        raise ManifestError(f"{field} keys/order differ from the exact V1 contract")


def _wire_u64(value: Any, field: str) -> int:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdigit()
        or (value != "0" and value.startswith("0"))
    ):
        raise ManifestError(f"{field} must be a canonical decimal string")
    parsed = int(value)
    if parsed > 2**64 - 1:
        raise ManifestError(f"{field} exceeds u64")
    return parsed


@dataclass(frozen=True, slots=True)
class FixtureProgramRegistration:
    """Independently checked Python view of the exact Rust N00 fixture registration."""

    document: dict[str, Any]
    exact_bytes: bytes
    document_digest: str

    @property
    def program_id(self) -> str:
        return self.document["programId"]

    @property
    def registration_digest(self) -> str:
        return self.document["registrationDigest"]

    def artifact_kind(self, kind_id: str) -> dict[str, Any]:
        for kind in self.document["artifactKinds"]:
            if kind["kindId"] == kind_id:
                return kind
        raise ManifestError(f"program registration does not admit artifact kind {kind_id}")


def parse_fixture_program_registration_exact(
    exact_bytes: bytes, schema_bytes_by_kind: dict[str, bytes]
) -> FixtureProgramRegistration:
    """Strictly cross-check exact N00 bytes and every registered artifact schema digest."""

    try:
        document = json.loads(exact_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ManifestError("program registration is not valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ManifestError("program registration must be one JSON object")
    _ordered_keys(document, _TOP_LEVEL_KEYS, "program registration")
    canonical = (
        json.dumps(
            document, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=False
        ).encode()
        + b"\n"
    )
    if canonical != exact_bytes:
        raise ManifestError("program registration is not exact compact JSON with one newline")
    if (
        document["contract"] != PROGRAM_CONTRACT
        or document["authority"] != PROGRAM_AUTHORITY
        or document["semanticCeiling"] != PROGRAM_CEILING
        or document["consumedWave5Gates"] != []
    ):
        raise ManifestError(
            "fixture program contract, authority, ceiling, or gate boundary changed"
        )
    for field in ("programId", "programFamilyId", "semanticVersion"):
        _stable(document[field], field)
    for field in (
        "sourceTreeDigest",
        "buildDigest",
        "environmentDigest",
        "configDigest",
        "registrationDigest",
    ):
        try:
            require_qualified_sha256(document[field], field)
        except ValueError as error:
            raise ManifestError(str(error)) from error
    digest_material = dict(document)
    declared = digest_material.pop("registrationDigest")
    computed = qualified_sha256_bytes(
        json.dumps(
            digest_material,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=False,
        ).encode()
        + b"\n"
    )
    if declared != computed:
        raise ManifestError("program registration self-digest mismatch")

    kinds = document["artifactKinds"]
    if not isinstance(kinds, list) or not kinds:
        raise ManifestError("program registration needs artifact kinds")
    kind_ids: list[str] = []
    for kind in kinds:
        if not isinstance(kind, dict):
            raise ManifestError("artifact kind must be an object")
        _ordered_keys(kind, _ARTIFACT_KIND_KEYS, "artifact kind")
        kind_id = _stable(kind["kindId"], "kindId")
        kind_ids.append(kind_id)
        try:
            require_qualified_sha256(kind["schemaDigest"], "schemaDigest")
        except ValueError as error:
            raise ManifestError(str(error)) from error
        schema_bytes = schema_bytes_by_kind.get(kind_id)
        if schema_bytes is None or qualified_sha256_bytes(schema_bytes) != kind["schemaDigest"]:
            raise ManifestError("artifact schema bytes do not match the registered digest")
        if kind["maxFixtureMaturity"] not in {"contract_only", "fixture_roundtrip"}:
            raise ManifestError("artifact kind attempts to exceed fixture maturity")
        for field in ("schemaId", "permittedClaim", "prohibitedInference"):
            _stable(kind[field], f"artifact kind {field}")
        if (
            kind["schemaId"],
            kind["claimRung"],
            kind["permittedClaim"],
            kind["prohibitedInference"],
        ) != _EXPECTED_ARTIFACT_KIND_BOUNDARIES.get(kind_id):
            raise ManifestError("artifact kind changed its exact schema or claim boundary")
    if kind_ids != sorted(set(kind_ids)) or set(schema_bytes_by_kind) != set(kind_ids):
        raise ManifestError("artifact kinds and supplied schema documents must close exactly")

    budgets = document["budgets"]
    if not isinstance(budgets, dict):
        raise ManifestError("program budgets must be an object")
    budget_keys = (
        "computeUnits",
        "readUnits",
        "attentionUnits",
        "providerUnits",
        "externalMutationUnits",
        "maxArtifacts",
    )
    _ordered_keys(budgets, budget_keys, "program budgets")
    parsed_budgets = {field: _wire_u64(budgets[field], field) for field in budget_keys}
    if (
        parsed_budgets["providerUnits"] != 0
        or parsed_budgets["externalMutationUnits"] != 0
        or parsed_budgets["maxArtifacts"] == 0
    ):
        raise ManifestError(
            "fixture provider/external budgets must be zero and artifact cap positive"
        )
    if document["dataPolicy"] != _EXPECTED_DATA_POLICY:
        raise ManifestError("program registration widened fixture data policy")
    _ordered_keys(
        document["dataPolicy"],
        ("privacyClass", "retentionClass", "deletionClass", "exportClass"),
        "program data policy",
    )
    if document["permittedDeskOperations"] != _EXPECTED_DESK_OPERATIONS:
        raise ManifestError("program registration changed fixture desk operations")
    if document["prohibitedSources"] != _EXPECTED_PROHIBITED_SOURCES:
        raise ManifestError("program registration widened prohibited sources")
    if document["prohibitedOutputs"] != _EXPECTED_PROHIBITED_OUTPUTS:
        raise ManifestError("program registration widened prohibited outputs")
    if document["prohibitedClaims"] != _EXPECTED_PROHIBITED_CLAIMS:
        raise ManifestError("program registration widened prohibited claims")
    if (
        not isinstance(document["prohibitedSideEffects"], list)
        or document["prohibitedSideEffects"] != sorted(set(document["prohibitedSideEffects"]))
        or not _REQUIRED_SIDE_EFFECT_PROHIBITIONS.issubset(document["prohibitedSideEffects"])
    ):
        raise ManifestError("program registration widened a prohibited side effect")
    symbols = document["localSymbols"]
    if (
        not isinstance(symbols, list)
        or not symbols
        or any(not isinstance(symbol, dict) for symbol in symbols)
    ):
        raise ManifestError("program local symbols must be exact objects")
    for symbol in symbols:
        if tuple(symbol) != (
            "symbolId",
            "definition",
            "unit",
            "clock",
        ):
            raise ManifestError("program local symbol differs from the exact V1 contract")
        _stable(symbol["symbolId"], "symbolId")
        _stable(symbol["definition"], "symbol definition")
        if symbol["unit"] is not None:
            _stable(symbol["unit"], "symbol unit")
        if symbol["clock"] is not None:
            _stable(symbol["clock"], "symbol clock")
    symbol_ids = [symbol["symbolId"] for symbol in symbols]
    if symbol_ids != sorted(set(symbol_ids)):
        raise ManifestError("program local symbols must be sorted and unique")

    return FixtureProgramRegistration(document, exact_bytes, qualified_sha256_bytes(exact_bytes))


def _known_truth_evaluation() -> tuple[KnownTruthSuite, KnownTruthEvaluation]:
    suite = build_signed_flow_known_truth_suite()
    results = tuple(CandidateResult.build(case, derive_truth(case)) for case in suite.cases)
    return suite, evaluate_candidate_suite(suite, "candidate:exact-reference", results)


def _protocol_known_truth_evaluation(
    pump_fixture_bytes: bytes, dlmm_fixture_bytes: bytes
) -> tuple[ProtocolKnownTruthBattery, ProtocolBatteryEvaluation]:
    battery = build_protocol_known_truth_battery(pump_fixture_bytes, dlmm_fixture_bytes)
    results = tuple(ProtocolCandidateResult.build(case) for case in battery.cases)
    return battery, evaluate_protocol_candidate(
        battery, "candidate:python-protocol-exact-reference", results
    )


def _structural_known_truth_evaluation(
    structural_fixture_bytes: bytes,
) -> tuple[StructuralKnownTruthBattery, StructuralBatteryEvaluation]:
    battery = build_structural_known_truth_battery(structural_fixture_bytes)
    results = tuple(StructuralCandidateResult.build(case) for case in battery.cases)
    return battery, evaluate_structural_candidate(
        battery, "candidate:python-structural-exact-reference", results
    )


def _proposal(
    suite: KnownTruthSuite,
    evaluation: KnownTruthEvaluation,
    protocol_battery: ProtocolKnownTruthBattery,
    protocol_evaluation: ProtocolBatteryEvaluation,
    structural_battery: StructuralKnownTruthBattery,
    structural_evaluation: StructuralBatteryEvaluation,
) -> tuple[
    ResearchProposal,
    tuple[ArtifactDescriptor, ArtifactDescriptor, ArtifactDescriptor],
]:
    t0 = datetime(2026, 8, 18, tzinfo=UTC)
    artifact_id = f"known-truth-evaluation-{evaluation.evaluation_digest[7:39]}"
    known_truth_descriptor = ArtifactDescriptor(
        artifact_id,
        ArtifactRole.DESIGN,
        t0 + timedelta(minutes=5),
        t0 + timedelta(minutes=10),
        10,
        evaluation.evaluation_digest,
        CoverageStatus.COMPLETE,
        1_000_000,
        (),
        "fixture_case_fraction_ppm",
        "known-truth-suite",
        "n01-fixture-battery-v2",
    )
    protocol_artifact_id = (
        f"protocol-truth-evaluation-{protocol_evaluation.evaluation_digest[7:39]}"
    )
    protocol_descriptor = ArtifactDescriptor(
        protocol_artifact_id,
        ArtifactRole.DESIGN,
        t0 + timedelta(minutes=6),
        t0 + timedelta(minutes=10),
        11,
        protocol_evaluation.evaluation_digest,
        CoverageStatus.COMPLETE,
        1_000_000,
        (),
        "fixture_case_fraction_ppm",
        "known-truth-suite",
        "n01-fixture-battery-v2",
    )
    structural_artifact_id = (
        f"structural-truth-evaluation-{structural_evaluation.evaluation_digest[7:39]}"
    )
    structural_descriptor = ArtifactDescriptor(
        structural_artifact_id,
        ArtifactRole.DESIGN,
        t0 + timedelta(minutes=7),
        t0 + timedelta(minutes=10),
        12,
        structural_evaluation.evaluation_digest,
        CoverageStatus.COMPLETE,
        1_000_000,
        (),
        "fixture_case_fraction_ppm",
        "known-truth-suite",
        "n01-fixture-battery-v2",
    )
    descriptors = (known_truth_descriptor, protocol_descriptor, structural_descriptor)
    policy = DeskPolicy(
        "desk-policy-known-truth-fixture-v1",
        t0 + timedelta(minutes=11),
        1_000_000,
        (),
        "fixture_case_fraction_ppm",
        "known-truth-suite",
        "n01-fixture-battery-v2",
        3,
        1,
        3,
        3,
    )
    specification = ProposalSpec(
        ProposalKind.EXPERIMENT_MANIFEST,
        "predeclare an independent known-truth candidate comparison",
        (
            "a separately implemented candidate either reproduces every frozen fixture "
            "disposition or is refused"
        ),
        (artifact_id, protocol_artifact_id, structural_artifact_id),
        Estimand(
            "fixture-recovery-fraction",
            "exactly reproduced frozen case dispositions",
            "eighteen preregistered generic, protocol, and structural adversary cases",
            "fixture_recovery_fraction",
            "fixture_case_fraction_ppm",
        ),
        (
            Control(
                "exact-reference-control",
                "deterministic reference candidate over the same frozen case manifests",
                "detect candidate and packet wiring errors before comparison",
            ),
        ),
        (
            Feature(
                "adversary-family",
                (
                    "one of the eighteen frozen generic, protocol, or structural "
                    "recovery/refusal families"
                ),
                "categorical_case_family",
            ),
        ),
        tuple(
            sorted(
                [f"counterexample:{case.adversary.value}" for case in suite.cases]
                + [f"counterexample:{case.adversary.value}" for case in protocol_battery.cases]
                + [f"counterexample:{case.adversary.value}" for case in structural_battery.cases]
            )
        ),
        (
            Falsifier(
                "any-case-mismatch",
                (
                    "candidate changes a disposition, exact value, compatible set, refusal, "
                    "cut, evidence membership, protocol arithmetic, migration splice, "
                    "same-slot order set, or identity revision boundary"
                ),
                "reject the candidate for this registered fixture suite",
            ),
        ),
        (
            ExperimentManifest(
                "offline-candidate-comparison",
                "compare immutable candidate bytes without query or execution",
                (artifact_id, protocol_artifact_id, structural_artifact_id),
                3,
            ),
        ),
    )
    return (
        propose(
            policy,
            specification,
            descriptors,
            created_at=t0 + timedelta(minutes=12),
            hypothesis_locked_at=t0 + timedelta(minutes=11),
        ),
        descriptors,
    )


@dataclass(frozen=True, slots=True)
class FixtureResearchPacket:
    packet_id: str
    packet_digest: str
    registration: FixtureProgramRegistration
    known_truth_suite: KnownTruthSuite
    known_truth_evaluation: KnownTruthEvaluation
    protocol_known_truth_battery: ProtocolKnownTruthBattery
    protocol_known_truth_evaluation: ProtocolBatteryEvaluation
    structural_known_truth_battery: StructuralKnownTruthBattery
    structural_known_truth_evaluation: StructuralBatteryEvaluation
    proposal: ResearchProposal
    status: str = "protocol_draft"
    authority: str = FIXTURE_PACKET_AUTHORITY
    claim_scope: str = FIXTURE_PACKET_CLAIM_SCOPE
    executable: bool = False
    query_count: int = 0

    def content(self) -> dict[str, Any]:
        return {
            "schema_id": FIXTURE_PACKET_SCHEMA,
            "program_id": self.registration.program_id,
            "program_registration_digest": self.registration.registration_digest,
            "program_document_digest": self.registration.document_digest,
            "known_truth_suite_id": self.known_truth_suite.suite_id,
            "known_truth_suite_digest": self.known_truth_suite.suite_digest,
            "known_truth_evaluation_digest": self.known_truth_evaluation.evaluation_digest,
            "protocol_known_truth_suite_id": self.protocol_known_truth_battery.suite_id,
            "protocol_known_truth_suite_digest": self.protocol_known_truth_battery.suite_digest,
            "protocol_known_truth_evaluation_digest": (
                self.protocol_known_truth_evaluation.evaluation_digest
            ),
            "structural_known_truth_suite_id": self.structural_known_truth_battery.suite_id,
            "structural_known_truth_suite_digest": self.structural_known_truth_battery.suite_digest,
            "structural_known_truth_evaluation_digest": (
                self.structural_known_truth_evaluation.evaluation_digest
            ),
            "proposal": self.proposal.as_dict(),
            "status": self.status,
            "authority": self.authority,
            "claim_scope": self.claim_scope,
            "executable": self.executable,
            "query_count": self.query_count,
        }

    def validate(
        self,
        schema_bytes_by_kind: dict[str, bytes],
        pump_fixture_bytes: bytes,
        dlmm_fixture_bytes: bytes,
        structural_fixture_bytes: bytes,
    ) -> None:
        registration = parse_fixture_program_registration_exact(
            self.registration.exact_bytes, schema_bytes_by_kind
        )
        if registration != self.registration:
            raise ManifestError("packet registration differs from exact reparsed bytes")
        research_kind = registration.artifact_kind(RESEARCH_KIND_ID)
        if research_kind["schemaId"] != RESEARCH_SCHEMA_ID:
            raise ManifestError("research proposal kind does not match the registered schema")
        if (
            registration.artifact_kind(DOMAIN_TRUTH_KIND_ID)["schemaId"]
            != DOMAIN_TRUTH_SCHEMA_ID
            or registration.artifact_kind(KNOWN_TRUTH_KIND_ID)["schemaId"]
            != KNOWN_TRUTH_SCHEMA_ID
            or registration.artifact_kind(PROTOCOL_TRUTH_KIND_ID)["schemaId"]
            != PROTOCOL_TRUTH_SCHEMA_ID
            or registration.artifact_kind(STRUCTURAL_TRUTH_KIND_ID)["schemaId"]
            != STRUCTURAL_TRUTH_SCHEMA_ID
        ):
            raise ManifestError("N01 evaluation kind does not match the registered schema")
        suite, evaluation = _known_truth_evaluation()
        if suite != self.known_truth_suite or evaluation != self.known_truth_evaluation:
            raise ManifestError("packet known-truth closure is not the deterministic N01 fixture")
        protocol_battery, protocol_evaluation = _protocol_known_truth_evaluation(
            pump_fixture_bytes, dlmm_fixture_bytes
        )
        if (
            protocol_battery != self.protocol_known_truth_battery
            or protocol_evaluation != self.protocol_known_truth_evaluation
        ):
            raise ManifestError(
                "packet protocol known-truth closure is not the deterministic N01 fixture"
            )
        structural_battery, structural_evaluation = _structural_known_truth_evaluation(
            structural_fixture_bytes
        )
        if (
            structural_battery != self.structural_known_truth_battery
            or structural_evaluation != self.structural_known_truth_evaluation
        ):
            raise ManifestError(
                "packet structural known-truth closure is not the deterministic N01 fixture"
            )
        expected_proposal, expected_descriptors = _proposal(
            suite,
            evaluation,
            protocol_battery,
            protocol_evaluation,
            structural_battery,
            structural_evaluation,
        )
        self.proposal.validate()
        if (
            self.proposal != expected_proposal
            or self.proposal.artifact_descriptors != expected_descriptors
        ):
            raise ManifestError("packet proposal does not bind the exact N01 evaluations")
        if (
            self.status != "protocol_draft"
            or self.authority != FIXTURE_PACKET_AUTHORITY
            or self.claim_scope != FIXTURE_PACKET_CLAIM_SCOPE
            or self.executable
            or self.query_count != 0
        ):
            raise ManifestError("fixture packet widened status, authority, or execution boundary")
        digest = qualified_sha256_bytes(canonical_json_bytes(self.content()))
        if (
            self.packet_digest != digest
            or self.packet_id != f"fixture-research-packet-{digest[7:39]}"
        ):
            raise ManifestError("fixture packet identity does not match exact content")

    def as_dict(
        self,
        schema_bytes_by_kind: dict[str, bytes],
        pump_fixture_bytes: bytes,
        dlmm_fixture_bytes: bytes,
        structural_fixture_bytes: bytes,
    ) -> dict[str, Any]:
        self.validate(
            schema_bytes_by_kind,
            pump_fixture_bytes,
            dlmm_fixture_bytes,
            structural_fixture_bytes,
        )
        return {
            "packet_id": self.packet_id,
            "packet_digest": self.packet_digest,
            **self.content(),
        }


def build_fixture_research_packet(
    registration_bytes: bytes,
    schema_bytes_by_kind: dict[str, bytes],
    pump_fixture_bytes: bytes,
    dlmm_fixture_bytes: bytes,
    structural_fixture_bytes: bytes,
) -> FixtureResearchPacket:
    """Build one deterministic no-query N00/N01-bound research protocol draft."""

    registration = parse_fixture_program_registration_exact(
        registration_bytes, schema_bytes_by_kind
    )
    suite, evaluation = _known_truth_evaluation()
    protocol_battery, protocol_evaluation = _protocol_known_truth_evaluation(
        pump_fixture_bytes, dlmm_fixture_bytes
    )
    structural_battery, structural_evaluation = _structural_known_truth_evaluation(
        structural_fixture_bytes
    )
    proposal, _ = _proposal(
        suite,
        evaluation,
        protocol_battery,
        protocol_evaluation,
        structural_battery,
        structural_evaluation,
    )
    provisional = FixtureResearchPacket(
        "fixture-research-packet-pending",
        "sha256:" + "0" * 64,
        registration,
        suite,
        evaluation,
        protocol_battery,
        protocol_evaluation,
        structural_battery,
        structural_evaluation,
        proposal,
    )
    digest = qualified_sha256_bytes(canonical_json_bytes(provisional.content()))
    packet = FixtureResearchPacket(
        f"fixture-research-packet-{digest[7:39]}",
        digest,
        registration,
        suite,
        evaluation,
        protocol_battery,
        protocol_evaluation,
        structural_battery,
        structural_evaluation,
        proposal,
    )
    packet.validate(
        schema_bytes_by_kind,
        pump_fixture_bytes,
        dlmm_fixture_bytes,
        structural_fixture_bytes,
    )
    return packet
