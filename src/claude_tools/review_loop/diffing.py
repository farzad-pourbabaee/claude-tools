"""Diff helpers for the review-loop.

After the author finishes an iteration, the orchestrator computes a diff
between the working file's pre- and post-turn contents. The diff serves two
purposes:

1. ``changed_line_ranges`` returns 1-indexed inclusive line ranges in the
   post-file that the author touched. These are forwarded to the reviewer as
   focusing hints ("the author edited lines 42-67 and 110-115; start there").
2. ``unified_diff_text`` produces a standard unified diff that we log to
   ``iter-NN-diff.md`` for forensic inspection.

The orchestrator-computed line ranges are authoritative — the author's prose
summary may misremember which lines it touched, but the diff cannot lie.
"""

from __future__ import annotations

import difflib


def changed_line_ranges(pre: str, post: str) -> list[tuple[int, int]]:
    """Return (start, end) 1-indexed inclusive ranges in ``post`` that differ.

    Empty list iff the two strings are line-by-line identical. For pure
    deletions (lines removed in post), we anchor a single-line hint at the
    gap location so the reviewer still has somewhere to look.
    """
    pre_lines = pre.splitlines()
    post_lines = post.splitlines()
    matcher = difflib.SequenceMatcher(a=pre_lines, b=post_lines)
    ranges: list[tuple[int, int]] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if j2 > j1:
            ranges.append((j1 + 1, j2))
        else:
            # Pure deletion at post-position j1: nothing in post to point at,
            # so anchor a 1-line hint at the surrounding location.
            anchor = max(j1, 1)
            ranges.append((anchor, anchor))
    return ranges


def format_ranges(ranges: list[tuple[int, int]]) -> str:
    """Render ``[(42, 67), (110, 115)]`` as ``"lines 42-67, 110-115"``.

    Single-line ranges collapse to ``"line 42"``. Empty input returns
    ``"(no changes)"`` so the reviewer sees something rather than a blank.
    """
    if not ranges:
        return "(no changes)"
    parts: list[str] = []
    for start, end in ranges:
        parts.append(f"{start}" if start == end else f"{start}-{end}")
    label = "line" if len(ranges) == 1 and ranges[0][0] == ranges[0][1] else "lines"
    return f"{label} " + ", ".join(parts)


def unified_diff_text(
    pre: str,
    post: str,
    *,
    fromfile: str = "before",
    tofile: str = "after",
    context_lines: int = 3,
) -> str:
    """Return a unified diff between ``pre`` and ``post``. Empty when identical."""
    pre_lines = pre.splitlines(keepends=True)
    post_lines = post.splitlines(keepends=True)
    diff = difflib.unified_diff(
        pre_lines,
        post_lines,
        fromfile=fromfile,
        tofile=tofile,
        n=context_lines,
    )
    return "".join(diff)
