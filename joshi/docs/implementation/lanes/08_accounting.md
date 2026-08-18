# Implementation lane 08 — exact accounting projections

Status: Wave 1 implementation; pure read-side component; no execution authority.

## Delivered boundary

`crates/joshi-accounting` is a deterministic, no-I/O projector over finalized controlled-wallet
snapshots. Its inventory authority is the independently derived before/after wallet effect. An
economic classification can fail, remain unknown, or be corrected later without changing the
landed balance truth already applied.

The crate uses the shared `joshi-domain` `AccountId`, `AssetId`, `EpisodeId`, `LotId`, and
`WalletEffectId` identities and its decimal-string `WireU64`/`WireU128` types. It introduces no
parallel cross-crate identifiers. Its public modules are:

| Module | Responsibility |
| --- | --- |
| `amount` | `u64` account atoms, checked `u128` portfolio totals/intermediates, signed-magnitude effects, explicit floor/ceiling `mul_div` |
| `effect` | exact per-account and consolidated effects derived from finalized snapshots |
| `basis` | normalized exact rational basis and explicit `known` / `estimated` / `partial` / `unknown` quality |
| `lots` | acquisition and unknown-inflow lots, named disposal slices, exact remaining basis, capital-recovery cash facts |
| `accounting` | landed-effect application, later classification, reconciliation residuals, realized projections |
| `episode` | attribution-only inventory epochs, exact flat, watching-flat, and re-entry inside one episode |
| `model` | snapshot rows bound to shared domain IDs and wire integers |

Nothing in the dependency graph performs network, database, transaction construction, signing,
simulation, or submission.

## Numerical choices

- Observed account amounts are `u64`; consolidated controlled-domain quantities are checked
  `u128`. Signed changes are magnitude-plus-direction rather than `i64`, so a legal `u64::MAX`
  amount can be represented safely.
- Multiplication/division primitives use a checked `u128` intermediate and an explicit floor or
  ceiling operation. Narrowing back to `u64` is checked.
- Partial basis allocation uses `num-rational` 0.4.2 backed by the currently locked `num-bigint`
  0.4.8. This is confined to analytical allocation: landed atoms never become arbitrary-precision
  or floating values.
  Exact rationals prevent sale partitioning from manufacturing basis dust.
- `proptest` 1.11 exercises closure/conservation across generated sale partitions and arithmetic
  rounding boundaries.
- `serde_json_canonicalizer` 0.3.2 is test-only and verifies RFC 8785-stable fixture bytes. It is
  not another production serializer or accounting authority.

The Rust-num and proptest projects are established MIT/Apache-2.0 libraries. JCS canonicalization
is MIT-licensed and has deliberately been kept outside production dependencies.

## Semantic behavior

### Landed truth before interpretation

`FinalizedWalletEffect::between` unions every account/asset key, treats an absent row as exact zero,
and derives both per-account and consolidated changes. A transfer between two included wallets has
two account effects but zero consolidated asset effect. The accounting state only advances when an
effect begins at the current finalized aggregate snapshot and has a new effect ID.

`AccountingState::apply_effect` and `AccountingState::classify` are separate calls. Applying the
effect updates landed truth. A classification mismatch cannot roll it back or replace its amount;
the mismatch remains visible for later correction/reconciliation.

### Lots and basis

Acquisitions create exact lots only after the acquired quantity and atomic basis components match
the wallet effect. External inflows may create an explicitly unknown-basis lot. Unknown basis is
never represented as zero or current mark.

Every disposal or external outflow supplies named `(lot_id, quantity)` slices. There is no implicit
FIFO/LIFO/default selector. This keeps the factual lot lineage separate from a future operational,
analytical, or tax projection. A sale returns allocated basis and a realized result only when basis
quality supports it; an external transfer returns transferred basis but no realized PnL.

For a partial slice `s` from remaining lot quantity `Q`, each known basis component is allocated as
the exact rational `B*s/Q`. Full consumption therefore removes the exact residue. When quantity is
zero, remaining basis is exact zero; the code never rounds each partial sale to lamports.

### Runner and capital recovery

A partial disposal leaves exact quantity and basis in the lot book. Capital recovery is a separate
cash-flow projection per `(episode, inventory epoch, reference asset)`:

- `not_recovered(shortfall)` when exact returned atoms are below spent atoms;
- `recovered(excess)` when returned atoms meet or exceed spent atoms; and
- `no_capital_recorded` when the projection has no declared spend.

Recovery does not zero the runner's basis, quantity, value, or risk and is not called profit.

### Flat watching and re-entry

Episode attribution is deliberately unable to alter wallet balances or lots. A transition from
nonzero attributed quantity to exact zero closes the current inventory epoch but leaves the episode
open. `continue_watching_flat` is explicit. A later zero-to-nonzero transition starts the next
epoch inside the same episode; the acquisition lot names that new basis epoch.

External or unclassified wallet changes can advance the exact ledger without silently entering an
episode. The difference between observed inventory and classified lot quantity remains available as
a signed reconciliation residual.

## Golden vectors

`fixtures/accounting` contains readable, language-neutral JSON. All financial integers are decimal
strings and rationals are reduced numerator/denominator strings.

| Fixture | Cases |
| --- | --- |
| `arithmetic.json` | nondivisible floor/ceiling, exact ceiling, zero denominator, `u128` product whose result cannot narrow to `u64` |
| `state_machine.json` | buy → partial profit → live runner → exact flat → watching-flat → re-entry/new epoch; unknown external basis and outflow; custody-only movement; unclassified inflow residual |

The principal runner vector spends 101 SOL atoms for 1,000 token atoms, sells 600 for net 119,
retains 400 with basis `202/5`, and reports realized `292/5` plus capital-recovery excess 18. The
remainder is then sold for 50, consuming exact basis `202/5`; total epoch realized result is the
integer cash identity 68. Re-entry spends 30 for a fresh 200-token lot in epoch 2 of the same
episode.

Fixture expectations are hand-reviewed inputs. Tests parse and execute them; they do not regenerate
the expected documents from the implementation under test.

## Invariants exercised

1. No source amount or monetary calculation passes through binary floating point.
2. Account atoms, aggregate atoms, and exact rational basis are distinct types.
3. Finalized wallet effects, not classifications or episode labels, determine balances.
4. Internal controlled-wallet moves have zero household effect.
5. An effect is applied once and must connect to the current finalized snapshot.
6. Acquisition/proceeds quantities must match the corresponding observed asset effect exactly.
7. Every lot disposal names complete nonduplicated slices; no selection policy is guessed.
8. Unknown basis remains unknown through partial external outflow.
9. Partial allocations plus final allocation equal original basis exactly.
10. Exact flat leaves zero classified quantity and no basis dust.
11. Capital recovery is cash-flow truth and cannot make a remaining runner free.
12. Episode attribution cannot create inventory; watching-flat and re-entry preserve episode
    identity while starting a new basis epoch.
13. Unclassified holdings produce an explicit lot reconciliation residual rather than zero basis.
14. Reparsed fixture values produce byte-identical RFC 8785 serialization and contain no JSON
    numeric tokens.

## Verification command

```sh
cargo test --locked -p joshi-accounting --all-targets
```

This lane does not own the root manifest or lockfile. The integration owner refreshes the shared
lock after package membership/dependency changes; lane verification always runs with `--locked`.

## Deliberate limits and handoff

- The initial `AssetId` is the shared opaque identity. A later protocol plane may validate a
  structured network/program/mint profile before constructing it; accounting must not infer asset
  identity from ticker text.
- Basis supports a commodity vector internally, while current goldens use one SOL-like reference
  component. Multi-commodity fixtures should arrive with LP custody and token-token history.
- Episode inventory quantities are explicit attribution observations. The projector does not infer
  that every wallet unit belongs to one episode.
- Corrections are represented by rebuilding/versioning projections from retained evidence; no
  persistence API is included here.
- Marks, executable liquidation, LP-bin contingent schedules, counterfactual branches, tax-lot
  policy, and fee/rent decomposition remain separate future projectors. None should be smuggled into
  lot basis or the landed balance state.
- The next integration seam is an evidence-to-finalized-snapshot adapter plus a versioned output
  envelope. It should call this pure API and retain reconciliation failures, not add convenience
  arithmetic in the store or UI.
