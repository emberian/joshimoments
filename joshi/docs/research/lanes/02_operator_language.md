# Lane 02 — operator language and elicitation

Status: research proposal; no engineering or execution authorization.

## Question

How can the system learn Ember's roughly 3–8 ways of regarding a coin and 2–5 kinds of
"crackle" without making Ember translate a fast, adaptive judgment into our vocabulary
before we have earned that vocabulary?

The answer cannot be a larger dropdown. The human is an adaptive sensor embedded in the
policy, not a label oracle standing outside it. A gesture, a moment of attention, an
immediate remark, and a retrospective explanation are observations made under different
conditions. They may disagree without any of them being corrupt. The product's job is to
preserve those observations and their conditions, make later comparison possible, and let
a personal language emerge through use.

This lane proposes a capture and elicitation discipline. It does not decide the final UI,
event schema, trading policy, or ontology.

## Provenance and observed facts

The following are inputs, not conclusions about profitability:

- `docs/PROJECT.md` defines an episode, rather than a position, as the atomic unit. An
  episode may contain entries, partial exits, flat-but-watching periods, and re-entries.
- Ember reports several presently unnamed dispositions toward a coin and several kinds of
  crackle. They are experienced as meaningful but have not yet been elicited systematically.
- Ember reports that material PnL can come from watching a graph, exiting, and re-entering
  later. Therefore `exit` cannot be assumed to mean `episode over`, nor can a re-entry be
  assumed to be an independent selection.
- `RADON`, `EarthCoin`, and `CRASHIUS` are requirements examples of crackles that became
  retained exposure after some profit realization. They are not validation examples.
- The old `joshibot` hunch tape has several sound capture choices:
  - the operator's exact utterance is kept alongside, rather than replaced by, its parse;
  - a click with no note is explicitly represented as an empty utterance rather than an
    invented explanation;
  - the gesture is persisted before the machine readout is shown;
  - event time and ingest time are separate;
  - retractions are appended rather than silently cleaning history;
  - zap records attempt to preserve the observable market and position state at exit.
- The same implementation also illustrates the compression to avoid. A hunch is forced
  into `wiggle`, `up`, `down`, or `watch`; confidence defaults to `0.6`; and `wiggle` has a
  predefined management meaning. Those fields can be useful as one historical experiment,
  but they are not an adequate language for the process now described.
- The current local hunch file is dominated by agent/test demonstrations and their
  retractions. Its existence establishes a data shape, not an empirical operator corpus.

Source paths in the compost repository include
`shitcoims_paperdesk/hunch.py`, `shitcoims_paperdesk/readout.py`,
`shitcoims_paperdesk/glass.py`, and `design/glass.md`.

## Position: capture acts before asking what kind of act they were

There are three separable layers:

1. **What happened:** a surface was visible, Ember inspected a coin, an action was intended,
   exposure changed, Ember stayed attentive while flat, or the episode ended.
2. **What Ember meant then:** a contemporaneous phrase, comparison, feeling, confidence,
   horizon, or explicitly inarticulable judgment.
3. **How the experience is organized later:** a named crackle type, disposition, thesis,
   episode phase, or machine interpretation.

Layer 1 should be as factual as the apparatus can make it. Layer 2 is an operator
observation whose timing and prompt matter. Layer 3 is versioned analysis. Neither a later
taxonomy nor a later interview may rewrite the first two.

This avoids a recurrent category error: `crackle`, `current disposition`, `thesis`,
`horizon`, and `management act` are not necessarily values of one enum. For example:

```text
entry mode:        a particular kind of crackle
current stance:    retain a runner
thesis:            community may cohere around the coin
horizon:           open-ended, reassess on social transition
current act:       sell enough to recognize a small profit
```

The same crackle type may lead to a full exit or a retained runner. The same runner stance
may have begun through different crackles. A partial sale changes inventory; it does not
by itself prove that the thesis or disposition changed. A full sale may begin a flat
interval inside the same episode rather than terminate it.

## Proposed observation language

The durable substrate should consist of events and assertions, not a mutable row containing
the system's latest story about a trade.

### 1. Episode and scene references

