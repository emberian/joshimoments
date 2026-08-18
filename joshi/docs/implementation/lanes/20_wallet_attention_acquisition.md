# Lane 20 — wallet and attention-directed chain acquisition

Status: **offline read-only substrate complete; W4 receipt/decoder follow-on is complete offline;
live transport remains gated**  
Date and source posture: 2026-08-16  
Code: [`crates/joshi-wallet-source`](../../../crates/joshi-wallet-source)  
Fixtures: [`fixtures/wallet-source`](../../../fixtures/wallet-source)

W4 follow-on: [`Lane 21 — receipt-gated wallet/topology circulation`](21_wallet_topology_admission.md)
adds the pinned Pump/PumpSwap decoder, real store receipt/coverage/cursor closure, and immutable
correction snapshots. This lane remains the source/planner contract and makes no live-provider claim.

## Decision

This lane implements the narrow bridge from operator/social attention to bounded public-chain
observation. It does not implement a wallet crawler, an identity resolver, a copy-trading system, or
a provider-derived “smart money” label.

The working shape is:

```text
operator selection / attention occurrence / topology candidate
             |
             v
 versioned candidate or mint-cohort input
             |
             v
 bitemporal finite lease ----> hard independent read budgets
             |
             v
 credential-free Helius/Solana logical read plan
             |
             v
 exact RawSourceFrame --------> joshi-evidence draft
             |
             +----------------> additive raw-chain normalization
                                      |
                                      v
                         version-bound topology facts
                                      |
                                      v
                         point-in-time topology reducer

social evidence remains social evidence; chain evidence remains chain evidence
durable coverage/cursor truth remains a core/store decision
```

The important product claim is therefore small and useful: when Ember selects a wallet, a mint
cohort, or a Pump callout/follow occurrence promotes one, Joshi can express exactly what public keys
to watch, for how long, under what budget, and what source evidence any later flow row came from.

No component in this crate can load a provider key, derive a private key, build/simulate/sign/submit a
transaction, scan the whole address graph, or act on a wallet observation.

## Authority and epistemic boundary

The lane accepts only public-key candidates already selected by an upstream source or the operator.
The input says why the address entered scope, but never silently upgrades that reason.

| Input status | Permitted meaning | Meaning explicitly forbidden |
| --- | --- | --- |
| `provider_claim` | a named provider revision supplied this wallet field | the profile owner controls it now or is one human |
| `on_chain_fact` | a public key occupied an exact signer/account role | the signer is the profile, creator, funder, or skilled trader |
| `operator_selected` | Ember requested observation of this public address | endorsement, ownership, or a trade instruction |
| `inferred` | a versioned upstream method proposed this candidate | durable entity identity or ground truth |
| `retracted` | an earlier candidate remains replayable but is no longer active | deletion of the historic assertion |

`CandidateWalletInput`, `MintCohortInput`, and `ScopeInput` retain method/input/evidence/coverage IDs,
valid time, and independent `available_at`. A mint cohort is a finite supplied list. It never grows by
walking counterparties or funding ancestors.

### Attention promotion

`AttentionPromotionInput` implements the handoff agreed with the attention lane:

- mint and optional public wallet;
- reason variant and requested finite scope;
- event/as-known cutoff and expiry;
- exact attention-input and coverage references; and
- derivation version.

Pump callout, follow-member, community, presentation, and chain observations are not copied into a
wallet fact. They remain distinct retained inputs and only their typed IDs cross the boundary.

Cluster context is especially strict. A promotion may carry a nullable
`caller_cluster_context_id` and its resolved `source_cluster_hypothesis_id`. A bare current cluster
hypothesis is rejected: the selected context must bind the exact attention event, event time/slot,
as-known cut, source artifact/snapshot/query digests, and upstream validity. This prevents a cluster
learned later from being projected backward onto an earlier callout.

A follow occurrence can promote a wallet-only lease directly. A callout normally promotes the mint
and, when an exact candidate wallet exists, that wallet. A later wallet trade that connects a
followed wallet to the mint can request a new promotion citing both evidence inputs. None of these
operations claims that the caller traded, that followers copied, or that either caused a response.

## Lease state machine

