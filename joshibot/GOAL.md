# GOAL — build out the joshibot research program

Standing goal set 2026-08-13. Spine: `PROGRAM.md` (what the evidence establishes) and
`SWARM.md` (how to build it without the fleet building a mirror).

## Current thrust

**Phase 0 is DONE — all 8 interfaces exist as types that build.** Tracks B, C and E are now
unblocked and swarmable, because a lane can be handed real signatures instead of prose.

## Next 3 moves

1. Mint-indexed panel collection, hard-capped at 100k credits (1% of plan). Every signal lane
   converged on this as the single unblocker; the existing store is a 2-address watchlist.
2. Phase 2 replay harness: deterministic tape replay with exact AMM fills through the Lean
   kernel, so a strategy is evaluated against the artifact the theorems are about.
3. Phase 2 search: MAP-Elites over DSL terms with OPE on propensity-logged trades, purged
   walk-forward, and trials accounting taken from the grammar cardinality rather than guessed.

## Done log

- 2026-08-13 — Track A landed (`e509cc3`): fabricated cost basis killed at all four sites (engine
  auto-protect, `policies.from_quote`, dashboard client-side, `overview.tsx`); executor made safe to
  retry (local signature before execute, `isBlockhashValid` as proof-of-death, `unresolved` terminal
  state); 32-address simulation ceiling chunked; blanket 1500bps replaced by reason-conditional
  computed `minOut`; config lost-update race closed; `--status` made incapable of executing.
  416 pytest + 5 dashboard tests, ruff/tsc/eslint clean. Every lane falsified its own tests.
- 2026-08-13 — sentinel restarted onto the hardened code (pid 15101, live, zero tracebacks). First
  time the running process has carried a real cost basis.
- 2026-08-13 — Phase 0 tape contract (`3f0c1b1`): interfaces #1/#7/#8 in `shitcoims_tape/`.
  Raw amounts as strings on the wire (f64 cliff), two clocks never conflated, censoring
  recorded explicitly with informative closes flagged, reserves recorded not prices.
  18 tests, all falsified by four probes.
- 2026-08-13 — Phase 0 Lean kernel: interfaces #2–#6 in `kernel/Joshi/`. Fills (payout bounded
  by reserve, monotone in size), Basis (quote-derived basis is unconstructible; no-basis can
  never fire a stop), History (no-lookahead as a theorem over all strategies), Dsl (trial count
  N computable from the grammar: 110,880 predicates at 8 features/depth 1), Envelope (exposure
  bounded over EVERY action sequence, i.e. every learner). Zero sorries; axiom audit shows only
  propext/Quot.sound/Classical.choice. Lean core only, no mathlib — builds in ~2s.
- 2026-08-13 — merge gate: `scripts/check.sh` (ruff, mypy, pytest, dashboard tsc/eslint/render,
  lake build, no-sorry, axiom audit). mypy introduced with a GATED set — executor, transaction,
  domain, tape must stay clean; 65 findings elsewhere are tracked debt surfaced by `--full`.
  Two real narrowing holes closed in the money path while gating (executor reconciliation,
  domain no-quote guard); both now fail closed instead of relying on a reader's inference.
- 2026-08-13 — stale-doc sweep: README no longer claims full-balance-only exits and now states
  the cost-basis contract (never inferred from a quote; unknown basis ⇒ rug-only); Scout's
  "cannot sell" corrected to "cannot sell directly" (it can write a rule that causes a later
  sale); `lots.py` grace comment no longer describes the deleted fabrication. `policy_to_mapping`
  float exception documented with the condition under which it must be split.
- 2026-08-13 — Track C: the kernel is now load-bearing, not a parallel document. `@[export]`
  C ABI (`joshi_sell_out`, `joshi_accepts`) with a proof that narrowing back to UInt64 is
  lossless — `sellOut_le_reserve` is what licenses the signature. Shipped as `joshi-oracle`
  (macOS dylib linking dropped the objects; the executable is lake-supported and robust).
  `shitcoims_kernel/` is the Python binding: an authoritative subprocess oracle plus a fast
  path for replay, held to exact agreement by 15 parity tests over adversarial sizes and 600
  random pools. Falsified with two transcription bugs (dropped denominator term; round vs
  floor — the latter only diverges at scale, which is the class that silently corrupts a
  backtest). Parity tests skipping is now itself a gate failure.
