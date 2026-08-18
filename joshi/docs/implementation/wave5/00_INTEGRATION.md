# Wave 5 integration — Living Instrument authority spine

Status: **implementation in progress / useful partial**. No full Phase-0 fault walk, live,
product-parity, publication, export/import, repeated-use, or remote qualification is claimed by
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
`wave5-ignition-readiness` command also emits the expected V9 `useful_partial` result. The full root
script is not recorded as passing yet: its preserved Wave 4 workspace gate encountered a concurrent
scientific-memory compile failure outside this lane, so no root PASS is inferred from focused gates.

The final script output must continue to state `useful_partial`,
`qualification.fullOfflineFaultWalk: false`, and false for bounded-nonfixture,
restart-recovered, sustained, live, Ember-use, accessibility, and parity maturity until separate
occurrences prove those states. The C0 component walk may report
`public_c0_spool_catalog_closed`; it does not claim the full fixture traversal because source-fact,
publication, export/import, status recovery and backup/restore crash boundaries remain open. The
separate `wave5-g0-source-publication` command now closes source fact plus Cockpit V2
prepare/body/head for one exact offline fixture and reports their artifact identities, but keeps
`fullOfflineFaultWalk:false`. The same command now closes one same-run, fixture-bound supervisor
reservation/accounting prefix before the Pump adapter, but those two durable segments are not an
atomic handoff. The full crash matrix, default product mount, complete memory closure,
export/import, status and backup/restore remain outside that component.
The component now also
retains one exact headed-scene act and partial unresolved episode; complete session/outcome/reveal/
interview memory closure remains outside it. A fixture may
exercise canonical Pump policy bytes without network I/O; the supervisor fake
`joshi.store.policy.v1` is not a production physical-policy contract and cannot qualify spool
circulation.

An opt-in Core integration test now joins the same durable Cockpit V2 body/head to ordinary
SQLite-backed pairing. A `CockpitRead` capability receives the byte-exact headed response; a
wrong-scope capability, revoked session, and pre-restart capability are refused. The default
`Serve` path still mounts neither exchange nor headed-publication route, and this local join is not
recorded as Glass use or as a completed root occurrence.

The component report now embeds a strict G0 V1 partial fault result. Ten baseline artifacts are
bound by exact owner/store digests (supervisor reservation, origin, receipt, binding, ACK, fact,
prepare, head, act, and episode), and each maps one-to-one to `observed_partial`. The provider plan
binds the same registered run and exact fixture digest before its no-network attempt. The runtime
and Pump/catalog adapters still create separate durable segments rather than one atomic handoff;
the remaining roles and full 37-scenario matrix are absent, and both the embedded and outer
`fullOfflineFaultWalk` fields remain false.

## Explicit nonclaims

No Wave 5 code path reads a credential or wallet secret, calls a provider, opens a remote service,
constructs/signs/submits a transaction, places an order, changes liquidity, or claims profitability.
Replica ACK and catalog ACK never authorize deletion. Any mounted publication, export, import,
health, or Glass adapter must remain a read-only projection over already durable authority; none
may mint the facts it reports.
