#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
label="com.shitcoims.scout"
source_plist="$repo_dir/ops/$label.plist"
target_dir="$HOME/Library/LaunchAgents"
target_plist="$target_dir/$label.plist"
domain="gui/$(id -u)"

cd "$repo_dir"
/opt/homebrew/bin/uv run python scout.py --check-ready
mkdir -p "$target_dir" "$repo_dir/intelligence_state"
chmod 700 "$repo_dir/intelligence_state"
install -m 600 "$source_plist" "$target_plist"
launchctl bootout "$domain/$label" 2>/dev/null || true
i=0
while launchctl print "$domain/$label" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 50 ]; then
    echo "existing shitcoims Scout did not stop cleanly" >&2
    exit 1
  fi
  sleep 0.1
done
launchctl bootstrap "$domain" "$target_plist"
launchctl enable "$domain/$label"
launchctl kickstart -k "$domain/$label"
echo "shitcoims Scout launch agent installed (read-only Telegram gateway)"
