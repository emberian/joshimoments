# Lane 01: episode, inventory, and accounting semantics

Status: exploratory proposal for reconciliation; not an architecture decision.

## Executive finding

The accounting object should be an **episode**, while the financial source of truth should be an
append-only household asset ledger. Those are related but not interchangeable.

An episode is the continuity of Ember's attention, intent, and evolving treatment of one coin. It
may contain several buys, partial sells, a retained runner, a graph-driven full exit, time spent
watching while flat, and a later re-entry. A position or flat-to-flat round trip is therefore too
small. Conversely, a lifetime record keyed only by mint is too large: Ember can later approach the
same coin for an unrelated reason.

The proposed central separation is:

```text
immutable household asset events          immutable operator/observation events
buys, sells, transfers, fees, fills        scenes, gestures, attention, annotations
                 \                         /
                  \                       /
                   episode attribution links
                            |
             replayed accounting and study views
```

The raw asset ledger must balance without an episode assignment. Episode and strategy attribution
may be incomplete or disputed without corrupting wallet totals. This matters when a manual trade
arrives without a recorded gesture, when tokens move between Ember's wallets, or when a new
crackle-sized buy is placed on top of an existing retained runner.

The primary live PnL view should use average cost within each flat-to-flat inventory epoch because
that is the operational number Ember is likely to react to. Acquisition lots must nevertheless be
preserved exactly, and any attribution of a partial sale to a runner tranche or a newer crackle
tranche must be explicit. At full closure the total cash-flow result is independent of the lot
convention; before closure, “realized PnL” is convention-dependent and must say which convention
produced it.

Most importantly, **flat is an inventory state, not an episode boundary**. The period in which Ember
has sold after reading the graph, continues watching, and re-enters later is part of the policy and
must remain observable.

## Scope and non-goals

This lane covers spot-token episodes:

- entries and additional entries;
- partial exits and profit recognition;
- retained exposure and later disposition changes;
- graph-driven full exits;
- continued observation while flat and later re-entry;
- multiple acquisition lots and, when needed, logical management tranches;
- realized PnL, remaining basis, executable liquidation value, and opportunity-cost views;
- failure and missing-data semantics needed to keep these numbers honest.

LP positions need a related but distinct inventory ledger because an LP withdrawal returns a basket
and “closed” does not mean “converted to SOL.” Fancoin and social-transition positions use this spot
accounting once they trade, but their social state machine belongs in another lane. Tax-lot reporting
is also not the purpose of this model.

## What the compost establishes

Several useful constraints are already present in `joshibot`, although no existing component has
the complete object required here.

1. The sentinel correctly noticed that a balance returning to zero must kill mint-keyed runtime
   trail state, and that a later acquisition is a new lot generation
   (`~/dev/joshibot/shitcoims_sentinel/lots.py:1-6`, `:76-92`, `:130-146`). That is a sound
   **inventory-epoch** rule. It is not an episode rule: it loses the continuous flat-watch/re-entry
   behavior now in scope.

2. The sentinel now reconstructs basis only from observed on-chain acquisitions and refuses to
   manufacture it from a current exit quote
   (`~/dev/joshibot/shitcoims_sentinel/engine.py:66-77`, `:212-300`). It also preserves a
   per-unit entry price through a partial scale-out (`:108-116`). Those are valuable invariants.
   However, the reconstruction collapses all acquisitions in the current non-flat interval to one
   average and does not account for realized proceeds or an episode spanning a later flat interval.

3. The older intelligence PnL module already represents exact acquisition lots, unknown transfer
   basis, same-slot ambiguity, balance mismatches, and full-balance executable quotes
   (`~/dev/joshibot/shitcoims_intelligence/pnl.py:28-55`, `:57-105`, `:108-173`). It is a
   useful failure-semantics donor. Its FIFO disposal rule (`:304-355`) should not silently become
   the operator-facing meaning of profit recognition.

4. The market-wide unrealized-PnL study gives a strong reason to retain an average-cost view. It
   identifies a buy from flat as the natural basis-reset boundary and describes why average cost,
   rather than FIFO, is the PnL representation retail front ends and presets expose
   (`~/dev/joshibot/studies/RESULT_unrealized_pnl.md:79-108`). It also measured material
   FIFO/average-cost disagreement in the repeatedly scaled tail (`:182-195`). This supports storing
   raw lots and naming the accounting projection rather than declaring one projection reality.

5. The hunch tape contains the right beginnings of an operator event log: append-only gestures,
   separate gesture and ingest clocks, and a zap whose state records what the instrument showed
   when Ember decided to leave (`~/dev/joshibot/shitcoims_paperdesk/hunch.py:1-59`,
   `:104-139`, `:288-328`). The operator paper book also correctly separates the zap decision from
   the later executable observation/fill (`~/dev/joshibot/shitcoims_paperdesk/operator.py:271-292`).
   It models only one entry and one terminal close, however; no partial realization, retained runner,
   flat watch, or re-entry exists in the paper position.

