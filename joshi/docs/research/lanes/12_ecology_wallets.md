# Lane 12 — territories, launch ecology, and followed-wallet watching

Status: pre-engineering reconnaissance; source/API facts checked 2026-08-16.

## Executive finding

Both ideas are useful, but only after stripping away two misleading names.

**Ecology should initially be a temporal query layer over coin families, communities, launches,
and migrating attention—not a new predictive subsystem.** The smallest valuable abstraction is a
possibly overlapping, revisable **territory**: a person, story, joke, event, aesthetic, or community
niche for which several coins may compete, coexist, succeed one another, or become the provisional
Schelling point. This is already implicit in the fancoin lane's duplicate-family problem. Preserving
the facts needed to reconstruct territories is worthwhile now because launch context, board state,
social composition, and the operator's contemporary interpretation cannot be recovered faithfully
later. Building a grand ecosystem model before the cockpit exists is not worthwhile.

**Wallet watching should be a candidate router, not copy trading.** Ember's curated Pump follows are
part of the human attention policy. When a followed profile's *verified trade signer* touches a coin,
the system may promote that coin—and its competing territory—to the hot lane before a callout or
board transition. It should not buy merely because the wallet bought. The old corpus contains both
the reason to try this and the reason not to automate it: one followed Pump profile wallet really did
trade roughly fifty launches a day at a 45-second median horizon, but its ten-day reconstructed book
lost money, and a second mover inherits latency, impact, and adverse selection.

The combined useful loop is:

```text
Ember follows / watches a Pump profile
              ↓
typed identity map: profile wallet ≠ assumed trading entity
              ↓ verified signed trade, with source coverage
promote mint + provisional territory to the hot lane
              ↓
show the trade, flow, competing launches, communities, quotes, and provenance
              ↓
Ember inspects / dismisses / arms / annotates
              ↓
measure discovery value, attention cost, lead time, and executable shadow outcomes
```

This lane recommends a small prospective pilot piggybacking on the main cockpit slice. It does not
recommend a wallet-copy book or a market-wide ecological model.

## Scope and separation of the two questions

The two objects share evidence but have different claims:

1. **Narrative/community territory:** does knowing the competing family and the movement of people,
   wallets, and attention between its coins improve situational awareness, canonical-coin choice,
   transition recognition, or later estimation beyond treating each mint independently?
2. **Followed-wallet surfacing:** does a trade by a wallet connected to a profile Ember deliberately
   follows provide incremental, timely candidate discovery beyond boards, anonymous flow, and
   callouts, while preserving Ember's judgment as the actual selection step?

Neither question is “do clones go up?” or “are profitable wallets profitable?” Those pale versions
have already produced misleading answers in `joshibot`.

This lane does not cover transaction construction, automated trading, private-wallet deanonymizing,
public allegations about wallet ownership, or a general-purpose entity resolver. All pilots are
read-only and shadow-only under `PROJECT.md`'s current boundary.

## What the `joshibot` compost actually establishes

The local results constrain the design; they do not settle the new questions.

| observed local fact | what it supports | what it does not support |
| --- | --- | --- |
| The imitation study saw 9,708 launches in 9.8 listening hours, 1,001 families of size at least two, and 547 `k=3` onsets. Roughly 70% of families were farm/self-farm rather than multi-deployer convergence. | Launch-family structure is common, and deployer structure must be retained. | Three same-name/image coins define an independent community or a trade. |
| Real family/onset counts were only 1.06×/1.13× an identity-shuffled collision floor. Swarmed hosts survived longer, but matched forward return was null with a slightly negative sign. | Imitation is a useful attention/survival covariate. | A swarm onset is a long entry or “costly signal” of upside. |
| In the funded-clone subset, wallets moving from hosts to clones produced median drain equal to 3.37% of the clone's buying; only 709 of 20,642 family edges had both sides on the high-activity flow tape. | Directional audience/capital migration is observable in principle. | The modal clone takes meaningful capital; most attracted no measurable crowd at all. |
| In the live `glasses` family, rival launches, an arbitration callout, a flow burst, and a provisional “OG” contest formed one intelligible episode. The host-side flow burst preceded the derivative launches. | A territory timeline can explain a scene that a coin-local chart cannot. | That one selected duel validates an ecology strategy or any post-hoc burst rule. |
| The cluster map found systematic avoidance for 223 of 300 tested fleet pairs and directional predation for 12 of 50 ordered pairs. | The market is partitioned and coordinated at the trading-fleet level. | Those fleet “territories” are the same thing as narrative/community territories, or the reported prevalences generalize. |
| The mature-pool copy study found no dedicated leader→follower timing signature at its power floor. One-slot second movers gave up roughly 0.69–0.88% against a 1.37% median closed round-trip edge. | Blind following can consume much of a small edge, and copy claims need dependency-preserving nulls. | No profile wallet can ever be useful for discovery; the population was four mature operator pools, not Ember's curated follows on fresh launches. |
| A later direct watch of `jackduvalcalls` showed the Pump profile wallet was an active trading wallet: 493 Pump coins in ten days, median first-to-last balance-change span 45 seconds, with a complete trade captured 14 seconds after launch. | Profile→trading-wallet identity sometimes is direct and actionable at the surfacing layer. | Profile wallets generally trade, or that wallet is worth copying. |
| The same wallet's ten-day executable reconstruction showed a 17.7% FIFO-round-trip win rate, −40.6% median return, and −179.65 SOL total under an executable-exit mark; its median 60-second coin return after entry was −18.6%. | “Early” and “skilled” are different predicates; an alert must show history and current flow, not a green leader badge. | Every future trade by the wallet will lose, or Ember cannot identify a useful subset. |
| Three other wallets traded 98.8–99.6% of their coins in common with that profile wallet, but timing was symmetric and same-slot activity was also common for a universal-sniper control. | Breadth can identify a coordinated set that timing alone misses. | The wallets are controlled by the same human; a tightly scoped copier and one entity remain observationally equivalent. |
| Pump's mapped social surface returned 1,896/1,896 timestamped outgoing follow edges, and Pump content objects natively carried author wallets and often stable external numeric IDs. | Ember's current social curation and wallet-linked content can be recorded prospectively without a handle-guessing join. | The unsupported endpoints are stable contracts, outgoing edges reveal the whole follower graph, or a social author wallet is always the actual trading wallet. |

