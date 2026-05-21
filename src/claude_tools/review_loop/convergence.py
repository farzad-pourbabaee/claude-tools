"""Convergence detection for the review-loop."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

APPROVED_RE = re.compile(r"<approved\s*/>|<\s*/?\s*approved\s*>", re.IGNORECASE)
NO_ISSUES_RE = re.compile(
    r"\bno (remaining |substantive )?(errors|issues|problems)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConvergenceDecision:
    converged: bool
    reason: str  # human-readable explanation


def reviewer_approved(review_text: str) -> ConvergenceDecision:
    """Convergence by explicit reviewer signal.

    Looks for the literal token ``<approved/>`` (or variants) or a phrase like
    "no remaining errors" / "no substantive issues".
    """
    if APPROVED_RE.search(review_text):
        return ConvergenceDecision(True, "Reviewer emitted <approved/>.")
    if NO_ISSUES_RE.search(review_text):
        return ConvergenceDecision(True, "Reviewer reported no remaining errors/issues.")
    return ConvergenceDecision(False, "Reviewer did not signal approval.")


def diff_below_threshold(prev: str, current: str, *, min_changed_bytes: int) -> ConvergenceDecision:
    """Convergence by content stability between consecutive author rounds.

    Counts the number of characters in non-``equal`` opcodes of a
    ``SequenceMatcher`` between the two strings. Strict byte equality
    short-circuits to converged. This is more precise than a length-difference
    check, which would call two completely different strings of the same
    length "stable" (delta=0) — a real footgun for file content.
    """
    if prev == current:
        return ConvergenceDecision(True, "Working file identical to previous iteration.")
    matcher = difflib.SequenceMatcher(a=prev, b=current, autojunk=False)
    changed = sum(
        (i2 - i1) + (j2 - j1)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    )
    if changed < min_changed_bytes:
        return ConvergenceDecision(
            True,
            f"Working file stable (~{changed} chars changed < {min_changed_bytes}).",
        )
    return ConvergenceDecision(
        False, f"Working file still changing (~{changed} chars changed)."
    )