6. The paperdesk ledger learned that partial-looking rows are worse than absent rows and that
   censoring must be recorded rather than silently dropped
   (`~/dev/joshibot/shitcoims_paperdesk/ledger.py:11-38`). We should keep its two-clock,
   append-only discipline, but its close row requires one positive spend and one terminal proceeds
   number (`:144-230`), which cannot express an episode with several fills and flat intervals.

7. The lifetime position reconstruction proves that exact raw-unit accounting and a household
   boundary are achievable. It reconciled all five wallets to chain balances and found that internal
   transfers previously booked as income net to zero
   (`~/dev/joshibot/studies/RESULT_position_history.md:18-51`, `:76-127`). It also shows why
   classifying transaction plumbing is not a minor parser detail.

8. Current realized-performance reporting is not adequate for this project. The sentinel history
   summary calls the sum of sell outputs “realized” without subtracting acquisition cost or fees
   (`~/dev/joshibot/shitcoims_sentinel/history.py:63-85`), and the trade CSV contains only
   exit time, input amount, reported output, reason, and signature
   (`~/dev/joshibot/shitcoims_sentinel/executor.py:161-179`). These records cannot answer
   which episode, lot, disposition, or decision scene produced a result.

These are donor organs, not a schema to copy wholesale.

## Proposed vocabulary

### Household boundary

The versioned set of wallets and token accounts treated as Ember's portfolio for a given time.
Moving SOL or tokens between members of this set is not income, expenditure, acquisition, disposal,
or realization. It changes custody only and preserves basis provenance.

The set must be time-versioned. Adding an old wallet retrospectively can reclassify what previously
looked external, but it must do so through a versioned interpretation rather than rewriting raw
chain events.

### Episode

A durable identity for one continuous line of operator attention and intent toward a subject,
usually one mint. It begins with an explicit operator gesture when available; a discovered manual
fill may create an unattributed provisional episode. It ends only with explicit resolution,
withdrawal, or a later adjudication—not merely when inventory reaches zero.

An episode can contain:

- zero or more execution attempts;
- zero or more inventory epochs;
- multiple attention intervals, including intervals while flat;
- multiple dispositions and disposition transitions;
- annotations during the episode and a replay-backed postmortem after resolution.

`episode_id` must not be derived from mint, wallet, or transaction signature.

### Inventory epoch

A maximal interval during which aggregate household quantity in the mint is economically non-flat.
Normally it begins when reconciled quantity moves from zero to positive and ends when it returns to
exactly zero. It is a basis-reset boundary, not necessarily an episode boundary.

Exact chain-flat and economically-flat are different:

- **chain-flat:** aggregate raw quantity is exactly zero;
- **economic dust:** quantity remains, but no route exists or liquidation is below a declared dust
  threshold;
- **unknown:** observations are insufficient to establish either.

An episode may resolve with dust still present, but the portfolio must continue showing the residual.
The system may never call such a state a full fill or a zero exposure.

### Acquisition lot

The exact raw token quantity acquired by one economically coherent event, with acquisition
signature, slot/order, wallet, route, actual consideration, separately attributable execution cost,
quality, and remaining quantity. Lots preserve provenance even when the main display projects them
to average cost.

An acquisition by transfer has carried basis only when that basis can be traced across the household
boundary or explicitly attested. Unknown does not mean zero. A verified promotional airdrop may have
zero acquisition cost, but “airdrop” must be an evidence-backed classification.

### Management tranche

A logical allocation of some fungible inventory to a current disposition or playbook, for example:

- the retained runner left from an initial crackle;
- a fresh crackle clip bought while that runner still exists;
- a fancoin/catalyst allocation on the same mint.

A tranche is not an SPL token account and not necessarily a tax lot. It is an attribution claim. A
sale can be linked to a tranche only if the operator or the pre-authorized action says which tranche
it manages. If that link is absent, household PnL remains exact while per-disposition PnL is
`unallocated`, not guessed.

### Inventory interval

For analysis, a maximal span in which a particular tranche has positive assigned quantity. Several
tranche intervals may overlap inside one household inventory epoch. “Time in market” can therefore
be calculated at household, episode, or tranche level, and the denominator must be named.

### Attention interval

A measured span during which the coin was visible or deliberately monitored. At minimum distinguish:

- surfaced on a board;
- in viewport;
- chart/detail opened;
- focused/actively interacted with;
- background watch armed;
- not observed because the instrument had a gap.

Calendar time while flat is not automatically “watched flat.” The latter is the union of measured
attention/background-watch intervals during a flat inventory state.

### Disposition

Ember's current intended treatment of an episode or tranche. It is not inferred from quantity. A
partial sell and `promote remainder to runner` are separate events; either may occur without the
other. Early vocabularies should be versioned, allow free text, and remain replaceable.

