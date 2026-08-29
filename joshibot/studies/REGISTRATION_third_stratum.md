# REGISTRATION: the third stratum — membership, birth share, and what it does to B1

2026-08-29, registered BEFORE any third-stratum estimand was computed. Instrument will be
`studies/third_stratum.py`; caches to `studies/data/third_stratum/`. Data: BigQuery
`bigquery-public-data.crypto_solana_mainnet_us.Transactions` (`log_messages` +
`block_timestamp` + `err` only; dry-run cost gate FIRST, project `manifest-quasar-414607`,
authorized to $20, refusal threshold $10 without explicit escalation), the existing corpus
distillates (`studies/data/operator_crime/` 2026-08-05..14 and
`studies/data/operator_crime_fresh/` 2026-08-26..28, including
`operator_crime_fresh/combined/panel.parquet`, the exact table B1's `screen_seeded.json`
was computed from — reproduced byte-for-byte on its counts before this registration:
n=91,505 / admitted 7,784 / rip 0 bad / collapse 2 bad), `state/boards/*.jsonl`
(2026-08-14..23), and `state/dregg_screen/firehose/new_token/` retained frames.

## Author-knowledge disclosure (already seen; cannot count as findings)

- MAYHEM_MODE.md §5: a non-mayhem cohort born at exactly (vTok 1.073e15, vSol 4.292 SOL),
  k = 4.605e24 constant along its path, supply exactly 1e15, `is_mayhem_mode = 0`,
  first appearing ~June 2026, ~2.7% of board rows (board rows skew visible).
- `state/boards/boards-20260823.jsonl` untouched-seed census (computed while scoping this
  registration): among rows with `virtual_token_reserves` exactly 1.073e15, vSol clusters
  at 30,000,000,000 (14,398 rows) and **4,292,000,000** (469 rows), each with a small
  dust-bumped tail — so the candidate constant is exact, and the predicate below is an
  equality, not a band.
- The pinned `CreateEvent` layout (`shitcoims_intelligence/pump_layouts.py`, official IDL
  commit 9c82f61) carries `virtual_sol_reserves`, `is_mayhem_mode`, `quote_mint`, and
  `virtual_quote_reserves`; pump events ride in `log_messages` as `Program data:` lines
  (RESULT_pump_logs_spike.md, verified live 2026-08-15).
- B1's shipping operating point (`screen_seeded.json`): CLEAN admit 8.51%, rip precision
  100% [99.95, 100], collapse precision 99.97% [99.91, 99.99] — computed over the 1e15
  population WITH the third stratum inside it, outcomes priced under k_std.
- RESULT_verdict_survival.md limitation: for third-stratum coins the S3 materiality bar
  (peak >= 100 SOL via k_std) is really a ~14.3 SOL bar (4.292/30 = 0.14307).
- I have NOT computed: any third-stratum birth count, share, outcome rate, or any B1
  recompute variant. The 87 retained WS frames of 08-29 contain zero third-stratum creates
  (measured while scoping; consistent with a small share on a small sample).

## Membership predicate under test (fixed now)

STRATUM3 := the mint's pump `CreateEvent` has `virtual_sol_reserves == 4_292_000_000`
exactly, `is_mayhem_mode == false`, decoded from a `Program data:` log line attributed to
the pump program by the invoke-stack walk (`shitcoims_tape.recorder.attribute_program_data`
— discriminator match alone is spoofable and is NOT attribution), in a successful
transaction (`err IS NULL`), with the decoded `bonding_curve` field equal to the locally
derived PDA `find_program_address(["bonding-curve", mint], pump)` (the vendor-independent
check; MAYHEM_MODE.md documents the vendor `bondingCurveKey` junk mode).
STANDARD := same decode, `virtual_sol_reserves == 30_000_000_000`, not mayhem.
Any OTHER seed value is counted and reported per value, never folded into either stratum.

