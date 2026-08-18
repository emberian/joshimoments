# Book map

## Reading route

The book builds a layered argument rather than one unified theorem:

```text
market institutions and price statistics
  -> visible LOB mechanics and empirical regularities
  -> stochastic queues and event clustering
  -> persistent signed order flow
  -> observed impact and metaorder impact
  -> propagator and adverse-selection models
  -> latent supply/demand and nonlinear impact
  -> execution, stability, and valuation consequences
```

For JOSHI, the shortest high-value route is Chapters 1–4 for measurement discipline; Chapters
9–14 for intensity, flow, and impact; Chapters 16–17 for liquidity-provider economics; Chapters
18–21 for latent liquidity, nonlinear impact, and execution; and Chapter 22 for impact-adjusted
valuation and feedback. Chapters 5–8 supply useful queue/state-process methods but rely most heavily
on LOB-specific mechanics.

## Parts and chapter spans

Ranges below use printed pages. A range ending before the next chapter includes its further-reading
section; part introductions occupy some intervening pages.

| part | printed pages | role |
| --- | ---: | --- |
| Preface | xiii–xvi | empirical, bottom-up aim; source data boundary |
| I. How and Why Do Prices Move? | 1–41 | institutions, ecology, random walks, heavy tails, endogeneity |
| II. Limit Order Books: Introduction | 42–74 | mechanics and empirical LOB state |
| III. Limit Order Books: Models | 75–158 | single/joint queues and the Santa Fe null model |
| IV. Clustering and Correlations | 159–204 | Hawkes activity and persistent signed flow |
| V. Price Impact | 205–244 | single-order and metaorder impact evidence |
| VI. Market Dynamics at the Micro-Scale | 245–286 | transient and history-dependent propagators |
| VII. Adverse Selection and Liquidity Provision | 287–332 | Kyle, spread formation, and market-making P&L |
| VIII. Market Dynamics at the Meso-Scale | 333–380 | latent liquidity and nonlinear impact dynamics |
| IX. Practical Consequences | 381–421 | execution, stability, feedback, and valuation |
| Appendix | 422–440 | data, transforms, propagator fits, alternate market-making derivation, symbols |
| Index | 441–444 | source index |

## Chapter and section map

### Part I — institutions and price statistics

#### Chapter 1 — The Ecology of Financial Markets (pp. 5–21)

- 1.1 The Rules of Trading — p. 6
- 1.2 The Ecology of Financial Markets — p. 10
- 1.3 The Risks of Market-Making — p. 14
- 1.4 The Liquidity Game — p. 18
- 1.5 Further Reading — p. 20

Role: establishes auction, dealer, and continuous-double-auction institutions; distinguishes
liquidity taking/provision; introduces adverse selection, impact, inventory skew, and competition.

#### Chapter 2 — The Statistics of Price Changes: An Informal Primer (pp. 22–41)

- 2.1 The Random Walk Model — p. 23
- 2.2 Jumps and Intermittency in Financial Markets — p. 28
- 2.3 Why Do Prices Move? — p. 33
- 2.4 Summary and Outlook — p. 36
- 2.5 Further Reading — p. 37

Role: defines variograms, autocorrelation, signature plots, fat tails, clustered volatility, excess
volatility, statistical efficiency, and the endogenous-price thesis.

### Part II — visible order-book mechanics

#### Chapter 3 — Limit Order Books (pp. 44–57)

- 3.1 The Mechanics of LOB Trading — p. 44
- 3.2 Practical Considerations — p. 52
- 3.3 Further Reading — p. 57

Role: defines order queues, bid/ask/mid, spread, relative prices, priority, order types, and price
changes caused by best-queue depletion.

#### Chapter 4 — Empirical Properties of Limit Order Books (pp. 58–74)

