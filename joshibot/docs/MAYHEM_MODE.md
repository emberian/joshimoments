# MAYHEM MODE — the mechanism, measured

2026-08-29, mayhem recon deputy. Every claim is tagged **[VERIFIED-LIVE]** (measured this
session against chain/live API/retained frames, method stated), **[DOC-ONLY]** (a published
source, cited, not independently confirmed), or **[INFERRED]** (our reading of verified
facts; could be wrong in stated ways). The statistical questions (rip rates, gate
separation within the stratum) belong to `studies/REGISTRATION_mayhem_arm.md` and are NOT
answered here; §7 flags what this recon changes about that registration.

Case-study coin used throughout: `4WrjfJXMSJnWgxFhzCvNRtTVLAfzXL3Zmf4413aqpump`
(created 2026-08-29 11:07:00 UTC, curve `CS4U7DFbcwmLxmwvgqcJtoMEzvatMfXJvhZfobxCHGQR`),
full 31-transaction tape decoded from chain. Cross-sections: all 87 retained WS create
frames of 2026-08-29 (32 mayhem), curve accounts of all 32 mayhem + 20 standard mints,
4 three-day-old mayhem mints from the fresh corpus, `state/boards/` 2026-08-14..23.

---

## 1. The mechanism in one paragraph

Mayhem mode is a per-coin, opt-in-at-creation flag (`create_v2(..., is_mayhem_mode: true)`,
Token-2022 mandatory) that mints **2×10¹⁵ raw (2 billion tokens, 6 decimals)** instead of
the standard 1e15: one billion funds the **completely standard bonding curve** (seeds
1.073e15 / 30 SOL, verified to the raw unit at birth), and the second billion goes to a
per-coin **Token-2022 vault owned by a separate pump-operated "Mayhem" program**
(`MAyhSmzXzV1pTf7LsNkrNwkWKTo4ougAJ1PPg47MD4e`). For exactly **86,400 seconds** an
AI agent operated by pump trades the coin fee-free out of that vault — and, critically,
its trades carry an **administrative rewrite of the curve's virtual SOL reserves**: in the
case tape each agent trade moved `virtual_sol_reserves` by roughly **500× its real SOL
size**, so the quoted price during the first 24h is *administered volatility*, not
discovered price — the constant product `k` is not constant on these coins (measured
`k/k_std` from 0.0023 to 4.87 across 19 live mayhem curves, while 18/18 standard curves
sat exactly at `k_std`). At window end the vault's unsold tokens (and apparently
agent-repurchased tokens) are **burned**; observed 3-day-old mayhem supplies are
0.85–1.01e15, their real SOL reserves exactly 0. Everything the validated screen assumes
about a pump coin's price path — `k = 3.219e25`, log-price affine in curve balance,
market-cap thresholds meaning real money — is false by construction inside the 24h window.

## 2. The product [DOC-ONLY except where noted]

- **Name/pitch**: "Mayhem Mode" — pump.fun's opt-in launch setting where an autonomous AI
  trading agent buys and sells the new coin during its first 24 hours, marketed as faster
  "early price discovery"; extra 1B tokens minted for the agent, unused agent tokens
  burned after 24h; agent has trade size/frequency caps and pays no protocol fees.
  [DOC-ONLY: The Block 2025-11-18; CryptoRank/Cryptopolitan launch coverage. The fee
  exemption and burn are independently **[VERIFIED-LIVE]** below.]
