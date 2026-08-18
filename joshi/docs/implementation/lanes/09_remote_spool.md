# Lane 09 — remote acquisition spool

Status: implemented and verified locally on 2026-08-16  
Owned code: `crates/joshi-spool`, `fixtures/spool`  
Protocol contracts: `joshi.spool.segment.v1`, `joshi.spool.remote_ack.v1`,
`joshi.spool.catalog_ack.v1`

## Result

This lane lands a synchronous, host-agnostic Rust library for bounded append-only evidence
segments and resumable byte replication. It deliberately does **not** land a daemon, listener,
source adapter, semantic catalog, cursor owner, signer, transaction builder, or trading path.

The important result is not “two hosts have the data.” It is a narrower, testable statement:

> An exact, occurrence-identified segment envelope was atomically retained locally; optionally,
> those exact sealed bytes were durably reproduced at a named replica generation; optionally and
> separately, an exact evidence batch received a real post-commit catalog receipt.

Those are three different facts with three different records. None authorizes deletion.

## Authority boundary

```text
collector/adapter
  │ exact DurableIngestBatch JSON + exact store-policy bytes
  ▼
segment encoder ── one protection domain; seal private body before remote boundary
  │
  ▼
LocalSpool ready/ ── bounded chunks ──► Replica partial/ → ready/ → remote ACK
  │                                           │
  │                                           └─ exact sealed-envelope durability only
  │
  └─► normal store admission ── DurableReceipt ──► separate catalog ACK ledger
                                                    (still no deletion authority)
```

The spool can retain and replay bytes into a new catalog only through normal admission. It cannot:

- mint `CommitSeq`, accept an assertion, close a coverage gap, choose supersession, create a scene,
  or become query/read truth;
- turn a descriptive source cursor or a `CursorCandidate` into a durable cursor watermark;
- interpret HTTP success, transport completion, or a remote ACK as SQL admission;
- sign, quote, submit, rebalance, or trade; or
- delete local/remote bytes or destroy a key.

The catalog can survive spool loss from its own committed state. The spool can survive catalog loss
as replayable input, not as a second semantic database.

## Segment model

`SegmentId` is an opaque transport occurrence/container identity. It is not an observation ID,
acquisition ID, batch digest, or content hash. Two segments containing equal entry bytes under two
different IDs remain two occurrences; tests retain both.

Every segment has:

- one `SegmentId`, creation timestamp, protection domain, and protection class;
- a strictly ordered entry descriptor closure;
- a sorted, duplicate-free closure over represented source/acquisition occurrences;
- an exact plaintext-body SHA-256 digest and length;
- an exact sealed-body SHA-256 digest and length; and
- an outer exact-segment SHA-256 digest and length used by sync and ACKs.

Entry bytes are compact JSON framed by an unsigned 64-bit big-endian length. The ordered header
binds each entry's ordinal, kind, occurrence ID, exact byte digest/length, and batch closure where
applicable. Decode verifies the envelope, body, frames, entries, logical batch digest, policy bytes,
cursor-candidate copies, and recomputed source-occurrence closure. A producer cannot change a copied
cursor candidate or header batch count independently of the exact `DurableIngestBatch`.

### Exact evidence batch retention

`EvidenceBatchEntry::from_exact_bytes` checks that:

1. the exact supplied JSON decodes to the supplied `DurableIngestBatch`;
2. the batch uses `joshi.durable_ingest_batch.v1`;
3. `joshi-store` computes the supplied canonical logical `BatchDigest`; and
4. later segment decode reconstructs the same batch closure and cursor candidates.

The exact batch bytes and exact opaque policy bytes are then retained; the spool does not
reserialize them during replication or admission handoff. A convenience constructor serializes
once at this boundary and retains the result.

The batch header closure records logical digest, exact batch/policy closures, optional store
admission digest, expected counts, acquisition IDs, and gap IDs. The admission digest is supplied
by the store adapter because the spool does not own policy normalization. If it is absent, remote
replication still works, but `record_catalog_receipt` refuses to claim exact catalog admission.