- 4.1 Summary Statistics — p. 59
- 4.2 Intra-day Patterns — p. 59
- 4.3 The Spread Distribution — p. 62
- 4.4 Order Arrivals and Cancellations — p. 63
- 4.5 Order Size Distributions — p. 66
- 4.6 Volume at the Best Quotes — p. 66
- 4.7 Volume Profiles — p. 68
- 4.8 Tick-Size Effects — p. 69
- 4.9 Conclusion — p. 71
- 4.10 Further Reading — p. 73

Role: supplies the main NASDAQ descriptive evidence and shows that relative tick size separates
qualitatively different queue/liquidity regimes. See Table 4.1 and Figures 4.1–4.12.

### Part III — stochastic LOB models

#### Chapter 5 — Single-Queue Dynamics: Simple Models (pp. 78–100)

- 5.1 The Case for Stochastic Models — p. 79
- 5.2 Modelling an Order Queue — p. 80
- 5.3 The Simplest Model: Constant Cancellation Rate — p. 80
- 5.4 A More Complex Model: Linear Cancellation Rate — p. 89
- 5.5 Conclusion — p. 98
- 5.6 Further Reading — p. 99

Role: birth–death queues, master equations, first-hitting times, stationary regimes, Fokker–Planck
limits, Q-CIR dynamics, and rare depletion.

#### Chapter 6 — Single-Queue Dynamics for Large-Tick Stocks (pp. 101–116)

- 6.1 Price-Changing Events — p. 102
- 6.2 The Fokker–Planck Equation — p. 104
- 6.3 Sweeping Market Orders — p. 107
- 6.4 Analysing Empirical Data — p. 110
- 6.5 Conclusion — p. 115
- 6.6 Further Reading — p. 116

Role: calibrates queue drift/diffusion from event-resolved data, includes price-changing jumps, and
tests scale-invariant rescaled queue dynamics.

#### Chapter 7 — Joint-Queue Dynamics for Large-Tick Stocks (pp. 117–133)

- 7.1 The Race to the Bottom — p. 118
- 7.2 Empirical Results — p. 119
- 7.3 Independent Queues — p. 120
- 7.4 The Coupled Dynamics of the Best Queues — p. 127
- 7.5 What Happens After a Race Ends? — p. 130
- 7.6 Conclusion — p. 131
- 7.7 Further Reading — p. 132

Role: connects bid/ask queue imbalance to the direction of the next price change and demonstrates
why naïve independent diffusions miss the empirical functional shape.

#### Chapter 8 — The Santa Fe Model for Limit Order Books (pp. 134–158)

- 8.1 The Challenges of Modelling LOBs — p. 135
- 8.2 The Santa Fe Model — p. 136
- 8.3 Basic Intuitions — p. 137
- 8.4 Parameter Estimation — p. 139
- 8.5 Model Simulations — p. 141
- 8.6 Some Analytical Results — p. 148
- 8.7 The Continuum, Diffusive-Price Limit — p. 152
- 8.8 Conclusion: Weaknesses of the Santa Fe Model — p. 154
- 8.9 Further Reading — p. 156

Role: a zero-intelligence null model that respects LOB mechanics, reproduces some macro facts, and
fails on state dependence, clustered/correlated flow, and strategic liquidity response.

### Part IV — event clustering and persistent flow

#### Chapter 9 — Time Clustering and Hawkes Processes (pp. 163–186)

- 9.1 Point Processes — p. 164
- 9.2 Hawkes Processes — p. 166
- 9.3 Empirical Calibration of Hawkes Processes — p. 173
- 9.4 From Hawkes Processes to Price Statistics — p. 179
- 9.5 Generalised Hawkes Processes — p. 181
- 9.6 Conclusion and Open Issues — p. 183
- 9.7 Further Reading — p. 185

Role: models wall-time event intensity, self-excitation, branching/feedback, criticality, estimation,
and the correlation-versus-causality trap.

#### Chapter 10 — Long-Range Persistence of Order Flow (pp. 187–204)

