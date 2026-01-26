"""Output formatting for different use cases."""

import json
from typing import Any


def format_text(answer: str, sources: list[str], model: str) -> str:
    """Plain text output for terminal display.
    
    Clean output without rich formatting.
    """
    lines = [answer]
    
    if sources:
        lines.append("")
        lines.append("Sources:")
        for source in sources:
            lines.append(f"  • {source}")
    
    lines.append("")
    lines.append(f"— AsyncReview • {model}")
    
    return "\n".join(lines)


def format_markdown(answer: str, sources: list[str], model: str) -> str:
    """Markdown output for docs/skills.
    
    Suitable for embedding in documentation or Claude Code skills.
    """
    lines = [answer]
    
    if sources:
        lines.append("")
        lines.append("### Sources")
        for source in sources:
            lines.append(f"- `{source}`")
    
    lines.append("")
    lines.append("---")
    lines.append(f"*AsyncReview • {model}*")
    
    return "\n".join(lines)


def format_json(
    answer: str,
    sources: list[str],
    model: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """JSON output for scripting and automation.
    
    Returns a JSON string with answer, sources, model, and optional metadata.
    """
    result = {
        "answer": answer,
        "sources": sources,
        "model": model,
    }
    
    if metadata:
        result["metadata"] = metadata
    
    return json.dumps(result, indent=2)


def format_output(
    answer: str,
    sources: list[str],
    model: str,
    output_format: str = "text",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Format output based on specified format.
    
    Args:
        answer: The review answer text
        sources: List of source citations
        model: Model name used for review
        output_format: One of "text", "markdown", "json"
        metadata: Optional metadata for JSON output
        
    Returns:
        Formatted output string
    """
    if output_format == "markdown":
        return format_markdown(answer, sources, model)
    elif output_format == "json":
        return format_json(answer, sources, model, metadata)
    else:
        return format_text(answer, sources, model)
