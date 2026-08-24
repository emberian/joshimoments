# JOSHI — session handoff, 2026-08-23 morning

Seed for a fresh session. The repo is the source of truth; this is orientation, not history.
`GOAL.md` carries the full done-log and every correction Ember made along the way.

## Where things stand

Tree clean, all lanes integrated and gated: fmt clean, workspace clippy `-D warnings` clean,
joshi-core 81, Glass 252, pump-api/adapter/admission 164, liquidity/market-math 100, store/operator
included, analysis 291 (ruff clean).

**The window composes.** `keeper -> catalog -> follow-mode -> scene` works end to end for both the
wallet source and the price source. The keeper commits real bounded cycles with hard budgets, a
heartbeat, and clean SIGTERM coherence. Scenes are immutable; new observations mint new scenes, a
journal write does not, and the operator chooses when to advance. A resident (Claude Agent SDK,
jailed to four MCP tools) can pair like the cockpit and write durable evidence.

**Ember can hold a coin with one key.** `;` binds a durable `record_focus` to exact scene bytes,
the held rail never scrolls away, and the journal reads acts back verbatim after restart. What she
saw (`viewport`) is now recorded distinctly from what was drawn (`rendered`).

## What is measured, and what it says

- **The dip is real and candles cannot see it.** Live on our own tape: 45.16% drawdown at event
  resolution where the one-minute close series shows 1.27%. 77% of coins have <=3 candles in their
  first hour.
- **Venue fee tier dominates, not graduation.** A freshly graduated pool measured 249 bps and a
  0.81 SOL max clip — indistinguishable from a bonding curve — because its market cap selects the
  first tier row. The lever is which row the cap selects.
- **State age beats arithmetic.** ~12s chain-to-receipt at finalized; a pool drifted 9-10 bps in
  30s, so a 60 bps fee floor is two to four minutes of drift.
- **Post-callout, the edge is in waiting.** 6/6 sampled callouts dipped below the callout price
  (median 28%); 6/6 clear the hurdle entering at the trough vs 2/6 at the callout price. n=6, and
  the occurrence-vs-availability confound is unresolved.
- **Nothing beat doing nothing.** Replaying the retained tape through five declared variants: 0 of 5
  on any coin cleared its own drift haircut against a net of zero. Also, the parameter grid was
  finer than the tape's price granularity — five strategies were two behaviours.
- **Regime persists a few hundred events ahead, not across lifetimes** — and only on the coins worth
  working (split-half rho 0.51 there, ~0 pooled). The two clocks disagree at chance level, so a tag
  must name its clock.
- **Selection is the unmeasured frontier.** Callers show no forward edge, leaderboards are
  retrospective, and the strongest corpus predictor is an accounting identity. If there is alpha
  here, current evidence points at Ember's own picking — which is now instrumented and pre-registered.

## The next things

1. **Bring-up glue.** Everything is built; sitting in it still takes four commands across three
   terminals plus ferrying a pairing code. One `joshi-up` would close it. Ember's stated next goal
   is to sit inside JOSHI and iterate from within.
2. **Run the keeper under launchd for real** (`ops/launchd/`), so the catalog advances unattended.
3. **The selection power budget**: ~110 scored scenes to detect skill, ~891 for a tradeable edge.
   That is a lot of sitting; design sessions accordingly.

Done since this handoff was written: the viewport definition is corrected for a primarily-visual
operator (v2: scroll-rectangle visibility and pointer entry join focus-reach; `pointed` is its own
recorded kind per Ember's ruling; migration 0025 widens the store vocabulary), and the
blob-agreement subset check for client-observed kinds is in.

## House rules that were learned the hard way

An absent row is an absent record; an empty result is not absence; a number without its age is a
lie by omission. Refuse rather than guess, and make the refusal say why. A schema that cannot
express "I have nothing" will get a fabricated answer — that already happened once, and a
fifteen-number dossier was invented to satisfy a required cardinality. Gate the narrowest thing that
could refute you; never a bare `-p` suite.

Ember is PRIMARILY VISUAL and uses a pointer. She uses a screen reader sometimes; she is NOT
keyboard-only, and designing as if she were is a mistake this project already made (a repo doc said
so, an agent believed it, and it shaped real decisions before she corrected it). Keyboard paths must
work — six of eight single-letter shortcuts collide with NVDA/JAWS quick-nav, which is why the hold
key is `;` — but visual scanning is her main channel and should be treated as first-class. (The listbox/`aria-activedescendant` restructure has since landed: the feed is one tab stop,
scroll-invariant, and hunt mode renders through the same frozen architecture.)
