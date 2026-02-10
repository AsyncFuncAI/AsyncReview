"""Virtual review runner - runs RLM reviews on GitHub content without local repo."""

import asyncio
import concurrent.futures
import logging
from typing import Callable

import dspy
from dspy.primitives.python_interpreter import PythonInterpreter

from cr.config import MAIN_MODEL, SUB_MODEL, MAX_ITERATIONS, MAX_LLM_CALLS
from cr.rlm_runner import build_deno_command

from .github_fetcher import (
    parse_github_url,
    fetch_pr,
    fetch_issue,
    build_review_context,
)
from .local_fetcher import build_local_context, validate_local_path
from .local_repo_tools import LocalRepoTools
from .repo_tools import RepoTools





class VirtualReviewRunner:
    """Run RLM code reviews on GitHub PRs and local directories.

    Creates a 'virtual' codebase context from GitHub API data or local filesystem.
    Uses native DSPy RLM tools for agentic file fetching, directory listing, and code search.
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
        self._lm = None
        # Repo tools state (set per-review)
        self._repo_tools: RepoTools | None = None
    
    def _load_local_checklist(self, path: str) -> str:
        """Load a bundled checklist file from the CLI package.

        Args:
            path: Path like 'checklists/solid-checklist.md'

        Returns:
            Content of the checklist file, or error message if not found
        """
        from pathlib import Path

        # Get the directory where this module is located
        cli_dir = Path(__file__).parent
        checklist_path = cli_dir / path

        if checklist_path.exists():
            return checklist_path.read_text()
        else:
            return f"[Error] Checklist not found: {path}"

    def _sync_call(self, coro):
        """Bridge async coroutines to sync using ThreadPoolExecutor.

        DSPy RLM tools must be sync, but RepoTools/LocalRepoTools methods are async.
        This helper runs the coroutine in a thread pool and returns the result.

        Args:
            coro: An async coroutine to execute

        Returns:
            The result of the coroutine
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()

    def _create_tool_functions(self):
        """Create sync tool wrapper functions for DSPy RLM.

        Returns a dict of three sync tool functions as closures that capture
        self by reference (so self._repo_tools can change between review calls).

        Returns:
            Dict mapping tool name to function: {fetch_file, list_dir, search_code}
        """
        runner = self

        def fetch_file(path: str) -> str:
            """Fetch a file from the repository by path.

            Handles both regular repository files and bundled checklist files.
            Returns file content as a string, or an error message if the file
            cannot be read.

            Args:
                path: File path (e.g., 'src/main.py' or 'checklists/solid-checklist.md')

            Returns:
                File content as string, or error message
            """
            if path.startswith("checklists/"):
                return runner._load_local_checklist(path)
            return runner._sync_call(runner._repo_tools.fetch_file(path))

        def list_dir(path: str) -> str:
            """List directory contents at the given path.

            Returns a formatted text listing of files and directories,
            showing path, type (file/dir), and size in bytes.

            Args:
                path: Directory path (e.g., 'src' or '')

            Returns:
                Formatted text listing of directory contents
            """
            entries = runner._sync_call(runner._repo_tools.list_directory(path))
            if not entries:
                return "[No entries]"

            # Format as readable text
            lines = []
            for entry in entries:
                if "error" in entry:
                    lines.append(f"[Error] {entry['error']}")
                else:
                    entry_path = entry.get("path", "?")
                    entry_type = entry.get("type", "?")
                    entry_size = entry.get("size", 0)
                    if entry_type == "dir":
                        lines.append(f"[DIR]  {entry_path}")
                    else:
                        lines.append(f"[FILE] {entry_path} ({entry_size} bytes)")
            return "\n".join(lines)

        def search_code(query: str) -> str:
            """Search for code patterns in the repository.

            Searches for code content, filenames, or paths. Returns a formatted
            text listing of matching files with code fragments.

            Args:
                query: Search query (e.g., 'enable_tool_optimization' or 'rlm.py')

            Returns:
                Formatted text listing of search results with file paths and fragments
            """
            results = runner._sync_call(runner._repo_tools.search_code(query))
            if not results:
                return "[No matches found]"

            # Format as readable text
            lines = []
            for result in results:
                path = result.get("path", "?")
                fragment = result.get("fragment", "")
                if fragment:
                    # Truncate fragment if too long
                    if len(fragment) > 100:
                        fragment = fragment[:100] + "..."
                    lines.append(f"{path}: {fragment}")
                else:
                    lines.append(f"{path}")
            return "\n".join(lines)

        return {"fetch_file": fetch_file, "list_dir": list_dir, "search_code": search_code}

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
        
        # Configure DSPy with specified model (cache=False to prevent disk caching)
        model_name = self.model
        if not model_name.startswith("gemini/"):
            model_name = f"gemini/{model_name}"
        
        self._lm = dspy.LM(model_name, cache=False)
        
        # Create RLM with custom interpreter that has Deno 2.x fix
        deno_command = build_deno_command()
        interpreter = PythonInterpreter(deno_command=deno_command)
        
        # Standard signature
        sub_model = f"gemini/{SUB_MODEL}" if not SUB_MODEL.startswith("gemini/") else SUB_MODEL
        self._rlm = dspy.RLM(
            signature="context, question -> answer, sources",
            max_iterations=MAX_ITERATIONS,
            max_llm_calls=MAX_LLM_CALLS,
            sub_lm=dspy.LM(sub_model, cache=False),
            verbose=not self.quiet,
            interpreter=interpreter,
            tools=self._create_tool_functions(),
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

        # Get head SHA for PR (for consistent file reads)
        head_sha = data.get("head_sha", "HEAD")

        # Create repo tools for this review
        self._repo_tools = RepoTools(owner, repo, head_sha)

        # Build context from PR data
        context = build_review_context(data)

        # Run RLM
        self._ensure_configured()

        try:
            with dspy.context(lm=self._lm):
                result = await self._rlm.aforward(context=context, question=question)

            # Extract answer and sources from result
            answer = result.answer
            sources = result.sources
            if isinstance(sources, str):
                sources = [s.strip() for s in sources.split(",") if s.strip()]

            # Note: DSPy's verbose=True already shows step-by-step progress in real-time.
            # Post-hoc trajectory replay via on_step is intentionally removed to avoid
            # duplicate output (steps were being shown twice).
        finally:
            # Cleanup
            if self._repo_tools:
                await self._repo_tools.close()
                self._repo_tools = None

        metadata = {
            "type": url_type,
            "owner": owner,
            "repo": repo,
            "number": number,
            "title": data.get("title", ""),
            "model": self.model,
            "files_fetched": [],
        }

        return answer, sources, metadata

    async def review_local(self, path: str, question: str) -> tuple[str, list[str], dict]:
        """Review a local directory.

        Args:
            path: Local directory path (relative or absolute)
            question: Question to ask about the code

        Returns:
            Tuple of (answer, sources, metadata)
        """
        # Validate and resolve path
        abs_path = validate_local_path(path)

        # Create local repo tools
        local_tools = LocalRepoTools(abs_path)
        self._repo_tools = local_tools

        # Build context from local directory
        context = build_local_context(abs_path)

        # Run RLM
        self._ensure_configured()

        try:
            with dspy.context(lm=self._lm):
                result = await self._rlm.aforward(context=context, question=question)

            # Extract answer and sources from result
            answer = result.answer
            sources = result.sources
            if isinstance(sources, str):
                sources = [s.strip() for s in sources.split(",") if s.strip()]

            # Note: DSPy's verbose=True already shows step-by-step progress in real-time.
            # Post-hoc trajectory replay via on_step is intentionally removed to avoid
            # duplicate output (steps were being shown twice).
        finally:
            # Cleanup
            if self._repo_tools:
                await self._repo_tools.close()
                self._repo_tools = None

        metadata = {
            "type": "local",
            "path": abs_path,
            "model": self.model,
            "files_fetched": [],
        }

        return answer, sources, metadata
    
    async def review_pr(self, url: str, question: str) -> tuple[str, list[str], dict]:
        """Review a GitHub PR with full diff context."""
        return await self.review(url, question)
    
    async def review_issue(self, url: str, question: str) -> tuple[str, list[str], dict]:
        """Review a GitHub issue."""
        return await self.review(url, question)
