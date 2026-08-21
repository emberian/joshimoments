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

## Not yet true, and this is the honest gap

`wave5-g0-inspect` serves the **offline G0 fixture**, not the S1 census. Reading "a real number
about a real coin" needs the S1 rendered surface mounted behind that same pairing path. That is the
last wiring step and it is tracked in `GOAL.md`.

Until it lands, running the commands below exercises the *accessibility* half against fixture
content. That is still worth doing — every finding about focus order, reflow, contrast and screen
reader behaviour is real regardless of whose numbers are on the screen — but it does **not** close
S2, because the slice requires a real observation to be what is read.

## The commands

Two terminals.

```sh
# 1. serve, on loopback only
cd ~/dev/joshi
./target/debug/joshi-core wave5-g0-inspect \
  --state /tmp/joshi-s2 \
  --listen 127.0.0.1:43219 \
  --glass-origin http://127.0.0.1:4173
# it prints the one-time pairing code; keep the terminal visible

# 2. the cockpit
cd ~/dev/joshi/apps/glass
pnpm dev:g0-inspect --port 4173
```

Then open `http://127.0.0.1:4173`, enter the code from terminal 1.

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

## Recording the occurrence

Write findings to `state/s2/<date>-session.md` as they happen, during the session rather than
after. Include what was wrong, verbatim, including anything embarrassing. Then it becomes a durable
occurrence rather than a memory.

Row 8 is the one that matters most and is the easiest to skip. The whole project exists because the
existing interfaces hurt to use. If the cockpit also hurts, that is the single most important
finding S2 can produce, and it should stop the slice rather than be noted and moved past.