### Cursor candidates

Each batch's `CursorAdvance` values are copied into a type named `CursorCandidate`. The copy retains
the exact scope, kind/value, acquisition and evidence identities, but has no commit field and no API
which advances collection state. It is descriptive/replay material only. The sole authoritative
advance remains a store-committed `CursorAdvance` backed by its atomic evidence batch.

## Protection-domain boundary

There are two explicit physical classes:

| Class | Body on disk/transport | Intended use |
|---|---|---|
| `PublicIntegrity` | plaintext plus SHA-256 closures | explicitly public fixtures/evidence only |
| `AuthenticatedPrivate` | ChaCha20-Poly1305 ciphertext and tag | private authenticated evidence before any remote boundary |

`ring` 0.17 provides ChaCha20-Poly1305. Header material through the plaintext-body closure is AEAD
associated data. Therefore the domain, segment occurrence, ordered entries, source-occurrence
closure, inner digest/length, key ID, and nonce are authenticated even though the replica cannot
decrypt the body. The remote ACK binds the exact outer ciphertext envelope, not the plaintext
digest alone.

Keys are caller-owned `KeyMaterial`; key bytes are neither serialized nor exposed through `Debug`.
Headers contain only a non-secret key ID and base64 nonce. A nonce is caller-supplied because this
library has no RNG/config authority. Reuse under the same key ID and domain is rejected in-process
and again by scanning already durable local segments, so a restart does not reset the invariant.
Key rotation is a new key ID; protection-domain retention remains independently authorized.

There is no cross-domain physical deduplication. The domain is bound into the envelope, and a
segment occurrence ID cannot be reused with a different domain/closure. Retention and deletion
records whose embedded domain differs from the physical segment domain are refused.

Private protection does not claim traffic-analysis resistance. The V1 authenticated header exposes
non-secret protocol metadata: domain/key IDs, nonce, entry kinds/occurrence IDs, batch closure, and
source/acquisition occurrence IDs. Source credentials, request secrets, wallet keys, bearer tokens,
and sensitive source locators must never be identifiers or metadata. If those occurrence IDs cannot
be made opaque/non-secret, a header-minimization or keyed-ID V2 is a deployment stop gate—not a
reason to put private evidence on an unencrypted remote filesystem.

Correctness and confidentiality do not depend on Tailscale/SSH or remote at-rest encryption.
Transport privacy remains defense in depth; replicas do not need decryption keys.

## Local durability

`LocalSpool` is a single-writer filesystem boundary with this fixed root layout:

```text
<local_spool_root>/
  staging/       reserved for caller-side assembly/recovery
  ready/         verified exact segment envelopes
  acks/          remote durability ACKs
  catalog_acks/  exact post-commit store receipt closures
  quarantine/    corrupt bytes plus reason records
```

The atomic sequence is same-directory pending-file creation, complete write, file `sync_all`,
rename to the ready/receipt name, and parent-directory `sync_all`. A deterministic `.pending` name
allows retry/restart to complete an equal write. Conflicting pending bytes fail closed. A crash after
rename is repaired by re-verification and directory fsync before returning idempotent success.

Ready filenames use hashes of the opaque segment ID plus the exact segment digest. Path components
therefore never trust caller identifiers as filesystem syntax. Same ID/same closure is idempotent;
same ID/different bytes, domain, or protection is an identity conflict.

`SpoolConfig` requires:

| Field | Meaning |
|---|---|
| `root` | exact root on one local filesystem |
| `max_segment_bytes` | outer encoded-envelope limit |
| `max_entries_per_segment` | ordered entry-count limit |
| `max_total_bytes` | total files below the root, including pending/ACK/quarantine state |
| `control_reserve_bytes` | capacity unavailable to evidence segments, reserved for pure control segments |
| `max_transfer_chunk_bytes` | maximum bytes returned by one `read_transfer_chunk` call |

Evidence admission stops before using the control reserve and returns a `Degraded` error requiring
the source owner to append a scoped `GapRecord`. The spool cannot invent the affected source,
family, subject, or trustworthy boundaries. Pure gap/retention/deletion segments may use the
reserve. Exhausting even that reserve is a visible hard failure, never silent loss.

