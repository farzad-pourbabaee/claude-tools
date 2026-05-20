"""Tests for review_loop.orchestrator (using fake adapters; no real CLIs)."""

from __future__ import annotations

from dataclasses import dataclass
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

    def invoke(self, system_prompt: str, user_prompt: str, *, timeout_s: float = 600.0) -> str:
        self.calls.append((system_prompt, user_prompt))
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


def test_converges_on_reviewer_approval(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    target = tmp_path / "paper.md"
    target.write_text("original body\n")

    fake_adapters["claude"] = FakeAdapter(
        name="claude",
        responses=["<<<FILE>>>\nrevised body 1\n<<<END>>>"],
        calls=[],
    )
    fake_adapters["codex"] = FakeAdapter(
        name="codex",
        responses=["No remaining errors. <approved/>"],
        calls=[],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=4)
    result = run_loop(cfg)

    assert result.final_converged is True
    assert "approved" in result.final_reason.lower()
    assert target.read_text() == "revised body 1"
    assert len(result.iterations) == 1


def test_hits_max_iterations(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
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


def test_dry_run_does_not_invoke(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    target = tmp_path / "paper.md"
    original = "untouched\n"
    target.write_text(original)

    fake_adapters["claude"] = FakeAdapter(name="claude", responses=[], calls=[])
    fake_adapters["codex"] = FakeAdapter(name="codex", responses=[], calls=[])

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=3, dry_run=True)
    result = run_loop(cfg)

    assert fake_adapters["claude"].calls == []
    assert fake_adapters["codex"].calls == []
    assert target.read_text() == original
    # Prompt files should exist in the run dir.
    prompts = sorted(p.name for p in result.run_dir.iterdir())
    assert any("author-prompt" in n for n in prompts)
