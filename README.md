# claude-tools

Personal Claude Code plugin + Python toolkit.

Currently ships one tool:

- **`review-loop`** — cross-model reviewer/author loop on a target file.
  Default: Codex (GPT-5) critiques first, Claude (Opus) rewrites with the
  feedback, iterates until reviewer approval or `--max-iterations` is hit.
  If the original file already passes review, the author is never invoked.
  Per-run transcripts under `~/.claude/logs/review-loop/<UTC-stamp>/`.

## Install on a new machine

Prerequisites (install once; bootstrap will warn if missing):

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

`bootstrap.sh` is idempotent — safe to re-run after `git pull` to pick
up new tools or updates. Restart Claude Code afterward so it loads the
plugin's skills.

## Use a tool

From a terminal:

```bash
claude-tools review-loop ./paper.md --max-iterations 6
```

From inside Claude Code (everything on **one line** — newlines split the
slash-command's argument list):

```
/review-loop ./paper.md --max-iterations 6
```

The target file can be given positionally (as above) or via `--target FILE`;
both are equivalent. Pin per-engine model + reasoning effort with
`--claude-model / --claude-effort / --codex-model / --codex-effort`
(unset = each CLI's own default).

See `docs/` for architecture, machine-specific overrides, and the
checklist for adding a new tool.

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
