# Lane 16 — wallet-flow and topology substrate

Status: implemented typed substrate; offline fixtures only; no live crawl, identity resolution,
provider credential use, trading, or profitability claim.

Date: 2026-08-16.

Primary artifacts:

- [`crates/joshi-wallet-topology`](../../../crates/joshi-wallet-topology)
- [`fixtures/wallet-topology/point_in_time.json`](../../../fixtures/wallet-topology/point_in_time.json)

## 1. Outcome

This lane supplies a bounded, replayable **dynamic multiplex topology**, not a wallet-scoring or
deanonymization engine. It retains accounts, assets, programs, venues, pools, LP positions,
transfers, swaps, caller roles, and same-transaction bundles as typed public-chain observations. It
then emits deterministic graph/flow tables and separately carries versioned funding, clustering,
and coordination hypotheses.

The central separation is:

| Layer | Meaning | Examples | May claim common human identity? |
|---|---|---|---|
| observed transaction version | what a named source showed, with as-known finality/canonicality | signature, slot, signer bit, transfer, swap, LP event | no |
| accepted exact fact | observed record admitted by the snapshot's named chain policy | current canonical transaction version and its bound decoded facts | no |
| deterministic derivation | pure bounded reduction over accepted facts | incidence, accumulation, co-trade window, cohort counts, route closure | no |
| inferred hypothesis | fallible versioned interpretation | “this transfer may be funding,” candidate cluster, candidate coordination | no; cluster is not a person |

Funding/co-trading/bundling are not silently promoted into ownership. The fixture deliberately
contains two wallets that buy the same mint, a transfer between wallets, and a same-transaction
cross-venue route. Every associated inference retains observationally equivalent alternatives such
as ordinary payment, independent universal snipers, or reaction to a shared signal.

## 2. Identity and ontology contract

### Stable facts

- `wallet_id` is `joshi_domain::AccountId` containing a canonical public-chain address under the
  declared chain/resolver contract. It is not a Pump profile, X account, household, bot operator,
  funder cluster, or human.
- `mint_id` is `AssetId`; venues, pools and LP positions reuse `VenueId`, `PoolId`, and
  `PositionId`.
- `ProgramId`, `TransactionId`, `TransactionFactId`, `FlowId`, `SwapId`, `LiquidityEventId`, and
  `BundleId` are strong opaque topology IDs.
- A transaction's natural `TransactionId` can have several immutable `TransactionFactId` versions
  as JOSHI learns stronger finality or a reorg/noncanonical correction.
- Every caller association, transfer, swap, LP event, and bundle binds the exact
  `TransactionFactId` from which it was decoded. It cannot float onto the latest transaction row.

### Hypotheses are not entities

There is deliberately no `cluster_id` representing a canonical real-world actor.

- `HypothesisId` identifies one immutable assertion version.
- `HypothesisSeriesId` identifies its semantic correction/supersession line.
- A cluster claim contains a sorted set of wallet addresses and per-member support, but it does not
  name or infer a person.
- Profile wallet, social identity, funder, trading wallet, and cluster hypothesis stay separate.
  The attention/social lanes may link them with their own evidence-bearing assertions.
- Public reporting must call the object a **cluster hypothesis**, include its status/method, and
  avoid allegations of ownership or coordination.

This supports followed-wallet candidate routing without laundering “shares a funder” into “is the
same person.”

## 3. Exact fact families

| Rust fact | Required closure | Semantics |
|---|---|---|
| `TransactionFact` | fact ID/version/supersedes, natural transaction ID, chain, signature, slot, block time when supplied, finality, canonicality, availability, observations/events/coverage | one immutable as-known chain observation |
| `CallerAccountFact` | transaction fact, instruction path, account ordinal, account, role, program, signer/writable flags | exact account placement/flags, not beneficial ownership |
| `TransferFact` | transaction fact, instruction path/order, source/target accounts, program, asset/atoms/kind, optional venue/pool | directed atomic transfer; never automatically “funding” |
| `SwapFact` | transaction fact, instruction path/order, exact caller, optional exact trader wallet, program/venue/pool, input/output/fees | decoded asset exchange; absent trader attribution stays absent |
| `LiquidityPositionEventFact` | transaction fact, position, actor when exact, authority, program/venue/pool, event kind, asset legs, protocol units | open/add/remove/claim/close observation without action authority |
| `SameTransactionBundleFact` | transaction fact and ordered typed fact references | exact co-occurrence/order inside one transaction, not coordination |

Every fact has a nonempty observation or source-event closure and canonical sorted coverage refs.
Atom amounts are unsigned decimal strings. Flow direction carries the sign; totals use full `u128`
wire integers. No float enters an exact or canonical derived row.