The crucial reconciliation is: the old “no copy-trading” result tested whether persistent mechanical
mirroring was visible on a tiny mature-pool universe. The proposed lane tests whether *Ember's
curated social graph plus verified wallet activity* improves candidate surfacing on the whole Pump
launch surface. Those are different estimands.

# Part I — ecological and territory analysis

## A deliberately modest definition of territory

A **territory** is a versioned hypothesis that a set of coins competes for, shares, or succeeds one
another within the same attention niche. The niche can be anchored by:

- a represented person, project, fictional character, institution, or community;
- a real-world event, trend, catchphrase, meme template, image, or aesthetic;
- an existing coin and the derivative launches explicitly referring to it;
- a community's own claim that several coins are alternatives, predecessors, successors, “OGs,”
  or impostors.

Territories are not partitions. A coin can simultaneously inhabit a person territory, a trend
territory, and an imitation family. Membership may be unknown, disputed, time-varying, and visible
to JOSHI only after the market event. A territory therefore cannot be a mutable `territory_id`
column on the coin table.

At minimum, preserve assertions of the form:

```text
TerritoryAssertion
  territory_assertion_id
  territory_subject: person | project | event | phrase | media | coin | unknown
  coin_mint
  relation: depicts | imitates | competes | succeeds | argues_about | community_links
  evidence_ids and method: protocol | metadata | media | text | graph | operator | model
  valid_from / valid_to                 # when the relation allegedly held
  observed_from / observed_to           # when JOSHI could know it
  confidence/status: candidate | supported | disputed | retracted
  resolver/model version
```

The stable entity is the mint. Territory and family membership are revisable interpretations over
immutable evidence.

## Three “ecologies” that must not be collapsed

The compost uses ecological language for several real but different structures:

1. **Launch/narrative ecology:** births, duplicates, derivatives, succession, and competition
   around an attention niche.
2. **Community ecology:** authors, viewers, holders, buyers, repeat participants, and their movement
   or coexistence between coins.
3. **Trading-fleet territory:** inferred wallet clusters that systematically occupy disjoint coin
   universes or sell into one another's entries.

They may interact, but none identifies the others. A farm can launch forty same-image coins without
forty communities. Two fleets can avoid one another because of venue, age, latency, or software
specialization rather than culture. The same social community can deliberately maintain two coins.
Use typed relations, not one graph whose edges all mean “related.”

## Territory dynamics worth making observable

The following vocabulary is descriptive rather than a forced state machine:

- **birth:** the first prospectively observed launch tied to a niche;
- **succession:** a new coin is understood as replacing, reviving, or inheriting from an earlier
  one;
- **duplication:** multiple launches claim substantially the same subject or representation;
- **derivation:** a launch comments on, parodies, opposes, or remixes an existing coin;
- **provisional canonicalization:** one coin currently concentrates enough first-party,
  community, flow, or liquidity evidence to act as the Schelling point;
- **leader switch:** that concentration moves to another coin;
- **fragmentation:** several members retain meaningful, distinct participation;
- **coexistence:** overlap is stable without evidence that one coin is replacing another;
- **migration:** identifiable participants reduce involvement in one member and increase it in
  another in a directed temporal sequence;
- **decay/dormancy:** the territory or a member loses observable participation and executable
  capacity, under known-good coverage;
- **revival:** activity resumes after a measured dormant interval.

“Canonical” is never permanent and never chosen from eventual market cap. The UI should say
`PROVISIONAL LEADER BY <evidence>` and show the alternatives. A correct territory thesis can still
lose money if Ember enters the member the audience abandons.

## Connection to the fancoin lane

Fancoin analysis is the highest-value special case of territory analysis because the represented
subject supplies a relatively stable anchor. Lane 04 already needs coin families, provisional
leadership, audience arrival, fragmentation, and migration. This lane adds the more general case:
the anchor may be a trend or an incumbent coin rather than a verified person.

For a fancoin territory, keep distinct:

- which coin routes fees or claims to represent the subject;
- which coin the subject or their verified account actually mentions;
- which coin contains the coherent Pump community;
- which coin attracts the subject's prior audience;
- which coin holds trading liquidity and executable capacity;
- whether these predicates point to the same mint at the same time.

