# Adding a new tool

The repo is designed so a new tool slots in with no structural changes. Here's
the full checklist for a hypothetical `proof-checker` tool.

## 1. Python module

Create `src/claude_tools/proof_checker/`:

```
src/claude_tools/proof_checker/
├── __init__.py          # docstring
├── cli.py               # add_subparser(subparsers) + run(args)
└── checker.py           # the actual logic
```

`cli.py` follows the same shape as `review_loop/cli.py`:

```python
import argparse
from claude_tools.common.config import load_tool_config

DEFAULTS = {"strict": True}

def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("proof-checker", help="Check proof structure.")
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--strict", action="store_true")
    p.set_defaults(func=run)

def run(args: argparse.Namespace) -> int:
    cfg = load_tool_config("proof-checker", defaults=DEFAULTS)
    # ... call into checker.py ...
    return 0
```

Re-use everything in `claude_tools.common/`: paths, config, logging,
subprocess_runner, context_collector.

## 2. Register the subcommand

In `src/claude_tools/cli.py`, add one line inside `_register_subcommands`:

```python
def _register_subcommands(subparsers):
    from claude_tools.review_loop.cli import add_subparser as _review_loop
    _review_loop(subparsers)
    from claude_tools.proof_checker.cli import add_subparser as _proof_checker
    _proof_checker(subparsers)
```

## 3. Add the slash command

Create `skills/proof-checker/SKILL.md` mirroring `skills/review-loop/SKILL.md`:

```markdown
---
name: proof-checker
description: Check proof structure for ...
argument-hint: <target-file> [--strict]
allowed-tools: ["Bash(${CLAUDE_PLUGIN_ROOT}/scripts/run-tool.sh:*)"]
version: 0.1.0
---

# /proof-checker

```!
"${CLAUDE_PLUGIN_ROOT}/scripts/run-tool.sh" proof-checker $ARGUMENTS
```
```

No change to `scripts/run-tool.sh` — it's generic over the first argument.

## 4. Config example

Drop `config/proof-checker.toml.example` with documented defaults.
`bootstrap.sh` will seed `~/.config/claude-tools/proof-checker.toml` from it
on the next run (without overwriting existing).

## 5. Tests

`tests/proof_checker/` with whatever unit tests make sense. They run as part
of `uv run pytest` (no test discovery config to touch).

## 6. Reinstall on each machine

```bash
cd ~/dev/claude-tools && git pull && ./bootstrap.sh
```

Then restart Claude Code so it loads the new skill.

That's it — seven steps, purely additive, no structural reshuffling.
