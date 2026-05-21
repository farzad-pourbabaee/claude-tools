"""Codex CLI adapter: stateful, resumable, streaming.

First turn: ``codex exec --json …`` — captures ``thread_id`` from the first
JSONL event and stores it as the session id.
Subsequent turns: ``codex exec resume --json <session-id> …`` — preserves
the full prior-turn transcript so the model carries memory across rounds.

``--skip-git-repo-check`` is set because review-loop targets are often
standalone files outside any git repo (research notes, drafts in scratch
dirs). The author runs in ``workspace-write`` sandbox so it can Edit the
working file; the reviewer is ``read-only``.

We always feed ``stdin=DEVNULL`` because codex's exec mode otherwise tries to
read stdin even when a positional prompt is supplied, which deadlocks the
subprocess when invoked from Python without explicit stdin handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from claude_tools.common.streaming_runner import StreamingRunResult, run_streaming
from claude_tools.common.subprocess_runner import SubprocessError
from claude_tools.review_loop.adapters.base import EventCallback


@dataclass
class CodexAdapter:
    """Stateful wrapper around ``codex exec`` for one role of one loop run."""

    role: str                              # "author" | "reviewer"
    model: str | None = None
    effort: str | None = None
    cwd: str | None = None
    timeout_s: float = 1800.0
    name: str = "codex"
    session_id: str | None = None
    last_run: StreamingRunResult | None = field(default=None, repr=False)

    def send(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        on_event: EventCallback | None = None,
    ) -> str:
        sandbox = "workspace-write" if self.role == "author" else "read-only"

        argv: list[str] = ["codex"]
        if self.model is not None:
            argv += ["-m", self.model]
        if self.effort is not None:
            argv += ["-c", f"model_reasoning_effort={self.effort}"]

        if self.session_id is None:
            argv += ["exec", "--json", "--skip-git-repo-check", "-s", sandbox]
            if self.cwd is not None:
                argv += ["-C", self.cwd]
            sysp = system_prompt or ""
            combined = (
                f"<system>\n{sysp}\n</system>\n\n{user_prompt}" if sysp else user_prompt
            )
            argv += [combined]
        else:
            argv += [
                "exec",
                "resume",
                "--json",
                "--skip-git-repo-check",
                "-s",
                sandbox,
                self.session_id,
                user_prompt,
            ]

        result = run_streaming(
            argv,
            timeout_s=self.timeout_s,
            cwd=self.cwd,
            on_event=on_event,
        )
        self.last_run = result

        if self.session_id is None:
            self.session_id = _extract_thread_id(result.events)
            if self.session_id is None:
                # Codex GH issue #15870: rare case where the session id is
                # never emitted (e.g. early transport failure). Fail loudly
                # so the orchestrator doesn't try to resume a non-session.
                raise SubprocessError(
                    "codex exec produced no thread.started event; cannot resume."
                )
        return _extract_final_text(result.events)


def _extract_thread_id(events: list[dict[str, Any]]) -> str | None:
    for evt in events:
        if evt.get("type") == "thread.started":
            tid = evt.get("thread_id")
            if isinstance(tid, str) and tid:
                return tid
    return None


def _extract_final_text(events: list[dict[str, Any]]) -> str:
    """Last ``item.completed`` of item type ``agent_message`` is the answer."""
    for evt in reversed(events):
        if evt.get("type") != "item.completed":
            continue
        item = evt.get("item", {}) or {}
        if item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str) and text:
                return text
    return ""
