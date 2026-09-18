#!/usr/bin/env bash
set -euo pipefail

root=$(git rev-parse --show-toplevel)
install_root=${AIGCNEWS_AUTOSCALER_INSTALL_ROOT:-"$HOME/.local/lib/aigcnews-ci-autoscaler"}
unit_root=${XDG_CONFIG_HOME:-"$HOME/.config"}/systemd/user
env_file=${AIGCNEWS_AUTOSCALER_ENV_FILE:-"$HOME/.config/aigcnews/ci-autoscaler.env"}

if [[ ! -s "$env_file" ]]; then
  echo "Create mode-0600 $env_file with GH_TOKEN before installation" >&2
  exit 1
fi
mode=$(stat -c '%a' "$env_file")
if [[ "$mode" != "600" ]]; then
  echo "$env_file must use mode 600 (found $mode)" >&2
  exit 1
fi
if ! lxc info "${AIGCNEWS_RUNNER_TEMPLATE:-aigcnews-ci-template}" >/dev/null 2>&1; then
  echo "LXD runner template is unavailable; run prepare_ephemeral_runner_template.sh" >&2
  exit 1
fi

mkdir -p "$install_root" "$unit_root"
install -m 0755 "$root/scripts/ci/ephemeral_runner_autoscaler.py" "$install_root/autoscaler.py"
cat > "$unit_root/aigcnews-ci-autoscaler.service" <<UNIT
[Unit]
Description=AIGCNEWS ephemeral CI runner autoscaler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$env_file
ExecStart=/usr/bin/python3 $install_root/autoscaler.py --apply --loop
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now aigcnews-ci-autoscaler.service
systemctl --user --no-pager status aigcnews-ci-autoscaler.service
