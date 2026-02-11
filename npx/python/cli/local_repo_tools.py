"""Local filesystem version of RepoTools for agentic code review.

Provides the same interface as RepoTools but reads from local filesystem
instead of GitHub API. Enables RLM to explore local files during review.
"""

import asyncio
import os
import re
import subprocess
from typing import Any

from .repo_tools import MAX_FILE_BYTES, sanitize_path, find_line_range

# Common ignore patterns for directory listing
IGNORE_PATTERNS = {
    "node_modules",
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    "*.egg-info",
}

# File extensions to search
SEARCH_EXTENSIONS = (
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".md", ".json",
    ".yaml", ".yml", ".sh", ".bash"
)


class LocalRepoTools:
    """Tools for exploring a local repository."""
    
    def __init__(self, root_path: str):
        """Initialize with local directory root path.
        
        Args:
            root_path: Absolute or relative path to repository root
        """
        self.root_path = os.path.realpath(root_path)
        if not os.path.isdir(self.root_path):
            raise ValueError(f"root_path is not a directory: {self.root_path}")
    
    def _resolve_path(self, path: str) -> str | None:
        """Resolve and validate a path relative to root_path.
        
        Returns absolute path if valid, None if invalid or outside root.
        """
        clean = sanitize_path(path) if path else ""
        if clean is None:
            return None
        
        # Build absolute path
        abs_path = os.path.realpath(os.path.join(self.root_path, clean))
        
        # Security: ensure resolved path is within root_path
        if not abs_path.startswith(self.root_path + os.sep) and abs_path != self.root_path:
            return None
        
        return abs_path
    
    async def fetch_file(self, path: str) -> str:
        """Fetch a file from the local filesystem.
        
        Returns file content or error/skip stub.
        """
        abs_path = self._resolve_path(path)
        if abs_path is None:
            return "[ERROR: invalid path]"
        
        if not os.path.exists(abs_path):
            return "[ERROR: 404 - not found]"
        
        if not os.path.isfile(abs_path):
            return "[SKIPPED: path is a directory, use list_directory]"
        
        # Check size
        try:
            size = os.path.getsize(abs_path)
        except OSError:
            return "[ERROR: cannot read file]"
        
        if size > MAX_FILE_BYTES:
            return f"[SKIPPED: file exceeds {MAX_FILE_BYTES // 1000}KB limit ({size // 1000}KB)]"
        
        # Try to read as text
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
            return content
        except (UnicodeDecodeError, OSError):
            return "[SKIPPED: binary/unsupported file]"
    
    async def list_directory(self, path: str = "") -> list[dict[str, Any]]:
        """List files and directories at a path.
        
        Returns structured entries: [{path, type, size}]
        """
        # Treat ".", "./", "/" same as "" (root directory)
        abs_path = self._resolve_path(path) if path and path.strip() not in (".", "./", "/") else self.root_path
        if abs_path is None:
            return [{"error": "invalid path"}]
        
        if not os.path.exists(abs_path):
            return [{"error": "not found"}]
        
        # Single file case
        if os.path.isfile(abs_path):
            rel_path = os.path.relpath(abs_path, self.root_path)
            return [{
                "path": rel_path.replace(os.sep, "/"),
                "type": "file",
                "size": os.path.getsize(abs_path),
            }]
        
        # Directory listing
        entries = []
        try:
            for entry in os.listdir(abs_path):
                # Skip hidden files/dirs
                if entry.startswith("."):
                    continue
                # Skip ignore patterns
                if entry in IGNORE_PATTERNS:
                    continue
                
                entry_path = os.path.join(abs_path, entry)
                rel_path = os.path.relpath(entry_path, self.root_path)
                
                if os.path.isdir(entry_path):
                    entries.append({
                        "path": rel_path.replace(os.sep, "/"),
                        "type": "dir",
                        "size": 0,
                    })
                else:
                    entries.append({
                        "path": rel_path.replace(os.sep, "/"),
                        "type": "file",
                        "size": os.path.getsize(entry_path),
                    })
        except OSError:
            return [{"error": "cannot read directory"}]
        
        return entries
    
    async def search_code(self, query: str) -> list[dict[str, Any]]:
        """Search for code patterns in the local repo using grep.

        Returns paths + fragments. Soft-fails on error (returns []).
        """
        if not query or not query.strip():
            return []

        query = query.strip()

        # Build grep command as list (no shell=True to prevent shell injection)
        args = ["grep", "-rn"]
        for ext in SEARCH_EXTENSIONS:
            args.append(f"--include=*{ext}")
        args.append("--")  # End of options, prevents query from being interpreted as flag
        args.append(query)
        args.append(self.root_path)

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return []  # Soft fail
        except Exception:
            return []  # Soft fail

        if result.returncode != 0:
            return []  # No matches or error

        results = []
        for line in result.stdout.splitlines()[:10]:  # Limit to 10 results
            # Parse grep output: path:line:content
            parts = line.split(":", 2)
            if len(parts) >= 3:
                file_path = parts[0]
                rel_path = os.path.relpath(file_path, self.root_path)
                fragment = parts[2][:500]  # Limit fragment size
                results.append({
                    "path": rel_path.replace(os.sep, "/"),
                    "fragment": fragment,
                })

        return results
    
    async def get_symbol_definition(self, symbol: str, context_file: str = "") -> str:
        """Find the definition of a symbol (function or class).

        Uses grep to find 'def symbol' or 'class symbol' patterns.
        Returns path + snippet or error message.
        """
        if not symbol or not symbol.strip():
            return "[ERROR: empty symbol]"

        symbol = symbol.strip()
        # Extract simple name from dotted paths (e.g., "dspy.adapters.DataFrame" -> "DataFrame")
        if "." in symbol:
            symbol = symbol.rsplit(".", 1)[-1]

        # Build grep command to find definitions
        args = ["grep", "-rn"]
        for ext in SEARCH_EXTENSIONS:
            args.append(f"--include=*{ext}")
        args.append("--")
        # Search for "def symbol" or "class symbol"
        args.append(f"(def|class) {symbol}")
        args.append(self.root_path)

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return "[ERROR: search timeout]"
        except Exception as e:
            return f"[ERROR: {str(e)[:50]}]"

        if result.returncode != 0:
            return f"[ERROR: symbol '{symbol}' not found]"

        # Parse first match
        lines = result.stdout.splitlines()
        if not lines:
            return f"[ERROR: symbol '{symbol}' not found]"

        first_match = lines[0]
        parts = first_match.split(":", 2)
        if len(parts) >= 3:
            file_path = parts[0]
            line_num = parts[1]
            rel_path = os.path.relpath(file_path, self.root_path)
            snippet = parts[2][:200]
            return f"local:{rel_path}#L{line_num}\n{snippet}"

        return f"[ERROR: could not parse definition]"

    async def find_usages(self, symbol: str, scope_path: str = ".") -> str:
        """Find all usages of a symbol in the codebase.

        Uses grep to find references. Returns formatted list of matches.
        """
        if not symbol or not symbol.strip():
            return "[ERROR: empty symbol]"

        symbol = symbol.strip()
        # Extract simple name from dotted paths (e.g., "dspy.predict.rlm.RLM" -> "RLM")
        if "." in symbol:
            symbol = symbol.rsplit(".", 1)[-1]

        # Resolve scope path
        scope_abs = self._resolve_path(scope_path) if scope_path != "." else self.root_path
        if scope_abs is None:
            scope_abs = self.root_path

        # Build grep command
        args = ["grep", "-rn"]
        for ext in SEARCH_EXTENSIONS:
            args.append(f"--include=*{ext}")
        args.append("--")
        args.append(symbol)
        args.append(scope_abs)

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return "[ERROR: search timeout]"
        except Exception as e:
            return f"[ERROR: {str(e)[:50]}]"

        if result.returncode != 0:
            return f"[ERROR: no usages found for '{symbol}']"

        # Format results
        results = []
        for line in result.stdout.splitlines()[:20]:  # Limit to 20 results
            parts = line.split(":", 2)
            if len(parts) >= 3:
                file_path = parts[0]
                line_num = parts[1]
                rel_path = os.path.relpath(file_path, self.root_path)
                snippet = parts[2][:100]
                results.append(f"  {rel_path}:{line_num} {snippet}")

        if not results:
            return f"[ERROR: no usages found for '{symbol}']"

        return f"Found {len(results)} usages of '{symbol}':\n" + "\n".join(results)

    async def get_type_hierarchy(self, class_name: str) -> str:
        """Get the type hierarchy (parent classes) for a class.

        Finds class definition and parses parent classes, including one level of parent resolution.
        """
        if not class_name or not class_name.strip():
            return "[ERROR: empty class name]"

        class_name = class_name.strip()
        # Extract simple name from dotted paths (e.g., "dspy.adapters.DataFrame" -> "DataFrame")
        if "." in class_name:
            class_name = class_name.rsplit(".", 1)[-1]

        # Find class definition
        args = ["grep", "-rn"]
        for ext in SEARCH_EXTENSIONS:
            args.append(f"--include=*{ext}")
        args.append("--")
        args.append(f"class {class_name}")
        args.append(self.root_path)

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return "[ERROR: search timeout]"
        except Exception as e:
            return f"[ERROR: {str(e)[:50]}]"

        if result.returncode != 0:
            return f"[ERROR: class '{class_name}' not found]"

        # Parse first match to extract parent classes
        lines = result.stdout.splitlines()
        if not lines:
            return f"[ERROR: class '{class_name}' not found]"

        first_match = lines[0]
        parts = first_match.split(":", 2)
        if len(parts) < 3:
            return f"[ERROR: could not parse class definition]"

        file_path = parts[0]
        line_num = parts[1]
        rel_path = os.path.relpath(file_path, self.root_path)

        # Read the actual file and apply regex to full content to handle multi-line defs
        import re
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                file_content = f.read()
        except Exception:
            return f"[ERROR: could not read {rel_path}]"

        # Extract parent classes from "class X(Parent1, Parent2):" pattern
        # Use re.DOTALL to handle multi-line class definitions
        pattern = rf"class\s+{re.escape(class_name)}\s*\(([^)]+)\)"
        match = re.search(pattern, file_content, re.DOTALL)
        parents = []
        if match:
            parent_str = match.group(1)
            # Strip whitespace and newlines from each parent, filter out empty strings
            parents = [p.strip() for p in parent_str.split(",") if p.strip()]

        hierarchy = f"Type hierarchy for '{class_name}':\n"
        hierarchy += f"  {class_name} extends: {', '.join(parents) if parents else '(no parents)'}\n"
        hierarchy += f"  Parent details:\n"

        # Resolve one level of parent classes
        for parent in parents:
            parent_info = await self._resolve_parent_class_local(parent)
            if parent_info:
                hierarchy += f"    {parent_info}\n"
            else:
                hierarchy += f"    {parent} (no parents found)\n"

        return hierarchy

    async def _resolve_parent_class_local(self, parent_name: str) -> str | None:
        """Resolve one level of parent class hierarchy in local filesystem.

        Searches for the parent class definition and extracts its parents.
        Returns a string like "ParentClass extends: GrandParent" or None if not found.
        """
        if not parent_name or not parent_name.strip():
            return None

        parent_name = parent_name.strip()

        # Find parent class definition
        args = ["grep", "-rn"]
        for ext in SEARCH_EXTENSIONS:
            args.append(f"--include=*{ext}")
        args.append("--")
        args.append(f"class {parent_name}")
        args.append(self.root_path)

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, Exception):
            return None

        if result.returncode != 0:
            return None

        lines = result.stdout.splitlines()
        if not lines:
            return None

        first_match = lines[0]
        parts = first_match.split(":", 2)
        if len(parts) < 3:
            return None

        file_path = parts[0]

        # Read the actual file and apply regex to full content
        import re
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                file_content = f.read()
        except Exception:
            return None

        # Extract parent classes of the parent class
        pattern = rf"class\s+{re.escape(parent_name)}\s*\(([^)]+)\)"
        match = re.search(pattern, file_content, re.DOTALL)

        if not match:
            return None

        parent_str = match.group(1)
        grandparents = [p.strip() for p in parent_str.split(",") if p.strip()]

        return f"{parent_name} extends: {', '.join(grandparents)}"

    async def get_call_graph(self, func_name: str, depth: int = 1) -> str:
        """Get the call graph for a function (functions it calls and callers).

        Limited to depth 1 for performance.
        """
        if not func_name or not func_name.strip():
            return "[ERROR: empty function name]"

        func_name = func_name.strip()
        # Extract simple name from dotted paths (e.g., "module.sub.my_func" -> "my_func")
        if "." in func_name:
            func_name = func_name.rsplit(".", 1)[-1]

        # Find function definition
        args = ["grep", "-rn"]
        for ext in SEARCH_EXTENSIONS:
            args.append(f"--include=*{ext}")
        args.append("--")
        args.append(f"def {func_name}")
        args.append(self.root_path)

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return "[ERROR: search timeout]"
        except Exception as e:
            return f"[ERROR: {str(e)[:50]}]"

        if result.returncode != 0:
            return f"[ERROR: function '{func_name}' not found]"

        lines = result.stdout.splitlines()
        if not lines:
            return f"[ERROR: function '{func_name}' not found]"

        first_match = lines[0]
        parts = first_match.split(":", 2)
        if len(parts) < 3:
            return f"[ERROR: could not parse function definition]"

        file_path = parts[0]
        line_num = parts[1]
        rel_path = os.path.relpath(file_path, self.root_path)

        # Find callers of this function
        caller_args = ["grep", "-rn"]
        for ext in SEARCH_EXTENSIONS:
            caller_args.append(f"--include=*{ext}")
        caller_args.append("--")
        caller_args.append(f"{func_name}(")
        caller_args.append(self.root_path)

        callers = []
        try:
            caller_result = subprocess.run(
                caller_args,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if caller_result.returncode == 0:
                for line in caller_result.stdout.splitlines()[:10]:
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        caller_file = parts[0]
                        caller_line = parts[1]
                        caller_rel = os.path.relpath(caller_file, self.root_path)
                        callers.append(f"  {caller_rel}:{caller_line}")
        except Exception:
            pass  # Soft fail on caller search

        result_str = f"local:{rel_path}#L{line_num}\ndef {func_name}(...)"
        if callers:
            result_str += f"\n\nCallers ({len(callers)}):\n" + "\n".join(callers)
        else:
            result_str += "\n\nNo callers found"

        # If depth >= 1, find outgoing calls from this function
        if depth >= 1:
            outgoing = await self._get_outgoing_calls(file_path, func_name)
            if outgoing:
                result_str += f"\n\nCalls (outgoing):\n" + "\n".join(f"  {call}" for call in outgoing)
            else:
                result_str += "\n\nCalls (outgoing): none found"

        return result_str

    async def _get_outgoing_calls(self, file_path: str, func_name: str) -> list[str]:
        """Extract outgoing calls from a function definition.

        Returns list of function names called by func_name.
        """
        # Extract simple name from dotted paths
        if "." in func_name:
            func_name = func_name.rsplit(".", 1)[-1]

        # Python keywords to filter out
        keywords = {
            "if", "for", "while", "return", "print", "range", "len", "str",
            "int", "list", "dict", "set", "tuple", "type", "isinstance",
            "hasattr", "getattr", "setattr", "super", "enumerate", "zip",
            "map", "filter", "sorted", "reversed", "any", "all", "min",
            "max", "sum", "abs", "round", "open", "format", "repr", "hash",
            "id", "input", "next", "iter"
        }

        # Read the file
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return []

        # Extract function body
        func_body = self._extract_function_body(content, func_name)
        if not func_body:
            return []

        # Find all function calls using regex: word followed by (
        pattern = r"\b(\w+)\s*\("
        matches = re.findall(pattern, func_body)

        # Filter out keywords and duplicates
        calls = []
        seen = set()
        for match in matches:
            if match not in keywords and match not in seen:
                calls.append(match)
                seen.add(match)

        return calls[:10]  # Limit to 10 results

    def _extract_function_body(self, content: str, func_name: str) -> str:
        """Extract the body of a function from file content.

        Returns the function body as a string, or empty string if not found.
        """
        lines = content.splitlines()
        func_start = None

        # Find the function definition line
        for i, line in enumerate(lines):
            if re.match(rf"def\s+{re.escape(func_name)}\s*\(", line):
                func_start = i
                break

        if func_start is None:
            return ""

        # Get the indentation level of the function definition
        def_line = lines[func_start]
        def_indent = len(def_line) - len(def_line.lstrip())

        # Extract lines until we hit a line with same or less indentation (next function/class)
        body_lines = [def_line]
        for i in range(func_start + 1, len(lines)):
            line = lines[i]
            # Skip empty lines
            if not line.strip():
                body_lines.append(line)
                continue
            # Check indentation
            line_indent = len(line) - len(line.lstrip())
            if line_indent <= def_indent and line.strip():
                # Hit next function/class at same level
                break
            body_lines.append(line)

        return "\n".join(body_lines)

    async def get_pr_comments(self, pr_number: int) -> str:
        """Get PR comments (not available in local mode)."""
        return "[Not available for local repos — use --url mode]"

    async def get_blame(self, path: str, line_range: str = "") -> str:
        """Get git blame information for a file or line range.

        Uses 'git blame' subprocess. Line range format: "10,20" for lines 10-20.
        """
        if not path or not path.strip():
            return "[ERROR: empty path]"

        abs_path = self._resolve_path(path)
        if abs_path is None:
            return "[ERROR: invalid path]"

        if not os.path.exists(abs_path):
            return "[ERROR: file not found]"

        # Build git blame command
        args = ["git", "blame"]
        if line_range:
            # Parse line range "start,end"
            try:
                parts = line_range.split(",")
                if len(parts) == 2:
                    start, end = parts[0].strip(), parts[1].strip()
                    args.append(f"-L{start},{end}")
            except Exception:
                pass  # Ignore malformed line range

        args.append(abs_path)

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.root_path,
            )
        except subprocess.TimeoutExpired:
            return "[ERROR: blame timeout]"
        except Exception as e:
            return f"[ERROR: {str(e)[:50]}]"

        if result.returncode != 0:
            return f"[ERROR: git blame failed]"

        # Limit output to first 30 lines
        lines = result.stdout.splitlines()[:30]
        return "\n".join(lines) if lines else "[ERROR: no blame output]"

    async def get_commit_history(self, path: str, limit: int = 5) -> str:
        """Get commit history for a file.

        Uses 'git log --oneline' subprocess.
        """
        if not path or not path.strip():
            return "[ERROR: empty path]"

        abs_path = self._resolve_path(path)
        if abs_path is None:
            return "[ERROR: invalid path]"

        if not os.path.exists(abs_path):
            return "[ERROR: file not found]"

        # Clamp limit
        limit = max(1, min(limit, 50))

        # Build git log command
        args = ["git", "log", "--oneline", f"-n{limit}", "--", abs_path]

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.root_path,
            )
        except subprocess.TimeoutExpired:
            return "[ERROR: log timeout]"
        except Exception as e:
            return f"[ERROR: {str(e)[:50]}]"

        if result.returncode != 0:
            return "[ERROR: git log failed]"

        lines = result.stdout.splitlines()
        if not lines:
            return "[ERROR: no commit history found]"

        return "\n".join(lines)

    async def get_related_issues(self, query_text: str) -> str:
        """Search for related issues in git log (not available in local mode for GitHub issues)."""
        if not query_text or not query_text.strip():
            return "[ERROR: empty query]"

        query_text = query_text.strip()

        # Search git log messages for the query
        args = ["git", "log", "--oneline", "--all", "--grep", query_text]

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.root_path,
            )
        except subprocess.TimeoutExpired:
            return "[ERROR: search timeout]"
        except Exception as e:
            return f"[ERROR: {str(e)[:50]}]"

        if result.returncode != 0:
            return f"[ERROR: no matching commits found for '{query_text}']"

        lines = result.stdout.splitlines()[:20]  # Limit to 20 results
        if not lines:
            return f"[ERROR: no matching commits found for '{query_text}']"

        return f"Found {len(lines)} matching commits:\n" + "\n".join(lines)

    async def close(self):
        """No-op for local tools (no HTTP client to close)."""
        pass

    def format_source(self, path: str, content: str | None = None, needle: str | None = None) -> str:
        """Format a source citation as local:path#Lx-Ly."""
        line_range = ""
        if content:
            line_range = find_line_range(content, needle)
        return f"local:{path}{line_range}"

