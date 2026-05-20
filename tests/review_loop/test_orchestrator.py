"""Tests for review_loop.orchestrator (using fake adapters; no real CLIs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

import claude_tools.review_loop.orchestrator as orch
from claude_tools.review_loop.orchestrator import (
    LoopConfig,
    _atomic_write,
    _extract_file_body,
    run_loop,
)


def test_extract_file_body_with_markers() -> None:
    raw = "noise\n<<<FILE>>>\nhello\nworld\n<<<END>>>\nrationale"
    assert _extract_file_body(raw) == "hello\nworld"


def test_extract_file_body_no_markers_falls_back() -> None:
    assert _extract_file_body("just the body") == "just the body"


def test_atomic_write_replaces(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    target.write_text("old")
    _atomic_write(target, "new")
    assert target.read_text() == "new"
    # No tmp turds
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftovers == []


@dataclass
class FakeAdapter:
    name: str
    responses: list[str]
    calls: list[tuple[str, str]]
    # Records the model/effort kwargs each invocation was called with, so
    # tests can assert the orchestrator threaded engine settings correctly.
    invocations: list[dict] = field(default_factory=list)

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        timeout_s: float = 1800.0,
        model: str | None = None,
        effort: str | None = None,
    ) -> str:
        self.calls.append((system_prompt, user_prompt))
        self.invocations.append({"model": model, "effort": effort})
        if not self.responses:
            raise AssertionError("Fake adapter ran out of responses")
        return self.responses.pop(0)


@pytest.fixture
def fake_adapters(monkeypatch: pytest.MonkeyPatch):
    state: dict[str, FakeAdapter] = {}

    def fake_get_adapter(name: str):
        return state[name]

    monkeypatch.setattr(orch, "get_adapter", fake_get_adapter)
    return state


def test_converges_on_reviewer_approval_of_original(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    """Reviewer approves the original file on its first pass; author never runs."""
    target = tmp_path / "paper.md"
    target.write_text("original body\n")

    fake_adapters["claude"] = FakeAdapter(name="claude", responses=[], calls=[])
    fake_adapters["codex"] = FakeAdapter(
        name="codex",
        responses=["No remaining errors. <approved/>"],
        calls=[],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=4)
    result = run_loop(cfg)

    assert result.final_converged is True
    assert "approved" in result.final_reason.lower()
    # Original file is untouched because the reviewer-first loop stops before
    # the author is invoked.
    assert target.read_text() == "original body\n"
    assert fake_adapters["claude"].calls == []
    assert len(result.iterations) == 1


def test_converges_after_one_revision(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    """Reviewer flags the original, author rewrites once, reviewer then approves."""
    target = tmp_path / "paper.md"
    target.write_text("original body\n")

    fake_adapters["claude"] = FakeAdapter(
        name="claude",
        responses=["<<<FILE>>>\nrevised body 1\n<<<END>>>"],
        calls=[],
    )
    fake_adapters["codex"] = FakeAdapter(
        name="codex",
        responses=["Issue: missing intro", "No remaining errors. <approved/>"],
        calls=[],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=4)
    result = run_loop(cfg)

    assert result.final_converged is True
    assert "approved" in result.final_reason.lower()
    assert target.read_text() == "revised body 1"
    # Iter 1: codex flags + claude rewrites. Iter 2: codex approves, no author.
    assert len(result.iterations) == 2
    assert len(fake_adapters["claude"].calls) == 1
    assert len(fake_adapters["codex"].calls) == 2


def test_hits_max_iterations(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    """Reviewer never approves; loop terminates by hitting max_iterations."""
    target = tmp_path / "paper.md"
    target.write_text("body\n")

    fake_adapters["claude"] = FakeAdapter(
        name="claude",
        responses=[
            "<<<FILE>>>\nrev1 " + "X" * 100 + "\n<<<END>>>",
            "<<<FILE>>>\nrev2 " + "Y" * 500 + "\n<<<END>>>",
        ],
        calls=[],
    )
    fake_adapters["codex"] = FakeAdapter(
        name="codex",
        responses=["Issue: foo", "Issue: bar"],
        calls=[],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=2)
    result = run_loop(cfg)

    assert result.final_converged is False
    assert "max iterations" in result.final_reason.lower()
    assert len(result.iterations) == 2
    # Each iteration runs both adapters once (codex flags issues, claude rewrites).
    assert len(fake_adapters["codex"].calls) == 2
    assert len(fake_adapters["claude"].calls) == 2


def test_dry_run_does_not_invoke(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    target = tmp_path / "paper.md"
    original = "untouched\n"
    target.write_text(original)

    fake_adapters["claude"] = FakeAdapter(name="claude", responses=[], calls=[])
    fake_adapters["codex"] = FakeAdapter(name="codex", responses=[], calls=[])

    cfg = LoopConfig(
        target=target, author="claude", reviewer="codex",
        max_iterations=3, dry_run=True,
    )
    result = run_loop(cfg)

    assert fake_adapters["claude"].calls == []
    assert fake_adapters["codex"].calls == []
    assert target.read_text() == original
    # Dry-run writes the first prompt the orchestrator would send. Under the
    # reviewer-first loop, that's the reviewer prompt.
    prompts = sorted(p.name for p in result.run_dir.iterdir())
    assert any("reviewer-prompt" in n for n in prompts)


def test_engine_settings_threaded_to_adapters(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    """claude_model/effort and codex_model/effort follow the engine, not the role."""
    target = tmp_path / "paper.md"
    target.write_text("body\n")

    fake_adapters["claude"] = FakeAdapter(
        name="claude",
        responses=["<<<FILE>>>\nrev1\n<<<END>>>"],
        calls=[],
    )
    fake_adapters["codex"] = FakeAdapter(
        name="codex",
        responses=["Issue: foo", "No remaining errors. <approved/>"],
        calls=[],
    )

    cfg = LoopConfig(
        target=target,
        author="claude",
        reviewer="codex",
        max_iterations=2,
        claude_model="opus",
        claude_effort="high",
        codex_model="gpt-5.5",
        codex_effort="xhigh",
    )
    result = run_loop(cfg)

    assert result.final_converged is True
    # One Claude call (author rewrite) with the Claude engine settings.
    assert fake_adapters["claude"].invocations == [
        {"model": "opus", "effort": "high"},
    ]
    # Two Codex calls (reviewer iter 1 + reviewer iter 2 approval), both with Codex settings.
    assert fake_adapters["codex"].invocations == [
        {"model": "gpt-5.5", "effort": "xhigh"},
        {"model": "gpt-5.5", "effort": "xhigh"},
    ]


def test_engine_settings_default_to_none(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    """When the user sets nothing, adapters receive model=None and effort=None."""
    target = tmp_path / "paper.md"
    target.write_text("body\n")

    fake_adapters["claude"] = FakeAdapter(name="claude", responses=[], calls=[])
    fake_adapters["codex"] = FakeAdapter(
        name="codex",
        responses=["No remaining errors. <approved/>"],
        calls=[],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=1)
    run_loop(cfg)

    assert fake_adapters["codex"].invocations == [{"model": None, "effort": None}]