- 10.1 Empirical Evidence — p. 188
- 10.2 Order Size and Aggressiveness — p. 189
- 10.3 Order-Sign Imbalance — p. 191
- 10.4 Mathematical Models for Persistent Order Flows — p. 193
- 10.5 Liquidity Rationing and Order-Splitting — p. 198
- 10.6 Conclusion — p. 201
- 10.7 Further Reading — p. 203

Role: establishes long-memory signed flow, contrasts herding with metaorder splitting, and poses the
efficiency paradox: predictable flow alongside nearly unpredictable returns.

### Part V — measured impact

#### Chapter 11 — The Impact of Market Orders (pp. 208–228)

- 11.1 What Is Price Impact? — p. 208
- 11.2 Observed Impact, Reaction Impact and Prediction Impact — p. 210
- 11.3 The Lag-1 Impact of Market Orders — p. 212
- 11.4 Order-Flow Imbalance and Aggregate Impact — p. 222
- 11.5 Conclusion — p. 224
- 11.6 Further Reading — p. 226

Role: gives the book's crucial causal distinction, measures response by size and conditioning, and
relates spread, impact, selective liquidity taking, signed imbalance, and scale.

#### Chapter 12 — The Impact of Metaorders (pp. 229–244)

- 12.1 Metaorders and Child Orders — p. 230
- 12.2 Measuring the Impact of a Metaorder — p. 230
- 12.3 The Square-Root Law — p. 233
- 12.4 Impact Decay — p. 240
- 12.5 Impact Path and Slippage Costs — p. 240
- 12.6 Conclusion — p. 241
- 12.7 Further Reading — p. 243

Role: states and stress-tests the square-root metaorder impact law, impact path/decay, participation
and horizon effects, measurement biases, and execution shortfall.

### Part VI — reduced-form micro-dynamics

#### Chapter 13 — The Propagator Model (pp. 249–269)

- 13.1 A Simple Propagator Model — p. 249
- 13.2 A Model of Transient Impact and Long-Range Resilience — p. 251
- 13.3 History-Dependent Impact Models — p. 259
- 13.4 More on the Propagator Model — p. 261
- 13.5 Conclusion — p. 267
- 13.6 Further Reading — p. 268

Role: couples persistent trade signs to decaying impact and explains how predictable order flow can
coexist with diffusive prices.

#### Chapter 14 — Generalised Propagator Models (pp. 270–286)

- 14.1 Price Micro-Mechanics — p. 270
- 14.2 Limitations of the Propagator Model — p. 270
- 14.3 Two Types of Market Orders — p. 272
- 14.4 A Six-Event Propagator Model — p. 275
- 14.5 Other Generalisations — p. 282
- 14.6 Conclusion — p. 284
- 14.7 Further Reading — p. 286

Role: distinguishes price-changing/non-changing market orders, adds limit/cancel events, and
contrasts transient kernels with history-dependent liquidity.

### Part VII — adverse selection and liquidity provision

#### Chapter 15 — The Kyle Model (pp. 290–297)

- 15.1 Model Set-Up — p. 290
- 15.2 Linear Impact — p. 292
- 15.3 Discussion — p. 293
- 15.4 Some Extensions — p. 294
- 15.5 Conclusion — p. 295
- 15.6 Further Reading — p. 297

Role: stylised informed trader, noise flow, competitive market maker, and linear permanent impact;
valuable intuition with important empirical failures.

#### Chapter 16 — The Determinants of the Bid–Ask Spread (pp. 298–318)

- 16.1 The Market-Maker's Problem — p. 299
- 16.2 The MRR Model — p. 308
- 16.3 Empirical Analysis of the MRR Model — p. 312
- 16.4 Conclusion — p. 315
- 16.5 Further Reading — p. 317

Role: Glosten–Milgrom break-even spreads, liquidity breakdown, fair pricing, MRR martingale
dynamics, and empirical spread/response/volatility relations.

#### Chapter 17 — The Profitability of Market-Making (pp. 319–332)

