"""Measured verdict-survival copy, shared by every Telegram surface that shows verdicts.

Source of truth (registered studies; their ship lists carry these exact sentences):

* ``studies/RESULT_verdict_survival.md`` — safety and longevity order in OPPOSITE
  directions. BUNDLED coins outlive CLEAN ones and fatten both tails; the modal CLEAN
  launch fades quietly inside six minutes. The whole point of this module is that a
  reader must never hear CLEAN as "likely to go up" — CLEAN means nobody with a record
  is at the table, including anyone who would push it.
* ``studies/RESULT_mayhem_arm.md`` (revised) + ``docs/MAYHEM_MODE.md`` — the mayhem
  stratum stays unscored, now as a measurement: crew fingerprints do not exist there,
  deployer history inverts, and every registered gate conjunction admits a set with MORE
  real rips than the stratum base. The mechanism is pump.fun's own global vault trading
  into every mayhem coin's curve and re-marking the price for the first 24h. Only
  REAL-FLOW numbers ship for this stratum; the price-path rates were demoted as artifacts.
* ``studies/RESULT_crew_persistence.md`` — the crew ledger's memory holds across weeks,
  and the risk concentrates in the UNSEEN deployer, not the known-dirty one.

Held, deliberately absent: the CLEAN-vs-KNOWN_CREW lifetime comparison missed one
registered per-day sign check and DOES NOT SHIP — no sentence here may claim CLEAN
outlives KNOWN-CREW (or the reverse). Each cohort's own numbers are fine; the pair
ordering is not, until a longer window re-registers it.

Every sentence carries its window and n. Plain text only — these strings ride surfaces
with no parse_mode. No method vocabulary (the copy-invariants jargon blacklist bites).
"""

from __future__ import annotations

# -- verdict survival (standard-born launches; RESULT_verdict_survival.md ship list) ---

CLEAN_SURVIVAL = (
    "CLEAN cohort (2026-08-26..28, n=8,773): median last trade 5.7 min after birth; "
    "16.4% still trading at 6h; collapse by 24h 0.03%; graduation by 24h 0.19%. "
    "CLEAN measures the absence of known operators — quiet fade is the modal outcome."
)

CLEAN_NOT_A_BUY_SIGNAL = (
    "CLEAN means nobody with a record is at the table — including anyone who would "
    "push it. It is not a prediction the price goes up."
)

BUNDLED_SURVIVAL = (
    "BUNDLED cohort (2026-08-26..28, n=965): median last trade 10.3 min; 20.7% still "
    "trading at 6h; collapse by 24h 3.89% (130x CLEAN); graduation by 24h 13.49% "
    "(71x CLEAN). A birth bundle marks committed operators — both tails are fat."
)

KNOWN_CREW_CONTEXT = (
    "KNOWN-CREW is the screen's most common verdict — 85.7% of the 91,505 fresh "
    "launches of 2026-08-26..28 had a tracked wallet in the room. It names the actor; "
    "it does not predict the coin's path. Most of these just die fast: median last "
    "trade 184 seconds after birth."
)

# -- the mayhem stratum (RESULT_mayhem_arm.md section 6 + docs/MAYHEM_MODE.md) ---------
# Group facts about ALL mayhem launches, never a score for one coin — every renderer
# that shows these numbers must keep them labeled as group facts (the full paragraph
# ships only in the archive edition; cards carry MAYHEM_CARD_GROUP_FACTS below).
# REAL-FLOW numbers only: the study's revision demoted every price-path rate on this
# stratum (collapse/rip/peak) as artifacts of administered pricing, so none of those
# may be quoted as market facts.

MAYHEM_MECHANISM = (
    "Mayhem launches mint double supply: half goes on a normal curve, half into a "
    "vault pump.fun itself operates — the same vault address on every mayhem coin. "
    "An automated, fee-exempt agent starts selling that vault into the coin's curve "
    "a median 2 seconds after birth and re-marks the quoted price as it trades (at "
    "roughly 500x the trade's real size), so for the first 24 hours the number you "
    "see is administered, not discovered. Unsold vault tokens burn at the 24-hour "
    "mark."
)

MAYHEM_STRATUM_FACTS = (
    "Facts about ALL mayhem launches as a group (2026-08-26..28, n=30,831), never a "
    "score for this coin: insider dump 94%; the typical coin's whole human audience "
    "is 4 wallets; only 7% see any human trade after the 24h burn; birth bundles "
    "and crew fingerprints are essentially absent here. Our screen's checks were "
    "built for a crew-and-deployer economy that does not operate in mayhem — tested "
    "there, they pick the wrong coins — so mayhem launches stay unscored on purpose."
)

