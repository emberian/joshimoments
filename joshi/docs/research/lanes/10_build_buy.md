# Build versus buy: the apparatus boundary

Survey date: 2026-08-16  
Status: research input, not an architecture or purchasing decision

## Executive finding

There is plenty of reusable plumbing. There is almost no off-the-shelf product that represents
the object this project is trying to measure.

We should buy or reuse transport, official protocol builders, chart primitives, query engines,
wallet connectors, and (only when measurement justifies it) managed low-latency infrastructure.
We must build the evidence semantics: the market surface Ember could have seen, the attention
funnel, episodes with flat intervals and re-entries, evolving dispositions, executable-value
accounting, social-state transitions, gesture capture, and deterministic replay.

That boundary is not an expression of “not invented here.” It is forced by the estimand. A vendor
can deliver a Pump trade or a candle. It cannot know whether the event was presented, entered the
viewport, was inspected and rejected, began a crackle, became a runner, was exited while Ember
kept watching, and was re-entered within the same episode. Outsourcing those meanings would
compress away the evidence before it exists.

The current recommendation is therefore:

1. Define provider-neutral evidence envelopes and protocol adapters.
2. Start with official Pump/PumpSwap and Meteora SDKs, open chart/UI components, a conventional
   transactional store, and immutable raw files.
3. Run provider shootouts against our workload before buying a “fast” data or landing plan.
4. Treat lawful, stable access to Pump's candidate and social surface as the largest unresolved
   product dependency and an explicit go/no-go gate for calling the product a Pump replacement.
5. Do not outsource accounting, scene reconstruction, ontology, or operator interaction data.

No account was created, service purchased, API key requested, or transaction constructed or sent
for this survey.

## Decision rule

A component is safely reusable when replacing it would not change the meaning of recorded
evidence. A component must remain ours when replacing it could change what the system says Ember
saw, believed, intended, owned, or could actually have liquidated.

| Layer | Reuse / buy | Keep bespoke | Initial posture |
|---|---|---|---|
| Solana transport | JSON-RPC, WebSocket, Yellowstone-compatible gRPC, archive RPC | gap detection, deduplication, commitment/fork handling, source comparison | adapter plus measured provider shootout |
| Protocol access | official Pump, PumpSwap, Meteora SDKs and IDLs | version pinning, conformance fixtures, state snapshots, fee/quote evidence | reuse official code; never rederive the program casually |
| Routes and landing | Jupiter, ordinary RPC, Jito, or a managed sender | route policy, freshness bounds, net-profit gate, outcome telemetry | shadow comparison first |
| Market surface | raw on-chain events and any authorized platform/source APIs | candidate membership/rank, viewport and attention trace, contemporaneous alternatives | bespoke surface recorder |
| Social and identity | authorized Pump access, X API, public identity sources | entity graph, evidence strength, temporal state transitions, uncertainty | source adapters around our graph |
| Charts | Lightweight Charts; possibly licensed Advanced Charts later | candle construction, executable overlays, drawings/gestures, exact viewport replay | Lightweight Charts proof of concept |
| Storage/query | PostgreSQL, Parquet, DuckDB; ClickHouse only after a benchmark | event envelope, immutable/raw policy, reducers, lineage, point-in-time semantics | simple local-first stack |
| Wallet connection | Solana Wallet Standard; optionally policy-backed managed signing later | episode ledger, lots, inventory intervals, disposition transitions, opportunity cost | read-only reconciliation first |
| UI shell | React + TypeScript + Vite; Tauri only if desktop capabilities earn their cost | the cockpit, gesture language, interview/replay experience | browser-local vertical slice |
| Product analytics | generic session replay may be supplementary | domain events are canonical; never infer decisions from pixels alone | do not depend on an analytics SaaS |

## 1. Solana event streams and history

### What is available

