# RESULT: the mayhem arm — the stratum stays UNSCORED, and now we know exactly why

2026-08-29, revised same day after `docs/MAYHEM_MODE.md` (478673c) landed mechanism ground
truth mid-study. Instruments: `studies/mayhem_arm.py` (registered in
`REGISTRATION_mayhem_arm.md` before any estimand) and `studies/mayhem_real_flows.py`
(registered in `REGISTRATION_mayhem_real_flows.md` after the mechanism doc, before its own
estimands). Caches under `studies/data/mayhem_arm/`. Window: fresh corpus 2026-08-26..28;
causal history seeded from 2026-08-05..14. Cost: $0 BigQuery (stratum n = 30,831 locally,
6x the registered floor; a fresher-day pull was dry-run-estimated but not bought — see the
wire report).

**Verdict, both registrations: NO mayhem screen arm ships — not as a recalibration of the
validated gates (original M6: three of five conditions FAIL) and not as a real-flows
re-instrumentation (amendment: the only separating feature covers 0.53% of the stratum and
every conjunction is anti-selective). The stratum stays honestly UNSCORED, and the negative
is a measurement.** This agrees with and extends the mechanism recon's recommendation
(MAYHEM_MODE.md §7): prices here are administered by pump's fee-exempt agent (virtual SOL
re-marked ~500x per agent trade; k/k_std measured 0.0023-4.87 by the recon), so the
screen's price-path machinery has nothing to stand on, and the surviving real-flow features
point the wrong way or almost never fire.

## 0. Corrections against the first version of this document

The first draft (same day, pre-recon) claimed "H1 confirmed: standard curve" from three
checks. Two of those checks verified TOKEN-side structure only and one was circular:

- RETRACTED: "k = 3.219e25 confirmed three independent ways." What the checks proved:
  the curve is standard-SEEDED at birth (32/32 vendor frames exact; seed arithmetic
  30,831/30,831) and its TOKEN bookkeeping is standard (graduation holdback exactly
  2.069e14). The "median graduated peak = 410.9 SOL" line was arithmetic on the token
  balance under an ASSUMED k — it verifies the holdback, not the price. The recon measured
  k rewritten inside agent trades; no constant k exists during the 24h window.
- DEMOTED: every mcap/price-based number in §3-4 below (collapse, rip, peak>=100 SOL,
  the M5 gate precisions on those outcomes) is computed on a PSEUDO-price (standard-k
  projection of the token balance). On this stratum that is neither the marked price nor
  real money. They are retained, labeled, because the registration promised them and they
  document WHY the transplant fails; never quote them as market facts.
- CORRECTED: "the vault feeds out its entire 1e15 on the median coin" conflated agent
  sales with the t+24h BURN. By amount: gross vault outflow 3.61e19 raw, of which 40.9%
  sold into the curve, **52.8% burned** (20,777 coins burned in-window, exactly one burn
  row each — the t+24h burn arriving for day-1/2 births), 6.3% other.

## 1. The mechanism (one paragraph, aligned with MAYHEM_MODE.md — the authority)

Mayhem is per-coin opt-in: 2e15 raw minted; 1e15 funds a standard-seeded bonding curve;
1e15 sits in a per-coin Token-2022 vault whose on-curve identity is ONE constant sol-vault
PDA across all 30,831 coins — `BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s` — from which
pump's AI agent trades fee-free for exactly 86,400 s, re-marking virtual SOL ~500x its real
size per trade; unsold and repurchased vault tokens burn at t+24h. Corpus-side facts this
study adds: the agent's first outflow lands a median of **2 seconds** after birth (p10 1 s,
p90 11 s); gross agent outflow decomposes 40.9% sold-into-curve / 52.8% burn / 6.3% other;
the derived bonding-curve PDA appears among the birth legs on 100.00% of mayhem creates and
the seed is exactly 1e15 - dev_buy on 100.00%. The vendor emits the sol-vault PDA as
`bondingCurveKey` on ~1/3 of mayhem frames (10/32 here; independently found by the recon)
— derive the PDA locally, never trust that field on this stratum.

## 2. Census (M1)

