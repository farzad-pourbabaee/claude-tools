"""Tests for claude_tools.common.paths."""

from __future__ import annotations

from pathlib import Path

from claude_tools.common import paths


def test_log_dir_under_home(isolated_home: Path) -> None:
    p = paths.log_dir("review-loop")
    assert p == isolated_home / ".claude" / "logs" / "review-loop"


def test_tool_config_path(isolated_home: Path) -> None:
    p = paths.tool_config_path("review-loop")
    assert p.name == "review-loop.toml"
    assert "claude-tools" in str(p)


def test_plugin_root_absent(isolated_home: Path) -> None:
    assert paths.plugin_root() is None


def test_plugin_root_present(monkeypatch, isolated_home: Path) -> None:
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/some/plugin/dir")
    assert paths.plugin_root() == Path("/some/plugin/dir")
