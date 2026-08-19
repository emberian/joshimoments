# Wave 6 store-resolved input census

Status: **useful partial**. V20 closes one genuine offline W5 C0 discovery occurrence into the W6
fixture program through sole-store construction, exact retry, and read-only restart. It is not a
Wave 6 market atlas, field release, empirical result, product surface, or live source.

## Exact boundary

Migration `0020_wave6_store_input_census.sql` adds one append-only
`wave6_store_input_census_v1` row per W6 program. The caller supplies only two prior identities and
an idempotency batch. `joshi-store` independently reloads and rederives:

- the exact canonical W6 program registration;
- the exact retained W5 source occurrence and its original public V10 catalog-admission receipt;
- its full source descriptor bytes, fact set, eligible denominator, memberships, coverage, gaps,
  omissions, input cutoff, protection, and store commit; and
- nonempty facts and coverage plus both a hot and a cold-control subject.

The store then constructs the V20 document itself, allocates the commit, reparses the exact bytes,
reloads both priors, rederives every count and digest, and refuses update/delete or a second source
for the program. A later catalog migration does not invalidate the immutable V10 source receipt:
readback validates that frozen receipt version instead of incorrectly comparing it to the latest
catalog version.

The Core command is:

```bash
cargo run --locked --offline -q -p joshi-core -- \
  wave6-store-input-census --state /tmp/joshi-wave6-input.manual/catalog
```

On a fresh state it first executes the real offline W5 G0 component, migrates that same catalog
through latest V22, commits the frozen zero-provider/zero-mutation W6 program, commits the V20
store-built input
census, retries it exactly, and reopens it read-only. A whole-command retry reuses the same binding,
digest, and commit sequence.

The bounded runner is:

```bash
./scripts/wave6-store-input-census-readiness
```

It retains a versioned witness under `/tmp/joshi-wave6-input.*`.

## Hard ceiling

The exact semantic ceiling is
`store_resolved_offline_fixture_input_census_only`, with claim scope
`mint_discovery_input_census_not_market_atlas_field_release_causal_strategy_or_execution`.

The two facts are Pump discovery `mint` facts for the fixture subjects already resolved by W5.
They do not supply the venue state, liquidity topology, wallet state, caller/social state, episode
state, typed prices, or source-native provenance required by the six-stratum W6 market-atlas
contract. V19's market-atlas artifact remains a separate caller-fed fixture. Accordingly every
report and witness fixes `storeResolvedMarketAtlas`, field release, empirical/causal/strategy
claims, provider I/O, external mutation, product qualification, and live qualification to false.
