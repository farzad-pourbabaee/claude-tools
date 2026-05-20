"""Tests for claude_tools.common.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_tools.common import config, paths


def test_load_returns_defaults_when_no_file(isolated_home: Path) -> None:
    result = config.load_tool_config("review-loop", defaults={"a": 1, "b": "x"})
    assert result == {"a": 1, "b": "x"}


def test_load_merges_flat_toml(isolated_home: Path) -> None:
    cfg = paths.tool_config_path("review-loop")
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("max_iterations = 12\nauthor = \"codex\"\n")
    result = config.load_tool_config(
        "review-loop", defaults={"max_iterations": 6, "reviewer": "claude"}
    )
    assert result == {"max_iterations": 12, "author": "codex", "reviewer": "claude"}


def test_load_unwraps_named_section(isolated_home: Path) -> None:
    cfg = paths.tool_config_path("review-loop")
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("[review-loop]\nauthor = \"codex\"\n")
    result = config.load_tool_config("review-loop", defaults={"author": "claude"})
    assert result == {"author": "codex"}


def test_load_rejects_non_dict_section(isolated_home: Path) -> None:
    cfg = paths.tool_config_path("review-loop")
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("'review-loop' = 'oops'\n")
    with pytest.raises(ValueError):
        config.load_tool_config("review-loop")


def test_write_example_if_missing(tmp_path: Path) -> None:
    src = tmp_path / "example.toml"
    src.write_text("foo = 1\n")
    dst = tmp_path / "subdir" / "target.toml"
    assert config.write_example_if_missing(src, dst) is True
    assert dst.read_text() == "foo = 1\n"
    # Second call must not overwrite.
    src.write_text("foo = 2\n")
    assert config.write_example_if_missing(src, dst) is False
    assert dst.read_text() == "foo = 1\n"
