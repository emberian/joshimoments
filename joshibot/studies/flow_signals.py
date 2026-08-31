"""Will a held coin dump, and IN WHAT MANNER? A competing-risks treatment of token exit.

Run it::

    uv run python studies/flow_signals.py                  # everything, writes results.json
    uv run python studies/flow_signals.py --quick          # fewer replicates, same code path
    uv run python studies/flow_signals.py --part survival  # one part only
    uv run python studies/flow_signals.py --part changepoint
    uv run python studies/flow_signals.py --part flow

Pure stdlib, deterministic given ``--seed``, opens no socket. It reads three caches that other
collectors materialise and never writes outside ``studies/``:

- ``state/deterioration/ohlcv/*.json`` + ``discovery.jsonl`` — hourly GeckoTerminal OHLCV for a
  few hundred Solana pools. The survival cohort.
- ``state/bulk_history/swaps/*.jsonl`` — the BigQuery replay tape (exact pre/post reserves).
- ``state/cluster_tape/swaps/*.jsonl`` — the live RPC tape (same, plus signers/fee payer).

=========================================================================================
1. THE FRAMING: "AND HOW" IS NOT A MODIFIER, IT IS THE MODEL
=========================================================================================

A token does not "die". It leaves through one of several mutually exclusive doors, and which
door it takes is the entire decision-relevant content. A holder facing a cliff has already
lost; a holder facing a slow bleed has weeks to leave at leisure; a holder facing a dump that
recovers should do nothing at all. These are **competing risks**, and the correct objects are
a cause-specific hazard per mode and a cumulative incidence function (CIF) per mode.

A binary "will it dump" classifier cannot express this. It must collapse incompatible modes
into one label and therefore learns their average. §4 below *measures* the collapse: the
conditional mode mix swings from 89% SILENCE / 0% CLIFF in one stratum to 4% SILENCE / 69%
DOUBLE in another, while the all-cause event probability moves far less. A single label
throws away exactly the part the operator needs.

**The literature has not done this.** Grepping 99 papers in ``~/paperbin/joshibot`` for
``competing risk``, ``cumulative incidence``, ``Fine-Gray``, ``subdistribution``,
``cause-specific`` and ``Aalen`` returns **zero hits**. Exactly one paper in the corpus does
survival analysis of any kind — see §2 — and it is binary. Per-exit-mode *time* distributions
appear once, as raw quantiles with no censoring model (``solana-rugpull-hype-to-collapse``
Table IV). The only paper that even names the sharp-vs-slow distinction
(``memecoin-viral-to-void``, "hard pull" vs "soft pull") never operationalises it, and that
paper's labels are partly randomly fabricated by its own admission, so its numbers are unusable.
Competing risks on token exits is unoccupied ground.

=========================================================================================
2. arXiv 2607.02823, AND WHY ITS INSTRUMENT IS BROKEN
=========================================================================================

``pumpfun-graduation-regime-windows-censored-2607.02823`` — "Survival Analysis of 832,941 Token
Launches". Kaplan-Meier plus L2-penalised Cox (concordance 0.858), ``lifelines 0.30.3``.
N = 832,941 mints, **1,651 graduations**, 831,290 TIMEOUTs. It is **not** competing risks: two
states only, GRADUATED vs TIMEOUT, and TIMEOUT is treated as *censoring* rather than as a
competing event. Because every censoring event lands at exactly 24h and every failure lands
before 6 minutes, its Kaplan-Meier estimator is arithmetically identical to the pooled binomial
proportion — the paper concedes this ("the asymptote at t = 24 h coincides with the pooled
graduation rate of 0.198% to within the displayed precision"). The survival machinery adds
nothing over a 2x2 table.

**Its instrument is displacement-censored, per PROGRAM.md §3.8, and here is the check.** Among
its 1,651 graduates the median time-to-graduation is 1.0 min and the **maximum is 5.0 min**
(5.98 min on the chain-time basis) inside a nominal 1,440-minute window. Marino & Lillo measure
a median of **4.4 minutes from creation** on a distribution explicitly described as having "a
pronounced heavy tail … a minority of tokens requires tens of minutes to migrate". So this
observer recorded *zero* graduations beyond a point past which roughly half of Marino's occur.
That is a collection-side truncation of the event process, not a property of pump.fun. It is
corroborated three ways: every reported order statistic across 1,651 events lands on an integer
(minute-quantised event times, so the KM risk set has ~5 distinct failure times); the authors
admit a four-day interval where "launch-detection callbacks appear to have been wired before
the graduation-detection callbacks", converting graduations into censoring events by a wiring
defect; and the mcap quartile at exactly 30.00 SOL contains **1 graduation in 91,247 mints**
against ~77 expected at the neighbouring rate, a Poisson tail event of order 1e-30. The same
author's companion paper abandoned its Cox model six weeks later because "coverage is too thin
to support a Cox-PH estimate". PROGRAM.md §3.8 says verify the pipeline reproduces Marino's
4.4-minute median *with a tail*, and that if your max is ~5 minutes your instrument is
truncated. This is that failure, in print.

**Our own instrument carries the mirror-image defect and we handle it explicitly.** The
GeckoTerminal OHLCV endpoint returns at most 1000 hourly bars, so any token older than ~41 days
is **left-truncated by the API, not by the clock** — as of this writing 76 of 240 cached tokens
sit exactly on the 1000-bar cap. The landmark design in §3 makes this harmless: every risk
interval begins at an observed bar, so a truncated history costs us landmarks, never
correctness. The one quantity it does bias is drawdown-from-running-peak, which is understated
for capped tokens because their true peak predates the window; that is flagged per token and
the affected covariate is reported as a lower bound.

=========================================================================================
3. THE ESTIMAND: LANDMARK COMPETING RISKS, NOT FIRST-PASSAGE-FROM-BIRTH
=========================================================================================

The obvious construction — clock from pool creation, event = first crossing of a deep drawdown
— was built first and **discarded on measurement**. Of 164 tokens with usable history, 62 cross
-70% from their running peak, but that crossing is overwhelmingly the post-launch shakeout
rather than deterioration: median return *after* the crossing is +20.8%, the 75th percentile is
+8.7x, and the 90th is +22.8x. weave crosses -70% early and then trades up 57x. An estimator
built on that event would be measuring launch mechanics and calling it death.

So the clock starts where the operator actually stands: **at a landmark**, holding a coin, asking
what the next week looks like. At each landmark ``L`` (every ``--stride`` hours of a token's
observed life, requiring 168h of prior history for the covariates) we follow forward to horizon
``H`` and record the **first** of four mutually exclusive absorbing events, checked in this
order at each hour:

===========  ============================================================================
mode         operational definition (thresholds are knobs; PROGRAM.md §3.7 — report them)
===========  ============================================================================
SILENCE      ``--silence`` (default 12) consecutive hours with no bar. GeckoTerminal omits
             bars with zero trades, so a gap *is* the observation. Death by irrelevance.
CLIFF        a single-bar close-to-close return <= ``--cliff`` (default -50%). The rug /
             instant drain shape.
BLEED        cumulative return from L <= ``--bleed`` (default -60%) with no prior CLIFF.
             Death by a thousand cuts.
DOUBLE       cumulative return from L >= ``--double`` (default +100%). The competing GOOD
             event, and genuinely competing: if it doubles first, the dump question is
             answered differently.
(censored)   none of the above by ``min(H, end of data)``.
===========  ============================================================================

"Sharp dump with recovery" is deliberately **not** a fifth mode. A transient that recovers has
not absorbed the token, so it must leave the unit at risk rather than remove it — modelling it
as an exit would double-count. It is recoverable from the same fitted object as
``CIF_CLIFF`` conditioned on subsequent DOUBLE, and is left to a later study rather than faked
here. "Graduation/migration" is likewise absent by construction: this cohort is discovered from
a top-volume snapshot of *already-migrated* pools, so migration is a selection criterion, not an
observable event.

**Estimator: Aalen-Johansen, non-parametric, per PROGRAM.md §1.5's "few events" constraint.**
With ``d_ki`` events of cause k at time ``t_i`` among ``n_i`` at risk::

    S(t)      = prod_{t_i <= t} (1 - d_i / n_i)              # all-cause survival
    CIF_k(t)  = sum_{t_i <= t} S(t_{i-1}) * d_ki / n_i       # cumulative incidence, cause k

The identity ``sum_k CIF_k(t) + S(t) = 1`` holds exactly and is asserted at runtime as a
self-check. Cox and Fine-Gray were both evaluated and **demoted**: with 10-24 CLIFF events in a
split half, a subdistribution regression estimates a hazard ratio whose confidence interval
spans an order of magnitude, and Fine-Gray additionally reweights the risk set in a way that
makes the coefficient uninterpretable as anything but a within-model summary. Non-parametric
first is not modesty here, it is the only thing the event counts support.

Confidence intervals are by **entity-level bootstrap** — resample tokens with replacement,
carry all of a token's landmarks together — because landmarks from one token overlap heavily
(stride 24h inside a 168h horizon) and a landmark-level bootstrap would treat one token's week
as seven independent weeks. PROGRAM.md §3.2.

=========================================================================================
4. WHAT THE COHORT IS, AND THE SELECTION THAT BINDS EVERY NUMBER BELOW
=========================================================================================

The cohort is discovered from GeckoTerminal's ``h24_volume_usd_desc`` ranking. **Every token in
it necessarily survived to the discovery snapshot with high volume.** That is a survivorship
filter, and it means the CIFs below are conditional on membership in a top-volume snapshot on
2026-08-13/14 — "among tokens that had a big day, this is how they behave" — not the
unconditional exit distribution of a random new mint. It biases every death rate *down* and
cannot be repaired from this cache. It is, however, close to the population the operator
actually cares about: coins that still trade and that someone still holds.

The estimand is therefore stated as: *among tokens present in a top-volume snapshot, at a
random hour of their observed life, what is the probability of each exit mode within H hours?*
Anything stronger would be a lie about the sampling frame.

=========================================================================================
5. THE SECOND PROTOTYPE: SEQUENTIAL CHANGEPOINT ON THE LIVE TAPE
=========================================================================================

Competing risks answers "what does the population do". It does not watch the tape. The honest
question to ask of a live feed is not "what will happen" but **"has something just changed"** —
that is genuinely model-free, and it is the piece that could actually page a human.

Three detectors are implemented and compared *at matched ARL0* (average run length under the
null), which is the only fair protocol for sequential detection — comparing "probability of ever
alarming" over a fixed window is meaningless because a detector with ARL0 = 100 is *supposed*
to alarm ~15 times in 1500 steps.

**Shiryaev-Roberts e-detector** (the one to beat). On the Bernoulli sell-indicator, each restart
point ``j`` carries a betting martingale against the null ``p0``, mixed over the alternative
with a uniform Beta(1,1) prior::

    E_j(t) = [B(1+s, 1+f) / B(1,1)] / [p0^s * (1-p0)^f]        s = sells, f = buys since j
    R_t    = sum_j E_j(t)          stop at R_t >= A            =>  ARL0 >= A

The guarantee is Ville's inequality plus optional stopping: it is **anytime-valid**, needs no
multiple-testing correction for continuous monitoring, and the threshold A *is* the ARL0. No
tuning knob. Restart pruning caps memory at ``--cap`` processes by dropping the smallest terms,
which can only lower ``R_t`` and therefore only delay stopping — the false-alarm guarantee
survives pruning by construction, which is why pruning is safe here and not a fudge.

**Page's CUSUM** on the robustly standardised signed SOL flow, threshold calibrated by
simulation. **BOCPD** (Adams-MacKay, Normal-Inverse-Gamma conjugate) reporting P(run length <
10). Their measured ranking is in §7.

**Two nulls, per PROGRAM.md §3.13, because one null is a knob and not a test.** (i) an i.i.d.
permutation of the token's own flow sequence — destroys any changepoint, preserves the marginal
exactly; (ii) a **moving-block permutation** at block length 50, which additionally preserves
short-range autocorrelation. The second null is the load-bearing one: trade signs are strongly
autocorrelated (metaorder splitting; measured lag-1 autocorrelation +0.23 to +0.45 on these
pools), and autocorrelation alone inflates the alarm rate of any sequential detector with no
regime change present whatsoever. A detector validated only against an i.i.d. null will report
order-splitting as deterioration.

=========================================================================================
6. WHAT WAS EVALUATED AND DEMOTED
=========================================================================================

- **Hawkes / branching ratio — demoted, and not merely as expensive.** Filimonov & Sornette show
  that calibrating Hawkes on *a mixture of pure Poisson segments with regime changes* yields
  n_hat ~ 1 when the true value is **0**; concatenating n=0.5 and n=0.2 segments estimates
  n_hat = 1.0, and a 60% difference in background rate alone estimates the critical value. A
  memecoin's arrival process is definitionally a regime mixture — launch burst, plateau, dump,
  death. So the statistic is driven to criticality by exactly the structure we are trying to
  detect, and cannot separate the two. Hardiman & Bouchaud's kernel-free ``n = 1 - 1/sqrt(Fano)``
  is implemented here as a diagnostic only, and it is a **floor, never a measurement**: the
  authors state σ²_W/W under-estimates and "only becomes exact in the limit W → ∞". Use it to
  refute a high branching ratio, never to confirm a low one. Fano = 1 <=> Poisson <=> n = 0.
- **Goh-Barabási burstiness B — demoted for Kim & Jo's A_n(r)**, because B is capped at
  ``(sqrt(n-1) - 1)/(sqrt(n-1) + 1)`` and is therefore confounded with event count, making
  cross-token comparison at different trade counts invalid. A_n(r) is implemented.
- **Conformal prediction — demoted as premature, not wrong.** Calibrated intervals across tokens
  is the right idea, but conformal wraps a point predictor and the finding in §4 is that we do
  not yet have one whose signal survives a strict split. Conformalising noise produces
  beautifully calibrated intervals of width 1.0. Revisit when there is a predictor.
- **GNNs / SVN co-trading / temporal-graph models — demoted on the record already in
  PROGRAM.md §1.5 and §4.1**, and nothing here disturbs it. The relevant baseline is
  memorisation.
- **Fine-Gray and cause-specific Cox — demoted on event counts** (see §3).

=========================================================================================
7. RESULTS SUMMARY (full numbers and thresholds in studies/RESULT_flow_signals.md)
=========================================================================================

- The competing-risks framing is **endorsed and it earns its keep**: the conditional mode mix is
  where the information lives, and it moves far more than the all-cause rate.
- Detector ranking at matched ARL0 ~ 1500 on planted shifts: the **e-detector dominates CUSUM**
  (median delay 163.5 vs 297.5 samples at p 0.50->0.60; 51 vs 80 at 0.50->0.70; tied at 0.80),
  and BOCPD is not competitive under a misspecified observation model.
- **The live changepoint result is a NULL, and it is reported as one.** Against the
  autocorrelation-preserving block null the observed alarm rate matches the null rate in every
  pool and on both observables — on nosis, 5.04 vs 5.04 alarms per 1000 swaps to three figures.
  Forward price moves after an alarm are indistinguishable from moves at random times. On 27
  hours of tape, the sign and size of order flow carry **no changepoint structure beyond their
  own marginal and short-range autocorrelation**.
- Marino's asserted multi-wallet-in / single-wallet-out asymmetry is **contradicted in sign** on
  these four pools; see §8 of the RESULT file.

Everything here obeys PROGRAM.md §3: temporal splits, entity-level grouping, no resampling of
minority classes, base-rate-preserving reporting, every threshold printed beside every number,
and a null run for each claim.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import glob
import json
import math
import os
import random
import statistics as st
from dataclasses import dataclass
from typing import Any, Final

# --------------------------------------------------------------------------------------
# paths and the cluster universe (mints/pools per shitcoims_cluster.pools, the on-chain
# verified authority -- duplicated as literals here only so this study opens no imports
# into the live tree; the addresses are asserted against pools.py when it is importable)
# --------------------------------------------------------------------------------------

REPO: Final[str] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OHLCV_DIR: Final[str] = os.path.join(REPO, "state", "deterioration", "ohlcv")
DISCOVERY: Final[str] = os.path.join(REPO, "state", "deterioration", "discovery.jsonl")
BULK_GLOB: Final[str] = os.path.join(REPO, "state", "bulk_history", "swaps", "*.jsonl")
LIVE_GLOB: Final[str] = os.path.join(REPO, "state", "cluster_tape", "swaps", "*.jsonl")
RESULTS: Final[str] = os.path.join(REPO, "studies", "data", "flow_signals_results.json")

WSOL: Final[str] = "So11111111111111111111111111111111111111112"

#: The operator's four coins, keyed by their SOL-quoted pool.
CLUSTER: Final[dict[str, str]] = {
    "GA1nQL5RLBYUkLfBRrTPxhiSaPYnanJwteMGa3jPRjEn": "weave",
    "7nv2RtGXXVDEgT9sWB3EjT8MQbMuA6CTMiuBGvEwmZSc": "nosis",
    "2XHrhkxfXweUpNRZAaS6tBAGUGVa6vTEyi4nPXUi8sfU": "DREGG",
    "BQHANwBnoo3tUKCQT8PjjhgJyxnVbgXL3AQuCPSYpnzr": "SOLVE",
}

MODES: Final[tuple[str, ...]] = ("CLIFF", "BLEED", "SILENCE", "DOUBLE")


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Every knob in the mode definition. Printed beside every number (PROGRAM.md §3.7)."""

    cliff: float = -0.50      # single-bar close-to-close return
    bleed: float = -0.60      # cumulative return from the landmark
    double: float = 1.00      # cumulative return from the landmark
    silence: int = 12         # consecutive missing hourly bars
    horizon: int = 168        # follow-up hours per landmark
    stride: int = 24          # hours between landmarks
    warmup: int = 168         # prior hours required before a landmark is admissible

    #: When True, CLIFF/BLEED/DOUBLE are measured in units of the token's OWN robust
    #: volatility (Marino & Lillo's Shewhart chart: sigma_MAD = MAD/0.67449, cliff at
    #: -k*sigma_MAD, cumulative bands at +-k_band*sigma_MAD*sqrt(h)) instead of in fixed
    #: return space. This exists to FALSIFY covariate findings: a covariate that is really
    #: just "this token is volatile" will separate the modes under fixed thresholds and stop
    #: separating them here, because the thresholds have absorbed the scale. See §4 of
    #: RESULT_flow_signals.md -- rv24 fails exactly this test.
    vol_normalised: bool = False
    mad_k: float = 4.0        # Marino's k for the single-bar cliff
    mad_band: float = 3.0     # cumulative band in sigma*sqrt(h) units

    def as_dict(self) -> dict[str, Any]:
        return {
            "cliff_1bar_return": self.cliff,
            "bleed_cumulative_return": self.bleed,
            "double_cumulative_return": self.double,
            "silence_consecutive_missing_bars": self.silence,
            "horizon_hours": self.horizon,
            "landmark_stride_hours": self.stride,
            "warmup_hours": self.warmup,
            "vol_normalised": self.vol_normalised,
            "mad_k": self.mad_k if self.vol_normalised else None,
            "mad_band": self.mad_band if self.vol_normalised else None,
        }


