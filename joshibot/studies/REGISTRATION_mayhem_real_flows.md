# REGISTRATION AMENDMENT: mayhem outcomes on REAL flows — is a re-instrumentation worth building?

2026-08-29, registered AFTER `docs/MAYHEM_MODE.md` (478673c) landed and BEFORE any estimand
below was computed. This amends `REGISTRATION_mayhem_arm.md`: the mechanism recon proved
prices in the mayhem stratum are ADMINISTERED (virtual SOL reserves rewritten ~500x inside
fee-exempt agent trades; k/k_std measured 0.0023-4.87), so the original M4/M5 outcome
definitions (mcap-threshold rip/collapse via the affine identity) measure pump's re-marking
policy, not market behavior. Those numbers are hereby demoted to labeled artifacts in the
RESULT. This amendment defines outcome estimands on REAL token flows only and answers the
coordinator's question: does anything separate rips from non-rips once the agent is
excluded and outcomes are real — and is the t+24h re-instrumentation worth building?

## Author-knowledge disclosure

I have seen: everything in RESULT_mayhem_arm.md as first written (census, roles, the
pseudo-price outcome rates and gate tables, the crew null), the vault outflow row counts
(1.2M negative rows, 96% of ROWS exact same-tx transfers into the curve — an accounting I
now know conflates agent sales with the t+24h burn and must redo by AMOUNT and by
supply-reduction semantics), and all of docs/MAYHEM_MODE.md. I have NOT computed: any
human-participation distribution, any post-24h activity rate, any real-flow rip rate, or
any feature separation against a real-flow outcome.

## Definitions (pinned now)

- AGENT := any ledger row whose owner is the sol-vault PDA `BwWK17cb...` (constant across
  the stratum; cannot rotate per the recon). CURVE := the derived bonding-curve PDA owner.
- HUMAN := any other owner (the deployer counts: its flows are real).
- BURN row := a (slot, tx) whose summed delta for the mint is negative (net supply
  reduction). Vault outflow decomposes by AMOUNT into: into-curve (same-tx exact-match
  curve credit), burn (supply-reducing tx), other.
- R1 HUMAN CROWD := distinct human owners with a positive delta in any tx from the birth
  slot through birth+86400.
- R2 ALIVE PAST THE WINDOW := at least one human-involving row for the mint strictly after
  birth+86400. Computed only on coins with birth_time <= window_end - 86400 - 21600
  (>= 6h of observable post-burn exposure).
- R3 REAL RIP := insider disposal >= 80% of insider peak (token-side, agent excluded —
  the existing t_dump) AND R1 >= 25 (materiality by crowd, pinned now; declared
  sensitivity cells at >= 10 and >= 50, reported beside it, never swapped in).

## Registered estimands

E1. The R1 distribution (p25/50/75/90, share with R1 >= 10/25/50) — the addressable-
    audience size for any mayhem AVOID product.
E2. The R2 rate — the addressable population for the recon's "score at t+24h" design.
E3. R3 base rate (pooled and day-08-26-only).
E4. Feature separation against R3, within-stratum, agent excluded, features that the
    recon says survive: (a) human bundledness n_snipers >= 2; (b) dev_buy_share >= 2%
    with the denominator PINNED at 2e15 (share of true minted supply; stated on every
    output); (c) REAL dirty history := deployer has a prior token-side dump (t_dump) or
    prior REAL rip among window-A/fresh-standard coins (their price labels are valid) —
    mayhem prior events contribute dumps only, never mcap-based rips. Each: risk ratio
    with 2,000-draw deployer-clustered bootstrap 95% CI.
E5. The CLEAN-analog conjunction (no human bundle, dev buy < 2% of 2e15, no real dirty
    history, no recidivist sniper) vs R3: admit rate, precision, Wilson 95% CI.

## Ship rule (pinned now)

Recommend BUILDING the t+24h real-flows arm iff BOTH:
  (a) coverage: R2 >= 10% of exposure-complete mayhem coins, OR R3 has >= 300 events
      pooled (enough rips to price a screen against);
  (b) separation: at least one of E4(a-c) has risk ratio >= 2 with CI excluding 1.
Otherwise recommend NO-BUILD: the stratum stays UNSCORED permanently under both the
validated screen AND the real-flows re-instrumentation, and the mechanism writeup ships as
the product content. A clean NO is a complete deliverable.
