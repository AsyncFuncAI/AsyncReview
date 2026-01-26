"""Virtual review runner - runs RLM reviews on GitHub content without local repo."""

import asyncio
import logging
from typing import Callable

import dspy

from cr.config import MAIN_MODEL, SUB_MODEL, MAX_ITERATIONS, MAX_LLM_CALLS

from .github_fetcher import (
    parse_github_url,
    fetch_pr,
    fetch_issue,
    build_review_context,
)


class VirtualReviewRunner:
    """Run RLM code reviews on GitHub PRs without a local repository.
    
    Creates a 'virtual' codebase context from GitHub API data.
    """
    
    def __init__(
        self,
        model: str | None = None,
        quiet: bool = False,
        on_step: Callable[[int, str, str], None] | None = None,
    ):
        """Initialize the virtual runner.
        
        Args:
            model: Override model (e.g. "gemini-3.0-pro-preview")
            quiet: If True, suppress progress output
            on_step: Optional callback for RLM step updates
        """
        self.model = model or MAIN_MODEL
        self.quiet = quiet
        self.on_step = on_step
        self._rlm = None
        self._configured = False
    
    def _ensure_configured(self):
        """Configure DSPy and RLM on first use."""
        if self._configured:
            return
        
        # Configure logging based on quiet mode
        if self.quiet:
            logging.getLogger("dspy").setLevel(logging.WARNING)
            logging.getLogger("dspy.predict.rlm").setLevel(logging.WARNING)
            logging.getLogger("httpx").setLevel(logging.WARNING)
        else:
            logging.getLogger("dspy.predict.rlm").setLevel(logging.INFO)
        
        # Suppress noisy loggers
        for name in ("httpx", "anthropic", "google", "urllib3"):
            logging.getLogger(name).setLevel(logging.WARNING)
        
        # Configure DSPy with specified model
        model_name = self.model
        if not model_name.startswith("gemini/"):
            model_name = f"gemini/{model_name}"
        
        dspy.configure(lm=dspy.LM(model_name))
        
        # Create RLM with custom interpreter that has Deno 2.x fix
        from dspy.primitives.python_interpreter import PythonInterpreter
        from cr.rlm_runner import build_deno_command
        
        deno_command = build_deno_command()
        interpreter = PythonInterpreter(deno_command=deno_command)
        
        self._rlm = dspy.RLM(
            signature="context, question -> answer, sources",
            max_iterations=MAX_ITERATIONS,
            max_llm_calls=MAX_LLM_CALLS,
            sub_lm=dspy.LM(f"gemini/{SUB_MODEL}" if not SUB_MODEL.startswith("gemini/") else SUB_MODEL),
            verbose=not self.quiet,
            interpreter=interpreter,
        )
        self._configured = True
    
    async def review(self, url: str, question: str) -> tuple[str, list[str], dict]:
        """Review a GitHub URL (PR or Issue).
        
        Args:
            url: GitHub PR or Issue URL
            question: Question to ask about the content
            
        Returns:
            Tuple of (answer, sources, metadata)
        """
        # Parse URL to determine type
        owner, repo, number, url_type = parse_github_url(url)
        
        # Fetch content
        if url_type == "pr":
            data = await fetch_pr(owner, repo, number)
        else:
            data = await fetch_issue(owner, repo, number)
        
        # Build context
        context = build_review_context(data)
        
        # Run RLM
        self._ensure_configured()
        
        # Run in thread pool since RLM is sync
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._run_rlm(context, question)
        )
        
        answer, sources = result
        
        metadata = {
            "type": url_type,
            "owner": owner,
            "repo": repo,
            "number": number,
            "title": data.get("title", ""),
            "model": self.model,
        }
        
        return answer, sources, metadata
    
    def _run_rlm(self, context: str, question: str) -> tuple[str, list[str]]:
        """Run the RLM synchronously."""
        result = self._rlm(context=context, question=question)
        
        answer = getattr(result, "answer", str(result))
        sources = getattr(result, "sources", [])
        
        if isinstance(sources, str):
            sources = [s.strip() for s in sources.split(",") if s.strip()]
        
        return answer, sources
    
    async def review_pr(self, url: str, question: str) -> tuple[str, list[str], dict]:
        """Review a GitHub PR with full diff context.
        
        This is the primary use case - builds comprehensive context including
        all changed files with their patches, PR description, and commit history.
        """
        return await self.review(url, question)
    
    async def review_issue(self, url: str, question: str) -> tuple[str, list[str], dict]:
        """Review a GitHub issue (secondary use case)."""
        return await self.review(url, question)
