# JOSHI — the desk platform (v2 design)

Design document, 2026-08-15. Status: **design lane output — no code here, no code changed.**
Companions: `design/domain-model.md` (type sketches), `design/glass.md` (the personal pump
app), `design/reconciler.md` (the only tape→journal bridge, designed as an instrument).
This document **supersedes SUBSTRATE.md where they conflict**; §10 reconciles them explicitly.
The house rules bind: PROGRAM.md §3 methodology, the Lean tripwire, harden-don't-rewrite.

Target repo: `~/dev/joshi` — because it's more than just a bot now. This repo (`joshibot`)
becomes the organ donor and reference implementation; it keeps running throughout.

---

## 0. What JOSHI is

**The operator's personal copy of the pump app.** Operator, verbatim: *"basically JOSHI is
turning into my personal copy of the pump app. we should be thinking about it that way
explicitly."* Adopted as the product definition. JOSHI-glass is pump.fun rebuilt for one
operator: the same daily surfaces — trenches/new-coins feed, callouts, boards/trending, the
coin page, the quick-trade panel, the creator/fee view — served from **our** tapes with the
instrument disciplines (provenance on hover, n beside every rate, four-state data), with the
operator-native gestures (hunch, zap, expectation, duel) woven in. Parity surfaces are the
spine and ship first; superpowers second; the engine room (journal, playbooks, models)
underneath. The frame also settles the one exception cleanly: JOSHI clones the *consumer*
surface the operator lives in daily — the **creator** side (launching) stays on the real
pump.fun, manual forever, because the renewable asset is the launch capability, not a button.

**One glass.** The same app absorbs the other three tabs — trade.padre.gg, jup.ag,
app.meteora.ag — as panels of that personal pump app: charts, positions, LP book, fee
streams, orders, all from our own tapes and our own execution rails.

**One log.** An append-only, typed event journal as the single seam. Every state store is a
projection of it; the only mutation path is a command; every automated decision carries its
propensity. The v1 tapes — two clocks, watch windows, run_ids, heartbeats, partial-tail
tolerance, censoring-as-data — are the primitive ancestor; in v2 their disciplines are the
log's **type system**, not conventions recited in prompts.

**Four first-class objects the v1 architecture had no home for**, which are the actual
product: **EXPECTATION** (the operator's recorded belief, scored at resolution, compiled to
structure), **PLAYBOOK** (a typed, versioned, simulatable program over commands),
**TOLL** (fee streams as income objects with decay and coverage), **MODEL** (fitted models
with residual streams and health monitors — "exit when the model stops predicting" as a
platform primitive, PROGRAM.md §9 rung 0).

**Operator-coupled by design.** The measured record says the operator's taste is the desk's
best signal (discretionary exits +1.96% vs routing, t=3.31, n=221; operator-typed basis
+18.1% vs fabricated −29.1%) and its automated layer, unsupervised, is its worst
(−7.47 SOL in one live window). JOSHI is built to *instrument the operator*, not replace
them: record the belief, compile it to structure, score it honestly, and keep every
irreversible act behind a ceremony.

What JOSHI is **not**: a rewrite of the money path (§9.1), a general trading platform, a
cloud service, or a reason to stop the desk for a single day (§8).

---

## 1. Why a v2, and why it is not a rewrite

The v1 tree is ~20 agent-built Python packages with measured duplication — 22 JSONL writers,
23 partial-tail loops, 42 HTTP client sites, 12 DexScreener fetchers, ≥3 friction tables
(SUBSTRATE.md). That number is a symptom, not the disease. The disease is that v1's real
architecture — event tapes, projections, commands, gates — exists as *discipline* scattered
across packages, so every new lane re-derives it and some fraction re-derives it wrong. The
scars catalogue (§9.2) is exactly the set of places a convention failed where a type would
have held.

At the same time, **harden-don't-rewrite stands and is not in tension with this.** Two
independent reviews converged: none of v1's money-path defects were type errors, and
`shitcoims_sentinel/transaction.py` plus `shitcoims_lpexec/guard.py` are the best code in the
tree, with adversarial tests that encode a year of paranoia. So:

> **v2 is a new spine around ported organs.** The event log, the domain objects, the glass,
> and the playbook/expectation machinery are new. The money organs, the Lean kernel, the tape
> contracts, and the research harnesses transplant with their tests. Nothing that holds keys
> or touches chain state gets rewritten to satisfy an architecture diagram.

---

## 2. The two logs — what the state stores are, what the events are between them

The single most important structural decision. v1 conflated "what the market did" with "what
the desk did" (the intelligence store's inverted clocks, the sentinel's closed-loop
own-wallet contamination that manufactured p=0.00498). v2 separates them by type:

### 2.1 The TAPE — observations of the world

High-rate, external facts: launches, trades, reserve readings, board membership, callouts,
graduations. Owned by the Python collectors (`tapecraft`/`marketdata` per SUBSTRATE). JSONL
hot, parquet cold, terabyte-scale on `/tank`. An observation is **never** a desk fact: it has
no actor, no propensity, no lifecycle. Its disciplines (two clocks `t_event`/`t_ingest`,
watch windows, censoring flags, tri-state observations, amounts as strings) are already
landed in `shitcoims_tape/schema.py` and port as-is.

### 2.2 The JOURNAL — facts about the desk

Low-rate (operator-scale: tens to hundreds of events per hour), append-only, hash-chained,
megabyte-scale, kept forever. Every event is a typed record with a mandatory envelope
(§6). The journal contains exactly three kinds of fact:

1. **Decisions** — a command was proposed, validated, accepted, or **refused (refusals are
   data, with reasons — a refused arm is as informative as a fill)**. Automated decisions
   carry propensity (the paperdesk's `policy.py` pattern, promoted to the envelope).
2. **Transitions** — a domain object changed state: order planned, expectation recorded,
   playbook armed, model died, toll claimed.
3. **Reconciliations** — a chain observation about *our* wallets, lifted into a desk fact by
   a reconciler (fills attributed, basis established from chain, divergence classified).
   This is the only bridge from tape to journal, and it is one-directional.

### 2.3 Projections — the state stores

Every state store is a **named, versioned, pure fold over the journal** (plus read-only tape
context): Positions, Book, TollLedger, ExpectationScorecard, PlaybookRegistry, ModelHealth,
OrderBook (ours, not the market's). Rebuild-from-genesis is a supported operation *and a CI
test* — a projection that cannot replay is a bug. Projections carry health (last seq applied,
lag); the glass renders projection lag, never hides it.

### 2.4 Commands — the only mutation path

`Proposed → Validated → Accepted | Refused`. Validation runs against projections + the
envelope (Lean-checked exposure/loss-budget arithmetic, ported from `kernel/Joshi/
Envelope.lean` with its absorbing-breaker theorem). Nothing writes the journal except the
command pipeline and the reconcilers. The glass proposes commands; playbooks propose
commands; the expectation compiler proposes commands. **Proposal is never execution** —
execution requires the order lifecycle and its gates (§4).

Journal heartbeats make absence interpretable, the watch-window discipline promoted to the
desk: inside a heartbeat-covered window, no event means nothing happened; outside one, no
event means *no information*. "No data" is never rendered as zero (v1 `Measured<T>` /
`figure.tsx`, promoted to the platform contract).

---

## 3. The domain model — spine

Full type sketches in `design/domain-model.md`. Each object: identity, lifecycle, events,
invariants.

| object | identity | lifecycle | the invariant that is the point |
|---|---|---|---|
| **Event** | ulid | append-only | envelope mandatory; two clocks; amounts as strings; propensity on automated decisions |
| **Command** | ulid | proposed→validated→accepted/refused | only mutation path; refusals recorded with reasons |
| **Projection** | name@version | rebuildable fold | never a source of truth; replay-from-genesis is a test |
| **Order** | ulid | intent→plan→simulated→armed→sent→landed/failed/expired/**unresolved** | armed only from a 3-gate proof; signature recorded before submit; unresolved never auto-resumed; every landing reconciled and divergence classified {bug, modeling error, parameter gap, irreducible} |
| **Expectation** | ulid | recorded→compiled→active→resolved/withdrawn/censored | utterance kept verbatim; typed claim; evidence links at creation; **scored** at horizon (Brier, pessimistic marking, censoring recorded not dropped) |
| **Hunch** | ulid | recorded→positioned→zapped/expired | the minute-horizon species of Expectation (claim: Wiggle \| Activity) carrying an immediate PositionProposal; scored by **position outcome**, not Brier-on-drift; the zap records full tape-state at exit — (state, exit) pairs are the reactive-exit training set |
| **Wallet** | address | — | role, key custody, **per-wallet allowlists**; five wallets, at least two live keys; the signer keeps one spool per key; the reconciler tracks all five |
| **Playbook** | id@semver | draft→checked→simulated→shadow→armed→retired | a typed term over commands with gates, authored in the Lean DSL; trial count from grammar cardinality; every activation propensity-logged; population-scoped |
| **Position/Lot** | mint+lot | open→scaling→closed | basis is a provenance type: FromChainFills \| OperatorAttested \| Unknown — Unknown ⇒ rug-only; **population tag {quality, scalp} mandatory**, playbooks scoped to one |
| **Book** | singleton | — | cluster-level exposure caps (capacitors leak); daily loss budget with absorbing breaker |
| **Toll** | stream id | discovered→metered→decaying→dead | claims observed from chain; run-rate vs obligations as a coverage trigger; obligations reference TollStreams and structurally *cannot* reference Book |
| **Model** | id | fitted→live→degraded→dead | residual stream + e-CUSUM health; MODEL_DIED is an event playbook gates consume |
| **Attestation** | ulid | — | operator-supplied labels (addresses, basis, entities) with confidence; **measured and attested never summed** |

Three of these deserve their design argument here; the rest are in the type sketches.

### 3.1 EXPECTATION — belief as an object, and compilation to structure

The operator says *"idk i think this is gonna keep goin down"* about nosis, semivisually, on
a chart. That is currently vapor. In v2 it becomes:

```
Expectation {
  scope:      Mint(nosis)
  claim:      Drift(Down)              -- from a small typed vocabulary, §domain-model
  horizon:    3d                       -- picked on the chart gesture; defaults per scope
  confidence: 0.65                     -- declared at record time; what Brier scores
  utterance:  "idk i think this is gonna keep goin down"   -- verbatim, always kept
  evidence:   [chart window ref, hovered tape rows, open RESULT_* docs]
}
```

**And expectations COMPILE.** A compiler (pure function, `Expectation × DeskView →
[CommandProposal]`) turns the belief into reviewable structure. For the nosis example:

1. **LP shape constraint**: pools containing nosis get an *ask-only conversion* profile —
   bins only above spot on the nosis side, so the book converts nosis into the other asset
   on strength and never accumulates more on the way down; a rebalance proposal to pull
   existing bid-side bins ships in the same diff.
2. **Playbook gating**: any armed playbook whose action set includes buys scoped to nosis is
   suspended while the expectation is active (the two-populations discipline needs this hook
   anyway).
3. **A falsifier alert**: if nosis rises through the claim's invalidation level, the glass
   prompts re-evaluation *before* horizon — an expectation is a position in belief-space and
   gets a stop.
4. **A scoring hook**: at horizon, the claim is scored against the tape (executable-exit
   valuation, never last-trade closes — the bid-ask-bounce scar), and the score lands on the
   operator's calibration scorecard, split by scope and horizon, n beside every rate.

Compilation output is a **diff the operator approves** — nothing an expectation compiles to
arms anything by itself. This is the platform's answer to "the operator's taste is the
best-measured signal": measure the taste, then let it parameterize the machine through a
typed, audited channel instead of through vibes at 2am.

**The hunch is the minute-scale species of the same object, and it is already live in v1.**
A one-click `[wiggle]`/`[down]`/`[watch]` on a coin card is an
`Expectation { claim: Wiggle | Activity, horizon: minutes }` that additionally carries an
immediate `PositionProposal` — paper by default, live only inside an armed scalp playbook's
pre-authorized budget (§4, ceremony placement). Hunches are scored by the **position
outcome**, not Brier-on-drift, and land on their own scorecard section (the two scoring
regimes are never summed). The **zap** — one-keystroke exit on every operator position —
records the full tape-state at the moment of exit; the accumulated (state, exit) pairs are
the training set for the reactive-exit-policy search. The v1 live build delivering this loop
is a port candidate, not a prototype (§8 organ table).

### 3.2 PLAYBOOK — the operator's program-synthesis background, given a substrate

A playbook is a typed program over commands: gates (preconditions over `View t` — the
causally-restricted history type, so lookahead is unwritable), a trigger, an action template,
a sizing rule, an exit rule, and a **population scope**. Examples the measured record already
wrote: the ghost-town wiggle scalp (reactive exit with a 5-minute clock **backstop** — the
clock is not the policy, see §3.3; the measured record behind the backstop: every hold past
5 min went 1/20, −$61), the unlock ladder (~14 daily clips at random minutes: 10.9% dispersion vs 46.8% for
one clip; whole-tranche tilt when spot is within 2.71% above a fee rung), the model-death
exit (rung 0).

Per the house rule, **playbook terms are authored in the Lean DSL** — `kernel/Joshi/Dsl.lean`
is the ancestor, extended from predicates to policy terms. What Lean buys, concretely:
no-lookahead by construction; envelope compatibility inherited from the existing theorem
(exposure bounded over *every* action sequence, i.e. every playbook, proved once); and the
trial count for deflated-Sharpe as grammar arithmetic rather than a guess — which is what
makes the playbook *searchable* later (MAP-Elites over terms, Phase 2) without the search
lying about multiplicity. Execution follows the proven v1 pattern: the checked artifact is
the oracle (`joshi-oracle`), a fast path is held to parity by adversarial tests, and parity
skipping is a gate failure.

Analyzability is the requirement that shapes everything: every activation logs propensity;
per-playbook attribution decomposes realized PnL into entry selection / exit timing /
interaction (PROGRAM.md §4.3 — reported, never allocated); a playbook page on the glass shows
its simulation record, its shadow record, and its live record as three columns that are never
summed.

### 3.3 MODEL — §9's ladder as a platform primitive

A fitted model is an object, not a script: class, params, fit window, and a **residual
stream** written to the journal as it predicts. An e-CUSUM monitor (validated against planted
shifts before it is trusted — both-controls-always) turns the residual stream into health:
`fitted → live → degraded → dead`. `MODEL_DIED` is an event; positions and playbooks
subscribe to it. This is the operator's sentence — *"exit once the model is no longer
predictive"* — made mechanical, and it subsumes the deterioration stack and the "it'll come
back" safety rail in one construct. One correction sharpens it: the operator's real exits
are **reactive** — *"hold duration was never my policy"* — and the 5-minute wiggle clock was
an *outcome miscast as a rule*. So the reactive exit **is** the model-health exit: the
zap-recorded (state, exit) pairs are what the rung-0 exit policy is fitted to, and the clock
survives only as a backstop gate that fires when the fitted policy has nothing to say.

---

## 4. The money boundary — v1's proven patterns as types

The boundary is sacred and **structural**. Every one of these is a v1 pattern that already
paid for itself; v2's job is to make each one a type, so an agent (or a tired operator)
cannot drift past it.

1. **Three-gate arming, as a proof object.** v1: `execution.enabled: true` + `--live` +
   mode-0600 arm file bound to the current pubkey. v2: `ArmedPlan` is constructible only
   from a `GateProof` that the signer client alone can mint, and the signer re-verifies all
   three gates itself — it never trusts the domain core's word. The dashboard-prefill scar
   taught the pattern: **make the wrong state unrepresentable in the type that crosses the
   boundary** (basis was removed from the draft type; reintroducing it is a compile error).
2. **Builder-level instruction allowlists.** lpexec cannot construct a swap — not "doesn't,"
   *cannot*: the discriminator isn't in the data. `transaction.py` treats Jupiter's output as
   hostile bytes. Both organs port verbatim into `joshi-signer` (§7) with their tests. The
   allowlists remain **data**, reviewed as code, and are **per-wallet**: the LP key's
   allowlist carries no swap discriminator, the trading key's no DLMM instructions — a key
   can only do its role's job. Adding a program, pool, or destination is a commit, never a
   runtime action, never a glass affordance.
3. **No broadcast path by default.** The domain core has no RPC send capability at all —
   `joshid` can plan and simulate but the only process that can submit is the signer daemon,
   which holds the only keys (one spool per key, §7) and lives on the operator's box. A
   compromised or merely buggy domain core can propose garbage forever and move nothing.
4. **Caps as arithmetic the envelope proves.** Per-trade size as both bankroll fraction and
   pool-impact cap (ρ = B/Y ≤ θ); cluster-level aggregate exposure; per-day loss budget with
   the absorbing breaker (once tripped, `run` is the identity for any learner — already
   proved in `Envelope.lean`). These stay in Lean; C# and Python call the oracle.
5. **Rent priced into every plan.** Position rent, binArray pioneer rent, priority fee at
   *measured* levels (21–53k lamports, not the hardcoded 500k that 4×-oversized a whole
   shadow run), computed `minOut` from live reserves. A Plan that cannot show its friction
   line items does not validate — friction constants come from one versioned artifact (§10).
6. **Destination hygiene.** A live address-poisoning campaign targets this operator. No
   transfer destination is ever accepted from transaction history or free text; destinations
   come only from the attested address book. The glass renders history addresses
   non-copyable (design/glass.md).

**Ceremony placement (proposed-normative, pending the operator's explicit confirmation).**
Per-order ceremony — the typed size confirmation — is right for the **Quality** population
and impossible for **Scalp**, where the click must *be* the entry or the trade does not
exist. Resolution: **the ceremony moves to playbook-arm time for Scalp.** The scalp playbook
is armed once, with budget and caps, through the full three-gate ceremony; thereafter each
click spends pre-authorized budget inside it, and the three gates remain *structurally* in
force at the process level — what relocates is the human ceremony, not the gates. Disarm and
zap are one keystroke, always, for both populations: **exits never have ceremony.** The
operator has signaled the direction (*"hold duration was never my policy; my exits are
reactive"*) but has not confirmed this placement; until they do, it is a proposal, marked.

---

## 5. The language cut

Five languages, each with one job, talking through data. The argument, not just the verdict:

| layer | language | why |
|---|---|---|
| kernel: fills, accounting, envelope, DSL/playbook terms | **Lean** | already built, zero sorries, load-bearing via oracle; refinement is a machine-checked theorem over the emitted object; the tripwire applies |
| domain core `joshid`: journal, projections, commands, playbook runtime, expectation compiler, model monitors | **C# / .NET (NativeAOT)** | argued below |
| glass | **TypeScript** (kept) | argued below |
| research | **Python** (engines per SUBSTRATE) | unchanged; DuckDB/polars/lifelines; studies stay here forever |
| signer organs; later: replay fast path, ingest | **Python (ported organs)**, **Rust behind criteria** | argued below |

### 5.1 The C# endorsement — what .NET's tooling actually buys here

The operator proposed modern C# for the architecture. **Endorsed, for the domain core
specifically**, on grounds concrete enough to defend:

- **The workload is a state-machine zoo, and that is C#'s best register.** Orders,
  expectations, playbooks, models — closed sums with lifecycles. `sealed` hierarchies +
  exhaustive `switch` expressions + warnings-as-errors give DU-shaped modeling;
  `readonly record struct Lamports(ulong)` gives the NewType discipline (raw-base-units vs
  UI-amount vs lamports vs SOL — a *live* v1 hazard) at zero runtime cost. Honesty note:
  C# DUs are pattern-idiom, not compiler-guaranteed exhaustiveness like Rust or F#; the
  mitigation is an analyzer that forbids `_ =>` over domain sums. If that ever chafes hard,
  F# on the same runtime is the escape hatch, interoperating with everything else here.
- **Source generators + analyzers are the drift-resistance tool this project keeps paying
  for in prompt recitations.** The whole scars catalogue is "a convention failed where a
  type would have held." Roslyn lets house rules become build errors: an event type with no
  schema-registry entry does not compile; a `float` in a money type does not compile;
  constructing `SentOrder` outside the signer client namespace does not compile;
  serializers are *generated from the schema registry*, so a malformed event is a
  deserialization failure, never a silent null. This is the closest mainstream ecosystem to
  "custom tripwires as compiler errors," and it is the actual content of "architecture
  tooling" — not diagrams, enforcement.
- **The runtime fits the topology.** `System.Threading.Channels` is the in-process event bus
  (typed, backpressured, no broker); Rx projections feed the glass as live queries; NativeAOT
  produces single-file, fast-start, low-RSS daemons for both persvati (Linux) and the Mac —
  which matters on a co-tenant box where memory is what kills you.
- **Operator bandwidth is a named risk (§9.4), and this is the mitigation.** The operator
  reads and writes C# fluently. A language the operator can audit at 1am is worth more than
  any property of a language they'd be learning while tired. The 2026-08-12 loss was not a
  type error; it was a review that didn't happen. Optimize for review happening.

What C# does **not** get: the signer, the kernel's arithmetic, or the constraint logic. The
domain core proposes; it cannot construct a transaction, and the envelope math it enforces is
Lean's, reached through the oracle.

### 5.2 The dissents

**Full-Rust: no.** The strongest argument for Rust — the borrow checker and real ADTs — is
answered by the repo's own post-mortem: *none of the defects found are type errors* (the
double-submit was protocol ordering; the basis fabrication was provenance; the config race
was lock scope). Rust's price here is real: it discards two crown-jewel Python organs with
adversarial test suites, re-earning their bugs; it has the weakest GUI story of the options;
and it puts the whole spine in the operator's third-best language. Rust is *admitted* where
it is genuinely native, behind measured criteria: the replay fast path (already sanctioned by
PROGRAM.md §2 — differentially tested against the Lean oracle over millions of random tapes,
and described as engineering discipline, never as verification), and the ingest daemon **iff**
a firehose subscription shows measured drop under the Python collectors (record the drop rate
first; the current collectors just landed a 617k-line panel with coverage 1.00000, so the
burden of proof is on the rewrite). Rust never hand-writes constraints — the tripwire is
verbatim in every lane prompt that touches it.

**Avalonia glass: not now, with a door left open.** The operator's lean toward a native C#
glass is understood — one toolchain, no web stack. Dissent, with reasons: (1) the TS glass
*exists* and embodies the promoted principles in tested code — `Measured<T>`/`figure.tsx` is
"the only sanctioned way to put a number on screen," and `rendered-html.test.mjs` literally
pins the fabricated-basis regression; a rewrite re-earns those. (2) Charting and
dense-information UI is where the web ecosystem is a decade ahead of LiveCharts/ScottPlot,
and the glass is the surface we will iterate on most — iteration speed is the binding
resource there. (3) The glass sits *behind* the seam: it is a projection consumer speaking
schema-generated types over a local socket. That makes this decision **reversible** — the
cheapest option now is correct precisely because switching later costs a UI, not an
architecture. The compromise: the glass ships browser-first against `joshid` (zero new
toolchain), gets a thin desktop shell only when window management earns it, and Avalonia is
re-evaluated if the glass ever needs native canvas latency or global hotkeys the shell can't
give. **Tauri: no** as a core (a Rust core buys nothing when the core is C#), acceptable
later as a dumb shell.

**Keep-TS-everything (grow the v1 dashboard): no.** The dashboard is a *view server* welded
to the sentinel's process and state files; it has no journal, no command pipeline, no place
for expectations or playbooks to live. Extending it is how we got 20 packages.

### 5.3 The event-log schema — language-neutral, and which neutral

**JSONL with a checked schema registry for hot; parquet for cold. Not protobuf, not
flatbuffers.** Reasoning:

- The forensic record decides it. Every audit, every reconciliation, every 2am
  investigation in this repo's history ran on greppable text plus DuckDB. A binary hot
  format would have made HANDOFF.md's entire detour slower and some of it impossible.
  Throughput does not argue back: the journal is operator-scale, and the tape's proven JSONL
  path just swallowed a 306k-fill panel without strain; the 106M-row corpus work already
  lives in parquet where columnar wins.
- The f64 cliff is handled where v1 handles it: **amounts are decimal strings on the wire**,
  integers (lamports, raw base units) in every typed reader. Protobuf's int64 would fix that
  one hazard at the cost of the greppability that catches the other nine.
- **The registry is the contract**: versioned schemas (`order.planned@3`) in `schema/`,
  code-generated into C# records (source generator), TS types, Python TypedDicts, and Lean
  structures for the kernel-relevant subset. One definition, four languages, no mirrors —
  the ground-truth-first lesson applied to ourselves.
- The journal adds what the tape doesn't need: per-stream monotone `seq`, `prev_hash` chain
  (cheap at this rate, makes tampering and truncation evident), single-writer-per-stream.
  Envelope spec in §6 of `design/domain-model.md`.

---

## 6. Event envelope (normative sketch)

Every journal event:

```
event_id      ulid            unique, sortable
stream        string          "journal" | "signer/<key>" (one writer per stream; one spool per key)
seq           u64             monotone per stream
schema        string          "expectation.recorded@1"
t_event       rfc3339         when it happened (chain/world clock) — never fabricated
t_recorded    rfc3339         when we wrote it — the two clocks are never conflated
run_id        string          process incarnation
actor         typed           Operator | Daemon(name@ver) | Playbook(id@semver)
causation_id  ulid?           the command/event that caused this
correlation_id ulid           the saga (order, expectation, …) this belongs to
propensity    f64?            MANDATORY on automated decisions; absent means "not a decision"
prev_hash     hex             chain per stream
body          object          schema-validated; amounts as strings
```

Tri-state discipline everywhere: a boolean the producer did not observe is `null`, never
`false` — a fabricated negative is the same disease as a quote-stamped basis.

---

## 7. Process topology

```
persvati (24c/83G, never sleeps)          Mac (operator present)             hbox (co-tenant)
┌─────────────────────────────┐     ┌──────────────────────────────┐   ┌─────────────────────┐
│ tapesmith  (Py collectors)  │     │ glass (TS, browser/shell)    │   │ corpus replica      │
│   boards/firehose/cluster/  │     │   ▲ projections (WS/SSE)     │   │ replay + search     │
│   intel → TAPE (JSONL)      │     │   ▼ command proposals        │   │  (Py + Lean oracle, │
│ joshid  (C#, NativeAOT)     │◄────┤                              │   │   Rust fast path    │
│   JOURNAL authority         │ tls │ joshi-signer (ported organs) │   │   later)            │
│   projections, playbooks,   │────►│   THE ONLY KEY-HOLDING PROC  │   │ swarm-build, small  │
│   expectation compiler,     │     │   N keys, 1 spool per key    │   │ waves, spare codex  │
│   model monitors, alerts,   │     │   per-wallet allowlists      │   └─────────────────────┘
│   reconciler (5 wallets)    │     │   re-verifies gates itself   │
│ watchdog (exists, extended) │     │   Jito/MEV-protected submit  │
│ Lean oracle (joshi-oracle)  │     └──────────────────────────────┘
└─────────────────────────────┘
        TAPE + JOURNAL rsync → hbox & Mac (followers, read-only)
```

Placement arguments:

- **joshid lives on persvati** because projections, model monitors, expectation horizons,
  and alerting must survive a closed laptop lid. persvati never sleeps; it is already the
  collector/watchdog home per SUBSTRATE.
- **Keys never leave the Mac, so execution requires the operator's box awake — by design,
  not limitation.** This desk is operator-coupled; there is no unattended broadcast path
  *anywhere in the topology*, which upgrades v1's "no-broadcast-by-default" from a flag to a
  physical arrangement. The signer daemon is the ported `transaction.py` + lpexec
  guard/signer organs behind one narrow socket, re-validating everything (it treats joshid
  exactly as v1's guard treats the Meteora sidecar: as hostile bytes). It is **multi-key**:
  the desk runs five wallets with different roles and at least two live keys
  (`~/.shitcoims-wallet` trading, `~/.thafunds-wallet` LP) — each key gets its own spool
  stream and its own per-wallet allowlist (§4 item 2), merged into the journal by the
  **reconciler** (design/reconciler.md), which tracks all five wallets and is the only
  tape→journal bridge. One spool per key means a signed-send survives any link drop —
  reconciliation-first, because ambiguous submission was the double-submit scar.
- **Moving the signer to persvati is a named future decision** with its own review, required
  only if truly-unattended execution (e.g. LP rebalance while asleep) ever earns it. It is
  not in scope and the glass offers no path to it.
- **hbox stays batch**: replay, search, corpus sweeps, Lean builds — under `swarm-build`,
  small waves, sparing codex's datacake procs.
- **The watchdog watches everything and stays report-only for dead-by-choice components.**
  The sentinel is dead by the operator's own ban; the glass renders it dead and offers no
  restart affordance (design/glass.md §manual).

---

## 8. Migration path — the desk never stops

Strangler-fig, five phases. Rules that bind every phase: never stop a running collector to
port it; every replacement runs **in parallel with a diff** before cutover; every cutover has
an end date after which the old organ is deleted (two books left running is how the
basis-fabrication class of bug returns); pathspec commits while lanes are live.

**M0 — the journal, additive (no risk, immediate value).**
Stand up `joshid` + the schema registry. Adapters tail v1's existing state files read-only
(sentinel event journal, paperdesk ledger, lpexec ledger, wallet reconciliation from the
tape) and lift them into journal events. Nothing depends on the journal yet.
*Exit criterion:* journal replay reproduces v1 state snapshots (positions, LP book, toll
claims) with zero divergence over 7 days.

**M1 — the pump-parity surfaces + the gesture layer (read-first).**
Per the product definition (§0): the parity surfaces are the spine of this phase — the
trenches/new-coins feed, boards/trending, the coin page, the callout stream, and the
creator/fee view, read-only, from our tapes with the instrument disciplines. The glass
connects to joshid projections; v1's dashboard keeps running; views retire one at a time
only when the projection matches the old view in parallel-run. The **hunch loop and zap**
are absorbed here from the live v1 build (below), and **expectations ship here** — purely
additive, no money path, and every week not recording the operator's beliefs is data lost
forever (the same argument that made the tape recorder do-first).
*Exit criterion:* the operator's daily pump.fun browsing happens in the glass for a week;
the v1 dashboard goes unopened for the same week without being missed.

> **Shipped early, in v1 form, 2026-08-15 — because "every week not recording the operator's
> beliefs is data lost forever" argued for its own schedule.** `state/hunches.jsonl` is an
> append-only, fsynced tape of Expectation-shaped rows (scope, claim, horizon, confidence,
> utterance kept VERBATIM, evidence, two clocks where the event clock is the gesture), with
> `hunch.retraction.v1` rows in place of edits. Capture is a click on a coin card in the v1
> glass (`app/views/explorer.tsx` → `shitcoims_paperdesk.glass`, loopback :8790); a
> `wiggle` claim opens a real paper position in the desk's fifth book under the wiggle
> book's execution, and `down`/`up`/`watch` compile to a scored claim with a falsifier
> level and a Brier at horizon. What is NOT here is the part that needs the platform: the
> compiler that turns a belief into a reviewable diff of command proposals, and the
> approval step. When joshid exists, this tape is the import source — the row shape is the
> `Expectation` record's, deliberately, so the migration is a read rather than a
> reconstruction.

**M2 — commands orchestrate the v1 organs.**
Order tickets and LP actions initiated from the glass flow through the command pipeline,
which **shells out to the existing v1 executors** (lpexec CLI, sentinel's exit machinery for
manual disposes). The money code does not change; it gains intent→plan→simulate→arm→send
lifecycle, refusal records, and reconciliation rows around it.
*Exit criterion:* every chain-touching act the operator performs appears in the journal with
a full lifecycle, including the refusals.

**M3 — signer extraction.**
`transaction.py` + lpexec guard/signer/allowlists move into `joshi-signer` **with their test
suites**, plus the scar regressions re-pinned in the new home. Parallel-run: M2's shell-out
path and the signer socket path both live, diffed on plans (never double-sent — the diff is
on the plan/simulation, the send goes through exactly one).
*Exit criterion:* N=50 consecutive real operations with zero plan divergence; old path
deleted with its end date honored.

**M4 — playbooks and models.**
Paperdesk policies and the probe become Lean DSL terms; simulate on the replay harness
(exact kernel fills, purged walk-forward, grammar-counted trials); shadow via the paperdesk
pattern (propensity-logged, no money); per-playbook arming with size caps only after shadow
clears its own pre-registered bar. Model monitors (rung 0) attach first to the reactive-exit
policy — fitted to the zap-recorded (state, exit) pairs, with the 5-minute clock as its
backstop, per §3.3 — and to OU on cluster ratios: the easy models, per the operator's
tooling principle.
*Exit criterion:* is per-playbook, forever — a playbook is armed only while its shadow and
live attribution agree within stated bounds.

**Organ disposition** (the donor map):

| v1 organ | disposition | criterion for the old one dying |
|---|---|---|
| `kernel/` (Lean: fills, basis, envelope, DSL, oracle) | **port as-is**, gains `Playbook.lean` | n/a — it is the foundation |
| `shitcoims_tape` schema + recorder | **port** into tapecraft (SUBSTRATE order) | collectors migrated one at a time, suite green each step |
| `shitcoims_sentinel/transaction.py` | **port verbatim** → joshi-signer | M3 criterion |
| `shitcoims_lpexec` guard/allowlist/signer/planner | **port verbatim** → joshi-signer | M3 criterion |
| `scripts/watchdog.py` | **port**, extended to joshid/journal freshness | immediately, it's additive |
| `shitcoims_replay`, `ope.py`, `trials.py`, `split.py` | **stay Python**, research side | never — they are the harness |
| `app/` components (`figure`, `instrument`, `Measured<T>`) | **port** as the glass's core | M1 per-view criterion |
| hunch loop (`app/views/explorer.tsx`, `shitcoims_paperdesk.glass`, `state/hunches.jsonl`) | **port** as M1's seed; the hunches tape is the import source (row shape is the `Expectation` record's, deliberately) | joshid's expectation store replays the tape exactly, then the v1 endpoint dies |
| sentinel `engine.py` (policy semantics) | **reference-only** | M2+M3 subsume manual paths; automated selling stays dead by choice until the operator lifts the ban — v2 does not resurrect it |
| paperdesk (books/policy/toll) | **reference-only** (its propensity pattern is already promoted into the envelope) | M4 |
| dashboard `server.py`, per-view API | **dies** | M1 per-view |
| 42 HTTP clients / 22 JSONL writers / ≥3 friction tables | **die** into marketdata / tapecraft / the friction artifact | SUBSTRATE's own metric: counts go to ~1 |
| `intel.py` + scout | **keep running**; adapters absorbed by marketdata; scout stays the remote read-only console | SUBSTRATE order |
| marketfabric | **never enters**; `crates/quantmath` liftable with re-derivation, per standing memory | n/a |

---

## 9. RISKS — honest, in the operator's order of severity

### 9.1 The rewrite trap

**v1's earned paranoia lives in comments and tests, and a rewrite silently discards it.**
The mitigation is structural: organs port *with their tests*; scars get named regression
pins in the new home before the old one dies; and the adversarial-audit cadence (SWARM.md)
applies to v2's own claims — the first three waves of v1 ran the build gate every time and
the adversarial audit zero times, and that is exactly the failure v2's green dashboards will
invite again.

### 9.2 The scars that must survive transplantation

Each scar, its mechanism, and where it lives in v2 — if a scar has no row here when v2
ships, that is a defect in v2:

| # | scar (measured cost) | v1 mechanism | v2 embodiment |
|---|---|---|---|
| 1 | **Fabricated cost basis** (−7.47 SOL; appeared **three times**: engine auto-protect, `policies.from_quote`, dashboard prefill) | basis stamped from current exit quote | `Basis` provenance type with *no constructor from a quote*; `Unknown ⇒ rug-only`; draft types carry no basis field (compile error to reintroduce) |
| 2 | **Two-clocks violations** (intelligence store inverted between kinds; backfill ran ingest-time backwards, Spearman −0.77; recorder's 0.5s graduation median) | conventions on field names | envelope's `t_event`/`t_recorded` mandatory and named so semantics can't invert; mixed-clock joins a type error; Marino's 4.4-min-median-with-tail as the standing instrument check |
| 3 | **Address fabrication / poisoning** (live campaign, leading+trailing vanity matches) | copy-from-history | destinations only from the attested address book; glass renders history addresses non-copyable; signer refuses unlisted destinations |
| 4 | **The −151% partial row** (and the censored-96% drop, the 24× attempt overcount) | hand-rolled loops folding partials/censoring wrong | partial-tail tolerance and censoring in tapecraft/cohortkit imports; journal heartbeats make absence typed; "no study row-loops a corpus" tripwire |
| 5 | **Double-submit** (over-sell with scale-outs live) | signature recorded only on confirm; retry built a fresh order | signature recorded locally *before* submit; `unresolved` is terminal-pending, never auto-resumed; reconciler is the only resolver |
| 6 | **Closed-loop contamination** (own sentinel wallet in the treatment set: p=0.00498 from nothing; structural zeros flooring p-values) | studies read undifferentiated tapes | journal/tape separation by type; own-wallet rows enter studies only through the reconciler with `actor` stamped |
| 7 | **Fabricated denominators** (OPE without propensities; the mechanically-floored placebo) | optional propensity | propensity mandatory in the envelope on automated decisions; OPE's refusal behavior kept |
| 8 | **Hardcoded constants wearing fact costumes** (SOL=$150 in our own tree; 500k-lamport priority 4×-oversizing a shadow run; 20-bps incident) | constants scattered per package | one versioned friction artifact stamped into every Plan; hardcode-audit `--check` stays a CI gate in v2 |
| 9 | **Vendor ceilings** (32-address simulation ceiling: past it *every* live sell fails) | cap in one file, limit in another | vendor limits live in the schema registry beside the client that owns them; plans validate against them |
| 10 | **Green ≠ verified** (25/60 mutations survived; the money printer replay; `P → P` theorems) | build gate mistaken for audit | scheduled adversarial audits; mutation runs clear `__pycache__`; parity-test skips are gate failures |
| 11 | **Reconciler misclassification** (every error in a night of forensics was a labelling error; two this week: the 757-SOL fee label, the fabricated addresses) | ad-hoc classification folded residuals into the nearest bucket | the reconciler is its own designed, audited component (design/reconciler.md): deterministic classification battery, `Unclassified` a rendered state never a retry loop, planted-world controls, scheduled adversarial audit |

### 9.3 Scope creep — the no-list

v2 does **not** include: a Rust rewrite of anything currently working; Avalonia; moving keys
off the Mac or any unattended broadcast path; resurrecting the sentinel's automated selling
(dead by choice, operator's ban); automated launches; multi-operator/auth/cloud anything;
venue abstraction beyond pump.fun/PumpSwap/Meteora DLMM/Jupiter; an event-sourcing framework
or broker (files and one process suffice at operator scale); protobuf; marketfabric code;
replacing research Python. Each is either a named later-decision with a criterion, or dead.

### 9.4 Operator bandwidth

One person, ~$4.1k/mo obligations, a $40k IRS debt, and **the fee stream is the business —
trading is a research program funded by it**. So: every phase must ship something the
operator uses that same week (M0's journal feeds M1's glass; M1's expectations are useful the
day they land); no phase is allowed to block the desk or the studies; and v2 pauses without
ceremony if the toll coverage trigger fires — the platform exists to serve the desk, and a
platform that competes with the desk for the operator's attention is a cost center wearing an
asset's costume. The v1.5 SUBSTRATE wave (§10) is deliberately sequenced first because it
pays for itself inside the existing workload.

### 9.5 Denomination risk

**Obligations are USD; the book and the income are SOL.** Rent is dollars on the 1st, the AI
bill is dollars on the 28th, and the toll streams pay in SOL whose dollar value moved this
desk's own accounting by double-digit percents inside single weeks. So `Obligation` is
denominated in fiat in the domain model, `CoverageReading` carries the SOL/USD conversion
exposure explicitly (days-covered is a function of a rate that moves, and the glass shows
the sensitivity, not just the point estimate), and the default mitigation is the boring one:
**a scheduled USDC conversion sized to ~30 days of obligations**, executed as ordinary
orders through the pipeline. Everything above the buffer stays SOL — the book is capital and
is never dismantled for the calendar; the buffer is what makes that rule survivable.

### 9.6 When v2 replaces each v1 organ — the general criterion

An organ is replaced only when **all four** hold: (1) the organ's own adversarial test suite
ports and is green in the new home; (2) parallel-run divergence is zero over the organ's
stated window (7 days state, 50 operations money); (3) every §9.2 scar touching the organ
has a named regression pin in the new home; (4) the operator has used the replacement for
its real job for a week without reaching for the old one. Then the old organ is **deleted on
its end date** — not archived in place, not left as a fallback — because two live
implementations of one truth is the exact substrate the fabrication class of bug grows in.

---

## 10. SUBSTRATE.md reconciliation (v1.5 vs v2)

SUBSTRATE is the v1.5 consolidation wave; v2 supersedes it *where they conflict*. The
explicit deltas:

1. **Proceeds unchanged, v2 depends on it:** `cohortkit` (research engines), `marketdata`
   (one client layer; the collectors' throat), the compute-residency plan, the tripwire
   ("no new JSONL writer / HTTP client / friction constant / hand-rolled statistic").
2. **`tapecraft` — scope narrowed, not changed:** it owns the **tape** (market
   observations). The **journal** is new, C#-owned, and *not* a tapecraft consumer — but it
   speaks the same wire disciplines, which now live in the schema registry rather than in
   any one package. One discipline, two logs, two owners.
3. **`friction` — superseded in form:** SUBSTRATE planned a Python package; v2 makes the
   constants a **versioned language-neutral data artifact** (checked into the repo, stamped
   into every Plan by version), with the Python package demoted to its reference reader and
   the C# planner reading the same file. The 500k-lamport and 20-bps incidents are the case
   law; the fix is one source of truth *across languages*, not one per language.
4. **"Contracts stay the seams; language per layer talking through data"** — adopted
   verbatim and extended: the schema registry with four-language codegen *is* that sentence,
   made enforceable.
5. **SUBSTRATE's untouchables** (Lean kernel + FFI oracle, tape schema, signer isolation,
   lpexec guard) are exactly v2's **ported organs** — the two documents agree on what is
   sacred, which is the strongest sign the plan is the same plan at two zoom levels.

---

## 11. Deliberately left out, and why

- **Sentinel resurrection** — dead by choice; v2 builds the instruments to earn the ban's
  lifting, and nothing else.
- **A DSL surface syntax for playbooks** — the terms are Lean; a pretty syntax is M4+ sugar
  and designing it now would be designing without the five playbooks that should shape it.
- **Entity/wallet-graph objects in the domain model** — signals #1/#2 remain research-side
  until an estimator survives its own nulls at real n; promoting them early would freeze a
  moving interface.
- **The network map view** (PROGRAM.md §8's dashboard) — deferred to the glass's second
  wave; it depends on cluster-tape projections that should be built as projections first.
- **Numbers for v2's own cost** — deliberately: the phases are sized so each pays inside a
  week, and any phase that can't is evidence the design is wrong, which we want to hear
  early.
