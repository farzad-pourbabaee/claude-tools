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
                       (persistent           (persistent
                        session, --resume)    session, exec resume)
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
- **CLI session rollouts** (Codex side): persisted to
  `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl` by the codex CLI
  itself; the orchestrator captures the `thread_id` from the first
  ``thread.started`` event and reuses it across the run.

## Why subscription-backed CLIs?

The two model adapters shell out to `claude -p` and `codex exec` rather than
calling the Anthropic / OpenAI HTTP APIs directly. This means:

- No API keys live anywhere on disk.
- Quota comes from the user's existing Max / Plus subscriptions.
- Per-machine `claude login` / `codex login` is the only auth setup needed.
- The CLI tools are themselves models-of-models (Claude Code is opinionated
  about how to talk to Claude), which is a feature, not a bug — we inherit
  the same tool-call semantics, reasoning effort, etc.

## How review-loop exposes project context

The orchestrator inlines the target file body **only on iteration 1**, and
even then only into the iter-1 prompt. From iteration 2 onward both sides'
persistent sessions already know the file (the author has been editing it,
the reviewer has been reading it), so the orchestrator ships only deltas:
the author's prose summary + orchestrator-computed changed line ranges to
the reviewer; the reviewer's critique to the author. Sibling files are
**never** inlined — both CLIs are launched with the project root as their
working directory so they can read siblings on demand via Read / Glob /
Grep.

This matters for two reasons:

1. **Context window.** A research directory with many large `.md`/`.tex`
   drafts can easily exceed 200K tokens of sibling content. Re-inlining
   any of it would blow past every model's input window in a 6-round loop.
2. **Cache friendliness.** Subsequent turns inside a persistent session
   replay the prior transcript through the model's own prompt cache. The
   smaller the per-turn delta, the better the cache hit rate.

The legacy `collect_context()` helper (which DOES inline siblings up to a
token budget) is still available in `claude_tools.common.context_collector`
for tools that genuinely need a single self-contained prompt. The review-loop
uses the lighter `collect_review_context()` instead, which collects only
the target's content and a project tree listing.

## How sessions are kept alive

- **Claude side.** The adapter pre-generates a UUID via `uuid.uuid4()` and
  passes it as `--session-id <uuid>` on the very first call. Subsequent
  calls pass `--resume <uuid>`. The CLI persists the conversation under
  `~/.claude/projects/<…>/` on its own.
- **Codex side.** The adapter calls `codex exec --json …` on the first
  turn and scrapes the `thread_id` field out of the first JSONL event
  (`{"type":"thread.started","thread_id":"…"}`). Subsequent turns use
  `codex exec resume --json <thread_id> …`. The CLI persists the
  conversation under `~/.codex/sessions/YYYY/MM/DD/…`.

Both adapters consume their stdout as a structured event stream
(`--output-format stream-json` for Claude, `--json` for Codex) so the
orchestrator can surface live progress and persist a forensic record
without buffering the whole turn before showing anything.

## Edit-in-place vs. marker extraction

The previous review-loop design required the author to wrap a full file
rewrite between `<<<FILE>>>` and `<<<END>>>` markers, which the
orchestrator would extract and atomically write back. That pattern is
gone. The author now uses its built-in **Edit** tool to modify the working
file directly; the orchestrator only diffs the file pre/post the author's
turn to compute changed line ranges for the next reviewer prompt.

To keep the author from touching anything outside the working file, the
Claude adapter restricts its tool allowlist to `Edit,Read,Glob,Grep` and
runs with `--permission-mode acceptEdits` so edits don't block on
interactive approvals. The Codex adapter sets `-s workspace-write` for
the author session and `-s read-only` for the reviewer session.
