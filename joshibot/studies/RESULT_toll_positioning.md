# RESULT: toll positioning — the toll surface, sized against this desk

2026-08-15. Instrument: `studies/toll_positioning.py`. Reproduce:
`uv run --group research python studies/toll_positioning.py all` (sections:
`decay tiers escrow ladder joint rank nulls`). First study in this repo written against the
`research` dependency group — decay CIs are Newey–West via statsmodels, ladder inference is
hour-clustered OLS, no hand-rolled statistics anywhere in it.

Data, all already on disk or keyless: GeckoTerminal daily/hourly OHLCV for the canonical
DREGG/SOL pool (cached to `studies/data/toll_positioning/`), the operator's complete
266-claim ledger (`.cache/position_history/ledger.json` + raw txs, built by
`studies/position_history.py`), the minute-bar dataset
`studies/data/mean_reversion/gt_ohlcv.jsonl`, and the edge_creation transaction cache
(`/tmp/joshibot-edge-creation/`). Nothing signed, nothing sent, $0 spent.

**The thesis under test** (operator's, and the program's after eight null/negative strategy
studies): *you get paid for being positioned where flow crosses, never for predicting where
it goes.* This study takes it seriously, prices every toll it can find, and then attacks
the part the thesis is quiet about: tolls are rents, and rents decay.

---

## 0. What this found, in nine lines

1. **The toll thesis survives, with one word added: tolls on flow pay, and the flow is
   dying at a measurable rate.** DREGG volume: half-life **12.1 d** [95% CI 9.1–18.4] on
   the full 49-day daily series; the fee-claim series independently gives **17.0 d**. But
   the last two weeks have *flattened*: OOS, a random-walk null (0.377 log-MAE) beats the
   exponential (0.449). The stream's own history cannot distinguish "dead in a month" from
   "plateau at ~$37k/day" — **NPV of the fee stream: $4.8k–$31k**, and that width is a
   finding, not sloppiness.
2. **CORRECTION to PROGRAM.md §0 / RESULT_circuit_model.md §9.3: the 0.81–1.19% realized
   creator take does not replicate.** Dividing the operator's actual 154 DREGG-vault
   claims by the pool's actual daily volume, week by week over the whole life, gives
   **0.30–0.85% (recent 3-week mean 0.68%)** — and against the published ladder's own
   volume-weighted prediction the claims track at **0.93× mean** (range 0.47–1.42, n=7
   weeks). The "anomaly" was a denominator artifact: an income *estimate* divided by a
   single-day volume snapshot. The ladder is *confirmed*, not exceeded, and the income
   model should be read at ~0.6–0.8% of volume.
3. **The unrun benchmark is now run, and the ladder wins.** Per-fill, against routing the
   same clip at the same minute through the two-leg SOL substitute (2×1.44% + impact):
   the desk's one-sided DLMM sell ladders show an advantage of **+1.96% (hour-clustered
   SE 0.59%, t=3.31, n=221 fills, 32 clusters)** at the conservative t+60s price, +2.71%
   same-bar; **+1.36% after operator fee-recapture adjustment**. The fills landed *at*
   the market cross rate (premium −0.15% to −0.56% weighted) — the entire edge is the
   avoided toll. This settles `RESULT_lp_history` next-experiment #1 /
   `RESULT_edge_creation` what-to-do #4: **the desk sells well; what lost money was
   holding the inventory it was selling** (−$595 vs HODL stands untouched).
4. **The four DREGG levers were modelled jointly for the first time**, and the coupling
   has a sign nobody had written down: at FDV $305k — **1.8% above the $300k tier
   boundary** — the operator's total position is locally **short its own token's price**.
   Crossing under the boundary raises the take 0.60%→0.95% on all volume (~$129/day,
   ~$2.3k over the fitted remaining life) against ~$318 of escrow mark-to-market. Do not
   spend to cause it; do not spend to defend it — defending the boundary is paying to
   lower your own take rate.
5. **The volume lever is the largest unpriced asset on the desk.** The community-activity
   null (~1.86× volume, no durable price effect) is, for a fee earner, a *positive*
   result: ≈ **$250/day gross** at current volume and take. It is +EV iff the activity
   costs less than that. Nobody has priced the labour; the multiplier was measured once.
6. **Joint income statement, next 30 days: $4.8k–$9.2k against $4.1k obligations
   (1.16×–2.25×)** — creator fees $4.0k–$8.4k (decay-integrated vs plateau), vesting
   sales $0.8k, volume lever $0–7.6k gross, LP yield **$0** (η < VR everywhere measured).
