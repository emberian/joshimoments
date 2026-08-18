# W5-G0 adversarial integration review

Status on 2026-08-18: **BLOCKED**. This ledger reviews the in-flight implementation of
`W5-G0 root_fault_witness`; it does not implement or promote it. The current `useful_partial`
Wave 5 readiness result is not W5-G0.

## Authority and ceiling

The controlling requirement is the named external gate in
`docs/planning/WAVE6_REFLEXIVE_FIELD_LAB.md`: one complete fake
source -> spool -> catalog -> semantic fact -> immutable Cockpit V2 -> paired Glass -> memory ->
nonempty V10 export/import -> status -> backup/restore fault walk, against fixture authority. The
detailed acceptance matrix in `99_INTEGRATION_REVIEW.md` additionally requires exact store
registration before attempts, reservation-before-I/O and conservative settlement, a nonempty
store-derived denominator and independent hot/control membership, exact facts/gaps/omissions at
one cutoff, readback/restart, and producer/store-derived receipts rather than labels.

W5-G0 is a conjunction, not a progress score. Its root result must be false unless every required
component below passes in the *same occurrence*. A package-local test, syntactically valid digest,
caller-supplied clock/cutoff/receipt, empty relation, standalone head, success label, or
`useful_partial` status cannot satisfy any missing conjunct. Passing W5-G0 authorizes fixture store
adapter integration only; it is not `W5-G1`, live-provider, product, accessibility, operator-use,
memory, claim, mechanics, retention, or economic qualification.

## Current dependency graph audit

`cargo metadata --locked --offline --no-deps --format-version 1` on the current tree shows:

```text
joshi-collector -> domain, spool, supervisor
joshi-supervisor -> admission, domain, evidence, sources, spool, store
joshi-admission -> domain, evidence, pump-api, sources, store, surface
joshi-store -> artifact-admission, domain, evidence, export, operational-status,
               operator, pairing, projection, publication, scientific-memory, surface
joshi-core -> admission, domain, evidence, operational-status, operator, pump-adapter,
              pairing, spool, store
joshi-publication -> domain, projection
joshi-export -> domain, projection, publication, scientific-memory
joshi-pairing -> domain
joshi-scientific-memory -> (no internal package dependency)
```

These new edges provide only compile-time reachability. Pairing now has a private SQLite journal
adapter and an opt-in Core authorization/router constructor with passing durable tests. The
explicit offline-fixture inspector selects it, while default `Serve` still does not;
export now uses its parser dependencies, and Core exercises the private store wrapper against an
exact input backup and registered CAS import through the 24-table commit/reopen path. The root
cannot infer persistence or semantic verification from a public port, import or package edge. The
G0 component now joins its supervisor reservation and exact Pump batch to the sole store/catalog
origin. The root readiness wrapper now runs the component and paired-route/restart smoke through
one join, exact-matches their run/source/publication lineage, and binds both nested report digests,
the eighteen-role evidence-bundle digest, and V10 snapshot ID into a schema-V5 witness. The witness
remains a partial
artifact index rather than a completed root occurrence and keeps every qualification bit false.

## Per-component gate ledger

