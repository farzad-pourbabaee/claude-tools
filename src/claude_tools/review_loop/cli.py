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
}


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "review-loop",
        help="Run an author/reviewer feedback loop on a target file.",
        description=(
            "Iterates: author rewrites the target file, reviewer critiques the new "
            "version, repeat until convergence or --max-iterations. Per-run logs "
            "land in ~/.claude/logs/review-loop/<UTC-stamp>/."
        ),
    )
    p.add_argument("--target", required=True, type=Path, help="Path to the file to iterate on.")
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
    p.add_argument("--dry-run", action="store_true",
                   help="Build prompts and write them to the run dir without invoking models.")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cfg_dict = load_tool_config("review-loop", defaults=DEFAULTS)
    # CLI flags override config file.
    overridable = (
        "author", "reviewer", "max_iterations",
        "context_budget_tokens", "diff_threshold_bytes",
    )
    for key in overridable:
        val = getattr(args, key, None)
        if val is not None:
            cfg_dict[key] = val

    cfg = LoopConfig(
        target=args.target,
        author=cfg_dict["author"],
        reviewer=cfg_dict["reviewer"],
        max_iterations=int(cfg_dict["max_iterations"]),
        context_budget_tokens=int(cfg_dict["context_budget_tokens"]),
        diff_threshold_bytes=int(cfg_dict["diff_threshold_bytes"]),
        dry_run=bool(args.dry_run),
    )
    result = run_loop(cfg)
    return 0 if result.final_converged or cfg.dry_run else 1