A fee claim can occur in one branch while social participation or liquidity concentrates in
another. Territory analysis prevents the system from silently calling the fee-linked mint the
canonical coin.

## Facts that must be captured now

The future ecology questions remain answerable only if the tape retains the denominators and the
relations before outcome-aware compression.

### Market-wide, compact census

- every creation with mint, instruction user/signer, declared creator, quote mint, launch mode,
  transaction/slot/index, source and ingest clocks;
- metadata URI response bytes or content hash, text fields, social links, image/media hashes, and
  each later revision observed;
- migrations, canonical and noncanonical pools, venue transitions, current fee-routing changes,
  and loss of quote/executable capacity;
- compact Pump/PumpSwap trades with exact user, mint/pool, side, raw amounts, fee/config reference,
  complete event locator, and enough reserve state to calculate coin-local and cross-coin flow;
- board/feed membership, rank, filters, and source coverage—not merely the coins that received
  clicks;
- source outage and backfill intervals, so absence of rivals or activity is never manufactured.

### Social/community evidence

- raw posts, callouts, mentions, thread edges, deletion/revision state, media, author wallet, Pump
  user UUID, and stable external numeric ID where supplied;
- community header snapshots with unique/repeat-author derivations kept separate from provider
  member/post counts;
- point-in-time profile and handle snapshots, outgoing follow edges, and poll-detected removals;
- first-party participation evidence and social-fee/CTO/creator-routing events as distinct types;
- cross-coin references and explicit “OG,” replacement, impostor, or migration claims as evidence,
  never automatically as truth.

### Operator and machine interpretations

- the family/territory candidates that were actually rendered at every consequential scene;
- Ember's `SAME TERRITORY`, `NOT SAME`, `PROVISIONAL OG`, `AUDIENCE MOVING`, and `NOT ARTICULABLE`
  gestures, when these gestures become useful rather than mandatory;
- rejected candidate memberships and competing alternatives;
- versioned text/image/graph embeddings and LLM assertions with exact inputs and availability time;
- later interviews as retrospective annotations, not edits to contemporaneous membership.

Some fields are backfillable from chain history; the as-known scene is not. Creation metadata may
also point to mutable HTTP resources, social content can be deleted, handles change, and follow
removals are absent from a current out-edge snapshot. Those are the highest-priority facts to record
prospectively.

## Current acquisition feasibility

### What is already feasible

- The existing union of PumpPortal `subscribeNewToken` and Pump's metadata endpoints measured
  roughly 98.8% agreement while the socket was healthy. A retrospective 24-hour census enumerated
  33,202 launches by combining the local chain/balance corpus with Pump's batch metadata route.
- `swarm_detect.py` already extracts exact/squashed symbols, normalized names, metadata URI, image
  URI, deployer, launch time, and candidate imitation families. Its family assertions are useful
  seeds, not a finished territory resolver.
- The ten-day local flow corpus demonstrates that wallet-level market-wide trade data is tractable
  in compact columnar form: 58.7 million priced legs were used by the wallet estimator. Lane 03's
  retention work must decide which compact raw program events and promoted transactions survive in
  the new tape.
- The mapped Pump social surface exposes coin communities, content authors, wallet↔Pump/X numeric
  identity links, batch community headers, and timestamped outgoing follow edges. These routes are
  reverse-engineered and unsupported; dated probes, raw responses, and explicit partial/stale status
  are mandatory.
- Pump's official IDLs and docs supply the on-chain distinction between the signed instruction
  `user`, the declared `creator`, mint, bonding curve, pool, and event authority. The current
  `create`/`create_v2` semantics explicitly allow user and creator to differ, which is why launch
  attribution must retain both.

### What remains incomplete

- There is no documented, stable public Pump API contract for the social routes in the compost.
- External first-party X, livestream, and broader trend events remain a separate source problem.
- Public Pump social data does not expose a complete historical follower set: the observed endpoint
  provides current outgoing edges with follow timestamps, not past unfollows or global in-edges.
- Semantic territory discovery across text and images will have high false linkage and needs Ember's
  prospective adjudication. Exact symbol/image matching misses paraphrase and cultural relation;
  broad embeddings can invent it.
- Market-wide verbose transaction retention is likely wasteful. The event-tape pilot must measure
  compact event volume and promote full transactions for hot, sampled, disputed, and reconciliation
  cases.

## Concrete ecology estimands

The initial goal is to determine whether the abstraction adds information or product value. Useful
estimands include:

1. **Membership quality:** against blinded/prospective Ember adjudication, precision and supported
   recall of exact-metadata, semantic, social-overlap, and composite family proposals, including
   `none of these are related`.
2. **Incremental discovery:** fraction of Ember-recognized territories and rival coins surfaced by
   the family view before Ember or the ordinary Pump surface discovered them independently.
3. **Attention concentration:** time-varying share and entropy of unique authors, repeat authors,
   new buyers, buy/sell flow, board exposure, and executable liquidity across the members known at
   time `t`.
4. **Directed migration:** excess probability/amount that a participant exits or becomes inactive
   in member A and enters/participates in member B, relative to time-, age-, size-, and general
   wallet-rotation-matched alternatives.
