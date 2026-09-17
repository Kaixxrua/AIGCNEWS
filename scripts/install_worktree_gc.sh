#!/usr/bin/env bash
set -euo pipefail

root=$(git rev-parse --show-toplevel)
install -d -m 0755 "$HOME/.local/lib/aigcnews" "$HOME/.config/systemd/user"
install -m 0755 "$root/scripts/worktree_gc.py" "$HOME/.local/lib/aigcnews/worktree_gc.py"
install -m 0644 \
  "$root/deploy/systemd/aigcnews-worktree-gc.service" \
  "$root/deploy/systemd/aigcnews-worktree-gc.timer" \
  "$HOME/.config/systemd/user/"

systemctl --user daemon-reload
systemctl --user enable --now aigcnews-worktree-gc.timer
systemctl --user start aigcnews-worktree-gc.service
systemctl --user status aigcnews-worktree-gc.timer --no-pager
