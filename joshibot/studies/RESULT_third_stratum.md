# RESULT: the third stratum — a USDC-quoted curve, small, live-detectable, and B1 survives it

2026-08-29. Registered: `studies/REGISTRATION_third_stratum.md` (+ Amendment 1, disclosed
before any estimand ran). Instrument: `studies/third_stratum.py`. Reproduce:
`uv run python studies/third_stratum.py census|screen|verify` (census and screen are
offline over the corpus distillates + raw bulk tapes; verify is read-only Helius).
Artifacts: `studies/data/third_stratum/` (`census.json`, `membership.parquet`,
`screen_recompute.json`, `fn_check.parquet`, `board_s3_candidates.json`,
`old_corpus_s3_candidates.parquet`; `creates/` is predicate-validation scratch).
Budget: ~$0.5 of the $20 BigQuery authorization went to probe queries that found the
channel dead; the registered pull itself never ran ($0 local channel replaced it).

**Headlines.**

1. **What the stratum is**: pump's QUOTE-MINT curve — `CreateEvent.quote_mint = USDC`,
   `virtual_quote_reserves = 4_292_000_000` raw USDC ($4,292 = 30 SOL × $143.07, the
   dollar-denominated clone of the standard seed), the same integer mirrored into
   `virtual_sol_reserves`, supply exactly 1e15 at 6 decimals, not mayhem. Token-side
   indistinguishable from a standard birth — which is exactly how it sat inside B1's
   validated population unnoticed.
2. **The flagged "~7x mcap overstatement" was a CURRENCY MISLABEL, not a 7x error.**
   4.292 is not SOL; it is $4,292. A stratum-3 coin's k_std pseudo-SOL mcap equals its
   true marked USD cap / 143.07, so in SOL terms the error is P_SOL/143.07 — ~1.05x at
   $150, ~1.4x at $200. Real unit bug, bounded magnitude.
3. **The stratum is small and growing**: 0.96% of 1e15 births in 2026-08-05..14, 1.39%
   in 2026-08-26..28 (pooled Wilson 95% CIs below); 1,392 of B1's 91,505 scored coins
   (1.52%).
4. **The shipping precision claim SURVIVES — no restating.** Registered rule: the
   collapse-precision CI lower bound must stay ≥ 99.90% with the stratum excluded AND
   with its outcomes FX-corrected. It does, both ways (§3).
5. **No user-facing surface prints a wrong market cap.** No dregg surface computes a
   market cap from curve constants at all; every cap-like number a user sees is either
   our own scale-invariant tape measurement or a labeled provider claim (§4).
6. **The predicate is LIVE-computable** and now ships: hydrated launches get the
   authoritative CreateEvent/vault-leg detection at zero added spend; quote-curve
   launches are `in_validated_population = false` and can never mint a CLEAN (§5).

---

## 1. Membership predicate — and whether it can run live

**Corpus-side (census instrument, Amendment 1)**: the create transaction — the tx whose
legs of the born mint net exactly +1e15 in the birth slot — contains a USDC leg owned by
the coin's `curve_owner` (a quote-curve create initializes the curve's USDC vault in the
same transaction). Resolved **100.00% of births in both windows** (old: 266,928/266,928;
fresh: 104,380/104,380 — T1 coverage gate ≥ 99.5%: PASS, both). False-positive gauge:
1,842 creates carried a USDC leg NOT owned by the curve (someone else's USDC moving in
the same tx) — excluded by the ownership conjunct, counted, reported.

**Chain-side (authoritative)**: pump `CreateEvent` decoded from the create's own
`logMessages` with invoke-stack attribution, `virtual_sol_reserves == 4_292_000_000`,
`quote_mint == USDC`, `is_mayhem_mode == false`. `verify` concordance on a seeded sample
of 10 stratum-3 + 10 standard fresh mints: **20/20 agree**, every stratum-3 decode
carrying exactly vsol = vquote = 4,292,000,000 and quote = USDC, every standard decode
exactly 30e9. (One instrument fix was needed to get there, disclosed in §6.)

