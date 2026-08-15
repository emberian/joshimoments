# JOSHI glass — the one-glass UI

Companion to `JOSHI.md` §0/§5/§7. The glass is a TypeScript app (kept, per the language cut)
speaking schema-generated types to `joshid` over an authenticated local socket, browser-first
with a thin desktop shell only when window management earns it. It runs where the operator
is: the Mac.

**The premise:** the operator currently runs the desk across four browser tabs owned by other
people, none of which knows about basis provenance, censoring, expectations, or the journal.
The glass replaces the *reading and deciding* on all four immediately, and the *acting* on
each only as the order pipeline earns it (JOSHI.md §8, phases M1→M3).

---

## 0. Principles — promoted from v1, now the platform contract

These come from the v1 dashboard's earned discipline (`Measured<T>`, `figure.tsx` — "the only
sanctioned way to put a number on screen") and HANDOFF §5. They are not style; violations are
defects:

1. **Provenance on hover.** Every number hangs its origin, clock, staleness, and caveats off
   a hover. A figure that cannot say where it came from does not render.
2. **Sample size beside every rate.** `+18.1% (n=3)` — always, in the same visual register,
   never in a tooltip.
3. **"No data" is never zero.** Measured-zero, watched-but-never-sampled, not-watching, and
   producer-errored are four visually distinct states (v1's four-state rendering, kept).
4. **Measured and attested never sum.** Chain-derived and operator-supplied figures live in
   different columns; totals that would mix them do not exist.
5. **Refusals are rendered.** A refused command, a suspended playbook, a rug-only lot — the
   glass shows what the system declined and why, with the reason from the journal.
6. **Censoring is shown, not dropped.** An expectation that couldn't be scored, a watch
   window that closed early — visible as censored, counted in denominators as censored.
7. **Dead-by-choice is rendered dead.** The sentinel shows as dead with the operator's own
   ban quoted beside it. There is no restart button. (An affordance is an argument; the
   glass does not argue with standing constraints.)
8. **No copyable addresses from history.** A live address-poisoning campaign targets this
   operator with leading-and-trailing vanity matches. History rows render addresses as
   labeled, truncated, *non-copyable* text; the only copyable addresses in the entire glass
   live in the attested address book.

---

## 1. The surfaces it replaces

For each: what it is actually used for today, what replaces it, and what deliberately stays.

### 1.1 trade.padre.gg

| used for | replacement |
|---|---|
| fast candles on watched mints | chart from our own tape — reserve-derived, **executable-exit valuation** (the price you could actually get for your size), not last-trade prints; bounce-free by construction |
| buy/sell with presets | the order ticket → command pipeline (§3): intent → plan → simulate → arm → send, every step visible, every refusal explained |
| wallet PnL | Positions projection with **basis provenance badges** (chain / attested / unknown-rug-only) and reconciliation rows — a PnL number traces to fills on hover |
| token safety glance | the mint card: holder/bundle deltas where measured, tri-state where not; the anti-signal list (locker contracts, raw top-10) rendered as anti-signals |

Stays on padre: nothing, once M3 lands — padre's venue coverage beyond our allowlists was
never used with size, and adding a venue is a code-reviewed allowlist change, not a UI
feature.

### 1.2 jup.ag

| used for | replacement |
|---|---|
| quotes/routing | the plan step *is* the quote — Jupiter's API remains the execution rail (keep the rail, drop the site); the plan shows route provenance, computed `minOut` vs quoted, and the friction line items (priority at measured levels, rent, impact ρ) |
| ad-hoc swaps between majors | same ticket, `OrderKind.Swap`; simulation binding shown before arm |

Stays on jup.ag: truly novel one-off swaps in tokens outside our allowlists — deliberately,
because extending the allowlist is a commit with review, and that friction is the feature.

### 1.3 app.meteora.ag

| used for | replacement |
|---|---|
| DLMM position monitoring | the LP book view: bins vs spot rendered live, **duty-cycle meter** per position (the 49.4%-vs-99.4% scar — an out-of-range DLMM is an open circuit and the glass makes that state loud), fees harvested with n and window |
| deciding width/fee/rebalance | per-pool **η vs VR(T) readout** (LP is +EV ⟺ η > VR; measured η printed with its CI, and "no data" on VR rendered as such — the reversion premise is provisional) |
| open/close/claim/rebalance | commands through the pipeline to the ported lpexec organs; a rebalance proposal renders as a diff (bins pulled, bins placed, rent delta, expected duty-cycle change) |
| pool discovery | deliberately weakened: a watchlist fed by the cluster tape, not a browse-everything surface — pool entry is a decision, not a scroll |

Stays on app.meteora.ag: nothing for the existing book; browsing for exotic new pools stays
manual and rare, and adding one to the allowlist is a commit.

### 1.4 pump.fun

| used for | replacement |
|---|---|
| watching boards/trenches | the boards view from our own boards tape, with the **drawdown split rendered** (shallow-drawdown entries +5.73% median at 2h vs deep −0.45% — the one measured board structure) and the callout stream overlaid as a *volatility locator*, never a direction signal (its measured verdict) |
| coin pages (socials, holders) | the mint card, with tri-state socials (a flag not observed is null, never false) and `x_mint_mention` latency badges (p50 209s — the only social source inside the decision window) |
| claiming creator fees | Toll view: vault balance, claim as a `TollClaim` command through the allowlisted claim path; run-rate, decay t½ with CI, **coverage trigger** vs obligations (obligations attach to streams, structurally never the book) |
| the fee-rung readout | spot distance to the nearest 5-bps rung (25 rungs, mcap-in-SOL, evaluated spot per swap) — with the one surviving tilt surfaced: within 2.71% *above* a rung, the unlock tranche ships whole |
| launching coins | **stays manual, on pump.fun, forever in this design** — the renewable asset is the launch capability, and it is creative work, not desk plumbing |

---

## 2. Layout

Three panes, information-dense, keyboard-first:

- **Left rail — the objects.** Book · Positions · LP · Tolls · Expectations · Playbooks ·
  Models · Boards · Journal. Each with a health glyph (projection lag, watch coverage,
  breaker state). The daily-loss breaker, when tripped, colors the entire rail: the
  absorbing state is not a notification, it is the room's lighting.
- **Center — the stage.** Charts and object detail. Every chart is a tape view: candles from
  reserve readings, our own fills overlaid with actor badges (operator / playbook@version),
  expectations overlaid as translucent cones (see §4), watch-window gaps rendered as gaps —
  never interpolated.
- **Right — provenance and pending.** The hover-provenance pane (pinned version of the
  hover), pending command proposals awaiting approval, and unresolved orders — which sit at
  the top in a state that refuses to be ignored, because `Unresolved` is the state whose
  neglect costs money.

The Journal view is the desk's own history rendered raw: filterable events, refusals
included, each row expandable to its envelope. It is the debugging surface and the audit
surface, and its existence is the point of the architecture.

---

## 3. The order ticket — investigation to signature

Every chain-touching act walks the same visible lifecycle. No express path.

1. **Intent** — from a chart, a position, a proposal. Records provenance (which
   expectation/playbook/gesture caused it).
2. **Plan** — the priced form: route provenance, computed `minOut`, priority fee (measured
   constant, version-stamped), rent itemized, pool impact ρ against the envelope cap,
   friction-artifact version. A plan that can't show a line item doesn't render an arm
   button.
3. **Simulate** — the sim report and what it *binds*: expected balance changes, the
   remainder check. Divergence between plan and sim is shown, not smoothed.
4. **Arm** — the ceremony, deliberately heavier than a click: the three-gate state is
   displayed (config / process / arm-file binding), and arming requires a typed confirmation
   naming the size ("sell 2.1 SOL of nosis"). Muscle memory is the enemy at this step;
   typing the amount defeats it.
5. **Send → Landed/Failed/Unresolved** — signature shown the instant it exists locally;
   reconciliation row appears when the chain answers, divergence classified. `Unresolved`
   pins itself to the right pane until the reconciler resolves it.

**Disarm is one keystroke, always, from anywhere.** Arming is ceremony; stopping is instant.
The asymmetry is the design.

---

## 4. The expectation gesture

The requirement, verbatim: *"semivisually record things like 'idk i think this is gonna keep
goin down' on nosis."* The gesture, on any chart or object:

1. Press **E**. The chart enters expectation mode.
2. **Draw the claim**: drag a cone from now — horizontal extent = horizon, slope =
   direction, vertical spread = the range you'd call "consistent with this." A flat wide
   cone is `Range`; a downward cone is `Drift(Down)`. (Claim vocabulary is small on purpose;
   the sketch snaps to the nearest typed claim and shows which.)
3. **Say it**: type the utterance verbatim — it is kept forever alongside the parse, because
   the parse is lossy and the operator's words are data.
4. **Confidence**: one slider, default 0.65, shown as "what Brier will score."
5. **Evidence attaches itself**: the visible chart window, hovered tape rows, and any open
   RESULT_* docs are linked automatically; add more by pointing.
6. **Enter** records it. The compilation preview appears immediately as a diff (the nosis
   example: ask-only LP shapes on two pools, buy-playbook suspension, a falsifier alert, a
   scoring date). Approve all, some, or none — recording the belief never requires accepting
   the structure.

The expectation then lives on the chart as a translucent cone until resolution; the
falsifier level is a visible line. When price exits the cone early, the glass prompts —
re-affirm, revise (a new version, old one scored as withdrawn-at-level), or withdraw.

**The scorecard** is a first-class view: calibration curve of the operator's declared
confidence vs realized outcomes, split by scope × horizon × population, n beside every
point, censored expectations counted and shown. This is the desk instrumenting its
best-measured signal. It is never a leaderboard; there is exactly one operator.

---

## 5. The playbook review/arm flow

A playbook's page is its whole case file, three records that are **never summed**:

| section | contents |
|---|---|
| identity | id@semver, population scope (Quality/Scalp), the Lean term rendered, check status (typed, envelope-compatible, grammar N) |
| simulation | replay results on pinned tape: purged walk-forward cells, deflated Sharpe with the counted N, the permuted-worlds gate result (a lineage that wins on permuted worlds is discarded regardless of backtest) |
| shadow | paperdesk-pattern record: propensity-logged decisions, would-have fills, attribution split (selection / timing / interaction — reported, not allocated) |
| live | reconciled fills only, same attribution columns, divergence classes |
| bindings | which expectations currently parameterize it; which model healths gate it |

**Arming**: per-playbook, with its own size cap and daily budget slice, through the same
three-gate ceremony as an order — plus one extra: the arm dialog displays the playbook's
shadow-vs-live divergence and refuses if the shadow record is younger than its
pre-registered minimum. **Suspension is automatic** on: expectation compilation (§4), model
death for subscribed models, population-discipline violation, or envelope breaker. Suspended
playbooks render with the reason, in the operator's face, until acknowledged.

---

## 6. Deliberately manual — the list

Things the glass will never automate, each with its reason:

1. **Launching coins** — creative work; the renewable asset is the capability, not a button.
2. **Paying people** — the largest historical outflow category, targeted by a live
   poisoning campaign; stays in wallet software, by hand, from the attested address book.
3. **Adding a venue, program, pool, or destination to an allowlist** — a reviewed commit.
   The friction is the security model.
4. **Basis attestation** — typing a cost basis is a signed statement with a confidence, its
   own small ceremony; it is never prefilled from anything (the mechanism behind the worst
   loss this desk has taken was a prefill).
5. **Restarting the sentinel** — dead by choice; the ban is the operator's, and lifting it
   happens in conversation, not in a UI.
6. **Overriding a breaker** — the absorbing state absorbs. It resets on its own schedule.
7. **Resolving `Unresolved` orders** — only the chain reconciler resolves them; the glass
   shows, and refuses to guess.

---

## 7. Build notes (constraints, not implementation)

- Ships against `joshid` projections over WebSocket/SSE; types generated from the schema
  registry — the glass compiles against the same contract the journal validates.
- Local-first: the Mac keeps follower copies of journal + tape; the glass renders from local
  state and degrades visibly (staleness badges, never silent) when persvati is unreachable.
- The v1 components port as the foundation: `Measured<T>`/`figure.tsx` (four-state
  rendering, provenance hover), `instrument.tsx`, `pricechart.tsx`, and
  `rendered-html.test.mjs`'s scar pins move with them.
- Charting stays in the web ecosystem (the deciding argument for keeping TS); dataviz
  discipline per house rules.
- No public listener, ever. Loopback + authenticated tunnel (the v1 posture, kept).
