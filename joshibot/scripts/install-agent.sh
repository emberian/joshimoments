#!/bin/sh
# Install and (re)start any ops/*.plist by label. Idempotent: safe to re-run.
#
#   scripts/install-agent.sh com.shitcoims.cluster com.shitcoims.watchdog
#   scripts/install-agent.sh --all
#
# There were three near-identical install-*.sh scripts here, one per daemon, each a copy of
# the same bootout/wait/bootstrap/enable/kickstart dance. A fourth and fifth copy for the
# cluster recorder and the watchdog would have made the drift between them a certainty, so
# this takes the label instead. The wait loop matters: `launchctl bootstrap` fails with
# "service already loaded" if the old job has not finished unloading, which is how a
# reinstall silently leaves the OLD binary running.
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
target_dir="$HOME/Library/LaunchAgents"
domain="gui/$(id -u)"

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <label>... | --all" >&2
  exit 2
fi

if [ "$1" = "--all" ]; then
  set --
  for plist in "$repo_dir"/ops/*.plist; do
    label=$(basename "$plist" .plist)
    # The sentinel signs transactions. It is never installed by a bulk command.
    [ "$label" = "com.shitcoims.sentinel" ] && continue
    set -- "$@" "$label"
  done
fi

mkdir -p "$target_dir" "$repo_dir/state/logs"

for label in "$@"; do
  source_plist="$repo_dir/ops/$label.plist"
  if [ ! -f "$source_plist" ]; then
    echo "no such plist: $source_plist" >&2
    exit 1
  fi
  target_plist="$target_dir/$label.plist"
  install -m 600 "$source_plist" "$target_plist"
  launchctl bootout "$domain/$label" 2>/dev/null || true
  i=0
  while launchctl print "$domain/$label" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 50 ]; then
      echo "$label did not stop cleanly" >&2
      exit 1
    fi
    sleep 0.1
  done
  launchctl bootstrap "$domain" "$target_plist"
  launchctl enable "$domain/$label"
  # `kickstart`, NOT `kickstart -k`. The bootout above already stopped the old instance and
  # the loop above waited for it to go; a RunAtLoad job is therefore ALREADY running by now,
  # and `-k` would SIGTERM the process that bootstrap just started. On the cluster recorder,
  # which drains a full pass over every pool before exiting, that produced a successor racing
  # a predecessor for the tape lock and launchd throttling the pair into a crash loop.
  launchctl kickstart "$domain/$label"
  echo "installed and started $label"
done