**Live?** YES, on every hydrated launch, at zero added spend: `dregg_screen.features.
detect_curve_seed` runs both witnesses on the create tx the screen already fetches —
the CreateEvent decode (authoritative, carries the exact seed) with the USDC-vault-leg
check as fallback for log-less RPC shapes. Pre-hydration the only witness is the vendor
frame's float seed estimate (`vSolInBondingCurve − solAmount` ≈ 4.292), which ships as a
**suspicion-only** population note — no quote-curve WebSocket frame has yet been retained
to verify the vendor's rendering, so cheap-path detection is flagged, never asserted.
The 87 retained frames of 08-29 contain zero stratum-3 creates (consistent with a ~1.4%
share on a small sample).

## 2. Share by day (T2) — census.json

| window | day | births (1e15) | stratum 3 | share | Wilson 95% |
|---|---|---:|---:|---:|---|
| old | 08-05 | 25,510 | 213 | 0.835% | [0.730%, 0.954%] |
| old | 08-06 | 24,118 | 286 | 1.186% | [1.057%, 1.330%] |
| old | 08-07 | 25,181 | 235 | 0.933% | [0.822%, 1.060%] |
| old | 08-08 | 25,528 | 216 | 0.846% | [0.741%, 0.966%] |
| old | 08-09 | 28,404 | 251 | 0.884% | [0.781%, 0.999%] |
| old | 08-10 | 28,932 | 216 | 0.747% | [0.654%, 0.853%] |
| old | 08-11 | 29,574 | 495 | 1.674% | [1.534%, 1.826%] |
| old | 08-12 | 26,324 | 201 | 0.764% | [0.665%, 0.876%] |
| old | 08-13 | 27,333 | 224 | 0.820% | [0.719%, 0.934%] |
| old | 08-14 | 26,024 | 216 | 0.830% | [0.727%, 0.948%] |
| fresh | 08-26 | 33,248 | 498 | 1.498% | [1.373%, 1.634%] |
| fresh | 08-27 | 37,953 | 464 | 1.223% | [1.117%, 1.338%] |
| fresh | 08-28 | 33,179 | 487 | 1.468% | [1.344%, 1.603%] |

Pooled: old **2,553/266,928 = 0.956%** [0.920%, 0.994%]; fresh **1,449/104,380 =
1.388%** [1.319%, 1.461%]. Declared anchor (recon: "~2.7% of board rows"): boards
over-represent the stratum roughly 2x — board rows skew toward coins that trade, and
the anchor was a board census, not a birth census. 08-11 is a real one-day spike
(1.674%), not an artifact — its per-mint rows are in `membership.parquet`.

Gap days 08-15..25 and 08-29: NOT measured. The registered event channel (BigQuery
`log_messages`) is dead — `[""]` on every sampled row of every sampled partition — and
the $0 replacement channel only exists where raw bulk tapes exist (the corpus days).

## 3. The B1 recompute (T3) — screen_recompute.json

Population: `combined/panel.parquet`, fresh window, `deployer.notna()` — n = 91,505,
the exact B1 population; stratum 3 inside it: 1,392 (1.52%). Variant (a) reproduces
`screen_seeded.json` exactly. Clopper-Pearson 95% CIs.

