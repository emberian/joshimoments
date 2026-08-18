# Lane 06 — Portfolio, capital allocation, and LP inventory

Status: pre-engineering research, 2026-08-16.

## Question this lane owns

How should the cockpit represent and constrain one economic portfolio containing:

- fast crackle clips;
- deliberately retained runners;
- catalyst and fancoin exposure;
- repeated exit, flat-watch, and re-entry intervals inside one episode;
- liquid SOL and dated reserves;
- and Meteora DLMM positions whose bins are contingent trades rather than passive yield?

The objective is not to choose an allocation policy yet. It is to make the actual policy
observable, prevent accounting illusions, and provide controls that mean what Ember thinks they
mean. A portfolio system that cannot represent “I exited while watching the graph, remained
interested while flat, and re-entered later” has already discarded a material part of the policy.

This lane treats `RADON`, `EarthCoin`, and `CRASHIUS` as requirements examples for crackles that
became retained runners. They are not evidence of profitability and this document does not make a
recommendation about their current disposition.

## Main conclusion

There should be one consolidated economic balance sheet and several strategy books layered over
it. The books are labels and authorization budgets, not separate piles of money.

An LP position belongs on that balance sheet as both:

1. its current custody-invariant token inventory and accrued fees; and
2. a price-indexed schedule of future token conversions across bins.

It is not a deposit receipt, a yield account, or a completed sale. Removing liquidity changes
custody but does not necessarily change asset exposure. Closing a position does not mean its token
basket has been realized into SOL. Rebalancing changes the contingent trade schedule and may add or
remove capital; it must not silently become an opportunity to rotate inventory through a swap.

Similarly, a full spot exit need not end an episode. The episode can remain live while inventory is
zero. The value of a graph-driven exit/re-entry policy is measurable only if those flat intervals,
the attended scene, actual fills, and a contemporaneous continuous-hold counterfactual are all
preserved.

## Observed facts and provenance

### What the existing chain work establishes

The following are useful compost, not inherited verdicts:

- [`RESULT_lp_history.md`](../../../../joshibot/studies/RESULT_lp_history.md) reconstructed a
  window containing 42 Meteora positions and correctly recognized alternating one-sided positions
  as buy and sell ladders. Its strongest semantic observation is that these were staged executions
  with a fee rebate, not generic “yield positions.” The same study explicitly could not isolate LP
  PnL from commingled swaps for all positions.
- The later, lifetime reconstruction in
  [`RESULT_position_history.md`](../../../../joshibot/studies/RESULT_position_history.md) found 48
  positions opened, 44 closed, and four open at its observation time. It also found that the
  claimed “20.10 SOL realized” could not be a literal cash-flow statement: Meteora withdrawals
  returned token baskets, while 12.913149 SOL of SOL receipts were fee claims. The numbers are
  historical, not current; the accounting correction is durable.
- That reconstruction initially misclassified a transfer to the wallet's own wrapped-SOL account
  as an external distribution. It also showed that internal transfers across five operator wallets
  net to zero only after the wallets are consolidated. Counterparty and custody classification are
  therefore first-order accounting requirements, not cleanup.
- [`RESULT_toll_positioning.md`](../../../../joshibot/studies/RESULT_toll_positioning.md) estimated
  that two one-sided token-token ladders beat its routing counterfactual by roughly 1.4–2.0% per
  unit of flow, using 221 fills across two pools. The same document reports that ten closed LP
  positions underperformed HODL in aggregate. Both may be true: the execution schedule can improve
  a sale while carrying the inventory can lose. The sample, price proxy, and counterfactual are too
  narrow to make this a general allocation rule.
- [`RESULT_lp_strategy.md`](../../../../joshibot/studies/RESULT_lp_strategy.md) supplies useful bin
  algebra, custody/fee distinctions, and explicit short-window caveats. Its conclusions about
  which pools should receive capital repeatedly depend on hours of data, assumed holding horizons,
  and an objective that changed during the study. They are hypotheses for prospective evaluation,
  not portfolio policy.

### What the existing executor actually exposes

The old executor is narrower than the desired LP semantics:

- [`builder.cjs`](../../../../joshibot/shitcoims_lpexec/node/builder.cjs) reads per-bin inventory,
  removes a percentage from a selected bin range, and creates a new one-sided uniform `Spot`
  position.
- [`planner.py`](../../../../joshibot/shitcoims_lpexec/planner.py) embeds one particular policy:
  trim token-X exposure from the far end of the range and build a uniform ask ladder. That may be a
  useful action, but it is not the meaning of “manage an LP position.” It should not become the new
  system's ontology.
- [`allowlist.py`](../../../../joshibot/shitcoims_lpexec/allowlist.py) permits several add-by-weight
  and ranged-removal instructions, but explicitly refuses `rebalance_liquidity` because the old
  guard cannot verify the resulting per-bin effect from the instruction bytes. The builder does not
  expose add-to-existing-by-weight or in-place rebalance.
- [`ledger.py`](../../../../joshibot/shitcoims_lpexec/ledger.py) has a valuable
  `intended / simulated / actual` reconciliation shape, two clocks, and explicit divergence classes.
  The hostile-builder instruction allowlist, dry-run default, independent simulation, and
  fail-closed gates are also worth composting.

### Current protocol capability

The current official Meteora TypeScript SDK reference documents more expressive operations than
the old executor presents:

- adding strategy-based liquidity to an existing position;
- initializing or adding liquidity using explicit per-bin weights;
- removing a BPS amount over a selected bin range, with closing optional;
- simulating a balanced or custom rebalance with deposits and withdrawals; and
- building an on-chain `rebalance_liquidity` instruction for the result.

