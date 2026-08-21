# S2 runbook — one attached-browser session

Status: **staged, not run.** Everything below was verified to start and respond on 2026-08-21
except where it says otherwise. The human half of S2 cannot be performed by an agent and has not
been attempted.

S2 is a **measurement, not a demonstration.** Failures are the deliverable. A session where
everything worked and nothing was written down is worth less than a session that found four things
broken and recorded them exactly.

## What S2 asks for

Quoted from `PILLARS.md`: *Ember opens the cockpit on an ordinary morning, with her screen reader
on and her hands on the keyboard, reads a real number about a real coin, and marks it — and that
session exists as a recorded occurrence with its exact findings, including everything that was
wrong.*

## Verified working as of 2026-08-21

- `joshi-core wave5-g0-inspect` starts, mounts durable ordinary pairing, and prints a
  human-checkable one-time code of the form
  `JOSHI-8Q7X-ZQ1P-R7EZ-96GQ-SG6T-7YNR-T7PF-QGN5`, scoped to *Cockpit read + presentation
  evidence, no signing or execution*.
- `GET /api/v1/health` responds `{"contract":"joshi.core.health","authority":"read_only_no_execution"}`.
- `apps/glass` is built (`dist/` present), `node_modules` installed, node v26.4.0, pnpm 11.9.0.

## The gap closed on 2026-08-21: it now serves real data

`live-surface-inspect` derives a Glass scene **from real store rows** and mounts it behind the same
ordinary-pairing path. It backs the real catalog into an overlay first, so a sibling writer is
undisturbed and the catalog you point at is never written.

**One caveat before you run it:** `joshi-core` currently has 12 failing tests, a cross-lane
regression from the parallel slice work, and a repair is in flight. The command below is what the
lane exercised live — health 200, unpaired snapshot correctly 403, restart digest equality proven —
but it has not been re-verified against a green crate. If it misbehaves, that is the likely reason,
and it is not a finding about the cockpit.

## The commands

Two terminals.

```sh
# 1. serve a REAL catalog, loopback only
cd ~/dev/joshi
./target/debug/joshi-core live-surface-inspect \
  --catalog /private/tmp/claude-501/-Users-you-dev-joshi/b8d6cc61-e1ee-4422-9ce0-f6a213c381f9/scratchpad/census-v6 \
  --state /tmp/joshi-s2 \
  --listen 127.0.0.1:43219 \
  --glass-origin http://127.0.0.1:4173
```

It prints three things you need — keep the terminal visible:

```
live surface mounted from <catalog>: scene scene-live-<digest>
Glass needs: VITE_JOSHI_CORE_URL=http://127.0.0.1:43219 VITE_JOSHI_LAUNCH_SCENE_ID=scene-live-<digest>
one-time pairing code (Cockpit read + operator evidence; no signing or execution): JOSHI-...
```

```sh
# 2. the cockpit, in live-surface mode, using the two values it just printed
cd ~/dev/joshi/apps/glass
VITE_JOSHI_LIVE_SURFACE=1 \
VITE_JOSHI_CORE_URL=http://127.0.0.1:43219 \
VITE_JOSHI_LAUNCH_SCENE_ID=<the scene id> \
pnpm dev --port 4173
```

Then open `http://127.0.0.1:4173`, enter the code from terminal 1.

`live-gesture-walk`, with the same arguments, runs the whole thing headless: mount, pair, snapshot,
mark a real mint, drop everything, reopen read-only, and prove the digests match. Useful if you want
to know the path works before you spend your own attention on it.

## What you will actually see, so it is not a surprise

Mostly nulls, and that is correct. Every `getTransaction` in the current cut is a **failed**
transaction, so there is no fill, no size and no price in those bytes. `priceSol`, `marketCapUsd`
and `change5mBps` are null, `symbol` reads `unobserved`, `finality` reads `unstated`, and the price
chart says no price series was observed rather than drawing anything.

The mints are real. The emptiness is real too. If the screen ever shows a number those bytes do not
contain, that is the most important bug this project can have and it outranks every row in the
table below.

The code is single-use, rate-limited, expiring, and revocable, and it carries no signing, wallet,
transaction or execution scope. If it is refused, that refusal is a finding worth recording.

## What to measure

Each row gets a verdict and a note. "Pass" with no note is not a result.

| # | Measurement | What counts as a finding |
| --- | --- | --- |
| 1 | Screen reader announces the live regions and the feed | Anything announced late, twice, out of order, or not at all |
| 2 | Keyboard-only traversal, no pointer at any moment | Any trap, any skipped control, any action reachable only by mouse |
| 3 | Focus order is visible and correct | Invisible focus ring, focus order that disagrees with reading order |
| 4 | 200% zoom | Anything clipped, overlapped or unreachable |
| 5 | 320 CSS px reflow | Any horizontal scrollbar at all |
| 6 | Contrast measured on **rendered pixels**, not declared tokens | Any pair below its WCAG ratio; screenshot it |
| 7 | Crash, reload, re-pair | Whether the session recovers, and what it loses |
| 8 | Hands | Anything that hurt, or that needed a precision movement. This is the originating requirement and it outranks the rest of the table. |

## Six findings already banked, from the lane that built this

These are S2 evidence discovered while wiring the path. Confirm or refute them in your session.

1. `LoopbackDataSource` sent **no pairing token**, so the ordinary cockpit could never have read a
   paired core at all. Fixed. This is why nobody had ever seen live data in Glass.
2. `GlassApp` rendered **nothing** for a loopback source; live data hit "Publication is incomplete."
   Fixed.
3. `MarketChart` claimed `"{n} fixture bars · 30-second interval"` for every candidate, which is
   false on live data and on an empty series. Fixed.
4. `App.tsx` hardcodes `useState("radon")`, a fixture ID, as the initial selection in production
   code. It self-repairs one render later, so for one frame the selected candidate does not exist.
   **Not fixed** — worth a look.
5. A keyboard mark is written to IndexedDB **before** it is POSTed. Where IndexedDB is unavailable
   (private window, blocked storage) the mark never reaches the store and surfaces only as a local
   journal error. Deliberate retention-first design, but it is a single point of failure between
   your keypress and the store.
6. Pairing needs a 45-character grouped code typed per session. Keyboard reachable and correctly
   labelled, but ergonomically heavy — which is row 8 territory.

## Recording the occurrence

Write findings to `state/s2/<date>-session.md` as they happen, during the session rather than
after. Include what was wrong, verbatim, including anything embarrassing. Then it becomes a durable
occurrence rather than a memory.

Row 8 is the one that matters most and is the easiest to skip. The whole project exists because the
existing interfaces hurt to use. If the cockpit also hurts, that is the single most important
finding S2 can produce, and it should stop the slice rather than be noted and moved past.