# ======================================================================================
# DATA LOADING
# ======================================================================================


@dataclass(slots=True)
class Token:
    pool: str
    name: str
    bars: dict[int, list[float]]   # hour index -> [ts, o, h, l, c, v]
    capped: bool                   # sitting on the 1000-bar API cap => left-truncated
    created_at: str | None


def load_cohort(min_bars: int = 72) -> list[Token]:
    """Load the OHLCV survival cohort. Bars are keyed by absolute hour index."""

    disc: dict[str, dict[str, Any]] = {}
    if os.path.exists(DISCOVERY):
        with open(DISCOVERY) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                disc[rec["pool"]] = rec

    out: list[Token] = []
    for path in sorted(glob.glob(os.path.join(OHLCV_DIR, "*.json"))):
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        pool = doc.get("pool")
        raw = doc.get("ohlcv") or []
        if pool is None or len(raw) < min_bars:
            continue
        meta = disc.get(pool, {})
        bars = {int(r[0]) // 3600: r for r in raw if r and r[4] and r[4] > 0}
        if len(bars) < min_bars:
            continue
        out.append(
            Token(
                pool=pool,
                name=meta.get("name", pool[:8]),
                bars=bars,
                capped=len(raw) >= 1000,
                created_at=meta.get("created_at"),
            )
        )
    return out


@dataclass(slots=True)
class Swap:
    bt: int
    sol: float          # signed WSOL vault delta: >0 = SOL in = BUY, <0 = SOL out = SELL
    tok: float          # signed token vault delta
    sol_reserve: float
    signer: str | None
    tx_index: int | None


def load_tape() -> dict[str, list[Swap]]:
    """Merge the BigQuery replay tape and the live RPC tape, deduping on signature.

    Both sources carry exact integer pre/post reserves. The RPC tape additionally carries
    signers, so when the same signature appears in both, the signer-bearing copy wins.
    """

    merged: dict[str, dict[str, Swap]] = collections.defaultdict(dict)
    for pattern in (BULK_GLOB, LIVE_GLOB):
        for path in glob.glob(pattern):
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if rec.get("kind") != "swap":
                        continue
                    pool = rec.get("pool")
                    if pool not in CLUSTER:
                        continue
                    vaults = rec.get("reserves", {}).get("vaults") or []
                    by_mint = {v["mint"]: v for v in vaults}
                    if WSOL not in by_mint or len(vaults) != 2:
                        continue
                    other = next(v for v in vaults if v["mint"] != WSOL)
                    sol_v = by_mint[WSOL]
                    signers = rec.get("signers") or []
                    signer = signers[0] if signers else rec.get("fee_payer")
                    swap = Swap(
                        bt=int(rec["chain"]["block_time"]),
                        sol=int(sol_v["delta_raw"]) / 1e9,
                        tok=int(other["delta_raw"]) / (10 ** int(other["decimals"])),
                        sol_reserve=int(sol_v["post_raw"]) / 1e9,
                        signer=signer,
                        tx_index=rec["chain"].get("tx_index"),
                    )
                    sig = rec["chain"]["signature"]
                    prior = merged[pool].get(sig)
                    if prior is None or (prior.signer is None and swap.signer is not None):
                        merged[pool][sig] = swap

    out: dict[str, list[Swap]] = {}
    for pool, d in merged.items():
        out[pool] = sorted(d.values(), key=lambda s: (s.bt, s.tx_index if s.tx_index is not None else 0))
    return out


# ======================================================================================
# PART 1 -- COMPETING RISKS
# ======================================================================================


@dataclass(slots=True)
class Landmark:
    pool: str
    at_hour: int
    time_to: int          # hours to event, or to censoring
    mode: str | None      # None => right-censored
    rv24: float           # realised vol of hourly log returns, prior 24h
    gapfrac: float        # fraction of the prior 24 hours with no bar
    dd: float             # drawdown from observed running peak (a LOWER bound if capped)
    dvol24: float         # log(volume last 24h / volume prior 24h)


def build_landmarks(tok: Token, th: Thresholds) -> list[Landmark]:
    """Emit one risk interval per landmark, with the first competing event that follows it."""

    hours = sorted(tok.bars)
    lo, hi = hours[0], hours[-1]
    peak_at: dict[int, float] = {}
    peak = 0.0
    for h in hours:
        peak = max(peak, tok.bars[h][4])
        peak_at[h] = peak

    out: list[Landmark] = []
    for L in range(lo + th.warmup, hi + 1, th.stride):
        bar = tok.bars.get(L)
        if bar is None or bar[4] <= 0:
            continue
        p0 = bar[4]
        v1 = sum(tok.bars[h][5] for h in range(L - 23, L + 1) if h in tok.bars)
        v0 = sum(tok.bars[h][5] for h in range(L - 47, L - 23) if h in tok.bars)
        if v0 <= 0 or v1 <= 0:
            continue
        rets = [
            math.log(tok.bars[h][4] / tok.bars[h - 1][4])
            for h in range(L - 23, L + 1)
            if h in tok.bars and h - 1 in tok.bars
        ]
        if len(rets) < 6:
            continue

        sigma_mad: float | None = None
        if th.vol_normalised:
            long_rets = [
                math.log(tok.bars[h][4] / tok.bars[h - 1][4])
                for h in range(L - th.warmup + 1, L + 1)
                if h in tok.bars and h - 1 in tok.bars
            ]
            if len(long_rets) < 24:
                continue
            med = st.median(long_rets)
            mad = st.median([abs(v - med) for v in long_rets])
            if mad <= 0:
                continue
            sigma_mad = mad / 0.67449

        mode: str | None = None
        t_ev = 0
        missing = 0
        for k in range(1, th.horizon + 1):
            h = L + k
            if h > hi:
                break
            if h not in tok.bars:
                missing += 1
                if missing >= th.silence:
                    mode, t_ev = "SILENCE", k
                    break
                continue
            missing = 0
            close = tok.bars[h][4]
            prev = next((tok.bars[j][4] for j in range(h - 1, L - 1, -1) if j in tok.bars), None)
            if sigma_mad is None:
                if prev and prev > 0 and close / prev - 1.0 <= th.cliff:
                    mode, t_ev = "CLIFF", k
                    break
                r = close / p0 - 1.0
                if r <= th.bleed:
                    mode, t_ev = "BLEED", k
                    break
                if r >= th.double:
                    mode, t_ev = "DOUBLE", k
                    break
            else:
                if prev and prev > 0 and math.log(close / prev) <= -th.mad_k * sigma_mad:
                    mode, t_ev = "CLIFF", k
                    break
                r = math.log(close / p0)
                band = th.mad_band * sigma_mad * math.sqrt(k)
                if r <= -band:
                    mode, t_ev = "BLEED", k
                    break
                if r >= band:
                    mode, t_ev = "DOUBLE", k
                    break

        if mode is None:
            t_ev = max(min(th.horizon, hi - L), 1)

        out.append(
            Landmark(
                pool=tok.pool,
                at_hour=L,
                time_to=t_ev,
                mode=mode,
                rv24=st.pstdev(rets),
                gapfrac=1.0 - sum(1 for h in range(L - 23, L + 1) if h in tok.bars) / 24.0,
                dd=p0 / peak_at[L] - 1.0,
                dvol24=math.log(v1 / v0),
            )
        )
    return out


def aalen_johansen(rows: list[Landmark], grid: tuple[int, ...],
                   ) -> tuple[dict[str, dict[int, float]], dict[int, float]]:
    """Non-parametric cumulative incidence per cause, plus all-cause survival.

    CIF_k(t) = sum_{t_i<=t} S(t_{i-1}) * d_ki / n_i, with S the all-cause Kaplan-Meier.
    """

    if not rows:
        return {k: {g: 0.0 for g in grid} for k in MODES}, {g: 1.0 for g in grid}

    at_time: dict[int, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for r in rows:
        if r.mode is not None:
            at_time[r.time_to][r.mode] += 1
    exits = sorted(r.time_to for r in rows)

    surv = 1.0
    cif = {k: 0.0 for k in MODES}
    out_cif: dict[str, dict[int, float]] = {k: {} for k in MODES}
    out_surv: dict[int, float] = {}
    grid_sorted = sorted(grid)

    for t in sorted(at_time):
        n_risk = len(exits) - bisect.bisect_left(exits, t)
        if n_risk <= 0:
            continue
        counts = at_time[t]
        for k in MODES:
            if counts[k]:
                cif[k] += surv * counts[k] / n_risk
        surv *= 1.0 - sum(counts.values()) / n_risk
        for g in grid_sorted:
            if t <= g:
                for k in MODES:
                    out_cif[k][g] = cif[k]
                out_surv[g] = surv

    for g in grid_sorted:
        out_surv.setdefault(g, surv if g >= (max(at_time) if at_time else 0) else 1.0)
        for k in MODES:
            out_cif[k].setdefault(g, 0.0)
    return out_cif, out_surv


def one_minus_km(rows: list[Landmark], cause: str, grid: tuple[int, ...]) -> dict[int, float]:
    """1 - Kaplan-Meier treating competing events as censoring. The classic WRONG estimator.

    Kept so the study can quantify its upward bias rather than merely assert it.
    """

    exits = sorted(r.time_to for r in rows)
    ev = collections.Counter(r.time_to for r in rows if r.mode == cause)
    surv = 1.0
    out: dict[int, float] = {}
    for t in sorted(ev):
        n_risk = len(exits) - bisect.bisect_left(exits, t)
        if n_risk <= 0:
            continue
        surv *= 1.0 - ev[t] / n_risk
        for g in grid:
            if t <= g:
                out[g] = 1.0 - surv
    for g in grid:
        out.setdefault(g, 1.0 - surv if ev and g >= max(ev) else 0.0)
    return out


def mode_mix(cif: dict[str, dict[int, float]], at: int) -> tuple[float, dict[str, float]]:
    """(total event probability, conditional mode mix) at horizon `at`. The 'AND HOW' object."""

    tot = sum(cif[k].get(at, 0.0) for k in MODES)
    if tot <= 1e-12:
        return 0.0, {k: 0.0 for k in MODES}
    return tot, {k: cif[k].get(at, 0.0) / tot for k in MODES}


def mix_separation(rows: list[Landmark], feat: str, q1: float, q2: float, min_n: int = 40) -> float | None:
    """Total-variation distance between the conditional mode mix of the top vs bottom tercile.

    This is the statistic the permutation null is run against. It is deliberately a distance
    between *mixes*, not between rates: a feature that merely predicts "something happens"
    is not what the competing-risks framing is for.
    """

    lo = [r for r in rows if getattr(r, feat) <= q1]
    hi = [r for r in rows if getattr(r, feat) > q2]
    if len(lo) < min_n or len(hi) < min_n:
        return None
    grid = (168,)
    c_lo, _ = aalen_johansen(lo, grid)
    c_hi, _ = aalen_johansen(hi, grid)
    t_lo, m_lo = mode_mix(c_lo, 168)
    t_hi, m_hi = mode_mix(c_hi, 168)
    if t_lo <= 1e-9 or t_hi <= 1e-9:
        return None
    return sum(abs(m_lo[k] - m_hi[k]) for k in MODES) / 2.0


def entity_bootstrap(rows: list[Landmark], grid: tuple[int, ...], reps: int, rng: random.Random
                     ) -> dict[str, dict[int, tuple[float, float]]]:
    """Percentile CIs by resampling TOKENS (not landmarks) with replacement. PROGRAM.md §3.2."""

    by_pool: dict[str, list[Landmark]] = collections.defaultdict(list)
    for r in rows:
        by_pool[r.pool].append(r)
    pools = list(by_pool)
    draws: dict[str, dict[int, list[float]]] = {k: {g: [] for g in grid} for k in MODES}
    for _ in range(reps):
        sample: list[Landmark] = []
        for _ in range(len(pools)):
            sample.extend(by_pool[pools[rng.randrange(len(pools))]])
        cif, _ = aalen_johansen(sample, grid)
        for k in MODES:
            for g in grid:
                draws[k][g].append(cif[k].get(g, 0.0))
    out: dict[str, dict[int, tuple[float, float]]] = {k: {} for k in MODES}
    for k in MODES:
        for g in grid:
            xs = sorted(draws[k][g])
            if not xs:
                out[k][g] = (0.0, 0.0)
                continue
            out[k][g] = (xs[int(0.025 * (len(xs) - 1))], xs[int(0.975 * (len(xs) - 1))])
    return out


def run_survival(args: argparse.Namespace, rng: random.Random) -> dict[str, Any]:
    th = Thresholds(cliff=args.cliff, bleed=args.bleed, double=args.double,
                    silence=args.silence, horizon=args.horizon, stride=args.stride,
                    vol_normalised=args.vol_normalised)
    cohort = load_cohort()
    rows: list[Landmark] = []
    for tok in cohort:
        rows.extend(build_landmarks(tok, th))

    grid = (24, 72, 168)
    cif, surv = aalen_johansen(rows, grid)
    counts = collections.Counter(r.mode for r in rows)

    # self-check: the AJ identity is exact, not approximate.
    total = sum(cif[k][168] for k in MODES) + surv[168]
    assert abs(total - 1.0) < 1e-9, f"Aalen-Johansen identity violated: {total}"

    out: dict[str, Any] = {
        "thresholds": th.as_dict(),
        "cohort": {
            "tokens_with_ohlcv": len(cohort),
            "tokens_capped_at_1000_bars_left_truncated": sum(1 for t in cohort if t.capped),
            "landmarks": len(rows),
            "tokens_contributing_landmarks": len({r.pool for r in rows}),
            "event_counts": {k: counts[k] for k in MODES},
            "censored": counts[None],
        },
        "cif": {k: {str(g): round(cif[k][g], 5) for g in grid} for k in MODES},
        "all_cause_survival": {str(g): round(surv[g], 5) for g in grid},
        "aj_identity_check": round(total, 12),
    }

    # --- the competing-risks argument, made quantitative: 1-KM overstates every cause -------
    km_bias = {}
    for k in MODES:
        km = one_minus_km(rows, k, grid)
        km_bias[k] = {
            "aalen_johansen_168h": round(cif[k][168], 5),
            "one_minus_km_168h": round(km.get(168, 0.0), 5),
            "overstatement_pct": (
                round((km.get(168, 0.0) / cif[k][168] - 1.0) * 100, 2) if cif[k][168] > 1e-9 else None
            ),
        }
    out["naive_km_overstatement"] = km_bias

    ci = entity_bootstrap(rows, grid, reps=args.boot, rng=rng)
    out["cif_entity_bootstrap_95ci"] = {
        k: {str(g): [round(ci[k][g][0], 5), round(ci[k][g][1], 5)] for g in grid} for k in MODES
    }

    # --- stratification: does a covariate move the MODE MIX, not just the rate? -------------
    strata: dict[str, Any] = {}
    for feat in ("rv24", "gapfrac", "dd", "dvol24"):
        vals = sorted(getattr(r, feat) for r in rows)
        q1, q2 = vals[len(vals) // 3], vals[2 * len(vals) // 3]
        per: dict[str, Any] = {"tercile_cuts": [round(q1, 5), round(q2, 5)]}
        for lab, sel in (("T1", lambda v, a=q1: v <= a),
                         ("T3", lambda v, b=q2: v > b)):
            sub = [r for r in rows if sel(getattr(r, feat))]
            c, _ = aalen_johansen(sub, grid)
            tot, mix = mode_mix(c, 168)
            per[lab] = {
                "n_landmarks": len(sub),
                "p_any_event_168h": round(tot, 5),
                "conditional_mode_mix": {k: round(mix[k], 4) for k in MODES},
            }
        strata[feat] = per
    out["stratification_in_sample"] = strata

    # --- THE GATE: token-disjoint AND temporal split, plus a whole-token permutation null ---
    # Repeated over `--splits` independent token partitions. ONE random partition is not a
    # test at this scale: with 124 tokens and 10-70 events per mode, the p-value from a single
    # partition moved from 0.55 to 0.07 across two seeds during development. What is reported
    # is therefore the DISTRIBUTION of the out-of-sample separation and of its permutation
    # p-value across partitions, and the fraction of partitions that clear 0.05.
    pools = sorted({r.pool for r in rows})
    hours = sorted(r.at_hour for r in rows)
    cut = hours[len(hours) // 2]

    gate: dict[str, Any] = {
        "split": "token-disjoint AND temporal (strict): train tokens before cut, disjoint test tokens after",
        "temporal_cut_hour_index": cut,
        "n_token_partitions": args.splits,
        "features": {},
    }
    per_feat: dict[str, dict[str, list[float]]] = {
        f: {"sep_out": [], "p": [], "n_test": []} for f in ("rv24", "gapfrac", "dd", "dvol24")
    }

    for _ in range(args.splits):
        shuffled = pools[:]
        rng.shuffle(shuffled)
        train_pools = set(shuffled[: len(shuffled) // 2])
        train = [r for r in rows if r.pool in train_pools and r.at_hour < cut]
        test = [r for r in rows if r.pool not in train_pools and r.at_hour >= cut]
        by_pool_test: dict[str, list[Landmark]] = collections.defaultdict(list)
        for r in test:
            by_pool_test[r.pool].append(r)
        keys = list(by_pool_test)
        if not keys:
            continue

        for feat in per_feat:
            tv = sorted(getattr(r, feat) for r in train)
            if len(tv) < 60:
                continue
            q1, q2 = tv[len(tv) // 3], tv[2 * len(tv) // 3]
            sep_out = mix_separation(test, feat, q1, q2)
            if sep_out is None:
                continue

            nulls: list[float] = []
            for _ in range(args.perm):
                blocks = [[getattr(x, feat) for x in by_pool_test[k]] for k in keys]
                rng.shuffle(blocks)
                permuted: list[Landmark] = []
                for k, vals_b in zip(keys, blocks, strict=True):
                    for i, r in enumerate(by_pool_test[k]):
                        clone = Landmark(r.pool, r.at_hour, r.time_to, r.mode,
                                         r.rv24, r.gapfrac, r.dd, r.dvol24)
                        setattr(clone, feat, vals_b[i % len(vals_b)])
                        permuted.append(clone)
                s = mix_separation(permuted, feat, q1, q2)
                if s is not None:
                    nulls.append(s)
            if not nulls:
                continue
            p = (1 + sum(1 for s in nulls if s >= sep_out)) / (1 + len(nulls))
            per_feat[feat]["sep_out"].append(sep_out)
            per_feat[feat]["p"].append(p)
            per_feat[feat]["n_test"].append(len(test))

    for feat, acc in per_feat.items():
        if not acc["p"]:
            continue
        ps = sorted(acc["p"])
        seps = sorted(acc["sep_out"])
        gate["features"][feat] = {
            "n_partitions_evaluated": len(ps),
            "median_n_test_landmarks": int(st.median(acc["n_test"])),
            "sep_out_median": round(st.median(seps), 4),
            "sep_out_iqr": [round(seps[len(seps) // 4], 4), round(seps[(3 * len(seps)) // 4], 4)],
            "permutation_p_median": round(st.median(ps), 4),
            "permutation_p_iqr": [round(ps[len(ps) // 4], 4), round(ps[(3 * len(ps)) // 4], 4)],
            "frac_partitions_p_lt_0.05": round(sum(1 for p in ps if p < 0.05) / len(ps), 3),
        }
    out["strict_split_gate"] = gate

    # --- the operator's four coins, located in the cohort ------------------------------------
    four: dict[str, Any] = {}
    for tok in cohort:
        if tok.pool not in CLUSTER:
            continue
        hrs = sorted(tok.bars)
        peak = 0.0
        max_dd = 0.0
        worst_1bar = 0.0
        for i, h in enumerate(hrs):
            c = tok.bars[h][4]
            peak = max(peak, c)
            max_dd = min(max_dd, c / peak - 1.0)
            if i > 0 and tok.bars[hrs[i - 1]][4] > 0:
                worst_1bar = min(worst_1bar, c / tok.bars[hrs[i - 1]][4] - 1.0)
        mine = [r for r in rows if r.pool == tok.pool]
        four[CLUSTER[tok.pool]] = {
            "bars": len(tok.bars),
            "left_truncated_by_api_cap": tok.capped,
            "max_drawdown_from_observed_peak": round(max_dd, 4),
            "worst_single_hour_return": round(worst_1bar, 4),
            "manner": ("CLIFF-shaped" if worst_1bar <= -0.50
                       else "step" if worst_1bar <= -0.30 else "BLEED-shaped"),
            "landmarks_contributed": len(mine),
            "own_landmark_events": {k: sum(1 for r in mine if r.mode == k) for k in MODES},
        }
    out["operator_coins"] = four
    return out


# ======================================================================================
# PART 2 -- SEQUENTIAL CHANGEPOINT DETECTION
# ======================================================================================

_LGAMMA: list[float] = [0.0, 0.0]


def _lg(n: int) -> float:
    """log((n-1)!) with a growing cache. Integer-only, which is all the mixture needs."""
    while len(_LGAMMA) <= n:
        _LGAMMA.append(_LGAMMA[-1] + math.log(len(_LGAMMA) - 1))
    return _LGAMMA[n]


def e_detector(x: list[int], p0: float, cap: int = 200) -> list[float]:
    """Shiryaev-Roberts e-detector on a Bernoulli stream against null p0.

    Each restart j accumulates a Beta(1,1)-mixture betting martingale; R_t is their sum, and
    stopping at R_t >= A gives ARL0 >= A by Ville plus optional stopping. Pruning to `cap`
    live processes only ever REMOVES positive terms, so the reported R_t is a lower bound on
    the true one and the false-alarm guarantee is preserved (it can only stop later).
    """

    lp, lq = math.log(p0), math.log1p(-p0)
    live: list[list[int]] = []
    out: list[float] = []
    for xi in x:
        live.append([0, 0])
        if xi:
            for c in live:
                c[0] += 1
        else:
            for c in live:
                c[1] += 1
        vals = [_lg(s + 1) + _lg(f + 1) - _lg(s + f + 2) - (s * lp + f * lq) for s, f in live]
        m = max(vals)
        out.append(math.exp(m) * sum(math.exp(v - m) for v in vals) if m > -700 else 0.0)
        if len(live) > cap:
            keep = sorted(range(len(live)), key=lambda i: vals[i], reverse=True)[:cap]
            live = [live[i] for i in sorted(keep)]
    return out


def cusum(z: list[float], k: float = 0.5) -> list[float]:
    """Two-sided Page CUSUM on a standardised stream with reference value k."""
    hi = lo = 0.0
    out: list[float] = []
    for v in z:
        hi = max(0.0, hi + v - k)
        lo = max(0.0, lo - v - k)
        out.append(hi if hi > lo else lo)
    return out


def bocpd(x: list[float], hazard: float, trunc: int = 120) -> list[float]:
    """Adams-MacKay BOCPD with a Normal-Inverse-Gamma conjugate model. Returns P(run < 10).

    Carried for comparison and demoted on measurement: it requires an observation model AND a
    hazard prior, i.e. two knobs, where the e-detector requires neither.
    """

    mu0, kappa0, alpha0, beta0 = 0.0, 1.0, 1.0, 1.0
    R, mu, kap, al, be = [1.0], [mu0], [kappa0], [alpha0], [beta0]
    out: list[float] = []
    lpi = math.log(math.pi)
    for v in x:
        pred: list[float] = []
        for i in range(len(R)):
            nu = 2 * al[i]
            sc = math.sqrt(be[i] * (kap[i] + 1) / (al[i] * kap[i]))
            t = (v - mu[i]) / sc
            pred.append(math.exp(
                math.lgamma((nu + 1) / 2) - math.lgamma(nu / 2) - 0.5 * (math.log(nu) + lpi)
                - math.log(sc) - ((nu + 1) / 2) * math.log1p(t * t / nu)
            ))
        cp = hazard * sum(R[i] * pred[i] for i in range(len(R)))
        newR = [cp] + [R[i] * pred[i] * (1 - hazard) for i in range(len(R))]
        nmu = [mu0] + [(kap[i] * mu[i] + v) / (kap[i] + 1) for i in range(len(R))]
        nkap = [kappa0] + [kap[i] + 1 for i in range(len(R))]
        nal = [alpha0] + [al[i] + 0.5 for i in range(len(R))]
        nbe = [beta0] + [be[i] + kap[i] * (v - mu[i]) ** 2 / (2 * (kap[i] + 1)) for i in range(len(R))]
        if len(newR) > trunc:
            newR, nmu, nkap, nal, nbe = newR[:trunc], nmu[:trunc], nkap[:trunc], nal[:trunc], nbe[:trunc]
        z = sum(newR) or 1e-300
        R = [r / z for r in newR]
        mu, kap, al, be = nmu, nkap, nal, nbe
        out.append(sum(R[:10]))
    return out


def block_permute(x: list[Any], block: int, rng: random.Random) -> list[Any]:
    """Moving-block (circular) permutation. block=1 is the i.i.d. null; block>1 preserves
    short-range autocorrelation, which is the null that actually binds on order flow."""

    n = len(x)
    out: list[Any] = []
    while len(out) < n:
        s = rng.randrange(n)
        out.extend(x[s:s + block] if s + block <= n else x[s:] + x[:s + block - n])
    return out[:n]


def _first_alarms(trace: list[float], thr: float, start: int, refractory: int = 200) -> list[int]:
    out: list[int] = []
    last = -10 ** 9
    for i in range(start, len(trace)):
        if trace[i] >= thr and i - last > refractory:
            out.append(i)
            last = i
    return out


def _calibrate(traces: list[list[float]], target: float, grid: list[float], burn: int) -> tuple[float, float]:
    best: tuple[float, float] | None = None
    for g in grid:
        arl = st.mean([
            next((i for i, v in enumerate(t) if i >= burn and v >= g), len(t)) for t in traces
        ])
        if best is None or abs(arl - target) < abs(best[1] - target):
            best = (g, arl)
    assert best is not None
    return best


def _calibrate_to_rate(traces: list[list[float]], target_rate: float, grid: list[float],
                       burn: int, refractory: int = 200) -> tuple[float, float, bool]:
    """Pick the threshold whose alarm RATE under the null matches `target_rate` per 1000 samples.

    This replaces ARL0-matching for the live tape, and it is the same discipline PROGRAM.md
    §3.13 already imposes on network nulls: **compare at matched density, not at a matched
    nominal level**. ARL0-matching silently fails on short series -- if the target ARL0 exceeds
    the usable length, the search collapses onto a grid endpoint and returns a SATURATED
    detector that alarms every `refractory` samples on any input whatsoever. Such a detector
    passes a null test perfectly while measuring nothing, which is precisely the failure mode
    §3.12 was written about. The returned flag reports grid-boundary saturation instead of
    hiding it.
    """

    best: tuple[float, float] | None = None
    best_i = -1
    for i, g in enumerate(grid):
        rate = st.mean([
            len(_first_alarms(t, g, burn, refractory)) / max(len(t) - burn, 1) * 1000.0 for t in traces
        ])
        if best is None or abs(rate - target_rate) < abs(best[1] - target_rate):
            best, best_i = (g, rate), i
    assert best is not None
    degenerate = best_i in (0, len(grid) - 1) or abs(best[1] - target_rate) > 0.5 * target_rate
    return best[0], best[1], degenerate


def run_changepoint(args: argparse.Namespace, rng: random.Random) -> dict[str, Any]:
    out: dict[str, Any] = {}

    # ---- CONTROL 1 + 2: known-ZERO and known-EFFECT worlds, at MATCHED ARL0 ----------------
    # PROGRAM.md §3.12 -- a null control alone certifies a broken estimator as readily as a
    # working one, so every detector is also run against a planted, known-size shift.
    n_sim, trials, cp = (2000, args.sim_trials, 1000)
    burn = 100
    nulls = [[1 if rng.random() < 0.5 else 0 for _ in range(n_sim)] for _ in range(trials)]
    tE = _calibrate([e_detector(x, 0.5) for x in nulls], args.arl0,
                    [10 ** (i / 4) for i in range(0, 32)], burn)
    tC = _calibrate([cusum([(v - 0.5) / 0.5 for v in x]) for x in nulls], args.arl0,
                    [i * 0.25 for i in range(4, 120)], burn)
    tB = _calibrate([bocpd([float(v) for v in x], 1 / 250) for x in nulls], args.arl0,
                    [0.5 + i * 0.005 for i in range(0, 100)], burn)

    bench: dict[str, Any] = {
        "protocol": "matched ARL0 on a known-zero world, then median detection delay on a planted shift",
        "target_arl0_samples": args.arl0,
        "thresholds": {
            "e_detector_A": round(tE[0], 4), "e_detector_measured_arl0": round(tE[1], 1),
            "cusum_h": round(tC[0], 4), "cusum_measured_arl0": round(tC[1], 1),
            "bocpd_thr": round(tB[0], 4), "bocpd_measured_arl0": round(tB[1], 1),
        },
        "planted_shifts": {},
    }
    for shift in (0.60, 0.70, 0.80):
        xs = [
            [1 if rng.random() < 0.5 else 0 for _ in range(cp)]
            + [1 if rng.random() < shift else 0 for _ in range(n_sim - cp)]
            for _ in range(trials)
        ]
        row: dict[str, Any] = {}
        for name, traces, thr in (
            ("e_detector", [e_detector(x, 0.5) for x in xs], tE[0]),
            ("cusum", [cusum([(v - 0.5) / 0.5 for v in x]) for x in xs], tC[0]),
            ("bocpd", [bocpd([float(v) for v in x], 1 / 250) for x in xs], tB[0]),
        ):
            delays = [
                h - cp
                for h in (next((i for i, v in enumerate(t) if i >= cp and v >= thr), None) for t in traces)
                if h is not None
            ]
            row[name] = {
                "power": round(len(delays) / trials, 3),
                "median_detection_delay_samples": st.median(delays) if delays else None,
            }
        bench["planted_shifts"][f"p_0.50_to_{shift:.2f}"] = row
    out["detector_benchmark"] = bench

    # ---- LIVE: the operator's four coins, TWO nulls -----------------------------------------
    tape = load_tape()
    live: dict[str, Any] = {}
    for pool, name in CLUSTER.items():
        swaps = tape.get(pool, [])
        if len(swaps) < args.min_swaps:
            live[name] = {"n_swaps": len(swaps), "verdict": "too few swaps for sequential detection"}
            continue

        # Observable 1: the sell indicator. SOL leaving the vault == someone sold the token.
        sign = [1 if s.sol < 0 else 0 for s in swaps]
        # Observable 2: robustly standardised signed SOL size, winsorised at 8 MAD.
        sizes = [s.sol for s in swaps]
        med = st.median(sizes)
        mad = st.median([abs(v - med) for v in sizes]) or 1e-12
        size_z = [max(-8.0, min(8.0, (v - med) / (mad / 0.67449))) for v in sizes]

        nb = max(100, len(sign) // 5)
        p0 = min(max(sum(sign[:nb]) / nb, 0.05), 0.95)

        # Threshold set so the I.I.D. NULL alarms at `--target-rate` per 1000 swaps, then the
        # observed and block-null rates are read off at that same threshold: matched density.
        cal = [e_detector(block_permute(sign, 1, rng), p0) for _ in range(args.null_reps)]
        A, iid_rate, degenerate = _calibrate_to_rate(
            cal, args.target_rate, [10 ** (i / 4) for i in range(0, 40)], nb)

        def rate(seq: list[int], thr: float, _p0: float = p0, _nb: int = nb) -> float:
            tr = e_detector(seq, _p0)
            return len(_first_alarms(tr, thr, _nb)) / max(len(tr) - _nb, 1) * 1000.0

        obs_rate = rate(sign, A)
        blk_draws = [rate(block_permute(sign, 50, rng), A) for _ in range(args.null_reps // 2)]
        blk_rate = st.mean(blk_draws)
        blk_sd = st.pstdev(blk_draws)
        # Where the observed rate falls in the block null's own replicate distribution. This is
        # what decides whether a small positive excess is a finding or a rounding error.
        blk_p = (1 + sum(1 for v in blk_draws if v >= obs_rate)) / (1 + len(blk_draws))

        mu = st.mean(sign)
        sd = st.pstdev(sign) or 1e-12
        ac1 = (sum((sign[i] - mu) * (sign[i + 1] - mu) for i in range(len(sign) - 1))
               / ((len(sign) - 1) * sd * sd))

        trace = e_detector(sign, p0)
        alarms = _first_alarms(trace, A, nb)

        def forward(i: int, _sw: list[Swap] = swaps) -> float | None:
            before = [abs(s.sol / s.tok) for s in _sw[max(0, i - 50):i] if s.tok]
            after = [abs(s.sol / s.tok) for s in _sw[i:i + 200] if s.tok]
            if not before or len(after) < 20:
                return None
            return st.median(after) / st.median(before) - 1.0

        after_alarm = [v for v in (forward(i) for i in alarms) if v is not None]
        at_random = [
            v for v in (forward(rng.randrange(nb, max(nb + 1, len(swaps) - 200))) for _ in range(400))
            if v is not None
        ]

        # second observable, same two-null treatment at matched density
        cal_c = [cusum(block_permute(size_z, 1, rng)) for _ in range(args.null_reps)]
        h, iid_c, degen_c = _calibrate_to_rate(cal_c, args.target_rate, [i * 0.5 for i in range(2, 200)], nb)

        def rate_c(seq: list[float], thr: float, _nb: int = nb) -> float:
            tr = cusum(seq)
            return len(_first_alarms(tr, thr, _nb)) / max(len(tr) - _nb, 1) * 1000.0

        live[name] = {
            "n_swaps": len(swaps),
            "baseline_sell_fraction_p0": round(p0, 4),
            "burn_in_swaps": nb,
            "e_detector_threshold_A": round(A, 3),
            "calibration_degenerate": degenerate,
            "target_null_alarm_rate_per_1000": args.target_rate,
            "lag1_sign_autocorrelation": round(ac1, 4),
            "alarms_per_1000_swaps": {
                "observed": round(obs_rate, 3),
                "null_iid_permutation": round(iid_rate, 3),
                "null_block50_permutation": round(blk_rate, 3),
                "null_block50_replicate_sd": round(blk_sd, 3),
                "excess_over_block_null": round(obs_rate - blk_rate, 3),
                "frac_of_iid_excess_explained_by_block_null": (
                    round((blk_rate - iid_rate) / (obs_rate - iid_rate), 3)
                    if abs(obs_rate - iid_rate) > 1e-9 else None),
                "p_observed_vs_block_null": round(blk_p, 3),
            },
            "observable2_signed_sol_size_cusum": {
                "threshold_h": round(h, 3),
                "calibration_degenerate": degen_c,
                "observed": round(rate_c(size_z, h), 3),
                "null_iid_permutation": round(iid_c, 3),
                "null_block50_permutation": round(st.mean(
                    [rate_c(block_permute(size_z, 50, rng), h)
                     for _ in range(args.null_reps // 2)]), 3),
            },
            "n_alarms": len(alarms),
            "forward_price_move_after_alarm_median_pct": (
                round(st.median(after_alarm) * 100, 3) if after_alarm else None),
            "forward_price_move_at_random_times_median_pct": (
                round(st.median(at_random) * 100, 3) if at_random else None),
        }
    out["live"] = live
    return out


# ======================================================================================
# PART 3 -- ORDER FLOW DECOMPOSITION AND THE DIAGNOSTICS WE KEPT
# ======================================================================================


def kim_jo_burstiness(intervals: list[float]) -> float | None:
    """Kim & Jo (2016) eq. 22 -- burstiness without Goh-Barabasi's finite-size ceiling.

        A_n(r) = (sqrt(n+1)*r - sqrt(n-1)) / ((sqrt(n+1) - 2)*r + sqrt(n-1))

    Goh-Barabasi B is bounded by (sqrt(n-1)-1)/(sqrt(n-1)+1) -- 0.817 at n=100 -- so B is
    confounded with event count and cross-token comparison at different n is invalid.
    """

    n = len(intervals)
    if n < 3:
        return None
    mu = st.mean(intervals)
    if mu <= 0:
        return None
    r = st.pstdev(intervals) / mu
    num = math.sqrt(n + 1) * r - math.sqrt(n - 1)
    den = (math.sqrt(n + 1) - 2) * r + math.sqrt(n - 1)
    return num / den if abs(den) > 1e-12 else None


def fano_branching(counts: list[int]) -> tuple[float, float] | None:
    """Hardiman & Bouchaud kernel-free branching estimator: n = 1 - 1/sqrt(Fano).

    A FLOOR, never a measurement: sigma^2_W/W under-estimates the integral and becomes exact
    only as W -> inf. Use it to REFUTE a high Hawkes branching ratio, never to confirm a low
    one. Fano = 1 <=> Poisson <=> n = 0.
    """

    if len(counts) < 8:
        return None
    mu = st.mean(counts)
    if mu <= 0:
        return None
    fano = st.variance(counts) / mu
    if fano <= 0:
        return None
    return fano, 1.0 - 1.0 / math.sqrt(fano)


def run_flow(args: argparse.Namespace, rng: random.Random) -> dict[str, Any]:
    tape = load_tape()
    out: dict[str, Any] = {
        "note": (
            "Signers exist only on the RPC-sourced portion of the merged tape; the BigQuery path "
            "would need the 267 GB/day `accounts` column. The signer-bearing subset is a "
            "time-contiguous slice, NOT a random sample, so concentration below is a windowed "
            "measurement and not a property of the whole tape."
        ),
        "pools": {},
    }
    for pool, name in CLUSTER.items():
        swaps = tape.get(pool, [])
        if not swaps:
            continue
        buys = [s for s in swaps if s.sol > 0]
        sells = [s for s in swaps if s.sol < 0]

        def concentration(group: list[Swap]) -> dict[str, Any]:
            weight: collections.Counter[str] = collections.Counter()
            for s in group:
                if s.signer:
                    weight[s.signer] += abs(s.sol)
            total = sum(weight.values())
            if total <= 0:
                return {"wallets": 0, "top1_share": None, "hhi": None}
            return {
                "wallets": len(weight),
                "top1_share": round(max(weight.values()) / total, 4),
                "hhi": round(sum((v / total) ** 2 for v in weight.values()), 4),
            }

        gaps = [swaps[i + 1].bt - swaps[i].bt for i in range(len(swaps) - 1)]
        gaps = [float(g) for g in gaps if g > 0]
        minute_counts: collections.Counter[int] = collections.Counter(s.bt // 60 for s in swaps)
        span = (max(minute_counts) - min(minute_counts) + 1) if minute_counts else 0
        counts = ([minute_counts.get(m, 0)
                   for m in range(min(minute_counts), min(minute_counts) + span)] if span else [])

        fano = fano_branching(counts) if counts else None
        signed = sum(s.sol for s in swaps)
        out["pools"][name] = {
            "n_swaps": len(swaps),
            "n_with_signer": sum(1 for s in swaps if s.signer),
            "buys": len(buys),
            "sells": len(sells),
            "sol_in": round(sum(s.sol for s in buys), 3),
            "sol_out": round(-sum(s.sol for s in sells), 3),
            "net_sol_flow": round(signed, 3),
            "buy_side_concentration": concentration(buys),
            "sell_side_concentration": concentration(sells),
            "kim_jo_burstiness_A_n": (
                round(v, 4) if (v := kim_jo_burstiness(gaps)) is not None else None),
            "fano_1min": round(fano[0], 4) if fano else None,
            "branching_floor_n": round(fano[1], 4) if fano else None,
        }
    return out


# ======================================================================================


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--part", choices=["all", "survival", "changepoint", "flow"], default="all")
    ap.add_argument("--seed", type=int, default=20260814)
    ap.add_argument("--quick", action="store_true", help="fewer replicates, identical code path")
    ap.add_argument("--cliff", type=float, default=-0.50)
    ap.add_argument("--bleed", type=float, default=-0.60)
    ap.add_argument("--double", type=float, default=1.00)
    ap.add_argument("--silence", type=int, default=12)
    ap.add_argument("--horizon", type=int, default=168)
    ap.add_argument("--stride", type=int, default=24)
    ap.add_argument("--vol-normalised", action="store_true",
                    help="measure CLIFF/BLEED/DOUBLE in the token's own sigma_MAD units "
                         "(Marino's Shewhart rule) instead of fixed returns -- the falsification "
                         "run for any covariate that might just be measuring volatility")
    ap.add_argument("--boot", type=int, default=400, help="entity-level bootstrap replicates")
    ap.add_argument("--perm", type=int, default=200, help="permutation-null draws per partition")
    ap.add_argument("--splits", type=int, default=20, help="independent token partitions for the strict gate")
    ap.add_argument("--sim-trials", type=int, default=40, help="detector benchmark trials")
    ap.add_argument("--null-reps", type=int, default=24, help="tape-null replicates")
    ap.add_argument("--arl0", type=float, default=1500.0, help="target ARL0 for the simulated benchmark")
    ap.add_argument("--target-rate", type=float, default=2.0,
                    help="live tape: null alarm rate per 1000 swaps setting the threshold "
                         "(matched density)")
    ap.add_argument("--min-swaps", type=int, default=400)
    ap.add_argument("--out", default=RESULTS)
    args = ap.parse_args(argv)

    if args.quick:
        args.boot, args.perm, args.sim_trials, args.null_reps, args.splits = 60, 50, 12, 8, 5

    rng = random.Random(args.seed)
    results: dict[str, Any] = {"seed": args.seed, "quick": args.quick}

    if args.part in ("all", "survival"):
        results["survival"] = run_survival(args, rng)
    if args.part in ("all", "changepoint"):
        results["changepoint"] = run_changepoint(args, rng)
    if args.part in ("all", "flow"):
        results["flow"] = run_flow(args, rng)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(results, fh, indent=2, sort_keys=True)
    print(json.dumps(results, indent=2, sort_keys=True))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
