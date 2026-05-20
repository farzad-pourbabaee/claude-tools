"""Adapter protocol: maps a (system, user) prompt pair to a string response."""

from __future__ import annotations

from typing import Protocol


class ModelAdapter(Protocol):
    """Each adapter wraps one model CLI/API and exposes a uniform `invoke`."""

    name: str

    def invoke(self, system_prompt: str, user_prompt: str, *, timeout_s: float = 1800.0) -> str:
        """Run the model once and return its full text response.

        Implementations must raise ``SubprocessError`` (from
        ``claude_tools.common.subprocess_runner``) on failure.
        """
        ...