- 2026-08-13 — Track E spike #3 (callout→flow): **UNRESOLVABLE-AT-THIS-N**, not null — the
  exogenous outcome was never observed (0 of 61 called-out mints touched by the exogenous
  wallet). The finding that matters is the TRAP: including our own sentinel wallet yields
  p=0.00498 and 6/6 surviving FDR, from a closed loop plus a mechanically-floored p
  (n_placebo_arrivals=0 across 32,400 windows). Structural-zero guard added and pinned.
  8/8 mutations killed their test. Also: the store's two clocks are INVERTED between kinds
  (`emitted_at` is block time for wallet_transaction, post time is `observed_at` for social).
- 2026-08-13 — Envelope completed: daily-loss breaker with `tripped_breaker_is_absorbing` —
  once the budget is blown, `run` is the IDENTITY on desk state for any learner and any
  sequence length. Structural, not lucky: `apply` never touches the loss field. Zero sorries,
  propext only.
- 2026-08-13 — `resolve_pending_exit` promoted to the executor's public contract; the engine
  no longer reaches through `getattr` into a private name, where a rename would have silently
  degraded to "delete the intent without resolving it" — i.e. drop a confirmed fill from the
  ledger. Still probed (test stubs legitimately omit it), but probing a public name makes a
  rename a visible break.
- 2026-08-13 — Track B landed the tape recorder (`2d93305`, 96 tests, 31/31 mutations caught,
  and it found a clock bug in its own instrument: graduation median 0.5s on the observer clock,
  now 250s against Marino's 264s). It then found three holes in MY contract, now closed:
  social flags are tri-state (`None` = not observed — `False` was a fabricated negative, the
  same disease as a quote-stamped cost basis); `Callout` gained `posted_at` (ingest lag median
  368s / p95 2h, so anchoring on ingest measures a closed window); and `_mint` now DECODES to
  32 bytes instead of matching a character class, which catches ~3 in 4 lowercased addresses.
  Falsification found a gap in my own test — the first probe was a no-op — so the missing
  case (absent post time must not be fabricated) is now pinned too.
- 2026-08-13 — `prints_from_wallet_payload` no longer splits one native SOL delta evenly
  across multiple token legs (a route/arb carries one delta and no way to attribute it, so
  the split invented a per-leg price on every leg). Multi-leg rows are refused, keeping the
  ambiguity visible as a smaller n rather than confident noise. Also made the lowercase-address
  test a deterministic RATE test — a single case flaked on the minority that still decodes to
  32 bytes, which would have hidden the residual risk instead of measuring it.
- 2026-08-13 — Signal #2 (funding-tree entity resolution): **NO-LINKS-AT-THIS-N** on the live
  store (2 wallets wide), reported as the null it is. Its real-data finding is a false positive
  it *refused*: the store's only linkage-shaped relation is fee-payer sponsorship, and one
  sponsor touched both watched wallets — trusting it would have fused OUR OWN SENTINEL with a
  third-party KOL into one entity. A fan-out rule does not catch that (fan-out 2); only the
  typed edge does. 15/15 mutations killed, including one that tunes the generator to flatter
  the resolver. Pair precision 1.000 at every hub threshold — the knobs buy recall, never
  errors. Contract updated in response: `Trade` now carries `signers` (custody evidence) and
  `fee_payer` (explicitly NOT custody), which was its #1 next experiment.
- 2026-08-13 — Recorder now extracts custody: `signers` (the account keys that actually signed
  — requires the private key, so the strongest linkage) and `fee_payer`, kept in separate
  fields on every recorded trade. Malformed input yields EMPTY custody, never a guess, since a
  wrong signer set would be treated as strong evidence. Falsified both directions (all-keys-are
  -signers; guessing from the fee payer). This closes signal #2's #1 next experiment and
  unlocks its held-out custody precision check.
- 2026-08-13 — Signal #1 (SVN co-trading): **UNRESOLVABLE-AT-THIS-N** on the signal (2-wallet
  store, 5.15h overlap, 0 performable tests) but the INSTRUMENT result is a real measurement:
  with zero planted coordination, heavy-tailed + active wallets give Bonferroni FWER **0.600**
  and ~99 BH clusters **from nothing** in 30/30 worlds — all deleted by the degree-preserving
  null. Popularity baseline out-ranks the SVN (AUPRC 0.979 vs 0.961); the SVN's contribution is
  the threshold, not the ordering. 16/16 mutations killed. Promoted two rules to PROGRAM.md §3
  (both-controls-always; two-nulls-at-matched-density), the first now independently discovered
  by two lanes.
