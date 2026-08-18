# Lane 21 — deterministic census-to-hot acquisition policy

Status: **offline deterministic policy and collector-control adapter complete; persistence, live
source control, and provider coverage remain integration-gated**  
Date: 2026-08-17  
Code: [`crates/joshi-acquisition-policy`](../../../crates/joshi-acquisition-policy)  
Fixtures: [`fixtures/acquisition-policy`](../../../fixtures/acquisition-policy)

## Decision

This lane implements W4-03 as a pure append-only reducer between an already committed census and a
collector-owned source-control boundary. It does not crawl, subscribe, authenticate, write the
catalog, choose a trade, or spend money/native units. Its literal authority is
`read_only_no_execution`.

```text
committed census membership + coverage
  + admitted operator/attention/wallet/rule nomination
  + exact resource counters + source health
                       |
                       v
              HotScopeIntentV1
                       |
          deterministic replay/reduction
                       |
       +---------------+----------------+
       v               v                v
 HotScopeDesired  HotScopeDegraded  HotScopeClosed
       |               |                |
       +---------------+----------------+
                       v
   exact fsynced supervisor ControlWrite reservation
                       |
                       v
          inert collector control bytes
                       |
             local adapter receipt
                       |
                       v
              HotScopeAppliedV1

Applied = local control write only
Applied != provider acceptance != source coverage
```

The reducer's useful claim is narrow: given the same exact journal and evaluation snapshot, it
emits byte-identical scope-state records, preserves every cited census denominator under overload,
and never activates a model proposal without a distinct accepted intent.

## Stable record families

The crate emits strict camel-case V1 DTOs under these contract strings:

| Record | Contract | Meaning |
| --- | --- | --- |
| `HotScopeIntentV1` | `joshi.hot_scope_intent/v1` | append-only bounded request/proposal with exact reasons, cutoffs, source operations, fidelity, and budgets |
| `HotScopeDesiredV1` | `joshi.hot_scope_desired/v1` | full per-source desire under the evaluated policy |
| `HotScopeDegradedV1` | `joshi.hot_scope_degraded/v1` | changed or absent per-source desire with ordered reasons and retained denominator closure |
| `HotScopeClosedV1` | `joshi.hot_scope_closed/v1` | terminal expiry/closure for one intent/source/operation |
| `HotScopeAppliedV1` | `joshi.hot_scope_applied/v1` | exact local control command and receipt applied in one collector generation |
| `CollectorControlCommandV1` | `joshi.collector_scope_control/v1` | inert exact apply/remove bytes, after durable attempt reservation |
| `CollectorControlReceiptV1` | `joshi.collector_scope_control_receipt/v1` | local handoff receipt; provider and coverage fields must be literal `not_asserted` |

Every journal record has an occurrence `recordId`, exact decimal-string `recordOrdinal`, timestamp,
and direct predecessor. Occurrence IDs are not content hashes. The journal rejects duplicate IDs,
gaps, changed predecessors, decreasing record time, wrong contract/schema, later references, and a
desired/degraded state after terminal closure. Idempotent retry belongs at the future durable
admission boundary; writing the same occurrence twice into the append log is not a second event.

The reducer does not own storage. `PolicyJournal` validates exact records supplied by an owner; the
W4-00 typed store capability must later persist and resolve these contracts without exposing raw
SQL or letting a caller invent duplicate indexes.

## Intent and knowledge closure

`HotScopeIntentV1` names:

- a public subject kind/key (`mint`, `wallet`, `profile`, `community`, or `territory`), without a
  person, owner, insider, or skill label;
- open and half-open expiry times plus `lastJustifiedAt`;
- the exact requesting occurrence, optional scene, policy occurrence and configuration digest;
- `AsOfCutoff { availableThrough, commitThrough }`, with a mandatory bounded commit for an intent;
- literal `read_only_no_execution` authority;
- sorted, duplicate-free reasons and typed evidence links;
- one or more exact census-denominator closures; and
- sorted per-source `{sourceKey, operationKey, sourceFamily, fidelity, budget}` requests.

Every `EvidenceLink` carries kind, ID, optional SHA-256 digest, `availableAt`, and optional commit
sequence. Intent reasons require committed evidence: each reason occurrence, evidence availability,
and evidence commit must be no later than the intent cutoff. A later event time alone cannot make a
later-known input eligible. The intent also requires an exact policy-occurrence evidence link whose
ID and digest match `policyOccurrenceId` and `policyConfigDigest`.

### Operator acceptance

`ActivationAuthority::OperatorAccepted` contains one boxed `OperatorAcceptanceBinding` with:

- exact operator command ID and command-payload digest;
- exact durable operator-admission receipt ID;
- exact scene ID and view digest; and
- an optional typed `PresentationChoiceBinding`.

