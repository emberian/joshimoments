# Living in JOSHI — the gaps between today and a daily life

Status: gaps deputy report, 2026-08-22. Grounded against GOAL.md, S2_RUNBOOK.md, the last 40
commits, SESSION_HISTORY.md, the glass components and core route registrations, and Yuè's
polymarket work under ~/kimi_state. Every gap below was verified against the tree, not taken
from the brief. This document proposes no new ceremony and no new crates; every fix builds on
something that already runs.

## The measuring stick: one real morning

This morning, 2026-08-21:

- The primary agent swept Ember's wallet (Funv3QdbBA1ZUC53t2ZoWa9zubAz15w9oCyajDPoRaMQ) by
  hand-composing fetch requests. That address appears **nowhere in this repository** — not in a
  config, not in a fixture, not in a test.
- Transactions were decoded with inline Python. An LP band was analyzed with ad-hoc DuckDB.
  All of it real work, none of it a JOSHI surface, and none of its conclusions retained anywhere
  a future morning can find them.
- She held 5.28M SOLVE through a price spike she would have liked to sell into, because nothing
  was watching. That is the largest named dollar cost in this document.

"Living in JOSHI" means: the morning begins on a JOSHI page, charts are studied there, positions
are watched there, and conclusions are remembered there. SESSION_HISTORY.md's requirement 10
already licenses this: the workstation is valuable through **better perception, accounting,
replay and containment** even if every strategy family is parked. Nothing below needs execution
authority, and nothing below asks Ember's hands to do more.

## The ranked gaps

Ranked by (what living with it costs) × (how cheap the honest fix is). Sizes are for the
smallest honest version, not the complete one.

### 1. A hold vanishes on reload — no read-back route for operator acts

**What it is.** The hold gesture (`;`) commits a durable operator act bound to exact scene
bytes, and the store retains it. But core serves no GET route for operator commands —
service.rs mounts only `POST /api/v1/operator/commands` — so after a reload the rail is empty.
HeldCoins.tsx says so on screen (line 325), which is honest, and still a broken promise.

**What it costs.** JOSHI's founding asymmetry is "pump.fun's feed FORGETS, and JOSHI is a
retention machine." Today JOSHI forgets too, one `Cmd-R` at a time. Every browser hiccup, every
core restart, every morning-after loses the working set of held coins — the one thing the
machine was built to never lose. Nobody lives in a house that forgets what you put on the table.

**Smallest honest fix.** One GET route serving accepted operator commands for the paired
session, from the store, with their scene bindings; glass hydrates the rail on mount, ordered
by original hold time. No new types — the acts are already durable and typed.

**Builds on.** The store already retains the acts; the route and pairing patterns in
apps/core/src/service.rs; HeldCoins already renders exactly this rail.

**Size.** Hours to a day. The cheapest real fix in this document.

### 2. Nothing is watching what she holds — no standing watch, no alert

**What it is.** No process, anywhere, observes a held coin or an open position and says
"this moved." The candidate finder differences two sweeps when a human runs it; the venue
readout answers when a human asks. Between invocations, JOSHI is blind.

**What it costs.** The SOLVE spike, directly: 5.28M tokens held through a move she wanted to
sell into. And the second-order cost is worse for her hands — with no watcher, *she* is the
watcher, which means polling charts by hand, which is the exact interface tax JOSHI exists to
remove. GOAL.md's bottleneck line — "i literally couldn't push buttons fast enough" — has a
sibling: she cannot *look* continuously either. Nobody can.

**Smallest honest fix.** One persistent read-only process that polls marks for a named watch
set — the union of the held rail and the wallet's token holdings — at an honest cadence, and
when |move| since a stated reference crosses a stated threshold, (a) records the alert durably
with the bytes that triggered it and its state age, and (b) surfaces it in a screen-reader
live region and/or a macOS notification. It is an **attention pager, not a signal**: it says
"look here," never "buy/sell." Thresholds are per-subject and hers.

**Builds on.** joshi-pump-api's client and the venue-readout mark arithmetic; joshi-supervisor's
occurrence/journal/queue machinery (built for exactly this shape of bounded ingestion);
the held rail as the natural watch-set source; the hold-survival rendering in glass (a coin the
feed stopped carrying already renders honestly). Requires gap 4 (persistence) and is the best
reason to close it.

**Size.** Days (2–4) for marks-on-a-watch-set with durable alerts. Position-aware variants
(gap 6) come later.

### 3. The wallet is invisible — no portfolio, no cost basis, no PnL surface

