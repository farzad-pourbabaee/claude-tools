"""Tests for review_loop.adapters factory + sanity checks on the new stateful shape."""

from __future__ import annotations

import pytest

from claude_tools.review_loop.adapters import (
    ClaudeAdapter,
    CodexAdapter,
    get_adapter,
)


def test_factory_returns_claude_with_role() -> None:
    adapter = get_adapter("claude", role="author")
    assert isinstance(adapter, ClaudeAdapter)
    assert adapter.name == "claude"
    assert adapter.role == "author"
    assert adapter.session_id is None


def test_factory_returns_codex_with_role() -> None:
    adapter = get_adapter("codex", role="reviewer", model="gpt-5", effort="high")
    assert isinstance(adapter, CodexAdapter)
    assert adapter.name == "codex"
    assert adapter.role == "reviewer"
    assert adapter.model == "gpt-5"
    assert adapter.effort == "high"


def test_factory_is_case_insensitive() -> None:
    assert isinstance(get_adapter("Claude", role="author"), ClaudeAdapter)
    assert isinstance(get_adapter("CODEX", role="reviewer"), CodexAdapter)


def test_factory_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        get_adapter("gpt-4", role="author")


def test_each_factory_call_returns_a_fresh_adapter() -> None:
    """Two calls must yield independent instances so the orchestrator can pair
    them as author + reviewer of the same engine without sharing a session."""
    a = get_adapter("claude", role="author")
    b = get_adapter("claude", role="reviewer")
    assert a is not b
    assert a.role != b.role