5. **Leader-switch and fragmentation hazards:** distribution of time to provisional leadership,
   switch, coexistence, fragmentation, or territory death using only membership/evidence available
   then.
6. **Incremental outcome information:** whether territory state adds chronologically held-out
   information over coin-local age, flow, liquidity, and momentum for survival, usable capacity,
   social transition, and executable episode outcomes.
7. **Operator value:** whether showing territory context changes which mint Ember inspects, avoids,
   arms, retains, exits, or later re-enters, and whether those changes improve episode utility or
   merely consume attention.
8. **Lead/lag:** ordering and latency among anonymous flow bursts, derivative launches, Pump social
   arbitration, first-party participation, board movement, and price/liquidity transitions.

Do not use eventual territory membership, eventual canonical coin, peak market cap, or later-resolved
identity as features at earlier times.

## Ecology failure modes and causal traps

- **Outcome-defined territories.** Grouping only the coins later recognized as the same story and
  picking the eventual winner creates the answer in the label.
- **Collision mistaken for competition.** Common names and ticker reuse are ambient; the old
  detector was only modestly above its collision floor.
- **Factories mistaken for independent demand.** Most observed imitation families were a farm or
  self-farm. Distinct deployers remain only an upper bound on distinct actors.
- **Host movement causes clones.** Rival launches and social arbitration often respond to an
  existing flow burst. A launch-count event study can only rediscover the prior move.
- **Co-trending mistaken for migration.** The same wallet buying two hot coins is not evidence it
  moved from one to the other. Require direction, timing, bounded amounts, and a matched general
  rotation rate.
- **Coin multiplicity mistaken for effective sample size.** Members of one territory share the
  same event and audience. Inference clusters on territories and regimes, not rows or mints.
- **Death and source loss mistaken for abandonment.** A silent social endpoint, gappy launch socket,
  or missing price source is not ecological death.
- **One graph erases edge meaning.** Metadata identity, semantic resemblance, first-funder linkage,
  community overlap, and sell-A→buy-B migration are different claims and need typed evidence.
- **The UI creates canonicalization.** A green `OG` badge can become part of the coordination
  mechanism being measured. Start with evidence and uncertainty; record display exposure.
- **Multiple territories and coexistence are real.** Forcing each coin into one winner-take-all
  family can manufacture migration and erase communities that intentionally coexist.

## Bounded ecology pilot

Piggyback on the first operator-facing cockpit rather than build a separate ecology service.

Run for **14 calendar days**, with at most **20 hot territories at once**:

1. Seed candidates from coins Ember inspects, fancoin watches, high-confidence metadata/image
   families, and followed-wallet hits. Keep an ambient sample of proposed families that Ember never
   opens.
2. At first nomination, freeze the members and evidence available then. Subsequent members append;
   they do not rewrite the initial scene.
3. For each hot territory, capture all launches, social/community changes, compact trade events,
   board exposures, and size-specific shadow quotes for known members.
4. Show a small family strip: exact mint, launch time, relationship evidence, community/flow share,
   and `provisional leader by <metric>`—never one definitive canonical badge.
5. Offer optional `SAME`, `NOT SAME`, `OG FOR NOW`, `MOVING TO`, and free-text gestures. Measure
   burden and disagreement rather than requiring a complete ontology.
6. Produce at least one as-known replay for each territory that exhibited a launch, leader change,
   social transition, migration candidate, fragmentation, or decay. Unresolved territories remain
   censored.
7. Before opening outcomes, freeze a small set of coin-local baselines and territory-context
   comparisons. Treat this as apparatus/product evaluation, not a profitability trial.

### Continue ecology work if

- the family strip repeatedly reveals a live rival, predecessor, successor, or audience movement
  Ember would otherwise have missed;
- prospective membership can express uncertainty without frequent harmful false merges;
- at least one territory variable adds stable descriptive or held-out information beyond coin-local
  flow/age/liquidity, or materially improves Ember's decisions and interviews;
- the extra collection and UI remain subordinate to normal cockpit use.

### Shelve the higher-order ecology layer if

- most proposed territories resolve to ambient collisions, one-wallet launch inventory, or labels
  Ember cannot adjudicate consistently;
- provisional canonicalization is only knowable after the price/flow move and adds no earlier
  situational value;
- directed migration collapses to general wallet rotation under matched nulls;
- territory context does not alter attention or decisions and adds no held-out information beyond
  the existing fancoin family strip and coin-local state;
- maintaining membership and social coverage consumes more operator/system attention than the
  information returned.

Shelving the model does not mean discarding launch, metadata, community, wallet, or operator facts.
Those are shared tape evidence. It means refusing to promote “ecology” into a subsystem when typed
coin-family queries suffice.

# Part II — followed accounts and wallet watching

## Identity mapping: social follow is not wallet control

For each followed account, preserve this typed ladder:

```text
Ember's Pump profile wallet
  └─ social_follow ─▶ followed Pump profile wallet
                         ├─ profile identity / Pump UUID / external numeric ID
                         ├─ authors Pump content
                         ├─ may itself sign Pump trades
                         └─ may have zero observable trading activity

profile wallet or discovered address
  ├─ signed_trade_as_user ─▶ mint/pool                 # direct fact
  ├─ fee_paid_by ─▶ relayer or sponsor                 # not trader identity
  ├─ first_funded_by / co-signed / bundled_with        # typed entity evidence
  └─ co-trades broad coin universe with ─▶ wallet      # coordination evidence
```

