# Wave 6 — the far-future formal seam

Status: design note only; no Lean project, dependency, generator, FFI, or build gate is authorized by this document.

## Decision

JOSHI has a useful formal-methods seam, but it is narrower than “verify the strategy.” The seam is the pure deterministic boundary:

1. a typed input has named units, provenance, clock cuts, and a protocol profile;
2. a total reference function returns either a typed result or a typed refusal;
3. accepted transitions preserve stated arithmetic, accounting, and trace invariants; and
4. shadow or later-known information cannot mutate witnessed ledger truth.

Those are realistic Lean targets. Agreement between that reference function and Rust is a separate refinement/conformance problem. Agreement between Rust and a deployed program is a further empirical and versioned conformance problem. Profitability, causal market impact, calibration, and generalization are not consequences of any of the three.

The first formal program should therefore prove a small checked-integer kernel and one quote profile, then stop and audit the claim boundary. It should not start with stochastic microstructure, an extracted trading system, or a theorem named `strategy_is_profitable`.

## 1. Claim classes

The proof ledger must distinguish four kinds of claim. A proof badge without this class is incomplete.

| Class | Example | Appropriate evidence | What it establishes |
|---|---|---|---|
| Pure theorem | checked division rounds as specified; a successful reducer preserves a balance equation | Lean proof over a declared specification | The proposition follows from the definitions and assumptions |
| Refinement/conformance | Rust `calculate` agrees with the Lean reference on a corpus or all encoded inputs | differential tests now; later, a verified refinement or very small audited translation | Agreement only for the covered implementation/profile/encoding |
| Statistical theorem | a Hawkes process with branching ratio below one has a stationary mean | probability theorem with explicit assumptions | A conditional result inside the model, not that data satisfy it |
| Empirical or causal claim | a route improves realized execution, a signal predicts returns, a strategy has positive expected value | prospective evidence, identification design, calibration, and out-of-sample evaluation | A bounded claim about observations and deployment conditions |

“Formally verified” is admissible only for the first class, or for the second when the refinement relation itself is proved. A golden-vector pass is conformance evidence, not a proof. A theorem conditional on a fitted parameter is not evidence that the parameter is stable, identified, or even correctly estimated.

This division follows the field-model ladder: H0/H1 settlement and protocol kinematics contain deterministic proof candidates; H2–H5 introduce description, fitting, latent state, and policy assumptions that must remain visible. See the [field-model overview](../field_models/README.md), [identifiability and units](../field_models/IDENTIFIABILITY_AND_UNITS.md), and [JOSHI lanes](../field_models/JOSHI_LANES.md).

## 2. The present executable boundary

The current tree already contains unusually good raw material for a later reference model. It also contains deliberate gaps that a proof must not erase.

| Surface | Current exact objects | Worth proving at the pure boundary | Present ceiling |
|---|---|---|---|
| Market math | `AssetAmount`, `QuoteRequest`, `QuoteBinding`, `AtomicPrice`, `QuoteCalculation`, `QuoteRefusal`; checked `u128`/`U256`; profile identity | dimensional compatibility, checked-rounding bounds, total success/refusal partition, binding preservation, reserve/capacity preconditions | calculators quote; they are not transaction handlers or post-state reducers |
| Pump curve | raw and virtual reserves; exact-base buy/sell profiles; component fee schedule | formula-specific rounding, result bounds, payout capacity, fee partition, post-state invariant once a transition is explicitly defined | source revision/profile is an input; deployed parity is not proved |
| PumpSwap | raw reserves plus signed virtual reserve; canonical/noncanonical profiles | effective-reserve construction, raw payout capacity, checked state update once specified | effective reserves are not custody; a quote is not a fill |
| DLMM | Q64.64 price, bin IDs/steps, fee arithmetic, per-bin share entitlement, inventory, chunking, action projections | finite exponent algorithm, share and rounding bounds, aggregation, chunk coverage, arithmetic consistency of budgets | swap traversal and several action fields are unsupported; actions currently report `ModeledOnly` |
| Accounting | `AtomQty` (`u64`), `TotalAtoms` (`u128`), signed deltas, exact rational basis, lots, finalized effects, epochs | boundary-relative conservation, effect continuity, named-lot partition, atomic classification failure, flat/re-entry state-machine safety | classification is interpretation after landed truth; it cannot prove intent or economic causality |
| Projection | `ExactMetric<T>`, unit tags, observed/deterministic epistemic classes, known/stale/conflicting/missing/unknown/unsupported/refused readings | unit and evidence preservation, refusal propagation, absence is not coerced to zero, freshness/cutoff validation | publication is read-only and does not create evidence |
| Mechanics capability | independent capability kinds, finality, coverage, refusal, `UnverifiedSemantic` authority | non-implication between capabilities and monotone gate logic | semantic preflight is not a durable observation, fill, close, or calibration |
| Store and evidence traces | commit sequence, observation/availability clocks, digests, receipts, append-oriented records | cutoff selection, idempotency, receipt closure, append-only history, no-future-input | source truth and wall-clock honesty remain outside the pure reducer |

