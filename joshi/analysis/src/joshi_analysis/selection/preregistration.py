"""Frozen pre-registration for the operator-selection measurement.

This module is the pre-registration. It is deliberately a *separate file from any
result*, it contains no data-dependent branch, and every knob the scoring depends on
is a module-level constant fixed here before the instrument was ever pointed at a real
catalog. If a horizon, a fee floor, a set kind or a test changes, it changes here, in a
diff, with a date -- not silently inside an analysis that has already seen its outcome.

Read this before reading any number the instrument prints.


THE QUESTION
------------
When the operator looks at a scene and marks one candidate out of several, is the marked
candidate's forward move better than the moves of the candidates she passed over in that
same scene?

The comparison is *within a scene*: same instant, same choice set, same market. A move
that lifted everything lifts the chosen and the passed alike and cancels out. This is why
no market factor, beta or benchmark appears anywhere in the scoring -- the design controls
for market-wide movement by construction rather than by regression.


THE UNIT OF OBSERVATION IS THE SCENE, NOT THE ACT
-------------------------------------------------
If the operator marks three candidates in one eight-candidate scene, that is ONE selection
event with a chosen set of size three, not three events. The three acts share a choice set
and a market instant; counting them as independent observations would treble the apparent
sample and shrink every interval by sqrt(3) for free. Scenes are the independent unit.

A scene where every candidate was marked, or none was, carries no counterfactual and is
excluded -- and counted as excluded. See NO_COUNTERFACTUAL in the exclusion vocabulary.


THE CHOICE SET IS `viewport`, FALLING BACK TO `rendered`
--------------------------------------------------------
`scene_choice_member.set_kind` admits six nested sets: eligible, surfaced, rendered,
viewport, interacted, compared. Which one is the denominator is the single most consequential
choice in this design, and the flattering answer is the wrong one.

Scoring against `eligible` would credit the operator with passing over candidates she never
laid eyes on. Every coin the system considered and never drew becomes a "pass" she gets rank
credit for. That inflates measured skill for free.

The denominator is what she could actually see: `viewport` when the scene recorded one, else
`rendered`. Which was used is recorded per event in `SelectionEventV1.choice_set_kind`, so a
mixed corpus is visible rather than silently pooled.


LEAKAGE: TWO CLOCKS, AND THE CONSERVATIVE ONE WINS
---------------------------------------------------
A scene has a knowledge cutoff (the commit through which its contents were known) and an act
has an issue time. They are not the same instant and can be far apart -- in the first real
catalog examined, a scene rendered at 19:44:40 carried an act issued at 20:26:49, a 42-minute
gap.

The outcome window opens at the ACT's issue time, never at the scene's render time. The act is
when the decision locked; anything after it is fair, anything before it is leakage. Opening the
window at the (earlier) render time would hand the measurement free forward information.

The gap between the two is recorded as `staleness_us` on every event, because it is a quality
fact about the decision: a judgement made against a badly stale scene is less attributable to
that scene's contents. Staleness is REPORTED, never used to drop an event.


THE OUTCOME, AND WHAT COUNTS AS NOT HAVING ONE
-----------------------------------------------
Baseline leg: the candidate's price *in the decision scene itself* -- the number the operator
was looking at. Its market clock is the candidate's own `lastObservedAt`, which is at or before
the decision by construction, so the baseline cannot leak.

Forward leg: the same mint's price in a LATER durably retained scene, taken at the observation
whose market clock lands nearest the target horizon inside the tolerance band.

The market clock is the candidate's `lastObservedAt`, NOT the scene's `renderedAt`. A scene
rendered at noon can carry a price observed at 11:03; using the render time would date a stale
price to the present and manufacture returns out of rendering activity. (Joshi's own runbook is
explicit on this point: the ingest clock is the source's freshness, a clock inside a candidate is
a market clock, and they are not interchangeable.)

If either leg is missing the outcome is ABSENT. An absent outcome is recorded, counted and
reported. It is never zero-filled, and events carrying it are never dropped quietly. This matters
more than it sounds: the corpus lifecycle work measured that 77.1% of mints have three or fewer
minute-bars in their first hour, so absence is the common case, not the exception. Silently
dropping absent outcomes would restrict the sample to coins that stayed observable -- which is
itself an outcome, and a survivorship filter pointed the flattering way.


THE THREE STATISTICS, AND WHY THREE
------------------------------------
S1  DISCRIMINATION -- mean normalised within-scene rank of the chosen candidates.
    Under the null of no skill the chosen set is a uniformly random subset of the choice set,
    so its mean normalised rank is 0.5. Rank, not return, is the primary statistic on purpose:
    memecoin forward returns are violently heavy-tailed and a mean-difference test is decided by
    whichever single scene happened to contain the outlier. Rank is bounded, has an exact null,
    and answers "does she pick the better one" without asking "by how much".
    Fee-independent: both the chosen and the passed alternative would pay the same fee.

S2  WITHIN-SCENE EXCESS -- chosen mean log return minus passed mean log return.
    The size of the discrimination, in log return. Also fee-independent, for the same reason:
    the counterfactual to taking this coin is taking a different coin from the same scene, and
    that alternative pays the fee too. The fee cancels in the difference.

S3  TRADEABLE EDGE, NET OF THE FEE FLOOR -- chosen mean log return minus the round-trip fee floor.
    The counterfactual here is DIFFERENT: not trading at all, which costs nothing. So the fee does
    not cancel and must be paid. This is the only one of the three that answers "was this worth
    doing".

    S1 and S2 can be strongly positive while S3 is negative, and that combination is a real and
    likely outcome, not a pathology: it means the operator genuinely picks the best coin in the
    room and the room was not worth trading. The instrument must report that as SKILL WITHOUT A
    TRADEABLE EDGE and must not let a significant S1 be read as a green light. A selection edge
    smaller than the fee floor is not an edge.


NULL DISTRIBUTIONS
------------------
S1's null is exact and needs no asymptotics: permute which subset of each scene's choice set was
chosen, holding the scene's sizes fixed, and recompute. This is valid at any N, which matters
because N will start at zero and grow slowly.

S2 and S3 are reported with a fixed-seed bootstrap interval AND a sign test. The sign test is the
one to believe when N is small or a single scene dominates the mean.

All randomisation uses PERMUTATION_SEED. Results are byte-reproducible.
"""

