"""Tests for review_loop.diffing."""

from __future__ import annotations

from claude_tools.review_loop.diffing import (
    changed_line_ranges,
    format_ranges,
    unified_diff_text,
)


def test_identical_text_yields_no_ranges() -> None:
    assert changed_line_ranges("a\nb\nc\n", "a\nb\nc\n") == []


def test_single_line_replacement() -> None:
    pre = "a\nb\nc\n"
    post = "a\nBETA\nc\n"
    assert changed_line_ranges(pre, post) == [(2, 2)]


def test_multiple_disjoint_changes() -> None:
    pre = "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n"
    post = "1\nTWO\n3\n4\n5\n6\nSEVEN\nEIGHT\n9\n10\n"
    assert changed_line_ranges(pre, post) == [(2, 2), (7, 8)]


def test_pure_insertion() -> None:
    pre = "a\nb\n"
    post = "a\nNEW\nNEW2\nb\n"
    # Lines 2-3 in post are the new insertions.
    assert changed_line_ranges(pre, post) == [(2, 3)]


def test_pure_deletion_anchors_a_single_line() -> None:
    pre = "a\nb\nc\n"
    post = "a\nc\n"
    # The deletion of 'b' shows up as a 1-line anchor in post-coords.
    ranges = changed_line_ranges(pre, post)
    assert len(ranges) == 1
    start, end = ranges[0]
    assert start == end  # single-line anchor


def test_format_ranges_human_friendly() -> None:
    assert format_ranges([]) == "(no changes)"
    assert format_ranges([(42, 42)]) == "line 42"
    assert format_ranges([(42, 67)]) == "lines 42-67"
    assert format_ranges([(42, 67), (110, 115)]) == "lines 42-67, 110-115"


def test_unified_diff_text_includes_markers() -> None:
    d = unified_diff_text("a\nb\nc\n", "a\nBETA\nc\n", fromfile="x", tofile="y")
    assert "-b" in d
    assert "+BETA" in d
    assert "--- x" in d
    assert "+++ y" in d


def test_unified_diff_empty_when_identical() -> None:
    assert unified_diff_text("a\n", "a\n") == ""
