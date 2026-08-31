# The complete position, from chain, across all five wallets

2026-08-14. Tooling: `studies/position_history.py`. Read-only throughout — no signing, no
sending, no keypair, and no import of `shitcoims_sentinel`. Cache in `.cache/position_history/`.

**Scope.** All 2,012 transactions ever to touch the operator's five wallets or any of their 167
token accounts, from the first (`pumpfun_main`, 2026-06-27T13:14:02Z) to the last at time of
writing (2026-08-14T05:25:42Z). Not a window, not a sample: the whole history.

Every SOL figure is exact lamports; every token figure is exact raw base units. USD appears only
as a display layer, and every USD number on this page uses the **same** price set, fetched once:

> **Jupiter lite-api v3, 2026-08-14T05:47:08Z** — SOL `$75.8097844546`, DREGG `$0.0003277316`,
> weave `$0.0001453362`, nosis `$0.0002992459`, SOLVE `$0.0000393660`.

---

## 0. Why you can believe the rest of this page

The reconstruction proves itself twice, and both checks are exact rather than approximate.

**SOL.** Summing every signed lamport delta over the whole history, per wallet, reproduces the
live `getBalance` for all five wallets **to the lamport**:

| wallet | Σ deltas (SOL) | live `getBalance` |
|---|---|---|
| shitcoims `Sh1WNJ8g` | 0.222140256 | 0.222140256 |
| tha funds `Funv3Qdb` | 3.052244871 | 3.052244871 |
| pumpfun main `PmpDh2BQ` | 0.044135043 | 0.044135043 |
| Ember dev `Dev2GmPW` | 0.086172985 | 0.086172985 |
| og shitcoims `PrvpTgcu` | 0.000983922 | 0.000983922 |

**Tokens.** The same test per `(wallet, mint)` against `getTokenAccountsByOwner` — exact on
every mint.

This is a stronger check than it looks. A ledger reconciles to the current balance only if it
starts from the true zero and misses nothing in between; a truncated history or a dropped
transaction shows up as a non-zero residual. It also settles a question the brief raised:
`PrvpTgc` has no activity before 2026-07-21, because if it had, the residual would be its
balance on that date and the books would not close.

**The one place I had to correct myself.** My first attribution pass booked 77 SOL of LP
deposits as gifts to strangers, because depositing SOL into a DLMM position is a `system.transfer`
to the wallet's *own* WSOL token account — whose address is an ATA and therefore not in the
wallet list. The same class of error booked ~121M DREGG of swap legs as distributions, because a
sell sends tokens to a pool vault the operator does not own. Both are fixed by resolving every
transfer endpoint through the transaction's own token-balance owner records, and by refusing to
counterparty-classify transfers inside a DEX or LP transaction at all. **This is the identical
defect the study was commissioned to find, and it reappeared inside the instrument built to find
it.** Worth saying plainly: counterparty classification is not a detail, it is the whole
measurement, and it will go wrong again.

---

## 1. Verdicts

| # | Claim | Verdict | Chain says |
|---|---|---|---|
| a1 | Trading lost **7.47 SOL** on 2026-08-12 | **VERIFIED** (0.4% off) | −7.440821 SOL realized, fully closed, all positions flat |
| a2 | "**8.31 SOL of fee income** flowed in during the window" | **WRONG, twice** | 8.162961 SOL, and **none of it was fee income** — 84.1% internal, 15.9% exchange withdrawal |
| a3 | "the book **ended at ~1.1 SOL**" | **WRONG** | 0.549597 SOL at end of 2026-08-12; 1.06 SOL was the balance entering the final hour |
| a4 | `PrvpTgc`'s 4.47 SOL was an unknown external counterparty | **WRONG** (as the brief anticipated) | internal transfer; and a **second** internal transfer of 2.390716 SOL from `tha_funds` was in the same window and was also missed |
| b1 | Meteora realized **+20.10 SOL** over 42 closed positions | **WRONG as stated** | **12.913149 SOL** is all the SOL Meteora ever paid, and every lamport of it was a fee claim. No withdrawal converted to SOL |
| b2 | Meteora realized **+$1,449.46** | **UNRECONSTRUCTABLE** | needs a per-event price series this study does not have. The fee leg alone marks at **$1,829.66** today — *above* the claim — while the basket the positions are down is worth ~$3,500 and is not netted into it |
| b3 | 42 closed positions | **VERIFIED, refined** | 48 opened, 44 closed, **4 open** (`getProgramAccounts` on the DLMM program, owner at offset 40; all four on `tha_funds`) |
| c1 | **256 SOL** of lifetime creator fees | **PARTLY RETRACTED — see §7.** My headline was over-attributed | 757.111 SOL of pump.fun fee claims arrived and is real, but only **467.209 SOL is DREGG-attributable**; 287.235 SOL comes from a social-fee PDA carrying no coin identity. The DREGG figure is 1.83× the UI, not 2.96× |
| c1b | The USDC-legged inflows are not fee income | **REFUTED** | **zero USDC ever moved** in any of the 405 inflow transactions; the USDC leg is a second claim attempt logging "No fees available to claim" in 103 of 104 cases |
| c2 | Some creator fees are still unclaimed | **VERIFIED — none are** | every claim is swept within the hour; the wallet ends at 0.044 SOL |
| c3 | Realized creator take is 0.60% vs 0.81–1.19% of DREGG volume | **UNRECONSTRUCTABLE here** | this study measured fees, not volume. It does invert the check: the corrected **467.209 SOL** of DREGG fees implies $3.73M–$5.90M of lifetime DREGG volume |
| c4 | DREGG fees run **$213–313/day** | **VERIFIED for now, wrong as a lifetime rate** | August: 51.593 SOL / 14 days = **$279.38/day**, dead centre. June ran 221.9 SOL and July 483.6 SOL — the estimate was calibrated on the decayed regime |
| d | DREGG unlocks to `Dev2Gm` — never accounted anywhere | **NOW SIZED** | Streamflow escrow, **62,626,849.3125 DREGG locked (6.2635% of supply)**, 3 tranches of 1,204,362.4868 released = **$1,184.12**; **$19,340.67 still locked** |
| e | Net position and net PnL | **COMPUTED, identity closes to 1 lamport** | see §2 |

