# Wave 6 point-in-time market atlas

Status: **implemented as a fixture-scale, read-only analysis prototype**

The implementation lives in
[`analysis/src/joshi_analysis/wave6_market_atlas`](../../../analysis/src/joshi_analysis/wave6_market_atlas).
It is a pure Arrow-table reducer: no network, store mutation, CLI, model fitting, inference of
missing facts, or economic action is present. Every result names the machine-readable semantic
ceiling `caller_fed_unverified_semantic_fixture_only`.

## Purpose and claim boundary

The atlas is a typed H2 snapshot/trajectory instrument for the stratified state described in the
[field-model corpus](../../research/field_models/README.md) and the Wave 6 plan's `W6-F` lane. It
keeps the following native components separate:

- mint lifecycle and canonical-venue selection;
- canonical venue state and a typed price carrier;
- liquidity topology and its epoch/version;
- wallet/cluster flow with identity versions;
- caller/product-surface attention; and
- operator episode, portfolio, and flat-watch state.

It intentionally emits no market `pressure`, `energy`, `quality`, `conviction`, or other scalar
truth. It neither identifies common control from a cluster label nor treats render evidence as
attention. The output claim scope explicitly says it is not a causal or strategy claim. This is a
descriptive point-in-time closure that can remain useful if later field compression adds nothing.

## Exact point-in-time contract

`AtlasCut` names all three required coordinates: `state_time`, `knowledge_cutoff`, and
`as_of_commit_seq`. A source row is eligible only when it is valid at the state time, available no
later than the knowledge cut, committed no later than the commit cut, and not retracted by that
knowledge cut. A later correction therefore cannot revise an older atlas cut.

Each source relation has an exact Arrow schema and carries a stable `record_id`, `source_id`,
`source_version_id`, `native_event_id`, component and component-version identities, half-open
validity interval, availability/retraction clocks, commit sequence, coverage window/gap, and native
fields. The raw transport schema permits nullable caller-fed semantic fields (including validity
bounds and identities), while retaining nonnullable `available_at` and `available_commit_seq` as
the minimal knowledge/commit gate. The universal source/index schema is checked before a cut is
evaluated. A row is first gated solely by those knowledge fields; only then are its validity bounds,
payload, coverage, native-identity, duplicate, and conflict semantics checked. A malformed future
row consequently cannot change an earlier artifact's success, content, or ID; when that same row
becomes known at a later cut, it refuses rather than being treated as absent.

For an observed component, its generic identity is required to equal the native identity and
version: mint/lifecycle, venue/state, topology-element/topology-version, wallet/wallet-identity,
caller/caller-identity, or episode/watch-version as applicable. The native source/event/version
tuple is unique within a component relation at a cut. The snapshot retains these three references;
it is not merely a payload digest projection. The reducer refuses duplicate occurrence or semantic
identities and refuses a cut that would select two versions of one component. It never uses a
mutable "latest" selection.

The snapshot contains source-record identity and a digest of the native payload rather than a
flattened feature value. A trajectory is an ordered list of these exact snapshots for one subject,
component kind, and component ID. Topology transitions are therefore visible as a version change,
not smoothed across an epoch boundary.

## Units, prices, and missingness

Canonical prices are admissible only as a complete `quote_atoms_per_base_atom` carrier: integer
numerator in `quote_asset_atoms` and positive integer denominator in `base_asset_atoms`. The module
deliberately does not normalize last-trade, reserve, chart, route, or quote objects into a common
price. Wallet flow, liquidity, and portfolio atom carriers similarly require `base_asset_atoms`
when present.

Coverage status is one of `observed`, `gap`, `unknown`, or `not_applicable`. A gap or unknown row
must name a gap ID. It remains a row in the snapshot and makes its trajectory a
`path_with_declared_nonobservation`; it is never synthesized as an empty collection or zero value.
Absence of a row also has no zero/healthy-coverage meaning.

## Reproducibility and tests

For every cut the reducer hashes only source rows eligible at that exact cut, in canonical record
order, to obtain a logical input digest and deterministic input/snapshot IDs. Trajectory IDs hash
their ordered snapshot membership. Reordering input rows is therefore inert, while a known-at-cut
correction or identity/version change changes the relevant artifact identity.

The focused adversarial suite covers future-known corrections, nullable future semantic-index rows
that are inert earlier and refuse once known, topology transitions, unknown-state retention,
missing price denominators, mixed price
carriers/units, native component/source-version substitution, duplicate occurrences/versions, and
input permutation stability:

```text
pytest analysis/tests/wave6_market_atlas -q
ruff check analysis/src/joshi_analysis/wave6_market_atlas analysis/tests/wave6_market_atlas
```

This remains caller-fed `UnverifiedSemantic` fixture material. A typed source ID, event ID, version,
coverage status, clock, digest, or identity relation is an intrinsic consistency check over supplied
rows—not proof that the caller resolved it from retained source evidence. This is not an operational
Wave 6 release adapter. A later store-resolved release must provide the plan's campaign-local
topology, coverage, source-manifest, and Wave 5 gate closure before the same contract can be used
beyond fixtures.
