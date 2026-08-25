# JOSHI — session handoff, 2026-08-25 (seed for the curated continuation)

The repo is the source of truth; this is orientation. GOAL.md carries the long done-log and
every correction. docs/planning/REORIENTATION.md is the forward program (five ranked thrusts).
docs/reference/PUMP_API_MAP.md maps the provider surface. The reader of this file is assumed to
be the curated continuation of the session that wrote it.

## Where things stand

Tree clean and gated at HEAD. Ember has a live session (joshi-up: keeper + follow core + glass,
started from committed release binaries). The day landed, in order: hunt mode (live sessions
open on a dense recency-ordered board; `'` toggles inspect), hot attention (hold / hot-scope /
inspect → keeper leases the coin: 1s candles with units, trades, coin_exact, callout_top,
community callouts), the socket recorder with reconnect-and-restate, the self-writing session
debrief (state/s2/), scalplab (pre-registered probabilistic lab, armed, INSUFFICIENT_DATA
verdicts with real diagnostics), the LP desk (her wSOL/USDC book reconstructed to the atom),
the social taps (movers volume + community callout counters flowing through the keeper), boot
perf (51s → 0.7s warm; the backup was 99.96% nanosleep), and the bounded candidate render
(1,343 subjects → 300 by recency, elision stated — the 6.4MB/500 fix, derivation v4).

## OPEN BUGS, with their exact next steps

1. **FIXED 2026-08-25 (82e4dd5): holds commit again.** The 422 was derivation v4 minting
   derived evidence ids (`:rowN:coin-record`, `:claim-*`, `:price-close`, `:change-5m`,
   `:request-resolved-subject`, `:operator-attested-subject`) that named no durable
   observation, so the store's as-known validation refused every act over a metadata-carrying
   scene — and the service swallowed the reason. Evidence entries now carry an explicit
   `observationId` parent (clocks pinned to that row), the store resolves through it
   exact-match, 422 details speak, derivation is v5 (v4 scenes retire through the upgrade
   path). Proven end-to-end on a copy of her real catalog: hold → 202, commitSeq 1141.
   Mutation-verified regression test: `a_hold_act_commits_over_a_view_carrying_derived_evidence`.
2. **Presentation append 404 in follow mode.** The scope is granted now, so Glass tries and
   gets route_not_mounted (NotConfigured — follow-mode CoreService lacks a presentation store).
   Either wire it or make Glass feature-detect; today it renders as a red banner.
3. **Venue readout NetworkError on held coins** in live sessions — likely the venue-readouts
   route absent in follow mounts unless --venue-accounts was passed; check and make honest.
4. **`'` inspect → candles** was wired end to end and blocked only by bug 1; with 1 fixed it
   should work on the next bounce — verify live: inspect a coin, watch
   state/keeper/hot-requests.json appear and the keeper lease it.

## EMBER'S STANDING INSTRUCTIONS (unexecuted or ongoing)

- **THE COPY PASS, her words**: "look at all the text. EVERY SENTENCE IS DISCLAIMING 'IS NOT IS
  NOT'... PLEASE do a pass over all copy and just omit all of that. it's so needless." Strip
  disclaimer prose from ALL glass user-facing copy. Honesty lives in STRUCTURE (the dash, the
  chip, provenance one hover away); the full epistemic sentences may live in tooltips/the
  scene inspector, never on cards, banners, or empty states. Tests pin many copy strings —
  update them honestly. This is a whole-surface editorial lane, not a tweak.
- Background tapes: 10-minute captures only, few per day, as the control corpus — her
  attention-driven tapes (hot loop) are the primary stream. Never again 90 minutes of guessed
  coins.
- Publication intention recorded in GOAL.md: readiness marker = an hour a day in the chair, two
  days running → then the publication-audit lane (linkage inventory, fixture third-party
  review, license, book-derivation check, release shape). Keep commits publication-clean.
- The catalog version string has been extended additively twice (documented at ROUTE_CATALOG);
  bumping it is a migration wanting her call.

## IN-FLIGHT LANES at session end (transcripts harvestable via cv; agents die with the session)

