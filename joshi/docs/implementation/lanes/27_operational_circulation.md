# Lane 27 — operational circulation proof audit

Status: **exact source→census→market→projection prefix audited; full circulation correctly
blocked by three missing durable joins**  
Authority: `read_only_no_execution`  
Code: [`crates/joshi-operational-circulation`](../../../crates/joshi-operational-circulation)  
Fixture:
[`fixtures/operational-circulation/adversarial.v1.json`](../../../fixtures/operational-circulation/adversarial.v1.json)

## Outcome

This lane answers a deliberately narrow question: can the current Wave 4 objects prove, using
exact persisted bytes and post-commit receipts, that one source occurrence circulated through the
census, an event-bound wallet-cluster selection, a point-in-time market-state artifact, a
deterministic projection, and durable publication?

The honest V1 answer is **not yet**. `audit_circulation` validates the complete prefix and returns
`CirculationOutcomeV1::Blocked` with three stable blockers:

| Blocker | What is proven | What is still absent |
| --- | --- | --- |
| `census_membership_artifact_not_semantically_inspectable` | exact `CensusDenominatorRef`, cutoff, evidence/coverage links, and `acquisition_policy` source/fact receipt | exact sorted eligible-member rows that prove the selected market subject belongs to the stated denominator |
| `projection_market_state_artifact_unreferenced` | the projection contains every exact effective assertion and observation in the market-state input closure, and its cutoff follows the market-state commit | a typed projection input reference naming the exact market-state artifact ID, artifact digest, and post-commit receipt |
| `publication_exact_bytes_unbound` | canonical publication semantics, semantic `publicationDigest`, exact projection artifact bytes/digest, and the current post-commit publication receipt | a versioned receipt field for exact publication-byte SHA-256 and length, distinct from semantic `publicationDigest` |

These are typed proof limitations, not test failures and not an invitation to infer the missing
edges. The public `CirculationWitnessV1` type is reserved for a future version whose receipts close
all of them. The current adapter never constructs that variant.

If a caller supplies any `SourceFactArtifactCapability` or `ProjectionPublicationCapability`, the
report additionally emits `capability_not_semantically_inspectable`. A capability is a validated
pre-commit input to a store operation. Its existence does not prove that a row committed or that
the persisted semantic bytes were read back. This lane never reconstructs a receipt from a
capability.

## Exact walking boundary

The audit is pure and performs no I/O:

```text
exact spool segment bytes
  + exact DurableIngestBatch bytes
  + exact policy bytes
  + SpoolCatalogReceiptV1
    -> exact segment/batch/policy SHA-256 and length
    -> canonical logical batch digest
    -> store-admission digest
    -> PublicStoreReceiptV1 commit/count/acquisition/gap closure

exact CensusDenominatorRef bytes
  + deterministic CensusInputClosureV1 bytes
  + SourceFactArtifactReceiptV1(family=acquisition_policy)
    -> evidence IDs resolve to the durable source batch
    -> evidence availableAt/commit <= denominator cut
    -> source commit <= denominator known-through < census commit

exact SelectedClusterContext bytes
  + exact MarketStateSnapshotV1 bytes
  + SourceFactArtifactReceiptV1(family=market_state)
    -> context occurs exactly once in the attention branch
    -> event/time/slot/availability/context identity all agree
    -> context is non-retracted and valid at the forcing event
    -> attention fact occurs in the exact market input closure
    -> census evidence survives in the market branch
    -> all market evidence resolves to the same durable source batch

exact ProjectionArtifactV1 bytes
  + exact ProjectionPublicationV1 bytes
  + current durable ProjectionPublicationReceiptV1
    -> every market assertion/observation is retained in projection input
    -> projection result, artifact, input, and publication semantic digests close
    -> source <= census < market <= projection < publication commit order
    -> report three still-open semantic/durable joins
```

Every JSON input is parsed through the bounded duplicate-key/dangerous-key/unknown-field rejecting
boundary. Semantic artifacts must also equal their schema-ordered compact serialization. The
audit refuses substituted bytes before it considers an open-join blocker.

## Digest domains

`DigestDomainsV1` keeps all of these values distinct:

| Domain | Preimage |
| --- | --- |
| `sourceSegmentExact` | exact durable spool-segment bytes |
| `sourceBatchExact` | exact submitted `DurableIngestBatch` JSON bytes |
| `sourceBatchLogical` | store canonical digest material excluding `expected_digest` |
| `sourceStoreAdmission` | logical batch plus normalized store policy |
| `sourceReceiptExact` | exact public spool/catalog receipt bytes presented to the audit |
| `censusArtifactExact` | exact compact `CensusDenominatorRef` bytes |
| `censusInputClosure` | exact compact `CensusInputClosureV1` bytes |
| `marketStateArtifactExact` | exact compact `MarketStateSnapshotV1` bytes |
| `marketStateInputClosure` | exact compact market `input_closure` bytes |
| `projectionResultSemantic` | projection calculator result material |
| `projectionArtifactExact` | exact `ProjectionArtifactV1` bytes |
| `projectionInputClosure` | exact serialized `ProjectionInputClosure` |
| `publicationSemantic` | publication semantic body excluding its self field |
| `publicationExact` | exact compact `ProjectionPublicationV1` bytes presented to the audit |

Receipt byte hashes and selected-cluster byte hashes are also retained. Equality between any two
domains is never treated as proof. In particular, canonical re-encoding plus a semantic
`publicationDigest` does not prove which publication byte string the store admitted. Store V7
already persists `publication_bytes_sha256`; the correct repair is a future versioned public
receipt that echoes that digest and byte length. Frozen V1 must not be widened in place.

