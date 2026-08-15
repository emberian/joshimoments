# JOSHI glass — the operator's personal pump app

Companion to `JOSHI.md` §0/§5/§7. The glass is a TypeScript app (kept, per the language cut)
speaking schema-generated types to `joshid` over an authenticated local socket, browser-first
with a thin desktop shell only when window management earns it. It runs where the operator
is: the Mac.

**The organizing principle, operator verbatim: *"basically JOSHI is turning into my personal
copy of the pump app."*** That is the product. JOSHI-glass is pump.fun rebuilt for one
operator — the same daily surfaces, in the same reach-for-it-without-thinking positions,
served from **our** tapes with the instrument disciplines (provenance, n, four-state data)
and the operator-native gestures (hunch, zap, expectation, duel) woven into them. Three
layers, built in this order:

1. **Parity surfaces** — the pump.fun daily loop, cloned: trenches/new-coins, callouts,
   boards/trending, the coin page, the quick-trade panel, the creator/fee view. The spine;
   ships first (M1).
2. **Superpowers** — what pump.fun cannot do because it doesn't know the operator: hunch
   cards, zap, expectation cones, the duel view, drawdown-split boards, basis provenance,
   the scorecard.
3. **Engine room** — journal, playbooks, models, reconciler state, underneath and always one
   click down.

The other three tabs — trade.padre.gg, jup.ag, app.meteora.ag — fold in as panels of the
same app (§2). The one thing the frame excludes cleanly: JOSHI clones the **consumer**
surface the operator lives in; the **creator** side — launching — stays on the real
pump.fun, manual forever, because the renewable asset is the launch capability, not a
button.

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
9. **Exits never have ceremony.** The zap is one keystroke, per position, from anywhere,
   always. Entry may carry ceremony — placed per population (§4) — but nothing may ever
   stand between the operator and an exit. The asymmetry is the design.

---

## 1. The pump.fun parity map — the spine

For each surface of the real app: what the operator actually uses it for, and what the
personal copy renders instead. Parity means the *daily loop* works here; every cell also
carries the instrument disciplines the real app structurally cannot have.

| pump.fun surface | used for | the personal copy |
|---|---|---|
| **trenches / new-coins feed** | ambient watching of fresh launches | the live launch feed from our own boards/firehose tape, age and vSol curve position on every card, watch-window gaps rendered as gaps; **hunch buttons on every card** (§3) |
| **boards / trending** | what's moving, what has attention | the boards view with the **drawdown split rendered** — the one measured board structure (shallow-drawdown entries +5.73% median at 2h, p(up) 76%, vs deep −0.45%) colors the cards; null-arm baseline shown beside it |
| **callouts** | the social feed beside the coins | the callout stream overlaid as a **volatility locator, never a direction signal** (its measured verdict: direction is an anti-signal; streams mark two-sided flow), with `x_mint_mention` latency badges (p50 209 s — the only social source inside the decision window) |
| **coin page** | the look before a trade: chart, socials, holders | the mint card: candles from reserve readings at **executable-exit valuation** (bounce-free by construction), tri-state socials (unobserved is null, never false), bundle-adjusted holder deltas where measured, the anti-signal list rendered *as* anti-signals; expectations and past hunches on this mint overlaid |
| **quick trade panel** | the buy/sell click | the hunch card (Scalp: click spends pre-authorized playbook budget) or the order ticket (Quality: full lifecycle, §4) — same position on screen as the real app's panel, because muscle memory is the interface |
| **creator / fee view** | claiming DREGG creator fees, watching the vault | the Toll view: vault balance, claim as a one-click `TollClaim` command through the allowlisted claim path, run-rate and decay t½ with CI, **coverage trigger** vs USD obligations with the SOL/USD exposure shown (JOSHI.md §9.5), and the fee-rung readout — distance to the nearest 5-bps rung (25 rungs, mcap-in-SOL, spot per swap) with the one surviving tilt surfaced: within 2.71% *above* a rung, the unlock tranche ships whole |
| **any coin by address** | pasting a mint to look at it | same paste box; an unwatched mint renders honestly as **not-watching** (four-state, never fabricated) with a one-click **Watch** command that starts collection — the personal copy's universe is the collected universe, and it says so |
| **launching** | the creator side | **stays on the real pump.fun, manual, forever** — out of the clone by definition |

The parity constraint cuts the other way too: the trenches feed only works if the collectors
are treated as **product infrastructure, not research plumbing** — feed staleness is a
product defect the moment the glass is the daily surface. The watchdog's freshness targets
become product SLOs, rendered as staleness badges, never silently stale (§7).

---

## 2. The other three tabs — folded into the same app

### 2.1 trade.padre.gg

