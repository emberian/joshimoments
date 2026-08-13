#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
label="com.shitcoims.sentinel"
source_plist="$repo_dir/ops/$label.plist"
target_dir="$HOME/Library/LaunchAgents"
target_plist="$target_dir/$label.plist"
domain="gui/$(id -u)"

mkdir -p "$target_dir" "$repo_dir/state"
install -m 600 "$source_plist" "$target_plist"
launchctl bootout "$domain/$label" 2>/dev/null || true
i=0
while launchctl print "$domain/$label" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 50 ]; then
    echo "existing shitcoims Sentinel did not stop cleanly" >&2
    exit 1
  fi
  sleep 0.1
done
launchctl bootstrap "$domain" "$target_plist"
launchctl enable "$domain/$label"
launchctl kickstart -k "$domain/$label"
echo "shitcoims Sentinel installed at http://127.0.0.1:8787"
