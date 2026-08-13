#!/bin/sh
set -eu

label="com.shitcoims.sentinel"
target_plist="$HOME/Library/LaunchAgents/$label.plist"
domain="gui/$(id -u)"

launchctl bootout "$domain/$label" 2>/dev/null || true
if [ -f "$target_plist" ]; then
  mv "$target_plist" "$target_plist.disabled"
fi
echo "shitcoims Sentinel stopped; the disabled plist remains recoverable."

