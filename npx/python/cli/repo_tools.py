"""Repository exploration tools for agentic code review.

Provides tools that the RLM can use to fetch files, list directories,
and search code beyond the PR diff.
"""

import asyncio
import os
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
    
    def __init__(self, owner: str, repo: str, head_sha: str):
        """Initialize with repo context.
        
        Args:
            owner: Repository owner
            repo: Repository name
            head_sha: PR head commit SHA for consistent reads
        """
        self.owner = owner
        self.repo = repo
        self.head_sha = head_sha
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
        clean_path = sanitize_path(path) if path else ""
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
            entries.append({
                "path": item.get("path", ""),
                "type": item.get("type", "file"),
                "size": item.get("size") if item.get("type") == "file" else None,
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
            return []  # Soft fail
        
        if _is_rate_limited(resp) or resp.status_code != 200:
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
    
    def format_source(self, path: str, content: str | None = None, needle: str | None = None) -> str:
        """Format a source citation as repo@sha:path#Lx-Ly."""
        line_range = ""
        if content:
            line_range = find_line_range(content, needle)
        return f"{self.owner}/{self.repo}@{self.head_sha[:7]}:{path}{line_range}"


# --- Tool Descriptions for RLM Prompt ---

TOOL_DESCRIPTIONS = """
AVAILABLE TOOLS (use via Python in REPL):
- fetch_file(path: str) -> str: Fetch any file from the repo. Returns content or error stub.
- list_directory(path: str = "") -> list[dict]: List {path, type, size} entries.
- search_code(query: str) -> list[dict]: Search for patterns. Returns {path, fragment}.

TOOL USAGE RULES:
1. Fetch the minimum: prefer 1–3 files; don't traverse the repo.
2. If analysis depends on unchanged code, use fetch_file.
3. Use search_code to find paths; then fetch_file to read.
4. Files > 200KB return a stub—avoid large/generated files.
5. Use list_directory to understand structure first.
"""