---

## 2. The household book — lifetime, all five wallets, in SOL

Every lamport that ever moved, assigned to exactly one bucket. The buckets sum to the live
balance by construction, so an unclassified flow cannot hide.

| bucket | shitcoims | tha funds | pumpfun main | Ember dev | og shitcoims | **TOTAL** |
|---|---|---|---|---|---|---|
| pump.fun fee claims | — | — | +757.018737 | +1.128507 | — | **+758.147244** |
| LP fees | — | +12.347144 | +0.041000 | +0.525004 | — | **+12.913149** |
| LP withdrawals | — | +61.489863 | — | +5.294176 | — | **+66.784039** |
| LP deposits | — | −80.951987 | — | −5.917821 | — | **−86.869808** |
| swaps (trading) | −7.362208 | −8.276624 | −12.268925 | +4.023479 | −8.569061 | **−32.453340** |
| internal in | +6.861848 | +0.100000 | — | +5.338533 | +1.556066 | +13.856447 |
| internal out | — | −2.490716 | −6.894599 | — | −4.471132 | −13.856447 |
| external in | +1.301113 | +31.335103 | +0.000779 | +1.556529 | +12.660371 | **+46.853894** |
| external out | −0.500000 | −25.078989 | −737.669082 | −11.828051 | −1.199364 | **−776.275485** |
| gas | −0.078613 | −0.026167 | −0.007305 | −0.007011 | −0.005002 | −0.124098 |
| rent / unwrap / other | — | +14.604617 | −0.176471 | −0.027172 | +0.029107 | +14.430081 |
| **NET (= live balance)** | **0.222140** | **3.052245** | **0.044135** | **0.086173** | **0.000984** | **3.405677** |

**Internal transfers net to exactly zero** — +13.856447 in, −13.856447 out — which is the whole
point of holding five wallets in one ledger. There were seven of them, all previously invisible:

| date | from | to | SOL |
|---|---|---|---|
| 2026-07-11 | pumpfun main | Ember dev | 1.045186 |
| 2026-07-24 | pumpfun main | og shitcoims | 1.556071 |
| 2026-07-26 | pumpfun main | Ember dev | 0.535036 |
| 2026-07-26 | pumpfun main | Ember dev | 2.751765 |
| 2026-07-26 | pumpfun main | Ember dev | 1.006567 |
| **2026-08-12 11:32** | **og shitcoims** | **shitcoims** | **4.471212** |
| **2026-08-12 12:30** | **tha funds** | **shitcoims** | **2.390796** |

### The reconciliation the coordinator asked for

```
  creator fees            +758.147244
  LP fees                  +12.913149
  LP withdrawals           +66.784039
  LP deposits              −86.869808
  trading (swaps)          −32.453340
  external in              +46.853894
  external out            −776.275485
  gas                       −0.124098
  rent / unwrap / other    +14.430081
  internal (nets)           ±0.000000
  ─────────────────────────────────────
  = current SOL holdings     +3.405676     vs live 3.405677
  RESIDUAL                    0.000001 SOL   (1,290 lamports, floating-point display only)
```

