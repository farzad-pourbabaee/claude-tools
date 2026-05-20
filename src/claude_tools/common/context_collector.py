"""Collect read-only directory context for the author/reviewer prompts.

The author needs to *understand* the surrounding project (other .md files,
related code, layout) without editing anything other than the target file.
This module assembles that context with a token-aware budget.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Crude token estimate: 1 token ≈ 4 chars of English text. Good enough for budget gating;
# adapters can swap in a real tokenizer later.
CHARS_PER_TOKEN_ESTIMATE = 4

# Sane default extensions to include when sweeping a directory for context.
TEXT_EXTENSIONS: tuple[str, ...] = (
    ".md", ".txt", ".rst", ".tex", ".bib",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".c", ".h", ".cpp", ".hpp",
    ".toml", ".yaml", ".yml", ".json", ".cfg", ".ini",
    ".sh", ".bash", ".zsh",
)

# Directories we never descend into when gathering context.
SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    "node_modules", "dist", "build", ".idea", ".vscode", ".tox", ".mypy_cache",
})


@dataclass(frozen=True)
class ContextFile:
    path: Path           # absolute
    rel: str             # path relative to the project root
    content: str
    bytes: int


@dataclass(frozen=True)
class Context:
    project_root: Path
    target: Path
    target_content: str
    tree: str
    siblings: list[ContextFile]    # other text files included (excluding target)
    estimated_tokens: int


def _walk(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            yield Path(dirpath) / name


def _is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS


def build_tree(root: Path, max_entries: int = 200) -> str:
    """Return a flat indented listing of the project tree, truncated."""
    lines: list[str] = [str(root.name) + "/"]
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        rel = Path(dirpath).relative_to(root)
        depth = 0 if str(rel) == "." else len(rel.parts)
        prefix = "  " * depth
        for d in dirnames:
            lines.append(f"{prefix}  {d}/")
            count += 1
            if count >= max_entries:
                lines.append(f"{prefix}  ... (truncated)")
                return "\n".join(lines)
        for f in sorted(filenames):
            if f.startswith("."):
                continue
            lines.append(f"{prefix}  {f}")
            count += 1
            if count >= max_entries:
                lines.append(f"{prefix}  ... (truncated)")
                return "\n".join(lines)
    return "\n".join(lines)


def collect_context(
    target: Path,
    *,
    project_root: Path | None = None,
    max_tokens: int = 200_000,
    extensions: tuple[str, ...] | None = None,
    exclude: Iterable[Path] | None = None,
) -> Context:
    """Gather target file + sibling text files under ``project_root``.

    Files are prioritized by: target itself > files in same directory as target,
    same stem first > all other text files, most-recently-modified first. We
    drop files when the cumulative token estimate exceeds ``max_tokens``.

    ``exclude`` skips additional paths from the sibling sweep (the target is
    always excluded automatically). Used by review-loop to hide the original
    file when the loop operates on a working copy next to it.
    """
    target = target.resolve()
    if project_root is None:
        project_root = target.parent
    project_root = project_root.resolve()
    exts = extensions or TEXT_EXTENSIONS
    excluded_paths: set[Path] = (
        {p.resolve() for p in exclude} if exclude is not None else set()
    )

    target_content = target.read_text(encoding="utf-8", errors="replace")
    used_tokens = len(target_content) // CHARS_PER_TOKEN_ESTIMATE

    candidates: list[Path] = []
    for p in _walk(project_root):
        if p == target:
            continue
        if p.resolve() in excluded_paths:
            continue
        if p.suffix.lower() not in exts:
            continue
        candidates.append(p)

    target_dir = target.parent
    target_stem = target.stem

    def priority(p: Path) -> tuple[int, float]:
        # Lower tuple sorts first.
        # Group: 0 = same dir + same stem prefix, 1 = same dir, 2 = elsewhere
        if p.parent != target_dir:
            grp = 2
        elif p.stem.startswith(target_stem):
            grp = 0
        else:
            grp = 1
        # Most recently modified first within group → negate mtime.
        return (grp, -p.stat().st_mtime)

    candidates.sort(key=priority)

    siblings: list[ContextFile] = []
    for p in candidates:
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        size = len(content)
        cost = size // CHARS_PER_TOKEN_ESTIMATE
        if used_tokens + cost > max_tokens:
            continue
        used_tokens += cost
        siblings.append(
            ContextFile(
                path=p,
                rel=str(p.relative_to(project_root)),
                content=content,
                bytes=size,
            )
        )

    return Context(
        project_root=project_root,
        target=target,
        target_content=target_content,
        tree=build_tree(project_root),
        siblings=siblings,
        estimated_tokens=used_tokens,
    )
