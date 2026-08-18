# Coherence review: one apparatus, several books, no premature theory

Status: cross-lane reconciliation for the root synthesis; pre-engineering only.

Reviewed in full: `docs/PROJECT.md` and lanes 01–12.

## Overall judgment

The lanes converge on a coherent project. They do not converge on one coherent vocabulary or one
first experiment yet.

The common project is an operator-facing evidence instrument with a whole-market census, an
attention-sensitive high-resolution slice, exact portfolio accounting, and causal replay. It must
be useful enough that Ember naturally notices, inspects, acts, exits, remains flat while watching,
re-enters, retains exposure, and later reflects inside it. Strategy models come after the system
can preserve that process without replacing it.

The strongest agreement is architectural in the semantic sense:

```text
untrusted sources and operator interactions
                 |
                 v
      immutable acquisition records + coverage
                 |
                 v
      versioned assertions and derivations
                 |
          +------+------------------+
          |                         |
   witnessed/as-known replay   financial reconciliation
          |                         |
          +-----------+-------------+
                      v
           operator cockpit and studies

Later, through a separately reviewed seam only:

operator arm -> bounded capability -> unsigned plan -> independent guard
             -> signer -> identical-byte submission -> chain reconciliation
```

The principal reconciliation problem is that several lanes independently named the same layers.
`episode`, `inventory epoch`, `inventory interval`, `clip`, `lot`, `tranche`, `scene`, `scene
bundle`, `scene snapshot`, `event tape`, `journal`, `arm`, `authorization`, `disposition`, and
`book` sometimes denote overlapping or incompatible objects. If these terms are allowed to harden
independently in code, the project will recreate the projection error it was founded to avoid.

The other major problem is pilot proliferation. Nearly every lane proposes a different “smallest
experiment”: one scene, one week, two weeks, 20 episodes, 30 episodes, 30 days, 50 families,
72 hours, 100–200 arms, and several existing positions. These are useful ingredients, not eleven
parallel starts. The synthesis should commission one integrated observational corridor, with
specialized dockets hanging off it.

## Agreements strong enough to adopt

### The behavioral and financial units are different

An **operator episode** is the continuity of Ember's attention and intent. Becoming flat does not
end it. An **inventory epoch** is a flat-to-flat accounting interval. The asset ledger must balance
without knowing any episode, disposition, or strategy label. This separation is the most important
cross-lane result.

The lanes also agree that a later acquisition after true portfolio-flat starts fresh basis even
when it is a re-entry in the same episode. A graph-driven exit, flat watch, and later re-entry are
therefore one behavioral episode containing two accounting epochs.

### The policy is a funnel and a path, not a feature row

The market universe, surfaced list, client-rendered list, viewport, inspection, rejection, arm,
execution, partial realization, flat observation, re-entry, and eventual resolution are all
evidence. Ember's attention is simultaneously a useful sensor and a non-random selection
mechanism. Whole-market census and hot observation are complementary, not competing, acquisition
modes.

### Facts, interpretations, and what was shown must remain separable

All lanes support immutable raw acquisition, explicit clocks and gaps, versioned parsing, and
recomputable interpretations. Current identity, metadata, engagement, LLM summaries, or corrected
chain state must not leak into an earlier decision scene. Screenshots are useful perceptual checks,
but not substitutes for structured rendered state, raw source evidence, or choice-set membership.

### Inventory change, operator meaning, and execution lifecycle are orthogonal

A partial sell does not prove a runner transition. A full sell does not prove episode resolution.
An arm is not a prediction. A submitted signature is not a fill. A fill is not reconciled
inventory. A disposition is not a wallet balance. These distinctions should be structural rather
than conventions in application code.

### Executable economics dominate marks

Exact integer amounts, dynamic fee configuration, size-specific route state, transaction costs,
latency, actual wallet deltas, and current liquidation capacity are required. The system may show
a chart mark, but it must not label the mark realizable PnL. Remaining runners and withdrawn LP
assets retain current risk and opportunity cost even when original cash has been recovered.

### The initial system is observational

