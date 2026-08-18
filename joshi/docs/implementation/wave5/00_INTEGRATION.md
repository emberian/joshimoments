# Wave 5 integration — Living Instrument authority spine

Status: **implementation in progress / useful partial**. No full Phase-0 fault walk, live,
product-parity, complete publication, nonempty V10 export/import, repeated-use, or remote qualification is claimed by
this document. The runnable Wave 5 readiness target now closes registration plus one public C0
origin-segment/store-receipt/catalog-binding/ACK/reopen component walk; it must not be promoted
beyond the explicit closed boundaries and open joins below.

## Sole authority sequence

The Phase-0 operational order is:

```text
exact build + source tree + config + budget + privacy + DailyUseSurfaceProfile
  -> strict semantic parse and exact byte closure
  -> sole SQLite writer registers the run and returns a durable receipt
  -> collector/runtime consumes the store-readback-bound run only
  -> sealed segment + exact physical policy + exact logical batch
  -> sole SQLite ingest transaction and structural DurableReceipt
  -> store rederives exact public receipt counts/gaps/protection from durable truth
  -> durable SpoolCatalogReceipt binding
  -> collector may fsync catalog ACK (never deletion authority)
  -> private store-resolved semantic publication/export/import/status adapters
```

Registration is not a bag of digests. `joshi-admission::wave5` owns finite public component wire
contracts; the store independently parses the same exact bytes before persistence because the
existing admission/store dependency direction prevents an admission DTO from serving as an opaque
store capability. The build manifest closes the exact source-tree document; configuration is
currently `offline_fixture_only`; budgets are finite and positive; privacy forbids wallet material
and private export; and the surface profile is validated through `joshi-surface`. A dirty or unborn
tree can support a named foreground local canary, never an immutable remote release claim.
The registered configuration closes a domain-separated `planTemplateDigest` over the exact
source/method/operation/budget-relevant plan body with run fields omitted, avoiding a digest cycle.
The final provider plan must match that template and bind the durable run receipt; each attempt then
binds the full run reference and final plan digest.

## Implemented foundation

- Migration `0009_wave5_living_instrument.sql` adds append-only run, spool/catalog-binding,
  operational-record, export-binding, and restricted-import closure tables. Fresh catalogs identify
  themselves as V9; historical V8 stores retain their exact V8 identity.
- Run-registration contracts retain all seven exact byte strings and reject unknown/noncanonical
  component contracts, digest-closed junk, cross-tree build substitution, unbounded budgets,
  privacy widening, and invalid daily-use profiles.
- The store owns commit time creation; callers supply occurrence/build identity but cannot supply a
  backdated store wall or monotonic clock. Persisted global wall time and same-clock monotonic time
  are checked across reopen.
- Public-integrity spool admission reconstructs the exact serialized entry from the sealed segment,
  logical batch, canonical Pump physical policy, cursors, and durable rows at or before the receipt
  cutoff. The immutable origin segment contains no postcommit admission digest; only the exact
  store receipt, run-bound catalog binding and separately fsynced catalog ACK bind that later
  digest. Crash/retry preserves the origin bytes. Authenticated-private segments fail closed until
  the store can verify their AEAD tag and reconstructed plaintext; byte-length resemblance is not
  admission.
- Operational recovery cannot self-author an initial ready/recovering/stopped state. Verified
  recovery requires the exact latest predecessor plus later same-run, component-resolved durable
  evidence; the current finite evidence resolvers are spool and export, and unsupported components
  refuse promotion.
- Restricted import accepts only `joshi.analysis.derived-artifact/v2`. Store-owned cutoff checks
  enforce maximum-input <= fit <= commit, while `joshi-artifact-admission` reads the exact resolved
  CAS bytes once and verifies their physical digest, Arrow schema, row count, logical relation, and
  support before commit and again after reopen.
- `joshi-operational-status` now separates durable receipt/cursor/gap/publication progress from
  explicitly sampled host resources and provides bounded status/query DTOs. A store-only adapter
  resolves registered run/spool/export/import milestones into query progress without accepting
  samples or minting transitions; the authenticated core query route is not yet mounted.
