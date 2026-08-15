# Copy-trading and app-mediated flow on the cluster pools

**Reproduce:** `python3 studies/copytrading.py [--bq-dir DIR]` · code in `studies/copytrading.py`
**Data:** 2,937 swaps of live tape (2026-08-12 21:25 → 08-14 03:22 UTC, 30.0 h) and 8,385 swaps of
BigQuery replication (full UTC day 2026-08-13), both on the operator's own pools. The two overlap on
791 swaps and agree on counterparty **791/791** and side **791/791**.
**Spend:** $4.43 of BigQuery — $3.02 for reserves + signers + `index` (531.1 GB), $1.41 for trader
identity (247.6 GB). Both dry-run first, both capped with `--maximum_bytes_billed`.

---

## The answer

**Copy-trading — a leader's trade triggering a follower's trade at a characteristic lag — is NOT
DETECTABLE on the operator's coins, and the detector is strong enough for that to mean something.**
Once the null holds the market's own burstiness fixed, the density of same-direction trades by
*distinct* wallets at short lag is **0.69–1.03× expected**: flat. Not one leader→follower pair
survives family-wise testing at wallet level — the eight tests return p_rot from 0.428 to 0.995, with
nothing even near the boundary. An injected copier that mirrors **20** of a leader's trades is caught
100% of the time; one that mirrors 12 is caught a third of the time; five or fewer is invisible. So
what is ruled out is a *dedicated* follower, and only that.

**App-mediated flow is real, large, and now identified by name.** One fee payer,
`AgmLJBMDCqWynYnQiPCuj9ewsNNsBJXyzoUhD9LJzN51`, pays gas for **22.5%** of every distinct trader that
touched the operator's coins in the live window (13.0% over the full BigQuery day). It is **FOMO
(fomo.family)**, the social trading app that overtook Axiom as Solana's top-volume terminal in
August 2026.

**FOMO's users herd; they do not mirror.** FOMO's own documentation says its copy trading is
*notification plus manual confirmation* — "you decide whether to execute each trade" — so its follow
trades land at human reaction latency, not bot latency. That is a falsifiable prediction and the tape
confirms it: no lag mode, no pair structure, and on the quiet full day FOMO's own users are **less**
synchronised than chance (1 observed cross-wallet pair against 30.5 expected). What does happen is an
**attention herd**: 90 distinct FOMO wallets buying nosis inside 492 seconds.

**So: a herd hazard, not a mirror hazard — and the one vivid instance of it did not survive a
pre-committed test.** §6 is where this study nearly fooled itself, kept in view deliberately.

| Question asked | Answer measured |
|---|---|
| Is there a copy signature? | **No.** Short-lag distinct-wallet density is **0.69–1.03×** the intensity-preserving null |
| Lag distribution? | **No mode exists.** The literature has none either — its copier is a formula |
| Copier penalty? | **0.25%** median mechanical · **0.88%** median realised at 1 slot (**94.5%** worse off) |
| Does it touch the operator's coins? | **Yes as app flow (≥22% of traders); no as copying** |
| What did the null say? | Naive null: **73×**. Correct null: **1.01×**. |

---

## 1. The signature, and why the naive answer is wrong by 73×

A copied trade should leave a mark: after wallet L trades pool P in direction D at slot s, an unusual
density of trades on P in direction D by **distinct** wallets in slots (s, s+Δ]. The unit is the
**slot**, not the second — `block_time` quantises ~2.5 slots into one stamp and would smear exactly
the 0.4–2 s band a bot copier lives in.

Three impostors are excluded by construction rather than judgement. **Atomic/MEV bundles**: lag ≥ 1
slot required, and with BigQuery's `index` we can show **13% of same-slot consecutive pairs are
`tx_index`-adjacent**, i.e. literally bundle-shaped. **One entity across many wallets**: entity
resolution, §3. **Ordinary momentum**: not a filter but the null — and it is the whole ball game.

| null | what it preserves | lag-1 cross-wallet pairs, nosis/SOL buy |
|---|---|---|
| naive — each wallet's *rate*, times uniform | wallet counts only | 1,815 vs 25.0 = **73×** (lag 0: **149×**) |
| PERM — permute wallet labels over observed times | + aggregate intensity | 1,815 vs 1,844 = **0.98×** |
| ROT — circular-shift labels along event order | + each wallet's own burst structure | 1,815 vs 1,790 = **1.01×** |

