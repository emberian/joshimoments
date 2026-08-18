# Wave 6 — read-only shadow-policy arena

Status: deterministic intrinsic-contract/fixture prototype after the adversarial repairs required
by `99_INTEGRATION_REVIEW.md`; no ceiling promotion. No durable-store adapter, provider, wallet,
transaction builder, signer, submission path, live authority, or profitability claim is included.

## Delivered boundary

`analysis/src/joshi_analysis/wave6_shadow_policy` is a pure comparison kernel over an already
materialized evidence episode. It evaluates frozen policy versions on one common chronological
tape and emits a canonical JSON artifact. It performs no I/O and reads no clock, environment,
credential, wallet, provider, or live state.

The closed prototype registry contains:

- abstain;
- observe without exposure change;
- nominated crackle entry, with a later exact exit when that prospective cue exists;
- take-some with an economically live runner;
- full exit, flat watch, and re-entry as one continuing episode with a fresh exposure epoch;
- LP/routed-liquidity shadow actions for install, observed external flow, self-routed flow,
  rebalance, and removal.

These are policy families, not claims that a family is profitable or that the fixed rules recover
Ember's tacit policy. The arena preserves the
[thought kernel](../../../JOSHI_THOUGHT.md) distinction between the complete composite process and
a bounded projection being tested.

## Contract

An `ArenaPlan` is frozen no later than the episode start. Every included `PolicySpec` must already
have been registered when the plan was frozen. The plan predeclares one opportunity baseline, and
all policies consume the exact same `EvidenceEpisode` digest, starting finalized snapshot,
starting valuation, terminal horizon, and liquidation manifest.

The episode retains:

- a snapshot with exact asset atoms, known-at clock, commit sequence, evidence closure, and digest;
- a clocked, commit-ordered starting valuation closure by asset rather than an unexplained scalar;
- known reduced-rational or explicitly unknown aggregate subject basis tied to exact quantity;
- prospective decision points ordered by `(available_at, commit_seq, point_id)`;
- event, availability, and commit clocks plus observed/stale/conflicting/missing/unsupported state;
- explicit epistemic kind: observed fact, deterministic calculation, or scene-bound operator
  perception;
- exact-size, state-conditioned quote projections or quote refusals; and
- a common whole-position terminal-liquidation method and horizon.

Decision material marked outcome-visible is rejected. A point or quote beyond the as-known commit
closure is rejected. A quote cannot be requested before its policy decision, commit at or before
that decision, sort at or after the next decision under
`(available_at, commit_seq, occurrence_id)`, or arrive after the terminal horizon. Thus a later
same-time quote commit cannot affect the earlier decision. Policy decisions can use only the point
currently exposed by chronological replay. Terminal quotes are isolated from the decision tape
and used only after the prospective path ends.

This follows the Wave 5
[scientific-memory episode boundary](../wave5/06_SCIENTIFIC_MEMORY.md): exact flat does not end an
episode, flat watch remains explicit, re-entry starts another inventory epoch, and operator intent
does not imply a landed effect. It also follows the
[epistemic-book ceiling](../wave5/07_EPISTEMIC_BOOK.md): semantic inputs and canonical bytes do not
establish durable prospective qualification, adjudication, support, or maturity.

## Action, execution, and effect separation

The branch record has three disjoint occurrence types:

```text
PolicyAction
  hypothetical policy decision under exact point evidence

ExecutionProjection
  exact quote selected, quote refusal, or missing/ambiguous quote refusal
  explicitly not a transaction, signature, submission, landing, or fill

HypotheticalEffect
  deterministic consolidated balance delta from the selected quote
  explicitly not posted to the actual ledger and not a caused market effect
```

The fixed authority literal is
`read_only_evidence_only_no_signing_or_submission`. No public type contains instructions, key
material, signing requests, submission methods, or live-capability handles. This is deliberately
below the `read_only_no_execution` projection ceiling described in
[lane 15](../lanes/15_projection.md), because even the effect is only a shadow branch effect.

Every projected quote binds every asset it changes to an exact pre-balance. A branch refuses
missing, ambiguous, duplicate-use, wrong-state, wrong-size, stale, conflicting, unsupported, or
policy-incompatible evidence. It never substitutes a chart mark for a quote, chooses a convenient
size, silently carries a stale quote forward, or calls a quote a fill. The quote effect cannot
create negative or overflowing inventory.

## Episode and terminal accounting

All policy effects update a branch-local consolidated quantity vector. The input snapshot remains
immutable. This mirrors [exact accounting lane 08](../lanes/08_accounting.md): classification and
episode attribution do not mutate finalized wallet truth; partial realization does not make the
runner free; exact flat can preserve attention; and re-entry creates a fresh epoch.

