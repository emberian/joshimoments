# Lane 08 — Product glass and operator interaction

Status: exploratory product specification, not an architecture decision or an execution
authorization.

## 1. Question and proposed answer

What must the operator-facing product do before it is reasonable to compress Ember's process
into features, labels, rules, or learned policies?

The proposed answer is a **personal Pump-like cockpit that is also an experimental
instrument**. It must be useful enough to become the place Ember naturally looks, compares,
acts, and revisits; otherwise it will observe a distorted, impoverished version of the real
process. At the same time, it must preserve the market, product, portfolio, and social scene
surrounding each allocation of attention and each gesture.

The glass is therefore not a dashboard placed on top of a strategy. It is part of the object
being measured:

    market surface -> viewport -> attention -> interpretation -> gesture
      -> order/fill or deliberate inaction -> later management -> resolution

This lane proposes product behavior and information architecture. It does not choose a web
framework, database, chart library, RPC vendor, execution venue, or pixel design.

## 2. Grounding and compost

### 2.1 Project facts that constrain this lane

From `docs/PROJECT.md`:

- The atomic object is an **episode**, which may contain multiple inventory intervals,
  realized clips, flat-but-watching intervals, and re-entries.
- Crackle is an entry and early-management mode, not a complete position lifecycle.
- Crackle, retained runners, fancoin/social transitions, and LP inventory are independent
  books sharing a sensorium.
- The whole attention funnel matters: universe, surfaced candidates, viewport, inspection,
  dismissal, arming, execution, management, and contemporaneous alternatives.
- Raw inputs precede derived interpretations. Later model and LLM outputs are recomputable,
  versioned annotations.
- This phase may observe but may not sign or submit transactions.

These are requirements, not hypotheses produced by this lane.

### 2.2 Useful compost from `~/dev/joshibot`

The old glass and app earned several interaction and instrumentation principles worth
carrying forward:

- A live list must not reshuffle under a pointer while the operator is reading, typing, or
  acting. The old explorer explicitly paused reordering in these states.
- Exits must remain continuously reachable. The old sticky zap rail correctly treated an
  exit hidden behind a tab as not actually available.
- Missing, stale, errored, unwatched, and measured-zero states must not collapse into zero.
- Event time, ingest time, source, and caveat should travel with a displayed fact.
- An optional note must never block a time-sensitive gesture; the exact operator utterance
  is more valuable than a forced parse.
- A reconstructed five-point price path must not masquerade as candles. The old chart's
  warning is a useful example of display semantics following evidence semantics.
- A client-declared screen context and a server-measured market context should remain
  distinguishable.
- A submitted action needs a receipt and an honest unresolved state, not an optimistic
  animation that implies a fill.

These ideas are visible in `design/glass.md`, `app/views/explorer.tsx`,
`app/components/pricechart.tsx`, `app/components/instrument.tsx`, and
`design/reconciler.md`.

### 2.3 Compost not promoted

The old design also embedded conclusions that the new project must not inherit as product
facts:

- “wiggle” as the sole action-producing hunch;
- a mechanical hold-duration backstop as a representation of reactive exit judgment;
- fixed entry gates and a particular ranking as the strategy;
- prior studies' callout or drawdown verdicts written directly into the daily surface;
- a click simultaneously meaning “I see this disposition,” “buy now,” and “use this
  management policy”;
- a permanent claim that external trading tools can be discarded after a milestone;
- a fully specified expectation grammar before ordinary actions and scenes can be captured;
- an early commitment to typed program synthesis or any other learning family.

Those remain historical artifacts and candidate hypotheses. They are not the new glass's
ontology.

## 3. Product contract

### 3.1 Parity is a continuously audited capability, not a frozen page list

“Pump-like” means Ember can perform the information-seeking loop that would otherwise take
place in Pump without losing material information or reaction time. It does not mean
copying Pump's pixels.

At minimum the parity audit must inventory, using the current product rather than memory:

- every discovery surface Ember actually uses, such as new launches, trending/boards, live
  activity, callouts, communities, search, and direct mint opening;
- ordering, pagination or infinite-scroll behavior, badges, filters, and update cadence;
- the coin-page chart, trades, holders, creator/community identity, posts/replies, media,
  and migration or pool status;
- the route from discovery card to closer inspection and then to action;
- which surfaces are personalized, session-dependent, geographically variable, or opaque.

