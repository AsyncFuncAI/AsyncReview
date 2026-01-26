#!/usr/bin/env python3
"""AsyncReview CLI - Review GitHub PRs and Issues from the command line.

Primary use case: PR code review with full diff context.

Examples:
    # Quick PR review
    asyncreview review --url https://github.com/org/repo/pull/123 -q "Any security concerns?"
    
    # Output as markdown for docs
    asyncreview review --url https://github.com/org/repo/pull/123 -q "Summarize changes" --output markdown
    
    # Quiet mode for scripting
    asyncreview review --url https://github.com/org/repo/pull/123 -q "Review this" --quiet --output json
"""

import argparse
import asyncio
import sys

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from . import __version__
from .github_fetcher import parse_github_url
from .output_formatter import format_output
from .virtual_runner import VirtualReviewRunner


console = Console()


def print_step(step_num: int, reasoning: str, code: str):
    """Print RLM step progress (when not in quiet mode)."""
    console.print(f"\n[cyan]Step {step_num}[/cyan]", style="bold")
    if reasoning:
        # Truncate for display
        display = reasoning[:200] + "..." if len(reasoning) > 200 else reasoning
        console.print(f"[dim]{display}[/dim]")


def print_info(message: str):
    """Print an info message."""
    console.print(f"[dim]{message}[/dim]")


def print_error(message: str):
    """Print an error message."""
    console.print(f"[red]Error: {message}[/red]")


async def run_review(
    url: str,
    question: str,
    output_format: str = "text",
    quiet: bool = False,
    model: str | None = None,
):
    """Run a review on a GitHub URL."""
    # Parse URL first to validate
    try:
        owner, repo, number, url_type = parse_github_url(url)
    except ValueError as e:
        print_error(str(e))
        sys.exit(1)
    
    if not quiet:
        type_label = "PR" if url_type == "pr" else "Issue"
        print_info(f"Reviewing {type_label}: {owner}/{repo}#{number}")
        print_info(f"Question: {question}")
        console.print()
    
    # Create runner
    runner = VirtualReviewRunner(
        model=model,
        quiet=quiet,
        on_step=None if quiet else print_step,
    )
    
    try:
        answer, sources, metadata = await runner.review(url, question)
    except Exception as e:
        print_error(f"Review failed: {e}")
        sys.exit(1)
    
    # Format and print output
    model_name = metadata.get("model", model or "unknown")
    output = format_output(
        answer=answer,
        sources=sources,
        model=model_name,
        output_format=output_format,
        metadata=metadata if output_format == "json" else None,
    )
    
    if quiet or output_format == "json":
        # Raw output for scripting
        print(output)
    else:
        # Rich formatted output
        console.print()
        if output_format == "markdown":
            console.print(Panel(Markdown(output), title="Review", border_style="green"))
        else:
            console.print(Panel(output, title="Review", border_style="green"))


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AsyncReview CLI - Review GitHub PRs and Issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  asyncreview review --url https://github.com/org/repo/pull/123 -q "Any risks?"
  asyncreview review --url https://github.com/org/repo/issues/42 -q "What's needed?" --output markdown
  asyncreview review --url <url> -q "Review" --quiet --output json
        """,
    )
    
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"asyncreview {__version__}",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # review command
    review_parser = subparsers.add_parser(
        "review",
        help="Review a GitHub PR or Issue",
    )
    review_parser.add_argument(
        "--url", "-u",
        type=str,
        required=True,
        help="GitHub PR or Issue URL",
    )
    review_parser.add_argument(
        "--question", "-q",
        type=str,
        required=True,
        help="Question to ask about the PR/Issue",
    )
    review_parser.add_argument(
        "--output", "-o",
        type=str,
        choices=["text", "markdown", "json"],
        default="text",
        help="Output format (default: text)",
    )
    review_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output, print only the result",
    )
    review_parser.add_argument(
        "--model", "-m",
        type=str,
        default=None,
        help="Model to use (e.g. gemini-3.0-pro-preview)",
    )
    
    args = parser.parse_args()
    
    if args.command == "review":
        asyncio.run(run_review(
            url=args.url,
            question=args.question,
            output_format=args.output,
            quiet=args.quiet,
            model=args.model,
        ))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
