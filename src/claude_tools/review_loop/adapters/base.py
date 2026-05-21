"""Adapter protocol: a stateful, persistent model session.

Each adapter wraps one model CLI (claude / codex) and keeps a single session
alive across many turns within one review-loop run. The orchestrator calls
``send`` once per turn; the adapter handles starting the session on the first
call and resuming it via the CLI's own session-id machinery on subsequent
calls. ``on_event`` is a live-event callback (one call per JSONL event from
the CLI's structured output stream); see ``review_loop.signals``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from claude_tools.common.streaming_runner import StreamingRunResult

EventCallback = Callable[[dict[str, Any]], None]


class ModelAdapter(Protocol):
    """A stateful wrapper around one model CLI for the duration of a loop run."""

    name: str          # engine identifier: "claude" or "codex"
    role: str          # "author" or "reviewer" (governs tool allowlist / sandbox)
    session_id: str | None  # populated after the first ``send`` call
    # Set after each ``send`` call. Holds the raw stdout lines + parsed events
    # for the most recent turn so the orchestrator can persist the event
    # stream to ``iter-NN-<side>.events.jsonl`` for forensic inspection.
    last_run: StreamingRunResult | None

    def send(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        on_event: EventCallback | None = None,
    ) -> str:
        """Send one turn to the underlying CLI. Returns the model's final text.

        On the very first call the adapter starts a fresh session (generating
        or capturing a session id and recording it in ``self.session_id``).
        On subsequent calls it resumes that session. ``system_prompt`` is only
        meaningful on the first call; resumed turns inherit the original
        system context from the persisted session.

        ``on_event`` is invoked once per parsed JSONL event from the CLI's
        structured output stream while the model is working. The full event
        stream is also stored on the returned ``LastRun`` (see concrete
        implementations) for forensic logging.

        Raises ``SubprocessError`` on CLI failure or timeout.
        """
        ...
