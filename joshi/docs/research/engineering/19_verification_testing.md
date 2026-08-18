# Engineering lane 19 — verification and testing

Status: engineering research; no implementation or live-capital authorization.

Tool facts and links were checked against current maintainer or official documentation on
2026-08-16. Versions must be pinned and rechecked when an implementation language is selected.

## 1. Position

Joshi should earn engineering pride by making consequential failures easy to state, hard to hide,
cheap to reproduce, and progressively less likely as authority rises. It should not earn pride by
accumulating theorem-prover syntax around an unstable ontology.

The verification program has four priorities, in order:

1. preserve evidence and financial truth through duplicates, gaps, corrections, crashes, and
   replay;
2. distinguish observed, hypothetical, intended, signed, submitted, landed, and reconciled effects;
3. prevent authority from widening or repeating silently;
4. prove small stable kernels only when testing leaves an important state space uncovered.

The default stack is ordinary unit and integration tests, property-based generators, executable
state-machine models, deterministic simulation, differential checks, hostile-input fuzzing,
crash/recovery testing, and fixed replay corpora. Model checking or deductive proof is added at a
specific assurance gap. “Formally verified” is never a product-wide adjective.

This lane does not select OCaml, C#, Rust, a database, or a formal tool. It defines a bakeoff and
an assurance case that any selected stack must pass.

## 2. The assurance case

Every promoted capability should carry a small, reviewable argument rather than a pile of tests:

```text
claim
  -> hazards that could make the claim false
  -> invariants and explicit environmental assumptions
  -> architectural enforcement mechanism
  -> executable and/or formal evidence
  -> known residual risk and operational detector
  -> owner, tool/version, last run, and expiry condition
```

The evidence must be attached to the exact code, schema, protocol/IDL version, fixture corpus, and
authority level it supports. Coverage percentage, test count, fuzzing hours, and a green proof are
inputs, not claims.

### 2.1 Top claims by authority stage

| Stage | Top-level claim | Principal evidence | Claims explicitly not made |
|---|---|---|---|
| read-only, R1–R3 | Joshi can restart and replay without fabricating, losing silently, time-travelling, or causing external effects | state-machine properties, crash matrix, schema round trips, fixed adversarial replay, chain reconciliation, effect-sink tests | that sources are complete, Pump-equivalent, or economically predictive |
| shadow, R4 | Every proposal is cutoff-safe, size-specific, reproducible, and visibly hypothetical; uncertainty is smaller than the question being studied | deterministic quote simulator, official-SDK differential tests, latency/fill envelopes, provider and finalized-chain conformance, shadow-path replay | that a hypothetical quote would have filled, landed, or earned money |
| unsigned/signing lab, R5–R6 | Only an exact reviewed plan can become exact bytes; signing cannot widen it; no component can broadcast | hostile-byte parser tests, plan/byte conformance, simulation postconditions, capability state-machine model, signer isolation tests | that simulation predicts landing or that signed bytes were authorized for broadcast |
| tiny live authority, R7 | A manually initiated attempt has bounded scope, cannot double-spend its reservation or mutate on retry, and is reconciled to chain | attempt protocol model checking, crash/chaos tests, identical-byte checks, submit ledger, finalized wallet deltas, independent guard | that the venue will fill at the simulated price or that future automation is safe |
| bounded automation, R8 | Repeated attempts remain within aggregate limits under concurrency, delay, partial failure, expiry, and restart | controlled-schedule testing, model checking of reservations/limits, adversarial live canaries, aggregate reconciliation and kill drills | open-ended autonomy, profitable operation, or safety outside the issued capability |

### 2.2 Evidence classes

The suite should label what each result establishes:

- **example:** one named behavior remains understandable;
- **property:** many generated inputs satisfy an executable predicate;
- **model conformance:** implementation traces refine a smaller executable model;
- **differential agreement:** two independent implementations agree on a declared domain;
- **wire/chain conformance:** bytes or state agree with an authoritative external artifact;
- **bounded proof:** a property holds for the modeled bounds and assumptions;
- **deductive proof:** a stable algorithm meets a stated contract under stated axioms;
- **operational evidence:** production-like crashes, delays, providers, and finalized outcomes match
  the modeled envelope.

None subsumes all the others. Two implementations can agree and both be wrong; a proof can prove
the wrong model; a fuzz target can never reach the dangerous state; and chain conformance can say
nothing about a transaction that was never submitted.

## 3. One deterministic laboratory before many test frameworks

The most valuable testing component is a language-neutral deterministic laboratory. Domain logic
should receive time, randomness, source events, provider responses, chain commitment transitions,
and effect capabilities through explicit interfaces. A test owns:

- a seed and generated command trace;
- a logical wall clock plus chain slot/block-height clocks;
- an ordered delivery schedule distinct from source order;
- named source/provider state and failure script;
- a durable-store failpoint schedule;
- an effect sink whose ceiling is part of the fixture;
- a stable serialization of all inputs, outputs, and decisions.

