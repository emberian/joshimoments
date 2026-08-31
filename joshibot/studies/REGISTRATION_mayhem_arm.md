# REGISTRATION: the mayhem arm — can the birth-time screen score the nonstandard-curve stratum?

2026-08-29, registered BEFORE any mayhem-stratum estimand was computed. Instrument will be
`studies/mayhem_arm.py`; caches to `studies/data/mayhem_arm/`. Data: the fresh corpus
`state/bulk_pump_fresh/raw/` (2026-08-26..28) via the already-built distillates under
`studies/data/operator_crime_fresh/` (ledger/day=*.parquet, birth.parquet), plus
`state/boards/` vendor snapshots and `state/dregg_screen/firehose/new_token/` frames for the
curve-constant cross-checks, and `studies/data/operator_crime/` (2026-08-05..14) for causal
deployer/sniper history. No BigQuery spend is planned unless the local stratum n falls below
5,000 coins; if a pull is considered, the dry-run estimate is reported either way.

## Author-knowledge disclosure (what I have already seen, so it cannot count as a finding)

- Live screen telemetry: mayhem-flagged creates are ~28–44% of the stream; 10/10 hydrated
  mayhem creates minted exactly 2e15 raw (`dregg_screen/live.py`, `score.py` comments).
- One live vendor frame for a mayhem create showing `vTokensInBondingCurve + initialBuy =
  1,073,000,000.000000` exactly and `vSol - solAmount = 30.0` exactly — i.e. the vendor
  reports STANDARD-curve arithmetic on a mayhem frame. This seeds hypothesis H1 below; it is
  one frame, not a measurement.
- `RESULT_operator_crime.md` §2.2: 31% of on-curve board snapshots carried k ≠ 3.219e25.
- The standard arm's validated operating point (CLEAN ≥99.90% clean at 95% conf on the fresh
  window; bundled-at-birth rip separation; crew Jaccard 0.26 vs 0.0026 day-matched null).
- I have NOT computed: the mayhem birth census, any mayhem outcome rate, any within-stratum
  gate separation, or any mayhem crew statistic.

## The known trap this study exists to avoid

`birth.parquet`'s `curve_owner` is the LARGEST positive leg of the first transaction and
`deployer` is the second-largest. If a mayhem create mints 2e15 with ~1e15 to a non-curve
account (H1), those role assignments are WRONG for the whole stratum whenever dev_buy > 0,
which corrupts snipers (the vault counts as a birth-slot buyer), dev-buy, deployer history,
and the entire curve price path. Nothing downstream of role assignment may be computed until
M2's identification rule is applied and validated. Likewise `dev_buy_share` must use the
stratum's true supply, never 1e15.

## Membership

MAYHEM := first observed transaction of a `%pump` mint inside 2026-08-26..28 nets exactly
2_000_000_000_000_000 raw with decimals = 6. The residual census (first-tx net not in
{1e15, 2e15}, or decimals ≠ 6) is counted and reported, never rescaled or folded in.

## Hypothesis under test (falsifiable, stated in advance)

H1 (standard-curve, doubled-supply): the mayhem curve is the STANDARD constant-product curve
(k = 3.219e25, v_tok = curve_balance + 7.3e13), the dev buy comes out of a standard-funded
1e15 curve (curve first-tx net = 1e15 − dev_buy), and the second 1e15 sits in a separate
birth-leg account (the "mayhem reserve") that does not trade on the curve.
H1 fails if: the curve-leg seed distribution is not 1e15 − dev_buy; or vendor/boards virtual
reserves joined at ≤60 s staleness disagree with k = 3.219e25 by >1% at the median; or no
static ~1e15 second leg exists.

## Registered estimands

M1 CENSUS. Per day and pooled: n mayhem births; mayhem share of (standard + mayhem) births;
   the residual nonstandard table by first-tx net value. (Telemetry anchor: 28–44%.)

M2 ROLES. Identification rule, fixed now: among the birth transaction's positive legs,
   CURVE := the leg whose owner has the most subsequent ledger touches for that mint
   (the account that trades); RESERVE := a leg of exactly 1e15 whose balance never changes
   in-window (if H1); DEV := the largest remaining positive leg in the birth transaction;
   SNIPERS := birth-slot positive owners excluding CURVE and RESERVE (dev included, as in
   the standard arm where the deployer is a birth-slot buyer via its dev buy).
   Validation: for every mayhem mint also present in `state/dregg_screen/firehose/new_token/`
   (vendor gives `bondingCurveKey`), the identified CURVE owner must equal the vendor's curve
   key; report x/n. If agreement < 95%, the study STOPS and reports the stratum unscoreable
   at this time (role assignment is the foundation of everything below).
   Also reported: n_birth_legs distribution; RESERVE stability (fraction of reserves that
   ever move in-window, and where they go — this is KNOW-YOUR-ENEMY content either way).

