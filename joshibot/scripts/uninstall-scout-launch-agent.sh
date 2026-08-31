#!/bin/sh
set -eu

label="com.shitcoims.scout"
target_plist="$HOME/Library/LaunchAgents/$label.plist"
domain="gui/$(id -u)"

launchctl bootout "$domain/$label" 2>/dev/null || true
if [ -f "$target_plist" ]; then
  mv "$target_plist" "$target_plist.disabled"
  echo "shitcoims Scout launch agent disabled at $target_plist.disabled"
else
  echo "shitcoims Scout launch agent was not installed"
fi