| Component | Required G0 closure | Current result | Adversarial ceiling / blocker |
| --- | --- | --- | --- |
| Run + accounting | Store-readback registration consumed before attempt; reservation before I/O; exact settlement/retry/restart | **PASS only as same-run offline reservation/source handoff; BLOCKED fault/live/root** | Core runs the sealed supervisor with the store-registered run and a plan whose scenario binds the exact fixture digest. Journal readback requires one observed, gap-free settlement; cancellation or post-I/O recovery refuses. The exact retained Pump batch becomes the sole store/catalog origin, but reservation fault injection, nonfixture execution and the rest of the root remain absent. |
| Origin + catalog | Fsynced immutable origin, exact store ingest receipt, run-bound catalog binding, ACK, reopen | **PASS only as joined durable-offline component** | The supervisor's exact local receipt and physical segment must equal the canonical precommit Pump batch; the sole store consumes those bytes, the run binding commits, and only then does the same spool record its ACK. Receipt substitution and a second/regenerated origin refuse. It is still fixture-only and not a complete G0 pass. |
| Denominator + hot/control | Nonempty store-derived eligible identities/count/digest at one cutoff; independently derived hot and cold-control membership | **PASS only as an isolated durable offline-fixture component; BLOCKED root/live** | The exact selection is retained separately from the exact provider body, its subjects must equal the parsed fact denominator, and the private resolver/reopen derives one hot plus one cold-control subject. This is fixture membership, not product parity or a live acquisition-policy result. |
| Semantic fact | Exact source/fact bytes, provenance, clocks, commit and readback derived from the store | **PASS only as a joined durable offline-fixture component; BLOCKED root/live** | `wave5-g0-source-publication` derives the source occurrence from the receipt over the supervisor-owned Pump segment and decoded provider bytes, then fully rederives it after read-only reopen and exact retry. A nonfixture source and the remaining root components are absent. |
| Cockpit V2 publication | Store resolves inputs at one cutoff; atomic prepare/body/checkpoint/head; immutable exact-byte reopen | **PASS only as an isolated durable offline-fixture component with opt-in paired read; BLOCKED root/default mount** | The component command commits strict prepare → immutable body → append-only head and reopens all exact bytes/digests. Eight before/after semantic/prepare/body/head interruptions converge to the identical chain. The explicit inspector returns a bounded, store-rederived head index and those exact body/head bytes under a durable scoped session, but default `Serve` and the product remain unmounted and the other root seams are absent. |
| Pairing + Glass | OS entropy; trusted origin and time; bounded rate/expiry; one-time durable consume/revoke/restart; same-origin open of exact publication | **PASS only as isolated durable paired-publication API + Glass inspection protocol; BLOCKED default-product/root G0** | The SQLite exchange opens the exact headed offline-fixture publication only for `CockpitRead`; wrong scope, revoke, and restart refuse. Root readiness now runs a finite in-process exchange/open, restarts the epoch, refuses the old capability, and verifies a byte-identical fresh-session open. The explicit Glass inspector independently parses the V2 closure without action sinks. Default `Serve`/Glass remain unavailable, no browser instance was connected for UI QA, and no product presentation occurrence or complete root fault bundle exists. |
| Scientific memory | One scene-bound presentation-or-gap/act/session/outcome-or-censor/reveal/interview chain with store-owned occurrence/commit order, ACK and restart | **PASS only for an isolated durable censored fixture chain; BLOCKED qualified presentation/outcome/root** | The component commits and reopens one exact headed-scene act with a typed presentation gap, a partial unresolved/no-trade episode, hidden replay, incomplete close, explicitly gapped partial knowledge, missing outcome, retrospective replay, and interview in strict queue/commit order. Complete session, closed knowledge, and available outcome are adversarially refused. The chain remains `unverified_semantic`: no actual product presentation or qualified outcome exists. |
| Nonempty V10 export/import | Lower-cutoff store query; every required nonempty relation; store-resolved metadata; independent offline validation; CAS import and reopen | **PASS as a joined durable offline-fixture component; BLOCKED complete root/live** | Core copies the checked V8 catalog and exact referenced files, regenerates and independently validates its fourteen-table snapshot, commits the V9 export and same-run binding, advances to V10, and admits/reopens the restricted manifest plus Parquet CAS. It then creates an immutable input backup, runs the private backup-bound 24-table V10 wrapper, independently validates Rust/Python readback, commits the exact snapshot, and captures it in the final backup. This remains fixture-only and does not imply status recovery, product use, or root completion. |
| Status | Store-derived status over the exact occurrence, with typed gaps and recovery readback | **PASS as a joined durable offline-fixture export recovery; BLOCKED root/live** | Core commits `export_stale`, starts recovery before the immutable input backup, commits the V10 snapshot, and adds a canonical same-run export binding. `RecoveryVerified/Ready` cites only that binding's exact commit sequence and commit digest; store semantics reject a production receipt or unrelated commit. The full chain reopens exactly but does not imply product, live, or root readiness. |
| Backup/restore | Backup includes SQLite plus every referenced artifact/CAS/publication/origin object; restore into a distinct location; artifact-bearing reads and digest revalidation | **PASS as isolated durable and joined partial store backup/restore; BLOCKED complete inventory/fault/root** | The public-API test still proves original-root removal and tamper refusal. Core now additionally joins the actual writer to the same partial occurrence, with a 1 KiB external source object, nonempty inventory, distinct backup/restore roots, exact retry and restart readback. That joined path does not hide the original roots or include the separate supervisor spool inventory, so it is not the final recovery set. |
| Fault matrix | Crash/retry at reserve, I/O, spool, store commit, publication prepare/body/head, pairing consume, memory ACK, export/import, backup/restore | **PASS only for strict false contract + package-local prefix recovery; BLOCKED full executable/root** | The source/publication/memory/status/export/backup implementation passes thirty exact before/after component interruptions. Pairing/open adds six more around exchange, exact read, and reopen, with fresh-session recovery on the same catalog. These 36 package-local checks are not an exact mapping of the schedule's 36 transitions. The root join closes baseline evidence roles only; it does not emit a result for each of the 37 scheduled scenarios, so no fault-walk qualification follows. |
| Root evidence bundle | Canonical machine-readable evidence with exact IDs, digests, cutoffs, clocks, paths/keys, receipts and negative qualification bits, independently reverified after reopen | **PASS only as one eighteen-role partial baseline bundle; BLOCKED fault-root** | `wave5-g0-root-evidence` runs the component and pairing/open/restart smoke over one catalog, exact-matches run registration, source occurrence, publication semantic/byte digests and head, and extends the fifteen component artifacts with consumed pairing, exact HTTP read and post-restart readback. The schema-V5 readiness witness binds the resulting eighteen-item bundle and both nested report digests. This is one baseline conjunction, not 37 executed scenario results; final no-original-root recovery and every qualification bit remain false. |

