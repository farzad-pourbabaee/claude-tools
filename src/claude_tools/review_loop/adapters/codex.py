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
        # `codex exec PROMPT` runs a single-turn non-interactive query and prints
        # the final assistant message to stdout. We prepend a system block into
        # the user prompt for compatibility across CLI versions.
        combined = f"<system>\n{system_prompt}\n</system>\n\n{user_prompt}"
        # Top-level codex flags must come BEFORE the `exec` subcommand. `-m`
        # and `-c` are both top-level options per `codex --help`.
        argv: list[str] = ["codex"]
        if model is not None:
            argv += ["-m", model]
        if effort is not None:
            # Codex doesn't expose a dedicated --effort flag; the reasoning
            # effort is a config override under `model_reasoning_effort`.
            argv += ["-c", f"model_reasoning_effort={effort}"]
        # --skip-git-repo-check: codex exec otherwise refuses to run outside a
        # trusted git repo. Our review-loop targets are often standalone files
        # (e.g. research notes in a non-git directory); the prompt is read-only
        # so the safety guard is unnecessary here.
        argv += ["exec", "--skip-git-repo-check"]
        # -C/--cd is an exec-level flag that sets the agent's working root, so
        # the model's file tools resolve relative paths against the project.
        # We also set the subprocess cwd to the same directory for belt-and-
        # suspenders symmetry with the Claude adapter.
        if cwd is not None:
            argv += ["-C", cwd]
        argv += [combined]
        result = run_capture(argv, timeout_s=timeout_s, cwd=cwd)
        return result.stdout.strip()
