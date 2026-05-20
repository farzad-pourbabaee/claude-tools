"""Adapter protocol: maps a (system, user) prompt pair to a string response."""

from __future__ import annotations

from typing import Protocol


class ModelAdapter(Protocol):
    """Each adapter wraps one model CLI/API and exposes a uniform `invoke`."""

    name: str

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout_s: float = 1800.0,
        model: str | None = None,
        effort: str | None = None,
        cwd: str | None = None,
    ) -> str:
        """Run the model once and return its full text response.

        ``model`` and ``effort`` are optional pass-throughs to the underlying
        CLI. ``None`` means "use the CLI's own default"; non-None values are
        translated into the CLI's flag syntax by each adapter. The set of
        valid values is governed by the CLI itself — invalid values are
        rejected at invocation time.

        ``cwd`` is the working directory the underlying CLI should treat as
        its workspace (i.e. what its file-reading tools resolve relative
        paths against). Used by the review-loop to expose the project to
        the model so siblings can be read on demand instead of inlined.
        ``None`` falls through to the subprocess's inherited cwd.

        Implementations must raise ``SubprocessError`` (from
        ``claude_tools.common.subprocess_runner``) on failure.
        """
        ...