```text
PROPOSED
   |
   | strict schema + public-key + clock + evidence validation
   v
ADMITTED ---- identity conflict ----> REJECTED
   |
   | input.available_at <= opened_at
   | candidate/cohort.available_at <= input.available_at
   | candidate valid interval contains opened_at
   v
ACTIVE at as-known cut
   |
   | expires_at <= cut
   v
EXPIRED
```

Expiration removes observation desire; it never deletes evidence or normalized facts. Lease replay
is idempotent only when the same lease ID carries identical content. Reusing an ID for new content
fails closed.

The `active_at` query requires all three conditions:

```text
input.available_at <= query_cut
opened_at          <= query_cut
query_cut          <  expires_at
```

Admission additionally checks `requested_at <= available_at`, nested candidate/cohort availability,
nonempty scope, a positive half-open interval, and the lease's public-key ceiling. The adversarial
fixture proves that a future-known inferred candidate cannot become active in an earlier replay even
when its enclosing lease time would otherwise match.

## Source surfaces: known facts and our posture

The following provider facts come from current official documentation. Design decisions are labeled
separately.

| Surface | Current primary-source fact | Lane posture |
| --- | --- | --- |
| Helius `getTransactionsForAddress` | Helius describes an exclusive full address-history RPC with a pagination token, up to 1,000 transactions, `getTransaction`-shaped full responses, transaction index, and a `tokenAccounts: balanceChanged` filter. Full rows cost 10 credits per 100 returned, with a 10-credit minimum. | Primary finalized bounded backfill. Default page size is 100; every configured started block of 100 is budgeted at 10 credits. Cursor is only a candidate until durable admission. |
| Helius `transactionSubscribe` | Helius documents full transaction notifications with account include/exclude/required filters, commitment, encoding, max transaction version, and up to 50,000 addresses in the include list. It is a Helius extension, not standard Solana RPC. | Low-latency leased hot scope. Local default is 500 keys, deliberately below the provider ceiling. Processed notifications are provisional hints requiring later correction/finalization. |
| Solana `getTransaction` | Solana returns a confirmed transaction plus metadata for a signature or `null`; the client declares encoding, commitment, and maximum supported transaction version. | Standard exact lookup/fallback and finalized reconciliation surface. `null` is an observed result, not proof the transaction never existed. |
| Solana `getSignaturesForAddress` | Solana provides address-relative signature pagination with commitment and `before`/`until` bounds. | Standard bounded fallback when the Helius modern history route is unavailable; signatures must be expanded through exact transaction lookup. |
| Helius Enhanced Transaction API | Helius marks the legacy Enhanced transaction history path as maintenance/deprecated for new integrations. It returns provider-parsed semantic projections rather than being the raw chain record. | Disabled by default. Optional cross-check only, conservatively budgeted, quarantined as `EnhancedProjection`, and never authoritative for transfer/swap truth. |

Primary references:

- [Helius `getTransactionsForAddress`](https://www.helius.dev/docs/rpc/gettransactionsforaddress)
- [Helius `transactionSubscribe`](https://www.helius.dev/docs/rpc/websocket/transaction-subscribe)
- [Helius Enhanced transaction history](https://www.helius.dev/docs/enhanced-transactions/transaction-history)
- [Helius Enhanced API overview](https://www.helius.dev/docs/enhanced-transactions/overview)
- [Solana `getTransaction`](https://solana.com/docs/rpc/http/gettransaction)
- [Solana `getSignaturesForAddress`](https://solana.com/docs/rpc/http/getsignaturesforaddress)

### Credential-free logical plans

`AcquisitionPlanner` emits typed logical request templates only. It supplies method, bounded params,
public keys, commitment, cursor candidate, and response expectations. It does not contain an RPC URL,
API key, header, wallet capability, or transport client.

The default plan for a live set is:

1. deduplicate public keys while retaining every benefiting lease/scope ID;
2. chunk keys into Helius `transactionSubscribe` requests at at most 500 each;
3. emit one finalized `getTransactionsForAddress` backfill per key, page size 100, full
   transaction details and `balanceChanged` token-account filter; and
4. omit legacy Enhanced calls unless a caller explicitly enables non-authoritative cross-checking.

Every request ID includes an explicit `plan_occurrence_id`; local chunk ordinals alone are not
durable identities and cannot collide across restarts/plans. A read is attributed only to leases
whose keys it actually serves. Shared subscriptions are conservatively charged in full to every
benefiting lease rather than hiding work in another scope's budget.

The request allowlist contains only:

- `transactionSubscribe`;
- `getTransactionsForAddress`;
- `getSignaturesForAddress`;
- `getTransaction`; and
- the explicitly deprecated Enhanced HTTP GET projection.

There is no template variant for `sendTransaction`, `simulateTransaction`, blockhash acquisition,
unsigned builders, signing, or submission.

## Budget and capacity contract

Each scope carries independent hard ceilings for:

- requests;
- pages;
- response bytes;
- provider credits; and
- public keys.

The planner accounts worst-case configured history-page credits, not just default-page cost. It
fails the entire plan when any lease's conservative request/page/credit estimate crosses a ceiling.
At runtime `BudgetLedger` admits measured use dimension by dimension with checked arithmetic; one
dimension cannot borrow from another. An unexpectedly large response, provider billing change, or
extra page stops that lease and produces a visible gap. An estimate is never permission to exceed a
hard measured cap.

Provider bills and local calculations must later be reconciled as separate observations. This crate
does not claim that its credit estimate is an invoice or authorize overage, autoscaling, a plan
change, or broader crawl.

Capacity remains attention-directed. It scales with the explicit leased public-key set, not the
entire wallet graph. The 50,000-key provider maximum is a protocol ceiling, not Joshi's operating
target.

## Exact frame and evidence boundary

`normalize_frame` first clones the exact `RawSourceFrame` body and passes the original frame through
the shared `joshi-sources::observation_draft` adapter. Only then does it parse the cloned bytes.

The retained frame envelope preserves:

- exact response body bytes;
- source and transport;
- live/backfill stream class;
- inbound/outbound direction;
- HTTP status and safe headers;
- receive wall time, connection epoch, sequence, and content type; and
- restart-global occurrence namespace and safe logical locator from `EvidenceContext`.

Authenticated URLs and headers never enter the evidence locator or normalized DTO. Payload SHA-256
identifies equal bytes, while acquisition/observation occurrence IDs remain independent so identical
provider bytes observed twice do not collapse two occurrences.

The source emits an `EvidenceDraft`; it does not write SQLite and does not acknowledge durability.
The durable one-writer path alone may commit acquisition/blob/observation/source-event links,
coverage/gaps, cursor advancement, and outbox together. In particular:

- `AcquisitionRecord.source_cursor` and this lane's `source_cursor_candidate` are descriptive
  candidates;
- a producer cannot assert `durable_cursor_advance_authorized`;
- a durable `CursorAdvance` requires nonempty exact observation evidence and the same atomic store
  batch; and
- source coverage IDs remain `RequestedUnverified` until core/store validates their scope and cut.

Elapsed monotonic time at the shared source edge is `received - started` exactly once. During this
lane, the shared source owner verified the expression and added a nonzero-start regression
(`start=10`, `received=20`, elapsed `10`) so admission does not compensate or subtract twice.

## Raw-chain normalization

The normalizer consumes strict `AcquisitionResponseContext` separately from the raw provider frame.
That context names the logical surface, exact scope/public-key/mint filter, commitment, availability
time, prior cursor, requested coverage/gaps, and optional transaction-version corrections. Unknown
admission fields are rejected.

### Direct observations

`RawTransactionFact` retains:

- natural signature, slot, optional provider transaction index, optional block time;
- immutable `transaction_fact_id`, positive version, exact predecessor, finality, canonicality, and
  local availability;
- success/failure and network fee atoms;
- ordered transaction account keys with signer/writable/source roles;
- native lamport pre/post/delta effects;
- token-account/mint/owner/decimals pre/post/delta effects;
- top-level and inner instruction paths, program IDs, ordered caller accounts and execution status;
- observed Pump bonding-curve/PumpSwap/System/SPL program paths;
- successful parsed native/SPL transfers only;
- strictly admitted protocol-decoder swaps;
- exact same-transaction membership; and
- query-scope and requested-coverage references.

Amounts are canonical integer atoms. A UI decimal or JavaScript float never enters an exact fact.
Missing transaction index/block time remains missing plus an issue; it is not synthesized.

Failed transactions are retained with their instructions, error status, fee/balance metadata, and
observation closure, but the normalizer emits no executed parsed transfer. This prevents an attempted
transfer from becoming a flow edge. Provider-error and malformed payloads still produce raw evidence
plus an explicit normalization issue rather than disappearing.

### Account, transfer, and bundle semantics

An ordered account is a caller/account-role fact only for the instruction in which it appeared.
Signer and writable bits are chain-message facts; they do not establish beneficial ownership. A
same-transaction bundle preserves ordered typed fact references and does not imply coordination.

A successful parsed System/SPL transfer becomes a directed exact flow with source, destination,
authority when present, asset, atoms, program, instruction path and order. It is **not** called
funding. `FundingHypothesisInput` may later cite a direct transfer and emit a versioned separate
`FundingHypothesis`; the contract hard-codes `establishes_common_ownership = false`.

### Swap admission

This crate does not invent Pump/PumpSwap semantics from provider labels. `DecodedSwapInput` is a
strict boundary for a separately versioned, pinned protocol decoder. Admission requires:

- the same retained raw observation and transaction locator;
- a successful raw transaction;
- the decoded program at the exact instruction path;
- the attributed trader wallet to be a raw signer;
- explicit event ordinal and nonzero integer input/output atoms; and
- decoder version, program, optional pool, availability, and exact assets.

Any mismatch fails; there is no “best effort” exact swap. The legacy Helius Enhanced payload is
stored as a vendor `EnhancedProjection` with `requires_raw_reconciliation = true`; its transfer and
swap claims cannot enter exact topology facts.

The current gap is deliberate: this crate does not yet contain the pinned Pump/PumpSwap IDL decoder.
The protocol-plane conformance work must supply it and differential fixtures before live exact swaps
are admitted.

## Exact topology adapter

`to_topology_facts` maps one immutable raw transaction version into lane 16's final topology
contract. The mapping is explicit so source DTOs do not become a second durable truth:

| Wallet-source value | Canonical topology value |
| --- | --- |
| Solana public key | `AccountId("solana.account:<base58>")` |
| signature | `TransactionId("solana.transaction:<signature>")` |
| transaction version | `TransactionFactId("solana.transaction:<signature>:v<N>")` |
| program public key | `ProgramId("solana.program:<base58>")` |
| mint asset | `AssetId("solana.mint:<base58>")`; native SOL remains its named native asset |
| program-classified venue | typed `VenueId` for Pump curve, PumpSwap, System, SPL or explicit other program |
| transfer | `TransferFact` bound to the exact transaction fact version |
| admitted decoded swap | `SwapFact` bound to the exact transaction fact version |
| instruction account placement | `CallerAccountFact` bound to exact path and transaction fact |
| same-transaction occurrence | ordered `SameTransactionBundleFact` of typed fact references |

Every dependent fact carries the same exact `TransactionFactId`, availability, observation, and
requested coverage closure. Member ordering uses outer instruction, inner instruction, fact kind,
and event/account ordinal. The adapter never silently rebinds an old decoded fact onto the newest
version of a signature.

Lane 16's point-in-time reducer then selects the latest transaction version as known. Noncanonical
or unacceptable-finality versions remain visible in `observed_transaction_versions`, while their
dependent records are excluded from accepted facts and derived rows. Its output coverage remains
`CoverageBinding::UnverifiedRequest` until the store adapter proves it.

## Finality, reorg, and correction

Processed live notifications optimize attention latency, not truth. Finalized backfill and exact
transaction lookup establish later observations. `TransactionVersionInput` supplies the append-only
version/supersession/canonicality context selected by the chain reconciler.

For a signature, the state is:

```text
observed processed v1
       |
       +---- confirmed/finalized same semantics ----> v2 canonical
       |
       +---- slot/finality conflict ----------------> v2 conflicted
       |
       +---- dead fork / unavailable ---------------> v2 noncanonical
                                                        |
                                                        +--> later reappearance v3
```

`reconcile_transaction_facts` produces a separate append-only correction classification such as
finality advanced/regressed, slot conflict, became unavailable, or reappeared. It never updates an
old fact in place. The topology reducer—not this source—decides which version is acceptable for a
named point-in-time policy.

## Coverage, cursors, and gaps

Coverage is scoped to the exact leased query. `CoverageAssessment` reports:

- scope IDs;
- observed lower/upper slots;
- source cursor candidate;
- whether the page appeared exhausted;
- known gap IDs; and
- `RequestedUnverified` status.

The status never means “this wallet's complete history” or “no activity occurred.” A clean WebSocket
connection is not replay coverage. Disconnect, rate limit, budget stop, `null` transaction, provider
error, malformed page, page cap, expired lease, cursor conflict, or unsupported schema must produce a
bounded gap/issue and trigger no cursor advancement.

For modern Helius history, the response pagination token is retained exactly. For the synthetic
fixture the provider's slot/transaction-index cursor is merely an observed candidate. Standard
signature pagination retains the last signature candidate. Only the core/store batch can turn either
into durable progress.

## Mint-relative and cohort outputs

`summarize_mint_relative` performs a bounded deterministic reduction over exact token balance
effects for one supplied mint/wallet cohort member. It outputs gross in/out atoms, first/last
observed slot, transaction count, venue set, input transaction fact IDs, cohort-input ID, and
availability.

The names are intentionally **gross in/out**, not buy/sell or entry/exit. A balance effect may be a
transfer, swap leg, account migration, distribution, or other chain action. Exact buy/sell semantics
come from admitted swaps. Complete inventory/holder claims require opening balance and proven
coverage. Co-trade, concentration, incidence/divergence, route, and cohort tables belong to lane 16's
bounded topology reducer, not this source adapter.

## Failure containment and adverse cases

| Adverse case | Required behavior | Offline evidence |
| --- | --- | --- |
| future-known candidate/cohort | reject lease; never appear in earlier replay | `scope_input_future_known_rejected.json` |
| unknown admission field | strict parse failure | adversarial input test |
| duplicate plan-local request ordinal across runs | include `plan_occurrence_id` namespace | two-plan test |
| lease estimate exceeds any budget dimension | reject entire plan | tight-credit test |
| equal response bytes observed twice | retain separate occurrence IDs | shared source adapter contract |
| malformed/provider error body | retain exact evidence, emit issue, no facts/cursor authority | normalizer branches |
| failed transaction containing transfer-shaped instruction | retain failed instruction; emit no executed transfer | failed finalized fixture |
| missing transaction index/block time | preserve `None`, emit issue | standard Solana fixture |
| legacy Enhanced swap/transfer claim | quarantine projection; require raw reconciliation | enhanced fixture |
| decoder disagrees on tx/path/signer/program | reject exact swap | decoder admission test |
| transfer resembles first funding | keep transfer exact; emit separate non-ownership hypothesis only | funding test |
| transaction later becomes noncanonical | append new version/correction; dependent facts bind old version and are excluded by reducer | version/topology contract test |
| attention cluster learned after event | reject bare hypothesis; require event-bound selected context | cluster-binding test |
| cursor candidate without durable observation closure | never advance durable cursor | type/API separation |

Unknown Pump/PumpSwap instructions are retained as raw instructions/program occurrences and marked
unsupported. The correct failure is less semantics, not a guessed economic fact.

## Offline fixture set and verification

The five committed JSON fixtures are synthetic, finalized-shape, credential-free examples, with a
sixth README artifact describing their provenance:

- `helius_get_transactions_for_address_finalized.json`: modern raw history, tx index, account roles,
  native/token effects, direct transfer, Pump path, cursor candidate, and mint-relative flow;
- `solana_get_transaction_failed_finalized.json`: failed transaction containment;
- `helius_legacy_enhanced_projection_finalized.json`: quarantined provider projection;
- `scope_input_future_known_rejected.json`: bitemporal future-knowledge attack;
- `attention_promotion_callout.json`: distinct social evidence plus event-bound cluster context; and
- fixture README documenting provenance and exclusions.

Golden-byte register:

| JSON fixture | Exact bytes | SHA-256 |
| --- | ---: | --- |
| `helius_get_transactions_for_address_finalized.json` | 3,923 | `fc7a431fd89510ed5b4c74ff0bb810f139ffa359fc6103fbc9a1e7e5d4670a90` |
| `solana_get_transaction_failed_finalized.json` | 1,567 | `9d53060b43d3c7c9a901867014cd9399c8d3265d7280d1f3fc7eb050169d803d` |
| `helius_legacy_enhanced_projection_finalized.json` | 1,183 | `34a74fae217ad07c53e768bbdef69dc9365015d0d9bcef7c32f1b3db7cc5259b` |
| `scope_input_future_known_rejected.json` | 996 | `8b3b47e1b7c4205e9cdd86fdc141a7f19305c079b1f611422cca9dd789b24177` |
| `attention_promotion_callout.json` | 718 | `f3b3382b81fbc5f861be4551c897ff53712706a97767d3927946175a583d148e` |

The current locked-workspace verification gate is:

```text
cargo clippy --locked -p joshi-wallet-source --all-targets -- -D warnings
cargo test   --locked -p joshi-wallet-source --all-targets
RUSTDOCFLAGS='-D warnings' cargo doc --locked -p joshi-wallet-source --no-deps
```

Fourteen focused tests prove exact body retention; direct-fact normalization; failed-transaction
behavior; legacy projection quarantine; balance-effect naming; decoder/funding evidence binding;
future-known lease rejection; strict admission; plan occurrence identity/read allowlist/budget
failure; social promotion separation; event-bound cluster selection; and exact transaction-version
binding through the final topology DTOs.

No test opens a socket, reads a provider key, reaches a paid route, derives private material,
constructs a transaction, or submits anything.

## Gate status and explicit gaps

### Green offline

- strict versioned wallet/cohort/social inputs;
- bitemporal finite leases and expiry;
- credential-free bounded logical planning;
- independent hard budget accounting;
- exact source-frame/evidence preservation;
- modern Helius and standard Solana response normalization;
- failures, balances, account roles, program paths and direct transfers;
- non-authoritative Enhanced quarantine;
- strict protocol-decoder swap admission boundary;
- separate funding hypothesis;
- transaction version/canonicality/reorg model; and
- exact adapter into lane 16 topology IDs/facts.

### Red for live use

- No transport adapter in this crate has been wired to a live authenticated Helius connection.
- No paid/provider call or broad crawl was authorized or run in this lane.
- Helius request/response schema drift and credit accounting have not been characterized live here.
- The official pinned Pump/PumpSwap IDL decoder and differential conformance fixtures are not yet
  connected, so exact live swap semantics remain gated.
- Standard and Helius surfaces have not yet been cross-compared on the same finalized signatures.
- Per-scope requested coverage has not completed the core/store atomic coverage/cursor receipt path.
- Token-account owner metadata limitations in older history and address-lookup/version variants need
  additional finalized goldens.
- Transaction-local instruction/log ordering beyond the currently supplied JSON fields needs the
  protocol decoder/event adapter; absent indices remain absent.
- The Pump social plane is a separate source lane. This crate accepts its versioned promotion IDs but
  neither authenticates nor scrapes social/product feeds.

Consequently this lane is not a profitability result and not evidence that followed wallets, caller
clusters, funding candidates, or social transitions predict returns. It is the instrumentation needed
to measure those questions without future leakage or identity laundering.

## Smallest next conformance experiment

Run one entirely offline end-to-end receipt before enabling a provider:

1. feed the finalized modern-history fixture as a `RawSourceFrame`;
2. produce the exact evidence draft and wallet normalization in one call;
3. admit a pinned fixture decoder result for the Pump instruction;
4. map all transaction/caller/transfer/swap/bundle facts to `joshi-wallet-topology`;
5. commit the evidence, facts, requested coverage and cursor candidate through the real one-writer
   batch;
6. read the durable receipt and only then mark the coverage binding/store cursor advanced;
7. produce a topology snapshot before and after a synthetic noncanonical superseding version and
   prove the old dependent facts disappear from accepted/derived rows while remaining observable;
8. round-trip the exact stored blob and compare its SHA-256 and bytes to the fixture.

Pass criteria are byte equality, one transaction identity with explicit fact versions, no dangling
dependent fact, correct noncanonical exclusion, no cursor before the receipt, bounded resource use,
and no source/provider secret in any artifact.

Only after that passes should the next separately capped step open one read-only provider connection
for one known public wallet, compare modern Helius history with standard finalized Solana lookup,
measure actual bytes/credits/schema variants, and propose—not silently expand—the next cap.
