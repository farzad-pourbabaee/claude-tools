"""Tests for review_loop.convergence."""

from __future__ import annotations

from claude_tools.review_loop.convergence import (
    diff_below_threshold,
    reviewer_approved,
)


def test_reviewer_approved_marker() -> None:
    d = reviewer_approved("Looks good.\n\n<approved/>")
    assert d.converged
    assert "approved" in d.reason.lower()


def test_reviewer_approved_phrase() -> None:
    d = reviewer_approved("After my review I found no remaining errors.")
    assert d.converged


def test_reviewer_not_approved() -> None:
    d = reviewer_approved("Issue 1: equation (3) has wrong sign.")
    assert not d.converged


def test_diff_below_threshold_stable() -> None:
    prev = "A" * 1000
    curr = "A" * 1005
    d = diff_below_threshold(prev, curr, min_changed_bytes=32)
    assert d.converged


def test_diff_below_threshold_changing() -> None:
    prev = "A" * 1000
    curr = "A" * 2000
    d = diff_below_threshold(prev, curr, min_changed_bytes=32)
    assert not d.converged
