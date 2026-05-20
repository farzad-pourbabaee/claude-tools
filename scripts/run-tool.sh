#!/usr/bin/env bash
# Generic dispatcher: forward "$1 ..." to the claude-tools Python CLI.
# Prefers a `uv tool install`-installed `claude-tools` on PATH; falls back to
# `uv run --project` so a fresh-clone machine works even before bootstrap.

set -euo pipefail

if command -v claude-tools >/dev/null 2>&1; then
  exec claude-tools "$@"
elif [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
  exec uv run --project "${CLAUDE_PLUGIN_ROOT}" claude-tools "$@"
else
  echo "claude-tools not on PATH and CLAUDE_PLUGIN_ROOT not set; run bootstrap.sh first." >&2
  exit 127
fi