- The Wave 5 readiness script preserves the complete Wave 4 structural witness and reserves a
  distinct `useful_partial` Wave 5 result whose live/product maturity bits are all false.

The dependency direction for publication was repaired narrowly: the unused
`joshi-projection -> joshi-store` dependency and its unused `From<&EffectiveAssertion>` convenience
conversion were removed so the sole store can depend on publication contracts. This removes one
convenience conversion only; projection semantics and evidence requirements are unchanged.

The source registry is validated but deliberately unwired from `joshi-supervisor`. Phase-0 source
execution is a sealed no-network C0 fixture path; C1/C2 refuse before a runner or provider I/O can
exist. A supervisor -> source-registry dependency lands only with a real adapter from a
store-readback run/source/method receipt, never as an unused graph edge.

## Closed Phase-0 gates and remaining promotion blockers

These boundaries have independent adversarial coverage:

1. Exact seven-document run registration, independent six-component semantic parsing, service-owned
   clock authority, exact retry identity, and restart readback are closed for offline C0.
2. Public-integrity Pump origin-segment/store-receipt/run-bound catalog binding/catalog ACK and exact
   restart readback are closed; authenticated-private spool admission is explicitly unavailable
   rather than weakly inferred.
3. The finite operational recovery state machine and same-run spool/export evidence resolution are
   closed; unsupported recovery evidence refuses.
4. The restricted derived-artifact V2 import/CAS/Parquet/readback seam is closed at its descriptive,
   noncausal, no-execution authority ceiling.

The following remain promotion blockers and must not be hidden by the green Phase-0 gates:

1. A nonfixture collector must consume a store-readback registration and canonical source/method
   receipt. C1/C2 are intentionally disabled, and the source registry is not yet wired.
2. Cockpit V2 remains `unverified semantic` until exact expected profile x eligible-subject coverage
   closure passes red team and the store supplies atomic prepare -> body -> head with exact
   readback. Glass must not mirror a self-authored publication DTO as authority.
3. Ordinary pairing exchange is not mounted. The existing prospective-launch pairing capability is
   separate; no route should appear until Rust/Glass wire identity, OS entropy, trusted time,
   one-time persistence, restart/revoke, and fault semantics share one reviewed authority.
4. Private spool admission requires actual authenticated decryption/tag verification and key-policy
   authority; it must continue to refuse in their absence.

## Validation and witness discipline

Focused crate gates are useful evidence but not a root PASS. After concurrent crate work and the
root lockfile settle, run:

```sh
./schema/validate.sh
cargo test --locked --offline -p joshi-admission -p joshi-store
cargo clippy --locked --offline -p joshi-admission -p joshi-store --all-targets -- -D warnings
cargo test --locked --offline -p joshi-artifact-admission -p joshi-core
cargo test --locked --offline -p joshi-operational-status
./scripts/wave5-readiness
```

The migration validator, combined admission/artifact/store/core tests, operational-status and
mechanics-capability tests, and strict focused Clippy gates pass at this handoff. The standalone
`wave5-ignition-readiness` command also emits the expected V9 `useful_partial` result. A fresh full
`./scripts/wave5-readiness` run now passes the preserved workspace gate and executes both the C0
ignition component and the joined partial G0 component. Its schema-V3 witness binds the exact G0
component file, fifteen-role evidence bundle, V10 snapshot and V9/V10 migration digests while
keeping every root/product/live qualification false.