M3 CONSTANTS. k and the v_tok offset for the mayhem curve, measured two ways:
   (a) `state/boards/` snapshots joined to mayhem mints at ≤60 s staleness: median and p90 of
       |vendor_vTok·vendor_vSol − k_std| / k_std, and offset := vendor_vTok·1e6 − our curve
       balance at the snapshot clock;
   (b) live firehose new_token frames: does vTok + initialBuy = 1.073e9 and vSol − sol = 30.0
       hold for all mayhem creates captured (report x/n)?
   Pricing downstream uses the MEASURED constants. Market cap is reported two ways:
   mcap_circ := price × 1e15 (reserve excluded; the SOL actually reachable on the curve;
   PRIMARY, cross-arm comparable) and mcap_total := price × 2e15 (secondary).

M4 OUTCOMES. Within the mayhem stratum, with corrected roles/constants, the standard arm's
   pre-registered definitions verbatim: graduation (curve balance ≤ 1e9 raw); insider DUMP
   (DUMP_FRAC = 0.80 of insider-set peak disposed, t_dump strictly after peak); RIP :=
   dump ∧ ins_peak_share ≥ 5% of TRUE supply (2e15) ∧ peak_mcap_circ ≥ 100 SOL ∧ drawdown
   ≥ 90%; COLLAPSE (price-only) := peak_mcap_circ ≥ 100 SOL ∧ drawdown ≥ 90%. Reported per
   day and pooled, beside the standard arm's same-window rates. Exposure caveat is stated
   (3-day window; prior result: rug risk ~decided in the first 60 min, so collapse has
   adequate exposure; graduation is reported but not gated on).

M5 DO THE FEATURES STILL SEPARATE? Within-stratum only, never blended with the standard arm:
   (a) bundledness: collapse and rip rates for n_snipers ≤ 1 vs ≥ 2 (corrected sniper set);
       risk ratio with 95% CI (deployer-clustered bootstrap, 2,000 draws).
   (b) dev-buy gate: collapse rate for dev_buy/2e15 < 2% vs ≥ 2%.
   (c) history gates: prior_launches/rips/dumps for the DEV wallet computed causally from
       the combined event stream (window A 08-05..14 standard births + fresh standard +
       fresh mayhem, each event at its own time, strictly before birth); collapse rate for
       clean-history vs dirty-history.
   (d) crew reuse: same-deployer ex-dev birth-slot sniper-set mean Jaccard vs day-matched
       different-deployer control and a curveball degree-preserving null (n=200), with
       cmd_graph's caps (≤400 deployers, ≤25 coins each) — the same statistic at the same
       unit as the validated standard-arm number.
   (e) the mayhem-CLEAN screen: all five standard gates (n_snipers ≤ 1, prior_rips = 0,
       prior_dumps = 0, sniper_prior_max = 0, dev_buy_share < 0.02 on the 2e15 denominator)
       conjoined; report admit rate, admitted n, clean precision on rip and on collapse with
       Wilson 95% CIs, pooled and for day-08-26-only (max exposure).

M6 SHIP RULE (fixed now). A MAYHEM-CALIBRATED screen arm ships iff ALL of:
   (i)   M2 curve-owner validation ≥ 95% agreement;
   (ii)  mayhem-CLEAN admitted n ≥ 1,000 pooled;
   (iii) collapse clean precision Wilson 95% lower bound ≥ 99.5%;
   (iv)  bundledness separation: bundled/unbundled collapse risk ratio CI excludes 1;
   (v)   crew Jaccard treatment/day-matched-control ratio ≥ 10× with curveball p ≤ 0.01.
   The shipped arm carries its OWN numbers (separate operating point, separately stated,
   policy note `mayhem_arm:validated_2026-08-26..28`); the standard arm's precision is never
   quoted for a mayhem verdict. If any of (i)–(v) fails, the stratum stays UNSCORED, the
   RESULT says which condition failed and at what value, and that is the deliverable.

## What would falsify the whole approach

Role assignment unverifiable (M2 < 95%); or the measured constants unstable across coins
(no single (k, offset) fits ≥ 99% of joined snapshots within 1%); or gates that pass M6
(ii)–(iii) only by admitting a stratum with near-zero base rate (base collapse rate < 0.1%
makes "clean precision" vacuous — reported as such, not shipped as a win).
