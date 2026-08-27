"""Flow-model census: the registered v1.4 flow features, models, and market benchmark.

The prior census's momentum signal was a strawman (trailing-1h price direction). This
package builds the real thing on the Kraken tick tape — order-flow imbalance, arrival
intensity, Hawkes excitation, aggressor imbalance, large-trade markers — under the same
decision-time causal pipe, and re-runs the census with the fitted model as the signal.
Registered as jupiter_conditional REGISTRATION.md amendment v1.4 BEFORE any real-data fit.
"""