The corresponding implementation descriptions are [protocol liquidity](../../implementation/lanes/12_protocol_liquidity.md), [accounting](../../implementation/lanes/08_accounting.md), [projection](../../implementation/lanes/15_projection.md), and [projection publication](../../implementation/lanes/23_projection_publication.md). The future model should follow these exact types; it must not silently replace them with real-valued textbook AMMs.

## 3. Reference-model shape

The formal kernel should be a small, pure library. Protocol facts, observations, and policy remain parameters. The following is Lean-oriented pseudocode, not proposed source code and not guaranteed to parse.

```lean
opaque AssetId : Type
opaque ProfileId : Type

-- A value carries its asset at the type level inside the model.
structure Atoms (asset : AssetId) where
  val : Nat
  fits_u64 : val < 2^64

structure PairAmounts (x y : AssetId) where
  xAtoms : Atoms x
  yAtoms : Atoms y

inductive Refusal
  | zeroDenominator
  | arithmeticOverflow
  | assetMismatch
  | invalidState
  | insufficientCapacity
  | unsupportedProfile
  | unsupportedField

inductive Outcome (α : Type)
  | success (value : α)
  | refused (reason : Refusal)

structure Transition (State Action Result : Type) where
  step : State → Action → Outcome (State × Result)
  valid : State → Prop
```

There are two deliberate differences from ordinary mathematical exposition:

- Asset identity and scale are part of the type or an explicit decoding proof. A bare `Nat` is never silently SOL, token atoms, basis points, a Q64.64 number, a wall duration, an event count, or a slot count.
- Expected invalidity is data. Division by zero, overflow, unsupported profile, insufficient raw custody, unknown creator-fee applicability, and absent traversal return `Refusal`; they are not hidden preconditions, panics, default zeroes, or arbitrary axioms.

Separate clocks remain separate types:

```lean
opaque WallInstant : Type
opaque MonotonicTick : Type
opaque Slot : Type
opaque CommitSeq : Type

structure BitemporalCut where
  validAt : WallInstant
  knownBy : WallInstant
  knownByCommit : CommitSeq
```

There should be no general addition or comparison between wall duration, event time, slots, and commit sequence. A named conversion may be introduced only with its assumptions and evidence.

## 4. Staged roadmap

### Stage 0 — freeze semantics before tooling

This document is the only Wave 6 deliverable for the formal seam. Before adding Lean, select one profile and write a proof-statement manifest containing:

- the exact Rust type and function names being modeled;
- integer widths and overflow behavior;
- the meaning of every rounding operation;
- asset orientation and decimal authority;
- success and refusal constructors;
- profile ID, program identity, and source revision;
- which inputs are observations and which are deterministic calculations; and
- explicit non-goals, including deployed parity and profitability.

A formula may not enter the reference model under a generic name such as `constantProduct` if the production function is profile-specific. In particular, `floor(n / d) + 1` is not interchangeable with mathematical ceiling: it is one greater even when `d` divides `n` exactly.

### Stage 1 — units and checked integers

This is the highest-value, lowest-ambiguity proof layer.

Prove:

- `u64`, `u128`, signed reserve, and `U256` conversions either preserve the mathematical value or refuse;
- downward, upward, and floor-plus-one division have their stated bounds;
- checked add/subtract/multiply do not wrap on success;
- fee basis-point/rate domains are bounded;
- separately rounded LP, protocol, and creator fees sum to `checked_total` on success; and
- asset-pair operations cannot cross x and y or base and quote.

Example signatures:

