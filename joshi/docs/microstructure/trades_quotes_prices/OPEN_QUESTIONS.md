# Open questions and follow-up lanes

## Reading uncertainties

This is a rigorous first pass, not a proof-checked reconstruction of every derivation. The following
areas require source-page rereading before implementation:

1. exact normalization choices in Hawkes covariance/kernel inversion [pp. 168–182];
2. finite-sample behavior of the propagator inversion and TIM/HDIM fitting [pp. 253–260,
   275–285; Appendix A.3–A.4];
3. metaorder selection-bias arguments and the conditions behind partial-path scaling
   [pp. 233–242];
4. fair-pricing/permanent-impact derivation [pp. 302–308];
5. market-making P&L approximations and alternate Appendix A.5 derivation [pp. 321–330,
   432–434];
6. boundary assumptions in the latent-liquidity integral equation [pp. 338–362]; and
7. price-manipulation proof and admissible execution functions [pp. 361–362].

## Extraction defects requiring rendered pages

The prose layer is reliable enough for search. These equation groups are not safe to transcribe
from text alone:

| printed pages | affected items | observed extraction problem |
| ---: | --- | --- |
| 85 | Eqs. 5.14–5.20 | transform hats, primes, square-root bar, and delimiters |
| 94–95, 105 | Eqs. 5.45–5.46, 6.5–6.8 | probability glyphs, sums, and small-versus-much-less signs |
| 169–171 | Eqs. 9.15–9.22 | Laplace-transform hats and kernel symbols |
| 193–197 | Eqs. 10.4–10.11 | lag glyphs, conditional distributions, integral/sum layout |
| 211 | Eqs. 11.1–11.4 | superscript labels and counterfactual conditioning alignment |
| 234, 240–241 | Eqs. 12.6, 12.10–12.11 | approximate sign, exponent brackets, nested cumulative quantity |
| 252–256 | Eqs. 13.7–13.17 | lag symbols, script response/variogram, sums |
| 275–285 | multi-event TIM/HDIM equations | event-type subscripts and kernel matrices |
| 307–311 | Eqs. 16.11–16.23 | script impact symbols, hats, infinity subscripts |
| 323–326 | Eqs. 17.4–17.12 | position symbols, nested expectations/sums, approximation status |
| 345–350 | Eqs. 18.11–18.18 | integration variables, square roots, latent-density superscripts |
| 357–362 | Eqs. 19.5–19.12 | heat-kernel exponent and nonlinear self-consistent price |
| 388–400 | Eqs. 21.5–21.23 | delta functions, integrals, expected-gain symbols |
| 423–434 | Appendix A.2–A.5 | transforms, matrices, hats, primes, calligraphic symbols |

Any code or machine-readable formula registry should be sourced from a fresh render check, a second
human/agent transcription, dimensional checks, and source-book test cases.

## Formal questions

1. What is the minimal common state space across bonding curves, constant-product pools, DLMM bins,
   routed quotes, and external LOBs without reducing every venue to vague `liquidity`?
2. Which price object should each response target: pool marginal, last fill, external composite,
   intended-size liquidation, or a vector of them?
3. Can observed response be decomposed into deterministic protocol curve movement plus adaptive
   market response without claiming the remainder is causal reaction?
4. What is the correct sign for multi-asset/routed transactions, partial fills, LP operations, and
   bundled instructions?
5. What defines a parent flow when wallets split across routers, accounts, mints, and venues?
6. How should migration create a new regime while retaining one episode and asset identity history?
7. What simulator invariants replace the LOB no-manipulation property after protocol fees,
   external arbitrage, and stochastic landing?
8. Can a state-dependent propagator be parameterized sparsely enough to remain identifiable in a
   rapidly changing small-token market?
9. Which variables are genuinely dimensionless and comparable across tokens: reserve fraction,
   participation, volatility-scaled size, price displacement, or something lifecycle-specific?

## Evidence questions

1. Is the selected acquisition path complete enough to measure market-wide signed flow, or only hot
   promoted mints?
2. How much left truncation occurs between launch/board appearance and hot-scope activation?
3. Can route and participant attribution distinguish user action, aggregator, arbitrageur,
   protocol account, and multi-wallet controller?
4. Are buy/sell events reconstructed from authoritative instructions/account effects or provider
   labels?
5. Which pool state is available at decision, quote, send, leader execution, and finality?
6. Can full-size quote surfaces be regenerated for historical states, including fee/token-program
   profiles?
7. Which social events have reliable occurrence *and availability* times?
8. How do provider gaps correlate with high-intensity periods and extreme price moves?
9. Can failed transactions and unlanded attempts be observed well enough to estimate selection and
   cost, rather than only successful fills?
10. How will hard deletion of social/screenshot evidence propagate through hashes, backups,
    derived features, and model prompts?

## Empirical questions

1. Does trade-sign persistence survive stratification by lifecycle, venue, token liquidity, and
   wallet/route cluster?
2. Is persistence mainly repeated actors, market-wide common shocks, platform ranking, or broad
   herding?
3. What is the observed response surface after subtracting deterministic instantaneous curve
   movement?
4. Does expected flow face smaller incremental response than surprising flow, as asymmetric
   liquidity suggests?
5. Are there reproducible impact-decay shapes after large wallet flows, and how often does route
   loss/collapse censor them?
6. Does any square-root-like normalization survive across Pump curve, migrated PumpSwap pools, and
   Meteora? What competing forms fit better?
7. How stable are point-process kernels across launch, early bonding, migration, trend, and decay
   regimes?
8. Do social/creator events improve held-out intensity/response forecasts beyond price and platform
   state?
9. Do liquidity providers withdraw or narrow ranges together after shared volatility/activity
   triggers?
