"""Repository exploration tools for agentic code review.

Provides tools that the RLM can use to fetch files, list directories,
and search code beyond the PR diff.
"""

import asyncio
import os
import re
from typing import Any

import httpx

from cr.config import GITHUB_TOKEN, GITHUB_API_BASE

# --- Configuration ---
MAX_FILE_BYTES = 200_000  # 200KB per file
MAX_CACHE_ENTRIES = 200
MAX_FALLBACK_LINES = 200
MAX_RETRIES = 2
BACKOFF_BASE = 1  # seconds

# --- State (per-run) ---
_file_cache: dict[tuple[str, str], str] = {}  # (ref, path) -> content
_semaphore = asyncio.Semaphore(5)  # Max 5 concurrent GitHub calls


def _get_headers() -> dict[str, str]:
    """Get HTTP headers for GitHub API requests."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "asyncreview-cli",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


# --- Path Sanitization ---

def sanitize_path(path: str) -> str | None:
    """Normalize and validate a file path.
    
    Returns None for invalid paths (caller returns error stub).
    """
    if not path or not path.strip():
        return None
    path = path.replace("\\", "/")
    normalized = os.path.normpath(path).lstrip("/")
    if normalized in (".", "..") or normalized.startswith("../"):
        return None
    return normalized


# --- Rate Limit Detection ---

def _parse_retry_after(resp: httpx.Response) -> int:
    """Safe Retry-After parsing with clamp."""
    try:
        val = int(resp.headers.get("Retry-After", 60))
        return min(max(val, 1), 600)  # Clamp 1-600s
    except (ValueError, TypeError):
        return 60


def _is_rate_limited(resp: httpx.Response) -> bool:
    """Check if response indicates rate limiting."""
    if resp.status_code == 429:
        return True
    if resp.status_code == 403:
        # Check header first
        if resp.headers.get("X-RateLimit-Remaining") == "0":
            return True
        # Then body
        body = resp.text.lower()
        if "rate limit" in body or "secondary rate limit" in body:
            return True
    return False


class RateLimitError(Exception):
    """Raised when rate limit is hit after retries."""
    pass


# --- GitHub Request with Concurrency + Backoff ---

async def _github_request(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """Make a GitHub API request with retries and backoff."""
    for attempt in range(MAX_RETRIES + 1):
        async with _semaphore:
            resp = await client.get(url, headers=_get_headers(), timeout=30.0)
        if not _is_rate_limited(resp):
            return resp
        if attempt < MAX_RETRIES:
            # Backoff OUTSIDE semaphore
            await asyncio.sleep(min(BACKOFF_BASE * (2 ** attempt), 10))
    # Still limited -> raise; caller returns stub
    raise RateLimitError()


# --- Cache ---

def _cache_get(ref: str, path: str) -> str | None:
    """Get cached file content."""
    return _file_cache.get((ref, path))


def _cache_set(ref: str, path: str, content: str):
    """Cache file content (only success, not error stubs)."""
    if content.startswith("[ERROR:") or content.startswith("[SKIPPED:"):
        return
    if len(_file_cache) >= MAX_CACHE_ENTRIES:
        # FIFO eviction
        _file_cache.pop(next(iter(_file_cache)))
    _file_cache[(ref, path)] = content


# --- Line Range Computation ---

def find_line_range(content: str, needle: str | None = None) -> str:
    """Find line range for a needle in content.
    
    Returns #Lx-Ly format. Falls back to first N lines if no match.
    """
    lines = content.splitlines()
    if needle:
        for i, line in enumerate(lines, 1):
            if needle in line:
                return f"#L{i}-L{min(i + 2, len(lines))}"
    # No match or no needle: cap at MAX_FALLBACK_LINES
    return f"#L1-L{min(len(lines), MAX_FALLBACK_LINES)}"


# --- Tool Implementations ---

class RepoTools:
    """Tools for exploring a GitHub repository beyond the PR diff."""
    
    def __init__(self, owner: str, repo: str, head_sha: str, pr_number: int | None = None):
        """Initialize with repo context.

        Args:
            owner: Repository owner
            repo: Repository name
            head_sha: PR head commit SHA for consistent reads
            pr_number: Optional PR number for PR-specific tools
        """
        self.owner = owner
        self.repo = repo
        self.head_sha = head_sha
        self.pr_number = pr_number
        self._client: httpx.AsyncClient | None = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client
    
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def fetch_file(self, path: str) -> str:
        """Fetch any file from the repo at the PR's head commit.
        
        Returns file content or error/skip stub.
        """
        clean_path = sanitize_path(path)
        if clean_path is None:
            return "[ERROR: invalid path]"
        
        # Check cache
        cached = _cache_get(self.head_sha, clean_path)
        if cached is not None:
            return cached
        
        client = await self._get_client()
        url = f"{GITHUB_API_BASE}/repos/{self.owner}/{self.repo}/contents/{clean_path}?ref={self.head_sha}"
        
        try:
            resp = await _github_request(client, url)
        except RateLimitError:
            return "[ERROR: 429/403 rate limited]"
        
        if resp.status_code == 404:
            return "[ERROR: 404 - not found or no access]"
        if resp.status_code == 403:
            return "[ERROR: 403 - access denied]"
        if resp.status_code != 200:
            return f"[ERROR: {resp.status_code}]"
        
        data = resp.json()
        
        # Check if it's a file (not directory)
        if data.get("type") != "file":
            return "[SKIPPED: path is a directory, use list_directory]"
        
        # Check size
        size = data.get("size", 0)
        if size > MAX_FILE_BYTES:
            return f"[SKIPPED: file exceeds {MAX_FILE_BYTES // 1000}KB limit ({size // 1000}KB)]"
        
        # Check encoding (binary detection)
        encoding = data.get("encoding", "")
        if encoding != "base64":
            return "[SKIPPED: binary/unsupported file]"
        
        # Decode content
        import base64
        try:
            content = base64.b64decode(data.get("content", "")).decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            return "[SKIPPED: binary/unsupported file]"
        
        _cache_set(self.head_sha, clean_path, content)
        return content
    
    async def list_directory(self, path: str = "") -> list[dict[str, Any]]:
        """List files and directories at a path.
        
        Returns structured entries: [{path, type, size}]
        """
        # Treat ".", "./", "/" same as "" (root directory)
        clean_path = sanitize_path(path) if path and path.strip() not in (".", "./", "/") else ""
        if clean_path is None:
            return [{"error": "invalid path"}]
        
        client = await self._get_client()
        url = f"{GITHUB_API_BASE}/repos/{self.owner}/{self.repo}/contents/{clean_path}?ref={self.head_sha}"
        
        try:
            resp = await _github_request(client, url)
        except RateLimitError:
            return [{"error": "rate limited"}]
        
        if resp.status_code != 200:
            return [{"error": f"status {resp.status_code}"}]
        
        data = resp.json()
        
        # Single file case
        if isinstance(data, dict):
            return [{
                "path": data.get("path", clean_path),
                "type": data.get("type", "file"),
                "size": data.get("size"),
            }]
        
        # Directory listing
        entries = []
        for item in data:
            # Use 0 instead of None for directory size to avoid JSON null -> Pyodide issues
            size = item.get("size") if item.get("type") == "file" else 0
            entries.append({
                "path": item.get("path", ""),
                "type": item.get("type", "file"),
                "size": size,
            })
        return entries
    
    async def search_code(self, query: str) -> list[dict[str, Any]]:
        """Search for code patterns in the repository.
        
        Supports:
        - Code content search: "enable_tool_optimization"
        - Filename search: "rlm.py" (auto-detects .py/.js/.ts etc)
        - Path search: "dspy/predict/" (ends with /)
        
        Returns paths + fragments. Use fetch_file for full context.
        Soft-fails on error (returns []).
        """
        if not query or not query.strip():
            return []
        
        query = query.strip()
        client = await self._get_client()
        
        # Detect if query is a filename (has extension) or path (ends with /)
        # and add appropriate GitHub search qualifiers
        file_extensions = ('.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java', '.md', '.json', '.yaml', '.yml')
        
        if query.endswith('/'):
            # Path/directory search
            search_query = f"path:{query[:-1]} repo:{self.owner}/{self.repo}"
        elif any(query.endswith(ext) for ext in file_extensions):
            # Filename search - use filename: qualifier
            search_query = f"filename:{query} repo:{self.owner}/{self.repo}"
        else:
            # Content search
            search_query = f"{query} repo:{self.owner}/{self.repo}"
        
        url = f"{GITHUB_API_BASE}/search/code"
        
        # Debug logging for bundled mode troubleshooting
        print(f"[DEBUG-SEARCH] Query: '{search_query}'")
        print(f"[DEBUG-SEARCH] URL: {url}")
        print(f"[DEBUG-SEARCH] GITHUB_TOKEN present: {bool(GITHUB_TOKEN)}")
        
        try:
            async with _semaphore:
                resp = await client.get(
                    url,
                    headers={
                        **_get_headers(),
                        "Accept": "application/vnd.github.text-match+json",
                    },
                    params={"q": search_query, "per_page": 10},
                    timeout=30.0,
                )
            print(f"[DEBUG-SEARCH] Response status: {resp.status_code}")
        except Exception as e:
            print(f"[DEBUG-SEARCH] Exception: {e}")
            return []  # Soft fail
        
        if _is_rate_limited(resp):
            print(f"[DEBUG-SEARCH] Rate limited!")
            return []
        if resp.status_code != 200:
            print(f"[DEBUG-SEARCH] Non-200 response: {resp.text[:500]}")
            return []  # Soft fail
        
        data = resp.json()
        results = []
        
        for item in data.get("items", []):
            entry = {"path": item.get("path", "")}
            # Extract fragment from text_matches if available
            text_matches = item.get("text_matches", [])
            if text_matches:
                fragments = [m.get("fragment", "") for m in text_matches if m.get("fragment")]
                if fragments:
                    entry["fragment"] = fragments[0][:500]  # Limit size
            results.append(entry)
        
        return results

    async def get_symbol_definition(self, symbol: str, context_file: str = "") -> str:
        """Search for a symbol definition (function or class).

        Uses GitHub code search to find 'def {symbol}' or 'class {symbol}' patterns.
        When context_file is provided, prioritizes results from that directory.
        Returns file path + content snippet or error stub.
        """
        if not symbol or not symbol.strip():
            return "[ERROR: empty symbol]"

        symbol = symbol.strip()
        client = await self._get_client()

        # Build search query with optional path qualifier
        base_query = f"(def {symbol}|class {symbol}) repo:{self.owner}/{self.repo}"

        # If context_file is provided, extract directory and try scoped search first
        context_dir = ""
        if context_file and context_file.strip():
            context_dir = os.path.dirname(context_file).strip()

        # Try with path qualifier if context_dir is available
        if context_dir:
            search_query = f"{base_query} path:{context_dir}"
        else:
            search_query = base_query

        url = f"{GITHUB_API_BASE}/search/code"

        try:
            async with _semaphore:
                resp = await client.get(
                    url,
                    headers={
                        **_get_headers(),
                        "Accept": "application/vnd.github.text-match+json",
                    },
                    params={"q": search_query, "per_page": 5},
                    timeout=30.0,
                )
        except Exception:
            return "[ERROR: search failed]"

        if _is_rate_limited(resp):
            return "[ERROR: rate limited]"
        if resp.status_code != 200:
            return f"[ERROR: {resp.status_code}]"

        data = resp.json()
        items = data.get("items", [])

        # If no results with path qualifier, fall back to repo-wide search
        if not items and context_dir:
            try:
                async with _semaphore:
                    resp = await client.get(
                        url,
                        headers={
                            **_get_headers(),
                            "Accept": "application/vnd.github.text-match+json",
                        },
                        params={"q": base_query, "per_page": 5},
                        timeout=30.0,
                    )
            except Exception:
                return "[ERROR: search failed]"

            if not _is_rate_limited(resp) and resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])

        if not items:
            return f"[ERROR: symbol '{symbol}' not found]"

        # Return first match with path and fragment
        item = items[0]
        path = item.get("path", "")
        fragment = ""
        text_matches = item.get("text_matches", [])
        if text_matches:
            fragment = text_matches[0].get("fragment", "")[:500]

        result = f"Found in: {path}\n"
        if fragment:
            result += f"Definition:\n{fragment}"
        return result

    async def find_usages(self, symbol: str, scope_path: str = ".") -> str:
        """Search for usages of a symbol in the repository.

        When scope_path is provided and not ".", narrows search to that path.
        Returns list of files + fragments where symbol is referenced.
        """
        if not symbol or not symbol.strip():
            return "[ERROR: empty symbol]"

        symbol = symbol.strip()
        client = await self._get_client()

        # Build search query with optional path qualifier
        search_query = f"{symbol} repo:{self.owner}/{self.repo}"

        # Add path qualifier if scope_path is provided and not "."
        if scope_path and scope_path.strip() and scope_path.strip() != ".":
            search_query = f"{search_query} path:{scope_path.strip()}"

        url = f"{GITHUB_API_BASE}/search/code"

        try:
            async with _semaphore:
                resp = await client.get(
                    url,
                    headers={
                        **_get_headers(),
                        "Accept": "application/vnd.github.text-match+json",
                    },
                    params={"q": search_query, "per_page": 10},
                    timeout=30.0,
                )
        except Exception:
            return "[ERROR: search failed]"

        if _is_rate_limited(resp):
            return "[ERROR: rate limited]"
        if resp.status_code != 200:
            return f"[ERROR: {resp.status_code}]"

        data = resp.json()
        items = data.get("items", [])

        if not items:
            return f"[ERROR: no usages of '{symbol}' found]"

        # Format results
        result = f"Found {len(items)} usages of '{symbol}':\n"
        for item in items[:10]:
            path = item.get("path", "")
            result += f"  - {path}\n"

        return result

    async def get_type_hierarchy(self, class_name: str) -> str:
        """Get the type hierarchy (parent classes) for a class.

        Searches for the class definition, parses parent classes using regex,
        and recursively resolves parent classes.
        """
        if not class_name or not class_name.strip():
            return "[ERROR: empty class name]"

        class_name = class_name.strip()
        client = await self._get_client()

        # Search for class definition
        search_query = f"class {class_name} repo:{self.owner}/{self.repo}"
        url = f"{GITHUB_API_BASE}/search/code"

        try:
            async with _semaphore:
                resp = await client.get(
                    url,
                    headers={
                        **_get_headers(),
                        "Accept": "application/vnd.github.text-match+json",
                    },
                    params={"q": search_query, "per_page": 5},
                    timeout=30.0,
                )
        except Exception:
            return "[ERROR: search failed]"

        if _is_rate_limited(resp):
            return "[ERROR: rate limited]"
        if resp.status_code != 200:
            return f"[ERROR: {resp.status_code}]"

        data = resp.json()
        items = data.get("items", [])

        if not items:
            return f"[ERROR: class '{class_name}' not found]"

        # Fetch the file containing the class
        path = items[0].get("path", "")
        file_content = await self.fetch_file(path)

        if file_content.startswith("[ERROR:") or file_content.startswith("[SKIPPED:"):
            return f"[ERROR: could not fetch {path}]"

        # Parse parent classes using regex: class ClassName(Parent1, Parent2):
        # Use re.DOTALL to handle multi-line class definitions
        pattern = rf"class\s+{re.escape(class_name)}\s*\(([^)]+)\)"
        match = re.search(pattern, file_content, re.DOTALL)

        if not match:
            return f"Class '{class_name}' has no parent classes (or is not found)"

        parents_str = match.group(1)
        # Strip whitespace and newlines from each parent, filter out empty strings
        parents = [p.strip() for p in parents_str.split(",") if p.strip()]

        result = f"Type hierarchy for '{class_name}':\n"
        result += f"  {class_name} extends: {', '.join(parents)}\n"

        # Resolve one level of parent classes
        result += "  Parent details:\n"
        for parent in parents:
            parent_hierarchy = await self._resolve_parent_class(parent)
            if parent_hierarchy:
                result += f"    {parent_hierarchy}\n"
            else:
                result += f"    {parent} (no parents found)\n"

        return result

    async def _resolve_parent_class(self, parent_name: str) -> str | None:
        """Resolve one level of parent class hierarchy.

        Searches for the parent class definition and extracts its parents.
        Returns a string like "ParentClass extends: GrandParent" or None if not found.
        """
        if not parent_name or not parent_name.strip():
            return None

        parent_name = parent_name.strip()
        client = await self._get_client()

        # Search for parent class definition
        search_query = f"class {parent_name} repo:{self.owner}/{self.repo}"
        url = f"{GITHUB_API_BASE}/search/code"

        try:
            async with _semaphore:
                resp = await client.get(
                    url,
                    headers={
                        **_get_headers(),
                        "Accept": "application/vnd.github.text-match+json",
                    },
                    params={"q": search_query, "per_page": 5},
                    timeout=30.0,
                )
        except Exception:
            return None

        if _is_rate_limited(resp) or resp.status_code != 200:
            return None

        data = resp.json()
        items = data.get("items", [])

        if not items:
            return None

        # Fetch the file containing the parent class
        path = items[0].get("path", "")
        file_content = await self.fetch_file(path)

        if file_content.startswith("[ERROR:") or file_content.startswith("[SKIPPED:"):
            return None

        # Parse parent classes of the parent class
        pattern = rf"class\s+{re.escape(parent_name)}\s*\(([^)]+)\)"
        match = re.search(pattern, file_content, re.DOTALL)

        if not match:
            return None

        parents_str = match.group(1)
        grandparents = [p.strip() for p in parents_str.split(",") if p.strip()]

        return f"{parent_name} extends: {', '.join(grandparents)}"

    async def get_call_graph(self, func_name: str, depth: int = 1) -> str:
        """Get the call graph for a function.

        Searches for calls to func_name, and if depth > 0, searches for what
        func_name calls by fetching its definition.
        """
        if not func_name or not func_name.strip():
            return "[ERROR: empty function name]"

        func_name = func_name.strip()
        client = await self._get_client()

        # Search for calls to the function
        search_query = f"{func_name}( repo:{self.owner}/{self.repo}"
        url = f"{GITHUB_API_BASE}/search/code"

        try:
            async with _semaphore:
                resp = await client.get(
                    url,
                    headers={
                        **_get_headers(),
                        "Accept": "application/vnd.github.text-match+json",
                    },
                    params={"q": search_query, "per_page": 10},
                    timeout=30.0,
                )
        except Exception:
            return "[ERROR: search failed]"

        if _is_rate_limited(resp):
            return "[ERROR: rate limited]"
        if resp.status_code != 200:
            return f"[ERROR: {resp.status_code}]"

        data = resp.json()
        items = data.get("items", [])

        result = f"Call graph for '{func_name}':\n"

        if not items:
            result += f"  No calls found\n"
        else:
            # List files that call this function
            result += f"  Called in {len(items)} locations:\n"
            for item in items[:10]:
                path = item.get("path", "")
                result += f"    - {path}\n"

        # If depth >= 1, find outgoing calls from this function
        if depth >= 1:
            outgoing = await self._get_outgoing_calls(func_name)
            if outgoing:
                result += f"\n  Calls (outgoing):\n"
                for call in outgoing:
                    result += f"    - {call}\n"
            else:
                result += f"\n  Calls (outgoing): none found\n"

        return result

    async def _get_outgoing_calls(self, func_name: str) -> list[str]:
        """Extract outgoing calls from a function definition.

        Returns list of function names called by func_name.
        """
        # Python keywords to filter out
        keywords = {
            "if", "for", "while", "return", "print", "range", "len", "str",
            "int", "list", "dict", "set", "tuple", "type", "isinstance",
            "hasattr", "getattr", "setattr", "super", "enumerate", "zip",
            "map", "filter", "sorted", "reversed", "any", "all", "min",
            "max", "sum", "abs", "round", "open", "format", "repr", "hash",
            "id", "input", "next", "iter"
        }

        # Search for function definition
        search_query = f"def {func_name} repo:{self.owner}/{self.repo}"
        url = f"{GITHUB_API_BASE}/search/code"

        client = await self._get_client()

        try:
            async with _semaphore:
                resp = await client.get(
                    url,
                    headers={
                        **_get_headers(),
                        "Accept": "application/vnd.github.text-match+json",
                    },
                    params={"q": search_query, "per_page": 5},
                    timeout=30.0,
                )
        except Exception:
            return []

        if _is_rate_limited(resp) or resp.status_code != 200:
            return []

        data = resp.json()
        items = data.get("items", [])

        if not items:
            return []

        # Fetch the file containing the function
        path = items[0].get("path", "")
        file_content = await self.fetch_file(path)

        if file_content.startswith("[ERROR:") or file_content.startswith("[SKIPPED:"):
            return []

        # Extract function body
        func_body = self._extract_function_body(file_content, func_name)
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

    async def get_pr_comments(self, pr_number: int | None = None) -> str:
        """Get all comments and reviews from a PR.

        Uses /repos/{owner}/{repo}/pulls/{pr_number}/reviews and /comments endpoints.
        """
        pr_num = pr_number or self.pr_number
        if not pr_num:
            return "[ERROR: no PR number provided]"

        client = await self._get_client()

        # Fetch reviews
        reviews_url = f"{GITHUB_API_BASE}/repos/{self.owner}/{self.repo}/pulls/{pr_num}/reviews"
        comments_url = f"{GITHUB_API_BASE}/repos/{self.owner}/{self.repo}/pulls/{pr_num}/comments"

        result = f"PR #{pr_num} Comments and Reviews:\n"

        try:
            async with _semaphore:
                reviews_resp = await client.get(reviews_url, headers=_get_headers(), timeout=30.0)
                comments_resp = await client.get(comments_url, headers=_get_headers(), timeout=30.0)
        except Exception:
            return "[ERROR: failed to fetch PR comments]"

        if reviews_resp.status_code == 200:
            reviews = reviews_resp.json()
            result += f"\nReviews ({len(reviews)}):\n"
            for review in reviews[:10]:
                author = review.get("user", {}).get("login", "unknown")
                state = review.get("state", "UNKNOWN")
                body = review.get("body", "")[:200]
                result += f"  - {author} ({state}): {body}\n"

        if comments_resp.status_code == 200:
            comments = comments_resp.json()
            result += f"\nComments ({len(comments)}):\n"
            for comment in comments[:10]:
                author = comment.get("user", {}).get("login", "unknown")
                body = comment.get("body", "")[:200]
                result += f"  - {author}: {body}\n"

        return result

    def _parse_line_range(self, line_range: str) -> tuple[int, int] | None:
        """Parse line range from "10-20" or "10,20" format.

        Returns (start, end) tuple or None if parsing fails.
        """
        if not line_range or not line_range.strip():
            return None

        line_range = line_range.strip()

        # Try "10-20" format
        if "-" in line_range:
            parts = line_range.split("-")
            if len(parts) == 2:
                try:
                    start = int(parts[0].strip())
                    end = int(parts[1].strip())
                    if start > 0 and end > 0 and start <= end:
                        return (start, end)
                except ValueError:
                    pass

        # Try "10,20" format
        if "," in line_range:
            parts = line_range.split(",")
            if len(parts) == 2:
                try:
                    start = int(parts[0].strip())
                    end = int(parts[1].strip())
                    if start > 0 and end > 0 and start <= end:
                        return (start, end)
                except ValueError:
                    pass

        return None

    def _patch_touches_lines(self, patch: str, start_line: int, end_line: int) -> bool:
        """Check if a unified diff patch touches the given line range.

        Parses @@ -start,count +start,count @@ headers to determine
        if the patch modifies lines in the requested range.
        """
        if not patch:
            return False

        # Find all hunk headers: @@ -start,count +start,count @@
        # The second number is the line range in the new file
        hunk_pattern = r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@"

        for match in re.finditer(hunk_pattern, patch):
            hunk_start = int(match.group(1))
            hunk_count = int(match.group(2)) if match.group(2) else 1
            hunk_end = hunk_start + hunk_count - 1

            # Check if this hunk overlaps with the requested range
            if hunk_start <= end_line and hunk_end >= start_line:
                return True

        return False

    async def get_blame(self, path: str, line_range: str = "") -> str:
        """Get blame information for a file or line range.

        Parses line_range like "10-20" or "10,20" and returns commit info
        for commits that touched those lines. If line_range is empty,
        returns recent commits for the entire file.
        """
        clean_path = sanitize_path(path)
        if clean_path is None:
            return "[ERROR: invalid path]"

        client = await self._get_client()

        # GitHub doesn't have a direct blame API, so we fetch commits for the file
        url = f"{GITHUB_API_BASE}/repos/{self.owner}/{self.repo}/commits"

        try:
            async with _semaphore:
                resp = await client.get(
                    url,
                    headers=_get_headers(),
                    params={"path": clean_path, "per_page": 10},
                    timeout=30.0,
                )
        except Exception:
            return "[ERROR: blame fetch failed]"

        if _is_rate_limited(resp):
            return "[ERROR: rate limited]"
        if resp.status_code != 200:
            return f"[ERROR: {resp.status_code}]"

        commits = resp.json()

        # If no line_range specified, return all recent commits
        if not line_range or not line_range.strip():
            result = f"Blame for {clean_path} (recent commits):\n"
            for commit in commits[:10]:
                sha = commit.get("sha", "")[:7]
                author = commit.get("commit", {}).get("author", {}).get("name", "unknown")
                message = commit.get("commit", {}).get("message", "")[:100]
                result += f"  {sha} - {author}: {message}\n"
            return result

        # Parse line_range
        parsed_range = self._parse_line_range(line_range)
        if parsed_range is None:
            # Parsing failed - fall back to all commits with a note
            result = f"Blame for {clean_path} (invalid line range '{line_range}', showing recent commits):\n"
            for commit in commits[:10]:
                sha = commit.get("sha", "")[:7]
                author = commit.get("commit", {}).get("author", {}).get("name", "unknown")
                message = commit.get("commit", {}).get("message", "")[:100]
                result += f"  {sha} - {author}: {message}\n"
            return result

        start_line, end_line = parsed_range

        # Filter commits to those that touched the requested line range
        matching_commits = []
        for commit in commits[:10]:
            sha = commit.get("sha", "")

            # Fetch commit details to get the patch
            commit_url = f"{GITHUB_API_BASE}/repos/{self.owner}/{self.repo}/commits/{sha}"
            try:
                async with _semaphore:
                    commit_resp = await client.get(
                        commit_url,
                        headers=_get_headers(),
                        timeout=30.0,
                    )
            except Exception:
                # If we can't fetch commit details, skip it
                continue

            if _is_rate_limited(commit_resp):
                # Rate limited - return what we have so far
                break
            if commit_resp.status_code != 200:
                # Skip this commit
                continue

            commit_data = commit_resp.json()
            files = commit_data.get("files", [])

            # Check if any file in this commit touches our line range
            for file_info in files:
                if file_info.get("filename") == clean_path:
                    patch = file_info.get("patch", "")
                    if self._patch_touches_lines(patch, start_line, end_line):
                        matching_commits.append(commit)
                    break

        # Format result
        result = f"Blame for {clean_path} (lines {line_range}):\n"

        if not matching_commits:
            result += f"  No commits found that touched lines {line_range}\n"
        else:
            for commit in matching_commits:
                sha = commit.get("sha", "")[:7]
                author = commit.get("commit", {}).get("author", {}).get("name", "unknown")
                message = commit.get("commit", {}).get("message", "")[:100]
                result += f"  {sha} - {author}: {message}\n"

        return result

    async def get_commit_history(self, path: str, limit: int = 5) -> str:
        """Get commit history for a file.

        Uses /repos/{owner}/{repo}/commits?path={path}&per_page={limit} endpoint.
        """
        clean_path = sanitize_path(path)
        if clean_path is None:
            return "[ERROR: invalid path]"

        client = await self._get_client()
        url = f"{GITHUB_API_BASE}/repos/{self.owner}/{self.repo}/commits"

        try:
            async with _semaphore:
                resp = await client.get(
                    url,
                    headers=_get_headers(),
                    params={"path": clean_path, "per_page": min(limit, 100)},
                    timeout=30.0,
                )
        except Exception:
            return "[ERROR: commit history fetch failed]"

        if _is_rate_limited(resp):
            return "[ERROR: rate limited]"
        if resp.status_code != 200:
            return f"[ERROR: {resp.status_code}]"

        commits = resp.json()

        result = f"Commit history for {clean_path} (last {len(commits)} commits):\n"
        for commit in commits[:limit]:
            sha = commit.get("sha", "")[:7]
            author = commit.get("commit", {}).get("author", {}).get("name", "unknown")
            date = commit.get("commit", {}).get("author", {}).get("date", "")[:10]
            message = commit.get("commit", {}).get("message", "").split("\n")[0][:80]
            result += f"  {sha} ({date}) - {author}: {message}\n"

        return result

    async def get_related_issues(self, query_text: str) -> str:
        """Search for related issues in the repository.

        Uses /search/issues?q={query_text}+repo:{owner}/{repo} endpoint.
        """
        if not query_text or not query_text.strip():
            return "[ERROR: empty query]"

        query_text = query_text.strip()
        client = await self._get_client()

        search_query = f"{query_text} repo:{self.owner}/{self.repo}"
        url = f"{GITHUB_API_BASE}/search/issues"

        try:
            async with _semaphore:
                resp = await client.get(
                    url,
                    headers=_get_headers(),
                    params={"q": search_query, "per_page": 10},
                    timeout=30.0,
                )
        except Exception:
            return "[ERROR: issue search failed]"

        if _is_rate_limited(resp):
            return "[ERROR: rate limited]"
        if resp.status_code != 200:
            return f"[ERROR: {resp.status_code}]"

        data = resp.json()
        items = data.get("items", [])

        if not items:
            return f"[ERROR: no issues found for '{query_text}']"

        result = f"Related issues for '{query_text}' ({len(items)} found):\n"
        for item in items[:10]:
            number = item.get("number", "")
            title = item.get("title", "")[:80]
            state = item.get("state", "")
            result += f"  #{number} [{state}] {title}\n"

        return result

    def format_source(self, path: str, content: str | None = None, needle: str | None = None) -> str:
        """Format a source citation as repo@sha:path#Lx-Ly."""
        line_range = ""
        if content:
            line_range = find_line_range(content, needle)
        return f"{self.owner}/{self.repo}@{self.head_sha[:7]}:{path}{line_range}"


