"""Popen-based runner that streams stdout line-by-line.

Used by the review-loop adapters to consume each model CLI's structured event
stream (``codex exec --json`` and ``claude -p --output-format stream-json``) as
the model is still working — so the orchestrator can surface live progress
("reviewer is reading paper.md", "author is editing lines 42-67") to the user
instead of only printing the final blob at end-of-turn.

This is intentionally a separate function from ``run_capture``: that one is
correct for "run a command, give me its full output, fail loudly on non-zero,"
while this one is correct for "stream stdout while the process runs, hand each
line to a callback, then return the lot."
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from claude_tools.common.subprocess_runner import SubprocessError

# Event callback contract: the runner calls this once per parsed JSONL line
# from stdout. ``event`` is the parsed JSON object (typically a dict). Raise
# nothing the runner can't recover from; the runner ignores callback errors.
EventCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class StreamingRunResult:
    raw_lines: list[str]
    events: list[dict[str, Any]]
    stderr: str
    returncode: int
    duration_s: float


def run_streaming(
    argv: list[str],
    *,
    stdin: str | None = None,
    timeout_s: float | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    on_event: EventCallback | None = None,
) -> StreamingRunResult:
    """Run ``argv`` and stream stdout line-by-line to ``on_event``.

    Each stdout line is appended to ``result.raw_lines``. Lines that parse as
    JSON are also appended to ``result.events`` and passed to ``on_event`` if
    provided. Non-JSON lines are retained in ``raw_lines`` but skipped for
    ``on_event``; this is defensive against CLIs that occasionally interleave
    plain-text status output in their JSON stream.

    Raises ``SubprocessError`` on timeout or non-zero exit (mirroring
    ``run_capture``'s contract so adapter call sites can handle one failure
    type).
    """
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=cwd,
        bufsize=1,  # line-buffered
    )

    raw_lines: list[str] = []
    events: list[dict[str, Any]] = []
    stderr_chunks: list[str] = []
    timed_out = False

    # Drain stderr in a background thread to avoid the classic Popen deadlock
    # where stderr fills its OS pipe buffer while we're blocked reading stdout.
    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for chunk in proc.stderr:
            stderr_chunks.append(chunk)

    err_thread = threading.Thread(target=_drain_stderr, daemon=True)
    err_thread.start()

    # Wall-clock timer that kills the child if it overruns. We can't rely on
    # ``proc.wait(timeout=...)`` alone because the stdout-iteration loop blocks
    # until EOF and a silent child (no stdout, e.g. ``sleep 5``) never reaches
    # the wait() call. The timer flips a flag and kills the process; the for
    # loop then exits naturally and we raise.
    timer: threading.Timer | None = None
    if timeout_s is not None:
        def _on_timeout() -> None:
            nonlocal timed_out
            timed_out = True
            with contextlib.suppress(ProcessLookupError):
                proc.kill()

        timer = threading.Timer(timeout_s, _on_timeout)
        timer.daemon = True
        timer.start()

    # Feed stdin once if provided, then close so the child sees EOF.
    if stdin is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin)
        finally:
            proc.stdin.close()

    # Read stdout line-by-line on the main thread.
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            raw_lines.append(line)
            stripped = line.strip()
            if not stripped:
                continue
            try:
                evt = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(evt, dict):
                events.append(evt)
                if on_event is not None:
                    # A bad callback should not poison the run. The raw event
                    # is still recorded in ``events`` and the JSONL file, so
                    # the user can diagnose offline.
                    with contextlib.suppress(Exception):
                        on_event(evt)

        rc = proc.wait()
    finally:
        if timer is not None:
            timer.cancel()
        err_thread.join(timeout=1.0)

    elapsed = time.monotonic() - started
    stderr = "".join(stderr_chunks)
    if timed_out:
        raise SubprocessError(
            f"Command timed out after {timeout_s}s: {' '.join(argv)}"
        )
    if rc != 0:
        raise SubprocessError(
            f"Command failed (exit {rc}): {' '.join(argv)}\n--- stderr ---\n{stderr}"
        )
    return StreamingRunResult(
        raw_lines=raw_lines,
        events=events,
        stderr=stderr,
        returncode=rc,
        duration_s=elapsed,
    )