Failure modes to report, not hide: creates whose event fails the PDA check (spoof/quarantine
count), corpus births with no decoded CreateEvent (coverage), corpus births with >1 decode
(dupes kept as first-by-time, count reported), mayhem-flagged events at nonstandard seeds.

## Registered estimands

T1 IDENTIFICATION. Coverage: fraction of corpus BORN-standard births (birth.parquet,
   minted_raw = 1e15, decimals 6) whose mint has exactly one attributed, PDA-verified
   CreateEvent in the same window. Gate: >= 99.5% per window, else the census is reported
   as a bound, not a share. Concordance: 100% of STRATUM3 events must be non-mayhem (any
   violation is a stop-and-report). Product identification (descriptive, no gate):
   distribution of `quote_mint` / `virtual_quote_reserves` / `token_program` /
   `is_cashback_enabled` on STRATUM3 vs STANDARD events.

T2 SHARE BY DAY. Among corpus-joined 1e15 births: STRATUM3 share per day for 2026-08-05..14
   and 2026-08-26..28, with Wilson 95% CIs. Event-side-only counts (no corpus join;
   labeled as such) for gap days 08-15..25 and 08-29 if the pull covers them within
   budget. Anchor to declare against: the recon's "2.7% of board rows".

T3 THE B1 RECOMPUTE (the shipping claim). On `combined/panel.parquet` filtered to the
   fresh window (the exact B1 population, n = 91,505), the five-gate CLEAN screen
   recomputed THREE ways, each reporting admitted n, admitted_bad, precision and
   Clopper-Pearson 95% CI for BOTH outcomes (is_rip, collapse), plus base rates:
   (a) AS SHIPPED — all coins, k_std outcomes (must reproduce `screen_seeded.json`);
   (b) STANDARD-ONLY — STRATUM3 coins excluded from the population;
   (c) CORRECTED — all coins, with STRATUM3 coins' `peak_mcap_sol`/`final_mcap_sol`
       rescaled by 4.292/30 (their true marked price under their own constant k;
       drawdown and every token-side quantity are scale-invariant and untouched), then
       collapse := peak_mcap_sol >= 100 AND drawdown >= 0.90 and is_rip's mcap conjunct
       re-evaluated on the rescaled peak.
   RESTATEMENT RULE (fixed now): the public claim ("admits >= 99.90% clean at 95% conf")
   survives iff BOTH (b) and (c) keep the collapse-precision CI lower bound >= 99.90%.
   If either fails, the site/cards must be restated and this study says to what.
   Also reported: STRATUM3's own row — its n in the fresh window, its CLEAN-admitted n,
   and its corrected-outcome collapse count (descriptive; a stratum arm is NOT being
   validated here and no stratum-3 precision claim ships from 3 days of exposure).

T4 THE LIVE FIX (ship rule fixed now). The stratum label ships regardless of T2/T3:
   cheap path = vendor-frame seed estimate (vSolInBondingCurve − solAmount within 1e-6
   of 4.292, a vendor float, labeled estimate); hydrated path = authoritative CreateEvent
   decode from the create transaction's own `logMessages` (already fetched — zero new
   spend). Policy, pinned: STRATUM3 launches are OUTSIDE the validated population —
   `in_validated_population = false` with a stated reason — and the B1 precision sentence
   is never quoted on their lines. They keep their feature-fact verdicts (KNOWN_CREW /
   BUNDLED / NOT_CLEAN are birth-slot facts, valid on this stratum) but a launch that
   passes all five gates is emitted UNSCORED(stratum needs its own validation cycle),
   NOT CLEAN — CLEAN is the name of a measured precision claim and this stratum has no
   measured precision. If T3(b)/(c) restore the >= 99.90% bound for the standard-seed
   population, cards may keep quoting it for standard-seed coins only.

## What would falsify the whole framing

- T1 coverage < 95%: the log channel is not the census instrument; stop, report, and
  bound the share from boards instead.
- STRATUM3 events whose reserves disagree with the boards' 4.292e9 constant, or whose
  constant product is NOT preserved in later board snapshots at > 1% median deviation:
  the "constant k_3" model is wrong and T3(c)'s rescaling is invalid — report (b) only.
