# Which numbers in this tree are guesses wearing the costume of facts?

**Scanner:** `studies/hardcode_audit.py` — re-runnable, read-only, four modes:

```
uv run python studies/hardcode_audit.py            # ranked table + full inventory
uv run python studies/hardcode_audit.py --measure  # re-derive the A-class values from the tape
uv run python studies/hardcode_audit.py --check    # CI gate; exits 0 today
uv run python studies/hardcode_audit.py --json     # structured, for diffing
```

**Scope:** 3,243 numeric literals across `shitcoims_sentinel`, `shitcoims_scalper`, `shitcoims_cluster`,
`shitcoims_tape`, `shitcoims_intelligence`, `shitcoims_netmap`, `shitcoims_replay`, `shitcoims_scout`,
`shitcoims_kernel`, `kernel_svm`, `scripts/`, `studies/`, plus `app/` (TypeScript), `kernel/` (Lean),
`config.yaml` and `intelligence.yaml` read by hand.

**Measured against:** `state/cluster_tape/` (2,937 swaps, 19,061 attempts, six pools, 2026-08-12→14),
`scripts/sim2real.py`, `studies/RESULT_execution_landing.md`, and live SOL/USD — **$75.795** Coinbase
spot / **$75.79** Kraken last, 2026-08-14T08:00Z.

```
A  MUST BE DERIVED       100
B  LEGITIMATE CONSTANT  1680
C  POLICY CHOICE        1313
D  INSTRUMENT LIMIT      150
```

---

## The headline

**Three findings are not about a wrong number at all — they are about a number that was never
measured being indistinguishable from one that was.** That is the shape worth generalising:

1. **A ceiling read as a typical value.** `config.yaml`'s `max_priority_fee_lamports: 5_000_000` is a
   *cap*. It equals $0.379. Somebody rounded it to **$0.30** and wrote "on Solana gas is ~$0.30" as a
   fact about the world (`studies/circuit_theory.py:1514`); that sentence then became
   `GAS_USD = 0.30` (`studies/circuit_model.py:568`) and `DEFAULT_GAS_USD = 0.30`
   (`shitcoims_netmap/physics.py:58`). The measured median network fee on our own tape is **55,000
   lamports = $0.0042**. One safety limit, propagated three files deep, now sits on the boundary that
   decides whether an arbitrage cycle is worth trading.

2. **A defence disarmed by the fallback one line above it.** `shitcoims_intelligence/tape.py:58`
   reads `decimals = _as_int(delta.get("decimals")) or 0`, and line 59 guards `if decimals >= 0`.
   After `or 0` that guard can never fail. The author wrote the right check and a silent default
   made it unreachable. Same shape at `scripts/lp_report.py`: `usd_price`'s docstring (lines 118-127)
   forswears valuing a missing price at zero, the per-position line honours it ("valuing it at zero
   would lie", line 297) — and `grand_value` twenty lines later accumulates `(px or 0)` and prints it
   as `TOTAL`.

3. **A number measured on the wrong basis, agreeing with itself.** `sim2real.py` inverts constant
   product against the pool vaults and gets 20.0 bps on DREGG/SOL. `studies/lp_strategy.py` does the
   same inversion independently and gets 0.200%/leg — and *labels it correctly*: that is what the LP
   **receives**, not what the taker **pays**, which is 1.44% decoded from pool config. Two
   implementations agreeing to 0.1 bps is not evidence they measure the right thing. Anyone
   "fixing" the scalper's `swap_fee_bps = 100` with the measured 20 bps would make it worse.

The counter-example, and the one to copy: `shitcoims_sentinel/engine.py:283-284` walks signature
history for a cost basis, hits its 40-transaction limit, and returns
`(None, "lot start not reached within N inspected transaction(s)")`. It refuses to let a truncated
window become an answer. **That is what every D-class finding below should look like after it is
fixed.**

---

## Rank 0 — found while hunting default-on-missing, and it outranks everything else here

**`app/views/positions.tsx:45`**

```js
const quoted = exitSol == null || exitSol === "" ? Number.NaN : Number(exitSol);
setEditing({
  mint, name,
  cost_basis_sol: Number.isFinite(quoted) ? quoted : null,   // <-- the current EXIT QUOTE
```

The new-policy form is **pre-filled with the bag's current exit quote as its cost basis**.
`submit()` spreads the whole `editing` object into `savePolicy()` (`positions.tsx:62`), and
`api.ts:115-124` PUTs it unmodified. An operator who opens a fresh bag's exit rules and saves
without clearing that field writes a basis equal to what the bag is worth *right now* — which makes
PnL start at 0% by construction and puts every stop that far below wherever the coin had already
fallen. That is the mechanism `engine.py:63-68` was written to kill: *"-7.47 SOL over 16
fabricated-basis round trips at -29.1% mean, against +18.1% on 3 operator-typed."*

It matters because `engine.py:1039` reconstructs an observed basis only when **both**
`cost_basis_sol` and `buy_price_sol` are None. A pre-filled quote is indistinguishable, at that
line, from a number the operator typed.

**Verified:** the pre-fill, the submit path, and the unmodified PUT.
**Not verified:** whether `_basis_needs_observation`'s migration clause (`engine.py:310-312` —
`origin == ORIGIN_DEFAULT and policy.buy_price_sol is None`) still forces observation and overwrites
the fabricated value. **Resolve that before treating this as live rather than latent.** Note that
`app/lib/api.ts`'s protect-unmonitored path deliberately sends no basis at all, and
`shitcoims_scout/desk.py:224-227` does stamp a quote — so the three clients disagree with each other
about this exact question.