`FlowMark` makes this a marked temporal flow graph: edge kind, asset, atomic size, venue and pool are
retained beside slot/order. It remains possible to condition on size, asset, venue, lifecycle or
program rather than turning every transfer into the same unlabeled adjacency.

## 4. Hypothesis contract

`TopologyHypothesis` supports three current payloads:

1. `funding_edge`: named wallets and exact supporting transfer IDs;
2. `wallet_cluster`: sorted wallet memberships and non-probabilistic support ppm; and
3. `coordination`: sorted wallets with same-transaction bundle and/or deterministic co-trade inputs.

Every version requires:

- hypothesis ID, series ID, positive version and exact predecessor when superseding;
- producer, method and method version;
- `SupportPpm` in `0..=1_000_000`—a support score, not a calibrated probability;
- half-open slot validity plus wall-time validity and independent `available_at` knowledge time;
- candidate/supported/disputed/retracted status;
- sorted observation, source-event, coverage, exact-fact and derivation inputs;
- lowercase algorithm-qualified SHA-256 input digest;
- nonempty adversarial alternatives; and
- a causality check that no cited exact fact became available after the assertion.

The current reducer activates wall validity only when the semantic interval status is:

- `bounded`, with both bounds present and the query time inside `[lower, upper)`; or
- `unbounded`, with neither bound present.

`source_missing`, unknown, malformed, or otherwise unsupported statuses are retained but are not
active. Missing bounds can never become “valid for all time” by accident.

## 5. Three-axis point-in-time and chain correction

A `SnapshotRequest` binds three independent axes:

```text
available_through   local knowledge cutoff
event_slot          chain-history cutoff and hypothesis-valid slot
event_time          hypothesis-valid wall time
```

The reducer:

1. selects the latest transaction-fact version available by the knowledge cutoff;
2. retains that version in `observed_transaction_versions`, even if it is provisional,
   noncanonical, or below the accepted finality;
3. places a transaction and its dependent decoded facts in `accepted_facts` only if the current
   transaction version has an accepted canonicality/finality and slot at or before `event_slot`;
4. excludes facts bound to an older superseded transaction version;
5. selects a hypothesis only if it was known by the cutoff, its slot and wall validity both contain
   the query point, and all exact fact inputs are accepted in that same snapshot; and
6. selects the newest applicable version per hypothesis series, keeping a latest retraction visible
   as a retraction rather than silently reviving an older version.

This prevents two common leaks:

- a transaction observed as confirmed and later learned noncanonical no longer feeds wallet flow,
  co-trade, cohort, or cluster tables at the later knowledge cutoff; and
- a cluster/profile attribution learned later or valid only in a later interval cannot be joined to
  an older market event merely because the address string matches.

The fixture exercises both. Before the correction, the provisional reorg swap is accepted under an
explicit `confirmed|finalized` policy. After the noncanonical version arrives, the transaction
observation remains inspectable but its swap and two flow edges disappear. A later-period cluster
and a source-missing-validity cluster are absent from the historical query; a later retraction
supersedes the applicable cluster version.

`accepted_finalities` and `accepted_canonicalities` are named snapshot-policy inputs, not source
truth. A production adapter must bind the policy itself to a versioned configuration and expose
provisional status in glass. “Observed” is not synonymous with finalized.

## 6. Reducer invariants and bounds

The pure synchronous reducer has hard limits for facts, hypotheses, co-trade activities and pair
rows. Exceeding a bound fails the snapshot; it never truncates a graph and calls the denominator
complete.

Validation includes:

- closed contract version and stable typed IDs;
- positive, strictly increasing transaction/hypothesis versions and direct supersession;
- same chain/signature within a transaction correction series;
- nonempty, sorted, duplicate-free evidence closures;
- causal availability and exact transaction-version binding;
- nonzero transfer/swap/LP legs and distinct swap assets;
- same-transaction, prior-available, duplicate-free bundle membership;
- sorted/unique claim members and inputs;
- nonempty alternatives and correctly shaped SHA-256 input closure; and
- checked `u128` aggregation and checked `i128` net accumulation.

No reducer operation queries a network, a mutable wallet, a provider, or the catalog. Its coverage
IDs are therefore emitted as `CoverageBinding::UnverifiedRequest`. The core/store adapter must prove
that each coverage record exists and matches the snapshot's source/scope/cutoff before a product or
study calls the window covered.

## 7. Canonical flow and topology tables

The crate does not depend on a general Rust graph library. It emits small typed logical tables whose
rows are useful to glass and to Python/Arrow analysis:

| Table | Grain | Use and non-claim |
|---|---|---|
| `flow_edges` | exact directed asset leg | marked transfer/swap/LP graph |
| `incidence` | two rows per edge | oriented `B1`: tail `-1`, head `+1`; column conservation |
| `divergence` | node × asset × snapshot | inflow, outflow and net accumulation; not wallet PnL |
| `bundle_legs` | bundle × ordered fact | same-transaction higher-order membership |
| `route_legs` | bundle × ordered swap | cross-venue asset routes |
| `cycle_inputs` | bundle route endpoints | structural path continuity/asset closure, not profitable arbitrage |
| `wallet_mint_cohorts` | wallet × focus mint | first observed acquisition, last observed disposal, gross atoms, venues |
| `concentration_inputs` | wallet × focus mint | raw exact activity weights and denominator; downstream concentration |
| `cohort_aggregates` | focus mint | counts with acquisition/disposal/both; not holder inventory |
| `co_trades` | sorted wallet pair × focus mint × window | bounded temporal co-activity; never common identity |

The reducer only computes co-trading for explicit `focus_mint_ids`. It does not use shared SOL/USDC
as a universal pair key, which would generate a meaningless near-complete graph. Pair construction
is bounded and fails closed on row explosion.

“Entry” and “exit” fields are deliberately named `first_observed_acquisition` and
`last_observed_disposal`. Without balance-before, complete venue coverage and transfer
reconciliation, they do not prove a wallet opened or fully exited an economic position. Similarly,
LP event legs preserve cash/inventory movement but do not merge into Ember's accounting episodes.

## 8. Graph/Hodge and multiplex analysis boundary

The row family preserves layers instead of forcing one adjacency matrix:

- account transfers;
- wallet↔pool swap legs;
- wallet/pool/position LP legs;
- account-role associations;
- same-transaction bundle membership;
- derived temporal co-trading; and
- inferred funding/cluster/coordination assertions.

`incidence` is an explicit sparse oriented `B1` input. `bundle_legs`, `route_legs`, and
`cycle_inputs` preserve enough ordered higher-order structure for analysis to propose a named
`B2`/simplex contract. Python must test `B1 @ B2 == 0` on every declared cell; a same-transaction
bundle is not automatically a valid topological 2-cell.

The build/buy decision is:

- use NetworkX 3.6.1 for initial small/medium point-in-time graph studies;
- use SciPy sparse matrices for incidence, Hodge and boundary goldens;
- treat rustworkx or Python GraphBLAS only as measured performance probes;
- treat TopoNetX 0.4 and XGI 0.10 as differential research tools, not ontology/storage authority;
- do not add a graph database, Raphtory, a general Rust graph engine, or a home-grown graph
  framework to the evidence path.

This crate owns typed reduction and bounds. Python owns exploratory decomposition over immutable
exports. Neither owns identity truth.

## 9. Arrow/Parquet logical schema

The Rust structs are the logical schema; an exporter maps them without semantic coercion:

| Rust/wire value | Arrow-facing type |
|---|---|
| IDs/discriminators/digests | non-null UTF-8; dictionary encoding is physical only |
| `WireU64` atom/slot/count | `decimal128(20,0)` to retain full unsigned range |
| `WireU128` aggregate | `decimal256(39,0)` |
| `SignedAtoms` | `decimal256(39,0)` |
| `UtcTimestamp` | `timestamp[us, tz=UTC]` |
| optional value | nullable field, never sentinel zero/empty string |
| typed lists | Arrow list with non-null element type and stable order semantics |
| observed/derived/inferred class | explicit enum UTF-8/dictionary column |

Every table manifest must name:

- `joshi.wallet_topology.arrow_tables.v1`;
- snapshot ID, knowledge cutoff, event slot and event wall time;
- accepted finality/canonicality policy ID/digest once the adapter exists;
- fact/assertion producer versions and logical-table digest;
- requested coverage IDs plus later store-verified coverage binding;
- row count, canonical sort key, units and null meaning; and
- source snapshot/file digests under the existing export manifest.

Canonical table order is by typed primary key, then transaction/slot/order where meaningful.
Bundle/route order is evidence and must not be sorted away. Parquet file bytes are a physical
encoding, not the logical digest.

## 10. Acquisition requirements

### Compact census

Keep enough whole-market data to reconstruct denominators and promote hot scopes:

- transaction signature/natural ID, slot, commitment/finality, current canonicality observation,
  provider/source clocks, and correction/reorg evidence;
