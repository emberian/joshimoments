# Lane 22 — Wave 4 operational status, pressure, backfill, and recovery

Status: implemented pure substrate and offline fixtures; no route mount, store mutation, live
backfill, provider call, remote action, wallet capability, or economic execution.

## Outcome

This lane adds [`joshi-operational-status`](../../../crates/joshi-operational-status) as the shared
read-only vocabulary for Wave 4 operational state. It turns “healthy” into a bounded readiness
vector, keeps metrics finite-cardinality, makes degradation/recovery deterministic, and represents
backfill as a plan plus independently durable result rather than a hidden network retry.

The crate is deliberately pure:

- it has no provider client, HTTP server, database handle, logger integration, transaction type,
  wallet material, or signer dependency;
- status is derived from supplied durable receipts and exact counters, never logs;
- a status observation cannot advance a source cursor or close an evidence gap;
- a backfill plan has no `run` method; and
- every public snapshot/backfill/query artifact carries `read_only_no_execution`.

Owned paths are only:

```text
crates/joshi-operational-status/
fixtures/operational-status/
docs/implementation/lanes/22_wave4_operational_status.md
```

No root manifest, schema, migration, store, core route, source adapter, supervisor, projection,
Glass, export, analysis, or execution path was edited by this lane.

## Contract inventory

| Contract | Purpose | Authority |
| --- | --- | --- |
| `joshi.operational.health/v1` | complete bounded operational readiness vector | read only |
| `joshi.operational.metrics/v1` | fixed-enum metric samples derived from health | diagnostic only |
| `joshi.operational.status_query/v1` | exact durable-ID/scope GET query with bounded cursor pagination | read only |
| `joshi.operational.status_query_result/v1` | at most 100 strict detail rows, 4 MiB transport ceiling | read only |
| `joshi.operational.degradation_policy/v1` | ordered pressure thresholds and drain target | proposal/control policy only |
| `joshi.operational.backfill_plan/v1` | bounded offline plan with no I/O method | proposal only |
| `joshi.operational.backfill_result/v1` | imported durable proof or typed failure/unrecoverability | evidence reference only |
| `joshi.operational.fault_scenario/v1` | deterministic no-I/O fault and recovery harness | fixture only |

Every DTO uses `deny_unknown_fields`, canonical decimal-string integers through `WireU64`, exact
microsecond UTC, stable bounded identities, and closed enums at metric dimensions. Public structs
use camel-case fields; tagged variants use snake-case discriminators.

## Readiness vector

`OperationalHealthV1` models the W4-10 surface directly:

- supervisor phase, restart count, shutdown-deadline failures, last reservation age, and pending
  reservation count;
- one sorted source-family row containing the current durable generation as a **value**, source
  lifecycle, last reservation and locally durable frame ages, retries, and next retry delay;
- record and byte queue occupancy, maxima, and protected control reserves;
- saturation closure: incident count, exact rejected-occurrence preservation, durable scoped gap,
  and restart permission;
- local spool ready segments/bytes/oldest age plus total/max/control-reserve bytes;
- optional replica generation, unacknowledged bytes/age, and ACK lag;
- catalog unacknowledged segments/batches/bytes/oldest age and last exact receipt age;
- exact V1 catalog receipt summary: catalog/schema/commit range, batch/digests/status, and bounded
  sorted gap outcome IDs;
- sorted cursor scopes and open gaps with opaque durable IDs, finite source/gap classes, clocked
  boundaries, recoverability, and recovery state;
- normalizer drift count and finite quarantine-class counts;
- projection, Glass presentation, Glass command capture, export, and analysis artifact ages;
- CPU/RSS/FD/disk/inode/clock-offset observations and configured ceilings/floors; and
- request/page/byte/credit/native-unit/currency/spool/hot-scope budgets with exact authorized,
  used, and remaining quantities.

Zero authorization is valid. For example, PumpPortal native-unit spend can be represented as exact
zero with `refused`, not omitted and not treated as infinite free capacity.

The validator rejects:

- the wrong contract or authority;
- excessive, duplicate, or noncanonical source/scope/gap/resource/budget/artifact rows;
- cursor values without a catalog commit;
- artifact occurrence without content digest or vice versa;
- queue/spool values outside capacity;
- a spool degraded flag inconsistent with the protected control-reserve boundary;
- budget `remaining != authorized - used`;
- a catalog ACK inferred without one exact validated V1 receipt closure; and
- restart after saturation unless the rejected occurrence is retained and a durable scoped gap is
  already recorded.