- A STRATUM3 share so large (> 20% of births) that B1's population was never mostly
  standard: escalate beyond restatement.

## Budget

Dry-run first, always. Planned scan: `log_messages` + `block_timestamp` + `err` over up to
25 day-partitions (2026-08-05..29); prior measurement says ~3.1 + ~2.5 + ~7.8 GB/day ≈
13.4 GB/day ≈ 335 GB ≈ $2.05 at $6.25/TiB — well inside the $20 authorization. If the
dry-run says materially more (> $10), the pull shrinks to the 13 corpus days; if still
> $10, corpus-window-only with `err` dropped and the failed-create caveat stated.

## AMENDMENT 1 (2026-08-29, before any census/share/B1 estimand was computed)

Registered instrument channel and one registered constant are amended, with the evidence
that forced each, gathered during predicate validation (T1 groundwork), disclosed here
before T2/T3 run:

1. **The BigQuery log channel is DEAD, and the pull is replaced by a $0 local channel.**
   `log_messages` in `bigquery-public-data.crypto_solana_mainnet_us.Transactions` is
   `[""]` on every row of every sampled partition (2026-08-05/14/26/29; measured after
   the dry-run gate — total real spend so far ~$0.5 of the $20 authorization, exact
   tally in the RESULT). `scripts/pump_history.py` had already documented this
   ("log_messages is empty on 2026-08-04"); I read it only after registering. The
   replacement, validated before adoption: the third stratum is a QUOTE-MINT (USDC)
   curve, and its create transaction carries USDC token legs — visible in the raw local
   corpus (`state/bulk_pump*/raw` keeps ALL legs of matching txs). New membership
   predicate, corpus-side: the create transaction (the tx whose legs of the born mint
   net exactly +1e15) contains a USDC (`EPjFWdd5Auf...`) leg owned by the coin's
   `curve_owner`. Validation on the 51 board-k-identified candidates born 08-05..14:
   49/51 carry the USDC leg; the 2 that do not were Helius-decoded and their chain
   CreateEvents read STANDARD (vsol = 30e9, quote = native SOL) — board reserve
   snapshots can mislabel, the birth legs did not. Chain CreateEvent spot-checks on
   USDC-legged candidates: 2/2 read `virtual_sol_reserves = 4_292_000_000`,
   `quote_mint = USDC`, `virtual_quote_reserves = 4_292_000_000`, `is_mayhem = false`.
   The event-reserve predicate (T1 as registered) stays the LIVE/hydrated-path
   predicate; the leg predicate is its corpus-side equivalent, and `verify` measures
   their concordance on a sample.

2. **The registered T3(c) rescale factor 4.292/30 was WRONG and is amended.** Ground
   truth: `virtual_quote_reserves = 4_292_000_000` is RAW USDC (6 decimals) = $4,292 —
   pump's USD-denominated clone of the standard curve ($4,292 = 30 SOL x $143.07; the
   initial marked cap is $4,000, not 4.0 SOL). The flag's "~7x mcap overstatement" is
   therefore a CURRENCY MISLABEL, not a scale error: the k_std pseudo-mcap of a
   stratum-3 coin equals its true marked USD mcap divided by 143.07, so in SOL terms
   the overstatement is P_SOL/143.07 (~1.05x at $150, ~1.4x at $200) — bounded, small,
   and price-dependent. T3(c) is amended to rescale stratum-3 `peak/final_mcap_sol` by
   4292 / (30 x P) with P = $150 (the repo's seeded SOL/USD reference,
   `studies/hardcode_audit.py`) and a $200 sensitivity, both reported. The registered
   restatement rule (99.90% lower bound must hold in (b) AND (c)) is unchanged.

3. Author-knowledge update: while validating I saw the per-day counts of the 51
   candidates and the 4/49 wSOL-and-USDC leg mix. I have still computed NO share,
   NO census over either corpus, and NO B1 variant.
