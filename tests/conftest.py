"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Redirect $HOME and XDG_CONFIG_HOME to a fresh tmp_path subtree.

    Use this in any test that exercises code from `claude_tools.common.paths`
    so it doesn't write into the user's real ~/.claude or ~/.config.
    """
    home = tmp_path / "home"
    home.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    # platformdirs caches HOME lookups via os.path.expanduser — clear so tests see new $HOME.
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    yield home
