#!/bin/sh
# Put every research collector under launchd supervision.
#
# Why this exists: on 2026-08-14 all three data sources were down at once and
# nobody noticed. inteld had a plist that was never bootstrapped, the board
# recorder was a `--minutes N` one-shot that simply ended, and the firehose had
# run for ten minutes. A study that needs a live tape cannot rely on someone
# remembering to restart a nohup.
#
# Idempotent: safe to re-run after editing a plist or the collector code.
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
target_dir="$HOME/Library/LaunchAgents"
domain="gui/$(id -u)"

mkdir -p "$target_dir" "$repo_dir/state/logs"

for label in com.shitcoims.inteld com.shitcoims.boards com.shitcoims.firehose; do
  source_plist="$repo_dir/ops/$label.plist"
  target_plist="$target_dir/$label.plist"
  [ -f "$source_plist" ] || { echo "missing $source_plist" >&2; exit 1; }
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
  # `enable` must precede `bootstrap`: a label sitting in launchd's disabled
  # override database makes bootstrap fail with a bare "Input/output error",
  # which is exactly how inteld ended up running unsupervised under nohup.
  launchctl enable "$domain/$label"
  launchctl bootstrap "$domain" "$target_plist"
  echo "supervised: $label"
done

launchctl list | grep shitcoims || true
