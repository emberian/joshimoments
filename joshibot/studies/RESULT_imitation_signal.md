# RESULT: imitation swarms — the costly-signal channel, measured

*(draft in progress — §0 and §5 are written from the final run; do not cite until the header
line below names a pinned command.)*

Code: `shitcoims_scalper/swarm_detect.py`, `studies/imitation_signal.py`,
`tests/test_swarm_detect.py`.
Data: `state/firehose/new_token/`, `state/swarms/census-*.jsonl`, `state/swarms/candles/`.
**Spend: $0.00.** Every endpoint used is keyless and free.

---

## 1. The hypothesis, and the one reason to expect a different answer than last time

The operator's words: *"noticing when scam/imitators start popping up. i'm willing to bet
that if we are fast we can setup positions that will massively gain from them when they are
even slightly legitimate."*

`RESULT_callout_edge.md` closed the social channel with a null that had a sign — buying a
callout returns **−11.9% at 1 h**, the callout block *lowers* test AUC from 0.796 to 0.665,
and permuting caller identity **beat** the real identity in 24 of 24 draws. The structural
reading offered there was that talking is free, so the loudest callers are recruiting exit
liquidity.

An imitator is not talking. A clone costs a create transaction plus a dev buy, and it is
aimed at a chosen target. A swarm is therefore a **costly signal**: N adversaries each
spending money to assert that one specific coin has attention worth stealing. That is the
one theoretical reason to expect a different answer from the callout channel, and this study
exists to make it survive the data or die.

It is worth naming the reason it might still fail, before any number appears. Nothing
guarantees a parasite's attention estimate is *early*. If clones show up only once a coin has
already run, the swarm is a lagging indicator of a finished move, and paying to attach
yourself to it is perfectly consistent with the host being over.

---

## 2. The instrument

### 2.1 Two transports, because a socket is not a census

Launches come from the union of two sources with different failure modes:

| source | what it gives | what it misses |
|---|---|---|
| PumpPortal socket (`state/firehose/new_token/`) | push, ~2 s latency, `traderPublicKey`, `solAmount`, `initialBuy`, `marketCapSol`, `uri` | **no `image_uri`**, no vendor clock at all, and it drops when the socket drops |
| pump.fun REST list (`state/swarms/census-*.jsonl`) | `created_timestamp` (a real vendor clock), `image_uri`, `ath_market_cap`, `reply_count` | it is a poller — the failure mode this repo was already burned by — and pages to a hard wall at `offset≈2000`, ~1.9 h of history |

Measured agreement over a quiet 33-minute window: the socket carried **565 of 572** REST
coins, **98.8%**. So the socket is good when it is up, and the census exists for when it is
not — and for `image_uri`, which turns out to be one of the strongest clone links in the
data.

Three defects in the raw tape that a naive read would have propagated:

1. **A 172-minute hole.** The tape for 2026-08-15 has one clean segment and one long gap.
   The study restricts to the ledger's demonstrated `watch_open`/`watch_close` intervals;
   outside them, absence of a launch is our blindness, not the market's silence.
2. **Double ingestion.** Two socket windows were connected simultaneously for ten minutes and
   every launch in that stretch landed on the tape twice. Deduping by mint is not hygiene
   here — counting rows would have doubled the apparent launch rate and manufactured a family
   out of every coin.
3. **The real launch rate is ~1090/hour**, not the ~300/hour a naive read of the gappy tape
   suggests.

### 2.2 Prices, free and retroactive

`https://swap-api.pump.fun/v1/coins/<mint>/candles?interval=1m&currency=SOL` returns
per-minute OHLCV in SOL, keyless, one request per mint, and **retains at least a month** —
so the price path of any coin in the tape is recoverable after the fact rather than having to
be polled forward. A candle exists only for a minute in which the pool traded.

