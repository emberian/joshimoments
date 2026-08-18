# Engineering lane 24: runway-aware delivery and option economics

Status: delivery economics and sequencing proposal, 2026-08-16. No implementation, purchase,
private-key or wallet authority, transaction construction, signing, submission, or capital
authorization is implied.

## Executive judgment

Useful revenue or leverage before September matters to whether the project can continue. Profit
cannot be made a scheduled engineering milestone. The schedule can, however, produce a tool that
helps Ember make existing manual decisions, prevents some accounting and exposure mistakes, and
begins accumulating the high-resolution prospective evidence needed to find out whether the
strategy has value.

The best runway-adjusted architecture is a **greenfield, local, companion-capable vertical core**:

- one exact-mint workbench;
- one read-only exposure/episode rail;
- one genuine event-backed chart;
- current size-specific executable quotes when supportable;
- a tiny semantic gesture/event core;
- external-wallet reconciliation;
- scene capture and witnessed replay;
- and, if Spike 0 proves access, one local Pump discovery surface plugged into the same shell.

This core can begin useful life beside Pump/Padre and later become a replacement surface. It avoids
making full Pump parity a precondition for any value. It also avoids the opposite error of building
a post-selection dashboard and calling it a complete attention instrument.

The before-September delivery claim should be:

> Ember can use one thin, honest Joshi loop during natural manual sessions, and the resulting
> episode record is useful even if no strategy profit occurs.

The claim must not be:

> Joshi will produce trading profit, automate crackles, or establish positive expected value by
> September.

With roughly two weeks from this review to September, Slices 0–2 are the planning horizon. Slice 3
may begin only if the earlier work lands unusually cleanly; Slices 4–5 are option value, not August
commitments.

## Delivery constraints that actually matter

### The machine is not the bottleneck

The development machine is Apple arm64 with 96 GiB RAM. .NET 10, Rust nightly, OCaml/opam, Node,
Python/uv, Julia, and Docker are already installed. No language, runtime, container, or compute
purchase is needed to build the first local cockpit.

This argues for using the smallest familiar stack, not for exploiting every available toolchain.
React/TypeScript, a small local API, SQLite or an equivalently boring transactional store, and
content-addressed raw files are sufficient for the pre-September corridor. Introducing Rust,
OCaml, Lean, a graph database, ClickHouse, or containers into the critical path needs a measured
failure that the simpler stack cannot solve.

### The compost is an asset and a migration hazard

`~/dev/joshibot` contains at least 74 GiB of state, studies, and tape, roughly 164,000 lines of
project Python, and roughly 9,400 lines of TypeScript/TSX. It contains valuable fixtures and several
correct local invariants. It also contains the old ontology, many policy experiments, large
historical artifacts, and live-adjacent components that should not define the new system.

The runway-optimal treatment is:

1. inventory a named donor;
2. extract the smallest fixture, pure function, UI pattern, or adversarial test needed by the
   current slice;
3. copy it into `joshi` with provenance and a conformance test;
4. leave the remaining code and 74+ GiB in place as read-only compost;
5. never bulk-import old state into the new canonical tape.

A bulk migration could consume the entire pre-September window while preserving none of the new
decision context. Selective fixture extraction is therefore on the critical path; corpus migration
is explicitly not.

### Ember's ordinary use is a scarce dependency

Natural cockpit use cannot be parallelized away. Ember must supply a few ordinary sessions, quick
parity judgments, and corrections to episode/gesture semantics. The interface cannot be validated
by agents role-playing the operator. Product sessions should be short and scheduled at decision
gates so engineering does not turn Ember into a full-time annotator.

### Capital is not an engineering test fixture

The project may observe real manual trades initiated in existing tools. It may not create trades to
meet a sample count or validate a pipeline. A read-only system can still produce immediate
decision leverage and exact economic reconciliation. Any PnL during the corridor is an observed
operator outcome, not a release acceptance criterion.

## Separate the scheduled milestone from the profit hypothesis

There are four distinct value claims:

| level | schedulable before September? | acceptance evidence |
| --- | --- | --- |
| **Instrument/tooling value** | yes | exact exposure, honest quotes/gaps, natural gestures, recognizable witnessed replay |
| **Decision-support value** | partly | Ember uses the loop voluntarily; it reduces tool switching, forgotten exposure, or ambiguity without increasing errors |
| **Composite-policy profit** | no | prospective, executable, cross-regime episode results versus attainable baselines |
| **Automation/scale profit** | no | later bounded execution, measured fill behavior, held-out policy evidence, capacity and tail-risk gates |

