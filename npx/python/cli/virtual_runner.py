"""Virtual review runner - runs RLM reviews on GitHub content without local repo."""

import asyncio
import logging
import re
from typing import Callable

import dspy
from dspy.primitives.python_interpreter import PythonInterpreter
from dspy.primitives.prediction import Prediction
from dspy.primitives.repl_types import REPLHistory

from cr.config import MAIN_MODEL, SUB_MODEL, MAX_ITERATIONS, MAX_LLM_CALLS
from cr.rlm_runner import build_deno_command

from .github_fetcher import (
    parse_github_url,
    fetch_pr,
    fetch_issue,
    build_review_context,
)
from .repo_tools import RepoTools


# Tool usage instructions for the model - simplified and clear
AGENTIC_TOOLS_PROMPT = """
## REPOSITORY ACCESS COMMANDS

You can access ANY file in the repository (not just the diff). Use these commands:

### STEP 1: Find file paths with SEARCH_CODE
```python
print("SEARCH_CODE:rlm.py")  # Search for files by name
print("SEARCH_CODE:enable_tool_optimization")  # Search for code patterns
```
Results appear in `search_results` on your NEXT step.

### STEP 2: Fetch files with FETCH_FILE
```python
print("FETCH_FILE:dspy/predict/rlm.py")  # Exact path required
```
Content appears in `repo_files['dspy/predict/rlm.py']` on your NEXT step.

### STEP 3: List directories with LIST_DIR
```python
print("LIST_DIR:dspy/predict/")
```
Entries appear in `repo_dirs['dspy/predict/']` on your NEXT step.

### IMPORTANT NOTES:
- Commands print EXACTLY as shown, the system intercepts them
- Do NOT try os.walk() or open() - those won't work
- Data becomes available on your NEXT step
- Check `repo_files`, `repo_dirs`, `search_results` dicts

### WORKFLOW EXAMPLE (finding if rlm.py contains X):
Step 1: `print("SEARCH_CODE:rlm.py")` → find the path
Step 2: Check `search_results` for path, then `print("FETCH_FILE:dspy/predict/rlm.py")`
Step 3: Check `repo_files['dspy/predict/rlm.py']` for content
"""




