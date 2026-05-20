# Per-machine overrides

Each tool reads config from `~/.config/claude-tools/<tool>.toml` if present.
`bootstrap.sh` seeds these files from `config/<tool>.toml.example` only when
they're absent — it never overwrites your existing customizations.

## Precedence

Later layers win:

1. **Defaults** baked into the tool (in its `DEFAULTS` dict).
2. **Per-machine TOML** at `~/.config/claude-tools/<tool>.toml`.
3. **CLI flags** passed at invocation.

## Worked example

Office machine prefers Codex as author (because it has lower latency from
your network); laptop sticks with the default Claude. Both use `max_iterations=4`
to keep costs in check on the M-series chips' subscription quota.

`office:~/.config/claude-tools/review-loop.toml`:
```toml
author = "codex"
reviewer = "claude"
max_iterations = 4
```

`laptop:~/.config/claude-tools/review-loop.toml`:
```toml
max_iterations = 4
```

A one-off run on the office machine with `--author claude` flips back to
Claude for that invocation only (CLI flags override the TOML).

## Don't commit per-machine configs

The repo's `.gitignore` keeps `~/.config/claude-tools/` out of git by virtue
of being outside the repo, but if you ever symlink it inside, add
`config/*.toml` (without `.example`) to `.gitignore`.

## Inspecting effective config

For now, the easiest way is to run with `--dry-run`; the run-dir's prompt
files include the resolved configuration in their context. A future
`claude-tools <tool> --show-config` flag is on the to-do list.