Validated against the socket's own `marketCapSol` on 24 fresh mints: `candle[0].open × 1e9 /
marketCapSol` has median **0.974** — the candle open is the bucket's first print, usually just
before the dev buy that the socket's market cap already includes.

**Why mark-to-last-trade is close to an executable price here, unlike on an AMM.** The
callout study had to caveat its marks: a coin that stopped trading has a quote but no
counterparty. On the pump.fun bonding curve the curve *is* the counterparty — a sell executes
against the program at a deterministic price whether or not another human is present. The
study still reports `live` (did anything trade in the window) beside every return, because
"attainable" is not "attained", and it reports the two halves separately (§5.3) because that
distinction turns out to decide the whole clone-arm result.

### 2.3 What counts as an imitation

Launches are clustered by five links, strongest first, and every family records which fired:

| link | meaning |
|---|---|
| `uri` | identical metadata document — same artwork, same description. As close to a confession as this data gets |
| `image` | identical `image_uri` (census only) |
| `symbol` | identical alphanumeric-folded ticker |
| `symbol_squashed` | identical after collapsing character runs: `READ` ≡ `READDDDDDDDDD`. Known cost: also merges `BULL` with `BUL`, so it is its own kind and never folded into `symbol` |
| `name_near` | normalised edit distance ≥ 0.82 on the folded name, trigram-blocked |

### 2.4 The host is an observable, not a guess

"Earliest member" is the right prior — an imitation postdates its target — but it is wrong
exactly when it matters, because if the original launched before we were listening then the
earliest member *we saw* is itself a clone. So the detector takes an optional traction probe
and the host is the family member with the most SOL-equivalent turnover **before** the onset
instant, falling back to earliest. Only candles at or before the onset are read, so the probe
cannot see the future the study then measures. Every event row records which rule fired, and
families whose earliest member sits within one matching window of the stream's own start are
flagged `host_left_censored` and excluded from the cohort.

### 2.5 The taxonomy that must never be pooled

`traderPublicKey` splits the phenomenon in two:

* **parasite** — no single deployer emits more than 60% of the clones *and* the host's own
  deployer is absent from them. Independent adversaries converging on one target. **This is
  the hypothesis.**
* **farm** — one deployer emits more than 60% of the clones. A factory shipping inventory.
* **self_farm** — the host's own deployer did most of the cloning. A dev spamming their own
  idea.
* **mixed** — the host's deployer is present among the cloners but not dominant.

**The honest limit on this discriminator, stated once and loudly:** distinct-deployer count
is an *upper* bound on independence. Sybil wallets are free, and MELT puts 36.5% of supply in
coordinated hands. Nothing in this study clusters wallets by funding ancestry (that is
PROGRAM.md signal #2, and it is a prerequisite this study did not have). A four-wallet
"parasite" swarm may be one actor with four wallets. The detector records each cloner's prior
launch count in the same tape as a cheap partial check — a wallet with fifty prior launches is
infrastructure — but the clean test is unbuilt.

---

## 3. The three ways this could have produced a false positive, and what was done about each

1. **Ambient collisions.** Only 23.6% of launches carry a ticker unique within 30 minutes
   (measured by the callout study's cashtag resolver). `SOLANA` launches ~25 times in four
   hours with nobody imitating anybody. Handled by **two** detector-level nulls, because
   PROGRAM.md §3.13 is explicit that one null is a knob rather than a test:
   * **shuffle** — launch identity permuted i.i.d. across the tape. Every symbol keeps its
     frequency; same-symbol launches no longer arrive together. This is the collision floor.
   * **rotation** — identity shifted as a block. Because the launch rate is near-constant, a
     rotation carries a burst *intact* to a different hour and merely lands it on a different
     host. It answers the narrower question "is it the swarm, or just a coin that had
     traction at that minute?" — and anyone reading its family count as "the detector finds
     nothing" has misread it. Both are run; the difference between them is reported.
2. **The free columns.** Market cap and age are the reigning champions at AUC 0.796. A coin
   that attracts clones is a coin that has *already moved*, and "coins that just moved keep
   mean-reverting" is not the hypothesis. Handled by matched controls that balance momentum
   and turnover, not just size and age — see §5.2 for how much this mattered — and by the
   incremental-AUC test, which is the only question that counts.
3. **Survivorship.** Dropping the coins that die flipped the callout cohort's 8 h return from
   −14.6% to **+25%**. Every row here is priced mark-to-last-trade, the dead are counted as
   their own state in a competing-risks table, and §5.3 splits every arm into rows that
   traded inside the window and rows that did not.

---

## 4. Methodology bindings actually honoured

* **Temporal splits only**, with the **family as the indivisible entity** — a host and its
  clones share a deployer network, an image and a minute of market regime, and a control
  inherits its treated row's family id so a matched pair cannot straddle either.
* **No resampling of any kind.** Natural base rates throughout.
* **Both controls.** A known-zero world (three label nulls) *and* a known-effect world (a
  planted treated→label effect the estimator must recover). A green zero-control certifies a
  broken estimator exactly as readily as a working one.
* **Competing risks** via `lifelines`, reported as {up, down, dead} rather than a mean over
  survivors.
* **Trials counted and FDR'd**, with the sweep over the detector's two free knobs (`k`, the
  matching window) reported rather than hidden.
* **A power floor.** A null without a minimum detectable effect is a shrug, so every headline
  comparison carries the multiplicative shift the cohort could have detected at 80% power.

---

## 5. The result

*(filled from the final pinned run)*

---

## 6. The candidates feed contract

`state/swarms/candidates.jsonl`, append-only JSONL, one row per onset. It carries **evidence,
never a verdict** — a consumer decides direction and size; the file never says "buy".

```json
{
  "kind": "swarm_candidate", "schema": 1,
  "t_ingest": "<our clock, ISO8601 UTC>", "t_ingest_unix": 1786852740.5,
  "t_event": "<onset instant — the tradeable moment, NOT the host's launch>",
  "t_event_unix": 1786852740.0,
  "t_event_source": "launch_clock:vendor | launch_clock:ingest",
  "family_id": "f0000123",
  "host_mint": "…", "host_symbol": "…", "host_launch_t": "…",
  "host_left_censored": false,
  "host_rule": "traction | traction_agrees_earliest | earliest | earliest_no_traction",
  "taxonomy": "parasite | farm | self_farm | mixed",
  "clone_count": 2, "distinct_clone_deployers": 2, "clone_spend_sol": 4.0,
  "lag_from_host_s": 66.0, "lag_from_first_clone_s": 40.0,
  "match_kinds": {"symbol": 2},
  "host_mcap_sol_at_onset": 95.9, "host_age_s_at_onset": 66.0,
  "host_momentum_at_onset": 0.31, "host_traded_minutes_at_onset": 2,
  "members": ["<host mint>", "<clone mint>", "…"]
}
```

Consumer notes, which matter more than the schema:

* Both clocks appear twice: ISO for a human, unix float under the `_unix` suffix every
  `shitcoims_paperdesk.feeds.Source` already speaks, so tailing this needs no translation.
* This is an **event** feed, not an observation feed. It deliberately carries no curve
  reserves: a consumer already tails `state/firehose/new_token/` and should read
  `vSolInBondingCurve` from there, fresh, rather than from a stale copy here.
* `t_event` is the **onset**, not the launch. Entering from the launch is a different
  (and unmeasured) trade.
* `host_left_censored: true` means the detector could not see far enough back to be sure the
  nominated host is the original. Those rows are excluded from every number in this document
  and should be excluded from any position.
* **`taxonomy` must be read before `clone_count`.** A farm's forty clones are one wallet's
  inventory and say nothing about a host.
* **Pre-graduation pump.fun tokens cannot be shorted.** There is no borrow and no perp on a
  bonding-curve token. A negative-signal reading of this feed is therefore an *avoid list*,
  not a short book, until the host has migrated to PumpSwap.

---

## 7. Trials accounting and honest limits

*(filled from the final pinned run)*

---

## 8. What to do next

*(filled from the final pinned run)*
