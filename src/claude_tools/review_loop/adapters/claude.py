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

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout_s: float = 1800.0,
        model: str | None = None,
        effort: str | None = None,
    ) -> str:
        # `claude -p PROMPT` runs a single-turn non-interactive query and prints the response.
        # We pass the prompt as a positional arg; system prompt is prepended into the user
        # prompt because the CLI's `--system` flag varies across versions.
        combined = f"<system>\n{system_prompt}\n</system>\n\n{user_prompt}"
        argv: list[str] = ["claude"]
        if model is not None:
            argv += ["--model", model]
        if effort is not None:
            argv += ["--effort", effort]
        argv += ["-p", combined]
        result = run_capture(argv, timeout_s=timeout_s)
        return result.stdout.strip()
