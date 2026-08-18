# Wave 6 — data and tooling envelope

Date checked: 2026-08-18
Status: research decision record; this document authorizes neither provider activation nor data
collection. It makes no API call, creates no account/key, accepts no marketplace offer, and enables
no paid or execution surface.

## Decision

Use a small **historical discovery + forward witness** envelope. Historical chain data can support
descriptive candidate discovery, raw-transaction reconciliation, and bounded response/topology
archaeology. It cannot recreate a contemporaneous router choice or all state of an unchosen route.
Therefore, no `WouldQuote`, shadow-route, or prospective active-sensing result is admissible until
the forward collector retains the named raw request/response, exact account-state closure, clocks,
coverage, and correction lineage.

The existing [routed-liquidity envelope](../routed_liquidity/01_DATA_ENVELOPE.md) remains the
quantitative starting point; [the source registry](../../implementation/wave5/02_SOURCE_REGISTRY.md)
remains the only pre-I/O/budget gate; [response atlas](../../implementation/wave6/01_RESPONSE_ATLAS.md),
[routed shadow](../../implementation/wave6/05_ROUTED_LIQUIDITY_SHADOW.md), and the
[wallet-topology contract](../../implementation/lanes/16_wallet_flow_topology.md) remain the
semantic owners. This document reconciles their input needs with currently documented surfaces.

## 1. Reconciliation of the current external envelope