All lanes are compatible with an initial system that reads public sources and watched wallet
addresses, records operator gestures, computes shadow quotes, and reconciles trades Ember makes in
external tools. There is broad agreement that no key, signer, builder, or broadcast method belongs
in that phase. Later authority must be narrow, revocable, stateful, independently checked, and
separately approved.

### Build meanings; reuse plumbing

Official protocol SDKs and IDLs, Solana transports, conventional storage, chart renderers, query
engines, and later send infrastructure are replaceable plumbing. Episode semantics, attention and
scene capture, point-in-time identity/community evidence, operator language, executable-value
accounting, and replay are bespoke because they define the estimand.

### Ecology and wallet watching are context routers, not new automatic books

Lane 12 closes an important scope gap without broadening the first execution surface. Territory
analysis begins as versioned, overlapping relations among launches, coin families, communities,
and attention—not a grand ecological predictor. Followed-wallet activity begins as provenance-rich
candidate surfacing, not “smart money” and not automatic copying. In both cases, the useful path is
context -> Ember inspection -> optional arm, with exact lead time, coverage, identity evidence,
and executable shadow outcomes preserved.

### Formal methods have a real but bounded role

Formal and executable specifications earn their cost at conservation, authority, and replay
boundaries: exact asset identities; state-machine transitions; durable reservation; no duplicate
signing; transaction-effect validation; gap/cursor invariants; knowledge-time cutoffs; and
deterministic reducers. They do not establish market profitability or supply a missing perceptual
ontology.

## Fault lines the synthesis must resolve

### 1. `epoch`, `interval`, `clip`, `lot`, and `tranche` are not yet coherent

Lane 01 gives `inventory epoch` the precise flat-to-flat household meaning, then uses `inventory
interval` for the positive-quantity span of a management tranche. Lanes 05, 06, 07, and 08 use
`inventory interval` for the whole non-flat span inside an episode—the object lane 01 calls an
epoch. Lane 05 describes a `clip` as a realized entry/exit cash-flow sequence, while lane 06 calls
each attributable acquisition or disposition a clip. A one-sided action and a round trip cannot
both be the same primitive.

Resolution:

- Reserve **inventory epoch** for a maximal portfolio-domain flat-to-nonflat-to-flat interval in
  one mint. It is a derived accounting boundary.
- Use **exposure interval** only with an explicit scope: portfolio, episode, or tranche. It is a
  derived time interval, not a source entity.
- Use **fill** for reconciled execution quantity and cash effects.
- Use **acquisition lot** for provenance-preserving acquired units and basis.
- Use **disposal allocation** for the declared accounting consumption of lots/tranches.
- Use **management tranche** only for an explicit quantity allocation to a playbook or book. It is
  optional attribution, not token custody.
- Keep **clip** as operator-facing shorthand or a versioned analytical grouping. Do not make it a
  canonical ledger entity until Ember demonstrates one stable meaning.

This leaves the financial source of truth exact while still permitting views such as “the newer
crackle quantity on top of an older runner.” When that attribution was not prospective, the
tranche result is unknown rather than guessed after the outcome.

### 2. Episode termination is inconsistent

Lane 01 correctly says inactivity may mark an episode dormant but must not silently resolve it.
Lane 07 allows an expiry policy to close an episode. Playbook expiry and episode resolution are
different facts.

Resolution: an authorization or hot-observation level may expire automatically. An episode may
become `dormant` automatically. Only an operator resolution, an explicit versioned adjudication, or
a correction can mark it `resolved`. A dormant episode may be reopened without rewriting history.
The system can propose closure after inactivity; it cannot convert lack of interaction into proof
that the line of attention ended.

Episode identity also should not be keyed by mint. A coin-centered episode is the first default,
but a fancoin episode may follow a family across competing mints. Store a stable episode ID plus
versioned subject links. Default to one open episode per primary subject and portfolio domain, with
explicit split/link when meanings overlap. The asset ledger remains mint-keyed and unaffected.

### 3. `crackle`, `runner`, `book`, and `disposition` are being collapsed