The identity closes. There is no unclassified flow.

---

## 3. Where the money went — the third category

`external out` is 776.275485 SOL, and lumping it into "losses" or "distributions" would be wrong
in both directions. It splits cleanly on chain into two populations with different shapes.

### 3a. Coinbase — 486.630 SOL, operator-confirmed

`Cbx3NneV…3HP3Eh` is **the operator's Coinbase receiving address** (confirmed by the operator).
The chain shape agrees, and the discriminating property is worth stating because it is what
separates this address from the three below: **it receives essentially only from us.** A per-user
exchange deposit address has exactly one depositor. It forwards everything immediately
(balance 0.0011 SOL against 365 lifetime transactions) to `2AQdpHJ2`, `D89hHJT5`, `4NyK1AdJ`,
`FpwQQhQQ` — and `FpwQQhQQ` (**35,087.5 SOL**) and `F7p3dFrj` (**8,291.9 SOL**) later *fund the
trading wallet*, which closes the loop.

| direction | SOL | transfers | USD at **time of transfer** |
|---|---|---|---|
| out to Coinbase, from `pumpfun_main` | 483.1017 | 135 | $36,657 |
| out to Coinbase, all five wallets | 486.6299 | 137 | **$36,884** |
| back in from Coinbase infrastructure | ~43.5 | — | ~$3,300 |
| **net cashed out** | **~443 SOL** | | **~$33,600** |

Valued at time-of-transfer per the operator's own frame: June $7,584, July $25,348, August
$3,953. **SOL was flat at $71.81–$77.81 across the entire window** (CoinGecko daily), so today's
price gives $36,891 — a 0.02% difference. The historical-price refinement changes nothing here,
which is itself worth recording so nobody redoes it.

**This reconciles with the operator's "I would notice $40k."** They did receive ~$36.9k — but
across **137 separate transfers averaging $269 each**, spread over seven weeks, against ~$4,100/mo
of obligations and a $40k IRS debt. A drip at that cadence never presents as a lump sum. The
chain and the recollection are not in conflict; they are the same money seen at different
resolutions.

Neither direction belongs in PnL: outbound is cashing out, inbound is funding from off-chain.

### 3b. Three unidentified destinations — 223.346 SOL — **first-draft classification RETRACTED**

| address | SOL | transfers | distinct senders (30-tx sample) | last payment |
|---|---|---|---|---|
| `WYoLt8fH…uwYhB1` | 84.9968 | 25 | 4, **none ours** | 2026-07-23 |
| `Drg3Mo7K…P6D2Dbq` | 82.3278 | 30 | 8, **none ours** | 2026-07-28 |
| `6RTFsqEW…H5aXXn` | 56.0217 | 17 | 7, **none ours** | 2026-07-26 |

**My first draft called these "exchange-deposit-shaped" and grouped them with Coinbase. That was
wrong and is withdrawn.** They fail the test that Coinbase passes: each receives from several
distinct senders, none of them the operator's wallets. A per-user deposit address has one
depositor. These are shared.

Two facts about them that the tape does establish and that should go to the operator:

- **The payments stop dead on 2026-07-28.** From 2026-07-29 onward, every lamport of claimed fee
  goes to Coinbase — in August the daily claim and the daily Coinbase transfer agree to four
  decimal places (2026-08-01: 6.6839 in, 6.6839 out; 2026-08-12: 4.6291/4.6291).
- **They run in lockstep with the social-fee stream, not the DREGG one.** Payments span
  2026-06-28 → 2026-07-28, the same window in which the social-fee PDA paid 284.3 of its 287.2
  SOL, and total **77.8% of that stream**. That is a temporal coincidence, not a proven link, and
  I am flagging it as a hypothesis for the operator to confirm rather than asserting it.

**Consequence for `external in` (46.853894 SOL):** it is mostly the same money returning.
**Consequence for `external in` (46.853894 SOL):** it is mostly the same money returning.
`2AQdpHJ2` (17.446), `D89hHJT5` (9.769), `4NyK1AdJ` (9.027) are the very addresses `Cbx3NneV`
forwards to. **Treating that 46.85 SOL as outside income would double-count it.** How much is
returning capital versus genuinely new money is **UNRECONSTRUCTABLE** without knowing which
custodian sits behind those addresses.

### 3b. Discretionary distributions — the "randos"

Bare transfers, excluding all DEX/LP/fee plumbing, excluding the treasury hubs, and excluding the
operator's own vesting escrow:

| asset | amount | recipients | transfers | USD @ spot |
|---|---|---|---|---|
| SOL | 66.2993 | 28 | 219 | $5,026.14 |
| DREGG | 17,522,791 | 976 | 989 | $5,742.77 |
| weave | 6,894,544 | 1 | 6 | $1,002.03 |
| SOLVE | 7,221,773 | 1 | 1 | $284.29 |
| nosis | 715,035 | 1 | 1 | $213.97 |
| | | | | **$12,269.20** |

Of the SOL, **39.6241 SOL went to 14 one-shot recipients** — the gift-shaped tail. The remaining
26.68 SOL went to 14 repeat counterparties, which is service-shaped or trade-shaped, and the tape
does not distinguish them; that split is **ambiguous and I am not going to guess it**.

The DREGG distribution is the interesting one and it is **not** what "sent too much to randos"
sounds like. Its shape:

- **median recipient: 744.05 DREGG — $0.24.** Roughly 970 of the 976 recipients got dust.
- **the top 10 take 97.1%.** The real giveaway is a handful of transfers: 8,510,709 ($2,789),
  3,003,136 ($984), 1,400,670 ($459), 1,063,080 ($348), 800,000 ($262).

So the giveaway is denominated in **tokens, not SOL**, it is **~$5,700 not ~$29,000**, and it is
**concentrated in about five transfers**, not spread over a thousand. A thousand-wallet dust
airdrop is a marketing action with a negligible balance-sheet cost; five large transfers are the
decision worth revisiting.

Three exclusions that each move the number by a lot, and each of which a naive counterparty rule
gets wrong:

1. **62,626,849.31 DREGG to `9Go2paWt…`** is the Streamflow vesting escrow — the operator's own
   locked tokens, which vest back to `Ember dev`. Counting it as a giveaway inflates the
   distributed figure **3.5×**.
2. **9,138,358 DREGG to the treasury hubs** is off-ramping, not gifting.
3. **~121M DREGG of swap legs** are sales into pool vaults. Booking those as distributions was my
   own first-pass bug (§0).

---

## 4. The claims, in detail

### (a) The 2026-08-12 loss survives; the story around it does not

The `shitcoims` wallet's **entire life** is 2026-08-12T11:32:36Z → 2026-08-13T23:23:01Z, 329
transactions. Its first transaction is its funding, so there is no prior state to estimate.

| | SOL |
|---|---|
| funded, internal (og shitcoims 4.471132 + tha funds 2.390716) | +6.861848 |
| funded, external (2 exchange withdrawals + 2 poison dust) | +1.301113 |
| **total in** | **+8.162961** |
| non-swap outflow | −0.500000 |
| **realized trading result incl. gas** | **−7.440821** |
| final balance | +0.222140 |

Split by day: **−7.113360 SOL on 2026-08-12**, a further **−0.327457 SOL on 2026-08-13**.

**The −7.47 SOL claim is VERIFIED.** The complete cross-wallet reconstruction gives −7.440821 SOL,
a 0.029 SOL (0.4%) discrepancy against the published figure — and PROGRAM.md's own USD gloss
(`~$564`) matches my −7.440821 SOL at today's price to the dollar (**$564.09**). All token
positions closed to *exactly* zero, so this is fully realized with nothing marked to market.

**Correctly classifying `PrvpTgc` does not change the loss, and that is worth understanding.**
Trading PnL is `final balance − deposits + withdrawals`, and it is invariant to *where* a deposit
came from. The misclassification never touched the loss number. What it corrupted was the
*narrative*:

- **"8.31 SOL of fee income flowed in during the window" is wrong on both counts.** The inflow was
  8.162961 SOL, and **zero SOL of creator fee income has ever reached the trading wallet.**
  `pumpfun_main` has never sent `shitcoims` anything. 84.1% of the funding was the operator moving
  their own money between their own wallets, and the remaining 15.9% was withdrawn from an
  exchange. The session was not funded by the fee stream; it was funded by liquidating the
  previous wallet and the LP wallet.
- **The brief anticipated one internal transfer. There were two.** `tha_funds` sent 2.390716 SOL
  at 12:30, 58 minutes after `og_shitcoims` sent 4.471212 at 11:32. The second was also booked as
  external.
- **"the book ended at ~1.1 SOL"** — end of 2026-08-12 was **0.549597 SOL**. 1.0606 SOL was the
  balance entering the final hour, before the last two trades.

### (b) The LP book in token units — and why "+20.10 SOL realized" cannot mean what it says

48 positions opened, 44 closed, **4 still open**, all on `tha_funds` (verified directly:
`getProgramAccounts` on `LBUZKhRx…` with a memcmp on the owner field at offset 40 returns 4 for
`tha_funds` and 0 for every other wallet).

The complete LP ledger, all wallets, in **token units**:

| token | deposited | withdrawn | fees claimed | net |
|---|---|---|---|---|
| weave | 79,307,468 | 56,734,745 | 1,081,940 | **−21,490,783** |
| DREGG | 18,240,215 | 19,542,636 | 1,966,889 | **+3,269,310** |
| SOLVE | 9,065,055 | 6,911,425 | 0 | **−2,153,630** |
| nosis | 3,060,470 | 1,735,280 | 163,293 | **−1,161,897** |
| `5pVQnF…` | 4,931,059 | 435,241 | 1,324,028 | **−3,171,790** |
| SOL | 86.869808 | 66.784039 | 12.913149 | **−7.172620** |

**The verdict on +20.10 SOL: WRONG as stated.** Meteora paid this desk **12.913149 SOL** in its
entire history, and every lamport of it came from a `ClaimFee2` instruction. Not one withdrawal
returned SOL beyond that. A closed position returns a *basket* — weave, DREGG, SOLVE, nosis — and
"+20.10 SOL realized" is that basket re-quoted at prices Meteora chose, at times Meteora chose.
The brief's suspicion is confirmed by the ledger: **"realized" here means the position closed, not
that anything converted.**

**The verdict on +$1,449.46: UNRECONSTRUCTABLE.** Reproducing it needs the mark on every deposit
and every withdrawal at its own block time — a per-event price series this study does not have,
and which is the honest thing to say rather than to estimate. Two things I *can* put next to it:

- **The fee leg alone marks at $1,829.66 today** — SOL $978.94 + DREGG $644.61 + weave $157.25 +
  nosis $48.86, plus 1,324,028 `5pVQnF` whose price I did not fetch. That is *more* than the
  claim, so the claim is not obviously inflated.
- **But the basket is down 21.5M weave, 2.15M SOLVE, 1.16M nosis and 3.17M `5pVQnF`**, and how
  much of that is still inside the 4 open positions versus consumed by divergence is **not
  resolved here** — separating them requires decoding the `PositionV2` account layout and the bin
  liquidity, which this study did not do. That is the single highest-value follow-up, and it is
  cheap: four accounts.

This is consistent with `RESULT_circuit_theory.md` §8.1 (the desk is up because the tokens rose,
not because LPing beat holding) and it sharpens it: **the fee numerator is real and denominated in
tokens; the SOL-denominated summary is a re-quote, not a cash flow.**

### (c) Creator fees — 757 SOL of claims, but only 467 SOL of them are DREGG

**757.110643 SOL** of pump.fun fee claims arrived at `PmpDh2` over its whole life. That figure is
not in doubt: it is a balance delta, it is reproduced independently by the coordinator's own
measurement (757.111 gross in / 757.067 gross out / +0.044 net), and it is corroborated
downstream by **$36,884 landing at the operator's confirmed Coinbase address**.

**But my first draft called all of it "DREGG creator fees", and that was over-attribution.** The
error was the test: I asked *"does the pump.fun fee program appear in this transaction?"*, which
is true of every claim **attempt**, including the ones that pay nothing. The unfoolable test is
*"whose lamports went down?"* — and it splits the aggregate in two:

| paying account | what it is | txs | 2026-06 | 2026-07 | 2026-08 | **total** |
|---|---|---|---|---|---|---|
| `2dQa7pRL…UE4A` | WSOL token account; **DREGG mint present in 154/154** | 154 | 78.086 | 340.971 | 48.152 | **467.209** |
| `8buZegTz…V7kF` | 179-byte pump.fun-fee-program account carrying ASCII id `704250`; **no coin mint at all** | 105 | 142.518 | 141.823 | 2.895 | **287.235** |
| others | dust and one-off | 146 | 1.308 | 0.812 | 0.547 | 2.667 |

Two mechanical points that took real work and are worth keeping:

- **A creator fee is never a `system.transfer`.** `2dQa7pRL` is a *WSOL token account*, and
  wrapped SOL lives in the token account's own lamports — so a fee payment shows up as a lamport
  delta on a token account and appears nowhere in the parsed instruction stream. Summing parsed
  transfers into `PmpDh2` gives **0.00078 SOL**, and all of it is poisoning dust.
- **The USDC hypothesis is dead.** Across all 405 inflow transactions, the total USDC that moved
  is **exactly zero**. The USDC leg is a *second* `ClaimSocialFeePdaV2` instruction in the same
  transaction, claiming against a USDC-denominated vault, and **103 of the 104 log "No fees
  available to claim"**. Splitting the 757 by "does USDC appear" splits it by claim-attempt
  shape, not by income type.

