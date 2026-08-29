# RESULT: survival by birth verdict — safety and longevity ORDER IN OPPOSITE DIRECTIONS

2026-08-29. Instrument: `studies/verdict_survival.py` (stages crossings/stats, cached under
`studies/data/verdict_survival/`). Registered in `studies/REGISTRATION_verdict_survival.md`
before any estimand was computed. Population: the 91,505 standard-BORN fresh coins
(2026-08-26..28) with an identified deployer; verdicts assigned causally from birth-time
panel features with score.py precedence (KNOWN_CREW 78,404 / CLEAN 8,773 / NOT_CLEAN 3,363 /
BUNDLED 965 — the live Jaccard crew arm has no panel column, disclosed in the registration;
KNOWN_CREW here is the three history arms). Cost: $0, all local.

**The headline: the verdict ordering for LIFETIME is the REVERSE of the ordering for
SAFETY, and both directions are strong.** BUNDLED coins — someone paid to be in the birth
slot, no known-crew record — are the longest-lived, most-graduating cohort AND the most
collapse-prone: 130× CLEAN's collapse rate, 71× CLEAN's graduation rate. CLEAN coins almost
never collapse (0.03% by 24h) and almost never go anywhere (0.19% graduate); the modal CLEAN
launch fades quietly inside six minutes. This is the exact sentence the screen card needs so
a reader stops hearing CLEAN as "will do well": CLEAN means nobody with a record is at the
table — including anyone who would push it.

Endpoint validity: resurrection rate 17.26% at G=1h, 9.33% at G=6h — under the registered
20%/both gate, so the QUIET(1h) endpoint stands (a sixth of coins do take a ≥1h nap and
trade again; the KM medians are robust to this because naps this long sit far above them).

## S1 — still trading at h (exposure-complete cohorts, Wilson 95%)

| verdict | alive at 1h | alive at 6h (n) | alive at 24h |
|---|---:|---:|---:|
| CLEAN | 25.2% | 16.4% [15.6, 17.3] (7,939) | 7.4% |
| BUNDLED | 32.7% | 20.7% [18.1, 23.5] (851) | 12.2% |
| KNOWN_CREW | 18.3% | 11.5% [11.3, 11.8] (69,872) | 5.3% |
| NOT_CLEAN | 26.2% | 16.0% [14.8, 17.4] (2,998) | 8.6% |

Deployer-clustered bootstrap (2,000 draws) on the registered pair differences at 6h:
CLEAN − BUNDLED = **−4.24%** [−7.19%, −1.45%]; CLEAN − KNOWN_CREW = **+4.91%**
[+3.95%, +5.91%]. Both CIs exclude 0.

## S2 — Kaplan–Meier time-to-quiet (G = 1h; censored at window end)

| verdict | KM median | IQR | per-day medians (26/27/28) |
|---|---:|---|---|
| CLEAN | 344 s | [24 s, 4,158 s] | 501 / 181 / 396 |
| BUNDLED | 618 s | [117 s, 9,700 s] | 571 / 786 / 515 |
| KNOWN_CREW | 184 s | [31 s, 1,333 s] | 184 / 183 / 185 |
| NOT_CLEAN | 343 s | [65 s, 4,812 s] | 363 / 307 / 371 |

BUNDLED > CLEAN on all three days (stable). CLEAN vs KNOWN_CREW flips on 08-27 by TWO
SECONDS (181 vs 183) — see the ship rule below.

## S3/S4 — collapse and graduation by 24h (24h-exposure-complete, Wilson 95%)

| verdict | collapse by 24h | graduate by 24h | n |
|---|---:|---:|---:|
| CLEAN | **0.03%** [0.01, 0.11] | 0.19% [0.11, 0.32] | 6,464 |
| BUNDLED | **3.89%** [2.71, 5.57] | **13.49%** [11.19, 16.18] | 719 |
| KNOWN_CREW | 0.94% [0.86, 1.03] | 2.72% [2.58, 2.86] | 52,282 |
| NOT_CLEAN | 0.70% [0.44, 1.12] | 4.53% [3.77, 5.43] | 2,429 |

The BUNDLED row is the market's honest bargain, measured: the birth-slot bundle marks
commitment — 13.5% graduate (71× CLEAN) — and it marks the rip capacity — 3.9% collapse
(130× CLEAN). Both tails fat, by construction of who bundles.

## Ship list (per the registered rule: n ≥ 500 both arms, 6h CI excludes 0, per-day S2 signs agree)

- **CLEAN vs BUNDLED: SHIPS** (all three conditions pass). Card sentences, numbers as
  printed:
  - CLEAN card: "CLEAN cohort (2026-08-26..28, n=8,773): median last trade 5.7 min after
    birth; 16.4% still trading at 6h; collapse by 24h 0.03%; graduation by 24h 0.19%.
    CLEAN measures the absence of known operators — quiet fade is the modal outcome."
  - BUNDLED card: "BUNDLED cohort (n=965): median last trade 10.3 min; 20.7% still trading
    at 6h; collapse by 24h 3.89% (130× CLEAN); graduation by 24h 13.49% (71× CLEAN). A
    birth bundle marks committed operators — both tails are fat."
- **CLEAN vs KNOWN_CREW: DOES NOT SHIP under the registered rule.** The alive-at-6h CI is
  solidly positive and the KNOWN_CREW per-day medians are the most stable in the table
  (184/183/185 s), but the registered stability check compares the PAIR's median signs and
  CLEAN's own 08-27 dip (181 s) flips it by 2 seconds. The rule is the rule; the sentence is
  held. A re-run on the next corpus pull with more days settles it cheaply — if the sign
  holds on ≥4 of 5 days there, re-register and ship.
- NOT_CLEAN was not a registered pair; its row is context in the tables above.

## Limitations / what would have falsified

Three days; 24h cells lose day-3 births to exposure-completeness (n columns say so).
Verdicts are panel reconstructions of the live gates (no Jaccard crew arm). The
resurrection rate (17.3%) means "last trade" undershoots true lifetime for a sixth of
coins — direction is conservative for the CLEAN-fades-quietly reading (some CLEANs live
longer than printed). Falsifiers registered in advance: per-day sign reversal (occurred
only for the CLEAN/KNOWN_CREW pair, which is therefore held), resurrection > 20% at both G
(did not occur), CLEAN n < 500 (did not occur).
