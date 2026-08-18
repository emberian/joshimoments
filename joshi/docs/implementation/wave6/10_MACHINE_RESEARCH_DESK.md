# Wave 6 — machine research desk

Status: bounded deterministic research-design prototype with one exact `N00`/`N01` fixture packet.
It is intentionally a proposal desk, not a data plane, analyst replacement, Glass surface, claim
promoter, or action engine.

## Boundary

`analysis/src/joshi_analysis/wave6_research_desk` accepts only already-admitted point-in-time
`ArtifactDescriptor` values. A descriptor is a manifest identity with provenance digest, as-of and
available clocks, commit sequence, coverage and gap identities, unit, and topology version. It is
not a file handle, SQL statement, provider client, data acquisition request, or live capability.
The package does no I/O and exposes no query, Glass, wallet, signing, transaction, routing,
selection, policy-update, or claim-promotion API.

The only output is a content-addressed `ResearchProposal` with this fixed authority:

```text
read_only_proposal_only_no_query_no_glass_no_action_no_claim_promotion
```

Its fixed claim scope is `research_design_proposal_not_result_or_live_decision`. A proposal may
predeclare an estimand, controls, a feature decomposition, counterexamples, falsifiers, and capped
non-executable experiment manifests. It cannot calculate a result or say that a hypothesis,
strategy, or outcome is true.

## Admission and point-in-time gates

Every proposal embeds one immutable `DeskPolicy`, its canonical `policy_digest`, and all ceiling
fields: information cutoff, coverage/gap rule, unit/topology rule, artifact cap, experiment cap,
and per-experiment and total resource caps. The digest is re-derived from the embedded policy
bytes during validation; a caller cannot retain a policy ID while replacing its budget. This is an
intrinsic freeze over caller-provided policy content, not evidence that a policy ID was registered
or approved in a durable policy store.

Each input must be available no later than the information cutoff and no later than
`hypothesis_locked_at`; its as-of time must precede availability. Inputs must meet the exact
minimum coverage, allowed-gap set, unit, topology ID, and topology version declared in that policy.
Partial, stale, gap, and unsupported coverage do not silently become complete. The current V1
requires `complete` coverage even when a policy has an allowed named gap, making the latter a
forward-compatible audit allowlist rather than a way to smuggle incomplete evidence into a study.

`ArtifactRole.OUTCOME` is rejected from a locked proposal altogether. This keeps observed outcomes
out of hypothesis construction rather than merely asking callers to promise they were not used.
Future-known descriptors are rejected at the information cutoff.

An `Estimand` requires an explicit numerator, denominator, outcome name, and unit. A proposal
requires at least one named control with a measurement and rationale. Features, counterexamples,
and falsifiers have stable identities and deterministic ordering. This prevents an unreviewable
scalar metric, denominator-free rate, or opportunistic metric list from being called a study
design.

## Capped manifests and immutability

Experiments are descriptive manifests only. Each must name a nonempty subset of the proposal's
exact admitted descriptor closure and positive abstract resource units, while `executable` is
permanently false and `query_count` permanently zero. A policy caps artifact count, number of
experiments, each experiment's units, and total units. The desk therefore cannot turn a review
plan into a provider workload, refer to unadmitted evidence, or evade a declared resource budget
by splitting work into manifests.

The proposal exposes four canonical SHA-256 bindings: `policy_digest`,
`evidence_closure_digest`, `commitment_digest`, and `proposal_digest`. The evidence closure digest
is over every retained descriptor byte, including provenance, clocks, coverage, unit, and
topology. The commitment digest is over the full embedded policy and policy digest, locked cutoff,
specification, descriptor closure and closure digest, authority, and claim scope. Proposal identity
then commits to that frozen commitment and creation clock. Replaying identical inputs creates
identical bytes, digests, and ID; the same proposal cannot be appended twice.

## Human review and supersession

`ResearchDeskLedger` is a persistent-value append-only review record: every append returns a new
ledger and leaves the predecessor unchanged. A human must supply their own `human_id`, timestamp,
reason, and disposition (`accept`, `reject`, `hold`, or `supersede`). The desk does not make a
disposition.

