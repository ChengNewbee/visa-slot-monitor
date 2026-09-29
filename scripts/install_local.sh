#!/bin/zsh
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
agent_dir="${HOME}/Library/LaunchAgents"
agent_path="${agent_dir}/com.csy.visa-slot-monitor.plist"
label="com.csy.visa-slot-monitor"
python_bin="$(command -v python3.11)"

cd "${project_dir}"

mkdir -p "${agent_dir}"
sed \
  -e "s#__PYTHON__#${python_bin}#g" \
  -e "s#__PROJECT__#${project_dir}#g" \
  launchd/com.csy.visa-slot-monitor.plist.template > "${agent_path}"

launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${agent_path}"
launchctl enable "gui/$(id -u)/${label}"

echo "Installed and started ${label}"
echo "Logs: ${project_dir}/watch.log and ${project_dir}/watch.err.log"
