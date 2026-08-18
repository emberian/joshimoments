# Wave 6 authority and fixture registry

Status: `N00/W6-0` authority/registry foundation and exact V11 store persistence implemented at
`unverified_semantic_fixture_only`; no Wave 5 gate-resolved program or Wave 6 operational release
exists.

The implementation lives in
[`crates/joshi-wave6-registry`](../../../crates/joshi-wave6-registry). Its checked-in exact
registration is
[`fixtures/wave6/program_registration_v1.json`](../../../fixtures/wave6/program_registration_v1.json).

## What is frozen

`Wave6ProgramRegistrationV1` closes one fixture program over:

- exact source-tree, build, environment, and configuration digests;
- the sole public authority `read_record_replay_propose_shadow_only`;
- the sole public ceiling `unverified_semantic_fixture_only`;
- caller-declared Wave 5 gate references that remain explicitly unverified;
- versioned artifact kinds, exact schema digests, H0–H5 rungs, and permitted/prohibited claims;
- a local symbol table with explicit units and clocks;
- fixture-public privacy, retention, deletion, and export classes;
- bounded compute/read/attention/artifact budgets with provider and external-mutation budgets fixed
  at zero;
- a closed list of local research-desk operations; and
- mandatory prohibited sources, outputs, claims, and side effects.

The self-declared registration digest is recomputed over exact compact JSON digest material. The
full document additionally has one canonical encoding: compact JSON plus one trailing newline.
Unknown fields, alternative whitespace, uppercase/malformed digests, collection reordering,
missing prohibitions, and a reclosed nonzero provider budget all refuse.

The checked-in registration deliberately consumes no Wave 5 gates. Adding a caller-authored gate
reference cannot raise its ceiling.

The six registered fixture kinds cover the checked campaign-registration, generic known-truth
evaluation, market-atlas, Pump/PumpSwap/DLMM protocol known-truth evaluation, research-proposal,
and migration/order/identity structural known-truth schemas. All three evaluation kinds are
limited to H1 deterministic fixture results, ambiguity sets, or refusals: none permits a market,
estimator-performance, quote, route, identity, causal, or economic claim. Registering the campaign
schema grants only `fixture_campaign_protocol_only`; it explicitly prohibits any prospective
result or operational campaign inference. The independently bounded N03 contract is documented in
[11_PROSPECTIVE_CAMPAIGN_CONTRACT.md](11_PROSPECTIVE_CAMPAIGN_CONTRACT.md).

## Artifact lineage and claim grammar

`ArtifactDagV1` binds the exact program and registration digest, registered artifact kinds,
distinct occurrence IDs and content digests, typed information/production clocks, and exact
parents. Parents must already occur in the topological sequence, match their content digest, and
not be later than the child. The artifact budget is rechecked. A public DAG remains fixture-only.

`ClaimLanguageV1` has no free-form inference channel. Its statement must equal the exact
`permittedClaim` registered for the artifact kind, and its verb is mechanically fixed by rung:

| Rung | Only accepted statement family |
| --- | --- |
| H0 | declared boundary fact |
| H1 | deterministic result or refusal |
| H2 | observation-policy-scoped description |
| H3 | calibrated conditional estimate |
| H4 | compatible equivalence class only |
| H5 | hypothetical read-only proposal |

Causality and economic authority are always `not_claimed`; identity meaning is unavailable except
for the explicit H4 equivalence-class form. This is an intrinsic language check, not evidence that
the referenced artifact or claim is true.

## Append-only fixture dispositions

`FixtureDecisionLedgerV1` can record only `retain_contract_only`,
`promote_fixture_roundtrip`, `park`, or `reject`. It closes every decision over an exact DAG
artifact/evidence set, requires an exact predecessor per artifact, refuses branches and clock
rollback, and permits fixture-roundtrip promotion at most once. There is intentionally no
`store_resolved`, operational, prospective, live, product, or economic decision variant.

## Campaign lifecycle

`CampaignLifecycleV1` implements the exact generic Wave 6 state machine without pretending to
implement a campaign runtime:

```text
draft_exploratory
  -> preregistered
  -> enrollment_frozen
  -> running
  -> sealed
  -> matured | censored | aborted_apparatus
  -> adjudicated
  -> continue | revise_as_new_campaign | park | reject
```

The genesis, predecessor, prior state, strict clock order, definition digest, and frozen
commitment are revalidated on every transition. The commitment must first appear at
`enrollment_frozen` and remain byte-identical. A revision must name a distinct successor campaign;
it cannot silently edit the current one. Apparatus abort remains a distinct state and cannot be
recast as a negative scientific result.

All state names are caller-declared fixture semantics. In particular, `preregistered`, `sealed`,
`matured`, and `adjudicated` do not mean that a durable registration, sealed journal, outcome,
coverage closure, or adjudication receipt exists. The crate performs no enrollment, assignment,
sensing, presentation, evidence collection, reveal, scoring, or execution.

## Authority boundary

The registry crate has no dependency on `joshi-store` and defines no durable receipt, commit
sequence, provider client, filesystem path, campaign runner, Glass hook, wallet, reservation, or
execution API. Its validated wrappers expose their exact bytes and document digests but cannot
upgrade their semantic ceiling.

The one-way store adapter in `joshi-store` now persists and independently reparses the exact N00
document under the V11 append-only table. Store commit order, commit time, batch identity, exact
document bytes and both semantic/document digests survive read-only reopen. The adapter accepts
only the checked contract shape with an empty Wave 5 gate set and zero provider/external-mutation
budgets. This is durable storage of an unverified fixture contract, not resolution of the gates it
deliberately omits. See [12_STORE_PROGRAM_REGISTRY.md](12_STORE_PROGRAM_REGISTRY.md).

Per the Wave 6 master plan, a future sole-store adapter may be considered only after the exact
external gates close. The current offline Wave 5 G0 component evidence does not satisfy `W5-G1`,
so no `W6-X1`, market-field, response, operator, sensing, routed, or production-release adapter is
authorized by this work.

## Verification

The focused suite covers exact fixture roundtrip, unknown/noncanonical JSON, digest and artifact
substitution, provider-budget/missing-prohibition widening, strict digest wire form, DAG
topology/time closure, duplicate content/unknown kind refusal, rung/wording substitution, and
decision branching, lifecycle skipping/branching, and frozen-commitment mutation:

```bash
cargo test --locked --offline -p joshi-wave6-registry --all-targets
cargo clippy --locked --offline -p joshi-wave6-registry --all-targets -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --locked --offline \
  -p joshi-wave6-registry --no-deps
```

The honest current statement is:

```text
Wave 6 has an exact, restart-safe fixture-only program registration,
artifact-lineage validator, typed H0-H5 claim grammar, and append-only fixture
disposition ledger. Its program has no resolved Wave 5 gates and therefore no
operational release, prospective campaign, live/product conclusion, or economic authority.
```