# -- crew-ledger persistence (RESULT_crew_persistence.md ship list) --------------------

CREW_PERSISTENCE = (
    "Crew fingerprints are durable: across an 11-day gap (record 2026-08-05..14, "
    "fresh launches 2026-08-26..28), the 400 busiest returning deployers' new "
    "launches matched their own recorded crew 48.5% of the time (strangers: 0.59%); "
    "fingerprint overlap keeps 93% of its same-day strength after two weeks."
)

UNSEEN_RISK = (
    "40.4% of that window's births came from deployers already on record two weeks "
    "earlier — and the risk concentrates in the UNSEEN: no-record deployers' coins "
    "collapsed 1.03% vs 0.57% for known-dirty ones. No record is the risk factor."
)

# -- compact renderings for space-capped surfaces --------------------------------------
#
# THE RELEVANCE RULE (Gricean, 2026-08-29): a recurring broadcast surface carries a
# gloss ONLY where the misreading it prevents can actually happen on that surface —
# beside a listed CLEAN, on a card that names an actor. The full measured sentences
# live in exactly two standing places (the wire's markdown/archive edition and the
# /screen card, which answers a question about one coin); recurring surfaces point,
# they do not restate. The old hourly/daily restatements (DIGEST_SURVIVAL_NOTE,
# WIRE_VERDICT_FOOTER_LINES, CREW_WIRE_COMPACT) were deleted, not moved: repeating a
# true sentence every hour teaches readers to skip it.

#: One line for the momentum feed's photo caption (1024-char cap; keep this under 63
#: chars so six worst-case coin lines plus header and standing line still fit). Also
#: rides the wire's Telegram edition beside its notable-CLEANs list — the one spot in
#: that message where CLEAN could be read as a pick.
CLEAN_FEED_GLOSS = "CLEAN = no known operators at birth, not a price call."

#: The mayhem group base rates a /screen card owes its reader, compressed to the two
#: numbers that change a decision. The full stratum paragraph (MAYHEM_STRATUM_FACTS)
#: stays in the wire's archive edition and the research page; the card carries the
#: mechanism (about THIS coin's quoted price) plus this line, labeled as group facts.
MAYHEM_CARD_GROUP_FACTS = (
    "As a group (all 30,831 mayhem launches of 2026-08-26..28 — never a score for "
    "this coin): insider dump 94%, and the typical coin's whole human audience is "
    "4 wallets."
)

#: A day-window percentage needs at least this many launches behind it before any
#: surface may print it; below the floor the counts stand alone. At the screen's
#: 8.5% long-run admit rate, 20 launches is where a day-rate stops being integer
#: noise dressed as a measurement.
RATE_FLOOR_N = 20


def is_mayhem_row(row: dict) -> bool:
    """Whether a score row belongs to the mayhem stratum, from its own trail.

    A vendor mayhem flag that hydration DISPROVED (standard 1e15 curve confirmed)
    clears both the population note and the reasons, so such a row is honestly
    standard here — only the note, the policy reason, or a hydrated 2e15 mint mark
    the stratum.
    """

    reasons = [str(r) for r in row.get("reasons") or []]
    if any(r.startswith("policy:mayhem_flag") for r in reasons):
        return True
    if any(r.startswith("nonstandard_curve:minted_raw=2000000000000000") for r in reasons):
        return True
    notes = [str(n) for n in row.get("population_notes") or []]
    return any(n.startswith("vendor_flag:is_mayhem_mode") for n in notes)


def verdict_context(row: dict) -> list[str]:
    """The survival/stratum paragraph(s) a verdict card owes its reader, or [].

    Mayhem rows get the stratum mechanism INSTEAD of a cohort sentence: the cohort
    numbers were measured on standard-born launches and do not transfer, whatever
    verdict the live screen managed to assign from history alone. The card gets the
    compact group-facts line, not the full stratum paragraph — the two numbers that
    change a decision, labeled as group rates; the rest lives in the archive edition
    and the research page.
    """

    if is_mayhem_row(row):
        return [MAYHEM_MECHANISM, MAYHEM_CARD_GROUP_FACTS]
    verdict = str(row.get("verdict") or "")
    if verdict == "CLEAN":
        return [CLEAN_SURVIVAL, CLEAN_NOT_A_BUY_SIGNAL]
    if verdict == "BUNDLED":
        return [BUNDLED_SURVIVAL]
    if verdict == "KNOWN_CREW":
        return [KNOWN_CREW_CONTEXT]
    return []
