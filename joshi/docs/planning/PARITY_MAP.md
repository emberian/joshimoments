# PARITY MAP — pump.fun surfaces × Glass × the data layer

2026-08-25, the parity lane's working map. Written against NORTH_STAR.md ("replicate the
pump.fun experience wholesale, augment it exocortexy") and the operator's 3–5-minute verdict.
One page: what pump.fun has, what Glass has, what the catalog already carries, and the order
this lane built in. File paths are the evidence; nothing here is aspiration dressed as fact.

## The map

| Surface | pump.fun | Glass after this lane | Data layer today (apps/core, keeper) |
|---|---|---|---|
| **Board** | dense rows: ticker, name, age, mcap, % move; flows continuously | hunt board (`AttentionFeed` variant=board): ticker, name, age, mcap, signed 5m, sparkline where a path exists; chips for epistemics; **flows via the advance pill** — feed poll now actually parses (see fix 1) | candidates carry symbol/name/mcap/5m/age; **but** `rank` is mint-lexicographic (not a ranking), `board` hardcoded `watch`, `lifecycle`/`activity` hardcoded unknown, `ageSeconds` is *evidence* age not coin age (`live_surface.rs:2039`) |
| **Coin page** | one click from any row: chart, about, callouts, holders | **one click (or Enter) from any row** → the inspect lens led by the coin page: identity + actions (Hold `;`, Journal), metric cards with lineage, two-mcap disagreement chip, gap-honest chart (1s path, silences drawn), venue floor & break-even clip when measured, microstructure slots stating absence | 1s gap-compressed candles for hot mints (keeper hot lease: candles+trades 2min); `coin_exact` 30min; the two-mcap disagreement ships as tag `market_cap_fields_disagree` + the note carrying both figures |
| **Callouts** | per-coin feed with multiple, caller, likes, replies; callers' track records | coin page renders callout events **when the view carries them**; live views carry none — stated absence, never zero ("Retained callouts are not yet derived into scenes") | **retained but underived**: keeper taps `callout_top` (30m) + community callouts (10m) for hot mints; `multiple`/`maxMultiplier`/likes/replies extracted by `normalize.rs:527‑600`; `live_surface.rs` hardcodes `socialEvents: []` (line 500). Caller track-record route exists (`callout_leaderboard`), keeper never taps it |
| **Search** | global coin search | search over the served scene only (honest: "this immutable choice set") | `coins/search-unrestricted` is catalogued; no live search route in core |
| **Portfolio** | positions, PnL | episode rail + accounting fields, all nullable and honest | no reconciled accounting projection feeds live scenes |
| **Friends / social graph** | followers, holders-in-common | none | routes mapped (PUMP_API_MAP §4.4–4.5), none retained |
| **Livestreams / mayhem** | yes | none — out of scope for parity of the core loop | reconnaissance only |

## What this lane built, in order, and why

1. **The feed-schema fix** (`data/sceneFeed.ts`) — *the actual "cockpit is a photograph" bug.*
   The core's `SceneFeedEntryWire` grew `derivationVersion`, `retiredReason`, and a `retired`
   retention state; Glass's strict zod schema rejected every live feed, so the poll ran forever
   and never once succeeded, no advance pill ever appeared, and the shell could only say
   "unreachable". The client polls fine (`useSceneFeed`, 20s) — it could never *parse*. Also:
   advance now follows the core's own rule — the `cutoffCommitSeq` evidence watermark, never a
   new scene id — and retired rows are never offered (`LiveSurfaceShell.tsx`).
2. **The click-through coin page** — one click (or Enter) on any board row opens the coin,
   recording the same focus-in assertion the `'` lens switch records (debounced per
   scene+coin). The coin page (`CoinWorkbench.tsx`): identity + Hold/Journal actions, the
   `2 caps differ` chip (from the `market_cap_fields_disagree` tag; both figures on hover),
   the gap-honest chart with its resolution stated, callouts-or-stated-absence, the shared
   venue block (`VenueReadoutBlock.tsx`) asking the venue question for the *inspected* coin
   (not only held ones), and three microstructure slots (signature volatility, flow
   decomposition, tier-latency workability) that state "not computed live" instead of a number.
3. **Density where she races** — the hunt lens's held rail is now a one-row chip strip
   (retention stated at chip scale, sentences on hover, full cards one lens switch away).
4. **Red banners → stated absences** — a core with no presentation-witness route renders a
   quiet "witness not mounted" chip (typed `PresentationUnavailableError` on 404/405), never
   the perpetual red alert; real append failures stay loud. Venue-readout absences were
   already stated (`venue/client.ts::absenceFor`); the coin page inherits them. Also removed
   the invalid `[::1]` CSP sources that logged console errors on every load.
