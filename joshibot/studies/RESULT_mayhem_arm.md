# RESULT: the mayhem arm — the stratum stays UNSCORED, and now we know exactly why

2026-08-29. Instrument: `studies/mayhem_arm.py` (stages census/roles/constants/build/screen/
graph, cached under `studies/data/mayhem_arm/`). Registered in
`studies/REGISTRATION_mayhem_arm.md` before any estimand was computed. Window: the fresh
corpus 2026-08-26..28 via `studies/data/operator_crime_fresh/`; causal history seeded from
2026-08-05..14. Cost: $0 (no BigQuery — the local stratum is 30,831 coins, six times the
registered 5,000-coin floor, so no pull was considered and no dry-run was needed).

**The one-line verdict: the registered ship rule FAILS on three of five conditions — the
mayhem stratum stays honestly UNSCORED, and the negative is now a measurement, not a
policy.** The screen's five gates, transplanted with every correction the registration
demanded (true curve identification, true 2e15 denominator, causal cross-window history),
are ANTI-selective in this stratum: mayhem-CLEAN admits coins that collapse at 4.45% against
a 2.67% stratum base rate. The features the standard arm rides do not exist here (bundling:
0.53% vs 44.17% standard — 83× rarer; crew fingerprints: same-deployer Jaccard 0.0011 ≈
curveball null 0.0010, p = 0.43) or point backwards (dirty-history deployers are SAFER,
risk ratio 0.47× [0.31, 0.74]). No threshold re-tuning fixes a stratum whose risk mechanism
is a different actor — see §3.

**And the different actor is pump.fun itself.** The stratum's defining mechanism, measured:
every mayhem create mints 2e15 raw; exactly 1e15 goes onto a BONE-STANDARD bonding curve
(k = 3.219e25 confirmed three independent ways) and exactly 1e15 goes to ONE GLOBAL VAULT —
`BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s`, the same account on all 30,831 coins — which
begins transferring tokens into the curve a median of **2 seconds** after birth (p10 1 s,
p90 11 s) and, for the median coin, feeds out its **entire** 1e15 in-window (mean 70.8%).
96.0% of its 1.2M outflow rows are exact-amount same-transaction transfers into the curve
account; 4.0% go elsewhere. The birth-slot sniper-crew economy that the screen fingerprints
simply does not operate where the protocol is the whale.

---

## 1. Census (M1)

| day | standard (1e15) | mayhem (2e15) | mayhem share |
|---|---:|---:|---:|
| 2026-08-26 | 35,280 | 11,051 | 23.85% |
| 2026-08-27 | 35,879 | 10,213 | 22.16% |
| 2026-08-28 | 28,021 | 8,071 | 22.36% |
| **pooled** | **104,380** | **30,831** | **22.80%** |

The live telemetry's "28–44% of the stream" is an hour-of-day figure; the corpus-wide share
is 22.8%. Residual nonstandard first-tx nets are dominated by minted_raw = 0 (n = 81,744:
pre-window coins whose first observed transaction is a trade — expected, not mayhem) plus
174 one-legged 1e18/9-decimal impostors; full table in `census.json`.

## 2. Roles and constants (M2, M3) — H1 confirmed, with one registered rule superseded

- The derived bonding-curve PDA (seeds `["bonding-curve", mint]`) appears among the birth
  legs of **30,831/30,831 (100.00%)** mayhem creates — curve identification is exact and
  deterministic. **Deviation, disclosed**: the REGISTERED touch-rule heuristic agreed with
  the PDA on only 92.51% — BELOW its own 95% bar. The PDA derivation (stronger than the
  registered firehose-key validation, which covers 0 corpus days) replaced it as primary;
  had we shipped on the touch rule alone we'd have mis-assigned ~7.5% of curves. The
  corpus's rank-1-leg `curve_owner` is wrong for essentially every mayhem coin with a dev
  buy, as predicted — nothing built on `birth.parquet` roles may be reused for this stratum.
- Exact-1e15 reserve leg: 30,831/30,831. `curve_seed = 1e15 − dev_buy`: 30,831/30,831.
  n_birth_legs = 3 on 30,828 (2 on the 3 zero-dev-buy coins).
- Constants, three independent confirmations of the standard curve: (a) 32/32 vendor mayhem
  create frames satisfy `vTok + initialBuy = 1.073e9` and `vSol − sol = 30.0` exactly;
  (b) graduated mayhem coins' median peak mcap on the circulating basis is **410.9 SOL**
  (the standard-curve calibration constant is ~411); (c) median last-live curve balance is
  **exactly 2.069e14** (the standard migration holdback). Registered check M3(a) (boards
  snapshot join) was unavailable — the boards tape ends 2026-08-23 — and is disclosed as
  such; (b) and (c) are stronger than the snapshot join would have been.
- So pricing uses k = 3.219e25, offset = 7.3e13; `mcap_circ = price × 1e15` (primary),
  `mcap_total = price × 2e15` (secondary). The screen's cheap-feature trap is confirmed
  quantitatively: a live `dev_buy_share` computed against 1e15 overstates the true share 2×.
- **The vault is one address across all mayhem coins** — and it is the address the vendor
  emits as `bondingCurveKey` on a fraction of mayhem frames (10/32 today; the other 22 carry
  the real per-mint PDA). A hydrator that trusted the vendor key would read the wrong
  account on those frames; ours derives the PDA, so no change needed — but it is now a
  documented vendor failure mode.