The final script output must continue to state `useful_partial`,
`qualification.fullOfflineFaultWalk: false`, and false for bounded-nonfixture,
restart-recovered, sustained, live, Ember-use, accessibility, and parity maturity until separate
occurrences prove those states. The C0 component walk reports
`public_c0_spool_catalog_closed`; it does not claim the full fixture traversal because complete
memory, default product mount, and the full 37-scenario crash boundary remain open. The separate
`wave5-g0-source-publication` command now closes source fact plus Cockpit V2
prepare/body/head for one exact offline fixture and reports their artifact identities, but keeps
`fullOfflineFaultWalk:false`. The same command now closes one same-run, fixture-bound supervisor
reservation/accounting prefix before the no-network attempt. The supervisor fsyncs the Pump
adapter's exact semantic batch with no store digest; the store consumes those same segment bytes,
then binds its receipt to the run before the supervisor spool records the ACK. The full 37-scenario
crash matrix, default product mount, complete memory closure and final
no-original-root reopen remain outside that component.
The component now also
retains one exact headed-scene act and partial unresolved episode; complete session/outcome/reveal/
interview memory closure remains outside it. This component exercises the canonical Pump policy
bytes without network I/O. The supervisor's separate generic synthetic adapter still uses the
fixture-only `joshi.store.policy.v1` contract and does not qualify production circulation.
Before the V10 G0 prefix, the same command copies the checked V8 operational catalog and its exact
referenced blob/export files into private state, migrates through V9, independently regenerates and
validates its real fourteen-table Snapshot V2 in Rust and locked Python, commits that snapshot plus
a same-run export binding, advances forward once to V10, then admits and reopens the exact restricted
manifest and Parquet artifact in external CAS. After the source/publication/memory/status prefix,
the store creates a second immutable input backup, privately resolves that backup plus the
registered CAS import, executes the exact 24-table V10 exporter with independent Rust and
locked-Python validation, commits and reopens the production snapshot, and includes its immutable
files in the final backup/restore inventory. Exact retry derives export time from the durable input
backup commit, so it reproduces the same snapshot and operation digest. This is a real nonempty V10
component export/import closure, but it is not a complete root walk.
After the memory prefix, the component persists one exact same-run `export_stale` degradation,
starts recovery before the immutable export-input backup, commits the production V10 snapshot, and
then creates a same-run export binding. Only that binding's store commit sequence and commit digest
may authorize the final `RecoveryVerified/Ready` occurrence. The complete chain is re-parsed and
reopened after restart; no caller boolean or production-receipt field can bypass the binding. This
proves positive recovery for the offline-fixture export component only, not root or live readiness.
The component uses a 1 KiB inline threshold so the retained source body produces one genuine
external immutable object, then executes the store-owned backup and restore writers into distinct
roots. It requires a nonempty inventory, exact retry, restored catalog/artifact digest equality and
read-only restart verification. The supervisor spool remains outside that store inventory and the
original roots remain available, so this is partial backup/restore evidence rather than the final
root recovery proof.

An opt-in Core integration test now joins the same durable Cockpit V2 body/head to ordinary
SQLite-backed pairing. A `CockpitRead` capability receives the byte-exact headed response; a
wrong-scope capability, revoked session, and pre-restart capability are refused. The default
`Serve` path still mounts neither exchange nor headed-publication route. The explicit
`wave5-g0-inspect` command now mounts a bounded store-rederived index and exact open route only for
the offline component fixture with a read-only one-time code. An explicit Glass build now consumes
that exact V2 inspection contract, independently recomputes the Rust digest domains, and exposes no
operator or presentation sink. No connected browser was available for real UI QA, and default
Glass remains unavailable, so this local join is not recorded as product Glass use or as a
completed root occurrence.

The component report now embeds a strict G0 V1 partial fault result. Fifteen baseline artifacts are
bound by exact owner/store digests (supervisor reservation, origin, receipt, binding, ACK, fact,
prepare, head, act, episode, committed V10 export manifest, restricted import, recovered status,
backup, and
restore), and
each maps one-to-one to
`observed_partial`. The provider plan
binds the same registered run and exact fixture digest before its no-network attempt. The runtime
fsyncs the exact Pump batch as the sole origin subsequently consumed by store/catalog; no second
segment is generated. The remaining roles and full 37-scenario matrix are absent, and both the embedded and outer
`fullOfflineFaultWalk` fields remain false.

## Explicit nonclaims

No Wave 5 code path reads a credential or wallet secret, calls a provider, opens a remote service,
constructs/signs/submits a transaction, places an order, changes liquidity, or claims profitability.
Replica ACK and catalog ACK never authorize deletion. Any mounted publication, export, import,
health, or Glass adapter must remain a read-only projection over already durable authority; none
may mint the facts it reports.