A screen is not “parity complete” because it has fields with similar names. It is complete
when a side-by-side observation session shows that Ember can notice the same opportunities,
understand at least the same context, and move between surfaces at least as quickly. This
comparison should be repeated because the reference product changes.

“Superior” means adding operator-specific powers without degrading parity:

- exact choice-set and attention capture;
- synchronized market and social timelines;
- size-specific executable quotes and live round-trip hurdles;
- episode, disposition, and portfolio context;
- duplicate/family and social-transition views;
- stable replay of what was knowable at the time;
- immediate and retrospective annotations;
- honest provenance, uncertainty, conflict, and absence.

Coverage, rank agreement, card latency, social/media completeness, and coin-page freshness
should be measured during parity audits. Unknown personalization in the reference product is
an explicit limitation, not silently counted as agreement.

### 3.2 Daily surface and laboratory are the same product

A separate “research logger” that Ember remembers to fill out after trading will mostly
capture memorable successes and rationalized failures. A separate “clean trading UI” will
discard the very context the project needs.

The primary surface must therefore:

1. show the market naturally enough to earn attention;
2. capture the scene automatically;
3. let Ember express a low-latency gesture with little or no prose;
4. provide deeper annotation and replay later;
5. never require research chores before an urgent action.

Research affordances are embedded but visually quiet. Instrumentation should not make every
coin card look like a laboratory control panel.

### 3.3 Stable primitives; evolving meanings

Some product primitives can be stable even while the strategy vocabulary changes:

- surfacing, impression, focus, open, compare, pin, dismiss;
- watch while flat;
- arm an entry disposition;
- create, increase, reduce, or remove inventory;
- realize part and retain part;
- re-enter an existing episode;
- attach an utterance, mark, confidence, horizon, or unknown;
- revise or retire a label;
- close an episode.

The meaning of “crackle type 3,” “this might send,” or a not-yet-articulated social feel must
remain flexible. The glass records action and language separately. A new disposition label
does not rewrite the historical action that originally carried an “other” note.

## 4. The four always-available contexts

The glass should feel like one continuous workspace, not a collection of analytical tabs.
Four contexts must be reachable without losing the current coin or scene.

### 4.1 Market surface

This is the market-wide census made usable:

- current Pump-parity feeds and boards;
- search and mint paste;
- watchlists and personally pinned candidates;
- live callout/social activity;
- candidate families and duplicates when known;
- indicators of feed health and the limits of collection.

Cards initially show only identity, age/state, a compact activity trace, current context
badges, whether the coin is already in an episode, and the available low-commitment
gestures. More fields expand in place.

Feed updates should enter a pending buffer while a row is under the pointer, has keyboard
focus, is selected, or is visible during a gesture. The card may update its numbers without
moving; rank changes can be indicated separately. A “new order available” affordance lets
the operator accept reordering. This preserves both responsiveness and attribution of the
intended target.

The system records the board snapshot and ordering even for rows below the viewport. It
separately records which rows actually entered the viewport. “Served” and “seen” are not
synonyms.

### 4.2 Coin workbench

Opening a coin preserves the market surface behind it and creates a high-fidelity hot
context. The workbench combines:

- identity and lifecycle header;
- live chart and event tape;
- trades/flow and size-specific executable quotes;
- Pump posts, replies, authors, media, mentions, callouts, and community context;
- creator/fancoin identity and transition evidence;
- holder and liquidity context when genuinely measured;
- current episode, inventory intervals, realized clips, disposition history, and annotations;
- contemporaneous alternatives or a return to the exact originating board state;
- an action tray whose primary gestures are reachable without scrolling.

The workbench must not make a social post, model summary, market metric, or operator
attestation look like the same kind of fact.

### 4.3 Episode/exposure rail

A persistent rail shows all economically or attentively live episodes, including coins for
which inventory is currently zero but Ember is still watching for re-entry.

Each compact row answers:

- what is the coin and current disposition, in Ember's own latest words?
- exposed, pending, or watching flat?
- how much was spent and recovered across the episode?
- what inventory remains and what can it actually liquidate for at the displayed size?
- what happened in the latest clip?
- how old and fresh are the market and quote observations?
- what is one unambiguous route to reduce, zap, or reopen the workbench?

A retained runner is not “free.” The rail shows realized net PnL, unrecovered basis,
remaining executable value, maximum remaining economic downside, and aggregate runner
budget separately.

The rail cannot poll from a slower snapshot than the action surface without making the
mismatch loud. If the displayed inventory and chain observation disagree, the row is
“reconciling” rather than silently choosing one.

