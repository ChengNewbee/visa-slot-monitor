#!/bin/zsh
set -euo pipefail

label="com.csy.visa-slot-monitor"
agent_path="${HOME}/Library/LaunchAgents/${label}.plist"
launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true
if [[ -f "${agent_path}" ]]; then
  mv "${agent_path}" "${agent_path}.disabled"
fi
echo "Stopped ${label}; the disabled plist is kept at ${agent_path}.disabled"

