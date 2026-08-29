# RESULT: crew persistence across the gap — the ledger's memory HOLDS (93% two-week retention)

2026-08-29. Instrument: `studies/crew_persistence.py` (stages traders/p1/p2/p3/p4, cached
under `studies/data/crew_persistence/`). Registered in
`studies/REGISTRATION_crew_persistence.md` before any cross-window estimand was computed.
Window A = 2026-08-05..14 (266,928 births), window B = 2026-08-26..28 (91,505
deployer-identified births), 11 unobserved days between. Cost: $0, all local.

**The one-line verdict: every persistence claim the shipping KNOWN_CREW arm depends on
passes its registered gate, decisively.** The failure-roster prior (2-day half-life) does
NOT transfer to crews: crew fingerprints retain **93.2%** of their same-day overlap across a
12–23 day gap, sniper wallets keep their role at **19.1×** the activity-matched base rate,
and 40.4% of all fresh births come from deployers already in the corpus. The biweekly
ledger rebuild cadence is adequate and crew-match reasons need no age caveat.

## P1 — deployer recidivism, and the inversion holds cross-gap

40.36% of window-B births (36,932/91,505) have a deployer who launched in window A.
Outcomes of their fresh coins:

| deployer group | n | collapse [Wilson 95%] | rip |
|---|---:|---|---:|
| dirty-A (prior A rip/dump) | 34,840 | 0.574% [0.500%, 0.659%] | 0.568% |
| clean-A (A record, no dump) | 2,092 | 0.191% [0.074%, 0.491%] | 0.143% |
| unseen (no A record) | 54,573 | 1.032% [0.950%, 1.120%] | 0.517% |

dirty-A − unseen collapse difference: **−0.458%** [95% deployer-clustered −0.607%, −0.314%].
The registered gate (dirty-A CI excludes the unseen rate) PASSES — with the sign INVERTED
relative to the folk reading, exactly as the standard arm found in-window ("no record =
first-timer = the risk"): a deployer with a two-week-old dirty record is HALF as
collapse-prone as an unseen one. The KNOWN_CREW verdict names the actor; it does not claim
the coin dies — the survival study (RESULT_verdict_survival.md) carries that side.

## P2 — sniper role persistence

- P(snipes in B | sniped in A) = 6.320% (5,908 of 93,481 wallets)
- P(snipes in B | traded in A, never sniped) = 0.331% (8,039 of 2,428,635 wallets)
- **Lift 19.1× [95% boot 18.5, 19.7]** — role persistence, not activity persistence.
- **54.97% of window-B birth-slot sniper incidences are carried by A-known sniper wallets**
  — after 11 dark days, the `sniper_prior_max` gate's memory still covers over half the
  incidence mass.

## P3 — the cross-gap crew fingerprint (the product-critical number)

Arm: the 400 busiest of 1,995 deployers with ≥2 A-coins and ≥1 B-coin; 25,570 B coins
scored with the live ledger's own statistic (best-match ex-deployer birth-slot Jaccard
against the deployer's per-A-coin sets).

| | treatment (own A fingerprint) | control (random other deployer's A-sets) |
|---|---:|---:|
| mean best-match Jaccard | **0.3799** | 0.0119 |
| live-threshold match rate (J ≥ 0.10, overlap ≥ 2) | **48.51%** | 0.59% |

Ratio 32.0× (gate: ≥ 5×). Curveball degree-preserving null (n = 200): mean 0.0286,
**p = 0.0000**, effect 13.3× (gate: p ≤ 0.01). Live-threshold rate ratio 82× (gate: ≥ 10×).
**All three registered legs PASS.** Read plainly: when a corpus deployer launches again two
weeks later, the live ledger recognizes the crew on nearly half of the coins, and would
false-match a stranger 0.59% of the time.

## P4 — decay, and the compositional trap the registration walked into on purpose

Within-A same-deployer pair Jaccard by inter-birth gap (deployer-clustered 95% CIs):

| gap | n pairs | mean Jaccard |
|---|---:|---|
| 0–1d | 106,586 | 0.2931 [0.2592, 0.3263] |
| 1–3d | 11,215 | 0.2248 [0.1702, 0.2831] |
| 3–6d | 1,929 | 0.1251 [0.0187, 0.2580] |
| 6–9d | 180 | 0.0109 [0.0000, 0.0978] |
| **A→B, 12–23d (same arm, cross-window)** | **639,250** | **0.2732 [0.2235, 0.3199]** |

The within-A bins LOOK like fast decay — and the A→B cell refutes that reading: the same
busiest-400 arm retains **0.2732/0.2931 = 93.2%** of its 0–1d overlap across two-plus
weeks. The long-gap within-A bins are populated by a DIFFERENT deployer composition (slow
sporadic launchers with tiny n; the busy fleets launch batches within a day and so never
enter the 6–9d bin), which is why the registration pre-committed to the A→B/0–1d ratio as
the retention number rather than a fitted half-life. Fingerprints are stable; the apparent
decay was selection.

## Ship list

1. **Refresh-cadence claim (ships)**: the biweekly corpus pull + ledger rebuild is
   validated as adequate; no age caveat on crew-match reasons. (Ops doc note, not UI.)
2. **Crew page / wire sentence (ships)**: "Crew fingerprints are durable: across an 11-day
   gap, the 400 busiest returning deployers' new launches matched their own recorded crew
   48.5% of the time at live thresholds (strangers: 0.59%); fingerprint overlap retains 93%
   of its same-day strength after two weeks."
3. **Wire recidivism fact (ships, inverted sign stated)**: "40.4% of this window's births
   came from deployers already on record two weeks ago. The risk concentrates in the
   UNSEEN: no-record deployers' coins collapsed 1.03% vs 0.57% for known-dirty ones — no
   record is the risk factor, again."
4. P2's 55% incidence-coverage number belongs in the ledger build log / heartbeat as a
   standing coverage metric (how much of today's sniper mass the ledger has seen before).

## Limitations / falsifiers

P1's collapse outcome inherits the standard arm's k_std pricing; the third stratum flagged
post-recon (docs/MAYHEM_MODE.md §5: 4.292-SOL-seed non-mayhem coins inside the 1e15
population, unknown birth share) overstates a slice of those market caps ~7x. P2/P3/P4 are
price-free and unaffected.

One gap length (11 dark days) — the retention curve beyond ~3 weeks is unmeasured; the
registered falsifiers (treatment < 2× control; P2 lift ≈ 1; recidivist share < 1%) all
failed to occur by wide margins. The B window post-dates the regime shift, so persistence
survived at least this one regime boundary; a future shift is not covered by this result.
