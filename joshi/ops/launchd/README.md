# Running the JOSHI keeper under launchd

The keeper is `joshi-collector keeper`: a long-running loop of bounded acquisition cycles that
keeps one durable catalog alive (candles/trades for the watched mints, plus the wallet sweep).
It edits nothing and submits nothing; it reads, retains, and writes down every gap.

Config lives at `ops/keeper.toml` and is re-read every tick, so editing the watch set does not
need a restart. All keeper state lives under `state/keeper/`:

- `state/keeper/catalog/` — the durable catalog (SQLite + blobs). The keeper is its only writer.
- `state/keeper/heartbeat.json` — rewritten every tick; the answer to "is the keeper alive and
  when did it last land data". `lastCycle.taps[].commitSeq` is where data last landed.
- `state/keeper/keeper.log` — bounded (4 MiB, one rotated `.log.old` generation).

## Install

```sh
cd ~/dev/joshi
cargo build --release -p joshi-collector
mkdir -p state/keeper
cp ops/launchd/software.ember.joshi.keeper.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/software.ember.joshi.keeper.plist
```

## Check on it

```sh
launchctl print gui/$UID/software.ember.joshi.keeper | head -20   # is launchd running it
cat state/keeper/heartbeat.json                                   # is it alive, what landed last
tail -40 state/keeper/keeper.log                                  # what the cycles did
```

A healthy heartbeat has a recent `lastWriteAt` (it advances every tick, ~30s) and a `state` of
`running`, `backoff` (provider throttled us; it says until when), or `day_budget_idle` (the
per-day request budget is spent; it resumes at UTC midnight). A stale `lastWriteAt` with launchd
still claiming the job means something is wrong — read `keeper.log` and `launchd.err.log`.

## Restart / apply a new build

```sh
launchctl kickstart -k gui/$UID/software.ember.joshi.keeper
```

(SIGTERM is clean: the keeper finishes the tap it is on, commits its cycle closure, writes a
shutdown heartbeat, and exits. A hard kill is also safe — every catalog commit is atomic — it
only loses the last heartbeat update.)

## Uninstall

```sh
launchctl bootout gui/$UID/software.ember.joshi.keeper
rm ~/Library/LaunchAgents/software.ember.joshi.keeper.plist
```

The catalog under `state/keeper/` is yours; uninstalling the agent does not touch it.

## Bounded proof run (no launchd)

```sh
cargo run --release -p joshi-collector -- keeper --config ops/keeper.toml --max-cycles 3
```