The pre-September milestone is the first row and an early signal on the second. It must remain useful
if rows three and four later fail.

Possible immediate leverage includes:

- knowing the actual executable value and remaining risk of RADON, EarthCoin, and CRASHIUS;
- seeing realized cash, remaining basis quality, and residual exposure in one place;
- keeping an exited coin visibly alive while flat and preserving the re-entry scene;
- showing that a contemplated crackle target is below the current economic hurdle;
- preserving the chart/social/portfolio context for a later replay instead of relying on memory;
- and reducing accidental forgotten runners or contradictory simultaneous commitments.

These can protect capital or improve manual decisions. They are not forecast revenue and must not
be entered into a runway plan as expected profit.

## Architecture options and their economics

Time ranges below are planning ranges after the first access decision, assuming the minimum
parallel team described later. They are not commitments. “Recurring cost” excludes developer time
and assumes existing machine and network access; no purchase is authorized.

| option | time to first natural use | information gained per week | reversibility | recurring cash cost | operational burden | failure containment | useful stopping artifact |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **A. Greenfield local companion core** — recommended | 3–6 focused days | very high for exposure, management, gestures, and replay; selection denominator partial until companion/feed capture lands | high; local API and adapters can later feed a replacement UI | target $0 incremental using existing/public read paths; local storage only | low–medium; one local start path and a few source health checks | strong if process is structurally keyless and source gaps are explicit | exposure/episode rail, coin workbench, replayable prospective diary |
| **B. One-surface Pump replacement first** | 7–14 days *if* Spike 0 is green | highest if Ember actually moves discovery into it; near zero if one missing cue sends them back to Pump | medium–high if built on the same local core; low if feed semantics infect the domain | $0–medium initially; could later require paid stream/social access | medium–high due rank, media, social, and frontend drift | good while read-only, but source failure can silently destroy the denominator unless audited | a useful single-feed market viewer and workbench even if broader parity stops |
| **C. Reviewed Pump companion capture** | 3–7 days after access/terms decision | very high for the *actual* Pump choice set and fast natural use | medium; DOM/layout adapter is replaceable but brittle | target $0 incremental | medium; browser/version drift and privacy/retention handling | financially strong while read-only; evidence containment depends on explicit DOM break/gap detection | faithful Pump-assisted episode recorder plus local exposure/quote/replay glass |
| **D. On-chain-first Joshi observatory** | 4–8 days | high for a newly defined Joshi universe and wallet/flow context; cannot identify the Pump selection funnel | high; deterministic own board is under project control | low with existing standard RPC; higher only if measured volume later earns a stream | medium; program decoding and gap recovery, less social drift | strong if unsupported states fail closed | reproducible launch/activity board, hot workbench, wallet candidate router foundation |
| **E. Patch the old `joshibot` dashboard** | 1–3 days to an apparent screen; unpredictable to a truthful loop | initially moderate, then low because old position/hunch/paper semantics contaminate new evidence | low; every patch deepens runtime dependence on the compost | low cash, high engineering attention | high; many modules/daemons and live-adjacent code paths | weak relative to a new keyless process; old assumptions are dispersed | a better legacy dashboard, but not a trustworthy new corpus |
| **F. General data platform first** | several weeks or months | low before natural use; potentially high later | low after provider/storage/schema commitments | medium–high for streams, storage, and maintenance | very high | potentially strong eventually, but no early product validates what it preserves | collectors and infrastructure without proof they instrument the relevant policy |

### Recommended option structure

Choose A as the stable center. Spike 0 chooses B, C, or D as the discovery adapter around it:

```text
                         +-> B: one local Pump surface
greenfield local core ---+-> C: Pump companion capture
                         `-> D: Joshi-defined on-chain surface