7. **The escrow is a stock, not an income substitute**: 59.0M DREGG = **$18.0k** vesting
   at $368/14d (~19% of obligations), 23 months to full vest. One tranche = 1.42% of the
   pool's SOL side — fits the 2% envelope cap in a single clip.
8. **Every reachable toll is denominated in one community's attention.** The fee stream,
   the escrow, the ladder counterflow and the volume multiplier discharge together —
   38% of lifetime fee income (the 287 SOL social stream) *already* went to zero in
   August (142.5 → 141.8 → 2.9 SOL/mo). That is what toll death looks like, observed
   in the desk's own books.
9. **Ranked, with arithmetic, at this desk's size** (§1): incumbent creator fee ≫ volume
   lever ≫ vesting-exit ladder > token-token arb tolls (EV straddles 0) > new-launch
   lottery (~0) > token/SOL LP (negative), Jupiter maker (negative), gas-sponsorship
   terminal (real business, not reachable — the moat is distribution, not capital),
   validator/MEV (fantasy at 1 SOL liquid).

---

## 1. The toll surface, enumerated and priced

EV/mo in USD at today's flow, take and price. "Capital" is marginal capital required now.

| # | toll | what flow crosses it | you capture | capital | EV/mo at this desk | dies to |
|---|---|---|---|---|---|---|
| 1 | **DREGG creator fee** (incumbent) | canonical-pool volume, $36.9k/d trailing-7d | 0.60–0.95% ladder, measured 0.93× face | 0 (sunk) | **$4.0k–$8.4k**, decaying; NPV $4.8k–$31k | volume decay (t½ 12–17 d); schedule change; community death |
| 2 | **Volume lever** (community → fee channel) | the same volume, multiplied ~1.86× | take × Δvolume | 0; unpriced labour | **≤ $7.6k gross** | fatigue; multiplier measured once |
| 3 | **Vesting-exit ladder** (one-sided DLMM above market) | the desk's own forced selling + arb counterflow | +1.4–2.0% vs routing (measured, §4) | 0.057 SOL rent, refunded | $0.8k of flow × edge ≈ **$11 + execution quality on all rotation** | no counterflow; DREGG price; cluster death |
| 4 | **Token-token arb tolls** (5–6% DLMM on cycles the desk closes) | 84.5% arbitrage cycles, 15.3% router legs | η = 0.59–1.08 → **EV straddles 0**; realized −$595 vs HODL on 10 positions | $100–800/pool | ~0 ± large; duty cycle is the only lever | **one Jupiter routing deploy** (64% single-hop share is the rent); range exit |
| 5 | **New-launch creator fees** | bonding-curve + post-grad volume of a new coin | 0.3% curve, ladder after | ~0.03 SOL/launch | **≈ 0 per anonymous launch**: 2.6% of 913 censused launches even completed the curve, median curve life 6 min; the 757 SOL came from the community, not the mechanic | launch fatigue burns the community powering #1–3 |
| 6 | **Token/SOL LP yield** | pool volume | η = 0.055–0.235 vs VR 0.27–0.75 | any | **negative, −EV 1.9–9.2×** (RESULT_circuit_theory §4.5) | already refuted |
| 7 | **Jupiter resting orders** (maker) | taker flow via one keeper | −10 bps, no rebate, option written free | escrowed | **negative** (RESULT_jupiter_programs) | already refuted |
| 8 | **Gas sponsorship / terminal** (the FOMO toll) | 22.5% of distinct traders on our own pools ride it | ~1% app fee vs ~$0.0008/tx gas — ~99% gross margin | capital ≈ 0; **moat = distribution** | from our 4 pools alone FOMO books ≈ $40–50/day (302 sponsored swaps/30h × 0.228 SOL median × ~1%) | app churn; venue integration. **Not reachable as an app; the reachable analog IS toll #2** — the community is distribution the desk already owns |
| 9 | **Referral/integrator rails** | community flow routed through an operator interface | integrator bps | ~0 | small: 50 bps on even half of DREGG volume ≈ $2.8k/mo *if* the community adopts an operator front-end — untested, and cannibalizes nothing | same community risk; venue terms |
| 10 | **Validator / MEV infra** | everything | tips/priority | $100k+ | **fantasy at 1 SOL liquid** — said plainly | n/a |