## Red-team invariants for landing components

1. **No self-authored authority.** The root must resolve stored bytes and recompute identities,
   digests, counts, clocks, cutoffs and receipt links. It may not accept those fields from the
   fixture or merely compare two values derived from the same caller object.
2. **No circular digest closure.** An artifact identity cannot be included in the bytes used to
   derive itself. Precommit bodies must omit postcommit receipts; later bindings must name exact
   earlier bytes and be recomputed on readback.
3. **No semantic fixture laundering.** A structurally valid row is not a source fact. The receipt
   must bind exact fixture-source evidence, parsed semantic content, run, provenance, occurrence
   and store commit.
4. **No empty-relation success.** Every relation that G0 claims to traverse must be nonempty where
   the fixture semantics require rows. Manifest-only declarations, zero-row Parquet files and
   optional omitted tables cannot satisfy nonempty V10 export/import.
5. **One cutoff, independently enforced.** Publication, surface, status and export must query the
   store at the recorded lower bound/cutoff. A caller field named `cutoff` or
   `from_commit_seq` is not enforcement.
6. **Pairing is a durable protocol.** Entropy must come from the production OS boundary; the
   trusted service supplies time and exact origin; issue/failed-attempt/rate/consume/revoke state
   survives reopen; capability bytes never enter logs, persisted public evidence or serialization.
7. **Crash success means atomic durable state.** Faults must prove either absence or exactly-once
   committed state at every boundary, followed by reopen and artifact-bearing readback. Cleanup or
   process exit alone is not recovery.
8. **Backup includes reachable bytes.** Restoring only the catalog cannot pass when rows reference
   origin, publication, export or CAS bytes. The restored system must read and rehash every
   referenced artifact without consulting the original paths.
9. **Readiness is a strict AND.** Any absent, false, malformed, duplicated, caller-authored or
   unreverified component keeps `W5-G0=false`. `useful_partial` remains orthogonal.

## Landing review findings

### P0 intercepted — caller-implemented memory port minted `store_verified`

The first in-flight `joshi-scientific-memory` port shape exposed a public,
generic `ScientificMemoryStorePort`, accepts the implementer's returned JSON bytes in public
`MemoryKernel::append_via_store`, and then replaces the kernel with a staged copy whose global
`store_verified` Boolean is true. Any downstream crate can implement that trait and construct
canonical JSON containing the request's public occurrence ID/digest plus arbitrary positive queue
generation and catalog sequence. Private Rust fields do not make JSON bytes unforgeable.

That path proved neither the sole store, fsync, restart readback, run binding nor actual commit
order, yet it could remove `ResearchRefusal::UnverifiedSemantic` for all retained acts. Review
feedback caused the promoting API and staged global Boolean flip to be removed. The current public
port returns no receipt and its success cannot upgrade `MemoryKernel`; its regression test retains
the unverified refusal. This closes the intrinsic laundering vector. Scientific memory and W5-G0
remain **BLOCKED** until a closed store-owned adapter persists and reopens per-occurrence receipts
and the complete chain.

### P0 — initial V10 store spine cannot represent the claimed joins

The first in-flight `0010_wave5_g0_store_spine.sql` is **BLOCKED** pending its private writer and
schema repair:

- `cockpit_v2_preparation_v1` requires its `resolved_input_bytes` and digest to equal the source
  occurrence descriptor bytes and digest. The source row separately declares
  `joshi.store.wave5.source_occurrence.v1`, while the strict publication parser requires the input
  bytes to carry `joshi.store.cockpit.v2.resolved_source_facts_input`. One canonical byte string
  cannot satisfy both contract identities. Either these are distinct artifacts with an explicit
  binding or the join is not representable.
- `fact_count`, `eligible_subject_count`, `coverage_count` and maximum availability time are scalar
  columns. A writer must reconstruct them and the exact facts/universe/memberships/coverage/gaps
  from the prior source receipt and persisted bytes. Accepting them from a caller would launder a
  structurally valid source descriptor into a semantic fact.
- the head lineage permits two new heads to name the same prior head; without a unique successor
  or another store-owned selection rule there is no sole immutable current head.
- the pairing journal lacks origin, scopes, trusted issue clock/clock identity and failed-attempt
  rate state. Its terminal trigger also treats consumption as final, preventing later revocation of
  a consumed session. It cannot establish the required durable pairing protocol.
- the backup row retains a manifest and catalog digest but has no schema-enforced or writer-shown
  closure over every referenced origin/publication/export/CAS artifact and no distinct-root
  artifact-bearing readback.

The source/preparation bytes were separated, the head gained a unique successor, and a private
source/publication/memory adapter then landed. Its first revision assigned the lexicographically
first eligible subject to `Hot`, fabricated per-subject coverage and always emitted empty gaps.
That laundering path was replaced with exact subject-scoped hot/census coverage windows, retained
gaps, omissions and a mandatory nonempty hot/cold partition. A second revision still allowed
opaque/malformed observations and unknown open-variant coverage/gap labels to drive typed facts;
recognized `provider_body` + `decoded` JSON and known coverage/gap semantics are now required.
These repairs raise the private resolver above the fabricated-input revisions, but no honest
store-writer fixture or root occurrence currently exercises and reopens it. The SQL-seeded export
fixture is not such evidence because it bypasses these resolvers.