- instruction/program path, account ordinal, signer/writable flags, and caller roles;
- native/SPL transfers with exact endpoints, mint and atoms;
- decoded Pump/PumpSwap and selected venue swaps with user/caller, pool, asset legs and fees;
- creation/migration/pool/position lifecycle facts needed to type venue and asset nodes; and
- source coverage/gaps by program, account, slot/cursor and subscription generation.

The census need not retain every verbose transaction forever. It must retain exact compact event
facts and promote raw transactions for sampled, disputed, decoder-unknown, reorged, hot-scope and
reconciliation cases.

### Leased hot scope

For an operator-selected mint, followed wallet, territory or disputed cluster candidate, retain:

- full transaction metadata, inner instructions, logs and pre/post native/token balances;
- exact account ownership/authority observations used to map token accounts to wallets;
- all relevant venue swaps/transfers/LP position events during the lease;
- wallet/mint scope start/end, reason, source generation, request budget and coverage gaps;
- contemporaneous scene/board/social/territory references through their own typed lanes; and
- later correction/backfill without overwriting the as-known version.

Wallet events promote a candidate/hot lane; they do not authorize a copy trade or provider-wide
entity search. No acquisition adapter should crawl funders recursively until a named bounded study
and privacy review earns that scope.

## 11. Glass and analysis query contract

`TopologyQuery` names one immutable `SnapshotId`, finite wallet/mint/venue/hypothesis filters,
allowed evidence classes, and a hard row limit. It cannot silently request “current” data or expand
a cluster.

The smallest useful glass response is:

- the exact three-axis snapshot basis and verified/unverified coverage state;
- observed transaction versions and excluded canonicality/finality corrections;
- mint-relative wallet gross acquired/disposed atoms and first/last observed event labels;
- exact marked flows, route/bundle context and LP position events;
- nullable cluster hypothesis, always with method/version/status/support/evidence/alternatives; and
- badges for `observed`, `deterministic_derived`, and `inferred_hypothesis`.

Glass must not render “same owner,” “smart money,” “insider,” or “profitable wallet” from this
substrate. Analysis joins must use hypothesis validity and availability, group train/test splits by
wallet/cluster series where leakage is plausible, retain retractions, and never backfill eventual
cluster membership into earlier features.

## 12. Fixture and verification

`point_in_time.json` is synthetic/adversarial. It contains:

- exact transfer plus a fallible funding claim;
- two-wallet temporal co-trading with universal-sniper/shared-signal alternatives;
- a Pump→PumpSwap same-transaction asset-closed route;
- a Meteora LP add event with two asset legs;
- a confirmed/canonical transaction later superseded as finalized/noncanonical;
- a cluster version later retracted;
- a later-period cluster that must not join the historical query; and
- a source-missing wall-validity claim that must not become globally active.

Current executable checks prove:

- strict fixture parsing with no JSON number tokens;
- early and late point-in-time fact/edge/co-trade/hypothesis closures;
- reorg correction removes dependent flow while preserving the observed correction;
- unknown validity and future validity do not activate;
- a latest retraction remains visible;
- every oriented edge has one tail and one head with equal atom/asset mark;
- the route's structural continuity and asset closure; and
- inference without an adversarial alternative is rejected.

Targeted gates:

```text
cargo test --locked -p joshi-wallet-topology
cargo clippy --locked -p joshi-wallet-topology --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked -p joshi-wallet-topology --no-deps
cargo fmt --package joshi-wallet-topology -- --check
```

At lane close these report seven passing tests, strict Clippy, strict rustdoc and formatting.

## 13. Deliberate nonclaims and next joins

This substrate does not establish:

- who controls a wallet, whether two wallets share a human, or whether an observed funder remains
  economically relevant;
- that a same-slot/same-transaction pattern is coordinated, malicious or predictive;
- complete holdings, entry, exit, PnL, capacity, causality or strategy edge;
- a stable social/profile→trading-wallet mapping;
- territory membership or a canonical fancoin; or
- permission to construct, sign, submit or copy a transaction.

Required integration joins are intentionally directional:

1. source adapters produce exact observations and coverage, then map into transaction-version-bound
   topology facts;
2. the core/store verifies evidence and coverage closure before export;
3. wallet/cluster facts nominate hot scopes to attention, never trades;
4. social attention links nullable wallet/profile/cluster/territory IDs without merging them;
5. glass queries immutable snapshots and keeps epistemic badges; and
6. analysis consumes manifested Parquet tables, builds B1/B2 under named contracts, and returns
   versioned assertions rather than mutating exact facts.

The next implementation should be the strict source/store adapter and exporter, not a market-wide
cluster job. A first prospective pilot needs enough cockpit use to learn whether wallet topology
improves candidate surfacing and situational awareness beyond anonymous flow—without pretending the
same data has already demonstrated economic value.
