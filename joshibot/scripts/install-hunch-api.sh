#!/bin/sh
# Install the hunch capture API as a launchd job.
#
# The glass's coin explorer talks to this. It reads the collectors' tapes and appends to
# state/hunches.jsonl; it holds no key, has no RPC client, and cannot reach the sentinel.
# Loopback only, port 8790 (8787 is the sentinel, 8788/8799 are intel.py).
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
label="com.shitcoims.hunch"
source_plist="$repo_dir/ops/$label.plist"
target_dir="$HOME/Library/LaunchAgents"
target_plist="$target_dir/$label.plist"
domain="gui/$(id -u)"

mkdir -p "$target_dir" "$repo_dir/state/logs"
install -m 600 "$source_plist" "$target_plist"
launchctl bootout "$domain/$label" 2>/dev/null || true
i=0
while launchctl print "$domain/$label" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 50 ]; then
    echo "existing hunch API did not stop cleanly" >&2
    exit 1
  fi
  sleep 0.1
done
launchctl bootstrap "$domain" "$target_plist"
launchctl enable "$domain/$label"
launchctl kickstart -k "$domain/$label"
echo "hunch API installed at http://127.0.0.1:8790 — the glass explorer proxies /hunch to it"
