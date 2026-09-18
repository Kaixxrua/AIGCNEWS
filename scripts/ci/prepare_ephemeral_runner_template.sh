#!/usr/bin/env bash
set -euo pipefail

source_container=${1:-aigcnews-ci}
template=${2:-aigcnews-ci-template}

if lxc info "$template" >/dev/null 2>&1; then
  echo "Refusing to replace existing LXD template $template" >&2
  exit 1
fi
if ! lxc info "$source_container" >/dev/null 2>&1; then
  echo "Source LXD container $source_container does not exist" >&2
  exit 1
fi

service=$(lxc exec "$source_container" -- cat /opt/actions-runner/.service)
if [[ ! "$service" =~ ^actions\.runner\.[A-Za-z0-9_.-]+\.service$ ]]; then
  echo "Unexpected source runner service name: $service" >&2
  exit 1
fi

# LXD's storage snapshot keeps the installed toolchain but no running state.
# Disable the cloned persistent identity before the clone is ever booted.
lxc copy "$source_container" "$template"
lxc config set "$template" boot.autostart false
lxc file delete "$template/etc/systemd/system/multi-user.target.wants/$service"
lxc start "$template"

lxc exec "$template" -- bash -s <<'SCRIPT'
set -euo pipefail
systemctl disable --now 'actions.runner.*.service' >/dev/null 2>&1 || true
find /etc/systemd/system -maxdepth 2 -name 'actions.runner.*.service*' -exec rm -rf {} +
rm -f /opt/actions-runner/.credentials \
  /opt/actions-runner/.credentials_rsaparams \
  /opt/actions-runner/.runner \
  /opt/actions-runner/.runner_migrated \
  /opt/actions-runner/.service
find /opt/actions-runner/_work -mindepth 1 -maxdepth 1 -exec rm -rf {} +
find /opt/actions-runner/_diag -mindepth 1 -maxdepth 1 -exec rm -rf {} +
systemctl stop docker.service docker.socket containerd.service || true
rm -rf /var/lib/docker/* /var/lib/containerd/*
# The persistent source runner uses a localhost registry cache. A clean JIT
# instance does not inherit that container, so it must pull through its own
# proxied Docker daemon instead of pointing at a dead loopback mirror.
printf '{}\n' > /etc/docker/daemon.json
apt-get clean
SCRIPT

cat <<'SCRIPT' | lxc file push -p - "$template/usr/local/sbin/aigcnews-run-ephemeral"
#!/usr/bin/env bash
set -euo pipefail
config=/run/aigcnews-jitconfig
if [[ ! -s "$config" ]]; then
  echo "JIT configuration is unavailable" >&2
  exit 1
fi
jit=$(cat "$config")
rm -f "$config"
exec runuser -u runner -- env \
  HOME=/home/runner \
  RUNNER_ALLOW_RUNASROOT=0 \
  /opt/actions-runner/run.sh --jitconfig "$jit"
SCRIPT
lxc exec "$template" -- chmod 0755 /usr/local/sbin/aigcnews-run-ephemeral

cat <<'UNIT' | lxc file push -p - "$template/etc/systemd/system/aigcnews-ephemeral-runner.service"
[Unit]
Description=AIGCNEWS one-job GitHub Actions JIT runner
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=oneshot
Environment="HTTP_PROXY=http://127.0.0.1:7895"
Environment="HTTPS_PROXY=http://127.0.0.1:7895"
Environment="ALL_PROXY=socks5h://127.0.0.1:7895"
Environment="NO_PROXY=localhost,127.0.0.1,::1"
Environment="http_proxy=http://127.0.0.1:7895"
Environment="https_proxy=http://127.0.0.1:7895"
Environment="all_proxy=socks5h://127.0.0.1:7895"
Environment="no_proxy=localhost,127.0.0.1,::1"
Environment="RUNNER_TOOL_CACHE=/opt/hostedtoolcache"
Environment="ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE=/opt/actions-runner/_action_archive_cache"
ExecStart=/usr/local/sbin/aigcnews-run-ephemeral
ExecStopPost=/usr/bin/systemctl poweroff
TimeoutStartSec=infinity

[Install]
WantedBy=multi-user.target
UNIT
lxc exec "$template" -- systemctl daemon-reload
lxc stop "$template" --timeout 120

echo "Prepared stopped LXD template $template from $source_container"
