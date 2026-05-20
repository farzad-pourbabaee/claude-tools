"""review-loop subcommand: argparse wiring + run() entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from claude_tools.common.config import load_tool_config
from claude_tools.review_loop.orchestrator import LoopConfig, run_loop

DEFAULTS = {
    "author": "claude",
    "reviewer": "codex",
    "max_iterations": 6,
    "context_budget_tokens": 200_000,
    "diff_threshold_bytes": 32,
    "per_call_timeout_s": 1800.0,
    # Per-engine model + reasoning-effort overrides. None falls through to the
    # CLI's own default (typically set in ~/.claude/settings.json and
    # ~/.codex/config.toml).
    "claude_model": None,
    "claude_effort": None,
    "codex_model": None,
    "codex_effort": None,
}


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "review-loop",
        help="Run a reviewer/author feedback loop on a target file.",
        description=(
            "Iterates: reviewer critiques the current target file; if it approves "
            "the loop ends, otherwise the author rewrites the file with that "
            "feedback. Repeat until reviewer approval, byte-stable author output, "
            "or --max-iterations. Per-run logs land in "
            "~/.claude/logs/review-loop/<UTC-stamp>/."
        ),
    )
    # Target file can be given positionally OR via --target. The positional
    # form makes slash-command usage natural: `/review-loop ./paper.md ...`.
    p.add_argument("target", nargs="?", default=None, type=Path,
                   help="Path to the file to iterate on (positional form). "
                        "Equivalent to --target.")
    p.add_argument("--target", dest="target_flag", type=Path, default=None,
                   help="Path to the file to iterate on (flag form, equivalent "
                        "to the positional argument).")
    p.add_argument("--author", choices=["claude", "codex"], help="Model that revises the file.")
    p.add_argument(
        "--reviewer",
        choices=["claude", "codex"],
        help="Model that critiques each revision.",
    )
    p.add_argument("--max-iterations", type=int, help="Hard cap on rounds (default 6).")
    p.add_argument("--context-budget", type=int, dest="context_budget_tokens",
                   help="Approx token budget for read-only sibling files.")
    p.add_argument("--diff-threshold", type=int, dest="diff_threshold_bytes",
                   help="Author-output byte delta below which we declare stability.")
    p.add_argument("--per-call-timeout", type=float, dest="per_call_timeout_s",
                   help="Per-invocation timeout in seconds for each model call "
                        "(default 1800).")
    p.add_argument("--claude-model", dest="claude_model",
                   help="Model alias or full ID for the Claude CLI (e.g. 'opus', "
                        "'sonnet', 'claude-opus-4-7'). Default: CLI's own setting.")
    p.add_argument("--claude-effort", dest="claude_effort",
                   help="Reasoning effort for the Claude CLI: "
                        "low | medium | high | xhigh | max. Default: CLI's own setting.")
    p.add_argument("--codex-model", dest="codex_model",
                   help="Model name for the Codex CLI (e.g. 'gpt-5', 'gpt-5.5', "
                        "'gpt-5-codex'). Default: CLI's own setting.")
    p.add_argument("--codex-effort", dest="codex_effort",
                   help="Reasoning effort for the Codex CLI: "
                        "low | medium | high | xhigh. Default: CLI's own setting.")
    p.add_argument("--dry-run", action="store_true",
                   help="Build prompts and write them to the run dir without invoking models.")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    # Resolve target from positional or --target. Positional wins if both are given.
    target = args.target if args.target is not None else args.target_flag
    if target is None:
        raise SystemExit(
            "error: a target file is required (positional argument or --target FILE)"
        )

    cfg_dict = load_tool_config("review-loop", defaults=DEFAULTS)
    # CLI flags override config file.
    overridable = (
        "author", "reviewer", "max_iterations",
        "context_budget_tokens", "diff_threshold_bytes",
        "per_call_timeout_s",
        "claude_model", "claude_effort",
        "codex_model", "codex_effort",
    )
    for key in overridable:
        val = getattr(args, key, None)
        if val is not None:
            cfg_dict[key] = val

    cfg = LoopConfig(
        target=target,
        author=cfg_dict["author"],
        reviewer=cfg_dict["reviewer"],
        max_iterations=int(cfg_dict["max_iterations"]),
        context_budget_tokens=int(cfg_dict["context_budget_tokens"]),
        diff_threshold_bytes=int(cfg_dict["diff_threshold_bytes"]),
        per_call_timeout_s=float(cfg_dict["per_call_timeout_s"]),
        claude_model=cfg_dict.get("claude_model"),
        claude_effort=cfg_dict.get("claude_effort"),
        codex_model=cfg_dict.get("codex_model"),
        codex_effort=cfg_dict.get("codex_effort"),
        dry_run=bool(args.dry_run),
    )
    result = run_loop(cfg)
    return 0 if result.final_converged or cfg.dry_run else 1
