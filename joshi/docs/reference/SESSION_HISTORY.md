# Session-history synthesis

Status: provenance and steering record, recovered 2026-08-16 with ClusterVision (`cv`).

This document records what Ember was trying to build, how the work was repeatedly narrowed,
and which conclusions belong only to those narrower experiments. It is intentionally separate
from the architecture: a future design should be able to cite the steer it serves rather than
quietly replacing it.

## Corpus and coverage

The relevant ClusterVision inventory contains ten Claude top-level sessions rooted at
`~/dev/joshibot`, comprising 13,244 stored messages and 173 spawned subagents.
The large message counts include tool results, task notifications, compaction continuations,
and repeated fork context—not 13,244 independent human prompts.

| Claude session | Stored messages | Subagents | Main role in the history |
|---|---:|---:|---|
| `6afafeaf…` | 2,160 | 61 | execution, data sources, circuit/flow work, copy trading, bandit and LLM studies, safety audits |
| `59905ce5…` | 1,890 | 52 | broad strategy wave, Pump social/firehose, paper desk, crime/caller/wallet studies, LP executor, V2 draft |
| `906b2135…` | 1,527 | 39 | research-program foundations, literature, mint panel, tapes, graph and wallet methods, early executor work |
| `b2266099…` | 1,490 | 11 | LP/DLMM ground truth, mean reversion, survival controls, SVM parity |
| `1b11eb3f…` | 1,439 | 1 | continuation and audit-backlog repair |
| `bf8ff16b…` | 1,390 | 0 | continuation/fork material |
| `fbbcae9b…` | 1,356 | 0 | continuation/fork material |
| `70c9e82a…` | 1,198 | 9 | accounting side quest, corpus digests, handoff, hygiene, final Claude continuation |
| `755965fc…` | 793 | 0 | continuation/fork material |
| `24ca7550…` | 1 | 0 | empty/stub session |

`cv index --subagents` was run before synthesis. It indexed the subagent forests as searchable
provenance and event records. One dangling Grok history path under an unrelated `leanuweave`
workspace failed to parse; it is not part of this corpus. The many Grok sessions under
`joshibot/.cache/llm_filter/` are generated screening runs, not conversations with Ember and not
independent evidence about the strategy.

Coverage method:

1. Enumerate every top-level session and every subagent task/final return with `cv ls` and
   `cv show --subagents`.
2. Recover parent-session user steers, including interrupts, corrections, and post-compaction
   repetitions.
3. Use the event catalog and repository result files to connect task claims to what actually
   changed or ran.
4. Treat repeated agent branches and generated model screens as dependent artifacts.
5. Reconcile the history against the current code and study documents rather than accepting
   either a session summary or `HANDOFF.md` as authoritative.

The subagent forest covers these major families: Pump and X ingestion; board/callout/firehose
collection; wallet and entity resolution; copy-trading and caller-wallet studies; transaction
landing, priority fees, Jito/Jupiter and MEV; Pump/PumpSwap quoting; Meteora/DLMM math, LP history,
rebalancing and execution; paper desks, bandits, OPE and replay; crime, clustering and circuit
models; LLM selection; portfolio/accounting reconstruction; UI glass; formal envelope work;
literature surveys; adversarial audits; and the final V2 handoff. That breadth is real. The
problem was not lack of activity; it was loss of the composite object across the lanes.

## Steering trajectory

### 1. Protect and understand the actual wallet

The initial system grew from a real need to understand DREGG-derived income, current holdings,
LP positions, and manual trades, and to avoid accidental loss. Exact wallet accounting and a
safe exit path were therefore legitimate foundations.

The first major correction was that the stop-oriented sentinel was not Ember's management
policy. Ember repeatedly said, in substance:

- stop selling bags merely because they fall;
- prefer holding when the thesis remains live;
- a fixed five-minute horizon is absurd for coins that can take time to move;
- take profit when it is available, but do not confuse a safety backstop with judgment;
- manual graph watching changes exits.

Claude widened stops and built richer exit machinery, but the architecture continued to treat
an inventory position and its clock as the main behavioral unit. That retained the wrong center.

