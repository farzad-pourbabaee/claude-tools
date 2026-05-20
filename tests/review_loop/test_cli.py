"""Tests for review_loop.cli argument parsing.

Specifically guards the dual positional / --target shape so future refactors
can't silently regress slash-command UX.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from claude_tools.review_loop.cli import add_subparser


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    add_subparser(subparsers)
    return parser


def test_target_as_positional() -> None:
    parser = _build_parser()
    args = parser.parse_args(["review-loop", "./paper.md", "--max-iterations", "2"])
    assert args.target == Path("./paper.md")
    assert args.target_flag is None
    assert args.max_iterations == 2


def test_target_as_flag() -> None:
    parser = _build_parser()
    args = parser.parse_args(["review-loop", "--target", "./paper.md", "--max-iterations", "2"])
    assert args.target is None
    assert args.target_flag == Path("./paper.md")
    assert args.max_iterations == 2


def test_neither_form_parses_but_run_will_error_later() -> None:
    """Argparse no longer flags the missing target; cli.run() raises instead."""
    parser = _build_parser()
    args = parser.parse_args(["review-loop"])
    assert args.target is None
    assert args.target_flag is None


def test_per_engine_flags_parse() -> None:
    parser = _build_parser()
    args = parser.parse_args([
        "review-loop", "./paper.md",
        "--claude-model", "opus", "--claude-effort", "max",
        "--codex-model", "gpt-5.5", "--codex-effort", "xhigh",
        "--per-call-timeout", "2400",
    ])
    assert args.claude_model == "opus"
    assert args.claude_effort == "max"
    assert args.codex_model == "gpt-5.5"
    assert args.codex_effort == "xhigh"
    assert args.per_call_timeout_s == pytest.approx(2400.0)
