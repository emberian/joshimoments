# Trading and market-microstructure reading guide

Status: suggested sequence for this project, checked 2026-08-16.

## If reading one book first

Read Larry Harris, [*Trading and Exchanges: Market Microstructure for
Practitioners*](https://academic.oup.com/book/52292) (Oxford University Press, 2002).

It is old enough that its venue examples predate current crypto infrastructure, but it remains the
best first map of who trades, why they trade, order types, liquidity, spreads, informed versus
uninformed flow, dealers, brokers, and the difference between a good idea and good execution. Those
concepts transfer; the mechanics of Pump bonding curves and AMMs must be learned separately.

For Joshi, prioritize the parts on:

- why people trade and the resulting order-flow ecology;
- market/limit order economics, spread and price impact;
- informed trading, adverse selection, liquidity suppliers, and parasitic strategies;
- execution quality and transaction costs;
- market design and trading rules.

Do not read it as a recipe book for memecoin entries. Read it as the vocabulary needed to stop
confusing a mark, quote, order, fill, inventory risk, information advantage, and liquidity service.

## Best fit for Ember's signals/physics intuition

Jean-Philippe Bouchaud, Julius Bonart, Jonathan Donier, and Martin Gould,
[*Trades, Quotes and Prices: Financial Markets Under the
Microscope*](https://www.cambridge.org/core/books/trades-quotes-and-prices/029A71078EE4C41C0D5D4574211AB1B5)
(Cambridge University Press, 2018).

This is the book I expect Ember to enjoy more. It treats empirical order flow, price impact,
micro/mesoscale dynamics, adverse selection, liquidity provision, and market-making profitability
with the style of statistical physics. Its primary venue model is a limit-order book rather than an
AMM, so the objects do not transfer literally. The questions—how correlated flow, hidden liquidity,
impact, strategic response, and adverse selection produce apparent patterns—transfer extremely
well.

Suggested parts after Harris:

- empirical properties of order books and price impact;
- correlations and clustering;
- market dynamics at micro and meso scales;
- adverse selection and liquidity provision;
- practical consequences for execution.

## Formal execution reference

Álvaro Cartea, Sebastian Jaimungal, and José Penalva,
[*Algorithmic and High-Frequency
Trading*](https://www.cambridge.org/us/search?currentTheme=Academic_v1&page=1&query=algorithmic+finance&searchSubmitProducts=Academic&site=&tab=related)
(Cambridge University Press, 2015).

Use this after the first two, selectively. It is valuable for electronic-market mechanics,
inventory-aware market making, stochastic control, optimal execution, and how latency/impact enter
a policy. It is not the right first book and its limit-order-book/HFT models should not be pasted
onto thin Pump curves or DLMM bins.

## AMM bridge

There is no single textbook that joins Pump-style launches, memecoin social dynamics, concentrated
liquidity, and operator-centered trading. Use a short paper/protocol bridge:

1. Angeris, Agrawal, Evans, Chitra, and Boyd,
   [“Constant Function Market Makers: Multi-Asset Trades via Convex
   Optimization”](https://arxiv.org/abs/2107.12484) for the general reserve/trading-function view.
2. Angeris, Chitra, Evans, and Boyd,
   [“Optimal Routing for Constant Function Market Makers”](https://arxiv.org/abs/2204.05238) for
   routing, fixed costs, and arbitrage structure.
3. Milionis, Moallemi, Roughgarden, and Zhang,
   [“Automated Market Making and Loss-Versus-Rebalancing”](https://arxiv.org/abs/2208.06046) for the
   LP adverse-selection cost that fee income alone hides.
4. Current [Pump public program documentation](https://github.com/pump-fun/pump-public-docs) and
   [Meteora documentation](https://docs.meteora.ag/) for the actual state accounts, fees, lifecycle,
   quotes, bins, and operations the system must model now.

Protocol docs define mechanics, not economics. The academic AMM models define useful baselines,
not a guarantee that their assumptions fit a reflexive, socially driven, shallow coin.

## Project-directed study loop

Reading should attach to cockpit questions rather than delay instrumentation:

- When a spread/impact/adverse-selection concept appears, identify its Pump/PumpSwap/DLMM analogue.
- Record which state would be required to measure it exactly.
- Create an operator-facing example from a real prospective episode.
- Mark where the theory assumes an order book, external reference price, continuous liquidity,
  price-taking, stationary volatility, or rational actors that the market may violate.
- Turn only the surviving distinction into a candidate scene field, counterfactual, or hypothesis.

This makes the reading program another sensor-design loop rather than another source of premature
strategy rules.
