# RESULT: bulk historical tape — what it costs, and what fidelity it buys

**Date:** 2026-08-13 · **Tool:** `scripts/bulk_history.py` · **Status:** path built, run end to end,
disqualifying defect found in the source and measured rather than assumed.

---

## Bottom line

The operator asked whether we can sync bulk data instead of paying ~206% of the monthly Helius
plan to backfill 22 days by RPC. The answer has two halves, and the second one is the important one.

1. **The bulk path works, is nearly free, and is byte-exact.** BigQuery's public Solana dataset
   holds inner-CPI token transfers whose `value` is a raw integer. Extracted for the cluster pools
   and checked against transactions the live RPC collector had independently recorded, **9 of 9
   swaps matched on every digit of both vault legs**. Cost of the day actually pulled: **58.03 GB
   scanned = $0.33 at on-demand rates, $0.00 inside the 1 TiB/month free tier.**

2. **The source is not populated, so the tape it can build is one day long.** Across six sampled
   months, the transfers table has `mint IS NULL` on 92–96% of rows and carries essentially no DEX
   flow. Exactly one day in the sample — 2026-08-12 — is loaded, and even that one is only
   **83.3% covered**. On 2026-08-13 our pools' vault transfers stop at slot 438,930,102 while the
   day runs to 439,117,724, and the slots past that point are *not* empty (369–1690 transfers
   each), they simply do not contain our pools. This is silent row loss, not a lag that fills in.

So: **bulk gives summary-grade history for flow / volume / trader-attribution analysis at ~$0, but
only for the days that happen to be loaded — currently 1 day in 22. Replay-grade history requires
RPC at the price already costed.** Nothing in any free source carries pool reserves.

The tool's most valuable feature is therefore not extraction, it is **refusing to extract silently**.
A backtest built on a day that dropped 95% of its swaps is worse than no backtest, because it looks
like a result.

---

## The four options, measured

All BigQuery figures are **real, measured on this machine** on 2026-08-13 against project
`manifest-quasar-414607` (the gcloud default project has the BigQuery API disabled; pass
`--project` or set `BULK_HISTORY_PROJECT`). Total spend for this entire investigation, tool
development and end-to-end run included: **300.4 GB = 0.273 TiB, $1.71 on-demand, $0.00 actual.**

### 1. BigQuery public Solana dataset — CHOSEN, with the caveat above

`bigquery-public-data.crypto_solana_mainnet_us` exists and is **fresh to within ~3 hours** (the
2026-08-14 partition already held 29,896 blocks when queried). Partitioning is favourable:

| table | rows | size | partition | cluster |
|---|---|---|---|---|
| `Instructions` | 1.14e12 | 936.8 TB | DAY on `block_timestamp`, `requirePartitionFilter` | `program_id` |
| `Token Transfers` | 1.45e11 | 43.9 TB | DAY on `block_timestamp`, `requirePartitionFilter` | none |
| `Accounts` | 1.64e8 | 0.14 TB | MONTH | none |

**Partitioning bounds the scan, and column pruning matters more than the row filter.** One day of
`Instructions` is 759.4 GB with `SELECT *` but 32.9 GB for the eight columns we need — a 23x lever.
Per-column costs for one day of `Token Transfers`, measured individually:

```
tx_signature 11.99 GB   source 6.53 GB   destination 6.50 GB   transfer_type 2.26 GB
block_slot    1.96 GB   authority 1.68 GB   mint 1.53 GB   value 1.23 GB   decimals 1.15 GB
```

Cost is driven by columns, **not by how many pools you filter for**, so the tool queries all pools
in one query per day rather than one query per pool. Note `tx_signature` alone is 44% of the bill
and is not optional — it is the join key to the tape contract.

Two tables could have carried a swap tape. Only one carries exact numbers:

- **`Instructions` is disqualified: it contains only top-level instructions.**
  `COUNTIF(parent_index IS NOT NULL) = 0` across a full day of PumpSwap (25,360,281 instructions).
  Measured against 528 known-good cluster swaps the live collector recorded on 2026-08-13, it
  holds a top-level PumpSwap instruction for **224 of 528 — 42.4%**. The missing 57.6% are
  aggregator-routed, where PumpSwap is invoked by CPI and is therefore invisible. It also carries
  only the *requested* Anchor args, never the realised fill. A tape that silently omits 57.6% of
  fills, biased toward exactly the routed/bot flow we care about, is not a tape.

- **`Token Transfers` does include inner CPI transfers**, and its `value` is a raw integer in base
  units (verified: no decimal scaling, no float). This is the source used.

- **`Accounts` is not a reserves fallback.** It returns **zero rows** for every cluster pool
  address. There is no pre/post pool balance anywhere in this dataset.

**The defect.** Wrapped SOL is a leg of essentially every DEX swap, so its row count is a coverage
thermometer for the whole table:

| day | total rows | WSOL rows | null-mint % |
|---|---:|---:|---:|
| 2026-02-01 | 96,057,774 | 2,433 | 96.3 |
| 2026-05-01 | 56,408,085 | 319,070 | 92.1 |
| 2026-06-15 | 72,661,809 | 7,749 | 95.9 |
| 2026-07-05 | 79,926,733 | 3,280 | 95.8 |
| 2026-07-20 | 81,097,859 | 2,763 | 95.2 |
| 2026-07-28 | 94,899,755 | 2,586 | 94.2 |
| 2026-08-04 | 105,818,194 | 2,620 | 95.1 |
| 2026-08-08 | 103,375,291 | 10,149 | 95.5 |
| 2026-08-10 | 111,066,785 | 14,156 | 95.4 |
| 2026-08-11 | 107,453,910 | 14,488 | 95.9 |
| **2026-08-12** | **216,717,409** | **42,627,164** | **55.6** |
| 2026-08-13 | 122,628,992 | 3,302,998 | 90.1 |

One day out of twelve sampled is loaded, and it has roughly twice the row count of its neighbours —
consistent with a one-off reprocessing rather than the normal pipeline. Direct confirmation at the
pool level: our four cluster mints had **1–7 transfer rows per day** on normal days against
hundreds of real swaps, and 13,784 / 36,281 / 298 / 3,426 on 2026-08-12.

This is why `preflight` exists and why it measures **per slot-bucket within the day**, not just
per day. A day-level ratio would have called 2026-08-13 usable at 2.69%; the bucket measurement
correctly reports **8.3% of the day covered**, and correctly downgrades even the good day to
**83.3%**.

### 2. Dune Analytics

Not evaluated hands-on — no account, and the decisive question was already answered by the
architecture. Dune's Solana DEX tables are *decoded trade* tables: they carry amounts, prices and
traders, not pool state. Even in the best case they are summary-grade for the same reason
`Token Transfers` is, so they would not change the fidelity verdict, only the price of getting the
same grade of data. **If summary-grade over the full 22 days is what we want, this is the option to
price out properly** — it is the one plausible way to get more than one loaded day. Flagged as the
open follow-up rather than claimed either way.

### 3. Flipside Crypto

Same as above and for the same reason: `solana.defi.fact_swaps`-style tables are decoded swaps,
not pool state. Free-tier limits were not verified in this session. Same follow-up applies.

### 4. Solana Foundation GCS ledger archives — impractical, with numbers