`studies/RESULT_flow_signals.md` found that an i.i.d. null alone would have shipped a bogus
changepoint alarm on this exact data. It does it again here, and not marginally: the naive null turns
a flat result into a **73-fold headline**. It says only that trading is bursty in wall-clock time.

Against either correct null the correlogram is flat at every short lag, on both datasets:

```
BigQuery full day, obs/ROT ratio by lag (slots)
                    1     2    3-5   6-10   11-25    p_rot at lag 1
  nosis/SOL sell  0.93  0.96   0.98   1.01    1.01          1.000
  nosis/SOL buy   1.01  1.00   0.98   0.96    0.96          0.050
  weave/SOL buy   0.99  0.96   0.89   0.69    0.94          0.677
  weave/SOL sell  1.00  1.03   0.96   0.91    0.91          0.751
```

One cell (nosis buy, lag 1) lands at p_rot = 0.050 — with an effect size of **1.01×**. That is a
p-value with nothing behind it, and it is reported rather than dropped.

**Two significant excesses exist, and neither is copying — which is what makes the flat result
informative.** The **same-slot** bin runs 1.03–1.04× with p_rot = 0.005–0.020 across three of four
pool-sides: that is the atomic/bundle signature, corroborated independently by the 13% of same-slot
consecutive pairs that are `tx_index`-adjacent, and it is excluded by design. And nosis/SOL sell runs
**1.05–1.06× at lags 26–200 slots** (10–80 s), p_rot = 0.005 — a momentum / attention timescale, the
*opposite* of where copying must live. So the detector demonstrably resolves 3–6% effects on this
data. It finds nothing at the lags where copying has to be.

## 2. The lag distribution: there isn't one

There is no leader-follower lag mode to report, and that is worth stating in context: the field does
not have one either. `memecoin-copytrading-manipulative-bots-2601.08641` contains **no copier
detector, no observed copier, and no lag distribution at all** — its "copier" is a closed-form
construct (Lemma 1 / Theorem 2) evaluated analytically on the leader's trade sequence. The only
latency figures in circulation are vendor marketing, and they contradict each other by 4× (OdinBot's
site claims 65% same-block; Decrypt, quoting the same vendor, reports 15%). **Our tape is strictly
better evidence than any of it**, and what it says is that on these pools the distribution is flat.

## 3. Entity resolution is circular here, and that is itself a finding

PROGRAM.md §3 binds us to group wallets into entities before splitting. The natural on-chain rule —
wallets that repeatedly land in the same slot on the same pool are one operator (2601.08641 Alg. 1's
logic: no public mempool, ~400 ms blocks) — is a **temporal** rule. Feeding it into a **temporal**
test is circular, and it fails loudly:

| nosis/SOL buy, Δ=12 slots | max pair | ROT null | p_rot |
|---|---:|---:|---:|
| ENTITY (co-slot union-find) | 67 | 28.7 | **0.005** |
| WALLET (no merging) | 9 | 9.3 | 0.552 |

The union-find builds a **138-wallet mega-entity** whose events cluster in time *because that is how
it was built*; independent bots racing the same opportunity co-slot too, so the rule over-merges.
**Resolution adopted:** entity grouping is used for the outcome analyses (P&L, round trips, the
adversarial read), where "one operator counted many times" is the real risk; the timing test runs at
**wallet level as primary**, with the entity result printed beside it as the artifact it is. Both are
in the output; neither is hidden.

## 4. Pair-level test, and the MDE that makes the null mean something

The aggregate correlogram has no power against a heavy-tailed copy graph, and copy graphs are
extremely heavy-tailed: Apesteguia et al. (Mgmt Sci 2020) report **20.7–59.5% of copied leaders have
exactly one copier**, and the top 5% of leaders hold 61–93% of all copy relationships. So the question
is not "is flow more clustered" but "is there **any** ordered pair too tight to be chance".
Family-wise error is controlled by the null distribution of the **maximum** pair count — exact, and
without Bonferroni's conservatism over ~10⁵ pairs.

**Wallet level, ROT null, full day: nothing survives, and nothing is close.**