### Execution objects

Keep these distinct:

| Object | Meaning |
|---|---|
| action gesture | what Ember asked for, when, and from which scene |
| conditional authorization | the bounds under which automation may act later |
| trigger observation | the state that satisfied those bounds |
| quote | a size-, route-, slot-, and time-specific executable estimate |
| transaction attempt | exact signed bytes/signature or a failed pre-submit attempt |
| chain outcome | landed success, landed failure, expired, or still unresolved |
| fill | reconciled asset deltas actually attributable to the trade |
| inventory effect | the change in household quantity after internal edges are netted |

A submitted signature is not a fill, a balance decrease alone is not proceeds, and a vendor's
reported output is not a substitute for reconciling the chain asset deltas.

## Episode boundaries and overlap

The default interaction rule should be one open episode per `(household, mint)`. This keeps normal
use simple while still permitting several tranches inside it. Buying a new crackle clip on top of a
runner usually creates a new tranche and another entry phase in the same episode.

The operator may explicitly split a genuinely independent thesis into another episode. Overlapping
episodes on the same fungible mint are allowed only when their inventory allocations are explicit.
Otherwise the second episode can carry observations and intent, but its PnL attribution remains
unallocated. The system should never invent a mapping merely to make a per-strategy chart add up.

Suggested boundary behavior:

```text
episode.opened
    -> observing_flat
    -> entry_armed
    -> exposed
    -> partially_reduced / disposition_changed / added
    -> flat_but_observing
    -> reentry_armed
    -> exposed
    -> episode.resolved
```

This diagram is descriptive, not one giant persisted enum. Episode lifecycle, inventory, attention,
disposition, and execution are orthogonal projections. Conflating them creates impossible states
such as “the episode closed, but its exit transaction is unresolved” or “the position is a runner,
therefore the user must have taken profit.”

No inactivity timeout should silently end an episode. A timeout may mark it `dormant` or request an
operator decision. Resolution remains explicit, and a correction/reopen is appended if the operator
later explains that a supposedly resolved episode actually continued.

## Minimal event language

The eventual implementation may use different names, but the research record needs at least the
following semantic events.

### Operator and episode events

- `episode.opened`, with subject, initiating scene, utterance, and whether the episode was recorded
  prospectively or reconstructed later;
- `episode.linked` or `episode.split`, preserving the previous interpretation rather than editing it;
- `attention.changed`, with visibility/focus/watch mode and both client and ingest clocks;
- `action.requested`, including enter, add, reduce, take-profit-and-keep, full exit, re-enter, zap,
  cancel, and no-action annotations;
- `authorization.armed`, changed, expired, cancelled, or consumed;
- `disposition.changed`, scoped to episode or tranche, with previous value, new value, free text,
  confidence, and horizon;
- `episode.resolved`, with resolution reason and whether inventory remains as dust/unattributed;
- `interview.recorded`, linked to the replayed scene and labeled immediate or retrospective;
- `correction.appended`, which supersedes an interpretation without deleting the original event.

### Market and execution events

- raw quote observations, including the full input size, expected and minimum output, route/venue,
  reserves or state version, fee configuration, quote slot, received time, and expiry;
- trigger observations and the policy/authorization version they satisfied;
- transaction built, simulated, signed, submitted, rebroadcast, landed-success, landed-failure,
  expired, or unresolved;
- reconciled asset deltas and fee/rent/tip decomposition;
- balance snapshots used to prove ledger completeness;
- observation gaps and venue migrations.

### Attribution events

- fill assigned to episode;
- acquisition quantity assigned to or moved between management tranches;
- disposal assigned to a tranche or explicitly left unallocated;
- manual transaction intent later attested by Ember;
- external transfer classified, with evidence and confidence.

Attribution is append-only metadata over financial facts. Changing an episode label must not alter
the wallet balance or recompute what actually landed.

## Clocks and order

Every decision-sensitive event should carry the clocks it genuinely has, never substitutes:

- chain slot and transaction index, when known;
- chain block time, when available;
- source event time, such as a post time;
- operator gesture time on the client;
- persistence/ingest time;
- server receipt time;
- UI render or viewport time where interaction latency is under study.

Events in one transaction are atomic for portfolio accounting even if their instruction order can be
decoded. Different transactions in the same slot need transaction index before they can be ordered;
otherwise their relative order is explicitly ambiguous. The old PnL module already flags missing
same-slot order rather than sorting by signature and pretending (`shitcoims_intelligence/pnl.py:230-277`).

## Financial ledger and classification

All token quantities remain raw integers and all SOL quantities remain lamports in the source ledger.
Decimal/UI conversions are display projections. Each chain transaction should first produce a set of
asset deltas at the household boundary; only then should those deltas be classified.

For a spot acquisition, distinguish:

- token quantity received;
- trade consideration paid, including venue economics embedded in the swap;
- base/priority fees and tips irreversibly paid;
- account rent deposited, which may later be recovered and is not silently treated as either PnL or
  spend;
- creator cashback or other later rebate actually received by the household;
- unrelated actions bundled into the same transaction.

For a disposal, distinguish actual trade proceeds from rent refunds, transfers, rebates, and other
program movements. A failed transaction may create an execution expense but no token fill. A
multi-action transaction whose economics cannot be allocated must remain partially unclassified.

Transfers have their own semantics:

- household-internal: custody movement, carrying lot provenance and no realization;
- external gift or payment: a token disposal with no sale proceeds, kept separate from trading PnL;
- incoming known-basis transfer: acquisition with carried basis;
- incoming verified zero-cost airdrop: acquisition with zero basis and explicit provenance;
- incoming unknown: quantity known, basis unknown, PnL not fully available.

## The accounting projections

### 1. Exact inventory identity

For mint `m` at event boundary `t`:

```text
Q_m(t) = sum(external acquisitions and buys)
       - sum(external disposals and sells)
```

Household-internal transfers cancel. `Q_m(t)` must equal independently observed aggregate household
balances or carry a visible gap. No episode assignment is needed for this identity.

### 2. Average-cost operational view

Within one inventory epoch, let `Q` be raw quantity and `B` be remaining economic basis in lamports.
For an acquisition of `dQ` with attributable cost `C`:

```text
Q' = Q + dQ
B' = B + C
b' = B' / Q'
```

For a sale of `sQ` with actual net proceeds `P`, under the named `average_cost` projection:

```text
allocated_basis = B * sQ / Q
realized_delta  = P - allocated_basis
Q'              = Q - sQ
B'              = B - allocated_basis
```

Sells do not change the remaining unit basis `b`. If `Q' = 0`, then `B'` must also be zero and a
later acquisition begins a new inventory epoch with a fresh unit basis. Rounding residue must use a
documented exact allocation rule so the final sale consumes the remaining basis exactly.

This is the recommended primary live view, not a claim that average cost is the only valid lot
projection.

### 3. Provenance-lot and tranche views

Every acquisition lot remains available for FIFO, LIFO, specific-identification, and sensitivity
analysis. A management-tranche view uses explicit quantity-allocation events. It answers questions
such as “did the fresh crackle clip work while the older runner remained?” that a blended average
cannot.

If a sell was not assigned to a tranche, the system may show household and episode totals but must
not choose “newest clip first” after seeing which attribution looks best. Any default rule used for
automation must be declared before the sale and recorded on the authorization.

### 4. Realized PnL

“Realized PnL” must always identify scope, reference asset, fee treatment, and lot projection:

```text
realized_pnl[episode, SOL, average_cost, net]
```

At a partial exit this number depends on basis allocation. At a fully flat inventory epoch with only
known-basis trades, the epoch total becomes convention-independent:

```text
flat_epoch_pnl = all actual sale proceeds
               - all actual acquisition consideration
               - irreversible execution expenses
               + attributable rebates
```

The sum of per-sale realized deltas must equal this cash-flow identity when the epoch becomes flat.
Across an episode with several flat-to-flat epochs, episode realized PnL is the sum of their results
plus any open epoch's realized component.

### 5. Cash recovery

Ember's phrase “recognize a small profit and keep the remainder” needs two simultaneous quantities:

- **allocated realized PnL:** proceeds less the basis allocated to the units sold;
- **net trade cash returned:** cumulative sale proceeds less cumulative acquisition cash and
  standalone execution expense so far.

They are not the same. A partial sale can realize profit on the sold units before returning all cash
deployed, or can return all cash deployed while the remaining inventory still has a nonzero economic
basis. The interface should say `initial cash recovered` or `cash surplus before remaining inventory`,
never “free coins.”

### 6. Executable liquidation value and unrealized PnL

For exact current quantity `Q`, a fresh full-size exit quote provides:

```text
expected_liquidation_value = quoted_expected_output - costs not already in quote
minimum_liquidation_value  = quoted_minimum_output - costs not already in quote
executable_unrealized_pnl   = liquidation_value - remaining_basis
episode_total_if_liquidated = realized_pnl + executable_unrealized_pnl
```

This is a quote observation, not a balance-sheet fact. It must carry age, slot, amount, route,
slippage/minimum, and quote-health status. The chart mark may be shown as market context, but it must
not be labeled liquidation value. A quote for one token cannot be linearly scaled to the full bag.

The expected and minimum views answer different questions. The minimum is only meaningful if the
transaction could still be landed under the same state; a stale `minOut` is not a guarantee.

### 7. Remaining downside and exposure

For a long spot bag with no debt, current capital exposed to a collapse is approximately its current
executable liquidation value, not its historical basis. Prior realized profit does not make that
market value non-economic. Report both:

- current quantity and liquidation value at risk;
- remaining accounting basis;
- episode realized result;
- total episode result if liquidated now.

### 8. Reference currencies

Pump-native trade accounting should close first in lamports/SOL. USD is a versioned valuation view
with its own price source and timestamp. A USD re-quote must never mutate the SOL ledger. If the
question becomes whether trading beat simply holding SOL, that is an opportunity-cost comparison,
not a correction to SOL PnL.

## Opportunity cost is a family of estimands

There is no single observable called “opportunity cost.” At least four useful versions exist:

1. **Capital occupancy:** integral of SOL-equivalent capital committed to the episode over time.
   This can be computed from actual cash deployed or, for a liquidation-aware view, from fresh
   executable value. The choice must be named.

2. **Declared benchmark regret:** the difference from a benchmark selected without future
   knowledge, such as holding SOL, entering immediately rather than waiting for the microdip, or
   selling fully rather than retaining the runner. Both legs pay realistic friction and use only
   information available at the decision time.

3. **Contemporaneous alternative regret:** the result of surfaced-but-skipped alternatives from the
   recorded choice set. This is a shadow counterfactual, not money Ember “would have made.” It must
   account for whether capital, attention, and execution capacity were actually available.

4. **Attention return:** episode value per measured minute of focused or background-monitoring
   attention. Calendar holding time is not a substitute for attention time.

The ex-post best price, best coin, or perfect exit is not a legitimate benchmark. “Missed the peak”
is a descriptive path statistic, not opportunity cost. Benchmark definitions and versions must be
fixed before outcome inspection for confirmatory claims.

Capital constraints introduce a particularly valuable event: an otherwise eligible action that was
not taken because capital remained in runners or LP inventory. Recording the blocked action permits
a realistic portfolio-level comparison later. Without that record, claims about forgone opportunity
are hindsight stories.

## Orthogonal state projections

Persist events; derive these views.

### Episode lifecycle

```text
provisional -> open <-> dormant -> resolved
                 ^                  |
                 +---- reopened <---+
```

`provisional` means a fill or holding was discovered before its operator intent was known. `dormant`
means no current attention was observed; it does not mean the thesis ended. Reopen and correction are
append-only acts.

### Household inventory

```text
flat -> transition_uncertain -> exposed -> transition_uncertain -> flat
```

`transition_uncertain` covers a submitted but unresolved transaction or a stale/incomplete balance
view. Partial exit remains `exposed` with lower quantity. Dust is a flag on exposed inventory, not a
fabricated flat state.

### Execution

```text
requested -> armed -> triggered -> built -> submitted
                                      |         |-> landed_failed
                                      |         |-> expired
                                      |         |-> unresolved
                                      |         `-> landed_success -> reconciled_fill
                                      `-> failed_before_submit
```

Cancellation and expiry can occur before submission. No replacement action may assume an unresolved
signature failed.

### Attention

```text
not_visible -> surfaced -> viewport -> focused
                    \          \        /
                     +---- background_watch
```

Observation gaps are explicit intervals. They are not transitions back to `not_visible`, because
the system not observing Ember is different from Ember not observing the coin.

### Disposition

Disposition is a versioned label plus free-form context, not a closed universal automaton. Early
values may include `crackle`, `retained_runner`, `send_candidate`, `social_transition`, `reduce`,
`exit_now`, and `watch_flat`, but the data contract stores the vocabulary version and verbatim
operator language.

## Required invariants

### Ledger invariants

1. All source quantities are exact integers in native units; display conversions do not feed back.
2. For every mint, reconstructed household quantity equals independent finalized balance snapshots
   or exposes a quantified gap.
3. Internal household transfers net to zero and preserve lot provenance.
4. Every acquisition quantity is either assigned a known/estimated basis with provenance or marked
   unknown; no quote may construct historical basis.
5. Every disposal consumes no more quantity than is available. Underflow taints the projection and
   cannot be repaired with a synthetic lot hidden from the user.
6. A failed transaction changes inventory only if reconciled chain deltas show that it did; any paid
   fee remains an expense.
7. Full closure consumes all remaining basis exactly. The flat-epoch PnL equals net trade cash flow
   to the native unit.
8. Household accounting totals never depend on episode, disposition, or tranche attribution.

### Episode invariants

9. Inventory becoming flat does not close an episode.
10. A later re-entry never inherits the prior inventory epoch's unit basis, peak, stop, or trailing
    state.
11. A partial fill is not a disposition transition; a disposition transition is not a fill.
12. “Full exit” names intent until finalized balances establish the actual remaining quantity.
13. One fill may be attributed at most once at each accounting scope. Split allocation quantities
    must sum exactly to the fill quantity.
14. Overlapping episode/tranche attribution never alters the household inventory identity.
15. Retractions and corrections append; they do not delete financial facts or prior utterances.

### Valuation invariants

16. An executable quote matches the exact quantity it values and records route, slot/time, fee
    assumptions, and freshness.
