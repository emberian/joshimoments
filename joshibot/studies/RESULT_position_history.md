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
| c1 | **256 SOL** of lifetime creator fees | **WRONG by 2.96×** | **757.018737 SOL** claimed to `PmpDh2` over 266 claim transactions |
| c2 | Some creator fees are still unclaimed | **VERIFIED — none are** | every claim is swept within the hour; the wallet ends at 0.044 SOL |
| c3 | Realized creator take is 0.60% vs 0.81–1.19% of DREGG volume | **UNRECONSTRUCTABLE here** | this study measured fees, not volume. It does invert the check: 757 SOL implies $6.04M–$9.56M of lifetime DREGG volume |
| c4 | DREGG fees run **$213–313/day** | **VERIFIED for now, wrong as a lifetime rate** | August: 51.593 SOL / 14 days = **$279.38/day**, dead centre. June ran 221.9 SOL and July 483.6 SOL — the estimate was calibrated on the decayed regime |
| d | DREGG unlocks to `Dev2Gm` — never accounted anywhere | **NOW SIZED** | Streamflow escrow, **62,626,849.3125 DREGG locked (6.2635% of supply)**, 3 tranches of 1,204,362.4868 released = **$1,184.12**; **$19,340.67 still locked** |
| e | Net position and net PnL | **COMPUTED, identity closes to 1 lamport** | see §2 |

---

## 2. The household book — lifetime, all five wallets, in SOL

Every lamport that ever moved, assigned to exactly one bucket. The buckets sum to the live
balance by construction, so an unclassified flow cannot hide.

| bucket | shitcoims | tha funds | pumpfun main | Ember dev | og shitcoims | **TOTAL** |
|---|---|---|---|---|---|---|
| creator fees | — | — | +757.018737 | +1.128507 | — | **+758.147244** |
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

### 3a. Treasury movement — 709.976 SOL (91.5%), four addresses

| address | SOL | transfers | balance now | lifetime sigs |
|---|---|---|---|---|
| `Cbx3NneV…3HP3Eh` | 486.6299 | 137 | 0.0011 | 365 |
| `WYoLt8fH…uwYhB1` | 84.9968 | 25 | 0.1993 | 224 |
| `Drg3Mo7K…P6D2Dbq` | 82.3278 | 30 | 0.0193 | 313 |
| `6RTFsqEW…H5aXXn` | 56.0217 | 17 | 0.0168 | 1000+ |

All four have the same signature: a balance within a rounding error of zero, hundreds to
thousands of lifetime transactions, and an immediate forward of everything received. Sampling
`Cbx3NneV`'s recent history, it receives **essentially only from `pumpfun_main`** and forwards to
`2AQdpHJ2`, `D89hHJT5`, `4NyK1AdJ`, `FpwQQhQQ`. Two of those — `FpwQQhQQ` (**35,087.5 SOL**,
1,000+ sigs) and `F7p3dFrj` (**8,291.9 SOL**) — later *fund the trading wallet*.

That is the shape of an exchange deposit address and its matching hot wallet, and it closes a
loop: **money leaves `pumpfun_main` → hub → custody, and comes back into the trading wallets from
the hot wallets.** Ownership is not provable from chain and is not asserted here. What *is*
provable is the part that matters for the books: this is a treasury movement, not a gift, and
booking it as a discretionary distribution would overstate the giveaway by roughly 11×.

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

### (c) Creator fees — 757 SOL, not 256

**757.018737 SOL** arrived at `PmpDh2` from pump.fun creator-fee instructions, over **266 claim
transactions** spanning 49 active days (2026-06-27 → 2026-08-14). A further 1.128507 SOL of
creator fee reached `Ember dev`, so the household lifetime total is **758.147244 SOL ≈ $57,475**.

Creator fees do **not** arrive as a system transfer — the program reassigns lamports on a PDA
directly — so the parsed instruction stream shows nothing and only the balance delta records
them. Attribution is therefore by the instruction name the program itself logged:

| instruction set | txs | SOL |
|---|---|---|
| `ClaimSocialFeePda` + `DistributeCreatorFees` + `TransferCreatorFeesToPump` | 162 | 473.0962 |
| `ClaimSocialFeePdaV2` | 107 | 283.9625 |
| `ClaimFee` (Meteora, not pump.fun) | 1 | 0.0410 |

By month: **June 221.911, July 483.554, August 51.593.** The DREGG mint appears in 155 of the
claim transactions accounting for ~468.17 SOL; a second mint `5NFcUdd5…` accounts for ~3.95 SOL;
the 107 V2 claims name no mint in their account list.

**The 256 SOL figure is wrong by 2.96×.** One observation, offered as a lead and not a finding:
the running sum **from 2026-07-15 to now is 256.11 SOL**, which is what you would see if the UI
were showing a trailing window rather than a lifetime. Resolving that needs the UI, not the chain.

**Unclaimed: none, and chain agrees with the operator.** Every claim is swept within the hour and
`pumpfun_main` ends at 0.044 SOL.

**On the rate.** This study measured fees, not DREGG volume, so the 0.60%-vs-0.81–1.19% question
is **UNRECONSTRUCTABLE here**. It does invert usefully: 757 SOL of fees implies **126,170 SOL
($9.56M)** of lifetime DREGG volume at a 0.60% take, or **79,686 SOL ($6.04M)** at 0.95%.

**And it rescues PROGRAM.md §0's income model rather than breaking it.** August ran 51.593 SOL
over 14 days = 3.685 SOL/day = **$279.38/day**, sitting dead centre in the quoted $213–313/day.
That estimate is *correct for the current regime*. It is simply not a lifetime rate: extrapolating
it across 49 days gives ~$12k against an actual ~$57k, because June and July ran 4–9× hotter.
**The business was much larger than the document says, and is now much smaller than the document's
lifetime framing implies.** Both halves matter for planning.

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
| creator fees earned | +758.147244 | +$57,474.98 |
| LP fees earned | +12.913149 | +$978.94 (SOL leg only; token legs $850.72 more) |
| trading, all five wallets | **−32.453340** | **−$2,460.28** |
| LP principal (deposits − withdrawals) | −20.085769 | −$1,522.69 |
| moved to treasury/custody | −709.976 | −$53,823.14 |
| returned from custody | +46.85 (mostly) | +$3,551.86 |
| discretionary distributions | −66.2993 SOL + tokens | −$12,269.20 |
| gas | −0.124098 | −$9.41 |

**Net PnL, stated honestly.** The single number the brief asks for does not exist as a single
number, and saying so is the finding rather than a dodge. Two are defensible and they answer
different questions:

1. **Operating result, chain-only** — what the desk *earned* minus what it *lost trading*:
   `+758.147 (fees) + 12.913 (LP fees) − 32.453 (trading) − 20.086 (LP principal) − 0.124 (gas)`
   = **+718.397 SOL ≈ +$54,471**, plus $19,341 of locked DREGG. The business is the fee stream, at
   a 23× ratio over everything else on the page — exactly as PROGRAM.md §8 argues, and by a wider
   margin than it claims.
2. **Net worth change** is **not computable from chain**, because 709.976 SOL left for custody and
   46.85 SOL came back, and no on-chain evidence establishes what happened in between. Whether the
   $53,823 was spent, held as fiat, or lost off-chain is outside the tape. **Anyone quoting a net
   worth figure for this desk is quoting an assumption about those four addresses.**

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
6. **Why the pump.fun UI shows 256 SOL against 757 SOL on chain.** The 2026-07-15 suffix-sum
   coincidence is a lead, not an answer.

---

## Appendix: reproducing this

```
python3 studies/position_history.py fetch    # ~2,200 RPC calls, cached, idempotent
python3 studies/position_history.py ledger   # per-transaction deltas + classification
python3 studies/position_history.py report   # the books, the buckets, the split
```

`fetch` runs a fixed-point closure over token accounts rather than enumerating the five owners,
because owner enumeration misses inbound token transfers. It converged in 2 rounds, discovered 21
additional token accounts and **3 transactions that owner-only enumeration would never have seen**.
The DREGG unlock path runs through exactly that gap.