```lean
inductive Rounding | down | up

def checkedMulDiv
    (rounding : Rounding) (a b d : Nat) : Outcome Nat := ...

theorem mulDiv_down_spec
    (h : checkedMulDiv .down a b d = .success q) :
    d > 0 ∧ q * d ≤ a * b ∧ a * b < (q + 1) * d := ...

theorem mulDiv_up_spec
    (h : checkedMulDiv .up a b d = .success q) :
    d > 0 ∧ (q = 0 → a * b = 0) ∧
      (q > 0 → (q - 1) * d < a * b ∧ a * b ≤ q * d) := ...

def floorPlusOne (n d : Nat) : Outcome Nat := ...

theorem floorPlusOne_spec
    (h : floorPlusOne n d = .success q) :
    d > 0 ∧ q = n / d + 1 := ...

theorem checked_success_fits_u128
    (h : checkedMulDiv r a b d = .success q) : q < 2^128 := ...
```

The last bound belongs in the statement only when the reference result models a `u128` return. A convenient unbounded-`Nat` proof that omits the production bound does not refine the Rust operation.

### Stage 2 — venue-native quote and transition kernels

Build separate models for Pump curve, PumpSwap, and DLMM. Shared lemmas may cover arithmetic; shared venue state should not be invented.

#### Pump curve and PumpSwap

For a quote calculator, prove only quote properties:

```lean
def quotePumpBuy
    (profile : PumpProfile) (state : PumpState)
    (request : QuoteRequest) : QuoteCalculation := ...

theorem pump_quote_preserves_binding :
  let c := quotePumpBuy p s r
  c.binding.quoteId = r.quoteId
    ∧ c.binding.intentCommandId = r.intentCommandId
    ∧ c.binding.intendedStateObservation = r.intendedStateObservation
    ∧ c.requestedSize = r.size := ...

theorem pump_buy_success_is_positive_and_bounded
    (h : (quotePumpBuy p s r).outcome = .success q) :
    0 < q.output.atoms.val
      ∧ q.output.atoms.val ≤ s.realBaseReserves.val := ...

theorem pump_buy_fee_partition
    (h : (quotePumpBuy p s r).outcome = .success q) :
    q.input.atoms.val = q.rawQuoteAtoms.val + q.fees.lpAtoms
      + q.fees.protocolAtoms + q.fees.creatorAtoms := ...

theorem pumpswap_success_respects_raw_payout
    (h : (quotePumpSwapSell p s r).outcome = .success q) :
    q.output.atoms.val ≤ s.rawQuoteReserves.val := ...
```

Do not state reserve conservation over `calculate` alone. The current calculator returns a quote and refusal/binding information; it does not apply a chain transaction. Conservation requires a distinct transition with an explicit post-state and explicit destinations for fees:

```lean
structure PumpPostings where
  traderBase : SignedAtoms base
  traderQuote : SignedAtoms quote
  poolBase : SignedAtoms base
  poolQuote : SignedAtoms quote
  protocolQuote : SignedAtoms quote
  creatorQuote : SignedAtoms quote

def applyPumpFill
    (p : PumpProfile) (s : PumpState) (f : WitnessedFill) :
    Outcome (PumpState × PumpPostings) := ...

theorem accepted_fill_conserves_quote_at_declared_boundary
    (h : applyPumpFill p s f = .success (s', postings)) :
    postings.traderQuote + postings.poolQuote
      + postings.protocolQuote + postings.creatorQuote = 0 := ...
```

That theorem is boundary-relative. Network fees, rent, priority fees, token extensions, and accounts outside the declared posting set must either be included or named as residuals. For PumpSwap, effective raw-plus-virtual reserves drive the curve but virtual reserves are not custody balances and must not appear as spendable conservation postings.

A later invariant theorem may show that a successful rounded trade keeps the curve in its valid-state set or moves its product in a specified direction. It should not assert equality to a real-valued `x · y = k` unless that equality is actually preserved by the integer, fee, and rounding rules.

#### DLMM

The first DLMM layer should cover objects the Rust crate already computes:

- Q64.64 price construction over its bounded exponent algorithm;
- total, gross/net, and protocol fee arithmetic;
- per-bin share entitlement and floor-rounding bounds;
- aggregation of principal, fee, and reward inventory without mixing assets;
- bin-chunk ordering, disjointness, and exact coverage; and
- rebalance-budget arithmetic.

Example properties:

```lean
theorem entitlement_floor_bound
    (h : inventoryForShare reserve userShare totalShare = .success amount) :
    totalShare > 0 ∧
    amount * totalShare ≤ reserve * userShare ∧
    reserve * userShare < (amount + 1) * totalShare := ...

theorem entitlement_never_exceeds_reserve
    (hshare : userShare ≤ totalShare)
    (h : inventoryForShare reserve userShare totalShare = .success amount) :
    amount ≤ reserve := ...

theorem chunks_form_ordered_partition
    (h : chunkBinIds constraints ids = .success chunks) :
    chunks.flatMap (·.binIds) = ids ∧ PairwiseDisjoint chunks
      ∧ ∀ c ∈ chunks, c.binIds.length ≤ constraints.maxBins := ...
```

Do not formalize a complete DLMM swap or deployed add/remove/rebalance transition by filling gaps with assumptions. Swap traversal, minted/initial share behavior, composition fees, account limits, transaction cost/priority, interface support, close/reopen friction, and accrual derivation remain explicit unsupported fields. Proof of a `ModeledOnly` rebalance budget establishes its arithmetic, not that a handler exists or that the operation is executable.

A DLMM state-transition milestone starts only after a versioned traversal reducer exists. Its proof obligations would include ordered bin visitation, per-bin gross/net and protocol-fee postings, no negative balance, active-bin/range validity, and conservation over the declared accounts. Until then, the honest theorem is “this inventory or budget calculation is internally consistent,” not “this DLMM action preserves protocol state.”

### Stage 3 — accounting, refusal, and projection

Accounting proofs should begin from finalized before/after wallet snapshots. They must preserve the [accounting lane](../../implementation/lanes/08_accounting.md) distinction between landed truth and later classification.

Good targets are:

- `FinalizedWalletEffect.between` reconstructs aggregate signed changes from snapshots;
- a custody-only transfer has zero aggregate change per asset inside the declared wallet boundary;
- `apply_effect` accepts only the expected predecessor snapshot and never rewrites an earlier effect;
- failed classification leaves observed balances, landed effects, lots, and cash movements unchanged;
- successful named-lot consumption partitions exactly the requested quantity and never invents basis;
- rational basis allocation and subtraction are exact;
- flat-watch and re-entry open a new inventory epoch instead of erasing the prior one; and
- every residual is named rather than absorbed into P&L.

```lean
theorem custody_transfer_cancels
    (h : FinalizedWalletEffect.between id before after = .success e)
    (hc : e.isCustodyOnly) :
    ∀ asset, e.aggregateChange asset = 0 := ...

theorem classification_refusal_is_atomic
    (h : runClassify st effectId proposal = (st', .refused reason)) :
    st' = st := ...

theorem consume_named_lots_exact
    (h : consume book asset requested allocations = .success (book', basis)) :
    sum (allocations.map (·.quantity)) = requested
      ∧ remainingQty book' asset + requested = remainingQty book asset := ...

theorem reentry_starts_fresh_epoch
    (hflat : observeInventory episode zeroEffect 0 = .success flat)
    (hre : observeInventory flat reentryEffect q = .success live)
    (hq : q > 0) :
    live.currentEpoch.index = flat.lastEpoch.index + 1 := ...
```

Refusal must be closed under projection. If the exact layer refused, the accessible layer may render that refusal but cannot substitute a number. `Known`, `Stale`, `Conflicting`, `Missing`, `Unknown`, `Unsupported`, and `Refused` are disjoint constructors; none is zero.

```lean
theorem project_refusal_preserved
    (h : exact.outcome = .refused r) :
    (project exact).reading = .refused (renderRefusal r) := ...

theorem metric_projection_preserves_unit
    (h : exact.outcome = .success v) :
    (project exact).unit = exact.declaredUnit := ...

theorem projection_adds_no_evidence :
    setOf (project exact).evidence ⊆ setOf exact.observationClosure := ...
```

The projection theorem does not establish that an observation is correct. It establishes only that presentation did not change the declared meaning or provenance of its input.

### Stage 4 — temporal safety and noninterference

Wave 5’s most important future formal objects are traces, not market equations. The [Wave 5 learning-field plan](../../planning/WAVE5_LEARNING_FIELD_LAB.md) identifies revision, bitemporal selection, episodes, topology, reservations, and slow/medium/fast shadows as a typed transition IR. The [mechanics capability plan](../../implementation/wave5/13_MECHANICS_CAPABILITIES.md) and [epistemic admission plan](../../implementation/wave5/14_EPISTEMIC_ADMISSION.md) keep capability and authority ceilings independent.

Model a finite event trace with distinct state components:

```lean
structure SystemState where
  ledger : LedgerState
  catalog : AppendOnlyCatalog
  reservations : ReservationState
  slowShadow : SlowState
  mediumShadow : MediumState
  fastShadow : FastState
  authority : AuthorityCeiling

inductive Event
  | admitObserved (observation : Observation)
  | appendCorrection (correction : Correction)
  | derive (artifact : DerivedArtifact)
  | shadowStep (lane : ShadowLane) (input : ShadowInput)
  | reserve (request : ReservationRequest)
  | attachReceipt (receipt : DurableReceipt)
  | refuse (reason : Refusal)
```

Pure finite-trace safety targets:

```lean
theorem no_future_input
    (h : reachable initial trace final) :
    ∀ use ∈ final.derivedUses,
      use.input.availableAt ≤ use.cut.knownBy
      ∧ use.input.commitSeq ≤ use.cut.knownByCommit
      ∧ eligibleAtValidTime use.input use.cut.validAt := ...

theorem correction_does_not_rewrite_prior_cut
    (h : ¬ eligibleAtCut c cut) :
    selectAsOf (catalog.append c) cut = selectAsOf catalog cut := ...

theorem shadow_noninterference
    (h : step st (.shadowStep lane input) = .success st') :
    st'.ledger = st.ledger ∧ st'.catalog.observed = st.catalog.observed := ...

theorem receipt_before_exposure
    (h : reachable initial trace final)
    (hexposed : final.publications.contains artifact) :
    ∃ receipt, receipt ∈ prefixBefore trace artifact
      ∧ closes receipt artifact.inputs := ...

theorem no_double_reservation
    (h : reachable initial trace final) :
    ∀ r₁ r₂ ∈ final.reservations.active,
      overlaps r₁.scope r₂.scope → r₁.id = r₂.id := ...

theorem authority_never_increases_by_derivation
    (h : step st (.derive artifact) = .success st') :
    noMoreAuthoritative st'.authority st.authority := ...
```

The first Lean version should prove these for a deterministic reducer and finite traces. Concurrency, crashes, retries, writer interleavings, and liveness may be better explored first with bounded state-machine tools, as Wave 5 proposes. A bounded model check can find counterexamples; it does not prove an unbounded theorem. Conversely, a pure trace theorem does not show that production I/O always emits the modeled events. Both obligations should be recorded.

Important temporal limits:

- `observed_at`, `valid_at`, `available_at`/`known_by`, monotonic time, slot, and commit sequence cannot substitute for one another.
- Receipt closure proves a byte/digest relation and ordering in the modeled catalog; it does not prove the source’s report was true.
- Append-only semantics allow corrections and supersession. They do not mean the first assertion remains the selected truth at every later cutoff.
- Safety properties such as “no shadow event changes the ledger” do not imply liveness such as “every valid observation is eventually admitted.”
- A command or reservation is evidence of an intended control transition, not evidence of an attempt, fill, or economic outcome.

### Stage 5 — implementation refinement

Only after the pure model is small and stable should JOSHI attempt to connect it to Rust.

The desired relation is explicit:

```text
canonical bytes
    -> strict decoder
    -> Lean input value
    -> Lean reference outcome

canonical bytes
    -> Rust decoder
    -> Rust production outcome

compare normalized success/refusal values under the same profile
```

There are three increasing strengths:

1. Golden conformance: both paths agree on a retained finite corpus.
2. Property conformance: generated inputs exercise a much larger bounded domain and shrink mismatches.
3. Verified refinement: a proof covers every admitted encoding and every branch of the selected Rust implementation or an audited generated implementation.

JOSHI should claim the strength it actually has. Stages 1 and 2 are valuable even if stage 3 never becomes economical.

The refinement statement must cover success and refusal. A Rust overflow or unsupported branch that is absent from the Lean model is a mismatch, not an inconvenient test exclusion. Normalization must also preserve formula/profile ID, asset orientation, amounts, fees, observation closure, and refusal reason.

### Stage 6 — conditional probability and statistics

The Bouchaud et al. distillation includes mathematically formal objects, but most sit beyond the deterministic seam: marked point processes, Hawkes intensities, propagator kernels, response functions, latent liquidity, queue/execution distributions, and forecast scores. See the [formal microstructure model](../../microstructure/trades_quotes_prices/FORMAL_MODEL.md), [book map](../../microstructure/trades_quotes_prices/BOOK_MAP.md), [JOSHI beacon](../../microstructure/trades_quotes_prices/JOSHI_BEACON.md), and [transfer limits](../../microstructure/trades_quotes_prices/TRANSFER_LIMITS.md).

