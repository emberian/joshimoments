# W4-01 — always-on supervisor and durable spool transport

Status: implemented offline continuity path; no live provider, remote host, listener, deployment,
purchase, wallet authority, transaction construction, signing, submission, or economic action.

Owned paths:

- `apps/collector`;
- `crates/joshi-supervisor`;
- `fixtures/supervisor`; and
- this document.

Shared ACK DTOs are owned by W4-00 in `joshi-admission::operational`; spool byte semantics remain
owned by `joshi-spool`. This lane does not add another receipt, cursor, catalog, or truth contract.

## Walking path

```text
source driver
  -> Supervisor::reserve + fsync journal
  -> one reviewed read / connection generation / poll / control write
  -> source-owned exact adapter
  -> PendingSegment owns exact DurableIngestBatch + exact policy bytes
  -> record-count and byte-count bounded queue
  -> encode and (for private evidence) AEAD-seal one-domain segment
  -> LocalSpool::append_segment fsync/rename
  -> shared LocalSpoolReceiptV1
  -> release in-memory queue ownership
  -> optional transport-neutral ciphertext replication
  -> optional no-listener catalog drain returning exact DurableReceipt
  -> LocalSpool::record_catalog_receipt
  -> shared SpoolCatalogReceiptV1
  -> retain the exact local segment
```

No step in the collector can advance a catalog cursor. Descriptive cursor candidates may remain in
the retained `DurableIngestBatch`; only the catalog writer can commit `CursorAdvance`. Local spool,
remote replica, catalog, and retention remain four different facts.

## Durable identity and generations

The first open creates `<root>/identity/installation.json`, then keeps an OS file lock on
`supervisor.lock`. Each event is a separate strict JSON file under `journal/events/` with a
20-digit ordinal. Writes use create-new temporary file, file fsync, rename, and directory fsync.
Startup promotes a fully written pending journal file before replay and refuses ordinal gaps,
conflicts, unknown fields, wrong contracts, or wrong authority.

`Supervisor::reserve` returns only after `AttemptReserved` is durable. The returned identity binds:

- installation, source key, and operation key;
- generation and attempt ordinal;
- HTTP request, WebSocket connection, poll, or control-write kind;
- exact coverage scope and last trustworthy lower boundary;
- public/private protection domain and non-secret key ID;
- reservation wall clock; and
- literal authority `read_only_no_execution`.

WebSocket connections and polls start a new monotonically increasing durable generation. HTTP and
control attempts remain in their current generation. `reserve_retry` preserves the generation and
requires the prior attempt to have become locally durable or an explicit gap. Retry policy is
project-owned, deterministic exponential backoff with a hard attempt/delay ceiling. A provider
`Retry-After` longer than the ceiling exhausts the retry instead of waiting less than requested.
No transport library retry is hidden beneath it.

After a process crash, every pending reservation is reconciled before source restart:

1. if its deterministic segment ID already exists and verifies as evidence, journal an idempotent
   local-durability transition;
2. if it verifies as a gap, journal the already durable abandoned-attempt result; or
3. otherwise consume protected control reserve to append an `abandoned_attempt_after_restart` gap.

The gap consumes that attempt's deterministic segment ID. A late response cannot subsequently
reuse the occurrence identity with different bytes.

## Queue and pressure contract

The single-writer queue owns each payload until the shared local spool receipt validates. The
default S0 bounds are:

| Class | Records | Bytes | Behavior at bound |
| --- | ---: | ---: | --- |
| evidence | 4,096 | 64 MiB | return the exact item; stop its generation; append a scoped gap |
| protected control reserve | 128 | 1 MiB | reserved for gaps/shutdown; never consumed by evidence |
| total | 4,224 | 65 MiB | refuse rather than allocate without bound |

Both limits apply simultaneously. A single oversized item is returned unchanged. `stop_saturated`
releases it only after the gap and `GenerationStopped` record are durable. Spool/disk policy uses
the same fail-closed shape through `stop_front_for_pressure`.

The collector configuration also enforces the Wave 4 **1 GiB per UTC day** evidence-segment cap.
The calculation uses verified segment creation clocks and exact outer-envelope lengths. Same-byte
idempotent retries do not consume the cap twice. Control/gap segments may use the separately bounded
spool reserve so the cap itself cannot erase the fact that capture stopped. The local spool retains
its independent total-root and free-space bounds.

## Exact transport adapters

`SourceOutputAdapter` is the typed source seam. It receives the already durable reservation plus the
owned `joshi_sources::SourceOutput` and must either produce one exact `PendingSegment` or refuse.
The supervisor does not invent provider event IDs, event time, finality, coverage, or cursor
meaning. The checked-in fake provider uses this same seam.

`prepare_evidence_batch` is the common seam for source adapters that already own a canonical
`DurableIngestBatch`: ordinary source output, direct Pump acquisition envelopes, paired companion
batches, and wallet-source output. It requires:

- the typed batch and its exact supplied bytes;
- exact opaque store-policy bytes and policy contract;
- the distinct store admission digest; and
- a prior durable reservation.

