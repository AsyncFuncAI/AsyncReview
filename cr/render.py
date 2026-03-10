"""Rich console rendering for CLI output."""

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape as rich_escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box

from .config import MAIN_MODEL, SUB_MODEL
from .types import RLMTrace

console = Console()


def print_step(step_num: int, reasoning: str, code: str):
    """Print a single RLM step with reasoning and code panels."""
    console.print()
    console.rule(f"[bold cyan]Step {step_num}[/bold cyan]", style="cyan")

    if reasoning:
        # Truncate long reasoning
        display = reasoning[:500] + "..." if len(reasoning) > 500 else reasoning
        console.print(
            Panel(
                Text(display, style="italic"),
                title="[yellow]Reasoning[/yellow]",
                border_style="yellow",
                padding=(0, 1),
            )
        )

    if code:
        # Truncate long code
        if len(code) > 800:
            code = code[:800] + "\n# ... (truncated)"

        console.print(
            Panel(
                Syntax(code, "python", theme="monokai", line_numbers=False),
                title="[green]Code[/green]",
                border_style="green",
                padding=(0, 1),
            )
        )


def print_answer(answer: str, sources: list[str] | None = None):
    """Print the final answer with sources."""
    console.print()
    console.rule("[bold green]Answer[/bold green]", style="green")
    console.print()

    console.print(
        Panel(
            Markdown(answer),
            title="[bold white]Response[/bold white]",
            border_style="green",
            padding=(1, 2),
        )
    )

    if sources:
        console.print()
        text = "\n".join(f"• {s}" for s in sources)
        console.print(
            Panel(
                text,
                title="[bold blue]Sources[/bold blue]",
                border_style="blue",
                padding=(0, 1),
            )
        )


def print_welcome(repo_path: str, file_count: int):
    """Print welcome message with repo info."""
    console.print()
    console.print(
        Panel(
            f"""[bold cyan]Codebase Review Tool[/bold cyan]

Powered by DSPy RLM + Gemini

[dim]• Repository: {repo_path}
• Files indexed: {file_count}
• Models: {MAIN_MODEL} / {SUB_MODEL}
• Conversational: follow-ups use context
• Type 'help' for commands[/dim]""",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print()


def print_help():
    """Print help table with available commands."""
    table = Table(box=box.ROUNDED, border_style="cyan")
    table.add_column("Command", style="cyan")
    table.add_column("Description")
    table.add_row("quit, exit, q", "Exit the program")
    table.add_row("help", "Show this help message")
    table.add_row("reset", "Clear screen and conversation history")
    table.add_row("history", "Show conversation history")
    table.add_row("files", "List indexed files")
    table.add_row("info", "Show repository info")
    console.print(table)
    console.print()


def print_error(message: str):
    """Print an error message."""
    console.print(f"\n[red]Error: {rich_escape(message)}[/red]")


def print_info(message: str):
    """Print an info message."""
    console.print(f"[dim]{rich_escape(message)}[/dim]")


def print_history(history: list[tuple[str, str]]):
    """Print conversation history."""
    if not history:
        console.print("[dim]No history yet.[/dim]")
    else:
        for i, (q, a) in enumerate(history, 1):
            console.print(f"\n[cyan]Q{i}:[/cyan] {rich_escape(q)}")
            # Truncate long answers
            display_a = a[:200] + "..." if len(a) > 200 else a
            console.print(f"[green]A{i}:[/green] {rich_escape(display_a)}")
    console.print()


def print_files(file_tree: list[str], max_display: int = 50):
    """Print file tree (truncated if too long)."""
    console.print(f"\n[bold]Indexed files ({len(file_tree)} total):[/bold]")
    for path in file_tree[:max_display]:
        console.print(f"  {path}")
    if len(file_tree) > max_display:
        console.print(f"  [dim]... and {len(file_tree) - max_display} more[/dim]")
    console.print()


def print_repo_info(repo_info: dict):
    """Print repository information."""
    console.print("\n[bold]Repository Info:[/bold]")
    console.print(f"  Root: {repo_info.get('root', 'N/A')}")
    console.print(f"  Total files: {repo_info.get('total_files', 0)}")
    console.print(f"  Total size: {repo_info.get('total_bytes', 0):,} bytes")

    languages = repo_info.get("languages", {})
    if languages:
        console.print("  Languages:")
        for lang, count in sorted(languages.items(), key=lambda x: -x[1])[:10]:
            console.print(f"    {lang}: {count} files")
    console.print()

