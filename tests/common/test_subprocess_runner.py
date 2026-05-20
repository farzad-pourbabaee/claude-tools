"""Tests for claude_tools.common.subprocess_runner."""

from __future__ import annotations

import pytest

from claude_tools.common.subprocess_runner import SubprocessError, run_capture


def test_capture_success() -> None:
    result = run_capture(["printf", "hello"])
    assert result.stdout == "hello"
    assert result.returncode == 0
    assert result.duration_s >= 0


def test_capture_failure_raises() -> None:
    with pytest.raises(SubprocessError) as exc:
        run_capture(["sh", "-c", "echo boom >&2; exit 7"])
    assert "exit 7" in str(exc.value)
    assert "boom" in str(exc.value)


def test_stdin_passthrough() -> None:
    result = run_capture(["cat"], stdin="from-stdin\n")
    assert result.stdout == "from-stdin\n"


def test_timeout_raises() -> None:
    with pytest.raises(SubprocessError) as exc:
        run_capture(["sleep", "5"], timeout_s=0.05)
    assert "timed out" in str(exc.value)