It refuses a noncanonical batch or digest mismatch. The supervisor does not recompute a private
store policy or treat a source-ingress digest as the store admission digest.

Private segments use the existing ChaCha20-Poly1305 spool envelope. The journal stores only a key
ID. The nonce is deterministically derived from installation, unique deterministic segment ID,
domain, and key ID; segment IDs never repeat within an installation, and `LocalSpool` independently
rejects durable nonce reuse. Encryption/authentication occurs before any replica adapter sees the
bytes.

`ReplicaTransport` is an in-process adapter over the transport-neutral resumable protocol. It
resumes exact byte offsets, records only the replica's exact generation-bound ciphertext receipt,
and never deletes local bytes. It opens no socket and is not a deployment service.

`CatalogTransport` decodes verified segments, gives each exact batch/policy closure to a
`CatalogSink`, requires the real post-commit `DurableReceipt`, asks the spool to match it against
batch/digest/policy/count/acquisition/gap/commit closure, and then returns the shared strict
`SpoolCatalogReceiptV1`. Generic HTTP success cannot satisfy the trait. Control records remain
retained. Retrying re-admits exact bytes idempotently. There is deliberately no deletion method.

## Shutdown

`shutdown` follows one bounded protocol:

1. append `ShutdownStarted` and stop accepting reservations;
2. drain queued records through local durability;
3. reconcile every pending attempt to exact bytes or a gap;
4. append one open `source_downtime_shutdown` gap and `GenerationStopped` record for each active
   source/operation generation;
5. append `ShutdownCompleted`, including drained/gap counts and whether the deadline was exceeded;
6. fsync the final health snapshot.

Deadline exceedance is recorded; it does not convert an incomplete transition to success. Restart
replays the same journal and deterministic segment identities.

## Health

`health/snapshot.json` is an atomic local snapshot, not an endpoint and not evidence authority. It
contains:

- installation and lifecycle;
- last journal ordinal;
- record/byte queue occupancy, maxima, and protected reserves;
- spool used/max/reserve/degraded state and verified ready-segment count;
- local remote-ACK and catalog-ACK file counts;
- abandoned attempt, saturation stop, and quarantine counts; and
- bounded per-source/operation generation, pending reservation, retry, and stopped state.

The shared W4-10 operational-status layer owns exported finite-cardinality metric families. Subject,
mint, wallet, URL, error text, and credentials are not metric labels. Backlog-drain qualification
must use a named fixed recovery interval with nonzero starting backlog; lifetime counters cannot
manufacture the `>=2x` recovery claim.

## Collector CLI

W4-01 exposes exactly three offline commands:

```text
joshi-collector replay --root <collector-root> [--private-key-file <owner-only-path>]
joshi-collector fake-provider --root <collector-root> --fixture <path> --hours <1..24> [--realtime]
joshi-collector health --root <collector-root>
```

There is no `run`, provider endpoint, source credential option, listener, readiness HTTP route,
daemon/service unit, remote host, or runtime mutation config. W4-09 correctly renders collector
deployment blocked until a separately authorized live-run/config/shutdown interface exists.

Replay with no key verifies every exact public segment and every private ciphertext closure; a
private segment remains visibly opaque. The optional argument contains a path, not bytes. On Unix
the file must be a regular owner-only file and contain exactly 32 raw bytes for the single key ID
already named by spool metadata. Read bytes are zeroized immediately after constructing the
in-memory protector. No test or fixture contains a production key.

The root layout is:

```text
<collector-root>/
  identity/{installation.json,supervisor.lock}
  journal/events/
  spool/{staging,ready,acks,catalog_acks,quarantine}/
  health/snapshot.json
```

## Offline gate

The accelerated fixture covers a full virtual 24 hours with exact frames every hour,
duplicate content under distinct occurrence IDs, deterministic retryable failures, connection
generations, gaps, shutdown, and byte-identical repeat replay. `--realtime` runs the identical state
machine with wall-clock pacing.

The process-kill suite starts the real helper binary and sends an OS kill after:

- durable reservation before I/O;
- in-memory bounded enqueue before spool append; and
- complete local spool durability.

The first two restart as one explicit gap each; the third restarts as the exact evidence batch with
no manufactured gap. Named failpoints cover journal temp fsync, journal rename, local spool append
before journal progress, and health temp fsync. Existing spool tests cover segment temp/rename,
replica partial/ready/ACK transitions, reordering, duplicate chunks, overlap, nonce reuse, and
corruption quarantine.

The lane gate is:

```sh
cargo test --locked -p joshi-supervisor
cargo clippy --locked -p joshi-supervisor -p joshi-collector --all-targets -- -D warnings
cargo run --locked -p joshi-collector -- fake-provider \
  --root "$(mktemp -d)" \
  --fixture fixtures/supervisor/fake_provider_24h.json \
  --hours 24
```

Passing this gate proves the local no-network continuity code and its failure accounting. It does
not prove a provider can run for 24 hours, a host is deployable, catalog lag meets S0, remote
resilience, Pump parity, market completeness, usefulness, or profit. Those claims require their
separate Wave 4 gates.