Notes on #8, since the brief asked "what is that worth": FOMO's relayer
(`AgmLJBMD…`) pays ~10,420 lamports/tx (~$0.0008) and pre-simulates to a 0% failure rate;
its fee wallet takes USDC per swap. The toll is real and large *in aggregate across all of
Solana*, and it is a **software-distribution business** — capital is not the barrier and
never was. At this desk's scale the reachable version of the same toll is #2: the operator
already owns distribution over one community; FOMO's business is owning distribution over
everyone else's.

---

## 2. Decay — the thing the thesis is quiet about, measured

Daily USD volume of the canonical pool, full life (49 bars, 2026-06-27 → 08-14, peak
$859,515/d, trailing-7d $36,884/d):

| model | full-sample fit (HAC, maxlags=7) | OOS log-MAE (train ≤ 08-01, n=13 test) |
|---|---|---|
| exponential | slope −0.0571/day (SE 0.0099) → **t½ 12.1 d [9.1–18.4]** | 0.449 |
| power-law | exponent **−0.917** (SE 0.101), volume ~ 1/t | 0.689 |
| no-decay null (train mean) | — | 1.468 |
| **random-walk null (last obs)** | — | **0.377 ← wins** |

The fee series agrees independently: weekly DREGG-vault claims 190.3 → 40.0 → 87.7 → 48.1
→ 59.5 → 22.9 SOL, exponential slope −0.0408/day → **t½ 17.0 d**.

Read all three honestly: the collapse from launch is real and fast, *and* the most recent
two weeks are flat enough that carrying the last value forward beats every fitted decay
out of sample. A 1/t power-law (the attention-decay shape; next halving at ~age 98 d) sits
between. So the fee stream's NPV is **$4.8k (exponential) to $31.2k (power-law, 1-year
horizon)**, and days until the daily rate falls under obligations ($135/day) spans
**13 days (exp) to 57 (power-law) to never (RW plateau)**. The instrument cannot separate
these futures — which is precisely why §6's portfolio must be built as if the low band
binds.

**The already-dead stream is the strongest decay evidence in the file.** Lifetime fee
income was two streams: the DREGG vault (467.2 SOL, volume-linked, alive) and the social
PDA (287.2 SOL — 38% of lifetime income), which went **142.5 → 141.8 → 2.9 SOL/month** and
is dead. One of the desk's two tolls has already completed the full lifecycle this study
is trying to price.

---

## 3. The take rate — a correction to PROGRAM.md §0

PROGRAM.md §0 and RESULT_circuit_model.md §9.3 carry: *realized creator take 0.81–1.19%,
statistically excluding the 0.60% tier; the income model is therefore conservative by
1.5–2×.* That number was an income **estimate** ($213–313/day) divided by a **single-day**
all-pools volume snapshot ($26,300).

The better instrument existed on disk: 154 DREGG-vault claims with block times, and the
pool's own daily volume series. Weekly, over the whole life:

| week | volume $ | claims $ | measured take | ladder-predicted take | meas/pred | mean FDV |
|---|---|---|---|---|---|---|
| 0 | 3,615,435 | 14,231 | 0.39% | 0.61% | 0.65 | $557k |
| 1 | 1,026,538 | 3,041 | 0.30% | 0.63% | 0.47 | $367k |
| 2 | 994,119 | 5,807 | 0.58% | 0.65% | 0.89 | $518k |
| 3 | 725,666 | 4,680 | 0.64% | 0.56% | 1.16 | $776k |
| 4 | 736,192 | 4,118 | 0.56% | 0.60% | 0.93 | $610k |
| 5 | 233,114 | 1,981 | 0.85% | 0.60% | 1.42 | $408k |
| 6 | 258,187 | 1,602 | 0.62% | 0.64% | 0.97 | $341k |

(Ladder prediction = volume-weighted published tier rate over hourly FDV where hourly bars
exist, daily close before. Threshold: full 7-day weeks only; partial buckets dropped as
censored, not zeroed.)

**Measured/predicted: mean 0.93, range 0.47–1.42.** The operator's own claim history
*tracks the published inverse-FDV ladder*. The 0.81–1.19% figure does not replicate as a
lifetime take; the trailing-14d take is 0.79% only because FDV now sits near the $300k
boundary where the ladder itself predicts 0.60–0.95% mixture. Consequences:

- PROGRAM.md §0's "real coverage runs ~1.5–2× the tier-table figures" should be retired;
  coverage runs ≈ 0.93× the tier table.
- The open question "why does the realized rate exceed the published tier" dissolves —
  it doesn't exceed it.
- The **tier kink at $300k FDV is real at face value** (with the 0.47–1.42 weekly noise
  band), which is what gives §5's short-own-price result its teeth.

---

## 4. The ladder benchmark — the deciding measurement, finally run

`RESULT_lp_history` ("next experiment #1") and `RESULT_edge_creation` ("the only one that
changes the verdict") both asked: per fill, did the one-sided DLMM ladders beat selling
the same size at the same time at market? Data: full cached transaction history of
weave/DREGG A (`GxnCwxTi…`, 5% tier) and DREGG/nosis (`FNxnyS3h…`, 5%), minute-bar closes
from the mean_reversion dataset, fills = swap txs with two-mint opposite-sign vault deltas
(liquidity ops excluded by log signature; threshold: fills > 30 min from a price bar
dropped — zero were).

| pool | fills | flow | premium vs market cross rate (wtd) | advantage vs routing, same-bar | advantage, t+60s (conservative) |
|---|---|---|---|---|---|
| weave/DREGG A | 189 over 46.3 h | 71.6M weave → 17.8M DREGG, 87.4 SOL | −0.15% | +2.71% (SE 1.09%, 30 clusters, t=2.48) | **+1.80% (SE 0.68%, t=2.66)** |
| DREGG/nosis | 32 over 1.9 h | 1.44M DREGG → 1.54M nosis, 6.5 SOL | −0.56% | +2.76% (SE 1.35%, 3 clusters, t=2.05) | **+2.90% (SE 0.57%, t=5.06)** |
| **pooled** | **221, 32 hour-clusters** | | | +2.71% (SE 0.95%, t=2.86) | **+1.96% (SE 0.59%, t=3.31)** |

Routing counterfactual = A→SOL→B through the PumpSwap legs: 2×1.44% decoded fee + B/(Y+B)
impact per leg at each fill's clip size (median clip 0.243 / 0.049 SOL). Operator
adjustment: the routed alternative's DREGG leg pays ~0.6% creator fee back to this
operator, so the operator-specific advantage is **≈ +1.36%**.

The decomposition is the finding: the fills landed essentially *at* the market cross rate
(−0.15%/−0.56% weighted; −1.73% median at t+60s on weave — fills co-move with price inside
the bar, which is why the t+60s column is the honest one). **The ladder's whole edge is
that it collects the toll the router would have charged.** "Be the thing that gets
crossed" — RESULT_jupiter_programs' closing instinct — is hereby measured at +1.4–2.0%
per unit of flow, on the one venue where the desk is the junction.

What this does **not** overturn: LP−HODL is still −$595 across the 10 closed positions.
Both facts are true simultaneously and they decompose the token-token programme exactly:
**the selling earned its toll; the holding lost the freight.** A ladder on inventory you
*must* sell (vesting tranches, rotation) is measured +EV; a ladder as a way to *hold*
inventory is the measured −EV.

Caveats that travel with the table: GT minute closes, not on-chain mid — same-bar premium
is biased up for a sell filled on an uptick (hence t+60s); counterfactual impact uses
today's pool depths, not fill-time depths; the two pools share hours, so the pooled
clustering by hour is the right unit; n=2 pools.

---

## 5. The joint DREGG model — four levers, one position

State (2026-08-15): price $0.0003054, FDV $305,385, trailing-7d volume $36,884/day, fee
$277/day, take 0.79% trailing-14d, escrow 59.0M DREGG ($18.0k), decay slope −0.0571/day.

**Lever 1 — volume.** d(fee)/d(volume) = take, direction-free. At the measured ~1.86×
community-activity multiplier: **+$250/day gross** ($7.6k/mo). PROGRAM.md filed 1.86× as a
*price* null; for a fee earner the null IS the payoff — the desk can drive current through
its own toll without needing the price to move. +EV iff the activity costs < $250/day.
Durability unmeasured (one observation).

**Lever 2 — price, and the kink.** Same-day dlog(volume)~dlog(price): β = +0.29 (HAC SE
0.26, rotation-null p = 0.396) — no measurable elasticity; volume does not reliably follow
price day-to-day. The kink: FDV is **1.8% above $300k**. Crossing down re-rates *all*
volume 0.60%→0.95% = +$129/day ≈ +$2.3k over the fitted remaining life, against −$318 of
escrow mark-to-market to get there. **Net ≈ +$1.9k: the operator's total position is
locally short its own price.** With §3 confirming the ladder at 0.93× face, this is
carried as real. Policy that follows: never spend to defend the $300k boundary (defending
it pays to lower your own take), and treat organic dips under it as fee-accretive, not as
emergencies. Symmetrically: the *next* kink up ($1M FDV, 0.60%→0.35%) means a 3.3× price
rally cuts the take rate 42% — the fee business is structurally a bear-market business.

**Lever 3 — vesting exits.** $368/14d forced flow. Exit-cost table per tranche:
market-sell as an outsider 2.84% (1.44% + 1.40% single-clip impact); as the operator
2.05% (creator recapture); **DLMM sell ladder: −1.4 to −2.0%, i.e. the exit PAYS** (§4).
One tranche = ρ 1.42% of the pool's SOL side — inside the 2% envelope cap even unsliced.

**Lever 4 — LP.** η = 0.235 vs best VR 0.438 on DREGG/SOL: yield-LP allocation **zero**.
The only LP form with a measured positive is lever 3's ladder — an execution rebate on
flow that had to move anyway.

**Joint income statement, next 30 days (USD):**

| stream | low | high | note |
|---|---|---|---|
| creator fees | 3,971 | 8,409 | low = decay integrated; high = plateau (the RW null that won OOS) |
| vesting sales | 799 | 799 | via ladder, not market-sell |
| volume lever | 0 | 7,601 | gross; unpriced labour |
| LP yield | 0 | 0 | η < VR |
| **total vs $4,100** | **4,770 (1.16×)** | **9,208 (2.25×)** | |

**The coupling, which is the point of modelling jointly:** all four levers load on one
community's attention with ρ ≈ 1 — fee stream, escrow value, ladder counterflow, and the
multiplier are one position, not four. (Cross-token diversification inside the cluster is
real but weak: measured ρ 0.11–0.24.) The only lever that *reduces* the concentration is
selling vested DREGG for SOL on schedule — which is also the lever with the measured
execution edge. The joint model's one-sentence output: **harvest the fee stream, sell the
vesting through your own ladder, spend nothing defending price levels, and treat the
volume lever as the only growth asset — priced against the labour it actually costs.**

---

## 6. Breaking the thesis — what kills each toll, and what survives

The strongest counter-argument, quantified where the data allows:

- **Rents get routed around.** The token-token rent is 64% single-hop flow paying 2.67×
  the best route (RESULT_circuit_theory §5.3) — one Jupiter deploy removes it as a step
  function, not an elasticity. The creator fee has the same shape one level up: it exists
  at pump.fun's pleasure, and the schedule has already changed at least once (Marino
  records the ladder; the social-fee stream's death may itself have been a schedule
  event).
