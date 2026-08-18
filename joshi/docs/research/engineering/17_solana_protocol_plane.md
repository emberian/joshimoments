# Solana protocol plane: acquisition, decoding, quoting, and future execution boundary

**Status:** engineering research; not an implementation authorization  
**Evidence cutoff:** 2026-08-16  
**Decision scope:** choose the smallest trustworthy protocol integration boundary for Pump, PumpSwap, and Meteora DLMM. The repository remains inside the read/query/shadow envelope authorized by `FOUNDATION.md`; this document does not authorize transaction construction, signing, or submission.

## Outcome

Do not make TypeScript, Rust, C#, Python, or the old Node sidecar the canonical representation of the market. Make raw Solana observations and language-neutral, integer-valued derived artifacts canonical. Keep the vendor libraries as pinned, replaceable interpreters of those artifacts.

The best current hypothesis is:

1. use native Rust for Solana wire decoding, acquisition, normalization, and Pump/PumpSwap interpretation;
2. keep the official TypeScript SDKs as independent reference oracles;
3. decide whether Meteora can also be native Rust only after an exact differential conformance spike against `@meteora-ag/dlmm@1.9.14`;
4. if Meteora Rust parity is incomplete, use a narrow, untrusted TypeScript process for Meteora reads and quote calculations—not FFI, not signing, and not submission;
5. let C# consume the language-neutral protocol stream if it proves valuable for the application/domain layer, but do not make it responsible for Pump or DLMM arithmetic today.

That is a hypothesis, not a runtime decision. The final section gives a read-only spike whose result actually chooses among those branches.

## Epistemic labels

- **Known:** stated by a current primary/official protocol source, an official package registry, or the protocol's public source.
- **Observed compost:** fact about `~/dev/joshibot`; useful as a fixture or warning, not evidence that the design is correct.
- **Inference:** an engineering conclusion drawn from known facts.
- **Gap:** a material fact the public sources do not establish or that still needs conformance testing.
- **Proposed:** a design choice for `joshi`, subject to the repository's decision gates.