`gs://mainnet-beta-ledger-us-ny5/` is real and reachable but is a **requester-pays** bucket, so
every byte is billed to us, and this account's billing is currently closed (`HTTPError 403: The
billing account for the owning project is disabled`). Beyond the billing wall the arithmetic
settles it: the archive stores per-epoch RocksDB snapshots, an epoch is ~432,000 slots ≈ 2.2 days,
so 22 days is ~10 epochs at multiple TB each — **tens of TB of egress against 1.9 TB free on
/tank**, before any of it is usable, because a raw ledger must be replayed by a validator to yield
transactions at all. It does not fit on the disk, let alone in the budget. Ruled out.

---

## Fidelity: summary-grade, and exactly where the line falls

`Token Transfers` gives **deltas, never levels**. There is no pre/post reserve in this dataset.
That is the whole difference:

- **What we get, exactly:** block time, slot, signature, both vault deltas in raw integer units,
  direction, and the trader — all verified digit-for-digit against RPC.
- **What we do not get:** the reserves. Impact is a deterministic function of pool state, so
  without reserves a fill cannot be replayed. `reserves` is emitted as `null` on every row with an
  explicit `reserves_absent_reason`. It is never guessed, never inferred from a price, and never
  omitted silently.

Reserve *levels* are reconstructible in principle by cumulative-summing deltas from one anchor
balance per vault (one cheap RPC call each) — but only if the transfer stream is complete over the
whole interval, which per the table above it is not. **The tool does not implement the
reconstruction, because on this data it would produce a confidently wrong number.** If the source
were ever fully loaded, this is the first thing to build, and it is validated the same way this
report validated the deltas: chain it and check against live rows.

Two further limits that hold *even on a fully loaded day*:

- **Failed transactions do not exist in a transfers table.** A failed swap moves no tokens. The
  live tape's own composition makes the size of this gap concrete: of 79,102 recorded rows, **2,937
  are swaps and 19,061 are attempts** — attempts outnumber fills 6.5 to 1. Any study of attempt
  rate, revert rate, or competitive failure **cannot use the bulk tape at all**.
- **DLMM pools stay non-replayable regardless.** A Meteora fill walks bins; the two vault totals
  are a sum over bins and do not determine marginal price or depth. This is already recorded
  per-pool as `PoolSpec.replay_sufficient_reserves` and is a property of concentrated liquidity,
  not a gap in this source.

### One thing the bulk path does *better* than RPC

`Token Transfers.authority` is the signing authority of the debited token account. On a swap's
inbound leg that is the trader, **stated by the chain rather than inferred**. The RPC parser has to
identify the counterparty by mirroring vault deltas, which `shitcoims_cluster.parse` documents as
failing on 0 of 13 early live swaps and still returning `None` whenever a route nets to zero.

On the 9 validated swaps, `authority` recovered the trader on **all 9** — including one where the
live parser returned `counterparty: None`, and one where it differed from `fee_payer` because the
fee was sponsored. That second case is precisely the confusion `shitcoims_tape.schema` warns is a
fabricated-provenance bug. On the real pull, attribution was non-null on **100% of 30,601 rows**,
yielding 3,270 distinct traders in a day.

It is still **not** a beneficial-owner claim: for an aggregator-routed fill the authority is the
router's PDA. It is therefore emitted as `attributed_authority`, never as `wallet`.

---

## Schema compatibility: where bulk rows map, and where they must not

Rows carry their own marker, `"schema": "bulk_history.v1"`, and are **not** drop-in
`shitcoims_cluster` swap rows. Sharing field names while missing `reserves` / `fee_lamports` /
`signers` would let a consumer read a summary row as a replay row, so the marker is the guard. The
contracts are not bent to fit; the gaps are listed.

`row_id` deliberately reuses the cluster's own `sha256(f"{pool}:{signature}")`, so bulk and live
rows dedupe against each other — that is what made the 9/9 verification a one-line join.

### Against `shitcoims_cluster` swap rows

| field | bulk | note |
|---|---|---|
| `row_id`, `pool`, `dex`, `label`, `t_event` | ✅ identical | same convention |
| `chain.slot` / `.signature` / `.block_time` | ✅ | |
| `token_in_*` / `token_out_*` | ✅ raw ints as strings | verified exact |
| vault deltas | ⚠️ `delta_raw` only | **no `pre_raw` / `post_raw`** |
| `reserves` | ❌ | absent from the source entirely |
| `swap_legs` | ⚠️ `transfer_count` | related but not the same quantity |
| `fee_lamports`, `fee_payer`, `signers`, `compute_units`, `confirmation_status` | ❌ | not in a transfers table |
| `counterparty` | ⚠️ `attributed_authority` | different semantics — see above |
| `leg_discriminators`, `leg_names` | ❌ | needs instruction-level data |
| `kind: attempt` / `reference` rows | ❌ | failed txs move no tokens |

### Against `shitcoims_tape.schema`

- `Chainstamp` — `slot`, `signature`, `block_time` all satisfied. `tx_index` stays `None`; the
  transfers table has no block index, so the intra-slot ordering ambiguity `parse.py` already
  documents is **not** resolved by this path either.
- `Provenance` — fully satisfied: `source` = `bigquery.crypto_solana_mainnet_us.token_transfers`
  (valid under the `_IDENT` pattern), `fetched_at` = extraction time, `cursor` = the BigQuery job
  id, which makes any row traceable to the exact billed job.
- `Reserves` — **cannot be constructed at all.** Every one of `virtual_sol`, `virtual_tokens`,
  `real_sol`, `real_tokens` is unavailable. No `EventKind.RESERVE` event can be emitted from bulk.
- `Trade` — partially constructible, and the gaps are load-bearing:
  - `wallet` is **required** by the dataclass, and `attributed_authority` is not a safe value for
    it on routed fills. Do not fill it in to satisfy the type.
  - `side` assumes a quote asset. It is derivable for the four SOL-quoted pools; for `weave/nosis`
    and `DREGG/nosis` there is no buy/sell direction and the `Side` enum does not apply.
  - `sol_delta_lamports` likewise exists only for SOL-quoted pools.
  - `fee_lamports` would have to be faked as `0`; its default is `0`, which is exactly the kind of
    silent zero that reads as measured. Leave it unset rather than defaulted.
  - `routed_via_frontend` — unavailable, and it is the literature's only estimation-free bot proxy.

**The sharpest hazard, and the reason bulk rows are not simply appended to the tape:**
`TapeEvent.observed_at` means *when we saw it*, and the schema's second load-bearing decision is
that observer lag is real and must be modelled as delayed entry. For a bulk row, `observed_at` is
the extraction timestamp — days after the event. Feeding bulk rows into a survival model that
treats `observed_at` as delayed entry would manufacture a lag distribution out of when we happened
to run a query. Bulk rows are a **separate stream with `t_event` as their only meaningful clock**.

---

## The run actually executed

```
python3 scripts/bulk_history.py selftest                                      # 23/23 offline
python3 scripts/bulk_history.py vaults                                        # 12 vaults, 6/7 pools
python3 scripts/bulk_history.py preflight --start 2026-08-10 --end 2026-08-13
python3 scripts/bulk_history.py pull --start 2026-08-12 --end 2026-08-12 --allow-partial
python3 scripts/bulk_history.py verify
```

**Preflight** — 15.40 GB for 4 days (3.85 GB/day):

```
day          verdict    covered  wsol/total     total rows
2026-08-10   EMPTY         0.0%       0.01%    111,066,785
2026-08-11   EMPTY         0.0%       0.01%    107,453,910
2026-08-12   PARTIAL      83.3%      19.67%    216,717,409
2026-08-13   PARTIAL       8.3%       2.69%    122,628,992
```

The guard fired as designed — the first `pull` attempt **refused** 2026-08-12 and required an
explicit `--allow-partial`.

**Pull, 2026-08-12, all 12 known vaults in one query** — dry-run upper bound 58.03 GB, **actual
billed 58.03 GB ($0.33 on-demand, $0.00 in free tier)**; 107,087 raw transfers folded into
**30,601 rows** (30,085 swaps + 516 liquidity/fee flows), 0 defects, 49 MB JSONL.

| pool | dex | swaps | traders | SOL volume |
|---|---|---:|---:|---:|
| nosis/SOL | pumpswap | 18,329 | 2,126 | 35,560.4 |
| weave/SOL | pumpswap | 9,917 | 1,394 | 9,498.6 |
| DREGG/SOL | pumpswap | 1,637 | 216 | 1,270.4 |
| SOLVE/SOL | pumpswap | 202 | 90 | 116.9 |
| weave/nosis, DREGG/nosis | meteora_dlmm | 0 | — | — |

**Verify, against the live RPC tape:** 9 comparable swaps, **9 exact raw-delta matches, 0
disagreements, 0 absent — 100% recall.**

**Idempotency/resumability:** re-running the same range skips the completed day and re-reports
**$0.00**; preflight results are cached so a re-measure is free. Writes are atomic (temp + rename),
and every output file carries source, full query text, query SHA-256, job id, billed bytes,
extraction time, and the coverage measurement for its day.

**Two honest caveats on this run.** Both Meteora pools with known vaults returned zero rows, and on
an 83%-covered day *we cannot distinguish "idle" from "not loaded"* — do not read that as evidence
they were quiet. And the seventh pool, `77Nm2cKt…` (weave/SOL DLMM, added 2026-08-13), has no
recorded swaps yet so its vaults are unknown; the tool **warns loudly** that it will be missing
rather than silently returning a short tape. Vault addresses are derived from the live tape at
runtime, never hard-coded, because `pools.py` is right that a hard-coded vault table is a second
source of truth that drifts.

---

## Cost curve — decide by what you need to backtest

Per-day scan cost is column-driven and **independent of how many pools you ask for**: all 12 vaults
for a normal-sized day estimate at **22.83 GB** (measured by `--dry-run` on 2026-08-11), rising to
58.03 GB on the double-sized 2026-08-12, plus **3.85 GB/day** of preflight. A full 22-day sweep is
therefore ~502 GB of pull + ~85 GB of preflight ≈ **587 GB — inside the 1 TiB/month free tier**.

| what you want | source | cost | what you can backtest |
|---|---|---|---|
| 22 days, summary-grade | BigQuery | ~587 GB scanned → **$0 in free tier** (~$3.34 on-demand) | **almost nothing — only ~1 day of 22 is loaded** |
| 1 loaded day, summary-grade | BigQuery | 58 GB → **$0.33 / $0 free** | flow, volume, trader attribution, inter-pool timing |
| 22 days, summary-grade, *actually complete* | Dune / Flipside | not yet priced | same as above, over the full window |
| 22 days, replay-grade | RPC backfill | **206% of the monthly Helius plan** | fills, impact, slippage, execution policy |
| 1 day, replay-grade | RPC backfill | 9.4% of monthly plan | as above, one day |
| 1 week, replay-grade | RPC backfill | 66% of monthly plan | as above, one week |

The decision is not bulk-versus-RPC on price. It is: **fills or flow?**

- Backtesting an **execution policy** — entry price, slippage, impact, stop behaviour — needs
  reserves, so it needs RPC. No free source has reserves; that was checked, not assumed.
- Backtesting **flow signals** — volume, trader arrival, cross-pool timing, wallet attribution —
  does not need reserves, and bulk delivers it exactly, for free, on the days that exist.

**Recommendation.** Do not buy 22 days of RPC on the strength of this. Spend the next hour pricing
Dune and Flipside, because they are the only realistic route to a *complete* 22-day summary tape,
and a complete summary tape is what most of the open flow questions actually need. Then, if and
only if a study needs fills, buy replay-grade RPC for the **shortest window that answers it** —
one day is 9.4% of the plan and is enough to validate a fill model that the free summary tape can
then be used to apply broadly.

Meanwhile the live collector keeps producing replay-grade rows at zero marginal cost. It has
already recorded 2,937 swaps with full reserves. Every day it runs, the replay-grade window grows
for free — which is a stronger argument for *keeping it healthy* than for buying history.