The command must be the intent's requesting occurrence, the scene must equal the intent scene, and
matching `operator_command`, `scene`, and `receipt` evidence must exist under the cutoff. Missing any
part refuses the whole journal.

`PresentationChoiceBinding` is optional because the current V1 operator command is scene-bound but
is not itself presentation-complete. When a sibling presentation/choice binding exists, its
presentation digest, optional jointly-present choice-context ID/digest, availability, and commit
must also close under the intent cutoff. When absent, the scope may still be an explicit operator
request, but no consumer may call it witnessed-presentation complete.

### Model proposals

A model-origin intent must use `ProposalOnly`, match its exact proposal occurrence, cite the model
artifact, and include a `model_proposal` reason. Replay emits an explicit
`model_proposal_nonactivating` degraded record with no effective scope. It does not produce a source
control command.

Operator acceptance of a model suggestion is a new, distinct operator-accepted intent that may
cite the prior artifact as evidence. Changing the authority on the model's original intent is
rejected. This keeps proposal, acceptance, and later observation as different occurrences.

## Census denominator retention

Each `CensusDenominatorRef` closes:

- census occurrence ID and kind;
- exact eligible-membership artifact ID;
- exact eligible-universe SHA-256 digest and subject count;
- bounded availability and commit cut;
- typed source evidence and a nonempty typed coverage-evidence set; and
- for a product board, an exact passed parity receipt.

An independent chain/provider census must not carry a product-board parity receipt. A product-board
denominator cannot exist without one. The denominator cutoff must be no later than the intent cutoff.
Reusing a census ID for changed content fails.

The policy output returns the union of exact denominator closures from all intents even when every
hot lane is absent, a source is unavailable, or protected reserves force a stop. Activity labels,
returns, profit/loss, and model scores are intentionally absent from the policy input. They therefore
cannot erase a cold or losing census member. The fixture's adversarial market labels live outside
`PolicyEvaluationV1`, and changing them leaves the decision bytes unchanged.

For W4-11, the exact sibling closure to cite is:

```text
censusId
+ eligibleMembershipArtifactId
+ eligibleUniverseDigest
+ eligibleSubjectCount
+ asOf.availableThrough
+ asOf.commitThrough
+ evidence[]
+ coverageEvidence[]
```

This is a reference closure, not proof that this crate queried membership or coverage. W4-00 must
resolve those IDs/digests/cuts through its validated store capability before admission.

## Exact multidimensional budgets

Every requested source operation contains every local dimension:

- `maxRequests`;
- `maxPages`;
- `maxResponseBytes`;
- `maxProviderCredits`;
- sorted provider-currency caps as `{currency, maxMinorUnits, decimalsEvidence}`; and
- sorted chain-native caps as `{assetId, maxAtoms, decimalsEvidence}`.

Integers are canonical decimal JSON strings. Empty provider-currency or chain-native collections
mean no permission in that class. Every currency/native decimals reference requires an exact digest.
Each configured source has an operation allowlist and an independent maximum envelope. A request
that exceeds any dimension, cites an unavailable currency/asset definition, requests native units
where they are disabled, or names an unallowlisted operation is absent with `budget_refused`; the
policy never clamps a cap and calls the result equivalent. Dimensions do not borrow from one another.

This is a maximum observation budget, not an invoice, purchase, quota expansion, or transaction
authority. W4 S0 should keep provider-currency and chain-native collections empty unless a separate
configuration and authorization review explicitly changes that ceiling.

## Deterministic admission and degradation

Capacity is counted over unique activating subjects. Subjects are ranked only by exact
`lastJustifiedAt` descending and then stable identities. Overlapping intents for one subject do not
consume multiple subject slots. Proposal-only intents consume none. Initial S0 configuration can
therefore set the planned five-mint and ten-wallet limits directly.

Pressure comes from exact queue, spool, disk, and protected-control-reserve counters plus a sampled
time and sorted source-health evidence known by the evaluation. Collector generations likewise
require nonempty source-health evidence known by the evaluation. The reducer computes one ordered
stage:

1. `full` below 50% usable queue capacity;
2. `drop_optional_bodies` at 50%, removing optional exact private bodies and optional media;
3. `slow_refresh` at 75%, additionally raising social/profile refresh to the configured floor;
4. `shorten_hot_leases` at 90%, capping expiry at last justification plus the configured TTL;
5. `denominator_only` when usable queue capacity or the daily spool cap is exhausted; and
6. `stop_before_reserve` when the disk floor or protected control reserve would be crossed.

The maximum of record-queue and byte-queue pressure wins. Queue capacity is calculated only after
subtracting the protected control reserve. Every change is an ordered `DegradationChange` with a
typed reason. Source-unavailable and source-degraded evidence remain separate from capacity and
resource pressure.

Capacity overflow yields `capacity_evicted_least_recently_justified`. It does not inspect high
activity, past returns, winning/losing status, or model rank. A subject can become desired again on a
later evaluation if a new exact justification changes the recency cut; history is not rewritten.