### 4.4 Replay and interview queue

Replay is not a back-office report. Any episode, gesture, fill, or notable social transition
can open a reconstruction of the scene as it appeared then.

The queue surfaces:

- short immediate prompts that were deferred during live attention;
- unresolved action/fill reconciliation;
- episodes ready for a post-zap interview;
- ontology labels that may need clarification;
- scenes marked “interesting but I cannot articulate why.”

Replay initially withholds later outcomes. Ember first sees the original scene and can
describe the contemporaneous feeling without outcome contamination. A second step reveals
what happened and asks for retrospective interpretation. Both accounts remain distinct.

## 5. Chart and synchronized context

### 5.1 Evidence requirements

A high-resolution chart must be backed by actual event or sampling semantics. It should
support, as sources permit:

- real trades or legitimate OHLCV aggregation;
- bonding-curve or pool reserve state;
- current venue and migration boundary;
- executable buy and sell quotes at Ember's intended size;
- event time and ingest delay;
- explicit gaps and degraded collection;
- multiple horizons from seconds through the full episode.

Connecting sparse observations is allowed only if the visual grammar says they are samples,
not a continuously observed path. Chart marks and executable liquidation values remain
different series.

### 5.2 Overlays

Overlays should be independently toggleable and time-aligned:

- operator gestures and utterance markers;
- planned, submitted, landed, failed, and unresolved orders;
- actual fills and inventory intervals;
- partial realizations, runner promotions, full exits, and re-entries;
- posts, callouts, creator claims, participation, and community transitions;
- board entries, rank changes, and appearance in the viewport;
- versioned machine interpretations;
- LP bin range, active bin, adds, removes, fee collections, and rebalances where applicable.

The default view contains only the overlays needed for the present disposition. Progressive
disclosure, not omission, manages density.

### 5.3 Drawing and pointing

A chart gesture can capture a region, path, level, interval, or “this bit” without requiring
an immediate formal interpretation. The artifact stores:

- raw geometry in chart coordinates;
- visible time/price bounds and scale mode;
- the utterance, if any;
- the scene bundle and selection state;
- any later structured interpretations as separate versions.

The product may later suggest “local retest,” “microdip,” or another label, but Ember can
accept, edit, reject, or leave it unparsed. The raw pointing act survives vocabulary change.

## 6. Social and identity context

The social pane must preserve enough structure for future transition analysis rather than
rendering a flat sentiment score:

- original text and media references;
- author identity as observed then, with aliases and verification evidence;
- reply/repost/mention/thread relationships;
- post, edit, delete, ingest, and first-observed clocks where available;
- community membership and activity;
- relationship to the represented person, deployer, fee recipient, and competing coins;
- provenance and collection gaps.

A compact live pane can group activity into threads and participants. Expanding it reveals
the raw event order. An LLM summary is visibly an interpretation with model, prompt version,
input coverage, creation time, and uncertainty. It never replaces source posts.

For fancoins, the workbench should show a transition notebook rather than a single
“claimed” badge. Candidate states may include unofficial reference, community aggregation,
identity resolved, verified fee claim, creator participation, public endorsement, audience
arrival, fragmentation, persistence, and decay. These are observations or hypotheses with
evidence, not forced mutually exclusive phases. Multiple transitions can be disputed or
unknown.

## 7. Choice-set, viewport, and attention capture

### 7.1 What the glass records

For each rendered list epoch:

- feed/source, query, filters, sort, experiment/version, and refresh identifier;
- complete candidate IDs and order served to the client;
- card data actually rendered and its clocks;
- viewport bounds, visible candidates, their visible fraction, and duration;
- focused, hovered, expanded, compared, pinned, dismissed, or acted-on candidates;
- the originating surface and navigation path;
- whether ordering was frozen and which updates were pending;
- device class, window dimensions, and relevant disclosure state;
- portfolio and currently hot episodes;
- collection health and known gaps.

Dwell is a behavioral trace, not proof of attention. Hover is a pointer event, not interest.
The names should say exactly what happened.

### 7.2 Scene bundles at decision points

At every arm, inventory-changing gesture, disposition change, zap, re-entry, or explicit
annotation, commit an immutable scene bundle containing references to:

- the originating choice set and exact visible card state;
- current coin workbench state and chart viewport;
- raw market/social event cursors;
- quote and portfolio snapshots;
- current episode and disposition;
- alternative candidates visible or recently compared;
- client version and derived-annotation versions;
- operator utterance and gesture geometry.

