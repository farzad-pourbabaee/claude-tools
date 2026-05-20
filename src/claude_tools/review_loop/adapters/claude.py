"""Claude Code CLI adapter: shells out to `claude -p ...`.

Uses the user's authenticated Claude Code session (subscription-backed quota).
"""

from __future__ import annotations

from dataclasses import dataclass

from claude_tools.common.subprocess_runner import run_capture


@dataclass
class ClaudeAdapter:
    """Wraps `claude -p` for non-interactive prompts."""

    name: str = "claude"

    def invoke(self, system_prompt: str, user_prompt: str, *, timeout_s: float = 1800.0) -> str:
        # `claude -p PROMPT` runs a single-turn non-interactive query and prints the response.
        # We pass the prompt as a positional arg; system prompt is prepended into the user
        # prompt because the CLI's `--system` flag varies across versions.
        combined = f"<system>\n{system_prompt}\n</system>\n\n{user_prompt}"
        result = run_capture(
            ["claude", "-p", combined],
            timeout_s=timeout_s,
        )
        return result.stdout.strip()