## Finite-cardinality metrics

`MetricBatchV1::from_health` emits only closed dimensions:

```text
metric name
component
optional source family
optional finite status/resource/budget/artifact/gap/quarantine class
exact integer value and finite unit
```

There is no string label slot. In particular, metrics cannot contain:

- source key or operation key;
- generation ID (generation sequence is the gauge value);
- mint, wallet, pool, position, route, URL, endpoint, or page cursor;
- error text, exception type, HTTP body, social text, or credential;
- gap, quarantine, receipt, scene, publication, export, or model occurrence ID.

The current vocabulary covers supervisor lifecycle; source generation/reservation/frame/retry;
record and byte queue limits/reserves/saturation; spool backlog/capacity/degraded state; replica and
catalog backlog/lag; open gap and quarantine/drift counts; artifact age; resources and remaining
budgets.

Recovery arrival/drain/backlog records and bytes are emitted only through
`from_health_and_recovery` with one named fixed interval and its drain target. Lifetime counters
cannot be used to claim the Wave 4 `>=2x admitted arrival` drain gate.

Detailed subject diagnostics use the authenticated query instead. The query supports exact health,
source-family generation, cursor-scope ID, gap ID, quarantine ID, backfill plan/result ID, artifact
kind+occurrence ID, or catalog batch ID. There is no free-text search. Core integration must be
same-origin authenticated and GET-only, with at most 100 rows/page and 4 MiB response, as agreed
with the W4-00/infra lane. This lane mounts no route.

## Backpressure and declared degradation

`evaluate_degradation` is a pure decision over a validated health snapshot and a versioned policy.
Thresholds are strictly ordered in parts per million:

```text
full fidelity
 -> optional media/private exact bodies disabled
 -> social/profile refresh slowed
 -> least-recently-justified hot scopes reduced
 -> compact census only
 -> stop new evidence before the control reserve
```

It computes pressure independently for queue records, queue bytes, spool usable bytes, and exact
budgets, then selects the highest required stage. Disk/inode floors, active saturation, and refused
hard resources force `stop_before_control_reserve`. The returned decision contains finite causes
and cannot itself mutate the collector.

The queue semantic agreed with the supervisor lane is stricter than a dropped counter:

1. saturation occurs when either record or byte evidence capacity is exhausted;
2. the source generation stops and the saturation incident increments once;
3. the exact rejected item remains owned/preserved;
4. a scoped saturation gap must become locally durable through the control reserve; and
5. only then can a later verified recovery permit a new generation.

The health adapter must map the supervisor's record and byte queues separately. A low record count
cannot hide a byte-saturated body and a low byte count cannot hide record exhaustion.

## Drain and recovery

`RecoveryDrainWindowV1` names one positive wall interval and exact:

```text
backlog at start + newly admitted arrival - durably drained = backlog at end
```

for both records and bytes. Overflow, drain beyond available work, and an inconsistent ending
backlog refuse. The ratio gate is checked only when the declared starting backlog is nonzero. Zero
new arrivals pass only when positive backlog was actually drained; an empty healthy lifetime does
not manufacture infinite drain capacity.

Meeting the drain rate changes operational recovery from `draining` to `verifying` only when the
backlog reaches zero. It does not close any evidence gap. A separate committed recovery record with
its evidence is still required.

## Backfill and evidence recovery

Backfill has three distinct meanings:

1. **Same-source bounded history.** Helius WS/public-wallet gaps may propose bounded Helius HTTP
   acquisition. A paginated source with real historical support may propose bounded same-source
   pagination.
2. **Cross-source reconstruction.** Another named source and reconstruction contract may append
   evidence about an interval. It never changes the original source's coverage.
3. **Unrecoverable.** A live-only or unsupported interval remains an open gap.

A plan fixes source, immutable gap, boundaries, strategy, request/page/byte/provider-credit limits,
deadline, policy, and authority. Positive work requires positive request, page, byte, and deadline
bounds. An unrecoverable declaration reserves zero provider work.

`BackfillResultV1::Recovered` or `Partial` requires all of:

- exact validated catalog receipt closure for the recovered evidence;
- nonempty sorted bounded acquisition and observation IDs;
- a separate append-only recovery record and catalog commit no earlier than the evidence commit;
- a typed recovered boundary; and
- the original gap/result/plan/source identities.

An empty later page, reconnect, zero error count, log line, or apparently continuous chart is not a
recovery proof.

### PumpPortal rule

