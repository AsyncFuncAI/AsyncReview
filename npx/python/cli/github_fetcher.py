"""GitHub URL parsing and content fetching for PR code review."""

import re
from typing import Literal

import httpx

# Import config from cr package
from cr.config import GITHUB_TOKEN, GITHUB_API_BASE


UrlType = Literal["pr", "issue"]


def parse_github_url(url: str) -> tuple[str, str, int, UrlType]:
    """Parse a GitHub URL into (owner, repo, number, type).
    
    Args:
        url: GitHub Issue or PR URL
        
    Returns:
        Tuple of (owner, repo, number, type)
        
    Raises:
        ValueError: If URL format is invalid
        
    Examples:
        >>> parse_github_url("https://github.com/vercel-labs/json-render/pull/35")
        ('vercel-labs', 'json-render', 35, 'pr')
        >>> parse_github_url("https://github.com/AsyncFuncAI/AsyncReview/issues/1")
        ('AsyncFuncAI', 'AsyncReview', 1, 'issue')
    """
    # Try PR URL first (primary use case)
    pr_pattern = r"github\.com/([^/]+)/([^/]+)/pull/(\d+)"
    pr_match = re.search(pr_pattern, url)
    if pr_match:
        return pr_match.group(1), pr_match.group(2), int(pr_match.group(3)), "pr"
    
    # Try Issue URL
    issue_pattern = r"github\.com/([^/]+)/([^/]+)/issues/(\d+)"
    issue_match = re.search(issue_pattern, url)
    if issue_match:
        return issue_match.group(1), issue_match.group(2), int(issue_match.group(3)), "issue"
    
    raise ValueError(
        f"Invalid GitHub URL: {url}\n"
        "Expected format: https://github.com/owner/repo/pull/123 or .../issues/123"
    )


