# Wave 5 I6 — durable operational status

Status: pure adapters, bounded query models, and append-only degradation/recovery journal complete;
route mounting and store integration remain owned by the integrator.

Owned paths:

- `crates/joshi-operational-status/**`;
- `fixtures/operational-status/**`; and
- this document.

## Authority boundary

The existing bounded `OperationalHealthV1` remains the read-only health vector. The new status
projection makes the I6 distinction explicit:

```text
store/spool/publication/export owners
  -> UnverifiedDurableProgressV1 (receipt/cursor/gap/publication/export/import)
host sampler
  -> ResourceSampleV1 (CPU/RSS/FD/disk/inodes/clock)
status owner
  -> UnverifiedStatusJournal (append-only degradation/recovery)
  -> UnverifiedOperationalStatusViewV1 (bounded authenticated query projection)
```

The canonical public DTOs are explicitly `Unverified*`; compatibility aliases retain the shorter
Wave 5 names but do not change qualification. `UnverifiedDurableProgressV1` requires the exact
durable commit for every non-pending state and may carry a content digest. It does not expose a
writer, ACK constructor, cursor advancement, publication
mount, export/import operation, or readiness promotion. The store/core integrator must resolve
these IDs against its authoritative rows and reject an unknown or conflicting occurrence.
`from_store_resolved` names this query-only adapter boundary explicitly; its compatibility `new`
alias does not mint a receipt or advance an owner.

`ResourceSampleV1` is deliberately a separate type. It carries an explicit sample clock ID and
sample timestamp, but no durable commit, receipt, cursor, gap, or publication relation. A CPU/RSS/
FD/disk/clock reading therefore cannot silently become durable truth. The sample's status is an
observation, not a readiness authority.

The pure `DurableProgressV1::new` and `ResourceSampleV1::new` adapters fix their contract headers
and read-only boundary, then validate before returning. Pending progress cannot carry a commit or
digest; cursor/gap progress must name a source. The resource constructor accepts only the explicit
sample clock and does not accept an authority or commit argument.

## Append-only degradation and recovery

`StatusJournal` reconstructs exact records after restart and refuses:

- ordinal gaps, changed predecessor links, duplicate IDs, or stale record clocks;
- recovery without one prior degradation record in the same append history;
- duplicate recovery of one degradation occurrence;
- a `recovered` transition without a durable evidence-progress ID; and
- empty/unsorted degradation causes or mixed source/scope closure.

Recovery says that an operational state was verified; it does not close a source coverage gap.
The named evidence progress must separately be committed by the store/source owner. A PumpPortal
live-only gap remains open even when its connection recovers.

`UnverifiedOperationalStatusViewV1` joins durable progress, sampled resources, and the transition
journal for bounded readback. It validates each component independently and rejects duplicate/conflicting
durable occurrences. It never computes receipt, cursor, publication, export, import, or readiness
authority from a sample or metric. Its qualification is always `unverified`; there is no public
promotion or verified-journal capability. Views are bounded and canonical by durable occurrence ID; a
recovery evidence ID must resolve to one of the durable progress rows in that view. Resource rows
are unique sample occurrences and may not be sampled after the view's observation clock. Recovery
evidence must match transition scope/source, precede the recovery clock, and be a committed/closed
receipt, cursor, publication, export, or import; an open gap cannot prove recovery. Journal recovery
records are terminal (`unverified_semantic` or `blocked_unrecoverable`) so intermediate state cannot
consume the one closure slot. The legacy `recovered` state is not accepted by the public journal.

## Integration requests

The store/core integrator should provide a narrow read-only adapter that:

1. reads the exact latest durable receipt/cursor/gap/publication/export/import rows by occurrence
   and commit sequence;
2. supplies the already committed content digest and source/scope IDs without reserializing source
   bytes;
3. supplies append-only degradation/recovery records after its own durable commit;
4. supplies host samples as typed observations with a sample clock ID; and
5. binds query responses to the authenticated same-origin route and the caller's requested page.

This crate requests shared occurrence, run, catalog commit, and artifact IDs from store/supervisor/
publication owners; it creates no parallel identity authority. Health/status adapters must not write
SQLite, call a provider, ACK a spool, advance a cursor, mount publication, import artifacts, or
promote readiness.

The authenticated query seam is represented by `OperationalStatusQueryV1` and
`OperationalStatusQueryResultV1`. `decode_query_result_v1` enforces the requested page size, the
read-only result authority, nested durable-detail validation, and a 4 MiB response ceiling. Query
targets are exact IDs/scopes or a finite source-family/health target; free-text and log search are
not representable. `decode_query_result_for_query_v1` additionally binds the result to the exact
query occurrence ID and target. Resource samples reject a `ready` status when their configured
ceiling/floor is breached; quarantine details require a tagged SHA-256 content digest.

## Fixtures and validation

`fixtures/operational-status/status_view_durable_and_sampled.json` contains receipt, gap, and
publication progress alongside CPU/disk samples, proving that resource observations remain outside
the durable commit domain. Existing degraded-health and queue-fault fixtures continue to exercise
finite metrics, pressure, restart closure, and source-specific backfill semantics.

Focused tests additionally cover constructor authority fixing, pending-progress refusal, result
page/authority bounds, canonical durable ordering, and recovery evidence resolution.

```sh
cargo fmt -p joshi-operational-status -- --check
cargo test -p joshi-operational-status --all-targets
cargo clippy -p joshi-operational-status --all-targets -- -D warnings
cargo doc -p joshi-operational-status --no-deps
```