**What it is.** No JOSHI surface shows what the wallet holds, what it cost, or what it is
worth. The crates for the honest version exist — joshi-wallet-source (read-only leased
acquisition planning), joshi-sources (the actual RPC client), joshi-accounting (pure, no-I/O
lot-basis and episode projections), joshi-wallet-admission (receipt-gated admission to the
store) — and nothing wires Ember's actual wallet through them to a screen.

**What it costs.** This morning, concretely: a hand-composed sweep, inline decoding, and a
result that lives in a terminal scrollback. Every future morning pays it again, with fresh
opportunity for transcription error, and the accounting requirement SESSION_HISTORY names
("exact wallet accounting … legitimate foundations") stays unmet. The watch set for gap 2 also
has no authoritative source without this.

**Smallest honest fix.** Stage 1: a `wallet-readout` in the venue_readout idiom — token
accounts and balances at a finalized slot, state age carried, mark from the existing venue
math where a venue is decodable, "no mark" stated where it is not. Stage 2: a per-wallet GET
route + a glass rail, same shape as `/api/v1/glass/venue-readouts/{mint}`. Cost basis and PnL
are stage 3 and honestly need her trade history admitted through the existing backfill +
wallet-admission path — do not fake them from current balances.

**Builds on.** All four crates above; the trades-backfill binary; the venue-readouts route
pattern.

**Size.** Days for stages 1–2. A week-plus for basis/PnL done honestly. Do not let stage 3
block stages 1–2.

### 4. Nothing outlives a terminal — no persistent service, no refreshing scene

**What it is.** Everything runs ad hoc in a foreground terminal: core is
`./target/debug/joshi-core live-surface-inspect …`, glass is `pnpm dev`, the readout is
`cargo run --example venue_readout`. The served scene is derived **once** and served
byte-for-byte until remount — the glass data client has no polling, and V1 deliberately has no
stream route ("reconnect ordering/digest binding is not frozen," service.rs). Close a laptop
lid and JOSHI ceases to exist.

**What it costs.** A cockpit that is only alive while a terminal is attended cannot be where
mornings begin — the morning starts with ritual re-launching instead of with the market. It
also blocks gaps 2 and 7 outright: a watcher and a tape recorder are only real if they run
while she sleeps.

**Smallest honest fix.** launchd plists (or one supervised tmux session, documented) for core
and the watcher/recorder, with state dirs, logs, and restart-on-crash. In glass: re-fetch the
snapshot on an honest cadence, keeping scene-id lineage so any act still binds to the exact
bytes on screen — the hold rail already survives a feed that stops carrying a coin, so the
hard rendering problem is solved. Respect the no-stream decision; polling is enough for a
daily life.

**Builds on.** The existing binaries; the scene-id/act-binding discipline already in place;
macOS launchd. No new code beyond the glass cadence.

**Size.** A day or two. Disproportionate leverage: three other gaps are gated on it.

### 5. Discovery lives in a terminal — candidate finder is a CLI, not a board

**What it is.** `joshi-pump-candidates` works and was measured live (+274%, −96%, +63% over a
92-second window) — and its slate prints to stdout and dies. The AttentionFeed renders
candidates from the derived scene; the finder's output never reaches it. The crackle counter
(`joshi-pump-crackle`), product-read, and backfill are the same shape: real instruments, no
surface.

**What it costs.** Phase 3's whole point — "find coins inside JOSHI" — is unmet, so discovery
still happens on pump.fun, which means her selection scene is still unrecorded, which is the
exact "residual and biased attention data" failure SESSION_HISTORY's requirement 3 warns
about. The deputy line in GOAL.md says it plainly: there is no record of which coins she
looked at.

**Smallest honest fix.** The finder writes its slate durably; scene derivation includes it as
a board (AttentionFeed already has board filters); each row carries its window, its refusal
counts, and "not a volume of zero" annotations exactly as the CLI prints them. The crackle
counter becomes a per-mint panel beside the venue readout for held coins.

**Builds on.** The finder and its row-projection gate; scene derivation from store rows;
AttentionFeed boards; the venue-readouts per-mint route pattern.

**Size.** Days. Candidates-to-board first; crackle panel second.

### 6. Venue positions and resting orders are off the books

**What it is.** The LP position analyzed this morning with ad-hoc DuckDB has no JOSHI
representation. Limit orders live on the venue with no JOSHI awareness of their existence,
let alone their fills. Zero hits for any of it in the tree.