No model or projection may read the real clock, global RNG, ambient environment, network, or
filesystem directly. Production adapters do; the semantic core does not. A failed property must
emit a self-contained trace that can be committed as a regression fixture.

Three simulators should remain conceptually separate:

1. **Evidence simulator:** delivers duplicates, conflicts, gaps, finality changes, corrections,
   and crashes to collectors/projections.
2. **Market/quote simulator:** replays exact captured account states and quote observations, adding
   controlled latency and state movement. It estimates apparatus error; it is not a market model.
3. **Authority simulator, later:** exercises plan, reservation, construction, signing, submission,
   retry, expiry, and reconciliation. Its network and chain are adversarial state machines.

Determinism applies to the test harness and replay transformation, not to claims that the market is
deterministic. The simulator must preserve nondeterminism as explicit choices rather than erase it
with one convenient ordering.

## 4. Executable state-machine models

### 4.1 Episode and inventory model

The reference model should be deliberately smaller than the application. It tracks:

- operator episode identity and status (`open`, `dormant`, `resolved`, `reopened`);
- watch state, including `watching_flat`;
- zero or more non-overlapping inventory epochs per `(portfolio domain, mint)`;
- lots, quantities, proceeds, fees, and basis quality;
- prospective management tranches and book attribution;
- raw acts, later assertions, corrections, and current versioned meaning.

Generated commands should include open/watch/arm/cancel, external fill arrival, partial exit, full
exit, flat interval, re-entry, runner promotion, book transfer, late attribution, correction,
resolve/reopen, duplicate delivery, and repeated equal-valued fills with distinct event identity.

Core properties:

- a full exit ends an inventory epoch but does not resolve the episode;
- a re-entry starts a fresh basis epoch without requiring a new episode;
- watching flat creates no inventory or PnL;
- product macros expand to semantic records; they cannot manufacture fills;
- moving fungible quantity between books changes attribution, not consolidated balance or PnL;
- repeated equal fills are retained when their source event identities differ;
- redelivery of the same source event is idempotent;
- a correction is additive provenance, never an in-place rewrite of evidence;
- all projected remaining lot quantities sum exactly to the reconciled holding or expose a named
  unresolved residual;
- replaying the same evidence and versions twice yields the same semantic digest;
- witnessed, knowledge-cutoff, and retrospective replay never collapse into one view.

The implementation should run each generated command against both the pure model and the real
storage/projection boundary. Shrinking should minimize the command trace, not merely individual
field values; the useful counterexample is often “fill, crash, duplicate, re-enter,” not a smaller
mint string.

### 4.2 Observation, cursor, and projection model

State includes source cursor/high-water mark, spool records, durable observations, blob hashes,
coverage intervals, projection offset/version, and pending effects. Commands include receive,
persist, conflict, cursor advance, crash at each boundary, restart, backfill, reorg/finality update,
projection, migration, replay, and erasure/tombstone under an explicit policy.

Properties:

- the durable cursor never claims evidence that is absent;
- restart repeats work rather than skipping it;
- one observation attempt retains its identity even when bytes equal an earlier blob;
- same source identity plus different bytes becomes a visible revision/conflict;
- collector silence never creates a market-silence assertion;
- a projection checkpoint advances only after its output is durable;
- replay cannot call notification, model-service, proposal, signing, or submission effects;
- backfill and finality updates can change retrospective projections without changing witnessed
  replay;
- schema/projection upgrades create a new version and difference report rather than mutating the
  old answer.

### 4.3 Transaction-attempt model, only when R5 is separately authorized

A proposed lifecycle is:

```text
proposed
  -> reserved
  -> constructed_unsigned
  -> simulated
  -> guard_accepted | refused
  -> signature_issued
  -> submitted(bytes_hash, signature)
  -> rebroadcast_same_bytes*
  -> landed_success | landed_revert | expired_unseen
  -> reconciled
  -> reservation_released
```

Simulation may repeat as chain state changes, but a state change invalidates the prior binding. A
new blockhash or any other byte mutation after signature is a new plan/attempt, not a retry.

The model generates concurrent proposals, duplicate operator requests, stale quotes, slot advance,
capability expiry, crashes after every durable step, signer timeout, RPC disagreement, dropped
submissions, landed reverts, delayed success, and reconciliation arriving before the submitter's
response.

Safety properties:

- capability and effect ceilings are monotone; no arm or retry widens them;
- one reservation backs at most one live economic attempt and every live attempt has one durable
  reservation;
- signing is unique for `(capability, plan hash, attempt nonce)`;
- all rebroadcasts are byte-identical to the signed message;
- a retry with changed bytes requires a new guard decision and, when applicable, new approval;
- simulation is never authority;
- expiration releases capacity only after the system has ruled out a late landing under the
  declared reconciliation policy;
