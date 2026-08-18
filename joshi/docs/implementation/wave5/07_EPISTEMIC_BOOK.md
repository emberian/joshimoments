# Wave 5 epistemic book: pure contract settle

## Status and ceiling

`joshi-epistemic-book` is a pure, strict semantic contract implementation for the B0–B4
epistemic-book spine. Its honest implementation status is
`contract_draft_fixture_validated`. It does **not** currently establish
`forecast_before_issue_deadline`, durable mutual blindness, admissibly adjudicated, prospectively
scored, repeated prospective support, or ensemble-qualified maturity. No public caller can upgrade
that ceiling: the durable occurrence, submission, adjudication, and support capability types have
private fields and no public constructor. A future private adapter inside this crate must mint them
only after resolving exact durable store rows, receipts, namespace visibility, reveal events,
evidence closure, and historical membership.

The unverified `Resolved*PortV1` values are deliberately only caller-owned projections for
contract testing. They grant no maturity and cannot produce any `Qualified*` marker (those markers
and public qualification functions do not exist). Semantic ensemble preflight returns either
explicit incompatibility or `BlockedMissingDurableProof`; it never returns eligibility. Exact
Brier arithmetic is available as `preview_brier_score`, whose result carries the same explicit
non-promoting status. Artifact-producing score and ensemble APIs require the opaque durable
capabilities, so fixture code cannot launder timestamps, receipts, or empty visibility lists into
prospective evidence.

## Implemented contracts

- Versioned `ClaimDefinitionV1` with exact consecutive prior-object supersession, typed claim
  families, ordered outcome spaces, scoring/adjudication/support contracts, typed mechanics
  prerequisites and powerless H3 authority.
- Frozen `ClaimOccurrenceV1` with exact definition/scene/universe references, immutable evidence
  manifest digest, coverage/gaps, typed capability closure, conditioning, and the exact B0 clock:
  `max_input <= info_cutoff <= occurrence_commit <= issue_deadline <= target_origin < horizon <
  knowledge_deadline`. Revision occurrences require the exact prior object and a later information
  cutoff.
- A prospectively declared sealed-journal namespace, sorted eligible first-round forecasters,
  required component count, and reveal-not-before clock. First-round submissions must belong to
  that registered set; revisions bind the exact prior forecast and disclose visible parents. This
  semantic declaration does not substitute for the still-required durable sealed namespace.
- Strict forecast payloads, exact million-ppm categorical distributions, immutable producer
  lineage, exact occurrence-frozen input digest, and no acquisition, presentation, reservation,
  transaction, signing, or submission authority.
- Append-only adjudication versions with distinct observed, healthy-no-event, frozen-replay,
  administrative/source-loss/interval censoring, left truncation, competing event,
  route/liquidation refusal, intervention invalidation, conflict, unsupported and open states.
  Healthy no-event requires nonempty complete horizon evidence/coverage. Frozen replay is refused
  outside its enabled family and requires complete terminal evidence plus terminal-manifest,
  replay, and whole-position-liquidation prerequisites.
- Exact categorical Brier arithmetic and baseline increment. Every semantic and opaque dependency
  must bind the same exact definition/occurrence; cross-occurrence substitution is refused.
- Support/calibration summaries retain the complete denominator. Repeated prospective support
  currently requires at least forty named, unique occurrences, partitioned exactly across at least
  two chronological nonadjacent windows with at least twenty scores each. Each membership names
  its score, occurrence, adjudication and outcome-availability clock; score reuse, occurrence
  double-counting and post-embargo outcomes are refused. When considered for a current occurrence,
  every embargo and outcome availability must be strictly earlier than that occurrence's
  information cutoff.
- A deterministic equal-weight, unique-primary-lineage, shadow-only ensemble contract. Semantic
  preflight rejects wrong occurrences, non-first-round/noncategorical components, duplicated
  submissions or lineages, insufficient preregistered components, and current/future support.
  Actual construction additionally requires opaque store-derived occurrence, support and sealed
  submission capabilities and proves all components committed before the earliest permitted
  reveal.

Initial live-capable definitions cover spot competing risk and liquidity survival. Runner
competing-risk and frozen branch value carry their mechanics prerequisites. LP schedule and routed
liquidity definitions are typed but occurrences remain disabled until schedule/state,
external/self-flow, exact inventory, whole-position liquidation and replay capabilities close.

## Store integration required for promotion

The integration must privately resolve and attest all of the following before any maturity label
can change:

1. Exact occurrence canonical bytes/digest, atomic commit receipt/time, scene and universe, every
   frozen evidence row with availability/validity, coverage/gaps, and typed capability rows.
2. An occurrence-scoped sealed forecast namespace; exact submission bytes/digest and commit receipt
   before the issue deadline; store-derived precommit visibility; proof every eligible first-round
   component was sealed before any reveal; and the single durable reveal occurrence/time.
3. Exact adjudication bytes/digest, durable commit receipt/time, eligible evidence available by K,
   complete horizon/terminal coverage or honest unresolved disposition, and exact correction
   lineage.
4. The complete eligible occurrence denominator; exact score membership in disjoint chronological
   windows; adjudication, coverage, gap and calibration derivation; and embargo/release clocks
   strictly before any target occurrence that consumes the support.

The requested shared identity ports are `ClaimDefinitionId`, `ClaimOccurrenceId`,
`ForecastSubmissionId`, `AdjudicationId`, `ScoreId`, `SupportSummaryId`, and `EnsembleId`. This
crate uses validated `StableString` identities at its boundary until those shared newtypes exist;
it does not edit shared crates or schemas.

## Evidence and witnesses

Canonical fixture:

- `fixtures/epistemic-book/spot-claim-definition.v1.json`
- SHA-256:
  `4f5e5144456fe91ef3bc529ce39cbd264294aef3635760f284a40368e67b1ba2`

Focused tests exercise canonical/strict decoding, authority widening, late evidence, exact
definition and revision lineage, frozen-input substitution, sealed-journal membership,
cross-occurrence score refusal, honest censor/conflict/refusal/unsupported states, healthy/replay
closure, exact Brier preview, support membership/threshold/embargo rules, and lineage-capped
ensemble preflight. No positive test constructs a store receipt or durable capability.

Witness commands:

```text
cargo test -p joshi-epistemic-book --locked
cargo clippy -p joshi-epistemic-book --all-targets --locked -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc -p joshi-epistemic-book --no-deps --locked
```

At this settle all thirteen focused tests pass, Clippy is warning-free, and rustdoc builds with
warnings denied. The crate owns no provider, store, wallet, portfolio, presentation, acquisition,
transaction, signer, submission, or economic authority.