17. Missing route is `unknown/unquotable`, not zero. Zero is permitted only with evidence supporting
    an unsellable/dead valuation assumption, and the assumption is labeled.
18. A chart mark, last trade, expected quote, minimum quote, actual fill, and post-fill balance are
    separate values.
19. Realized, unrealized, and total PnL always name basis convention, fee treatment, scope, and
    reference asset.
20. USD and benchmark views carry valuation sources and do not rewrite native-unit results.

### Temporal invariants

21. Intent time, trigger time, submission time, chain order, reconciliation time, and display time
    are not collapsed.
22. A counterfactual uses only information available at its decision boundary; later enrichment is
    versioned separately.
23. Observation gaps and stale quotes remain visible in duration and performance denominators.

## Counterexamples the model must pass

### A. Partial profit plus retained runner

Ember buys 100 tokens for 1 SOL, then sells 40 for 0.8 SOL and retains 60. Ignoring additional fees
for the arithmetic:

```text
average unit basis       0.01 SOL
realized PnL             0.8 - 0.4 = +0.4 SOL
remaining basis          0.6 SOL
cash returned vs spent   0.8 - 1.0 = -0.2 SOL
```

If the remaining 60 can currently liquidate for 0.9 SOL, executable unrealized PnL is +0.3 SOL and
total-if-liquidated is +0.7 SOL. The runner has 0.9 SOL of current value at risk. Calling it “free”
would hide both its value and opportunity cost.

### B. Cash recovered does not erase remaining basis

Ember buys 100 for 1 SOL and sells 60 for 1.2 SOL. Cash deployed has been recovered with a 0.2 SOL
surplus, while average-cost accounting still assigns 0.4 SOL basis to the remaining 40. This is not
a contradiction; it is why cash recovery and allocated realized PnL are separate displays.

### C. Full exit, flat graph watching, and re-entry

Ember buys, exits after reading the chart, watches flat for eleven minutes, and re-enters lower. This
is one operator episode containing two inventory epochs. The first epoch is fully realized; the
second begins with fresh basis. A position-keyed system splits the behavior and loses the avoided
drawdown/re-entry timing. A lifetime mint basis blends unrelated capital and corrupts both epochs.

### D. Exit intent versus fill

Ember presses zap while the visible executable quote implies +1.5%. The transaction lands four
seconds later at -0.3% after fees. The episode records the scene and intended exit, but accounting
uses the reconciled fill. The 1.8 percentage-point gap is execution/latency evidence, not operator
PnL.

### E. Fresh crackle on top of a runner

An old 60-token runner remains. Ember buys 30 more tokens for a new microdip crackle and later sells
30. Household average-cost PnL is computable, but whether the sale closed the new clip or trimmed the
runner is a management attribution. If the action authorization said `sell new crackle tranche`, use
that. If not, the tranche result is unknown; do not choose LIFO after seeing the outcome.

### F. Partial exit without promotion

Automation takes 25% profit according to a pre-authorized scale rule, but Ember still considers the
whole remaining thesis a crackle. No runner transition should be inferred. Conversely, Ember may
promote a position to `send_candidate` without selling anything.

### G. Internal wallet movement

Tokens move from `shitcoims` to another controlled wallet. The source wallet goes flat, but household
inventory and the inventory epoch continue with carried basis. Wallet-local accounting alone would
fabricate a disposal and an unknown-basis acquisition.

### H. Unknown incoming basis

A balance is discovered after the observer was offline, or tokens arrive from an uncontrolled
wallet. Quantity and current executable value can be known while realized/unrealized PnL remains
unknown. Stamping the current quote as basis would manufacture a zero-PnL starting point—the precise
failure the old sentinel learned to reject.

### I. Quote absence versus economic death

The route service times out for a healthy coin. Liquidation value is missing/stale, not zero. A
different coin has finalized evidence of drained liquidity and no reachable venue; a pessimistic
zero mark may be a labeled scenario. These cases must not share the same numeric representation.

### J. Failed or unresolved sell

A sell transaction lands failed and burns a priority fee. Inventory remains, the episode incurs an
execution expense, and a retry may be allowed. If signature state is unresolved, inventory is
`transition_uncertain`; neither a second sell nor a full-exit record is justified.

### K. Dust after “sell all”

A route sells almost all tokens and leaves an unsellable residue. The gesture was a full-exit intent,
the fill was partial relative to exact inventory, and the episode may be intentionally resolved with
dust. The residual must remain in household exposure and cannot silently inherit a later episode.

### L. Manual trade outside the cockpit

Ember buys or sells in Pump/Padre while the recorder sees only chain effects. The financial event is
exact and creates or changes inventory. The episode link, seen scene, and reason are missing until an
optional attestation; the system must not infer that the trade was an automated crackle.

## Missing-data semantics

Use explicit quality and absence states rather than `null`/zero overloading.

