"""The declared policy file: the bridge artifact a Rust harness variant can execute.

A promising cell of the evaluation grid does not become a claim; it becomes a JSON file under
the contract ``joshi.scalplab.declared_policy.v1`` carrying everything an executor needs and
everything an auditor is owed: feature definitions verbatim, model parameters, threshold,
horizon, floor, the honest decision clock, the exit alarm, the tape provenance, the LOCO
evaluation block, and a non-blank author-knowledge disclosure — a blank one is refused,
mirroring the replay harness's RULES_ARE_NOT_BLIND stance.
"""

from __future__ import annotations

import json
from pathlib import Path

from .featureset import FEATURE_DEFINITIONS, FEATURE_NAMES
from .vocabulary import (
    AUTHOR_KNOWLEDGE_REQUIRED,
    EXECUTION_DELAY_EVENTS,
    LAB_AUTHORITY,
    NOT_AN_ECONOMIC_VERDICT,
    ONE_TAPE_FITS_NOTHING,
    POLICY_CONTRACT,
    REGISTRATION_VERSION,
)

_HAWKES_HEAD_FEATURES = {
    "log_lambda_buy": "log of the causal buy intensity at the event instant (pre-event)",
    "log_lambda_sell": "log of the causal sell intensity at the event instant (pre-event)",
}


class PolicyError(Exception):
    """A policy file this module refuses to write."""


def declared_policy(
    *,
    family: str,
    model_params: dict,
    horizon_k: int,
    threshold: float,
    venue_floor_bps: int,
    decision_clock: str,
    exit_alarm: str,
    tape_provenances: list[dict],
    evaluation: dict,
    author_knowledge: str,
    parameters_scope: str = (
        "full-corpus refit with the registered procedure; the evaluation block is "
        "leave-one-coin-out and was NOT produced by these exact parameters"
    ),
) -> dict:
    """Assemble and validate one declared policy document."""
    if family == "hawkes":
        features = dict(_HAWKES_HEAD_FEATURES)
    else:
        features = {name: FEATURE_DEFINITIONS[name] for name in FEATURE_NAMES}
    doc = {
        "contract": POLICY_CONTRACT,
        "registration": REGISTRATION_VERSION,
        "authority": LAB_AUTHORITY,
        "family": family,
        "features": features,
        "model": model_params,
        "parametersScope": parameters_scope,
        "decision": {
            "probabilityThreshold": threshold,
            "horizonKEvents": horizon_k,
            "executionDelayEvents": EXECUTION_DELAY_EVENTS,
            "venueFloorBps": venue_floor_bps,
            "decisionClock": decision_clock,
            "exitAlarm": exit_alarm,
        },
        "provenance": {"tapes": tape_provenances},
        "evaluation": evaluation,
        "authorKnowledge": author_knowledge,
        "honesty": {
            "oneTapeFitsNothing": ONE_TAPE_FITS_NOTHING,
            "notAnEconomicVerdict": NOT_AN_ECONOMIC_VERDICT,
        },
    }
    validate_policy(doc)
    return doc


def validate_policy(doc: dict) -> None:
    if doc.get("contract") != POLICY_CONTRACT:
        raise PolicyError(f"contract must be {POLICY_CONTRACT}")
    knowledge = doc.get("authorKnowledge")
    if not isinstance(knowledge, str) or not knowledge.strip():
        raise PolicyError(AUTHOR_KNOWLEDGE_REQUIRED)
    decision = doc.get("decision", {})
    threshold = decision.get("probabilityThreshold")
    if not isinstance(threshold, int | float) or not 0.0 < threshold < 1.0:
        raise PolicyError("probabilityThreshold must lie strictly inside (0, 1)")
    horizon = decision.get("horizonKEvents")
    if not isinstance(horizon, int) or horizon < 1:
        raise PolicyError("horizonKEvents must be a positive integer")
    floor = decision.get("venueFloorBps")
    if not isinstance(floor, int) or floor < 0:
        raise PolicyError("venueFloorBps must be a non-negative integer")
    if not str(decision.get("decisionClock", "")).strip():
        raise PolicyError("decisionClock must state the honest clock, and may not be blank")
    if not doc.get("features"):
        raise PolicyError("a policy without feature definitions is not executable")
    if not doc.get("model"):
        raise PolicyError("a policy without model parameters is not executable")
    tapes = doc.get("provenance", {}).get("tapes")
    if not tapes:
        raise PolicyError("a policy must carry the provenance of every tape behind it")
    honesty = doc.get("honesty", {})
    if honesty.get("oneTapeFitsNothing") != ONE_TAPE_FITS_NOTHING:
        raise PolicyError("the honesty block must quote the harness vocabulary verbatim")


def write_policy(path: str | Path, doc: dict) -> Path:
    validate_policy(doc)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return path
