# Wave 5 — authenticated-private retention controller

Status: semantic kernel delivered; physical controller and store/migration integration remain an
explicit follow-up owned by the integrator.

This semantic crate does not close the A0 gate by itself. Continuous authenticated-social capture
remains `unavailable` until a host-side controller has fault-tested origin, CAS, replica, export,
and derived-reference inventory against store-produced cut/receipt witnesses. A fixture replay or
an eligible report is not evidence that a filesystem, remote replica, export, or key manager was
actually changed.

## Boundary and capability ceiling

`joshi-retention` is a pure transition kernel. It inventories exact authenticated-private bytes
and references at five layers:

```text
origin spool -> CAS -> replica -> export -> derived reference
```

It accepts only append-only `Tombstone`, `Release`, `DeletionRequest`, and `DeletionReceipt`
occurrences. A receipt records an externally observed fact (`Requested`, `BytesDeleted`,
`KeyDestroyed`, or `BytesDeletedAndKeyDestroyed`); it never grants permission and the crate exposes
no filesystem, object-store, key-manager, or deletion-action method. Key erasure and byte absence
are independent facts. A partial/unknown replica, live export or derived reference, missing
tombstone/release, stale receipt, domain mismatch, and incomplete key scope refuse closed.

Every report contains `coverage_effect: unchanged`. Retention state cannot produce a coverage
positive, negative, gap closure, source ACK, or publication. This is the nonimpersonation boundary:
source coverage remains owned by evidence/store admissions.

`Kernel::new` is suitable for adversarial/local reasoning only and marks its inventory unverified;
every report then refuses with `unknown_inventory`. There is deliberately no public qualification
constructor: a store adapter must privately validate its exact inventory receipt and feed only a
store-owned capability into the future controller. This keeps an incomplete caller list from
becoming a deletion qualification witness.

Exact occurrence bytes are idempotent on retry; a changed body under one occurrence ID is an
identity conflict. A receipt is accepted only for a matching eligible request. This lets the host
crash after any append boundary and replay the same occurrence without manufacturing a second
fact.

## Integrator store ports (exact requests)

The store owner should add these versioned, append-only ports. They are semantic ports, not a new
authority or second registry:

1. `joshi.store.retention_inventory.v1`: read a point-in-time inventory by `domain_id` and
   `content_digest`, including every origin/CAS/replica/export/derived-reference item, exact
   `ByteFact`, dependency edges, protection-domain ID, key ID, and inventory cutoff. A missing or
   unknown row must be returned as `unknown`, never as absence.
2. `joshi.store.retention_occurrence.v1`: append/read the exact occurrence bytes and SHA-256
   occurrence digest for the four occurrence types. The unique key is `(occurrence_id,
   occurrence_digest)`; same ID with different bytes must return an identity conflict. The write
   must be atomic with its catalog commit and receipt readback.
3. `joshi.store.retention_closure.v1`: resolve tombstone, catalog release, request, and receipt
   relations transitively from persisted rows. It must return deterministic refusal codes for
   missing/unknown dependencies, outstanding exports/derived refs, partial replicas, stale
   receipts, domain mismatch, and incomplete key scope. It must not infer coverage or alter an
   evidence cursor.
4. `joshi.store.retention_receipt.v1`: read the latest exact receipt facts by request/item/domain
   and distinguish byte absence from key-erased state. A key-erased domain remains represented even
   if ciphertext rows remain; key loss cannot be rewritten as byte deletion.
5. `joshi.store.retention_coverage_fence.v1`: expose the unchanged coverage/evidence digest and
   cutoff alongside retention reports. Retention may verify that the fence is unchanged, but may
   not mint, close, revise, or supersede it.

## Migration requests

The next migration should add (without rewriting historical rows):

- `retention_inventory_item` keyed by `(domain_id, item_id)` with layer enum, content digest,
  byte-fact enum, key ID, and a separate dependency-edge table;
- `retention_occurrence` keyed by occurrence ID with contract, exact bytes, exact digest,
  occurrence kind, recorded time, and domain; and
- typed projections/indexes for tombstones, releases, requests, receipts, and domain key state.

All new enums must preserve unknown values, and all digest columns must retain their domain (exact
occurrence, content, authorization, catalog release, and evidence are not interchangeable). The
migration must fail closed on duplicate IDs, changed same-ID bytes, unknown domain/key bindings,
or dependency cycles. No migration may delete CAS/origin rows or destroy key material.

## Required fault walk

The integrator should replay `fixtures/retention/adversarial.v1.json` after crashes injected after
inventory read, occurrence append, catalog commit, and receipt readback. Expected outcomes are
identical before and after restart: partial replicas and outstanding references remain blocked;
exact retries are duplicate; stale receipts refuse; and every report says `coverage_effect:
unchanged`. A physical controller, when separately authorized, must consume an eligible report and
emit a later receipt through the store port; it must not call a method on this crate to erase bytes
or keys.