| used for | replacement |
|---|---|
| fast candles on watched mints | the coin page chart (§1) — our tape, executable-exit valuation |
| buy/sell with presets | hunch card (Scalp) or order ticket (Quality), §3/§4 |
| wallet PnL | Positions projection with **basis provenance badges** (chain / attested / unknown-rug-only) and reconciliation rows — a PnL number traces to fills on hover |
| token safety glance | the mint card's measured columns; tri-state everywhere |

Stays on padre: nothing, once M3 lands — padre's venue coverage beyond our allowlists was
never used with size, and adding a venue is a code-reviewed allowlist change, not a UI
feature.

### 2.2 jup.ag

| used for | replacement |
|---|---|
| quotes/routing | the plan step *is* the quote — Jupiter's API remains the execution rail (keep the rail, drop the site); the plan shows route provenance, computed `minOut` vs quoted, and the friction line items (priority at measured levels, rent, impact ρ) |
| ad-hoc swaps between majors | same ticket, `OrderKind.Swap`; simulation binding shown before arm — including the scheduled USDC obligation-buffer conversions (JOSHI.md §9.5), which are ordinary orders |

Stays on jup.ag: truly novel one-off swaps in tokens outside our allowlists — deliberately,
because extending the allowlist is a commit with review, and that friction is the feature.

### 2.3 app.meteora.ag

| used for | replacement |
|---|---|
| DLMM position monitoring | the LP book view: bins vs spot rendered live, **duty-cycle meter** per position (the 49.4%-vs-99.4% scar — an out-of-range DLMM is an open circuit and the glass makes that state loud), fees harvested with n and window |
| deciding width/fee/rebalance | per-pool **η vs VR(T) readout** (LP is +EV ⟺ η > VR; measured η printed with its CI, and "no data" on VR rendered as such — the reversion premise is provisional) |
| open/close/claim/rebalance | commands through the pipeline to the ported lpexec organs, from the LP wallet with the LP key's allowlist; a rebalance proposal renders as a diff (bins pulled, bins placed, rent delta, expected duty-cycle change) |
| pool discovery | deliberately weakened: a watchlist fed by the cluster tape, not a browse-everything surface — pool entry is a decision, not a scroll. (The browse-freely inversion of §1 applies to the *pump* surfaces, where browsing is the product; it does not extend to opening pools.) |

Stays on app.meteora.ag: nothing for the existing book; browsing for exotic new pools stays
manual and rare, and adding one to the allowlist is a commit.

---

## 3. The hunch loop — the superpower on every card

Live in v1 already (`app/views/explorer.tsx` → `state/hunches.jsonl`); this is its v2 form.
Every coin card — trenches, boards, coin page — carries the hunch buttons:

- **[wiggle]** — "this will oscillate tradably": records the hunch (claim `Wiggle`, horizon
  minutes, confidence one tap) and opens an **instant paper position** in the wiggle book —
  or a live one, iff the Scalp playbook is armed and has budget (§4). The click *is* the
  entry; there is nothing else to do.
- **[down]** / **[up]** — a directional minute-scale claim: scored at horizon with a
  falsifier line on the card's sparkline.
- **[watch]** — starts collection and a watch window; the card joins the operator's feed.

**Instrument readback, immediately:** the card flips to show what the instruments know about
this mint — flow, age, vSol position, drawdown percentile, crime-score percentile (as an
avoid-filter, its measured verdict), each four-state, each with n. The hunch was recorded
*before* the readback flip, deliberately: the belief is captured pre-instrument, so the
scorecard can later measure what the operator's eye adds over the instruments — that
comparison is the whole point of recording hunches at all.

**The zap** sits on every operator position, everywhere it appears — one keystroke, no
confirmation, no ceremony (principle 9). Each zap writes a `ZapRecord` with the **full
tape-state at exit**; the (state, exit) pairs are the training set for the reactive-exit
policy search — the operator's exits are reactive, hold-duration was never the policy, and
this is how the reaction gets learned instead of miscast as a clock. The 5-minute clock
survives only as the backstop on paper positions the operator walked away from.

Hunches score by **position outcome** on their own scorecard section; expectation Briers on
theirs; the two are never summed.

---

## 4. Entry — the ticket, and where the ceremony lives

Every chain-touching act walks the same visible lifecycle: **intent → plan → simulate → arm
→ send → landed/failed/unresolved**, with the plan showing its route provenance, computed
`minOut`, priority at measured levels, rent itemized, impact ρ against the envelope cap, the
friction-artifact version, and the acting **wallet** (whose per-wallet allowlist scopes what
the ticket can even propose). Refusals render with reasons. `Unresolved` pins itself to the
right pane until the reconciler resolves it — the glass shows, and never guesses.

**Ceremony placement is per population** (proposed-normative pending the operator's
explicit confirmation — JOSHI.md §4):

- **Quality** — ceremony per order: the arm step requires a typed confirmation naming the
  size ("sell 2.1 SOL of nosis"). Muscle memory is the enemy at this step; typing the
  amount defeats it.