**What it costs.** Positions are exactly the things a morning checks first, and today each
check is a bespoke analysis. A fill she doesn't notice is state she doesn't have; an LP band
the price walked out of is inventory silently converting. SESSION_HISTORY's steer 7 (LP as
inventory management) cannot even begin without the read.

**Smallest honest fix.** Read-only decode of her LP position accounts (getMultipleAccounts at
a finalized slot, same idiom as the pool decoder), rendered as band vs. current mark with
state age. Fills and order awareness are then a watch-set entry for gap 2's pager, not a new
system. Exchange-side resting orders wait for the quarter (see gap 9).

**Builds on.** The venue decoder discipline in joshi-sources (which just learned, expensively,
how to decode a pool honestly); the wallet readout of gap 3 (positions are holdings); gap 2's
watcher.

**Size.** Days for the LP read; fills-awareness comes almost free once gap 2 exists.

### 7. The live tape and the callout clock are built but not living

**What it is.** The event-resolution tape recorder exists as
`crates/joshi-sources/examples/coin_tape_live.rs` and has only been exercised on a night the
machine's load average was 77–94 (the same load that produced the phantom Glass failures).
Callout capture retains occurrence time (`createdAt`) but nothing records an **availability
time** — when the callout became visible to us — and GOAL.md is explicit that a callout is a
clean t=0 only with both.

**What it costs.** The science that answers Ember's own entry-window question is blocked on
bytes we are not retaining. The corpus finding is stark — 57.7% of no-drawdown-on-candles
coins had a real dip at event resolution — and remains a finding about a BigQuery export until
the instrument she would actually use has run on bytes we captured ourselves.

**Smallest honest fix.** Stamp first-seen receipt time on every callout capture (an honest
lower bound on availability, labeled as such — never backfilled). Run the tape recorder and
the callout poller on the quiet machine, under gap 4's supervision, for a week. This is mostly
"turn it on and leave it on."

**Builds on.** coin_tape_live.rs, pumpportal.rs, the callout routes already read live, the
capture path exercised at slot 440866559, joshi-supervisor.

**Size.** Hours to stamp and start; the persistence it rides on is gap 4.

### 8. The morning has no page, and conclusions evaporate

**What it is.** There is no journal/exocortex surface: what was concluded this morning (the LP
analysis, the wallet sweep, the SOLVE regret) lives in a terminal scrollback and an agent's
context window. A sibling deputy is designing the journal/exocortex; this document defers to
that design and does not duplicate it.

**What it costs.** GOAL.md itself is currently doing the journal's job by hand — a human and
an agent maintaining a findings file because no surface remembers. Every re-derivation of a
known fact (the fee-tier lesson, the stale-reserve trap) is a tax paid by whoever forgot.

**What to say here, without duplicating.** The morning page is mostly **composition**: holdings
(gap 3) + overnight alerts (gap 2) + the candidate board (gap 5) + positions (gap 6) + world
signals (gap 9) + yesterday's conclusions (the sibling's journal). If the sibling's design
lands a place to write, the gaps above supply what it reads on wake.

**Size.** Owned by the sibling lane; the composition itself is days once components exist.

### 9. The world-signal lane lives entirely outside JOSHI

**What it is.** Yuè's polymarket work is real and running: `~/kimi_state/tools/polywatch.py`
(219 lines, stdlib-only Python against the no-auth gamma API) with scan/search/board/watch/
digest subcommands, a ~94-board watchlist, snapshot differencing for movers ≥3 points, and a
sports filter — deployed in Yuè's background container, scheduled by hand ("the scheduler is
me"). Separately: Ember missed the SOL-upgrade catalyst trade she had the impulse to take
(sold into USDC pre-upgrade; named an unforced error), and Yuè already found the next one
(Alpenglow mainnet, Sep 28) and offered to wire a catalyst calendar. Coinbase has an MCP; ETH
markets interest her; memecoins are the start, not the boundary.

**What it costs.** Trades she had the impulse to take passed with no surface watching them,
and the instrument that would have paged her exists — on someone else's machine, on a manual
clock.