The initial expanded pairing schema was incompatible with the canonical pairing bytes on
predecessors, issue IDs and authority. Those fields and the exact epoch occurrence were
subsequently aligned. Restart invalidations now belong to the new epoch, their predecessor must be
exactly one epoch earlier, their wall clock cannot regress a live predecessor, ordinary same-epoch
transitions check predecessor clocks, and origin-scoped identities prevent cross-origin epoch-one
collisions. Review then intercepted two persistence defects: Core ignored the store-returned
post-invalidation ordinal, and a fresh registry reset both failed-attempt and issue windows. The
draft now seeds the ordinal and reconstructs live fixed rate windows with a persisted policy and
per-occurrence window identity. An intermediate store revision derived a plain rather than
domain-separated origin tag; it now uses the model's canonical identity helpers. That repair is
not yet an integration pass. An intermediate `begin_pairing_epoch_v1` read the prior epoch,
reconstructed rate state and enumerated live predecessors *before* acquiring its `IMMEDIATE`
writer transaction. A second connection could append a live issue/session between those reads and
lock acquisition, so the new epoch could commit without invalidating it. That P0 was intercepted: epoch, rate and live
predecessor derivation now run beneath the `IMMEDIATE` transaction. At that intermediate revision
no honest store-to-Core adapter or constructible production journal existed. The later private
SQLite adapter and lifecycle tests close that isolated durability boundary, while the default
mount and paired-publication root occurrence remain absent.

Schema existence is not store resolution. Until exact private writers rederive and reopen every
relation—or explicitly cap it as nonqualifying—store spine, publication, pairing, backup and
W5-G0 remain **BLOCKED**.

The private scientific-memory writer initially had a parallel atomicity defect: it rebuilt and
validated the semantic kernel prefix before opening its `IMMEDIATE` transaction. That validation
and idempotency check now run beneath the writer transaction, closing the stale-prefix race. The
writer now also admits the exact nonclosed/censored fixture states through interview, while
refusing complete session, closed knowledge, and available outcome. This closes a censored durable
prefix only, not qualified presentation, outcome, or the complete root chain.

### P0 intercepted — initial pairing wire/state changes did not round-trip

The first in-flight pairing change is **BLOCKED** on intrinsic defects before durability is even
considered:

- the generated human code is 45 characters (`JOSHI`, eight separators and 32 symbols), while
  `PAIRING_CODE_TEXT_LENGTH` is 46; every issued code is therefore refused by `SecretCode::parse`;
- the first bad code increments `failed_attempts` to one but records
  `failed_attempts.max(max_failed_attempts)`, so it falsely persists the threshold ordinal instead
  of the actual rate state;
- `MonotonicMillis::new(0)` can serialize as `"0"`, while its deserializer refuses zero, so a
  process-start occurrence can be emitted but not parsed on durable readback;
- the trait-level authorization method discards expiry occurrences produced during authorization,
  while direct revocation does not expire first and can turn an already-expired session into a
  revoke without retaining the expiry transition; and
- entropy and the coherent-clock trait remain publicly injectable and the registry remains
  memory-only. No mounted production boundary forces OS entropy, trusted origin/time, durable rate
  state or atomic consume/restart.

These defects were routed immediately. The length, actual ordinal, zero round-trip and retained
expiry transitions were repaired and focused package tests now pass. This raises only the pure
state/wire slice to `intrinsic_contract`; pairing remains **BLOCKED** at durable/G0.

### P0 — initial G0 export checks nonemptiness, not one closed occurrence

The first in-flight V10 exporter adds twelve relations and refuses an empty one, but it does not
yet verify that selected rows form one run-rooted connected component. A row may reference a run,
source occurrence, prior head, opening act or predecessor below `from_commit_seq`; unrelated rows
can keep every relation nonempty. Likewise, one `issued` pairing row, an arbitrary status row, a
manifest-only backup row and unrelated prior export/import rows satisfy table nonemptiness without
the required consume, recovery, artifact readback or same-run lineage. This is nonempty-relation
laundering, not G0 export closure.

The derived-artifact recomputation also initially used the *minimum* input
`decision_available_at` for a metric computed from every observed sample, backdating the aggregate
before its latest input, and checked stable identity only across observed rows while allowing gap
rows with conflicting identity. Those temporal/identity defects were routed for repair. Export and
artifact admission remain **BLOCKED** pending connected-lineage, required-disposition, staggered-
availability, conflicting-gap and lower-bound adversaries.

The aggregate availability and identity checks were subsequently repaired. A connected-lineage
validator was added. One intermediate revision attempted 12 G0 relations including pairing and
backup, exposing further exact defects:

- the exporter's pairing query selects a nonexistent `token_sha256`, reads the SQL-null issued
  `session_id` as non-null, and requires it to equal the consumed session ID. The migration
  deliberately contains no secret-token digest and requires issued session ID to be null;
- the Python validator neither checks the pairing chain nor the backup/run join, and applies
  `read_only_no_execution` to every G0 row even though the pairing contract requires
  `read_only_pairing_exchange`. An honest V10 therefore cannot pass both validators; and
- restart validation does not require a `wave5_g0_backup_restore_v1` occurrence and never proves
  the restored catalog digest equals the selected backup. It hashes the source backup and one CAS
  part at caller paths, leaving a foreign restored catalog able to satisfy that check.

Pairing and backup were then removed from the export relation set, eliminating those false claims
from the snapshot. The current V10 factory is explicitly a narrower ten-relation export slice; it
does not prove pairing or backup/restore and cannot be treated as the root G0 closure. The first
production store revision also rejected every 24-part V10 snapshot because it required exactly the
14 base relations. Store commit now selects the exact 14- or 24-table closure by snapshot catalog
schema and recognizes headed Cockpit V2 publications. This repairs the cardinality/import boundary
but does not provide an honest snapshot or any omitted root component.

Artifact admission also initially retained an empty-group laundering path: metric recomputation
returned `None` as soon as a group had zero `observed` rows, before checking gap shape, stable
identities and clocks. Validation was moved before the zero-output case, and focused regressions
now reject conflicting identity, malformed status, non-null measurement and bad-clock all-gap
inputs. Exact-ratio tests above JavaScript's integer width also pass. That repairs the artifact
component adversary; it does not repair the V10 occurrence closure.

The producer now invokes a separately reusable Rust directory reopen validator and the Python
command is locked and offline. Current blockers are at the honest store/export boundary:

- `cockpit_v2_head_v1.head_sha256` is the head's semantic digest over material that excludes the
  self field. Both the relation factory and earlier publication-closure loader initially compared
  it to SHA-256 of serialized head bytes. They now parse the head and validate its semantic digest
  against the body, closing that honest-writer contradiction.
- The first SQL-seeded G0 fixture inserted placeholder, noncanonical source/publication/memory
  bytes, logical ticks above `u64::MAX` and omitted newly required source columns. It was neither
  an honest writer fixture nor a runnable positive serializer fixture. The fixture now constructs
  canonical semantic bytes and required columns, and a checked-in V10 catalog drives a positive
  24-relation Rust/Python export/reopen test. It remains direct SQL that bypasses the private
  source/publication/memory writers, so this raises only the synthetic format ceiling.
- An intermediate source/publication/memory parser revision was dead code. The relation factory
  now invokes those parsers and carries the exact source/publication/head/memory bytes. Focused
  tests exercise semantic closure, Arrow `Binary` encode/reopen and substitutions; Python schemas
  are aligned. This repairs the tested format path, not the absent store-owned occurrence.
- Import rows are selected from database scalar descriptors without opening the referenced CAS
  object. The exporter now additionally requires and reopens a manifest/part path DTO, checks the
  exact physical/logical/schema/row closure, and explicitly labels that DTO neutral. This closes
  format-level artifact-bearing readback. A private store wrapper resolves that DTO from its
  registered CAS object before and after export. Its first revision still accepted arbitrary
  caller catalog path/range/identity and could commit a foreign same-identity V10 catalog. The
  wrapper now requires an exact loaded backup, overwrites catalog path, identity, schema and range
  from that backup, requires the import to precede its cutoff, and rechecks backup/CAS closure
  after export. This closes the inspected foreign-catalog path. The later Core component test now
  invokes the repaired wrapper from the exact private backup/import, commits the 24-table result,
  and reopens it; this supplies offline-fixture store provenance but not complete root closure.
- The production store's 14-part and legacy-publication restrictions were repaired to require the
  exact 24 V10 parts and a headed Cockpit V2 publication. The exporter's separate publication
  closure loader was then aligned to the semantic head digest. Store commit briefly required V10
  unconditionally and regressed the existing V9 14-part path; it now selects the exact 14- or
  24-table closure by snapshot catalog schema. The joined Core component supplies the honest
  offline-fixture store call; default product/live and the complete root fault walk remain absent.

Export/import now reaches the **joined durable offline-fixture component** ceiling against the
frozen V10 migration. The regenerated catalog and 24-relation snapshot pass exact Rust/Python
reopen with ten nonempty G0 relations, and the Core component independently exercises the private
backup-bound writer/commit/reopen path. W5-G0 remains **BLOCKED** at root/product/live scope; the
separate direct-SQL serializer fixture is only independent format evidence.

### P0 intercepted — public pairing journal could echo durable-looking receipts

The initial `OrdinaryPairingService::production` accepted a public caller-implemented
`Box<dyn PairingJournal>`. It accepted a positive caller-returned epoch/commit sequence and exact
echoed request bytes as proof of durable journal readback before returning the one-time code or
capability. An arbitrary caller could therefore mint the same receipt echo without any commit or
restart state.

