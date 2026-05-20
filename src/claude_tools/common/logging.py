"""Per-run logging: a fresh timestamped directory under ~/.claude/logs/<tool>/."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from claude_tools.common.paths import log_dir


def new_run_dir(tool_name: str, when: datetime | None = None) -> Path:
    """Create and return ~/.claude/logs/<tool>/<UTC-iso-stamp>/.

    The stamp format is filesystem-safe and lexicographically sortable.
    """
    stamp = (when or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    run = log_dir(tool_name) / stamp
    run.mkdir(parents=True, exist_ok=True)
    return run


def write_transcript(run: Path, name: str, body: str) -> Path:
    """Write a markdown transcript to ``<run>/<name>.md``. Returns the path."""
    if not name.endswith(".md"):
        name = f"{name}.md"
    path = run / name
    path.write_text(body, encoding="utf-8")
    return path
