"""Earlier-only deterministic analog memory.

The module is deliberately independent of the operational store and provider clients. It accepts
already materialized point-in-time records and returns canonical decision-mode artifacts. Outcome
reveal is an explicit, separate retrospective artifact.
"""

from .core import (
    AnalogArtifact,
    DecisionRecord,
    DistanceSpec,
    FeatureObservation,
    FilterObservation,
    FilterSpec,
    MissingPolicy,
    Neighbor,
    OutcomeClosure,
    OutcomeClosureStatus,
    PlainFilterArtifact,
    RetrospectiveReveal,
    retrieve,
    reveal_outcomes,
    run_plain_filter,
)

__all__ = [
    "AnalogArtifact",
    "DecisionRecord",
    "DistanceSpec",
    "FeatureObservation",
    "FilterObservation",
    "FilterSpec",
    "MissingPolicy",
    "Neighbor",
    "OutcomeClosure",
    "OutcomeClosureStatus",
    "PlainFilterArtifact",
    "RetrospectiveReveal",
    "retrieve",
    "reveal_outcomes",
    "run_plain_filter",
]