| Surface | Current official interface and usable role | Explicit boundary |
| --- | --- | --- |
| Solana RPC | [`getTransaction`](https://solana.com/docs/rpc/http/gettransaction) returns a confirmed transaction or `null` and exposes encoding, commitment, and maximum supported transaction version. [`getSignaturesForAddress`](https://solana.com/docs/rpc/http/getsignaturesforaddress) is the portable address pagination fallback. Use raw transaction/meta as the primary hydration witness and preserve `null`, failure, inner-instruction/log absence, and transaction version. | Public mainnet RPC is rate limited and explicitly not intended for production; published limits can change ([cluster guidance](https://solana.com/docs/references/clusters)). It is not a historical account-state or off-chain quote archive. |
| Google public Solana BigQuery | Google labels Solana community-maintained in its [supported-datasets list](https://docs.cloud.google.com/blockchain-analytics/docs/supported-datasets); use the existing public dataset only for partitioned program/signature candidate discovery and an independent landed-tx rendering. BigQuery charges analysis by bytes processed in on-demand mode, while capacity is slot based ([official cost controls](https://docs.cloud.google.com/bigquery/docs/best-practices-costs)); public data storage is hosted by Google but query users pay and there is no public-dataset SLA ([public-data contract](https://docs.cloud.google.com/bigquery/public-data)). | Never call it a complete address index, state history, quote archive, or permanent-retention promise. Partition and clustering reduce scan; they do not prove a query is cheap. Dry-run/actual bytes and SQL digest are required before scale. |
| Helius historical + hot stream | [`getTransactionsForAddress`](https://www.helius.dev/docs/rpc/gettransactionsforaddress) provides address history with pagination, filters, full transaction responses and transaction index. [`transactionSubscribe`](https://www.helius.dev/docs/rpc/websocket/transaction-subscribe) is a provider extension for filtered full transaction notifications. Use the former for bounded finalized backfill and the latter only for a finite leased hot set followed by finalized reconciliation. | Helius currently prices `getTransactionsForAddress` at **50 credits/call**, up to 100 full transactions (or 1,000 signatures), and normal historical calls at one credit ([credits](https://www.helius.dev/docs/billing/credits)); no batch is allowed for that endpoint and plan RPS varies ([rate limits](https://www.helius.dev/docs/billing/rate-limits)). This supersedes the 10-credits/100-row planning assertion in `20_wallet_attention_acquisition.md`; registry declarations must be revised and re-approved before any live use. Enhanced parsed history remains a non-authoritative projection. |
| Jupiter Swap V2 | Current [`/swap/v2/order`](https://developers.jup.ag/docs/swap/order-and-execute) can return a quote without a taker; with one it also returns an unsigned transaction. It reports winning router and expected output across Metis, JupiterZ, Dflow and OKX. Retain each *read-only order/quote* request/response including no-route/error, router eligibility and request ID. | `/execute` takes a **signed transaction** and performs managed landing; it is categorically excluded. Optional order parameters can change router eligibility. The current platform plans list `/order` and `/build` as one credit and execute as zero credits, subject to change ([plans](https://developers.jup.ag/docs/portal/plans)); record the observed dashboard price rather than treating docs as an invoice. There is no advertised historical order/quote archive. |
| Pump / PumpSwap | The official [`pump-public-docs`](https://github.com/pump-fun/pump-public-docs) publish program IDLs, current `buy_v2`/`sell_v2` instructions and TS/Rust SDK pointers; the official [`buy` instruction guide](https://github.com/pump-fun/pump-public-docs/blob/main/docs/instructions/BUY.md) distinguishes requested quantity and maximum quote cost. Use a pinned commit + IDL hash and the already narrow decoder. | Intent limits are not fills. Derive an exact swap only from successful raw transaction legs, not SDK output or instruction arguments. No unofficial Pump portal/API or wallet-bearing credential enters the registry. |
| Meteora DLMM | The official [pool API](https://docs.meteora.ag/api-reference/dlmm/pools/pools) provides paginated pool discovery (page size at most 1,000). Use it for candidates and retain its response as a provider assertion. Direct quote replay needs the pool, vault/config and every traversed bin-array state plus a pinned DLMM math/IDL version. | The API aggregate/current fields are not an account-at-slot proof, a fill, or a quote history. No published public rate/price commitment was found in the cited API reference: run at a conservative registered cap and record `429`/headers/response bytes. |
| Raydium CPMM/CLMM | Raydium documents its [SDK/API split](https://docs.raydium.io/sdk-api): server Trade API versus SDK/IDL path. For CLMM, `PoolState` is live state read on swaps/position changes ([accounts](https://docs.raydium.io/products/clmm/accounts)); quote/replay needs pool/config/vault/observation/tick-array state and Token-2022 fee context. | Trade API is server-built transaction machinery, so quote-only endpoints may be observed but build/sign/send paths are forbidden. Its official trade guide publishes 120 quote req/min and 60 build req/min per IP with `429`/`Retry-After` ([rate-limit section](https://docs.raydium.io/ja/sdk-api/trade-api)); its rate is not a durability or completeness guarantee. |
| Orca Whirlpools | Orca's [public API](https://docs.orca.so/api-reference/overview) is unauthenticated read access for pool/analytics discovery. The official SDK overview exposes Rust/TS quote machinery, and warns that quote generation must fetch/parse tick arrays; an uninitialized array is not proof of no liquidity ([tick arrays](https://docs.orca.so/developers/architecture/tick-arrays)). | REST data is current provider data, not exact historical account state. Its docs publish only `429` backoff guidance, not a numeric quota. Direct quote replay must retain Whirlpool/config/vault/tick-array/mint-extension state and SDK/IDL version. |

The old V1-Metis material is not the primary forward witness. Jupiter's current documentation says
new integrations should use Swap V2 ([migration/changelog](https://developers.jup.ag/docs/changelog)).
Do not send signed bytes to any build/execute endpoint merely to get a more convenient witness.

## 2. Required observations, by consumer

All rows below require immutable raw-frame bytes or a content digest, producer/schema/version,
`event/valid/available/received/committed` clocks as applicable, source/method identity, and a
coverage or typed-gap identity. A later correction appends a version; it never repairs an old
as-known record in place.

| Consumer | Exact minimum observation closure | Historical support | Forward-only requirement |
| --- | --- | --- | --- |
| Response atlas | For each anchor and horizon: exact focal `MarketEvent`; mark functional/size/direction; three complete signed atom components (`same_wallet`, `same_cluster_other_wallet`, `external`) or three explicit gaps; event/response windows; lifecycle, caller and topology versions; source coverage; one competing-risk outcome or censoring/gap. The atlas's three-component and cut-off contract is authoritative ([implementation](../../implementation/wave6/01_RESPONSE_ATLAS.md)). | Raw final transactions plus a bounded, correctly versioned topology snapshot can produce **descriptive current-known archaeology**. It cannot claim contemporaneous knowledge if topology/lifecycle was learned later. | Collect finalized/reconciled raw tx, causal availability of topology/lifecycle versions, exact coverage intervals, and registered horizon outcome polling from the outset. Future-known cluster links cannot enter earlier cells. |
| Routed-liquidity shadow | Candidate signature and raw tx/meta (CPI, ALT-resolved accounts, logs, status, pre/post balances); full account manifest and every write/version at the quote cutoff; pinned program/IDL/math fingerprints; direct venue quote/refusal; Jupiter order request/response/no-route; named size/direction/fees; route candidate/eligibility set; receipt/slot/state digest; actual observed choice; sequential inventory and terminal quote manifests. | Chain history can nominate landed route hypotheses and validate decoders. It cannot prove an unchosen direct edge, RFQ alternative, router candidate set, latency/cache condition, or state for all unchosen pools. | Capture direct and Jupiter read-only witnesses at registered sizes/directions together with state writes; then require state-digest equality, not nearest timestamp. This is the necessary prerequisite in the [routed-shadow contract](../../implementation/wave6/05_ROUTED_LIQUIDITY_SHADOW.md). |
| Wallet topology | Compact census: signatures/slot/finality/canonicality observations, ordered instruction path/accounts, transfers, selected exact swap/LP decoder outputs, program/pool lifecycle, coverage and correction evidence. Hot lease additionally requires full raw tx/meta/logs/inner instructions/balances and account authority observations. | Bounded finalized backfill is viable via Helius/raw RPC plus BigQuery cross-check. It remains an observation graph: it cannot recover private ownership, full holdings, causal funding, or original availability. | Finite public-key lease, raw notification bytes, reconnect/recovery and finality correction window, atomic cursor/coverage receipt. Do not recursively crawl counterparties. The source-to-snapshot receipt boundary remains that of [lane 21](../../implementation/lanes/21_wallet_topology_admission.md). |
| Active sensing | Immutable pre-I/O assignment/seed and inclusion probability; census/denominator and protected floors; requested scope/fidelity/cadence; provider/application/coverage/exposure/nonresponse receipts; actual requests/pages/bytes/credits/wall time; presentation visibility/focus/comprehension and operator response; consent/retention class. | Not reconstructible from chain/provider history: assignment-before-I/O, exposure and presentation receipts did not exist. | Begin only after the sealed model-blind baseline. The `SensingDecisionV1` budget, floor and receipt requirements in [active sensing](04_ACTIVE_SENSING_PRESENTATION.md) are mandatory. |
| Replay and adjudication | Original normalized/raw frame bytes; schema/IDL/SDK/model/config/build digest; source method/endpoint; response status/safe headers; all clocks; full coverage/gap/cursor lineage; exact input manifest and output digest; deterministic seed/tie order; finality/canonicality correction lineage; query SQL and measured scan/billing counters. | Historical raw tx plus BigQuery result can replay a defined descriptive calculation only when inputs and availability are honestly reconstructed as *now known*. | Persist every state and quote witness at acquisition, including refusals and disconnects; retain enough to replay byte-for-byte without re-contacting a mutable provider. |

## 3. Capture topology and retention

```text
BigQuery candidate manifest / Helius address page / raw RPC hydration
    -> immutable raw frame + source event + coverage/gap
    -> finalized transaction-version and selected decoder facts
    -> compact census / finite topology snapshot
    -> response-atlas descriptive cells

forward account-write + direct venue quote + Jupiter read-only order witness
    -> slot/state digest and route-eligibility closure
    -> shadow opportunity / replay (never a fill or a causal routing claim)

registered SensingDecision before provider I/O
    -> apply/coverage/exposure/nonresponse receipts
    -> outcome closure and sealed replay
```

Keep two physically and access-separated classes.

1. **Research evidence vault:** lossless raw provider frames, public addresses, request/response
   bodies, SQL, state and quote witnesses, durable receipts, and correction history. Encrypt at
   rest, use least-privilege named readers, do not put credentials or private keys in frames,
   commits, fixtures, prompts, or issue text. Public-chain data is not anonymous: addresses and
   joins are linkable, so retain only the finite study scope, redact safe headers, and keep social/
   operator material in a separate consent-governed partition.
2. **Derived/releasable partition:** compact normalized facts and Arrow/Parquet exports with
   pseudonymous study IDs where possible; no raw social/operator text, secret, IP, authorization
   header, or full provider URL. Preserve source/evidence digests so a permitted reviewer can
   trace an export without broad raw-data circulation.

Retention is a registered policy, not an inferred provider promise: raw material lives only through
the study's correction/replay/adjudication horizon and is then reviewed for deletion or continued
restricted preservation; immutable hashes/manifests may outlive it. A lease expiry ends new
collection, never deletes already admitted evidence. Helius credits reset monthly and may consume
monthly, prepaid, then autoscaling balances ([billing order](https://www.helius.dev/docs/billing/credits));
autoscaling must stay disabled so an overrun fails as a visible gap. Provider invoice and local
ledger remain separate observations.

## 4. Capped plans — planning bands, not purchase authority

These are bounds for the fixed focus set from the routed-liquidity envelope (three mints, 10–30
pools, two directions, three sizes). They use its Strategy-C historical scan and forward compact
storage bands. Decimal `GB` is deliberately not `GiB`; budget reservations use binary bytes.
Numbers are planning estimates pending one measured closed UTC day.

| Window | BigQuery Strategy-C scan cap, base [low–high] | Raw hydrated download, base [low–high] | Forward compact storage, base [low–high] | Helius full-history calls/credits/day at 500 / 5,000 / 50,000 tx | Jupiter order credits at 1,000 / 10,000 / 100,000 witnesses/day | Decision |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 day | 10.4 GB [1–82 GB] | 60 MB [2 MB–2 GB] | 100 MB [5 MB–5.5 GB] | 5 / 50 / 500 calls = 250 / 2,500 / 25,000 credits | 1k / 10k / 100k | **C0 measurement.** 10 GiB hard scan, 3 GiB ingress, 6 GiB durable. Stop at any state/quote closure failure. |
| 7 days | 72.8 GB [7–574 GB] | 420 MB [14 MB–14 GB] | 700 MB [35 MB–38.5 GB] | 35 / 350 / 3,500 = 1,750 / 17,500 / 175,000 credits | 7k / 70k / 700k | **C1 feasibility.** 96 GiB scan, 20 GiB ingress, 40 GiB durable; reserve only base-case 17,500 Helius + 70,000 Jupiter credits if actually approved. |
| 30 days | 312 GB [30 GB–2.46 TB] | 1.8 GB [60 MB–60 GB] | 3 GB [150 MB–165 GB] | 150 / 1,500 / 15,000 = 7,500 / 75,000 / 750,000 credits | 30k / 300k / 3m | **C2 preliminary.** 384 GiB scan, 80 GiB ingress, 180 GiB durable. Continue only after the 7-day gates and an explicit cost re-registration. |
| 90 days | 936 GB [90 GB–7.38 TB] | 5.4 GB [180 MB–180 GB] | 9 GB [450 MB–495 GB] | 450 / 4,500 / 45,000 = 22,500 / 225,000 / 2.25m credits | 90k / 900k / 9m | **C3 robustness.** 1 TiB scan, 256 GiB ingress, 512 GiB durable. Only a surviving, well-covered edge or sparse regime merits this window. |

The credit arithmetic is intentionally conservative: full history pages are capped at 100 rows by
Helius's current documentation, so `ceil(tx/100) × 50`; it excludes retries, subscriptions,
BigQuery price, egress, storage, and any provider price change. Jupiter's published free plan is
rate-limited rather than credit-limited, while paid plans include/reset credits and excess is listed
as $1 per million credits ([pricing](https://developers.jup.ag/pricing)); no paid plan, API key or
autoscale setting is implied here. Meteora/Orca/Raydium discovery calls receive independent request,
byte and wall-time ceilings until a measured response distribution is registered.

### Hard admission rules

- Reserve worst case **before** each request/page/stream interval across requests, pages, ingress,
  durable bytes, provider credits, event count, provider currency and wall time. Do not borrow one
  dimension for another.
- Use only closed UTC partitions for a historical day; preserve current-partition and recovery
  windows as incomplete until finality/correction policy closes them.
- At one day, reject scaling if measured scan exceeds 10 GiB, compressed durable data exceeds 6
  GiB, candidate hydration is below 99% without bounded gaps, or BigQuery/RPC conformance is below
  99.5% on its predeclared sample.
- At seven days, stop/shelf shadow work if any direct quote cannot name every state account at its
  cutoff, any route witness lacks request/response/eligibility closure, ALT/CPI replay fails, or
  a source gap is represented as a zero/no-route.
- At 30 days, require 500–3,000 effective paired opportunities per claimed edge/regime, temporal
  holdout, registered fee/landing/inventory assumptions, and survival of perturbation checks.
- At 90 days, stop when the earlier claim does not survive, storage or cost grows beyond the new
  registered cap, or privacy review does not justify continued wallet/attention retention.

## 5. Build versus buy

| Need | Buy/read surface | Build/own seam | Decision |
| --- | --- | --- | --- |
| Broad historical candidates | Public BigQuery; Helius address history | Candidate reason, SQL/partition digest, raw-RPC reconciliation | Buy/read. Do not self-index the chain for the pilot. |
| Raw transaction truth | Helius or an archival RPC | Lossless raw-frame retention, finality/correction reducer, protocol decoder | Hybrid. Provider is transport; raw frame and decoder stay owned. |
| Forward account state | Narrow provider stream first | Exact account manifest, write/slot/fork ordering, coverage/gap and state digest | Build the evidence seam; defer a self-hosted Geyser/validator. Agave's [Geyser interface](https://github.com/anza-xyz/agave/blob/master/geyser-plugin-interface/src/geyser_plugin_interface.rs) is the semantic reference, not a pilot requirement. |
| Router/venue witnesses | Jupiter read-only order; direct protocol SDK/API state/quote | Quote envelope, direct math differential tests, refusal semantics, state join | Hybrid; never buy an opaque historical quote claim. |
| Wallet graph | No graph database | Existing typed snapshot/reducer, NetworkX/SciPy analysis projection | Build/retain typed rows; no Neo4j/Raphtory-style second truth store. |
| Statistics / point process | Python scientific stack | Coverage-aware risk sets, exact likelihood/score/replay wrapper | Build the wrapper, not a generic modeling platform. |
| Formal assurance | Lean for small specifications | Checked invariants and property/differential fixtures in Rust | Use formal proof only for stable pure properties; it cannot certify coverage or provider truth. |

## 6. Tooling posture

The [modeling toolbox](../../implementation/MODELING_TOOLBOX.md) remains correct in architecture:
Arrow/DuckDB are interchange/cohort authority; Python is offline research; Rust owns exact facts,
bounds and exports. Refresh its package *versions* only when a named experiment is admitted.

| Workload | First tool | Promotion gate / non-claim |
| --- | --- | --- |
| Exact preprocessing and constrained optimization | NumPy/SciPy (`scipy.stats`, sparse, `optimize`, numerical integration) — [current SciPy reference](https://docs.scipy.org/doc/scipy/reference/stats.html) | Use integer/decimal source atoms until a declared float model matrix; record threads, solver, tolerance, seed and convergence. |
| Duration, censoring and calibration | `statsmodels.duration` supplies right-censored survival and PH regression ([official docs](https://www.statsmodels.org/stable/duration.html)); lifelines is an exploratory oracle only | Model risk set, left truncation, interval/source censoring and competing causes in Joshi inputs; no package default can convert coverage loss into healthy survival. |
| Wallet/pool graphs | NetworkX `MultiDiGraph` for inspectable temporal snapshots ([graph types](https://networkx.org/documentation/stable/reference/introduction.html)); SciPy sparse for `B1`/Hodge checks | Multiplicity, direction, validity and availability must be explicit edge attributes. A graph metric is not identity, coordination, ownership, or causality. |
| Rust graph/export path | Existing typed rows; add `petgraph` only after a named bounded online workload | `petgraph` provides graph representations/algorithms ([crate docs](https://docs.rs/petgraph/latest/petgraph/)), but it must not become topology or evidence authority. |
| Point process | Start with binned/counting-process baselines in SciPy/statsmodels and a project-owned likelihood. `tick` can be a differential Hawkes probe ([official docs](https://x-datainitiative.github.io/tick/modules/hawkes.html)); do not promote its result blindly. | Hawkes excitation is association conditional on the supplied marks/coverage, not an influence/causal-route claim. Reject coincident/ambiguous order and gaps according to the registered model. |
| Rust numerical point process | Keep a small explicit implementation, `ndarray` only for arrays and `atelier_quant` only as a non-authoritative Hawkes comparison ([ndarray](https://docs.rs/ndarray/latest/ndarray/type.Array.html), [Hawkes API](https://docs.rs/atelier_quant/latest/atelier_quant/hawkes/core/struct.HawkesProcess.html)) | No Rust port until frozen Python replay, gradient/finite-difference agreement, stress bounds and an online latency need all pass. |
| Formal seam | Lean 4 for algebraic invariants such as canonical ordering, half-open windows, component total and `B1 @ B2 = 0`; Lean's kernel checks proof terms ([reference](https://lean-lang.org/doc/reference/latest)) | Formalize only a stable spec with executable extraction/differential fixtures. It cannot establish data completeness, protocol-version parity, or economic counterfactuals. |

## 7. Minimum sequence and stop gates

1. Register the source/method/price fingerprints and a C0 budget; take one closed-day metadata and
   dry-run measurement without provider activation.
2. If the measured scan fits, perform the 7-day read-only feasibility only after the registry can
   express Helius's current 50-credit call price and explicit provider-rate/backoff semantics.
3. Admit forward capture only for the finite pool/wallet scope, with a complete direct-quote account
   manifest and a read-only Jupiter witness. A signed transaction, `simulateTransaction`, builder,
   or `execute` path is outside scope.
4. Build response-atlas and topology outputs first as coverage-qualified descriptive artifacts.
   Keep routed shadow disabled until quote-to-state equality and every decoder/account closure pass.
5. Begin active sensing only after the sealed baseline, separate registration and protected floors;
   no model output changes initial acquisition or presentation.

**Stop, retain the gap, and do not substitute a proxy** when pricing/rate/schema changes without a
new registry version; an account/tick/bin/ALT/CPI state is missing; raw/provider and BigQuery
disagree without classification; a response quote lacks its exact state or receipt clock; source
coverage is discontinuous; wallet scope expands recursively; a model needs future-known topology;
or a provider surface requires a signer/wallet-bearing credential. The valid fallback is a smaller,
plainly labelled descriptive census/replay—not an inferred shadow fill or execution recommendation.