```
  delta  pool        side    max n_AB   null PERM   null ROT   p_perm   p_rot
      2  nosis/SOL   sell           4         3.4        3.6    0.373   0.468
      2  nosis/SOL   buy            8         3.2        7.4    0.005   0.428
      2  weave/SOL   buy           12         6.8       13.1    0.020   0.617
      2  weave/SOL   sell           2         1.2        1.9    0.164   0.756
     12  nosis/SOL   sell           5         7.2        6.4    0.970   0.940
     12  nosis/SOL   buy            9         4.5        9.3    0.005   0.552
     12  weave/SOL   buy           14         9.6       16.9    0.050   0.577
     12  weave/SOL   sell           2         1.4        2.3    0.393   0.995
```

**PERM flags four of eight at p ≤ 0.05; ROT flags none.** PERM destroys within-wallet
autocorrelation, so a wallet that slices one order into six clips looks like six independent draws
and the null max is understated. This is the exact failure the binding warns about, caught in the
act: an analyst who ran only the label-permutation null would have shipped four "copy relationships"
from this data.

**The MDE.** A synthetic copier injected into the real tape, mirroring N of a real leader's trades at
lag U[1,12] slots — the friendliest case, a perfect follower that never misses. Arena: nosis/SOL buy,
n=2,302, 868 wallets, 9 candidate leaders, 40 trials each.

| trades copied | 3 | 5 | 8 | 12 | 20 |
|---|---:|---:|---:|---:|---:|
| detected at p<0.05 | 0% | 0% | 18% | 32% | **100%** |

The honest claim is bounded: **no wallet copied ≥20 of any leader's trades in this window; a copier
at 12 would have been caught only about a third of the time; ≤5 is below resolution.** Given the
heavy tail, that residual is exactly where a real copier would hide, and no amount of cleverness on
24 h of tape closes it. Note also that the ROT null is *conservative* against a clustered copier —
rotation keeps the copier's own run of trades intact — so this MDE is an upper bound on what is
needed. **The 30 h live tape has no pair-level power at all**: its largest arena has only 3 wallets
with ≥20 trades, and detection is 0% at every injected level. The MDE above comes entirely from the
full BigQuery day, which is what the $1.41 bought.

## 5. The app is FOMO, and it is a terminal, not a copy engine

`AgmLJBMD..` pays gas for **183 distinct traders across 302 swaps** in the live tape (22.5% of all
813 traders) and **235 traders / 387 swaps** over the BigQuery day (13.0% of 1,807). Identified three
independent ways, not guessed: Manifest DEX's `client/ts/src/aggregators.ts` lists it in
`ORIGINATING_PROTOCOL_IDS` as `'fomo'`, beside verified entries for jupiter, phantom, binance and
coinbase; 43 of 60 sampled transactions pay USDC into `R4rNJHaff..`, DefiLlama's documented FOMO fee
wallet; and its structure is a textbook relayer — always fee payer, always multi-signer, 30 distinct
co-signers in 30 sampled transactions, **0% failure rate** (pre-simulated retail order flow).

The second-ranked payer, `gasTzr94..`, is **Jupiter's gasless sponsor wallet**, named in Jupiter's own
docs. It fires when the taker holds < 0.01 SOL, so it is a cross-app artifact — a hit means "routed
through Jupiter gasless", never "user of app X". Labelled, so it is never read as one venue.

**The cohort test.** If a relayer is a copy engine, its own users must fire together. On the quiet
full day they conspicuously do not:

```
nosis/SOL buy    FOMO swaps=139  wallets=94   observed cross-wallet pairs ≤25 slots = 1   null = 30.5   p=1.000
weave/SOL buy    FOMO swaps=44   wallets=27   observed = 1                                null = 12.3   p=1.000
nosis/SOL sell   FOMO swaps=129  wallets=120  observed = 7                                null =  5.4   p=0.308
```

On the live tape the same test returns p = 0.005 — not a contradiction but the finding in §6: the
live window contains one attention herd and the BigQuery day does not. **FOMO flow synchronises on
events, not on leaders.** That is a different mechanism with a different implication, and conflating
the two is how "copy-trading is moving our coins" gets asserted without evidence.

**The blind spot, measured rather than hand-waved.** The fee-payer test finds *gas-sponsored*
relayers only. Sampling 30 transactions at each product's known fee wallet: FOMO and Jupiter-gasless
are 30/30 multi-signer with a shared payer; **Trojan, BullX, Photon, GMGN, Axiom, Bloom, Maestro,
Nova, Banana Gun, Pepeboost and Vector are all 30/30 single-signer** — the app hands the user a
keypair and that wallet pays its own gas. Their flow is indistinguishable from an ordinary wallet
here. **22.5% is a lower bound on app-mediated share, not an estimate.**