- 17.1 An Infinitesimal Market-Maker — p. 321
- 17.2 Inventory Control for Small-Tick Stocks — p. 323
- 17.3 Large-Tick Stocks — p. 327
- 17.4 Conclusion — p. 329
- 17.5 Further Reading — p. 331

Role: decomposes spread gain, response/adverse selection, inventory control, queue priority, and
rebates; shows simple market-making is near break-even or negative.

### Part VIII — latent liquidity and nonlinear impact

#### Chapter 18 — Latent Liquidity and Walrasian Auctions (pp. 337–353)

- 18.1 More than Meets the Eye — p. 337
- 18.2 A Dynamic Theory for Supply and Demand Curves — p. 338
- 18.3 Infrequent Auctions — p. 343
- 18.4 Frequent Auctions — p. 345
- 18.5 From Linear to Square-Root Impact — p. 348
- 18.6 Conclusion — p. 350
- 18.7 Further Reading — p. 353

Role: treats intentions as diffusing/cancelling/replenishing latent supply/demand and derives
V-shaped marginal liquidity near frequently cleared prices.

#### Chapter 19 — Impact Dynamics in a Continuous-Time Double Auction (pp. 354–365)

- 19.1 A Reaction–Diffusion Model — p. 354
- 19.2 A Metaorder in an Equilibrated Market — p. 356
- 19.3 Square-Root Impact of Metaorders — p. 358
- 19.4 Impact Decay — p. 359
- 19.5 Absence of Price Manipulation — p. 361
- 19.6 Conclusion and Open Problems — p. 362
- 19.7 Further Reading — p. 364

Role: gives a nonlinear latent-order-book impact equation, square-root regimes, decay/reversal
paths, and a non-negative closed-loop impact cost.

#### Chapter 20 — The Information Content of Prices (pp. 366–380)

- 20.1 The Efficient-Market View — p. 366
- 20.2 Order-Driven Prices — p. 368
- 20.3 A Self-Referential Model for Prices — p. 372
- 20.4 Conclusion — p. 375
- 20.5 Further Reading — p. 376

Role: contrasts price discovery with order-driven price formation and models self-referential
forecasting/error correction.

### Part IX — practice and systemic consequences

#### Chapter 21 — Optimal Execution (pp. 384–405)

- 21.1 The Many Facets of Optimal Execution — p. 385
- 21.2 The Optimal Scheduling Problem — p. 386
- 21.3 Market Orders or Limit Orders? — p. 394
- 21.4 Should I Stay or Should I Go? — p. 397
- 21.5 Conclusion — p. 402
- 21.6 Further Reading — p. 403

Role: separates macro/meso/micro execution, balances signal horizon against impact and risk, and
warns that historical insertion of phantom trades omits market reaction.

#### Chapter 22 — Market Fairness and Stability (pp. 406–421)

- 22.1 Volatility, Feedback Loops and Instabilities — p. 409
- 22.2 A Short Review of Micro-Regulatory Tools — p. 412
- 22.3 Conclusion: In Prices We Trust? — p. 418
- 22.4 Further Reading — p. 419

Role: feedback loops, correlated liquidity withdrawal, regulation, manipulation, impact-adjusted
valuation, and the fragility of instantaneous marks.

### Appendix (pp. 422–440)

- A.1 Description of the NASDAQ Data — p. 422
- A.2 Laplace Transforms and CLT — p. 423
- A.3 A Propagator Model with Volume Fluctuations — p. 428
- A.4 TIM and HDIM — p. 430
- A.5 An Alternative Market-Making Strategy — p. 432
- A.6 Acronyms, Conventions and Symbols — p. 434

The NASDAQ data description is necessary when interpreting Chapters 3–17: four focal stocks use
2015 NASDAQ data during a restricted intraday window, with a broader 120-stock sample for some
cross-sectional results. Appendix formula transcriptions should be taken from the render, not the
text extraction.

