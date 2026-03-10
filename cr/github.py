"""GitHub PR ingestion for Part 2."""

import os
import re
import subprocess
import uuid
from pathlib import Path
from datetime import datetime

import httpx

from .config import CR_CACHE_DIR, GITHUB_TOKEN, GITHUB_API_BASE
from .diff_types import PRInfo, FileContents, DiffFileContext


def _get_login(user: dict) -> str:
    """Get user login, falling back to username (Gitea compat)."""
    return user.get("login") or user.get("username") or "unknown"


# In-memory store for loaded PRs (MVP - no persistence)
_pr_cache: dict[str, PRInfo] = {}


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """Parse a PR/MR URL into (owner, repo, number).
    
    Supports GitHub, Gitea, GitLab, and Bitbucket URL formats.
    
    Args:
        url: PR/MR URL (e.g. /pull/1, /pulls/1, /-/merge_requests/1, /pull-requests/1)
        
    Returns:
        Tuple of (owner, repo, pr_number)
        
    Raises:
        ValueError: If URL format is invalid
    """
    # GitHub /pull/, Gitea /pulls/, GitLab /-/merge_requests/, Bitbucket /pull-requests/
    pattern = r"^https?://[^/]+/([^/]+)/([^/]+)/(?:-/)?(?:pulls?|merge_requests|pull-requests)/(\d+)(?:[/?#].*)?$"
    match = re.search(pattern, url)
    if not match:
        raise ValueError(
            f"Invalid PR URL: {url}\n"
            "Expected: https://host/owner/repo/{pull,pulls,merge_requests,pull-requests}/123"
        )
    return match.group(1), match.group(2), int(match.group(3))


def _get_headers() -> dict[str, str]:
    """Get HTTP headers for GitHub API requests."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "cr-review-tool",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


async def load_pr(pr_url: str) -> PRInfo:
    """Load PR metadata from GitHub.
    
    Args:
        pr_url: GitHub PR URL
        
    Returns:
        PRInfo with metadata and file list
    """
    owner, repo, number = parse_pr_url(pr_url)
    review_id = str(uuid.uuid4())[:8]
    
    async with httpx.AsyncClient() as client:
        # Fetch PR metadata
        pr_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}",
            headers=_get_headers(),
            timeout=30.0,
        )
        pr_resp.raise_for_status()
        pr_data = pr_resp.json()
        
        # Fetch changed files
        files_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}/files",
            headers=_get_headers(),
            params={"per_page": 100},
            timeout=30.0,
        )
        files_resp.raise_for_status()
        files_data = files_resp.json()
    
        # Fetch commits
        commits_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}/commits",
            headers=_get_headers(),
            params={"per_page": 100},
            timeout=30.0,
        )
        commits_list = []
        if commits_resp.status_code == 200:
            commits_data = commits_resp.json()
            commits_list = [
                {
                    "sha": c["sha"],
                    "message": c["commit"]["message"],
                    "author": {
                        "name": c["commit"]["author"]["name"],
                        "date": c["commit"]["author"]["date"],
                        "login": _get_login(c["author"]) if c.get("author") else None,
                        "avatar_url": c["author"].get("avatar_url", "") if c.get("author") else None,
                    },
                    "html_url": c.get("html_url", ""),
                }
                for c in commits_data
            ]

        # Fetch comments (using issue comments for main conversation)
        comments_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{number}/comments",
            headers=_get_headers(),
            params={"per_page": 100},
            timeout=30.0,
        )
        comments_list = []
        if comments_resp.status_code == 200:
             comments_data = comments_resp.json()
             comments_list = [
                 {
                     "id": c["id"],
                     "user": {
                         "login": _get_login(c["user"]),
                         "avatar_url": c["user"].get("avatar_url", ""),
                     },
                     "body": c["body"],
                     "created_at": c["created_at"],
                     "html_url": c.get("html_url", ""),
                 }
                 for c in comments_data
             ]

    files = [
        {
             "path": f["filename"],
             "status": f.get("status", "modified"),
             "additions": f.get("additions", 0),
             "deletions": f.get("deletions", 0),
             "patch": f.get("patch"),
        }
        for f in files_data
    ]
    
    pr_info = PRInfo(
        review_id=review_id,
        owner=owner,
        repo=repo,
        number=number,
        title=pr_data.get("title", ""),
        body=pr_data.get("body") or "",
        base_sha=pr_data.get("base", {}).get("sha", "HEAD"),
        head_sha=pr_data.get("head", {}).get("sha", "HEAD"),
        files=files,
        created_at=datetime.now(),
        user={"login": _get_login(pr_data["user"]), "avatar_url": pr_data["user"].get("avatar_url", "")},
        state=pr_data.get("state", "open"),
        draft=pr_data.get("draft", False),
        head_ref=pr_data.get("head", {}).get("ref", "unknown"),
        base_ref=pr_data.get("base", {}).get("ref", "main"),
        commits=pr_data.get("commits", 0),
        additions=pr_data.get("additions", 0),
        deletions=pr_data.get("deletions", 0),
        changed_files=pr_data.get("changed_files", 0),
        commits_list=commits_list,
        comments=comments_list,
    )
    
    # Cache for later file fetching
    _pr_cache[review_id] = pr_info
    
    return pr_info


def get_cached_pr(review_id: str) -> PRInfo | None:
    """Get a cached PR by review ID."""
    return _pr_cache.get(review_id)


async def get_file_contents(
    review_id: str,
    path: str,
) -> tuple[FileContents | None, FileContents | None]:
    """Get old and new file contents for a file in a PR.
    
    Args:
        review_id: The review ID from load_pr
        path: File path within the repo
        
    Returns:
        Tuple of (old_file, new_file) - either can be None for added/deleted files
    """
    pr_info = _pr_cache.get(review_id)
    if not pr_info:
        raise ValueError(f"Review {review_id} not found")
    
    owner, repo = pr_info.owner, pr_info.repo
    base_sha, head_sha = pr_info.base_sha, pr_info.head_sha
    
    async with httpx.AsyncClient() as client:
        old_file = None
        new_file = None
        
        # Fetch base version
        try:
            base_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
                headers={**_get_headers(), "Accept": "application/vnd.github.v3.raw"},
                params={"ref": base_sha},
                timeout=30.0,
            )
            if base_resp.status_code == 200:
                old_file = FileContents(
                    name=path,
                    contents=base_resp.text,
                    cache_key=f"{owner}/{repo}/{base_sha}/{path}",
                )
        except httpx.HTTPStatusError:
            pass  # File doesn't exist in base (new file)
        
        # Fetch head version
        try:
            head_resp = await client.get(
                f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
                headers={**_get_headers(), "Accept": "application/vnd.github.v3.raw"},
                params={"ref": head_sha},
                timeout=30.0,
            )
            if head_resp.status_code == 200:
                new_file = FileContents(
                    name=path,
                    contents=head_resp.text,
                    cache_key=f"{owner}/{repo}/{head_sha}/{path}",
                )
        except httpx.HTTPStatusError:
            pass  # File doesn't exist in head (deleted file)
    
    return old_file, new_file

