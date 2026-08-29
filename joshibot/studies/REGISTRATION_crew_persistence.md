# REGISTRATION: crew persistence across the gap — does the KNOWN_CREW arm's memory hold?

2026-08-29, registered BEFORE any cross-window estimand was computed. Instrument will be
`studies/crew_persistence.py`; caches to `studies/data/crew_persistence/`. Data: window A =
`studies/data/operator_crime/` (2026-08-05..14, standard-BORN, snipers.parquet +
coins.parquet + panel.parquet + ledger), window B = `studies/data/operator_crime_fresh/`
(2026-08-26..28, same artifacts). The two windows are separated by an 11-day unobserved gap
and the corpus-noted regime shift.

## Why this study

The shipping ledger (`dregg_screen/ledger.py`, 11k+ crew fingerprints) ASSUMES that a crew
seen in the corpus is still the same actor when it reappears live — an assumption validated
within-window (Jaccard 0.26 vs 0.0026 day-matched) but never ACROSS a gap. If fingerprints
decay on a failure-roster-like timescale (prior: that roster's half-life was ~2 days,
different population), the KNOWN_CREW arm silently degrades between biweekly rebuilds. This
study prices that decay and ships as (1) refresh-cadence guidance with a measured number and
(2) wire/crew-page content (recidivism rates with CIs). Chosen over (b)/(d) — reasons in
REGISTRATION_verdict_survival.md.

## Author-knowledge disclosure

I know the within-window crew result (0.26 vs 0.0026), the live match thresholds
(min_overlap = 2, min_jaccard = 0.10), that the combined ledger build simply unions the two
windows, and the failure-roster 2-day half-life prior. I have not computed any A→B overlap,
recidivism rate, or cross-window Jaccard.

## Registered estimands

P1 DEPLOYER RECIDIVISM. Share of window-B births (with identified deployer) whose deployer
   launched in window A; among those, the split by the A record (dirty := any A rip or A
   dump; clean-A otherwise). Outcome-conditional: P(B-coin collapse) and P(B-coin rip) for
   {dirty-A deployer, clean-A deployer, unseen deployer}, Wilson 95% CIs, deployer-clustered
   bootstrap for the dirty-vs-unseen difference. This is the cross-gap re-validation of the
   deployer_record gate.

P2 SNIPER PERSISTENCE LIFT. Among wallets active in window A, compare
   P(snipes in B | sniped in A) vs P(snipes in B | traded a pump coin in A, never sniped) —
   the lift isolates role persistence from mere activity persistence. Reported with the
   unique-wallet counts and a 95% CI on the ratio (bootstrap over wallets, 2,000 draws).
   Also: share of B birth-slot sniper incidences carried by A-known sniper wallets (the
   coverage number the sniper_prior_max gate actually depends on).

P3 CROSS-GAP CREW FINGERPRINT. For deployers with ≥ 2 A-coins and ≥ 1 B-coin (caps as in
   cmd_graph: ≤ 400 busiest such deployers, ≤ 25 A-coins each): best-match Jaccard of each
   B-coin's ex-deployer sniper set against the same deployer's per-A-coin sets — the exact
   statistic and unit the live ledger matches on. Controls, both reported: (i) day-matched
   different-deployer control (same B coins scored against a random OTHER qualifying
   deployer's A-sets, same count); (ii) curveball degree-preserving null (n = 200) shuffling
   the B-side sets' membership at fixed set sizes and wallet degrees. Also: the match rate
   at the LIVE thresholds (jaccard ≥ 0.10, overlap ≥ 2) for treatment vs control — the
   false-fingerprint rate the shipped product would emit.

P4 DECAY CURVE. Within window A: same-deployer coin-pair mean Jaccard binned by inter-birth
   gap {0–1d, 1–3d, 3–6d, 6–9d}; plus the A→B cell (12–23d) from P3. A monotone decay fit
   is descriptive only; the deliverable is the binned means with bootstrap CIs and the ratio
   of the A→B cell to the 0–1d cell (the "two-week retention" number).

## Structure-preserving discipline

No i.i.d. shuffle anywhere: the day-matched control preserves calendar structure, the
curveball null preserves both set sizes and wallet degrees, and all CIs cluster at the
deployer (P1, P3, P4) or wallet (P2) level. Both controls are reported side by side; only
effects that clear BOTH are claimed.

## Ship rule (fixed now)

- The refresh-cadence / crew-page claim ("fingerprints persist across ≥ 12 days") ships iff
  P3 treatment mean ≥ 5× the day-matched control AND curveball p ≤ 0.01 AND the live-threshold
  match rate in treatment ≥ 10× control.
- The recidivism sentence ships iff P1's dirty-A collapse CI excludes the unseen-deployer
  rate.
- If P3 fails, the deliverable is the decay result: the RESULT states the measured retention,
  the implied ledger half-life, and the recommended rebuild cadence — and the live crew-match
  reasons should then carry an age caveat. A negative here is a real product change, not a
  discard.

## Falsifiers

P3 treatment indistinguishable from the day-matched control (ratio < 2×) — the fingerprint
is a within-day artifact; P2 lift ≈ 1 — "sniper" is a transient role and sniper_prior_max
is memorizing activity, not identity; P1 recidivist share so small (< 1% of B births) that
the gate rarely fires cross-gap — then the arm's live value rests on within-window recency,
stated in the RESULT.
