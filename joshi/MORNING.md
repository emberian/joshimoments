# Good morning, ember ☀️

Written 2026-08-25 ~15:30Z while you slept. The full trail is in GOAL.md's done log; this is
the part worth reading over coffee.

## The one thing to know: the cockpit works now, end to end

I drove the whole thing myself with the Playwright walk, on a copy of your real catalog, and it
**passed every station**: pair → an 18-row board with tickers/names/ages/mcaps → click into a
coin page ($CATE Catecoin, `2 caps differ` chip and all) → hold it → journal it → advance
(correctly stating "no newer scene" as an absence, not an error). The venue-readout NetworkError
you kept hitting on held coins is fixed — it now renders as a stated absence. Screenshots:
`apps/glass/qa/shots/2026-08-25T15-23-14Z/`.

Two honest gaps the walk surfaced, both being handled:
1. **The board rows still carry disclaimer paragraphs** — exactly the "IS NOT IS NOT" prose you
   told me to strip, never applied to these two surfaces. A copy deputy is on it right now;
   you should wake to chips-and-hovers instead of paragraphs. If it hasn't landed, it's the
   first thing to check.
2. **Empty charts on discovery coins** — a coin only grows a price series once you inspect it
   (the hot-tap loop) with the keeper running. The walk has no keeper, so no bars. In a real
   `joshi-up` session, inspecting a coin starts its candles.

## What the night's science actually found

Two registered studies, both concluded honestly (neither is a win; both are real):

- **selector-live v1** — does measured workability pick coins, live? 8 paired cycles
  (treatment = top-workability coin, control = random), overnight. **Inconclusive on the
  registered tier-8 primary (2-1-3), promising on the exploratory tier-2 secondary (4-0-2).**
  The night was the US-overnight trough — 3 of 8 pools had zero workable coins, half the socket
  tapes caught coins that never printed. The instrument fought coverage the whole way (three
  dated deviations, both arms symmetric). Verdict: **re-run 4-6 cycles in waking-market hours
  before anything hardens** — the machinery is now stable and one command.
  `state/studies/selector-live-v1/results.md`.
- **tournament-v1** — does a strategy family pay in its own regime? **Every conditional cell red
  after the adverse haircut; least-red family is "do the least".** The registered
  regime-orders-families hypothesis FAILED informatively — the two reverting windows disagree on
  which family is least-red. One green cell appeared and was correctly killed (window drift
  priced into held inventory). `state/studies/tournament-v1/panel.md`.

## New capability that landed overnight (all committed, gated)

- **The resident core** — JOSHI now contains its own analyst (reads your scenes, runs analysis,
  writes durable journal evidence — it left one real entry in your session at commit 1381) and
  its own developer (Claude Code in a fenced git worktree; the FIRST self-edit is in main's
  history, `a6863ea`, authored `joshi-resident`). NORTH_STAR commitment #3, done.
- **The availability clock** — the ws consumer that finally stamps when a callout became
  *visible* vs when it *occurred*. First dataset is an honest null (US-prime-time saturated the
  shared bucket for ~2 of 5.5 hours — itself the night's biggest measured fact), but the
  machinery is proven and one command.
- **The candidate-slice route** — one coin verbatim from a 962-subject scene, so the coin page
  and the resident stop pulling multi-megabyte snapshots.

## Loose ends waiting for you (none blocking)

- Community callout COUNTERS (likes/replies/followers) now fetch successfully but sit
  unparsed — the route has no reviewed schema, so the bytes are quarantined by design. Needs a
  `schema_review_community_callouts_v1.json` (daylight work).
  `state/studies/workability-census/RESULTS_ADDENDUM.md`.
- The detached availability run finished ~12:52Z; harvest is done (null, coverage-conditioned).
- Postmark: 6 threads still await the dreggon's reply — untouched, yours to point me at.

To sit down: `./target/release/joshi-up`, pair, hunt. The chair is ready. 🐉