from __future__ import annotations

from typing import Final

# --- identity -------------------------------------------------------------------------

PREREGISTRATION_ID: Final = "joshi.selection.preregistration.v1"
PREREGISTERED_ON: Final = "2026-08-23"

# --- the choice set -------------------------------------------------------------------

#: Denominator preference, most-restrictive first. The first set kind a scene actually
#: recorded wins. Never `eligible`: it contains candidates the operator never saw.
CHOICE_SET_KIND_PREFERENCE: Final = ("viewport", "rendered")

#: Subject kind that can be a selection. `record_focus` acts name the scene itself
#: (`subject_kind='scene'`) and are not selections; they are excluded and counted.
SELECTABLE_SUBJECT_KIND: Final = "candidate"

# --- horizons -------------------------------------------------------------------------

#: Forward horizons in seconds. FROZEN. No horizon may be added, removed or reordered
#: after any real result has been seen; doing so is horizon-shopping.
HORIZONS_SECONDS: Final = (300, 900, 3600, 14400)

#: A forward observation counts for horizon h if its market clock lands within
#: h * (1 +/- HORIZON_TOLERANCE_FRACTION) of the decision. Nearest-to-target wins.
HORIZON_TOLERANCE_FRACTION: Final = 0.20

#: The headline horizon. One horizon is the headline so that four cannot be searched for
#: the prettiest. The other three are reported alongside it, always, including when they
#: disagree with it.
PRIMARY_HORIZON_SECONDS: Final = 3600

# --- cost -----------------------------------------------------------------------------

#: Round-trip fee floor in basis points, measured live on three real mints (Study M0,
#: recorded in docs/implementation/S2_RUNBOOK.md): bonding curve 247 bps, graduated pool
#: 60 bps, freshly graduated pool 249 bps. The default is the bonding-curve figure because
#: hunt candidates are overwhelmingly pre-migration, and because "graduated" predicts
#: nothing -- a freshly graduated pool measured 249 bps, worse than the curve.
#:
#: This is a FLOOR. It is fees only. It excludes price impact at the operator's clip size,
#: state age (chain-to-receipt measured 11-13 s, and one pool drifted 9-10 bps in 30 s),
#: and the spread actually crossed. Real cost is higher. S3 clearing this floor is
#: necessary for a tradeable edge and nowhere near sufficient.
FEE_FLOOR_BPS_BONDING_CURVE: Final = 247
FEE_FLOOR_BPS_GRADUATED_POOL: Final = 60
FEE_FLOOR_BPS_GRADUATED_POOL_FRESH: Final = 249
DEFAULT_FEE_FLOOR_BPS: Final = FEE_FLOOR_BPS_BONDING_CURVE

# --- inference ------------------------------------------------------------------------

ALPHA: Final = 0.05
TARGET_POWER: Final = 0.80
PERMUTATION_DRAWS: Final = 20_000
BOOTSTRAP_DRAWS: Final = 20_000
PERMUTATION_SEED: Final = 20260823

#: S1 is two-sided: the honest prior admits that the operator may be systematically
#: choosing the *worse* candidate, and a one-sided test could not see it.
S1_SIDED: Final = 2
#: S3 is one-sided: the only question that matters is whether the edge clears the floor.
S3_SIDED: Final = 1

# --- exclusion vocabulary -------------------------------------------------------------

#: Every act and scene the instrument declines to score lands in exactly one of these and
#: is counted. Nothing is dropped without appearing in this census.
EXCLUSION_ACT_NOT_SUBJECT_BOUND: Final = "act_names_no_candidate"
EXCLUSION_ACT_NO_SCENE: Final = "act_bound_to_no_scene"
EXCLUSION_ACT_SUBJECT_OFF_CHOICE_SET: Final = "act_subject_absent_from_choice_set"
EXCLUSION_SCENE_NO_CHOICE_SET: Final = "scene_recorded_no_choice_set"
EXCLUSION_NO_COUNTERFACTUAL: Final = "scene_chosen_set_is_whole_choice_set"

#: An event that reconstructs cleanly but has no measurable outcome. This is an OUTCOME
#: state, not an exclusion: the event is real, it is counted in N_events, and it is absent
#: from N_scored. Reporting these two numbers separately is the entire point.
OUTCOME_ABSENT_NO_BASELINE: Final = "no_baseline_price_in_decision_scene"
OUTCOME_ABSENT_NO_FORWARD: Final = "no_forward_price_within_horizon_band"
OUTCOME_ABSENT_NO_PASSED: Final = "no_passed_candidate_scored"
OUTCOME_PRESENT: Final = "scored"
