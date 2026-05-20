"""Tests for claude_tools.common.logging."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from claude_tools.common import logging as ctlog


def test_new_run_dir_creates_timestamped(isolated_home: Path) -> None:
    when = datetime(2026, 5, 20, 13, 37, 42, tzinfo=UTC)
    p = ctlog.new_run_dir("review-loop", when=when)
    assert p.exists()
    assert p.is_dir()
    assert p.name == "20260520T133742Z"
    assert p.parent == isolated_home / ".claude" / "logs" / "review-loop"


def test_new_run_dir_default_time_format(isolated_home: Path) -> None:
    p = ctlog.new_run_dir("review-loop")
    assert re.fullmatch(r"\d{8}T\d{6}Z", p.name)


def test_write_transcript_with_and_without_extension(isolated_home: Path) -> None:
    run = ctlog.new_run_dir("review-loop")
    p1 = ctlog.write_transcript(run, "iter-01-author", "hello")
    assert p1.read_text() == "hello"
    assert p1.name == "iter-01-author.md"
    p2 = ctlog.write_transcript(run, "iter-01-reviewer.md", "world")
    assert p2.name == "iter-01-reviewer.md"
    assert p2.read_text() == "world"