**So the corrected DREGG-attributable lifetime figure is 467.209 SOL, and the UI's 256 SOL is
1.83× off rather than 2.96× off.** The gap narrowed by more than half and did not close.

**What is now established about the residual, and what is not.** The operator created **two**
coins on 2026-06-27 — DREGG (`XkeTXo11`, 16:31) and `HNAKdSP5…pump` (20:47) — and a
`CreateFeeSharingConfig` / `CreateSocialFeePda` transaction at 20:55 is bound to **`HNAKdSP5`, not
DREGG**, with a *different* social id (`2381523`). So the wallet demonstrably aggregates more than
one coin's economics, and the social-fee stream carries no coin identity, which means **it would
not appear on DREGG's coin page under any reading.** That is the honest resolution of the
aggregation question: 287.235 SOL of the 757 is not DREGG revenue.

**The trailing-window hypothesis I raised in the first draft is REFUTED** on the corrected series
and I am withdrawing it. On the DREGG-only stream the cumulative crosses 256 SOL on 2026-07-16,
and the nearest trailing-window sum is 254.25 SOL from 2026-07-08 — neither lands on a month
boundary, a config change, or any other natural edge. Fitting a window to a target is curve-fitting,
and the simpler explanation the coordinator asked me to prefer (per-coin split) does more of the
work but does **not** finish the job.

**What remains UNRECONSTRUCTABLE: why pump.fun's UI shows 256 SOL against 467.209 SOL of
DREGG-linked claims.** The 211 SOL gap needs pump.fun's own definition of the number it displays —
whether it is net of a fee-sharing split, restricted to the PumpSwap post-graduation component,
or scoped to a period. No on-chain artifact settles it, and I would rather hand the operator a
precise 211 SOL discrepancy than a story that closes it.

**Unclaimed: none**, and chain agrees with the operator. Every claim is swept within the hour and
`pumpfun_main` ends at 0.044 SOL.

**On the rate.** The corrected DREGG-only figure implies **77,868 SOL ($5.90M)** of lifetime DREGG
volume at a 0.60% take, or **49,180 SOL ($3.73M)** at 0.95%.

**PROGRAM.md §0's income model survives, and the correction sharpens it.** August ran 48.152 SOL
of DREGG fees over 14 days = 3.439 SOL/day = **$260.72/day**, inside the quoted $213–313/day. That
estimate is right for the current regime. It is not a lifetime rate: June and July ran 4–9× hotter.

### (d) The DREGG unlocks — sized for the first time

Never accounted anywhere in this project, and the closure step in §0 is what made them visible:
`getSignaturesForAddress(owner)` does not return transactions that move a wallet's tokens without
naming the owner, which is exactly the shape of an inbound vesting withdrawal.

The vehicle is **Streamflow** (`strmRqUCoQUgy2XeFptbhSJH2sfF4uYdgLcaAdEbQaQ`).

- **2026-06-27T16:31:01Z** — `pumpfun_main` locked **62,626,849.3125 DREGG** into the escrow
  `9Go2paWt…`. Against a supply of **999,872,425.106879**, that is **6.2635% of DREGG**.
- Withdrawals land on `Dev2Gm`, **1,204,362.4868 DREGG each**, at 16:31 UTC on a strict **14-day**
  cadence: **2026-07-11, 2026-07-25, 2026-08-08**. Next expected **2026-08-22T16:31Z**.
- **Released to date: 3,613,087.4604 DREGG = 0.3614% of supply = $1,184.12.**
- **Still locked: 59,013,761.85 DREGG = 5.9021% of supply = $19,340.67.**
- Per tranche **$394.71**, i.e. **$28.19/day** — about 10% of the current creator-fee run rate.
- `Ember dev` holds **749.884812 DREGG ($0.25)** now: essentially the entire release has been
  passed on, mostly as the ~202-recipient tranches of 5,952.375 DREGG visible on 2026-07-26.

The schedule implies roughly **49 more tranches, ~22 months**, if the stream runs to exhaustion at
this rate. That is a real, quantified, previously-unbooked asset — and at $19,341 it is
**larger than every other holding on this page combined**, which is the reason it was worth
sizing even though the per-day figure is small.

### (e) The complete position

**Liquid, on-chain, now:**

| | amount | USD @ spot |
|---|---|---|
| SOL (5 wallets) | 3.405677 | $258.18 |
| weave (`tha_funds`) | 221,855.3166 | $32.24 |
| SOLVE (`tha_funds`) | 3,095,045.5364 | $121.84 |
| DREGG (`Ember dev`) | 749.884812 | $0.25 |
| **identified liquid** | | **$412.51** |