- **Launch date**: announced ~**2025-11-11/12** (X trending item timestamp 2025-11-11
  18:59 UTC; The Block's 11-18 piece says "last week"). [DOC-ONLY]
- **Opt-in per coin**: yes — an explicit `is_mayhem_mode: bool` argument on `create_v2`,
  plus a global `mayhem_mode_enabled` kill-switch in pump's `Global` account (currently 1).
  Cannot be toggled after creation (no such instruction exists in the IDL).
  [VERIFIED-LIVE: official IDL + decoded `Global` account]
- **Two modes**: pump's own overview reports `coinsCreatedByMode: auto 8,678 / manual
  2,188` per 24h and the per-coin object carries `mode: "auto"|"manual"`. Semantics of
  "manual" (creator-driven agent?) unverified. [VERIFIED-LIVE that the field and split
  exist; INFERRED what manual means]
- **Adoption, dated from our own data** — the share was small in early August 2026 and is
  now a third of the market:
  - 2026-08-05: 2e15-births were not separately tallied, but ALL "other positive"
    first-tx nets were 8,746 of 66,316 traded mints (≤13.2% bound, described as "mostly
    1e18 seeds") — mayhem was at most a modest slice then. [VERIFIED from
    `studies/RESULT_operator_crime.md` §3 census]
  - 2026-08-26/27/28 (fresh corpus `birth.parquet`, first-tx net exactly 2e15): 10,700 /
    10,395 / 9,736 mayhem births = **24.3% / 21.5% / 22.7%** of standard+mayhem births.
    [VERIFIED-LIVE, coarse; the registered M1 census owns the definitive number]
  - 2026-08-29 live: **32/87 = 36.8%** of retained WS create frames; screen telemetry has
    ranged 28–44%. Pump's own `/mayhem/overview`: **10,866 mayhem coins created in 24h**,
    agent volume $7.0M/24h, 94 currently active. [VERIFIED-LIVE]

## 3. Supply, curve, constants

| Constant | Standard coin | Mayhem coin | Verdict |
|---|---|---|---|
| Minted at create | 1e15 raw | **2e15 raw** (`getTokenSupply` = 2,000,000,000,000,000; hydration measured 10/10 earlier) | VERIFIED-LIVE |
| Decimals | 6 | 6 | VERIFIED-LIVE |
| Token program | SPL Token (legacy `create`) / Token-2022 (`create_v2`) | **Token-2022 always** (`create_v2` only) | VERIFIED-LIVE |
| Curve seed vTok | 1,073,000,000,000,000 | **same** | VERIFIED-LIVE (Global acct + CreateEvent + fill math) |
| Curve seed vSol | 30,000,000,000 lamports | **same at birth** | VERIFIED-LIVE (dev-buy fill reproduces standard math to the raw unit) |
| Curve seed real tokens | 793,100,000,000,000 | **same** | VERIFIED-LIVE |
| Curve struct `token_total_supply` | 1e15 | **1e15 — the curve does not know about the second billion** | VERIFIED-LIVE (account bytes) |
| Second 1e15 | — | per-coin Token-2022 vault under the Mayhem program (case coin: `drUTwRM4yGfYVuBpDAZvjPdyL95Mz2XPyivNq9oieMG`); balance = 1e15 − net agent-sold, reconciles the curve vault to the raw unit | VERIFIED-LIVE |
| `k` after birth | invariant 3.219e25 | **NOT invariant** — rewritten inside agent trades; measured k/k_std ∈ [0.0023, 4.87] over 19 live coins; 3 more still standard (agent not yet acted) | VERIFIED-LIVE |
| Protocol fee | 95 bps on trades (fee tiers exist, not measured here) | 95 bps for humans, **0 bps for the agent** | VERIFIED-LIVE (TradeEvent `fee_basis_points`) |
| Creator fee | 5 bps (Global) | same field; not separately measured | VERIFIED-LIVE (decoded), semantics DOC-ONLY |
| Agent window | — | **exactly 86,400 s** (`mayhem-state`: end_time = start_time + 86,400) | VERIFIED-LIVE |
| End-of-window burn | — | unsold vault tokens burned; observed 3-day-old supplies 1.0148e15, **0.8519e15 (below 1e15!)**, 0.9766e15, 0.9886e15 — the burn can exceed the vault seed, i.e. tokens the agent bought back burn too | VERIFIED-LIVE (n=4); "burn after 24h" also DOC-ONLY |
| Graduation | real_token_reserves → 0, `complete=1`, ≈411 SOL peak / ≈85 SOL raised | same predicate mechanically, but **no fixed SOL-at-graduation** — the path is administered | predicate VERIFIED (IDL unchanged); economics INFERRED |
| Key addresses | — | program `MAyhSmzXzV1pTf7LsNkrNwkWKTo4ougAJ1PPg47MD4e`; sol-vault PDA (seed `"sol-vault"`, the agent's on-curve identity) `BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s`; global-params PDA `13ec7XdrjF3h3YcqBTFDSReRcUFwbCnJaAQspM4j6DDJ`; per-coin `mayhem-state` PDA seeds `["mayhem-state", mint]` | VERIFIED-LIVE |

**How the rewrite happens.** The pump program itself exposes
`set_mayhem_virtual_params` (signer: `sol_vault_authority`, no args) and emits
`UpdateMayhemVirtualParamsEvent{virtual_*_reserves, new_virtual_*_reserves, ...}`
[VERIFIED: official IDL]. In the case tape no standalone rewrite event appears — the
re-marks ride *inside the agent's trades*: each agent buy/sell moves `virtual_sol_reserves`
by ~**340–513×** (median ≈505×) the trade's real SOL while `virtual_token_reserves` moves
by exactly the real token amount [VERIFIED-LIVE, one coin's full tape]. The ~500×
amplification is a single-coin measurement; the general rule (fixed multiplier? schedule?
`global-params` holds candidate caps 20 SOL and 5e13 raw, plus 8,000 and 12.8 SOL values,
partially decoded) is **unknown** — the Mayhem program publishes **no on-chain anchor IDL**
and is absent from `pump-fun/pump-public-docs`. [VERIFIED-LIVE that it's absent]

**The case tape, 36 seconds from birth to death** [VERIFIED-LIVE]: create + dev buy
0.0587 SOL at 95 bps (standard math exact) → one human buys 0.001 SOL → agent (signer
`Gygj9QQb…`, TradeEvent user = sol-vault PDA, 0 bps) fires 24 trades in 27 s, real sizes
0.001–0.05 SOL, walking vSol 30 → 49.1 → 9.48 (ath marked 4,756 SOL market cap **3 seconds
after birth**); the human exits at t+4s for −20%; agent stops; state = `paused /
low_sol_reserves`; real SOL left in curve: 0.0093. Dev then fires 4 failed txs and walks.

## 4. The API surface

**On-chain (authoritative)** [VERIFIED-LIVE against IDL + live decode]:
- `CreateEvent.is_mayhem_mode` (bool) — set at birth; but the event's reserve fields and
  `token_total_supply` report the **1e15 curve bookkeeping**, standard constants exactly.
  The 2e15 truth is visible only in mint supply / balance legs.
- `TradeEvent.mayhem_mode` (bool), plus per-trade `fee_basis_points` (0 = agent),
  `virtual_*_reserves` **post-rewrite** — the only truthful per-trade price record.
- `BondingCurve.is_mayhem_mode` (byte offset 81) — 22/22 mayhem curves = 1, 18/18
  standard = 0: the flag is consistent chain-side.
- `UpdateMayhemVirtualParamsEvent`; pump-AMM `CreatePoolEvent.is_mayhem_mode` (migrated
  mayhem coins are labeled in the AMM too).
- Our pinned layouts (`shitcoims_intelligence/pump_layouts.py`) already carry all of these.

**PumpPortal WS (`newToken` frames — what the screen consumes)** [VERIFIED-LIVE, n=87]:
- `is_mayhem_mode` present and **concordant with chain** (32/32 flagged frames had
  mayhem=1 curves; 0 false positives among 55 standard).
- **The reserve fields do read standard on mayhem frames — and they are TRUE at that
  instant**: all 32 mayhem frames satisfy `vTokens + initialBuy = 1,073,000,000.000000`
  and `vSol − solAmount = 30.0` exactly (so do all 55 standard frames). This confirms the
  screen deputy's measurement and resolves it: the vendor is not lying at create — the
  mayhem curve is genuinely standard-seeded — but the numbers go stale within seconds
  once the agent starts re-marking. Any later use of create-frame reserves is wrong.
- **`bondingCurveKey` is junk on 10/32 mayhem frames**: those ten all carry the SAME
  address — the Mayhem sol-vault PDA `BwWK17cb…` — instead of the coin's curve. Derive
  the real key locally: `find_program_address(["bonding-curve", mint], pump_program)`
  (55/55 standard + 22/32 mayhem frames match that derivation). [VERIFIED-LIVE]
- We do not retain trade frames for mayhem coins (screen subscribes `newToken` only), so
  whether PumpPortal's trade stream carries the flag/rewritten reserves is unmeasured.

**Pump frontend-api-v3** [VERIFIED-LIVE probes]:
- Coin record: `mayhem_state` (string) and `mayhem: {state, mode, pause_reason}` (e.g.
  `paused / auto / low_sol_reserves`); `token_program` identifies Token-2022;
  `virtual_*_reserves` match chain (post-rewrite).
- **`total_supply` LIES on mayhem coins: it reports 1,000,000,000,000,000 while
  `getTokenSupply` says 2,000,000,000,000,000** (case coin, during the window). Its
  market caps are priced on 1e15. Never use vendor supply for this stratum.
- Routes: `/coins/mayhem-mode`, `/mayhem/overview`, `/mayhem/top-coins`,
  `/mayhem/top-traders`, `/coins-v2/{mint}/mayhem-state` (null for non-mayhem) — all live;
  catalogued in `~/dev/joshi/docs/reference/PUMP_API_MAP.md` and
  `~/dev/joshi/crates/joshi-pump-api/src/catalog.rs`.

## 5. What breaks — per-feature transfer analysis

| Screen feature | Verdict | Why (all mechanism claims verified above) |
|---|---|---|
| `dev_buy_share` (÷1e15) | **needs recalibration** | Numerator survives: the WS `initialBuy`→raw conversion is exact and the fill matches standard curve math at birth. Denominator is a decision: 2e15 = share of minted supply (halves every share; matches "insider % of true supply"); 1e15 = share of curve float (the vault is agent-only and burns at 24h; matches the registered `mcap_circ` choice). Pick one, state it, never blend. Post-24h the true supply is neither (0.85–1.01e15 observed). |
| Birth-slot bundle shape / `n_snipers` | **needs recalibration** | The birth tx carries an extra ~1e15 positive leg (the mayhem vault), and the agent trades in the birth second(s). "Largest positive leg = curve, second = deployer" mis-roles the whole stratum — the registration's known trap, now confirmed mechanically. Fix = exclude the vault ATA and any leg whose owner is the sol-vault PDA `BwWK17cb…` (constant across ALL mayhem coins), then bundledness may transfer. |
| Sniper-crew fingerprints | **needs recalibration, then unknown** | Pump's agent is a birth-slot buyer on *every* mayhem coin with one constant on-curve identity — any crew statistic that doesn't exclude it will discover one gigantic fake crew. The operator *signer* (`Gygj9QQb…` observed once) may rotate; key on TradeEvent `user == sol-vault` instead. Whether human crews differ inside the stratum is the sibling study's M5(d). |
| Deployer history (`prior_launches/rips/dumps`) | **survives** | Wallet-history semantics unchanged — provided upstream rip/dump labels on mayhem coins aren't produced by the broken price-path detectors below. |
| Curve pricing machinery (`log p` affine in curve balance, k=3.219e25) | **does not transfer** | k is rewritten inside agent trades; no single (k, offset) exists for the stratum, not even per-coin over time. Price must be read from each TradeEvent's reserve fields, never reconstructed from balances. |
| Rip / collapse detectors (`peak_mcap ≥ 100 SOL`, drawdown ≥ 90%) | **does not transfer — redefine on real reserves** | The peak is administered: the case coin printed a 4,756 SOL market cap 3 s after birth on < 0.1 real SOL, then a ≥ 90% "drawdown" by design. Every mayhem coin can cross any virtual-mcap threshold with no real money. Materiality and drawdown must be computed from real SOL (`real_quote_reserves` path, fee-paying trade volume, SOL actually extracted). |
| Graduation | **needs redefinition** | `complete` flag mechanism unchanged, but "curve balance ≤ 1e9 raw" style definitions break: vTok can *exceed* its seed (agent sells from outside float — impossible on standard coins) and the burn removes curve tokens. Gate on `complete` / `real_token_reserves == 0`. SOL-raised-at-graduation is path-dependent, so graduation no longer implies ≈85 SOL of real depth. [INFERRED from verified mechanism; no completed mayhem coin was decoded this session] |
| WS cheap-verdict path (`features.py`) | **survives with two patches** | The flag itself is trustworthy (32/32); keep gating on it. Patch 1: never trust `bondingCurveKey` on mayhem frames (10/32 junk) — derive the PDA. Patch 2: `dev_buy_share_est` denominator decision above. |

**Also discovered, so nobody re-conflates it**: the "31% of on-curve boards carry
k ≠ 3.219e25" line in `RESULT_operator_crime.md` §2.2 attributed the whole non-standard
cohort to mayhem. That attribution is **wrong**. Boards decompose into: standard k
(91.6% of rows), mayhem coins with *rewritten, scattered* k, and a **separate non-mayhem
cohort born at exactly (vTok 1.073e15, vSol 4.292 SOL)** — k = 4.60532e24, initial market
cap exactly 4.0 SOL, constant product *preserved* along its path, first appearing
~June 2026, ~2.7% of rows. Spot-checked on-chain: supply exactly 1e15, `is_mayhem_mode=0`.
That is a third stratum (plausibly related to pump's `set_virtual_quote_reserves` /
quote-mint work), outside both the validated population and this doc's scope — it needs
its own membership predicate; a 2e15 mint is *not* the only nonstandard birth.
[VERIFIED-LIVE, n=1 decisive + 1,933 exact-seed board rows; cause INFERRED]

## 6. The trader-visible difference

[VERIFIED-LIVE unless noted]
- **Fee drag**: humans pay the same 95 bps; the agent pays 0 — every counter-trade you
  take against the agent is against a fee-exempt counterparty.
- **Tape speed/shape**: administered volatility — whole-SOL price jumps on milli-SOL
  agent flow (~500× re-marks), an ath printed seconds after birth, and (case coin)
  death inside 36 seconds when the agent pauses on `low_sol_reserves`.
- **Depth is a mirage**: 22/22 live mayhem curves scanned held ≤ 0.02 real SOL; the four
  3-day-old ones held exactly 0. The marked cap and the exit liquidity are unrelated —
  the one human in the case tape lost 20% in 4 seconds on a 0.001 SOL round trip.
- **Supply overhang then deflation**: during the window an extra 1e9 can be sold into the
  curve by the agent; at t+24h whatever the agent still holds burns (observed burns of
  0.99–1.15e15, one *below*-1e15 final supply — mildly deflationary for survivors).
- **Graduation odds**: not measured here (sibling M4); mechanically possible, and
  migrated pools are labeled `is_mayhem_mode` in the AMM. [INFERRED: odds and
  SOL-at-graduation are not comparable with standard coins]

## 7. Recommendation for the screen

1. **Keep the stratum UNSCORED under the validated screen** (current behavior is
   correct), and keep the vendor flag as the gate — it is chain-concordant (32/32, 0
   false positives). Skipping hydration on mayhem creates remains the right spend call.
2. **A mayhem arm cannot be a recalibration of the price-path features; it must be a
   re-instrumentation.** Features that survive: dev-buy (with a pinned denominator),
   deployer history, bundledness and crews *after* excluding the vault ATA and
   `user == BwWK17cb…` (sol-vault). Features that must be rebuilt on real reserves:
   materiality, drawdown, rip, collapse, graduation economics. Virtual-reserve prices
   during the first 24h should be treated as fabricated by design.
3. **Score at t+24h, not at birth, if a mayhem arm ships.** After the burn the coin is a
   normal constant-product coin again (with a per-coin parked k readable from its curve
   account) and its supply/float are final. Birth-time cleanliness gates (dev buy,
   history, human bundledness) can still be computed retroactively from the birth slot
   with agent legs excluded.
4. **For the registered sibling study** (`REGISTRATION_mayhem_arm.md`):
   - H1 is half-right and the falsifier will fire for the wrong reason: the curve IS
     standard-seeded and the second 1e15 IS a separate leg (structure confirmed), but k
     is rewritten within seconds and the "reserve" leg both trades and burns — M3's
     "single (k, offset) fits ≥99%" criterion will fail because **no constant exists**,
     which is a mechanism fact, not a role-assignment failure. The two stop conditions
     must be distinguished.
   - M2's vendor-key validation must drop frames whose `bondingCurveKey` equals
     `BwWK17cb…` (≈31% of mayhem frames) or agreement will fall for vendor reasons;
     validate against the locally derived PDA instead.
   - M4's graduation definition ("curve balance ≤ 1e9 raw") needs the `complete` flag
     instead, and RIP/COLLAPSE need real-SOL materiality, or the stratum's outcome rates
     will be artifacts of administered prices.

## 8. What we cannot know yet, and what would resolve it

| Open question | What resolves it |
|---|---|
| The exact re-mark rule (is ~500× a constant? per-coin? scheduled? capped by the 20 SOL / 5e13 values sitting in `global-params`?) | The Mayhem program ships no IDL — reverse the deployed `MAyhSmz…` binary in a LiteSVM differential harness patterned on `kernel_svm/` (which today drives DLMM, not pump: new work), or regress `TradeEvent`/`UpdateMayhemVirtualParamsEvent` tapes across a few hundred mayhem coins. |
| `manual` vs `auto` mode semantics (2,188/day are manual) | pump's docs page is an unfetchable SPA; sample manual-mode coins' tapes and diff agent behavior; or read the app UI. |
| Does the agent ever commit meaningful real SOL, and who funds the sol-vault? | Lamport history of `BwWK17cb…`; one `getSignaturesForAddress` sweep. |
| The post-window "settle" rule for parked k (observed scattered 0.018–1.91; one board-row anomaly showed a coin at the 4.292 seed later reading standard) | Track a day's cohort across t+24h; decode `set_virtual_quote_reserves` / admin traffic on their curves. |
| Whether PumpPortal *trade* frames carry `mayhem_mode` and post-rewrite reserves | Subscribe once to the trade feed for a mayhem mint and retain a day of frames. |
| Operator-signer rotation (one wallet observed) | Cross-coin sweep of agent-trade signers; but exclusion should key on `user == sol-vault`, which cannot rotate. |
| The third stratum (4.292-SOL-seed, non-mayhem, ~June 2026+) | Its own recon: membership predicate from CreateEvent reserves, product identification. |
| Definitive adoption curve by day | Sibling M1 census owns it (this doc: ≤13% bound 08-05 → 22–24% 08-26..28 → 37% live 08-29). |

## Sources

- The Block, ["Pump's new 'Mayhem Mode' fails to boost token launches or revenue in first week"](https://www.theblock.co/post/379285/pump-funs-new-mayhem-mode-fails-boost-token-launches-revenue) (2025-11-18)
- [Cryptopolitan](https://www.cryptopolitan.com/pump-fun-launches-mayhem-mode-letting-ai-agents-loose-in-the-trenches/) / [CryptoRank](https://cryptorank.io/news/feed/e1c50-pump-fun-launches-mayhem-mode-letting-ai-agents-loose-in-the-trenches) launch coverage (2025-11)
- [Chainstack blog: Full Mayhem Mode support for Pump.fun](https://chainstack.com/trading-bot-update-full-mayhem-mode-support-for-pump-fun/) (create_v2/Token-2022 mechanics)
- [nirholas/pump-fun-sdk docs/mayhem-mode.md](https://github.com/nirholas/pump-fun-sdk/blob/main/docs/mayhem-mode.md) (third-party; program id + PDA seeds, independently verified on-chain here)
- [pump-fun/pump-public-docs](https://github.com/pump-fun/pump-public-docs) `idl/pump.json` @ main (official IDL; `create_v2`, `set_mayhem_virtual_params`, `BondingCurve.is_mayhem_mode`)
- [pump.fun/docs/mayhem-mode](https://pump.fun/docs/mayhem-mode) (SPA shell; text not extractable in this session)
- Live: `frontend-api-v3.pump.fun` (`/coins/{mint}`, `/coins-v2/{mint}/mayhem-state`, `/mayhem/overview`), Helius mainnet RPC (accounts, transactions, supplies), retained frames under `state/dregg_screen/` and `state/boards/`, corpus distillate `studies/data/operator_crime_fresh/birth.parquet`.