- **LP desk** (analysis/joshi_analysis/lpdesk, committed through the shaping extensions): was
  resumed with two tasks not yet reported — (a) floor-free both-sides recount on a fresh 1-2h
  dense swap tape ending now (her chart-based pushback: the oracle ring averages away edge
  touches; the dense window was only 103s during the rip), with the bins-per-candle
  reconciliation; (b) DAMMv2 measured: find the canonical SOL/USDC cp-amm pool, pull its
  fee/volume/TVL tape (~100 requests), place it on the attention frontier as a measured
  cadence-None point. Key numbers already landed: her gross 4.5-11%/day real, net −9.5%/day on
  the 6.3h trending window; κ=0.075 (effective competing liquidity ~13× the static bin read);
  attention curve non-monotonic (eager worse than never; ~15min best); shaping (CUSUM
  withhold-adverse) rescues +0.5-0.9%/3.6h; her cadence 130s vs her band's 10-15min oscillation.
- **Workability census** (Ember's design: ~300 recent mints + ~100 callouts, statistics →
  autostrat-harvest interaction test, callout entry-window at n~100): mid-collection, its
  sweeps run in its own background with state under this session's scratchpad. Its package
  analysis/src/joshi_analysis/workability/ is UNCOMMITTED and in-flight (a failing test of its
  own was visible: test_workability_tiers.py). Harvest or re-run; the design is in its brief
  (cv: the census deputy's transcript).

## WHERE THE TAPES LIVE (session scratchpad — tmp, not durable; move what matters)

/private/tmp/claude-501/-Users-you-dev-joshi/8f1bedc9-0a94-40bc-90b0-2e3ac40d6f60/scratchpad/
holds: duck-tape (socket, 1,689-event collapse tape), duck-tape-polled (134 obs), kylie-tape +
kylie-backfill (18 trades/s firehose; the sub-block study), fleet-tape-1 (8 coins × 10 min
control slices), keeper-proof, grid panels (duck-grid-*.txt/json), scalplab-v1-run,
mount-check-catalog. The scalplab/census read these paths. tmp evaporates on reboot: anything
the lab needs long-term should be copied into a durable home (state/ or a gitignored
analysis/fixtures corner) by whoever continues.

## Measured findings this arc (the ones that steer decisions)

- Latency tiers: kylie-type coins hold ~94% of extractable structure SAME-SLOT (nobody's
  reflexes matter; only pre-positioned conditionals reach it — spray-with-bounds is the
  measured pro meta, 13/13 error-rate wallets); duck-type coins have a climbable gradient
  (0.5s→+3,347% bound vs 12s→+166%). The intra/cross-slot ratio from a 2-minute backfill is a
  coin-species classifier — "never fight a kylie-type by hand."
- The Duck grid ensemble: every cell deep red on the collapse tape; chosen cell −280bps
  in-sample → −7,722bps held out. "A rule fitted to the first regime was fitted to a market
  that had already stopped existing."
- Scalplab: INSUFFICIENT_DATA everywhere (correct); Hawkes branching dial works (kylie 0.908
  near-critical vs duck 0.166, socket tapes only); needs 6+ moving-coin tapes with 500+ labeled
  events and 25+ positives each. Corpus composition is the binding constraint — tape coins that
  MOVE.
- Two-source reconciliation: 1,584 fills matched, zero price disagreements; 308 socket-missing
  fills inside its own live window — ack is not coverage, measured twice.
- The keeper day budget 3500 with hard stop; coincident cycle ≤30.

## House rules learned or re-learned this arc

Named files only when staging around live deputies (a `git add analysis` swept an in-flight
lane once). Verify SendMessage recipient ids against your own dispatch notes (two LP addenda
went to the perf deputy). `grep -c` exits nonzero on zero matches — never let it gate a chained
commit. The narrowest test that could refute you is the one to run FIRST (the candidate-order
regression shipped because unit fixtures were too small to trip the contract; the perf lane's
real-catalog mount caught it). Deputies pause on API errors/credit outages with work intact on
disk — harvest, gate yourself, finish their last step; a resumed send continues them. Her
verbatim words outrank every summary, including this one.

Ember is PRIMARILY VISUAL and uses a pointer; keyboard complete, reader honest. Absence is
absence; a number without its age is a lie; instruments must be structurally unable to flatter;
and the copy should say things, not disclaim them — see her instruction above.
