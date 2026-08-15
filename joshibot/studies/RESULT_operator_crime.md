# RESULT: operator crime — the blind zone was never about the unit of analysis

*Study code: `studies/operator_crime.py`, `studies/operator_crime_discriminators.py`,
`studies/operator_crime_benford_strat.py`. Controls: `tests/test_operator_crime.py`.
Artifacts: `studies/data/operator_crime/` (gitignored). Corpus: `state/bulk_pump/raw/`,
2026-08-05 .. 2026-08-14. Run 2026-08-15. **Spend: $0.00** — no BigQuery, no vendor API, no
Helius calls; every number below comes from parquet already on disk.*

Reproduce:

```
uv run --group research python -m studies.operator_crime ledger    # ~15 min, 28 GB in
uv run --group research python -m studies.operator_crime census    # ~10 min
uv run --group research python -m studies.operator_crime coins
uv run --group research python -m studies.operator_crime panel
uv run --group research python -m studies.operator_crime verify    # falsify the price identity
uv run --group research python -m studies.operator_crime labels
uv run --group research python -m studies.operator_crime graph  --n-null 100 --max-deployers 400
uv run --group research python -m studies.operator_crime predict
uv run --group research python -m studies.operator_crime risks
uv run --group research python -m studies.operator_crime screen
uv run --group research python -m studies.operator_crime tape      # for the discriminators
uv run --group research python studies/operator_crime_discriminators.py \
    --tape studies/data/operator_crime/tape.parquet \
    --cohort studies/data/operator_crime/cohort.parquet \
    --out studies/data/operator_crime/discriminators --tag final10d
```

---

## 0. The answer

**The operator reframe is half right, and the half that is wrong is the interesting half.**

`RESULT_crime_signatures.md` found that 16 of 23 mechanical cliffs complete inside a pool's
first 0–45 hours and concluded the detector was structurally blind where the money is. The
operator's critique — that the blind zone was an artifact of treating the COIN as the unit,
when crime is a repeated game by persistent operators — motivated this study. Ten days of
full pump.fun flow says:

1. **The blind zone was a DATA problem, not a unit problem — and it is far narrower than
   45 hours.** Cause-specific cumulative incidence says **96–99% of a coin's lifetime rip
   risk has already been realised one hour after it exists.** The prior study was blind there
   because its instrument was hourly price history, which by construction has nothing at hour
   zero. The birth slot itself is enormously informative and needs no history at all:
   coin-intrinsic birth features alone score **AUPRC 0.0274, 4.93× the base rate**, against
   an EdgeBank-style memorisation baseline at 1.13×. Bundled-at-birth coins rip at
   **1.598%** against **0.070%** for unbundled — a **23×** separation from one slot of data.
2. **There IS a persistent actor, and it is not the deployer.** Same-deployer coins share
   birth-slot sniper wallets at mean Jaccard **0.2834** against **0.0014** for day-matched
   different-deployer pairs, and **51.2× a degree-preserving (curveball) null** at
   p < 0.01. The bot crews are reused. Crew history adds a real **+13.7%** to the birth-slot
   features.
3. **The DEPLOYER's own history predicts, but adds nothing you did not already have.** Arm B
   (deployer history only) scores 0.0127 = 2.28× base and beats its rotation null decisively
   (p_rot < 0.01) — so the signal is real, not an artifact. But adding it to the birth-slot
   features **does not improve them** (0.0312 → 0.0278). Everything the deployer's past knows
   is already legible in the coin's first slot.
4. **The mechanical label works, and it is 180× the prior study's evidence base.**
   **1,271 rips** in ten days with timestamps and named perpetrator wallets, against the
   prior study's 7 scorable cliffs. 4,053 distinct perpetrator wallets; the busiest single
   wallet dumped on **55** different coins, and thirteen wallets dumped on 51 each.
5. **The product works, and it is the most shippable thing here.** A birth-time CLEAN screen
   — no bundle, small dev buy, no recidivist sniper, no prior operator dump — admits **4.8%**
   of new coins and, on a **price-only outcome the screen's gates do not construct**, is
   clean **99.96%** of the time: it admits **2 of 771** collapses. That is a **20× reduction**
   in collapse rate at the cost of looking at one coin in twenty.
6. **One gate points the opposite way from intuition and it matters for the product.**
   "This deployer has never dumped before" is a **RISK** factor, not a safety factor: those
   coins collapse at **1.71×** the base rate. A clean record is mostly indistinguishable from
   no record, and no record means a first-timer.
7. **Three of the four cheap discriminators are nulls, and two of them are nulls for a reason
   worth keeping.** NCD does cluster same-deployer coins — but 63% of the effect survives
   shuffling each tape's order, so it is a **size-histogram fingerprint, not a sequence one**.
   Lomb–Scargle finds no scheduler and *cannot*: `block_time` is 1-second resolution and 63.3%
   of consecutive trades share a timestamp, so the event rate sits above the sampling Nyquist
   and every flagged peak piles up at a band edge. The size-vs-impact exponent separates arms
   and the separation is **61% volatility** — the `vol-control` lesson arriving in a new place.
   Benford's serial-arm effect dies once trade-size repetition is held fixed (§8).

**What this does not do: it does not give an exit signal, and it does not predict which
coins go up.** Everything here is birth-time triage.

---

## 1. The corpus, and three things the brief got wrong about it

Ten days of every balance-changing transaction touching a pump-suffixed mint.

| | |
|---|---:|
| raw transactions | **106,639,238** |
| distinct signatures | 106,639,200 |
| rows with `err = ''` (success) | **106,639,238** |
| derived ledger rows (signed balance changes) | **301,592,622** |
| mints appearing at all | 449,727 |
| **pump.fun creates in-window** | **266,928** |

Three corrections, each established by reading all ten days rather than the docstring:

* **There is no signer column and no fee-payer column.** The schema is exactly `signature,
  block_slot, block_time, tx_index, fee_lamports, err, compute_units, pre, post` plus
  provenance. Identity in this corpus is the token-account **owner** — the beneficial holder,
  not the signer. This kills the fee-payer fingerprint outright: the prior "10 fee payers =
  46.6% of failures" result (`RESULT_execution_landing.md`) **cannot be extended here**, and
  every wallet named in this document is an owner.
* **Every row is a success.** `err = ''` on 106,639,238 of 106,639,238. The export dropped
  reverts, so failure-rate fingerprints are unavailable too. Both are limitations of the
  *pull*, not of the chain; a re-pull recovers them and would be worth doing.
* **38 duplicate signatures** exist (106,639,238 rows, 106,639,200 distinct). Immaterial at
  this scale, recorded so the next study does not treat `signature` as a primary key.

The corpus also has no SOL transfers (it is filtered to pump-mint balance changes), so
**funding lineage is not available** and no claim below rests on it. §6.3 is what replaced it.

---

## 2. The instrument: pricing 266,928 coins from the curve alone, and falsifying it

This is the enabling result and it is worth more than any single number in §5.

A pump.fun bonding curve holds *native* SOL in a PDA, which is not a token balance, so this
corpus never shows the SOL leg of a pre-migration trade. That looks fatal for pricing and is
not, because a bonding curve is constant-product against virtual reserves:

> `p = sol/tok` and `sol · tok = k`  ⟹  **`log p = log k − 2 log(v_tok)`**

so **log price is an exact affine function of the curve's own token balance**. The constants
are recovered from data already on disk rather than from folklore: `state/boards/` carries
`virtual_sol_reserves × virtual_token_reserves = 3.219e25` on every standard row, and
`state/firehose/new_token/` confirms the split independently (a create with `initialBuy =
17,376,518.132293` leaves `vTokens = 1,055,623,481.867707`, summing to 1,073,000,000.000000
exactly; `vSol = 30.493827158 − 0.493827158 = 30.0` exactly). Hence

```
v_tok = curve_token_balance + 7.3e13          k = 3.219e25
mcap_lamports = k · 1e15 / v_tok²
```

### 2.1 Two independent checks, one of which we could have failed

**Internal.** The curve stops selling when its *tradeable* reserve is gone, not when its
balance is gone — 206.9M of the 1e9 supply is held back for the migration LP. So graduation
must occur at `v_tok = 2.799e14`, i.e. **411 SOL**. Observed median peak over 6,549 graduated
coins: **410.9 SOL**. (Reading the peak at `bal = 0` instead gives a nonsense 6,040 SOL,
identical for every graduated coin — §10 trap 3.)

**External, and genuinely independent.** `state/boards/` is a vendor feed we did not derive.
Comparing its `virtual_token_reserves` against ours at the same wall-clock second:

| | |
|---|---:|
| on-curve board snapshots (`complete = false`) | 12,541 |
| carrying the standard `k = 3.219e25` (to 0.1%) | **69.13%** |
| standard-curve probes joined to our path | 6,583 |
| median \|ours − vendor\| / vendor, all | 0.13% |
| ... restricted to snapshots ≤ 60 s stale (n = 6,137) | **0.118%**, p90 3.663% |

**The staleness split is itself the result.** The vendor's board clock is an *ingest* time,
not a chain time — the two-clock rule again — and a coin that traded 300 times since the
snapshot has genuinely moved. Conditioned on the snapshot being current, our curve balance
reproduces a number we never saw to within **0.12%**.

### 2.2 The honest limit

**31% of on-curve coins run a non-standard curve** (pump.fun's boosted / "mayhem mode"
launches), where `k ≠ 3.219e25`. Their market caps here are approximate. Market cap enters
this study only as a *materiality screen* (`peak ≥ 100 SOL`) and never as a fitted quantity,
so the cost is cohort membership rather than a biased estimate — but a study that wanted
market cap as an outcome would have to solve this first.

---

## 3. Membership: what counts as a coin

A mint is **born in-window** iff the net token supply created at its first observed
transaction is exactly the pump.fun supply. Supply is minted from nothing, so a create is the
one transaction whose token legs do not sum to zero — and it does so by exactly 1e15 raw.

This replaced a first version that asked "was the curve funded with a lot", which mis-sorts
every coin with a large dev buy (the curve's seed leg is `1e15 − dev_buy`, so a creator who
bought 20% of his own coin looked like a smaller launch). On 2026-08-05, of 66,316 mints that
traded:

| first-transaction net | mints | reading |
|---|---:|---|
| **exactly 1e15** | **25,510** | a pump.fun create, in-window |
| zero | 25,581 | ordinary trade; the coin predates the window |
| negative | 6,479 | likewise |
| other positive | 8,746 | mostly 1e18 single-leg seeds — a 9-decimal token wearing the `pump` suffix. Excluded and counted, not rescaled |

---

## 4. The labels: 1,271 rips, with names

The brief asked how many labelled events ten days contain. The honest answer is a **ladder**,
because "an insider dumped" on its own is close to universal and says nothing. Each rung adds
one materiality condition.

| label | coins | share |
|---|---:|---:|
| coins born in-window | 266,928 | 100.00% |
| with an identified deployer | 218,652 | 81.91% |
| graduated (curve emptied to the pool) | 6,549 | 2.45% |
| **bundled at birth (≥2 birth-slot buyers)** | **116,266** | **43.56%** |
| no birth-slot buyer at all | 46,468 | 17.41% |
| insider set disposed ≥80% of its peak | 167,662 | 62.81% |
| … and held ≥2% of supply | 119,220 | 44.66% |
| … and held ≥5% of supply | 103,629 | 38.82% |
| … and held ≥10% of supply | 85,706 | 32.11% |
| … and held ≥20% of supply | 55,430 | 20.77% |
| … ≥5% of supply and peak ≥ 50 SOL | 54,001 | 20.23% |
| … ≥5% of supply and peak ≥ 100 SOL | 16,517 | 6.19% |
| … ≥5% of supply and peak ≥ 200 SOL | 6,747 | 2.53% |
| **RIP (all four conditions)** | **1,271** | **0.48%** |

