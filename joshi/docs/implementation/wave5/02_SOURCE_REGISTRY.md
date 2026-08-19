# Wave 5 A0 — source, cost, and privacy registry

Status: pure Rust contracts and offline validation complete; no provider I/O, credential loading,
store writer, or collector runtime lives here.

The canonical V1 registry now also contains one credential-free public-Solana C1 declaration for
`getSignaturesForAddress` on mainnet. The declaration is exact-byte/fingerprint bound, finalized,
newest-first, public-retained, rate-limited, and explicitly `never_proves_absence`; it is not a
live runner, production backend, quota observation, wallet-activity conclusion, or `W5-G1`
witness. Solana's official public endpoint is documented as rate-limited and unsuitable for
production applications, so this source may support only the separately registered bounded C1
conformance occurrence.

Owned paths:

- `crates/joshi-source-registry`;
- `fixtures/source-registry`; and
- this document.

## Boundary

`joshi-source-registry` is the pre-I/O seam between a registered run and a collector. It contains
non-secret source declarations, field-specific authority, method/schema fingerprints,
commitment/finality, billing/quota/reset, progress/absence and retry/gap semantics, physical
protection/retention, and an explicit kill switch. It does not contain URLs, credential bytes,
filesystem access, network clients, or a durable cursor. A valid declaration is not provider
availability or positive coverage.

```text
SourceRegistry::validate
  -> SourceRegistry::admit(source_id)
  -> source.admit_method(method_key)
  -> RunBudget::reserve_for_method(...)
  -> collector performs exactly one bounded I/O attempt
  -> RunBudget::settle(...)
```

`validate` is structural and permits a disabled/unavailable declaration so its gap reason can be
retained. `admit` is the explicit run gate and refuses those states and an active kill switch.
`BudgetReservation` carries the run identity and source/method scope; the mutable ledger retains
the exact reservation ID, held dimensions, and scope. A cloned or changed token cannot settle a
different reservation.

## Authority and privacy invariants

Access class is separate from credential authority and price. `zero-priced` is a billing fact,
not proof of unauthenticated access. An unauthenticated method requires a documented public-surface
attestation; a credentialed method requires a non-secret owner-only descriptor. Wallet-bearing and
transaction-execution authority are rejected at source validation, before any collector can read a
key. `pumpportal_contract()` returns the typed `WalletBearingCredential` refusal because the
provider API key carries Lightning-wallet signing authority, even where a route's published price
is zero. No risk cap converts that key into a read-only credential.

Field declarations retain separate primary, secondary, provider-assertion, companion-attestation,
and chain-evidence authority. A Pump/provider assertion cannot be declared chain authority. Field
absence must agree with every referenced method, so an empty page, `null`, interval poll, and live
disconnect cannot silently acquire one another's meaning.

## Semantics

Methods carry a schema fingerprint and max request/response envelope, commitment, finality policy,
billing unit, quota/reset, and absence rule. Progress joins retry/gap behavior:

| Progress | Required interpretation |
| --- | --- |
| `replay_cursor` | a cursor may support bounded recovery, subject to source evidence |
| `slot_anchor_requires_recovery` | a websocket slot is only a recovery anchor |
| `interval_poll` | each poll is interval-censored; empty/null does not prove feed absence |
| `live_only_no_replay` | reconnect opens an unrecoverable live gap |
| `fixture_sequence` | deterministic local sequence may be replayed |

Finality remains distinct from commitment. Processed data is provisional; corrections append new
knowledge. The registry does not promote a provider assertion into canonical chain truth.

## Hard run budgets

`RunBudget` is the only budget ledger. It independently accounts requests, pages, ingress bytes,
durable bytes, provider credits, event counts, provider-currency minor units, chain-native atoms,
and wall time.
Every reservation consumes worst-case cost plus declared in-flight overshoot before I/O. The ledger
refuses arithmetic overflow, cap crossing, unknown reservation IDs, changed scopes, duplicate
settlement, and dimension borrowing. `reserve_for_method` additionally checks the method's exact
response envelope and declared billing/quota ceiling; it requires a full method response envelope
to be reserved before a request is made. Provider counters are local hard ceilings, not invoices.

Planning profiles are frozen as offline declarations:

| Profile | Planning ceiling |
| --- | --- |
| C0 | no provider credits; bounded fake-source walk |
| C1 | 25 reads, 250 provider credits, 64 MiB ingress/durable |
| C2 | 10k provider credits, 256 MiB ingress, 128 MiB durable |
| C3 | 25k provider credits, 512 MiB ingress, 256 MiB durable |
| C4 | 100k provider credits, 2 GB ingress/day, 1 GB durable/day |

Profiles authorize no I/O by themselves. `PlanningProfile::run_budget()` intentionally refuses;
the integrator must call `registered_run_budget(run_id)` with the exact store-validated run
occurrence, then reserve before every request or connection. No profile adds chain-native or
provider-currency spend.

## Fixtures and gate

`fixtures/source-registry/canonical_registry.v1.json` is the non-secret canonical shape.
`pumpportal-wallet-bearing-rejected.v1.json`, `zero-price-not-public.v1.json`, and
`overshoot-refused.v1.json` are adversarial inputs. Rust tests cover unknown fields, fingerprint
changes, duplicate methods/fields, field/method absence mismatch, wallet-bearing PumpPortal,
zero-price ambiguity, kill-switch admission, source-bound response reservations, exact scope
settlement, double settlement, dimension borrowing, and all C0–C4 profiles.

```sh
cargo fmt --package joshi-source-registry -- --check
cargo test --package joshi-source-registry --all-targets
cargo clippy --package joshi-source-registry --all-targets -- -D warnings
cargo doc --package joshi-source-registry --no-deps
```

The collector/supervisor adapter should consume `SourceRegistry::admit`,
`SourceContract::admit_method`, `RunBudget::reserve_for_method`, and `RunBudget::settle`; it should
request source/run/attempt IDs from the shared supervisor and store owners rather than minting
parallel identities here.