Solana's standard WebSocket API is enough for a cheap first experiment. `accountSubscribe`
delivers account changes with a slot context; `logsSubscribe` can filter transactions mentioning a
public key, although the `mentions` filter accepts only one key per subscription. It provides no
native historical replay. ([Solana `accountSubscribe`](https://solana.com/docs/rpc/websocket/accountsubscribe),
[Solana `logsSubscribe`](https://solana.com/docs/rpc/websocket/logssubscribe))

For a whole-program census and hot per-coin streams, Yellowstone gRPC is the useful commodity
boundary. Its open protocol filters transactions by included/required/excluded accounts and
accounts by address or owner. The server is AGPL-licensed, so consuming a compatible managed
endpoint is easy to move between; modifying and distributing a server has different licensing
implications. The project is also moving quickly: its July 2026 changelog includes a fix for a
silent `from_slot` block-replay gap and several breaking releases. That is evidence for pinning
client/protobuf versions and testing replay, not against using Yellowstone.
([Yellowstone repository](https://github.com/rpcpool/yellowstone-grpc),
[Yellowstone changelog](https://github.com/rpcpool/yellowstone-grpc/blob/master/CHANGELOG.md))

Representative managed offerings currently expose materially different recovery semantics:

- Helius LaserStream offers Yellowstone-compatible gRPC, failover, reconnect support, and up to
  roughly 24 hours of slot replay. Helius explicitly says messages are not guaranteed to arrive in
  order. Mainnet access begins on its Business tier according to the current docs.
  ([LaserStream](https://www.helius.dev/docs/laserstream),
  [LaserStream FAQ](https://www.helius.dev/docs/faqs/laserstream))
- QuickNode's Yellowstone-compatible service advertises a `fromSlot` replay window of up to 3,000
  recent slots (approximately 20 minutes), and includes gRPC on its Scale and Business plans.
  ([QuickNode gRPC overview](https://www.quicknode.com/docs/solana/solana-grpc/overview),
  [plan details](https://www.quicknode.com/blog/solana-grpc-is-now-included-with-scale-and-business-plans))
- Triton Dragon's Mouth is the upstream managed implementation behind Yellowstone and recommends
  gRPC over traditional WebSockets for backend clients. Triton's Old Faithful exposes full-ledger
  history as an open-source archive, but its managed gRPC history was still described as private
  beta in the current documentation. Its ordinary deep BigTable fallback is listed at $25 per
  million queries with a $25 monthly minimum when used.
  ([Dragon's Mouth](https://docs.triton.one/project-yellowstone/dragons-mouth-grpc-subscriptions),
  [Old Faithful](https://docs.triton.one/project-yellowstone/old-faithful-historical-archive),
  [archive access and price](https://docs.triton.one/chains/solana/old-faithful-historical-archive-1))

Helius's formerly convenient Enhanced Transactions parser is deprecated and is not receiving new
parser types. Its newer `getTransactionsForAddress` returns complete transactions with time/slot
filters, chronological ordering, token-account inclusion, and unlimited mainnet retention. It is a
useful wallet-history accelerator, but our protocol decoders must remain authoritative because a
generic parser can lag new Pump instructions.
([deprecation notice](https://www.helius.dev/docs/enhanced-transactions/overview),
[`getTransactionsForAddress`](https://www.helius.dev/docs/rpc/gettransactionsforaddress))

Curated data products can accelerate exploration. Bitquery, for example, publishes Pump/PumpSwap
GraphQL, WebSocket, gRPC, Kafka, and historical query shapes for launches, trades, curves, and
migrations. Those normalized rows are excellent as an independent comparator or fast exploratory
dataset; they should not replace canonical transaction/event bytes because the vendor applies
parsing and, in some products, MEV filtering and a bounded “recent” window.
([Bitquery Pump API](https://docs.bitquery.io/docs/blockchain/Solana/Pumpfun/Pump-Fun-API/))

### What we should reuse

- A Yellowstone-compatible stream when standard WebSockets demonstrate an actual gap, throughput,
  or latency problem.
- Standard archive RPC or a managed history query for backfill.
- Official Solana transaction/account representations and commitment metadata.
- One independent, derived provider only as a completeness/normalization cross-check.

### What we must build

The canonical ingest record needs, at minimum, source identity, source event ID, signature, slot,
transaction index where available, commitment, source time, ingest time, local monotonic receive
time, raw-payload location and hash, decoder version, and observed missingness. Raw transaction
bytes and program event bytes must survive derived schema changes.

We also need our own:

- idempotency keys and duplicate handling;
- processed/confirmed/finalized transitions and fork correction;
- watermarks and explicit gap records;
- reconnect/replay verification rather than trust in a successful reconnect;
- cross-provider completeness and latency measurements;
- census-to-hot-lane promotion without losing the preceding scene.

The adapter boundary should be our normalized *transport event*, not a provider's enriched trade
object. Provider-specific enhancements may be retained as versioned annotations.

### Smallest useful test

Run a 72-hour, read-only stream for the Pump, PumpSwap, and Pump Fees program IDs through two
independent paths available without a new purchase. After finalization, backfill the same slots and
compare the signature/instruction sets. Intentionally disconnect each live path and verify recovery.
Report recall, duplicates, out-of-order distance, gap duration, event-to-receive latency, bytes,
and estimated monthly cost. A provider is ineligible if it can silently resume after a gap.

Do not select Helius versus QuickNode versus Triton from advertised latency. Select after this test,
then retain a cheaper independent audit path.

## 2. Pump, PumpSwap, and LP protocol access

### Official protocol code is good plumbing

Pump publishes IDLs plus official TypeScript and Rust clients. Its current public interface urges
integrators onto unified `buy_v2`, `sell_v2`, and `buy_exact_quote_in_v2` instructions; it also
supports SOL- and USDC-paired coins through the same account layout. The TypeScript SDK had reached
1.36.0 in the npm version history at survey time. PumpSwap's official SDK was at 1.19.0 and had been
published again within the preceding two weeks. This pace makes exact package/IDL provenance part
of every quote and transaction fixture.
([Pump public docs](https://github.com/pump-fun/pump-public-docs),
[`@pump-fun/pump-sdk` versions](https://www.npmjs.com/package/@pump-fun/pump-sdk?activeTab=versions),
[`@pump-fun/pump-swap-sdk`](https://www.npmjs.com/package/@pump-fun/pump-swap-sdk))

The SDK and IDL should build/decode instructions; they should not define our domain objects. Wrap
them behind a thin protocol adapter, pin exact versions, retain the package and IDL checksums in
build provenance, and maintain fixtures for every instruction variant seen on-chain.

Quotes must read current accounts and fee configuration. Pump fees are dynamic by market-cap tier
and Pump warns that displayed fees can change; PumpSwap now prices against effective quote reserves
including a `virtual_quote_reserves` field, so reading vault balances alone is no longer a safe
quote implementation.
([Pump fees](https://pump.fun/docs/fees),
[PumpSwap state and quote semantics](https://github.com/pump-fun/pump-public-docs/blob/main/docs/PUMP_SWAP_README.md))

For the LP book, Meteora publishes an official `@meteora-ag/dlmm` SDK with position discovery,
bin-level liquidity, exact-in/exact-out quotes, partial withdrawal by bin range, fees/rewards, and
rebalancing helpers. We should reuse these instructions and math while keeping the LP's economic
interpretation, opportunity budget, and transition history in our ledger.
([Meteora DLMM reference](https://github.com/MeteoraAg/docs/blob/main/developer-guides/dlmm/typescript-sdk/reference.mdx),
[DLMM SDK](https://github.com/MeteoraAg/dlmm-sdk))

### Conformance test, not faith

For sampled states spanning bonding curves, graduated canonical PumpSwap pools, SOL/USDC pairs,
Token/Token-2022, cashback/mayhem variants, and several trade sizes:

1. Snapshot every account and fee/config input at a known slot.
2. Compute official-SDK buy and sell outputs.
3. Compare with an independently decoded program event or no-signature simulation where safe.
4. Persist integer inputs/outputs, rounding, fees, impact, account slot and package/IDL hashes.
5. Repeat the fixtures on every SDK/IDL upgrade.

No floating-point UI number is permitted in protocol math. A package upgrade that changes a fixture
requires explanation before deployment.

## 3. Executable quoting and route choice

### Direct and aggregated paths solve different problems

For a Pump bonding curve or canonical PumpSwap pool, the official SDK gives a transparent direct
path with fewer remote dependencies. Jupiter Swap V2 gives an excellent independent quote and
fallback path: `/order` returns a quote and assembled transaction from competing routers and
`/execute` handles landing; `/build` exposes raw instructions when custom composition is required.
Jupiter lists both Pump.fun and Pump.fun AMM for instant routing, but later removes markets that
fail its liquidity criteria, and its `/build` path can return no route where `/order` finds a
non-Metis route.
([Jupiter Swap V2](https://developers.jup.ag/docs/swap/order-and-execute),
[market listing rules](https://developers.jup.ag/docs/swap/routing/market-listing))

Therefore Jupiter cannot be the only quote source for the early, small coins that define much of
this project. Nor should direct routing be assumed best after graduation or fragmentation across
venues.

PumpPortal is a useful off-the-shelf baseline, not a suitable default execution substrate for the
crackle hypothesis. Its current fee page lists 0.5% for its local transaction API and 1% for its
Lightning API, in addition to protocol/network costs. That additional friction can consume the
entire target edge. Its token/account trade stream is also metered at 0.01 SOL per 10,000 delivered
events, which makes an unfiltered whole-market firehose a cost question rather than “free data.”
([PumpPortal fees](https://pumpportal.fun/fees/),
[trading API](https://pumpportal.fun/trading-api/))

### The quote artifact is ours

Every decision-facing quote should record:

- exact input size and denomination;
- expected and minimum output in integer units;
- direct venue or complete route;
- all protocol, creator, LP, platform, priority and tip costs;
- price impact and account-creation/rent effects;
- the slot/state hashes from which it was computed;
- request/response timestamps and expiry/freshness bound;
- whether it was informational, arm-triggering, submitted, landed, or counterfactual;
- for an exit, net cash after the actual acquired lot and all round-trip costs.

That is more important than choosing a router early. “Price” is a lossy display field; a
size-specific executable quote is evidence.

### Smallest useful test

Collect a shadow corpus of direct SDK and Jupiter quotes for selected and surfaced-but-skipped
coins, at the intended clip sizes, before and after migration. Do not send. Measure quote RTT,
coverage, disagreement, age, fee completeness, and how each quote predicts the next executable
state. A route becomes eligible only after it produces a complete explainable cost breakdown and
freshness metadata.

## 4. Transaction landing

Landing is reusable infrastructure, but vendor performance claims are not transferable evidence.

Available paths include:

- ordinary `sendTransaction` through an RPC with staked connections;
- Jito's direct `sendTransaction` proxy or atomic bundles of up to five transactions. Jito's proxy
  always skips preflight; bundle acceptance does not mean the bundle landed, and auction tips are
  dynamic. ([Jito low-latency send](https://docs.jito.wtf/lowlatencytxnsend/))
- Helius Sender, which currently dual-routes to validators and Jito, exposes regional endpoints,
  consumes no API credits, and requires both a tip and priority fee. Its fast path also mandates
  skipped preflight. ([Helius Sender](https://www.helius.dev/docs/sending-transactions/sender))
- Jupiter `/execute`, which manages slippage, priority fee, broadcasting and confirmation for its
  `/order` transaction. ([Jupiter execute](https://developers.jup.ag/docs/api-reference/swap/execute))

We should make transaction construction, simulation, signing, sending and reconciliation separate
stages. A send adapter receives the same immutable signed bytes where the service permits it and
returns provider acknowledgements; only the chain decides the outcome. Sending through multiple
paths may be useful because a Solana signature deduplicates identical bytes, but this must be
validated per path and must never regenerate differently signed “equivalent” transactions that
could both land.

The eventual landing experiment, after explicit execution authorization, should randomize eligible
small transactions among direct RPC, Jito, Sender, and/or Jupiter by contemporaneous regime. Record
construction time, simulation, quote age, fee/tip bid, first acknowledgement, processed/confirmed/
finalized slots, failure reason, realized amounts, and all cost. Until then, log shadow route
availability and latency only.

## 5. Pump's product surface, community data, and identity

### This is the highest build-versus-access risk

Pump publishes its on-chain programs, IDLs, fees, and SDKs. It does not publish a supported public
developer API for the complete New/Trending/Live/Callouts/community/post surface in the official
protocol repository. A third-party reverse-engineered catalog currently shows hundreds of frontend
routes, including boards, communities, profiles, live content, candles and trades. That proves the
web product has useful endpoints; it does **not** turn them into a supported contract or grant a
right to archive them.
([official Pump repositories](https://github.com/pump-fun),
[example reverse-engineered June 2026 catalog](https://github.com/BankkRoll/pumpfun-apis/blob/main/captures/2026-06-17/INDEX.md))

Pump's current general terms say access through bots is possible “as we may permit from time to
time,” subject to the terms, grant only the necessary non-commercial personal-use IP license, and
disclaim continuity, timeliness, completeness, and accuracy. That is not a durable social-data SLA.
([Pump Terms, updated 2026-05-02](https://pump.fun/docs/terms-and-conditions))

Before a continuous collector scales, this project needs an explicit terms/access review and,
ideally, documented permission or a supported interface. Three outcomes must remain distinct:

1. Official/supported access: build a versioned adapter and fidelity monitor.
2. User-side personal capture of information actually rendered to Ember: consider only after a
   terms/privacy review, with rate limits and no bypass of controls.
3. No lawful/stable access: build from public on-chain and authorized social sources, but do not
   claim it reproduces Pump's information surface. That outcome materially weakens the “better than
   Pump” foundation and triggers project re-evaluation rather than wishful substitution.

### External social sources are selective enrichments

X is an important identity and catalyst source, but whole-market ingestion is not cheap or
instantaneous. Its current pay-per-use documentation lists $0.005 per post read and $0.010 per user
read. Filtered Stream permits 1,000 rules and one pay-per-use connection, and documents roughly
6–7 seconds P99 delivery latency. That can be appropriate for fancoin/social transitions; it is not
the timing source for a microdip trigger.
([X pricing](https://docs.x.com/x-api/getting-started/pricing),
[Filtered Stream](https://docs.x.com/x-api/posts/filtered-stream/introduction))

Use X selectively for resolved persons, handles, project names, cashtags, and links promoted from
the census/attention funnel. Set a hard spend cap and record query/rule versions so “not observed”
does not become “did not happen.” Pump posts, X posts, on-chain social-recipient claims, creator-fee
sweeps, profile changes and human public participation are separate source events, not a single
`claimed` boolean.

Other networks should be demand-driven enrichments, not another indiscriminate firehose. Farcaster
is unusually reusable because its developer stack supports syncing the public network to a local
Snapchain/replicator, and its client exposes cross-platform account verifications for X, GitHub and
Discord; the latter endpoint is explicitly beta and unstable. This could strengthen entity joins
when a watched community actually uses Farcaster, but there is no reason to operate it before a
prospective sample shows incremental coverage.
([Farcaster local analysis paths](https://docs.neynar.com/farcaster/developers),
[Farcaster client and verification API](https://docs.neynar.com/farcaster/reference/farcaster/api))

### What must be bespoke

- An identity graph with time-bounded edges among coin, mint, Pump profile, numeric social ID,
  handle, person/project, wallets, fee recipients, deployers and communities.
- Evidence strength and contradiction: asserted, platform-verified, on-chain, inferred, stale,
  ambiguous, or retracted.
- Temporal social states and transitions without backfilling today's creator/identity into the
  past.
- Raw post/thread/media references and source timestamps, plus explicit missing/deleted content.
- Versioned LLM/OCR/embedding interpretations that can be recomputed and never overwrite sources.
- Privacy, retention and deletion handling for user content.

No commercial “social sentiment score” should be admitted as a fact. It may be stored as one
vendor's timestamped annotation after its inputs and coverage are understood.

### Smallest useful test

For 24 hours, sample the Pump surface visible to Ember and compare it with every candidate/social
event our authorized sources capture. Measure new-token coverage, board membership and rank drift,
post/thread completeness, identity joins, deletion/update behavior, delay, and authentication
expiry. Preserve screenshots only as a secondary audit artifact; structured point-in-time records
are primary. The test must identify each field as public on-chain, public social, Pump-only,
derived, or unavailable.

## 6. Charting and visual annotation

TradingView Lightweight Charts is the strongest starting primitive: it is a small interactive
financial canvas library, supports custom plugins, and is Apache-2.0 with a required TradingView
attribution/link notice. It had current v5 releases in 2026.
([Lightweight Charts](https://github.com/tradingview/lightweight-charts),
[documentation](https://tradingview.github.io/lightweight-charts/))

TradingView Advanced Charts has the rich drawing surface that may eventually matter for eliciting
chart-shape judgments, but access requires approval, the library is private and non-redistributable,
and it cannot be committed to a public repository. It should be evaluated only after Ember's use of
simple marks/regions demonstrates that richer drawing is a bottleneck.
([Advanced Charts access terms](https://www.tradingview.com/charting-library-docs/latest/quick-start/))

We still build:

- candles from our event tape at arbitrary event-time resolutions;
- trade, reserve, executable buy/sell quote, fill, fee and inventory overlays;
- crosshair-synchronized social and operator events;
- marks, regions and freehand annotations with data coordinates;
- exact viewport state: time/price bounds, scale mode, resolution, overlays and selected coin;
- deterministic scene replay from a chosen knowledge-time cutoff.

The chart library is a renderer, not the market record. Vendor candles may be displayed only as a
comparison series. A screenshot is useful for interviews but cannot replace the data, coordinate
transform, and visible alternatives that created it.

The proof-of-concept acceptance case is not “draw a candlestick chart.” It is: replay RADON,
EarthCoin, and CRASHIUS with Ember's actual clips, flat intervals, re-entries, partial realization,
remaining exposure and annotations aligned to the social/market tape.

## 7. Storage and deterministic replay

### Reuse boring storage; own the log

An initial stack does not need Kafka, a lakehouse, or a cloud warehouse:

- PostgreSQL for mutable control-plane state, identities, episodes, annotations, reducer versions,
  and indexes. Native range partitioning remains available if tables become large.
  ([PostgreSQL partitioning](https://www.postgresql.org/docs/current/ddl-partitioning.html))
- Append-only, content-addressed raw payload/media files and partitioned Parquet exports for durable
  evidence and portable analysis.
- DuckDB for local chronological studies and replay audits; it reads/writes Parquet directly with
  filter/projection pushdown and can unify evolving schemas by name.
  ([DuckDB Parquet](https://duckdb.org/docs/stable/data/parquet/overview),
  [schema evolution tips](https://duckdb.org/docs/stable/data/parquet/tips))

SQLite is acceptable for a disposable single-process prototype. PostgreSQL is preferable as soon
as ingest, reducers, UI and annotation workers run concurrently. ClickHouse becomes attractive only
if measured whole-market event volume or interactive scans exceed this stack; Parquet keeps that
migration reversible. A broker such as Kafka/Redpanda becomes warranted only when durable fan-out,
backpressure and multiple independent consumers are demonstrated problems.

### Replay semantics are not purchasable

The source log must distinguish at least:

- event time, source publication time, ingest time and interpretation time;
- chain slot/commitment versus wall clock;
- raw observation, correction/tombstone, enrichment and machine interpretation;
- what was known at decision time from what was learned later;
- schema version and reducer/model/prompt version;
- absence from “not collected,” “source unavailable,” and “collected zero.”

Reducers should be pure enough that replaying the same raw manifest with the same code/config
produces the same state hash. Derived tables are caches and can be discarded. A raw-file manifest,
hashes and backup/restore drill matter more than a fashionable database choice.

### Smallest useful test

Record one complete session, stop every derived service, rebuild all views from the raw manifest,
and compare state hashes and the rendered episode. Then replay from a cutoff immediately before a
gesture and prove that no later identity, price, post, fill or annotation leaks into the scene.

## 8. Wallet access and accounting

### Connection/signing can be reused

For explicit user-authorized actions, Solana Wallet Standard and its wallet-adapter ecosystem are
the interoperable starting point. The newer `@solana/kit` is the maintained JavaScript SDK, while
Pump's official examples still use its documented compatible client shapes; protocol adapters can
contain that mismatch.
([Wallet Standard](https://github.com/anza-xyz/wallet-standard),
[`@solana/kit`](https://github.com/anza-xyz/kit))

If unattended, pre-authorized execution is eventually proven necessary, a managed policy-backed
signer may be safer than placing a raw hot key in an application process. Privy, for example,
documents Solana program-instruction policies, transfer limits, allow/deny lists, time-bound
signers, key quorums, and TEE enforcement. It also documents app/server execution on behalf of a
wallet. This is an option to test, not a present recommendation: a policy service adds availability,
account, pricing and migration dependencies, and some controls may be enforced outside its enclave.
([Privy wallet controls](https://docs.privy.io/security/wallet-infrastructure/policy-and-controls),
[Solana policy primitives](https://docs.privy.io/controls/policies/overview))

Before any managed signer is accepted, demonstrate on a non-valued test wallet that it can deny:

- every program except the exact allowed Pump/PumpSwap/Jupiter/system/token instructions;
- SOL transfers other than enumerated protocol, ATA/rent, priority and tip destinations;
- amounts above per-action, per-mint, per-episode and daily limits;
- stale blockhashes, unexpected additional instructions, key export and policy mutation;
- actions after the arm TTL or operator zap.

If the service cannot express and independently enforce those invariants, it does not solve the key
custody problem.

### Accounting cannot be bought

Portfolio APIs can return balances and categorized transactions. They cannot infer Ember's episode
boundary, the fact that an exit began a watched-flat interval, a later re-entry, a crackle-to-runner
transition, or the counterfactual capital Ember consciously reserved.

Our ledger must reconcile:

- chain transactions, instructions, token/native balance deltas, fees and account rent;
- orders/intents, sends, landing attempts and fills;
- token lots and inventory intervals;
- realized gross and net PnL;
- remaining basis and size-specific executable liquidation value;
- episode and disposition transitions independently of position openings/closings;
- LP deposits/withdrawals, composition changes, fees and impermanent inventory conversion.

The first acceptance test is read-only reconstruction of the current `shitcoims` wallet, especially
RADON, EarthCoin and CRASHIUS. On-chain beginning balance plus decoded deltas must equal current
balances exactly, and every unexplained delta must remain explicit rather than being assigned to
“PnL.” Ember should be able to correct episode grouping without rewriting the immutable chain facts.

## 9. UI framework and local operator glass

React + TypeScript + Vite is a low-risk default for the first local cockpit. React fits the many
explicit visual states, and Vite provides a small client-side TypeScript/React build without forcing
server rendering or a deployment platform.
([React UI state](https://react.dev/learn/reacting-to-input-with-state),
[Vite guide](https://vite.dev/guide/))

Tauri is a later packaging option if local filesystem access, trusted OS-level hotkeys, multiple
windows or a constrained signing boundary become necessary. Its v2 capability system can grant
different windows narrow native permissions, but its own security guidance stresses that the Rust
core and plugins retain system access. Desktop packaging is not a substitute for wallet policy.
([Tauri capabilities](https://tauri.app/learn/security/capabilities-for-windows-and-platforms/),
[security model](https://v2.tauri.app/security/))

Generic trading terminals should not be the application shell. They bring strong charts and order
widgets but usually define a trade as an order/position lifecycle, not an attention-to-episode
lifecycle. We can borrow interaction patterns without inheriting that ontology.

Likewise, generic product analytics or session-replay software may supplement usability debugging,
but the canonical interaction record must be emitted by the application as domain events:
`presented`, `viewport_entered`, `opened`, `compared`, `dismissed`, `armed`, `entry_intended`,
`partial_exit`, `watching_flat`, `reentered`, `promoted`, `reduced`, `zapped`, `annotated`, and
`interviewed`, with the relevant scene manifest. Pixel replay alone cannot distinguish intention
from an accidental click.

The UI/framework decision stays reversible if the frontend reads a stable local query API and sends
typed domain commands/events rather than writing database rows.

## Cost observations, not a budget

Current public prices illustrate where measurement is needed. They are volatile and should be
rechecked immediately before any purchase.

| Service (2026-08-16 public information) | Relevant public price | What it implies |
|---|---:|---|
| Helius | Business $499/month; Professional $999/month; LaserStream metered at 2 credits/0.1 MB; fixed data add-ons from $400/5 TB | first measure filtered byte volume; do not buy an all-market stream blind ([pricing](https://www.helius.dev/pricing)) |
| QuickNode | Scale $499/month includes 10 gRPC streams and 950M credits; Business $999/month | similar entry price, shorter advertised replay; benchmark rather than brand-select |
| Jupiter | Free 1 RPS; $25/10 RPS; $100/50 RPS; $500/150 RPS; `/execute` has a separate bucket and zero credits | free is sufficient for shadow integration; higher quote rate only after workload measurement ([plans](https://developers.jup.ag/docs/portal/plans)) |
| X | $0.005/post read; $0.010/user read; spend caps available | 100,000 delivered posts would be $500 before storage/analysis; target promoted entities |
| PumpPortal | 0.01 SOL/10,000 token/account trade events; 0.5% local or 1% Lightning execution fee | viable comparator, poor default economics for micro-profit execution |
| Triton deep archive | $25/million BigTable queries, $25 minimum in a month when used | cheap for targeted history, potentially expensive for naive per-event lookup |
| Advanced Charts | approval/licence required; no public redistributable package | do not design the repository around access we do not yet have |

The largest unknown cost is not an RPC subscription. It is the continuous byte volume and storage
created by a faithful whole-market census, especially media and social content. The 72-hour ingest
test should be extrapolated by source and payload class before selecting retention or cloud plans.

## Recommended proof-of-concept gates

These tests answer build-versus-buy questions without committing the engineering architecture.

### Gate A — canonical stream completeness

- 72 hours, Pump/PumpSwap/Pump Fees, two independent sources, finalized backfill truth set.
- Pass: no silent gaps; every gap represented; duplicates harmless; recovery reproducible; latency
  and cost distribution reported by event class.
- Decision: standard WebSocket is sufficient, or choose one Yellowstone provider plus audit path.

### Gate B — Pump surface fidelity and permission

- 24-hour sampled comparison of what Pump renders against what authorized adapters preserve.
- Pass: quantified candidate/rank/post/thread/identity coverage and delay, plus a documented lawful
  access basis stable enough for prospective collection.
- Decision: full replacement is feasible, partial companion is honest, or the premise needs review.

### Gate C — protocol/quote conformance

- Direct official SDK versus Jupiter shadow quotes across lifecycle variants and intended sizes.
- Pass: explainable integer reconciliation of reserves, dynamic fees, platform costs and min-out;
  quote freshness/coverage distributions known.
- Decision: direct primary plus Jupiter fallback/cross-check, or another measured split.

### Gate D — episode/accounting reconstruction

- Reconstruct the three named runners and their prior clips from public wallet history.
- Pass: exact balance reconciliation; visible lots, flat intervals, realized net, remaining basis and
  executable liquidation; editable episode grouping without fact mutation.
- Decision: whether our ledger primitives fit Ember's actual behavior before live automation.

### Gate E — deterministic scene replay

- One session containing board exposure, chart inspection, annotation and disposition changes.
- Pass: byte-for-byte/state-hash repeatable reducer output; knowledge-time replay has no future
  leakage; rendered viewport and alternatives are intelligible to Ember.
- Decision: storage stack is adequate or requires a measured upgrade.

### Gate F — operator usefulness

- Ember uses the local cockpit for several real observation sessions without execution.
- Pass: it exposes at least the Pump slice Ember normally uses, makes inspected/skipped choices and
  flat watching cheap to record, and does not cause a return to Pump merely to recover missing
  context.
- Decision: elaborate the gesture language or stop building infrastructure that is not becoming an
  instrument.

### Gate G — landing and signer policy

- Deferred until an explicit engineering and capital authorization.
- Shadow first; then separately authorized tiny-value tests.
- Pass: policy bypass attempts fail; route-specific landing/cost/tail behavior measured; chain
  reconciliation is exact.
- Decision: explicit signing, policy-backed automation, and chosen sender mix.

## Lock-in and failure modes

1. **Provider schema lock-in.** If enriched vendor rows become canonical, a parser change rewrites
   history. Retain raw Solana bytes and adapt enrichments.
2. **Replay-feature lock-in.** LaserStream's 24-hour replay and QuickNode's shorter `fromSlot`
   window are conveniences, not durability. Our checkpoint and archive close the gap.
3. **Protocol-version drift.** Pump and PumpSwap are actively adding instructions and fields.
   Exact SDK/IDL hashes and fixture gates are mandatory.
4. **Aggregator coverage drift.** Jupiter can list and later remove thin markets. Direct Pump
   support must not disappear merely because an aggregator returns no route.
5. **Frontend API drift or revocation.** Reverse-engineered Pump endpoints can change, block or
   become impermissible. This is a project-premise risk, not just an adapter bug.
6. **Social cost/coverage bias.** Selective X queries create structured missingness; whole-stream
   costs can force silent truncation. Record rules, budgets and outages.
7. **Chart-library ontology leakage.** A renderer may encourage candles/positions as the only units.
   Episode, attention and social events remain first-class outside it.
8. **Managed-signing concentration.** A policy service can fail, change price, or implement a rule
   differently from our reading. Use a dedicated limited-capital wallet and test actual denials.
9. **Premature scale infrastructure.** Kafka/ClickHouse/Kubernetes can consume the project before
   the operator loop exists. Adopt only on observed throughput/query failure.
10. **Cloud analytics leakage.** Session replay and social text can contain sensitive operator or
    third-party data. Keep canonical telemetry local until retention/privacy boundaries are set.
11. **False redundancy.** Two products may share upstream validators, Jito paths, or derived data.
    Audit independence must be established, not inferred from two logos.
12. **“Free” execution products.** Tips, priority fees, platform fees, slippage and data plans are
    still costs. Measure realized all-in economics per route.

## Unresolved questions

- Can Pump provide a supported personal/developer interface for boards, communities, posts,
  callouts, live state and rank history, with terms compatible with prospective research capture?
- Which current RPC/data access already exists in the old `joshibot` environment, and can the
  72-hour shootout be run without a new account or purchase?
- What is the actual filtered byte rate for all Pump/PumpSwap program events, and how much grows
  from social/media rather than chain data?
- Does Jupiter's current direct route coverage and quote latency remain competitive for the exact
  low-cap sizes Ember uses, especially before graduation?
- Which actions require unattended signing rather than a fast explicit gesture, and can a managed
  policy engine constrain every instruction/account/amount invariant we need?
- How much drawing expressiveness is needed beyond points, regions, rays and text before a licensed
  chart library is worth its restrictions?
- Are all current wallet addresses and Meteora position accounts known well enough to perform an
  exact read-only accounting reconstruction?

## Bottom line

Do not buy a trading bot, a generic “Pump API,” or a social score and mistake it for the project.
Do not build an RPC network, AMM math library, chart renderer, database, or key enclave from
scratch.

Build the narrow layer that no provider can sell us: a high-resolution, point-in-time account of
the whole observable surface and Ember's changing relationship to a selected slice of it. Surround
that layer with replaceable commodity adapters, and make every paid dependency earn its place in a
controlled comparison. The proposed apparatus remains feasible with substantial off-the-shelf
plumbing; stable access to Pump's social/product surface, not Solana mechanics, is the material
external uncertainty.