| day | standard (1e15) | mayhem (2e15) | mayhem share |
|---|---:|---:|---:|
| 2026-08-26 | 35,280 | 11,051 | 23.85% |
| 2026-08-27 | 35,879 | 10,213 | 22.16% |
| 2026-08-28 | 28,021 | 8,071 | 22.36% |
| **pooled** | **104,380** | **30,831** | **22.80%** |

Live telemetry's 28-44% is an hour-of-day figure; the corpus-wide share is 22.8%. The
residual census (`census.json`) is dominated by minted_raw = 0 (81,744 pre-window coins
whose first observed tx is a trade) plus 174 one-legged 1e18/9-decimal impostors. NOTE
(recon §5): a THIRD stratum exists — non-mayhem coins seeded at vSol 4.292 SOL with supply
exactly 1e15 — which is INSIDE the "standard" count above and cannot be separated from the
token-side ledger. Its share of births is unknown (2.7% of board rows); it needs its own
membership predicate from CreateEvent reserves before any of the standard arm's per-coin
price arithmetic can be called exact on that slice.

## 3. Roles (M2) — clean, with one registered rule superseded

- Derived PDA among birth legs: 30,831/30,831 (100.00%). Exact-1e15 vault leg:
  30,831/30,831. Seed = 1e15 - dev_buy: 30,831/30,831. n_birth_legs = 3 on 30,828
  (2 on the 3 zero-dev-buy coins).