**Patch:** `cost_basis_sol: null`. Leave it empty and let the sentinel observe it, or require the
operator to type what they actually paid.

---

## Ranked by blast radius — (how wrong) × (what depends on it)

| # | cls | site | current | correct | how wrong |
|---|---|---|---|---|---|
| 1 | A | `shitcoims_scalper/policy.py:167` | `priority_fee_lamports = 500_000` | 55,000 measured; 21,000-53,000 budgeted | **9.1×**; B* oversized **3.0-4.9×** |
| 2 | A | `shitcoims_scalper/policy.py:166` | `swap_fee_bps = 100` | per-pool taker all-in (144 bps PumpSwap) | **45× spread** across our own pools, and the obvious fix is the wrong basis |
| 3 | A | `shitcoims_intelligence/tape.py:58` | `decimals … or 0` | refuse the row | **10⁶-10⁹** |
| 4 | A | `shitcoims_netmap/tapefeed.py:515,549` | `decimals, 0` | refuse the row | **10⁶-10⁹**, into TVL |
| 5 | A | `shitcoims_netmap/physics.py:58` | `DEFAULT_GAS_USD = 0.30` | $0.003-$0.009 | **33-94×**, on a verdict boundary |
| 6 | A | `scripts/lp_report.py:267,274` | `(px or 0)` in the TOTAL | carry None | 100% of the missing leg |
| 7 | A | `studies/deterioration.py:586` | `150.0` SOL/USD | return None | **1.98×** — the marketfabric constant, in our tree |
| 8 | D | `shitcoims_intelligence/runtime.py:751` | top-20 holder book normalised to 1.0 | use `getTokenSupply` | structural: `top20` ≡ 1.0 always |
| 9 | D | `kernel_svm/stream.py:233,241` | full 200-sig page = complete history | paginate | unbounded, and it masquerades as `chain_drifted` |
| 10 | A | `studies/power_gate.py:1148` | `swap_fee_bps = 110.0` | 144 bps | **31%**, already superseded in writing |
| 11 | D | `studies/edge_creation.py:570` | out-of-window price → window edge | return None | unbounded, unsigned |
| 12 | A | `config.yaml:17` | `slippage_bps: 1500` | minOut from live reserves | **6×** the tight value the code prefers |
| 13 | D | `shitcoims_cluster/record.py:154,192` | 10k cap, cursor advances past the loss | write a gap row | silent and permanent |
| 14 | A | `shitcoims_intelligence/helius.py:198` | `estimated_credits_per_page = 50` | 10 | **5×**; defects at 20% of budget |
| 15 | D | `shitcoims_intelligence/runtime.py:69` | page limit 20 == threshold 20 | page > threshold | the organic gate is a dead branch |

Registered below the cut (same treatment in `--json`): `circuit_model.py:568` and
`circuit_theory.py:1514` (the other two $0.30 copies), `shitcoims_replay/ope.py:76` (ESS gate buried
in a property), `shitcoims_scalper/feed.py:87,100`, `shitcoims_netmap/assemble.py:325`,
`shitcoims_sentinel/transaction.py:109`, `shitcoims_sentinel/executor.py:631`, and
`shitcoims_sentinel/engine.py:69` — registered as the **exemplar**, not a defect.

---

## The patches

### 1. `shitcoims_scalper/policy.py:167` — the priority fee

```python
-        priority_fee_lamports: int = 500_000,
+        priority_fee_lamports: int = 55_000,  # tape median, n=2937; pass the pool p75 when known
```

`B* = sqrt(priority × Y)`. At Y = 100 SOL the current constant gives B* = 0.224 SOL ($16.94); at the
measured median it gives 0.074 SOL ($5.61); at the policy floor (21,000) 0.046 SOL ($3.47).
`--measure` prints the shrink factor: **3.02×** at today's tape.

**Breaks:** the pass rate falls — small pools that cleared `max_friction` at an inflated B* now fail
it. Every decision in the completed shadow run was sized under the old constant and cannot be
compared to a re-run without re-scoring. The same constant is duplicated at
`shitcoims_scalper/shadow.py:76` and mirrored at `studies/power_gate.py:78`; all three move together
or the study stops matching the policy.