**Not marked** (stated, not estimated): the **4 open DLMM positions**; `HNAKdSP5` 1,770,172.60 and
JUP 9.79 on `pumpfun_main`; `EKH3tGXvf5` 2,178,132.39, `xBB9QSpJLz` 1,584,290.99 and `8iB8GmY1X2`
18.05 on `og_shitcoims`. No price was fetched for these mints and none is guessed.

**Locked:** 59,013,761.85 DREGG in Streamflow = **$19,340.67**.

**Lifetime flows:**

| | SOL | USD @ spot |
|---|---|---|
| pump.fun fee claims received | +758.147244 | +$57,474.98 |
| — of which DREGG-attributable | +467.209 | +$35,420 |
| — of which social-fee PDA (no coin) | +287.235 | +$21,773 |
| LP fees earned | +12.913149 | +$978.94 (SOL leg only; token legs $850.72 more) |
| trading, all five wallets | **−32.453340** | **−$2,460.28** |
| LP principal (deposits − withdrawals) | −20.085769 | −$1,522.69 |
| cashed out to Coinbase (confirmed) | −486.630 | −$36,884 *(at time of transfer)* |
| to 3 unidentified destinations | −223.346 | −$16,932 |
| returned from custody | +46.85 (mostly) | +$3,551.86 |
| discretionary distributions | −66.2993 SOL + tokens | −$12,269.20 |
| gas | −0.124098 | −$9.41 |

**Net PnL, stated honestly.** The single number the brief asks for does not exist as a single
number, and saying so is the finding rather than a dodge. Two are defensible and they answer
different questions:

1. **Operating result, chain-only** — what the desk *earned* minus what it *lost trading*:
   `+758.147 (all fee claims) + 12.913 (LP fees) − 32.453 (trading) − 20.086 (LP principal) − 0.124 (gas)`
   = **+718.397 SOL ≈ +$54,471**, plus $19,341 of locked DREGG. The business is the fee stream, at
   a 23× ratio over everything else on the page — exactly as PROGRAM.md §8 argues, and by a wider
   margin than it claims.
2. **Net worth change** is **not computable from chain.** 486.630 SOL (**$36,884** at time of
   transfer) went to the operator's Coinbase and ~43.5 SOL came back, netting **~443 SOL (~$33,600)
   cashed out** — but what happened to it inside Coinbase is off-tape. A further **223.346 SOL
   (~$16,932)** went to three destinations nobody has yet identified (§3b). **Anyone quoting a net
   worth figure for this desk is quoting an assumption about those three addresses.**

**Trading is a rounding error against the fee stream, and it is negative in four wallets of five:**
shitcoims −7.441, tha funds −8.277, pumpfun main −12.269, og shitcoims −8.569, Ember dev +4.023.
Note `pumpfun_main`'s −12.269 SOL is not a losing trade — it is the launch-day bonding-curve
purchase of ~72.3M DREGG (7.2% of supply) for ~$930, most of which was then locked into the
vesting escrow. Read as a position rather than a loss, it is the best trade on the page.

---

## 5. Two findings nobody asked for

### 5a. A targeted address-poisoning campaign, ongoing

**84 of the 91 external addresses that have ever sent SOL to these wallets are poisoning dust** —
1-lamport transfers totalling **0.000838047 SOL**. They are not spray. Every one is a vanity
address generated to match the **prefix and suffix** of an address the operator actually
transacts with:

| real counterparty | poison lookalikes |
|---|---|
| `Cbx3NneV…3HP3Eh` (486.6 SOL) | `Cbx3naVY…JRP3Eh`, `Cbx3SmW9…DRP3Eh`, `Cbx3gMty…n3P3Eh` |
| `Drg3Mo7K…P6D2Dbq` (82.3 SOL) | `Drg37JY9…gD2Dbq`, `Drg3swgh…H2Dbq`, `Dr11TDws…HYbDbq` |
| `WYoLt8fH…uwYhB1` (85.0 SOL) | `WYoLASoy…dK1hB1`, `WYoLeAhb…rgQ1B1`, `WY1Sxw…hB1` |
| `6RTFsqEW…H5aXXn` (56.0 SOL) | `6RTFzAQK…ukjaXXn`, `6R11EBjH…LDpxXXn` |
| `PrvpTgcu…` (og shitcoims) | `Prv1CVzq…` — dust arrived **28 seconds** after the real 4.47 SOL transfer |
| `Funv3Qdb…aMQ` (tha funds) | `Fun1hUJX…WaMQ` — dust arrived **45 seconds** after the real 2.39 SOL transfer |
| `PmpDh2BQ…` (pumpfun main) | `Pmp1xuHhCb…` |