- DISCLOSED DEVIATION: the registered touch-rule heuristic agreed with the PDA on only
  92.51% — below its own 95% bar; the deterministic PDA derivation superseded it (the
  recon's Trap 1 — vendor-key junk — never bit because no vendor gating was used).
- The corpus `birth.parquet` rank-1/rank-2 roles are wrong for essentially every mayhem
  coin with a dev buy (the vault out-ranks the curve); nothing built on those roles may be
  reused for this stratum. All sniper/insider/crew features below EXCLUDE the vault/agent
  identity — which is exactly the exclusion MAYHEM_MODE.md §5 requires (unexcluded, the
  agent reads as one giant fake crew across the whole stratum).

## 4. The original M4/M5/M6 — the transplant fails (pseudo-price outcomes, labeled)

Pseudo-price outcome rates (standard-k projection; ARTIFACTS of administered pricing,
retained per registration): "collapse" 2.673%, "rip" 1.304%, "peak>=100 SOL" 9.44% —
against standard-arm same-window 0.781% / 0.507% / 8.12%. Real token-side rates: insider
dump 94.38% (vs 75.79% standard; the label saturates and is uninformative here),
graduation-by-balance 4.13% (vs 2.46%; on this stratum the balance predicate is a proxy —
the recon notes agent sells can push the curve above its seed and graduation implies no
fixed real-SOL depth).

Gate behavior against the pseudo-outcomes (n = 30,828 deployer-identified): the five-gate
CLEAN conjunction admits 1,888 (6.12%) with "collapse" precision 95.55% [94.52%, 96.39%] —
BELOW the 97.33% base — anti-selective; dirty-history risk ratio 0.47x [0.31, 0.74]
(inverted: 92.3% of mayhem deployers carry a prior dump; the dangerous ones are the
first-timers); bundledness rip ratio 2.38x [0.62, 4.64] on only 162 bundled coins
(bundling is 83x rarer than standard: 0.53% vs 44.17% — a feature-side fact, valid);
crew fingerprints ABSENT (agent excluded: 22 distinct ex-deployer birth-slot wallets
across 8,782 coins / 400 multi-launch deployers; same-deployer Jaccard 0.0011 vs curveball
0.0010, p = 0.425 — feature-side, valid).

Registered M6 ship rule: (i) identification PASS (100%); (ii) admitted n PASS (1,888);
(iii) precision FAIL (94.52% lower bound vs required 99.5%); (iv) bundle CI FAIL;
(v) crew FAIL. **No recalibrated arm ships.** Post-recon this is overdetermined: (iii)'s
outcome was an artifact to begin with, and (iv)/(v) fail on feature absence, which no
outcome redefinition can rescue.

## 5. The amendment — real-flow outcomes, and the build/no-build answer

Registered post-recon (`REGISTRATION_mayhem_real_flows.md`), agent excluded everywhere,
outcomes on real token flows only:

- E1 HUMAN CROWD (distinct human buyers in first 24h): median **4** wallets; p75 = 10,
  p90 = 20; only 6.8% of mayhem coins ever attract >=25 humans, 1.2% >=50. The typical
  mayhem coin's entire human audience is four wallets.
- E2 LIFE AFTER THE BURN: **7.39%** [7.03%, 7.78%] of exposure-complete coins
  (n = 18,472) see ANY human activity after t+24h. The recon's "score at t+24h" design is
  well-posed but addresses under 8% of the stratum.
- E3 REAL RIP (insider dump + crowd >= 25): 6.12% pooled (1,886 events; sensitivity:
  23.58% at crowd>=10, 1.11% at >=50 — the dump is near-universal, so this outcome is
  mostly a crowd-size dial).
- E4 separation, deployer-clustered 95% CIs: human bundledness **2.03x [1.18, 2.98]**
  (the ONE qualifying separator — on 162 coins, 0.53% of the stratum); dev-buy >= 2%
  of 2e15: 0.37x [0.14, 0.84] (protective — big dev buys correlate with NOT ripping
  here); real dirty history: 0.49x [0.41, 0.58] (protective again).
- E5 CLEAN-analog conjunction: admits 6.1%, real-rip precision 88.15% [86.61%, 89.53%]
  vs 93.88% base — **anti-selective**, because its dominant gates are the inverted ones.

**The pinned ship rule technically FIRES** — (a) via >=300 events, (b) via bundledness at
exactly the 2.0x floor — **and the recommendation is still NO-BUILD**, stated with the
discrepancy visible rather than tuned away: the rule as pinned was too loose (a single
covariate at minimum strength on 0.53% coverage satisfies it). What a build would actually
ship: one rare positive covariate and a set of gates that admit MORE rips than base. There
is no admit-class in this stratum safer than the stratum itself under any registered
conjunction, both outcome definitions agree on that, and predicting the crowd-size dial
that remains is attention-prediction — territory the season's law already closed. A future
arm would need a NEW feature family (e.g. agent-behavior/mayhem-state telemetry), not
these features re-thresholded.

## 6. What ships anyway (honest, and better than silence)

The UNSCORED tg_line currently says `policy:mayhem_flag_nonstandard_curve`. It can now
carry measured stratum context — labeled as stratum facts, never a coin score:

> "MAYHEM launch — unscored by design: pricing in the first 24h is administered by pump's
> fee-exempt agent (re-marks ~500x real size; see MAYHEM_MODE.md), so the validated screen
> does not transfer (its gates measured anti-selective here). Stratum facts 08-26..28,
> n=30,831: half of supply trades from pump's vault starting ~2 s after birth and burns at
> 24h; insider dump rate 94%; median human audience 4 wallets; 7% of coins see any human
> trade after the burn; birth bundles and crew fingerprints are absent in this stratum."

Plus, for the wire/site (KNOW-YOUR-ENEMY): the vault mechanics above, the vendor
`bondingCurveKey` junk mode, and the 22.8%-of-births census. Implementation notes:
keep `hydrate_mayhem = False`; never compute `dev_buy_share` against 1e15 on a mayhem
frame (2x overstatement); a `mayhem_stratum` block in `base_rates` may quote §5's E1/E2
and the dump rate (real-flow numbers only — none of §4's pseudo-price rates).

## 7. Limitations

Three days of exposure; E2/E3 inherit the window (day-3 births drop from E2 by design).
Real SOL flows are invisible to this corpus (native SOL is not in token balances), so
"real materiality" here is crowd-count, not SOL — the recon's real_quote_reserves path is
the right instrument if anyone revisits, and would need TradeEvent-level data. The third
stratum (4.292-SOL seed) contaminates the STANDARD population at an unknown birth share
and is flagged in RESULT_verdict_survival.md and above. The burn accounting counts
supply-reducing transactions; if pump ever burns via a different mechanism the 52.8% split
shifts.