The lanes say both that crackle is an entry/early-management mode and that `crackle` may be a
disposition. Product tables mix entry mode, current stance, thesis, horizon, and management act.
That would force Ember's multidimensional judgment back into one enum.

Resolution: maintain five orthogonal semantic axes, each optional and versioned:

| axis | question | examples |
| --- | --- | --- |
| playbook / entry mode | what watcher or early-management behavior is armed? | crackle variant, immediate entry, social-transition watch |
| current stance | what relationship to current exposure is intended? | retain, reduce-only, watching flat, undecided |
| thesis | why might continued attention or exposure be worthwhile? | might send, community coalescing, graph-only, not articulable |
| horizon / review condition | until when or what event? | minutes, creator action, open-ended review |
| management gesture | what is Ember doing now? | take some, zap, re-enter, keep remainder |

A **strategy family** is a research/program family such as crackle, retained runner, fancoin, or
LP management. A **book** is a portfolio risk-and-reporting allocation. It is not custody, episode
identity, or a mutually exclusive description of a coin. Moving an allocation between books
carries live value and basis and creates no profit.

### 4. The gesture tables disagree and mix semantic events with UI macros

Lanes 01, 02, 05, 06, and 08 variously use `take_some`, `partial_exit`, `profit + runner`,
`keep_remainder`, `reduce`, `full_exit`, `zap`, `go_flat_watch`, `stay_flat`, `close_episode`, and
`resolve_episode`. These can coexist as UI language only if the event language underneath is
smaller and compositional.

Resolution: use a stable semantic command/event core:

- `attention_marked`, `watch_started`, `watch_changed`, `watch_ended`;
- `playbook_armed`, `playbook_changed`, `playbook_cancelled`, `playbook_expired`;
- `increase_requested`, `reduce_requested`, `exit_all_requested`, `reentry_requested`;
- `disposition_asserted` and `thesis_asserted`;
- `episode_resolved` and `episode_reopened`;
- `annotation_recorded`, `comparison_recorded`, and `correction_recorded`.

Amounts, fractions, target value, urgency, and intended residual are parameters. Product macros
expand into these events:

- `ZAP` -> `exit_all_requested(urgency=immediate)`;
- `TAKE SOME` -> `reduce_requested(...)`;
- `PROFIT + RUNNER` -> a reduction request plus an explicit conditional assertion about the
  reconciled remainder; the sell is never blocked on the assertion;
- `STAY FLAT` -> continued watch after reconciled zero inventory;
- `RE-ENTER` -> a new increase request linked to the current episode.

The exact operator utterance and the UI label/version remain preserved. The canonical semantics do
not require Ember to speak like the schema.

### 5. `arm` means different authority in read-only, shadow, and live phases

In a shadow cockpit, `ARM CRACKLE` can only start observation and counterfactual policy evaluation.
In later execution designs, it creates bounded transaction authority. Reusing one unqualified
event risks turning a previously harmless gesture into capital authority after an upgrade.

Resolution: every arm names an **effect ceiling**:

```text
observe_only < shadow_propose < construct_unsigned < request_signature < execute_bounded
```

No deployment or UI update may increase the ceiling of an existing arm. Live authority requires a
new operator event and a separately issued capability. `playbook_armed` and `capability_issued` are
different records.

### 6. `read-only`, `shadow`, and `live` need component-scoped meanings

An observational cockpit may be read-only while Ember is trading real capital in Pump or Padre.
Calling the whole session “shadow” would falsely turn those external fills into simulations.
Conversely, a shadow quote is not a fill even if it later happens to match the market.

Resolution:

- **system read-only:** Joshi cannot construct, sign, or submit; it may observe public chain state
  and reconcile external actions.
- **shadow action:** a counterfactual proposal evaluated under a declared quote/latency model; it
  never changes the actual asset ledger and never uses the word `fill`.
- **external live action:** real wallet change initiated outside Joshi; intent may be observed or
  missing, and the chain effect is reconciled exactly.
- **Joshi live action:** a future transaction created through the reviewed capability path.

Keep actual and shadow inventory ledgers in visibly different namespaces. The first product phase
is system-read-only but may observe external-live episodes.