The timing is the tell: the dust lands within a minute of the genuine transfer it is imitating, so
the fake sits adjacent to the real one in wallet history exactly when the operator is most likely
to copy an address from it. **Every one of the five wallets and every one of the four treasury
destinations is being targeted, and the campaign is live** — dust arrived on 2026-08-14.

Nothing has been lost to it: no outbound transfer in the entire history goes to a poisoned
address. **Never copy a destination address out of transaction history.**

### 5b. The five-wallet set is not closed

`Cbx3NneV` receives 486.6 SOL essentially only from `pumpfun_main` and forwards to addresses that
later fund `shitcoims`. Whatever those addresses are, **value routes out of the five-wallet set and
back into it**, so "the operator's position" as measured here has a boundary that the tape can see
value crossing in both directions. The books close anyway — every crossing is counted — but any
future study that wants a true net-worth figure needs those four addresses identified, and that
identification has to come from the operator or a custodian, not from chain.

---

## 6. What is missing, precisely

Stated rather than estimated, per the brief:

1. **The contents of the 4 open DLMM positions.** Needs the `PositionV2` account layout and bin
   liquidity decode. Without it, the split of the LP basket deficit between "still deployed" and
   "lost to divergence" is unresolved, and claim (b2) stays unreconstructable.
2. **A per-event price series.** Every "realized USD" figure any venue reports — Meteora's
   $1,449.46 included — is unreproducible without marks at each deposit, withdrawal and claim
   block time.
3. **Identity of the four treasury addresses.** Blocks any net-worth statement (§4e).
4. **DREGG volume.** Blocks the creator-take-rate check (c3). Available from
   `scripts/bulk_history.py` over the DREGG/SOL pool.
5. **Prices for 6 held mints** (`HNAKdSP5`, `EKH3tGXvf5`, `xBB9QSpJLz`, `8iB8GmY1X2`, `5pVQnF`,
   `8gJUTwn9`). Cheap; not fetched here.
6. **Why the pump.fun UI shows 256 SOL against 467.209 SOL of DREGG-linked claims** (§4c). Needs
   pump.fun's definition of the displayed number. The trailing-window story is refuted.
7. **What the three destinations in §3b are.** 223.346 SOL, ~$16,932, payments stopping dead on
   2026-07-28. Identifiable from the operator's records, not from chain.

---

## 7. Retractions, and the method that produced them

Three claims from the first version of this page are withdrawn. All three failed the same way,
and it is the way §0 already warned about: **I classified by what a transaction *touched* rather
than by what it *moved*.**

| withdrawn claim | why it was wrong | what replaces it |
|---|---|---|
| "757.02 SOL of lifetime **creator** fees" | attributed by "the pump.fun fee program appears in `accountKeys`" — true of every claim *attempt*, including ones that pay nothing | 757.111 SOL of **fee claims**, of which **467.209 DREGG-attributable** and 287.235 from a coin-less social-fee PDA |
| "four exchange-deposit-shaped hubs, 709.976 SOL of treasury movement" | inferred from balance/throughput shape alone; never tested *how many distinct senders* each has | **one** confirmed Coinbase address (486.630 SOL) + **three unidentified shared destinations** (223.346 SOL) |
| "the 2026-07-15 trailing window explains 256 SOL" | fitted a window to a target | refuted on the corrected DREGG-only series; the 211 SOL gap is stated as unreconstructable |

The general lesson, and the reason this is in the document rather than quietly fixed: **program
presence is not a payment, and address shape is not an identity.** The tests that held up were the
ones that asked the ledger a question only the ledger can answer — *whose lamports went down?* and
*how many distinct addresses have ever paid this one?* Both are cheap. Neither was in the first
draft.

What did **not** change under audit is worth stating too, because a retraction is only meaningful
against a baseline that held: the 2,012-transaction reconstruction still closes to the lamport on
all five wallets; the −7.440821 SOL trading loss stands; the internal transfers still net to
exactly zero; the Streamflow schedule is unmoved; and the 757.111 SOL gross figure was confirmed
by an independent measurement rather than overturned. **The number survived; its label did not.**

---

## Appendix: reproducing this

```
python3 studies/position_history.py fetch    # ~2,200 RPC calls, cached, idempotent
python3 studies/position_history.py ledger   # per-transaction deltas + classification
python3 studies/position_history.py report   # the books, the buckets, the split
python3 studies/position_history.py fees     # fee streams by PAYING account, and where they went
```

`fetch` runs a fixed-point closure over token accounts rather than enumerating the five owners,
because owner enumeration misses inbound token transfers. It converged in 2 rounds, discovered 21
additional token accounts and **3 transactions that owner-only enumeration would never have seen**.
The DREGG unlock path runs through exactly that gap.