**Second-order, and it is good news:** `RESULT_execution_landing.md` §8 shows B* (√Y) and the
sandwich floor φ·Y crossing at Y = priority/φ² = 3.4 SOL for a 21,000-lamport fee. Below the
corrected constant, sizing at the friction optimum already sits under the sandwich threshold on every
pool worth trading, so the two constraints never have to be traded off.

### 2. `shitcoims_scalper/policy.py:166` — the swap fee

```python
-        swap_fee_bps: int = 100,
+        swap_fee_bps: int,  # REQUIRED: the pool's TAKER all-in. Refuse the candidate when unknown.
```

Measured effective take, `--measure`, constant-product pools only:

| pool | n | median bps | p10 | p90 |
|---|---|---|---|---|
| DREGG/SOL | 81 | **20.0** | 19.9 | 20.0 |
| SOLVE/SOL | 165 | **20.0** | 19.8 | 20.0 |
| nosis/SOL | 2052 | **406.5** | -454.0 | 508.7 |
| weave/SOL | 160 | **908.7** | 865.2 | 976.6 |

**Read this table correctly.** Vault inversion measures what stays in the pool — the LP-received
leg. `studies/lp_strategy.py:131-142` reaches 0.200%/leg by the same method and says so explicitly,
then gives the taker leg as **1.44%**, decoded from pool config. So on DREGG/SOL the scalper's 100 bps
*understates* the taker by 44%; on weave/SOL it understates by ~9×. The constant is wrong on every
pool, in the same direction, and the number a reader would grab to fix it is the wrong quantity.

**Breaks:** on weave-like pools nothing is actionable (2 × 908.7 bps alone exceeds
`max_friction = 0.05`). That is the correct answer and the enter rate collapses to match.

### 3-4. The decimals fallbacks

```python
# shitcoims_intelligence/tape.py:58
-        decimals = _as_int(delta.get("decimals")) or 0
+        decimals = _as_int(delta.get("decimals"))
+        if decimals is None:
+            return ()          # a missing exponent is not a zero exponent

# shitcoims_netmap/tapefeed.py:515
-        decimals = int(vault.get("decimals", 0) or 0)
+        raw_decimals = vault.get("decimals")
+        if raw_decimals is None:
+            return None        # and count it
```

`tape.py:58` flows into `TapePrint.base`, stored verbatim at `runtime.py:305`. `tapefeed.py:515`
flows into `PoolTape.last_reserves_units` → `assemble._tape_tvl_usd` → `Edge.tvl_usd` →
`capacitance_usd`/`depth_term` → every arb notional. `tapefeed.py:549` is the worse twin: it reads
`pool_tape.decimals.get(out_mint, 0)` from a **cross-row cache**, so it silently yields 10⁰ for any
mint whose decimals were never populated in that window. Co-change `shitcoims_cluster/parse.py:519`
to return `None` rather than `0` — it has three separate paths that return `0` for "missing", and
`0` is also a legal decimals value, so a defect is currently indistinguishable from an NFT-like mint.

**Breaks:** rows with absent decimals disappear instead of appearing with million-fold amounts. Every
count over those rows changes — which is the point.

### 5, 16, 17. The $0.30 gas constant, three copies

```python
# shitcoims_netmap/physics.py:58
-DEFAULT_GAS_USD: Final[float] = 0.30
+#: Measured: median network fee 55,000 lamports = $0.0042 (studies/hardcode_audit.py --measure).
+#: A 3-leg route at ~371k CU and the 100k-300k microlamport/CU policy band costs $0.0032-$0.0088.
+DEFAULT_GAS_USD: Final[float] = 0.01
```

Same edit at `studies/circuit_model.py:568`. At `studies/circuit_theory.py:1514`, restate the prose:
"On Solana gas is ~$0.004 (measured median network fee; the $0.30 figure was the configured
priority-fee ceiling)". **That argument survives the correction and gets stronger** — it concludes
gas is negligible against the swap fee, which is more true at $0.004 than at $0.30.

`fee_lamports` is already on every tape row (`shitcoims_cluster/parse.py:785`) and `compute_units`
at `:794`, so this should be derived rather than pinned. The gas term enters as `√(2·G·Σr)`, so a
30× error widens the band by **√30 = 5.5×**, and `arb_value_usd` subtracts G from profit directly
against per-loop residuals the module itself quotes as $0.37-$9.86.

**Breaks:** every reported band narrows and cycles previously below it become tradeable. Any
conclusion of the form "no cycle clears the band" must be recomputed, in `RESULT_circuit_model.md`
and the netmap output both.

### 6. `scripts/lp_report.py:267` — the total that lies