### 7. `scene`, `choice set`, `tape`, `ledger`, and `journal` need narrower meanings

The event-tape lane's three layers are sound, but the lanes call many objects “the event.” The
infrastructure lane also proposes a deterministic raw `record_id`, while lane 03 correctly says
that every acquisition has a unique observation ID even when identical bytes were fetched twice.
Content equality is not acquisition identity or event identity.

Resolution:

- **evidence tape:** the logical append-oriented corpus of observations, operator records,
  assertions, derivations, coverage, scenes, and retention actions. It is not one universal table.
- **observation:** one acquisition attempt/result from one source. It always has a unique
  `observation_id`.
- **blob:** exact retained bytes, addressed by content hash. Repeated observations may reference
  the same blob.
- **source object/event key:** a typed, source-specific candidate identity. Equal values at
  distinct chain indices remain distinct events.
- **assertion:** a versioned typed claim decoded or reconciled from evidence.
- **derivation:** a versioned computed interpretation with exact input manifest.
- **financial ledger:** the reconciled asset-flow projection, independent of strategy
  attribution.
- **journal:** reserve this word for durability-critical ordered authority records such as signer
  issuance, reservations, submissions, and reconciliation. Do not call the whole tape a journal.
- **scene manifest:** an immutable reference to the actual rendered view state, choice context,
  quote/portfolio observations, source/projection watermarks, UI version, and optional app-only
  screenshot at a consequential moment.

The **choice context** inside a scene should retain separately: census-eligible universe, source
surface set and order, client-rendered set, viewport set, interaction set, and any explicitly
ranked/compared decision set. Calling all surfaced coins “choices Ember considered” would recreate
denominator error.

### 8. Two replay modes are not enough

Lane 03's `as-known` replay sometimes means “everything the system could have known by time T” and
sometimes “what the operator actually saw.” Those differ whenever evidence was available to a
backend but not rendered, or a UI hid a field.

Resolution: define three replay products:

1. **Witnessed replay:** reconstruct the exact scene the application rendered, including its stale
   values, omissions, feature flags, and source watermarks. This is primary for operator interview.
2. **Knowledge-cutoff replay:** compute a named view using only evidence available by T and named
   parser/model versions. It answers what a specified system could have known, not what Ember saw.
3. **Retrospective replay:** use later finality, backfills, decoder corrections, and outcomes under
   an explicit modern view.

A screenshot checks witnessed replay but does not define it. A later corrected parser can be used
in a cutoff-safe analytical replay only if the report clearly distinguishes “decoded later from
bytes already possessed” from “available to the policy then.”

### 9. The privacy erasure exception must be explicit

“Raw evidence is immutable” conflicts with lane 02's justified hard-erasure path for intimate
operator data and with possible source/legal deletion obligations. This is resolvable without
pretending deletion never happens.

Resolution: immutable means no in-place semantic rewriting during ordinary operation. Retention
and deletion are explicit, authorized lifecycle events. Content may be cryptographically or
physically erased; a permitted tombstone retains identifiers, policy, and time but not the erased
content. Replay reports missing-by-retention rather than silently using an old derived cache.
Operator utterances, screenshots, voice, third-party media, public chain bytes, and derived models
may require different policies.

### 10. Hot observation cannot remain mint-only

Lane 03 keys hot lanes by mint, which is sufficient for an early crackle but not for fancoin family
migration, a represented person, a followed wallet, or an LP pool. Reusing “lane” for both research
workstreams and runtime subscriptions adds more ambiguity.

Resolution: call the runtime object a **hot scope**. It has a typed subject and manifest: mint,
coin family, person/identity, wallet set, pool/LP position, or a declared composite. Activation,
degradation, expansion, and closure are events. A hot scope may keep one mint's chain stream at
event resolution while selectively enriching its related identities and wallets. This avoids
making “watch one person” synonymous with “archive the whole world around them.”

## Ranked decisions for the root synthesis

### Rank 1 — freeze the semantic spine before selecting technology

