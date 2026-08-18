# Lane 22 — strict market-state circulation

Status: **offline reducer and adversarial contract complete; real-source canary and publication
registration remain gated**  
Authority: `read_only_no_execution`  
Code: [`crates/joshi-market-state`](../../../crates/joshi-market-state)  
Fixtures: [`fixtures/market-state`](../../../fixtures/market-state)

## Outcome and boundary

This lane adds a narrow, store-backed reducer for the four market-context streams required by
W4-05:

| Stream | Admitted content | Authority that is deliberately preserved |
| --- | --- | --- |
| social/product | callout, community, follow, content revision, identity-link, and transition occurrences from `joshi-attention` | source protection domain, epistemic class, exact observation, coverage, gaps |
| lifecycle | create, complete, migrate, creator, fee configuration, and fee-share facts or product hints | finalized chain fact and provider hint are different enum variants |
| pool state | one coherent Pump curve, canonical PumpSwap, or selected DLMM position/pool account closure | exact account roles, decoder profile, bytes digest, observation, slot, finality, token extensions, unsupported fields |
| attention | one marked forcing event and the identity, territory, and cluster versions selected for that event | selected-as-known references, witnessed presentation when present, response coverage, explicit response censoring |

The streams remain distinct stored assertions. They join only when `MarketStateReducer` receives a
`MarketStateQuery` naming every semantic key and an explicit four-dimensional cut:

```text
valid_at
AND available_at <= known_by
AND available_commit <= known_by_commit
AND produced_commit <= known_by_commit
AND exactly one effective store branch at known_by_commit
AND applicable finalized slot/finality predicate
```

There is no “latest” method in the reducer seam. `EffectiveFactReader` exposes only
`effective_assertions_as_known(key, cutoff)`, and its production implementation delegates to the
existing historical `SqliteStore` query. Zero branches is missing; two effective branches is
ambiguous. Neither becomes a winner by ordering.

The accepted `MarketStateSnapshotV1` is a source/fact artifact input for W4-06 publication. It
contains the exact query cut, sorted assertion IDs, semantic keys, produced commits, value digests,
supersession links, per-input availability, and observation/source/coverage/gap/protection closure.
`snapshot_store_capability` serializes the exact artifact and input closure, computes both SHA-256
digests, refuses public classification over any private/restricted input, and returns a V7
`SourceFactArtifactCapability` with family `market_state`. It neither opens the store nor commits a
row. The W4-00/W4-06 transaction boundary owns `commit_source_fact_artifact_v1` and mapping its
post-commit result to `SourceFactArtifactReceiptV1`.

## Capture time is not valid time

`CaptureAttestation { started_at, ended_at, acquisition_id }` says when direct or companion bytes
were captured. It is retained beside the fact. It is never passed to `ValidInterval::contains`.

A social occurrence with an exact or bounded source event clock receives a half-open source-event
interval. A missing/not-applicable source clock receives `capture_attestation_only` and no valid
interval. The reducer refuses that value for a point-in-time join even when the requested instant
falls inside the capture window. A later object-version resolver may append an assertion with a
real source-object validity interval; it may not mutate the capture into one.

## Attention and later-known context

The attention adapter first validates the complete existing `AttentionDataset`. It then extracts
only:

- the exact forcing input;
- the marked event;
- the identity, territory, and cluster versions referenced by that event;
- actually bound presentation context already present on the event; and
- response rows belonging to the event, retaining each row's coverage and censoring.

The resulting assertion's wall availability is the maximum of event/context availability,
response availability, and every response analysis cutoff. Thus a response-bearing branch cannot
enter an event-time scene. The initial event branch contains no post-anchor outcomes; a later
superseding branch may carry covered/censored responses and becomes selectable only at its later
store commit and wall cutoff.

At reduction the selected identity and territory must be both valid at `valid_at` and known at the
wall/commit cut. Cluster context must additionally carry
`latest_effective_known_for_exact_cut`, source and selection availability, and a containing slot
interval when one exists. A later assertion may supersede the stored attention fact, but the store
query at the old commit still selects the old branch. The adversarial fixture proves that a future
identity correction cannot enter the old artifact.

The row remains a `marked_forcing_event_no_causal_claim`. No adapter or snapshot type encodes a
treatment effect.