```

This preserves work across the access decision. The episode rail, wallet reconciliation, coin
workbench, gesture events, scene manifest, and replay do not care whether a candidate arrived from
a local board, a companion capture, a watched wallet, or a pasted exact mint. The choice context
does care, so the source mode remains explicit in every scene.

Option E should contribute donors only. Option F is rejected for the runway horizon.

## Small implementation choices with large runway effects

### Local browser shell versus desktop packaging

Use a loopback local web application for the first corridor. It is fast to inspect, has a mature
React/Lightweight Charts donor, and keeps UI iteration cheap. Tauri earns consideration only if a
reviewed companion capture, trusted global hotkey, or later signer boundary requires it. Packaging
does not create product value in August.

### One transactional writer versus a service mesh

Use one durable evidence/command writer with typed idempotency keys. Collectors may be separate
processes if source failure isolation requires it, but they append through one narrow interface or
spool. Do not create independent databases per lane. A local SQLite control/evidence index plus
content-addressed raw blobs is sufficient until concurrent write or query measurements prove
otherwise.

The minimum evidence header freezes only:

- unique acquisition or operator record ID;
- kind and typed subject;
- source and source contract/collector version;
- source/chain time when genuinely supplied;
- receive, persist, render, and gesture clocks where applicable;
- raw blob reference/hash;
- coverage/gap state;
- producer/parser/product version; and
- links to the scene/episode when known.

Domain payloads remain versioned and source-specific. Do not spend the runway designing every
future social, LP, model, and signer record.

### Selective grafts versus a runtime dependency on `joshibot`

Copy only the donor organ under test. The first candidates are:

- honest chart renderer and evidence-state visual grammar;
- list-freeze behavior;
- read-only social endpoint probe fixtures;
- exact integer, clock, gap, and reserve invariants;
- conservative wallet-lot reconstruction and unknown-basis cases;
- append-before-readback operator gesture fixtures; and
- old null, disappearance, duplicate, and parser-drift examples as regression tests.

The new process must not import `shitcoims_*` packages through `PYTHONPATH`, point at the old state
tree as writable canonical storage, or start the old sentinel/signer/executor to save time.

### Existing/public sources versus a pre-September vendor purchase

No paid low-latency source is required to determine whether the product loop is usable. Use existing
access, standard Solana RPC/WebSocket, and bounded read-only probes. If the only route to one-surface
parity requires a new paid plan, the gate compares its cost and stability after the workload is
measured. It does not purchase under deadline pressure.

## Critical path to a pre-September artifact

The dates are decision targets, not promises of profitability or even completion. A failed gate is
allowed to select a smaller useful artifact.

### Gate R0 — freeze the delivery spine, August 16–17

Freeze only the distinctions required for the first corridor:

- operator episode versus inventory epoch;
- raw observation versus assertion/derivation;
- witnessed scene versus knowledge-cutoff and retrospective replay;
- operator gesture versus external transaction/fill;
- current stance/thesis versus inventory change;
- effect ceiling `observe_only` or `shadow_propose`; and
- explicit missing/stale/gap states.

Also freeze the no-key/no-builder/no-broadcast boundary and a short donor manifest. Do not freeze
the complete ontology.

**Pass:** the UI, wallet reducer, scene recorder, and source adapter can share a small contract
without redefining those distinctions.

**If failed by August 17:** reduce to a read-only inventory/quote report and witnessed manual scene
capture. Do not compensate with more design meetings or a universal schema.

### Gate R1 — Spike 0 and access mode, target August 18–19

Run the bounded Pump workflow/source truth test from the vertical-slice review. In parallel, verify
one genuine chart source, one size-specific quote path, and the current wallet scope. Select
replacement-capable, companion-capable, on-chain observatory, or stop/rethink.

**Pass:** one mode has a documented access basis, measured candidate/context coverage, a known
breakage mode, and enough fidelity for one natural workflow.

**Fallback:** the exact-mint companion workbench remains valid even if no discovery mode passes.
That fallback can study management but must not claim to measure selection.

**Deadline danger:** calling a similar public list “the Pump feed” to avoid the gate would create a
false denominator and invalidate the central research object.

### Gate R2 — Slice 1 exposure truth, target August 20–23

Deliver the smallest stop-worthy tool:

- exact current quantities for the scoped wallet;
- RADON, EarthCoin, and CRASHIUS as current runner fixtures;
- realized/basis quality where reconstructable, with unknown left unknown;
- full-size liquidation quote or explicit unquotability;
- one exact-mint workbench with genuine chart and source health;
- minimal acts and append-only scene capture;
- observation of external wallet changes; and
- one witnessed replay.

Historical accounting must not block current visibility. If complete history is expensive or
ambiguous, ship exact quantity/current liquidation and an explicit basis gap. The system must not
invent basis to make the card look finished.

**Pass:** Ember finds the rail/workbench useful in a normal session, current balances reconcile,
one prospective act replays recognizably, and there is no money-moving capability.

**Stop artifact:** even if the project pauses here, Ember retains a trustworthy exposure monitor,
manual episode notebook, and first prospective evidence corpus.

### Gate R3 — Slice 2 natural discovery loop, target August 24–29

Attach the selected discovery mode to the same core. Preserve served order, viewport, originating
scene, hot workbench, social/context fields that proved material, stable targeting, external fill
reconciliation, and the episode rail.

Use two or more short ordinary sessions to find material omissions early. The target is not a
polished dashboard; it is one workflow Ember chooses to use without being asked to perform a test.

**Pass:** Ember stays in Joshi/companion mode for the selected information loop except for
intentionally external execution; consequential gestures have replayable scenes; parity/source
defects are measurable; capture burden does not block a time-sensitive act.

**Stop artifact:** a useful single-feed viewer or faithful Pump companion plus the exposure and
episode instrument.

**Deadline danger:** omitting images, thread structure, neighboring candidates, or update rhythm
because their database fields seem secondary may make the UI fast to ship and useless for the
actual judgment being measured.

### Gate R4 — August 30 runway review

Review only:

- voluntary natural use;
- missing material cues;
- balance/quote/replay integrity;
- source and operational burden;
- observed decision leverage or avoided ambiguity;
- and the cost of continuing.

Do not promote August PnL into a strategy result. There will be too little prospective independence,
and the product will have changed during the window.

**Continue into September** if the tool is naturally used, the evidence corridor is credible, and
one next slice has clear marginal value.

**Hold at the useful artifact** if the rail/workbench helps but parity is not ready.

**Pivot to companion or observatory** if access is the blocker.

**Stop expansion** if Ember returns to existing tools for material context, capture feels clerical,
or the engineering system requires more upkeep than the leverage it creates.

### Gate R5 — Slice 3 shadow crackle, September option

Only after R4 should the project add event-level shadow arming, candidate microdip interpretations,
latency perturbations, partial/runner paths, flat-watch/re-entry comparisons, and calibrated quote
error. This is the first component that can begin testing execution-scale economics. It remains
system read-only.

Attempting to pull R5 into August risks spending the window on quote engines and policy simulators
before Ember naturally uses the observation surface. It also encourages an early PnL narrative
from under-calibrated shadows.

## Dependency graph and parallel work

```text
semantic/no-authority spine -----------+
                                       |