## 3. Outcomes (M4) — the stratum against the standard arm, same window

| quantity | standard (n=104,380) | mayhem (n=30,831) | ratio |
|---|---:|---:|---:|
| graduated | 2.46% | 4.13% | 1.7× |
| insider dump (80% disposal) | 75.79% | 94.38% | 1.25× |
| RIP (all four conditions) | 0.507% | 1.304% | 2.6× |
| collapse (≥90% from ≥100 SOL peak) | 0.781% | 2.673% | **3.4×** |
| peak ≥ 100 SOL | 8.12% | 9.44% (circ) | 1.2× |
| bundled at birth (n_snipers ≥ 2) | 44.17% | **0.53%** | 1/83× |

Day-08-26-only (max exposure): grad 5.23%, rip 0.935%, collapse 1.981% — same shape, so the
pooled numbers are not a censoring artifact. Mayhem coins both graduate more AND collapse
3.4× more: the vault feed manufactures action in both tails.

## 4. Do the separations reproduce? (M5) — no

On the deployer-identified population (n = 30,828), outcome = collapse (base 2.67%):

- **mayhem-CLEAN (all five gates)**: admits 1,888 (6.12%), clean precision **95.55%**
  [Wilson 95%: 94.52%, 96.39%] — the admitted set collapses at 4.45%, ABOVE base. On is_rip:
  97.35% [96.53%, 97.99%] vs base 1.30% — again above base among admitted. Anti-selective.
- **bundledness**: rip risk ratio 2.38× but 95% deployer-clustered CI [0.62, 4.64] — only
  162 bundled coins exist; the feature is too rare here to carry anything.
- **deployer history, inverted**: dirty-history (prior rips/dumps) collapse risk ratio
  0.58× [0.45, 0.76]; rip 0.47× [0.31, 0.74]. 92.3% of mayhem coins have a deployer with a
  prior dump on record — this is a repeat-operator factory stratum, and it is the
  FIRST-TIMERS who are dangerous (the standard arm's "no record = 1.71× risk" finding, but
  now strong enough to invert the gate outright).
- **crew fingerprints do not exist**: 400 busiest multi-launch deployers, 8,782 coins,
  95,760 same-deployer pairs — and 22 distinct ex-deployer birth-slot wallets in the entire
  arm. Mean Jaccard 0.0011 vs day-matched 0.0000 vs curveball null 0.0010 (p = 0.425,
  effect 1.1×). Against the standard arm's 0.26 vs 0.0026, the crew phenomenon is absent,
  not attenuated.
- The DUMP label saturates (94.38% base) and is uninformative within-stratum.

## 5. The registered ship rule (M6)

| condition | required | measured | verdict |
|---|---|---|---|
| (i) curve identification | ≥ 95% | 100% (PDA; registered heuristic 92.5%, superseded) | PASS |
| (ii) admitted n | ≥ 1,000 | 1,888 | PASS |
| (iii) collapse clean precision, Wilson LB | ≥ 99.5% | 94.52% | **FAIL** |
| (iv) bundled risk-ratio CI excludes 1 | yes | [0.62, 4.64] | **FAIL** |
| (v) crew Jaccard ≥ 10× control, p ≤ 0.01 | yes | 1.1×, p = 0.425 | **FAIL** |

**No mayhem-calibrated arm ships. The stratum stays UNSCORED**, and per the registration
this is stated as the deliverable, not softened: the screen's validated features measure a
crew-and-deployer economy, and mayhem launches are priced by a protocol vault instead. A
re-tuned threshold set would be a new unvalidated screen wearing this one's name.

## 6. What ships anyway (honest, and better than silence)

The UNSCORED verdict line currently says only `policy:mayhem_flag_nonstandard_curve`. It can
now carry the measured stratum context — clearly labeled as stratum base rates, never as a
coin score:

> "MAYHEM launch — unscored by design (validated screen does not transfer: its gates are
> anti-selective here). Stratum facts 08-26..28, n=30,831: 2× supply, half on a standard
> curve, half in pump.fun's global vault which starts selling into the curve ~2 s after
> birth and fully drains on the median coin. Collapse rate 2.67% (3.4× standard), insider
> dump 94%, graduation 4.13% (1.7× standard). Bundle/crew signals do not exist in this
> stratum."

Also for the wire/site (KNOW-YOUR-ENEMY): the BwWK vault explainer, the 2-second feed-out
clock, and the vendor `bondingCurveKey` failure mode. Implementation notes for
`dregg_screen`: keep `hydrate_mayhem = False` (hydration can only confirm UNSCORED — now
proven, not presumed); the `base_rates` blob may carry a `mayhem_stratum` block quoting §3.

## 7. What would have changed the verdict / limitations

- Three days of exposure; collapse is decided in the first hour (prior result) so (iii)
  is exposure-robust (day-1-only CLEAN reads 96.94% [95.52%, 97.92%] — same failure), but
  graduation and any slow-burn outcome are right-censored.
- History features saturate (dump base 94%) — a longer window could differentiate degrees
  of dirtiness, but it cannot rescue (iv) or (v), which fail on feature absence.
- The 4.0% of vault outflow that does NOT enter the curve is uncharacterized (who receives
  it, and is it informative?) — the one open thread this study leaves, and it is exit-side.
- Vault semantics (per-buy top-up vs scheduled sale; where the SOL side settles) are not
  determinable from token legs alone — native SOL is invisible to this corpus. The measured
  facts (§0 mechanism paragraph) do not depend on the interpretation.