```python
-        value = (amount_x / 10**dec_x) * (px or 0) + (amount_y / 10**dec_y) * (py or 0)
+        if px is None or py is None:
+            unpriced += 1
+        else:
+            grand_value += (amount_x / 10**dec_x) * px + (amount_y / 10**dec_y) * py
+            grand_basis += basis
```

and print `TOTAL ... ({unpriced} position(s) omitted, unpriceable)`. This is the smallest and most
certain fix in the audit, and the file already argues for it in its own docstring.

### 7. `studies/deterioration.py:586` — SOL = $150

```python
-    last = next((p for p in price if not math.isnan(p)), 150.0)
+    last = next((p for p in price if not math.isnan(p)), None)
+    if last is None:
+        return None
```

This is the marketfabric constant (`sol_usd = 150.0`, 11.3% zeros, 50,164× p95/p05 spread) sitting
in our own tree. It seeds the forward-fill for the SOL/USD reference series, which
`deterioration.py:634-636` divides into every forward return — both the study's matching features
*and* its outcome. The result persists to `state/deterioration/sol_usd.json` for six hours, so one
bad fetch poisons a window. Two more in the same class, same file: `SolUsd.at` returns `1.0` when
the reference is missing (`:601-607`), and `self.price[idx] or 1.0` turns one zero hour into a **75×**
return spike.

### 8. `shitcoims_intelligence/runtime.py:751` — the holder book that is always 20 deep

`getTokenLargestAccounts` is capped at 20 accounts by the node. `numerics.py:58-79` then normalises
by `total = sum(xs)` over only those 20, so `holder_top1` means "largest holder's share **of the top
20**", `holder_count` is always ≤ 20, and `top20` is identically 1.0. `holder_veto` (`numerics.py:88`,
duplicated at `sieve.py:51-52` with a comment admitting the duplication) then vetoes on
`top1 ≥ 0.35`. A mint whose top 20 wallets hold 3% of supply, with #1 holding 40% *of that 3%*, is
rejected.

**Patch:** fetch `getTokenSupply`, append a synthetic remainder bucket before calling
`concentration()`. If that is too expensive, stop emitting `top1`/`hhi`/`nakamoto` and emit only an
honestly named `top20_share_of_supply`. **Breaks:** the veto rate falls — correctly.

### 9. `kernel_svm/stream.py:233,241` — a full page read as complete history

```python
-        seen = {s["signature"] for s in rpc("getSignaturesForAddress", [pool, {"limit": 200}])}
+        page = rpc("getSignaturesForAddress", [pool, {"limit": 200}])
+        if len(page) == 200:
+            raise RuntimeError("signature page saturated; paginate with `before` before trusting the diff")
+        seen = {s["signature"] for s in page}
```

No `len(page) == limit` check and no `before` cursor, polling every 4s. Copy
`shitcoims_cluster/record.py:155-169`, which does exactly this correctly in the same repo. The
danger is not that the loss is silent — it is that it **surfaces as `chain_drifted`**
(`stream.py:120,260`), which reads as a race and invites a "fix" by re-snapshotting.
`kernel_svm/capture.py:246-253` has the same defect at `limit=100` and worse: the page is
newest-first, so filtering by slot drops the *oldest* entries — exactly the ones the chained replay
needs first.

### 10. `studies/power_gate.py:1148` — a correction that was written down and never propagated

```python
-    swap_fee_bps = 110.0
+    from studies.lp_strategy import PUMPSWAP_TAKER_FEE
+    swap_fee_bps = PUMPSWAP_TAKER_FEE * 10_000  # 144 bps, decoded from pool config
```

`lp_strategy.py:138-141` names this site: *"RESULT_power_gate.md carried the taker leg as 'up to
1.10%' and flagged it as its weakest inherited assumption; 1.44% decoded settles it, and it is HIGHER
than the bound that section called absurd."* The superseded number is still a bare local inside
`section [10]`, driving `friction_usd` in a dollar feasibility verdict. Friction rises ~31%; any
experiment sized against that table was under-budgeted.

### 11. `studies/edge_creation.py:570` — the clamp

```python
     def at(self, token: str, when: int) -> float:
         ts, px = self._s[token]
+        if when < ts[0] or when > ts[-1]:
+            return None       # outside the fetched window; the caller must refuse the position
         i = bisect.bisect_right(ts, when) - 1
-        return px[max(0, min(len(px) - 1, i))]
+        return px[i]
```

`bisect_right(ts, when) - 1` is `-1` below the window; `max(0, -1)` clamps it to the oldest bar, so
any pre-window timestamp is priced at the window edge with no marker. It flows into deposit USD
(`:1067`), the HODL counterfactual (`:1077`) and the IL ratio (`:1083-1084`). The class docstring
(`:530-537`) already states the instrument limit, and the method docstring insists `at()` is *"never
an interpolation: interpolating a price you did not observe is exactly the kind of quiet fabrication
PROGRAM.md was written about."* Backward extrapolation off the window edge is that fabrication.