The subject-asset basis projection uses exact `fractions.Fraction` arithmetic. Acquisitions add the
exact numeraire outflow when the quote establishes it. Partial/full dispositions allocate aggregate
basis in exact proportion to disposed quantity and report a realized projection only when both
basis and numeraire proceeds are known. The branch exposes basis before and after every hypothetical
effect, at the pre-liquidation runner, and after terminal liquidation. Unknown basis stays unknown
through a partial disposal; exact flat can close the remainder at zero without retroactively making
the disposed clip known. A re-entry after flat begins with its new exact acquisition basis.

Starting valuation is no longer a free normalization scalar. Its as-of state must equal the
starting snapshot; its known-at/commit order must follow that snapshot and precede the episode;
its exact evidence closure and digest remain visible. A known component must carry an
`ExactValuationArtifact`, not merely a caller-selected method label and amount. That artifact binds
a recognized source kind (`numeraire_identity`, `exact_sized_quote`, or `exact_sized_mark`), source
artifact ID and digest, carrier, the fixed `asset_atoms_exact_integer` unit, exact unit input/output,
exact whole-holding sized input/output, availability clock, and commit sequence. The sized output
must recompute by exact integer ratio from the unit amounts and sized input, name the episode
numeraire, equal the component amount, and precede the valuation decision in both availability and
commit order. The completed valuation commit must itself precede the first policy-decision commit.
Its source artifact ID must occur in the component and manifest evidence closure.

Numeraire inventory is valued strictly 1:1 through the intrinsic identity carrier. An unknown or
custom method such as `caller_asserted_positive_quote` cannot authorize a known amount; it must be
represented as a typed refusal without a numeric value or source artifact. Every positive starting
holding therefore has either a positive recomputable exact value from the strict artifact shape or
a typed refusal. Zero valuation of positive inventory is invalid. A typed refusal preserves
terminal inventory and wealth arithmetic but makes starting value, net PnL, opportunity cost, and
candidate surplus unknown rather than manufacturing a scalar result.

At the common horizon, every positive non-numeraire holding requires one unique exact
whole-position quote using the declared terminal method. The arena applies those quotes in stable
asset order. A missing, refused, ambiguous, or state-mismatched terminal leg remains an exact
residual and makes scalar terminal wealth and PnL unknown. It is never assigned zero recovery and
is never valued at a mark. A projected positive-input terminal disposal must return a positive
exact numeraire delta; zero output is invalid and must instead be represented as a typed refused
quote/residual.

When terminal closure is complete, the sole PnL identity is:

```text
net PnL, when defined = terminal numeraire wealth - exact complete starting valuation
```

The result carries this literal identity:

```text
net_pnl_when_defined_equals_terminal_wealth_minus_exact_starting_value;
refused_starting_or_terminal_value_yields_no_scalar_pnl;
diagnostics_and_opportunity_cost_are_non_posting
```

No fee, LVR, ITR, avoided loss, or opportunity comparison is added to or deducted from that
identity. Exact quote balance deltas already contain the branch's consolidated economic effect.

## Routed-liquidity accounting

The LP family is grounded in the
[routed-liquidity option/control/accounting model](../../research/routed_liquidity/04_OPTION_CONTROL_ACCOUNTING.md).
It does not turn an LP tenure into a round-trip cycle or assume that an uninstalled edge would have
attracted historical flow. LP flow, self-flow, rebalance, and removal are refused until a
successfully projected install names an exact position and installed-capital occurrence. Later
events must bind that same pair; flow after removal is refused. Each routed action retains its
independent decision and effect.

Every projected LP quote carries `LiquidityEffectEvidence` with an exact event/position/install
identity, evidence closure/digest, and separated principal, external fee, external cost, self-payer,
and owned-LP counterlegs. These components must reconcile exactly to the quote balance delta:

- install requires a capital-decreasing principal leg;
- external flow requires both give and receive principal legs;
- external fee diagnostics equal the positive evidenced controlled accrual by asset;
- irreversible-cost diagnostics equal the negative household deltas by asset;
- self payer and owned-LP legs consolidate to zero, with matching exact paid/owned fee evidence;
- a self-flow quote may post only evidenced negative external costs, never the internal owned fee;
  and
- maintenance cannot create positive inventory without a corresponding input.

The prototype then supports explicit non-posting/attribution diagnostics:

- external LP fee: already included in the consolidated balance effect;
- self-routed owned fee: internal and non-posting, never external service revenue;
- irreversible cost: already included in the consolidated effect;
- `LVR_grid` or ITR: counterfactual and non-posting.

One quote cannot contain both `LVR_grid` and ITR. An LP policy must predeclare which one, if either,
it reports; a quote containing the other measure is refused. Diagnostic IDs cannot be reused in
one branch. LVR/ITR values are signed and are never clipped at zero. The arena therefore cannot
manufacture consolidated wealth by adding fees twice,
adding an internal owned fee, deducting both adverse-selection measures, or posting a saved loss.
Each branch emits a `double_counting_audit` partitioning diagnostic IDs into already-in-effect,
internal non-posting, and counterfactual non-posting sets. It states explicitly that diagnostics
and opportunity cost are not added to PnL and that LVR/ITR are not additive.

