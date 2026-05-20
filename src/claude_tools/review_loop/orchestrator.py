"""The review-loop orchestrator: reviewer/author iteration on a single file.

Each iteration runs the reviewer first against the current file, then — only
if the reviewer did not approve — runs the author with the reviewer's feedback
to produce a revised file. The loop terminates as soon as the reviewer emits
`<approved/>`, so when the file is already in good shape no author call is
needed.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from claude_tools.common.context_collector import Context, collect_context
from claude_tools.common.logging import new_run_dir, write_transcript
from claude_tools.review_loop.adapters import get_adapter
from claude_tools.review_loop.convergence import (
    diff_below_threshold,
    reviewer_approved,
)

console = Console()

AUTHOR_SYSTEM_PROMPT = """You are the AUTHOR in a multi-model review loop.

You will be given:
  1. A target file (the only file you may modify).
  2. Read-only context: a directory tree and the contents of sibling files.
  3. The reviewer's feedback on the current target file (always present —
     the reviewer runs first each iteration and only invokes you when there
     are remaining issues to address).

Your job: emit the FULL new contents of the target file, incorporating all valid
reviewer feedback. Do not narrate; emit only the file body. Wrap it between
literal markers <<<FILE>>> and <<<END>>> so the orchestrator can extract it.

If the reviewer raised an issue you believe is wrong, briefly explain why in
prose AFTER the <<<END>>> marker so the reviewer sees your rationale.
"""

REVIEWER_SYSTEM_PROMPT = """You are the REVIEWER in a multi-model review loop.

