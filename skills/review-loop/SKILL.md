---
name: review-loop
description: Persistent-session author/reviewer feedback loop on a target file using Claude (Opus) and Codex (GPT-5). Use when the user asks to "review", "iterate on", "improve", or "have Codex/Claude review" a paper, document, or any single file with model-vs-model feedback until convergence.
argument-hint: <target-file> [--max-iterations N] [--author claude|codex] [--reviewer claude|codex] [--claude-model M] [--claude-effort L] [--codex-model M] [--codex-effort L] [--per-call-timeout S] [--dry-run]
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/scripts/run-tool.sh:*)"]
version: 0.2.0
---

# /review-loop

Run a reviewer/author feedback loop on a target file using the Claude Code CLI
and the Codex CLI (both subscription-backed, no API keys required). Each side
keeps a single persistent session across all iterations, so neither model
re-derives the file each round.

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

1. **Reviewer** (default: Codex / GPT-5) reads the working file (full
   contents inlined on iteration 1; thereafter only the author's prose
   summary + orchestrator-computed line ranges, with the reviewer reading
   the file fresh from disk via its Read tool) and either lists remaining
   substantive issues or ends with `<approved/>`.
2. **Author** (default: Claude Opus) gets the reviewer's feedback and edits
   the working file in place via its Edit tool — no marker extraction. On
   iteration 1 the file is also inlined; thereafter the author's persistent
   session already knows the file from its own Edit history. The author
   ends each turn with a short prose summary.

Both author and reviewer are launched with the project root as their
working directory, so they can read any other file in the project on
demand via their own built-in tools (Read / Glob / Grep / Bash). Sibling
file contents are NOT inlined into prompts — siblings don't change during
the loop, so re-shipping them every iteration would just waste tokens.

The author's tool allowlist is constrained to `Edit / Read / Glob / Grep` so
it can't accidentally damage anything other than the working file. The
reviewer is read-only.

If the reviewer approves on its very first pass, the author is never invoked
and the loop ends after a single reviewer call; the working file in that
case is a byte-for-byte copy of the original.

Loop stops on: explicit `<approved/>`, working-file stability between
consecutive iterations (within `--diff-threshold` characters of true diff
cost; iteration 1 is exempt), or `--max-iterations` (default 6).

## Live signals

While each model is working you'll see one short, color-coded line per
interesting event — file reads, edits, reasoning summaries, comments —
tagged with the round and side. The full raw event stream is also persisted
to `iter-NN-<side>.events.jsonl` for offline inspection.

## Logs

Per-run directory at `~/.claude/logs/review-loop/<UTC-stamp>/` contains:

- `target.before.md` and `iter-NN-target-after.md` — snapshots for `diff`.
- `iter-NN-msg-to-reviewer.md` / `iter-NN-msg-to-author.md` — exact strings
  the orchestrator sent into each session this round.
- `iter-NN-reviewer.md` / `iter-NN-author.md` — full model response text.
- `iter-NN-reviewer.events.jsonl` / `iter-NN-author.events.jsonl` — raw
  JSONL event streams.
- `iter-NN-diff.md` — unified diff of the working file pre/post the author's
  turn this round.
- `summary.md` — config + outcome + per-iter changed line ranges.

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