The production constructor was changed to require `DurablePairingJournal`, whose inner constructor
is private. That sealed the echo vector: generic/test journals can exercise the intrinsic
coordinator but cannot construct the production route. A subsequent private `SqlitePairingJournal`
adapter now derives its commit contexts, calls the V10 pairing writers and maps only exact
store-owned readback receipts. The first honest opt-in lifecycle test then exposed a store receipt
defect: one live `Consumed` predecessor carries both issue and session IDs, and restart bootstrap
counted it as both an invalidated issue and invalidated session although it emits one session
invalidation. Core's exact count/receipt verification refused reopen. Store now derives both
counts by predecessor kind. The rerun passes exchange, scoped read/write authorization, durable
revocation, another live consume, reopen/restart invalidation, next ordinal and refusal of the old
capability. A separate adapter test passes exact expiry persistence and readback across reopen.
The later paired-publication test opens the store-revalidated G0 Cockpit body/head under
`CockpitRead`, rejects a write-only scope, then proves revoke and restart refusal. This raises
pairing to an **isolated durable paired-publication pass**. The explicit `wave5-g0-inspect` command
now selects the sealed constructor for that offline fixture and exposes a bounded exact head index;
default CLI `Serve` still calls `CoreService::new`, which leaves ordinary pairing absent.

The first mount draft exposed an actual protocol incompatibility, not merely a missing router
merge. Ordinary exchange returns `jpc1_<64 lowercase hex>` and Glass forwards it in
`X-Joshi-Pairing-Token`, while Cockpit/operator handlers authenticated only the separate legacy
64-hex capability. An optional Core seam now parses the ordinary capability, checks the exact
origin/browser posture and required read/write scope, and does not fall back to legacy auth while
configured. The end-to-end unit exercises refusal across the restart boundary and now also reads
the exact headed G0 publication. This repairs the intrinsic
namespace/scope mismatch, but the
constructor is crate-private, the default service still configures no ordinary coordinator, the
exchange route therefore remains 404 in production, and no launch path selects the SQLite seal.

The first scoped-authorization implementation also sampled the clock twice. It first called
`expire_now`, persisted those occurrences, then called `authorize_now`, which sampled again and
internally expired once more. A session crossing its TTL between those samples was removed and
refused without a durable `Expired` occurrence. Review intercepted that race. The sealed Core path
now uses one sampled outcome carrying expiry occurrences on both success and rejection, persists
that vector before mapping the result, and has focused expiry-on-refusal tests.

The generic public `PairingSessionPort::authorize_capability` initially retained the older result
shape and still dropped rejection-side expiry vectors. It now returns the same explicit
authorization outcome, closing that public mutation-without-receipt trap. Pairing nevertheless
remains **BLOCKED for W5-G0** pending a default product launch, a real browser presentation
occurrence, and the complete root conjunction. The explicit offline inspector is not that product
occurrence.

### P0 — a backup inventory and a false-only schedule are not restored artifact recovery

Migration V10 now has typed backup/restore rows. A private backup writer copies the SQLite snapshot
plus paths selected from external blob/export tables, rehashes copied bytes, commits a canonical
inventory and reopens that inventory. A subsequent restore writer copies the catalog and inventory
to new roots, opens a read-only `SqliteStore` over those roots, runs full verification and retains
an exact restore document.

Review intercepted a retry branch that accepted any pre-existing, internally valid same-max
SQLite file as the backup; it did not prove that the file came from this source. The same revision
allowed zero artifacts, trusted its own inventory without rederiving reachability from the backup
catalog and restored only SQLite. Those defects are now repaired: destinations must initially be
absent, inventory must be nonempty, load rederives exact blob/export reachability from the backup
catalog, and restore copies and fully verifies the artifact roots.

The next revision adds distinct backup and restore reservations, a private staging catalog,
atomic exact-digest copies, exact inventory-tree checks and symlink-ancestor refusal. Review then
caught that an existing internally valid same-max staging file was reused without a bound digest.
A second durable snapshot settlement now records the staged catalog digest/cutoff, requires the
staged commit tip to be an exact live-store prefix, discards any unsettled crash residue, and only
reuses bytes matching the settlement. This closes the reproduced foreign-stage laundering path,
and the store/Core compile check is green. Review also caught that `copy_file_atomically` initially
hashed and renamed without syncing the copied file or parent directory. It now `sync_all`s the
temporary/final files and directory chain before SQLite settlement. A later audit found that
postcommit restore reopen checked the exact restored path set and called `VerifyDepth::Full`, but
that general verifier did not hash `export_manifest` or `export_snapshot` paths. A tampered restored
export manifest could therefore survive reopen. Restore load now independently rehashes and
length-checks every inventory entry; the focused manifest/snapshot tamper regression passes.
An honest public-API test now registers canonical run bytes, commits a forced-external 2 KiB
observation, executes the complete backup writer with a nonempty inventory and exact retry, renames
the original live blob/export roots unavailable, restores to distinct roots, restarts the authority
store, reopens the exact restore, then tampers the restored artifact and observes refusal. That
raises backup/restore to an **isolated durable component pass**. Core now also executes the writer
at four component-local before/after interruption points and joins its exact manifest/readback to
the partial evidence bundle. It remains **BLOCKED for the full fault walk and W5-G0**: that joined
backup does not cover the separate supervisor spool inventory, remove the original roots, or execute
the harness's complete 37-scenario schedule.