def _get_headers() -> dict[str, str]:
    """Get HTTP headers for GitHub API requests."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "asyncreview-cli",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


async def fetch_pr(owner: str, repo: str, number: int) -> dict:
    """Fetch PR with full code review context.
    
    Returns dict with:
        - metadata: title, body, author, state, etc.
        - files: list of changed files with patches
        - commits: commit history
        - comments: PR discussion comments
    """
    async with httpx.AsyncClient() as client:
        # Fetch PR metadata
        pr_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{number}",
            headers=_get_headers(),
            timeout=30.0,
        )
        pr_resp.raise_for_status()
        pr_data = pr_resp.json()
        
        # Fetch changed files with patches
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
                    "sha": c["sha"][:7],
                    "message": c["commit"]["message"].split("\n")[0],  # First line only
                    "author": c["commit"]["author"]["name"],
                }
                for c in commits_data
            ]
        
        # Fetch PR comments
        comments_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{number}/comments",
            headers=_get_headers(),
            params={"per_page": 50},
            timeout=30.0,
        )
        comments_list = []
        if comments_resp.status_code == 200:
            comments_data = comments_resp.json()
            comments_list = [
                {
                    "author": c["user"]["login"],
                    "body": c["body"],
                }
                for c in comments_data
            ]
    
    # Build structured result
    files = [
        {
            "path": f["filename"],
            "status": f.get("status", "modified"),
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
            "patch": f.get("patch", ""),
        }
        for f in files_data
    ]
    
    return {
        "type": "pr",
        "owner": owner,
        "repo": repo,
        "number": number,
        "title": pr_data.get("title", ""),
        "body": pr_data.get("body") or "",
        "author": pr_data["user"]["login"],
        "state": pr_data.get("state", "open"),
        "base_branch": pr_data["base"]["ref"],
        "head_branch": pr_data["head"]["ref"],
        "head_sha": pr_data["head"]["sha"],  # For consistent file reads
        "files": files,
        "commits": commits_list,
        "comments": comments_list,
        "additions": pr_data.get("additions", 0),
        "deletions": pr_data.get("deletions", 0),
        "changed_files_count": pr_data.get("changed_files", 0),
    }


async def fetch_issue(owner: str, repo: str, number: int) -> dict:
    """Fetch issue content and comments (secondary use case)."""
    async with httpx.AsyncClient() as client:
        # Fetch issue metadata
        issue_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{number}",
            headers=_get_headers(),
            timeout=30.0,
        )
        issue_resp.raise_for_status()
        issue_data = issue_resp.json()
        
        # Fetch comments
        comments_resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{number}/comments",
            headers=_get_headers(),
            params={"per_page": 50},
            timeout=30.0,
        )
        comments_list = []
        if comments_resp.status_code == 200:
            comments_data = comments_resp.json()
            comments_list = [
                {
                    "author": c["user"]["login"],
                    "body": c["body"],
                }
                for c in comments_data
            ]
    
    return {
        "type": "issue",
        "owner": owner,
        "repo": repo,
        "number": number,
        "title": issue_data.get("title", ""),
        "body": issue_data.get("body") or "",
        "author": issue_data["user"]["login"],
        "state": issue_data.get("state", "open"),
        "labels": [l["name"] for l in issue_data.get("labels", [])],
        "comments": comments_list,
    }


def build_pr_context(data: dict) -> str:
    """Build a structured text representation of a PR for RLM input.
    
    Optimized for code review - includes full diff patches.
    """
    lines = [
        f"# Pull Request: {data['title']}",
        f"",
        f"**Repository:** {data['owner']}/{data['repo']}",
        f"**Author:** {data['author']}",
        f"**Branch:** {data['head_branch']} → {data['base_branch']}",
        f"**Changes:** +{data['additions']} -{data['deletions']} across {data['changed_files_count']} files",
        f"",
    ]
    
    # PR description
    if data["body"]:
        lines.extend([
            "## Description",
            "",
            data["body"],
            "",
        ])
    
    # Commits
    if data["commits"]:
        lines.extend([
            "## Commits",
            "",
        ])
        for commit in data["commits"]:
            lines.append(f"- `{commit['sha']}` {commit['message']} ({commit['author']})")
        lines.append("")
    
    # Changed files with patches
    lines.extend([
        "## Changed Files",
        "",
    ])
    
    for file in data["files"]:
        status_icon = {"added": "+", "removed": "-", "modified": "~"}.get(file["status"], "~")
        lines.append(f"### [{status_icon}] {file['path']}")
        lines.append(f"*+{file['additions']} -{file['deletions']}*")
        lines.append("")
        
        if file["patch"]:
            lines.append("```diff")
            lines.append(file["patch"])
            lines.append("```")
            lines.append("")
    
    # Comments/Discussion
    if data["comments"]:
        lines.extend([
            "## Discussion",
            "",
        ])
        for comment in data["comments"]:
            lines.append(f"**{comment['author']}:**")
            lines.append(comment["body"])
            lines.append("")
    
    return "\n".join(lines)


def build_issue_context(data: dict) -> str:
    """Build a text representation of an issue for RLM input."""
    lines = [
        f"# Issue: {data['title']}",
        f"",
        f"**Repository:** {data['owner']}/{data['repo']}",
        f"**Author:** {data['author']}",
        f"**State:** {data['state']}",
    ]
    
    if data["labels"]:
        lines.append(f"**Labels:** {', '.join(data['labels'])}")
    
    lines.append("")
    
    # Issue body
    if data["body"]:
        lines.extend([
            "## Description",
            "",
            data["body"],
            "",
        ])
    
    # Comments
    if data["comments"]:
        lines.extend([
            "## Discussion",
            "",
        ])
        for comment in data["comments"]:
            lines.append(f"**{comment['author']}:**")
            lines.append(comment["body"])
            lines.append("")
    
    return "\n".join(lines)


def build_review_context(data: dict) -> str:
    """Build a structured text representation for RLM input.
    
    Dispatches to PR or Issue context builder based on type.
    """
    if data["type"] == "pr":
        return build_pr_context(data)
    else:
        return build_issue_context(data)
