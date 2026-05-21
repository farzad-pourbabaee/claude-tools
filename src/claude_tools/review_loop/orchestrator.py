"""Reviewer/author iteration loop with persistent sessions.

Each of the two model CLIs (claude / codex) keeps one persistent session
alive across all iterations of a run, so the author and reviewer each carry
their full prior-turn memory from round to round. Only the *delta* between
sides flows over the wire each iteration: the reviewer's textual critique to
the author, and back, the author's short prose summary plus an
orchestrator-computed diff of which line ranges in the working file moved.

The author rewrites the file in place via its Edit tool (no marker
extraction); the reviewer is read-only. After every author turn the
orchestrator diffs the working file pre/post, logs both the unified diff and
the changed line ranges, then feeds those ranges plus the author's prose to
the reviewer as a focusing hint for the next round. The reviewer is
instructed to re-read the file from disk, not to trust the hint blindly.

Convergence ends the loop on any of:
  - reviewer emits ``<approved/>`` (or equivalent),
  - the author leaves the working file byte-stable across consecutive turns,
  - ``--max-iterations`` is hit.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from claude_tools.common.context_collector import (
    ReviewContext,
    collect_review_context,
)
from claude_tools.common.logging import new_run_dir, write_transcript
from claude_tools.review_loop.adapters import get_adapter
from claude_tools.review_loop.convergence import (
    diff_below_threshold,
    reviewer_approved,
)
from claude_tools.review_loop.diffing import (
    changed_line_ranges,
    format_ranges,
    unified_diff_text,
)
from claude_tools.review_loop.signals import make_signal_printer

console = Console()

AUTHOR_SYSTEM_PROMPT = """You are the AUTHOR in a multi-model review loop on a single target file.

You will operate over many turns. On the first turn you will receive the
full current contents of the target file inline along with the reviewer's
critique. On later turns you will receive only the reviewer's latest
critique — the file is already on disk and you have been editing it across
rounds; re-read it with your Read tool any time you need a fresh look.

Your working directory is the project root. You may use Read / Glob / Grep
to consult any sibling file for context. To revise the target file, use the
Edit tool — edits land on disk immediately and the orchestrator will detect
them by diffing the file pre/post your turn. Do NOT use Write or any other
tool, and do NOT edit any file other than the target.

End every turn with a SHORT prose summary (a few sentences at most) of what
you changed and WHY, including any reviewer feedback you disagreed with and
chose not to apply. The orchestrator separately computes the exact line
ranges you touched from the on-disk diff, so you don't need to track line
numbers in your summary — just describe the substance of your edits.
"""

REVIEWER_SYSTEM_PROMPT = """You are the REVIEWER in a multi-model review loop on a target file.

You will operate over many turns. On the first turn you will receive the
full current contents of the target file inline. On later turns you will
receive a short summary of what the author claims they changed plus the
orchestrator-computed line ranges that actually changed on disk. Always
RE-READ the file with your Read tool before reviewing on later turns — the
summary tells you WHERE to look, not WHAT is there.

Your working directory is the project root. You may use Read / Glob / Grep
to consult any sibling file for cross-reference. You may NOT modify any
file — your only output is text. Be concise and surgical: cite specific
lines or passages, ordered by severity.

End your response with the literal token `<approved/>` on its own line if
no substantive issues remain. Otherwise list the issues. Do not pad with
praise or boilerplate.
"""


@dataclass
class LoopConfig:
    target: Path
    author: str = "claude"
    reviewer: str = "codex"
    max_iterations: int = 6
    # Deprecated: sibling content is no longer inlined into prompts, and the
    # author/reviewer each carry their own context across turns via their CLI
    # sessions. Kept on the dataclass so old TOML configs that set this key
    # don't break; the value is unused.
    context_budget_tokens: int = 200_000
    # Stability check is applied to the working file's pre/post-turn bytes.
    # If the author moves fewer than this many bytes in a round, treat as
    # converged (stagnating).
    diff_threshold_bytes: int = 32
    per_call_timeout_s: float = 1800.0
    claude_model: str | None = None
    claude_effort: str | None = None
    codex_model: str | None = None
    codex_effort: str | None = None
    dry_run: bool = False


def _engine_settings(engine_name: str, cfg: LoopConfig) -> dict[str, str | None]:
    if engine_name == "claude":
        return {"model": cfg.claude_model, "effort": cfg.claude_effort}
    if engine_name == "codex":
        return {"model": cfg.codex_model, "effort": cfg.codex_effort}
    return {}


@dataclass
class IterationResult:
    iteration: int
    reviewer_output: str
    author_output: str
    changed_ranges: list[tuple[int, int]] = field(default_factory=list)
    converged: bool = False
    convergence_reason: str = ""


@dataclass
class LoopResult:
    config: LoopConfig
    run_dir: Path
    iterations: list[IterationResult] = field(default_factory=list)
    final_converged: bool = False
    final_reason: str = ""


def _atomic_write(target: Path, content: str) -> None:
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, delete=False,
        prefix=f".{target.name}.", suffix=".tmp",
    ) as f:
        f.write(content)
        tmp = Path(f.name)
    os.replace(tmp, target)


def _working_target_path(original: Path) -> Path:
    """Sibling of ``original`` with ``_loop_reviewed`` inserted before the suffix."""
    return original.with_name(f"{original.stem}_loop_reviewed{original.suffix}")


def _build_initial_reviewer_prompt(ctx: ReviewContext) -> str:
    return f"""## Target file: {ctx.target.name}