These require a second library layer with measure theory, probability spaces, filtrations, conditional expectation, stochastic processes, stopping times, and estimation-specific definitions. Mathlib’s general probability foundation may support part of that work; specialized, repository-audited developments would still be needed for point-process likelihoods, multivariate Hawkes stability, censoring/survival estimands, irregular event-time sampling, and the exact estimators JOSHI uses. Library availability must be audited at project start rather than assumed here.

Reasonable conditional theorem shapes include:

```lean
theorem hawkes_stationary_mean
    (hNonneg : 0 ≤ kernel)
    (hIntegrable : Integrable kernel)
    (hSubcritical : integral kernel < 1) :
    stationaryMean baseline kernel = baseline / (1 - integral kernel) := ...

theorem propagator_cost_nonnegative
    (hKernel : positiveSemidefiniteKernel G)
    (hSchedule : deterministicSchedule q) :
    expectedMechanicalCost G q ≥ 0 := ...

theorem proper_score_prefers_true_distribution
    (hProper : StrictlyProper score)
    (hDgp : outcomeLaw = p) :
    E[score p outcome] ≤ E[score q outcome] := ...
```

Every such theorem is conditional. The proof cannot supply `hSubcritical`, `hKernel`, or `hDgp` for a live market. Those are empirical/model-admission obligations. Likewise:

- `observed response = reaction + prediction` is an algebraic bookkeeping identity once those variables are defined; the reaction counterfactual remains latent;
- a square-root impact law or propagator exponent is a fitted regularity, not a protocol theorem;
- an MRR, Kyle, Hawkes, latent-order-book, or queue model is not portable to an AMM merely because both produce price changes;
- positivity of model cost under an admissible kernel does not prove a deployed schedule’s all-in realized cost; and
- a proper scoring theorem does not prove the forecast is calibrated or that an action policy is beneficial.

The first stochastic milestone, if ever justified by empirical work, should use a finite/discrete probability space and one estimator contract. It should not begin with continuous-time multivariate Hawkes infrastructure.

## 5. What cannot honestly be “strategy verified”

No plausible Lean program can, from the current repository, prove any of the following as facts about future markets:

- positive expected value, positive realized P&L, or bounded drawdown for a strategy;
- that a descriptive association is causal impact;
- that an external-liquidity action stabilizes price, improves execution, or reduces liquidation risk;
- that a signal remains calibrated after regime, participant, protocol, or fee changes;
- that a backtested alternate route existed and was executable at the historical decision time;
- that an observed fill is the counterfactual fill under a different route, order, or liquidity state;
- that an operator’s intended acceptable set has been captured by a formal policy;
- that source coverage is complete merely because retained rows pass a schema and digest check;
- that an oracle, RPC, archive, SDK, or decoded account reflects canonical chain truth; or
- that a proof about one source revision applies to a later deployed program.

The routed-liquidity documents make these limits concrete. The [data envelope](../routed_liquidity/01_DATA_ENVELOPE.md) does not contain historical counterfactual route state. The [ghost-edge experiment](../routed_liquidity/03_GHOST_EDGE_EXPERIMENT.md) is a fixed-demand mechanical activation surface, not a causal market path. [Option/control accounting](../routed_liquidity/04_OPTION_CONTROL_ACCOUNTING.md) requires one inventory, self-flow elimination, reservations, and terminal liquidation. [Dynamics and causality](../routed_liquidity/06_DYNAMICS_CAUSALITY.md) explicitly separates quote mechanics from stabilization claims. The [book-to-JOSHI traceability](../routed_liquidity/07_BOOK_TO_JOSHI_TRACEABILITY.md) reaches the same formal boundary.

A future dashboard label should therefore say, for example, “integer quote invariant proved for profile P at revision R; Rust corpus agrees at digest D.” It should not say “strategy verified.”

## 6. Golden artifacts: inputs and counterexamples, not proofs

Rust and Python golden artifacts can make the formal seam useful before verified extraction. They should feed theorem *instances* and conformance tests through a canonical, bounded case format:

```text
FormalCaseV1
  case_id
  semantic_contract
  profile_id / program_identity / source_revision
  canonical_input_bytes + digest
  decoded dimensions and asset orientation
  expected normalized outcome: success(value) | refused(reason)
  source kind: synthetic | retained observation | adversarial boundary
  observation closure, if any
  generator build/digest
```

