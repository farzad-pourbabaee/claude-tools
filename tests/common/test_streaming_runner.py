"""Tests for claude_tools.common.streaming_runner."""

from __future__ import annotations

import sys

import pytest

from claude_tools.common.streaming_runner import run_streaming
from claude_tools.common.subprocess_runner import SubprocessError


def test_streams_jsonl_events_to_callback() -> None:
    """A short python child that emits 3 JSONL events; callback receives all 3."""
    script = (
        "import json, sys\n"
        "for i in range(3):\n"
        "    print(json.dumps({'type': 'tick', 'i': i}), flush=True)\n"
    )
    received: list[dict] = []

    def on_event(evt: dict) -> None:
        received.append(evt)

    result = run_streaming(
        [sys.executable, "-u", "-c", script], on_event=on_event,
    )
    assert [e["i"] for e in received] == [0, 1, 2]
    assert len(result.events) == 3
    assert len(result.raw_lines) == 3
    assert result.returncode == 0


def test_non_json_lines_are_kept_in_raw_but_not_in_events() -> None:
    script = (
        "import json\n"
        "print('not json at all')\n"
        "print(json.dumps({'type': 'real'}))\n"
    )
    seen: list[dict] = []
    result = run_streaming([sys.executable, "-u", "-c", script], on_event=seen.append)
    assert len(seen) == 1
    assert seen[0]["type"] == "real"
    assert len(result.raw_lines) == 2
    assert any("not json" in line for line in result.raw_lines)


def test_callback_errors_do_not_crash_run() -> None:
    script = (
        "import json\n"
        "for i in range(2):\n"
        "    print(json.dumps({'i': i}))\n"
    )
    calls = []

    def on_event(evt: dict) -> None:
        calls.append(evt)
        raise RuntimeError("boom")

    result = run_streaming([sys.executable, "-u", "-c", script], on_event=on_event)
    assert len(calls) == 2
    assert result.returncode == 0


def test_non_zero_exit_raises_subprocess_error() -> None:
    with pytest.raises(SubprocessError) as exc:
        run_streaming(["sh", "-c", "echo oops >&2; exit 9"])
    assert "exit 9" in str(exc.value)
    assert "oops" in str(exc.value)


def test_timeout_raises_subprocess_error() -> None:
    with pytest.raises(SubprocessError) as exc:
        run_streaming(["sleep", "5"], timeout_s=0.1)
    assert "timed out" in str(exc.value)
