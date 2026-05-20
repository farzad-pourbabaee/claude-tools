"""Tests for review_loop.adapters."""

from __future__ import annotations

import pytest

from claude_tools.review_loop.adapters import (
    ClaudeAdapter,
    CodexAdapter,
    get_adapter,
)


def test_factory_returns_claude() -> None:
    adapter = get_adapter("claude")
    assert isinstance(adapter, ClaudeAdapter)
    assert adapter.name == "claude"


def test_factory_returns_codex() -> None:
    adapter = get_adapter("codex")
    assert isinstance(adapter, CodexAdapter)
    assert adapter.name == "codex"


def test_factory_is_case_insensitive() -> None:
    assert isinstance(get_adapter("Claude"), ClaudeAdapter)
    assert isinstance(get_adapter("CODEX"), CodexAdapter)


def test_factory_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        get_adapter("gpt-4")