- landed effects are derived from chain/wallet deltas, not the plan or simulation;
- unknown programs, accounts, writable privileges, token mints, address-table entries, or effect
  classes cause refusal;
- aggregate wallet, asset, venue, book, and correlated-exposure limits count reservations plus
  reconciled holdings;
- restart cannot sign, submit, or debit twice;
- no unsigned lab path contains a broadcast-capable dependency or credential.

Liveness properties should be modest: every durable attempt eventually becomes reconciled or a
visible unresolved incident *assuming* bounded provider recovery and chain observability. Do not
prove eventual network delivery.

## 5. Property and model-based testing by candidate language

### 5.1 OCaml

Current primary tooling is credible for a pure semantic kernel:

- QCheck supplies generated properties and shrinking; QCheck2 integrates shrinking into generators
  ([current OCaml package documentation](https://ocaml.org/p/qcheck-core/latest/doc/index.html)).
- `qcheck-stm` generates command programs and compares a system under test with a pure functional
  model; it supports sequential and parallel/domain modes, while its thread-concurrency mode is
  explicitly described as experimental
  ([qcheck-stm documentation](https://ocaml.org/p/qcheck-stm/latest/doc/index.html)).
- Crowbar combines QuickCheck-style properties with AFL-driven fuzzing
  ([current Crowbar package](https://ocaml.org/p/crowbar/latest)).

**Likely advantage:** algebraic data types and pure transition functions make illegal domain states,
versioned events, and trace models concise. The state-machine model can be the natural core rather
than a test-side imitation.

**Likely cost:** Pump's current public docs point to TypeScript and Rust SDKs, and Meteora publishes
TypeScript plus Rust integration, not an official OCaml client. An OCaml production boundary would
therefore own more wire/protocol conformance or maintain a foreign/service boundary. This is an
assurance cost, not merely an ecosystem inconvenience
([Pump public docs](https://github.com/pump-fun/pump-public-docs),
[Meteora DLMM docs](https://github.com/MeteoraAg/docs/tree/main/developer-guides/dlmm)).

**Falsifiers:** reject the claimed OCaml advantage if a time-boxed episode/cursor model cannot
produce small readable counterexamples; if qcheck-stm's concurrency coverage misses the crash and
interleaving bugs planted in the bakeoff; if Crowbar/AFL integration is operationally brittle on
the chosen CI/developer machines; or if protocol/SDK bridging makes independent conformance slower
and less trustworthy than the type-level benefit buys.

### 5.2 C#/.NET

Current primary tooling offers two distinct strengths:

- FsCheck supplies generated properties, shrinking, and integration with .NET test runners. Its
  newer model-based `Machine`/`Operation` interface exists but is explicitly documented as
  experimental
  ([FsCheck repository](https://github.com/fscheck/FsCheck),
  [stateful testing documentation](https://fscheck.github.io/FsCheck/StatefulTestingNew.html)).
- Microsoft Coyote controls supported task/actor nondeterminism, explores alternative schedules,
  and emits reproducible traces. It rewrites assemblies and supports a declared subset of .NET
  concurrency APIs; unsupported external concurrent APIs need mocking/rewrite or sacrifice trace
  reproduction
  ([Coyote documentation](https://microsoft.github.io/coyote/get-started/using-coyote/),
  [supported approach](https://microsoft.github.io/coyote/overview/how/)).

**Likely advantage:** Coyote is unusually well matched to cursor/checkpoint, reservation, signer,
and retry protocols if implementation concurrency stays inside supported task/actor surfaces.
.NET also makes isolated services, durable workers, test hosts, and diagnostics straightforward.

**Likely cost:** FsCheck's most fluent surface is F#-shaped even though it tests .NET programs, and
the current state-machine API is experimental. Pump/Meteora do not currently designate C# as an
official SDK path, so byte-level or service-boundary conformance remains ours. Coyote's controlled
scheduler is powerful only for nondeterminism it can intercept.

**Falsifiers:** reject the claimed C# advantage if production dependencies force pervasive Coyote
mocks or `--no-repro`; if planted concurrency faults outside the rewritten Task/lock surface escape;
if C#-authored FsCheck generators and shrinkers become test code more complex than the model; or if
SDK boundary/serialization duplication dominates delivery and review.

### 5.3 Rust

Rust currently has the broadest relevant testing and protocol-adjacent tool surface:

- Proptest supplies shrinking property tests and current state-machine testing support
  ([API](https://docs.rs/proptest/latest/proptest/),
  [state-machine guide](https://proptest-rs.github.io/proptest/proptest/state-machine.html)).
- The Rust Fuzz Book documents `cargo-fuzz`/libFuzzer and `afl.rs`
  ([Rust Fuzz Book](https://rust-fuzz.github.io/book/)).
- Loom permutes modeled concurrent executions under a C11-style memory model, but its own
  documentation names unsupported behaviors and both false-alarm and incompleteness risks
  ([Loom repository](https://github.com/tokio-rs/loom)).
- Kani is a bit-precise Rust model checker for proof harnesses, panics, overflow, custom assertions,
  and supported unsafe-code checks. Its documentation says concurrency is not supported, and its
  function-contract interface remains unstable
  ([Kani guide](https://model-checking.github.io/kani/),
  [contracts status](https://model-checking.github.io/kani/crates/doc/kani/contracts/index.html)).

Pump currently publishes a Rust client alongside its TypeScript SDK, and Meteora publishes Rust
integration as well as its TypeScript SDK. That makes Rust the least indirect candidate for exact
wire/account work, although official SDK output is still a comparator rather than truth.

**Likely advantage:** one language can plausibly cover exact bytes, checked integer arithmetic,
parsers, protocol clients, fuzzing, pure models, and later isolated authority with strong memory
safety. Proptest, cargo-fuzz, Loom, and bounded Kani harnesses cover complementary failure classes.

**Likely cost:** async applications can become harder to simulate if runtime primitives leak into
domain logic. Loom requires modeled synchronization types and does not cover the full memory model;
Kani can exhaust resources or exclude needed library/concurrency features; compile and fuzz cycles
may slow exploration. Rust's type system does not establish semantic correctness or authority
containment by itself.

**Falsifiers:** reject the claimed Rust advantage if the common state-machine fixture becomes
runtime-coupled and cannot shrink cleanly; if official SDK versions or Solana crates force broad
unsafe/unreviewable dependency surfaces; if Loom cannot model the actual concurrency boundary;
if Kani harnesses time out or require assumptions that erase the dangerous cases; or if compile,
instrumentation, and iteration latency materially impair the cockpit's exploratory development.

### 5.4 Language decision bakeoff

Do not build three applications. Give each serious candidate the same small evaluation packet:

1. pure episode/inventory transition model with generated traces;
2. observation/cursor crash model with one durable adapter fake;
3. one hostile Pump/Solana byte decoder boundary;
4. one official-SDK differential quote or instruction fixture across a pinned protocol version;
5. one planted concurrency bug and one planted arithmetic/identity bug;
6. seed capture, shrinking, CI execution, debugger/replay, and corpus promotion.

Score evidence, not taste:

- smallest comprehensible counterexample found;
- planted faults recovered and false positives understood;
- model/production-code sharing without coupling the model to effects;
- wall time and flake rate locally and in CI;
- protocol/SDK conformance burden;
- ability to enforce an effect-free read-only build;
- ease of reviewing integer and identity semantics;
- dependency/unsafe/FFI surface;
- time to diagnose a deliberate crash-recovery failure;
- maintenance cost when the sample schema and SDK version change.

One candidate may win the observational core and another a later isolated signer, but every
language boundary adds serialization, deployment, differential-testing, and operational failure
cost. Split only for an assurance boundary that survives this accounting.

## 6. Differential and conformance testing

### 6.1 Oracle hierarchy

Use an explicit hierarchy rather than “two libraries agree”:

1. finalized chain bytes, account state, wallet deltas, and program effects for what actually
   landed;
2. official IDLs, program documentation, and pinned official SDK behavior;
3. independently implemented exact arithmetic/decoding;
4. multiple RPC/provider observations at named slots/commitments;
5. historical `joshibot` decoders and fixtures;
6. UI values and third-party enriched APIs.

Each layer has limits. Finalized chain state does not reveal an expired or never-landed submission.
An IDL may lag a deployed program. An official SDK may have a bug or silently upgrade. Provider
agreement can reproduce the same upstream indexer error. `joshibot` is compost, never an oracle.

Solana's official RPC documents `simulateTransaction` as returning error, logs, units, optional
accounts, and other simulated results, while `getTransaction` returns a confirmed transaction or
`null` at the requested commitment. These are different instruments and must remain separate
([simulateTransaction](https://solana.com/docs/rpc/http/simulatetransaction),
[getTransaction](https://solana.com/docs/rpc/http/gettransaction)).

### 6.2 Protocol conformance suites

For each supported Pump, PumpSwap, SPL Token/Token-2022, Solana message, and eventual Meteora DLMM
version, retain:

- exact IDL/schema and SDK package digest;
- real finalized account and transaction fixtures with slot and commitment;
- instruction discriminator, ordered accounts, signer/writable flags, data bytes, address lookup
  resolution, logs, pre/post balances, fees, and inner instructions;
- decoded semantic record and explicit unknown fields;
- boundary cases generated around every integer/rounding threshold.

Tests should compare:

- our decode with the pinned official decoder;
- our quote/arithmetic with the pinned official SDK on identical account snapshots;
- unsigned instruction semantics and account privileges, not merely JSON shape;
- predicted postconditions with simulation results at a named context slot;
- later, simulated postconditions with finalized wallet/account deltas from the exact signed bytes.

The current Pump docs publish IDLs plus TypeScript and Rust SDK routes
([official repository](https://github.com/pump-fun/pump-public-docs)); Meteora publishes program,
TypeScript, and Rust-integration references
([DLMM reference](https://github.com/MeteoraAg/docs/blob/main/developer-guides/dlmm/typescript-sdk/reference.mdx)).
Pin these as versioned comparators. An upgrade opens a conformance diff; it never rolls straight
into an authority path.

### 6.3 Metamorphic relations

When no independent oracle exists, test relations that must survive transformation:

- encode–decode–encode preserves canonical semantic bytes where the format is canonical;
- changing receive time cannot change source identity;
- duplicating delivery changes observation attempts but not economic effects;
- reordering independent events preserves the same consolidated ledger while changing arrival
  provenance;
- splitting one acquisition into exact sub-lots preserves total quantity and basis;
- book transfer followed by inverse transfer preserves consolidated PnL;
- increasing a trade size cannot decrease its required input under one fixed state and fee config;
- tightening `minOut`/`maxIn` cannot make the plan less restrictive;
- adding an unknown writable account or instruction can only preserve refusal, never authorize;
- replay at a later cutoff may add known evidence but cannot alter what was witnessed earlier.

Metamorphic properties must state their domain. AMM monotonicity across a fee-tier boundary, state
change, route change, or integer dust floor may require a different relation.

## 7. Hostile-byte fuzzing

Fuzz every untrusted boundary before fuzzing business stories:

- Solana legacy/versioned messages, compact lengths, signatures, address lookup tables, account
  keys, instruction discriminators, log/event payloads, and token balance records;
- Pump/PumpSwap/Meteora account bytes and evolving IDL variants;
- RPC JSON, WebSocket notifications, truncation, duplicate keys, extreme numbers, invalid UTF-8
  where applicable, deep nesting, and oversized arrays;
- Pump/social HTML or JSON, image/media metadata, usernames, URLs, Unicode confusables, and mutable
  metadata;
- database/event envelopes, schema version tags, compressed blobs, and corrupted checkpoints;
- later, unsigned and signed transaction bytes presented to the guard.

Properties are stronger than “does not crash”:

- no panic, undefined behavior, unbounded allocation, recursion explosion, path traversal, or
  secret-bearing diagnostic;
- parse failure is explicit and retains the original evidence safely;
- unknown enum, version, program, account, or privilege cannot map to a known authorized effect;
- decode followed by render/log cannot inject active markup or terminal/control behavior;
- resource budgets are enforced before allocation;
- parsers agree with the official decoder on valid corpus inputs;
- every discovered input becomes a minimized, content-addressed regression fixture.

Maintain three corpora: valid production bytes, hand-built adversarial boundaries, and minimized
fuzzer discoveries. Fuzzing only random bytes usually tests the first parser branch forever; seed
with real structured messages and dictionaries derived from pinned IDLs. Run fast bounded fuzz
smoke tests on changes, longer coverage-guided campaigns nightly, and corpus minimization/replay
before releases.

If Rust is chosen, `cargo-fuzz` is the default first spike, not a promise that libFuzzer is the only
backend. If OCaml is chosen, validate Crowbar/AFL on the actual toolchain. For C#, choose a current
.NET-compatible coverage-guided fuzzer only after a maintained-tool spike; FsCheck generation and
Coyote schedule search do not substitute for hostile raw-byte coverage.

## 8. Replay and golden fixtures

Golden tests are valuable where exact history matters, dangerous where developers approve opaque
snapshot churn. Every fixture needs a purpose, provenance, schema/protocol version, and named
assertions.

### 8.1 Required fixture families

- two distinct fills with exactly equal values;
- duplicate delivery of the same source event;
- same source identity with conflicting bytes;
- out-of-order arrival, delayed backfill, commitment upgrade, and fork/reorg correction;
- source gap followed by recovery;
- crash before/after evidence write, cursor write, projection output, and checkpoint;
- partial wallet history, internal transfer, airdrop, fee, rent/account close, and unknown delta;
- full exit, watching flat, re-entry, partial realization, runner attribution, and book transfer;
- mutable creator/community metadata and later identity correction;
- stale, missing, conflicting, and size-dependent quotes;
- unknown program/account in an otherwise plausible transaction;
- later, signed submission acknowledged late after apparent expiry.

### 8.2 Three golden products

1. **Wire golden:** exact bytes and decode; changes require protocol/version evidence.
2. **Semantic golden:** canonical projection and accounting digest; changes require a reviewed
   semantic diff and migration story.
3. **Witnessed UI golden:** structured scene manifest plus a small number of rendered screenshots;
   changes require a user-visible reason, but pixel equality is not the semantic oracle.

The suite must reproduce an individual failure from its seed/trace without rerunning the whole
fuzzer. A minimized property or model-checking counterexample should be promoted into the most
appropriate golden family. Never bulk-update all snapshots after an unexplained diff.

## 9. Chaos and crash testing

### 9.1 Storage and projection failpoints

Inject process death at every durable boundary and every `fsync`/commit acknowledgement. Also
inject disk-full, permission failure, partial/truncated spool record, corrupt checksum, stale lock,
read-only filesystem, backup failure, and restore to a new machine.

Required outcomes:

- committed evidence is not lost;
- uncommitted work is safely repeated;
- cursor/checkpoint never jumps ahead;
- duplicate replay is economically idempotent;
- raw corruption is quarantined and visible rather than skipped;
- old projections remain queryable while a new projection rebuilds;
- restore reproduces the recorded semantic digest and coverage gaps;
- replay runs with all external effect sinks structurally disabled.

### 9.2 Source and clock chaos

Inject disconnects, half-open streams, reordered notifications, rate limits, pagination loops,
provider disagreement, stale slots, commitment regression, local wall-clock jump, DST change,
large receive delay, and a source returning success with an incomplete page.

Do not assert a false universal time order. Source time can be absent or skewed; receive time can
precede another provider's report of an earlier chain event. The invariants are preservation of
each clock and honest partial ordering, not wall-clock tidiness.

### 9.3 Authority chaos, later

Inject guard crash, signer crash, submitter crash, response loss, duplicate operator gesture,
capability expiry mid-flight, blockhash expiry, state movement after simulation, provider saying
`null` while another sees a transaction, landed revert, and late finalization. Kill the system
between signing and recording, and between landing and reconciliation.

The expected recovery is driven by the durable attempt model. “Try again” is never the default
recovery for an unknown signed/submitted state.

## 10. Schema and migration testing

Evidence and interpretation evolve at different rates. Test them differently.

### 10.1 Evidence-envelope compatibility

- every released reader parses all retained historical envelope versions or invokes an explicit,
  tested adapter;
- unknown fields survive round trip where the format promises preservation;
- unknown versions fail visibly, never as an empty successful observation;
- migrations do not rewrite content hashes or observation identity;
- retention/erasure creates explicit policy events and cannot leave live derived copies behind.

### 10.2 Projection migration

For every projection version:

- replay the fixed corpus from raw evidence into old and new versions;
- produce a field-level and aggregate semantic diff;
- declare intended differences and bound unintended ones;
- test fresh build, in-place operational upgrade where supported, rollback/read coexistence, crash
  mid-migration, and restart;
- test idempotence by running the migration/rebuild twice;
- retain the exact code/config/input manifest used for historical research outputs.

Database migration success is not semantic migration success. Row counts can agree while episode
boundaries, cutoff visibility, lot basis, or duplicate identity change.

### 10.3 Research reproducibility

A released study records evidence snapshot/coverage, projection version, query/code digest, model
and prompt version, seed, environment, and output hash. A later decoder correction should produce
a named reanalysis, not silently alter the prior artifact. Reproduction tests should use small
committed fixtures plus periodic full-corpus rebuilds; CI need not carry private or enormous raw
data.

## 11. Numerical invariants

### 11.1 Representation rules

- lamports and token base units are bounded integers with checked arithmetic;
- asset identity includes mint/program/decimals context; equal numbers across assets never add;
- ledger, fee, slippage, `minOut`/`maxIn`, bin, and lot arithmetic do not use binary floating point;
- rational or arbitrary-precision decimal values may describe ratios, but every executable amount
  ends in the protocol's exact integer rounding rule;
- USD and chart values are annotations, never conservation units;
- overflow, underflow, divide-by-zero, invalid decimals, and unreachable rounding are explicit
  errors, not saturation unless the protocol itself specifies saturation.

### 11.2 Financial properties

- asset conservation holds across reconciled pre/post balances, with fees, rent, account creation/
  closure, wraps, transfers, and external boundary flows explicit;
- lot remaining quantities never go below zero and sum to the consolidated balance after named
  unresolved residuals;
- realized proceeds plus executable remainder do not change when quantity is merely reclassified;
- partial exit allocations sum exactly to the fill quantity;
- a runner retains live basis/value; it is never initialized at zero because prior proceeds
  recovered capital;
- episode aggregation equals the sum of its inventory epochs under the declared attribution rule;
- portfolio aggregation equals wallets plus custody/LP positions minus explicitly identified
  internal transfers, not the sum of UI PnL headlines;
- LP add/remove/reweight plans conserve each asset under exact fees and rounding; recentering with a
  swap is a distinct asset conversion;
- quote outputs and limits match pinned official SDK arithmetic on the supported state domain.

Test numeric boundaries at `0`, `1`, max values, decimal transitions, fee-tier boundaries, dust,
one-unit rounding changes, empty/full reserves, DLMM bin edges, token-2022 transfer-fee behavior,
and values just inside/outside every policy ceiling. Random generation should be biased toward
boundaries rather than uniform across huge integer spaces.

## 12. Where formal methods buy something

Formal work begins with a question that testing cannot answer confidently, not with a preferred
tool.

### 12.1 TLA+, PlusCal, or Quint for concurrent protocols

The strongest early candidates are:

- atomic evidence/cursor/projection checkpointing through crash and restart;
- durable reservation, unique signing, identical-byte retry, expiry, and late reconciliation;
- aggregate authority monotonicity across concurrent arms;
- possibly a multi-step LP transformation protocol once actual authority is designed.

TLA+ with TLC is mature for transition systems and temporal properties; PlusCal is useful when the
team reasons more clearly from an imperative algorithm that is translated to TLA+
([official TLA+ tools](https://lamport.org/tla/tools.html)). Quint offers an executable state-
machine language, randomized simulation/tests, and verification through Apalache or TLC with
counterexample traces
([Quint overview](https://quint.sh/docs/what-does-quint-do),
[CLI documentation](https://quint.sh/docs/quint)).

Choose one notation after a spike. Do not maintain equivalent TLA+ and Quint specs for prestige.
The acceptance test for either is:

1. it finds a planted protocol defect;
2. its counterexample converts into an executable state-machine regression trace;
3. every abstraction/assumption and bound is reviewed;
4. implementation events map mechanically or by a small checked adapter to model actions;
5. the spec remains small enough to review when the protocol changes.

Model checking a state machine does not prove the production storage adapter, scheduler, signer,
or chain implements it. That refinement gap is covered by trace conformance, failpoints, and
reconciliation.

### 12.2 Kani or Dafny for stable pure kernels

If Rust is selected, Kani may be useful for bounded, bit-precise checks of parser/guard arithmetic,
integer fee/limit functions, lot allocation, and small capability predicates. It should not be
selected for the concurrent attempt protocol because current Kani documentation says concurrency
is unsupported; unstable function contracts must not become a hidden platform dependency.

Dafny is useful when a stable sequential algorithm needs functional correctness over unbounded
mathematical structures: for example, a carefully scoped lot allocator or conservation-preserving
LP transformation. Current Dafny documentation describes built-in pre/postconditions, frames,
termination, and compilation to .NET via C#, Java, JavaScript, Go, and C++—not direct verification
of arbitrary OCaml, C#, or Rust implementations
([Dafny reference](https://dafny.org/dafny/DafnyRef/DafnyRef)). If the production algorithm is
rewritten from Dafny or placed behind an FFI, the translation/refinement boundary remains part of
the assurance case. For ordinary small integer functions, executable properties plus differential
tests will usually be cheaper and more directly connected to production.

### 12.3 Lean only for enduring mathematics

Lean is an interactive theorem prover and programming language with a small proof-checking kernel
([official documentation](https://lean-lang.org/lean4/doc)). It earns a place only if Joshi develops
an enduring mathematical result whose proof is genuinely hard to obtain or maintain with a smaller
tool—for example, a reusable theorem about a nontrivial LP transformation or policy composition.

Do not use Lean to encode CRUD state transitions, the current episode vocabulary, or routine
conservation arithmetic merely because Ember knows formal methods. A beautiful Lean theorem about
an informal extraction from production code can increase confidence less than one ugly crash test.

### 12.4 Formal-artifact maintenance gate

Each formal artifact must state:

- exact theorem/invariants and excluded behavior;
- environmental and fairness assumptions;
- finite bounds/unwind limits and why they are adequate;
- correspondence to production types, events, and versions;
- counterexample-to-regression path;
- tool version and reproducible invocation;
- an owner and deletion/revision criterion.

Retire or rewrite an artifact when the mapping to production becomes aspirational. A stale proof is
worse than no proof because it advertises assurance while covering an extinct system.

## 13. What not to prove

Do not spend formal or testing budget trying to establish:

- that Ember's intuition, a crackle taxonomy, social-transition ontology, or chart-shape vocabulary
  is complete or correct;
- that a strategy is profitable from software invariants;
- that the market or community is stationary;
- that a provider/API reports the whole truth when completeness is unobservable;
- that a current SDK, IDL, UI, or deployed program will never change;
- that simulation success implies landing, fill, finality, or economic outcome;
- that a viewport event proves attention or an interview recovers original intent;
- that a transaction is safe because its top-level program is allowlisted while inner effects,
  account privileges, address tables, and token programs are unmodeled;
- that cryptographic primitives, Solana consensus, or external wallets are correct in full;
- that “memory safe” means authority safe, numerically correct, or semantically honest;
- exhaustive safety for unlimited capital or unbounded autonomy;
- pixel-perfect UI rendering beyond a few witnessed-replay checks.

The right response to an environmental uncertainty is a coverage record, bound, refusal, detector,
or operational contingency—not a theorem with the uncertainty hidden in an axiom.

## 14. Staged verification budget

The budget scales with authority and consequence, not code size. These are initial ceilings and
cadences to validate during the engineering spike, not permanent CI dogma.

### 14.1 Read-only R1–R3

**Engineering allocation:** approximately one quarter of slice engineering time goes to fixtures,
models, failpoints, and replayability. This is product work: the evidence instrument is the product.

**Every change, target under 8 minutes on a clean CI worker:**

- unit/type/schema checks;
- deterministic example and property suite with saved seeds;
- episode and cursor model traces at bounded depth;
- fixed adversarial replay corpus;
- migration compatibility for touched schemas;
- effect-ceiling scan/test proving the build has no signing/broadcast surface.

**Nightly, target 1–2 worker-hours, parallelizable:**

- deeper property/state-machine generation;
- hostile input fuzzing and corpus replay;
- crash matrix over durable boundaries;
- two-build deterministic replay digest;
- backup/restore drill on a representative store;
- provider/source conformance samples with gaps recorded.

**Release/slice gate:** full fixed-corpus replay, fresh-store rebuild, prior-version migration and
rollback/read coexistence, deliberate kill/restart, and human inspection of semantic diffs. No
release with an unexplained evidence, accounting, or cutoff diff.

### 14.2 Shadow R4

**Engineering allocation:** roughly one third of work that introduces quote/counterfactual logic
goes to exact-state fixtures, independent arithmetic, latency modeling, and apparatus calibration.

**Add to every change, target under 12 minutes:** official-SDK differential fixtures, numeric
boundary properties, cutoff leakage checks, quote-age/state binding, and deterministic shadow-path
replay. Shadow outputs must be type- and UI-distinct from fills.

**Nightly, target 2–4 worker-hours:** structured byte fuzzing, captured-account quote sweeps,
provider divergence, latency/adverse-fill perturbations, and route disappearance. Compare apparatus
error with the smallest economic hurdle under study.

**Promotion gate:** on a sealed corpus, every proposal recomputes or is explicitly unquotable; no
mark substitutes for a quote; p95 replay/quote uncertainty clears the slice's declared resolution
gate; and a protocol/SDK upgrade diff has independent review.

### 14.3 Eventual live authority R5–R8

This stage requires a separate authorization and budget decision. Verification is not a final QA
phase. Expect at least two-fifths of engineering effort on the authority slice to go to independent
guarding, attempt journaling, adversarial simulation, reconciliation, and drills.

**Every authority change, target under 15 minutes for the blocking tier:** all earlier suites plus
plan-to-byte conformance, hostile-byte guard tests, capability/reservation state-machine traces,
exact retry identity, numeric limits, and isolation checks. Signing code requires review by someone
other than the author of the planner/builder change.

**Nightly/release campaign, several parallel worker-hours:** controlled schedule exploration
(Coyote, Loom, or equivalent where it actually covers the runtime), protocol model checking,
long-running fuzz corpora, every-boundary process kill, stale-state and late-landing chaos, and
finalized-chain reconciliation on non-authoritative fixtures.

**Before R7:** red-team a dedicated empty/tiny wallet; demonstrate kill, expiry, duplicate gesture,
lost response, late landing, and full restore; verify independent limits from raw bytes and
accounts; rotate/revoke the capability; and produce one complete assurance case with residual risks.

**During R7/R8:** each attempt is a canary with manual observability. Any unexplained wallet delta,
duplicate economic effect, mutated retry, stale-state action, reconciliation gap, or failed limit
stops the authority lane. Profitable PnL never waives a safety failure.

### 14.4 Suite health budget

Reserve recurring time to delete redundant tests, repair generators, minimize corpora, and measure
mutation/known-effect sensitivity. A suite that only grows becomes slow, ignored, and theatrically
green. Track:

- flake rate (target zero in deterministic tiers);
- seeds/traces reproducible after failure;
- generator state/branch coverage rather than only source lines;
- planted mutations caught by each assurance layer;
- median counterexample size and diagnosis time;
- replay corpus age and protocol/schema coverage;
- proof/model assumptions that changed;
- CI wall time and false-alarm burden.

## 15. Commissioning sequence

1. Freeze the core invariant catalogue and effect ceilings for the first read-only slice.
2. Build the deterministic laboratory contract and one synthetic crash/replay trace.
3. Run the OCaml/C#/Rust bakeoff on the common episode/cursor/decoder packet; select based on
   counterexamples and boundary cost.
4. Establish wire, semantic, and witnessed golden families.
5. Add property/state-machine suites and durable failpoints before live collectors accumulate
   irreplaceable evidence.
6. Commission schema migration and restore tests before the second schema version exists.
7. At R4, add official-SDK differential quotes and apparatus-error calibration.
8. Only after a separate R5 decision, model the attempt protocol in Quint/TLA+ or the selected
   controlled-concurrency tool, and connect counterexamples to executable traces.
9. Add Kani/Dafny/Lean only for a named stable kernel whose assurance gap survived the simpler
   layers.

The desired culture is empirical formalism: state the property exactly, attack it with the
cheapest tool that can find a counterexample, preserve the failure, and increase rigor only where
authority or state-space structure demands it. That is substantially more serious than either
“tests are enough” or “we should verify the bot.”
