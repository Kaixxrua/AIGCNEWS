#!/usr/bin/env bash
# Stage user units only. Runtime activation and legacy drain belong to coordinator.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
unit_root=${XDG_CONFIG_HOME:-"$HOME/.config"}/systemd/user
install_root=${AIGCNEWS_AUTOSCALER_INSTALL_ROOT:-"$HOME/.local/lib/aigcnews-ci-autoscaler"}
if [[ "$install_root" != "$HOME/.local/lib/aigcnews-ci-autoscaler" ]]; then
  echo "Pool unit requires the canonical user install path" >&2; exit 1
fi
if [[ $(systemctl --user is-active aigcnews-ci-autoscaler.service || true) == active ]]; then
  echo "Coordinator must pause/drain and stop autoscaler before staging activation dependencies" >&2; exit 1
fi
mkdir -p "$unit_root/aigcnews-ci-autoscaler.service.d" "$install_root"
install -m 0755 "$root/scripts/ci/ephemeral_runner_autoscaler.py" "$install_root/autoscaler.py"
for module in ephemeral_runner_autoscaler runner_pool_owner runner_resource_budget shared_runner_pool runner_workloads runner_pool_receipts check_shared_runner_pool review_pool_recovery; do
  install -m 0644 "$root/scripts/ci/$module.py" "$install_root/$module.py"
done
cat > "$unit_root/aigcnews-ci-autoscaler.service" <<'UNIT'
[Unit]
Description=AIGCNEWS verified shared CI scheduler
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
EnvironmentFile=%h/.config/aigcnews/ci-autoscaler.env
ExecStart=/usr/bin/python3 %h/.local/lib/aigcnews-ci-autoscaler/autoscaler.py --apply --loop
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target
UNIT
install -m 0644 "$root/scripts/ci/aigcnews-ci-pool.service" "$unit_root/aigcnews-ci-pool.service"
cat > "$unit_root/aigcnews-ci-autoscaler.service.d/shared-pool.conf" <<'UNIT'
[Unit]
Requires=aigcnews-ci-pool.service
After=aigcnews-ci-pool.service
BindsTo=aigcnews-ci-pool.service
UNIT
systemd-analyze --user verify "$unit_root/aigcnews-ci-pool.service"
echo "Units staged only. No daemon reload, enable, start, linger or permission changes."
