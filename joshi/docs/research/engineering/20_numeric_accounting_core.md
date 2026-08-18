# Engineering lane 20 — Numeric and accounting core

Status: engineering design candidate; no implementation or trading authorization; 2026-08-16.

## Decision summary

Joshi needs two kinds of truth that must never be collapsed:

1. **Landed financial truth** comes from reconciled finalized asset effects at the declared
   portfolio boundary. A quote, event field, SDK result, chart price, or transaction intent cannot
   override those effects.
2. **Derived numerical truth** comes from one versioned calculator with explicit integer widths,
   units, operation order, rounding, protocol profile, and input manifest.

The recommended single executable source for derived values is a small **Rust numeric/accounting
core**. Other application languages consume its canonical request/result artifacts or a narrow
local process interface; they do not independently calculate PnL, basis, quotes, or LP exposure in
production. OCaml/Zarith should supply an independently written unbounded reference model for the
conformance suite. C# should participate in the bakeoff if it remains a serious application-shell
candidate, but should not become a second financial implementation. Official TypeScript SDKs are
pinned protocol comparators, not Joshi's arithmetic authority.

This is not a decision to implement the application in Rust. It is a decision that a financial
number should have one executable meaning regardless of which language renders or studies it.

The durable ledger source is an append-oriented set of exact, commodity-aware postings and their
evidence links—not a mutable balance/PnL table. Every projection must be rebuildable. Counterfactual
ledgers are separate branches and can never post into the actual ledger.

## Scope

This lane specifies numerical truth for:

- Pump bonding-curve spot trades;
- PumpSwap and routed spot trades;
- partial exits, cash recovery, retained runners, full exits, flat intervals, and re-entry;
- exact lots, average-cost and alternative lot projections;
- transaction base fees, priority fees, tips, rent, rebates, transfer fees, and ambiguous bundles;
- mark, expected quote, minimum quote, actual fill, and full-size executable liquidation;
- Meteora DLMM per-bin inventory, fee accrual, withdrawal, and contingent conversion schedules;
- actual and counterfactual portfolio paths;
- SOL and versioned external reference-unit views;
- deterministic reproduction across Rust, OCaml, C#, TypeScript comparators, storage, and UI.

It does not select a database, UI language, LP policy, cost-basis method for taxes, execution route,
or live authority path.

## Sources and current protocol profile

“Official formula” is not a timeless phrase. Every calculation must bind a program identity,
deployed-program observation where relevant, package/source revision, state observation, and
formula profile. The following were current when this lane was written.