| State | Meaning | Example |
|---|---|---|
| known | directly observed and reconciled | finalized raw balance delta |
| known absent | the concept is applicable and did not occur | no token fill in a failed tx |
| unknown | it may exist, but evidence is insufficient | basis before observer coverage |
| not applicable | the field has no meaning here | sell proceeds for an internal transfer |
| estimated | produced by a named approximation | future network cost on a quote |
| stale | once observed, no longer current enough | 20-second-old microcap exit quote |
| censored | outcome could not be observed through horizon | venue/feed disappeared |
| ambiguous | several interpretations fit evidence | multi-action transaction allocation |
| disputed | operator/source interpretations conflict | whether two gestures share an episode |
| retracted | a prior human interpretation was taken back | mistaken runner promotion |

Specific rules:

- No basis means PnL is unknown, not zero. Known-basis and unknown-basis quantities may be shown
  separately without summing them into a false total.
- No exit quote means liquidation value is unavailable. Preserve the latest quote as stale history,
  but do not present it as current.
- Missing gesture context means the financial trade remains valid and operator-policy attribution is
  unknown.
- Missing viewport telemetry means `attention unobserved`, not `operator ignored coin`.
- A later interview may explain an earlier act but cannot retroactively become contemporaneous
  evidence. It is a new event with a link to the old scene.
- A balance mismatch is a first-class defect with magnitude and affected interval. Reconciliation
  cannot silently insert a zero-cost synthetic acquisition.
- When only part of a bag has known basis, provide known-subset quantities and bounds only if their
  assumptions are explicit. Do not label the subset result total PnL.

## What “high resolution” means for this lane

Accounting resolution is not just faster price sampling. For every meaningful action we need:

- the complete pre-action household quantities and liquid SOL;
- all active lots, tranche allocations, dispositions, and pending authorizations;
- the exact candidate/scene and chart state that provoked the gesture;
- the gesture time and requested size/fraction;
- the first executable quotes after gesture and trigger;
- transaction construction, simulation, submission, landing, and reconciliation clocks;
- actual asset deltas, fees, rent changes, and remaining balance;
- continued attention state while exposed or flat;
- later disposition changes and immediate/retrospective explanations.

This lets later work decompose entry selection, waiting for a dip, execution, partial-profit choice,
runner retention, graph-driven exit, flat avoidance, and re-entry. Without it, a round-trip return
collapses all of those mechanisms into one number and cannot identify what Ember actually did.

## Research questions before schema commitment

1. How does Ember decide that a flat re-entry belongs to the same ongoing episode rather than a new
   encounter? Which one-tap default is least intrusive, and when should the system ask?
2. When a retained runner receives a new crackle-sized buy, does Ember normally think in separate
   clips, blended inventory, or both depending on intent?
3. On a partial sell, does Ember's felt “profit recognized” track average-cost realized PnL, cash
   recovered, the fate of the newest clip, or a combination? Which values should be prominent versus
   available on drill-down?
4. Can dispositions apply to token quantities, or are they normally beliefs about the whole coin?
   How often will per-tranche disposition be worth the interaction cost?
5. What is the household boundary for V1, and are any exchange/custodial addresses intended to carry
   basis across the boundary?
6. Should SOL be the only primary accounting numeraire for Pump trades, or does Ember make some
   decisions in USD cash terms that need simultaneous prospective capture?
7. Which opportunity-cost comparisons are actionable to Ember: hold SOL, take full profit, another
   surfaced coin, retain a liquid reserve, or something else?
8. What level of viewport/focus logging captures attention without producing intolerable noise or
   creating false precision about cognition?
9. How should background watch time be weighted relative to active graph inspection when estimating
   value per attention-hour?
10. How reliably can Pump, PumpSwap, aggregator, transfers, rent, cashback, and bundled transactions
    be decomposed from the exact wallet history? Which classes remain ambiguous?
11. Can transaction index and complete token-account closure be obtained prospectively at low enough
    latency while still allowing a later finalized correction?
12. How should dust be treated in exposure limits and episode resolution without allowing forgotten
    residuals to disappear?
13. What does “opportunity unavailable because capital was tied up” require from the portfolio and
    candidate-choice-set lanes?
14. For the present `RADON`, `EarthCoin`, and `CRASHIUS` holdings, is acquisition history complete,
    and can the earlier partial proceeds and current retained quantities reconcile exactly?

## Smallest useful experiment

Do not start by implementing a generalized portfolio service. Run one **episode-accounting
falsification slice** around the three named retained positions and the next naturally occurring
flat-exit/re-entry episode.

### Subjects

- `RADON`, `EarthCoin`, and `CRASHIUS`: reconstruct the complete current inventory epochs, all
  acquisitions, partial disposals, actual proceeds, current retained quantities, and basis quality.
