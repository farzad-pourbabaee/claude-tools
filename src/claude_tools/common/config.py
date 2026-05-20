"""TOML config loader with layered overrides.

Precedence (later wins):
  1. Defaults passed by the tool.
  2. ~/.config/claude-tools/<tool>.toml (per-machine, never in git).
  3. CLI flags (applied by the caller after this function returns).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from claude_tools.common.paths import tool_config_path


def load_tool_config(tool_name: str, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return defaults merged with values from ``~/.config/claude-tools/<tool_name>.toml``.

    If the per-machine file is absent, returns ``defaults`` (or {}) unchanged.
    The TOML file may be flat or nested; a top-level ``[<tool_name>]`` table is
    automatically unwrapped so a single file can hold multiple tools' configs.
    """
    merged: dict[str, Any] = dict(defaults or {})
    path = tool_config_path(tool_name)
    if not path.exists():
        return merged
    with path.open("rb") as f:
        data = tomllib.load(f)
    # Unwrap [<tool_name>] table if present, else use whole file.
    section = data.get(tool_name, data)
    if not isinstance(section, dict):
        raise ValueError(
            f"Expected dict at top of {path} (or under [{tool_name}]); got {type(section).__name__}"
        )
    merged.update(section)
    return merged


def write_example_if_missing(example_path: Path, target_path: Path) -> bool:
    """Copy example_path → target_path only if target doesn't exist. Returns True if written."""
    if target_path.exists():
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(example_path.read_bytes())
    return True
