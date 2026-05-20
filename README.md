# claude-tools

Personal Claude Code plugin + Python toolkit.

Currently ships one tool:

- **`review-loop`** — cross-model reviewer/author loop on a single file.
  Default: Codex (GPT-5) critiques first, Claude (Opus) rewrites with the
  feedback, iterates until reviewer approval, byte-stable author output, or
  `--max-iterations` is hit. If the file already passes review, the author
  is never invoked. The original is never modified — the final revision
  lands in a sibling `<stem>_loop_reviewed<ext>` file. Sibling files in
  the project directory are NOT inlined into prompts; both models can read
  them on demand from disk via their own built-in tools. Per-run transcripts
  under `~/.claude/logs/review-loop/<UTC-stamp>/`.

## Install on a new machine

Prerequisites (install once; `bootstrap.sh` warns if any are missing):

- [`uv`](https://docs.astral.sh/uv/) — Python package manager
- [`claude`](https://docs.claude.com/en/docs/claude-code) — Claude Code CLI, authenticated via `claude login`
- [`codex`](https://github.com/openai/codex) — OpenAI Codex CLI, authenticated via `codex login`
- [`gh`](https://cli.github.com) — GitHub CLI (only needed to clone)
- A working `git` with `user.name` and `user.email` configured

Then:

```bash
gh repo clone farzad-pourbabaee/claude-tools ~/dev/claude-tools
cd ~/dev/claude-tools
./bootstrap.sh
```

`bootstrap.sh` is idempotent — safe to re-run after `git pull` to pick up new
tools or updates. Restart Claude Code afterward so it loads the plugin's
skills.

## `review-loop` in 30 seconds

There are two entry points to the same Python implementation:

| Where | Invocation |
|---|---|
| **Terminal** | `claude-tools review-loop ./paper.md` |
| **Claude Code** | `/review-loop ./paper.md` |

Both forms accept the same flags. Inside Claude Code you can also use the
fully-qualified `/claude-tools:review-loop` form if the bare name collides
with another plugin's command.

The target file can be given positionally (shown above) or via `--target
./paper.md`; both forms are equivalent.

## Terminal usage

```bash
claude-tools review-loop ./paper.md \
  --author claude \
  --reviewer codex \
  --max-iterations 6 \
  --claude-model opus \
  --claude-effort high \
  --codex-model gpt-5.5 \
  --codex-effort xhigh \
  --per-call-timeout 1800 \
  --diff-threshold 32
```

### Flag reference

| Flag | Default | Meaning |
|---|---|---|
| `<file>` (positional) or `--target FILE` | *(required)* | File to iterate on. The original is never modified — the loop writes a sibling `<stem>_loop_reviewed<ext>` and works on that. |
| `--author {claude,codex}` | `claude` | Model that rewrites the file each round, incorporating the reviewer's feedback. |
| `--reviewer {claude,codex}` | `codex` | Model that critiques the current revision each round. |
| `--max-iterations N` | `6` | Hard cap on reviewer/author rounds. The loop also stops early on approval or stability. |
| `--diff-threshold N` | `32` (bytes) | Convergence threshold: if two consecutive author rewrites differ by fewer than `N` bytes, the loop stops (the author has "settled"). Smaller = stricter. |
| `--per-call-timeout SECS` | `1800` (= 30 min) | Per-invocation timeout for each `claude -p` or `codex exec` subprocess. Bump this if you hit `subprocess.TimeoutExpired` on big files. |
| `--claude-model NAME` | *(CLI default)* | Model alias or ID for the Claude CLI (`opus`, `sonnet`, `claude-opus-4-7`, …). **Engine-scoped**: applies whenever Claude is invoked, regardless of role. |
| `--claude-effort LEVEL` | *(CLI default)* | Reasoning effort for Claude: `low` \| `medium` \| `high` \| `xhigh` \| `max`. |
| `--codex-model NAME` | *(CLI default)* | Model name for the Codex CLI (`gpt-5`, `gpt-5.5`, `gpt-5-codex`, …). **Engine-scoped**: applies whenever Codex is invoked, regardless of role. |
| `--codex-effort LEVEL` | *(CLI default)* | Reasoning effort for Codex: `low` \| `medium` \| `high` \| `xhigh`. |
| `--dry-run` | off | Build the iteration-1 prompts and write them to the run dir without invoking either model. Useful for inspecting what the orchestrator would send. |
| `--context-budget N` | *(deprecated)* | No-op flag retained so old configs keep parsing. Sibling content is no longer inlined into prompts; the models read siblings on demand from disk. |

"Engine-scoped" means `--claude-*` always controls the Claude CLI even if you
swap `--author codex --reviewer claude`. Leaving these unset falls through
to whatever each CLI has configured in `~/.claude/settings.json` or
`~/.codex/config.toml`.

### Common terminal recipes

```bash
# Minimal: defaults across the board (Claude author, Codex reviewer, 6 iters).
claude-tools review-loop ./paper.md

# Swap roles: Codex rewrites, Claude reviews. Engine settings (the Claude/Codex
# model + effort) follow the engine, not the role — so --claude-model still
# controls Claude even though Claude is now the reviewer.
claude-tools review-loop ./paper.md --author codex --reviewer claude

# Quick smoke test: render the prompts but don't burn API quota.
claude-tools review-loop ./paper.md --dry-run

# Heavy review: pin both engines to their strongest reasoning, allow more rounds.
claude-tools review-loop ./paper.md \
  --max-iterations 10 \
  --claude-model opus --claude-effort max \
  --codex-model gpt-5.5 --codex-effort xhigh
```

## Claude Code usage

Inside a Claude Code session, the same tool is exposed as a slash command:

```
/review-loop ./paper.md --max-iterations 6 --claude-effort high --codex-effort xhigh
```

Every flag from the terminal table above works identically — the slash
command just forwards `$ARGUMENTS` to `scripts/run-tool.sh review-loop`.

Two things to keep in mind:

1. **Keep the invocation on a single line.** Claude Code splits multi-line
   slash commands at newlines and silently drops everything after the first
   line. If your invocation gets long, use the per-machine config file
   (next section) for the parts that don't change.
2. **Namespaced form.** If you have multiple plugins installed and the bare
   `/review-loop` name collides, use the fully-qualified
   `/claude-tools:review-loop ./paper.md …` form. The arguments are
   identical.

### Common Claude-Code recipes

```
/review-loop ./paper.md
/review-loop ./paper.md --max-iterations 10
/review-loop ./paper.md --dry-run
/review-loop ./paper.md --author codex --reviewer claude
/claude-tools:review-loop ./paper.md --claude-effort max --codex-effort xhigh
```

## What happens on a run

When the loop starts, the orchestrator:

1. Copies your target file to a sibling `<stem>_loop_reviewed<ext>`
   (overwriting any prior copy). All edits happen to that working copy —
   the original is untouched.
2. Creates a fresh log directory at `~/.claude/logs/review-loop/<UTC-stamp>/`.
3. On each iteration:
   - **Reviewer** reads the working copy and emits feedback (or `<approved/>`).
   - If the reviewer approved, the loop ends.
   - Otherwise, **author** reads the working copy + feedback, emits a full
     rewrite wrapped in `<<<FILE>>>…<<<END>>>` markers, and the orchestrator
     atomically writes the extracted body back to the working copy.
4. Stops on: explicit `<approved/>`, byte-stable author output across two
   consecutive iterations, or `--max-iterations`.

Both author and reviewer are launched with the project root as their
working directory, so they can read **any** sibling file from disk on
demand via their own built-in tools (Read / grep / cat / Bash). No
sibling content is pasted into prompts.

### Per-run artifacts

Inside `~/.claude/logs/review-loop/<UTC-stamp>/` you'll find:

| File | Purpose |
|---|---|
| `target.before.md` | Snapshot of the original file at the start of the run. |
| `iter-NN-reviewer-prompt.md` | What was sent to the reviewer (dry-run only). |
| `iter-NN-reviewer-system.md` | The reviewer's system prompt (dry-run only). |
| `iter-NN-reviewer.md` | The reviewer's response. |
| `iter-NN-author.md` | The author's response (full text, including markers). |
| `iter-NN-target-after.md` | Working file after iteration N. |
| `summary.md` | Config used, iterations run, convergence reason. |

`diff target.before.md iter-NN-target-after.md` is the cleanest way to see
what the loop changed on round N.

## Per-machine config

Defaults can be set per-machine at `~/.config/claude-tools/review-loop.toml`.
`bootstrap.sh` seeds this file from `config/review-loop.toml.example` on its
first run and never overwrites it afterward. CLI flags override values in
the config file.

Useful keys (all optional):

```toml
author          = "claude"
reviewer        = "codex"
max_iterations  = 6
diff_threshold_bytes = 32
per_call_timeout_s   = 1800

claude_model    = "opus"
claude_effort   = "high"
codex_model     = "gpt-5.5"
codex_effort    = "xhigh"
```

See `config/review-loop.toml.example` for the canonical commented version.

## Layout

```
.
├── .claude-plugin/        # plugin + marketplace manifests
├── skills/                # auto-discovered Claude Code skills
├── agents/                # auto-discovered subagents (reserved)
├── scripts/               # plugin-root shell shims
├── src/claude_tools/      # uv-managed Python package
├── config/                # *.toml.example templates
├── tests/                 # pytest suite
├── docs/                  # architecture + extension guides
└── bootstrap.sh           # per-machine installer
```

## License

MIT — see `LICENSE`.
