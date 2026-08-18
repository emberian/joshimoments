# Lane 21 — receipt-gated wallet/topology circulation (W4-04)

Status: **offline walking seam complete; live provider and Glass/export circulation remain gated**  
Date: 2026-08-17  
Code: [`crates/joshi-wallet-source`](../../../crates/joshi-wallet-source),
[`crates/joshi-wallet-admission`](../../../crates/joshi-wallet-admission),
[`crates/joshi-wallet-topology`](../../../crates/joshi-wallet-topology)  
Goldens: [`fixtures/wallet-source`](../../../fixtures/wallet-source)

## Outcome

W4-04 now has one typed, offline-tested path:

```text
exact public-chain RawSourceFrame
  -> retained EvidenceDraft (full lossless frame envelope)
  -> raw transaction versions + quarantined provider projections
  -> pinned Pump/PumpSwap instruction intents
  -> exact swaps only from unique executed transfer legs
  -> one atomic store batch: observation + source events + coverage + cursor candidate
  -> validated public durable receipt
  -> admitted transaction/caller/transfer/swap/bundle facts
  -> store-verified coverage binding
  -> immutable point-in-time topology snapshot
```

The implementation does not contain a provider client, crawler, private-key reader, signer,
transaction builder, simulation request, or submission path. No live read was used for this work.
All fixtures are synthetic or offline differential vectors.

## Receipt-gated authority

`prepare_wallet_admission` normalizes and stages the response, but returns a
`PreparedWalletAdmission` whose normalized facts, topology facts, coverage closure, and cursor are
private. There is no pre-receipt getter that can claim them as admitted.

`PreparedWalletAdmission::commit` is the only transition:

```text
PREPARED / NOT DURABLE
  | AdmissionBatch::commit(SqliteStore)
  | - source registration
  | - exact acquisition/observation payload
  | - all transaction source-event links
  | - one scoped coverage window
  | - optional evidence-backed CursorAdvance
  v
RECEIPT VALIDATED
  | receipt batch digest == submitted canonical batch digest
  | exact counts close the wallet batch
  | cursor is re-read at receipt.through_commit_seq
  v
ADMITTED
  | facts become public
  | coverage becomes StoreVerified
  v
IMMUTABLE TOPOLOGY SNAPSHOT
```

The cursor is supplied inside the same atomic batch because that is the store contract, but the
adapter does not expose it until `justified_source_cursors_as_known` finds the exact cursor at the
receipt cutoff. A merely observed source cursor remains descriptive before commit.

The `CoverageBinding::StoreVerified` variant carries the exact sorted coverage IDs, catalog ID,
receipt cutoff, and every contributing `StoreCoverageReceipt` (batch ID/digest, cutoff, and coverage
IDs). Binding consumes the snapshot and requires exact set equality between the union of those
receipt closures and `SnapshotRequest.requested_coverage_ids`; a narrower or unrelated receipt
cannot bless it.

Prior facts are not accepted as caller-supplied `Vec<TopologyFact>`. A correction may receive only
an opaque, nonserializable `VerifiedTopologyHistory` cloned from an earlier receipt-gated
`AdmittedWalletTopology`. The history privately carries all earlier facts and coverage receipts.
The adapter rejects a history from another catalog or a cutoff later than the new receipt. The
cross-catalog adversary proves refusal; the already-durable current evidence remains recoverable by
an exact retry without the unrelated history. This closes in-process arbitrary-fact injection.

The remaining restart boundary is explicit: no typed store readback currently reconstructs
`VerifiedTopologyHistory`, and exact snapshot bytes/digest are not yet registered as a durable
artifact. A process restart must therefore wait for the owning store/publication lane rather than
deserializing a claimed history from JSON.

The offline round-trip test uses the real V7 SQLite/CAS writer. It verifies the exact raw-body
digest and byte length, the receipt closure, full store integrity, and an exact idempotent replay
that returns the original commit/digest instead of creating a second cursor. The store payload is
the shared lossless retained-frame envelope, which includes the exact response body plus source,
transport, direction, stream class, status, safe headers, and acquisition clocks.

## Pinned Pump/PumpSwap decoder

Runtime decoding is a small Rust reference implementation; it has no SDK/runtime or network
dependency. The profile is pinned to official Pump material:

| Pin | Exact value |
| --- | --- |
| `pump-public-docs` commit | `9c82f61cb711b044a17f770ab8ce9f9bdf78f333` |
| `idl/pump.json` SHA-256 | `b90bc471327f671449271d5d1d42354d1fae6f5a06502f5834459a3108138e49` |
| `idl/pump_amm.json` SHA-256 | `6b5c7ec4e5ef9742fa99dc57b0d75b1031b379bba02a7e1b3c5a4cad68d77e56` |
| Pump program | `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` |
| PumpSwap program | `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA` |
| `@pump-fun/pump-sdk` oracle artifact | `1.36.0`, pinned npm integrity in the golden |
| `@pump-fun/pump-swap-sdk` oracle artifact | `1.19.0`, pinned npm integrity in the golden |
| local decoder contract | `joshi.pump_instruction_decoder.v1` |

Primary sources are the official
[`pump-public-docs`](https://github.com/pump-fun/pump-public-docs) repository and the two official
`@pump-fun` npm packages. The packages/Anchor coder were used only to produce the offline oracle
corpus; they are not linked into Joshi.

The differential golden contains the exact Anchor-encoded base58 and hex bytes for:

- Pump `buy`, `sell`, `buy_v2`, `sell_v2`, and `buy_exact_quote_in_v2`;
- PumpSwap `buy`, `buy_exact_quote_in`, and `sell`; and
- typed request/limit arguments for each case.

The decoder first selects by **program ID and discriminator together**. This matters because legacy
Pump and PumpSwap buy/sell discriminators overlap. It then validates exact Borsh length, the optional
boolean enum tail, official account count/layout, and the expected user signer position.

### Intent is not a fill

Instruction fields such as `max_quote_amount_in`, `min_quote_amount_out`, or requested base amount
are retained as `PinnedSwapIntent`. They are not contemporaneous fills.

An exact `SwapFact` is admitted only if all of the following are true:

1. the transaction and instruction succeeded;
2. the pinned program invocation/path exists in the same raw transaction fact;
3. the official user account is an exact transaction signer;
4. exactly one nonzero executed input transfer and one nonzero executed output transfer occur under
   the same outer instruction invocation;
5. both transfers match the pinned user/pool token accounts and exact base/quote asset IDs; and
6. the strict existing `admit_decoded_swap` evidence check accepts the constructed result.

Missing or ambiguous legs yield `IntentOnlyMissingOrAmbiguousExecutedLegs`; a failed transaction
yields `IntentOnlyTransactionFailed`. Neither produces an exact swap. The two-transaction finalized
fixture deliberately makes the Pump request limit differ from the actual input and the PumpSwap
minimum differ from actual output, proving the decoder uses transfers rather than copying args.

This V1 decoder is deliberately narrow. It does not infer fees from residual deltas, collapse
multi-hop routes, decode arbitrary token extensions, or recover exact legacy SOL fills where a
matching successful transfer leg is absent. Those remain intents/effects until a separately pinned
profile supplies exact semantics and differential vectors.

## Versioning, finality, and correction

Each normalized transaction carries:

- a natural signature/slot/index locator;
- immutable `transaction_fact_id`, positive version, and exact superseded fact ID;
- finality, canonicality, and independent local `available_at`; and
- the source-namespaced Solana transaction event ID assigned in the exact store batch; and
- every dependent caller, transfer, swap, and bundle bound to that exact version ID.

The correction gate commits canonical finalized V1 facts, freezes/serializes its snapshot, then
commits later-known V2 noncanonical versions of the same two signatures. At the later cutoff:

- both V2 transaction versions remain visible in `observed_transaction_versions`;
- neither V2 transaction nor any dependent row enters `accepted_facts`;
- both natural transaction IDs appear in the noncanonical exclusion set; and
- the earlier accepted snapshot bytes and digest are unchanged.

This is bitemporal append-and-reduce behavior. It is not mutation of “the current transaction.” A
processed/confirmed version can use the same mechanism, but this lane did not run a live processed
notification.

## Vendor projection quarantine

The legacy Helius Enhanced shape still normalizes only to `EnhancedProjection` with
`requires_raw_reconciliation = true`. `prepare_wallet_admission` never passes these projections to
the pinned decoder, `to_topology_facts`, or `TopologyReducer`. After receipt, they are exposed only
as `quarantined_enhanced_projections` for diagnostics/differential study.

An Enhanced claim cannot manufacture a transfer, swap, caller identity, or topology edge. Raw
Solana transaction evidence is required for those facts.

## Epistemic invariants

- A public key is an account identifier, not a person, owner, creator, insider, or skilled wallet.
- Same-transaction account bundles are ordered incidence facts, not common-control assertions.
- A direct transfer is not a funding/identity fact; funding remains a separate hypothesis family.
- A Pump/PumpSwap instruction is intent until exact successful transfer legs prove a fill.
- Vendor parsing is a quarantined projection, never raw-chain truth.
- Coverage is `RequestedUnverified` at the source and becomes `StoreVerified` only from the receipt.
- Receipt knowledge time, chain slot/finality, block/event time, and normalized availability remain
  distinct axes.
- New finality/canonicality knowledge appends a version and produces a new snapshot; old snapshots
  are immutable.

There are no fields or discriminators named `person`, `owner`, `insider`, `smart_money`, or
`skilled_wallet` in this lane's output contract.

## Offline gates

The focused gates cover:

- all eight differential instruction vectors, including byte-for-byte base58/hex agreement;
- exact Pump v2 and PumpSwap fills from four executed transfer legs;
- refusal to call a recognized intent exact when one transfer leg is removed;
- exact retained response body and receipt/CAS closure;
- two source-event links, one store coverage window, and one receipt-gated cursor;
- transaction, caller-account, transfer, exact swap, and same-transaction bundle facts;
- store-verified coverage on the immutable snapshot;
- opaque receipt-derived history plus the complete ordered receipt/coverage union;
- idempotent exact replay at the same commit/digest;
- refusal of an otherwise valid history from an unrelated catalog;
- later noncanonical V2 selection without mutation of the V1 snapshot; and
- legacy Enhanced quarantine.

Committed fixture closure for review:

| Fixture | Bytes | SHA-256 |
| --- | ---: | --- |
| `finalized_pump_pumpswap_exact.json` | 9,108 | `50a61bec0cd3f12b08f3ed8702fa1818a7da6ab64538d7c5afdc01c6a6f25d73` |
| `pump_decoder_differential.json` | 4,354 | `73b01ee86b8074fa8e54cacdc54fa833ac15be86f9972cd0dcaf04fc950956ee` |

Normal focused commands are:

```bash
cargo test -p joshi-wallet-source --all-targets
cargo test -p joshi-wallet-topology --all-targets
cargo test -p joshi-wallet-admission --all-targets
cargo clippy -p joshi-wallet-source -p joshi-wallet-topology -p joshi-wallet-admission \
  --all-targets -- -D warnings
```

Final focused results on the current W4-04 code:

- `joshi-wallet-source`: **17/17** tests passed;
- `joshi-wallet-topology`: **7/7** tests passed;
- `joshi-wallet-admission`: **3/3** tests passed against the real store;
- owned-crate `cargo clippy --no-deps ... -- -D warnings`: passed; and
- owned-crate rustdoc with `RUSTDOCFLAGS='-D warnings'`: passed.

The final combined locked test command passed all **27/27** focused tests. Full dependency Clippy
remains red outside this lane on missing public `# Errors` docs and `items_after_statements` in
`joshi-admission/src/operational.rs`; owned-crate no-dependency Clippy is clean. This lane does not
relabel the workspace root as green. It also has no 24-hour continuity/kill-gate result: that
belongs to W4-01 and no live provider process ran here.

## Remaining gates

1. Resolve shared admission Clippy failures outside this lane and run the workspace root gate.
2. Walk one separately authorized bounded public provider response through this exact adapter; do
   not substitute it for the offline correction/differential corpus.
3. Add a typed store-backed export/Glass consumer in the owning W4-06/W4-07/W4-08 lanes. The wallet
   adapter intentionally ends at the immutable snapshot and does not publish a cockpit head.
4. Register exact topology snapshot bytes/digest and implement receipt-derived history readback;
   until then restart cannot reconstruct operational history from store.
5. Expand the decoder only through a new pinned IDL/profile plus new oracle and adversarial vectors.
   Never reinterpret unknown bytes under the existing V1 profile.
