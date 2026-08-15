"""The standing paper desk: three books, one accounting, one ledger.

WHY THIS EXISTS
---------------
Every strategy in this repo has been tested once, by a bespoke study, under its own
rules. ``board_entry`` marked positions one way and ``bandit_search`` another;
``lp_strategy`` priced friction in USD while ``probe`` priced it in lamports; each ran
over a different window and none of them persisted anything past the afternoon it ran.
So the operator's actual question -- *is the short horizon, the medium horizon, or the
toll (LP) position the better use of the same SOL?* -- has never been asked, because the
three have never once been measured against each other under identical rules.

This package is that comparison, made standing. Three books:

* **SHORT** (minutes-hours) -- boards / firehose / callout candidates, bracket exits.
* **MEDIUM** (hours-days) -- the held cluster plus boards survivors, deterioration exits.
* **TOLL** (a paper LP book) -- DLMM ranges gated on ``eta * D > VR``, fees accrued only
  from swap flow actually observed crossing the paper range.

They share ONE bankroll size, ONE friction model, ONE ledger and ONE clock discipline, so
the cross-book table is a comparison rather than three incomparable numbers side by side.

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
    """The three horizons. Identical capital, identical friction, one ledger."""

    SHORT = "short"
    MEDIUM = "medium"
    TOLL = "toll"


BOOKS: tuple[Book, ...] = (Book.SHORT, Book.MEDIUM, Book.TOLL)
