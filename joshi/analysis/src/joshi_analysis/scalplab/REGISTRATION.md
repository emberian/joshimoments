# scalplab v1 — pre-registered evaluation protocol

Registration version: `joshi.scalplab.registration.v1`
Registered: 2026-08-24, BEFORE any model in this package was run on a real tape.
Author knowledge disclosure: the choices below were made after reading catalog *schemas* and
row/coin/count summaries of duck-tape (1,689 socket trades, one coin), duck-tape-polled
(2,421 unique polled trades, same coin), kylie-backfill (2,200 polled trades, one coin,
retrospective), and fleet-tape-1 (in-flight socket recording, 7 coins, ~450 trades at
inspection). No price path was plotted, no label statistic was computed, and no model was fit
before this document was written. The duck coin is known to the author as "a 1,689-event
collapse" and kylie as "an 18/s firehose" from the primary agent's prose; that prose is the
whole of the author's prior knowledge of these tapes' dynamics.

Any deviation from this protocol requires a new registration version; results produced under a
deviation must say so.

## 1. Canonical tape frame and decision clocks

One loader (`tape.py`) turns either tape kind into the same event frame: per-coin,
time-ordered, deduplicated trade events with exact `Decimal` prices.

- Socket tapes (`pumpportal.websocket.data.v1`): order = catalog commit order; dedupe key =
  transaction signature; canonical price = post-trade marginal pool price
  `solInPool / tokensInPool` computed in `Decimal` from the frame's own literals; arrival
  clock = the catalog's `received_wall_us`. **Honest decision clock: socket arrival**
  (sub-second floor, taken as 0 for labeling purposes).
- Polled tapes (`pump.api.product.v1` trades pages): order = ascending `slotIndexId` (slot =
  first 12 digits); dedupe key = (`slotIndexId`, `tx`); canonical price = the page's exact
  decimal `priceSol` literal; venue event time = the row's ISO timestamp (1 s precision).
  **Honest decision clock: venue timestamp + the tape's own poll floor** (median interval
  between poll receipts). A tape whose poll-receipt span is less than half its trade-time span
  is declared `retrospective_none`: it has NO honest live decision clock, and any policy file
  built from it alone must carry that flag.

Per-tape provenance always carries: source kind, source id, event/coin counts, the catalog's
own `coverage_gap` rows (cause code, severity, bounds), the count of full poll pages with zero
overlap against previously seen keys (possible unobserved trades — reported, never
interpolated over), the arrival-clock kind and floor, and the declared venue floor.

## 2. Venue floor and the only label

Declared venue floor: **250 bps round trip** per tape unless a caller declares a different
measured floor at load time (the desk's measured range is 190–250 bps; the default is the
conservative end). The declared value is recorded in provenance and in every result.

**The only label in this package** (`labels.py`): for decision event `i` with horizon `k`
events, entry is at the price of event `i+1` (one-event execution delay, declared,
conservative against the same-slot latency finding), and

```
label(i, k) = 1  iff  exists j in [i+2, i+1+k] with
              price[j] * 10^4 >= price[i+1] * (10^4 + floor_bps)
```

i.e. a floor-clearing up-leg begins within `k` events of the decision. Labels whose window
runs off the tape end are undefined and excluded (counted, never imputed). No raw-direction
label exists anywhere in this package. Horizon sweep: `k in {10, 25, 50, 100}`.

## 3. Features (all causal, declared, shared by every model)

Computed at event `i` from events `<= i` only; events with `i < 33` (warmup = window 32 + 1)
are excluded from fitting and judging. Window `W = 32` events. Declared clock for time-based
features: venue event time when present, else arrival wall time (stated per tape).

r1, r4, r16, r32 (log returns); quote-volume imbalance over W; buy fraction over W; trader
concentration (unique traders / W); log run-up from window min; log drawdown from window max;
depth-2 path-signature Lévy area of (normalized time, centered log price) over W; EWMA
buy/sell intensity (event-clock exponential decay, half-life 8 events) as log-ratio and
log-total; log10 mean inter-event time over W; two-sided causal CUSUM statistics (up, down) on
running-standardized r1 (drift `k = 0.5`, threshold `h = 5`, Welford running moments).