Adopt the vocabulary above for episode, inventory epoch, fill, lot, optional tranche, disposition
axes, observation/assertion/derivation, scene manifest, replay modes, and authority level. Mark
`clip`, one-enum disposition, mint-keyed episode IDs, and automatic episode closure as deferred or
noncanonical. Every domain can extend the spine, but none may redefine it.

### Rank 2 — commission one integrated observational corridor

Do not launch eleven “smallest experiments.” The first program should be:

```text
offline adversarial replay fixture
  -> bounded live census + audited Pump-surface subset
  -> coin workbench opens a typed hot scope
  -> scene and optional operator gesture are committed
  -> external wallet actions are observed and reconciled
  -> episode/portfolio views retain partial exits, flat watch, and re-entry
  -> witnessed and retrospective replay
  -> optional immediate fragment and outcome-separated interview
```

Use the three named runners only to test current accounting/exposure fixtures; do not fabricate
their missing historical scenes. Use the next naturally encountered episodes prospectively. Fold
the 72-hour stream characterization, Pump fidelity sample, portfolio reconstruction, and one
crash/replay fixture into commissioning. Then run a calendar-bounded operator diary. Let observed
episode rate, tail behavior, capture burden, and source coverage determine later sample sizes.

### Rank 3 — adopt the infrastructure gate ladder, with one correction

Lane 09's R0–R8 ladder is the clearest cross-project capability plan. Adopt it, but explicitly
split `R3 local cockpit` from any inference that manual trading is shadow. At R3/R4, Joshi is
read-only and Ember may still take external live actions. Actual wallet facts and counterfactual
shadow actions remain distinct.

The root synthesis should authorize work only through R4. R5 unsigned construction, R6 signing
lab, R7 tiny live, and R8 reactive automation each require a new review. LP and spot receive
separate authority ladders.

### Rank 4 — decide the portfolio boundary and current-basis quality

Before portfolio claims, name the initial controlled portfolio domain: wallets, token accounts,
wrapped SOL, fee vaults, LP positions, and any custody intentionally excluded. Reconstruct exact
asset deltas and classify unknown basis rather than inventing it. Adopt SOL-native accounting with
versioned USD valuation and dated-reserve views; do not let either rewrite the other.

Preserve exact acquisition lots, while using average cost within each inventory epoch as the first
operator-facing projection if it matches Ember's mental accounting. Every realized PnL display
must name its lot convention; the fully flat epoch cash-flow result must reconcile independently of
that convention. LP deposits, withdrawals, and fee claims are custody/composition events until an
actual conversion occurs.

This decision should also set a protected reserve and a learning-loss authorization before any
future live trial. The source of money—fees, wins, or transfers—does not create “house money.”

### Rank 5 — make Pump-surface access a product gate, not a hidden adapter task

The strongest external uncertainty is lawful, stable access to the Pump discovery and social
surface. Run the fidelity/access audit early. Until it passes, call the product a companion or an
audited subset, not a complete Pump replacement. Failure of full parity does not kill the ledger,
replay, hot workbench, or wallet/ecology research, but it does invalidate claims about Ember's
complete choice denominator and may keep Pump in the operational loop.

The first parity target should be the exact surfaces Ember actually uses during the diary, not an
invented list of every Pump screen.

### Rank 6 — adopt lane 12's narrow ecology and wallet-router boundary

Lane 12 supplies the previously missing treatment and should be incorporated without turning it
into a separate platform project. Preserve:

- launches, deployers, funders, first traders, creator/fee routes, migrations, pool/LP relations,
  coin families, communities, and attention flows as a changing graph;
- Ember's Pump follows and follow/unfollow time, with the reason unknown unless stated;
- the distinction between a Pump profile, author wallet, transaction signer, funding wallet,
  deployer, fee recipient, and inferred common controller;
- every watched wallet action with chain order, our receipt time, quote availability, later
  callout/post time, and source coverage;
- lead/lag and executable shadow outcomes for wallet trade -> callout hypotheses;
- duplicate, transfer, self-trade, LP, fee-claim, and routing classifications rather than treating
  every token delta as a buy/sell signal.