### 2. Find the fast, small-stake loop

Ember kept returning to an earlier, largely unbuilt idea: choose a coin using the information
surface, wait reactively for a small dip, enter quickly, and take a very small executable profit.
The value proposition was not one static predictor. It was the whole loop:

```text
market/social surface
  -> Ember notices and selects
  -> conditional microdip watch
  -> fast entry
  -> graph- and quote-aware management
  -> small realization, full exit, or changed disposition
```

Speed matters after the human decision. Breadth is an eventual scaling question: first discover
whether selected, armed episodes create a reproducible “crackle,” then test how selection quality,
capacity, and tail risk decay as more of the surface is covered.

Claude instead repeatedly instantiated small pieces as complete strategies: board-entry grids,
mechanical callout buys, a fixed wiggle book, bandit arms on available columns, fixed brackets,
and a static LLM glance. Those are valid component probes. They do not identify the loop above.

### 3. Preserve the possibility that a crackle becomes something else

Ember's strongest positive examples were not pure scalps. A coin could be entered for a crackle,
then look capable of sending; some profit could be realized while a remainder remained exposed.
RADON, EarthCoin, and CRASHIUS were named as current examples.

The steer contains several distinctions:

- partial realization is not necessarily thesis termination;
- a remainder can be deliberately promoted to a runner;
- “capital recovered” does not mean the remainder is economically free;
- a graph-driven full exit can be followed by continued attention and later re-entry;
- realized clips, avoided drawdowns, missed upside, and current remaining exposure all belong to
  one episode-level account.

No old study reconstructed this composite path prospectively. The hunch tape reported zero real
operator rows, and wallet transactions alone cannot recover flat-but-watching intent.

### 4. Treat social dynamics as state, not decoration

Ember was not asking for a generic sentiment score. The repeated examples concern changes in a
social ecology:

- an unofficial “fancoin” exists before a represented creator claims or participates;
- a person, project, or cultural event begins to attract a community;
- several duplicate coins compete to become canonical;
- callouts, replies, identities, media, fee routing, wallet behavior, and chart response evolve in
  different orders;
- scam/imitator launches and manipulation patterns can be exit information even when they are not
  entry signals;
- social adjacency—accounts one or two degrees from Ember's own network, especially around AI—can
  matter more than a population-level callout feature.

The desired object is a point-in-time transition history with uncertainty and competing outcomes.
It is not “claimed versus not claimed,” and it cannot backfill today's verified identity into an
earlier scene.

### 5. Build the complete Pump alternative before judging the operator

This steer recurred in several forms: if Ember still has to discover and understand coins in Pump,
then a separate logger or dashboard observes only the already-selected residue. The instrument has
to offer the same or better discovery, coin, chart, social, and community loop before it can claim
to capture selection.

“Pump-like” means behavioral parity, not pixel imitation:

- comparable feeds, ranking, cadence, identity and community texture;
- stable navigation from candidate to chart/social inspection to action;
- exact choice sets, rank, viewport and alternatives;
- faster operator-specific gestures, quotes, accounting, replay and annotations;
- explicit gaps where lawful or stable access cannot reproduce Pump.

Claude's later `design/glass.md` moved toward this requirement, but it embedded the narrow
`wiggle/down/up/watch` language and study verdicts directly in the product. The new glass must
preserve ordinary acts and allow meanings to evolve.

### 6. Learn the language before selecting the learner

Ember described roughly three to eight dispositions toward a coin and two to five crackle types,
without claiming those counts or names were settled. They also proposed chart drawing, visual or
numeric shape models, multimodal ensembles, realtime LLM analysis, program synthesis, and circuit
abduction.

The recurring instruction was temporal: build enough correct data and operator-facing structure
that useful learning problems eventually become expressible. Claude often reversed this order by
choosing a small feature set, fitting or testing a simple rule, and treating the result as evidence
about the intuition that had been projected away.

The formal-methods analogy was not “encode a five-button policy in Lean now.” It was closer to:

- infer a changing controller from partial, selected observations;
- identify missing sensors and indistinguishable latent mechanisms;
- preserve counterexamples and unknown predicates;
- synthesize compact advisory components only after the input language exists;
- keep learned policy separate from a formally constrained authority envelope.

### 7. Model LP control as inventory management

Ember repeatedly objected to LP work being reduced to “fees versus hold” or interpreted as a
reason to reject LPs. The operational questions were:

- which pools and pair structures are worth making markets in;
- how bin weights should express a nonconstant inventory-conversion policy;
- whether to add, remove, or reshape liquidity inside an existing position;
- when recentering truly requires a swap and when it merely changes the schedule;
- how much SOL to withdraw because another opportunity is better;
- whether weights could adapt to a learned volatility-to-bin distribution;
- how LP inventory complements spot exposure and treasury needs.

The old work measured real scars, including fees, adverse composition, range duty cycle and
friction. It did not supply the required control model or prove that LP inventory is foolish.

### 8. Wallet watching is discovery, not blind imitation

Ember curates followed accounts in Pump and proposed observing the wallets through which those
accounts actually trade, potentially before public callouts. Earlier caller/copy-trading studies
mostly began from researcher-selected influencers, observed post-call behavior, or asked whether
mechanical mirroring worked.

The corrected question is whether a time-varying, confidence-scored mapping from followed profile
to trading wallet can promote useful candidates into Ember's attention early enough to matter.
It must measure detection delay, executable price and capacity, wallet/entity ambiguity, later
callout time, and Ember's subsequent selection. It does not authorize automatic copying or
front-running.

### 9. V2 was a request to rethink, not port

Ember called the code disconnected, over-hand-rolled, and poorly engineered, while also wondering
whether V2 would merely repeat the same mistake at greater cost. They explicitly asked not to
fixate on the current ideas or language choices.

Claude's `JOSHI.md` did contain good organs—tape versus journal, event sourcing, reconciliation,
operator-native gestures, provenance, signer separation—but froze several premature conclusions:
“entry dead,” position/lot lifecycle, `quality/scalp`, expectation compilation, Lean playbooks,
C# domain core, and a specific milestone plan.

The current answer is neither “port the code” nor “throw everything away.” Start a clean semantic
repository, retain `joshibot` as compost, reuse commodity plumbing, and make old modules re-earn
admission through conformance and replay tests.

## What the old studies actually tested

The following table is the key antidote to both despair and wishful reinterpretation.

| Old study family | Legitimate finding | What it did not test |
|---|---|---|
| board entry / bandit grids | no robust edge found in the tested coarse fields and short window; censoring and fill sensitivity were severe | Ember's actual selection scene, chart reading, social state, or episode management |
| callout buying | mechanical direction-following was late/adverse in the measured cohort; disappearance handling changed conclusions | callouts as discovery, social transitions, operator selection, or pre-call wallet activity |
| LLM filter | one static card-level prompt on a selected cohort did not add reliable value | realtime threads, images, identity change, chart context, multimodal retrieval, or an evolving operator model |
| fixed wiggle/paper desks | certain fixed arms were fragile; a few hand-selected operator examples differed from mechanical breadth | a prospective natural gesture vocabulary or scale-decay curve |
| copy-trading/caller wallets | known-account mechanical following and some joins were weak or ambiguous | Ember's curated Pump follow graph as a candidate sensor |
| crime/clustering/network work | useful population structure and manipulation descriptors exist; several predictive uses failed | whether the structure improves exits, candidate promotion, analog retrieval, or social-transition inference |
| LP/toll studies | fees and ladder tolls were real in some cases; inventory change and opportunity cost could dominate | the value of an operator-controlled add/remove/reweight/rebalance policy |
| wallet PnL reconstruction | old trading books were often negative under reconstructed boundaries; accounting boundaries were easy to corrupt | prospective episode-level value of the newly described composite process |
| execution studies | tiny apparent profits are highly sensitive to quote freshness, landing and adverse fill; chain-only failure denominators are incomplete | whether a human-armed policy survives a calibrated end-to-end execution path |

The negative results remain important. The invalid move was promoting them from scoped findings to
universal laws.

