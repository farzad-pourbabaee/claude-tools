#!/usr/bin/env bash
# Idempotent installer for the claude-tools plugin + Python CLI.
# Run from anywhere; uses script-relative paths.
# Re-run after `git pull` to pick up new tools or upgrades.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_NAME="claude-tools"
MARKETPLACE_NAME="claude-tools"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/claude-tools"
LOG_ROOT="$HOME/.claude/logs"

log()  { printf '\033[1;34m[bootstrap]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bootstrap]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[bootstrap]\033[0m %s\n' "$*" >&2; exit 1; }

# 1) Prereqs (warn-only; we don't auto-install)
command -v uv     >/dev/null || fail "uv not found: https://docs.astral.sh/uv/"
command -v claude >/dev/null || fail "claude CLI not found: install Claude Code first"
command -v codex  >/dev/null || warn "codex CLI not found; review-loop with --reviewer codex will fail until installed"

# 2) Validate manifests
log "Validating plugin manifest..."
claude plugin validate "$REPO_ROOT" >/dev/null || fail "plugin/marketplace manifest invalid"

# 3) Register the repo as a marketplace (idempotent)
if claude plugin marketplace list 2>/dev/null | grep -Fq "$MARKETPLACE_NAME"; then
  log "Marketplace '$MARKETPLACE_NAME' already registered; refreshing..."
  claude plugin marketplace update "$MARKETPLACE_NAME" >/dev/null || warn "marketplace update returned non-zero; continuing"
else
  log "Registering '$REPO_ROOT' as marketplace '$MARKETPLACE_NAME'..."
  claude plugin marketplace add "$REPO_ROOT" >/dev/null
fi

# 4) Install or re-enable the plugin
if claude plugin list 2>/dev/null | grep -Fq "$PLUGIN_NAME"; then
  log "Plugin '$PLUGIN_NAME' already installed; ensuring enabled..."
  claude plugin enable "$PLUGIN_NAME" >/dev/null 2>&1 || true
else
  log "Installing plugin '$PLUGIN_NAME@$MARKETPLACE_NAME'..."
  claude plugin install "$PLUGIN_NAME@$MARKETPLACE_NAME" >/dev/null
fi

# 5) Install / refresh the Python CLI (editable, so git pull updates live)
log "Installing claude-tools Python CLI via uv tool (editable)..."
if uv tool list 2>/dev/null | grep -q '^claude-tools '; then
  uv tool upgrade --reinstall claude-tools >/dev/null
else
  uv tool install --editable "$REPO_ROOT" >/dev/null
fi
( cd "$REPO_ROOT" && uv lock --check >/dev/null 2>&1 ) || warn "uv.lock drift; run 'uv lock' and commit"

# 6) Create config + log dirs
log "Ensuring $CONFIG_DIR and $LOG_ROOT exist..."
mkdir -p "$CONFIG_DIR" "$LOG_ROOT"

# 7) Seed per-tool configs (never overwrite existing)
if [[ -d "$REPO_ROOT/config" ]]; then
  for example in "$REPO_ROOT"/config/*.toml.example; do
    [[ -e "$example" ]] || continue
    base=$(basename "$example" .example)
    target="$CONFIG_DIR/$base"
    if [[ -e "$target" ]]; then
      log "Config exists, skipping: $target"
    else
      cp "$example" "$target"
      log "Seeded: $target"
    fi
  done
fi

# 8) Smoke test
log "Smoke test: claude-tools --version"
claude-tools --version || fail "claude-tools not on PATH; check uv tool install output"

log "✔ Bootstrap complete. Restart Claude Code to load plugin skills."