| Domain | Current primary source | Numerical facts used here |
|---|---|---|
| Pump curve | [Pump public docs](https://github.com/pump-fun/pump-public-docs/tree/9c82f61cb711b044a17f770ab8ce9f9bdf78f333) and official `@pump-fun/pump-sdk` 1.36.0 package | trade arguments/reserves are integer native units; curve quote order; component fees use ceiling division; fee tier is selected from on-chain configuration using integer market cap |
| PumpSwap | [official PumpSwap documentation](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/PUMP_SWAP_README.md) and official `@pump-fun/pump-swap-sdk` 1.19.0 package | constant-product integer order; fee components rounded separately; effective quote reserve includes signed `virtual_quote_reserves`; canonical-pool dynamic fees come from on-chain fee configuration |
| Pump fees | [official fee-program documentation](https://github.com/pump-fun/pump-public-docs/blob/9c82f61cb711b044a17f770ab8ce9f9bdf78f333/docs/FEE_PROGRAM_README.md) | market-cap formulas truncate integer division; thresholds use exact comparisons; noncanonical pools use flat fees; future tier changes are expected and must be read from chain |
| Meteora DLMM | [official DLMM SDK](https://github.com/MeteoraAg/dlmm-sdk/tree/fb02e51ae677bbd18e76543f702dae40632426db), package 1.9.14 | Q64.64 bin price, checked `u128`, U256 `mul_div`, explicit up/down rounding, 1e9 fee precision, dynamic-fee and per-bin traversal semantics |
| Solana fees | [Solana fee structure](https://solana.com/docs/core/fees/fee-structure) and [compute budget](https://solana.com/docs/core/fees/compute-budget) | compute-unit price is `u64` micro-lamports/CU; CU limit is `u32`; priority fee is ceiling of their product divided by 1,000,000 and uses requested rather than consumed CUs |
| Token-2022 | [official Token-2022 transfer-fee program](https://github.com/solana-program/token-2022/tree/main/program/src/extension/transfer_fee) | active configuration is epoch-dependent; transfer amounts and caps are `u64`; fee calculations and inverse-fee calculations have explicit ceiling/cap behavior |

Exact package tarball integrity digests should be captured in the eventual protocol manifest. A
package tagged `latest`, an unpinned Git branch, or the fact that an SDK is official is insufficient
for replay.

The deployed program is the final authority over a landed result. Public Meteora source does not
publish every deployed handler body, and SDKs can contain bugs or lag an upgrade. Protocol profiles
therefore require differential tests against read-only simulation and reconciled mainnet fixtures,
not source reading alone.

## The four arithmetic domains

The numeric core should expose four non-interchangeable domains.

### 1. Ledger arithmetic

Exact signed changes in named assets. Individual on-chain amounts are bounded native integers, but
portfolio sums and deltas use arbitrary-precision signed integers so aggregating many `u64` values
cannot overflow. No price or decimal conversion enters inventory conservation.

### 2. Protocol-exact arithmetic

Reproduce the deployed/official operation order, width, narrowing, overflow behavior, and rounding
literally. Use `u64`, `u128`, signed `i128`, and U256 where the profile says so. Unlimited integers
must not silently rescue an operation that would fail on chain.

### 3. Analytical exact arithmetic

Use normalized arbitrary-precision rationals for cost-basis allocation, returns, price ratios,
reference-unit valuation, and comparisons that are not themselves on-chain transfers. Do not force
these quantities into floating point or prematurely round them to lamports/cents.

### 4. Display arithmetic

Formatting only. It may abbreviate and round using a declared display policy, but its output may
never feed a trigger, limit, ledger posting, counterfactual fill, or persisted source quantity.

Each domain gets distinct types. A compiler-visible conversion is preferable to a convention in a
field name.

## Canonical numeric types and units

### Asset identity and amounts

An amount is not “a number with decimals.” Its minimum identity is:

```text
AssetId = {
  network,
  token_program,
  mint_or_native_identifier
}

AssetAmount = {
  asset_id,
  atoms: NonNegativeBigInt
}

AssetDelta = {
  asset_id,
  atoms: SignedBigInt
}
```

Native SOL and wrapped SOL remain different custody assets. A named normalization can treat one
lamport of wrapped SOL as economically convertible to one lamport of native SOL, while separately
accounting for wrapping state, token-account rent, and transaction cost. They are not made equal by
using the same symbol.

Symbols and human names are never asset keys. Record the observed owner program of each mint
account; do not infer account derivation or transfer behavior from mint bytes or ticker alone.

### Token decimals

- Store, reconcile, quote, and trade only raw atoms.
- Store mint decimals with the exact mint-account observation and token-program identity.
- Convert atoms to display text with integer `pow10`, never `10 ** decimals` in a binary float.
- A human quantity such as `1.23` is parsed only under a named asset and declared excess-digit
  policy. For financial intent, excess fractional digits should reject rather than round silently.
- Token-2022 interest-bearing or scaled-UI extensions affect display projections, not raw balance
  conservation. Transfer-fee and transfer-hook extensions affect execution semantics and must be
  profile inputs.

### Dimensioned rates and prices

Do not use one generic `Rate` or `Price`:

| Type | Meaning |
|---|---|
| `BasisPoints1e4` | Pump and Token-2022 rate with denominator 10,000 |
| `DlmmFeeRate1e9` | Meteora fee rate with denominator 1,000,000,000; never labelled bps |
| `MicroLamportsPerCu` | Solana compute-unit bid |
| `Q64x64Price` | unsigned 128-bit Meteora Y-atoms per X-atom fixed-point value |
| `AtomicPrice` | exact rational of quote atoms per base atom |
| `WholeUnitPrice` | derived rational adjusted by both mint decimal exponents |
| `ReferenceQuote` | versioned external reference-unit price observation |

For a Meteora Q64.64 price `P` whose dimension is Y atoms per X atom:

```text
atomic_price  = P / 2^64
whole_price   = P * 10^decimals_x / (2^64 * 10^decimals_y)
```

Both remain rational. The UI may decimal-format the result; the schedule and quote core do not.

### Time and order

Slots, transaction indices, instruction indices, epochs, Unix seconds, and wall-clock nanoseconds
are different types. None is a float. A fee configuration selected by epoch or market state carries
the exact state/epoch observation used.

## Integer-width and overflow policy

### Wire and on-chain widths

- SOL lamports, SPL token amounts, most Pump reserves, and instruction amount bounds are `u64`.
- PumpSwap `virtual_quote_reserves` is signed `i128`; adding it to a raw `u64` reserve must use a
  checked signed intermediate and reject nonpositive or out-of-profile effective reserves.
- Solana CU limit is `u32`; CU price is `u64`; their product must be computed above `u64` before
  ceiling conversion to lamports.
- Meteora bin prices and liquidity quantities use `u128` Q64.64 values. Multiplying two `u128`
  operands for `mul_div` requires U256. U256 is an intermediate, not a wire type; the result must be
  checked before narrowing.
- Signed ledger deltas must not use `i64`: negating or summing `u64::MAX` is outside it. Use bounded
  `i128` for one known-safe subtraction or arbitrary signed integer for durable postings.
- Never use Rust `usize`, OCaml `int`, C# `long`, JavaScript `number`, or database `BIGINT` as a
  generic financial amount merely because it is convenient on one platform.

### Operation policy

Every arithmetic primitive names its behavior:

```text
checked_add
checked_sub
checked_mul
checked_narrow
mul_div_floor
mul_div_ceil
div_floor_nonnegative
div_ceil_nonnegative
div_trunc_toward_zero
pow10_checked
q64_mul_floor
```

No protocol path uses language-default overflow. Rust release overflow wrapping, C# unchecked
contexts, OCaml machine-int overflow, JavaScript precision loss, and database coercion must all be
structurally unavailable at the boundary.

When a protocol deliberately uses saturating or wrapping behavior, the profile names that exact
operation. “Safer” checked arithmetic is not protocol-exact if the deployed program wraps; an
emulator must reproduce the deployed behavior and a planner may separately refuse the state.

All serialized big integers have per-type digit/bit limits checked before allocation. Arbitrary
precision is not permission for an untrusted payload to allocate an arbitrary-size integer.

## Rounding is provenance

Algebraically equivalent formulas are often numerically inequivalent after integer division.
Preserve the literal operation graph.

For every protocol-derived quantity retain:

- formula/profile identifier and version;
- ordered operands in native units;
- intermediate width where it matters;
- rounding at each division or shift;
- quotient and remainder for auditable `mul_div` steps;
- cap/min/max and checked-narrow decisions;
- result or typed error;
- source-state observation/hash.

This does not require persisting a huge trace for every UI refresh. The calculator must be able to
emit a trace for any retained quote/scene and golden vector, and the derived artifact records enough
inputs to regenerate it byte-for-byte.

Required rounding modes are:

- **floor/down** for nonnegative protocol quantities;
- **ceiling/up** where the protocol protects required input or collects a fractional fee;
- **toward zero** only where a signed protocol operation explicitly says so;
- **half-even**, if desired, for display-only decimal formatting;
- **exact rational**, with no rounding, for analytical allocation and ratios.

Negative analytical values make “floor” and “truncate” materially different. Never reuse a helper
written for nonnegative protocol amounts on signed PnL.

## Current Pump curve arithmetic profile

The official SDK 1.36.0 currently implements the important paths in this order. These summaries
are conformance targets, not a substitute for pinning the package and state.

### Fee tier

```text
market_cap_quote_atoms = floor(
  virtual_quote_reserves * mint_supply / virtual_token_reserves
)
```

Select the first tier when below its threshold; otherwise select the last tier, iterated from the
highest threshold downward, whose threshold is `<= market_cap`. The configuration is read from the
on-chain FeeConfig used at the quote state. Do not hardcode today's tier table.

For the current SDK's fee helper, a component fee is:

```text
component_fee = ceil(amount * component_bps / 10_000)
```

Protocol and creator components are rounded separately. `ceil(a*x/d) + ceil(a*y/d)` can differ
from `ceil(a*(x+y)/d)`; the latter is not a valid optimization. Whether creator fees apply depends
on the curve state/mode and is part of the profile input.

### Exact-token buy quote

For `q` base atoms, capped by real reserves:

```text
raw_quote = floor(q * virtual_quote / (virtual_token - q)) + 1
total_quote = raw_quote
            + ceil(raw_quote * protocol_bps / 10_000)
            + applicable ceil(raw_quote * creator_bps / 10_000)
```

The literal `+1` is not replaced by generic ceiling division; it also adds one when the division is
exact. Boundary vectors must preserve that behavior.

### Exact-quote buy estimate

The current SDK backs fees out of the gross quote amount with integer operations, subtracts one
atom before the constant-product step, floors the base output, and caps it at real token reserves.
The exact sequence, including `amount - 1`, receives golden vectors at 0, 1, exact-divisible, and
near-reserve boundaries. It must not be rewritten as a real-number constant-product equation.

### Sell estimate

```text
raw_quote = floor(base_in * virtual_quote / (virtual_token + base_in))
net_quote = raw_quote
          - ceil(raw_quote * protocol_bps / 10_000)
          - applicable ceil(raw_quote * creator_bps / 10_000)
```

An actual fill remains the reconciled balance effect. This quote profile forecasts or constructs a
counterfactual; it does not override the fill.

## Current PumpSwap arithmetic profile

Define:

```text
effective_quote_reserve = raw_quote_vault_amount + virtual_quote_reserves
```

The official docs say the virtual field is currently zero on pools, but it is part of state and is
already included in current event/SDK shapes. Ignoring it because today's values happen to be zero
is a replay bug waiting for a state change.

### Exact-base buy

```text
raw_quote_in = ceil(effective_quote_reserve * base_out
                    / (base_reserve - base_out))

total_quote_in = raw_quote_in
               + ceil(raw_quote_in * lp_bps / 10_000)
               + ceil(raw_quote_in * protocol_bps / 10_000)
               + applicable ceil(raw_quote_in * creator_bps / 10_000)
```

### Exact-base sell

```text
raw_quote_out = floor(effective_quote_reserve * base_in
                      / (base_reserve + base_in))

net_quote_out = raw_quote_out
              - ceil(raw_quote_out * lp_bps / 10_000)
              - ceil(raw_quote_out * protocol_bps / 10_000)
              - applicable ceil(raw_quote_out * creator_bps / 10_000)
```

Current SDK logic additionally checks that real quote reserves—not only effective reserves—can
cover the payout condition. Exact-quote paths have different inversion and correction steps and
must receive separate formula IDs rather than being inferred by algebraically inverting these two.

For canonical Pump pools, fee selection uses integer pool market cap:

```text
market_cap = floor(effective_quote_reserve * base_mint_supply / base_reserve)
```

For noncanonical pools, current fee configuration returns flat fees. Canonical-pool identity,
creator/coin-creator distinction, mint supply, effective reserves, fee account, and state slot are
quote inputs.

The official TypeScript SDK accepts slippage as a JavaScript `number` in some helpers. Joshi must
not inherit that boundary. Represent slippage/limits as integer basis points or an exact rational,
then compute instruction maxima/minima with a documented rounding direction.

## Solana execution-cost attribution

### Actual cost first

The transaction metadata's total fee and finalized household balance changes are authoritative for
actual cost. A computed fee breakdown is explanatory and must reconcile to the actual total or
leave a named residual.

Current priority fee arithmetic is:

```text
priority_micro_lamports = requested_cu_limit * micro_lamports_per_cu
priority_lamports       = ceil(priority_micro_lamports / 1_000_000)
```

It uses the requested limit, not consumed CUs. Base fee depends on message/signature/runtime state.
Do not permanently assume 5,000 lamports per signature even when it is current; retain the observed
or runtime-derived fee inputs. A failed landed transaction pays its fee and may have no trade fill.

### Cost component model

Keep distinct postings/annotations for:

- venue consideration paid or received;
- venue LP/protocol/creator fees embedded in the asset delta;
- Token-2022 withheld transfer fee;
- Solana base fee;
- priority fee;
- explicit validator/bundle tip;
- account rent deposited;
- rent refunded;
- irreversible account/data-allocation cost where applicable;
- later cashback, creator-fee recapture, rebate, or reward;
- unexplained residual.

Venue fees already embedded in the user's net input/output are decomposition, not another debit.
The calculator must prove that gross amount, fee components, and net boundary delta agree before a
breakdown is marked reconciled.

Rent is not automatically expense. It moves liquid SOL into a recoverable account balance/claim
until the account closes, unless evidence shows an irreversible cost. A rent refund changes custody
and liquidity, not trade PnL. Attribute opportunity cost separately. Account creation and closure
can occur in a transaction with a swap and must not be mistaken for price impact.

For a transaction containing several economic actions, preserve the exact household total and
allocate shared network cost only under a named prospective rule. If exact instruction causality is
unavailable, per-episode cost is ambiguous while household cost remains exact.

## Token-2022 boundaries

The asset profile must record the token program and every extension affecting amounts or transfer
feasibility. In particular:

- select the transfer-fee configuration by chain epoch;
- compute the forward transfer fee and inverse pre-fee amount with the official ceiling and maximum
  cap order;
- distinguish gross debited, spendable credited, and withheld atoms;
- represent withheld amounts as controlled assets only when the portfolio domain owns the relevant
  withdrawal right;
- carry transfer-hook account/state requirements in quote feasibility, not price arithmetic;
- reject an unsupported extension/profile rather than silently treating it as ordinary SPL Token.

Meteora applies Token-2022 transfer-fee calculations outside its internal bin swap math. A quote
must not apply the fee twice or omit it on the output leg.

## Lots, basis, partial exits, and runners

### Actual ledger before basis

Every economic action first produces an exact multi-asset flow vector. A spot purchase with SOL has
an obvious SOL consideration; a token-token LP conversion may not. Do not manufacture a SOL basis
for a multi-asset exchange by using a later price.

An acquisition lot records:

- acquired asset and exact atoms;
- exact consideration vector;
- attributable irreversible cost vector;
- transaction/event provenance and chain order;
- basis quality (`known`, `estimated`, `partial`, `unknown`) and why;
- remaining atoms;
- optional derived basis in a named reference asset with valuation manifest.

Incoming controlled-domain transfers carry lot lineage and do not realize PnL. Unknown incoming
basis remains unknown. An executable quote can value the asset now but cannot become historical
basis.

### Average-cost operational projection

Within an inventory epoch, keep remaining basis as an exact rational in the chosen reference asset.
For remaining quantity `Q`, remaining rational basis `B`, and partial sale quantity `sQ`:

```text
allocated_basis = B * sQ / Q       # exact rational
realized_delta  = net_proceeds - allocated_basis
new_basis       = B - allocated_basis
new_quantity    = Q - sQ
```

Using a rational prevents arbitrary sub-lamport rounding from making partial-sale partitioning alter
the result. Reduce numerator/denominator after each operation. When the epoch becomes exactly flat,
remaining basis must be exactly zero and the sum of realized deltas must equal the integer net-cash
identity. Display rounding is applied only afterward.

If rational denominator growth becomes an operational problem, the alternative is a versioned
integer residual rule—floor allocations until the final disposal consumes all residue. That is a
different projection and must not silently replace the rational one.

Preserve acquisition lots independently for FIFO, LIFO, specific-identification, and sensitivity
views. These may also require rational pro-rata allocation for a partially consumed lot. Tax
reporting is explicitly out of scope and may impose a jurisdiction-specific projection later.

### Retained runners

A partial exit does not zero the remaining basis or value. Show separately:

- allocated realized result;
- net cash returned relative to cash spent;
- remaining exact quantity;
- remaining rational basis and its quality;
- current full-size executable liquidation value;
- current value at risk and unquotability/impact;
- episode and management-tranche attribution.

“Initial cash recovered” is a cash-flow fact. “Free runner” is not a numeric state.

If an old runner receives a new crackle acquisition, household average cost can remain exact while
management attribution stays unknown unless a prospective tranche allocation says which units a
later sale manages. The calculator must not choose a profitable-looking LIFO/FIFO story after the
outcome.

## Mark, quote, liquidation, and fill

Use separate artifact types:

| Artifact | Numeric meaning |
|---|---|
| chart/last mark | contextual price observation; no capacity promise |
| marginal pool price | infinitesimal or reserve-derived ratio; not a bag quote |
| expected executable quote | integer expected outputs for an exact input/route/state |
| instruction bound | exact `maxIn` or `minOut`; not expected fill |
| stressed liquidation | scenario calculation with explicit haircuts/path |
| actual fill | reconciled household asset effects of a landed action |
| post-fill balance | independent inventory check; may include unrelated bundled effects |

A liquidation artifact includes exact input amount, expected and minimum outputs, every cost
included/excluded, route/venue, reserve and fee state, slot/request/receive/expiry clocks, quote
engine/profile, and quality. Never scale a one-token or 0.1-SOL quote linearly to a full bag.

Missing route or stale state is `unquotable/unknown`, not numeric zero. A zero liquidation scenario
requires explicit evidence/assumption and cannot masquerade as a fresh quote.

For an LP, executable liquidation is a composed path:

1. withdraw current per-bin entitlement under a named state;
2. include claimable/claimed fees exactly once;
3. account for rent release and transaction fees separately;
4. quote each resulting asset at the actual size into the chosen reference asset;
5. report unrouteable legs rather than dropping them.

## DLMM bin math and contingent schedules

### Exact bin state

Persist/reconstruct each position version with:

- exact pool, token programs, mints, decimals, and deployed-program profile;
- active bin and observation slot/time;
- position lower/upper bin and dynamic length;
- per-bin X atoms, Y atoms, Q64.64 liquidity shares, and accrued-fee checkpoints;
- pool per-bin reserves, liquidity supply, fee accumulators, function/collection mode;
- bin-array presence/gaps and Token-2022 transfer-fee state;
- schedule intent separately from protocol state.

### Price

Current official Meteora math computes:

```text
bps_q64  = floor((bin_step << 64) / 10_000)
base_q64 = 2^64 + bps_q64
price_q64(bin_id) = protocol_pow_q64(base_q64, bin_id)
```

`protocol_pow_q64` is repeated integer Q64.64 multiplication/shift with an inversion trick using
`u128::MAX / value`, not ideal real exponentiation. Every intermediate truncates. A decimal `pow`
or floating exponent will disagree at some bins and cannot be used for schedule truth.

### Liquidity and withdrawal

Within a bin, current public math uses constant-sum Q64.64 liquidity:

```text
L = price_q64 * x_atoms + (y_atoms << 64)       # U256 intermediate

share = floor(contributed_L * bin_supply / bin_L)
x_out = floor(share * bin_x / bin_supply)
y_out = floor(share * bin_y / bin_supply)
```

Flooring creates real dust. Removing a percentage from a bin range must use the protocol's
per-bin share/amount operations and cannot multiply the position's aggregate token balance by a
percentage.

### Swap and fee rounding

Current public math uses U256 `mul_div` with explicit rounding. Examples:

- exact-in output: down;
- input required to drain/provide exact output: up;
- fee added atop known net input: `ceil(amount*r/(1e9-r))`;
- fee included in gross input: `ceil(amount*r/1e9)`;
- protocol share of fee: down;
- LP liquidity shares and withdrawal output: down.

DLMM rates use precision `1e9`, not basis points. Current total fee is capped at 10% and combines:

```text
base_rate = base_factor * bin_step * 10 * 10^base_fee_power_factor

variable_rate = ceil(
  variable_fee_control * (volatility_accumulator * bin_step)^2 / 10^11
)

total_rate = min(base_rate + variable_rate, 100_000_000)
```

The variable accumulator is stateful and changes across traversed bins. A multi-bin quote therefore
requires the ordered pool state machine, not a fee percentage applied once to aggregate volume.

### Contingent schedule outputs

An LP schedule calculation should emit exact inventory at:

- current state;
- each materially funded bin boundary;
- complete traversal to the lower edge;
- complete traversal to the upper edge;
- each proposed add/remove/rebalance state;
- withdrawal without swaps;
- liquidation through named executable routes.

It must preserve token quantities before converting them to SOL/USD. A rebalance is a custody and
schedule transformation unless an explicit swap occurs; closing an LP account is not a token sale.
In-place rebalance simulation and landed post-state get different artifact IDs and must reconcile.

## Reference units and FX

The actual ledger is multi-commodity and does not need a universal currency to balance.

Reference views are derivations:

- SOL view uses exact lamports where an action actually paid/received SOL and a versioned quote for
  non-SOL residuals;
- USD view uses a named source, pair, timestamp, availability time, exact decimal/rational value,
  and staleness/quality;
- hold-SOL, hold-token, and other benchmarks are counterfactuals, not corrections to PnL.

Serialize a vendor decimal exactly as its character representation and parse it into a rational
`coefficient / 10^scale`. Do not first parse through `double`, OCaml `float`, Rust `f64`, or C#
`double`. C# `decimal` is useful for display/business inputs but is not the canonical storage type:
its 96-bit coefficient and maximum 28–29 decimal digits cannot cover all protocol intermediates.

Every cross-rate names its derivation path. A USD value derived through token/SOL and SOL/USD is
not interchangeable with a direct token/USD observation. Updating FX creates a new derivation and
never rewrites native-unit PnL.

## Financial journal and reconciliation

### Commodity-aware postings

The journal records balanced movements per asset between named accounts such as:

- controlled wallet/token account;
- controlled LP custody;
- controlled recoverable-rent claim;
- external venue/counterparty;
- network fee expense;
- explicit tip expense;
- unknown/unclassified boundary;
- rebate/fee-receivable custody where the right is actually controlled.

Debits and credits for each asset must sum to zero once external/expense/equity boundary accounts
are included. Strategy book, episode, lot, and tranche labels are attribution dimensions, not the
balancing accounts that determine inventory.

### Transaction reconciliation order

1. Retain exact transaction/message/meta/account evidence and finality.
2. Compute controlled-domain pre/post native and token balances, including created/closed accounts.
3. Produce exact per-asset household deltas.
4. Decode program/instruction/event evidence to classify flows and decompose fees.
5. Reconcile classification back to the boundary delta.
6. Create/update lots and basis projections only after the fill effect is established.
7. Reconcile aggregate projected holdings to independent finalized balance snapshots.

Logs and events can explain a fill but cannot override the household balance. Balance alone may not
identify intent or split a bundled transaction; that ambiguity remains explicit.

Provisional and finalized projections are separate versions. Rollback/finality correction appends
a retraction/replacement rather than mutating the earlier observation. Rebuilding from the same
evidence and calculator version must produce the same canonical digest.

### Attribution of expenses

Household cost remains exact even when episode allocation is not. Shared fees may be allocated by a
prospectively declared rule, but the output must carry `allocated` rather than `observed` quality.
No unallocated cost disappears to make a book profitable.

## Counterfactual ledgers

A counterfactual is a separate immutable branch rooted at an explicit knowledge cutoff and actual
portfolio snapshot. Its type cannot be passed to an actual-ledger posting API.

Each branch records:

- branch/run and parent snapshot IDs;
- policy/treatment and version;
- exact eligible information manifest;
- quote/protocol/calculator versions;
- assumed observation, decision, send, and landing latency;
- modeled fee, rent, tip, failure, capacity, and partial-fill rules;
- exact hypothetical fills and lots;
- missing/unquotable intervals;
- common terminal horizon and residual liquidation method;
- pseudorandom seed and draw manifest when a stochastic model is used.

Counterfactual basis begins from the branch's exact inventory and treatment; it never borrows a
later actual lot. Exit–flat–re-entry versus hold-through, partial-plus-runner versus full exit, and
LP edit versus unchanged schedule are each separate branches. Saved downside, forgone upside, and
benchmark regret remain comparison outputs and never become actual PnL postings.

No branch result may be called a fill. Preferred vocabulary is `hypothetical_execution` or
`counterfactual_fill_effect` with visible treatment/profile labels.

## Canonical serialization

### Durable interchange form

Use UTF-8 JSON with an RFC 8785 JSON Canonicalization Scheme representation for hashing and golden
vectors. JSON is chosen for inspectability and broad language support, but its numeric type is not
used for financial quantities.

Rules:

- every integer, including slots and timestamps when used in hashed calculation artifacts, is a
  canonical base-10 string;
- nonnegative zero is exactly `"0"`; no leading `+`, no leading zeros, no whitespace, no exponent;
- signed zero and `"-0"` are invalid;
- rationals are `{ "numerator": "...", "denominator": "..." }`, reduced by GCD, denominator
  positive, zero normalized to `0/1`;
- raw bytes are lowercase hex or unpadded base64url under a field-specific rule, never a mixture;
- public keys carry canonical 32-byte identity plus a validated base58 display form if desired;
- maps whose ordering affects meaning are forbidden; use arrays with declared stable ordering;
- optional/unknown/known-zero are tagged states, not `null` overloads;
- enum tags and formula IDs are ASCII and schema-versioned;
- no NaN, infinity, binary float, locale-dependent decimal, or implicit unit;
- unknown fields follow the schema's explicit reject/preserve policy; financial commands reject
  unknown semantic fields rather than guessing.

Protobuf/database representations may be generated later for performance, but canonical hashes and
goldens are defined over this form. Do not depend on “deterministic protobuf” across runtimes or a
database driver's decimal coercion.

### Calculation artifact

Every retained derived value should name:

```text
schema_version
calculator_version and source commit
formula_profile_id
protocol program/package/deployment identity
ordered input observation/content hashes
canonical request hash
canonical result or typed error
rounding/trace availability
production time (not part of pure result hash)
quality and missingness
```

Changing a formula produces a new derivation. Historical artifacts are not overwritten; comparison
and migration are explicit.

## Reproducibility across languages

### Determinism requirements

- no implicit current time, locale, process-random seed, network fetch, environment decimal mode,
  unordered map iteration, or architecture-sized integer inside a pure calculation;
- all state and configuration enter in the request;
- sort only by a declared byte/integer key;
- pin source packages and checksum their exact artifacts;
- compile Rust with overflow checks and still use explicit checked/narrow helpers;
- disable or isolate CPU floating behavior by banning float from canonical calculation paths;
- return typed errors with stable codes, not language-specific exception text;
- hash canonical input and output separately;
- keep property-test seeds and minimized counterexamples.

### Code generation boundary

Generate only mechanical boundaries initially:

- JSON schema/types and validators;
- enum/formula IDs;
- canonical serializer test harnesses;
- protocol IDL account/instruction decoders, immediately wrapped in domain types;
- vector runners for Rust, OCaml, C#, and TypeScript.

Do not generate several arithmetic implementations from an ad hoc formula DSL in Slice 1. That
would make the generator another unverified numerical core and would correlate bugs across every
language. The OCaml oracle should be independent. If a later small typed arithmetic IR gains a
formal semantics and proved/interpreted backends, it can replace this decision deliberately.

## Language comparison

| Criterion | Rust | OCaml | C# |
|---|---|---|---|
| Solana/protocol affinity | strongest; deployed ecosystem and official arithmetic are predominantly Rust | weak SDK affinity; decoders and RPC integration require more bespoke work | moderate client ecosystem, weaker protocol-source affinity |
| bounded integers | native `u64/u128`; U256 libraries; explicit checked/narrow operations | machine `int` is unsuitable; Zarith plus explicit bounds can model widths exactly | `ulong/UInt128` available on modern .NET; `checked` must be pervasive; U256 bespoke/library |
| arbitrary integers/rationals | `num_bigint`/`num_rational`; adequate, not built in | Zarith `Z`/`Q` is excellent for an independent mathematical oracle | `BigInteger` built in; no built-in rational canonical type |
| fixed decimal | external crates; should remain display-only | external libraries; rational formatting straightforward | built-in `decimal`, but 96-bit/28-digit limit makes it unsuitable for protocol truth |
| type safety for units | strong newtypes, enums, ownership, `Result` | very strong algebraic types/modules | strong structs/records, but operator/conversion discipline required |
| overflow footguns | release arithmetic can wrap unless checked/profiled; `as` casts dangerous | machine-int overflow and accidental float use | unchecked is default outside `checked`; decimal overflow/rounding context |
| sharing with other components | local service/CLI, C ABI, WASM possible | process or C FFI; operational ecosystem smaller | natural for a C# shell; cross-language service straightforward |
| independent-oracle value | poor if it merely copies Rust protocol source into production core | excellent: different runtime and Zarith make correlated bugs less likely | useful third implementation, especially serialization and .NET boundary bugs |
| recommended role | **single production calculator and journal projector** | **independent exact reference/conformance oracle; later formal bridge if earned** | consumer plus conformance candidate; production arithmetic only through core |

Rust wins here because the hardest protocol arithmetic already speaks in its integer widths and
because one core can serve any eventual UI. OCaml is more valuable as an independent reference than
as a second production path. C#'s excellent application ergonomics do not justify allowing a UI or
service layer to recompute money.

The application may still choose OCaml or C# for substantial nonfinancial components. The boundary
is semantic, not tribal.

## Invariants

### Arithmetic invariants

1. No source asset quantity or landed delta passes through binary floating point.
2. Every amount and price carries dimensions; unlike assets cannot be added.
3. Protocol-exact functions reproduce width, operation order, rounding, caps, and failure behavior.
4. Every narrowing conversion is checked; no platform-width integer appears in canonical data.
5. A rational is normalized and denominator-positive; display rounding cannot feed calculation.
6. Separate fee components are rounded in the same order as the active protocol profile.
7. Formula profile plus canonical input determines one canonical output/error digest.

### Ledger invariants

8. Per-asset postings balance, including named external/expense/unclassified boundary accounts.
9. Consolidated quantity equals independent finalized balances or exposes an exact residual.
10. Internal wallet and LP custody changes create no economic PnL.
11. Actual transaction total fee reconciles before any component allocation is trusted.
12. Failed landed transactions can incur cost without creating a fill.
13. Rent deposit/refund and venue consideration remain distinguishable.
14. Unknown basis never becomes zero basis or current mark basis.
15. Full closure consumes exact remaining rational basis and closes to the flat-epoch cash identity.
16. Runner quantity, basis, executable value, and risk remain live after cash recovery.

### Quote and LP invariants

17. Mark, quote, bound, fill, and balance are different artifact types.
18. A quote binds exact size, route, state, fees, clocks, and profile; absent/stale is not zero.
19. LP aggregate inventory equals the sum of per-bin entitlement under the same state/profile.
20. LP withdrawal/rebalance changes custody/schedule but does not imply a swap or SOL realization.
21. Current, lower-edge, and upper-edge LP asset compositions are all available without decimal
    approximation.
22. Token-2022 transfer fees are applied exactly once at their protocol boundary.

### Counterfactual invariants

23. Actual and counterfactual posting types cannot be mixed or merged.
24. A branch uses only state available at its declared cutoff plus named assumptions.
25. Re-running a branch with identical inputs, seed, and calculator version is byte-identical.
26. Saved loss, forgone gain, and opportunity cost never post as realized PnL.

## Golden-vector corpus

Goldens are reviewed artifacts. CI must never regenerate expected outputs using the implementation
under test. Every vector names its authority: manually derived, official SDK/package, protocol
source, read-only simulation, landed transaction, or independently agreed reference result.

### Primitive vectors

- decimal-string canonicalization and rejection cases;
- signed/unsigned bounds at `0`, `1`, maximum, maximum±1;
- checked add/sub/mul/narrow success and failure;
- floor/ceiling with exact and nonzero remainders;
- negative rational formatting and display rounding;
- U256 intermediate whose output fits `u128`, and one whose narrowing fails;
- priority-fee products at zero, exact million, remainder one, and upper CU/price bounds;
- `pow10` and decimal conversion without float.

### Pump/PumpSwap vectors

- component-fee ceilings where summed components differ from a combined rate;
- market cap just below, exactly at, and above every fee threshold;
- standard, Mayhem, zero/default creator, cashback/other supported mode distinctions;
- curve buy/sell at amount 0, 1, exact-divisible `+1`, reserve cap, and near-denominator-zero;
- exact-quote and exact-base paths as separate vectors;
- PumpSwap raw versus nonzero virtual quote reserve;
- canonical versus noncanonical fee selection;
- real-reserve payout failure despite effective reserve pricing;
- slippage rational/bps boundaries;
- package version drift vector whose expected output intentionally changes only under a new profile.

### DLMM vectors

- Q64.64 bin price at bin 0, positive/negative IDs, min/max supported IDs, multiple bin steps;
- `u128::MAX` reciprocal quirk in the official `pow` path;
- U256 `mul_div` up/down and exact remainder trace;
- per-bin exact-in, exact-out, full-drain, and dust behavior;
- base fee power factor, variable fee ceiling, total-fee cap;
- protocol/host/LP fee splits;
- Token-2022 input/output transfer fee and inverse fee;
- deposit share and partial/full withdrawal dust;
- gap/uninitialized bin-array traversal and unsupported profile errors;
- lower/current/upper schedule inventory conservation;
- remove/rebalance simulation versus landed post-state fixture.

### Accounting vectors

- one buy and full sell closing exactly to net cash flow;
- partial profit with runner and exact rational remaining basis;
- cash recovered while remaining basis is nonzero;
- runner plus new crackle lot with unassigned management tranche;
- full exit, flat watch, and re-entry with fresh epoch basis;
- controlled internal transfer preserving lots;
- unknown incoming basis;
- failed transaction with fee but no fill;
- bundled transaction with exact household cost and ambiguous episode allocation;
- rent deposit and later refund;
- mark available but full-size route unquotable;
- LP close returning tokens rather than SOL;
- same counterfactual branch run twice with identical digest.

### Serialization vectors

Each language must accept and emit the same canonical bytes for all valid vectors and reject all
invalid encodings: leading zeros, `-0`, unreduced rationals, zero/negative denominator, JSON numeric
money, Unicode-confusable enum tags, unordered semantic maps, oversized integers, and unknown
financial command fields.

## Conformance bakeoff

### Contenders

1. Rust candidate numeric core.
2. Independent OCaml/Zarith reference model.
3. C#/BigInteger implementation of the same public contract if C# remains an application candidate.
4. Pinned official Pump and Meteora TypeScript SDKs as external differential comparators for the
   formula paths they expose.

The TypeScript comparator is not required to agree where the official helper intentionally uses a
floating UI slippage boundary or where a deployed-program fixture supersedes it. Such exceptions
must be narrow, reviewed, and encoded in the profile—not waved away.

### Stages

1. **Serialization:** canonical bytes and stable typed errors.
2. **Primitive arithmetic:** exhaustive small domains plus adversarial boundaries.
3. **Protocol formulas:** golden and randomized valid states, with operation traces on mismatch.
4. **Chain differential:** pinned SDK, read-only simulation, and historical landed fixtures.
5. **Accounting:** lots, rational basis, fees/rent, LP custody, and exact portfolio reconciliation.
6. **Counterfactual replay:** branch determinism, causal cutoff, and canonical digest.
7. **Mutation test:** deliberately change every rounding mode, fee-component order, width check, and
   reserve choice; the suite must kill the mutation.
8. **Performance/operability:** measure realistic portfolio replay and quote batches only after
   correctness. No correctness concession is allowed to win a benchmark.

### Pass gate

- zero unexplained valid-vector mismatches;
- zero differences in canonical output or typed error for normative vectors;
- every official-SDK/deployed-program discrepancy assigned to a pinned profile and fixture;
- all mutation operators detected;
- deterministic rebuild digest on two architectures and at least two language runners;
- resource bounds reject adversarial oversized inputs before expensive big-integer work;
- no float reaches a canonical calculation API under static and runtime instrumentation.

If Rust fails this gate, it does not become the source of truth by architectural preference. Fix or
reconsider it. If C#/OCaml pass but differ only because they used unbounded arithmetic where the
protocol overflows, Rust/protocol-exact failure behavior still wins for that profile; the oracle
must enforce the same bounds explicitly.

## Failure modes this design must prevent

1. JavaScript `number` rounds a token atom, reserve, slot, or slippage threshold.
2. C# `decimal` or SQL `NUMERIC` silently truncates a Q64.64/U256 intermediate.
3. OCaml/Rust arbitrary precision makes a quote succeed where the chain would overflow.
4. Rust release wrapping or `as` narrowing changes an amount without an error.
5. Fee components are added before one ceiling rather than ceiled separately.
6. A current dynamic fee tier is hardcoded and replayed onto a prior state.
7. PumpSwap uses raw vault reserve while the protocol uses effective reserve.
8. Meteora `fee_bps` is divided by 10,000 although its unit is 1e9 precision.
9. Real exponent/decimal bin price replaces the protocol Q64.64 power path.
10. LP aggregate percentages replace per-bin share withdrawal and lose dust/state.
11. Token-2022 transfer fee is omitted or applied twice.
12. Transaction metadata fee and derived components are both posted as expenses.
13. Rent is expensed on account creation and counted as income again on refund.
14. A UI mark is multiplied by bag size and labelled executable liquidation.
15. Closing an LP is recorded as realizing SOL when it returned tokens.
16. Partial basis rounding makes sale partitioning manufacture PnL.
17. Re-entry inherits the prior flat epoch's basis.
18. A recovered cash basis causes the runner's economic value to become zero.
19. Unknown incoming basis is set to the current quote.
20. Cross-wallet/LP custody transfers create profit or reset lots.
21. A multi-action fee allocation changes household total or disappears from all books.
22. USD revaluation rewrites native SOL/token PnL.
23. Counterfactual “saved loss” is posted into actual PnL.
24. A golden file is regenerated by the code it is supposed to test.
25. Schema/code generation duplicates a wrong formula consistently across every language.

## Smallest engineering experiment

Run the conformance bakeoff offline on a deliberately small Slice 1 corpus. Do not build a general
pricing service or connect transaction authority.

Corpus:

- the three retained-runner accounting fixtures named in the foundation, with public/sanitized raw
  transaction evidence and explicit basis gaps;
- one prospective external partial-exit or exit/re-entry episode when it occurs naturally;
- one Pump curve quote state and one PumpSwap state at two sizes;
- one Meteora position snapshot with several funded bins and a hypothetical partial remove;
- one failed transaction and one rent-create/refund lifecycle;
- 100–300 hand-reviewed primitive/protocol/accounting goldens plus deterministic generated cases.

Outputs:

1. language comparison report with every mismatch and operation trace;
2. canonical schema and vector format proposal;
3. exact rebuilt asset ledger and quantified unresolved classifications;
4. mark versus full-size liquidation comparison;
5. partial-runner and flat-re-entry basis projections;
6. current/lower/upper LP contingent inventory vectors;
7. deterministic digest reproduced by Rust and the independent OCaml runner;
8. a go/no-go recommendation for making the Rust core the Slice 1 calculator.

Success means the exact asset ledger closes or exposes named evidence gaps, formula mismatches are
zero or explicitly profile-scoped, and Ember-facing runner/LP numbers can be traced to raw atoms and
rounding. It does not mean any strategy is profitable.

## Dependencies and unresolved choices

Dependencies:

- finalized transaction/account observations and declared portfolio domain;
- exact Pump/PumpSwap fee/reserve state and program/package manifests;
- exact Meteora account layouts, program deployment identity, and per-bin state;
- quote lifecycle and source-health contracts;
- episode/epoch/lot/tranche semantics from the foundation;
- append-oriented evidence IDs and canonical content hashing;
- explicit missingness and correction records.

Unresolved choices to settle in the bakeoff/reconciliation:

- precise Rust big-integer/rational and U256 libraries and their audit posture;
- whether canonical JSON is sufficient for throughput or needs a generated binary mirror;
- rational-basis resource limits and whether an integer-residual display projection is also useful;
- exact transaction fee/rent classification coverage available from RPC evidence;
- formula-profile key for upgradeable programs: program-data hash, deploy slot, IDL hash, SDK
  package digest, or a required combination;
- which Token-2022 extensions Slice 1 supports versus explicitly refuses;
- whether C# remains likely enough to justify a full third implementation in the bakeoff;
- whether the OCaml oracle later connects to Lean/executable specifications or remains a test
  model;
- retention policy for full arithmetic traces versus reproducible inputs only.

## Decision boundary

Do not let application stack selection create a second financial calculator. Do not implement
transaction construction, signing, submission, automated LP edits, or live trading in this lane.
The next decision is whether the offline bakeoff validates one Rust numeric core and its canonical
contract strongly enough for Slice 1's read-only exposure truth.