## 6. The operator's coins: a herd, and the trap of looking first

Eyeballing found something vivid. On **2026-08-14 00:15:54 UTC**, nosis/SOL ran a 492-second window
(the script prints this block automatically, immediately above the test that refuses to credit it):

| | before (3,000 slots) | during | after (9,000 slots) |
|---|---|---|---|
| swaps | 202 | 436 | 565 |
| FOMO share of flow | **4%** | **33%** | 11% |
| price move | +22.6% | **+52.6%** (peak +59.8%) | **−16.1%** |

**96 buys by 90 distinct FOMO wallets**, median clip 0.228 SOL, 101.6 SOL total (identified
counterparties only). Price gave back **−19.0% at +10 min, −24.1% at +30 min, −21.7% at +1 h, −27.7%
at +4 h**. Read on its own that is a perfect exit-liquidity story and an obvious trade.

**It does not survive a pre-committed test.** Rule fixed in advance: trailing FOMO share of buys over
500 slots crosses a threshold; take forward returns at fixed horizons; null **permutes the FOMO flag
across trades** while holding every timestamp and every price fixed — asking the only question that
matters, whether it is FOMO specifically or whether any busy window looks like this.

```
LIVE TAPE     share≥30%  9 events   +900s  −4.19% (null −0.72%, p=0.060)   +10800s  −0.52% (null +4.87%, p=0.279)
              share≥50%  5 events   +900s  +8.80% (null −0.81%, p=0.760)
BIGQUERY DAY  share≥30%  9 events   +900s  +1.61% (null +0.28%, p=0.682)   +10800s  −7.58% (null −4.03%, p=0.273)
              share≥50%  3 events  +2700s  −9.86% (null −3.82%, p=0.250)
```

Median forward returns after a FOMO surge are mostly negative — **and so are the nulls.** The best of
sixteen cells reaches p = 0.060. **The single dramatic burst was a garden-of-forking-paths artifact
and is not evidence.** The direction is worth watching; it is not worth trading.

**Attention.** The other half of the FOMO channel is the pump.fun boards, and the operator's coins are
essentially absent from them: across ~1,200 snapshots per board, **nosis appears 14 times, weave once,
SOLVE once, DREGG never** — and only ever on `last_trade_timestamp`, a recency list, never on
`market_cap`, `reply_count`, `last_reply` or `currently-live`. The attention surface these apps
distribute through does not carry these coins. That is a structural answer, not a statistical one.

## 7. The penalty, measured instead of cited

PROGRAM.md §4 records "smart money averages ~14%/trade while a copier gets ~3%". Reading the source
changes what that sentence can support: **the 14.4% is measured; the 2.9% is not.** The copier there
is a closed-form construct — a hypothetical one-to-one immediate imitator, never observed. Its
mechanism, though, is exact and portable: `cost ratio = Y/(Y − 2d)`. So we ran it on our own pools.

**Counterfactual — mechanical price impact only, the floor:**

| pool | side | n | median d/Y | median penalty | p90 | p99 |
|---|---|---:|---:|---:|---:|---:|
| nosis/SOL | buy | 2,696 | 0.080% | 0.277% | 2.03% | 5.61% |
| nosis/SOL | sell | 3,121 | 0.055% | 0.316% | 1.79% | 7.97% |
| weave/SOL | buy | 1,137 | 0.060% | 0.178% | 1.85% | 6.85% |
| **all pools** | | **8,385** | | **0.253%** (mean 0.578%) | 1.85% | 7.20% |

`d/Y` is **three orders of magnitude** below a fresh bonding curve. The paper's 11.5 pp imitation
penalty **does not transfer to post-graduation pools**, and citing it as if it did overstates the
mechanical hazard by ~45×.

**Empirical — what real second movers actually paid (realised fills, no model):**

| Δ (slots) | pairs | median penalty | % worse off | size-matched median |
|---:|---:|---:|---:|---:|
| 1 | 4,592 | **0.879%** | **94.5%** | 0.686% |
| 5 | 11,115 | 1.050% | 88.3% | 0.703% |
| 25 | 17,273 | 0.818% | 80.7% | 0.573% |
| 75 | 30,119 | 0.449% | 66.5% | 0.286% |