- **Rents decay with their flow.** Volume t½ 12.1 d [9.1–18.4] from launch; the honest
  wide read of the recent flattening still brackets the stream's NPV at $4.8k–$31k. The
  desk has already watched one of its two fee streams (38% of lifetime income) go to
  zero inside six weeks.
- **The decay is survivable in one direction only.** DREGG's own death shape is BLEED,
  not CLIFF (RESULT_flow_signals: −79% without ever losing 17.6% in an hour; crossed
  −70% at bar 622/999) — the one death mode that is *exitable at leisure*. The vesting
  schedule (23 months) is long against a 12–17 day fee half-life: **most of the escrow's
  vesting life will occur after the fee stream, at fitted decay, has gone quiet.** The
  escrow's value therefore depends almost entirely on whether the community re-excites
  volume, not on the current stream.
- **What a surviving toll portfolio looks like, given all that:** (i) fees converted to
  SOL on schedule — discharge protection is structural, already PROGRAM.md policy;
  (ii) exits always laddered — the one toll that is +EV *because* it rides flow the desk
  must generate anyway, and the only lever that de-correlates the stack; (iii) zero
  capital in yield-LP and zero in maker rails — both measured negative; (iv) token-token
  pools sized as experiments only ($100–200, the TVL floor) until the duty-cycle rule
  exists, because their EV straddles zero *before* counting the router-update cliff;
  (v) the renewable asset is not any toll but **the community + the launch capability**
  — an anonymous launch is worth ~0 (2.6% curve-completion, n=913 census), a
  community-attached launch produced 757 SOL once; toll #1 is the *depreciating output*
  of that asset, and the portfolio survives its own obsolescence only by occasionally
  building a new junction while the old one still pays. That cadence question — does a
  new launch cannibalize or renew — is unmeasured and is the single most valuable open
  experiment this study leaves.

