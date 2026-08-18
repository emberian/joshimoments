# `joshibot` compost map

Status: selective provenance note. This is not a migration plan.

`~/dev/joshibot` is evidence, a library of failure cases, and a source of some strong
mechanical organs. It is not the architecture for `joshi`. The safest reuse rule is:

> Reuse an old artifact only after restating the behavior it provides in the new episode,
> evidence, and authority vocabulary. Never inherit a conclusion merely because code was
> built around it.

No runtime state, keys, credentials, wallet authority, or live service configuration should
be copied into this repository.

## Transplant as specifications and fixtures

These ideas survived the review. Their existing implementations are useful references and
adversarial fixtures, but should not be imported wholesale before the new contracts exist.

### Evidence and provenance

- Raw integer asset quantities, explicit units, chain and observation clocks, reserve data,
  and censoring records from `shitcoims_tape`.
- Append-only operator utterances, retractions instead of edits, and durable writes from the
  hunch tape. The old rows are demonstrations rather than real operator evidence, so retain
  the record-shape lesson without treating their content as training data.
- The tape/journal distinction in `JOSHI.md`: high-rate external observations and lower-rate
  operator or command transitions require different semantics, even if one storage substrate
  eventually carries both.
- The glass rules in `design/glass.md` that distinguish missing, stale, errored, unwatched,
  and measured-zero states; keep exits reachable; freeze reordering under an active gesture;
  preserve utterances; and show provenance with displayed facts.
- Reconciliation records that keep intended, simulated, provider-reported, and chain-observed
  outcomes distinct.

### Transaction containment, for a much later phase

- RPC clients whose method surface structurally excludes broadcast.
- Treating SDK-produced transactions as hostile bytes: decode the entire message, resolve
  lookup tables, deny unknown programs and instructions, bind every relevant account and
  amount to an exact authorization, and verify wallet-level postconditions independently.
- Keyless builders, isolated signers, persist-before-submit, sign-once/rebroadcast-identical-
  bytes behavior, and an explicit unresolved state until a transaction lands or expires.
- Default-deny refusal when an operation's economic effect cannot be established. The old
  refusal to authorize DLMM rebalance is an especially useful fixture.

These are behavioral requirements, not authorization to port or activate money code. The
current project phase remains read-only.

### Accounting and market mechanics

- Wallet reconstruction, lot and basis provenance, exact lamport/token reconciliation, and
  the old cross-wallet accounting discrepancies as fixtures.
- Pump/PumpSwap decoders, quote experiments, migration observations, fee/version handling,
  and DLMM bin math where they can be checked against current official interfaces.
- The observation that an LP is inventory plus a contingent trade schedule, and that fees,
  composition change, active range, removal, and rebalance must be reported separately.

### Research scars

Preserve the old studies as tests of the new apparatus:

- disappearance and stale marks must not be treated as benign censoring;
- repeated board appearances must not become independent coins;
- current metadata must not leak backward into historical scenes;
- live quote, mark, attempted transaction, landed transaction, and wallet fill are different;
- a small hand-selected sample must not be linearly expanded into a market-wide policy;
- provider-visible chain outcomes cannot measure never-landed submissions;
- fee income, deposits, locked assets, external custody, and trading PnL must not share an
  unexplained accounting boundary;
- null generators and statistics must preserve dependence and have power against relevant
  planted alternatives.

The result files should become regression-fixture provenance, not laws embedded in the UI.

## Retain as scoped findings, not governing claims

Several findings can guide what is cheap or dangerous to try, but identify only the population,
features, execution model, and market window actually studied:

- The old low-dimensional board-entry grids did not find a robust executable entry rule in
  their short tapes.
- Mechanical callout-following was fragile or adverse in the tested cohorts; callouts often
  arrived after flow and may still be useful as a surfacing or social-state event.
- Fixed exit families were highly sensitive to quote freshness and small adverse fills.
- Some LP positions earned meaningful fees while underperforming hold after inventory change
  and friction.