PumpPortal WebSocket history is live-only. The planner refuses same-source pagination or same-source
recovery for its gaps. It permits only:

- `DeclareUnrecoverable`, leaving the live-only gap explicit; or
- `CrossSourceReconstruction`, using another named source and contract.

The cross-source result must carry `originalGapRemainsOpen = true`. It may establish useful
separate evidence but cannot turn the PumpPortal cursor green or claim PumpPortal coverage.

Product/Pump pagination gaps obey the same proof boundary: a later empty page does not close an
earlier scoped gap. Only exact recovered occurrences and the committed recovery record do.

## Receipt and route integration seam

The W4-00/infra contract review supplied these authoritative receipt families in
`joshi_admission::operational`:

- `LocalSpoolReceiptV1` / `joshi.spool.local_ack`;
- `SpoolCatalogReceiptV1` / `joshi.spool.catalog_admission_receipt`;
- `ProjectionPublicationReceiptV1`;
- `CockpitPublicationReceiptV1`;
- `PresentationSceneReceiptV1` and `PresentationEventReceiptV1`;
- `ExportValidationReceiptV1`; and
- `AnalysisArtifactImportReceiptV1`.

The future adapter should accept those already validated DTOs and project their exact occurrence,
digest, commit, and receipt time into this crate's summaries. It must not reconstruct ACK status
from file presence, lag, metrics, log text, or an HTTP 2xx. `CatalogReceiptSummaryV1` mirrors the
public V1 catalog/schema/from/through/commit/batch/digest/status/gap closure so the adapter is
loss-checkable without making this shared crate depend on store/core.

No status endpoint should be mounted until the typed store query exists. The agreed transport is a
same-origin paired GET, exact durable ID/scope selection, cursor pagination, and at most 4 MiB per
response. Any future mutation receipt remains a different endpoint and keeps the existing 128 KiB
body / 64 KiB receipt ceilings.

## Fault harness

The no-I/O harness supports the required finite fault matrix:

| Fault | Required visible behavior |
| --- | --- |
| source disconnect, 429, auth rejection | degraded source, scoped gap, no false cursor |
| malformed data or schema drift | retained gap plus quarantine; no trusted normalized fact |
| record or byte queue full | stop before control reserve; rejected occurrence retained by adapter |
| disk pressure | not ready; stop new evidence before disk/control floor |
| Mac/core unavailable | collector backlog remains explicit; no catalog-as-of inference |
| replica unavailable/corrupt | local operation may continue; off-site claim degrades; corrupt bytes quarantine |
| projection failure | prior complete publication may be served explicitly stale |
| browser disconnect | presentation is not witnessed merely because it was planned |
| clock step | freshness/order claims refuse or verify; no wall-clock rewrite |

`fault_queue_recovery.json` exercises saturation → durable backlog → clear → two exact recovery
windows → verification. A test enumerates every fault class. The harness never has a field through
which logs can become evidence; `logsUsedAsEvidence` must remain false in every state/report.

Fault fixtures test state/control semantics only. They cannot satisfy the Wave 4 non-fixture
prospective source or 24-hour canary gates.

## Verification

Focused commands:

```bash
cargo fmt -p joshi-operational-status -- --check
cargo test -p joshi-operational-status --locked
cargo clippy -p joshi-operational-status --all-targets --locked -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc -p joshi-operational-status --no-deps --locked
```

Adversarial tests cover unknown JSON fields, page bounds, sensitive/open-cardinality metric
absence, saturation restart without gap closure, record/byte and disk pressure, exact drain
conservation, every required fault, PumpPortal same-source refusal, valid cross-source
reconstruction, and the rule that cross-source evidence cannot close the original gap.

At implementation time the workspace was under concurrent Wave 4 construction. Any unrelated
workspace dependency cycle or missing in-progress module is reported separately; it does not
authorize edits outside the owned paths.

## Remaining integration work

- Map `joshi-supervisor::SupervisorHealthV1` and spool/replica state into the fixed source/queue/
  spool vocabulary, including generation-as-value and per-window drain counters.
- Map only validated `joshi_admission::operational` receipts into catalog and artifact ages.
- Back the exact durable-ID query with typed store methods before core mounts it.
- Persist degradation decisions and recovery records through the single writer; the pure evaluator
  does not make them durable.
- Run the 24-hour fake-provider and process-kill canary, then separately authorized real source
  canaries. Fixtures prove contracts, not continuous operation.

These are explicit adapter/integration tasks, not hidden omissions in the status crate.