## 4. Model zoo v1 (locked env has no numpy/sklearn/GBDT: pure Python, declared)

1. **Hawkes** (`hawkes.py`): bivariate (buy, sell) exponential-kernel Hawkes, shared decay
   `beta`; log-likelihood by the standard O(n) recursion; MLE by Nelder–Mead in log-parameter
   space (budget 600 evaluations, deterministic start). Equal-timestamp ties are dithered by
   `+j * 1e-4 s` in tape order (declared fabrication, polled tapes only need it). Branching
   ratio = spectral radius of the 2x2 `alpha/beta` matrix — reported for the pooled fit and
   per non-overlapping 256-event window; it is the regime dial. Probability head: logistic
   link on the two causal log-intensities, fit on train coins only.
2. **Analog** (`analog.py`): nearest-neighbour over the section-3 feature vectors,
   standardized on train coins; forecast = Laplace-smoothed empirical label distribution of
   the `k_nn = 50` nearest train-coin neighbours (Euclidean). When the train memory exceeds
   4,000 vectors it is thinned by a deterministic uniform stride to 4,000 (declared,
   pure-Python tractability; the thinning is part of the model, not a tuning knob).
3. **Logistic regression** (`logit.py`): the declared substitute for gradient-boosted trees —
   the locked environment ships neither xgboost nor lightgbm nor sklearn, and heavy
   dependencies are out of scope by instruction. Fit by IRLS (Newton) with L2
   `lambda = 1e-3`, at most 25 iterations, tolerance 1e-8, deterministic.
4. **Change-point** (`changepoint.py`): declared CUSUM (not BOCPD), used both as features
   (section 3) and as the declared exit-alarm carried into any policy file.

## 5. Evaluation protocol

- **Coin-level splits, leave-one-coin-out**: each judged coin is evaluated by models fit only
  on the other coins. Train coins are never judged inside their own fold. Tapes covering the
  same mint (duck socket + duck polled) are ONE coin for splitting purposes.
- **Time order within coin is never shuffled.**
- **Calibration is the claim**: reliability curve with 10 equal-width probability bins (n,
  mean predicted, observed rate per bin) plus Brier score, against the fold's base rate.
- **Policy extraction is part of the grid**: thresholds `tau in {0.5, 0.6, 0.7, 0.8, 0.9}`
  swept; a cell reports fired-count and precision. Economic verdicts are NOT computed here —
  they belong to the Rust replay/grid harnesses; the bridge artifact is the policy file.
- **Candidate rule (pre-registered)**: a (model, k, tau) cell is a CANDIDATE_POLICY only if
  all data gates pass, the cell fires >= 20 times on judged coins, and the Wilson 90% lower
  bound of its precision exceeds 1.5x the pooled base rate. Otherwise the verdict is
  CALIBRATED_NULL (gates passed, nothing clears) or INSUFFICIENT_DATA.

## 6. Minimum-data gates ("enough tapes", concretely)

Per judged coin: >= 500 labeled events and >= 25 positives, else that fold is
INSUFFICIENT_DATA. Per model family, minimum training corpus:

| family  | min train coins | min train labeled events |
|---------|-----------------|--------------------------|
| logit   | 5               | 5,000                    |
| analog  | 8               | 20,000                   |
| hawkes  | 5               | 3,000 (>= 300/coin)      |

Any result fit below these gates renders with the harness's own vocabulary (quoted verbatim
from `crates/joshi-liquidity/src/grid.rs::ONE_TAPE_FITS_NOTHING`) and claims nothing forward.
Every reported number carries n-tapes / n-coins / n-events. A calibrated "nothing here" is a
deliverable.

## 7. Policy file

Contract `joshi.scalplab.declared_policy.v1` (schema in `policy.py`): feature definitions
verbatim, model family and parameters, threshold, horizon, venue floor, decision clock and
execution delay, exit alarm, tape provenance, the full evaluation summary (calibration
included), and a REQUIRED non-blank author-knowledge disclosure. A blank disclosure is
refused, mirroring the replay harness's RULES_ARE_NOT_BLIND stance. A candidate's shipped
parameters are a full-corpus refit with the declared procedure; the evaluation block remains
the LOCO numbers, and the file says so.
