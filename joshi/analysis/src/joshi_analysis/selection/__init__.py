"""Measure the operator's own selection: what she chose, against what she passed over.

Everything measured so far says the edge is not in the obvious places. What has never been
measured is the operator's own picking. Joshi already retains the raw material -- an act
binds to a scene, the scene's view bytes are durably kept, and the scene's choice set
reconstructs from them -- so the counterfactual "she took this one and passed those" is
answerable from bytes that already exist.

    preregistration  the frozen scoring rule. Read it first.
    events           reconstruct SelectionEventV1 from a catalog, read-only
    outcomes         forward returns measured only on post-act data; absence is a result
    score            S1 discrimination / S2 within-scene excess / S3 tradeable net of fees
    power            how many decisions are needed before any of this is answerable
    report           render the whole thing

Run it:  uv run --offline python -m joshi_analysis.selection <catalog.sqlite> [...]
"""

from __future__ import annotations

from .events import (
    ActRef,
    CandidateRef,
    ReconstructionCensus,
    SelectionEventV1,
    reconstruct_catalog,
    reconstruct_many,
)
from .outcomes import (
    CandidateOutcome,
    EventOutcomeV1,
    ForwardPriceIndex,
    build_price_index,
    measure_all,
    measure_event,
)
from .power import PowerStatementV1, power_statement, render_power_statement
from .report import SelectionReportV1, build_report, render_report
from .score import SceneStatistic, SelectionScoreV1, score

__all__ = [
    "ActRef",
    "CandidateOutcome",
    "CandidateRef",
    "EventOutcomeV1",
    "ForwardPriceIndex",
    "PowerStatementV1",
    "ReconstructionCensus",
    "SceneStatistic",
    "SelectionEventV1",
    "SelectionReportV1",
    "SelectionScoreV1",
    "build_price_index",
    "build_report",
    "measure_all",
    "measure_event",
    "power_statement",
    "reconstruct_catalog",
    "reconstruct_many",
    "render_power_statement",
    "render_report",
    "score",
]
