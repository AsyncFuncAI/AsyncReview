"""AtomGit PR ingestion for Part 2."""

import os
import re
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any

import httpx

from .config import CR_CACHE_DIR, ATOMGIT_TOKEN, ATOMGIT_API_BASE
from .diff_types import PRInfo, FileContents, DiffFileContext


import logging

logger = logging.getLogger(__name__)


def _parse_datetime(dt_str: str | None) -> datetime | None:
    """Parse ISO format datetime string."""
    if not dt_str:
        return None
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        return datetime.fromisoformat(dt_str.replace("+00:00", ""))
    except Exception:
        return None


_pr_cache: dict[str, PRInfo] = {}


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """Parse an AtomGit or GitCode PR URL into (owner, repo, number).

    Args:
        url: AtomGit/GitCode PR URL like https://atomgit.com/owner/repo/pulls/123
             or https://gitcode.com/owner/repo/pull/456

    Returns:
        Tuple of (owner, repo, pr_number)

    Raises:
        ValueError: If URL format is invalid
    """
    patterns = [
        r"atomgit\.com/([^/]+)/([^/]+)/pulls?/(\d+)",
        r"gitcode\.com/([^/]+)/([^/]+)/pulls?/(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), match.group(2), int(match.group(3))

    raise ValueError(f"Invalid AtomGit/GitCode PR URL: {url}")


def _get_headers() -> dict[str, str]:
    """Get HTTP headers for AtomGit API requests."""
    headers = {
        "Accept": "application/json",
        "User-Agent": "asyncreview-atomgit",
        "Content-Type": "application/json",
    }
    if ATOMGIT_TOKEN:
        headers["private-token"] = ATOMGIT_TOKEN
    return headers


async def load_pr(pr_url: str) -> PRInfo:
    """Load PR metadata from AtomGit.

    Args:
        pr_url: AtomGit PR URL

    Returns:
        PRInfo with metadata and file list
    """
    owner, repo, number = parse_pr_url(pr_url)
    review_id = str(uuid.uuid4())[:8]

    async with httpx.AsyncClient() as client:
        pr_resp = await client.get(
            f"{ATOMGIT_API_BASE}/api/v5/repos/{owner}/{repo}/pulls/{number}",
            headers=_get_headers(),
            timeout=30.0,
        )
        pr_resp.raise_for_status()
        pr_data = pr_resp.json()

        files_resp = await client.get(
            f"{ATOMGIT_API_BASE}/api/v5/repos/{owner}/{repo}/pulls/{number}/files",
            headers=_get_headers(),
            params={"per_page": 100},
            timeout=30.0,
        )
        files_resp.raise_for_status()
        files_data = files_resp.json()

        commits_resp = await client.get(
            f"{ATOMGIT_API_BASE}/api/v5/repos/{owner}/{repo}/pulls/{number}/commits",
            headers=_get_headers(),
            params={"per_page": 100},
            timeout=30.0,
        )
        commits_list = []
        if commits_resp.status_code == 200:
            commits_data = commits_resp.json()
            commits_list = [
                {
                    "sha": c["sha"][:7] if c.get("sha") else "",
                    "message": c.get("commit", {}).get("message", "").split("\n")[0],
                    "author": c.get("commit", {}).get("author", {}).get("name", ""),
                    "date": c.get("commit", {}).get("author", {}).get("date", ""),
                    "html_url": c.get("html_url", ""),
                }
                for c in commits_data
            ]

        comments_resp = await client.get(
            f"{ATOMGIT_API_BASE}/api/v5/repos/{owner}/{repo}/pulls/{number}/comments",
            headers=_get_headers(),
            params={"per_page": 100},
            timeout=30.0,
        )
        comments_list = []
        if comments_resp.status_code == 200:
            comments_data = comments_resp.json()
            comments_list = [
                {
                    "id": c.get("id"),
                    "user": {
                        "login": c.get("user", {}).get("login", ""),
                        "avatar_url": c.get("user", {}).get("avatar_url", ""),
                    },
                    "body": c.get("body", ""),
                    "created_at": c.get("created_at", ""),
                    "html_url": c.get("html_url", ""),
                }
                for c in comments_data
            ]

    files = _parse_files_data(files_data)

        if not pr_data.get("created_at"):
            created_at = datetime.now()
        else:
            parsed_dt = _parse_datetime(pr_data.get("created_at"))
            created_at = parsed_dt if parsed_dt else datetime.now()

        pr_info = PRInfo(
            review_id=review_id,
            owner=owner,
            repo=repo,
            number=number,
            title=pr_data.get("title", ""),
            body=pr_data.get("body") or "",
            base_sha=pr_data.get("base", {}).get("sha", ""),
            head_sha=pr_data.get("head", {}).get("sha", ""),
            files=files,
            created_at=created_at,
        user={
            "login": pr_data.get("user", {}).get("login", ""),
            "avatar_url": pr_data.get("user", {}).get("avatar_url", ""),
        },
        state=pr_data.get("state", "open"),
        draft=pr_data.get("draft", False),
        head_ref=pr_data.get("head", {}).get("ref", ""),
        base_ref=pr_data.get("base", {}).get("ref", ""),
        commits=pr_data.get("commits", 0),
        additions=pr_data.get("additions", 0),
        deletions=pr_data.get("deletions", 0),
        changed_files=pr_data.get("changed_files", 0),
        commits_list=commits_list,
        comments=comments_list,
    )

    _pr_cache[review_id] = pr_info

    return pr_info


def _parse_files_data(files_data: list[dict]) -> list[dict]:
    """Parse AtomGit files response into standard format."""
    files = []
    for f in files_data:
        patch_content = ""
        patch_obj = f.get("patch")
        if patch_obj:
            if isinstance(patch_obj, dict):
                patch_content = patch_obj.get("diff", "")
            elif isinstance(patch_obj, str):
                patch_content = patch_obj

        files.append(
            {
                "path": f.get("filename", ""),
                "status": f.get("status", "modified"),
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "patch": patch_content,
            }
        )
    return files


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

        try:
            encoded_path = path.replace("/", "%2F")
            base_resp = await client.get(
                f"{ATOMGIT_API_BASE}/api/v5/repos/{owner}/{repo}/contents/{encoded_path}",
                headers=_get_headers(),
                params={"ref": base_sha},
                timeout=30.0,
            )
            if base_resp.status_code == 200:
                data = base_resp.json()
                if data.get("content"):
                    import base64

                    content = base64.b64decode(data["content"]).decode("utf-8")
                    old_file = FileContents(
                        name=path,
                        contents=content,
                        cache_key=f"{owner}/{repo}/{base_sha}/{path}",
                    )
        except httpx.HTTPStatusError:
            pass
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug(f"Failed to fetch base file {path}: {e}")

        try:
            encoded_path = path.replace("/", "%2F")
            head_resp = await client.get(
                f"{ATOMGIT_API_BASE}/api/v5/repos/{owner}/{repo}/contents/{encoded_path}",
                headers=_get_headers(),
                params={"ref": head_sha},
                timeout=30.0,
            )
            if head_resp.status_code == 200:
                data = head_resp.json()
                if data.get("content"):
                    import base64

                    content = base64.b64decode(data["content"]).decode("utf-8")
                    new_file = FileContents(
                        name=path,
                        contents=content,
                        cache_key=f"{owner}/{repo}/{head_sha}/{path}",
                    )
        except httpx.HTTPStatusError:
            pass
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug(f"Failed to fetch head file {path}: {e}")

    return old_file, new_file


async def submit_pr_comment(pr_url: str, body: str) -> dict:
    """Submit a comment to an AtomGit PR.

    Args:
        pr_url: AtomGit PR URL
        body: Comment body (markdown supported)

    Returns:
        API response
    """
    owner, repo, number = parse_pr_url(pr_url)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ATOMGIT_API_BASE}/api/v5/repos/{owner}/{repo}/pulls/{number}/comments",
            headers=_get_headers(),
            json={"body": body},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()


