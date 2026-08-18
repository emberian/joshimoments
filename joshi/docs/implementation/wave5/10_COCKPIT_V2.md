# Cockpit V2 publication closure

`joshi-publication` now exposes a pure V2 semantic-manifest waist. It does not own a store, route,
CAS, provider, or UI authority. Store adapters may use the DTOs only after their own exact durable
foreign-key checks.

## Manifest closure

`CockpitV2ManifestV1` requires a typed surface-profile reference, observed-universe reference,
exact knowledge/commit/chain cutoff, sorted public `CockpitV2SourceFactRefV1` values, sorted
membership, coverage and gap references, rendered subjects, omissions, and explicit ordering and
pagination policies. A source fact with `app_private`, `authenticated`, or `raw_private_bytes`
protection is refused before publication; no source-body bytes are present in the DTO.

Every timestamp and optional commit sequence is checked against the cutoff. References are sorted
and duplicate-free. Coverage states (`complete`, `partial`, `stale`, `unknown`, `unavailable`,
`refused`) carry sorted `fact_ids`, the exact eligible-subject denominator, and field lists; every
field must equal the union from its referenced public fact set, so every profile/source × subject
cell remains explicit. A complete scope cannot have a gap. Typed gaps remain visible rather than
being collapsed to absence.
The universe digest is recomputed from its domain, ID, count and sorted eligible subjects. The
manifest requires memberships to cover every eligible subject exactly once and rendered plus
omitted subjects to form an exact disjoint eligible partition. Public V2
DTOs carry an explicit `unverified_semantic` ceiling until a private atomic store adapter resolves
all evidence and receipt identities.

## Digest domains and prepare

`computed_semantic_digest()` hashes the semantic material. `computed_container_digest()` hashes
the canonical container material with a zero self-slot. `canonical_bytes()` is the full serialized
manifest with the actual container digest. These are intentionally distinct domains. The
`PreparedCockpitV2` object retains semantic bytes, container bytes and a checkpoint, and performs
no I/O; preparation cross-binds every checkpoint profile/universe/cutoff/digest field to the
manifest. Strict canonical readback helpers reject unknown fields or noncanonical bytes.

## Commit/head crash semantics

`finalize_cockpit_v2` constructs a complete immutable publication only after preparation. The pure
`CockpitV2CommitStage` model is monotonic: `prepared -> committed -> head_published`. A crash before
commit leaves the prior head; after body commit the complete new body is queryable while the prior
head remains selected; after head publication the new complete head is selected. `CockpitV2HeadV1`
binds the exact publication ID, digest and commit sequence.
Stage transitions cannot skip a stage or accept an arbitrary head digest.

## Integrator surface

Use `prepare_cockpit_v2`, `finalize_cockpit_v2`, `CockpitV2QueryV1::validate_loaded`,
`CockpitV2HeadV1::from_publication`, and `CockpitV2CommitStateV1::advance`. The canonical semantic
vector is [`cockpit_v2_manifest_v1.json`](../../../fixtures/publication/cockpit_v2_manifest_v1.json).