### 12. `config.yaml:17` — slippage

```yaml
 jupiter:
   slippage_bps: 1500
+  exit_slippage_bps: 250
```

**Less bad than it looks, and the nuance matters.** `clients.py:56` already sets
`TIGHT_EXIT_SLIPPAGE_BPS = 250` for `exit_trail`/`exit_stop`/`exit_scale`/`exit_dispose`, and
`executable_order` (`clients.py:486-491`) rejects any order whose own threshold sits below the floor
computed from its own quote. The 1500 is live only on **panic / exit_rug** — and on every
`quote_exit` PnL mark, which passes `config.slippage_bps` unmodified (`clients.py:417`). The config
key above is already honoured through `getattr` at `clients.py:65`; it just does not exist yet.

**Breaks:** panic exits on genuinely collapsing liquidity may revert instead of filling. That is the
trade the 1500 buys, and it should be bought deliberately rather than by default.

### 13-15

- **`shitcoims_cluster/record.py:154`** — the pagination is *correct* (`:167` has exactly the
  `len(page) < page_limit` check kernel_svm lacks). The defect is that when the 10,000 cap binds, the
  cursor advances to the newest signature collected (`:192`) and the skipped interval is never
  revisited **and never recorded**, while every other truncation in this repo writes a gap
  (`note_failure`, `SourceGap`, `OBSERVER_LOST`). Downstream, `tapefeed.evidence` reports the window
  as `observed`. Patch: `write_watch` a truncation gap before advancing the cursor.
- **`shitcoims_intelligence/helius.py:198`** — `estimated_credits_per_page: int = 50`, contradicted
  twice by its own file: *"Every page is 10 credits whatever it contains"* (`:689`) and *"it is the
  10-credits-per-100-transactions RPC"* (`:737`). Patch to `10`. **Breaks:** runs collect up to 5×
  more pages; verify real spend on the Helius dashboard before shipping, because the budget was
  always there but has never been exercised.
- **`shitcoims_intelligence/runtime.py:69`** — `MINT_TAPE_PAGE_LIMIT = 20` and
  `sieve.py:44 _MIN_TRADES_FOR_ORGANIC = 20` are the same number in different files with nothing
  connecting them, and `sieve.py:166` skips when `trade_count < 20`. `trade_count` cannot exceed the
  page, so `organic_verdict` is a near-dead branch — and in the boundary case where it *does* fire,
  it judges wash-trading off ~20 prints, a few seconds of tape. Patch: import the threshold, set the
  page to `4 × _MIN_TRADES_FOR_ORGANIC`, and put `trade_count_is_truncated = (len(page) == limit)`
  in the feature bag so the sieve SKIPs explicitly rather than by arithmetic accident. Note this
  interacts with the credit fix above.

---

## Class D in full — instrument limits, ranked by whether the caller believes them

**Believes the limit is a fact (fix these):** `kernel_svm/stream.py:233,241`;
`kernel_svm/capture.py:246,253,281`; `shitcoims_intelligence/runtime.py:751` (holder book) and `:69`
(page == threshold); `shitcoims_intelligence/service.py:25,270` (`CANDIDATE_OBSERVATION_LIMIT = 200`
— `mentions` is "how many of the last 200 *heterogeneous* observations touched this mint", and
`siblings_by_creator` is built from the same window, so `deployer_verdict`'s serial-rugger check is a
fact about the page, not the deployer); `service.py:284` (200 rows pulled across *all* wallets then
split per wallet, so `tx_count` is a share of a shared window);
`studies/edge_creation.py:570`; `studies/control_arm.py:511` (`calls > 40` caps "every transaction of
the operator's wallet" at 4,000 and exits identically to natural exhaustion, then caches as
complete); `scripts/meteora_lp_report.py:518-523` (unpaged `page_size=50`, while the sibling function
20 lines above pages correctly on `hasNext`); `studies/lp_strategy.py:2551` and
`studies/circuit_theory.py:1926,1932` (`page=1`, no loop); `scripts/lp_report.py:104,258`
(position age from `signatures[-1]` of one 1,000-signature page); `scripts/bulk_history.py:247`
(`max_rows` with no `len(rows) >= max_rows` check, then marked `"complete"`);
`scripts/lp/survival.py:12` (`most_common(20)[:12]` — already named as wrong in
`studies/control_arm.py:918` and not yet fixed).