Periodic and event-triggered checkpoints allow deterministic replay between gestures. A
lossy screenshot can be included as a visual checksum, but cannot substitute for structured
state or raw source evidence. Continuous video should not be the default: it is difficult
to query, expensive, privacy-invasive, and worse than an event-sourced reconstruction for
most research questions.

### 7.3 Privacy boundary

High resolution means high resolution inside the cockpit, not ambient surveillance of the
computer. By default the glass does not record arbitrary keystrokes, unrelated windows,
clipboard contents, microphone audio, or screen video. It records its own render state,
focus/visibility events, and text intentionally entered into its controls. Any broader
capture requires a separate explicit decision and visible recording state.

## 8. Gesture language

### 8.1 Separate observation, intent, and capital action

The following must not collapse into one click:

1. “I notice this.”
2. “I think it has a particular disposition.”
3. “Watch for a condition.”
4. “I authorize bounded action if the condition occurs.”
5. “An order was submitted.”
6. “Inventory changed.”
7. “My interpretation changed.”

A low-latency interface can make steps 2–4 one deliberate gesture when Ember wants that,
but the event model preserves the constituent meanings and their clocks.

### 8.2 Initial gestures

The first vocabulary should be small and extensible:

| Gesture | Meaning | Inventory effect |
|---|---|---|
| **open / compare / pin** | allocate attention | none |
| **watch flat** | keep coin/episode live without exposure | none |
| **arm crackle** | authorize or shadow a bounded conditional entry | none until fill |
| **buy/add** | create or increase an inventory interval | positive |
| **take some** | realize a specified quantity or value | negative, episode stays live |
| **profit + runner** | partial realization plus explicit retained disposition | negative, still exposed |
| **promote/change disposition** | revise current intent or thesis | none by itself |
| **reduce** | deliberately lower exposure without closing | negative |
| **zap** | request the full executable exit | closes interval if filled |
| **stay flat** | after exit, continue watching inside the episode | none |
| **re-enter** | begin a new inventory interval in the same episode | positive |
| **resolve episode** | stop treating the coin as attentively live | none |
| **watch social transition** | track a person/community/coin transition hypothesis | none |
| **arm fancoin** | authorize or shadow a bounded catalyst entry | none until fill |
| **LP add/remove/reweight/close** | manage contingent inventory schedule | position-specific |

“Take some” and “profit + runner” are not interchangeable. The former is an inventory
action; the latter additionally records a disposition transition. A full exit does not
automatically resolve the episode. Re-entry after graph watching must remain linked to the
same episode unless Ember deliberately starts a new thesis.

Every gesture accepts an optional short utterance, “not articulable,” confidence, horizon,
and custom tag. None is mandatory on the time-critical path.

### 8.3 Flexible ontology

Disposition and crackle-type vocabularies should be operator-owned, versioned label sets:

- a new label can be created from “other” without schema migration;
- labels can be renamed, aliased, split, merged, deprecated, or related;
- historical rows retain the label/version chosen then;
- later recoding is a separate annotation with author and reason;
- free text and raw gestures remain queryable even when no label fits;
- the UI can offer recent/frequent labels without turning frequency into truth.

The product should periodically present a small cluster of confusing or repeated “other”
notes during interviews. It should not interrupt a live trade to demand ontology work.

## 9. Exact quote and hurdle visibility

### 9.1 Before entry

For a proposed size, the action tray must show:

- intended spend and expected token amount;
- venue/route and quote source;
- dynamic protocol, LP, creator, and other fee components;
- price impact, priority/network cost, rent/account-creation effects if applicable;
- quote event/ingest time and staleness;
- minimum received or explicit tolerance;
- capacity or failure warnings;
- what remains unmodeled or uncertain.

A single green “price” is insufficient.

### 9.2 Crackle hurdle

The glass should translate “small profit” into an executable, size-specific hurdle:

    actual acquired tokens
      -> current executable sell proceeds at intended exit size
      - total episode/clip acquisition spend
      - entry and projected exit costs
      = net realizable clip PnL

Before a fill, this is a scenario based on a quote. After a fill, it uses actual acquired
tokens and reconciled costs. The chart can show:

- gross chart movement;
- estimated break-even;
- Ember's selected net-profit target;
- current executable net PnL;
- uncertainty/staleness band.

These lines must not imply an exit can fill at a mark. Changing the retained fraction changes
the sell size, impact, realized clip, and remaining risk; the readout updates together.

### 9.3 Across an episode