No backup status or manifest row may qualify without enumerating every reachable origin,
publication, export and CAS object and reopening their bytes under a distinct restored root with
the original paths unavailable.

The harness freezes baseline plus all 18 before/after crash scenarios and its V1 result can never
emit `fullOfflineFaultWalk:true`. It is now a root-workspace library with six tests. Core supplies
fifteen artifact digests rederived from its owner/store objects; the harness maps those roles
one-to-one to `observed_partial` and refuses hidden/duplicate/missing-role evidence. This is a
**PASS for strict partial baseline accounting only**. The harness does not independently open the
artifacts, and no positive authority follows from its digest. Unimplemented seams remain typed,
the authority stays `fixture_harness_no_execution`, the full schedule is not executed, and result
validation unconditionally rejects a positive root Boolean.

## Targeted verification during this review

- Final store/schema audit used frozen migration 0010 SHA-256
  `92616764f786ba3eaf3f2da9c739c1f5ed36f9da1beb47416bd74e20cdf69c1b`.
  `cargo fmt --all -- --check`, schema validation, store all-target tests (14 unit plus one
  authority integration), strict store Clippy and store rustdoc all pass on that frozen tree.
- `cargo check --locked --offline -p joshi-store -p joshi-export -p joshi-core
  -p joshi-artifact-admission -p joshi-pairing`: passed after the in-flight compile repairs.
- Focused artifact tests passed, including exact values above `2^53` and malformed all-gap input.
- `cargo test --locked --offline -p joshi-pairing --all-targets`: 13 intrinsic tests passed after
  origin identity, restart ordinal, durable rate-bootstrap and expiry-on-refusal repairs. There is
  still no default mounted route, so this alone is not product evidence.
- Final `cargo test --locked --offline -p joshi-core --all-targets` passes 21 library, one binary
  and eight HTTP tests. This includes exact SQLite exchange/scoped access/revoke/restart/next
  ordinal/old-capability refusal, boundary-expiry persistence/reopen, and the byte-exact headed G0
  publication open with wrong-scope/revoke/restart adversaries. The HTTP V10 receipt golden is
  aligned. Pairing tests still do not supply a default production mount.
- Full Glass gates pass 23 files / 157 tests plus default and explicit-inspector builds. The six new
  inspector tests match the frozen Rust V2 digest vector; reject private/future/narrowed/substituted
  inputs; verify memory-only scoped transport; and exercise pair → exact index → explicit open UI.
  The route is not mounted by the default production service, and attached-browser QA did not run.
- An earlier combined targeted package run was red at
  `apps/core/tests/http.rs::ack_is_only_emitted_after_commit_and_exact_retry_is_idempotent` because
  its expected receipt still named catalog V9 after migration V10. The golden was aligned and the
  final Core all-target rerun above is green.
- `./schema/validate.sh`: passed 10 migrations again after the pairing schema changes, but its tape
  contains no V10 G0 rows. It proves
  migration load/legacy invariants, not any G0 writer, transition or root occurrence.
- The first attempted G0 fixture build was compile-blocked while a CAS argument was being added,
  and inspection found the head-digest contradiction and noncanonical direct-SQL semantic rows.
  Those format defects are repaired and covered by the final positive fixture; its direct SQL
  provenance still cannot close the private store boundary.
- The final combined `cargo test --locked --offline -p joshi-pairing -p joshi-store
  -p joshi-export --all-targets` passed 13 pairing, 14 store and 21 export tests. Export now includes
  a positive 24-relation V10 Rust/Python export/reopen, lower-bound and post-registration CAS
  tamper adversaries, exact semantic-byte binary reopen and substitutions. These tests use a
  direct-SQL catalog and a public neutral CAS DTO; they do not exercise the private store writers.
  The later public authority integration test separately exercises the backup/restore methods; it
  does not invoke the export wrapper or V10 store commit branch.
- That combined result initially predated the backup reservation/snapshot edits to migration 0010,
  and this review reproduced its migration-hash refusal. After store freeze, the fixture was
  regenerated with the exact migration hash
  `92616764f786ba3eaf3f2da9c739c1f5ed36f9da1beb47416bd74e20cdf69c1b`.
  The focused Rust G0 export tests now pass 2/2, including lower-bound/CAS adversaries and the
  positive cross-runtime reopen. Focused locked/offline Python tests pass; root's complete rerun
  reports export/artifact 30/30, focused Python 36, and direct validation of 24 tables/10 rows.
  Checked fixture identities are catalog
  `sha256:c3857f874eda776c15cf3d6bd6bc225ce674275645f2c591d20f3c539cf1f0d0`,
  snapshot `sha256:7027d8751401ff0eff8f2d0a76ade9ac3204d53a9f5b47b046608001e934b0a2`
  and manifest `sha256:b639eb93ed95dd3c5488ccc84c735d4a8675dfea1eddd9d76ea01e7cc5b2dec3`.
