"""Convergence detection for the review-loop."""

from __future__ import annotations

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
    """Convergence by author output stability.

    Compares the byte-length difference of consecutive author outputs. If the
    revision is shorter than ``min_changed_bytes``, treat as converged.
    """
    delta = abs(len(current) - len(prev))
    if delta < min_changed_bytes:
        return ConvergenceDecision(
            True,
            f"Author output stable (|delta|={delta} bytes < {min_changed_bytes}).",
        )
    return ConvergenceDecision(False, f"Author output still changing (|delta|={delta} bytes).")
