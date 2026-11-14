#!/usr/bin/env bash
# Stop MISTER PLIS and remove the auto-start agent.
LABEL="com.misterplis.server"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "Stopped." || echo "Was not running."
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