## Lifecycle authority

`adapt_lifecycle_fact` is the only public constructor for the strict lifecycle envelope:

- `FinalizedChain` requires `finalized_chain_slot`, an exact `ChainPoint` with `finalized`
  commitment, and matching observation/source evidence.
- `ProductHint` forbids a chain point and forbids the finalized-chain validity basis. A product
  “migrated” badge remains a provider hint even when it agrees with chain state.

The reducer repeats these checks at the trust boundary. Finalized lifecycle occurrences may be at
or before the query's finalized cut; a pool state is stricter and must equal the requested slot.

## Coherent pool closures

`adapt_pool_bundle` validates all account roles before invoking any arithmetic kernel. Every
account must have a unique account identity, the bundle slot, finalized commitment, retained data
digest, named decoder profile, and no unsupported price/inventory-relevant field.

Required roles are:

| Family | Exact required closure |
| --- | --- |
| Pump curve | curve, global configuration, fee configuration, base mint |
| canonical PumpSwap | pool, global configuration, fee configuration, base/quote mints, base/quote vaults |
| selected Meteora DLMM position | position, LB pair, fee configuration, X/Y reserves, X/Y mints, at least one bin array; bitmap extension is permitted when decoded |

Decoded state observation IDs must resolve to the matching role in the closure. Mint definitions
retain token program, decimals, decoded extensions, and unsupported extensions. DLMM bin state
retains exact Q64.64 price, supply, position share, pending fee/reward state, and account evidence.
Any unsupported account field, token extension, position layout/lifecycle, or accrual field refuses
the whole bundle.

Only after closure admission does the adapter call the existing kernels:

- `PumpCurveState::mark` or `PumpSwapState::mark` produces a ratio-only reserve mark;
- `DlmmPositionState::inventory` produces exact withdrawal inventory with fees kept separate.

The artifact has no quote request, fill, price-impact promise, liquidation value, transaction
builder, signer, or submission type. `quote_state_admitted` merely records that the exact supported
trading-state closure passed this boundary; it is not a quote. Missing, mixed-slot, merely
confirmed, noncanonical, or unsupported input produces a typed refusal and no mark/inventory.

## Refusal and deterministic gates

The reducer returns `MarketStateOutcome`, so refusal is a durable candidate artifact rather than an
exception callers can accidentally coerce to zeros. Stable refusal codes distinguish missing and
ambiguous store state, wrong contract/stream/subject, capture-only time, invalid valid/known cuts,
future commits, missing evidence, invalid selected attention context, and pool
incomplete/mixed-slot/nonfinal/unsupported/kernel-refused cases.

The current tests prove:

- byte-deterministic canonical JSON for one accepted four-stream artifact;
- exact observation/source evidence closure and read-only authority;
- old-cut immunity to a later superseding identity correction;
- capture attestation cannot supply validity;
- competing effective branches refuse;
- missing fee account, mixed slot, confirmed-only account, and unsupported decoded field refuse;
- complete Pump curve, canonical PumpSwap, and DLMM closures reach their existing kernels; and
- `SqliteStore` implements the narrow historical read seam; and
- an accepted artifact builds the exact V7 market-state capability while public protection over a
  private input refuses.

Run the focused gates with:

```bash
cargo test -p joshi-market-state
cargo clippy -p joshi-market-state --all-targets -- -D warnings
cargo fmt -p joshi-market-state -- --check
```

## Honest remaining gates

The fixtures are synthetic and reuse the validated synthetic attention corpus. They test the
contracts; they do not satisfy W4-05's real-source occurrence gate. Before this lane is called
operational, a separately authorized bounded canary must trace one retained occurrence of each
enabled family through its real adapter, durable assertion, snapshot, and evidence readback. A
family without an admissible source is disabled explicitly with an empty key set; it is not filled
from a neighboring provider or presented as covered.

Upstream byte decoders remain responsible for pinning program/layout versions and for retaining
raw observations. This crate admits their typed closure but does not claim that a fixture decoder
matches current deployed programs. Downstream deterministic publication and source/fact artifact
receipt registration remain W4-06/W4-00 work. Authentication, broad live collection, Glass schema,
causal modeling, and every form of execution authority remain out of scope.