Recommended uses:

- Rust unit/property vectors provide edge cases for the Lean specification.
- Lean evaluation can generate normalized expected values for a Rust differential harness.
- An independent Python implementation can triangulate arithmetic and serialization mistakes.
- Retained deployed observations can falsify a claimed protocol profile.
- Counterexamples become immutable regression cases with the mismatching profile and build.

Forbidden promotion:

- A thousand passing cases do not prove a universal arithmetic theorem.
- A Lean `by native_decide` result over one imported fixture proves only the decoded finite proposition, and only within the trust path of that evaluation mode.
- Agreement among Lean, Rust, and Python can reflect a shared misunderstood formula.
- A source digest proves byte identity, not semantic truth or chain finality.
- Synthetic cases provide no empirical frequency, calibration, or profitability evidence.

Golden artifacts should therefore have a `conformance_evidence` authority, never `proof`, `witnessed_fill`, or `strategy_validation`. The immutable digest and profile binding matter more than which language emitted the case.

## 7. Trust boundary

A formal result is meaningful only with a visible trusted-computing and evidence boundary.

| Inside the logical statement | Outside, or separately trusted/verified |
|---|---|
| pure definitions; explicit profile parameter; decoded typed state; success/refusal reducer; proved invariant | Lean kernel and selected libraries; build/toolchain; parser and canonical-byte decoder; any code generator or extraction backend |
| theorem that a declared transition conserves a declared posting boundary | assertion that retained bytes came from the intended account/program and canonical finalized chain |
| theorem that selection excludes modeled future inputs | OS clocks, source timestamps, writer honesty, durability hardware, and completeness of upstream acquisition |
| theorem that shadow transitions do not alter modeled ledger state | production wiring, unsafe/FFI code, databases, network clients, signers, and actual execution authority |
| theorem over a versioned protocol definition | correctness of the reverse-engineered formula and continued equality to the deployed program |
| theorem conditional on stochastic assumptions | identification, parameter estimation, stationarity, calibration, regime stability, and external validity |

The proof manifest should list every axiom and opaque definition. Profile constants are preferably explicit inputs with well-formedness proofs, not global axioms. A theorem with an assumption equivalent to its conclusion is proof theater even if Lean accepts it.

There are at least four identities that must never collapse into one:

1. specification identity: theorem/library revision and statement digest;
2. protocol identity: family, program, profile, and source revision;
3. implementation identity: Rust/Python source tree and build digest; and
4. evidence identity: observation closure, cutoff, finality, coverage, and artifact digest.

## 8. Extraction and FFI cautions

Extraction is not the first milestone and should not be presented as a shortcut to verified production.

- Lean `Nat`/`Int` semantics do not automatically match Rust `u64`, `u128`, signed `i128`, or the repository’s `U256`. Bounds and checked conversion/refusal must be part of the model.
- Modeling Rust integers as bit-vectors models wraparound unless checked operations are defined. JOSHI’s exact lanes generally refuse overflow; silently proving modular arithmetic is the wrong contract.
- Arbitrary-precision rational normalization must match the wire representation. Equality of rational values is not necessarily equality of canonical numerator/denominator bytes.
- `floor + 1`, component-wise ceiling, saturating subtraction, and fixed-step Q64.64 exponentiation must stay distinct operations. A compiler optimization or helper substitution may change edge behavior.
- Panics, allocation failure, resource exhaustion, recursion limits, and denial-of-service bounds live outside a total mathematical function unless modeled explicitly.
- Serialization, hashing, filesystem/database I/O, clocks, network reads, finality, and signatures should remain outside the pure extracted kernel.
- An FFI layer introduces ABI layout, ownership, aliasing, panic/unwind, unsafe-code, and versioning obligations. `repr` compatibility is not semantic refinement.
- A generated Rust function can be a useful offline oracle even if it is too slow or awkward for the production path. Performance pressure must not silently weaken refusals or units.
- Calling the existing Rust implementation from Lean proves nothing about that implementation; it only moves it into the trusted boundary.
- Using native compilation to discharge large finite propositions has a different trust story from kernel-reduced proof terms and must be labeled.

The conservative architecture is a pure reference evaluator with canonical byte adapters on both sides, used offline. Execution, signing, and live routing stay outside it.

## 9. Small first milestone