class VirtualReviewRunner:
    """Run RLM code reviews on GitHub PRs without a local repository.
    
    Creates a 'virtual' codebase context from GitHub API data.
    Supports agentic file fetching via FETCH_FILE/LIST_DIR/SEARCH_CODE commands.
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
        self._repo_files: dict[str, str] = {}  # Fetched file contents
        self._repo_dirs: dict[str, list] = {}  # Directory listings
        self._search_results: list[dict] = []  # Search results
    
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
        
        self._lm = dspy.LM(model_name)
        
        # Create RLM with custom interpreter that has Deno 2.x fix
        deno_command = build_deno_command()
        interpreter = PythonInterpreter(deno_command=deno_command)
        
        # Standard signature
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
        
        # Get head SHA for PR (for consistent file reads)
        head_sha = data.get("head_sha", "HEAD")
        
        # Create repo tools for this review
        self._repo_tools = RepoTools(owner, repo, head_sha)
        self._repo_files = {}
        self._repo_dirs = {}
        self._search_results = []
        
        # Build context from PR data (tools go in question, not context)
        context = build_review_context(data)
        
        # Run RLM
        self._ensure_configured()
        
        try:
            answer, sources = await self._run_rlm_with_tools(context, question)
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
            "files_fetched": list(self._repo_files.keys()),
        }
        
        return answer, sources, metadata
    
    async def _process_tool_requests(self, output: str) -> bool:
        """Parse output for tool requests and execute them.
        
        Returns True if any tools were executed.
        """
        if not self._repo_tools:
            return False
        
        executed = False
        
        # Check for FETCH_FILE requests
        fetch_matches = re.findall(r'FETCH_FILE:([^\s\n]+)', output)
        if fetch_matches and not self.quiet:
            print(f"\n[DEBUG] Found FETCH_FILE requests: {fetch_matches}")
        for path in fetch_matches[:3]:  # Limit to 3 per iteration
            if path not in self._repo_files:
                if not self.quiet:
                    print(f"[DEBUG] Fetching file: {path}")
                content = await self._repo_tools.fetch_file(path)
                self._repo_files[path] = content
                if not self.quiet:
                    print(f"[DEBUG] Fetched {path}: {len(content)} chars, starts with: {content[:100]}...")
                executed = True
        
        # Check for LIST_DIR requests
        dir_matches = re.findall(r'LIST_DIR:([^\s\n]+)', output)
        if dir_matches and not self.quiet:
            print(f"\n[DEBUG] Found LIST_DIR requests: {dir_matches}")
        for path in dir_matches[:2]:  # Limit to 2 per iteration
            if path not in self._repo_dirs:
                entries = await self._repo_tools.list_directory(path)
                self._repo_dirs[path] = entries
                if not self.quiet:
                    print(f"[DEBUG] Listed {path}: {len(entries)} entries")
                executed = True
        
        # Check for SEARCH_CODE requests
        search_matches = re.findall(r'SEARCH_CODE:(.+?)(?:\n|$)', output)
        if search_matches and not self.quiet:
            print(f"\n[DEBUG] Found SEARCH_CODE requests: {search_matches}")
        for query in search_matches[:1]:  # Limit to 1 per iteration
            results = await self._repo_tools.search_code(query.strip())
            self._search_results = results
            if not self.quiet:
                print(f"[DEBUG] Search for '{query.strip()}': {len(results)} results")
                for r in results[:3]:
                    print(f"[DEBUG]   - {r.get('path')}")
            executed = True
        
        return executed
    
    async def _run_rlm_with_tools(self, context: str, question: str) -> tuple[str, list[str]]:
        """Run the RLM with agentic tool support."""
        from dspy.predict.rlm import _strip_code_fences
        
        rlm = self._rlm
        output_field_names = list(rlm.signature.output_fields.keys())
        execution_tools = rlm._prepare_execution_tools()
        
        # Prepend tool instructions to question (treated as instructions, not data)
        augmented_question = AGENTIC_TOOLS_PROMPT + "\n\n---\n\n**USER QUESTION:** " + question
        
        input_args = {
            "context": context,
            "question": augmented_question,
        }
        
        variables = rlm._build_variables(**input_args)
        
        with dspy.context(lm=self._lm):
            with rlm._interpreter_context(execution_tools) as repl:
                history = REPLHistory()
                
                for iteration in range(rlm.max_iterations):
                    variables_info = [variable.format() for variable in variables]
                    pred = await rlm.generate_action.acall(
                        variables_info=variables_info,
                        repl_history=history,
                        iteration=f"{iteration + 1}/{rlm.max_iterations}",
                    )
                    
                    # Execute the code with current repo state
                    try:
                        code = _strip_code_fences(pred.code)
                        
                        # Inject serializable data only
                        exec_vars = {
                            "context": context,
                            "question": question,
                            "repo_files": self._repo_files,
                            "repo_dirs": self._repo_dirs,
                            "search_results": self._search_results,
                        }
                        
                        result = repl.execute(code, variables=exec_vars)
                    except Exception as e:
                        result = f"[Error] {e}"
                    
                    # Format output
                    if isinstance(result, list):
                        output = "\n".join(map(str, result))
                    else:
                        output = str(result) if result else ""
                    
                    # Process any tool requests in the output
                    await self._process_tool_requests(output)
                    
                    # Call step callback if provided (pass reasoning, code, and output)
                    if self.on_step:
                        self.on_step(iteration + 1, pred.reasoning, code, output)
                    
                    # Process result to check if done
                    processed = rlm._process_execution_result(pred, result, history, output_field_names)
                    
                    if isinstance(processed, Prediction):
                        # Done!
                        answer = getattr(processed, "answer", str(processed))
                        sources = getattr(processed, "sources", [])
                        if isinstance(sources, str):
                            sources = [s.strip() for s in sources.split(",") if s.strip()]
                        return answer, sources
                    
                    history = processed
                
                # Max iterations reached
                final_result = await rlm._aextract_fallback(variables, history, output_field_names)
                answer = getattr(final_result, "answer", str(final_result))
                sources = getattr(final_result, "sources", [])
                if isinstance(sources, str):
                    sources = [s.strip() for s in sources.split(",") if s.strip()]
                return answer, sources
    
    async def review_pr(self, url: str, question: str) -> tuple[str, list[str], dict]:
        """Review a GitHub PR with full diff context."""
        return await self.review(url, question)
    
    async def review_issue(self, url: str, question: str) -> tuple[str, list[str], dict]:
        """Review a GitHub issue."""
        return await self.review(url, question)
