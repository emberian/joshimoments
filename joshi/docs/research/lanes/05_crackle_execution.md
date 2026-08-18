# Lane 05: human-armed crackle execution

Status: research design, not an authorization to trade.

This lane asks how to preserve Ember's selection and graph-reading policy while making the
machine fast, exact, and observable after Ember has pointed at a coin. It does **not** try to
discover an autonomous entry rule. It does **not** infer that the strategy has positive expected
value. It defines the apparatus required to find out.

The central correction is:

> A crackle is an entry and early-management mode inside an episode. It is not a five-minute
> position, a fixed bracket, or a promise to close the whole inventory.

An episode may contain a watched dip, an entry, several partial realizations, retained exposure,
a graph-driven full exit, time watching while flat, and one or more re-entries. Treating any one
of those boundaries as the whole trade discards the policy we want to measure.

## 1. Outcome of this lane

Build toward a **human-armed conditional execution instrument**, not a mechanical whole-market
scalper:

1. Ember selects a mint and arms a bounded playbook while the system captures the entire scene.
2. The machine watches that mint at event-level resolution, continuously computes size-specific
   executable quotes, and may act only within the playbook's explicit authority.
3. Profit targets are expressed in net lamports against reconciled wallet inventory—not as chart
   percentages.
4. Ember can instantly override automation: cancel an unfilled entry, reduce, take profit while
   retaining a runner, fully zap, continue watching flat, or re-arm a re-entry.
5. Every intention, trigger, transaction attempt, chain outcome, wallet delta, and change of
   disposition remains reconstructible as one episode.

The smallest useful result is not profitable automation. It is an honest shadow instrument that
can replay what Ember selected, what it waited for, what Ember did while watching the graph, and
what could actually have filled after fees and latency.

## 2. Epistemic labels

This document uses these labels deliberately:

- **Protocol fact** — stated by current official Pump/PumpSwap documentation or SDK interfaces.
- **Corpus observation** — measured or implemented in `joshibot`; informative but tied to its
  window, code, and measurement errors.
- **Operator report** — Ember's description of their own process; a requirement and a hypothesis
  about mechanism, not proof of profitability.
- **Proposal** — an architecture or experimental choice for `joshi`.
- **Hypothesis** — a claim the prospective apparatus must be able to falsify.

## 3. What is known now

### 3.1 Current protocol facts

These were checked against Pump's official public documentation on 2026-08-16. They should still
be version-pinned and rechecked before implementation because the programs and required accounts
have changed before.