**What integrating the direction honestly takes.**
- **Hours**: run polywatch (or a copy) on Ember's own machine under launchd; its digest text
  lands where the morning begins (gap 8's page, or a dated file until that exists). The
  movers-digest idiom is the same snapshot-differencing as joshi-pump-candidates — this is a
  culture match, not a foreign body.
- **Days**: a catalyst calendar is a list of dates with sources; rendering "what is dated and
  near" on the morning page is trivial and is the cheapest watch in this whole document.
- **Weeks, and only if warranted**: full JOSHI admission (retained frames, row gates, receipts)
  for polymarket bytes. Do this only when a polymarket position becomes real; doing it first
  would repeat the ceremony failure mode.
- Carry Yuè's own findings with the feed, not just the feed: on thin boards volume can be pure
  noise (the Ethiopia board), and favorite-longshot bias means cheap tails are systematically
  overpriced — the digest should keep saying so.
- **Coinbase MCP / ETH**: the agent sitting with her in the morning can query it read-only
  today with zero JOSHI code. Retention of what was read follows the same "admit when real"
  rule. This quarter, not this week.

**Size.** Hours for the glue; the boundary-drawing above is the actual work.

### 10. The cockpit's focus structure taxes the hands it was built to spare

**What it is.** Known and stated in the runbook: 51 focusable stops at first paint, mutating
as the virtualized feed scrolls. The structural answer (a listbox with `aria-activedescendant`
— one tab stop, and readers drop into focus mode so letter keys pass through) is specified and
unbuilt.

**What it costs.** Runbook row 8 — hands — "outranks the seven above," and this is the row 8
item. Every session spent tabbing through 51 mutating stops is the founding injury re-incurred
inside the tool built to prevent it. Living in JOSHI daily multiplies this cost by every day.

**Smallest honest fix.** The restructure itself; there is no honest smaller version, which is
why it ranks below cheaper fixes despite the cost. Do it as its own lane with the S2
measurement session as its gate, findings written during the session per the runbook.

**Builds on.** The runbook's own spec; the existing shortcut discipline (the `;` non-letter
lesson).

**Size.** One to two weeks, properly.

### Paper cut, noted not ranked

Daily tools run as debug builds and cargo examples (`target/debug/…`,
`cargo run -p joshi-sources --example venue_readout`). When a tool graduates to daily life,
give it a release build and a name on PATH. An hour, once, per tool.

## This week / this month / this quarter

**This week** (all read-only, all building on live code):
1. Hold read-back route + rail hydration (gap 1) — hours.
2. Wallet holdings readout, CLI then route (gap 3, stages 1–2) — days.
3. launchd persistence for core + one watcher/recorder; glass snapshot cadence (gap 4) — 1–2 days.
4. Standing watch v1 on held ∪ holdings, alerts durable and announced (gap 2) — days.
5. Start the tape recorder and callout poller with first-seen stamping, and leave them
   running (gap 7) — hours once 3 exists.

**This month:**
- Candidate slates into the AttentionFeed as a board; crackle counter as a per-mint panel (gap 5).
- LP position readout; fills-awareness via the watcher (gap 6).
- Cost basis / PnL from admitted trade history (gap 3 stage 3).
- polywatch digest + catalyst calendar landing on the morning page; journal composition with
  the sibling deputy's design (gaps 8, 9).
- The listbox restructure, gated by a real S2 session (gap 10).

**This quarter:**
- Exchange-side order/fill awareness; Coinbase MCP read-only lane formalized if ETH positions
  become real (gaps 6, 9).
- Callout-aligned live entry-window study on self-retained bytes (the science gap 7 unblocks).
- Full-ceremony admission for any world-signal source that has earned it by then.

## The three I would do first

1. **Hold read-back (gap 1).** Hours of work that repairs the core promise. A retention
   machine that forgets on reload cannot be lived in; after this, what she holds is what the
   rail shows, every morning, unconditionally.

2. **Wallet holdings readout (gap 3, stages 1–2).** Turns this morning's hand-composed sweep
   into one command and then one rail. It is also the authoritative watch set — without it,
   the watcher watches a guess.

3. **Standing watch v1 under launchd (gaps 2 + 4 together).** The SOLVE spike is the largest
   named dollar cost, and the fix drags the persistence gap closed as a side effect, which
   unblocks the tape recorder and the callout clock the same week. After these three, JOSHI
   knows what she holds, never forgets what she marked, and taps her on the shoulder when
   something she owns moves — which is most of what "living there" means.

## What this document deliberately does not propose

Per SESSION_HISTORY.md's failure record: no new type ceremony (the six corpus types are a
science question, not a prerequisite for a portfolio rail); no fixture-only development (every
fix above terminates in a live exercise against her real wallet, real holds, real feeds); no
taxonomy before acts (the watcher pages attention, it does not classify moves; the hold stays
one unclassified keystroke). No execution authority anywhere: everything here reads, retains,
and announces. The machine reacts after her decision; these gaps are about making sure it is
awake, remembers, and can be lived with.