Never compress this into `account.trading_wallet` without evidence. In particular:

- A **social follow** says Ember chose to receive or attend to that profile. It is an operator
  selection event, not endorsement and not proof of skill.
- The **profile wallet** is the address Pump associates with the social account. It may be a direct
  trader, a posting/identity wallet, or inactive.
- A **trade wallet** is direct only when that address is the signed `user` of a decoded Pump or
  PumpSwap trade. A transaction merely referencing the address may be dust, an airdrop, a token
  account, a permissionless action, or an unsolicited transfer.
- A **fee payer/relayer** can sponsor many users. It must not be ranked as the trader or merged with
  every customer.
- A **funder or inferred entity cluster** is evidence about coordination/custody, not identity.
  Shared first funding, co-signing, bundle membership, or 99% coin-book overlap must remain separate
  methods. “Same human,” “same system,” and “dedicated copier” can be observationally equivalent.
- A **creator** can differ from the signed launch user under current Pump semantics. Neither is
  necessarily the wallet later trading the coin.

This mapping should be bitemporal: the profile/handle/follow relation can change, and a later entity
inference must not appear in an earlier replay.

## Why watch before callouts without blindly copying

A watched wallet trade is potentially valuable in three ways:

1. **Discovery:** it names a mint Ember has not yet seen.
2. **Attention routing:** the account's identity and behavior may justify opening a high-resolution
   lane earlier than a board or callout would.
3. **Context:** repeated accounts entering, exiting, returning, or moving between a territory's
   coins may help characterize the scene even when no copy action is attractive.

It is not a privileged pre-trade signal. JOSHI learns of the action after the watched trade has
landed or at least been observed by a provider. The leader has already moved the curve. The correct
product event is therefore:

```text
WATCHED WALLET BOUGHT
  exact wallet/profile/evidence, slot and venue
  coin age and watched size
  receipt latency and current quote/capacity
  anonymous crowd before/after the trade
  watched wallet's measured horizon/history with censoring
  competing territory members
  [inspect] [dismiss] [watch]            # no automatic buy
```

If Ember inspects and then arms a crackle, that is a new human selection event. Its performance is
attributed to the composite `wallet surfaced → Ember selected → crackle managed` path, not to a
fictional mechanical copier.

## What must be recorded for wallet-watch questions

### Social selection and identity

- snapshots of Ember's outgoing Pump follows, including provider follow timestamps, first observed
  and last observed; poll diffs for removal, with the initial absence of unfollow history explicit;
- an explicit JOSHI watchlist distinct from Pump follows, with watch start/end, reason or `not
  articulable`, intended use, and whether Ember saw machine history before adding it;
- profile wallet, Pump UUID, stable external numeric ID, handle/display-name history, profile
  follower/following snapshots, and every provider/source assertion separately;
- candidate trade wallets and entity relations with method, evidence, confidence, valid/known
  intervals, contradiction and retraction.

### Direct wallet activity

- exact subscription manifest and coverage per wallet—not merely “the socket was connected”;
- raw vendor message, ingest time, signature if present, later chain slot/block time/finality,
  venue, mint/pool, decoded instruction user/signer, side, raw amounts and post-balance;
- failed/duplicate/out-of-order/provider-only events and chain reconciliation;
- current dynamic fee and size-specific executable quote at event receipt and at fixed latency
  offsets; route loss and quote absence;
- all observed wallet actions, including sells, partial exits, returns, transfers, holdings, and
  venue migrations, rather than buy alerts alone;
- history completeness/left censoring. A wallet whose first observed action is a sell has unknown
  basis; current balances are not trade history.

### Surfacing and operator response

- earliest known source for the mint: launch stream, anonymous flow, wallet watch, board, callout,
  social post, or Ember navigation;
- alert render/viewport time, inspect/dismiss/watch/arm time, attention duration, and whether a
  later recommendation or outcome contaminated the label;
- the contemporaneous candidate set and matched unwatched public-flow events;
- territory promoted with the mint and whether the followed wallet touched the provisional leader,
  a rival, or several members;
- shadow policies only: no trade, immediate second-mover quote, wait-for-dip, Ember's eventual arm,
  and simple exit horizons using the same executable/latency assumptions.

Without buy and sell activity, exact coverage, and alert exposure, the system will recreate a
variance-selected “smart money” leaderboard and call it evidence.

## Current wallet-watch feasibility

### Social follow and profile layer

The 2026-08-15 local API mapping found an unauthenticated Pump endpoint for current outgoing follows.
Every one of 1,896 sampled edges carried a follow timestamp. The endpoint exposes no global incoming
edge list, and the reverse-engineered route is unsupported. A current snapshot can reconstruct when
present edges say they began; only prospective polling can observe later removals. The Pump content
backend also supplies author wallets and wallet↔Pump/X numeric-ID mappings, but the content host is a
third-party provider claim rather than chain truth.

