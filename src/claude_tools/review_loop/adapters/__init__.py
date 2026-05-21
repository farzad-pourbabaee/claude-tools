"""Model adapters for the review-loop orchestrator."""

from claude_tools.review_loop.adapters.base import EventCallback, ModelAdapter
from claude_tools.review_loop.adapters.claude import ClaudeAdapter
from claude_tools.review_loop.adapters.codex import CodexAdapter

__all__ = [
    "ClaudeAdapter",
    "CodexAdapter",
    "EventCallback",
    "ModelAdapter",
    "get_adapter",
]


def get_adapter(
    name: str,
    *,
    role: str,
    model: str | None = None,
    effort: str | None = None,
    cwd: str | None = None,
    timeout_s: float = 1800.0,
) -> ModelAdapter:
    """Build a fresh, stateful adapter for one role of one loop run.

    Each adapter holds the session id for its persistent CLI session and the
    engine settings (model + effort) it was constructed with. ``role`` is
    "author" or "reviewer"; it governs the tool allowlist (Claude) or sandbox
    mode (Codex). The factory is engine-keyed by ``name`` so the orchestrator
    can pair an arbitrary author engine with an arbitrary reviewer engine.
    """
    key = name.lower().strip()
    if key == "claude":
        return ClaudeAdapter(
            role=role, model=model, effort=effort, cwd=cwd, timeout_s=timeout_s,
        )
    if key == "codex":
        return CodexAdapter(
            role=role, model=model, effort=effort, cwd=cwd, timeout_s=timeout_s,
        )
    raise ValueError(f"Unknown adapter: {name!r} (expected 'claude' or 'codex')")
