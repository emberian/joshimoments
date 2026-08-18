# Glossary

Definitions are compact restatements of the book. The final column flags how JOSHI must reinterpret
the term rather than importing it blindly.

## Market objects and prices

| term | distilled meaning | JOSHI boundary |
| --- | --- | --- |
| **asset** | The traded instrument whose ownership and price are studied. | A mint is not enough: network, token program, venue/pool, lifecycle, and quote asset matter. |
| **bid / ask** | Highest displayed buy price / lowest displayed sell price in an LOB. | Pump/PumpSwap have reserve-derived quotes, not standing bid/ask queues. Use only for genuine LOB sources. |
| **bid–ask spread** `s=a-b` | Cost gap between immediate buying and selling at the best displayed quotes. | On AMMs, distinguish buy/sell quote round-trip, fees, price impact, transfer costs, and landing risk; do not call all of it a spread. |
| **mid-price** `m=(a+b)/2` | Arithmetic center of best bid and ask; the book's main high-frequency reference price. | AMMs may have a marginal reserve price or external mark instead. Record the price definition with every study. |
| **transaction price** `p_t` | Price of an actual executed trade. | Must come from exact landed asset effects and venue state, not a chart mark or intended swap. |
| **fundamental price/value** `p_F` | Model-dependent latent value, often assumed to be revealed eventually. | There is no safe near-term fundamental-value oracle for memecoins. Treat as a model variable, never a stored fact. |
| **mark** | Current contextual price used for comparison or valuation. | Never multiply a marginal mark by a bag and call it executable liquidation. |
| **quote** | Conditional executable terms for a size, route, state, and time. | Preserve expected output, bounds, exact state/slot, fees, latency, route, and expiry. |
| **fill** | Actual execution result. | Finalized controlled-wallet asset effects outrank decoded event summaries. |
| **tick size** `ϑ` | Minimum allowed LOB price increment. | Pump curves have discrete atomic arithmetic but no exchange tick queue; Meteora bin step is analogous only in limited ways. |
| **relative tick size** `ϑ_r` | Tick size relative to a price/volatility scale; the book's main large-/small-tick regime separator. | Do not substitute token decimals, lamports, or DLMM bin step without defining the economic scale. |

## Orders, queues, and liquidity

| term | distilled meaning | JOSHI boundary |
| --- | --- | --- |
| **limit order** | Standing willingness to trade no worse than a stated price, usually with queue priority. | Not the same as AMM liquidity or an unsigned future swap plan. |
| **market order** | Order demanding immediate execution against available standing liquidity. | A swap is economically aggressive, but its routing, slippage bound, landing delay, and atomic transaction semantics differ. |
| **cancellation** | Removal of a standing limit order. | AMM liquidity removal/rebalance changes inventory and curve depth; it is not an LOB cancellation event. |
| **order queue** `V(p,t)` | Aggregate standing volume at one price and side. | Pump/PumpSwap reserve state has no FIFO queue. A DLMM bin is closer to a price bucket but LP shares are not queue priority. |
| **best-queue depletion** | Best bid or ask volume reaches zero, allowing the quoted price to move. | AMM price moves continuously/discretely with reserve/bin traversal rather than waiting for best-queue exhaustion. |
| **queue imbalance** `I=V_b/(V_a+V_b)` | Relative best-bid depth; predictive of the next one-tick move in large-tick LOBs. | No direct AMM equivalent. Candidate analogues must be newly defined from two-sided executable depth or wallet flow. |
| **queue position / priority** | Location in the execution order for limit orders at one price. | Crucial for LOB market making; generally absent from pro-rata AMM LP accounting. |
| **revealed liquidity** | Visible executable volume currently displayed in the book. | Exact reserve/bin state can be public but still omits future LP edits, routes, competing transactions, and social flow. |
| **latent liquidity** | Unexpressed or slowly revealed buy/sell intentions not present in the visible book. | Wallet holdings, intentions, off-chain attention, creator plans, and undeployed capital are latent but not directly observable. |
| **marginal supply/demand (MSD)** | Density of latent intentions as a function of price relative to the current price. | A modeling object, not equivalent to current AMM reserves. |
| **liquidity provider** | Participant offering execution and earning spread/rebates while bearing impact, adverse selection, and inventory risk. | Meteora LPs earn fees and bear inventory conversion/selection risk, but mechanics are protocol/bin-specific. |
| **liquidity taker** | Participant demanding immediacy and paying spread/impact. | Swap user is the nearest AMM analogue. |
| **large-tick / small-tick** | LOB regimes where the enforced tick is large/small relative to the natural price scale. | Must not be mapped to high-/low-liquidity memecoins without a measured analogue. |

## Time, events, and dependence

| term | distilled meaning | JOSHI boundary |
| --- | --- | --- |
| **calendar time** | Physical elapsed time between events. | Preserve source, receive, render, gesture, send, landing, and finality clocks separately. |
| **event time** | Index that advances once per selected market event, ignoring irregular wall-time gaps. | Define the event universe and coverage; trade time, pool-state time, social time, and block/slot time differ. |
| **point process** `N(t)` | Random event-counting process with conditional intensity. | Useful for launches, trades, callouts, replies, creator events, and operator acts if missingness is explicit. |
| **intensity** `ϕ(t)` | Conditional instantaneous event rate given the history. | A model-derived quantity with availability and estimator version, not a source fact. |
| **Hawkes process** | Point process whose intensity includes decaying contributions from earlier events. | A descriptive candidate for clustering; a fitted kernel does not prove social or trade contagion. |
| **branching/feedback ratio** `g` | Integral of a linear Hawkes kernel; stationarity requires `g<1` in the model. | Near-one fits can reflect misspecification, nonstationarity, seasonality, selection, or true feedback. |
| **autocorrelation** `C(ℓ)` | Normalized dependence between a series and its lagged values. | Compute only on explicit eligible intervals; gaps and adaptive hot-scope promotion can create spurious persistence. |
| **long memory** | Autocorrelation decays so slowly that its sum/integral diverges, often `C(ℓ)∼ℓ^{-γ}` with `0<γ<1`. | Estimate across lifecycle/regime and with coverage controls; do not assume one stationary exponent. |
| **self-excitation** | Past events raise current event intensity in a model. | Correlation is not causal excitation; shared news, ranking, or sampling can cause the same pattern. |
| **endogeneity** | Market activity generated by feedback within the system rather than an external information stream. | The boundary between endogenous and exogenous depends on which social/platform/chain events JOSHI observes. |

