# Project frame

Status: exploratory, before engineering commitment.

## The object being measured

The target is not a standalone predictive model. It is Ember's composite
selection–execution–management process operating inside a changing market:

```text
whole market
  -> surfaced candidates
  -> human attention
  -> inspection and interpretation
  -> an armed disposition
  -> entries, exits, partial exits, flat intervals, and re-entries
  -> retained or changed exposure
  -> eventual resolution and retrospective account
```

Every arrow is part of the policy and therefore part of the required evidence. A study of
returns conditional on a small projection of market features does not identify the value of
the composite process.

The atomic unit is an **episode**, not a position. An episode may contain several inventory
intervals and several realized clips. The operator may exit after reading a graph, continue
watching while flat, and re-enter later. A crackle is an entry and early-management mode; it
does not determine the position's entire lifecycle.

## Initial strategy families

These are independent books sharing one sensorium, not one policy:

1. **Crackle** — the operator selects a coin; automation watches for a locally meaningful
   entry and manages executable micro-profit opportunities.
2. **Retained runner** — some exposure remains after partial realization because the coin may
   re-rate or "send." The remainder is economically live, never "free money."
3. **Fancoin/social transition** — exposure to an incomplete transition from unofficial
   reference through community formation, identity claim, participation, endorsement,
   fragmentation, persistence, or decay.
4. **LP inventory** — liquidity positions as schedules of contingent trades whose capital,
   token composition, bin weights, and opportunity cost can be actively managed.

More dispositions and crackle types are expected to emerge. The system must preserve raw
observations and free-form explanations so an inadequate early taxonomy can be replaced.

## The attention funnel

For every decision time, preserve the denominators:

- the market universe observed by the census;
- the candidates presented by the product and their ranking;
- what entered the viewport;
- what Ember opened, compared, annotated, dismissed, armed, or traded;
- which alternatives were contemporaneously available;
- what the system knew at that time, distinguished from later enrichment.

This is required to separate operator selection, platform surfacing, timing, management,
execution, regime, and luck. Human attention is an adaptive sensor and a source of selection
bias at the same time.

## Required accounting semantics

The system must distinguish:

- orders, transactions, fills, token lots, and inventory intervals;
- an episode from any one position interval;
- gross proceeds, realized net PnL, remaining cost basis, current executable liquidation
  value, and opportunity cost;
- a partial exit from a thesis transition;
- time in the market from time watching while flat;
- an intended exit from the price at which it actually filled;
- chart marks from size-specific executable quotes;
- an ordinary permissionless creator-fee sweep from a verified social-recipient claim or a
  human act of public participation.

`RADON`, `EarthCoin`, and `CRASHIUS` are the initial requirements examples for positions that
began as crackles and became deliberately retained exposure after some profit recognition.
They are examples, not evidence that the strategy is profitable.

## Observation before compression

Capture raw, timestamped inputs before derived interpretations:

- Pump/PumpSwap state and events;
- candidate-board membership and rank;
- trades, reserves, quotes, route availability, fees, latency, and landing outcome;
- chart state at multiple resolutions;
- posts, replies, authors, identities, mentions, media, callouts, and community membership;
- operator viewport, gestures, annotations, and contemporaneous confidence/horizon;
- portfolio state and alternatives forgone;
- versioned machine interpretations with model, prompt, inputs, and production time.

Later LLM or statistical outputs must remain recomputable annotations, not replacements for
the source evidence.

## Research posture

- Preserve exploration separately from confirmatory evaluation.
- A null on an impoverished projection is not a verdict on the unobserved composite policy.
- The operator's strategy may still be negative-EV; the apparatus must be able to establish
  that rather than protect the thesis.
- Scaling is an estimand, not an assumption. Measure how value changes as attention and
  automation expand from the operator's top choices toward the whole surface.
- Prefer prospective logging, chronological holdouts, executable outcomes, explicit missing
  data, and replayable transformations.
- Do not force randomized capital deployment merely to make an estimator convenient. Shadow
  actions, matched contemporaneous alternatives, and low-cost elicitation come first.

## Safety boundary during this phase

Research and design may read public market data and the existing `joshibot` corpus. This
repository must not contain secrets or initiate, sign, or submit transactions until a later,
explicitly reviewed engineering decision authorizes a tightly scoped execution design.