**Records the limit honestly (the reference patterns):** `shitcoims_sentinel/engine.py:283-284`;
`shitcoims_tape/sources.py:174-176` (*"It stops on the cursor, never on a short page"*) and
`:113,119` (`STOP_PAGE_CAP` becomes a `OBSERVER_LOST` close reason, so censoring shows up in
`tape_health`); `kernel_svm/snapshot.py:160-168` (tests whether the fetch window bounds real
emptiness before believing a revert); `studies/deterioration.py:391,653-656` (*"Age must come from
pool creation, never from the first candle"* — **this is the 500-bar bug, already found and fixed
here**); `scripts/fetch_mean_reversion_data.py:167-192` (pages backwards to on-chain
`pool_created_at`); `scripts/pumpfun_frame.py:46-92` (Chao1 coverage audit instead of assuming a
sweep is a census); `scripts/panel_audit.py:249-297` (*"Counting a half-read replication would report
the AUDIT's truncation as the TAPE's missing trades"*); `shitcoims_intelligence/early_coin.py:132`
(raises rather than truncating).

**Display truncation with no "… and N more":** `app/views/intelligence.tsx:50,110,144`,
`app/lib/intelligence.ts:28,49,81,89,97`, `app/views/overview.tsx:178`,
`shitcoims_scout/gateway.py:215`, `shitcoims_scout/desk.py:164`,
`shitcoims_scout/local_api.py:271,277,350,377,410,444`. Counter-example done right:
`local_api.py:134-135`. `app/lib/intelligence.ts:28` requests `limit=50` and never checks
`next_cursor`; `app/lib/api.ts:113,117` request `limit=200` and do the same.

---

## Class A that did not make the top 15

- **`shitcoims_netmap/assemble.py:325`** — `fdv = (… else 0.0) or (… else 0.0)`. Both aggregators
  failing gives FDV = 0, which selects the **most expensive** creator rung (0.95%). Fails
  conservative, but `pumpswap_fee` always sets `uncertain=True`, so nothing distinguishes a measured
  ladder from a guessed one.
- **`shitcoims_netmap/tapefeed.py:372-373`** — `_units` returns `0.0` on an unparseable amount, and
  `assemble._choose_tvl:247-258` explicitly prefers chain readings *"including when zero. A vault
  read that comes back empty is a measurement — the pool was drained."* So a parse failure is
  **promoted to a drained-pool verdict** over both aggregators, and fires the DRAINED warning.
- **`shitcoims_netmap/physics.py:151`** — `dynamic = dynamic_pct or 0.0`, then the `Fee` is stamped
  `uncertain=False`, source `"(served, not assumed)"`. Half-served is recorded as fully served.
- **`shitcoims_sentinel/transaction.py:109`** — `unit_limit = 200_000` when no `SetComputeUnitLimit`
  is present. Solana's default is 200,000 **per instruction**, capped at 1,400,000 per transaction,
  so this under-estimates the fee in the direction that *passes* the cap. Cold today (Jupiter always
  emits an explicit limit) and bounded by the 0.005 SOL cap. Patch:
  `min(200_000 * max(1, len(instructions)), 1_400_000)`.
- **`shitcoims_sentinel/executor.py:631`** — `int(order.get("otherAmountThreshold") or 0)`. At 0 the
  simulation gate degenerates from "the exit returned at least minOut" to "the wallet lost less than
  0.02 SOL". Unreachable today: `clients.py:478-482` enforces `0 < minimum_output <= out_amount`. But
  the `or 0` encodes the opposite invariant to the one the caller guarantees, and dead defences are
  how invariants quietly move. Patch to `int(order["otherAmountThreshold"])` — a `KeyError` here is
  the correct failure.
- **`shitcoims_sentinel/clients.py:648`** — `liquidity.get("usd", 0)`. A missing DexScreener field
  becomes 0, which *can* form the `drained` half of a rug verdict. **Contained by design:**
  `rug_detector.py:91` also requires an independent Jupiter quote collapse, and the comment at
  `:86-87` states the principle — *"Missing provider data is UNKNOWN, not ZERO … can never become rug
  evidence."* One provider's absent field cannot fire a sell. Still worth a `None`.
- **`scripts/lp/ladder_econ.py:10`** — `UNIT=1e6` assumes every mint has 6 decimals and divides
  whatever appears in `pnl_rows.json` by it, into realised SOL. `sym()` explicitly expects unknown
  mints. Decimals are already present in the source `wallet_txs.json`. **`scripts/lp/*.py` are
  modified in the working tree by another agent right now — coordinate before patching.**
- **`scripts/lp/find_positions2.py:15,17`** — `0.05e9 <= post[i] <= 0.07e9` as the DLMM position-rent
  window. Rent is `getMinimumBalanceForRentExemption(len)` and varies with bin width, so any position
  outside that band is silently absent from the entire census.
- **`studies/position_history.py:844-846`** — `/1e6` applied to *every* mint under a header claiming
  "raw base units → UI units". Display only (the JSON keeps raw ints), but wrong for any
  non-6-decimal mint.
- **`studies/control_arm.py:1269`** — `PUMPFUN_LAUNCH_MCAP_USD = 2_120.0`. A SOL-price-dependent
  quantity frozen as a constant.

**Price constants, all of them.** `studies/lp_strategy.py:129` `SOL_USD_DEFAULT = 75.95` (0.2% off
today, surfaced as `--sol-usd`, documented as the value at the run that produced the RESULT — this is
the correct handling); `studies/execution_landing.py:1200` `--sol-usd default=75.75` (current);
`studies/circuit_theory.py:1011,1305,1681,1734` — `next(…, 76.0)` **four times**, right for today but
a silent default inside a generator expression that feeds `C_sol` and therefore `eta`, the study's
headline quantity; `studies/deterioration.py:586` — `150.0` (rank 7). `shitcoims_netmap` computes
every USD figure from a live quote and picks the deepest quoting pool — **no hardcoded price anywhere
in it** except `DEFAULT_GAS_USD`. `shitcoims_intelligence`, `shitcoims_scout`, `kernel/` and
`shitcoims_kernel` contain **no price constant at all**; everything is lamport- or SOL-denominated.

**No `$190` exists anywhere in the tree.** The nearest thing is `app/views/overview.tsx:282`
`const target = 18;` — the rent goal, buried in `BookClimb`, rendered as `/ 18 SOL`. It is
**SOL-denominated with no recorded date or price anchor**, so its dollar meaning drifts with SOL
whether or not anyone intends it: $1,364 at today's $75.795. Patch: state the goal in USD and derive
`target = rentUsd / solUsd`, or at minimum rename it `TARGET_SOL` with the date and SOL price at
which it was chosen.

---

## Class C — correct as constants, but buried

The audit found 1,313 policy choices. These are the ones where "buried" is doing real damage:

- **`shitcoims_replay/ope.py:76`** — `return self.ess_fraction >= 0.10`. The single most consequential
  number in the replay tree, inside a property body: not a constructor argument, not a module
  constant, not in the returned `Estimate`, not overridable. Worth saying that `ope.py` has **no IPS
  clipping and no discount factor at all**, which is the right call (clipping biases in a way no
  diagnostic recovers) — this threshold is the one exception to an otherwise clean module.
- **`studies/power_gate.py:1148,1510`** and **`studies/execution_landing.py:780,943,989,1007,1015`** —
  the entire execution policy (`cu_limit = 160_000`, `cu_price_floor = 100_000`, the `[100k, 3M]`
  clamp, the `1.15` simulate multiplier, `expected_landing_rate: 0.95`, `phi = 0.0025` twice) lives as
  literals in a function's local scope and a dict literal. Each is justified by a measured p99 in an
  adjacent comment, so the *reasoning* is excellent; none is a module constant or a flag.
- **`shitcoims_intelligence/sieve.py:43-52`** — eight veto gates, none carrying the date, mint set, or
  sample size it was tuned on, and `_HOLDER_TOP1_VETO`/`_HOLDER_HHI_VETO` duplicated at
  `numerics.py:88` with a comment admitting *"keep them aligned"* — two sources of truth by
  admission.
- **`shitcoims_intelligence/sieve.py:277-311`** — `score_mention_quality` multiplies eight bare magic
  numbers (`0.15/0.5/1.0`, `0.7/0.9`, `min(1.1, 0.8 + 0.5*log1p(likes)/log(50))`, `0.55`, `0.4/0.7`)
  into a "0..1 genuine-attention prior". A fabricated probability with no calibration behind any
  constant.
- **`x_apify.py:278,295,312,333`, `claudekol_collect.py:19-20`, `kol_wallets.py:27`,
  `early_lab.py:22-23`** — asserted confidences from 0.15 to 0.55, then **averaged** at
  `service.py:361` and published as a dossier confidence.
- **`shitcoims_intelligence/runtime.py:580,637-640`** — every Helius budget knob in
  `intelligence.yaml` is silently clamped by a smaller literal buried in a function body:
  `watchlist_max_addresses` 2000 → 20, `history_pages_per_run` 10 → 2,
  `history_transactions_per_run` 1000 → 25, `history_page_size` 100 → 25. **The YAML is a decoy.**
- **Three different "default" risk policies for the same bag:** `shitcoims_scout/desk.py:9-11`
  (SL −35 / TP 80 / trail 20), `app/lib/api.ts:11-16` (**−30 / 100** / 20), and
  `app/views/positions.tsx:46-48` (−30 / 100 / 20, **buried in a click handler** and duplicating
  `api.ts` rather than importing it). The Telegram desk and the web UI create policies with different
  stop losses.
- **`shitcoims_scalper/policy.py:94,168`** — `rho_max_bps = 200` written twice as a default argument;
  and `bankroll_cap_lamports` at `:169` silently caps B* with nothing in the `Decision` recording
  which of the three caps bound. Patch: have `optimal_size_lamports` return
  `(size, binding_constraint)` and log the constraint name.
- **`shitcoims_tape/schema.py:746`** and **`health.py:487`** — the `0.98` coverage bar, as a bare
  literal in two files.
- **`shitcoims_netmap/assemble.py:802,808`** — `10.0` / `100.0` / `2.0` alarm thresholds inside
  `_warnings`; hoist alongside `MIN_CYCLE_LIQUIDITY_USD`.
- **`shitcoims_replay/trials.py:99-100`** — `skew=0.0, kurtosis=3.0` default the non-normality
  correction **off**, in a module whose docstring exists because memecoin returns are violently
  non-normal. Surfaced as arguments, so a caller *can* pass real moments — measurable from the return
  series being deflated. Same shape at `split.py:79`, where `embargo=0` defaults the embargo defence
  off in a module whose docstring cites a published "purged" CV whose purge was a literal no-op.

---

## Class B — legitimate, listed so nobody "fixes" them

`LAMPORTS_PER_SOL = 1_000_000_000` and `10_000` bps throughout. `5_000` lamports/signature
(`execution_landing.py:81`, verified against 4,130 of our own transactions). `SIMULATION_ADDRESS_LIMIT
= 32` (`clients.py:41`) and 32-byte pubkeys. 8-byte Anchor discriminators, and
`shitcoims_cluster/pools.py:52-66`'s sixteen of them with the `sha256("global:"+name)[:8]` derivation
shown. `MAX_SIGNATURE_LIMIT = 1000` (`cluster/rpc.py:54`, documented Helius cap).
`MAX_CU_PER_TX = 1_400_000`. `432_000` slots/epoch. `BINS_PER_ARRAY = 70` (Meteora DLMM). SPL Token
account layout offsets (`kernel_svm/svm.py:41-47`, `scripts/lp_report.py:50-56`) and the 165-byte
account size. Borsh widths. `maxSupportedTransactionVersion: 0`. `decimals ∈ [0, 255]` (SPL `u8`).
Base58 pubkey length 32-44 (ten copies — consider one shared constant). `86_400`/`3_600`. `CPMM_SPAN
= 4.0` (`C = TVL/4` is exactly `C = TVL/W` at `W = 4`). `EULER_GAMMA`. `1.96`/`1.645`. Bailey &
López de Prado's `(kurtosis - 1)/4`. File modes `0o600`/`0o700`.

Three that look like constants and are better than that: `shitcoims_tape/backfill.py:77`
`RED_PUMP_MEASURED_DISPLACEMENT_SECONDS = 166` sits next to `:81 RED_PUMP_CLAIMED_HORIZON = 24h` with
the comment *"the gap between this and the line above is the entire bias"*; `health.py:54`
`MARINO_MEDIAN_GRADUATION_SECONDS = 264.0` cited to arXiv; `helius.py:884`
`DEFAULT_BLOCK_TIME_CACHE_SIZE = 8_192` with twelve lines deriving it from ~400ms slots. That is the
documentation standard the rest of the C-class should meet.

One boundary case: `shitcoims_scalper/feed.py:25` `VIRTUAL_SOL_FLOOR_LAMPORTS = 30_000_000_000`.
Protocol-fixed *today*, but it is pump.fun program **config**, readable from the global account and
changed historically. Classified B, flagged.

---

## Standing check

`--check` exits **0** on the tree as of this audit. It goes red when:

- a registered finding **moves** (reports the new line), or is **rewritten/resolved** (so the
  registry gets updated rather than quietly rotting into a document about a codebase that no longer
  exists);
- a **new** numeric literal appears in a money-path file (`shitcoims_sentinel/{executor,transaction,
  clients,policies,lots}.py`, `shitcoims_scalper/{policy,shadow}.py`) that the classifier reads as
  derivable and that carries no per-site ruling in `OVERRIDES`.

Adding a ruling to `OVERRIDES` is the intended way to close a finding — it forces someone to write
down *which class* the number is and *why*, which is the only part of this audit that a grep could
not have produced.

`--measure` re-derives the A-class values from `state/cluster_tape/` on every run, so the numbers in
this report do not go stale silently. Today it returns: effective fee 20.0-908.7 bps across four
constant-product pools; network fee median 55,000 lamports = $0.004169; compute units median 123,615;
3-leg gas $0.0032-$0.0088; **B\* shrink versus the current constant: 3.02×**.

---

## What was not done

This report describes patches; **it does not apply them.** The sentinel is live-armed with real money
and several agents held files in `studies/` and `scripts/lp/` while this ran. The only files written
are `studies/hardcode_audit.py` and this document.

Two claims here are stated at lower confidence than the rest and are marked in place: the taker-versus-
LP-fee reading of the `sim2real` measurement (corroborated by `lp_strategy.py`'s independent
implementation and its own labelling, but not verified against a decoded pool config in this pass),
and the provenance of `DEFAULT_GAS_USD = 0.30` as a rounding of the config ceiling (the arithmetic
matches — 5,000,000 lamports = $0.379 — and the docstring says *"at the config's priority-fee cap"*,
but no commit was traced).
