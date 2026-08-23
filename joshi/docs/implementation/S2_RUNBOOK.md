# Operator runbook

What Ember can actually run, as of 2026-08-23 evening. Everything here was exercised against live
data unless it says otherwise.

S2 — one attended browser session — is still the slice nobody can do for her, and it is still the
point. The tools below exist to make that session worth having. (The operator model this file once
assumed was wrong: Ember is primarily visual and uses a pointer, with a screen reader sometimes.
The measurement table below reflects the corrected model.)

## The one command that matters

```sh
cd ~/dev/joshi
./target/release/joshi-up
```

Proven end to end on a cold start (2026-08-23): it starts the keeper (real bounded acquisition
into the durable catalog `ops/keeper.toml` names), waits honestly while a cold catalog warms
("surface cannot mount yet; retrying while the keeper advances the catalog" — a quiet coin's
first candle windows are legitimately empty), mounts the follow surface over it (the catalog is
backed into an overlay and never written), starts the Glass cockpit with the exact values the
core printed, and ends with the one thing that is genuinely yours to do:

```
JOSHI is up.

  cockpit   http://127.0.0.1:4173
  pairing   JOSHI-XXXX-....   (one-time; Cockpit read + operator evidence; no signing, no execution)
  feed      http://127.0.0.1:43219/api/v1/glass/scenes
  keeper    state/keeper/heartbeat.json
```

Open the cockpit, enter the code, sit down. Ctrl-C takes the whole session down in order, and the
keeper records its own shutdown reason durably. If any piece dies, the rest are taken down loudly —
a half-up session that looks up is the failure mode it refuses.

Worth knowing: `--no-keeper` mounts over a still catalog (nothing advances); a keeper already
running (launchd, another terminal) is detected by its fresh heartbeat and adopted rather than
doubled; `--source-id helius.http.solana.v1` follows wallet activity instead of prices; and each
sibling binary's build age is printed at startup, because a stale binary is the quietest way to
get an honestly-wrong catalog (learned the hard way, same night).

`joshi-core live-gesture-walk` still runs the whole gesture loop headless — mount, pair, snapshot,
mark a real mint, drop everything, reopen read-only, prove the digests match — if you want to know
the path works before spending your own attention on it.

### Press `;` to hold a coin

One key, no modifier, no confirm. It is deliberately **not a letter**: six of the eight existing
single-letter shortcuts collide with NVDA and JAWS browse-mode quick navigation, which eat them
before the page sees them. Held coins go to a rail that is ordered by *when you held them*, so
nothing above a new hold ever moves, and they survive a feed refresh that no longer carries them —
the rail then says the feed stopped carrying it rather than dropping it.

The hold commits a durable operator act bound to the exact scene bytes on screen. Nothing is
classified at the moment of noticing: no dropdown, no required fields. Words go on afterwards.

Holds and journal entries read back after a reload — the durable readback route landed 2026-08-22
and the journal replays acts verbatim after a restart. (An earlier version of this file named the
missing read route as a known gap; it is closed.)

## Finding something to hold

```sh
./target/release/joshi-pump-candidates      # sweep, wait, sweep, join on mint, rank by |delta mcap|
```

Differences two discovery sweeps. Measured live: a 92-second window over 58 persisting mints
produced a top slate of +274%, −96%, +63%, +40%, −27%. It is named a **candidate finder for human
attention**, not a signal and not an entry, and only pages a row projection promoted contribute rows
— refusals are counted and shouted, so a thin slate can never read as a quiet market.

## Deciding whether a coin is worth your attention

```sh
cargo run -p joshi-sources --example venue_readout -- \
  --mint <addr> --lift-bps 800 --clip-sol 0.25 --drift-window-seconds 30
```

One `getMultipleAccounts` at a finalized slot. Prints venue kind and how the address was bound, the
effective quote reserve with its composition, the fee rates **and their source**, the fee floor, and
the break-even clip **interval** for a stated lift.

**Read the fee floor before anything else.** Measured live on three real mints the same night:

| | fee floor | max clip at an 8% lift |
| --- | --- | --- |
| bonding curve | 247 bps | 0.81 SOL |
| graduated pool | 60 bps | 58.0 SOL |
| graduated pool, freshly | **249 bps** | **0.81 SOL** |

The third is the lesson. **"Graduated" predicts nothing.** Its 42.8 SOL market cap selects the fee
program's first tier row at 125 bps a leg — the same as a bonding curve. The lever is which tier row
the market cap selects, and the readout prints it.

Two things it will tell you that are easy to skim past. The break-even answer is an **interval**,
because below roughly 0.0003 SOL the network fee eats the trade. And where the two PumpSwap fee
tier tables disagree — they do, over a wide populated band, and no retained byte says which applies
— it takes the **worse** branch and marks it unreconstructed. It errs against the trade, never for
it.

**State age is bigger than any of the arithmetic.** Chain-to-receipt measured 11–13 seconds, mostly
the `finalized` commitment depth rather than slowness, and one pool drifted 9–10 bps in 30 seconds.
Its entire 60 bps fee floor is two to four minutes of drift. The readout carries its own age; do not
read a number without it.

## Retaining what you looked at

```sh
./target/release/joshi-collector census        # bounded Pump/PumpSwap census, with coverage and gaps
./target/release/joshi-collector census-readback
./target/release/joshi-pump-product-read --route candles --query interval=1s --query limit=1000 ...
./target/release/joshi-pump-trades-backfill    # walk one mint's trade history backwards
./target/release/joshi-pump-crackle --mint ... # excursions per hour above that venue's measured fee floor
```

## What you will see, so it is not a surprise

Charts will often be nearly empty, and that is correct rather than broken. **77.1% of coins have
three or fewer candles in their entire first hour.** More importantly, of 113,859 coins whose minute
candles showed no drawdown at all, **57.7% had one at event resolution**, median about −16.7%. The
dip you watch for after a callout is real and **a one-minute chart does not render it**. An
event-resolution tape is the only thing that can, and capturing one live is in flight.

If the screen ever shows a number the underlying bytes do not contain, that is the worst bug this
project can have and it outranks everything else here.

## The measurement session itself

Each row gets a verdict and a note; "pass" with no note is not a result.

| # | Measurement | What counts as a finding |
| --- | --- | --- |
| 1 | Visual scanning as the primary channel: can you read the feed at a glance, and is the active row's ring obvious? | Anything you had to hunt for, squint at, or re-find after a refresh |
| 2 | Pointer as an attention marker: hover marks a row (`pointed`), click selects, targets are full-row | Any target needing precision, any hover that hijacks selection, any pointer act that hurt |
| 3 | Keyboard paths complete as the equal second channel | Any trap, any skipped control, anything reachable only by mouse — or only by keyboard |
| 4 | Screen reader (when used) announces the live regions, the feed, and a hold | Announced late, twice, out of order, or not at all |
| 5 | Focus order visible and correct; 200% zoom; 320 CSS px reflow | Invisible ring; clipped or unreachable content; any horizontal scrollbar |
| 6 | Contrast on **rendered pixels**, not declared tokens | Any pair below its ratio; screenshot it |
| 7 | Crash, reload, re-pair (kill joshi-up mid-session and run it again) | Whether the session recovers, and what it loses |
| 8 | **Hands** | Anything that hurt, or needed a precision movement. This outranks the seven above. |

The feed's focus architecture was restructured 2026-08-23: it is now a single-tab-stop listbox
with `aria-activedescendant` (the active row is pinned into the virtualizer's mounted range so
the attribute can never dangle), the board filters are a roving-tabindex radiogroup, and the feed
panel contributes exactly two stops, invariant under scrolling — measured before at 74 fully
settled with row stops mutating on every scroll, after at 63. The active row keeps a strong
visible ring for eye-first reading; the listbox also forces readers into focus mode so letter
keys pass through. Roughly 61 stops elsewhere in the shell remain a future lane.

Write findings to `state/s2/<date>-session.md` during the session rather than after, including
anything embarrassing. Row 8 is the one the whole project was founded on and the easiest to skip.