This is enough to seed a candidate list from the accounts Ember actually follows. It is not enough
to infer every account's trade wallet.

### Direct activity layer

Three acquisition routes are available:

1. **PumpPortal `subscribeAccountTrade`:** its current documentation accepts wallet keys and emits
   trades by those accounts across Pump/PumpSwap. It is metered at 0.01 SOL per 10,000 events and
   requires a linked wallet funded with at least 0.02 SOL. The local collector has already measured
   both venues and fixed two silent defects: token-trade mints and account-trade wallets need
   separate key manifests, and free launch traffic cannot be allowed to mask a dead metered feed.
2. **Solana RPC:** official `logsSubscribe` can filter transactions mentioning a single address per
   subscription and returns slot, signature, error and logs. `getSignaturesForAddress` pages confirmed
   transactions referencing an address, and `getTransaction` supplies the full transaction/meta.
   Reference is not authorship: each transaction still needs signed-user and Pump/PumpSwap instruction
   decoding. The one-address log filter also makes a large watchlist operationally awkward.
3. **Program-wide compact events plus a wallet index:** consume Pump/PumpSwap events once, decode the
   signed user from the official IDLs/transactions, and index by wallet. This is likely the durable
   market-wide route if Lane 03's measured event volume is affordable. It gives both watched and
   anonymous-flow baselines, but requires collector completeness and gap reconciliation.

The pilot should run PumpPortal as the low-effort alert path and reconcile every event to chain. It
should simultaneously measure whether the market-wide event tape can replace the vendor before any
architectural commitment.

## Concrete wallet-watch estimands

### Mapping and observability

1. Among profiles Ember follows or explicitly promotes, what fraction have a profile wallet that
   directly signs classified Pump/PumpSwap trades during healthy coverage?
2. For inactive profile wallets, what fraction can be linked to candidate trading wallets by an
   evidence method that survives manual review and a negative-control population? Report each
   method separately; no pooled “resolved” rate.
3. What is per-wallet coverage, provider omission/disagreement, event-to-chain reconciliation, and
   ingest/availability latency?

### Candidate-discovery value

4. What fraction of watched-wallet hits are the first JOSHI source for the mint, and by how many
   seconds do they precede board inclusion, callout, Pump social activity, or Ember's independent
   inspection?
5. Conditional on the complete candidate funnel, how often does Ember inspect, watch, arm, retain,
   exit, or re-enter a wallet-surfaced coin versus matched anonymously surfaced coins?
6. How much operator attention does each account consume per useful inspection or prospective arm?
   Estimate this account-by-account; a global average hides one useful profile in a noisy roster.

### Incremental information and economics

7. At receipt and fixed 1/5/15/30/60-second latencies, what net executable markout, maximum adverse
   excursion, maximum favorable excursion, live-quote duration, and capacity is available for
   Ember's intended size after the watched trade?
8. Does wallet identity add held-out information over anonymous pre/post-trade flow, coin age,
   liquidity, market cap, venue and recent trajectory? This directly tests whether watching the
   wallet adds anything that a market-wide flow detector already knew.
9. For wallet-surfaced coins Ember selects, decompose value into `surfacing`, `Ember selection`,
   `entry timing`, and `management`; never attribute the whole episode to the watched wallet.
10. How stable are each wallet's behavior, horizon, side, sizing, outcomes, and territory preferences
    across chronological sessions and regimes? A leaderboard selected on the same window is not an
    estimator of skill.
11. What is the conservative second-mover penalty relative to the watched trader's own fill and
    relative to Ember's eventual policy? Re-estimate on fresh curves; do not transplant the
    mature-pool 0.69–0.88% number.

## Wallet-watch failure modes

- **Follow selection and left truncation:** Ember often follows an account after seeing something
  impressive. Post-follow performance is the prospective object; prior success is selection
  context, not an independent test set.
- **Profile substitution and impersonation:** similar usernames and homoglyphs are live hazards.
  Resolve exact full wallet addresses, stable IDs and timestamps; never shorten the identity badge.
- **Profile wallet assumed to trade:** one positive case does not make it a platform rule. Require a
  direct signed Pump/PumpSwap action.
- **Reference mistaken for action:** dust, airdrops, transfers, token accounts and permissionless
  cranks can make an address appear in a transaction it did not authorize.
- **Relayer mistaken for entity:** fee sponsorship and co-signing can merge an app's customer base.
- **Fleet ownership invented:** 99% book overlap establishes coordination/specific following, not
  common human control.
- **Copying the selected-for-variance leader:** rankings reward luck and unrealized marks. Include
  dead/unquotable positions and executable liquidation value.
- **Buy-only survivorship:** a wallet can look prescient if its exits, partials, transfers, and open
  bags are absent. Observe the entire lifecycle.
- **Anonymous flow explains the alert:** a watched account may simply participate in a public burst.
  Compare against flow state and earliest-source ordering.
- **Latency and capacity:** the watched fill moves the curve before JOSHI can react. A profitable
  leader can be uncopyable at Ember's size; a losing leader can still surface a coin Ember judges
  differently. These are separate outcomes.
- **Silent keyed-feed death:** a quiet wallet and a dead subscription look identical. Per-key or
  sampled-chain reconciliation and explicit manifests are required; global socket heartbeats are
  insufficient.