Corruption discovered while listing, finding, or reading a ready local segment moves it to
`quarantine/`, fsyncs both directories, and writes a reason sidecar. The caller must turn the known
or unknown affected boundary into a scoped gap; quarantine does not itself close or recover one.

## Resumable replica protocol

`Replica` is also a synchronous single-writer filesystem boundary:

```text
<replica_root>/
  partial/       exact durable prefix for an in-progress closure
  ready/         completed and verified outer envelopes
  acks/          durable remote ACK records
  quarantine/    corrupt partial/ready bytes plus reasons
```

`ReplicaConfig` binds that root to a caller-supplied `replica_id` and explicit `generation`, plus
maximum segment, chunk, and total bytes. Generation is never inferred from a hostname/IP. Reusing a
host or replacing a disk requires a new generation unless the existing durable state is proven to
be the same generation.

The sender asks `resume_state` for one exact `SegmentClosure`, then requests a bounded local chunk at
the returned offset. The receiver behavior is:

- offset equal to the durable prefix: append and `sync_all`;
- offset behind the prefix: compare overlap byte-for-byte and append only an equal suffix;
- offset ahead of the prefix: refuse the gap;
- same segment ID with a different closure: refuse the conflict;
- completed bytes: verify outer digest/length, contract, ID/domain/class, and sealed-body closure;
- then rename `partial` to `ready`, fsync both directories, write/fsync/rename/fsync the ACK; and
- return the ACK only after those transitions complete.

Whole segments may arrive out of order. Chunks within one segment may be duplicated or overlap, but
cannot skip forward. A restart after partial fsync resumes at the durable prefix. A restart after
ready rename but before ACK reconstructs the ACK only after re-verifying and fsyncing ready state. A
restart after ACK-temp fsync finishes that exact pending ACK. If ready bytes later corrupt or vanish,
a historical ACK is not treated as current durability: corrupt bytes are quarantined and absence is
an integrity incident.

No network framing is part of the contract. A future process may carry `TransferChunk` over a
private SSH/Tailscale path, HTTP, removable media, or an in-process channel without changing these
semantics. An HTTP `2xx` alone can never construct `RemoteDurabilityAck`.

## Two acknowledgement ledgers

### Remote durability ACK

`RemoteDurabilityAck` binds exactly:

- protocol contract;
- replica ID and explicit generation;
- segment occurrence ID;
- protection domain/class; and
- exact outer envelope SHA-256 digest and byte length.

It means only “these exact sealed bytes are currently durable at this replica generation.” Local
recording rechecks the ACK against its own ready closure. Recording it does not dequeue, delete,
advance a cursor, claim evidence validity/coverage, or imply SQL admission.

### Catalog admission ACK

`record_catalog_receipt` accepts only the existing `joshi_store::DurableReceipt`. It finds the exact
batch closure in the retained segment and compares:

- receipt contract/schema and nonzero closed commit range;
- catalog identity/schema;
- batch ID and canonical logical digest;
- exact store admission digest;
- every logical/physical admitted count;
- exact acquisition identity set; and
- exact gap identity set.

Only after all fields agree is a separate `CatalogAdmissionAck` fsynced. Partial receipts, wrong
catalogs, mismatched counts, missing admission digests, and generic transport success fail closed.
Even this ACK does not authorize disposal.

## Gap, retention, and deletion records

The segment body supports append-only typed records:

- `GapRecord`: exact `CoverageScope`, lower/optional upper boundary, reason, detection time, and
  optional related segment;
- `RetentionRecord`: domain/segment, action/not-before time, catalog-release digest, and independent
  authorization digest; and
- `DeletionRecord`: later fact distinguishing `Requested`, `BytesDeleted`, `KeyDestroyed`, and
  `BytesDeletedAndKeyDestroyed`, tied to a retention record and evidence digest.