10. How large is the mark-to-full-liquidation gap for actual runners and LP states across time?

## Operator-process questions

1. Which of Ember's 3–8 dispositions alter entry scale, acceptable delay, partial-exit rule,
   runner size, or re-entry willingness?
2. Which 2–5 “crackle” types correspond to different state/flow patterns rather than different
   retrospective stories?
3. Can a low-friction act capture intent before execution without forcing a premature taxonomy?
4. When Ember overrides a planned exit, what visible evidence changed and was it already in the
   scene?
5. Is the decision to remain flat and watch itself predictable/useful?
6. How should competing SOL opportunities enter a management counterfactual?
7. Does impact-adjusted exposure change actual behavior, or merely make the tool feel rigorous?
8. Can post-episode interviews recover distinctions without leaking outcome into the original
   action label?

## LP questions

1. What exact operations does each live Meteora position permit: add, remove, claim, shift range,
   or close/reopen?
2. Which operations can occur in place and which require a new position or explicit swap?
3. How do dynamic fees and active-bin movement alter fee income and selection?
4. What is the exact token inventory at current, lower-edge, upper-edge, partial-withdrawal, and
   full-withdrawal states?
5. Does rebalancing reduce unwanted SOL conversion enough to overcome fees, landing risk, and
   opportunity cost?
6. What fraction of LP P&L comes from fees versus underlying token exposure and endogenous
   inventory conversion?
7. Are observed profitable intervals survivor-selected because failed/abandoned positions or
   unrouteable residuals disappear?

## Social and fancoin questions

1. Which observable event is the start of a creator/community transition: launch, first post,
   public claim, fee routing, stream, response, or something else?
2. Can creator awareness, participation, endorsement, and permissionless fee collection remain
   separate predicates?
3. How does platform ranking mediate audience arrival, and can its choice set be observed lawfully
   and faithfully?
4. Which actor graph is stable enough for analysis: wallet, Pump profile, X account, social-fee
   recipient, or temporal evidence edges among them?
5. Does a fitted excitation effect survive platform-wide bursts and future-shift negative controls?
6. Are fancoin families identifiable prospectively without using later success, current metadata,
   or community narrative?

## Follow-up study lanes

### Lane B1 — equation and notation audit

**Deliverable.** A small machine-readable registry for only Eqs. 2.1, 5.1–5.2, 6.8, 9.10–9.13,
10.2, 11.1–11.4, 12.6, 13.7–13.17, 16.18–16.23, 18.4, 19.7–19.9, and 21.5, with dimensions,
assumptions, rendered crops, and independent transcription checks.

**Stop condition.** Do not expand into a full formalization language. Preserve citations and tests.

### Lane B2 — venue-native price/impact semantics

**Deliverable.** A formal comparison of Pump curve, PumpSwap, and Meteora state transitions defining
mark, marginal price, directional size quote, fill, subsequent response, and liquidation.

**Stop condition.** If a field cannot be reconstructed from authoritative evidence, label it
unsupported rather than using a provider mark.

### Lane B3 — signed-flow and activity baseline

**Deliverable.** One frozen prospective dataset with coverage controls, Poisson/seasonal baseline,
sign ACF, participant clustering, and held-out forecasts across lifecycle strata.

**Stop condition.** If hot-scope selection prevents a valid denominator, restrict claims to scoped
mint management and preserve the coverage study.

### Lane B4 — AMM observed-response atlas

**Deliverable.** State/size/lifecycle-conditioned observed response surfaces with exact protocol
curve contribution shown separately.

**Stop condition.** If post-event price objects or state clocks cannot be aligned within the
economic hurdle, preserve the exact quote/fill calibration and abandon response policy claims.

### Lane B5 — social intensity and transition study

**Deliverable.** A source-reviewed multivariate event inventory, seasonal/common-cause baselines,
negative controls, and held-out intensity results.

**Stop condition.** If source access, availability time, or privacy prevents honest covariates,
retain manual scene evidence and do not infer community contagion.

### Lane B6 — LP provider-economics docket

**Deliverable.** Prospective per-position fee/selection/inventory/rebalance/liquidation accounting
with no-change and declared-edit comparisons.

**Stop condition.** If exact per-bin state/operations cannot be reconstructed, ship exposure truth
and stop policy analysis.

### Lane B7 — composite management episodes

**Deliverable.** A small corpus of prospective crackle, runner, full-exit, flat-watch, and re-entry
episodes with witnessed scenes and attainable counterfactuals.

**Stop condition.** If annotations become clerical or retrospective, keep the episode notebook and
drop strategy-learning claims.

### Lane B8 — microstructure textbook comparison

**Deliverable.** Compare this 2018 synthesis with current primary research on AMM execution, Solana
MEV, concentrated/discrete liquidity, crypto order flow, and impact estimation. Record which source
claims have held up, weakened, or changed.

**Stop condition.** Do not browse broadly until B2 identifies the exact venue questions; current
literature should answer a frozen problem rather than generate another encyclopedia.

## Promotion questions before ML

Before training a chart-shape, sequence, graph, language, or ensemble model:

1. What is the target, price object, horizon, and action?
2. Was every feature available at the decision cutoff?
3. What source/coverage process determines inclusion?
4. What deterministic protocol component should be removed or represented explicitly?
5. What simple baseline corresponds to random walk, seasonal intensity, exact curve, or current
   Ember policy?
6. How are transaction costs, failure, capacity, and residual inventory scored?
7. Does the model learn selection/attention, entry timing, management, or all three?
8. What happens when Ember changes the policy because the glass changes?
9. Which held-out regime can reject the claim?
10. What useful instrument remains if prediction fails?

If these are unanswered, more model capacity will create narrative resolution, not knowledge.

