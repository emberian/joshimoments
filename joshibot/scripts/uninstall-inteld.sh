#!/bin/sh
set -eu

label="com.shitcoims.inteld"
target_plist="$HOME/Library/LaunchAgents/$label.plist"
domain="gui/$(id -u)"

launchctl bootout "$domain/$label" 2>/dev/null || true
if [ -f "$target_plist" ]; then
  launchctl bootout "$domain" "$target_plist" 2>/dev/null || true
  rm -f "$target_plist"
fi
echo "shitcoims intelligence launch agent removed; local intelligence data was preserved"