The official sources used here are pinned in [Source register](#source-register). Consumer-facing wording is not treated as a wire-level specification when it conflicts with a program account or instruction description.

## Boundary first

The protocol plane is an adapter between chain/provider facts and our evidence model. It is not the strategy, UI, ledger, signer, or submitter.

```text
RPC / WebSocket / Geyser
          |
          v
 raw provider envelopes + bytes  -----> immutable evidence tape
          |
          v
 versioned-tx / ALT / IDL decoders ----> decoded assertions
          |
          +----> Pump lifecycle + quote artifacts
          +----> PumpSwap lifecycle + quote artifacts
          +----> DLMM pool / position / quote artifacts
          |
          v
 strategy, operator episode, and accounting consumers

Future and separately authorized:
capability -> planner -> unsigned bytes -> independent guard
           -> isolated signer -> identical-byte submitter -> reconciliation
```

At the currently authorized stage, the lower line does not exist. A read process may depend on a package that happens to export transaction builders, but our adapter API, tests, credentials, and network proxy must not expose or call them.

## What the official ecosystem actually supports

### Program and SDK matrix

| Surface | TypeScript | Rust | C# | Consequence |
|---|---|---|---|---|
| Solana core | **Known:** Anza lists `@solana/kit` as recommended and `@solana/web3.js` as legacy, both official | **Known:** `solana_sdk` and the decomposed Solana crates are official | **Known:** Solana lists Solnet as community-maintained and warns community SDKs may be incomplete or stale | Rust and TS are first-party wire choices; C# needs a cross-language oracle |
| Anchor IDL decoding | Anchor TS; Codama can generate Kit-compatible JS | Anchor `declare_program!`; Codama can generate Rust | An IDL-to-C# generator is documented, but the tool/runtime is community code | An IDL generates shapes; it does not supply protocol quote math or integration conformance |
| Pump bonding curve | **Known:** official npm `@pump-fun/pump-sdk@1.36.0` | **Known:** official `pump-rust-client@0.1.11` covers instruction builders, account/PDA helpers, quotes, and optional RPC | No first-party Pump client found | Rust and TS can be compared directly |
| PumpSwap | **Known:** official npm `@pump-fun/pump-swap-sdk@1.19.0` | **Known:** `pump-rust-client@0.1.11` also exposes `pump_amm` | No first-party PumpSwap client found | Rust is plausible for the production decoder/quote plane |
| Meteora DLMM | **Known:** official `@meteora-ag/dlmm@1.9.14`; this is the most complete documented client | **Known:** official public repository contains `dlmm_interface` and a `commons` Rust crate with account/position parsing and quote math | No first-party DLMM client found | TS is the reference; Rust is a candidate, not yet assumed equivalent |
| Yellowstone gRPC | Official project provides Rust and Node clients | Rust is the primary client/server path | Protobuf makes generation possible, but no project-supported C# conformance claim was found | A language-neutral protobuf boundary does not imply equal client maturity |

The [Solana SDK list][solana-sdk-list] is unusually explicit: C# is a community surface. [Solana's IDL guide][solana-idl] documents C# generation, and [Codama][codama] can generate Rust and Kit-compatible JS, but Codama is itself marked active development. An IDL supplies discriminators, account layouts, instruction layouts, events, and errors. It does not supply Pump's evolving fee selection or DLMM's bin traversal, dynamic fee, transfer-fee, and rebalancing logic.

### Package/source integrity facts

The version observations above were checked against the registries on the evidence date. The Pump npm package metadata points at `github.com/pump-fun/pump-sdk` and `github.com/pump-fun/pump-swap-sdk`, but those repositories were not publicly retrievable during this research. The official npm artifacts and public [`pump-public-docs`][pump-docs] IDLs are available; the npm source history is not.

Observed pins:

| Artifact | Version/commit | Registry integrity where applicable |
|---|---|---|
| `@pump-fun/pump-sdk` | `1.36.0` | `sha512-X8rf+Wm/p/jhBj6zbwouM9blJ3UW8XJFSL7YTT8osBnpHsOH0ccT0DjCkIi6AAT7b6jf1nM3MXk7l78Fuf1M0g==` |
| `@pump-fun/pump-swap-sdk` | `1.19.0` | `sha512-ayLO7ESmPOpZfz1hQSiGJBanJVaQTQB/+8yRHiuZnaHIRMTwOYknH1EZr++tPNa+kYJgg8kccU98Jp9RGOdZLQ==` |
| `pump-rust-client` | `0.1.11` | crates.io registry checksum belongs in the generated Cargo lockfile |
| `@meteora-ag/dlmm` | `1.9.14` | `sha512-3xJGBaYgkHWSZ7sjfaMYTuCUE9/FGibIwhoNKSaP3iXX3kZck4b3qrtFwDl/1+JaflTeiZQY4zO25e+u2V/9ug==` |
| `MeteoraAg/dlmm-sdk` | `fb02e51ae677bbd18e76543f702dae40632426db` | Git commit |
| `pump-fun/pump-public-docs` | `9c82f61cb711b044a17f770ab8ce9f9bdf78f333` | Git commit |
| `rpcpool/yellowstone-grpc` | `ecdac262a500460e82aeaddbb1891ef002670bc7` | Git commit |

**Gap:** there is no publicly auditable one-to-one source commit for the current Pump npm tarballs that this research could establish.

**Proposed control:** pin package version, registry tarball integrity, lockfile, public IDL hash, public-doc commit, program IDs, and observed executable program-data hash. Do not silently update any one of them. The Rust crate is independently useful because its source is published through crates.io/docs.rs, but it is still an implementation to verify, not protocol truth.

Meteora's situation is different: [`MeteoraAg/dlmm-sdk`][meteora-sdk] is public and contains `ts-client`, `commons`, `dlmm_interface`, IDLs, CLI, and a Python client. The Rust `commons` crate is a workspace/path crate (currently versioned `0.3.3` in the source tree), not a clean, independently versioned crates.io integration equivalent to the npm package. Pin it by repository commit or vendor it with provenance. Meteora's own changelog recommends comparison with the TS SDK, and recent releases changed quote, position, Token-2022, and rebalancing behavior. That is precisely why conformance comes before reuse.

## Canonical artifacts, not SDK objects

All amounts, counters, fees, reserves, prices represented as ratios, slots, and timestamps cross the language boundary as decimal strings or fixed-width bytes. No JavaScript `number`, C# `double`, or JSON floating point is allowed for economic state.

### Raw observations

`RawAccountObservation`

- pubkey, owner, lamports, executable, rent epoch, and exact account-data bytes;
- RPC context slot, requested commitment, provider/source ID;
- Geyser write version and transaction signature when supplied;
- source receive time, provider `created_at` when supplied, content hash;
- acquisition epoch and gap/reconnect identifier.

`RawTransactionObservation`

- signature and exact serialized transaction bytes when the provider exposes them;
- legacy/v0 version, slot, transaction index, block time, commitment/finality;
- exact metadata: `err`, log messages, inner instructions, rewards, CU consumed, fee, pre/post lamports and token balances;
- resolved writable/read-only lookup-table addresses plus the raw lookup references;
- provider envelope, source time, receive time, content hash.

`AcquisitionCoverage`

- source, filter specification and hash, commitment, start/end slots;
- first and last received sequence/slot, reconnect epochs;
- duplicates, conflicts, dead/skipped/missing slots, bounded replay result;
- `complete`, `partial`, `unknown`, or `unrecoverable`, with reason.

### Derived assertions

`DecodedAssertion`

- raw-observation hash;
- program ID and executable program-data hash if known;
- IDL/source artifact hash and decoder build hash;
- instruction/account/event discriminator;
- exact typed fields with integer values serialized as decimal strings;
- invocation depth and top-level/inner-instruction location;
- confidence (`wire_decoded`, `event_only`, `balance_inferred`) and decode errors.

Decoded data is an assertion that can be recomputed. It never replaces the raw observation. This matters because Anchor [events can be logged or emitted through CPI][anchor-events], and provider logs may be truncated. A trade should be recoverable from instruction data and balance effects even when an event is absent.

### Venue artifacts

`VenueLifecycle`

- base mint and quote mint/token programs;
- `pump_curve_open`, `pump_curve_complete_unmigrated`, `pumpswap_canonical`, `other_pool`, or `unknown`;
- curve, pool, and fee-config account keys and hashes;
- evidence slots for each claim, never a single blended “current” timestamp.

`QuoteArtifact`

- venue, program, pool/curve, base/quote mint, direction, exact-in/exact-out;
- raw integer request, gross input, net input, output, min/max field before slippage, and any unconsumed input;
- each fee component, its basis/rounding rule, Token-2022 transfer fees, rent excluded/included, and network/priority/Jito costs explicitly excluded unless separately modeled;
- raw and effective reserves; Pump fee tier and market-cap inputs; DLMM start/end bin, traversed bin arrays, fee-on-input mode, protocol fee, price impact;
- a state manifest of every account pubkey, context slot, data hash, and decoder/SDK version used;
- source receive time, quote completion time, stale-state bound;
- result `quotable`, `partial`, `unquotable`, or `inconsistent`, with reason.

`DlmmPositionSnapshot`

- position and pool IDs, owner/authority, position kind/version;
- lower/upper bin, active bin, bitmap/bin-array coverage;
- per-bin liquidity, token X/Y amounts, fee and reward checkpoints/accruals;
- reserve and mint/token-program observations, including transfer-hook inputs;
- state manifest and interpretation version.

These schemas are language-neutral contracts. Protobuf is suitable for live transport; canonical CBOR or length-delimited protobuf plus a normative JSON projection is suitable for fixtures. The durable identity is a hash of canonical bytes, not a serializer's field order.

### What is a reference implementation, and what we own

| Keep as a pinned reference/oracle | Own as a language-neutral contract |
|---|---|
| Solana Rust/Kit wire parsing and official RPC response definitions | raw account/transaction/provider observations and coverage/gap records |
| Pump and PumpSwap public IDLs/docs plus TS and Rust quote/account implementations | lifecycle classifications, state manifests, quote artifacts, and decode assertions |
| Meteora TS 1.9.14 account/position/quote/rebalance simulation, differentially checked against the same-revision Rust repository | DLMM pool/position/per-bin snapshots, quote inputs/results, and unquotable/partial reasons |
| Anchor event/account parsers tied to an explicit IDL hash | evidence confidence, correction/supersession, and cross-source inconsistency records |
| Recorded finalized chain effects as the economic oracle | reconciled ledger effects and operator/strategy attribution |

We should not port SDK object graphs wholesale into protobuf, and we should not copy current fee tables or instruction accounts into an unversioned domain enum. A reference implementation is allowed to change behind a new adapter version. A canonical artifact remains readable and replayable after that change because it retains raw bytes, exact integers, state inputs, and interpreter identity.

## Acquisition plane

### Baseline: HTTP snapshots plus WebSocket hints

Solana exposes `accountSubscribe`, `programSubscribe`, `logsSubscribe`, and `signatureSubscribe` over WebSocket, and account/transaction/block reads over HTTP. Notifications include a context slot, but the official WebSocket API does not promise a durable cursor or replay log. A clean connection is therefore not evidence of completeness.

**Proposed baseline loop:**

1. fetch a finalized snapshot or bounded finalized history watermark;
2. establish processed/confirmed subscriptions for low-latency hints and explicit finalized slot tracking;
3. record the subscription request, response ID, connection epoch, and every raw notification;
4. on disconnect, mark coverage unknown immediately;
5. reconnect, backfill the bounded slot/signature interval through HTTP, refetch relevant accounts at a recorded slot context where possible, and reconcile duplicates/conflicts;
6. advance the finalized watermark only after the backfill and both-source comparison close the gap.

Processed observations can power a fast display, but they are provisional. The evidence tape retains their later confirmation/finalization or dead-fork correction.

Use raw transaction encoding with `maxSupportedTransactionVersion` rather than relying only on `jsonParsed`. [`getTransaction`][get-transaction] can return `null`, requires version negotiation for versioned transactions, and returns transaction metadata such as inner instructions and loaded addresses. `jsonParsed` is convenient for known native/SPL programs but cannot be the semantic decoder for Pump or Meteora.

### Geyser and Yellowstone

Agave's Geyser plugin interface emits validator account, transaction, slot, and block updates. [Yellowstone gRPC][yellowstone] is Triton/rpcpool's open Geyser transport, not a Solana protocol guarantee. Its current protobuf includes filtered account/transaction/status/block/slot streams, commitment, account `write_version`, transaction index, provider creation time, ping/pong, and an optional `from_slot`. `SubscribeReplayInfo.first_available` makes the key limitation explicit: replay starts only as far back as that server retained. Stream is not archive.

The protobuf and changelog have had breaking changes. Pin the proto and generated-code hash. A provider advertising “Yellowstone” must still be tested for:

- available filters and maximum subscription count;
- commitments and fork/dead-slot behavior;
- `from_slot` retention and replay behavior;
- account write versions and transaction indexes;
- raw transaction/meta fidelity, ALT resolution, and block reconstruction gaps;
- ping, reconnect, rate-limit, overflow, and slow-consumer behavior;
- whether optional/deshred methods are actually implemented.

**Inference:** WebSocket + HTTP is the correct first baseline because it has fewer moving parts and defines the recovery algorithm we need regardless. Yellowstone should win only if the two-source spike shows materially better completeness, latency, or cost without weakening replay/reconciliation. A Geyser source does not remove the need for finalized HTTP backfill.

### Historical backfill

There are three distinct jobs:

1. **bounded recovery:** `getBlock` by slot, or `getSignaturesForAddress` followed by `getTransaction`, closes a known recent interruption;
2. **venue history:** signature scans around the Pump/PumpSwap/Meteora program and relevant pool/mint accounts recover protocol transactions, subject to provider retention and query policy;
3. **historical state:** exact account state before/after an arbitrary old event generally requires an archive/indexer or reconstructing it from a complete ledger; `getProgramAccounts` only gives a current snapshot.

Provider ledger retention, pagination caps, null transactions, skipped slots, rate limits, log truncation, and program-wide scan policy make “all historical Pump activity” an unproven claim. A managed archive or data lake may be necessary. It still must deliver raw transaction/meta bytes or a documented loss boundary.

**Gap:** no primary Solana or venue source guarantees that an arbitrary RPC provider can produce a complete, genesis-to-present program history. Label backfill coverage rather than converting “no result” into “no event.” From the first day of `joshi`, retain our own raw observations so this gap shrinks prospectively.

## Transaction decoding and reconciliation inputs

A correct decoder must handle:

- legacy and v0 messages;
- address lookup tables and loaded writable/read-only addresses;
- top-level instructions and CPI/inner instructions with invocation ordering;
- Anchor discriminator changes pinned to a particular IDL;
- native SOL, wrapped SOL, SPL Token, and Token-2022 balance effects;
- account creation/closure/rent and fee-payer deltas;
- failed transactions: fees may be charged even when program state effects roll back;
- multiple venue instructions in one transaction;
- event logs that are missing, duplicated by a retry observation, or disagree with balance effects.

The decoder emits assertions, not “fills.” The financial ledger reconciles a fill only from landed transaction facts and asset deltas, with protocol instruction/event data as attribution evidence. Manual wallet transactions and unknown instructions remain external/unattributed until classified.

Useful redundancy is intentional:

```text
instruction intent
     + protocol event / CPI event
     + pre/post token and lamport deltas
     + pool/curve account transition
     + finalized signature/slot/index
     = reconciled economic effect (or an explicit inconsistency)
```

An event-only fill is not acceptable. A balance-only attribution may be acceptable as `unknown_external`, not as a strategy success.

## Pump bonding curve and PumpSwap

### Lifecycle is a state machine, not a ticker rename

The current Pump program documentation defines a completed curve as `complete == true` and `real_token_reserves == 0`. Its `migrate(user, mint)` instruction is permissionless and idempotent. The canonical PumpSwap pool created by migration uses pool index `0` ([Pump program][pump-program], [PumpSwap][pump-swap]). Therefore:

```text
CURVE_OPEN
   |
   | curve completion observed
   v
CURVE_COMPLETE_UNMIGRATED
   |
   | canonical pool account exists and migration is observed/reconciled
   v
PUMPSWAP_CANONICAL
```

The [Pump consumer page][pump-bonding] describes graduation as automatic/atomic, but that shorthand must not collapse the observable `complete-but-no-pool-yet` interval in our data. A quote request during the interval is `unquotable: migration_gap`, not silently routed to stale curve math or to a guessed pool. Noncanonical PumpSwap pools remain distinct venues.

### Current instruction surface

The official public docs now specify `buy_v2`, `sell_v2`, and `buy_exact_quote_in_v2`, with a unified mandatory account list supporting SOL- and other quote-mint pairs. For `buy_v2`, `max_sol_cost`/maximum quote cost includes protocol and creator fees; sells specify a minimum quote output after applicable fees. The exact account order, PDAs, discriminators, and integer formulas must come from the pinned IDL/docs and be checked against landed transactions ([Pump buy docs][pump-buy], [Pump IDL][pump-idl]).

Do not infer SOL pairing only from historic defaults: V2 introduces quote mint and quote token program inputs. Native-SOL transfer behavior and wrapped-SOL-shaped PDA constraints are protocol details that the decoder must preserve.

### Reserves and fees

For a bonding curve, quote from the decoded on-chain `BondingCurve`, `Global`, quote-mint/token-program state, and live Pump fee program configuration. Never use UI display numbers as the arithmetic source. Integer division and per-component ceiling order are part of the protocol. A mathematically equivalent-looking rearrangement can differ by lamports or base units.

For PumpSwap, the official pool specification requires:

```text
effective_quote_reserves = raw_quote_vault_amount + Pool.virtual_quote_reserves
effective_base_reserves  = raw_base_vault_amount
```

`virtual_quote_reserves` is currently documented as zero on all pools, but is an `i128` field intended for future nonzero use. It belongs in the schema now. Validate the signed addition, reject a nonpositive effective reserve, and record raw and effective values separately.

Canonical PumpSwap pools use market-cap-tiered fees from the on-chain Pump Fee Program; noncanonical pools use their configured/flat path. Pump's public fee page is useful orientation, but it explicitly says the smart contracts determine the charged fees and may change them. The quote artifact therefore records the decoded fee-config account and selected tier, not a hard-coded web table.

Market cap and tier selection must be computed from raw integer reserves/supply according to the pinned fee-program definition. Decimal/UI conversions happen only after the exact tier and fee arithmetic. Record protocol, creator, LP, cashback/buyback, and any transfer-fee components separately rather than reporting one unexplained percentage.

**Invariant:** a quote is valid only for the exact set of account hashes in its state manifest. Accounts fetched at materially inconsistent slots produce `inconsistent_state`, not a number.

## Meteora DLMM

### State needed for an honest quote

A DLMM price is not “reserve X / reserve Y.” The official SDK state and quote paths use:

- `LbPair`, including active bin, bin step, fee parameters, volatility accumulator/reference state, pair/fee mode, bitmap, and activation/status fields;
- all traversed `BinArray` accounts plus bitmap extension when applicable;
- reserve token accounts and mint/token-program accounts;
- oracle/clock or other accounts required by the selected pair/fee mode;
- Token-2022 transfer-fee configuration and transfer-hook extra accounts;
- limit-order liquidity and pool mode where supported.

The official TS API exposes exact-in `swapQuote` and exact-out `swapQuoteExactOut`; current results include requested/consumed input, output, fee/protocol fee, min-out or max-in, price impact, traversed bin arrays, end price, and fee-on-input behavior. The Rust `commons` code contains equivalent categories of bin traversal, dynamic fee update, Token-2022, and position parsing, but equivalence is a test target, not assumed fact.

Every quote must disclose partial-fill/unconsumed input. “Expected output” without the end bin, traversed arrays, fee state, transfer-fee treatment, and state manifest is not a reproducible quote.

### Positions are custody plus a per-bin schedule

The operator's mental model is implementable: a DLMM position is not one indivisible LP blob. It owns liquidity across a bounded set of bins, and the protocol exposes several different mutations:

- **Add:** add X/Y into an existing position under a strategy or explicit `BinAndAmount[]` distribution. This adds custody/liquidity; it does not first remove the old schedule.
- **Remove:** remove a basis-point fraction across a specified bin interval. The current SDK can return multiple transactions when the range is large, can optionally claim fees/rewards, and can optionally close. It returns the position's current X/Y composition; it is not a swap back to the originally deposited asset.
- **Rebalance:** simulate a desired distribution off-chain, then create the on-chain `rebalance_liquidity` instruction and any missing-bin-array initialization instructions. This can change the schedule of the existing position and model top-ups/withdrawals. It is the important alternative to close/reopen churn.
- **Extend/shrink:** current dynamic positions can cover broader ranges (the changelog documents extension up to 1,400 bins), with rent and transaction-size consequences.

The official [DLMM TS reference][meteora-reference] returns `initBinArrayInstructions[]` separately from `rebalancePositionInstruction[]`. Therefore “rebalance is atomic” is too broad. The final liquidity mutation may be one instruction, while prerequisite bin-array initialization may land separately. Broad positions and removals may be chunked across multiple transactions. A future planner must model partial sequence progress and reconcile each transaction.

**Gap:** this research has not proven exactly which rebalance combinations are single-instruction for every current position type, Token-2022 mint, bitmap state, and bin width. The conformance spike decodes representative outputs but does not submit them.

**Critical semantic constraint:** rebalancing does not create the desired inventory. If moving a range requires more X or Y than the position plus authorized top-up contains, a swap or a smaller schedule is required. Swap authority is separate and defaults false. “Recenter while preserving SOL” is a constrained allocation problem, not a UI convenience flag.

### Effective fee and inventory computation

For DLMM, quote and position views should retain:

1. token quantities in each bin before any UI decimal conversion;
2. dynamic base/variable fee inputs and updated volatility state used by the quote;
3. fee-on-input/output mode, protocol share, Token-2022 transfer fee on each relevant transfer;
4. exact bin traversal and rounding at each step;
5. claimable fees/rewards separately from principal inventory;
6. rent and account-creation costs separately from trading/LP economics.

Do not calculate LP PnL from deposit versus current withdrawal alone. The financial plane must distinguish inventory transformation, claimed/unclaimed fees, rewards, top-ups/withdrawals, swap costs, network/rent costs, external transfers, and mark convention.

## Quotes versus transaction simulation

These are different artifacts:

- a **state quote** is a deterministic, local calculation from a captured set of accounts;
- an **RPC simulation** executes serialized transaction bytes against a node bank and can expose logs, errors, return data, and CU consumption;
- a **shadow fill model** estimates what could have landed given observed future states and latency; it is neither of the above.

Solana's [`simulateTransaction`][simulate-transaction] can replace a recent blockhash and optionally return accounts, but it still consumes transaction bytes. Under the current R0–R4 authority boundary, we do not construct such bytes. State quotes are allowed; transaction simulation begins only when R5 separately authorizes an unsigned builder and hostile-byte guard. At that point, simulation results must be tied to the exact message hash and simulation slot, and a successful simulation must never be treated as landing evidence.

For now, transaction cost models may use observed landed analogues and documented rent/account sizes. Mark these as estimates. They must not be hidden inside venue output.

## Future write plane: isolation before speed

This section is a design constraint for a later gate, not permission to implement it.

### Authority graph

```text
operator capability (bounded venue/action/size/expiry)
       |
       v
planner -> typed economic intent + candidate unsigned message
       |
       v
independent decoder/guard -> approved exact message hash
       |
       v
isolated signer -> signature only, no RPC credentials or submit method
       |
       v
identical-byte submitter -> rebroadcast only, no rebuild/re-sign
       |
       v
multi-source confirmation -> asset/state reconciliation
```

Guard invariants include:

- resolve every ALT and decode legacy/v0 messages independently of the builder;
- exact program IDs, discriminators, account order, signer/writable flags, token programs, pools/positions, owners, and economic bounds;
- reject unknown instructions, opaque CPI enablers, unexpected address-table contents, unexpected durable nonce use, and unapproved account creation/closure;
- bound gross input, minimum output, position range, per-bin allocation, top-up/withdrawal, rent, CU limit, CU price, Jito tip, and total SOL outflow;
- separate spot, LP add/remove, rebalance, and claim capabilities; swap remains false unless explicitly granted;
- signer receives only a canonical validated message/capability reference, and cannot access the network;
- submitter cannot mutate, create, or sign a message.

The old sidecar/guard is not this proof boundary merely because comments say “unsigned builder only.”

### Confirmation state machine

```text
PROPOSED
  -> GUARDED
  -> SIGNED
  -> SUBMITTED(signature, message_hash, blockhash, last_valid_block_height)
       -> PROCESSED -> CONFIRMED -> FINALIZED
       -> LANDED_FAILED -> FINALIZED_FAILED
       -> EXPIRED_UNSEEN
       -> UNKNOWN (provider disagreement / coverage gap)
```

Preserve each provider submission attempt, response, and time. Rebroadcast the same signed bytes while its blockhash remains valid; do not manufacture a new signature while the earlier transaction can still land. A provider acceptance response or Jito bundle ID means received, not landed.

Reconciliation records the exact slot/index, `meta.err`, fee/CU/logs/inner instructions, pre/post assets, account creations/closures, protocol state transition, and finality changes. `processed` is provisional. A failure may still consume network fees. `expired_unseen` requires both blockheight expiry and adequate multi-source coverage; otherwise it remains `unknown`.

### Priority fees and Jito

Solana defines priority fee as:

```text
ceil(compute_unit_price_micro_lamports * compute_unit_limit / 1_000_000)
```

It is based on the requested CU limit, not actual CU consumed. [`getRecentPrioritizationFees`][recent-priority-fees] can take writable accounts and exposes only a recent node cache; Solana's own integration guide says there is no perfect fee estimator and an unscoped result is often uninformative. Treat fee selection as an empirical landing policy with hard spend caps, not a constant.

[Jito's official send documentation][jito-send] says its `sendTransaction` proxy always uses `skip_preflight=true`; `bundleOnly=true` sends a single-transaction bundle, and bundles contain at most five signed transactions, execute in order and all-or-nothing within one slot, compete on tips, and require status checking. Submission acknowledgment does not guarantee landing. Jito therefore adds a submission/auction venue and another explicit cost component; it does not replace Solana confirmation or our reconciliation.

Jito is irrelevant to R0–R4 and should not influence the protocol runtime choice. At a later tiny-live landing gate, compare ordinary RPC fanout and Jito using identical capability, fee-cap, latency, adverse-selection, and finality metrics. A tip is never allowed to bypass the total-cost bound.

## Provider versus self-host

| Option | Strength | Failure/cost boundary | Initial posture |
|---|---|---|---|
| Public Solana RPC | Zero setup, useful for development | [Official endpoints][public-rpc] are rate-limited and explicitly not intended for production; history and websocket capacity are insufficiently guaranteed | Smoke tests only |
| Managed dedicated RPC/WS | Fastest path to two independent sources and archive options | Vendor retention, filter, transformation, quota, and outage behavior; trust concentration | Use two materially independent providers and measure them |
| Managed Yellowstone | Rich raw stream, write versions/indexes, optional bounded replay | Proto/version and server-feature drift; replay window is configured, not history | Candidate after baseline recovery works |
| Self-hosted Agave RPC + Geyser | Maximum control over raw callbacks, filters, retention policy | Validator-class operations: snapshots/catch-up, ledger/accounts storage, network, upgrades, monitoring, plugin backpressure and data loss | Do not start here |
| Own archival pipeline from provider stream | Canonical prospective evidence and replay | Only complete from start; source gaps remain gaps | Required from first acquisition spike |

Self-hosting does not recover time before the node/archive existed, and it can create worse gaps if operations are immature. Managed providers do not eliminate trust. The sensible first architecture is hybrid: two independent raw-compatible sources, our own immutable capture, explicit coverage accounting, and a provider conformance suite. Revisit self-host only after measured bandwidth/history cost, latency, or evidence-fidelity failures justify it.

Provider selection tests should score raw fidelity, finalized backfill, reconnect recovery, history horizon, rate/size limits, slot/fork behavior, log/inner-instruction completeness, ALT handling, Token-2022 metadata, latency distribution, support incident evidence, and price. Marketing latency numbers are not protocol facts.

## Runtime choices

### Native Rust protocol plane

**Known advantages:** official Solana core, official Pump Rust client, strongest Yellowstone client path, fixed-width integer types, mature binary/protobuf tooling, and a natural future home for an independent hostile-byte guard.

**Costs/gaps:** dependency/version churn across Solana/Anchor crates; Meteora Rust is a repository workspace component rather than a polished versioned equivalent of the TS package; exact parity for new fee modes, limit orders, Token-2022, and rebalance helpers is unproven.

**Use if:** the spike proves raw decode and Pump parity, and either proves Meteora parity or defines a narrow TS exception.

### TypeScript protocol plane

**Known advantages:** current official Pump, PumpSwap, and Meteora packages, most official examples, and the fastest reference implementation for quotes and position semantics.

**Costs/gaps:** Meteora and Pump packages use the legacy `@solana/web3.js`/Anchor ecosystem while Solana now recommends Kit; BN/Decimal/JS-number boundary mistakes are easy; current Pump npm source repositories are not publicly auditable; package-rich processes have a larger future signer attack surface.

**Use if:** Meteora parity forces it, but isolate the process. Its output is a versioned assertion with inputs and hashes, never trusted unsigned bytes. Keep keys and submission out.

### Native C# protocol plane

**Known advantages:** .NET 10 is installed; good domain modeling, services, tooling, and UI/application options; Solnet can cover general RPC, streaming, and wire decoding; Anchor IDLs can generate C# shapes.

**Costs/gaps:** Solana calls Solnet community-maintained; no first-party Pump/PumpSwap/Meteora clients were found; IDL generation does not implement quote, dynamic-fee, bin, transfer-hook, or rebalance semantics. A native port would create a third arithmetic implementation before we have an oracle.

**Use if:** as a consumer of canonical protocol artifacts, or much later after a differential suite makes a C# port safe. Do not select it as the initial protocol reference.

### FFI versus sidecar

FFI (Node-API, shared Rust library, P/Invoke) couples allocation, ABI, crash, and upgrade boundaries and makes it harder to enforce “no secret/no send.” There is no demonstrated performance need for it in the quote/control loop.

A process sidecar has overhead but gives us a killable, resource-limited, separately pinned trust boundary. If needed, use framed protobuf over stdin/stdout or a Unix socket, deny wallet files and submit RPC methods, cap requests, and include all input account hashes in every response. The caller revalidates shape and bounds. Do not let a TypeScript sidecar return opaque economic truth without a state manifest.

### Python/solders

The compost uses Python plus `solders`, which Solana classifies as community SDK support. It remains useful for research and fixture analysis, but there is no current first-party high-level Pump/Meteora Python surface equivalent to the TS/Rust options. It should not become the canonical protocol runtime by inertia.

## What to reuse from `joshibot`, and what not to trust

**Observed compost:** `shitcoims_lpexec` has Python/solders integration and a Node sidecar pinned to `@meteora-ag/dlmm@1.9.14`, `@solana/web3.js@1.98.4`, and `bn.js`. `builder.cjs` fetches state/blockhash and compiles unsigned v0 transactions for pool reads, position reads, add, and remove. `guard.py` independently decodes messages, resolves ALTs, checks signers/programs/opcodes/pools/positions, and caps compute settings.

Useful donors:

- captured pool/position identifiers and known historical transactions;
- adversarial guard fixtures and the idea of independent ALT expansion;
- account allowlist concepts and explicit no-swap policy;
- observed SDK edge cases, result samples, and rent/CU measurements.

Do not inherit:

- the claim that a process is safe because it is called “unsigned-builder-only”;
- current instruction allowlists/discriminators/account orders without current IDL comparison;
- one-process-per-request behavior, blockhash fetching, SDK transaction rewriting, or JSON number conversions;
- any position semantic inferred from the Meteora UI;
- package trust or quote correctness without exact inputs and cross-implementation parity.

The old sidecar is a hostile fixture producer until it passes the same conformance suite as a fresh adapter. In R0–R4, there is no reason to expose its builder commands at all.

## Invariants and failure containment

1. Raw bytes and provider envelope are retained before decoding.
2. Every decoded assertion names its raw input, decoder, IDL/source hash, and executable program identity where available.
3. Economic integers never cross a boundary as floating point.
4. A quote identifies every account state and slot/hash it used; mixed/incomplete state is visible.
5. WebSocket/Geyser disconnect means `coverage_unknown` until bounded recovery succeeds.
6. A migration gap is a first-class Pump lifecycle state.
7. DLMM partial fill, chunking, prerequisites, and current token composition are never collapsed into one “rebalance succeeded” flag.
8. Event logs corroborate; they do not replace transaction/meta and balance reconciliation.
9. Provider agreement is measured on raw/normalized facts, not merely on matching UI price.
10. No read/reference process has wallet secrets, signer access, or a callable submit endpoint.
11. Future signed bytes are immutable through submission; confirmation and economic reconciliation remain separate.
12. Unknown protocol version, account extension, discriminator, token extension, fee mode, or executable program hash fails closed into raw capture—not guessed decoding.

Adverse cases that must be fixtures include:

- v0 transaction with multiple ALTs and Pump/Meteora CPI below another program;
- truncated/missing Anchor logs but complete inner instruction data;
- failed transaction that still pays fees;
- websocket disconnect spanning fork/dead slots and duplicate replay;
- curve completion without canonical pool, and pool observation before migration transaction backfill;
- nonzero or negative-edge `virtual_quote_reserves` decoding;
- fee tier boundary plus rounding at one-unit sizes;
- Token-2022 transfer fee epoch change and transfer hook;
- DLMM empty active bin, limit-order liquidity, exact-out, partial fill, and stale bin array;
- position remove/rebalance split across prerequisites/chunks with only a prefix observed;
- manual wallet action interleaved with an operator episode;
- SDK/package/IDL update with unchanged friendly type names but changed bytes.

## Read-only conformance spike that chooses the runtime

### Question

Can Rust reproduce the official TS interpretations closely enough to own the protocol plane, especially Meteora, while two independent providers supply recoverable raw evidence? If not, exactly what narrow function must remain in an untrusted TS process? C# is measured as a consumer/decoder candidate, not presumed equivalent.

### Hard safety envelope

- mainnet reads only through an RPC proxy that allows only account/block/transaction/signature/slot and subscription methods;
- explicitly block `sendTransaction`, `requestAirdrop`, `simulateTransaction`, Jito endpoints, wallet adapters, secret/keypair inputs, and all transaction-builder entry points;
- no new keypair generation, blockhash request, unsigned message construction, signing, or submission;
- captured historical transaction bytes may be decoded but never mutated or resubmitted;
- all package installs are locked and checksummed; the spike records runtime, package, repo/IDL, proto, and program-data identities.

### Fixture set

Capture, from two independent RPC providers at finalized commitment:

- at least 10 open Pump bonding curves, including SOL and non-SOL quote mints if available;
- at least 5 completed-unmigrated observations if naturally observable, plus 10 completed/migrated histories;
- at least 10 canonical PumpSwap pools and 3 noncanonical pools, including fee-tier boundary neighborhoods;
- at least 10 DLMM pools spanning pair/fee modes, active-bin liquidity shapes, bitmap extension, and Token-2022 where available;
- every accessible position belonging to the research wallet plus public example positions covering ordinary and dynamic/extended layouts;
- 100 finalized historical transactions across buys, sells, migration, DLMM swaps, add/remove, rebalance, failures, v0/ALT, and inner instructions.

If a rare case cannot be found, mark the row untested; do not synthesize confidence. Store exact provider payloads, raw bytes, account hashes, slots, and acquisition coverage.

### Implement only three read harnesses

1. **TS oracle:** pinned Pump/PumpSwap SDKs and `@meteora-ag/dlmm@1.9.14`; account/position decoding and local quote methods only.
2. **Rust candidate:** official Solana wire crates, `pump-rust-client@0.1.11`, and Meteora `commons`/`dlmm_interface` pinned to commit `fb02e51ae677bbd18e76543f702dae40632426db`; decoding and local quote methods only.
3. **C# probe:** Solnet raw transaction/message decode plus generated account/instruction types for a small Pump and DLMM subset. Do not port quote math. Measure missing features and fidelity.

All three emit the language-neutral artifacts above. None may emit a transaction.

### Tests

**Wire and account parity**

- byte-for-byte public keys, owners, discriminators, field integers, account extensions, signers/writables, instruction data, ALT-expanded keys, and invocation position;
- decoded assertions re-encode only in a test buffer, where supported, and match the original field bytes;
- both providers converge at finalized slots or produce an explicit provider conflict/coverage gap.

**Pump/PumpSwap parity**

- PDA and lifecycle classification;
- exact-in/exact-out or exact-token quote results for a grid of 1-unit, small, ordinary, near-reserve, and fee-tier-boundary sizes;
- every fee component and rounding step;
- raw/effective reserve handling, including an offline fixture with nonzero `virtual_quote_reserves` solely to test decoding/arithmetic;
- migration transaction and canonical pool identity.

**DLMM parity**

- pool, bin array/bitmap, dynamic position, per-bin inventory, fees, rewards, and token-extension decode;
- exact-in and exact-out quote grids in both directions, including partial fills and empty bins;
- traversed bin arrays, end bin/price representation, consumed input, output, fee/protocol fee, fee-on-input mode, and transfer fees;
- read-only invocation of rebalance *simulation* helpers to compare proposed per-bin deposits/withdrawals and missing-bin-array requirements. Do not call transaction-building `rebalancePosition`; inspect source signatures/recorded historical rebalance bytes for instruction semantics instead.

**Acquisition recovery**

- run HTTP+WebSocket and one Yellowstone source, if available, against the same filters for 24 hours;
- deliberately disconnect each client three times without sleeping the whole harness; reconnect from the recorded watermark, do bounded finalized backfill, and report duplicates, omissions, forks, latency, replay horizon, and provider disagreement;
- replay the captured tape offline and require deterministic artifact hashes.

**Operational measurements**

- cold/warm startup, memory, CPU, p50/p95/p99 decode and quote latency;
- package/build size, compile/install failures, crash isolation, schema evolution effort;
- number and severity of protocol features that require TS-only code or C# manual ports.

### Acceptance rules

- **Choose Rust for the core protocol plane** if wire/account decoding is exact on all tested fixtures, Pump/PumpSwap integer outputs are exact on all grid cases, and no unexplained finalized-provider disagreement remains.
- **Use Meteora Rust natively** only if every tested DLMM integer result and state dependency matches the TS oracle exactly, with zero silent partial/stale cases and all required current position/fee modes covered.
- **Otherwise use a narrow Meteora TS sidecar** for the mismatching decode/quote functions. Rust still owns raw capture and normalization; TS receives explicit account bytes and returns a manifest-bound assertion. Keep the TS oracle in CI even if Rust passes.
- **Do not select C# as protocol core** unless it unexpectedly demonstrates exact wire/account parity with no manual arithmetic port and offers a measured operational advantage. It may be selected for the application/domain process independently.
- **Do not select Yellowstone as the sole source.** It may replace one low-latency WebSocket path only after replay/recovery behavior is measured; finalized HTTP backfill and a second source remain.
- Any unexplained one-unit economic mismatch, unknown account extension, missing Token-2022 input, or nonreproducible quote blocks the affected adapter. Performance never overrides correctness.

### Deliverables and decision record

The spike ends with:

- immutable raw fixture bundle and coverage report;
- artifact schemas plus golden JSON/protobuf projections;
- TS-vs-Rust-vs-C# differential matrix with exact mismatches;
- provider reconnect/backfill report;
- dependency/SBOM and source/IDL/program identity manifest;
- a one-page runtime ADR selecting: `Rust`, `Rust + Meteora TS sidecar`, or `stop and research`; and separately `HTTP/WS + archive` versus `HTTP/WS + Yellowstone + archive`.

This is the smallest experiment that materially changes the architecture. Anything smaller merely confirms that each SDK can print a pool; anything larger starts building an execution system before we know which interpretation boundary is trustworthy.

## Explicit gaps after this research

- Pump's current official npm tarballs could not be tied to publicly retrievable source repositories.
- Meteora Rust `commons` parity with npm 1.9.14 across every current pair/fee/limit-order/Token-2022/rebalance path is not established.
- The atomicity and prerequisite/chunking behavior of every DLMM rebalance shape is not established without decoding representative live history and, later, an authorized local/testnet builder study.
- Complete historic Pump/Meteora program coverage from any candidate managed provider is not established.
- Provider-specific Yellowstone retention, filters, and optional method support are unknown until endpoint conformance.
- Priority-fee/Jito landing policy, capacity, and adverse selection cannot be inferred from documentation; they require a separately authorized shadow/tiny-live study.
- Program upgrades can invalidate all of the above. Program-data identity and IDL/package pins must be continuously observed.

## Source register

Accessed 2026-08-16. Registry versions and repository heads are point-in-time observations; lock them in the spike manifest rather than relying on `latest` or `main`.

### Solana, Anchor, acquisition, and landing

- [Solana SDK list and community SDK warning][solana-sdk-list]
- [Solana IDLs and C# generator][solana-idl]
- [Codama client generation][codama]
- [Anchor IDL discriminators][anchor-idl] and [events/log truncation][anchor-events]
- [`getTransaction`][get-transaction], [`getBlock`][get-block], [`getSignaturesForAddress`][get-signatures], [`simulateTransaction`][simulate-transaction], and [WebSocket methods][solana-websocket]
- [Agave Geyser plugin interface source][agave-geyser]
- [Yellowstone gRPC repository/protobuf][yellowstone] and [changelog][yellowstone-changelog]
- [Solana fee structure][solana-fees] and [`getRecentPrioritizationFees`][recent-priority-fees]
- [Solana public endpoint limits and production warning][public-rpc]
- [Jito low-latency transaction and bundle API][jito-send]

### Pump and PumpSwap

- [Pump public protocol docs and IDLs][pump-docs]
- [Pump consumer bonding-curve/graduation overview][pump-bonding]
- [Pump program and migration][pump-program]
- [Pump V2 buy instruction][pump-buy]
- [Pump program IDL][pump-idl]
- [PumpSwap pool, effective reserves, and canonical pool][pump-swap]
- [Pump public fee schedule and on-chain-determination warning][pump-fees]
- [Pump TypeScript SDK on npm][pump-sdk-npm], [PumpSwap SDK on npm][pump-swap-sdk-npm], and [Pump Rust client on crates.io][pump-rust]

### Meteora

- [Meteora DLMM SDK repository][meteora-sdk]
- [Official DLMM TypeScript SDK reference][meteora-reference]
- [DLMM changelog][meteora-changelog]
- [`@meteora-ag/dlmm` on npm][meteora-npm]

[solana-sdk-list]: https://solana.com/docs
[solana-idl]: https://solana.com/docs/programs/idls
[codama]: https://solana.com/docs/programs/codama/clients
[anchor-idl]: https://www.anchor-lang.com/docs/basics/idl
[anchor-events]: https://www.anchor-lang.com/docs/features/events
[get-transaction]: https://solana.com/docs/rpc/http/gettransaction
[get-block]: https://solana.com/docs/rpc/http/getblock
[get-signatures]: https://solana.com/docs/rpc/http/getsignaturesforaddress
[simulate-transaction]: https://solana.com/docs/rpc/http/simulatetransaction
[solana-websocket]: https://solana.com/docs/rpc/websocket
[agave-geyser]: https://github.com/anza-xyz/agave/tree/master/geyser-plugin-interface
[yellowstone]: https://github.com/rpcpool/yellowstone-grpc
[yellowstone-changelog]: https://github.com/rpcpool/yellowstone-grpc/blob/master/CHANGELOG.md
[solana-fees]: https://solana.com/docs/core/fees/fee-structure
[recent-priority-fees]: https://solana.com/docs/rpc/http/getrecentprioritizationfees
[public-rpc]: https://solana.com/docs/references/clusters
[jito-send]: https://docs.jito.wtf/lowlatencytxnsend/

[pump-docs]: https://github.com/pump-fun/pump-public-docs
[pump-bonding]: https://pump.fun/docs/bonding-curve
[pump-program]: https://github.com/pump-fun/pump-public-docs/blob/main/docs/PUMP_PROGRAM_README.md
[pump-buy]: https://github.com/pump-fun/pump-public-docs/blob/main/docs/instructions/BUY.md
[pump-idl]: https://github.com/pump-fun/pump-public-docs/blob/main/idl/pump.json
[pump-swap]: https://github.com/pump-fun/pump-public-docs/blob/main/docs/PUMP_SWAP_README.md
[pump-fees]: https://pump.fun/docs/fees
[pump-sdk-npm]: https://www.npmjs.com/package/@pump-fun/pump-sdk
[pump-swap-sdk-npm]: https://www.npmjs.com/package/@pump-fun/pump-swap-sdk
[pump-rust]: https://crates.io/crates/pump-rust-client

[meteora-sdk]: https://github.com/MeteoraAg/dlmm-sdk
[meteora-reference]: https://github.com/MeteoraAg/docs/blob/main/developer-guides/dlmm/typescript-sdk/reference.mdx
[meteora-changelog]: https://github.com/MeteoraAg/dlmm-sdk/blob/main/CHANGELOG.md
[meteora-npm]: https://www.npmjs.com/package/@meteora-ag/dlmm
