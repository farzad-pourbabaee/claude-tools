"""Model adapters for the review-loop orchestrator."""

from claude_tools.review_loop.adapters.base import ModelAdapter
from claude_tools.review_loop.adapters.claude import ClaudeAdapter
from claude_tools.review_loop.adapters.codex import CodexAdapter

__all__ = ["ModelAdapter", "ClaudeAdapter", "CodexAdapter"]


def get_adapter(name: str) -> ModelAdapter:
    """Factory: 'claude' → ClaudeAdapter, 'codex' → CodexAdapter."""
    key = name.lower().strip()
    if key == "claude":
        return ClaudeAdapter()
    if key == "codex":
        return CodexAdapter()
    raise ValueError(f"Unknown adapter: {name!r} (expected 'claude' or 'codex')")