## Price dynamics and impact

| term | distilled meaning | JOSHI boundary |
| --- | --- | --- |
| **return** | Price increment, often normalized by a reference price. | Define venue, price object, clocks, and treatment of migration/routing discontinuities. |
| **variogram** `V(τ)` | Expected squared price change over lag `τ`. | Compute separately for marks, pool marginal prices, and actual executable quote surfaces. |
| **volatility signature plot** | Volatility estimate as a function of sampling lag; slope reveals trend/mean-reversion/noise. | Useful for venue/state diagnostics, not automatically for profitable entry timing. |
| **observed impact** | Conditional subsequent price move after a trade. | Directly estimable but mixes trade reaction, selection, information, and common causes. |
| **reaction impact** | Difference between worlds with and without the focal trade under the same pre-trade state. | Fundamentally counterfactual; cannot be read off replay or historical insertion. |
| **prediction impact** | Price move that would have occurred from the trader's pre-trade information even without the trade. | Usually unobserved; do not set to zero to credit a strategy or simulator. |
| **response function** `R(ℓ)` | Expected signed price change after a signed trade at lag `ℓ`. | Define sign and price for each venue. Pool direction and quote-side choice are not interchangeable. |
| **propagator** `G(ℓ)` | Kernel assigning lag-dependent reaction impact to a past signed event. | Reduced-form candidate, not a protocol formula or causal law. |
| **resilience** | Decay/refill that offsets persistent same-direction flow. | In AMMs it may arise from arbitrage, LP changes, route competition, or opposite flow rather than book refill. |
| **asymmetric liquidity** | Expected same-direction events have less marginal impact; surprising/reversing events have more. | High-value hypothesis for signed-flow conditioning, but it needs an AMM-specific state definition. |
| **Kyle's lambda** `Λ` | Local slope relating signed volume imbalance to price response in a linear impact model. | A scale-dependent descriptive slope, not a universal liquidity constant. |
| **square-root impact law** | Metaorder peak impact scales approximately with volatility times square root of participation. | Evidence is broad in mature markets, but token lifecycle, AMM mechanics, manipulation, and routing may change it radically. |
| **impact decay** | Post-execution relaxation of a trade/metaorder's observed price effect. | Must distinguish true resilience, market regime changes, selection, and exit of social attention. |
| **price manipulation** | Expected profit from a closed uninformed trading loop generated solely by a flawed impact rule. | A valid live simulator must not manufacture profitable round trips by omitting fees, reaction, or state competition. |

## Execution, accounting, and strategy

| term | distilled meaning | JOSHI boundary |
| --- | --- | --- |
| **metaorder** | A larger parent intention executed through many child orders over time. | A discretionary episode may contain entries, exits, flat intervals, and re-entry; it is not necessarily one metaorder. |
| **child order** | One execution slice belonging to a parent metaorder. | Link only prospectively or from reliable wallet/intent evidence; do not infer parentage from outcome. |
| **participation rate** | Metaorder volume divided by contemporaneous market volume over its horizon. | Denominator must include exact venue/universe and coverage; tiny tokens can make it unstable. |
| **implementation shortfall** | Difference between execution outcome and a declared pre-trade reference, including impact and other costs. | Keep mark, expected quote, minimum output, actual fill, network fees, tips, and residual exposure separate. |
| **TWAP / VWAP** | Time-/volume-weighted execution benchmarks. | A benchmark can be endogenous to the focal flow and hide impact; record attainability. |
| **adverse selection** | Liquidity provider is executed more often when the next move is unfavorable. | For LPs, measure fee income against inventory conversion and executable post-withdrawal value. |
| **inventory risk** | Exposure accumulated while providing liquidity or executing incompletely. | Includes runner holdings, LP contingent token schedules, SOL opportunity cost, and correlated tail states. |
| **break-even condition** | Expected provider gains from spread/fees equal selection, impact, inventory, and operating costs. | Must use landed flows and full liquidation paths, not accrued fees or marks alone. |
| **runner** | JOSHI term: residual position retained after partial realization/cash recovery. | Not a source-book term; preserve quantity, remaining basis quality, liquidation value, and active episode status. |
| **operator episode** | JOSHI term: continuity of attention and intent across trades and flat intervals. | Distinct from an inventory epoch and from a source-book metaorder. |
| **inventory epoch** | JOSHI term: flat-to-flat accounting interval. | Re-entry after exact flat starts new basis even when the operator episode continues. |

## Epistemic categories

| term | meaning in this corpus |
| --- | --- |
| **identity/definition** | True by notation or construction, not an empirical discovery. |
| **model assumption** | Premise imposed to make a model tractable. |
| **model result** | Consequence of stated assumptions; may be exact within the model. |
| **empirical regularity** | Pattern observed in a specified sample or literature reviewed by the book. |
| **author interpretation** | Proposed mechanism or conceptual reading of evidence. |
| **JOSHI hypothesis** | Transfer candidate requiring prospective measurement in the actual venue/process. |