`RIP` is pre-registered as the conjunction: the insider set disposed ≥80% of its own peak
holding; that holding was ≥5% of supply; the coin's peak market cap was ≥100 SOL; and the
price fell ≥90% from its peak.

Two facts worth reading off this table before any model:

* **43.56% of new pump.fun coins are bundled at birth** — two or more wallets buying in the
  same slot as the create, which cannot happen organically because the mint did not exist one
  slot earlier. This is the on-chain bundle shape, and it needs no Jito bundle id (which is
  not on chain at all). It is in the right neighbourhood of MELT's 36.5%-of-supply-in-
  coordinated-hands prior, derived completely differently.
* **Only 1,271 of 16,517 material insider dumps (7.7%) also cratered the price ≥90%.**
  Insiders dumping a ≥5%-of-supply position on a ≥100 SOL coin usually does *not* kill it.
  "Insider sold" and "coin died" are much less coupled than the folk model assumes.

### 4.1 There is no LP-pull population to label, and that is measured

The brief asked for **LP-pull** labels alongside insider-dump labels. On pump.fun the
migration hands the pool its reserves and the LP position is not the deployer's to withdraw,
so the classic "pull the liquidity" rug should be structurally unavailable — which is folklore
until it is counted. A withdrawal is mechanically distinct from a trade: **a trade moves the
pool's two legs in opposite directions; a withdrawal moves both out.** One predicate over every
post-migration pool transaction:

| | |
|---|---:|
| post-migration pools observed | 6,549 |
| pool transactions | 51,512,871 |
| **coins with ANY dual-leg outflow** | **12 (0.18%)** |
| such transactions | 30 |

**Confirmed: LP pulls essentially do not happen on pump.fun.** The entire rug surface here is
supply disposal, which is why §4's ladder is built on holdings and not on liquidity. A study
importing an Ethereum-shaped rug taxonomy would have spent its time on a population of twelve.

### 4.2 The perpetrators, and their recidivism

| | |
|---|---:|
| (coin, wallet) disposals inside a rip window | 6,688 |
| ripped coins | 1,271 |
| distinct perpetrator wallets | 4,053 |

| coins ripped by one wallet | wallets |
|---:|---:|
| 55 | 1 |
| 51 | 13 |
| 49 | 1 |
| 47 | 1 |
| 41 | 2 |
| 36 | 1 |

**Thirteen wallets each dumped on 51 different coins in ten days.** That is the "reusable
infrastructure" claim, visible without any clustering at all.

---

## 5. The predictive test

Temporal split on birth time: train = days 0–4, test = days 5–9. Every history feature is
computed over events whose own timestamp precedes the coin's birth (§10 trap 4). Entity =
deployer; 52.3% of test coins have a deployer seen in training, which is the mechanism, not a
leak.

| | train | test |
|---|---:|---:|
| coins (with a deployer) | 107,202 | 111,450 |
| rips | 582 (0.5429%) | 621 (0.5572%) |

### 5.1 Baselines first