Revisions are separately identified append-only `ProposalRevision` records that link a prior and
successor proposal. Ledger validation requires both proposals and their revision time to follow
both proposal creation clocks. It accepts a continuation only when the complete commitment digest
is identical. Consequently a same-ID policy with changed resource limits, a descriptor/provenance
swap, a cutoff change, and a hypothesis or metric/control change all refuse under a supersession
identity. The human-supplied revision reason does not override that refusal.

A changed policy or evidence basis must be submitted as a separate independent proposal, with its
own declared title, hypothesis, and fresh human disposition; it cannot inherit acceptance through a
continuation. The bounded V1 ledger has no cross-lineage promotion mechanism. A human disposition
must likewise follow the proposal creation clock it reviews. These are intrinsic ordering checks,
not durable proof that a person, clock, review, policy registration, or append-only store is real.

## N00/N01 fixture packet

`fixture_packet.py` supplies the first bounded `N02` integration path. It independently:

1. parses the exact compact Rust `Wave6ProgramRegistrationV1` bytes;
2. recomputes the registration self-digest and full document digest;
3. requires zero consumed Wave 5 gates, zero provider/external-mutation budgets, the fixed fixture
   data policy, desk operation list, claim/source/output/side-effect prohibitions, artifact claim
   boundaries, and sorted local symbols;
4. rehashes all six registered artifact schema documents: campaign registration, generic
   known-truth evaluation, Arrow-derived market atlas, protocol known-truth evaluation, and the
   research-proposal and structural known-truth contracts;
5. rebuilds and evaluates the exact eight-case generic `N01` known-truth suite and seven-case
   Pump/PumpSwap/DLMM protocol battery from their pinned raw fixture bytes, plus the three-case
   migration/same-slot/identity-revision structural battery;
6. admits the three evaluations only as separate fixture `DESIGN` descriptors; and
7. produces one deterministic protocol draft for comparing a separately implemented candidate
   against the same frozen 18-case denominator.

The packet binds program and registration identity, all three complete N01 suite/evaluation digests,
the full research proposal, status, authority, claim scope, `executable=false`, and
`query_count=0` under a recomputed packet ID/digest. The proposal's only experiment manifest is
likewise non-executable with zero queries.

The packet authority is:

```text
fixture_inspection_proposal_only_no_query_no_action_no_claim_promotion
```

This join proves deterministic cross-contract fixture closure, not that the registration, schema,
known-truth result, descriptor, or review is store-resolved. The exact N00 fixture consumes no Wave
5 gates. Consequently the packet remains `fixture_inspector`/`protocol_draft`; it cannot become a
`release_inspector`, replication result, admitted prospective protocol, or product action.

## Focused verification

```bash
uv --directory analysis run --locked pytest tests/wave6_research_desk
uv --directory analysis run --locked ruff check \
  src/joshi_analysis/wave6_research_desk tests/wave6_research_desk
```

The adversarial suite covers authority laundering, future-known and outcome-role inputs, coverage
and gap cutoffs, unit/topology mismatch, missing controls or denominators, duplicate proposal
identities, non-executable manifest enforcement, unadmitted experiment evidence, per-experiment
budget escape, deterministic policy/evidence/commitment IDs, review-time ordering, and
outcome-targeted, same-policy-ID budget-replacement, and provenance-swap supersession edits.

The fixture-packet tests additionally cover Rust/Python registration digest parity, exact artifact
schema bytes, unknown/reordered registration fields, provider-budget widening, schema
substitution, deterministic packet construction, exact generic/protocol/structural N01 closure,
raw Pump/DLMM/structural fixture substitution, the 18-case denominator, packet identity, authority,
and evaluation substitution.

## Deferred work

This prototype does not admit actual source rows, persist the ledger, execute a study, fit a
model, determine causality, select metrics from outcomes, communicate through Glass, or promote a
claim. Those need independently authorized source, evaluation, operator, and publication
contracts.
