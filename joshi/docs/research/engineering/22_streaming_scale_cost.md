# Engineering lane 22 — streaming scale, control plane, and cost

Status: engineering research; no implementation, paid-service purchase, or transaction authority.

Survey date: 2026-08-16. Provider prices and product limits below are point-in-time facts from
primary documentation and must be rechecked before any purchase. Workload rates marked **measured**
come from the `joshibot` compost on this machine; all other rates are explicit planning scenarios,
not forecasts.

## 1. Recommendation

The pre-September runway should fund a **selective local observatory**, not an always-on copy of
the Solana/Pump firehose:

1. Continuously retain the cheap denominator: launches, migrations, the one Pump surface chosen by
   Spike 0, coverage, and low-rate lifecycle facts.
2. Route followed-wallet events, operator gestures, board entries, and family/territory queries
   into a small candidate queue.
3. Promote at most a few candidates into bounded hot scopes. Only hot scopes receive every trade,
   reserve update, size-specific quote evaluation, social revision, and consequential scene blob.
4. Keep quote arithmetic and joins local. A provider call may corroborate a quote; it must not be
   required for every market event.
5. Make source scope, byte use, credits, SOL charges, queue depth, and gaps first-class control-plane
   state. Budget exhaustion is a visible degradation event, not an overage surprise.
6. Do not buy Geyser, a full-market stream, managed compute, or a validator in the pre-September
   corridor. First run the zero-incremental-cost capacity experiment in section 13 and promote only
   when a measured threshold is crossed.

This is not a retreat from market-wide estimation. It is the way to preserve the denominator
without paying to treat every failed sniper transaction, thread image, and hypothetical quote as
equally valuable. Territory/family queries mostly reuse facts the census already needs; they do
not justify a new stream. Followed wallets nominate candidates; they do not justify copying every
wallet or subscribing to every mint those wallets ever touched.

## 2. Boundaries inherited from the foundation

This lane refines the accepted census/hot-scope split in
[`FOUNDATION.md`](../../decisions/FOUNDATION.md) and the one-loop gate in
[`PRE_ENGINEERING_PROGRAM.md`](../../decisions/PRE_ENGINEERING_PROGRAM.md). It does not select a
database or authorize the collector stack that the pre-engineering program explicitly defers.

The logical flow is:

```text
cheap market census
  launches · migrations · selected boards · coarse lifecycle · coverage
          |                         |
          |                         +------> territory/family query views
          v
candidate router <-------- direct watched-wallet event / callout / operator nomination
          |
          | promote(scope manifest, TTL, reason, budget)
          v
hot lanes
  exact trades · reserves · local quotes · selected social · scenes · wallet reconciliation
          |
          v
append-oriented evidence + disposable projections
```

The acquisition system is read-only. None of these queues, priorities, or degradations can create,
sign, or submit a transaction.

## 3. What the compost has already measured

These anchors are more useful than generic Solana throughput figures because they measure this
project's actual filters and payloads.

### 3.1 Launches and boards

- The independent 24-hour launch census contains **33,202 launches**, or **0.384/s** on average.
  A separate live analysis reports a real rate near **1,090/hour**; the PumpPortal free launch feed
  was observed near 30/minute in another window. Plan for 0.3–0.5/s normally and measure the tail.
- The 2026-08-15 board tape polled five boards, up to 50 cards each, every 30 seconds. It wrote
  147,002 records and **297.6 MB** of JSONL. Gzip reduces that exact file to **66.1 MB**. The
  11,407 snapshot records average 22.3 KB each; the normalized card exposure is about 6.6 card
  observations/s. This is cheap enough to retain, but it is not free and it is interval-censored.
- The 2026-08-15 and 2026-08-16 PumpPortal launch tapes contain 27,399 and 31,324 rows, respectively;
  the former is 27.3 MB raw and 6.6 MB gzipped.

These are local artifacts, not guarantees about tomorrow's market or endpoint.

### 3.2 The full Pump/PumpSwap log stream

`studies/RESULT_pump_logs_spike.md` measured a 720-second standard WebSocket run:

| Quantity | Measured result |
|---|---:|
| Pump + PumpSwap notifications | 1,116,600 |
| Mean input rate | **1,552 messages/s** |
| Observed peak on one program | **2,568 messages/s** |
| Uncompressed input | **2.765 MB/s = 238.9 GB/day** |
| Decodable successful events | **327 rows/s = 28.2 million/day** |
| Minimal compact reducer estimate | **about 1.4 GB/day at 50 bytes/row** |
| Receive-loop work | 52 seconds of the 720-second run |

The stream achieved full recall against the checked interior RPC signature sets in that bounded
window. That establishes feasibility, not permanent completeness. It also found that roughly nine
of ten Pump-program notifications were failed transactions. The raw program log is therefore
valuable for source/audit samples and failure-flow studies, but paying to retain all of it is not
required to maintain a successful-event census.

The durable size has a meaningful range. At 28.2 million successful rows/day:

| Compressed/enveloped bytes per compact row | Durable volume/day |
|---:|---:|
| 50 B (measured reducer floor) | 1.41 GB |
| 80 B | 2.26 GB |
| 150 B | 4.24 GB |
| 250 B | 7.06 GB |

The pilot must measure the real envelope, compression, indexes, manifests, and write amplification;
the 50-byte floor must not be used as a storage promise.

### 3.3 Current selective wallet/token stream

The existing PumpPortal subscription covering four token streams and two accounts measured about
**3.6 metered trade events/minute**, approximately 5,200/day. The 2026-08-15 trade JSONL is 1.9 MB
raw and 0.40 MB gzipped. This proves that a small promoted set is tiny compared with the full
program stream. It does not predict the rate from 10–20 different watched wallets: wallet activity
is heavy-tailed and correlated during launches.

PumpPortal's current documentation says launch and migration subscriptions are free, while token
and account trade messages cost **0.01 SOL per 10,000 messages** and require a linked wallet funded
with at least 0.02 SOL. It also directs clients to use one WebSocket and update subscriptions on
that connection. ([data API](https://pumpportal.fun/data-api/bonk-fun-data-api/),
[fees](https://pumpportal.fun/fees/))

At the published rate:

| Metered messages/day | Monthly data charge, excluding the funding balance |
|---:|---:|
| 5,200 (the measured current subscription) | 0.156 SOL |
| 20,000 | 0.600 SOL |
| 100,000 | 3.000 SOL |

The USD value is deliberately omitted because it changes with SOL. The control plane must show both
the native-unit burn and a point-in-time USD translation without calling the latter stable.

### 3.4 Current local capacity

Read-only inspection on 2026-08-16 reports:

- Mac model `Mac14,5`, 12 logical CPUs, and 96 GiB RAM;
- about 634 GiB free on the data volume, which is already 92% allocated;
- roughly 65 GB apparent size under the old repository's `state/` tree.

CPU and RAM are ample for the selective slice and probably for compact-event reduction. Disk
runway and continuous uptime are the first local constraints. A 90-day archive at 7 GB/day would
consume the entire current free-space margin; even 4 GB/day requires a deliberate retention or
offload decision.

## 4. Evidence classes must be costed separately

“Whole market” is not one rate. The following planning envelopes keep acquisition choices
separable. Ranges labeled assumed are inputs to the capacity experiment, not facts.

| Evidence class | Initial rate / cadence | Payload assumption | Daily order of magnitude | Retention posture |
|---|---:|---:|---:|---|
| launches + migrations | measured 0.3–0.5/s average; assume 1.5/s burst | measured about 1 KB JSONL/launch | 25–90 MB raw; 6–25 MB compressed | all compact records; exact source observations |
| five board snapshots | measured 5 × up to 50 cards / 30 s | measured 22 KB/snapshot plus deltas | 298 MB raw, 66 MB gzip on sampled day | all raw responses or lossless blobs + normalized order/deltas |
| market-wide successful trades | measured 327 rows/s | assumed 80–250 B compressed evidence row | 2.3–7.1 GB | deferred; all compact facts only if acquired |
| unfiltered program logs | measured 1,552 messages/s, 2.765 MB/s | measured wire bytes | 238.9 GB ingress | do not retain continuously; bounded samples and gap evidence |
| hot-mint trade/state events | assume 1–20/s/mint normally, 100+/s burst | 0.3–1.5 KB raw envelope | depends on promoted mints and TTL | all while scope is healthy; explicit overflow gap otherwise |
| watched-wallet candidates | measured aggregate 0.06/s for current set; plan by message budget | 0.3–1.5 KB | small until a promoted wallet is very active | every direct decoded event for declared wallets |
| quote evaluations | derive locally per state change; coalesce UI refresh | 0.2–1 KB consequential artifact | compute-bound, not network-bound | persist displayed, acted-on, policy-triggering, and sampled checks |
| social text headers | assumed 20 hot communities every 60 s | assumed 20 KB/response | 0.576 GB raw response traffic | hot scopes only; revisions and pagination coverage |
| faster social text | assumed 20 communities every 15 s | assumed 20 KB/response | 2.30 GB | only when observed interaction warrants it |
| broad social text | assumed 100 communities every 15 s | assumed 20 KB/response | 11.52 GB | later capacity tier; not September |
| media blobs | assumed 20–200 new objects/day | 0.3–2 MB/object | 6–400 MB | fetch once, content-hash, explicit retention class |
| consequential scenes | assumed 20–100/day | 0.3–2 MB screenshot plus small manifest | 6–200 MB | manifests durable; private screenshot lifecycle separate |

Social-response and blob sizes must be measured against the selected Pump loop. The present Pump
social contracts are reverse-engineered and mutable; no broad crawl should be sized from these
illustrative numbers or treated as stable API entitlement.

### Quotes are not a provider firehose

For one reserve update, a workbench may want buy and sell values at several sizes. Six local quote
evaluations per update across 20 hot mints at five updates/s/mint is 600 evaluations/s, but it is
still zero additional network requests if exact state and pinned protocol math are local. Persist:

- every quote Ember saw or acted beside;
- every evaluation capable of firing a future policy;
- calibration samples compared with official SDK/direct and router responses;
- the exact state, size, fees, route, code/IDL version, and clocks needed to regenerate others.

Do not persist six near-identical display rows for every event merely because they were cheap to
compute. Do not call a remote quote endpoint 600 times/s merely because the UI could have refreshed
that often.

### Territory and family queries add little ingestion by themselves

A territory/family strip should query launches, metadata/image hashes, social membership, direct
wallet flows, pools, and current liquidity already on the evidence tape. Its additional durable
load is assertions, adjudications, and small materialized indexes. If a territory requires every
thread and media object for every possibly related mint, that is a hot-scope expansion with its own
manifest and budget—not a consequence of drawing a family edge.

## 5. Explicit workload scenarios

These scenarios are decision envelopes. Rates are deliberately conservative where no measurement
exists, and a row's high end must not be silently selected as “expected.”

### S0 — pre-September truth test

- free launch/migration census;
- the single Pump discovery surface selected by Spike 0 (the existing five-board tape is a useful
  capacity upper bound, not a product requirement);
- at most five simultaneous hot mints, normally session-bound;
- at most 10 directly verified wallet identities if wallet routing is part of the selected loop;
- at most 10 hot social scopes at a 60-second baseline, accelerated only while visible;
- local quote computation; only displayed/consequential quote artifacts retained;
- no market-wide trade firehose, media crawl, or live LLM inference.

Planning envelope: 10–50 source events/s sustained while active, 200/s short bursts, 0.1–1 GB/day
compressed durable data, and less than 2 GB/day network traffic. These are hypotheses to measure.
The exact existing board-plus-launch tapes would use roughly 73 MB/day gzipped before store/index
overhead.

### S1 — useful selective observatory

- continuous launches/migrations and one or a few earned surfaces;
- 10–20 wallet routes, max 20 simultaneous hot mints, max 20 hot territories;
- 20 social scopes at 60 seconds, with a subset at 15 seconds;
- local chart/quote processing and bounded social/media blobs;
- no unconditional full-program raw stream.

Planning envelope: 25–150 relevant events/s average, up to 1,000/s bursts, 0.5–5 GB/day durable,
and 1–15 GB/day ingress. Variable wallet-provider charges are bounded by messages, not by the
nominal wallet count.

### S2 — full compact Pump/PumpSwap successful-event census

Use the actual program-stream measurement: 1,552 messages/s and 238.9 GB/day input, plan for a
5,000 messages/s burst, and reduce to 327 successful rows/s / 2.3–7.1 GB/day durable. Failed
transactions should initially be time-bucketed with deterministic raw samples; retain all of them
only if a named study earns the additional bytes.

This scenario is computationally plausible locally. It is not economically plausible through the
currently measured metered standard WebSocket path for the pre-September corridor.

### S3 — later broad social joins

S3 adds up to 100 hot/community scopes, faster revisions, richer media, and optional model
annotations. At the explicit assumption of a 20 KB response every 15 seconds, the text-response
traffic alone is 11.5 GB/day before media. The first optimization is conditional retrieval and
content/revision deduplication, not a distributed stream processor.

Realtime LLM analysis is downstream of the retained evidence. Model calls should be triggered by
new/revised content in a hot lane or by a retrospective batch, with duplicate content cached and a
daily token/currency budget. A model outage or exhausted budget may delay annotations; it must not
drop source evidence or stop the cockpit.

### Scenario resource summary

CPU/RAM figures here are experiment ceilings for acquisition, decoding, joins, and quote math—not
predictions or database sizing. Browser rendering and offline model inference are measured
separately. “Logical CPU” means one of the 12 logical CPUs observed on the current machine.

| Scenario | Sustained / burst ingress | Local quote-evaluation envelope | Network/day | Durable/day | Acquisition/reduction experiment ceiling |
|---|---|---:|---:|---:|---|
| S0 | assumed 10–50/s / 200/s | up to 1,000/s in brief hot bursts | <2 GB | 0.1–1 GB compressed | <=1 logical CPU average, <=2 GiB RSS; whole host remains responsive |
| S1 | assumed 25–150/s / 1,000/s | up to 2,000/s | 1–15 GB | 0.5–5 GB | <=4 logical CPUs and <=8 GiB RSS at peak; whole host below the section 13 limits |
| S2 | measured 1,552/s; design burst 5,000/s | independent selective hot-quote budget | measured 238.9 GB raw WSS input | 2.3–7.1 GB compact | <=4 logical CPUs and <=16 GiB RSS for ingest/decode/commit at measured rate; otherwise optimize or compare managed filtering |
| S3 addition | assumed 1.7–6.7 social requests/s plus S1 | same as S1 | +2.3–11.5 GB text before media | measure change/revision yield | JSON/join work fits S1 ceiling; model inference has a separate queue and budget |

The old full-stream receive loop spent 52 of 720 seconds doing receive/decode work, which suggests
the raw S2 event rate is locally tractable. It did not include the proposed durable schema,
compression, indexes, concurrent UI, crash protocol, or replay, so only the end-to-end load test may
accept the CPU ceilings.

## 6. Transport comparison

| Transport | Best use here | Advantages | Failure/cost shape | Posture |
|---|---|---|---|---|
| HTTP polling | Pump boards, mutable social pages, periodic state reconciliation | simple, source-specific cadence; exact request/response evidence | interval censoring, repeated bytes, cache ambiguity, 429s, pagination truncation | required where no push contract exists; retain attempt status and cadence |
| standard Solana WebSocket | bounded program/wallet/account probes and a cheap first comparator | standard interface; `logsSubscribe` yields slot, signature, error and logs | no native replay; provider metering; `mentions` supports one address per subscription; broad program logs waste bytes | use selectively and in the provider shootout |
| PumpPortal WebSocket | free launches/migrations; small token/wallet hot routes | task-specific, one connection with dynamic subscriptions, already proven locally | vendor schema/time/precision limits; token/account events are SOL-metered; no completeness guarantee | useful adapter, never sole chain truth |
| managed Yellowstone-compatible gRPC | filtered program transactions/accounts at larger sustained scope | binary protocol, rich server-side filters, lower envelope overhead, provider replay options | $499-class mainnet entry at surveyed providers, vendor-specific limits/replay, out-of-order delivery, byte metering | consider only after S1/S2 threshold and a measured trial |
| provider Webhooks/APIs | sparse wallet addresses, history/backfill, independent normalization checks | avoids maintaining a live socket; convenient address sets | callback infrastructure, retries outside our control, per-event/per-call credits, enriched-schema lock-in | comparator or sparse router, not canonical tape |
| self-hosted validator/RPC + Geyser | very large sustained feed where provider spend and control justify an ops team | complete control over filters/plugin and no provider byte meter | dedicated high-end hardware, bandwidth, upgrades, forks, replay, disk wear, 24/7 operations | explicitly out for September |

Solana documents that `logsSubscribe` can filter transactions mentioning exactly one public key,
and that `programSubscribe` emits changes for accounts owned by a program; they are different
evidence and neither is historical replay. ([`logsSubscribe`](https://solana.com/docs/rpc/websocket/logssubscribe),
[`programSubscribe`](https://solana.com/docs/rpc/websocket/programsubscribe)) Public mainnet RPC is
rate-limited and expressly not intended for production applications, so it is suitable for a
bounded feasibility test, not an uptime promise. ([cluster endpoints](https://solana.com/docs/references/clusters))

Yellowstone is an open protocol boundary, not a delivery guarantee. Helius currently advertises
up to 24 hours of replay and mainnet gRPC on Business or higher; its documentation explicitly says
messages, including account updates within a slot, can arrive out of order. QuickNode advertises
up to 3,000 slots of replay and includes gRPC on Scale and Business. These materially different
recovery windows belong in the provider scorecard, not behind one `stream_ok` Boolean.
([Helius LaserStream](https://www.helius.dev/docs/laserstream),
[Helius ordering FAQ](https://www.helius.dev/docs/faqs/laserstream),
[QuickNode gRPC](https://www.quicknode.com/docs/solana/solana-grpc/overview),
[Yellowstone repository](https://github.com/rpcpool/yellowstone-grpc))

### Why self-hosting is not the cheap next step

Anza's current guide recommends at least 16 cores/32 threads and 512 GB RAM for an RPC node with
all account indexes, separate high-endurance NVMe storage of at least 1 TB for accounts, 1 TB for
ledger, and 500 GB for snapshots, plus 1 Gbit/s symmetric networking with 10 Gbit/s recommended.
That is not the current local workstation and it is a separate operational job.
([Anza system requirements](https://docs.anza.xyz/operations/requirements))

Self-hosting a small Joshi collector that consumes someone else's RPC is normal local-first
operation. Self-hosting Solana itself is the out-of-scope step.

## 7. Provider economics and the September runway envelope

### 7.1 Current published prices

Helius currently lists Free at 1 million credits, Developer at a $49/month list price with
10 million credits, Business at $499/100 million, and Professional at $999/200 million. All
standard and enhanced WebSocket traffic is billed by **uncompressed** size at 2 credits/0.1 MB;
mainnet LaserStream gRPC requires Business or Professional. Additional credits on paid plans are
listed at $5/million. ([credits](https://www.helius.dev/docs/billing/credits),
[plans](https://www.helius.dev/pricing))

Applied to the measured 238.9 GB/day standard-WebSocket stream:

```text
7,167 GB/month × 1,000 MB/GB × 20 credits/MB
  = 143.34 million credits/month

Developer: $49 + (143.34M - 10M) × $5/M ~= $715.70/month
Business:  $499 + (143.34M - 100M) × $5/M ~= $715.70/month
```

The measured Pump-only `transactionSubscribe(failed:false)` path was 55.2 GB/day and would be
about 33.12 million credits/month, or **about $164.60/month** on Developer at those list rates.
It was not recall-tested in the old spike, so this is a cost bound for a candidate, not a source
recommendation.

QuickNode currently lists Scale at $499/month with 950 million credits; its June 2026 primary
announcement says Solana gRPC is included on Scale and metered at 10 credits/0.1 MB, with up to
3,000-slot replay. Helius advertises mainnet LaserStream beginning with its $499 Business plan and
dedicated nodes starting at $2,900/month. Envelope, compression, filter, and credit definitions
are different, so advertised credits do not settle comparative cost without sending the exact
Joshi filter through both. ([QuickNode pricing](https://www.quicknode.com/pricing),
[QuickNode gRPC plan announcement](https://www.quicknode.com/blog/solana-grpc-is-now-included-with-scale-and-business-plans),
[Helius pricing](https://www.helius.dev/pricing))

Optional object storage is cheap relative to stream ingress. Cloudflare R2 currently lists Standard
storage at $0.015/GB-month, with 10 GB-month, one million Class A writes, and ten million Class B
reads included monthly, and no egress charge. Segmenting by minutes/hours rather than writing one
object per event keeps operation counts small. This is a comparison point, not a purchase
recommendation; encrypted local removable backup may be preferable for private scenes.
([R2 pricing](https://developers.cloudflare.com/r2/pricing/))

### 7.2 Pre-September planning bands

Lane 24 identifies roughly two weeks from 2026-08-16 to September as the immediate delivery
corridor. No verified cash runway after that date, September income, or active service inventory is
recorded in `joshi`. Prior fee income and trading PnL must not be assumed. The pre-engineering
decision also withholds authorization for paid infrastructure. Therefore the only authorized
pre-September envelope is:

| Band | Incremental spend | Meaning |
|---|---:|---|
| **authorized / recommended** | **$0** | local compute/storage; free sources; only already-paid quotas after measuring remaining allowance; no autoscaling or automatic top-up |
| planning comparison only | up to roughly $49/month | one reversible developer RPC plan or small backup service, only after explicit approval and a passed product-feasibility gate |
| excluded before the next runway decision | $400–$499+/month | managed Geyser/data tier or Scale/Business plan |
| excluded | $999–$2,900+/month and hardware | professional data products, shreds, or dedicated/self-hosted nodes |

If no new decision is made on September 1, the $0 incremental default continues; crossing a date
does not manufacture revenue or spending authority.

Native-unit PumpPortal charges sit outside the $0 band even if a wallet already has balance. A
future approved pilot must set both an event ceiling and a SOL ceiling, disable automatic refill,
and stop before the ceiling rather than treating funded balance as permission.

Existing subscription fees are not “free”; inventory their renewal date, included credits,
autoscaling state, and competing uses before calling marginal capacity available. Helius now
documents an Admin API for current credit usage, so the earlier inability to observe usage should
be re-tested through the supported endpoint rather than scraped from a dashboard.
([Helius Admin API](https://www.helius.dev/docs/api-reference/admin))

## 8. The control plane

This workload does not require Kafka or Kubernetes. It does require one durable desired-state and
coverage ledger. The initial durability boundary should be the single-writer SQLite/catalog path
selected by [`15_data_replay_storage.md`](15_data_replay_storage.md), not a second custom log. A
minimal control-plane model is:

```text
SourceManifest
  source/endpoint/contract version
  desired scopes and subscription keys
  acquisition mode, cadence, commitment, and fields
  priority class and fidelity tier
  byte/request/message/native-unit budgets
  retry and backfill policy
  retention class

ScopeLease
  scope id and typed subject (mint, wallet set, person, family, territory, pool)
  opened at / expires at / renewed at
  promotion reason and parent candidate event
  feeds actually acknowledged
  budget remaining and current degradation

CoverageInterval
  source + exact scope manifest + connection generation
  request/receive/persist interval or slot/index watermarks
  expected completeness class
  received, duplicate, conflict, parse-failed, quarantined, and sampled counts
  known gaps and backfill evidence
  sampling probability/policy version
  close/degrade reason
```

The controller reconciles desired subscriptions with acknowledged reality. Promotion is
idempotent: reopening the same scope extends or changes a lease and appends that fact; it does not
silently create a second billable socket. Demotion closes only feeds named in the lease. An episode
may remain watching-flat while its mint stays hot.

One connection should carry many PumpPortal token/account subscription changes as the provider
requires. Standard WebSocket and gRPC connections should similarly batch compatible filters while
keeping per-key coverage visible. A healthy connection is not proof that a particular wallet key
is still subscribed.

### Priority classes

| Priority | Records | Backpressure rule |
|---|---|---|
| P0 | operator gestures/scenes, portfolio and quote dependencies, hot-scope chain state, coverage/gap/budget events | never intentionally sample; fail closed and declare incident if durable write cannot keep up |
| P1 | launches/migrations, direct watched-wallet events, compact market census, source heartbeats | spool durably; may delay projections, not silently discard |
| P2 | board/social snapshots, metadata revisions, territory joins | reduce cadence or pause declared scopes with explicit coverage intervals |
| P3 | media, backfills, screenshots not tied to a consequence, LLM/embedding jobs, bulk derived views | suspend first; replay later if still available and useful |

Control records themselves are P0. A system that drops the fact that it began dropping data cannot
make an honest replay.

## 9. Backpressure, deduplication, ordering, and retry

### 9.1 Backpressure

Use bounded in-memory queues feeding the single durable committer. Queue occupancy is measured in
both records and bytes; a few large social/media responses can dominate a record-count-safe queue.
Each source has its own ingress queue so a board response cannot block hot reserve state. The
initial SQLite outbox/spool is for already committed projection work; this lane does not introduce
a custom ingress log or broker before the storage benchmark fails.

High-water actions are monotone:

1. stop optional projection/model/media work;
2. coalesce UI refreshes and recomputable quote displays while retaining the underlying state;
3. slow cold polling and record the new cadence;
4. stop accepting new hot-scope promotions and show the reason;
5. give P0/P1 the reserved share of the durable commit budget;
6. if the committer cannot accept P0/P1, open a coverage gap, invalidate dependent currentness, and
   stop the affected source rather than losing records invisibly.

The reducer may aggregate failed-transaction counts by fixed source/slot/time windows only after a
deterministic raw sample and exact input count are committed. It may not throw failed transactions
away before a future failure-flow study can estimate what was omitted.

### 9.2 Identity and deduplication

At-least-once acquisition plus deterministic dedupe is the honest contract:

- every request/frame delivery is a unique observation, even when bytes repeat;
- identical bytes share a content hash but do not erase repeated observations;
- chain-event identity is `(cluster, signature, transaction index, instruction path/event index)`
  when those locators exist;
- account state is keyed by `(cluster, account, slot, write version)`;
- provider event IDs are retained in a provider namespace, never promoted to universal identity;
- same natural event key with different bytes becomes a visible conflict/revision;
- two equal fills at different instruction indices remain two fills.

Raw observation dedupe controls storage; assertion/event dedupe controls economic double counting.
They are separate operations.

### 9.3 Ordering

Preserve arrival order and source-native order. Canonical chain projections order by slot,
transaction index, instruction/event index, and write version where available. Standard
`logsSubscribe` supplies slot and signature but not a transaction index; do not invent one from
receive time. A finalized block/backfill may later establish retrospective order without rewriting
the witnessed arrival sequence.

Buffering by slot is allowed for derived views, with an explicit maximum wait. Past that bound the
view publishes partial order plus a late-event marker. Helius's documented out-of-order gRPC
delivery makes this client responsibility even under a premium source.

### 9.4 Retry and recovery

- HTTP reads: honor `Retry-After`, use capped exponential backoff with jitter, persist each attempt
  status/body hash, and distinguish valid empty response from transport failure.
- WebSocket/gRPC: increment connection generation, resubmit the exact desired manifest, require or
  infer acknowledgements per key, overlap the recoverable slot/time window, and rely on dedupe.
- Cursor advancement: commit evidence and the cursor/watermark atomically or repeat after crash;
  the cursor never outruns durable evidence.
- Backfill: fetch finalized history for the declared gap, retain its late availability time, and
  close only the portion proven covered. “Reconnect succeeded” does not close a gap.
- Provider APIs: retry idempotent reads; webhook/event acknowledgement happens only after durable
  append. A retry may duplicate an event and must not change its semantic identity.

## 10. Coverage accounting and adaptive sampling

Coverage is a queryable product, not a green light:

- **polling coverage** records every scheduled attempt, successful snapshot interval, response
  cache/computation clock, pagination cursor, and failure interval;
- **stream coverage** records requested and acknowledged filters, connection generation, slot
  watermarks, heartbeats, reconnects, and finalized cross-checks;
- **wallet coverage** is per verified direct-trade wallet key; ambient traffic on the same socket
  cannot keep a silent wallet route green;
- **hot coverage** records activation latency and the left-truncated interval before promotion;
- **social coverage** distinguishes root, reply tail, revisions, media, and membership; a complete
  first page is not a complete thread;
- **budget coverage** records scopes not observed because a byte/request/SOL budget was exhausted.

Adaptive sampling is allowed only when its selection mechanism survives replay:

1. Never sample operator acts, current portfolio/quote dependencies, direct hot-lane facts, or gap
   records.
2. Preserve all low-volume launches/migrations and exact board order for the selected surface.
3. Sample verbose raw market transactions deterministically by signature hash, optionally
   stratified by program, success/failure, time, size, and lifecycle. Store inclusion probability
   and policy version.
4. Change cold poll cadence using a logged controller state, not invisible “smart polling.” Board
   entry time remains interval-censored under the actual cadence.
5. Keep a small source-neutral random control sample even when hot promotion is activity-driven.
   Otherwise every retained high-resolution coin is selected on the outcome-generating process.
6. Do not reduce fidelity precisely during bursts without declaring that missingness; peak load is
   usually the scientific target.

The controller can spend a fixed daily observation budget across cold, random-control, and hot
strata. It cannot claim the sampled union is a census.

## 11. Graceful degradation

Degradation should preserve the cockpit's truthfulness in this order:

| Condition | Continue | Degrade/stop | Visible consequence |
|---|---|---|---|
| model/inference budget exhausted | raw social and market capture | LLM labels, embeddings, summaries | annotations delayed/unavailable |
| media or blob pressure | text locators, manifests, consequential scenes | speculative media prefetch | placeholder plus omitted-retention reason |
| social endpoint throttled | chain, boards, cached social with age | social cadence and reply tails | social pane stale/gapped; social policy unavailable |
| cold board pressure | active hot lanes, operator/portfolio state | slower cold polls | wider membership interval censoring |
| wallet vendor budget nearing cap | already-hot direct chain scopes and manual nomination | new metered wallet routes | candidate coverage incomplete; no “wallet quiet” claim |
| chain stream backlog | P0 hot/portfolio, compact P1 spool | derived charts/analytics and new promotions | chart/quote age and gap shown |
| quote/state dependency stale | observation and manual external navigation | shadow proposal/current executable claim | quote marked stale/unquotable; future authority would fail closed |
| durable spool unavailable | only already-rendered stale state with warning | affected acquisition | explicit incident; no silent memory-only continuation |

The product may remain useful with stale social data and a current chain chart. It may not show one
global “healthy” badge or carry the last quote/board membership forward as current.

## 12. Provider lock-in controls

Provider neutrality is not achieved by naming an interface `Provider`. Require:

- a source-neutral observation envelope around the exact raw provider bytes;
- canonical chain locators and point-in-time facts decoded by our versioned protocol adapter;
- provider cursors, event IDs, parsed trades, wallet labels, candles, and latency claims retained as
  provider-scoped evidence/annotations;
- source conformance fixtures for duplicates, missing index, reordered same-slot events, reconnect,
  replay-window exhaustion, schema drift, and rate-limit response;
- a 72-hour overlap/difference report before replacing a source;
- cost counters based on measured uncompressed bytes, requests, events, and native-unit charges;
- exportable segmented blobs and ordinary tables rather than a provider-only warehouse schema;
- a recovery plan that does not depend solely on the live provider's proprietary cursor.

The provider scorecard should report:

```text
recall after finalization
false/extra or conflicting event sets
latency distribution by commitment and program
duplicate and out-of-order distance
disconnect detection and recoverable window
bytes per useful compact event
credits/SOL/USD per useful compact event
filter precision and maximum scope
rate-limit and overage behavior
contract/version churn
terms and retention constraints
```

Paid service wins only on this workload. “Geyser is faster” is not a reason to spend $499 if the
operator's selected mint becomes hot after human inspection and standard transport already lands
inside the reaction window.

## 13. Smallest capacity experiment

The experiment is a capacity and recovery characterization, not implementation authorization and
not a source purchase.

### 13.1 Preflight

1. Inventory every current provider/account, plan, renewal, remaining credits, autoscaling or
   prepaid state, funded data wallet, and existing competing workload. Disable/cap automatic
   overage before a stream test. If this cannot be done, omit the metered path.
2. Record current free disk, CPU/RAM baseline, network interface counters, and a hard local reserve.
   For this machine, provisionally keep at least **300 GiB free** and no more than half of today's
   free space in the 90-day tape forecast; Ember may choose a stricter reserve.
3. Fix the exact manifests: launch/migration; selected board route; no more than five hot mints; no
   more than 10 verified wallets; no more than 10 social scopes. A scope with no lawful/stable
   source is recorded unavailable rather than substituted.

### 13.2 Seventy-two-hour live slice

- collect the cheap census and selected Pump surface;
- promote five naturally encountered mints for bounded TTLs, including at least one watching-flat
  interval if it occurs naturally;
- route direct wallet events only if an already-authorized, capped source exists;
- compute quotes locally and sample direct/router corroboration at a low fixed rate;
- deliberately disconnect each live source once; reconnect, backfill finalized evidence where
  supported, and retain the unresolved remainder;
- record per-source events/s, bytes/s, response bytes, compression, queue depth, persist latency,
  CPU, RSS, disk growth, parser yield/failure, duplicates, out-of-order distance, gaps, credits,
  and SOL charges;
- hash and compact segments, then rebuild the projections from those segments.

No purchase is necessary. PumpPortal launch/migration is currently free. Standard/public RPC may
be used only within its bounded feasibility limits. Metered token/account data is skipped unless
the existing balance and an explicit native-unit cap are authorized; “we already funded it” is not
the cap.

### 13.3 Offline load and failure replay

Replay the captured envelopes at 1×, 5×, and a 30-second 10× burst. Inject duplicates, equal-valued
distinct events, out-of-order same-slot delivery, source conflict, parser drift, queue saturation,
disk-write failure, clock step, process crash after append but before cursor commit, and a reconnect
beyond the advertised replay window.

For S2 capacity, a generated envelope stream must match the measured **1,552 messages/s and
2.765 MB/s** mix and the observed payload-size distribution; a row generator at 1,552 tiny objects
per second is not a valid proxy. Repeating the live full firehose is unnecessary until the offline
consumer passes and a paid-byte cap is explicitly approved.

### 13.4 Passing thresholds

The selective local design passes when:

- every intentional disconnect opens a gap within two expected heartbeat/poll intervals;
- every recovery closes only evidence actually replayed/backfilled; there is no silent gap;
- P0 has zero intentional drops and every P1 omission is represented by a scoped gap;
- under normal live load, p99 ingress-to-durable latency is below one second and backlog age is
  below five seconds;
- a 30-minute 5× replay has a non-growing queue, stays below 70% total CPU and 70% memory, and does
  not push cockpit query/gesture p95 latency above 250 ms;
- after the 10× burst, backlog drains within five minutes without losing P0/P1 evidence;
- replay from immutable segments produces the same canonical digest, and cursor-crash tests repeat
  rather than skip;
- parser rejection, duplicate, conflict, sampling, and budget counters reconcile exactly to input;
- projected 90-day retained data uses no more than half the free space measured at preflight and
  preserves the hard free-space reserve;
- the measured September provider burn remains inside already-authorized quotas with automatic
  overage disabled.

These are apparatus thresholds, not trading-latency or profitability claims. Tighten them if the
smallest meaningful crackle hurdle requires fresher evidence.

## 14. Local versus managed promotion thresholds

Keep acquisition and compute local while all of the following hold:

- S0/S1 fits the live and 5× replay thresholds above;
- the machine is awake and connected for every interval the study claims to cover, or source
  backfill reliably covers the downtime;
- 90-day retention fits the disk reserve after measured compression/index overhead;
- provider quotas/caps are visible and no source requires a public callback endpoint;
- local collection does not impair ordinary cockpit use or other important work.

Promote **storage only** to an encrypted, vendor-neutral object store or removable backup when
disk runway fails but local compute/recovery still passes. This is usually the cheapest first
split; it does not require moving queries, operator notes, or control authority into the cloud.

Promote a **small managed collector** only when one of these is observed:

- scientifically necessary 24/7 coverage cannot tolerate laptop sleep, travel, or local network
  outages and the source's replay window cannot close those gaps;
- normal backlog age exceeds five seconds or the 5× queue grows after a bounded optimization;
- restart/backfill regularly exceeds one hour or overruns the provider's replay window;
- durable volume exceeds the local 90-day/free-space threshold;
- a callback-only provider or collaboration requirement makes a narrowly exposed service
  necessary;
- measured managed filtering costs less than the bytes/credits of the standard path and passes the
  same completeness test.

Consider managed Geyser only when the selective standard paths cannot meet measured coverage,
latency, filter, or cost needs—or when S2 is explicitly approved. A $499 plan does not earn itself
because 20 wallets fit more elegantly in one filter.

Do not consider a self-hosted Solana RPC/validator until sustained provider spend exceeds a fully
costed machine, colocation/network, disk replacement, monitoring, upgrades, on-call time, and
independent history path, and the project has demonstrated durable operator value. Nothing in the
pre-September slice approaches that gate.

## 15. Decision ledger

Adopt now as design constraints:

- cheap census plus explicitly leased hot scopes;
- one durable coverage/budget control plane;
- source-isolated bounded queues and one durable commit/outbox boundary;
- at-least-once acquisition, separate observation/event/blob identities, and deterministic replay;
- local quote computation and consequence-based quote retention;
- per-key wallet health and message/native-unit budgets;
- explicit sampling probabilities and degradation events;
- local-first operation with a $0 incremental pre-September target that remains the default until
  explicitly revised.

Defer until measurement:

- whole-market successful-trade census;
- WebSocket versus managed Yellowstone provider choice;
- database, queue, and segment format;
- exact compression/retention tiers;
- managed object store or collector;
- broad realtime social/LLM joins;
- any self-hosted Solana node.

Reject:

- one always-on high-resolution feed for every evidence class;
- provider-enriched trades, wallet labels, candles, or social summaries as canonical;
- a global health light, an exactly-once claim, or reconnect success as proof of coverage;
- silent load shedding or sampling the busiest intervals without disclosure;
- per-event remote quote calls when exact local state/math exists;
- paid streaming justified by unverified revenue or presumed future scale.

The likely pre-September bottleneck is not event-processing code. It is whether the selected Pump
loop can be observed faithfully, whether the selective source stays inside a visible budget, and
whether Ember naturally uses the resulting cockpit. The architecture should spend money only after
those premises survive.