## Restart and collector-control seam

W4-01 freezes pre-I/O identity in `joshi_supervisor::AttemptReservation`. Importing the supervisor
crate here would also import its store-bearing runtime dependency closure, violating this lane's pure
boundary. Instead, `adapt_supervisor_control_reservation` consumes the exact canonical bytes of that
public type and strictly validates/retains:

- supervisor contract and exact reservation digest;
- reservation/installation IDs;
- source and operation keys;
- positive durable generation and positive attempt ordinal;
- literal `ControlWrite` kind;
- exact `CoverageScope`, whose subject must be the policy target record ID;
- exact lower boundary and public/private protection profile;
- reservation wall time; and
- literal `read_only_no_execution` authority.

Noncanonical bytes, unknown keys, wrong kind, wrong ordinal/generation, changed source/operation,
wrong target scope, or changed authority refuse. The resulting value cannot be deserialized or
constructed through public fields; only the strict adapter creates it.

`pending_control_commands` reconstructs the latest semantic state independently from the latest
applied state:

- an active target needs `Apply` if it was never applied, changed target record, or belongs to a new
  generation;
- an absent target needs `Remove` only when an active scope was actually applied in the same
  generation;
- a new connection/generation starts empty, so an already-absent target does not generate a fake
  unsubscribe; and
- a never-active model proposal or capacity refusal creates no control write.

The exact supervisor reservation fields and digest enter `CollectorControlCommandV1`. The command
digest then enters `CollectorControlReceiptV1`. `receipt_to_applied` accepts only matching command,
reservation, source/operation, generation, attempt ordinal, target, adapter version, digest, and a
handoff time no earlier than reservation. It constructs `HotScopeAppliedV1` only when both
`providerAcceptance` and `coverageStatus` are literal `not_asserted`.

A receipt for a control target superseded before handoff is refused rather than appended as stale
applied state. The collector must reserve and apply the latest target instead.

Provider acknowledgement, observed frames, positive coverage, gaps, and authoritative cursors are
later source/store facts. No applied scope record can manufacture them.

## Fixture and gates

`deterministic_scope.json` supplies four synthetic subjects over one exact independent census. With
capacity two, the two newest operator justifications are desired, the oldest is explicitly absent,
and the newest model proposal remains nonactivating. `expected_summary.json` freezes normal and
denominator-only output.

The crate tests prove:

- two replays serialize to byte-identical decisions;
- appending those records and restarting reconstructs no duplicate desired decision;
- exact integer policy output contains no JSON number tokens;
- overload retains the membership/digest/count/coverage denominator and makes all hot scopes absent;
- changing external high-activity/losing/cold labels cannot change policy bytes;
- a model proposal cannot silently become operator accepted;
- expiry produces terminal closure without deleting denominator history;
- desired versus applied state reconstructs across process/source generation changes;
- inactive scopes do not cause spurious remove writes, while same-generation applied activity does;
- missing budget dimensions, product-board parity evidence, command/scene closure, reason
  availability, or bounded denominator commits refuse; and
- canonical supervisor reservation adaptation rejects wrong kind and wrong attempt ordinal.

Targeted gate:

```text
cargo fmt --package joshi-acquisition-policy -- --check
cargo test --locked -p joshi-acquisition-policy
cargo clippy --locked -p joshi-acquisition-policy --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked -p joshi-acquisition-policy --no-deps
```

## Integration requests and remaining gates

No shared root, schema, core, store, source, or supervisor file is edited by this lane. Integration
owners still need to supply:

1. **W4-00 typed admission.** Resolve policy-config, census membership, coverage, command, scene,
   receipt, and optional presentation/choice IDs/digests at the declared availability/commit cut;
   then persist exact append-only records through a generic validated capability.
2. **W4-01 reservation call.** Reserve `AttemptKind::ControlWrite` with the exact policy target
   record ID as `CoverageScope.subject`, preserve source/operation/generation/attempt ordinal, then
   hand the exact canonical reservation bytes to this adapter before queueing control.
3. **Source-specific writer.** Translate inert apply/remove scope into each reviewed source's local
   control format. The writer returns only a local receipt; provider acknowledgement and coverage
   travel through their own evidence path.
4. **Restart witness.** Persist intents, desired/degraded/closed records, canonical reservation,
   exact command bytes, and applied receipts in the collector journal/spool; kill between each arrow
   and prove repeat-never-skip without a false applied or cursor.
5. **W4-11 sibling citation.** Bind the prospective episode to the exact census closure listed
   above and to the exact `HotScopeIntent`/effective-state/applied occurrences. A real wallet or
   topology circulation result remains a separate W4-04 sibling, never a field invented here.

Until those gates pass, this is a deterministic offline control policy—not an always-on collector
and not evidence of Pump product-surface parity, provider coverage, strategy value, or profitability.
