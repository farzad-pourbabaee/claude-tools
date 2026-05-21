"""Tests for review_loop.signals — event → console-line formatting."""

from __future__ import annotations

import io

from rich.console import Console

from claude_tools.review_loop.signals import (
    _format_claude_event,
    _format_codex_event,
    make_signal_printer,
)


def test_claude_tool_use_read() -> None:
    evt = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Read",
                 "input": {"file_path": "/abs/path/paper.md"}},
            ],
        },
    }
    out = _format_claude_event(evt)
    assert out is not None
    assert out.startswith("tool: Read(")
    assert "paper.md" in out


def test_claude_tool_use_edit() -> None:
    evt = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Edit",
                 "input": {"file_path": "x.md", "old_string": "foo\nbar"}},
            ],
        },
    }
    out = _format_claude_event(evt)
    assert out is not None
    assert "Edit" in out
    assert "x.md" in out


def test_claude_text_message_truncated() -> None:
    big = "X" * 500
    evt = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": big}]},
    }
    out = _format_claude_event(evt)
    assert out is not None
    assert out.startswith("comment: ")
    assert out.endswith("…")
    assert len(out) <= len("comment: ") + 100 + 1


def test_claude_thinking() -> None:
    evt = {
        "type": "assistant",
        "message": {"content": [{"type": "thinking", "thinking": "tracing recursion"}]},
    }
    out = _format_claude_event(evt)
    assert out is not None
    assert out.startswith("thinking:")


def test_claude_irrelevant_event_returns_none() -> None:
    assert _format_claude_event({"type": "system", "subtype": "init"}) is None
    assert _format_claude_event({"type": "rate_limit_event"}) is None
    assert _format_claude_event({"type": "result"}) is None


def test_codex_agent_message() -> None:
    evt = {
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "Looks good to me."},
    }
    out = _format_codex_event(evt)
    assert out == "comment: Looks good to me."


def test_codex_command_execution() -> None:
    evt = {
        "type": "item.completed",
        "item": {"type": "command_execution", "command": ["grep", "-n", "TODO"]},
    }
    out = _format_codex_event(evt)
    assert out is not None
    assert "bash" in out
    assert "grep" in out


def test_codex_unknown_item_type_surfaces_label() -> None:
    evt = {
        "type": "item.completed",
        "item": {"type": "newfangled_thing"},
    }
    out = _format_codex_event(evt)
    assert out == "event: newfangled_thing"


def test_printer_emits_one_line_per_interesting_event() -> None:
    """make_signal_printer wires events to the Rich console with side+iter tag."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, no_color=True, width=200)
    on_event = make_signal_printer(
        console, iteration=3, side="author", engine="claude",
    )

    on_event({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "hello"}]},
    })
    on_event({"type": "rate_limit_event"})  # skipped
    on_event({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Glob",
                                  "input": {"pattern": "*.md"}}]},
    })

    output = buf.getvalue()
    lines = [ln for ln in output.splitlines() if ln.strip()]
    assert len(lines) == 2
    for ln in lines:
        assert "iter 03" in ln
        assert "author" in ln
    assert "comment: hello" in lines[0]
    assert "tool: Glob" in lines[1]
