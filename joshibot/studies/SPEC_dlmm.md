# SPEC — Meteora DLMM (LB CLMM) ground-truth semantics

Program: `LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo` (crate `lb_clmm`, IDL version **0.12.0**, Anchor IDL spec 0.1.0).

Purpose: a byte- and integer-exact description of the on-chain program, precise enough to be transcribed
into a Lean 4 formalisation without further guessing. Every claim carries a provenance tag:

| tag | meaning |
|---|---|
| **[CHAIN]** | verified by me against real mainnet accounts / transactions during this study |
| **[IDL]** | taken from the *on-chain* Anchor IDL account (authoritative for the deployed program's declared shape) |
| **[SRC-0.12]** | Meteora's own SDK reimplementation shipped alongside IDL 0.12.0 (`MeteoraAg/dlmm-sdk`, crate `commons` v0.3.3, commit `fb02e51`) |
| **[SRC-0.8.2]** | the last publicly available copy of the *program* source tree (`programs/lb_clmm/src`, v0.8.2). Handler bodies are stubbed in every public copy; state/math modules are complete |
| **[INFER]** | derived by me, not directly read or observed |

### Provenance caveats you must carry into the Lean model

1. **There is no public copy of the deployed program's instruction handlers.** Meteora publishes only the
   `#[derive(Accounts)]` context structs; every `handle_*` body in every public copy (crates.io `lb_clmm`
   0.1.1, the vendored v0.8.2 trees) is literally `Ok(())`. The *orchestration* below (order of
   `update_references` / `update_volatility_accumulator` / bin traversal / `last_update_timestamp` write)
   was therefore reconstructed from Meteora's own quoter (`commons/src/quote.rs`) plus **direct
   observational fitting against mainnet**, and the fit is exact (see §3.6). It is not read off source.
2. **v0.8.2 `Bin` and 0.12.0 `Bin` are both 144 bytes but mean different things.** In 0.8.2 the tail is
   `reward_per_token_stored: [u128;2]`, `amount_x_in: u128`, `amount_y_in: u128`; in 0.12.0 those same bytes
   are the limit-order fields. Decoding a current bin with the old struct is silent garbage. `commons`
   0.12.0 even reconstitutes `reward_per_token_stored[0]` by concatenating
   `fulfilled_order_amount_x ‖ fulfilled_order_amount_y` and `[1]` from
   `limit_order_fee_ask_side ‖ limit_order_fee_bid_side` **[SRC-0.12]** — i.e. the reward accumulators
   still physically live in those bytes for non-limit-order pools; the union is discriminated by
   `StaticParameters.function_type`.
3. v0.8.2's `get_base_fee` has **no** `base_fee_power_factor` term. The 0.12.0 form does. Use 0.12.0.

---

## 0. Constants

**[IDL]** (the on-chain IDL exports these; values cross-checked against **[SRC-0.12]** `commons/src/constants.rs`)

```
BASIS_POINT_MAX              = 10_000        (u16)
FEE_DENOMINATOR/FEE_PRECISION= 1_000_000_000 (u64)   -- fee rates are in 1e9 units, NOT bps
MAX_FEE_RATE                 = 100_000_000   (u64)   -- 10%
MAX_BASE_FEE                 = 100_000_000   (u128)  -- 10%
MIN_BASE_FEE                 = 100_000       (u128)  -- 0.01%
MAX_PROTOCOL_SHARE           = 2_500         (u16)   -- 25% of the trading fee
PROTOCOL_SHARE (default)     = 500           (u16)
ILM_PROTOCOL_SHARE           = 2_000         (u16)
HOST_FEE_BPS                 = 2_000         (u16)   -- 20% of the protocol fee
LIMIT_ORDER_FEE_SHARE        = 5_000         (u16)
MAX_BIN_PER_ARRAY            = 70
DEFAULT_BIN_PER_POSITION     = 70
POSITION_MAX_LENGTH          = 1_400
MAX_RESIZE_LENGTH            = 91            (u64)   -- NOTE: commons/src/constants.rs says 70; IDL says 91
BIN_ARRAY_BITMAP_SIZE        = 512           (i32)
EXTENSION_BINARRAY_BITMAP_SIZE = 12
NUM_REWARDS                  = 2
MAX_REWARD_BIN_SPLIT         = 15
MAX_BIN_STEP                 = 400
MAX_BIN_ID_PER_BIN_STEP      = 351_639       (i32)
MINIMUM_LIQUIDITY            = 1_000_000     (u128)
SCALE_OFFSET                 = 64                    -- Q64.64 everywhere  [SRC]
ONE                          = 1 << 64
MAX_EXPONENTIAL              = 0x80000 = 1_048_576   -- pow() domain guard  [SRC]
MIN_BIN_ID / MAX_BIN_ID      = -443_636 / 443_636    -- global, 1bps-derived  [SRC]
DEFAULT_OBSERVATION_LENGTH   = 100
SAMPLE_LIFETIME              = 120           (seconds, oracle)
```

PDA seeds **[SRC-0.12]** `commons/src/seeds.rs`, PDA derivations **[CHAIN]**-confirmed for `bin_array` and `oracle`:

```
bin_array   : ["bin_array",  lb_pair(32), index_i64_le(8)]      -> BinArray        [CHAIN]
oracle      : ["oracle",     lb_pair(32)]                        -> Oracle          (LbPair.oracle field [CHAIN])
bitmap ext  : ["bitmap",     lb_pair(32)]                        -> BinArrayBitmapExtension
position    : ["position", ...]                                  (initialize_position_pda only)
preset param: ["preset_parameter"] / ["preset_parameter2"]
token badge : ["token_badge", mint(32)]
cf operator : ["cf_operator", ...]
operator    : ["operator", ...]
ILM_BASE_KEY = MFGQxwAmB91SwuYX36okv2Qmdc9aMuHTwWGUrp4AtB1
```

---

## 1. Account layouts, byte-exact

All accounts below are Anchor `#[account(zero_copy)]` = `#[repr(C)]` + bytemuck `Pod`, so offsets follow
C layout rules (field offsets rounded up to field alignment; struct size rounded up to struct alignment).
`pubkey` is `[u8;32]`, **alignment 1**. All integers little-endian.

Offsets in the tables are **absolute** (i.e. including the 8-byte Anchor discriminator).

### 1.1 Discriminators **[IDL]**, sizes **[CHAIN]**

| account | discriminator (hex) | size | census (mainnet, confirmed) |
|---|---|---|---|
| `LbPair` | `210b3162b565b10d` | **904** | 153 867 |
| `Oracle` | `8bc283b38cb3e5f4` | **32 + 32·length** (3232 at length=100) | 153 865 |
| `BinArray` | `5c8e5cdc059446b5` | **10 136** | 451 654 |
| `PositionV2` | `75b0d4c7f5b485b6` | **8 120** base, **280 + 112·W** when resized | 173 848 at 8120, 153 at 10136 |
| `BinArrayBitmapExtension` | `506f7c7137ed1205` | **1 576** | 6 285 |
| `PresetParameter` | `f23ef422b5703aaa` | 40 | |
| `PresetParameter2` | `abec9473a271deae` | 192 | |
| `LimitOrder` | `89b7d45b731d8de3` | 120 | |
| `ClaimFeeOperator` | `a630865622c8bc96` | 168 | |
| `Operator` | `db1fbc91458bcc75` | 72 | |
| `TokenBadge` | `74dbcce5f974ff96` | 168 | |
| `DummyZcAccount` | `5e6bee50d030b408` | 120 | IDL-only helper exposing `PositionBinData` |

Legacy sizes **do not exist on chain**: a `getProgramAccounts` census returned **0** accounts at 5656
(pre-migration `BinArray`) and **0** at 7560 (`Position` v1). Every `BinArray` carries `version = 2`
**[CHAIN]**. A model may therefore assume the current layout universally.

### 1.2 `LbPair` — 904 bytes **[IDL]** + spot-checked **[CHAIN]**

The user's prior claims are **CONFIRMED**: `active_id` at `8+68` (i32), `bin_step` at `8+72` (u16),
`token_x_mint` at `8+80`, `token_y_mint` at `8+112`.

| abs | rel | size | field | type |
|---|---|---|---|---|
| 0 | | 8 | discriminator | `210b3162b565b10d` |
| 8 | +0 | 32 | `parameters` | `StaticParameters` |
| 40 | +32 | 32 | `v_parameters` | `VariableParameters` |
| 72 | +64 | 1 | `bump_seed` | `[u8;1]` |
| 73 | +65 | 2 | `bin_step_seed` | `[u8;2]` |
| 75 | +67 | 1 | `pair_type` | u8 |
| 76 | +68 | 4 | **`active_id`** | **i32** |
| 80 | +72 | 2 | **`bin_step`** | **u16** |
| 82 | +74 | 1 | `status` | u8 |
| 83 | +75 | 1 | `require_base_factor_seed` | u8 |
| 84 | +76 | 2 | `base_factor_seed` | `[u8;2]` |
| 86 | +78 | 1 | `activation_type` | u8 |
| 87 | +79 | 1 | `creator_pool_on_off_control` | u8 |
| 88 | +80 | 32 | **`token_x_mint`** | pubkey |
| 120 | +112 | 32 | **`token_y_mint`** | pubkey |
| 152 | +144 | 32 | `reserve_x` | pubkey |
| 184 | +176 | 32 | `reserve_y` | pubkey |
| 216 | +208 | 16 | `protocol_fee` | `ProtocolFee { amount_x:u64 @+208, amount_y:u64 @+216 }` |
| 232 | +224 | 32 | `_padding_1` | `[u8;32]` |
| 264 | +256 | 288 | `reward_infos` | `[RewardInfo;2]` (144 each) |
| 552 | +544 | 32 | `oracle` | pubkey |
| 584 | +576 | 128 | `bin_array_bitmap` | `[u64;16]` (U1024, bin-array indices −512..511) |
| 712 | +704 | 8 | `last_updated_at` | i64 (fee-parameter update time, **not** the volatility clock) |
| 720 | +712 | 32 | `_padding_2` | `[u8;32]` |
| 752 | +744 | 32 | `pre_activation_swap_address` | pubkey |
| 784 | +776 | 32 | `base_key` | pubkey |
| 816 | +808 | 8 | `activation_point` | u64 |
| 824 | +816 | 8 | `pre_activation_duration` | u64 |
| 832 | +824 | 8 | `_padding_3` | `[u8;8]` |
| 840 | +832 | 8 | `_padding_4` | u64 |
| 848 | +840 | 32 | `creator` | pubkey |
| 880 | +872 | 1 | `token_mint_x_program_flag` | u8 (0 = SPL Token, 1 = Token-2022) |
| 881 | +873 | 1 | `token_mint_y_program_flag` | u8 |
| 882 | +874 | 1 | `version` | u8 (observed 1) |
| 883 | +875 | 21 | `_reserved` | `[u8;21]` |
| | | **896** | struct size (align 16) → **904** with discriminator | |

`RewardInfo` (144, align 16): `mint` pubkey @0, `vault` pubkey @32, `funder` pubkey @64,
`reward_duration` u64 @96, `reward_duration_end` u64 @104, `reward_rate` u128 @112,
`last_update_time` u64 @128, `cumulative_seconds_with_empty_liquidity_reward` u64 @136.

### 1.3 `StaticParameters` — 32 bytes **[IDL]**, values **[CHAIN]**

| rel (within struct) | abs in LbPair | size | field | type |
|---|---|---|---|---|
| 0 | 8 | 2 | `base_factor` | u16 |
| 2 | 10 | 2 | `filter_period` | u16 (seconds) |
| 4 | 12 | 2 | `decay_period` | u16 (seconds) |
| 6 | 14 | 2 | `reduction_factor` | u16 (bps) |
| 8 | 16 | 4 | `variable_fee_control` | u32 |
| 12 | 20 | 4 | `max_volatility_accumulator` | u32 |
| 16 | 24 | 4 | `min_bin_id` | i32 |
| 20 | 28 | 4 | `max_bin_id` | i32 |
| 24 | 32 | 2 | `protocol_share` | u16 (bps) |
| 26 | 34 | 1 | `base_fee_power_factor` | u8 |
| 27 | 35 | 1 | `function_type` | u8 (0 Undetermined, 1 LiquidityMining, 2 LimitOrder) |
| 28 | 36 | 1 | `collect_fee_mode` | u8 (0 InputOnly, 1 OnlyY) |
| 29 | 37 | 3 | `_padding` | `[u8;3]` |

**[CHAIN]** Mainnet census over all 153 867 pools (value → count, top values):

```
bin_step         100:37670  80:20404  125:16431  250:14809  200:14165  400:13468  1:7381  20:5276  2:5269  50:5175
base_factor      10000:38307  20000:24600  12500:12972  8000:11039  40000:10665  50000:9423  5000:8932
filter_period    300:115809  10:16425  30:16402  120:5066  0:165
decay_period     1200:120875  120:16425  600:16402  0:165
reduction_factor 5000:153702  0:165                       <-- effectively a constant: halving
variable_fee_control 7500:115809  2000000:7182  50000:5514  20000:5194  10000:5066  120000:3920  500000:3729
max_volatility_accumulator 150000:121323  350000:12482  250000:8795  100000:7182  300000:3920
protocol_share   1000:148226  2000:5616  500:25
base_fee_power_factor 0:148240  1:5603  2:24
function_type    0:143839  2:9663  1:365
collect_fee_mode 0:149141  1:4726
pair_type        0:74379  3:73762  2:5616  1:110
status           0:153791  1:76
```

`(filter_period, decay_period)` is always one of `(300,1200)`, `(10,120)`, `(30,600)`, `(120,1200)`,
`(0,0)`. `reduction_factor` is 5000 (exact halving) in 99.9% of pools.

### 1.4 `VariableParameters` — 32 bytes **[IDL]**

| rel | abs in LbPair | size | field | type |
|---|---|---|---|---|
| 0 | 40 | 4 | `volatility_accumulator` | u32 |
| 4 | 44 | 4 | `volatility_reference` | u32 |
| 8 | 48 | 4 | `index_reference` | i32 |
| 12 | 52 | 4 | `_padding` | `[u8;4]` |
| 16 | 56 | 8 | `last_update_timestamp` | i64 |
| 24 | 64 | 8 | `_padding_1` | `[u8;8]` |

### 1.5 `Bin` — 144 bytes, align 16 **[IDL]**, size **[CHAIN]** (10136 = 56 + 70·144)

| rel | size | field | type |
|---|---|---|---|
| 0 | 8 | `amount_x` | u64 — MM token X in the bin, **protocol fees already excluded** |
| 8 | 8 | `amount_y` | u64 |
| 16 | 16 | `price` | u128 — Q64.64, lazily materialised (0 ⇒ never touched) |
| 32 | 16 | `liquidity_supply` | u128 — Q64.64 |
| 48 | 8 | `fulfilled_order_amount_x` | u64 ‖ ⎫ for non-limit-order pools these 16 bytes are |
| 56 | 8 | `fulfilled_order_amount_y` | u64 ‖ ⎭ `reward_per_token_stored[0]` (u128) |
| 64 | 8 | `limit_order_fee_ask_side` | u64 ‖ ⎫ …and these 16 are `reward_per_token_stored[1]` |
| 72 | 8 | `limit_order_fee_bid_side` | u64 ‖ ⎭ |
| 80 | 16 | `fee_amount_x_per_token_stored` | u128 — Q64.64 |
| 96 | 16 | `fee_amount_y_per_token_stored` | u128 — Q64.64 |
| 112 | 8 | `open_order_amount` | u64 |
| 120 | 8 | `total_processing_order_amount` | u64 |
| 128 | 8 | `processed_order_remaining_amount` | u64 |
| 136 | 4 | `order_age` | u32 |
| 140 | 1 | `limit_order_ask_side` | u8 |
| 141 | 3 | `_padding_1` | `[u8;3]` |

The reward-accumulator aliasing is **[SRC-0.12]** (`DynamicPosition::decode_reward_per_token_stored`),
and matches v0.8.2's `Bin` where those bytes *are* `reward_per_token_stored: [u128;2]` **[SRC-0.8.2]**.

### 1.6 `BinArray` — 10 136 bytes **[IDL]+[CHAIN]**

| abs | rel | size | field |
|---|---|---|---|
| 0 | | 8 | discriminator `5c8e5cdc059446b5` |
| 8 | +0 | 8 | `index` : i64 (bin-array index, **not** bin id) |
| 16 | +8 | 1 | `version` : u8 (2 on all mainnet accounts) |
| 17 | +9 | 7 | `_padding` `[u8;7]` |
| 24 | +16 | 32 | `lb_pair` : pubkey |
| 56 | +48 | 10080 | `bins` : `[Bin;70]` — bin `i` at `56 + 144·(i − 70·index)` |

### 1.7 `PositionV2` — 8 120 bytes base, **resizable** **[IDL]+[CHAIN]**

The user's prior claim is **CONFIRMED exactly**:
`8 disc | 32 lb_pair | 32 owner | 70×u128 liquidity_shares | 70×48 reward_infos | 70×48 fee_infos |
i32 lower | i32 upper | i64 last_updated | u64 claimed_x | u64 claimed_y | …`

| abs | rel | size | field | type |
|---|---|---|---|---|
| 0 | | 8 | discriminator `75b0d4c7f5b485b6` | |
| 8 | +0 | 32 | `lb_pair` | pubkey |
| 40 | +32 | 32 | `owner` | pubkey |
| 72 | +64 | 1120 | `liquidity_shares` | `[u128;70]` — **Q64.64** |
| 1192 | +1184 | 3360 | `reward_infos` | `[UserRewardInfo;70]` (48 each) |
| 4552 | +4544 | 3360 | `fee_infos` | `[FeeInfo;70]` (48 each) |
| 7912 | +7904 | 4 | `lower_bin_id` | i32 |
| 7916 | +7908 | 4 | `upper_bin_id` | i32 |
| 7920 | +7912 | 8 | `last_updated_at` | i64 |
| 7928 | +7920 | 8 | `total_claimed_fee_x_amount` | u64 |
| 7936 | +7928 | 8 | `total_claimed_fee_y_amount` | u64 |
| 7944 | +7936 | 16 | `total_claimed_rewards` | `[u64;2]` |
| 7960 | +7952 | 32 | `operator` | pubkey |
| 7992 | +7984 | 8 | `lock_release_point` | u64 |
| 8000 | +7992 | 1 | `_padding_0` | u8 (tombstone) |
| 8001 | +7993 | 32 | `fee_owner` | pubkey (**unaligned by design** — pubkey has align 1) |
| 8033 | +8025 | 1 | `version` | u8 |
| 8034 | +8026 | 1 | `permissionless_operation_bits` | u8 |
| 8035 | +8027 | 85 | `_reserved` | `[u8;85]` |
| | | **8112** | struct size (align 16) → **8120** total | |

`UserRewardInfo` (48): `reward_per_token_completes:[u128;2]` @0, `reward_pendings:[u64;2]` @32.
`FeeInfo` (48): `fee_x_per_token_complete:u128` @0, `fee_y_per_token_complete:u128` @16,
`fee_x_pending:u64` @32, `fee_y_pending:u64` @40.

#### 1.7.1 Resized ("dynamic") positions — **a naive fixed-offset parser is wrong** **[SRC-0.12]+[CHAIN]**

`initialize_position(lower_bin_id, width)` can be followed by `increase_position_length` /
`increase_position_length2` / `decrease_position_length`, which **realloc** the account. Let
`W = upper_bin_id − lower_bin_id + 1`.

```
account_size(W) = 8 + 8112 + 112 · max(0, W − 70)
                = 280 + 112·W                      for W ≥ 70
```

`112 = size_of(PositionBinData) = 16 (liquidity_share u128) + 48 (UserRewardInfo) + 48 (FeeInfo)`.

* Bins `0 .. min(W,70)−1` live in the three **separate parallel arrays** of the base struct.
* Bins `70 .. W−1` live in an **array-of-structs** appended at absolute offset `8 + 8112 = 8120`,
  each entry laid out `liquidity_share(16) ‖ reward_info(48) ‖ fee_info(48)` — i.e. **interleaved**, the
  opposite of the base struct. Bin `70+i` is at `8120 + 112·i`.
* `POSITION_MAX_LENGTH = 1400` bins → max size `280 + 112·1400 = 157 080` bytes.

**[CHAIN]** The census found 153 accounts of size 10 136 carrying the *PositionV2* discriminator:
`10136 = 280 + 112·88`, i.e. 88-bin positions. Those bytes also happen to be the size of a `BinArray`, so a
recorder that keys off `dataSize` alone will mis-parse 153 positions as bin arrays. **Discriminate on the
8-byte discriminator, never on size.**

### 1.8 `Oracle` — 32-byte header + ring buffer **[IDL]+[SRC]+[CHAIN]**

| abs | size | field |
|---|---|---|
| 0 | 8 | discriminator `8bc283b38cb3e5f4` |
| 8 | 8 | `idx` : u64 — index of latest observation |
| 16 | 8 | `active_size` : u64 — number of initialised samples |
| 24 | 8 | `length` : u64 — ring capacity (default 100, growable via `increase_oracle_length`) |
| 32 | 32·length | `observations` : `[Observation]` |

`Observation` (32 bytes, `#[zero_copy]`) **[SRC-0.8.2]**, layout **[CHAIN]**-confirmed by decoding
`EgEYXef2FCoEYLHJJW74dMbom1atLXo6KwPuA6mSATYA`:

```
+0  i128 cumulative_active_bin_id
+16 i64  created_at
+24 i64  last_updated_at
```

Semantics **[SRC-0.8.2]**:

```
initialized(o)            := o.created_at > 0 ∧ o.last_updated_at > 0
accumulate(o, id, t)      := if initialized(o) then o.cum + (id : i128)·(t − o.last_updated_at) else (id : i128)
next_sampling_ts(o)       := o.created_at + SAMPLE_LIFETIME     (=120s)
update(oracle, id, t):
   if active_size = 0 then active_size := 1
   let s := observations[idx]
   let c := accumulate(s, id, t)
   if initialized(s) ∧ t ≥ next_sampling_ts(s) then
        idx := (idx + 1) mod length
        if ¬initialized(observations[idx]) then active_size := min(active_size+1, length)
        observations[idx].reset()                 -- (cum, created_at, last_updated_at) := (0,0,0)
        s := observations[idx]
   s.cumulative_active_bin_id := c ; s.last_updated_at := t
   if ¬initialized(s) then s.created_at := t
```

Note the time-weighted quantity is the **bin id**, not the price — a TWAP must be reconstructed as
`price_of_bin(Δcum / Δt)` with the exponential, which is *not* a time-weighted price.

### 1.9 `BinArrayBitmapExtension` — 1 576 bytes **[IDL]+[CHAIN]**

`lb_pair` pubkey @+0, `positive_bin_array_bitmap : [[u64;8];12]` @+32, `negative_bin_array_bitmap : [[u64;8];12]` @+800.

---

## 2. Bin math

### 2.1 Price of a bin **[SRC-0.12] = [SRC-0.8.2]**, **[CHAIN]**-verified

```
get_price_from_id(id : i32, bin_step : u16) : u128 (Q64.64) =
    let bps  := (bin_step << 64) / 10_000          -- integer division, truncating
    let base := (1 << 64) + bps                    -- Q64.64 representation of (1 + bin_step/10000)
    pow(base, id)
```

`pow(base, exp)` is a Q64.64 binary exponentiation, **not** real arithmetic:

```
pow(base, exp):
  invert := exp < 0
  if exp = 0 then return 1<<64
  e := |exp| (as u32); if e ≥ 0x80000 then FAIL
  sq := base ; res := 1<<64
  if sq ≥ res then { sq := u128::MAX / sq ; invert := ¬invert }   -- reciprocal trick, floor division
  for bit in 0..18:                                              -- exactly 19 bits
      if bit > 0 then sq := (sq * sq) >> 64                       -- truncating
      if e & (1<<bit) ≠ 0 then res := (res * sq) >> 64             -- truncating
  if res = 0 then FAIL
  if invert then res := u128::MAX / res
  return res
```

Every step truncates (floor). `u128::MAX / x` is used in place of `2^128 / x`, so the reciprocal is
*not* exactly `1/x`; a faithful Lean model must reproduce this literally. Because `base ≥ 1<<64` always,
the reciprocal branch is **always taken** for `bin_step ≥ 1`, and `invert` is flipped: positive `id`
ends up inverted at the end, negative `id` does not.

**[CHAIN] verification.** For pools `HTvjzsfX…` (bin_step 1) and `4caKMZZy…` (bin_step 20) I read the
full active `BinArray` (70 bins each) and compared each stored `Bin.price` to the recomputation:
**140 / 140 exact matches, 0 mismatches, 0 uninitialised.**

Note `Bin.price` is **cached lazily**: `get_or_store_bin_price` writes it only if it is currently 0
**[SRC]**. A bin never touched has `price = 0`, which does *not* mean price zero.

### 2.2 Decimal adjustment (raw ↔ UI price) **[INFER, arithmetically forced]**

`price` is Q64.64 and denominates **token Y base units per token X base unit**. The human price is

```
ui_price = (price / 2^64) · 10^(decimals_x − decimals_y)
```

e.g. SOL/USDC at bin −25796, bin_step 1: `price = 1398523242823703303`, `price/2^64 = 0.075814096907`,
×10^(9−6) = **75.814 USDC/SOL**. **[CHAIN]** (computed from the live account; the multiplier direction is
forced by the reserve denominations and is the standard Meteora `getPriceFromId` convention).

Meteora's SDK also exposes a `PRECISION = 10^12` decimal conversion helper **[SRC]**; that is a display
convenience, not part of the on-chain math.

### 2.3 The constant-sum invariant **[SRC-0.8.2]** `math/bin_math.rs`

```
get_liquidity(x : u64, y : u64, price : u128) : u128 =
    ((U256(price) · U256(x))  +  (U256(u128(y) << 64)))    -- computed in U256, then narrowed to u128
```

So **`L = P·x + y` in Q64.64**, with `P` the Q64.64 bin price and `x`, `y` raw base units.
`L` is therefore a **Q64.64 quantity denominated in token Y base units**. This is the dimension of
`Bin.liquidity_supply` and of `PositionV2.liquidity_shares[i]`.

Deposit / withdraw **[SRC-0.8.2]** `state/bin.rs`:

```
get_liquidity_share(in_liquidity, bin_liquidity, liquidity_supply) =
    ⌊ in_liquidity · liquidity_supply / bin_liquidity ⌋            (Rounding::Down)
get_out_amount(share, bin_token_amount, liquidity_supply) =
    if liquidity_supply = 0 then 0
    else ⌊ share · bin_token_amount / liquidity_supply ⌋            (Rounding::Down)
withdraw(share): amount_x := ⌊share·amount_x/supply⌋ ; amount_y := ⌊share·amount_y/supply⌋ ; supply −= share
```

All three intermediate products are done in **U256** (`mul_div`) and then narrowed, so there is no
intermediate overflow, but every result is floored — withdrawing dust rounds to the LP's loss.

### 2.4 Swap arithmetic inside one bin **[SRC-0.12]** (identical in **[SRC-0.8.2]**)

With `price` = Q64.64 bin price, `swap_for_y` = "user sells X, receives Y":

```
get_amount_out(a_in, price, swap_for_y, r) =
   swap_for_y  ⇒  mul_shr(price, a_in, 64, r)      = round_r(price · a_in / 2^64)
   ¬swap_for_y ⇒  shl_div(a_in, price, 64, r)      = round_r(a_in · 2^64 / price)

get_amount_in(a_out, price, swap_for_y, r) =
   swap_for_y  ⇒  shl_div(a_out, price, 64, r)     = round_r(a_out · 2^64 / price)
   ¬swap_for_y ⇒  mul_shr(a_out, price, 64, r)     = round_r(a_out · price / 2^64)

get_max_amount_out(bin, swap_for_y) = if swap_for_y then bin.amount_y else bin.amount_x
get_max_amount_in (bin, price, swap_for_y) =
   swap_for_y  ⇒  ⌈ amount_y · 2^64 / price ⌉      (Rounding::Up)
   ¬swap_for_y ⇒  ⌈ amount_x · price / 2^64 ⌉      (Rounding::Up)
```

`mul_div(x,y,d,r)` computes `x·y/d` in **U256** and then rounds: `Down` = `div_rem`, `Up` = `div_ceil`.
`mul_shr(x,y,off,r) = mul_div(x, y, 1<<off, r)`; `shl_div(x,y,off,r) = mul_div(x, 1<<off, y, r)`.

**Rounding direction table** (this is the part that silently corrupts backtests):

| quantity | rounding | why |
|---|---|---|
| `get_amount_out` in the exact-in path | **Down** | user receives less |
| `get_amount_in` when sizing a bin fill (`calculate_exact_in_fill_amount`) | **Up** | user pays more |
| `get_max_amount_in` | **Up** | |
| `compute_fee` (fee *added on top* of amount) | **Up** (ceil) | |
| `compute_fee_from_amount` (fee *inside* amount) | **Up** (ceil) | |
| `compute_protocol_fee` | **Down** | |
| host fee split | **Down** | |
| `get_liquidity_share`, `get_out_amount`, `withdraw` | **Down** | |
| `Bin::update_fee_per_token_stored` | **Down** | |
| position fee accrual | **Down** | |
| `compute_variable_fee` scale-down by 1e11 | **Up** (ceil, via `+99_999_999_999`) | |
| `compute_composition_fee` scale-down by 1e18 | **Down** | |
| `split_fee` mm-portion | **Up** (ceil) | |

### 2.5 Single-bin swap step **[SRC-0.12]** `Bin::swap`

```
swap(bin, amount_in, price, swap_for_y, pair, host_fee_bps):
  max_out := get_max_amount_out(bin, swap_for_y)
  max_in  := get_max_amount_in(bin, price, swap_for_y)          -- ceil
  max_fee := pair.compute_fee(max_in)                            -- ceil, fee added on top
  max_in  := max_in + max_fee
  if amount_in > max_in then
      (in_with_fees, out, fee) := (max_in, max_out, max_fee)
  else
      fee  := pair.compute_fee_from_amount(amount_in)            -- ceil, fee inside
      out  := min(get_amount_out(amount_in − fee, price, swap_for_y, Down), max_out)
      (in_with_fees, out, fee) := (amount_in, out, fee)
  protocol_fee := pair.compute_protocol_fee(fee)                 -- floor
  host_fee     := ⌊protocol_fee · host_fee_bps / 10000⌋ (0 if no host)
  amount_into_bin := in_with_fees − fee
  if swap_for_y then bin.amount_x += amount_into_bin ; bin.amount_y −= out
              else bin.amount_y += amount_into_bin ; bin.amount_x −= out
```

The LP-facing fee that feeds `fee_amount_*_per_token_stored` is `fee − protocol_fee`
**[INFER, corroborated [CHAIN]]**; `protocol_fee_after_host_fee` accrues into
`LbPair.protocol_fee.{amount_x, amount_y}`.

**[CHAIN] corroboration.** Polling the active bin of `HTvjzsfX…` across a live Y→X swap
(slot 439154478, `swap_for_y = false`):

```
Δbin.amount_y                     = +201 615 026     -- = amount_in_with_fees − fee, i.e. fee NOT in the bin
Δbin.amount_x                     = −2 658 005 000
Δbin.liquidity_supply             = 0                -- constant-sum: L is invariant across a swap
Δfee_amount_y_per_token_stored    = 145 556 647 320 959   (Q64.64)
Δfee_amount_x_per_token_stored    = 0                -- fee lands on the INPUT side only
liquidity_supply >> 64            = 2 300 319 895
⟹ implied LP fee = (Δ · L) >> 64  = 18 150 token-Y units
```

At `base_fee_rate ≈ 1.0e-4` the gross fee on that input is ≈ 20 161, and
`18 150 / 20 161 = 0.9002` — exactly `1 − protocol_share/10000` with `protocol_share = 1000`. It also
confirms the direction rule: `swap_for_y = false` ⇒ the **Y** accumulator grows, matching
`update_fee_per_token_stored`'s `if swap_for_y { x } else { y }`, and confirms
**`liquidity_supply` is invariant under swaps** (only deposits/withdrawals move it).

### 2.6 Traversal across bins and bin arrays **[SRC-0.12]** `commons/src/quote.rs`

```
quote_exact_in(pair, amount_in, swap_for_y):
  validate_swap_activation(pair, now, slot)
  pair.update_references(now)                                   -- §3.4, ONCE, before any bin
  amount_left := transfer_fee_excluded(amount_in)
  while amount_left > 0:
      ba_key := first bin-array index with liquidity in the swap direction, from active_id
                (via bitmap; if none ⇒ ERROR "Pool out of liquidity")
      ba := load(ba_key)                                        -- if the account is missing ⇒ ERROR
      shift_active_bin_if_empty_gap(pair, ba, swap_for_y)       -- see below
      loop:
          if ¬ba.is_bin_id_within_range(active_id) ∨ amount_left = 0 then break
          bin := ba[active_id]
          if get_max_amount_out(bin, swap_for_y) > 0:
              pair.update_volatility_accumulator()              -- §3.4, PER BIN
              r := swap_at_bin(bin, pair, amount_left, …)
              amount_left −= r.amount_in ; total_out += r.amount_out ; …
          if amount_left > 0 then advance_active_bin(pair, swap_for_y)
  total_out := transfer_fee_excluded(total_out)
```

* `advance_active_bin`: `active_id ± 1` (`−1` when `swap_for_y`), erroring if it leaves
  `[MIN_BIN_ID, MAX_BIN_ID] = [−443636, 443636]` with `PairInsufficientLiquidity`.
* **Bin exhaustion is not a special case.** A bin is simply skipped when
  `get_max_amount_out = 0`; the accumulator is *not* bumped for a skipped bin, and no fee is charged there.
* **Bin-array boundary**: the inner loop exits when `active_id` leaves the array's
  `[70·index, 70·index + 69]` range; the outer loop then re-queries the bitmap.
* **Uninitialised / gapped bin arrays**: the bitmap search returns the next *initialised* array index. If
  that array's `index` differs from `bin_id_to_bin_array_index(active_id)`, `shift_active_bin_if_empty_gap`
  **teleports** `active_id` to the far edge of that array — `upper_bin_id` when `swap_for_y`, `lower_bin_id`
  otherwise — *without* passing through the intervening bins. This is a genuine discontinuity in the
  price path and it **does** enter the volatility accumulator, because `|index_reference − active_id|`
  is recomputed from the new `active_id`.
* If **no** initialised array exists in the direction, the swap fails with "Pool out of liquidity"
  (`get_bin_array_pubkeys_for_swap` returns empty).

Index arithmetic **[SRC-0.12]**:

```
bin_id_to_bin_array_index(b) = ⌊b / 70⌋   (floor toward −∞: div_rem then −1 if b<0 ∧ rem≠0)
bin_array_range(idx)         = (70·idx, 70·idx + 69)
```

Bitmap **[SRC-0.12]** `LbPair::next_bin_array_index_with_liquidity_internal`: `bin_array_bitmap` is a
`U1024` over indices `−512 ..= 511` (`offset = idx + 512`); `swap_for_y` scans **down** using
`leading_zeros` of the left-shifted bitmap, otherwise **up** using `trailing_zeros` of the right-shifted
bitmap. Out of that range the `BinArrayBitmapExtension` account is consulted; when it is absent the
search stops.

---

## 3. The fee mechanism — **fully determined and verified on chain**

### 3.1 Fee rates **[SRC-0.12]**, **[CHAIN]**-verified

All rates are in **1e9 units** (`FEE_PRECISION`), *not* basis points, despite the event field being
named `fee_bps`.

```
base_fee_rate      = base_factor · bin_step · 10 · 10^base_fee_power_factor            [SRC-0.12]
variable_fee_rate(v)= if variable_fee_control = 0 then 0
                      else ⌈ variable_fee_control · (v · bin_step)^2 / 10^11 ⌉
                           implemented as (vfc·(v·bin_step)^2 + 99_999_999_999) / 10^11
total_fee_rate      = min(base_fee_rate + variable_fee_rate(volatility_accumulator), MAX_FEE_RATE=1e8)
```

**[CHAIN] verification of the base term.** For `HTvjzsfX…` (base_factor 10000, bin_step 1,
power_factor 0) the minimum `fee_bps` observed over 276 swaps is **exactly 100 000** = `10000·1·10·10^0`.
For `4caKMZZy…` (base_factor 10000, bin_step 20, power_factor **1**) the base is **20 000 000** =
`10000·20·10·10^1` — i.e. the `10^base_fee_power_factor` factor is real and is a factor of 10, not 10 bps.
v0.8.2 source **lacks** this term and would be off by 10× on 5 627 mainnet pools.

**[CHAIN] verification that `fee_bps` = `total_fee_rate`.** Over 276 swaps on `HTvjzsfX…`, all 71
distinct `fee_bps` values are exactly expressible as `base_fee_rate + variable_fee_rate(v)` for an integer
`v`; and a directly polled `LbPair.volatility_accumulator = 21914` reproduces the concurrently emitted
`fee_bps = 109605` exactly. `fee_bps` is *not* `fee/amount_in` (that differs by up to 1.8%).

### 3.2 Fee application **[SRC-0.12]**

```
compute_fee(amount)              -- fee ADDED on top; solves (amount+f)·r/1e9 = f
   = ⌈ amount · r / (1e9 − r) ⌉      implemented as (amount·r + (1e9−r) − 1) / (1e9 − r)
compute_fee_from_amount(amount)  -- fee is PART of amount
   = ⌈ amount · r / 1e9 ⌉            implemented as (amount·r + 1e9 − 1) / 1e9
compute_protocol_fee(fee)        = ⌊ fee · protocol_share / 10000 ⌋
host_fee                         = ⌊ protocol_fee · host_fee_bps / 10000 ⌋   (HOST_FEE_BPS = 2000)
protocol_fee_after_host_fee      = protocol_fee − host_fee
compute_composition_fee(amount)  = ⌊ amount·r·(1e9 + r) / 1e18 ⌋
```

`compute_fee` and `compute_fee_from_amount` are **not** inverses; the program uses the first when it
knows the net amount (draining a bin, exact-out) and the second when the gross amount is given.

### 3.3 Where the fee goes **[SRC]**

* **Protocol** share: `⌊fee · protocol_share / 10000⌋`, accrued into the `LbPair.protocol_fee.{amount_x,
  amount_y}` counters (offsets +208/+216) and withdrawn by `withdraw_protocol_fee`. Mainnet
  `protocol_share` is 1000 bps (10%) on 148 226 of 153 867 pools, 2000 bps on 5 616, 500 bps on 25. Cap 2500.
* **Host/referrer**: if the optional `host_fee_in` account is supplied, 20% (`HOST_FEE_BPS`) of the
  *protocol* fee is diverted to it. It is a slice of the protocol share, not an extra charge.
* **LP** share = `fee − protocol_fee`. It is **not** added to `Bin.amount_x/amount_y` (those are documented
  as "already excluded protocol fees" and the swap adds `in_with_fees − fee` to the bin). Instead it is
  converted to a **per-bin growth accumulator**:

```
Bin::update_fee_per_token_stored(fee, swap_for_y):                             [SRC-0.8.2]
    Δ := ⌊ (fee << 64) / (liquidity_supply >> 64) ⌋           -- Q64.64 per unit of integer liquidity
    if swap_for_y then fee_amount_x_per_token_stored += Δ else fee_amount_y_per_token_stored += Δ
```

  Note the denominator is `liquidity_supply >> 64`, i.e. the **integer part** of the Q64.64 supply. A bin
  whose entire supply is `< 2^64` has denominator 0 ⇒ that branch would fail; `MINIMUM_LIQUIDITY = 1e6`
  exists to keep supplies away from that.

* **Position level** is a lazy pull, evaluated in `update_fees_and_rewards`, `claim_fee`, and implicitly
  on any liquidity mutation:

```
PositionV2::update_fee_per_token_stored(bin_id, bin):                          [SRC-0.8.2]
    i := bin_id − lower_bin_id
    new_fee_x := ⌊ (liquidity_shares[i] >> 64) · (bin.fee_amount_x_per_token_stored
                                                   − fee_infos[i].fee_x_per_token_complete) / 2^64 ⌋
    fee_infos[i].fee_x_pending += new_fee_x
    fee_infos[i].fee_x_per_token_complete := bin.fee_amount_x_per_token_stored
    (symmetrically for y)
```

  The subtraction is `safe_sub` in 0.8.2 (would trap on wrap) but `saturating_sub` in the 0.12 SDK
  reimplementation **[SRC-0.12]** — a divergence worth flagging; the `wrapping_add` TODO comment in
  `update_fee_per_token_stored` suggests the accumulators are *intended* to wrap.
* **Composition fee** (`CompositionFee` event): when a deposit's X:Y ratio at the **active** bin does not
  match the bin's current ratio, the mismatch is treated as an implicit swap and charged
  `compute_composition_fee`, split protocol/LP the same way, and the fee tokens are added straight into
  the bin (`Bin::deposit_composition_fee`) rather than into the growth accumulator.

### 3.4 The volatility accumulator state machine **[SRC-0.12] + [CHAIN] orchestration**

State: `(active_id, volatility_accumulator, volatility_reference, index_reference, last_update_timestamp)`.

```
update_references(t):                                                          [SRC, verbatim]
    elapsed := t − last_update_timestamp
    if elapsed ≥ filter_period then
        index_reference := active_id                       -- active bin BEFORE this swap
        if elapsed < decay_period then
            volatility_reference := ⌊ volatility_accumulator · reduction_factor / 10000 ⌋
        else
            volatility_reference := 0
    -- NOTE: last_update_timestamp is NOT written here (the line is commented out in the source)

update_volatility_accumulator():                                               [SRC, verbatim]
    Δ := |index_reference − active_id|                     -- computed in i64, then unsigned_abs
    volatility_accumulator := min(volatility_reference + Δ·10000, max_volatility_accumulator)
```

**Orchestration (the part not in any public source — determined by fitting against mainnet):**

```
on swap at wall-clock t (= Clock::unix_timestamp = the block's blockTime):
   1. update_references(t)                                  -- exactly once, before any bin is touched
   2. for each visited bin with non-zero output liquidity, in traversal order:
          update_volatility_accumulator()                   -- with the CURRENT active_id
          charge that bin's fill at total_fee_rate(volatility_accumulator)
          (then advance_active_bin if more input remains)
   3. if active_id changed during the swap:
          oracle.update(active_id, t)
          last_update_timestamp := t
      else:
          last_update_timestamp is LEFT UNCHANGED
```

Step 3 is the surprising bit and it is load-bearing: **`last_update_timestamp` only advances when the
swap actually moves the active bin.** A run of swaps that all stay inside the active bin does not reset
the clock, so `elapsed` keeps growing and the reference keeps decaying on *every* such swap — including
several swaps in the *same slot*, where the naive "elapsed = time since previous swap" model gives
`elapsed = 0` and predicts no decay at all.

`add_liquidity` (and `remove_liquidity` / `rebalance_liquidity`) also run
`update_references` + `update_volatility_accumulator` — they need `total_fee_rate` for the composition
fee — with `active_id` unchanged, and likewise do **not** advance `last_update_timestamp`.

**[CHAIN] verification.** I reconstructed `volatility_accumulator` from the emitted `fee_bps` of every
DLMM event on two pools and simulated the machine above:

| pool | params | events | rule `lts := t` always | rule `lts := t` on branch | rule `lts` never | **rule above** |
|---|---|---|---|---|---|---|
| `HTvjzsfX…` (SOL/USDC) | bs 1, filter 10, decay 120, red 5000, maxv 100000, vfc 2e6 | 67 swaps / 145 s, seeded from a polled `LbPair` pre-state | 3/67 | 3/67 | 1/67 | **67/67 (100%)** |
| `4caKMZZy…` | bs 20, bfpf 1, filter 10, decay 120, red 5000, maxv 150000, vfc 5e4 | 370 swaps / 56 116 s, cold start | 292/367 | 289/367 | 191/367 | **370/370 (100%)** |

The second pool reaches 100% only once `AddLiquidity` events are also stepped through the machine; with
swaps alone it is 369/370, and the single miss is immediately preceded by an
`add_liquidity_by_strategy2` that emitted a `CompositionFee`. That is direct evidence for the deposit
path running the same update.

### 3.5 The variable fee is a **path-length** measure over a *burst*, not a volatility measure

Unrolling: within one swap the accumulator ends at

```
volatility_accumulator = min( volatility_reference + |index_reference − active_id_final| · 10000,
                              max_volatility_accumulator )
```

`index_reference` is the active bin at the start of the *current burst* (the last time `elapsed ≥
filter_period` fired). So the accumulator measures **net signed bin displacement from the burst anchor,
in absolute value** — not realised volatility, not path length. A round trip out `k` bins and back to the
anchor drives the accumulator to `volatility_reference` (≈ 0), i.e. **back to the base fee**, even though
the pool has been arbitraged twice. This is directly visible in the data: at `t = 1786679906` a swap that
crossed a bin (−25807 → −25808) returned the active bin to `index_reference` and the fee collapsed from
102 002 to **100 001** — one part in 10⁹ above base.

### 3.6 Verdict on the accumulator-reset hypothesis

> *Hypothesis: a slow monotonic price drift that crosses many bins but spaced out enough that the
> accumulator keeps resetting past `decay_period` will collect near-base fees while incurring full
> adverse selection.*

**CONFIRMED — and the real mechanism is strictly worse for the LP than the hypothesis states.**
Three independent channels, all verified above, produce near-base fees under slow drift:

1. **`index_reference` re-anchors, so displacement never accumulates.** Whenever
   `elapsed ≥ filter_period`, `index_reference := active_id` — the *current* bin. A drift of `N` bins
   delivered as `N` swaps each separated by more than `filter_period` yields, on every swap,
   `|index_reference − active_id| = 1`, hence `volatility_accumulator ≈ volatility_reference + 10000`,
   i.e. **one bin of "volatility" regardless of how far the price has actually travelled.** The
   accumulator has no memory of the drift at all. This is the dominant effect and it needs only
   `filter_period` (10–300 s; **300 s on 115 809 of 153 867 pools**), not `decay_period`.
2. **Past `decay_period`, `volatility_reference := 0`** — so even the one-bin residue starts from zero
   rather than from a decayed prior. With `decay_period` = 1200 s on 120 875 pools, any drift slower than
   20 minutes per bin collects **exactly** `base_fee + variable_fee(10000)`.
3. **The quadratic makes the residue negligible.** `variable_fee(10000) = ⌈vfc·(10⁴·bin_step)²/10¹¹⌉`.
   For the modal pool (`vfc = 7500`, `bin_step = 100`) that is
   `⌈7500·10¹²/10¹¹⌉ = 75 000` against a typical base of `base_factor·100·10` — e.g. with
   `base_factor = 10000`, base is 10 000 000. **The variable component is 0.75% of the base fee.**
   For SOL/USDC bs=1 it is 2 000 against a base of 100 000 — 2%.

Concretely, on `HTvjzsfX…` I measured the realised `fee_bps` bucketed by inter-swap gap:

```
gap < filter_period (10s):   n=251  median 102 000  mean 104 681  max 150 021
gap ∈ [filter, decay):       n= 24  median 100 605  mean 102 203  max 112 506
                                        (base = 100 000)
```

i.e. **bursty flow pays up to 50% over base, spaced flow pays ~0.6% over base**, for the *same* number of
bins crossed. The fee schedule prices *clustering in time*, and adverse selection is priced by
*displacement*, and the two are only weakly related. A drifting informed flow that self-paces above
`filter_period` extracts the full bin-by-bin adverse selection at essentially the base fee.

**Refinement to the hypothesis worth carrying into the model:** the binding threshold is
`filter_period`, not `decay_period`. Crossing `decay_period` only removes the (already tiny, already
halving) `volatility_reference` residue. And there is a fourth channel the hypothesis does not mention —
the round-trip cancellation of §3.5 — which lets even *fast* flow pay base fees as long as it returns the
active bin to the anchor.

---

## 4. Instructions and events

### 4.1 Discriminators

**All 76 instruction discriminators in the on-chain IDL are exactly `sha256("global:" ‖ name)[0:8]`,
with `name` in `snake_case`** — I checked all 76 programmatically: **76/76 match, 0 mismatches**
**[IDL]+[verified]**. The earlier failure to guess them was a naming issue: the IDL names are
`initialize_position`, not `initializePosition`.

| instruction | discriminator | args |
|---|---|---|
| `initialize_position` | `dbc0ea47bebf6650` | `lower_bin_id: i32, width: i32` |
| `initialize_position2` | `8f13f291d50f6873` | `lower_bin_id: i32, width: i32` |
| `initialize_position_pda` | `2e527d92558de499` | `lower_bin_id: i32, width: i32` |
| `initialize_position_by_operator` | `fbbdbef475fe2394` | `lower_bin_id: i32, width: i32, fee_owner: pubkey, lock_release_point: u64` |
| `increase_position_length` | `505375d3420d2195` | `length_to_add: u16, side: u8` |
| `increase_position_length2` | `ffd2cc477389e171` | `minimum_upper_bin_id: i32` |
| `decrease_position_length` | `c2db882019606925` | `length_to_remove: u16, side: u8` |
| `add_liquidity` | `b59d59438fb63448` | `LiquidityParameter` |
| `add_liquidity2` | `e4a24e1c46db7473` | `LiquidityParameter, RemainingAccountsInfo` |
| `add_liquidity_by_strategy` | `0703967f94283dc8` | `LiquidityParameterByStrategy` |
| `add_liquidity_by_strategy2` | `03dd95da6f8d76d5` | `LiquidityParameterByStrategy, RemainingAccountsInfo` |
| `add_liquidity_by_strategy_one_side` | `2905eeaf64e106cd` | |
| `add_liquidity_by_weight` | `1c8cee63e7a21595` | `LiquidityParameterByWeight` |
| `add_liquidity_by_weight2` | `d13b3f5b6fc899e4` | |
| `add_liquidity_one_side` | `5e9b6797465fdca5` | |
| `add_liquidity_one_side_precise` | `a1c26754ab47fa9a` | |
| `add_liquidity_one_side_precise2` | `2133a3c975627de7` | `AddLiquiditySingleSidePreciseParameter2, RemainingAccountsInfo` |
| `remove_liquidity` | `5055d14818ceb16c` | `Vec<BinLiquidityReduction>` |
| `remove_liquidity2` | `e6d7527ff165e392` | `Vec<BinLiquidityReduction>, RemainingAccountsInfo` |
| `remove_liquidity_by_range` | `1a526698f04a691a` | `from_bin_id: i32, to_bin_id: i32, bps_to_remove: u16` |
| `remove_liquidity_by_range2` | `cc02c391359191cd` | `… , RemainingAccountsInfo` |
| `remove_all_liquidity` | `0a333d2370691855` | — |
| `rebalance_liquidity` | `5c04b0c177b95309` | `RebalanceLiquidityParams, RemainingAccountsInfo` |
| `claim_fee` | `a9204f8988e84689` | — |
| `claim_fee2` | `70bf65ab1c907fbb` | `min_bin_id: i32, max_bin_id: i32, RemainingAccountsInfo` |
| `claim_reward` / `claim_reward2` | `955fb5f25e5a9ea2` / `be037f77b2579db7` | |
| `close_position` | `7b86510031446262` | — |
| `close_position2` | `ae5a2373ba2893e2` | — |
| `close_position_if_empty` | `3b7cd4765b986e9d` | — |
| `swap` | `f8c69e91e17587c8` | `amount_in: u64, min_amount_out: u64` |
| `swap2` | `414b3f4ceb5b5b88` | `amount_in: u64, min_amount_out: u64, RemainingAccountsInfo` |
| `swap_exact_out` | `fa49652126cf4bb8` | `max_in_amount: u64, out_amount: u64` |
| `swap_exact_out2` | `2bd7f784893cf351` | `… , RemainingAccountsInfo` |
| `swap_with_price_impact` | `38ade6d0ade49ccd` | `amount_in: u64, active_id: Option<i32>, max_price_impact_bps: u16` |
| `swap_with_price_impact2` | `4a62c0d6b1334b33` | `… , RemainingAccountsInfo` |
| `update_fees_and_rewards` | `9ae6fa0decd14bdf` | — |
| `update_fees_and_reward2` | `208eb89a6741b858` | |
| `initialize_lb_pair` / `2` | `2d9aedd2dd0fa65c` / `493b2478ed536cc6` | |
| `initialize_customizable_permissionless_lb_pair` / `2` | `2e2729876fb7c840` / `f349817e3313f16b` | |
| `initialize_bin_array` | `235613b94ed44bd3` | |
| `initialize_bin_array_bitmap_extension` | `2f9de2b40cf02147` | |
| `increase_oracle_length` | `be3d7d57674f9ead` | |
| `withdraw_protocol_fee` | `9ec99ebd215da267` | |
| `update_base_fee_parameters` | `4ba8dfa110c3032f` | |
| `update_dynamic_fee_parameters` | `5ca12ef6ffbd1616` | |
| `go_to_a_bin` | `9248aee028fd54ae` | |
| `place_limit_order` | `6cb021ba92e501c5` | |
| `cancel_limit_order` | `849c841f4328e861` | |

(Full list of 76 available by recomputing `sha256("global:"+name)[0:8]`; the mapping is total.)

Argument struct shapes **[IDL]** (Borsh):

```
LiquidityParameter            = { amount_x: u64, amount_y: u64, bin_liquidity_dist: Vec<BinLiquidityDistribution> }
BinLiquidityDistribution      = { bin_id: i32, distribution_x: u16, distribution_y: u16 }
LiquidityParameterByStrategy  = { amount_x: u64, amount_y: u64, active_id: i32,
                                  max_active_bin_slippage: i32, strategy_parameters: StrategyParameters }
StrategyParameters            = { min_bin_id: i32, max_bin_id: i32, strategy_type: StrategyType, parameteres: [u8;64] }
StrategyType                  = SpotOneSide | CurveOneSide | BidAskOneSide | SpotBalanced | CurveBalanced
                                | BidAskBalanced | SpotImBalanced | CurveImBalanced | BidAskImBalanced   (u8)
BinLiquidityReduction         = { bin_id: i32, bps_to_remove: u16 }
CompressedBinDepositAmount    = { bin_id: i32, amount: u32 }
RemainingAccountsInfo         = { slices: Vec<RemainingAccountsSlice> }
RemainingAccountsSlice        = { accounts_type: AccountsType, length: u8 }
AccountsType                  = TransferHookX | TransferHookY | TransferHookReward
                                | TransferHookMultiReward | TransferHookReferral                       (u8)
```

Account order for `swap` **[IDL]** (bin arrays are passed as *remaining accounts* after these):
`0 lb_pair(w) · 1 bin_array_bitmap_extension(w, optional) · 2 reserve_x(w) · 3 reserve_y(w) ·
4 user_token_in(w) · 5 user_token_out(w) · 6 token_x_mint · 7 token_y_mint · 8 oracle(w) ·
9 host_fee_in(w, optional) · 10 user(signer) · 11 token_x_program · 12 token_y_program ·
13 event_authority · 14 program`. `swap2` inserts `memo_program` at index 13.

### 4.2 The Anchor event-CPI envelope — **correction to the stated premise**

A DLMM event arrives as a **self-CPI instruction** to the DLMM program itself, whose instruction data is:

```
[0..8]   e4 45 a5 2e 51 cb 9a 1d          <- the event-CPI tag
[8..16]  <event discriminator>            <- sha256("event:" ‖ EventName)[0:8]
[16..]   <Borsh-encoded event struct>
```

**The tag `e445a52e51cb9a1d` is NOT `sha256("anchor:event")[0:8]`.**
`sha256("anchor:event")[0:8] = 1d9acb512ea545e4`. The tag is that value's **byte reversal**: Anchor
defines `EVENT_IX_TAG: u64 = 0x1d9acb512ea545e4` and serialises it **little-endian**, giving the byte
string `e4 45 a5 2e 51 cb 9a 1d`. **[CHAIN]** — confirmed by decoding live transactions. Get this
backwards in Lean and every event decodes to nothing.

The inner discriminators *are* `sha256("event:" ‖ Name)[0:8]` in normal big-endian-first-8-bytes order:
`sha256("event:Swap")[0:8] = 516ce3becdd00ac4` matches the IDL's `Swap` discriminator exactly **[verified]**.

`event_authority` is the PDA `find_program_address(["__event_authority"], program_id)` =
**`D1ZN9Wj1fRSUQfCjhvnu1hqDMT7hzjzBBpi12nVniYD6`** (bump 255) and signs the self-CPI. **[CHAIN]** On the
wire the event-CPI inner instruction carries **exactly one account** — the event authority — even though
the IDL lists `event_authority` and `program` on the outer instruction. A recorder should therefore match
on `(program_id == DLMM) ∧ (data[0..8] == e445a52e51cb9a1d)` and ignore account count.

### 4.3 Event layouts (Borsh, little-endian, no padding) **[IDL]**, `Swap`/`Swap2Evt` **[CHAIN]**

Every observed swap emits **both** `Swap` and `Swap2Evt` — 67/67 transactions on `HTvjzsfX…`,
740 events over 370 swaps on `4caKMZZy…`, regardless of whether the instruction was `swap` or `swap2`
**[CHAIN]**. A recorder that keys only on `Swap` will therefore not miss swaps on the current program
version, but must **deduplicate** the pair.

```
Swap        disc 516ce3becdd00ac4   size 129
  +0   pubkey  lb_pair
  +32  pubkey  from
  +64  i32     start_bin_id          -- active bin at the START of the swap (after any gap-shift)
  +68  i32     end_bin_id            -- active bin at the END
  +72  u64     amount_in             -- includes fee when fees are on input
  +80  u64     amount_out
  +88  u8      swap_for_y            (bool)
  +89  u64     fee                   -- total trading fee, INCLUDES protocol fee
  +97  u64     protocol_fee
  +105 u128    fee_bps               -- total_fee_rate in 1e9 units (misnamed; NOT bps)   [CHAIN]
  +121 u64     host_fee

Swap2Evt    disc 2e7452d7941b544d   size 147
  +0   pubkey  lb_pair
  +32  pubkey  from
  +64  i32     start_bin_id
  +68  i32     end_bin_id
  +72  u8      swap_for_y
  +73  u128    fee_bps
  +89  u64     amount_in
  +97  u64     amount_left           -- unconsumed input (partial fill)
  +105 u64     amount_out
  +113 u64     mm_fee                -- market-maker (LP) portion, excludes limit-order fee
  +121 u64     protocol_fee
  +129 u64     limit_order_fee
  +137 u64     host_fee
  +145 u8      fees_on_input
  +146 u8      fees_on_token_x

AddLiquidity     1f5e7d5ae3343dba  116  { lb_pair:32, from:32, position:32, amounts:[u64;2] @96, active_bin_id:i32 @112 }
RemoveLiquidity  74f461e8671f983a  116  { same shape }
ClaimFee         4b7a9a308c4a7ba3  112  { lb_pair, position, owner, fee_x:u64 @96, fee_y:u64 @104 }
ClaimFee2        e8abf2613a4d232d  116  { … , active_bin_id:i32 @112 }
ClaimReward      947486cc16ab555f  112  { lb_pair, position, owner, reward_index:u64, total_reward:u64 }
ClaimReward2     1b8ff421502b6e92  116  { … , active_bin_id:i32 }
CompositionFee   80977b6a1166718e   66  { from:32, bin_id:i16 @32, token_x_fee_amount:u64 @34,
                                          token_y_fee_amount:u64 @42, protocol_token_x_fee_amount:u64 @50,
                                          protocol_token_y_fee_amount:u64 @58 }
                                        -- NOTE bin_id is i16 here, i32 everywhere else
PositionCreate   908efc549d352579   96  { lb_pair, position, owner }
PositionClose    ffc4106b1cca3580   64  { position, owner }
Rebalancing      006d75b33d5bc7c8  180  { lb_pair, position, owner, active_bin_id:i32,
                                          x_withdrawn, x_added, y_withdrawn, y_added,
                                          x_fee_amount, y_fee_amount : u64 ×6,
                                          old_min_id, old_max_id, new_min_id, new_max_id : i32 ×4,
                                          rewards:[u64;2] }
FeeParameterUpdate        304cf17590d7f22c  37
DynamicFeeParameterUpdate 5858b287c2925bf3  46  { lb_pair, filter_period:u16, decay_period:u16,
                                                  reduction_factor:u16, variable_fee_control:u32,
                                                  max_volatility_accumulator:u32 }
IncreasePositionLength    9def2acc1e38df2e  ...
DecreasePositionLength    3476eb55aca90f80   99  { lb_pair, position, owner, length_to_remove:u16, side:u8 }
GoToABin                  3b8a4c448a8ab043  ...
```

(30 events total in the IDL; the remainder are limit-order and admin events.)

---

## 5. Edge cases a formalisation must handle

1. **`fee_bps` is a rate in 1e9 units, not basis points.** Dividing by 10 000 is a 100 000× error.
2. **Resized positions** (§1.7.1). `W ≠ 70` changes the account size *and* the physical layout of bins
   ≥ 70 (interleaved, not parallel arrays). 153 mainnet positions are already resized, and they collide
   in size with `BinArray`.
3. **Single-bin positions.** `initialize_position(lower, width=1)` is legal; the base struct is still
   8 120 bytes with 69 zeroed slots. `is_empty` scans all 70 slots **[SRC-0.12]**, so trailing garbage
   would break `close_position_if_empty`.
4. **Positions spanning bin-array boundaries.** `PositionExtension::get_bin_array_indexes_bound` returns
   `(bin_id_to_bin_array_index(lower), that + 1)` — **exactly two** bin arrays, unconditionally
   **[SRC-0.12]**. Combined with `MAX_BIN_PER_ARRAY = 70` this means a base 70-bin position touches at
   most two arrays; a *resized* position wider than 70 bins violates that assumption, and the chunked
   variants (`get_bin_array_keys_coverage_by_chunk`) exist for exactly that reason. Do not model
   "position ⊂ one bin array".
5. **`liquidity_share` dimension: Q64.64, denominated in token Y base units** (§2.3). Conversions:
   * `L_contributed = P·x + (y << 64)` computed in U256.
   * `share = ⌊L_contributed · liquidity_supply / L_bin⌋`.
   * `x_out = ⌊share · bin.amount_x / bin.liquidity_supply⌋`, `y_out` symmetric — both floored, so
     `x_out·P + y_out ≤ share` strictly in general.
   * Fee accrual divides by `liquidity_share >> 64` (the **integer part**), which loses the fractional
     64 bits. A position with `liquidity_share < 2^64` accrues **zero** fees.
6. **`Bin.price = 0` means "never initialised", not "price zero".** Recompute from `get_price_from_id`.
7. **Uninitialised bin arrays and the gap teleport** (§2.6). The active bin can jump many bins in one
   step without any trade occurring at the skipped prices, and that jump is priced into the fee.
8. **Token-2022.** `token_mint_{x,y}_program_flag` (offsets +872/+873) selects SPL Token vs Token-2022;
   `token_x_program`/`token_y_program` are separate accounts and may differ. Transfer fees are applied
   *outside* the bin math: input is `transfer_fee_excluded` before entering the loop and output is
   `transfer_fee_excluded` after, while exact-out grosses the target up with
   `transfer_fee_included` first **[SRC-0.12]**. Transfer hooks arrive as remaining accounts described
   by `RemainingAccountsInfo` (`TransferHookX`/`TransferHookY`/…), which is why every `*2` instruction
   variant exists. **A model that ignores transfer fees will not reproduce `amount_out`.**
9. **Non-SOL quote assets.** Nothing in the program privileges SOL or wSOL; `token_y` is whatever the
   creator chose. The only asymmetry is `collect_fee_mode`: `0 = InputOnly` (fee on the input token),
   `1 = OnlyY` (fee always taken on token Y, so `fee_on_input = ¬swap_for_y`) **[SRC-0.12]**.
   **4 726 of 153 867 mainnet pools use mode 1** — for those, the fee is charged on the *output* for
   X→Y swaps, which changes `amount_out` and which side the LP fee accumulator grows on.
10. **Limit orders.** When `function_type = LimitOrder` (or `Undetermined` with no reward mints
    configured), a bin's fillable output is `bin.amount_{x,y} + processed_order_remaining_amount +
    open_order_amount`, filled **MM first, then processed orders, then open orders**, and the trading
    fee is split by `split_fee` with `LIMIT_ORDER_FEE_SHARE = 5000` going to order placers
    **[SRC-0.12]**. 9 663 mainnet pools have `function_type = 2`. In those pools the *same 32 bytes* of
    `Bin` that otherwise hold `reward_per_token_stored` hold limit-order state (§1.5) — a pool cannot
    have both.
11. **Fee-rate cap and the base-fee cap interact.** `total_fee_rate` is capped at `MAX_FEE_RATE = 1e8`
    (10%). Some live pools have `base_fee_rate` already **at or above** the cap
    (e.g. `4JE4Xnsd…`: `8000·125·10·10¹ = 1e8`), so their variable component is identically zero and
    the dynamic-fee mechanism is inert. A model must apply the `min` before, not after, use.
12. **`compute_fee` vs `compute_fee_from_amount` are different functions** (§3.2) and the swap uses both
    within one bin depending on whether the bin is drained.
13. **Exact-out rounding dust goes to the protocol.** In `swap_exact_out_quote_at_bin`, if the achieved
    output exceeds the requested output by `δ > 1`, `δ` is added to `protocol_fee` and the reported
    `amount_out` is truncated to the request **[SRC-0.12]**.
14. **The oracle accumulates bin *ids*, not prices** (§1.8); `Δcum/Δt` is a time-weighted bin index, and
    `price(TWA bin) ≠ TWA price` because the bin→price map is exponential (Jensen gap).
15. **`i64` upcast in the accumulator.** `|index_reference − active_id|` is computed as
    `i64::from(index_reference) − i64::from(active_id)` then `unsigned_abs`, deliberately, so the full
    `[-443636, 443636]` span cannot overflow. Then `Δ·10000` is done in `u64` before the `min` and the
    narrowing cast to `u32`.
16. **`Position` (v1) no longer exists on chain** (0 accounts at 7 560 bytes) — `migrate_position` has
    fully run. Similarly all `BinArray`s are at `version = 2`. A model may treat the current layouts as
    total.
17. **`status` and activation.** Swaps require `status = Enabled (0)`; for `pair_type ∈ {Permission(2),
    CustomizablePermissionless(3)}` they additionally require
    `current_point ≥ activation_point`, where `current_point` is the slot or the unix timestamp
    according to `activation_type` **[SRC-0.12]**. 76 of 153 867 pools are non-Enabled.

---

## Appendix A — where the docs / source contradict the chain

| claim | source says | chain says |
|---|---|---|
| `MAX_RESIZE_LENGTH` | 70 (`commons/src/constants.rs`) | IDL constant says **91**; positions of width 88 exist |
| `get_base_fee` | v0.8.2: `base_factor · bin_step · 10` | must include `· 10^base_fee_power_factor`; 5 627 pools have it non-zero, off by 10× or 100× otherwise |
| `Bin` tail fields | v0.8.2: `reward_per_token_stored`, `amount_x_in`, `amount_y_in` | 0.12.0: limit-order fields occupying the same 48+ bytes; the SDK re-derives the reward accumulators from them |
| event tag | commonly stated as `sha256("anchor:event")[0:8]` | the on-wire bytes are the **little-endian u64** of that value, i.e. reversed |
| `Swap` event `fee_bps` | name implies basis points | it is `total_fee_rate` in 1e9 units (verified two ways) |
| `last_update_timestamp` | not written in `update_references` (line commented out); no public handler | written **only when the swap moved the active bin**; verified 437/437 events across two pools |
| swap handlers | all public copies stub `handle_exact_in` etc. to `Ok(())` | orchestration reconstructed and fitted exactly |

## Appendix B — reproduction

Everything above was produced read-only against mainnet via Helius RPC plus the on-chain Anchor IDL
account, which is at `7UZRobkzaKVm1RbCH5WdFaYCGzCRjnu3prziHAsYiSyr`
(= `create_with_seed(find_program_address([], program_id).0, "anchor:idl", program_id)`), owned by the
DLMM program, 26 244 bytes, holding a zlib-compressed IDL JSON at `data[44 .. 44+len]` with
`len = u32_le(data[40..44])`. The SDK's `idls/dlmm.json` at commit `fb02e51` is byte-equivalent in
instruction set and metadata (`lb_clmm` 0.12.0).

Pools used for verification: `HTvjzsfX3yU6BUodCjZ5vZkUrAxMDTrBs3CJaq43ashR` (SOL/USDC, bin_step 1) and
`4caKMZZyR3vxNPrDgCGDa7Dyqbn8dgYo1mtu5MNcYXQ7` (bin_step 20, `base_fee_power_factor = 1`).
Oracle: `EgEYXef2FCoEYLHJJW74dMbom1atLXo6KwPuA6mSATYA`.