An episode is a minted identity that can span multiple inventory intervals. Every operator
event points to an episode when known and to a **scene reference** containing what was
available at that moment:

- coin and resolved mint;
- product surface and candidate-board membership/rank;
- viewport contents and visible chart window/resolution;
- open comparison panes and other coins recently inspected;
- contemporaneous market, social, quote, portfolio, and execution state;
- which fields were actually visible, merely known to the system, absent, stale, or added
  later;
- timestamps for gesture, local persistence, source events, and later enrichment;
- product, prompt, and interpretation versions.

The scene reference is not a screenshot alone. A screenshot is useful for replay but loses
semantic objects, offscreen candidate denominators, provenance, and exact values. Structured
state and a faithful rendered reconstruction should coexist where practical.

### 2. Coarse operator acts

The initial stable vocabulary should name observable interaction intent, not inferred
strategy. A possible bootstrap set is:

| act | narrow meaning |
|---|---|
| `notice` | deliberately mark a coin as worth returning to |
| `inspect` | open or focus the coin; often passively observed rather than clicked as a label |
| `arm` | authorize a specified watcher/playbook; not a prediction class |
| `cancel_arm` | revoke that authorization before entry |
| `enter` | express entry intent; transaction/fill remains a separate fact |
| `take_some` | reduce exposure without declaring the episode or thesis complete |
| `keep_remainder` | explicitly retain current exposure rather than merely neglect it |
| `go_flat_watch` | exit while intending to keep observing for a possible re-entry |
| `reenter` | enter during an existing episode after a flat interval |
| `reduce` | reduce risk for a reason not yet captured by a more specific act |
| `zap` | seek immediate exit; never delayed by elicitation |
| `close_episode` | declare that this line of attention is over for now |
| `compare` | explicitly place this coin in relation to one or more alternatives |
| `mark` | preserve an interesting moment without implying an action or thesis |
| `correct` | identify a misclick, wrong resolution, or mistaken earlier assertion |

This table is a proposal to test, not the first ontology release. Some of these may be
inferred safely from UI actions; others require an explicit gesture. `go_flat_watch` is
especially important: inferring it from a full sell would erase exactly the behavior the
project previously missed. Conversely, asking Ember to press `go_flat_watch` before an
urgent exit would be unacceptable. The sell/zap must happen first; continued watching can
be declared with a nonblocking follow-up or inferred only as an explicitly uncertain
candidate when the coin remains foregrounded.

Orders, sends, landings, fills, inventory intervals, and PnL records are not operator acts.
They are linked economic events. This preserves differences such as intended exit versus
actual fill, and `take_some` versus a transaction that failed to land.

### 3. Contemporaneous assertions

After an act has been durably recorded, Ember may add zero or more assertions:

- exact free text or deliberately recorded voice;
- `what_changed` source cues such as chart, flow, social activity, identity/narrative,
  execution/liquidity, portfolio/risk, another opportunity, or `not articulable`;
