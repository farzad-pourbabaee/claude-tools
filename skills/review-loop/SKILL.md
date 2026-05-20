---
name: review-loop
description: Author/reviewer feedback loop on a target file using Claude (Opus) and Codex (GPT-5). Use when the user asks to "review", "iterate on", "improve", or "have Codex/Claude review" a paper, document, or any single file with model-vs-model feedback until convergence.
argument-hint: <target-file> [--max-iterations N] [--author claude|codex] [--reviewer claude|codex] [--claude-model M] [--claude-effort L] [--codex-model M] [--codex-effort L] [--per-call-timeout S] [--dry-run]
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/scripts/run-tool.sh:*)"]
version: 0.1.0
---

# /review-loop

Run a reviewer/author feedback loop on a target file using the Claude Code CLI
and the Codex CLI (both subscription-backed, no API keys required).

```!
"${CLAUDE_PLUGIN_ROOT}/scripts/run-tool.sh" review-loop $ARGUMENTS
```

## Usage

```
/review-loop <target-file> [flags...]
/review-loop --target <target-file> [flags...]   # equivalent flag form
```

Keep the whole invocation on **one line** — Claude Code splits a multi-line
slash command into separate dispatches, so newlines inside the argument list
will silently drop everything after the first line.

## What happens

The original target file is **never modified**. At startup the orchestrator
copies it to a sibling `<stem>_loop_reviewed<ext>` (e.g. `paper.md` →
`paper_loop_reviewed.md`, overwriting any prior copy) and runs the loop
against that working file. When the loop ends — by approval, stability, or
hitting `--max-iterations` — that sibling file holds the final version.

Each iteration:

1. **Reviewer** (default: Codex / GPT-5) reads the current working file
   (inlined into the prompt) plus a project-tree listing for orientation,
   and either lists remaining substantive issues or ends with `<approved/>`.
2. **Author** (default: Claude Opus) reads the same context plus the
   reviewer's feedback and emits a full revised version of the working file.
   The orchestrator writes it back atomically to the working path.

Both author and reviewer are launched with the project root as their
working directory, so they can read any other file in the project on
demand via their own built-in tools (Read / grep / cat / Bash). Sibling
file contents are NOT inlined into prompts — siblings don't change during
the loop, so re-shipping them every iteration would just waste tokens.

If the reviewer approves on its very first pass, the author is never invoked
and the loop ends after a single reviewer call; the working file in that
case is a byte-for-byte copy of the original.

Loop stops on: explicit `<approved/>`, byte-stable author output across
consecutive iterations, or `--max-iterations` (default 6).

## Logs

Per-run directory at `~/.claude/logs/review-loop/<UTC-stamp>/` contains:

- `target.before.md` and `iter-NN-target-after.md` — snapshots for `diff`.
- `iter-NN-author.md` / `iter-NN-reviewer.md` — full model transcripts.
- `summary.md` — config + outcome.

## Config

Defaults can be overridden per-machine at
`~/.config/claude-tools/review-loop.toml`. See
`${CLAUDE_PLUGIN_ROOT}/config/review-loop.toml.example` for available keys.
CLI flags override config-file values.

Model + reasoning-effort are **engine-scoped**: `--claude-model` /
`--claude-effort` always apply to the Claude CLI (whether it's the author
or the reviewer), and `--codex-model` / `--codex-effort` always apply to
the Codex CLI. Leaving them unset falls through to each CLI's own default
(typically configured in `~/.claude/settings.json` and `~/.codex/config.toml`).