| variant | n | admitted (rate) | rip: bad / precision / CI | collapse: bad / precision / CI |
|---|---:|---:|---|---|
| (a) as shipped, k_std | 91,505 | 7,784 (8.51%) | 0 / 1.000 / [0.99953, 1] | 2 / 0.99974 / [0.99907, 0.99997] |
| (b) stratum 3 excluded | 90,113 | 7,270 (8.07%) | 0 / 1.000 / [0.99949, 1] | 2 / 0.99972 / [0.99901, 0.99997] |
| (c) FX-corrected @ $150 | 91,505 | 7,784 (8.51%) | 0 / 1.000 / [0.99953, 1] | 2 / 0.99974 / [0.99907, 0.99997] |
| (c') FX-corrected @ $200 | 91,505 | 7,784 (8.51%) | 0 / 1.000 / [0.99953, 1] | 2 / 0.99974 / [0.99907, 0.99997] |

The FX correction (stratum-3 peaks × 143.07/P) flipped **zero** outcomes at either
price — (c) and (c') are bit-identical to (a). Stratum 3's own descriptive row: 1,392
coins, **514 admitted CLEAN, 0 bad admits under every pricing convention**; the stratum
carries 9 collapses and 5 rips (same sets under k_std and fx150), all caught by the
gates. No stratum-3 precision claim ships from 3 days of exposure.

**RESTATEMENT RULE (registered): does the published claim need restating? NO.** The
collapse CI lower bound stays ≥ 99.90% in (b) (99.901%) and (c)/(c') (99.907%), so the
site's receipts line and the cards' precision sentence stand as measured. Going forward
the sentence is quoted for standard-seed coins only — quote-curve launches are outside
the validated population and never wear it (§5).

## 4. The market-cap audit — every surface, one verdict each

The crux distinction: a **provider-claimed** cap we label as theirs is their number and
their bug; a cap **we derive** from reserves/curve constants with the wrong k would be
ours. Sweep of every surface that prints a market cap or anything derived from one:

| surface | what it shows | mcap source | verdict |
|---|---|---|---|
| `dregg_screen` score rows + `tg_line` | dev-buy %, sniper counts, precision claim | none — no mcap field exists | **clean** (0 coins) |
| `dregg_screen/digest.py` (hourly digest) | pass rate, admit rate | none | **clean** |
| `dregg_feed/compose.py` (montage caption) | 5m volume "provider claims" label | `mc_usd` (pump's own `usd_market_cap`) is parsed and carried on `Alert` but **rendered nowhere** | **clean** — if ever shipped it is the provider's USD number, labeled |
| `dregg_feed/charts.py` (montage panels) | price/volume series, last close | none — swap-api candles (provider-served, `currency=SOL`) | **clean** — no cap label drawn |
| `dregg_wire` (`facts.py`/`wire.py`/`visuals.py`) | net realized SOL (our tape), "provider-claimed peak multiple — their number, not our measurement" | provider claim, labeled | **clean** |
| `dregg_dossier/cards.py` (/coin, /wallet) | SOL flow measurements from our tape | none | **clean** (see caveat below) |
| `dregg_gate/lookup.py` (/screen card) | verdict, gates, survival context | none | **clean** — now carries the USDC-curve gloss |
| `dregg_record` (caller leaderboard) | close-multiples measured from candles (ratios, scale-invariant); "claimed (theirs)" column | provider claim, labeled | **clean** |
| `dregg_archive` (`market_cap_first`) | stored, never rendered | provider's `marketCap` field, verbatim | **clean** — an archived provider claim |
| `dregg_site/pages.py` | one static "4,756 SOL market cap" sentence | the MAYHEM case tape (its own decoded stratum, administered pricing stated in the copy) | **clean** — not stratum 3, not k_std-derived |
| `dregg_portal` | stamped operating point, digest snapshots | none | **clean** |

**Bottom line: zero coins receive a wrong user-facing market cap from us.** Nothing in
the product computes `mcap = price × supply / k` from curve constants; the k_std
pseudo-mcap exists only inside the studies' outcome definitions (next section). Two
caveats for internal consumers, stated so nobody re-discovers them: (i)
`shitcoims_scalper` (research/trading, not a user surface) consumes the vendor's
`marketCapSol` float, which pump itself presumably mislabels on stratum-3 frames —
vendor floats there are already quarantined as unverified by design; (ii) the dossier's
"netted X SOL" tape measurements count SOL legs, so a stratum-3 coin's USDC-settled
flow reads as absence, not as a wrong number — the label stays true, the coverage gap
is this stratum's (1.4% of births, far less of traded volume).

### Do the rip/collapse detectors mis-fire on this stratum?

- `studies/operator_crime.py`: `is_rip` and `collapse` both require
  `peak_mcap_sol >= 100`, where `peak_mcap_sol` is the k_std pseudo-SOL cap. On a
  stratum-3 coin that reads marked-USD/143.07, so the "100 SOL" bar is really a
  "$14,307 marked cap" bar — ≈95.4 true SOL at $150 (over-inclusive by ~4.6%), ≈71.5 at
  $200 (~28.5%). **Measured effect on B1: zero.** The outcome sets are identical under
  k_std, fx@150, and fx@200 on the whole fresh window (§3), and none of the 514
  stratum-3 CLEAN admits is bad under any convention. No B1 verdict could have flipped.
- `dregg_screen` live: **no mcap threshold exists anywhere in the live path.** The five
  gates are birth-slot facts (snipers, dev-buy share) plus ledger history. The pseudo-
  mcap touches live output only through the seeded ledger's `prior_rips`/`prior_dumps`
  counts (corpus `is_rip` labels). Fresh-window labels are measured invariant; the old
  window was not recomputed (not registered), where the bounded ~5%-of-bar error could
  at most flip a marginal ~100-SOL-peak stratum-3 coin's label inside some deployer's
  history — an over-inclusive direction (more KNOWN_CREW, never more CLEAN).

## 5. What shipped (T4, registered before measurement)

Live code (in `dregg_screen` + `dregg_gate`, tests green):

- `features.detect_curve_seed` — both witnesses, CreateEvent-first;
  `BirthFeatures.quote_curve/curve_quote_mint/curve_seed_source/curve_seed_vsol`;
  `CheapFeatures.v_sol_seed_est` + `quote_seed_suspected` (vendor-float, ±1e-3 of 4.292).
- `score.score_launch` — hydrated quote-curve rows get population note
  `quote_curve:usdc:outside_validated_population` (⇒ `in_validated_population = false`,
  so the digest's pass-rate denominator, the site's validated-admits list, and the
  precision quoting all exclude them structurally); a quote-curve launch that passes
  all five gates is **UNSCORED** with reasons `quote_curve_screen_not_measured`,
  `five_gates_passed` — CLEAN is the name of a measured precision claim and this
  stratum has none. Feature-fact verdicts (KNOWN_CREW / BUNDLED / NOT_CLEAN) still fire
  — birth-slot facts are valid here. Unhydrated suspicion ships as
  `vendor_seed:quote_curve_suspected:unverified`, note only.
- Plain-language copy: gate card reasons ("its bonding curve is priced in USDC, not
  SOL — a launch type the screen's hit rate has never been measured on, so no clean
  stamp is given"), population-note glosses, and a widened digest UNSCORED gloss. The
  jargon blacklist gained `quote_curve` / `five_gates_passed` / `vendor_seed:` so the
  raw codes can never reach a Telegram surface.
- Tests: `tests/test_dregg_screen.py` (leg witness incl. the not-curve-owned USDC
  negative, encoded-CreateEvent log witness for both seeds, never-CLEAN ship rule,
  BUNDLED-stays-BUNDLED, suspicion-note-until-hydration) and the quote-curve rows in
  `tests/test_dregg_copy_invariants.py`'s worst-case sweep. All dregg suites green;
  ruff clean.

## 6. Deviations from the registration

1. **Amendment 1 (in the registration, pre-estimand)**: BigQuery channel dead → $0
   local leg channel; rescale constant corrected from 4.292/30 to 143.07/P (the
   currency-mislabel discovery). Both disclosed before census/screen ran.
2. **"Any OTHER seed value counted per value" is not observable corpus-side**: the leg
   witness is binary (USDC vault present/absent), so no per-value seed distribution
   exists in the census. Reported instead: the 1,842-create FP gauge, foreign-mint sets
   on stratum-3 creates, and exact seed values on the verify sample (20/20 at exactly
   4,292,000,000 / 30,000,000,000; no third value seen).
3. **T1 product identification** (`quote_mint`/`virtual_quote_reserves`/
   `token_program`/`is_cashback_enabled` distributions) shipped as verify-sample spot
   checks only, same reason.
4. **T2 gap days** (08-15..25, 08-29) not measured — the pull that would have covered
   them never ran (see §2).
5. **`cmd_verify` instrument fix (post-hoc, this session)**: the original took the
   mint's oldest signature as the create; a FAILED same-slot tx (losing sniper race)
   can be older, and one sample mint (`AaoWrw4w…`, slot 442127479) mis-read as "no
   CreateEvent" until the selection was pinned to the oldest **successful** signatures
   (the registration's own `err IS NULL`). After the fix: 20/20. The failed-first
   pattern is itself corroborating — bots raced that stratum-3 birth slot.
6. `fn_check.parquet` records the 51 board-k-identified old-window candidates used to
   validate the leg predicate before adoption: 49/51 carry the USDC leg (45 pure, 4
   USDC+wSOL mixes); the 2 without were Helius-decoded as genuinely STANDARD (board
   reserve snapshots can mislabel; birth legs did not).

None of the registered falsifiers tripped: coverage 100% (≥ 95%), every decoded
stratum-3 event agrees with the boards' 4.292e9 constant exactly, and the share (1.4%)
is nowhere near the 20% escalation bar.
