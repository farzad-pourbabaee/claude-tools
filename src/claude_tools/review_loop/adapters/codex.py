"""Codex CLI adapter: shells out to `codex exec ...`.

Uses the user's authenticated Codex CLI session (subscription-backed quota).
"""

from __future__ import annotations

from dataclasses import dataclass

from claude_tools.common.subprocess_runner import run_capture


@dataclass
class CodexAdapter:
    """Wraps `codex exec` for non-interactive prompts."""

    name: str = "codex"

    def invoke(self, system_prompt: str, user_prompt: str, *, timeout_s: float = 1800.0) -> str:
        # `codex exec PROMPT` runs a single-turn non-interactive query and prints
        # the final assistant message to stdout. We prepend a system block into
        # the user prompt for compatibility across CLI versions.
        combined = f"<system>\n{system_prompt}\n</system>\n\n{user_prompt}"
        # --skip-git-repo-check: codex exec otherwise refuses to run outside a
        # trusted git repo. Our review-loop targets are often standalone files
        # (e.g. research notes in a non-git directory); the prompt is read-only
        # so the safety guard is unnecessary here.
        result = run_capture(
            ["codex", "exec", "--skip-git-repo-check", combined],
            timeout_s=timeout_s,
        )
        return result.stdout.strip()