- **Alerts alter the policy:** flooding the cockpit with famous-wallet badges may cause FOMO and
  displace Ember's own attention. Begin as provenance-rich, visually modest evidence.
- **Correlated accounts overcount one event:** several watched wallets may be one fleet or react to
  the same launch. Alert once per mint/scene while preserving every wallet event.

## Bounded wallet-watch pilot

Run alongside the ecology/cockpit slice for **14 calendar days**. Start with at most **10–20 Pump
profiles that Ember already follows or explicitly promotes**; do not import a global “smart money”
leaderboard.

### Warm-up and mapping

1. Snapshot Ember's current Pump outgoing follows and record the JOSHI watch start separately from
   the provider's historical follow timestamp.
2. For each promoted profile, resolve the exact profile wallet and identity evidence. Review recent
   chain history only to classify whether that wallet directly signs Pump/PumpSwap trades and to
   estimate event volume; do not search until some correlated wallet can be called “theirs.”
3. Put direct trading profile wallets on one PumpPortal account-trade connection with an exact
   wallet-key manifest. Keep social-only/inactive profiles visible but do not invent trade alerts.
4. Calibrate alert-volume, reaction burden, and meaningful latency during warm-up. Freeze the
   tolerable alert-rate and matching protocol before evaluating the held-out portion.

### Prospective alert loop

5. On every watched trade, append the raw vendor event immediately, reconcile it to the full chain
   transaction, and promote the mint plus provisional territory into a short hot lane.
6. Render only direct evidence and current executable context. Permit `inspect`, `dismiss`, `watch`,
   `arm`, and an optional one-sentence reason. No automatic buy and no “smart wallet” verdict.
7. Retain all sells and partials from the watched account and all operator non-actions. Deduplicate
   the notification while preserving multiple watched wallets in the evidence drawer.
8. For each hit, sample matched anonymous-flow and ordinary-board candidates from the same event
   time. Maintain fixed shadow response/management policies with measured receipt latency and quote
   availability.
9. Report account-level discovery yield, lead time, operator attention, identity-over-flow
   increment, and executable shadow distributions. Do not pool all accounts into one score unless a
   hierarchical estimate shows pooling is defensible.

### Continue a narrow watchlist if

- direct wallet mapping is verifiable for at least some accounts without speculative entity merges;
- one or more accounts repeatedly surfaces coins or territory changes earlier than the existing
  cockpit and at a tolerable alert cost;
- Ember's prospective inspect/arm rate indicates the alerts contain distinctions they actually use;
- wallet identity adds information or discovery value beyond anonymous flow, even if mechanical
  copying remains negative;
- provider events reconcile to chain with sufficiently measured coverage and latency for their
  role as candidate alerts.

### Shelve wallet watching as a strategy input if

- profile→trade-wallet mapping is mostly absent or depends on unvalidated funder/entity inference;
- watched hits arrive no earlier than the anonymous flow/board surface or identity adds no held-out
  information after that flow;
- most alerts are ignored, duplicate already-visible activity, or measurably distort Ember toward
  reactive FOMO;
- ordinary latency, fees, impact, or liquidity make every intended second-mover action
  execution-fragile, and Ember does not derive independent selection value from the surfacing;
- useful accounts are behaviorally unstable enough that a watch becomes stale before it can be
  calibrated;
- source coverage cannot distinguish wallet silence from collector silence.

Even then, keep followed-account identity and public actions in the social tape. Shelving means “do
not use this as a trading/candidate signal,” not “forget which accounts formed Ember's information
environment.”

## How the two lanes compose without becoming a platform detour

The only integration needed in the first cockpit is small:

```text
[watched wallet touched COIN B]
  profile: exact identity + direct-trader evidence
  trade: buy/sell, size, slot, receipt lag
  territory: COIN A / COIN B / COIN C, membership evidence
  shares now: community | buyers | flow | liquidity
  current quote and hot-lane health
  operator gestures
```

This composition matters because a followed wallet may touch the wrong duplicate, an early rival,
or several members. A coin-only wallet alert hides that fact; a territory strip makes it visible.
Conversely, wallet flow can supply the first evidence that a static duplicate family has become a
live contest.

Do not build a graph database, ecological simulator, entity-resolution service, or wallet ranking
pipeline merely to render this card. The event tape can store typed assertions and ordinary
projections can serve the first UI. Architecture should follow measured query and volume needs.

## Dependencies on other lanes

- **Lane 03, event tape:** immutable multi-clock launches/trades/social observations, exact coverage
  manifests, board/choice-set history, bitemporal assertions, hot-lane promotion, and replay.
- **Lane 04, social transition:** stable subject identities, coin families, fee/claim/participation
  distinctions, community evidence and adversarial identity presentation.
- **Lane 05, crackle/execution:** current dynamic-fee quotes, receipt-to-decision latency,
  second-mover shadow fills, route/capacity bounds, and eventual authorization boundaries.
- **Lane 01, accounting:** watched-wallet outcomes must not be confused with Ember's episodes;
  operator episodes need partial exits, flat watching and re-entry.
- **Lane 02 and Lane 08, operator language/product glass:** low-friction follow/watch/territory
  gestures, scene capture, alert burden, exact-address UI, and display-effect logging.
