# Architecture

`claude-tools` is a three-layer thing:

1. **Plugin layer** (`skills/`, `agents/`, `.claude-plugin/`) — installed into
   Claude Code via `claude plugin install claude-tools@claude-tools`. Each
   skill is auto-discovered from its directory and registered as a slash
   command. Skills are intentionally thin: their body just shells out to
   `${CLAUDE_PLUGIN_ROOT}/scripts/run-tool.sh <tool> $ARGUMENTS`.

2. **Dispatcher** (`scripts/run-tool.sh`) — a two-line shim that forwards to
   the Python CLI. It prefers the `claude-tools` executable on PATH (installed
   via `uv tool install --editable .`) and falls back to
   `uv run --project ${CLAUDE_PLUGIN_ROOT} claude-tools` so the slash command
   works even on a fresh-clone machine that hasn't run `bootstrap.sh` yet.

3. **Python package** (`src/claude_tools/`) — a uv-managed package with a
   single entry point (`claude_tools.cli:main`) that dispatches to per-tool
   subcommands. Shared utilities live under `claude_tools.common/`; each tool
   lives under `claude_tools.<tool_name>/` and exposes `add_subparser(subparsers)`
   plus `run(args)`. The top-level CLI registers tools by importing them in
   `_register_subcommands`.

```
Claude Code  →  /review-loop foo.md
                   │
                   ▼
            SKILL.md  ──── allowed-tools: ${CLAUDE_PLUGIN_ROOT}/scripts/run-tool.sh
                   │
                   ▼
        scripts/run-tool.sh
                   │
                   ▼
           claude-tools (PATH or uv run --project)
                   │
                   ▼
          claude_tools.cli:main  →  review_loop.cli.run(args)
                                       │
                                       ▼
                            review_loop.orchestrator.run_loop(cfg)
                              │                      │
                              ▼                      ▼
                       ClaudeAdapter         CodexAdapter
                              │                      │
                              ▼                      ▼
                       `claude -p ...`         `codex exec ...`
```

## State boundaries

- **Source of truth**: the git repo. Never edit installed plugin files
  directly; edit the repo and re-run `bootstrap.sh` (or rely on the
  editable install).
- **Per-machine config**: `~/.config/claude-tools/<tool>.toml`. Created
  from `config/<tool>.toml.example` by `bootstrap.sh`, never overwritten.
- **Per-run logs**: `~/.claude/logs/<tool>/<UTC-stamp>/`. Always created
  fresh; never reused across runs.
- **Plugin install state**: managed by Claude Code under
  `~/.claude/plugins/`. Don't touch.

## Why subscription-backed CLIs?

The two model adapters shell out to `claude -p` and `codex exec` rather than
calling the Anthropic / OpenAI HTTP APIs directly. This means:

- No API keys live anywhere on disk.
- Quota comes from the user's existing Max / Plus subscriptions.
- Per-machine `claude login` / `codex login` is the only auth setup needed.
- The CLI tools are themselves models-of-models (Claude Code is opinionated
  about how to talk to Claude), which is a feature, not a bug — we inherit
  the same tool-call semantics, reasoning effort, etc.
