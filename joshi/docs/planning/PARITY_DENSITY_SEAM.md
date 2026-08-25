# Parity-density seam — the candidate wire additions (2026-08-25)

The board is far from pump.fun density (Ember's reference shots: ~10 sortable data columns +
coin art + sparkline in Table; image-first cards in Grid, which she says is the mobile-primary
UX and matters most; candles — not just a sparkline — on Grid cards). Ground truth: the
discovery_coins rows JOSHI already retains carry almost every field pump shows; the derivation
drops them. This seam is the exact set of candidate fields the Rust derivation
(apps/core/src/live_surface.rs) ADDS and the Glass contract (apps/glass/src/contract/v1.ts)
LEARNS, so the two lanes cannot drift. Every field is a labelled PROVIDER CLAIM (evidence class
`observed` when the coin's own record carries it) with its `observationId` parent per derivation
v5. Absent → the field is omitted (optional) and Glass renders a dash. NOTHING is fabricated.

## Confirmed present in retained discovery_coins rows (verified against real bytes)
image_uri, ath_market_cap, ath_market_cap_timestamp, reply_count, description, created_timestamp,
last_trade_timestamp, usd_market_cap, market_cap (quote), complete (graduated), verified, nsfw,
is_currently_live, creator, username, twitter, website, real_sol_reserves, virtual_sol_reserves,
total_supply. (coin_exact carries the same shape for a single mint.)

## Confirmed available from the movers tap (advanced-indexer, catalogued, keeper taps it)
per-window volume SOL + USD (5m/15m/1h/24h), trade counts, unique traders (where present),
provider serverTs. These are the TXNS / VOL / TRADERS / multi-window %-change columns.

## New optional fields on the candidate wire (camelCase; all optional; omit when unobserved)
- `imageUri: string`        — coin art URL, provider-asserted. See SECURITY below.
- `description: string`     — the coin's own thesis line (trending caption).
- `replyCount: string`      — wire-u64 as string, provider social counter.
- `athMarketCapUsd: string` — exact decimal literal, provider claim (never f64).
- `athAtUnixMs: string`     — ath timestamp, provider claim.
- `createdAtUnixMs: string` — for a true COIN age (distinct from evidence age — this is the fix
  for the fake mint-lexicographic rank/age the parity deputy flagged).
- `lastTradeAtUnixMs: string`
- `graduated: bool`, `verified: bool`, `nsfw: bool`, `currentlyLive: bool`
- `flow: { window: "5m"|"15m"|"1h"|"24h", volumeSol: string, volumeUsd: string, txns: string,
    traders?: string, serverTsUnixMs: string }[]`  — from the movers tap, per retained window.
  Absent entirely when movers was not tapped for this mint.
- The existing `metrics` block and `candles` array stay; Grid plots `candles` where present
  (Ember's ask), a movers-derived sparkline where only `flow` exists, a dash where neither.

## Provenance (non-negotiable)
Each new field gets an evidence entry (class `observed`, field-named, its coin-record parent in
`observationId`, clocks pinned to that observation) OR — for the movers `flow` — class
`observed` bound to the movers observation. The two-market-cap disagreement chip pattern stays.
Provider timestamps are provider claims, retained verbatim, unit declared (epoch ms here;
the coin-communities ISO-µs family is elsewhere — do not cross them).

## SECURITY — remote images
`imageUri` is a provider-controlled remote URL (ipfs/cdn). Rendering it in the cockpit fetches
from a third party (a privacy signal, and a CSP surface). Decision for this lane: render with a
strict `referrerpolicy=no-referrer`, `loading=lazy`, a fixed box with `object-fit: cover`, a
monogram fallback on error, and NO cookies/credentials. Do NOT proxy through core in v1 (heavier;
revisit). State this in the coin page's provenance drawer: "art is fetched from the provider's
URL; JOSHI does not host it." A future hardening is a core image-proxy; flag it, don't build it.

## Territories
Lane A (derivation): apps/core/src/live_surface.rs + its tests, the candidate wire struct there.
Lane B (glass): apps/glass — contract/v1.ts (learn the fields), AttentionFeed/CoinWorkbench,
a real Grid view (image-first cards, candles-where-present), sortable Table columns, the
Trending strip. The two meet ONLY at the field names above.