- The next coin on which Ember naturally exits while watching and later considers or performs a
  re-entry: capture it prospectively as one episode, whether or not the re-entry occurs.

### Minimal apparatus

1. Read-only chain reconstruction for the `shitcoims` household scope, using exact token-account
   closure and asset deltas. No signer or transaction submission.
2. A tiny append-only gesture record with episode ID, mint, gesture (`enter`, `reduce`, `full_exit`,
   `continue_watching_flat`, `reenter`, `promote`, `zap`), optional quantity/fraction, verbatim note,
   client time, and persistence time.
3. Full-size executable exit-quote snapshots on every gesture and periodically while the coin is
   focused or background-watched, with explicit stale/gap records.
4. A manual episode-link/split correction mechanism; no automatic ontology learning yet.
5. A readout showing exact holdings, average-cost basis, realized PnL, cash recovery, remaining basis,
   expected/minimum liquidation value, total-if-liquidated, flat-watch duration, and quality flags.

### Required scenarios

- at least one partial disposal with nonzero retained inventory;
- at least one disposition change independently recorded from a fill;
- at least one full-exit intent whose actual remaining balance is checked;
- at least one measured interval flat while the same episode remains open;
- a re-entry if it occurs naturally—never deploy capital just to satisfy the fixture;
- one quote/feed gap to verify missing is not rendered as zero;
- one manual correction or attestation to prove append-only reinterpretation works.

### Pass conditions

- Current raw token and SOL balances reconcile exactly to finalized chain state.
- Every acquisition, disposal, and irreversible execution expense is either classified or visibly
  unresolved; no residual is hidden in “other.”
- At every full-flat boundary, calculated epoch PnL equals net epoch trade cash flow to the lamport.
- A re-entry starts fresh epoch basis while episode-level realized PnL and flat-watch evidence remain.
- Partial-exit metrics explain, without contradiction, both profit recognized and cash recovered.
- The readout refuses total PnL when basis or quote coverage is incomplete.
- The operator can inspect the episode replay and say whether the segmentation and labels match what
  they meant. A mismatch is a result, not a UX failure to smooth over.

### Falsifiers

- We cannot reconstruct the named holdings without unbounded manual basis entry.
- Household balances fail to reconcile after complete token-account closure.
- The gesture burden changes or interrupts the behavior we are trying to measure.
- Ember cannot give a stable meaning to episode continuity even during replay; if so, episode links
  may need to remain post-hoc hypotheses rather than live required fields.
- Management-tranche attribution is usually unknowable or feels artificial; if so, keep lots and
  household/episode totals but postpone per-disposition PnL.

The experiment is informative even if no strategy is profitable. Its purpose is to establish that
the apparatus can represent the behavior and close the books.

## Dependencies on other lanes

### Inputs required

- **Event tape and clock discipline:** immutable IDs, append-only correction, gap events, and causal
  availability boundaries.
- **Wallet/chain reconstruction:** full account-key resolution, token-account closure, program-aware
  trade/transfer/rent classification, household membership history, and finalized reconciliation.
- **Execution and quote telemetry:** size-specific Pump/PumpSwap/aggregator quotes, dynamic fees,
  transaction lifecycle, and actual fill deltas.
- **Sensorium and attention capture:** board/viewport/chart scenes and focus/background-watch intervals,
  especially while flat.
- **Gesture/disposition ontology:** low-friction capture and versioned free-form semantics without
  forcing the final 3–8 dispositions or 2–5 crackle types prematurely.
- **Portfolio and risk:** liquid reserve, capital constraints, correlated exposure, and declared
  benchmark definitions for opportunity cost.
- **Venue/lifecycle identity:** stable mint identity through bonding-curve graduation and route
  changes.

### Outputs provided

- episode, epoch, lot, tranche, fill, and flat-watch semantics for reactive-exit and re-entry studies;
- basis-quality and executable-value contracts for portfolio glass;
- realized/cash-recovery/runner-exposure targets for the cockpit;
- exact treatment assignments for counterfactual replay;
- episode sequences for later interviews, analog retrieval, LLM annotation, and policy/program
  synthesis.

## Recommendations to carry into reconciliation

1. Adopt `episode` as the behavioral unit and `inventory epoch` as the flat-to-flat accounting unit.
2. Make the household asset ledger exact and independent of all strategy attribution.
3. Preserve exact acquisition lots, but use named average-cost accounting as the initial operator
   view; keep FIFO/specific-identification as alternative projections.
4. Introduce explicit management tranches only where Ember actually distinguishes overlapping
   exposure; never infer tranche PnL after the outcome.
5. Treat flat observation and re-entry as first-class episode events.
6. Display realized PnL, cash recovery, remaining basis, and executable value together. Ban “free
   runner” from the accounting vocabulary.
7. Treat opportunity cost as a set of prospectively defined counterfactual studies, not one ledger
   field.
8. Run the small read-only experiment before choosing storage technology or implementing execution.

