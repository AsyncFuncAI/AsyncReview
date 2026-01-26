"""RLM runner with DSPy configuration and trace capture."""

import json
import logging
import os
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import dspy
from dspy.primitives.python_interpreter import PythonInterpreter

from .config import (
    CR_CACHE_DIR,
    MAIN_MODEL,
    MAX_ITERATIONS,
    MAX_LLM_CALLS,
    SUB_MODEL,
    TRACES_DIR,
)
from .snapshot import build_snapshot
from .types import CodebaseSnapshot, RLMTrace, TraceStep


def build_deno_command() -> list[str]:
    """Build a Deno command for RLM code execution.

    This is needed for Deno 2.x compatibility where npm packages (like pyodide)
    are stored in Deno's global cache. We use --node-modules-dir=false to ensure
    Deno uses its global npm cache rather than looking for a local node_modules.

    Returns:
        List of command arguments for Deno
    """
    # Get Deno's cache directory
    deno_dir = ""
    if "DENO_DIR" in os.environ:
        deno_dir = os.environ["DENO_DIR"]
    else:
        try:
            result = subprocess.run(
                ['deno', 'info', '--json'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                deno_info = json.loads(result.stdout)
                deno_dir = deno_info.get('denoDir', '')
        except Exception:
            pass

    # Get the runner.js path from DSPy
    import dspy.primitives.python_interpreter as pi
    runner_path = os.path.join(os.path.dirname(pi.__file__), "runner.js")

    # Build allowed read paths
    read_paths = [runner_path]
    if deno_dir:
        read_paths.append(deno_dir)

    # Deno 2.x: Use --node-modules-dir=false to use global npm cache
    # This is critical for Deno 2.x which otherwise looks for local node_modules
    return [
        'deno', 'run',
        '--node-modules-dir=false',  # Use Deno's global npm cache
        f'--allow-read={",".join(read_paths)}',
        runner_path
    ]


class TraceCapture:
    """Captures RLM trace steps during execution."""

    def __init__(self, trace: RLMTrace):
        self.trace = trace
        self.current_step = 0

    def add_step(self, reasoning: str, code: str, stdout: str = "", artifacts: dict | None = None):
        """Add a step to the trace."""
        self.current_step += 1
        self.trace.steps.append(
            TraceStep(
                step=self.current_step,
                reasoning=reasoning,
                code=code,
                stdout=stdout,
                artifacts=artifacts or {},
            )
        )


class RLMLogHandler(logging.Handler):
    """Logging handler that captures RLM iteration logs."""

    def __init__(self, trace_capture: TraceCapture, on_step: Callable[[int, str, str], None] | None = None):
        super().__init__()
        self.trace_capture = trace_capture
        self.on_step = on_step  # Callback for UI updates

    def emit(self, record):
        msg = record.getMessage()
        if "RLM iteration" not in msg:
            return

        parts = msg.split("\n", 1)
        header = parts[0]

        # Extract iteration number
        try:
            iter_num = int(header.split("iteration")[1].strip().split("/")[0].strip())
        except (ValueError, IndexError):
            iter_num = self.trace_capture.current_step + 1

        if len(parts) <= 1 or "Reasoning:" not in parts[1]:
            return

        content = parts[1]
        reasoning_start = content.find("Reasoning:") + len("Reasoning:")
        code_start = content.find("Code:")

        if code_start > 0:
            reasoning = content[reasoning_start:code_start].strip()
            code = content[code_start + len("Code:"):].strip()
        else:
            reasoning = content[reasoning_start:].strip()
            code = ""

        # Clean up code block markers
        if code:
            code = code.strip()
            for prefix in ("```python", "```"):
                if code.startswith(prefix):
                    code = code[len(prefix):]
                    break
            if code.endswith("```"):
                code = code[:-3]
            code = code.strip()

        self.trace_capture.add_step(reasoning=reasoning, code=code)

        # Notify UI
        if self.on_step:
            self.on_step(iter_num, reasoning, code)


def setup_rlm_logging(trace_capture: TraceCapture, on_step: Callable[[int, str, str], None] | None = None) -> RLMLogHandler:
    """Set up logging to capture RLM iterations."""
    handler = RLMLogHandler(trace_capture, on_step)
    handler.setLevel(logging.INFO)

    rlm_logger = logging.getLogger("dspy.predict.rlm")
    rlm_logger.setLevel(logging.INFO)
    rlm_logger.addHandler(handler)

    # Suppress noisy loggers
    for name in ("httpx", "anthropic", "google", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)

    return handler


def save_trace(trace: RLMTrace) -> Path:
    """Save trace to JSON file."""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = trace.started_at.strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}.json"
    filepath = TRACES_DIR / filename

    with open(filepath, "w") as f:
        json.dump(trace.to_dict(), f, indent=2)

    return filepath


def format_history(history: list[tuple[str, str]]) -> str:
    """Format conversation history for RLM input."""
    if not history:
        return "No previous conversation."
    lines = ["Previous conversation:"]
    for i, (q, a) in enumerate(history, 1):
        lines.extend([f"\nQ{i}: {q}", f"A{i}: {a}"])
    return "\n".join(lines)


class CodebaseReviewRLM:
    """RLM-based codebase review engine."""

    def __init__(self, on_step: Callable[[int, str, str], None] | None = None):
        """Initialize the RLM engine.
        
        Args:
            on_step: Optional callback(step_num, reasoning, code) for UI updates
        """
        self.on_step = on_step
        self._rlm = None
        self._configured = False

    def _ensure_configured(self):
        """Ensure DSPy is configured."""
        if self._configured:
            return

        dspy.configure(lm=dspy.LM(MAIN_MODEL))

        # Create custom interpreter with Deno command that includes node_modules
        # This is needed for Deno 2.x where pyodide is in local node_modules
        deno_command = build_deno_command()
        interpreter = PythonInterpreter(deno_command=deno_command)

        self._rlm = dspy.RLM(
            signature="codebase, conversation_history, question -> answer, sources",
            max_iterations=MAX_ITERATIONS,
            max_llm_calls=MAX_LLM_CALLS,
            sub_lm=dspy.LM(SUB_MODEL),
            verbose=True,
            interpreter=interpreter,
        )
        self._configured = True

    def run(
        self,
        repo_path: str | Path,
        question: str,
        history: list[tuple[str, str]] | None = None,
        save_trace_file: bool = True,
    ) -> tuple[str, list[str], RLMTrace]:
        """Run the RLM on a codebase with a question.

        Args:
            repo_path: Path to the repository
            question: The question to answer
            history: Optional conversation history as [(question, answer), ...]
            save_trace_file: Whether to save the trace to a file

        Returns:
            Tuple of (answer, sources, trace)
        """
        self._ensure_configured()

        # Build snapshot
        snapshot = build_snapshot(repo_path)

        # Create trace
        trace = RLMTrace(
            question=question,
            repo_path=str(repo_path),
            started_at=datetime.now(),
        )

        # Set up logging
        trace_capture = TraceCapture(trace)
        handler = setup_rlm_logging(trace_capture, self.on_step)

        try:
            # Run RLM - use simple dict format (path -> content) like huberman example
            result = self._rlm(
                codebase=snapshot.to_simple_dict(),
                conversation_history=format_history(history or []),
                question=question,
            )

            # Extract results
            answer = getattr(result, "answer", str(result))
            sources = getattr(result, "sources", [])
            if isinstance(sources, str):
                sources = [s.strip() for s in sources.split(",") if s.strip()]

            trace.answer = answer
            trace.sources = sources
            trace.ended_at = datetime.now()

        except Exception as e:
            trace.error = str(e)
            trace.ended_at = datetime.now()
            raise

        finally:
            # Clean up logging handler
            rlm_logger = logging.getLogger("dspy.predict.rlm")
            rlm_logger.removeHandler(handler)

            # Save trace
            if save_trace_file:
                save_trace(trace)

        return answer, sources, trace

    def run_one_shot(
        self,
        repo_path: str | Path,
        question: str,
        save_trace_file: bool = True,
    ) -> tuple[str, list[str], RLMTrace]:
        """Run a one-shot question (no history).

        Args:
            repo_path: Path to the repository
            question: The question to answer
            save_trace_file: Whether to save the trace to a file

        Returns:
            Tuple of (answer, sources, trace)
        """
        return self.run(repo_path, question, history=None, save_trace_file=save_trace_file)