async def submit_inline_comment(
    pr_url: str,
    body: str,
    path: str,
    position: int,
    commit_id: str | None = None,
) -> dict:
    """Submit an inline comment to an AtomGit PR.

    Args:
        pr_url: AtomGit PR URL
        body: Comment body
        path: File path
        position: Position in diff (1-indexed)
        commit_id: Commit SHA (optional)

    Returns:
        API response
    """
    owner, repo, number = parse_pr_url(pr_url)

    payload: dict[str, Any] = {
        "body": body,
        "path": path,
        "position": position,
    }
    if commit_id:
        payload["commit_id"] = commit_id

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ATOMGIT_API_BASE}/api/v5/repos/{owner}/{repo}/pulls/{number}/comments",
            headers=_get_headers(),
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()


def calculate_diff_position(patch: str, line_number: int, is_new_file: bool = False) -> int | None:
    """Calculate the position in diff for a given line number.

    AtomGit API uses position (diff line index) instead of line number.

    Args:
        patch: The diff patch content
        line_number: The line number in the new file
        is_new_file: Whether this is a newly added file

    Returns:
        Position in diff (1-indexed) or None if not found
    """
    if not patch:
        return None

    lines = patch.split("\n")
    position = 0
    current_new_line = 0

    in_hunk = False

    for i, line in enumerate(lines):
        hunk_match = re.match(r"^@@\s+-\d+,?\d*\s+\+(\d+),?\d*\s+@@", line)
        if hunk_match:
            in_hunk = True
            position = i + 1
            current_new_line = int(hunk_match.group(1)) - 1
            continue

        if not in_hunk:
            continue

        first_char = line[0] if line else ""

        if first_char == "+":
            current_new_line += 1
            if current_new_line == line_number:
                return position
        elif first_char == " ":
            current_new_line += 1
            if current_new_line == line_number:
                return position

        position += 1

    if is_new_file:
        return line_number

    return None