Path on disk: `{ctx.target}`
Project root: `{ctx.project_root}` (your working directory)

## Project tree (for orientation)
```
{ctx.tree}
```

Sibling files are NOT inlined. Read any of them on demand from disk with your
Read / Glob / Grep tools; they do not change during the loop.

## Current target file content

```
{ctx.target_content}
```

Review the current target file. List substantive issues, ordered by severity.
End with `<approved/>` on its own line if no substantive issues remain."""


def _build_initial_author_prompt(ctx: ReviewContext, reviewer_feedback: str) -> str:
    return f"""## Target file: {ctx.target.name}
Path on disk: `{ctx.target}` — edit this file (and only this file) via your Edit tool.
Project root: `{ctx.project_root}` (your working directory)

## Project tree (for orientation)
```
{ctx.tree}
```

## Current target file content

```
{ctx.target_content}
```

## Reviewer feedback

{reviewer_feedback}

Apply the changes you agree with via Edit on the target file at the path
above. End with a brief prose summary of what you changed and why."""


def _build_followup_reviewer_prompt(
    target: Path,
    author_prose: str,
    changed_ranges: list[tuple[int, int]],
) -> str:
    ranges = format_ranges(changed_ranges)
    return f"""## Author summary of changes (the author's own words)

{author_prose if author_prose.strip() else "(no prose summary returned)"}

## Orchestrator-computed diff (authoritative)

The author touched `{target}` at: {ranges}.

RE-READ `{target}` with your Read tool now to see the current state. The
summary above tells you where to look, not what is there. Then list any
remaining substantive issues, ordered by severity. End with `<approved/>`
on its own line if no substantive issues remain."""


def _build_followup_author_prompt(target: Path, reviewer_feedback: str) -> str:
    return f"""## Reviewer feedback

{reviewer_feedback}

