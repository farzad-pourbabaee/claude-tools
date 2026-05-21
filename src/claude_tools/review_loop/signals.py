"""Live progress signals from the author/reviewer event streams.

Both ``claude -p --output-format stream-json`` and ``codex exec --json`` emit a
JSONL event stream while the model is working. This module converts a single
event into at most one short console line so the user can see what each side
is doing (reading siblings, calling tools, thinking, replying) as it happens,
instead of waiting for the full transcript at end-of-turn.

The full raw event stream is still persisted to disk by the orchestrator
(``iter-NN-<side>.events.jsonl``); the printer here is purely cosmetic.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any

from rich.console import Console

# Maximum chars of any free-text field we surface on a single line. Keeps the
# terminal from drowning in giant thinking dumps mid-loop.
MAX_LINE_CHARS = 100

# Color tags applied to the side label so author/reviewer are easy to scan in
# a mixed stream.
SIDE_COLOR = {
    "author": "cyan",
    "reviewer": "magenta",
}

# Shell wrapper prefixes that codex/claude prepend to model-generated commands.
# Stripped from the displayed signal line — the wrapper is noise, not signal.
_SHELL_WRAPPERS: tuple[str, ...] = (
    "/bin/zsh -lc ", "/bin/bash -lc ", "/bin/sh -lc ",
    "/bin/zsh -c ",  "/bin/bash -c ",  "/bin/sh -c ",
    "zsh -lc ",      "bash -lc ",      "sh -lc ",
    "zsh -c ",       "bash -c ",       "sh -c ",
)


def _truncate(s: str, limit: int = MAX_LINE_CHARS) -> str:
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _basename(path: str) -> str:
    """Return just the filename — full paths are noise in the signal stream."""
    return os.path.basename(path) if path else ""


def _strip_shell_wrapper(cmd: str) -> str:
    """Drop ``/bin/zsh -lc 'X'`` → ``X``; quotes around the inner command too."""
    s = cmd.strip()
    for pref in _SHELL_WRAPPERS:
        if s.startswith(pref):
            s = s[len(pref):].strip()
            break
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1].strip()
    return s


def format_duration(seconds: float) -> str:
    """Compact human duration: ``12.3s`` or ``2m 05s``."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    total = int(round(seconds))
    m, s = divmod(total, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def _format_claude_event(event: dict[str, Any]) -> str | None:
    """Render one Claude stream-json event into a one-line summary, or None."""
    et = event.get("type")
    if et == "assistant":
        msg = event.get("message", {})
        for block in msg.get("content", []) or []:
            bt = block.get("type")
            if bt == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input", {}) or {}
                detail = _summarize_tool_input(name, inp)
                return f"tool: {name}({detail})" if detail else f"tool: {name}"
            if bt == "text":
                text = (block.get("text") or "").strip()
                if not text:
                    continue
                return f"comment: {_truncate(text)}"
            if bt == "thinking":
                t = (block.get("thinking") or "").strip()
                if not t:
                    continue
                return f"thinking: {_truncate(t)}"
        return None
    if et == "result":
        # Final wrapper — skip; the inner "assistant" text already surfaced.
        return None
    return None


def _format_codex_event(event: dict[str, Any]) -> str | None:
    """Render one Codex --json event into a one-line summary, or None."""
    et = event.get("type")
    if et == "item.completed":
        item = event.get("item", {}) or {}
        it = item.get("type")
        if it == "agent_message":
            text = (item.get("text") or "").strip()
            return f"comment: {_truncate(text)}" if text else None
        if it == "agent_reasoning":
            text = (item.get("text") or item.get("summary") or "").strip()
            return f"thinking: {_truncate(text)}" if text else None
        if it == "command_execution":
            cmd = item.get("command")
            cmd_s = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd or "")
            return f"tool: bash({_truncate(_strip_shell_wrapper(cmd_s), 100)})"
        if it == "file_change":
            path = _basename(str(item.get("path") or item.get("file") or "?"))
            return f"tool: edit({path})"
        if it == "mcp_tool_call":
            name = item.get("name") or item.get("tool") or "?"
            return f"tool: mcp({name})"
        # Unknown item type — surface it minimally so we notice in logs.
        if it:
            return f"event: {it}"
        return None
    return None


def _summarize_tool_input(name: str, inp: dict[str, Any]) -> str:
    """Pick a small, useful field or two out of a Claude tool_use input dict.

    File paths are reduced to their basename — the full path is noise in the
    signal stream (every Edit on the same paper would otherwise re-emit
    ``/Users/.../My Drive/.../bounded_memory…``). Shell commands strip their
    ``/bin/zsh -lc`` wrapper for the same reason. The full input is in the
    events.jsonl for forensic inspection.
    """
    if name == "Read":
        return _basename(str(inp.get("file_path", "")))
    if name == "Edit":
        path = _basename(str(inp.get("file_path", "")))
        old = inp.get("old_string", "") or ""
        snippet = (old.splitlines() or [""])[0]
        return _truncate(f"{path} :: {snippet}", 100) if snippet else path
    if name in {"Glob", "Grep"}:
        return _truncate(str(inp.get("pattern") or inp.get("query") or ""), 100)
    if name == "Bash":
        return _truncate(_strip_shell_wrapper(str(inp.get("command", ""))), 100)
    if name == "Write":
        return _basename(str(inp.get("file_path", "")))
    # Best-effort fallback: stringify the input, truncated.
    try:
        return _truncate(json.dumps(inp, ensure_ascii=False), 100)
    except (TypeError, ValueError):
        return ""


def make_signal_printer(
    console: Console,
    *,
    iteration: int,
    side: str,
    engine: str,
) -> Callable[[dict[str, Any]], None]:
    """Return an ``on_event`` callback that prints one tagged line per event.

    ``side`` is "author" or "reviewer"; ``engine`` is "claude" or "codex".
    The closure embeds those so the orchestrator can pass the same callback
    to the streaming runner without re-stating them per call.
    """
    color = SIDE_COLOR.get(side, "white")
    prefix = f"[dim]\\[iter {iteration:02d} · [/dim][{color}]{side:<8}[/{color}][dim]][/dim]"
    formatter = _format_claude_event if engine == "claude" else _format_codex_event

    def _emit(event: dict[str, Any]) -> None:
        line = formatter(event)
        if line:
            console.print(
                f"[dim]{_now_hms()}[/dim] {prefix} {line}", highlight=False,
            )

    return _emit