**The bar it has to clear.** Of 2,084 wallet-pool books, **45.5% are censored** — they sold inventory
acquired outside the window, so their "profit" is just net SOL out and is meaningless; excluded, not
marked. Of the **523 fully closed** round trips that entered flat inside the window: median **+1.37%
on capital**, mean +1.13%, 55.3% positive, p10 −15.27%, p90 +16.18%. (Live tape, shorter and busier:
269 fully closed, median +2.36%, 60.6% positive.)

> **A trader who lands one slot behind another same-direction trade gives up ~0.69–0.88% out of a
> median round-trip edge of 1.37%. Copying costs roughly half the edge — before priority fees, before
> MEV, before being wrong about the leader.** The literature's ~5:1 ratio does not hold here. The 2:1
> that does is still enough to make follow-the-wallet uneconomic on these pools.

## 8. Adversarial read

Treating every profitable-looking wallet as constructed until shown otherwise:

- **Wash trading: none, at the literature's own threshold.** 2601.08641 Alg. 3 flags a bump bot at
  `α = flips/(|net|+1) ≥ 50`. Across 291 wallet-pools showing ≥1 identical-quantity flip, the maximum
  α is **6** (live tape: 58 wallet-pools, max α **13**). **Zero clear the bar.** The volume on these
  pools is not being manufactured by identical-quantity flipping.
- **Bait shape is present at a meaningful base rate.** Of uncensored wallet-pools with ≥6 trades,
  **28% show zero-or-negative realised SOL while still holding inventory** — marked "profitable" but
  not realisable. Any smart-money leaderboard built on marked P&L ranks these as winners. That is a
  reason to distrust *every* leaderboard, not evidence of a specific bait operation here.
- **The leaderboard is selected for variance, structurally.** Apesteguia's mechanism: rankings sort on
  *realised* payoff, so the top is whoever took the most variance and got lucky. In their experiment
  88% of copiers copied from the top-5 page and 71% copied the single top earner, while elicited risk
  preferences implied 1.7% should have held the riskiest asset — and it is the **more risk-averse**
  subjects who copy. **Treat any "smart money" list as a variance leaderboard by default.**

## 9. Two defects found on the way, both worth fixing

**(a) `counterparty` can be a pool.** `shitcoims_cluster.parse._counterparty` excludes only the pool
being traded (`owner == pool`), so any *other* pool holding the mint can satisfy the exact-mirror test
and be recorded as the trader. On 2026-08-13 that admits **16 off-curve accounts carrying 584 of
8,385 swaps (7.0%)**; on the live tape, 194 swaps. The largest, `C889ex3M..` with 304 swaps, is a
Meteora DLMM `lb_pair` (nosis/wSOL, owned by `LBUZKhRx..`) — off the ed25519 curve, has never signed
anything, cannot. Left in, it is the **second most profitable "wallet" in the tape at +68.9 SOL
realised**, which is not profit but reserve movement.

This is not cosmetic — it moved the headline. Before the fix, short-lag correlogram ratios ran as low
as **0.45× at entity level and 0.79× at wallet level**, which read as a *deficit* of cross-wallet
activity and invited a tidy story about order slicing. After it, the same lags sit at 0.69–1.03×:
flat. Pool accounts co-occur with everything, so leaving them in bends the null in whichever
direction the pool happens to trade. The guard is pure arithmetic — no RPC, no label list, no
maintenance: reject any address off the ed25519 curve. `on_curve()` in `studies/copytrading.py` is a
drop-in.

The guard is falsifiable, not merely plausible, and the study checks it every run: **every address
that signed a transaction must be on-curve**, because signing requires the private key. Measured on
the live tape — **970 distinct signers, 0 off-curve**. Zero false positives on the only population
where a false positive is provable.

**(b) Vault balances are not the pricing reserve on two of four pools.** Fitting the implied
constant-product `g = 1 − fee` from each pool's own fills, **separately on buys and on sells** — they
have opposite monotonicity in the fitted parameter, so agreement is a real test, not a restatement:

| pool | k from sells | k from buys | agreement | reading |
|---|---:|---:|---:|---|
| DREGG/SOL | −0.000% | −0.000% | 0.000 pp | vault **is** the curve, fee exactly 0.200% |
| SOLVE/SOL | −0.000% | −0.000% | 0.000 pp | vault **is** the curve |
| nosis/SOL | **4.753%** | **4.779%** | 0.027 pp | vault holds 4.8% excess tokens the curve ignores |
| weave/SOL | **8.600%** | **8.946%** | 0.346 pp | vault holds 8.8% excess |

Uncorrected, the raw vault balances imply `g = 1.048` on nosis sells and `1.092` on weave sells —
**above 1, impossible for a real curve**, i.e. the trader appears to get a better price than the
pool's own marginal. Anything replaying nosis/SOL or weave/SOL from vault balances misprices by
~4.8% / ~8.8%, and `replay_sufficient: true` currently asserts otherwise for both. This affects LP
and replay work well beyond this study. (Independently refit on the live tape: 4.394/4.401% and
8.728/8.908% — same conclusion, different window.)

## 10. What would change the answer

- **The live tape is certified complete, and that was load-bearing.** **Zero** reserve-chain breaks
  across all six pools (2,047 chained adjacent single-tx slots on nosis alone) — a dropped swap would
  break `post_raw == pre_raw`. And for every pool-hour after each collector's first partial hour, the
  live tape's signature set equals BigQuery's **exactly in both directions** (nosis 149/149, 159/159,
  203/203; weave 18/18, 58/58, 48/48; SOLVE 133/133 all day). The apparent 91% shortfall on
  2026-08-13 is collector start-up, not sampling. A burst detector on a sampled tape measures
  nothing, so this had to be checked.
- **Mildly counterintuitive: the $3 BigQuery scan is *less* complete than the free RPC collector.**
  The BigQuery day leaves ~21 chain breaks across nosis/weave/DREGG (0.06%, 0.8%, 2.3% of chained
  pairs) with median jumps of 1.6%/0.9%/0.3% of reserve — trade-sized, so these are genuinely
  uncaptured reserve-moving events, not dust. The replication is therefore a **corroboration** of the
  live tape, not a replacement for it, and the identity-bearing primary analysis stays on the tape
  that chains perfectly.
- **The single highest-value next increment is free.** Collect each app's **fee wallet** (a maintained
  DefiLlama-sourced map exists in OpenChainBench). That converts the 22.5% lower bound into a real
  estimate and makes the single-signer cohort — Trojan, BullX, Photon, GMGN, Axiom — visible for the
  first time. It costs nothing and closes the one gap that actually bounds this study.
- **Wallet history depth bounds the adversarial read.** The literature's smart-money gate is months
  deep (t-stat over all prior coins, returns bucketed over the 11th–15th prior coin, "time since
  first trade ≈ 221 days"). Our window is hours. Nothing here can rank a wallet's skill and this
  study does not try.
- **More days raise power, not direction.** The flat short-lag result is consistent across two
  independent windows, two nulls, and both aggregation levels. Going from "no copier above 12
  trades/day" to "no copier above 5" needs roughly an order of magnitude more tape at ~$4.43/day.
  Cheap — but hard to justify when the measured effect is *flat*, not merely small.

## 11. What to do with this

1. **Do not build follow-the-wallet.** There is nothing to follow at our resolution, and the
   arithmetic is against it anyway: ~0.69–0.88% second-mover cost against a 1.37% median round-trip
   edge.
2. **Do not treat FOMO flow as an alarm.** It is ≥22% of the traders on these coins and it is *not*
   copy-driven. Its share spiking does not predict a top once the null is run — best p = 0.060 of 16.
3. **Do treat any smart-money leaderboard as adversarial.** 28% of active wallets here show
   non-realisable marked profit, and the ranking mechanism itself selects for variance.
4. **Fix the two defects in §9.** The off-curve guard prevents a liquidity pool from being ranked the
   second-best trader on the tape and removes a spurious signal from flow work. The curve haircut
   matters to anything replaying nosis or weave.
5. **Collect app fee wallets.** Free, and it is the only measurement gap that materially bounds this
   conclusion.

---

*Recorded as a null, deliberately. The naive null said 73×; the correct null said 1.01×. The vivid
herd said −27.7% and then declined to replicate. The label-permutation null offered four copy
relationships and the autocorrelation-preserving null took all four back. Four chances to ship
something exciting and wrong.*
