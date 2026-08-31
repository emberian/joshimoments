"""dregg_record — THE CALLOUT RECORD: the un-gameable caller ledger.

The archive (dregg_archive) keeps every callout from the moment it was first
witnessed, prices every call from OUR retained candles at the callout's own
clock, and files a removal verdict when the provider's board quietly loses one.
This package turns that into the product's signature surface: per-caller records
that cannot be edited by the people they describe.

Four modules, one direction of flow:

    records.py  -> leaderboard.py -> lookup.py / post.py
    (aggregate)    (rank + render)   (DM card)   (weekly post via approvals)

The framing is measured and it is the edge (studies/RESULT_callout_edge.md):
buying the callout feed averaged -11.9% at 1h and -43.6% at 8h, and shuffling
caller identity matched or beat the real assignment 24/24 — "who called it"
carried no measured skill. So this is a RECORD, never a tipster ranking: every
rendered surface carries the standing line, provider multiples appear only as
labeled claims, and ranks come from our measured outcomes with a minimum-n gate.

Why deletion cannot game it: a callout is archived at first sighting and its
outcome is computed from candles we retained, so a caller deleting a bad call
removes NOTHING from their stats — it adds a published removal verdict, which
every record renders beside the numbers.
"""
