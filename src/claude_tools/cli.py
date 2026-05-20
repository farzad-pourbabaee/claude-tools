"""Top-level CLI for claude-tools.

Dispatches to per-tool subcommands. To add a new tool, write
`src/claude_tools/<tool>/cli.py` with `add_subparser(subparsers)` and
`run(args)`, then register a single line below in `_register_subcommands`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from claude_tools import __version__


def _register_subcommands(subparsers: argparse._SubParsersAction) -> None:
    """Register each tool's subcommand. Add one line per new tool."""
    from claude_tools.review_loop.cli import add_subparser as _review_loop
    _review_loop(subparsers)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-tools",
        description="Personal Claude Code toolkit (orchestrators, helpers, skills).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="subcommand", metavar="<tool>")
    _register_subcommands(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "subcommand", None):
        parser.print_help()
        return 0
    # Each tool's add_subparser sets `args.func = run`.
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    return int(func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