`Territory` should begin as Ember's operator term and a versioned graph view, not a primitive with
assumed boundaries. `Smart wallet` and `copyable trade` should be derived hypotheses. A followed
identity may not control the wallet that trades, and a visible wallet action may arrive too late
to copy economically. The first wallet study is observational/shadow and must not authorize
copying. Treat Pump follows, explicit Joshi watches, direct signed trade activity, and inferred
wallet coordination as four different relations.

Keep lane 12's two modest product hypotheses distinct:

- **territory context:** an overlapping temporal query over launch/narrative, community, and
  trading-fleet relations, with typed edges that never collapse those three ecologies;
- **followed-wallet routing:** a candidate router whose incremental value is tested against the
  anonymous flow and board information already available at the same time.

Do not build a graph database, entity-resolution platform, wallet leaderboard, or ecological
simulator for the pilot. Piggyback a bounded territory strip and a small explicitly promoted
watchlist on the integrated cockpit diary. Lane 12's suggested 14-day/10–20-wallet/20-territory
bounds are capacity guards, not independent experiments or evidence that those counts are powered.

### Rank 7 — select scene cadence, privacy, and retention together

Choose what is captured at session start, significant viewport change, hot-scope activation, and
consequential gesture; how much ring-buffer context is retained around a mark; and when an app-only
screenshot is taken. Make app-scoped interaction the default. Define hard erasure and hosted-model
export rules before accumulating intimate notes, screenshots, voice, or portfolio traces.

### Rank 8 — preserve operator usefulness as an acceptance gate

The cockpit must replace enough of the normal inspection loop that it records the real process.
If Ember repeatedly returns to Pump for missing context or if the pre-action gesture delays manual
execution, this is an instrument failure, not user noncompliance. Measure switching, gesture
overhead, target errors, and deferred prompts. Do not optimize annotation completion.

### Rank 9 — keep storage and vendors reversible until measurement

Official Pump/PumpSwap/Meteora SDK use, exact IDL/version pinning, and provider-neutral adapters
are earned decisions. PostgreSQL, React/Vite, Lightweight Charts, a particular Yellowstone vendor,
Jupiter routing, Tauri, Kafka, ClickHouse, Advanced Charts, or a managed signer are not yet project
commitments.

A boring local stack is a reasonable implementation hypothesis, but first measure event volume,
concurrency, replay cost, and chart/annotation needs. No vendor's enriched object becomes canonical.

### Rank 10 — state what formal methods will and will not own

Write executable invariants early for:

- exact integer asset conservation and portfolio reconciliation;
- episode/epoch independence and append-only attribution;
- observation identity, causal cutoffs, gaps, and replay determinism;
- cursor/evidence atomicity and crash recovery;
- quote freshness, fee/state binding, and no mark-as-fill substitution;
- capability monotonicity, reservations, transaction effect bounds, idempotent submission, and
  no conflicting action while unresolved.

Use property-based and state-machine testing first. Apply model checking or proof where concurrency
or monetary authority makes testing inadequate—especially reservation/signing protocols and
multi-step LP transformations. Do not formalize the provisional disposition taxonomy, infer a
stationary market circuit, or treat program synthesis as a commitment. Those abstractions should
remain empirical partial specifications until the sensor language has support.

## Proposed coherent vocabulary