- The focused backup helper regression passes after the restored inventory-entry repair, strict
  store Clippy is green, and the public authority integration test passes the complete nonempty
  backup/restore/retry/no-original-root/restart/tamper lifecycle. This qualifies the isolated
  durable component, not the unexecuted harness fault matrix or root conjunction.
- Executing `build_g0_catalog_fixture` against a fresh destination now succeeds and emits a V10
  catalog. This repairs the synthetic serializer fixture after its missing-column failure; it does
  not make the fixture an honest store occurrence.
- `uv run --locked --offline pytest -q` in `analysis`: the full suite passed after Python binary
  schema alignment. With no producer-created G0 directory fixture, that is regression coverage for
  the validator, not cross-runtime G0 evidence.

## Final frozen store/schema audit

No remaining store/schema P0 was reproduced after the freeze. The exact ceilings remain narrower
than that statement:

- **Source/denominator: isolated durable offline-fixture PASS; root/live BLOCKED.** The resolver accepts only retained public C0 receipts and known
  decoded `provider_body` JSON, derives facts from exact blobs at the receipt commit, requires at
  least two subjects, exactly one recognized subject-scoped hot/census window per subject,
  nonempty hot and cold-control partitions, retained recognized gaps, and the exact
  rendered/omission partition. Load rebuilds the descriptor from store rows and bytes. The new
  component witness executes and reopens this path with an exact, separately retained
  `offline_fixture_only` selection. No supervisor-joined or nonfixture occurrence exists.
- **Publication: isolated durable offline-fixture, local fault-prefix, and opt-in paired-read PASS; root/default mount BLOCKED.** Prepare stores exact resolved
  input/semantic/container/checkpoint bytes together; body finalization allocates its own commit
  inside one transaction; the later head append is linear and unique, and V10 export admission
  accepts a V2 publication only with its head at the cutoff. The component witness now executes
  the honest store lifecycle, exact retry, read-only reopen, and interruption immediately before
  and after semantic fact, prepare, body and head. The opt-in Core route returns the exact headed
  bytes after durable scoped pairing and refuses wrong-scope, revoked, and pre-restart sessions. It
  does not run the other G0 crash boundaries or record a product Glass presentation occurrence.
- **Scientific memory: isolated durable act/partial-episode prefix PASS; complete chain/root BLOCKED.** Prefix
  reconstruction, idempotency, semantic append validation and queue-generation allocation occur
  beneath the `IMMEDIATE` transaction, and load revalidates the prefix plus exact headed scene.
  The component now commits, exact-retries and reopens one typed-presentation-gap act followed by
  one partial unresolved/no-trade episode, including its four before/after interruption points.
  The store deliberately admits no later session/outcome-or-censor/reveal/interview artifacts, so
  the required full chain remains absent.
- **Pairing: isolated durable paired-publication + Glass inspection protocol PASS; default/product/root G0 BLOCKED.**
  Exact SQLite lifecycle, expiry/reopen, origin, rate-window, restart-count and ordinal tests pass,
  and a scoped capability opens the exact G0 Cockpit V2 body/head. The explicit CLI/Glass inspector
  is mounted only by deliberate developer selection; default `Serve` and production Glass remain
  deliberately unmounted.
- **Export store boundary: joined durable offline-fixture V10 PASS; complete root/live BLOCKED.** Core exercises
  the store-owned fourteen-table V8/V9 commit branch, same-run export binding, forward V10
  migration, and exact restricted manifest/Parquet CAS readback. The private V10 wrapper loads an exact backup and import,
  overwrites catalog path/identity/schema/range with the backup closure, resolves CAS before and
  after export, and reopens the backup. The commit branch requires exact ordered 14-table V8/V9 or
  24-table V10 closures and headed V2 publications for V10. Core now invokes that wrapper, commits
  and reopens the resulting production snapshot, exact-retries it from the same immutable backup
  time, and includes its files in the final backup. The regenerated direct-SQL 24-table fixture
  remains a separate independent synthetic format witness.
- **Backup/restore: isolated durable component PASS; fault/root BLOCKED.** Nonempty inventory,
  exact reservation/staging settlement, fsynced copies, independent reachability, distinct-root
  restore, no-original-root restart and tamper refusal pass. No harness adapter executes all
  before/after crash points.

## Current root decision

**W5-G0: BLOCKED.** Origin/catalog, source/denominator/publication, deliberately partial memory,
export/import/status/backup and paired API read now form one eighteen-role baseline evidence
bundle, but it cannot raise the fault/root or product gate. No implementation reviewed at this
point emits exact results across all 37 required scenarios or a final no-original-root product
reopen, and no Boolean readiness claim may say otherwise.