The library intentionally implements no deletion method. An external retention controller must
first prove catalog/reference policy closure and separately authorize a specific domain/segment.
Byte deletion and key destruction remain different append-only facts. Remote ACK is not an input to
that authorization by itself.

## Verification

The deterministic fixture corpus is `fixtures/spool/replication_schedules.json`. It drives restart,
overlapping retry, forward-gap refusal, whole-segment reorder, and duplicate delivery schedules.
Rust failpoints cover temp fsync, ready rename, replica partial fsync, replica ready rename, and ACK
temp fsync.

Local verification on 2026-08-16:

```text
cargo clippy --locked -p joshi-spool --all-targets -- -D warnings
    PASS

cargo test --locked -p joshi-spool
    15 integration tests passed; 0 failed
    doc tests passed
```

The tests specifically close:

- segment occurrence identity versus equal content;
- public and authenticated-private round trips;
- AEAD tamper rejection and absence of key bytes from the envelope;
- nonce reuse in-process and after reopening a local spool;
- pre/post-rename atomic append recovery;
- same-ID idempotency and changed-byte conflict;
- data-budget degradation with a usable control reserve;
- local and replica corruption quarantine, including distrust of a stale historical ACK;
- partial transfer, duplicate overlap, mismatch, forward-gap refusal, and restart;
- crashes after replica ready rename and ACK-temp fsync;
- whole-segment reordering and duplicate completion;
- remote ACK recording without local deletion or semantic fields; and
- exact catalog receipt success and count mismatch refusal.

## Remote-host integration and stop gates

This library has no CLI, config parser, health endpoint, graceful-shutdown process, listener, or
systemd unit. `deploy/README.md` is therefore correct to keep deployment scaffolding inert. A future
service should own exactly one `LocalSpool` or `Replica` writer, expose stable health/shutdown and
config contracts, and use the library without weakening its fsync/ACK ordering. Concurrent processes
must not write one root; cross-filesystem temp/rename, NFS/SMB roots, and shared SQLite are out.

The canonical deployment paths documented by the remote lane are:

```text
/var/lib/joshi/spool/local/
/var/lib/joshi/spool/replicas/<replica>/<generation>/
```

An explicitly approved `hbox` archive root may later be under `/tank/joshi/spool`, but it cannot be
the sole copy. Current host inventory makes all deployment conditional:

- both `persvati` and `hbox` run end-of-life Ubuntu releases and are deployment-blocked pending host
  maintenance;
- neither host demonstrated trusted at-rest encryption, so private bodies must be sealed locally;
- `hbox` has memory pressure and a nonredundant ZFS special vdev, requiring explicit archive-risk
  acceptance and a measured resource gate;
- `persvati` needs a lid/suspend/restart continuity canary; and
- Tailscale reachability is asymmetric and requires a bidirectional transfer canary, not an assumed
  listener or firewall change.

No purchase, remote mutation, service installation, credential placement, or network change was
performed by this lane.

## Deliberate V1 limitations

- Filesystem operations are synchronous and single-writer. The service/runtime boundary remains a
  later small decision; adding Tokio or HTTP here would distort the core.
- Ready/nonce lookup scans bounded directory contents instead of maintaining a second index. That is
  appropriate for the first canary; measured lookup/segment counts gate an index.
- SHA-256 is an integrity closure, not a signature. Authenticity for private bodies comes from AEAD;
  public segments need a separately authenticated transport/source if origin authenticity matters.
- Nonces and key lifecycle are caller responsibilities. A production collector needs a durable,
  reviewed nonce/key allocation policy before private live use.
- V1 header metadata is authenticated but not encrypted. Opaque/non-secret IDs are mandatory; full
  metadata confidentiality requires a protocol revision.
- Backpressure/corruption returns enough context for the owning source/service to append a scoped
  gap, but the spool does not invent coverage bounds or silently auto-close the incident.
- Retention/deletion are evidence records only. A separately reviewed reference-policy controller is
  required before any material deletion API exists.
- There is no remote collector service yet. Passing offline tests is an observability/durability
  milestone, not a claim that live acquisition continuity or revenue exists.
