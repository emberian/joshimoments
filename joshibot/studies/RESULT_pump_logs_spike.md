# RESULT: the firehose is complete, sustainable and decodable — and it is metered, so it is not free

2026-08-15. `scripts/pump_logs_spike.py`, 17.4 minutes of live streaming in four bounded
windows (45 s, 40 s, **720 s primary**, 180 s), plus a 60 s probe of the filtered feed.
1.12 M log notifications on the primary window alone.

The spike was launched on a hypothesis: **standard Helius websockets are included, not
credit-metered, so a `logsSubscribe` firehose plus a stream-reducer buys platform-wide live
surge detection for ~$0.** Three of the four load-bearing claims survived contact with
measurement. The one that did not is the one the whole plan rested on.

| Question | Verdict | The measurement |
|---|---|---|
| **Sustained?** | **YES** — emphatically | 720 s, 1,116,600 messages, **1,552 msg/s combined**, peak 2,568/s on one program. Zero disconnects, zero reconnects, zero reconnect-gaps. Rate did not degrade: first half 866/s → second half 927/s (pump.fun). Our own receive loop spent 52 s of the 720 s working, so the client was never the bottleneck. |
| **Complete?** | **YES** — more complete than the RPC index | Recall **1.000** on both programs against `getSignaturesForAddress` over interior slot ranges (3,409 / 3,409 and 1,805 / 1,805). **Zero missing slots** — 1,711 of 1,711 and 1,716 of 1,716 contiguous. Independent vendor cross-check: 340 of 341 PumpPortal creates present (0.9971). |
| **Metered?** | **YES — the hypothesis is false** | Helius unified streaming billing at **20 credits per uncompressed MB** on 2026-04-07 and switched metering on for previously-unmetered WSS on **2026-05-01**. LaserStream now backs the standard `wss://` endpoint, so there is no unmetered path left. Not measurable on our key (no usage endpoint exists — four candidates, all 404, no credit headers); bounded from published pricing. |
| **Reducible?** | **YES** — zero follow-up RPC | Every event rides in the `logs` array as a `Program data:` line. 42,565 rows decoded from notifications alone in 720 s. Verified two ways: 340/340 decoded mints agree with PumpPortal's independent report, and three trades spot-checked against `getTransaction` match in sign and magnitude within the fee schedule. |
| **Cost** | **~$716–738/month** for both programs | 238.9 GB/day → 143 M credits/month → $49 + $667 overage on Developer. Identical on Business ($499 + $217). |

**VERDICT: NO-GO on the ~$0 platform-wide firehose.** GO on two much cheaper subsets, below.

---

## 1. The premise died on a pricing page, not on the wire

The wire behaved perfectly. Helius delivered 1.12 M notifications across two subscriptions for
twelve minutes without dropping a single slot, and delivered them within a slot of the
validator confirming them.

Delivery lag was measured clock-free — sampling `getSlot` at the same commitment and
subtracting each stream's high-water mark, bracketed either side of the RPC round trip, 68
samples over the window. Median **1 slot** (pessimistic bracket) / **0 slots** (optimistic),
**85% within 2 slots**, and on two occasions the stream was *ahead* of what `getSlot`
reported. The tail is honest though: **8% of samples exceeded 4 slots and the worst was 15
(~6 s)**, so this is a fast feed with occasional multi-second excursions, not a hard latency
guarantee.

But since **2026-05-01** every byte of that is billed at 20 credits/MB, and the bytes are the
problem:

| | msg/s | MB/s | GB/day | credits/month | Developer $/mo |
|---|---|---|---|---|---|
| pump.fun `logsSubscribe` | 896 | 1.016 | 87.8 | 52.7 M | **$262** |
| PumpSwap `logsSubscribe` | 656 | 1.750 | 151.2 | 90.7 M | **$453** |
| **both** | **1,552** | **2.765** | **238.9** | **143.3 M** | **$716** |

Our plan is Developer — $49/mo, **10 M credits** (`PROGRAM.md:395`). At 20 credits/MB that
allowance is **500 GB/month**. The firehose is **7.2 TB/month**. We are not 20% over the free
lunch; we are **14.3×** over it.

Two consequences worth stating plainly:

- **The tier ladder does not help.** Overage is $5/M credits on every paid tier, so Developer
  and Business cost *exactly the same* ($716) at this volume — the $450 tier upgrade buys back
  exactly $450 of overage and nothing else. Professional's $999 flat is strictly worse until
  ~200 M credits/month. There is no plan on which this firehose is cheap.
- **The node comparison inverts.** A $400–600/mo dedicated node is *unmetered*. At full
  two-program coverage the metered websocket is **more expensive than the node it was supposed
  to avoid.**

### What "free" actually buys

Within the existing 10 M credits, at $0 marginal cost, the firehose runs:

- both programs: **1.7 hours/day**
- pump.fun only: **4.6 hours/day**
- pump.fun filtered (§4): **7.3 hours/day**

Duty-cycled surveillance is a real product — but it is not "live platform-wide surge
detection," because a surge that happens in the other 22 hours is invisible.

---

## 2. Two surprises that change other studies

**The websocket is more complete than `getSignaturesForAddress`.** On the scored PumpSwap slot
range the stream delivered **2,299** transactions; the signature index returned **1,805**.
Recall ran 1.000 in the direction we tested — everything the index knew, the stream had — but
**494 transactions (21.5%) that the stream saw are absent from the index entirely.** The
`mentions` filter matches a program that was *invoked*, including through CPI and
address-lookup-table routing; the signature index does not appear to. Aggregator-routed
PumpSwap fills are exactly the shape that falls in this gap.

This is a defect notice for every historical collector we run: **anything sampling PumpSwap
activity via `getSignaturesForAddress` is missing roughly a fifth of it, and missing it
non-randomly** — the missing fifth is the aggregator-routed flow, which is not a random fifth
of anything. Same probe on pump.fun found zero such gap (0 of 3,409), so this is PumpSwap-
specific and consistent with routing rather than with indexer lag.

**Nine of ten pump.fun transactions fail.** 580,908 of 644,563 messages carried a non-null
`err` — a **90.1% failure rate**, independently corroborated at 79.8% by the `err` field in the
RPC index over the same slots. The "~83 M pump-touching transactions/day" figure is real, and
our measured 896/s matches it closely — but it is overwhelmingly a count of *sniper bots
losing races*. Real economic pump.fun events run **~59/s**, not ~900/s.

