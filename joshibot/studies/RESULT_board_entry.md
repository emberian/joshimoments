# RESULT: board entry as an attention shock — and the drawdown filter runs backwards

2026-08-14. `studies/board_entry.py` over `state/boards/` — 9.8 h of pump.fun board
membership recorded at 30 s, 76,349 rows, **35,031 board entries**, 8,764 mints in view.

## Why this event and not graduation

Board entry is frequent, timestamped, exogenously delivered by the platform, and has an
obvious causal mechanism. Graduation is a 0.63%-base-rate one-shot that the literature
could not predict. Entry gives ~35,000 events in ten hours; graduation gives a handful
a month. **The event study needs no model at all** — only the conditioning variable does.

## The operator's hypothesis, and its refutation

The hypothesis was: trending coins are usually in a drawdown, so buy the dip as the
attention arrives and take a mini profit. **The premise is right and the trade is
backwards.**

Median board member is **51–60% off its all-time-high market cap** — the "overall
downslump" is real and measured. But splitting entries at the median drawdown:

| | 5 min | 15 min | 30 min | 1 h | 2 h |
|---|---|---|---|---|---|
| **Deep drawdown (≥50% off ATH)** median | −0.02% | −0.02% | −0.05% | −0.30% | **−0.45%** |
| p(up) | 48% | 49% | 48% | 43% | **44%** |
| **Shallow drawdown (<50% off ATH)** median | +0.44% | +1.18% | +2.26% | +3.85% | **+5.73%** |
| p(up) | 69% | 73% | 74% | 76% | **76%** |
| *null — same times, random coin in view* median | +0.02% | +0.03% | +0.07% | +0.08% | +0.12% |
| *null* p(up) | 57% | 57% | 57% | 59% | 62% |

The null sits **between** the two groups. So deep-drawdown entries *underperform a
randomly chosen coin already in view*, and shallow-drawdown entries beat it. This is
**continuation, not reversion**: a coin that joins a board while near its highs keeps
going; one that joins while beaten down does not bounce.

**Censoring strengthens the finding rather than threatening it.** Observation ends when a
coin leaves the boards, and collapse is a reason to leave — so every return here is
conditioned on survival-in-view and biased **up**. Deep-drawdown entries are censored
*more* (65→81% across horizons) than shallow (48→77%). The group that looks flat is the
group we lose sight of faster, so its true performance is worse than the table shows.

## What survives as a signal

Entries beat the null on median at every horizon (+0.26% vs +0.02% at 5 min; +2.02% vs
+0.12% at 2 h), but on p(up) the margin is thinner (64% vs 57%) because *coins visible on
boards are already a rising population*. The event carries information; most of the
apparent edge is selection into the boards, not the entry moment itself.

The usable version is the **conditional** one: entry **and** near-highs. That combination
reaches 76% p(up) and +5.73% median at two hours, against a 62% / +0.12% null.

## Caveats, none of them small

- **One 9.8-hour window, one regime.** No temporal split is possible yet; §3 rule 1 is
  unmet. This is a lead, not a finding, until it survives a held-out day.
- **Returns are market-cap ratios from board snapshots**, not fills. No friction, no
  slippage, no landing. At the measured ~2.4% round-trip friction for a $2.45 clip, the
  5-minute median (+0.44% shallow) does **not** clear costs; the 1–2 h horizons do.
- **Informative censoring** is bounded but not corrected. A survival treatment with
  leaving-the-board as a competing risk is the right next form — the machinery already
  exists in `studies/flow_signals.py`.
- The first null was **broken** and is recorded here rather than quietly replaced:
  permuting entry *times* put many draws before a coin's first observation, so `value_at`
  returned the entry point itself, manufacturing exact 0.0 returns — a 0.00% median and a
  p(up) deflated by counting zeros as not-up. Permuting *mints* at fixed times is the
  correct construction and is what the table above uses.

## Next

1. A second day of tape, held out, to make the temporal split possible.
2. Add friction to the return so the horizon question is answered in net terms.
3. Model board exit as a competing risk rather than as censoring to be apologised for.