Pump/source truth test -> mode choice --+-> natural cockpit session -> witnessed replay -> R4
                                       |
wallet reconciliation + quote probe ---+
                                       |
local UI shell + selected donor grafts -+
```

The merge points are the critical path. Source probing, wallet reconstruction, and UI shell work
can run concurrently, but none can invent the shared contract independently.

### Minimum staffing/agent assumptions

The planning ranges assume:

- **one integrating owner** with exclusive responsibility for semantic contracts, merge order,
  effect ceiling, and the running local artifact;
- **one source/accounting lane** for Pump access probes, wallet reconstruction, chart/quote inputs,
  and source-health fixtures;
- **one product/replay lane** for the local shell, episode rail, gestures, scene manifest, and
  witnessed replay;
- **one reliability/test lane**, which may be a part-time agent, for crash/gap/idempotency fixtures,
  secret/broadcast absence checks, and cross-lane conformance;
- **Ember as operator**, supplying three or more short natural sessions and fast accept/reject
  judgments at R1–R4.

This is one integrator plus two active implementation lanes and one bounded verification lane—not
four independent architectures. A maximum of three agents should edit code concurrently during the
first corridor. More parallel agents increase interface churn and review debt faster than they
reduce the nonparallel product-feedback path.

If only one implementation lane is available, preserve R2 and companion-mode scene capture; drop
local discovery parity from the pre-September commitment. If Ember cannot supply ordinary sessions,
ship the exposure truth artifact and pause claims about natural cockpit use.

Daily integration should produce one runnable state, not a pile of branches. No lane may widen the
effect ceiling, add a paid dependency, or import old canonical state without the integrating owner
and the corresponding gate.

## Information gain per week

The delivery order is designed around uncertainty retired per unit time:

| deliverable | primary uncertainty retired | information value if project stops |
| --- | --- | --- |
| Spike 0 source/fidelity matrix | can Joshi lawfully and technically observe the loop that matters? | prevents months building an impossible or misleading replacement |
| current exposure truth | can the ledger represent actual runners and external wallet changes honestly? | immediate treasury/risk visibility and reusable accounting fixtures |
| gesture + scene + witnessed replay | can the system capture Ember's behavior without replacing it? | unique prospective corpus and a reusable personal episode notebook |
| one natural discovery loop | will Ember voluntarily move attention into the instrument? | a useful daily viewer/companion even without strategy proof |
| query-only shadow hurdle | are micro-profit questions resolvable at the intended economic scale? | prevents testing targets smaller than source/quote error |
| selective wallet/territory pane | does one new context route useful attention beyond the base surface? | bounded discovery tool; easy to shelve if noisy |

This ordering also protects against the most expensive false positive: a technically impressive
data system that does not become the place where the decision happens.

## Stop/continue portfolio of small deliverables

Each deliverable should be releasable and reviewable independently.

### D0 — access and fidelity dossier

**Cost envelope:** several sessions and bounded probes; no purchase.  
**Continue if:** one operating mode is credible.  
**Stop with:** a definitive build/companion/observatory decision and a field-level source map.

### D1 — runner and exposure truth view

**Cost envelope:** one scoped wallet and three named fixtures.  
**Continue if:** balances/quotes are honest and Ember consults the view.  
**Stop with:** a useful local portfolio/risk tool even if behavior capture pauses.

### D2 — prospective episode notebook

**Cost envelope:** minimal acts, scene manifest, one replay, no final taxonomy.  
**Continue if:** gestures remain natural and replay restores the decision scene.  
**Stop with:** a high-quality personal decision diary and reusable event/replay substrate.

### D3 — one-surface cockpit or companion

**Cost envelope:** exactly one observed workflow, not all Pump surfaces.  
**Continue if:** Ember voluntarily uses it and gaps are measurable.  
**Stop with:** a focused market viewer plus D1–D2.

### D4 — calibrated shadow crackle

**Cost envelope:** one mint at a time, query-only, after natural use.  
**Continue if:** quote/latency error is below the intended net edge and the apparatus separates
selection, waiting, and management.  
**Stop with:** a trustworthy execution-feasibility report; no need to build a signer.

### D5 — one selective breadth card

**Cost envelope:** either a 10–20-profile wallet router or at most 20 hot territories, not both
automatically.  
**Continue if:** it repeatedly supplies useful lead time/context at tolerable attention cost.  
**Stop with:** a bounded identity/family evidence view; shelf the trading-signal hypothesis.

The portfolio rule is simple: never have more than one unfinished operator-facing deliverable and
one bounded source/reliability spike in flight. A research lane does not earn indefinite engineering
merely because its future dataset might be valuable.

## Recurring-cost and operational envelope

### Before September

- incremental paid data budget: **$0 target**;
- deployment: local machine only;
- storage: a new small `joshi` store, never a copied 74+ GiB corpus;
- processes: one UI/API start path plus only the collectors needed for the selected loop;
- source health: visible in the product, not a separate operations dashboard;
- backups: only the small irreplaceable prospective evidence and configuration;
- models: no hosted realtime LLM dependency;
- execution: no builder, signer, send client, or managed wallet product.

### A cost may be considered later only when

- the exact workload, event volume, latency, and recovery requirement have been measured;
- the free/existing path has a named failure affecting product value;
- the provider can be replaced behind an adapter;
- the recurring amount fits the runway without relying on future trading profit; and
- the useful artifact continues in a degraded mode if the subscription ends.

A subscription whose cost must be repaid by an unvalidated crackle strategy is not infrastructure;
it is leveraged speculation on the research result.

## Opportunity-cost traps

1. **Bulk legacy migration.** Reading or copying 74+ GiB and harmonizing 164k Python lines can fill
   the entire runway. Extract fixtures on demand; leave history in compost.
2. **Full Pump parity before any use.** A companion-capable core creates data sooner. One missing
   social cue can defeat a wide but shallow clone.
3. **General event-platform design.** Every day spent naming future events is a day without a
   prospective scene. Freeze the spine, not the universe.
4. **Premature live execution for “revenue.”** It adds the largest safety surface before the
   strategy and instrument are calibrated. Manual trading already supplies real outcomes.
5. **Perfect historical PnL as a UI blocker.** Exact current quantities and explicit unknown basis
   are more useful than a delayed synthetic total.
6. **Paid latency before natural use.** Faster data does not help a cockpit Ember does not use.
7. **ML, LLM, program synthesis, and embeddings.** These consume the scarce prospective corpus
   before it exists and can alter the operator policy being measured.
8. **Formal verification outside the authority/evidence boundary.** Verify conservation,
   idempotency, cutoffs, and later signer effects; do not formalize a speculative market ontology.
9. **Mobile, packaging, and visual polish.** Desktop local use is enough to test the loop. Polish
   after repeated use reveals what deserves stable placement.
10. **Agent over-parallelization.** Ten clever components built against ten slightly different
    event meanings cost more integration time than they save.
11. **Background collector proliferation.** Every daemon adds silent-gap and operational burden.
    Collect only what the current surface renders or what a bounded spike measures.
12. **Treating project work as free.** Every additional dashboard, study, and provider integration
    displaces both Ember's market attention and other high-leverage projects.

## Deadline pressure: explicit unsafe shortcuts

The following shortcuts would make the system less safe or the evidence less credible. Missing the
date is preferable to taking them.

| shortcut under pressure | damage |
| --- | --- |
| reuse an old key-bearing or broadcast-capable process for convenience | collapses the read-only boundary; a display/research bug can reach money |
| add a signer or tiny-live send to demonstrate “real value” | turns an observability milestone into a capital experiment without capability, reconciliation, and loss gates |
| call a last trade, chart mark, or broad percentage-window reconstruction an executable price | can green-light a target that does not survive fees, size, latency, or impact |
| treat a submitted/external signature as the intended fill | corrupts accounting and can authorize contradictory downstream state |
| fabricate basis from the current quote | produces reassuring but false PnL and stop semantics |
| skip source/terms review and depend on unsupported Pump routes as if permanent | creates revocation, breakage, and collection-risk exactly at the product's core |
| substitute a similar public board for the actual Pump choice set | manufactures selection denominators and invalidates operator-uplift studies |
| omit gaps, source failures, or disappearing coins to keep the UI green | selects survivors and hides the regimes most relevant to loss |
| let later metadata, identity, posts, or parser corrections appear in witnessed replay | leaks the future into Ember's supposed decision scene |
| force early crackle/disposition buttons to simplify the schema | trains Ember to emit our vocabulary and destroys the object we intended to learn |
| merge external manual trades into Joshi intents after seeing outcomes | creates hindsight intent and falsely credits the system |
| run independent agents against writable old and new state without one integration owner | risks inconsistent facts, duplicate ingestion, and accidental mutation of user data |
| buy a provider plan because integration is easier | converts a reversible source experiment into recurring runway burn before workload value is known |

Two forms of deadline pressure deserve separate emphasis:

- **Safety compression** attempts to reach live capital sooner. It is categorically out of scope.
- **Evidence compression** attempts to make the cockpit look complete by filling unknowns or
  substituting proxies. It is less visibly dangerous but can waste the entire project by teaching
  from a false process.

## What success before September actually looks like

The strongest plausible pre-September result is not a profitable bot. It is:

- one access mode has been honestly selected;
- the three named runners and current wallet exposure are legible;
- a coin can be inspected through a genuine chart and current economic quote;
- Ember can mark, remain flat while watching, re-enter, take some, keep a remainder, zap externally,
  and resolve without the tool forcing an ontology;
- one natural session produces a witnessed scene and a retrospective replay;
- external wallet changes reconcile or remain explicitly unattributed;
- the product stays keyless and costs no new recurring money;
- and the whole artifact can be stopped there without becoming useless.

If, during that use, Ember earns money manually, record it as part of the episode with all residual
exposure and uncertainty. Do not cite it as proof that the project will fund itself. The engineering
achievement is that future wins and losses will finally be evidence about the process actually
used.

## Recommendation

Fund the runway as a sequence of options, not one platform bet:

1. spend the first option on the access/fidelity decision;
2. exercise the second only to build current exposure truth and one replayable exact-mint loop;
3. exercise the third only if Ember finds that artifact useful, attaching one discovery mode;
4. hold shadow crackle, wallet routing, territories, LLM work, and live execution as later options;
5. stop at any gate with the useful artifact already earned.

This plan does not maximize the number of components started before September. It maximizes the
probability that September begins with something Ember actually uses, a corpus worth learning from,
and enough architectural reversibility to keep going if the strategy, source access, or runway
turns out differently than hoped.
