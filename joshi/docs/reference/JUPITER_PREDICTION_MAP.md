# Jupiter prediction contracts, mapped for a base-rate study

Status: reconnaissance completed 2026-08-27. Read-only throughout. No order was constructed, serialized,
signed, or submitted, and no route classed MUTATING / ORDER-PLACEMENT was called. Every price, market
object, and on-chain account below came from an actual GET or `getAccountInfo`, or is explicitly marked
unverified.

This document answers one question Ember asked — *is there an honest, durable study to be had in the
"SOL up or down over 5m/15m" contracts, and against exactly what does the contract settle?* It answers
it by asking the product: the Jupiter Prediction API, the shipped resolution rules, and the Solana chain
the markets settle on. The make-or-break is the settlement reference, so that is nailed first.

The companion `docs/reference/PUMP_API_MAP.md` governs the method and the verdict discipline. Nothing
here has been written into `crates/joshi-pump-api/src/catalog.rs` or any other code; the tap proposal in
[§9](#9-proposal-what-joshi-would-tap-and-how) is a proposal.

---

## 0. The one thing to read first: two products wear the same clothes

There are **two distinct products** behind "Jupiter prediction," and Ember's framing ("Jupiter's native
SOL up/down") maps cleanly onto neither today. This is the first correction, and it changes the study.

| | **Forecast** (native) | **Predict** (aggregated) |
|---|---|---|
| Provider tag in API | `bisonfi` | `polymarket` (and Kalshi) |
| Market microstructure | Prop-AMM (Jupiter routes competing market-maker quotes) | Polymarket CLOB (order book, matched off-chain, mirrored to Solana) |
| On-chain state | market is a **PDA owned by the BISON program** (verified) | off-chain CLOB; only settlement/escrow touches Solana |
| Assets live **right now** (2026-08-27) | **Bitcoin only** — BTC Up/Down 5m & 15m | BTC, **SOL**, ETH, XRP … Up/Down 5m & 15m, plus all the event markets |
| Settlement reference | Chainlink **BTC/USD** data stream | for the crypto up/down rows: Chainlink **SOL/USD** (resp. BTC/ETH) data stream |
| Market id shape | `BISON-<marketPda>-UP` / `-DOWN` | `POLY-<n>-0` / `-1` |

**The consequence for the study, stated plainly:** the *thing Ember trades when she buys "Solana Up or
Down"* is, today, a **Polymarket-provided** contract surfaced inside Jupiter — not Jupiter's own
Prop-AMM. Jupiter's native (BISON) up/down is BTC-only at this snapshot. **Do not** assume a native
Jupiter SOL market exists on-chain to read; it does not yet.

**The good news that rescues the study:** both products settle a SOL up/down round against the **same
objective reference** — the Chainlink SOL/USD *data stream* — with the **same rule** (`close ≥ open ⇒
Up`). So the *study object* (the empirical base rate of "Chainlink SOL/USD higher after 5m/15m", and the
chop-vs-trend structure) is well-defined and reference-correct **regardless of which venue quotes the
contract**. Only the *mispricing/edge* half of the study is venue-specific, because implied probability
is a price and prices differ by venue. [§9](#9-proposal-what-joshi-would-tap-and-how) splits the study
along exactly that seam.

---

## Contents

1. [Method](#1-method)
2. [Verdict taxonomy](#2-verdict-taxonomy)
3. [Settlement mechanics, exactly](#3-settlement-mechanics-exactly)
4. [The fee and the edge floor](#4-the-fee-and-the-edge-floor)
5. [On-chain vs API — the answer, both surfaces](#5-on-chain-vs-api--the-answer-both-surfaces)
6. [Reading live price / implied probability](#6-reading-live-price--implied-probability)
7. [History: what can be reconstructed](#7-history-what-can-be-reconstructed)
8. [The reference price series for the study](#8-the-reference-price-series-for-the-study)
9. [Proposal: what JOSHI would tap, and how](#9-proposal-what-joshi-would-tap-and-how)
10. [What I did not verify; the mutating endpoints I did not touch](#10-what-i-did-not-verify-the-mutating-endpoints-i-did-not-touch)
11. [Counts](#11-counts)

---

## 1. Method

- **Docs read from the source of record.** The Jupiter developer docs (`developers.jup.ag/docs/prediction/*`,
  index at `dev.jup.ag/docs/llms.txt`) name the program ids, the market-id scheme, the Chainlink feed,
  and the fee model. These are treated as *found-in-docs* until an actual read confirms them.
- **The API was read live, keyless, read-only.** Base `https://api.jup.ag/prediction/v1`. `GET /events`,
  `/events/{id}`, `/events/search`, `/markets/{id}`, `/orderbook/{id}`, `/trading-status` all answered
  `200` with **no `x-api-key`** (the docs say the header is required; for reads it is not — `access-control-allow-origin: *`,
  Cloudflare-fronted). Requests were single-shot and small; this characterises a surface, it does not
  scrape a dataset.
- **The chain was read live, keyless, read-only.** Program ids, the config PDA, a live market PDA, and an
  outcome mint were confirmed with `getAccountInfo` against the **public** RPC
  `https://api.mainnet-beta.solana.com` (the Helius key was not needed and was not used for this pass).
- **The settlement rule was read out of the market object itself.** Each market's `rulesPrimary` field
  carries the human-readable resolution rule verbatim; that is the strongest available statement of what
  settles the contract, short of reading the program's resolve instruction.
- **Order placement was mapped, never exercised.** `POST /orders`, `/execute`, `/positions/{p}/claim`
  are ORDER-PLACEMENT/MUTATING; they are catalogued in [§10](#10-what-i-did-not-verify-the-mutating-endpoints-i-did-not-touch)
  and were not called.

---

## 2. Verdict taxonomy

- **VERIFIED-LIVE** — confirmed this pass by an actual GET or `getAccountInfo`. Reproducible now.
- **DOC** — stated in Jupiter's own developer docs; not independently re-derived here.
- **DOC+LIVE** — stated in docs *and* corroborated by a live read.
- **DERIVED** — computed here from verified data (e.g. the fee constant fit to the published table).
- **UNVERIFIED** — plausible, found somewhere, but not grounded. Never promoted.

---

## 3. Settlement mechanics, exactly

**One-paragraph version.** A round is a fixed wall-clock window (300 s or 900 s, its `openTime`/`closeTime`
being exact unix multiples of 300 s — VERIFIED-LIVE). Two outcome tokens exist, **Up** and **Down**, each
a Token-2022 mint worth **$1 if it wins and $0 if it loses**. The round resolves **Up** iff the reference
asset's price *at the end of the window* is **greater than or equal to** its price *at the start*;
otherwise **Down**. **Exact equality resolves Up** — Up is the tie-inclusive side, Down is strict-below
(VERIFIED-LIVE from `rulesPrimary`). The reference is the **Chainlink data stream** for that asset
(BTC/USD for the native BISON markets; SOL/USD for the SOL up/down rows), *"not according to other
sources or spot markets"* — the rule text is emphatic on this point. Settlement is on-chain; a winning
Token-2022 balance is redeemable 1:1 for the deposit stablecoin (USDC) with **no claim fee**.

### The exact rule text, quoted (VERIFIED-LIVE)

Native BTC round (`marketPda z5ShV5A4UNxCAGhFVGjsRPfgzVfXFmTYtpjthrsDoNm`, provider `bisonfi`):

> "This market will resolve to \"Up\" if the Bitcoin price at the end of the time range specified in the
> title is greater than or equal to the price at the beginning of that range. Otherwise, it will resolve
> to \"Down\". The resolution source for this market is information from Chainlink, specifically the
> BTC/USD data stream available at https://data.chain.link/streams/btc-usd. Please note that this market
> is about the price according to Chainlink data stream BTC/USD, not according to other sources or spot
> markets."

SOL round (`POLY-3337747-*`, provider `polymarket`) — identical rule, SOL feed:

> "This market will resolve to \"Up\" if the Solana price at the end of the time range … is greater than
> or equal to the price at the beginning of that range. Otherwise … \"Down\". The resolution source … is
> Chainlink, specifically the SOL/USD data stream available at https://data.chain.link/streams/sol-usd …
> not according to other sources or spot markets."

### The window (VERIFIED-LIVE)

- `openTime`, `closeTime` are **unix seconds**. Observed windows: 5m round `1787897700 → 1787898000`
  (Δ = 300 s); 15m round `1787881500 → 1787882400` (Δ = 900 s). Both endpoints are exact multiples of
  300 s → **anchored to the wall-clock 5-minute grid**, matching the ET titles ("9:30AM–9:45AM ET").
- The window is anchored by these timestamps, not by block height. The open/close reference prices are
  the Chainlink stream values *at those two instants*. The precise snapshot mechanism (nearest report at
  or before the boundary) is **UNVERIFIED** — it is not documented and I did not decode a resolve
  transaction. For a study this matters at the sub-second margin only; see [§8](#8-the-reference-price-series-for-the-study).

### "Up" definition and ties (VERIFIED-LIVE)

- **Up wins** iff `price_close ≥ price_open`. **Down wins** iff `price_close < price_open`.
- **Ties (exact equality) → Up.** There is no push / no refund / no half-resolution on the crypto
  directional rows. (The *event* markets — sports etc. — do carry "resolve 50-50" clauses; the crypto
  up/down rows do not.)

### Payout (DOC+LIVE)

- Each outcome is a **Token-2022 mint** (`outcomeMint`, program `TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb`,
  VERIFIED-LIVE owner) worth **exactly $1 if it wins, $0 if it loses**.
- Deposit / settlement stablecoin: **USDC** `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` (DOC; JupUSD
  `Juprjzn…USD` is also accepted on the aggregated side). Winning tokens **settle automatically, no claim
  fee** (DOC). Per-order size band via the Prediction API: **5–250 USDC** (DOC).
- Terminal-price evidence of a resolved SOL round (VERIFIED-LIVE): the winning side's `buyYesPriceUsd`
  had converged to `1000000` (=$1.000000, prices are **micro-USD**) and the losing side to `1000`
  (=$0.001).

---

## 4. The fee and the edge floor

This number is central to every edge calc, so it is derived, not asserted.

**The published fee table** (DOC, `developers.jup.ag/docs/prediction`), fee charged **only on executed
buys/sells**, **rounded up to the nearest cent**, **no claim/settlement fee**:

| price/contract | fee, 1 contract | fee, 100 contracts |
|---|---|---|
| $0.01 | $0.01 | $0.07 |
| $0.05 | $0.01 | $0.34 |
| $0.10 | $0.01 | $0.63 |
| $0.15 | $0.01 | $0.90 |
| $0.20 | $0.02 | $1.12 |
| $0.25 | $0.02 | $1.32 |
| $0.30 | $0.02 | $1.47 |
| $0.35 | $0.02 | $1.60 |
| $0.40 | $0.02 | $1.68 |

**The fee formula (DERIVED).** Dividing the 100-contract column by 100 and regressing against `p(1−p)`
gives a constant of **0.070 ± 0.001** across every row:

```
fee_per_contract ≈ 0.070 · p · (1 − p)      (dollars, before the round-up-to-cent)
```

This is an *uncertainty* rake: it is maximised at `p = 0.5` and vanishes at the certain ends. Evaluated
at the coin-flip midpoint the table does not reach:

```
fee(p=0.5) ≈ 0.070 · 0.25 = $0.0175 per contract  =  1.75% of the $1 payout
```

**So the explicit-fee edge floor near a genuine 50/50 SOL round is ≈ 1.6–1.75¢ per $1 contract.** Two
riders make the *real* floor higher:

1. **The round-up-to-cent dominates small/cheap orders.** At $0.01 a single contract costs a $0.01 fee —
   **100% of price**. Cheap-tail sniping (the "both sides keep printing cheap" intuition) is exactly
   where the cent-floor rake is most punishing per dollar risked. A base-rate edge in the tails must
   clear a *much* larger relative fee than the 1.75% midpoint.
2. **Spread + overround sit on top of the explicit fee.** Live SOL 15m round (`POLY-3902106`, VERIFIED-LIVE):
   the two sides quoted `buyYes 0.17 / sellYes 0.16` and `buyYes 0.84 / sellYes 0.83` — a **1¢ bid/ask
   spread per side**, and the two **buy** legs sum to **$1.01** (a **~1% overround** — buying both sides
   to lock $1 costs $1.01).

**Working edge floor to overcome, per $1 SOL contract near the middle:** explicit fee (~1.3–1.75¢) +
half-spread (~0.5¢) + the overround share ⇒ **on the order of 2–3.5¢ (2–3.5%)** round-trip-equivalent.
A base-rate mispricing must beat *that*, not just be nonzero. (VERIFIED-LIVE spread/overround; DERIVED
composition.)

---

## 5. On-chain vs API — the answer, both surfaces

**Both exist, and they are complementary.** The API is the easy live read; the chain is the honest,
durable, backfillable read — and for the **native BISON** markets the market state genuinely lives
on-chain.

### 5a. The REST API (VERIFIED-LIVE, keyless for reads)

Base `https://api.jup.ag/prediction/v1`. Read routes exercised this pass:

| route | verdict | what it gives |
|---|---|---|
| `GET /events?…&includeMarkets=true` | VERIFIED-LIVE | event + embedded market objects; filterable |
| `GET /events/{eventId}` | VERIFIED-LIVE | one event, hydrated with its markets |
| `GET /events/search?query=…` | VERIFIED-LIVE | keyword search (does **not** hydrate `markets[]`) |
| `GET /markets/{marketId}` | VERIFIED-LIVE | one market's pricing + status |
| `GET /orderbook/{marketId}` | VERIFIED-LIVE | full depth ladder `{yes:[[price¢,size]…], no:[…]}` |
| `GET /trading-status` | VERIFIED-LIVE | `{"trading_active":true}` |
| `GET /positions?ownerPubkey=…` | DOC | a wallet's open positions |

Useful filters (DOC+LIVE): `provider=bisonfi` isolates native forecast; `category=crypto`; `tag=5m` /
`tag=15m`; `includeMarkets=true`. The default `/events` feed is dominated by Polymarket event markets;
**you must filter to find the directional rounds**, and the 5m/15m rounds are **ephemeral** — `pricing`
is `null` until a round enters its live window (`tradable` flips true), so you *poll* to catch a live one
("Rounds are scheduled by the issuer rather than rotating continuously, so poll /events" — DOC, confirmed:
every round I sampled outside its window had `pricing: null`).

**The market object shape (VERIFIED-LIVE), native BISON:**
`marketId, marketPda, oracle, outcomeMint, outcomeSide ('up'|'down'), sideLabel, outcomeTokenProgram,
lifecycleStatus, tradable, status, result (null|…), openTime, closeTime, resolveAt, marketResultPubkey,
rulesPrimary, marketOptions, title, imageUrl`. (`oracle` was `null` in every open-round embed sampled —
it appears to populate on/after resolution; UNVERIFIED.) **Polymarket** market objects carry a *different*
key set — `clobTokenIds, outcomes, sportsMarketType, team, …` and **no** `marketPda`/`outcomeMint` — which
is the API-level tell that a SOL up/down row is CLOB-backed, not BISON-backed.

Prices are **micro-USD** integers (`650000` = $0.65) and **price = implied probability** (DOC+LIVE):
`buyYesPriceUsd, sellYesPriceUsd, buyNoPriceUsd, sellNoPriceUsd, volume`.

### 5b. The Solana program layer (VERIFIED-LIVE)

The native forecast markets are a real deployed program with real per-market accounts. Confirmed this
pass via `getAccountInfo` on the **public** RPC:

| account | address | verified fact |
|---|---|---|
| BISON issuer program | `2sVcg2dBSUzXkmdZ8M5cp1LbnzDrWJmr6hktkHwB8nY3` | `executable: true`, owner `BPFLoaderUpgradeab1e…` |
| Config PDA | `8LczfBkVZJhGnTYH8nQke2YC3b83GFZ8qZtfuMRe6AN6` | owned by the issuer program, 115-byte data |
| A live market PDA | `z5ShV5A4UNxCAGhFVGjsRPfgzVfXFmTYtpjthrsDoNm` | **owned by the issuer program, 676-byte data** |
| An outcome mint | `7cZFffWmiDZLxrxPEtUT1TaAyQ2uJfYnAKkDcGmy8pv8` | owner Token-2022 `TokenzQdB…`, 456-byte data |

That the **market is a 676-byte PDA owned by the BISON program** is the load-bearing finding for "the
honest durable path": JOSHI can enumerate live and settled markets with `getProgramAccounts(2sVcg2dB…)`
and read any single one with `getAccountInfo(marketPda)`, and can walk the program's history with
`getSignaturesForAddress(2sVcg2dB…)` → `getTransaction`. The 676-byte layout (open/close prices, result,
window bounds, mints) is **not yet decoded** — that is the one piece of net-new on-chain work, and it is
exactly the `crates/joshi-sources/src/meteora.rs` pattern (owner + discriminator + fixed-offset decode).

**The asymmetry to remember:** this on-chain richness is **BISON-only (BTC today)**. The SOL up/down rows
are Polymarket CLOB — matched off-chain, so there is *no per-round market PDA to read*; only escrow /
settlement touches Solana, and `result`/`marketResultPubkey` were `null` even on a long-settled SOL round
(the outcome had to be *inferred from terminal price*, $1.00 vs $0.001). So for **SOL specifically**, the
API is the primary live read and the chain gives you far less than it does for BTC.

---

## 6. Reading live price / implied probability

- **Cheapest read:** `GET /markets/{marketId}` → `pricing.buyYesPriceUsd / 1e6` **is** the implied
  probability of that side, live. For a two-sided view, read both `-UP` and `-DOWN` (BISON) or `-0` and
  `-1` (POLY). VERIFIED-LIVE.
- **Depth read:** `GET /orderbook/{marketId}` → `{yes, no}` ladders of `[price_in_cents, size]`. VERIFIED-LIVE
  (the SOL round returned a full ladder of ~75 levels per side). This is what feeds a fill-aware edge
  calc rather than a top-of-book one.
- **Discovery for a live SOL round:** `GET /events/search?query=Solana Up or Down` → take the row whose
  window straddles now → `GET /events/{eventId}` to hydrate `markets[].marketId` → read pricing/orderbook.
  VERIFIED-LIVE end-to-end (captured `Up 0.17 / Down 0.84` on a live 15m round).

---

## 7. History: what can be reconstructed

**Short answer: outcomes are reconstructable; contract *prices* over time are essentially not — they need
live collection.**

- **API history is thin.** `/events` surfaces near-live rounds plus a modest recent tail; there is no
  documented "give me all rounds since date T with their settlement" endpoint. The 5m/15m rounds are
  ephemeral and `pricing` is only populated inside the live window. **So the implied-probability path of
  each round is not retrievable after the fact via the API — it must be captured live, in-window.** This
  is the binding constraint on the mispricing half of the study.
- **On-chain history is real — for BISON/BTC.** `getSignaturesForAddress(2sVcg2dB…)` → `getTransaction`
  reconstructs every round the program ever ran, and `getProgramAccounts` enumerates market PDAs whose
  bytes carry the result and (probably) the open/close reference prices. This is the durable, honest,
  backfillable base-rate-of-*outcomes* source. **It does not recover the intra-round price path** (the
  AMM quotes) unless those were also posted on-chain per trade — UNVERIFIED, likely partial.
- **On-chain history for SOL/POLY is weak.** No per-round market PDA; outcomes must be inferred from
  terminal API price or from Polymarket's own resolution feed. Treat SOL outcome history as **needing
  live collection** unless a Polymarket historical source is brought in.

**Verdict on feasibility:** a **base-rate-of-outcomes** study for SOL is fully possible **from the
reference series alone** (§8) — you do not need the contract's history to know how often Chainlink SOL/USD
was higher after 5m/15m. The **implied-probability-vs-base-rate (mispricing)** study **needs live
collection over time**, because contract prices are not durably retrievable.

---

## 8. The reference price series for the study

This is the make-or-break, so it gets its own caution.

**The exact settlement reference is the Chainlink SOL/USD *Data Stream*** — product name
`SOL/USD-RefPrice-DS-Premium-Global-003`, canonical page `https://data.chain.link/streams/sol-usd`. The
feed id renders on Chainlink's UI as `0x0003…c24f` (**the full 32-byte id was not captured this pass** —
UNVERIFIED-COMPLETE; pull it from the Chainlink Data Streams verifier/API at implementation time). For
reference, the BTC stream's full id is documented as
`0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8` (DOC).

**The trap that would ruin the study — Streams ≠ Feeds:**

- **Chainlink Data *Streams*** (what settles the contract) are **pull-based**: off-chain, signed,
  sub-second reports fetched on demand. The report value *at `openTime`* and *at `closeTime`* is the
  settlement price.
- **Chainlink Data *Feeds*** on Solana (a price account readable with `getAccountInfo`) are a **different
  object**: push-based, updated on a deviation/heartbeat schedule (seconds-to-minutes granularity). Using
  the on-chain *feed* as the base-rate reference would measure a **coarser, laggier** price than the one
  that settles — a wrong-reference study, precisely the failure mode the brief warns against ("a study
  against the wrong reference is worse than none").

**So the reference series must be the Data Stream, and JOSHI has three honest ways to get it:**

1. **Reconstruct the exact settlement prices from chain (best for BISON/BTC).** The BISON resolve
   transaction / market PDA very likely records the open and close stream values it settled on. Decode
   the 676-byte market PDA and/or the resolve tx (`getTransaction`) and you have the *exact* pair the
   protocol used — ground truth, no approximation. UNVERIFIED that the bytes contain both prices; this is
   the first thing to check when the layout is decoded. **This path does not exist for SOL/POLY.**
2. **Capture the Data Stream live going forward (the durable path for SOL).** Subscribe to / poll the
   Chainlink Data Streams report for SOL/USD and retain a report at each round boundary. This is net-new
   (JOSHI has **no Pyth/Chainlink stream reader today** — confirmed absent) but rides the existing
   `RetainingSession` / `reqwest` retention pattern. It is the only way to get a settlement-exact SOL
   series, and it only accrues from turn-on.
3. **Chainlink Data Streams historical API (retrospective SOL).** Chainlink offers historical report
   retrieval, but it is credentialed (Data Streams API access). Flag as a dependency, not a given.

**What is collectable now vs needs time:**
- *Now, retrospective, settlement-exact:* BISON/BTC outcomes and (pending layout decode) their reference
  prices, from chain.
- *Now, retrospective, approximate:* a SOL/USD series from any spot/aggregator source — **only for
  scoping/feasibility, never for the headline base rate**, because it is not the settlement object.
- *Needs live collection over time:* settlement-exact **SOL** reference series (Streams), **and** all
  contract implied-probability paths (both assets).

---

## 9. Proposal: what JOSHI would tap, and how

The study splits cleanly into three deliverables along the seam identified in §0. Each is mapped to
existing JOSHI machinery so this is an extension, not a greenfield.

### The existing machinery this rides on (from the infra recon)

- **Fetch/retain envelope:** `FetchOutcome` (`crates/joshi-pump-api/src/model.rs`) — the exact
  `{attempts:[{sourceLocator, body:{bytesBase64}}]}` JSON that `analysis/.../signature.py::bars_from_outcome`
  and `workability/reads.py::body_of_outcome` already decode. Any Jupiter GET retained in this shape is
  immediately consumable by the Python side.
- **Keeper cadence:** `apps/collector/src/keeper.rs` — an in-process 30 s-tick loop of per-tap cadences
  (`TapKind` enum), budgets, backoff, heartbeat, and a `hot-requests.json` escalation seam from
  `apps/core`. A new tap kind fits here.
- **On-chain reads:** `crates/joshi-sources/src/helius.rs` — hand-rolled JSON-RPC over Helius/public RPC,
  with `SolanaReadMethod::{GetAccountInfo, GetMultipleAccounts, GetProgramAccounts, GetSignaturesForAddress,
  GetTransaction}` already enumerated. Account decoders live beside it (`meteora.rs` is the template).
  Python mirror: `analysis/.../lpdesk/rpc.py::RetainingSession` (key at `~/.helius-key`).
- **Study module pattern:** `analysis/src/joshi_analysis/<study>/` with `contracts.py` (frozen dataclasses,
  invariant-checked), `reads.py` (decode retained outcomes), `study.py` (pure compute), `__main__.py`,
  `STUDY.md`, tests under `analysis/tests/<study>/`. `wave6_routed_shadow/contracts.py` already defines a
  `JupiterWitness` contract to extend.
- **The chop instrument already exists:** `analysis/src/joshi_analysis/signature.py` computes σ²(τ) =
  V(τ)/(τ·p̄²) in both event-time and wall-time (`signature_event`, `signature_wall`, lags out to 900 s).
  A **falling** σ²(τ) is net mean-reversion (chop); a **rising** curve is trend. This *is* the
  chop-vs-trend instrument the brief asks for — point it at the SOL/USD reference series, no new math.

### Deliverable (a) — empirical base rate P(up) and the return distribution

- **Source:** the settlement-exact SOL/USD reference series (§8). Collectable *now, retrospectively and
  exactly* only for BTC (from chain); for SOL, start live capture (path §8.2) and/or use the credentialed
  historical Streams API (§8.3). A spot-approximate SOL series may scope the shape but must not be the
  headline.
- **Compute:** over a rolling grid of 300 s and 900 s windows aligned to the 5-minute wall-clock grid
  (matching how rounds are anchored), tabulate `P(close ≥ open)` (ties → Up, per the rule) and the full
  distribution of `log(close/open)`. New module `analysis/src/joshi_analysis/jupiter_base_rate/`.
- **What it answers:** is P(up) actually ≈ 0.5, or is there a drift/asymmetry a naive both-sides trader is
  paying into? And how fat are the tails that make "both sides print cheap."

### Deliverable (b) — implied-probability vs base rate (the mispricing edge, net of fee)

- **Source:** **must be collected live** (§7). A **keeper tap** — propose `TapKind::JupiterForecast` — that,
  during each live round, polls `GET /markets/{id}` (both sides) and `GET /orderbook/{id}` on a fast
  cadence (**~10–15 s**, well inside the gentle-cadence floor for a market that only lives 5–15 min),
  retaining each response as a `FetchOutcome` into `state/studies/jupiter-forecast/<asset>/<round>/`. The
  tap discovers live rounds via `GET /events?provider=bisonfi&tag=5m|15m` (BTC) and
  `GET /events/search?query=Solana Up or Down` (SOL), then follows each round's ids to `closeTime`.
- **Compute:** for each round, align the retained implied-probability path against the realised outcome;
  estimate calibration (does a 0.30 contract win ~30% of the time?) and the sign/size of any systematic
  mis-pricing, **net of the §4 edge floor** (fee `0.070·p(1−p)` + spread + overround). Report edge only
  where it clears the floor with margin.
- **Reality check to state up front:** because prices aren't retrievable after the fact, (b) *only accrues
  from turn-on* — it is a live-collection study with a warm-up, not a backfill.

### Deliverable (c) — chop-vs-trend structure via σ²(τ)

- **Source:** the same SOL/USD reference series as (a).
- **Compute:** run the **existing** `signature.py` over the series; read σ²(τ) at τ = 300 s and 900 s
  against shorter lags. The trade thesis ("5/15m SOL is choppy so both sides keep printing") predicts a
  **falling** σ²(τ) (mean reversion) at those horizons; the instrument confirms or refutes it directly and
  ties the microstructure claim to the base rate in (a).

### The catalog / tap changes, as a proposal (not written)

JOSHI's route catalog (`crates/joshi-pump-api/src/catalog.rs`, the `RouteId`/`RouteSpec` model:
`origin, path_template, access, stability, transport, pagination, allowed_query, sensitive_query,
collection_enabled`) is pump.fun-specific by origin. **Do not shoehorn Jupiter into it.** Instead:

1. **A parallel read-only route catalog** for `origin = https://api.jup.ag/prediction/v1`, same `RouteSpec`
   shape, GET-only by construction. Routes: `Events`, `EventById`, `EventsSearch`, `MarketById`,
   `Orderbook`, `TradingStatus`, `Positions`. Classify all as `ObservedPublicProduct` / `UndocumentedObserved`
   (the docs call the API beta). **The order routes do not go in the catalog at all** — the catalog holds
   only reads (see §10).
2. **Pinned on-chain program constants** beside the existing `PUMP_PROGRAM`/`PUMPSWAP_PROGRAM` in
   `apps/collector/src/census.rs`: `BISON_ISSUER_PROGRAM = "2sVcg2dB…"`, `BISON_CONFIG_PDA = "8LczfBk…"`,
   `OUTCOME_TOKEN_PROGRAM = "TokenzQdB…"`.
3. **A market-PDA decoder** in `crates/joshi-sources/` following `meteora.rs` (owner-check + discriminator +
   fixed-offset decode of the 676-byte market account) — the one genuinely new on-chain artifact, and the
   thing that unlocks settlement-exact BTC history and confirms whether the open/close reference prices
   live in the account.
4. **A `TapKind::JupiterForecast` keeper tap** for deliverable (b)'s live capture, cadence ~10–15 s inside
   live windows, retaining `FetchOutcome` envelopes.
5. **A Chainlink SOL/USD Data-Stream reader** (net-new; no Pyth/Chainlink reader exists today) for §8.2 —
   the only route to a settlement-exact SOL reference series going forward.

---

## 10. What I did not verify; the mutating endpoints I did not touch

**Deliberately not called — ORDER-PLACEMENT / MUTATING (mapped, never exercised):**

- `POST /prediction/v1/orders` — builds an order (returns an unsigned transaction). Even unsigned, this is
  order construction; not called.
- `POST /prediction/v1/execute` — submits a signed order. Not called.
- `POST /prediction/v1/positions/{positionPubkey}/claim` — builds the payout/redeem transaction. Not
  called.
- The on-chain **BISON program instructions** (buy/sell/resolve/claim). The program id is mapped; no
  instruction was constructed or sent.

**Not verified this pass (honest gaps):**

- **The full Chainlink SOL/USD Data-Stream feed id** — only the UI-truncated `0x0003…c24f` was captured
  (chain.link rate-limited the full page). Pull the complete id from the Data Streams verifier/API before
  any code depends on it.
- **The 676-byte market-PDA byte layout** — not decoded. Whether it stores the open/close reference prices
  (the §8.1 ground-truth path) is therefore UNVERIFIED.
- **The exact stream-snapshot rule at a boundary** — nearest-report-at-or-before vs interpolated is not
  documented and not decoded.
- **The `oracle` field's populated value** — it was `null` in every open-round embed; its post-resolution
  contents are unknown.
- **`GET /positions`** — documented, not exercised (would require a wallet pubkey; read-only but out of
  scope for a price/mechanics map).
- **JupUSD vs USDC settlement differences**, and whether the native BISON side ever accepts JupUSD — not
  probed.
- **Live BISON *pricing/spread*** — no BISON round was inside its tradable window at poll time, so all
  live spread/overround numbers in §4 come from the **SOL (POLY)** round. BISON Prop-AMM spreads may
  differ; re-measure in-window before trusting a BTC edge floor.
- **Geo:** the API answered from this location; the docs note US/South-Korea IP restrictions on the app.
  The read API did not enforce them this pass, but a production tap should not assume that holds.

---

## 11. Counts

- API read routes exercised live: **6** (`/events`, `/events/{id}`, `/events/search`, `/markets/{id}`,
  `/orderbook/{id}`, `/trading-status`). Order/mutating routes mapped and **not** called: **3** (+ the
  on-chain program instructions).
- On-chain accounts verified via `getAccountInfo` (public RPC, keyless): **4** (issuer program, config
  PDA, a market PDA, an outcome mint).
- Settlement rule quoted verbatim from live market objects: **2** (BTC/BISON, SOL/POLY) — identical rule,
  different Chainlink feed.
- Program ids pinned (VERIFIED-LIVE): issuer `2sVcg2dBSUzXkmdZ8M5cp1LbnzDrWJmr6hktkHwB8nY3`; config PDA
  `8LczfBkVZJhGnTYH8nQke2YC3b83GFZ8qZtfuMRe6AN6`; outcome-token program (Token-2022)
  `TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb`; USDC mint `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`.
- Fee constant (DERIVED): `fee ≈ 0.070·p(1−p)` per contract; midpoint ≈ **1.75%** of $1; real edge floor
  with spread+overround ≈ **2–3.5%** near a 50/50 round.
- Net-new artifacts the study needs: **1** on-chain (676-byte market-PDA decoder) + **1** off-chain
  (Chainlink SOL/USD Data-Stream reader) + **1** analysis module (`jupiter_base_rate/`) + **1** keeper tap
  (`JupiterForecast`). The chop instrument (`signature.py`) is reused as-is.