You will be given:
  1. The current version of a target file (the author's latest revision).
  2. Read-only context: a directory tree and the contents of sibling files.

Your job: identify remaining substantive issues — mathematical, logical,
factual, or structural. Be concise and surgical: cite specific lines or
passages.

If the file has no remaining substantive issues, end your response with the
literal token <approved/> on its own line. Otherwise list the issues, ordered
by severity.
"""


@dataclass
class LoopConfig:
    target: Path
    author: str = "claude"
    reviewer: str = "codex"
    max_iterations: int = 6
    context_budget_tokens: int = 200_000
    diff_threshold_bytes: int = 32
    per_call_timeout_s: float = 1800.0
    dry_run: bool = False


@dataclass
class IterationResult:
    iteration: int
    author_output: str
    reviewer_output: str
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
    """Write file via tmp + rename so a crash never leaves a partial target."""
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, delete=False,
        prefix=f".{target.name}.", suffix=".tmp",
    ) as f:
        f.write(content)
        tmp = Path(f.name)
    os.replace(tmp, target)


def _extract_file_body(author_output: str) -> str:
    """Pull the new file body out of the author's response.

    Looks for the <<<FILE>>>...<<<END>>> markers. Falls back to the raw output
    if markers are absent (some models may forget; we still try to make
    progress rather than crash).
    """
    start_marker = "<<<FILE>>>"
    end_marker = "<<<END>>>"
    i = author_output.find(start_marker)
    j = author_output.find(end_marker, i + len(start_marker)) if i >= 0 else -1
    if i >= 0 and j > i:
        body = author_output[i + len(start_marker) : j]
        return body.lstrip("\n").rstrip()
    return author_output.strip()


def _build_author_prompt(ctx: Context, last_reviewer: str) -> str:
    sibling_blocks = "\n\n".join(
        f"### {sib.rel}\n```\n{sib.content}\n```" for sib in ctx.siblings
    )
    # Under the reviewer-first loop, ``last_reviewer`` is always non-empty when
    # the author runs; the else branch is defensive only.
    reviewer_block = (
        f"## Most recent reviewer feedback\n\n{last_reviewer}\n"
        if last_reviewer.strip()
        else "## Most recent reviewer feedback\n\n(empty — reviewer returned no text)\n"
    )
    return f"""## Target file: {ctx.target.name}

## Project tree
```
{ctx.tree}
```

## Sibling files (read-only)

{sibling_blocks}

## Current target file content

```
{ctx.target_content}
```

{reviewer_block}

Please emit the full new contents of `{ctx.target.name}` wrapped between
<<<FILE>>> and <<<END>>> markers."""


def _build_reviewer_prompt(ctx: Context) -> str:
    sibling_blocks = "\n\n".join(
        f"### {sib.rel}\n```\n{sib.content}\n```" for sib in ctx.siblings
    )
    return f"""## Target file: {ctx.target.name}

## Project tree
```
{ctx.tree}
```

## Sibling files (read-only)

{sibling_blocks}

## Current target file content

```
{ctx.target_content}
```

Review the current target file. List substantive issues, or end with
<approved/> if none remain."""


def run_loop(cfg: LoopConfig) -> LoopResult:
    """Execute the reviewer/author loop. Returns a LoopResult with logs.

    Each iteration runs the reviewer first against the current target file.
    If the reviewer signals approval, the loop ends without an author call.
    Otherwise the author rewrites the file with the reviewer's feedback in
    hand and we move to the next iteration.
    """
    target = cfg.target.resolve()
    if not target.exists():
        raise FileNotFoundError(target)

    author = get_adapter(cfg.author)
    reviewer = get_adapter(cfg.reviewer)

    run_dir = new_run_dir("review-loop")
    console.print(f"[bold]review-loop[/bold] run dir: {run_dir}")
    write_transcript(run_dir, "target.before", target.read_text(encoding="utf-8"))

    result = LoopResult(config=cfg, run_dir=run_dir)
    prev_author_output = ""

    for i in range(1, cfg.max_iterations + 1):
        console.rule(f"Iteration {i}/{cfg.max_iterations}")

        # --- Reviewer turn (always runs first; sees the current file in place). ---
        ctx = collect_context(target, max_tokens=cfg.context_budget_tokens)
        reviewer_prompt = _build_reviewer_prompt(ctx)

        if cfg.dry_run:
            console.print(
                "[yellow]DRY-RUN: skipping reviewer invocation; writing prompts only.[/yellow]"
            )
            write_transcript(run_dir, f"iter-{i:02d}-reviewer-prompt", reviewer_prompt)
            write_transcript(run_dir, f"iter-{i:02d}-reviewer-system", REVIEWER_SYSTEM_PROMPT)
            break

        console.print(f"[magenta]reviewer[/magenta] = {reviewer.name}; invoking...")
        reviewer_output = reviewer.invoke(
            REVIEWER_SYSTEM_PROMPT, reviewer_prompt, timeout_s=cfg.per_call_timeout_s
        )
        write_transcript(run_dir, f"iter-{i:02d}-reviewer", reviewer_output)

        # Convergence check #1: reviewer approved? Then no author call this iter.
        decision = reviewer_approved(reviewer_output)
        if decision.converged:
            iter_result = IterationResult(
                iteration=i,
                author_output="(no author call — reviewer approved)",
                reviewer_output=reviewer_output,
                converged=True,
                convergence_reason=decision.reason,
            )
            result.iterations.append(iter_result)
            result.final_converged = True
            result.final_reason = decision.reason
            console.print(f"[green]converged[/green]: {decision.reason}")
            break

        # --- Author turn (acts on the reviewer's feedback). ---
        # Re-collect context defensively, though only the reviewer block has changed.
        ctx = collect_context(target, max_tokens=cfg.context_budget_tokens)
        author_prompt = _build_author_prompt(ctx, reviewer_output)
        console.print(f"[cyan]author[/cyan] = {author.name}; invoking...")
        author_output = author.invoke(
            AUTHOR_SYSTEM_PROMPT, author_prompt, timeout_s=cfg.per_call_timeout_s
        )
        write_transcript(run_dir, f"iter-{i:02d}-author", author_output)

        new_body = _extract_file_body(author_output)
        _atomic_write(target, new_body)
        write_transcript(run_dir, f"iter-{i:02d}-target-after", new_body)

        iter_result = IterationResult(
            iteration=i,
            author_output=author_output,
            reviewer_output=reviewer_output,
            converged=False,
            convergence_reason="",
        )
        result.iterations.append(iter_result)

        # Convergence check #2: author output stable across consecutive iterations?
        # If the author barely changed anything despite the reviewer's feedback,
        # further iterations are unlikely to help.
        if prev_author_output:
            d = diff_below_threshold(
                prev_author_output, author_output, min_changed_bytes=cfg.diff_threshold_bytes
            )
            if d.converged:
                iter_result.converged = True
                iter_result.convergence_reason = d.reason
                result.final_converged = True
                result.final_reason = d.reason
                break
        prev_author_output = author_output

    if not result.final_converged:
        result.final_reason = f"Max iterations ({cfg.max_iterations}) reached without approval."
        console.print(f"[yellow]{result.final_reason}[/yellow]")

    # Write a summary file.
    summary_lines = [
        f"# review-loop run — {datetime.now(UTC).isoformat()}",
        "",
        f"- target: `{target}`",
        f"- author: `{cfg.author}`",
        f"- reviewer: `{cfg.reviewer}`",
        f"- iterations run: {len(result.iterations)}",
        f"- converged: {result.final_converged}",
        f"- reason: {result.final_reason}",
    ]
    write_transcript(run_dir, "summary", "\n".join(summary_lines))
    return result