## Census closure and the no-disappearing-denominator rule

`CensusInputClosureV1` is deterministic material derived only from the denominator's census ID,
as-of cut, evidence, and coverage evidence. Its exact bytes must match the source/fact receipt's
`inputClosureDigest`. The denominator must:

- have a nonzero eligible count and algorithm-qualified SHA-256 universe digest;
- carry a bounded commit cut;
- contain sorted, duplicate-free, nonempty evidence and coverage evidence;
- use only exact observation/assertion/coverage IDs present in the durable source batch;
- keep every evidence wall/commit clock at or before its denominator cut; and
- obey its parity mode (`product_board_parity_passed` requires a parity receipt;
  `independent_chain_provider` forbids one).

The audit then requires those exact observation/coverage IDs to remain in the market-state input
closure. A source or census row cannot quietly disappear and improve apparent coverage. A missing
row is a refusal, never zero evidence.

The remaining membership blocker is narrower: `CensusDenominatorRef` names
`eligible_membership_artifact_id` but does not contain or type the member rows. Its count and
universe digest therefore cannot establish that the market subject was actually among the
eligible subjects. The repair is an exact, sorted membership artifact with an independently
recomputed count/universe digest and a post-commit `acquisition_policy` receipt—not a caller-supplied
`Vec<ScopeSubject>`.

## Point-in-time cluster and market-state rules

A free-standing cluster hypothesis or selected context is insufficient. The supplied exact
`SelectedClusterContext` must equal the context nested in exactly one
`MarketStateSnapshotV1.attention` fact. That fact's effective reference must also occur in the
snapshot input closure.

The audit repeats the important event-bound invariants at this trust boundary:

- selected attention event ID, event-time interval, chain slot, wall cutoff, and commit cutoff are
  exact matches;
- source availability is no later than selection/event availability;
- the cluster assertion is not retracted;
- half-open wall and slot validity contain the forcing event;
- the selected cluster has at least one wallet member;
- every market effective input was produced and available by the market cut; and
- the attention event mint equals the market snapshot subject.

The source/fact receipt must bind the exact market artifact bytes and exact serialized input
closure, use family `market_state`, and commit after the snapshot's known-through cut. A later
identity/territory/cluster correction cannot enter this old snapshot merely because it exists
now.

## Projection and publication boundary

The projection must validate under the existing finalized projection contract and equal its
canonical exact bytes. Every market effective fact is converted field-for-field into an existing
`EffectiveAssertionRef`, and every market evidence observation must occur in the projection input
closure. This proves that the projection did not omit the market inputs.

It does not prove that the reducer consumed the exact market-state artifact as an artifact. The
current `ProjectionInputClosure` carries effective assertions and observations but no source/fact
artifact reference. Commit ordering and coincident input sets cannot prove an artifact edge, so
the report retains `projection_market_state_artifact_unreferenced`.

The publication must close the projection ID, semantic result, exact artifact digest/length, input
closure, catalog, commit range, and supersession. The same exact receipt bytes are parsed against
both the semantic `joshi-publication` receipt and the frozen public `joshi-admission` receipt, and
all fields must agree. That proves the current semantic receipt, but the separate exact publication
byte domain remains unacknowledged and therefore blocked.

## Refusals and adversarial vectors

Malformed or contradictory inputs return `CirculationError` before a report is emitted. Stable
codes distinguish strict JSON/noncanonical bytes, source byte/receipt or logical-digest mismatch,
store catalog mismatch, census evidence defects, cutoff regression, free-standing/leaky cluster
context, market-state closure defects, projection omission, and publication substitution.

The fixture freezes blocker and refusal vocabulary. Tests exercise:

- one fully valid synthetic prefix reaching exactly the three honest blockers;
- exact source-segment byte substitution;
- duplicate untrusted cluster-context keys;
- a free-standing cluster mutation not present in the market artifact;
- a market input available after the snapshot cut; and
- separation of publication semantic and exact-byte digests.

Focused gates:

```bash
cargo test --locked -p joshi-operational-circulation
cargo clippy --locked -p joshi-operational-circulation --all-targets --no-deps -- -D warnings
RUSTDOCFLAGS="-D warnings" cargo doc --locked -p joshi-operational-circulation --no-deps
cargo fmt --all -- --check
```

The dependency-inclusive strict Clippy gate is green. The receipt audit is split into semantic
header/identity/gap checks and a separate exact admitted-count check so each trust-boundary review
remains narrow without suppressing `too_many_lines`.

## What a root witness may and may not count

Root may count this lane as:

- proof that the named exact prefix artifacts and receipts can be cross-checked without I/O;
- proof that source evidence cannot disappear between denominator and selected market branch;
- proof that the event-bound cluster context is nested and cutoff-valid;
- proof that market inputs survive into a finalized projection closure; and
- a precise schema request for the remaining durable joins.

Root may **not** count it as:

- an end-to-end operational circulation witness;
- proof that the selected subject belonged to the census eligible universe;
- proof that the projection consumed the exact market-state artifact rather than the same inputs;
- proof of the exact publication bytes admitted by V1;
- proof that any capability committed;
- proof of live provider/RPC/store operation, coverage outside the supplied source batch, or a
  prospective non-fixture run; or
- authorization for source acquisition, operator choice, posting/following, transaction
  construction, signing, submission, trading, LP changes, or any economic action.

The next valid step is for the root/store owner to land versioned, post-commit semantic readback
contracts for exact eligible membership, exact market-state artifact consumption, and exact
publication bytes. Until then, `blocked` is the successful and truthful outcome.