- Pump exposes official TypeScript and Rust SDKs. Its current unified bonding-curve instructions
  are `buy_v2`, `sell_v2`, and `buy_exact_quote_in_v2`; required accounts are mandatory rather
  than optional. A bonding-curve buy is exact base-token output capped by `max_sol_cost`, including
  protocol and creator fees. A sell is exact base-token input floored by `min_sol_output`, after
  those fees. See the [official repository](https://github.com/pump-fun/pump-public-docs),
  [buy specification](https://github.com/pump-fun/pump-public-docs/blob/main/docs/instructions/BUY.md),
  and [sell specification](https://github.com/pump-fun/pump-public-docs/blob/main/docs/instructions/SELL.md).
- Fee rates for bonding curves and canonical PumpSwap pools are selected from the on-chain
  `FeeConfig` using current market capitalization. Therefore a universal hard-coded “Pump fee” is
  not a safe input to a net-profit trigger. The relevant fee config and state must be read at the
  quote slot. See the [official fee-program documentation](https://github.com/pump-fun/pump-public-docs/blob/main/docs/FEE_PROGRAM_README.md).
- A completed bonding curve can be migrated permissionlessly and idempotently to PumpSwap; the
  canonical migrated pool has index zero. Completion and pool existence are separate observable
  states. See the [Pump program documentation](https://github.com/pump-fun/pump-public-docs/blob/main/docs/PUMP_PROGRAM_README.md).
- PumpSwap provides direct `buy(baseOut, maxQuoteIn)` and `sell(baseIn, minQuoteOut)` instructions.
  The official low-level SDK is explicitly intended for programmatic integrations and permits
  construction of exact-input/exact-output instruction bounds. See the
  [PumpSwap program](https://github.com/pump-fun/pump-public-docs/blob/main/docs/PUMP_SWAP_README.md)
  and [SDK mapping](https://github.com/pump-fun/pump-public-docs/blob/main/docs/PUMP_SWAP_SDK_README.md).
- PumpSwap quotes must use effective quote reserves:
  `quote_vault_balance + pool.virtual_quote_reserves`. The official documentation says the
  appended virtual amount is zero on all pools at the time of writing, but explicitly warns that
  it may become nonzero. Code based only on the raw vault is already conceptually stale.
- Current bonding-curve v2 instructions may initialize or top up accounts such as the user's
  volume accumulator and ATAs. Those costs and latency can differ between a wallet's first trade
  and later trades. They cannot be silently folded into “slippage.”

**Inference from the protocol facts:** direct smart-contract interaction is technically
available. “Direct” should initially mean building instructions through version-pinned official
SDKs/IDLs and submitting them to the Pump or PumpSwap program, not hand-encoding every account and
discriminator. The latter adds no strategic value and creates upgrade risk.

### 3.2 Corpus observations from `joshibot`

- The reconstructed operator history found 13 round trips under five minutes, 7 winners, and
  +$3.09, while 20 longer round trips had one winner and approximately -$61. This is a small,
  selected sample. It is evidence that the operator's short episodes deserve prospective
  measurement, not evidence of an edge. See
  [`wiggle.py`](../../../../joshibot/shitcoims_paperdesk/wiggle.py).
- The mechanical wiggle book converted the observed holding-time distribution into a 240–420
  second exit clock. Its own commentary later acknowledges that the clock records **when** Ember's
  reactive exits occurred, not **why**. See
  [`policy.py`](../../../../joshibot/shitcoims_paperdesk/policy.py).
- A later operator book added an immediate “zap” gesture, captured the path visible at the gesture,
  and filled on a later observation. This was an important correction, but it still closed the
  whole paper position and did not represent partial exits, retained runners, flat watching, or
  re-entry within an episode. See
  [`operator.py`](../../../../joshibot/shitcoims_paperdesk/operator.py).
- One paper stop armed at -16.5% and filled at -64.7% after a 43-second observation gap. Whatever
  the exact simulator limitations, it establishes that a low-frequency candidate board is not an
  execution feed and that a stop is not a guaranteed price.
- On a 30-second board tape, 55.9% of simulated resolutions used stale mark-outs. The modest
  apparent advantage of bracket exits disappeared under 1–2% adverse-fill assumptions. Entry
  search over 1,944 configurations was null. See
  [`RESULT_bandit_search.md`](../../../../joshibot/studies/RESULT_bandit_search.md).
- The old friction module correctly discovered that a vault-shortfall calculation omitted fee
  legs, but its particular constants are snapshots for particular pools. The enduring fact is
  that a small “gross win” can be a net loss and that fees must be derived leg-completely from
  current state. See
  [`friction.py`](../../../../joshibot/shitcoims_paperdesk/friction.py).
- An ambient transaction study estimated 95.3% landing for direct AMM calls versus 59.0% for
  Jupiter overall, while adequately bid Jupiter traffic also landed around 97%. The study itself
  says route and bid were confounded, other traders were the reference population, and dropped
  transactions were invisible. Its useful design contributions are the three-outcome transaction
  model, sign-once rebroadcast rule, and required send-time instrumentation—not a promised 95%
  rate for us. See
  [`RESULT_execution_landing.md`](../../../../joshibot/studies/RESULT_execution_landing.md).
- The projection from 13 hand-selected clips to roughly 2,000 mechanical daily trades was explicitly
  unsupported: it multiplied selection quality by about 240, ignored measured capacity, and was
  already contradicted by the paper desk's earliest closes. See
  [`RESULT_callout_volatility.md`](../../../../joshibot/studies/RESULT_callout_volatility.md).

### 3.3 Operator reports that define requirements

- Coin selection and the decision to arm are initially Ember's, not the machine's.
- There appear to be several different felt types of crackle and several broader dispositions;
  their vocabulary should emerge from use instead of being imposed now.
- Material PnL can come from watching a graph, exiting, remaining attentive while flat, and
  re-entering later.
- A crackle can become “this might send”: recognize some profit and keep meaningful exposure.
- Ember sometimes makes bad calls. The instrument must be able to reveal this without substituting
  a different policy and testing that instead.

## 4. The unit of execution: episode, intervals, clips, and lots

**Proposal:** give every selected mint interaction an `episode_id`. An episode contains:

- the scene in which the mint was selected;
- one or more **inventory intervals** during which token balance was positive;
- **flat intervals** during which Ember continued to watch but held no tokens;
- one or more **clips**, each an actual realized entry/exit cash-flow sequence;
- token **lots** and explicit basis allocation for partial sales;
- disposition transitions, gestures, and immediate/later explanations;
- a terminal resolution chosen by Ember or declared abandoned under an explicit rule.

The episode is not automatically over when inventory reaches zero. A full graph-driven exit can
transition to `FLAT_WATCHING`; a later re-entry opens a new inventory interval in the same episode.
Conversely, merely buying the same ticker days later should not silently reopen an old episode.
The operator chooses “continue this episode” versus “new episode,” with a conservative time-based
suggestion only.

This hierarchy prevents three accounting errors:

1. Calling every re-entry an independent successful trade and losing the flat interval that made
   it meaningful.
2. Calling a partial sale “the exit” while hiding the live risk of the remainder.
3. Averaging several fills into one imaginary position whose intended and executable prices never
   existed.

## 5. Two interacting state machines

### 5.1 Episode state

```text
OBSERVING
   |
   | ARM CRACKLE (bounded conditional authority)
   v
ARMED_FLAT --cancel/expiry--> OBSERVING
   |
   | trigger + fresh executable quote
   v
ENTRY_PENDING --definitive failure/expiry--> ARMED_FLAT or OBSERVING
   |
   | reconciled token acquisition
   v
EXPOSED_CRACKLE
   |          | partial sell + explicit keep/promote
   |          +--------------------------------------+
   |                                                 v
   | full zap / full conditional exit          EXPOSED_RUNNER
   v                                                 |
EXIT_PENDING <---------------------------------------+
   |
   +-- reconciled residual > 0 --> EXPOSED_CRACKLE or EXPOSED_RUNNER
   |
   +-- reconciled residual = 0 --> FLAT_WATCHING
                                      |
                         re-arm ------+---- resolve episode
                            |
                            v
                      REENTRY_ARMED
                            |
                            +-------> ENTRY_PENDING
```

The state names describe authorization and reconciled inventory, not what a chart looks like.
“Runner,” “catalyst,” or any later disposition is orthogonal to venue and cost basis.

`ENTRY_PENDING` and `EXIT_PENDING` cannot be skipped in live accounting. An RPC timeout is not a
failure, and a submitted transaction is not a fill.

### 5.2 Transaction-attempt state

```text
INTENT_RECORDED
   -> QUOTED(slot, state hash, fees, bounds)
   -> BUILT(message hash, blockhash, validity, CU settings)
   -> SIGNED(signature, exact bytes)
   -> SUBMITTED(first send and every rebroadcast)
   -> one of:
        LANDED_SUCCEEDED
        LANDED_FAILED       (fee paid; instructions rolled back)
        NEVER_LANDED        (known only after validity expires)
   -> WALLET_RECONCILED
```

An attempt may be superseded only after its prior bytes can no longer execute or have definitively
failed. A new quote and signature before that point can double-fill.

## 6. Arming is a capability, not a prediction

Pressing `ARM CRACKLE` should create a narrowly scoped, revocable authorization. At minimum it
records:

- mint, episode, wallet, and allowed direction;
- maximum quote spend and/or intended token amount;
- expiry/TTL and whether one trigger consumes the arm;
- maximum concurrent exposure and portfolio reserve that must remain untouched;
- permitted venues and whether a curve-to-PumpSwap transition may be followed automatically;
- maximum total current fee rate, size-specific impact, slippage bound, and network-fee budget;
- the desired net outcome for any automated exit and which fraction may be sold;
- whether any residual may remain, and what disposition it should enter;
- cooldown and maximum number of entries; default one, never an unbounded loop;
- an optional free-form description and provisional crackle tags;
- a content-addressed snapshot of the scene and all inputs available at arm time.

The arm does **not** assert that a dip will occur, that an entry will be profitable, or that the
coin is safe. It says what the machine may do if observed conditions and all safety bounds hold.

`CANCEL` revokes an untriggered arm immediately. If a transaction is already signed/submitted, it
cannot be wished away; the UI must say `ENTRY UNRESOLVED`, stop creating new attempts, and offer a
contingent “exit immediately if this lands” instruction that activates only after reconciliation.

### 6.1 Preserve microdip ambiguity initially

The phrase “microdip” may currently conflate several phenomena:

- a small retracement after a new impulse;
- return to a recently defended local shelf;
- one downswing inside established two-sided oscillation;
- seller exhaustion followed by renewed buying;
- an attention burst cooling without social abandonment;
- a post-launch or post-migration repricing discontinuity;
- a graph gestalt Ember recognizes but cannot yet verbalize.

These are **candidate types**, not the first button taxonomy and not interchangeable percentage
thresholds. The first instrument should store the raw event path, displayed chart transform,
viewport, arm gesture, and optional words. It may also compute counterfactual triggers for several
versioned definitions in shadow. Only prospective episodes can tell us whether the felt types are
stable, useful distinctions.

**Hypothesis H1:** Ember's arm plus a locally meaningful wait improves executable entry outcomes
over buying immediately at the arm gesture.

**Required contrasts:** for each arm, preserve at least (a) immediate-entry quote, (b) each
candidate microdip trigger's first actionable quote, (c) no-entry/expired, and (d) Ember's actual
subsequent gestures. Do not force capital into any counterfactual.

## 7. Exact net-PnL semantics

No automated exit may trigger from market cap, last trade, candle close, percentage above chart
entry, or a vendor's displayed PnL.

For a contemplated sale of `q` raw token units, define:

```text
expected_net_if_sold(q, slot) =
    expected_quote_out_after_protocol_creator_and_LP_fees(q, slot)
  - expected_sell_transaction_fee
  - allocated_confirmed_entry_basis(q)

lower_bound_net_if_sold(q, slot) =
    instruction_min_quote_out(q, slot)
  - maximum_authorized_sell_transaction_fee
  - allocated_confirmed_entry_basis(q)
```

The entry basis must come from confirmed wallet deltas and include:

- quote asset actually debited for the acquired lot;
- entry transaction fee actually paid;
- nonrecoverable account costs attributable under an explicit policy;
- any prior lot basis brought into the episode, separately labeled.

Recoverable rent should be displayed as tied-up capital, not quietly booked as permanent trading
loss. The policy must be explicit and consistent.

**Proposal:** display both expected and lower-bound net. An automated minimum-profit exit fires
only when the lower-bound value clears its target on a quote no older than the configured slot/time
budget. This is conservative by design. The resulting realized PnL is then recomputed from actual
post-transaction deltas; it may differ from both numbers.

For the whole episode, also maintain the cash-flow identity:

```text
episode_wealth_if_liquidated_now =
    sum(confirmed quote proceeds)
  - sum(confirmed quote spends)
  - sum(transaction fees and nonrecoverable costs)
  + executable liquidation value of all remaining tokens
```

This identity is more important than any chosen lot-allocation convention. Lot allocation is still
required to describe individual clips, but the episode total must not change when FIFO is replaced
by average basis.

### 7.1 Fees, impact, size, and capacity

- Fetch and record the applicable dynamic fee config and fee tier at each quote. Cache only with an
  explicit slot/version and invalidate on observed account changes.
- Quote the exact contemplated size against the correct venue state. Linear `size / reserve`
  approximations are diagnostics, not execution prices.
- Keep four different quantities visible: protocol/creator/LP fees, price impact caused by our
  order, allowed adverse drift (`maxQuoteIn`/`minQuoteOut`), and network/account cost.
- Size should be an operator/capital-allocation decision constrained by executable impact and
  portfolio budgets. The old `sqrt(priority_fee * reserve)` optimum answers a narrow friction
  minimization problem; it does not price selection confidence, tail loss, opportunity cost, or
  repeated daily capacity.
- Measure cumulative footprint, not only one-clip impact. Repeated entries/exits in one shallow
  mint can become material even when each individual clip passes a two-percent cap.
- A displayed profit target smaller than the current round-trip hurdle should be visibly
  impossible, not silently rounded up.

**Hypothesis H2:** there is a range of sizes where Ember's selected opportunities preserve positive
net expectancy after dynamic fees, realized impact, landing failures, and graph-driven exits.
There is currently no evidence that this range exists or that it scales.

## 8. Partial profit and retained runners

Partial exit is a first-class action, not a percentage flag on a full close:

- `SELL EXACT TOKENS`
- `SELL FRACTION OF RECONCILED INVENTORY`
- `REALIZE QUOTE AMOUNT`
- `RECOVER CHOSEN CAPITAL AMOUNT, KEEP THE REST`
- `FULL ZAP`

“Recover capital” is nonlinear. The system must solve for the smallest raw token amount whose
current size-specific sell quote meets the requested net proceeds, subject to integer rounding and
safety bounds. Multiplying inventory by a chart percentage is wrong.

After a confirmed partial fill:

1. Reconcile actual tokens sold and quote received.
2. Allocate basis and book realized PnL for the sold lot under the declared convention.
3. Show residual tokens, remaining basis, executable liquidation value, and maximum remaining
   downside.
4. Record whether Ember explicitly retains the residual as the same crackle disposition or promotes
   it to `runner`, `social/catalyst`, or an as-yet unnamed disposition.

The remainder is never “free.” Even when prior proceeds exceed original cash outlay, it has live
market value, opportunity cost, and possibly correlated tail risk. RADON, EarthCoin, and CRASHIUS
are initial product requirements for importing and representing this state, not evidence that the
state is profitable.

An automated partial-profit plan may be armed in advance, but promotion into a longer-lived runner
must be explicit at first. We do not yet know which observed state should authorize the machine to
change the thesis or horizon.

## 9. Graph-driven exit, flat watching, and re-entry

### 9.1 Operator zap

`ZAP` should be the fastest gesture on the surface:

- no confirmation dialog after the operator presses it;
- cancel any unsubmitted conflicting automated intent;
- bind to an exact episode, mint, and reconciled inventory version;
- snapshot the graph, viewport, raw path, flow, quotes, feed state, position state, and portfolio
  alternatives at gesture time;
- request a fresh executable quote immediately and submit within the reviewed slippage/fee bounds;
- visibly distinguish `gesture captured`, `transaction submitted`, `landed`, and `wallet reconciled`.

Fast does not mean unbounded. The operator may override the strategy but should not accidentally
sell the wrong token account, exceed current inventory, or turn an RPC ambiguity into two sells.

The old paper zap's “first observation after gesture” was an honest no-lookahead convention for a
slow tape, but it is not the desired live architecture. In shadow, sample the quote at a realistic
measured action latency after the gesture. In live operation, the quote/send pipeline itself
produces the latency and fill evidence.

### 9.2 Full exit is not necessarily resolution

Once a full exit reconciles to zero inventory, the UI asks non-blockingly whether to:

- continue `FLAT_WATCHING` in the same episode;
- resolve the episode;
- start a new independent watch.

If Ember keeps watching, preserve the graph and social path during the flat interval just as
carefully as during exposure. Otherwise the system cannot learn what avoided drawdown, renewed
strength, or changed social state led to re-entry.

Re-entry is a new arm and a new inventory interval. It never inherits stale limits from the first
entry. It recomputes venue, fee tier, balance, impact, and portfolio budget. The episode total spans
both intervals while each clip retains its own realized result.

**Hypothesis H3:** some value attributed to “coin selection” actually comes from Ember's ability to
move between exposure and flat observation using graph state, then re-enter. Testing only buy-to-
final-sell returns cannot see it.

For every such episode, preserve executable counterfactuals:

- continue holding through the flat interval;
- exit when Ember did and remain flat;
- exit and re-enter when Ember did;
- each counterfactual at the same size and realistic quote latency where observable.

These are descriptive paired paths, not proof of causality; Ember's exit and re-entry are selected
on the path. They are nevertheless much closer to the relevant estimand than pretending the first
position never closed.

## 10. Venue router and migration boundary

The venue is determined from current on-chain state, never from token age or stale metadata:

```text
curve exists and complete == false
    -> quote/build Pump bonding-curve v2 instruction

curve complete, canonical pool not yet observable
    -> MIGRATION_GAP: no trade; continue observing

canonical PumpSwap pool observable and valid
    -> quote/build direct PumpSwap instruction

state contradictory, unsupported quote mint/token program, or only unknown pool
    -> refuse automation; surface exact reason
```

The migration instruction is permissionless and idempotent, but this does **not** imply the crackle
engine should invoke it. **Proposal for the first version:** observe migration; do not initiate it.
Migration is an external state transition, not part of the trading intent.

A race remains possible: the curve completes after quote/build and before execution. The old-venue
transaction should fail atomically rather than be translated mid-transaction. The engine then:

1. reconciles the original signature to landed-failed or waits until it can no longer land;
2. refreshes curve and pool state;
3. recomputes all fees, bounds, and the net target;
4. creates a new attempt only if the arm explicitly allows following migration and has not expired.

No chart series may splice curve and PumpSwap prices without a venue transition marker and a
defined normalization. A manufactured migration candle must never become a microdip trigger.

## 11. Latency is part of the strategy

Capture separate clocks rather than one generic timestamp:

- chain event slot/time;
- node receipt and normalized ingest;
- derived quote start/end and state slot/hash;
- UI render/viewport time;
- operator gesture and local acknowledgement;
- trigger observation;
- transaction build, simulation, sign, first submit, and every rebroadcast;
- landing slot, confirmation observation, and wallet reconciliation.

Derived latencies include market-to-ingest, ingest-to-render, gesture-to-quote, quote-to-sign,
sign-to-first-send, send-to-land, and land-to-reconciliation. Store missing clocks as missing; do
not replace them with ingest time.

**Proposal:** a low-rate whole-market census finds candidates, but an armed or exposed mint is
promoted to a hot lane using chain program events and relevant account subscriptions. A 30-second
board poll may remain context; it cannot arm a stop or net-profit exit.

Every quote carries:

- state slot and account hashes;
- local receipt time;
- venue and fee-config version;
- exact size and direction;
- expected output and instruction bound;
- estimated transaction cost;
- expiry/freshness budget.

If source lag, slot divergence, quote age, or subscription health breaches a reviewed threshold,
new automated entries fail closed. Existing exposure becomes a loud `UNMARKABLE / AUTOMATION
PAUSED` condition; it does not receive a fabricated price. A direct operator zap may use an
independent fresh RPC path, but the degraded state must remain visible.

## 12. Transaction construction and submission proposal

This is a design to validate later, not implementation authority.

1. Use the official, version-pinned low-level SDK to construct one direct venue instruction path.
2. Read all state needed for fees and quotes at a coherent slot where possible.
3. Simulate the exact transaction before signing when latency permits; use the result to bound the
   compute-unit limit. Do not assume the old study's 160,000-CU fallback applies to current v2
   instructions or first-use account initialization.
4. Set `maxQuoteIn` or `minQuoteOut` from the arm's economic limit and current quote. Slippage is a
   maximum loss authorization, not a landing-rate knob.
5. Sign once per attempt. Rebroadcast identical serialized bytes; never change bid, blockhash, or
   slippage while the prior bytes remain valid.
6. Track expiry by `lastValidBlockHeight`, not a wall-clock guess.
7. Reprice and re-sign only after definitive landed failure or expiry, and only while the original
   intent remains authorized.
8. Reconcile from chain and wallet deltas before permitting a dependent sale or new buy.

The old execution study recommends direct Pump/PumpSwap submission and a priority-fee ladder, but
its rates are ambient and predate current instruction shapes. Direct submission is the reasonable
first path because it minimizes routing state and matches the single-venue intent. Its landing and
latency must be remeasured on our own no-capital simulations and eventual explicitly authorized
tiny sends.

Jupiter can remain a reference quote or later fallback study. It must not become a hidden alternate
venue whose price, fee, account set, and failure distribution are blended with direct execution.

## 13. Reconciliation and external activity

The wallet is the source of economic truth, but an RPC balance read without causal provenance is
not enough. Reconciliation joins:

- transaction signature and exact submitted bytes;
- landed metadata, logs, fee, compute consumed, and pre/post token balances;
- Pump/PumpSwap events where available;
- pre/post wallet SOL and token accounts;
- account creation, rent movements, wrapping/unwrapping, and token-program type;
- the expected episode, intent, attempt, and inventory version.

Transaction outcomes are three-valued:

1. `LANDED_SUCCEEDED`;
2. `LANDED_FAILED`—fee paid, state changes rolled back;
3. `NEVER_LANDED`—no chain record, known only after expiry.

Do not collapse the last two into “failed.” Do not call a signature returned by `sendTransaction`
a fill.

Manual wallet activity is expected. If Ember trades in Pump, Padre, or another interface, the
reconciler records an `EXTERNAL_WALLET_ACTION` and asks for episode/lot attribution when ambiguous.
It does not rewrite history to pretend `joshi` submitted the action. Automation pauses for that
mint until the available balance and open intents agree again.

Reservations prevent concurrent intents from spending the same SOL or selling the same tokens.
A transaction binds to a wallet inventory version; any unexpected delta invalidates dependent
unsigned intents.

On restart, rebuild pending state from the append-only intent/attempt ledger and the wallet, not
from an in-memory “open position” cache. An unresolved valid signature resumes monitoring; it is
never blindly rebuilt.

## 14. Safety invariants

These should become executable specifications before live engineering:

### Authority and inventory

1. No transaction exists without an unexpired operator-created capability naming the mint,
   direction, size bound, venue scope, and economic bounds.
2. Filled buys never exceed the arm's maximum quote spend plus its separately authorized network
   and initialization costs.
3. Filled sells never exceed reconciled, unreserved token inventory.
4. Automation never averages down, re-enters, or follows a migration unless that action is
   explicitly authorized.
5. A partial exit cannot silently change the disposition or horizon of the residual.

### Attempts and idempotence

6. At most one executable signed attempt exists for a given logical intent at a time.
7. Identical signed bytes may be rebroadcast; new signed bytes require definitive failure or
   expiry of the prior attempt.
8. Submitted is not filled; filled is not reconciled; no downstream action conflates them.
9. Every terminal attempt has exactly one of the three transaction outcomes plus reconciliation
   status.

### Economic truth

10. Automated profit exits use a current size-specific executable lower bound after fees, costs,
    and allocated confirmed basis.
11. Episode wealth equals confirmed cash flows plus current executable residual value under the
    declared accounting policy.
12. Retained tokens always carry quantity, remaining basis, executable value, and downside; no
    state calls them free.
13. Curve and PumpSwap observations retain venue identity and cannot form an unmarked synthetic
    price move.

### Failure containment

14. Stale, contradictory, unsupported, or missing state blocks new automation and is surfaced.
15. A kill switch revokes all untriggered capabilities and prevents new signatures; it does not
    claim to cancel bytes already sent to the network.
16. Wallet/key authority is isolated from the market-data and model processes. No raw key or seed
    enters the event tape, logs, prompts, or repository.
17. Portfolio-wide maximum at-risk capital, daily realized loss, concurrent exposure, and reserved
    liquid quote balance dominate all per-coin playbooks.
18. No safety invariant relies on a stop filling at its trigger price.

## 15. Adverse cases the design must rehearse

| Case | Required behavior |
|---|---|
| Coin gaps through profit or stop level between events | Quote actual size now; either execute within authorized lower bound or report missed/unfillable. Never backfill trigger price. |
| Buy is submitted and Ember immediately zaps | Revoke further entry attempts; mark `ENTRY UNRESOLVED`; if it lands, reconcile then execute the pre-authorized contingent exit. |
| RPC times out after submit | Continue status/expiry resolution for the exact signature; do not re-sign. |
| Transaction lands but reverts on slippage | Record fee and program/log error; refresh; retry only under still-valid capability. |
| Curve completes during an armed entry/exit | Resolve old attempt; enter migration gap; optionally rebuild on canonical pool only if venue-follow was authorized. |
| PumpSwap virtual quote reserves become nonzero | Quote effective reserves; raw-vault-only adapter fails conformance tests. |
| Dynamic fee tier changes across quote and execution | Instruction economic bounds contain the outcome; trigger is re-evaluated from fresh state for any retry. |
| First-use ATA/volume account must be initialized | Include initialization rent/CU/latency in quote and budget; never compare it to a warmed shadow fill. |
| Manual Padre/Pump transaction changes balance | Record external action, invalidate stale reservations, pause affected automation, request attribution. |
| Partial sell leaves dust or rounds unexpectedly | Reconcile raw units, display residual, and never mark fully flat unless reconciled token balance is zero under explicit dust handling. |
| Sell quote exists but liquidity disappears before landing | Slippage bound reverts rather than accepting an unbounded fill; fee/failure is recorded. |
| Feed disconnects while exposed | Stop new automation; show unmarkable exposure and independent zap-path health; no stale PnL. |
| Process crashes with valid transaction in flight | Recover signature and exact validity from ledger; monitor it; do not rebuild. |
| Model/LLM recommends a trade | Recommendation is an annotation only; it has no signing authority unless Ember separately arms a bounded capability. |

## 16. Shadow-first experiment

### 16.1 Smallest useful slice

Run one human-selected mint at a time with **no transaction submission**:

1. Ember opens a real candidate scene and presses `ARM CRACKLE` with a maximum size and TTL.
2. Promote that mint to the hot event/quote lane.
3. Record raw market events, board/social context, graph/viewport state, current venue, dynamic
   fees, and a fresh size-specific buy and sell quote stream.
4. Evaluate several versioned microdip interpretations side by side without allowing any of them
   to redefine Ember's selection.
5. At a trigger, construct a hypothetical intent and sample the quote again after measured target
   build/sign/send latencies; never “fill” on the triggering tick.
6. Let Ember perform partial-profit, promote-to-runner, full-zap, flat-watch, and re-entry gestures
   against the shadow inventory.
7. Replay the episode and verify that every displayed balance and net result follows the event and
   quote ledger exactly.

The first 20–30 episodes test instrument completeness and interaction naturalness. They do not
estimate profitability. Continue to roughly 100–200 prospective operator arms across chronological
regimes before making claims about selection, trigger, or management value; the required count may
increase based on tail frequency and the number of discovered crackle types.

### 16.2 Shadow outputs

For every arm:

- immediate-entry versus each microdip-trigger quote;
- expected and lower-bound round-trip hurdle at contemplated size;
- whether a trigger remained executable after realistic latency;
- operator actions and scene snapshots at each action;
- partial-exit and runner accounting;
- flat interval and re-entry comparisons;
- censored/unobservable periods, never neutral returns;
- simulated transaction construction/simulation outcome without signature or submit;
- attributable selection, waiting, management, and execution components, with uncertainty.

The shadow ledger must preserve a strict distinction between `hypothetical_quote` and `fill`.
There are no fills in this phase.

## 17. Gate to any tiny-live trial

No live trial is implied by completing this document. It requires a separate explicit review and
authorization. Minimum gates should include:

1. Current official SDK/IDL versions pinned; program/account compatibility tests pass for legacy
   SPL, Token-2022, curve, canonical PumpSwap, and the migration gap.
2. Quote math agrees with official SDK outputs and sampled on-chain outcomes at raw-unit precision;
   dynamic fees and effective reserves are included.
3. Property/state-machine tests establish the invariants above, especially no double-signing,
   overspend, oversell, or disposition-changing residual.
4. Crash/restart and RPC ambiguity drills recover every unresolved attempt without duplicate
   execution.
5. Shadow balances and episode identities reconcile exactly under partial exits and multiple
   re-entries, including imported manual wallet activity.
6. Operator usability test demonstrates that arm, cancel, partial-profit, runner promotion, zap,
   flat watch, and re-entry are faster and less ambiguous than current manual handling.
7. A separately reviewed signer boundary, wallet with deliberately capped funds, portfolio loss
   limits, kill switch, and monitoring exist. The trial size is the lowest economically meaningful
   amount explicitly chosen at that review—not inherited from the old 0.1-SOL paper clip.
8. The first live objective is execution correctness, not PnL. Every send records quote state,
   signature, serialized-message hash, validity, CU settings, submit attempts, all three outcomes,
   logs, fees, and reconciled wallet deltas.
9. Size or autonomy cannot increase automatically after wins. Every expansion is another reviewed
   experiment with held-out chronological evaluation.

The old execution study proposed falsifying its reference class if the first 100 sends landed and
succeeded below 85%. Retain that as a historical prior, not a launch guarantee. Our own failure
taxonomy and latency distribution matter more than matching an ambient headline.

## 18. Research questions enabled by the apparatus

1. Does waiting after Ember arms improve executable entry versus immediate entry, and for which
   retrospectively discovered crackle types?
2. How much value is attributable to selection, wait timing, graph-driven exit, partial realization,
   retained runners, flat intervals, and re-entry?
3. Does operator performance decay from the first choice to the next few choices in the same
   scene? At what attention or throughput does it disappear?
4. Do nominal microprofits survive dynamic fee tiers, first-trade account costs, priority fees,
   impact, failed attempts, and realistic latency?
5. When does “take profit and keep a remainder” improve episode wealth versus full exit, and how
   much runner cemetery risk accumulates?
6. Which pre-exit and pre-re-entry path properties recur, and which explanations appear only in
   retrospective interviews?
7. Does a curve-to-PumpSwap transition create a genuinely different crackle type or only a chart/
   venue artifact?
8. What capacity can the strategy absorb before our repeated footprint and weaker marginal
   selections destroy it?

None of these is answered by this lane. This lane specifies how their answers could become about
the real composite policy.

## 19. Dependencies on other lanes

- **Event tape / time semantics:** immutable raw chain, quote, UI, gesture, and model records;
  explicit event, ingest, render, and action clocks.
- **Whole-market census and hot-lane sensorium:** Pump-like candidate surface plus low-latency
  selected-mint trade/account streams.
- **Interaction capture / glass:** viewport-aware arm, cancel, partial-profit, promotion, zap,
  flat-watch, re-entry, and annotation gestures.
- **Portfolio and accounting:** lots, inventory intervals, episode cash-flow identity, runner
  exposure, opportunity reserve, manual action import, and tax/accounting policy boundaries.
- **Protocol/indexer:** coherent Pump/PumpSwap state, fee config, migration detection, Token versus
  Token-2022 support, quote conformance, and program-upgrade alerts.
- **Safety/signer:** capability enforcement, fund caps, reservations, kill switch, transaction
  idempotence, secret isolation, and audit log.
- **Inference/replay:** chronological counterfactual quotes, realistic latency, censoring, scene
  denominators, episode-level estimands, and exploratory versus confirmatory separation.
- **Disposition/ontology:** evolving crackle and coin-disposition language without baking an early
  taxonomy into the execution core.

The execution core should consume versioned observations and bounded operator capabilities. It
should not depend on any particular predictive model, LLM label, social-transition classifier, or
crackle taxonomy.

## 20. Open design decisions

- What is the minimum economically meaningful tiny-live size once first-use account costs and
  dynamic fee tiers are measured?
- Should a zap authorize any executable price within a portfolio-wide catastrophe bound, or use a
  per-zap bound derived from the latest visible quote? The UI must remain immediate either way.
- Which residual-basis convention best matches Ember's mental accounting while preserving the
  invariant episode cash-flow result?
- How long does a flat-watching interval remain part of the same episode by default?
- Can multiple independent dispositions coexist on separate lots of the same mint, or should the
  first interface keep one disposition per residual inventory?
- Which provider mix gives independent enough hot-lane and zap paths without creating contradictory
  slot views?
- Should account warming be permitted for armed mints, given its rent cost and public footprint?
- What evidence and user gesture authorize following an arm across the migration boundary?
- How should an external manual fill be attributed when it overlaps an unresolved `joshi` attempt?

These are reconciliation questions for the project-level design. They should not be silently
answered by the first implementation.