- **Scalp** — ceremony at playbook-arm time: the scalp playbook is armed once, with budget
  and caps, through the full three-gate ceremony; thereafter the hunch click **is** the
  entry, spending pre-authorized budget inside the playbook. A scalp that waits for a typed
  confirmation does not exist as a trade. The three gates remain structurally in force at
  the process level; what moves is the human ceremony.
- **Both populations** — disarm and zap are one keystroke, always, from anywhere
  (principle 9). Arming is ceremony; stopping is instant.

---

## 5. The expectation gesture

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

**The scorecard** is a first-class view: calibration of the operator's declared confidence
vs realized outcomes — Brier for expectations, position outcome for hunches, in separate
sections — split by scope × horizon × population, n beside every point, censored counted
and shown. This is the desk instrumenting its best-measured signal. It is never a
leaderboard; there is exactly one operator.

---

## 6. The duel view — imitation families, side by side

When a symbol spawns a family — the original and its imitators sharing a name — the duel
view renders the family **side-by-side on one clock**: each member's flow, holders, board
presence, and reserve path, plus the **drain direction** — which member is bleeding wallets
and SOL to which, read from the cross-member flow the tape already carries. This is a
surface pump.fun structurally cannot offer (it shows each coin alone; the family is the
object here), and it feeds the same gestures: hunch buttons per member, an expectation cone
over the family (`Relative` claims: "the original outlives the clone").

---

## 7. The playbook review/arm flow

A playbook's page is its whole case file, three records that are **never summed**:

| section | contents |
|---|---|
| identity | id@semver, population scope (Quality/Scalp), the Lean term rendered, check status (typed, envelope-compatible, grammar N) |
| simulation | replay results on pinned tape: purged walk-forward cells, deflated Sharpe with the counted N, the permuted-worlds gate result (a lineage that wins on permuted worlds is discarded regardless of backtest) |
| shadow | paperdesk-pattern record: propensity-logged decisions, would-have fills, attribution split (selection / timing / interaction — reported, not allocated) |
| live | reconciled fills only, same attribution columns, divergence classes |
| bindings | which expectations currently parameterize it; which model healths gate it; for Scalp: remaining pre-authorized budget, rendered where the operator can see it drain |

**Arming**: per-playbook, with its own size cap and daily budget slice, through the same
three-gate ceremony as an order — plus one extra: the arm dialog displays the playbook's
shadow-vs-live divergence and refuses if the shadow record is younger than its
pre-registered minimum. For Scalp playbooks this arm ceremony is *the* ceremony (§4).
**Suspension is automatic** on: expectation compilation (§5), model death for subscribed
models, population-discipline violation, or envelope breaker. Suspended playbooks render
with the reason, in the operator's face, until acknowledged.

---

## 8. Deliberately manual — the list

Things the glass will never automate, each with its reason:

1. **Launching coins** — the creator side of the app is not cloned; the renewable asset is
   the capability, and it stays on the real pump.fun.
2. **Paying people** — the largest historical outflow category, targeted by a live
   poisoning campaign; stays in wallet software, by hand, from the attested address book.
3. **Adding a venue, program, pool, wallet, or destination to an allowlist** — a reviewed
   commit. The friction is the security model.
4. **Basis attestation** — typing a cost basis is a signed statement with a confidence, its
   own small ceremony; it is never prefilled from anything (the mechanism behind the worst
   loss this desk has taken was a prefill).
5. **Restarting the sentinel** — dead by choice; the ban is the operator's, and lifting it
   happens in conversation, not in a UI.
6. **Overriding a breaker** — the absorbing state absorbs. It resets on its own schedule.
7. **Resolving `Unresolved` orders or `Unclassified` reconciliations** — only the
   reconciler resolves the first on chain evidence; only an operator attestation resolves
   the second. The glass shows, and refuses to guess (design/reconciler.md).

---

## 9. Build notes (constraints, not implementation)

- Ships against `joshid` projections over WebSocket/SSE; types generated from the schema
  registry — the glass compiles against the same contract the journal validates.
- Local-first: the Mac keeps follower copies of journal + tape; the glass renders from local
  state and degrades visibly (staleness badges, never silent) when persvati is unreachable.
- **Collectors are product infrastructure now.** The parity frame promotes the boards/
  firehose/callout collectors' freshness from research nicety to product SLO: the watchdog's
  targets surface in the glass as feed-health badges, and a stale trenches feed is a defect
  with an owner, not a shrug.
- The v1 components port as the foundation: `Measured<T>`/`figure.tsx` (four-state
  rendering, provenance hover), `instrument.tsx`, `pricechart.tsx`, the v1 explorer/hunch
  views, and `rendered-html.test.mjs`'s scar pins move with them.
- Charting stays in the web ecosystem (the deciding argument for keeping TS); dataviz
  discipline per house rules.
- No public listener, ever. Loopback + authenticated tunnel (the v1 posture, kept).
