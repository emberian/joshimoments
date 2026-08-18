# W5-C mechanics capability registry

`joshi-mechanics-capability` is the pure semantic seam for the independent mechanics profiles
described in [the living instrument](../../planning/WAVE5_LIVING_INSTRUMENT.md#11-w5-c--incremental-mechanics-capabilities).
It is intentionally not a store, source adapter, quote engine, transaction builder, wallet, or
execution process. Its status is semantic only.

## Contract

`MechanicsCapabilityRegistry` registers a `ProtocolProfile` and its one bound `SourceId`, then
records `CapabilityEvidence` rows by `CapabilityKind`. Every row carries the explicit
`EvidenceAuthority::UnverifiedSemantic` ceiling: callers cannot obtain a store-resolved or live
qualification token from this crate. The rows are independent. The registry
never manufactures `observed_attempt` from `observed_simulation`, `landed_fill_or_failure` from
an attempt, or `terminal_position_closure` from a liquidation. `record` replaces only the named
row; it does not run a ladder.

The current kinds are:

```text
exact_math, coherent_real_state, mark, marginal_quote, size_quote,
observed_simulation, observed_attempt, landed_fill_or_failure,
whole_position_liquidation, terminal_position_closure, publication, calibration
```

`EvidenceStatus` is one of `attained`, `refused { reason }`, `pending_opportunity`, or
`unavailable { reason }`. Refusals and absence are retained as statuses, not converted to zero or
negative performance. Quote rows retain the `QuoteId` even when the size path is refused.

## Evidence closure

Every row binds an `EvidenceBinding` containing:

- source and protocol-profile IDs;
- state observation, quote, attempt, fill, liquidation, position, publication and calibration
  IDs where the named kind requires them;
- an `EvidenceHorizon` with the full domain `AsOfVector`, explicit finality, coverage state and
  named coverage gaps; and
- an optional source/build `ValueDigest`.

`EvidenceBinding::validate_for` rejects missing IDs and rejects a source that is absent from the
as-of source vector. `EvidenceHorizon::new` rejects duplicate gap IDs, a gapless complete state
that carries gap IDs, and a gap state without a named gap. An attained row cannot use unknown
finality. An exact-math row requires a state observation and exact profile/build digest; mark,
coherent-state, simulation, liquidation and terminal rows require a state observation; landed
evidence requires an attempt plus either a fill ID or an explicit failure ID; terminal closure
also requires a terminal-closure receipt ID. These checks close identity and epistemic joins but
do not claim that the underlying source was live or that a fill occurred.

## Claim checks

Consumers name their own prerequisites with `ClaimPrerequisite::attained` or
`ClaimPrerequisite::strict`. `MechanicsCapabilityRegistry::check_prerequisites` returns every
failure (`unknown_profile`, `missing`, status, finality, or coverage) in `ClaimCheck`; it never
collapses a partial vector into a global Wave 5 gate. The result is only a semantic preflight;
`ClaimCheck::semantically_satisfied` must not be read as durable qualification. A strict
prerequisite asks for finalized,
complete coverage. A descriptive claim can ask only for an attained row and retain its explicit
coverage/finality in the output.

## Open joins and ceiling

This crate does not prove any of the following, and no fixture below is evidence for them:

- source bytes were admitted by SQLite/CAS or remained retained after a crash;
- market-math or liquidity calculations are correct for a provider's deployed profile beyond the
  profile/source references supplied by the caller;
- a simulation was attempted, an attempt landed, a fill was finalized, or a position closed;
- a publication was mounted by Glass or a calibration row was independently scored; or
- any capability authorizes transaction construction, signing, submission, liquidity deployment,
  policy, or economic action.

Those joins belong to the store/source/projection, witnessed-attempt, and research lanes. A
naturally occurring LP management opportunity is represented as `pending_opportunity` until a
separately bound observation arrives.

The adversarial fixture in `fixtures/mechanics-capability/adversarial.json` demonstrates that a
simulation row does not satisfy an attempt prerequisite, and that a refused size quote keeps its
quote identity and refusal reason.