- horizon as ordinary language first ("a few minutes", "while this is alive", "until the
  creator notices"), with any normalized duration kept as a derived parse;
- a personal type token if one is already in active use;
- relation to another episode or moment: `same kind`, `different in this way`, `reminds me
  of`, or `not actually like`;
- confidence only when Ember spontaneously has or deliberately supplies a probability-like
  judgment. A universal default confidence must not fabricate one.

The source cues are retrieval aids, not a causal taxonomy. Multi-select, none, and "other"
must be normal. Their order should rotate or remain visually neutral enough not to train
one answer. If the system has an interpretation, it is shown only after the operator's
contemporaneous capture unless the research question explicitly concerns decision support.

### 4. Attention observations

Attention is never directly observable. The apparatus observes exposure and interaction:

- which candidates were rendered and at what ranks;
- viewport entry/exit and foreground/background state;
- opens, closes, tab changes, comparisons, watchlist changes, chart timeframe changes,
  pan/zoom, and intentional marks;
- interaction recency and idle periods;
- time a coin remains visible while Ember is flat or holding;
- whether a machine alert, Pump surface, search, or prior episode led to the inspection.

These events support statements such as "coin A was in the foreground for 42 seconds with
three chart-resolution changes." They do **not** support "Ember studied A for 42 seconds."
Dwell may be distraction, a conversation, or a window left open. Cursor travel is not a
thought trace. The data model should represent `foreground_visible`, `visible_idle`,
`background`, and `unknown`, with uncertainty, rather than manufacturing a single attention
duration.

Capture should be app-scoped. No global keylogger, clipboard logging, unrelated-browser
history, camera inference, ambient microphone, or OS-wide screen recording is justified by
this lane. A deliberate voice note is different from ambient audio. High resolution means
preserving the relevant scene faithfully, not surveilling everything a person does.

## Elicitation protocol

### Stage A — preserve behavior with almost no taxonomy

At first, the primary input is the act itself. The act is recorded synchronously and the
market scene is attached automatically. Exits are never gated on a question. Entry arming
must not grow extra steps merely to improve the dataset.

After a meaningful transition, a small, dismissible prompt may remain available for roughly
the next minute:

> What changed? `chart` `flow` `social` `position/PnL` `another opportunity`
> `just felt different` `say/type a few words` `skip`

The prompt is not modal and no answer is considered missing ground truth. The exact prompt,
option layout, response latency, and whether an answer was skipped are captured. `Skip`
must be one tap and emotionally neutral.

Some transitions deserve a tailored but still open question:

- after `take_some`: "Did your view change, or only the amount you wanted exposed?"
- after going flat while the coin stays visible: "Still watching this episode?"
- after re-entry: "What is different from the exit scene?"
- after keeping a remainder: "What would make this remainder no longer worth holding?"
- after a mark: no automatic request; the mark is already useful.

The point is not to fill every field. It is to distinguish changes that look identical in
the ledger and to catch phrases that would otherwise vanish.

### Stage B — collect personal tokens without defining them

When Ember repeatedly says something like "this is the other kind of crackle" or "this one
is becoming a sender," allow a one-tap **name this for now** action. It creates an opaque,
personal token attached to the examples Ember chose. A token may begin as `crackle-2`, an
emoji, or Ember's own phrase. It need not have a definition.

The system should never autocomplete a newly coined term onto old episodes. It may offer
recent tokens, but `unsure`, multiple tokens, and no token remain valid. The token is a
handle for retrieving examples and contrasts, not yet a class label.

### Stage C — contrast cases, not abstract questionnaires

Definitions are easier to discover from counterexamples than from asking "what are your
crackle types?" After enough marked moments exist, present short, outcome-blinded pairs or
small sets:

```text
scene A at arm time       scene B at arm time
same kind / importantly different / cannot tell now
What distinction mattered, if any?
```

Pairs should include:

- two moments Ember gave the same provisional token;
- one tokened and one nearby unlabelled moment;
- two acts with the same economic result but visibly different paths;
- repeated visits to the same coin before exit and re-entry;
- a machine-suggested near neighbor;
- at least occasional successful/unsuccessful examples hidden from view.

Start with open contrast ("what differs?") before showing machine-generated factors. A
later follow-up can ask whether a proposed phrase fits. This reduces priming and gives us
both the unassisted distinction and reaction to the proposal.

### Stage D — propose, test, split, merge, and retire

A provisional category is ready for an explicit definition only when it recurs and the
distinction changes retrieval, expectation, or management in a way Ember recognizes. A
useful review card contains:

- the proposed name and Ember's original phrases;
- representative positive examples at decision time;
- boundary cases and counterexamples;
- the acts and transitions commonly associated with it, clearly reported as associations;
- whether Ember recognizes it on blinded replay;
- known confounds such as outcome, token age, UI source, or market regime;
- unanswered questions and examples that do not fit.

Ember can accept the proposal as provisional, rename it, split it, merge it, reject it, or
leave it as an unnamed cluster. No minimum sample count alone can promote a category. It
should not be promoted merely because the cluster has unusually good PnL: that would turn
an outcome partition into a counterfeit contemporaneous disposition.

### Stage E — use the language prospectively

Only after a term survives contrast review should it earn a quick button. The button's use
is another assertion, not proof that every pressed example belongs or that every unpressed
example does not. Measure whether the button reduces burden, gets corrected, changes
behavior, or becomes a reflex that obscures nuance.

Terms that eventually support different automation may become part of a stricter playbook
language. That later compilation step must name which term version it consumes and show
which parts remain informal.

### Relation to program synthesis and abduction

The eventual synthesis object is not a classifier that predicts which button Ember would
press. The trace is a **partial behavioral specification**:

- acts and non-acts under known choice sets provide positive and qualified negative cases;
- `same kind` / `importantly different` judgments provide relational constraints;
- corrections and counterexamples identify missing predicates;
- episode transitions constrain allowable temporal structure;
- immediate utterances suggest latent predicates without defining their implementation;
- flat watches and re-entries show hidden state that inventory alone cannot distinguish.

An inferred circuit or program can therefore be asked to reproduce only a named slice of
the composite policy—for example, when a particular watch becomes armable—while leaving
selection, exit, or disposition change uninterpreted. Competing programs that are
observationally equivalent on the current corpus should remain a versioned hypothesis set,
not be collapsed to the shortest story. The elicitation loop should preferentially surface
real future cases that distinguish those hypotheses; it should not ask Ember to manufacture
labels for synthetic states they have never encountered.

## Low-friction interface semantics

The interface should separate **act now** from **explain later**:

- Immediate acts live at the coin/position and use stable placement. A gesture records
  before any readback, suggestion, animation, or network call that could fail.
- `zap`/sell remains one action with no confirmation or annotation gate. The apparatus can
  ask after the intent is safely persisted and the execution path has begun.
- Optional explanation appears as a small pending chip, not a modal. It expires visibly;
  expiration means "not elicited," not "no reason."
- A single `mark` hotkey captures the last short scene window and the next few seconds. It
  gives Ember a way to say "something happened here" without finding a label in real time.
- Notes accept fragments. No grammar correction, normalization, forced sentence, or minimum
  length. `idk`, `felt alive`, and an empty note are valid and distinct.
- Voice notes, if added, require a deliberate press/hold and an obvious recording state.
  Preserve audio only by explicit retention choice; preserve transcript confidence and the
  transcription model separately.
- Product defaults should not masquerade as operator judgments. An omitted horizon,
  confidence, runner fraction, or type is absent, not the system's favorite value attributed
  to Ember.
- The machine may offer "same as last time?" only after the event is captured. `No` and
  `not sure` must be easier than accepting a wrong analogy.
- The prompt system needs a visible snooze/private-session control and a per-session burden
  budget. Urgent or dense periods should produce fewer questions, not a backlog demanding
  clerical work later.

A promising interaction sequence for partial realization is:

```text
[sell 40%]  -> intent captured and sent
            -> nonblocking: [just taking profit] [view changed] [free text] [skip]
            -> current remainder: [intentionally keep] [undecided] [plan to exit]
```

These answers must not be required to complete the sell. They distinguish an inventory act
from a disposition transition without pretending that the button names every possible
reason.

## Replay-backed interviews

Retrospective interviews are valuable because Ember may be able to articulate a gestalt
only after seeing several phases together. They are also contaminated by outcome knowledge.
The apparatus should make the contamination measurable rather than pretend to remove it.

### Interview sampling

Do not interview every episode. Sample for information, including:

- exit and later re-entry;
- partial profit followed by deliberate retention;
- a provisional type's boundary case;
- an unusually fast or slow decision;
- a good outcome, bad outcome, and unresolved outcome;
- a random ordinary episode, so only salient successes and disasters do not define the
  language;
- an episode where no contemporaneous explanation was given.

The sampling rule and selection time are recorded. The operator can defer, skip, or declare
the episode private without penalty.

### Two-pass protocol

**Pass 1: outcome-blinded reconstruction.** Replay only information available up to each
gesture. Hide future path, final PnL, later social events, and later model interpretations.
Show the actual viewport before a reconstructed analytical dashboard when possible. Pause
at notice, arm, entry, partial exit, full exit, flat watch, and re-entry.

For each important pause, ask open questions first:

1. "What, if anything, were you attending to here?"
2. "What action were you trying to make possible or avoid?"
3. "Had your view of the coin changed, or only your desired exposure?"
4. "What nearby alternative were you comparing it to, if any?"
5. "Does this feel like the same kind of situation as [operator-chosen prior example]?"
6. "What would you have needed to see next?"

`I do not remember`, `nothing articulable`, and disagreement with the replay are valid.
Only after open recall should the interviewer show Ember's contemporaneous note or ask about
a machine-proposed distinction.

**Pass 2: outcome-aware reflection.** Reveal later events and accounting, clearly marking
the phase change. Ask:

- "What did the later path teach you that was not available then?"
- "Which part of your earlier account still feels true?"
- "Are you recalling the decision or constructing an explanation from the outcome?"
- "Would you now rename, split, or relate this situation differently?"
- "Was the eventual zap thesis completion, risk reduction, attention loss, another
  opportunity, or something else?"

Pass 2 creates retrospective assertions; it never repairs Pass 1 or the contemporaneous
tape. Interviewer prompts, replay build, visibility cutoff, pauses, edits, and any LLM
participation are themselves recorded.

### Interviews around a flat interval

For an exit/re-entry sequence, replay must keep one clock running across the flat period.
Ask what kept the coin cognitively alive, what changed enough to cause exit, and what changed
again to cause re-entry. Showing two disconnected trade tickets would invite the same false
model as treating them as independent positions.

## Hindsight and intervention contamination

Every assertion should carry at least:

- `asserted_at`;
- the event or interval it refers to;
- `elicitation_mode`: spontaneous, immediate prompt, blinded replay, outcome-aware replay,
  correction, analyst annotation, or machine annotation;
- exactly what future data was visible at assertion time;
- prompt text/order and product version;
- whether machine suggestions were visible before the answer;
- the operator's words and any parse as separate objects.

This permits useful distinctions:

```text
"felt socially alive" said 4 seconds after arm
"I think I saw community cohesion" said during blinded replay
"obviously it was going to send" said after seeing a 12x outcome
```

All three may be psychologically informative. Only the first two can plausibly describe
information available to the policy at the original decision. Even a blinded replay is not
fully uncontaminated: Ember knows the episode was selected for interview and may remember
the result. Record self-reported recognition rather than calling it unbiased.

LLM analysis introduces an additional intervention. If the model's social-transition
summary is visible before Ember acts, it becomes part of the composite policy and must be
captured as visible evidence. If it is produced later for research, it is a recomputable
annotation. Studies must not quietly mix those roles.

## Ontology versioning

The ontology is a graph of historical proposals, not a table whose rows are edited in
place.

A term version should contain:

- stable term identity and version identity;
- Ember's display name and exact defining words;
- creation time and elicitation mode;
- status: `opaque`, `provisional`, `active`, `split`, `merged`, `retired`, or `rejected`;
- positive examples, boundary examples, and explicit counterexamples as assertions;
- parent/successor relationships and reasons for split/merge/retirement;
- dimensions it purports to describe: entry mode, present disposition, thesis, horizon,
  management style, scene quality, or another named dimension;
- known observables, missing predicates, and incompatible interpretations;
- any playbook/model versions that consumed it.

An assignment of a term to an episode is independently versioned and attributed. For
example, Ember may apply `crackle/foamy@v1` immediately, later say it was a boundary case,
and a researcher may annotate it as `foamy@v2` under a harmonized retrospective view. The
historical query returns what was believed then; the harmonized query returns later
reinterpretations with their source. Neither silently replaces the other.

Splits and merges are many-to-many mappings with notes, not database migrations that rewrite
history. A retired term remains resolvable for old buttons, interviews, and policies. A
model trained against a taxonomy release pins that release. Free text and source scenes
remain the recovery path when every early parse turns out to be wrong.

## Counterexamples the design must survive

1. **Same action, different meaning.** Ember sells 40% once because the coin may send and
   once because another opportunity is better. Inventory deltas alone cannot infer stance.
2. **Different action, same stance.** Ember keeps a runner by doing nothing in one episode
   and by deliberately rebuying after going flat in another.
3. **Full exit is not closure.** Ember exits on the graph, watches while flat, and re-enters.
   Splitting this into two selections loses management value and double-counts attention.
4. **The label follows the outcome.** A profitable remainder gets called a `runner`; a
   worthless remainder with the same event-time intent gets called `dust`. Outcome-aware
   language must not be backfilled as the original disposition.
5. **A convenient button becomes a false ground truth.** Ember presses the nearest quick
   button while moving quickly. Usage is evidence of fit plus interface cost, not an oracle.
6. **No note is not no intuition.** Urgency, cognitive load, or inarticulability may produce
   an empty annotation during the most meaningful decisions.
7. **Long dwell is not attention.** The graph is foregrounded while Ember gets food or
   messages someone.
8. **Short dwell is not disregard.** A familiar visual pattern is rejected or armed almost
   instantly.
9. **Words drift.** `sendy` may initially mean chart energy and later mean social convexity.
   One string does not imply one timeless concept.
10. **One moment has multiple dispositions.** Ember is willing to crackle a microdip while
    separately wanting a small catalyst runner. A single mutually exclusive label destroys
    the structure.
11. **Machine interpretation changes the sensor.** An LLM calls a community "cohering";
    Ember subsequently notices supporting evidence. The summary is an intervention, not a
    latent label recovered from an untouched human.
12. **A correction is informative but not shameful.** Wrong mint, misclick, accidental arm,
    and "I said that badly" need lightweight correction without deleting the record or
    treating the event as a strategic failure.

## Privacy, autonomy, and burden

The highest-resolution human data is also the most intimate part of the system. A personal
trading cockpit can reveal wallet holdings, sleep/work rhythms, fixation patterns, emotional
language, private social interpretations, and mistakes. "Useful for later training" is not
sufficient consent for indefinite collection or external transmission.

Proposed constraints:

- app-scoped interaction capture by default; no ambient surveillance;
- local-first storage for operator utterances, view traces, and interviews;
- explicit, per-use disclosure before any raw scene, voice, social content, or operator text
  is sent to a hosted model;
- minimization at export: pseudonymous episode/coin identities where possible, no secrets,
  clipboard contents, signing material, or unrelated application state;
- separate retention controls for structured gestures, rendered scene snapshots, raw audio,
  and interview transcripts;
- a private-session switch that still permits trading/observing without research capture;
- append-only corrections for scientific integrity, **plus a real hard-erasure path for
  sensitive human data**. An audit tombstone may say that material was erased; it must not
  preserve the erased content. Research provenance does not outrank the operator's privacy.
- corpus-exclusion flags independent of display: Ember may keep a note for personal replay
  while forbidding its use for model training or exports;
- no nagging to fill missing fields and no gamified annotation-completeness score.

Burden is an outcome to measure. Record prompt frequency, dismissal, response latency,
unfinished annotations, and whether prompting caused Ember to miss or alter a trade. Ask
periodically whether the glass feels like an instrument or a clerk. The system should spend
its prompt budget on rare distinctions—especially exit/re-entry and crackle-to-runner
transitions—rather than request a confidence slider on every glance.

## Smallest useful experiment

Run an **instrumentation-only, prospective episode diary** alongside Ember's existing manual
workflow. It observes and marks; it neither signs nor submits transactions.

### Scope

Collect the next approximately 20 attended coin episodes or two weeks of ordinary use,
whichever provides enough variation for a review. Include all marked episodes, not only
winners or completed trades. An episode can begin at `notice` and need never receive capital.

Use only:

- coarse acts: `notice`, `arm`, `take_some`, `flat_watch`, `reenter`, `keep_remainder`,
  `zap`, `close_episode`, and `mark`;
- automatic scene/viewport references and manual transaction reconciliation;
- an optional, nonblocking "what changed?" fragment after `take_some`, `flat_watch`,
  `reenter`, `keep_remainder`, and `zap`;
- no predefined crackle-type or disposition selector;
- a way to attach an improvised personal token when Ember spontaneously wants one.

The three existing runner examples can be imported only as retrospective requirements and
used to test replay shape. They must not be mixed with the prospective sample as though
their original scenes had been captured.

### Review

After sufficient prospective scenes exist:

1. sample five episodes, including at least one flat/re-entry interval and one partial
   realization/remainder transition;
2. conduct the two-pass replay interview;
3. perform ten or fewer outcome-blinded pairwise comparisons chosen for contrast, not PnL;
4. let Ember create, reject, or leave unnamed provisional tokens;
5. produce an ontology draft containing examples and counterexamples, not a set of required
   buttons.

### Evaluation

The experiment succeeds if it tells us whether the apparatus can:

- reconstruct what was visible and what alternatives existed at each gesture;
- link multiple position intervals into the intended episode;
- distinguish partial inventory management from a change in disposition;
- preserve a flat-but-attentive interval and later re-entry;
- capture useful fragments without slowing exits or materially disrupting Ember's process;
- recover at least some stable contrasts **or honestly show that the current sample does
  not support them**;
- identify what the next version failed to observe.

Track capture/linkage failures and median interaction overhead. Do not use PnL, label count,
annotation completion, or agreement with a machine cluster as the success criterion. The
product can learn that it is too intrusive or that the scenes are inadequate before it has
learned any profitable type; that is valuable experimental output.

## Dependencies on other lanes

- **Episode/accounting model:** must represent multiple inventory intervals, partial exits,
  flat watches, re-entries, intent versus fill, and eventual resolution.
- **Market-wide census and scene tape:** supplies the candidate denominator, ranks,
  contemporaneous alternatives, raw chart/flow state, and knowledge-time boundaries.
- **Glass and replay:** supplies faithful view capture, nonblocking gesture placement,
  comparison views, and outcome-blinded reconstruction.
- **Execution and reconciliation:** eventually links intent to quotes, transactions, fills,
  and exposure without letting annotation block a safety action. This lane authorizes none
  of those operations.
- **Social/identity history:** preserves raw social material and point-in-time identity
  transitions that Ember may have responded to.
- **Privacy/security:** determines encryption, hosted-model boundaries, deletion,
  pseudonymization, and export policy before intimate traces accumulate.
- **Interpretation/model provenance:** versions LLM prompts, outputs, visibility, and model
  timing so analysis can be separated from decision support.
- **Clock and data-quality semantics:** distinguish gesture, persistence, source-event,
  render, enrichment, order, and fill time, and represent absence rather than zero.

## Unresolved questions

1. What event begins an episode when Ember notices a coin on Pump before opening it in the
   personal glass?
2. How long can a flat interval remain in the same episode, and should only Ember close it,
   or may the system propose closure after inactivity?
3. Which viewport semantics are feasible across Pump-like parity surfaces without brittle
   screenshots or invasive browser instrumentation?
4. Which actions are safe to infer from ordinary UI use, and which require a distinct
   operator gesture?
5. Does prompting immediately after an exit interfere with continued graph watching even
   when nonmodal?
6. Would a hold-to-record voice fragment be lower burden than typing, or too intimate and
   operationally awkward?
7. How should the system sample ordinary, forgettable episodes for interview without making
   the interview itself feel like punishment?
8. Can Ember reliably recognize provisional types on outcome-blinded replay, or are some
   dispositions inherently relational to portfolio state and recent market experience?
9. How much candidate/context history must be shown for a replay to restore the relevant
   state without exposing future information?
10. When LLM analysis becomes realtime, which questions measure the unassisted operator and
    which deliberately evaluate the augmented composite policy?

## Recommendation for reconciliation

Adopt four invariants now:

1. Record observable acts and their scenes before requesting a class label.
2. Keep entry type, current disposition, thesis, horizon, and management act separable.
3. Version every interpretation and preserve contemporaneous, blinded-retrospective, and
   outcome-aware accounts as different evidence.
4. Make exit/re-entry and partial-profit/remainder sequences first-class episode paths in
   the very first observational slice.

Defer the actual 3–8 disposition buttons and 2–5 crackle buttons until prospective use and
contrastive replay produce language Ember recognizes. The absence of a settled taxonomy is
not a blocker. It is the thing this apparatus is being built to measure.
