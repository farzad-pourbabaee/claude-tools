"""Tests for review_loop.orchestrator (using fake adapters; no real CLIs).

The orchestrator under test now drives two persistent sessions (one per
adapter) and reads the working file from disk after each author turn to
compute changed line ranges. The FakeAdapter below honors that contract:
its ``send`` callable can take a side effect that mutates the working file,
so the diff path is exercised the same way it is in production.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import claude_tools.review_loop.orchestrator as orch
from claude_tools.review_loop.orchestrator import (
    LoopConfig,
    _atomic_write,
    _working_target_path,
    run_loop,
)

Effect = Callable[[], None] | None


@dataclass
class FakeTurn:
    """One scripted turn: the prose to return plus an optional file mutation."""

    response: str
    effect: Effect = None


@dataclass
class FakeAdapter:
    """Fakes the persistent-session interface (ModelAdapter protocol)."""

    name: str
    role: str
    turns: list[FakeTurn] = field(default_factory=list)
    sends: list[dict] = field(default_factory=list)
    session_id: str | None = None
    last_run: object = None
    # Constructor kwargs the orchestrator threaded in (recorded for assertions).
    init_kwargs: dict = field(default_factory=dict)

    def send(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        on_event=None,
    ) -> str:
        self.sends.append({
            "user_prompt": user_prompt,
            "system_prompt": system_prompt,
        })
        if self.session_id is None:
            self.session_id = f"fake-sid-{self.name}-{self.role}"
        if not self.turns:
            raise AssertionError(
                f"FakeAdapter({self.name}/{self.role}) ran out of scripted turns"
            )
        turn = self.turns.pop(0)
        if turn.effect is not None:
            turn.effect()
        return turn.response


@pytest.fixture
def fake_adapters(monkeypatch: pytest.MonkeyPatch):
    """Override get_adapter so the orchestrator gets per-role FakeAdapters.

    Test code populates the dict keyed by role ("author"/"reviewer") before
    calling run_loop. Engine settings (model/effort/cwd/timeout) the
    orchestrator passes in are recorded on the adapter's ``init_kwargs`` for
    inspection.
    """
    state: dict[str, FakeAdapter] = {}

    def fake_get_adapter(name: str, *, role: str, **kwargs):
        adapter = state[role]
        adapter.init_kwargs = {"name": name, **kwargs}
        return adapter

    monkeypatch.setattr(orch, "get_adapter", fake_get_adapter)
    return state


def _edit_to(path: Path, new_content: str) -> Effect:
    """Build an effect that overwrites ``path`` with ``new_content``."""

    def _do() -> None:
        path.write_text(new_content, encoding="utf-8")

    return _do


# --- Pure helpers ---------------------------------------------------------


def test_atomic_write_replaces(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    target.write_text("old")
    _atomic_write(target, "new")
    assert target.read_text() == "new"
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftovers == []


def test_working_target_path_inserts_suffix_before_extension(tmp_path: Path) -> None:
    assert _working_target_path(tmp_path / "paper.md") == tmp_path / "paper_loop_reviewed.md"
    assert _working_target_path(tmp_path / "a.b.tex") == tmp_path / "a.b_loop_reviewed.tex"
    assert _working_target_path(tmp_path / "NOTES") == tmp_path / "NOTES_loop_reviewed"


# --- End-to-end orchestrator behavior -------------------------------------


def test_converges_on_reviewer_approval_of_original(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    target = tmp_path / "paper.md"
    target.write_text("original body\n")

    fake_adapters["author"] = FakeAdapter(name="claude", role="author", turns=[])
    fake_adapters["reviewer"] = FakeAdapter(
        name="codex",
        role="reviewer",
        turns=[FakeTurn(response="No remaining errors. <approved/>")],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=4)
    result = run_loop(cfg)

    assert result.final_converged is True
    assert "approved" in result.final_reason.lower()
    assert target.read_text() == "original body\n"
    working = tmp_path / "paper_loop_reviewed.md"
    assert working.read_text() == "original body\n"
    assert fake_adapters["author"].sends == []
    assert len(result.iterations) == 1


def test_converges_after_one_revision(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    target = tmp_path / "paper.md"
    target.write_text("original body\n")
    working = tmp_path / "paper_loop_reviewed.md"

    fake_adapters["author"] = FakeAdapter(
        name="claude",
        role="author",
        turns=[
            FakeTurn(
                response="Added an intro paragraph as requested.",
                effect=_edit_to(working, "intro\n\noriginal body\n"),
            ),
        ],
    )
    fake_adapters["reviewer"] = FakeAdapter(
        name="codex",
        role="reviewer",
        turns=[
            FakeTurn(response="Issue: missing intro paragraph."),
            FakeTurn(response="No remaining errors. <approved/>"),
        ],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=4)
    result = run_loop(cfg)

    assert result.final_converged is True
    assert "approved" in result.final_reason.lower()
    # Original untouched, working has the revision.
    assert target.read_text() == "original body\n"
    assert working.read_text() == "intro\n\noriginal body\n"
    assert len(result.iterations) == 2
    assert len(fake_adapters["author"].sends) == 1
    assert len(fake_adapters["reviewer"].sends) == 2


def test_hits_max_iterations(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    target = tmp_path / "paper.md"
    target.write_text("body\n")
    working = tmp_path / "paper_loop_reviewed.md"

    # Author makes substantial changes each round so stability check doesn't trip.
    fake_adapters["author"] = FakeAdapter(
        name="claude",
        role="author",
        turns=[
            FakeTurn(response="rev1 summary", effect=_edit_to(working, "rev1 " + "X" * 200)),
            FakeTurn(response="rev2 summary", effect=_edit_to(working, "rev2 " + "Y" * 200)),
        ],
    )
    fake_adapters["reviewer"] = FakeAdapter(
        name="codex",
        role="reviewer",
        turns=[
            FakeTurn(response="Issue: foo"),
            FakeTurn(response="Issue: bar"),
        ],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=2)
    result = run_loop(cfg)

    assert result.final_converged is False
    assert "max iterations" in result.final_reason.lower()
    assert len(result.iterations) == 2
    assert len(fake_adapters["reviewer"].sends) == 2
    assert len(fake_adapters["author"].sends) == 2


def test_stops_on_author_byte_stability(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    """Two consecutive no-op author turns trip the stability check.

    Iteration 1's author turn establishes the baseline; iteration 2's
    no-op author turn yields a working file byte-identical to iter-1's
    end state, so the orchestrator declares stability and stops.
    """
    target = tmp_path / "paper.md"
    target.write_text("body 1234567890\n")

    fake_adapters["author"] = FakeAdapter(
        name="claude",
        role="author",
        turns=[
            # Both turns are no-ops: author disagrees and doesn't edit.
            FakeTurn(response="I disagree with this feedback; not changing anything."),
            FakeTurn(response="Still disagreeing; not changing anything."),
        ],
    )
    fake_adapters["reviewer"] = FakeAdapter(
        name="codex",
        role="reviewer",
        turns=[
            FakeTurn(response="Issue: foo"),
            FakeTurn(response="Issue: still foo"),
        ],
    )

    cfg = LoopConfig(
        target=target, author="claude", reviewer="codex",
        max_iterations=4, diff_threshold_bytes=4,
    )
    result = run_loop(cfg)

    assert result.final_converged is True
    assert "stable" in result.final_reason.lower() or "identical" in result.final_reason.lower()


def test_dry_run_does_not_invoke(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    target = tmp_path / "paper.md"
    original = "untouched\n"
    target.write_text(original)

    fake_adapters["author"] = FakeAdapter(name="claude", role="author", turns=[])
    fake_adapters["reviewer"] = FakeAdapter(name="codex", role="reviewer", turns=[])

    cfg = LoopConfig(
        target=target, author="claude", reviewer="codex",
        max_iterations=3, dry_run=True,
    )
    result = run_loop(cfg)

    assert fake_adapters["author"].sends == []
    assert fake_adapters["reviewer"].sends == []
    assert target.read_text() == original
    working = tmp_path / "paper_loop_reviewed.md"
    assert working.read_text() == original
    # Dry-run writes the initial prompts the loop would send.
    prompts = sorted(p.name for p in result.run_dir.iterdir())
    assert any("msg-to-reviewer" in n for n in prompts)


def test_engine_settings_threaded_to_adapters(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    """claude_model/effort and codex_model/effort follow the engine, not the role."""
    target = tmp_path / "paper.md"
    target.write_text("body\n")
    working = tmp_path / "paper_loop_reviewed.md"

    fake_adapters["author"] = FakeAdapter(
        name="claude",
        role="author",
        turns=[FakeTurn(response="done", effect=_edit_to(working, "revised\n"))],
    )
    fake_adapters["reviewer"] = FakeAdapter(
        name="codex",
        role="reviewer",
        turns=[
            FakeTurn(response="Issue: foo"),
            FakeTurn(response="No remaining errors. <approved/>"),
        ],
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
    expected_cwd = str(tmp_path.resolve())
    assert fake_adapters["author"].init_kwargs == {
        "name": "claude",
        "model": "opus",
        "effort": "high",
        "cwd": expected_cwd,
        "timeout_s": cfg.per_call_timeout_s,
    }
    assert fake_adapters["reviewer"].init_kwargs == {
        "name": "codex",
        "model": "gpt-5.5",
        "effort": "xhigh",
        "cwd": expected_cwd,
        "timeout_s": cfg.per_call_timeout_s,
    }


def test_engine_settings_default_to_none(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    target = tmp_path / "paper.md"
    target.write_text("body\n")

    fake_adapters["author"] = FakeAdapter(name="claude", role="author", turns=[])
    fake_adapters["reviewer"] = FakeAdapter(
        name="codex",
        role="reviewer",
        turns=[FakeTurn(response="No remaining errors. <approved/>")],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=1)
    run_loop(cfg)

    assert fake_adapters["reviewer"].init_kwargs["model"] is None
    assert fake_adapters["reviewer"].init_kwargs["effort"] is None


def test_reviewer_prompts_never_inline_file_body(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    """The target file body is never inlined into reviewer prompts — the
    reviewer is pointed at the path on disk and reads it via its Read tool.
    Iter-1 still attaches the system prompt; iter-N (N>1) sees only deltas
    and no system prompt (the session carries it)."""
    target = tmp_path / "paper.md"
    target.write_text("UNIQUE_BODY_MARKER content\n")
    working = tmp_path / "paper_loop_reviewed.md"

    fake_adapters["author"] = FakeAdapter(
        name="claude",
        role="author",
        turns=[
            FakeTurn(
                response="Reworked the intro per your feedback.",
                effect=_edit_to(working, "REVISED_BODY_MARKER content\n"),
            ),
        ],
    )
    fake_adapters["reviewer"] = FakeAdapter(
        name="codex",
        role="reviewer",
        turns=[
            FakeTurn(response="Issue: rewrite the intro."),
            FakeTurn(response="No remaining errors. <approved/>"),
        ],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=4)
    run_loop(cfg)

    iter1_reviewer = fake_adapters["reviewer"].sends[0]["user_prompt"]
    iter2_reviewer = fake_adapters["reviewer"].sends[1]["user_prompt"]

    # Iter-1 points at the path but does NOT inline the body; system prompt
    # is attached for the first turn so the persistent session has it.
    assert "UNIQUE_BODY_MARKER" not in iter1_reviewer
    assert str(working.resolve()) in iter1_reviewer
    assert fake_adapters["reviewer"].sends[0]["system_prompt"] is not None
    # Iter-2 also does not inline the body — only delta info.
    assert "REVISED_BODY_MARKER" not in iter2_reviewer
    assert "UNIQUE_BODY_MARKER" not in iter2_reviewer
    # Iter-2 sees the author's prose summary and orchestrator-computed ranges.
    assert "Reworked the intro" in iter2_reviewer
    assert "line" in iter2_reviewer.lower()
    # System prompt is only attached on the first turn (the session carries it).
    assert fake_adapters["reviewer"].sends[1]["system_prompt"] is None


def test_persistent_session_id_reused_across_turns(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    """Each adapter's session id must persist across iterations.

    The orchestrator does not look at session_id directly, but production
    adapters use it to drive --resume; this test guards the contract that the
    adapter is reused (not recreated) between turns.
    """
    target = tmp_path / "paper.md"
    target.write_text("body\n")
    working = tmp_path / "paper_loop_reviewed.md"

    author = FakeAdapter(
        name="claude",
        role="author",
        turns=[FakeTurn(response="ok", effect=_edit_to(working, "rev " + "X" * 200))],
    )
    reviewer = FakeAdapter(
        name="codex",
        role="reviewer",
        turns=[
            FakeTurn(response="Issue: x"),
            FakeTurn(response="No remaining errors. <approved/>"),
        ],
    )
    fake_adapters["author"] = author
    fake_adapters["reviewer"] = reviewer

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=3)
    run_loop(cfg)

    # Adapter instance is the same across turns; session id is set once.
    assert reviewer.session_id == "fake-sid-codex-reviewer"
    assert author.session_id == "fake-sid-claude-author"


def test_original_untouched_when_max_iterations_hit(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    target = tmp_path / "paper.md"
    original_body = "original body\n"
    target.write_text(original_body)
    working = tmp_path / "paper_loop_reviewed.md"

    fake_adapters["author"] = FakeAdapter(
        name="claude",
        role="author",
        turns=[
            FakeTurn(response="rev1", effect=_edit_to(working, "rev1 " + "X" * 200)),
            FakeTurn(response="rev2", effect=_edit_to(working, "rev2 " + "Y" * 200)),
        ],
    )
    fake_adapters["reviewer"] = FakeAdapter(
        name="codex",
        role="reviewer",
        turns=[
            FakeTurn(response="Issue: foo"),
            FakeTurn(response="Issue: bar"),
        ],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=2)
    run_loop(cfg)

    assert target.read_text() == original_body
    assert working.exists()
    assert working.read_text().startswith("rev2 ")


def test_siblings_are_not_inlined_in_prompt(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    """No sibling content AND no enumerated project tree leaks into prompts.

    Re-shipping unchanged sibling content on every turn was the original
    context-window blow-up. The current design just exposes the project
    root via cwd; both sides discover and read siblings on demand via their
    own tools.
    """
    target = tmp_path / "paper.md"
    target.write_text("WORKING_TOKEN body\n")
    big_sibling = tmp_path / "huge_notes.md"
    big_sibling.write_text("BIG_SIBLING_TOKEN " + "X" * 100_000)
    small_sibling = tmp_path / "tiny.md"
    small_sibling.write_text("SMALL_SIBLING_TOKEN")

    fake_adapters["author"] = FakeAdapter(name="claude", role="author", turns=[])
    fake_adapters["reviewer"] = FakeAdapter(
        name="codex",
        role="reviewer",
        turns=[FakeTurn(response="No remaining errors. <approved/>")],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=1)
    run_loop(cfg)

    reviewer_prompt = fake_adapters["reviewer"].sends[0]["user_prompt"]
    # No file contents AND no enumerated tree — the prompt only points at
    # the target path; the model uses Glob/ls to discover siblings if it
    # wants them.
    assert "WORKING_TOKEN" not in reviewer_prompt
    assert "BIG_SIBLING_TOKEN" not in reviewer_prompt
    assert "SMALL_SIBLING_TOKEN" not in reviewer_prompt
    assert "huge_notes.md" not in reviewer_prompt
    assert "tiny.md" not in reviewer_prompt
    # But the working file path IS in the prompt so the model can Read it.
    working = tmp_path / "paper_loop_reviewed.md"
    assert str(working.resolve()) in reviewer_prompt


def test_diff_artifacts_written(
    fake_adapters, tmp_path: Path, isolated_home: Path
) -> None:
    """Per-iteration diff + msg-to-* + events files appear in the run dir."""
    target = tmp_path / "paper.md"
    target.write_text("alpha\nbeta\ngamma\n")
    working = tmp_path / "paper_loop_reviewed.md"

    fake_adapters["author"] = FakeAdapter(
        name="claude",
        role="author",
        turns=[
            FakeTurn(
                response="Renamed beta to BETA.",
                effect=_edit_to(working, "alpha\nBETA\ngamma\n"),
            ),
        ],
    )
    fake_adapters["reviewer"] = FakeAdapter(
        name="codex",
        role="reviewer",
        turns=[
            FakeTurn(response="Issue: rename beta."),
            FakeTurn(response="No remaining errors. <approved/>"),
        ],
    )

    cfg = LoopConfig(target=target, author="claude", reviewer="codex", max_iterations=4)
    result = run_loop(cfg)

    names = {p.name for p in result.run_dir.iterdir()}
    assert "iter-01-msg-to-reviewer.md" in names
    assert "iter-01-msg-to-author.md" in names
    assert "iter-01-diff.md" in names
    assert "iter-01-target-after.md" in names
    # Iteration 2 (where reviewer approves) writes msg-to-reviewer but no
    # author msg because the author was never invoked.
    assert "iter-02-msg-to-reviewer.md" in names
    assert "iter-02-msg-to-author.md" not in names

    # Diff content shows the rename.
    diff = (result.run_dir / "iter-01-diff.md").read_text()
    assert "-beta" in diff
    assert "+BETA" in diff
