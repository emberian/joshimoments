# Operator runbook

What Ember can actually run, as of 2026-08-22 02:00. Everything here was exercised tonight against
live data unless it says otherwise.

S2 — one attended browser session with a screen reader and a keyboard — is still the slice nobody
can do for her, and it is still the point. The tools below exist to make that session worth having.

## The one command that matters

```sh
cd ~/dev/joshi
./target/debug/joshi-core live-surface-inspect \
  --catalog <dir containing catalog.sqlite> \
  --state   /tmp/joshi-s2 \
  --listen  127.0.0.1:43219 \
  --glass-origin http://127.0.0.1:4173
```

It backs the real catalog into an overlay (so a sibling writer is undisturbed and the catalog is
never written), derives one Glass scene **from store rows**, mounts durable ordinary pairing, and
prints three things: the scene id, the two `VITE_` values Glass needs, and a one-time pairing code
scoped to cockpit read and operator evidence, with no signing or execution.

```sh
cd ~/dev/joshi/apps/glass
VITE_JOSHI_LIVE_SURFACE=1 VITE_JOSHI_CORE_URL=... VITE_JOSHI_LAUNCH_SCENE_ID=... pnpm dev --port 4173
```

`live-gesture-walk`, same arguments, runs the whole loop headless — mount, pair, snapshot, mark a
real mint, drop everything, reopen read-only, prove the digests match — if you want to know the path
works before spending your own attention on it.

### Press `;` to hold a coin

One key, no modifier, no confirm. It is deliberately **not a letter**: six of the eight existing
single-letter shortcuts collide with NVDA and JAWS browse-mode quick navigation, which eat them
before the page sees them. Held coins go to a rail that is ordered by *when you held them*, so
nothing above a new hold ever moves, and they survive a feed refresh that no longer carries them —
the rail then says the feed stopped carrying it rather than dropping it.

The hold commits a durable operator act bound to the exact scene bytes on screen. Nothing is
classified at the moment of noticing: no dropdown, no required fields. Words go on afterwards.

**Known gap, stated on screen:** a hold already accepted is not read back after a reload, because
core serves no read route for operator commands yet.

## Finding something to hold

```sh
./target/debug/joshi-pump-candidates      # sweep, wait, sweep, join on mint, rank by |delta mcap|
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
./target/debug/joshi-collector census        # bounded Pump/PumpSwap census, with coverage and gaps
./target/debug/joshi-collector census-readback
./target/debug/joshi-pump-product-read --route candles --query interval=1s --query limit=1000 ...
./target/debug/joshi-pump-trades-backfill    # walk one mint's trade history backwards
./target/debug/joshi-pump-crackle --mint ... # excursions per hour above that venue's measured fee floor
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
| 1 | Screen reader announces the live regions, the feed, and a hold | Announced late, twice, out of order, or not at all |
| 2 | Keyboard-only throughout, no pointer at any moment | Any trap, any skipped control, anything reachable only by mouse |
| 3 | Focus order visible and correct | Invisible ring; order disagreeing with reading order |
| 4 | 200% zoom | Anything clipped, overlapped, unreachable |
| 5 | 320 CSS px reflow | Any horizontal scrollbar at all |
| 6 | Contrast on **rendered pixels**, not declared tokens | Any pair below its ratio; screenshot it |
| 7 | Crash, reload, re-pair | Whether the session recovers, and what it loses |
| 8 | **Hands** | Anything that hurt, or needed a precision movement. This outranks the seven above. |

Known before you start, and not yet fixed: the shell presents **51 focusable stops** at first paint
before the virtualized feed adds one per row, and those stops **mutate as you scroll**. The
structural answer is a listbox with `aria-activedescendant`, which is one tab stop and also forces
readers into focus mode so letter keys pass through. It is a real restructure and has its own lane.

Write findings to `state/s2/<date>-session.md` during the session rather than after, including
anything embarrassing. Row 8 is the one the whole project was founded on and the easiest to skip.
