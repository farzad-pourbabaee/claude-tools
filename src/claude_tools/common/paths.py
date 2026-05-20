"""Standard paths used across tools."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_config_dir


def config_dir() -> Path:
    """XDG-compliant config dir, e.g. ~/.config/claude-tools on Linux/macOS.

    Created lazily by callers if needed; this function only returns the path.
    """
    return Path(user_config_dir("claude-tools"))


def tool_config_path(tool_name: str) -> Path:
    """Per-tool TOML config path: {config_dir()}/<tool_name>.toml."""
    return config_dir() / f"{tool_name}.toml"


def log_dir(tool_name: str) -> Path:
    """Per-tool log root: ~/.claude/logs/<tool_name>/.

    Created lazily by callers; this function only returns the path.
    """
    return Path.home() / ".claude" / "logs" / tool_name


def plugin_root() -> Path | None:
    """Plugin root if the caller was invoked via a Claude Code skill.

    Returns the value of ``$CLAUDE_PLUGIN_ROOT`` as a Path if set, else None.
    Useful for resolving sibling files shipped inside the plugin.
    """
    raw = os.environ.get("CLAUDE_PLUGIN_ROOT")
    return Path(raw) if raw else None