Opportunity cost is calculated only after terminal closure:

```text
opportunity_cost(candidate) = terminal_wealth(baseline) - terminal_wealth(candidate)
candidate_surplus           = -opportunity_cost(candidate)
```

It is a signed, mutually exclusive branch comparison and remains `counterfactual_non_posting`.
It does not alter either branch's PnL. If either starting valuation or terminal value is unknown,
the comparison is also unknown.

## Refusal and uncertainty

Contract-invalid manifests fail closed. Economically incomplete but well-formed replay remains an
artifact with typed branch state:

- `complete`;
- `complete_with_refusals`; or
- `starting_value_unknown`; or
- `terminal_value_unknown`.

Every non-observed decision point produces an `UncertaintyRecord` with its gap IDs and the literal
treatment `preserved_not_zero`. A relevant financial cue additionally produces a typed refusal and
no effect. Missing terminal routes produce a residual-bearing terminal uncertainty. An abstain or
observe branch may still close economically when taking no risk is defined by the registered
policy; it does not convert the underlying evidence gap to observed fact.

This is consistent with the
[epistemic red team](../../research/lanes/11_epistemic_redteam.md): the episode is the unit,
unrouteability is often an outcome rather than ignorable missingness, and marks, quotes,
transactions, fills, and caused effects are separate claims.

## Determinism and artifact identity

Financial atoms are integers internally and canonical decimal strings on the wire. No float enters
accounting. Evidence arrays and asset rows are sorted and duplicate-free; set-like policies,
quotes, epistemic kinds, and diagnostics are serialized in stable identity order. Record IDs are
content-derived SHA-256 prefixes. The arena digest is SHA-256 over canonical JSON excluding only
the self-identifying artifact fields; `as_dict()` revalidates both ID and digest. Replaying the
same semantic plan produces identical action, execution, effect, branch, comparison, and artifact
bytes.

The artifact says only:

- conditional shadow comparison;
- common-information chronological replay; and
- terminal liquidation where every leg is fully quotable.

It explicitly does not claim a fill, landing, causal policy value, profitability generalization,
or live authority.

## Adversarial verification

`analysis/tests/wave6_shadow_policy/test_arena.py` covers:

- all six registered families over one common evidence digest and horizon;
- take-some/runner and flat-watch/re-entry episode continuity;
- exact terminal wealth for every fully quoted branch;
- stable canonical bytes and content-derived IDs;
- action/execution/effect separation and absence of actual-ledger posting;
- external versus self-routed LP fee treatment;
- exact LP principal/fee/cost reconciliation and installed-position transition ordering;
- non-posting ITR and opportunity comparison;
- explicit double-counting audit partitions;
- stale evidence refusal with preserved gap identity;
- unrouteable and zero-output terminal inventory refusing rather than becoming zero recovery;
- 1:1 numeraire valuation, a recomputable exact-sized non-numeraire fixture, and typed baseline
  refusal;
- rejection of caller-asserted valuation labels/amounts and late source commits;
- outcome leakage, late policy registration, and pre-decision quote rejection;
- quote-after-decision and same-time quote/next-decision commit ordering;
- ambiguous and wrong-state quote refusal;
- LVR/ITR conflict and self-fee misclassification rejection; and
- negative inventory and incomplete pre-state rejection.

Focused witness commands:

```sh
analysis/.venv/bin/pytest -q analysis/tests/wave6_shadow_policy
analysis/.venv/bin/ruff check \
  analysis/src/joshi_analysis/wave6_shadow_policy \
  analysis/tests/wave6_shadow_policy
```

## Deliberate limits

This prototype does not load Wave 5 store rows, certify durability, reconstruct protocol state,
model route-choice endogeneity, synthesize quotes, infer operator cues, adjudicate outcomes, fit a
policy, estimate support, perform named lot/tax allocation, allocate shared attention cost, or
simulate adaptive market response.
Its fixed cue rules are deliberately legible falsifiers, not the final operator ontology.

All evidence bytes/digests, clocks, registrations, quote effects, position events, valuation source
artifacts, and carriers remain caller-authored fixtures checked only by this pure contract. Known
valuation method labels are now a closed recognized set and their numeric result is recomputed, but
the source digest is not store-resolved and the carrier is not externally certified.
Content-derived prefix IDs are not collision-checked durable store occurrences. The repairs close
the accepted arithmetic, valuation-authority, and ordering counterexamples; they do not establish
store resolution, protocol parity, route-choice support, prospective registration, household
economic truth, or a Wave 6 release.

A later adapter must resolve immutable store evidence, projection versions, quote/protocol formula
profiles, coverage closure, and terminal manifests without weakening these types. Any tiny-live
proposal would still require an independent capability and safety review; a successful shadow
artifact is not that authority.