By bytes rather than counts, the spam is 74.6% of the pump.fun stream and only 22.4% of its
bytes carry a decodable event. **We would be paying $262/mo mostly to receive failed
transactions.** PumpSwap is the opposite: 33% of messages fail but 72.3% of bytes carry an
event, because its successful messages are fat (p95 8,147 bytes vs pump.fun's 2,607).

---

## 3. The reducer needs zero follow-up RPC, and that part is solid

The doubt worth having was whether `logsSubscribe` payloads carry the structured event data or
only human-readable log text, since `shitcoims_cluster/pumpswap.py` decodes those events out of
transaction *meta* (inner instructions). They carry it — with one wrinkle:

**These programs use bare `emit!`, not `emit_cpi!`.** The `Program data:` base64 begins
directly with the 8-byte event discriminator, with **no** `e445a52e51cb9a1d` anchor CPI tag.
`decode_swap_event` checks for that tag and returns `None` without it, so **the existing decoder
silently returns nothing on log-sourced bytes** — a one-line re-wrap fixes it, and the spike
does exactly that. This is a real trap for whoever builds the reducer: the failure mode is
"decodes zero events", not an exception.

Decoded live, no `getTransaction` anywhere:

- **pump.fun `TradeEvent`** (`bddb7fd34ee661ee`) → mint, side, SOL lamports, token amount, user,
  timestamp. 42,150 decoded, **42,150 with a timestamp within 120 s of receipt, zero outside**.
- **pump.fun `CreateEvent`** (`1b72a94ddeeb6376`) → name, symbol, uri, mint, bonding curve, user.
- **PumpSwap Buy/Sell** → pool, side, both reserves. 192,639 decoded in 720 s.

Verification, because a decode that parses is not a decode that is *correct*:

- **340 of 340** mints decoded from log lines match the mint PumpPortal independently reported
  for the same signature. A wrong field layout cannot pass this.
- Three trades fetched with `getTransaction`: decoded `sol_amount` 273,910,544 vs on-chain user
  delta +267,666,795 (sell); 977,777 vs −1,025,000 (buy); 198,117,879 vs −204,074,279 (buy).
  Correct sign, correct magnitude, residual equals the documented fee schedule plus tx fee.

**Reducer output volume:** 327 rows/s combined → **28 M rows/day**, ~50 bytes each ≈ **1.4
GB/day**, from 238.9 GB/day of input. The 170× reduction the plan assumed is real. It is the
*input* side that costs money, and no reducer can make the input cheaper.

One gap for the builder: pump.fun rows are **mint-keyed** directly, but PumpSwap `SwapEvent`
carries only the **pool**. Platform-wide PumpSwap surge detection needs a pool→mint map, and
`shitcoims_cluster/pools.py` is a hardcoded 2-address watchlist. That map is learnable lazily
and cacheable forever, but it is unbuilt work and it needs an RPC method that
`READ_METHODS` does not currently whitelist.

---

## 4. The cheapest complete live option measured is $165/mo, and it is not `logsSubscribe`

Since the meter charges by the byte, the lever is server-side filtering — and `logsSubscribe`
has none. `transactionSubscribe` on the enhanced endpoint does, and the question of whether
our plan may use it was asked on the wire rather than assumed:

**It was accepted on this key.** `{"failed": false, "accountInclude": [pump.fun]}`, 60 s,
5,430 transactions, **0 failed delivered** — the filter is honoured.

| pump.fun, live and complete | msg/s | MB/s | GB/day | Developer $/mo |
|---|---|---|---|---|
| `logsSubscribe` (everything) | 710 | 0.832 | 71.8 | $215 |
| `transactionSubscribe` (`failed:false`) | 90.5 | 0.639 | 55.2 | **$165** |

The saving is **23%, not the 90% the message counts suggest** — 7.8× fewer messages, but each
is a full base64 transaction averaging 7,087 bytes against a 912-byte median log notification.
Dropping the spam mostly buys back what the fatter envelope costs. Worth having, not
transformative, and it was **not** recall-tested here — only the log streams were.

---

## 5. What this study cannot tell you

- **The meter was never observed debiting.** No Helius usage endpoint exists on this key
  (`/v0/usage`, `/v0/credits`, `/v0/account-usage`, `/v0/rpc-usage`, `/v0/plan` — all 404; no
  credit headers on RPC responses). Every dollar here is derived from published rates, not
  from an observed balance. **Falsifiable prediction: the dashboard should show ≈54,800
  credits consumed between 16:55 and 17:20 UTC on 2026-08-15 from 2.74 GB streamed. If it
  shows ~0, WSS metering is not live on this key and the verdict flips to GO.** Check this
  before spending anything on the alternatives.
- **Twelve minutes is not a day.** Per-window pump.fun rates ranged 533–1,340 msg/s across the
  four windows. The 12-minute mean of 896/s sits close to the ~960/s implied by 83 M/day, so
  the extrapolation is anchored, but ±30% on the monthly bill is honest.
- **Byte counts for the primary window are a slight under-count.** It measured message length
  in characters; the fix to count UTF-8 bytes landed for the 180 s window, which read 3%
  higher (2.850 vs 2.765 MB/s). Costs quoted from the primary window are therefore floors.

## 6. Recommendation

**Do not build the always-on platform-wide reducer on standard websockets.** It is not $0, it
is ~$716/mo, and that is more than the dedicated node it was meant to replace.

Ranked by value per dollar:

1. **PumpPortal's free `newToken`/`migration` feed** — $0, already implemented in
   `shitcoims_scalper/firehose.py`, and it delivered 341 creates in 12 minutes with 99.7%
   agreement against the chain. For *new-token* surge detection specifically, this is done.
2. **pump.fun only, `transactionSubscribe` with `failed:false`** — **$165/mo**, complete live
   coverage of the launchpad where our edge research actually lives. Cheapest complete option
   measured, and it fits inside the plan at a 7.3 h/day duty cycle for $0.
3. **Both programs, all the time** — $716/mo metered, or a $400–600/mo unmetered node.
   **Gate this on desk scaling, as originally framed** — and if it is ever wanted, the node is
   now the *cheaper* of the two, which is the opposite of the assumption we started with.

Independently of the streaming decision, §2's index gap should be treated as a defect: our
PumpSwap history is missing ~21% of transactions, non-randomly.
