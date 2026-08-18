# W4-00 integration handoff

Status: **useful partial; not an operational-exocortex witness**.

`scripts/wave4-readiness` is the single root gate and witness producer. It runs the existing fully
offline workspace, schema, Glass, companion, analysis, dependency-authority, and durable component
walk, then writes `wave4-witness.json`. The witness is intentionally capped at `useful_partial` and
names every still-open qualification. A fixture, green test, or manually assembled JSON cannot set
the status to complete.

## Closed shared boundaries

- Root Cargo includes `apps/collector` and all first-party crates; the lock is root-owned and
  resolves the Wave 4 graph without the former store/export/publication/projection cycle.
- SQLite V8 adds append-only structural homes for source-fact artifacts, projection and cockpit
  publications, presentation evidence, export validation, derived-artifact import, spool/catalog
  closure, protocol/launch preregistration, and mutually exclusive prospective choice evidence.
  V8 additionally preserves `exportRequestId -> snapshotId` and
  `importId -> analysisRunId -> artifactId` as distinct occurrence/content identities and registers
  immutable derived-artifact parts for verified readback after restart.
- The shared admission crate has strict, bounded, duplicate-key-aware camelCase receipts for local
  spool ACK, spool-to-catalog closure, publication, presentation, export, artifact import, and source
  facts. Semantic/result digests are never equated with exact serialized-byte digests.
- Protocol definition/revision is distinct from a fresh protocol-registration occurrence; launch
  has a fresh prospective-session occurrence. Frozen timing is: D 30--90 minutes and minute-aligned,
  warmup 300 seconds, choice `floor(3D/5)`, outcome `D+1800s`, knowledge `outcome+900s`.
- Launch preregisters both choice branches, never a prechosen nullable command:
  `joshi.operator.prospective_nomination` and `joshi.operator.explicit_abstention`. It reserves one
  command occurrence/idempotency key consumed by exactly one branch, plus distinct hot-decision,
  hot-intent, outcome, interview, export-request, analysis-run, and artifact-import occurrences.
  Export request is not the later content-derived snapshot ID; analysis run is not the later
  content-derived artifact ID.
- The no-index session envelope contains exact protocol + protocol receipt + launch + launch
  receipt. Launch contains the exact server-resolved, sorted choice-member rows; clients echo a
  `{subjectId, choiceUniverseDigest, membershipDigest}` row and never synthesize membership.
- Exact Rust prospective-nomination request and receipt vectors live in
  `crates/joshi-admission/src/operational.rs`. Their byte digests are respectively
  `sha256:e1826827d4b2629b88e9b51af1d84cc3afffeb7bb07e7a756a758894556a320e` and
  `sha256:7dd5ce90b1a5ae882f81570c0b7adae5d9216302365616b5e1110a66b85b96a3`.
- Exact protocol-registration bytes now cross a private semantic admission capability, append
  atomically to `episode_protocol_v1`, return a post-commit receipt, retry idempotently, and are
  digest-verified on readback after restart. This closes protocol registration only; it does not
  imply launch, pairing, or choice admission.
- Production Snapshot V2 validation can now atomically register its export-request occurrence,
  content-derived snapshot, exact manifest, fourteen immutable Parquet parts, validator receipts,
  publication closure, and truth fingerprint. A derived V2 artifact can then register a distinct
  import/run/content identity, immutable part metadata, and exact truth-preservation closure; its
  part is digest/length-verified on readback after restart. The tested walk remains fixture-backed,
  so it is a component gate rather than an operational witness.
- Core mounts the final prospective paths but fails closed with 503 after strict parsing/pairing:
  `GET /api/v1/session/launch`, `POST /api/v1/operator/prospective-nominations`, and
  `POST /api/v1/operator/abstentions`. They cannot emit an ACK until the private semantic store
  adapter below exists.

## Deliberately open P0 joins

- Several V7-era tables remain structural. There is not yet a private adapter that parses exact publication,
  launch, presentation, and choice-universe bytes and resolves every reference
  from persisted rows before constructing a capability. Export/import and protocol registration
  now have narrow typed adapters, but public low-level publication capability constructors must not
  be confused with a complete semantic publication boundary.
- Projection checkpoint + publication commit, cockpit publication append/readback, production
  store-to-Parquet validation registration, and analysis artifact import are not one continuous,
  non-fixture durable root walk yet.
- Launch/nomination/abstention store methods are not mounted. The writer must derive source
  receipts and choice membership from store state, bind the paired client session to the launch,
  reject commit at or after the choice deadline, and enforce cross-table one-branch consumption.
- Session-close, outcome-at-H, knowledge-by-K, and interview-disposition DTOs are now frozen in
  `joshi-episode-closure`, but store tables, semantic writers, root-owned post-commit receipts, and
  routes do not exist. Arbitrary contract strings or DTO validation alone cannot qualify or export
  an episode.
- Wallet topology/history can use `SourceFactFamily::WalletTopology`, but there is no typed
  W4-04-to-store registration/readback adapter across restart yet. A W4-04 fixture receipt therefore
  does not qualify as circulation.
- Source-fact commits currently use the catalog `projection` commit class because the V1 commit
  class domain names all deterministic read-only evidence reductions “projection.” This naming is
  lossless only if kept explicit in public receipts; a future migration may add a narrower class.
- Continuous non-fixture source supervision, durable publication selection, same-origin
  launch-bound pairing, remote repair/deployment, and live operational status readback remain open.
- Prospective qualification requires protocol commit first, post-protocol launch support, launch
  commit before T0/reveal, and at least one non-fixture source occurrence in `[T0,T_end)`. No such
  live run occurred. No Ember choice episode occurred. All-abstention runs can demonstrate
  instrumentation but cannot elevate the root status above `useful_partial`.

No code in this lane starts a source, reads a secret, deploys, constructs/signs/submits a
transaction, or claims economic authority.
