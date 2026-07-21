#!/usr/bin/env bash
set -euo pipefail

payload=$(cat)
command=$(jq -r '.tool_input.command // ""' <<<"$payload")

# PostToolUse only invokes this after Bash succeeds. Ignore Bash calls that did
# not create a commit, and allow an explicit one-shot opt-out.
if ! grep -Eq '(^|[;&|][[:space:]]*|[[:space:]])git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+commit([[:space:]]|$)' <<<"$command"; then
  exit 0
fi
if [[ "$command" == *"AIGCNEWS_SKIP_AUTO_PUSH=1"* ]] || [[ "${AIGCNEWS_SKIP_AUTO_PUSH:-}" == "1" ]]; then
  printf '{"systemMessage":"AIGCNEWS auto-push skipped by AIGCNEWS_SKIP_AUTO_PUSH=1."}\n'
  exit 0
fi

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || {
  printf '{"systemMessage":"AIGCNEWS auto-push skipped: not inside a Git repository."}\n'
  exit 0
}
cd "$repo_root"

branch=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)
if [[ -z "$branch" ]]; then
  printf '{"systemMessage":"AIGCNEWS auto-push skipped: detached HEAD."}\n'
  exit 0
fi
if [[ "$branch" == "main" || "$branch" == "master" ]]; then
  printf '{"systemMessage":"AIGCNEWS auto-push blocked on default branch: %s."}\n' "$branch"
  exit 0
fi
if ! git remote get-url origin >/dev/null 2>&1; then
  printf '{"systemMessage":"AIGCNEWS auto-push skipped: origin remote is not configured."}\n'
  exit 0
fi

if git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' >/dev/null 2>&1; then
  git push
else
  git push -u origin HEAD
fi

printf '{"systemMessage":"AIGCNEWS auto-push succeeded for branch %s."}\n' "$branch"