| term | proposed canonical meaning | explicitly not |
| --- | --- | --- |
| portfolio domain | versioned set of controlled custody locations consolidated for economic accounting | a strategy book or one wallet |
| financial ledger | exact, provenance-linked asset-flow and balance projection over the portfolio domain | episode story, mark-price report |
| operator episode | stable identity for one continuous line of attention/intent, across zero or many inventory epochs | position, mint lifetime, flat-to-flat trade |
| subject link | versioned relation from an episode/hot scope to mint, family, person, wallet, pool, or narrative | the episode primary key |
| inventory epoch | maximal interval in which portfolio-domain quantity of one mint is nonzero, bounded by exact flat | episode boundary |
| exposure interval | derived positive-exposure span at a named portfolio/episode/tranche scope | an unscoped synonym for epoch |
| fill | reconciled asset effect of a landed economic action | order, submission, vendor response |
| acquisition lot | exact acquired units with provenance, basis quality, and remaining quantity | current position or strategy thesis |
| management tranche | optional explicit allocation of fungible quantity to a playbook/book/disposition | SPL account, inferred tax lot |
| clip | noncanonical display/analysis grouping with a declared rule | ledger primitive |
| LP schedule version | exact per-bin inventory and contingent conversion surface before/after an LP transformation | yield balance, spot position, realized sale |
| strategy family | research/program family such as crackle, runner, fancoin, or LP | custody bucket |
| book allocation | prospective risk/reporting allocation on one consolidated balance sheet | source of money or independent asset pile |
| playbook | versioned watcher/management logic and parameters | prediction of profit, authority by itself |
| disposition / stance | Ember's current intended relationship to an episode or tranche | entry type, fill, thesis, horizon |
| thesis | Ember's reason or hypothesis, including free text or `not articulable` | mandatory causal explanation |
| gesture | persisted operator act in a scene | transaction or proof of intent completion |
| intent | requested economic or observational action with parameters | fill |
| capability | bounded, expiring authority ceiling issued separately from playbook semantics | persistent arm flag |
| observation | one source acquisition attempt/result with unique identity and true acquisition clocks | canonical fact |
| assertion | versioned typed claim supported by observations | immutable eternal truth |
| derivation | versioned computed/model interpretation with exact inputs and production time | raw evidence |
| evidence tape | logical corpus containing observations, operator records, assertions, derivations, scenes, and coverage | one table or one universal event row |
| coverage window/gap | evidence about what a source/scope observed or failed to observe | global process-up Boolean |
| choice context | separate eligible, surfaced, rendered, viewport, interacted, and explicitly compared sets | proof of human consideration |
| scene manifest | immutable record of actual view state, evidence watermarks, quotes, portfolio state, and optional screenshot at a moment | screenshot alone, whole database snapshot |
| hot scope | typed, manifest-driven increase in observation fidelity | research-document lane, necessarily one mint |
| witnessed replay | reconstruction of what was actually rendered | all information the backend possessed |
| knowledge-cutoff replay | named recomputation using only evidence available by a cutoff | what Ember necessarily saw |
| retrospective replay | later best account with backfills/corrections/outcomes | decision-time input |
| shadow action | counterfactual action/quote under a declared model | fill or real PnL |
| external live action | real wallet action initiated outside Joshi and later reconciled | Joshi execution |
| journal | durability-critical ordered authority/reservation/submission record | generic name for all evidence |
| identity evidence graph | bitemporal, typed claims linking people, platform IDs, profiles, wallets, fee routes, and accounts | mutable creator column or scalar certainty |
| coin family | versioned hypothesis that several mints compete for or represent a relatively specific subject | eventual winner, exact-name collision set |
| territory | overlapping, revisable attention niche connecting families/coins around a person, story, event, phrase, media object, or community | partition, permanent canonical coin, predictive state machine |
| ecology relations | typed launch/narrative, community, and trading-fleet edges kept distinguishable | one graph edge meaning “related” |
| followed-wallet hit | directly evidenced watched-address action that may route a candidate into a hot scope | endorsement, wallet skill, instruction to copy |

## One coherent pre-engineering program

### Phase A — semantic and adversarial commissioning

Freeze the vocabulary, clocks, missingness, evidence identity, scene manifest, three replay modes,
and read-only effect ceiling. Exercise one synthetic crash/replay path containing duplicate and
conflicting observations, parser drift, source gap, inspect, arm, external exit, flat watch,
re-entry, partial reduction, and runner assertion. Require deterministic projections and explicit
degradation.

This is where formal specification has immediate leverage. It should not require a general event
warehouse or final UI.

### Phase B — source and premise characterization

Run bounded chain-stream completeness/recovery and Pump-surface fidelity/access tests. Measure raw
volume, latency, ranks, social/thread coverage, mutable fields, legal/operational stability, and
cost. Select only the initial Pump surfaces Ember actually uses. Confirm that current runner and LP
asset quantities can be reconstructed across the declared portfolio domain.

### Phase C — integrated read-only cockpit diary

