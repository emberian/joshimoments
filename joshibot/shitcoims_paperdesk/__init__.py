"""The standing paper desk: five books, one accounting, one ledger.

WHY THIS EXISTS
---------------
Every strategy in this repo has been tested once, by a bespoke study, under its own
rules. ``board_entry`` marked positions one way and ``bandit_search`` another;
``lp_strategy`` priced friction in USD while ``probe`` priced it in lamports; each ran
over a different window and none of them persisted anything past the afternoon it ran.
So the operator's actual question -- *is the short horizon, the medium horizon, or the
toll (LP) position the better use of the same SOL?* -- has never been asked, because the
three have never once been measured against each other under identical rules.

This package is that comparison, made standing. Five books:

* **SHORT** (minutes-hours) -- boards / firehose / callout candidates, bracket exits.
* **MEDIUM** (hours-days) -- the held cluster plus boards survivors, deterioration exits.
* **TOLL** (a paper LP book) -- DLMM ranges gated on ``eta * D > VR``, fees accrued only
  from swap flow actually observed crossing the paper range.
* **WIGGLE** (minutes, and *only* minutes) -- post-collapse bottom scalps on a HARD CLOCK.
  The operator's own measured pattern, and the one book whose exit rule is a discipline
  rather than a forecast; see :mod:`shitcoims_paperdesk.wiggle` for why it refuses to hold.
* **OPERATOR** -- the wiggle book's execution with the operator's own gesture in place of
  BOTH its entry rule and its clock: they pick the coin, and they decide when to leave.
  See below.

They share ONE bankroll size, ONE friction model, ONE ledger and ONE clock discipline, so
the cross-book table is a comparison rather than five incomparable numbers side by side.

THE FIFTH BOOK IS AN EXPERIMENT ABOUT THE OPERATOR, AND IT IS THE ONLY ONE WITH A PRIOR
---------------------------------------------------------------------------------------
Every entry-selection study in this tree returned null. The one repeatedly-positive signal
is the operator's own choosing: over the same pattern and the same clock, the rule-chosen
wiggle book's first closes ran **-14.08%** while the operator's hand-picked equivalents
measured **+3.14%**. The difference between those two numbers is not a threshold. It is
whatever the operator is doing when they look at a chart and say *"this one is gonna wiggle
for a bit"*, and until now nothing in this repo recorded it.

The OPERATOR book records it. Execution, friction, sizing, marking, censoring, the brackets
and the close-row builder are the WIGGLE book's, inherited rather than reimplemented,
because two arms are only comparable if everything downstream of the decision is the same
code. TWO things differ, and both are the operator:

* **the entry** -- the gates are computed and LOGGED but gate nothing, because the gesture
  IS the entry signal. Propensity 1.0, source ``operator``: their policy is exogenous to
  this desk, so this is a treatment arm and not an off-policy estimate.
* **the exit** -- their ZAP, not a clock. The wiggle book's five minutes is where their
  exits happened to LAND, not a rule they follow (*"i watch it closely, and pull out the
  position whenever i feel like it"*), so this book holds until they pull out, with a
  20-40 minute backstop behind that. The zap carries the instrument state at the moment of
  the exit, which is the training set for a reactive exit policy nobody has ever recorded.

See :mod:`shitcoims_paperdesk.operator`.

WHAT MAKES IT AN EXPERIMENT RATHER THAN A DIARY
-----------------------------------------------
Every decision is propensity-logged at decision time against the real
:class:`shitcoims_tape.schema.PropensityRecord`, with jittered thresholds and an
epsilon-explore flip, exactly as ``shitcoims_scalper.policy`` does. That is the thing the
observational board tape never had and the reason ``studies/bandit_search.py`` had to
fall back on a simulator: nobody had recorded the probability that generated an action,
so nothing could be reweighted. The desk generates its own propensities, which makes the
ledger a designed experiment scoreable by ``shitcoims_replay.ope`` -- including on the
counterfactual thresholds nobody chose.

THE ACCOUNTING RULES, WHICH ARE NOT NEGOTIABLE
----------------------------------------------
Every one was paid for by a wrong number that shipped:

1. **Entries fill at the NEXT observation after the decision; exits at the FIRST
   observation after the trigger.** A fill at the snapshot that produced the decision is
   lookahead, and lookahead is where paper returns come from.
2. **Censoring is priced, never dropped.** ``studies/RESULT_board_entry.md`` reported
   +21.77% over 8h; repriced with the censored 96% marked out at their last observed
   price it is **-12.24%**. Every close row therefore carries both the marked-out P&L and
   the pessimistic total-loss P&L, and the report prints both.
3. **One close-row builder, no exceptions.** Nine drain rows missing ``spend_lamports``
   once made a report print -151%. A partial row is worse than no row: it looks like data.
4. **Two clocks on every row.** ``t_ingest`` is ours; ``t_event`` is the source's and is
   explicitly ``null`` with a reason when the source has none -- the firehose carries no
   event clock by construction, and that is a fact to record, not a gap to fill in.
5. **Watch windows.** Absence of data and absence of events are different states, and a
   desk that cannot tell them apart reports a cold collector as a quiet market.
"""

from __future__ import annotations

__all__ = ["BOOKS", "Book"]

from enum import StrEnum


class Book(StrEnum):
    """The horizons. Identical capital, identical friction, one ledger.

    WIGGLE is not a fourth horizon so much as a fourth *discipline*, and the distinction is
    the point: SHORT, MEDIUM and TOLL all decide when to leave by asking what the position
    is doing, and WIGGLE decides by asking what time it is. The operator's own trades say
    those are two populations wanting two rules, and a desk that ran one rule over both
    would answer neither question.

    OPERATOR is WIGGLE's machinery with the operator in both decision seats: they choose the
    coin, and they choose when to leave. Everything between those two choices -- sizing,
    friction, filling, marking, censoring, the close row -- is the same code, which is the
    only reason the two books' P&L can be put in the same table at all.
    """

    SHORT = "short"
    MEDIUM = "medium"
    TOLL = "toll"
    WIGGLE = "wiggle"
    OPERATOR = "operator"


BOOKS: tuple[Book, ...] = (Book.SHORT, Book.MEDIUM, Book.TOLL, Book.WIGGLE, Book.OPERATOR)
