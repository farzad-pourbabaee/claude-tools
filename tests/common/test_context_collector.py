"""Tests for claude_tools.common.context_collector."""

from __future__ import annotations

from pathlib import Path

from claude_tools.common import context_collector as cc


def _write(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def test_collects_target_and_text_siblings(tmp_path: Path) -> None:
    target = _write(tmp_path / "paper.md", "target body")
    _write(tmp_path / "notes.md", "sibling notes")
    _write(tmp_path / "draft.tex", "tex")
    _write(tmp_path / "image.png", "binary-skip")  # png skipped (not in TEXT_EXTENSIONS)

    ctx = cc.collect_context(target, max_tokens=1_000_000)

    rels = {f.rel for f in ctx.siblings}
    assert "notes.md" in rels
    assert "draft.tex" in rels
    assert "image.png" not in rels
    assert ctx.target_content == "target body"
    assert ctx.estimated_tokens > 0


def test_skips_dot_dirs(tmp_path: Path) -> None:
    target = _write(tmp_path / "paper.md", "x")
    _write(tmp_path / ".git" / "config", "should-skip")
    _write(tmp_path / "__pycache__" / "junk.py", "should-skip")
    _write(tmp_path / "src" / "tool.py", "include")

    ctx = cc.collect_context(target, max_tokens=1_000_000)
    rels = {f.rel for f in ctx.siblings}
    assert any(r.endswith("tool.py") for r in rels)
    assert not any(".git" in r for r in rels)
    assert not any("__pycache__" in r for r in rels)


def test_budget_drops_low_priority_files(tmp_path: Path) -> None:
    # target dominates the budget; nothing else fits.
    target = _write(tmp_path / "paper.md", "X" * 4_000)  # ~1000 tokens
    _write(tmp_path / "other.md", "Y" * 4_000)            # ~1000 tokens
    ctx = cc.collect_context(target, max_tokens=1_100)    # only target fits
    assert ctx.siblings == []


def test_priority_same_dir_same_stem_first(tmp_path: Path) -> None:
    target = _write(tmp_path / "paper.md", "x")
    _write(tmp_path / "paper-notes.md", "high priority")
    _write(tmp_path / "subdir" / "elsewhere.md", "low priority")

    ctx = cc.collect_context(target, max_tokens=1_000_000)
    assert ctx.siblings[0].rel == "paper-notes.md"


def test_build_tree_includes_target_and_skips_dot_dirs(tmp_path: Path) -> None:
    _write(tmp_path / "paper.md", "x")
    _write(tmp_path / ".git" / "config", "skip")
    _write(tmp_path / "src" / "tool.py", "x")
    out = cc.build_tree(tmp_path)
    assert "paper.md" in out
    assert "src/" in out
    assert ".git" not in out


def test_build_tree_honors_exclude(tmp_path: Path) -> None:
    keep = _write(tmp_path / "keep.md", "x")
    skip = _write(tmp_path / "skip.md", "x")
    out = cc.build_tree(tmp_path, exclude=[skip])
    assert keep.name in out
    assert skip.name not in out


def test_collect_review_context_returns_target_and_tree_only(tmp_path: Path) -> None:
    target = _write(tmp_path / "paper.md", "TARGET_BODY")
    _write(tmp_path / "sibling.md", "SIBLING_BODY " + "Z" * 50_000)
    _write(tmp_path / ".git" / "config", "skip")

    rc = cc.collect_review_context(target)

    # The target's content IS captured (it's inlined by the orchestrator).
    assert rc.target_content == "TARGET_BODY"
    # The tree lists the sibling so the model knows it exists.
    assert "sibling.md" in rc.tree
    # No siblings dataclass field — by construction this context type does
    # not carry sibling file contents.
    assert not hasattr(rc, "siblings")
    # project_root defaults to the target's parent dir.
    assert rc.project_root == tmp_path.resolve()


def test_collect_review_context_excludes_files_from_tree(tmp_path: Path) -> None:
    target = _write(tmp_path / "paper_loop_reviewed.md", "x")
    original = _write(tmp_path / "paper.md", "x")
    _write(tmp_path / "other.md", "x")

    rc = cc.collect_review_context(target, exclude=[original])

    assert "paper_loop_reviewed.md" in rc.tree
    assert "other.md" in rc.tree
    # The excluded original is hidden. "paper.md" is not a substring of
    # "paper_loop_reviewed.md", so the absence is unambiguous.
    assert "paper.md" not in rc.tree