The episode accounting panel separates:

- gross spend and proceeds for each inventory interval;
- realized net PnL by clip;
- current remaining basis under a declared accounting convention;
- current size-specific liquidation value;
- recovered capital;
- current economic exposure and opportunity cost;
- costs attributable to exiting and re-entering;
- counterfactual continuous-hold value as a research annotation, not a judgment.

This last comparison is essential because graph-driven exits followed by later re-entry are
part of the policy. The glass should make the behavior measurable without implying it was
mistaken.

## 10. State model exposed by the glass

Inventory, action, attention, and disposition are orthogonal. One giant “position status”
will create contradictions.

### 10.1 Episode and inventory

    SURFACED
       -> WATCHING_FLAT
       -> ENTRY_ARMED
       -> ORDER_PENDING
       -> EXPOSED
            -> PARTIALLY_REDUCED -> EXPOSED
            -> EXIT_PENDING -> WATCHING_FLAT
            -> EXIT_PENDING -> RESOLVED
       WATCHING_FLAT -> REENTRY_ARMED -> ORDER_PENDING -> EXPOSED
       WATCHING_FLAT -> RESOLVED

A failed or expired order returns to an explicit prior attention state. An unresolved order
remains unresolved. A manual transaction observed on chain may create an exposed interval
before the glass can associate intent; association is a reconciliation task, not a guessed
timestamp.

### 10.2 Disposition

Disposition is a time-varying annotation over an episode, not an inventory state:

    unspecified
      -> crackle:<open vocabulary>
      -> runner / might-send
      -> social-catalyst / fancoin
      -> reduce-only
      -> watch-flat
      -> invalidated / resolved
      -> any later revised disposition

Several can coexist when Ember is uncertain. The product records “changed from A to B
because…” without rewriting A.

### 10.3 Action/transaction

Each action renders its own lifecycle:

    gesture recorded -> intent bounded -> quote prepared -> submitted
      -> landed and reconciled
      -> failed before landing
      -> expired/proven dead
      -> unresolved

The UI never uses “done” for both “gesture saved” and “tokens changed hands.”

### 10.4 LP-specific state

LP controls need their own vocabulary: proposed range/weights, open, active-bin-in-range,
partially out of range, inactive, fees accrued/claimed, add pending, partial remove pending,
reweight/rebalance pending, withdrawn, and unresolved. “Remove SOL” must show that withdrawal
returns the assets currently in bins; it does not promise to return the original SOL
composition.

## 11. Textual wireframes

These describe hierarchy and reachability, not pixels.

### 11.1 Desktop trading workspace

    [source health] [wallet/exposure] [hot streams] [recording state] [global search]

    +---------------- market surface ----------------+
    | New | Trending | Live | Callouts | Watch       |
    | filters/sort        [ordering frozen: 8 new]   |
    | coin card                                     |
    | coin card       selected                      |
    | coin card                                     |
    +-----------------------+------------------------+
                            |
    +---------------- coin workbench -------------------------------+
    | identity · lifecycle · episode · current disposition          |
    | chart with quote/hurdle + gesture/social/fill overlays         |
    | [trades] [social threads] [community/identity] [holders]       |
    | source gaps / uncertainty                                     |
    +--------------------------------------+-------------------------+
                                           |
    +---------------- action tray ----------+
    | WATCH FLAT  ARM CRACKLE  ARM FANCOIN |
    | intended size · live hurdle · costs  |
    | TAKE SOME · PROFIT+RUNNER · REDUCE   |
    | ZAP · note/not-articulable           |
    +--------------------------------------+

    [persistent episode/exposure rail:
       exposed | pending | watching-flat | LP | quote freshness | immediate zap]

The market surface and workbench may be side by side on a wide display or switch focus on a
narrow desktop window. Opening a coin never destroys the originating list epoch; “back”
returns to the exact scroll position and frozen ordering.

### 11.2 Focus/replay workspace

    [episode timeline: surfaced -> inspected -> arm -> fills -> flat -> re-entry -> zap]

    [original scene, outcome hidden]   [operator account]
    chart + social + board context      immediate note
    alternatives visible then           retrospective answer
    quote/portfolio state               revised labels

    [reveal subsequent events/outcome]
    [link explanation to exact region/event] [leave unresolved]

### 11.3 Mobile

Mobile is not a shrunk desktop dashboard.