5. **The candidate-slice seam** — core grew
   `GET /api/v1/glass/scenes/{scene}/candidates/{id}` mid-lane (a verbatim, digest-traceable
   slice of one candidate). Glass consumes it on the coin page (`data/candidateSlice.ts`,
   optional `GlassDataSource.candidateSlice`): feature-detected, verified against the loaded
   view's digest, adopted only when its bytes differ (today they never do, so it acts as a
   live integrity probe; under a future slim snapshot the adopt branch lights up unchanged).
   The render-bound 404 keeps the core's own words — a bound, never a denial.
6. **The walk harness** (`qa/walk.mjs` + `qa/mockcore.mjs` + `qa/selftest.mjs`) — below.

Order reasoning: fix the flow first (a board that never learns about newer scenes fails the
verdict no matter how pretty), then the click-through (the single largest structural gap to
pump.fun), then absence honesty, then the harness that proves all of it before Ember sits.

## The flow loop, measured (so nobody re-derives it)

inspect/click-through → `request_hot_scope` (mint in payload) → core writes
`hot-requests.json` (TTL 30min, max 16) → keeper tick ≤30s → hot lease (max 3 mints, freshest
attention wins): candles 1s×1000 every 2min, trades 2min, coin_exact 30min, callout_top
30min, community callouts 10min → catalog commit → core follow poll ≤20s mints a new scene →
Glass feed poll ≤20s → **advance pill**. Floor from click to first chart bars: ~2–3 minutes,
and they arrive in a *newer* scene — the current scene's bytes never change. The coin page
says exactly this under an empty chart.

## Data-layer asks (ranked; owner: core/keeper lanes — this lane touched none of it)

1. **Derive retained callouts into `socialEvents`** — the single highest-parity-per-effort
   item; the bytes (multiple, caller, likes, ages) are already durable, `kind:"callout"` is
   already in the contract, and Glass already renders it (the mock proves the rendering).
2. **Stop serving a fake `rank`** — mint-lexicographic ordinals read as board positions;
   serve recency rank or null.
3. **`ageSeconds` semantics** — evidence age masquerades as coin age; discovery carries the
   real creation age (`/boards/movers` `age` key). Serve coin age or null.
4. **`board`/`lifecycle`/`activity`** hardcoded — the tabs starve; discovery + movers carry
   enough to populate them honestly.
5. **Tap `callout_leaderboard`** for caller track records (route live, fields mapped, never
   collected).

## The walk harness — how the primary runs it

Self-test first (no live core needed; proves the harness itself, including a real advance):

```sh
cd apps/glass && pnpm qa:selftest
```

Against a live session (core `live-surface-inspect`/`joshi-up` running, vite serving Glass):

```sh
cd apps/glass
JOSHI_GLASS_URL=http://127.0.0.1:4173 \
JOSHI_PAIRING_CODE_FILE=/path/the/launcher/wrote \
pnpm qa:walk
```

Stations: pair → board → coin page (click-through) → hold → journal → advance. Screenshots +
`report.json` land in `qa/shots/<stamp>/`. Exit nonzero on any console error, page error,
failed request outside the feature-detected absence classes (venue readouts, presentation
witness, single-scene feed), or missing surface. "No newer scene during the walk" is a stated
absence, not a failure (`JOSHI_WALK_ADVANCE_WAIT_MS`, default 45s). Two honesty properties of
the walk itself: **it marks its own acts in-band** (the hold gets an immediate note, and the
journal entry names itself, as harness output — so the selection instrument can exclude them
by stated provenance), and **it deletes a consumed `--code-file`** so the launcher reissues a
fresh code for the human (`--keep-code-file` to opt out).

## Deliberately deferred (and why)

- **Global search / bigger candidate universe** — needs a core search route; scene-local
  search stays honest until then.
- **Portfolio / PnL** — no reconciled accounting projection exists; rendering one would be
  fabrication.
- **Holders / friends surfaces** — routes mapped but unverified/uncollected (PUMP_API_MAP
  §4.5); design waits for data.
- **The held-historical coin page** — a held coin the feed stopped carrying could get a full
  page sliced from its HOLDING scene (the slice route serves any retained generation). Real
  value, deferred because the selection machinery deliberately resets to the current scene's
  candidates; it needs its own small design pass, not a bolt-on.
- **Streaming chart ticks** — scenes are immutable by design; flow is the advance loop, and
  auto-swap under the operator stays forbidden. If sub-scene tick flow is ever wanted it is a
  new, separate surface with its own honesty contract, not a mutation of this one.