---

## 7. Falsifiable claims

| # | claim | falsified by | status |
|---|---|---|---|
| 1 | DREGG volume decays with t½ ~12 d (exp) / exponent ~−0.92 (power-law) | 30 more days of daily bars refitting far outside the CIs | measured, CI stated |
| 2 | The recent regime is plateau-consistent (RW beats decay OOS) | the next 2 weeks resuming the fitted decay | measured on 13 OOS days |
| 3 | Realized take tracks the published ladder at ~0.93× | future weekly claims/volume departing the ladder prediction by >2× sustained | measured, 7 weeks |
| 4 | The 0.81–1.19% take of PROGRAM.md §0 is a denominator artifact | reproducing 0.81–1.19% from claims and daily volume over any multi-week window | correction; the series is printed |
| 5 | Ladder exits beat routing by +1.4–2.0% per unit flow | re-running `ladder` on new fills with on-chain mid prices and finding ≤0 | measured, t=3.31, n=221, 2 pools |
| 6 | The joint position is locally short its own price just above $300k FDV | pump.fun not applying the 0.95% tier below $300k (watch claim/volume for the step next crossing) | derived from #3; free natural experiment pending |
| 7 | The volume lever is worth ≤ $250/day gross at 1.86× | a second activity episode with a different multiplier; or take/volume shifting | single measurement, flagged |
| 8 | An anonymous launch has ~zero creator-fee EV | a cohort of anonymous launches with measured curve volume paying > launch cost | census-based bound |

---

## 8. What this changes upstream

- **PROGRAM.md §0**: the "measured correction" paragraph (realized take 0.81–1.19%,
  excluding the 0.60% tier, income model conservative by 1.5–2×) is superseded by §3.
  Annotated in place, pointing here.
- **RESULT_circuit_model.md §9.3**: same correction applies; the creator-fee estimator's
  method (income/volume) was right, its inputs (estimate ÷ snapshot) were not.
- **RESULT_edge_creation.md "what to do" #4 and RESULT_lp_history "next experiment #1"**
  are done (§4). The verdict they said this measurement would decide: the ladder
  programme is good **as execution**, bad **as inventory** — run ladders on flow you must
  move, never as a reason to hold.
- **RESULT_jupiter_programs.md**'s closing instinct ("the version of maker-side that
  pays is the LP position") now has a number: +1.4–2.0% per unit flow.
- The eight-study null streak stands: nothing here found a prediction edge, and the one
  new positive (the ladder) is a toll, which is the thesis.

## 9. What to do, in cost order

1. **Route every planned exit — vesting tranches first — through a one-sided DLMM ladder
   above market** instead of market-selling or resting Jupiter orders. Measured
   +1.4–2.0% vs routing, and it converts the desk's largest forced flow into toll flow.
   Next tranche: 2026-08-22.
2. **Never defend $300k FDV.** Sitting 1.8% above the boundary, defence spends escrow
   value to hold the take rate at 0.60% when 0.95% is on the other side. (§5, lever 2.)
3. **Price the volume lever.** One honest week of logging hours/dollars spent on
   community activity against the fee delta decides whether the desk's largest gross
   lever ($7.6k/mo) is real net income or an unpaid job. Free.
4. **Watch the next $300k crossing's claim/volume ratio** for the 0.60→0.95 step (claim
   #6) — a free natural experiment that pins the kink the joint model leans on.
5. **Re-run `decay` weekly** (one command, cached fetches). The NPV band [$4.8k, $31k]
   is the desk's solvency question; two more weeks of bars will collapse most of it.
6. **Hold token-token pools at experiment size** until the duty-cycle instrumentation
   exists (RESULT_edge_creation #2); their EV straddles zero before the router-update
   cliff is priced.

---

*Nulls and trials: `toll_positioning.py nulls` prints the register — 6 enumerated
specifications, nothing run and discarded; decay tested against constant AND random-walk
nulls OOS; take tested against the ladder's own prediction; elasticity against a 2,000-
shift rotation null; ladder inference hour-clustered with a same-bar/t+60s robustness
pair. A null is a result; two of this study's four headline numbers are corrections that
made an upstream edge smaller.*