- Position age and observed realization behavior interacted in the reconstructed wallet data,
  but did not yield an identified trading rule.

These should influence baselines, failure injections, and falsifiers. They do not settle the
value of Ember's unrecorded selection, graph interpretation, partial realization, flat watching,
re-entry, runner promotion, or social/community judgment.

## Compost rather than port

The following old assumptions are explicitly not part of the new foundation:

- **“Entry prediction is dead.”** The old work supports narrower nulls. It did not observe the
  complete attention funnel or the composite episode policy.
- **Position-centric lifecycle.** A fully flat interval can remain inside one attentive episode,
  and re-entry can continue the same thesis. Wallet inventory intervals are not behavioral
  episode boundaries.
- **A fixed hunch vocabulary.** `wiggle/down/up/watch`, `quality/scalp`, and any fixed five-button
  population are historical probes, not Ember's ontology.
- **A hold clock as the policy.** A timer may be a safety or abandonment backstop; it is not a
  substitute for graph-driven management.
- **One gesture as observation, belief, authorization, and trade.** Those acts can remain fast in
  the glass while producing semantically separate records.
- **Callouts as universally directional or universally useless.** Their discovery, identity,
  volatility, coordination, and transition roles require separate estimands.
- **Blind wallet copying.** A watched-wallet touch is a candidate-discovery event with latency,
  identity confidence, liquidity, and selection context—not an automatic instruction.
- **Expectation compilation and policy synthesis as an early milestone.** First capture ordinary
  scenes, acts, disagreements, and counterexamples; introduce a program language only after its
  predicates are evidenced.
- **C#/Lean/TypeScript or any other language split as a foundation.** Formal verification remains
  promising for safety envelopes and accounting refinements, but technology and proof boundaries
  follow the validated operation model.
- **Port-as-is and harden-don't-rewrite.** The new repository is intentionally a clean semantic
  boundary. Re-derivation and differential tests are safer than inheriting hidden commitments.
- **Hard-coded fee, route, lifecycle, or program assumptions.** Current accounts, SDK/IDL versions,
  program deployments, and conformance fixtures define what is valid at a given time.

## Donor map

| `joshibot` area | `joshi` treatment | Admission test |
|---|---|---|
| `studies/` and `RESULT_*.md` | provenance and adversarial fixtures | claim is restated with its actual cohort, clocks, costs, and missingness |
| `shitcoims_tape/` and collectors | mine schemas and failure cases | repeated/live/backfill input replays without gaps or semantic collapse |
| explorer, chart, instrument, `design/glass.md` | mine interaction invariants | preserves the real Pump information loop and the new gesture language |
| hunch tape/API | mine append-only utterance mechanics | clearly excludes demo rows and does not impose the old taxonomy |
| paper desk and replay/OPE | reuse mathematical tests selectively | episodes, choice sets, support, dependence, and executable outcomes are explicit |
| wallet/accounting reconstruction | differential oracle and fixtures | closes exactly to chain while preserving episode attribution separately |
| Pump/PumpSwap quote and execution code | protocol fixtures only | agrees with pinned official SDK/IDL and sampled chain state at integer precision |
| LP math, guard, ledger | fixture source | supports exact add/remove/rebalance semantics and fails closed on corrupt state |
| sentinel signer/executor | later adversarial corpus | no code crosses into the current read-only process graph |
| Lean kernel and proposed DSL | candidate future proof artifact | a stable domain object and useful theorem boundary have first been demonstrated |
| `JOSHI.md` architecture | historical design input | every adopted decision is re-earned in the new decision register |

## Practical rule for future composting

When considering any old module:

1. Name the new behavior or invariant it might provide.
2. Identify the old study assumptions and state it silently embeds.
3. Extract fixtures, counterexamples, or an interface contract before code.
4. Differentially test a minimal adapter against current official protocol behavior.
5. Import only if it reduces work without changing the evidence meaning or widening authority.

This keeps the old repository valuable without allowing its premature conclusions to become the
new project's ontology.