When the project is explicitly authorized, start with **M0: checked arithmetic plus one Pump exact-base-out buy quote**.

Scope:

- model `Rounding`, checked `mul_div_u128`, and `mul_div_floor_plus_one`;
- model one frozen Pump state/profile using an observed flat fee policy, including its creator-fee applicability;
- model the minimal asset-oriented request, state, binding, success result, and refusal set;
- prove denominator/rounding bounds, no successful overflow, binding preservation, output capacity, and fee partition; and
- run a later differential harness over adversarial and existing immutable vectors.

Explicitly out of scope:

- Pump sell, PumpSwap, DLMM, post-transaction state, and conservation across chain accounts;
- extraction, FFI, generated production code, or a new workspace/build gate;
- program equivalence, RPC/source correctness, simulation/fill equivalence, and profitability; and
- stochastic microstructure.

Entry criteria:

1. the profile/program/source revision is frozen and named;
2. the Rust formula and every rounding/refusal branch have a reviewed statement manifest;
3. canonical input/output normalization is specified independently of display DTOs; and
4. edge vectors include zero denominators, exact divisibility, maximum widths, one-past-capacity, creator-fee variants, and asset reversal.

Exit criteria:

1. no admitted proof uses an unstated arithmetic or protocol axiom;
2. every success and refusal constructor is covered by a theorem or a named non-goal;
3. the theorem report says exactly “reference specification,” not “deployed program”; and
4. any Rust/Python mismatch is retained as a counterexample, not normalized away.

Only after M0 should the team decide whether a Pump post-state reducer is stable enough for a conservation milestone. That audit is the point: a small proved seam that stops at the right boundary is more valuable than a broad formal story that quietly assumes its hardest claims.

## 10. Source map

The design depends on these existing claim boundaries:

- Microstructure: [formal model](../../microstructure/trades_quotes_prices/FORMAL_MODEL.md), [book map](../../microstructure/trades_quotes_prices/BOOK_MAP.md), [JOSHI beacon](../../microstructure/trades_quotes_prices/JOSHI_BEACON.md), and [transfer limits](../../microstructure/trades_quotes_prices/TRANSFER_LIMITS.md).
- Field model: [state space](../field_models/STATE_SPACE.md), [fields and operators](../field_models/FIELDS_AND_OPERATORS.md), [conservation and geometry](../field_models/CONSERVATION_AND_GEOMETRY.md), [identifiability and units](../field_models/IDENTIFIABILITY_AND_UNITS.md), [analogy red team](../field_models/ANALOGY_REDTEAM.md), and [forecast/mechanism note](../field_models/FORECAST_MECHANISM_NOTE.md).
- Routed liquidity: [venue routability](../routed_liquidity/02_VENUE_ROUTABILITY.md), [ghost edge](../routed_liquidity/03_GHOST_EDGE_EXPERIMENT.md), [option/control accounting](../routed_liquidity/04_OPTION_CONTROL_ACCOUNTING.md), [glass operator](../routed_liquidity/05_GLASS_OPERATOR.md), and [dynamics/causality](../routed_liquidity/06_DYNAMICS_CAUSALITY.md).
- Wave 5: [learning-field plan](../../planning/WAVE5_LEARNING_FIELD_LAB.md), [mechanics capabilities](../../implementation/wave5/13_MECHANICS_CAPABILITIES.md), [epistemic admission](../../implementation/wave5/14_EPISTEMIC_ADMISSION.md), and [integration review](../../implementation/wave5/99_INTEGRATION_REVIEW.md).
- Executable exact types: [market quote types](../../../crates/joshi-market-math/src/quote.rs), [checked wide arithmetic](../../../crates/joshi-market-math/src/wide.rs), [Pump calculators](../../../crates/joshi-market-math/src/pump.rs), [DLMM Q64.64](../../../crates/joshi-liquidity/src/q64.rs), [DLMM positions](../../../crates/joshi-liquidity/src/position.rs), [DLMM actions](../../../crates/joshi-liquidity/src/action.rs), [accounting effects](../../../crates/joshi-accounting/src/effect.rs), [accounting reducer](../../../crates/joshi-accounting/src/accounting.rs), and [projection metrics](../../../crates/joshi-projection/src/metric.rs).

The governing rule across all of them is consistent: exact protocol movement and deterministic bookkeeping come first; statistical response and causal claims remain conditional; shadow analysis cannot acquire economic authority by passing through a proof assistant.