Use one daily surface, one coin workbench, one episode/exposure rail, and one replay path during
real sessions. Open typed hot scopes on inspection/arm. Record simple operator gestures and exact
free text without requiring a taxonomy. Observe external wallet actions, never infer missing
intent, and maintain separate shadow quote paths.

Capture the next natural partial realization, retained remainder, full exit while watching, and
re-entry if they occur. Do not create capital actions to fill fixtures. Add a small set of
followed-wallet and ecology observations without presenting them as recommendations. Keep the
social transition docket prospective if source access permits.

The commissioning block ends on apparatus criteria, not PnL: balance closure, recognizable
witnessed replay, low-distortion gestures, explicit coverage, quote semantics, and no future
leakage.

### Phase D — freeze the first evaluation protocols

Use the diary to choose supported shadow policies, effective episode/regime units, source-quality
gates, terminal horizons, and power planning. Only then freeze later chronological blocks for
selection, wait timing, exit/re-entry, retained-runner, wallet-lead, or social-transition claims.
Each component may fail independently. Do not let a successful instrument become evidence of
alpha, and do not let an unresolved strategy erase the usefulness of the instrument.

## Important omissions and risks that remain

- **Ecology and watchlist scope:** lane 12 supplies a bounded treatment, but the initial promoted
  profiles, direct signer mappings, alert budget, and useful territory gestures remain empirical
  choices. Pump follow edges cannot be treated as verified trading-wallet control.
- **Manual execution displacement:** a read-only cockpit still forces a switch to Pump/Padre for
  action. The exact decision-to-send path may remain partially unobserved until an acceptable
  bridge exists. This limitation must be measured, not patched with transaction timestamps.
- **Family-spanning episodes:** fancoin duplicate migration can cross mints. The first data model
  must permit subject links without forcing cross-mint accounting attribution.
- **Portfolio-domain definition:** current documents do not settle which wallets, fee vaults, LP
  accounts, obligations, and external custody are in scope.
- **Source legality and durability:** parity and social retention may be limited even when reverse-
  engineered endpoints technically work.
- **Historical model leakage:** an LLM queried later may know the outcome through training or web
  context even when its supplied prompt is cutoff-safe. Early historical LLM use should be labeled
  interpretive, not causal, unless this is controlled.
- **Interference and capacity:** shadow replay assumes Ember's action does not materially alter the
  path. That fails first in shallow pools and under breadth. Capacity is part of every estimand.
- **Normative portfolio objective:** PnL, SOL growth, USD obligations, tail survival, attention,
  and learning value cannot be collapsed without Ember choosing tradeoffs. Preserve components.
- **Tax and compliance accounting:** deliberately outside the current lot model. Do not imply the
  operator-facing average-cost projection is tax reporting.

## Decisions that should remain deferred

- the names and count of Ember's crackle types and dispositions;
- automatic runner promotion, re-entry, averaging down, or episode resolution;
- LP range/weight policy or whether in-place rebalance is economically best;
- a predictive model family, social scalar, sentiment score, or universal “circuit”;
- a whole-market autonomous strategy or linear scaling assumption;
- a particular database, stream vendor, chart license, router, sender, signer, or desktop wrapper;
- fixed sample sizes for profit claims before pilot dependence and tail rates are known;
- continuous screenshots, ambient audio, global input capture, or external model upload;
- any transaction construction, signing, or submission authority.

## Bottom line for synthesis

The lanes support proceeding. They support building an evidence-rich personal workstation before
building a bot. They do not support eleven independent prototypes, one giant event enum, a single
disposition dropdown, or a live engine.

The root synthesis should make one compact commitment:

> Build a system-read-only, locally controlled observational corridor that preserves the market
> denominator, actual rendered scenes, Ember's low-friction gestures, exact external wallet
> effects, evolving episode meaning, and three kinds of replay; surround it with replaceable
> source/rendering plumbing; and let prospective use determine the ontology and later studies.

That is enough structure to begin without freezing the market theory. It is also enough rigor for
future nulls, successes, and disagreements to refer to the policy Ember actually enacted.
