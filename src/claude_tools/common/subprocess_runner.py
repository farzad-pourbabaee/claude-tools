"""Subprocess wrapper with stdin/stdout capture and timeouts.

Used by model adapters that shell out to ``claude -p`` and ``codex exec``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


class SubprocessError(RuntimeError):
    """Raised when a subprocess fails (non-zero exit) or times out."""


@dataclass(frozen=True)
class RunResult:
    stdout: str
    stderr: str
    returncode: int
    duration_s: float


def run_capture(
    argv: list[str],
    *,
    stdin: str | None = None,
    timeout_s: float | None = None,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> RunResult:
    """Run ``argv``, capture stdout+stderr as text, raise on non-zero exit or timeout.

    Returns a RunResult on success. Use this everywhere we shell out to
    external CLIs so error handling is uniform.
    """
    import time

    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SubprocessError(
            f"Command timed out after {timeout_s}s: {' '.join(argv)}"
        ) from exc
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        raise SubprocessError(
            f"Command failed (exit {completed.returncode}): {' '.join(argv)}\n"
            f"--- stderr ---\n{completed.stderr}"
        )
    return RunResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
        duration_s=elapsed,
    )