# --- Tool Descriptions for RLM Prompt ---

TOOL_DESCRIPTIONS = """
AVAILABLE TOOLS (use via Python in REPL):

BASIC TOOLS:
- fetch_file(path: str) -> str: Fetch any file from the repo. Returns content or error stub.
- list_directory(path: str = "") -> list[dict]: List {path, type, size} entries.
- search_code(query: str) -> list[dict]: Search for patterns. Returns {path, fragment}.

DEEP CODE UNDERSTANDING:
- get_symbol_definition(symbol: str, context_file: str = "") -> str: Find function/class definition.
- find_usages(symbol: str, scope_path: str = ".") -> str: Find all usages of a symbol.
- get_type_hierarchy(class_name: str) -> str: Get parent classes for a class.
- get_call_graph(func_name: str, depth: int = 1) -> str: Get functions that call func_name.

GITHUB CONTEXT:
- get_pr_comments(pr_number: int | None = None) -> str: Get PR reviews and comments.
- get_blame(path: str, line_range: str = "") -> str: Get blame info for a file/lines.
- get_commit_history(path: str, limit: int = 5) -> str: Get commit history for a file.
- get_related_issues(query_text: str) -> str: Search for related issues.

TOOL USAGE RULES:
1. Fetch the minimum: prefer 1–3 files; don't traverse the repo.
2. If analysis depends on unchanged code, use fetch_file.
3. Use search_code to find paths; then fetch_file to read.
4. Files > 200KB return a stub—avoid large/generated files.
5. Use list_directory to understand structure first.
6. Use get_symbol_definition to find where a symbol is defined.
7. Use find_usages to understand impact of changes.
8. Use get_type_hierarchy to understand class relationships.
9. Use get_call_graph to trace function dependencies.
10. Use get_pr_comments to understand review feedback.
11. Use get_blame to find who changed what and when.
12. Use get_commit_history to understand evolution of a file.
13. Use get_related_issues to find context about bugs/features.
"""