| baseline | AUPRC | × base rate |
|---|---:|---:|
| EdgeBank-style memorisation (this deployer's train rip count) | 0.0063 | 1.13× |
| decayed popularity (this deployer's launch count) | 0.0053 | 0.95× |
| random | 0.0056 | 1.00× |

**The naive operator prior does essentially nothing.** "This deployer rugged before, so he
will rug again" is worth 1.13× the base rate. If the study had stopped at the obvious version
of its own hypothesis, the answer would have been a null.

### 5.2 The arms

| arm | features | AUPRC | × base | P@100 | P@1000 |
|---|---|---:|---:|---:|---:|
| **A0** coin-intrinsic | `n_snipers`, `dev_buy_share` | **0.0274** | **4.93×** | 0.060 | 0.046 |
| **A1** sniper-crew history | `sniper_recidivism`, `sniper_prior_max` | 0.0205 | 3.68× | **0.090** | 0.044 |
| **A** both of the above | | **0.0312** | **5.60×** | 0.060 | **0.059** |
| **B** deployer history | `prior_launches/rips/dumps/grads`, rates, recency | 0.0127 | 2.28× | 0.040 | 0.023 |
| **C** everything | | 0.0278 | 4.99× | 0.070 | 0.040 |

### 5.3 The null: give this coin somebody else's operator

The history block is permuted across test coins, **stratified on `prior_launches`**, so every
coin keeps a history of exactly the right *size* and loses only whose it was. The model is
refit on the untouched training half and re-scored, so the comparison is like-for-like.

| arm | observed | null mean | null p95 | p_rot | beats null |
|---|---:|---:|---:|---:|---|
| B deployer history | 0.0127 | 0.0083 | 0.0085 | **< 0.01** | **YES** |
| C everything | 0.0278 | 0.0244 | 0.0254 | **< 0.01** | **YES** |

**So operator history is real.** It is not an artifact of some operators launching more coins.

### 5.4 …and it is redundant

| comparison | Δ AUPRC | ratio |
|---|---:|---:|
| C (everything) − A (birth slot) | **−0.0034** | **0.891×** |
| A (birth slot) − A0 (coin intrinsic) | **+0.0038** | **1.137×** |

Read together, these two lines are the study's verdict. The **deployer's** past adds nothing
once the birth slot is known — the point estimate falls, and while a fall of that size is
within what adding seven features to a fixed sample can do by itself, there is certainly no
gain. The **sniper crew's** past adds a real +13.7%.

> **The persistent actor that predicts a rug is the bot crew, not the creator.**

This is consistent with §6.2: crews are reused 51× above a degree-preserving null, whereas
the deployer wallet is cheap to rotate and evidently is rotated.

### 5.5 Competing risks — and the blind zone is even worse than the prior study found

AUPRC answers "does it rip" and not "when", and it treats a coin that **graduated** as a
non-event when graduation is a competing outcome that removes the coin from risk on the curve
entirely. Cause-specific cumulative incidence is the right object. Censoring is clock-based
(PROGRAM.md §3.8): a coin still trading at the window edge is censored there.

218,652 coins — **1,203 RIP**, **6,380 GRADUATED**, 211,069 censored.

**P(RIP by t), cause-specific, in the presence of graduation:**

| stratum | 1 h | 6 h | 24 h | 72 h |
|---|---:|---:|---:|---:|
| operator has never ripped (`prior_rips = 0`) | 0.477% | 0.482% | 0.485% | 0.486% |
| operator has ripped 1–2 before | 0.709% | 0.730% | 0.730% | 0.730% |
| operator has ripped 3+ before | **1.233%** | 1.233% | 1.243% | 1.243% |
| **no bundle at birth** (`n_snipers ≤ 1`) | **0.066%** | 0.067% | 0.069% | 0.070% |
| **bundled at birth** (`n_snipers ≥ 5`) | **1.572%** | 1.594% | 1.596% | 1.598% |

Two readings, and the first is the more important finding in this section:

* **Essentially every rip has already happened by hour one.** Across every stratum, the
  cumulative incidence at 1 hour is 96–99% of its value at 72 hours. `RESULT_crime_signatures.md`
  put 16 of 23 cliffs in the pool's first 0–45 *hours* and called that a blind zone for a
  48-hour feature window. At the scale of a full corpus it is far sharper than that: **the
  window in which a rug can be predicted at all closes about sixty minutes after the coin
  exists.** No price-history detector of any window length can operate there. A birth-slot
  detector can, which is why §7 is the shippable part of this study.
* **The birth slot separates 23×; the operator's record separates 2.6×.** `n_snipers ≤ 1` vs
  `≥ 5` is 0.070% vs 1.598%. Prior rips 0 vs 3+ is 0.486% vs 1.243%. Both are real and monotone;
  they are not the same size, and the bigger one needs no history at all.

*(Aalen–Johansen refuses exact ties and `block_time` is 1-second resolution, so lifelines
jitters tied event times. The estimator warns about it on every stratum; the effect at these
separations is immaterial and the warning is left visible rather than silenced.)*

---

## 6. The operator graph

### 6.1 Deployers

| | |
|---|---:|
| coins with a deployer | 218,652 |
| distinct deployers | 53,335 |
| deployers with >1 coin | 12,141 (**66.5% of all coins**) |
| with ≥5 / ≥10 / ≥50 coins | 4,733 / 2,518 / 610 |
| busiest deployer | **1,563 coins in ten days** |

Two thirds of pump.fun's output comes from repeat launchers. The unit-of-analysis critique was
right about *that* much: these are not i.i.d. coins.

### 6.2 Sniper reuse — the one big positive

Arm: top 400 deployers by launch count, capped at 25 coins each (same-deployer pairs are
quadratic in a deployer's coin count, and one operator with 1,563 coins would contribute 1.2M
pairs and dominate the mean). 9,999 coins, 1,519 distinct birth-slot wallets (deployers included in that count),
19,111 ex-deployer edges.

| | mean Jaccard |
|---|---:|
| same-deployer pairs (n = 119,976) | **0.2834** |
| day-matched different-deployer pairs (n = 119,976) | 0.0014 |
| **ratio** | **203×** |
| degree-preserving (curveball) null, n = 100 | mean 0.0055, p95 0.0057, max 0.0059 |
| **effect over the null** | **51.2×**, p_curveball < 0.01 |

**The deployer is excluded from its own coins' sniper sets and that is not a detail.** A create
carries the dev buy, so the deployer is a birth-slot buyer of every coin it launches — it is
in all 25 of its own sniper sets *by construction*. Left in, the same statistic reads
**0.7754** instead of 0.2834. The inflated number is printed beside the real one by the code
so the size of the artifact is visible rather than argued about; this is the same failure that
built a 138-wallet mega-entity in `RESULT_copytrading.md` §3.

The comparison arm is **day-matched** for the same reason: two coins born the same day draw
snipers from the same ambient pool of bots, so an all-time random pair would measure the
calendar.

### 6.3 Custody transfers — an honest negative

The corpus has no SOL transfers, so `RESULT_entity_resolution.md`'s typed funding edge ("a
native SOL transfer that is the account's first inbound SOL") is unavailable. The substitute
is **token custody**: a transaction moving one pump mint between exactly two accounts, equal
and opposite, with the curve absent and **no WSOL leg at all** — nobody was paid, so it is
custody-shaped rather than co-timing-shaped, and therefore admissible as ground truth for a
clustering that a temporal test will use.

| | |
|---|---:|
| direct token transfers | 904,574 |
| distinct wallets | 208,096 |
| connected components | 9,907 |
| **giant_component_share** | **0.452** |

**This does not work as entity resolution, and the diagnostic is exactly the one the label
file warns about.** Union-find over custody transfers collapses 45% of all wallets into one
component, and **FOMO's relayer sits inside that 94,004-wallet blob** — an infrastructure hub
absorbed into a single "entity", which is the documented failure mode. Reported as a negative;
no clustering downstream of it is used anywhere in this study.

### 6.4 Known-entity validation

| wallet | in ten days of corpus |
|---|---|
| `shitcoims` | PRESENT — 287 changes over 112 mints |
| `tha_funds` | PRESENT — 229 changes over 12 mints |
| `pumpfun_main` | **ABSENT** |
| `ember_dev` | PRESENT — 5 changes over 1 mint |
| `og_shitcoims` | PRESENT — 11 changes over 5 mints |
| `fomo_family_relayer` | PRESENT — 58,270 changes over 11 mints |

**The "the operator's five wallets must cluster together" validation is NOT TESTABLE in this
corpus, and saying so is the result.** Only two of the five appear in any direct custody
transfer at all: these wallets *trade*, they do not hand pump tokens to each other. There is
no edge on which to test whether they cluster. The FOMO check *is* testable and it **fails**
(§6.3).

### 6.5 A label-file bug found and fixed on the way

`wallet_labels.yaml` recorded FOMO's relayer as `AgmLJBMDwDrsyNsFC1JS8yeAJt8DBB1cJC4dyLctnh4c`.
Its own cited source, `RESULT_copytrading.md` line 24, and the code that produced it,
`studies/copytrading.py` line 164, both say `AgmLJBMDCqWynYnQiPCuj9ewsNNsBJXyzoUhD9LJzN51` —
sharing only the first **eight** characters. Both decode to valid 32-byte pubkeys, so nothing
syntactic catches it. Only `...CqWyn...` appears on chain (58,270 balance changes); the
`...wDrsy...` string appears nowhere else on disk and nowhere in 106M transactions. Given the
`address_poisoning` block in that same file, a prefix-matching lookalike sitting *in the label
file* is precisely the failure the file exists to prevent. **Corrected**, with the old value
retained as `superseded_address`.

---

## 7. The product: a birth-time CLEAN screen

The operator's use case is a $40 taste bet, so the asymmetry is explicit: **a false CLEAN is
worse than a false DIRTY**, and the operating point is chosen for *precision of CLEAN*.
Recall is reported but is not the target — there are 25,000 new coins a day.

Test half only: 111,450 coins. **Two outcomes are scored, and the second is the honest one.**
`is_rip` is built from the insider set and three of the five gates are also built from the
insider set, so a perfect score against it would be substantially *definitional*. `collapse`
is a ≥90% fall from a ≥100 SOL peak computed from the **curve alone**, with no reference to
who sold.

### Outcome: `collapse` (price only) — base rate 0.6918%

| gate | passes | P(clean) | collapse lift |
|---|---:|---:|---:|
| no bundle at birth (`n_snipers ≤ 1`) | 51,889 | 99.8863% | **0.16×** |
| dev buy under 2% of supply | 46,599 | 99.7704% | **0.33×** |
| no recidivist sniper (`sniper_prior_max = 0`) | 9,904 | 99.4043% | 0.86× |
| deployer has never ripped | 90,904 | 99.3631% | 0.92× |
| **deployer has never dumped** | 33,574 | 98.8146% | **1.71×** |
| **ALL GATES — the CLEAN screen** | **5,322** | **99.9624%** | **0.05×** |

**Operating point: the screen admits 4.8% of new coins and is clean 99.96% of the time,
letting through 2 of 771 collapses.** Against the insider-mechanical `is_rip` label it admits
0 of 621, but that number is partly definitional and the 99.96% is the one to quote.

### 7.1 It is not a censoring artifact

A coin born on the last day of the window has hours in which to collapse, so a screen
evaluated on the whole test half could be flattered by coins that simply have not died yet.
Requiring a minimum observation window:

| minimum observation | test coins | passing the screen | collapse base | P(clean) | lift |
|---|---:|---:|---:|---:|---:|
| 0 h | 111,450 | 5,322 | 0.6918% | 99.9624% | 0.05× |
| 1 h | 110,693 | 5,188 | 0.6911% | 99.9614% | 0.06× |
| 6 h | 105,364 | 4,946 | 0.6881% | 99.9596% | 0.06× |
| 24 h | 90,430 | 4,351 | 0.7033% | 99.9540% | 0.07× |
| 48 h | 68,134 | 3,560 | 0.7148% | 99.9719% | 0.04× |

Flat. Which §5.5 predicts: if essentially all the risk is realised in the first hour, then
observing a coin for two days rather than one hour cannot reveal much more of it.

Three things a reader should take from the gate table rather than from the bottom line:

1. **The bundle gate does nearly all the work** (0.16×), and it is available in the coin's
   first slot. Dev-buy size is second (0.33×).
2. **"This deployer has never dumped" is a RISK factor at 1.71×.** A clean record is mostly
   indistinguishable from *no* record, and no record means a first-time deployer. The absence
   of history is not evidence of innocence — this inverts the most natural manual heuristic
   and is the single most actionable line in the document.
3. The screen is **not** an edge. It says nothing about which of the 5,311 admitted coins goes
   up; it says that if you are going to make twenty $40 bets, these are the ones where the
   money is lost to the market rather than to a bundle.

---

## 8. The four cheap discriminators

*Code: `studies/operator_crime_discriminators.py` (+ `studies/operator_crime_benford_strat.py`).
Artifacts: `studies/data/operator_crime/discriminators/`. Seed 20260815. Run on the ten-day
tape — 8,655,040 bonding-curve transactions over 17,234 coins; the three-day tape reproduces
every sign and every verdict.*

Each was budgeted as an afternoon with a null attached, on the understanding that a null is a
result. **Three of the four are nulls, and two of the three are nulls for an instructive
reason rather than for want of signal.**

### 8.1 Three data pathologies, and one of them invalidates a natural mistake

* **A ledger row is a LEG, not a trade.** 5.05% of curve transactions carry 2–20 rows sharing
  one `curve_bal_after`. Checking the chain identity `curve_bal_after[i] + Σq[i] ==
  curve_bal_after[i−1]`: per row it fails **20.2%** of the time, per transaction **3.9%**.
  Trade size must be `sum(delta_raw)` over `(mint, block_slot, tx_index)`. **Any future test
  on this tape that uses a row as a trade misstates ~5% of its sizes.**
* **1-second quantization is severe.** 63.3% of consecutive curve transactions share a
  `block_time` (Δt = 0 s); median gap 0 s, p90 3 s. The event rate sits *far above* the
  timestamp Nyquist of 0.5 Hz.
* **Round numbers live in SOL, not in tokens.** The implied-SOL first-digit law is badly
  non-Benford (MAD 0.0212; digit 9 at 11.7% against 4.6% expected; 6.7% of trades round to
  0.01 SOL), because users specify SOL. Token deltas are curve-determined and near-continuous,
  so the ambient *token* law is nearly Benford (MAD 0.0078). Test (b) runs on tokens and is
  clean of the artifact — which also means "deviates from Benford" carries no forensic content
  here.

### 8.3 (a) Normalized compression distance — **SURVIVES, but not as claimed**

Serialization, stated: three ASCII bytes per trade in chain order — `B`/`S`; `chr(65 + min(63,
⌊log₂|q|⌋))`; `chr(97 + min(25, ⌊log₂(1+Δt_s)⌋))`. No address, no absolute time, no mint.
Truncated to the first N; coins shorter than N are **excluded, not padded**, so every string is
exactly 3N bytes. `C = len(zlib.compress(s, level=9))`; zlib's 32 KiB window exceeds 2×3N so
the concatenation is fully cross-referenceable.

| N | NCD same-deployer | different | Cohen's d | p (1,999 label perms) |
|---|---:|---:|---:|---:|
| 256 (4,034 coins, 169,293 same-pairs) | 0.85634 | 0.86441 | **−0.371** | 0.0005 |
| 256, **shuffled tapes** | 0.85094 | 0.85577 | −0.232 | 0.0005 |
| 512 (2,222 coins) | 0.91131 | 0.91630 | −0.280 | 0.0005 |
| 512, **shuffled tapes** | 0.89959 | 0.90289 | −0.182 | 0.0005 |

**The second null is the whole story.** Shuffling each coin's trade order — same
(direction, size, gap) multiset, sequence destroyed — retains **62.6%** of the effect at N=256
and 65.1% at N=512. So same-deployer coins do compress together, and two thirds of that is a
**size-histogram fingerprint**, not a sequence one. The absolute gap is also small: 0.008 of
NCD on a base of 0.86, about 0.9%. Unmistakable in aggregate, useless on a single coin.

### 8.4 (b) Benford — **NULL for the serial arm; the rest is trade-size diversity**

Per-coin MAD from the first 50 trades against a **finite-sample floor of 0.0337** (20,000
simulations of 50 draws from the ambient law; p95 0.0496). Observed per-coin mean 0.052,
median 0.0449 — most of a coin's MAD is sampling noise.

| contrast | Cliff's δ | p | **δ stratified by repetition** |
|---|---:|---:|---:|
| serial vs solo | −0.076 | 6.5e−18 | **+0.007** |
| high vs low snipers | −0.219 | 6.5e−137 | **−0.161** |
| dumped vs not | −0.269 | 2.5e−136 | **−0.112** |

All three point the **same** way, and it is the *opposite* of the classic fabrication
direction: crime-adjacent coins sit **closer** to Benford. That inversion is what exposed the
confound. MAD is inflated by repetitive early tapes (Spearman ρ = −0.192 between distinct |q|
in the first 50 trades and MAD); distinct-size means run 37.5 for not-dumped vs 44.7 for
dumped. Stratifying on distinct-size count **annihilates the serial-vs-solo effect** and halves
the other two. What survives is a trade-size-diversity signal wearing a forensics costume.

### 8.5 (c) Lomb–Scargle — **NULL, and the naive version is an artifact detector**

400 log-spaced frequencies, astropy-standard normalization, 19 realizations of each null per
coin. Two nulls: **rotation** (rotate the value sequence, hold x fixed so the quantization comb
is identical) and **Poisson-matched** (same n, same T, rounded to whole seconds exactly as
`block_time` is).

**The nulls are the finding.** Against a 5% expectation, the detrended statistic beats the
Poisson null on **69.7%** of coins — which says only that arrivals are bursty — and the
rotation null, which holds the marginal gap distribution and the sampling geometry fixed, on
**15.3%**.

The peak-period histogram of the 2,344 flagged coins settles it: **651 sit in 255–339 s and
370 in 192–255 s, at the top of the accessible band (P_max = 300 s)**, and 113 sit at exactly
**2.0 s, the Nyquist edge**. Both piles are band-edge artifacts. **There is no mode at any
bot-plausible period — nothing at 5, 10, 15, 30 or 60 s.**

The honest form of this verdict is not "there are no clocked bots". It is: **at 1-second
timestamps with 63% zero gaps there is no band left in which to see one.** A scheduler with a
period under a few seconds is invisible *by construction*. The prior study's inter-arrival CV
was not missing anything this instrument could have caught.

### 8.6 (d) Size-vs-impact exponent — **the control passes exactly; the wash reading fails**

The h = 0 control confirms the price identity to four decimals: with relative size
`x = log(|q| / v_tok_before)` the within-coin exponent is **1.0003** in every arm. Immediate
impact is mechanical and carries zero information, exactly as expected on a CFMM.

| h (trades ahead) | γ ALL | serial | solo | dumped | not dumped |
|---|---:|---:|---:|---:|---:|
| 0 | 1.0003 | 1.0001 | 1.0004 | 1.0000 | 1.0008 |
| 10 | 0.279 | 0.127 | 0.413 | 0.159 | 0.573 |
| 25 | 0.215 | 0.065 | 0.347 | 0.091 | 0.516 |

Bootstrap B = 2,000 **clustered by coin**. Two estimator corrections were needed and both
matter: pooled OLS gave serial 0.172 vs solo 0.823, and coin-fixed-effects gives 0.127 vs
0.413 — **roughly half the pooled gap was Simpson's paradox**; and raw `log|q|` instead of
relative size gives 0.973 within / 0.926 pooled, the difference being curve depth.

**γ does not mean what the brief hoped, and three diagnostics say so:**

1. **Order-flow autocorrelation is positive and equal across arms** (lag-1 ACF of signed
   relative size: serial 0.357, solo 0.352, dumped 0.348). Wash trading — a buy immediately
   undone by a matching sell — requires a *negative* ACF. It is not there.
2. **Signed follow-through is positive and equal** (serial 0.0268, solo 0.0276).
3. **The noise scale differs, and that is what γ reads.** Median |R| at h = 10 is 0.110 for
   serial vs 0.0736 for solo — 1.5× more volatile per ten trades — while the regressor spread
   is identical (sd 1.860 vs 1.859). A log–log exponent attenuates toward zero exactly when
   noise in the response is large relative to own impact.

The decisive check is the attenuation-free signed coefficient β from `R = β·f`, which recovers
β = 1.81 ≈ 2 at h = 0 as the identity requires. At h = 10 the serial−solo difference is
**+0.235 [−0.209, 0.673], p = 0.348**; snipers p = 0.805; dumped p = 0.382. Volatility-
stratified γ shrinks the serial−solo gap from −0.286 to −0.111, i.e. **~61% of it is
volatility** — the same `vol-control` lesson from `RESULT_crime_signatures.md` §5.5, arriving
in a new place.

And a fourth point that corrects the brief's own premise: **the square-root law is the wrong
prior on a bonding curve.** Mechanical impact here is *linear* in relative size (γ = 1.0003 at
h = 0, by construction), so there is no organic γ ≈ 0.5 regime anywhere in this data to
compare a manipulated one against. The square-root law is an empirical regularity of
order-driven markets with hidden liquidity; a CFMM has no hidden liquidity.

**VERDICT: γ survives statistically and is uninformative as a crime discriminator.** Impact
*amplifies* with horizon in every arm (β(10)/β(0) = 1.7–2.2, β(25)/β(0) = 2.0–3.0) — momentum,
the opposite of the reversion a wash trade would leave. Stated in the honest direction: this
is "no difference detected", not "shown equal" — the β confidence intervals are wide.

### 8.2 Multiplicity

16 pre-registered confirmatory cells: (a) 2 lengths × {real, shuffled}; (b) 3 contrasts;
(c) 3 contrasts on the detrended primary; (d) 3 contrasts × 2 horizons. Everything else — h=0
controls, pooled/absolute variants, the naive LS variant, signed β, volatility stratification,
repetition stratification — is declared descriptive and excluded.

**Benjamini–Yekutieli at q = 0.10, c(16) = 3.3807: 14 of 16 survive.** Both failures are in
(c). The three-day tape gives the same 14/16 with the same two failures.

**BY survival is not the verdict, and this is the section's most reusable line.** Three of the
fourteen survivors are demoted by their own post-hoc controls: `b.serial_vs_solo` dies under
repetition stratification, `c.high_vs_low_snipers` rests on a band-edge artifact, and all six
`d` cells are volatility restatements. **A multiplicity correction protects against luck; it
does not protect against measuring the wrong thing fourteen times.**

---

## 9. Trials counted

| family | cells |
|---|---:|
| label ladder rungs (descriptive, no test) | 14 |
| predictive arms × 1 label × 1 split | 5 |
| baselines | 3 |
| rotation nulls (arms with history features) | 3 |
| sniper-reuse: 1 statistic × 1 null | 1 |
| screen gates × 2 outcomes | 12 |
| four cheap discriminators, pre-registered confirmatory cells (§8) | 16 |
| **substantive configurations** | **~40** |

The 16 discriminator cells carry their own **BY-FDR at q = 0.10** (14 of 16 survive, §8.2).
The rest of this document is not FDR-corrected as a family, because it is not a family of
comparable tests: it is one label ladder, one predictive comparison with two nulls, and one
screen. Where a claim rests on a p-value it is a permutation p against a structure-preserving
null, and those are reported individually with their effect sizes.

PROGRAM.md §3.9's rule — past ~7 configurations an in-sample Sharpe of 1 is an out-of-sample
zero — argues for the nulls, and the nulls are the load-bearing part of §5 and §6.2. The two
claims this document rests on are each backed by a null the naive version fails: sniper reuse
against a **degree-preserving** null (51.2×, where the *inflated* self-inclusion version reads
2.7× higher and would have been wrong), and operator history against a **stratified
permutation** null (2.28× observed vs 1.49× null mean).

**No fixed-percentage drawdown claim is made without its mechanical companion.** The `collapse`
label in §7 is a fixed −90%, so per `RESULT_crime_signatures.md` §5.5 it must be treated as
volatility-suspect: it is used only as an *independent check* on a screen built from other
quantities, never as the thing being optimised, and the primary label `is_rip` is mechanical
(who moved what supply) rather than a drawdown.

---

## 10. Method notes: five traps, paid for

Each produced a wrong number first and would have been invisible in the output.

**1. A CTE referenced twice materialises 10M rows of nested lists — 25 GB of spill per day,
before a single output row.** The ledger explode is a per-row operation: `account_index` is
unique within each of `pre` and `post`, so netting is a join of two short lists *inside* a
row. The second attempt kept one scan but netted with `GROUP BY block_slot, tx_index, owner,
mint` — a near-unique-key aggregate over 28M rows/day that reduces nothing and still spilled
4 GB. Row-local netting streams with an empty spill directory.

**2. HUGEINT silently becomes DOUBLE on parquet.** Parquet has no 128-bit integer. Every
value here is bounded by the 1e15 supply and *happens* to be exactly representable, but a
`sum()` over a coin's 400,000 trades is 4e17 — past 2⁵³ — and the total would quietly stop
being the total. Cast to `BIGINT`. This is the corpus docstring's "cast int, never float" rule
biting in a place the docstring did not name.

**3. The migration transaction poisons the peak price by 15×.** At migration the curve hands
its *entire* balance to the pool and goes to zero, but it stopped *selling* with 206.9M tokens
still in the account. Reading the peak at `bal = 0` gives `v_tok = 7.3e13` and a nonsense
6,040 SOL — identical for every graduated coin, which is what made it visible. `min_bal_live`
excludes it and the median lands on 410.9 SOL against 411 predicted.

**4. Birth order is not information order, and the leak points at the hypothesis.** The
obvious history frame — `PARTITION BY deployer ORDER BY birth_time ROWS UNBOUNDED PRECEDING
AND 1 PRECEDING` — looks strictly causal and is not: a deployer's previous coin is born an
hour earlier and rips five days *later*, and the frame credits this coin with `prior_rips = 1`
for a rug that had not happened. Fixed by aggregating over **events** whose own timestamp
precedes the birth. Two features (`prior_mean_ins_share`, `prior_best_mcap`) were **deleted
rather than fixed** because they are maxima over a prior coin's whole life and have no
leak-free form at this cost.

**5. A "custody transfer" that is really a trade.** The first transfer detector asked only for
two equal-and-opposite pump legs with the curve absent, and returned **18,195,092** transfers
in four days — because that is exactly the shape of a PumpSwap trade after migration, where
the pool takes one side and the pool is not the curve. Requiring the transaction to have moved
**no WSOL at all** drops it to 904,574 in ten days. A payment is not a custody link.

**And one that is not a trap but a fact worth carrying forward:** the deployer is a birth-slot
buyer of its own coin, so any statistic over "the wallets that bought at birth" is
self-inflated for the operator unless the deployer is removed. It was worth 2.7× here.

---

## 11. Controls

`tests/test_operator_crime.py`, six tests, all green. PROGRAM.md §3.12 — *both controls,
always* — is the rule they exist for, because the SVN study's z-score bug passed its
zero-coordination control perfectly (an estimator that detects nothing always does) and only
the planted-recovery test caught it.

| test | world | asserts |
|---|---|---|
| `test_independent_wallets_yield_no_validated_edges` | no shared crews | observed Jaccard **inside** the curveball p95 |
| `test_planted_clusters_are_recovered` | each deployer reuses half its crew | observed **above** p95, and > 3× null mean |
| `test_curveball_preserves_both_degrees` | — | every coin's sniper count and every wallet's coin count unchanged |
| `test_curveball_actually_randomises` | — | the null moves (a no-op is degree-preserving too) |
| `test_the_verdict_flips_with_the_world` (×2) | both | one statistic, two worlds, **opposite** verdicts |

The last one is the important one: if that parametrisation ever agrees on both rows, the
instrument is a constant and every headline built on it is meaningless.

---

## 12. What this does NOT establish

1. **No funding lineage.** The corpus has no SOL transfers. Every "operator" here is a
   deployer wallet or a sniper wallet, never a funding-tree entity. Sybil wallets are free, so
   53,335 distinct deployers is an **upper bound** on the number of operators.
2. **16.5% of coins have no identifiable deployer** — no dev buy, so no wallet appears in the
   create at all. They are not excluded from the label ladder but they are absent from every
   deployer-keyed analysis.
3. **No entity resolution succeeded.** §6.3 is a negative. Nothing downstream clusters wallets,
   and the §5 test is at deployer-wallet level with that stated as a limitation, not solved.
   **Spectral co-clustering / SVD over the wallet × coin incidence was not run**, and the
   reason is §6.3 rather than time: the only linkage relation this corpus offers already
   collapses 45% of wallets into one component through an infrastructure hub, so a spectral
   method would have been fitted on a graph known to be over-merged. `RESULT_svn_cotrading.md`
   is explicit that the null, not the clustering algorithm, is where this work lives or dies —
   the honest move was to report the linkage failure rather than to layer a nicer algorithm on
   top of it.
4. **Ten days is ten days**, and coins born on day 9 are heavily right-censored. The temporal
   split mitigates the comparison but not the base rates: a coin born on the last day has
   hours, not days, in which to rip.
5. **`is_rip` is a definition, not a court verdict.** It says a set of birth-slot wallets
   disposed of a material position before a collapse. It does not establish intent, and some
   fraction of these are honest early buyers taking profit into a coin that was dying anyway.
6. **The screen is evaluated on the same ten days it was designed on.** The gates were fixed
   from the mechanism before the numbers were read, and the split is temporal — but the *set*
   of gates was chosen by a person who had already seen §4. Forward evaluation is the only
   thing that settles it.
7. **31% of coins are priced approximately** (§2.2).
8. **This is not an exit signal and not an entry edge** (§0).
9. **The discriminators ran on the serial/solo cohort, not the whole corpus.** §8's tape is
   17,234 coins with ≥100 curve trades, selected as top-60-deployer coins plus a matched
   single-launch sample. It is the right sample for a labelled same-vs-different-operator test
   and the wrong one for a population statement.
10. **"No scheduler detected" is bounded by the clock, not by the chain.** §8.5 can only
    speak about periods above a few seconds. A sub-second bot is invisible in this corpus at
    any sample size; catching one needs the transaction's own timestamp resolution, which
    means a different pull.

---

## 13. What to do with this

1. **Ship the CLEAN screen as birth-time triage for the $40 bets**, at the stated operating
   point: 4.8% coverage, 99.96% clean, 2 of 771 collapses admitted. It needs one slot of chain
   data per coin and no history at all.
2. **Stop treating a clean deployer record as reassurance.** It reads 1.71× *worse* than base.
   If a history gate is used at all, it should be "this deployer has a *long* clean record",
   which the 610 deployers with ≥50 coins make measurable and which this study did not test.
3. **Re-pull the corpus with signers and fee payers.** Two of this study's three dead ends
   (fee-payer fingerprints, failure-rate fingerprints) are limitations of the *export*, not of
   the chain, and the pull is the same bytes.
4. **The next real experiment is the crew, not the creator.** §5.4 and §6.2 both point there:
   sniper crews are reused 51× above a degree-preserving null and their history is the only
   history that adds anything. A crew-keyed panel — cluster birth-slot wallets by co-appearance
   across coins, *validated on held-out coins rather than on the co-appearance that built it* —
   is the follow-up with the most support behind it.
5. **Carry `verify` forward.** A price identity that reproduces an independent vendor's number
   to 0.12% is reusable by every future study on this corpus, and it costs nothing.