Source: [Meteora DLMM TypeScript SDK reference](https://github.com/MeteoraAg/docs/blob/main/developer-guides/dlmm/typescript-sdk/reference.mdx), checked 2026-08-16. The
[official SDK changelog](https://github.com/MeteoraAg/dlmm-sdk/blob/main/CHANGELOG.md) records the
rebalance helpers in the 1.6.0 release and current weight-based and Token-2022 changes.

The position's withdrawal-and-redeposit transformation can occur in one rebalance instruction.
Missing bin arrays or position expansion may require prerequisite instructions or transactions, so
“atomic rebalance” must refer precisely to the inventory transformation, not promise that every
possible preparation step is one transaction. SDK availability is also not a safety proof. The old
guard was right not to allow an instruction whose economic postcondition it could not independently
check.

## Required conceptual model

### Episode, inventory interval, and clip

The accounting hierarchy should be:

```text
episode
  thesis/disposition transitions
  attention intervals
  inventory interval 1
    entry and one or more partial/full exit clips
  flat-but-watching interval
  inventory interval 2
    re-entry and subsequent management clips
  ...
  resolution or dormant continuation
```

An **episode** is the operator-meaningful attempt to understand and trade one evolving situation.
It may span several position intervals and several realized clips. An **inventory interval** begins
when exposure moves from zero to nonzero and ends when it returns to zero. A **clip** is one
economically attributable acquisition or disposition inside an interval.

Episode identity should be explicit and operator-correctable. Time-gap heuristics may suggest that a
re-entry continues an earlier episode, but must not decide it silently. Ember may exit one thesis
and later enter an unrelated thesis in the same mint; conversely, a long flat watch may remain one
episode.

Required events include:

- `exit_inventory`, distinct from `resolve_episode`;
- `continue_watching_flat`;
- `reenter_episode`, with a link to the prior inventory interval;
- `take_profit_keep_runner`;
- `promote_or_change_disposition`;
- `reduce`, `add`, and `zap`;
- an immediate reason fragment and a later replay-backed account.

This prevents the PnL from graph-driven exit and later re-entry from disappearing into two
unrelated trades.

### LP position as a contingent trade schedule

Represent an LP position at time `t` as a versioned set of bins:

```text
LP schedule = {
  pool and exact mint identities,
  active bin and source slot,
  per bin: price, token X, token Y, liquidity, accrued fees, intended role,
  account rent and other recoverable/nonrecoverable costs,
  owner and position account,
  schedule version and parent transformation
}
```

For operator display, every bin should be translated into an asset-semantic sentence such as:

> If the market traverses this bin in direction D, up to Q of mint A is offered for mint B around
> price P, before fees and path-dependent competition.

Never rely on “above means sell” without also naming the mint orientation. An X/Y inversion error
can turn a “stop selling SOL” gesture into the opposite transaction.

The schedule has at least four economically different actions:

1. **Add capital** to selected existing bins or a new target distribution.
2. **Remove capital** from selected bins, partially or fully, without changing the withdrawn
   assets into anything else.
3. **Redistribute/rebalance** current position inventory across bins, optionally with tightly
   bounded top-ups or withdrawals.
4. **Swap/recenter** inventory through an explicit trade.

Action 4 must never be smuggled into actions 1–3. If Ember says, “I do not want to sell more SOL
right now,” the direct control is to remove or down-weight the bins that would convert SOL into the
other token and leave the withdrawn SOL liquid. It cannot undo SOL already converted on prior
crossings.

A schedule version should survive removes, adds, and in-place rebalances. Opening or closing an
account is a protocol implementation detail, not an economic episode boundary. Continually closing
and reopening positions can incur transaction, rent, opportunity, and half-completed-state costs;
in-place rebalance or add/remove may avoid some of them, but only after their exact effects are
validated.

### Three simultaneous accounting views

One number cannot serve custody, performance, and risk. Preserve three linked views.

#### 1. Asset ledger: exact and custody-invariant

Track exact raw quantities by mint across every controlled wallet, token account, LP position,
claimable fee account, and unsettled transaction. Internal movements, wrapping SOL, depositing into
an LP, withdrawing from an LP, and claiming a token-denominated fee do not create profit.

Every asset unit must have exactly one current custody location. Pending and failed transactions
must not create phantom inventory.

#### 2. Performance ledger: cash flows plus explicitly valued residuals

For an episode that is still open, an executable PnL view in reporting numeraire `N` is:

```text
net proceeds already realized in N
  - acquisition and execution costs in N
  + size-specific executable liquidation value of residual inventory in N
```

Exact token flows remain primary. Every conversion into `N` records the route, quote size, fee
configuration, slippage assumption, source slot, and valuation time. A chart mark is not an
executable liquidation value. A fee received in a memecoin is income in that memecoin; it is not
realized SOL merely because a UI quotes it in SOL.

At minimum show both SOL and USD reporting views. SOL is the transaction reserve and common quote
asset, but SOL itself carries USD risk and dated household obligations may be USD-denominated.

#### 3. Risk/commitment view: current and contingent exposure

Current inventory is insufficient for an LP. For every position compute:

- current token quantities and liquidation value;
- token quantities after complete traversal to each range edge;
- conversion by each materially funded bin or bin group;
- value and composition under named price/liquidity scenarios;
- time and estimated impact required to exit each resulting asset;
- accrued but unclaimed fees separately;
- capital or rent locked but recoverable only on close;
- irreversible rent or transaction costs;
- all pending top-up and withdrawal bounds.

An LP contains funded contingent conversions, not an unfunded promise: a filled buy-side bin will
not debit extra SOL from the wallet because that SOL is already in the position. It can nonetheless
consume the portfolio's desired SOL exposure by transforming the escrowed inventory.

## Measuring exit and re-entry rather than erasing it

### Actual episode result

The whole-episode result includes every inventory interval, every clip, all network and venue fees,
and the final executable value of anything retained. Subtotals may be attached to crackle,
runner, or catalyst phases, but their sum must reconcile to the episode and then to the
consolidated portfolio.

### Management counterfactuals

The system should replay at least these causal comparisons from the same initial state:

- actual exit/re-entry sequence versus continuous hold through the flat interval;
- actual delayed re-entry versus immediate re-entry after the exit;
- actual partial exit and runner versus full exit;
- actual re-entry sizing versus redeploying the exit proceeds mechanically;
- actual LP schedule edits versus leaving the prior schedule in place.

For a full exit and later re-entry, a particularly legible measure is the quantity uplift or loss:
how many tokens the net exit proceeds could actually repurchase at the later quote, compared with
the tokens that would have remained under continuous hold. A terminal-value comparison is still
needed when sizes differ or some proceeds were allocated elsewhere.

These are counterfactual management estimates, not additional realized PnL. “Avoided a 40% fall”
must not be added to actual profit. Use quotes and routes available at the historical decision
times, including latency and capacity. Never compare against the hindsight-best bottom or the
best coin in the market.

### Flat intervals are economically active

While flat, record:

- whether the episode remained visible or was explicitly watched;
- the chart and social scene Ember continued to observe;
- rejected re-entry moments and their reasons;
- capital redirected elsewhere;
- the actual re-entry trigger, if any;
- and the counterfactual held position's path.

This permits estimates of graph-watching value, attention cost, avoided downside, missed upside,
and capital recycling without pretending the attention was free.

## Capital allocation without mental-accounting errors

### One balance sheet, many policy overlays

The allocator begins from consolidated current wealth, not the source of each dollar. Creator
fees, a winning crackle, an LP withdrawal, and a transfer between the operator's wallets do not
receive different risk treatment merely because of their history. “House money,” “free runners,”
and “LP principal” are useful stories only when they correspond to explicit present-tense policy.

Virtual buckets can still be useful as constraints:

1. **Dated reserve:** assets intended for obligations, sized with their currency and due date.
2. **Transaction reserve:** liquid SOL for network fees, account creation, unwinds, and failed-send
   recovery.
3. **Opportunity reserve:** capital deliberately kept liquid for future human-selected entries.
4. **Crackle authorization:** maximum current and reserved risk for armed short-horizon actions.
5. **Runner authorization:** maximum economic downside and illiquidity carried by retained
   residuals.
6. **Catalyst/fancoin authorization:** exposure with a longer social-transition horizon.
7. **LP authorization:** current inventory plus its contingent conversion surface.
8. **Learning-loss authorization:** an explicit amount the portfolio can lose acquiring evidence,
   independent of whether a recent strategy happened to win.

These must be mutually reconcilable overlays on one asset ledger. A dollar can fund only one
simultaneous commitment. Unused budget is not an asset; realized proceeds return to the allocator
before they are redeployed.

### Available capital is horizon-dependent

Display at least:

- spendable SOL now;
- SOL remaining after all submitted but unsettled transactions;
- SOL protected by dated and transaction reserves;
- maximum SOL reserved by every simultaneously armed intent;
- value liquidatable within selected horizons and impact bounds;
- capital deployed but intentionally retrievable from LP bins;
- assets whose apparent value cannot be exited within the relevant horizon.

An unfilled sell ladder is not cash. A runner valued at a stale last trade is not opportunity
reserve. A token withdrawn from an LP is more operationally available but no less exposed to that
token.

### Opportunity cost

Opportunity cost should be measured against predeclared, contemporaneously feasible alternatives,
not the best subsequent chart. Useful comparisons include:

- keep SOL liquid;
- retain or reduce the present position;
- execute the next selected crackle;
- maintain or withdraw a particular LP schedule;
- and the specific candidate Ember wanted but could not arm because capital was committed.

When a budget blocks an action, preserve the rejected intent and shadow its executable path. This
measures the cost of capital lock-up without requiring a real trade. “Could have bought the day's
winner” is not an estimator.

## Aggregate economic exposure and concentration

### Aggregate by asset before attributing by strategy

The same mint may appear as a runner, inside one or more LPs, in an armed crackle, and as future
fee income. First aggregate its current and contingent quantity across custody locations. Then
attribute portions to books for policy analysis. Do not call the same unit diversified because it
appears in two products or wallets.

For each asset show:

- current net quantity and executable liquidation value;
- maximum quantity after all funded LP paths and armed actions;
- net spend still authorized;
- realized and unrealized episode attribution;
- exit time/impact bands;
- and contribution to portfolio drawdown scenarios.

### Narrative and community concentration

Price correlation estimates will be unstable and frequently absent. Maintain a many-to-many
exposure graph using point-in-time evidence:

```text
asset -> represented person / narrative / community / deployer / related mints
asset -> venue / pool / router / fee-program dependencies
asset -> SOL beta / broad Pump attention / shared social cluster
book  -> operator attention and execution-system dependencies
```

Concentration controls should operate over current hypotheses with uncertainty, not pretend these
labels are facts. A fancoin, its duplicate, and an LP containing either may be one community bet.
Several “independent” books may all fail when Pump attention falls or the RPC/executor is degraded.

The old toll study's observation that creator fees, token holdings, LP flow, and community activity
can all load on the same community is a useful warning: income streams and inventory tied to one
narrative are not diversification simply because they have different ledger labels.

### Scenario exposure is more useful than a single covariance matrix

Maintain named stresses such as:

- one coin goes to zero while exit liquidity disappears;
- all retained runners fall together;
- SOL falls sharply in USD;
- a creator disavows a fancoin or attention migrates to a duplicate;
- the DLMM route stops receiving flow;
- a pool traverses fully to either edge;
- all armed crackles trigger during a market-wide fall;
- fee income stops while its correlated token inventory also falls;
- RPC or UI state becomes stale during an intended exit.

Report the assumptions and missing quotes. A conservative unknown is not equivalent to a measured
zero.

## Runner cemetery prevention

Runner retention is a deliberate way to preserve convex upside after recognizing some profit. It
becomes a cemetery when residual exposure no longer reflects an active or consciously dormant
choice.

Every runner needs:

- originating episode and cost/proceeds history;
- current executable liquidation value and maximum remaining downside;
- present disposition, thesis fragment, and horizon;
- last intentional review time;
- reason for continued holding, including “nothing articulable”;
- social/market transitions since the last review;
- exit capacity and whether the position is merely dust;
- and a status: active, dormant-intentional, queued for reduction, or forgotten/unclassified.

Use a **runner risk budget** and an **attention-debt indicator**, not a mandatory age-based sale.
Forced cleanup can destroy exactly the rare right-tail exposure the strategy preserves. Appropriate
prompts are “is this still intentional?” and “what other action is this value preventing?”, with
`keep unchanged` as a first-class answer.

Metrics include retained value, at-risk basis, count, age, time since review, liquidity-adjusted
value, narrative concentration, and the share whose disposition is unclassified. Do not call a
runner free after recovered basis: its current value, downside, correlation, and opportunity cost
remain real.

## Proposed portfolio abstractions

### Core entities

- **Controlled domain:** wallets, authorities, token accounts, LP accounts, fee accounts, and
  known external custody included in the consolidated view.
- **Asset lot:** exact quantity with acquisition/transfer lineage; valuation is an annotation.
- **Episode:** operator-meaningful thesis and management history across inventory intervals.
- **Inventory interval:** continuous nonzero exposure inside an episode.
- **Disposition:** current intent, allowed to change independently of entry type.
- **Intent/reservation:** an armed action with bounded capital, assets, expiry, and cancellation.
- **LP schedule version:** exact bin state plus intended roles before and after a transformation.
- **Book attribution:** policy label used for budgets and analysis, not custody.
- **Narrative exposure:** versioned, uncertain links among assets, people, communities, and shared
  failure dependencies.
- **Obligation/reserve:** currency, due date, required confidence, and permitted backing assets.
- **Valuation:** quote method, amount, route, slot/time, fee assumptions, and confidence.

### Provenance rules

- Never overwrite raw token quantities with marked values.
- Never rewrite a historical episode when the taxonomy changes; append a versioned interpretation.
- Preserve both event time and observation/ingest time.
- Record intended, quoted/simulated, submitted, landed, and reconciled states separately.
- Link every derived PnL or risk number to its source flows and valuation.
- Treat missing data as explicit state, not zero.

## Safety invariants for a future operator surface

These are design requirements, not authorization to execute.

### Portfolio invariants

1. Exact asset quantities reconcile across the controlled domain after every confirmed action.
2. Internal transfers and LP custody changes cannot create portfolio PnL.
3. A strategy subtotal must reconcile to its episode, and all episodes plus unattributed flows must
   reconcile to the portfolio.
4. Residual runners are valued and risked even when their original basis has been recovered.
5. Current exposure and fully traversed LP exposure are both shown before an LP action is approved.
6. Aggregate commitments assume all concurrently armed actions may trigger; capital cannot be
   reserved twice.
7. Dated and transaction reserves remain satisfiable under their stated liquidation horizon and
   currency assumptions after any risk-increasing action.
8. Every risk display names its valuation time and refuses to present stale data as current.

### Intent and execution invariants

1. Every action names exact mint and pool addresses; symbols are display-only.
2. An LP action states separately: top-up maxima, withdrawal minima, target bin distribution, fee
   claims, account close behavior, rent, slippage, and whether any swap is allowed.
3. Swap permission defaults to false for add, remove, and rebalance. If a swap is desired, it is a
   distinct, visible intent with its own executable quote and cap.
4. A rebalance is accepted only if an independent decoder/simulator can verify the signed economic
   intent and the resulting per-bin and per-asset bounds. Merely allowlisting the instruction name
   is insufficient.
5. Pre-action simulation, submitted bytes, landed transaction, and post-state reconcile. An
   unexplained divergence halts subsequent risk-increasing actions.
6. A stale active bin or quote invalidates the action rather than silently changing which asset is
   sold.
7. All intents have a TTL and explicit cancellation. A later disposition transition cancels or
   reauthorizes incompatible intents.
8. Automation cannot average down, promote a runner, use reserve capital, or broaden a target range
   without a matching operator intent.
9. Emergency controls distinguish custody changes from economic risk reduction. Withdrawing a
   token from an LP is not falsely labelled “exited.”

### Candidate hard controls

- minimum liquid SOL after submitted and worst-case armed commitments;
- minimum dated-reserve coverage by currency and horizon;
- maximum net new spend per intent, asset, day, and book;
- maximum current and contingent exposure per mint;
- maximum aggregate narrative/community and venue dependency;
- maximum illiquid exposure by estimated exit horizon and impact;
- maximum simultaneously armed actions and pending transactions;
- maximum LP top-up in each asset and maximum acceptable post-rebalance asset composition;
- maximum priority fee, rent, slippage, and transaction count;
- stale-data and unreconciled-state circuit breakers;
- a global cancel for intents and a separately designed, narrowly scoped unwind path.

Limits should be direction-aware. A daily risk-increase cap should not accidentally prevent an
otherwise safe cancellation or removal of unfilled LP conversion capacity. Conversely, a large
withdrawal is not automatically risk-reducing if it merely moves the same risky token into the
wallet.

## Measurements this lane needs

### Accounting integrity

- exact per-mint reconciliation residual across all included custody;
- fraction of transactions and flows with unresolved economic classification;
- intended/simulated/actual divergence rate and cause;
- stale or missing valuation fraction;
- portfolio NAV under executable, mark, and stressed-liquidation views.

### Capital use

- liquid SOL, protected reserves, reserved commitments, and deployable balance over time;
- capital recycling time from exit to next selected use;
- shadow value of intents rejected for insufficient free capital;
- exposure-days and attention-hours by book;
- costs of closes/reopens versus in-place edits, including rent, fees, failure probability, and
  time spent out of service.

### Episode management

- result of the full episode and of each inventory interval;
- contribution of exit/re-entry versus a continuous-hold replay;
- contribution of partial realization and runner retention versus full-exit replay;
- executable price at intent, send, land, and fill;
- time flat while still watching and operator attention cost;
- performance conditional on disposition transitions, without treating those labels as fixed.

### LP inventory

- per-bin fills and fees against a same-time executable route counterfactual;
- current and edge-traversal asset composition;
- duty cycle and funded weight near active flow;
- add/remove/rebalance frequency and total friction;
- realized fee assets versus inventory change and HODL/alternative execution benchmarks;
- schedule fill quality, exit capacity, and time to convert at actual flow;
- frequency with which Ember's desired edit cannot be expressed by the available UI or target
  distribution.

### Concentration and cemetery risk

- current and stressed exposure by mint, narrative, community, venue, and system dependency;
- runner value, downside, liquidity, age, and time since intentional review;
- share of runner exposure marked unclassified or forgotten;
- overlap between future income, token inventory, LP legs, and social activity in the same
  community;
- how much opportunity reserve would be recovered by each possible reduction, using current
  executable value rather than basis.

## Failure modes and counterexamples

1. **Position-centric accounting:** a full exit closes the record, so graph-driven re-entry is
   counted as a new unrelated trade and the management edge vanishes.
2. **Hindsight attribution:** avoided losses or missed winners are treated as actual PnL.
3. **Mark-price solvency:** an illiquid runner or LP basket is counted as spendable SOL.
4. **Closed-means-realized:** closing an LP token account is reported as realizing SOL even though
   the wallet receives risky tokens.
5. **Fee-income double count:** token fees are marked as income while the same tokens also appear in
   residual inventory, or fees are celebrated without the inventory freight.
6. **Custody-as-trade:** wallet transfers, SOL wrapping, LP deposits, withdrawals, or fee claims
   create phantom performance.
7. **House-money budgeting:** recent wins authorize more risk even though current wealth and
   liabilities are unchanged by the source label.
8. **Free-runner fallacy:** recovered basis hides the present value, tail exposure, and opportunity
   cost of the remainder.
9. **Runner cemetery:** tiny residues accumulate without an intentional disposition and consume
   attention or correlated risk budget.
10. **Forced cemetery cleanup:** an age or count rule systematically sells rare right-tail runners
    merely to make the dashboard tidy.
11. **Wallet-local caps:** risk is spread across wallets or LP custody and escapes a per-wallet
    limit; internal transfers look like deposits or withdrawals.
12. **Book-label diversification:** the same mint/community appears in crackle, runner, catalyst,
    fee income, and LP books and is counted as several independent edges.
13. **Reserve overbooking:** several armed crackles and pending LP top-ups each assume the same SOL
    is available.
14. **Currency mismatch:** SOL reserve appears adequate while an approaching USD obligation is not.
15. **LP orientation error:** X/Y or quote/base inversion implements the opposite schedule from the
    operator's words.
16. **Uniform-shape trap:** the easiest SDK strategy becomes the assumed optimal policy even when
    Ember intends nonconstant bin weights.
17. **Rebalance laundering:** a helper performs or induces an inventory swap that was not visibly
    authorized.
18. **Half-completed transformation:** remove succeeds and add fails, or prerequisite transactions
    land while the final rebalance does not.
19. **Stale-bin action:** the active bin moves between observation and landing, materially changing
    the intended conversion surface.
20. **Cap blocks safety:** a coarse transaction/day limit prevents cancellation or removal of
    future conversion capacity; the opposite bug labels any withdrawal safe.
21. **Attention omitted:** flat watching and portfolio monitoring are priced at zero, so a strategy
    that consumes all of Ember's attention appears scalable.
22. **Policy frozen too early:** provisional dispositions become database enums that cannot express
    later distinctions, corrupting both UI and analysis.

## Smallest useful experiment

Run a read-only, prospective **portfolio shadow week**. It should not sign, submit, or recommend a
trade.

### Scope

- Start with the three named retained runners, every currently controlled liquid asset, and every
  current Meteora position that can be read safely.
- Follow the next ten operator-meaningful spot episodes, including any full exit followed by
  continued watching or re-entry.
- Select one live or recently used LP position for a schedule-expression exercise.

### Procedure

1. Reconcile exact quantities across the agreed controlled-wallet set and all LP custody. Make
   unknown custody and external accounts explicit.
2. Ask Ember to assign a coarse current disposition and one-sentence-or-empty reason to the three
   runners. Do not force a taxonomy beyond what is natural.
3. At every spot gesture, preserve the episode link, inventory interval, attended scene,
   executable quote, portfolio state, competing use of capital, and immediate reason fragment.
4. When Ember exits but keeps watching, leave the episode open. Shadow continuous hold and
   mechanically funded re-entry counterfactuals from contemporaneous quotes.
5. Once daily, show a compact consolidated view: liquid and reserved SOL, executable runner value,
   current/contingent LP exposure, narrative concentration, and unclassified attention debt. Ask
   only whether it matches Ember's mental model and record corrections.
6. For the LP exercise, render the actual per-bin schedule and ask Ember to express one concrete
   change, preferably a statement like “I no longer want this much SOL converted at these prices.”
   Compare four hypothetical implementations: partial remove, add-to-existing with weights,
   in-place rebalance, and close/reopen. Show exact before/after token custody, per-bin conversions,
   top-ups/withdrawals, rent/friction, and partial-failure states. Execute none of them.
7. At any eventual zap or episode resolution, conduct the replay-backed interview and distinguish
   contemporaneous reasons from retrospective explanation.

### Success criteria

- Every asset quantity reconciles or has an explicit unresolved cause.
- Ember recognizes exits, flat watches, re-entries, partial profits, and runners as the same
  episodes they intended.
- The portfolio view never calls LP withdrawal or closure a sale and never calls a runner free.
- At least one exit/re-entry interval can be replayed against continuous hold without using future
  information.
- The LP schedule view correctly captures the intended capital reduction or rebucketing without an
  X/Y ambiguity.
- The daily view surfaces simultaneous commitments and correlated exposure without becoming too
  onerous to consult.
- Corrections to vocabulary and dispositions are easy to append rather than destructive migrations.

This experiment is useful even if Ember's trading policy is negative-EV. It determines whether the
apparatus can faithfully observe capital movement and management decisions—the prerequisite for
any honest answer about the policy.

## Unresolved questions

- Which wallets, exchange balances, vesting accounts, fee vaults, and household obligations belong
  inside the initial controlled domain?
- Which reporting numeraire should govern performance, and which currency/horizon should govern
  reserves?
- When does Ember consider a re-entry the same episode versus a genuinely new thesis?
- What are the initial natural dispositions and crackle types, and which should remain free text?
- What review prompt prevents forgotten runners without biasing Ember toward needless selling?
- How should narrative/community links be proposed, corrected, and assigned uncertainty?
- Which counterfactual capital alternatives are worth maintaining continuously?
- What loss and illiquidity budgets feel like real authorization rather than decorative warnings?
- For each LP use, is the objective execution, retained exposure, fee collection, staged
  accumulation/distribution, or a mixture? The same bin shape cannot be evaluated without this.
- Which nonconstant bin shapes correspond to Ember's actual intuitions, and can the shapes be
  elicited visually rather than as numeric weights?
- Can `rebalance_liquidity` parameters and postconditions be decoded independently enough to make
  in-place rebalance safer than a remove/add sequence? How are prerequisite bin-array transactions
  staged without misleading atomicity claims?
- How should emergency unwinds work when risk-reducing intent conflicts with ordinary caps,
  stale-data breakers, or unavailable routes?
- How should attention time be measured without turning the cockpit into surveillance or making the
  operator narrate every glance?

## Dependencies on other lanes

- **Event tape and temporal model:** exact transaction, quote, active-bin, viewport, intent, and
  ingest/event clocks.
- **Episode/gesture ontology:** explicit exits, flat watches, re-entries, disposition transitions,
  partial profits, runners, and zaps.
- **Execution and replay:** size-specific historical quotes, landing latency, actual fills, route
  capacity, and shadow counterfactuals.
- **Pump-like cockpit:** candidate context, graph state, low-friction operator gestures, and an
  understandable consolidated portfolio surface.
- **Social/fancoin lane:** versioned identity and community graphs for narrative concentration and
  catalyst-state exposure.
- **Research methodology lane:** prospective denominators, chronological evaluation, selection
  effects, and rules for separating exploration from confirmation.
- **Security/execution lane, later:** independent transaction decoding, simulation, instruction
  postconditions, signer isolation, reservations, gates, and reconciled post-state. This lane does
  not authorize it.

## Decision boundary

Do not choose LP widths, runner percentages, book allocations, or automated re-entry rules from
this lane. First make the episode and consolidated exposure model faithful during the shadow week.
Only then should the project reconcile portfolio controls with the sensorium, execution, social,
and evaluation lanes and decide what engineering slice is justified.
