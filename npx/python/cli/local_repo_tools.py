"""Local filesystem version of RepoTools for agentic code review.

Provides the same interface as RepoTools but reads from local filesystem
instead of GitHub API. Enables RLM to explore local files during review.
"""

import asyncio
import os
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
    
    async def close(self):
        """No-op for local tools (no HTTP client to close)."""
        pass
    
    def format_source(self, path: str, content: str | None = None, needle: str | None = None) -> str:
        """Format a source citation as local:path#Lx-Ly."""
        line_range = ""
        if content:
            line_range = find_line_range(content, needle)
        return f"local:{path}{line_range}"