- The default is one surface at a time: feed, coin workbench, or exposure rail.
- The selected coin header and exposure status remain sticky.
- Chart gets the full available width and can temporarily hide secondary overlays.
- Social/context is a swipeable or tabbed lower section, not layered over the chart.
- The action tray is a bottom sheet with the live quote/hurdle always above capital actions.
- Zap remains one obvious, target-specific action, but is separated from scroll edges and
  low-stakes annotation controls.
- The persistent exposure affordance shows count and urgent/stale status; opening it takes
  one tap.
- Hover-only provenance is prohibited. Tap/keyboard focus exposes the same evidence drawer.
- Feed rows freeze position under touch; incoming ranks do not move the target.

Desktop may support keyboard shortcuts after they are explicitly learned. Mobile and
desktop write the same semantic gestures and scene bundles.

## 12. Responsiveness and cognitive load

### 12.1 Reaction budget

The hot path should require:

- one action to focus a candidate;
- one action to express a low-stakes watch or annotation;
- one deliberate action to arm a previously configured bounded crackle;
- one unambiguous action to request a full exit;
- no prose, modal interview, provenance reading, or taxonomy choice before those actions.

Latency should be reported end to end: last market event, screen update, gesture record,
quote creation, submission, landing, and reconciliation. “Fast UI” does not compensate for
a stale feed.

### 12.2 Progressive disclosure

Default cards answer “what is this, why is it here, is it fresh, am I involved?” Expanded
cards answer “what is happening?” The workbench answers “what does the full scene say?”
Evidence drawers answer “where did this claim come from?” Replay answers “what exactly did
I see and do?”

Alerts are reserved for states that change permissible action or threaten an existing
exposure: stale hot stream, unresolved transaction, inventory mismatch, breached capital
bound, or lost venue/quote. Interesting social activity belongs in the feed, not in a red
alarm.

### 12.3 Visual semantic consistency

A value's style conveys evidence class before valence:

- observed;
- derived from identified observations;
- operator-attested;
- machine-interpreted;
- unknown/uncollected;
- stale;
- errored;
- conflicting.

Positive/negative color then conveys economic direction. A machine inference must not
become green merely because it predicts upside.

Every displayed rate shows its relevant denominator. Detailed provenance can live in a
drawer, but freshness and evidence class must be visible without hover.

## 13. Accidental-action safety

The research slice has no transaction capability. If execution is later authorized, the
glass should use asymmetric safety:

- **Arming or increasing risk:** deliberate bounded authorization, with wallet, size,
  duration, venue scope, maximum impact/loss, and remaining capital visible. Larger or
  unusual actions receive more ceremony.
- **Partial exits and LP changes:** explicit amount/composition preview, because “some” and
  “remove SOL” are materially ambiguous.
- **Zap/full exit:** no confirmation dialog and no fake undo. Safety comes from a stable
  target row, target identity inside the control, spatial separation from low-stakes
  gestures, disabled card movement during touch/click, and immediate receipt. It remains
  reachable under stale-data conditions as an explicitly best-effort exit.
- **Re-entry:** a new capital action, never an “undo exit” animation.
- **Keyboard:** shortcuts are scoped to the focused coin, never single printable keys while
  typing, and show the target before sending. A global panic exit cannot share a key family
  with navigation.
- **Mobile:** capital controls do not live on swipe edges or beneath scrolling thumbs.
- **Addresses:** historical identifiers are non-copyable by default; intentional copy or
  paste displays the full resolved identity and provenance to resist lookalike poisoning.
- **Unresolved state:** repeat submission is not offered as the default response to
  uncertainty.

A gesture that the system refuses is still logged with its reason and scene. Refusals are
part of the policy boundary.

## 14. User journeys

### 14.1 Crackle becomes retained runner

1. Ember sees a coin in a parity feed; its exact rank and neighboring cards are preserved.
2. Opening it starts the hot stream and keeps the originating choice set.
3. Ember selects **arm crackle**, optionally chooses an existing crackle label or says
   “other,” and sees the live size-specific break-even and target hurdle.
4. In the research slice this is shadow-only; later it may be a bounded conditional intent.
5. A reconciled fill begins an inventory interval.
6. When executable net PnL supports it, Ember chooses **profit + runner**, selects the
   realized fraction, and optionally says “this might actually send.”
7. The scene and disposition transition are committed. Realized clip and remaining exposure
   appear separately.
8. The runner stays visible without being described as free or already successful.

### 14.2 Graph-driven exit and later re-entry

1. While exposed, Ember sees a chart/social change and presses **zap**, optionally adding an
   immediate fragment.