- **Lane 07 and Lane 11, estimation/red team:** adaptive-follow selection, dependency-preserving
  nulls, matched choice sets, chronological confirmation, disappearance, entity leakage, and UI
  counterfactuals.
- **Lane 09, infrastructure/security:** unsupported API health probes, hostile metadata/media,
  read-only identity isolation, rate/credit budgets, and no secret-bearing raw records.

## Unresolved questions for reconciliation

1. Which of Ember's current Pump follows should be socially visible but not placed on the paid
   trade watch? The product should learn this from explicit promotion and measured volume.
2. Does Pump's current profile wallet always equal the wallet field on that profile's authored
   content, and what historical changes are observable?
3. Can a program-wide Pump/PumpSwap event collector index signed users with lower cost and better
   coverage than PumpPortal `subscribeAccountTrade` at the expected watchlist size?
4. How should per-wallet liveness be probed without paying to query every quiet wallet continuously?
5. Which direct wallet activity should promote a hot lane: buys only, first trade on a mint,
   position-size threshold, repeated entries, sells into a territory rival, or an operator-specific
   combination? The pilot should preserve all and display conservatively before choosing.
6. What is the minimally useful territory vocabulary in Ember's own language? “Territory,” “narrative,”
   “family,” “OG,” “rival,” and “migration” may not match the dispositions that emerge in use.
7. Can social/community author movement be observed with enough membership coverage to distinguish
   migration from general cross-posting?
8. How often does a coin belong to several active territories, and can the UI show this without
   turning the family strip into clutter?
9. Does a wallet hit improve discovery specifically for fancoin transitions, or mainly for the
   sub-minute launch-sniping ecology exemplified by the current direct-profile case?

## Sources

Primary/current protocol and provider sources:

- Pump, [Pump Program README](https://github.com/pump-fun/pump-public-docs/blob/main/docs/PUMP_PROGRAM_README.md), for signed `user` trade accounts and the distinction between launch `user` and `creator`.
- Pump, [Coin Creation Accounts](https://github.com/pump-fun/pump-public-docs/blob/main/docs/instructions/COIN_CREATION.md), for current `create_v2` creator and launch-account semantics.
- Pump, [PumpSwap README](https://github.com/pump-fun/pump-public-docs/blob/main/docs/PUMP_SWAP_README.md), for current AMM pool, signed-user trade, event/reserve, and venue semantics.
- Pump, [official public IDLs](https://github.com/pump-fun/pump-public-docs/tree/main/idl), for decoding Pump/PumpSwap instruction users and events.
- Solana, [`logsSubscribe`](https://solana.com/docs/rpc/websocket/logssubscribe), for the one-address `mentions` filter and slot/signature/log notifications.
- Solana, [`getSignaturesForAddress`](https://solana.com/docs/rpc/http/getsignaturesforaddress), for paginated transactions referencing an address.
- Solana, [`getTransaction`](https://solana.com/docs/rpc/http/gettransaction), for confirmed transaction/meta retrieval.
- PumpPortal, [real-time data API](https://pumpportal.fun/data-api/bonk-fun-data-api/), for `subscribeAccountTrade`, `subscribeTokenTrade`, one-connection guidance, and the current funded-key requirement.
- PumpPortal, [fees](https://pumpportal.fun/fees/), for the current 0.01 SOL per 10,000 metered trade messages rate. PumpPortal is a third-party provider, not protocol authority.

Local measured sources in the `joshibot` compost:

- `studies/RESULT_imitation_signal.md` and `shitcoims_scalper/swarm_detect.py`: launch census,
  candidate-family semantics, collision nulls, farm/parasite distinction, survival result, source
  gaps and ingestion latency.
- `studies/RESULT_pvp_vamps.md`: directed host→clone drain, funded-clone selection, the live
  `glasses` duel and ordering of chain flow, derivative launches, and social arbitration.
- `studies/RESULT_cluster_map.md`: fleet avoidance, directional predation, co-firing, and the warning
  that synchronized launch entry is confounded by universal sniping.
- `studies/RESULT_copytrading.md`: dependency-preserving copy tests, second-mover penalty on mature
  pools, relayer/fee-payer traps, and variance-selected leaderboards.
- `studies/RESULT_caller_wallets.md`: callout/crowd ordering, the failure of handle→wallet inference,
  and anonymous flow outperforming caller identity in that cohort.
- `studies/RESULT_jackduval_workup.md`: a direct profile/trading-wallet case, sub-minute horizon,
  complete prospective watch, negative ten-day economics, coordinated-wallet ambiguity, and two
  silent subscription defects.
- `studies/RESULT_pump_social_api.md`, `shitcoims_pumpsocial/endpoints.py`, and
  `shitcoims_pumpsocial/models.py`: dated unsupported social/profile/follow routes, native author
  wallets, numeric identity joins, outgoing-edge timestamps, missing in-edges, and mutable-profile
  caveats.
- `shitcoims_scalper/firehose.py`: per-feed key types, subscription manifests, metered-stream health,
  and current PumpPortal account-trade observations.
- `studies/RESULT_wallet_estimator.md`: executable wallet-history context and the warning that wallet
  behavior ranks situations without identifying intent or human ownership.