- 2026-08-13 — **First real-data validation of the recorder**, and it found a permanent blind
  spot: pool facts came only from a witnessed `CreatePoolEvent`, so a recorder started today
  records NOTHING for any already-migrated token, forever. Replaying 29 real transactions
  produced 0 events (27 decoded AMM trades, all dropped as unattributed). Fixed by resolving
  (base, quote) from the transaction's own token balances — no extra RPC — and the same sample
  now yields 54 events. Fails closed on anything ambiguous; a witnessed creation still wins.
  Falsification caught a second gap: nothing had pinned that precedence, so a pool-shaped
  transaction could silently re-point an existing pool at a different mint.
- 2026-08-13 — Phase 2 replay engine (`shitcoims_replay/`): deterministic tape replay where
  fills are COMPUTED through the Lean-checked kernel rather than modelled, and a policy is
  handed a causally-restricted `Snapshot` (the Python analogue of Lean's `View t`) instead of
  the tape, so lookahead is structurally impossible. Slots are sorted, not trusted — a recorder
  paging history backwards would otherwise run the market in reverse. Realised-only ledger, no
  mark-to-market. 13 tests; falsification found two weak ones: `PoolState.slot` was stamped
  from the loop variable (agreeing with the current slot by construction, witnessing nothing)
  and the round-trip test had too much margin to catch a rounding-direction flip.
- 2026-08-13 — Purged/embargoed/entity-grouped walk-forward (`shitcoims_replay/split.py`).
  Three defences because each catches a different leak: temporal (insufficient alone), purge
  (a label window reaching into test has already seen it — survives a naive temporal split),
  and entity grouping (one actor straddling the boundary). Every removal is COUNTED, because a
  purge that removes nothing is indistinguishable from one never needed — the published defect
  was a purge parameter that was a literal no-op. Plus `assert_no_leakage`, an independent
  re-check of produced indices. 11 tests, 5/5 mutations killed.
- 2026-08-13 — Trials accounting (`shitcoims_replay/trials.py`) with N taken from the Lean
  grammar rather than guessed: the oracle now answers `predcount`, so a DSL search reports a
  COUNTED trial count. Deflated Sharpe implemented with the cross-trial variance term intact
  — the term both audited reference implementations dropped — and `trial_sharpe_sd` is
  MANDATORY, which is how it stops getting lost. 10 tests, 4 mutations (dropped variance term,
  the invented `sr/ln(trials)`, ignored non-normality, a guessed N) all killed. Falsification
  also caught one of my own tests turning a real failure into a skip via `except Exception`.
- 2026-08-13 — Panel collection (interim, 33.3k/100k credits): stratum B complete — 250 mints,
  221,184 trades, 443,039 tape events, 0 malformed, 0 duplicate ids, 0 displaced. **Signal #1
  is FEASIBLE**: 2,230 wallets at an activity floor of 5 against a Bonferroni cap of 3,880; at
  floor 2 it is infeasible by three orders of magnitude, exactly as PROGRAM.md §4.1 predicted.
  Two real recorder defects found against live chain and fixed: (1) pump.fun spells native SOL
  as the ALL-ZERO pubkey on the bonding curve, so the recorder dropped *every* curve trade
  (735 → 1,123 on the same 5 mints, verified against a checked-in mainnet fixture reconciling
  to 0.13%); (2) `HeliusHistorySource` never paged and paid for failed transactions — filtering
  to succeeded is ~2.5× more usable data per credit. Plus a latent bug caught in review:
  terminal watch closes weren't keyed by mint, so a neighbour's graduation inside a bundled
  transaction could swallow an `OBSERVER_LOST` record and bias the censoring rate DOWNWARD.
- 2026-08-13 — Off-policy evaluation (`shitcoims_replay/ope.py`): IPS / SNIPS / doubly-robust
  over propensity-logged decisions, so a candidate policy is scored against trades actually
  made — no simulator-fidelity assumption. Effective sample size is reported and gates
  trust: a thousand records with one dominant weight is an estimate from ONE record.
  `require_overlap` refuses a target that acts where the logs have no support, because OPE
  cannot extrapolate and silently trying is how it lies. 10 tests, 4/4 mutations killed — and
  the tests caught a real bug in my own DR formula (the direct term must be the target-weighted
  expectation over ALL actions, not the model's value for the logged one).