2. The order lifecycle remains visible until reconciled.
3. On a full fill the episode becomes **watching flat**, not automatically resolved.
4. The chart continues collecting at hot or warm fidelity according to resource policy.
5. Ember later marks another chart region and chooses **re-enter**.
6. A new inventory interval begins inside the same episode.
7. Replay can compare the actual flat interval with continuous holding and the realized
   costs of exit/re-entry, without assuming either policy was superior.

### 14.3 Fancoin/social transition

1. Ember or the system links a coin to a represented person, with evidence and uncertainty.
2. **Watch social transition** opens a notebook containing raw posts, community structure,
   identity candidates, fee-claim events, public participation, and duplicate coins.
3. Ember marks “creator seems aware” or another free-form transition hypothesis.
4. **Arm fancoin** records the expected next transition, horizon, and bounded exposure
   separately from a crackle disposition.
5. Later fee claims, mentions, audience arrival, fragmentation, and market response are
   placed on the same timeline. Machine summaries remain versioned interpretations.
6. Exit, partial retention, or a switch to runner are ordinary episode transitions.

### 14.4 LP opportunity reserve

1. An LP row shows current asset composition, active-bin relation, executable withdrawal
   estimate, fees, and opportunity cost.
2. Ember chooses **partial remove** because SOL is preferred for another opportunity.
3. The preview states which bins/assets are removed and what is expected back; it does not
   promise SOL where token inventory exists.
4. The removal and later reweight/add are distinct actions linked to the same LP episode.
5. Portfolio glass shows the freed capital and forgone LP exposure without merging them
   into spot-trade PnL.

### 14.5 Replay-backed interview

1. After a final zap or explicit resolution, the episode enters the interview queue.
2. The first view replays the original scene with future events hidden.
3. Ember explains attraction, crackle type or unarticulated feel, transition to runner,
   exit, flat watching, and re-entry.
4. The product reveals the later path and asks which account is recollection versus
   hindsight.
5. Proposed new labels can be accepted, rejected, or deferred. Original utterances and
   gestures remain untouched.

## 15. Smallest useful vertical slice

The smallest slice should be a **read-only shadow cockpit used during real manual sessions**.
It does not submit transactions, consistent with the project safety boundary.

It includes:

1. A side-by-side-audited subset of the current Pump daily discovery feeds, with exact
   choice-set, rank, viewport, freeze, and navigation capture.
2. A hot coin workbench with genuine chart/event semantics, raw Pump social context, source
   health, and query-only size-specific buy/sell quotes.
3. A persistent episode rail covering exposed, pending/manual-unreconciled, and
   watching-flat states.
4. Gestures for watch flat, arm crackle in shadow, annotate, partial/profit+runner intent,
   disposition change, zap intent, re-entry intent, and episode resolution.
5. Read-only observation of the named wallet so manual external fills can be reconciled to
   episodes and inventory intervals. Ambiguous association remains visible.
6. Immutable scene bundles at every gesture plus a replay that restores board order,
   chart viewport, social state, quote, portfolio, and utterance.
7. One immediate optional “what changed?” prompt that can be deferred, and one
   outcome-hidden post-resolution interview flow.

Use RADON, EarthCoin, and CRASHIUS only as lifecycle fixtures for the runner state, not as
performance evidence. The next naturally encountered crackles are the prospective test.

The slice is successful if, over several actual sessions:

- Ember can use it as the primary observation surface without material information loss;
- the only required switch is to an external interface for manual execution;
- every manual entry, partial, full exit, flat interval, and re-entry is represented
  correctly or explicitly unresolved;
- a replay is recognizable as what Ember actually saw;
- time-sensitive gestures remain natural enough that logging does not change the policy
  beyond an agreed tolerance;
- missing data and reference-product parity gaps are measurable rather than anecdotal.

It is not successful merely because it stores many events or produces attractive charts.

## 16. Dependencies on other lanes

This glass depends on, but should not dictate:

- **market census and hot-stream capture:** board snapshots, candidate identity, trade,
  reserve, migration, and freshness semantics;
- **social/identity history:** raw Pump posts and relationships, person/wallet/coin identity,
  claims, participation, duplicates, edits, and deletes;
- **episode and accounting model:** fills, lots, inventory intervals, realized clips,
  retained exposure, flat watching, and re-entry;
- **quote/execution research:** size-specific routes, dynamic fees, impact, latency,
  min-received, landing and reconciliation states;
