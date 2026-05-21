"""Claude Code CLI adapter: stateful, resumable, streaming.

Wraps ``claude -p`` for non-interactive turns and uses ``--session-id`` (first
call) + ``--resume`` (subsequent calls) to keep one persistent session alive
across all of the loop's iterations. This means the model carries its full
prior-turn memory ("I already pushed back on this issue in round 2 because…")
into each new turn without the orchestrator having to re-inline the file.

Output is consumed as a JSONL event stream (``--output-format stream-json
--verbose``) so the orchestrator can surface live progress and persist the
full transcript without buffering through end-of-turn.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from claude_tools.common.streaming_runner import StreamingRunResult, run_streaming
from claude_tools.review_loop.adapters.base import EventCallback

# Tool allowlists per role. The author needs Edit so it can rewrite the
# working file in place; the reviewer is strictly read-only so a bug in the
# model cannot accidentally damage the file under review.
_AUTHOR_TOOLS = "Edit,Read,Glob,Grep"
_REVIEWER_TOOLS = "Read,Glob,Grep"


@dataclass
class ClaudeAdapter:
    """Stateful wrapper around ``claude -p`` for one role of one loop run."""

    role: str                              # "author" | "reviewer"
    model: str | None = None               # CLI default if None
    effort: str | None = None              # CLI default if None
    cwd: str | None = None                 # project root for the model's tools
    timeout_s: float = 1800.0
    name: str = "claude"
    session_id: str | None = None
    last_run: StreamingRunResult | None = field(default=None, repr=False)

    def send(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        on_event: EventCallback | None = None,
    ) -> str:
        argv = ["claude", "-p", "--output-format", "stream-json", "--verbose"]
        argv += ["--permission-mode", "acceptEdits"]
        tools = _AUTHOR_TOOLS if self.role == "author" else _REVIEWER_TOOLS
        argv += ["--allowedTools", tools]
        if self.model is not None:
            argv += ["--model", self.model]
        if self.effort is not None:
            argv += ["--effort", self.effort]

        if self.session_id is None:
            self.session_id = str(uuid.uuid4())
            argv += ["--session-id", self.session_id]
            # System prompt is embedded on the first turn; subsequent turns
            # inherit it via the persisted session.
            sysp = system_prompt or ""
            combined = (
                f"<system>\n{sysp}\n</system>\n\n{user_prompt}" if sysp else user_prompt
            )
        else:
            argv += ["--resume", self.session_id]
            combined = user_prompt

        argv += [combined]

        result = run_streaming(
            argv,
            timeout_s=self.timeout_s,
            cwd=self.cwd,
            on_event=on_event,
        )
        self.last_run = result
        return _extract_final_text(result.events)


def _extract_final_text(events: list[dict[str, Any]]) -> str:
    """Pull the model's final user-facing message text out of a Claude event list.

    Preference order:
      1. ``result`` event (final wrapper, contains a clean ``result`` string).
      2. Last ``assistant`` event with a ``text`` content block.
    Falls back to an empty string if neither is present.
    """
    for evt in reversed(events):
        if evt.get("type") == "result":
            text = evt.get("result")
            if isinstance(text, str) and text:
                return text
            break
    for evt in reversed(events):
        if evt.get("type") != "assistant":
            continue
        msg = evt.get("message", {})
        content = msg.get("content", []) or []
        for block in reversed(content):
            if block.get("type") == "text":
                t = block.get("text") or ""
                if t:
                    return t
    return ""