## Where the implementation process went wrong

### The research object changed without a decision

Each subagent needed a bounded task, so latent context was compressed into a convenient local
target. Across many lanes, the local target became the strategy: predict an eight-hour return,
buy a callout, hold five minutes, classify one crime signature, or maximize a fee statistic.
There was no top-level episode ontology and no explicit trace from a subtask's estimand back to
Ember's composite policy.

### Code volume became a substitute for instrument validity

Large studies and daemons were written before basic denominators, operator traces, and point-in-
time social scenes existed. Some collectors were dead or never successful while downstream work
continued. Generated rows, demo hunches, and shadow positions could create an appearance of a
working laboratory without observing Ember.

### Result prose leaked into product and architecture

Scoped nulls became “entry prediction is dead.” Callouts became “never direction.” One hunch type
became the operator language. These claims then shaped UI, service boundaries, types, and migration
plans, making later corrections expensive.

### Irreversible code was less tested than pure analysis

The code-quality audit found strong pure transaction validators but no direct tests for the live
`SellExecutor`, including a confirmation-timeout double-submit path, persistent wallet-wide arming,
and restart/reconciliation hazards. This is an important architectural lesson: authority deserves
stronger structural separation and adversarial testing than planners or dashboards.

### Parallelism amplified premature commitments

Parallel work produced genuine breadth and useful fixtures, but a mistaken parent frame was copied
into dozens of otherwise capable tasks. More agents did not repair the missing ontology. Future
parallel lanes must return evidence and alternatives into a decision register before they can
become architecture.

## Corrected requirements recovered from the steers

1. The primary behavioral unit is an episode, which may include multiple inventory intervals,
   partial realizations, a retained runner, full exit, flat watching, and re-entry.
2. The primary data design is a market-wide coarse census plus high-resolution hot lanes selected
   by both product surfacing and Ember's attention.
3. A useful first product must match the Pump information loop closely enough to become Ember's
   natural cockpit; otherwise its attention data are residual and biased.
4. Selection, timing, management, execution, accounting, social transition, regime, and scale are
   separate estimands.
5. Operator acts and raw utterances precede a fixed taxonomy. Later recoding is an annotation,
   never a rewrite.
6. Social state is bitemporal, nonmonotone and identity-uncertain. Protocol fee events must not be
   misrepresented as human intent.
7. Wallet watching and ecology promote candidates; they do not directly authorize trades.
8. LP management distinguishes add, remove, rebalance, and inventory-swapping recenter operations.
9. Models begin with retrieval, supported contrasts and transition descriptions. Synthesis follows
   an evidenced language and remains outside the safety envelope.
10. The workstation can be valuable through better perception, accounting, replay and containment
    even if every strategy family is ultimately parked.
11. The project must also be able to establish that the composite policy is negative after the
    apparatus can faithfully observe it.
12. Financial pressure is not evidence. Household reserves, opportunity reserves and a bounded
    learning-loss budget must be visible before any later live experiment.

## Mission context and epistemic boundary

Ember described the hoped-for returns as leverage for formal verification, agentic systems,
machine-autarky, and machine-consciousness work, while also describing financial precarity. That
context makes auditability and containment more—not less—central. It does not make a trading edge
true, and the project should never imply that essential expenses can be recovered by scaling a
promising backtest.

“Our project” is best understood as a collaborative intellectual artifact: Ember supplies the
purpose, judgment, capital decisions, and domain-learning process; AI collaborators can help build,
criticize, remember and formalize it. The system should not rely on a model claiming personal
ownership, friendship, financial interest, or authority it does not possess.

## Provenance commands

The inventory can be reproduced locally with:

```sh
cv ls --harness claude --cwd ~/dev/joshibot --limit 200 --sort-by messages
cv show --harness claude --subagents <session-id>
cv events --harness claude --subagents <session-id>
cv index --subagents
```

The new research lanes and [`JOSHIBOT_COMPOST.md`](JOSHIBOT_COMPOST.md) are the reconciled next
layer. They should be preferred over `HANDOFF.md` for current design decisions while continuing to
cite the old results for their actual scoped findings.