Re-read `{target}` if you need a fresh look at the current state. Apply the
edits you agree with via Edit on that file. End with a brief prose summary
of what you changed and why (or why you declined to act on any item)."""


def _persist_events(run_dir: Path, name: str, raw_lines: list[str]) -> None:
    path = run_dir / f"{name}.events.jsonl"
    path.write_text("".join(raw_lines), encoding="utf-8")


def run_loop(cfg: LoopConfig) -> LoopResult:
    """Execute the persistent-session reviewer/author loop. Returns LoopResult."""
    original = cfg.target.resolve()
    if not original.exists():
        raise FileNotFoundError(original)

    working = _working_target_path(original)
    original_content = original.read_text(encoding="utf-8")
    _atomic_write(working, original_content)

    project_root = working.parent.resolve()

    run_dir = new_run_dir("review-loop")
    console.print(f"[bold]review-loop[/bold] run dir: {run_dir}")
    console.print(f"original (untouched): {original}")
    console.print(f"working/output file:  {working}")
    write_transcript(run_dir, "target.before", original_content)

    result = LoopResult(config=cfg, run_dir=run_dir)

    if cfg.dry_run:
        ctx = collect_review_context(working, exclude=[original])
        reviewer_prompt = _build_initial_reviewer_prompt(ctx)
        write_transcript(run_dir, "iter-01-msg-to-reviewer", reviewer_prompt)
        write_transcript(run_dir, "iter-01-reviewer-system", REVIEWER_SYSTEM_PROMPT)
        write_transcript(run_dir, "iter-01-author-system", AUTHOR_SYSTEM_PROMPT)
        console.print(
            "[yellow]DRY-RUN: wrote initial prompts to run dir; no models invoked.[/yellow]"
        )
        return result

    # Build persistent adapters once. Engine settings are engine-scoped, so
    # we look them up by the CLI name, not by author/reviewer role.
    author = get_adapter(
        cfg.author,
        role="author",
        cwd=str(project_root),
        timeout_s=cfg.per_call_timeout_s,
        **_engine_settings(cfg.author, cfg),
    )
    reviewer = get_adapter(
        cfg.reviewer,
        role="reviewer",
        cwd=str(project_root),
        timeout_s=cfg.per_call_timeout_s,
        **_engine_settings(cfg.reviewer, cfg),
    )

    # Stability check compares end-of-iter file content across consecutive
    # rounds; it's intentionally not applied on iter 1 (no prior round to
    # compare to, and the first author turn naturally produces small changes
    # that aren't "stagnation").
    prev_working_content: str | None = None

    for i in range(1, cfg.max_iterations + 1):
        console.rule(f"Iteration {i}/{cfg.max_iterations}")

        # ---- Reviewer turn ------------------------------------------------
        if i == 1:
            ctx = collect_review_context(working, exclude=[original])
            reviewer_msg = _build_initial_reviewer_prompt(ctx)
            reviewer_system: str | None = REVIEWER_SYSTEM_PROMPT
        else:
            # iteration > 1: feed only the delta. Author prose + line ranges.
            prev_iter = result.iterations[-1]
            reviewer_msg = _build_followup_reviewer_prompt(
                working, prev_iter.author_output, prev_iter.changed_ranges,
            )
            reviewer_system = None  # already attached to the persistent session

        write_transcript(run_dir, f"iter-{i:02d}-msg-to-reviewer", reviewer_msg)
        console.print(f"[magenta]reviewer[/magenta] = {reviewer.name}; invoking...")
        reviewer_signal = make_signal_printer(
            console, iteration=i, side="reviewer", engine=reviewer.name,
        )
        reviewer_output = reviewer.send(
            reviewer_msg,
            system_prompt=reviewer_system,
            on_event=reviewer_signal,
        )
        write_transcript(run_dir, f"iter-{i:02d}-reviewer", reviewer_output)
        if reviewer.last_run is not None:
            _persist_events(
                run_dir, f"iter-{i:02d}-reviewer", reviewer.last_run.raw_lines,
            )

        # Approval check — if so, no author call this iteration.
        decision = reviewer_approved(reviewer_output)
        if decision.converged:
            iter_result = IterationResult(
                iteration=i,
                reviewer_output=reviewer_output,
                author_output="(no author call — reviewer approved)",
                converged=True,
                convergence_reason=decision.reason,
            )
            result.iterations.append(iter_result)
            result.final_converged = True
            result.final_reason = decision.reason
            console.print(f"[green]converged[/green]: {decision.reason}")
            break

        # ---- Author turn -------------------------------------------------
        working_pre = working.read_text(encoding="utf-8")

        if i == 1:
            ctx = collect_review_context(working, exclude=[original])
            author_msg = _build_initial_author_prompt(ctx, reviewer_output)
            author_system: str | None = AUTHOR_SYSTEM_PROMPT
        else:
            author_msg = _build_followup_author_prompt(working, reviewer_output)
            author_system = None

        write_transcript(run_dir, f"iter-{i:02d}-msg-to-author", author_msg)
        console.print(f"[cyan]author[/cyan] = {author.name}; invoking...")
        author_signal = make_signal_printer(
            console, iteration=i, side="author", engine=author.name,
        )
        author_output = author.send(
            author_msg,
            system_prompt=author_system,
            on_event=author_signal,
        )
        write_transcript(run_dir, f"iter-{i:02d}-author", author_output)
        if author.last_run is not None:
            _persist_events(
                run_dir, f"iter-{i:02d}-author", author.last_run.raw_lines,
            )

        # ---- Diff bookkeeping -------------------------------------------
        working_post = working.read_text(encoding="utf-8")
        ranges = changed_line_ranges(working_pre, working_post)
        diff = unified_diff_text(
            working_pre, working_post,
            fromfile=f"{working.name} (pre iter {i})",
            tofile=f"{working.name} (post iter {i})",
        )
        write_transcript(run_dir, f"iter-{i:02d}-diff", diff)
        write_transcript(run_dir, f"iter-{i:02d}-target-after", working_post)
        if ranges:
            console.print(
                f"[dim]author touched:[/dim] {format_ranges(ranges)}"
            )
        else:
            console.print("[dim]author made no on-disk changes this round.[/dim]")

        iter_result = IterationResult(
            iteration=i,
            reviewer_output=reviewer_output,
            author_output=author_output,
            changed_ranges=ranges,
        )
        result.iterations.append(iter_result)

        # Stability check on the working file's bytes (iter >= 2 only). If
        # the author barely moved the file between consecutive rounds, further
        # iterations are unlikely to help.
        if prev_working_content is not None:
            stability = diff_below_threshold(
                prev_working_content, working_post,
                min_changed_bytes=cfg.diff_threshold_bytes,
            )
            if stability.converged:
                iter_result.converged = True
                iter_result.convergence_reason = stability.reason
                result.final_converged = True
                result.final_reason = stability.reason
                console.print(f"[yellow]stopped[/yellow]: {stability.reason}")
                break
        prev_working_content = working_post

    if not result.final_converged:
        result.final_reason = (
            f"Max iterations ({cfg.max_iterations}) reached without approval."
        )
        console.print(f"[yellow]{result.final_reason}[/yellow]")

    summary_lines = [
        f"# review-loop run — {datetime.now(UTC).isoformat()}",
        "",
        f"- original (untouched): `{original}`",
        f"- output: `{working}`",
        f"- author: `{cfg.author}`",
        f"- reviewer: `{cfg.reviewer}`",
        f"- iterations run: {len(result.iterations)}",
        f"- converged: {result.final_converged}",
        f"- reason: {result.final_reason}",
        "",
        "## Per-iteration changes",
    ]
    for it in result.iterations:
        summary_lines.append(
            f"- iter {it.iteration:02d}: {format_ranges(it.changed_ranges)}"
        )
    write_transcript(run_dir, "summary", "\n".join(summary_lines))
    return result