- **attention/causal measurement:** choice-set schemas, scene-bundle rules, privacy,
  prospective estimands, and outcome-hidden replay;
- **LP semantics:** bin composition, add/remove/reweight effects, fee accounting, and
  opportunity reserve;
- **security:** wallet/address identity, poisoning resistance, authorization envelopes,
  refusal behavior, and key separation;
- **storage/provenance:** immutable raw evidence, event/ingest clocks, derived annotation
  versions, conflict and absence states, and deterministic replay;
- **parity operations:** recurring observation of the reference products and product-level
  freshness/coverage objectives.

The dependencies flow both ways: if a source cannot support a visual claim, the glass must
weaken the visual grammar rather than manufacture continuity or precision.

## 17. Failure modes and counterexamples

- **Telemetry theater:** recording pointer motion and dwell without the served denominator
  creates abundant but uninterpretable data.
- **Logger displacement:** if Ember still needs Pump for discovery, the glass observes only
  post-selection leftovers.
- **Dashboard overload:** exposing every provenance field by default slows perception and
  changes the behavior being measured.
- **Premature taxonomy:** forcing every action into five buttons teaches Ember to describe
  the buttons rather than the market.
- **Action collapse:** treating arm, send, fill, disposition, and episode resolution as one
  event destroys timing and causal attribution.
- **Position collapse:** treating a full exit as the end loses flat watching and re-entry,
  one of the explicitly important PnL paths.
- **Mark-price profit:** a green chart PnL that cannot be liquidated at the shown size
  fabricates the crackle.
- **Outcome leakage:** retrospective interviews conducted only after revealing the result
  reward narrative reconstruction.
- **LLM factualization:** storing a social summary instead of its inputs makes later models
  impossible to rerun and disagreements impossible to inspect.
- **Reordering corruption:** a live feed moving under a click can record the wrong selected
  coin.
- **Stale exit illusion:** an always-visible button backed by a minute-old position snapshot
  is not an always-available exit.
- **False parity:** matching field names while missing the media, ranking, community texture,
  or update rhythm that drives attention.
- **Desktop-only instrumentation:** hover provenance and dense sidebars disappear precisely
  when Ember trades from mobile.
- **Safety ceremony on exits:** a confirmation modal measures hesitation introduced by the
  product; safety should be structural around the one-step exit.
- **Universal cockpit ambition:** attempting every feed, book, venue, drawing tool, and
  interview before one end-to-end replay works delays learning while preserving none of it.

## 18. Unresolved questions for reconciliation

- Which Pump surfaces and information cues are actually used in a normal week, and how do
  they differ between desktop and mobile?
- Is a rendered-state/event reconstruction sufficient, or are occasional visual screenshots
  necessary to recover layout-dependent intuition?
- When should a fully flat coin remain a live episode automatically, and when should Ember
  explicitly choose “watch flat”?
- What are the first coarse crackle and disposition labels Ember can use without feeling
  constrained? “Other” and “not articulable” must remain valid regardless.
- Which annotation prompt timing is least disruptive: immediately after gesture, after the
  order resolves, at a lull, or only in the interview queue?
- How long should hot capture continue while flat, and what operator gesture changes its
  resource priority?
- Which quote sizes should be continuously maintained: current configured clip, full
  inventory, standard fractions, or all three?
- How should the product display conflicting creator/person identity evidence without making
  impersonation appear as uncertainty about a verified identity?
- Can parity be evaluated with recorded comparison sessions if Pump's ranking is personalized
  or ephemeral?
- Which actions, if any, may eventually be one-click after bounded playbook arming? This lane
  specifies semantics, not authorization.
- How are simultaneous spot, runner, fancoin, and LP dispositions allocated to portfolio
  budgets without visually collapsing their PnL?
- What level of mobile reaction speed is genuinely required, and should the first slice be
  desktop-first while preserving semantic mobile compatibility?

## 19. Recommendation

Build the read-only vertical slice before designing the polished engine room or a learned
policy. Begin with faithful discovery, hot inspection, episode/exposure state, exact quote
semantics, natural gestures, and recognizable replay. Treat every screen element as either
part of the operator's sensorium or part of the measurement apparatus; if it is neither, it
probably does not belong in the first slice.

The decisive design test is not “does the dashboard contain our metrics?” It is:

> Can Ember naturally notice, inspect, arm, partially realize, retain, exit, watch while
> flat, re-enter, and later explain a coin here—and can we reconstruct what was knowable at
> each transition without pretending the early vocabulary was complete?

